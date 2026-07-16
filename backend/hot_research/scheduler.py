"""APScheduler — 运行在 FastAPI 进程内部的定时任务。

定时任务:
  - 每天 09:00  → 上午推送
  - 每天 20:00  → 晚上推送
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_scheduler = None


def init_scheduler():
    """幂等启动 — 多次调用安全。"""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning(
            "未安装 apscheduler — 热榜定时任务已禁用。"
            "请运行 pip install apscheduler"
        )
        return None

    sched = AsyncIOScheduler()

    sched.add_job(
        _scheduled_job,
        CronTrigger(hour=9, minute=0),
        id="hot_am",
        name="热榜上午推送",
        misfire_grace_time=3600,
        coalesce=True,
    )
    sched.add_job(
        _scheduled_job,
        CronTrigger(hour=20, minute=0),
        id="hot_pm",
        name="热榜晚上推送",
        misfire_grace_time=3600,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    logger.info("★ 热榜定时任务已启动 — 每天 09:00 / 20:00")
    return _scheduler


def shutdown_scheduler():
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None


async def _scheduled_job():
    logger.info(f"★ 热榜定时任务触发于 {datetime.now():%H:%M}")
    try:
        from .pipeline import fetch_raw_hot_lists, generate_report_from_raw, _push_to_feishu

        # 阶段1: 获取原始数据（不调用大模型）
        raw_data = await fetch_raw_hot_lists()

        # 阶段2: 使用大模型加工
        # max_text_items: 每个平台多少条做大模型摘要
        # 每次大模型调用约 0.5-2 秒，20 条 × 9 个平台 ≈ 2-3 分钟
        reports = await generate_report_from_raw(raw_data, max_text_items=15)

        # 阶段3: 推送到飞书（每个平台一条消息）
        await _push_to_feishu(reports)

        logger.info("★ 热榜定时推送完成")
    except Exception as e:
        logger.error(f"★ 热榜定时推送失败: {e}", exc_info=True)
