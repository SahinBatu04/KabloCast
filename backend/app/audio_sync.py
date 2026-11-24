"""Automatic Windows audio output detection and persistent A/V sync calibration."""

from __future__ import annotations

import contextlib
import ctypes
import sys
import uuid
from ctypes import wintypes

from .db import Database
from .models import AudioOutputKind, AudioSyncStatus, AudioSyncUpdateRequest, ResolvedStrategy

_SYNC_BASE_MS: dict[AudioOutputKind, int] = {
    "speaker": 180,
    "wired_headphones": 175,
    "hdmi_monitor": 155,
    "wireless_headset": 140,
    "bluetooth": 10,
}

_KIND_LABELS: dict[AudioOutputKind, str] = {
    "speaker": "Dahili Hoparlör",
    "wired_headphones": "Kablolu Kulaklık",
    "hdmi_monitor": "HDMI / Monitör Sesi",
    "wireless_headset": "Kablosuz Kulaklık",
    "bluetooth": "Bluetooth Ses",
}

_BLUETOOTH_TOKENS = (
    "bluetooth",
    "bth",
    "airpods",
    "buds",
    "a2dp",
    "hands-free",
    "wh-1000",
    "wf-1000",
)

_HDMI_TOKENS = (
    "nvidia",
    "amd high definition",
    "intel(r) display",
    "hdmi",
    "displayport",
)

_WIRELESS_HEADSET_TOKENS = (
    "wireless",
    "2.4",
    "dongle",
    "h2002",
    "g733",
    "arctis",
    "hyperx",
    "razer",
)

_HEADPHONE_WORDS = ("kulaklık", "headphone", "headset")


class _COMGUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_str(cls, raw: str) -> _COMGUID:
        return cls.from_buffer_copy(uuid.UUID(raw).bytes_le)


def detect_default_audio_output() -> tuple[str, str, str]:
    """Return (endpoint_id, desc, iface) for the default Windows multimedia render endpoint."""
    fallback = ("default_speaker", "Sistem Hoparlörü", "WASAPI")
    if sys.platform != "win32":
        return fallback

    try:
        import winreg

        ole32 = ctypes.WinDLL("ole32")
        ole32.CoInitializeEx.restype = ctypes.c_long
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        ole32.CoCreateInstance.restype = ctypes.c_long
        ole32.CoCreateInstance.argtypes = [
            ctypes.POINTER(_COMGUID),
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_COMGUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

        hr_init = int(ole32.CoInitializeEx(None, 0))
        rpc_e_changed_mode = -2147417850  # 0x80010106
        should_uninit = hr_init in (0, 1)
        if hr_init < 0 and hr_init != rpc_e_changed_mode:
            return fallback

        enum_ptr = ctypes.c_void_p()
        dev_ptr = ctypes.c_void_p()
        try:
            clsid_enum = _COMGUID.from_str("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
            iid_enum = _COMGUID.from_str("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
            hr = int(
                ole32.CoCreateInstance(
                    ctypes.byref(clsid_enum),
                    None,
                    1,
                    ctypes.byref(iid_enum),
                    ctypes.byref(enum_ptr),
                )
            )
            if hr != 0 or not enum_ptr.value:
                return fallback

            enum_vtbl = ctypes.cast(
                ctypes.cast(enum_ptr, ctypes.POINTER(ctypes.c_void_p))[0],
                ctypes.POINTER(ctypes.c_void_p),
            )
            get_default = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_void_p),
            )(enum_vtbl[4])
            # eRender = 0, eMultimedia = 1
            if int(get_default(enum_ptr, 0, 1, ctypes.byref(dev_ptr))) != 0 or not dev_ptr.value:
                return fallback

            dev_vtbl = ctypes.cast(
                ctypes.cast(dev_ptr, ctypes.POINTER(ctypes.c_void_p))[0],
                ctypes.POINTER(ctypes.c_void_p),
            )
            get_id = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.LPWSTR),
            )(dev_vtbl[5])
            pwstr = wintypes.LPWSTR()
            if int(get_id(dev_ptr, ctypes.byref(pwstr))) != 0 or not pwstr.value:
                return fallback

            endpoint_id = str(pwstr.value)
            ole32.CoTaskMemFree(pwstr)

            guid_part = endpoint_id.split("}.")[-1] if "}." in endpoint_id else endpoint_id
            desc = "Sistem Hoparlörü"
            iface = "WASAPI"
            reg_path = (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
                rf"\{guid_part}\Properties"
            )
            with (
                contextlib.suppress(OSError),
                winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path) as pk,
            ):
                with contextlib.suppress(OSError):
                    val = winreg.QueryValueEx(pk, "{a45c254e-df1c-4efd-8020-67d146a850e0},2")[0]
                    if val:
                        desc = str(val).strip()
                with contextlib.suppress(OSError):
                    val = winreg.QueryValueEx(pk, "{b3f8fa53-0004-438e-9003-51a46e139bfc},6")[0]
                    if val:
                        iface = str(val).strip()

            return (endpoint_id, desc, iface)
        finally:
            if dev_ptr.value:
                with contextlib.suppress(Exception):
                    dev_vtbl = ctypes.cast(
                        ctypes.cast(dev_ptr, ctypes.POINTER(ctypes.c_void_p))[0],
                        ctypes.POINTER(ctypes.c_void_p),
                    )
                    ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(dev_vtbl[2])(dev_ptr)
            if enum_ptr.value:
                with contextlib.suppress(Exception):
                    enum_vtbl = ctypes.cast(
                        ctypes.cast(enum_ptr, ctypes.POINTER(ctypes.c_void_p))[0],
                        ctypes.POINTER(ctypes.c_void_p),
                    )
                    ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(enum_vtbl[2])(enum_ptr)
            if should_uninit:
                with contextlib.suppress(Exception):
                    ole32.CoUninitialize()
    except Exception:
        return fallback


