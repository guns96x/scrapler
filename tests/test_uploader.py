import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from scrapler.uploader.job_store import JobStore, calculate_file_hash
from scrapler.uploader.octo_client import OctoClient, OctoClientError


class TestJobStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_jobs.db")
        self.store = JobStore(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_get_job(self):
        job = self.store.create_job(
            job_id="test-job-1",
            profile_uuid="uuid-123",
            file_path="some_video.mp4",
            title="My Video",
            description="My Desc",
            visibility="unlisted"
        )
        self.assertEqual(job["job_id"], "test-job-1")
        self.assertEqual(job["status"], "PENDING")
        self.assertEqual(job["title"], "My Video")

        fetched = self.store.get_job("test-job-1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["profile_uuid"], "uuid-123")

    def test_update_job(self):
        self.store.create_job(
            job_id="test-job-2",
            profile_uuid="uuid-123",
            file_path="some_video.mp4",
            title="My Video",
            description="My Desc"
        )
        self.store.update_job(
            job_id="test-job-2",
            status="PUBLISHED",
            video_id="abc123xyz",
            video_url="https://youtu.be/abc123xyz"
        )
        job = self.store.get_job("test-job-2")
        self.assertEqual(job["status"], "PUBLISHED")
        self.assertEqual(job["video_id"], "abc123xyz")
        self.assertEqual(job["video_url"], "https://youtu.be/abc123xyz")

    def test_profile_lock(self):
        acquired1 = self.store.acquire_lock("uuid-lock-test", "job-1")
        self.assertTrue(acquired1)

        # Another job cannot acquire same lock
        acquired2 = self.store.acquire_lock("uuid-lock-test", "job-2")
        self.assertFalse(acquired2)

        # Same job ID cannot steal active lock
        acquired_same = self.store.acquire_lock("uuid-lock-test", "job-1")
        self.assertFalse(acquired_same)

        # Renewal works
        renewed = self.store.renew_lock("uuid-lock-test", "job-1")
        self.assertTrue(renewed)

        # Release lock
        self.store.release_lock("uuid-lock-test", "job-1")
        acquired3 = self.store.acquire_lock("uuid-lock-test", "job-2")
        self.assertTrue(acquired3)


class TestOctoClient(unittest.TestCase):
    @patch("requests.get")
    def test_is_healthy(self, mock_get):
        mock_get.return_value.status_code = 200
        client = OctoClient()
        self.assertTrue(client.is_healthy())

        mock_get.side_effect = Exception("network down")
        self.assertFalse(client.is_healthy())

    @patch("requests.get")
    @patch("requests.post")
    def test_start_profile(self, mock_post, mock_get):
        # Mock active profiles check (returns empty list)
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = []

        # Mock start profile response
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "ws_endpoint": "ws://127.0.0.1:12345/devtools",
            "debug_port": 12345
        }
        client = OctoClient()
        info = client.start_profile("test-uuid")
        self.assertEqual(info["ws_endpoint"], "ws://127.0.0.1:12345/devtools")
        self.assertFalse(info["already_running"])

    @patch("requests.post")
    def test_stop_profile(self, mock_post):
        mock_post.return_value.status_code = 200
        client = OctoClient()
        self.assertTrue(client.stop_profile("test-uuid"))


if __name__ == "__main__":
    unittest.main()
