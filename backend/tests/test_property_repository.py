"""MongoPropertyRepository semantics against an in-process collection double.

The double implements exactly the query/update operators the repository uses,
including the unique multikey index on ``place_ids``. Real index behaviour is
covered by the live Atlas tests (tests/test_live_smoke.py).
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pymongo.errors import AutoReconnect, DuplicateKeyError

from app.core.errors import StorageUnavailableError
from app.db.property_repository import (
    GOOGLE_DERIVED_FIELDS,
    SCHEMA_VERSION,
    InMemoryPropertyRepository,
    MongoPropertyRepository,
    distance_m,
)
from app.schemas.property import (
    Coordinates,
    JurisdictionOut,
    PropertySnapshot,
    Provenance,
    ResolutionRequestRecord,
)

T0 = datetime(2026, 10, 27, 10, tzinfo=UTC)
KEY = "pt/lisboa/cascais|avenida-25-de-abril|1011|"


def _matches(doc: dict, flt: dict) -> bool:
    for key, cond in flt.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
            continue
        value = doc.get(key)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$in":
                    ok = any(v in arg for v in value) if isinstance(value, list) else value in arg
                elif op == "$lt":
                    ok = value is not None and value < arg
                elif op == "$lte":
                    ok = value is not None and value <= arg
                elif op == "$gt":
                    ok = value is not None and value > arg
                elif op == "$ne":
                    ok = value != arg
                elif op == "$exists":
                    ok = (key in doc) == arg
                else:
                    raise NotImplementedError(op)
                if not ok:
                    return False
        elif isinstance(value, list) and not isinstance(cond, list):
            if cond not in value:  # MongoDB: equality on an array field matches an element
                return False
        elif value != cond:
            return False
    return True


class Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length=None):
        return self._docs if length is None else self._docs[:length]


class FakeCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    def _check_aliases(self, doc_id: str, aliases) -> None:
        # Like MongoDB's unique multikey index: an empty array is indexed as a null key,
        # so two documents with `place_ids: []` collide (missing fields are excluded by the
        # partial filter).
        if aliases is None:
            return
        for other_id, other in self.docs.items():
            if other_id == doc_id or "place_ids" not in other:
                continue
            if set(other["place_ids"]) & set(aliases) or (not aliases and not other["place_ids"]):
                raise DuplicateKeyError("E11000 duplicate key: place_ids")

    def _check_premise(self, doc_id: str, premise_key) -> None:
        # Unique partial index on string premise_key values.
        if isinstance(premise_key, str) and any(
            other_id != doc_id and other.get("premise_key") == premise_key for other_id, other in self.docs.items()
        ):
            raise DuplicateKeyError("E11000 duplicate key: premise_key")

    async def find_one(self, flt: dict, projection=None, sort=None):
        found = [d for d in self.docs.values() if _matches(d, flt)]
        if sort:
            field, _ = sort[0]
            found.sort(key=lambda d: d.get(field))
        return dict(found[0]) if found else None

    def find(self, flt: dict, projection=None) -> Cursor:
        return Cursor([dict(d) for d in self.docs.values() if _matches(d, flt)])

    async def insert_one(self, doc: dict) -> None:
        if doc["_id"] in self.docs:
            raise DuplicateKeyError("E11000 duplicate key: _id")
        self._check_aliases(doc["_id"], doc.get("place_ids"))
        self._check_premise(doc["_id"], doc.get("premise_key"))
        self.docs[doc["_id"]] = dict(doc)

    def _apply(self, target: dict, update: dict) -> dict:
        new = {**target, **update.get("$set", {})}
        for field in update.get("$unset", {}):
            new.pop(field, None)
        for field, value in update.get("$pull", {}).items():
            new[field] = [v for v in new.get(field, []) if v != value]
        for field, step in update.get("$inc", {}).items():
            new[field] = new.get(field, 0) + step
        for field, spec in update.get("$addToSet", {}).items():
            new[field] = list(dict.fromkeys([*new.get(field, []), *spec["$each"]]))
        self._check_aliases(target["_id"], new.get("place_ids"))
        self._check_premise(target["_id"], new.get("premise_key"))
        return new

    async def update_one(self, flt: dict, update: dict):
        target = next((d for d in self.docs.values() if _matches(d, flt)), None)
        if target is None:
            return SimpleNamespace(matched_count=0, modified_count=0)
        self.docs[target["_id"]] = self._apply(target, update)
        return SimpleNamespace(matched_count=1, modified_count=1)

    async def update_many(self, flt: dict, update: dict):
        targets = [d for d in self.docs.values() if _matches(d, flt)]
        for target in targets:
            self.docs[target["_id"]] = self._apply(target, update)
        return SimpleNamespace(matched_count=len(targets), modified_count=len(targets))


def make_repo(collection=None) -> tuple[MongoPropertyRepository, FakeCollection]:
    collection = collection or FakeCollection()
    repo = MongoPropertyRepository.__new__(MongoPropertyRepository)
    repo._collection = collection  # type: ignore[assignment]
    return repo, collection


def snapshot(
    resolved_at: datetime = T0,
    place_id: str = "ChIJ-a",
    address: str = "Av. 25 de Abril 1011, Cascais",
    lat: float = 38.69712,
    lng: float = -9.42932,
) -> PropertySnapshot:
    return PropertySnapshot(
        formatted_address=address,
        coordinates=Coordinates(lat=lat, lng=lng),
        precision="rooftop",
        place_id=place_id,
        jurisdiction=JurisdictionOut(
            id="pt/lisboa/cascais",
            country_code="PT",
            levels=[],
            local_authority=None,
            coverage="modelled",
            country="Portugal",
            region="Lisboa",
            municipality="Cascais",
            city="Cascais",
        ),
        provenance=Provenance(request=ResolutionRequestRecord(address=address), lookups=[], adapter="PT", adapter_version=2),
        resolved_at=resolved_at,
        expires_at=resolved_at + timedelta(days=30),
    )


# --- identity -------------------------------------------------------------------------


async def test_insert_stores_current_document_with_generated_id_and_aliases():
    repo, col = make_repo()
    prop = await repo.save(snapshot(), {"ChIJ-a", "ChIJ-b"}, address_key=KEY)

    assert prop.property_id.startswith("prp_") and len(prop.property_id) == 20
    assert prop.provenance.identity == "new"
    doc = col.docs[prop.property_id]
    assert (doc["schema_version"], doc["snapshot_state"], doc["address_key"]) == (SCHEMA_VERSION, "current", KEY)
    assert sorted(doc["place_ids"]) == ["ChIJ-a", "ChIJ-b"]
    assert doc["location"] == {"type": "Point", "coordinates": [-9.42932, 38.69712]}
    assert doc["created_at"] == T0
    assert "partial_match" not in doc
    assert (await repo.get(prop.property_id)).snapshot == prop


async def test_any_known_alias_resolves_to_the_same_property():
    repo, col = make_repo()
    first = await repo.save(snapshot(), {"ChIJ-a", "ChIJ-b"})
    second = await repo.save(snapshot(T0 + timedelta(hours=1), place_id="ChIJ-c"), {"ChIJ-b", "ChIJ-c"})

    assert second.property_id == first.property_id
    assert second.provenance.identity == "alias"
    assert len(col.docs) == 1
    assert sorted(col.docs[first.property_id]["place_ids"]) == ["ChIJ-a", "ChIJ-b", "ChIJ-c"]
    assert col.docs[first.property_id]["created_at"] == T0


async def test_unrelated_place_ids_for_the_same_premise_reconcile_by_address():
    # Free text and autocomplete returned unrelated IDs (and postcodes) for one building, 3 m apart.
    repo, col = make_repo()
    typed = await repo.save(snapshot(place_id="ChIJ-typed"), {"ChIJ-typed"}, address_key=KEY)
    picked = await repo.save(
        snapshot(T0 + timedelta(minutes=5), place_id="ChIJ-picked", lat=38.69714, lng=-9.42930),
        {"ChIJ-picked"},
        address_key=KEY,
    )
    assert picked.property_id == typed.property_id
    assert picked.provenance.identity == "address"
    assert len(col.docs) == 1
    assert sorted(col.docs[typed.property_id]["place_ids"]) == ["ChIJ-picked", "ChIJ-typed"]


async def test_same_key_but_too_far_apart_is_not_merged_and_is_flagged():
    repo, col = make_repo()
    a = await repo.save(snapshot(place_id="ChIJ-a"), {"ChIJ-a"}, address_key=KEY)
    far = snapshot(place_id="ChIJ-far", lat=38.69712 + 0.001)  # ~111 m north
    assert distance_m(far.coordinates, a.coordinates) > 100
    b = await repo.save(far, {"ChIJ-far"}, address_key=KEY)

    assert b.property_id != a.property_id
    assert col.docs[b.property_id]["possible_duplicates"] == [a.property_id]


async def test_two_nearby_candidates_are_ambiguous_and_not_merged():
    repo, col = make_repo()
    for pid, alias in (("prp_aaaaaaaaaaaaaaaa", "ChIJ-1"), ("prp_bbbbbbbbbbbbbbbb", "ChIJ-2")):
        col.docs[pid] = {
            **MongoPropertyRepository._document(snapshot(place_id=alias), KEY),
            "_id": pid,
            "place_ids": [alias],
            "created_at": T0,
        }
    prop = await repo.save(snapshot(place_id="ChIJ-3"), {"ChIJ-3"}, address_key=KEY)

    assert prop.property_id not in ("prp_aaaaaaaaaaaaaaaa", "prp_bbbbbbbbbbbbbbbb")
    assert sorted(col.docs[prop.property_id]["possible_duplicates"]) == ["prp_aaaaaaaaaaaaaaaa", "prp_bbbbbbbbbbbbbbbb"]


async def test_no_address_key_never_matches_by_address():
    repo, col = make_repo()
    await repo.save(snapshot(place_id="ChIJ-a"), {"ChIJ-a"}, address_key=None)
    await repo.save(snapshot(place_id="ChIJ-b"), {"ChIJ-b"}, address_key=None)
    assert len(col.docs) == 2


async def test_expired_candidate_keeps_identity_but_its_data_is_replaced():
    # An expired, not-yet-purged property is the same premise: reuse its ID, never its data.
    repo, col = make_repo()
    old = await repo.save(snapshot(T0 - timedelta(days=40), place_id="ChIJ-old", address="stale"), {"ChIJ-old"}, address_key=KEY)
    new = await repo.save(snapshot(place_id="ChIJ-new", address="fresh"), {"ChIJ-new"}, address_key=KEY)
    assert new.property_id == old.property_id
    assert new.formatted_address == col.docs[old.property_id]["formatted_address"] == "fresh"


async def test_purged_candidate_frees_the_premise_claim():
    repo, col = make_repo()
    old = await repo.save(snapshot(T0 - timedelta(days=40), place_id="ChIJ-old"), {"ChIJ-old"}, address_key=KEY)
    await repo.purge_expired(now=T0)
    assert "premise_key" not in col.docs[old.property_id]
    new = await repo.save(snapshot(place_id="ChIJ-new"), {"ChIJ-new"}, address_key=KEY)
    assert col.docs[new.property_id]["premise_key"] == KEY


# --- ordering and convergence -------------------------------------------------------


async def test_delayed_older_write_does_not_overwrite_newer_snapshot():
    repo, col = make_repo()
    newer = await repo.save(snapshot(T0 + timedelta(hours=1), address="newer"), {"ChIJ-a"})
    result = await repo.save(snapshot(T0, address="older"), {"ChIJ-a", "ChIJ-late"})

    stored = col.docs[newer.property_id]
    assert stored["formatted_address"] == "newer"
    assert result.formatted_address == "newer"
    assert "ChIJ-late" in stored["place_ids"]  # the alias is still learned


async def test_losing_write_with_alias_owned_elsewhere_returns_the_winner():
    """Codex re-verification CX-10: an older write that loses AND carries another property's alias."""
    repo, col = make_repo()
    other = await repo.save(snapshot(place_id="ChIJ-other"), {"ChIJ-other"})
    winner = await repo.save(snapshot(T0 + timedelta(hours=1), address="winner"), {"ChIJ-a"})

    result = await repo.save(snapshot(T0, address="loser"), {"ChIJ-a", "ChIJ-other"})

    assert result.property_id == winner.property_id
    assert result.formatted_address == "winner"
    assert col.docs[winner.property_id]["place_ids"] == ["ChIJ-a"]
    assert col.docs[other.property_id]["place_ids"] == ["ChIJ-other"]
    # The conflict is explicit, not silent.
    assert col.docs[winner.property_id]["possible_duplicates"] == [other.property_id]


