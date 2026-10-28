"""The independent verifier, deterministic reconciliation, and the question tool's contract."""

import json
from datetime import UTC, datetime

import pytest

from app.services.sources.registry import TrustPin
from app.schemas.permit import (
    NextAction,
    ProcedureStep,
    Risk,
    Checklist,
    ChecklistItem,
    Claim,
    Conclusion,
    Condition,
    Draft,
    Evidence,
    MatterState,
    PermitMatter,
)
from app.services.permit import requirements
from app.services.permit.model import ChatResult
from app.services.permit.sources.base import SourceRegistry
from app.services.permit.tools import PermitTools
from app.schemas.sources import SourceProvenance
from app.services.permit.verifier import Verifier, rule_checks

NOW = datetime(2026, 10, 28, tzinfo=UTC)
CHAIN = ["pt", "pt/lisboa", "pt/lisboa/cascais"]
AUTHORITY = "pt/lisboa/cascais:camara-municipal"


def matter(**kw) -> PermitMatter:
    return PermitMatter(matter_id="pm_0000000000000001", property_id="prp_0000000000000001", question="Convert?",
                        state=MatterState.VERIFYING, jurisdiction_id="pt/lisboa/cascais", authority_id=AUTHORITY,
                        created_at=NOW, updated_at=NOW, **kw)


#: Registry sources trusted for CHAIN (stands in for the official source registry).
TRUSTED = {"pt-rjue", "cascais-pdm"}


class Trust:
    async def trusted_ids(self, chain):
        return set(TRUSTED)

    async def pin(self, chain):
        return TrustPin({sid: ("trusted", 0) for sid in await self.trusted_ids(chain)})


TRUST = Trust()


def ev(eid: str, kind="regulatory_source", jurisdiction="pt", authority=None, matter_id="pm_0000000000000001",
       source="pt-rjue", **structured) -> Evidence:
    provenance = SourceProvenance(source_id=source, basis="curated_reference", trust_status="trusted") \
        if kind == "regulatory_source" else None
    return Evidence(evidence_id=eid, matter_id=matter_id, source_type=kind, source_title="t",
                    source_reference="r", jurisdiction_id=jurisdiction, authority_id=authority, retrieved_at=NOW,
                    claim_supported="x", excerpt="y", structured=structured, confidence="medium",
                    verification_status="curated_reference", dedupe_key=eid, provenance=provenance)


def item(key, status="satisfied", owner="SYSTEM_TOOL", required=True) -> ChecklistItem:
    return ChecklistItem(key=key, area="restrictions", question=f"{key}?", required=required, owner=owner, status=status,
                         evidence_ids=["E1"] if status == "satisfied" else [])


def checklist(*items: ChecklistItem) -> Checklist:
    return Checklist(matter_id="pm_0000000000000001", intent="unit_conversion", intent_summary="s",
                     items=list(items) or [item("jurisdiction")], model_id="m", created_at=NOW, updated_at=NOW)


def draft(*claims: Claim, answer="conditional", conditions=(), **sections) -> Draft:
    return Draft(revision=0, conclusion=sections.pop("conclusion", Conclusion(answer=answer, summary="s", evidence_ids=["E1"])),
                 claims=list(claims) or [Claim(claim_id="K1", text="t", material=True, evidence_ids=["E1"])],
                 conditions=list(conditions), procedure=sections.get("procedure", []), risks=sections.get("risks", []),
                 next_actions=sections.get("next_actions", []), model_id="m", created_at=NOW)


class Reviewer:
    model_id = "muse-spark-1.3"

    def __init__(self, review: dict) -> None:
        self.review = review
        self.calls = 0
        self.payload: dict | None = None

    async def chat(self, messages, **kwargs):
        self.calls += 1
        assert "VERIFIER" in messages[0]["content"]  # separate, independent role prompt
        self.payload = json.loads(messages[1]["content"])
        return ChatResult(content=json.dumps(self.review))


VERIFIED = {"outcome": "VERIFIED", "conclusion_follows": True, "issues": [], "suggested_follow_up": [], "summary": "ok"}
PLANNING_CONDITION = [Condition(item_key="planning_constraints", text="Confirm with the Câmara.")]


def codes(issues):
    return {i.code for i in issues}


# --- rules ------------------------------------------------------------------------------


def test_clean_draft_passes_rules():
    issues, checks = rule_checks(matter(), checklist(), draft(), [ev("E1")], CHAIN, TRUSTED)
    assert issues == [] and all(checks.values())


