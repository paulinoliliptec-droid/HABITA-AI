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
        if self.unique and any(all(d.get(k) == doc.get(k) for k in self.unique) for d in self.docs.values()):
            raise DuplicateKeyError("E11000")
        self.docs[doc["_id"]] = dict(doc)
        if self.lost_ack:  # applied, but the acknowledgement is lost
            raise AutoReconnect("connection closed")

    async def insert_many(self, docs):
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