async def test_concurrent_first_insert_converges_on_the_winner():
    class RacingCollection(FakeCollection):
        """The owner lookup misses once, then a competing request's insert lands first."""

        def __init__(self) -> None:
            super().__init__()
            self.misses = 2  # both owner lookups (primary, aliases) of the first attempt
            self.inserts = 0

        async def find_one(self, flt, projection=None, sort=None):
            if self.misses and "$or" in flt:
                self.misses -= 1
                self.docs.setdefault(
                    "prp_aaaaaaaaaaaaaaaa",
                    {
                        **MongoPropertyRepository._document(snapshot(), None),
                        "_id": "prp_aaaaaaaaaaaaaaaa",
                        "place_ids": ["ChIJ-a"],
                        "created_at": T0,
                    },
                )
                return None
            return await super().find_one(flt, projection, sort)

        async def insert_one(self, doc):
            self.inserts += 1
            await super().insert_one(doc)

    repo, col = make_repo(RacingCollection())
    prop = await repo.save(snapshot(T0 + timedelta(minutes=1)), {"ChIJ-a"})
    assert col.inserts == 1  # our insert hit the duplicate key, and the retry attached instead
    assert prop.property_id == "prp_aaaaaaaaaaaaaaaa"
    assert prop.provenance.identity == "alias"
    assert len(col.docs) == 1


