"""
Scrapler Engine: 4-Tier Automated Web Acquisition Pipeline.

Cascade:
  Tier 0: curl_cffi with Chrome TLS/JA3 impersonation (Fastest, zero browser overhead)
  Tier 1: Scrapling Fetcher with stealth HTTP headers
  Tier 2: Scrapling StealthyFetcher (Patchright headless Chromium, Turnstile bypass)
  Tier 3: PowerSkills Edge CDP (Real browser session/cookies, strict opt-in last resort)

Efficiency rules:
  - Dead pages (404/410/401...) and non-HTML documents stop the cascade: no browser launch.
  - JS-only shells (empty SPA markup) skip Tier 1 and go straight to the browser.
  - The tier that worked for a domain is remembered, so the next URL starts there.
  - HTTP sessions are pooled per thread; browser tiers are capped by a semaphore.
  - Optional SQLite cache (cache_ttl) and parallel batch fetching (scrape_many).
"""

import io
import os
import re
import subprocess
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from typing import Optional, Tuple, Dict, Any, List
from bs4 import BeautifulSoup

POWERSKILLS_PATH = r"C:\Users\pavlo\.codex\skills\powerskills\powerskills.ps1"

TIER_NAMES = {
    0: "tier0_curl_cffi",
    1: "tier1_scrapling_fetcher",
    2: "tier2_scrapling_stealth",
    3: "tier3_powerskills_cdp",
}

# Statuses where a browser will not help: stop the cascade immediately.
DEAD_STATUSES = {400, 401, 404, 405, 410, 414, 451}
BLOCK_STATUSES = {403, 429, 503}
MIN_USEFUL_TEXT = 200
BROWSER_CONCURRENCY = 2

SPA_SHELL_MARKERS = (
    'id="root"></div>',
    'id="app"></div>',
    'id="__next"></div>',
    "ng-app",
    "you need to enable javascript",
    "please enable javascript",
    "requires javascript",
)

# Regex patterns for challenge / interstitial titles (match full title or branded header,
# so articles like "Troubleshoot Access Denied errors in Amazon S3" are not blocked).
CHALLENGE_TITLE_PATTERNS = (
    re.compile(
        r"^(just a moment(\.\.\.)?|attention required!?|access denied|security check|security verification|"
        r"verify you are human|are you a robot\??|bot verification|human verification|ddos-guard|"
        r"cloudflare challenge|captcha|captcha verification|captcha challenge|solve captcha)(\s*[-|:—–]\s*.*)?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^.*(\s*[-|:—–]\s*)(just a moment(\.\.\.)?|attention required!?|access denied|security check|"
        r"verify you are human|are you a robot\??|captcha|captcha verification|captcha challenge|solve captcha)$",
        re.IGNORECASE,
    ),
)
# Markers that big normal pages may also mention (CSP lists, script configs):
# only trusted on small pages, which is what real challenge pages are.
CHALLENGE_INDICATORS = (
    "cf-turnstile",
    "turnstile-wrapper",
    "challenges.cloudflare.com",
    "just a moment...",
    "attention required! | cloudflare",
    "security check to continue",
    "please verify you are a human",
    "cf-browser-verification",
    "datadome",
    "perimeterx",
    "protected by cloudflare",
)
CHALLENGE_PAGE_MAX_BYTES = 50000

_thread_local = threading.local()
_browser_slots = threading.BoundedSemaphore(BROWSER_CONCURRENCY)
_domain_tier: Dict[str, int] = {}
_domain_lock = threading.Lock()


@dataclass
class ScrapeResult:
    url: str
    title: str
    text: str
    tier_used: str
    status_code: int = 200
    from_cache: bool = False
    content_type: str = ""
    final_url: str = ""
    elapsed: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text) and 200 <= self.status_code < 400

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class _Attempt:
    verdict: str  # ok | blocked | thin | dead | unsupported | error
    status: int = 0
    html: str = ""
    text: str = ""
    title: str = ""
    content_type: str = ""
    final_url: str = ""
    error: str = ""


