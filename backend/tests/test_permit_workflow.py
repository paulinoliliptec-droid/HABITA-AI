"""Permit workflow end to end through the API, with the scripted Muse Spark stand-in."""

import pytest

from app.core.errors import UpstreamServiceError
from app.services.permit.model import ToolCall
from app.services.permit.workflow import MAX_ROUNDS
from tests.permit_fakes import (
    ANSWERS,
    CONVERSION_QUESTION,
    USER_KEYS,
    ScriptedModel,
    default_draft,
    default_investigation,
    make_client,
    resolve_cascais,
)


@pytest.fixture
def model() -> ScriptedModel:
    return ScriptedModel()


@pytest.fixture
def client(model):
    with make_client(model) as c:
        yield c


def create(client, question: str = CONVERSION_QUESTION) -> dict:
    res = client.post("/api/permit/matters", json={"property_id": resolve_cascais(client), "question": question})
    assert res.status_code == 201, res.text
    body = res.json()
    # The creator's capability: every later request in the test carries it.
    client.headers["Authorization"] = f"Bearer {body['access_token']}"
    return body["matter"]


def run(client, matter_id: str) -> dict:
    res = client.post(f"/api/permit/matters/{matter_id}/continue")
    assert res.status_code == 200, res.text
    return res.json()


def answer(client, matter_id: str, answers: dict | None = None) -> dict:
    res = client.post(f"/api/permit/matters/{matter_id}/inputs", json={"inputs": answers or ANSWERS})
    assert res.status_code == 200, res.text
    return res.json()


def checklist(client, matter_id):
    return {i["key"]: i for i in client.get(f"/api/permit/matters/{matter_id}/checklist").json()["items"]}


# --- convergence ------------------------------------------------------------------------


def test_converges_to_needs_input_with_only_user_owned_questions(client, model):
    matter_id = create(client)["matter_id"]
    paused = run(client, matter_id)

    assert paused["state"] == "NEEDS_INPUT"
    assert [m["input_key"] for m in paused["missing_inputs"]] == list(USER_KEYS)
    assert {m["owner"] for m in paused["missing_inputs"]} == {"USER"}
    # The model's phrasing is used where it asked; canonical wording otherwise.
    assert paused["missing_inputs"][0]["question"] == "What is the property's currently licensed use?"
    assert paused["draft"] is None  # no draft call while user facts are missing
    items = checklist(client, matter_id)
    assert items["planning_constraints"]["status"] == "blocked_external"  # a condition, never a question
    assert items["planning_constraints"]["owner"] == "AUTHORITY"
    assert model.calls == ["checklist", "investigate", "investigate"]


def test_resume_after_answers_converges_to_verified_with_few_calls(client, model):
    matter_id = create(client)["matter_id"]
    run(client, matter_id)
    supplied = answer(client, matter_id)
    assert supplied["state"] == "INVESTIGATING" and supplied["missing_inputs"] == []

    done = run(client, matter_id)
    assert done["state"] == "VERIFIED"
    assert done["draft"]["status"] == "UNVERIFIED"  # the draft itself is never relabelled
    # VERIFIED is an assessment outcome, never a permit.
    assert done["assessment_status"] == "verified_assessment"
    assert done["authority_approval"] == "not_obtained"
    assert "not a permit" in done["outcome_note"] and "Conditions remain" in done["outcome_note"]
    assert done["draft"]["conclusion"]["answer"] == "conditional"
    assert [c["item_key"] for c in done["draft"]["conditions"]] == ["planning_constraints", "required_documents"]
    # Resume reused the checklist and the tool loop's evidence: one planner call, one tool loop, one draft, one review.
    assert model.calls == ["checklist", "investigate", "investigate", "draft", "verification"]
    assert done["rounds"] == 2
    items = checklist(client, matter_id)
    assert {k for k, i in items.items() if i["status"] == "satisfied"} == {
        "jurisdiction", "competent_authority", "current_licensed_use", "intended_use", "ownership_status",
        "unit_conversion", "licensing_procedure", "habitability",
    }


