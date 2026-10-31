"""HR-012: before/after concepts from the user's own photos, with a scripted image editor (AC12.1–AC12.10)."""

import io
import json

import pytest
from PIL import Image

from app.core.errors import RateLimitedError, UpstreamServiceError
from app.services.concepts import catalog
from app.services.concepts.label import NOTICE_EN, NOTICE_PT, burn
from app.services.concepts.service import Concepts, InMemoryConceptRepository
from app.services.files.service import InMemoryFileRepository, InvalidFileError, MatterFiles
from app.services.files.storage import InMemoryFileStorage
from app.services.i18n.translator import PINNED
from app.services.permit.model import ChatResult
from tests.permit_fakes import ANSWERS, ScriptedModel, make_client, resolve_cascais
from tests.test_files import CONSENT_VERSION, LIMITS, jpeg, pdf, png
from tests.test_permit_workflow import answer, run


class Reader(ScriptedModel):
    def __init__(self, people=False, **kw):
        super().__init__(**kw)
        self.people = people

    async def chat(self, messages, *, tools=None, response_schema=None, schema_name=None):
        if schema_name != "file_reading":
            return await super().chat(messages, tools=tools, response_schema=response_schema, schema_name=schema_name)
        return ChatResult(content=json.dumps({"observations": ["A room."], "checks": [], "people": self.people}))


class Editor:
    model_id = "muse-image-1.0"

    def __init__(self, result: bytes | None = None, fail=False):
        self.calls: list[tuple[bytes, str]] = []
        self.result, self.fail = result, fail

    async def edit(self, image: bytes, prompt: str) -> bytes:
        self.calls.append((image, prompt))
        if self.fail:
            raise UpstreamServiceError("down")
        if self.result is not None:
            return self.result
        out = io.BytesIO()
        Image.new("RGB", (640, 480), (90, 120, 150)).save(out, "PNG")
        return out.getvalue()


def client_with(editor=None, people=False, **kw):
    return make_client(Reader(people=people), permit_image_editor=editor or Editor(), **{**LIMITS, **kw})


def matter(client, intent="interior_works"):
    res = client.post("/api/permit/matters", json={"property_id": resolve_cascais(client),
                                                    "question": "Quero remodelar a cozinha.", "intent": intent})
    body = res.json()
    client.headers["Authorization"] = f"Bearer {body['access_token']}"
    return body["matter"]["matter_id"]


def photo(client, mid, data=None, kind="photo"):
    res = client.post(f"/api/permit/matters/{mid}/files", params={"kind": kind, "consent": CONSENT_VERSION},
                      content=data or jpeg(), headers={"Content-Type": "application/octet-stream"})
    assert res.status_code == 201, res.text
    return res.json()["file_id"]


def concept(client, mid, fid, change="new_kitchen"):
    return client.post(f"/api/permit/matters/{mid}/concepts", json={"file_id": fid, "change": change})


def test_options_follow_the_matters_type_and_never_touch_the_outside():
    assert catalog.options("interior_works") == ["new_kitchen", "new_bathroom", "floor_and_paint"]
    assert catalog.options("out_of_scope") == []
    every = " ".join(catalog.instruction(k) for k in catalog.CHANGES)
    assert "facade" not in " ".join(catalog.CHANGES[k][1] for k in catalog.CHANGES)
    assert "Do not add any person" in every and "Do not add, remove or move any wall" in every


def test_a_concept_from_the_users_photo_with_the_fixed_instruction_and_the_notice():
    editor = Editor()
    with client_with(editor) as client:
        mid = matter(client)
        fid = photo(client, mid)
        res = concept(client, mid, fid)
        assert res.status_code == 201, res.text
        c = res.json()
        image = client.get(f"/api/permit/matters/{mid}/concepts/{c['concept_id']}/content")
        original = client.get(f"/api/permit/matters/{mid}/files/{fid}/content").content
    (sent, prompt), = editor.calls
    assert sent == original and prompt == catalog.instruction("new_kitchen")
    assert c["change_label"] == "New kitchen units and worktop" and c["model_id"] == "muse-image-1.0"
    assert image.headers["content-type"] == "image/jpeg" and image.headers["content-security-policy"] == "sandbox"
    with Image.open(io.BytesIO(image.content)) as shown:
        assert shown.size[1] > 480  # the notice band was added below the picture