async def test_alias_owned_by_another_property_is_not_stolen():
    repo, col = make_repo()
    a = await repo.save(snapshot(place_id="ChIJ-a"), {"ChIJ-a"})
    b = await repo.save(snapshot(place_id="ChIJ-b"), {"ChIJ-b"})
    result = await repo.save(snapshot(T0 + timedelta(hours=1)), {"ChIJ-a", "ChIJ-b"})

    assert result.property_id == a.property_id
    assert col.docs[a.property_id]["place_ids"] == ["ChIJ-a"]
    assert col.docs[b.property_id]["place_ids"] == ["ChIJ-b"]
    assert col.docs[a.property_id]["possible_duplicates"] == [b.property_id]


# --- lifecycle and migration ----------------------------------------------------------


async def test_purge_removes_google_fields_but_keeps_identity_and_aliases():
    repo, col = make_repo()
    expired = await repo.save(snapshot(T0 - timedelta(days=31), place_id="ChIJ-x"), {"ChIJ-x"}, address_key=KEY)
    fresh = await repo.save(snapshot(place_id="ChIJ-y"), {"ChIJ-y"})

    assert await repo.purge_expired(now=T0) == 1
    assert await repo.purge_expired(now=T0) == 0  # idempotent

    doc = col.docs[expired.property_id]
    assert doc["snapshot_state"] == "purged"
    assert not set(GOOGLE_DERIVED_FIELDS) & doc.keys()
    assert (doc["_id"], doc["place_id"], doc["place_ids"], doc["created_at"]) == (
        expired.property_id, "ChIJ-x", ["ChIJ-x"], expired.resolved_at,
    )
    assert col.docs[fresh.property_id]["snapshot_state"] == "current"

    stored = await repo.get(expired.property_id)
    assert stored.snapshot is None and stored.place_id == "ChIJ-x"

    refreshed = await repo.save(snapshot(T0, place_id="ChIJ-x"), {"ChIJ-x"}, property_id=expired.property_id)
    assert refreshed.property_id == expired.property_id
    assert col.docs[expired.property_id]["snapshot_state"] == "current"
    assert (await repo.get(expired.property_id)).snapshot is not None


