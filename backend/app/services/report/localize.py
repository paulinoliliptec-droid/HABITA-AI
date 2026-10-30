"""The report in the reader's language: a copy with its texts replaced, after it was built from stored results.

Only words change. Statuses, ids, evidence, sources and official titles are copied as they are, so nothing here can
alter what the report says was verified. Evidence stays in its original wording: it is what was checked."""

from app.schemas.permit import PermitMatter
from app.schemas.report import PermitReport, ReportTranslation
from app.services.i18n.translator import Translator, msg, translation_note, translator_for

#: Fixed lead-ins of the builder's pending items; what follows each one is translated on its own.
PENDING_LEADS = (msg("Condition: "), msg("Assessment: "), msg("Your answer is needed: "))


def matter_texts(matter: PermitMatter) -> list[str]:
    """Every text of a matter that the workspace shows."""
    texts = [m for i in matter.missing_inputs for m in (i.question, i.reason)]
    texts += [t for t in (matter.escalation_reason, matter.outcome_note) if t]
    if matter.error is not None:
        texts.append(matter.error.message)
    d = matter.draft
    if d is not None:
        texts.append(d.conclusion.summary)
        texts += [c.text for c in d.conditions] + [c.text for c in d.claims]
        texts += [t for p in d.procedure for t in (p.step, p.description)]
        texts += [r.text for r in d.risks] + [a.text for a in d.next_actions]
    return texts


def _split_pending(item: str) -> tuple[str, str]:
    lead = next((p for p in PENDING_LEADS if item.startswith(p)), "")
    return lead, item[len(lead):]


async def localize_report(report: PermitReport, lang: str, translator: Translator) -> PermitReport:
    if lang == "en":
        return report
    t = translator_for(lang)
    a, pl = report.assessment, report.planning
    texts = [report.disclaimer, pl.guidance, *pl.reasons, *(d.reason for d in pl.documents_to_consult),
             *(_split_pending(p)[1] for p in report.pending)]
    if a is not None:
        texts += [a.status_reason, a.conclusion_summary or "", *a.conditions, *a.issues]
        texts += [x for s in a.statements for x in (s.text, s.step or "")]
    x = await translator.translate(texts, lang)
    planning = pl.model_copy(update={
        "guidance": x(pl.guidance), "reasons": [x(r) for r in pl.reasons],
        "documents_to_consult": [d.model_copy(update={"reason": x(d.reason)}) for d in pl.documents_to_consult],
    })
    assessment = a.model_copy(update={
        "status_reason": x(a.status_reason), "conclusion_summary": x(a.conclusion_summary),
        "conditions": [x(c) for c in a.conditions], "issues": [x(i) for i in a.issues],
        "statements": [s.model_copy(update={"text": x(s.text), "step": x(s.step)}) for s in a.statements],
    }) if a is not None else None
    leads = (_split_pending(p) for p in report.pending)
    return report.model_copy(update={
        "language": lang, "disclaimer": x(report.disclaimer), "planning": planning, "assessment": assessment,
        "pending": [t(lead) + x(rest) if lead else x(rest) for lead, rest in leads],
        "translation": ReportTranslation(
            available=x.available, kept_original=x.kept_original,
            note=translation_note(x, verified=a is not None and a.content_verified and a.status == "VERIFIED",
                                  has_answer=a is not None and a.conclusion_summary is not None)),
    })
