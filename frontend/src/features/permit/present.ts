import type { BadgeTone } from "@/components/ui/Badge";
import { english, msg, type Translate } from "@/i18n/core";
import type { ConclusionAnswer, Evidence, MatterState, PermitIntent } from "./types";

export const PHASES = [msg("Goal"), msg("Investigation"), msg("Evidence"), msg("Result")] as const;
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
  VERIFIED: { label: msg("Verified assessment"), tone: "positive" },
  NEEDS_INPUT: { label: msg("Waiting for your information"), tone: "warning" },
  ESCALATE: { label: msg("Needs professional review"), tone: "warning" },
  REJECTED: { label: msg("Not verified: unsupported by its evidence"), tone: "warning" },
  FAILED: { label: msg("Interrupted"), tone: "warning" },
};

// MU-9: a VERIFIED state verified under a protocol HABITA no longer accepts is presented as superseded — legacy, not
// revalidated — never as a current verified assessment. The API's assessment_status decides, not the raw state.
export const SUPERSEDED = { label: msg("Superseded: verified under an earlier protocol"), tone: "warning" as BadgeTone };

export function outcomeOf(matter: { state: string; assessment_status: string }) {
  if (matter.assessment_status === "superseded_assessment") return SUPERSEDED;
  return OUTCOME[matter.state as keyof typeof OUTCOME];
}

export const ANSWER: Record<ConclusionAnswer, string> = {
  likely_possible: msg("Likely possible"),
  conditional: msg("Possible, subject to conditions"),
  likely_not_possible: msg("Likely not possible"),
  undetermined: msg("Not yet determined"),
};

export const EVIDENCE_STATUS: Record<Evidence["verification_status"], string> = {
  system_record: msg("HABITA record"),
  curated_reference: msg("Curated reference — check the official text"),
  official_text: msg("Official text"),
  user_declared: msg("Stated by you"),
};

/** How an evidence record is grounded, e.g. "Official text · retrieved 28 Oct 2026". */
export function evidenceBasis(e: Evidence, t: Translate = english, locale = "en-GB"): string {
  const label = t(e.source_type === "planning_context" ? msg("Official planning sources") : EVIDENCE_STATUS[e.verification_status]);
  const at = e.verification_status === "official_text" ? e.provenance?.retrieved_at : null;
  if (!at) return label;
  const date = new Date(at);
  if (Number.isNaN(date.getTime())) return label;
  return `${label} · ${t("retrieved")} ${date.toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })}`;
}

/**
 * Structured answers for checklist items with a small, known answer space (canonical keys from the backend's
 * requirement catalog). The chosen English label is sent as the answer, whatever the language shown: it is what the
 * verifier reads. Descriptive items stay free text.
 */
export const INPUT_CHOICES: Record<string, { options: readonly string[]; other?: string }> = {
  ownership_status: {
    options: [msg("Single ownership"), msg("Horizontal property / multiple fractions"), msg("I don't know")],
  },
  current_licensed_use: {
    options: [msg("Housing: one dwelling"), msg("Housing: more than one dwelling"), msg("I don't know")],
    other: msg("Other use"),
  },
};

export function sourcesLine(checked: number, needed: number, t: Translate = english): string {
  const sources = checked === 1 ? t("{n} source checked", { n: checked }) : t("{n} sources checked", { n: checked });
  if (!needed) return sources;
  const facts = needed === 1 ? t("{n} fact still needed from you", { n: needed }) : t("{n} facts still needed from you", { n: needed });
  return `${sources} · ${facts}`;
}

export const SUGGESTED_QUESTIONS = [
  msg("Can I convert this property into two residential units?"),
  msg("Can I change this property's use?"),
  msg("Can I do interior works in this property?"),
  msg("What can I do with this property?"),
] as const;

/** The closed catalog of request types (HR-009), in the order they are offered. */
export const INTENT_LABEL: Record<PermitIntent, string> = {
  unit_conversion: msg("Dividing into units"),
  change_of_use: msg("Change of use"),
  interior_works: msg("Interior works"),
  general_overview: msg("General orientation"),
};