async def test_legacy_documents_are_found_by_place_id_and_upgraded_in_place():
    repo, col = make_repo()
    col.docs["prp_50847c0c8292962d"] = {
        "_id": "prp_50847c0c8292962d",
        "place_id": "ChIJ-legacy",
        "formatted_address": "old shape",
        "jurisdiction": {"country": "Portugal", "local_authority": "Câmara Municipal de Cascais"},
        "resolved_at": T0 + timedelta(days=5),  # newer than the refresh below: schema upgrade still wins
        "created_at": T0,
        "partial_match": True,  # stored by schema 1; request-scoped since schema 2
    }
    stored = await repo.get("prp_50847c0c8292962d")
    assert stored.snapshot is None and stored.place_id == "ChIJ-legacy"

    prop = await repo.save(snapshot(place_id="ChIJ-legacy"), {"ChIJ-legacy"})
    assert prop.property_id == "prp_50847c0c8292962d"
    upgraded = col.docs["prp_50847c0c8292962d"]
    assert (upgraded["schema_version"], upgraded["snapshot_state"]) == (SCHEMA_VERSION, "current")
    assert upgraded["place_ids"] == ["ChIJ-legacy"]
    assert upgraded["created_at"] == T0
    assert "partial_match" not in upgraded


async def test_driver_errors_become_storage_unavailable():
    class DownCollection(FakeCollection):
        async def find_one(self, *args, **kwargs):
            raise AutoReconnect("connection closed to habita-ai-m0-shard-00-01")

    repo, _ = make_repo(DownCollection())
    with pytest.raises(StorageUnavailableError) as exc:
        await repo.get("prp_0000000000000000")
    assert "habita-ai-m0" not in exc.value.message
    with pytest.raises(StorageUnavailableError):
        await repo.save(snapshot(), {"ChIJ-a"})


async def test_in_memory_repository_follows_the_same_rules():
    repo = InMemoryPropertyRepository()
    first = await repo.save(snapshot(T0 + timedelta(hours=1), address="newer"), {"ChIJ-a"}, address_key=KEY)
    second = await repo.save(snapshot(T0, address="older"), {"ChIJ-a", "ChIJ-b"})
    third = await repo.save(snapshot(T0 + timedelta(hours=2), place_id="ChIJ-z", lat=38.69713), {"ChIJ-z"}, address_key=KEY)
    assert first.property_id == second.property_id == third.property_id
    assert second.formatted_address == "newer"
    assert third.provenance.identity == "address"


# --- reconciliation -------------------------------------------------------------------


async def test_real_observed_pair_30m_apart_reconciles():
    # Live HR-001 data: one premise, two rooftop points from unrelated place IDs.
    repo, col = make_repo()
    a = await repo.save(snapshot(place_id="ChIJj-z7", lat=38.6969708, lng=-9.429614), {"ChIJj-z7"}, address_key=KEY)
    b = await repo.save(
        snapshot(T0 + timedelta(minutes=1), place_id="ChIJhdAU", lat=38.6971199, lng=-9.429322),
        {"ChIJhdAU"},
        address_key=KEY,
    )
    assert 30 < distance_m(a.coordinates, b.coordinates) < 31
    assert b.property_id == a.property_id and b.provenance.identity == "address"


async def test_merge_folds_a_reviewed_duplicate_and_keeps_its_link_working():
    repo, col = make_repo()
    keep = await repo.save(snapshot(place_id="ChIJ-keep"), {"ChIJ-keep"})
    dup = await repo.save(snapshot(place_id="ChIJ-dup"), {"ChIJ-dup"})

    await repo.merge(keep=keep.property_id, duplicate=dup.property_id)

    tomb = col.docs[dup.property_id]
    assert (tomb["merged_into"], tomb["snapshot_state"]) == (keep.property_id, "merged")
    assert "place_ids" not in tomb
    assert tomb["merged_aliases"] == ["ChIJ-dup"]
    assert not set(GOOGLE_DERIVED_FIELDS) & tomb.keys()
    assert sorted(col.docs[keep.property_id]["place_ids"]) == ["ChIJ-dup", "ChIJ-keep"]

    # The old link resolves to the kept property; new resolutions by either alias land there too.
    assert (await repo.get(dup.property_id)).property_id == keep.property_id
    again = await repo.save(snapshot(T0 + timedelta(hours=1), place_id="ChIJ-dup"), {"ChIJ-dup"})
    assert again.property_id == keep.property_id


