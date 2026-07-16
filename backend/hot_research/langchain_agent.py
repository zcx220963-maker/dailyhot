"""LangChain Agent — 交互式热榜问答。

使用 langgraph 的 create_react_agent（轻量、原生支持 async）。

Agent 流程:
  1. 读取用户问题
  2. 自行判断要查哪个平台（或请用户澄清）
  3. 调用工具获取原始热搜条目 + 爬取文章正文
  4. 返回带单条摘要的结构化 Markdown 报告
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Annotated

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.prebuilt import create_react_agent

logger = logging.getLogger(__name__)

# 只在用户首次提问时构建一次
_agent = None


def _get_langchain_llm():
    """获取项目里用作"快速 LLM"的实例，包装为 LangChain 聊天模型。"""
    import sys
    from pathlib import Path
    from dotenv import load_dotenv

    proj_root = Path(__file__).resolve().parent.parent.parent
    if str(proj_root) not in sys.path:
        sys.path.insert(0, str(proj_root))
    load_dotenv(proj_root / ".env", override=True)

    from gpt_researcher.config.config import Config
    from gpt_researcher.llm_provider.generic.base import GenericLLMProvider

    cfg = Config()
    cfg.verbose = False
    provider = GenericLLMProvider.from_provider(
        cfg.fast_llm_provider,
        model=cfg.fast_llm_model,
        temperature=0.3,
        stream_usage=False,
    )
    return provider.llm


def _build_agent():
    """构建 LangChain ReAct Agent（只在第一次调用 ask() 时执行）。"""
    from langchain_core.tools import tool

    from .daily_hot_api import (
        PLATFORMS,
        fetch_hot,
        find_related,
    )
    from .scraper import fetch_article_text

    # ---------- 工具函数的外层封装（langgraph 同步调用） ----------

    @tool
    def list_platforms() -> str:
        """列出所有支持的热榜平台（代码+名称）。"""
        lines = [f"  {c} — {n}" for c, n, _, _ in PLATFORMS]
        return "支持的平台:\n" + "\n".join(lines)

    @tool
    def fetch_platform_hot(platform_code: str, limit: int = 10) -> str:
        """获取某个平台的实时热搜榜。

        platform_code — 可选值: douyin, toutiao, thepaper, baidu, 36kr, sspai, v2ex, juejin, bilibili
        limit — 最多返回多少条（1-50）
        """
        items = fetch_hot(platform_code, max(1, min(limit, 50)))
        if not items:
            return f"无法获取 {platform_code} 的热搜数据"
        lines = []
        for i, it in enumerate(items, 1):
            t = it.get("title", "")
            h = it.get("hot", "")
            u = it.get("url", "")
            lines.append(f"{i}. {t}" + (f" 🔥{h}" if h else ""))
            if u:
                lines.append(f"   {u}")
        return "\n".join(lines)

    @tool
    def fetch_article(url: str) -> str:
        """爬取文章正文（只对文字网页有效，视频页面如抖音/B站会失败）。

        适用于 toutiao, 36kr, thepaper, v2ex, juejin, sspai 的链接。
        """
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            # 同步上下文无法 await，使用线程池
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(asyncio.run, fetch_article_text(url))
                text, title = fut.result(timeout=20)
        except Exception:
            # 回退到同步请求
            from hot_research.scraper import _bs_fetch
            text = _bs_fetch(url, 12)
            title = ""

        if not text:
            return "⚠️ 无法从该链接提取正文（可能是视频页面）"
        head = f"[{title}]\n" if title else ""
        return f"{head}{text[:2000]}"

    @tool
    def find_related_news(title: str, from_platform: str, limit: int = 3) -> str:
        """在另一个平台搜索与给定标题相关的新闻。

        当主要条目是视频（抖音/B站）时，用此工具在其他平台找文字报道。
        from_platform — toutiao, thepaper, 36kr, v2ex, juejin 等。
        """
        items = fetch_hot(from_platform, 50)
        related = find_related(title, items, max_results=limit)
        if not related:
            return f"在 {from_platform} 上未找到相关新闻"
        lines = []
        for r in related:
            t = r.get("title", "")
            u = r.get("url", "")
            h = r.get("hot", "")
            line = f"- {t}" + (f" 🔥{h}" if h else "")
            lines.append(line)
            if u:
                lines.append(f"  {u}")
        return "\n".join(lines)

    tools = [list_platforms, fetch_platform_hot, fetch_article, find_related_news]

    # ---------- 系统提示词 ----------
    system_prompt = """你是一个多平台热点资讯研究助手。所有输出必须使用中文，不要用英文。

支持的热榜平台: douyin（抖音）, toutiao（今日头条）, thepaper（澎湃新闻）, baidu（百度）, 36kr（36氪）, sspai（少数派）, v2ex（V2EX）, juejin（掘金）, bilibili（B站）

你有以下工具:
- list_platforms: 列出所有支持的平台
- fetch_platform_hot(code, limit): 获取某平台热搜
- fetch_article(url): 爬取文章正文（只对文字网页有效，视频页面会失败）
- find_related_news(title, platform, limit): 在另一个平台找相关新闻

★★★ 核心规则（不可违反）:
规则1: 用户没指定平台 → 必须拉取 ALL 9个平台 的数据
规则2: 用户指定了平台 → 除了该平台外，还要用其他平台的数据来补充和交叉验证

工作流程（严格遵守上述2条规则）:
1. 理解用户问题的核心需求
2. 识别用户是否指定了平台（如"抖音热点"→仅指定了douyin，"全网"或没提→未指定）
3. 根据规则决定要拉取哪些平台的数据:
   - 未指定 → fetch_platform_hot 逐个拉取全部 9 个平台
   - 已指定 → 拉取指定平台 + 其他所有平台做辅助
4. 对每条热点：
   a. 如果能爬文字（头条/澎湃/36kr/v2ex/juejin/sspai）用 fetch_article 爬正文
   b. 如果是视频页（抖音/B站）用 find_related_news 在头条/澎湃等平台找相关文字报道
   c. 始终用它平台数据做交叉引用（规则2）
5. 按用户需求格式生成报告

输出规则:
- 口播稿：每条100字左右，口语化，开场抓人，结尾互动
- 摘要：每条1-2句话说明核心信息
- 报告开头列出覆盖的所有平台名称
- 链接只附在末尾作为参考
- 所有思考、描述、标题必须使用中文
"""

    llm = _get_langchain_llm()
    agent = create_react_agent(
        llm,
        tools,
        prompt=system_prompt,
        debug=False,
    )
    return agent


async def ask(question: str) -> str:
    """主入口: 用户提出热榜相关问题，返回报告文本。"""
    global _agent
    if _agent is None:
        loop = asyncio.get_running_loop()
        _agent = await loop.run_in_executor(None, _build_agent)

    result = await _agent.ainvoke(
        {"messages": [HumanMessage(content=question)]},
        config={"recursion_limit": 20},
    )
    messages = result.get("messages", [])
    for m in reversed(messages):
        if isinstance(m, AIMessage) and m.content:
            return m.content
    return ""
