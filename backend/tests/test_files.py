"""HR-010: photos, plans and documents added to a matter (AC10.1–AC10.9), with a scripted reader."""

import io
import json

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from app.schemas.files import CONSENT_VERSION
from app.services.files.inspect import MAX_BYTES, FileRejected, distance_m, inspect, sniff
from app.services.i18n.translator import PINNED
from app.services.permit.model import ChatResult
from app.services.report.builder import FILE_CONDITION
from tests.permit_fakes import ANSWERS, ScriptedModel, make_client
from tests.test_permit_workflow import answer, create, run

CASCAIS = (38.6968, -9.4215)


class Reader(ScriptedModel):
    """The scripted permit model, plus a file reader that records what it was sent."""

    def __init__(self, observations=("A kitchen with wall units.",), fail=False, **kw):
        super().__init__(**kw)
        self.observations, self.fail, self.images = list(observations), fail, []

    async def chat(self, messages, *, tools=None, response_schema=None, schema_name=None):
        if schema_name != "file_reading":
            return await super().chat(messages, tools=tools, response_schema=response_schema, schema_name=schema_name)
        self.images.append(messages[-1]["content"][1]["image_url"]["url"])
        if self.fail:
            raise ValueError("model down")
        return ChatResult(content=json.dumps({"observations": self.observations}))


def jpeg(gps=None, when="2026:10:01 10:00:00") -> bytes:
    image = Image.new("RGB", (64, 48), (200, 180, 160))
    exif = image.getexif()
    exif[0x010F] = "PhoneMaker"  # device data
    exif.get_ifd(0x8769)[0x9003] = when
    if gps:
        lat, lng = gps

        def dms(v):
            v = abs(v)
            d = int(v); m = int((v - d) * 60); s = round(((v - d) * 60 - m) * 60, 2)
            return (float(d), float(m), s)
        exif.get_ifd(0x8825).update({1: "N" if lat >= 0 else "S", 2: dms(lat), 3: "E" if lng >= 0 else "W", 4: dms(lng)})
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif)
    return out.getvalue()


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 20, 30)).save(out, "PNG")
    return out.getvalue()


def pdf(with_image=True) -> bytes:
    writer = PdfWriter()
    if with_image:
        image = io.BytesIO()
        Image.new("RGB", (80, 60), (255, 255, 255)).save(image, "PDF")
        writer.append(PdfReader(image))
    else:
        writer.add_blank_page(100, 100)
    writer.add_metadata({"/Author": "Jane Owner", "/Producer": "Scanner 3000"})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# --- content checks (AC10.2, AC10.3) -----------------------------------------------------------------------------


@pytest.mark.parametrize(("data", "kind"), [(jpeg(), "image/jpeg"), (png(), "image/png"), (pdf(), "application/pdf")])
def test_the_type_comes_from_the_content(data, kind):
    assert sniff(data) == kind


@pytest.mark.parametrize("data", [b"", b"GIF89a....", b"<html>photo.jpg</html>", b"MZ\x90\x00"],
                         ids=["empty", "gif", "html-named-jpg", "executable"])
def test_other_content_is_refused(data):
    with pytest.raises(FileRejected):
        inspect(data)


def test_too_large_is_refused():
    with pytest.raises(FileRejected):
        inspect(b"\xff\xd8\xff" + b"0" * MAX_BYTES)


def test_location_and_device_data_are_read_then_removed():
    checked = inspect(jpeg(gps=CASCAIS))
    assert checked.gps is not None and distance_m(checked.gps, CASCAIS) < 5
    assert checked.captured_at is not None and checked.captured_at.year == 2026
    with Image.open(io.BytesIO(checked.kept)) as kept:
        assert not kept.getexif() and "exif" not in kept.info


def test_a_png_keeps_no_metadata():
    with Image.open(io.BytesIO(inspect(png()).kept)) as kept:
        assert not kept.info.get("exif") and not getattr(kept, "text", {})


def test_a_pdf_loses_its_document_info_and_its_image_is_read():
    checked = inspect(pdf())
    assert checked.readable is not None
    info = PdfReader(io.BytesIO(checked.kept)).metadata or {}
    assert "Jane Owner" not in str(dict(info)) and "Scanner 3000" not in str(dict(info))