async def test_merge_refuses_unsafe_requests():
    repo, _ = make_repo()
    a = await repo.save(snapshot(place_id="ChIJ-a"), {"ChIJ-a"})
    b = await repo.save(snapshot(place_id="ChIJ-b"), {"ChIJ-b"})
    for keep, dup in ((a.property_id, a.property_id), (a.property_id, "prp_0000000000000000")):
        with pytest.raises(ValueError):
            await repo.merge(keep=keep, duplicate=dup)
    await repo.merge(keep=a.property_id, duplicate=b.property_id)
    with pytest.raises(ValueError):
        await repo.merge(keep=b.property_id, duplicate=a.property_id)



# --- concurrent creation of one premise (Codex final verification, CX-2) --------------


class BarrierCollection(FakeCollection):
    """Holds every insert until `parties` requests have reached it, like simultaneous traffic."""

    def __init__(self, parties: int) -> None:
        super().__init__()
        self.barrier = asyncio.Barrier(parties)
        self.first_round = True

    async def insert_one(self, doc: dict) -> None:
        if self.first_round:
            await self.barrier.wait()
            self.first_round = False
        await super().insert_one(doc)


async def test_concurrent_unrelated_place_ids_for_one_premise_converge():
    """Codex's reproduction: same premise key, points 3 m apart, unrelated IDs, both see no candidate."""
    repo, col = make_repo(BarrierCollection(parties=2))
    typed, picked = await asyncio.gather(
        repo.save(snapshot(place_id="ChIJ-typed"), {"ChIJ-typed"}, address_key=KEY),
        repo.save(
            snapshot(T0 + timedelta(seconds=1), place_id="ChIJ-picked", lat=38.69714, lng=-9.42930),
            {"ChIJ-picked"},
            address_key=KEY,
        ),
    )
    assert typed.property_id == picked.property_id
    assert len(col.docs) == 1
    doc = next(iter(col.docs.values()))
    assert doc["premise_key"] == KEY
    assert sorted(doc["place_ids"]) == ["ChIJ-picked", "ChIJ-typed"]
    # Which request wins the race is not deterministic; convergence is.
    assert {typed.provenance.identity, picked.provenance.identity} <= {"new", "address"}


async def test_concurrent_far_apart_homonyms_both_succeed_without_merging():
    repo, col = make_repo(BarrierCollection(parties=2))
    a, b = await asyncio.gather(
        repo.save(snapshot(place_id="ChIJ-north"), {"ChIJ-north"}, address_key=KEY),
        repo.save(snapshot(place_id="ChIJ-south", lat=38.69712 - 0.01), {"ChIJ-south"}, address_key=KEY),  # ~1.1 km
    )
    assert a.property_id != b.property_id
    claimed = [d for d in col.docs.values() if d.get("premise_key") == KEY]
    flagged = [d for d in col.docs.values() if d.get("possible_duplicates")]
    assert len(claimed) == 1 and len(flagged) == 1
    assert flagged[0]["possible_duplicates"] == [claimed[0]["_id"]]


async def test_concurrent_units_in_one_building_never_merge():
    unit_a, unit_b = KEY[:-1] + "|2esq", KEY[:-1] + "|2dto"
    repo, col = make_repo(BarrierCollection(parties=3))
    a, b, building = await asyncio.gather(
        repo.save(snapshot(place_id="ChIJ-2esq"), {"ChIJ-2esq"}, address_key=unit_a),
        repo.save(snapshot(place_id="ChIJ-2dto"), {"ChIJ-2dto"}, address_key=unit_b),
        repo.save(snapshot(place_id="ChIJ-bldg"), {"ChIJ-bldg"}, address_key=KEY),
    )
    assert len({a.property_id, b.property_id, building.property_id}) == 3
    assert len(col.docs) == 3


# --- merge atomicity and recovery (Codex final verification, merge regression) --------


