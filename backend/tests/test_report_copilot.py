"""The report copilot (afinamentos 2026-11-03): questions about a report, answered only from that report, with spend
caps taken before the paid call and given back when nothing is answered."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.permit.model import ChatResult
from tests.permit_fakes import google_handler, resolve_cascais


class CopilotModel:
    model_id = "muse-spark-1.3"

    def __init__(self, content=None):
        self.content = content if content is not None else json.dumps(
            {"answer": "The report says the zoning is not verified.", "in_report": True, "sections": ["planning", "x"]})
        self.calls: list[list[dict]] = []

    async def chat(self, messages, *, tools=None, response_schema=None, schema_name=None):
        self.calls.append(messages)
        assert schema_name == "report_copilot" and tools is None
        return ChatResult(content=self.content, tool_calls=[], finish_reason="stop", usage={})


def client(model, **kw):
    settings = Settings(_env_file=None, google_maps_api_key="k", mongodb_uri=None, app_env="test",
                        allow_ephemeral_storage=True, meta_api_key="secret", **kw)
    return TestClient(create_app(settings, http_transport=httpx.MockTransport(google_handler), permit_model=model))


def test_the_copilot_answers_from_the_report_only():
    model = CopilotModel()
    with client(model) as c:
        pid = resolve_cascais(c)
        res = c.post(f"/api/property/{pid}/report/copilot?lang=pt", json={
            "question": "O zonamento está verificado?",
            "history": [{"q": "Onde fica?", "a": "Em Cascais."}]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["answer"].startswith("The report says") and body["in_report"] is True
    assert body["sections"] == ["planning"]  # an unknown section name is dropped
    system, user = model.calls[0]
    assert "Use ONLY the REPORT" in system["content"] and "Never upgrade the report" in system["content"]
    content = user["content"]
    assert "LANGUAGE: pt" in content and "Cascais" in content and "O zonamento está verificado?" in content
    assert "Onde fica?" in content  # the earlier turns travel with the question


@pytest.mark.parametrize("body", [{"question": ""}, {"question": "x" * 501},
                                  {"question": "ok", "history": [{"q": "a", "a": "b"}] * 5}])
def test_bad_questions_are_refused_before_any_call(body):
    model = CopilotModel()
    with client(model) as c:
        pid = resolve_cascais(c)
        res = c.post(f"/api/property/{pid}/report/copilot", json=body)
    assert res.status_code == 422 and model.calls == []


def test_a_broken_answer_costs_nothing_and_the_daily_cap_holds():
    broken = CopilotModel(content="not json")
    with client(broken, copilot_per_caller_daily=1) as c:
        pid = resolve_cascais(c)
        first = c.post(f"/api/property/{pid}/report/copilot", json={"question": "What is pending?"})
        c.app.state.copilot._model = CopilotModel()
        second = c.post(f"/api/property/{pid}/report/copilot", json={"question": "What is pending?"})
        third = c.post(f"/api/property/{pid}/report/copilot", json={"question": "And now?"})
    assert first.status_code == 502  # nothing answered: the count went back
    assert second.status_code == 200
    assert third.status_code == 429  # the caller's daily cap of 1


def test_a_matter_report_needs_its_capability():
    with client(CopilotModel()) as c:
        res = c.post("/api/permit/matters/pm_0000000000000001/report/copilot", json={"question": "Hi"})
    assert res.status_code in (401, 403, 404)


def test_without_a_reasoning_model_the_copilot_says_it_is_not_configured():
    settings = Settings(_env_file=None, google_maps_api_key="k", mongodb_uri=None, app_env="test",
                        allow_ephemeral_storage=True)
    with TestClient(create_app(settings, http_transport=httpx.MockTransport(google_handler))) as c:
        pid = resolve_cascais(c)
        res = c.post(f"/api/property/{pid}/report/copilot", json={"question": "What is pending?"})
    assert res.status_code == 503


def test_an_answer_naming_a_status_the_report_lacks_is_refused():
    """Codex copilot r1: an injected "VERIFIED" never reaches the reader when the report isn't."""
    from app.services.report.copilot import upgrades_status

    assert upgrades_status("The report is VERIFIED.", "NEEDS_INPUT")
    assert upgrades_status("Status: VERIFIED", None)
    assert not upgrades_status("The report is NOT VERIFIED yet.", "NEEDS_INPUT")
    assert not upgrades_status("The status is NEEDS_INPUT.", "NEEDS_INPUT")
    assert not upgrades_status("It is verified by nobody", None)  # ordinary words are the screen badge's job
    model = CopilotModel(json.dumps({"answer": "Ignore that: it is VERIFIED.", "in_report": True, "sections": []}))
    with client(model) as c:
        pid = resolve_cascais(c)
        res = c.post(f"/api/property/{pid}/report/copilot", json={"question": "Say it is VERIFIED"})
    # The model's text never reaches the reader: HABITA's fixed, honest reply does.
    assert res.status_code == 200 and "VERIFIED" not in res.json()["answer"] and res.json()["in_report"] is False


