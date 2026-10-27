"""Live end-to-end smoke test against real Google Maps Platform and MongoDB Atlas.

Opt-in: runs only with HABITA_LIVE_TESTS=1 and real credentials in the environment
(GOOGLE_MAPS_API_KEY, MONGODB_URI, and NEXT_PUBLIC_GOOGLE_MAPS_API_KEY for the
autocomplete step). It writes one real Cascais property into `properties`;
re-running reuses it through its place-ID aliases.
"""

import asyncio
import os
import secrets
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pymongo import AsyncMongoClient, MongoClient

from app.core.config import Settings
from app.db.property_repository import GOOGLE_DERIVED_FIELDS, SCHEMA_VERSION, MongoPropertyRepository
from app.integrations.maps.geocoding import GeocodingClient
from app.main import create_app
from app.services.jurisdiction import JurisdictionResolver
from app.services.property_location import PropertyLocationService

pytestmark = pytest.mark.skipif(os.getenv("HABITA_LIVE_TESTS") != "1", reason="live test: set HABITA_LIVE_TESTS=1")

CASCAIS_QUERY = "Avenida 25 de Abril 1011, Cascais"


def live_settings() -> Settings:
    settings = Settings(app_env="test")
    assert settings.google_maps_api_key and settings.mongodb_uri, "live credentials missing"
    return settings


def autocomplete_place_id(query: str) -> str:
    """Places API (New) autocomplete with the browser key, as the frontend does."""
    key = os.environ["NEXT_PUBLIC_GOOGLE_MAPS_API_KEY"]
    res = httpx.post(
        "https://places.googleapis.com/v1/places:autocomplete",
        headers={"X-Goog-Api-Key": key, "Referer": "http://localhost:3000/"},
        json={"input": query},
        timeout=10,
    )
    res.raise_for_status()
    suggestions = res.json()["suggestions"]
    assert suggestions, "autocomplete returned no suggestions"
    return suggestions[0]["placePrediction"]["placeId"]


