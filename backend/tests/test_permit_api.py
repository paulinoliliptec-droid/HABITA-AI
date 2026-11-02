"""Permit API: schemas, structured errors and tool contracts."""

import json
import pytest

from app.services.permit.sources.base import SourceRegistry
from app.services.permit.sources.portugal import PortugalSources
from app.services.permit.tools import TOOL_SPECS
from tests.permit_fakes import ANSWERS, CONVERSION_QUESTION, ScriptedModel, make_client, resolve_cascais


def new_matter(c, question: str = CONVERSION_QUESTION) -> str:
    created = c.post("/api/permit/matters", json={"property_id": resolve_cascais(c), "question": question}).json()
    c.headers["Authorization"] = f"Bearer {created['access_token']}"
    return created["matter"]["matter_id"]


@pytest.fixture
def client():
    with make_client(ScriptedModel()) as c:
        yield c


def test_status_reports_configuration():
    with make_client(ScriptedModel()) as c:
        assert c.get("/api/permit/status").json() == {"available": True, "model": "muse-spark-1.3"}
    with make_client(None, meta_api_key=None) as c:
        assert c.get("/api/permit/status").json()["available"] is False


def test_unconfigured_meta_returns_503_and_leaves_the_matter_resumable():
    with make_client(None, meta_api_key=None) as c:
        mid = new_matter(c)
        res = c.post(f"/api/permit/matters/{mid}/continue")
        assert res.status_code == 503 and res.json()["error"]["code"] == "service_not_configured"
        assert c.get(f"/api/permit/matters/{mid}").json()["state"] == "PLANNING"


@pytest.mark.parametrize(
    "body",
    [{}, {"property_id": "prp_x", "question": CONVERSION_QUESTION}, {"property_id": "prp_0000000000000000", "question": "short"}],
)
def test_create_validation(client, body):
    res = client.post("/api/permit/matters", json=body)
    assert res.status_code == 422 and res.json()["error"]["code"] == "validation_error"


def test_create_for_unknown_property_is_404(client):
    res = client.post("/api/permit/matters", json={"property_id": "prp_0000000000000000", "question": CONVERSION_QUESTION})
    assert res.status_code == 404 and res.json()["error"]["code"] == "not_found"


def test_reads_before_work_and_unknown_matters(client):
    mid = new_matter(client)
    assert client.get(f"/api/permit/matters/{mid}/checklist").status_code == 404
    assert client.get(f"/api/permit/matters/{mid}/verification").status_code == 404
    assert client.get(f"/api/permit/matters/{mid}/evidence").json() == []
    assert client.get("/api/permit/matters/pm_0000000000000000").status_code == 403  # indistinguishable from a wrong token
    assert client.get("/api/permit/matters/not-an-id").status_code == 422


def test_inputs_are_only_accepted_when_requested(client):
    mid = new_matter(client)
    early = client.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": {"current_licensed_use": "dwelling"}})
    assert early.status_code == 409 and early.json()["error"]["code"] == "conflict"

    client.post(f"/api/permit/matters/{mid}/continue")
    unknown = client.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": {"zoning_hack": "allowed"}})
    assert unknown.status_code == 409 and "Unexpected information" in unknown.json()["error"]["message"]
    empty = client.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": {"current_licensed_use": "  "}})
    assert empty.status_code == 422


def test_partial_answers_keep_waiting_for_the_rest(client):
    mid = new_matter(client)
    client.post(f"/api/permit/matters/{mid}/continue")
    partial = client.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": {"current_licensed_use": "dwelling"}}).json()
    assert partial["state"] == "NEEDS_INPUT"
    assert [m["input_key"] for m in partial["missing_inputs"]] == ["intended_use", "ownership_status"]


def test_concurrent_continue_is_refused_while_leased(client):
    mid = new_matter(client)
    repo = client.app.state.permit_workflow._repo
    import asyncio
    asyncio.run(repo.acquire(mid))
    res = client.post(f"/api/permit/matters/{mid}/continue")
    assert res.status_code == 409


