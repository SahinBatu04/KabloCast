import { describe, expect, it } from "vitest";
import { parseKabloPacket, TYPE_VIDEO_FRAME } from "./streamClient";

describe("parseKabloPacket", () => {
  it("parses valid 16-byte KC header + payload", () => {
    const payload = Uint8Array.from([0, 0, 0, 1, 0x65, 0x88]);
    const buf = new ArrayBuffer(16 + payload.length);
    const view = new DataView(buf);
    view.setUint8(0, 0x4b);
    view.setUint8(1, 0x43);
    view.setUint8(2, TYPE_VIDEO_FRAME);
    view.setUint8(3, 1);
    view.setBigUint64(4, 33333n, true);
    view.setUint32(12, payload.length, true);
    new Uint8Array(buf, 16).set(payload);

    const parsed = parseKabloPacket(buf);
    expect(parsed).not.toBeNull();
    expect(parsed?.ptype).toBe(TYPE_VIDEO_FRAME);
    expect(parsed?.flags).toBe(1);
    expect(parsed?.ptsUs).toBe(33333);
    expect(Array.from(parsed?.payload ?? [])).toEqual(Array.from(payload));
  });

  it("rejects truncated or wrong-magic buffers", () => {
    const bad = new ArrayBuffer(12);
    expect(parseKabloPacket(bad)).toBeNull();

    const wrongMagic = new ArrayBuffer(16);
    new DataView(wrongMagic).setUint8(0, 0x58);
    expect(parseKabloPacket(wrongMagic)).toBeNull();
  });
});
