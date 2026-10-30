"""Bilingual system: the translated view never changes what was verified, a doubtful translation stays English, fixed
legal wording is pinned, and nothing fails when Google Translate is missing or down."""

import html
import io
import json
import logging
import re
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.core.config import Settings
from app.integrations.translate.client import DETECT_URL, TRANSLATE_URL, GoogleTranslateClient, TranslationUnavailable
from app.main import create_app
from app.services.i18n.generate import FRONTEND_CATALOG, backend_texts, frontend_texts
from app.services.i18n.translator import (
    CATALOG, PINNED, Translations, Translator, _decode, _encode, fidelity_problems, fixed, translation_note,
    translator_for,
)
from tests.permit_fakes import ScriptedModel, google_handler
from tests.test_permit_official_sources import auth, ingest_regulamento, run_matter

KEY = "TRANSLATE-KEY-must-never-appear"
PT_VERIFIED = "Tradução automática da resposta verificada"


class FakeGoogle:
    """Google stand-in: "translates" to a marked copy, so any faithful-looking text passes the checks."""

    def __init__(self, failure: int | None = None, language: str = "pt"):
        self.bodies: list[dict] = []
        self.headers: list[httpx.Headers] = []
        self.failure, self.language = failure, language

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != "translation.googleapis.com":
            return google_handler(request)
        self.bodies.append(json.loads(request.content))
        self.headers.append(request.headers)
        if self.failure:
            return httpx.Response(self.failure, text="denied")
        if request.url.path.endswith("/detect"):
            return httpx.Response(200, json={"data": {"detections": [[{"language": self.language}]]}})
        # Keeps the words so numbers and quotations survive; the checks are exercised on their own below.
        return httpx.Response(200, json={"data": {"translations": [{"translatedText": q} for q in self.bodies[-1]["q"]]}})


def client(service: FakeGoogle, key: str | None = KEY) -> TestClient:
    settings = Settings(_env_file=None, google_maps_api_key="g", google_translate_api_key=key, mongodb_uri=None,
                        app_env="test", allow_ephemeral_storage=True, meta_api_key="m", permit_rate_per_minute=1000,
                        permit_burst=1000, translate_rate_per_minute=1000, translate_burst=1000)
    return TestClient(create_app(settings, http_transport=httpx.MockTransport(service), permit_model=ScriptedModel()))


def pdf_text(content: bytes) -> str:
    return " ".join(" ".join(p.extract_text().split()) for p in PdfReader(io.BytesIO(content)).pages)


# ── The fidelity checks ────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("source, target", [
    ("The minimum height is 1.5 m.", "A altura mínima é de 1,5 m."),
    ("You must confirm this with the authority [E1].", "Tem de confirmar isto junto da autoridade [E1]."),
    ("The change may need a permit.", "A alteração pode exigir uma licença."),
    ("This is not a permit.", "Isto não é uma autorização."),
    ("You must not change the facade.", "Não pode alterar a fachada."),
    ("Any building here cannot be extended.", "Nenhum edifício aqui pode ser ampliado, é proibido."),
    ('The regulation says "uso habitacional" here.', 'O regulamento diz "uso habitacional" aqui.'),
])
def test_a_faithful_translation_passes(source, target):
    assert fidelity_problems(source, target) == []


@pytest.mark.parametrize("source, target, problem", [
    ("The minimum height is 1.5 m.", "A altura mínima é de 2,5 m.", "number"),
    ("Article 62 applies [E1].", "Aplica-se o artigo 62 [E2].", "reference"),
    ("This is not allowed.", "Isto é permitido.", "negation"),
    ("You cannot build here.", "Pode construir aqui.", "negation"),
    ("You must submit the form.", "Pode submeter o formulário.", "obligation"),
    ("The works may be exempt.", "As obras são isentas.", "possibility"),
    ("The building has two units.", "O edifício tem três frações.", "number word"),
    ('It says "uso habitacional".', 'Diz "uso residencial".', "quotation"),
    ("The RJUE applies.", "Aplica-se o regime.", "acronym"),
    ("The Câmara's index of documents.", "Índice da Câmara dos Representantes dos documentos.", "official name"),
    ("The Regulamento's rules for the category.", "As regras do ™ para a categoria.", "official name"),
    ("The rules for the category.", "As regras do ™ para a categoria.", "stray symbol"),
    ("The parcel is not in the REN.", "A parcela não está na REN (Região de Referência de Energia).", "added explanation"),
    ("You must not change the facade.", "Não se deve alterar a fachada.", "prohibition"),
    ("You must not change the facade.", "Não deve alterar a fachada.", "prohibition"),
    ("You must not build here. You must not demolish the wall.", "Não deve construir aqui. Não pode demolir o muro.",
     "prohibition"),
    ("The parcel is in the REN.", "A parcela está na REN: Região de Referência de Energia.", "added explanation"),
    ("The parcel is in the REN.", "A parcela está na REN: região de referência de energia.", "added explanation"),
    ("Works are exempt where the building is classified.",
     "As obras estão isentas se o edifício for classificado como monumento nacional.", "added meaning"),
    ("Works are exempt where the building is classified.", "As obras estão isentas se classificado como património.", "added meaning"),
    ("Each unit must have two rooms.", "Cada unidade deve ter dois quartos.", "added meaning"),
    ("The works comply with the plan.", "As obras foram aprovadas.", "legal outcome"),
    ("The works comply with the plan.", "As obras estão licenciadas.", "legal outcome"),
])
def test_a_translation_that_changes_the_meaning_is_refused(source, target, problem):
    assert problem in fidelity_problems(source, target)


