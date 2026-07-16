"""Browser manager skill for GPT Researcher.

This module provides the BrowserManager class that handles web scraping
and content extraction from URLs.
"""

from gpt_researcher.utils.workers import WorkerPool

from ..actions.utils import stream_output
from ..actions.web_scraping import scrape_urls
from ..scraper.utils import get_image_hash


class BrowserManager:
    """Manages web browsing and content scraping for research.

    This class handles URL scraping, content extraction, and image
    selection during the research process.

    Attributes:
        researcher: The parent GPTResearcher instance.
        worker_pool: Pool of workers for parallel scraping.
    """

    def __init__(self, researcher):
        """Initialize the BrowserManager.

        Args:
            researcher: The GPTResearcher instance that owns this manager.
        """
        self.researcher = researcher
        self.worker_pool = WorkerPool(
            researcher.cfg.max_scraper_workers,
            researcher.cfg.scraper_rate_limit_delay
        )

    async def browse_urls(self, urls: list[str]) -> list[dict]:
        """
        Scrape content from a list of URLs.

        Args:
            urls (list[str]): list of URLs to scrape.

        Returns:
            list[dict]: list of scraped content results.
        """
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "scraping_urls",
                f"🌐 正在从 {len(urls)} 个网址抓取内容...",
                self.researcher.websocket,
            )

        scraped_content, images = await scrape_urls(
            urls, self.researcher.cfg, self.worker_pool
        )
        self.researcher.add_research_sources(scraped_content)
        new_images = self.select_top_images(images, k=4)  # Select top 4 images
        self.researcher.add_research_images(new_images)

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "scraping_content",
                f"📄 已抓取 {len(scraped_content)} 页内容",
                self.researcher.websocket,
            )
            await stream_output(
                "logs",
                "scraping_images",
                f"🖼️ 已从 {len(images)} 张图片中选择了 {len(new_images)} 张新图片",
                self.researcher.websocket,
                True,
                new_images,
            )
            await stream_output(
                "logs",
                "scraping_complete",
                f"🌐 抓取完成",
                self.researcher.websocket,
            )

            # 推送带有标题的来源信息，便于前端显示中文名+网址
            for item in scraped_content:
                url = item.get("url") or ""
                title = item.get("title") or ""
                if url:
                    await stream_output(
                        "logs",
                        "added_source_url",
                        f"✅ 已将来源「{title}」添加到研究队列：{url}\n",
                        self.researcher.websocket,
                        True,
                        {"url": url, "title": title},
                    )

        return scraped_content

    def select_top_images(self, images: list[dict], k: int = 2) -> list[str]:
        """
        Select most relevant images and remove duplicates based on image content.

        Args:
            images (list[dict]): list of image dictionaries with 'url' and 'score' keys.
            k (int): Number of top images to select if no high-score images are found.

        Returns:
            list[str]: list of selected image URLs.
        """
        unique_images = []
        seen_hashes = set()
        current_research_images = self.researcher.get_research_images()

        # Process images in descending order of their scores
        for img in sorted(images, key=lambda im: im["score"], reverse=True):
            img_hash = get_image_hash(img['url'])
            if (
                img_hash
                and img_hash not in seen_hashes
                and img['url'] not in current_research_images
            ):
                seen_hashes.add(img_hash)
                unique_images.append(img["url"])

                if len(unique_images) == k:
                    break

        return unique_images