@pytest.mark.parametrize(
    ("the_draft", "records", "expected"),
    [
        (draft(Claim(claim_id="K1", text="Allowed.", material=True, evidence_ids=[])), [ev("E1")], "unsupported_claim"),
        (draft(Claim(claim_id="K1", text="t", material=True, evidence_ids=["E9"])), [ev("E1")], "unknown_evidence"),
        (draft(), [ev("E1", jurisdiction="pt/porto/porto")], "wrong_jurisdiction"),
        (draft(), [ev("E1", jurisdiction="pt/lisboa/cascais", authority="pt/porto/porto:camara-municipal")], "authority_mismatch"),
        (draft(answer="likely_possible", conditions=PLANNING_CONDITION), [ev("E1")], "definitive_with_conditions"),
    ],
    ids=["no-evidence", "invented-evidence-id", "other-municipality", "other-authority", "definitive-with-conditions"],
)
def test_rejecting_rule_failures(the_draft, records, expected):
    issues, _ = rule_checks(matter(), checklist(), the_draft, records, CHAIN, TRUSTED)
    assert expected in codes(issues)


def test_status_driven_rules():
    c = checklist(item("current_licensed_use", "needs_input", "USER"), item("unit_conversion", "open"),
                  item("planning_constraints", "blocked_external", "AUTHORITY"), item("notes", "open", required=False))
    issues, checks = rule_checks(matter(), c, draft(conditions=PLANNING_CONDITION), [ev("E1")], CHAIN, TRUSTED)
    assert codes(issues) == {"missing_information", "evidence_gap"}  # blocked_external is a condition, not an issue
    assert not checks["user_information_complete"] and not checks["no_evidence_gaps"]


# --- outcomes ---------------------------------------------------------------------------


async def test_rule_failure_rejects_without_consulting_the_model():
    reviewer = Reviewer(VERIFIED)
    bad = draft(Claim(claim_id="K1", text="Allowed.", material=True, evidence_ids=[]))
    report = await Verifier(reviewer, TRUST).verify(matter(), checklist(), bad, [ev("E1")], CHAIN)
    assert report.outcome == "REJECTED" and reviewer.calls == 0


async def test_unanswered_user_item_needs_input_and_gap_escalates():
    v = Verifier(Reviewer(VERIFIED), TRUST)
    needs = await v.verify(matter(), checklist(item("current_licensed_use", "needs_input", "USER")), draft(), [ev("E1")], CHAIN)
    gap = await v.verify(matter(), checklist(item("unit_conversion", "open")), draft(), [ev("E1")], CHAIN)
    assert (needs.outcome, gap.outcome) == ("NEEDS_INPUT", "ESCALATE")
    assert gap.unresolved == ["unit_conversion"]


async def test_undetermined_conclusion_escalates():
    report = await Verifier(Reviewer(VERIFIED), TRUST).verify(matter(), checklist(), draft(answer="undetermined"), [ev("E1")], CHAIN)
    assert report.outcome == "ESCALATE"


async def test_conditional_draft_with_conditions_can_be_verified_and_reviewer_sees_only_cited_evidence():
    reviewer = Reviewer(VERIFIED)
    c = checklist(item("jurisdiction"), item("planning_constraints", "blocked_external", "AUTHORITY"))
    report = await Verifier(reviewer, TRUST).verify(matter(), c, draft(conditions=PLANNING_CONDITION), [ev("E1"), ev("E2")], CHAIN)
    assert report.outcome == "VERIFIED" and report.unresolved == ["planning_constraints"]
    assert [e["id"] for e in reviewer.payload["evidence"]] == ["E1"]
    assert reviewer.payload["conditions"] == [{"item_key": "planning_constraints", "text": "Confirm with the Câmara."}]


@pytest.mark.parametrize(
    "review",
    [
        {**VERIFIED, "conclusion_follows": False},
        {**VERIFIED, "issues": [{"code": "contradiction", "message": "K1 vs E1", "claim_id": "K1"}]},
    ],
    ids=["says-verified-but-conclusion-does-not-follow", "says-verified-but-lists-issues"],
)
async def test_a_self_contradicting_model_pass_is_rejected(review):
    report = await Verifier(Reviewer(review), TRUST).verify(matter(), checklist(), draft(), [ev("E1")], CHAIN)
    assert report.outcome == "REJECTED"


