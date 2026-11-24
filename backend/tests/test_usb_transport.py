"""Unit tests for USB transport, libusb backend loader, and Valeria endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.usb.usb_transport import (
    APPLE_VID,
    QT_INTERFACE_CLASS,
    QT_INTERFACE_SUBCLASS,
    READ_BUFFER_SIZE,
    QuickTimeUsbStreamer,
    UsbStreamEndpointInfo,
    _clean_usb_str,
    _is_usb_timeout,
    _load_libusb_backend,
    find_qt_endpoints,
)


def test_constants_and_buffer_size() -> None:
    assert READ_BUFFER_SIZE == 1024 * 1024  # 1 MB for 1080p60 IDR frame integrity
    assert APPLE_VID == 0x05AC
    assert QT_INTERFACE_CLASS == 0xFF
    assert QT_INTERFACE_SUBCLASS == 0x2A


def test_find_qt_endpoints_matches_interface_2() -> None:
    # Build a mock USB device with Valeria configuration
    mock_ep_in = MagicMock()
    mock_ep_in.bEndpointAddress = 0x86

    mock_ep_out = MagicMock()
    mock_ep_out.bEndpointAddress = 0x05

    mock_intf = MagicMock()
    mock_intf.bInterfaceNumber = 2
    mock_intf.bInterfaceClass = QT_INTERFACE_CLASS
    mock_intf.bInterfaceSubClass = QT_INTERFACE_SUBCLASS
    mock_intf.__iter__.return_value = [mock_ep_in, mock_ep_out]

    mock_cfg = MagicMock()
    mock_cfg.bConfigurationValue = 5
    mock_cfg.__iter__.return_value = [mock_intf]

    mock_dev = MagicMock()
    mock_dev.__iter__.return_value = [mock_cfg]

    info = find_qt_endpoints(mock_dev)
    assert info is not None
    assert isinstance(info, UsbStreamEndpointInfo)
    assert info.config_value == 5
    assert info.interface_number == 2
    assert info.ep_in == 0x86
    assert info.ep_out == 0x05


def test_load_libusb_backend_fallback_to_libusb0_when_libusb1_empty() -> None:
    mock_b1 = MagicMock()
    mock_b0 = MagicMock()

    def _mock_find(find_all=True, backend=None, **_kwargs):
        return [] if backend == mock_b1 else [MagicMock()]

    with (
        patch("app.usb.usb_transport._has_libusb0_apple_driver", return_value=False),
        patch("usb.backend.libusb1.get_backend", return_value=mock_b1),
        patch("usb.backend.libusb0.get_backend", return_value=mock_b0),
        patch("usb.core.find", side_effect=_mock_find),
    ):
        chosen = _load_libusb_backend()
        assert chosen == mock_b0


def test_load_libusb_backend_uses_libusb1_when_devices_found() -> None:
    mock_b1 = MagicMock()
    mock_b0 = MagicMock()

    with (
        patch("app.usb.usb_transport._has_libusb0_apple_driver", return_value=False),
        patch("usb.backend.libusb1.get_backend", return_value=mock_b1),
        patch("usb.backend.libusb0.get_backend", return_value=mock_b0),
        patch("usb.core.find", return_value=[MagicMock()]),
    ):
        chosen = _load_libusb_backend()
        assert chosen == mock_b1


def test_load_libusb_backend_prefers_libusb0_when_libusb0_driver_active() -> None:
    mock_b1 = MagicMock()
    mock_b0 = MagicMock()

    with (
        patch("app.usb.usb_transport._has_libusb0_apple_driver", return_value=True),
        patch("usb.backend.libusb1.get_backend", return_value=mock_b1),
        patch("usb.backend.libusb0.get_backend", return_value=mock_b0),
        patch("usb.core.find", return_value=[MagicMock()]),
    ):
        chosen = _load_libusb_backend()
        assert chosen == mock_b0


def test_clean_usb_str_and_libusb0_timeout_detection() -> None:
    assert _clean_usb_str("000081100011223344556677\x00\x00\x00") == "000081100011223344556677"
    assert _is_usb_timeout(RuntimeError("libusb0-dll:err [_usb_reap_async] timeout error"))
    assert _is_usb_timeout(RuntimeError("Operation timed out (10060)"))
    assert not _is_usb_timeout(RuntimeError("LIBUSB_ERROR_NO_DEVICE"))


def test_activate_qt_config_sends_0x40_even_when_config5_descriptor_exists() -> None:
    mock_ep_in = MagicMock()
    mock_ep_in.bEndpointAddress = 0x86
    mock_ep_out = MagicMock()
    mock_ep_out.bEndpointAddress = 0x05
    mock_intf = MagicMock()
    mock_intf.bInterfaceNumber = 2
    mock_intf.bInterfaceClass = QT_INTERFACE_CLASS
    mock_intf.bInterfaceSubClass = QT_INTERFACE_SUBCLASS
    mock_intf.__iter__.return_value = [mock_ep_in, mock_ep_out]
    mock_cfg = MagicMock()
    mock_cfg.bConfigurationValue = 5
    mock_cfg.__iter__.return_value = [mock_intf]

    mode_state = {"mode": [3, 3, 3, 0]}

    def fake_ctrl(bm_req, b_req, w_val, w_idx, data_or_len, timeout=1000):
        if bm_req == 0xC0 and b_req == 0x45:
            return list(mode_state["mode"])
        if bm_req == 0x40 and b_req == 0x52 and w_idx == 2:
            mode_state["mode"] = [5, 3, 3, 0]
            return 0
        return b""

    mock_dev = MagicMock()
    mock_dev.serial_number = "000081100011223344556677\x00\x00"
    mock_dev.__iter__.return_value = [mock_cfg]
    mock_dev.ctrl_transfer.side_effect = fake_ctrl

    streamer = QuickTimeUsbStreamer(
        on_video=lambda *args: None,
        on_audio=lambda *args: None,
        on_error=lambda _err: None,
        serial="000081100011223344556677",
    )

    with patch("usb.core.find", return_value=[mock_dev]):
        selected, _ = streamer._select_device()
        activated = streamer._activate_qt_config(selected, MagicMock())
        assert activated is mock_dev
        assert mode_state["mode"][0] == 5
        mock_dev.ctrl_transfer.assert_any_call(0x40, 0x52, 0x0000, 0x0002, b"", timeout=1500)


def test_find_qt_endpoints_returns_none_for_standard_composite_device() -> None:
    # 1. Device with standard Still Image / PTP interface (class 6, subclass 1)
    mock_ep_in = MagicMock()
    mock_ep_in.bEndpointAddress = 0x81
    mock_ep_out = MagicMock()
    mock_ep_out.bEndpointAddress = 0x02

    mock_ptp_intf = MagicMock()
    mock_ptp_intf.bInterfaceNumber = 0
    mock_ptp_intf.bInterfaceClass = 6
    mock_ptp_intf.bInterfaceSubClass = 1
    mock_ptp_intf.__iter__.return_value = [mock_ep_in, mock_ep_out]

    mock_cfg = MagicMock()
    mock_cfg.bConfigurationValue = 1
    mock_cfg.__iter__.return_value = [mock_ptp_intf]

    mock_dev = MagicMock()
    mock_dev.__iter__.return_value = [mock_cfg]

    assert find_qt_endpoints(mock_dev) is None

    # 2. Device with class 0xFF but mismatched subclass (0x00 != 0x2A)
    mock_vendor_intf = MagicMock()
    mock_vendor_intf.bInterfaceNumber = 1
    mock_vendor_intf.bInterfaceClass = 0xFF
    mock_vendor_intf.bInterfaceSubClass = 0x00
    mock_vendor_intf.__iter__.return_value = [mock_ep_in, mock_ep_out]
    mock_cfg.__iter__.return_value = [mock_vendor_intf]

    assert find_qt_endpoints(mock_dev) is None

    # 3. QuickTime class/subclass matching but missing IN endpoint
    mock_missing_ep_intf = MagicMock()
    mock_missing_ep_intf.bInterfaceNumber = 2
    mock_missing_ep_intf.bInterfaceClass = QT_INTERFACE_CLASS
    mock_missing_ep_intf.bInterfaceSubClass = QT_INTERFACE_SUBCLASS
    mock_missing_ep_intf.__iter__.return_value = [mock_ep_out]
    mock_cfg.__iter__.return_value = [mock_missing_ep_intf]

    assert find_qt_endpoints(mock_dev) is None