def test_a_pdf_without_images_is_kept_but_not_readable():
    assert inspect(pdf(with_image=False)).readable is None


# --- API ---------------------------------------------------------------------------------------------------------


def upload(client, matter_id, data, kind="photo", consent=CONSENT_VERSION):
    return client.post(f"/api/permit/matters/{matter_id}/files", params={"kind": kind, "consent": consent},
                       content=data, headers={"Content-Type": "application/octet-stream"})


@pytest.fixture
def reader():
    return Reader()


LIMITS = {"file_read_rate_per_minute": 1000, "file_read_burst": 1000}


@pytest.fixture
def client(reader):
    with make_client(reader, **LIMITS) as c:
        yield c


def test_consent_is_required_first(client):
    matter_id = create(client)["matter_id"]
    assert upload(client, matter_id, jpeg(), consent="").status_code == 422
    assert client.get(f"/api/permit/matters/{matter_id}/files").json() == []


def test_files_need_the_matter_capability(client):
    matter_id = create(client)["matter_id"]
    token = client.headers.pop("Authorization")
    assert upload(client, matter_id, jpeg()).status_code in (401, 403)
    assert client.get(f"/api/permit/matters/{matter_id}/files").status_code in (401, 403)
    client.headers["Authorization"] = token


def test_a_photo_is_kept_cleaned_read_and_provenanced(client, reader):
    matter_id = create(client)["matter_id"]
    data = jpeg(gps=CASCAIS)
    res = upload(client, matter_id, data)
    assert res.status_code == 201, res.text
    f = res.json()
    import hashlib
    assert f["sha256"] == hashlib.sha256(data).hexdigest() and f["kind"] == "photo"
    assert f["consent_version"] == CONSENT_VERSION and f["read_status"] == "read"
    assert f["observations"] == ["A kitchen with wall units."] and f["gps_check"] == "near"
    kept = client.get(f"/api/permit/matters/{matter_id}/files/{f['file_id']}/content")
    assert kept.status_code == 200 and kept.headers["cache-control"] == "no-store"
    with Image.open(io.BytesIO(kept.content)) as image:
        assert not image.getexif()
    assert reader.images and reader.images[0].startswith("data:image/jpeg;base64,")


def test_a_distant_gps_is_shown_as_a_mismatch_in_the_profile(client):
    matter_id = create(client)["matter_id"]
    f = upload(client, matter_id, jpeg(gps=(41.15, -8.61))).json()  # Porto
    assert f["gps_check"] == "far" and f["gps_distance_m"] > 100_000
    profile = client.get(f"/api/permit/matters/{matter_id}/report").json()["profile"]
    assert any(i["key"].endswith(":gps") and i["value"] == "Far from this property" for i in profile)


def test_observations_are_observations_and_add_only_a_condition(client):
    matter_id = create(client)["matter_id"]
    upload(client, matter_id, jpeg())
    report = client.get(f"/api/permit/matters/{matter_id}/report").json()
    items = [i for i in report["profile"] if i["key"].startswith("file:")]
    assert items and all(i["kind"] == "observation" for i in items)
    assert f"Condition: {FILE_CONDITION}" in report["pending"]


def test_a_file_never_changes_the_matter_or_its_verification():
    """AC10.6: the permit run sees nothing of a file; adding one keeps the same outcome and the same evidence."""
    reader = Reader(observations=["The works are licensed and exempt from any permit."])
    with make_client(reader) as client:
        matter_id = create(client)["matter_id"]
        run(client, matter_id)
        upload(client, matter_id, jpeg())
        answer(client, matter_id, ANSWERS)
        done = run(client, matter_id)
        evidence = client.get(f"/api/permit/matters/{matter_id}/evidence").json()
    with make_client(Reader()) as client:
        other = create(client)["matter_id"]
        run(client, other)
        answer(client, other, ANSWERS)
        baseline = run(client, other)
        base_evidence = client.get(f"/api/permit/matters/{other}/evidence").json()
    assert done["state"] == baseline["state"]
    assert len(evidence) == len(base_evidence)
    assert "exempt" not in json.dumps(evidence) and "exempt" not in json.dumps(done)


