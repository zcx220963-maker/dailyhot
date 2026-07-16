"""多平台热榜报告生成器。

核心设计（主干 + 辅助分层）：
- 主干：用户指定的平台（如 "B站", "抖音"）→ 全量 TOP N 逐条分析，每条占报告一个小节
- 辅助：其他平台 → 不单独分析，用 find_related() 为每条主干热搜找相关条目作为补充素材
- 数据全来自 pre-fetch 的热榜 API，不走 web search / conduct_research()

主干平台由上游 intent_agent 识别后传入，本模块不再做关键词匹配。
"""
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import WebSocket

# 确保 backend/ 目录在 sys.path 上，以便 import hot_research / gpt_researcher
# __file__ = .../gpt-researcher/backend/report_type/hot_list_report/hot_list_report.py
# parent^3 = .../gpt-researcher/backend/
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
# 同时确保项目根目录在 path 上（gpt_researcher 包需要）
_PROJECT_ROOT = _BACKEND_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hot_research.daily_hot_api import (  # noqa: E402
    PLATFORMS,
    PLATFORM_NAME_MAP,
    fetch_hot,
    find_related,
)
from hot_research.scraper import fetch_article_text  # noqa: E402

from gpt_researcher.actions.utils import stream_output  # noqa: E402

# LangChain 组件 — 全链路统一 LLM 调用
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM 实例化（统一用 LangChain 风格，复用 langchain_agent.py 的工厂）
# ---------------------------------------------------------------------------

_llm_instance = None  # 模块级缓存，避免重复创建


def _get_llm():
    """获取 LangChain 聊天模型实例（带缓存）。

    优先复用 hot_list_agent.py 的工厂，失败则回退到本地创建。
    """
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

        proj_root = Path(__file__).resolve().parent.parent.parent.parent
        if str(proj_root) not in sys.path:
            sys.path.insert(0, str(proj_root))
        load_dotenv(proj_root / ".env", override=True)

        cfg = Config()
        cfg.verbose = False
        provider = GenericLLMProvider.from_provider(
            cfg.fast_llm_provider,
            model=cfg.fast_llm_model,
            temperature=0.3,
            stream_usage=False,
        )
        _llm_instance = provider.llm

    return _llm_instance


# ---------------------------------------------------------------------------
# HotListReport 类
# ---------------------------------------------------------------------------

