"""
今日热榜 (DailyHotApi) Retriever for GPT Researcher

Aggregates hot trending data from 40+ Chinese platforms including:
微博、知乎、B站、抖音、百度、今日头条、36氪、V2EX、NGA, etc.

Uses LLM-based intent recognition to dynamically select the right platforms
for each user query — no hardcoded keyword mapping required.

API Docs: https://github.com/imsyy/DailyHotApi
"""

import os
import json
import ssl
import asyncio
import urllib3
import requests
from typing import Any, Dict, List, Optional

# Disable SSL warnings for compatibility with proxies
urllib3.disable_warnings()

# All supported platforms from DailyHotApi
SUPPORTED_PLATFORMS = [
    "bilibili", "acfun", "weibo", "zhihu", "zhihu-daily",
    "baidu", "douyin", "kuaishou", "douban-movie",
    "douban-group", "tieba", "sspai", "ithome", "ithome-xijiayi",
    "jianshu", "guokr", "thepaper", "toutiao", "36kr",
    "51cto", "csdn", "nodeseek", "juejin", "qq-news",
    "sina", "sina-news", "netease-news", "52pojie", "hostloc",
    "huxiu", "coolapk", "hupu", "ifanr", "lol",
    "miyoushe", "genshin", "honkai", "starrail",
    "weread", "ngabbs", "v2ex", "hellogithub",
    "weatheralarm", "earthquake", "history",
]

# Platform display names for mapping query intent
PLATFORM_NAMES = {
    "bilibili": "B站", "acfun": "AcFun", "weibo": "微博",
    "zhihu": "知乎", "zhihu-daily": "知乎日报",
    "baidu": "百度", "douyin": "抖音", "kuaishou": "快手",
    "douban-movie": "豆瓣电影", "douban-group": "豆瓣讨论小组",
    "tieba": "百度贴吧", "sspai": "少数派", "ithome": "IT之家",
    "jianshu": "简书", "guokr": "果壳", "thepaper": "澎湃新闻",
    "toutiao": "今日头条", "36kr": "36氪", "juejin": "掘金",
    "v2ex": "V2EX", "ngabbs": "NGA", "hupu": "虎扑",
    "netease-news": "网易新闻", "huxiu": "虎嗅",
    "tencent-news": "腾讯新闻",
}


