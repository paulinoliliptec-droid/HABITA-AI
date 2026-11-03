"""Seen from the air (owner, 2026-11-01): DGT orthophoto + Meta SAM 3.1, observations only, conditions to confirm."""

import io
import json
import random
from datetime import UTC, datetime

import httpx
import pytest
from meta_sam_parser._mask_codec import _encode_raster
from PIL import Image

from app.integrations.dgt.orthophoto import SIZE, DgtOrthophotoClient, Orthophoto, bbox_3857, covers
from app.integrations.meta.segment import MetaSegmenter, Segment, parse
from app.services.aerial.service import SMALL_M2, measure
from tests.permit_fakes import make_client, resolve_cascais


def noisy_jpeg(size=SIZE) -> bytes:
    rnd = random.Random(1)
    img = Image.new("RGB", (size, size))
    img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(size * size)])
    out = io.BytesIO()
    img.save(out, "JPEG", quality=60)
    return out.getvalue()


JPEG = noisy_jpeg()


def square(left, top, side) -> Segment:
    return Segment(left=left, top=top, width=side, height=side, mask=bytes([1]) * side * side)


class Ortho:
    def __init__(self, photo=True):
        self.calls = 0
        self.photo = photo

    async def fetch(self, lat, lng, half):
        self.calls += 1
        if not self.photo:
            return None
        return Orthophoto(jpeg=JPEG, bbox=bbox_3857(lat, lng, half), metres_per_pixel=2 * half / SIZE,
                          sha256="0" * 64, retrieved_at=datetime.now(UTC))


class Sam:
    model_id = "sam-3.1"

    def __init__(self, found=None, fail=False):
        self.prompts: list[str] = []
        self.found = found if found is not None else {
            # mpp 0.117 at rooftop: the house under the point, an annex ~19 m², a pool ~12 m², a far building.
            "building": [square(462, 462, 100), square(600, 520, 37), square(10, 10, 60)],
            "swimming pool": [square(470, 580, 30)],
        }
        self.fail = fail

    def configured(self):
        return True

    async def segment(self, jpeg, prompt, width, height, keep=None):
        from app.core.errors import UpstreamServiceError
        self.prompts.append(prompt)
        if self.fail:
            raise UpstreamServiceError("down")
        segs = self.found.get(prompt, [])
        return [g for g in segs if keep is None or keep(g.left, g.top, g.left + g.width, g.top + g.height)]


def client(sam=None, ortho=None, **kw):
    from app.core.config import Settings
    from app.main import create_app
    from tests.permit_fakes import google_handler
    values = {"_env_file": None, "google_maps_api_key": "test-key", "mongodb_uri": None, "app_env": "test",
              "allow_ephemeral_storage": True, "meta_api_key": "k", "aerial_rate_per_minute": 1000,
              "aerial_burst": 1000, **kw}
    from fastapi.testclient import TestClient
    return TestClient(create_app(Settings(**values), http_transport=httpx.MockTransport(google_handler),
                                 aerial_segmenter=sam or Sam(), aerial_orthophotos=ortho or Ortho()))


def test_an_analysis_lists_what_is_near_the_point_with_conditions_to_confirm():
    sam, ortho = Sam(), Ortho()
    with client(sam, ortho) as c:
        pid = resolve_cascais(c)
        made = c.post(f"/api/property/{pid}/aerial")
        again = c.post(f"/api/property/{pid}/aerial")
        image = c.get(f"/api/property/{pid}/aerial/image")
        report = c.get(f"/api/property/{pid}/report").json()
    assert made.status_code == 200, made.text
    body = made.json()
    assert again.json()["aerial_id"] == body["aerial_id"] and ortho.calls == 1 and sam.prompts == ["building",
                                                                                                    "swimming pool"]
    kinds = [(o["kind"], o["at_point"]) for o in body["objects"]]
    assert ("building", True) in kinds and ("small_building", False) in kinds and ("pool", False) in kinds
    assert len(body["objects"]) == 3  # the far building is outside the 25 m radius
    assert body["checks"] == ["aerial_small_building", "aerial_pool"] and body["radius_m"] == 25
    assert body["source"]["provider"] == "DGT" and body["source"]["layer"] == "Ortos2018-RGB"
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(image.content)) as img:
        assert img.size == (SIZE, SIZE + 56)  # attribution and source lines are burned in under the image
    pending = " ".join(report["pending"])
    assert "small separate building is visible from the air" in pending and "swimming pool is visible" in pending
    assert "not a survey or a parcel boundary" in pending and "cedida pela Direção-Geral do Território" in pending
    assert report["assessment"] is None  # nothing about the property's assessment changes


