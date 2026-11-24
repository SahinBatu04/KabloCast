import type {
  AirPlayWindowModeResult,
  ApiProblemDetail,
  AppleUsbDevice,
  AudioSyncStatus,
  AudioSyncUpdateRequest,
  BleBeaconStatus,
  BonjourActionResult,
  DashboardOverview,
  DriverAction,
  DriverActionResult,
  MirrorSessionRecord,
  QuickStartRequest,
  QuickStartResult,
  QuotaShieldStatus,
  ResolutionPreset,
  StartMirrorRequest,
  StreamTelemetry,
  WifiDirectStatus,
} from "../types/api";

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    let isTr = true;
    try {
      const saved = window.localStorage.getItem("kablocast_lang");
      if (saved === "en") isTr = false;
      else if (saved !== "tr" && !navigator.language.toLowerCase().startsWith("tr")) isTr = false;
    } catch {
      // Default to Turkish fallback
    }
    throw new Error(
      isTr
        ? "Yerel KabloCast sunucusuna (127.0.0.1:8765) bağlanılamıyor. Lütfen KabloCast.exe'yi yeniden başlatın."
        : "Unable to reach the local KabloCast server (127.0.0.1:8765). Please relaunch KabloCast.exe."
    );
  }

  if (!response.ok) {
    let detail = `Sunucu hatası (${response.status})`;
    try {
      const problem = (await response.json()) as ApiProblemDetail;
      if (problem.detail) {
        detail = problem.detail;
      }
    } catch {
      // Fallback to status message when body is non-JSON
    }
    throw new Error(detail);
  }

  return (await response.json()) as T;
}

export const api = {
  overview: () => requestJson<DashboardOverview>("/api/overview"),
  usbDevices: () => requestJson<AppleUsbDevice[]>("/api/usb/devices"),
  usbDriverAction: (instance_id: string, action: DriverAction) =>
    requestJson<DriverActionResult>("/api/usb/driver", {
      method: "POST",
      body: JSON.stringify({ instance_id, action }),
    }),
  startStream: (req: StartMirrorRequest) =>
    requestJson<StreamTelemetry>("/api/stream/start", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  stopStream: () =>
    requestJson<StreamTelemetry>("/api/stream/stop", {
      method: "POST",
    }),
  startWifiDirect: (ssid = "DIRECT-KabloCast", passphrase?: string | null) =>
    requestJson<WifiDirectStatus>("/api/wifi-direct/start", {
      method: "POST",
      body: JSON.stringify({ ssid, passphrase: passphrase || null }),
    }),
  stopWifiDirect: () =>
    requestJson<WifiDirectStatus>("/api/wifi-direct/stop", {
      method: "POST",
    }),
  startBle: (port = 7000) =>
    requestJson<BleBeaconStatus>(`/api/ble/start?port=${port}`, {
      method: "POST",
    }),
  stopBle: () =>
    requestJson<BleBeaconStatus>("/api/ble/stop", {
      method: "POST",
    }),
  toggleQuotaShield: (enable: boolean, adapter_name?: string | null) =>
    requestJson<QuotaShieldStatus>("/api/quota-shield/toggle", {
      method: "POST",
      body: JSON.stringify({ enable, adapter_name: adapter_name || null }),
    }),
  installBonjour: () =>
    requestJson<BonjourActionResult>("/api/airplay/install-bonjour", {
      method: "POST",
    }),
  setAirplayWindowMode: (fullscreen: boolean) =>
    requestJson<AirPlayWindowModeResult>("/api/airplay/window-mode", {
      method: "POST",
      body: JSON.stringify({ fullscreen }),
    }),
  quickstart: (req: QuickStartRequest) =>
    requestJson<QuickStartResult>("/api/quickstart", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  getAudioSync: (resolutionPreset: ResolutionPreset = "1080p", deviceKey?: string | null) => {
    const params = new URLSearchParams({ resolution_preset: resolutionPreset });
    if (deviceKey) params.set("device_key", deviceKey);
    return requestJson<AudioSyncStatus>(`/api/audio-sync?${params.toString()}`);
  },
  updateAudioSync: (req: AudioSyncUpdateRequest) =>
    requestJson<AudioSyncStatus>("/api/audio-sync", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  sessions: () => requestJson<MirrorSessionRecord[]>("/api/sessions"),
};
