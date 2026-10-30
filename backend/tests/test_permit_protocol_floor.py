"""MU-9 (M8): the verification protocol floor survives rollback; an unsafe verifier can't commit VERIFIED."""

import pytest

from app.services.permit import verifier as verifier_module
from app.services.permit.protocol import CURRENT, DEFAULT_FLOOR, PROTOCOLS, Floor, FloorError, raise_floor, validator
from app.db.property_repository import InMemoryPropertyRepository
from app.services.permit.repository import InMemoryPermitRepository, ProtocolBelowFloor
from app.services.sources.repository import InMemorySourceRepository
from tests.permit_fakes import ScriptedModel, make_client
from tests.test_permit_commit_durability import IDENT, PIN, coherent, persisted, props, stores, verified
from tests.test_permit_official_sources import auth, ingest_regulamento, run_matter
from tests.test_property_repository import snapshot


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
    repo, sources, properties = InMemoryPermitRepository(), InMemorySourceRepository(), InMemoryPropertyRepository()
    await properties.save(snapshot(), {"ChIJ-a"}, property_id=IDENT.property_id)  # version 0
    m, r = verified()
    old = r.model_copy(update={"protocol": "statement-v1"})
    await repo.create_matter(m.model_copy(update={"state": "VERIFYING"}), "h")
    with pytest.raises(ProtocolBelowFloor):
        await repo.commit_verified(m, old, PIN.__class__({}), sources, IDENT, properties)
    assert repo.verifications == {} and repo.matters[m.matter_id].state == "VERIFYING"
    assert await repo.commit_verified(m, r, PIN.__class__({}), sources, IDENT, properties) is True


@pytest.mark.parametrize("stored_floor", [None, Floor(CURRENT, ("statement-v1",)).to_doc()])
async def test_the_mongo_commit_reads_the_floor_in_its_transaction_and_writes_nothing_below_it(stored_floor):
    """Also without a stored floor: the default is fail-closed."""
    client, permit, src = stores()
    if stored_floor:
        permit._policy.docs["floor"] = stored_floor
    m, r = verified()
    with pytest.raises(ProtocolBelowFloor):
        await permit.commit_verified(m, r.model_copy(update={"protocol": "statement-v1"}), PIN, src, IDENT, props(client))
    matter, reports = persisted(permit)
    assert matter["state"] == "VERIFYING" and reports == {} and coherent(permit) and client.aborts >= 1
    assert await permit.commit_verified(m, r, PIN, src, IDENT, props(client)) is True and coherent(permit)


async def test_a_binary_below_a_raised_floor_cannot_commit():
    """A later floor that no longer admits this binary's protocol (simulated by marking it unsafe) refuses it."""
    client, permit, src = stores()
    permit._policy.docs["floor"] = Floor(CURRENT, ("statement-v1", CURRENT)).to_doc()
    m, r = verified()
    with pytest.raises(ProtocolBelowFloor):
        await permit.commit_verified(m, r, PIN, src, IDENT, props(client))
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


# --- Codex Phase 1 review, F5-F7 (floor installation order, startup validator, superseded matters) -------------------

class _Recorder:
    """A Mongo stand-in that records calls and answers finds from ``docs``."""

    def __init__(self, log, name, docs=()):
        self.log, self.name, self.docs = log, name, list(docs)
        self.database = self
        # permit_verifications as listCollections reports it: exists, no validator yet (None: absent).
        self.collection = {"name": "permit_verifications", "options": {}}

    async def create_index(self, *a, **kw):
        self.log.append((self.name, "create_index"))

    async def list_collections(self, filter=None):
        found = [self.collection] if self.collection else []

        class _Cursor:
            async def to_list(self):
                return found
        return _Cursor()

    async def create_collection(self, name, **kw):
        self.log.append(("db", "create_collection", name, kw["validator"], kw["validationLevel"]))

    async def command(self, name, collection, **kw):
        self.log.append(("db", name, collection, kw["validator"], kw["validationLevel"]))

    async def find_one(self, flt, *a, **kw):
        self.log.append((self.name, "find_one", flt))
        return None

    async def insert_one(self, doc, **kw):
        self.log.append((self.name, "insert_one", doc["_id"]))

    async def replace_one(self, flt, doc, **kw):
        self.log.append((self.name, "replace_one", flt))

    def find(self, flt, projection=None):
        self.log.append((self.name, "find", flt))

        async def gen():
            for d in self.docs:
                yield d
        return gen()

    async def update_many(self, flt, update, **kw):
        self.log.append((self.name, "update_many", flt, update))
        return type("R", (), {"modified_count": len(flt.get("_id", {}).get("$in", []))})()


def _recording_repo(reports=()):
    from app.services.permit.repository import MongoPermitRepository
    log = []
    repo = MongoPermitRepository.__new__(MongoPermitRepository)
    for attr, name in (("_matters", "matters"), ("_evidence", "evidence"), ("_verifications", "verifications"),
                       ("_policy", "policy"), ("_checklists", "checklists")):
        setattr(repo, attr, _Recorder(log, name, reports if name == "verifications" else ()))
    return repo, log