def test_continue_is_rate_limited():
    with make_client(ScriptedModel(), permit_rate_per_minute=1, permit_burst=1) as c:
        mid = new_matter(c)
        c.post(f"/api/permit/matters/{mid}/continue")
        assert c.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": ANSWERS}).status_code == 200
        limited = c.post(f"/api/permit/matters/{mid}/continue")
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"


# --- tool and source contracts ------------------------------------------------------


def test_tool_specs_follow_the_meta_function_contract():
    names = [t["function"]["name"] for t in TOOL_SPECS]
    assert names == ["get_property_context", "get_jurisdiction_context", "get_competent_authority",
                     "get_available_evidence", "get_planning_context", "search_regulatory_sources",
                     "request_missing_information"]
    # No tool accepts a URL, and none can change a source's trust status (HR-003).
    for spec in TOOL_SPECS:
        assert "url" not in json.dumps(spec["function"]["parameters"]).lower()
        assert "status" not in spec["function"]["parameters"]["properties"]
    for spec in TOOL_SPECS:
        params = spec["function"]["parameters"]
        assert spec["type"] == "function" and params["type"] == "object"
        assert params["additionalProperties"] is False and set(params["required"]) <= set(params["properties"])


def test_sources_are_filtered_by_jurisdiction_chain():
    registry = SourceRegistry([PortugalSources()])
    cascais = registry.search(["pt", "pt/lisboa", "pt/lisboa/cascais"], ["land_use_planning"])
    porto = registry.search(["pt", "pt/porto", "pt/porto/porto"], ["land_use_planning"])
    assert {h.source.source_id for h in cascais} == {"cascais-pdm"}
    assert porto == []  # Cascais's PDM never applies elsewhere
    assert registry.covers(["pt", "pt/porto"]) and not registry.covers(["us", "us/california"])
    for hit in registry.search(["pt", "pt/lisboa", "pt/lisboa/cascais"], ["unit_division"]):
        assert hit.source.authoritative and hit.source.retrieval == "curated_reference" and hit.source.reviewed_on


# --- TD-061: typed, contextual answers ------------------------------------------------------------------------------

@pytest.mark.parametrize("key,answer", [
    ("intended_use", "yes"), ("intended_use", "areas"), ("intended_use", "ok"), ("intended_use", "Sim"),
    ("intended_use", "two flats"),  # no floors, no areas, no entrances
    ("intended_use", "Two flats, one per floor, each with its own street door."),  # no area
    ("intended_use", "Two flats of about 60 m2 each, one per floor."),  # no entrance
    ("current_licensed_use", "yes"), ("current_licensed_use", "não sei"), ("current_licensed_use", "ok"),
    ("ownership_status", "yes"), ("ownership_status", "?"),
])
def test_td061_a_non_answer_to_a_structural_question_is_refused_and_asked_again(client, key, answer):
    """TD-061: 'yes', 'areas', 'ok' or a layout without floors/areas/entrances does not close the question."""
    mid = new_matter(client)
    client.post(f"/api/permit/matters/{mid}/continue")
    res = client.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": {key: answer}})
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "input_incomplete"
    assert answer.lower() not in res.json()["error"]["message"].lower() or len(answer) < 3  # never echoes the answer
    matter = client.get(f"/api/permit/matters/{mid}").json()
    assert matter["state"] == "NEEDS_INPUT" and key in [m["input_key"] for m in matter["missing_inputs"]]
    assert key not in matter["inputs"]
    assert not [e for e in client.get(f"/api/permit/matters/{mid}/evidence").json()
                if e["source_type"] == "user_statement"]  # nothing recorded


def test_td061_one_incomplete_answer_refuses_the_whole_submission(client):
    """No partial write: a valid answer submitted with an incomplete one is not recorded either."""
    mid = new_matter(client)
    client.post(f"/api/permit/matters/{mid}/continue")
    res = client.post(f"/api/permit/matters/{mid}/inputs",
                      json={"inputs": {"current_licensed_use": "dwelling", "intended_use": "yes"}})
    assert res.status_code == 409
    assert client.get(f"/api/permit/matters/{mid}").json()["inputs"] == {}


