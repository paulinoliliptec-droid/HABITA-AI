import { describe, expect, it } from "vitest";
import { instrumentName, officialTextSource, PLANNING_STATUS, provenanceDate, type OfficialSource } from "./planning";

describe("planning context presentation", () => {
  it("names the instrument by its official short name", () => {
    expect(instrumentName("Plano Diretor Municipal de Cascais (PDM-Cascais) — Regulamento")).toBe("PDM-Cascais");
    expect(instrumentName("Plano de Pormenor — Regulamento")).toBe("Plano de Pormenor");
  });

  it("never presents a manual-confirmation status as determined", () => {
    expect(PLANNING_STATUS.requires_manual_confirmation).toEqual({ label: "Requires confirmation", tone: "warning" });
    expect(PLANNING_STATUS.resolved.tone).toBe("positive");
  });

  it("formats verification and retrieval dates, ignoring missing or invalid ones", () => {
    expect(provenanceDate("2026-10-28", "Sources verified")).toBe("Sources verified 28 Oct 2026");
    expect(provenanceDate("2026-10-28T03:31:00Z", "Regulation text retrieved")).toBe("Regulation text retrieved 28 Oct 2026");
    expect(provenanceDate(null, "x")).toBeNull();
    expect(provenanceDate("not a date", "x")).toBeNull();
  });

  it("finds the instrument's official text only once it has been retrieved", () => {
    const pdm: OfficialSource = {
      source_id: "cascais-pdm", jurisdiction_id: "pt/lisboa/cascais", title: "PDM", official_url: null,
      designation: null, retrieval_method: "http_pdf", snapshot_retrieved_at: null,
    };
    expect(officialTextSource([pdm], "cascais-pdm")).toBeUndefined();
    const retrieved = { ...pdm, snapshot_retrieved_at: "2026-10-28T03:31:00Z" };
    expect(officialTextSource([retrieved], "cascais-pdm")).toBe(retrieved);
  });
});
