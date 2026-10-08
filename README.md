# Scrapler 🕷️⚡

> **Intelligent 4-Tier Web Scraping, Recursive Crawling, Multi-Engine Meta Search & Local Hybrid Vector Retrieval**

`Scrapler` is a modern, high-performance data acquisition and knowledge engine designed for Python and Windows AI agent workflows. It completely replaces bloated browser setups by enforcing an automated **cascade hierarchy**, using a real browser UI strictly as an opt-in last resort.

---

## 🚀 Key Features & Architecture

```
                    ┌───────────────────────────┐
                    │       URL to Fetch        │
                    └─────────────┬─────────────┘
                                  │
                                  ▼
      ┌───────────────────────────────────────────────────────┐
      │ TIER 0: curl_cffi (Chrome TLS/JA3 impersonation)      │
      │ ⚡ Fastest, sub-second, zero-browser overhead         │
      └───────────────────────────┬───────────────────────────┘
                                  │ Fail / 403 / 429 / Challenge
                                  ▼
      ┌───────────────────────────────────────────────────────┐
      │ TIER 1: Scrapling Fetcher (Stealth HTTP + Markdown)   │
      │ 🛡️ Adaptive stealth headers & clean RAG formatting    │
      └───────────────────────────┬───────────────────────────┘
                                  │ Fail / Dynamic JS / Turnstile
                                  ▼
      ┌───────────────────────────────────────────────────────┐
      │ TIER 2: Scrapling StealthyFetcher (Patchright Engine) │
      │ 🤖 Headless Chromium, Cloudflare Turnstile bypass     │
      └───────────────────────────┬───────────────────────────┘
                                  │ Only if Login/Profile required
                                  │ or explicit --allow-tier3
                                  ▼
      ┌───────────────────────────────────────────────────────┐
      │ TIER 3: PowerSkills + Real Edge CDP (Last Resort)     │
      │ 🌐 Real browser session, active cookies, user profile │
      └───────────────────────────────────────────────────────┘
```

### ⚡ Efficiency rules of the cascade
- **Dead pages stop immediately**: 404 / 410 / 401 / 400 never launch a browser (was ~6 s of browser retries, now ~0.5 s).
- **Non-HTML is handled, not escalated**: plain text / JSON / XML returned as-is, PDFs extracted with `pypdf`, images and archives reported as `unsupported`.
- **JS-only shells** (empty SPA markup) skip Tier 1 and go straight to the browser.
- **Per-domain memory**: once a domain needed a higher tier because of anti-bot blocking, its next URLs start at that tier.
- **Pooled HTTP sessions** per thread; browser tiers capped at 2 concurrent instances.
- **`scrape_many()`** fetches a list in parallel (5 docs pages: 2.8 s sequential → 1.2 s).
- **Main-content extraction** via `trafilatura` (menus, cookie banners and footers dropped), with full-text fallback for index pages.
- **Optional SQLite cache** (`cache_ttl` / `--cache`) shared across processes in `~/.scrapler/cache.db`.
- Challenge detection no longer flags large normal pages that merely *mention* Cloudflare in a script/CSP config.

### 🔎 Multi-Engine Meta Search
Engines run **in parallel**, rankings are merged with **Reciprocal Rank Fusion** (a URL that several engines agree on rises to the top), results are deduplicated by normalized URL, cached for an hour, and an engine that rate-limits or shows a captcha is put on a **10-minute cooldown** so later calls skip it.

| Engine | Type | Needs |
|---|---|---|
| `duckduckgo` | web (HTML) | — |
| `bing` | web (HTML) | — |
| `yahoo` | web (HTML, Bing-backed, weight 0.6) | — |
| `brave` | web (API, independent index) | `BRAVE_API_KEY` |
| `google` | web (Programmable Search API) | `GOOGLE_API_KEY` + `GOOGLE_CSE_ID` |
| `searxng` | web (your own instance, JSON) | `SEARXNG_URL` |
| `wikipedia` | vertical (language-aware via `--lang`) | — |
| `stackoverflow` | vertical | optional `STACKEXCHANGE_KEY` |
| `github` | vertical (repositories) | optional `GITHUB_TOKEN` |
| `hackernews` | vertical (Algolia) | — |
| `arxiv` | vertical (papers) | — |

Aliases: `ddg`, `wiki`, `so`, `gh`, `hn`, and groups `web`, `dev` (stackoverflow+github+hackernews), `science` (arxiv+wikipedia), `all`.
Default engine set = `duckduckgo,bing,yahoo` plus every configured API engine.

Engines that were tested and deliberately left out (2026-10): Google HTML (JS wall; even through the stealth browser it takes ~60 s and returns opaque `/goto` links), Mojeek (captcha), Brave HTML (429), Startpage / Qwant / Ecosia (block plain HTTP).
Bing quirk handled in code: cookieless clients randomly get a degraded "first word only" result set, and any extra parameter (`first=`, `setlang=`) makes it permanent — Scrapler sends plain `q` only, checks query-term coverage and retries on a fresh connection.

