import { describe, expect, it } from "vitest";
import { OUTCOME, evidenceBasis, phaseOf, sourcesLine } from "./present";
import { STABLE_STATES } from "./types";

describe("phaseOf", () => {
  it("maps workflow states onto Goal → Investigation → Evidence → Result", () => {
    expect(phaseOf("PLANNING")).toEqual({ phase: "Goal", done: false });
    expect(phaseOf("INVESTIGATING")).toEqual({ phase: "Investigation", done: false });
    // Waiting for the user's facts keeps the investigation current; Evidence is not reached yet.
    expect(phaseOf("NEEDS_INPUT")).toEqual({ phase: "Investigation", done: false, waiting: true });
    expect(phaseOf("VERIFYING")).toEqual({ phase: "Result", done: false });
    expect(phaseOf("VERIFIED")).toEqual({ phase: "Result", done: true });
    expect(phaseOf("ESCALATE")).toEqual({ phase: "Result", done: true });
    expect(phaseOf("REJECTED")).toEqual({ phase: "Result", done: true });
  });

  it("shows a failure at the phase where it happened, unfinished", () => {
    expect(phaseOf("FAILED", "INVESTIGATING")).toEqual({ phase: "Investigation", done: false });
  });
});

describe("sourcesLine", () => {
  it("states what HABITA already checked and what it still needs", () => {
    expect(sourcesLine(11, 3)).toBe("11 sources checked · 3 facts still needed from you");
    expect(sourcesLine(1, 1)).toBe("1 source checked · 1 fact still needed from you");
    expect(sourcesLine(14, 0)).toBe("14 sources checked");
  });
});

describe("outcomes", () => {
  it("only a verified matter is presented as verified", () => {
    const verified = Object.entries(OUTCOME).filter(([, o]) => o.label.startsWith("Verified"));
    expect(verified.map(([state]) => state)).toEqual(["VERIFIED"]);
    // An assessment, never a permit or approval.
    expect(Object.values(OUTCOME).some((o) => /permit|approv|authori[sz]/i.test(o.label))).toBe(false);
    expect([...STABLE_STATES].sort()).toEqual(["ESCALATE", "FAILED", "NEEDS_INPUT", "REJECTED", "VERIFIED"]);
  });
});

describe("evidenceBasis", () => {
  const base = {
    evidence_id: "E1", source_title: "t", source_reference: "r", source_url: null, jurisdiction_id: "pt", excerpt: "x",
  } as const;
  it("distinguishes official text, curated references and planning context", () => {
    expect(evidenceBasis({ ...base, source_type: "regulatory_source", verification_status: "official_text",
      provenance: { source_id: "cascais-pdm", basis: "official_text", trust_status: "trusted", version: null,
        locator: "Artigo 61.º", snapshot_id: "ss_1", sha256: "a", retrieved_at: "2026-10-28T03:31:00Z" } }))
      .toBe("Official text · retrieved 28 Oct 2026");
    expect(evidenceBasis({ ...base, source_type: "regulatory_source", verification_status: "curated_reference" }))
      .toBe("Curated reference — check the official text");
    expect(evidenceBasis({ ...base, source_type: "planning_context", verification_status: "system_record" }))
      .toBe("Official planning sources");
  });
});

describe("MU-9 legacy results", () => {
  it("never present a superseded VERIFIED matter as a current verified assessment", async () => {
    const { outcomeOf } = await import("./present");
    expect(outcomeOf({ state: "VERIFIED", assessment_status: "verified_assessment" }).label).toBe("Verified assessment");
    const legacy = outcomeOf({ state: "VERIFIED", assessment_status: "superseded_assessment" });
    expect(legacy.label).toContain("Superseded");
    expect(legacy.tone).toBe("warning");
  });
});