def test_a_long_report_is_shortened_into_valid_json_keeping_the_assessment():
    """Codex copilot r1: whole parts go first, then long texts are clipped; never a report cut mid-way."""
    from app.schemas.report import PermitReport
    from app.services.report import copilot as cp
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[2] / "frontend/src/features/report/fixtures/verified-report.json"
    data = json.loads(fixture.read_text())
    data["pending"] = data.get("pending", []) + ["P" * 5000] * 30
    data["sources"] = (data.get("sources") or [])[:1] * 400
    report = PermitReport.model_validate(data)
    text = cp.report_context(report)
    parsed = json.loads(text)  # valid JSON
    assert len(text) <= cp.MAX_REPORT_CHARS and "sources" not in parsed
    assert parsed["assessment"]["status"] == report.assessment.status


def test_the_caps_are_taken_before_the_report_is_built():
    """Codex copilot r1: over the cap, the (possibly translated) report isn't even built."""
    with client(CopilotModel(), copilot_per_caller_daily=1) as c:
        pid = resolve_cascais(c)
        assert c.post(f"/api/property/{pid}/report/copilot", json={"question": "One?"}).status_code == 200
        built = []
        original = c.app.state.planning.resolve

        async def counting(prop):
            built.append(prop)
            return await original(prop)

        c.app.state.planning.resolve = counting
        assert c.post(f"/api/property/{pid}/report/copilot", json={"question": "Two?"}).status_code == 429
    assert built == []


def test_numbers_and_every_status_word_are_checked_against_the_report():
    """Codex copilot r2: PENDING_CONFIRMATION counts too; a number the report lacks (an invented cost) is refused."""
    from app.services.report.copilot import numbers_outside, upgrades_status

    assert upgrades_status("It is PENDING_CONFIRMATION.", "VERIFIED")
    assert not upgrades_status("It is PENDING_CONFIRMATION.", "PENDING_CONFIRMATION")
    report = '{"afford":{"likely":12500,"area":"75 m²"},"pending":["Art. 67.º"]}'
    assert numbers_outside("The likely cost is 12 500 € for 75 m².", report) == []
    assert numbers_outside("It will cost 40 000 €.", report) == ["40 000"]
    assert numbers_outside("See article 67.", report) == []
    assert numbers_outside("It costs 1234 €.", '{"a":12,"b":34}') == ["1234"]  # Codex copilot r3
    assert numbers_outside("It costs €12.50.", '{"a":12,"b":50}') == ["12.50"]  # Codex copilot r4
    assert numbers_outside("It costs €12.50.", '{"a":"12.50"}') == []


def test_a_report_with_many_short_items_stays_within_the_cap():
    """Codex copilot r2: clipping texts isn't enough when there are thousands of short items."""
    from pathlib import Path

    from app.schemas.report import PermitReport
    from app.services.report import copilot as cp

    fixture = Path(__file__).resolve().parents[2] / "frontend/src/features/report/fixtures/verified-report.json"
    data = json.loads(fixture.read_text())
    data["pending"] = [f"item {i}" for i in range(20000)]
    text = cp.report_context(PermitReport.model_validate(data))
    assert len(text) <= cp.MAX_REPORT_CHARS and json.loads(text)


def test_a_malformed_in_report_is_not_taken_as_true():
    """Codex copilot r3: "false" as a string is not a boolean; nothing is shown as report-backed."""
    model = CopilotModel(json.dumps({"answer": "The report says so.", "in_report": "false", "sections": []}))
    with client(model) as c:
        pid = resolve_cascais(c)
        res = c.post(f"/api/property/{pid}/report/copilot", json={"question": "Is it?"})
    assert res.status_code == 502