@pytest.mark.parametrize(("setup", "body_change"), [
    ("other_change", "facade_colour"),
    ("wrong_type", "office_layout"),
], ids=["not-in-catalog", "not-for-this-type"])
def test_changes_outside_the_types_catalog_are_refused_before_any_call(setup, body_change):
    editor = Editor()
    with client_with(editor) as client:
        mid = matter(client)
        fid = photo(client, mid)
        assert concept(client, mid, fid, body_change).status_code == 422
    assert editor.calls == []


def test_a_photo_with_people_or_unchecked_is_refused():
    editor = Editor()
    with client_with(editor, people=True) as client:
        mid = matter(client)
        fid = photo(client, mid)
        res = concept(client, mid, fid)
    assert res.status_code == 422 and "no people" in res.text
    assert editor.calls == []


def test_only_photos_not_plans_or_pdfs():
    editor = Editor()
    with client_with(editor) as client:
        mid = matter(client)
        assert concept(client, mid, photo(client, mid, png(), kind="plan")).status_code == 422
        assert concept(client, mid, photo(client, mid, pdf(), kind="photo")).status_code == 422
    assert editor.calls == []


def test_at_most_three_per_matter_and_a_refusal_costs_nothing():
    editor = Editor()
    with client_with(editor) as client:
        mid = matter(client)
        fid = photo(client, mid)
        assert [concept(client, mid, fid).status_code for _ in range(3)] == [201, 201, 201]
        assert concept(client, mid, fid).status_code == 429
    assert len(editor.calls) == 3


async def test_the_daily_cap_across_matters():
    files = MatterFiles(InMemoryFileRepository(), InMemoryFileStorage(), Reader())
    from app.core.rate_limit import ResolutionLimiter
    from tests.test_files import CASCAIS
    files._limiter = ResolutionLimiter(1000, 1000, 2)
    editor = Editor()
    concepts = Concepts(InMemoryConceptRepository(), files._storage, files, editor,
                        limiter=ResolutionLimiter(1000, 1000, 2), daily_limit=2, per_matter=3)
    made = 0
    for n in range(3):
        f = await files.add(f"pm_{n}", CASCAIS, "photo", CONSENT_VERSION, jpeg())
        try:
            await concepts.create(f"pm_{n}", "interior_works", f.file_id, "new_kitchen")
            made += 1
        except RateLimitedError:
            pass
    assert made == 2 and len(editor.calls) == 2


def test_a_non_image_answer_is_never_shown_or_stored():
    with client_with(Editor(result=b"<html>not an image</html>")) as client:
        mid = matter(client)
        res = concept(client, mid, photo(client, mid))
        listed = client.get(f"/api/permit/matters/{mid}/concepts").json()
    assert res.status_code == 502 and listed == []


def test_deleting_the_photo_deletes_its_concepts():
    with client_with() as client:
        mid = matter(client)
        fid = photo(client, mid)
        cid = concept(client, mid, fid).json()["concept_id"]
        storage = client.app.state.matter_files._storage
        assert any("/concepts/" in k for k in storage.objects)
        assert client.delete(f"/api/permit/matters/{mid}/files/{fid}").status_code == 204
        assert client.get(f"/api/permit/matters/{mid}/concepts").json() == []
        assert client.get(f"/api/permit/matters/{mid}/concepts/{cid}/content").status_code == 404
        assert not storage.objects


def test_a_concept_can_be_deleted_and_needs_the_capability():
    with client_with() as client:
        mid = matter(client)
        cid = concept(client, mid, photo(client, mid)).json()["concept_id"]
        token = client.headers.pop("Authorization")
        assert client.get(f"/api/permit/matters/{mid}/concepts").status_code in (401, 403)
        assert client.delete(f"/api/permit/matters/{mid}/concepts/{cid}").status_code in (401, 403)
        client.headers["Authorization"] = token
        assert client.delete(f"/api/permit/matters/{mid}/concepts/{cid}").status_code == 204


def test_concepts_never_touch_the_permit_run():
    with client_with() as client:
        mid = matter(client, intent="unit_conversion")
        run(client, mid)
        concept(client, mid, photo(client, mid), "light_partition")
        answer(client, mid, ANSWERS)
        done = run(client, mid)
        evidence = client.get(f"/api/permit/matters/{mid}/evidence").json()
    assert done["state"] == "VERIFIED" and "concept" not in json.dumps(evidence).lower()


def test_report_pdf_and_voice_say_what_a_concept_is_not():
    with client_with() as client:
        mid = matter(client)
        concept(client, mid, photo(client, mid))
        report = client.get(f"/api/permit/matters/{mid}/report").json()
        pt = client.get(f"/api/permit/matters/{mid}/report", params={"lang": "pt"}).json()
        lines = client.get(f"/api/permit/matters/{mid}/report/voice").json()["lines"]
        pdf_res = client.get(f"/api/permit/matters/{mid}/report.pdf")
    assert report["concepts"][0]["change_label"] == "New kitchen units and worktop"
    assert pt["concepts"][0]["change_label"] == "Móveis de cozinha e bancada novos"
    assert any("not an authorisation" in line for line in lines) and pdf_res.status_code == 200


