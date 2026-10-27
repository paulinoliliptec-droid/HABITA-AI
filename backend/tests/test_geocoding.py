import json

import httpx
import pytest

from app.core.errors import AddressNotFoundError, ServiceNotConfiguredError, UpstreamServiceError
from app.integrations.maps.geocoding import GeocodingClient
from tests import fixtures

SECRET = "test-key-should-never-leak"


def client_with(handler) -> GeocodingClient:
    return GeocodingClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), SECRET)


async def test_parses_first_result_and_sends_params():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=fixtures.cascais())

    loc = await client_with(handler).geocode(address="Praça 5 de Outubro, Cascais", language="pt")

    assert loc.place_id == fixtures.CASCAIS_PLACE_ID
    assert loc.country_code == "PT"
    assert loc.location_type == "ROOFTOP"
    assert seen[0].url.params["address"] == "Praça 5 de Outubro, Cascais"
    assert seen[0].url.params["language"] == "pt"
    assert seen[0].url.params["key"] == SECRET


async def test_zero_results_is_address_not_found():
    client = client_with(lambda _: httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []}))
    with pytest.raises(AddressNotFoundError):
        await client.geocode(address="nowhere at all", language="en")


async def test_request_denied_is_upstream_error_without_leaking_key(caplog):
    payload = {"status": "REQUEST_DENIED", "error_message": "The provided API key is invalid."}
    client = client_with(lambda _: httpx.Response(200, json=payload))
    with pytest.raises(UpstreamServiceError) as exc:
        await client.geocode(address="Cascais", language="en")
    assert SECRET not in exc.value.message
    assert SECRET not in caplog.text


async def test_retries_once_on_server_error():
    responses = iter([httpx.Response(503), httpx.Response(200, json=fixtures.porto())])
    loc = await client_with(lambda _: next(responses)).geocode(address="Porto", language="pt")
    assert loc.formatted_address.startswith("Av. dos Aliados")


async def test_transport_failure_is_upstream_error(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    with pytest.raises(UpstreamServiceError):
        await client_with(handler).geocode(address="Porto", language="pt")
    assert SECRET not in caplog.text


async def test_missing_key_is_not_configured():
    client = GeocodingClient(httpx.AsyncClient(), None)
    with pytest.raises(ServiceNotConfiguredError):
        await client.geocode(address="Porto", language="pt")


def _with_result(**overrides) -> dict:
    payload = fixtures.cascais()
    result = payload["results"][0]
    for key, value in overrides.items():
        if key in ("lat", "lng"):
            result["geometry"]["location"][key] = value
        elif value is None:
            result.pop(key)
        else:
            result[key] = value
    return payload


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"<html>not json</html>"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"status": "OK", "results": "nope"}),
        httpx.Response(200, json=_with_result(geometry=None)),
        httpx.Response(200, json=_with_result(place_id="")),
        httpx.Response(200, json=_with_result(lat="north")),
        httpx.Response(200, json=_with_result(lat=91)),
        httpx.Response(200, json=_with_result(lng=-181)),
        httpx.Response(200, content=json.dumps(_with_result(lat=float("nan"))).encode()),
    ],
    ids=["non-json", "wrong-envelope", "results-not-list", "no-geometry", "empty-place-id",
         "non-numeric", "lat-out-of-range", "lng-out-of-range", "nan"],
)
async def test_malformed_upstream_results_are_upstream_errors(response):
    with pytest.raises(UpstreamServiceError):
        await client_with(lambda _: response).geocode(address="Cascais", language="pt")
