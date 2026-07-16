"""热榜 MCP 服务器 —— 支持动态平台配置。

平台来源（优先级从高到低）:
  1. 环境变量 HOT_PLATFORMS_JSON —— 前端传入的自定义平台列表
  2. 内置 PLATFORMS —— 默认9平台

正文抓取策略：
  MCP 仅返回标题 + URL + 热度，不爬正文（快速返回）。
  正文由 HotListReport 在分析阶段按需并发抓取（asyncio.gather + Semaphore）。

启动方式（stdio）:
    python -m backend.mcp_servers.hot_list_server
"""

import sys
import os
import json
import logging
from pathlib import Path

# backend/ 加入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

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

    # 注册每个平台的 tool
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

    return platforms


if __name__ == "__main__":
    platforms = _build_server()
    logger.info(f"🔥 热榜 MCP 服务器启动（stdio 模式）")
    logger.info(f"   已注册 {len(platforms)} 个平台: {[p[1] for p in platforms]}")
    mcp.run(transport="stdio")
