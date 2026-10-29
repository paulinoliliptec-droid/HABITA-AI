"""Independent verification of a Permit draft.

Input contract: the *reconciled* checklist (statuses computed from evidence just
before verification), the draft, and only the evidence the draft cites. The
verifier never sees the executor's conversation and never changes the checklist:
it returns a VerificationReport. Requirements it would add are returned as
``suggested_follow_up`` for review, not inserted into the active checklist.

Two layers:

Evidence is re-validated against the registry *now* (``admissibility``): records stay as
history, but only currently admissible ones can support a checklist item or a statement,
and the report lists the excluded ones separately.

1. Rules (deterministic, always):
   - REJECTED: any model-written statement without evidence (every claim,
     procedure step, risk, next action and the conclusion; the model cannot
     exempt its own statements), a citation of evidence that doesn't exist or
     belongs to another matter, evidence from outside the property's jurisdiction
     chain, a different authority, regulatory or planning evidence whose source is not
     trusted in the official registry for this jurisdiction (or official text without
     a snapshot hash), a statement placing the parcel in a zoning class or category
     without citing an authoritative planning determination for this property, or a
     definitive answer while conditions remain.
     Only HABITA-generated text (conditions, status notes) needs no citation;
   - NEEDS_INPUT: a required user-owned item is still unanswered;
   - ESCALATE: a required item HABITA's tools could not evidence (a gap, including an item
     whose only support is no longer admissible), or an
     "undetermined" conclusion.
2. Model review (Muse Spark, separate prompt, only when the rules pass):
   VERIFIED / REJECTED / ESCALATE. It can only tighten the outcome.
"""

import json
from datetime import UTC, datetime

from app.schemas.permit import (
    Checklist,
    ClaimAtom,
    Draft,
    Evidence,
    FollowUp,
    PermitMatter,
    VerificationIssue,
    VerificationReport,
)
from app.services.permit import prompts
from app.services.permit.model import ReasoningModel
from app.services.permit.repository import new_verification_id
from app.services.permit.tools import compact_evidence
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.services.permit.admissibility import (
    EXPLANATION,
    USER_DECLARATION,
    SOURCED,
    inadmissibility,
    is_determination,
    is_user_declared,
    partition,
    source_problem,
    statement_problem,
)
from app.services.permit.claims import assess, legal_claim_problem, verdict
from app.services.sources.registry import OfficialSourceRegistry, TrustPin

__all__ = ["Verifier", "rule_checks", "model_statements", "cited_ids", "source_problem", "SOURCED"]

DEFINITIVE = {"likely_possible", "likely_not_possible"}
#: The protocol this verifier implements: the planning contract plus atomic legal claims (MU-9 Phase 1).
PROTOCOL = "atomic-v1"
REJECTING = {
    "unsupported_claim", "unknown_evidence", "foreign_evidence", "wrong_jurisdiction", "authority_mismatch",
    "definitive_with_conditions", "untrusted_source", "unverified_zoning", "unsupported_legal_claim",
}
#: A required item without currently admissible support is a gap (ESCALATE), not a pass.
GAPS = {"evidence_gap", "inadmissible_support"}


@dataclass(frozen=True)
class Statement:
    label: str
    text: str
    evidence_ids: list[str]
    planning_basis: str
    quote: str | None = None
    step: str | None = None  # procedure only

    @property
    def display(self) -> str:
        return f"{self.step}: {self.text}" if self.step is not None else self.text


def model_statements(draft: Draft) -> list[Statement]:
    """Every statement in the draft. All of them need evidence and a valid planning basis."""
    c = draft.conclusion
    out = [Statement("conclusion", c.summary, c.evidence_ids, c.planning_basis, c.quote)]
    out += [Statement(k.claim_id, k.text, k.evidence_ids, k.planning_basis, k.quote) for k in draft.claims]
    out += [Statement(f"procedure {n}", p.description, p.evidence_ids, p.planning_basis, p.quote, p.step)
            for n, p in enumerate(draft.procedure, 1)]
    out += [Statement(f"risk {n}", r.text, r.evidence_ids, r.planning_basis, r.quote) for n, r in enumerate(draft.risks, 1)]
    out += [Statement(f"next action {n}", a.text, a.evidence_ids, a.planning_basis, a.quote)
            for n, a in enumerate(draft.next_actions, 1)]
    return out