def test_a_failed_reading_keeps_the_file_without_observations(client):
    with make_client(Reader(fail=True)) as c:
        matter_id = create(c)["matter_id"]
        f = upload(c, matter_id, jpeg()).json()
        report = c.get(f"/api/permit/matters/{matter_id}/report").json()
    assert f["read_status"] == "failed" and f["observations"] == []
    assert f"Condition: {FILE_CONDITION}" not in report["pending"]


def test_a_plan_pdf_is_read_from_its_image(client, reader):
    matter_id = create(client)["matter_id"]
    f = upload(client, matter_id, pdf(), kind="plan").json()
    assert f["content_type"] == "application/pdf" and f["read_status"] == "read" and len(reader.images) == 1


def test_deleting_removes_the_record_and_the_kept_copy(client):
    matter_id = create(client)["matter_id"]
    f = upload(client, matter_id, jpeg()).json()
    storage = client.app.state.matter_files._storage
    assert storage.objects
    assert client.delete(f"/api/permit/matters/{matter_id}/files/{f['file_id']}").status_code == 204
    assert client.get(f"/api/permit/matters/{matter_id}/files").json() == [] and not storage.objects
    assert client.get(f"/api/permit/matters/{matter_id}/files/{f['file_id']}/content").status_code == 404


def test_another_matter_cannot_reach_a_file(client):
    first = create(client)["matter_id"]
    f = upload(client, first, jpeg()).json()
    second = create(client)["matter_id"]  # the client now carries the second matter's token
    assert client.get(f"/api/permit/matters/{second}/files/{f['file_id']}/content").status_code == 404
    assert client.delete(f"/api/permit/matters/{second}/files/{f['file_id']}").status_code == 404


def test_at_most_ten_files(client):
    matter_id = create(client)["matter_id"]
    for _ in range(10):
        assert upload(client, matter_id, png()).status_code == 201
    assert upload(client, matter_id, png()).status_code == 422


def test_without_a_bucket_nothing_is_read_or_kept():
    reader = Reader()
    with make_client(reader, allow_ephemeral_storage=True) as client:
        from app.services.files.storage import UnconfiguredFileStorage
        client.app.state.matter_files._storage = UnconfiguredFileStorage()
        matter_id = create(client)["matter_id"]
        assert upload(client, matter_id, jpeg()).status_code == 503
        assert reader.images == [] and client.get(f"/api/permit/matters/{matter_id}/files").json() == []


def test_portuguese_report_uses_pinned_labels(client):
    matter_id = create(client)["matter_id"]
    upload(client, matter_id, jpeg(gps=(41.15, -8.61)))
    report = client.get(f"/api/permit/matters/{matter_id}/report", params={"lang": "pt"}).json()
    labels = {i["label"] for i in report["profile"] if i["key"].startswith("file:")}
    assert "Visto na sua fotografia" in labels and "Onde a sua fotografia diz ter sido tirada" in labels
    assert FILE_CONDITION in PINNED


def test_the_voice_and_the_pdf_carry_the_observation(client):
    matter_id = create(client)["matter_id"]
    upload(client, matter_id, jpeg())
    lines = client.get(f"/api/permit/matters/{matter_id}/report/voice").json()["lines"]
    assert any("Seen in your photo: A kitchen with wall units" in line for line in lines)
    assert any("What HABITA read in your files is not verified." in line for line in lines)  # spoken by sentence
    pdf_res = client.get(f"/api/permit/matters/{matter_id}/report.pdf")
    assert pdf_res.status_code == 200 and pdf_res.content.startswith(b"%PDF")


# --- Codex HR-010 round 1 regressions ------------------------------------------------------------------------------

from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, TextStringObject  # noqa: E402

from app.services.files.inspect import MAX_PAGES  # noqa: E402
from app.services.files.service import InMemoryFileRepository, InvalidFileError, MatterFiles  # noqa: E402
from app.services.files.storage import InMemoryFileStorage  # noqa: E402
from app.core.errors import NotFoundError  # noqa: E402


