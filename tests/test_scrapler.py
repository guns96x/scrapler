"""
Unit and integration tests for Scrapler package.

Offline tests always run. Live-network tests (real sites, real search engines,
browser tier) run only with SCRAPLER_NET_TESTS=1.
"""

import base64
import importlib
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from scrapler import engine as engine_mod
from scrapler.engine import (
    scrape_url, scrape_many, is_challenge_or_blocked, extract_title, extract, _judge, _ps_quote,
)
from scrapler.crawler import crawl_site, normalize_crawl_url
from scrapler.vectors import VectorStore, HybridRetriever
from scrapler.cache import Cache
search_mod = importlib.import_module("scrapler.search")  # the package re-exports search(), shadowing the module
from scrapler.search import (
    SearchHit, parse_duckduckgo, parse_bing, parse_yahoo, decode_bing_url, decode_yahoo_url,
    decode_ddg_url, normalize_url, strip_tracking, fuse, resolve_engines, term_coverage, EngineBlocked,
)

NET = os.environ.get("SCRAPLER_NET_TESTS") == "1"
needs_net = unittest.skipUnless(NET, "live network test (set SCRAPLER_NET_TESTS=1)")


def _b64(url: str) -> str:
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


DDG_HTML = """
<div class="result results_links web-result"><div class="links_main result__body">
  <h2 class="result__title"><a class="result__a" href="https://sqlite.org/fts5.html">SQLite <b>FTS5</b> Extension</a></h2>
  <a class="result__snippet" href="https://sqlite.org/fts5.html">FTS5 is an SQLite virtual table module.</a>
</div></div>
<div class="result results_links web-result result--ad"><div class="links_main result__body">
  <h2 class="result__title"><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Ad</a></h2>
</div></div>
<div class="result results_links web-result"><div class="links_main result__body">
  <h2 class="result__title"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa%3Fx%3D1&rut=abc">Wrapped</a></h2>
</div></div>
"""

BING_HTML = f"""
<ol id="b_results">
<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?!&&p=abc&u=a1{_b64('https://sqlite.org/index.html')}&ntb=1"><strong>SQLite</strong> Home Page</a></h2>
  <div class="b_caption"><p class="b_lineclamp2"><span class="news_dt">Aug 14, 2026</span>· SQLite is a C-language library.</p></div></li>
<li class="b_ad"><h2><a href="https://www.bing.com/aclk?ld=1">Sponsored</a></h2></li>
<li class="b_algo"><h2><a href="https://github.com/x/y">Direct link</a></h2><p>Plain snippet</p></li>
</ol>
"""

YAHOO_HTML = """
<div class="dd algo algo-sr Sr"><div class="compTitle options-toggle">
  <a href="https://r.search.yahoo.com/_ylt=A;_ylu=B/RV=2/RE=1/RO=10/RU=https%3a%2f%2fwww.slingacademy.com%2farticle%2franking%2f/RK=2/RS=xyz-">
    <span class="d-ib">Sling Academy https://www.slingacademy.com</span>
    <h3 class="title"><span>Ranking Full-Text Search Results</span></h3></a></div>
  <div class="compText aAbs"><p><span class="fc-smoke">Dec 7, 2024 · </span> SQLite FTS5 utilizes BM25.</p></div>
</div>
"""


