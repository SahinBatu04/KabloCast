"""KabloCast FastAPI application: REST API, WebSocket media hub, and static SPA host."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .airplay.uxplay_manager import UxPlayManager
from .audio_sync import AudioSyncManager
from .config import Settings, get_settings
from .db import Database
from .models import (
    AirPlayWindowModeRequest,
    AirPlayWindowModeResult,
    AppleUsbDevice,
    AudioSyncStatus,
    AudioSyncUpdateRequest,
    BleBeaconStatus,
    BonjourActionResult,
    DashboardOverview,
    DriverActionRequest,
    DriverActionResult,
    MirrorSessionRecord,
    NetworkAdapterMetrics,
    QuickStartRequest,
    QuickStartResult,
    QuickStartStep,
    QuotaShieldStatus,
    QuotaShieldToggleRequest,
    ResolvedStrategy,
    StartMirrorRequest,
    StreamTelemetry,
    WifiDirectStartRequest,
    WifiDirectStatus,
)
from .network.ble_beacon import BleBeaconManager
from .network.quota_shield import QuotaShieldManager
from .network.wifi_direct import WifiDirectManager
from .stream.muxer import (
    encode_audio_config,
    encode_audio_pcm,
    encode_video_config,
    encode_video_frame,
)
from .stream.simulator import StreamSimulator
from .usb.driver_assistant import detect_apple_usb_devices, run_driver_assistant
from .usb.qvh_protocol import codec_string_from_sps
from .usb.usb_transport import QuickTimeUsbStreamer


def detect_network_context(
    usb_devices: list[AppleUsbDevice],
    adapters: list[NetworkAdapterMetrics],
) -> tuple[ResolvedStrategy, str]:
    """Choose the best zero-quota connection path based on live USB and LAN adapters."""
    up_adapters = [a for a in adapters if a.is_up and a.ipv4]

    for adp in up_adapters:
        ipv4 = adp.ipv4 or ""
        lower_name = adp.name.lower()
        if ipv4.startswith("172.20.10.") or "apple" in lower_name or "iphone" in lower_name:
            return ("usb_zero_quota", "iPhone USB Ağı Hazır • Sıfır Kota")

    for adp in up_adapters:
        ipv4 = adp.ipv4 or ""
        if not ipv4.startswith("172.20.10.") and not ipv4.startswith("192.168.137."):
            return ("lan_wifi", f"Yerel Ağ Hazır ({ipv4}) • Sıfır Mobil Kota")

    if usb_devices:
        return (
            "usb_zero_quota",
            f"{usb_devices[0].model_hint} Takılı • Kablolu Sıfır Kota Önerilir",
        )

    return (
        "wifi_direct",
        "Wi-Fi Yok • Doğrudan Kablosuz Köprü (Wi-Fi Direct) Önerilir",
    )


class StreamOrchestrator:
    """Coordinates active mirroring engine, WebSocket clients, and SQLite sessions."""

    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.uxplay = UxPlayManager(settings.uxplay_dir)
        self.wifi_direct = WifiDirectManager()
        self.ble_beacon = BleBeaconManager()
        self.quota_shield = QuotaShieldManager()
        self.audio_sync = AudioSyncManager(db)

        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._simulator: StreamSimulator | None = None
        self._usb_streamer: QuickTimeUsbStreamer | None = None
        self._worker_task: asyncio.Task[None] | None = None

        self._mode: str = "idle"
        self._device_name: str = "Bağlı cihaz yok"
        self._codec: str = "H.264"
        self._resolution: str = "1920x1080"
        self._active_session_id: int | None = None
        self._started_at: float = 0.0
        self._first_data_at: float | None = None
        self._bytes_received: int = 0
        self._window_bytes: int = 0
        self._window_frames: int = 0
        self._window_start: float = time.monotonic()
        self._fps: float = 0.0
        self._bitrate_mbps: float = 0.0
        self._latency_ms: float = 0.0
        self._audio_active: bool = False
        self._last_error: str | None = None
        self._cached_video_config: bytes | None = None
        self._cached_audio_config: bytes | None = encode_audio_config(48000, 2, 16)
        self._last_sps: bytes = b""

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def register_ws(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        if self._cached_video_config:
            await ws.send_bytes(self._cached_video_config)
        if self._cached_audio_config:
            await ws.send_bytes(self._cached_audio_config)

    def unregister_ws(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def _broadcast(self, packet: bytes) -> None:
        if not self._clients:
            return
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_bytes(packet)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    def _record_frame_stats(self, byte_count: int, is_video: bool) -> None:
        now = time.monotonic()
        if self._first_data_at is None and byte_count > 0:
            self._first_data_at = now
            if self._mode == "usb_quicktime" and self._latency_ms == 0.0:
                self._latency_ms = 12.0
        self._bytes_received += byte_count
        self._window_bytes += byte_count
        if is_video:
            self._window_frames += 1
        elapsed = now - self._window_start
        if elapsed >= 0.8:
            self._fps = round(self._window_frames / elapsed, 1)
            self._bitrate_mbps = round((self._window_bytes * 8.0) / (elapsed * 1_000_000.0), 2)
            self._window_bytes = 0
            self._window_frames = 0
            self._window_start = now

    def telemetry(self) -> StreamTelemetry:
        if self._mode == "airplay_uxplay":
            st = self.uxplay.poll()
            if not st.running and self._active_session_id is not None:
                self._finalize_db_session()
                self._mode = "idle"
            elif st.running:
                self._codec = st.codec
                self._resolution = st.resolution
                if st.fps > 0:
                    self._fps = st.fps
                self._device_name = st.client_name
                if st.error:
                    self._last_error = st.error

        # Estimated mobile hotspot MB saved only while media frames/clients are actively streaming
        if self._mode == "airplay_uxplay":
            if self.uxplay.state.client_connected:
                if self._first_data_at is None:
                    self._first_data_at = time.monotonic()
                active_sec = max(0.0, time.monotonic() - self._first_data_at)
            else:
                self._first_data_at = None
                active_sec = 0.0
        elif (
            self._mode in ("usb_quicktime", "simulator")
            and self._first_data_at is not None
            and self._bytes_received > 0
        ):
            active_sec = max(0.0, time.monotonic() - self._first_data_at)
        else:
            active_sec = 0.0
        saved_mb = active_sec * self.settings.default_hotspot_mbps / 8.0

        return StreamTelemetry(
            active=self._mode != "idle",
            mode=self._mode,  # type: ignore[arg-type]
            device_name=self._device_name,
            codec=self._codec,
            resolution=self._resolution,
            fps=self._fps,
            bitrate_mbps=self._bitrate_mbps,
            latency_ms=self._latency_ms,
            bytes_received=self._bytes_received,
            estimated_saved_mb=round(saved_mb, 2),
            audio_active=self._audio_active,
            last_error=self._last_error,
        )

    def _finalize_db_session(self) -> None:
        if self._active_session_id is None:
            return
        dur = max(0.0, time.monotonic() - self._started_at)
        if self._bytes_received > 0 and self._first_data_at is not None:
            saved_sec = max(0.0, time.monotonic() - self._first_data_at)
            saved_mb = round(saved_sec * self.settings.default_hotspot_mbps / 8.0, 2)
        elif self._mode == "airplay_uxplay" and self.uxplay.state.client_connected:
            saved_mb = round(dur * self.settings.default_hotspot_mbps / 8.0, 2)
        else:
            saved_mb = 0.0
        self.db.finish_session(
            session_id=self._active_session_id,
            duration_sec=dur,
            avg_fps=self._fps,
            bytes_received=self._bytes_received,
            estimated_saved_mb=saved_mb,
            resolution=self._resolution,
            video_codec=self._codec,
        )
        self._active_session_id = None

    async def start(self, req: StartMirrorRequest) -> StreamTelemetry:
        await self.stop()
        self._last_error = None
        self._bytes_received = 0
        self._first_data_at = None
        self._window_bytes = 0
        self._window_frames = 0
        self._window_start = time.monotonic()
        self._started_at = time.monotonic()
        self._fps = 0.0
        self._bitrate_mbps = 0.0
        self._audio_active = req.audio_enabled

        if req.mode == "simulator":
            self._mode = "simulator"
            self._device_name = f"{req.device_label} (Canlı Simülasyon)"
            self._codec = "H.264 (Baseline)"
            self._resolution = "960x540"
            self._latency_ms = 14.0
            self._active_session_id = self.db.start_session(
                "simulator", self._device_name, req.device_label, self._codec, self._resolution
            )
            sim = StreamSimulator(width=960, height=540, fps=30)
            self._simulator = sim

            async def on_cfg(codec: str, width: int, height: int, fps: int) -> None:
                pkt = encode_video_config(codec, width, height, fps)
                self._cached_video_config = pkt
                await self._broadcast(pkt)
                if self._cached_audio_config and req.audio_enabled:
                    await self._broadcast(self._cached_audio_config)

            async def on_vid(payload: bytes, is_key: bool, pts_us: int) -> None:
                self._record_frame_stats(len(payload), True)
                await self._broadcast(encode_video_frame(payload, pts_us, is_key))

            async def on_aud(pcm: bytes, pts_us: int) -> None:
                if not req.audio_enabled:
                    return
                self._record_frame_stats(len(pcm), False)
                await self._broadcast(encode_audio_pcm(pcm, pts_us))

            self._worker_task = asyncio.create_task(sim.run(on_cfg, on_vid, on_aud))
            self._worker_task.add_done_callback(self._on_worker_done)
            return self.telemetry()

        if req.mode == "airplay_uxplay":
            st = self.uxplay.start(
                airplay_name=req.airplay_name,
                resolution_preset=req.resolution_preset,
                audio_enabled=req.audio_enabled,
                audio_sync_ms=req.audio_sync_ms,
                fullscreen=req.fullscreen,
            )
            if not st.running:
                self._last_error = st.error or "AirPlay 2 sunucusu başlatılamadı."
                self._mode = "idle"
                return self.telemetry()
            self._mode = "airplay_uxplay"
            self._device_name = st.client_name
            self._codec = st.codec
            self._resolution = st.resolution
            self._latency_ms = 18.0
            self._active_session_id = self.db.start_session(
                "airplay_uxplay", req.airplay_name, "AirPlay 2", self._codec, self._resolution
            )
            return self.telemetry()

        if req.mode == "usb_quicktime":
            self._mode = "usb_quicktime"
            self._device_name = f"{req.device_label} (Kablolu USB)"
            self._codec = "H.264 (QuickTime USB)"
            self._resolution = "1920x1080"
            self._latency_ms = 0.0
            self._active_session_id = self.db.start_session(
                "usb_quicktime", self._device_name, req.device_label, self._codec, self._resolution
            )

            def on_usb_video(
                annex_b: bytes,
                is_key: bool,
                pts_us: int,
                sps: bytes,
                _pps: bytes,
                width: int,
                height: int,
            ) -> None:
                if sps and sps != self._last_sps:
                    self._last_sps = sps
                    self._resolution = f"{width}x{height}"
                    cfg_pkt = encode_video_config(codec_string_from_sps(sps), width, height, 60)
                    self._cached_video_config = cfg_pkt
                    if self._loop:
                        asyncio.run_coroutine_threadsafe(self._broadcast(cfg_pkt), self._loop)
                        if self._cached_audio_config and req.audio_enabled:
                            asyncio.run_coroutine_threadsafe(
                                self._broadcast(self._cached_audio_config), self._loop
                            )
                self._record_frame_stats(len(annex_b), True)
                if self._loop:
                    asyncio.run_coroutine_threadsafe(
                        self._broadcast(encode_video_frame(annex_b, pts_us, is_key)), self._loop
                    )

            def on_usb_audio(pcm: bytes, pts_us: int) -> None:
                if not req.audio_enabled:
                    return
                self._record_frame_stats(len(pcm), False)
                if self._loop:
                    asyncio.run_coroutine_threadsafe(
                        self._broadcast(encode_audio_pcm(pcm, pts_us)), self._loop
                    )

            def on_usb_err(err: str) -> None:
                self._last_error = err
                self._mode = "idle"

            def on_usb_status(msg: str) -> None:
                if self._mode == "usb_quicktime" and self._bytes_received == 0:
                    self._last_error = msg

            streamer = QuickTimeUsbStreamer(
                on_video=on_usb_video,
                on_audio=on_usb_audio,
                on_error=on_usb_err,
                serial=req.device_serial,
                on_status=on_usb_status,
            )
            self._usb_streamer = streamer
            self._worker_task = asyncio.create_task(streamer.start())
            self._worker_task.add_done_callback(self._on_worker_done)
            return self.telemetry()

        raise HTTPException(status_code=400, detail="Desteklenmeyen yansıtma modu.")

    def _on_worker_done(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                self._last_error = f"Akış motoru hatası: {exc}"
                self._mode = "idle"
        if self._mode == "idle" and self._active_session_id is not None:
            self._finalize_db_session()

    async def stop(self) -> StreamTelemetry:
        if self._simulator is not None:
            self._simulator.request_stop()
            self._simulator = None
        if self._usb_streamer is not None:
            self._usb_streamer.request_stop()
            self._usb_streamer = None
        if self._worker_task is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._worker_task, timeout=2.0)
            self._worker_task = None
        if self._mode == "airplay_uxplay":
            self.uxplay.stop()

        self._finalize_db_session()
        self._mode = "idle"
        self._first_data_at = None
        self._fps = 0.0
        self._bitrate_mbps = 0.0
        self._latency_ms = 0.0
        self._cached_video_config = None
        self._last_sps = b""
        return self.telemetry()

    async def shutdown(self) -> None:
        await self.stop()
        self.wifi_direct.stop()
        self.ble_beacon.stop()

    async def quickstart(self, req: QuickStartRequest) -> QuickStartResult:
        """Run one-click preflight checks, auto A/V sync resolution, and AirPlay startup."""
        steps: list[QuickStartStep] = []
        usb_devices = detect_apple_usb_devices()
        qs_status = self.quota_shield.status()
        adapters = qs_status.adapters
        detected_strategy, _ = detect_network_context(usb_devices, adapters)
        selected_strategy: ResolvedStrategy = (
            detected_strategy
            if req.connection_strategy == "auto"
            else req.connection_strategy
        )

        # Step 1: Ensure connected iPhone/iPad uses Apple standard composite driver (usbccgp)
        if not usb_devices:
            steps.append(
                QuickStartStep(
                    id="usb_driver",
                    label="iPhone / iPad USB Kontrolü",
                    status="skipped",
                    detail="USB kablosu algılanmadı; kablosuz AirPlay 2 akışına geçiliyor.",
                )
            )
        else:
            needs_restore = [d for d in usb_devices if d.driver_mode != "apple_usbccgp"]
            if not needs_restore:
                steps.append(
                    QuickStartStep(
                        id="usb_driver",
                        label="iPhone / iPad USB Kontrolü",
                        status="done",
                        detail=f"{usb_devices[0].model_hint} Apple standart sürücüsü ile hazır.",
                    )
                )
            else:
                script = self.settings.project_root / "scripts" / "usb_driver_assistant.ps1"
                restore_ok = True
                restore_msg = ""
                for dev in needs_restore:
                    res = run_driver_assistant(
                        script,
                        self.settings.driver_backup_dir,
                        dev.instance_id,
                        "restore_apple",
                    )
                    if res.ok and res.backup_path:
                        self.db.record_driver_backup(
                            dev.instance_id, "restore_apple", res.backup_path
                        )
                    if not res.ok:
                        restore_ok = False
                    restore_msg = res.message
                steps.append(
                    QuickStartStep(
                        id="usb_driver",
                        label="Apple Sürücüsüne Dönüş",
                        status="done" if restore_ok else "warning",
                        detail=restore_msg
                        or (
                            "Cihaz Apple standart USB moduna döndürüldü."
                            if restore_ok
                            else "Apple moduna dönülemedi; UAC izni gerekebilir."
                        ),
                    )
                )

        # Step 2: Ensure Bonjour mDNS discovery service is running
        if self.uxplay.bonjour_ready():
            steps.append(
                QuickStartStep(
                    id="bonjour",
                    label="Bonjour Keşif Servisi",
                    status="done",
                    detail="Apple mDNS keşif servisi aktif.",
                )
            )
        else:
            bj_ok, bj_msg = self.uxplay.install_bonjour()
            if not self.uxplay.bonjour_ready():
                steps.append(
                    QuickStartStep(
                        id="bonjour",
                        label="Bonjour Keşif Servisi",
                        status="failed",
                        detail=bj_msg,
                    )
                )
                return QuickStartResult(
                    ok=False,
                    selected_strategy=selected_strategy,
                    applied_sync_ms=180,
                    sync_source="auto",
                    audio_output_label="Sistem Hoparlörü",
                    steps=steps,
                    user_instruction=bj_msg,
                    stream=self.telemetry(),
                )
            steps.append(
                QuickStartStep(
                    id="bonjour",
                    label="Bonjour Keşif Servisi",
                    status="done" if bj_ok else "warning",
                    detail=bj_msg,
                )
            )

        # Step 3: Prepare chosen zero-quota network bridge
        if selected_strategy == "usb_zero_quota":
            if not qs_status.active:
                qs_status = self.quota_shield.toggle(True)
            steps.append(
                QuickStartStep(
                    id="network",
                    label="Sıfır Kota Kablolu Ağ & Kalkan",
                    status="done" if qs_status.active else "warning",
                    detail=(
                        "Kota Kalkanı aktif; arka plan Windows/OneDrive trafiği kesildi."
                        if qs_status.active
                        else (
                            qs_status.last_message
                            or "Kota Kalkanı açılamadı; USB üzerinden devam ediliyor."
                        )
                    ),
                )
            )
        elif selected_strategy == "lan_wifi":
            uses_hotspot = any(
                a.is_up and a.ipv4 and a.ipv4.startswith("172.20.10.") for a in adapters
            )
            if uses_hotspot:
                if not qs_status.active:
                    qs_status = self.quota_shield.toggle(True)
                steps.append(
                    QuickStartStep(
                        id="network",
                        label="Hotspot Kota Kalkanı",
                        status="done" if qs_status.active else "warning",
                        detail=(
                            "Hotspot algılandı ve Kota Kalkanı otomatik etkinleştirildi."
                            if qs_status.active
                            else (qs_status.last_message or "Hotspot kalkanı UAC bekliyor.")
                        ),
                    )
                )
            else:
                steps.append(
                    QuickStartStep(
                        id="network",
                        label="Yerel Wi-Fi Doğrulaması",
                        status="done",
                        detail="Yerel Wi-Fi ağı aktif; mobil internet tüketilmez.",
                    )
                )
        else:  # wifi_direct
            wfd = self.wifi_direct.status()
            if not wfd.active:
                wfd = self.wifi_direct.start()
            if wfd.active and not wfd.error:
                self.ble_beacon.start(ipv4=wfd.local_ip)
                steps.append(
                    QuickStartStep(
                        id="network",
                        label="Wi-Fi Direct Köprüsü",
                        status="done",
                        detail=f"{wfd.ssid} ve BLE keşif sinyali hazır.",
                    )
                )
            else:
                steps.append(
                    QuickStartStep(
                        id="network",
                        label="Wi-Fi Direct Köprüsü",
                        status="warning",
                        detail=wfd.error or "Wi-Fi Direct köprüsü başlatılamadı.",
                    )
                )

        # Step 4: Resolve optimal A/V sync for current Windows audio output
        device_key = usb_devices[0].serial if usb_devices else "default_ios"
        sync_status = self.audio_sync.resolve_status(
            device_key=device_key,
            strategy=selected_strategy,
            resolution_preset=req.resolution_preset,
        )
        if req.sync_override_ms is not None:
            applied_sync_ms = req.sync_override_ms
            sync_source: str = "override"
            sync_mode_note = "anlık değer"
        elif sync_status.mode == "manual":
            applied_sync_ms = sync_status.effective_ms
            sync_source = "saved_manual"
            sync_mode_note = "kayıtlı profil"
        else:
            applied_sync_ms = sync_status.effective_ms
            sync_source = "auto"
            sync_mode_note = "otomatik kalibre"

        steps.append(
            QuickStartStep(
                id="audio_sync",
                label="Otomatik Ses-Görüntü Senkronu",
                status="done",
                detail=(
                    f"{sync_status.output_label} için {applied_sync_ms:+d} ms "
                    f"({sync_mode_note})."
                ),
            )
        )

        # Step 5: Launch D3D11 + WASAPI2 AirPlay 2 receiver
        stream_tel = await self.start(
            StartMirrorRequest(
                mode="airplay_uxplay",
                airplay_name=req.airplay_name,
                resolution_preset=req.resolution_preset,
                audio_enabled=req.audio_enabled,
                audio_sync_ms=applied_sync_ms,
                fullscreen=req.fullscreen,
            )
        )
        if not stream_tel.active:
            err_detail = stream_tel.last_error or "AirPlay 2 alıcısı başlatılamadı."
            steps.append(
                QuickStartStep(
                    id="airplay",
                    label="AirPlay 2 Alıcısı",
                    status="failed",
                    detail=err_detail,
                )
            )
            return QuickStartResult(
                ok=False,
                selected_strategy=selected_strategy,
                applied_sync_ms=applied_sync_ms,
                sync_source=sync_source,  # type: ignore[arg-type]
                audio_output_label=sync_status.output_label,
                steps=steps,
                user_instruction=err_detail,
                stream=stream_tel,
            )

        steps.append(
            QuickStartStep(
                id="airplay",
                label="AirPlay 2 Alıcısı",
                status="done",
                detail=f"'{req.airplay_name}' yayına hazır ({req.resolution_preset}).",
            )
        )

        if selected_strategy == "usb_zero_quota":
            instruction = (
                "iPhone'da Kişisel Erişim Noktası (Yalnızca USB) açıkken Denetim Merkezi → "
                f"Ekran Yansıtma → '{req.airplay_name}' seçin."
            )
        elif selected_strategy == "wifi_direct":
            instruction = (
                "iPhone kamerasıyla QR kodu okutun (gerekirse Yönlendirici alanını boş bırakın), "
                f"ardından Denetim Merkezi → Ekran Yansıtma → '{req.airplay_name}' seçin."
            )
        else:
            instruction = (
                f"iPhone'unuzda Denetim Merkezi → Ekran Yansıtma → '{req.airplay_name}' "
                "seçin; video ve ses otomatik açılacaktır."
            )

        return QuickStartResult(
            ok=True,
            selected_strategy=selected_strategy,
            applied_sync_ms=applied_sync_ms,
            sync_source=sync_source,  # type: ignore[arg-type]
            audio_output_label=sync_status.output_label,
            steps=steps,
            user_instruction=instruction,
            stream=stream_tel,
        )


def create_app(custom_settings: Settings | None = None) -> FastAPI:
    """Application factory for KabloCast."""
    settings = custom_settings or get_settings()
    db = Database(settings.db_path)
    orchestrator = StreamOrchestrator(settings, db)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        orchestrator.bind_loop(asyncio.get_running_loop())
        yield
        await orchestrator.shutdown()

    app = FastAPI(title="KabloCast API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.orchestrator = orchestrator

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8765"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def rfc9457_http_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "İstek Hatası",
                "status": exc.status_code,
                "detail": str(exc.detail),
                "instance": str(request.url.path),
            },
        )

    @app.exception_handler(ValueError)
    async def rfc9457_value_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Doğrulama Hatası",
                "status": 400,
                "detail": str(exc),
                "instance": str(request.url.path),
            },
        )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": settings.app_name}

    @app.get("/api/overview", response_model=DashboardOverview)
    def overview() -> DashboardOverview:
        usb_devices = detect_apple_usb_devices()
        qs_status = orchestrator.quota_shield.status()
        rec_strategy, net_summary = detect_network_context(usb_devices, qs_status.adapters)
        device_key = usb_devices[0].serial if usb_devices else "default_ios"
        sync_status = orchestrator.audio_sync.resolve_status(
            device_key=device_key,
            strategy=rec_strategy,
            resolution_preset=orchestrator.uxplay._last_resolution_preset,
        )
        return DashboardOverview(
            stream=orchestrator.telemetry(),
            usb_devices=usb_devices,
            wifi_direct=orchestrator.wifi_direct.status(),
            quota_shield=qs_status,
            ble_beacon=orchestrator.ble_beacon.status(),
            uxplay_installed=orchestrator.uxplay.is_installed,
            bonjour_ready=orchestrator.uxplay.bonjour_ready(),
            recent_sessions=db.list_sessions(limit=12),
            total_saved_mb=db.total_saved_mb(),
            audio_sync=sync_status,
            recommended_strategy=rec_strategy,
            network_summary=net_summary,
        )

    @app.post("/api/quickstart", response_model=QuickStartResult)
    async def quickstart(req: QuickStartRequest) -> QuickStartResult:
        return await orchestrator.quickstart(req)

    @app.get("/api/audio-sync", response_model=AudioSyncStatus)
    def get_audio_sync(
        device_key: str | None = None,
        resolution_preset: Literal["1080p", "1440p", "native"] = "1080p",
    ) -> AudioSyncStatus:
        usb_devices = detect_apple_usb_devices()
        adapters = orchestrator.quota_shield.sample_adapters()
        rec_strategy, _ = detect_network_context(usb_devices, adapters)
        resolved_device = device_key or (usb_devices[0].serial if usb_devices else "default_ios")
        return orchestrator.audio_sync.resolve_status(
            device_key=resolved_device,
            strategy=rec_strategy,
            resolution_preset=resolution_preset,
        )

    @app.post("/api/audio-sync", response_model=AudioSyncStatus)
    def update_audio_sync(req: AudioSyncUpdateRequest) -> AudioSyncStatus:
        usb_devices = detect_apple_usb_devices()
        adapters = orchestrator.quota_shield.sample_adapters()
        rec_strategy, _ = detect_network_context(usb_devices, adapters)
        fallback_key = usb_devices[0].serial if usb_devices else "default_ios"
        updated = orchestrator.audio_sync.update_profile(
            req=req,
            fallback_device_key=fallback_key,
            strategy=rec_strategy,
        )
        if req.apply_live:
            orchestrator.uxplay.apply_live_audio_sync(updated.effective_ms)
        return updated

    @app.post("/api/airplay/install-bonjour", response_model=BonjourActionResult)
    def install_bonjour_service() -> BonjourActionResult:
        ok, msg = orchestrator.uxplay.install_bonjour()
        return BonjourActionResult(
            ok=ok,
            bonjour_ready=orchestrator.uxplay.bonjour_ready(),
            message=msg,
        )

    @app.post("/api/airplay/window-mode", response_model=AirPlayWindowModeResult)
    def set_airplay_window_mode(req: AirPlayWindowModeRequest) -> AirPlayWindowModeResult:
        ok, live_applied, msg = orchestrator.uxplay.set_window_mode(req.fullscreen)
        return AirPlayWindowModeResult(
            ok=ok,
            fullscreen=req.fullscreen,
            live_applied=live_applied,
            message=msg,
        )

    @app.get("/api/devices", response_model=list[AppleUsbDevice], tags=["USB"])
    def list_devices_alias() -> list[AppleUsbDevice]:
        return detect_apple_usb_devices()

    @app.get("/api/usb/devices", response_model=list[AppleUsbDevice])
    def list_usb_devices() -> list[AppleUsbDevice]:
        return detect_apple_usb_devices()

    @app.post("/api/usb/driver", response_model=DriverActionResult)
    def manage_usb_driver(req: DriverActionRequest) -> DriverActionResult:
        script = settings.project_root / "scripts" / "usb_driver_assistant.ps1"
        res = run_driver_assistant(script, settings.driver_backup_dir, req.instance_id, req.action)
        if res.ok and res.backup_path:
            db.record_driver_backup(req.instance_id, req.action, res.backup_path)
        return res

    @app.post("/api/stream/start", response_model=StreamTelemetry)
    async def start_stream(req: StartMirrorRequest) -> StreamTelemetry:
        return await orchestrator.start(req)

    @app.post("/api/stream/stop", response_model=StreamTelemetry)
    async def stop_stream() -> StreamTelemetry:
        return await orchestrator.stop()

    @app.post("/api/wifi-direct/start", response_model=WifiDirectStatus)
    def start_wifi_direct(req: WifiDirectStartRequest) -> WifiDirectStatus:
        return orchestrator.wifi_direct.start(ssid=req.ssid, passphrase=req.passphrase)

    @app.post("/api/wifi-direct/stop", response_model=WifiDirectStatus)
    def stop_wifi_direct() -> WifiDirectStatus:
        return orchestrator.wifi_direct.stop()

    @app.post("/api/ble/start", response_model=BleBeaconStatus)
    def start_ble(port: int = 7000) -> BleBeaconStatus:
        wfd_ip = orchestrator.wifi_direct.status().local_ip
        return orchestrator.ble_beacon.start(ipv4=wfd_ip, port=port)

    @app.post("/api/ble/stop", response_model=BleBeaconStatus)
    def stop_ble() -> BleBeaconStatus:
        return orchestrator.ble_beacon.stop()

    @app.post("/api/quota-shield/toggle", response_model=QuotaShieldStatus)
    def toggle_quota_shield(req: QuotaShieldToggleRequest) -> QuotaShieldStatus:
        return orchestrator.quota_shield.toggle(req.enable, req.adapter_name)

    @app.get("/api/sessions", response_model=list[MirrorSessionRecord])
    def list_sessions() -> list[MirrorSessionRecord]:
        return db.list_sessions(limit=25)

    @app.websocket("/ws/stream")
    async def ws_stream(websocket: WebSocket) -> None:
        await orchestrator.register_ws(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            orchestrator.unregister_ws(websocket)
        except Exception:
            orchestrator.unregister_ws(websocket)

    @app.websocket("/ws/telemetry")
    async def ws_telemetry(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(orchestrator.telemetry().model_dump())
                await asyncio.sleep(0.6)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    dist_dir = settings.frontend_dist_dir
    if dist_dir.exists() and (dist_dir / "index.html").exists():
        assets_dir = dist_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}")
        def serve_spa(full_path: str) -> FileResponse:
            candidate = (dist_dir / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(dist_dir.resolve()):
                return FileResponse(candidate)
            return FileResponse(dist_dir / "index.html")

    return app


app = create_app()
