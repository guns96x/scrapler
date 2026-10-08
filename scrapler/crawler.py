"""
Scrapler Crawler: Recursive Documentation & Site Crawler using Scrapling Spider API.

Efficiency rules:
  - Never schedules more URLs than max_pages, so no fetch is wasted past the limit.
  - URLs are normalized (fragment, tracking params, trailing slash) before dedup.
  - Binary/media links are skipped before they are requested.
  - stealth=True swaps the HTTP session for a pooled stealth browser session.
"""

import logging
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional, Set
from .engine import extract

SKIP_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp", ".avif",
    ".pdf", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z", ".rar", ".xz",
    ".mp3", ".mp4", ".webm", ".avi", ".mov", ".wav", ".ogg",
    ".exe", ".msi", ".dmg", ".apk", ".iso", ".bin", ".deb", ".rpm",
    ".css", ".js", ".mjs", ".map", ".woff", ".woff2", ".ttf", ".eot",
    ".xml", ".rss", ".atom", ".json",
)
TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"fbclid", "gclid", "ref", "ref_src", "share", "replytocom"}


@dataclass
class CrawlResult:
    url: str
    title: str
    text: str
    status: int


def normalize_crawl_url(url: str) -> str:
    """Drop fragment and tracking params; trim trailing slash (except root)."""
    url, _ = urllib.parse.urldefrag(url)
    p = urllib.parse.urlsplit(url)
    query = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
        if not k.lower().startswith(TRACKING_PREFIXES) and k.lower() not in TRACKING_KEYS
    ]
    path = p.path.rstrip("/") if len(p.path) > 1 else (p.path or "/")
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), path, urllib.parse.urlencode(query), ""))


def crawl_site(
    start_url: str,
    allowed_domains: Optional[List[str]] = None,
    max_pages: int = 20,
    match_pattern: Optional[str] = None,
    rate_limit: float = 0.5,
    stealth: bool = False,
    concurrency: int = 4,
    obey_robots: bool = False,
    max_depth: Optional[int] = None,
) -> List[CrawlResult]:
    """
    Recursively crawl websites/documentation trees using Scrapling Spider.
    Extracts main-content markdown for each page.
    """
    from scrapling.spiders import Spider, Response, Request

    fetch_start, _ = urllib.parse.urldefrag(start_url)
    clean_start = normalize_crawl_url(fetch_start)
    allowed = {d.lower() for d in (allowed_domains or [urllib.parse.urlsplit(fetch_start).netloc])}

    scraped_items: List[CrawlResult] = []
    # Dedup keys ignore the scheme: many sites serve the same page on http and https.
    def key(url: str) -> str:
        return url.split("://", 1)[-1]

    scheduled_urls: Set[str] = {key(clean_start)}
    depth_of = {key(clean_start): 0}

    class ScraplerSpider(Spider):
        name = "scrapler_spider"
        start_urls = [fetch_start]
        concurrent_requests = max(1, concurrency)
        download_delay = rate_limit
        robots_txt_obey = obey_robots
        logging_level = logging.WARNING

        async def start_requests(self):
            for u in self.start_urls:
                yield Request(u, sid=self._session_manager.default_session_id, meta={"depth": 0})

        def configure_sessions(self, manager):
            if stealth:
                from scrapling.fetchers import AsyncStealthySession
                manager.add("default", AsyncStealthySession(
                    headless=True,
                    disable_resources=True,
                    block_ads=True,
                    solve_cloudflare=True,
                    max_pages=max(1, min(concurrency, 4)),
                ))
            else:
                from scrapling.fetchers import FetcherSession
                manager.add("default", FetcherSession(impersonate="chrome"))

        async def parse(self, response: Response):
            if len(scraped_items) >= max_pages:
                return

            resp_url = str(response.url)
            cur_url = normalize_crawl_url(resp_url)
            html = getattr(response, "html_content", "") or response.body.decode("utf-8", "replace")
            title, markdown_text = extract(html, resp_url)

            item = CrawlResult(url=cur_url, title=title or cur_url, text=markdown_text, status=response.status)
            scraped_items.append(item)
            yield {"url": item.url, "title": item.title, "status": item.status}

            # When the page redirects (e.g. apex to www, or http to https), associate
            # the landing URL with scheduled_urls so links pointing back to it don't re-schedule it.
            scheduled_urls.add(key(cur_url))
            if len(scraped_items) == 1:
                # The start URL may redirect (http -> https, apex -> www): follow that host too.
                allowed.add(urllib.parse.urlsplit(resp_url).netloc.lower())

            # Retrieve depth from request/response metadata to survive redirects, falling back to URL key
            meta = getattr(response, "meta", None) or getattr(getattr(response, "request", None), "meta", None) or {}
            depth = meta.get("depth")
            if depth is None:
                depth = depth_of.get(key(cur_url), 0)
            if max_depth is not None and depth >= max_depth:
                return

            for link in response.css("a::attr(href)").getall():
                if len(scheduled_urls) >= max_pages:
                    break
                if not link or link.startswith(("mailto:", "tel:", "javascript:", "#")):
                    continue
                # Resolve relative link against response.url (preserving path hierarchy and trailing slash)
                resolved_url = urllib.parse.urljoin(resp_url, link)
                fetch_url, _ = urllib.parse.urldefrag(resolved_url)
                p = urllib.parse.urlsplit(fetch_url)
                if p.scheme not in ("http", "https") or p.netloc.lower() not in allowed:
                    continue
                if p.path.lower().endswith(SKIP_EXTENSIONS):
                    continue
                clean_url = normalize_crawl_url(fetch_url)
                if match_pattern and match_pattern not in clean_url:
                    continue
                dedup_key = key(clean_url)
                if dedup_key not in scheduled_urls:
                    scheduled_urls.add(dedup_key)
                    depth_of[dedup_key] = depth + 1
                    yield response.follow(fetch_url, meta={"depth": depth + 1})

    ScraplerSpider().start()
    return scraped_items[:max_pages]
