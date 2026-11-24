"""Pydantic v2 DTOs for KabloCast REST and WebSocket endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AudioOutputKind = Literal[
    "speaker",
    "wired_headphones",
    "hdmi_monitor",
    "wireless_headset",
    "bluetooth",
]
ConnectionStrategy = Literal["auto", "lan_wifi", "usb_zero_quota", "wifi_direct"]
ResolvedStrategy = Literal["lan_wifi", "usb_zero_quota", "wifi_direct"]


class StrictModel(BaseModel):
    """Base schema with strict field safety."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class AppleUsbDevice(StrictModel):
    """Detected Apple iPhone/iPad connected over USB."""

    instance_id: str
    friendly_name: str
    product_id: str
    serial: str
    model_hint: str
    cable_hint: str
    active_service: str
    status: str
    qt_ready: bool
    driver_mode: Literal["apple_usbccgp", "libusb_win32", "winusb", "unknown"]


class MirrorSessionRecord(StrictModel):
    """Persisted mirroring session telemetry and quota savings."""

    id: int
    mode: Literal["usb_quicktime", "airplay_uxplay", "simulator"]
    device_name: str
    device_model: str
    started_at: str
    ended_at: str | None = None
    duration_sec: float = 0.0
    video_codec: str = "H.264"
    resolution: str = "1920x1080"
    avg_fps: float = 0.0
    bytes_received: int = 0
    estimated_saved_mb: float = 0.0


class StreamTelemetry(StrictModel):
    """Live runtime stream metrics broadcast to the UI."""

    active: bool
    mode: Literal["idle", "usb_quicktime", "airplay_uxplay", "simulator"]
    device_name: str
    codec: str
    resolution: str
    fps: float
    bitrate_mbps: float
    latency_ms: float
    bytes_received: int
    estimated_saved_mb: float
    audio_active: bool
    last_error: str | None = None


class StartMirrorRequest(StrictModel):
    """Request payload to start USB, AirPlay, or Simulator mirroring."""

    mode: Literal["usb_quicktime", "airplay_uxplay", "simulator"]
    device_serial: str | None = None
    device_label: str = "iPhone 16 Pro Max"
    airplay_name: str = Field(default="KabloCast", min_length=2, max_length=32)
    resolution_preset: Literal["1080p", "1440p", "native"] = "1080p"
    audio_enabled: bool = True
    audio_sync_ms: int = Field(default=180, ge=-900, le=900)
    fullscreen: bool = True


class WifiDirectStatus(StrictModel):
    """Status of the local WinRT Wi-Fi Direct SoftAP."""

    supported: bool
    active: bool
    ssid: str
    passphrase: str
    local_ip: str | None = None
    qr_svg_data_uri: str | None = None
    manual_ip_guide: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


class WifiDirectStartRequest(StrictModel):
    """Parameters for starting local Wi-Fi Direct AP."""

    ssid: str = Field(default="DIRECT-KabloCast", min_length=4, max_length=32)
    passphrase: str | None = Field(default=None, min_length=8, max_length=63)


class NetworkAdapterMetrics(StrictModel):
    """Live RX/TX traffic counters for a Windows network interface."""

    name: str
    description: str
    is_up: bool
    ipv4: str | None = None
    rx_bytes: int
    tx_bytes: int
    rx_kbps: float
    tx_kbps: float
    looks_like_hotspot: bool


class QuotaShieldStatus(StrictModel):
    """Status of the Zero-Leak Windows Firewall Quota Shield."""

    active: bool
    protected_adapter: str | None = None
    active_rule_count: int = 0
    blocked_apps_summary: list[str] = Field(default_factory=list)
    adapters: list[NetworkAdapterMetrics] = Field(default_factory=list)
    last_message: str | None = None


class QuotaShieldToggleRequest(StrictModel):
    """Toggle request for Zero-Leak Firewall Quota Shield."""

    enable: bool
    adapter_name: str | None = None


class BleBeaconStatus(StrictModel):
    """Status of Bluetooth LE AirPlay discovery beacon."""

    supported: bool
    active: bool
    target_ip: str | None = None
    port: int = 7000
    error: str | None = None


class DriverActionRequest(StrictModel):
    """Driver bind/restore/removefilter request for a specific Apple device."""

    instance_id: str
    action: Literal["bind_libusb", "restore_apple", "remove_unsafe_filter"]


class DriverActionResult(StrictModel):
    """Outcome of a USB driver inspection or UAC switch operation."""

    ok: bool
    action: str
    instance_id: str
    message: str
    requires_uac: bool = False
    backup_path: str | None = None
    rolled_back: bool = False


class BonjourActionResult(StrictModel):
    """Outcome of checking or installing Windows Bonjour Service."""

    ok: bool
    bonjour_ready: bool
    message: str


class AirPlayWindowModeRequest(StrictModel):
    """Request to toggle AirPlay video window between borderless fullscreen and windowed."""

    fullscreen: bool


class AirPlayWindowModeResult(StrictModel):
    """Result of applying AirPlay fullscreen/borderless or windowed mode."""

    ok: bool
    fullscreen: bool
    live_applied: bool
    message: str


class AudioSyncStatus(StrictModel):
    """Current automatic or saved manual A/V sync profile for active audio endpoint."""

    endpoint_id: str = "default_speaker"
    output_label: str = "Sistem Hoparlörü"
    output_kind: AudioOutputKind = "speaker"
    device_key: str = "default_ios"
    profile_key: str = "default_speaker::default_ios"
    mode: Literal["auto", "manual"] = "auto"
    recommended_ms: int = 180
    effective_ms: int = 180
    explanation: str = ""


class AudioSyncUpdateRequest(StrictModel):
    """Request to save manual offset or reset back to automatic A/V sync."""

    mode: Literal["auto", "manual"]
    manual_offset_ms: int = Field(default=180, ge=-400, le=600)
    device_key: str | None = None
    resolution_preset: Literal["1080p", "1440p", "native"] = "1080p"
    apply_live: bool = True


class QuickStartStep(StrictModel):
    """Single automation step executed during one-click QuickStart."""

    id: str
    label: str
    status: Literal["done", "skipped", "warning", "failed"]
    detail: str


class QuickStartRequest(StrictModel):
    """One-click automated mirroring launch parameters."""

    connection_strategy: ConnectionStrategy = "auto"
    airplay_name: str = Field(default="KabloCast", min_length=2, max_length=32)
    resolution_preset: Literal["1080p", "1440p", "native"] = "1080p"
    audio_enabled: bool = True
    fullscreen: bool = True
    sync_override_ms: int | None = Field(default=None, ge=-400, le=600)


class QuickStartResult(StrictModel):
    """Detailed outcome of the one-click QuickStart mirroring pipeline."""

    ok: bool
    selected_strategy: ResolvedStrategy
    applied_sync_ms: int
    sync_source: Literal["auto", "saved_manual", "override"]
    audio_output_label: str
    steps: list[QuickStartStep]
    user_instruction: str
    stream: StreamTelemetry


class DashboardOverview(StrictModel):
    """Combined initial state payload for KabloCast Studio."""

    stream: StreamTelemetry
    usb_devices: list[AppleUsbDevice]
    wifi_direct: WifiDirectStatus
    quota_shield: QuotaShieldStatus
    ble_beacon: BleBeaconStatus
    uxplay_installed: bool
    bonjour_ready: bool = True
    recent_sessions: list[MirrorSessionRecord]
    total_saved_mb: float
    audio_sync: AudioSyncStatus = Field(default_factory=AudioSyncStatus)
    recommended_strategy: ResolvedStrategy = "lan_wifi"
    network_summary: str = ""
