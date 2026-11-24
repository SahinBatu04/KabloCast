"""Safe Apple USB device detector and non-filter driver assistant for Windows 11."""

from __future__ import annotations

import contextlib
import ctypes
import json
import re
import subprocess
import sys
from pathlib import Path

from ..models import AppleUsbDevice, DriverActionResult
from ..win_uac import WIN_NO_WINDOW, run_elevated_powershell

APPLE_INSTANCE_RE = re.compile(r"^USB\\VID_05AC&PID_([0-9A-Fa-f]{4})\\([^\\&]+)$")

MODEL_BY_PID = {
    "12A8": ("iPhone (USB-C / Lightning)", "Type-C veya Lightning-Type-C Kablo"),
    "12AB": ("iPad (USB-C / Lightning)", "Type-C veya Lightning Kablo"),
}

UDID_PREFIX_HINTS: dict[str, tuple[str, str]] = {
    "00008150": ("iPhone 17 Serisi", "USB Type-C Kablo"),
    "00008140": ("iPhone 16 Pro / Pro Max", "USB Type-C Kablo"),
    "00008130": ("iPhone 15 Pro / Pro Max", "USB Type-C Kablo"),
    "00008120": ("iPhone 14 Pro / 15", "USB-C veya Lightning Kablo"),
    "00008110": ("iPhone 13 / 14", "Lightning → Type-C Kablo"),
    "00008101": ("iPhone 12 Serisi", "Lightning → Type-C Kablo"),
    "00008030": ("iPhone 11 / SE", "Lightning → Type-C Kablo"),
}


def infer_apple_device_hint(pid: str, serial: str, friendly_name: str) -> tuple[str, str]:
    """Infer user-friendly Apple device model and cable hint from PID, UDID serial, and name."""
    norm_pid = (pid or "").strip().upper()
    norm_name = (friendly_name or "").strip().lower()
    if norm_pid == "12AB" or "ipad" in norm_name:
        return ("iPad (USB-C / Lightning)", "Type-C veya Lightning Kablo")

    norm_serial = (serial or "").strip().upper()
    if len(norm_serial) >= 8:
        prefix = norm_serial[:8]
        if prefix in UDID_PREFIX_HINTS:
            return UDID_PREFIX_HINTS[prefix]

    if norm_pid in MODEL_BY_PID:
        return MODEL_BY_PID[norm_pid]
    return ("iPhone (USB-C / Lightning)", "Type-C veya Lightning Kablo")


def classify_driver_mode(service_name: str) -> str:
    """Map Windows PnP driver service name to normalized driver_mode."""
    svc = (service_name or "").strip().lower()
    if svc == "usbccgp":
        return "apple_usbccgp"
    if svc in ("libusb0", "libusbk"):
        return "libusb_win32"
    if svc == "winusb":
        return "winusb"
    return "unknown"


def validate_apple_instance_id(instance_id: str) -> tuple[str, str]:
    """Validate and extract (PID, serial) from a Windows Apple USB InstanceId."""
    match = APPLE_INSTANCE_RE.match(instance_id.strip())
    if not match:
        raise ValueError(f"Geçersiz Apple USB aygıt kimliği: {instance_id}")
    return match.group(1).upper(), match.group(2)


