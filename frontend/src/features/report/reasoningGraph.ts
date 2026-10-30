import { ANSWER } from "@/features/permit/present";
import type { ConclusionAnswer } from "@/features/permit/types";
import { english, msg, type Translate } from "@/i18n/core";
import { STATUS_LABEL, type PostItTone } from "./postits";
import type { PermitReport, ReportEvidence, ReportStatement } from "./types";

// HR-005 reasoning graph: a presentation of the shared report model only, like the post-its. No model runs, and an edge
// exists only where the report stores that relation: nothing causal or authorising is drawn. Findings, risks and
// conditions are not linked to the conclusion because the report does not store that link. Evidence is drawn in groups
// to stay readable, so an edge carries the exact ids cited, and both ends list them: a group is never cited as a whole.

export const COLUMNS = [
  msg("Property"),
  msg("Jurisdiction and rules"),
  msg("Evidence and conditions"),
  msg("Conclusion"),
  msg("Documents"),
  msg("Next steps"),
] as const;

export interface GraphLink {
  label: string;
  url: string;
}

export interface GraphNode {
  id: string;
  column: number;
  title: string;
  text: string;
  tone: PostItTone;
  /** What the side panel shows: the node's own stored content, in order. */
  lines: string[];
  links: GraphLink[];
}

export interface GraphEdge {
  from: string;
  to: string;
  /** For an edge from an evidence group: the only evidence of that group the target cites. */
  evidenceIds?: string[];
}

export interface ReasoningGraphModel {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** What the graph must always say about itself: demonstration data, translation. */
  notices: string[];
}

const links = (items: { label: string; url: string | null }[]): GraphLink[] => [
  ...new Map(items.filter((i) => i.url).map((i) => [i.url, { label: i.label, url: i.url! }])).values(),
];

const GROUPS = [
  { id: "official", status: "official_text", title: msg("Official texts") },
  { id: "curated", status: "curated_reference", title: msg("Curated references") },
  { id: "system", status: "system_record", title: msg("HABITA records") },
  { id: "declared", status: "user_declared", title: msg("Your statements") },
] as const;

/** Evidence grouped by its stored verification status; an unknown status keeps its own group rather than being hidden. */
function evidenceGroups(evidence: ReportEvidence[]) {
  const known: readonly string[] = GROUPS.map((g) => g.status);
  const groups: { id: string; title: string; items: ReportEvidence[] }[] = GROUPS.map((g) => ({
    id: `ev:${g.id}`,
    title: g.title,
    items: evidence.filter((e) => e.verification_status === g.status),
  }));
  const other = evidence.filter((e) => !known.includes(e.verification_status));
  return [...groups, { id: "ev:other", title: msg("Other evidence"), items: other }].filter((g) => g.items.length);
}

const statementLine = (s: ReportStatement) =>
  `${s.step ? `${s.step}: ` : ""}${s.text}${s.evidence_ids.length ? ` [${s.evidence_ids.join(", ")}]` : ""}`;