def test_areas_and_distances_come_from_the_mask_and_the_scale():
    mpp = 0.117
    house = measure(square(462, 462, 100), "building", mpp, 25)
    annex = measure(square(600, 520, 37), "building", mpp, 25)
    assert house.at_point and house.distance_m == 0 and house.kind == "building" and house.area_m2 == 135
    assert annex.kind == "small_building" and annex.area_m2 < SMALL_M2 and 10 <= annex.distance_m <= 12
    assert measure(square(10, 10, 60), "building", mpp, 25) is None
    big_far = measure(square(700, 700, 200), "building", mpp, 60)
    assert big_far is not None and big_far.kind == "building"


def test_coarse_addresses_and_places_outside_the_mainland_get_no_analysis():
    from app.services.aerial.service import AerialAnalysis, AerialUnavailableError, InMemoryAerialRepository
    from app.services.files.storage import InMemoryFileStorage

    class Prop:
        def __init__(self, precision, lat=38.7, lng=-9.42):
            self.property_id, self.precision = "prp_" + "1" * 16, precision

            class C:
                pass
            self.coordinates = C()
            self.coordinates.lat, self.coordinates.lng = lat, lng

    import asyncio
    sam, ortho = Sam(), Ortho()
    a = AerialAnalysis(InMemoryAerialRepository(), InMemoryFileStorage(), ortho, sam)
    for prop in (Prop("area_center"), Prop("approximate"), Prop("rooftop", 32.65, -16.9)):  # Madeira
        with pytest.raises(AerialUnavailableError):
            asyncio.run(a.create(prop))
    assert ortho.calls == 0 and sam.prompts == []


def test_a_failure_costs_nothing_and_keeps_nothing():
    with client(Sam(fail=True), aerial_daily_limit=1) as c:
        pid = resolve_cascais(c)
        assert c.post(f"/api/property/{pid}/aerial").status_code == 502
        assert c.get(f"/api/property/{pid}/aerial").status_code == 404
    sam = Sam()
    with client(sam, Ortho(photo=False), aerial_daily_limit=1) as c:
        pid = resolve_cascais(c)
        assert c.post(f"/api/property/{pid}/aerial").status_code == 502  # no orthophoto: SAM never called
    assert sam.prompts == []


def test_one_paid_attempt_per_property_and_day():
    """Codex aerial-r1: repeated failures after SAM was called can't buy more calls; an attempt that paid nothing
    (no orthophoto) doesn't count."""
    sam = Sam(fail=True)
    with client(sam, aerial_daily_limit=10) as c:
        pid = resolve_cascais(c)
        first = c.post(f"/api/property/{pid}/aerial").status_code
        sam.fail = False
        second = c.post(f"/api/property/{pid}/aerial")
    assert first == 502 and second.status_code == 429 and "already tried today" in second.text
    assert sam.prompts == ["building"]
    ortho = Ortho(photo=False)
    with client(Sam(), ortho, aerial_daily_limit=10) as c:
        pid = resolve_cascais(c)
        assert c.post(f"/api/property/{pid}/aerial").status_code == 502
        ortho.photo = True
        assert c.post(f"/api/property/{pid}/aerial").status_code == 200


def test_a_small_building_touching_another_is_not_separate():
    touching = Sam(found={"building": [square(462, 462, 100), square(562, 470, 30)], "swimming pool": []})
    with client(touching) as c:
        pid = resolve_cascais(c)
        body = c.post(f"/api/property/{pid}/aerial").json()
    assert [o["kind"] for o in body["objects"]] == ["building", "building"] and body["checks"] == []


