"""
Scrapler Cache: tiny SQLite key/value store with TTL.

Shared across processes (WAL mode), so repeated CLI runs and the research skill
reuse search results, scraped pages and engine cooldowns instead of hitting the
network again.
"""

import json
import os
import sqlite3
import threading
import time
from typing import Any, Optional


def scrapler_home() -> str:
    """Directory for Scrapler state; override with SCRAPLER_HOME."""
    return os.environ.get("SCRAPLER_HOME") or os.path.join(os.path.expanduser("~"), ".scrapler")


class Cache:
    """SQLite-backed JSON cache. Every call opens its own connection, so it is thread-safe."""

    _init_lock = threading.Lock()

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(scrapler_home(), "cache.db")
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with self._init_lock, self._connect() as con:
            con.execute("PRAGMA journal_mode = WAL;")
            con.execute(
                "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires REAL NOT NULL)"
            )
            con.execute("DELETE FROM kv WHERE expires < ?", (time.time(),))

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=15.0)
        con.execute("PRAGMA busy_timeout = 15000;")
        return con

    def get(self, key: str) -> Optional[Any]:
        try:
            with self._connect() as con:
                row = con.execute("SELECT value, expires FROM kv WHERE key = ?", (key,)).fetchone()
        except sqlite3.Error:
            return None
        if not row or row[1] < time.time():
            return None
        try:
            return json.loads(row[0])
        except ValueError:
            return None

    def set(self, key: str, value: Any, ttl: float) -> None:
        if ttl <= 0:
            return
        try:
            with self._connect() as con:
                con.execute(
                    "INSERT OR REPLACE INTO kv(key, value, expires) VALUES (?, ?, ?)",
                    (key, json.dumps(value, ensure_ascii=False), time.time() + ttl),
                )
        except sqlite3.Error:
            pass

    def delete(self, key: str) -> None:
        try:
            with self._connect() as con:
                con.execute("DELETE FROM kv WHERE key = ?", (key,))
        except sqlite3.Error:
            pass

    def clear(self, prefix: str = "") -> int:
        with self._connect() as con:
            cur = con.execute("DELETE FROM kv WHERE key LIKE ?", (prefix + "%",))
            return cur.rowcount


_default_cache: Optional[Cache] = None
_default_lock = threading.Lock()


def get_cache() -> Cache:
    """Process-wide default cache (lazily created)."""
    global _default_cache
    with _default_lock:
        if _default_cache is None or _default_cache.db_path != os.path.join(scrapler_home(), "cache.db"):
            _default_cache = Cache()
        return _default_cache
