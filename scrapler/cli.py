"""
Scrapler Command Line Interface.
"""

import argparse
import json
import os
import sys
from .engine import scrape_url
from .crawler import crawl_site
from . import __version__

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _print_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_fetch(args):
    tier = int(args.tier) if args.tier is not None else None
    result = scrape_url(
        args.url,
        force_tier=tier,
        allow_tier3=args.allow_tier3,
        timeout=args.timeout,
        cache_ttl=args.cache,
        allow_browser=not args.no_browser,
    )
    if args.json:
        data = result.to_dict()
        data["text_length"] = len(result.text)
        _print_json(data)
    else:
        cached = " (cached)" if result.from_cache else ""
        print(f"[{result.tier_used}] {result.title} ({len(result.text)} chars, {result.elapsed:.2f}s){cached}")
        if result.error:
            print(f"  error: {result.error}")
        print("-" * 60)
        print(result.text[:1000])
        if len(result.text) > 1000:
            print("\n... [truncated] ...")


def cmd_crawl(args):
    if not args.json:
        print(f"Starting Scrapler Spider crawl: {args.url} (max pages: {args.max_pages})")
    items = crawl_site(
        start_url=args.url,
        max_pages=args.max_pages,
        match_pattern=args.match if args.match else None,
        rate_limit=args.rate_limit,
        stealth=args.stealth,
        concurrency=args.concurrency,
        obey_robots=args.robots,
        max_depth=args.depth,
    )
    if args.json:
        _print_json([item.__dict__ for item in items])
        return
    print(f"\n[OK] Crawl finished. Successfully retrieved {len(items)} page(s):")
    for idx, item in enumerate(items, 1):
        print(f"  {idx}. [{item.status}] {item.title} -> {item.url} ({len(item.text)} chars)")


def cmd_search(args):
    from .search import search, search_and_fetch

    common = dict(
        engines=args.engines or None,
        max_results=args.max_results,
        lang=args.lang,
        timeout=args.timeout,
        cache_ttl=0 if args.no_cache else args.cache,
        respect_cooldown=not args.ignore_cooldown,
    )
    pages = []
    if args.fetch:
        response, pages = search_and_fetch(
            args.query, fetch_top=args.fetch, allow_browser=not args.no_browser, **common
        )
    else:
        response = search(args.query, **common)

    if args.json:
        data = response.to_dict()
        if pages:
            data["pages"] = [p.to_dict() for p in pages]
        _print_json(data)
        return

    print(f"Search: {response.query!r}  ({response.elapsed:.2f}s)")
    for rep in response.reports:
        extra = f" — {rep.error}" if rep.error else ""
        print(f"  · {rep.engine:<13} {rep.status:<8} {rep.count:>3} hits  {rep.elapsed:.2f}s{extra}")
    print("-" * 60)
    for idx, hit in enumerate(response.hits, 1):
        print(f"{idx:>2}. {hit.title}")
        print(f"    {hit.url}")
        if hit.snippet:
            print(f"    {hit.snippet[:220]}")
        print(f"    [{'+'.join(hit.engines)}  score={hit.score:.4f}]")
    for page in pages:
        print("=" * 60)
        print(f"[{page.tier_used}] {page.title} — {page.url} ({len(page.text)} chars, {page.elapsed:.2f}s)")
        if page.error:
            print(f"  error: {page.error}")
        print(page.text[: args.chars])


def cmd_engines(args):
    from .search import ENGINES, ALIASES, resolve_engines

    defaults = set(resolve_engines(None))
    print("Search engines:")
    for e in ENGINES.values():
        if e.available:
            state = "ready"
        else:
            state = "needs " + ", ".join(v for v in e.requires if not os.environ.get(v))
        default = " (default)" if e.name in defaults else ""
        print(f"  {e.name:<13} {e.kind:<8} w={e.weight:<4} {state:<32} {e.description}{default}")
    print("\nAliases: " + ", ".join(f"{k}={'+'.join(v)}" for k, v in ALIASES.items() if k != "all") + ", all")


def cmd_cache(args):
    from .cache import get_cache

    prefix = {"all": "", "search": "search:", "pages": "page:", "cooldowns": "cooldown:"}[args.what]
    removed = get_cache().clear(prefix)
    print(f"Removed {removed} cache entr{'y' if removed == 1 else 'ies'} ({args.what}).")


