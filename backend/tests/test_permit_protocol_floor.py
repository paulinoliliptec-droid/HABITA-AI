"""MU-9 (M8): the verification protocol floor survives rollback; an unsafe verifier can't commit VERIFIED."""

import pytest

from app.services.permit import verifier as verifier_module
from app.services.permit.protocol import CURRENT, DEFAULT_FLOOR, PROTOCOLS, Floor, FloorError, raise_floor, validator
from app.services.permit.repository import InMemoryPermitRepository, ProtocolBelowFloor
from app.services.sources.repository import InMemorySourceRepository
from tests.permit_fakes import ScriptedModel, make_client
from tests.test_permit_commit_durability import PIN, coherent, persisted, stores, verified
from tests.test_permit_official_sources import auth, ingest_regulamento, run_matter


def test_the_floor_only_goes_up_and_never_forgets_an_unsafe_protocol():
    assert DEFAULT_FLOOR.min_protocol == CURRENT and DEFAULT_FLOOR.admitted() == [CURRENT]
    assert "statement-v1" in DEFAULT_FLOOR.known_unsafe
    with pytest.raises(FloorError):
        raise_floor(DEFAULT_FLOOR, "statement-v1", "ops", "rollback")  # lower
    with pytest.raises(FloorError):
        raise_floor(DEFAULT_FLOOR, "atomic-v9", "ops", "typo")  # unknown
    with pytest.raises(FloorError):
        raise_floor(DEFAULT_FLOOR, CURRENT, "", "no operator")
    same = raise_floor(DEFAULT_FLOOR, CURRENT, "ops", "install the MU-9 floor")
    assert same.known_unsafe == DEFAULT_FLOOR.known_unsafe and same.history[-1]["operator"] == "ops"
    with pytest.raises(FloorError):
        raise_floor(same, CURRENT, "ops", "mark the current protocol unsafe", known_unsafe=(CURRENT,))
    assert list(PROTOCOLS).index("statement-v1") < list(PROTOCOLS).index(CURRENT)


async def test_the_in_memory_store_refuses_a_report_below_the_floor():
    repo, sources = InMemoryPermitRepository(), InMemorySourceRepository()
    m, r = verified()
    old = r.model_copy(update={"protocol": "statement-v1"})
    await repo.create_matter(m.model_copy(update={"state": "VERIFYING"}), "h")
    with pytest.raises(ProtocolBelowFloor):
        await repo.commit_verified(m, old, PIN.__class__({}), sources)
    assert repo.verifications == {} and repo.matters[m.matter_id].state == "VERIFYING"
    assert await repo.commit_verified(m, r, PIN.__class__({}), sources) is True


@pytest.mark.parametrize("stored_floor", [None, Floor(CURRENT, ("statement-v1",)).to_doc()])
async def test_the_mongo_commit_reads_the_floor_in_its_transaction_and_writes_nothing_below_it(stored_floor):
    """Also without a stored floor: the default is fail-closed."""
    client, permit, src = stores()
    if stored_floor:
        permit._policy.docs["floor"] = stored_floor
    m, r = verified()
    with pytest.raises(ProtocolBelowFloor):
        await permit.commit_verified(m, r.model_copy(update={"protocol": "statement-v1"}), PIN, src)
    matter, reports = persisted(permit)
    assert matter["state"] == "VERIFYING" and reports == {} and coherent(permit) and client.aborts >= 1
    assert await permit.commit_verified(m, r, PIN, src) is True and coherent(permit)


async def test_a_binary_below_a_raised_floor_cannot_commit():
    """A later floor that no longer admits this binary's protocol (simulated by marking it unsafe) refuses it."""
    client, permit, src = stores()
    permit._policy.docs["floor"] = Floor(CURRENT, ("statement-v1", CURRENT)).to_doc()
    m, r = verified()
    with pytest.raises(ProtocolBelowFloor):
        await permit.commit_verified(m, r, PIN, src)
    assert persisted(permit)[1] == {}


def test_the_validator_admits_verified_only_with_an_admitted_protocol_and_its_atoms():
    rule = validator(DEFAULT_FLOOR)
    verified_branch = rule["$or"][1]
    assert rule["$or"][0] == {"outcome": {"$ne": "VERIFIED"}}  # REJECTED / ESCALATE reports of any code still save
    assert verified_branch == {"protocol": {"$in": [CURRENT]}, "claim_atoms": {"$type": "array"}}
    # A pre-MU-9 VERIFIED document has neither field, so it matches no branch.
    old = {"outcome": "VERIFIED", "issues": [], "checks": {}}
    assert "protocol" not in old and "claim_atoms" not in old


def test_a_rolled_back_verifier_never_persists_verified(monkeypatch):
    """End to end: the deployed code is the pre-MU-9 protocol (statement-v1). The final gate still runs, but the
    commit refuses the report and the matter does not end VERIFIED."""
    monkeypatch.setattr(verifier_module, "PROTOCOL", "statement-v1")
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        mid, token = run_matter(client)
        state = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()["state"]
    assert state != "VERIFIED"


def test_the_current_verifier_still_reaches_verified_end_to_end():
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        mid, token = run_matter(client)
        state = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()["state"]
        report = client.get(f"/api/permit/matters/{mid}/verification", headers=auth(token)).json()
    assert state == "VERIFIED" and report["protocol"] == CURRENT and isinstance(report["claim_atoms"], list)
