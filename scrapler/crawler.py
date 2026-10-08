"""
Scrapler Crawler: Recursive Documentation & Site Crawler using Scrapling Spider API.
"""

import urllib.parse
from dataclasses import dataclass
from typing import List, Optional, Set
from .engine import extract_title, clean_html_to_markdown


@dataclass
class CrawlResult:
    url: str
    title: str
    text: str
    status: int


def crawl_site(
    start_url: str,
    allowed_domains: Optional[List[str]] = None,
    max_pages: int = 20,
    match_pattern: Optional[str] = None,
    rate_limit: float = 0.5,
    stealth: bool = False
) -> List[CrawlResult]:
    """
    Recursively crawl websites/documentation trees using Scrapling Spider.
    Extracts structured markdown for each page.
    """
    from scrapling.spiders import Spider, Response

    parsed_start = urllib.parse.urlparse(start_url)
    default_domain = parsed_start.netloc
    allowed = set(allowed_domains or [default_domain])

    scraped_items: List[CrawlResult] = []
    scheduled_urls: Set[str] = set()

    clean_start, _ = urllib.parse.urldefrag(start_url)
    scheduled_urls.add(clean_start)

    class ScraplerSpider(Spider):
        name = "scrapler_spider"
        start_urls = [clean_start]
        concurrent_requests = 1 if rate_limit >= 0.5 else 3
        download_delay = rate_limit

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.max_limit = max_pages

        async def parse(self, response: Response):
            if len(scraped_items) >= self.max_limit:
                return

            cur_url, _ = urllib.parse.urldefrag(response.url)
            html = getattr(response, "html_content", "") or (response.body.decode("utf-8", "replace") if hasattr(response, "body") else "")
            title = extract_title(html) or cur_url

            if callable(getattr(response, "markdown", None)):
                markdown_text = response.markdown()
            else:
                markdown_text = clean_html_to_markdown(html)

            item = CrawlResult(
                url=cur_url,
                title=title,
                text=markdown_text,
                status=response.status
            )
            scraped_items.append(item)
            yield item

            # Discover internal links
            if len(scraped_items) < self.max_limit:
                links = response.css("a::attr(href)").getall()
                for link in links:
                    if len(scraped_items) >= self.max_limit:
                        break
                    full_url = urllib.parse.urljoin(cur_url, link)
                    full_url, _ = urllib.parse.urldefrag(full_url)
                    p = urllib.parse.urlparse(full_url)

                    # Domain check
                    if p.netloc not in allowed:
                        continue
                    # Ignore anchors, non-http, media
                    if p.scheme not in ("http", "https"):
                        continue
                    if any(p.path.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz"]):
                        continue
                    # Match pattern
                    if match_pattern and match_pattern not in full_url:
                        continue

                    if full_url not in scheduled_urls:
                        scheduled_urls.add(full_url)
                        yield response.follow(full_url)

    spider = ScraplerSpider()
    spider.start()
    return scraped_items
