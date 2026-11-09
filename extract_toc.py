"""
Extract all chapters table of contents for 'Лабиринт монстров' from ranobes.com
via Jina Reader (bypassing ISP network blocks).
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from curl_cffi import requests

TOTAL_PAGES = 27
BOOK_ID = 615982
BASE_TOC_URL = "https://r.jina.ai/https://ranobes.com/chapters/{book_id}/page/{page}/"
TOC_FILE = "chapters_toc.json"

def fetch_page(page: int, retries: int = 5) -> list[dict]:
    url = BASE_TOC_URL.format(book_id=BOOK_ID, page=page)
    headers = {
        "X-Return-Format": "html",
        "X-Timeout": "30",
    }
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=headers, impersonate="chrome124", timeout=35)
            if r.status_code == 200:
                idx = r.text.find("window.__DATA__ = ")
                if idx != -1:
                    start = idx + len("window.__DATA__ = ")
                    data, _ = json.JSONDecoder().raw_decode(r.text[start:])
                    chaps = data.get("chapters", [])
                    print(f"[Page {page:02d}/{TOTAL_PAGES}] Fetched {len(chaps)} chapters")
                    return chaps
                else:
                    print(f"[Page {page:02d}] __DATA__ not found in HTML (attempt {attempt})")
            else:
                print(f"[Page {page:02d}] HTTP {r.status_code} (attempt {attempt})")
        except Exception as e:
            print(f"[Page {page:02d}] Error: {e} (attempt {attempt})")
        time.sleep(2 * attempt)
    raise RuntimeError(f"Failed to fetch page {page} after {retries} attempts")

def main():
    all_chapters = {}
    print(f"Fetching {TOTAL_PAGES} TOC pages...")
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_page, p): p for p in range(1, TOTAL_PAGES + 1)}
        for f in as_completed(futures):
            page_num = futures[f]
            try:
                chaps = f.result()
                for c in chaps:
                    cid = c["id"]
                    all_chapters[cid] = c
            except Exception as e:
                print(f"Fatal error on page {page_num}: {e}")

    # Convert to list and sort
    chapter_list = list(all_chapters.values())
    
    # Extract chapter number for sorting
    def get_num(ch):
        title = ch.get("title", "")
        m = re.search(r"(\d+)", title)
        return int(m.group(1)) if m else 0

    chapter_list.sort(key=get_num)
    print(f"Total unique chapters fetched: {len(chapter_list)}")
    if chapter_list:
        print(f"First: {chapter_list[0]['title']} ({chapter_list[0]['link']})")
        print(f"Last:  {chapter_list[-1]['title']} ({chapter_list[-1]['link']})")

    with open(TOC_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "book_id": BOOK_ID,
            "book_title": "Лабиринт монстров",
            "total_chapters": len(chapter_list),
            "chapters": chapter_list
        }, f, ensure_ascii=False, indent=2)
    print(f"Saved TOC to {TOC_FILE}")

if __name__ == "__main__":
    main()
