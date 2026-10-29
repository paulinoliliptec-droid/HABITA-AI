"""Property persistence.

Identity
    A HABITA ``property_id`` is generated once, when a location is first
    resolved, and never derived from a provider ID. A resolution attaches to an
    existing property by, in order:

    1. ``property_id`` (refreshing a known property);
    2. alias: any Google place ID seen in this resolution is already in a
       property's ``place_ids`` (unique across properties);
    3. address: the same deterministic ``address_key`` (jurisdiction ID +
       normalised route + street number + unit; built only for premise-level
       results) **and** a stored point within ``ADDRESS_MATCH_TOLERANCE_M``,
       with exactly one such candidate.

    Anything less certain creates a new property. Candidates that share the
    address key but fail the distance check, or more than one passing candidate,
    are recorded on the new document as ``possible_duplicates`` for review,
    never merged automatically.

    Concurrent creation of one premise is arbitrated by ``premise_key``: the first
    property for an address key holds it under a unique (partial) index, so two
    simultaneous inserts for the same premise collide, and the loser's retry finds
    the winner through the address step. A far-away homonym (same key, beyond the
    tolerance) is still created, just without the premise claim. Unit numbers are
    part of the key, so a unit never merges with another unit or with the
    building-level record.

Reconciliation
    ``merge(keep, duplicate)`` is the explicit, operator-run path for reviewed
    duplicates (``python -m app.maintenance``). It is an idempotent state machine:

        1. duplicate → ``snapshot_state: "merging"``, ``merging_into: keep``; its
           aliases move from ``place_ids`` to ``merged_aliases`` (one atomic update);
        2. ``merged_aliases`` are added to ``keep`` (idempotent ``$addToSet``);
        3. duplicate → ``snapshot_state: "merged"``, ``merged_into: keep``.

    In every intermediate state the aliases are recorded on the duplicate, alias
    lookups and reads of the duplicate's ID resolve to ``keep``, and re-running
    ``merge`` (or ``resume_pending_merges`` at startup) completes the remaining
    steps. No failure can leave aliases orphaned or links broken.

    Merges may chain (A → B, later B → C). Reads, alias lookups, explicit-ID
    writes and merges all follow ``merged_into``/``merging_into`` to the
    *canonical* property, so A's link and aliases reach C. A merged or merging
    document is never written as a property again: snapshot updates exclude
    tombstones, and a write that races a merge retries against the canonical ID.

Snapshot lifecycle
    Google-derived fields form a snapshot with ``expires_at``. A stored
    snapshot is replaced only by a newer one (or any snapshot when the stored
    document is from an older schema), so a delayed write can't regress fresher
    data. Expired snapshots are never served (the service refreshes from the
    place ID) and are purged by ``purge_expired``, which removes the
    Google-derived fields but keeps the HABITA identity, place IDs and request
    provenance.

Concurrency
    Saves are optimistic and retried, never resolved by swallowing a conflict.
    Every write that touches a property (snapshot, aliases) is conditional on
    the target still being active (not merging or merged). If a condition fails,
    an alias is claimed concurrently, or an insert collides, the whole save is
    retried against the *current* canonical property (bounded). Before reporting
    success the save re-checks that its target is still the active canonical
    property, so a successful save always returns the final canonical ID with
    every one of its aliases attached to it (or recorded on the merge path to
    it). An alias owned by another, unrelated canonical property is not moved:
    the conflict is recorded explicitly in ``possible_duplicates``.

Identity binding (HR-003 MU-9 C2)
    Every write to a property document increments ``identity_version`` (an integer; 0 on insert, backfilled to 0 for
    older documents). A VERIFIED permit commit reads ``(property_id, identity_version)`` before its final gate and, in
    the same transaction as the matter, writes the property conditionally on that version, an active state and no
    merge in flight (``identity_filter``). A save, merge or purge after the read is then a write conflict or a filter
    miss, and nothing is committed. The commit's own write (``last_verified_commit_at``) does not change the version.

Schema versions:
    0  (HR-001 initial) ``_id`` = hash of a single place ID; flat jurisdiction strings.
    1  aliases, generic jurisdiction levels, authority entity, provenance, expiry.
    2  ``address_key``, ``snapshot_state``, identity method in provenance;
       ``partial_match`` is no longer stored (it belongs to a request).
Documents below the current version are kept and upgraded in place on their next
resolution or read.
"""

