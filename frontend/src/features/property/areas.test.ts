import { describe, expect, it } from "vitest";
import { AREAS, areaFromHash, DEFAULT_AREA } from "./areas";

describe("workspace areas", () => {
  it("opens the area a link names", () => {
    expect(areaFromHash("#costs")).toBe("costs");
    expect(areaFromHash("documents")).toBe("documents");
  });

  it("falls back to the question for an unknown or empty hash", () => {
    expect(areaFromHash("")).toBe(DEFAULT_AREA);
    expect(areaFromHash("#nope")).toBe(DEFAULT_AREA);
    expect(DEFAULT_AREA).toBe("question");
  });

  it("starts with the question, where people look first", () => {
    expect(AREAS[0].id).toBe("question");
  });
});
