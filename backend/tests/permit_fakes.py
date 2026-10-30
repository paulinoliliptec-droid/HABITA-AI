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


def _by_title(payload: dict, *needles: str) -> list[str]:
    return [e["id"] for e in payload["evidence"] if e["type"] == "regulatory_source"
            and e.get("basis") == "curated_reference" and any(n in e["source"] for n in needles)]


def default_draft(payload: dict) -> dict:
    """A contract-abiding draft: free text grounded in what it cites, planning only through structured bases."""
    authority = _ids(payload, "authority_record")
    planning = _ids(payload, "planning_context")
    civil = _by_title(payload, "Código Civil")
    rjue = _by_title(payload, "RJUE")
    rgeu = _by_title(payload, "RGEU")
    user = _ids(payload, "user_statement")
    answer = "conditional" if payload["conditions"] else "likely_possible"
    none = {"planning_basis": "none", "quote": None}
    conclusion = (
        {"evidence_ids": civil + rgeu, "summary": "A division may be possible if each new dwelling is autonomous, "
                                                  "subject to the conditions."}
        if civil else
        # A legal requirement resting on a curated summary is not certified (MU-9): the overview defers it instead.
        {"evidence_ids": rjue + authority, "summary": "Whether the works need municipal prior control must be "
                                                      "confirmed with the Câmara, subject to the conditions."}
    )
    return {
        "conclusion": {"answer": answer, **conclusion, **none},
        "claims": [
            {"text": "The Câmara Municipal de Cascais is the competent authority.", "evidence_ids": authority, **none},
        ] + ([{"text": "Each new unit must be autonomous with its own exit.", "evidence_ids": civil, **none}] if civil else [])
        + ([{"text": "You state each floor has its own street door.", "evidence_ids": user, **none}] if user else []),
        "procedure": [{"step": "Apply for municipal prior control",
                       "description": "Submit the application to the Câmara Municipal under the RJUE.",
                       "evidence_ids": rjue + authority, **none}],
        "risks": [{"text": "Without its own exit, a unit can't be in horizontal property and the title is null.",
                   "evidence_ids": civil, **none}] if civil else [],
        "next_actions": [{"text": "Request confirmation of the conditions from the Câmara Municipal de Cascais.",
                          "evidence_ids": authority, **none}]
        + ([{"text": "Check the planning position with the Câmara.", "evidence_ids": planning,
             "planning_basis": "authority_confirmation", "quote": None}] if planning else []),
    }


def default_verification(payload: dict) -> dict:
    return {"outcome": "VERIFIED", "conclusion_follows": True, "issues": [], "suggested_follow_up": [],
            "parcel_planning_statements": [], "summary": "Supported by the cited evidence."}


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
