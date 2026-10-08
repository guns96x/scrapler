"""
Scrapler Search: multi-engine meta search with Reciprocal Rank Fusion.

Engines run in parallel; their rankings are fused with RRF (a URL that several
engines agree on rises to the top), deduplicated by normalized URL, cached in
SQLite, and an engine that gets rate-limited or captcha'd is put on a cooldown
so later calls skip it instead of wasting a request.

Keyless general web engines : duckduckgo, bing, yahoo
Keyless vertical engines    : wikipedia, stackoverflow, github, hackernews, arxiv
Configured via environment  : brave (BRAVE_API_KEY), searxng (SEARXNG_URL),
                              google (GOOGLE_API_KEY + GOOGLE_CSE_ID)

Not included on purpose (verified 2026-10-08): Google HTML needs JS and returns
opaque /goto links even through a stealth browser (~60 s); Mojeek serves a
captcha; Brave HTML answers 429; Startpage/Qwant/Ecosia block plain HTTP.
"""

import base64
import hashlib
import html as html_lib
import os
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional, Tuple, Any

from bs4 import BeautifulSoup

from .engine import get_http_session, is_challenge_or_blocked

API_USER_AGENT = "scrapler/0.3 (+https://github.com/guns96x/scrapler)"
DEFAULT_ENGINES = ("duckduckgo", "bing", "yahoo")
COOLDOWN_SECONDS = 600
SEARCH_CACHE_TTL = 3600

TRACKING_PARAMS = {"fbclid", "gclid", "yclid", "msclkid", "ref", "ref_src", "spm", "mc_cid", "mc_eid"}


class EngineBlocked(Exception):
    """The engine answered with a rate limit, captcha or challenge page."""


@dataclass
class SearchHit:
    url: str
    title: str
    snippet: str = ""
    engine: str = ""
    rank: int = 0
    engines: List[str] = field(default_factory=list)
    score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EngineReport:
    engine: str
    status: str  # ok | empty | blocked | error | cooldown | cached | skipped
    count: int = 0
    elapsed: float = 0.0
    error: str = ""


@dataclass
class SearchResponse:
    query: str
    hits: List[SearchHit]
    reports: List[EngineReport]
    elapsed: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "elapsed": round(self.elapsed, 3),
            "engines": [asdict(r) for r in self.reports],
            "hits": [h.to_dict() for h in self.hits],
        }


# -------------------------------------------------------------
# URL helpers
# -------------------------------------------------------------
_UNRESERVED_ASCII = set(
    b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
)


def _unquote_unreserved(path: str) -> str:
    """RFC 3986 section 2.3: decode ONLY unreserved characters; keep reserved/percent (%25, %2F) in uppercase."""
    def repl(m: re.Match) -> str:
        val = int(m.group(1), 16)
        if val in _UNRESERVED_ASCII:
            return chr(val)
        return f"%{m.group(1).upper()}"

    return re.sub(r"%([0-9a-fA-F]{2})", repl, path)


def normalize_url(url: str) -> str:
    """Canonical form used for deduplication (not for fetching)."""
    try:
        p = urllib.parse.urlsplit(url.strip())
        host = p.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host.startswith("m.") and "wikipedia.org" in host:
            host = host[2:]
        query = [
            (k, v)
            for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
        ]
        clean_path = _unquote_unreserved(p.path).rstrip("/") or "/"
        return urllib.parse.urlunsplit(("https", host, clean_path, urllib.parse.urlencode(sorted(query)), ""))
    except Exception:
        return url.strip()


def strip_tracking(url: str) -> str:
    """Remove tracking parameters but keep the URL fetchable."""
    try:
        p = urllib.parse.urlsplit(url)
        query = [
            (k, v)
            for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
        ]
        return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(query), ""))
    except Exception:
        return url