def test_converges_to_escalate_when_the_model_reviewer_escalates():
    model = ScriptedModel(verification=lambda p: {
        "outcome": "ESCALATE", "conclusion_follows": True, "issues": [], "suggested_follow_up": [],
        "summary": "Needs an architect's assessment."})
    with make_client(model) as client:
        matter_id = create(client)["matter_id"]
        run(client, matter_id)
        answer(client, matter_id)
        final = run(client, matter_id)
    assert final["state"] == "ESCALATE"
    assert "planning_constraints" in final["unresolved_items"]


def test_converges_to_rejected_after_one_revision():
    def overclaiming(payload):
        draft = default_draft(payload)
        draft["claims"].append({"text": "The conversion is definitely allowed.", "evidence_ids": []})
        return draft

    model = ScriptedModel(draft=overclaiming)
    with make_client(model) as client:
        matter_id = create(client)["matter_id"]
        run(client, matter_id)
        answer(client, matter_id)
        final = run(client, matter_id)
        report = client.get(f"/api/permit/matters/{matter_id}/verification").json()
    assert final["state"] == "REJECTED" and final["revision"] == 1
    assert report["outcome"] == "REJECTED"
    assert any(i["code"] == "unsupported_claim" for i in report["issues"])
    assert "verification" not in model.calls  # the model reviewer never saw a rule-failing draft
    assert model.calls.count("draft") == 2  # original + one revision, then it stops


def test_revision_can_recover_to_verified():
    reviews = iter([
        {"outcome": "REJECTED", "conclusion_follows": False, "suggested_follow_up": [], "summary": "Overstated.",
         "issues": [{"code": "overstated_claim", "message": "Too strong.", "claim_id": "K2"}]},
        {"outcome": "VERIFIED", "conclusion_follows": True, "issues": [], "suggested_follow_up": [], "summary": "Proportionate."},
    ])
    model = ScriptedModel(verification=lambda payload: next(reviews))
    with make_client(model) as client:
        matter_id = create(client)["matter_id"]
        run(client, matter_id)
        answer(client, matter_id)
        final = run(client, matter_id)
    assert final["state"] == "VERIFIED" and final["revision"] == 1
    assert model.calls.count("investigate") == 2  # the revision didn't re-run the tool loop


def test_definitive_answer_despite_conditions_is_rejected():
    def definitive(payload):
        draft = default_draft(payload)
        draft["conclusion"]["answer"] = "likely_possible"
        return draft

    with make_client(ScriptedModel(draft=definitive)) as client:
        matter_id = create(client)["matter_id"]
        run(client, matter_id)
        answer(client, matter_id)
        final = run(client, matter_id)
        report = client.get(f"/api/permit/matters/{matter_id}/verification").json()
    assert final["state"] == "REJECTED"
    assert any(i["code"] == "definitive_with_conditions" for i in report["issues"])


# --- boundedness ------------------------------------------------------------------------


def test_a_model_that_keeps_asking_cannot_create_new_or_foreign_questions(client, model):
    def pushy(round_no, messages):
        return [ToolCall(f"c{round_no}", "request_missing_information", {"items": [
            {"item_key": "pdm_parcel_check", "question": "Did the Câmara confirm the PDM?", "reason": "r", "owner": "USER"},
            {"item_key": "planning_constraints", "question": "Do you have municipal confirmation?", "reason": "r", "owner": "USER"},
            {"item_key": "current_licensed_use", "question": "Licensed use?", "reason": "r", "owner": "USER"},
            {"item_key": "current_licensed_use", "question": "Licensed use, again?", "reason": "r", "owner": "USER"},
        ]})]

    model.investigation = pushy
    matter_id = create(client)["matter_id"]
    paused = run(client, matter_id)
    assert [m["input_key"] for m in paused["missing_inputs"]] == list(USER_KEYS)  # canonical keys only
    assert model.calls.count("investigate") == 2  # the tool loop is bounded
    answer(client, matter_id)
    done = run(client, matter_id)
    assert done["state"] == "VERIFIED"
    assert model.calls.count("investigate") == 2  # and not repeated on resume


def test_rounds_are_bounded_even_if_state_keeps_reopening(client, model):
    matter_id = create(client)["matter_id"]
    run(client, matter_id)
    answer(client, matter_id)
    repo = client.app.state.permit_workflow._repo
    import asyncio

    matter = asyncio.run(repo.get_matter(matter_id))
    matter.rounds = MAX_ROUNDS  # as if it had already looped
    asyncio.run(repo.save_matter(matter))
    final = run(client, matter_id)
    assert final["state"] == "ESCALATE"
    assert "round limit" in final["escalation_reason"]
    assert final["unresolved_items"]


