"""热榜 MCP 服务器 —— 支持 stdio / HTTP 两种模式。

平台来源（优先级从高到低）:
  1. 环境变量 HOT_PLATFORMS_JSON —— 前端传入的自定义平台列表
  2. 内置 PLATFORMS —— 默认9平台

工具分类:
  原始数据工具:  get_{code}_hot, get_all_hot_list, list_hot_platforms
  Agent 工具:   generate_hot_report (完整报告), chat_about_hot_report (追问)

启动方式:
    本地 Agent（stdio）:    python backend/mcp_servers/hot_list_server.py --transport stdio
    外部 Agent（HTTP）:     python backend/mcp_servers/hot_list_server.py --transport http --port 8002
"""

import sys
import os
import json
import logging
import asyncio
import argparse
from pathlib import Path
from typing import Any

# backend/ 和项目根目录加入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_DIR = _BACKEND_DIR.parent
for _p in (_BACKEND_DIR, _PROJECT_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastmcp import FastMCP

from hot_research.daily_hot_api import (
    PLATFORMS as BUILTIN_PLATFORMS,
    fetch_hot,
)

logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
logger = logging.getLogger(__name__)

mcp = FastMCP("hot-list-server")


def _get_platforms() -> list[tuple]:
    """获取平台列表：优先用环境变量中的自定义配置，否则用内置默认。"""
    custom = os.environ.get("HOT_PLATFORMS_JSON")
    if custom:
        try:
            custom_list = json.loads(custom)
            platforms = []
            for p in custom_list:
                code = p.get("code", "")
                name = p.get("name", code)
                limit = p.get("limit", 30)
                readable = p.get("readable", False)
                platforms.append((code, name, limit, readable))
                _register_fetch_route(code, p)
            logger.info(f"从环境变量加载 {len(platforms)} 个自定义平台")
            return platforms
        except json.JSONDecodeError as e:
            logger.warning(f"HOT_PLATFORMS_JSON 解析失败: {e}，回退到内置平台")
    return BUILTIN_PLATFORMS


def _register_fetch_route(code: str, platform_config: dict):
    """为自定义平台注册 fetch_hot 路由。"""
    source_type = platform_config.get("source_type", "dailyhotapi")
    url = platform_config.get("url", "")

    if source_type == "dailyhotapi":
        pass
    elif source_type == "json_api":
        import hot_research.daily_hot_api as dha
        import requests as req

        def _fetch_custom(limit=30):
            try:
                headers = platform_config.get("headers", {})
                resp = req.get(url, headers=headers, timeout=15, proxies=dha._proxy())
                data = resp.json()
                items_path = platform_config.get("items_path", "data")
                items = data
                for key in items_path.split("."):
                    items = items.get(key, []) if isinstance(items, dict) else []
                title_field = platform_config.get("title_field", "title")
                hot_field = platform_config.get("hot_field", "hot")
                url_field = platform_config.get("url_field", "url")
                result = []
                for it in items[:limit]:
                    result.append({
                        "title": it.get(title_field, ""),
                        "hot": it.get(hot_field, 0),
                        "url": it.get(url_field, ""),
                    })
                return result
            except Exception as e:
                logger.warning(f"fetch_custom({code}): {e}")
                return []

        original_fetch_hot = dha.fetch_hot

        def _patched_fetch_hot(platform_code, limit=50, _code=code, _fetch=_fetch_custom):
            if platform_code == _code:
                return _fetch(limit)
            return original_fetch_hot(platform_code, limit)

        dha.fetch_hot = _patched_fetch_hot
        logger.info(f"已注册自定义平台 {code} (json_api) → {url}")


def _make_tool(code: str, name: str, readable: bool = True):
    """为指定平台动态生成 MCP tool 函数 —— 仅返回标题+URL，不爬正文。"""

    async def _tool(
        code: str = code,
        name: str = name,
        readable: bool = readable,
        limit: int = 30,
    ) -> str:
        try:
            items = fetch_hot(code, limit)
            if not items:
                return json.dumps(
                    {"platform": name, "code": code, "items": [], "error": "无数据"},
                    ensure_ascii=False,
                )
            return json.dumps(
                {"platform": name, "code": code, "count": len(items), "items": items},
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps({"platform": name, "code": code, "error": str(e)}, ensure_ascii=False)

    _tool.__name__ = f"get_{code}_hot"
    _tool.__qualname__ = f"get_{code}_hot"
    _tool.__doc__ = f"获取{name}实时热搜榜单（TOP N，仅标题+URL）"
    return _tool


def _build_server():
    """根据平台配置构建 MCP 服务器。"""
    platforms = _get_platforms()

    # ── 原始数据工具（快速返回，仅标题+URL） ──────────────────────
    for _code, _name, _default_n, _readable in platforms:
        _registered = _make_tool(_code, _name, readable=_readable)
        mcp.tool(
            name=f"get_{_code}_hot",
            description=f"获取{_name}实时热搜榜单（仅标题+URL，快速返回）",
        )(_registered)

    @mcp.tool(name="get_all_hot_list", description="一次性抓取所有支持平台的热榜数据（仅标题+URL，快速返回）")
    async def get_all_hot_list(default_limit: int = 30) -> str:
        """抓取所有平台的热榜数据 —— 不爬正文，返回标题+URL+热度。"""
        result = {}
        for code, name, _, readable in platforms:
            try:
                items = fetch_hot(code, default_limit)
                result[code] = {"platform": name, "count": len(items), "items": items}
            except Exception as e:
                result[code] = {"platform": name, "count": 0, "items": [], "error": str(e)}
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(name="list_hot_platforms", description="列出所有支持的热搜平台及其说明")
    async def list_hot_platforms() -> str:
        """列出所有可用平台。"""
        return json.dumps(
            [{"code": c, "name": n, "limit": l} for c, n, l, _ in platforms],
            ensure_ascii=False,
        )

    # ── Agent 工具（完整报告生成 + 追问） ─────────────────────────

    @mcp.tool(
        name="generate_hot_report",
        description=(
            "根据用户自然语言查询，自动完成热榜报告生成的完整流程："
            "意图识别 → 抓取全平台热榜 → 关键词匹配辅助平台 → 爬取正文 → "
            "LLM 逐条分析 → 生成 Markdown 报告。"
            "输入示例: '今日抖音热榜' 或 '抖音+B站科技热点' 或 '今天全网热搜'。"
            "返回: {ok, report, hot_items, error}"
        ),
    )
    async def generate_hot_report(query: str) -> str:
        """外部 Agent 调用 —— 传入自然语言，返回完整热榜报告。"""
        try:
            # 1. 意图识别
            from hot_research.intent_agent import recognize_intent
            intent = await recognize_intent(query)
            if not intent.get("is_hot_list"):
                return json.dumps({
                    "ok": False,
                    "error": "意图识别判定非热榜查询",
                    "intent": intent,
                }, ensure_ascii=False)

            primary_codes = intent.get("primary_codes", [])
            if not primary_codes:
                primary_codes = [p[0] for p in platforms]

            # 2. 抓取全平台原始数据
            all_raw_data: dict[str, list[dict]] = {}
            for code, name, _, _ in platforms:
                try:
                    all_raw_data[code] = fetch_hot(code, 30)
                except Exception as e:
                    logger.warning(f"抓取 {name}({code}) 失败: {e}")
                    all_raw_data[code] = []

            # 3. 构造一个 dummy websocket（不推前端，只收集日志）
            class _DummyWS:
                async def send_json(self, data): pass
            dummy_ws = _DummyWS()

            # 4. 跑完整报告生成
            from report_type.hot_list_report.hot_list_report import HotListReport
            agent = HotListReport(
                query=query,
                all_raw_data=all_raw_data,
                primary_codes=primary_codes,
                websocket=dummy_ws,
            )
            report = await agent.run()

            # 5. 提取 hot_items（从 agent.analyses 结构化）
            hot_items = []
            for platform_name, rank, title, hot, summary, related_links, url in agent.analyses:
                hot_items.append({
                    "platform": platform_name,
                    "rank": rank,
                    "title": title,
                    "hot": hot,
                    "url": url or "",
                    "summary": summary[:300],
                    "related_links": [
                        {"platform": s, "title": t, "url": u}
                        for s, t, u in (related_links or [])
                    ],
                })

            return json.dumps({
                "ok": True,
                "report": report,
                "hot_items": hot_items,
                "primary_codes": primary_codes,
            }, ensure_ascii=False)

        except Exception as e:
            logger.exception(f"generate_hot_report 失败: {e}")
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    @mcp.tool(
        name="chat_about_hot_report",
        description=(
            "对已生成的热榜报告进行追问。"
            "输入: question（追问内容）+ report（报告文本）+ hot_items（结构化索引，可选）。"
            "输出: {ok, answer, error}"
            "示例问题: '第二条详细说说'、'写个口播稿'、'B站那条关于XX的'"
        ),
    )
    async def chat_about_hot_report(
        question: str,
        report: str = "",
        hot_items: list[dict[str, Any]] | None = None,
    ) -> str:
        """外部 Agent 调用 —— 追问热榜报告。"""
        try:
            from chat.chat import ChatAgentWithMemory
            agent = ChatAgentWithMemory(
                report=report,
                config_path="default",
                headers=None,
                hot_items=hot_items or [],
            )
            messages = [{"role": "user", "content": question}]
            answer, _tool_calls = await agent.chat(messages)
            return json.dumps({"ok": True, "answer": answer}, ensure_ascii=False)
        except Exception as e:
            logger.exception(f"chat_about_hot_report 失败: {e}")
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    return platforms


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="热榜 MCP 服务器 —— 支持 stdio / HTTP 两种模式")
    parser.add_argument(
        "--transport", "-t",
        choices=["stdio", "http"],
        default="stdio",
        help="传输协议: stdio（本地进程）| http（外部 Agent 调用）",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8002,
        help="HTTP 模式监听端口（默认 8002）",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="HTTP 模式监听地址（默认 0.0.0.0，外网可访问）",
    )
    args = parser.parse_args()

    platforms = _build_server()
    logger.info(f"🔥 热榜 MCP 服务器启动")
    logger.info(f"   已注册 {len(platforms)} 个平台: {[p[1] for p in platforms]}")

    if args.transport == "stdio":
        logger.info(f"   模式: stdio（本地进程通信）")
        mcp.run(transport="stdio")

    elif args.transport == "http":
        logger.info(f"   模式: HTTP（MCP Streamable HTTP）")
        logger.info(f"   地址: http://{args.host}:{args.port}/mcp")
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
        )