def hostile_pdf() -> bytes:
    """A page with XMP holding GPS and a device, a JavaScript page action, and an embedded JPEG carrying EXIF GPS."""
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(jpeg_pdf(jpeg(gps=(41.15, -8.61))))))
    page = writer.pages[0]
    xmp = DecodedStreamObject()
    xmp.set_data(b"<x:xmpmeta><exif:GPSLatitude>41,9N</exif:GPSLatitude><tiff:Model>PhoneMaker X</tiff:Model></x:xmpmeta>")
    page[NameObject("/Metadata")] = writer._add_object(xmp)
    js = DictionaryObject({NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("app.alert(1)")})
    page[NameObject("/AA")] = DictionaryObject({NameObject("/O"): writer._add_object(js)})
    writer.add_js("app.alert(2)")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def jpeg_pdf(jpeg_bytes: bytes) -> bytes:
    """A one-page PDF whose image is the given JPEG stream, kept as is (DCTDecode)."""
    from pypdf.generic import ArrayObject, FloatObject, NumberObject, StreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(64, 48)
    with Image.open(io.BytesIO(jpeg_bytes)) as im:
        w, h = im.size
    img = StreamObject()
    img._data = jpeg_bytes
    img.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(w), NameObject("/Height"): NumberObject(h),
                NameObject("/ColorSpace"): NameObject("/DeviceRGB"), NameObject("/BitsPerComponent"): NumberObject(8),
                NameObject("/Filter"): NameObject("/DCTDecode")})
    content = DecodedStreamObject()
    content.set_data(b"q 64 0 0 48 0 0 cm /Im0 Do Q")
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject(
        {NameObject("/Im0"): writer._add_object(img)})})
    page[NameObject("/Contents")] = writer._add_object(content)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_a_pdf_loses_page_metadata_actions_scripts_and_image_exif():
    data = hostile_pdf()
    assert b"PhoneMaker" in data and b"/JavaScript" in data and b"Exif" in data  # the test file really carries them
    kept = inspect(data).kept
    for leak in (b"PhoneMaker", b"GPSLatitude", b"app.alert", b"/JavaScript", b"Exif"):
        assert leak not in kept, leak
    page = PdfReader(io.BytesIO(kept)).pages[0]
    assert "/AA" not in page and "/Metadata" not in page
    assert next(iter(page.images)).image.size == (64, 48)  # the plan itself is still there


def test_too_many_pages_are_refused():
    writer = PdfWriter()
    for _ in range(MAX_PAGES + 1):
        writer.add_blank_page(10, 10)
    out = io.BytesIO()
    writer.write(out)
    with pytest.raises(FileRejected):
        inspect(out.getvalue())


def test_an_image_too_large_to_process_is_refused_before_decoding():
    out = io.BytesIO()
    Image.new("1", (7000, 7000)).save(out, "PNG")  # small file, 49 million pixels
    assert len(out.getvalue()) < MAX_BYTES
    with pytest.raises(FileRejected):
        inspect(out.getvalue())


class SlowReader:
    model_id = "m"

    def __init__(self, cancel=False):
        self.calls, self.cancel = 0, cancel

    async def chat(self, messages, **kw):
        import asyncio
        self.calls += 1
        await asyncio.sleep(0.01)
        if self.cancel:
            raise asyncio.CancelledError
        return ChatResult(content=json.dumps({"observations": ["A wall."]}))


async def test_concurrent_uploads_cannot_pass_the_limit():
    import asyncio
    from app.core.rate_limit import ResolutionLimiter
    reader = SlowReader()
    files = MatterFiles(InMemoryFileRepository(), InMemoryFileStorage(), reader, limiter=ResolutionLimiter(1000, 1000, 4))
    results = await asyncio.gather(*(files.add("pm_1", CASCAIS, "photo", CONSENT_VERSION, png()) for _ in range(14)),
                                   return_exceptions=True)
    kept = await files.list("pm_1")
    assert len(kept) <= 10 and reader.calls <= 10 and len(files._storage.objects) == len(kept)
    assert all(isinstance(r, InvalidFileError) for r in results if isinstance(r, BaseException))


