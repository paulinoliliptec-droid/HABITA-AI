"""Source persistence.

MongoDB collections:
    official_sources   one document per registry source (``_id`` = source_id)
    source_snapshots   one document per distinct retrieved version (metadata + sha256, no binary)
    regulatory_chunks  normalized passages of a snapshot (``_id`` = chunk_id); kept for old
                       snapshots too, so cited evidence stays reproducible

Seeding sets reviewed metadata but never overwrites ``status``, ``status_history`` or
``latest_snapshot_id``, which belong to operators and ingestion.
"""

import asyncio
from datetime import date, datetime
from typing import Any

from pymongo import ASCENDING, AsyncMongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.errors import StorageUnavailableError
from app.schemas.sources import OfficialSource, RegulatoryChunk, SourceSnapshot, StatusChange

_UNAVAILABLE = "HABITA can't reach its source store right now. Please try again shortly."
_OPERATIONAL = {"status", "status_history", "latest_snapshot_id", "trust_version"}


def to_bson(value: Any) -> Any:
    """BSON stores datetimes but not plain dates: dates become ISO strings (Pydantic parses them back)."""
    if isinstance(value, dict):
        return {k: to_bson(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_bson(v) for v in value]
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    return value


class StatusChangedConcurrently(Exception):
    """The source's status or trust_version moved since the operator's change was validated (CX-3)."""


class InMemorySourceRepository:
    def __init__(self) -> None:
        self.sources: dict[str, OfficialSource] = {}
        #: Serialises status changes with VERIFIED commits (``InMemoryPermitRepository.commit_verified``).
        self.trust_lock = asyncio.Lock()
        self.snapshots: dict[str, SourceSnapshot] = {}
        self.chunks: dict[str, list[RegulatoryChunk]] = {}

    async def upsert_seed(self, source: OfficialSource) -> None:
        current = self.sources.get(source.source_id)
        if current is None:
            self.sources[source.source_id] = source.model_copy(deep=True)
        else:
            self.sources[source.source_id] = source.model_copy(
                update={k: getattr(current, k) for k in _OPERATIONAL}, deep=True
            )

    async def insert_source(self, source: OfficialSource) -> bool:
        if source.source_id in self.sources:
            return False
        self.sources[source.source_id] = source.model_copy(deep=True)
        return True

    async def get_source(self, source_id: str) -> OfficialSource | None:
        source = self.sources.get(source_id)
        return source.model_copy(deep=True) if source else None

    async def list_sources(self) -> list[OfficialSource]:
        return [s.model_copy(deep=True) for s in self.sources.values()]

    async def set_status(self, source_id: str, change: StatusChange,
                         expected: tuple[str, int] | None = None) -> None:
        """``expected``: the (status, trust_version) the change was validated against; if it moved, nothing is written
        and ``StatusChangedConcurrently`` is raised (CX-3: a retirement can't be undone by a stale promotion)."""
        async with self.trust_lock:
            source = self.sources[source_id]
            if expected is not None and (source.status, source.trust_version) != expected:
                raise StatusChangedConcurrently(source_id)
            source.status = change.status
            source.status_history.append(change)
            source.trust_version += 1

    def pin_holds(self, versions: dict[str, tuple[str, int]]) -> bool:
        """Every pinned source still has the (status, trust_version) the final gate read. Call under trust_lock."""
        return all((s := self.sources.get(sid)) is not None and (s.status, s.trust_version) == pinned
                   for sid, pinned in versions.items())

    async def set_latest_snapshot(self, source_id: str, snapshot_id: str) -> None:
        self.sources[source_id].latest_snapshot_id = snapshot_id

    async def find_snapshot(self, source_id: str, sha256: str) -> SourceSnapshot | None:
        return next((s for s in self.snapshots.values() if s.source_id == source_id and s.sha256 == sha256), None)

    async def get_snapshot(self, snapshot_id: str) -> SourceSnapshot | None:
        return self.snapshots.get(snapshot_id)

    async def save_snapshot(self, snapshot: SourceSnapshot, chunks: list[RegulatoryChunk]) -> SourceSnapshot:
        """The stored snapshot: this one, or the one already stored for the same (source_id, sha256) (CX-4)."""
        if (winner := await self.find_snapshot(snapshot.source_id, snapshot.sha256)) is not None:
            return winner
        self.snapshots[snapshot.snapshot_id] = snapshot
        self.chunks[snapshot.snapshot_id] = list(chunks)
        return snapshot

    async def list_chunks(self, snapshot_id: str) -> list[RegulatoryChunk]:
        return list(self.chunks.get(snapshot_id, []))


class MongoSourceRepository:
    def __init__(self, client: AsyncMongoClient, db_name: str) -> None:
        db = client[db_name]
        self.client = client
        self._sources = db["official_sources"]
        self._snapshots = db["source_snapshots"]
        self._chunks = db["regulatory_chunks"]

    async def ensure_indexes(self) -> None:
        await self._call(self._sources.create_index([("jurisdiction_id", ASCENDING), ("status", ASCENDING)]))
        await self._call(self._snapshots.create_index([("source_id", ASCENDING), ("sha256", ASCENDING)], unique=True))
        await self._call(self._chunks.create_index([("snapshot_id", ASCENDING), ("seq", ASCENDING)]))
        await self._call(self._chunks.create_index([("jurisdiction_id", ASCENDING), ("source_id", ASCENDING)]))

    async def upsert_seed(self, source: OfficialSource) -> None:
        doc = to_bson(source.model_dump(mode="python"))
        await self._call(self._sources.update_one(
            {"_id": source.source_id},
            {"$set": {k: v for k, v in doc.items() if k not in _OPERATIONAL},
             "$setOnInsert": {k: doc[k] for k in _OPERATIONAL}},
            upsert=True,
        ))

    async def insert_source(self, source: OfficialSource) -> bool:
        try:
            await self._sources.insert_one({"_id": source.source_id, **to_bson(source.model_dump(mode="python"))})
        except DuplicateKeyError:
            return False
        except PyMongoError:
            raise StorageUnavailableError(_UNAVAILABLE) from None
        return True

    async def get_source(self, source_id: str) -> OfficialSource | None:
        doc = await self._call(self._sources.find_one({"_id": source_id}))
        return OfficialSource.model_validate(doc) if doc else None

    async def list_sources(self) -> list[OfficialSource]:
        docs = await self._call(self._sources.find({}).to_list(None))
        return [OfficialSource.model_validate(d) for d in docs]

    async def set_status(self, source_id: str, change: StatusChange,
                         expected: tuple[str, int] | None = None) -> None:
        """Compare-and-swap when ``expected`` is given (see the in-memory store; CX-3)."""
        flt = self.pin_filter(source_id, *expected) if expected is not None else {"_id": source_id}
        result = await self._call(self._sources.update_one(
            flt,
            {"$set": {"status": change.status}, "$inc": {"trust_version": 1},
             "$push": {"status_history": to_bson(change.model_dump(mode="python"))}},
        ))
        if expected is not None and result.matched_count != 1:
            raise StatusChangedConcurrently(source_id)

    async def set_latest_snapshot(self, source_id: str, snapshot_id: str) -> None:
        await self._call(self._sources.update_one({"_id": source_id}, {"$set": {"latest_snapshot_id": snapshot_id}}))

    @property
    def collection(self):
        return self._sources

    @staticmethod
    def pin_filter(source_id: str, status: str, version: int) -> dict:
        """Matches the source only while it still has the pinned status and trust_version (a document written before
        trust_version existed counts as version 0)."""
        return {"_id": source_id, "status": status,
                "trust_version": {"$in": [0, None]} if version == 0 else version}

    async def find_snapshot(self, source_id: str, sha256: str) -> SourceSnapshot | None:
        doc = await self._call(self._snapshots.find_one({"source_id": source_id, "sha256": sha256}))
        return SourceSnapshot.model_validate(doc) if doc else None

    async def get_snapshot(self, snapshot_id: str) -> SourceSnapshot | None:
        doc = await self._call(self._snapshots.find_one({"_id": snapshot_id}))
        return SourceSnapshot.model_validate(doc) if doc else None

    async def save_snapshot(self, snapshot: SourceSnapshot, chunks: list[RegulatoryChunk]) -> SourceSnapshot:
        """Publish a snapshot idempotently under its unique (source_id, sha256) key and return the stored one.

        Chunks first: a snapshot document only exists once its passages are stored. If another worker published the
        same content first (duplicate key), or the chunk write fails part-way, this snapshot's chunks are removed so
        none is left orphaned, and the winner is returned (HR-003 CX-4)."""
        try:
            if chunks:
                await self._chunks.insert_many(
                    [{"_id": c.chunk_id, "seq": n, **to_bson(c.model_dump(mode="python"))}
                     for n, c in enumerate(chunks)])
            await self._snapshots.insert_one(
                {"_id": snapshot.snapshot_id, **to_bson(snapshot.model_dump(mode="python"))})
            return snapshot
        except DuplicateKeyError:
            await self._call(self._chunks.delete_many({"snapshot_id": snapshot.snapshot_id}))
            winner = await self.find_snapshot(snapshot.source_id, snapshot.sha256)
            if winner is None:
                raise StorageUnavailableError(_UNAVAILABLE) from None
            return winner
        except PyMongoError:
            try:
                await self._chunks.delete_many({"snapshot_id": snapshot.snapshot_id})
            except PyMongoError:
                pass  # best effort; the snapshot document was never written, so nothing references them
            raise StorageUnavailableError(_UNAVAILABLE) from None

    async def list_chunks(self, snapshot_id: str) -> list[RegulatoryChunk]:
        docs = await self._call(self._chunks.find({"snapshot_id": snapshot_id}).sort("seq", ASCENDING).to_list(None))
        return [RegulatoryChunk.model_validate(d) for d in docs]

    @staticmethod
    async def _call(awaitable):
        try:
            return await awaitable
        except PyMongoError:
            raise StorageUnavailableError(_UNAVAILABLE) from None
