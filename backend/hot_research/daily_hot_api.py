"""从 DailyHotApi 获取热榜数据。"""
import io
import json
import os
import re
import sys
import logging
from typing import Optional
from pathlib import Path

import requests

# Windows 终端编码修复
if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("DAILY_HOT_API_BASE_URL", "https://dailyhotapi.vercel.app")

# 每条: (平台代码, 显示名称, 默认抓取数量, 是否可爬取正文)
# text_readable=True  → 对应 URL 是普通网页，BeautifulSoup 可以提取正文
# text_readable=False → 对应 URL 是视频或 JS 渲染页面，爬虫基本无法获取内容
PLATFORMS = [
    ("douyin",   "抖音",     50, False),
    ("toutiao",  "今日头条", 50, True),
    ("thepaper", "澎湃新闻", 20, True),
    ("baidu",    "百度",     20, True),
    ("36kr",     "36氪",     30, True),
    ("sspai",    "少数派",   20, True),
    ("v2ex",     "V2EX",     20, True),
    ("juejin",   "掘金",     20, True),
    ("bilibili", "B站",      30, False),
]

# 平台名称 → 代码，用于反向匹配用户输入中的关键词
PLATFORM_NAME_MAP = {}
for _code, _name, _, _ in PLATFORMS:
    PLATFORM_NAME_MAP[_code] = _code
    PLATFORM_NAME_MAP[_name] = _code


def _proxy() -> dict:
    """读取 .env 中的代理配置，返回 requests 可用的 proxies 字典。"""
    proxies = {}
    for k in ("http", "https"):
        v = os.getenv(f"{k.upper()}_PROXY") or os.getenv(f"{k}_proxy")
        if v:
            proxies[k] = v
    return proxies


def _fetch_baidu_hot(limit: int = 30) -> list[dict]:
    """百度官方实时热搜（解析 HTML 中的 s-data JSON）。

    DailyHotApi 的 /baidu 接口数据损坏（乱码、仅1条），
    改用官方页面 https://top.baidu.com/board?tab=realtime
    """
    import re
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(
            "https://top.baidu.com/board?tab=realtime",
            headers=headers, timeout=15, proxies=_proxy()
        )
        scripts = re.findall(r"<!--s-data:(.*?)-->", resp.text, re.DOTALL)
        if not scripts:
            return []
        data = json.loads(scripts[0])
        content = data["data"]["cards"][0]["content"]
        result = []
        for it in content[:limit]:
            word = it.get("word") or it.get("query", "")
            score = it.get("hotScore", 0)
            url = it.get("url") or f"https://www.baidu.com/s?wd={word}"
            result.append({"title": word, "hot": score, "url": url})
        return result
    except Exception as e:
        logger.warning(f"_fetch_baidu_hot: {e}")
        return []


def _fetch_bilibili_square(limit: int = 30) -> list[dict]:
    """B站官方实时热搜接口（search/square）。

    DailyHotApi 对 B站返回的是热门视频而非热搜关键词，
    所以 B站单独走官方接口: https://api.bilibili.com/x/web-interface/search/square
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(
            f"https://api.bilibili.com/x/web-interface/search/square?limit={limit}",
            headers=headers, timeout=15, proxies=_proxy()
        )
        data = resp.json()
        if data.get("code") != 0:
            return []
        items = data.get("data", {}).get("trending", {}).get("list", [])
        result = []
        for it in items:
            keyword = it.get("keyword") or it.get("show_name", "")
            url = f"https://search.bilibili.com/all?keyword={keyword}"
            result.append({
                "title": it.get("show_name") or keyword,
                "hot": it.get("heat_score", 0),
                "url": url,
                "keyword": keyword,
            })
        return result[:limit]
    except Exception as e:
        logger.warning(f"_fetch_bilibili_square: {e}")
        return []


def fetch_hot(platform_code: str, limit: int = 50) -> list[dict]:
    """获取单个平台的原始热搜列表。

    每个元素包含 title / hot / url 等字段。
    对瞬时网络/API 错误自动重试 2 次（指数退避）。
    """
    limit = limit or 50
    # B站和百度走官方实时热搜接口（DailyHotApi 对这两个平台数据不准确）
    if platform_code == "bilibili":
        return _fetch_bilibili_square(limit)
    if platform_code == "baidu":
        return _fetch_baidu_hot(limit)
    last_err: Exception | None = None
    for attempt in range(3):          # 1 次原始 + 2 次重试
        try:
            resp = requests.get(
                f"{BASE_URL}/{platform_code}",
                timeout=15,
                proxies=_proxy(),
            )
            data = resp.json()
            if data.get("code") == 200 or "data" in data:
                items = data.get("data", [])
                # 统一字段名，方便下游使用
                for it in items:
                    if "url" not in it:
                        it["url"] = it.get("mobileUrl", "")
                return items[:limit]
        except Exception as e:
            last_err = e
            logger.warning(
                "fetch_hot(%s) 第%d次失败: %s%s",
                platform_code,
                attempt + 1,
                e,
                "（将重试）" if attempt < 2 else "",
            )
            import time
            time.sleep(1 * (attempt + 1))   # 1s, 2s 退避
    logger.warning(f"fetch_hot({platform_code}) 最终失败: {last_err}")
    return []


def fetch_all(limit_per_platform: Optional[dict[str, int]] = None) -> dict[str, list]:
    """抓取所有平台的热搜列表。返回 {平台代码: [条目列表]}。"""
    limit_per_platform = limit_per_platform or {}
    result = {}
    for code, name, default_n, _ in PLATFORMS:
        n = limit_per_platform.get(code, default_n)
        items = fetch_hot(code, n)
        result[code] = items
        logger.info(f"  {name}: {len(items)} 条")
    return result


def detect_platforms_in_query(query: str) -> list[str]:
    """检测用户问题中提到了哪些平台（匹配中文名或英文代码）。

    返回命中平台代码的列表。
    """
    q = query.lower()
    hits = []
    for code, name, _, _ in PLATFORMS:
        if name.lower() in q or code.lower() in q:
            hits.append(code)
    return hits


def get_supported_platforms() -> list[dict]:
    """返回所有支持的平台及其可读性标志（前端下拉列表等用途）。"""
    return [
        {"code": c, "name": n, "readable": r}
        for c, n, _, r in PLATFORMS
    ]


# ---------------------------------------------------------------------------
# Embedding 语义匹配（替代旧的字符串重叠匹配）
# ---------------------------------------------------------------------------

_embedding_model = None  # 模块级缓存


class _OllamaEmbeddings:
    """通过 Ollama HTTP 接口获取 embedding 向量（不依赖 langchain_ollama）。

    使用 /api/embed 端点（Ollama 0.1.34+），单次请求可传多个文本。
    """

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def _embed(self, texts: list[str]) -> list[list[float]]:
        import urllib.request
        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        embeddings = body.get("embeddings", [])
        if not embeddings:
            raise ValueError("Ollama /api/embed 返回空 embeddings")
        return embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量获取多条文本的 embedding。"""
        if not texts:
            return []
        # Ollama 单次请求过多文本可能 OOM，分批（每批 32 条）
        batch_size = 32
        all_vecs: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            all_vecs.extend(self._embed(batch))
        return all_vecs

    def embed_query(self, text: str) -> list[float]:
        """获取单条文本的 embedding。"""
        return self.embed_documents([text])[0]


