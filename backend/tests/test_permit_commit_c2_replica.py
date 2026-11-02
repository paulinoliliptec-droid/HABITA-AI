"""TD-001 adversarial C2 run (HR-003): the VERIFIED commit transaction against a real MongoDB replica set.

Opt-in and local only. Set ``HABITA_REPLICA_TEST_URI`` to a throwaway replica set on this machine, for example
``docker run -d --rm --name habita-rs -p 127.0.0.1:27099:27017 mongo:8.0 --replSet rs0 --bind_ip_all`` then
``docker exec habita-rs mongosh --quiet --eval "rs.initiate()"`` and
``HABITA_REPLICA_TEST_URI='mongodb://127.0.0.1:27099/?replicaSet=rs0&directConnection=true'``.

The URI must point to localhost: this test never runs against Atlas or any shared database (the Atlas run stays in
``test_permit_commit_atlas.py``, behind the owner's authorisation). Every scenario uses its own database, dropped at
the end. Each scenario states the attack, and checks that nothing VERIFIED and nothing partial was written."""

import asyncio
import os
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import WriteError

from app.db.property_repository import MongoPropertyRepository, PropertyIdentity
from app.schemas.permit import MatterState, VerificationReport
from app.schemas.sources import StatusChange
from app.services.permit.protocol import CURRENT
from app.services.permit.repository import (
    MatterCommitConflict, MongoPermitRepository, ProtocolBelowFloor, hash_token,
)
from app.services.sources.catalog import ALL_SOURCES
from app.services.sources.registry import TrustPin
from app.services.sources.repository import MongoSourceRepository
from tests.test_permit_verifier import matter as make_matter

URI = os.getenv("HABITA_REPLICA_TEST_URI", "")


def _local(uri: str) -> bool:
    try:
        host = urlparse(uri).hostname
    except ValueError:
        return False
    return uri.startswith("mongodb://") and host in {"127.0.0.1", "localhost"}


pytestmark = pytest.mark.skipif(not _local(URI), reason="local replica-set test: set HABITA_REPLICA_TEST_URI to a "
                                                        "throwaway replica set on 127.0.0.1")

RESULTS: list[str] = []


class World:
    """A throwaway database with two properties, two trusted sources and helpers to build gate/commit pairs."""

    def __init__(self, client: AsyncMongoClient, name: str) -> None:
        self.client, self.name, self.db = client, name, client[name]
        self.permit = MongoPermitRepository(client, name)
        self.src = MongoSourceRepository(client, name)
        self.props = MongoPropertyRepository(client, name)
        self.tag = secrets.token_hex(3)
        self.s1, self.s2 = f"c2-{self.tag}-a", f"c2-{self.tag}-b"
        self.pa, self.pb = f"prop-a-{self.tag}", f"prop-b-{self.tag}"

    async def setup(self) -> None:
        await self.permit.ensure_indexes()  # installs the MU-9 server validator at the default floor
        for pid in (self.pa, self.pb):
            await self.db["properties"].insert_one({"_id": pid, "identity_version": 0, "snapshot_state": "current",
                                                    "place_ids": [f"place-{pid}"]})
        for sid in (self.s1, self.s2):
            await self.src.insert_source(ALL_SOURCES[0].model_copy(update={
                "source_id": sid, "jurisdiction_id": f"test/c2-{self.tag}", "status": "trusted",
                "status_history": [], "trust_version": 0, "latest_snapshot_id": None}))

    def pin(self) -> TrustPin:
        return TrustPin({self.s1: ("trusted", 0), self.s2: ("trusted", 0)})

    async def matter(self, mid: str, property_id: str):
        m = make_matter().model_copy(update={"matter_id": mid, "property_id": property_id,
                                             "state": MatterState.VERIFYING, "revision": 0})
        await self.permit.create_matter(m, hash_token(f"t-{mid}"))
        return m

    @staticmethod
    def pair(m, rid: str, protocol: str = CURRENT):
        verified = m.model_copy(update={"state": MatterState.VERIFIED, "latest_verification_id": rid})
        report = VerificationReport(verification_id=rid, matter_id=m.matter_id, draft_revision=0, outcome="VERIFIED",
                                    issues=[], checks={"final_gate_passed": True}, created_at=datetime.now(UTC),
                                    protocol=protocol)
        return verified, report

    async def gate_identity(self, pid: str) -> PropertyIdentity | None:
        """What the final gate reads, just before the commit."""
        return await self.props.identity(pid)

    async def nothing_written(self, mid: str) -> bool:
        doc = await self.db["permit_matters"].find_one({"_id": mid})
        reports = await self.db["permit_verifications"].count_documents({"matter_id": mid})
        return (doc is None or doc["state"] == MatterState.VERIFYING.value) and reports == 0

    async def sources_untouched(self) -> bool:
        docs = await self.db["official_sources"].find({"_id": {"$in": [self.s1, self.s2]}}).to_list(None)
        return all("last_verified_commit_at" not in d for d in docs)

    async def verified_count(self) -> int:
        return await self.db["permit_matters"].count_documents({"state": MatterState.VERIFIED.value})


