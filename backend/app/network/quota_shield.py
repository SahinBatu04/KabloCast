"""Live Windows adapter telemetry and Zero-Leak Firewall Quota Shield."""

from __future__ import annotations

import subprocess
import sys
import time

import psutil

from ..models import NetworkAdapterMetrics, QuotaShieldStatus
from ..win_uac import WIN_NO_WINDOW, run_elevated_powershell

SHIELD_RULE_PREFIX = "KabloCast_Shield_"
# Strict tuple: (rule_id_suffix, ui_label, program_path, service_name)
# CRITICAL: svchost.exe MUST use -Service so Dnscache/Dhcp/WlanSvc are NEVER blocked.
SHIELD_TARGETS: list[tuple[str, str, str, str | None]] = [
    (
        "Windows_Update_wuauserv",
        "Windows Update (wuauserv)",
        r"%SystemRoot%\System32\svchost.exe",
        "wuauserv",
    ),
    (
        "Background_BITS",
        "Arka Plan Aktarımı (BITS)",
        r"%SystemRoot%\System32\svchost.exe",
        "BITS",
    ),
    (
        "Delivery_Optimization_DoSvc",
        "Teslim En İyileştirme (DoSvc)",
        r"%SystemRoot%\System32\svchost.exe",
        "DoSvc",
    ),
    (
        "OneDrive",
        "OneDrive",
        r"%LocalAppData%\Microsoft\OneDrive\OneDrive.exe",
        None,
    ),
    (
        "Edge_Updater",
        "Edge Güncelleyici",
        r"%ProgramFiles(x86)%\Microsoft\EdgeUpdate\MicrosoftEdgeUpdate.exe",
        None,
    ),
]


def build_shield_rules_script(
    targets: list[tuple[str, str, str, str | None]] = SHIELD_TARGETS,
) -> str:
    """Build PowerShell commands creating service-safe outbound block rules."""
    rules_ps: list[str] = []
    for suffix, _label, prog, service in targets:
        if prog.lower().endswith("svchost.exe") and not service:
            raise ValueError(
                f"svchost.exe kuralı hizmet filtresi (-Service) olmadan oluşturulamaz: {suffix}"
            )
        safe_name = f"{SHIELD_RULE_PREFIX}{suffix}"
        service_part = f" -Service '{service}'" if service else ""
        rules_ps.append(
            f"New-NetFirewallRule -DisplayName '{safe_name}' -Direction Outbound "
            f"-Action Block -Program '{prog}'{service_part} -Profile Any -Enabled True | Out-Null"
        )
    return (
        f"Remove-NetFirewallRule -DisplayName '{SHIELD_RULE_PREFIX}*' "
        "-ErrorAction SilentlyContinue; "
        + "; ".join(rules_ps)
    )


class QuotaShieldManager:
    """Monitors hotspot adapter bandwidth and manages scoped Windows Firewall rules."""

    def __init__(self) -> None:
        self._last_sample: dict[str, tuple[int, int, float]] = {}
        self._protected_adapter: str | None = None
        self._last_message: str | None = None

    def sample_adapters(self) -> list[NetworkAdapterMetrics]:
        """Return live RX/TX byte counters and hotspot heuristics per interface."""
        now = time.monotonic()
        io_map = psutil.net_io_counters(pernic=True)
        stats_map = psutil.net_if_stats()
        addrs_map = psutil.net_if_addrs()

        adapters: list[NetworkAdapterMetrics] = []
        for name, counters in io_map.items():
            lower = name.lower()
            if "loopback" in lower or "pseudo" in lower:
                continue
            stat = stats_map.get(name)
            is_up = bool(stat.isup) if stat else False

            ipv4 = None
            for entry in addrs_map.get(name, []):
                if entry.family.name == "AF_INET" and not entry.address.startswith("169.254."):
                    ipv4 = entry.address
                    break

            prev = self._last_sample.get(name)
            rx_kbps = 0.0
            tx_kbps = 0.0
            if prev is not None:
                dt = max(0.05, now - prev[2])
                rx_kbps = max(0.0, ((counters.bytes_recv - prev[0]) * 8.0) / (dt * 1000.0))
                tx_kbps = max(0.0, ((counters.bytes_sent - prev[1]) * 8.0) / (dt * 1000.0))
            self._last_sample[name] = (counters.bytes_recv, counters.bytes_sent, now)

            looks_hotspot = bool(
                (ipv4 and ipv4.startswith("172.20.10."))
                or "apple" in lower
                or "iphone" in lower
                or "wi-fi" in lower
            )
            adapters.append(
                NetworkAdapterMetrics(
                    name=name,
                    description=name,
                    is_up=is_up,
                    ipv4=ipv4,
                    rx_bytes=counters.bytes_recv,
                    tx_bytes=counters.bytes_sent,
                    rx_kbps=round(rx_kbps, 1),
                    tx_kbps=round(tx_kbps, 1),
                    looks_like_hotspot=looks_hotspot,
                )
            )

        adapters.sort(key=lambda a: (not a.is_up, not a.looks_like_hotspot, a.name))
        return adapters

    def _query_shield_rules(self) -> int:
        if sys.platform == "win32":
            try:
                import winreg

                key_path = (
                    r"SYSTEM\CurrentControlSet\Services\SharedAccess"
                    r"\Parameters\FirewallPolicy\FirewallRules"
                )
                count = 0
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                    num_vals = winreg.QueryInfoKey(key)[1]
                    for idx in range(num_vals):
                        _name, val, _kind = winreg.EnumValue(key, idx)
                        if (
                            isinstance(val, str)
                            and "Active=TRUE" in val
                            and "Action=Block" in val
                            and f"Name={SHIELD_RULE_PREFIX}" in val
                        ):
                            count += 1
                return count
            except OSError:
                pass

        ps_cmd = (
            f"(Get-NetFirewallRule -DisplayName '{SHIELD_RULE_PREFIX}*' "
            "-ErrorAction SilentlyContinue | Measure-Object).Count"
        )
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=4,
                creationflags=WIN_NO_WINDOW,
                check=False,
            )
            return int(proc.stdout.strip() or "0")
        except Exception:
            return 0

    def toggle(self, enable: bool, adapter_name: str | None = None) -> QuotaShieldStatus:
        """Create or remove scoped Windows Firewall rules via UAC elevation."""
        if enable:
            inner = build_shield_rules_script()
            self._protected_adapter = adapter_name or "Wi-Fi / Hotspot"
            action_msg = (
                "Kota Kalkanı aktif (yalnızca Windows Update/BITS/DoSvc, OneDrive ve Edge Update "
                "engellendi; DNS ve tarayıcı trafiğiniz açıktır)."
            )
        else:
            inner = (
                f"Remove-NetFirewallRule -DisplayName '{SHIELD_RULE_PREFIX}*' "
                "-ErrorAction SilentlyContinue"
            )
            self._protected_adapter = None
            action_msg = "Kota Kalkanı kuralları temizlendi."

        ok, err_msg = run_elevated_powershell(inner, timeout=30)
        if not ok and err_msg:
            self._last_message = f"UAC onayı alınamadı veya iptal edildi: {err_msg}"
        else:
            self._last_message = action_msg
        return self.status()

    def status(self) -> QuotaShieldStatus:
        rule_count = self._query_shield_rules()
        return QuotaShieldStatus(
            active=rule_count > 0,
            protected_adapter=self._protected_adapter,
            active_rule_count=rule_count,
            blocked_apps_summary=[label for _suffix, label, _prog, _svc in SHIELD_TARGETS],
            adapters=self.sample_adapters(),
            last_message=self._last_message,
        )
