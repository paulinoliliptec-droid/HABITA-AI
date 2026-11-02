"""HR-003 backlog CX-4: concurrent ingestion of the same content leaves no orphaned chunks.

Two workers can both miss the (source_id, sha256) snapshot, build different snapshot ids and insert their chunks; the
loser of the unique snapshot insert removes its own chunks and adopts the winner. A chunk write that fails part-way is
cleaned up too."""

from datetime import UTC, datetime

import pytest
from pymongo.errors import AutoReconnect, DuplicateKeyError

from app.core.errors import StorageUnavailableError
from app.schemas.sources import PassageLocator, RegulatoryChunk, SourceSnapshot
from app.services.sources.repository import MongoSourceRepository


class Collection:
    def __init__(self, unique=None):
        self.docs, self.unique, self.fail_insert_many, self.lost_ack = {}, unique, None, False

    async def insert_one(self, doc):
        if doc["_id"] in self.docs:  # MongoDB's own unique _id
            raise DuplicateKeyError("E11000 _id")
        if self.unique and any(all(d.get(k) == doc.get(k) for k in self.unique) for d in self.docs.values()):
            raise DuplicateKeyError("E11000")
        self.docs[doc["_id"]] = dict(doc)
        if self.lost_ack:  # applied, but the acknowledgement is lost
            raise AutoReconnect("connection closed")

    async def insert_many(self, docs):
        if self.unique and any(d["_id"] in self.docs for d in docs):
            raise DuplicateKeyError("E11000")
        for n, doc in enumerate(docs):
            if self.fail_insert_many is not None and n == self.fail_insert_many:
                raise AutoReconnect("injected")
            self.docs[doc["_id"]] = dict(doc)

    async def delete_many(self, flt):
        for key in [k for k, d in self.docs.items() if all(d.get(f) == v for f, v in flt.items())]:
            del self.docs[key]

    async def find_one(self, flt, *args, **kwargs):
        return next((d for d in self.docs.values() if all(d.get(f) == v for f, v in flt.items())), None)


def repo():
    r = MongoSourceRepository.__new__(MongoSourceRepository)
    r._snapshots, r._chunks = Collection(unique=("source_id", "sha256")), Collection()
    return r


def snapshot(sid, n=3):
    snap = SourceSnapshot(snapshot_id=sid, source_id="cascais-pdm", retrieved_at=datetime(2026, 10, 29, tzinfo=UTC),
                          requested_url="https://www.cascais.pt/x.pdf", final_url="https://www.cascais.pt/x.pdf",
                          http_status=200, content_type="application/pdf", bytes=10, sha256="ab" * 32,
                          version_detected=None, pages=1, text_extracted=True, chunk_count=n)
    chunks = [RegulatoryChunk(chunk_id=f"{sid}:{i}", source_id="cascais-pdm", snapshot_id=sid,
                              jurisdiction_id="pt/lisboa/cascais", locator=PassageLocator(page=1),
                              text=f"passage {i}") for i in range(n)]
    return snap, chunks


async def test_the_losing_worker_removes_its_chunks_and_adopts_the_winner():
    r = repo()
    winner, loser = snapshot("ss_winner"), snapshot("ss_loser")
    assert (await r.save_snapshot(*winner)).snapshot_id == "ss_winner"
    assert (await r.save_snapshot(*loser)).snapshot_id == "ss_winner"  # same content, published second
    assert {d["snapshot_id"] for d in r._chunks.docs.values()} == {"ss_winner"}  # no orphans
    assert list(r._snapshots.docs) == ["ss_winner"]


async def test_a_chunk_write_failing_part_way_leaves_nothing_behind():
    r = repo()
    r._chunks.fail_insert_many = 2
    with pytest.raises(StorageUnavailableError):
        await r.save_snapshot(*snapshot("ss_partial"))
    assert r._chunks.docs == {} and r._snapshots.docs == {}


async def test_a_lost_acknowledgement_keeps_a_published_snapshot_whole():
    """Codex backlog review round 2: the snapshot was written; its chunks must not be deleted."""
    r = repo()
    r._snapshots.lost_ack = True
    assert (await r.save_snapshot(*snapshot("ss_acked"))).snapshot_id == "ss_acked"
    assert len([d for d in r._chunks.docs.values() if d["snapshot_id"] == "ss_acked"]) == 3


