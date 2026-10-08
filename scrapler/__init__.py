"""
Scrapler - 4-Tier Web Scraping, Recursive Crawling, Multi-Engine Search & Hybrid Vector Retrieval.
"""

from .engine import scrape_url, scrape_many, ScrapeResult
from .crawler import crawl_site, CrawlResult
from .search import search, search_and_fetch, SearchHit, SearchResponse, ENGINES
from .vectors import VectorStore, HybridRetriever

__version__ = "0.3.0"
__all__ = [
    "scrape_url",
    "scrape_many",
    "ScrapeResult",
    "crawl_site",
    "CrawlResult",
    "search",
    "search_and_fetch",
    "SearchHit",
    "SearchResponse",
    "ENGINES",
    "VectorStore",
    "HybridRetriever",
]
