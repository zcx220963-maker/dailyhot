"""统一意图识别 Agent —— 单个 LangChain chain，替代所有散落的关键词匹配。

统一为一个结构化 LLM 调用，输出:
  {
    "is_hot_list": true/false,
    "primary_codes": ["douyin", "toutiao"],  // 用户关注的平台（主干）
    "category": "entertainment"/"tech"/"news"/"all",  // 内容分类过滤
    "confidence": 0.9  // 意图置信度
  }

使用 LangChain ChatPromptTemplate → llm → JSON 解析，无需 ReAct（单次调用即可）。
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 平台元数据（与 daily_hot_api.PLATFORMS 保持一致）
# ---------------------------------------------------------------------------

PLATFORMS_META = [
    {"code": "douyin",   "name": "抖音",     "aliases": ["抖音", "douyin", "tiktok"]},
    {"code": "toutiao",  "name": "今日头条", "aliases": ["头条", "今日头条", "toutiao"]},
    {"code": "thepaper", "name": "澎湃新闻", "aliases": ["澎湃", "澎湃新闻", "thepaper"]},
    {"code": "baidu",    "name": "百度",     "aliases": ["百度", "baidu", "百度热搜"]},
    {"code": "36kr",     "name": "36氪",     "aliases": ["36氪", "36kr", "三十六氪"]},
    {"code": "sspai",    "name": "少数派",   "aliases": ["少数派", "sspai"]},
    {"code": "v2ex",     "name": "V2EX",     "aliases": ["v2ex", "V2EX"]},
    {"code": "juejin",   "name": "掘金",     "aliases": ["掘金", "juejin"]},
    {"code": "bilibili", "name": "B站",      "aliases": ["b站", "B站", "哔哩哔哩", "bilibili", "bili"]},
]

VALID_CODES = {p["code"] for p in PLATFORMS_META}


# ---------------------------------------------------------------------------
# 系统提示词
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """你是一个热榜意图识别助手。根据用户查询，判断是否需要生成热榜报告，并识别用户关注的平台。

## 平台列表
- douyin（抖音）: 短视频平台
- toutiao（今日头条）: 综合新闻
- thepaper（澎湃新闻）: 深度新闻
- baidu（百度）: 搜索热搜
- 36kr（36氪）: 科技创投
- sspai（少数派）: 数字生活
- v2ex（V2EX）: 技术社区
- juejin（掘金）: 开发者社区
- bilibili（B站）: 视频社区

## 判断规则

### is_hot_list = true 的情况（热榜意图）：
- 明确提到"热榜/热搜/热点/热门/热文/热帖/trending"
- 提到具体平台名（如"抖音热门"、"今日头条新闻"、"B站视频"）
- 提到"今日/今天/最新" + 平台名/内容领域
- 提到"娱乐新闻"、"科技热点"、"互联网圈"等泛内容领域（这些都可以从热榜平台获取）
- 提到"什么火"、"什么热门"、"最近在聊什么"等探索性热榜查询

### is_hot_list = false 的情况（非热榜意图）：
- 具体事实查询（"什么是区块链"、"今天天气"）
- 需要深度研究的课题（"AI 对教育的影响"）
- 个人事务（"帮我写封邮件"）
- 历史事件（"2008年金融危机原因"）

### primary_codes（主干平台）：
- 用户指定了平台 → 只列这些平台
- 用户说泛内容（如"科技热点"）→ 选最相关的 1-3 个平台（如 36kr, v2ex, juejin）
- 用户说"今日热榜"/"热搜报告"等无特指 → 返回空列表（表示全平台）
- 用户说"娱乐新闻" → 选娱乐内容丰富的平台（如 douyin, toutiao, bilibili）

### category（内容分类）：
- 用户明确提到领域时分类：entertainment / tech / finance / sports / gaming / news / all
- 无法确定时返回 "all"

## 输出格式
严格输出 JSON，不要 markdown 代码块，不要其他文字：
{"is_hot_list": true/false, "primary_codes": ["code1", "code2"], "category": "xxx", "confidence": 0.0-1.0}

## 示例
输入: "生成今日抖音热榜报告"
输出: {"is_hot_list": true, "primary_codes": ["douyin"], "category": "all", "confidence": 0.95}

输入: "今天娱乐新闻"
输出: {"is_hot_list": true, "primary_codes": ["douyin", "toutiao", "bilibili"], "category": "entertainment", "confidence": 0.85}

