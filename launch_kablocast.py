"""KabloCast Studio desktop launcher (FastAPI + Edge App Window)."""

from __future__ import annotations

import contextlib
import ctypes
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
VENV_PYTHON = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
EDGE_PROFILE_DIR = ROOT_DIR / "data" / "edge_app_profile"
HOST = "127.0.0.1"
PORT = 8765
BASE_URL = f"http://{HOST}:{PORT}"
WIN_NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

EDGE_CANDIDATES = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    / "Microsoft"
    / "Edge"
    / "Application"
    / "msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    / "Microsoft"
    / "Edge"
    / "Application"
    / "msedge.exe",
]


def wait_for_health(timeout_sec: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=1.2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.35)
    return False


def _find_edge_profile_pids(profile_dir: Path) -> list[int]:
    """Return PIDs of main Edge browser processes owning KabloCast's isolated profile."""
    if sys.platform != "win32":
        return []
    needle = str(profile_dir).lower()
    pids: list[int] = []
    try:
        import psutil  # installed inside backend .venv

        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                if (proc.info.get("name") or "").lower() != "msedge.exe":
                    continue
                cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                if needle in cmdline and "--type=" not in cmdline:
                    pids.append(int(proc.info["pid"]))
    except Exception:
        return []
    return pids


def _focus_existing_edge_window(profile_dir: Path) -> bool:
    """Bring an already-open KabloCast Edge app window to the foreground."""
    if sys.platform != "win32":
        return False
    pids = set(_find_edge_profile_pids(profile_dir))
    if not pids:
        return False
    try:
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        matched_hwnd: list[int] = []
        enum_cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _cb(hwnd: int, _lp: int) -> bool:
            proc_id = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
            if proc_id.value in pids and user32.IsWindowVisible(hwnd):
                rc = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rc))
                if (rc.right - rc.left) >= 240 and (rc.bottom - rc.top) >= 180:
                    matched_hwnd.append(hwnd)
                    return False
            return True

        user32.EnumWindows(enum_cb(_cb), 0)
        if not matched_hwnd:
            return False
        hwnd = matched_hwnd[0]
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def _close_edge_profile_windows(profile_dir: Path) -> None:
    """Close any stale Edge --app window using KabloCast's isolated profile."""
    for pid in _find_edge_profile_pids(profile_dir):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=WIN_NO_WINDOW,
            check=False,
        )


def open_app_window() -> tuple[subprocess.Popen[bytes] | None, bool]:
    for candidate in EDGE_CANDIDATES:
        if candidate.exists():
            EDGE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            _close_edge_profile_windows(EDGE_PROFILE_DIR)
            time.sleep(0.25)
            proc = subprocess.Popen(
                [
                    str(candidate),
                    f"--app={BASE_URL}",
                    "--window-size=1180,820",
                    f"--user-data-dir={EDGE_PROFILE_DIR}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=WIN_NO_WINDOW,
            )
            return proc, True
    webbrowser.open(BASE_URL)
    return None, False


def _terminate_tree(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=WIN_NO_WINDOW,
            check=False,
        )
        with contextlib.suppress(Exception):
            proc.wait(timeout=3)
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


def _cleanup_uxplay_processes() -> None:
    """Ensure no orphaned uxplay-windows or BLE beacon processes remain on exit."""
    if sys.platform != "win32":
        return
    for exe_name in ("uxplay-windows.exe", "uxplay-bluetooth-beacon.exe"):
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/IM", exe_name, "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                creationflags=WIN_NO_WINDOW,
                check=False,
            )


def _stop_existing_server() -> None:
    """Stop any stale uvicorn app.main:app holding PORT so the desktop session owns UAC."""
    ps_cmd = (
        f"$pids = Get-NetTCPConnection -LocalPort {PORT} -State Listen "
        "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; "
        "foreach ($p in $pids) { "
        "$proc = Get-CimInstance Win32_Process -Filter \"ProcessId=$p\" "
        "-ErrorAction SilentlyContinue; "
        "if ($proc -and $proc.CommandLine -match 'app\\.main:app') { "
        "Stop-Process -Id $p -Force -ErrorAction SilentlyContinue "
        "} }"
    )
    with contextlib.suppress(Exception):
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            creationflags=WIN_NO_WINDOW,
            check=False,
        )
        time.sleep(0.3)


def _wait_for_edge_exit(app_proc: subprocess.Popen[bytes] | None, stop_check: object) -> None:
    saw_edge_browser = False
    missing_streak = 0
    grace_deadline = time.monotonic() + 10.0

    while not callable(stop_check) or not stop_check():
        edge_alive = bool(_find_edge_profile_pids(EDGE_PROFILE_DIR))
        if not edge_alive and app_proc is not None and app_proc.poll() is None:
            edge_alive = True
        if edge_alive:
            saw_edge_browser = True
            missing_streak = 0
        elif saw_edge_browser:
            missing_streak += 1
            if missing_streak >= 4:
                break
        elif time.monotonic() > grace_deadline:
            break
        time.sleep(0.45)


def main() -> int:
    # Single-instance guard: bring running KabloCast window forward if already active
    if wait_for_health(timeout_sec=0.8):
        if _focus_existing_edge_window(EDGE_PROFILE_DIR):
            return 0
        app_proc, using_edge = open_app_window()
        if using_edge:
            _wait_for_edge_exit(app_proc, lambda: False)
        return 0

    python_exe = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)

    _stop_existing_server()

    data_dir = ROOT_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    log_fh = open(data_dir / "uvicorn.log", "ab")

    stop_requested = False

    def _on_signal(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _on_signal)

    server = subprocess.Popen(
        [
            str(python_exe),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            HOST,
            "--port",
            str(PORT),
            "--no-use-colors",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        creationflags=WIN_NO_WINDOW,
    )

    app_proc: subprocess.Popen[bytes] | None = None
    using_edge = False
    try:
        if not wait_for_health():
            print("KabloCast sunucusu başlatılamadı.", file=sys.stderr)
            return 1
        app_proc, using_edge = open_app_window()

        if using_edge:
            _wait_for_edge_exit(
                app_proc,
                lambda: stop_requested or server.poll() is not None,
            )
        else:
            while not stop_requested and server.poll() is None:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        with contextlib.suppress(Exception):
            req = urllib.request.Request(f"{BASE_URL}/api/stream/stop", method="POST")
            with urllib.request.urlopen(req, timeout=1.5):
                pass
        if app_proc is not None and app_proc.poll() is None:
            _terminate_tree(app_proc)
        if using_edge and stop_requested:
            _close_edge_profile_windows(EDGE_PROFILE_DIR)
        _terminate_tree(server)
        with contextlib.suppress(Exception):
            log_fh.close()
        _cleanup_uxplay_processes()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
