"""Unit and integration tests for universal Apple detection, A/V sync, and 1-click QuickStart."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.airplay.uxplay_manager import AirPlayRuntimeState
from app.audio_sync import classify_audio_output, compute_recommended_sync_ms
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.models import AppleUsbDevice, DriverActionResult, NetworkAdapterMetrics
from app.usb.driver_assistant import infer_apple_device_hint


def test_classify_audio_output_and_recommended_sync() -> None:
    assert classify_audio_output("Speaker", "Realtek(R) Audio") == "speaker"
    assert classify_audio_output("VG279Q5A", "NVIDIA High Definition Audio") == "hdmi_monitor"
    assert classify_audio_output("Kulaklıklar", "H2002BG ") == "wireless_headset"
    assert classify_audio_output("Kulaklıklar", "Realtek(R) Audio") == "wired_headphones"
    assert classify_audio_output("AirPods Pro", "Bluetooth A2DP") == "bluetooth"

    assert compute_recommended_sync_ms("speaker", "lan_wifi", "1080p") == 180
    assert compute_recommended_sync_ms("speaker", "usb_zero_quota", "1080p") == 170
    assert compute_recommended_sync_ms("speaker", "wifi_direct", "1440p") == 210
    assert compute_recommended_sync_ms("bluetooth", "lan_wifi", "1080p") == 10
    assert compute_recommended_sync_ms("wireless_headset", "lan_wifi", "1080p") == 140


def test_infer_apple_device_hint_covers_iphone_and_ipad() -> None:
    assert infer_apple_device_hint("12A8", "000081400011223344556677", "Apple Mobile Device") == (
        "iPhone 16 Pro / Pro Max",
        "USB Type-C Kablo",
    )
    assert infer_apple_device_hint("12A8", "000081100011223344556677", "Apple Mobile Device") == (
        "iPhone 13 / 14",
        "Lightning → Type-C Kablo",
    )
    assert infer_apple_device_hint("12AB", "000081031122334455667788", "Apple iPad")[0].startswith(
        "iPad"
    )
    assert infer_apple_device_hint("12A8", "UNKNOWN_SERIAL", "Apple Mobile Device")[0].startswith(
        "iPhone"
    )


def test_sync_profiles_db_persistence(tmp_path: Path) -> None:
    db = Database(tmp_path / "sync.db")
    assert db.get_sync_profile("ep1::dev1") is None

    db.save_sync_profile("ep1::dev1", "ep1", "Speaker (Realtek)", "dev1", "manual", 240)
    saved = db.get_sync_profile("ep1::dev1")
    assert saved is not None
    assert saved["mode"] == "manual"
    assert saved["manual_offset_ms"] == 240

    db.save_sync_profile("ep1::dev1", "ep1", "Speaker (Realtek)", "dev1", "auto", 180)
    reset = db.get_sync_profile("ep1::dev1")
    assert reset is not None
    assert reset["mode"] == "auto"


def test_quickstart_and_audio_sync_api_integration(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))

    cfg = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "test.db",
        driver_backup_dir=tmp_path / "data" / "backups",
        frontend_dist_dir=tmp_path / "no_dist",
    )
    app = create_app(cfg)

    mock_libusb_device = AppleUsbDevice(
        instance_id=r"USB\VID_05AC&PID_12A8\000081400011223344556677",
        friendly_name="Apple Mobile Device USB Composite Device",
        product_id="12A8",
        serial="000081400011223344556677",
        model_hint="iPhone 16 Pro / Pro Max",
        cable_hint="USB Type-C Kablo",
        active_service="libusb0",
        status="OK",
        qt_ready=True,
        driver_mode="libusb_win32",
    )

    mock_adapters = [
        NetworkAdapterMetrics(
            name="Apple Mobile Device Ethernet",
            description="Apple Mobile Device Ethernet",
            is_up=True,
            ipv4="172.20.10.3",
            rx_bytes=100,
            tx_bytes=50,
            rx_kbps=0.0,
            tx_kbps=0.0,
            looks_like_hotspot=True,
        )
    ]

    shield_state = {"active": False}

    def fake_query_shield_rules() -> int:
        return 5 if shield_state["active"] else 0

    def fake_run_elevated(script: str, timeout: int = 30):
        if "New-NetFirewallRule" in script:
            shield_state["active"] = True
        elif "Remove-NetFirewallRule" in script:
            shield_state["active"] = False
        return True, "ok"

    class _FakeProc:
        pid = 4321

        def poll(self) -> None:
            return None

    ux_mgr = app.state.orchestrator.uxplay
    recorded_sync_args: list[int] = []

    def fake_uxplay_start(**kwargs) -> AirPlayRuntimeState:
        recorded_sync_args.append(int(kwargs.get("audio_sync_ms", 180)))
        ux_mgr._proc = _FakeProc()  # type: ignore[assignment]
        ux_mgr._last_resolution_preset = kwargs.get("resolution_preset", "1080p")
        ux_mgr._last_audio_enabled = bool(kwargs.get("audio_enabled", True))
        ux_mgr._last_audio_sync_ms = int(kwargs.get("audio_sync_ms", 180))
        ux_mgr._last_fullscreen = bool(kwargs.get("fullscreen", True))
        ux_mgr.state = AirPlayRuntimeState(
            running=True,
            pid=4321,
            airplay_name=kwargs.get("airplay_name", "KabloCast"),
            client_connected=False,
            client_name="Bekleniyor",
            codec="H.264 (AVC / D3D11)",
            resolution="1920x1080",
        )
        return ux_mgr.state

    def fake_uxplay_stop() -> AirPlayRuntimeState:
        ux_mgr._proc = None
        ux_mgr.state.running = False
        ux_mgr.state.client_connected = False
        ux_mgr.state.pid = None
        return ux_mgr.state

    with TestClient(app) as client:
        with (
            patch("app.main.detect_apple_usb_devices", return_value=[mock_libusb_device]),
            patch(
                "app.audio_sync.detect_default_audio_output",
                return_value=("ep-realtek", "Speaker", "Realtek(R) Audio"),
            ),
            patch(
                "app.network.quota_shield.QuotaShieldManager.sample_adapters",
                return_value=mock_adapters,
            ),
            patch(
                "app.network.quota_shield.QuotaShieldManager._query_shield_rules",
                side_effect=fake_query_shield_rules,
            ),
            patch(
                "app.network.quota_shield.run_elevated_powershell",
                side_effect=fake_run_elevated,
            ),
            patch(
                "app.main.run_driver_assistant",
                return_value=DriverActionResult(
                    ok=True,
                    action="restore_apple",
                    instance_id=mock_libusb_device.instance_id,
                    message="Apple moduna döndürüldü",
                    requires_uac=True,
                ),
            ) as mock_driver,
            patch("app.airplay.uxplay_manager.UxPlayManager.bonjour_ready", return_value=True),
            patch("app.airplay.uxplay_manager.UxPlayManager.start", side_effect=fake_uxplay_start),
            patch("app.airplay.uxplay_manager.UxPlayManager.stop", side_effect=fake_uxplay_stop),
        ):
            ov = client.get("/api/overview").json()
            assert ov["recommended_strategy"] == "usb_zero_quota"
            assert ov["audio_sync"]["output_kind"] == "speaker"
            assert ov["audio_sync"]["effective_ms"] == 170

            qs = client.post("/api/quickstart", json={"connection_strategy": "auto"})
            assert qs.status_code == 200
            qs_body = qs.json()
            assert qs_body["ok"] is True
            assert qs_body["selected_strategy"] == "usb_zero_quota"
            assert qs_body["applied_sync_ms"] == 170
            assert qs_body["sync_source"] == "auto"
            assert shield_state["active"] is True
            assert mock_driver.called

            # Save manual override for this device + endpoint and apply live while AirPlay runs
            upd = client.post(
                "/api/audio-sync",
                json={"mode": "manual", "manual_offset_ms": 235, "apply_live": True},
            )
            assert upd.status_code == 200
            upd_body = upd.json()
            assert upd_body["mode"] == "manual"
            assert upd_body["effective_ms"] == 235
            assert recorded_sync_args[-1] == 235

            # Subsequent quickstart honors saved manual sync
            qs2 = client.post("/api/quickstart", json={"connection_strategy": "auto"})
            assert qs2.status_code == 200
            assert qs2.json()["applied_sync_ms"] == 235
            assert qs2.json()["sync_source"] == "saved_manual"

            # Reset back to auto
            rst = client.post(
                "/api/audio-sync",
                json={"mode": "auto", "manual_offset_ms": 180, "apply_live": False},
            )
            assert rst.status_code == 200
            assert rst.json()["mode"] == "auto"
            assert rst.json()["effective_ms"] == 170