def cited_ids(draft: Draft) -> set[str]:
    return {eid for s in model_statements(draft) for eid in s.evidence_ids}


#: The planning resolver's current answer for a matter's property (None if unavailable).
PlanningState = Callable[[PermitMatter], Awaitable[object | None]]


def rules_outcome(issues: list[VerificationIssue], draft: Draft) -> str | None:
    """The outcome the deterministic rules impose, or None when they let the draft through to review."""
    codes = {i.code for i in issues}
    if codes & REJECTING:
        return "REJECTED"
    if "missing_information" in codes:
        return "NEEDS_INPUT"
    if codes & GAPS:
        return "ESCALATE"
    if draft.conclusion.answer == "undetermined":
        issues.append(VerificationIssue(code="undetermined", origin="rule",
                                        message="The available sources do not determine an answer."))
        return "ESCALATE"
    return None


def rule_checks(
    matter: PermitMatter, checklist: Checklist, draft: Draft, evidence: list[Evidence], jurisdiction_chain: list[str],
    trusted_sources: set[str], current_planning=None,
) -> tuple[list[VerificationIssue], dict[str, bool]]:
    by_id = {e.evidence_id: e for e in evidence}
    issues: list[VerificationIssue] = []

    for item in checklist.items:
        if not item.required:
            continue
        if item.status == "needs_input":
            issues.append(VerificationIssue(code="missing_information", item_key=item.key, origin="rule",
                                            message=f"Waiting for the user's answer to '{item.key}'."))
        elif item.status == "open":
            issues.append(VerificationIssue(code="evidence_gap", item_key=item.key, origin="rule",
                                            message=f"HABITA found no evidence for '{item.key}': {item.question}"))
        elif item.status == "satisfied":
            # Re-validate the support now (CX-2): history stays, but retired, untrusted, missing or foreign
            # records can't satisfy a required item. Mixed support counts only its admissible records.
            admissible = [eid for eid in item.evidence_ids if eid in by_id
                          and inadmissibility(by_id[eid], matter, jurisdiction_chain, trusted_sources) is None]
            if not admissible:
                issues.append(VerificationIssue(
                    code="inadmissible_support", item_key=item.key, origin="rule",
                    message=f"'{item.key}' is supported only by evidence that is not currently admissible "
                            f"({', '.join(item.evidence_ids) or 'none'})."))

    # Materiality is not the model's call: every model-written statement must cite evidence.
    case_facts = [e for e in evidence if e.source_type in ("property_record", "jurisdiction_record", "authority_record")
                  and inadmissibility(e, matter, jurisdiction_chain, trusted_sources) is None]
    for st in model_statements(draft):
        if not st.evidence_ids:
            issues.append(VerificationIssue(code="unsupported_claim", claim_id=st.label if st.label.startswith("K") else None,
                                            origin="rule", message=f"The draft's {st.label} cites no evidence."))
        # Planning contract (CX-1): structured statements must be exactly HABITA-derived content; free text
        # must be non-planning and grounded in what it cites. Checked here, never left to the model.
        cited = [by_id[i] for i in st.evidence_ids if i in by_id
                 and inadmissibility(by_id[i], matter, jurisdiction_chain, trusted_sources) is None]
        section = "claim" if st.label.startswith("K") else st.label.rsplit(" ", 1)[0] if st.label[-1].isdigit() else st.label
        if problem := statement_problem(st.text, st.planning_basis, st.quote, st.step, cited, matter,
                                        draft.conditions, case_facts, current_planning, section):
            issues.append(VerificationIssue(code="unverified_zoning", claim_id=st.label if st.label.startswith("K") else None,
                                            origin="rule", message=f"The draft's {st.label} {problem}."))
        # Atomic legal claims (MU-9): what each sentence asserts, about whom, and whether the cited records can
        # prove it in the direction stated. Only adds rejections; rendered statements are HABITA's own text.
        if problem := legal_claim_problem(st.text, st.planning_basis, st.step, cited):
            issues.append(VerificationIssue(code="unsupported_legal_claim",
                                            claim_id=st.label if st.label.startswith("K") else None, origin="rule",
                                            message=f"The draft's {st.label} {problem}."))
    for eid in sorted(cited_ids(draft)):
        e = by_id.get(eid)
        if e is None:
            issues.append(VerificationIssue(code="unknown_evidence", evidence_id=eid, origin="rule",
                                            message=f"The draft cites {eid}, which does not exist."))
            continue
        if e.matter_id != matter.matter_id:
            issues.append(VerificationIssue(code="foreign_evidence", evidence_id=eid, origin="rule",
                                            message=f"{eid} belongs to another matter."))
            continue
        if e.jurisdiction_id not in jurisdiction_chain:
            issues.append(VerificationIssue(code="wrong_jurisdiction", evidence_id=eid, origin="rule",
                                            message=f"{eid} belongs to {e.jurisdiction_id}, outside this property's jurisdiction."))
        if e.source_type in SOURCED and (problem := source_problem(e, trusted_sources)):
            issues.append(VerificationIssue(code="untrusted_source", evidence_id=eid, origin="rule",
                                            message=f"{eid} {problem}."))
        if e.authority_id and matter.authority_id and e.authority_id != matter.authority_id:
            issues.append(VerificationIssue(code="authority_mismatch", evidence_id=eid, origin="rule",
                                            message=f"{eid} concerns {e.authority_id}, not the competent authority {matter.authority_id}."))

    if draft.conditions and draft.conclusion.answer in DEFINITIVE:
        issues.append(VerificationIssue(code="definitive_with_conditions", origin="rule",
                                        message="The conclusion is definitive although conditions remain to be confirmed: "
                                        + ", ".join(c.item_key for c in draft.conditions)))

    codes = {i.code for i in issues}
    checks = {
        "claims_supported": not codes & {"unsupported_claim", "unknown_evidence", "foreign_evidence"},
        "jurisdiction_consistent": "wrong_jurisdiction" not in codes,
        "authority_consistent": "authority_mismatch" not in codes,
        "sources_trusted": "untrusted_source" not in codes,
        "zoning_supported": "unverified_zoning" not in codes,
        "legal_claims_supported": "unsupported_legal_claim" not in codes,
        # The invariant, recomputed here and at the final gate: only official, resolved planning-context records
        # for this property back a parcel determination; user declarations never do.
        "determinations_authoritative": all(
            any(is_determination(by_id[i], matter) for i in st.evidence_ids if i in by_id)
            and not any(is_user_declared(by_id[i]) for i in st.evidence_ids if i in by_id)
            for st in model_statements(draft) if st.planning_basis == "parcel_determination"),
        "support_admissible": "inadmissible_support" not in codes,
        "conclusion_proportionate": "definitive_with_conditions" not in codes,
        "user_information_complete": "missing_information" not in codes,
        "no_evidence_gaps": not codes & GAPS,
    }
    return issues, checks


