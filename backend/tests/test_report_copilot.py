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
