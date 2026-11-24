"""Live H.264 Annex-B + 48kHz Stereo LPCM simulator powered by PyAV and Pillow.

Generates a real, hardware-decodable H.264 stream mimicking an iPhone playing
YouTube over cellular while mirrored cleanly to the KabloCast Studio canvas.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import struct
import time
from collections.abc import Awaitable, Callable
from fractions import Fraction

import av
from PIL import Image, ImageDraw, ImageFont

from ..usb.qvh_protocol import ANNEX_B_START_CODE, codec_string_from_sps


def _split_annex_b_nalus(data: bytes) -> list[bytes]:
    """Split Annex-B bitstream into individual raw NALU payloads (without start codes)."""
    parts: list[bytes] = []
    i = 0
    n = len(data)
    while i < n:
        if i + 4 <= n and data[i : i + 4] == b"\x00\x00\x00\x01":
            sc_len = 4
        elif i + 3 <= n and data[i : i + 3] == b"\x00\x00\x01":
            sc_len = 3
        else:
            i += 1
            continue
        start = i + sc_len
        j = start
        while j < n:
            if (j + 4 <= n and data[j : j + 4] == b"\x00\x00\x00\x01") or (
                j + 3 <= n and data[j : j + 3] == b"\x00\x00\x01"
            ):
                break
            j += 1
        if j > start:
            parts.append(data[start:j])
        i = j
    return parts


class StreamSimulator:
    """Produces real H.264 Annex-B video frames and 48kHz stereo LPCM chunks."""

    def __init__(self, width: int = 960, height: int = 540, fps: int = 30) -> None:
        self.width = width
        self.height = height
        self.fps = fps
        self._stop = False
        self._task: asyncio.Task[None] | None = None

    def request_stop(self) -> None:
        self._stop = True

    def _render_frame(self, frame_idx: int) -> Image.Image:
        w, h = self.width, self.height
        sx = w / 960.0
        sy = h / 540.0
        img = Image.new("RGB", (w, h), (22, 22, 20))
        draw = ImageDraw.Draw(img)

        pad = max(6, int(24 * min(sx, sy)))
        inner_pad = max(12, int(48 * sx))
        draw.rounded_rectangle(
            [pad, pad, w - pad, h - pad],
            radius=max(6, int(22 * min(sx, sy))),
            fill=(31, 31, 29),
            outline=(78, 76, 70),
            width=2,
        )

        # Player stage area
        stage_top = max(pad + 18, int(84 * sy))
        stage_bottom = max(stage_top + 24, h - max(28, int(104 * sy)))
        draw.rounded_rectangle(
            [inner_pad, stage_top, w - inner_pad, stage_bottom],
            radius=max(4, int(14 * min(sx, sy))),
            fill=(16, 17, 19),
            outline=(58, 57, 52),
            width=1,
        )

        # Top iPhone status bar pill (shown at studio width >= 480px)
        font = ImageFont.load_default()
        if w >= 520:
            draw.rounded_rectangle([inner_pad, 38, 326, 70], radius=14, fill=(38, 68, 52))
            draw.text(
                (inner_pad + 14, 48),
                "iPhone 16 Pro Max | 5G Sinirsiz YouTube",
                fill=(214, 245, 224),
                font=font,
            )
            draw.rounded_rectangle(
                [w - 238, 38, w - inner_pad, 70],
                radius=14,
                fill=(68, 42, 30),
            )
            draw.text(
                (w - 222, 48),
                "HOTSPOT KOTA: 0.0 MB",
                fill=(255, 212, 186),
                font=font,
            )

        # Animated kinetic motion track inside video viewport
        cx = int((w / 2) + math.sin(frame_idx * 0.06) * (w * 0.22))
        stage_h = stage_bottom - stage_top
        cy = int(((stage_top + stage_bottom) / 2) + math.cos(frame_idx * 0.045) * (stage_h * 0.18))
        scale = min(sx, sy)
        for r_base, col in [(68, (54, 41, 33)), (46, (176, 98, 58)), (22, (238, 172, 128))]:
            r = max(4, int(r_base * scale))
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)

        # Spectrum bars
        bar_base_y = stage_bottom - max(8, int(24 * sy))
        bar_step = max(10, int(28 * sx))
        bar_w = max(5, int(16 * sx))
        max_bh = max(10, int(stage_h * 0.25))
        for idx in range(28):
            bx = inner_pad + 16 + idx * bar_step
            if bx + bar_w >= w - inner_pad - 8:
                break
            bh = max(4, int((0.25 + 0.75 * abs(math.sin(frame_idx * 0.14 + idx * 0.42))) * max_bh))
            draw.rounded_rectangle(
                [bx, bar_base_y - bh, bx + bar_w, bar_base_y],
                radius=2,
                fill=(212, 118, 68) if idx % 3 == 0 else (92, 168, 124),
            )

        # Bottom YouTube playback scrubber
        progress = (frame_idx % (self.fps * 30)) / float(self.fps * 30)
        bar_left, bar_right = inner_pad, max(inner_pad + 20, w - inner_pad)
        bar_y = min(h - 18, stage_bottom + max(8, int(26 * sy)))
        draw.rounded_rectangle([bar_left, bar_y, bar_right, bar_y + 6], radius=3, fill=(58, 56, 52))
        fill_x = max(bar_left + 8, int(bar_left + (bar_right - bar_left) * progress))
        draw.rounded_rectangle([bar_left, bar_y, fill_x, bar_y + 6], radius=3, fill=(214, 96, 54))
        draw.ellipse([fill_x - 6, bar_y - 3, fill_x + 6, bar_y + 9], fill=(246, 244, 238))

        if h >= 320:
            sec = frame_idx // self.fps
            draw.text(
                (inner_pad, h - 42),
                f"Canli H.264 Akisi • {sec // 60:02d}:{sec % 60:02d} • Kare #{frame_idx:04d}",
                fill=(228, 224, 214),
                font=font,
            )
        return img

    @staticmethod
    def _generate_audio_chunk(
        sample_start: int,
        num_samples: int = 1600,
        sample_rate: int = 48000,
    ) -> bytes:
        """Generate subtle, low-volume 48kHz stereo chime pulse."""
        buf = bytearray(num_samples * 4)
        for i in range(num_samples):
            t = (sample_start + i) / float(sample_rate)
            # Soft ambient harmonic chord gated softly every 2 seconds
            gate = 0.08 * max(0.0, math.sin(math.pi * (t % 2.0) / 2.0)) ** 3
            wave = math.sin(2 * math.pi * 220.0 * t) + 0.5 * math.sin(2 * math.pi * 330.0 * t)
            val = gate * wave
            pcm = max(-32767, min(32767, int(val * 32767)))
            struct.pack_into("<hh", buf, i * 4, pcm, pcm)
        return bytes(buf)

    async def run(
        self,
        on_config: Callable[[str, int, int, int], Awaitable[None]],
        on_video: Callable[[bytes, bool, int], Awaitable[None]],
        on_audio: Callable[[bytes, int], Awaitable[None]],
    ) -> None:
        """Encode and emit real H.264 Annex-B frames + LPCM audio at target FPS."""
        self._stop = False
        codec = av.CodecContext.create("libx264", "w")
        codec.width = self.width
        codec.height = self.height
        codec.pix_fmt = "yuv420p"
        codec.time_base = Fraction(1, self.fps)
        codec.gop_size = self.fps
        codec.max_b_frames = 0
        codec.options = {
            "preset": "ultrafast",
            "tune": "zerolatency",
            "profile": "baseline",
        }
        codec.open()

        sps = b""
        pps = b""
        config_sent = False
        frame_idx = 0
        audio_sample_cursor = 0
        samples_per_frame = 48000 // self.fps
        t0 = time.monotonic()

        while not self._stop:
            pil_img = self._render_frame(frame_idx)
            av_frame = av.VideoFrame.from_image(pil_img).reformat(format="yuv420p")
            av_frame.pts = frame_idx
            packets = codec.encode(av_frame)
            pts_us = int((frame_idx * 1_000_000) / self.fps)

            for pkt in packets:
                raw = bytes(pkt)
                nalus = _split_annex_b_nalus(raw)
                is_key = False
                for nalu in nalus:
                    ntype = nalu[0] & 0x1F
                    if ntype == 7:
                        sps = nalu
                    elif ntype == 8:
                        pps = nalu
                    elif ntype == 5:
                        is_key = True

                if not config_sent and sps:
                    await on_config(codec_string_from_sps(sps), self.width, self.height, self.fps)
                    config_sent = True

                if is_key and sps and pps:
                    # Ensure SPS + PPS precede every IDR for instant WebCodecs sync
                    has_sps = any((n[0] & 0x1F) == 7 for n in nalus)
                    prefix = ANNEX_B_START_CODE + sps + ANNEX_B_START_CODE + pps
                    payload = raw if has_sps else (prefix + raw)
                else:
                    payload = raw

                if payload:
                    await on_video(payload, is_key, pts_us)

            pcm = self._generate_audio_chunk(audio_sample_cursor, samples_per_frame)
            audio_sample_cursor += samples_per_frame
            await on_audio(pcm, pts_us)

            frame_idx += 1
            next_t = t0 + (frame_idx / float(self.fps))
            delay = next_t - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                await asyncio.sleep(0)

        with contextlib.suppress(Exception):
            codec.close()
