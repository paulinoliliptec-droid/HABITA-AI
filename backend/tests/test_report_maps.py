"""HR-006 location maps: two embedded images (road map, satellite) with the same framing, an approximate-location
legend instead of any boundary, a controlled notice when the map service is missing or fails, and no key in the PDF."""

import io
import logging
from datetime import date
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from pypdf import PdfReader

from app.core.config import Settings
from app.integrations.maps.static_maps import FRAMING, StaticMapClient, circle_polyline, map_params
from app.main import create_app
from tests.permit_fakes import ScriptedModel, google_handler
from tests.test_permit_official_sources import auth, ingest_regulamento, run_matter

KEY = "STATIC-KEY-must-never-appear"


def jpeg(colour: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (64, 40), colour).save(buf, "JPEG")
    return buf.getvalue()


class MapService:
    """Google stand-in: Static API requests get a JPEG (or a configured failure); everything else is geocoding."""

    def __init__(self, failure: str | None = None):
        self.requests: list[dict[str, str]] = []
        self.failure = failure

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/staticmap"):
            params = {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}
            self.requests.append(params)
            if self.failure == "denied":
                return httpx.Response(403, text="This API project is not authorized to use this API.")
            if self.failure == "not-image":
                return httpx.Response(200, json={"error": "nope"})
            if self.failure == "corrupt":
                return httpx.Response(200, content=b"\xff\xd8\xffgarbage", headers={"content-type": "image/jpeg"})
            if self.failure == "timeout":
                raise httpx.ConnectTimeout(f"timed out: {request.url}")  # the message quotes the URL and key
            colour = (200, 200, 190) if params["maptype"] == "roadmap" else (40, 70, 40)
            return httpx.Response(200, content=jpeg(colour), headers={"content-type": "image/jpeg"})
        return google_handler(request)


def client(service: MapService, **overrides) -> TestClient:
    values = {"_env_file": None, "google_maps_api_key": "geocoding-key", "maps_static_api_key": KEY,
              "mongodb_uri": None, "app_env": "test", "allow_ephemeral_storage": True, "meta_api_key": "m",
              "permit_rate_per_minute": 1000, "permit_burst": 1000}
    settings = Settings(**{**values, **overrides})
    return TestClient(create_app(settings, http_transport=httpx.MockTransport(service), permit_model=ScriptedModel()))


def resolve(c: TestClient) -> dict:
    return c.post("/api/property/resolve-location", json={"address": "Praça 5 de Outubro, Cascais"}).json()


def property_pdf(c: TestClient) -> bytes:
    response = c.get(f"/api/property/{resolve(c)['property_id']}/report.pdf")
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    return response.content


def images_and_text(content: bytes) -> tuple[list[bytes], str]:
    reader = PdfReader(io.BytesIO(content))
    images = [img.data for page in reader.pages for img in page.images]
    return images, " ".join(p.extract_text() for p in reader.pages)


def test_the_pdf_embeds_a_road_map_and_a_satellite_image():
    service = MapService()
    with client(service) as c:
        images, text = images_and_text(property_pdf(c))
    assert len(images) == 2 and all(i.startswith(b"\xff\xd8") for i in images)  # embedded JPEGs, not links
    assert [r["maptype"] for r in service.requests] == ["roadmap", "satellite"]
    assert "A. Road map" in text and "B. Satellite image" in text and "© Google" in text


def test_both_images_share_centre_zoom_size_and_highlight():
    service = MapService()
    with client(service) as c:
        prop = resolve(c)
        assert c.get(f"/api/property/{prop['property_id']}/report.pdf").status_code == 200
    road, sat = service.requests
    for key in ("center", "zoom", "size", "scale", "markers", "path", "format"):
        assert road[key] == sat[key], key
    assert {road["maptype"], sat["maptype"]} == {"roadmap", "satellite"}
    lat, lng = prop["coordinates"]["lat"], prop["coordinates"]["lng"]
    zoom, radius = FRAMING[prop["precision"]]  # e.g. rooftop → zoom 18, 25 m; area_center → zoom 16, 150 m
    assert road["center"] == f"{lat:.6f},{lng:.6f}" and road["zoom"] == str(zoom)
    assert road["path"].endswith(circle_polyline(lat, lng, radius))


def test_without_parcel_geometry_the_location_is_labelled_approximate_never_a_boundary():
    with client(MapService()) as c:
        _, text = images_and_text(property_pdf(c))
    flat = " ".join(text.split())
    assert "approximate location" in flat and "not a cadastral or parcel boundary" in flat
    assert "no verified parcel geometry" in flat


