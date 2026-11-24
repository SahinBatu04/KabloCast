/**
 * Low-latency WebSocket binary mux decoder + WebCodecs VideoDecoder + Web Audio PCM Worklet.
 * Matches backend app/stream/muxer.py header format: <2sBBQ I (16 bytes LE).
 */

const MAGIC_K = 0x4b; // 'K'
const MAGIC_C = 0x43; // 'C'
const HEADER_BYTES = 16;

export const TYPE_VIDEO_CONFIG = 1;
export const TYPE_VIDEO_FRAME = 2;
export const TYPE_AUDIO_CONFIG = 3;
export const TYPE_AUDIO_PCM = 4;

export interface ParsedKabloPacket {
  ptype: number;
  flags: number;
  ptsUs: number;
  payload: Uint8Array;
}

export function parseKabloPacket(buf: ArrayBuffer): ParsedKabloPacket | null {
  if (buf.byteLength < HEADER_BYTES) return null;
  const view = new DataView(buf);
  if (view.getUint8(0) !== MAGIC_K || view.getUint8(1) !== MAGIC_C) return null;

  const ptype = view.getUint8(2);
  const flags = view.getUint8(3);
  const ptsUs = Number(view.getBigUint64(4, true));
  const length = view.getUint32(12, true);
  if (HEADER_BYTES + length > buf.byteLength) return null;

  return {
    ptype,
    flags,
    ptsUs,
    payload: new Uint8Array(buf, HEADER_BYTES, length),
  };
}

interface VideoConfigMsg {
  codec: string;
  width: number;
  height: number;
  fps: number;
}

interface AudioConfigMsg {
  sampleRate: number;
  channels: number;
  bitsPerSample: number;
}

export interface DecoderMetrics {
  decodedFrames: number;
  droppedFrames: number;
  videoWidth: number;
  videoHeight: number;
  wsConnected: boolean;
  decoderReady: boolean;
  lastClientError: string | null;
}

const WORKLET_CODE = `
class KabloPcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.capacity = 24000;
    this.left = new Float32Array(this.capacity);
    this.right = new Float32Array(this.capacity);
    this.readIdx = 0;
    this.writeIdx = 0;
    this.count = 0;
    this.port.onmessage = (event) => {
      const { left, right } = event.data;
      if (!left || !right) return;
      for (let i = 0; i < left.length; i++) {
        if (this.count >= this.capacity) {
          this.readIdx = (this.readIdx + 1) % this.capacity;
          this.count--;
        }
        this.left[this.writeIdx] = left[i];
        this.right[this.writeIdx] = right[i];
        this.writeIdx = (this.writeIdx + 1) % this.capacity;
        this.count++;
      }
    };
  }
  process(_inputs, outputs) {
    const out = outputs[0];
    if (!out || out.length === 0) return true;
    const outL = out[0];
    const outR = out.length > 1 ? out[1] : null;
    for (let i = 0; i < outL.length; i++) {
      if (this.count > 0) {
        outL[i] = this.left[this.readIdx];
        if (outR) outR[i] = this.right[this.readIdx];
        this.readIdx = (this.readIdx + 1) % this.capacity;
        this.count--;
      } else {
        outL[i] = 0;
        if (outR) outR[i] = 0;
      }
    }
    return true;
  }
}
registerProcessor("kablo-pcm-processor", KabloPcmProcessor);
`;

export class KabloStreamClient {
  private ws: WebSocket | null = null;
  private decoder: VideoDecoder | null = null;
  private configured = false;
  private waitingForKeyframe = true;
  private configuring = false;
  private pendingConfig: VideoConfigMsg | null = null;

  private audioCtx: AudioContext | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private gainNode: GainNode | null = null;
  private delayNode: DelayNode | null = null;
  private workletLoaded = false;

  private volume = 0.85;
  private muted = false;
  private lipSyncMs = 0;
  private shouldReconnect = false;
  private reconnectTimer: number | null = null;

  private metrics: DecoderMetrics = {
    decodedFrames: 0,
    droppedFrames: 0,
    videoWidth: 0,
    videoHeight: 0,
    wsConnected: false,
    decoderReady: false,
    lastClientError: null,
  };

  private readonly onFrame: (frame: VideoFrame) => void;
  private readonly onMetrics: (m: DecoderMetrics) => void;

  constructor(
    onFrame: (frame: VideoFrame) => void,
    onMetrics: (m: DecoderMetrics) => void
  ) {
    this.onFrame = onFrame;
    this.onMetrics = onMetrics;
  }