def _detect_apple_usb_fast_win32() -> list[dict[str, str]] | None:
    """Enumerate present Apple USB composite devices in ~1-2 ms via cfgmgr32 + winreg."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        cfgmgr = ctypes.WinDLL("cfgmgr32")
        flags = 0x00000001 | 0x00000100  # CM_GETIDLIST_FILTER_ENUMERATOR | PRESENT
        size = ctypes.c_ulong(0)
        if cfgmgr.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), "USB", flags) != 0:
            return None
        if size.value == 0:
            return []
        buf = ctypes.create_unicode_buffer(size.value)
        if cfgmgr.CM_Get_Device_ID_ListW("USB", buf, size.value, flags) != 0:
            return None
        raw = ctypes.wstring_at(buf, size.value)
        items: list[dict[str, str]] = []
        for dev_id in raw.split("\x00"):
            if not dev_id or not APPLE_INSTANCE_RE.match(dev_id):
                continue
            svc = ""
            friendly = ""
            with contextlib.suppress(OSError), winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, rf"SYSTEM\CurrentControlSet\Enum\{dev_id}"
            ) as key:
                with contextlib.suppress(OSError):
                    svc = str(winreg.QueryValueEx(key, "Service")[0] or "")
                with contextlib.suppress(OSError):
                    friendly = str(winreg.QueryValueEx(key, "FriendlyName")[0] or "")
                if not friendly:
                    with contextlib.suppress(OSError):
                        desc = str(winreg.QueryValueEx(key, "DeviceDesc")[0] or "")
                        friendly = desc.rsplit(";", 1)[-1]
            items.append(
                {
                    "InstanceId": dev_id,
                    "FriendlyName": friendly or "Apple Mobile Device USB",
                    "Status": "OK",
                    "Service": svc,
                }
            )
        return items
    except Exception:
        return None


def detect_apple_usb_devices() -> list[AppleUsbDevice]:
    """Inspect connected Apple composite USB devices via Windows PnP (non-admin)."""
    items = _detect_apple_usb_fast_win32()
    if items is None:
        ps_script = (
            "$devs = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
            "Where-Object { $_.InstanceId -match '^USB\\\\VID_05AC&PID_[0-9A-Fa-f]{4}\\\\' }; "
            "$out = foreach ($d in $devs) { "
            "$svc = (Get-PnpDeviceProperty -InstanceId $d.InstanceId "
            "-KeyName 'DEVPKEY_Device_Service' -ErrorAction SilentlyContinue).Data; "
            "[PSCustomObject]@{ InstanceId=$d.InstanceId; FriendlyName=$d.FriendlyName; "
            "Status=$d.Status; Service=[string]$svc } }; "
            "$out | ConvertTo-Json -Compress"
        )
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=6,
                creationflags=WIN_NO_WINDOW,
                check=False,
            )
            raw = proc.stdout.strip()
            if not raw:
                return []
            parsed = json.loads(raw)
            items = parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            return []

    devices: list[AppleUsbDevice] = []
    for item in items:
        instance_id = str(item.get("InstanceId", ""))
        m = APPLE_INSTANCE_RE.match(instance_id)
        if not m:
            continue
        pid = m.group(1).upper()
        serial = m.group(2)
        svc = str(item.get("Service", "") or "")
        friendly = str(item.get("FriendlyName") or "Apple Mobile Device USB")
        driver_mode = classify_driver_mode(svc)
        model_hint, cable_hint = infer_apple_device_hint(pid, serial, friendly)
        devices.append(
            AppleUsbDevice(
                instance_id=instance_id,
                friendly_name=friendly,
                product_id=pid,
                serial=serial,
                model_hint=model_hint,
                cable_hint=cable_hint,
                active_service=svc or "unknown",
                status=str(item.get("Status") or "OK"),
                qt_ready=driver_mode in ("libusb_win32", "winusb"),
                driver_mode=driver_mode,  # type: ignore[arg-type]
            )
        )
    return devices


def run_driver_assistant(
    script_path: Path,
    backup_dir: Path,
    instance_id: str,
    action: str,
) -> DriverActionResult:
    """Invoke the UAC-elevated safe USB driver helper (never stacks UpperFilters)."""
    validate_apple_instance_id(instance_id)
    if not script_path.exists():
        return DriverActionResult(
            ok=False,
            action=action,
            instance_id=instance_id,
            message="Sürücü yardımcı betiği bulunamadı.",
        )

    ps_action = {
        "bind_libusb": "bind",
        "restore_apple": "restore",
        "remove_unsafe_filter": "removefilter",
    }.get(action)
    if not ps_action:
        raise ValueError(f"Desteklenmeyen sürücü eylemi: {action}")

    result_path = backup_dir / "last_driver_action.json"
    if result_path.exists():
        result_path.unlink()

    script_escaped = str(script_path).replace("'", "''")
    res_escaped = str(result_path).replace("'", "''")
    inst_escaped = instance_id.replace("'", "''")
    ps_script = (
        f"& '{script_escaped}' -Action '{ps_action}' "
        f"-InstanceId '{inst_escaped}' -ResultPath '{res_escaped}'"
    )
    ok, err_msg = run_elevated_powershell(ps_script, timeout=90)

    if result_path.exists():
        data = json.loads(result_path.read_text(encoding="utf-8-sig"))
        return DriverActionResult(
            ok=bool(data.get("ok", False)),
            action=action,
            instance_id=instance_id,
            message=str(data.get("message") or ""),
            requires_uac=True,
            backup_path=data.get("backup"),
            rolled_back=bool(data.get("rolledBack", False)),
        )

    return DriverActionResult(
        ok=False if not ok else True,
        action=action,
        instance_id=instance_id,
        message=err_msg or "UAC yönetici onayı kullanıcı tarafından iptal edildi.",
        requires_uac=True,
    )
