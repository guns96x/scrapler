"""
Scrapler Engine: 4-Tier Automated Web Acquisition Pipeline.

Cascade:
  Tier 0: curl_cffi with Chrome TLS/JA3 impersonation (Fastest, zero browser overhead)
  Tier 1: Scrapling Fetcher with stealth HTTP headers & clean markdown parsing
  Tier 2: Scrapling StealthyFetcher (Patchright headless Chromium, Turnstile bypass)
  Tier 3: PowerSkills Edge CDP (Real browser session/cookies, strict opt-in last resort)
"""

import os
import re
import subprocess
import urllib.parse
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
from bs4 import BeautifulSoup

POWERSKILLS_PATH = r"C:\Users\pavlo\.codex\skills\powerskills\powerskills.ps1"


@dataclass
class ScrapeResult:
    url: str
    title: str
    text: str
    tier_used: str
    status_code: int = 200
    from_cache: bool = False


def is_challenge_or_blocked(status_code: int, html_body: str) -> bool:
    """Detect Cloudflare Turnstile, interstitial, 403, 429, or bot challenge pages."""
    if status_code in (403, 429, 503):
        return True
    lower = html_body.lower()
    challenge_indicators = [
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
    ]
    return any(indicator in lower for indicator in challenge_indicators)


def extract_title(html: str) -> str:
    """Extract page title from HTML."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
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
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "iframe"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n\n".join(lines)
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)


# -------------------------------------------------------------
# Tier 0: curl_cffi with Chrome Impersonation
# -------------------------------------------------------------
def fetch_tier0_curl_cffi(url: str, timeout: int = 15) -> Optional[Tuple[str, str, int]]:
    """Tier 0: Ultra-fast HTTP request with Chrome TLS/JA3 fingerprint impersonation."""
    try:
        from curl_cffi import requests as cffi_requests
        response = cffi_requests.get(
            url,
            impersonate="chrome",
            allow_redirects=True,
            timeout=timeout,
            headers={"Accept-Language": "en-US,en;q=0.9,uk;q=0.8"}
        )
        if response.status_code == 200 and not is_challenge_or_blocked(response.status_code, response.text):
            text = clean_html_to_markdown(response.text)
            return response.text, text, response.status_code
        return None
    except Exception:
        return None


# -------------------------------------------------------------
# Tier 1: Scrapling Fetcher (Stealth HTTP)
# -------------------------------------------------------------
def fetch_tier1_scrapling(url: str, timeout: int = 20) -> Optional[Tuple[str, str, int]]:
    """Tier 1: Scrapling Fetcher with automated stealth headers and native markdown."""
    try:
        from scrapling import Fetcher
        fetcher = Fetcher()
        response = fetcher.get(url, timeout=timeout)
        if response.status == 200:
            html = getattr(response, "html_content", "") or response.body.decode("utf-8", "replace")
            if not is_challenge_or_blocked(response.status, html):
                if callable(getattr(response, "markdown", None)):
                    text = response.markdown()
                else:
                    text = clean_html_to_markdown(html)
                return html, text, response.status
        return None
    except Exception:
        return None


# -------------------------------------------------------------
# Tier 2: Scrapling StealthyFetcher (Patchright Headless Chromium)
# -------------------------------------------------------------
def fetch_tier2_scrapling_stealth(url: str, timeout: int = 30) -> Optional[Tuple[str, str, int]]:
    """Tier 2: Scrapling StealthyFetcher for JS-heavy apps and Cloudflare Turnstile bypass."""
    try:
        from scrapling import StealthyFetcher
        response = StealthyFetcher.fetch(url, headless=True, timeout=timeout * 1000, wait=1000)
        if response.status in (200, 304):
            html = getattr(response, "html_content", "") or response.body.decode("utf-8", "replace")
            if not is_challenge_or_blocked(response.status, html):
                if callable(getattr(response, "markdown", None)):
                    text = response.markdown()
                else:
                    text = clean_html_to_markdown(html)
                return html, text, response.status
        return None
    except Exception:
        return None


# -------------------------------------------------------------
# Tier 3: PowerSkills + Real Edge CDP
# -------------------------------------------------------------
def fetch_tier3_powerskills_cdp(url: str) -> Optional[Tuple[str, str, int]]:
    """Tier 3: PowerSkills Edge CDP automation (real browser profile/session)."""
    if not os.path.exists(POWERSKILLS_PATH):
        return None
    try:
        script = f"""
        & '{POWERSKILLS_PATH}' -Action Navigate -Url '{url}'
        Start-Sleep -Seconds 3
        $content = & '{POWERSKILLS_PATH}' -Action GetContent
        $content
        """
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=40
        )
        if proc.returncode == 0 and len(proc.stdout.strip()) > 100:
            html = proc.stdout
            text = clean_html_to_markdown(html)
            return html, text, 200
        return None
    except Exception:
        return None


# -------------------------------------------------------------
# Unified Cascade Orchestrator
# -------------------------------------------------------------
def scrape_url(
    url: str,
    force_tier: Optional[int] = None,
    allow_tier3: bool = False
) -> ScrapeResult:
    """
    Scrapes a target URL using the automated 4-tier cascade:
    Tier 0 (curl_cffi) -> Tier 1 (Scrapling) -> Tier 2 (Stealth Chromium) -> Tier 3 (Edge CDP)
    """
    if force_tier is not None:
        tiers_to_try = [force_tier]
    elif allow_tier3:
        tiers_to_try = [0, 1, 2, 3]
    else:
        tiers_to_try = [0, 1, 2]

    html = ""
    clean_text = ""
    status_code = 0
    tier_used = "none"

    for tier in tiers_to_try:
        if tier == 0:
            res = fetch_tier0_curl_cffi(url)
            if res and res[1]:
                html, clean_text, status_code = res
                tier_used = "tier0_curl_cffi"
                break
        elif tier == 1:
            res = fetch_tier1_scrapling(url)
            if res and res[1]:
                html, clean_text, status_code = res
                tier_used = "tier1_scrapling_fetcher"
                break
        elif tier == 2:
            res = fetch_tier2_scrapling_stealth(url)
            if res and res[1]:
                html, clean_text, status_code = res
                tier_used = "tier2_scrapling_stealth"
                break
        elif tier == 3:
            res = fetch_tier3_powerskills_cdp(url)
            if res and res[1]:
                html, clean_text, status_code = res
                tier_used = "tier3_powerskills_cdp"
                break

    title = extract_title(html)
    if not title:
        parsed = urllib.parse.urlparse(url)
        title = parsed.path.strip("/").split("/")[-1] or parsed.netloc

    return ScrapeResult(
        url=url,
        title=title.strip(),
        text=clean_text.strip(),
        tier_used=tier_used,
        status_code=status_code or (200 if clean_text else 500)
    )