### 🧠 Local Hybrid Vector Retrieval
- **`sqlite-vec`**: Native C-extension virtual table `vec0` supporting `DISTANCE_METRIC=COSINE` and `project PARTITION KEY`.
- **`FastEmbed`**: 100% offline, CPU-optimized multilingual embeddings (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensions).
- **RRF (Reciprocal Rank Fusion)**: Combines keyword search (BM25) and semantic vector distance without score normalization distortions.
- **Cross-Lingual Search**: Ukrainian queries semantically match English technical documentation.
- Pinned to the CPU ONNX provider (no CUDA probe errors on every load); set `SCRAPLER_USE_CUDA=1` to opt in.

### 🕸️ Scrapling Spider Crawler
- High-throughput recursive documentation crawler built on **Scrapling Spider API** (`--concurrency`, default 4).
- Never schedules more URLs than `--max-pages`, so no request is wasted past the limit.
- URL normalization (fragments, tracking params, trailing slash, http/https) before dedup; media/binary links skipped.
- `--stealth` runs the crawl through a pooled stealth-browser session; `--robots` obeys robots.txt; `--depth` limits link depth.

---

## 📦 Installation

```bash
git clone https://github.com/guns96x/scrapler.git
cd scrapler

# Install dependencies
pip install -r requirements.txt

# Install headless Chromium for Tier 2
patchright install chromium
```

---

## 🛠️ CLI Usage

### 1. System Health Check
```bash
python -m scrapler.cli doctor
```

### 2. Fetch Single URL (Automated Cascade)
```bash
# Automatic 4-tier cascade (Tier 0 -> Tier 1 -> Tier 2)
python -m scrapler.cli fetch "https://example.com"

# Force specific tier (e.g. Tier 2 for JS-heavy sites)
python -m scrapler.cli fetch "https://quotes.toscrape.com/js/" --tier 2

# Output JSON
python -m scrapler.cli fetch "https://httpbin.org/html" --json

# Allow Tier 3 fallback to real Edge CDP if authenticated session needed
python -m scrapler.cli fetch "https://internal-docs.example.com" --allow-tier3
```

# HTTP tiers only, cache the result for a day
python -m scrapler.cli fetch "https://example.com" --no-browser --cache 86400
```

### 3. Recursive Documentation Crawl
```bash
python -m scrapler.cli crawl "https://quotes.toscrape.com/" --max-pages 15 --rate-limit 0.5 --concurrency 4
```

### 4. Meta Search
```bash
# Default engines (duckduckgo, bing, yahoo + configured API engines)
python -m scrapler.cli search "sqlite fts5 bm25 ranking"

# Pick engines / groups, Ukrainian region hint
python -m scrapler.cli search "Київ метро історія" -e web,wiki --lang uk

# Developer sources only, JSON output
python -m scrapler.cli search "tokio select macro" -e dev --json

# Search and scrape the top 3 results in parallel
python -m scrapler.cli search "asyncio semaphore" --fetch 3 --no-browser

# Which engines are ready / need keys
python -m scrapler.cli engines

# Drop cached results or engine cooldowns
python -m scrapler.cli cache-clear cooldowns
```

---

## 🐍 Python API

```python
from scrapler import scrape_url, scrape_many, crawl_site, search, search_and_fetch, VectorStore

# 1. Fetching a page
result = scrape_url("https://example.com")
print(result.tier_used)  # "tier0_curl_cffi"
print(result.title)      # "Example Domain"
print(result.text)       # Markdown / clean text

# 2. Recursive spider crawl
pages = crawl_site("https://docs.python.org/3/tutorial/", max_pages=10)
for p in pages:
    print(p.url, p.title)

# 3. Multi-engine search (parallel engines + RRF fusion)
resp = search("sqlite fts5 bm25", engines="web,dev", max_results=10)
for hit in resp.hits:
    print(hit.score, hit.engines, hit.url)
for rep in resp.reports:          # per-engine status: ok / cached / blocked / cooldown / skipped
    print(rep.engine, rep.status, rep.count)

# 4. Search + fetch top pages in parallel
resp, pages = search_and_fetch("asyncio semaphore", fetch_top=3, allow_browser=False)

# 5. Batch fetching
results = scrape_many(["https://a.example", "https://b.example"], workers=8, cache_ttl=3600)

# 6. Vector store & KNN
store = VectorStore("vectors.db")
store.index_texts([
    {"id": 1, "project": "golf5", "text": "ECU Bosch EDC16U34 flashing guide."},
    {"id": 2, "project": "cooking", "text": "Pizza dough recipe."}
])

results = store.search_knn("як прошити блок управління", project="golf5")
print(results)  # Finds chunk 1 via multilingual cosine similarity
```

---

## 🧪 Testing

Offline tests (parsers, fusion, cascade logic, cache, vectors) run by default:
```bash
python -m pytest tests -q
```

Live tests (real sites, real search engines, browser tier) are opt-in:
```bash
SCRAPLER_NET_TESTS=1 python -m pytest tests -q
```

State (cache, cooldowns) lives in `~/.scrapler`; override with `SCRAPLER_HOME`.

---

## 📄 License
MIT License.