def claim_audit(matter: PermitMatter, draft: Draft, evidence: list[Evidence], jurisdiction_chain: list[str],
                trusted_sources: set[str]) -> list[ClaimAtom]:
    """Every atomic legal claim of the draft with its verdict, on the same admissible citations the rules use."""
    by_id = {e.evidence_id: e for e in evidence}
    out = []
    for st in model_statements(draft):
        cited = [by_id[i] for i in st.evidence_ids if i in by_id
                 and inadmissibility(by_id[i], matter, jurisdiction_chain, trusted_sources) is None]
        for atom in assess(st.text, st.planning_basis, st.step, cited):
            result, reason = verdict(atom, cited)
            out.append(ClaimAtom(statement=st.label, text=atom.text, kind=atom.kind, bearer=atom.bearer,
                                 supported_by=list(atom.supported_by), verdict=result, enforced=atom.enforced,
                                 reason=reason))
    return out


class Verifier:
    def __init__(self, model: ReasoningModel, sources: OfficialSourceRegistry, planning: PlanningState | None = None) -> None:
        self._model = model
        self._sources = sources
        #: Re-resolves the property's planning context; without it, parcel determinations fail closed.
        self._planning = planning

    async def _current_planning(self, matter: PermitMatter, draft: Draft):
        if self._planning is None or not any(s.planning_basis == "parcel_determination" for s in model_statements(draft)):
            return None
        return await self._planning(matter)

    async def verify(
        self, matter: PermitMatter, checklist: Checklist, draft: Draft, evidence: list[Evidence], jurisdiction_chain: list[str]
    ) -> VerificationReport:
        # Trust is read at verification time: a source retired since the evidence was recorded fails here.
        trusted = await self._sources.trusted_ids(jurisdiction_chain)
        planning_now = await self._current_planning(matter, draft)
        issues, checks = rule_checks(matter, checklist, draft, evidence, jurisdiction_chain, trusted, planning_now)
        review, model_id, follow_up = None, None, []

        outcome = rules_outcome(issues, draft)
        if outcome is None:
            review = await self._review(matter, checklist, draft, evidence)
            model_id = self._model.model_id
            follow_up = [FollowUp(**f) for f in review["suggested_follow_up"]]
            checks["model_review_passed"] = review["outcome"] == "VERIFIED" and review["conclusion_follows"]
            issues.extend(
                VerificationIssue(code=i["code"], message=i["message"], claim_id=i.get("claim_id"), origin="model")
                for i in review["issues"]
            )
            # The reviewer's reading of parcel-planning reliance is enforced by code: a flagged statement passes
            # only if it declared, and the rules validated, an authoritative parcel determination.
            # Structured statements are HABITA-rendered (rules checked them); model-worded statements (free text and
            # general explanations) must not rely on the parcel's planning. The flag can only tighten.
            basis = {st.label: st.planning_basis for st in model_statements(draft)}
            for label in review["parcel_planning_statements"]:
                if basis.get(label, "none") in ("none", EXPLANATION, USER_DECLARATION):
                    issues.append(VerificationIssue(
                        code="unverified_zoning", claim_id=label if label.startswith("K") else None, origin="model",
                        message=f"The reviewer reads the draft's {label} as relying on the parcel's planning "
                                "classification, which no authoritative determination for this property supports."))
            if any(i.code == "unverified_zoning" for i in issues):
                checks["zoning_supported"] = False
            outcome = review["outcome"]
            if outcome == "VERIFIED" and (not review["conclusion_follows"] or review["issues"]
                                          or not checks["zoning_supported"]):
                outcome = "REJECTED"  # the model's own findings contradict a pass

        report = VerificationReport(
            verification_id=new_verification_id(),
            matter_id=matter.matter_id,
            draft_revision=draft.revision,
            outcome=outcome,
            issues=issues,
            checks=checks,
            unresolved=[i.key for i in checklist.items if i.status != "satisfied"],
            excluded_evidence=_excluded(evidence, matter, jurisdiction_chain, trusted),
            suggested_follow_up=follow_up,
            model_review=review,
            model_id=model_id,
            created_at=datetime.now(UTC),
            protocol=PROTOCOL,
            claim_atoms=claim_audit(matter, draft, evidence, jurisdiction_chain, trusted),
        )
        if report.outcome == "VERIFIED":
            # Trust may have changed while the rules ran or the reviewer was thinking (CX-2).
            report = await self.final_gate(report, matter, checklist, draft, evidence, jurisdiction_chain)
        return report

    async def final_gate(
        self, report: VerificationReport, matter: PermitMatter, checklist: Checklist, draft: Draft,
        evidence: list[Evidence], jurisdiction_chain: list[str], pin: TrustPin | None = None,
    ) -> VerificationReport:
        """Re-run every rule on one read of the registry (``pin``: each applicable source's status and version).

        A pass keeps the report (``final_gate_passed``); any rule failure replaces VERIFIED with the outcome the
        rules impose, recording the failures. Evidence stays as history either way. The report records the pin
        (``trust_pin``): the workflow commits VERIFIED only while that pin still holds (``commit_verified``)."""
        pin = pin or await self._sources.pin(jurisdiction_chain)
        trusted = pin.trusted_ids
        planning_now = await self._current_planning(matter, draft)
        issues, checks = rule_checks(matter, checklist, draft, evidence, jurisdiction_chain, trusted, planning_now)
        outcome = rules_outcome(issues, draft)
        excluded = _excluded(evidence, matter, jurisdiction_chain, trusted)
        atoms = claim_audit(matter, draft, evidence, jurisdiction_chain, trusted)
        if outcome is None:
            return report.model_copy(update={"checks": {**report.checks, "final_gate_passed": True},
                                             "excluded_evidence": excluded, "trust_pin": pin.audit(),
                                             "protocol": PROTOCOL, "claim_atoms": atoms})
        gate_issues = [i.model_copy(update={"message": "Final check: " + i.message}) for i in issues]
        return report.model_copy(update={
            "outcome": outcome,
            "issues": report.issues + gate_issues,
            "checks": {**report.checks, **checks, "final_gate_passed": False},
            "excluded_evidence": excluded,
            "trust_pin": pin.audit(),
            "protocol": PROTOCOL,
            "claim_atoms": atoms,
        })

    async def _review(self, matter: PermitMatter, checklist: Checklist, draft: Draft, evidence: list[Evidence]) -> dict:
        payload = {
            "goal": matter.question,
            "user_answers": matter.inputs,
            "checklist": [{"key": i.key, "owner": i.owner, "status": i.status, "evidence": i.evidence_ids} for i in checklist.items],
            "conditions": [c.model_dump() for c in draft.conditions],
            # Only the evidence the draft relies on.
            "evidence": compact_evidence(evidence, only=cited_ids(draft)),
            "draft": draft.model_dump(include={"conclusion", "claims", "procedure", "risks", "next_actions"}),
            "statements": [{"label": st.label, "text": st.display, "planning_basis": st.planning_basis}
                           for st in model_statements(draft)],
        }
        result = await self._model.chat(
            [
                {"role": "system", "content": prompts.VERIFIER},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            response_schema=prompts.VERIFIER_SCHEMA,
            schema_name="verification",
        )
        review = json.loads(result.content or "")
        # Shape check: a malformed review must fail the step, never pass the draft.
        if not isinstance(review, dict) or review.get("outcome") not in {"VERIFIED", "REJECTED", "ESCALATE"}:
            raise ValueError("invalid verifier output")
        if not isinstance(review.get("issues"), list) or not isinstance(review.get("conclusion_follows"), bool):
            raise ValueError("invalid verifier output")
        if not isinstance(review.get("suggested_follow_up", []), list):
            raise ValueError("invalid verifier output")
        if not isinstance(review.get("parcel_planning_statements", []), list):
            raise ValueError("invalid verifier output")
        review.setdefault("suggested_follow_up", [])
        review.setdefault("parcel_planning_statements", [])
        return review


def _excluded(evidence: list[Evidence], matter: PermitMatter, chain: list[str], trusted: set[str]) -> list[dict[str, str]]:
    return [{"evidence_id": x.evidence_id, "reason": x.reason} for x in partition(evidence, matter, chain, trusted)[1]]
