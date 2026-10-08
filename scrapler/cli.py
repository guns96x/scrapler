"""
Scrapler Command Line Interface.
"""

import argparse
import json
import sys
from .engine import scrape_url
from .crawler import crawl_site
from . import __version__


def cmd_fetch(args):
    tier = int(args.tier) if args.tier is not None else None
    result = scrape_url(args.url, force_tier=tier, allow_tier3=args.allow_tier3)
    if args.json:
        data = {
            "url": result.url,
            "title": result.title,
            "tier_used": result.tier_used,
            "status_code": result.status_code,
            "text_length": len(result.text),
            "text": result.text
        }
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"[{result.tier_used}] {result.title} ({len(result.text)} chars)")
        print("-" * 60)
        print(result.text[:1000])
        if len(result.text) > 1000:
            print("\n... [truncated] ...")


def cmd_crawl(args):
    print(f"Starting Scrapler Spider crawl: {args.url} (max pages: {args.max_pages})")
    items = crawl_site(
        start_url=args.url,
        max_pages=args.max_pages,
        match_pattern=args.match if args.match else None,
        rate_limit=args.rate_limit,
        stealth=args.stealth
    )
    print(f"\n[OK] Crawl finished. Successfully retrieved {len(items)} page(s):")
    for idx, item in enumerate(items, 1):
        print(f"  {idx}. [{item.status}] {item.title} -> {item.url} ({len(item.text)} chars)")


def cmd_doctor(args):
    print("=== Scrapler System Doctor ===")
    
    # Tier 0
    try:
        import curl_cffi
        print(" [OK] Tier 0 (curl_cffi): Available (Chrome TLS impersonation)")
    except Exception as e:
        print(f" [WARN] Tier 0 (curl_cffi): Unavailable ({e})")

    # Tier 1
    try:
        import scrapling
        print(" [OK] Tier 1 (Scrapling Fetcher): Available")
    except Exception as e:
        print(f" [WARN] Tier 1 (Scrapling Fetcher): Unavailable ({e})")

    # Tier 2
    try:
        import patchright
        print(" [OK] Tier 2 (Scrapling StealthyFetcher): Available (Patchright Chromium)")
    except Exception as e:
        print(f" [WARN] Tier 2 (Scrapling StealthyFetcher): Unavailable ({e})")

    # Tier 3
    import os
    from .engine import POWERSKILLS_PATH
    if os.path.exists(POWERSKILLS_PATH):
        print(" [OK] Tier 3 (PowerSkills Edge CDP): Available (Opt-in via --allow-tier3)")
    else:
        print(f" [INFO] Tier 3 (PowerSkills): Script not found at {POWERSKILLS_PATH}")

    # Vectors
    try:
        import sqlite_vec
        import fastembed
        print(" [OK] Vector Engine: sqlite-vec & FastEmbed available (CPU ONNX)")
    except Exception as e:
        print(f" [WARN] Vector Engine: Missing dependencies ({e})")

    print(f"Scrapler version: {__version__}")
    print("==============================")


def main():
    parser = argparse.ArgumentParser(description="Scrapler - 4-Tier Web Scraping & Crawling Engine")
    parser.add_argument("-v", "--version", action="version", version=f"scrapler {__version__}")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # fetch
    fetch_p = subparsers.add_parser("fetch", help="Scrape a single URL using 4-tier cascade")
    fetch_p.add_argument("url", help="Target URL")
    fetch_p.add_argument("--tier", type=int, choices=[0, 1, 2, 3], help="Force specific tier")
    fetch_p.add_argument("--allow-tier3", action="store_true", help="Allow fallback to Tier 3 Edge CDP")
    fetch_p.add_argument("--json", action="store_true", help="Output JSON")

    # crawl
    crawl_p = subparsers.add_parser("crawl", help="Recursively crawl a website using Scrapling Spider")
    crawl_p.add_argument("url", help="Start URL")
    crawl_p.add_argument("--max-pages", type=int, default=15, help="Max pages limit")
    crawl_p.add_argument("--match", default="", help="URL substring filter")
    crawl_p.add_argument("--rate-limit", type=float, default=0.5, help="Delay between requests")
    crawl_p.add_argument("--stealth", action="store_true", help="Run with stealth browser")

    # doctor
    subparsers.add_parser("doctor", help="Check dependencies and browser readiness")

    args = parser.parse_args()
    if args.subcommand == "fetch":
        cmd_fetch(args)
    elif args.subcommand == "crawl":
        cmd_crawl(args)
    elif args.subcommand == "doctor":
        cmd_doctor(args)


if __name__ == "__main__":
    main()