async def test_follow_ups_are_recorded_separately_and_checklist_is_untouched():
    review = {**VERIFIED, "suggested_follow_up": [{"area": "restrictions", "text": "Check fire separation."}]}
    c = checklist(item("jurisdiction"))
    before = c.model_dump()
    report = await Verifier(Reviewer(review), TRUST).verify(matter(), c, draft(), [ev("E1")], CHAIN)
    assert report.outcome == "VERIFIED"
    assert [f.text for f in report.suggested_follow_up] == ["Check fire separation."]
    assert c.model_dump() == before


async def test_malformed_model_review_fails_instead_of_passing():
    with pytest.raises(ValueError):
        await Verifier(Reviewer({"outcome": "NEEDS_INPUT", "issues": [], "conclusion_follows": True}), TRUST).verify(
            matter(), checklist(), draft(), [ev("E1")], CHAIN)


# --- reconciliation ---------------------------------------------------------------------


def test_reconciliation_is_computed_from_evidence_and_owner():
    items = requirements.build_checklist_items("unit_conversion", {})
    evidence = [
        ev("E1", "jurisdiction_record"),
        ev("E2", "authority_record"),
        ev("E3", finding_id="cc-1415-autonomous-units"),
        ev("E4", finding_id="pdm-land-use", jurisdiction="pt/lisboa/cascais"),
        ev("E5", "user_statement", input_key="current_licensed_use"),
    ]
    status = {i.key: (i.status, i.evidence_ids) for i in requirements.reconcile("unit_conversion", items, evidence)}
    assert status["jurisdiction"] == ("satisfied", ["E1"])
    assert status["competent_authority"] == ("satisfied", ["E2"])
    assert status["unit_conversion"] == ("satisfied", ["E3"])
    assert status["current_licensed_use"] == ("satisfied", ["E5"])
    assert status["intended_use"] == ("needs_input", [])  # user-owned, unanswered
    assert status["licensing_procedure"] == ("open", [])  # system-owned, no evidence: a gap
    assert status["planning_constraints"] == ("blocked_external", ["E4"])  # rule found, parcel needs the authority
    assert status["required_documents"][0] == "blocked_external"
    conditions = requirements.conditions_for("unit_conversion", requirements.reconcile("unit_conversion", items, evidence))
    assert [c["item_key"] for c in conditions] == ["planning_constraints", "required_documents"]


def test_user_answer_for_another_key_does_not_satisfy_an_item():
    items = requirements.build_checklist_items("unit_conversion", {})
    status = {i.key: i.status for i in requirements.reconcile("unit_conversion", items,
                                                              [ev("E1", "user_statement", input_key="intended_use")])}
    assert status["intended_use"] == "satisfied" and status["current_licensed_use"] == "needs_input"


# --- question tool contract -------------------------------------------------------------


def tools_for(**matter_kw) -> PermitTools:
    items = {i.key: i for i in requirements.build_checklist_items("unit_conversion", {})}
    return PermitTools(matter=matter(**matter_kw), repository=None, properties=None,  # type: ignore[arg-type]
                       sources=SourceRegistry([]), checklist=items)


async def test_question_tool_accepts_only_canonical_unanswered_user_items():
    tools = tools_for(inputs={"ownership_status": "single owner"})
    result = await tools.execute("request_missing_information", {"items": [
        {"item_key": "current_licensed_use", "question": "Licensed use?", "reason": "r", "owner": "USER"},
        {"item_key": "current_licensed_use", "question": "Again?", "reason": "r", "owner": "USER"},
        {"item_key": "ownership_status", "question": "Owner?", "reason": "r", "owner": "USER"},
        {"item_key": "planning_constraints", "question": "Do you have municipal confirmation?", "reason": "r", "owner": "USER"},
        {"item_key": "licensing_procedure", "question": "Which procedure?", "reason": "r", "owner": "SYSTEM_TOOL"},
        {"item_key": "invented_key", "question": "?", "reason": "r", "owner": "USER"},
    ]})
    assert result["ok"] and result["accepted"] == ["current_licensed_use"]
    reasons = {r["item_key"]: r["reason"] for r in result["rejected"]}
    assert "duplicate" in reasons["ownership_status"]  # already answered
    assert "not user-owned (AUTHORITY)" in reasons["planning_constraints"]
    assert "not user-owned (SYSTEM_TOOL)" in reasons["licensing_procedure"]
    assert "unknown checklist key" in reasons["invented_key"]
    assert [m.input_key for m in tools.requested] == ["current_licensed_use"]


