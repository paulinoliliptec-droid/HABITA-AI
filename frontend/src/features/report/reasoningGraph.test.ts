import { describe, expect, it } from "vitest";
import { translator } from "@/i18n/core";
import verified from "./fixtures/verified-report.json";
import { buildGraph, edgeKey, flowOf, layout, revealDelays } from "./reasoningGraph";
import type { PermitReport } from "./types";

// The fixture is the backend's own report, so every relation below is checked against the JSON the PDF is rendered from.
const report = verified as unknown as PermitReport;
const a = report.assessment!;
const node = (r: PermitReport, id: string) => buildGraph(r).nodes.find((n) => n.id === id);
const withAssessment = (over: Partial<PermitReport["assessment"] & object>) =>
  ({ ...report, assessment: { ...a, ...over } }) as PermitReport;

describe("reasoning graph (HR-005)", () => {
  it("reads property → rules → evidence → conclusion → documents → next steps", () => {
    const { nodes } = buildGraph(report);
    expect(nodes.find((n) => n.id === "property")!.column).toBe(0);
    expect(nodes.find((n) => n.id === "planning")!.column).toBe(1);
    expect(nodes.find((n) => n.id === "conclusion")!.column).toBe(3);
    expect(nodes.find((n) => n.id === "documents")!.column).toBe(4);
    expect(nodes.find((n) => n.id === "actions")!.column).toBe(5);
  });

  it("draws every edge between existing nodes, once", () => {
    const { nodes, edges } = buildGraph(report);
    const ids = new Set(nodes.map((n) => n.id));
    for (const e of edges) expect(ids.has(e.from) && ids.has(e.to)).toBe(true);
    expect(new Set(edges.map((e) => `${e.from}>${e.to}`)).size).toBe(edges.length);
  });

  it("links the conclusion only to the evidence it cites, naming exactly those ids", () => {
    const only = a.evidence[0].evidence_id;
    const graph = buildGraph(withAssessment({ conclusion_evidence_ids: [only] }));
    const toConclusion = graph.edges.filter((e) => e.to === "conclusion");
    expect(toConclusion).toHaveLength(1);
    expect(toConclusion[0].evidenceIds).toEqual([only]);
    const group = graph.nodes.find((n) => n.id === toConclusion[0].from)!;
    expect(group.lines.filter((l) => l.startsWith("Cited by Conclusion:"))).toEqual([`Cited by Conclusion: ${only}`]);
    expect(graph.nodes.find((n) => n.id === "conclusion")!.lines).toContain(`Evidence cited: ${only}`);
    expect(buildGraph(withAssessment({ conclusion_evidence_ids: [] })).edges.filter((e) => e.to === "conclusion")).toEqual([]);
  });

  it("names exactly which evidence comes from each rule node", () => {
    const edges = buildGraph(report).edges.filter((e) => ["planning", "authority", "jurisdiction"].includes(e.from) && e.evidenceIds);
    expect(edges.length).toBeGreaterThan(0);
    const types = { planning: "planning_context", authority: "authority_record", jurisdiction: "jurisdiction_record" };
    for (const edge of edges) {
      for (const id of edge.evidenceIds!) {
        expect(a.evidence.find((e) => e.evidence_id === id)!.source_type).toBe(types[edge.from as keyof typeof types]);
      }
    }
  });

  it("invents no link from conditions to the conclusion", () => {
    const { nodes, edges } = buildGraph(withAssessment({ conditions: ["Confirm with the authority."] }));
    expect(nodes.some((n) => n.id === "conditions")).toBe(true);
    expect(edges.some((e) => e.from === "conditions" || e.to === "conditions")).toBe(false);
  });

  it("shows each source's own status", () => {
    const sources = [{ ...report.sources[0], status: "candidate" }];
    expect(node({ ...report, sources }, "sources")!.lines[0]).toContain("candidate");
  });

  it("invents no link from findings or risks to the conclusion", () => {
    const edges = buildGraph(report).edges;
    expect(edges.some((e) => ["findings", "risks"].includes(e.from))).toBe(false);
  });

  it("links a statement group only to evidence its statements cite", () => {
    const statements = a.statements.map((s) => ({ ...s, evidence_ids: [] }));
    const { edges } = buildGraph(withAssessment({ statements }));
    expect(edges.filter((e) => ["findings", "risks", "procedure", "actions"].includes(e.to))).toEqual([]);
  });

  it("shows exactly the report's status at the conclusion", () => {
    expect(node(report, "conclusion")).toMatchObject({ text: "Verified", tone: "positive" });
    const rejected = node(withAssessment({ status: "REJECTED", content_verified: false }), "conclusion")!;
    expect(rejected).toMatchObject({ text: "Rejected", tone: "danger" });
    const pending = node(withAssessment({ status: "PENDING_CONFIRMATION", content_verified: false }), "conclusion")!;
    expect(pending).toMatchObject({ text: "Pending confirmation", tone: "warning" });
    expect(pending.lines.join(" ")).toContain("Not verified:");
  });

  it("never shows verified when the status and the content disagree", () => {
    const conflict = node(withAssessment({ status: "VERIFIED", content_verified: false }), "conclusion")!;
    expect(conflict).toMatchObject({ text: "Pending confirmation", tone: "warning" });
    expect(conflict.lines.join(" ")).toContain("Not verified:");
  });

  it.each([
    ["superseded record", { current: false, outcome: "VERIFIED" }],
    ["rejected record", { current: true, outcome: "REJECTED" }],
    ["no record", null],
  ])("never shows verified with a %s", (_, verification) => {
    const conclusion = node(withAssessment({ verification }), "conclusion")!;
    expect(conclusion).toMatchObject({ text: "Pending confirmation", tone: "warning" });
    expect(conclusion.lines.join(" ")).toContain("Not verified:");
  });

  it("never keeps the reason of a status it corrected", () => {
    const lines = node(withAssessment({ verification: { current: false, outcome: "VERIFIED" } }), "conclusion")!.lines;
    expect(lines).not.toContain(a.status_reason);
    expect(lines).toContain("The verification record does not support a verified result.");
  });

  it("marks statements of an unverified result as not verified", () => {
    const findings = node(withAssessment({ status: "PENDING_CONFIRMATION", content_verified: false }), "findings")!;
    expect(findings.tone).toBe("warning");
    expect(findings.lines[0]).toBe("Not verified");
  });

  it("states unverified zoning and shows a classification only from a verified layer", () => {
    expect(node(report, "planning")).toMatchObject({ text: "Zoning not verified", tone: "warning" });
    const claimed = { ...report, planning: { ...report.planning, verified_zoning: false, classification: "Espaço Central" } };
    expect(node(claimed, "planning")!.text).toBe("Zoning not verified");
    const zoned = { ...report, planning: { ...report.planning, verified_zoning: true, classification: "Espaço Central" } };
    expect(node(zoned, "planning")).toMatchObject({ text: "Espaço Central", tone: "positive" });
  });

  it("says the point is not a parcel boundary", () => {
    expect(node(report, "property")!.lines.join(" ")).toContain("not a parcel boundary");
  });

  it("works with no assessment: pending, and no evidence", () => {
    const { nodes, edges } = buildGraph({ ...report, assessment: null, pending: ["Planning classification: confirm."] });
    expect(nodes.find((n) => n.id === "conclusion")).toMatchObject({ text: "Pending confirmation", tone: "warning" });
    expect(nodes.some((n) => n.id.startsWith("ev:"))).toBe(false);
    expect(edges).toContainEqual({ from: "property", to: "pending" });
  });

  it("draws no authority when the report names none", () => {
    const none = { ...report, property: { ...report.property, authority: null } };
    const { nodes, edges } = buildGraph(none);
    expect(nodes.some((n) => n.id === "authority")).toBe(false);
    expect(edges.some((e) => e.from === "authority" || e.to === "authority")).toBe(false);
  });

  it("keeps evidence of an unknown status visible", () => {
    const evidence = [{ ...a.evidence[0], verification_status: "something_new" }];
    const line = node(withAssessment({ evidence }), "ev:other")!.lines[0];
    expect(line).toContain(a.evidence[0].title);
    expect(line).toContain("something_new");
  });

  it("translates its own words and leaves names and ids alone", () => {
    const pt = buildGraph(report, translator("pt"));
    expect(pt.nodes.find((n) => n.id === "property")!.title).toBe("Imóvel");
    expect(pt.nodes.find((n) => n.id === "conclusion")!.text).toBe("Verificado");
    expect(pt.nodes.find((n) => n.id === "property")!.text).toBe(report.property.address);
  });

  it("always says when the data is a demonstration or a translation", () => {
    expect(buildGraph(report).notices).toEqual([]);
    expect(buildGraph({ ...report, demo: true }).notices).toEqual(["Demonstration data"]);
    const translation = { available: true, kept_original: 0, note: "Tradução automática." };
    expect(buildGraph({ ...report, demo: true, translation }, translator("pt")).notices).toEqual([
      "Dados de demonstração",
      "Tradução automática.",
    ]);
  });

  it("reveals every word in reading order and always ends soon", () => {
    const delays = revealDelays(["one two three", "four five"]);
    expect(delays.map((l) => l.length)).toEqual([3, 2]);
    expect(delays.flat()).toEqual([...delays.flat()].sort((x, y) => x - y));
    const long = revealDelays(Array.from({ length: 30 }, () => "word ".repeat(40).trim()));
    expect(Math.max(...long.flat())).toBeLessThanOrEqual(2400);
    expect(revealDelays([])).toEqual([]);
  });

  it("gives every node a place and finds its neighbours", () => {
    const graph = buildGraph(report);
    const { positions, width, height } = layout(graph);
    expect(positions.size).toBe(graph.nodes.length);
    for (const { x, y } of positions.values()) expect(x < width && y < height).toBe(true);
  });

  describe("the flow of a block", () => {
    const ev = (id: string, source_type: string) => ({ ...a.evidence[0], evidence_id: id, source_type, verification_status: "system_record" });
    // One group holds E1 (from the authority) and E2 (from planning); the conclusion cites only E2.
    const shared = withAssessment({
      evidence: [ev("E1", "authority_record"), ev("E2", "planning_context")],
      conclusion_evidence_ids: ["E2"],
      statements: [],
      conditions: [],
    });

    it("reaches back to what leads to the block", () => {
      const graph = buildGraph(shared);
      const { nodes } = flowOf(graph, "conclusion");
      expect([...nodes]).toEqual(expect.arrayContaining(["conclusion", "ev:system", "planning", "property"]));
    });

    it("follows evidence through a group: sharing a group is not sharing a flow", () => {
      const graph = buildGraph(shared);
      expect(flowOf(graph, "conclusion").nodes.has("authority")).toBe(false);
      expect(flowOf(graph, "authority").nodes.has("conclusion")).toBe(false);
      expect(flowOf(graph, "planning").nodes.has("conclusion")).toBe(true);
    });

    it("shows the whole group's relations when the group itself is selected", () => {
      const { nodes } = flowOf(buildGraph(shared), "ev:system");
      expect(nodes.has("authority") && nodes.has("planning") && nodes.has("conclusion")).toBe(true);
    });

    it("runs forward from a block to what follows it", () => {
      const graph = buildGraph(report);
      const { nodes, edges } = flowOf(graph, "property");
      expect(nodes.has("jurisdiction") && nodes.has("planning")).toBe(true);
      expect(edges.has(edgeKey({ from: "property", to: "planning" }))).toBe(true);
    });

    it("leaves out a block with no stored relation to it", () => {
      const graph = buildGraph(withAssessment({ conditions: ["x"] }));
      expect(flowOf(graph, "conditions").nodes).toEqual(new Set(["conditions"]));
      expect(flowOf(graph, "conclusion").nodes.has("conditions")).toBe(false);
    });

    it("only ever contains existing blocks and stored edges", () => {
      const graph = buildGraph(report);
      const keys = new Set(graph.edges.map(edgeKey));
      const ids = new Set(graph.nodes.map((n) => n.id));
      for (const n of graph.nodes) {
        const flow = flowOf(graph, n.id);
        for (const e of flow.edges) expect(keys.has(e)).toBe(true);
        for (const id of flow.nodes) expect(ids.has(id)).toBe(true);
      }
    });
  });
});
