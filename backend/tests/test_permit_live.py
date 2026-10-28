"""Opt-in live tests for HR-002.

- HABITA_LIVE_TESTS=1 (+ MONGODB_URI): the permit repository against MongoDB Atlas.
- HABITA_META_LIVE=1 (+ META_API_KEY, GOOGLE_MAPS_API_KEY): Muse Spark through the
  real Meta Model API, including a full permit run for a Cascais property.
Test data is removed afterwards.
"""

import asyncio
import json
import os
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from pymongo import AsyncMongoClient

from app.core.config import Settings
from app.integrations.meta.client import MetaChatModel
from app.main import create_app
from app.schemas.permit import Checklist, ChecklistItem, Evidence, MatterState, PermitMatter, VerificationReport
from app.services.permit.repository import MongoPermitRepository, hash_token, new_matter_id, new_verification_id

atlas = pytest.mark.skipif(os.getenv("HABITA_LIVE_TESTS") != "1", reason="live test: set HABITA_LIVE_TESTS=1")
meta = pytest.mark.skipif(os.getenv("HABITA_META_LIVE") != "1", reason="live Meta test: set HABITA_META_LIVE=1")


@atlas
def test_permit_repository_on_atlas():
    settings = Settings(app_env="test")
    assert settings.mongodb_uri

    async def run():
        client = AsyncMongoClient(settings.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=8000, tz_aware=True)
        repo = MongoPermitRepository(client, settings.mongodb_db_name)
        db = client[settings.mongodb_db_name]
        await repo.ensure_indexes()
        now = datetime.now(UTC)
        mid = new_matter_id()
        try:
            matter = PermitMatter(matter_id=mid, property_id="prp_0000000000000000", question="HABITA live test",
                                  state=MatterState.PLANNING, jurisdiction_id="pt/lisboa/cascais", created_at=now, updated_at=now)
            await repo.create_matter(matter, hash_token("live-test-token"))
            assert await repo.has_access(mid, hash_token("live-test-token"))
            assert not await repo.has_access(mid, hash_token("wrong"))
            assert "live-test-token" not in str(await db["permit_matters"].find_one({"_id": mid}))
            assert await repo.acquire(mid) and not await repo.acquire(mid)  # lease is exclusive
            await repo.release(mid)
            await repo.save_checklist(Checklist(matter_id=mid, intent="unit_conversion", intent_summary="s",
                                                items=[ChecklistItem(key="jurisdiction", area="jurisdiction", question="q", required=True, owner="SYSTEM_TOOL")],
                                                model_id="m", created_at=now, updated_at=now))
            base = dict(matter_id=mid, source_type="regulatory_source", source_title="RJUE", source_reference="DL 555/99",
                        jurisdiction_id="pt", retrieved_at=now, claim_supported="x", excerpt="y", confidence="medium",
                        verification_status="curated_reference")
            e1 = await repo.add_evidence(Evidence(evidence_id="pending", dedupe_key="a", **base))
            e2 = await repo.add_evidence(Evidence(evidence_id="pending", dedupe_key="b", **base))
            again = await repo.add_evidence(Evidence(evidence_id="pending", dedupe_key="a", **base))
            report = VerificationReport(verification_id=new_verification_id(), matter_id=mid, draft_revision=0,
                                        outcome="NEEDS_INPUT", issues=[], checks={}, created_at=now)
            await repo.save_verification(report)
            matter.state = MatterState.NEEDS_INPUT
            await repo.save_matter(matter)
            return (e1.evidence_id, e2.evidence_id, again.evidence_id,
                    [e.evidence_id for e in await repo.list_evidence(mid)],
                    (await repo.get_matter(mid)).state, (await repo.latest_verification(mid)).outcome,
                    (await repo.get_checklist(mid)).items[0].key)
        finally:
            for name in ("permit_matters", "permit_checklists"):
                await db[name].delete_one({"_id": mid})
            await db["permit_evidence"].delete_many({"matter_id": mid})
            await db["permit_verifications"].delete_many({"matter_id": mid})
            await client.close()

    e1, e2, again, listed, state, outcome, key = asyncio.run(run())
    assert (e1, e2, again, listed) == ("E1", "E2", "E1", ["E1", "E2"])
    assert (state, outcome, key) == (MatterState.NEEDS_INPUT, "NEEDS_INPUT", "jurisdiction")


def _meta_model(http: httpx.AsyncClient) -> MetaChatModel:
    settings = Settings(app_env="test")
    assert settings.meta_api_key, "META_API_KEY missing"
    return MetaChatModel(http, api_key=settings.meta_api_key.get_secret_value(), base_url=settings.meta_api_base_url,
                         model_id=settings.meta_text_model)


