import { english, msg, type Translate } from "@/i18n/core";
import type { PermitReport, ReportStatus } from "./types";

// HR-004 post-its: a presentation of the shared report model only. No status, zoning or source is decided here.

export type PostItTone = "positive" | "danger" | "warning" | "neutral";

export interface PostItLink {
  label: string;
  url: string;
}

export interface PostIt {
  id: "property" | "planning" | "assessment" | "risks" | "evidence" | "sources";
  title: string;
  tone: PostItTone;
  badge?: string;
  lines: string[];
  links: PostItLink[];
}

export const STATUS_LABEL: Record<ReportStatus, { label: string; tone: PostItTone }> = {
  VERIFIED: { label: msg("Verified"), tone: "positive" },
  REJECTED: { label: msg("Rejected"), tone: "danger" },
  PENDING_CONFIRMATION: { label: msg("Pending confirmation"), tone: "warning" },
};

const link = (label: string, url: string | null): PostItLink[] => (url ? [{ label, url }] : []);

// A geocoded point is never a parcel: anything but rooftop precision is an area, and even rooftop is not a boundary.
const location = (lat: number, lng: number, precision: string, t: Translate) => {
  const coordinates = `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
  return precision === "rooftop"
    ? t("Location: {coordinates} (rooftop point; not a parcel boundary)", { coordinates })
    : t("Location: {coordinates} (approximate, {precision}; not a parcel boundary)", { coordinates, precision: t(precision).replace("_", " ") });
};

/** "Municipality: Cascais" with its label in the language shown; names stay official. */
const level = (line: string, t: Translate) => {
  const [label, ...name] = line.split(": ");
  return `${t(label)}: ${name.join(": ")}`;
};

export function buildPostIts(report: PermitReport, t: Translate = english): PostIt[] {
  const { property, planning, assessment } = report;
  const notes: PostIt[] = [
    {
      id: "property",
      title: t("Property"),
      tone: "neutral",
      lines: [
        property.address,
        location(property.lat, property.lng, property.precision, t),
        ...(property.jurisdiction.some((j) => j.startsWith("Municipality:"))
          ? property.jurisdiction.filter((j) => j.startsWith("Municipality:")).map((j) => level(j, t))
          : [t("Municipality: not modelled for this jurisdiction")]),
        property.authority ? t("Competent authority: {authority}", { authority: property.authority }) : t("Competent authority not modelled"),
      ],
      links: [],
    },
    planning.verified_zoning && planning.classification
      ? {
          id: "planning",
          title: t("Zoning"),
          tone: "positive",
          badge: t("Verified layer"),
          lines: [planning.classification, ...(planning.instrument ? [planning.instrument] : [])],
          links: [],
        }
      : {
          id: "planning",
          title: t("Zoning"),
          tone: "warning",
          badge: t("Zoning not verified"),
          // The absence is stated; nothing is drawn or classified without a validated connector.
          lines: [
            t("Zoning not verified: no classification or boundary is shown. Confirm on the official maps or with the competent authority."),
            ...planning.reasons,
          ],
          links: planning.documents_to_consult.flatMap((d) => link(d.designation ?? d.title, d.url)),
        },
  ];
  if (!assessment) {
    notes.push({
      id: "assessment",
      title: t("Analysis status"),
      tone: "warning",
      badge: t(STATUS_LABEL.PENDING_CONFIRMATION.label),
      lines: [t("No permit assessment yet: no permit question has been verified for this property."), ...report.pending],
      links: [],
    });
  }
  if (assessment) {
    const status = STATUS_LABEL[assessment.status];
    notes.push({
      id: "assessment",
      title: t("Permit assessment"),
      tone: status.tone,
      badge: t(status.label),
      lines: [
        assessment.question,
        ...(assessment.conclusion_summary
          ? [assessment.content_verified ? assessment.conclusion_summary : t("Not verified: {text}", { text: assessment.conclusion_summary })]
          : []),
        assessment.status_reason,
        ...assessment.conditions.map((c) => t("Condition: {text}", { text: c })),
        ...assessment.issues,
      ],
      links: [],
    });
    const risks = assessment.statements.filter((s) => s.section === "risk");
    if (risks.length) {
      notes.push({
        id: "risks",
        title: t("Risks"),
        tone: assessment.content_verified ? "neutral" : "warning",
        badge: assessment.content_verified ? undefined : t("Not verified"),
        lines: risks.map((r) => (r.evidence_ids.length ? `${r.text} [${r.evidence_ids.join(", ")}]` : r.text)),
        links: [],
      });
    }
    if (assessment.evidence.length) {
      notes.push({
        id: "evidence",
        title: t("Evidence cited"),
        tone: "neutral",
        lines: assessment.evidence.map((e) => `${e.evidence_id} · ${e.title} — ${e.reference}`),
        // One link per cited document, however many of its passages are cited.
        links: [...new Map(assessment.evidence.filter((e) => e.url).map((e) => [e.url, { label: e.title, url: e.url! }])).values()],
      });
    }
  }
  notes.push({
    id: "sources",
    title: t("Official sources"),
    tone: "neutral",
    lines: report.sources.map((s) => s.title),
    links: report.sources.flatMap((s) => link(s.title, s.url)),
  });
  return notes;
}
