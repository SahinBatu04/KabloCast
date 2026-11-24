"""SQLite (WAL mode) persistence for sessions, preferences, and driver backups."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .models import MirrorSessionRecord

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL CHECK(mode IN ('usb_quicktime', 'airplay_uxplay', 'simulator')),
    device_name TEXT NOT NULL,
    device_model TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_sec REAL NOT NULL DEFAULT 0.0,
    video_codec TEXT NOT NULL DEFAULT 'H.264',
    resolution TEXT NOT NULL DEFAULT '1920x1080',
    avg_fps REAL NOT NULL DEFAULT 0.0,
    bytes_received INTEGER NOT NULL DEFAULT 0,
    estimated_saved_mb REAL NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at DESC);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS driver_backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    previous_service TEXT NOT NULL,
    backup_json_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_profiles (
    profile_key TEXT PRIMARY KEY,
    audio_endpoint_id TEXT NOT NULL,
    audio_label TEXT NOT NULL,
    device_key TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('auto', 'manual')),
    manual_offset_ms INTEGER NOT NULL DEFAULT 180,
    updated_at TEXT NOT NULL
);
"""


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


class Database:
    """Thread-safe SQLite WAL repository wrapper."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def start_session(
        self,
        mode: str,
        device_name: str,
        device_model: str,
        video_codec: str = "H.264",
        resolution: str = "1920x1080",
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO sessions (
                    mode, device_name, device_model, started_at, video_codec, resolution
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (mode, device_name, device_model, _utc_now(), video_codec, resolution),
            )
            return int(cur.lastrowid or 0)

    def finish_session(
        self,
        session_id: int,
        duration_sec: float,
        avg_fps: float,
        bytes_received: int,
        estimated_saved_mb: float,
        resolution: str | None = None,
        video_codec: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET ended_at = ?,
                    duration_sec = ?,
                    avg_fps = ?,
                    bytes_received = ?,
                    estimated_saved_mb = ?,
                    resolution = COALESCE(?, resolution),
                    video_codec = COALESCE(?, video_codec)
                WHERE id = ?
                """,
                (
                    _utc_now(),
                    round(duration_sec, 2),
                    round(avg_fps, 1),
                    int(bytes_received),
                    round(estimated_saved_mb, 2),
                    resolution,
                    video_codec,
                    session_id,
                ),
            )

    def list_sessions(self, limit: int = 20) -> list[MirrorSessionRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [MirrorSessionRecord(**dict(row)) for row in rows]

    def total_saved_mb(self) -> float:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(estimated_saved_mb), 0.0) AS total FROM sessions"
            ).fetchone()
        return round(float(row["total"]) if row else 0.0, 2)

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, _utc_now()),
            )

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def record_driver_backup(
        self, instance_id: str, previous_service: str, backup_json_path: str
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO driver_backups (
                    instance_id, previous_service, backup_json_path, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (instance_id, previous_service, backup_json_path, _utc_now()),
            )

    def get_sync_profile(self, profile_key: str) -> dict[str, object] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sync_profiles WHERE profile_key = ?",
                (profile_key,),
            ).fetchone()
        return dict(row) if row else None

    def save_sync_profile(
        self,
        profile_key: str,
        audio_endpoint_id: str,
        audio_label: str,
        device_key: str,
        mode: str,
        manual_offset_ms: int,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_profiles (
                    profile_key,
                    audio_endpoint_id,
                    audio_label,
                    device_key,
                    mode,
                    manual_offset_ms,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_key) DO UPDATE SET
                    audio_endpoint_id = excluded.audio_endpoint_id,
                    audio_label = excluded.audio_label,
                    device_key = excluded.device_key,
                    mode = excluded.mode,
                    manual_offset_ms = excluded.manual_offset_ms,
                    updated_at = excluded.updated_at
                """,
                (
                    profile_key,
                    audio_endpoint_id,
                    audio_label,
                    device_key,
                    mode,
                    int(manual_offset_ms),
                    _utc_now(),
                ),
            )