def test_the_notice_is_pinned_in_both_languages_and_burned_in():
    assert PINNED[NOTICE_EN] == NOTICE_PT
    out = io.BytesIO()
    Image.new("RGB", (400, 300)).save(out, "PNG")
    with Image.open(io.BytesIO(burn(out.getvalue()))) as labelled:
        assert labelled.format == "JPEG" and labelled.size[1] > 300


def test_a_failing_image_service_costs_no_stored_concept():
    with client_with(Editor(fail=True)) as client:
        mid = matter(client)
        assert concept(client, mid, photo(client, mid)).status_code == 502
        assert client.get(f"/api/permit/matters/{mid}/concepts").json() == []


# --- Codex HR-012 round 1 regressions ------------------------------------------------------------------------------

import asyncio  # noqa: E402

import httpx  # noqa: E402

from app.integrations.meta.image import MAX_RESPONSE, MetaImageEditor  # noqa: E402


class PeopleOnSecondRead(Reader):
    """The photo has no people; the generated image does."""

    def __init__(self):
        super().__init__()
        self.reads = 0

    async def chat(self, messages, *, tools=None, response_schema=None, schema_name=None):
        if schema_name == "file_reading":
            self.reads += 1
            self.people = self.reads > 1
        return await super().chat(messages, tools=tools, response_schema=response_schema, schema_name=schema_name)


def test_a_generated_image_with_a_person_is_never_kept():
    with make_client(PeopleOnSecondRead(), permit_image_editor=Editor(), **LIMITS) as client:
        mid = matter(client)
        res = concept(client, mid, photo(client, mid))
        listed = client.get(f"/api/permit/matters/{mid}/concepts").json()
        objects = client.app.state.matter_files._storage.objects
    assert res.status_code == 502 and "person" in res.text and listed == []
    assert not any("/concepts/" in k for k in objects)


def editor_with(handler) -> MetaImageEditor:
    return MetaImageEditor(httpx.AsyncClient(transport=httpx.MockTransport(handler)), api_key="k",
                           base_url="https://api.example/v1", model_id="muse-image-1.0")


async def test_a_url_answer_is_refused_and_never_fetched():
    fetched = []

    def handler(request):
        if request.url.path.endswith("/images/edits"):
            return httpx.Response(200, json={"data": [{"url": "https://169.254.169.254/latest"}]})
        fetched.append(str(request.url))
        return httpx.Response(200, content=b"x")

    with pytest.raises(UpstreamServiceError):
        await editor_with(handler).edit(b"img", "p")
    assert fetched == []


async def test_an_oversized_answer_is_refused_while_streaming():
    big = b'{"data":[{"b64_json":"' + b"A" * (MAX_RESPONSE + 10) + b'"}]}'
    with pytest.raises(UpstreamServiceError):
        await editor_with(lambda r: httpx.Response(200, content=big)).edit(b"img", "p")


async def test_a_base64_answer_is_decoded():
    import base64
    raw = b"\x89PNGdata"
    out = await editor_with(lambda r: httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(raw).decode()}]})
                            ).edit(b"img", "p")
    assert out == raw


def test_the_notice_wraps_and_is_never_clipped_on_a_narrow_image():
    from PIL import ImageFont

    from app.services.concepts.label import FONT, _wrap
    font = ImageFont.truetype(FONT, 12)
    for text in (NOTICE_PT, NOTICE_EN):
        lines = _wrap(text, font, 380)
        assert " ".join(lines) == text and all(font.getlength(line) <= 380 for line in lines)
    out = io.BytesIO()
    Image.new("RGB", (400, 300)).save(out, "PNG")
    with Image.open(io.BytesIO(burn(out.getvalue()))) as labelled:
        assert labelled.size[1] >= 300 + 4 * 18  # at least two lines per language


def test_the_matter_cap_is_for_life_not_per_day():
    editor = Editor()
    with client_with(editor) as client:
        mid = matter(client)
        fid = photo(client, mid)
        made = [concept(client, mid, fid).json()["concept_id"] for _ in range(3)]
        for cid in made:
            client.delete(f"/api/permit/matters/{mid}/concepts/{cid}")
        assert concept(client, mid, fid).status_code == 429
    assert len(editor.calls) == 3