class TestEngineOffline(unittest.TestCase):

    def test_challenge_detection(self):
        self.assertTrue(is_challenge_or_blocked(403, "Forbidden"))
        self.assertTrue(is_challenge_or_blocked(200, "<html>Just a moment... Please verify you are a human</html>"))
        self.assertTrue(is_challenge_or_blocked(200, "<html><head><title>Captcha</title></head></html>"))
        self.assertTrue(is_challenge_or_blocked(200, "<html><head><title>Security Check - Captcha Verification</title></head></html>"))
        self.assertFalse(is_challenge_or_blocked(200, "<html><h1>Normal Documentation Page</h1></html>"))

    def test_legitimate_captcha_article_is_not_blocked(self):
        page = "<html><head><title>How to implement CAPTCHA in Python</title></head><body><p>Guide on CAPTCHA forms.</p></body></html>"
        self.assertFalse(is_challenge_or_blocked(200, page))

    def test_access_denied_article_title_not_blocked(self):
        page = "<html><head><title>Troubleshoot Access Denied errors in Amazon S3</title></head><body><p>Guide on S3 IAM policies.</p></body></html>"
        self.assertFalse(is_challenge_or_blocked(200, page))

    def test_large_challenge_page_with_title_is_detected(self):
        page = "<html><head><title>Just a moment...</title></head><body>" + "x" * 60000 + "</body></html>"
        self.assertTrue(is_challenge_or_blocked(200, page))

    def test_short_static_page_not_classified_as_js_shell(self):
        def tier0(url, timeout=15):
            return engine_mod._Attempt("ok", 200, html="<html><body>Service healthy.</body></html>", text="Service healthy.", title="Health")
        with mock.patch.object(engine_mod, "fetch_tier0_curl_cffi", tier0):
            res = scrape_url("https://api.test/health", allow_browser=False)
        self.assertTrue(res.ok)
        self.assertEqual(res.text, "Service healthy.")

    def test_empty_html_response_continues_cascade(self):
        calls = []
        def tier0(url, timeout=15):
            calls.append(0)
            return engine_mod._judge(200, "", url)
        def tier1(url, timeout=20):
            calls.append(1)
            return engine_mod._Attempt("ok", 200, html="<html><body>Fallback text</body></html>", text="Fallback text", title="T")

        with mock.patch.object(engine_mod, "fetch_tier0_curl_cffi", tier0), \
             mock.patch.object(engine_mod, "fetch_tier1_scrapling", tier1):
            res = scrape_url("https://empty.test/page", allow_browser=False)
        self.assertEqual(calls, [0, 1])
        self.assertTrue(res.ok)
        self.assertEqual(res.tier_used, "tier1_scrapling_fetcher")
        self.assertEqual(res.text, "Fallback text")

    def test_challenge_marker_on_big_normal_page_is_not_a_block(self):
        # Bing's real result page lists challenges.cloudflare.com in a CSP config.
        page = "<html><title>sqlite - Search</title>" + "x" * 80000 + '"challenges.cloudflare.com","cf-turnstile-wrapper"</html>'
        self.assertFalse(is_challenge_or_blocked(200, page))

    def test_title_extraction(self):
        html = "<html><head><title>My Awesome Docs</title></head><body>Content</body></html>"
        self.assertEqual(extract_title(html), "My Awesome Docs")

    def test_extract_prefers_main_content(self):
        body = "<p>" + " ".join(["Scrapler extracts the main article text for retrieval."] * 20) + "</p>"
        html = f"<html><head><title>T</title></head><body><nav>Home | About | Login</nav><article>{body}</article></body></html>"
        title, text = extract(html, "https://x.test/a")
        self.assertEqual(title, "T")
        self.assertIn("main article text", text)
        self.assertNotIn("Login", text)

    def test_judge_verdicts(self):
        self.assertEqual(_judge(404, "", "https://x.test/").verdict, "dead")
        self.assertEqual(_judge(429, "", "https://x.test/").verdict, "blocked")
        self.assertEqual(_judge(200, '<html><body><div id="root"></div><script src=a.js></script></body></html>',
                                "https://x.test/").verdict, "thin")
        plain = _judge(200, "", "https://x.test/notes.txt", "text/plain", b"hello world")
        self.assertEqual((plain.verdict, plain.text, plain.title), ("ok", "hello world", "notes.txt"))
        self.assertEqual(_judge(200, "", "https://x.test/a.png", "image/png", b"\x89PNG").verdict, "unsupported")

    def test_dead_page_stops_cascade(self):
        calls = []

        def tier0(url, timeout=15):
            calls.append(0)
            return engine_mod._Attempt("dead", 404)

        def browser(*a, **k):
            calls.append(2)
            return engine_mod._Attempt("ok", 200, text="x")

        with mock.patch.object(engine_mod, "fetch_tier0_curl_cffi", tier0), \
                mock.patch.object(engine_mod, "fetch_tier1_scrapling", browser), \
                mock.patch.object(engine_mod, "fetch_tier2_scrapling_stealth", browser):
            res = scrape_url("https://dead.test/missing")
        self.assertEqual(calls, [0])
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.error, "dead")
        self.assertFalse(res.ok)

    def test_thin_shell_skips_tier1_and_blocked_domain_is_remembered(self):
        calls = []

        def tier0(url, timeout=15):
            calls.append(0)
            return engine_mod._Attempt("blocked", 403) if "blocked" in url else engine_mod._Attempt("thin", 200)

        def tier1(url, timeout=20):
            calls.append(1)
            return engine_mod._Attempt("blocked", 403)

        def tier2(url, timeout=30):
            calls.append(2)
            return engine_mod._Attempt("ok", 200, text="rendered", title="R")

        with mock.patch.object(engine_mod, "fetch_tier0_curl_cffi", tier0), \
                mock.patch.object(engine_mod, "fetch_tier1_scrapling", tier1), \
                mock.patch.object(engine_mod, "fetch_tier2_scrapling_stealth", tier2):
            res = scrape_url("https://spa.test/app")
            self.assertEqual((calls, res.tier_used), ([0, 2], "tier2_scrapling_stealth"))
            self.assertIsNone(engine_mod.remembered_tier("https://spa.test/other"))

            calls.clear()
            scrape_url("https://blocked.test/a")
            self.assertEqual(calls, [0, 1, 2])
            calls.clear()
            scrape_url("https://blocked.test/b")
            self.assertEqual(calls, [0, 2])  # cheap probe kept, blocked Tier 1 skipped
        engine_mod._domain_tier.clear()

    def test_scrape_many_keeps_order_and_dedupes(self):
        seen = []

        def fake(url, **kw):
            seen.append(url)
            return engine_mod.ScrapeResult(url=url, title=url, text="t", tier_used="x")

        with mock.patch.object(engine_mod, "scrape_url", fake):
            out = scrape_many(["https://a.test", "https://b.test", "https://a.test"], workers=4)
        self.assertEqual([r.url for r in out], ["https://a.test", "https://b.test", "https://a.test"])
        self.assertEqual(sorted(seen), ["https://a.test", "https://b.test"])

    def test_failed_js_shell_not_marked_ok_or_cached(self):
        def tier0(url, timeout=15):
            return engine_mod._Attempt("thin", 200, html="<html><title>App</title><body>Loading...</body></html>", text="Loading...", title="App")

        def tier2(url, timeout=30):
            return engine_mod._Attempt("blocked", 403, error="cf blocked")

        with mock.patch.object(engine_mod, "fetch_tier0_curl_cffi", tier0), \
                mock.patch.object(engine_mod, "fetch_tier2_scrapling_stealth", tier2):
            res = scrape_url("https://spa.test/failed", allow_tier3=False)
        self.assertFalse(res.ok)
        self.assertEqual(res.tier_used, "none")
        self.assertIn("blocked", res.error)

    def test_powershell_quoting(self):
        self.assertEqual(_ps_quote("https://x.test/?q='; rm -r"), "'https://x.test/?q=''; rm -r'")


