"""Bluetooth LE AirPlay discovery beacon for Windows 11."""

from __future__ import annotations

import contextlib
import ipaddress
import socket
import subprocess

from ..models import BleBeaconStatus
from ..win_uac import WIN_NO_WINDOW


def detect_primary_local_ipv4() -> str | None:
    """Find best local non-loopback IPv4 address for AirPlay advertisement."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("10.255.255.255", 1))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        hostname_ip = socket.gethostbyname(socket.gethostname())
        if hostname_ip and not hostname_ip.startswith("127."):
            return hostname_ip
    except Exception:
        pass
    return None


def build_airplay_ble_payload(ipv4: str, port: int = 7000) -> bytes:
    """Build Apple AirPlay Service Data / Manufacturer payload (UxPlay v1.73+ spec).

    Apple Company ID: 0x004C, Type 0x09 (AirPlay Target), Length 0x08,
    Flags 0x01, Seed 0x0000, IPv4 (4 bytes), Port (2 bytes big-endian).
    """
    ip_bytes = ipaddress.IPv4Address(ipv4).packed
    return bytes([0x09, 0x08, 0x13, 0x01]) + ip_bytes + port.to_bytes(2, "big")


class BleBeaconManager:
    """Controls Windows WinRT BluetoothLEAdvertisementPublisher for AirPlay discovery."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._ip: str | None = None
        self._port = 7000
        self._error: str | None = None

    def start(self, ipv4: str | None = None, port: int = 7000) -> BleBeaconStatus:
        self.stop()
        target_ip = ipv4 or detect_primary_local_ipv4() or "192.168.137.1"
        self._ip = target_ip
        self._port = port
        self._error = None

        payload = build_airplay_ble_payload(target_ip, port)
        hex_bytes = ",".join(f"0x{b:02X}" for b in payload)
        ble_ns = "Windows.Devices.Bluetooth.Advertisement"
        ps_script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [{ble_ns}.BluetoothLEAdvertisementPublisher, {ble_ns}, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.DataWriter, Windows.Storage.Streams, ContentType=WindowsRuntime]
$adv = [{ble_ns}.BluetoothLEAdvertisement]::new()
$mfg = [{ble_ns}.BluetoothLEManufacturerData]::new()
$mfg.CompanyId = 0x004C
$writer = [Windows.Storage.Streams.DataWriter]::new()
$bytes = [byte[]]@({hex_bytes})
$writer.WriteBytes($bytes)
$mfg.Data = $writer.DetachBuffer()
$adv.ManufacturerData.Add($mfg)
$pub = [{ble_ns}.BluetoothLEAdvertisementPublisher]::new($adv)
$pub.Start()
Write-Output ("BLE:" + $pub.Status)
[Console]::Out.Flush()
while ($true) {{ Start-Sleep -Seconds 3 }}
"""
        try:
            self._proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=WIN_NO_WINDOW,
            )
            if self._proc.stdout is not None:
                line = self._proc.stdout.readline().strip()
                if not line.startswith("BLE:"):
                    err = self._proc.stderr.read().strip() if self._proc.stderr else ""
                    self._error = err or "Bluetooth LE işaretçisi başlatılamadı."
        except Exception as exc:
            self._error = str(exc)
        return self.status()

    def stop(self) -> BleBeaconStatus:
        if self._proc is not None and self._proc.poll() is None:
            with contextlib.suppress(Exception):
                self._proc.terminate()
                self._proc.wait(timeout=2)
            if self._proc.poll() is None:
                with contextlib.suppress(Exception):
                    self._proc.kill()
        self._proc = None
        return self.status()

    def status(self) -> BleBeaconStatus:
        active = self._proc is not None and self._proc.poll() is None and self._error is None
        return BleBeaconStatus(
            supported=True,
            active=active,
            target_ip=self._ip,
            port=self._port,
            error=self._error,
        )
