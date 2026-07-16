"""热榜数据收集 Agent — ReAct 一次性拉取全平台热榜数据。

用 LangGraph 的 create_react_agent 跑 ReAct 循环：
  LLM 思考 → 调 get_all_hot_list → 观察结果 → 结束

核心设计：
- 始终调 get_all_hot_list（一次性拉全平台数据，供 HotListReport 做跨平台 find_related 辅助匹配）
- 意图识别（用户关心哪些平台）已由上层 intent_agent 完成，本模块只负责拿数据
- 返回结构化数据 (all_raw_data, primary_codes)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 系统提示词
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一个热榜数据收集助手。你的唯一职责是调用工具一次性拉取全平台热榜数据。

规则：
- 始终调用 get_all_hot_list(default_limit=30) 一次，获取全部平台的热榜数据
- 不要在一条一条平台分别调 get_<code>_hot
- 拉取完成后简短回复"数据收集完成"

注意：意图识别（用户关心哪些平台）已由上层完成，你只负责拿数据。
"""


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def collect_hot_data(
    query: str,
    primary_codes: list[str],
    hot_platforms: Optional[list[dict]] = None,
    websocket=None,
):
    """构建 ReAct agent 并一次性拉取全平台热榜数据。

    Args:
        query: 用户原始查询
        primary_codes: 主干平台代码列表（由 intent_agent 提供）
        hot_platforms: 前端配置的自定义平台列表（可选）
        websocket: 用于推送进度日志

    Returns:
        (all_raw_data, primary_codes)
        - all_raw_data: {平台代码: [{title, hot, url, text}, ...]} 全平台数据
        - primary_codes: 原样返回传入值
    """
    # 1. 注入自定义平台配置到环境
    mcp_env = os.environ.copy()
    if hot_platforms:
        mcp_env["HOT_PLATFORMS_JSON"] = json.dumps(hot_platforms, ensure_ascii=False)

    # 2. 通过 MultiServerMCPClient 连接 MCP
    from langchain_mcp_adapters.client import MultiServerMCPClient

    server_config = {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "backend.mcp_servers.hot_list_server"],
        "env": mcp_env,
    }
    client = MultiServerMCPClient({"hot_list": server_config})
    mcp_tools = await client.get_tools()

    if websocket:
        from gpt_researcher.actions.utils import stream_output
        tool_names = [t.name for t in mcp_tools]
        await stream_output("logs", "agent_tools",
            f"🔧 Agent 可用工具: {', '.join(tool_names[:5])}...",
            websocket, True)

    # 3. 构建 ReAct agent
    llm = _get_langchain_llm()
    agent = create_react_agent(llm, mcp_tools, prompt=SYSTEM_PROMPT, debug=False)

    # 4. 运行，从 events 里提取数据
    all_raw_data: dict[str, list] = {}

    async for event in agent.astream(
        {"messages": [HumanMessage(content=query)]},
        config={"recursion_limit": 15},
    ):
        # 收集所有要检查的消息：
        # - "tools" 事件: ToolMessage 在 event["tools"]["messages"]
        # - "model" 事件: AIMessage 在 event["messages"]
        messages_to_check = []
        if "tools" in event:
            messages_to_check.extend(event["tools"].get("messages", []))
            # 推送工具调用日志
            if websocket:
                from gpt_researcher.actions.utils import stream_output
                for msg in event["tools"]["messages"]:
                    await stream_output("logs", "agent_tool",
                        f"🔧 调用工具: {msg.name}",
                        websocket, True)
        messages_to_check.extend(event.get("messages", []))

        # 从所有消息里提取工具返回结果
        for msg in messages_to_check:
            if hasattr(msg, "name") and msg.name:
                data = _parse_tool_output(msg)
                if data:
                    # data 是 [(code, items), ...] 列表
                    for code, items in data:
                        all_raw_data[code] = items
                        if websocket:
                            from gpt_researcher.actions.utils import stream_output
                            await stream_output("logs", "agent_result",
                                f"✅ {code}: {len(items)} 条数据",
                                websocket, True)

    return all_raw_data, primary_codes


# ---------------------------------------------------------------------------
# 工具输出解析
# ---------------------------------------------------------------------------

def _parse_tool_output(msg) -> Optional[list[tuple[str, list]]]:
    """解析 MCP 工具返回的 JSON 数据 → [(平台代码, items 列表), ...]。

    支持两种格式：
    1. get_<code>_hot 返回 {"platform", "code", "count", "items": [...]} → [(code, items)]
    2. get_all_hot_list 返回 {code: {"platform", "count":50, "items": [...]}} → 返回所有平台
    """
    try:
        text = msg.content
        if isinstance(text, list):
            parts = []
            for item in text:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get("text", ""))
                elif hasattr(item, "text"):
                    parts.append(item.text)
            text = " ".join(parts) if parts else ""
        if not text or not text.strip():
            return None
        result = json.loads(text) if isinstance(text, str) else text

        # 格式1: get_<code>_hot 返回 {"platform", "code", "count", "items": [...]}
        if isinstance(result, dict) and "items" in result and "code" in result:
            code = result.get("code", msg.name.replace("get_", "").replace("_hot", ""))
            return [(code, result["items"])]

        # 格式2: get_all_hot_list 返回 {code: {"platform", "count", "items": [...]}}
        if isinstance(result, dict):
            all_results = []
            for code, pdata in result.items():
                if isinstance(pdata, dict) and "items" in pdata:
                    all_results.append((code, pdata["items"]))
            if all_results:
                return all_results

    except (json.JSONDecodeError, TypeError, KeyError) as e:
        logger.warning(f"解析工具输出失败 ({msg.name}): {e}, content_type={type(msg.content).__name__}")
    return None


# ---------------------------------------------------------------------------
# LLM 工厂（复用 langchain_agent.py 的逻辑）
# ---------------------------------------------------------------------------

def _get_langchain_llm():
    """获取项目里用作"快速 LLM"的实例，包装为 LangChain 聊天模型。

    与 langchain_agent.py 的 _get_langchain_llm() 完全一致。
    """
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
        temperature=0.3,
        stream_usage=False,
    )
    return provider.llm