class TestSearchOffline(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"SCRAPLER_HOME": self.home})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    def test_parse_duckduckgo(self):
        hits = parse_duckduckgo(DDG_HTML)
        self.assertEqual([h.url for h in hits], ["https://sqlite.org/fts5.html", "https://example.com/a?x=1"])
        self.assertEqual(hits[0].title, "SQLite FTS5 Extension")
        self.assertIn("virtual table", hits[0].snippet)

    def test_parse_bing(self):
        hits = parse_bing(BING_HTML)
        self.assertEqual([h.url for h in hits], ["https://sqlite.org/index.html", "https://github.com/x/y"])
        self.assertEqual(hits[0].snippet, "SQLite is a C-language library.")
        self.assertEqual(hits[1].snippet, "Plain snippet")

    def test_parse_yahoo(self):
        hits = parse_yahoo(YAHOO_HTML)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].url, "https://www.slingacademy.com/article/ranking/")
        self.assertEqual(hits[0].title, "Ranking Full-Text Search Results")
        self.assertEqual(hits[0].snippet, "SQLite FTS5 utilizes BM25.")

    def test_url_decoders(self):
        self.assertEqual(decode_bing_url(f"https://www.bing.com/ck/a?u=a1{_b64('https://a.test/x?y=1')}"), "https://a.test/x?y=1")
        self.assertEqual(decode_bing_url("https://plain.test/"), "https://plain.test/")
        self.assertEqual(decode_yahoo_url("https://r.search.yahoo.com/x/RU=https%3a%2f%2fa.test%2f/RK=2/RS=1"), "https://a.test/")
        self.assertEqual(decode_ddg_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.test%2F"), "https://a.test/")

    def test_normalize_and_strip_tracking(self):
        self.assertEqual(normalize_url("http://www.A.test/path/?utm_source=x&b=2&a=1#frag"),
                         normalize_url("https://a.test/path?a=1&b=2"))
        self.assertEqual(strip_tracking("https://a.test/p?utm_medium=x&id=5&fbclid=z"), "https://a.test/p?id=5")

    def test_fuse_rewards_agreement(self):
        per_engine = {
            "duckduckgo": [SearchHit("https://a.test/1", "A"), SearchHit("https://b.test/", "B")],
            "bing": [SearchHit("https://www.b.test", "B", "longer snippet"), SearchHit("https://c.test/", "C")],
        }
        hits = fuse(per_engine, limit=10)
        self.assertEqual(hits[0].url.rstrip("/").replace("www.", ""), "https://b.test")
        self.assertEqual(sorted(hits[0].engines), ["bing", "duckduckgo"])
        self.assertEqual(hits[0].snippet, "longer snippet")
        self.assertEqual(len(hits), 3)

    def test_generic_rrf(self):
        rrf = HybridRetriever.compute_rrf([1, 2, 3], [2, 1, 4], k=60, limit=3)
        self.assertEqual({cid for cid, _ in rrf[:2]}, {1, 2})
        three = HybridRetriever.fuse([[1, 2], [2, 3], [2, 1]], limit=3)
        self.assertEqual(three[0][0], 2)

    def test_resolve_engines(self):
        with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "", "SEARXNG_URL": "", "GOOGLE_API_KEY": ""}):
            self.assertEqual(resolve_engines(None), ["duckduckgo", "bing", "yahoo"])
            self.assertEqual(resolve_engines("ddg,bing,ddg"), ["duckduckgo", "bing"])
            self.assertEqual(resolve_engines("web"), ["duckduckgo", "bing", "yahoo"])
            self.assertEqual(resolve_engines("brave"), ["brave"])  # explicit: kept so the report explains
        with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "k"}):
            self.assertIn("brave", resolve_engines(None))
        with self.assertRaises(ValueError):
            resolve_engines("altavista")

    def test_term_coverage_detects_degraded_results(self):
        q = "python asyncio semaphore example"
        good = [SearchHit("u", "Asyncio Semaphore in Python"), SearchHit("u", "asyncio.Semaphore example")]
        bad = [SearchHit("u", "Welcome to Python.org"), SearchHit("u", "Download Python")]
        self.assertGreaterEqual(term_coverage(good, q), 0.5)
        self.assertEqual(term_coverage(bad, q), 0.0)
        self.assertEqual(term_coverage(bad, "python"), 1.0)

    def test_search_fuses_caches_and_cools_down(self):
        calls = {"good": 0, "bad": 0}

        def good(query, limit, lang, timeout):
            calls["good"] += 1
            return [SearchHit("https://a.test/", "A"), SearchHit("https://b.test/", "B")]

        def bad(query, limit, lang, timeout):
            calls["bad"] += 1
            raise EngineBlocked("HTTP 429")

        engines = {
            "good": search_mod.Engine("good", good, "web"),
            "bad": search_mod.Engine("bad", bad, "web"),
        }
        with mock.patch.dict(search_mod.ENGINES, engines, clear=True):
            r1 = search_mod.search("q", engines=["good", "bad"], cache_ttl=60)
            r2 = search_mod.search("q", engines=["good", "bad"], cache_ttl=60)
        self.assertEqual([h.url for h in r1.hits], ["https://a.test/", "https://b.test/"])
        self.assertEqual([r.status for r in r1.reports], ["ok", "blocked"])
        self.assertEqual([r.status for r in r2.reports], ["cached", "cooldown"])
        self.assertEqual(calls, {"good": 1, "bad": 1})

    def test_search_without_writable_cache_state(self):
        calls = []
        def good(*args):
            calls.append(1)
            return [SearchHit("https://example.test/", "Result")]
        with mock.patch.dict(search_mod.ENGINES, {"test": search_mod.Engine("test", good, "web")}, clear=True), \
             mock.patch("scrapler.cache.get_cache", side_effect=PermissionError("read-only state")):
            res = search_mod.search("query", engines=["test"], cache_ttl=0, respect_cooldown=False)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(res.hits), 1)

    def test_encoded_slash_preserved_in_dedup(self):
        urls = ["https://example.test/docs/a%2Fb", "https://example.test/docs/a/b"]
        norm = [normalize_url(u) for u in urls]
        self.assertNotEqual(norm[0], norm[1])
        hits = fuse({"bing": [SearchHit(urls[0], "Slug")], "duckduckgo": [SearchHit(urls[1], "Route")]}, limit=10)
        self.assertEqual(len(hits), 2)

    def test_rfc3986_unreserved_unquoting_nested_percent(self):
        urls = ["https://example.test/a%252Fb", "https://example.test/a%2Fb", "https://example.test/a%41b"]
        norm = [normalize_url(u) for u in urls]
        self.assertNotEqual(norm[0], norm[1])
        self.assertTrue(norm[2].endswith("/aAb"))

    def test_search_echoing_rate_limit_words_not_blocked(self):
        page = '<html><head><title>unusual traffic - Search</title></head><body><input value="unusual traffic"><div class="result results_links"><a class="result__a" href="https://ex.test">Hit</a></div></body></html>'
        hits = search_mod.parse_duckduckgo(page)
        self.assertEqual(len(hits), 1)

    def test_source_config_in_search_cache_keys(self):
        with mock.patch.dict(os.environ, {"GOOGLE_CSE_ID": "cse_1"}):
            k1 = search_mod._cache_key("google", "query", 10, "en")
        with mock.patch.dict(os.environ, {"GOOGLE_CSE_ID": "cse_2"}):
            k2 = search_mod._cache_key("google", "query", 10, "en")
        self.assertNotEqual(k1, k2)

    def test_duckduckgo_selects_forward_next_form(self):
        html = '''
        <div class="result results_links"><a class="result__a" href="https://ex.test">R</a></div>
        <div class="nav-link">
            <form action="/html/"><input type="hidden" name="s" value="0"><input type="submit" value="Previous"></form>
            <form action="/html/"><input type="hidden" name="s" value="20"><input type="submit" value="Next"></form>
        </div>
        '''
        class FakeResp:
            status_code = 200
            text = html
        calls = []
        def fake_http(*args, **kwargs):
            calls.append(kwargs.get("data", {}))
            return FakeResp()
        with mock.patch.object(search_mod, "_http", fake_http):
            hits = search_mod.engine_duckduckgo("query", limit=10, lang="en", timeout=5)
        self.assertTrue(any(c.get("s") == "20" for c in calls))

    def test_cache_ttl(self):
        cache = Cache(os.path.join(self.home, "c.db"))
        cache.set("k", {"a": 1}, ttl=60)
        cache.set("gone", 1, ttl=0.01)
        time.sleep(0.05)
        self.assertEqual(cache.get("k"), {"a": 1})
        self.assertIsNone(cache.get("gone"))
        cache.clear()
        self.assertIsNone(cache.get("k"))


