"""Local Wi-Fi Direct SoftAP controller using WinRT WiFiDirectAdvertisementPublisher."""

from __future__ import annotations

import contextlib
import io
import ipaddress
import secrets
import string
import subprocess
import time
from urllib.parse import quote

import psutil
import qrcode
import qrcode.image.svg

from ..models import WifiDirectStatus
from ..win_uac import WIN_NO_WINDOW

_ALPHABET = string.ascii_uppercase + string.digits


def generate_passphrase(length: int = 10) -> str:
    """Generate a clean WPA2 passphrase without ambiguous characters."""
    safe = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789abcdefghjkmnpqrstuvwxyz"
    return "".join(secrets.choice(safe) for _ in range(length))


def build_wifi_qr_data_uri(ssid: str, passphrase: str) -> str:
    """Build an inline SVG data URI (`encodeURIComponent`) for iPhone Camera Wi-Fi join."""
    esc = lambda s: s.replace("\\", "\\\\").replace(";", "\\;").replace(":", "\\:")  # noqa: E731
    payload = f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(passphrase)};;"
    img = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    svg_text = buf.getvalue().decode("utf-8")
    # Force explicit light background & dark modules for reliable iPhone camera scanning
    svg_text = svg_text.replace(
        "<svg ",
        '<svg style="background:#f6f5f0;border-radius:10px;padding:6px" ',
        1,
    )
    return f"data:image/svg+xml;charset=utf-8,{quote(svg_text)}"


def build_manual_ip_guide(local_ip: str | None) -> dict[str, str]:
    """Return exact iPhone Manual IP settings with blank Router so YouTube stays on Cellular."""
    host_ip = local_ip or "192.168.137.1"
    try:
        ip_obj = ipaddress.IPv4Address(host_ip)
        octets = str(ip_obj).split(".")
        iphone_ip = f"{octets[0]}.{octets[1]}.{octets[2]}.55"
    except Exception:
        iphone_ip = "192.168.137.55"

    return {
        "iphone_ip": iphone_ip,
        "subnet_mask": "255.255.255.0",
        "router": "BOŞ BIRAKIN (Hücresel İnterneti Korur)",
        "dns": "BOŞ BIRAKIN",
        "laptop_ip": host_ip,
    }


def _find_wifi_direct_ip() -> str | None:
    """Inspect active Windows interfaces for Wi-Fi Direct / SoftAP IPv4 address."""
    addrs = psutil.net_if_addrs()
    for name, entries in addrs.items():
        lower = name.lower()
        is_wfd_name = (
            "yerel ağ bağlantısı*" in lower
            or "local area connection*" in lower
            or "wi-fi direct" in lower
        )
        if is_wfd_name:
            for entry in entries:
                if entry.family.name == "AF_INET" and not entry.address.startswith("169.254."):
                    return entry.address
    # Fallback: check 192.168.137.x ICS / SoftAP address
    for entries in addrs.values():
        for entry in entries:
            if entry.family.name == "AF_INET" and entry.address.startswith("192.168.137."):
                return entry.address
    return None


class WifiDirectManager:
    """Manages a persistent WinRT Wi-Fi Direct Autonomous Group Owner (Legacy AP)."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._ssid = "DIRECT-KabloCast"
        self._passphrase = generate_passphrase()
        self._error: str | None = None

    def is_supported(self) -> bool:
        return True

    def start(
        self, ssid: str = "DIRECT-KabloCast", passphrase: str | None = None
    ) -> WifiDirectStatus:
        """Start Wi-Fi Direct SoftAP in a held PowerShell WinRT background worker."""
        self.stop()
        if any(ch in ssid for ch in ("\r", "\n", "\x00")) or (
            passphrase and any(ch in passphrase for ch in ("\r", "\n", "\x00"))
        ):
            raise ValueError("SSID veya parola geçersiz kontrol karakteri içeremez.")

        clean_ssid = ssid if ssid.startswith("DIRECT-") else f"DIRECT-{ssid[:25]}"
        self._ssid = clean_ssid
        self._passphrase = passphrase or generate_passphrase()
        self._error = None

        ssid_ps = self._ssid.replace("'", "''")
        pass_ps = self._passphrase.replace("'", "''")
        wfd_ns = "Windows.Devices.WiFiDirect"
        ps_script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [{wfd_ns}.WiFiDirectAdvertisementPublisher, {wfd_ns}, ContentType=WindowsRuntime]
$pub = [{wfd_ns}.WiFiDirectAdvertisementPublisher]::new()
$pub.Advertisement.IsAutonomousGroupOwnerEnabled = $true
$discEnum = [{wfd_ns}.WiFiDirectAdvertisementListenStateDiscoverability]::Normal
$pub.Advertisement.ListenStateDiscoverability = $discEnum
$pub.Advertisement.LegacySettings.IsEnabled = $true
$pub.Advertisement.LegacySettings.Ssid = '{ssid_ps}'
$pub.Advertisement.LegacySettings.Passphrase.Password = '{pass_ps}'
$pub.Start()
Write-Output ("STATUS:" + $pub.Status)
[Console]::Out.Flush()
while ($true) {{
  Start-Sleep -Seconds 2
  $aborted = [{wfd_ns}.WiFiDirectAdvertisementPublisherStatus]::Aborted
  if ($pub.Status -eq $aborted) {{
    Write-Output "ABORTED"
    break
  }}
}}
"""
        try:
            self._proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=WIN_NO_WINDOW,
            )
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline and self._proc.stdout is not None:
                line = self._proc.stdout.readline().strip()
                if line.startswith("STATUS:"):
                    if "Started" not in line and "Created" not in line:
                        self._error = f"Wi-Fi Direct durumu: {line}"
                    break
                if self._proc.poll() is not None:
                    err = self._proc.stderr.read().strip() if self._proc.stderr else ""
                    self._error = err or "Wi-Fi Direct başlatılamadı."
                    break
        except Exception as exc:
            self._error = str(exc)
        return self.status()

    def stop(self) -> WifiDirectStatus:
        if self._proc is not None and self._proc.poll() is None:
            with contextlib.suppress(Exception):
                self._proc.terminate()
                self._proc.wait(timeout=2)
            if self._proc.poll() is None:
                with contextlib.suppress(Exception):
                    self._proc.kill()
        self._proc = None
        return self.status()

    def status(self) -> WifiDirectStatus:
        active = self._proc is not None and self._proc.poll() is None and self._error is None
        local_ip = _find_wifi_direct_ip()
        return WifiDirectStatus(
            supported=self.is_supported(),
            active=active,
            ssid=self._ssid,
            passphrase=self._passphrase,
            local_ip=local_ip,
            qr_svg_data_uri=build_wifi_qr_data_uri(self._ssid, self._passphrase),
            manual_ip_guide=build_manual_ip_guide(local_ip),
            error=self._error,
        )