async def test_an_interrupted_upload_leaves_a_file_the_user_can_still_delete():
    import asyncio
    files = MatterFiles(InMemoryFileRepository(), InMemoryFileStorage(), SlowReader(cancel=True))
    with pytest.raises(asyncio.CancelledError):
        await files.add("pm_1", CASCAIS, "photo", CONSENT_VERSION, png())
    (left,) = await files.list("pm_1")
    assert left.read_status == "reading" and files._storage.objects
    from datetime import timedelta
    await files._repo.replace(left.model_copy(update={"added_at": left.added_at - timedelta(minutes=6)}))
    await files.delete("pm_1", left.file_id)
    assert await files.list("pm_1") == [] and not files._storage.objects


def test_the_content_endpoint_never_renders_inline(client):
    matter_id = create(client)["matter_id"]
    f = upload(client, matter_id, pdf(), kind="plan").json()
    res = client.get(f"/api/permit/matters/{matter_id}/files/{f['file_id']}/content")
    assert res.headers["content-disposition"] == "attachment" and res.headers["content-security-policy"] == "sandbox"


# --- Codex HR-010 round 2 regressions ------------------------------------------------------------------------------


async def test_deleting_and_adding_again_cannot_buy_unlimited_readings():
    from app.core.errors import RateLimitedError
    from app.core.rate_limit import ResolutionLimiter
    reader = SlowReader()
    files = MatterFiles(InMemoryFileRepository(), InMemoryFileStorage(), reader,
                        limiter=ResolutionLimiter(1000, 1000, 2), per_matter_daily=3)
    for _ in range(3):
        f = await files.add("pm_1", CASCAIS, "photo", CONSENT_VERSION, png())
        await files.delete("pm_1", f.file_id)
    with pytest.raises(RateLimitedError):
        await files.add("pm_1", CASCAIS, "photo", CONSENT_VERSION, png())
    assert reader.calls == 3 and not files._storage.objects


async def test_a_file_being_added_cannot_be_deleted_so_no_copy_is_left_behind():
    import asyncio
    from app.core.errors import ConflictError
    files = MatterFiles(InMemoryFileRepository(), InMemoryFileStorage(), SlowReader())
    upload_task = asyncio.create_task(files.add("pm_1", CASCAIS, "photo", CONSENT_VERSION, png()))
    for _ in range(200):  # the check runs in a thread; wait until the record exists
        if await files.list("pm_1"):
            break
        await asyncio.sleep(0.005)
    (pending,) = await files.list("pm_1")
    with pytest.raises(ConflictError):
        await files.delete("pm_1", pending.file_id)
    done = await upload_task
    await files.delete("pm_1", done.file_id)
    assert not files._storage.objects and await files.list("pm_1") == []


async def test_a_record_removed_during_the_write_takes_its_copy_with_it():
    class Racing(InMemoryFileStorage):
        async def put(self, key, data, content_type):
            await super().put(key, data, content_type)
            await repo.remove("pm_1", key.rsplit("/", 1)[1])  # someone else removes the record mid-write

    repo = InMemoryFileRepository()
    files = MatterFiles(repo, Racing(), SlowReader())
    with pytest.raises(NotFoundError):
        await files.add("pm_1", CASCAIS, "photo", CONSENT_VERSION, png())
    assert not files._storage.objects


def test_a_refused_upload_is_never_read_or_decoded(monkeypatch):
    """Codex round 3: rate and daily limits apply before the body is received or checked."""
    import app.services.files.service as service
    calls = []
    monkeypatch.setattr(service, "inspect", lambda data: calls.append(len(data)))
    with make_client(Reader(), file_read_rate_per_minute=0.0001, file_read_burst=1) as client:
        matter_id = create(client)["matter_id"]
        monkeypatch.setattr(service, "inspect", lambda data: calls.append(len(data)) or inspect(data))
        assert upload(client, matter_id, png()).status_code == 201
        assert upload(client, matter_id, png()).status_code == 429
        assert upload(client, matter_id, png(), consent="").status_code == 422
    assert len(calls) == 1


