"""
Scrapler - Modern 4-Tier Web Scraping, Recursive Crawling & Hybrid Vector Retrieval Engine.
"""

from .engine import scrape_url, ScrapeResult
from .crawler import crawl_site, CrawlResult
from .vectors import VectorStore, HybridRetriever

__version__ = "0.2.0"
__all__ = [
    "scrape_url",
    "ScrapeResult",
    "crawl_site",
    "CrawlResult",
    "VectorStore",
    "HybridRetriever",
]