export function buildGraph(report: PermitReport, t: Translate = english): ReasoningGraphModel {
  const { property, planning, assessment } = report;
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const count = (n: number) => t("{n} item(s)", { n });

  nodes.push({
    id: "property",
    column: 0,
    title: t("Property"),
    text: property.address,
    tone: "neutral",
    lines: [property.address, t("A geocoded point, not a parcel boundary.")],
    links: [],
  });

  const municipality = property.jurisdiction.find((j) => j.startsWith("Municipality:"))?.split(": ")[1];
  nodes.push({
    id: "jurisdiction",
    column: 1,
    title: t("Jurisdiction"),
    text: municipality ?? t("Not modelled for this jurisdiction"),
    tone: "neutral",
    lines: property.jurisdiction.map((j) => {
      const [label, ...name] = j.split(": ");
      return `${t(label)}: ${name.join(": ")}`;
    }),
    links: [],
  });
  edges.push({ from: "property", to: "jurisdiction" });

  if (property.authority) {
    nodes.push({
      id: "authority",
      column: 1,
      title: t("Competent authority"),
      text: property.authority,
      tone: "neutral",
      lines: [property.authority],
      links: [],
    });
    edges.push({ from: "jurisdiction", to: "authority" });
  }

  const zoned = planning.verified_zoning && planning.classification;
  nodes.push({
    id: "planning",
    column: 1,
    title: t("Zoning"),
    text: zoned ? planning.classification! : t("Zoning not verified"),
    tone: zoned ? "positive" : "warning",
    lines: [...(planning.instrument ? [planning.instrument] : []), planning.guidance, ...planning.reasons],
    links: [],
  });
  edges.push({ from: "property", to: "planning" });

  if (assessment) {
    const groups = evidenceGroups(assessment.evidence);
    const groupOf = (id: string) => groups.find((g) => g.items.some((e) => e.evidence_id === id))?.id;
    /** One edge per cited group, carrying exactly the ids cited; the group's panel says who cites what. */
    const citeBy = (to: string, title: string, ids: string[]) => {
      for (const group of groups) {
        const inGroup = [...new Set(ids)].filter((id) => groupOf(id) === group.id);
        if (!inGroup.length) continue;
        edges.push({ from: group.id, to, evidenceIds: inGroup });
        nodes
          .find((n) => n.id === group.id)!
          .lines.push(t("Cited by {name}: {ids}", { name: title, ids: inGroup.join(", ") }));
      }
    };

    for (const group of groups) {
      nodes.push({
        id: group.id,
        column: 2,
        title: t(group.title),
        text: count(group.items.length),
        tone: "neutral",
        lines: group.items.map((e) => {
          const line = `${e.evidence_id} · ${e.title} — ${e.reference}`;
          return group.id === "ev:other" ? `${line} (${e.verification_status})` : line;
        }),
        links: links(group.items.map((e) => ({ label: e.title, url: e.url }))),
      });
      const lines = nodes[nodes.length - 1].lines;
      const origin = (from: string, title: string, type: string) => {
        const ids = group.items.filter((e) => e.source_type === type).map((e) => e.evidence_id);
        if (!ids.length) return;
        edges.push({ from, to: group.id, evidenceIds: ids });
        lines.push(t("From {name}: {ids}", { name: title, ids: ids.join(", ") }));
      };
      origin("planning", t("Zoning"), "planning_context");
      if (property.authority) origin("authority", t("Competent authority"), "authority_record");
      origin("jurisdiction", t("Jurisdiction"), "jurisdiction_record");
    }

    if (assessment.conditions.length) {
      nodes.push({
        id: "conditions",
        column: 2,
        title: t("Conditions"),
        text: count(assessment.conditions.length),
        tone: "warning",
        lines: assessment.conditions,
        links: [],
      });
    }

    // The PDF's rule: verified only when the status, the content and a current VERIFIED record all agree.
    const record = assessment.verification;
    const verified =
      assessment.status === "VERIFIED" && assessment.content_verified && record?.current === true && record.outcome === "VERIFIED";
    const status = STATUS_LABEL[verified || assessment.status !== "VERIFIED" ? assessment.status : "PENDING_CONFIRMATION"];
    const answer = assessment.conclusion_answer as ConclusionAnswer | null;
    nodes.push({
      id: "conclusion",
      column: 3,
      title: t("Conclusion"),
      text: t(status.label),
      tone: status.tone,
      lines: [
        ...(answer && ANSWER[answer] ? [t(ANSWER[answer])] : []),
        ...(assessment.conclusion_summary
          ? [verified ? assessment.conclusion_summary : t("Not verified: {text}", { text: assessment.conclusion_summary })]
          : []),
        assessment.status_reason,
        ...assessment.issues,
        ...(assessment.conclusion_evidence_ids.length
          ? [t("Evidence cited: {ids}", { ids: assessment.conclusion_evidence_ids.join(", ") })]
          : []),
      ],
      links: [],
    });
    citeBy("conclusion", t("Conclusion"), assessment.conclusion_evidence_ids);

    const section = (id: string, column: number, title: string, kind: ReportStatement["section"], tone: PostItTone = "neutral") => {
      const items = assessment.statements.filter((s) => s.section === kind);
      if (!items.length) return;
      nodes.push({
        id,
        column,
        title: t(title),
        text: count(items.length),
        tone: verified ? tone : "warning",
        lines: [...(verified ? [] : [t("Not verified")]), ...items.map(statementLine)],
        links: [],
      });
      citeBy(id, t(title), items.flatMap((s) => s.evidence_ids));
    };
    section("findings", 3, msg("Findings"), "finding");
    section("risks", 3, msg("Risks and uncertainties"), "risk", "warning");
    section("procedure", 5, msg("Likely procedure"), "procedure");
    section("actions", 5, msg("Next actions"), "next_action");
  } else {
    nodes.push({
      id: "conclusion",
      column: 3,
      title: t("Conclusion"),
      text: t(STATUS_LABEL.PENDING_CONFIRMATION.label),
      tone: "warning",
      lines: [t("No permit assessment yet: no permit question has been verified for this property.")],
      links: [],
    });
  }

  if (planning.documents_to_consult.length) {
    nodes.push({
      id: "documents",
      column: 4,
      title: t("Official maps to consult"),
      text: count(planning.documents_to_consult.length),
      tone: "neutral",
      lines: planning.documents_to_consult.map((d) => `${d.designation ?? d.title}: ${d.reason}`),
      links: links(planning.documents_to_consult.map((d) => ({ label: d.designation ?? d.title, url: d.url }))),
    });
    edges.push({ from: "planning", to: "documents" });
  }
  if (report.sources.length) {
    nodes.push({
      id: "sources",
      column: 4,
      title: t("Official sources"),
      text: count(report.sources.length),
      tone: "neutral",
      lines: report.sources.map((s) => `${s.title} — ${t(s.status)}`), // a candidate source reads as one
      links: links(report.sources.map((s) => ({ label: s.title, url: s.url }))),
    });
    edges.push({ from: "jurisdiction", to: "sources" });
  }
  if (report.pending.length) {
    nodes.push({
      id: "pending",
      column: 5,
      title: t("Pending confirmation"),
      text: count(report.pending.length),
      tone: "warning",
      lines: report.pending,
      links: [],
    });
    edges.push({ from: "property", to: "pending" }); // the items belong to the report as a whole, not to one node
  }
  const notices = [...(report.demo ? [t("Demonstration data")] : []), ...(report.translation?.note ? [report.translation.note] : [])];
  return { nodes, edges, notices };
}

