"""Tests for H.264 PyAV simulator, binary muxer, QR/BLE helpers, and driver validation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import unquote

import pytest

from app.airplay.uxplay_manager import UxPlayManager
from app.network.ble_beacon import build_airplay_ble_payload
from app.network.wifi_direct import build_manual_ip_guide, build_wifi_qr_data_uri
from app.stream.muxer import (
    TYPE_AUDIO_PCM,
    TYPE_VIDEO_CONFIG,
    TYPE_VIDEO_FRAME,
    decode_packet,
    encode_audio_pcm,
    encode_video_config,
    encode_video_frame,
)
from app.stream.simulator import StreamSimulator
from app.usb.driver_assistant import classify_driver_mode, validate_apple_instance_id


def test_muxer_roundtrip() -> None:
    cfg = encode_video_config("avc1.42c01f", 960, 540, 30)
    ptype, flags, pts, payload = decode_packet(cfg)
    assert ptype == TYPE_VIDEO_CONFIG
    assert flags == 0
    assert pts == 0
    assert b"avc1.42c01f" in payload

    vid = encode_video_frame(b"\x00\x00\x00\x01\x65\x88", 33333, True)
    ptype, flags, pts, payload = decode_packet(vid)
    assert ptype == TYPE_VIDEO_FRAME
    assert flags == 1
    assert pts == 33333
    assert payload.startswith(b"\x00\x00\x00\x01")

    aud = encode_audio_pcm(b"\x01\x02\x03\x04", 16000)
    ptype, flags, pts, payload = decode_packet(aud)
    assert ptype == TYPE_AUDIO_PCM
    assert pts == 16000
    assert payload == b"\x01\x02\x03\x04"


@pytest.mark.asyncio
async def test_stream_simulator_emits_real_h264_and_pcm() -> None:
    sim = StreamSimulator(width=320, height=180, fps=15)
    configs: list[tuple[str, int, int, int]] = []
    frames: list[tuple[bytes, bool, int]] = []
    audios: list[tuple[bytes, int]] = []

    async def on_cfg(codec: str, w: int, h: int, fps: int) -> None:
        configs.append((codec, w, h, fps))

    async def on_vid(data: bytes, key: bool, pts: int) -> None:
        frames.append((data, key, pts))
        if len(frames) >= 4:
            sim.request_stop()

    async def on_aud(pcm: bytes, pts: int) -> None:
        audios.append((pcm, pts))

    await asyncio.wait_for(sim.run(on_cfg, on_vid, on_aud), timeout=8.0)
    assert len(configs) == 1
    assert configs[0][0].startswith("avc1.")
    assert len(frames) >= 4
    assert frames[0][1] is True
    assert b"\x00\x00\x00\x01" in frames[0][0]
    assert len(audios) >= 3


def test_wifi_qr_ble_payload_and_driver_validation() -> None:
    qr = build_wifi_qr_data_uri("DIRECT-KabloCast", "TestPass99")
    assert qr.startswith("data:image/svg+xml;charset=utf-8,")
    assert "<svg" in unquote(qr)

    guide = build_manual_ip_guide("192.168.137.1")
    assert guide["iphone_ip"] == "192.168.137.55"
    assert "BOŞ" in guide["router"]

    ble = build_airplay_ble_payload("192.168.137.1", 7000)
    assert len(ble) == 10
    assert ble[0] == 0x09

    pid, serial = validate_apple_instance_id(r"USB\VID_05AC&PID_12A8\00008140001A2B3C")
    assert pid == "12A8"
    assert serial == "00008140001A2B3C"
    with pytest.raises(ValueError):
        validate_apple_instance_id(r"USB\VID_1234&PID_9999\BAD")

    assert classify_driver_mode("usbccgp") == "apple_usbccgp"
    assert classify_driver_mode("libusb0") == "libusb_win32"
    assert classify_driver_mode("WinUSB") == "winusb"


def test_uxplay_manager_log_parser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    qsync_calls: list[bool] = []
    monkeypatch.setattr(
        UxPlayManager,
        "_sync_uxplay_qsettings",
        staticmethod(lambda fullscreen=True: qsync_calls.append(fullscreen)),
    )
    mgr = UxPlayManager(tmp_path)
    args_file = mgr.write_arguments("KabloCast", resolution_preset="1080p", audio_enabled=True)
    assert args_file.parent.name == "uxplay-windows"
    assert args_file.parent.parent.name == "leapbtw"
    args_text = args_file.read_text(encoding="utf-8")
    assert qsync_calls == [True]
    assert "-n KabloCast" in args_text
    assert "-as wasapi2sink" in args_text
    assert "-as wasapisink" not in args_text
    assert "-vd d3d11h264dec" in args_text
    assert "-vc d3d11convert" in args_text
    assert "-vs d3d11videosink" in args_text
    assert "-fps 60" in args_text
    assert "-reset 0" in args_text
    assert "-nofreeze" in args_text
    assert "-nohold" in args_text
    assert "-vsync no" in args_text
    assert "-fs" in args_text
    assert "-s 1920x1080@60" in args_text
    assert "-vol 1.0" in args_text
    assert "-al 0.070" in args_text

    zero_sync_args = mgr.write_arguments(
        "KabloCast",
        resolution_preset="1440p",
        audio_enabled=True,
        audio_sync_ms=0,
        fullscreen=False,
    ).read_text(encoding="utf-8")
    assert "-s 2560x1440@60" in zero_sync_args
    assert "-vsync no" in zero_sync_args
    assert "-al 0.250" in zero_sync_args
    assert "-fs" not in zero_sync_args

    neg_sync_args = mgr.write_arguments(
        "KabloCast", resolution_preset="1080p", audio_enabled=True, audio_sync_ms=-120
    ).read_text(encoding="utf-8")
    assert "-vsync no" in neg_sync_args
    assert "-al 0.370" in neg_sync_args

    spaced_args = mgr.write_arguments(
        'Living "Room\n', resolution_preset="1080p", audio_enabled=True
    ).read_text(encoding="utf-8")
    assert '-n "Living Room"' in spaced_args

    muted_path = mgr.write_arguments(
        "KabloCast", resolution_preset="native", audio_enabled=False
    )
    muted_args = muted_path.read_text(encoding="utf-8")
    assert "-as 0" in muted_args
    assert "-s " not in muted_args

    mgr._parse_log_line("raop_rtp_mirror starting connection from iPhone")
    mgr._parse_log_line("Video format: HEVC 1179x2556 @ 60 fps")
    assert mgr.state.client_connected is True
    assert mgr.state.codec == "HEVC (H.265)"
    assert mgr.state.resolution == "1179x2556"
    assert mgr.state.fps == 60.0


def test_quota_shield_rules_never_block_unscoped_svchost() -> None:
    from app.network.quota_shield import build_shield_rules_script

    script = build_shield_rules_script()
    assert "-Service 'wuauserv'" in script
    assert "-Service 'BITS'" in script
    assert "-Service 'DoSvc'" in script
    assert "-Program '%SystemRoot%\\System32\\svchost.exe' -Profile" not in script

    with pytest.raises(ValueError, match="-Service"):
        build_shield_rules_script([("bad", "Bad", r"%SystemRoot%\System32\svchost.exe", None)])


def test_quota_shield_adapter_heuristics_and_rate_calculation() -> None:
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.network.quota_shield import QuotaShieldManager

    mgr = QuotaShieldManager()
    t0 = 1000.0
    t1 = 1001.0

    sample1_io = {
        "Loopback Pseudo-Interface 1": SimpleNamespace(bytes_recv=1000, bytes_sent=1000),
        "Wi-Fi": SimpleNamespace(bytes_recv=200_000, bytes_sent=100_000),
        "Ethernet 2": SimpleNamespace(bytes_recv=50_000, bytes_sent=20_000),
        "Apple Mobile Device Ethernet": SimpleNamespace(bytes_recv=10_000, bytes_sent=5_000),
    }

    sample2_io = {
        "Loopback Pseudo-Interface 1": SimpleNamespace(bytes_recv=2000, bytes_sent=2000),
        "Wi-Fi": SimpleNamespace(bytes_recv=300_000, bytes_sent=150_000),
        "Ethernet 2": SimpleNamespace(bytes_recv=50_000, bytes_sent=20_000),
        "Apple Mobile Device Ethernet": SimpleNamespace(bytes_recv=35_000, bytes_sent=17_500),
    }

    stats = {
        "Loopback Pseudo-Interface 1": SimpleNamespace(isup=True),
        "Wi-Fi": SimpleNamespace(isup=True),
        "Ethernet 2": SimpleNamespace(isup=False),
        "Apple Mobile Device Ethernet": SimpleNamespace(isup=True),
    }

    addrs = {
        "Wi-Fi": [
            SimpleNamespace(family=SimpleNamespace(name="AF_INET"), address="192.168.1.50")
        ],
        "Ethernet 2": [
            SimpleNamespace(family=SimpleNamespace(name="AF_INET"), address="172.20.10.4")
        ],
        "Apple Mobile Device Ethernet": [
            SimpleNamespace(family=SimpleNamespace(name="AF_INET"), address="172.20.10.2")
        ],
    }

    with (
        patch("time.monotonic", return_value=t0),
        patch("psutil.net_io_counters", return_value=sample1_io),
        patch("psutil.net_if_stats", return_value=stats),
        patch("psutil.net_if_addrs", return_value=addrs),
    ):
        res1 = mgr.sample_adapters()
        names1 = [a.name for a in res1]
        assert "Loopback Pseudo-Interface 1" not in names1
        assert "Wi-Fi" in names1
        assert "Ethernet 2" in names1
        assert "Apple Mobile Device Ethernet" in names1

        wifi1 = next(a for a in res1 if a.name == "Wi-Fi")
        assert wifi1.rx_kbps == 0.0
        assert wifi1.tx_kbps == 0.0
        assert wifi1.looks_like_hotspot is True

        eth2_1 = next(a for a in res1 if a.name == "Ethernet 2")
        assert eth2_1.looks_like_hotspot is True
        assert eth2_1.is_up is False

        apple1 = next(a for a in res1 if a.name == "Apple Mobile Device Ethernet")
        assert apple1.looks_like_hotspot is True

    with (
        patch("time.monotonic", return_value=t1),
        patch("psutil.net_io_counters", return_value=sample2_io),
        patch("psutil.net_if_stats", return_value=stats),
        patch("psutil.net_if_addrs", return_value=addrs),
    ):
        res2 = mgr.sample_adapters()
        wifi2 = next(a for a in res2 if a.name == "Wi-Fi")
        assert wifi2.rx_kbps == pytest.approx(800.0, rel=1e-2)
        assert wifi2.tx_kbps == pytest.approx(400.0, rel=1e-2)

        apple2 = next(a for a in res2 if a.name == "Apple Mobile Device Ethernet")
        assert apple2.rx_kbps == pytest.approx(200.0, rel=1e-2)
        assert apple2.tx_kbps == pytest.approx(100.0, rel=1e-2)

        eth2_2 = next(a for a in res2 if a.name == "Ethernet 2")
        assert eth2_2.rx_kbps == 0.0
        assert eth2_2.tx_kbps == 0.0


def test_win_uac_encoding_and_error_translation() -> None:
    import base64
    from subprocess import CompletedProcess
    from unittest.mock import patch

    from app.win_uac import encode_powershell_command, run_elevated_powershell

    b64 = encode_powershell_command("Write-Output 'Merhaba'")
    assert base64.b64decode(b64).decode("utf-16-le") == "Write-Output 'Merhaba'"

    fake_err = CompletedProcess(
        args=["powershell"],
        returncode=1,
        stdout="",
        stderr="Start-Process : This command cannot be run due to the error: İstek desteklenmiyor.",
    )
    with (
        patch("app.win_uac.sys.platform", "win32"),
        patch("app.win_uac.is_admin", return_value=False),
        patch("app.win_uac.subprocess.run", return_value=fake_err),
    ):
        ok, msg = run_elevated_powershell("Get-Date")
        assert ok is False
        assert "KabloCast.bat" in msg


def test_wifi_direct_rejects_control_chars_and_escapes_quotes() -> None:
    from unittest.mock import MagicMock, patch

    from app.network.wifi_direct import WifiDirectManager

    mgr = WifiDirectManager()
    with pytest.raises(ValueError):
        mgr.start(ssid="DIRECT-Bad\nName")
    with pytest.raises(ValueError):
        mgr.start(ssid="DIRECT-OkName", passphrase="pass\rword12")

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    fake_proc.stdout.readline.return_value = "STATUS:Started\n"
    with patch("app.network.wifi_direct.subprocess.Popen", return_value=fake_proc) as mock_popen:
        mgr.start(ssid="DIRECT-O'Brien", passphrase="sec'ret99")
        cmd_arg = mock_popen.call_args.args[0][-1]
        assert "Ssid = 'DIRECT-O''Brien'" in cmd_arg
        assert "Password = 'sec''ret99'" in cmd_arg
        mgr.stop()
