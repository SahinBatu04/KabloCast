# Runtime Binaries (`runtime/uxplay`)

## English
Large third-party Windows binaries (~250 MB of GStreamer D3D11/WASAPI2 DLLs, `uxplay-windows.exe`, `mDNSResponder.exe`, and `uxplay-bluetooth-beacon.exe`) are excluded from Git tracking via `.gitignore`.

To run AirPlay 2 receiver mode locally, place the portable `uxplay-windows` release files (including `uxplay-windows.exe`, `mDNSResponder.exe`, and the accompanying `lib/` + DLLs) inside this `runtime/uxplay/` directory.

## Türkçe
Yaklaşık 250 MB tutan büyük üçüncü parti Windows ikilileri (`uxplay-windows.exe`, GStreamer D3D11/WASAPI2 DLL dosyaları, `mDNSResponder.exe` ve `uxplay-bluetooth-beacon.exe`) boyut nedeniyle `.gitignore` ile depo dışında tutulur.

AirPlay 2 alıcı modunu yerel bilgisayarınızda çalıştırmak için taşınabilir `uxplay-windows` paketinin içindeki dosyaları (exe, dll ve `lib/` klasörü) doğrudan bu `runtime/uxplay/` dizinine yerleştirin.
