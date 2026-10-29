"""HR-003 MU-9 Phase 2, item 1 (C2): a VERIFIED commit is bound to the property the final gate read.

Every write to a property document increments ``identity_version``; the commit writes the property in its own
transaction on ``identity_filter`` (same version, active, no merge in flight). ACC-BIND-01..06: a save, a merge on
either side, a pending merge, a purge or a missing identity after the gate ⇒ the commit is refused and nothing is
written; the workflow re-runs the gate."""

from datetime import timedelta

import pytest
from pymongo.errors import OperationFailure

from app.db.property_repository import PropertyIdentity
from tests import test_permit_commit_durability as durability
from tests.permit_fakes import ScriptedModel, make_client
from tests.test_permit_official_sources import ingest_regulamento, run_matter
from tests.test_property_repository import T0, make_repo, snapshot

PID = durability.IDENT.property_id


# --- every write moves the identity --------------------------------------------------------------------------------

async def test_every_write_to_a_property_increments_its_identity_version():
    repo, collection = make_repo()
    saved = await repo.save(snapshot(), {"ChIJ-a"})
    pid = saved.property_id
    versions = [(await repo.identity(pid)).version]
    await repo.save(snapshot(resolved_at=T0 + timedelta(hours=1)), {"ChIJ-a"}, property_id=pid)  # refresh
    versions.append((await repo.identity(pid)).version)
    await repo.save(snapshot(resolved_at=T0 + timedelta(hours=2)), {"ChIJ-a", "ChIJ-b"}, property_id=pid)  # alias
    versions.append((await repo.identity(pid)).version)
    assert versions[0] == 0 and versions == sorted(set(versions))  # strictly increasing


async def test_a_merge_moves_both_sides_and_the_duplicate_loses_its_identity():
    repo, collection = make_repo()
    keep = (await repo.save(snapshot(place_id="ChIJ-k"), {"ChIJ-k"})).property_id
    dup = (await repo.save(snapshot(place_id="ChIJ-d", address="Rua X 1, Cascais", lat=38.70), {"ChIJ-d"})).property_id
    before = (await repo.identity(keep)).version
    await repo.merge(keep=keep, duplicate=dup)
    assert (await repo.identity(keep)).version > before  # the kept property received aliases
    assert await repo.identity(dup) is None  # merged: no identity to bind a commit to


async def test_a_purge_moves_the_identity_and_leaves_none_to_bind():
    repo, collection = make_repo()
    pid = (await repo.save(snapshot(), {"ChIJ-a"})).property_id
    assert await repo.purge_expired(T0 + timedelta(days=60)) == 1
    assert collection.docs[pid]["identity_version"] == 1 and await repo.identity(pid) is None


async def test_an_unversioned_document_has_no_identity_until_backfilled():
    repo, collection = make_repo()
    pid = (await repo.save(snapshot(), {"ChIJ-a"})).property_id
    del collection.docs[pid]["identity_version"]
    assert await repo.identity(pid) is None  # fail closed: nothing to bind a commit to


# --- ACC-BIND-01..06: the commit refuses a property that moved after the gate ------------------------------------

def _moved(case, docs):
    doc = docs[PID]
    if case == "save":  # ACC-BIND-01 (and -03: the kept side of a merge receives aliases: a write)
        doc["identity_version"] += 1
    elif case == "merged-as-duplicate":  # ACC-BIND-02
        doc.update(merged_into="prp_other", snapshot_state="merged")
    elif case == "merge-pending":  # ACC-BIND-04
        doc.update(merging_into="prp_other", snapshot_state="merging")
    elif case == "purged":  # ACC-BIND-05
        doc.update(snapshot_state="purged")
    elif case == "deleted":
        del docs[PID]


@pytest.mark.parametrize("case", ["save", "merged-as-duplicate", "merge-pending", "purged", "deleted"])
async def test_a_property_that_moved_after_the_gate_refuses_the_commit(case):
    client, permit, src = durability.stores()
    _moved(case, client.collection("properties").docs)
    m, r = durability.verified()
    assert await permit.commit_verified(m, r, durability.PIN, src, durability.IDENT, durability.props(client)) is False
    assert client.commits_applied == 0 and "pv_1" not in permit._verifications.docs
    assert permit._matters.docs["pm_1"]["state"] == "VERIFYING"


@pytest.mark.parametrize("identity", [None, PropertyIdentity("prp_ffffffffffffffff", 0)], ids=["none", "other"])
async def test_no_identity_or_another_propertys_identity_fails_closed(identity):
    """ACC-BIND-06: the commit binds the matter's own property document, or nothing."""
    client, permit, src = durability.stores()
    m, r = durability.verified()
    assert await permit.commit_verified(m, r, durability.PIN, src, identity, durability.props(client)) is False
    assert client.commits_applied == 0