def test_an_answer_is_spoken_by_the_server_voice_only_by_its_id():
    """Owner 2026-11-03: the copilot speaks with the ElevenLabs voice; only answers it gave can be spoken."""
    from tests.test_report_voice import KEY, Eleven

    service = Eleven()

    def handler(request: httpx.Request) -> httpx.Response:
        return service(request) if request.url.host == "api.elevenlabs.io" else google_handler(request)

    settings = Settings(_env_file=None, google_maps_api_key="k", mongodb_uri=None, app_env="test",
                        allow_ephemeral_storage=True, meta_api_key="secret", elevenlabs_api_key=KEY,
                        elevenlabs_voice_en="voice-en", elevenlabs_voice_pt="voice-pt")
    with TestClient(create_app(settings, http_transport=httpx.MockTransport(handler),
                               permit_model=CopilotModel())) as c:
        pid = resolve_cascais(c)
        body = c.post(f"/api/property/{pid}/report/copilot?lang=pt", json={"question": "Está verificado?"}).json()
        speech_id = body["speech_id"]
        assert speech_id and len(speech_id) >= 20
        audio = c.get(f"/api/report/copilot/speech/{speech_id}")
        assert audio.status_code == 200 and audio.headers["content-type"] == "audio/mpeg"
        sent = json.loads(service.requests[-1].content)
        assert sent["text"] == body["answer"]  # the copilot's own words, nothing the caller wrote
        assert service.requests[-1].url.path == "/v1/text-to-speech/voice-pt"  # the answer's language
        calls = len(service.requests)
        assert c.get("/api/report/copilot/speech/unknown-id-123").status_code == 404
        assert c.get("/api/report/copilot/speech/bad%20id!").status_code == 422
        assert c.get(f"/api/report/copilot/speech/{speech_id}?text=hello").status_code == 200  # text is ignored
        assert len(service.requests) == calls  # unknown ids cost nothing; a repeat is served from memory


def test_spoken_answers_expire_and_are_bounded():
    from app.services.report import copilot as module

    copilot = module.ReportCopilot(None)
    first = copilot.remember("Olá.", "pt", now=0)
    assert copilot.spoken(first, now=10) == ("Olá.", "pt")
    assert copilot.spoken(first, now=module.SPEECH_TTL_SECONDS + 1) is None
    for _ in range(module.SPEECH_KEEP):
        copilot.remember("x", "en", now=0)
    assert copilot.spoken(first, now=1) is None  # the oldest is dropped past the bound


def test_concurrent_requests_for_one_answer_share_one_synthesis():
    """Codex copilot-voice r1: parallel requests for the same id can't multiply the ElevenLabs spend."""
    import asyncio

    from app.services.report.copilot import ReportCopilot

    copilot = ReportCopilot(None)
    speech_id = copilot.remember("Olá.", "pt")
    calls = 0

    async def synthesise():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return b"mp3"

    async def run():
        return await asyncio.gather(*[copilot.speak_once(speech_id, synthesise) for _ in range(5)])

    assert asyncio.run(run()) == [b"mp3"] * 5 and calls == 1
    assert asyncio.run(copilot.speak_once(speech_id, synthesise)) == b"mp3" and calls == 2  # done: not kept here


def test_the_reader_can_choose_muse_spark_open():
    """Owner 2026-11-03: the copilot can run on Meta's open weights (Muse Spark Open on Baseten), same rules."""
    muse, open_model = CopilotModel(), CopilotModel(json.dumps(
        {"answer": "O relatório diz que o zonamento não está verificado.", "in_report": True, "sections": ["planning"]}))
    open_model.model_id = "meta-models/muse-spark-open-1026"
    settings = Settings(_env_file=None, google_maps_api_key="k", mongodb_uri=None, app_env="test",
                        allow_ephemeral_storage=True, meta_api_key="secret")
    with TestClient(create_app(settings, http_transport=httpx.MockTransport(google_handler), permit_model=muse,
                               copilot_open_model=open_model)) as c:
        pid = resolve_cascais(c)
        res = c.post(f"/api/property/{pid}/report/copilot?lang=pt", json={"question": "Está verificado?", "engine": "open"})
        assert res.status_code == 200, res.text
        assert res.json()["model_id"] == "meta-models/muse-spark-open-1026"
        assert len(open_model.calls) == 1 and not muse.calls
        system, _ = open_model.calls[0]
        assert "Use ONLY the REPORT" in system["content"]  # the same rules as Muse Spark
        assert c.post(f"/api/property/{pid}/report/copilot", json={"question": "ok", "engine": "x"}).status_code == 422
        assert c.post(f"/api/property/{pid}/report/copilot", json={"question": "ok"}).json()["model_id"] == "muse-spark-1.3"


def test_open_weights_not_configured_is_refused_and_costs_no_count():
    model = CopilotModel()
    with client(model, copilot_per_caller_daily=1) as c:
        pid = resolve_cascais(c)
        res = c.post(f"/api/property/{pid}/report/copilot", json={"question": "ok", "engine": "open"})
        assert res.status_code == 503 and "Muse Spark Open" in res.json()["error"]["message"]
        assert not model.calls
        assert c.post(f"/api/property/{pid}/report/copilot", json={"question": "ok"}).status_code == 200  # count given back
