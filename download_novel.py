"""
Novel Downloader for 'Лабиринт монстров' (The Labyrinth of the Monsters)
Extracts all chapters from ranobes.com via Jina Reader, with atomic caching,
exponential backoff retries, resume support, and export to JSON and JSONL.
"""

import hashlib
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from curl_cffi import requests

TOC_FILE = "chapters_toc.json"
CACHE_DIR = "chapters_cache"
FINAL_JSON = "labyrinth_of_the_monsters.json"
FINAL_JSONL = "labyrinth_of_the_monsters.jsonl"
CONCURRENCY = 4
MAX_RETRIES = 5

def clean_jina_text(raw_text: str) -> str:
    """Clean Jina Reader output into pure chapter story text."""
    marker = "Markdown Content:"
    idx = raw_text.find(marker)
    if idx != -1:
        content = raw_text[idx + len(marker):].strip()
    else:
        content = raw_text.strip()

    # Remove leading decorative markers like *** or ---
    content = re.sub(r"^(?:\*{3,}|-{3,})\s*", "", content)
    # Remove trailing comments section if any
    content = re.sub(r"\n\s*Комментарии.*$", "", content, flags=re.DOTALL | re.IGNORECASE)
    return content.strip()

def parse_chapter_num(title: str) -> float:
    """Extract numeric chapter order (handles 'Глава 389-390' -> 389.0)."""
    m = re.search(r"(\d+)", title)
    return float(m.group(1)) if m else 0.0

def is_cached_valid(filepath: str) -> bool:
    if not os.path.exists(filepath):
        return False
    try:
        if os.path.getsize(filepath) < 300:
            return False
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            text = data.get("text", "")
            return len(text) >= 200
    except Exception:
        return False