def test_the_daily_cap_is_taken_before_any_call():
    sam, ortho = Sam(), Ortho()
    with client(sam, ortho, aerial_daily_limit=0) as c:
        pid = resolve_cascais(c)
        res = c.post(f"/api/property/{pid}/aerial")
    assert res.status_code == 429 and ortho.calls == 0 and sam.prompts == []


def test_unknown_properties_are_refused():
    with client() as c:
        assert c.post(f"/api/property/prp_{'0' * 16}/aerial").status_code == 404
        assert c.get(f"/api/property/prp_{'0' * 16}/aerial/image").status_code == 404
        assert c.post("/api/property/not-an-id/aerial").status_code == 422


# --- the SAM answer, with Meta's published codec --------------------------------------------------------------------

def record(oid, x1, y1, raster_rows):
    h, w = len(raster_rows), len(raster_rows[0])
    payload = _encode_raster([b for row in raster_rows for b in row], w, h)
    return f"{oid}<|box;x1={x1};y1={y1};x2={x1 + w - 1};y2={y1 + h - 1};w={SIZE};h={SIZE}|>" \
           f"<|mask;x=0;y=0;data={h},{w},{payload}|>"


def test_the_answer_is_parsed_with_metas_codec_and_bad_records_are_skipped():
    good = record(0, 10, 20, [[1, 1, 0], [1, 1, 1]])
    off_image = f"1<|box;x1=1020;y1=0;x2=1030;y2=1;w={SIZE};h={SIZE}|><|mask;x=0;y=0;data=2,11,!abc|>"
    wrong_size = record(2, 0, 0, [[1]]).replace("data=1,1,", "data=3,3,")
    corrupt = record(3, 5, 5, [[1, 0], [0, 1]]).replace("data=2,2,!", "data=2,2,!zz")
    segs = parse("<0f>" + good, SIZE, SIZE)
    assert len(segs) == 1 and (segs[0].left, segs[0].top, segs[0].width, segs[0].height) == (10, 20, 3, 2)
    assert list(segs[0].mask) == [1, 1, 0, 1, 1, 1]
    assert parse("", SIZE, SIZE) == [] and parse("<0f>", SIZE, SIZE) == []
    # Codex aerial-r1: anything malformed makes the whole answer unreadable, never "nothing found".
    for bad in (off_image, wrong_size, corrupt, "garbled", good + "trailing"):
        with pytest.raises(ValueError):
            parse("<0f>" + ",".join([good, bad]), SIZE, SIZE)
    # Boxes the caller doesn't want are not decoded at all (a corrupt one far away doesn't matter).
    far_corrupt = record(4, 900, 900, [[1, 0], [0, 1]]).replace("data=2,2,!", "data=2,2,!zz")
    kept = parse("<0f>" + ",".join([good, far_corrupt]), SIZE, SIZE, keep=lambda l, t, r, b: l < 500)
    assert len(kept) == 1
    with pytest.raises(ValueError):
        parse("<1f>" + good, SIZE, SIZE)


async def test_the_segmenter_sends_the_image_and_prompt_and_reads_the_output():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        text = "<0f>" + record(0, 1, 1, [[1, 1], [1, 1]])
        return httpx.Response(200, json={"output": [{"type": "message", "content": [
            {"type": "output_text", "text": text}]}]})

    sam = MetaSegmenter(httpx.AsyncClient(transport=httpx.MockTransport(handler)), api_key="k",
                        base_url="https://api.meta.ai/v1", model_id="sam-3.1")
    segs = await sam.segment(JPEG, "swimming pool", SIZE, SIZE)
    assert len(segs) == 1 and seen[0]["model"] == "sam-3.1"
    content = seen[0]["input"][0]["content"]
    assert content[0]["type"] == "input_image" and content[0]["image_url"].startswith("data:image/jpeg;base64,")
    assert content[1] == {"type": "input_text", "text": "swimming pool"}