def decode_bing_url(href: str) -> str:
    """Bing wraps results as bing.com/ck/a?...&u=a1<base64url>; return the real target."""
    if "bing.com/ck/a" not in href:
        return href
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
    u = (q.get("u") or [""])[0]
    if u.startswith("a1"):
        u = u[2:]
    try:
        return base64.urlsafe_b64decode(u + "=" * (-len(u) % 4)).decode("utf-8", "replace")
    except Exception:
        return href


def decode_yahoo_url(href: str) -> str:
    """Yahoo wraps results as r.search.yahoo.com/.../RU=<quoted url>/RK=...; return the target."""
    m = re.search(r"/RU=([^/]+)/R[KS]=", href)
    return urllib.parse.unquote(m.group(1)) if m else href


def decode_ddg_url(href: str) -> str:
    """DuckDuckGo sometimes wraps results as //duckduckgo.com/l/?uddg=<quoted url>."""
    if "duckduckgo.com/l/" in href:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
        if q.get("uddg"):
            return q["uddg"][0]
    if href.startswith("//"):
        return "https:" + href
    return href


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(text or "")).strip()


def _strip_tags(text: str) -> str:
    return _clean(re.sub(r"<[^>]+>", " ", text or ""))


def _valid(url: str) -> bool:
    return url.startswith(("http://", "https://"))


# -------------------------------------------------------------
# HTTP helpers
# -------------------------------------------------------------
def _http(method: str, url: str, timeout: float, api: bool = False, fresh: bool = False, **kwargs: Any):
    if fresh:
        from curl_cffi import requests as cffi_requests
        session = cffi_requests.Session(impersonate="chrome")
    else:
        session = get_http_session()
    headers = kwargs.pop("headers", {}) or {}
    if api:
        headers.setdefault("User-Agent", API_USER_AGENT)
        headers.setdefault("Accept", "application/json")
    response = session.request(method, url, timeout=timeout, headers=headers, **kwargs)
    body = response.text
    if response.status_code in (403, 429, 503) or (not api and is_challenge_or_blocked(response.status_code, body)):
        raise EngineBlocked(f"HTTP {response.status_code}")
    has_results = bool(re.search(r"class=[\"'](result|b_algo|dd algo|algo\b|g[\"\s])", body[:50000]))
    if not api and not has_results and (
        response.status_code == 202
        or re.search(r"/sorry/index|id=[\"']anomaly|class=[\"']anomaly|id=[\"']infoDiv|class=[\"']g-recaptcha", body[:30000], re.I)
    ):
        raise EngineBlocked(f"rate limited (HTTP {response.status_code})")
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}")
    return response


