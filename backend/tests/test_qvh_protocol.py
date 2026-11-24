"""Unit tests for the QuickTime USB AV (QVH) protocol encoder/decoder."""

from __future__ import annotations

import struct

import pytest

from app.usb.qvh_protocol import (
    ASYN_EAT,
    ASYN_FEED,
    ASYN_HPA0,
    ASYN_HPA1,
    ASYN_HPD0,
    ASYN_HPD1,
    ASYN_NEED,
    ASYN_RELS,
    MAGIC_ASBD,
    MAGIC_ASYN,
    MAGIC_AVC1,
    MAGIC_CODC,
    MAGIC_DATV,
    MAGIC_EXTN,
    MAGIC_FDSC,
    MAGIC_IDXK,
    MAGIC_KEYV,
    MAGIC_MDIA,
    MAGIC_OPTS,
    MAGIC_PING,
    MAGIC_RPLY,
    MAGIC_SBUF,
    MAGIC_SDAT,
    MAGIC_SOUN,
    MAGIC_SYNC,
    MAGIC_VDIM,
    MAGIC_VIDE,
    NANOSECOND_SCALE,
    SYNC_AFMT,
    SYNC_CLOK,
    SYNC_CVRP,
    SYNC_CWPA,
    SYNC_OG,
    SYNC_SKEW,
    SYNC_STOP,
    SYNC_TIME,
    AudioStreamBasicDescription,
    CMTime,
    NSNumber,
    PacketFramingBuffer,
    QvhProtocolError,
    QvhSessionProcessor,
    avcc_to_annex_b,
    codec_string_from_sps,
    parse_dict,
    parse_format_descriptor,
    parse_sample_buffer,
    serialize_string_dict,
)


def _wrap_frame(body: bytes) -> bytes:
    return struct.pack("<I", len(body) + 4) + body


def _make_idx_dict(entries: dict[int, bytes | dict], magic: int) -> bytes:
    parts: list[bytes] = []
    for k, val in entries.items():
        k_chunk = struct.pack("<IIH", 10, MAGIC_IDXK, k)
        if isinstance(val, dict):
            v_chunk = _make_idx_dict(val, 0x64696374)
        else:
            v_chunk = struct.pack("<II", 8 + len(val), MAGIC_DATV) + val
        entry = struct.pack("<II", 8 + len(k_chunk) + len(v_chunk), MAGIC_KEYV)
        parts.append(entry + k_chunk + v_chunk)
    payload = b"".join(parts)
    return struct.pack("<II", 8 + len(payload), magic) + payload


def _make_video_fdsc(width: int, height: int, sps: bytes, pps: bytes) -> bytes:
    # ISO/IEC 14496-15 avcC stored in CoreMedia extension key 49 -> key 105: SPS first, then PPS
    profile_triple = sps[1:4] if len(sps) >= 4 else b"\x64\x00\x28"
    avcc_blob = (
        b"\x01"
        + profile_triple
        + b"\xff\xe1"
        + struct.pack(">H", len(sps))
        + sps
        + b"\x01"
        + struct.pack(">H", len(pps))
        + pps
    )
    extn = _make_idx_dict({49: {105: bytes(avcc_blob)}}, MAGIC_EXTN)
    mdia = struct.pack("<III", 12, MAGIC_MDIA, MAGIC_VIDE)
    vdim = struct.pack("<IIII", 16, MAGIC_VDIM, width, height)
    codc = struct.pack("<III", 12, MAGIC_CODC, MAGIC_AVC1)
    inner = mdia + vdim + codc + extn
    return struct.pack("<II", 8 + len(inner), MAGIC_FDSC) + inner


def test_nsnumber_and_string_dict_roundtrip() -> None:
    raw = serialize_string_dict(
        {
            "Valeria": True,
            "Latency": NSNumber(6, 0.04),
            "Count": NSNumber(3, 42),
            "Nested": {"Name": "iPhone 16 Pro Max"},
        }
    )
    parsed = parse_dict(raw)
    assert parsed["Valeria"] is True
    assert parsed["Latency"].value == pytest.approx(0.04)
    assert parsed["Count"].value == 42
    assert parsed["Nested"]["Name"] == "iPhone 16 Pro Max"