async def test_the_segmenter_errors_are_upstream_errors():
    from app.core.errors import UpstreamServiceError
    for status, body in ((500, {"error": {}}), (200, {"output": "x"}), (200, [1]), (200, {"output": []}),
                         (200, {"output": [{"type": "message", "content": []}]})):
        sam = MetaSegmenter(httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r, s=status, b=body: httpx.Response(s, json=b))), api_key="k", base_url="https://x", model_id="sam-3.1")
        with pytest.raises(UpstreamServiceError):
            await sam.segment(JPEG, "building", SIZE, SIZE)
    with pytest.raises(ValueError):
        MetaSegmenter(httpx.AsyncClient(), api_key="k", base_url="https://x", model_id="sam-3.1-contributor")


async def test_the_dgt_client_asks_for_the_official_layer_and_refuses_blank_answers():
    asked = []
    blank = io.BytesIO()
    Image.new("RGB", (SIZE, SIZE), (250, 250, 250)).save(blank, "JPEG")

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url)
        return httpx.Response(200, content=JPEG if len(asked) == 1 else blank.getvalue())

    dgt = DgtOrthophotoClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    photo = await dgt.fetch(38.7, -9.42, 60)
    assert photo is not None and round(photo.metres_per_pixel, 4) == round(120 / SIZE, 4)
    url = asked[0]
    assert url.host == "cartografia.dgterritorio.gov.pt" and url.params["layers"] == "Ortos2018-RGB"
    assert url.params["crs"] == "EPSG:3857" and url.params["width"] == str(SIZE)
    assert await dgt.fetch(38.7, -9.42, 60) is None  # blank
    assert await dgt.fetch(32.65, -16.9, 60) is None and len(asked) == 2  # outside: not even asked
    assert covers(41.15, -8.61) and not covers(37.74, -25.67)


async def test_an_empty_output_text_means_nothing_found():
    sam = MetaSegmenter(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "output": [{"type": "message", "content": [{"type": "output_text", "text": ""}]}]}))),
        api_key="k", base_url="https://x", model_id="sam-3.1")
    assert await sam.segment(JPEG, "swimming pool", SIZE, SIZE) == []


def test_separation_is_a_true_distance():
    from app.services.aerial.service import _touches
    grid = bytearray(SIZE * SIZE)
    grid[100 * SIZE + 100] = 1  # one pixel of another building
    mpp = 0.117  # 1 m is about 8.5 pixels
    assert _touches(square(106, 100, 1), grid, mpp)  # 6 px straight: 0.7 m
    assert not _touches(square(107, 107, 1), grid, mpp)  # 7 px diagonally: about 1.16 m


# Afinamentos 2026-11-03: official orthophotos beyond Portugal (IGN for France, NYS for New York State).
def test_the_official_source_is_chosen_by_place():
    from app.integrations.orthophotos import source_for

    assert source_for(38.6968, -9.4215, "PT").provider == "DGT"  # Cascais
    assert source_for(48.8556, 2.3589, "FR").provider == "IGN"  # Paris
    assert source_for(40.7484, -73.9857, "US", "us/new-york").provider == "NYS"  # Manhattan
    assert source_for(1.2840, 103.8514, "SG") is None  # Singapore: OneMap terms not cleared
    assert source_for(37.74, -25.67, "PT") is None  # Azores: outside the DGT mainland orthophoto
    # Codex aerial r1: the jurisdiction decides, not the rectangle: Geneva and Jersey City sit inside the boxes.
    assert source_for(46.2044, 6.1432, "CH") is None
    assert source_for(40.7178, -74.0431, "US", "us/new-jersey") is None
    assert source_for(48.8556, 2.3589) is None  # no jurisdiction, no source


class _Storage:
    def __init__(self):
        self.items = {}

    async def put(self, key, data, content_type):
        self.items[key] = data

    async def get(self, key):
        return self.items.get(key)

    async def delete(self, key):
        self.items.pop(key, None)