async def test_invalid_uploads_do_not_use_the_daily_reading_budget():
    """Codex round 4: only a file that will be read takes from the daily caps."""
    from app.core.rate_limit import ResolutionLimiter
    files = MatterFiles(InMemoryFileRepository(), InMemoryFileStorage(), SlowReader(),
                        limiter=ResolutionLimiter(1000, 1000, 2), daily_limit=1)
    for bad in (b"", b"GIF89a", b"\xff\xd8\xffbroken"):
        with pytest.raises(InvalidFileError):
            await files.add("pm_1", CASCAIS, "photo", CONSENT_VERSION, bad)
    assert (await files.add("pm_1", CASCAIS, "photo", CONSENT_VERSION, png())).read_status == "read"


async def test_a_trickling_upload_gives_up_its_slot(monkeypatch):
    import asyncio
    import app.api.permit as api
    monkeypatch.setattr(api, "BODY_SECONDS", 0.05)

    class Slow:
        async def stream(self):
            yield b"\x89PNG"
            await asyncio.sleep(1)
            yield b"..."

    with pytest.raises(InvalidFileError):
        await api._body(Slow())


def test_an_oversized_pdf_image_is_never_decoded(monkeypatch):
    """Codex round 5: the size comes from the image dictionary; an image past the limit is skipped undecoded."""
    import app.services.files.inspect as ins
    decoded = []
    real = ins._decode
    monkeypatch.setattr(ins, "_decode", lambda x: decoded.append(int(x["/Width"])) or real(x))
    from pypdf.generic import NumberObject
    data = jpeg_pdf(jpeg())
    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter(clone_from=reader)
    xobj = writer.pages[0]["/Resources"]["/XObject"]["/Im0"].get_object()
    xobj[NameObject("/Width")], xobj[NameObject("/Height")] = NumberObject(9000), NumberObject(9000)
    out = io.BytesIO()
    writer.write(out)
    checked = inspect(out.getvalue())
    assert checked.readable is None and decoded == []
    assert inspect(data).readable is not None and decoded == [64]


# --- Codex TD-068 review round 1 regressions ----------------------------------------------------------------------


def _image_pdf(data: bytes, w: int, h: int, filters, colorspace="/DeviceGray") -> bytes:
    from pypdf.generic import ArrayObject, NumberObject, StreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(64, 48)
    img = StreamObject()
    img._data = data
    f = ArrayObject([NameObject(x) for x in filters]) if len(filters) > 1 else NameObject(filters[0])
    img.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(w), NameObject("/Height"): NumberObject(h),
                NameObject("/ColorSpace"): NameObject(colorspace), NameObject("/BitsPerComponent"): NumberObject(8),
                NameObject("/Filter"): f, NameObject("/Length"): NumberObject(len(data))})
    content = DecodedStreamObject()
    content.set_data(b"q 64 0 0 48 0 0 cm /Im0 Do Q")
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject(
        {NameObject("/Im0"): writer._add_object(img)})})
    page[NameObject("/Contents")] = writer._add_object(content)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _peak(fn) -> int:
    import tracemalloc
    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_a_run_length_bomb_is_kept_without_being_decompressed():
    """A 4000×4000 grey image as run-length data: about 250 KB that would decompress to 16 MB."""
    bomb = (b"\x81\x00" * (16_000_000 // 128)) + b"\x80"
    data = _image_pdf(bomb, 4000, 4000, ["/RunLengthDecode"])
    assert len(data) < 400_000
    checked = None

    def run():
        nonlocal checked
        checked = inspect(data)
    assert _peak(run) < 8_000_000  # the stream is copied, never expanded
    assert checked.readable is None


def test_a_jpeg_hidden_behind_a_filter_array_with_a_lying_size_is_not_decoded():
    big = io.BytesIO()
    Image.new("L", (6000, 6000)).save(big, "JPEG", quality=10)  # small file, 36 million pixels
    import zlib
    data = _image_pdf(zlib.compress(big.getvalue()), 1, 1, ["/FlateDecode", "/DCTDecode"])
    assert _peak(lambda: inspect(data)) < 20_000_000
    assert inspect(data).readable is None
