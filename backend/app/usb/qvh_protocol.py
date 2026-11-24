"""Byte-accurate implementation of the iOS QuickTime USB AV (QVH) protocol.

Implements framing, CoreMedia binary dictionaries, CMTime, AudioStreamBasicDescription,
CMFormatDescription (SPS/PPS extraction), CMSampleBuffer (H.264 AVCC -> Annex-B video
and 48kHz stereo LPCM audio), and the PING/SYNC/ASYN session state machine.
"""

from __future__ import annotations

import struct
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Outer packet magics (little-endian uint32 on wire)
MAGIC_PING = 0x70696E67  # "gnip" -> LE uint32 "ping"
MAGIC_SYNC = 0x73796E63  # "cnys" -> LE uint32 "sync"
MAGIC_RPLY = 0x72706C79  # "ylpr" -> LE uint32 "rply"
MAGIC_ASYN = 0x6173796E  # "nysa" -> LE uint32 "asyn"

# SYNC sub-types
SYNC_TIME = 0x74696D65
SYNC_CWPA = 0x63777061
SYNC_AFMT = 0x61666D74
SYNC_CVRP = 0x63767270
SYNC_CLOK = 0x636C6F6B
SYNC_OG = 0x676F2120
SYNC_SKEW = 0x736B6577
SYNC_STOP = 0x73746F70

# ASYN sub-types
ASYN_FEED = 0x66656564
ASYN_EAT = 0x65617421
ASYN_TJMP = 0x746A6D70
ASYN_SRAT = 0x73726174
ASYN_SPRP = 0x73707270
ASYN_TBAS = 0x74626173
ASYN_RELS = 0x72656C73
ASYN_HPD1 = 0x68706431
ASYN_HPA1 = 0x68706131
ASYN_NEED = 0x6E656564
ASYN_HPD0 = 0x68706430
ASYN_HPA0 = 0x68706130

# Dictionary / CoreMedia markers
MAGIC_DICT = 0x64696374
MAGIC_KEYV = 0x6B657976
MAGIC_STRK = 0x7374726B
MAGIC_IDXK = 0x6964786B
MAGIC_BULV = 0x62756C76
MAGIC_DATV = 0x64617476
MAGIC_STRV = 0x73747276
MAGIC_NMBV = 0x6E6D6276

MAGIC_FDSC = 0x66647363
MAGIC_MDIA = 0x6D646961
MAGIC_VIDE = 0x76696465
MAGIC_SOUN = 0x736F756E
MAGIC_VDIM = 0x7664696D
MAGIC_CODC = 0x636F6463
MAGIC_AVC1 = 0x61766331
MAGIC_EXTN = 0x6578746E
MAGIC_ASBD = 0x61736264
MAGIC_LPCM = 0x6C70636D

MAGIC_SBUF = 0x73627566
MAGIC_OPTS = 0x6F707473
MAGIC_STIA = 0x73746961
MAGIC_SDAT = 0x73646174
MAGIC_SATT = 0x73617474
MAGIC_SARY = 0x73617279
MAGIC_SSIZ = 0x7373697A
MAGIC_NSMP = 0x6E736D70

EMPTY_CF_TYPE = 1
PING_HEADER = 0x0000000100000000
NANOSECOND_SCALE = 1_000_000_000
ANNEX_B_START_CODE = b"\x00\x00\x00\x01"


class QvhProtocolError(ValueError):
    """Raised when a malformed QVH binary frame is encountered."""


