"""Shared Windows UAC elevation helper with safe Base64 command encoding."""

from __future__ import annotations

import base64
import contextlib
import ctypes
import subprocess
import sys

WIN_NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def is_admin() -> bool:
    """Return True when the current process holds Windows Administrator privileges."""
    if sys.platform != "win32":
        return True
    with contextlib.suppress(Exception):
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    return False


def encode_powershell_command(script: str) -> str:
    """Encode a PowerShell script as UTF-16LE Base64 for -EncodedCommand."""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def run_elevated_powershell(script: str, timeout: int = 90) -> tuple[bool, str]:
    """Execute PowerShell with Administrator rights, skipping RunAs if already elevated."""
    if sys.platform != "win32":
        return False, "Yönetici yükseltmesi yalnızca Windows üzerinde desteklenir."

    encoded = encode_powershell_command(script)
    if is_admin():
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=WIN_NO_WINDOW,
            check=False,
        )
        if proc.returncode == 0:
            return True, proc.stdout.strip()
        err = proc.stderr.strip() or proc.stdout.strip() or "Komut başarısız oldu."
        return False, err

    # Wrap Start-Process so UAC rejection or desktop restrictions surface cleanly
    launcher = (
        "$ErrorActionPreference = 'Stop'; "
        "try { "
        "$p = Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -PassThru "
        f"-ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded}'); "
        "if ($null -ne $p -and $p.ExitCode -ne 0) { exit $p.ExitCode } "
        "} catch { "
        "Write-Error ($_.Exception.Message); exit 1 "
        "}"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", launcher],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=WIN_NO_WINDOW,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "Yönetici işlemi zaman aşımına uğradı."

    if proc.returncode == 0:
        return True, proc.stdout.strip()

    raw_err = (proc.stderr or proc.stdout or "").strip()
    lower = raw_err.casefold().replace("i\u0307", "i")
    if "istek desteklenmiyor" in lower or "request is not supported" in lower:
        return False, (
            "Windows UAC penceresi bu arka plan oturumundan açılamadı (İstek desteklenmiyor). "
            "Lütfen uygulamayı masaüstündeki KabloCast.bat dosyasından açın (gerekirse sağ "
            "tıklayıp 'Yönetici olarak çalıştır' seçin)."
        )
    return False, raw_err or "UAC yönetici onayı kullanıcı tarafından iptal edildi."