def scenario(fn):
    """Run one scenario in its own throwaway database, always dropped."""
    def run():
        async def go():
            client = AsyncMongoClient(URI, serverSelectionTimeoutMS=5000)
            name = f"habita_c2test_{secrets.token_hex(4)}"
            try:
                world = World(client, name)
                await world.setup()
                await fn(world)
                RESULTS.append(f"{fn.__name__}: PASS")
            finally:
                await client.drop_database(name)
                await client.close()
        asyncio.run(go())
    run.__name__ = fn.__name__
    run.__doc__ = fn.__doc__
    return run


@scenario
async def test_c2_baseline_commit_binds_the_matters_own_property(w: World):
    """Control: unchanged sources and property → exactly one VERIFIED commit, property and sources written."""
    m = await w.matter("pm_base", w.pa)
    vm, vr = w.pair(m, "pv_base")
    assert await w.permit.commit_verified(vm, vr, w.pin(), w.src, await w.gate_identity(w.pa), w.props) is True
    assert await w.verified_count() == 1
    assert (await w.db["properties"].find_one({"_id": w.pa})).get("last_verified_commit_at")
    assert not (await w.db["properties"].find_one({"_id": w.pb})).get("last_verified_commit_at")


@scenario
async def test_c2_identity_of_another_property_is_refused(w: World):
    """Attack: the matter is about property A, the gate hands the identity of property B (wrong parcel)."""
    m = await w.matter("pm_wrong", w.pa)
    vm, vr = w.pair(m, "pv_wrong")
    assert await w.permit.commit_verified(vm, vr, w.pin(), w.src, await w.gate_identity(w.pb), w.props) is False
    assert await w.nothing_written("pm_wrong") and await w.sources_untouched()


@scenario
async def test_c2_two_matters_same_and_different_property(w: World):
    """Two matters: one on A, one on B. Each commits only with its own identity; swapping them commits nothing."""
    ma, mb = await w.matter("pm_a", w.pa), await w.matter("pm_b", w.pb)
    (va, ra), (vb, rb) = w.pair(ma, "pv_a"), w.pair(mb, "pv_b")
    ia, ib = await w.gate_identity(w.pa), await w.gate_identity(w.pb)
    assert await w.permit.commit_verified(va, ra, w.pin(), w.src, ib, w.props) is False
    assert await w.permit.commit_verified(vb, rb, w.pin(), w.src, ia, w.props) is False
    assert await w.verified_count() == 0
    assert await w.permit.commit_verified(va, ra, w.pin(), w.src, ia, w.props) is True
    # A's commit wrote A (no identity bump on a commit), so B still commits with B's identity.
    assert await w.permit.commit_verified(vb, rb, w.pin(), w.src, ib, w.props) is True
    assert await w.verified_count() == 2


@scenario
async def test_c2_property_saved_after_the_gate_is_refused(w: World):
    """Attack: a property refresh (identity_version bump) lands between the gate and the commit."""
    m = await w.matter("pm_saved", w.pa)
    vm, vr = w.pair(m, "pv_saved")
    ident = await w.gate_identity(w.pa)
    await w.db["properties"].update_one({"_id": w.pa}, {"$inc": {"identity_version": 1}})
    assert await w.permit.commit_verified(vm, vr, w.pin(), w.src, ident, w.props) is False
    assert await w.nothing_written("pm_saved") and await w.sources_untouched()


@scenario
async def test_c2_purge_after_the_gate_is_refused(w: World):
    """Attack: the Google-derived snapshot expires and is purged between the gate and the commit (real purge)."""
    m = await w.matter("pm_purge", w.pa)
    vm, vr = w.pair(m, "pv_purge")
    ident = await w.gate_identity(w.pa)
    await w.db["properties"].update_one({"_id": w.pa}, {"$set": {"expires_at": datetime.now(UTC) - timedelta(1)}})
    assert await w.props.purge_expired() == 1
    assert await w.permit.commit_verified(vm, vr, w.pin(), w.src, ident, w.props) is False
    assert await w.gate_identity(w.pa) is None  # a purged property has no identity: the next gate can't bind either
    assert await w.nothing_written("pm_purge")


