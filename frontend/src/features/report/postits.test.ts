import { describe, expect, it } from "vitest";
import { english } from "@/i18n/core";
import verified from "./fixtures/verified-report.json";
import { buildPostIts } from "./postits";
import { groupOf, profileCounts, profileSummary } from "./profile";
import { nodeIcon } from "./reasoningGraph";
import type { PermitReport, ProfileItem } from "./types";

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

  it("lists the same evidence ids as the report, and links each cited document", () => {
    const cited = note(report, "evidence");
    expect(cited.lines.map((l) => l.split(" · ")[0])).toEqual(report.assessment!.evidence.map((e) => e.evidence_id));
    expect(cited.links.length).toBeGreaterThan(0);
    for (const l of cited.links) expect(l.url).toMatch(/^https:\/\//);
  });

  it("keeps the jurisdiction's official sources visible next to the evidence", () => {
    expect(note(report, "sources").lines.length).toBe(report.sources.length);
  });

  it("states the absence of a verified zoning layer and never shows a classification without one", () => {
    expect(report.planning.verified_zoning).toBe(false);
    const zoning = note(report, "planning");
    expect(zoning.badge).toBe("Zoning not verified");
    expect(zoning.lines[0]).toContain("Zoning not verified");
    const sneaky = { ...report, planning: { ...report.planning, classification: "Espaços centrais" } };
    expect(note(sneaky, "planning").lines.join(" ")).not.toContain("Espaços centrais");
    const verifiedLayer = { ...report, planning: { ...report.planning, verified_zoning: true, classification: "Espaços centrais" } };
    expect(note(verifiedLayer, "planning").lines[0]).toBe("Espaços centrais");
  });

  it("without an assessment, states the pending analysis and shows the jurisdiction's official sources", () => {
    const propertyOnly = { ...report, assessment: null, pending: ["Planning classification: confirm on the official maps."] };
    expect(buildPostIts(propertyOnly).map((n) => n.id)).toEqual(["property", "planning", "assessment", "sources"]);
    const status = note(propertyOnly, "assessment");
    expect(status.title).toBe("Analysis status");
    expect(status.badge).toBe("Pending confirmation");
    expect(status.lines.join(" ")).toContain("No permit assessment yet");
    expect(status.lines).toContain("Planning classification: confirm on the official maps.");
    expect(buildPostIts(report).map((n) => n.id)).toEqual(["property", "planning", "assessment", "risks", "evidence", "sources"]);
    expect(note(propertyOnly, "sources").lines.length).toBe(report.sources.length);
  });
});

describe("property post-it (HR-004)", () => {
  it("identifies and locates the property, with municipality and authority, never as a parcel", () => {
    const lines = note(report, "property").lines;
    expect(lines[0]).toBe(report.property.address);
    expect(lines.join(" ")).toContain(`${report.property.lat.toFixed(6)}, ${report.property.lng.toFixed(6)}`);
    expect(lines.join(" ")).toContain("not a parcel boundary");
    expect(lines.some((l) => l.startsWith("Municipality:"))).toBe(true);
    expect(lines.join(" ")).toContain(`Competent authority: ${report.property.authority}`);
    const coarse = { ...report, property: { ...report.property, precision: "area_center" } };
    expect(note(coarse, "property").lines.join(" ")).toContain("approximate, area center");
    const unmodelled = { ...report, property: { ...report.property, jurisdiction: ["Country: United States"] } };
    expect(note(unmodelled, "property").lines).toContain("Municipality: not modelled for this jurisdiction");
  });
});

describe("property profile (HR-008)", () => {
  const item = (over: Partial<ProfileItem>): ProfileItem =>
    ({ key: "k", label: "L", value: "v", kind: "observation", origin: "o", as_of: null, precision: null, url: null, conflict: false, ...over });

  it("keeps an unknown out of the fact groups, whatever kind it would have been", () => {
    expect(groupOf(item({ kind: "official", value: null }))).toBe("unconfirmed");
    expect(groupOf(item({ kind: "official" }))).toBe("official");
    expect(groupOf(item({ kind: "declaration" }))).toBe("declaration");
  });

  it("counts each group and leaves empty ones out of the map's line", () => {
    const profile = [item({ kind: "official", value: null }), item({}), item({}), item({ kind: "declaration" })];
    const report = { profile } as PermitReport;
    expect(profileCounts(report)).toEqual({ official: 0, observation: 2, declaration: 1, unconfirmed: 1 });
    expect(profileSummary(report, english)).toBe("2 Observations · 1 Declarations · 1 Not confirmed");
  });

  it("gives every graph step a symbol, with a neutral one for the unknown", () => {
    expect(nodeIcon("conclusion")).toBe("scale");
    expect(nodeIcon("something new")).toBe("info");
  });
});