async def test_every_deployment_installs_the_validator_at_startup():
    repo, log = _recording_repo()
    await repo.ensure_indexes()
    installs = [entry for entry in log if entry[0] == "db" and entry[1] == "collMod"]
    assert installs and installs[0][3] == validator(DEFAULT_FLOOR) and installs[0][4] == "moderate"


def _installed(rule):
    return {"name": "permit_verifications",
            "options": {"validator": rule, "validationLevel": "moderate", "validationAction": "error"}}


async def test_a_new_database_gets_the_validator_with_the_collection_before_any_index():
    """Least privilege: creating the collection with its rule needs createCollection only, not collMod; an index
    created first would create the collection without the rule."""
    repo, log = _recording_repo()
    repo._verifications.collection = None
    await repo.ensure_indexes()
    installs = [entry for entry in log if entry[0] == "db"]
    assert [entry[1] for entry in installs] == ["create_collection"]
    assert installs[0][3] == validator(DEFAULT_FLOOR) and installs[0][4] == "moderate"
    assert log.index(installs[0]) < log.index(("verifications", "create_index"))


async def test_an_unchanged_validator_is_not_reinstalled():
    repo, log = _recording_repo()
    repo._verifications.collection = _installed(validator(DEFAULT_FLOOR))
    await repo.ensure_indexes()
    assert not [entry for entry in log if entry[0] == "db"]


async def test_a_changed_or_weaker_validator_is_replaced():
    repo, log = _recording_repo()
    repo._verifications.collection = _installed({"outcome": {"$ne": "VERIFIED"}})  # e.g. tampered or older rule
    await repo.ensure_indexes()
    installs = [entry for entry in log if entry[0] == "db"]
    assert [entry[1] for entry in installs] == ["collMod"] and installs[0][3] == validator(DEFAULT_FLOOR)


async def test_a_collection_created_concurrently_with_the_rule_is_accepted():
    from pymongo.errors import CollectionInvalid

    repo, log = _recording_repo()
    recorder = repo._verifications
    recorder.collection = None

    async def raced(name, **kw):  # the other instance won: the collection now exists with the rule
        recorder.collection = _installed(kw["validator"])
        raise CollectionInvalid("collection permit_verifications already exists")
    recorder.create_collection = raced
    await repo.ensure_indexes()
    assert not [entry for entry in log if entry[0] == "db"]


async def test_raising_the_floor_installs_the_validator_before_storing_the_floor():
    repo, log = _recording_repo()
    new = raise_floor(DEFAULT_FLOOR, CURRENT, "ops", "install")
    assert await repo.raise_floor(DEFAULT_FLOOR, new) is True
    validator_at = next(i for i, entry in enumerate(log) if entry[0] == "db")
    stored_at = next(i for i, entry in enumerate(log) if entry[:2] == ("policy", "insert_one"))
    assert validator_at < stored_at


async def test_superseding_flags_the_reports_and_their_verified_matters_including_null_fields():
    repo, log = _recording_repo([{"_id": "pv_old"}, {"_id": "pv_v1", "protocol": "statement-v1"}])
    assert await repo.flag_superseded(DEFAULT_FLOOR) == 2
    find = next(entry for entry in log if entry[:2] == ("verifications", "find"))
    assert find[2]["superseded_protocol"] is None  # matches a missing field and the null new reports store
    matters = [entry for entry in log if entry[:2] == ("matters", "update_many")]
    assert matters and all(entry[2]["state"] == "VERIFIED" and entry[3] == {"$set": {"superseded_protocol":
                                                                                     "statement-v1"}}
                           for entry in matters)
    assert {i for entry in matters for i in entry[2]["latest_verification_id"]["$in"]} == {"pv_old", "pv_v1"}


async def test_startup_fails_closed_when_the_validator_cannot_be_installed():
    """R3: without the validator a rollback would not be blocked server-side, so the service does not start."""
    from pymongo.errors import OperationFailure

    from app.core.errors import StorageUnavailableError
    repo, log = _recording_repo()

    async def denied(*a, **kw):
        raise OperationFailure("not authorized on habita_ai to execute command { collMod: ... }")
    repo._verifications.command = denied
    with pytest.raises(StorageUnavailableError):
        await repo.ensure_indexes()


def test_a_superseded_verified_matter_is_not_presented_as_verified():
    """R4: the API's own status and note change, not just a stored flag."""
    from tests.test_permit_verifier import matter
    m = matter().model_copy(update={"state": "VERIFIED", "superseded_protocol": "statement-v1"})
    assert m.assessment_status == "superseded_assessment"
    assert m.outcome_note.startswith("Superseded assessment") and "verified again" in m.outcome_note
    assert matter().model_copy(update={"state": "VERIFIED"}).assessment_status == "verified_assessment"


async def test_matters_are_flagged_before_their_reports_so_a_failed_run_can_be_repeated():
    """R5: the reports are what a rerun selects; flagging them last keeps a partial failure repairable."""
    repo, log = _recording_repo([{"_id": "pv_old"}])
    await repo.flag_superseded(DEFAULT_FLOOR)
    order = [entry[0] for entry in log if entry[1] == "update_many"]
    assert order == ["matters", "verifications"]
