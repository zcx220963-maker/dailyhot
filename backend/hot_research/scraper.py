"""从热搜条目 URL 爬取文章正文。"""
import logging
import time
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 已知可以直接用 requests + BeautifulSoup 的域名
# 走快速路径，其余走更重的浏览器爬取
HTML_CANDIDATES = {
    "toutiao.com", "thepaper.cn", "36kr.com", "sspai.com",
    "v2ex.com", "juejin.cn", "baidu.com", "bilibili.com",
    "douyin.com",  # JS 重，但尝试正文接口
}


async def fetch_article_text(url: str, timeout: int = 12) -> tuple[str, str]:
    """尝试从 URL 抓取纯文本，返回 (文本, 标题)。

    策略:
    1. 视频链接直接跳过
    2. 快速路径 — requests + BeautifulSoup（适合新闻/文章页）
    3. 慢速路径 — 回退到项目自带的 Scraper
    """
    from hot_research.daily_hot_api import _proxy

    if not url or not url.startswith("http"):
        return "", ""

    # --- 快速路径: requests + BeautifulSoup ---
    try:
        text = _bs_fetch(url, timeout)
        if text and len(text.strip()) > 30:
            return text, ""
    except Exception as e:
        logger.debug(f"_bs_fetch 失败 {url}: {e}")

    # --- 慢速路径: 项目自带的 Scraper ---
    try:
        from gpt_researcher.scraper.scraper import Scraper
        from gpt_researcher.config.config import Config

        cfg = Config()
        scraper = Scraper(url, cfg)
        scraped = await scraper.async_run(url)
        if scraped:
            page = scraped[0]
            return page.get("raw_content", "") or "", page.get("title", "")
    except Exception as e:
        logger.debug(f"scraper_manager 失败 {url}: {e}")

    return "", ""


def _bs_fetch(url: str, timeout: int) -> str:
    """使用 requests + BeautifulSoup 抓取并清洗正文。"""
    import requests
    from bs4 import BeautifulSoup
    from hot_research.daily_hot_api import _proxy

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    resp = requests.get(url, timeout=timeout, headers=headers,
                        proxies=_proxy(), allow_redirects=True)
    if resp.status_code != 200:
        return ""

    # 只处理文本类内容
    ct = resp.headers.get("Content-Type", "")
    if "text" not in ct and "json" not in ct:
        return ""

    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.content, "lxml")

    # 去掉噪音标签
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # 优先取 article / main / body
    body = soup.find("article") or soup.find("main") or soup.body
    if not body:
        return ""

    text = "\n".join(line.strip() for line in body.stripped_strings if line.strip())
    # 太短的页面不视为有效文章
    if len(text) < 40:
        return ""
    # 截取约 2000 字，够总结用又不至于撑爆上下文
    return text[:2000]
