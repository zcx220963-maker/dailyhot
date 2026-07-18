import asyncio
import json
import os
from typing import Dict, List, Any, Optional
import time
import logging
import sys
import warnings
from pathlib import Path

# Load .env from project root THIS MUST BE BEFORE any gpt_researcher imports
from dotenv import load_dotenv
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)

# Suppress Pydantic V2 migration warnings
warnings.filterwarnings("ignore", message="Valid config keys have changed in V2")
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, File, UploadFile, BackgroundTasks, HTTPException
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict

# Add the parent directory to sys.path to make sure we can import from server
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from server.websocket_manager import WebSocketManager
from server.server_utils import (
    sanitize_filename,
    handle_file_upload, handle_file_deletion,
    execute_multi_agents, handle_websocket_communication
)
from server.agent_discovery import build_agent_discovery_document

from server.websocket_manager import run_agent
from utils import write_md_to_word, write_md_to_pdf
from gpt_researcher.utils.enum import Tone
from chat.chat import ChatAgentWithMemory
from gpt_researcher.actions.notifiers import send_report_to_feishu

from server.report_store import ReportStore


async def _recognize_intent_for_rest(task: str) -> dict:
    """REST 路径的统一意图识别（与 WebSocket 路径共用 intent_agent）。"""
    try:
        from backend.hot_research.intent_agent import recognize_intent
        return await recognize_intent(task)
    except Exception as e:
        logger.warning(f"[IntentAgent] REST 调用失败: {e}")
        return {"is_hot_list": False, "primary_codes": [], "category": "all", "confidence": 0.0}

# 热榜研究模块（进程内定时任务 + LangChain Agent + 流水线）
from hot_research import init_scheduler, shutdown_scheduler
from hot_research.langchain_agent import ask as hot_ask
from hot_research.pipeline import run_pipeline as run_hot_pipeline
from hot_research.daily_hot_api import get_supported_platforms

# 无需数据库持久化

# 日志初始化
logger = logging.getLogger(__name__)

# Don't override parent logger settings
logger.propagate = True

# Silence uvicorn reload logs
logging.getLogger("uvicorn.supervisors.ChangeReload").setLevel(logging.WARNING)

# Models


class ResearchRequest(BaseModel):
    task: str
    report_type: str
    report_source: str
    tone: str
    headers: dict | None = None
    repo_name: str
    branch_name: str
    generate_in_background: bool = True


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")  # Allow extra fields in the request

    report: str
    messages: List[Dict[str, Any]]
    hot_items: Optional[List[Dict[str, Any]]] = None  # 结构化热榜条目（可选）


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    os.makedirs("outputs", exist_ok=True)

    # 启动进程内定时任务（每日 9:00 / 20:00 热榜推送）
    init_scheduler()
    logger.info("GPT Researcher API 已就绪 — 本地模式（无数据库持久化）")
    yield
    # 关闭
    shutdown_scheduler()
    logger.info("Research API 正在关闭")

# App initialization
app = FastAPI(lifespan=lifespan)