class FailingCollection(FakeCollection):
    """Raises a driver error on the Nth update_one call after `arm()`."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_on: int | None = None
        self.calls = 0

    def arm(self, nth: int) -> None:
        self.fail_on, self.calls = nth, 0

    async def update_one(self, flt, update):
        if self.fail_on is not None:
            self.calls += 1
            if self.calls == self.fail_on:
                self.fail_on = None
                raise AutoReconnect("injected failure")
        return await super().update_one(flt, update)


async def _two_properties(repo):
    keep = await repo.save(snapshot(place_id="ChIJ-keep"), {"ChIJ-keep"})
    dup = await repo.save(snapshot(place_id="ChIJ-dup"), {"ChIJ-dup"})
    return keep.property_id, dup.property_id


def _assert_merged(col, keep: str, dup: str) -> None:
    tomb = col.docs[dup]
    assert (tomb["merged_into"], tomb["snapshot_state"]) == (keep, "merged")
    assert "place_ids" not in tomb
    assert "merging_into" not in tomb and not set(GOOGLE_DERIVED_FIELDS) & tomb.keys()
    assert tomb["merged_aliases"] == ["ChIJ-dup"]
    assert sorted(col.docs[keep]["place_ids"]) == ["ChIJ-dup", "ChIJ-keep"]


@pytest.mark.parametrize("failing_step", [1, 2, 3], ids=["mark-pending", "attach-aliases", "finalise"])
async def test_merge_interrupted_at_any_step_stays_consistent_and_retry_converges(failing_step):
    repo, col = make_repo(FailingCollection())
    keep, dup = await _two_properties(repo)

    col.arm(failing_step + 1)  # write 1 is step 0: `keep` marked as absorbing (C2)
    with pytest.raises(StorageUnavailableError):
        await repo.merge(keep=keep, duplicate=dup)

    # Whatever state the failure left: links work and the alias is never orphaned.
    assert (await repo.get(dup)).property_id == (keep if failing_step > 1 else dup)
    owner = await repo._owner_of("ChIJ-dup", ["ChIJ-dup"])
    assert owner == (keep if failing_step > 1 else dup)
    recorded = col.docs[dup].get("merged_aliases", []) + col.docs[dup].get("place_ids", []) + col.docs[keep]["place_ids"]
    assert "ChIJ-dup" in recorded

    await repo.merge(keep=keep, duplicate=dup)  # the operator's retry
    _assert_merged(col, keep, dup)
    await repo.merge(keep=keep, duplicate=dup)  # and again: idempotent
    _assert_merged(col, keep, dup)


async def test_startup_resumes_an_interrupted_merge():
    repo, col = make_repo(FailingCollection())
    keep, dup = await _two_properties(repo)
    col.arm(3)  # step 2 (write 1 marks `keep`, C2)
    with pytest.raises(StorageUnavailableError):
        await repo.merge(keep=keep, duplicate=dup)
    assert col.docs[dup]["snapshot_state"] == "merging"

    assert await repo.resume_pending_merges() == 1
    _assert_merged(col, keep, dup)
    assert await repo.resume_pending_merges() == 0


async def test_resolution_during_an_interrupted_merge_attaches_to_the_target():
    repo, col = make_repo(FailingCollection())
    keep, dup = await _two_properties(repo)
    col.arm(3)  # step 2 (write 1 marks `keep`, C2)
    with pytest.raises(StorageUnavailableError):
        await repo.merge(keep=keep, duplicate=dup)

    prop = await repo.save(snapshot(T0 + timedelta(hours=1), place_id="ChIJ-dup"), {"ChIJ-dup"})
    assert prop.property_id == keep
    assert len([d for d in col.docs.values() if d["snapshot_state"] == "current"]) == 1


async def test_merge_into_a_different_target_is_refused():
    repo, col = make_repo()
    keep, dup = await _two_properties(repo)
    other = (await repo.save(snapshot(place_id="ChIJ-other"), {"ChIJ-other"})).property_id
    await repo.merge(keep=keep, duplicate=dup)
    with pytest.raises(ValueError):
        await repo.merge(keep=other, duplicate=dup)



async def test_two_tombstones_do_not_collide_on_the_alias_index():
    """Found live on Atlas: `place_ids: []` is a shared null key in the unique index."""
    repo, col = make_repo()
    keep, a, b = [
        (await repo.save(snapshot(place_id=f"ChIJ-{n}"), {f"ChIJ-{n}"})).property_id for n in ("keep", "a", "b")
    ]
    await repo.merge(keep=keep, duplicate=a)
    await repo.merge(keep=keep, duplicate=b)
    assert sorted(col.docs[keep]["place_ids"]) == ["ChIJ-a", "ChIJ-b", "ChIJ-keep"]


# --- chained merges (Codex final gate, CX-2-M1) ----------------------------------------


async def _three(repo):
    return [
        (await repo.save(snapshot(place_id=f"ChIJ-{n}"), {f"ChIJ-{n}"})).property_id for n in ("A", "B", "C")
    ]


def _assert_canonical(col, canonical: str, tombstones: list[str], aliases: list[str]) -> None:
    assert col.docs[canonical]["snapshot_state"] == "current"
    assert "merged_into" not in col.docs[canonical]
    assert sorted(col.docs[canonical]["place_ids"]) == sorted(aliases)
    for t in tombstones:
        assert col.docs[t]["snapshot_state"] == "merged" and "place_ids" not in col.docs[t]
    assert len([d for d in col.docs.values() if d["snapshot_state"] == "current"]) == 1


async def test_chained_merge_links_aliases_and_refresh_reach_the_canonical_property():
    """Codex reproduction: A → B, then B → C; get(A), A's alias and a refresh of A/B must reach C."""
    repo, col = make_repo()
    a, b, c = await _three(repo)
    await repo.merge(keep=b, duplicate=a)
    await repo.merge(keep=c, duplicate=b)

    assert (await repo.get(a)).property_id == c
    assert (await repo.get(b)).property_id == c
    assert await repo._owner_of("ChIJ-A", ["ChIJ-A"]) == c
    assert await repo._owner_of("ChIJ-B", ["ChIJ-B"]) == c

    # Refresh-on-read saves with the stored (old) ID: it must land on C, never revive A or B.
    for old_id in (a, b):
        refreshed = await repo.save(snapshot(T0 + timedelta(hours=1), place_id="ChIJ-A"), {"ChIJ-A"}, property_id=old_id)
        assert refreshed.property_id == c
    _assert_canonical(col, c, [a, b], ["ChIJ-A", "ChIJ-B", "ChIJ-C"])

    # A new resolution by any old alias also converges on C.
    again = await repo.save(snapshot(T0 + timedelta(hours=2), place_id="ChIJ-B"), {"ChIJ-B"})
    assert again.property_id == c
    _assert_canonical(col, c, [a, b], ["ChIJ-A", "ChIJ-B", "ChIJ-C"])


