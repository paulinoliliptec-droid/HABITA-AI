"""MU-9 acceptance corpus (Phase 0). See ``tests/mu9_acceptance.py`` and ``tests/data/mu9_acceptance.json``.

Every automated case runs through render → reconcile → Verifier with an always-approving Reviewer. A case with
``status: "open"`` (it failed on the frozen baseline ``98af6af``) is a strict xfail tagged with the phase that must
close it: when a change fixes it, the xpass fails the run until the case is promoted (``--promote``). A ``closed``
case that fails is a regression. Critical cases (``final_gate``) also run end to end through the workflow, the
final gate and the commit; ``final_gate_open`` lists the bases that still persisted VERIFIED at the freeze."""

import pytest

from tests.mu9_acceptance import load, observe, passes
from tests.permit_fakes import ScriptedModel, default_draft, make_client
from tests.test_permit_official_sources import auth, ingest_regulamento, run_matter

CORPUS = load()
CASES = CORPUS["cases"]
FROZEN = "98af6af"
FIELDS = {"id", "group", "statement", "lang", "provenance", "wording", "evidence_sets", "bases", "sections",
          "classification", "expected", "rationale", "harness", "final_gate", "fixed_in_phase", "status"}


def open_at_freeze(case) -> bool:
    return case["status"] == "open"


def marks(case):
    if case["harness"] == "verifier" and open_at_freeze(case):
        return [pytest.mark.xfail(strict=True, reason=f"open; to close in phase {case['fixed_in_phase']}")]
    return []


def test_every_case_is_complete_and_honest_about_its_provenance():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))
    for c in CASES:
        assert FIELDS <= c.keys(), c["id"]
        assert c["expected"] in {"REJECTED", "VERIFIED"}, c["id"]
        assert c["provenance"].get("reviewer") and c["provenance"].get("source"), c["id"]
        assert c["rationale"], c["id"]
        if c["harness"] != "verifier":
            assert c["status"] == "not_run", c["id"]
        if c["wording"] == "UNAVAILABLE":
            assert c["statement"] is None and c["harness"] == "unavailable", c["id"]
        else:
            assert c["statement"], c["id"]
        if c["harness"] == "verifier":
            assert FROZEN in c["observed"] and c["status"] in {"open", "closed"}, c["id"]
            if c["final_gate"]:
                assert set(c["final_gate_open"]) <= {"general_planning_explanation", "none"}, c["id"]
            assert c["expected"] == "VERIFIED" or c["fixed_in_phase"] or not open_at_freeze(c), c["id"]


def test_reviewer_groups_are_kept_apart():
    """C4: the E13 licensing attacks and the CX-1 zoning attacks are separate groups with their own provenance."""
    e13 = [c for c in CASES if c["group"] == "E13"]
    assert len(e13) == 6 and all(c["provenance"]["reviewer"] == "Codex" and "E13" in c["provenance"]["finding"]
                                 for c in e13)
    assert all(c["original_evidence"] == {"evidence_sets": ["pdm"], "bases": ["general_planning_explanation"],
                                          "sections": "all 5"} for c in e13)
    assert not any(c["group"] == "CX1" and "E13" in c["provenance"].get("finding", "") for c in CASES)


@pytest.mark.parametrize("case", [pytest.param(c, id=c["id"], marks=marks(c))
                                  for c in CASES if c["harness"] == "verifier"])
async def test_acceptance_case(case):
    seen = await observe(case)
    assert passes(case, seen), (case["expected"], seen["verified"], seen["verified_runs"][:5])


FINAL_GATE_RUNS = [("general_planning_explanation", "regulatory_source"), ("none", "authority_record")]


def _final_gate_param(case, basis, cited):
    leaked = basis in case["final_gate_open"]
    marks = [pytest.mark.xfail(strict=True, reason="persisted VERIFIED at the freeze; to close in phase "
                               f"{case['fixed_in_phase'] or 3}")] if leaked else []
    return pytest.param(case, basis, cited, id=f"{case['id']}-{basis}", marks=marks)


@pytest.mark.parametrize("case, basis, cited", [_final_gate_param(c, b, t) for c in CASES
                                                if c["final_gate"] and c["harness"] == "verifier"
                                                for b, t in FINAL_GATE_RUNS])
def test_critical_case_never_persists_verified_through_the_final_gate(case, basis, cited):
    """End to end: manual planning context, the PDM ingested, a passing reviewer, the final gate and the commit."""
    def drafting(payload):
        d = default_draft(payload)
        ids = [e["id"] for e in payload["evidence"] if e["type"] == cited]
        assert ids, cited
        d["claims"].append({"text": case["statement"], "evidence_ids": ids, "planning_basis": basis, "quote": None})
        return d

    with make_client(ScriptedModel(draft=drafting)) as client:
        ingest_regulamento(client)
        mid, token = run_matter(client)
        state = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()["state"]
        report = client.get(f"/api/permit/matters/{mid}/verification", headers=auth(token)).json()
    assert state != "VERIFIED" and report["outcome"] != "VERIFIED", (state, report["outcome"])
