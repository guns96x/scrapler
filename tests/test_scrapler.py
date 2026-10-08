"""
Unit and integration tests for Scrapler package.
"""

import os
import shutil
import tempfile
import unittest
from scrapler.engine import scrape_url, is_challenge_or_blocked, extract_title
from scrapler.crawler import crawl_site
from scrapler.vectors import VectorStore, HybridRetriever


class TestScrapler(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_challenge_detection(self):
        self.assertTrue(is_challenge_or_blocked(403, "Forbidden"))
        self.assertTrue(is_challenge_or_blocked(200, "<html>Just a moment... Please verify you are a human</html>"))
        self.assertFalse(is_challenge_or_blocked(200, "<html><h1>Normal Documentation Page</h1></html>"))

    def test_title_extraction(self):
        html = "<html><head><title>My Awesome Docs</title></head><body>Content</body></html>"
        self.assertEqual(extract_title(html), "My Awesome Docs")

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

    def test_crawler_spider(self):
        items = crawl_site("https://quotes.toscrape.com/", max_pages=2, rate_limit=0.2)
        self.assertTrue(len(items) >= 2)
        self.assertTrue(items[0].url.startswith("http"))
        self.assertTrue(len(items[0].text) > 50)

    def test_vector_store_and_knn(self):
        db_path = os.path.join(self.test_dir, "test_vec.db")
        store = VectorStore(db_path=db_path)
        items = [
            {"id": 1, "project": "cars", "text": "Volkswagen Golf engine OBD-2 diagnostics guide."},
            {"id": 2, "project": "cooking", "text": "Italian pizza dough recipe with yeast."}
        ]
        indexed = store.index_texts(items)
        self.assertEqual(indexed, 2)

        results = store.search_knn("diagnostics scan", project="cars", limit=2)
        self.assertTrue(len(results) >= 1)
        self.assertEqual(results[0]["chunk_id"], 1)

    def test_hybrid_rrf(self):
        fts_ranks = [1, 2, 3]
        vec_ranks = [2, 1, 4]
        rrf = HybridRetriever.compute_rrf(fts_ranks, vec_ranks, k=60, limit=3)
        self.assertEqual(len(rrf), 3)
        # 1 and 2 appear in both lists, so they must have highest scores
        top_ids = [cid for cid, score in rrf[:2]]
        self.assertIn(1, top_ids)
        self.assertIn(2, top_ids)


if __name__ == "__main__":
    unittest.main()