  connect(): void {
    this.shouldReconnect = true;
    this.openSocket();
  }

  disconnect(): void {
    this.shouldReconnect = false;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.closeDecoder();
    this.metrics = {
      ...this.metrics,
      wsConnected: false,
      decoderReady: false,
    };
    this.emitMetrics();
  }

  async unlockAudio(): Promise<void> {
    if (typeof window === "undefined" || typeof AudioContext === "undefined") {
      return;
    }
    if (!this.audioCtx) {
      this.audioCtx = new AudioContext({
        sampleRate: 48000,
        latencyHint: "interactive",
      });
      this.gainNode = this.audioCtx.createGain();
      this.delayNode = this.audioCtx.createDelay(0.5);
      this.applyAudioParams();
      this.delayNode.connect(this.gainNode);
      this.gainNode.connect(this.audioCtx.destination);
    }
    if (this.audioCtx.state === "suspended") {
      await this.audioCtx.resume();
    }
    if (!this.workletLoaded && this.audioCtx.audioWorklet) {
      const blob = new Blob([WORKLET_CODE], { type: "application/javascript" });
      const blobUrl = URL.createObjectURL(blob);
      try {
        await this.audioCtx.audioWorklet.addModule(blobUrl);
        this.workletNode = new AudioWorkletNode(this.audioCtx, "kablo-pcm-processor", {
          outputChannelCount: [2],
        });
        if (this.delayNode) {
          this.workletNode.connect(this.delayNode);
        }
        this.workletLoaded = true;
      } finally {
        URL.revokeObjectURL(blobUrl);
      }
    }
  }

  setAudioControls(muted: boolean, volume: number, lipSyncMs: number): void {
    this.muted = muted;
    this.volume = Math.max(0, Math.min(1, volume));
    this.lipSyncMs = Math.max(0, Math.min(400, lipSyncMs));
    this.applyAudioParams();
  }

  private applyAudioParams(): void {
    if (this.gainNode && this.audioCtx) {
      this.gainNode.gain.setTargetAtTime(
        this.muted ? 0 : this.volume,
        this.audioCtx.currentTime,
        0.015
      );
    }
    if (this.delayNode && this.audioCtx) {
      this.delayNode.delayTime.setTargetAtTime(
        this.lipSyncMs / 1000,
        this.audioCtx.currentTime,
        0.015
      );
    }
  }

