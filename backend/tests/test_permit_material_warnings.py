"""TD-065: a material warning can't depend on what the model chose to write.

The verifier checks that what a draft says is supported; it can't see what a draft left out. So the warnings of a
request type are fixed text added by code, and the rules refuse a draft without them."""

import pytest

from app.schemas.permit import Condition
from app.services.i18n.translator import PINNED
from app.services.permit.requirements import (
    CATALOG,
    MATERIAL_WARNINGS,
    build_checklist_items,
    conditions_for,
    reconcile,
)
from app.services.permit.verifier import rule_checks, rules_outcome, Verifier
from tests.permit_fakes import ANSWERS, ScriptedModel, default_draft, make_client
from tests.test_permit_verifier import CHAIN, TRUST, TRUSTED, VERIFIED, Reviewer, checklist, draft, ev, item, matter
from tests.test_permit_workflow import answer, create, run

WARNED = sorted(MATERIAL_WARNINGS)
ALL = [(intent, key, text) for intent, warnings in MATERIAL_WARNINGS.items() for key, text in warnings]


def warnings_of(intent: str) -> list[Condition]:
    return [Condition(item_key=k, text=t) for k, t in MATERIAL_WARNINGS[intent]]


def outcome(the_draft, intent: str, records=None):
    c = checklist(intent=intent)
    issues, _ = rule_checks(matter(), c, the_draft, records or [ev("E1")], CHAIN, TRUSTED)
    return rules_outcome(issues, the_draft), [i for i in issues if i.code == "missing_material_warning"]


@pytest.mark.parametrize("intent", WARNED)
def test_the_warnings_are_added_whatever_the_evidence_says(intent):
    items = reconcile(intent, build_checklist_items(intent, {}), [])
    keys = [c["item_key"] for c in conditions_for(intent, items, [])]
    assert [k for k, _ in MATERIAL_WARNINGS[intent]] == [k for k in keys if k.startswith("warning_")]


def test_the_nullity_warning_is_in_every_unit_division():
    assert any("is null" in text and "co-ownership" in text for _, text in MATERIAL_WARNINGS["unit_conversion"])


@pytest.mark.parametrize(("intent", "key", "text"), ALL)
def test_a_warning_never_reaches_machine_translation(intent, key, text):
    assert text in PINNED


def test_warning_keys_are_unique_and_never_a_checklist_key():
    keys = [k for _, k, _ in ALL]
    assert len(keys) == len(set(keys))  # the workspace uses them as list keys
    assert not set(keys) & {r.key for reqs in CATALOG.values() for r in reqs}


@pytest.mark.parametrize("intent", WARNED)
def test_a_draft_without_the_warnings_is_rejected(intent):
    result, missing = outcome(draft(), intent)
    assert result == "REJECTED"
    assert {i.item_key for i in missing} == {k for k, _ in MATERIAL_WARNINGS[intent]}


@pytest.mark.parametrize(("intent", "key", "text"), ALL)
def test_one_missing_warning_is_enough_to_reject(intent, key, text):
    kept = [c for c in warnings_of(intent) if c.item_key != key]
    result, missing = outcome(draft(conditions=kept), intent)
    assert result == "REJECTED" and [i.item_key for i in missing] == [key]


@pytest.mark.parametrize(("intent", "key", "text"), ALL)
def test_a_reworded_warning_does_not_count(intent, key, text):
    conditions = [Condition(item_key=c.item_key, text=c.text + " Usually this is fine.") if c.item_key == key else c
                  for c in warnings_of(intent)]
    assert outcome(draft(conditions=conditions), intent)[0] == "REJECTED"


def test_citing_the_risk_record_does_not_replace_the_warning():
    nullity = ev("E2", finding_id="cc-1416-nullity")
    c = checklist(item("unit_conversion"), intent="unit_conversion")
    c.items[0].evidence_ids = ["E1", "E2"]
    issues, _ = rule_checks(matter(), c, draft(), [ev("E1"), nullity], CHAIN, TRUSTED)
    assert "missing_material_warning" in {i.code for i in issues}


async def test_a_passing_reviewer_cannot_override_a_missing_warning():
    reviewer = Reviewer(VERIFIED)
    c = checklist(intent="unit_conversion")
    report = await Verifier(reviewer, TRUST).verify(matter(), c, draft(), [ev("E1")], CHAIN)
    assert report.outcome == "REJECTED" and reviewer.calls == 0


@pytest.mark.parametrize("intent", WARNED)
def test_a_draft_with_the_warnings_passes_the_rules(intent):
    assert outcome(draft(conditions=warnings_of(intent)), intent) == (None, [])


def test_a_type_without_warnings_is_unaffected():
    assert outcome(draft(), "general_overview") == (None, [])


def test_a_model_that_writes_no_risk_still_gets_a_report_with_the_warning():
    """End to end: the drafter drops every risk and offers its own conditions; the report still warns."""
    def silent(payload):
        out = default_draft(payload)
        return {**out, "risks": [], "conditions": [{"item_key": "x", "text": "Nothing to worry about."}]}

    with make_client(ScriptedModel(draft=silent)) as client:
        matter_id = create(client)["matter_id"]
        run(client, matter_id)
        answer(client, matter_id, ANSWERS)
        done = run(client, matter_id)
        report = client.get(f"/api/permit/matters/{matter_id}/report").json()
    assert done["state"] == "VERIFIED" and done["draft"]["risks"] == []
    shown = report["assessment"]["conditions"]
    for _, text in MATERIAL_WARNINGS["unit_conversion"]:
        assert text in shown
    assert "Nothing to worry about." not in shown
