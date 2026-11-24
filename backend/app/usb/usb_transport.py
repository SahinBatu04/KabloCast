"""USB QuickTime AV transport over libusb-1.0 / PyUSB for iPhone 13 and 16 Pro Max."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from .qvh_protocol import PacketFramingBuffer, QvhSessionProcessor, build_ping_packet

logger = logging.getLogger(__name__)

APPLE_VID = 0x05AC
QT_INTERFACE_CLASS = 0xFF
QT_INTERFACE_SUBCLASS = 0x2A
USBMUX_SUBCLASS = 0xFE
READ_BUFFER_SIZE = 1024 * 1024  # 1 MB to prevent 1080p60 IDR keyframe truncation

# Common Apple iPhone USB Product IDs (Lightning & USB-C generations)
APPLE_PID_HINTS: dict[int, str] = {
    0x12A8: "iPhone (Normal USB / Lightning veya USB-C)",
    0x12AB: "iPad / USB-C Apple Cihazı",
    0x1290: "iPhone (Legacy)",
}


@dataclass(slots=True)
class UsbStreamEndpointInfo:
    """Resolved QuickTime USB endpoints."""

    config_value: int
    interface_number: int
    ep_in: int
    ep_out: int


def _has_libusb0_apple_driver() -> bool:
    """Return True on Windows when an active Apple USB device is bound to libusb0.sys."""
    if sys.platform != "win32":
        return False
    with contextlib.suppress(Exception):
        import winreg

        enum_key = r"SYSTEM\CurrentControlSet\Services\libusb0\Enum"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, enum_key) as key:
            count, _ = winreg.QueryValueEx(key, "Count")
            for idx in range(int(count)):
                inst, _ = winreg.QueryValueEx(key, str(idx))
                if "VID_05AC" in str(inst).upper():
                    return True
    return False


def _load_libusb_backend():
    """Return a PyUSB backend: native libusb0 for libusb0.sys devices, else libusb-1.0."""
    import usb.backend.libusb0 as libusb0  # type: ignore[import-untyped]
    import usb.backend.libusb1 as libusb1  # type: ignore[import-untyped]
    import usb.core  # type: ignore[import-untyped]

    backend0 = None
    with contextlib.suppress(Exception):
        backend0 = libusb0.get_backend()

    if backend0 is not None and _has_libusb0_apple_driver():
        with contextlib.suppress(Exception):
            apple_devs = list(
                usb.core.find(find_all=True, idVendor=APPLE_VID, backend=backend0) or []
            )
            if len(apple_devs) > 0:
                return backend0

    backend1 = None
    try:
        import libusb  # type: ignore[import-untyped]

        dll_path = getattr(libusb, "__file__", None)
        if dll_path:
            from pathlib import Path

            pkg_dir = Path(dll_path).resolve().parent
            candidates = list(pkg_dir.rglob("libusb-1.0.dll"))
            if candidates:
                # Prefer 64-bit DLL on Windows x64
                x64 = [c for c in candidates if "64" in str(c) and "arm" not in str(c).lower()]
                chosen = str(x64[0] if x64 else candidates[0])
                backend1 = libusb1.get_backend(find_library=lambda _name: chosen)
        if backend1 is None:
            backend1 = libusb1.get_backend()
    except Exception as exc:
        logger.debug("libusb1 backend load failed: %s", exc)
        backend1 = None

    if backend1 is not None:
        try:
            # Check if libusb1 can actually find any devices
            devices = list(usb.core.find(find_all=True, backend=backend1) or [])
            if len(devices) > 0:
                return backend1
        except Exception as exc:
            logger.debug("libusb1 device enumeration failed: %s", exc)

    # Fallback to libusb0 (libusb-win32 on Windows) if libusb1 returned None or found 0 devices
    if backend0 is not None:
        return backend0

    return backend1


def find_qt_endpoints(dev: object) -> UsbStreamEndpointInfo | None:
    """Scan USB configurations for QuickTime AV interface (0xFF / 0x2A)."""
    for cfg in dev:  # type: ignore[attr-defined]
        for intf in cfg:
            if (
                intf.bInterfaceClass == QT_INTERFACE_CLASS
                and intf.bInterfaceSubClass == QT_INTERFACE_SUBCLASS
            ):
                ep_in = None
                ep_out = None
                for ep in intf:
                    if (ep.bEndpointAddress & 0x80) != 0:
                        ep_in = ep.bEndpointAddress
                    else:
                        ep_out = ep.bEndpointAddress
                if ep_in is not None and ep_out is not None:
                    return UsbStreamEndpointInfo(
                        config_value=cfg.bConfigurationValue,
                        interface_number=intf.bInterfaceNumber,
                        ep_in=ep_in,
                        ep_out=ep_out,
                    )
    return None


def _clean_usb_str(value: object) -> str:
    """Strip libusb0 NUL padding and whitespace from USB descriptor strings."""
    if not isinstance(value, str):
        return ""
    return value.replace("\x00", "").strip()


def _read_qt_mode(dev: object) -> tuple[int, ...] | None:
    """Read Apple vendor mode (request 0x45); byte 0 == 5 indicates Valeria is active."""
    with contextlib.suppress(Exception):
        raw = dev.ctrl_transfer(0xC0, 0x45, 0x0000, 0x0000, 4, timeout=1000)  # type: ignore[attr-defined]
        mode = tuple(int(b) for b in raw)
        if mode:
            return mode
    return None


def _is_usb_timeout(exc: Exception) -> bool:
    """Return True for libusb1, libusb0 ('timeout error'), and WinUSB (10060) timeouts."""
    msg = str(exc).lower()
    errno = getattr(exc, "errno", None)
    return errno in (110, 10060) or "timeout" in msg or "timed out" in msg or "10060" in msg


def probe_usb_devices() -> list[dict[str, str | int | bool]]:
    """Probe raw USB devices visible to libusb-1.0 (requires WinUSB/libusb driver)."""
    import usb.core  # type: ignore[import-untyped]

    backend = _load_libusb_backend()
    devices = usb.core.find(find_all=True, idVendor=APPLE_VID, backend=backend) or []
    results: list[dict[str, str | int | bool]] = []
    for dev in devices:
        qt_info = find_qt_endpoints(dev)
        mode = _read_qt_mode(dev)
        qt_active = qt_info is not None and (mode is None or mode[0] == 5)
        serial = ""
        product = ""
        with contextlib.suppress(Exception):
            serial = _clean_usb_str(dev.serial_number)
        with contextlib.suppress(Exception):
            product = _clean_usb_str(dev.product)
        results.append(
            {
                "vendor_id": f"0x{dev.idVendor:04X}",
                "product_id": f"0x{dev.idProduct:04X}",
                "serial": serial,
                "product": product or APPLE_PID_HINTS.get(dev.idProduct, "Apple iPhone"),
                "qt_config_active": qt_active,
            }
        )
    return results


class QuickTimeUsbStreamer:
    """Connects to an iPhone over USB (WinUSB/libusb) and streams H.264 + LPCM."""

    def __init__(
        self,
        on_video: Callable[[bytes, bool, int, bytes, bytes, int, int], None],
        on_audio: Callable[[bytes, int], None],
        on_error: Callable[[str], None],
        serial: str | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self._on_video = on_video
        self._on_audio = on_audio
        self._on_error = on_error
        self._serial = serial
        self._on_status = on_status
        self._stop_requested = False
        self._task: asyncio.Task[None] | None = None

    def request_stop(self) -> None:
        self._stop_requested = True

    async def start(self) -> None:
        self._stop_requested = False
        self._task = asyncio.create_task(asyncio.to_thread(self._run_blocking))
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    def _select_device(self):
        import usb.core  # type: ignore[import-untyped]

        backend = _load_libusb_backend()
        if backend is None:
            raise RuntimeError("libusb-1.0 sürücü kütüphanesi yüklenemedi.")
        devices = list(usb.core.find(find_all=True, idVendor=APPLE_VID, backend=backend) or [])
        if not devices:
            raise RuntimeError(
                "libusb üzerinden Apple iPhone bulunamadı. Kabloyu kontrol edin veya "
                "'USB Sürücü Asistanı' ile WinUSB/libusb bağlantısını doğrulayın."
            )
        if self._serial:
            want_serial = _clean_usb_str(self._serial).upper()
            for dev in devices:
                with contextlib.suppress(Exception):
                    if _clean_usb_str(dev.serial_number).upper() == want_serial:
                        return dev, backend
        return devices[0], backend

    def _activate_qt_config(self, dev: object, backend: object):
        import usb.core  # type: ignore[import-untyped]

        mode = _read_qt_mode(dev)
        if find_qt_endpoints(dev) is not None and mode is not None and mode[0] == 5:
            return dev

        # Vendor request 0x40 bRequest=0x52 (wIndex=2) activates QuickTime/Valeria mode;
        # always send 0x40 first because 0xC0 can return [0] without switching GET_MODE to 5.
        try:
            dev.ctrl_transfer(0x40, 0x52, 0x0000, 0x0002, b"", timeout=1500)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.debug("ctrl_transfer 0x40 bRequest 0x52 notice: %s, trying 0xC0", exc)
            with contextlib.suppress(Exception):
                dev.ctrl_transfer(0xC0, 0x52, 0x0000, 0x0002, 1, timeout=1500)  # type: ignore[attr-defined]

        def _is_qt_ready(candidate: object) -> bool:
            if find_qt_endpoints(candidate) is None:
                return False
            cand_mode = _read_qt_mode(candidate)
            if mode is not None:
                return cand_mode is not None and cand_mode[0] == 5
            return cand_mode is None or cand_mode[0] == 5

        if _is_qt_ready(dev):
            return dev

        # Wait for iPhone USB mode switch / re-enumeration with QuickTime configuration
        want_serial = _clean_usb_str(self._serial).upper() if self._serial else ""
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and not self._stop_requested:
            time.sleep(0.4)
            if _is_qt_ready(dev):
                return dev
            candidates = list(
                usb.core.find(find_all=True, idVendor=APPLE_VID, backend=backend) or []
            )
            for cand in candidates:
                if want_serial:
                    cand_sn = ""
                    with contextlib.suppress(Exception):
                        cand_sn = _clean_usb_str(cand.serial_number).upper()
                    if cand_sn and cand_sn != want_serial:
                        continue
                if _is_qt_ready(cand):
                    return cand

        if _is_qt_ready(dev):
            return dev

        raise RuntimeError(
            "iPhone QuickTime USB modu (0xFF/0x2A) aktifleşmedi. "
            "Telefon kilidini açıp 'Bu Bilgisayara Güven' onayını verin."
        )

    def _run_blocking(self) -> None:
        import usb.util  # type: ignore[import-untyped]

        dev = None
        claimed_intf: int | None = None
        processor: QvhSessionProcessor | None = None
        received_any = False
        kickstarted = False
        try:
            dev, backend = self._select_device()
            dev = self._activate_qt_config(dev, backend)
            qt_info = find_qt_endpoints(dev)
            if qt_info is None:
                raise RuntimeError("QuickTime USB endpoint çifti bulunamadı.")

            config_value = qt_info.config_value or 5
            dev.set_configuration(config_value)

            usb.util.claim_interface(dev, qt_info.interface_number)
            claimed_intf = qt_info.interface_number

            with contextlib.suppress(Exception):
                dev.set_interface_altsetting(
                    interface=qt_info.interface_number, alternate_setting=0
                )

            # Clear endpoint halts after claiming interface 2, falling back to control request
            for ep in (qt_info.ep_in, qt_info.ep_out):
                try:
                    dev.clear_halt(ep)
                except Exception as exc:
                    logger.debug("dev.clear_halt(0x%02x) notice: %s, trying CLEAR_FEATURE", ep, exc)
                    with contextlib.suppress(Exception):
                        dev.ctrl_transfer(0x02, 0x01, 0x0000, ep, b"", timeout=1000)

            def write_usb(payload: bytes) -> None:
                dev.write(qt_info.ep_out, payload, timeout=2000)

            processor = QvhSessionProcessor(
                write_cb=write_usb,
                on_video=self._on_video,
                on_audio=self._on_audio,
            )
            framer = PacketFramingBuffer()
            timeout_count = 0

            while not self._stop_requested:
                try:
                    raw = bytes(dev.read(qt_info.ep_in, READ_BUFFER_SIZE, timeout=1000))
                except Exception as exc:
                    if _is_usb_timeout(exc):
                        timeout_count += 1
                        if not received_any and not kickstarted:
                            kickstarted = True
                            with contextlib.suppress(Exception):
                                dev.ctrl_transfer(0x40, 0x40, 0x6400, 0x6400, b"", timeout=500)
                            with contextlib.suppress(Exception):
                                dev.write(qt_info.ep_out, build_ping_packet(), timeout=500)
                        if (
                            not received_any
                            and timeout_count == 5
                            and self._on_status is not None
                        ):
                            self._on_status(
                                "iPhone QuickTime USB akışı yanıt vermedi (0 B). Ekran kilidiniz "
                                "açıksa, iOS 18/26/27+ sürümlerinde Apple doğrudan USB Valeria "
                                "akışını kısıtlamış olabilir; kesintisiz sıfır kotalı yansıtma "
                                "için 'Apple'a Dön' + 'AirPlay 2' sekmesini kullanın."
                            )
                        if processor is not None:
                            processor.pace_need(force=True)
                        continue
                    raise
                if not raw:
                    continue
                received_any = True
                for frame in framer.feed(raw):
                    processor.handle_frame(frame)

        except Exception as exc:
            if not self._stop_requested:
                self._on_error(str(exc))
        finally:
            if processor is not None and received_any:
                with contextlib.suppress(Exception):
                    processor.close_session()
            if dev is not None:
                intf_to_release = claimed_intf if claimed_intf is not None else 2
                with contextlib.suppress(Exception):
                    usb.util.release_interface(dev, intf_to_release)
                with contextlib.suppress(Exception):
                    dev.ctrl_transfer(0x40, 0x52, 0x0000, 0x0000, b"", timeout=1000)
                with contextlib.suppress(Exception):
                    usb.util.dispose_resources(dev)