def test_portuguese_legal_terms_are_used_not_translated():
    encoded = _encode("Apply for municipal prior control under the RJUE.")
    assert "controlo prévio municipal" in encoded and "prior control" not in encoded
    assert "parecer prévio" in _encode("Request a prior opinion.")
    assert _decode(encoded.replace("Apply for", "Solicite")) == "Solicite controlo prévio municipal under the RJUE."


def test_what_must_not_change_is_protected_and_restored():
    source = 'See E1: "uso <misto>" & {authority}.'
    encoded = _encode(source)
    assert encoded.count('<span translate="no">') == 3 and "<misto>" not in encoded
    assert _decode(encoded) == source
    assert _decode('Ver <span translate="no">E1</span> .') == "Ver E1."
    assert _decode("A HABITA verifica ( {n})") == "O HABITA verifica ({n})"


# ── The translator ─────────────────────────────────────────────────────────────────────────────────────────────
class ScriptedClient:
    def __init__(self, answer=None, fail=False):
        self.calls: list[list[str]] = []
        self.answer, self.fail = answer or (lambda text: text), fail

    async def translate(self, texts, target):
        self.calls.append(list(texts))
        if self.fail:
            raise TranslationUnavailable
        assert target == "pt-PT"
        return [self.answer(t) for t in texts]

    async def detect(self, text):
        if self.fail:
            raise TranslationUnavailable
        return "pt-PT"


async def test_a_doubtful_translation_stays_in_english_and_is_counted():
    client_ = ScriptedClient(lambda t: "Isto é permitido." if "not" in t else "Avance com a obra.")
    result = await Translator(client_).translate(["This is not allowed.", "Proceed with the works."], "pt")
    assert result("This is not allowed.") == "This is not allowed."
    assert result("Proceed with the works.") == "Avance com a obra." and result.kept_original == 1 and result.available


async def test_when_the_service_fails_everything_stays_in_english():
    result = await Translator(ScriptedClient(fail=True)).translate(["Proceed."], "pt")
    assert result("Proceed.") == "Proceed." and not result.available and result.kept_original == 1
    assert "texto original em inglês" in translation_note(result, verified=True)


async def test_pinned_texts_never_reach_the_machine_and_results_are_cached():
    scripted = ScriptedClient(lambda t: "Avance com a obra.")
    translator = Translator(scripted)
    disclaimer = next(k for k in PINNED if k.startswith("HABITA AI provides decision support"))
    first = await translator.translate([disclaimer, "VERIFIED", "Proceed with the works."], "pt")
    second = await translator.translate(["Proceed with the works."], "pt")
    assert scripted.calls == [["Proceed with the works."]]  # once, and without the pinned texts
    assert first(disclaimer) == PINNED[disclaimer] and first("VERIFIED") == "VERIFICADO"
    assert second("Proceed with the works.") == "Avance com a obra."


async def test_english_needs_no_service():
    scripted = ScriptedClient()
    assert (await Translator(scripted).translate(["Proceed."], "en"))("Proceed.") == "Proceed."
    assert scripted.calls == []


async def test_only_portuguese_or_english_changes_the_language_shown():
    assert await Translator(ScriptedClient()).detect("Posso fazer obras?") == "pt"
    assert await Translator(ScriptedClient(fail=True)).detect("Posso fazer obras?") is None


@pytest.mark.parametrize("verified, has_answer, expected", [
    (True, True, PT_VERIFIED), (False, True, "rascunho que não foi verificado"), (False, False, "Tradução automática."),
])
def test_the_label_never_calls_a_draft_verified(verified, has_answer, expected):
    note = translation_note(Translations("pt", {}), verified=verified, has_answer=has_answer)
    assert expected in note and (verified or PT_VERIFIED not in note)
    assert translation_note(Translations("en", {}), verified=True) is None


