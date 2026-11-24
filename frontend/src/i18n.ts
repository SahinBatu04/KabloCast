import type {
  AppleUsbDevice,
  AudioOutputKind,
  ConnectionStrategy,
  QuickStartStep,
  ResolvedStrategy,
  StreamTelemetry,
} from "./types/api";

export type Locale = "tr" | "en";
export type ThemeMode = "light" | "dark";

export function detectInitialLocale(): Locale {
  if (typeof window === "undefined") return "en";
  try {
    const saved = window.localStorage.getItem("kablocast_lang");
    if (saved === "tr" || saved === "en") return saved;
  } catch {
    // Ignore storage access restrictions
  }
  const nav = (typeof navigator !== "undefined" ? navigator.language : "en").toLowerCase();
  return nav.startsWith("tr") ? "tr" : "en";
}

export function detectInitialTheme(): ThemeMode {
  if (typeof window === "undefined") return "dark";
  try {
    const saved = window.localStorage.getItem("kablocast_theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // Ignore storage access restrictions
  }
  if (typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: light)").matches) {
    return "light";
  }
  return "dark";
}

export function formatMs(ms: number): string {
  return ms > 0 ? `+${ms} ms` : `${ms} ms`;
}

export function formatDuration(totalSec: number): string {
  const sec = Math.max(0, Math.floor(totalSec));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

export function formatAudioKind(locale: Locale, kind: AudioOutputKind): string {
  const tr: Record<AudioOutputKind, string> = {
    speaker: "Hoparlör",
    wired_headphones: "Kablolu Kulaklık",
    hdmi_monitor: "Monitör Sesi",
    wireless_headset: "Kablosuz Kulaklık",
    bluetooth: "Bluetooth Ses",
  };
  const en: Record<AudioOutputKind, string> = {
    speaker: "Speaker",
    wired_headphones: "Wired Headphones",
    hdmi_monitor: "Monitor Audio",
    wireless_headset: "Wireless Headset",
    bluetooth: "Bluetooth Audio",
  };
  return (locale === "tr" ? tr : en)[kind];
}

export function formatStrategyLabel(
  locale: Locale,
  strategy: ResolvedStrategy | ConnectionStrategy
): string {
  const tr: Record<ResolvedStrategy | ConnectionStrategy, string> = {
    auto: "Otomatik",
    lan_wifi: "Ev Wi-Fi",
    usb_zero_quota: "Kablolu (USB)",
    wifi_direct: "Modemsiz Kablosuz",
  };
  const en: Record<ResolvedStrategy | ConnectionStrategy, string> = {
    auto: "Automatic",
    lan_wifi: "Home Wi-Fi",
    usb_zero_quota: "Wired (USB)",
    wifi_direct: "Direct Wireless",
  };
  return (locale === "tr" ? tr : en)[strategy];
}

export function formatReadyBadge(
  locale: Locale,
  usbDevices: AppleUsbDevice[],
  recommendedStrategy: ResolvedStrategy,
  telemetry: StreamTelemetry
): string {
  if (telemetry.active) {
    if (telemetry.mode === "simulator") {
      return locale === "tr" ? "Canlı Test Akışı" : "Live Test Stream";
    }
    if (telemetry.mode === "usb_quicktime") {
      return locale === "tr" ? "USB Akışı Aktif" : "USB Stream Active";
    }
    if (telemetry.device_name.includes("Bağlı") || telemetry.estimated_saved_mb > 0) {
      return locale === "tr" ? "Cihaz Bağlı • Yayında" : "Device Connected • Live";
    }
    return locale === "tr" ? "AirPlay 2 Yayında" : "AirPlay 2 Active";
  }

  const usbModel = usbDevices[0]?.model_hint;
  if (usbModel) {
    return locale === "tr"
      ? `Hazır • ${usbModel} Bağlı`
      : `Ready • ${usbModel} Connected`;
  }

  const pathLabel = formatStrategyLabel(locale, recommendedStrategy);
  return locale === "tr" ? `Hazır • ${pathLabel}` : `Ready • ${pathLabel}`;
}

export function formatActiveInstruction(
  locale: Locale,
  strategy: ResolvedStrategy,
  airplayName: string
): string {
  if (locale === "tr") {
    if (strategy === "usb_zero_quota") {
      return `iPhone'da Kişisel Erişim Noktası (Yalnızca USB) açıkken Denetim Merkezi → Ekran Yansıtma → "${airplayName}" seçin.`;
    }
    if (strategy === "wifi_direct") {
      return `Aşağıdaki QR kodu okutup bağlanın (Yönlendirici boş kalsın), ardından Denetim Merkezi → Ekran Yansıtma → "${airplayName}" seçin.`;
    }
    return `iPhone veya iPad'inizde Denetim Merkezi → Ekran Yansıtma → "${airplayName}" dokunun.`;
  }
  if (strategy === "usb_zero_quota") {
    return `Enable Personal Hotspot (USB Only) on your iPhone, then open Control Center → Screen Mirroring → "${airplayName}".`;
  }
  if (strategy === "wifi_direct") {
    return `Scan the QR code below to join (keep Router blank in IP settings), then select "${airplayName}" in Screen Mirroring.`;
  }
  return `Open Control Center → Screen Mirroring → "${airplayName}" on your iPhone or iPad.`;
}

export function formatQuickStartStep(
  locale: Locale,
  step: QuickStartStep,
  appliedSyncMs: number
): { label: string; detail: string } {
  if (locale === "tr") {
    return { label: step.label, detail: step.detail };
  }

  const labels: Record<string, string> = {
    usb_driver: "iPhone / iPad USB Check",
    bonjour: "Bonjour Discovery",
    network: "Zero-Quota Bridge",
    audio_sync: "Auto A/V Sync",
    airplay: "AirPlay 2 Receiver",
  };
  const label = labels[step.id] ?? step.label;

  if (step.id === "usb_driver") {
    if (step.status === "skipped") {
      return { label, detail: "No USB cable detected; using wireless AirPlay 2." };
    }
    if (step.status === "done") {
      return { label, detail: "Apple composite USB driver is ready." };
    }
    return { label, detail: "Could not switch USB mode automatically; check UAC prompt." };
  }

  if (step.id === "bonjour") {
    return {
      label,
      detail:
        step.status === "done"
          ? "Apple mDNS discovery service is running."
          : "Bonjour service installation requires administrator confirmation.",
    };
  }

  if (step.id === "network") {
    return {
      label,
      detail:
        step.status === "done"
          ? "Network path verified; mobile hotspot data is protected."
          : "Network bridge started with warning; check settings if needed.",
    };
  }

  if (step.id === "audio_sync") {
    return {
      label,
      detail: `Calibrated for your active audio output (${formatMs(appliedSyncMs)}).`,
    };
  }

  if (step.id === "airplay") {
    return {
      label,
      detail:
        step.status === "done"
          ? "Receiver is live and waiting for your iPhone or iPad."
          : "Failed to launch AirPlay 2 receiver.",
    };
  }

  return { label, detail: step.detail };
}

export const MESSAGES = {
  tr: {
    appName: "KabloCast",
    header: {
      guide: "Rehber",
      settings: "Ayarlar",
      toLight: "Açık Tema",
      toDark: "Koyu Tema",
      refresh: "Yenile",
    },
    hero: {
      title: "iPhone & iPad Ekranını Yansıt",
      subtitle:
        "Mobil internet kotanı harcamadan ekranı ve sesi bilgisayarına düşük gecikmeyle aktar.",
      startBtn: "Yansıtmayı Başlat",
      startingBtn: "Hazırlanıyor...",
      uxplayMissing: "AirPlay alıcı dosyaları (runtime/uxplay) bulunamadı.",
      strategies: [
        { id: "auto" as ConnectionStrategy, label: "Otomatik", hint: "En iyi yolu seçer" },
        { id: "usb_zero_quota" as ConnectionStrategy, label: "Kablolu (USB)", hint: "Modemsiz & sıfır kota" },
        { id: "wifi_direct" as ConnectionStrategy, label: "Modemsiz Kablosuz", hint: "Wi-Fi Direct köprüsü" },
      ],
    },
    prefs: {
      resolution: "Kalite",
      res1080: "1080p 60 FPS",
      res1440: "1440p 60 FPS",
      resNative: "Cihaz Doğal",
      display: "Görünüm",
      fullscreen: "Tam Ekran",
      windowed: "Pencere",
      syncPrefix: "Ses Senkronu",
      autoLabel: "Oto",
      customLabel: "Özel",
      tuneHint:
        "Ses görüntüden önce geliyorsa (+) artırın, görüntü öndeyse (-) düşürün. Bu ses çıkışı için kalıcı hatırlanır.",
      saveSync: "Kaydet",
      saveApplySync: "Kaydet ve Uygula",
      resetAuto: "Otomatiğe Dön",
      savedToast: "Ses senkronu bu ses çıkışı için kaydedildi.",
      resetToast: "Ses senkronu otomatik moda döndürüldü.",
    },
    airplay: {
      title: "Bağlanmaya Hazır",
      connectedTitle: "Yansıtma Aktif",
      elapsedLabel: "Süre",
      savedDataLabel: "Korunan Kota",
      shortcutPrefix: "İpucu: Yayındayken tam ekran geçişi için",
      shortcutKey: "Alt + Enter",
      shortcutSuffix: "tuşlarına basabilirsin.",
      step1: "Telefonun sağ üst köşesinden Denetim Merkezi'ni aç",
      step2: "Ekran Yansıtma simgesine dokun",
      step3Prefix: "Listeden",
      step3Suffix: "seçeneğini seç",
      switchToWindow: "Pencere Moduna Geç",
      switchToFullscreen: "Tam Ekran Yap",
      tuneSync: "Ses Senkronu",
      stop: "Durdur",
      wifiDirectBadge: "Modemsiz Wi-Fi Direct Aktif",
      ssid: "Ağ Adı",
      password: "Şifre",
      copy: "Kopyala",
      copied: "Kopyalandı",
      manualIpTitle: "Hücresel İnterneti Korumak İçin Elle IP",
      ipAddress: "IP Adresi",
      subnetMask: "Alt Ağ",
      routerBlank: "Yönlendirici: BOŞ BIRAK",
      stepsSummary: "Hazırlık Adımları",
    },
    usbWait: {
      title: "USB Bağlantısı Bekleniyor",
      unlockPrompt: "Lütfen iPhone/iPad ekran kilidini açın ve 'Bu Bilgisayara Güven' onayı verin.",
      fallbackMsg: "USB el sıkışması bekleniyor...",
      switchToAirplay: "Otomatik AirPlay 2'ye Geç",
    },
    canvasBar: {
      stop: "Durdur",
      rotate: "Döndür",
      snapshot: "Kare Al",
      fullscreen: "Tam Ekran",
      exitFullscreen: "Küçült",
      mute: "Sesi Kapat",
      unmute: "Sesi Aç",
      sync: "Senkron",
      data: "Veri",
      frames: "Kare",
    },
    settings: {
      title: "Ayarlar & Tanılama",
      subtitle: "Kota kalkanı, USB sürücüleri, Wi-Fi Direct ve test araçları",
      close: "Kapat",
      tabs: {
        general: "Genel & Kota",
        devices: "Cihazlar & Ağ",
        diagnostics: "Tanılama & Test",
      },
      receiverName: "AirPlay Alıcı Adı",
      mirrorAudio: "Yansıtma Sesi (48 kHz Stereo)",
      audioOn: "Açık",
      audioOff: "Sessiz",
      quotaTitle: "Sıfır Sızıntı Kota Kalkanı",
      quotaDesc:
        "Hotspot kullanırken yalnızca Windows Update, OneDrive ve Edge arka plan güncellemelerini durdurur; DNS ve tarayıcınız açık kalır.",
      quotaActive: "Aktif",
      quotaOff: "Kapalı",
      quotaEnable: "Kota Kalkanını Aç (UAC)",
      quotaDisable: "Kota Kalkanını Kapat (UAC)",
      totalSaved: "Toplam Korunan Mobil Kota",
      recentSessions: "Son Oturumlar",
      noSessions: "Henüz tamamlanmış yansıtma oturumu yok.",
      bonjourLabel: "Apple Keşif Servisi (Bonjour)",
      bonjourReady: "Hazır",
      bonjourMissing: "Kurulmadı",
      installBonjour: "Bonjour Kur (UAC)",
      manualAirplay: "Manuel AirPlay Başlat",
      usbDevicesTitle: "Bağlı Apple USB Cihazları",
      scan: "Tara",
      noUsb: "Bağlı iPhone / iPad algılanmadı. Kabloyu takıp 'Bu Bilgisayara Güven' deyin.",
      restoreApple: "Apple Moduna Dön",
      bindLibusb: "libusb Bağla",
      startUsbQt: "USB QuickTime Başlat",
      wfdTitle: "Manuel Wi-Fi Direct & BLE",
      wfdOn: "Yayında",
      wfdOff: "Kapalı",
      wfdPassPlaceholder: "Boş = Otomatik",
      wfdStart: "Wi-Fi Direct Başlat",
      wfdStop: "SoftAP Kapat",
      bleOn: "BLE Açık",
      bleOff: "BLE Aç",
      adaptersTitle: "Ağ Bağdaştırıcıları",
      simTitle: "Geliştirici Testi: Canlı H.264 Simülasyonu",
      simDesc: "Telefon bağlamadan WebCodecs + AudioWorklet boru hattını test eder.",
      simStart: "Simülasyonu Başlat",
      simStop: "Simülasyonu Durdur",
    },
    guide: {
      title: "Kurulum & Sıfır Kota Rehberi",
      subtitle: "Tüm iPhone ve iPad modelleri için adım adım kullanım",
      close: "Kapat",
      tabs: {
        usbc: "USB-C (iPhone 15/16/17 & iPad)",
        lightning: "Lightning (iPhone 11–14)",
      },
      zeroQuotaTitle: "Mobil İnternet Paketin Neden Tükenmez?",
      zeroQuotaBody:
        "Videoyu yalnızca telefon kendi ekranında oynatır; bilgisayara sadece yerel ağ veya USB kablo üzerinden sıkıştırılmış ekran + ses görüntüsü gelir. Bilgisayardan tarayıcı açılmadığı için paylaşımlı hotspot kotanız harcanmaz.",
      stepsTitle: "3 Adımda Günlük Kullanım",
      step1Usbc:
        "Kablolu bağlayacaksan veri destekli USB-C kablonu tak, ekranı açıp 'Bu Bilgisayara Güven' de ve iPhone'da Kişisel Erişim Noktası (Yalnızca USB)'yi aç. Evde Wi-Fi varsa kablo gerekmez.",
      step1Lightning:
        "Kablolu bağlayacaksan Lightning–USB kablonu tak, ekranı açıp 'Bu Bilgisayara Güven' de ve iPhone'da Kişisel Erişim Noktası (Yalnızca USB)'yi aç. Evde Wi-Fi varsa kablo gerekmez.",
      step2: "KabloCast ana ekranından 'Yansıtmayı Başlat' düğmesine tıkla. Sürücü, Bonjour ve ses senkronu otomatik hazırlanır.",
      step3: "Telefonunda Denetim Merkezi → Ekran Yansıtma → 'KabloCast' seç. Görüntü ve ses otomatik başlar.",
      noWifiTitle: "Evde Wi-Fi ve Kablo Yokken (Modemsiz Kablosuz)",
      noWifiBody:
        "Ana ekranda 'Modemsiz Kablosuz'u seçip başlat. Ekranda çıkan QR kodu iPhone kamerasıyla okut. Ardından iPhone Wi-Fi ayarlarından ağın (i) simgesine girip IP'yi Elle yap ve YÖNLENDİRİCİ (Router) kutusunu BOŞ bırak; böylece YouTube hücresel paketten akmaya devam ederken görüntü laptopa gelir.",
      syncTitle: "Otomatik Ses-Görüntü Senkronu",
      syncBody:
        "KabloCast hoparlör, kablolu/kablosuz kulaklık, monitör veya Bluetooth cihazını otomatik tanıyıp gecikmeyi kendisi ayarlar. İnce ayar yaparsan seçimin o kulaklık/hoparlör için kalıcı hatırlanır.",
    },
    common: {
      close: "Kapat",
      networkFallback: "Sunucuya bağlanılamadı.",
    },
    footer: {
      version: "KabloCast v1.0",
      engine: "Direct3D 11 • 60 FPS",
      tagline: "Sıfır Hotspot Kotası Motoru",
    },
  },
  en: {
    appName: "KabloCast",
    header: {
      guide: "Setup Guide",
      settings: "Settings",
      toLight: "Light Mode",
      toDark: "Dark Mode",
      refresh: "Refresh",
    },
    hero: {
      title: "Mirror Your iPhone or iPad",
      subtitle:
        "Stream screen and audio to your Windows PC at low latency without burning mobile hotspot data.",
      startBtn: "Start Mirroring",
      startingBtn: "Preparing...",
      uxplayMissing: "AirPlay receiver binaries (runtime/uxplay) were not found.",
      strategies: [
        { id: "auto" as ConnectionStrategy, label: "Automatic", hint: "Picks best path" },
        { id: "usb_zero_quota" as ConnectionStrategy, label: "Wired (USB)", hint: "No router, zero data" },
        { id: "wifi_direct" as ConnectionStrategy, label: "Direct Wireless", hint: "Wi-Fi Direct bridge" },
      ],
    },
    prefs: {
      resolution: "Quality",
      res1080: "1080p 60 FPS",
      res1440: "1440p 60 FPS",
      resNative: "Device Native",
      display: "Display",
      fullscreen: "Fullscreen",
      windowed: "Windowed",
      syncPrefix: "Audio Sync",
      autoLabel: "Auto",
      customLabel: "Custom",
      tuneHint:
        "Increase (+) if audio arrives before video; decrease (-) if video is ahead. Saved permanently for this output device.",
      saveSync: "Save",
      saveApplySync: "Save & Apply",
      resetAuto: "Reset to Auto",
      savedToast: "Audio sync profile saved for this output device.",
      resetToast: "Audio sync reset to automatic calibration.",
    },
    airplay: {
      title: "Ready to Connect",
      connectedTitle: "Mirroring Live",
      elapsedLabel: "Elapsed",
      savedDataLabel: "Data Saved",
      shortcutPrefix: "Tip: Press",
      shortcutKey: "Alt + Enter",
      shortcutSuffix: "anytime while streaming to toggle fullscreen.",
      step1: "Swipe down from the top-right corner to open Control Center",
      step2: "Tap the Screen Mirroring icon",
      step3Prefix: "Select",
      step3Suffix: "from the list",
      switchToWindow: "Switch to Windowed",
      switchToFullscreen: "Switch to Fullscreen",
      tuneSync: "Audio Sync",
      stop: "Stop",
      wifiDirectBadge: "Direct Wireless Bridge Active",
      ssid: "Network",
      password: "Password",
      copy: "Copy",
      copied: "Copied",
      manualIpTitle: "Keep Cellular Data Active (Manual IP)",
      ipAddress: "IP Address",
      subnetMask: "Subnet",
      routerBlank: "Router: LEAVE BLANK",
      stepsSummary: "Setup Steps",
    },
    usbWait: {
      title: "Waiting for USB Connection",
      unlockPrompt: "Unlock your iPhone/iPad and tap 'Trust This Computer' on the screen.",
      fallbackMsg: "Waiting for USB QuickTime handshake...",
      switchToAirplay: "Switch to Automatic AirPlay 2",
    },
    canvasBar: {
      stop: "Stop",
      rotate: "Rotate",
      snapshot: "Snapshot",
      fullscreen: "Fullscreen",
      exitFullscreen: "Exit Fullscreen",
      mute: "Mute",
      unmute: "Unmute",
      sync: "Sync",
      data: "Data",
      frames: "Frames",
    },
    settings: {
      title: "Settings & Diagnostics",
      subtitle: "Quota shield, USB drivers, Wi-Fi Direct, and stream diagnostics",
      close: "Close",
      tabs: {
        general: "General & Quota",
        devices: "Devices & Network",
        diagnostics: "Diagnostics & Test",
      },
      receiverName: "AirPlay Receiver Name",
      mirrorAudio: "Mirror Audio (48 kHz Stereo)",
      audioOn: "On",
      audioOff: "Muted",
      quotaTitle: "Zero-Leak Quota Shield",
      quotaDesc:
        "Blocks background Windows Update, OneDrive, and Edge Updater traffic over hotspot while keeping DNS and web browsing open.",
      quotaActive: "Active",
      quotaOff: "Off",
      quotaEnable: "Enable Quota Shield (UAC)",
      quotaDisable: "Disable Quota Shield (UAC)",
      totalSaved: "Estimated Mobile Data Saved",
      recentSessions: "Recent Sessions",
      noSessions: "No completed mirroring sessions yet.",
      bonjourLabel: "Apple Discovery Service (Bonjour)",
      bonjourReady: "Ready",
      bonjourMissing: "Not Installed",
      installBonjour: "Install Bonjour (UAC)",
      manualAirplay: "Manual AirPlay Start",
      usbDevicesTitle: "Connected Apple USB Devices",
      scan: "Scan",
      noUsb: "No iPhone or iPad detected over USB. Plug in and tap 'Trust This Computer'.",
      restoreApple: "Restore Apple Mode",
      bindLibusb: "Bind libusb",
      startUsbQt: "Start USB QuickTime",
      wfdTitle: "Manual Wi-Fi Direct & BLE",
      wfdOn: "Broadcasting",
      wfdOff: "Off",
      wfdPassPlaceholder: "Blank = Auto",
      wfdStart: "Start Wi-Fi Direct",
      wfdStop: "Stop SoftAP",
      bleOn: "BLE Active",
      bleOff: "Start BLE",
      adaptersTitle: "Network Adapters",
      simTitle: "Developer Test: Live H.264 Simulator",
      simDesc: "Verifies the WebCodecs + AudioWorklet pipeline without a physical device.",
      simStart: "Start Simulator",
      simStop: "Stop Simulator",
    },
    guide: {
      title: "Setup & Zero-Data Guide",
      subtitle: "Step-by-step instructions for every iPhone & iPad",
      close: "Close",
      tabs: {
        usbc: "USB-C (iPhone 15–17 & iPad)",
        lightning: "Lightning (iPhone 11–14)",
      },
      zeroQuotaTitle: "Why Mobile Hotspot Data Is Preserved",
      zeroQuotaBody:
        "Playback stays directly inside your phone's native app. Only the compressed screen video and audio stream travel to your PC over local Wi-Fi or USB, avoiding tethered hotspot data usage.",
      stepsTitle: "Everyday 3-Step Flow",
      step1Usbc:
        "If connecting via cable, plug in a data-capable USB-C cable, unlock your device, tap 'Trust This Computer', and enable Personal Hotspot (USB Only). On home Wi-Fi, no cable is needed.",
      step1Lightning:
        "If connecting via cable, plug in your Lightning cable, unlock your device, tap 'Trust This Computer', and enable Personal Hotspot (USB Only). On home Wi-Fi, no cable is needed.",
      step2: "Click 'Start Mirroring' in KabloCast. USB driver mode, Bonjour discovery, and audio sync are configured automatically.",
      step3: "Open Control Center → Screen Mirroring → 'KabloCast' on your iPhone or iPad.",
      noWifiTitle: "No Router & No Cable (Direct Wireless)",
      noWifiBody:
        "Select 'Direct Wireless' and start mirroring. Scan the QR code with your iPhone camera, open the network's (i) menu → Configure IP → Manual, enter the shown IP and Subnet Mask, and leave ROUTER blank so cellular data keeps streaming.",
      syncTitle: "Automatic Audio-Video Sync",
      syncBody:
        "KabloCast detects your default Windows audio output (speakers, wired/wireless headsets, monitor, or Bluetooth) and applies optimal latency automatically. Fine-tuned offsets are saved per output device.",
    },
    common: {
      close: "Close",
      networkFallback: "Unable to reach local server.",
    },
    footer: {
      version: "KabloCast v1.0",
      engine: "Direct3D 11 • 60 FPS",
      tagline: "Zero-Hotspot Engine",
    },
  },
} as const;
