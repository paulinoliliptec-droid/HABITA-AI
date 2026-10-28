"""Independent verification of a Permit draft.

Input contract: the *reconciled* checklist (statuses computed from evidence just
before verification), the draft, and only the evidence the draft cites. The
verifier never sees the executor's conversation and never changes the checklist:
it returns a VerificationReport. Requirements it would add are returned as
``suggested_follow_up`` for review, not inserted into the active checklist.

Two layers:

1. Rules (deterministic, always):
   - REJECTED: any model-written statement without evidence (every claim,
     procedure step, risk, next action and the conclusion; the model cannot
     exempt its own statements), a citation of evidence that doesn't exist or
     belongs to another matter, evidence from outside the property's jurisdiction
     chain, a different authority, or a definitive answer while conditions remain.
     Only HABITA-generated text (conditions, status notes) needs no citation;
   - NEEDS_INPUT: a required user-owned item is still unanswered;
   - ESCALATE: a required item HABITA's tools could not evidence (a gap), or an
     "undetermined" conclusion.
2. Model review (Muse Spark, separate prompt, only when the rules pass):
   VERIFIED / REJECTED / ESCALATE. It can only tighten the outcome.
"""

import json
from datetime import UTC, datetime

from app.schemas.permit import (
    Checklist,
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

DEFINITIVE = {"likely_possible", "likely_not_possible"}
REJECTING = {
    "unsupported_claim", "unknown_evidence", "foreign_evidence", "wrong_jurisdiction", "authority_mismatch",
    "definitive_with_conditions",
}


def model_statements(draft: Draft) -> list[tuple[str, str, list[str]]]:
    """Every statement the model wrote, as (label, text, evidence_ids). All of them need evidence."""
    statements = [("conclusion", draft.conclusion.summary, draft.conclusion.evidence_ids)]
    statements += [(claim.claim_id, claim.text, claim.evidence_ids) for claim in draft.claims]
    statements += [(f"procedure {n}", p.description, p.evidence_ids) for n, p in enumerate(draft.procedure, 1)]
    statements += [(f"risk {n}", r.text, r.evidence_ids) for n, r in enumerate(draft.risks, 1)]
    statements += [(f"next action {n}", a.text, a.evidence_ids) for n, a in enumerate(draft.next_actions, 1)]
    return statements


def cited_ids(draft: Draft) -> set[str]:
    return {eid for _, _, ids in model_statements(draft) for eid in ids}


def rule_checks(
    matter: PermitMatter, checklist: Checklist, draft: Draft, evidence: list[Evidence], jurisdiction_chain: list[str]
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

    # Materiality is not the model's call: every model-written statement must cite evidence.
    for label, _text, ids in model_statements(draft):
        if not ids:
            issues.append(VerificationIssue(code="unsupported_claim", claim_id=label if label.startswith("K") else None,
                                            origin="rule", message=f"The draft's {label} cites no evidence."))
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
        "conclusion_proportionate": "definitive_with_conditions" not in codes,
        "user_information_complete": "missing_information" not in codes,
        "no_evidence_gaps": "evidence_gap" not in codes,
    }
    return issues, checks


class Verifier:
    def __init__(self, model: ReasoningModel) -> None:
        self._model = model

    async def verify(
        self, matter: PermitMatter, checklist: Checklist, draft: Draft, evidence: list[Evidence], jurisdiction_chain: list[str]
    ) -> VerificationReport:
        issues, checks = rule_checks(matter, checklist, draft, evidence, jurisdiction_chain)
        codes = {i.code for i in issues}
        review, model_id, follow_up = None, None, []

        if codes & REJECTING:
            outcome = "REJECTED"
        elif "missing_information" in codes:
            outcome = "NEEDS_INPUT"
        elif "evidence_gap" in codes:
            outcome = "ESCALATE"
        elif draft.conclusion.answer == "undetermined":
            outcome = "ESCALATE"
            issues.append(VerificationIssue(code="undetermined", origin="rule",
                                            message="The available sources do not determine an answer."))
        else:
            review = await self._review(matter, checklist, draft, evidence)
            model_id = self._model.model_id
            follow_up = [FollowUp(**f) for f in review["suggested_follow_up"]]
            checks["model_review_passed"] = review["outcome"] == "VERIFIED" and review["conclusion_follows"]
            issues.extend(
                VerificationIssue(code=i["code"], message=i["message"], claim_id=i.get("claim_id"), origin="model")
                for i in review["issues"]
            )
            outcome = review["outcome"]
            if outcome == "VERIFIED" and (not review["conclusion_follows"] or review["issues"]):
                outcome = "REJECTED"  # the model's own findings contradict a pass

        return VerificationReport(
            verification_id=new_verification_id(),
            matter_id=matter.matter_id,
            draft_revision=draft.revision,
            outcome=outcome,
            issues=issues,
            checks=checks,
            unresolved=[i.key for i in checklist.items if i.status != "satisfied"],
            suggested_follow_up=follow_up,
            model_review=review,
            model_id=model_id,
            created_at=datetime.now(UTC),
        )

    async def _review(self, matter: PermitMatter, checklist: Checklist, draft: Draft, evidence: list[Evidence]) -> dict:
        payload = {
            "goal": matter.question,
            "user_answers": matter.inputs,
            "checklist": [{"key": i.key, "owner": i.owner, "status": i.status, "evidence": i.evidence_ids} for i in checklist.items],
            "conditions": [c.model_dump() for c in draft.conditions],
            # Only the evidence the draft relies on.
            "evidence": compact_evidence(evidence, only=cited_ids(draft)),
            "draft": draft.model_dump(include={"conclusion", "claims", "procedure", "risks", "next_actions"}),
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
        review.setdefault("suggested_follow_up", [])
        return review
