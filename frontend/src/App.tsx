import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, MonitorPlay, Moon, RefreshCw, Settings, Sun } from "lucide-react";
import { GuideDialog } from "./components/GuideDialog";
import { SettingsDrawer } from "./components/SettingsDrawer";
import { type RotationDeg, VideoStage } from "./components/VideoStage";
import {
  detectInitialLocale,
  detectInitialTheme,
  formatActiveInstruction,
  type Locale,
  MESSAGES,
  type ThemeMode,
} from "./i18n";
import { api } from "./lib/api";
import { type DecoderMetrics, KabloStreamClient } from "./lib/streamClient";
import type {
  AppleUsbDevice,
  AudioSyncStatus,
  BleBeaconStatus,
  ConnectionStrategy,
  DriverAction,
  MirrorSessionRecord,
  QuickStartResult,
  QuotaShieldStatus,
  ResolutionPreset,
  ResolvedStrategy,
  StreamTelemetry,
  WifiDirectStatus,
} from "./types/api";

const INITIAL_TELEMETRY: StreamTelemetry = {
  active: false,
  mode: "idle",
  device_name: "",
  codec: "H.264",
  resolution: "1920x1080",
  fps: 0,
  bitrate_mbps: 0,
  latency_ms: 0,
  bytes_received: 0,
  estimated_saved_mb: 0,
  audio_active: false,
  last_error: null,
};

const INITIAL_DECODER: DecoderMetrics = {
  decodedFrames: 0,
  droppedFrames: 0,
  videoWidth: 0,
  videoHeight: 0,
  wsConnected: false,
  decoderReady: false,
  lastClientError: null,
};

const INITIAL_AUDIO_SYNC: AudioSyncStatus = {
  endpoint_id: "default_speaker",
  output_label: "Speaker",
  output_kind: "speaker",
  device_key: "default_ios",
  profile_key: "default_speaker::default_ios",
  mode: "auto",
  recommended_ms: 180,
  effective_ms: 180,
  explanation: "",
};

