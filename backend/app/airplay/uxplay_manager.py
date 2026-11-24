"""AirPlay 2 receiver management powered by bundled UxPlay + D3D11/WASAPI + BLE Beacon."""

from __future__ import annotations

import contextlib
import ctypes
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import psutil

from ..win_uac import WIN_NO_WINDOW, is_admin, run_elevated_powershell

RESOLUTION_RE = re.compile(r"(\d{3,4})\s*[x×]\s*(\d{3,4})")
FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps", re.IGNORECASE)


@dataclass(slots=True)
class AirPlayRuntimeState:
    """Observed live AirPlay receiver status."""

    running: bool = False
    pid: int | None = None
    airplay_name: str = "KabloCast"
    client_connected: bool = False
    client_name: str = "Bekleniyor"
    codec: str = "H.264 / HEVC"
    resolution: str = "Otomatik"
    fps: float = 0.0
    last_log_line: str = ""
    error: str | None = None


class UxPlayManager:
    """Starts, configures, monitors, and stops the portable UxPlay AirPlay 2 receiver."""

    def __init__(self, uxplay_dir: Path) -> None:
        self.uxplay_dir = uxplay_dir
        self._proc: subprocess.Popen[bytes] | None = None
        self.state = AirPlayRuntimeState()
        self._log_offset = 0
        self._last_resolution_preset = "1080p"
        self._last_audio_enabled = True
        self._last_audio_sync_ms = 180
        self._last_fullscreen = True
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._enforced_hwnd_state: tuple[int, bool] | None = None
        self._video_hwnd_seen: bool = False
        self._log_fh: IO[bytes] | None = None
        self._firewall_checked = False

    @property
    def exe_path(self) -> Path:
        return self.uxplay_dir / "uxplay-windows.exe"

    @property
    def mdns_exe_path(self) -> Path:
        return self.uxplay_dir / "mDNSResponder.exe"

    @property
    def is_installed(self) -> bool:
        return self.exe_path.exists()

    def bonjour_ready(self) -> bool:
        """Return True on Windows when Apple's Bonjour Service is installed and running."""
        if sys.platform != "win32":
            return True
        with contextlib.suppress(Exception):
            svc = psutil.win_service_get("Bonjour Service")
            return str(svc.status()).lower() == "running"
        return False

    def _build_firewall_allow_ps(self) -> str:
        ux_escaped = str(self.exe_path).replace("'", "''")
        mdns_escaped = str(self.mdns_exe_path).replace("'", "''")
        return (
            "Remove-NetFirewallRule -DisplayName 'KabloCast_AirPlay_Allow*' "
            "-ErrorAction SilentlyContinue; "
            f"New-NetFirewallRule -DisplayName 'KabloCast_AirPlay_Allow_UxPlay' "
            f"-Direction Inbound -Action Allow -Program '{ux_escaped}' "
            "-Profile Any -Enabled True | Out-Null; "
            f"New-NetFirewallRule -DisplayName 'KabloCast_AirPlay_Allow_Bonjour' "
            f"-Direction Inbound -Action Allow -Program '{mdns_escaped}' "
            "-Profile Any -Enabled True | Out-Null"
        )

    def _ensure_firewall_allow_if_admin(self) -> None:
        """Ensure Profile=Any Inbound Allow rules exist when running elevated."""
        if self._firewall_checked or sys.platform != "win32" or not is_admin():
            return
        self._firewall_checked = True
        with contextlib.suppress(OSError):
            import winreg

            key_path = (
                r"SYSTEM\CurrentControlSet\Services\SharedAccess"
                r"\Parameters\FirewallPolicy\FirewallRules"
            )
            has_ux = False
            has_mdns = False
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                num_vals = winreg.QueryInfoKey(key)[1]
                for idx in range(num_vals):
                    _name, val, _kind = winreg.EnumValue(key, idx)
                    if isinstance(val, str) and "Name=KabloCast_AirPlay_Allow_UxPlay" in val:
                        has_ux = True
                    elif isinstance(val, str) and "Name=KabloCast_AirPlay_Allow_Bonjour" in val:
                        has_mdns = True
            if has_ux and has_mdns:
                return
        with contextlib.suppress(Exception):
            cmd = self._build_firewall_allow_ps()
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                capture_output=True,
                timeout=15,
                creationflags=WIN_NO_WINDOW,
                check=False,
            )

    def install_bonjour(self) -> tuple[bool, str]:
        """Install and start bundled mDNSResponder as 'Bonjour Service' via Windows UAC."""
        if self.bonjour_ready():
            return True, "Bonjour Service zaten kurulu ve çalışıyor."
        if sys.platform != "win32":
            return True, "Bonjour yalnızca Windows'ta gereklidir."
        if not self.mdns_exe_path.exists():
            return False, f"mDNSResponder.exe bulunamadı: {self.mdns_exe_path}"

        exe_escaped = str(self.mdns_exe_path).replace("'", "''")
        inner = (
            f"& '{exe_escaped}' -install; "
            "Start-Service -Name 'Bonjour Service' -ErrorAction SilentlyContinue; "
            f"{self._build_firewall_allow_ps()}"
        )
        ok, err = run_elevated_powershell(inner, timeout=90)
        if self.bonjour_ready():
            return True, "Bonjour Service (mDNSResponder) kuruldu ve başlatıldı."
        if ok:
            return False, "Bonjour kurulumu tamamlandı ancak servis henüz başlatılamadı."
        return False, err or "Bonjour Service başlatılamadı (UAC onayını kontrol edin)."

    @property
    def _arguments_file(self) -> Path:
        appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        return appdata / "leapbtw" / "uxplay-windows" / "arguments.txt"

    @property
    def _log_file(self) -> Path:
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return local / "leapbtw" / "uxplay-windows" / "session.log"

    @staticmethod
    def _sync_uxplay_qsettings(fullscreen: bool) -> None:
        """Persist force_fs_enabled + renderer_mode=d3d11 in HKCU QSettings so -fs is kept."""
        # uxplay-windows.exe applyRendererAndFullscreenArgs() strips -fs/-vs from arguments.txt
        # and only re-adds them based on HKCU\Software\leapbtw\uxplay-windows QSettings keys.
        if sys.platform != "win32":
            return
        with contextlib.suppress(OSError):
            import winreg

            reg_path = r"Software\leapbtw\uxplay-windows"
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, "renderer_mode", 0, winreg.REG_SZ, "d3d11")
                winreg.SetValueEx(
                    key, "force_fs_enabled", 0, winreg.REG_SZ, "true" if fullscreen else "false"
                )

    def write_arguments(
        self,
        airplay_name: str,
        resolution_preset: str = "1080p",
        audio_enabled: bool = True,
        audio_sync_ms: int = 180,
        fullscreen: bool = True,
    ) -> Path:
        """Write uxplay arguments.txt + QSettings for D3D11, fullscreen, and WASAPI2 audio."""
        self._sync_uxplay_qsettings(fullscreen=fullscreen)
        clean_name = re.sub(r'[\r\n"]+', "", airplay_name).strip() or "KabloCast"
        name_arg = f'"{clean_name}"' if " " in clean_name else clean_name
        args = [
            "-n",
            name_arg,
            "-nh",
            "-vd",
            "d3d11h264dec",
            "-vc",
            "d3d11convert",
            "-vs",
            "d3d11videosink",
            "-fps",
            "60",
            "-reset",
            "0",
            "-nofreeze",
            "-nohold",
            "-vsync",
            "no",
        ]
        if fullscreen:
            args.append("-fs")
        if resolution_preset == "1080p":
            args.extend(["-s", "1920x1080@60"])
        elif resolution_preset == "1440p":
            args.extend(["-s", "2560x1440@60"])
        if not audio_enabled:
            args.extend(["-as", "0"])
        else:
            sync_clamped = max(-900, min(900, int(audio_sync_ms)))
            al_sec = max(0.0, min(2.0, round((250 - sync_clamped) / 1000.0, 3)))
            args.extend(["-as", "wasapi2sink", "-vol", "1.0", "-al", f"{al_sec:.3f}"])

        target = self._arguments_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(" ".join(args), encoding="utf-8")
        return target

    def _cleanup_orphaned_instances(self) -> None:
        """Terminate any stale runtime/uxplay processes so fresh arguments.txt takes effect."""
        exe_norm = os.path.normcase(str(self.exe_path))
        for proc in psutil.process_iter(["pid", "exe", "name"]):
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                proc_exe = proc.info.get("exe") or ""
                if proc_exe and os.path.normcase(proc_exe) == exe_norm:
                    proc.kill()
                elif (proc.info.get("name") or "").lower() == "uxplay-bluetooth-beacon.exe":
                    proc.kill()

    def start(
        self,
        airplay_name: str = "KabloCast",
        resolution_preset: str = "1080p",
        audio_enabled: bool = True,
        audio_sync_ms: int = 180,
        fullscreen: bool = True,
    ) -> AirPlayRuntimeState:
        """Launch uxplay-windows.exe with configured AirPlay parameters."""
        self._last_resolution_preset = resolution_preset
        self._last_audio_enabled = audio_enabled
        self._last_audio_sync_ms = audio_sync_ms
        self._last_fullscreen = fullscreen
        self._video_hwnd_seen = False

        if not self.is_installed:
            self.state.running = False
            self.state.error = f"UxPlay yürütülebilir dosyası bulunamadı: {self.exe_path}"
            return self.state

        if not self.bonjour_ready():
            self.state.running = False
            self.state.error = (
                "Windows 'Bonjour Service' çalışmıyor; iPhone Ekran Yansıtma listesinin görünmesi "
                "için önce AirPlay 2 kartındaki 'Bonjour Servisini Kur (UAC)' düğmesine tıklayın."
            )
            return self.state

        if self._proc is not None and self._proc.poll() is None:
            self.stop()
        if sys.platform == "win32":
            self._cleanup_orphaned_instances()

        self.write_arguments(
            airplay_name=airplay_name,
            resolution_preset=resolution_preset,
            audio_enabled=audio_enabled,
            audio_sync_ms=audio_sync_ms,
            fullscreen=fullscreen,
        )
        log_path = self._log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if self._log_fh is not None:
            with contextlib.suppress(Exception):
                self._log_fh.close()
            self._log_fh = None
        self._log_fh = open(log_path, "wb")
        self._log_offset = 0

        res_label = (
            "1920x1080"
            if resolution_preset == "1080p"
            else ("2560x1440" if resolution_preset == "1440p" else "Otomatik")
        )

        self._ensure_firewall_allow_if_admin()

        try:
            self._proc = subprocess.Popen(
                [str(self.exe_path)],
                cwd=str(self.uxplay_dir),
                stdout=self._log_fh,
                stderr=subprocess.STDOUT,
            )
            self.state = AirPlayRuntimeState(
                running=True,
                pid=self._proc.pid,
                airplay_name=airplay_name,
                client_connected=False,
                client_name="iPhone Denetim Merkezi → Ekran Yansıtma bekleniyor",
                codec="H.264 (AVC / D3D11)",
                resolution=res_label,
            )
        except Exception as exc:
            self.state.running = False
            self.state.error = f"UxPlay başlatılamadı: {exc}"
        return self.state

    def poll(self) -> AirPlayRuntimeState:
        """Check process health and parse new session log entries."""
        if self._proc is None or self._proc.poll() is not None:
            if self.state.running:
                self.state.running = False
                self.state.client_connected = False
            return self.state

        if self._log_file.exists():
            with contextlib.suppress(Exception):
                with self._log_file.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(self._log_offset)
                    chunk = f.read()
                    self._log_offset = f.tell()
                for line in chunk.splitlines():
                    self._parse_log_line(line)
        if sys.platform == "win32" and self._proc is not None:
            hwnd = self._find_video_hwnd(self._proc.pid)
            if hwnd is not None:
                self._video_hwnd_seen = True
                if not self.state.client_connected:
                    self.state.client_connected = True
                    self.state.client_name = "iPhone (AirPlay 2 Bağlı)"
            elif self._video_hwnd_seen:
                self._video_hwnd_seen = False
                self.state.client_connected = False
                self.state.client_name = (
                    "iPhone Denetim Merkezi → Ekran Yansıtma bekleniyor"
                )
        return self.state

    def _parse_log_line(self, line: str) -> None:
        text = line.strip()
        if not text:
            return
        self.state.last_log_line = text[-180:]
        lower = text.lower()
        if "raop_rtp_mirror" in lower or "connection from" in lower or "mirroring" in lower:
            self.state.client_connected = True
            self.state.client_name = "iPhone (AirPlay 2 Bağlı)"
        if "connection closed" in lower or "teardown" in lower:
            self.state.client_connected = False
            self.state.client_name = "Bağlantı kesildi"
        if "hevc" in lower or "h265" in lower:
            self.state.codec = "HEVC (H.265)"
        elif "h264" in lower or "avc" in lower:
            self.state.codec = "H.264 (AVC)"
        res_m = RESOLUTION_RE.search(text)
        if res_m:
            self.state.resolution = f"{res_m.group(1)}x{res_m.group(2)}"
        fps_m = FPS_RE.search(text)
        if fps_m:
            self.state.fps = float(fps_m.group(1))

    def _start_window_watcher(self) -> None:
        """Watch for 'AirPlay Video Stream' HWND and enforce borderless fullscreen automatically."""
        self._stop_window_watcher()
        if sys.platform != "win32":
            return
        self._watch_stop.clear()
        self._enforced_hwnd_state = None
        t = threading.Thread(target=self._window_watch_loop, name="uxplay-hwnd-watch", daemon=True)
        self._watch_thread = t
        t.start()

    def _stop_window_watcher(self) -> None:
        self._watch_stop.set()
        if self._watch_thread is not None and self._watch_thread.is_alive():
            self._watch_thread.join(timeout=0.8)
        self._watch_thread = None
        self._enforced_hwnd_state = None

    @staticmethod
    def _get_window_style(hwnd: int) -> int:
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        return int(user32.GetWindowLongPtrW(hwnd, -16))

    @staticmethod
    def _is_window_fullscreen(hwnd: int) -> bool:
        """Return True when the video window already covers its monitor work/screen bounds."""
        if sys.platform != "win32":
            return False
        from ctypes import wintypes

        class _MonitorInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

        hmon = user32.MonitorFromWindow(hwnd, 2)
        mi = _MonitorInfo()
        mi.cbSize = ctypes.sizeof(_MonitorInfo)
        rc = wintypes.RECT()
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)) or not user32.GetWindowRect(
            hwnd, ctypes.byref(rc)
        ):
            return False
        mon = mi.rcMonitor
        return (
            rc.left <= mon.left
            and rc.top <= mon.top
            and rc.right >= mon.right
            and rc.bottom >= mon.bottom
        )

    def _window_watch_loop(self) -> None:
        ws_caption = 0x00C00000
        while not self._watch_stop.wait(0.25):
            proc = self._proc
            if proc is None or proc.poll() is not None:
                break
            hwnd = self._find_video_hwnd(proc.pid)
            if not hwnd:
                continue
            desired = self._last_fullscreen
            has_caption = bool(self._get_window_style(hwnd) & ws_caption)
            if desired and not has_caption and self._is_window_fullscreen(hwnd):
                self._enforced_hwnd_state = (hwnd, True)
                continue
            if self._enforced_hwnd_state != (hwnd, desired) or (desired and has_caption):
                if self._apply_win32_window_mode(hwnd, desired):
                    self._enforced_hwnd_state = (hwnd, desired)

    def stop(self) -> AirPlayRuntimeState:
        """Terminate UxPlay process cleanly."""
        self._stop_window_watcher()
        if self._proc is not None and self._proc.poll() is None:
            pid = self._proc.pid
            if sys.platform == "win32":
                with contextlib.suppress(Exception):
                    subprocess.run(
                        ["taskkill", "/T", "/F", "/PID", str(pid)],
                        capture_output=True,
                        timeout=4,
                        creationflags=WIN_NO_WINDOW,
                        check=False,
                    )
            with contextlib.suppress(Exception):
                self._proc.terminate()
                self._proc.wait(timeout=3)
            if self._proc.poll() is None:
                with contextlib.suppress(Exception):
                    self._proc.kill()
        if sys.platform == "win32":
            self._cleanup_orphaned_instances()
        if self._log_fh is not None:
            with contextlib.suppress(Exception):
                self._log_fh.close()
            self._log_fh = None
        self._proc = None
        self._video_hwnd_seen = False
        self.state.running = False
        self.state.client_connected = False
        self.state.pid = None
        return self.state

    @staticmethod
    def _find_video_hwnd(pid: int | None) -> int | None:
        """Find visible 'AirPlay Video Stream' HWND owned by UxPlay."""
        if sys.platform != "win32" or not pid:
            return None
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        matched: list[tuple[int, str]] = []
        enum_cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _cb(hwnd: int, _lp: int) -> bool:
            proc_id = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
            if proc_id.value != pid or not user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if "uxplay-windows" in buf.value.lower():
                return True
            rc = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rc))
            if (rc.right - rc.left) >= 240 and (rc.bottom - rc.top) >= 180:
                matched.append((hwnd, buf.value))
            return True

        user32.EnumWindows(enum_cb(_cb), 0)
        for hwnd, title in matched:
            if "airplay" in title.lower():
                return hwnd
        return matched[0][0] if matched else None

    @staticmethod
    def _apply_win32_window_mode(hwnd: int, fullscreen: bool) -> bool:
        """Switch an open Win32 D3D11 video window between borderless fullscreen and windowed."""
        if sys.platform != "win32":
            return False
        from ctypes import wintypes

        class _MonitorInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]

        gwl_style = -16
        gwl_exstyle = -20
        ws_visible = 0x10000000
        ws_popup = 0x80000000
        ws_overlappedwindow = 0x00CF0000
        ws_chrome = 0x00C40000 | 0x00030000 | 0x00080000  # CAPTION|THICKFRAME|MIN/MAX|SYSMENU
        ws_ex_chrome = 0x00000100 | 0x00000200  # WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE
        hwnd_top = 0
        hwnd_notopmost = -2
        swp_flags = 0x0020 | 0x0040 | 0x0200  # FRAMECHANGED | SHOWWINDOW | NOOWNERZORDER

        hmon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        mi = _MonitorInfo()
        mi.cbSize = ctypes.sizeof(_MonitorInfo)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            return False

        cur_style = user32.GetWindowLongPtrW(hwnd, gwl_style)
        cur_ex = user32.GetWindowLongPtrW(hwnd, gwl_exstyle)
        if fullscreen:
            new_style = (cur_style & ~ws_chrome) | ws_popup | ws_visible
            user32.SetWindowLongPtrW(hwnd, gwl_style, new_style)
            user32.SetWindowLongPtrW(hwnd, gwl_exstyle, cur_ex & ~ws_ex_chrome)
            rc = mi.rcMonitor
            user32.SetWindowPos(
                hwnd,
                hwnd_top,
                rc.left,
                rc.top,
                rc.right - rc.left,
                rc.bottom - rc.top,
                swp_flags,
            )
            return True

        new_style = (cur_style & ~ws_popup) | ws_overlappedwindow | ws_visible
        user32.SetWindowLongPtrW(hwnd, gwl_style, new_style)
        rc = mi.rcWork
        work_w = max(640, rc.right - rc.left)
        work_h = max(400, rc.bottom - rc.top)
        target_w = min(1280, int(work_w * 0.85))
        target_h = min(760, int(work_h * 0.85))
        pos_x = rc.left + (work_w - target_w) // 2
        pos_y = rc.top + (work_h - target_h) // 2
        user32.SetWindowPos(hwnd, hwnd_notopmost, pos_x, pos_y, target_w, target_h, swp_flags)
        return True

    def set_window_mode(self, fullscreen: bool) -> tuple[bool, bool, str]:
        """Apply fullscreen/borderless or windowed mode (live if streaming, else update config)."""
        self._last_fullscreen = fullscreen
        self.write_arguments(
            airplay_name=self.state.airplay_name,
            resolution_preset=self._last_resolution_preset,
            audio_enabled=self._last_audio_enabled,
            audio_sync_ms=self._last_audio_sync_ms,
            fullscreen=fullscreen,
        )
        mode_label = "Tam Ekran (Çerçevesiz)" if fullscreen else "Pencere Modu"

        if self._proc is not None and self._proc.poll() is None:
            hwnd = self._find_video_hwnd(self._proc.pid)
            if hwnd is not None and self._apply_win32_window_mode(hwnd, fullscreen):
                self._enforced_hwnd_state = (hwnd, fullscreen)
                return (
                    True,
                    True,
                    f"AirPlay Video Stream penceresi anında '{mode_label}' moduna alındı.",
                )
            # No active video window yet -> restart waiting receiver cleanly with new -fs flag
            st = self.start(
                airplay_name=self.state.airplay_name,
                resolution_preset=self._last_resolution_preset,
                audio_enabled=self._last_audio_enabled,
                audio_sync_ms=self._last_audio_sync_ms,
                fullscreen=fullscreen,
            )
            if st.running:
                return (
                    True,
                    False,
                    f"Alıcı '{mode_label}' ile yenilendi; bağlanınca bu modda açılır.",
                )
            return False, False, st.error or "AirPlay pencere modu güncellenemedi."

        return (
            True,
            False,
            f"Ekran modu '{mode_label}' olarak ayarlandı (AirPlay başlatıldığında uygulanır).",
        )

    def apply_live_audio_sync(self, audio_sync_ms: int) -> tuple[bool, str]:
        """Persist new -vsync offset and restart UxPlay seamlessly if currently running."""
        clamped = max(-900, min(900, int(audio_sync_ms)))
        self._last_audio_sync_ms = clamped
        if self._proc is not None and self._proc.poll() is None:
            st = self.start(
                airplay_name=self.state.airplay_name,
                resolution_preset=self._last_resolution_preset,
                audio_enabled=self._last_audio_enabled,
                audio_sync_ms=clamped,
                fullscreen=self._last_fullscreen,
            )
            if st.running:
                return True, f"Ses senkronu ({clamped:+d} ms) AirPlay alıcısına canlı uygulandı."
            return False, st.error or "Ses senkronu uygulanırken AirPlay alıcısı yenilenemedi."

        self.write_arguments(
            airplay_name=self.state.airplay_name,
            resolution_preset=self._last_resolution_preset,
            audio_enabled=self._last_audio_enabled,
            audio_sync_ms=clamped,
            fullscreen=self._last_fullscreen,
        )
        return True, f"Ses senkronu ({clamped:+d} ms) sonraki yayın için kaydedildi."