async def test_a_photo_deleted_during_generation_takes_the_concept_with_it():
    from app.core.errors import NotFoundError
    from app.core.rate_limit import ResolutionLimiter
    from tests.test_files import CASCAIS
    files = MatterFiles(InMemoryFileRepository(), InMemoryFileStorage(), Reader(),
                        limiter=ResolutionLimiter(1000, 1000, 2))
    f = await files.add("pm_1", CASCAIS, "photo", CONSENT_VERSION, jpeg())

    class Slow(Editor):
        async def edit(self, image, prompt):
            from datetime import timedelta
            await files._repo.replace(f.model_copy(update={"read_status": "read"}))
            await files.delete("pm_1", f.file_id)  # the user deletes the photo meanwhile
            return await super().edit(image, prompt)

    concepts = Concepts(InMemoryConceptRepository(), files._storage, files, Slow(),
                        limiter=ResolutionLimiter(1000, 1000, 2))
    with pytest.raises(NotFoundError):
        await concepts.create("pm_1", "interior_works", f.file_id, "new_kitchen")
    assert await concepts.list("pm_1") == [] and not files._storage.objects


async def test_a_failed_save_leaves_no_object():
    from app.core.rate_limit import ResolutionLimiter
    from tests.test_files import CASCAIS

    class Failing(InMemoryFileStorage):
        async def put(self, key, data, content_type):
            if "/concepts/" in key:
                await super().put(key, data, content_type)  # written, then the call fails
                raise asyncio.CancelledError
            await super().put(key, data, content_type)

    storage = Failing()
    files = MatterFiles(InMemoryFileRepository(), storage, Reader(), limiter=ResolutionLimiter(1000, 1000, 2))
    f = await files.add("pm_1", CASCAIS, "photo", CONSENT_VERSION, jpeg())
    concepts = Concepts(InMemoryConceptRepository(), storage, files, Editor(), limiter=ResolutionLimiter(1000, 1000, 2))
    with pytest.raises(asyncio.CancelledError):
        await concepts.create("pm_1", "interior_works", f.file_id, "new_kitchen")
    assert await concepts.list("pm_1") == [] and not any("/concepts/" in k for k in storage.objects)



def test_a_concept_saved_while_its_photo_is_deleted_is_swept_after():
    """Codex round 2: generation saves after the first sweep and before the photo goes."""
    with client_with() as client:
        mid = matter(client)
        fid = photo(client, mid)
        concepts = client.app.state.concepts
        real_delete = client.app.state.matter_files.delete

        async def delete_and_race(matter_id, file_id):
            # a concept lands between the first sweep and the photo's deletion
            from datetime import UTC, datetime

            from app.schemas.concepts import Concept
            late = Concept(concept_id="cn_00000000000000aa", matter_id=matter_id, file_id=file_id, change="new_kitchen",
                           change_label="New kitchen units and worktop", created_at=datetime.now(UTC), model_id="m")
            await concepts._repo.add(late)
            await concepts._storage.put(f"matters/{matter_id}/concepts/{late.concept_id}", b"x", "image/jpeg")
            await real_delete(matter_id, file_id)

        client.app.state.matter_files.delete = delete_and_race
        assert client.delete(f"/api/permit/matters/{mid}/files/{fid}").status_code == 204
        assert client.get(f"/api/permit/matters/{mid}/concepts").json() == []
        assert not client.app.state.matter_files._storage.objects



async def test_a_record_swept_during_the_write_leaves_no_object():
    """Codex round 3: the sweep removes the record while the image is being written."""
    from app.core.errors import NotFoundError
    from app.core.rate_limit import ResolutionLimiter
    from tests.test_files import CASCAIS

    class SweptDuringWrite(InMemoryFileStorage):
        async def put(self, key, data, content_type):
            if "/concepts/" in key:
                await concepts._repo.remove("pm_1", key.rsplit("/", 1)[1])  # a delete happens meanwhile
            await super().put(key, data, content_type)

    storage = SweptDuringWrite()
    files = MatterFiles(InMemoryFileRepository(), storage, Reader(), limiter=ResolutionLimiter(1000, 1000, 2))
    f = await files.add("pm_1", CASCAIS, "photo", CONSENT_VERSION, jpeg())
    concepts = Concepts(InMemoryConceptRepository(), storage, files, Editor(), limiter=ResolutionLimiter(1000, 1000, 2))
    with pytest.raises(NotFoundError):
        await concepts.create("pm_1", "interior_works", f.file_id, "new_kitchen")
    assert not any("/concepts/" in k for k in storage.objects)