def _get_embedding_model():
    """懒加载 LangChain embedding 模型（首次调用时初始化）。"""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = _build_embedding_model()
    return _embedding_model


def _build_embedding_model():
    """根据 .env 配置构建 LangChain Embeddings 实例。"""
    # 读取配置
    provider = os.getenv("EMBEDDING_PROVIDER", "openai").lower()
    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    api_key = os.getenv("OPENAI_API_KEY", "")

    try:
        if provider == "openai":
            from langchain_openai import OpenAIEmbeddings
            kwargs = {"model": model}
            if api_key:
                kwargs["api_key"] = api_key
            # 支持自定义 base_url（如用 LongCat 代理）
            base_url = os.getenv("OPENAI_BASE_URL", "")
            if base_url:
                kwargs["base_url"] = base_url
            return OpenAIEmbeddings(**kwargs)

        if provider == "ollama":
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
            # 自动检测本地是否有 bge-m3（中文优化 embedding）
            chosen = model
            try:
                import urllib.request
                req = urllib.request.Request(f"{base_url}/api/tags")
                resp = urllib.request.urlopen(req, timeout=5)
                tags = json.loads(resp.read().decode())
                local_models = [m.get("model", "").split(":")[0] for m in tags.get("models", [])]
                if "bge-m3" in local_models and "bge-m3" not in model:
                    chosen = "bge-m3"
                    logger.info(f"Ollama embedding: 自动选择 bge-m3（中文优化）")
            except Exception:
                pass
            return _OllamaEmbeddings(base_url=base_url, model=chosen)

        if provider == "huggingface":
            from langchain_huggingface import HuggingFaceEmbeddings
            return HuggingFaceEmbeddings(model_name=model)

        # 默认 fallback 到 openai
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(model=model, api_key=api_key or None)

    except ImportError as e:
        logger.warning(f"Embedding 依赖缺失 ({provider}): {e}")
        return None
    except Exception as e:
        logger.warning(f"Embedding 模型初始化失败: {e}")
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _fallback_find_related(title: str, items: list[dict], max_results: int = 3) -> list[dict]:
    """回退：字符串重叠匹配（当 embedding 不可用时）。"""
    def normalize(t: str) -> str:
        return re.sub(r'[^一-鿿]', '', t)

    def max_overlap(a: str, b: str) -> int:
        best = 0
        for s in range(len(a)):
            for e in range(s + 2, min(s + 8, len(a) + 1)):
                if a[s:e] in b:
                    best = max(best, e - s)
        return best

    norm = normalize(title)
    if len(norm) < 3:
        return []
    related = []
    for it in items:
        it_norm = normalize(it.get("title", ""))
        if not it_norm:
            continue
        if max_overlap(norm, it_norm) >= 3:
            related.append(it)
        if len(related) >= max_results:
            break
    return related


def find_related(title: str, items: list[dict], max_results: int = 3) -> list[dict]:
    """在另一平台的热搜中寻找相关条目。

    优先使用 embedding 向量语义匹配（余弦相似度）；
    embedding 不可用时回退到字符串重叠匹配。
    """
    if not items:
        return []

    # 尝试 embedding 语义匹配
    embedder = _get_embedding_model()
    if embedder is not None:
        try:
            # 批量计算所有标题的 embedding
            all_titles = [title] + [it.get("title", "") for it in items]
            embeddings = embedder.embed_documents(all_titles)
            query_vec = embeddings[0]
            item_vecs = embeddings[1:]

            # 计算余弦相似度并排序
            scored: list[tuple[float, int]] = []
            for i, vec in enumerate(item_vecs):
                sim = _cosine_similarity(query_vec, vec)
                scored.append((sim, i))
            scored.sort(key=lambda x: x[0], reverse=True)

            # 取相似度 > 0.5 的前 max_results 个
            related = []
            for sim, idx in scored:
                if sim < 0.5:
                    break
                related.append(items[idx])
                if len(related) >= max_results:
                    break
            if related:
                return related
        except Exception as e:
            logger.warning(f"Embedding 匹配失败，回退到字符串匹配: {e}")

    # 回退
    return _fallback_find_related(title, items, max_results)