def _soup(text: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(text, "lxml")
    except Exception:
        return BeautifulSoup(text, "html.parser")


# -------------------------------------------------------------
# HTML result parsers (pure functions, unit-tested offline)
# -------------------------------------------------------------
def parse_duckduckgo(page: str) -> List[SearchHit]:
    hits = []
    for div in _soup(page).select("div.result"):
        classes = div.get("class") or []
        if "result--ad" in classes or "result--no-result" in classes:
            continue
        a = div.select_one("a.result__a")
        if not a or not a.get("href"):
            continue
        url = decode_ddg_url(a["href"])
        if not _valid(url) or "duckduckgo.com/y.js" in url:
            continue
        snip = div.select_one(".result__snippet")
        hits.append(SearchHit(url, _clean(a.get_text()), _clean(snip.get_text()) if snip else ""))
    return hits


def parse_bing(page: str) -> List[SearchHit]:
    hits = []
    for li in _soup(page).select("li.b_algo"):
        a = li.select_one("h2 a")
        if not a or not a.get("href"):
            continue
        url = decode_bing_url(a["href"])
        if not _valid(url):
            continue
        p = li.select_one(".b_caption p") or li.select_one("p")
        snippet = ""
        if p:
            for date in p.select("span.news_dt"):
                date.decompose()
            snippet = _clean(p.get_text()).lstrip("· ").strip()
        hits.append(SearchHit(url, _clean(a.get_text()), snippet))
    return hits


def parse_yahoo(page: str) -> List[SearchHit]:
    hits = []
    for div in _soup(page).select("div.algo"):
        a = div.select_one("div.compTitle a")
        if not a or not a.get("href"):
            continue
        url = decode_yahoo_url(a["href"])
        if not _valid(url) or "r.search.yahoo.com" in url or "/cbclk" in url:
            continue
        h3 = div.select_one("h3")
        title = _clean(h3.get_text()) if h3 else _clean(a.get("aria-label") or a.get_text())
        snip = div.select_one("div.compText")
        snippet = ""
        if snip:
            for date in snip.select("span.fc-smoke"):
                date.decompose()
            snippet = _clean(snip.get_text())
        hits.append(SearchHit(url, title, snippet))
    return hits


# -------------------------------------------------------------
# Engine implementations: (query, limit, lang, timeout) -> hits
# -------------------------------------------------------------
_DDG_REGIONS = {"uk": "ua-uk", "en": "us-en", "ru": "ru-ru", "de": "de-de", "pl": "pl-pl", "fr": "fr-fr", "es": "es-es"}


def engine_duckduckgo(query: str, limit: int, lang: str, timeout: float) -> List[SearchHit]:
    hits: List[SearchHit] = []
    data = {"q": query, "b": ""}
    if lang:
        data["kl"] = _DDG_REGIONS.get(lang, lang)
    for page in range(3):
        resp = _http("POST", "https://html.duckduckgo.com/html/", timeout, data=data,
                     headers={"Referer": "https://html.duckduckgo.com/"})
        batch = parse_duckduckgo(resp.text)
        hits.extend(batch)
        if len(hits) >= limit or not batch:
            break
        # Next page: DDG's "Next" form carries the offset fields (explicitly match Next submit button).
        next_form = None
        for f in _soup(resp.text).select("div.nav-link form"):
            submit_btn = f.select_one("input[type='submit']")
            val = (submit_btn.get("value", "") if submit_btn else "").lower()
            if "next" in val:
                next_form = f
                break
        if not next_form:
            forms = _soup(resp.text).select("div.nav-link form")
            next_form = forms[-1] if forms else None
        if not next_form:
            break
        data = {i.get("name"): i.get("value", "") for i in next_form.select("input[name]")}
        if lang:
            data["kl"] = _DDG_REGIONS.get(lang, lang)
        time.sleep(0.3)
    return hits[:limit]


def term_coverage(hits: List[SearchHit], query: str) -> float:
    """
    Share of hits whose title/snippet mention at least two query terms (prefix match,
    so inflected Ukrainian/Russian forms count). 1.0 for one-term queries.
    """
    terms = [t[:5] for t in re.findall(r"\w+", query.lower()) if len(t) > 2]
    if len(terms) < 2 or not hits:
        return 1.0
    need = 2 if len(terms) < 4 else len(terms) // 2
    good = sum(1 for h in hits if sum(t in f"{h.title} {h.snippet}".lower() for t in terms) >= need)
    return good / len(hits)


def engine_bing(query: str, limit: int, lang: str, timeout: float) -> List[SearchHit]:
    # Bing randomly answers cookieless clients with a degraded "first word only" result
    # set, and any extra parameter (first=, setlang=, setmkt=) makes that consistent.
    # So: plain q only, one page, and retry on a fresh connection when the set looks degraded.
    url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query})
    best: List[SearchHit] = []
    best_cov = -1.0
    for attempt in range(3):
        hits = parse_bing(_http("GET", url, timeout, fresh=attempt > 0).text)
        cov = term_coverage(hits, query)
        if cov > best_cov:
            best, best_cov = hits, cov
        if cov >= 0.3:
            break
    return best[:limit]


def engine_yahoo(query: str, limit: int, lang: str, timeout: float) -> List[SearchHit]:
    hits: List[SearchHit] = []
    for page in range(3):
        params = {"p": query, "b": 1 + page * 7}
        resp = _http("GET", "https://search.yahoo.com/search?" + urllib.parse.urlencode(params), timeout)
        batch = parse_yahoo(resp.text)
        hits.extend(batch)
        if len(hits) >= limit or not batch:
            break
    return hits[:limit]