# ── The client ─────────────────────────────────────────────────────────────────────────────────────────────────
def google(service: FakeGoogle, key: str | None = KEY, **limits) -> GoogleTranslateClient:
    return GoogleTranslateClient(httpx.AsyncClient(transport=httpx.MockTransport(service)), key, **limits)


async def test_the_key_travels_in_a_header_never_in_the_url_or_the_logs(caplog):
    service = FakeGoogle(failure=403)
    with caplog.at_level(logging.DEBUG), pytest.raises(TranslationUnavailable) as raised:
        await google(service).translate(["x"], "pt-PT")
    assert service.headers[0]["x-goog-api-key"] == KEY
    assert KEY not in caplog.text and KEY not in str(raised.value) and TRANSLATE_URL.endswith("/v2")
    assert "HTTP 403" in caplog.text and KEY not in DETECT_URL


async def test_spend_is_bounded_and_long_batches_are_split():
    service = FakeGoogle()
    capped = google(service, daily_limit=1)
    await capped.translate(["x"], "pt-PT")
    with pytest.raises(TranslationUnavailable):
        await capped.translate(["y"], "pt-PT")
    assert len(service.bodies) == 1
    service = FakeGoogle()
    out = await google(service, today=date.today).translate([f"t{i}" for i in range(250)], "pt-PT")
    assert out == [f"t{i}" for i in range(250)] and [len(b["q"]) for b in service.bodies] == [100, 100, 50]


async def test_no_key_is_unavailable_without_a_request():
    service = FakeGoogle()
    with pytest.raises(TranslationUnavailable):
        await google(service, key=None).translate(["x"], "pt-PT")
    assert service.bodies == []


# ── Through the API ────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def verified():
    service = FakeGoogle()
    with client(service) as c:
        ingest_regulamento(c)
        mid, token = run_matter(c)
        yield c, service, mid, token


def test_the_portuguese_report_keeps_every_status_and_changes_nothing_stored(verified):
    c, _, mid, token = verified
    before = c.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
    verification = c.get(f"/api/permit/matters/{mid}/verification", headers=auth(token)).json()
    en = c.get(f"/api/permit/matters/{mid}/report", headers=auth(token)).json()
    pt = c.get(f"/api/permit/matters/{mid}/report?lang=pt", headers=auth(token)).json()
    assert en["language"] == "en" and en["translation"] is None and pt["language"] == "pt"
    a, b = en["assessment"], pt["assessment"]
    assert b["status"] == a["status"] == "VERIFIED" and b["content_verified"] and b["verification"] == a["verification"]
    assert b["evidence"] == a["evidence"] and b["conclusion_answer"] == a["conclusion_answer"]
    assert [s["evidence_ids"] for s in b["statements"]] == [s["evidence_ids"] for s in a["statements"]]
    assert PT_VERIFIED in pt["translation"]["note"] and pt["disclaimer"].startswith("O HABITA AI presta apoio")
    assert c.get(f"/api/permit/matters/{mid}", headers=auth(token)).json() == before  # the verified text is untouched
    assert c.get(f"/api/permit/matters/{mid}/verification", headers=auth(token)).json() == verification


def test_the_portuguese_pdf_says_what_it_is(verified):
    c, _, mid, token = verified
    response = c.get(f"/api/permit/matters/{mid}/report.pdf?lang=pt", headers=auth(token))
    text = pdf_text(response.content)
    assert response.status_code == 200 and "VERIFICADO" in text and "Sem confirmação municipal" in text
    assert PT_VERIFIED in text and "No municipal confirmation" not in text
    assert "Report at a glance" not in text and "Findings" not in text and "Conditions" not in text
    assert "VERIFIED" not in re.sub(r"statement-v\d|[a-z_]*VERIFIED[a-z_]*", "", text.split("Evidências e proveniência")[0])


def test_the_matter_translation_needs_the_capability_and_says_it_is_verified(verified):
    c, _, mid, token = verified
    assert c.get(f"/api/permit/matters/{mid}/translation?lang=pt").status_code == 401
    body = c.get(f"/api/permit/matters/{mid}/translation?lang=pt", headers=auth(token)).json()
    draft = c.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()["draft"]
    assert body["verified"] and PT_VERIFIED in body["note"] and draft["conclusion"]["summary"] in body["texts"]
    assert c.get(f"/api/permit/matters/{mid}/translation?lang=fr", headers=auth(token)).status_code == 422


def test_a_matter_not_yet_verified_is_never_labelled_verified():
    with client(FakeGoogle()) as c:
        pid = c.post("/api/property/resolve-location", json={"address": "Praça 5 de Outubro, Cascais"}).json()["property_id"]
        created = c.post("/api/permit/matters", json={"property_id": pid, "question": "Posso fazer obras aqui?"}).json()
        body = c.get(f"/api/permit/matters/{created['matter']['matter_id']}/translation?lang=pt",
                     headers=auth(created["access_token"])).json()
    assert created["detected_language"] == "pt" and not body["verified"] and PT_VERIFIED not in (body["note"] or "")