import logging
import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from pydantic import ValidationError
from pymongo import ASCENDING, GEOSPHERE, AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.errors import StorageUnavailableError
from app.schemas.property import Coordinates, IdentityMatch, PropertySnapshot, ResolvedProperty

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2
# The address key already pins municipality, route, number and unit; the distance only
# guards against homonymous streets in one municipality (typically far apart). Google's
# rooftop points for one premise were measured 30 m apart (Av. 25 de Abril 1011, Cascais).
ADDRESS_MATCH_TOLERANCE_M = 50.0
_SAVE_ATTEMPTS = 6
_MAX_MERGE_HOPS = 16
_STORAGE_UNAVAILABLE = "HABITA can't reach its property store right now. Please try again shortly."

# Google-derived content removed when a snapshot expires. HABITA identity, place IDs
# (storable indefinitely), the request record and timestamps are kept.
GOOGLE_DERIVED_FIELDS = (
    "formatted_address", "coordinates", "location", "precision", "jurisdiction", "address_key", "premise_key",
)


class _RetrySave(Exception):
    """The target became a tombstone mid-save; retry against the canonical property."""


def _merge_target(doc: dict) -> str | None:
    return doc.get("merged_into") or doc.get("merging_into")


def new_property_id() -> str:
    return "prp_" + secrets.token_hex(8)


def distance_m(a: Coordinates, b: Coordinates) -> float:
    """Great-circle distance in metres (haversine)."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat, dlng = lat2 - lat1, math.radians(b.lng - a.lng)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(math.sqrt(h))


@dataclass(frozen=True)
class PropertyIdentity:
    """A property as the final gate read it: its document ID and ``identity_version`` (see module docstring)."""
    property_id: str
    version: int


def identity_filter(identity: PropertyIdentity) -> dict:
    """The property is still the one the gate read: same version, active, no merge in flight."""
    return {"_id": identity.property_id, "identity_version": identity.version, "snapshot_state": "current",
            "merged_into": {"$exists": False}, "merging_into": {"$exists": False}}


_BUMP = {"$inc": {"identity_version": 1}}


@dataclass(frozen=True)
class StoredProperty:
    property_id: str
    #: Primary provider ID, used to refresh the snapshot.
    place_id: str
    #: ``None`` when the snapshot is expired-and-purged or predates the current schema.
    snapshot: ResolvedProperty | None


class PropertyRepository(Protocol):
    async def save(
        self,
        snapshot: PropertySnapshot,
        aliases: set[str],
        *,
        address_key: str | None = None,
        property_id: str | None = None,
    ) -> ResolvedProperty:
        """Attach a snapshot to an existing property (see module docstring) or create one."""
        ...

    async def get(self, property_id: str) -> StoredProperty | None: ...

    async def identity(self, property_id: str) -> PropertyIdentity | None:
        """The document's own identity (no merge followed), or None if it is merged, merging, purged or unversioned."""
        ...

    async def purge_expired(self, now: datetime | None = None) -> int: ...

    async def merge(self, keep: str, duplicate: str) -> None: ...

    async def resume_pending_merges(self) -> int: ...

    async def ping(self) -> None: ...


def _with_identity(snapshot: PropertySnapshot, identity: IdentityMatch) -> PropertySnapshot:
    return snapshot.model_copy(update={"provenance": snapshot.provenance.model_copy(update={"identity": identity})})