def fetch_single_chapter(chapter_info: dict, index: int, total: int) -> dict:
    cid = chapter_info["id"]
    title = chapter_info["title"]
    link = chapter_info["link"]
    cache_path = os.path.join(CACHE_DIR, f"{cid}.json")

    # Check cache
    if is_cached_valid(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    jina_url = f"https://r.jina.ai/{link}"
    headers = {
        "X-Timeout": "35",
        "X-No-Cache": "false"
    }

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Small jitter to prevent burst hammering
            time.sleep(random.uniform(0.1, 0.4))
            
            r = requests.get(jina_url, headers=headers, impersonate="chrome124", timeout=45)
            
            if r.status_code == 200:
                raw_text = r.text
                if "AssertionFailureError" in raw_text or "Timeout was reached" in raw_text:
                    raise RuntimeError("Jina upstream timeout error")
                
                clean_text = clean_jina_text(raw_text)
                if len(clean_text) < 200:
                    raise ValueError(f"Extracted text too short ({len(clean_text)} chars)")
                
                char_count = len(clean_text)
                word_count = len(clean_text.split())
                sha256 = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
                ch_num = parse_chapter_num(title)

                record = {
                    "id": cid,
                    "order_index": index,
                    "chapter_num": ch_num,
                    "title": title,
                    "url": link,
                    "text": clean_text,
                    "char_count": char_count,
                    "word_count": word_count,
                    "sha256": sha256,
                    "fetched_at": int(time.time()),
                }

                # Atomic write to cache
                tmp_path = cache_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(record, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, cache_path)

                print(f"[{index:03d}/{total:03d}] OK: {title} ({char_count} chars)")
                return record

            elif r.status_code == 429:
                wait_time = 15 + attempt * 5
                print(f"[{index:03d}] Rate limited (429). Sleeping {wait_time}s...")
                time.sleep(wait_time)
            elif r.status_code == 422:
                # Upstream timeout
                wait_time = 2 * attempt + random.uniform(0.5, 1.5)
                time.sleep(wait_time)
            else:
                print(f"[{index:03d}] HTTP {r.status_code} on attempt {attempt}")
                time.sleep(2 * attempt)

        except Exception as e:
            last_error = e
            wait_time = 2 * attempt + random.uniform(0.5, 2.0)
            # print(f"[{index:03d}] Error: {e} (attempt {attempt}), retrying in {wait_time:.1f}s")
            time.sleep(wait_time)

    raise RuntimeError(f"Failed to fetch {title} ({link}) after {MAX_RETRIES} attempts. Last error: {last_error}")

def assemble_book(chapters: list[dict], toc_data: dict):
    print("\n--- Assembling final book artifacts ---")
    
    # Sort chapters by chapter_num / order_index
    chapters.sort(key=lambda c: (c["chapter_num"], c["order_index"]))
    
    total_chars = sum(c["char_count"] for c in chapters)
    total_words = sum(c["word_count"] for c in chapters)
    
    book_meta = {
        "title": toc_data.get("book_title", "Лабиринт монстров"),
        "original_title": "The Labyrinth of the Monsters / 异兽迷城",
        "author": "Peng Pai",
        "source": "ranobes.com",
        "book_id": toc_data.get("book_id", 615982),
        "total_chapters": len(chapters),
        "total_characters": total_chars,
        "total_words": total_words,
        "chapters": chapters
    }

    # 1. Save Full JSON
    print(f"Writing {FINAL_JSON}...")
    with open(FINAL_JSON, "w", encoding="utf-8") as f:
        json.dump(book_meta, f, ensure_ascii=False, indent=2)
    
    # 2. Save JSONL (ideal for streaming & AI training/RAG)
    print(f"Writing {FINAL_JSONL}...")
    with open(FINAL_JSONL, "w", encoding="utf-8") as f:
        for ch in chapters:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")

    print("\n" + "="*50)
    print(f"SUCCESSFULLY DOWNLOADED FULL BOOK!")
    print(f"Book: {book_meta['title']}")
    print(f"Total Chapters: {len(chapters)}")
    print(f"Total Words: {total_words:,}")
    print(f"Total Characters: {total_chars:,}")
    print(f"Output JSON:  {FINAL_JSON} ({os.path.getsize(FINAL_JSON) / 1024 / 1024:.2f} MB)")
    print(f"Output JSONL: {FINAL_JSONL} ({os.path.getsize(FINAL_JSONL) / 1024 / 1024:.2f} MB)")
    print("="*50 + "\n")

def main():
    os.makedirs(CACHE_DIR, exist_ok=True)

    if not os.path.exists(TOC_FILE):
        print(f"Error: {TOC_FILE} not found! Run extract_toc.py first.")
        sys.exit(1)

    with open(TOC_FILE, "r", encoding="utf-8") as f:
        toc_data = json.load(f)

    raw_chapters = toc_data.get("chapters", [])
    total_chapters = len(raw_chapters)
    print(f"Loaded TOC with {total_chapters} chapters.")

    # Check how many are already cached
    cached_count = sum(1 for c in raw_chapters if is_cached_valid(os.path.join(CACHE_DIR, f"{c['id']}.json")))
    print(f"Already cached: {cached_count}/{total_chapters} chapters.")

    downloaded = []
    failed = []

    t_start = time.time()
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        future_to_ch = {
            executor.submit(fetch_single_chapter, ch, idx + 1, total_chapters): ch
            for idx, ch in enumerate(raw_chapters)
        }
        for future in as_completed(future_to_ch):
            ch = future_to_ch[future]
            try:
                res = future.result()
                downloaded.append(res)
            except Exception as e:
                print(f"FAILED: {ch['title']} ({ch['link']}): {e}")
                failed.append(ch)

    elapsed = time.time() - t_start
    print(f"\nDownloaded: {len(downloaded)}/{total_chapters} in {elapsed:.1f}s ({elapsed/60:.1f} min)")

    if failed:
        print(f"WARNING: {len(failed)} chapters failed. Rerun script to retry them.")
    else:
        assemble_book(downloaded, toc_data)

if __name__ == "__main__":
    main()
