import { ANSWER } from "@/features/permit/present";
import type { ConclusionAnswer } from "@/features/permit/types";
import { english, type Translate } from "@/i18n/core";
import { STATUS_LABEL } from "./postits";
import { isVerified, presentedStatus, statusReason } from "./reasoningGraph";
import type { PermitReport, ReportStatement } from "./types";

// HR-007 voice explanation: what is said comes only from the shared report model, with no model call, and says no more
// than the report does. Audio is an explanation, never proof: the script opens and closes by saying so, and carries the
// same status, the "not verified" warning and the translation label as the written report.

const MAX_CHARS = 180; // long utterances are cut short by some browsers

/** Spoken text: no evidence references, and one sentence at a time. */
export function speakable(text: string): string[] {
  const clean = text.replace(/\s*\[[EK]\d+(?:,\s*[EK]\d+)*\]/g, "").replace(/\s+/g, " ").trim();
  if (!clean) return [];
  const out: string[] = [];
  for (const sentence of clean.match(/[^.!?;]+[.!?;]*\s*/g) ?? [clean]) {
    let rest = sentence.trim();
    while (rest.length > MAX_CHARS) {
      const cut = rest.lastIndexOf(" ", MAX_CHARS);
      out.push(rest.slice(0, cut > 0 ? cut : MAX_CHARS));
      rest = rest.slice(cut > 0 ? cut + 1 : MAX_CHARS);
    }
    if (rest) out.push(rest);
  }
  return out;
}

export function buildVoiceScript(report: PermitReport, t: Translate = english): string[] {
  const { property, planning, assessment } = report;
  const say: string[] = [
    t("This is a spoken explanation of the report. It is not legal proof, a permit or an authorisation."),
    ...(report.demo ? [t("Demonstration data")] : []),
    ...(report.translation?.note ? [report.translation.note] : []),
    t("This report is about {address}.", { address: property.address }),
  ];
  if (property.authority) say.push(t("The competent authority is {authority}.", { authority: property.authority }));
  say.push(
    planning.verified_zoning && planning.classification
      ? t("Zoning from the official layer: {classification}.", { classification: planning.classification })
      : t("Zoning not verified: no classification or boundary is shown. Confirm on the official maps or with the competent authority."),
    ...planning.reasons,
  );
  // What each map covers is a possible restriction, so it is said, not just counted.
  if (planning.documents_to_consult.length) {
    say.push(t("Official maps to consult"), ...planning.documents_to_consult.map((d) => d.reason));
  }

  if (!assessment) {
    say.push(t("No permit assessment yet: no permit question has been verified for this property."));
  } else {
    const verified = isVerified(assessment);
    const answer = assessment.conclusion_answer as ConclusionAnswer | null;
    say.push(t("The question was: {question}", { question: assessment.question }));
    say.push(t("Status: {status}.", { status: t(STATUS_LABEL[presentedStatus(assessment)].label) }), statusReason(assessment, t));
    if (verified) say.push(t("This is HABITA's own check, not a municipal approval."));
    if (!verified && (assessment.conclusion_summary || assessment.statements.length)) {
      say.push(t("Not verified. The statements below have not passed HABITA's verification and must not be relied on."));
    }
    if (answer && ANSWER[answer]) say.push(t(ANSWER[answer]));
    if (assessment.conclusion_summary) say.push(assessment.conclusion_summary);
    if (assessment.conditions.length) say.push(t("Conditions"), ...assessment.conditions);
    if (assessment.issues.length) say.push(...assessment.issues);
    const section = (title: string, kind: ReportStatement["section"]) => {
      const items = assessment.statements.filter((s) => s.section === kind);
      if (items.length) say.push(title, ...items.map((s) => s.text));
    };
    section(t("Findings"), "finding");
    section(t("Likely procedure"), "procedure");
    section(t("Risks and uncertainties"), "risk");
    section(t("Next actions"), "next_action");
  }
  // Said in full: what is still open is what a summary must not make sound settled. Conditions were said above.
  const said = new Set((assessment?.conditions ?? []).map((c) => t("Condition: ") + c));
  const pending = report.pending.filter((item) => !said.has(item));
  if (pending.length) say.push(t("Pending confirmation"), ...pending);
  say.push(report.disclaimer);
  return say.flatMap(speakable);
}