def test_td061_complete_typed_answers_are_recorded_as_user_declarations(client):
    mid = new_matter(client)
    client.post(f"/api/permit/matters/{mid}/continue")
    res = client.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": {
        "current_licensed_use": "Habitação: uma moradia",
        "intended_use": "Dois apartamentos, um por piso, cerca de 60 m² cada, cada um com entrada própria da rua.",
        "ownership_status": "Um único proprietário, sem frações."}})
    assert res.status_code == 200, res.text
    declared = [e for e in client.get(f"/api/permit/matters/{mid}/evidence").json()
                if e["source_type"] == "user_statement"]
    assert len(declared) == 3 and all(e["verification_status"] == "user_declared" for e in declared)


def test_td061_every_clarifying_message_has_a_portuguese_text():
    import json
    from pathlib import Path

    from app.services.permit.answers import MESSAGES
    pt = json.loads((Path(__file__).parents[2] / "frontend" / "src" / "i18n" / "pt.json").read_text(encoding="utf-8"))
    assert [m for m in MESSAGES if not pt.get(m)] == []


@pytest.mark.parametrize("answer", [
    "2 floors, 60 m2, entrance unknown",  # an unknown part
    "2 floors 60 m2 entrance",  # no area per unit, no way in
    "Two flats, one per floor, 60 m2, own street doors",  # 60 m2 total or each?
    "Dois apartamentos, um por piso, 60 m² cada, entrada a definir",
])
def test_td061_r4_a_layout_with_an_unknown_or_ambiguous_part_is_refused(client, answer):
    """TD-061 (Codex 2026-11-02, P1): partial layouts passed the shape check."""
    mid = new_matter(client)
    client.post(f"/api/permit/matters/{mid}/continue")
    res = client.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": {"intended_use": answer}})
    assert res.status_code == 409 and res.json()["error"]["code"] == "input_incomplete"


def test_td061_r5_an_unrelated_descriptor_does_not_describe_the_entrance(client):
    """TD-061 review round 5 (Codex 2026-11-02, P1). Fixed after the last round: not re-reviewed."""
    mid = new_matter(client)
    client.post(f"/api/permit/matters/{mid}/continue")
    res = client.post(f"/api/permit/matters/{mid}/inputs",
                      json={"inputs": {"intended_use": "2 floors, 60 m2 each, private garden, entrance"}})
    assert res.status_code == 409 and res.json()["error"]["code"] == "input_incomplete"


@pytest.mark.parametrize("key,answer", [
    ("current_licensed_use", "I don't know if it is housing"),
    ("ownership_status", "I don't know who the owner is"),
    ("ownership_status", "Não sei quem é o proprietário"),
])
def test_td061_final_r1_an_answer_that_says_it_does_not_know_is_refused(client, key, answer):
    """TD-061 final review r1 (Codex 2026-11-02, P1)."""
    mid = new_matter(client)
    client.post(f"/api/permit/matters/{mid}/continue")
    res = client.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": {key: answer}})
    assert res.status_code == 409 and res.json()["error"]["code"] == "input_incomplete"


@pytest.mark.parametrize("key,answer", [
    ("intended_use", "Two floors; 60 m2 total for both flats, 40 m2 garden, each with an own street door"),
    ("current_licensed_use", "I don't really know if it is housing"),
])
def test_td061_final_r2_totals_gardens_and_hedged_unknowns_are_refused(client, key, answer):
    """TD-061 final review r2 (Codex 2026-11-02, P1)."""
    mid = new_matter(client)
    client.post(f"/api/permit/matters/{mid}/continue")
    res = client.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": {key: answer}})
    assert res.status_code == 409 and res.json()["error"]["code"] == "input_incomplete"


@pytest.mark.parametrize("key,answer", [
    ("current_licensed_use", "Não tenho a certeza se é habitação"),
    ("ownership_status", "Não tenho a certeza se sou o proprietário"),
])
def test_td061_final_r3_portuguese_hedges_are_unknowns(client, key, answer):
    """TD-061 final review r3 (Codex 2026-11-02, P1)."""
    mid = new_matter(client)
    client.post(f"/api/permit/matters/{mid}/continue")
    res = client.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": {key: answer}})
    assert res.status_code == 409 and res.json()["error"]["code"] == "input_incomplete"