async def test_an_analysis_on_another_source_carries_its_attribution_and_no_camara_checks():
    from types import SimpleNamespace

    from app.integrations.orthophotos import IGN_SOURCE, OfficialOrthophotoClient
    from app.services.aerial.service import AerialAnalysis, InMemoryAerialRepository

    class IgnOrtho(OfficialOrthophotoClient):
        def __init__(self):
            pass

        async def fetch(self, lat, lng, half, source=None):
            assert source is IGN_SOURCE  # the gate's choice is what is fetched
            return Orthophoto(jpeg=JPEG, bbox=bbox_3857(lat, lng, half), metres_per_pixel=2 * half / SIZE,
                              sha256="0" * 64, retrieved_at=datetime.now(UTC), source=IGN_SOURCE)

    storage = _Storage()
    service = AerialAnalysis(InMemoryAerialRepository(), storage, IgnOrtho(), Sam())
    prop = SimpleNamespace(property_id="prp_000000000000paris", precision="rooftop",
                           coordinates=SimpleNamespace(lat=48.8556, lng=2.3589),
                           jurisdiction=SimpleNamespace(country_code="FR", levels=[]))
    report = await service.create(prop)
    assert report.source.provider == "IGN" and report.source.year is None
    assert "IGN" in report.source.attribution and report.source.edition == "BD ORTHO, latest"
    # The fixed check sentences name the Câmara Municipal: never outside Portugal.
    assert report.checks == [] and {o.kind for o in report.objects} >= {"small_building", "pool"}
    with Image.open(io.BytesIO(next(iter(storage.items.values())))) as img:
        assert img.size == (SIZE, SIZE + 56)


async def test_a_place_without_an_official_source_is_refused_before_any_spend():
    from types import SimpleNamespace

    from app.integrations.orthophotos import OfficialOrthophotoClient
    from app.services.aerial.service import AerialAnalysis, AerialUnavailableError, InMemoryAerialRepository

    sam = Sam()
    service = AerialAnalysis(InMemoryAerialRepository(), _Storage(), OfficialOrthophotoClient(httpx.AsyncClient()), sam)
    prop = SimpleNamespace(property_id="prp_0000000singapore", precision="rooftop",
                           coordinates=SimpleNamespace(lat=1.2840, lng=103.8514),
                           jurisdiction=SimpleNamespace(country_code="SG", levels=[]))
    with pytest.raises(AerialUnavailableError):
        await service.create(prop)
    assert sam.prompts == []


async def test_a_property_across_the_border_is_refused_before_any_spend():
    """Codex aerial r1: Geneva lies inside France's rectangle, its square may show French imagery; no SAM call."""
    from types import SimpleNamespace

    from app.integrations.orthophotos import OfficialOrthophotoClient
    from app.services.aerial.service import AerialAnalysis, AerialUnavailableError, InMemoryAerialRepository

    sam = Sam()
    service = AerialAnalysis(InMemoryAerialRepository(), _Storage(), OfficialOrthophotoClient(httpx.AsyncClient()), sam)
    prop = SimpleNamespace(property_id="prp_000000000geneva", precision="rooftop",
                           coordinates=SimpleNamespace(lat=46.2044, lng=6.1432),
                           jurisdiction=SimpleNamespace(country_code="CH", levels=[]))
    with pytest.raises(AerialUnavailableError):
        await service.create(prop)
    assert sam.prompts == []


async def test_a_stored_analysis_is_not_returned_once_the_property_left_every_source():
    """Codex aerial r2: a refreshed property moved from New York to New Jersey is refused, not served its old image."""
    from types import SimpleNamespace

    from app.integrations.orthophotos import NYS_SOURCE, OfficialOrthophotoClient
    from app.services.aerial.service import AerialAnalysis, AerialUnavailableError, InMemoryAerialRepository

    class NysOrtho(OfficialOrthophotoClient):
        def __init__(self):
            pass

        async def fetch(self, lat, lng, half, source=None):
            return Orthophoto(jpeg=JPEG, bbox=bbox_3857(lat, lng, half), metres_per_pixel=2 * half / SIZE,
                              sha256="0" * 64, retrieved_at=datetime.now(UTC), source=NYS_SOURCE)

    service = AerialAnalysis(InMemoryAerialRepository(), _Storage(), NysOrtho(), Sam())
    region = [SimpleNamespace(type="region", id="us/new-york")]
    ny = SimpleNamespace(property_id="prp_00000000000000ny", precision="rooftop",
                         coordinates=SimpleNamespace(lat=40.7484, lng=-73.9857),
                         jurisdiction=SimpleNamespace(country_code="US", levels=region))
    first = await service.create(ny)
    assert first.source.provider == "NYS"
    moved = SimpleNamespace(property_id=ny.property_id, precision="rooftop",
                            coordinates=SimpleNamespace(lat=40.7178, lng=-74.0431),
                            jurisdiction=SimpleNamespace(country_code="US",
                                                         levels=[SimpleNamespace(type="region", id="us/new-jersey")]))
    with pytest.raises(AerialUnavailableError):
        await service.create(moved)