class InMemoryPropertyRepository:
    """Process-local store for development and tests. Same identity, ordering and lifecycle rules as Mongo."""

    def __init__(self) -> None:
        self._items: dict[str, ResolvedProperty] = {}
        self._address_keys: dict[str, str] = {}
        self._owner_by_alias: dict[str, str] = {}
        self._versions: dict[str, int] = {}

    async def save(
        self,
        snapshot: PropertySnapshot,
        aliases: set[str],
        *,
        address_key: str | None = None,
        property_id: str | None = None,
    ) -> ResolvedProperty:
        identity: IdentityMatch = "refresh"
        pid = property_id
        if pid is None:
            identity = "alias"
            pid = self._owner_by_alias.get(snapshot.place_id) or next(
                (self._owner_by_alias[a] for a in sorted(aliases) if a in self._owner_by_alias), None
            )
        if pid is None and address_key:
            identity = "address"
            pid = self._address_candidate(address_key, snapshot)
        if pid is None:
            identity, pid = "new", new_property_id()

        for alias in aliases:
            self._owner_by_alias.setdefault(alias, pid)
        current = self._items.get(pid)
        if current is not None and current.resolved_at >= snapshot.resolved_at:
            return current
        self._items[pid] = ResolvedProperty(**_with_identity(snapshot, identity).model_dump(), property_id=pid)
        self._versions[pid] = self._versions.get(pid, -1) + 1
        if address_key:
            self._address_keys[pid] = address_key
        return self._items[pid]

    def _address_candidate(self, address_key: str, snapshot: PropertySnapshot) -> str | None:
        near = [
            pid
            for pid, key in self._address_keys.items()
            if key == address_key
            and distance_m(self._items[pid].coordinates, snapshot.coordinates) <= ADDRESS_MATCH_TOLERANCE_M
        ]
        return near[0] if len(near) == 1 else None

    async def get(self, property_id: str) -> StoredProperty | None:
        prop = self._items.get(property_id)
        return StoredProperty(prop.property_id, prop.place_id, prop) if prop else None

    async def identity(self, property_id: str) -> PropertyIdentity | None:
        version = self._versions.get(property_id)
        return PropertyIdentity(property_id, version) if version is not None else None

    def identity_holds(self, identity: PropertyIdentity) -> bool:
        return self._versions.get(identity.property_id) == identity.version

    def touch(self, property_id: str) -> None:
        """A write to the property (tests: a save between the gate and the commit)."""
        self._versions[property_id] = self._versions.get(property_id, -1) + 1

    async def purge_expired(self, now: datetime | None = None) -> int:
        # Memory is never durable; nothing outlives the process.
        return 0

    async def merge(self, keep: str, duplicate: str) -> None:
        raise NotImplementedError("Reconciliation applies to the durable store only.")

    async def resume_pending_merges(self) -> int:
        return 0

    async def ping(self) -> None:
        return None


