"""HR-007 voice explanation: the script says no more than the report and keeps its warnings, and ElevenLabs speaks only
that script, one voice per language, within the spend bounds and with no key in the logs."""

import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.integrations.speech.client import ElevenLabsClient, SpeechUnavailable
from app.main import create_app
from app.schemas.report import PermitReport
from app.services.report.voice import MAX_CHARS, build_voice_script, script_version, speakable
from tests.permit_fakes import ScriptedModel, google_handler

FIXTURE = Path(__file__).parents[2] / "frontend/src/features/report/fixtures/verified-report.json"
report = PermitReport.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
a = report.assessment
KEY = "ELEVEN-KEY-must-never-appear"
VOICES = {"en": "voice-en", "pt": "voice-pt"}


def assessed(**over) -> PermitReport:
    return report.model_copy(update={"assessment": a.model_copy(update=over)})


def said(r: PermitReport) -> str:
    return " ".join(build_voice_script(r))


def record(**over):
    return a.verification.model_copy(update=over)


def test_opens_saying_audio_is_not_proof_and_closes_with_the_disclaimer():
    script = build_voice_script(report)
    assert "not legal proof" in " ".join(script[:2])
    assert script[-1] == speakable(report.disclaimer)[-1]


def test_says_the_status_and_that_verified_is_habitas_own_check():
    assert "Status: Verified." in said(report) and "not a municipal approval" in said(report)
    assert "Status: Rejected." in said(assessed(status="REJECTED", content_verified=False))


@pytest.mark.parametrize("over", [{"content_verified": False}, {"verification": record(current=False)},
                                  {"verification": record(outcome="REJECTED")}, {"verification": None}])
def test_never_says_verified_without_the_full_rule(over):
    text = said(assessed(**over))
    assert "Status: Pending confirmation." in text and "Status: Verified" not in text
    assert "must not be relied on" in text
    assert a.status_reason not in text and "does not support a verified result" in text


def test_pending_and_rejected_keep_their_own_reason_and_warning():
    for status in ("PENDING_CONFIRMATION", "REJECTED"):
        text = said(assessed(status=status, content_verified=False, status_reason="Waiting for the official plan."))
        assert "Waiting for the official plan." in text and "must not be relied on" in text


def test_says_every_open_item_section_and_map():
    text = said(report.model_copy(update={"pending": ["Confirm the land-use category."]}))
    assert "Confirm the land-use category." in text
    assert all(speakable(s.text)[0] in text for s in a.statements)
    assert all(speakable(d.reason)[0] in text for d in report.planning.documents_to_consult)


def test_conditions_are_said_once_but_an_answer_request_is_kept():
    with_condition = assessed(conditions=["Confirm the exits."])
    repeated = with_condition.model_copy(update={"pending": ["Condition: Confirm the exits."]})
    assert len([x for x in build_voice_script(repeated) if "Confirm the exits." in x]) == 1
    asked = with_condition.model_copy(update={"pending": ["Your answer is needed: Confirm the exits."]})
    assert "Your answer is needed" in said(asked)


def test_names_a_zoning_class_only_from_a_verified_layer():
    plan = report.planning
    assert "Zoning not verified" in said(report)
    claimed = plan.model_copy(update={"verified_zoning": False, "classification": "Espaço Central"})
    zoned = plan.model_copy(update={"verified_zoning": True, "classification": "Espaço Central"})
    assert "Espaço Central" not in said(report.model_copy(update={"planning": claimed}))
    assert "Espaço Central" in said(report.model_copy(update={"planning": zoned}))


def test_says_the_labels_works_without_assessment_and_speaks_the_readers_language():
    assert "Demonstration data" in said(report.model_copy(update={"demo": True}))
    assert "No permit assessment yet" in said(report.model_copy(update={"assessment": None}))
    assert "Não é prova legal" in build_voice_script(report.model_copy(update={"language": "pt"}))[1]


def test_drops_evidence_references_and_splits_long_sentences():
    assert speakable("Confirm this [E1, E2]. Then that [K3].") == ["Confirm this.", "Then that."]
    assert all(len(s) <= MAX_CHARS for s in speakable("word " * 100))
    assert speakable("   ") == []