@pytest.mark.parametrize("failure", ["denied", "not-image", "corrupt", "timeout"])
def test_a_failing_map_service_gives_a_notice_and_no_substitute_image(failure, caplog):
    service = MapService(failure)
    with caplog.at_level(logging.DEBUG), client(service) as c:
        content = property_pdf(c)
    images, text = images_and_text(content)
    assert images == [] and "Location maps unavailable" in text and "No image has been substituted" in text
    assert KEY.encode() not in content and KEY not in caplog.text


def test_the_geocoding_key_is_the_fallback_and_no_key_means_no_client_key():
    with client(MapService(), maps_static_api_key=None) as c:
        assert c.app.state.static_maps._key == "geocoding-key"
    with client(MapService(), maps_static_api_key=None, google_maps_api_key=None) as c:
        assert c.app.state.static_maps._key is None


async def test_the_client_without_a_key_reports_unavailable_and_makes_no_request():
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500))) as h:
        maps = await StaticMapClient(h, None).location_maps(38.7, -9.42, "area_center")
    assert maps.images == () and maps.unavailable and calls == []


async def test_map_pairs_have_a_daily_cap_that_resets_the_next_day():
    day = [date(2026, 10, 30)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(MapService())) as h:
        client_ = StaticMapClient(h, KEY, rate_per_minute=1000, burst=1000, daily_limit=2, today=lambda: day[0])
        got = [len((await client_.location_maps(38.7, -9.42, "rooftop")).images) for _ in range(3)]
        day[0] = date(2026, 10, 31)
        got.append(len((await client_.location_maps(38.7, -9.42, "rooftop")).images))
    assert got == [2, 2, 0, 2]


def test_the_cover_always_warns_that_there_is_no_municipal_confirmation(verified_with_maps):
    _, pdf, _ = verified_with_maps
    cover = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "VERIFIED" in cover and "No municipal confirmation" in cover


async def test_map_requests_are_rate_limited_and_then_skipped():
    async with httpx.AsyncClient(transport=httpx.MockTransport(MapService())) as h:
        client_ = StaticMapClient(h, KEY, rate_per_minute=1, burst=1)
        first = await client_.location_maps(38.7, -9.42, "rooftop")
        second = await client_.location_maps(38.7, -9.42, "rooftop")
    assert len(first.images) == 2 and second.images == () and "skipped" in second.unavailable


def test_no_key_or_token_appears_in_the_pdf_bytes_or_text():
    with client(MapService()) as c:
        content = property_pdf(c)
    _, text = images_and_text(content)
    for secret in (KEY, "geocoding-key", "key="):
        assert secret.encode() not in content and secret not in text


@pytest.fixture(scope="module")
def verified_with_maps():
    service = MapService()
    with client(service) as c:
        ingest_regulamento(c)
        mid, token = run_matter(c)
        report = c.get(f"/api/permit/matters/{mid}/report", headers=auth(token)).json()
        pdf = c.get(f"/api/permit/matters/{mid}/report.pdf", headers=auth(token)).content
    return report, pdf, token


def test_maps_do_not_change_status_evidence_or_provenance(verified_with_maps):
    report, pdf, token = verified_with_maps
    images, text = images_and_text(pdf)
    flat = text.replace(" ", "").replace("\n", "")
    assert len(images) == 2 and report["assessment"]["status"] == "VERIFIED"
    assert report["assessment"]["verification"]["protocol"] and report["assessment"]["verification"]["trust_pin"]
    for e in report["assessment"]["evidence"]:
        assert e["evidence_id"] in text
        if e["sha256"]:
            assert e["sha256"][:16] in flat
    assert token not in text and token.encode() not in pdf  # the matter's capability never reaches the PDF


def test_a_pending_report_is_never_presented_as_verified_on_the_cover():
    with client(MapService()) as c:
        content = property_pdf(c)
    cover = PdfReader(io.BytesIO(content)).pages[0].extract_text()
    assert "PENDING CONFIRMATION" in cover and "VERIFIED —" not in cover
    assert "Zoning not verified" in cover and "No municipal confirmation" in cover


def test_map_params_differ_only_in_maptype():
    road, sat = map_params(38.7, -9.42, "interpolated", "roadmap"), map_params(38.7, -9.42, "interpolated", "satellite")
    assert {k for k in road if road[k] != sat[k]} == {"maptype"} and "key" not in road