class DailyHotApi:
    """
    今日热榜 API Retriever - 从 40+ 平台获取热点数据
    """

    def __init__(self, query: str, query_domains=None):
        self.query = query
        self.base_url = os.getenv(
            "DAILY_HOT_API_BASE_URL", "https://dailyhotapi.vercel.app"
        )
        self.timeout = int(os.getenv("DAILY_HOT_API_TIMEOUT", "15"))

        # Configure proxy (uses system proxy by default)
        self.proxies = {}
        http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
        https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
        if http_proxy:
            self.proxies["http"] = http_proxy
        if https_proxy:
            self.proxies["https"] = https_proxy

        # Platforms to query (from env or default list)
        # Queries ALL platforms by default since each returns compact data.
        platforms_env = os.getenv("DAILY_HOT_API_PLATFORMS", "")
        if platforms_env.strip():
            self.platforms = [
                p.strip() for p in platforms_env.split(",") if p.strip()
            ]
        else:
            # Use the verified-working platforms as default
            self.platforms = [
                "bilibili", "toutiao", "baidu", "douyin", "36kr",
                "v2ex", "ngabbs", "juejin", "sspai",
            ]

    def _get_session(self) -> requests.Session:
        """
        Create a requests session with optimized SSL/TLS settings.
        Handles proxy compatibility issues with strict TLS servers.
        """
        session = requests.Session()

        # Configure retry strategy
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
        )

        # Optimize SSL context to handle proxy TLS issues
        class SSLAdapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                ctx.set_ciphers("DEFAULT@SECLEVEL=1")
                kwargs["ssl_context"] = ctx
                return super().init_poolmanager(*args, **kwargs)

        ssl_adapter = SSLAdapter(max_retries=retry)
        session.mount("https://", ssl_adapter)
        session.mount("http://", ssl_adapter)

        # Set proxies
        if self.proxies:
            session.proxies.update(self.proxies)

        return session

    def _fetch_platform(self, platform: str) -> Optional[Dict[str, Any]]:
        """
        Fetch hot items from a single platform.
        """
        url = f"{self.base_url}/{platform}"
        try:
            session = self._get_session()
            resp = session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == 200 or "data" in data:
                return data
            return None
        except Exception as e:
            if os.getenv("VERBOSE", "").lower() in ("true", "1"):
                print(f"[DailyHotApi] Failed to fetch {platform}: {e}")
            return None

    def search(self, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Query ALL platforms concurrently, then return formatted results.

        The user's query is preserved in self.query — the downstream LLM
        (LongCat) will handle all intent filtering, ranking and merge.

        Each platform returns compact hot-list items (title + url + heat),
        so querying all ~20 platforms is still fast (~2-3s total).
        """
        import concurrent.futures

        # All platforms to query concurrently
        platforms = self.platforms[:20]

        # Fetch multiple platforms in parallel (3 at a time)
        all_items: List[Dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_map = {
                executor.submit(self._fetch_platform, p): p
                for p in platforms
            }
            for future in concurrent.futures.as_completed(future_map):
                platform_name_raw = future_map[future]
                try:
                    data = future.result()
                except Exception:
                    data = None
                if not data or "data" not in data:
                    continue

                platform_name = PLATFORM_NAMES.get(
                    platform_name_raw, platform_name_raw
                )
                items = data.get("data", [])
                if not items:
                    continue

                for i, item in enumerate(items[:5]):
                    title = item.get("title", "")
                    url = item.get("url", item.get("mobileUrl", ""))
                    hot = item.get("hot", "")
                    desc = item.get("desc", "")

                    # Fix URLs missing the https scheme (e.g. tieba returns
                    # "//tieba.baidu.com/..." instead of "https://...")
                    if url and url.startswith("//"):
                        url = "https:" + url
                    # Drop SPA / video pages that can't yield meaningful text
                    # (douyin hot page, kuaishou short-video page, etc.) — but
                    # keep the trending title + heat as signal.
                    unscrapable = (
                        "douyin.com/hot/" in url
                        or "kuaishou.com/short-video/" in url
                    )

                    # Build context-rich content
                    content_parts = [
                        f"【{platform_name}热榜第{i + 1}名】"
                    ]
                    if title:
                        content_parts.append(f"标题：{title}")
                    if desc:
                        content_parts.append(f"摘要：{desc}")
                    if hot:
                        content_parts.append(f"热度：{hot}")
                    if unscrapable:
                        content_parts.append(
                            "（该平台为视频/SPA页面，仅提供标题与热度数据）"
                        )

                    # Only include a URL if it points to a scrapable page.
                    # Video/SPA pages get a placeholder so downstream
                    # scrape_urls will skip them (saves time, avoids 5MB JS).
                    final_url = (
                        url
                        if url and not unscrapable
                        else f"https://www.{platform_name_raw.replace('-', '')}.com"
                    )

                    all_items.append(
                        {
                            "url": final_url,
                            "title": title or f"{platform_name}热点",
                            "raw_content": "\n".join(content_parts),
                        }
                    )

        return all_items


    async def research(self, query: str = None) -> str:
        """
        Full research pipeline optimized for hot-trending data.

        Bypasses the default search→scrape→compress flow because
        hot-list data is already condensed (title + heat per item).

        Returns a query-aware summary ready for report generation.
        """
        # 1. Fetch hot data from all platforms
        items = self.search(max_results=60)
        if not items:
            return ""

        # 2. Format as structured context for LLM
        platform_groups: Dict[str, List[str]] = {}
        for item in items:
            raw = item.get("raw_content", "")
            title = item.get("title", "")
            # Extract platform from raw_content
            platform = "其他"
            for eng, zh in PLATFORM_NAMES.items():
                if zh in raw:
                    platform = zh
                    break
            platform_groups.setdefault(platform, []).append(title)

        # 3. Build structured summary
        lines = [f"# 全网热榜数据（共{len(items)}条）\n"]
        for platform, titles in platform_groups.items():
            lines.append(f"\n## {platform}热榜")
            for i, title in enumerate(titles[:8], 1):
                lines.append(f"  {i}. {title}")

        raw_context = "\n".join(lines)

        # 4. Use LLM to filter/rank based on query
        try:
            from gpt_researcher.utils.llm import create_chat_completion

            filter_prompt = f"""你是一个信息筛选助手。以下是抓取到的全网热榜数据：

{raw_context}

用户的问题：「{query or self.query}」

请完成：
1. 从上述热榜中挑选出与用户问题最相关的 10-15 条
2. 按重要性排序
3. 对每条用一句话说明为什么它和用户问题相关

输出格式（JSON）：
[{{"platform": "平台名", "title": "标题", "relevance": "相关性说明"}}]"""

            result = await create_chat_completion(
                model=os.getenv("FAST_LLM_MODEL", "LongCat-2.0"),
                llm_provider=os.getenv("FAST_LLM_PROVIDER", "openai"),
                messages=[{"role": "user", "content": filter_prompt}],
                temperature=0.3,
                max_tokens=2000,
            )
            return result.strip()
        except Exception as e:
            # If LLM filter fails, return raw context
            return raw_context


if __name__ == "__main__":
    import asyncio

    async def test():
        retriever = DailyHotApi("今天AI和科技热点新闻")
        result = await retriever.research()
        print(result[:2000])

    asyncio.run(test())