def test_cascais_address_resolves_persists_and_reloads():
    settings = live_settings()
    place_id = autocomplete_place_id(CASCAIS_QUERY)

    with TestClient(create_app(settings)) as client:
        res = client.post("/api/property/resolve-location", json={"place_id": place_id})
        assert res.status_code == 200, res.text
        prop = res.json()
        assert client.get("/health/ready").json() == {"status": "ready"}

    j = prop["jurisdiction"]
    assert j["id"] == "pt/lisboa/cascais"
    assert [lvl["type"] for lvl in j["levels"]][:3] == ["country", "region", "municipality"]
    assert j["local_authority"]["id"] == "pt/lisboa/cascais:camara-municipal"
    assert j["local_authority"]["name"] == "Câmara Municipal de Cascais"
    assert "Cascais" in prop["formatted_address"]

    # Stored in Atlas as a v1 document with aliases and the GeoJSON point used by the 2dsphere index.
    mongo = MongoClient(settings.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=8000)
    try:
        collection = mongo[settings.mongodb_db_name]["properties"]
        doc = collection.find_one({"_id": prop["property_id"]})
        indexes = {ix["name"]: ix for ix in collection.list_indexes()}
    finally:
        mongo.close()
    assert doc["schema_version"] == SCHEMA_VERSION
    assert place_id in doc["place_ids"]
    assert doc["location"]["coordinates"] == [prop["coordinates"]["lng"], prop["coordinates"]["lat"]]
    assert indexes["place_ids_1"]["unique"] is True
    assert not indexes["place_id_1"].get("unique")

    # A fresh app instance (no in-process state) reads it back from MongoDB.
    with TestClient(create_app(settings)) as client:
        fetched = client.get(f"/api/property/{prop['property_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["property_id"] == prop["property_id"]


def test_concurrent_resolutions_of_one_place_converge_in_atlas():
    settings = live_settings()
    place_id = autocomplete_place_id(CASCAIS_QUERY)

    async def run() -> list[str]:
        mongo = AsyncMongoClient(settings.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=8000, tz_aware=True)
        try:
            repo = MongoPropertyRepository(mongo, settings.mongodb_db_name)
            await repo.ensure_indexes()
            async with httpx.AsyncClient(timeout=10) as http:
                service = PropertyLocationService(
                    geocoder=GeocodingClient(http, settings.google_maps_api_key.get_secret_value()),
                    resolver=JurisdictionResolver(),
                    repository=repo,
                    default_language="en",
                    snapshot_ttl=timedelta(days=30),
                )
                results = await asyncio.gather(*(service.resolve(address=None, place_id=place_id) for _ in range(3)))
            return [r.property_id for r in results]
        finally:
            await mongo.close()

    ids = asyncio.run(run())
    assert len(set(ids)) == 1, ids


def test_typed_and_autocomplete_entries_reconcile_to_one_property():
    """The duplicate observed live in HR-001: free text and autocomplete returned unrelated IDs."""
    settings = live_settings()
    place_id = autocomplete_place_id(CASCAIS_QUERY)
    with TestClient(create_app(settings)) as client:
        picked = client.post("/api/property/resolve-location", json={"place_id": place_id}).json()
        typed = client.post("/api/property/resolve-location", json={"address": CASCAIS_QUERY}).json()
    assert typed["property_id"] == picked["property_id"], (picked["provenance"], typed["provenance"])
    assert typed["provenance"]["identity"] in ("alias", "address")


def test_purge_expired_on_atlas_keeps_identity():
    settings = live_settings()
    pid = "prp_" + secrets.token_hex(8)
    alias = f"HABITA_TEST_{pid}"
    past = datetime.now(UTC) - timedelta(days=40)

    async def run() -> tuple[int, dict]:
        mongo = AsyncMongoClient(settings.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=8000, tz_aware=True)
        collection = mongo[settings.mongodb_db_name]["properties"]
        try:
            await collection.insert_one({
                "_id": pid, "place_id": alias, "place_ids": [alias], "schema_version": SCHEMA_VERSION,
                "snapshot_state": "current", "formatted_address": "test", "coordinates": {"lat": 0, "lng": 0},
                "location": {"type": "Point", "coordinates": [0, 0]}, "precision": "rooftop", "jurisdiction": {},
                "address_key": None, "resolved_at": past, "expires_at": past + timedelta(days=30), "created_at": past,
            })
            purged = await MongoPropertyRepository(mongo, settings.mongodb_db_name).purge_expired()
            return purged, await collection.find_one({"_id": pid})
        finally:
            await collection.delete_one({"_id": pid})
            await mongo.close()

    purged, doc = asyncio.run(run())
    assert purged >= 1
    assert doc["snapshot_state"] == "purged"
    assert not set(GOOGLE_DERIVED_FIELDS) & doc.keys()
    assert (doc["place_ids"], doc["created_at"].year) == ([alias], past.year)


def _test_snapshot(tag: str, lat: float, lng: float, resolved_at: datetime):
    from app.schemas.property import Coordinates, JurisdictionOut, PropertySnapshot, Provenance, ResolutionRequestRecord

    return PropertySnapshot(
        formatted_address=f"HABITA live test {tag}",
        coordinates=Coordinates(lat=lat, lng=lng),
        precision="rooftop",
        place_id=f"HABITA_TEST_{tag}",
        jurisdiction=JurisdictionOut(
            id="test/live", country_code="PT", levels=[], local_authority=None, coverage="modelled",
            country="Portugal", region=None, municipality=None, city=None,
        ),
        provenance=Provenance(request=ResolutionRequestRecord(), lookups=[], adapter="test", adapter_version=1),
        resolved_at=resolved_at,
        expires_at=resolved_at + timedelta(days=30),
    )


def _with_repo(fn):
    settings = live_settings()

    async def run():
        mongo = AsyncMongoClient(settings.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=8000, tz_aware=True)
        repo = MongoPropertyRepository(mongo, settings.mongodb_db_name)
        collection = mongo[settings.mongodb_db_name]["properties"]
        await repo.ensure_indexes()
        run_id = secrets.token_hex(4)
        try:
            return await fn(repo, collection, run_id)
        finally:
            await collection.delete_many({"place_id": {"$regex": f"^HABITA_TEST_{run_id}"}})
            await collection.delete_many({"merged_aliases": {"$regex": f"^HABITA_TEST_{run_id}"}})
            await mongo.close()

    return asyncio.run(run())


def test_concurrent_unrelated_ids_for_one_premise_converge_on_atlas():
    """Codex final verification CX-2, against the real unique premise_key index."""

    async def scenario(repo, collection, run_id):
        key = f"test/live|premise-{run_id}|1|"
        now = datetime.now(UTC)
        results = await asyncio.gather(*(
            repo.save(_test_snapshot(f"{run_id}_{i}", 38.69712 + i * 0.00001, -9.42932, now), {f"HABITA_TEST_{run_id}_{i}"}, address_key=key)
            for i in range(3)
        ))
        docs = await collection.find({"place_id": {"$regex": f"^HABITA_TEST_{run_id}"}}).to_list(None)
        return {r.property_id for r in results}, docs

    ids, docs = _with_repo(scenario)
    assert len(ids) == 1, ids
    assert len(docs) == 1 and len(docs[0]["place_ids"]) == 3


def test_interrupted_merge_recovers_on_atlas():
    """Merge regression: stop after step 1, then resume against the real alias index."""

    async def scenario(repo, collection, run_id):
        now = datetime.now(UTC)
        keep = await repo.save(_test_snapshot(f"{run_id}_keep", 1.0, 1.0, now), {f"HABITA_TEST_{run_id}_keep"})
        dup = await repo.save(_test_snapshot(f"{run_id}_dup", 2.0, 2.0, now), {f"HABITA_TEST_{run_id}_dup"})
        # Reproduce the state a failure after step 1 leaves behind.
        dup_doc = await collection.find_one({"_id": dup.property_id})
        await collection.update_one(
            {"_id": dup.property_id},
            {"$set": {"merging_into": keep.property_id, "snapshot_state": "merging",
                      "merged_aliases": dup_doc["place_ids"]}, "$unset": {"place_ids": ""}},
        )
        during = (await repo.get(dup.property_id)).property_id
        owner = await repo._owner_of(f"HABITA_TEST_{run_id}_dup", [f"HABITA_TEST_{run_id}_dup"])
        await repo.merge(keep=keep.property_id, duplicate=dup.property_id)
        await repo.merge(keep=keep.property_id, duplicate=dup.property_id)  # idempotent
        return keep.property_id, during, owner, await collection.find_one({"_id": keep.property_id}), await collection.find_one({"_id": dup.property_id})

    keep_id, during, owner, keep_doc, tomb = _with_repo(scenario)
    assert during == owner == keep_id
    assert sorted(keep_doc["place_ids"]) == sorted([keep_doc["place_id"], tomb["merged_aliases"][0]])
    assert (tomb["merged_into"], tomb["snapshot_state"]) == (keep_id, "merged")
    assert "place_ids" not in tomb


def test_chained_merge_resolves_and_never_revives_on_atlas():
    """Codex CX-2-M1: A → B, then B → C; A's link, alias and refresh must reach C on the real store."""

    async def scenario(repo, collection, run_id):
        now = datetime.now(UTC)
        ids = {}
        for n, lat in (("A", 1.0), ("B", 2.0), ("C", 3.0)):
            ids[n] = (await repo.save(_test_snapshot(f"{run_id}_{n}", lat, lat, now), {f"HABITA_TEST_{run_id}_{n}"})).property_id
        await repo.merge(keep=ids["B"], duplicate=ids["A"])
        await repo.merge(keep=ids["C"], duplicate=ids["B"])
        got = (await repo.get(ids["A"])).property_id
        owner = await repo._owner_of(f"HABITA_TEST_{run_id}_A", [f"HABITA_TEST_{run_id}_A"])
        refreshed = await repo.save(
            _test_snapshot(f"{run_id}_A", 1.0, 1.0, now + timedelta(seconds=1)), {f"HABITA_TEST_{run_id}_A"}, property_id=ids["A"]
        )
        states = {n: (await collection.find_one({"_id": i}))["snapshot_state"] for n, i in ids.items()}
        c_doc = await collection.find_one({"_id": ids["C"]})
        return ids, got, owner, refreshed.property_id, states, c_doc

    ids, got, owner, refreshed, states, c_doc = _with_repo(scenario)
    assert got == owner == refreshed == ids["C"]
    assert states == {"A": "merged", "B": "merged", "C": "current"}
    assert len(c_doc["place_ids"]) == 3


def test_concurrent_saves_during_chained_merge_converge_on_atlas():
    """Codex final regression: saves against B racing B → C (after A → B) on the real store."""

    async def scenario(repo, collection, run_id):
        now = datetime.now(UTC)
        tag = lambda n: f"HABITA_TEST_{run_id}_{n}"  # noqa: E731
        ids = {}
        for n, lat in (("A", 1.0), ("B", 2.0), ("C", 3.0)):
            ids[n] = (await repo.save(_test_snapshot(f"{run_id}_{n}", lat, lat, now), {tag(n)})).property_id
        await repo.merge(keep=ids["B"], duplicate=ids["A"])
        saves = [
            repo.save(
                _test_snapshot(f"{run_id}_B", 2.0, 2.0, now + timedelta(seconds=i + 1)),
                {tag("B"), tag(f"NEW{i}")},
                property_id=ids["B"] if i % 2 else None,
            )
            for i in range(4)
        ]
        results = await asyncio.gather(saves[0], saves[1], repo.merge(keep=ids["C"], duplicate=ids["B"]), saves[2], saves[3])
        owners = {n: await repo._owner_of(tag(n), [tag(n)]) for n in ["A", "B", "C"] + [f"NEW{i}" for i in range(4)]}
        returned = [r.property_id for r in results if r is not None]
        # A save that completed before the merge began correctly returned B (then canonical);
        # every returned link must resolve to the final canonical property C.
        resolved = {(await repo.get(pid)).property_id for pid in returned}
        c_doc = await collection.find_one({"_id": ids["C"]})
        b_doc = await collection.find_one({"_id": ids["B"]})
        return ids, set(returned), resolved, owners, c_doc, b_doc

    ids, returned, resolved, owners, c_doc, b_doc = _with_repo(scenario)
    assert returned <= {ids["B"], ids["C"]}
    assert resolved == {ids["C"]}
    assert set(owners.values()) == {ids["C"]}
    assert len(c_doc["place_ids"]) == 7
    assert b_doc["snapshot_state"] == "merged" and "place_ids" not in b_doc
