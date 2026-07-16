"""热榜研究 Pipeline.

1.  从 DailyHotApi 抓取原始热榜条目
2.  尝试爬取每条对应的文章正文；
    如果是视频页，回退到其他平台找同主题的文字报道（可读取的纯文本平台）
3.  使用大模型基于已获取的每条文本写简明摘要
4.  格式化为结构化的 Markdown 报告
5.  可选：通过 Webhook 推送到飞书
"""
import asyncio
import logging
import os
import random
import re
from datetime import datetime
from typing import Optional

from .daily_hot_api import (
    PLATFORMS,
    fetch_hot,
    find_related,
)
from .scraper import fetch_article_text

logger = logging.getLogger(__name__)

# ----------------------------- 大模型调用封装 -----------------------------

def _get_llm():
    """获取一个兼容项目现有配置的聊天大模型（LongCat 等）。

    从项目根目录（backend 上一层）加载 .env。
    """
    import os
    import sys
    from pathlib import Path
    from dotenv import load_dotenv

    # 确保项目根目录在 Python 路径上，才能 import gpt_researcher
    proj_root = Path(__file__).resolve().parent.parent.parent
    if str(proj_root) not in sys.path:
        sys.path.insert(0, str(proj_root))

    # 加载项目根目录的 .env
    env_path = proj_root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)

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


_SUMMARY_PROMPT = """你是一个资讯编辑。请根据下面提供的标题和素材文本，写一段简明扼要的摘要（2-3句话，不超过80字）。
要求：说明事件是什么、关键信息点。如果素材为空或无法获取内容，仅根据标题推测即可（标注"标题推测"）。

标题: {title}
素材:
{materials}

只输出摘要本身，不要加任何前缀。
"""


_LINK_SUMMARY_PROMPT = """你是一个资讯编辑。以下是同一个热点话题在不同平台的几条报道标题和链接。请根据这些标题推测该话题的完整面貌，写一段3-5句话的摘要（不超过120字）。

话题: {title}

相关报道:
{links}

只输出摘要本身。
"""


def _summarise_item(title: str, materials: str) -> str:
    """让大模型为单条热搜写摘要。"""
    if not materials or len(materials.strip()) < 10:
        materials = "（无可用素材，仅凭标题推测）"
    prompt = _SUMMARY_PROMPT.format(title=title, materials=materials[:1500])
    try:
        llm = _get_llm()
        resp = llm.invoke(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)
        # 剥掉模型包裹的引号/换行
        text = text.strip().strip("\"'\n")
        return text[:200]
    except Exception as e:
        logger.warning(f"摘要生成失败 '{title}': {e}")
        return ""


def _summarise_from_links(title: str, link_lines: list[str]) -> str:
    """当任何正文都抓不到时，只基于其他平台相关新闻的标题写摘要。"""
    if not link_lines:
        return ""
    blob = "\n".join(f"  - {l}" for l in link_lines)
    prompt = _LINK_SUMMARY_PROMPT.format(title=title, links=blob)
    try:
        llm = _get_llm()
        resp = llm.invoke(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)
        return text.strip().strip("\"'\n")[:250]
    except Exception as e:
        logger.warning(f"链接摘要生成失败 '{title}': {e}")
        return ""


# ---------------------------- 主流程 ----------------------------

async def fetch_raw_hot_lists(
    platforms: Optional[list[str]] = None,
    max_items_per_platform: Optional[dict[str, int]] = None,
) -> dict:
    """阶段 1: 抓取原始热榜数据（标题 + 热度 + URL），不做处理。

    返回结构化字典: {平台代码: [条目列表], "_metadata": {...}}
    """
    platforms = platforms or [p[0] for p in PLATFORMS]
    max_items_per_platform = max_items_per_platform or {}

    logger.info("★ 阶段 1: 抓取原始热榜数据…")
    all_data: dict[str, list] = {}
    for code in platforms:
        platform_info = next((p for p in PLATFORMS if p[0] == code), None)
        if platform_info is None:
            continue
        _, name, _, _ = platform_info
        cap = max_items_per_platform.get(code, 50)
        items = fetch_hot(code, cap)
        all_data[code] = items
        logger.info(f"  {name}: {len(items)} 条")

    all_data["_metadata"] = {
        "fetch_time": datetime.now().isoformat(),
        "platforms": platforms,
    }
    return all_data


