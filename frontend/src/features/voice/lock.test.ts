import { describe, expect, it } from "vitest";
import { claim, release } from "./lock";

describe("one dictation at a time", () => {
  it("lets one box hold the microphone until it releases it", () => {
    const a = {};
    const b = {};
    expect(claim(a)).toBe(true);
    expect(claim(a)).toBe(true);
    expect(claim(b)).toBe(false);
    release(b); // not the holder: nothing changes
    expect(claim(b)).toBe(false);
    release(a);
    expect(claim(b)).toBe(true);
    release(b);
  });
});