export const NODE_WIDTH = 168;
export const NODE_HEIGHT = 76;
const COLUMN_GAP = 56;
const ROW_GAP = 16;
const HEADER = 32;

/** Fixed positions, so the graph is the same on every screen; a narrow screen scrolls it. */
export function layout(graph: ReasoningGraphModel) {
  const rows = COLUMNS.map((_, column) => graph.nodes.filter((n) => n.column === column).length);
  const tallest = Math.max(...rows, 1);
  const height = HEADER + tallest * (NODE_HEIGHT + ROW_GAP);
  const positions = new Map<string, { x: number; y: number }>();
  COLUMNS.forEach((_, column) => {
    const inColumn = graph.nodes.filter((n) => n.column === column);
    const top = HEADER + ((tallest - inColumn.length) * (NODE_HEIGHT + ROW_GAP)) / 2;
    inColumn.forEach((n, row) =>
      positions.set(n.id, { x: column * (NODE_WIDTH + COLUMN_GAP), y: top + row * (NODE_HEIGHT + ROW_GAP) }),
    );
  });
  return { positions, height, width: COLUMNS.length * (NODE_WIDTH + COLUMN_GAP) - COLUMN_GAP, columnX: (c: number) => c * (NODE_WIDTH + COLUMN_GAP) };
}

/** The nodes one step from a node, for highlighting. */
export function neighbours(graph: ReasoningGraphModel, id: string): Set<string> {
  return new Set(graph.edges.flatMap((e) => (e.from === id ? [e.to] : e.to === id ? [e.from] : [])));
}