@dataclass(slots=True)
class NSNumber:
    """CoreFoundation serialized NSNumber wrapper."""

    type_specifier: int
    value: int | float

    def to_bytes(self) -> bytes:
        if self.type_specifier == 6:
            return struct.pack("<Bd", 6, float(self.value))
        if self.type_specifier == 4:
            return struct.pack("<BQ", 4, int(self.value))
        if self.type_specifier in (3, 5):
            return struct.pack("<BI", self.type_specifier, int(self.value))
        raise QvhProtocolError(f"Unsupported NSNumber type: {self.type_specifier}")

    @classmethod
    def from_bytes(cls, data: bytes) -> NSNumber:
        if not data:
            raise QvhProtocolError("Empty NSNumber payload")
        spec = data[0]
        if spec == 6 and len(data) == 9:
            return cls(6, struct.unpack("<d", data[1:9])[0])
        if spec == 4 and len(data) == 9:
            return cls(4, struct.unpack("<Q", data[1:9])[0])
        if spec in (3, 5) and len(data) == 5:
            return cls(spec, struct.unpack("<I", data[1:5])[0])
        raise QvhProtocolError(f"Invalid NSNumber spec={spec} len={len(data)}")


@dataclass(slots=True)
class CMTime:
    """24-byte Apple CoreMedia CMTime."""

    value: int
    scale: int
    flags: int = 1
    epoch: int = 0

    def to_bytes(self) -> bytes:
        return struct.pack("<QIIQ", self.value, self.scale, self.flags, self.epoch)

    @classmethod
    def from_bytes(cls, data: bytes) -> CMTime:
        if len(data) < 24:
            raise QvhProtocolError(f"CMTime requires 24 bytes, got {len(data)}")
        value, scale, flags, epoch = struct.unpack("<QIIQ", data[:24])
        return cls(value=value, scale=scale, flags=flags, epoch=epoch)

    def to_microseconds(self) -> int:
        if self.scale <= 0:
            return 0
        return int((self.value * 1_000_000) // self.scale)


@dataclass(slots=True)
class AudioStreamBasicDescription:
    """CoreAudio LPCM format descriptor (40 bytes payload, 56 bytes serialized)."""

    sample_rate: float = 48000.0
    format_id: int = MAGIC_LPCM
    format_flags: int = 12
    bytes_per_packet: int = 4
    frames_per_packet: int = 1
    bytes_per_frame: int = 4
    channels_per_frame: int = 2
    bits_per_channel: int = 16
    reserved: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> AudioStreamBasicDescription:
        if len(data) < 40:
            raise QvhProtocolError(f"ASBD requires >= 40 bytes, got {len(data)}")
        sr, fid, flags, bpp, fpp, bpf, ch, bpc, res = struct.unpack("<dIIIIIIII", data[:40])
        return cls(
            sample_rate=sr,
            format_id=fid,
            format_flags=flags,
            bytes_per_packet=bpp,
            frames_per_packet=fpp,
            bytes_per_frame=bpf,
            channels_per_frame=ch,
            bits_per_channel=bpc,
            reserved=res,
        )

    def to_bytes(self) -> bytes:
        core = struct.pack(
            "<dIIIIIIII",
            self.sample_rate,
            self.format_id,
            self.format_flags,
            self.bytes_per_packet,
            self.frames_per_packet,
            self.bytes_per_frame,
            self.channels_per_frame,
            self.bits_per_channel,
            self.reserved,
        )
        return core + struct.pack("<dd", self.sample_rate, self.sample_rate)


@dataclass(slots=True)
class FormatDescriptor:
    """Parsed CMFormatDescription for video (H.264 SPS/PPS) or audio (LPCM)."""

    media_type: int
    width: int = 0
    height: int = 0
    codec: int = 0
    sps: bytes = b""
    pps: bytes = b""
    asbd: AudioStreamBasicDescription | None = None


@dataclass(slots=True)
class SampleBuffer:
    """Parsed CMSampleBuffer extracted from FEED (video) or EAT! (audio)."""

    media_type: int
    pts: CMTime = field(default_factory=lambda: CMTime(0, NANOSECOND_SCALE))
    format_descriptor: FormatDescriptor | None = None
    num_samples: int = 1
    sample_sizes: list[int] = field(default_factory=list)
    sample_data: bytes = b""


def _parse_len_magic(data: bytes, expected_magic: int | None = None) -> tuple[int, int, bytes]:
    if len(data) < 8:
        raise QvhProtocolError(f"Truncated header ({len(data)} bytes)")
    length, magic = struct.unpack("<II", data[:8])
    if length < 8 or length > len(data):
        raise QvhProtocolError(f"Invalid length {length} for buffer of {len(data)} bytes")
    if expected_magic is not None and magic != expected_magic:
        raise QvhProtocolError(f"Expected magic 0x{expected_magic:08x}, got 0x{magic:08x}")
    return length, magic, data[8:length]


def serialize_string_dict(entries: dict[str, Any]) -> bytes:
    """Serialize a string-keyed dictionary into QVH binary format."""
    parts: list[bytes] = []
    for key, value in entries.items():
        key_bytes = key.encode("utf-8")
        key_chunk = struct.pack("<II", len(key_bytes) + 8, MAGIC_STRK) + key_bytes
        val_chunk = _serialize_dict_value(value)
        pair_len = 8 + len(key_chunk) + len(val_chunk)
        parts.append(struct.pack("<II", pair_len, MAGIC_KEYV) + key_chunk + val_chunk)
    body = b"".join(parts)
    return struct.pack("<II", 8 + len(body), MAGIC_DICT) + body


def _serialize_dict_value(value: Any) -> bytes:
    if isinstance(value, bool):
        return struct.pack("<IIB", 9, MAGIC_BULV, 1 if value else 0)
    if isinstance(value, NSNumber):
        raw = value.to_bytes()
        return struct.pack("<II", 8 + len(raw), MAGIC_NMBV) + raw
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return struct.pack("<II", 8 + len(raw), MAGIC_STRV) + raw
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        return struct.pack("<II", 8 + len(raw), MAGIC_DATV) + raw
    if isinstance(value, dict):
        return serialize_string_dict(value)
    raise QvhProtocolError(f"Unsupported dict value type: {type(value)!r}")


def parse_dict(data: bytes, custom_magic: int = MAGIC_DICT) -> dict[Any, Any]:
    """Parse either a StringKeyDict or IndexKeyDict from QVH binary bytes."""
    _, _, body = _parse_len_magic(data, custom_magic)
    result: dict[Any, Any] = {}
    offset = 0
    while offset < len(body):
        pair_len, _, pair_body = _parse_len_magic(body[offset:], MAGIC_KEYV)
        k_len, k_magic, k_payload = _parse_len_magic(pair_body)
        if k_magic == MAGIC_STRK:
            key: Any = k_payload.decode("utf-8", errors="replace")
        elif k_magic == MAGIC_IDXK:
            key = struct.unpack("<H", k_payload[:2])[0]
        else:
            raise QvhProtocolError(f"Unknown key magic 0x{k_magic:08x}")

        v_raw = pair_body[k_len:]
        result[key] = _parse_dict_value(v_raw)
        offset += pair_len
    return result


def _parse_dict_value(data: bytes) -> Any:
    val_len, magic, payload = _parse_len_magic(data)
    if magic == MAGIC_STRV:
        return payload.decode("utf-8", errors="replace")
    if magic == MAGIC_DATV:
        return payload
    if magic == MAGIC_BULV:
        return bool(payload[0]) if payload else False
    if magic == MAGIC_NMBV:
        return NSNumber.from_bytes(payload)
    if magic == MAGIC_DICT:
        return parse_dict(data[:val_len], MAGIC_DICT)
    if magic == MAGIC_FDSC:
        return parse_format_descriptor(data[:val_len])
    raise QvhProtocolError(f"Unknown value magic 0x{magic:08x}")


def _extract_sps_pps_from_extensions(extensions: dict[Any, Any]) -> tuple[bytes, bytes]:
    """Extract (sps, pps) NALUs from CoreMedia extension key 49 -> key 105 (ISO avcC)."""
    nested = extensions.get(49)
    if not isinstance(nested, dict):
        return b"", b""
    avcc = nested.get(105)
    if not isinstance(avcc, (bytes, bytearray)) or len(avcc) < 11:
        return b"", b""
    first_len = int.from_bytes(avcc[6:8], "big")
    if first_len <= 0 or 10 + first_len >= len(avcc):
        return b"", b""
    first_nal = bytes(avcc[8 : 8 + first_len])
    second_len_pos = 9 + first_len
    second_len = int.from_bytes(avcc[second_len_pos : second_len_pos + 2], "big")
    second_start = 11 + first_len
    if second_len <= 0 or second_start + second_len > len(avcc):
        return b"", b""
    second_nal = bytes(avcc[second_start : second_start + second_len])

    # Apple avcC stores SPS (NAL type 7) first, PPS (NAL type 8) second; guard swapped fixtures.
    if (first_nal[0] & 0x1F) == 8 and (second_nal[0] & 0x1F) == 7:
        return second_nal, first_nal
    return first_nal, second_nal


def parse_format_descriptor(data: bytes) -> FormatDescriptor:
    """Parse CMFormatDescription (`fdsc`) for video or sound streams."""
    _, _, body = _parse_len_magic(data, MAGIC_FDSC)
    mdia_len, _, mdia_body = _parse_len_magic(body, MAGIC_MDIA)
    media_type = struct.unpack("<I", mdia_body[:4])[0]
    rem = body[mdia_len:]

    if media_type == MAGIC_SOUN:
        asbd_len, _, asbd_body = _parse_len_magic(rem, MAGIC_ASBD)
        _ = asbd_len
        return FormatDescriptor(
            media_type=MAGIC_SOUN,
            asbd=AudioStreamBasicDescription.from_bytes(asbd_body),
        )

    vdim_len, _, vdim_body = _parse_len_magic(rem, MAGIC_VDIM)
    width, height = struct.unpack("<II", vdim_body[:8])
    rem = rem[vdim_len:]

    codc_len, _, codc_body = _parse_len_magic(rem, MAGIC_CODC)
    codec = struct.unpack("<I", codc_body[:4])[0]
    rem = rem[codc_len:]

    extensions = parse_dict(rem, MAGIC_EXTN) if rem else {}
    sps, pps = _extract_sps_pps_from_extensions(extensions)
    return FormatDescriptor(
        media_type=MAGIC_VIDE,
        width=width,
        height=height,
        codec=codec,
        sps=sps,
        pps=pps,
    )


def parse_sample_buffer(data: bytes, media_type: int) -> SampleBuffer:
    """Parse CMSampleBuffer (`sbuf`) from FEED or EAT! async packet payload."""
    _, _, body = _parse_len_magic(data, MAGIC_SBUF)
    sample = SampleBuffer(media_type=media_type)
    offset = 0
    while offset < len(body):
        chunk_len, magic, payload = _parse_len_magic(body[offset:])
        if magic == MAGIC_OPTS:
            sample.pts = CMTime.from_bytes(payload)
        elif magic == MAGIC_SDAT:
            sample.sample_data = payload
        elif magic == MAGIC_NSMP:
            sample.num_samples = struct.unpack("<I", payload[:4])[0]
        elif magic == MAGIC_SSIZ:
            count = len(payload) // 4
            sample.sample_sizes = list(struct.unpack(f"<{count}I", payload[: count * 4]))
        elif magic == MAGIC_FDSC:
            sample.format_descriptor = parse_format_descriptor(body[offset : offset + chunk_len])
        elif magic in (MAGIC_STIA, MAGIC_SATT, MAGIC_SARY):
            pass
        offset += chunk_len
    return sample


def avcc_to_annex_b(
    sample_data: bytes, sps: bytes = b"", pps: bytes = b""
) -> tuple[bytes, bool]:
    """Convert 4-byte length-prefixed AVCC NALUs into Annex-B stream.

    Returns (annex_b_bytes, is_keyframe). Prepends SPS/PPS on IDR frames when supplied.
    """
    offset = 0
    nalus: list[bytes] = []
    is_keyframe = False
    while offset + 4 <= len(sample_data):
        nalu_len = struct.unpack(">I", sample_data[offset : offset + 4])[0]
        offset += 4
        if nalu_len == 0 or offset + nalu_len > len(sample_data):
            break
        nalu = sample_data[offset : offset + nalu_len]
        offset += nalu_len
        nal_type = nalu[0] & 0x1F
        if nal_type == 5:
            is_keyframe = True
        nalus.append(nalu)

    out: list[bytes] = []
    if is_keyframe and sps and pps:
        out.append(ANNEX_B_START_CODE + sps)
        out.append(ANNEX_B_START_CODE + pps)
    for nalu in nalus:
        out.append(ANNEX_B_START_CODE + nalu)
    return b"".join(out), is_keyframe


def codec_string_from_sps(sps: bytes) -> str:
    """Compute WebCodecs RFC 6381 H.264 codec string (`avc1.PPCCLL`) from SPS NALU."""
    if len(sps) >= 4:
        return f"avc1.{sps[1]:02x}{sps[2]:02x}{sps[3]:02x}"
    return "avc1.640028"


def build_ping_packet(payload: bytes | int | None = None) -> bytes:
    """Create a 16-byte QVH PING packet echoing device payload if provided."""
    if isinstance(payload, (bytes, bytearray)) and len(payload) == 8:
        payload_bytes = bytes(payload)
    elif isinstance(payload, int):
        payload_bytes = struct.pack("<Q", payload)
    else:
        payload_bytes = struct.pack("<Q", PING_HEADER)
    return struct.pack("<II", 16, MAGIC_PING) + payload_bytes


def build_hpd1_packet(width: float = 1920.0, height: float = 1200.0) -> bytes:
    """Create ASYN HPD1 video request packet."""
    payload = serialize_string_dict(
        {
            "Valeria": True,
            "HEVCDecoderSupports444": True,
            "DisplaySize": {
                "Width": NSNumber(6, width),
                "Height": NSNumber(6, height),
            },
        }
    )
    return struct.pack("<IIQI", len(payload) + 20, MAGIC_ASYN, EMPTY_CF_TYPE, ASYN_HPD1) + payload


def build_hpa1_packet(device_audio_clock_ref: int) -> bytes:
    """Create ASYN HPA1 audio request packet."""
    asbd_bytes = AudioStreamBasicDescription().to_bytes()
    payload = serialize_string_dict(
        {
            "BufferAheadInterval": NSNumber(6, 0.073),
            "deviceUID": "Valeria",
            "ScreenLatency": NSNumber(6, 0.04),
            "formats": asbd_bytes,
            "EDIDAC3Support": NSNumber(3, 0),
            "deviceName": "Valeria",
        }
    )
    return (
        struct.pack("<IIQI", len(payload) + 20, MAGIC_ASYN, device_audio_clock_ref, ASYN_HPA1)
        + payload
    )


def build_need_packet(video_clock_ref: int) -> bytes:
    """Create ASYN NEED pacing packet."""
    return struct.pack("<IIQI", 20, MAGIC_ASYN, video_clock_ref, ASYN_NEED)


def build_hpd0_packet() -> bytes:
    """Create ASYN HPD0 video stop packet."""
    return struct.pack("<IIQI", 20, MAGIC_ASYN, EMPTY_CF_TYPE, ASYN_HPD0)


def build_hpa0_packet(device_audio_clock_ref: int) -> bytes:
    """Create ASYN HPA0 audio stop packet."""
    return struct.pack("<IIQI", 20, MAGIC_ASYN, device_audio_clock_ref, ASYN_HPA0)


def build_clock_reply(correlation_id: int, clock_ref: int) -> bytes:
    """Create 28-byte RPLY packet carrying a newly allocated local CFTypeID."""
    return struct.pack("<IIQIQ", 28, MAGIC_RPLY, correlation_id, 0, clock_ref)


def build_afmt_reply(correlation_id: int) -> bytes:
    """Create RPLY packet acknowledging AudioStreamBasicDescription (`Error: 0`)."""
    dict_bytes = serialize_string_dict({"Error": NSNumber(3, 0)})
    return struct.pack("<IIQI", len(dict_bytes) + 20, MAGIC_RPLY, correlation_id, 0) + dict_bytes


def build_time_reply(correlation_id: int, host_time: CMTime) -> bytes:
    """Create 44-byte RPLY packet carrying local monotonic CMTime."""
    return struct.pack("<IIQI", 44, MAGIC_RPLY, correlation_id, 0) + host_time.to_bytes()


def build_skew_reply(correlation_id: int, skew_hz: float = 48000.0) -> bytes:
    """Create 28-byte RPLY packet carrying audio clock skew in Hz."""
    return struct.pack("<IIQId", 28, MAGIC_RPLY, correlation_id, 0, skew_hz)


def build_zero_reply(correlation_id: int) -> bytes:
    """Create 24-byte RPLY packet carrying 8 zero bytes (OG/STOP)."""
    return struct.pack("<IIQQ", 24, MAGIC_RPLY, correlation_id, 0)


class PacketFramingBuffer:
    """Accumulates raw USB Bulk IN reads into discrete QVH frames (without length prefix)."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buf.extend(chunk)
        frames: list[bytes] = []
        while len(self._buf) >= 4:
            frame_len = struct.unpack("<I", self._buf[:4])[0]
            if frame_len < 8:
                raise QvhProtocolError(f"Invalid frame length {frame_len}")
            if len(self._buf) < frame_len:
                break
            frames.append(bytes(self._buf[4:frame_len]))
            del self._buf[:frame_len]
        return frames


class QvhSessionProcessor:
    """Stateful QVH handshake and AV sample extractor."""

    def __init__(
        self,
        write_cb: Callable[[bytes], None],
        on_video: Callable[[bytes, bool, int, bytes, bytes, int, int], None],
        on_audio: Callable[[bytes, int], None],
        audio_only: bool = False,
    ) -> None:
        self._write = write_cb
        self._on_video = on_video
        self._on_audio = on_audio
        self._audio_only = audio_only
        self._start_ns = time.monotonic_ns()
        self._device_audio_clock_ref = 0
        self._need_packet = b""
        self._last_need_time: float = 0.0
        self._sps = b""
        self._pps = b""
        self._width = 1920
        self._height = 1080
        self._first_audio_pts: CMTime | None = None
        self._first_audio_local_ns = 0
        self._last_audio_pts: CMTime | None = None
        self._last_audio_local_ns = 0
        self.released_count = 0

    def _local_cmtime(self) -> CMTime:
        elapsed = time.monotonic_ns() - self._start_ns
        return CMTime(value=elapsed, scale=NANOSECOND_SCALE, flags=1, epoch=0)

    def pace_need(self, force: bool = False) -> bool:
        """Send continuous ASYN NEED token to pace video stream and prevent deadlocks."""
        if not self._need_packet:
            return False
        now = time.monotonic()
        # Rate limit autonomous pacing to ~60 Hz (16ms) unless forced
        if force or (now - self._last_need_time >= 0.016):
            self._last_need_time = now
            self._write(self._need_packet)
            return True
        return False

    def handle_frame(self, frame: bytes) -> None:
        """Process one unframed QVH packet (starting at 4-byte magic)."""
        if len(frame) < 4:
            raise QvhProtocolError("Frame shorter than 4 bytes")
        magic = struct.unpack("<I", frame[:4])[0]
        if magic == MAGIC_PING:
            ping_payload = frame[4:12] if len(frame) >= 12 else None
            self._write(build_ping_packet(ping_payload))
            return
        if magic == MAGIC_SYNC:
            self._handle_sync(frame)
            return
        if magic == MAGIC_ASYN:
            self._handle_asyn(frame)
            return
        raise QvhProtocolError(f"Unknown outer QVH magic 0x{magic:08x}")

    def _handle_sync(self, frame: bytes) -> None:
        if len(frame) < 24:
            raise QvhProtocolError("SYNC packet truncated")
        clock_ref = struct.unpack("<Q", frame[4:12])[0]
        subtype = struct.unpack("<I", frame[12:16])[0]
        corr_id = struct.unpack("<Q", frame[16:24])[0]
        rem = frame[24:]

        if subtype == SYNC_CWPA:
            dev_clock = struct.unpack("<Q", rem[:8])[0]
            self._device_audio_clock_ref = dev_clock
            local_audio_ref = dev_clock + 1000
            if not self._audio_only:
                hpd1 = build_hpd1_packet()
                self._write(hpd1)
                self._write(hpd1)
            self._write(build_clock_reply(corr_id, local_audio_ref))
            self._write(build_hpa1_packet(dev_clock))
        elif subtype == SYNC_AFMT:
            self._write(build_afmt_reply(corr_id))
        elif subtype == SYNC_CVRP:
            dev_video_ref = struct.unpack("<Q", rem[:8])[0]
            self._need_packet = build_need_packet(dev_video_ref)
            self._last_need_time = time.monotonic()
            self._write(self._need_packet)
            self._write(build_clock_reply(corr_id, dev_video_ref + 0x1000AF))
        elif subtype == SYNC_CLOK:
            self._write(build_clock_reply(corr_id, clock_ref + 0x10000))
        elif subtype == SYNC_TIME:
            self._write(build_time_reply(corr_id, self._local_cmtime()))
        elif subtype == SYNC_SKEW:
            self._write(build_skew_reply(corr_id, self._compute_skew()))
        elif subtype in (SYNC_OG, SYNC_STOP):
            self._write(build_zero_reply(corr_id))
        else:
            raise QvhProtocolError(f"Unknown SYNC subtype 0x{subtype:08x}")

    def _handle_asyn(self, frame: bytes) -> None:
        if len(frame) < 16:
            raise QvhProtocolError("ASYN packet truncated")
        subtype = struct.unpack("<I", frame[12:16])[0]
        payload = frame[16:]

        if subtype == ASYN_FEED:
            sbuf = parse_sample_buffer(payload, MAGIC_VIDE)
            if sbuf.format_descriptor:
                fd = sbuf.format_descriptor
                if fd.sps and fd.pps:
                    self._sps = fd.sps
                    self._pps = fd.pps
                if fd.width and fd.height:
                    self._width = fd.width
                    self._height = fd.height
            if sbuf.sample_data:
                annex_b, is_key = avcc_to_annex_b(sbuf.sample_data, self._sps, self._pps)
                if annex_b:
                    self._on_video(
                        annex_b,
                        is_key,
                        sbuf.pts.to_microseconds(),
                        self._sps,
                        self._pps,
                        self._width,
                        self._height,
                    )
            if self._need_packet:
                self._last_need_time = time.monotonic()
                self._write(self._need_packet)
        elif subtype == ASYN_EAT:
            sbuf = parse_sample_buffer(payload, MAGIC_SOUN)
            now_ns = time.monotonic_ns()
            if self._first_audio_pts is None:
                self._first_audio_pts = sbuf.pts
                self._first_audio_local_ns = now_ns
            self._last_audio_pts = sbuf.pts
            self._last_audio_local_ns = now_ns
            if sbuf.sample_data:
                self._on_audio(sbuf.sample_data, sbuf.pts.to_microseconds())
        elif subtype == ASYN_RELS:
            self.released_count += 1
        elif subtype in (ASYN_SPRP, ASYN_TJMP, ASYN_SRAT, ASYN_TBAS):
            pass

    def _compute_skew(self) -> float:
        if (
            self._first_audio_pts is None
            or self._last_audio_pts is None
            or self._last_audio_local_ns <= self._first_audio_local_ns
        ):
            return 48000.0
        dev_us = self._last_audio_pts.to_microseconds() - self._first_audio_pts.to_microseconds()
        local_us = (self._last_audio_local_ns - self._first_audio_local_ns) / 1000.0
        if dev_us <= 0 or local_us <= 0:
            return 48000.0
        ratio = dev_us / local_us
        return max(47500.0, min(48500.0, 48000.0 * ratio))

    def close_session(self) -> None:
        if self._device_audio_clock_ref:
            self._write(build_hpa0_packet(self._device_audio_clock_ref))
        self._write(build_hpd0_packet())