export function App() {
  const [locale, setLocale] = useState<Locale>(() => detectInitialLocale());
  const [theme, setTheme] = useState<ThemeMode>(() => detectInitialTheme());
  const t = MESSAGES[locale];

  const [telemetry, setTelemetry] = useState<StreamTelemetry>(INITIAL_TELEMETRY);
  const [decoderMetrics, setDecoderMetrics] = useState<DecoderMetrics>(INITIAL_DECODER);
  const [usbDevices, setUsbDevices] = useState<AppleUsbDevice[]>([]);
  const [wifiDirect, setWifiDirect] = useState<WifiDirectStatus>({
    supported: true,
    active: false,
    ssid: "DIRECT-KabloCast",
    passphrase: "",
    local_ip: null,
    qr_svg_data_uri: null,
    manual_ip_guide: {},
    error: null,
  });
  const [bleBeacon, setBleBeacon] = useState<BleBeaconStatus>({
    supported: true,
    active: false,
    target_ip: null,
    port: 7000,
    error: null,
  });
  const [quotaShield, setQuotaShield] = useState<QuotaShieldStatus>({
    active: false,
    protected_adapter: null,
    active_rule_count: 0,
    blocked_apps_summary: [],
    adapters: [],
    last_message: null,
  });
  const [uxplayInstalled, setUxplayInstalled] = useState(false);
  const [bonjourReady, setBonjourReady] = useState(true);
  const [recentSessions, setRecentSessions] = useState<MirrorSessionRecord[]>([]);
  const [totalSavedMb, setTotalSavedMb] = useState(0);
  const [audioSync, setAudioSync] = useState<AudioSyncStatus>(INITIAL_AUDIO_SYNC);
  const [recommendedStrategy, setRecommendedStrategy] =
    useState<ResolvedStrategy>("lan_wifi");

  // Preferences
  const [connectionStrategy, setConnectionStrategy] = useState<ConnectionStrategy>("auto");
  const [airplayName, setAirplayName] = useState("KabloCast");
  const [resPreset, setResPreset] = useState<ResolutionPreset>("1080p");
  const [audioEnabled, setAudioEnabled] = useState(true);
  const [airplayFullscreen, setAirplayFullscreen] = useState(true);
  const [quickStartResult, setQuickStartResult] = useState<QuickStartResult | null>(null);

  // Canvas controls
  const [rotation, setRotation] = useState<RotationDeg>(0);
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(0.85);
  const [lipSyncMs, setLipSyncMs] = useState(0);

  // Dialogs & Notices
  const [guideOpen, setGuideOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stageWrapperRef = useRef<HTMLDivElement | null>(null);
  const streamClientRef = useRef<KabloStreamClient | null>(null);
  const rotationRef = useRef<RotationDeg>(0);
  rotationRef.current = rotation;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem("kablocast_theme", theme);
    } catch {
      // Ignore storage error
    }
  }, [theme]);

  useEffect(() => {
    document.documentElement.lang = locale;
    document.title =
      locale === "tr"
        ? "KabloCast — Sıfır Kota iPhone & iPad Yansıtma"
        : "KabloCast — Zero-Quota iPhone & iPad Mirroring";
    try {
      window.localStorage.setItem("kablocast_lang", locale);
    } catch {
      // Ignore storage error
    }
  }, [locale]);

  const drawVideoFrame = useCallback((frame: VideoFrame) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const deg = rotationRef.current;
    const swap = deg === 90 || deg === 270;
    const targetW = swap ? frame.displayHeight : frame.displayWidth;
    const targetH = swap ? frame.displayWidth : frame.displayHeight;
    if (canvas.width !== targetW || canvas.height !== targetH) {
      canvas.width = targetW;
      canvas.height = targetH;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.save();
    if (deg === 0) {
      ctx.drawImage(frame, 0, 0, targetW, targetH);
    } else {
      ctx.translate(targetW / 2, targetH / 2);
      ctx.rotate((deg * Math.PI) / 180);
      ctx.drawImage(
        frame,
        -frame.displayWidth / 2,
        -frame.displayHeight / 2,
        frame.displayWidth,
        frame.displayHeight
      );
    }
    ctx.restore();
  }, []);

  const refreshOverview = useCallback(async () => {
    try {
      const ov = await api.overview();
      setTelemetry(ov.stream);
      setUsbDevices(ov.usb_devices);
      setWifiDirect(ov.wifi_direct);
      setQuotaShield(ov.quota_shield);
      setBleBeacon(ov.ble_beacon);
      setUxplayInstalled(ov.uxplay_installed);
      setBonjourReady(ov.bonjour_ready);
      setRecentSessions(ov.recent_sessions);
      setTotalSavedMb(ov.total_saved_mb);
      if (ov.audio_sync) {
        setAudioSync(ov.audio_sync);
      }
      if (ov.recommended_strategy) {
        setRecommendedStrategy(ov.recommended_strategy);
      }
    } catch (err) {
      setNotice({
        kind: "err",
        text: err instanceof Error ? err.message : t.common.networkFallback,
      });
    }
  }, [t.common.networkFallback]);

  useEffect(() => {
    void refreshOverview();

    const client = new KabloStreamClient(drawVideoFrame, setDecoderMetrics);
    streamClientRef.current = client;
    client.connect();

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    let telemetryWs: WebSocket | null = null;
    let alive = true;
    const openTelemetryWs = () => {
      if (!alive) return;
      telemetryWs = new WebSocket(`${proto}//${window.location.host}/ws/telemetry`);
      telemetryWs.onmessage = (ev) => {
        try {
          const msg = JSON.parse(String(ev.data)) as StreamTelemetry;
          setTelemetry(msg);
        } catch {
          // Ignore malformed frame
        }
      };
      telemetryWs.onclose = () => {
        if (alive) {
          window.setTimeout(openTelemetryWs, 2000);
        }
      };
    };
    openTelemetryWs();

    const pollTimer = window.setInterval(() => {
      void refreshOverview();
    }, 8000);

    return () => {
      alive = false;
      window.clearInterval(pollTimer);
      telemetryWs?.close();
      client.disconnect();
    };
  }, [drawVideoFrame, refreshOverview]);

  useEffect(() => {
    streamClientRef.current?.setAudioControls(muted, volume, lipSyncMs);
  }, [muted, volume, lipSyncMs]);

  const runAction = async (key: string, task: () => Promise<void>) => {
    setBusyAction(key);
    setNotice(null);
    try {
      await task();
      await refreshOverview();
    } catch (err) {
      setNotice({
        kind: "err",
        text: err instanceof Error ? err.message : t.common.networkFallback,
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleQuickStart = () =>
    void runAction("quickstart", async () => {
      const res = await api.quickstart({
        connection_strategy: connectionStrategy,
        airplay_name: airplayName,
        resolution_preset: resPreset,
        audio_enabled: audioEnabled,
        fullscreen: airplayFullscreen,
      });
      setQuickStartResult(res);
      setTelemetry(res.stream);
      if (res.ok) {
        setNotice({
          kind: "ok",
          text: formatActiveInstruction(locale, res.selected_strategy, airplayName),
        });
      } else {
        setNotice({
          kind: "err",
          text: res.user_instruction,
        });
      }
    });

  const handleResolutionChange = (nextPreset: ResolutionPreset) => {
    setResPreset(nextPreset);
    void (async () => {
      try {
        const nextSync = await api.getAudioSync(nextPreset, usbDevices[0]?.serial);
        setAudioSync(nextSync);
      } catch {
        // Ignore transient glitch
      }
    })();
  };

  const handleSaveManualSync = (offsetMs: number) =>
    void runAction("save_sync", async () => {
      const updated = await api.updateAudioSync({
        mode: "manual",
        manual_offset_ms: offsetMs,
        device_key: usbDevices[0]?.serial ?? null,
        resolution_preset: resPreset,
        apply_live: true,
      });
      setAudioSync(updated);
      setNotice({ kind: "ok", text: t.prefs.savedToast });
    });

  const handleResetAutoSync = () =>
    void runAction("reset_sync", async () => {
      const updated = await api.updateAudioSync({
        mode: "auto",
        manual_offset_ms: audioSync.recommended_ms,
        device_key: usbDevices[0]?.serial ?? null,
        resolution_preset: resPreset,
        apply_live: true,
      });
      setAudioSync(updated);
      setNotice({ kind: "ok", text: t.prefs.resetToast });
    });

  const handleStartSimulator = (audio = true) =>
    void runAction("start_simulator", async () => {
      await streamClientRef.current?.unlockAudio();
      const next = await api.startStream({
        mode: "simulator",
        device_label: "iPhone",
        audio_enabled: audio,
      });
      setTelemetry(next);
    });

  const handleStartUsb = (serial: string | null = null, label = "iPhone", audio = true) =>
    void runAction("start_usb", async () => {
      await streamClientRef.current?.unlockAudio();
      const next = await api.startStream({
        mode: "usb_quicktime",
        device_serial: serial,
        device_label: label,
        audio_enabled: audio,
      });
      setTelemetry(next);
    });

  const handleStartAirplay = (
    name: string,
    resolution_preset: ResolutionPreset,
    audio_enabled: boolean,
    audio_sync_ms = audioSync.effective_ms,
    fullscreen = airplayFullscreen
  ) =>
    void runAction("start_airplay", async () => {
      const next = await api.startStream({
        mode: "airplay_uxplay",
        airplay_name: name,
        resolution_preset,
        audio_enabled,
        audio_sync_ms,
        fullscreen,
      });
      setTelemetry(next);
    });

  const handleStopStream = () =>
    void runAction("stop_stream", async () => {
      const next = await api.stopStream();
      setTelemetry(next);
      setDecoderMetrics((m) => ({ ...m, decodedFrames: 0 }));
    });

  const handleUsbDriverAction = (instanceId: string, action: DriverAction) =>
    void runAction("usb_driver", async () => {
      const res = await api.usbDriverAction(instanceId, action);
      setNotice({ kind: res.ok ? "ok" : "err", text: res.message });
    });

  const handleStartWifiDirect = (ssid: string, passphrase: string) =>
    void runAction("wfd_start", async () => {
      const st = await api.startWifiDirect(ssid, passphrase);
      setWifiDirect(st);
      if (st.error) setNotice({ kind: "err", text: st.error });
    });

  const handleStopWifiDirect = () =>
    void runAction("wfd_stop", async () => {
      const st = await api.stopWifiDirect();
      setWifiDirect(st);
    });

  const handleToggleBle = (enable: boolean) =>
    void runAction("ble_toggle", async () => {
      const st = enable ? await api.startBle(7000) : await api.stopBle();
      setBleBeacon(st);
      if (st.error) setNotice({ kind: "err", text: st.error });
    });

  const handleToggleQuotaShield = (enable: boolean, adapterName?: string) =>
    void runAction("quota_shield", async () => {
      const st = await api.toggleQuotaShield(enable, adapterName);
      setQuotaShield(st);
      if (st.last_message) setNotice({ kind: "ok", text: st.last_message });
    });

  const handleInstallBonjour = () =>
    void runAction("install_bonjour", async () => {
      const res = await api.installBonjour();
      setBonjourReady(res.bonjour_ready);
      setNotice({ kind: res.ok ? "ok" : "err", text: res.message });
    });

  const handleSetAirplayWindowMode = (fullscreen: boolean) => {
    setAirplayFullscreen(fullscreen);
    if (telemetry.mode === "airplay_uxplay") {
      void runAction("airplay_window_mode", async () => {
        const res = await api.setAirplayWindowMode(fullscreen);
        setNotice({ kind: res.ok ? "ok" : "err", text: res.message });
      });
    }
  };

  return (
    <div className="flex min-h-[100dvh] w-full max-w-full flex-col overflow-x-clip bg-[var(--kc-bg-canvas)] text-[var(--kc-ink-primary)]">
      {/* Minimal Consumer Top Header */}
      <header className="mx-auto flex h-16 w-full max-w-6xl shrink-0 items-center justify-between gap-2 px-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--kc-accent)] text-[var(--kc-accent-on)] shadow-sm">
            <MonitorPlay className="h-4 w-4" />
          </div>
          <h1 className="truncate text-base font-bold tracking-tight sm:text-lg">{t.appName}</h1>
        </div>

        <div className="flex items-center gap-1.5 sm:gap-2">
          {/* TR / EN Language Segmented Pill */}
          <div
            role="group"
            aria-label="Language"
            className="inline-flex rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] p-0.5"
          >
            {(["tr", "en"] as const).map((lang) => {
              const active = locale === lang;
              return (
                <button
                  key={lang}
                  type="button"
                  onClick={() => setLocale(lang)}
                  className={`rounded-lg px-2 py-1 text-[11px] font-bold uppercase ${
                    active
                      ? "bg-[var(--kc-accent)] text-[var(--kc-accent-on)]"
                      : "text-[var(--kc-ink-secondary)] hover:text-[var(--kc-ink-primary)]"
                  }`}
                >
                  {lang}
                </button>
              );
            })}
          </div>

          {/* Light / Dark Theme Toggle */}
          <button
            type="button"
            onClick={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
            aria-label={theme === "dark" ? t.header.toLight : t.header.toDark}
            title={theme === "dark" ? t.header.toLight : t.header.toDark}
            className="inline-flex items-center justify-center rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] p-2 text-[var(--kc-ink-secondary)] hover:border-[var(--kc-border-strong)] hover:text-[var(--kc-ink-primary)]"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>

          {/* Setup Guide */}
          <button
            type="button"
            onClick={() => setGuideOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] px-2.5 py-2 text-xs font-semibold text-[var(--kc-ink-primary)] hover:border-[var(--kc-border-strong)] sm:px-3"
          >
            <BookOpen className="h-3.5 w-3.5 text-[var(--kc-accent-ink)]" />
            <span className="hidden sm:inline">{t.header.guide}</span>
          </button>

          {/* Settings & Diagnostics */}
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            aria-label={t.header.settings}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] px-2.5 py-2 text-xs font-semibold text-[var(--kc-ink-primary)] hover:border-[var(--kc-border-strong)] sm:px-3"
          >
            <Settings className="h-3.5 w-3.5 text-[var(--kc-ink-secondary)]" />
            <span className="hidden sm:inline">{t.header.settings}</span>
          </button>

          <button
            type="button"
            onClick={() => void refreshOverview()}
            aria-label={t.header.refresh}
            className="hidden items-center justify-center rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] p-2 text-[var(--kc-ink-secondary)] hover:border-[var(--kc-border-strong)] hover:text-[var(--kc-ink-primary)] sm:inline-flex"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
      </header>

      {/* Dismissible Notice Banner */}
      {notice && (
        <div className="mx-auto w-full max-w-xl px-4">
          <div
            role="status"
            className={`mb-2 flex items-center justify-between gap-3 rounded-2xl border px-4 py-2.5 text-xs font-medium ${
              notice.kind === "err"
                ? "border-[var(--kc-signal-crimson)]/40 bg-[var(--kc-signal-crimson-soft)] text-[var(--kc-signal-crimson)]"
                : "border-[var(--kc-signal-emerald)]/40 bg-[var(--kc-signal-emerald-soft)] text-[var(--kc-signal-emerald)]"
            }`}
          >
            <span className="text-[var(--kc-ink-primary)]">{notice.text}</span>
            <button
              type="button"
              onClick={() => setNotice(null)}
              className="shrink-0 font-semibold text-[var(--kc-ink-primary)] underline"
            >
              {t.common.close}
            </button>
          </div>
        </div>
      )}

      {/* Centered Single-Focus Stage */}
      <main className="mx-auto flex w-full max-w-6xl min-h-0 flex-1 items-center justify-center px-4 pb-4 pt-2 sm:px-6">
        <VideoStage
          locale={locale}
          telemetry={telemetry}
          decoderMetrics={decoderMetrics}
          usbDevices={usbDevices}
          wifiDirect={wifiDirect}
          audioSync={audioSync}
          recommendedStrategy={recommendedStrategy}
          connectionStrategy={connectionStrategy}
          onConnectionStrategyChange={setConnectionStrategy}
          quickStartResult={quickStartResult}
          airplayName={airplayName}
          resPreset={resPreset}
          onResPresetChange={handleResolutionChange}
          airplayFullscreen={airplayFullscreen}
          onAirplayFullscreenChange={handleSetAirplayWindowMode}
          uxplayInstalled={uxplayInstalled}
          canvasRef={canvasRef}
          stageWrapperRef={stageWrapperRef}
          rotation={rotation}
          onRotate={() => setRotation((r) => (((r + 90) % 360) as RotationDeg))}
          muted={muted}
          volume={volume}
          lipSyncMs={lipSyncMs}
          onToggleMute={() => {
            void streamClientRef.current?.unlockAudio();
            setMuted((m) => !m);
          }}
          onVolumeChange={(v) => {
            void streamClientRef.current?.unlockAudio();
            if (muted && v > 0) setMuted(false);
            setVolume(v);
          }}
          onLipSyncChange={setLipSyncMs}
          onQuickStart={handleQuickStart}
          onSaveManualSync={handleSaveManualSync}
          onResetAutoSync={handleResetAutoSync}
          onStopStream={handleStopStream}
          busyAction={busyAction}
        />
      </main>

      <footer className="mx-auto flex w-full max-w-6xl shrink-0 flex-wrap items-center justify-center gap-x-2 gap-y-1 px-4 pb-4 pt-1 text-center text-[11px] text-[var(--kc-ink-muted)] sm:px-6">
        <span className="font-mono-num font-semibold text-[var(--kc-ink-secondary)]">
          {t.footer.version}
        </span>
        <span aria-hidden="true">•</span>
        <span className="font-mono-num">{t.footer.engine}</span>
        <span aria-hidden="true">•</span>
        <span>{t.footer.tagline}</span>
      </footer>

      <GuideDialog open={guideOpen} locale={locale} onClose={() => setGuideOpen(false)} />

      <SettingsDrawer
        open={settingsOpen}
        locale={locale}
        onClose={() => setSettingsOpen(false)}
        telemetry={telemetry}
        usbDevices={usbDevices}
        wifiDirect={wifiDirect}
        bleBeacon={bleBeacon}
        quotaShield={quotaShield}
        recentSessions={recentSessions}
        totalSavedMb={totalSavedMb}
        uxplayInstalled={uxplayInstalled}
        bonjourReady={bonjourReady}
        airplayName={airplayName}
        onAirplayNameChange={setAirplayName}
        resPreset={resPreset}
        audioEnabled={audioEnabled}
        onAudioEnabledChange={setAudioEnabled}
        audioSyncMs={audioSync.effective_ms}
        airplayFullscreen={airplayFullscreen}
        busyAction={busyAction}
        onRefresh={() => void refreshOverview()}
        onToggleQuotaShield={handleToggleQuotaShield}
        onInstallBonjour={handleInstallBonjour}
        onStartAirplay={handleStartAirplay}
        onStartUsb={handleStartUsb}
        onUsbDriverAction={handleUsbDriverAction}
        onStartWifiDirect={handleStartWifiDirect}
        onStopWifiDirect={handleStopWifiDirect}
        onToggleBle={handleToggleBle}
        onStartSimulator={handleStartSimulator}
        onStopStream={handleStopStream}
      />
    </div>
  );
}

export default App;
