# Project: KabloCast
# Scope: iPhone 13 Type-C USB Screen Mirroring & Audio Live Stream (Valeria / QuickTime Protocol)

## Architecture
- **USB Hardware & Protocol Layer (`backend/app/usb/`)**:
  - `usb_transport.py`: libusb backend loader (libusb1 with libusb0 fallback on Windows), device detection (`VID: 0x05AC, PID: 0x12A8`), Mode 2 extended function activation (`bRequest=0x52`), Configuration 5 selection (`Valeria`), standard `CLEAR_FEATURE(ENDPOINT_HALT)` on EP 0x86 IN and 0x05 OUT, 1MB buffer bulk read loop.
  - `qvh_protocol.py`: QuickTime Video Hack (QVH) / Valeria state machine, PING/ECHO keepalive, clock sync (`CWPA`, `CVRP`, `CLOK`), `ASYN NEED` frame pacing, AVCC to Annex-B H.264 NALU conversion (SPS/PPS extraction), 48kHz stereo 16-bit LPCM audio extraction.
  - `driver_assistant.py`: Apple USB device discovery and driver guidance.
- **Streaming & Server Layer (`backend/app/stream/`, `backend/app/main.py`)**:
  - `muxer.py`: Binary packet multiplexer with magic `b"KC"` and 16-byte header `<2sBBQ I`.
  - `main.py`: FastAPI server running on `http://127.0.0.1:8765`, WebSocket `/ws/stream` binary AV delivery, WebSocket `/ws/telemetry` (600ms updates), REST API endpoints (`/api/stream/start`, `/api/stream/stop`, `/api/health`, `/api/overview`), static SPA serving.
- **Frontend Layer (`frontend/src/`)**:
  - `App.tsx`: React 19 app container, WebSocket telemetry binding, canvas render scheduling.
  - `VideoStage.tsx`: HTML5 `<canvas>` rendering with WebCodecs hardware accelerated `VideoDecoder`, rotation transforms (0°, 90°, 180°, 270°), snapshot capture, user screen unlock guidance, and lip-sync calibration (0-180ms).
  - `streamClient.ts`: WebSocket binary demuxer, WebCodecs pipeline, AudioWorklet ring buffer (`kablo-pcm-processor`).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Resilient USB Backend Loader | Fallback to `usb.backend.libusb0` when `libusb1` enumerates 0 devices on Windows 11 | M1 | Survey (Spec Miner & Explorer 1) |
| 2 | Valeria Mode 2 Activation | Send `bRequest=0x52` (`kVendorRequestSelectExtendedFunction`) to switch iPhone 13 from Config 4 (Ethernet) to Config 5 (Valeria) | M1 | Survey (Explorer 1 & Spec Miner) |
| 3 | Clear Endpoint Halt on Bulk EPs | Send standard USB `CLEAR_FEATURE(ENDPOINT_HALT)` (`0x02, 0x01, 0, EP`) to EP 0x86 and EP 0x05 upon selecting Config 5 | M1 | Survey (Spec Miner) |
| 4 | 1MB Bulk Read Buffer Sizing | Expand read buffer from 64 KB to 1 MB (`1024 * 1024`) to prevent truncation of 1080p60 IDR keyframes | M1 | Survey (Spec Miner) |
| 5 | Ping Keepalive & NEED Pacing | Echo 16-byte PING on EP 0x05, emit initial `ASYN NEED` on `CVRP` and maintain frame pacing | M1 | Survey (Spec Miner) |
| 6 | Robust Interface 2 Cleanup | Ensure `release_interface(2)` is cleanly called in `finally` blocks | M1 | Survey (Spec Miner & Explorer 1) |
| 7 | Low-Latency AV Multiplexing | Forward Annex-B H.264 and S16LE PCM over binary WebSocket `/ws/stream` with 16-byte `KC` header | M2 | Survey (Explorer 2) |
| 8 | FastAPI Live Server & Telemetry | Serve REST API and telemetry updates at `http://127.0.0.1:8765` | M2 | Survey (Explorer 2) |
| 9 | WebCodecs Hardware Video & AudioWorklet UI | Render video on HTML5 canvas with hardware acceleration, audio lip-sync delay, and user screen-unlock guidance | M2 | Survey (Explorer 2) |
| 10 | Live End-to-End Validation | Verify live screen mirroring and audio playback from connected iPhone 13 | M3 | ORIGINAL_REQUEST |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: USB Interface & Valeria Handshake Fix | Implement PyUSB backend fallback, Mode 2 activation, `CLEAR_FEATURE(ENDPOINT_HALT)` on 0x86/0x05, 1MB buffer, and protocol pacing in `usb_transport.py` and `qvh_protocol.py` | none | DONE |
| 2 | M2: AV Ingestion & Web UI Guidance | Ensure WebSocket `/ws/stream` feeds WebCodecs canvas, add screen unlock prompt in UI, verify backend tests and build | M1 | DONE |
| 3 | M3: Live E2E Streaming & Verification | Verify live screen and audio streaming from physical iPhone 13 on `http://127.0.0.1:8765` | M1, M2 | DONE |

## Interface Contracts
### USB Transport (`usb_transport.py`) ↔ Protocol Engine (`qvh_protocol.py`)
- `write_usb(data: bytes)`: Sends raw bulk data to EP 0x05.
- `on_packet_received(data: bytes)`: Delivers raw bulk packets read from EP 0x86 to `PacketFramingBuffer` and `QvhSessionProcessor`.
- `on_video_frame(nalus: bytes, pts: int, is_key: bool)`: Delivers Annex-B NALUs to `StreamOrchestrator`.
- `on_audio_sample(pcm: bytes, pts: int)`: Delivers 48kHz stereo S16LE PCM to `StreamOrchestrator`.

### Backend (`main.py` / `muxer.py`) ↔ Frontend (`streamClient.ts`)
- WebSocket endpoint: `ws://127.0.0.1:8765/ws/stream`
- Packet Header (16 bytes, `<2sBBQ I`):
  - `magic`: `b"KC"`
  - `packet_type`: 1 (VIDEO_CONFIG), 2 (VIDEO_FRAME), 3 (AUDIO_CONFIG), 4 (AUDIO_PCM), 5 (STATS)
  - `flags`: 1 (keyframe), 0 (delta)
  - `pts_us`: timestamp in microseconds
  - `payload_len`: length of following payload bytes

## Code Layout
- `backend/app/usb/usb_transport.py`: USB connection, configuration selection, endpoint halt clearing, bulk read/write loops.
- `backend/app/usb/qvh_protocol.py`: Packet framing, QuickTime CMSampleBuffer demuxing, NALU Annex-B conversion, clock sync, flow pacing.
- `backend/app/stream/muxer.py`: Binary WebSocket packet formatting.
- `backend/app/main.py`: FastAPI server, WebSocket handlers, static SPA hosting.
- `frontend/src/lib/streamClient.ts`: WebSocket receiver, WebCodecs VideoDecoder, Web Audio AudioWorklet.
- `frontend/src/components/VideoStage.tsx`: Canvas rendering, rotation, snapshot, UI feedback.
