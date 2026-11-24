"""Integration tests for FastAPI REST endpoints and WebSocket media streaming."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.stream.muxer import TYPE_VIDEO_CONFIG, TYPE_VIDEO_FRAME, decode_packet


def test_api_overview_simulator_websocket_and_problem_details(tmp_path: Path) -> None:
    cfg = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "test.db",
        driver_backup_dir=tmp_path / "data" / "backups",
        frontend_dist_dir=tmp_path / "no_dist",
    )
    app = create_app(cfg)

    with TestClient(app) as client:
        res_health = client.get("/api/health")
        assert res_health.status_code == 200
        assert res_health.json()["status"] == "ok"

        res_overview = client.get("/api/overview")
        assert res_overview.status_code == 200
        body = res_overview.json()
        assert body["stream"]["mode"] == "idle"
        assert "wifi_direct" in body

        # RFC 9457 Problem Details validation error on bad USB instance ID
        res_bad = client.post(
            "/api/usb/driver",
            json={"instance_id": "USB\\VID_0000\\BAD", "action": "restore_apple"},
        )
        assert res_bad.status_code == 400
        assert res_bad.headers["content-type"].startswith("application/problem+json")

        # Start Simulator stream & receive real H.264 packets over WebSocket
        res_start = client.post(
            "/api/stream/start",
            json={"mode": "simulator", "device_label": "iPhone 16 Pro Max", "audio_enabled": True},
        )
        assert res_start.status_code == 200
        assert res_start.json()["active"] is True

        seen_types: set[int] = set()
        with client.websocket_connect("/ws/stream") as ws:
            for _ in range(12):
                raw = ws.receive_bytes()
                ptype, _flags, _pts, _payload = decode_packet(raw)
                seen_types.add(ptype)
                if TYPE_VIDEO_CONFIG in seen_types and TYPE_VIDEO_FRAME in seen_types:
                    break

        assert TYPE_VIDEO_CONFIG in seen_types
        assert TYPE_VIDEO_FRAME in seen_types

        res_stop = client.post("/api/stream/stop")
        assert res_stop.status_code == 200
        assert res_stop.json()["active"] is False

        sessions = client.get("/api/sessions").json()
        assert len(sessions) == 1
        assert sessions[0]["mode"] == "simulator"

        # Waiting USB handshake without received media frames must not inflate estimated_saved_mb
        class _WaitingUsbStreamer:
            def __init__(self, **_kwargs):
                self._stop = False

            def request_stop(self) -> None:
                self._stop = True

            async def start(self) -> None:
                while not self._stop:
                    await asyncio.sleep(0.02)

        with patch("app.main.QuickTimeUsbStreamer", _WaitingUsbStreamer):
            res_usb = client.post(
                "/api/stream/start",
                json={"mode": "usb_quicktime", "device_label": "iPhone 13", "audio_enabled": True},
            )
            assert res_usb.status_code == 200
            usb_tel = client.get("/api/overview").json()["stream"]
            assert usb_tel["mode"] == "usb_quicktime"
            assert usb_tel["bytes_received"] == 0
            assert usb_tel["estimated_saved_mb"] == 0.0
            assert usb_tel["latency_ms"] == 0.0
            res_usb_stop = client.post("/api/stream/stop")
            assert res_usb_stop.status_code == 200
            latest_session = client.get("/api/sessions").json()[0]
            assert latest_session["mode"] == "usb_quicktime"
            assert latest_session["bytes_received"] == 0
            assert latest_session["estimated_saved_mb"] == 0.0


def test_api_usb_device_enumeration_and_wfd_validation(
    tmp_path: Path, monkeypatch
) -> None:
    from app.models import AppleUsbDevice

    monkeypatch.setenv("APPDATA", str(tmp_path))

    cfg = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "test.db",
        driver_backup_dir=tmp_path / "data" / "backups",
        frontend_dist_dir=tmp_path / "no_dist",
    )
    app = create_app(cfg)

    mock_device = AppleUsbDevice(
        instance_id=r"USB\VID_05AC&PID_12A8\00008140001A2B3C",
        friendly_name="Apple Mobile Device USB Composite Device",
        product_id="12A8",
        serial="00008140001A2B3C",
        model_hint="iPhone 16 Pro Max",
        cable_hint="USB Type-C",
        active_service="usbccgp",
        status="OK",
        qt_ready=True,
        driver_mode="apple_usbccgp",
    )

    with TestClient(app) as client:
        with patch("app.main.detect_apple_usb_devices", return_value=[mock_device]):
            res_alias = client.get("/api/devices")
            assert res_alias.status_code == 200
            devices_alias = res_alias.json()
            assert len(devices_alias) == 1
            assert devices_alias[0]["serial"] == "00008140001A2B3C"
            assert devices_alias[0]["model_hint"] == "iPhone 16 Pro Max"
            assert devices_alias[0]["qt_ready"] is True

            res_usb = client.get("/api/usb/devices")
            assert res_usb.status_code == 200
            devices_usb = res_usb.json()
            assert len(devices_usb) == 1
            assert devices_usb[0]["serial"] == "00008140001A2B3C"

        res_wfd_bad = client.post("/api/wifi-direct/start", json={"ssid": "ABC"})
        assert res_wfd_bad.status_code == 422

        with patch("app.airplay.uxplay_manager.UxPlayManager._sync_uxplay_qsettings"):
            res_wm = client.post("/api/airplay/window-mode", json={"fullscreen": False})
            assert res_wm.status_code == 200
            assert res_wm.json()["ok"] is True
            assert res_wm.json()["fullscreen"] is False

        with (
            patch("app.airplay.uxplay_manager.UxPlayManager.bonjour_ready", return_value=False),
            patch(
                "app.airplay.uxplay_manager.UxPlayManager.install_bonjour",
                return_value=(False, "Bonjour kurulumu bekliyor"),
            ),
        ):
            ov = client.get("/api/overview").json()
            assert ov["bonjour_ready"] is False
            res_bj = client.post("/api/airplay/install-bonjour")
            assert res_bj.status_code == 200
            assert res_bj.json()["bonjour_ready"] is False
            res_ap = client.post(
                "/api/stream/start",
                json={"mode": "airplay_uxplay", "airplay_name": "KabloCast-Test"},
            )
            assert res_ap.status_code == 200
            assert res_ap.json()["active"] is False
            assert "Bonjour" in (res_ap.json()["last_error"] or "")

        class _StatusUsbStreamer:
            def __init__(self, on_status=None, **_kwargs):
                self._on_status = on_status
                self._stop = False

            def request_stop(self) -> None:
                self._stop = True

            async def start(self) -> None:
                if self._on_status:
                    self._on_status("iOS 18/26/27+ Valeria kısıtı uyarısı")
                while not self._stop:
                    await asyncio.sleep(0.02)

        with patch("app.main.QuickTimeUsbStreamer", _StatusUsbStreamer):
            client.post(
                "/api/stream/start",
                json={"mode": "usb_quicktime", "device_label": "iPhone"},
            )
            import time

            time.sleep(0.06)
            tel = client.get("/api/overview").json()["stream"]
            assert tel["active"] is True
            assert "Valeria" in (tel["last_error"] or "")
            client.post("/api/stream/stop")