@pytest.mark.parametrize("failing_step", [1, 2, 3], ids=["mark-pending", "attach-aliases", "finalise"])
async def test_chained_merge_interrupted_then_reload_and_retry_converge(failing_step):
    """A → B → failure (during B → C) → reload of A's link → retry."""
    repo, col = make_repo(FailingCollection())
    a, b, c = await _three(repo)
    await repo.merge(keep=b, duplicate=a)

    col.arm(failing_step + 1)  # write 1 is step 0: `keep` marked as absorbing (C2)
    with pytest.raises(StorageUnavailableError):
        await repo.merge(keep=c, duplicate=b)

    # Reload of A's old link: always a live (current) property, never a tombstone.
    reloaded = await repo.get(a)
    assert reloaded.property_id == (b if failing_step == 1 else c)
    assert col.docs[reloaded.property_id]["snapshot_state"] == "current"
    # Refresh-on-read of that link must not revive anything.
    refreshed = await repo.save(snapshot(T0 + timedelta(hours=1), place_id="ChIJ-A"), {"ChIJ-A"}, property_id=a)
    assert refreshed.property_id == reloaded.property_id
    assert col.docs[a]["snapshot_state"] == "merged"
    if failing_step > 1:
        assert col.docs[b]["snapshot_state"] == "merging"
    # No alias is lost in the interrupted state.
    everywhere = [x for d in col.docs.values() for x in d.get("place_ids", []) + d.get("merged_aliases", [])]
    assert {"ChIJ-A", "ChIJ-B", "ChIJ-C"} <= set(everywhere)

    await repo.merge(keep=c, duplicate=b)  # the operator's retry
    _assert_canonical(col, c, [a, b], ["ChIJ-A", "ChIJ-B", "ChIJ-C"])
    assert (await repo.get(a)).property_id == c


async def test_pending_merge_into_a_property_blocks_merging_it_until_resumed():
    """A → B interrupted (A merging into B, B marked). B → C is refused until the pending merge completes (C2: C must
    not be bindable while A is still on its way to it); after resume, B → C lands everything on C."""
    repo, col = make_repo(FailingCollection())
    a, b, c = await _three(repo)
    col.arm(3)  # step 2 (write 1 marks `keep`, C2)
    with pytest.raises(StorageUnavailableError):
        await repo.merge(keep=b, duplicate=a)
    with pytest.raises(ValueError, match="pending merge"):
        await repo.merge(keep=c, duplicate=b)
    assert await repo.resume_pending_merges() == 1
    await repo.merge(keep=c, duplicate=b)
    _assert_canonical(col, c, [a, b], ["ChIJ-A", "ChIJ-B", "ChIJ-C"])


async def test_merging_into_a_tombstone_uses_its_canonical_property():
    repo, col = make_repo()
    a, b, c = await _three(repo)
    await repo.merge(keep=c, duplicate=b)
    await repo.merge(keep=b, duplicate=a)  # b is a tombstone now: the merge lands on c
    _assert_canonical(col, c, [a, b], ["ChIJ-A", "ChIJ-B", "ChIJ-C"])
    with pytest.raises(ValueError):
        await repo.merge(keep=b, duplicate=c)  # canonical(b) == c: refused, no cycle


async def test_write_racing_a_merge_retries_on_the_canonical_property():
    """The save picked B, then B was merged into C before the update: never revive B."""

    class MergeDuringSave(FakeCollection):
        def __init__(self) -> None:
            super().__init__()
            self.armed = False

        async def update_one(self, flt, update):
            if self.armed and "$set" in update and "formatted_address" in update["$set"]:
                self.armed = False
                await repo.merge(keep=c, duplicate=b)
            return await super().update_one(flt, update)

    repo, col = make_repo(MergeDuringSave())
    a, b, c = await _three(repo)
    col.armed = True
    result = await repo.save(snapshot(T0 + timedelta(hours=1), place_id="ChIJ-B"), {"ChIJ-B"}, property_id=b)
    assert result.property_id == c
    assert col.docs[b]["snapshot_state"] == "merged"


# --- concurrent save vs merge (Codex final regression) -------------------------------


class HookedCollection(FakeCollection):
    """Runs a one-shot callback (e.g. a merge) at a chosen point inside a save."""

    def __init__(self) -> None:
        super().__init__()
        self.hook = None  # (point, predicate, callback)

    async def _fire(self, point: str, flt: dict, update: dict | None, result) -> None:
        if self.hook and self.hook[0] == point and self.hook[1](flt, update, result):
            _, _, callback = self.hook
            self.hook = None
            await callback()

    async def find_one(self, flt, projection=None, sort=None):
        result = await super().find_one(flt, projection, sort)
        await self._fire("after-find", flt, None, result)
        return result

    async def update_one(self, flt, update):
        result = await super().update_one(flt, update)
        await self._fire("after-update", flt, update, result)
        return result


def _initial_read_of(pid):
    # The save's owner lookup (alias query) returning B.
    return lambda flt, _u, result: "$or" in flt and result is not None and result["_id"] == pid


