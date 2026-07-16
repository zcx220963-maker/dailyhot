import os
import sys
import asyncio
import datetime
import json
import logging
import traceback
from typing import Dict, List

from fastapi import WebSocket

# Ensure the project root (parent of backend/) is on sys.path so that
# `from backend.X import Y` works regardless of cwd.
# __file__ = .../backend/server/websocket_manager.py  ->  project root = .../gpt-researcher
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.report_type import BasicReport, DetailedReport, HotListReport

from gpt_researcher.utils.enum import ReportType, Tone
from gpt_researcher.actions import stream_output  # Import stream_output
from .multi_agent_runner import run_multi_agent_task
from .server_utils import CustomLogsHandler

logger = logging.getLogger(__name__)



class WebSocketManager:
    """Manage websockets"""

    def __init__(self):
        """Initialize the WebSocketManager class."""
        self.active_connections: List[WebSocket] = []
        self.sender_tasks: Dict[WebSocket, asyncio.Task] = {}
        self.message_queues: Dict[WebSocket, asyncio.Queue] = {}

    async def start_sender(self, websocket: WebSocket):
        """Start the sender task."""
        queue = self.message_queues.get(websocket)
        if not queue:
            return

        while True:
            try:
                message = await queue.get()
                if message is None:  # Shutdown signal
                    break
                    
                if websocket in self.active_connections:
                    if message == "ping":
                        await websocket.send_text("pong")
                    else:
                        await websocket.send_text(message)
                else:
                    break
            except Exception as e:
                print(f"Error in sender task: {e}")
                break

    async def connect(self, websocket: WebSocket):
        """Connect a websocket."""
        try:
            await websocket.accept()
            self.active_connections.append(websocket)
            self.message_queues[websocket] = asyncio.Queue()
            self.sender_tasks[websocket] = asyncio.create_task(
                self.start_sender(websocket))
        except Exception as e:
            print(f"Error connecting websocket: {e}")
            if websocket in self.active_connections:
                await self.disconnect(websocket)

    async def disconnect(self, websocket: WebSocket):
        """Disconnect a websocket."""
        try:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
                
                # Cancel sender task if it exists
                if websocket in self.sender_tasks:
                    try:
                        self.sender_tasks[websocket].cancel()
                        await self.message_queues[websocket].put(None)
                    except Exception as e:
                        logger.error(f"Error canceling sender task: {e}")
                    finally:
                        # Always try to clean up regardless of errors
                        if websocket in self.sender_tasks:
                            del self.sender_tasks[websocket]
                
                # Clean up message queue
                if websocket in self.message_queues:
                    del self.message_queues[websocket]
                
                # Finally close the WebSocket
                try:
                    await websocket.close()
                except Exception as e:
                    logger.info(f"WebSocket already closed: {e}")
        except Exception as e:
            logger.error(f"Error during WebSocket disconnection: {e}")
            # Still try to close the connection if possible
            try:
                await websocket.close()
            except Exception:
                pass  # If this fails too, there's nothing more we can do

    async def start_streaming(self, task, report_type, report_source, source_urls, document_urls, tone, websocket, headers=None, query_domains=[], mcp_enabled=False, mcp_strategy="fast", mcp_configs=[], max_search_results=None, hot_platforms=None):
        """Start streaming the output."""
        # 大小写不敏感地查找 Tone 枚举，避免前端传入 lowercase 值时崩溃
        tone_map = {member.name.lower(): member for member in Tone}
        tone_enum = tone_map.get(tone.lower(), Tone.Objective) if tone else Tone.Objective
        # add customized JSON config file path here
        config_path = os.environ.get("CONFIG_PATH", "default")

        # ── 统一意图识别（单次 LLM 调用，替代所有散落关键词匹配）──
        intent = await self._recognize_intent(task)
        if intent["is_hot_list"]:
            report_type = "hot_list_report"

        # Pass MCP parameters to run_agent
        report = await run_agent(
            task, report_type, report_source, source_urls, document_urls, tone_enum, websocket,
            headers=headers, query_domains=query_domains, config_path=config_path,
            mcp_enabled=mcp_enabled, mcp_strategy=mcp_strategy, mcp_configs=mcp_configs,
            max_search_results=max_search_results,
            intent_result=intent,
            hot_platforms=hot_platforms,
        )
        return report

    @staticmethod
    async def _recognize_intent(task: str) -> dict:
        """统一意图识别入口 —— 调 LangChain intent_agent。"""
        try:
            from backend.hot_research.intent_agent import recognize_intent
            return await recognize_intent(task)
        except Exception as e:
            logger.warning(f"[IntentAgent] 调用失败，回退到安全默认值: {e}")
            return {"is_hot_list": False, "primary_codes": [], "category": "all", "confidence": 0.0}