async def test_a_concurrent_property_write_is_a_refused_commit():
    """The commit writes the property, so a concurrent write is a write conflict: retried as a whole, then refused."""
    client, permit, src = durability.stores()
    conflict = OperationFailure("WriteConflict")
    conflict._add_error_label("TransientTransactionError")
    client.fail_on["properties.update_one"] = conflict
    m, r = durability.verified()
    assert await permit.commit_verified(m, r, durability.PIN, src, durability.IDENT, durability.props(client)) is False
    assert "pv_1" not in permit._verifications.docs


async def test_the_commit_marks_the_property_without_moving_its_identity():
    client, permit, src = durability.stores()
    m, r = durability.verified()
    assert await permit.commit_verified(m, r, durability.PIN, src, durability.IDENT, durability.props(client)) is True
    doc = client.collection("properties").docs[PID]
    assert "last_verified_commit_at" in doc and doc["identity_version"] == 0


# --- end to end: a property write between the gate and the commit -------------------------------------------------

def test_a_property_write_after_the_gate_is_never_committed_and_the_gate_re_runs():
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        workflow = client.app.state.permit_workflow
        repo, properties = workflow._repo, workflow._properties.repository
        original, results = repo.commit_verified, []

        async def commit(matter, report, pin, sources, identity, props):
            if not results:
                properties.touch(matter.property_id)  # a save lands after the gate's read
            results.append(await original(matter, report, pin, sources, identity, props))
            return results[-1]
        repo.commit_verified = commit
        mid, _ = run_matter(client)
        state = repo.matters[mid].state
    assert results[0] is False  # bound to the stale read: refused, nothing written
    assert results[-1] is True and state == "VERIFIED"  # the gate re-ran on the current property


# --- Codex Phase 2 binding review, round 1 (2026-10-29): exact cases ----------------------------------------------

async def test_a_merge_without_aliases_still_moves_the_kept_identity():
    repo, collection = make_repo()
    keep = (await repo.save(snapshot(place_id="ChIJ-k"), {"ChIJ-k"})).property_id
    collection.docs["prp_legacy"] = {"_id": "prp_legacy", "place_id": "ChIJ-old", "identity_version": 0,
                                     "snapshot_state": "current", "created_at": T0}  # a legacy duplicate, no place_ids
    before = await repo.identity(keep)
    await repo.merge(keep=keep, duplicate="prp_legacy")
    assert (await repo.identity(keep)).version > before.version


async def test_an_older_in_memory_save_that_attaches_an_alias_moves_the_identity():
    from app.db.property_repository import InMemoryPropertyRepository
    repo = InMemoryPropertyRepository()
    pid = (await repo.save(snapshot(resolved_at=T0 + timedelta(hours=1)), {"ChIJ-a"})).property_id
    captured = await repo.identity(pid)
    await repo.save(snapshot(), {"ChIJ-a", "ChIJ-late"})  # older snapshot, new alias
    assert not repo.identity_holds(captured)


# --- Codex Phase 2 binding review, round 2 (2026-10-29): exact cases ----------------------------------------------

async def test_a_pending_merge_into_the_property_refuses_the_commit():
    """The kept side is marked before the duplicate: a commit bound to the identity read before the merge fails."""
    repo, collection = make_repo()
    keep = (await repo.save(snapshot(place_id="ChIJ-k"), {"ChIJ-k"})).property_id
    dup = (await repo.save(snapshot(place_id="ChIJ-d", address="Rua X 1, Cascais", lat=38.70), {"ChIJ-d"})).property_id
    before = await repo.identity(keep)
    await repo._collection.update_one({"_id": keep}, {"$addToSet": {"absorbing": {"$each": [dup]}},
                                                      "$inc": {"identity_version": 1}})  # merge step 0 only
    assert await repo.identity(keep) is None  # no identity while absorbing
    client, permit, src = durability.stores()
    doc = client.collection("properties").docs[PID]
    doc.update(absorbing=[dup], identity_version=before.version + 1)
    m, r = durability.verified()
    assert await permit.commit_verified(m, r, durability.PIN, src, durability.IDENT, durability.props(client)) is False


async def test_an_in_memory_identity_needs_the_property_to_exist():
    from app.db.property_repository import InMemoryPropertyRepository
    repo = InMemoryPropertyRepository()
    pid = (await repo.save(snapshot(), {"ChIJ-a"})).property_id
    captured = await repo.identity(pid)
    del repo._items[pid]  # deleted
    assert not repo.identity_holds(captured) and await repo.identity(pid) is None


async def test_the_commit_filter_refuses_an_absorbing_property_even_at_the_same_version():
    """Defence in depth: the filter itself refuses a merge in flight into the property."""
    client, permit, src = durability.stores()
    client.collection("properties").docs[PID]["absorbing"] = ["prp_dup"]
    m, r = durability.verified()
    assert await permit.commit_verified(m, r, durability.PIN, src, durability.IDENT, durability.props(client)) is False
