import sqlite3
import os
import hashlib
import time
from contextlib import contextmanager
from typing import Optional, Dict, Any, Generator

DB_PATH = os.path.join(os.path.dirname(__file__), "upload_jobs.db")


def calculate_file_hash(filepath: str) -> str:
    """Calculate SHA256 of file header/tail for fast idempotency check."""
    if not os.path.exists(filepath) or not os.path.isfile(filepath):
        return ""
    h = hashlib.sha256()
    size = os.path.getsize(filepath)
    with open(filepath, "rb") as f:
        # Read first 1MB and last 1MB + size
        h.update(f.read(1024 * 1024))
        if size > 1024 * 1024:
            f.seek(max(0, size - 1024 * 1024))
            h.update(f.read(1024 * 1024))
        h.update(str(size).encode())
    return h.hexdigest()


class JobStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS upload_jobs (
                    job_id TEXT PRIMARY KEY,
                    profile_uuid TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_hash TEXT,
                    title TEXT,
                    description TEXT,
                    visibility TEXT,
                    video_id TEXT,
                    video_url TEXT,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS profile_locks (
                    profile_uuid TEXT PRIMARY KEY,
                    locked_by_job TEXT NOT NULL,
                    locked_at REAL NOT NULL
                )
            """)
            conn.commit()

    def acquire_lock(self, profile_uuid: str, job_id: str, timeout_seconds: int = 1800) -> bool:
        """
        Acquire exclusive lock on profile.
        Only clears locks that have strictly expired (locked_at < now - timeout_seconds).
        Never clears active locks from the same or different job.
        """
        now = time.time()
        with self._conn() as conn:
            # Delete only genuinely expired locks
            conn.execute(
                "DELETE FROM profile_locks WHERE profile_uuid = ? AND locked_at < ?",
                (profile_uuid, now - timeout_seconds)
            )
            try:
                conn.execute(
                    "INSERT INTO profile_locks (profile_uuid, locked_by_job, locked_at) VALUES (?, ?, ?)",
                    (profile_uuid, job_id, now)
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def renew_lock(self, profile_uuid: str, job_id: str) -> bool:
        """Renew active lease for the current job."""
        now = time.time()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE profile_locks SET locked_at = ? WHERE profile_uuid = ? AND locked_by_job = ?",
                (now, profile_uuid, job_id)
            )
            conn.commit()
            return cur.rowcount > 0

    def release_lock(self, profile_uuid: str, job_id: str):
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM profile_locks WHERE profile_uuid = ? AND locked_by_job = ?",
                (profile_uuid, job_id)
            )
            conn.commit()

    def create_job(
        self,
        job_id: str,
        profile_uuid: str,
        file_path: str,
        title: str,
        description: str,
        visibility: str = "unlisted"
    ) -> Dict[str, Any]:
        file_hash = calculate_file_hash(file_path)
        now = time.time()
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO upload_jobs 
                (job_id, profile_uuid, file_path, file_hash, title, description, visibility, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """, (job_id, profile_uuid, file_path, file_hash, title, description, visibility, now, now))
            conn.commit()
        return self.get_job(job_id)

    def update_job(
        self,
        job_id: str,
        status: Optional[str] = None,
        video_id: Optional[str] = None,
        video_url: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        now = time.time()
        updates = ["updated_at = ?"]
        params = [now]
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if video_id is not None:
            updates.append("video_id = ?")
            params.append(video_id)
        if video_url is not None:
            updates.append("video_url = ?")
            params.append(video_url)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)

        params.append(job_id)
        query = f"UPDATE upload_jobs SET {', '.join(updates)} WHERE job_id = ?"
        with self._conn() as conn:
            conn.execute(query, params)
            conn.commit()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            cur = conn.execute("SELECT * FROM upload_jobs WHERE job_id = ?", (job_id,))
            row = cur.fetchone()
            if row:
                return dict(row)
        return None
