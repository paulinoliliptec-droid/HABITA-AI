from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import StorageUnavailableError
from app.main import ConfigurationError, create_app
from tests import fixtures

FRONTEND = "http://localhost:3000"


def make_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "google_maps_api_key": "test-key",
        "mongodb_uri": None,
        "app_env": "test",
        "allow_ephemeral_storage": True,
    }
    return Settings(**{**values, **overrides})


def make_client(handler, **overrides) -> TestClient:
    return TestClient(create_app(make_settings(**overrides), http_transport=httpx.MockTransport(handler)))


@pytest.fixture
def google_calls() -> list[httpx.Request]:
    return []


def google_handler(google_calls, *, partial_first: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        google_calls.append(request)
        params = request.url.params
        # One numbered premise that Google knows under two unrelated place IDs and postcodes,
        # depending on whether it was typed or picked from autocomplete.
        if "Avenida 25 de Abril 1011" in params.get("address", "") or params.get("place_id") == "ChIJ-typed":
            return httpx.Response(200, json=fixtures.cascais_premise(place_id="ChIJ-typed", postal_code="2750-515"))
        if params.get("place_id") == "ChIJ-picked":
            return httpx.Response(
                200, json=fixtures.cascais_premise(place_id="ChIJ-picked", lat=38.69714, lng=-9.42930)
            )
        if params.get("address") == "unknown place":
            return httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})
        if "Mountain View" in params.get("address", ""):
            return httpx.Response(200, json=fixtures.mountain_view())
        payload = fixtures.cascais(params["language"])
        if partial_first and "address" in params:
            payload["results"][0]["partial_match"] = True
        return httpx.Response(200, json=payload)

    return handler


@pytest.fixture
def client(google_calls):
    with make_client(google_handler(google_calls)) as c:
        yield c


def resolve(client, **body):
    return client.post("/api/property/resolve-location", json=body, headers={"Origin": FRONTEND})


def test_resolves_portuguese_address_in_official_language(client, google_calls):
    res = resolve(client, address="  Praça 5 de Outubro, Cascais ")

    assert res.status_code == 200
    body = res.json()
    assert body["property_id"].startswith("prp_")
    assert body["formatted_address"] == "Praça 5 de Outubro, 2750-642 Cascais, Portugal"
    assert body["coordinates"] == {"lat": 38.6969, "lng": -9.4215}
    assert body["precision"] == "rooftop"
    assert body["partial_match"] is False

    j = body["jurisdiction"]
    assert j["id"] == "pt/lisboa/cascais"
    assert [lvl["id"] for lvl in j["levels"]] == [
        "pt", "pt/lisboa", "pt/lisboa/cascais", "pt/lisboa/cascais/cascais-e-estoril",
    ]
    assert j["local_authority"]["id"] == "pt/lisboa/cascais:camara-municipal"
    assert j["local_authority"]["name"] == "Câmara Municipal de Cascais"
    assert (j["country"], j["region"], j["municipality"], j["city"]) == ("Portugal", "Lisboa", "Cascais", "Cascais")
    assert j["coverage"] == "modelled"

    # First lookup in the default language, then the same place re-read in Portuguese.
    assert [r.url.params["language"] for r in google_calls] == ["en", "pt"]
    assert google_calls[0].url.params["address"] == "Praça 5 de Outubro, Cascais"
    assert google_calls[1].url.params["place_id"] == fixtures.CASCAIS_PLACE_ID

    prov = body["provenance"]
    assert prov["request"] == {"address": "Praça 5 de Outubro, Cascais", "place_id": None}
    assert [(lk["by"], lk["language"]) for lk in prov["lookups"]] == [("address", "en"), ("place_id", "pt")]
    assert (prov["adapter"], prov["adapter_version"]) == ("PT", 2)
    resolved_at = datetime.fromisoformat(body["resolved_at"])
    assert datetime.fromisoformat(body["expires_at"]) - resolved_at == timedelta(days=30)


def test_jurisdiction_ids_are_stable_across_request_language(client):
    # The first lookup returns "Lisbon" (en); IDs and names come from the Portuguese re-read.
    j = resolve(client, address="Praça 5 de Outubro, Cascais").json()["jurisdiction"]
    assert j["levels"][1] == {"type": "region", "id": "pt/lisboa", "name": "Lisboa", "label": "District"}


def test_partial_match_from_original_request_survives_official_language_reread(google_calls):
    with make_client(google_handler(google_calls, partial_first=True)) as c:
        body = resolve(c, address="Praca 5 Outubro Cascias").json()
    assert body["partial_match"] is True
    assert [lk["partial_match"] for lk in body["provenance"]["lookups"]] == [True, False]


def test_match_quality_is_request_scoped_and_never_stored(google_calls):
    """Codex re-verification CX-1: a later exact request must not rewrite an earlier user's warning."""
    with make_client(google_handler(google_calls, partial_first=True)) as c:
        first = resolve(c, address="Praca 5 Outubro Cascias").json()
        second = resolve(c, place_id=fixtures.CASCAIS_PLACE_ID).json()
        fetched = c.get(f"/api/property/{first['property_id']}").json()
    assert (first["partial_match"], second["partial_match"]) == (True, False)
    assert second["property_id"] == first["property_id"]
    # A property read carries no request-scoped flag at all; the first user's
    # warning travels with their navigation (see frontend ?match=partial).
    assert "partial_match" not in fetched


