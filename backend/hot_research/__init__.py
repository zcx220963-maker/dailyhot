"""热榜研究模块 — 生成内容丰富的热榜报告。

子模块
------------
daily_hot_api : 从 DailyHotApi 抓取原始热榜数据
scraper       : 从 URL 爬取文章正文（BeautifulSoup + 浏览器回退）
pipeline      : 主入口 — run_pipeline()
scheduler     : FastAPI 内嵌的 APScheduler 定时任务
langchain_agent : 交互式热榜问答 LangChain Agent
"""
from .daily_hot_api import fetch_hot, fetch_all
from .pipeline import run_pipeline, fetch_raw_hot_lists, generate_report_from_raw
from .pipeline import _push_to_feishu
from .scheduler import init_scheduler, shutdown_scheduler
from .langchain_agent import ask

__all__ = [
    "fetch_hot",
    "fetch_all",
    "fetch_raw_hot_lists",
    "generate_report_from_raw",
    "run_pipeline",
    "init_scheduler",
    "shutdown_scheduler",
    "ask",
]