class TestCrawlerOffline(unittest.TestCase):

    def test_normalize_crawl_url(self):
        self.assertEqual(normalize_crawl_url("https://Docs.test/a/?utm_source=x&page=2#top"), "https://docs.test/a?page=2")
        self.assertEqual(normalize_crawl_url("https://docs.test/"), "https://docs.test/")

    def test_relative_link_resolution_with_trailing_slash(self):
        import urllib.parse
        resp_url = "https://docs.test/tutorial/"
        link = "chapter1.html"
        resolved = urllib.parse.urljoin(resp_url, link)
        self.assertEqual(resolved, "https://docs.test/tutorial/chapter1.html")


class TestVectors(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_vector_store_and_knn(self):
        db_path = os.path.join(self.test_dir, "test_vec.db")
        store = VectorStore(db_path=db_path)
        items = [
            {"id": 1, "project": "cars", "text": "Volkswagen Golf engine OBD-2 diagnostics guide."},
            {"id": 2, "project": "cooking", "text": "Italian pizza dough recipe with yeast."}
        ]
        self.assertEqual(store.index_texts(items), 2)
        self.assertEqual(store.index_texts(items[:1]), 1)  # re-indexing replaces, no UNIQUE error

        results = store.search_knn("diagnostics scan", project="cars", limit=2)
        self.assertTrue(len(results) >= 1)
        self.assertEqual(results[0]["chunk_id"], 1)


@needs_net
class TestLive(unittest.TestCase):

    def test_tier0_fetch_static(self):
        res = scrape_url("https://example.com", force_tier=0)
        self.assertEqual(res.tier_used, "tier0_curl_cffi")
        self.assertIn("Example Domain", res.title)
        self.assertTrue(len(res.text) > 50)

    def test_tier1_fetch_scrapling(self):
        res = scrape_url("https://httpbin.org/html", force_tier=1)
        self.assertEqual(res.tier_used, "tier1_scrapling_fetcher")
        self.assertTrue(len(res.text) > 100)

    def test_tier2_fetch_stealth(self):
        res = scrape_url("https://quotes.toscrape.com/js/", force_tier=2)
        self.assertEqual(res.tier_used, "tier2_scrapling_stealth")
        self.assertTrue(len(res.text) > 100)

    def test_404_does_not_escalate(self):
        res = scrape_url("https://httpbin.org/status/404")
        self.assertEqual((res.status_code, res.tier_used), (404, "tier0_curl_cffi"))
        self.assertLess(res.elapsed, 10)

    def test_crawler_spider(self):
        items = crawl_site("https://quotes.toscrape.com/", max_pages=3, rate_limit=0.2)
        self.assertTrue(2 <= len(items) <= 3)
        self.assertTrue(items[0].url.startswith("http"))
        self.assertTrue(len(items[0].text) > 50)

    def test_live_engines(self):
        for name in ("bing", "yahoo", "wikipedia", "stackoverflow", "github", "hackernews", "arxiv"):
            with self.subTest(engine=name):
                r = search_mod.search("sqlite full text search", engines=name, cache_ttl=0, respect_cooldown=False)
                self.assertIn(r.reports[0].status, ("ok", "blocked"), r.reports[0].error)
                if r.reports[0].status == "ok":
                    self.assertTrue(all(h.url.startswith("http") for h in r.hits))


if __name__ == "__main__":
    unittest.main()