  private openSocket(): void {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${proto}//${window.location.host}/ws/stream`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      this.metrics = { ...this.metrics, wsConnected: true, lastClientError: null };
      this.emitMetrics();
    };

    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        this.handleBinaryPacket(event.data);
      }
    };

    ws.onerror = () => {
      this.metrics = {
        ...this.metrics,
        wsConnected: false,
        lastClientError: "WebSocket medya bağlantısı kesildi.",
      };
      this.emitMetrics();
    };

    ws.onclose = () => {
      this.metrics = { ...this.metrics, wsConnected: false };
      this.emitMetrics();
      if (this.shouldReconnect) {
        this.reconnectTimer = window.setTimeout(() => this.openSocket(), 1500);
      }
    };

    this.ws = ws;
  }

  private handleBinaryPacket(buf: ArrayBuffer): void {
    const parsed = parseKabloPacket(buf);
    if (!parsed) return;
    const { ptype, flags, ptsUs, payload } = parsed;

    if (ptype === TYPE_VIDEO_CONFIG) {
      try {
        const cfg = JSON.parse(new TextDecoder().decode(payload)) as VideoConfigMsg;
        void this.configureVideo(cfg);
      } catch (err) {
        this.metrics = {
          ...this.metrics,
          lastClientError: `Video yapılandırma ayrıştırma hatası: ${String(err)}`,
        };
        this.emitMetrics();
      }
      return;
    }

    if (ptype === TYPE_VIDEO_FRAME) {
      this.decodeVideoFrame(payload, (flags & 1) !== 0, ptsUs);
      return;
    }

    if (ptype === TYPE_AUDIO_CONFIG) {
      try {
        JSON.parse(new TextDecoder().decode(payload)) as AudioConfigMsg;
      } catch {
        // Ignore malformed optional config
      }
      return;
    }

    if (ptype === TYPE_AUDIO_PCM) {
      this.pushAudioPcm(payload);
    }
  }

  private async configureVideo(cfg: VideoConfigMsg): Promise<void> {
    if (typeof VideoDecoder === "undefined") {
      this.metrics = {
        ...this.metrics,
        decoderReady: false,
        lastClientError: "Tarayıcı WebCodecs VideoDecoder desteklemiyor.",
      };
      this.emitMetrics();
      return;
    }
    this.pendingConfig = cfg;
    if (this.configuring) return;
    this.configuring = true;

    try {
      while (this.pendingConfig) {
        const target = this.pendingConfig;
        this.pendingConfig = null;
        this.closeDecoder();

        const codecCandidates = [target.codec, "avc1.42E01E", "avc1.4D401F"].filter(Boolean);
        let chosen: VideoDecoderConfig | null = null;
        for (const codecStr of codecCandidates) {
          for (const accel of ["prefer-hardware", "prefer-software"] as const) {
            const candidate: VideoDecoderConfig = {
              codec: codecStr,
              codedWidth: target.width,
              codedHeight: target.height,
              optimizeForLatency: true,
              hardwareAcceleration: accel,
            };
            try {
              const support = await VideoDecoder.isConfigSupported(candidate);
              if (support.supported) {
                chosen = candidate;
                break;
              }
            } catch {
              // Try next candidate
            }
          }
          if (chosen) break;
        }

        if (!chosen) {
          this.metrics = {
            ...this.metrics,
            decoderReady: false,
            lastClientError: `Uygun H.264 WebCodecs profili bulunamadı (${target.codec}).`,
          };
          this.emitMetrics();
          return;
        }

        const decoder = new VideoDecoder({
          output: (frame: VideoFrame) => {
            this.metrics.decodedFrames += 1;
            this.metrics.videoWidth = frame.displayWidth;
            this.metrics.videoHeight = frame.displayHeight;
            try {
              this.onFrame(frame);
            } finally {
              frame.close();
            }
            if (this.metrics.decodedFrames % 10 === 1) {
              this.emitMetrics();
            }
          },
          error: (err: DOMException) => {
            this.configured = false;
            this.waitingForKeyframe = true;
            this.metrics = {
              ...this.metrics,
              decoderReady: false,
              lastClientError: `WebCodecs çözücü hatası: ${err.message}`,
            };
            this.emitMetrics();
          },
        });

        decoder.configure(chosen);
        this.decoder = decoder;
        this.configured = true;
        this.waitingForKeyframe = true;
        this.metrics = {
          ...this.metrics,
          decoderReady: true,
          videoWidth: target.width,
          videoHeight: target.height,
          lastClientError: null,
        };
        this.emitMetrics();
      }
    } finally {
      this.configuring = false;
    }
  }

  private decodeVideoFrame(annexB: Uint8Array, isKey: boolean, ptsUs: number): void {
    if (!this.decoder || !this.configured || this.decoder.state !== "configured") {
      return;
    }
    if (this.waitingForKeyframe) {
      if (!isKey) return;
      this.waitingForKeyframe = false;
    }
    if (this.decoder.decodeQueueSize > 5 && !isKey) {
      this.metrics.droppedFrames += 1;
      return;
    }
    try {
      const copy = new Uint8Array(annexB.byteLength);
      copy.set(annexB);
      this.decoder.decode(
        new EncodedVideoChunk({
          type: isKey ? "key" : "delta",
          timestamp: ptsUs,
          data: copy,
        })
      );
    } catch {
      this.waitingForKeyframe = true;
    }
  }

  private pushAudioPcm(bytes: Uint8Array): void {
    if (!this.workletNode || !this.audioCtx || this.audioCtx.state !== "running") {
      return;
    }
    const samplePairs = Math.floor(bytes.byteLength / 4);
    if (samplePairs <= 0) return;

    const view = new DataView(bytes.buffer, bytes.byteOffset, samplePairs * 4);
    const left = new Float32Array(samplePairs);
    const right = new Float32Array(samplePairs);
    for (let i = 0; i < samplePairs; i++) {
      left[i] = view.getInt16(i * 4, true) / 32768;
      right[i] = view.getInt16(i * 4 + 2, true) / 32768;
    }
    this.workletNode.port.postMessage({ left, right }, [left.buffer, right.buffer]);
  }

  private closeDecoder(): void {
    if (this.decoder) {
      try {
        if (this.decoder.state !== "closed") {
          this.decoder.close();
        }
      } catch {
        // Ignore teardown race
      }
      this.decoder = null;
    }
    this.configured = false;
    this.waitingForKeyframe = true;
  }

  private emitMetrics(): void {
    this.onMetrics({ ...this.metrics });
  }
}
