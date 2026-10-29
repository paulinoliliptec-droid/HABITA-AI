import type { PermitReport, ReportStatus } from "./types";

// HR-004 post-its: a presentation of the shared report model only. No status, zoning or source is decided here.

export type PostItTone = "positive" | "danger" | "warning" | "neutral";

export interface PostItLink {
  label: string;
  url: string;
}

export interface PostIt {
  id: "property" | "planning" | "assessment" | "risks" | "sources";
  title: string;
  tone: PostItTone;
  badge?: string;
  lines: string[];
  links: PostItLink[];
}

export const STATUS_LABEL: Record<ReportStatus, { label: string; tone: PostItTone }> = {
  VERIFIED: { label: "Verified", tone: "positive" },
  REJECTED: { label: "Rejected", tone: "danger" },
  PENDING_CONFIRMATION: { label: "Pending confirmation", tone: "warning" },
};

const link = (label: string, url: string | null): PostItLink[] => (url ? [{ label, url }] : []);

export function buildPostIts(report: PermitReport): PostIt[] {
  const { property, planning, assessment } = report;
  const notes: PostIt[] = [
    {
      id: "property",
      title: "Property",
      tone: "neutral",
      lines: [property.address, property.authority ? `Competent authority: ${property.authority}` : "Competent authority not modelled"],
      links: [],
    },
    planning.verified_zoning && planning.classification
      ? {
          id: "planning",
          title: "Zoning",
          tone: "positive",
          badge: "Verified layer",
          lines: [planning.classification, ...(planning.instrument ? [planning.instrument] : [])],
          links: [],
        }
      : {
          id: "planning",
          title: "Zoning",
          tone: "warning",
          badge: "No verified layer",
          // The absence is stated; nothing is drawn or classified without a validated connector.
          lines: ["No verified zoning layer for this location. Confirm on the official maps.", ...planning.reasons],
          links: planning.documents_to_consult.flatMap((d) => link(d.designation ?? d.title, d.url)),
        },
  ];
  if (assessment) {
    const status = STATUS_LABEL[assessment.status];
    notes.push({
      id: "assessment",
      title: "Permit assessment",
      tone: status.tone,
      badge: status.label,
      lines: [
        assessment.question,
        ...(assessment.conclusion_summary
          ? [assessment.content_verified ? assessment.conclusion_summary : `Not verified: ${assessment.conclusion_summary}`]
          : []),
        assessment.status_reason,
        ...assessment.conditions.map((c) => `Condition: ${c}`),
        ...assessment.issues,
      ],
      links: [],
    });
    const risks = assessment.statements.filter((s) => s.section === "risk");
    if (risks.length) {
      notes.push({
        id: "risks",
        title: "Risks",
        tone: assessment.content_verified ? "neutral" : "warning",
        badge: assessment.content_verified ? undefined : "Not verified",
        lines: risks.map((r) => (r.evidence_ids.length ? `${r.text} [${r.evidence_ids.join(", ")}]` : r.text)),
        links: [],
      });
    }
    notes.push({
      id: "sources",
      title: "Legal sources",
      tone: "neutral",
      lines: assessment.evidence.map((e) => `${e.evidence_id} · ${e.title} — ${e.reference}`),
      // One link per official document, however many passages of it are cited.
      links: [...new Map(assessment.evidence.filter((e) => e.url).map((e) => [e.url, { label: e.title, url: e.url! }])).values()],
    });
  } else {
    notes.push({
      id: "sources",
      title: "Official sources",
      tone: "neutral",
      lines: report.sources.map((s) => s.title),
      links: report.sources.flatMap((s) => link(s.title, s.url)),
    });
  }
  return notes;
}
