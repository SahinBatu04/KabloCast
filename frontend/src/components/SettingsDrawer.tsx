import { useEffect, useRef, useState } from "react";
import {
  Activity,
  Bluetooth,
  Play,
  Radio,
  RefreshCw,
  Settings,
  Shield,
  ShieldCheck,
  Smartphone,
  Square,
  Usb,
  Wifi,
  Wrench,
  X,
} from "lucide-react";
import { type Locale, MESSAGES } from "../i18n";
import type {
  AppleUsbDevice,
  BleBeaconStatus,
  DriverAction,
  MirrorSessionRecord,
  QuotaShieldStatus,
  ResolutionPreset,
  StreamTelemetry,
  WifiDirectStatus,
} from "../types/api";

type SettingsTab = "general" | "devices" | "diagnostics";

interface SettingsDrawerProps {
  open: boolean;
  locale: Locale;
  onClose: () => void;
  telemetry: StreamTelemetry;
  usbDevices: AppleUsbDevice[];
  wifiDirect: WifiDirectStatus;
  bleBeacon: BleBeaconStatus;
  quotaShield: QuotaShieldStatus;
  recentSessions: MirrorSessionRecord[];
  totalSavedMb: number;
  uxplayInstalled: boolean;
  bonjourReady: boolean;
  airplayName: string;
  onAirplayNameChange: (name: string) => void;
  resPreset: ResolutionPreset;
  audioEnabled: boolean;
  onAudioEnabledChange: (enabled: boolean) => void;
  audioSyncMs: number;
  airplayFullscreen: boolean;
  busyAction: string | null;
  onRefresh: () => void;
  onToggleQuotaShield: (enable: boolean, adapterName?: string) => void;
  onInstallBonjour: () => void;
  onStartAirplay: (
    name: string,
    preset: ResolutionPreset,
    audio: boolean,
    audioSyncMs: number,
    fullscreen: boolean
  ) => void;
  onStartUsb: (serial: string | null, label: string, audio: boolean) => void;
  onUsbDriverAction: (instanceId: string, action: DriverAction) => void;
  onStartWifiDirect: (ssid: string, passphrase: string) => void;
  onStopWifiDirect: () => void;
  onToggleBle: (enable: boolean) => void;
  onStartSimulator: (audio: boolean) => void;
  onStopStream: () => void;
}