def engine_wikipedia(query: str, limit: int, lang: str, timeout: float) -> List[SearchHit]:
    lang = lang or "en"
    params = {"action": "query", "list": "search", "srsearch": query, "format": "json",
              "srlimit": min(limit, 50), "utf8": 1}
    data = _http("GET", f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params),
                 timeout, api=True).json()
    hits = []
    for item in data.get("query", {}).get("search", []):
        title = item.get("title", "")
        url = f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        hits.append(SearchHit(url, title, _strip_tags(item.get("snippet", ""))))
    return hits


def engine_stackoverflow(query: str, limit: int, lang: str, timeout: float) -> List[SearchHit]:
    params = {"q": query, "site": "stackoverflow", "order": "desc", "sort": "relevance",
              "pagesize": min(limit, 50), "filter": "default"}
    key = os.environ.get("STACKEXCHANGE_KEY")
    if key:
        params["key"] = key
    data = _http("GET", "https://api.stackexchange.com/2.3/search/advanced?" + urllib.parse.urlencode(params),
                 timeout, api=True).json()
    hits = []
    for item in data.get("items", []):
        meta = f"score {item.get('score', 0)}, {item.get('answer_count', 0)} answers"
        if item.get("is_answered"):
            meta += ", answered"
        tags = ", ".join(item.get("tags", [])[:5])
        hits.append(SearchHit(item["link"], _clean(item.get("title", "")), f"[{tags}] {meta}"))
    return hits


def engine_github(query: str, limit: int, lang: str, timeout: float) -> List[SearchHit]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    params = {"q": query, "per_page": min(limit, 50)}
    data = _http("GET", "https://api.github.com/search/repositories?" + urllib.parse.urlencode(params),
                 timeout, api=True, headers=headers).json()
    hits = []
    for item in data.get("items", []):
        meta = f"★{item.get('stargazers_count', 0)}"
        if item.get("language"):
            meta += f" · {item['language']}"
        if item.get("pushed_at"):
            meta += f" · pushed {item['pushed_at'][:10]}"
        hits.append(SearchHit(item["html_url"], item.get("full_name", ""),
                              f"{_clean(item.get('description') or '')} ({meta})".strip()))
    return hits


def engine_hackernews(query: str, limit: int, lang: str, timeout: float) -> List[SearchHit]:
    params = {"query": query, "hitsPerPage": min(limit, 50), "tags": "story"}
    data = _http("GET", "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode(params),
                 timeout, api=True).json()
    hits = []
    for item in data.get("hits", []):
        discussion = f"https://news.ycombinator.com/item?id={item.get('objectID')}"
        url = item.get("url") or discussion
        meta = f"{item.get('points', 0)} points, {item.get('num_comments', 0)} comments — {discussion}"
        hits.append(SearchHit(url, _clean(item.get("title") or ""), meta))
    return hits