def get_http_session():
    """Thread-local curl_cffi session: keeps TCP/TLS connections alive between requests."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        from curl_cffi import requests as cffi_requests
        session = cffi_requests.Session(
            impersonate="chrome",
            headers={"Accept-Language": "en-US,en;q=0.9,uk;q=0.8"},
        )
        _thread_local.session = session
    return session


def is_challenge_or_blocked(status_code: int, html_body: str) -> bool:
    """Detect Cloudflare Turnstile, interstitial, 403, 429, or bot challenge pages."""
    if status_code in BLOCK_STATUSES:
        return True
    body = html_body or ""
    # Definitive challenge titles always identify interstitial blockers, even if the page
    # carries large inline challenge scripts (>50KB).
    match = re.search(r"<title[^>]*>(.*?)</title>", body[:20000], re.IGNORECASE | re.DOTALL)
    title = match.group(1).strip() if match else ""
    if title and any(p.match(title) for p in CHALLENGE_TITLE_PATTERNS):
        return True

    # Ambiguous body markers (e.g. challenges.cloudflare.com in Bing's CSP list or script configs)
    # are only trusted on small pages, which is what real challenge interstitials are.
    if len(body) > CHALLENGE_PAGE_MAX_BYTES:
        return False
    lower = body.lower()
    return any(indicator in lower for indicator in CHALLENGE_INDICATORS)


def looks_like_js_shell(html: str, text: str) -> bool:
    """True when the HTML is an empty client-side app that only a browser can render."""
    if len(text) >= MIN_USEFUL_TEXT:
        return False
    lower = html[:200000].lower()
    if any(marker in lower for marker in SPA_SHELL_MARKERS):
        return True
    # If text is empty or minimal, require evidence of scripts or empty containers
    # so short static pages like "Service healthy." are not discarded.
    return "<script" in lower and len(text) == 0


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _title_from_soup(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.string:
        return re.sub(r"\s+", " ", soup.title.string).strip()
    h1 = soup.find("h1")
    return h1.get_text(" ", strip=True) if h1 else ""


def _text_from_soup(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "iframe", "template"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n\n".join(lines)


def extract_title(html: str) -> str:
    """Extract page title from HTML."""
    if not html:
        return ""
    try:
        title = _title_from_soup(_soup(html))
        if title:
            return title
    except Exception:
        pass
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    return ""


def clean_html_to_markdown(html: str) -> str:
    """Clean HTML and format as readable markdown-like text."""
    if not html:
        return ""
    try:
        return _text_from_soup(_soup(html))
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)


def extract(html: str, url: str = "") -> Tuple[str, str]:
    """
    Parse HTML once and return (title, main_text).

    Uses trafilatura's main-content extraction (drops menus, cookie banners, related
    links) and falls back to a full-page text dump when trafilatura finds too little,
    which happens on index/list pages.
    """
    if not html:
        return "", ""
    soup = _soup(html)
    title = _title_from_soup(soup)
    main = ""
    try:
        import trafilatura
        main = trafilatura.extract(
            html,
            url=url or None,
            output_format="markdown",
            include_tables=True,
            include_links=False,
            include_comments=False,
            favor_recall=True,
        ) or ""
    except Exception:
        main = ""
    full = _text_from_soup(soup)
    if len(main) >= MIN_USEFUL_TEXT or len(main) >= 0.4 * len(full):
        return title, main.strip()
    return title, full.strip()


def _extract_non_html(body: bytes, content_type: str) -> Optional[str]:
    """Return text for plain/JSON/XML/PDF documents, or None when the type is unsupported."""
    ct = content_type.lower()
    if any(t in ct for t in ("text/plain", "json", "text/markdown", "text/csv", "xml")) and "html" not in ct:
        return body.decode("utf-8", "replace")
    if "pdf" in ct:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(body))
            return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
        except Exception:
            return ""
    if any(t in ct for t in ("image/", "video/", "audio/", "zip", "octet-stream", "font/")):
        return ""
    return None


def _judge(status: int, html: str, url: str, content_type: str = "", body: bytes = b"") -> _Attempt:
    """Classify a fetched response so the cascade knows whether to stop, retry or escalate."""
    if status in DEAD_STATUSES:
        return _Attempt("dead", status, content_type=content_type)
    if is_challenge_or_blocked(status, html):
        return _Attempt("blocked", status, content_type=content_type)
    if not 200 <= status < 400:
        return _Attempt("error", status, content_type=content_type)
    if content_type and "html" not in content_type.lower():
        text = _extract_non_html(body or html.encode("utf-8", "replace"), content_type)
        if text is not None:
            title = urllib.parse.unquote(urllib.parse.urlparse(url).path.rsplit("/", 1)[-1])
            return _Attempt("ok" if text else "unsupported", status, "", text, title, content_type)
    title, text = extract(html, url)
    if looks_like_js_shell(html, text):
        return _Attempt("thin", status, html, text, title, content_type)
    if not text.strip():
        return _Attempt("empty", status, html, text, title, content_type)
    return _Attempt("ok", status, html, text, title, content_type)


# -------------------------------------------------------------
# Tier 0: curl_cffi with Chrome Impersonation
# -------------------------------------------------------------
def fetch_tier0_curl_cffi(url: str, timeout: int = 15) -> _Attempt:
    """Tier 0: Pooled HTTP request with Chrome TLS/JA3 fingerprint impersonation."""
    try:
        response = get_http_session().get(url, allow_redirects=True, timeout=timeout)
        content_type = response.headers.get("content-type", "")
        html = response.text if ("html" in content_type.lower() or not content_type) else ""
        attempt = _judge(response.status_code, html, url, content_type, response.content)
        attempt.final_url = str(response.url)
        return attempt
    except Exception as e:
        return _Attempt("error", 0, error=str(e)[:200])


# -------------------------------------------------------------
# Tier 1: Scrapling Fetcher (Stealth HTTP)
# -------------------------------------------------------------
def fetch_tier1_scrapling(url: str, timeout: int = 20) -> _Attempt:
    """Tier 1: Scrapling Fetcher with automated stealth headers."""
    try:
        from scrapling import Fetcher
        response = Fetcher.get(url, timeout=timeout, stealthy_headers=True)
        html = getattr(response, "html_content", "") or response.body.decode("utf-8", "replace")
        attempt = _judge(response.status, html, url)
        attempt.final_url = str(getattr(response, "url", url))
        return attempt
    except Exception as e:
        return _Attempt("error", 0, error=str(e)[:200])


# -------------------------------------------------------------
# Tier 2: Scrapling StealthyFetcher (Patchright Headless Chromium)
# -------------------------------------------------------------
def fetch_tier2_scrapling_stealth(url: str, timeout: int = 30) -> _Attempt:
    """Tier 2: Scrapling StealthyFetcher for JS-heavy apps and Cloudflare Turnstile bypass."""
    try:
        from scrapling import StealthyFetcher
        with _browser_slots:
            response = StealthyFetcher.fetch(
                url,
                headless=True,
                timeout=timeout * 1000,
                wait=1000,
                disable_resources=True,
                block_ads=True,
                solve_cloudflare=True,
            )
        html = getattr(response, "html_content", "") or response.body.decode("utf-8", "replace")
        status = 200 if response.status == 304 else response.status
        attempt = _judge(status, html, url)
        if attempt.verdict == "thin" and attempt.text:
            attempt.verdict = "ok"  # a rendered page with little text is still the real page
        attempt.final_url = str(getattr(response, "url", url))
        return attempt
    except Exception as e:
        return _Attempt("error", 0, error=str(e)[:200])


# -------------------------------------------------------------
# Tier 3: PowerSkills + Real Edge CDP
# -------------------------------------------------------------
def _ps_quote(value: str) -> str:
    """Quote a value as a PowerShell single-quoted literal."""
    return "'" + value.replace("'", "''") + "'"


def fetch_tier3_powerskills_cdp(url: str) -> _Attempt:
    """Tier 3: PowerSkills Edge CDP automation (real browser profile/session)."""
    if not os.path.exists(POWERSKILLS_PATH):
        return _Attempt("error", 0, error="PowerSkills not installed")
    script = (
        f"& {_ps_quote(POWERSKILLS_PATH)} -Action Navigate -Url {_ps_quote(url)}\n"
        "Start-Sleep -Seconds 3\n"
        f"& {_ps_quote(POWERSKILLS_PATH)} -Action GetContent\n"
    )
    try:
        with _browser_slots:
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=40,
            )
        if proc.returncode == 0 and len(proc.stdout.strip()) > 100:
            attempt = _judge(200, proc.stdout, url)
            if attempt.verdict == "thin" and attempt.text:
                attempt.verdict = "ok"
            return attempt
        return _Attempt("error", 0, error=proc.stderr.strip()[:200] or f"exit code {proc.returncode}")
    except Exception as e:
        return _Attempt("error", 0, error=str(e)[:200])


# -------------------------------------------------------------
# Unified Cascade Orchestrator
# -------------------------------------------------------------
def _domain(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower()


def remembered_tier(url: str) -> Optional[int]:
    with _domain_lock:
        return _domain_tier.get(_domain(url))


def _remember_tier(url: str, tier: int) -> None:
    with _domain_lock:
        _domain_tier[_domain(url)] = tier


def _forget_tier(url: str) -> None:
    with _domain_lock:
        _domain_tier.pop(_domain(url), None)


def scrape_url(
    url: str,
    force_tier: Optional[int] = None,
    allow_tier3: bool = False,
    timeout: int = 15,
    cache_ttl: float = 0,
    allow_browser: bool = True,
) -> ScrapeResult:
    """
    Scrapes a target URL using the automated 4-tier cascade:
    Tier 0 (curl_cffi) -> Tier 1 (Scrapling) -> Tier 2 (Stealth Chromium) -> Tier 3 (Edge CDP)

    cache_ttl > 0 reads/writes successful results in the shared SQLite cache.
    allow_browser=False stops after the HTTP tiers (useful for bulk fetching).
    """
    started = time.time()
    cache_key = f"page:{url}"
    if cache_ttl > 0 and force_tier is None:
        try:
            from .cache import get_cache
            cached = get_cache().get(cache_key)
            if cached:
                cached["from_cache"] = True
                cached["elapsed"] = time.time() - started
                return ScrapeResult(**cached)
        except Exception:
            pass

    if force_tier is not None:
        tiers = [force_tier]
    else:
        tiers = [0, 1]
        if allow_browser:
            tiers.append(2)
            if allow_tier3:
                tiers.append(3)
        start = remembered_tier(url)
        if start is not None and start in tiers and start > 0:
            # Keep the cheap Tier 0 probe so dead links (404/401) still short-circuit,
            # but skip the HTTP tiers in between that are known to be blocked here.
            tiers = [0] + tiers[tiers.index(start):]

    best = _Attempt("error", 0)
    tier_used = "none"
    skip_tier1 = False
    was_blocked = False
    errors: List[str] = []
    for tier in tiers:
        if tier == 1 and skip_tier1:
            continue
        if tier == 0:
            attempt = fetch_tier0_curl_cffi(url, timeout=timeout)
        elif tier == 1:
            attempt = fetch_tier1_scrapling(url, timeout=timeout + 5)
        elif tier == 2:
            attempt = fetch_tier2_scrapling_stealth(url, timeout=max(timeout * 2, 30))
        else:
            attempt = fetch_tier3_powerskills_cdp(url)

        if attempt.verdict == "ok" or (attempt.verdict == "thin" and force_tier is not None):
            best, tier_used = attempt, TIER_NAMES[tier]
            # Anti-bot protection is domain-wide: start the next URL of this domain here.
            if force_tier is None and was_blocked:
                _remember_tier(url, tier)
            elif force_tier is None and tier == 0:
                _forget_tier(url)  # the domain stopped blocking plain HTTP
            break
        if attempt.verdict in ("dead", "unsupported"):
            best, tier_used = attempt, TIER_NAMES[tier]
            break
        if attempt.verdict in ("thin", "empty"):
            if attempt.verdict == "thin":
                skip_tier1 = True
            if not best.text:
                best, tier_used = attempt, TIER_NAMES[tier]
            continue
        was_blocked = was_blocked or attempt.verdict == "blocked"
        errors.append(f"{TIER_NAMES[tier]}: {attempt.error or attempt.verdict} ({attempt.status})")
        if not best.text and not best.status:
            best = attempt

    # If an empty/thin shell required escalation and escalation failed,
    # it is NOT considered ok and must not be cached as a success.
    ok = best.verdict == "ok" or (best.verdict in ("thin", "empty") and force_tier is not None and bool(best.text))
    text = best.text.strip() if ok else ""
    title = best.title
    if not title:
        parsed = urllib.parse.urlparse(url)
        title = parsed.path.strip("/").split("/")[-1] or parsed.netloc
    status = best.status or (200 if text else 500)
    if ok or best.verdict in ("dead", "unsupported"):
        error = "" if ok else best.verdict
    else:
        tier_used = "none"
        error = "; ".join(errors) or "fetch failed"

    result = ScrapeResult(
        url=url,
        title=title.strip(),
        text=text,
        tier_used=tier_used,
        status_code=status,
        content_type=best.content_type,
        final_url=best.final_url or url,
        elapsed=round(time.time() - started, 3),
        error=error,
    )
    if cache_ttl > 0 and result.ok and force_tier is None:
        try:
            from .cache import get_cache
            get_cache().set(cache_key, result.to_dict(), cache_ttl)
        except Exception:
            pass
    return result


def scrape_many(
    urls: List[str],
    workers: int = 8,
    **kwargs: Any,
) -> List[ScrapeResult]:
    """
    Scrape many URLs in parallel (HTTP tiers run concurrently; browser tiers are
    capped at BROWSER_CONCURRENCY). Results are returned in input order.
    """
    unique = list(dict.fromkeys(urls))
    if not unique:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(unique)))) as pool:
        results = dict(zip(unique, pool.map(lambda u: scrape_url(u, **kwargs), unique)))
    return [results[u] for u in urls]