async def generate_report_from_raw(
    all_data: dict,
    max_text_items: int = 20,
) -> list[tuple[str, str]]:
    """阶段 2: 基于原始热榜数据，爬取文章、大模型写摘要。

    返回 (报告标题, 报告正文) 列表——每个平台一条，加上总览摘要。
    """
    all_data.pop("_metadata", None)
    today = datetime.now().strftime("%Y年%m月%d日")
    now_time = datetime.now().strftime("%H:%M")

    reports: list[tuple[str, str]] = []

    # 2a. 总览消息（与原来的每日推送格式一致）
    total_items = sum(len(v) for v in all_data.values())
    platform_count = len(all_data)
    summary_lines = [
        f"📊 今日全网热榜汇总 — {today}",
        f"共 {platform_count} 个平台, {total_items} 条热搜",
        "以下为各平台热点，每条附有简要摘要和相关链接 👇",
    ]
    reports.append(("📊 今日热榜总览", "\n".join(summary_lines)))

    # 2b. 各平台详细报告
    other_data = dict(all_data)

    for code, items in all_data.items():
        if not items:
            continue
        platform_info = next((p for p in PLATFORMS if p[0] == code), None)
        if platform_info is None:
            continue
        name = platform_info[1]
        is_text_readable = platform_info[3]

        lines = [f"🔥 {name} 热搜 TOP {len(items)}", "=" * 30]

        items_to_summarise = items[:max_text_items]
        items_remaining = items[max_text_items:]

        text_fetch_count = 0
        for i, item in enumerate(items_to_summarise, 1):
            title = item.get("title", "")
            hot = item.get("hot", "")
            url = item.get("url", "")
            if not title:
                continue

            # 抓取本条 URL 对应的文章正文
            material = ""
            if is_text_readable and text_fetch_count < max_text_items:
                material, _ = await fetch_article_text(url)
                text_fetch_count += 1

            # 从其他平台找相关新闻（始终执行）
            related_links = []
            for pc, pn, _, _ in PLATFORMS:
                if pc == code:
                    continue
                for r in find_related(title, other_data.get(pc, []), max_results=2):
                    rt = r.get("title", "")
                    rurl = r.get("url", "")
                    rhot = r.get("hot", "")
                    line = f"{pn}: {rt}"
                    if rhot:
                        line += f" (🔥{rhot})"
                    related_links.append((line, rurl))

            # 生成摘要
            if material:
                summary = _summarise_item(title, material)
            elif related_links:
                titles_only = [l for l, _ in related_links]
                summary = _summarise_from_links(title, titles_only)
            else:
                summary = _summarise_item(title, "")

            heat = f" 🔥{hot}" if hot else ""
            lines.append(f"**{i}. {title}**{heat}")
            if summary:
                lines.append(f"> {summary}")
            if url:
                lines.append(f"  • {name}: {url}")
            for link_text, link_url in related_links:
                lines.append(f"  • {link_url}" if link_url else f"  • {link_text}")
            lines.append("")

        # 剩余条目只列标题（不写摘要）
        if items_remaining:
            lines.append(f"… 其余 {len(items_remaining)} 条未展开:")
            for i, item in enumerate(items_remaining, len(items_to_summarise) + 1):
                hot = item.get("hot", "")
                heat = f" 🔥{hot}" if hot else ""
                lines.append(f"  {i}. {item.get('title','')}{heat}")
            lines.append("")

        body = "\n".join(lines)
        reports.append((f"{name} TOP {len(items)}", body))

    return reports


async def run_pipeline(
    platforms: Optional[list[str]] = None,
    max_items_per_platform: Optional[dict[str, int]] = None,
    max_text_items: int = 20,
    push_feishu: bool = True,
) -> str:
    """高层流程: 阶段 1（抓原始）→ 阶段 2（处理）→ 推送到飞书。

    返回最终 Markdown 字符串。
    """
    # 阶段 1: 原始数据
    raw_data = await fetch_raw_hot_lists(platforms, max_items_per_platform)

    # 阶段 2: 处理为报告
    reports = await generate_report_from_raw(raw_data, max_text_items)

    # 阶段 3: 推送到飞书
    if push_feishu and (os.getenv("FEISHU_WEBHOOK_URL") or os.getenv("FEISHU_APP_ID")):
        await _push_to_feishu(reports)

    # 阶段 4: 保存备份
    full_md = "\n\n---\n\n".join(body for _, body in reports)
    try:
        from pathlib import Path
        proj_root = Path(__file__).resolve().parent.parent.parent
        out_dir = proj_root / "outputs"
        out_dir.mkdir(exist_ok=True)
        ds = datetime.now().strftime("%Y%m%d_%H%M")
        with open(out_dir / f"hot_research_{ds}.md", "w", encoding="utf-8") as f:
            f.write(full_md)
    except Exception as e:
        logger.warning(f"保存备份失败: {e}")

    return full_md


# ----------------------------- 飞书推送 ------------------------------

async def _push_to_feishu(reports: list[tuple[str, str]]):
    """每个平台单独推一条飞书消息，超长内容自动切分。"""
    from gpt_researcher.actions.notifiers import send_report_to_feishu

    loop = asyncio.get_running_loop()
    for title, body in reports:
        chunks = _split(body, 4000)
        n = len(chunks)
        for idx, chunk in enumerate(chunks, 1):
            msg_title = f"{title} ({idx}/{n})" if n > 1 else title
            try:
                await loop.run_in_executor(
                    None, send_report_to_feishu, chunk, msg_title
                )
            except Exception as e:
                logger.error(f"飞书推送失败 {msg_title}: {e}")


def _split(text: str, max_len: int) -> list[str]:
    """按行切分为长度不超过 max_len 的块。"""
    lines = text.split("\n")
    chunks, cur = [], []
    cur_len = 0
    for line in lines:
        add_len = len(line) + 1
        if cur_len + add_len > max_len and cur:
            chunks.append("\n".join(cur))
            cur = [line]
            cur_len = add_len
        else:
            cur.append(line)
            cur_len += add_len
    if cur:
        chunks.append("\n".join(cur))
    return chunks