async def run_agent(task, report_type, report_source, source_urls, document_urls, tone: Tone, websocket, stream_output=stream_output, headers=None, query_domains=[], config_path="", return_researcher=False, mcp_enabled=False, mcp_strategy="fast", mcp_configs=[], max_search_results=None, intent_result: dict = None, hot_platforms=None):
    """Run the agent."""
    # Create logs handler for this research task
    logs_handler = CustomLogsHandler(websocket, task)

    # Log MCP initialization. Retriever and strategy are configured per-request
    # inside GPTResearcher via mcp_configs/mcp_strategy params — no os.environ
    # mutation needed here (mutating os.environ would persist across requests and
    # affect unrelated sessions, see issue #1676).
    if mcp_enabled and mcp_configs:
        print(f"🔧 MCP enabled with strategy '{mcp_strategy}' and {len(mcp_configs)} server(s)")
        await logs_handler.send_json({
            "type": "logs",
            "content": "mcp_init",
            "output": f"🔧 MCP enabled with strategy '{mcp_strategy}' and {len(mcp_configs)} server(s)"
        })

    # Initialize researcher based on report type
    if report_type == "multi_agents":
        report = await run_multi_agent_task(
            query=task,
            websocket=logs_handler,  # Use logs_handler instead of raw websocket
            stream_output=stream_output,
            tone=tone,
            headers=headers
        )
        report = report.get("report", "")

    elif report_type == "hot_list_report":
        # 热榜专用分支：
        # 1. intent_result（来自意图识别 Agent）已包含 primary_codes
        # 2. collect_hot_data 拉齐全平台数据（MCP get_all_hot_list，~5 秒）
        # 3. HotListReport 用 primary_codes 定主干 + find_related 匹配辅助 → 逐条分析
        from backend.hot_research.hot_list_agent import collect_hot_data
        from hot_research.daily_hot_api import PLATFORMS

        # primary_codes 来自统一意图识别；兜底全平台
        intent_primary = intent_result.get("primary_codes", []) if intent_result else []
        intent_category = intent_result.get("category", "all") if intent_result else "all"

        await stream_output(
            "logs", "agent_start",
            f"🤖 意图识别完成（主干平台: {intent_primary or '全平台'}, 分类: {intent_category}）\n"
            f"   正在拉取全平台热榜数据...",
            websocket=logs_handler, output_log=True,
        )

        # MCP 拉齐全平台数据（Agent 内部走 ReAct + get_all_hot_list）
        # primary_codes 来自统一意图识别；全平台兜底
        primary_codes = intent_primary if intent_primary else [p[0] for p in PLATFORMS]
        all_raw, primary_codes = await collect_hot_data(
            query=task,
            primary_codes=primary_codes,
            hot_platforms=hot_platforms,
            websocket=logs_handler,
        )

        await stream_output(
            "logs", "agent_done",
            f"✅ 数据收集完成，主干平台: {primary_codes}",
            websocket=logs_handler, output_log=True,
        )

        researcher = HotListReport(
            query=task,
            all_raw_data=all_raw,
            primary_codes=primary_codes,
            websocket=logs_handler,
            tone=tone,
            config_path=config_path,
        )
        report = await researcher.run()

        # 报告生成后推送到飞书
        try:
            from gpt_researcher.actions.notifiers import send_report_to_feishu
            from hot_research.daily_hot_api import PLATFORM_NAME_MAP
            primary_names = [PLATFORM_NAME_MAP.get(c, c) for c in primary_codes]
            title = f"📊 {task} ({', '.join(primary_names)})"
            await asyncio.get_event_loop().run_in_executor(
                None, send_report_to_feishu, report, title
            )
            await stream_output("logs", "feishu",
                "📨 已推送到飞书",
                websocket=logs_handler, output_log=True,
            )
        except Exception as e:
            logger.warning(f"飞书推送失败: {e}")

    elif report_type == ReportType.DetailedReport.value:
        researcher = DetailedReport(
            query=task,
            query_domains=query_domains,
            report_type=report_type,
            report_source=report_source,
            source_urls=source_urls,
            document_urls=document_urls,
            tone=tone,
            config_path=config_path,
            websocket=logs_handler,  # Use logs_handler instead of raw websocket
            headers=headers,
            mcp_configs=mcp_configs if mcp_enabled else None,
            mcp_strategy=mcp_strategy if mcp_enabled else None,
            max_search_results=max_search_results,
        )
        report = await researcher.run()

    else:
        researcher = BasicReport(
            query=task,
            query_domains=query_domains,
            report_type=report_type,
            report_source=report_source,
            source_urls=source_urls,
            document_urls=document_urls,
            tone=tone,
            config_path=config_path,
            websocket=logs_handler,  # Use logs_handler instead of raw websocket
            headers=headers,
            mcp_configs=mcp_configs if mcp_enabled else None,
            mcp_strategy=mcp_strategy if mcp_enabled else None,
            max_search_results=max_search_results,
        )
        report = await researcher.run()

    if report_type not in ("multi_agents",) and return_researcher:
        return report, researcher.gpt_researcher
    else:
        return report