@scenario
async def test_c2_merge_after_the_gate_is_refused_on_both_sides(w: World):
    """Attack: an operator merges B into A between the gate and the commit (real merge). A matter on A and a matter
    on B, both gated before the merge, must both fail; B no longer has an identity at all."""
    ma, mb = await w.matter("pm_keep", w.pa), await w.matter("pm_dup", w.pb)
    (va, ra), (vb, rb) = w.pair(ma, "pv_keep"), w.pair(mb, "pv_dup")
    ia, ib = await w.gate_identity(w.pa), await w.gate_identity(w.pb)
    await w.props.merge(w.pa, w.pb)
    assert await w.permit.commit_verified(va, ra, w.pin(), w.src, ia, w.props) is False
    assert await w.permit.commit_verified(vb, rb, w.pin(), w.src, ib, w.props) is False
    assert await w.gate_identity(w.pb) is None
    assert await w.verified_count() == 0 and await w.sources_untouched()


@scenario
async def test_c2_merge_in_flight_is_refused(w: World):
    """Attack: a merge half done (A marked as absorbing B, the step-0 write) when the commit runs."""
    m = await w.matter("pm_flight", w.pa)
    vm, vr = w.pair(m, "pv_flight")
    ident = await w.gate_identity(w.pa)
    await w.db["properties"].update_one({"_id": w.pa}, {"$addToSet": {"absorbing": w.pb}})  # identity not bumped
    assert await w.permit.commit_verified(vm, vr, w.pin(), w.src, ident, w.props) is False
    assert await w.gate_identity(w.pa) is None
    assert await w.nothing_written("pm_flight")


@scenario
async def test_c2_source_retired_after_the_gate_is_refused(w: World):
    """Attack: a pinned source is retired (trust_version moves) between the gate and the commit."""
    m = await w.matter("pm_retired", w.pa)
    vm, vr = w.pair(m, "pv_retired")
    ident = await w.gate_identity(w.pa)
    await w.src.set_status(w.s2, StatusChange(status="retired", operator="c2-test", reason="adversarial",
                                              at=datetime.now(UTC)))
    assert await w.permit.commit_verified(vm, vr, w.pin(), w.src, ident, w.props) is False
    assert await w.nothing_written("pm_retired") and await w.sources_untouched()


@scenario
async def test_c2_unsafe_protocol_is_refused_by_the_floor_and_the_server(w: World):
    """Attack: a rolled-back verifier (statement-v1) tries to commit VERIFIED; then writes it directly."""
    m = await w.matter("pm_v1", w.pa)
    vm, vr = w.pair(m, "pv_v1", protocol="statement-v1")
    with pytest.raises(ProtocolBelowFloor):
        await w.permit.commit_verified(vm, vr, w.pin(), w.src, await w.gate_identity(w.pa), w.props)
    assert await w.nothing_written("pm_v1") and await w.sources_untouched()
    with pytest.raises(WriteError):  # the server validator, independent of the application code
        await w.db["permit_verifications"].insert_one({"_id": "pv_raw", "matter_id": "pm_v1", "outcome": "VERIFIED",
                                                       "protocol": "statement-v1", "draft_revision": 0,
                                                       "issues": [], "checks": {}, "claim_atoms": [],
                                                       "created_at": datetime.now(UTC)})


@scenario
async def test_c2_partial_failure_rolls_back_every_write(w: World):
    """Attack: the transaction fails after the source and property writes (report ID already taken). Nothing
    from the failed transaction may remain: no source or property stamp, no VERIFIED matter."""
    m = await w.matter("pm_partial", w.pa)
    vm, vr = w.pair(m, "pv_taken")
    await w.db["permit_verifications"].insert_one({"_id": "pv_taken", "matter_id": "other", "outcome": "REJECTED",
                                                   "draft_revision": 0, "issues": [], "checks": {},
                                                   "created_at": datetime.now(UTC)})
    with pytest.raises(MatterCommitConflict):
        await w.permit.commit_verified(vm, vr, w.pin(), w.src, await w.gate_identity(w.pa), w.props)
    doc = await w.db["permit_matters"].find_one({"_id": "pm_partial"})
    assert doc["state"] == MatterState.VERIFYING.value
    assert await w.sources_untouched()
    assert not (await w.db["properties"].find_one({"_id": w.pa})).get("last_verified_commit_at")


@scenario
async def test_c2_concurrent_commits_of_one_matter_write_one_report(w: World):
    """Race: the same VERIFIED commit retried 8 times concurrently (client retries). One report, one VERIFIED."""
    m = await w.matter("pm_race", w.pa)
    vm, vr = w.pair(m, "pv_race")
    ident = await w.gate_identity(w.pa)
    outcomes = await asyncio.gather(*(w.permit.commit_verified(vm, vr, w.pin(), w.src, ident, w.props)
                                      for _ in range(8)), return_exceptions=True)
    assert await w.db["permit_verifications"].count_documents({"matter_id": "pm_race"}) == 1
    assert await w.verified_count() == 1
    assert any(o is True for o in outcomes)
    assert all(o is True or o is False or isinstance(o, MatterCommitConflict) for o in outcomes), outcomes


