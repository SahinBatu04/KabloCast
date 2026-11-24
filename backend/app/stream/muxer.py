"""Compact binary frame multiplexer for WebCodecs VideoDecoder + AudioWorklet."""

from __future__ import annotations

import json
import struct
from typing import Literal

FRAME_MAGIC = b"KC"
TYPE_VIDEO_CONFIG = 1
TYPE_VIDEO_FRAME = 2
TYPE_AUDIO_CONFIG = 3
TYPE_AUDIO_PCM = 4
TYPE_STATS = 5

HEADER_STRUCT = struct.Struct("<2sBBQ I")


def encode_packet(
    packet_type: int,
    payload: bytes,
    pts_us: int = 0,
    flags: int = 0,
) -> bytes:
    """Pack a single KabloCast WebSocket binary message."""
    return HEADER_STRUCT.pack(FRAME_MAGIC, packet_type, flags, pts_us, len(payload)) + payload


def encode_video_config(codec: str, width: int, height: int, fps: int = 60) -> bytes:
    """Pack JSON video decoder configuration packet."""
    body = json.dumps(
        {"codec": codec, "width": width, "height": height, "fps": fps},
        separators=(",", ":"),
    ).encode("utf-8")
    return encode_packet(TYPE_VIDEO_CONFIG, body)


def encode_audio_config(
    sample_rate: int = 48000,
    channels: int = 2,
    bits_per_sample: int = 16,
) -> bytes:
    """Pack JSON audio format packet."""
    body = json.dumps(
        {
            "sampleRate": sample_rate,
            "channels": channels,
            "bitsPerSample": bits_per_sample,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return encode_packet(TYPE_AUDIO_CONFIG, body)


def encode_video_frame(annex_b: bytes, pts_us: int, is_keyframe: bool) -> bytes:
    """Pack an H.264 Annex-B video frame for WebCodecs VideoDecoder."""
    return encode_packet(
        TYPE_VIDEO_FRAME,
        annex_b,
        pts_us=pts_us,
        flags=1 if is_keyframe else 0,
    )


def encode_audio_pcm(pcm_s16le: bytes, pts_us: int) -> bytes:
    """Pack 48kHz stereo S16LE LPCM audio samples."""
    return encode_packet(TYPE_AUDIO_PCM, pcm_s16le, pts_us=pts_us)


def decode_packet(raw: bytes) -> tuple[Literal[1, 2, 3, 4, 5], int, int, bytes]:
    """Decode and validate a binary WebSocket packet (primarily for tests)."""
    if len(raw) < HEADER_STRUCT.size:
        raise ValueError("Packet shorter than header")
    magic, ptype, flags, pts_us, length = HEADER_STRUCT.unpack(raw[: HEADER_STRUCT.size])
    if magic != FRAME_MAGIC:
        raise ValueError(f"Invalid magic {magic!r}")
    payload = raw[HEADER_STRUCT.size : HEADER_STRUCT.size + length]
    if len(payload) != length:
        raise ValueError("Truncated payload")
    return ptype, flags, pts_us, payload  # type: ignore[return-value]