def cmd_doctor(args):
    print("=== Scrapler System Doctor ===")

    try:
        import curl_cffi  # noqa: F401
        print(" [OK] Tier 0 (curl_cffi): Available (Chrome TLS impersonation)")
    except Exception as e:
        print(f" [WARN] Tier 0 (curl_cffi): Unavailable ({e})")

    try:
        import scrapling  # noqa: F401
        print(" [OK] Tier 1 (Scrapling Fetcher): Available")
    except Exception as e:
        print(f" [WARN] Tier 1 (Scrapling Fetcher): Unavailable ({e})")

    try:
        import patchright  # noqa: F401
        print(" [OK] Tier 2 (Scrapling StealthyFetcher): Available (Patchright Chromium)")
    except Exception as e:
        print(f" [WARN] Tier 2 (Scrapling StealthyFetcher): Unavailable ({e})")

    from .engine import POWERSKILLS_PATH
    if os.path.exists(POWERSKILLS_PATH):
        print(" [OK] Tier 3 (PowerSkills Edge CDP): Available (Opt-in via --allow-tier3)")
    else:
        print(f" [INFO] Tier 3 (PowerSkills): Script not found at {POWERSKILLS_PATH}")

    try:
        import trafilatura  # noqa: F401
        print(" [OK] Main-content extraction: trafilatura available")
    except Exception:
        print(" [INFO] trafilatura missing: falling back to full-page text")

    try:
        import sqlite_vec  # noqa: F401
        import fastembed  # noqa: F401
        print(" [OK] Vector Engine: sqlite-vec & FastEmbed available (CPU ONNX)")
    except Exception as e:
        print(f" [WARN] Vector Engine: Missing dependencies ({e})")

    from .search import ENGINES
    ready = [e.name for e in ENGINES.values() if e.available]
    missing = [e.name for e in ENGINES.values() if not e.available]
    print(f" [OK] Search engines ready: {', '.join(ready)}")
    if missing:
        print(f" [INFO] Search engines needing keys/config: {', '.join(missing)} (see `scrapler engines`)")

    from .cache import scrapler_home
    print(f"Scrapler version: {__version__}  |  state dir: {scrapler_home()}")
    print("==============================")


def main():
    parser = argparse.ArgumentParser(description="Scrapler - 4-Tier Web Scraping, Crawling & Meta Search Engine")
    parser.add_argument("-v", "--version", action="version", version=f"scrapler {__version__}")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # fetch
    fetch_p = subparsers.add_parser("fetch", help="Scrape a single URL using 4-tier cascade")
    fetch_p.add_argument("url", help="Target URL")
    fetch_p.add_argument("--tier", type=int, choices=[0, 1, 2, 3], help="Force specific tier")
    fetch_p.add_argument("--allow-tier3", action="store_true", help="Allow fallback to Tier 3 Edge CDP")
    fetch_p.add_argument("--no-browser", action="store_true", help="HTTP tiers only (never launch Chromium)")
    fetch_p.add_argument("--timeout", type=int, default=15, help="HTTP timeout in seconds")
    fetch_p.add_argument("--cache", type=float, default=0, metavar="SECONDS", help="Cache successful result for N seconds")
    fetch_p.add_argument("--json", action="store_true", help="Output JSON")

    # crawl
    crawl_p = subparsers.add_parser("crawl", help="Recursively crawl a website using Scrapling Spider")
    crawl_p.add_argument("url", help="Start URL")
    crawl_p.add_argument("--max-pages", type=int, default=15, help="Max pages limit")
    crawl_p.add_argument("--match", default="", help="URL substring filter")
    crawl_p.add_argument("--rate-limit", type=float, default=0.5, help="Delay between requests")
    crawl_p.add_argument("--concurrency", type=int, default=4, help="Parallel requests")
    crawl_p.add_argument("--depth", type=int, default=None, help="Max link depth from the start URL")
    crawl_p.add_argument("--robots", action="store_true", help="Obey robots.txt")
    crawl_p.add_argument("--stealth", action="store_true", help="Run with stealth browser")
    crawl_p.add_argument("--json", action="store_true", help="Output JSON (includes page text)")

    # search
    search_p = subparsers.add_parser("search", help="Meta-search several engines and fuse results (RRF)")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("-e", "--engines", default="",
                          help="Comma list of engines/aliases, e.g. 'bing,ddg', 'web,dev', 'all' (see `scrapler engines`)")
    search_p.add_argument("-n", "--max-results", type=int, default=10, help="Results after fusion")
    search_p.add_argument("--lang", default="", help="Language/region hint, e.g. uk, en")
    search_p.add_argument("--fetch", type=int, default=0, metavar="N", help="Also scrape the top N results")
    search_p.add_argument("--chars", type=int, default=800, help="Characters of page text to print with --fetch")
    search_p.add_argument("--no-browser", action="store_true", help="With --fetch: HTTP tiers only")
    search_p.add_argument("--timeout", type=float, default=10, help="Per-engine timeout in seconds")
    search_p.add_argument("--cache", type=float, default=3600, metavar="SECONDS", help="Search result cache TTL")
    search_p.add_argument("--no-cache", action="store_true", help="Bypass the search cache")
    search_p.add_argument("--ignore-cooldown", action="store_true", help="Query engines even if recently blocked")
    search_p.add_argument("--json", action="store_true", help="Output JSON")

    # engines
    subparsers.add_parser("engines", help="List search engines and whether they are configured")

    # cache
    cache_p = subparsers.add_parser("cache-clear", help="Clear cached search results, pages or engine cooldowns")
    cache_p.add_argument("what", nargs="?", default="all", choices=["all", "search", "pages", "cooldowns"])

    # doctor
    subparsers.add_parser("doctor", help="Check dependencies and browser readiness")

    args = parser.parse_args()
    handlers = {
        "fetch": cmd_fetch,
        "crawl": cmd_crawl,
        "search": cmd_search,
        "engines": cmd_engines,
        "cache-clear": cmd_cache,
        "doctor": cmd_doctor,
    }
    handlers[args.subcommand](args)


if __name__ == "__main__":
    main()
