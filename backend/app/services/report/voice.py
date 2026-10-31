"""HR-007 voice explanation: what is said comes only from the shared report model, with no model call, and says no more
than the report does. Audio is an explanation, never proof: the script opens and closes by saying so, and carries the
same status, the "not verified" warning and the translation label as the written report.

The script lives here so the audio endpoint speaks only these sentences, chosen by position: it never takes text from
the caller."""

import hashlib
import re

from app.schemas.report import PermitReport, ReportAssessment, ReportStatus
from app.services.i18n.translator import msg, translator_for

MAX_CHARS = 180  # sentences are spoken and paid for one at a time

STATUS_LABEL: dict[ReportStatus, str] = {
    "VERIFIED": msg("Verified"), "REJECTED": msg("Rejected"), "PENDING_CONFIRMATION": msg("Pending confirmation"),
}
ANSWER = {
    "likely_possible": msg("Likely possible"), "conditional": msg("Possible, subject to conditions"),
    "likely_not_possible": msg("Likely not possible"), "undetermined": msg("Not yet determined"),
}


def speakable(text: str) -> list[str]:
    """Spoken text: no evidence references, and one sentence at a time."""
    clean = re.sub(r"\s+", " ", re.sub(r"\s*\[[EK]\d+(?:,\s*[EK]\d+)*\]", "", text)).strip()
    if not clean:
        return []
    out: list[str] = []
    for sentence in re.findall(r"[^.!?;]+[.!?;]*\s*", clean) or [clean]:
        rest = sentence.strip()
        while len(rest) > MAX_CHARS:
            cut = rest.rfind(" ", 0, MAX_CHARS + 1)
            out.append(rest[:cut] if cut > 0 else rest[:MAX_CHARS])
            rest = rest[cut + 1:] if cut > 0 else rest[MAX_CHARS:]
        if rest:
            out.append(rest)
    return out


def is_verified(assessment: ReportAssessment) -> bool:
    record = assessment.verification
    return (assessment.status == "VERIFIED" and assessment.content_verified and record is not None
            and record.current and record.outcome == "VERIFIED")


def _profile_lines(report: PermitReport, t) -> list[str]:
    say: list[str] = []
    for title, items in (
        (t("Official facts"), [i for i in report.profile if i.kind == "official" and i.value]),
        (t("Observations"), [i for i in report.profile if i.kind == "observation" and i.value]),
        (t("Your declarations, not verified"), [i for i in report.profile if i.kind == "declaration" and i.value]),
    ):
        if items:
            say += [title, *[t("{label}: {value}. Source: {origin}.", label=i.label, value=i.value, origin=i.origin)
                             for i in items]]
    unknown = [i for i in report.profile if not i.value]
    if unknown:
        say += [t("Not confirmed"), *[
            t("{label}: you declared that you do not know. Confirm with {origin}.", label=i.label, origin=i.origin)
            if i.kind == "declaration" else t("{label}: confirm with {origin}.", label=i.label, origin=i.origin)
            for i in unknown]]
    say += [t("{label}: the sources disagree. Check each one.", label=label)
            for label in dict.fromkeys(i.label for i in report.profile if i.conflict)]
    return say


def build_voice_script(report: PermitReport) -> list[str]:
    t = translator_for(report.language)
    prop, planning, assessment = report.property, report.planning, report.assessment
    say = [t("This is a spoken explanation of the report. It is not legal proof, a permit or an authorisation.")]
    if report.demo:
        say.append(t("Demonstration data"))
    if report.translation and report.translation.note:
        say.append(report.translation.note)
    say.append(t("This report is about {address}.", address=prop.address))
    if prop.authority:
        say.append(t("The competent authority is {authority}.", authority=prop.authority))
    say.append(
        t("Zoning from the official layer: {classification}.", classification=planning.classification)
        if planning.verified_zoning and planning.classification else
        t("Zoning not verified: no classification or boundary is shown. Confirm on the official maps or with the "
          "competent authority."))
    say += planning.reasons
    # What each map covers is a possible restriction, so it is said, not just counted.
    if planning.documents_to_consult:
        say += [t("Official maps to consult"), *[d.reason for d in planning.documents_to_consult]]

    say += _profile_lines(report, t)

    if assessment is None:
        say.append(t("No permit assessment yet: no permit question has been verified for this property."))
    else:
        verified = is_verified(assessment)
        corrected = assessment.status == "VERIFIED" and not verified  # never keeps the reason of the status it replaced
        status = "PENDING_CONFIRMATION" if corrected else assessment.status
        say += [t("The question was: {question}", question=assessment.question),
                t("Status: {status}.", status=t(STATUS_LABEL[status])),
                t("The verification record does not support a verified result.") if corrected
                else assessment.status_reason]
        if verified:
            say.append(t("This is HABITA's own check, not a municipal approval."))
        elif assessment.conclusion_summary or assessment.statements:
            say.append(t("Not verified. The statements below have not passed HABITA's verification and must not be "
                         "relied on."))
        if assessment.conclusion_answer in ANSWER:
            say.append(t(ANSWER[assessment.conclusion_answer]))
        if assessment.conclusion_summary:
            say.append(assessment.conclusion_summary)
        if assessment.conditions:
            say += [t("Conditions"), *assessment.conditions]
        say += assessment.issues
        for title, kind in ((t("Findings"), "finding"), (t("Likely procedure"), "procedure"),
                            (t("Risks and uncertainties"), "risk"), (t("Next actions"), "next_action")):
            items = [s.text for s in assessment.statements if s.section == kind]
            if items:
                say += [title, *items]
    # Said in full: what is still open is what a summary must not make sound settled. Conditions were said above.
    said = {t("Condition: ") + c for c in (assessment.conditions if assessment else [])}
    pending = [item for item in report.pending if item not in said]
    if pending:
        say += [t("Pending confirmation"), *pending]
    say.append(report.disclaimer)
    return [line for text in say for line in speakable(text)]


def script_version(lines: list[str]) -> str:
    """Audio is asked for by position, so a report that changed must not answer with another sentence."""
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]
