"""Build the shared report model (HR-004 map, HR-006 PDF) from stored results only.

Pure: no model, retriever or verifier call, no storage access. Callers pass what HABITA already holds; this module
only selects, labels and orders it. The status rule is the one place where VERIFIED can appear."""

from datetime import UTC, datetime

from app.schemas.permit import Evidence, MatterState, PermitMatter, VerificationReport
from app.schemas.property import ResolvedProperty
from app.schemas.report import (
    PermitReport, ReportAssessment, ReportDocument, ReportEvidence, ReportPlanning, ReportProperty, ReportSource,
    ReportStatement, ReportStatus, ReportVerification,
)
from app.schemas.sources import OfficialSourceOut, PlanningContext

DISCLAIMER = (
    "HABITA AI provides decision support, not legal advice. This report is not a permit, licence or authorisation: "
    "only the competent authority decides. Statements are shown with their verification status and sources."
)

_REASONS = {
    "no_machine_readable_layer": "No validated machine-readable zoning layer exists for this jurisdiction.",
    "low_geocode_precision": "The location is not precise enough to place the property on a zoning map.",
    "no_feature_at_point": "No zoning feature was found at the property's location.",
    "multiple_features": "More than one zoning feature applies at the property's location.",
    "near_class_boundary": "The property lies near a boundary between zoning classes.",
    "boundary_distance_unknown": "The distance to the nearest zoning boundary is unknown.",
}


def _is_current(matter: PermitMatter, verification: VerificationReport | None) -> bool:
    """The report decided the matter's current draft: it is the matter's latest one, for the same draft revision."""
    return (verification is not None and matter.draft is not None
            and verification.verification_id == matter.latest_verification_id
            and verification.draft_revision == matter.draft.revision)


def assessment_status(matter: PermitMatter, verification: VerificationReport | None) -> tuple[ReportStatus, str]:
    """VERIFIED only when the matter itself presents a verified assessment (VERIFIED and not superseded by a raised
    protocol floor) and its latest verification report is VERIFIED, not superseded, for the same draft revision;
    REJECTED when the matter is, or that current report is; anything else is pending."""
    current = _is_current(matter, verification)
    if (matter.assessment_status == "verified_assessment" and current and verification.outcome == "VERIFIED"
            and not verification.superseded_protocol):
        return "VERIFIED", "The assessment passed HABITA's evidence and verification checks."
    if matter.state == MatterState.REJECTED or (current and verification.outcome == "REJECTED"):
        return "REJECTED", "The draft did not pass verification against its evidence."
    if matter.state == MatterState.VERIFIED:  # superseded or inconsistent: never presented as verified
        return "PENDING_CONFIRMATION", "Verified under an earlier protocol that HABITA no longer accepts; it must be verified again."
    reasons = {
        MatterState.NEEDS_INPUT: "HABITA needs answers from you before it can verify the assessment.",
        MatterState.ESCALATE: "The available sources don't settle this question; it needs the authority.",
        MatterState.FAILED: "The assessment stopped before verification; it can be resumed.",
    }
    return "PENDING_CONFIRMATION", reasons.get(matter.state, "The assessment has not been verified yet.")


def _property(prop: ResolvedProperty) -> ReportProperty:
    j = prop.jurisdiction
    return ReportProperty(
        property_id=prop.property_id, address=prop.formatted_address, lat=prop.coordinates.lat,
        lng=prop.coordinates.lng, precision=prop.precision, jurisdiction_id=j.id,
        jurisdiction=[f"{level.label}: {level.name}" for level in j.levels],
        authority=j.local_authority.name if j.local_authority else None,
    )


def _planning(context: PlanningContext) -> ReportPlanning:
    resolved = context.status == "resolved" and context.classification is not None
    return ReportPlanning(
        status=context.status, verified_zoning=resolved,
        classification=context.classification.label if resolved else None,
        instrument=context.instrument.title if context.instrument else None,
        instrument_version=context.instrument.version if context.instrument else None,
        reasons=[_REASONS.get(r, r) for r in context.reasons],
        documents_to_consult=[ReportDocument(title=d.title, designation=d.designation, url=d.official_url,
                                             reason=d.reason) for d in context.documents_to_consult],
        guidance=context.guidance,
    )


