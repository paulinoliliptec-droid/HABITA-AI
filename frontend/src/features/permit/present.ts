import type { BadgeTone } from "@/components/ui/Badge";
import type { ConclusionAnswer, Evidence, MatterState } from "./types";

export const PHASES = ["Goal", "Investigation", "Evidence", "Result"] as const;
export type Phase = (typeof PHASES)[number];

/**
 * Where a state sits in Goal → Investigation → Evidence → Result, and whether that phase is finished.
 * Waiting for the user's facts is part of the investigation, not a finished evidence stage.
 */
export function phaseOf(state: MatterState, failedState?: MatterState): { phase: Phase; done: boolean; waiting?: boolean } {
  switch (state) {
    case "PLANNING":
      return { phase: "Goal", done: false };
    case "INVESTIGATING":
      return { phase: "Investigation", done: false };
    case "NEEDS_INPUT":
      return { phase: "Investigation", done: false, waiting: true };
    case "DRAFT_READY":
    case "VERIFYING":
      return { phase: "Result", done: false };
    case "VERIFIED":
    case "ESCALATE":
    case "REJECTED":
      return { phase: "Result", done: true };
    case "FAILED":
      return { ...phaseOf(failedState ?? "PLANNING"), done: false };
  }
}

export const OUTCOME: Record<"VERIFIED" | "ESCALATE" | "REJECTED" | "FAILED" | "NEEDS_INPUT", { label: string; tone: BadgeTone }> = {
  VERIFIED: { label: "Verified assessment", tone: "positive" },
  NEEDS_INPUT: { label: "Waiting for your information", tone: "warning" },
  ESCALATE: { label: "Needs professional review", tone: "warning" },
  REJECTED: { label: "Not verified: unsupported by its evidence", tone: "warning" },
  FAILED: { label: "Interrupted", tone: "warning" },
};

// MU-9: a VERIFIED state verified under a protocol HABITA no longer accepts is presented as superseded — legacy, not
// revalidated — never as a current verified assessment. The API's assessment_status decides, not the raw state.
export const SUPERSEDED = { label: "Superseded: verified under an earlier protocol", tone: "warning" as BadgeTone };

export function outcomeOf(matter: { state: string; assessment_status: string }) {
  if (matter.assessment_status === "superseded_assessment") return SUPERSEDED;
  return OUTCOME[matter.state as keyof typeof OUTCOME];
}

export const ANSWER: Record<ConclusionAnswer, string> = {
  likely_possible: "Likely possible",
  conditional: "Possible, subject to conditions",
  likely_not_possible: "Likely not possible",
  undetermined: "Not yet determined",
};

export const EVIDENCE_STATUS: Record<Evidence["verification_status"], string> = {
  system_record: "HABITA record",
  curated_reference: "Curated reference — check the official text",
  official_text: "Official text",
  user_declared: "Stated by you",
};

/** How an evidence record is grounded, e.g. "Official text · retrieved 28 Oct 2026". */
export function evidenceBasis(e: Evidence): string {
  const label = e.source_type === "planning_context" ? "Official planning sources" : EVIDENCE_STATUS[e.verification_status];
  const at = e.verification_status === "official_text" ? e.provenance?.retrieved_at : null;
  if (!at) return label;
  const date = new Date(at);
  if (Number.isNaN(date.getTime())) return label;
  return `${label} · retrieved ${date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })}`;
}

/**
 * Structured answers for checklist items with a small, known answer space (canonical keys from the backend's
 * requirement catalog). The chosen label is sent as the answer. Descriptive items stay free text.
 */
export const INPUT_CHOICES: Record<string, { options: readonly string[]; other?: string }> = {
  ownership_status: {
    options: ["Single ownership", "Horizontal property / multiple fractions", "I don't know"],
  },
  current_licensed_use: {
    options: ["Housing: one dwelling", "Housing: more than one dwelling", "I don't know"],
    other: "Other use",
  },
};

export function sourcesLine(checked: number, needed: number): string {
  const sources = `${checked} ${checked === 1 ? "source" : "sources"} checked`;
  return needed ? `${sources} · ${needed} ${needed === 1 ? "fact" : "facts"} still needed from you` : sources;
}

export const SUGGESTED_QUESTIONS = [
  "Can I convert this property into two residential units?",
  "What can I do with this property?",
] as const;
