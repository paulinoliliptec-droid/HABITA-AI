import { describe, expect, it } from "vitest";
import verified from "./fixtures/verified-report.json";
import { buildPostIts } from "./postits";
import type { PermitReport } from "./types";

// The fixture is the backend's own report for a real end-to-end Cascais run (scripted model, VERIFIED conditional),
// so these tests check the map against the same JSON the PDF is rendered from (AC4.5, AC6.6).
const report = verified as unknown as PermitReport;
const note = (r: PermitReport, id: string) => buildPostIts(r).find((n) => n.id === id)!;

describe("map post-its (HR-004)", () => {
  it("shows exactly the report's assessment status", () => {
    expect(report.assessment!.status).toBe("VERIFIED");
    expect(note(report, "assessment").badge).toBe("Verified");
    for (const [status, badge] of [["REJECTED", "Rejected"], ["PENDING_CONFIRMATION", "Pending confirmation"]] as const) {
      const other = { ...report, assessment: { ...report.assessment!, status, content_verified: false } };
      expect(note(other, "assessment").badge).toBe(badge);
      expect(note(other, "assessment").lines.join(" ")).toContain("Not verified:");
    }
  });

  it("lists the same evidence ids as the report, and links each official document", () => {
    const sources = note(report, "sources");
    expect(sources.lines.map((l) => l.split(" · ")[0])).toEqual(report.assessment!.evidence.map((e) => e.evidence_id));
    expect(sources.links.length).toBeGreaterThan(0);
    for (const l of sources.links) expect(l.url).toMatch(/^https:\/\//);
  });

  it("states the absence of a verified zoning layer and never shows a classification without one", () => {
    expect(report.planning.verified_zoning).toBe(false);
    const zoning = note(report, "planning");
    expect(zoning.badge).toBe("No verified layer");
    expect(zoning.lines[0]).toContain("No verified zoning layer");
    const sneaky = { ...report, planning: { ...report.planning, classification: "Espaços centrais" } };
    expect(note(sneaky, "planning").lines.join(" ")).not.toContain("Espaços centrais");
    const verifiedLayer = { ...report, planning: { ...report.planning, verified_zoning: true, classification: "Espaços centrais" } };
    expect(note(verifiedLayer, "planning").lines[0]).toBe("Espaços centrais");
  });

  it("without an assessment, shows the jurisdiction's official sources", () => {
    const propertyOnly = { ...report, assessment: null };
    expect(buildPostIts(propertyOnly).map((n) => n.id)).toEqual(["property", "planning", "sources"]);
    expect(note(propertyOnly, "sources").lines.length).toBe(report.sources.length);
  });
});
