import { describe, expect, it } from "vitest";
import { concat, downsample, encodeWav } from "./wav";

describe("dictation audio", () => {
  it("downsamples 48 kHz to 16 kHz by averaging", () => {
    const out = downsample(new Float32Array([0, 0.3, 0.6, 1, 1, 1]), 48000);
    expect(Array.from(out).map((v) => Math.round(v * 100) / 100)).toEqual([0.3, 1]);
  });

  it("leaves 16 kHz as it is and refuses to upsample", () => {
    const same = new Float32Array([0.1, 0.2]);
    expect(downsample(same, 16000)).toBe(same);
    expect(() => downsample(same, 8000)).toThrow();
  });

  it("writes a 16-bit mono PCM WAV header and clamps samples", async () => {
    const blob = encodeWav(new Float32Array([0, 1, -1, 2]));
    const view = new DataView(await blob.arrayBuffer());
    const text = (o: number) => String.fromCharCode(...[0, 1, 2, 3].map((i) => view.getUint8(o + i)));
    expect(blob.type).toBe("audio/wav");
    expect([text(0), text(8), text(12), text(36)]).toEqual(["RIFF", "WAVE", "fmt ", "data"]);
    expect([view.getUint16(20, true), view.getUint16(22, true), view.getUint32(24, true), view.getUint16(34, true)]).toEqual([1, 1, 16000, 16]);
    expect(view.getUint32(40, true)).toBe(8);
    expect([view.getInt16(46, true), view.getInt16(48, true), view.getInt16(50, true)]).toEqual([32767, -32768, 32767]);
  });

  it("joins chunks in order", () => {
    expect(Array.from(concat([new Float32Array([1]), new Float32Array([2, 3])]))).toEqual([1, 2, 3]);
  });
});