@pytest.mark.parametrize("failure", [403, 500])
def test_a_translation_failure_stops_nothing(failure):
    with client(FakeGoogle(failure=failure)) as c:
        ingest_regulamento(c)
        mid, token = run_matter(c)
        report = c.get(f"/api/permit/matters/{mid}/report?lang=pt", headers=auth(token))
        assert report.status_code == 200 and report.json()["assessment"]["status"] == "VERIFIED"
        assert report.json()["translation"]["available"] is False
        assert "texto original em inglês" in report.json()["translation"]["note"]
        assert c.get(f"/api/permit/matters/{mid}/report.pdf?lang=pt", headers=auth(token)).status_code == 200


def test_without_a_key_nothing_is_sent_and_the_question_stays_undetected():
    service = FakeGoogle()
    with client(service, key=None) as c:
        pid = c.post("/api/property/resolve-location", json={"address": "Praça 5 de Outubro, Cascais"}).json()["property_id"]
        created = c.post("/api/permit/matters", json={"property_id": pid, "question": "Posso fazer obras aqui?"}).json()
        assert created["detected_language"] is None and c.get(f"/api/property/{pid}/report?lang=pt").status_code == 200
    assert service.bodies == []


def test_detection_ignores_other_languages():
    with client(FakeGoogle(language="es")) as c:
        pid = c.post("/api/property/resolve-location", json={"address": "Praça 5 de Outubro, Cascais"}).json()["property_id"]
        created = c.post("/api/permit/matters", json={"property_id": pid, "question": "Puedo hacer obras aquí?"}).json()
    assert created["detected_language"] is None


# ── The catalogs ───────────────────────────────────────────────────────────────────────────────────────────────
def test_every_fixed_text_has_portuguese():
    assert not {t for t in backend_texts() if not fixed(t, "pt")}
    frontend = json.loads(FRONTEND_CATALOG.read_text(encoding="utf-8"))
    assert not frontend_texts() - set(frontend) and set(PINNED) <= set(frontend)
    assert all(frontend[k] == v for k, v in PINNED.items())  # pinned wording always wins


def test_generated_texts_pass_the_same_checks_as_answers():
    frontend = json.loads(FRONTEND_CATALOG.read_text(encoding="utf-8"))
    bad = {k: fidelity_problems(k, v) for k, v in (CATALOG | frontend).items()
           if k not in PINNED and fidelity_problems(k, v)}
    assert bad == {}


def test_status_words_are_the_reviewed_ones_and_never_mean_approved():
    t = translator_for("pt")
    assert (t("VERIFIED"), t("REJECTED"), t("PENDING CONFIRMATION")) == ("VERIFICADO", "REJEITADO", "CONFIRMAÇÃO PENDENTE")
    for key in ("VERIFIED", "Verified", "Verified assessment", "Verified layer", "Likely possible"):
        assert not re.search(r"aprovad|licenciad|deferid|autorizad", PINNED[key], re.I)


def test_the_builders_zoning_warnings_are_pinned_and_never_reach_the_machine():
    from app.services.report.builder import _REASONS
    assert not [r for r in _REASONS.values() if r not in PINNED]


def test_the_legacy_pdf_is_labelled_too(verified):
    from app.schemas.report import PermitReport
    from app.services.report.pdf import render_pdf
    c, _, mid, token = verified
    report = PermitReport.model_validate(c.get(f"/api/permit/matters/{mid}/report?lang=pt", headers=auth(token)).json())
    assert "Tradução automática da resposta verificada" in pdf_text(render_pdf(report))


def test_pinned_wording_keeps_every_placeholder():
    for english, portuguese in PINNED.items():
        assert sorted(re.findall(r"\{\w+\}", english)) == sorted(re.findall(r"\{\w+\}", portuguese)), english


def test_the_legal_warnings_keep_their_negations_in_portuguese():
    t = translator_for("pt")
    assert "não é uma licença" in t(next(k for k in PINNED if k.startswith("HABITA AI provides")))
    assert "não foi confirmado" in html.unescape(t(next(k for k in PINNED if "No municipal confirmation" in k)))
    frontend = json.loads(FRONTEND_CATALOG.read_text(encoding="utf-8"))
    assert "não é um limite" in frontend["Location: {coordinates} (rooftop point; not a parcel boundary)"]
    assert "Não é um limite cadastral" in t(next(k for k in PINNED if k.startswith("<b>Legend.")))