def _snapshot_write_on(pid):
    return lambda flt, update, _r: flt.get("_id") == pid and "formatted_address" in update.get("$set", {})


def _alias_write_on(pid):
    return lambda flt, update, _r: flt.get("_id") == pid and "place_ids" in update.get("$addToSet", {})


@pytest.mark.parametrize(
    "point, predicate",
    [
        ("after-find", _initial_read_of),
        ("after-update", _snapshot_write_on),
        ("after-update", _alias_write_on),
    ],
    ids=["merge-after-initial-read", "merge-after-snapshot-write", "merge-after-alias-write"],
)
async def test_save_racing_chained_merge_returns_canonical_and_keeps_every_alias(point, predicate):
    """A → B exists; a save against B (existing + brand-new alias) is interleaved with B → C."""
    repo, col = make_repo(HookedCollection())
    a, b, c = await _three(repo)
    await repo.merge(keep=b, duplicate=a)

    col.hook = (point, predicate(b), lambda: repo.merge(keep=c, duplicate=b))
    result = await repo.save(snapshot(T0 + timedelta(hours=1), place_id="ChIJ-B"), {"ChIJ-B", "ChIJ-NEW"})
    assert col.hook is None, "the merge hook must have fired inside the save"

    assert result.property_id == c
    assert await repo._owner_of("ChIJ-B", ["ChIJ-B"]) == c
    assert await repo._owner_of("ChIJ-NEW", ["ChIJ-NEW"]) == c
    assert {"ChIJ-A", "ChIJ-B", "ChIJ-C", "ChIJ-NEW"} <= set(col.docs[c]["place_ids"])
    assert col.docs[b]["snapshot_state"] == "merged" and "place_ids" not in col.docs[b]
    assert (await repo.get(a)).property_id == c
    _assert_canonical(col, c, [a, b], ["ChIJ-A", "ChIJ-B", "ChIJ-C", "ChIJ-NEW"])

    # Retrying the same save is idempotent.
    again = await repo.save(snapshot(T0 + timedelta(hours=1), place_id="ChIJ-B"), {"ChIJ-B", "ChIJ-NEW"})
    assert again.property_id == c
    _assert_canonical(col, c, [a, b], ["ChIJ-A", "ChIJ-B", "ChIJ-C", "ChIJ-NEW"])


class YieldingCollection(FakeCollection):
    """Yields to the event loop on every operation so concurrent saves and a merge interleave."""

    async def find_one(self, *args, **kwargs):
        await asyncio.sleep(0)
        return await super().find_one(*args, **kwargs)

    async def update_one(self, *args, **kwargs):
        await asyncio.sleep(0)
        return await super().update_one(*args, **kwargs)

    async def insert_one(self, *args, **kwargs):
        await asyncio.sleep(0)
        return await super().insert_one(*args, **kwargs)


@pytest.mark.parametrize("merge_position", range(5))
async def test_many_concurrent_saves_during_a_chained_merge_converge(merge_position):
    repo, col = make_repo(YieldingCollection())
    a, b, c = await _three(repo)
    await repo.merge(keep=b, duplicate=a)

    saves = [
        repo.save(snapshot(T0 + timedelta(minutes=i + 1), place_id="ChIJ-B"), {"ChIJ-B", f"ChIJ-NEW{i}"}, property_id=b if i % 2 else None)
        for i in range(4)
    ]
    tasks = saves[:merge_position] + [repo.merge(keep=c, duplicate=b)] + saves[merge_position:]
    results = await asyncio.gather(*tasks)
    props = [r for r in results if r is not None]

    assert {p.property_id for p in props} == {c}
    expected = ["ChIJ-A", "ChIJ-B", "ChIJ-C"] + [f"ChIJ-NEW{i}" for i in range(4)]
    _assert_canonical(col, c, [a, b], expected)
    for alias in expected:
        assert await repo._owner_of(alias, [alias]) == c


async def test_merge_interrupted_after_marking_keep_converges_and_clears_the_mark():
    """C2: the kept property is marked first; an interruption there leaves it without identity (fail-closed for a
    VERIFIED commit) until the merge is re-run, which converges and clears the mark."""
    repo, col = make_repo(FailingCollection())
    keep, dup = await _two_properties(repo)
    col.arm(2)  # write 1 marks keep; write 2 (marking the duplicate) fails
    with pytest.raises(StorageUnavailableError):
        await repo.merge(keep=keep, duplicate=dup)
    assert col.docs[keep]["absorbing"] == [dup] and await repo.identity(keep) is None
    await repo.merge(keep=keep, duplicate=dup)
    _assert_merged(col, keep, dup)
    assert not col.docs[keep].get("absorbing") and await repo.identity(keep) is not None


async def test_startup_resumes_a_merge_interrupted_right_after_marking_keep():
    """Codex binding review round 3 (P2): the kept property is not left unbindable after a restart."""
    repo, col = make_repo(FailingCollection())
    keep, dup = await _two_properties(repo)
    col.arm(2)
    with pytest.raises(StorageUnavailableError):
        await repo.merge(keep=keep, duplicate=dup)
    assert await repo.identity(keep) is None
    assert await repo.resume_pending_merges() == 1
    _assert_merged(col, keep, dup)
    assert await repo.identity(keep) is not None and await repo.resume_pending_merges() == 0
