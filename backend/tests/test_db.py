"""Tests for SQLite WAL persistence layer."""

from __future__ import annotations

from pathlib import Path

from app.db import Database


def test_database_wal_sessions_and_settings(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    with db.connect() as conn:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert str(mode).lower() == "wal"

    sid = db.start_session(
        "usb_quicktime", "iPhone 16 Pro Max", "iPhone 16 Pro Max", "H.264", "1920x1080"
    )
    assert sid > 0
    db.finish_session(
        sid,
        duration_sec=120.5,
        avg_fps=59.8,
        bytes_received=45_000_000,
        estimated_saved_mb=128.0,
    )

    sid2 = db.start_session("airplay_uxplay", "iPhone 13", "iPhone 13", "HEVC", "2532x1170")
    db.finish_session(
        sid2,
        duration_sec=60.0,
        avg_fps=60.0,
        bytes_received=22_000_000,
        estimated_saved_mb=64.0,
    )

    sessions = db.list_sessions(limit=10)
    assert len(sessions) == 2
    assert sessions[0].id == sid2
    assert db.total_saved_mb() == 192.0

    db.set_setting("airplay_name", "LivingRoom-PC")
    assert db.get_setting("airplay_name") == "LivingRoom-PC"
    db.set_setting("airplay_name", "KabloCast")
    assert db.get_setting("airplay_name") == "KabloCast"

    db.record_driver_backup("USB\\VID_05AC&PID_12A8\\ABC123", "usbccgp", "C:/backups/b1.json")
    with db.connect() as conn:
        cnt = conn.execute("SELECT COUNT(*) FROM driver_backups").fetchone()[0]
    assert cnt == 1