# Configure allowed origins for CORS
allowed_origins_env = os.getenv("CORS_ALLOW_ORIGINS")
ALLOWED_ORIGINS = (
    [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
    if allowed_origins_env
    else [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://app.gptr.dev",
    ]
)

# Standard JSON response - no custom MongoDB encoding needed

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Use default JSON response class

# 静态文件挂载（必须在 lifespan 之前完成，否则运行时 mount 不生效）
os.makedirs("outputs", exist_ok=True)
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")

# WebSocket manager
manager = WebSocketManager()

report_store = ReportStore(Path(os.getenv('REPORT_STORE_PATH', os.path.join('data', 'reports.json'))))

# Constants
DOC_PATH = os.getenv("DOC_PATH", "./my-docs")

# Startup event


# Lifespan events now handled in the lifespan context manager above


# Routes
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main frontend HTML page."""
    frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
    index_path = os.path.join(frontend_dir, "index.html")
    
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Frontend index.html not found")
    
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    return HTMLResponse(content=content)


@app.get("/.well-known/agent-discovery.json")
async def agent_discovery(request: Request):
    """Advertise GPT Researcher services via the Agent Discovery Protocol."""
    origin = str(request.base_url).rstrip("/")
    domain = request.url.hostname or request.headers.get("host", "")
    contact = os.getenv("AGENT_DISCOVERY_CONTACT")

    document = build_agent_discovery_document(origin=origin, domain=domain, contact=contact)
    response = JSONResponse(content=document)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

@app.get("/report/{research_id}")
async def read_report(request: Request, research_id: str):
    docx_path = os.path.join('outputs', f"{research_id}.docx")
    if not os.path.exists(docx_path):
        return {"message": "Report not found."}
    return FileResponse(docx_path)


# Simplified API routes - no database persistence
@app.get("/api/reports")
async def get_all_reports(report_ids: str = None):
    report_ids_list = report_ids.split(",") if report_ids else None
    reports = await report_store.list_reports(report_ids_list)
    return {"reports": reports}


@app.get("/api/reports/{research_id}")
async def get_report_by_id(research_id: str):
    report = await report_store.get_report(research_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"report": report}


@app.post("/api/reports")
async def create_or_update_report(request: Request):
    try:
        data = await request.json()
        research_id = data.get("id", "temp_id")

        now_ms = int(time.time() * 1000)
        existing = await report_store.get_report(research_id)
        incoming_timestamp = data.get("timestamp")
        timestamp = incoming_timestamp if isinstance(incoming_timestamp, int) else now_ms
        if existing and isinstance(existing.get("timestamp"), int):
            timestamp = max(timestamp, existing["timestamp"])

        report = {
            "id": research_id,
            "question": data.get("question"),
            "answer": data.get("answer"),
            "orderedData": data.get("orderedData") or [],
            "chatMessages": data.get("chatMessages") or [],
            "timestamp": timestamp,
        }

        await report_store.upsert_report(research_id, report)
        return {"success": True, "id": research_id}
    except Exception as e:
        logger.error(f"Error processing report creation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/reports/{research_id}")
async def update_report(research_id: str, request: Request):
    existing = await report_store.get_report(research_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Report not found")

    data = await request.json()
    now_ms = int(time.time() * 1000)

    updated = {
        **existing,
        **{k: v for k, v in data.items() if v is not None},
        "id": research_id,
        "timestamp": now_ms,
    }

    await report_store.upsert_report(research_id, updated)
    return {"success": True, "id": research_id}


@app.delete("/api/reports/{research_id}")
async def delete_report(research_id: str):
    existed = await report_store.delete_report(research_id)
    if not existed:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"success": True}


@app.get("/api/reports/{research_id}/chat")
async def get_report_chat(research_id: str):
    report = await report_store.get_report(research_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"chatMessages": report.get("chatMessages") or []}


@app.post("/api/reports/{research_id}/chat")
async def add_report_chat_message(research_id: str, request: Request):
    report = await report_store.get_report(research_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    message = await request.json()
    chat_messages = report.get("chatMessages") or []
    if isinstance(chat_messages, list):
        chat_messages = [*chat_messages, message]
    else:
        chat_messages = [message]

    now_ms = int(time.time() * 1000)
    updated = {
        **report,
        "chatMessages": chat_messages,
        "timestamp": now_ms,
    }

    await report_store.upsert_report(research_id, updated)
    return {"success": True, "id": research_id}


async def _notify_feishu(report: str, task: str):
    """Background helper — send report to Feishu (non-blocking), swallow errors."""
    try:
        loop = asyncio.get_running_loop()
        # Run the sync (urllib) call in a thread-pool so we don't block the loop
        ok = await loop.run_in_executor(None, send_report_to_feishu, report, task)
        if not ok:
            logger.warning("Feishu: notifier did not send (check .env config)")
        else:
            logger.info("Feishu: report push queued successfully")
    except Exception as e:
        logger.error(f"Feishu: notifier error — {e}")


async def write_report(research_request: ResearchRequest, research_id: str = None):
    # 统一意图识别（与 WebSocket 路径共用 intent_agent）
    intent = await _recognize_intent_for_rest(research_request.task)
    if intent["is_hot_list"]:
        research_request.report_type = "hot_list_report"

    report_information = await run_agent(
        task=research_request.task,
        report_type=research_request.report_type,
        report_source=research_request.report_source,
        source_urls=[],
        document_urls=[],
        tone=Tone[research_request.tone] if research_request.tone in Tone._member_map_ else Tone.Objective,
        websocket=None,
        stream_output=None,
        headers=research_request.headers,
        query_domains=[],
        config_path="",
        return_researcher=True,
        intent_result=intent,
    )

    docx_path = await write_md_to_word(report_information[0], research_id)
    pdf_path = await write_md_to_pdf(report_information[0], research_id)

    if research_request.report_type != "multi_agents":
        report, researcher = report_information
        response = {
            "research_id": research_id,
            "research_information": {
                "source_urls": researcher.get_source_urls(),
                "research_costs": researcher.get_costs(),
                "visited_urls": list(researcher.visited_urls),
                "research_images": researcher.get_research_images(),
                # "research_sources": researcher.get_research_sources(),  # Raw content of sources may be very large
            },
            "report": report,
            "docx_path": docx_path,
            "pdf_path": pdf_path
        }
    else:
        response = { "research_id": research_id, "report": "", "docx_path": docx_path, "pdf_path": pdf_path }

    return response

@app.post("/report/")
async def generate_report(research_request: ResearchRequest, background_tasks: BackgroundTasks):
    research_id = sanitize_filename(f"task_{int(time.time())}_{research_request.task}")

    if research_request.generate_in_background:
        background_tasks.add_task(write_report, research_request=research_request, research_id=research_id)
        return {"message": "Your report is being generated in the background. Please check back later.",
                "research_id": research_id}
    else:
        response = await write_report(research_request, research_id)
        return response


@app.get("/files/")
async def list_files():
    if not os.path.exists(DOC_PATH):
        os.makedirs(DOC_PATH, exist_ok=True)
    files = os.listdir(DOC_PATH)
    print(f"Files in {DOC_PATH}: {files}")
    return {"files": files}


@app.post("/api/multi_agents")
async def run_multi_agents():
    return await execute_multi_agents(manager)


@app.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    return await handle_file_upload(file, DOC_PATH)


@app.post("/api/cookies/upload")
async def upload_cookies(file: UploadFile = File(...)):
    """上传抖音/视频平台 cookies.txt"""
    backend_dir = Path(__file__).resolve().parent.parent
    save_path = backend_dir / "cookies.txt"
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)
    return JSONResponse(content={
        "message": "Cookie 已更新",
        "path": str(save_path),
        "size": len(content),
    })


@app.get("/api/cookies/status")
async def cookies_status():
    """检查 cookies 文件状态"""
    backend_dir = Path(__file__).resolve().parent.parent
    cookie_file = backend_dir / "cookies.txt"
    exists = cookie_file.exists()
    mtime = None
    size = 0
    if exists:
        stat = cookie_file.stat()
        size = stat.st_size
        mtime = stat.st_mtime
    return JSONResponse(content={
        "exists": exists,
        "path": str(cookie_file),
        "size": size,
        "mtime": mtime,
    })


@app.delete("/files/{filename}")
async def delete_file(filename: str):
    return await handle_file_deletion(filename, DOC_PATH)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await handle_websocket_communication(websocket, manager)
    except WebSocketDisconnect as e:
        # Disconnect with more detailed logging about the WebSocket disconnect reason
        logger.info(f"WebSocket disconnected with code {e.code} and reason: '{e.reason}'")
        await manager.disconnect(websocket)
    except Exception as e:
        # More general exception handling
        logger.error(f"Unexpected WebSocket error: {str(e)}")
        await manager.disconnect(websocket)

@app.post("/api/chat")
async def chat(chat_request: ChatRequest):
    """Process a chat request with a report and message history.

    Args:
        chat_request: ChatRequest object containing report text and message history

    Returns:
        JSON response with the assistant's message and any tool usage metadata
    """
    try:
        logger.info(f"Received chat request with {len(chat_request.messages)} messages")
        try:
            with open("/tmp/endpoint_debug.log", "a", encoding="utf-8") as _f:
                _f.write(f"[ENDPOINT /api/chat] report_len={len(chat_request.report or '')}, "
                         f"hot_items={len(chat_request.hot_items) if chat_request.hot_items else 0}, "
                         f"msg_count={len(chat_request.messages)}\n")
                if chat_request.hot_items:
                    _f.write(f"[ENDPOINT /api/chat] first_item={chat_request.hot_items[0].get('title','')[:50]}\n")
        except Exception:
            pass

        # Create chat agent with the report (and optional hot_items for hot-list follow-up)
        chat_agent = ChatAgentWithMemory(
            report=chat_request.report,
            config_path="default",
            headers=None,
            hot_items=chat_request.hot_items,
        )

        # Process the chat and get response with metadata
        response_content, tool_calls_metadata = await chat_agent.chat(chat_request.messages, None)
        logger.info(f"response_content: {response_content}")
        logger.info(f"Got chat response of length: {len(response_content) if response_content else 0}")
        
        if tool_calls_metadata:
            logger.info(f"Tool calls used: {json.dumps(tool_calls_metadata)}")

        # Format response as a ChatMessage object with role, content, timestamp and metadata
        response_message = {
            "role": "assistant",
            "content": response_content,
            "timestamp": int(time.time() * 1000),  # Current time in milliseconds
            "metadata": {
                "tool_calls": tool_calls_metadata
            } if tool_calls_metadata else None
        }

        logger.info(f"Returning formatted response: {json.dumps(response_message)[:100]}...")
        return {"response": response_message}
    except Exception as e:
        logger.error(f"Error processing chat request: {str(e)}", exc_info=True)
        return {"error": str(e)}


@app.post("/api/chat/feishu")
async def chat_forward_feishu(request: Request):
    """追问回复转发到飞书。"""
    try:
        data = await request.json()
        content = data.get("content", "")
        title = data.get("title", "AI 追问回复")
        if not content:
            return JSONResponse(status_code=400, content={"ok": False, "error": "内容为空"})

        from gpt_researcher.actions.notifiers import send_report_to_feishu
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, send_report_to_feishu, content, title)
        if ok:
            return {"ok": True, "message": "已推送到飞书"}
        return JSONResponse(status_code=500, content={"ok": False, "error": "飞书推送失败（检查 .env 中 FEISHU_WEBHOOK_URL 是否配置）"})
    except Exception as e:
        logger.error(f"chat/feishu failed: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.post("/api/reports/{research_id}/chat")
async def research_report_chat(research_id: str, request: Request):
    """Handle chat requests for a specific research report.
    Directly processes the raw request data to avoid validation errors.
    """
    try:
        # Get raw JSON data from request
        data = await request.json()
        try:
            with open("/tmp/endpoint_debug.log", "a", encoding="utf-8") as _f:
                _f.write(f"[ENDPOINT /api/reports/{research_id}/chat] "
                         f"report_len={len(data.get('report','') or '')}, "
                         f"hot_items={len(data.get('hot_items',[]) or [])}, "
                         f"msg_count={len(data.get('messages',[]) or [])}\n")
        except Exception:
            pass

        # Create chat agent with the report (and optional hot_items)
        chat_agent = ChatAgentWithMemory(
            report=data.get("report", ""),
            config_path="default",
            headers=None,
            hot_items=data.get("hot_items"),
        )

        # Process the chat and get response with metadata
        response_content, tool_calls_metadata = await chat_agent.chat(data.get("messages", []), None)
        
        if tool_calls_metadata:
            logger.info(f"Tool calls used: {json.dumps(tool_calls_metadata)}")

        # Format response as a ChatMessage object
        response_message = {
            "role": "assistant",
            "content": response_content,
            "timestamp": int(time.time() * 1000),
            "metadata": {
                "tool_calls": tool_calls_metadata
            } if tool_calls_metadata else None
        }

        return {"response": response_message}
    except Exception as e:
        logger.error(f"Error in research report chat: {str(e)}", exc_info=True)
        return {"error": str(e)}

# ============= 热榜研究 API =============

class HotAskRequest(BaseModel):
    question: str
    push_feishu: bool = True


class HotPlatformsResponse(BaseModel):
    platforms: list[dict]


@app.get("/api/hot/platforms")
async def hot_platforms():
    """返回所有支持的热榜平台列表。"""
    return {"platforms": get_supported_platforms()}


@app.post("/api/hot/ask")
async def hot_ask_api(req: HotAskRequest):
    """通过 LangChain Agent 进行交互式热榜问答。

    自主判断用户问题涉及的平台 → 抓取 + 爬取 → 生成结构化摘要报告。

    自动推飞书: .env 设置 HOT_PUSH_FEISHU=true，每次 agent 输出都会自动推送到群，
    无需客户端传任何标志。
    """
    try:
        report = await hot_ask(req.question)
        if not report:
            return {"report": "", "pushed": False}

        feishu_configured = os.getenv("FEISHU_WEBHOOK_URL") or os.getenv("FEISHU_APP_ID")
        auto_push = os.getenv("HOT_PUSH_FEISHU", "").lower() in ("1", "true", "yes")
        should_push = req.push_feishu or (auto_push and feishu_configured)

        if should_push and feishu_configured:
            from gpt_researcher.actions.notifiers import send_report_to_feishu
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(
                loop.run_in_executor(
                    None, send_report_to_feishu, report,
                    f"🔍 {req.question[:30]}"
                )
            )
        return {
            "report": report,
            "pushed": bool(should_push and feishu_configured),
        }
    except Exception as e:
        logger.error(f"hot_ask failed: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/hot/run")
async def hot_run_api(req: dict = None):
    """手动触发完整热榜研究流水线（与定时任务调用同一个 job）。"""
    try:
        report = await run_hot_pipeline(push_feishu=True)
        return {"ok": True, "chars": len(report)}
    except Exception as e:
        logger.error(f"hot_run failed: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/hot/status")
async def hot_status():
    """查看定时任务是否运行中，返回下次执行时间。"""
    from hot_research.scheduler import _scheduler
    info: dict = {"running": _scheduler is not None}
    if _scheduler:
        jobs = []
        for j in _scheduler.get_jobs():
            jobs.append({
                "id": j.id,
                "name": j.name,
                "next_run": str(j.next_run_time) if j.next_run_time else None,
            })
        info["jobs"] = jobs
    return info


class HotResearchRequest(BaseModel):
    """手动触发两阶段流水线的请求体。"""
    platforms: list[str] | None = None
    max_items_per_platform: dict[str, int] | None = None
    max_text_items: int = 10
    push_feishu: bool = True


@app.post("/api/hot/research")
async def hot_research_api(req: HotResearchRequest):
    """两阶段热榜研究:
    1) 抓取原始热榜（标题+热度+URL）
    2) 爬取文章 + 大模型摘要
    3) 按阶段推送到飞书
    """
    try:
        from hot_research.pipeline import fetch_raw_hot_lists, generate_report_from_raw, _push_to_feishu
        from hot_research.daily_hot_api import PLATFORMS

        # 规则1: 用户没指定 → 拉全部；规则2: 已指定 → 也拉全部（用其他参数区分主辅）
        raw_platforms = req.platforms if req.platforms else [p[0] for p in PLATFORMS]
        raw = await fetch_raw_hot_lists(raw_platforms, req.max_items_per_platform)
        raw_info = {
            c: len(items) for c, items in raw.items() if c != "_metadata"
        }

        reports = await generate_report_from_raw(raw, req.max_text_items)

        if req.push_feishu:
            await _push_to_feishu(reports)

        return {
            "ok": True,
            "raw_items": raw_info,
            "report_sections": len(reports),
        }
    except Exception as e:
        logger.error(f"hot_research failed: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


class HotQuickRequest(BaseModel):
    """一键研究请求体: Pipeline(抓原始) → Agent(加工) → 飞书。

    用户只用输入想做什么，系统自动完成其余。
    """
    question: str = ""
    platforms: list[str] | None = None
    push_feishu: bool = True


@app.post("/api/hot/quick")
async def hot_quick_api(req: HotQuickRequest):
    """端到端一键热榜研究。

    流程:
    1. 抓取目标平台原始热榜
    2. 把原始数据连同用户问题一起喂给 LangChain Agent
    3. Agent 自行决定格式，生成报告（口播稿/分析报告/摘要等）
    4. 推送到飞书

    示例:
      {"question": "给抖音TOP5写2分钟口播稿"}
      {"question": "分析B站当前热点趋势", "platforms": ["bilibili"]}
      {"question": "全站热点摘要，每条30字"}
    """
    try:
        # Stage 1: 根据规则决定拉取哪些平台
        # 规则1: 用户没指定 → 拉全部 9 个平台
        # 规则2: 用户指定了 → 该平台 + 其他平台辅助
        from hot_research.daily_hot_api import PLATFORMS, detect_platforms_in_query
        from hot_research import ask

        all_platform_codes = [p[0] for p in PLATFORMS]  # 全部 9 个

        if req.platforms:
            # 用户指定了 → 规则2：其他平台也要
            specified = req.platforms
            supplementary = [p for p in all_platform_codes if p not in specified]
            target_platforms = req.platforms  # 主平台在前
            platform_note = (
                f"用户指定了 {', '.join(specified)}。"
                f"规则2：请同时拉取其他平台辅助参考: {', '.join(supplementary)}。"
            )
        else:
            # 用户没指定 → 规则1：全部平台
            target_platforms = all_platform_codes
            platform_note = f"用户没指定平台。规则1：必须拉取全部 9 个平台: {', '.join(all_platform_codes)}。"

        # Stage 2: Agent 生成报告（把规则注入问题，强制 agent 遵守）
        enriched_q = (
            f"{req.question}\n\n"
            f"[系统提示（必须严格遵守）: {platform_note}\n"
            f"对每个平台先用 fetch_platform_hot 拿列表，再用 find_related_news 在其他平台找相关新闻做交叉验证，"
            f"用 fetch_article 爬取正文（抖音/B站等视频页改用 find_related_news 找文字报道替代）。"
            f"最后按用户要求格式生成报告，报告开头注明覆盖了哪些平台。]"
        )
        report = await ask(enriched_q)
        if not report:
            return JSONResponse(status_code=500, content={"error": "agent returned empty"})

        # Stage 3: auto push to Feishu
        feishu_configured = os.getenv("FEISHU_WEBHOOK_URL") or os.getenv("FEISHU_APP_ID")
        auto_push = os.getenv("HOT_PUSH_FEISHU", "").lower() in ("1", "true", "yes")
        pushed = False
        if req.push_feishu or (auto_push and feishu_configured):
            from gpt_researcher.actions.notifiers import send_report_to_feishu
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(
                loop.run_in_executor(
                    None, send_report_to_feishu, report,
                    f"📋 {req.question[:30]}"
                )
            )
            pushed = True

        return {
            "report": report,
            "platforms_used": target_platforms,
            "pushed": pushed,
        }
    except Exception as e:
        logger.error(f"hot_quick failed: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============= 追问回复导出 API =============

class ChatExportRequest(BaseModel):
    content: str                       # markdown 内容
    format: str = "md"                 # "md" | "pdf" | "docx"
    filename: str = "AI回复"           # 下载文件名（不含扩展名）


def _render_pdf_to_bytes(content: str) -> bytes:
    """用 fpdf2 把 markdown 文本渲染成 PDF bytes（支持中文）。

    不依赖 WeasyPrint，只需 fpdf2 + ttf/ttc 中文字体。
    纯同步函数，由 run_in_executor 调用。
    """
    from fpdf import FPDF
    from pathlib import Path
    import re

    # 中文字体候选路径（Docker 镜像 / 开发机）
    proj_root = Path(__file__).resolve().parent.parent.parent
    font_candidates = [
        proj_root / "backend" / "static" / "fonts" / "wqy-zenhei.ttc",
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path("/usr/share/fonts/truetype/arphic/ukai.ttc"),
        Path("/usr/share/fonts/truetype/arphic/uming.ttc"),
    ]
    font_path = next((str(p) for p in font_candidates if p.exists()), None)

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)

    if font_path:
        pdf.add_font("cn", "", font_path)
        pdf.add_font("cn", "B", font_path)
        body_font = ("cn", "", 11)
        bold_font = ("cn", "B", 11)
    else:
        body_font = ("Helvetica", "", 10)
        bold_font = ("Helvetica", "B", 10)

    pdf.add_page()

    # 朴素 markdown 渲染：## 标题、**正文**、列表项、普通段落
    lines = content.split("\n")
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            pdf.ln(3)
            continue
        if line.startswith("# "):
            pdf.set_font(*body_font); pdf.set_font("cn" if font_path else "Helvetica", "B", 16)
            pdf.multi_cell(0, 8, line[2:].strip())
            pdf.ln(2)
        elif line.startswith("## "):
            pdf.set_font("cn" if font_path else "Helvetica", "B", 13)
            pdf.multi_cell(0, 7, line[3:].strip())
            pdf.ln(1)
        elif line.startswith(("### ", "- ", "* ")):
            txt = line.lstrip("#* ").strip()
            pdf.set_font(*body_font)
            pdf.multi_cell(0, 6, f"• {txt}")
        else:
            # 行内 **bold** 简化为纯文本（fpdf2 不支持行内富文本，按普通行处理）
            txt = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
            pdf.set_font(*body_font)
            pdf.multi_cell(0, 6, txt)

    return pdf.output()


@app.post("/api/chat/export")
async def chat_export(req: ChatExportRequest):
    """把追问回复导出为 Markdown / PDF / DOCX。

    对 PDF / DOCX 直接返回文件流 + Content-Disposition，前端统一用 blob 下载，
    避免跨 host / 静态文件挂载问题。
    """
    from fastapi.responses import StreamingResponse
    import traceback as _tb, re as _re

    try:
        from utils import write_md_to_word

        # 安全化文件名：仅保留字母数字、中文、_-.，不强制三段式拆分
        raw_name = (req.filename or "AI回复").strip()
        safe_name = _re.sub(r"[^\w一-鿿\-.]", "_", raw_name)[:60] or "AI回复"
        logger.info(f"[export] format={req.format} filename={safe_name} content_len={len(req.content)}")

        if req.format == "md":
            # 直接返回 markdown JSON，前端用 blob 下载
            return {"content": req.content, "filename": f"{safe_name}.md"}

        if req.format == "pdf":
            # fpdf2 方案：不依赖 WeasyPrint，直接渲染 bytes
            pdf_bytes = await asyncio.get_running_loop().run_in_executor(
                None, _render_pdf_to_bytes, req.content
            )
            if not pdf_bytes:
                return JSONResponse(status_code=500, content={"error": "PDF 生成失败"})
            download_name = f"{safe_name}.pdf"
            media_type = "application/pdf"
            blob = pdf_bytes
        elif req.format == "docx":
            # DOCX：统一写到 outputs/ 绝对路径，避免 CWD 漂移（体积可能较大，用线程跑）
            import urllib

            def _gen_docx():
                from utils import write_md_to_word
                proj_root = Path(__file__).resolve().parent.parent.parent
                out_dir = proj_root / "outputs"
                out_dir.mkdir(exist_ok=True)
                old_cwd = os.getcwd()
                os.chdir(proj_root)  # write_md_to_word 用相对路径，切到 proj_root 确保 outputs/ 落在正确位置
                try:
                    return asyncio.run(write_md_to_word(req.content, safe_name))
                finally:
                    os.chdir(old_cwd)

            loop = asyncio.get_running_loop()
            rel_path = await loop.run_in_executor(None, _gen_docx)
            if not rel_path:
                return JSONResponse(status_code=500, content={"error": "DOCX 生成失败"})
            rel_unquoted = urllib.parse.unquote(rel_path)
            proj_root = Path(__file__).resolve().parent.parent.parent
            abs_path = (proj_root / rel_unquoted).resolve()
            if not abs_path.exists():
                logger.error(f"[export] DOCX missing: abs={abs_path} rel={rel_unquoted} cwd={os.getcwd()}")
                return JSONResponse(status_code=500, content={"error": "DOCX 文件不存在", "path": str(abs_path)})
            blob = abs_path.read_bytes()
            download_name = f"{safe_name}.docx"
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            return JSONResponse(status_code=400, content={"error": f"不支持的格式: {req.format}"})

        from urllib.parse import quote
        # RFC 5987：filename*=UTF-8''xxx 支持中文
        content_disposition = (
            f'attachment; filename="{download_name}"; '
            f"filename*=UTF-8''{quote(download_name)}"
        )

        def iterfile():
            # 确保 chunk 是 bytes（某些生成路径返回 bytearray）
            yield bytes(blob) if isinstance(blob, (bytes, bytearray)) else blob

        return StreamingResponse(
            iterfile(),
            media_type=media_type,
            headers={"Content-Disposition": content_disposition},
        )
    except Exception as e:
        logger.error(f"[export] FAILED format={req.format}: {e}\n{_tb.format_exc()}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============= 追问回复转发飞书 API =============


class ChatFeishuRequest(BaseModel):
    content: str                       # markdown 内容
    title: str = "AI 追问回复"         # 飞书消息标题


@app.post("/api/chat/feishu")
async def chat_feishu(req: ChatFeishuRequest):
    """把追问回复推送到飞书群。

    需要 .env 里配置 FEISHU_WEBHOOK_URL 或 (FEISHU_APP_ID + FEISHU_APP_SECRET)。
    """
    try:
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(
            None, send_report_to_feishu, req.content, req.title, "gpt-researcher-chat"
        )
        if ok:
            return {"ok": True, "message": "已成功推送到飞书"}
        else:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "飞书推送失败，请检查 .env 中 FEISHU_WEBHOOK_URL 或 FEISHU_APP_ID / FEISHU_APP_SECRET 配置"},
            )
    except Exception as e:
        logger.error(f"chat_feishu failed: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