def test_avcc_to_annex_b_prepends_sps_pps_on_idr() -> None:
    sps = b"\x67\x64\x00\x28\xac\xd9"
    pps = b"\x68\xeb\xe3\xcb\x22\xc0"
    idr_nalu = b"\x65\x88\x84\x21"
    non_idr = b"\x41\x9a\x22\x11"

    avcc_idr = struct.pack(">I", len(idr_nalu)) + idr_nalu
    annex_idr, is_key = avcc_to_annex_b(avcc_idr, sps, pps)
    assert is_key is True
    assert annex_idr == (
        b"\x00\x00\x00\x01" + sps + b"\x00\x00\x00\x01" + pps + b"\x00\x00\x00\x01" + idr_nalu
    )
    assert codec_string_from_sps(sps) == "avc1.640028"

    avcc_p = struct.pack(">I", len(non_idr)) + non_idr
    annex_p, is_key_p = avcc_to_annex_b(avcc_p, sps, pps)
    assert is_key_p is False
    assert annex_p == b"\x00\x00\x00\x01" + non_idr


def test_packet_framing_buffer_handles_split_chunks() -> None:
    buf = PacketFramingBuffer()
    f1 = _wrap_frame(struct.pack("<IQ", MAGIC_PING, 1))
    f2 = _wrap_frame(struct.pack("<IQ", MAGIC_PING, 2))
    joined = f1 + f2
    out = []
    for i in range(0, len(joined), 3):
        out.extend(buf.feed(joined[i : i + 3]))
    assert len(out) == 2
    assert out[0] == struct.pack("<IQ", MAGIC_PING, 1)
    assert out[1] == struct.pack("<IQ", MAGIC_PING, 2)