async def test_question_tool_caps_new_questions_per_round(monkeypatch):
    monkeypatch.setattr("app.services.permit.tools.USER_QUESTIONS_PER_ROUND", 2)
    tools = tools_for()
    result = await tools.execute("request_missing_information", {"items": [
        {"item_key": k, "question": "?", "reason": "r", "owner": "USER"}
        for k in ("current_licensed_use", "intended_use", "ownership_status")
    ]})
    assert result["accepted"] == ["current_licensed_use", "intended_use"]
    assert "at most 2" in result["rejected"][0]["reason"]



# --- evidence integrity (Codex CX-2 / Muse MU-1) ---------------------------------------


async def verify(d: Draft, records=None, reviewer=None):
    reviewer = reviewer or Reviewer(VERIFIED)
    report = await Verifier(reviewer, TRUST).verify(matter(), checklist(), d, records or [ev("E1")], CHAIN)
    return report, reviewer


@pytest.mark.parametrize(
    "the_draft",
    [
        draft(Claim(claim_id="K1", text="The RJUE requires a licence for this conversion.", evidence_ids=[])),
        draft(Claim(claim_id="K1", text="The building has two independent entrances.", evidence_ids=[])),
        draft(next_actions=[NextAction(text="Start the works; the authority has approved the conversion.")]),
        draft(procedure=[ProcedureStep(step="Apply", description="Submit a prior communication.")]),
        draft(risks=[Risk(text="Heritage rules forbid the division.")]),
        draft(conclusion=Conclusion(answer="conditional", summary="Approved by the Câmara.")),
    ],
    ids=["uncited-regulatory-claim", "uncited-property-claim", "uncited-recommended-action",
         "uncited-procedure", "uncited-risk", "uncited-conclusion"],
)
async def test_any_uncited_model_statement_blocks_verified_even_with_a_passing_reviewer(the_draft):
    report, reviewer = await verify(the_draft)
    assert report.outcome == "REJECTED" and reviewer.calls == 0
    assert "unsupported_claim" in codes(report.issues)


async def test_fake_evidence_id_blocks_verified():
    report, _ = await verify(draft(Claim(claim_id="K1", text="t", evidence_ids=["E404"])))
    assert report.outcome == "REJECTED" and "unknown_evidence" in codes(report.issues)


async def test_evidence_from_another_matter_cannot_satisfy_a_claim():
    report, _ = await verify(draft(), [ev("E1", matter_id="pm_ffffffffffffffff")])
    assert report.outcome == "REJECTED" and "foreign_evidence" in codes(report.issues)


async def test_evidence_from_an_incompatible_jurisdiction_cannot_satisfy_a_claim():
    report, _ = await verify(draft(), [ev("E1", jurisdiction="pt/porto/porto")])
    assert report.outcome == "REJECTED" and "wrong_jurisdiction" in codes(report.issues)


async def test_fully_cited_draft_can_still_be_verified():
    # (HR-003 CX-1: parcel planning prose is HABITA's condition, so these sections avoid it.)
    d = draft(next_actions=[NextAction(text="Ask the Câmara which documents the application needs.", evidence_ids=["E1"])],
              procedure=[ProcedureStep(step="Apply", description="Submit the prior-control application.", evidence_ids=["E1"])],
              risks=[Risk(text="Requirements not confirmed may delay the works.", evidence_ids=["E1"])])
    # Free text must be grounded in what it cites (HR-003 CX-1), so E1 carries realistic wording here.
    grounded = ev("E1").model_copy(update={"excerpt": "An application for prior control must be submitted to the "
                                                      "Câmara with the documents it needs; requirements not confirmed "
                                                      "may delay the works."})
    report, _ = await verify(d, [grounded])
    assert report.outcome == "VERIFIED" and report.checks["claims_supported"]


async def test_habita_generated_conditions_need_no_citation():
    c = checklist(item("jurisdiction"), item("planning_constraints", "blocked_external", "AUTHORITY"))
    report = await Verifier(Reviewer(VERIFIED), TRUST).verify(matter(), c, draft(conditions=PLANNING_CONDITION), [ev("E1")], CHAIN)
    assert report.outcome == "VERIFIED"


async def test_a_model_material_false_label_cannot_exempt_a_claim():
    # Even if a stored claim says material=False, every model-written claim is checked.
    report, _ = await verify(draft(Claim(claim_id="K1", text="Already approved.", material=False, evidence_ids=[])))
    assert report.outcome == "REJECTED" and "unsupported_claim" in codes(report.issues)
