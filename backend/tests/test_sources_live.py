"""Opt-in (HABITA_LIVE_TESTS=1): ingest the real official Cascais documents through the SafeFetcher."""

import os

import pytest

from app.services.sources.catalog import ALL_SOURCES, CASCAIS
from app.services.sources.fetcher import SafeFetcher
from app.services.sources.ingest import SourceIngestor
from app.services.sources.registry import OFFICIAL_HOSTS, OfficialSourceRegistry
from app.services.sources.repository import InMemorySourceRepository
from app.services.sources.retrieval import RegulatoryRetriever

pytestmark = pytest.mark.skipif(os.getenv("HABITA_LIVE_TESTS") != "1", reason="live test: set HABITA_LIVE_TESTS=1")


async def test_real_cascais_documents_are_ingested_and_retrievable():
    registry = OfficialSourceRegistry(InMemorySourceRepository(), ALL_SOURCES)
    await registry.seed()
    reports = {r.source_id: r for r in await SourceIngestor(registry, SafeFetcher(OFFICIAL_HOSTS)).ingest_jurisdiction(CASCAIS)}
    assert set(reports) == {"cascais-pdm", "cascais-urbanismo-faq"}
    assert all(r.outcome == "new_snapshot" for r in reports.values()), reports

    pdm = await registry.repository.get_snapshot(reports["cascais-pdm"].snapshot_id)
    assert pdm.pages > 200 and pdm.text_extracted and len(pdm.sha256) == 64
    chunks = await registry.repository.list_chunks(pdm.snapshot_id)
    assert len(chunks) > 200 and any(c.locator.article == "Artigo 61.º" for c in chunks)

    hits = await RegulatoryRetriever(registry).search(
        ["pt", "pt/lisboa", CASCAIS], ["land_use_planning", "unit_division"], "dwellings in urban land")
    assert hits and all(h.source.source_id == "cascais-pdm" for h in hits)
    print("\nLIVE_SOURCES", {k: (v.outcome, v.chunks) for k, v in reports.items()},
          [(h.chunk.locator.label(), h.score) for h in hits])