async def test_reads_hide_an_analysis_once_the_property_moved():
    """Codex aerial r3: GET, the image and the reports read through the same gate as POST."""
    from types import SimpleNamespace

    from app.integrations.orthophotos import NYS_SOURCE, OfficialOrthophotoClient
    from app.services.aerial.service import AerialAnalysis, AerialUnavailableError, InMemoryAerialRepository

    class NysOrtho(OfficialOrthophotoClient):
        def __init__(self):
            pass

        async def fetch(self, lat, lng, half, source=None):
            return Orthophoto(jpeg=JPEG, bbox=bbox_3857(lat, lng, half), metres_per_pixel=2 * half / SIZE,
                              sha256="0" * 64, retrieved_at=datetime.now(UTC), source=NYS_SOURCE)

    service = AerialAnalysis(InMemoryAerialRepository(), _Storage(), NysOrtho(), Sam())
    ny = [SimpleNamespace(type="region", id="us/new-york")]

    def at(lat, lng, levels=ny):
        return SimpleNamespace(property_id="prp_00000000000000ny", precision="rooftop",
                               coordinates=SimpleNamespace(lat=lat, lng=lng),
                               jurisdiction=SimpleNamespace(country_code="US", levels=levels))

    here = at(40.7484, -73.9857)
    await service.create(here)
    assert await service.current(here) is not None and await service.current_image(here)
    moved_in_ny = at(40.7500, -73.9900)  # still New York, another point: the old image describes another place
    to_nj = at(40.7178, -74.0431, [SimpleNamespace(type="region", id="us/new-jersey")])
    for prop in (moved_in_ny, to_nj):
        assert await service.current(prop) is None and await service.current_image(prop) is None
    with pytest.raises(AerialUnavailableError):
        await service.create(moved_in_ny)


async def test_a_concurrent_winner_made_at_another_point_is_not_returned():
    """Codex aerial r4: the losing insert gets the winner only when the winner analysed this request's point."""
    from types import SimpleNamespace

    from app.integrations.orthophotos import NYS_SOURCE, OfficialOrthophotoClient
    from app.services.aerial.service import AerialAnalysis, AerialUnavailableError, InMemoryAerialRepository

    class NysOrtho(OfficialOrthophotoClient):
        def __init__(self):
            pass

        async def fetch(self, lat, lng, half, source=None):
            return Orthophoto(jpeg=JPEG, bbox=bbox_3857(lat, lng, half), metres_per_pixel=2 * half / SIZE,
                              sha256="0" * 64, retrieved_at=datetime.now(UTC), source=NYS_SOURCE)

    ny = [SimpleNamespace(type="region", id="us/new-york")]

    def at(lat, lng):
        return SimpleNamespace(property_id="prp_00000000000000ny", precision="rooftop",
                               coordinates=SimpleNamespace(lat=lat, lng=lng),
                               jurisdiction=SimpleNamespace(country_code="US", levels=ny))

    other = await AerialAnalysis(InMemoryAerialRepository(), _Storage(), NysOrtho(), Sam()).create(at(40.7500, -73.9900))

    class Racing(InMemoryAerialRepository):
        """Empty when checked, then another request's analysis wins the insert."""
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def get(self, property_id):
            self.calls += 1
            return None if self.calls == 1 else other

        async def add(self, report):
            return False

    with pytest.raises(AerialUnavailableError):
        await AerialAnalysis(Racing(), _Storage(), NysOrtho(), Sam()).create(at(40.7484, -73.9857))
