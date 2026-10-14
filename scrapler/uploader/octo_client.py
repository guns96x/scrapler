import time
import logging
import requests
from typing import Optional, Dict, Any, List

logger = logging.getLogger("octo_uploader.octo_client")

DEFAULT_OCTO_LOCAL_URL = "http://127.0.0.1:58888"


class OctoClientError(Exception):
    """Base exception for Octo Client operations."""
    pass


class OctoClient:
    """Client for Octo Browser Local Automation API."""

    def __init__(self, base_url: str = DEFAULT_OCTO_LOCAL_URL, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def is_healthy(self) -> bool:
        """Check if Octo Browser local API is reachable."""
        try:
            r = requests.get(f"{self.base_url}/api/profiles/active", timeout=5)
            return r.status_code == 200
        except Exception as e:
            logger.debug(f"Octo health check failed: {e}")
            return False

    def get_active_profiles(self) -> List[Dict[str, Any]]:
        """List currently launched profiles on the device."""
        try:
            r = requests.get(f"{self.base_url}/api/profiles/active", timeout=10)
            if r.status_code == 200:
                return r.json()
            raise OctoClientError(f"Failed to get active profiles: {r.status_code} {r.text}")
        except requests.RequestException as e:
            raise OctoClientError(f"Connection error to Octo Browser at {self.base_url}: {e}")

    def find_active_profile(self, uuid: str) -> Optional[Dict[str, Any]]:
        """Find active profile info if already running."""
        for p in self.get_active_profiles():
            if p.get("uuid") == uuid:
                return p
        return None

    def start_profile(
        self,
        uuid: str,
        headless: bool = False,
        debug_port: bool = True,
        flags: Optional[List[str]] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Start an Octo profile with debug_port enabled.
        Returns dict containing 'ws_endpoint' and 'debug_port'.
        """
        active = self.find_active_profile(uuid)
        if active and active.get("ws_endpoint"):
            logger.info(f"Profile {uuid} is already active with ws_endpoint: {active['ws_endpoint']}")
            active["already_running"] = True
            return active

        payload = {
            "uuid": uuid,
            "headless": headless,
            "debug_port": debug_port,
            "only_local": True,
            "flags": flags or [
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding"
            ]
        }
        if timeout:
            payload["timeout"] = timeout

        logger.info(f"Starting Octo profile {uuid} (headless={headless})...")
        try:
            r = requests.post(
                f"{self.base_url}/api/profiles/start",
                json=payload,
                timeout=self.timeout
            )
            if r.status_code != 200:
                err_text = r.text
                try:
                    err_json = r.json()
                    err_text = err_json.get("error", err_text)
                except Exception:
                    pass
                raise OctoClientError(f"Octo start failed for {uuid}: {r.status_code} - {err_text}")

            data = r.json()
            data["already_running"] = False
            logger.info(f"Profile {uuid} started successfully. ws_endpoint: {data.get('ws_endpoint')}")
            return data
        except requests.RequestException as e:
            raise OctoClientError(f"HTTP request to start profile {uuid} failed: {e}")

    def stop_profile(self, uuid: str) -> bool:
        """
        Gracefully stop an Octo profile to save cloud state, cookies, and session.
        """
        logger.info(f"Stopping Octo profile {uuid}...")
        try:
            r = requests.post(
                f"{self.base_url}/api/profiles/stop",
                json={"uuid": uuid},
                timeout=30
            )
            if r.status_code == 200:
                logger.info(f"Profile {uuid} stopped successfully.")
                return True
            logger.warning(f"Stop profile {uuid} returned status {r.status_code}: {r.text}")
            return False
        except requests.RequestException as e:
            logger.error(f"Failed to stop profile {uuid}: {e}")
            return False

    def force_stop_profile(self, uuid: str) -> bool:
        """Force kill a profile if graceful stop hangs."""
        logger.warning(f"Force stopping profile {uuid}...")
        try:
            r = requests.post(
                f"{self.base_url}/api/profiles/force_stop",
                json={"uuid": uuid},
                timeout=15
            )
            return r.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Failed to force stop profile {uuid}: {e}")
            return False
