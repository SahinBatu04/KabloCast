export type EngineMode = "idle" | "usb_quicktime" | "airplay_uxplay" | "simulator";

export type DriverMode = "apple_usbccgp" | "libusb_win32" | "winusb" | "unknown";

export type DriverAction = "bind_libusb" | "restore_apple" | "remove_unsafe_filter";

export type ResolutionPreset = "1080p" | "1440p" | "native";

export type AudioOutputKind =
  | "speaker"
  | "wired_headphones"
  | "hdmi_monitor"
  | "wireless_headset"
  | "bluetooth";

export type ConnectionStrategy = "auto" | "lan_wifi" | "usb_zero_quota" | "wifi_direct";

export type ResolvedStrategy = "lan_wifi" | "usb_zero_quota" | "wifi_direct";

export interface AudioSyncStatus {
  endpoint_id: string;
  output_label: string;
  output_kind: AudioOutputKind;
  device_key: string;
  profile_key: string;
  mode: "auto" | "manual";
  recommended_ms: number;
  effective_ms: number;
  explanation: string;
}

export interface AudioSyncUpdateRequest {
  mode: "auto" | "manual";
  manual_offset_ms: number;
  device_key?: string | null;
  resolution_preset?: ResolutionPreset;
  apply_live?: boolean;
}

export interface QuickStartStep {
  id: string;
  label: string;
  status: "done" | "skipped" | "warning" | "failed";
  detail: string;
}

export interface QuickStartRequest {
  connection_strategy: ConnectionStrategy;
  airplay_name?: string;
  resolution_preset?: ResolutionPreset;
  audio_enabled?: boolean;
  fullscreen?: boolean;
  sync_override_ms?: number | null;
}

export interface QuickStartResult {
  ok: boolean;
  selected_strategy: ResolvedStrategy;
  applied_sync_ms: number;
  sync_source: "auto" | "saved_manual" | "override";
  audio_output_label: string;
  steps: QuickStartStep[];
  user_instruction: string;
  stream: StreamTelemetry;
}

export interface AppleUsbDevice {
  instance_id: string;
  friendly_name: string;
  product_id: string;
  serial: string;
  model_hint: string;
  cable_hint: string;
  active_service: string;
  status: string;
  qt_ready: boolean;
  driver_mode: DriverMode;
}

export interface MirrorSessionRecord {
  id: number;
  mode: Exclude<EngineMode, "idle">;
  device_name: string;
  device_model: string;
  started_at: string;
  ended_at: string | null;
  duration_sec: number;
  video_codec: string;
  resolution: string;
  avg_fps: number;
  bytes_received: number;
  estimated_saved_mb: number;
}

export interface StreamTelemetry {
  active: boolean;
  mode: EngineMode;
  device_name: string;
  codec: string;
  resolution: string;
  fps: number;
  bitrate_mbps: number;
  latency_ms: number;
  bytes_received: number;
  estimated_saved_mb: number;
  audio_active: boolean;
  last_error: string | null;
}

export interface StartMirrorRequest {
  mode: Exclude<EngineMode, "idle">;
  device_serial?: string | null;
  device_label?: string;
  airplay_name?: string;
  resolution_preset?: ResolutionPreset;
  audio_enabled?: boolean;
  audio_sync_ms?: number;
  fullscreen?: boolean;
}

export interface WifiDirectStatus {
  supported: boolean;
  active: boolean;
  ssid: string;
  passphrase: string;
  local_ip: string | null;
  qr_svg_data_uri: string | null;
  manual_ip_guide: Record<string, string>;
  error: string | null;
}

export interface NetworkAdapterMetrics {
  name: string;
  description: string;
  is_up: boolean;
  ipv4: string | null;
  rx_bytes: number;
  tx_bytes: number;
  rx_kbps: number;
  tx_kbps: number;
  looks_like_hotspot: boolean;
}

export interface QuotaShieldStatus {
  active: boolean;
  protected_adapter: string | null;
  active_rule_count: number;
  blocked_apps_summary: string[];
  adapters: NetworkAdapterMetrics[];
  last_message: string | null;
}

export interface BleBeaconStatus {
  supported: boolean;
  active: boolean;
  target_ip: string | null;
  port: number;
  error: string | null;
}

export interface DriverActionResult {
  ok: boolean;
  action: string;
  instance_id: string;
  message: string;
  requires_uac: boolean;
  backup_path: string | null;
  rolled_back: boolean;
}

export interface BonjourActionResult {
  ok: boolean;
  bonjour_ready: boolean;
  message: string;
}

export interface AirPlayWindowModeResult {
  ok: boolean;
  fullscreen: boolean;
  live_applied: boolean;
  message: string;
}

export interface DashboardOverview {
  stream: StreamTelemetry;
  usb_devices: AppleUsbDevice[];
  wifi_direct: WifiDirectStatus;
  quota_shield: QuotaShieldStatus;
  ble_beacon: BleBeaconStatus;
  uxplay_installed: boolean;
  bonjour_ready: boolean;
  recent_sessions: MirrorSessionRecord[];
  total_saved_mb: number;
  audio_sync: AudioSyncStatus;
  recommended_strategy: ResolvedStrategy;
  network_summary: string;
}

export interface ApiProblemDetail {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
}