def test_generic_country_needs_single_lookup(client, google_calls):
    res = resolve(client, address="1600 Amphitheatre Pkwy, Mountain View")
    assert res.status_code == 200
    j = res.json()["jurisdiction"]
    assert j["local_authority"] is None
    assert j["municipality"] is None
    assert j["coverage"] == "unmodelled"
    assert len(google_calls) == 1


def test_same_place_by_address_or_place_id_is_one_property(client, google_calls):
    first = resolve(client, address="Praça 5 de Outubro, Cascais").json()
    again = resolve(client, place_id=fixtures.CASCAIS_PLACE_ID).json()
    assert first["property_id"] == again["property_id"]

    fetched = client.get(f"/api/property/{first['property_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["jurisdiction"]["local_authority"]["name"] == "Câmara Municipal de Cascais"


def test_typed_and_autocomplete_entries_of_one_premise_are_one_property(client, google_calls):
    """Codex re-verification CX-2: unrelated place IDs for the same building reconcile by address."""
    typed = resolve(client, address="Avenida 25 de Abril 1011, Cascais").json()
    picked = resolve(client, place_id="ChIJ-picked").json()

    assert picked["property_id"] == typed["property_id"]
    assert picked["provenance"]["identity"] == "address"
    assert typed["provenance"]["identity"] == "new"


def test_get_refreshes_expired_snapshot_into_same_property(google_calls):
    with make_client(google_handler(google_calls), provider_snapshot_ttl_days=0) as c:
        created = resolve(c, address="Praça 5 de Outubro, Cascais").json()
        calls_before = len(google_calls)
        refreshed = c.get(f"/api/property/{created['property_id']}").json()
    assert refreshed["property_id"] == created["property_id"]
    assert refreshed["resolved_at"] > created["resolved_at"]
    assert len(google_calls) > calls_before
    assert refreshed["provenance"]["request"] == {"address": None, "place_id": fixtures.CASCAIS_PLACE_ID}


def test_unknown_property_is_404(client):
    res = client.get("/api/property/prp_0000000000000000")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("body", [{}, {"address": "  "}, {"address": "ab"}, {"address": "x" * 301}])
def test_invalid_requests_are_422(client, body):
    res = client.post("/api/property/resolve-location", json=body)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


def test_address_not_found(client):
    res = resolve(client, address="unknown place")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "address_not_found"


def test_missing_server_key_is_503():
    with make_client(lambda _: httpx.Response(500), google_maps_api_key=None) as c:
        res = resolve(c, address="Praça 5 de Outubro, Cascais")
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "service_not_configured"


def test_rate_limit_returns_structured_429_with_retry_after(google_calls):
    with make_client(google_handler(google_calls), resolve_burst=2, resolve_rate_per_minute=1) as c:
        statuses = [resolve(c, address="Praça 5 de Outubro, Cascais").status_code for _ in range(3)]
        limited = resolve(c, address="Praça 5 de Outubro, Cascais")
    assert statuses == [200, 200, 429]
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) > 0
    assert limited.headers["access-control-allow-origin"] == FRONTEND
    assert len(google_calls) == 4  # two admitted PT resolutions × two lookups; rejected ones cost nothing


def test_storage_outage_is_structured_503_with_cors(client, monkeypatch):
    async def failing_save(*args, **kwargs):
        raise StorageUnavailableError("HABITA can't reach its property store right now. Please try again shortly.")

    monkeypatch.setattr(client.app.state.repository, "save", failing_save)
    res = resolve(client, address="Praça 5 de Outubro, Cascais")
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "storage_unavailable"
    assert res.headers["access-control-allow-origin"] == FRONTEND


def test_unexpected_error_keeps_envelope_and_cors(client, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("secret-bearing detail mongodb+srv://user:pw@host")

    monkeypatch.setattr(client.app.state.repository, "save", boom)
    res = resolve(client, address="Praça 5 de Outubro, Cascais")
    assert res.status_code == 500
    assert res.json()["error"]["code"] == "internal_error"
    assert "mongodb" not in res.text
    assert res.headers["access-control-allow-origin"] == FRONTEND


@pytest.mark.parametrize("env", ["production", "preview", "development"])
def test_without_mongo_or_explicit_opt_in_refuses_to_start(env):
    # Not even the default APP_ENV may fall back to memory without the explicit opt-in.
    with pytest.raises(ConfigurationError):
        with make_client(lambda _: httpx.Response(500), app_env=env, allow_ephemeral_storage=False):
            pass


def test_health_and_readiness(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready"}



def test_maintenance_endpoint_is_disabled_without_a_token(client):
    assert client.post("/internal/maintenance/run").status_code == 404


def test_maintenance_endpoint_requires_the_token(google_calls):
    with make_client(google_handler(google_calls), maintenance_token="s3cret-token") as c:
        assert c.post("/internal/maintenance/run").status_code == 401
        assert c.post("/internal/maintenance/run", headers={"X-Maintenance-Token": "wrong"}).status_code == 401
        ok = c.post("/internal/maintenance/run", headers={"X-Maintenance-Token": "s3cret-token"})
    assert ok.status_code == 200
    assert ok.json() == {"purged": 0, "merges_resumed": 0}