class HotListReport:
    """多平台热榜报告生成器（主干 + 辅助分层）。"""

    def __init__(
        self,
        query: str,
        all_raw_data: dict[str, list[dict]],
        primary_codes: list[str],
        websocket: WebSocket,
        tone: Any = None,
        config_path: str = "default",
        max_text_items: int = 50,
    ):
        """
        Args:
            query: 用户原始查询
            all_raw_data: {平台代码: [{title, hot, url}, ...]} 所有9平台的原始数据
            primary_codes: 主干平台代码列表（由 intent_agent 识别后传入）
            websocket: 前端 WebSocket 推送对象（通常是 CustomLogsHandler）
            tone: 语气枚举（保留接口兼容）
            config_path: 配置文件路径
            max_text_items: 每个主干平台最多分析前 N 条
        """
        self.query = query
        self.all_raw_data = all_raw_data
        self.primary_codes = primary_codes
        self.websocket = websocket
        self.tone = tone
        self.config_path = config_path
        self.max_text_items = max_text_items

    async def run(self) -> str:
        """执行完整的主干+辅助分析流程，返回 Markdown 报告。

        LLM 调用使用异步并行（	asyncio.gather + Semaphore 限流 5 并发），
        大幅加速多平台多词条场景。
        """
        # 如果未指定主干，默认全部9平台都是主干
        primary_codes = self.primary_codes
        if not primary_codes:
            primary_codes = [p[0] for p in PLATFORMS]

        # 辅助平台 = 非主干
        supplementary_codes = [p[0] for p in PLATFORMS if p[0] not in primary_codes]

        # 主干条目总数（进度条用）
        total_primary_items = sum(
            len(self.all_raw_data.get(c, [])[: self.max_text_items]) for c in primary_codes
        )

        # 播报开始
        primary_names = [PLATFORM_NAME_MAP.get(c, c) for c in primary_codes]
        supp_names = [PLATFORM_NAME_MAP.get(c, c) for c in supplementary_codes]

        await stream_output(
            "logs", "hot_start",
            f"🔥 热榜报告生成中（并行 30 线程）\n"
            f"   主干平台: {', '.join(primary_names)}（共 {total_primary_items} 条）\n"
            f"   辅助平台: {', '.join(supp_names) if supp_names else '无（全是主干）'}（用 find_related 匹配相关条目）",
            self.websocket, True,
        )

        # ---- 第一阶段：I/O 密集（爬文章正文），可高度并发 ----
        tasks_meta: list[dict] = []

        # 辅助平台哪些可读（能爬正文）
        readable_supplementary = [
            sc for sc in supplementary_codes
            if next((p[3] for p in PLATFORMS if p[0] == sc), True)
        ]

        for code in primary_codes:
            items = self.all_raw_data.get(code, [])[: self.max_text_items]
            platform_name = PLATFORM_NAME_MAP.get(code, code)
            is_readable = next((p[3] for p in PLATFORMS if p[0] == code), True)

            for i, item in enumerate(items, 1):
                title = item.get("title", "")
                hot = item.get("hot", "")
                url = item.get("url", "")
                if not title:
                    continue

                tasks_meta.append({
                    "platform_name": platform_name,
                    "rank": i,
                    "title": title,
                    "hot": hot,
                    "url": url,
                    "text": item.get("text", ""),  # MCP 工具返回的正文
                    "is_readable": is_readable,
                    "supplementary_codes": supplementary_codes,
                    "readable_supplementary": readable_supplementary,
                    "all_raw_data_ref": self.all_raw_data,
                })

        # ---- 第一阶段 A：纯 CPU 匹配（find_related，无 I/O）----
        # 同时收集"需要爬正文"的 (meta_index, url, label) 列表
        fetch_jobs: list[tuple[int, str, str]] = []  # (meta_idx, url, label)

        for idx, meta in enumerate(tasks_meta):
            # 自身正文（可读平台）
            if meta["is_readable"] and meta.get("url"):
                fetch_jobs.append((idx, meta["url"], "__self__"))

            # 辅助平台 find_related 匹配
            for sc in meta["readable_supplementary"]:
                sc_name = PLATFORM_NAME_MAP.get(sc, sc)
                sc_items = meta["all_raw_data_ref"].get(sc, [])
                if not sc_items:
                    continue
                try:
                    matches = find_related(
                        meta["title"], sc_items, max_results=2
                    )
                except Exception:
                    continue
                for r in matches:
                    rurl = r.get("url", "")
                    rt = r.get("title", "")
                    label = f"[{sc_name}相关报道] {rt}"
                    meta.setdefault("_related_labels", []).append(label)
                    if rurl:
                        fetch_jobs.append((idx, rurl, label))

        # ---- 第一阶段 B：并发爬取所有需要的正文（Semaphore 限流 30）----
        scrape_semaphore = asyncio.Semaphore(30)
        scrape_cache: dict[str, str] = {}  # url → text，避免重复爬

        async def _scrape_one(url: str) -> str:
            if url in scrape_cache:
                return scrape_cache[url]
            async with scrape_semaphore:
                try:
                    text, _ = await fetch_article_text(url)
                    text = text or ""
                except Exception as e:
                    logger.debug(f"fetch_article_text 失败: {e}")
                    text = ""
                scrape_cache[url] = text
                return text

        # 去重后并发爬取
        unique_urls = list({job[1] for job in fetch_jobs})
        logger.info(f"[HotListReport] 需要爬取 {len(unique_urls)} 个唯一 URL 的正文（{len(fetch_jobs)} 次引用）")
        await asyncio.gather(*[_scrape_one(u) for u in unique_urls])

        # 分配结果回 tasks_meta
        for idx, m in enumerate(tasks_meta):
            m["material"] = scrape_cache.get(m.get("url", ""), "") if m["is_readable"] else ""
            m["related_materials"] = []
            for label in m.get("_related_labels", []):
                # 找对应的 url：重新在 fetch_jobs 里查
                pass  # 下面统一填充

        # 重新遍历 fetch_jobs 按 meta_idx 填充 related_materials
        related_by_idx: dict[int, list[str]] = {}
        for idx, url, label in fetch_jobs:
            if label == "__self__":
                continue
            text = scrape_cache.get(url, "")
            entry = f"{label}\n{text[:800]}" if text else label
            related_by_idx.setdefault(idx, []).append(entry)

        for idx, m in enumerate(tasks_meta):
            m["related_materials"] = related_by_idx.get(idx, [])

        # 调试日志
        total_related = sum(len(m["related_materials"]) for m in tasks_meta)
        total_with_material = sum(1 for m in tasks_meta if m.get("material"))
        logger.info(f"[HotListReport] 自身正文: {total_with_material}/{len(tasks_meta)} 条，"
                     f"辅助平台相关素材: {total_related} 条")

        # 构建 related_lines / related_links（用于报告展示）
        for m in tasks_meta:
            related_lines = []
            related_links = []
            for sc in m["supplementary_codes"]:
                sc_name = PLATFORM_NAME_MAP.get(sc, sc)
                try:
                    matches = find_related(
                        m["title"], m["all_raw_data_ref"].get(sc, []), max_results=2
                    )
                except Exception:
                    continue
                for r in matches:
                    rt = r.get("title", "")
                    rurl = r.get("url", "")
                    rhot = r.get("hot", "")
                    line = f"  - {sc_name}: {rt}"
                    if rhot:
                        line += f" (🔥{rhot})"
                    related_lines.append(line)
                    related_links.append((sc_name, rt, rurl))
            m["related_lines"] = related_lines
            m["related_links"] = related_links

        # ---- 第二阶段：LLM 分析（并行 5 线程），带进度推送 ----
        completed = 0
        semaphore = asyncio.Semaphore(30)  # 最多 30 个 LLM 请求同时飞

        async def _bounded_summarize(meta: dict) -> tuple:
            nonlocal completed
            async with semaphore:
                summary = await self._summarise_one(
                    meta["title"], meta["hot"], meta["material"],
                    meta["related_lines"], meta.get("related_materials", [])
                )
                completed += 1
                await stream_output(
                    "logs", "analyzing",
                    f"🔍 分析 {completed}/{total_primary_items} [{meta['platform_name']} #{meta['rank']}]: {meta['title']}",
                    self.websocket, True,
                )
                return (
                    meta["platform_name"], meta["rank"], meta["title"],
                    meta["hot"], summary, meta["related_links"],
                )

        analyses: list[tuple] = list(await asyncio.gather(
            *[_bounded_summarize(m) for m in tasks_meta],
            return_exceptions=True,
        ))
        # 过滤掉异常结果
        analyses = [a for a in analyses if not isinstance(a, Exception)]
        # 按平台和排名排序（gather 不保证顺序）
        analyses.sort(key=lambda a: (a[0], a[1]))

        # ---- 第三阶段：汇总引言 + 趋势总结 ----
        await stream_output(
            "logs", "summarizing",
            f"📝 已完成 {len(analyses)} 条热搜分析，正在生成引言和趋势总结...",
            self.websocket, True,
        )
        report = await self._build_report(analyses, primary_codes)

        # ---- 推送完整报告 ----
        await stream_output(
            "report", "report_complete", report,
            self.websocket, True,
        )
        return report

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _summarise_one(
        self, title: str, hot: str, material: str,
        related_lines: list[str], related_materials: list[str] = [],
    ) -> str:
        """调 LLM 为单条热搜写分析（LangChain chain，原生 async）。

        material: 自身正文（可读平台有，视频平台为空）
        related_materials: 辅助平台相关条目正文（find_related 后抓的正文）
        """
        try:
            llm = _get_llm()
            # 拼合所有正文素材：自身 + 辅助平台
            all_materials_parts = []
            if material:
                all_materials_parts.append(f"【自身正文】\n{material[:1000]}")
            if related_materials:
                all_materials_parts.append(f"【辅助平台相关报道】\n" + "\n\n".join(related_materials))
            materials_text = "\n\n".join(all_materials_parts) if all_materials_parts else "（无正文素材，仅根据标题推测）"

            prompt = ChatPromptTemplate.from_messages([
                ("system", "你是一个专业资讯编辑。请为热榜词条写简明分析（3-5句话，80-150字）。"
                 "优先使用提供的正文素材进行分析；素材中提到其他平台反应请引用；"
                 "无素材时才可仅根据标题推测（需标注'标题推测'）；严禁编造具体金额、数据、引言；"
                 "只输出分析文本，不要加前缀。"),
                ("human",
                 "词条：{title}\n热度：{hot}\n\n参考素材：\n{materials}\n\n只输出分析本身："),
            ])
            chain = prompt | llm | StrOutputParser()
            text = await chain.ainvoke({
                "title": title,
                "hot": hot or "未知",
                "materials": materials_text[:3000],
            })
            return text.strip().strip("\"'\n")[:300]
        except Exception as e:
            logger.warning(f"LLM 摘要失败 '{title}': {e}")
            return f"（分析生成失败，仅标题推测：{title}）"

    async def _build_report(
        self, analyses: list[tuple], primary_codes: list[str]
    ) -> str:
        """汇总所有分析为最终 Markdown 报告。"""
        today = datetime.now().strftime("%Y年%m月%d日")
        primary_names = [PLATFORM_NAME_MAP.get(c, c) for c in primary_codes]

        # 拼接所有单条分析为 buffer
        buffer_parts = []
        for platform_name, rank, title, hot, summary, related in analyses:
            heat_str = f" 🔥{hot}" if hot else ""
            buffer_parts.append(f"**{platform_name} #{rank}: {title}**{heat_str}\n{summary}")
        buffer = "\n\n".join(buffer_parts)

        # 调 LLM 生成引言 + 趋势总结（LangChain chain，原生 async）
        try:
            llm = _get_llm()
            prompt = ChatPromptTemplate.from_messages([
                ("system", "你是一个资深资讯分析师。根据热榜分析结果写引言和趋势总结。"
                 "只输出 Markdown 格式（## 引言 ... ## 趋势总结 ...）。"),
                ("human",
                 "主干平台：{platforms}\n分析条目数：{count}\n当前日期：{today}\n\n"
                 "热榜分析结果：\n{buffer}\n\n请写：1. 引言（2-3句话）2. 趋势总结（3-5句话）"),
            ])
            chain = prompt | llm | StrOutputParser()
            intro_trend = await chain.ainvoke({
                "platforms": ", ".join(primary_names),
                "count": len(analyses),
                "today": today,
                "buffer": buffer[:4000],
            })
            intro_trend = intro_trend.strip().strip("\"'\n")
        except Exception as e:
            logger.warning(f"LLM 汇总失败: {e}")
            intro_trend = (
                f"## 引言\n\n"
                f"本报告基于 {', '.join(primary_names)} 的 {len(analyses)} 条实时热搜数据，"
                f"逐条分析并整合多平台交叉信息，为用户提供全面热榜洞察。\n\n"
                f"## 趋势总结\n\n"
                f"详见各条热榜分析。"
            )

        # 拼接最终报告
        report_lines = [
            f"# 📊 {today} 热榜报告",
            "",
            f"**覆盖平台**: {', '.join(primary_names)}",
            f"**分析条数**: {len(analyses)}",
            f"**数据来源**: 实时热榜 API（DailyHotApi）+ 跨平台相关条目匹配",
            "",
            intro_trend,
            "",
            "---",
            "",
            "## 🔍 逐条热榜分析",
            "",
        ]

        # 逐条分析小节
        for platform_name, rank, title, hot, summary, related_links in analyses:
            heat_str = f" 🔥{hot}" if hot else ""
            report_lines.append(f"### {rank}. {title}{heat_str}")
            report_lines.append(f"*平台: {platform_name}*")
            report_lines.append("")
            report_lines.append(summary)

            if related_links:
                report_lines.append("")
                report_lines.append("**跨平台相关报道：**")
                for sc_name, rt, rurl in related_links:
                    link_text = f"  - {sc_name}: {rt}"
                    if rurl:
                        link_text += f" → {rurl}"
                    report_lines.append(link_text)

            report_lines.append("")
            report_lines.append("---")
            report_lines.append("")

        return "\n".join(report_lines)