async def test_publishing_the_same_snapshot_twice_keeps_its_chunks():
    """Codex backlog review round 3 (P2): a retry of the same snapshot is not a losing worker."""
    r = repo()
    r._chunks.unique = ("_id",)
    await r.save_snapshot(*snapshot("ss_same"))
    assert (await r.save_snapshot(*snapshot("ss_same"))).snapshot_id == "ss_same"
    assert len(r._chunks.docs) == 3


async def test_td003_an_overlapping_retry_never_deletes_the_chunks_of_the_call_still_publishing():
    """TD-003 (Codex 2026-11-01, P1): call A has written its chunks but not yet its snapshot; an overlapping retry B
    of the same snapshot hits the duplicate chunks and must not delete them, or A publishes a snapshot with none."""
    r = repo()
    r._chunks.unique = ("_id",)
    snap, chunks = snapshot("ss_overlap")
    await r._chunks.insert_many([{"_id": c.chunk_id, "seq": n, **c.model_dump(mode="python")}
                                 for n, c in enumerate(chunks)])  # A, paused after its chunk write
    with pytest.raises(StorageUnavailableError):
        await r.save_snapshot(snap, chunks)  # B
    await r._snapshots.insert_one({"_id": snap.snapshot_id, **snap.model_dump(mode="python")})  # A resumes
    assert len([d for d in r._chunks.docs.values() if d["snapshot_id"] == "ss_overlap"]) == snap.chunk_count


async def test_td003_a_reused_snapshot_id_with_other_content_keeps_the_stored_chunks():
    """TD-003 (Codex 2026-11-01, P2): an ID reused for different content is refused; the stored snapshot keeps all
    its chunks."""
    r = repo()
    r._chunks.unique = ("_id",)  # as MongoDB: a chunk _id is unique, never overwritten
    await r.save_snapshot(*snapshot("ss_same"))
    other, other_chunks = snapshot("ss_same")
    other = other.model_copy(update={"sha256": "cd" * 32})
    with pytest.raises(StorageUnavailableError):
        await r.save_snapshot(other, other_chunks)
    assert len([d for d in r._chunks.docs.values() if d["snapshot_id"] == "ss_same"]) == 3
    assert r._snapshots.docs["ss_same"]["sha256"] == "ab" * 32


async def test_td003_r3_a_failed_call_cleaning_up_never_deletes_the_chunks_another_call_published():
    """TD-003 round 3 (Codex 2026-11-01, P1): A's chunk write fails before writing anything; A sees no snapshot;
    B then publishes the same snapshot with its chunks; A's cleanup must not delete B's chunks."""
    r = repo()
    r._chunks.unique = ("_id",)
    snap, chunks = snapshot("ss_gap")
    real_find = r._snapshots.find_one
    state = {"b_done": False}

    async def find_then_b(flt, *a, **kw):
        found = await real_find(flt, *a, **kw)
        if not state["b_done"]:
            state["b_done"] = True
            r._chunks.fail_insert_many = None
            await r.save_snapshot(snap, chunks)  # B publishes in the gap
        return found
    r._chunks.fail_insert_many = 0  # A fails before writing a chunk
    r._snapshots.find_one = find_then_b
    with pytest.raises(StorageUnavailableError):
        await r.save_snapshot(snap, chunks)  # A
    assert "ss_gap" in r._snapshots.docs
    assert len([d for d in r._chunks.docs.values() if d["snapshot_id"] == "ss_gap"]) == snap.chunk_count


async def test_td003_candidate_a_reused_id_with_other_chunk_ids_leaves_none_of_its_chunks():
    """TD-003 candidate review r1 (Codex 2026-11-02, P2): other content under a taken snapshot ID, with chunk IDs of
    its own, was refused but its chunks stayed under the published ID (read by ``list_chunks``)."""
    r = repo()
    r._chunks.unique = ("_id",)
    await r.save_snapshot(*snapshot("ss_taken"))
    other, other_chunks = snapshot("ss_taken")
    other = other.model_copy(update={"sha256": "cd" * 32, "chunk_count": 1})
    stray = other_chunks[0].model_copy(update={"chunk_id": "ch_stray", "text": "Injected passage."})
    with pytest.raises(StorageUnavailableError):
        await r.save_snapshot(other, [stray])
    assert len([d for d in r._chunks.docs.values() if d["snapshot_id"] == "ss_taken"]) == 3
    assert "ch_stray" not in r._chunks.docs