@meta
def test_muse_spark_structured_output_and_tool_calling():
    async def run():
        async with httpx.AsyncClient(timeout=120) as http:
            model = _meta_model(http)
            schema = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"], "additionalProperties": False}
            structured = await model.chat([{"role": "user", "content": "Which city is the Câmara Municipal de Cascais in? Answer as JSON."}],
                                          response_schema=schema, schema_name="city")
            tools = [{"type": "function", "function": {"name": "get_property_context", "description": "Property facts.",
                                                       "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}}]
            tooled = await model.chat([{"role": "user", "content": "Call get_property_context, then stop."}], tools=tools)
            return json.loads(structured.content), tooled

    data, tooled = asyncio.run(run())
    assert "cascais" in data["city"].lower()
    assert tooled.tool_calls and tooled.tool_calls[0].name == "get_property_context"


class MeteredModel:
    """Wraps the real Muse Spark client and measures calls, tokens, latency and tool calls."""

    def __init__(self, inner: MetaChatModel) -> None:
        self.inner = inner
        self.model_id = inner.model_id
        self.calls: list[dict] = []

    async def chat(self, messages, **kwargs):
        import time

        started = time.monotonic()
        result = await self.inner.chat(messages, **kwargs)
        self.calls.append({
            "kind": kwargs.get("schema_name") or "investigate",
            "seconds": time.monotonic() - started,
            "prompt_tokens": result.usage.get("prompt_tokens") or 0,
            "completion_tokens": result.usage.get("completion_tokens") or 0,
            "tool_calls": [c.name for c in result.tool_calls],
        })
        return result


DEMO_ANSWERS = {
    "current_licensed_use": "TEST DATA: licensed as one single-family dwelling (habitação).",
    "intended_use": "TEST DATA: two flats, one per floor, about 90 m2 each; each floor has its own street door.",
    "ownership_status": "TEST DATA: single owner; not divided into fractions.",
}


@meta
def test_full_permit_run_with_muse_spark():
    """The demo path on the real model: ask only user-owned facts, resume, draft, verify, converge."""
    import time

    settings = Settings(app_env="test")
    http = httpx.AsyncClient(timeout=settings.meta_timeout_seconds)
    metered = MeteredModel(_meta_model(http))
    started = time.monotonic()
    with TestClient(create_app(settings, permit_model=metered)) as client:
        prop = client.post("/api/property/resolve-location", json={"address": "Avenida 25 de Abril 1011, Cascais"}).json()
        created = client.post("/api/permit/matters", json={"property_id": prop["property_id"],
                                                           "question": "Can I convert this property into two residential units?"}).json()
        mid = created["matter"]["matter_id"]
        client.headers["Authorization"] = f"Bearer {created['access_token']}"
        try:
            first = client.post(f"/api/permit/matters/{mid}/continue").json()
            questions = [m["input_key"] for m in first["missing_inputs"]]
            answers = {k: DEMO_ANSWERS.get(k, "TEST DATA: unknown.") for k in questions}
            if first["state"] == "NEEDS_INPUT":
                client.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": answers})
            final = client.post(f"/api/permit/matters/{mid}/continue").json()
            evidence = client.get(f"/api/permit/matters/{mid}/evidence").json()
            checklist = client.get(f"/api/permit/matters/{mid}/checklist").json()
            verification = client.get(f"/api/permit/matters/{mid}/verification")
        finally:
            repo = client.app.state.permit_workflow._repo
            if hasattr(repo, "_matters"):
                async def cleanup():
                    await repo._matters.delete_one({"_id": mid})
                    await repo._checklists.delete_one({"_id": mid})
                    await repo._evidence.delete_many({"matter_id": mid})
                    await repo._verifications.delete_many({"matter_id": mid})
                client.portal.call(cleanup)
            client.portal.call(http.aclose)  # close on the loop that used it
    duration = time.monotonic() - started

    metrics = {
        "first_state": first["state"],
        "final_state": final["state"],
        "rounds": final["rounds"],
        "user_questions": questions,
        "meta_calls": len(metered.calls),
        "calls_by_kind": [c["kind"] for c in metered.calls],
        "tool_calls": [t for c in metered.calls for t in c["tool_calls"]],
        "input_tokens": sum(c["prompt_tokens"] for c in metered.calls),
        "output_tokens": sum(c["completion_tokens"] for c in metered.calls),
        "model_seconds": round(sum(c["seconds"] for c in metered.calls), 1),
        "call_seconds": [round(c["seconds"], 1) for c in metered.calls],
        "duration_seconds": round(duration, 1),
        "evidence": len(evidence),
        "checklist": {i["key"]: i["status"] for i in checklist["items"]},
        "verification": verification.json() if verification.status_code == 200 else None,
        "conclusion": (final.get("draft") or {}).get("conclusion"),
        "escalation_reason": final.get("escalation_reason"),
    }
    print("\nPERMIT_LIVE_METRICS " + json.dumps(metrics, ensure_ascii=False, default=str))

    # Convergence, not a forced verdict.
    assert final["state"] in {"VERIFIED", "NEEDS_INPUT", "ESCALATE", "REJECTED"}, final
    assert len(questions) <= 3 and set(questions) <= set(DEMO_ANSWERS)
    assert final["draft"] is None or final["draft"]["status"] == "UNVERIFIED"
    assert any(e["source_type"] == "regulatory_source" for e in evidence)
    assert len(metered.calls) <= 8
