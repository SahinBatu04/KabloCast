import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Camera,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  Maximize2,
  Minimize2,
  Play,
  Radio,
  RotateCcw,
  RotateCw,
  Shield,
  SkipForward,
  SlidersHorizontal,
  Smartphone,
  Square,
  Usb,
  Volume2,
  VolumeX,
  Wifi,
  XCircle,
} from "lucide-react";
import {
  formatActiveInstruction,
  formatAudioKind,
  formatDuration,
  formatMs,
  formatQuickStartStep,
  formatReadyBadge,
  type Locale,
  MESSAGES,
} from "../i18n";
import type { DecoderMetrics } from "../lib/streamClient";
import type {
  AppleUsbDevice,
  AudioSyncStatus,
  ConnectionStrategy,
  QuickStartResult,
  ResolutionPreset,
  ResolvedStrategy,
  StreamTelemetry,
  WifiDirectStatus,
} from "../types/api";

export type RotationDeg = 0 | 90 | 180 | 270;

interface VideoStageProps {
  locale: Locale;
  telemetry: StreamTelemetry;
  decoderMetrics: DecoderMetrics;
  usbDevices: AppleUsbDevice[];
  wifiDirect: WifiDirectStatus;
  audioSync: AudioSyncStatus;
  recommendedStrategy: ResolvedStrategy;
  connectionStrategy: ConnectionStrategy;
  onConnectionStrategyChange: (strategy: ConnectionStrategy) => void;
  quickStartResult: QuickStartResult | null;
  airplayName: string;
  resPreset: ResolutionPreset;
  onResPresetChange: (preset: ResolutionPreset) => void;
  airplayFullscreen: boolean;
  onAirplayFullscreenChange: (fullscreen: boolean) => void;
  uxplayInstalled: boolean;
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  stageWrapperRef: React.RefObject<HTMLDivElement | null>;
  rotation: RotationDeg;
  onRotate: () => void;
  muted: boolean;
  volume: number;
  lipSyncMs: number;
  onToggleMute: () => void;
  onVolumeChange: (v: number) => void;
  onLipSyncChange: (ms: number) => void;
  onQuickStart: () => void;
  onSaveManualSync: (offsetMs: number) => void;
  onResetAutoSync: () => void;
  onStopStream: () => void;
  busyAction: string | null;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function VideoStage({
  locale,
  telemetry,
  decoderMetrics,
  usbDevices,
  wifiDirect,
  audioSync,
  recommendedStrategy,
  connectionStrategy,
  onConnectionStrategyChange,
  quickStartResult,
  airplayName,
  resPreset,
  onResPresetChange,
  airplayFullscreen,
  onAirplayFullscreenChange,
  uxplayInstalled,
  canvasRef,
  stageWrapperRef,
  rotation,
  onRotate,
  muted,
  volume,
  lipSyncMs,
  onToggleMute,
  onVolumeChange,
  onLipSyncChange,
  onQuickStart,
  onSaveManualSync,
  onResetAutoSync,
  onStopStream,
  busyAction,
}: VideoStageProps) {
  const t = MESSAGES[locale];
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [syncTuneOpen, setSyncTuneOpen] = useState(false);
  const [draftSyncMs, setDraftSyncMs] = useState(audioSync.effective_ms);
  const [elapsedSec, setElapsedSec] = useState(0);

  useEffect(() => {
    setDraftSyncMs(audioSync.effective_ms);
  }, [audioSync.effective_ms, audioSync.profile_key]);

  useEffect(() => {
    if (!telemetry.active) {
      setElapsedSec(0);
      return;
    }
    const startedAt = Date.now();
    setElapsedSec(0);
    const id = window.setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(id);
  }, [telemetry.active, telemetry.mode]);

  useEffect(() => {
    const onFsChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, []);

  const toggleFullscreen = async () => {
    const el = stageWrapperRef.current;
    if (!el) return;
    if (!document.fullscreenElement) {
      await el.requestFullscreen();
    } else {
      await document.exitFullscreen();
    }
  };

  const handleSnapshot = () => {
    const canvas = canvasRef.current;
    if (!canvas || canvas.width === 0) return;
    const link = document.createElement("a");
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    link.download = `kablocast-${stamp}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
  };

  const copyText = (key: string, value: string) => {
    void navigator.clipboard?.writeText(value);
    setCopiedKey(key);
    window.setTimeout(() => setCopiedKey(null), 1500);
  };

  const nudgeDraft = (delta: number) => {
    setDraftSyncMs((prev) => Math.max(-400, Math.min(600, prev + delta)));
  };

  const isCanvasMode = telemetry.mode === "usb_quicktime" || telemetry.mode === "simulator";
  const hasDecodedFrames = decoderMetrics.decodedFrames > 0;
  const readyBadge = formatReadyBadge(locale, usbDevices, recommendedStrategy, telemetry);
  const manualIp = wifiDirect.manual_ip_guide?.iphone_ip || "192.168.137.55";
  const manualMask = wifiDirect.manual_ip_guide?.subnet_mask || "255.255.255.0";
  const activeStrategy: ResolvedStrategy =
    quickStartResult?.selected_strategy ??
    (connectionStrategy === "auto" ? recommendedStrategy : connectionStrategy);
  const audioKindText = formatAudioKind(locale, audioSync.output_kind);
  const isAirplayConnected =
    telemetry.device_name.includes("Bağlı") || telemetry.estimated_saved_mb > 0;

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!e.altKey || e.key !== "Enter" || e.repeat) return;
      if (telemetry.mode === "airplay_uxplay" && busyAction === null) {
        e.preventDefault();
        onAirplayFullscreenChange(!airplayFullscreen);
      } else if (isCanvasMode) {
        e.preventDefault();
        const el = stageWrapperRef.current;
        if (!el) return;
        if (!document.fullscreenElement) {
          void el.requestFullscreen();
        } else {
          void document.exitFullscreen();
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    telemetry.mode,
    busyAction,
    airplayFullscreen,
    isCanvasMode,
    onAirplayFullscreenChange,
    stageWrapperRef,
  ]);

  const renderSyncPopover = () =>
    syncTuneOpen && (
      <div className="mt-4 w-full rounded-2xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-4 text-left">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className="font-semibold text-[var(--kc-ink-primary)]">
            {audioKindText} ({audioSync.output_label})
          </span>
          <span className="font-mono-num text-sm font-bold text-[var(--kc-accent-ink)]">
            {formatMs(draftSyncMs)}
          </span>
        </div>

        <div className="mt-2.5 grid grid-cols-4 gap-1.5">
          {([-50, -25, 25, 50] as const).map((delta) => (
            <button
              key={delta}
              type="button"
              onClick={() => nudgeDraft(delta)}
              className="rounded-lg border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] py-1.5 font-mono-num text-xs font-semibold text-[var(--kc-ink-primary)] hover:border-[var(--kc-accent)]"
            >
              {delta > 0 ? `+${delta}` : delta} ms
            </button>
          ))}
        </div>

        <input
          type="range"
          min={-400}
          max={600}
          step={5}
          value={draftSyncMs}
          onChange={(e) => setDraftSyncMs(Number(e.target.value))}
          aria-label={t.prefs.syncPrefix}
          className="mt-3 w-full accent-[var(--kc-accent)]"
        />

        <p className="mt-2 text-xs leading-relaxed text-[var(--kc-ink-secondary)]">
          {t.prefs.tuneHint}
        </p>

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busyAction !== null}
            onClick={() => {
              onSaveManualSync(draftSyncMs);
              setSyncTuneOpen(false);
            }}
            className="inline-flex flex-1 items-center justify-center rounded-xl bg-[var(--kc-accent)] px-3.5 py-2 text-xs font-semibold text-[var(--kc-accent-on)] hover:bg-[var(--kc-accent-hover)] disabled:opacity-60"
          >
            {telemetry.mode === "airplay_uxplay" ? t.prefs.saveApplySync : t.prefs.saveSync}
          </button>

          {audioSync.mode === "manual" && (
            <button
              type="button"
              disabled={busyAction !== null}
              onClick={() => {
                onResetAutoSync();
                setSyncTuneOpen(false);
              }}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--kc-border-strong)] bg-[var(--kc-bg-panel)] px-3 py-2 text-xs font-medium text-[var(--kc-ink-secondary)] hover:text-[var(--kc-ink-primary)]"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              {t.prefs.resetAuto}
            </button>
          )}
        </div>
      </div>
    );

  // Canvas Stream View (Simulator or USB QuickTime)
  if (isCanvasMode) {
    return (
      <section
        ref={stageWrapperRef}
        aria-label={t.hero.title}
        className="flex min-h-0 w-full max-w-5xl flex-col overflow-hidden rounded-3xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] shadow-2xl"
      >
        {/* Minimal Live Telemetry Header */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--kc-border-subtle)] px-4 py-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span
              className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
              style={{
                backgroundColor: "var(--kc-signal-emerald)",
                boxShadow: "0 0 0 3px var(--kc-signal-emerald-soft)",
              }}
            />
            <span className="truncate text-sm font-semibold text-[var(--kc-ink-primary)]">
              {telemetry.device_name}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2 font-mono-num text-xs text-[var(--kc-ink-secondary)]">
            <span className="inline-flex items-center gap-1 rounded-lg bg-[var(--kc-bg-elevated)] px-2.5 py-1 text-[var(--kc-ink-primary)]">
              <Clock className="h-3 w-3 text-[var(--kc-accent-ink)]" />
              {formatDuration(elapsedSec)}
            </span>
            <span className="inline-flex items-center gap-1 rounded-lg border border-[var(--kc-signal-emerald)]/35 bg-[var(--kc-signal-emerald-soft)] px-2.5 py-1 font-semibold text-[var(--kc-signal-emerald)]">
              <Shield className="h-3 w-3" />+{telemetry.estimated_saved_mb.toFixed(1)} MB
            </span>
            <span className="rounded-lg bg-[var(--kc-bg-elevated)] px-2.5 py-1">
              {telemetry.resolution}
            </span>
            <span className="rounded-lg bg-[var(--kc-bg-elevated)] px-2.5 py-1">
              {telemetry.fps.toFixed(1)} FPS
            </span>
            <span className="rounded-lg bg-[var(--kc-bg-elevated)] px-2.5 py-1">
              {telemetry.bitrate_mbps.toFixed(2)} Mbps
            </span>
          </div>
        </div>

        {/* Canvas Container */}
        <div className="relative flex min-h-[360px] min-w-0 flex-1 items-center justify-center bg-[var(--kc-bg-recessed)] p-4">
          <canvas
            ref={canvasRef}
            className={`max-h-[68dvh] max-w-full rounded-xl border border-[var(--kc-border-subtle)] bg-black object-contain shadow-xl transition-opacity duration-200 ${
              hasDecodedFrames ? "opacity-100" : "pointer-events-none absolute opacity-0"
            }`}
          />

          {!hasDecodedFrames && (
            <div className="flex max-w-md flex-col items-center p-6 text-center">
              <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--kc-accent-soft)] text-[var(--kc-accent-ink)]">
                <Usb className="h-6 w-6" />
              </div>
              <h2 className="text-base font-bold text-[var(--kc-ink-primary)]">
                {t.usbWait.title}
              </h2>
              <div className="mt-3 flex items-center gap-2 rounded-xl border border-[var(--kc-accent)]/30 bg-[var(--kc-accent-soft)] px-3 py-2 text-left text-xs text-[var(--kc-accent-ink)]">
                <Smartphone className="h-4 w-4 shrink-0" />
                <span>{t.usbWait.unlockPrompt}</span>
              </div>
              <p className="mt-2.5 text-xs text-[var(--kc-ink-secondary)]">
                {telemetry.last_error || t.usbWait.fallbackMsg}
              </p>
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                <button
                  type="button"
                  disabled={busyAction !== null}
                  onClick={onQuickStart}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--kc-accent)] px-4 py-2 text-xs font-semibold text-[var(--kc-accent-on)] hover:bg-[var(--kc-accent-hover)]"
                >
                  <Radio className="h-3.5 w-3.5" />
                  {t.usbWait.switchToAirplay}
                </button>
                <button
                  type="button"
                  disabled={busyAction !== null}
                  onClick={onStopStream}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--kc-signal-crimson)]/50 bg-[var(--kc-signal-crimson-soft)] px-4 py-2 text-xs font-semibold text-[var(--kc-signal-crimson)]"
                >
                  <Square className="h-3.5 w-3.5" />
                  {t.canvasBar.stop}
                </button>
              </div>
            </div>
          )}

          {decoderMetrics.lastClientError && (
            <div className="absolute bottom-4 left-4 right-4 rounded-xl border border-[var(--kc-signal-amber)]/40 bg-[var(--kc-signal-amber-soft)] px-3 py-2 text-xs text-[var(--kc-ink-primary)]">
              {decoderMetrics.lastClientError}
            </div>
          )}
        </div>

        {/* Clean Canvas Controls Bar */}
        <div className="flex flex-wrap items-center justify-between gap-2.5 border-t border-[var(--kc-border-subtle)] px-4 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busyAction !== null}
              onClick={onStopStream}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--kc-signal-crimson)]/40 bg-[var(--kc-signal-crimson-soft)] px-3 py-1.5 text-xs font-semibold text-[var(--kc-signal-crimson)]"
            >
              <Square className="h-3.5 w-3.5" />
              {t.canvasBar.stop}
            </button>

            <button
              type="button"
              onClick={onRotate}
              title={t.canvasBar.rotate}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] px-2.5 py-1.5 text-xs font-medium text-[var(--kc-ink-primary)]"
            >
              <RotateCw className="h-3.5 w-3.5" />
              <span className="font-mono-num">{rotation}°</span>
            </button>

            <button
              type="button"
              disabled={!hasDecodedFrames}
              onClick={handleSnapshot}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] px-2.5 py-1.5 text-xs font-medium text-[var(--kc-ink-primary)] disabled:opacity-45"
            >
              <Camera className="h-3.5 w-3.5" />
              {t.canvasBar.snapshot}
            </button>

            <button
              type="button"
              onClick={() => void toggleFullscreen()}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] px-2.5 py-1.5 text-xs font-medium text-[var(--kc-ink-primary)]"
            >
              {isFullscreen ? (
                <Minimize2 className="h-3.5 w-3.5" />
              ) : (
                <Maximize2 className="h-3.5 w-3.5" />
              )}
              {isFullscreen ? t.canvasBar.exitFullscreen : t.canvasBar.fullscreen}
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--kc-ink-secondary)]">
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={onToggleMute}
                aria-label={muted ? t.canvasBar.unmute : t.canvasBar.mute}
                className="inline-flex items-center justify-center rounded-lg border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-1.5 text-[var(--kc-ink-primary)]"
              >
                {muted ? <VolumeX className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5" />}
              </button>
              <input
                aria-label="Volume"
                type="range"
                min={0}
                max={100}
                value={muted ? 0 : Math.round(volume * 100)}
                onChange={(e) => onVolumeChange(Number(e.target.value) / 100)}
                className="h-1.5 w-20 accent-[var(--kc-accent)]"
              />
            </div>

            <label className="flex items-center gap-1.5">
              <span>{t.canvasBar.sync}:</span>
              <select
                value={lipSyncMs}
                onChange={(e) => onLipSyncChange(Number(e.target.value))}
                className="rounded-lg border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] px-2 py-1 font-mono-num text-xs text-[var(--kc-ink-primary)]"
              >
                <option value={0}>0 ms</option>
                <option value={40}>40 ms</option>
                <option value={80}>80 ms</option>
                <option value={120}>120 ms</option>
                <option value={180}>180 ms</option>
              </select>
            </label>

            <span className="hidden font-mono-num text-[11px] text-[var(--kc-ink-muted)] sm:inline">
              {t.canvasBar.data}: {formatBytes(telemetry.bytes_received)} • {t.canvasBar.frames}:{" "}
              {decoderMetrics.decodedFrames}
            </span>
          </div>
        </div>
      </section>
    );
  }

  // Focused Single-Card View (Idle or AirPlay 2 Active)
  return (
    <section
      ref={stageWrapperRef}
      aria-label={t.hero.title}
      className="w-full max-w-xl rounded-3xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] p-5 text-center shadow-2xl sm:p-8"
    >
      {/* Hidden canvas node preserved for instant stream transition */}
      <canvas ref={canvasRef} className="pointer-events-none absolute h-0 w-0 opacity-0" />

      {/* Top Status Pill */}
      <div className="mb-5 flex justify-center">
        <span className="inline-flex max-w-full items-center gap-2 rounded-full border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] px-3.5 py-1.5 text-xs font-semibold text-[var(--kc-ink-primary)]">
          <span
            className="h-2 w-2 shrink-0 rounded-full"
            style={{
              backgroundColor: "var(--kc-signal-emerald)",
              boxShadow: "0 0 0 3px var(--kc-signal-emerald-soft)",
            }}
          />
          <span className="truncate">{readyBadge}</span>
        </span>
      </div>

      {telemetry.mode === "airplay_uxplay" ? (
        <>
          <h2 className="text-xl font-bold tracking-tight text-[var(--kc-ink-primary)] sm:text-2xl">
            {isAirplayConnected ? t.airplay.connectedTitle : t.airplay.title}
          </h2>
          <p className="mt-1.5 text-xs leading-relaxed text-[var(--kc-ink-secondary)] sm:text-sm">
            {formatActiveInstruction(locale, activeStrategy, airplayName)}
          </p>

          {/* Live Session Timer & Protected Mobile Quota Strip */}
          <div className="mt-4 flex flex-wrap items-center justify-center gap-2 text-xs">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] px-3 py-1.5 text-[var(--kc-ink-secondary)]">
              <Clock className="h-3.5 w-3.5 text-[var(--kc-accent-ink)]" />
              <span>{t.airplay.elapsedLabel}:</span>
              <strong className="font-mono-num text-[var(--kc-ink-primary)]">
                {formatDuration(elapsedSec)}
              </strong>
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--kc-signal-emerald)]/35 bg-[var(--kc-signal-emerald-soft)] px-3 py-1.5 text-[var(--kc-ink-primary)]">
              <Shield className="h-3.5 w-3.5 text-[var(--kc-signal-emerald)]" />
              <span>{t.airplay.savedDataLabel}:</span>
              <strong className="font-mono-num text-[var(--kc-signal-emerald)]">
                +{telemetry.estimated_saved_mb.toFixed(1)} MB
              </strong>
            </span>
          </div>

          {/* Clean 3-Step Visual Guide */}
          <ol className="mt-5 space-y-2 rounded-2xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-4 text-left text-xs sm:text-sm">
            <li className="flex items-center gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--kc-accent-soft)] font-mono-num text-xs font-bold text-[var(--kc-accent-ink)]">
                1
              </span>
              <span className="text-[var(--kc-ink-primary)]">{t.airplay.step1}</span>
            </li>
            <li className="flex items-center gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--kc-accent-soft)] font-mono-num text-xs font-bold text-[var(--kc-accent-ink)]">
                2
              </span>
              <span className="text-[var(--kc-ink-primary)]">{t.airplay.step2}</span>
            </li>
            <li className="flex items-center gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--kc-accent-soft)] font-mono-num text-xs font-bold text-[var(--kc-accent-ink)]">
                3
              </span>
              <span className="text-[var(--kc-ink-primary)]">
                {t.airplay.step3Prefix}{" "}
                <strong className="font-mono-num text-[var(--kc-accent-ink)]">{airplayName}</strong>{" "}
                {t.airplay.step3Suffix}
              </span>
            </li>
          </ol>

          {/* Alt + Enter Fullscreen Shortcut Hint */}
          <div className="mt-3 flex flex-wrap items-center justify-center gap-1.5 rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] px-3 py-2 text-xs text-[var(--kc-ink-secondary)]">
            <Maximize2 className="h-3.5 w-3.5 shrink-0 text-[var(--kc-accent-ink)]" />
            <span>{t.airplay.shortcutPrefix}</span>
            <kbd className="rounded-md border border-[var(--kc-border-strong)] bg-[var(--kc-bg-panel)] px-1.5 py-0.5 font-mono-num text-[11px] font-semibold text-[var(--kc-ink-primary)]">
              {t.airplay.shortcutKey}
            </kbd>
            <span>{t.airplay.shortcutSuffix}</span>
          </div>

          {/* Inline Wi-Fi Direct QR & Manual IP when active */}
          {wifiDirect.active && (
            <div className="mt-4 rounded-2xl border border-[var(--kc-border-strong)] bg-[var(--kc-bg-elevated)] p-4 text-left">
              <div className="flex flex-col items-center gap-4 sm:flex-row">
                {wifiDirect.qr_svg_data_uri && (
                  <div className="shrink-0 rounded-xl bg-white p-1.5 shadow-sm">
                    <img
                      src={wifiDirect.qr_svg_data_uri}
                      alt="Wi-Fi Direct QR"
                      width={104}
                      height={104}
                      className="block h-[104px] w-[104px]"
                    />
                  </div>
                )}
                <div className="min-w-0 flex-1 space-y-1.5 text-xs">
                  <div className="flex items-center gap-1.5 font-semibold text-[var(--kc-signal-emerald)]">
                    <Wifi className="h-3.5 w-3.5" />
                    {t.airplay.wifiDirectBadge}
                  </div>
                  <div className="truncate font-mono-num text-[var(--kc-ink-primary)]">
                    {t.airplay.ssid}: {wifiDirect.ssid}
                  </div>
                  <div className="flex items-center gap-2 font-mono-num text-[var(--kc-ink-secondary)]">
                    <span className="truncate">
                      {t.airplay.password}: {wifiDirect.passphrase}
                    </span>
                    <button
                      type="button"
                      onClick={() => copyText("pass", wifiDirect.passphrase)}
                      aria-label={t.airplay.copy}
                      className="inline-flex items-center gap-1 rounded-md border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] px-2 py-0.5 text-[11px] font-medium text-[var(--kc-ink-primary)]"
                    >
                      {copiedKey === "pass" ? (
                        <>
                          <Check className="h-3 w-3 text-[var(--kc-signal-emerald)]" />
                          {t.airplay.copied}
                        </>
                      ) : (
                        <>
                          <Copy className="h-3 w-3" />
                          {t.airplay.copy}
                        </>
                      )}
                    </button>
                  </div>
                  <div className="rounded-lg border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] px-2.5 py-2 font-mono-num text-[11px] text-[var(--kc-ink-secondary)]">
                    <span className="text-[var(--kc-ink-muted)]">{t.airplay.ipAddress}: </span>
                    <button
                      type="button"
                      onClick={() => copyText("ip", manualIp)}
                      className="font-semibold text-[var(--kc-ink-primary)] hover:underline"
                    >
                      {manualIp}
                    </button>
                    {" • "}
                    <span className="text-[var(--kc-ink-muted)]">{t.airplay.subnetMask}: </span>
                    <span className="text-[var(--kc-ink-primary)]">{manualMask}</span>
                    {" • "}
                    <span className="font-semibold text-[var(--kc-signal-amber)]">
                      {t.airplay.routerBlank}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Action Buttons Row */}
          <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
            <button
              type="button"
              disabled={busyAction !== null}
              onClick={() => onAirplayFullscreenChange(!airplayFullscreen)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--kc-border-strong)] bg-[var(--kc-bg-elevated)] px-3.5 py-2.5 text-xs font-semibold text-[var(--kc-ink-primary)] hover:border-[var(--kc-accent)] disabled:opacity-60"
            >
              {airplayFullscreen ? (
                <>
                  <Minimize2 className="h-3.5 w-3.5" />
                  {t.airplay.switchToWindow}
                </>
              ) : (
                <>
                  <Maximize2 className="h-3.5 w-3.5" />
                  {t.airplay.switchToFullscreen}
                </>
              )}
            </button>

            <button
              type="button"
              onClick={() => setSyncTuneOpen((v) => !v)}
              className={`inline-flex items-center gap-1.5 rounded-xl border px-3.5 py-2.5 text-xs font-semibold ${
                syncTuneOpen
                  ? "border-[var(--kc-accent)] bg-[var(--kc-accent-soft)] text-[var(--kc-accent-ink)]"
                  : "border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] text-[var(--kc-ink-secondary)] hover:text-[var(--kc-ink-primary)]"
              }`}
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
              {t.airplay.tuneSync} ({formatMs(audioSync.effective_ms)})
            </button>

            <button
              type="button"
              disabled={busyAction !== null}
              onClick={onStopStream}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--kc-signal-crimson)]/40 bg-[var(--kc-signal-crimson-soft)] px-4 py-2.5 text-xs font-semibold text-[var(--kc-signal-crimson)] hover:opacity-90 disabled:opacity-60"
            >
              <Square className="h-3.5 w-3.5 fill-current" />
              {t.airplay.stop}
            </button>
          </div>

          {renderSyncPopover()}

          {/* Compact Steps Summary when there are steps */}
          {quickStartResult && quickStartResult.steps.length > 0 && (
            <details className="mt-4 rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] px-3.5 py-2.5 text-left">
              <summary className="cursor-pointer text-xs font-medium text-[var(--kc-ink-secondary)] hover:text-[var(--kc-ink-primary)]">
                {t.airplay.stepsSummary} ({quickStartResult.steps.length})
              </summary>
              <ul className="mt-2.5 space-y-1.5 text-xs">
                {quickStartResult.steps.map((step) => {
                  const localized = formatQuickStartStep(
                    locale,
                    step,
                    quickStartResult.applied_sync_ms
                  );
                  return (
                    <li key={step.id} className="flex items-start gap-2">
                      {step.status === "done" && (
                        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--kc-signal-emerald)]" />
                      )}
                      {step.status === "warning" && (
                        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--kc-signal-amber)]" />
                      )}
                      {step.status === "skipped" && (
                        <SkipForward className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--kc-ink-muted)]" />
                      )}
                      {step.status === "failed" && (
                        <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--kc-signal-crimson)]" />
                      )}
                      <span className="text-[var(--kc-ink-secondary)]">
                        <strong className="text-[var(--kc-ink-primary)]">{localized.label}:</strong>{" "}
                        {localized.detail}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </details>
          )}
        </>
      ) : (
        <>
          {/* IDLE: Consumer-Clean 1-Click Hero */}
          <h2 className="text-2xl font-bold tracking-tight text-[var(--kc-ink-primary)] sm:text-3xl">
            {t.hero.title}
          </h2>
          <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-[var(--kc-ink-secondary)] sm:text-sm">
            {t.hero.subtitle}
          </p>

          {/* 3 Clean Connection Mode Choices */}
          <div
            role="radiogroup"
            aria-label={t.hero.title}
            className="mt-6 grid grid-cols-1 gap-2 sm:grid-cols-3"
          >
            {t.hero.strategies.map((opt) => {
              const selected = connectionStrategy === opt.id;
              return (
                <button
                  key={opt.id}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => onConnectionStrategyChange(opt.id)}
                  className={`flex min-w-0 flex-col items-center rounded-2xl border px-3 py-2.5 text-center ${
                    selected
                      ? "border-[var(--kc-accent)] bg-[var(--kc-accent-soft)] text-[var(--kc-ink-primary)]"
                      : "border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] text-[var(--kc-ink-secondary)] hover:border-[var(--kc-border-strong)] hover:text-[var(--kc-ink-primary)]"
                  }`}
                >
                  <span className="truncate text-xs font-semibold">{opt.label}</span>
                  <span className="mt-0.5 truncate text-[11px] text-[var(--kc-ink-muted)]">
                    {opt.hint}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Primary Single CTA */}
          <button
            type="button"
            disabled={busyAction !== null || !uxplayInstalled}
            onClick={onQuickStart}
            className="mt-5 inline-flex w-full items-center justify-center gap-2.5 rounded-2xl bg-[var(--kc-accent)] px-6 py-3.5 text-sm font-bold text-[var(--kc-accent-on)] shadow-lg hover:bg-[var(--kc-accent-hover)] disabled:opacity-60 sm:text-base"
          >
            <Play className="h-4 w-4 fill-current" />
            {busyAction === "quickstart" ? t.hero.startingBtn : t.hero.startBtn}
          </button>

          {!uxplayInstalled && (
            <p className="mt-2.5 text-xs text-[var(--kc-signal-crimson)]">
              {t.hero.uxplayMissing}
            </p>
          )}

          {/* Quick Preferences Bar (Resolution, Display Mode, Auto Sync Pill) */}
          <div className="mt-5 flex flex-wrap items-center justify-center gap-2 border-t border-[var(--kc-border-subtle)] pt-4">
            <label className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] px-2.5 py-1.5 text-xs text-[var(--kc-ink-secondary)]">
              <span>{t.prefs.resolution}:</span>
              <select
                aria-label={t.prefs.resolution}
                value={resPreset}
                onChange={(e) => onResPresetChange(e.target.value as ResolutionPreset)}
                className="bg-transparent font-semibold text-[var(--kc-ink-primary)] focus:outline-none"
              >
                <option value="1080p" className="bg-[var(--kc-bg-panel)]">
                  {t.prefs.res1080}
                </option>
                <option value="1440p" className="bg-[var(--kc-bg-panel)]">
                  {t.prefs.res1440}
                </option>
                <option value="native" className="bg-[var(--kc-bg-panel)]">
                  {t.prefs.resNative}
                </option>
              </select>
            </label>

            <button
              type="button"
              onClick={() => onAirplayFullscreenChange(!airplayFullscreen)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] px-3 py-1.5 text-xs font-medium text-[var(--kc-ink-primary)] hover:border-[var(--kc-border-strong)]"
            >
              {airplayFullscreen ? (
                <Maximize2 className="h-3.5 w-3.5 text-[var(--kc-accent-ink)]" />
              ) : (
                <Minimize2 className="h-3.5 w-3.5 text-[var(--kc-accent-ink)]" />
              )}
              {airplayFullscreen ? t.prefs.fullscreen : t.prefs.windowed}
            </button>

            <button
              type="button"
              aria-expanded={syncTuneOpen}
              onClick={() => setSyncTuneOpen((v) => !v)}
              className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-medium ${
                syncTuneOpen
                  ? "border-[var(--kc-accent)] bg-[var(--kc-accent-soft)] text-[var(--kc-accent-ink)]"
                  : "border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] text-[var(--kc-ink-primary)] hover:border-[var(--kc-border-strong)]"
              }`}
            >
              <Volume2 className="h-3.5 w-3.5 text-[var(--kc-signal-emerald)]" />
              <span>
                {t.prefs.syncPrefix}:{" "}
                {audioSync.mode === "auto" ? t.prefs.autoLabel : t.prefs.customLabel}
              </span>
              <span className="font-mono-num text-[var(--kc-ink-secondary)]">
                ({formatMs(audioSync.effective_ms)})
              </span>
            </button>
          </div>

          {renderSyncPopover()}

          {telemetry.last_error && (
            <div className="mt-4 rounded-xl border border-[var(--kc-signal-crimson)]/40 bg-[var(--kc-signal-crimson-soft)] px-3.5 py-2.5 text-left text-xs text-[var(--kc-signal-crimson)]">
              {telemetry.last_error}
            </div>
          )}
        </>
      )}
    </section>
  );
}
