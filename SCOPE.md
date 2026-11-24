# KabloCast — Kapsam Sözleşmesi (Scope Lock)

## 1. Çözülen Problem
Evde sabit Wi-Fi bulunmadığı durumda, telefondaki **Sınırsız YouTube** paketini hotspot üzerinden laptopta tüketmeden (telefonun kendisinde YouTube oynatıp sadece görüntü + sesi laptopa aktararak) büyük ekranda izleme deneyimi sunmak.

## 2. Desteklenen Donanım
- **Telefonlar:** iPhone (USB-C / Lightning) ve iPad (iOS / iPadOS)
- **Bilgisayar:** Windows 11 Laptop (Wi-Fi Direct, Bluetooth LE, Microsoft Edge WebCodecs)

## 3. Dahil Olanlar (IN SCOPE — M1–M4)
1. **Çift Yansıtma Motoru:**
   - **Motor A (Kablolu USB Direct — QuickTime AV):** Tak-çalıştır H.264 video + 48kHz LPCM ses alımı, %0 Wi-Fi ve %0 mobil kota tüketimi.
   - **Motor B (Kablosuz AirPlay 2 — UxPlay v1.74):** Sürücü değişikliği gerektirmeyen H.264/HEVC video + AAC/ALAC ses + YouTube HLS alımı (`d3d11videosink` + `wasapisink` donanım ivmeli).
2. **Sıfır-Kota Ağ Araçları (Evde Wi-Fi Yok Senaryosu):**
   - WinRT `WiFiDirectAdvertisementPublisher` ile laptop üzerinde yerel Wi-Fi Direct erişim noktası + taranabilir Wi-Fi QR kodu + iPhone "Ağ Geçidi Boş Manuel IP" sihirbazı.
   - WinRT BLE AirPlay Beacon (mDNS engellenirse keşif yardımcısı).
   - **Kota Kalkanı (Zero-Leak Firewall):** Hotspot bağlantısında Windows arka plan veri sızıntısını (Update/OneDrive/arka plan süreçleri) tek tıkla engelleyen, kapatılınca temizlenen izole firewall kuralları + canlı adaptör RX/TX hız/kota sayacı.
3. **KabloCast Stüdyo Arayüzü (Desktop App Modu):**
   - `Edge --app=` masaüstü pencere başlatıcısı (`KabloCast.bat` / `launch.py`).
   - WebCodecs `VideoDecoder` + `AudioWorklet` canlı yansıtma tuvali (USB akışı ve yerleşik Simülatör için).
   - 0°/90°/180°/270° döndürme (Shorts/Dikey vs YouTube Yatay), Tam Ekran (`F11`), Dudak Senkronu (ms kaydırma), Ses/Sessiz, Anlık PNG Ekran Görüntüsü.
   - Tasarruf Edilen Mobil Veri (Tahmini MB/GB) canlı hesaplayıcı + SQLite (WAL) oturum geçmişi.
   - Güvenli USB Sürücü Asistanı (UpperFilter ASLA eklenmez, otomatik yedek ve Apple `usbccgp` geri alma destekli).
4. **Doğrulama & Kalite Kapıları:**
   - Python `pytest` (QVH binary protokol testleri, format parser, API, SQLite WAL, simülatör akışı, güvenli driver script sözdizimi & kuru test).
   - Vite + TypeScript strict build + gerçek tarayıcı (`1440x900` ve `390x844`) ekran görüntüsü ve `0` console error doğrulaması.

## 4. Bilerek Kapsam Dışı (OUT OF SCOPE — Faz 2)
- iPhone tarafına Xcode / AltStore ile özel Swift uygulaması yükleme.
- Laptop faresi/klavyesiyle iPhone'u uzaktan kontrol etme (iOS 17–26'da Apple Driver HID sınırlaması).
- macOS veya Linux paketleri.

## 5. Tanımlı Bitti Kriteri (DoD)
- `uxplay.exe` MSYS2 UCRT64 ile derlenmiş ve yerel çalıştırma testinden geçmiş olmalı.
- Backend `pytest` süiti %100 geçmeli (skip yok).
- Frontend `npm run build` ve `tsc --noEmit` hatasız geçmeli.
- Gerçek tarayıcıda Simülatör akışı oynarken masaüstü + mobil ekran görüntüsü alınıp doğrulanmalı.