def test_missing_system_evidence_escalates_with_the_gap():
    from app.services.permit.sources import portugal

    with make_client(ScriptedModel(investigation=lambda r, m: [])) as client:
        registry = client.app.state.permit_workflow._sources
        registry.providers = [type("NoCivilCode", (), {"sources": lambda self: (portugal.RJUE, portugal.RGEU, portugal.PDM_CASCAIS)})()]
        matter_id = create(client)["matter_id"]
        run(client, matter_id)
        answer(client, matter_id)
        final = run(client, matter_id)
    assert final["state"] == "ESCALATE"
    assert "unit_conversion" in final["escalation_reason"]
    assert "unit_conversion" in final["unresolved_items"]


def test_continue_on_a_converged_matter_is_a_no_op(client, model):
    matter_id = create(client)["matter_id"]
    run(client, matter_id)
    answer(client, matter_id)
    run(client, matter_id)
    calls = list(model.calls)
    again = run(client, matter_id)
    assert again["state"] == "VERIFIED" and model.calls == calls


# --- contracts --------------------------------------------------------------------------


def test_unknown_planner_keys_are_rejected_and_never_persisted():
    model = ScriptedModel(checklist=lambda p: {
        "intent": "unit_conversion", "intent_summary": "s",
        "questions": [{"key": "made_up_requirement", "question": "Invented?"},
                      {"key": "intended_use", "question": "Describe the two units."}]})
    with make_client(model) as client:
        matter_id = create(client)["matter_id"]
        run(client, matter_id)
        items = checklist(client, matter_id)
    assert "made_up_requirement" not in items
    assert set(items) == {"jurisdiction", "competent_authority", "current_licensed_use", "intended_use", "ownership_status",
                          "unit_conversion", "licensing_procedure", "habitability", "planning_constraints", "required_documents"}
    assert items["intended_use"]["question"] == "Describe the two units."


def test_verifier_suggestions_do_not_change_the_checklist():
    model = ScriptedModel(verification=lambda p: {
        "outcome": "VERIFIED", "conclusion_follows": True, "issues": [], "summary": "ok",
        "suggested_follow_up": [{"area": "restrictions", "text": "Check acoustic insulation between units."}]})
    with make_client(model) as client:
        matter_id = create(client)["matter_id"]
        run(client, matter_id)
        answer(client, matter_id)
        before = client.get(f"/api/permit/matters/{matter_id}/checklist").json()["items"]
        run(client, matter_id)
        after = client.get(f"/api/permit/matters/{matter_id}/checklist").json()["items"]
        report = client.get(f"/api/permit/matters/{matter_id}/verification").json()
    assert [i["key"] for i in after] == [i["key"] for i in before]
    assert report["suggested_follow_up"] == [{"area": "restrictions", "text": "Check acoustic insulation between units."}]
    assert "planning_constraints" in report["unresolved"]


def test_evidence_is_persisted_linked_and_never_duplicated(client):
    matter_id = create(client)["matter_id"]
    run(client, matter_id)
    before = client.get(f"/api/permit/matters/{matter_id}/evidence").json()
    answer(client, matter_id)
    run(client, matter_id)
    after = client.get(f"/api/permit/matters/{matter_id}/evidence").json()
    matter = client.get(f"/api/permit/matters/{matter_id}").json()

    assert [e["evidence_id"] for e in after][: len(before)] == [e["evidence_id"] for e in before]
    assert len(after) == len(before) + len(ANSWERS)
    ids = {e["evidence_id"] for e in after}
    assert {eid for c in matter["draft"]["claims"] for eid in c["evidence_ids"]} <= ids
    regulatory = [e for e in after if e["source_type"] == "regulatory_source"]
    assert all(e["verification_status"] == "curated_reference" for e in regulatory)
    assert {e["jurisdiction_id"] for e in regulatory} <= {"pt", "pt/lisboa/cascais"}
    assert {e["verification_status"] for e in after if e["source_type"] == "user_statement"} == {"user_declared"}


