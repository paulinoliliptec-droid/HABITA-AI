"""HR-003 × HR-002: the Permit agent consumes only trusted official sources, with provenance.

Property → jurisdiction → official sources → planning context → regulatory evidence → Permit reasoning.
"""

from datetime import UTC, datetime

import httpx
import pytest

from app.schemas.permit import Evidence
from app.schemas.sources import SourceProvenance
from app.services.permit.verifier import rule_checks, source_problem
from app.services.sources.fetcher import SafeFetcher
from app.services.sources.ingest import SourceIngestor
from app.services.sources.registry import OFFICIAL_HOSTS
from tests.pdf_fixture import REGULAMENTO_PAGES, make_pdf
from tests.permit_fakes import ANSWERS, CONVERSION_QUESTION, ScriptedModel, make_client, resolve_cascais
from tests.test_permit_verifier import CHAIN, checklist, draft, matter

NOW = datetime(2026, 10, 28, tzinfo=UTC)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ingest_regulamento(client) -> None:
    async def run():
        async def public(host):
            return ["193.236.10.10"]
        pdf = make_pdf(REGULAMENTO_PAGES)
        fetcher = SafeFetcher(OFFICIAL_HOSTS, resolver=public, transport=httpx.MockTransport(
            lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf)))
        report = await SourceIngestor(client.app.state.official_sources, fetcher).ingest("cascais-pdm")
        assert report.outcome == "new_snapshot"
    client.portal.call(run)


def retire(client, source_id: str) -> None:
    registry = client.app.state.official_sources
    client.portal.call(lambda: registry.change_status(source_id, "retired", operator="ops", reason="test"))


def run_matter(client, *, after_first_continue=None) -> tuple[str, str]:
    pid = resolve_cascais(client)
    created = client.post("/api/permit/matters", json={"property_id": pid, "question": CONVERSION_QUESTION}).json()
    mid, token = created["matter"]["matter_id"], created["access_token"]
    assert client.post(f"/api/permit/matters/{mid}/continue", headers=auth(token)).json()["state"] == "NEEDS_INPUT"
    if after_first_continue:
        after_first_continue()
    client.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": ANSWERS}, headers=auth(token))
    client.post(f"/api/permit/matters/{mid}/continue", headers=auth(token))
    return mid, token


@pytest.fixture
def app_client():
    with make_client(ScriptedModel()) as c:
        yield c


def test_cascais_path_property_to_permit_with_official_evidence(app_client):
    ingest_regulamento(app_client)
    mid, token = run_matter(app_client)
    matter = app_client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
    assert matter["state"] == "VERIFIED"
    evidence = app_client.get(f"/api/permit/matters/{mid}/evidence", headers=auth(token)).json()

    planning = [e for e in evidence if e["source_type"] == "planning_context"]
    assert len(planning) == 1
    assert planning[0]["structured"]["status"] == "requires_manual_confirmation"
    assert planning[0]["excerpt"].startswith("Planning classification requires confirmation against the official")
    assert planning[0]["provenance"]["source_id"] == "cascais-pdm"

    official = [e for e in evidence if e["verification_status"] == "official_text"]
    assert official, "the PDM Regulamento's official text reaches the agent"
    for e in official:
        p = e["provenance"]
        assert p["basis"] == "official_text" and p["trust_status"] == "trusted" and len(p["sha256"]) == 64
        assert p["snapshot_id"] and p["retrieved_at"] and p["locator"].startswith("Artigo")
        assert e["jurisdiction_id"] == "pt/lisboa/cascais" and e["source_url"].startswith("https://www.cascais.pt/")
    for e in evidence:
        if e["source_type"] == "regulatory_source":
            assert e["provenance"]["trust_status"] == "trusted"

    items = {i["key"]: i for i in app_client.get(f"/api/permit/matters/{mid}/checklist", headers=auth(token)).json()["items"]}
    assert items["planning_constraints"]["status"] == "blocked_external"
    assert planning[0]["evidence_id"] in items["planning_constraints"]["evidence_ids"]
    condition = next(c["text"] for c in matter["draft"]["conditions"] if c["item_key"] == "planning_constraints")
    assert "Planta de Ordenamento 01-02" in condition
    assert app_client.get(f"/api/permit/matters/{mid}/verification", headers=auth(token)).json()["checks"]["sources_trusted"]


def test_untrusted_sources_never_become_evidence(app_client):
    ingest_regulamento(app_client)
    retire(app_client, "cascais-pdm")  # the instrument, its official text and its curated finding
    mid, token = run_matter(app_client)
    evidence = app_client.get(f"/api/permit/matters/{mid}/evidence", headers=auth(token)).json()
    sourced = [e for e in evidence if e["source_type"] in ("regulatory_source", "planning_context")]
    assert sourced and all(e["provenance"]["source_id"] != "cascais-pdm" for e in sourced)
    assert not any(e["source_type"] == "planning_context" for e in evidence)