def test_full_qvh_session_handshake_and_av_extraction() -> None:
    written: list[bytes] = []
    video_events: list[tuple[bytes, bool, int, bytes, bytes, int, int]] = []
    audio_events: list[tuple[bytes, int]] = []

    proc = QvhSessionProcessor(
        write_cb=written.append,
        on_video=lambda d, k, pts, s, p, w, h: video_events.append((d, k, pts, s, p, w, h)),
        on_audio=lambda pcm, pts: audio_events.append((pcm, pts)),
    )

    # 1. PING
    proc.handle_frame(struct.pack("<IQ", MAGIC_PING, 0x0000000100000000))
    assert struct.unpack("<II", written[-1][:8]) == (16, MAGIC_PING)

    # 2. SYNC CWPA
    written.clear()
    proc.handle_frame(struct.pack("<IQIQQ", MAGIC_SYNC, 1, SYNC_CWPA, 1001, 0xAAAA))
    assert any(struct.unpack("<II", p[:8]) == (28, MAGIC_RPLY) for p in written)
    asyn_types = [
        struct.unpack("<I", p[16:20])[0]
        for p in written
        if struct.unpack("<II", p[:8])[1] == MAGIC_ASYN
    ]
    assert ASYN_HPD1 in asyn_types
    assert ASYN_HPA1 in asyn_types

    # 3. SYNC AFMT
    written.clear()
    asbd = AudioStreamBasicDescription().to_bytes()[:40]
    proc.handle_frame(struct.pack("<IQIQ", MAGIC_SYNC, 0xBBBB, SYNC_AFMT, 1002) + asbd)
    assert struct.unpack("<IIQ", written[0][:16]) == (len(written[0]), MAGIC_RPLY, 1002)

    # 4. SYNC CVRP
    written.clear()
    cvrp_dict = serialize_string_dict({"Width": NSNumber(3, 1920)})
    proc.handle_frame(struct.pack("<IQIQQ", MAGIC_SYNC, 1, SYNC_CVRP, 1003, 0xCCCC) + cvrp_dict)
    assert struct.unpack("<I", written[0][16:20])[0] == ASYN_NEED
    assert struct.unpack("<IIQ", written[1][:16]) == (28, MAGIC_RPLY, 1003)

    # 5. SYNC CLOK, TIME, SKEW, OG
    written.clear()
    proc.handle_frame(struct.pack("<IQIQ", MAGIC_SYNC, 0xDDDD, SYNC_CLOK, 1004))
    proc.handle_frame(struct.pack("<IQIQ", MAGIC_SYNC, 0xDDDD, SYNC_TIME, 1005))
    proc.handle_frame(struct.pack("<IQIQ", MAGIC_SYNC, 0xDDDD, SYNC_SKEW, 1006))
    proc.handle_frame(struct.pack("<IQIQI", MAGIC_SYNC, 0xDDDD, SYNC_OG, 1007, 1))
    assert len(written) == 4
    assert len(written[1]) == 44

    # 6. ASYN FEED with FDSC + IDR AVCC
    written.clear()
    sps = b"\x67\x64\x00\x28\xac\xd9"
    pps = b"\x68\xeb\xe3\xcb\x22\xc0"
    fdsc = _make_video_fdsc(1179, 2556, sps, pps)
    idr = b"\x65\x88\x84\x21"
    sdat_payload = struct.pack(">I", len(idr)) + idr
    sdat = struct.pack("<II", 8 + len(sdat_payload), MAGIC_SDAT) + sdat_payload
    opts = struct.pack("<II", 32, MAGIC_OPTS) + CMTime(500_000_000, NANOSECOND_SCALE).to_bytes()
    sbuf_body = opts + fdsc + sdat
    sbuf = struct.pack("<II", 8 + len(sbuf_body), MAGIC_SBUF) + sbuf_body
    proc.handle_frame(struct.pack("<IQI", MAGIC_ASYN, 0x1000AF, ASYN_FEED) + sbuf)
    assert len(video_events) == 1
    assert video_events[0][1] is True
    assert video_events[0][2] == 500_000
    assert video_events[0][3] == sps
    assert video_events[0][4] == pps
    assert video_events[0][5:] == (1179, 2556)
    assert struct.unpack("<I", written[0][16:20])[0] == ASYN_NEED

    # 7. ASYN EAT! audio LPCM
    pcm_raw = b"\x10\x00\x20\x00" * 16
    sdat_a = struct.pack("<II", 8 + len(pcm_raw), MAGIC_SDAT) + pcm_raw
    opts_a = struct.pack("<II", 32, MAGIC_OPTS) + CMTime(250_000_000, NANOSECOND_SCALE).to_bytes()
    sbuf_a_body = opts_a + sdat_a
    sbuf_a = struct.pack("<II", 8 + len(sbuf_a_body), MAGIC_SBUF) + sbuf_a_body
    proc.handle_frame(struct.pack("<IQI", MAGIC_ASYN, 0xAAAA, ASYN_EAT) + sbuf_a)
    assert len(audio_events) == 1
    assert audio_events[0] == (pcm_raw, 250_000)

    # 8. Close session + RELS + STOP
    written.clear()
    proc.close_session()
    assert struct.unpack("<I", written[0][16:20])[0] == ASYN_HPA0
    assert struct.unpack("<I", written[1][16:20])[0] == ASYN_HPD0
    proc.handle_frame(struct.pack("<IQI", MAGIC_ASYN, 0x1000AF, ASYN_RELS))
    assert proc.released_count == 1
    proc.handle_frame(struct.pack("<IQIQ", MAGIC_SYNC, 0x1000AF, SYNC_STOP, 1008))


def test_parse_sound_fdsc_and_invalid_magic_error() -> None:
    asbd = AudioStreamBasicDescription().to_bytes()[:40]
    mdia = struct.pack("<III", 12, MAGIC_MDIA, MAGIC_SOUN)
    asbd_chunk = struct.pack("<II", 8 + len(asbd), MAGIC_ASBD) + asbd
    fdsc = struct.pack("<II", 8 + len(mdia) + len(asbd_chunk), MAGIC_FDSC) + mdia + asbd_chunk
    parsed = parse_format_descriptor(fdsc)
    assert parsed.asbd is not None
    assert parsed.asbd.sample_rate == pytest.approx(48000.0)
    assert parsed.asbd.channels_per_frame == 2

    with pytest.raises(QvhProtocolError):
        parse_sample_buffer(b"BAD!", MAGIC_VIDE)


def test_ping_echo_preserves_device_payload_and_16_byte_size() -> None:
    from app.usb.qvh_protocol import build_ping_packet

    custom_payload = b"\x12\x34\x56\x78\x9a\xbc\xde\xf0"
    ping_pkt = build_ping_packet(custom_payload)
    assert len(ping_pkt) == 16
    pkt_len, magic = struct.unpack("<II", ping_pkt[:8])
    assert pkt_len == 16
    assert magic == MAGIC_PING
    assert ping_pkt[8:] == custom_payload

    # Default payload test
    default_ping = build_ping_packet()
    assert len(default_ping) == 16
    assert default_ping[:8] == struct.pack("<II", 16, MAGIC_PING)