输入: "科技圈最近什么热门"
输出: {"is_hot_list": true, "primary_codes": ["36kr", "v2ex", "juejin"], "category": "tech", "confidence": 0.8}

输入: "今日热榜"
输出: {"is_hot_list": true, "primary_codes": [], "category": "all", "confidence": 0.9}

输入: "什么是量子计算"
输出: {"is_hot_list": false, "primary_codes": [], "category": "all", "confidence": 0.95}

输入: "今天天气怎么样"
输出: {"is_hot_list": false, "primary_codes": [], "category": "all", "confidence": 0.9}
"""


# ---------------------------------------------------------------------------
# LLM 工厂（复用 hot_list_agent 的）
# ---------------------------------------------------------------------------

_llm_instance = None


def _get_llm():
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance
    try:
        from backend.hot_research.hot_list_agent import _get_langchain_llm
        _llm_instance = _get_langchain_llm()
    except ImportError:
        # 回退：本地创建
        from dotenv import load_dotenv
        from gpt_researcher.config.config import Config
        from gpt_researcher.llm_provider.generic.base import GenericLLMProvider

        proj_root = Path(__file__).resolve().parent.parent.parent
        if str(proj_root) not in sys.path:
            sys.path.insert(0, str(proj_root))
        load_dotenv(proj_root / ".env", override=True)

        cfg = Config()
        cfg.verbose = False
        provider = GenericLLMProvider.from_provider(
            cfg.fast_llm_provider,
            model=cfg.fast_llm_model,
            temperature=0.2,
            stream_usage=False,
        )
        _llm_instance = provider.llm
    return _llm_instance


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def recognize_intent(query: str) -> dict:
    """统一意图识别入口。

    Args:
        query: 用户原始查询

    Returns:
        {
            "is_hot_list": bool,
            "primary_codes": list[str],  // 空列表 = 全平台
            "category": str,
            "confidence": float,
        }
    """
    default = {"is_hot_list": False, "primary_codes": [], "category": "all", "confidence": 0.0}

    try:
        llm = _get_llm()
        prompt = ChatPromptTemplate.from_messages([
            ("system", _SYSTEM_PROMPT),
            ("human", "用户查询：{query}\n\n输出 JSON："),
        ])
        chain = prompt | llm | StrOutputParser()
        raw = await chain.ainvoke({"query": query})
        result = _parse_intent_json(raw)
        if result:
            logger.info(f"[IntentAgent] '{query[:40]}' → is_hot_list={result['is_hot_list']}, "
                         f"primary={result['primary_codes']}, category={result['category']}")
            return result
    except Exception as e:
        logger.warning(f"[IntentAgent] LLM 调用失败: {e}，回退到关键词匹配")

    # 回退：关键词匹配
    return _fallback_keyword_match(query)


def _parse_intent_json(raw: str) -> Optional[dict]:
    """从 LLM 输出中解析 JSON。"""
    if not raw:
        return None
    # 去掉可能的 markdown 代码块
    text = raw.strip()
    if text.startswith("```"):
        # ```json ... ```  → 提取中间
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
    # 找第一个 { ... }
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
        # 校验 + 清洗
        is_hot = bool(data.get("is_hot_list", False))
        codes = data.get("primary_codes", [])
        if not isinstance(codes, list):
            codes = []
        # 过滤无效代码
        codes = [c for c in codes if c in VALID_CODES]
        category = data.get("category", "all")
        confidence = float(data.get("confidence", 0.5))
        return {
            "is_hot_list": is_hot,
            "primary_codes": codes,
            "category": category,
            "confidence": confidence,
        }
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"[IntentAgent] JSON 解析失败: {e}, raw={raw[:200]}")
        return None


def _fallback_keyword_match(query: str) -> dict:
    """回退：关键词匹配（当 LLM 不可用时）。"""
    q = query.lower()
    # 热榜关键词
    hot_keywords = ["热榜", "热搜", "热点", "热门", "热文", "热帖",
                    "trending", "hot list", "top search", "今日要闻", "今日热点",
                    "什么火", "什么热门", "最近在聊", "娱乐新闻", "科技热点"]
    is_hot = any(kw in q for kw in hot_keywords)

    # 平台匹配
    codes = []
    for p in PLATFORMS_META:
        for alias in p["aliases"]:
            if alias.lower() in q:
                if p["code"] not in codes:
                    codes.append(p["code"])
                break

    return {"is_hot_list": is_hot, "primary_codes": codes, "category": "all", "confidence": 0.6}