def test_a_source_retired_after_retrieval_is_kept_as_history_but_no_longer_relied_on(app_client):
    ingest_regulamento(app_client)
    mid, token = run_matter(app_client, after_first_continue=lambda: retire(app_client, "cascais-pdm"))
    evidence = app_client.get(f"/api/permit/matters/{mid}/evidence", headers=auth(token)).json()
    retired = {e["evidence_id"] for e in evidence if (e.get("provenance") or {}).get("source_id") == "cascais-pdm"}
    assert retired, "historical records collected while trusted are preserved"
    report = app_client.get(f"/api/permit/matters/{mid}/verification", headers=auth(token)).json()
    assert retired <= {x["evidence_id"] for x in report["excluded_evidence"]}
    matter = app_client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
    draft = matter["draft"]
    cited = set(draft["conclusion"]["evidence_ids"]) | {i for section in ("claims", "procedure", "risks", "next_actions")
                                                       for entry in draft[section] for i in entry["evidence_ids"]}
    assert not cited & retired
    items = app_client.get(f"/api/permit/matters/{mid}/checklist", headers=auth(token)).json()["items"]
    assert not {i for item in items for i in item["evidence_ids"]} & retired


async def test_the_model_cannot_pass_a_url_or_promote_a_source():
    from app.services.permit.tools import PermitTools
    from app.services.permit.sources.base import SourceRegistry
    tools = PermitTools(matter=matter(), repository=None, properties=None, sources=SourceRegistry([]))  # type: ignore[arg-type]
    out = await tools.execute("search_regulatory_sources", {
        "topics": ["land_use_planning"], "query": "zoning", "url": "http://169.254.169.254/"})
    assert out == {"ok": False, "error": "Invalid arguments for 'search_regulatory_sources'."}
    for name in ("promote_source", "fetch_url", "add_source"):
        assert (await tools.execute(name, {}))["ok"] is False


def sourced(eid: str, source_id: str | None, basis="official_text", sha="a" * 64, **kw) -> Evidence:
    provenance = SourceProvenance(source_id=source_id, basis=basis, trust_status="trusted",
                                  snapshot_id="ss_1" if sha else None, sha256=sha) if source_id else None
    return Evidence(evidence_id=eid, matter_id="pm_0000000000000001", source_type="regulatory_source", source_title="t",
                    source_reference="r", jurisdiction_id="pt/lisboa/cascais", retrieved_at=NOW, claim_supported="x",
                    excerpt="y", confidence="medium", verification_status=basis if basis != "planning_context" else "system_record",
                    dedupe_key=eid, provenance=provenance, **kw)


@pytest.mark.parametrize("record, trusted, problem", [
    (sourced("E1", "cascais-pdm"), {"cascais-pdm"}, None),
    (sourced("E1", "cascais-geocascais"), {"cascais-pdm"}, "not currently a trusted official source"),
    (sourced("E1", "cascais-pdm", sha=None), {"cascais-pdm"}, "without a pinned snapshot"),
    (sourced("E1", None, structured={}), {"cascais-pdm"}, "no source provenance"),
    # HR-002 records (no provenance block) are still checked through their structured source_id.
    (sourced("E1", None, basis="curated_reference", structured={"source_id": "pt-rjue"}), {"pt-rjue"}, None),
    (sourced("E1", None, basis="curated_reference", structured={"source_id": "pt-rjue"}), set(), "not currently a trusted"),
])
def test_verifier_source_rule(record, trusted, problem):
    found = source_problem(record, trusted)
    assert (found is None) if problem is None else (problem in found)


def test_untrusted_cited_evidence_rejects_the_draft():
    issues, checks = rule_checks(matter(), checklist(), draft(), [sourced("E1", "cascais-geocascais")], CHAIN,
                                 {"cascais-pdm"})
    assert "untrusted_source" in {i.code for i in issues} and checks["sources_trusted"] is False


@pytest.mark.parametrize("determined, status", [(True, "satisfied"), (False, "blocked_external")])
def test_planning_item_is_settled_only_by_an_authoritative_determination(determined, status):
    from app.services.permit import requirements
    planning = Evidence(
        evidence_id="E9", matter_id="pm_0000000000000001", source_type="planning_context", source_title="Planning",
        source_reference="r", jurisdiction_id="pt/lisboa/cascais", retrieved_at=NOW, claim_supported="x", excerpt="y",
        confidence="low", verification_status="system_record", dedupe_key="planning",
        structured={"status": "resolved" if determined else "requires_manual_confirmation",
                    "authoritative_determination": determined,
                    "documents_to_consult": [] if determined else [{"designation": "Planta de Ordenamento 01-02"}]},
    )
    items = requirements.reconcile("general_overview", requirements.build_checklist_items("general_overview", {}), [planning])
    item = next(i for i in items if i.key == "planning_constraints")
    assert item.status == status and item.evidence_ids == ["E9"]
    conditions = requirements.conditions_for("general_overview", items, [planning])
    if determined:
        assert all(c["item_key"] != "planning_constraints" for c in conditions)
    else:
        text = next(c["text"] for c in conditions if c["item_key"] == "planning_constraints")
        assert text.endswith("Check against the official documents: Planta de Ordenamento 01-02.")