def test_pace_need_continuous_pacing_and_rate_limiting() -> None:
    written: list[bytes] = []
    proc = QvhSessionProcessor(
        write_cb=written.append,
        on_video=lambda *args: None,
        on_audio=lambda *args: None,
    )

    # Before CVRP is received, pace_need does nothing
    assert proc.pace_need() is False
    assert len(written) == 0

    # Simulate CVRP
    cvrp_dict = serialize_string_dict({"Width": NSNumber(3, 1920)})
    proc.handle_frame(struct.pack("<IQIQQ", MAGIC_SYNC, 1, SYNC_CVRP, 5001, 0x123456) + cvrp_dict)
    assert len(written) == 2  # initial ASYN NEED + clock reply
    assert struct.unpack("<I", written[0][16:20])[0] == ASYN_NEED
    written.clear()

    # Immediate pace_need should return False due to ~16ms rate limiting unless forced
    assert proc.pace_need(force=False) is False
    assert len(written) == 0

    # Forced pace_need sends immediately
    assert proc.pace_need(force=True) is True
    assert len(written) == 1
    assert struct.unpack("<I", written[0][16:20])[0] == ASYN_NEED


def test_afmt_reply_carries_status_zero_and_error_zero() -> None:
    from app.usb.qvh_protocol import build_afmt_reply

    reply = build_afmt_reply(correlation_id=9999)
    total_len, magic, corr_id, status = struct.unpack("<IIQI", reply[:20])
    assert total_len == len(reply)
    assert magic == MAGIC_RPLY
    assert corr_id == 9999
    assert status == 0

    body = parse_dict(reply[20:])
    assert "Error" in body
    assert body["Error"].value == 0


def test_real_iphone_avcc_sps_pps_order() -> None:
    # Exact SPS (type 7) and PPS (type 8) captured from QVH cmformatdescription_test.go
    real_sps = bytes.fromhex("27640033AC5680470133E69E6E04040404")
    real_pps = bytes.fromhex("28EE3CB0")
    fdsc = _make_video_fdsc(1920, 1080, real_sps, real_pps)
    parsed = parse_format_descriptor(fdsc)
    assert parsed.sps == real_sps
    assert parsed.pps == real_pps
    assert codec_string_from_sps(parsed.sps) == "avc1.640033"


def test_cmtime_and_asbd_serialization_roundtrip() -> None:
    # 1. CMTime normal conversion and roundtrip
    t = CMTime(value=1_500_000, scale=1_000_000, flags=1, epoch=0)
    assert t.to_microseconds() == 1_500_000
    packed_t = t.to_bytes()
    assert len(packed_t) == 24
    unpacked_t = CMTime.from_bytes(packed_t)
    assert unpacked_t == t

    # 2. CMTime zero scale boundary and negative scale
    assert CMTime(value=1000, scale=0).to_microseconds() == 0
    assert CMTime(value=1000, scale=-1).to_microseconds() == 0

    # 3. CMTime truncated buffer error
    with pytest.raises(QvhProtocolError, match="CMTime requires 24 bytes"):
        CMTime.from_bytes(b"\x00" * 23)

    # 4. AudioStreamBasicDescription pack/unpack roundtrip
    asbd = AudioStreamBasicDescription(
        sample_rate=44100.0,
        format_id=0x6C70636D,
        format_flags=12,
        bytes_per_packet=4,
        frames_per_packet=1,
        bytes_per_frame=4,
        channels_per_frame=2,
        bits_per_channel=16,
        reserved=0,
    )
    asbd_raw = asbd.to_bytes()
    assert len(asbd_raw) == 56
    unpacked_asbd = AudioStreamBasicDescription.from_bytes(asbd_raw[:40])
    assert unpacked_asbd.sample_rate == pytest.approx(44100.0)
    assert unpacked_asbd.channels_per_frame == 2
    assert unpacked_asbd.bits_per_channel == 16
    assert unpacked_asbd.bytes_per_frame == 4
    assert unpacked_asbd.format_flags == 12

    # 5. ASBD truncated buffer error
    with pytest.raises(QvhProtocolError, match="ASBD requires >= 40 bytes"):
        AudioStreamBasicDescription.from_bytes(b"\x00" * 39)
