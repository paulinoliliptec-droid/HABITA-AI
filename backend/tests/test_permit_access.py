"""Permit matter access control (Codex CX-1): the property is public, its matters are not."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.services.permit.repository import hash_token
from tests.permit_fakes import ANSWERS, CONVERSION_QUESTION, ScriptedModel, make_client, resolve_cascais


@pytest.fixture
def app_client():
    with make_client(ScriptedModel()) as c:
        yield c


def visitor(app_client: TestClient) -> TestClient:
    """A second browser against the same backend: no shared headers or cookies."""
    other = TestClient(app_client.app)
    other.headers.pop("Authorization", None)
    return other


def create(c: TestClient) -> tuple[str, str, str]:
    pid = resolve_cascais(c)
    created = c.post("/api/permit/matters", json={"property_id": pid, "question": CONVERSION_QUESTION}).json()
    return pid, created["matter"]["matter_id"], created["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def owned_matter(app_client):
    """Matter A, created and answered by its owner, so it holds private answers."""
    pid, mid, token = create(app_client)
    assert app_client.post(f"/api/permit/matters/{mid}/continue", headers=auth(token)).json()["state"] == "NEEDS_INPUT"
    assert app_client.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": ANSWERS}, headers=auth(token)).status_code == 200
    return pid, mid, token


PRIVATE_READS = ["", "/checklist", "/evidence", "/verification"]


def test_property_id_alone_cannot_list_or_read_matters(app_client, owned_matter):
    pid, mid, _ = owned_matter
    stranger = visitor(app_client)
    # There is no lookup of matters by property ID.
    assert stranger.get(f"/api/permit/matters?property_id={pid}").status_code in (404, 405)
    for path in PRIVATE_READS:
        res = stranger.get(f"/api/permit/matters/{mid}{path}")
        assert res.status_code == 401, path
        assert res.json()["error"]["code"] == "unauthorized"


def test_property_id_alone_cannot_read_user_answers(app_client, owned_matter):
    _, mid, _ = owned_matter
    stranger = visitor(app_client)
    for path in PRIVATE_READS:
        body = stranger.get(f"/api/permit/matters/{mid}{path}").text
        assert not any(answer in body for answer in ANSWERS.values()), path


def test_property_id_alone_cannot_supply_information_or_advance(app_client):
    _, mid, token = create(app_client)
    app_client.post(f"/api/permit/matters/{mid}/continue", headers=auth(token))
    stranger = visitor(app_client)
    assert stranger.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": ANSWERS}).status_code == 401
    assert stranger.post(f"/api/permit/matters/{mid}/continue").status_code == 401
    # The owner's matter is untouched.
    owner_view = app_client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
    assert owner_view["state"] == "NEEDS_INPUT" and owner_view["inputs"] == {}


@pytest.mark.parametrize("header", ["Bearer wrong-token", "Bearer ", "Basic abc", "wrong-token"])
def test_wrong_or_malformed_capability_is_rejected_without_revealing_existence(app_client, owned_matter, header):
    _, mid, _ = owned_matter
    stranger = visitor(app_client)
    real = stranger.get(f"/api/permit/matters/{mid}", headers={"Authorization": header})
    missing = stranger.get("/api/permit/matters/pm_0000000000000000", headers={"Authorization": header})
    assert real.status_code in (401, 403)
    # A wrong token on a real matter looks exactly like any token on a matter that doesn't exist.
    assert (real.status_code, real.json()) == (missing.status_code, missing.json())


def test_correct_capability_resumes_its_own_matter(app_client, owned_matter):
    _, mid, token = owned_matter
    resumed = visitor(app_client)  # e.g. after a reload: only the stored token
    final = resumed.post(f"/api/permit/matters/{mid}/continue", headers=auth(token)).json()
    assert final["state"] == "VERIFIED"
    assert resumed.get(f"/api/permit/matters/{mid}/verification", headers=auth(token)).status_code == 200


def test_capability_for_one_matter_cannot_access_another(app_client):
    _, mid_a, token_a = create(app_client)
    _, mid_b, token_b = create(app_client)
    assert app_client.get(f"/api/permit/matters/{mid_b}", headers=auth(token_a)).status_code == 403
    assert app_client.post(f"/api/permit/matters/{mid_b}/continue", headers=auth(token_a)).status_code == 403
    assert app_client.get(f"/api/permit/matters/{mid_a}", headers=auth(token_b)).status_code == 403


def test_creating_a_second_matter_for_the_same_property_does_not_expose_the_first(app_client, owned_matter):
    pid, mid_a, _ = owned_matter
    stranger = visitor(app_client)
    created = stranger.post("/api/permit/matters", json={"property_id": pid, "question": CONVERSION_QUESTION})
    assert created.status_code == 201
    body = created.json()
    assert body["matter"]["matter_id"] != mid_a
    assert body["matter"]["inputs"] == {}
    assert mid_a not in created.text
    assert stranger.get(f"/api/permit/matters/{mid_a}", headers=auth(body["access_token"])).status_code == 403


def test_public_property_experience_still_works(app_client, owned_matter):
    pid, _, _ = owned_matter
    stranger = visitor(app_client)
    prop = stranger.get(f"/api/property/{pid}")
    assert prop.status_code == 200
    assert prop.json()["jurisdiction"]["local_authority"]["name"] == "Câmara Municipal de Cascais"
    assert stranger.get("/api/permit/status").json()["available"] is True
    assert "inputs" not in prop.text and "access" not in prop.text


def test_raw_capability_is_never_persisted_or_logged(app_client, caplog):
    caplog.set_level(logging.DEBUG)
    _, mid, token = create(app_client)
    app_client.post(f"/api/permit/matters/{mid}/continue", headers=auth(token))
    repo = app_client.app.state.permit_workflow._repo
    stored = repo.access_hashes[mid]
    assert stored == hash_token(token) and stored != token
    persisted = repo.matters[mid].model_dump_json() + "".join(e.model_dump_json() for e in repo.evidence.get(mid, []))
    assert token not in persisted and token not in caplog.text
    # The token is never echoed back after creation.
    assert token not in app_client.get(f"/api/permit/matters/{mid}", headers=auth(token)).text