export function SettingsDrawer({
  open,
  locale,
  onClose,
  telemetry,
  usbDevices,
  wifiDirect,
  bleBeacon,
  quotaShield,
  recentSessions,
  totalSavedMb,
  uxplayInstalled,
  bonjourReady,
  airplayName,
  onAirplayNameChange,
  resPreset,
  audioEnabled,
  onAudioEnabledChange,
  audioSyncMs,
  airplayFullscreen,
  busyAction,
  onRefresh,
  onToggleQuotaShield,
  onInstallBonjour,
  onStartAirplay,
  onStartUsb,
  onUsbDriverAction,
  onStartWifiDirect,
  onStopWifiDirect,
  onToggleBle,
  onStartSimulator,
  onStopStream,
}: SettingsDrawerProps) {
  const t = MESSAGES[locale].settings;
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const [wfdSsid, setWfdSsid] = useState(wifiDirect.ssid || "DIRECT-KabloCast");
  const [wfdPass, setWfdPass] = useState("");

  useEffect(() => {
    const dlg = dialogRef.current;
    if (!dlg) return;
    if (open && !dlg.open) {
      dlg.showModal();
    } else if (!open && dlg.open) {
      dlg.close();
    }
  }, [open]);

  const hotspotAdapter = quotaShield.adapters.find((a) => a.looks_like_hotspot);

  return (
    <dialog
      ref={dialogRef}
      closedby="any"
      onClose={onClose}
      aria-labelledby="kc-settings-title"
      className="kc-dialog m-auto max-h-[90dvh] w-[min(95vw,720px)] overflow-x-clip overflow-y-auto rounded-3xl border border-[var(--kc-border-strong)] bg-[var(--kc-bg-panel)] p-0 text-[var(--kc-ink-primary)] shadow-2xl"
    >
      {/* Sticky Header + Tabs */}
      <div className="sticky top-0 z-10 border-b border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)]/95 px-4 py-3.5 backdrop-blur sm:px-5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <Settings className="h-5 w-5 shrink-0 text-[var(--kc-accent-ink)]" />
            <div className="min-w-0">
              <h2 id="kc-settings-title" className="truncate text-sm font-bold sm:text-base">
                {t.title}
              </h2>
              <p className="truncate text-[11px] text-[var(--kc-ink-muted)]">{t.subtitle}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t.close}
            className="shrink-0 rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-1.5 text-[var(--kc-ink-secondary)] hover:text-[var(--kc-ink-primary)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div role="tablist" className="mt-3 grid grid-cols-3 gap-1.5">
          {(
            [
              { id: "general", label: t.tabs.general },
              { id: "devices", label: t.tabs.devices },
              { id: "diagnostics", label: t.tabs.diagnostics },
            ] as const
          ).map((tab) => {
            const selected = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => setActiveTab(tab.id)}
                className={`truncate rounded-xl border px-2 py-2 text-xs font-semibold transition-colors ${
                  selected
                    ? "border-[var(--kc-accent)] bg-[var(--kc-accent-soft)] text-[var(--kc-accent-ink)]"
                    : "border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] text-[var(--kc-ink-secondary)] hover:text-[var(--kc-ink-primary)]"
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Tab Content */}
      <div className="space-y-4 p-4 sm:p-5">
        {activeTab === "general" && (
          <>
            {/* General Settings */}
            <section className="rounded-2xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="text-xs font-medium text-[var(--kc-ink-secondary)]">
                  {t.receiverName}
                  <input
                    type="text"
                    value={airplayName}
                    onChange={(e) => onAirplayNameChange(e.target.value)}
                    className="mt-1.5 w-full rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] px-3 py-2 text-xs font-semibold text-[var(--kc-ink-primary)]"
                  />
                </label>

                <div className="flex flex-col justify-end">
                  <div className="flex items-center justify-between rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] px-3 py-2">
                    <span className="text-xs font-medium text-[var(--kc-ink-secondary)]">
                      {t.mirrorAudio}
                    </span>
                    <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs font-semibold text-[var(--kc-ink-primary)]">
                      <input
                        type="checkbox"
                        checked={audioEnabled}
                        onChange={(e) => onAudioEnabledChange(e.target.checked)}
                        className="h-4 w-4 accent-[var(--kc-accent)]"
                      />
                      {audioEnabled ? t.audioOn : t.audioOff}
                    </label>
                  </div>
                </div>
              </div>
            </section>

            {/* Quota Shield */}
            <section className="rounded-2xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2.5">
                  <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-[var(--kc-signal-emerald)]" />
                  <div>
                    <h3 className="text-xs font-bold text-[var(--kc-ink-primary)]">
                      {t.quotaTitle}
                    </h3>
                    <p className="mt-1 text-xs leading-relaxed text-[var(--kc-ink-secondary)]">
                      {t.quotaDesc}
                    </p>
                  </div>
                </div>
                <span
                  className={`shrink-0 rounded-lg px-2 py-0.5 font-mono-num text-[11px] font-semibold ${
                    quotaShield.active
                      ? "bg-[var(--kc-signal-emerald-soft)] text-[var(--kc-signal-emerald)]"
                      : "bg-[var(--kc-bg-panel)] text-[var(--kc-ink-muted)]"
                  }`}
                >
                  {quotaShield.active ? `${t.quotaActive} (${quotaShield.active_rule_count})` : t.quotaOff}
                </span>
              </div>

              <button
                type="button"
                disabled={busyAction !== null}
                onClick={() => onToggleQuotaShield(!quotaShield.active, hotspotAdapter?.name)}
                className={`mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-xl px-4 py-2.5 text-xs font-semibold transition-colors disabled:opacity-60 ${
                  quotaShield.active
                    ? "border border-[var(--kc-signal-crimson)]/40 bg-[var(--kc-signal-crimson-soft)] text-[var(--kc-signal-crimson)]"
                    : "bg-[var(--kc-accent)] text-[var(--kc-accent-on)] hover:bg-[var(--kc-accent-hover)]"
                }`}
              >
                <Shield className="h-3.5 w-3.5" />
                {quotaShield.active ? t.quotaDisable : t.quotaEnable}
              </button>
            </section>

            {/* Data Saved & Recent Sessions */}
            <section className="rounded-2xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold text-[var(--kc-ink-secondary)]">
                  {t.totalSaved}
                </span>
                <span className="font-mono-num text-sm font-bold text-[var(--kc-signal-emerald)]">
                  {(totalSavedMb + telemetry.estimated_saved_mb).toFixed(1)} MB
                </span>
              </div>

              <div className="mt-3 border-t border-[var(--kc-border-subtle)] pt-3">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--kc-ink-muted)]">
                  {t.recentSessions}
                </div>
                {recentSessions.length === 0 ? (
                  <p className="text-xs text-[var(--kc-ink-muted)]">{t.noSessions}</p>
                ) : (
                  <div className="space-y-1.5">
                    {recentSessions.slice(0, 5).map((ses) => (
                      <div
                        key={ses.id}
                        className="flex items-center justify-between gap-2 rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] px-3 py-2 text-xs"
                      >
                        <div className="min-w-0">
                          <div className="truncate font-semibold text-[var(--kc-ink-primary)]">
                            {ses.device_name}
                          </div>
                          <div className="font-mono-num text-[11px] text-[var(--kc-ink-muted)]">
                            {ses.resolution} • {ses.duration_sec.toFixed(0)}s
                          </div>
                        </div>
                        <span className="shrink-0 rounded-md bg-[var(--kc-signal-emerald-soft)] px-2 py-0.5 font-mono-num text-[11px] font-semibold text-[var(--kc-signal-emerald)]">
                          +{ses.estimated_saved_mb.toFixed(1)} MB
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>
          </>
        )}

        {activeTab === "devices" && (
          <>
            {/* Bonjour + Manual AirPlay */}
            <section className="rounded-2xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-xs font-bold text-[var(--kc-ink-primary)]">
                  <Radio className="h-4 w-4 text-[var(--kc-signal-emerald)]" />
                  {t.bonjourLabel}
                </span>
                <span
                  className={`rounded-lg px-2 py-0.5 font-mono-num text-[11px] font-semibold ${
                    bonjourReady
                      ? "bg-[var(--kc-signal-emerald-soft)] text-[var(--kc-signal-emerald)]"
                      : "bg-[var(--kc-signal-amber-soft)] text-[var(--kc-signal-amber)]"
                  }`}
                >
                  {bonjourReady ? t.bonjourReady : t.bonjourMissing}
                </span>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                {!bonjourReady && (
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={onInstallBonjour}
                    className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-[var(--kc-signal-amber)]/50 bg-[var(--kc-signal-amber-soft)] px-3 py-2 text-xs font-semibold text-[var(--kc-signal-amber)]"
                  >
                    <Wrench className="h-3.5 w-3.5" />
                    {t.installBonjour}
                  </button>
                )}
                <button
                  type="button"
                  disabled={busyAction !== null || !uxplayInstalled}
                  onClick={() =>
                    onStartAirplay(
                      airplayName,
                      resPreset,
                      audioEnabled,
                      audioSyncMs,
                      airplayFullscreen
                    )
                  }
                  className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-[var(--kc-border-strong)] bg-[var(--kc-bg-panel)] px-3 py-2 text-xs font-semibold text-[var(--kc-ink-primary)] hover:border-[var(--kc-accent)] disabled:opacity-60"
                >
                  <Play className="h-3.5 w-3.5 text-[var(--kc-accent-ink)]" />
                  {t.manualAirplay}
                </button>
              </div>
            </section>

            {/* Connected USB Devices */}
            <section className="rounded-2xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-xs font-bold text-[var(--kc-ink-primary)]">
                  <Usb className="h-4 w-4 text-[var(--kc-accent-ink)]" />
                  {t.usbDevicesTitle}
                </span>
                <button
                  type="button"
                  onClick={onRefresh}
                  disabled={busyAction !== null}
                  className="inline-flex items-center gap-1 rounded-lg border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] px-2.5 py-1 text-[11px] font-medium text-[var(--kc-ink-secondary)] hover:text-[var(--kc-ink-primary)]"
                >
                  <RefreshCw className="h-3 w-3" />
                  {t.scan}
                </button>
              </div>

              {usbDevices.length === 0 ? (
                <div className="mt-3 flex items-center gap-2 rounded-xl border border-dashed border-[var(--kc-border-subtle)] p-3 text-xs text-[var(--kc-ink-muted)]">
                  <Smartphone className="h-4 w-4 shrink-0" />
                  {t.noUsb}
                </div>
              ) : (
                <div className="mt-3 space-y-2">
                  {usbDevices.map((dev) => (
                    <div
                      key={dev.instance_id}
                      className="rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] p-3"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-xs font-semibold text-[var(--kc-ink-primary)]">
                            {dev.model_hint}
                          </div>
                          <div className="truncate font-mono-num text-[11px] text-[var(--kc-ink-muted)]">
                            {dev.serial}
                          </div>
                        </div>
                        <span className="shrink-0 rounded-md bg-[var(--kc-bg-elevated)] px-2 py-0.5 font-mono-num text-[10px] font-semibold text-[var(--kc-ink-secondary)]">
                          {dev.driver_mode}
                        </span>
                      </div>

                      <div className="mt-2.5 flex flex-wrap gap-1.5">
                        <button
                          type="button"
                          disabled={busyAction !== null}
                          onClick={() => onUsbDriverAction(dev.instance_id, "restore_apple")}
                          className="rounded-lg border border-[var(--kc-border-strong)] bg-[var(--kc-bg-elevated)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--kc-ink-primary)]"
                        >
                          {t.restoreApple}
                        </button>
                        <button
                          type="button"
                          disabled={busyAction !== null}
                          onClick={() => onUsbDriverAction(dev.instance_id, "bind_libusb")}
                          className="rounded-lg border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--kc-ink-secondary)]"
                        >
                          {t.bindLibusb}
                        </button>
                        <button
                          type="button"
                          disabled={busyAction !== null}
                          onClick={() => {
                            onStartUsb(dev.serial, dev.model_hint, audioEnabled);
                            onClose();
                          }}
                          className="inline-flex items-center gap-1 rounded-lg border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--kc-ink-secondary)]"
                        >
                          <Play className="h-3 w-3" />
                          {t.startUsbQt}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Wi-Fi Direct Manual Controls */}
            <section className="rounded-2xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-xs font-bold text-[var(--kc-ink-primary)]">
                  <Wifi className="h-4 w-4 text-[var(--kc-accent-ink)]" />
                  {t.wfdTitle}
                </span>
                <span
                  className={`rounded-lg px-2 py-0.5 font-mono-num text-[10px] font-semibold ${
                    wifiDirect.active
                      ? "bg-[var(--kc-signal-emerald-soft)] text-[var(--kc-signal-emerald)]"
                      : "bg-[var(--kc-bg-panel)] text-[var(--kc-ink-muted)]"
                  }`}
                >
                  {wifiDirect.active ? t.wfdOn : t.wfdOff}
                </span>
              </div>

              <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                <input
                  type="text"
                  aria-label="SSID"
                  value={wfdSsid}
                  onChange={(e) => setWfdSsid(e.target.value)}
                  className="w-full rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] px-3 py-1.5 font-mono-num text-xs text-[var(--kc-ink-primary)]"
                />
                <input
                  type="text"
                  aria-label="Password"
                  placeholder={t.wfdPassPlaceholder}
                  value={wfdPass}
                  onChange={(e) => setWfdPass(e.target.value)}
                  className="w-full rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] px-3 py-1.5 font-mono-num text-xs text-[var(--kc-ink-primary)]"
                />
              </div>

              <div className="mt-2.5 flex flex-wrap gap-2">
                {wifiDirect.active ? (
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={onStopWifiDirect}
                    className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-[var(--kc-signal-crimson)]/40 bg-[var(--kc-signal-crimson-soft)] px-3 py-2 text-xs font-semibold text-[var(--kc-signal-crimson)]"
                  >
                    <Square className="h-3.5 w-3.5" />
                    {t.wfdStop}
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={() => onStartWifiDirect(wfdSsid, wfdPass)}
                    className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-[var(--kc-border-strong)] bg-[var(--kc-bg-panel)] px-3 py-2 text-xs font-semibold text-[var(--kc-ink-primary)]"
                  >
                    <Wifi className="h-3.5 w-3.5 text-[var(--kc-accent-ink)]" />
                    {t.wfdStart}
                  </button>
                )}

                <button
                  type="button"
                  disabled={busyAction !== null}
                  onClick={() => onToggleBle(!bleBeacon.active)}
                  className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-medium ${
                    bleBeacon.active
                      ? "border-[var(--kc-signal-emerald)]/50 bg-[var(--kc-signal-emerald-soft)] text-[var(--kc-signal-emerald)]"
                      : "border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] text-[var(--kc-ink-secondary)]"
                  }`}
                >
                  <Bluetooth className="h-3.5 w-3.5" />
                  {bleBeacon.active ? t.bleOn : t.bleOff}
                </button>
              </div>
            </section>
          </>
        )}

        {activeTab === "diagnostics" && (
          <>
            {/* Network Adapters */}
            <section className="rounded-2xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-4">
              <div className="mb-2.5 flex items-center justify-between">
                <h3 className="flex items-center gap-1.5 text-xs font-bold text-[var(--kc-ink-primary)]">
                  <Activity className="h-4 w-4 text-[var(--kc-signal-emerald)]" />
                  {t.adaptersTitle}
                </h3>
                <button
                  type="button"
                  onClick={onRefresh}
                  className="text-xs font-medium text-[var(--kc-accent-ink)] hover:underline"
                >
                  {MESSAGES[locale].header.refresh}
                </button>
              </div>
              <div className="space-y-1.5">
                {quotaShield.adapters.slice(0, 6).map((adp) => (
                  <div
                    key={adp.name}
                    className="flex items-center justify-between gap-2 rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)] px-3 py-2 text-xs"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span
                          className="h-2 w-2 shrink-0 rounded-full"
                          style={{
                            backgroundColor: adp.is_up
                              ? "var(--kc-signal-emerald)"
                              : "var(--kc-ink-muted)",
                          }}
                        />
                        <span className="truncate font-semibold text-[var(--kc-ink-primary)]">
                          {adp.name}
                        </span>
                      </div>
                      <div className="font-mono-num text-[11px] text-[var(--kc-ink-muted)]">
                        {adp.ipv4 || "—"}
                      </div>
                    </div>
                    <div className="shrink-0 text-right font-mono-num text-[11px] text-[var(--kc-ink-secondary)]">
                      <div>↓ {adp.rx_kbps.toFixed(0)} kb/s</div>
                      <div>↑ {adp.tx_kbps.toFixed(0)} kb/s</div>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            {/* Developer Simulator */}
            <section className="rounded-2xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-xs font-bold text-[var(--kc-ink-primary)]">{t.simTitle}</h3>
                  <p className="mt-0.5 text-xs text-[var(--kc-ink-muted)]">{t.simDesc}</p>
                </div>

                {telemetry.mode === "simulator" ? (
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={onStopStream}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--kc-signal-crimson)]/40 bg-[var(--kc-signal-crimson-soft)] px-3.5 py-2 text-xs font-semibold text-[var(--kc-signal-crimson)]"
                  >
                    <Square className="h-3.5 w-3.5" />
                    {t.simStop}
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={() => {
                      onStartSimulator(audioEnabled);
                      onClose();
                    }}
                    className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--kc-accent)] px-3.5 py-2 text-xs font-semibold text-[var(--kc-accent-on)] hover:bg-[var(--kc-accent-hover)]"
                  >
                    <Play className="h-3.5 w-3.5" />
                    {t.simStart}
                  </button>
                )}
              </div>
            </section>
          </>
        )}
      </div>
    </dialog>
  );
}