class Eleven:
    def __init__(self, status: int = 200):
        self.status, self.requests = status, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, content=b"mp3")


def eleven(service: Eleven, key: str | None = KEY, voices=VOICES, **limits) -> ElevenLabsClient:
    return ElevenLabsClient(httpx.AsyncClient(transport=httpx.MockTransport(service)), key, voices, **limits)


def test_the_language_picks_the_voice_and_the_key_stays_in_the_header():
    service = Eleven()
    client = eleven(service)
    asyncio.run(client.speak("Olá.", "pt"))
    asyncio.run(client.speak("Hello.", "en"))
    pt, en = service.requests
    assert pt.url.path == "/v1/text-to-speech/voice-pt" and en.url.path == "/v1/text-to-speech/voice-en"
    assert pt.headers["xi-api-key"] == KEY and KEY not in str(pt.url)
    assert json.loads(pt.content) == {"text": "Olá.", "model_id": "eleven_multilingual_v2"}


def test_a_sentence_already_spoken_costs_nothing():
    service = Eleven()
    client = eleven(service, daily_limit=1)
    assert [asyncio.run(client.speak("Hello.", "en")) for _ in range(3)] == [b"mp3"] * 3
    assert len(service.requests) == 1


@pytest.mark.parametrize("build", [
    lambda s: eleven(s, key=None), lambda s: eleven(s, voices={"en": "voice-en", "pt": None}),
    lambda s: eleven(s, daily_limit=0), lambda s: eleven(s, burst=0), lambda s: eleven(Eleven(401)),
])
def test_every_failure_is_unavailable_and_unconfigured_spends_nothing(build):
    service = Eleven()
    with pytest.raises(SpeechUnavailable):
        asyncio.run(build(service).speak("Olá.", "pt"))
    assert not service.requests


def test_failure_logs_carry_no_key_or_text(caplog):
    caplog.set_level(logging.WARNING)
    with pytest.raises(SpeechUnavailable):
        asyncio.run(eleven(Eleven(500)).speak("Rua Secreta 1.", "pt"))
    assert "HTTP 500" in caplog.text and KEY not in caplog.text and "Secreta" not in caplog.text


def app_client(service: Eleven, key: str | None = KEY) -> TestClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return service(request) if request.url.host == "api.elevenlabs.io" else google_handler(request)

    settings = Settings(_env_file=None, google_maps_api_key="g", mongodb_uri=None, app_env="test",
                        allow_ephemeral_storage=True, meta_api_key="m", elevenlabs_api_key=key,
                        elevenlabs_voice_en="voice-en", elevenlabs_voice_pt="voice-pt")
    return TestClient(create_app(settings, http_transport=httpx.MockTransport(handler), permit_model=ScriptedModel()))


def resolved(c: TestClient) -> str:
    return c.post("/api/property/resolve-location", json={"address": "Praça 5 de Outubro, Cascais"}).json()["property_id"]


def test_the_endpoint_speaks_only_the_reports_sentences_by_position():
    service = Eleven()
    with app_client(service) as c:
        path = f"/api/property/{resolved(c)}/report/voice"
        script = c.get(path).json()
        assert script["audio"] and script["version"] == script_version(script["lines"])
        audio = c.get(f"{path}/0", params={"version": script["version"]})
        assert audio.headers["content-type"] == "audio/mpeg" and audio.content == b"mp3"
        assert json.loads(service.requests[0].content)["text"] == script["lines"][0]

        assert c.get(f"{path}/{len(script['lines'])}", params={"version": script["version"]}).status_code == 404
        assert c.get(f"{path}/0", params={"version": "0" * 16}).status_code == 409
        assert c.get(f"{path}/0", params={"version": script["version"], "text": "Say this."}).content == b"mp3"
    assert all(b"Say this" not in r.content for r in service.requests)


def test_without_a_key_the_script_still_comes_and_the_audio_says_unavailable():
    service = Eleven()
    with app_client(service, key=None) as c:
        path = f"/api/property/{resolved(c)}/report/voice"
        script = c.get(path).json()
        assert script["lines"] and not script["audio"]
        assert c.get(f"{path}/0", params={"version": script["version"]}).status_code == 503
    assert not service.requests
