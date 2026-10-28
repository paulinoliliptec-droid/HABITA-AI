"""Deterministic stand-in for Muse Spark, speaking the same ReasoningModel protocol.

It reads the real prompts' payloads (checklist, evidence list, inputs) and answers
like a well-behaved model would, so tests exercise the actual workflow, tools,
persistence and verifier. Individual behaviours can be overridden per test.
"""

import json
from typing import Any, Callable

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.permit.model import ChatResult, ToolCall
from tests import fixtures

CONVERSION_QUESTION = "Can I convert this property into two residential units?"
USER_KEYS = ("current_licensed_use", "intended_use", "ownership_status")
ANSWERS = {
    "current_licensed_use": "One single-family dwelling (habitação).",
    "intended_use": "Two flats, one per floor, about 90 m2 each; each floor has its own street door.",
    "ownership_status": "Single owner; not divided into fractions.",
}


def default_checklist(payload: dict) -> dict:
    return {
        "intent": "unit_conversion",
        "intent_summary": "Divide the existing dwelling into two independent residential units.",
        "questions": [{"key": "intended_use", "question": "How would the two flats be laid out, and would each have its own door?"}],
    }


def default_investigation(round_no: int, messages: list[dict]) -> list[ToolCall]:
    if round_no == 0:
        return [
            ToolCall("call_1", "search_regulatory_sources", {
                "topics": ["unit_division", "horizontal_property", "licensing_procedure"],
                "query": "divide a dwelling into two residential units",
            }),
            ToolCall("call_2", "request_missing_information", {"items": [
                {"item_key": "current_licensed_use", "question": "What is the property's currently licensed use?",
                 "reason": "A division depends on the licensed use.", "owner": "USER"},
            ]}),
        ]
    return []


def _ids(payload: dict, kind: str) -> list[str]:
    return [e["id"] for e in payload["evidence"] if e["type"] == kind]


def default_draft(payload: dict) -> dict:
    authority = _ids(payload, "authority_record")
    sources = _ids(payload, "regulatory_source")
    user = _ids(payload, "user_statement")
    answer = "conditional" if payload["conditions"] else "likely_possible"
    return {
        "conclusion": {"answer": answer, "evidence_ids": sources[:2],
                       "summary": "A division may be possible if each unit is autonomous and the PDM allows it on this parcel."},
        "claims": [
            {"text": "The Câmara Municipal de Cascais is the competent authority.", "evidence_ids": authority},
            {"text": "Each new unit must be autonomous with its own exit.", "evidence_ids": sources[:2]},
        ] + ([{"text": "You state each unit can have its own entrance.", "evidence_ids": user}] if user else []),
        "procedure": [{"step": "Confirm the parcel's PDM category", "description": "Check the planta de ordenamento.",
                       "evidence_ids": sources[-1:]}],
        "risks": [{"text": "The parcel's land-use category may limit dwellings.", "evidence_ids": sources[-1:]}],
        "next_actions": [{"text": "Request the parcel's planning information from the Câmara Municipal.",
                          "evidence_ids": authority}],
    }


def default_verification(payload: dict) -> dict:
    return {"outcome": "VERIFIED", "conclusion_follows": True, "issues": [], "suggested_follow_up": [],
            "summary": "Supported by the cited evidence."}


class ScriptedModel:
    model_id = "muse-spark-1.3"

    def __init__(self, **overrides: Callable) -> None:
        self.checklist = overrides.get("checklist", default_checklist)
        self.investigation = overrides.get("investigation", default_investigation)
        self.draft = overrides.get("draft", default_draft)
        self.verification = overrides.get("verification", default_verification)
        self.calls: list[str] = []
        self._rounds = 0

    async def chat(self, messages: list[dict[str, Any]], *, tools=None, response_schema=None, schema_name=None) -> ChatResult:
        payload = json.loads(messages[-1]["content"]) if messages[-1]["role"] == "user" else {}
        if tools:
            # A new investigation conversation starts with system + user only.
            if len(messages) == 2:
                self._rounds = 0
            self.calls.append("investigate")
            calls = self.investigation(self._rounds, messages)
            self._rounds += 1
            return ChatResult(content=None if calls else "Done.", tool_calls=tuple(calls),
                              finish_reason="tool_calls" if calls else "stop")
        self.calls.append(schema_name)
        handler = {"checklist": self.checklist, "draft": self.draft, "verification": self.verification}[schema_name]
        return ChatResult(content=json.dumps(handler(payload)), finish_reason="stop")


def google_handler(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    if "Mountain View" in params.get("address", ""):
        return httpx.Response(200, json=fixtures.mountain_view())
    return httpx.Response(200, json=fixtures.cascais(params.get("language", "pt")))


def make_client(model: ScriptedModel | None = None, **overrides) -> TestClient:
    values = {
        "_env_file": None, "google_maps_api_key": "test-key", "mongodb_uri": None, "app_env": "test",
        "allow_ephemeral_storage": True, "meta_api_key": "test-meta-key", "permit_rate_per_minute": 1000,
        "permit_burst": 1000,
    }
    settings = Settings(**{**values, **overrides})
    return TestClient(create_app(settings, http_transport=httpx.MockTransport(google_handler), permit_model=model))


def resolve_cascais(client: TestClient) -> str:
    res = client.post("/api/property/resolve-location", json={"address": "Praça 5 de Outubro, Cascais"})
    assert res.status_code == 200, res.text
    return res.json()["property_id"]