def classify_audio_output(desc: str, iface: str) -> AudioOutputKind:
    """Classify Windows audio render device into a latency profile category."""
    text = f"{desc} {iface}".lower()
    iface_lower = iface.lower()

    if any(tok in text for tok in _BLUETOOTH_TOKENS):
        return "bluetooth"
    if any(tok in text for tok in _HDMI_TOKENS):
        return "hdmi_monitor"

    is_headphone = any(word in text for word in _HEADPHONE_WORDS)
    if any(tok in text for tok in _WIRELESS_HEADSET_TOKENS) or (
        is_headphone and "realtek" not in iface_lower
    ):
        return "wireless_headset"
    if is_headphone and "realtek" in iface_lower:
        return "wired_headphones"
    return "speaker"


def compute_recommended_sync_ms(
    kind: AudioOutputKind,
    strategy: ResolvedStrategy = "lan_wifi",
    resolution_preset: str = "1080p",
) -> int:
    """Compute optimal UxPlay -vsync offset (ms) for active audio hardware, link, and resolution."""
    base = _SYNC_BASE_MS.get(kind, 180)
    if strategy == "wifi_direct":
        base += 15
    elif strategy == "usb_zero_quota":
        base -= 10
    if resolution_preset == "1440p":
        base += 15
    return max(-400, min(600, base))


def _format_output_label(desc: str, iface: str) -> str:
    clean_desc = (desc or "Sistem Hoparlörü").strip()
    clean_iface = (iface or "").strip()
    if (
        clean_iface
        and clean_iface.lower() not in clean_desc.lower()
        and clean_iface.upper() != "WASAPI"
    ):
        return f"{clean_desc} ({clean_iface})"
    return clean_desc


def _format_ms(ms: int) -> str:
    return f"+{ms} ms" if ms > 0 else f"{ms} ms"


class AudioSyncManager:
    """Resolves automatic A/V sync values and remembers manual per-device/output overrides."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def resolve_status(
        self,
        device_key: str,
        strategy: ResolvedStrategy = "lan_wifi",
        resolution_preset: str = "1080p",
    ) -> AudioSyncStatus:
        endpoint_id, desc, iface = detect_default_audio_output()
        output_kind = classify_audio_output(desc, iface)
        output_label = _format_output_label(desc, iface)
        recommended_ms = compute_recommended_sync_ms(output_kind, strategy, resolution_preset)

        norm_device = (device_key or "default_ios").strip() or "default_ios"
        profile_key = f"{endpoint_id}::{norm_device}"
        saved = self.db.get_sync_profile(profile_key)

        if saved and saved.get("mode") == "manual":
            effective_ms = max(-400, min(600, int(saved.get("manual_offset_ms") or recommended_ms)))
            mode = "manual"
            explanation = (
                f"{output_label} çıkışı için kayıtlı özel gecikme ({_format_ms(effective_ms)}) "
                "uygulanıyor."
            )
        else:
            effective_ms = recommended_ms
            mode = "auto"
            kind_label = _KIND_LABELS[output_kind]
            explanation = (
                f"{kind_label} ({output_label}) algılandı; en akıcı ses-görüntü hizası için "
                f"otomatik {_format_ms(recommended_ms)} ayarlandı."
            )

        return AudioSyncStatus(
            endpoint_id=endpoint_id,
            output_label=output_label,
            output_kind=output_kind,
            device_key=norm_device,
            profile_key=profile_key,
            mode=mode,
            recommended_ms=recommended_ms,
            effective_ms=effective_ms,
            explanation=explanation,
        )

    def update_profile(
        self,
        req: AudioSyncUpdateRequest,
        fallback_device_key: str,
        strategy: ResolvedStrategy = "lan_wifi",
    ) -> AudioSyncStatus:
        endpoint_id, desc, iface = detect_default_audio_output()
        output_kind = classify_audio_output(desc, iface)
        output_label = _format_output_label(desc, iface)
        recommended_ms = compute_recommended_sync_ms(output_kind, strategy, req.resolution_preset)

        raw_device = req.device_key or fallback_device_key or "default_ios"
        norm_device = raw_device.strip() or "default_ios"
        profile_key = f"{endpoint_id}::{norm_device}"
        offset_to_save = recommended_ms if req.mode == "auto" else req.manual_offset_ms

        self.db.save_sync_profile(
            profile_key=profile_key,
            audio_endpoint_id=endpoint_id,
            audio_label=output_label,
            device_key=norm_device,
            mode=req.mode,
            manual_offset_ms=offset_to_save,
        )
        return self.resolve_status(norm_device, strategy, req.resolution_preset)