def test_tool_results_come_from_habita_not_the_model(client, model):
    def sneaky(round_no, messages):
        if round_no == 0:
            return [ToolCall("x1", "invent_fact", {"fact": "zoning allows 10 units"}),
                    ToolCall("x2", "search_regulatory_sources", {"topics": ["not_a_topic"], "query": "q"})]
        return []

    model.investigation = sneaky
    matter_id = create(client)["matter_id"]
    run(client, matter_id)
    evidence = client.get(f"/api/permit/matters/{matter_id}/evidence").json()
    assert not any("10 units" in e["excerpt"] for e in evidence)
    # HABITA's own deterministic retrieval still found the sources the checklist needs.
    assert any(e["source_type"] == "regulatory_source" for e in evidence)


# --- failures and scope -----------------------------------------------------------------


def test_model_failure_marks_failed_and_continue_resumes_from_that_step():
    failures = {"left": 1}

    def flaky_draft(payload):
        if failures["left"]:
            failures["left"] -= 1
            raise UpstreamServiceError("The reasoning service is temporarily unavailable. Please try again.")
        return default_draft(payload)

    model = ScriptedModel(draft=flaky_draft)
    with make_client(model) as client:
        matter_id = create(client)["matter_id"]
        run(client, matter_id)
        answer(client, matter_id)
        failed = run(client, matter_id)
        assert failed["state"] == "FAILED"
        assert failed["error"]["code"] == "upstream_error" and failed["error"]["failed_state"] == "INVESTIGATING"
        resumed = run(client, matter_id)
    assert resumed["state"] == "VERIFIED" and resumed["error"] is None
    assert model.calls.count("checklist") == 1


def test_invalid_model_output_fails_safely():
    model = ScriptedModel(draft=lambda payload: {"conclusion": "yes"})
    with make_client(model) as client:
        matter_id = create(client)["matter_id"]
        run(client, matter_id)
        answer(client, matter_id)
        failed = run(client, matter_id)
    assert failed["state"] == "FAILED" and failed["error"]["code"] == "invalid_model_output"


def test_out_of_scope_goal_escalates_without_investigation():
    model = ScriptedModel(checklist=lambda p: {"intent": "out_of_scope", "intent_summary": "Tax advice.", "questions": []})
    with make_client(model) as client:
        final = run(client, create(client, "How much tax will I pay when I sell?")["matter_id"])
    assert final["state"] == "ESCALATE"
    assert "investigate" not in model.calls


def test_matter_for_unmodelled_country_escalates_without_model_calls():
    model = ScriptedModel()
    with make_client(model) as client:
        prop = client.post("/api/property/resolve-location", json={"address": "1600 Amphitheatre Pkwy, Mountain View"}).json()
        created = client.post("/api/permit/matters", json={"property_id": prop["property_id"], "question": CONVERSION_QUESTION}).json()
        client.headers["Authorization"] = f"Bearer {created['access_token']}"
        final = run(client, created["matter"]["matter_id"])
    assert final["state"] == "ESCALATE"
    assert "no regulatory sources" in final["escalation_reason"]
    assert model.calls == []


def test_general_overview_needs_no_user_questions():
    model = ScriptedModel(checklist=lambda p: {"intent": "general_overview", "intent_summary": "Orientation.", "questions": []},
                          investigation=lambda r, m: [])
    with make_client(model) as client:
        final = run(client, create(client, "What can I do with this property?")["matter_id"])
    assert final["state"] == "VERIFIED"
    assert model.calls == ["checklist", "investigate", "draft", "verification"]


def test_default_investigation_is_used(model):
    assert model.investigation is default_investigation



def test_model_materiality_labels_are_ignored_when_drafting():
    """A drafter returning material=false on an uncited claim cannot get it past verification."""

    def sneaky_draft(payload):
        draft = default_draft(payload)
        draft["claims"].append({"text": "The Câmara has already approved this.", "material": False, "evidence_ids": []})
        return draft

    model = ScriptedModel(draft=sneaky_draft)
    with make_client(model) as client:
        matter_id = create(client)["matter_id"]
        run(client, matter_id)
        answer(client, matter_id)
        final = run(client, matter_id)
    assert final["state"] == "REJECTED"
    assert all(c["material"] for c in final["draft"]["claims"])