def _evidence(e: Evidence) -> ReportEvidence:
    p = e.provenance
    return ReportEvidence(
        evidence_id=e.evidence_id, title=e.source_title, reference=e.source_reference, url=e.source_url,
        source_type=e.source_type, verification_status=e.verification_status, retrieved_at=e.retrieved_at,
        excerpt=e.excerpt, source_id=p.source_id if p else None, trust_status=p.trust_status if p else None,
        version=p.version if p else None, snapshot_id=p.snapshot_id if p else None, sha256=p.sha256 if p else None,
        locator=p.locator if p else None,
    )


def _evidence_order(e: Evidence) -> tuple[int, int | str]:
    """E1, E2, … E10 in numeric order; any other id after them, alphabetically."""
    n = e.evidence_id[1:]
    return (0, int(n)) if e.evidence_id.startswith("E") and n.isdigit() else (1, e.evidence_id)


def _assessment(matter: PermitMatter, evidence: list[Evidence],
                verification: VerificationReport | None) -> ReportAssessment:
    status, reason = assessment_status(matter, verification)
    draft = matter.draft
    statements: list[ReportStatement] = []
    cited: set[str] = set()
    if draft is not None:
        for c in draft.claims:
            statements.append(ReportStatement(section="finding", label=c.claim_id, text=c.text,
                                              evidence_ids=c.evidence_ids))
        for n, p in enumerate(draft.procedure, 1):
            statements.append(ReportStatement(section="procedure", label=f"procedure {n}", text=p.description,
                                              step=p.step, evidence_ids=p.evidence_ids))
        for n, r in enumerate(draft.risks, 1):
            statements.append(ReportStatement(section="risk", label=f"risk {n}", text=r.text,
                                              evidence_ids=r.evidence_ids))
        for n, a in enumerate(draft.next_actions, 1):
            statements.append(ReportStatement(section="next_action", label=f"next action {n}", text=a.text,
                                              evidence_ids=a.evidence_ids))
        cited = {i for s in statements for i in s.evidence_ids} | set(draft.conclusion.evidence_ids)
    shown = [e for e in evidence if e.evidence_id in cited] if cited else list(evidence)
    rejected = status == "REJECTED"
    return ReportAssessment(
        matter_id=matter.matter_id, question=matter.question, state=str(matter.state), status=status,
        status_reason=reason, content_verified=status == "VERIFIED",
        conclusion_answer=draft.conclusion.answer if draft else None,
        conclusion_summary=draft.conclusion.summary if draft else None,
        conclusion_evidence_ids=list(draft.conclusion.evidence_ids) if draft else [],
        statements=statements, conditions=[c.text for c in draft.conditions] if draft else [],
        issues=[i.message for i in verification.issues] if rejected and verification else [],
        # The record is shown as current only when it is what decided the status shown; otherwise it is history.
        verification=ReportVerification(
            verification_id=verification.verification_id, outcome=verification.outcome,
            draft_revision=verification.draft_revision, created_at=verification.created_at,
            protocol=verification.protocol, trust_pin=dict(verification.trust_pin),
            current=status != "PENDING_CONFIRMATION" and _is_current(matter, verification),
        ) if verification is not None else None,
        evidence=[_evidence(e) for e in sorted(shown, key=_evidence_order)],
    )


def build_report(prop: ResolvedProperty, context: PlanningContext, sources: list[OfficialSourceOut],
                 matter: PermitMatter | None = None, evidence: list[Evidence] = (),
                 verification: VerificationReport | None = None, *, demo: bool = False,
                 now: datetime | None = None) -> PermitReport:
    planning = _planning(context)
    assessment = _assessment(matter, list(evidence), verification) if matter is not None else None
    pending: list[str] = []
    if not planning.verified_zoning:
        pending.append("Planning classification: confirm on the official maps or with the competent authority.")
    if assessment is not None:
        pending += [f"Condition: {c}" for c in assessment.conditions]
        if assessment.status != "VERIFIED":
            pending.append(f"Assessment: {assessment.status_reason}")
        if matter is not None:
            pending += [f"Your answer is needed: {m.question}" for m in matter.missing_inputs]
    return PermitReport(
        generated_at=now or datetime.now(UTC), property=_property(prop), planning=planning,
        sources=[ReportSource(source_id=s.source_id, title=s.title, publisher=s.publisher, url=s.official_url,
                              version=s.version, status=s.status, verified_on=s.verified_on) for s in sources],
        assessment=assessment, pending=pending, demo=demo, disclaimer=DISCLAIMER,
    )
