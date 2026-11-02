import { describe, expect, it } from "vitest";
import { inePeriod } from "./inePeriod";

describe("INE periods", () => {
  it("are said in English for English readers", () => {
    expect(inePeriod("2.º Trimestre de 2026", "en")).toBe("Q2 2026");
    expect(inePeriod("Setembro de 2026", "en")).toBe("September 2026");
  });
  it("stay as INE wrote them otherwise", () => {
    expect(inePeriod("Setembro de 2026", "pt")).toBe("Setembro de 2026");
    expect(inePeriod("2026", "en")).toBe("2026");
  });
});
