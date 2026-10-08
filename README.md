# Scrapler 🕷️⚡

> **Intelligent 4-Tier Web Scraping, Recursive Crawling & Local Hybrid Vector Retrieval Engine**

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

### 🧠 Local Hybrid Vector Retrieval
- **`sqlite-vec`**: Native C-extension virtual table `vec0` supporting `DISTANCE_METRIC=COSINE` and `project PARTITION KEY`.
- **`FastEmbed`**: 100% offline, CPU-optimized multilingual embeddings (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensions).
- **RRF (Reciprocal Rank Fusion)**: Combines keyword search (BM25) and semantic vector distance without score normalization distortions.
- **Cross-Lingual Search**: Ukrainian queries semantically match English technical documentation.

### 🕸️ Scrapling Spider Crawler
- High-throughput recursive documentation crawler built on **Scrapling Spider API**.
- Built-in rate limiting, same-domain constraints, canonical URL defragmentation, and duplicate scheduling guards.

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

### 3. Recursive Documentation Crawl
```bash
python -m scrapler.cli crawl "https://quotes.toscrape.com/" --max-pages 15 --rate-limit 0.5
```

---

## 🐍 Python API

```python
from scrapler import scrape_url, crawl_site, VectorStore

# 1. Fetching a page
result = scrape_url("https://example.com")
print(result.tier_used)  # "tier0_curl_cffi"
print(result.title)      # "Example Domain"
print(result.text)       # Markdown / clean text

# 2. Recursive spider crawl
pages = crawl_site("https://docs.python.org/3/tutorial/", max_pages=10)
for p in pages:
    print(p.url, p.title)

# 3. Vector store & KNN
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

Run the full test suite:
```bash
python -m unittest discover tests
```

---

## 📄 License
MIT License.