@scenario
async def test_c2_commit_racing_a_property_refresh_never_verifies_the_old_identity(w: World):
    """Race: 6 commits (different matters on A, all gated on version 0) run while a refresh bumps A's identity.
    Each commit either serialised before the bump (and then it is valid for version 0) or is refused; after the
    bump, a commit with the version-0 identity is always refused."""
    mats = [await w.matter(f"pm_r{i}", w.pa) for i in range(6)]
    ident = await w.gate_identity(w.pa)

    async def bump():
        await asyncio.sleep(0)
        await w.db["properties"].update_one({"_id": w.pa}, {"$inc": {"identity_version": 1}})

    pairs = [w.pair(m, f"pv_r{i}") for i, m in enumerate(mats)]
    outcomes = (await asyncio.gather(bump(), *(w.permit.commit_verified(vm, vr, w.pin(), w.src, ident, w.props)
                                               for vm, vr in pairs), return_exceptions=True))[1:]
    # Codex TD-003 r2 (P2): the outcomes are checked, not discarded. Each is a commit or a refusal, never an error.
    assert all(o is True or o is False for o in outcomes), outcomes
    committed = sum(o is True for o in outcomes)
    assert await w.verified_count() == committed
    late = await w.matter("pm_late", w.pa)
    lvm, lvr = w.pair(late, "pv_late")
    assert await w.permit.commit_verified(lvm, lvr, w.pin(), w.src, ident, w.props) is False
    assert await w.nothing_written("pm_late")
    # Every report written belongs to a matter that is VERIFIED (no orphan, no half commit).
    reports = await w.db["permit_verifications"].find({}, {"matter_id": 1}).to_list(None)
    for r in reports:
        assert (await w.db["permit_matters"].find_one({"_id": r["matter_id"]}))["state"] == MatterState.VERIFIED.value


@scenario
async def test_c2_write_conflict_on_the_property_is_refused_then_commits_once(w: World):
    """Race: another transaction holds a write on the property document during the commit."""
    m = await w.matter("pm_lock", w.pa)
    vm, vr = w.pair(m, "pv_lock")
    ident = await w.gate_identity(w.pa)
    async with w.client.start_session() as blocker:
        await blocker.start_transaction()
        await w.db["properties"].update_one({"_id": w.pa}, {"$set": {"note": "held"}}, session=blocker)
        assert await w.permit.commit_verified(vm, vr, w.pin(), w.src, ident, w.props) is False
        assert await w.nothing_written("pm_lock")
        await blocker.abort_transaction()
    assert await w.permit.commit_verified(vm, vr, w.pin(), w.src, ident, w.props) is True
    assert await w.db["permit_verifications"].count_documents({"matter_id": "pm_lock"}) == 1


@scenario
async def test_td003_overlapping_snapshot_retry_on_a_real_server_keeps_the_chunks(w: World):
    """TD-003 round 2 (Codex, P1): on a real server the duplicate chunk insert is a BulkWriteError. Call A has
    written its chunks, not yet its snapshot; an overlapping retry B must not delete them."""
    from app.core.errors import StorageUnavailableError
    from tests.test_sources_ingest_concurrency import snapshot
    snap, chunks = snapshot("ss_overlap_rs")
    await w.src.ensure_indexes()
    await w.db["regulatory_chunks"].insert_many([{"_id": c.chunk_id, "seq": n, **c.model_dump(mode="python")}
                                                 for n, c in enumerate(chunks)])  # A, paused
    with pytest.raises(StorageUnavailableError):
        await w.src.save_snapshot(snap, chunks)  # B
    await w.db["source_snapshots"].insert_one({"_id": snap.snapshot_id, **snap.model_dump(mode="python")})  # A
    assert await w.db["regulatory_chunks"].count_documents({"snapshot_id": "ss_overlap_rs"}) == snap.chunk_count
    # A plain retry of the same, now published, snapshot returns what is stored and keeps the chunks.
    assert (await w.src.save_snapshot(snap, chunks)).snapshot_id == "ss_overlap_rs"
    assert await w.db["regulatory_chunks"].count_documents({"snapshot_id": "ss_overlap_rs"}) == snap.chunk_count
    # The same ID with other content and more chunks: refused, stored snapshot and its chunks untouched.
    other, more = snapshot("ss_overlap_rs", n=5)
    with pytest.raises(StorageUnavailableError):
        await w.src.save_snapshot(other.model_copy(update={"sha256": "cd" * 32}), more)
    assert await w.db["regulatory_chunks"].count_documents({"snapshot_id": "ss_overlap_rs"}) == snap.chunk_count