class MongoPropertyRepository:
    def __init__(self, client: AsyncMongoClient, db_name: str) -> None:
        self._client = client
        self._collection: AsyncCollection = client[db_name]["properties"]

    async def ensure_indexes(self) -> None:
        # Tombstones written before this fix stored `place_ids: []`, which the unique index
        # treats as a null key shared between documents. Remove the empty arrays.
        await self._collection.update_many({"place_ids": {"$size": 0}}, {"$unset": {"place_ids": ""}, **_BUMP})
        indexes = {ix["name"]: ix async for ix in await self._collection.list_indexes()}
        # v0 made place_id unique; under aliases it is only the primary ID and need not be.
        if indexes.get("place_id_1", {}).get("unique"):
            await self._collection.drop_index("place_id_1")
        await self._collection.create_index([("place_id", ASCENDING)])
        await self._collection.create_index(
            [("place_ids", ASCENDING)],
            unique=True,
            partialFilterExpression={"place_ids": {"$exists": True}},
        )
        await self._collection.create_index([("address_key", ASCENDING)], sparse=True)
        # Arbitrates concurrent creation of one premise (see module docstring).
        await self._collection.create_index(
            [("premise_key", ASCENDING)],
            unique=True,
            partialFilterExpression={"premise_key": {"$type": "string"}},
        )
        await self._collection.create_index([("merged_aliases", ASCENDING)], sparse=True)
        # Backfill: current properties written before premise claims existed claim their key now
        # (oldest first), so concurrent creation is arbitrated for them too.
        unclaimed = await self._collection.find(
            {"snapshot_state": "current", "address_key": {"$type": "string"}, "premise_key": {"$exists": False}},
            {"_id": 1, "address_key": 1},
        ).sort("created_at", ASCENDING).to_list(None)
        for doc in unclaimed:
            await self._claim_premise(doc["_id"], doc["address_key"])
        # Identity binding: documents written before identity_version existed start at 0 (C2).
        await self._collection.update_many({"identity_version": {"$exists": False}}, {"$set": {"identity_version": 0}})
        await self._collection.create_index([("expires_at", ASCENDING)])
        await self._collection.create_index([("location", GEOSPHERE)])

    async def ping(self) -> None:
        try:
            await self._client.admin.command("ping")
        except PyMongoError as exc:
            raise _unavailable(exc) from None

    async def save(
        self,
        snapshot: PropertySnapshot,
        aliases: set[str],
        *,
        address_key: str | None = None,
        property_id: str | None = None,
    ) -> ResolvedProperty:
        ordered = sorted(aliases)
        try:
            for attempt in range(1, _SAVE_ATTEMPTS + 1):
                try:
                    return await self._save_once(snapshot, ordered, address_key, property_id)
                except DuplicateKeyError:
                    # Another request inserted first; the retry attaches to its property.
                    logger.info("Concurrent property insert; converging (attempt %d)", attempt)
                except _RetrySave as retry:
                    logger.info("Save retried on the canonical property (%s, attempt %d)", retry, attempt)
            raise StorageUnavailableError(_STORAGE_UNAVAILABLE)
        except PyMongoError as exc:
            raise _unavailable(exc) from None

    async def get(self, property_id: str) -> StoredProperty | None:
        try:
            doc = await self._collection.find_one({"_id": property_id})
        except PyMongoError as exc:
            raise _unavailable(exc) from None
        if doc is None:
            return None
        if _merge_target(doc):
            # A reconciled (or reconciling) duplicate: its ID resolves to the canonical property,
            # however many merges it took to get there.
            try:
                doc = await self._canonical_doc(doc)
            except PyMongoError as exc:
                raise _unavailable(exc) from None
            if doc is None:
                return None
        snapshot = None
        if doc.get("schema_version") == SCHEMA_VERSION and doc.get("snapshot_state") == "current":
            try:
                snapshot = ResolvedProperty.model_validate({**doc, "property_id": doc["_id"]})
            except ValidationError:
                logger.warning("Stored property %s failed validation; it will be refreshed", doc["_id"])
        return StoredProperty(doc["_id"], doc["place_id"], snapshot)

    async def identity(self, property_id: str) -> PropertyIdentity | None:
        try:
            doc = await self._collection.find_one({"_id": property_id},
                                                  {"identity_version": 1, "snapshot_state": 1, "merged_into": 1,
                                                   "merging_into": 1})
        except PyMongoError as exc:
            raise _unavailable(exc) from None
        if doc is None or _merge_target(doc) or doc.get("snapshot_state") != "current":
            return None
        version = doc.get("identity_version")
        return PropertyIdentity(property_id, version) if isinstance(version, int) else None

    @property
    def collection(self) -> AsyncCollection:
        return self._collection

    async def purge_expired(self, now: datetime | None = None) -> int:
        """Remove expired Google-derived fields. Identity, place IDs and provenance are kept."""
        try:
            result = await self._collection.update_many(
                {"expires_at": {"$lte": now or datetime.now(UTC)}, "snapshot_state": "current"},
                {"$unset": {field: "" for field in GOOGLE_DERIVED_FIELDS}, "$set": {"snapshot_state": "purged"},
                 **_BUMP},
            )
        except PyMongoError as exc:
            raise _unavailable(exc) from None
        return result.modified_count

    async def merge(self, keep: str, duplicate: str) -> None:
        """Fold a reviewed duplicate into ``keep``. Explicit, operator-run and safe to re-run."""
        if keep == duplicate:
            raise ValueError("A property can't be merged into itself.")
        try:
            kept = await self._collection.find_one({"_id": keep})
            dup = await self._collection.find_one({"_id": duplicate})
            if kept is None or dup is None:
                raise ValueError("Both properties must exist.")
            # Always merge into the canonical end of any chain (A → B, then B → C: keep C).
            kept = await self._canonical_doc(kept)
            if kept is None:
                raise ValueError(f"{keep} has no canonical property.")
            if kept["_id"] != keep:
                logger.info("Merge target %s is merged; using canonical %s", keep, kept["_id"])
                keep = kept["_id"]
            if keep == duplicate:
                raise ValueError("A property can't be merged into itself.")
            target = _merge_target(dup)
            if target:
                canonical_target = await self._canonical_doc(await self._collection.find_one({"_id": target}))
                if canonical_target is None or canonical_target["_id"] != keep:
                    raise ValueError(f"{duplicate} is already merged into {target}.")

            if not target:
                # Step 1, atomic: release the aliases into merged_aliases and mark the merge pending.
                await self._collection.update_one(
                    {"_id": duplicate, "merged_into": {"$exists": False}, "merging_into": {"$exists": False}},
                    {
                        "$set": {
                            "merging_into": keep,
                            "snapshot_state": "merging",
                            "merged_aliases": dup.get("place_ids", []),
                        },
                        # Unset, not []: an empty array is indexed as a null key, and the
                        # unique place_ids index would then collide between tombstones.
                        "$unset": {"place_ids": "", "premise_key": ""},
                        **_BUMP,
                    },
                )
                dup = await self._collection.find_one({"_id": duplicate})
                if _merge_target(dup) != keep:
                    raise ValueError(f"{duplicate} was merged concurrently; re-run to inspect.")

            # Step 2, idempotent: attach the recorded aliases to `keep` (its canonical property
            # if `keep` was itself merged meanwhile).
            aliases = dup.get("merged_aliases", [])
            for _ in range(_SAVE_ATTEMPTS):
                try:
                    if aliases:
                        await self._add_aliases(keep, aliases)
                    break
                except _RetrySave:
                    canonical = await self._canonical_doc(await self._collection.find_one({"_id": keep}))
                    if canonical is None:
                        raise StorageUnavailableError(_STORAGE_UNAVAILABLE) from None
                    keep = canonical["_id"]
            else:
                raise StorageUnavailableError(_STORAGE_UNAVAILABLE)
            # Step 3, idempotent: finalise the tombstone.
            await self._collection.update_one(
                {"_id": duplicate},
                {
                    "$set": {"merged_into": keep, "snapshot_state": "merged"},
                    "$unset": {"merging_into": "", **{field: "" for field in GOOGLE_DERIVED_FIELDS}},
                    **_BUMP,
                },
            )
        except PyMongoError as exc:
            raise _unavailable(exc) from None
        logger.info("Merged property %s into %s (%d aliases moved)", duplicate, keep, len(aliases))

    async def resume_pending_merges(self) -> int:
        """Complete merges interrupted between steps. Safe to run at any time."""
        try:
            pending = await self._collection.find(
                {"snapshot_state": "merging"}, {"_id": 1, "merging_into": 1}
            ).to_list(None)
        except PyMongoError as exc:
            raise _unavailable(exc) from None
        for doc in pending:
            await self.merge(keep=doc["merging_into"], duplicate=doc["_id"])
        return len(pending)

    async def _save_once(
        self, snapshot: PropertySnapshot, aliases: list[str], address_key: str | None, property_id: str | None
    ) -> ResolvedProperty:
        identity: IdentityMatch = "refresh"
        pid = property_id
        possible_duplicates: list[str] = []
        if pid is not None:
            # An explicit ID may be a merged duplicate's: write to its canonical property.
            doc = await self._canonical_doc(await self._collection.find_one({"_id": pid}))
            pid = doc["_id"] if doc else pid
        if pid is None:
            identity = "alias"
            pid = await self._owner_of(snapshot.place_id, aliases)
        if pid is None and address_key:
            identity = "address"
            pid, possible_duplicates = await self._address_match(address_key, snapshot)

        if pid is None:
            pid = new_property_id()
            snapshot = _with_identity(snapshot, "new")
            doc = {**self._document(snapshot, address_key), "_id": pid, "place_ids": aliases,
                   "created_at": snapshot.resolved_at, "identity_version": 0}
            if possible_duplicates:
                logger.warning("New property %s shares an address key with %s; not merged", pid, possible_duplicates)
                doc["possible_duplicates"] = possible_duplicates
            elif address_key:
                # First property for this premise: claim it. A concurrent insert of the same
                # premise collides here and its retry attaches to this property.
                doc["premise_key"] = address_key
            await self._collection.insert_one(doc)  # DuplicateKeyError → save() retries and converges
            return ResolvedProperty(**snapshot.model_dump(), property_id=pid)

        snapshot = _with_identity(snapshot, identity)
        newer_or_upgrade = {
            "$or": [
                {"resolved_at": {"$lt": snapshot.resolved_at}},
                {"schema_version": {"$ne": SCHEMA_VERSION}},
                {"snapshot_state": {"$ne": "current"}},
            ]
        }
        not_tombstone = {"merged_into": {"$exists": False}, "merging_into": {"$exists": False}}
        result = await self._collection.update_one(
            {"_id": pid, **not_tombstone, **newer_or_upgrade},
            # partial_match was stored by schema 1; it is request-scoped and must not linger.
            {"$set": self._document(snapshot, address_key), "$unset": {"partial_match": ""}, **_BUMP},
        )
        if result.matched_count == 0:
            current = await self._collection.find_one({"_id": pid}, {"merged_into": 1, "merging_into": 1})
            if current is not None and _merge_target(current):
                raise _RetrySave("target merged before the snapshot write")  # never reactivate a tombstone
        # Attach this resolution's aliases, conditionally on the target still being active.
        await self._add_aliases(pid, aliases)
        if result.matched_count:
            if address_key:
                await self._claim_premise(pid, address_key)
            else:
                await self._collection.update_one({"_id": pid, **not_tombstone},
                                                  {"$unset": {"premise_key": ""}, **_BUMP})
        # Success is only reported for the active canonical property. If a merge started after
        # our writes, the aliases we attached travel with it; retry so the result (and snapshot)
        # is the canonical property's.
        await self._ensure_active(pid)
        if result.matched_count == 0:
            # A newer snapshot is already stored: return that one.
            stored = await self.get(pid)
            if stored is not None and stored.snapshot is not None:
                return stored.snapshot
        return ResolvedProperty(**snapshot.model_dump(), property_id=pid)

    async def _owner_of(self, primary: str, aliases: list[str]) -> str | None:
        """The property owning the resolved (primary) place ID, else the oldest owner of any alias.

        Aliases recorded on a merged or merging duplicate resolve to its merge target,
        so no alias is ever orphaned while a merge is in flight.
        """
        # The legacy `place_id` clause finds schema-0 documents, which have no `place_ids`.
        for ids in ([primary], aliases):
            doc = await self._collection.find_one(
                {"$or": [{"place_ids": {"$in": ids}}, {"merged_aliases": {"$in": ids}}, {"place_id": {"$in": ids}}]},
                {"_id": 1, "merged_into": 1, "merging_into": 1},
                sort=[("created_at", ASCENDING)],
            )
            if doc:
                canonical = await self._canonical_doc(doc) if _merge_target(doc) else doc
                return canonical["_id"] if canonical else doc["_id"]
        return None

    async def _address_match(self, address_key: str, snapshot: PropertySnapshot) -> tuple[str | None, list[str]]:
        """Exactly one nearby property with the same address key, or none (plus near-misses)."""
        # Expired-but-unpurged candidates count: the key and point identify the premise only,
        # and the matched property's snapshot is replaced by this fresh one in the same save.
        # Purged, merging and merged documents carry no key and are never candidates.
        candidates = await self._collection.find(
            {"address_key": address_key, "snapshot_state": "current"},
            {"_id": 1, "coordinates": 1},
        ).to_list(10)
        near = [
            c["_id"]
            for c in candidates
            if distance_m(Coordinates(**c["coordinates"]), snapshot.coordinates) <= ADDRESS_MATCH_TOLERANCE_M
        ]
        if len(near) == 1:
            return near[0], []
        return None, [c["_id"] for c in candidates]

    async def _add_aliases(self, pid: str, aliases: list[str]) -> None:
        """Attach aliases to an *active* property, or raise ``_RetrySave``. Never swallows a conflict.

        - aliases already on ``pid``: nothing to do;
        - aliases owned by another active canonical property: not moved; the conflict is
          recorded explicitly on ``pid`` (``possible_duplicates``) for reconciliation;
        - the rest are added with a write conditional on ``pid`` still being active. If
          ``pid`` became a tombstone, or an alias was claimed concurrently, the caller retries
          the whole operation against the current canonical property.
        """
        owners = await self._collection.find(
            {"place_ids": {"$in": aliases}, "_id": {"$ne": pid}}, {"place_ids": 1}
        ).to_list(None)
        owned_elsewhere = {alias: doc["_id"] for doc in owners for alias in doc.get("place_ids", []) if alias in aliases}
        free = [alias for alias in aliases if alias not in owned_elsewhere]
        not_tombstone = {"merged_into": {"$exists": False}, "merging_into": {"$exists": False}}

        if free:
            try:
                result = await self._collection.update_one(
                    {"_id": pid, **not_tombstone}, {"$addToSet": {"place_ids": {"$each": free}}, **_BUMP}
                )
            except DuplicateKeyError:
                raise _RetrySave("an alias was claimed concurrently") from None
            if result.matched_count == 0:
                raise _RetrySave("target merged before the alias write")

        if owned_elsewhere:
            conflicting = sorted(set(owned_elsewhere.values()))
            logger.warning("Aliases of %s are owned by %s; recorded for reconciliation", pid, conflicting)
            result = await self._collection.update_one(
                {"_id": pid, **not_tombstone}, {"$addToSet": {"possible_duplicates": {"$each": conflicting}}, **_BUMP}
            )
            if result.matched_count == 0:
                raise _RetrySave("target merged before recording the alias conflict")

    async def _ensure_active(self, pid: str) -> None:
        doc = await self._collection.find_one({"_id": pid}, {"merged_into": 1, "merging_into": 1})
        if doc is None or _merge_target(doc):
            raise _RetrySave("target merged during the save")

    async def _canonical_doc(self, doc: dict | None) -> dict | None:
        """Follow merged_into/merging_into to the canonical (non-merged) property document."""
        seen: set[str] = set()
        while doc is not None and _merge_target(doc):
            if doc["_id"] in seen or len(seen) >= _MAX_MERGE_HOPS:
                logger.error("Merge chain from %s does not terminate", doc["_id"])
                return None
            seen.add(doc["_id"])
            doc = await self._collection.find_one({"_id": _merge_target(doc)})
        return doc

    async def _claim_premise(self, pid: str, address_key: str) -> None:
        """Let an existing property hold its premise key if nobody else does (migration, refresh)."""
        try:
            await self._collection.update_one({"_id": pid, "snapshot_state": "current"},
                                              {"$set": {"premise_key": address_key}, **_BUMP})
        except DuplicateKeyError:
            pass  # another property holds this premise; this one stays a reviewed/flagged peer

    @staticmethod
    def _document(snapshot: PropertySnapshot, address_key: str | None) -> dict:
        doc = snapshot.model_dump()
        doc["schema_version"] = SCHEMA_VERSION
        doc["snapshot_state"] = "current"
        doc["address_key"] = address_key
        # GeoJSON point (lng, lat) for 2dsphere queries, e.g. later point-in-polygon lookups.
        doc["location"] = {"type": "Point", "coordinates": [snapshot.coordinates.lng, snapshot.coordinates.lat]}
        return doc


def _unavailable(exc: PyMongoError) -> StorageUnavailableError:
    # Type only: driver messages can include hosts or connection details.
    logger.error("MongoDB operation failed: %s", type(exc).__name__)
    return StorageUnavailableError(_STORAGE_UNAVAILABLE)