def engine_arxiv(query: str, limit: int, lang: str, timeout: float) -> List[SearchHit]:
    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    search_query = " AND ".join(f"all:{t}" for t in terms)
    params = {"search_query": search_query, "max_results": min(limit, 50), "sortBy": "relevance"}
    resp = _http("GET", "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params), timeout, api=True)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(resp.content)
    hits = []
    for entry in root.findall("a:entry", ns):
        url = (entry.findtext("a:id", "", ns) or "").replace("http://", "https://")
        title = _clean(entry.findtext("a:title", "", ns))
        summary = _clean(entry.findtext("a:summary", "", ns))
        published = (entry.findtext("a:published", "", ns) or "")[:10]
        if url:
            hits.append(SearchHit(url, title, f"{published} — {summary[:300]}"))
    return hits


def engine_brave(query: str, limit: int, lang: str, timeout: float) -> List[SearchHit]:
    key = os.environ.get("BRAVE_API_KEY", "")
    params = {"q": query, "count": min(limit, 20)}
    if lang:
        params["search_lang"] = lang
    data = _http("GET", "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(params),
                 timeout, api=True, headers={"X-Subscription-Token": key}).json()
    return [
        SearchHit(r["url"], _clean(r.get("title", "")), _strip_tags(r.get("description", "")))
        for r in data.get("web", {}).get("results", [])
        if _valid(r.get("url", ""))
    ]


def engine_searxng(query: str, limit: int, lang: str, timeout: float) -> List[SearchHit]:
    base = os.environ.get("SEARXNG_URL", "").rstrip("/")
    params = {"q": query, "format": "json"}
    if lang:
        params["language"] = lang
    data = _http("GET", f"{base}/search?" + urllib.parse.urlencode(params), timeout, api=True).json()
    return [
        SearchHit(r["url"], _clean(r.get("title", "")), _clean(r.get("content", "")))
        for r in data.get("results", [])
        if _valid(r.get("url", ""))
    ][:limit]


def engine_google(query: str, limit: int, lang: str, timeout: float) -> List[SearchHit]:
    hits: List[SearchHit] = []
    for start in range(1, min(limit, 30) + 1, 10):
        params = {"key": os.environ.get("GOOGLE_API_KEY", ""), "cx": os.environ.get("GOOGLE_CSE_ID", ""),
                  "q": query, "num": 10, "start": start}
        if lang:
            params["lr"] = f"lang_{lang}"
        data = _http("GET", "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(params),
                     timeout, api=True).json()
        items = data.get("items", [])
        hits.extend(SearchHit(i["link"], _clean(i.get("title", "")), _clean(i.get("snippet", ""))) for i in items)
        if len(items) < 10:
            break
    return hits[:limit]


@dataclass
class Engine:
    name: str
    fn: Callable[[str, int, str, float], List[SearchHit]]
    kind: str  # web | vertical
    weight: float = 1.0
    requires: Tuple[str, ...] = ()
    description: str = ""

    @property
    def available(self) -> bool:
        return all(os.environ.get(var) for var in self.requires)


ENGINES: Dict[str, Engine] = {
    e.name: e
    for e in [
        Engine("duckduckgo", engine_duckduckgo, "web", 1.0, description="DuckDuckGo HTML endpoint"),
        Engine("bing", engine_bing, "web", 1.0, description="Bing HTML results"),
        # Yahoo's index is Bing's, so it mostly re-confirms Bing: weight it lower.
        Engine("yahoo", engine_yahoo, "web", 0.6, description="Yahoo HTML results (Bing-backed)"),
        Engine("brave", engine_brave, "web", 1.0, ("BRAVE_API_KEY",), "Brave Search API (independent index)"),
        Engine("google", engine_google, "web", 1.0, ("GOOGLE_API_KEY", "GOOGLE_CSE_ID"), "Google Programmable Search API"),
        Engine("searxng", engine_searxng, "web", 1.0, ("SEARXNG_URL",), "Self-hosted SearXNG instance (JSON API)"),
        Engine("wikipedia", engine_wikipedia, "vertical", 0.8, description="Wikipedia full-text search (lang-aware)"),
        Engine("stackoverflow", engine_stackoverflow, "vertical", 0.8, description="Stack Overflow questions"),
        Engine("github", engine_github, "vertical", 0.8, description="GitHub repositories"),
        Engine("hackernews", engine_hackernews, "vertical", 0.6, description="Hacker News stories (Algolia)"),
        Engine("arxiv", engine_arxiv, "vertical", 0.8, description="arXiv papers"),
    ]
}

ALIASES = {
    "ddg": ["duckduckgo"],
    "wiki": ["wikipedia"],
    "so": ["stackoverflow"],
    "gh": ["github"],
    "hn": ["hackernews"],
    "web": ["duckduckgo", "bing", "yahoo", "brave", "google", "searxng"],
    "dev": ["stackoverflow", "github", "hackernews"],
    "science": ["arxiv", "wikipedia"],
    "all": list(ENGINES),
}


def resolve_engines(spec: Optional[Any] = None) -> List[str]:
    """
    Turn "bing,ddg,dev" (or a list) into concrete engine names. Group aliases
    silently drop engines that need missing credentials; naming such an engine
    explicitly keeps it so its report says what is missing.
    """
    if spec is None or spec == "" or spec == []:
        names = list(DEFAULT_ENGINES) + [n for n in ("brave", "google", "searxng") if ENGINES[n].available]
        return names
    tokens = spec.split(",") if isinstance(spec, str) else list(spec)
    out: List[str] = []
    for token in (t.strip().lower() for t in tokens):
        if not token:
            continue
        if token in ENGINES:
            names = [token]
        elif token in ALIASES:
            names = [n for n in ALIASES[token] if len(ALIASES[token]) == 1 or ENGINES[n].available]
        else:
            raise ValueError(f"Unknown search engine '{token}'. Known: {', '.join(list(ENGINES) + list(ALIASES))}")
        out.extend(n for n in names if n not in out)
    return out


# -------------------------------------------------------------
# Fusion
# -------------------------------------------------------------
def fuse(per_engine: Dict[str, List[SearchHit]], limit: int, k: int = 60) -> List[SearchHit]:
    """Reciprocal Rank Fusion across engines, deduplicated by normalized URL."""
    merged: Dict[str, SearchHit] = {}
    for engine_name, hits in per_engine.items():
        weight = ENGINES[engine_name].weight if engine_name in ENGINES else 1.0
        seen_here = set()
        for rank, hit in enumerate(hits, 1):
            key = normalize_url(hit.url)
            if key in seen_here:
                continue
            seen_here.add(key)
            score = weight / (k + rank)
            cur = merged.get(key)
            if cur is None:
                merged[key] = SearchHit(
                    url=strip_tracking(hit.url), title=hit.title, snippet=hit.snippet,
                    engine=engine_name, rank=rank, engines=[engine_name], score=score,
                )
            else:
                cur.score += score
                cur.engines.append(engine_name)
                if len(hit.snippet) > len(cur.snippet):
                    cur.snippet = hit.snippet
                if not cur.title:
                    cur.title = hit.title
    ranked = sorted(merged.values(), key=lambda h: (-h.score, h.rank))
    for hit in ranked:
        hit.score = round(hit.score, 6)
    return ranked[:limit]


# -------------------------------------------------------------
# Orchestration
def _engine_config_fingerprint(engine: str) -> str:
    """Fingerprint engine-specific instance or credentials (CSE ID, instance URL, key)."""
    if engine == "google":
        return f"{os.environ.get('GOOGLE_CSE_ID', '')}|{os.environ.get('GOOGLE_API_KEY', '')[:8]}"
    if engine == "searxng":
        return os.environ.get("SEARXNG_URL", "").rstrip("/")
    if engine == "brave":
        return os.environ.get("BRAVE_API_KEY", "")[:8]
    if engine == "github":
        tok = os.environ.get("GITHUB_TOKEN", "")
        return hashlib.sha1(tok.encode()).hexdigest()[:12] if tok else "anon"
    return ""


def _cooldown_key(engine: str) -> str:
    cfg = _engine_config_fingerprint(engine)
    if cfg:
        h = hashlib.sha1(cfg.encode("utf-8")).hexdigest()[:10]
        return f"cooldown:{engine}:{h}"
    return f"cooldown:{engine}"


def _cache_key(engine: str, query: str, limit: int, lang: str) -> str:
    cfg = _engine_config_fingerprint(engine)
    digest = hashlib.sha1(f"{engine}|{cfg}|{query.strip().lower()}|{limit}|{lang}".encode("utf-8")).hexdigest()
    return f"search:{engine}:{digest}"


def _run_engine(name: str, query: str, limit: int, lang: str, timeout: float,
                cache_ttl: float, respect_cooldown: bool) -> Tuple[List[SearchHit], EngineReport]:
    engine = ENGINES[name]
    started = time.time()
    if not engine.available:
        missing = ", ".join(v for v in engine.requires if not os.environ.get(v))
        return [], EngineReport(name, "skipped", error=f"set {missing}")

    cache = None
    if cache_ttl > 0 or respect_cooldown:
        try:
            from .cache import get_cache
            cache = get_cache()
        except Exception:
            cache = None

    if cache is not None and cache_ttl > 0:
        cached = cache.get(_cache_key(name, query, limit, lang))
        if cached is not None:
            hits = [SearchHit(**h) for h in cached]
            return hits, EngineReport(name, "cached", len(hits), round(time.time() - started, 3))

    if cache is not None and respect_cooldown:
        until = cache.get(_cooldown_key(name))
        if until:
            wait = int(until - time.time())
            return [], EngineReport(name, "cooldown", error=f"blocked recently, retry in {max(wait, 0)}s")

    try:
        hits = engine.fn(query, limit, lang, timeout)
    except EngineBlocked as e:
        if cache is not None:
            cache.set(_cooldown_key(name), time.time() + COOLDOWN_SECONDS, COOLDOWN_SECONDS)
        return [], EngineReport(name, "blocked", 0, round(time.time() - started, 3), str(e))
    except Exception as e:
        return [], EngineReport(name, "error", 0, round(time.time() - started, 3), f"{type(e).__name__}: {e}"[:200])

    for rank, hit in enumerate(hits, 1):
        hit.engine, hit.rank = name, rank
    if cache is not None and cache_ttl > 0 and hits:
        cache.set(_cache_key(name, query, limit, lang), [h.to_dict() for h in hits], cache_ttl)
    return hits, EngineReport(name, "ok" if hits else "empty", len(hits), round(time.time() - started, 3))


def search(
    query: str,
    engines: Optional[Any] = None,
    max_results: int = 10,
    lang: str = "",
    timeout: float = 10,
    cache_ttl: float = SEARCH_CACHE_TTL,
    respect_cooldown: bool = True,
    per_engine: Optional[int] = None,
) -> SearchResponse:
    """
    Query several engines in parallel and fuse the rankings.

    engines: "duckduckgo,bing", ["dev"], "all"... (None = keyless web engines + configured API engines)
    lang:    "uk", "en", ... (region / interface language hint where the engine supports it)
    """
    started = time.time()
    names = resolve_engines(engines)
    fetch_n = per_engine or max(10, max_results)
    results: Dict[str, List[SearchHit]] = {}
    reports: Dict[str, EngineReport] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(names))) as pool:
        futures = {
            pool.submit(_run_engine, n, query, fetch_n, lang, timeout, cache_ttl, respect_cooldown): n
            for n in names
        }
        for fut in as_completed(futures):
            name = futures[fut]
            hits, report = fut.result()
            reports[name] = report
            if hits:
                results[name] = hits
    ordered = {n: results[n] for n in names if n in results}
    return SearchResponse(
        query=query,
        hits=fuse(ordered, max_results),
        reports=[reports[n] for n in names],
        elapsed=time.time() - started,
    )


def search_and_fetch(
    query: str,
    engines: Optional[Any] = None,
    max_results: int = 10,
    fetch_top: int = 5,
    workers: int = 6,
    lang: str = "",
    allow_browser: bool = True,
    page_cache_ttl: float = 86400,
    **search_kwargs: Any,
):
    """Search, then scrape the top `fetch_top` hits in parallel. Returns (SearchResponse, [ScrapeResult])."""
    from .engine import scrape_many

    response = search(query, engines=engines, max_results=max_results, lang=lang, **search_kwargs)
    urls = [h.url for h in response.hits[:fetch_top]]
    pages = scrape_many(urls, workers=workers, allow_browser=allow_browser, cache_ttl=page_cache_ttl)
    return response, pages
