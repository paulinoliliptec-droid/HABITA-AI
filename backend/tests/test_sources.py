"""HR-003 official source layer: registry trust lifecycle, safe fetching, normalization, ingestion, retrieval."""

from datetime import UTC, datetime

import bson
import httpx
import pytest

from app.schemas.sources import OfficialSource, SourceVerification, StatusChange
from app.services.sources.catalog import ALL_SOURCES, CASCAIS, VERIFIED_ON
from app.services.sources.fetcher import FetchError, SafeFetcher
from app.services.sources.ingest import SourceIngestor
from app.services.sources.normalize import extract_pdf
from app.services.sources.registry import (
    OFFICIAL_HOSTS,
    OfficialSourceRegistry,
    SourceRegistryError,
    validation_problems,
)
from app.services.sources.repository import InMemorySourceRepository, MongoSourceRepository
from app.services.sources.retrieval import RegulatoryRetriever
from tests.pdf_fixture import REGULAMENTO_PAGES, make_pdf

CASCAIS_CHAIN = ["pt", "pt/lisboa", CASCAIS]
PORTO_CHAIN = ["pt", "pt/porto", "pt/porto/porto"]
PDM_URL = next(s.official_url for s in ALL_SOURCES if s.source_id == "cascais-pdm")


async def registry() -> OfficialSourceRegistry:
    reg = OfficialSourceRegistry(InMemorySourceRepository(), ALL_SOURCES)
    await reg.seed()
    return reg


def source(**overrides) -> OfficialSource:
    values = dict(
        source_id="cascais-test", jurisdiction_id=CASCAIS, title="Test", source_type="official_pdf",
        official_url="https://www.cascais.pt/sites/default/files/x.pdf", publisher="Câmara Municipal de Cascais",
        geographic_scope="municipality", retrieval_method="manual", machine_readable=False, status="candidate",
        authority_class="municipal_instrument",
        provenance=SourceVerification(added_by="curated", verified_on=VERIFIED_ON, verified_by="tester"),
    )
    return OfficialSource(**{**values, **overrides})


# --- registry -----------------------------------------------------------------------------


def test_every_seeded_trusted_source_passes_validation_and_uses_an_official_host():
    trusted = [s for s in ALL_SOURCES if s.status == "trusted"]
    assert trusted and all(validation_problems(s) == [] for s in trusted)
    assert {s.source_id for s in ALL_SOURCES if s.status != "trusted"} == {"cascais-geocascais"}
    for s in trusted:
        assert s.official_url is None or s.official_url.startswith("https://")


@pytest.mark.parametrize("url, problem", [
    ("https://vlex.pt/vid/aviso-n-3054-2018", "allowlisted official host"),  # commercial legal database
    ("http://www.cascais.pt/x.pdf", "allowlisted official host"),
    ("https://user:pw@www.cascais.pt/x.pdf", "allowlisted official host"),
    ("https://www.cascais.pt:8443/x.pdf", "allowlisted official host"),
    ("https://www.cascais.pt.evil.example/x.pdf", "allowlisted official host"),
])
def test_non_official_urls_fail_validation(url, problem):
    assert any(problem in p for p in validation_problems(source(official_url=url)))


def test_a_host_only_publishes_for_its_own_jurisdiction_or_below():
    national_on_municipal_host = source(jurisdiction_id="pt")
    assert any("publishes for pt/lisboa/cascais" in p for p in validation_problems(national_on_municipal_host))
    municipal_in_national_gazette = source(official_url="https://files.diariodarepublica.pt/2s/x.pdf")
    assert validation_problems(municipal_in_national_gazette) == []


def test_fetching_sources_need_a_url_and_a_verification_record():
    problems = validation_problems(source(official_url=None, retrieval_method="http_pdf", machine_readable=True,
                                          provenance=SourceVerification(added_by="discovery")))
    assert any("needs a verified official_url" in p for p in problems)
    assert any("verification record" in p for p in problems)


async def test_lifecycle_requires_each_step_an_operator_and_validation():
    reg = await registry()
    await reg.repository.insert_source(source())
    with pytest.raises(SourceRegistryError, match="not allowed"):
        await reg.change_status("cascais-test", "trusted", operator="ops", reason="skip validation")
    with pytest.raises(SourceRegistryError, match="operator"):
        await reg.change_status("cascais-test", "validated", operator=" ", reason="checked")
    await reg.change_status("cascais-test", "validated", operator="ops", reason="host and document checked")
    promoted = await reg.change_status("cascais-test", "trusted", operator="ops", reason="reviewed")
    assert promoted.status == "trusted"
    assert [(c.status, c.operator) for c in promoted.status_history] == [("validated", "ops"), ("trusted", "ops")]
    with pytest.raises(SourceRegistryError, match="not allowed"):
        await reg.change_status("cascais-test", "validated", operator="ops", reason="downgrade")
    await reg.change_status("cascais-test", "retired", operator="ops", reason="superseded")
    assert "cascais-test" not in await reg.trusted_ids(CASCAIS_CHAIN)


async def test_an_invalid_source_cannot_be_validated():
    reg = await registry()
    await reg.repository.insert_source(source(source_id="vlex-copy", official_url="https://vlex.pt/x"))
    with pytest.raises(SourceRegistryError, match="fails validation"):
        await reg.change_status("vlex-copy", "validated", operator="ops", reason="looks fine")


async def test_discovered_sources_are_always_stored_as_candidates():
    reg = await registry()
    claimed = source(source_id="cascais-discovered", status="trusted")
    stored = await reg.register_candidate(claimed)
    assert stored.status == "candidate" and stored.provenance.added_by == "discovery"
    assert "cascais-discovered" not in await reg.trusted_ids(CASCAIS_CHAIN)
    with pytest.raises(SourceRegistryError, match="already registered"):
        await reg.register_candidate(claimed)


async def test_reseeding_never_overrides_an_operator_decision():
    reg = await registry()
    await reg.change_status("cascais-pdm", "retired", operator="ops", reason="under review")
    await reg.seed()
    assert (await reg.get("cascais-pdm")).status == "retired"
    assert "cascais-pdm" not in await reg.trusted_ids(CASCAIS_CHAIN)


async def test_trusted_sources_follow_the_jurisdiction_chain_and_topics():
    reg = await registry()
    cascais = await reg.trusted_ids(CASCAIS_CHAIN)
    porto = await reg.trusted_ids(PORTO_CHAIN)
    assert {"cascais-pdm", "cascais-pdm-planta-01-02", "pt-rjue"} <= cascais
    assert "cascais-geocascais" not in cascais  # candidate: registered but not trusted
    assert porto == {"pt-rjue", "pt-simplex-urbanistico", "pt-codigo-civil-propriedade-horizontal", "pt-rgeu"}
    habitability = {s.source_id for s in await reg.trusted(CASCAIS_CHAIN, ["habitability"])}
    assert habitability == {"pt-rgeu"}


# --- safe fetcher ---------------------------------------------------------------------------


def resolver(mapping: dict[str, list[str]] | None = None):
    async def resolve(host: str) -> list[str]:
        return (mapping or {}).get(host, ["193.236.10.10"])
    return resolve


def fetcher(handler, mapping=None, **kw) -> tuple[SafeFetcher, list[str]]:
    seen: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handler(request)

    return SafeFetcher(OFFICIAL_HOSTS, transport=httpx.MockTransport(record), resolver=resolver(mapping), **kw), seen


def pdf_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4 test")


@pytest.mark.parametrize("url", [
    "http://www.cascais.pt/a.pdf",
    "https://example.com/a.pdf",
    "https://www.cascais.pt.example.com/a.pdf",
    "https://admin:x@www.cascais.pt/a.pdf",
    "https://www.cascais.pt:444/a.pdf",
    "file:///etc/passwd",
])
async def test_fetcher_refuses_non_allowlisted_urls_without_any_request(url):
    f, seen = fetcher(pdf_response)
    with pytest.raises(FetchError):
        await f.fetch(url)
    assert seen == []


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.1.2.3", "192.168.0.10", "172.16.5.4", "169.254.169.254", "100.64.0.1", "0.0.0.0",
    "::1", "fd00::1", "fe80::1", "::ffff:127.0.0.1", "224.0.0.1",
])
async def test_fetcher_refuses_hosts_resolving_to_internal_addresses(address):
    f, seen = fetcher(pdf_response, {"www.cascais.pt": ["193.236.10.10", address]})
    with pytest.raises(FetchError, match="non-public"):
        await f.fetch(PDM_URL)
    assert seen == []


async def test_redirects_are_rechecked_at_every_hop():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cascais.pt":
            return httpx.Response(301, headers={"location": PDM_URL})
        if request.url.path.endswith("moved.pdf"):
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        return pdf_response(request)

    f, seen = fetcher(handler)
    result = await f.fetch("https://cascais.pt/sites/default/files/anexos/gerais/new/regulamento_pdm_em_vigor_1.pdf")
    assert result.final_url == PDM_URL and result.body.startswith(b"%PDF")
    assert len(seen) == 2

    f, seen = fetcher(handler)
    with pytest.raises(FetchError, match="https"):
        await f.fetch("https://www.cascais.pt/moved.pdf")
    assert seen == ["https://www.cascais.pt/moved.pdf"]  # the metadata address is never requested


async def test_redirect_loops_and_unexpected_responses_are_refused():
    loop, _ = fetcher(lambda r: httpx.Response(302, headers={"location": PDM_URL}))
    with pytest.raises(FetchError, match="too many redirects"):
        await loop.fetch(PDM_URL)
    html, _ = fetcher(lambda r: httpx.Response(200, headers={"content-type": "application/x-msdownload"}, content=b"MZ"))
    with pytest.raises(FetchError, match="content type"):
        await html.fetch(PDM_URL)
    missing, _ = fetcher(lambda r: httpx.Response(404, headers={"content-type": "text/html"}))
    with pytest.raises(FetchError, match="HTTP 404"):
        await missing.fetch(PDM_URL)


async def test_oversized_documents_are_refused():
    big = lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"x" * 5000)  # noqa: E731
    f, _ = fetcher(big, max_bytes=1000)
    with pytest.raises(FetchError, match="size limit"):
        await f.fetch(PDM_URL)


# --- normalization --------------------------------------------------------------------------


def test_text_pdf_becomes_article_passages_without_headers_or_toc():
    doc = extract_pdf(make_pdf(REGULAMENTO_PAGES))
    assert doc.text_extracted and doc.pages == 4
    labels = [p.article for p in doc.passages]
    assert labels == ["Artigo 1.º", "Artigo 2.º", "Artigo 61.º", "Artigo 62.º", "Artigo 63.º-A"]  # no TOC entries
    by_article = {p.article: p for p in doc.passages}
    assert by_article["Artigo 61.º"].page == 3
    assert by_article["Artigo 61.º"].heading == "Princípios gerais do solo urbano"
    assert "habitação" in by_article["Artigo 61.º"].text
    assert all("Regulamento PDM-Cascais" not in p.text for p in doc.passages)  # repeated header removed


def test_pdf_without_text_is_recorded_as_such_never_guessed():
    doc = extract_pdf(make_pdf(["", "", ""]))
    assert doc.text_extracted is False and doc.passages == []


def test_long_articles_are_split_into_numbered_parts():
    body = "\n".join(f"{n} - Disposição sobre edificação número {n} com texto suficiente." for n in range(120))
    doc = extract_pdf(make_pdf(["Artigo 9.º\nTítulo longo\n" + body]))
    parts = [p for p in doc.passages if p.article == "Artigo 9.º"]
    assert len(parts) > 1 and [p.part for p in parts] == list(range(1, len(parts) + 1))


# --- ingestion and retrieval ----------------------------------------------------------------


def ingestor(reg: OfficialSourceRegistry, body: bytes, content_type="application/pdf") -> tuple[SourceIngestor, list]:
    f, seen = fetcher(lambda r: httpx.Response(200, headers={"content-type": content_type}, content=body))
    return SourceIngestor(reg, f), seen


async def ingested_registry(pages=REGULAMENTO_PAGES) -> OfficialSourceRegistry:
    reg = await registry()
    report = await ingestor(reg, make_pdf(pages))[0].ingest("cascais-pdm")
    assert report.outcome == "new_snapshot", report
    return reg


async def test_ingestion_snapshots_and_indexes_a_trusted_pdf():
    reg = await registry()
    ing, seen = ingestor(reg, make_pdf(REGULAMENTO_PAGES))
    report = await ing.ingest("cascais-pdm")
    assert report.outcome == "new_snapshot" and report.chunks == 5 and seen == [PDM_URL]
    source = await reg.get("cascais-pdm")
    snapshot = await reg.repository.get_snapshot(source.latest_snapshot_id)
    assert len(snapshot.sha256) == 64 and snapshot.final_url == PDM_URL and snapshot.text_extracted
    chunks = await reg.repository.list_chunks(snapshot.snapshot_id)
    assert {c.jurisdiction_id for c in chunks} == {CASCAIS} and {c.source_id for c in chunks} == {"cascais-pdm"}

    again = await ing.ingest("cascais-pdm")
    assert again.outcome == "unchanged" and again.snapshot_id == report.snapshot_id


async def test_a_changed_document_becomes_a_new_snapshot_and_old_passages_are_kept():
    reg = await ingested_registry()
    first = (await reg.get("cascais-pdm")).latest_snapshot_id
    changed = REGULAMENTO_PAGES[:3] + [REGULAMENTO_PAGES[3].replace("anexo", "anexo revisto")]
    second = (await ingestor(reg, make_pdf(changed))[0].ingest("cascais-pdm")).snapshot_id
    assert second != first and (await reg.get("cascais-pdm")).latest_snapshot_id == second
    assert await reg.repository.list_chunks(first)  # still reproducible


async def test_only_trusted_machine_readable_sources_are_ingested():
    reg = await registry()
    ing, seen = ingestor(reg, make_pdf(REGULAMENTO_PAGES))
    assert (await ing.ingest("cascais-geocascais")).outcome == "skipped"  # candidate
    assert (await ing.ingest("pt-rjue")).outcome == "skipped"  # curated reference: no fetch
    assert (await ing.ingest("cascais-pdm-planta-01-02")).outcome == "skipped"  # map PDF: manual consultation
    assert (await ing.ingest("not-a-source")).outcome == "skipped"
    await reg.change_status("cascais-pdm", "retired", operator="ops", reason="test")
    assert (await ing.ingest("cascais-pdm")).outcome == "skipped"
    assert seen == []


async def test_scanned_or_non_pdf_documents_never_become_current():
    reg = await registry()
    scanned = await ingestor(reg, make_pdf(["", ""]))[0].ingest("cascais-pdm")
    assert scanned.outcome == "no_text" and (await reg.get("cascais-pdm")).latest_snapshot_id is None
    html = await ingestor(reg, b"<html>", "text/html")[0].ingest("cascais-pdm")
    assert html.outcome == "failed"


async def test_retrieval_is_scoped_to_the_jurisdiction_and_trusted_sources():
    reg = await ingested_registry()
    retriever = RegulatoryRetriever(reg)
    hits = await retriever.search(CASCAIS_CHAIN, ["land_use_planning"], "residential use in urban land")
    assert hits and hits[0].chunk.locator.article == "Artigo 61.º"
    assert all(h.source.source_id == "cascais-pdm" and h.snapshot.sha256 for h in hits)
    assert await retriever.search(PORTO_CHAIN, ["land_use_planning"], "residential use in urban land") == []
    await reg.change_status("cascais-pdm", "retired", operator="ops", reason="test")
    assert await RegulatoryRetriever(reg).search(CASCAIS_CHAIN, ["land_use_planning"], "urban land") == []


async def test_retrieval_is_deterministic_and_the_query_changes_the_ranking():
    reg = await ingested_registry()
    retriever = RegulatoryRetriever(reg)
    parking = await retriever.search(CASCAIS_CHAIN, ["unit_division"], "parking per dwelling unit")
    housing = await retriever.search(CASCAIS_CHAIN, ["unit_division"], "residential housing in urban land")
    assert parking[0].chunk.locator.article == "Artigo 62.º"
    assert housing[0].chunk.locator.article == "Artigo 61.º"
    again = await retriever.search(CASCAIS_CHAIN, ["unit_division"], "parking per dwelling unit")
    assert [h.chunk.chunk_id for h in again] == [h.chunk.chunk_id for h in parking]
    # Topics outside a source's regulatory scope don't reach it.
    assert await retriever.search(CASCAIS_CHAIN, ["habitability"], "parking") == []


# --- MongoDB repository (documents must be BSON-encodable and round-trip) --------------------


class RecordingCollection:
    def __init__(self) -> None:
        self.docs: dict = {}

    async def update_one(self, query, update, upsert=False):
        bson.encode(update.get("$set", {})), bson.encode(update.get("$setOnInsert", {}))
        bson.encode({k: v for k, v in update.get("$push", {}).items()})
        doc = self.docs.get(query["_id"])
        if doc is None and upsert:
            doc = self.docs[query["_id"]] = {"_id": query["_id"], **update.get("$setOnInsert", {})}
        if doc is not None:
            doc.update(update.get("$set", {}))
            for key, value in update.get("$push", {}).items():
                doc.setdefault(key, []).append(value)

    async def insert_one(self, doc):
        bson.encode(doc)
        self.docs[doc["_id"]] = doc

    async def insert_many(self, docs):
        for doc in docs:
            await self.insert_one(doc)

    async def find_one(self, query):
        return self.docs.get(query["_id"])


async def test_mongo_documents_are_bson_encodable_and_round_trip():
    repo = MongoSourceRepository.__new__(MongoSourceRepository)
    repo._sources, repo._snapshots, repo._chunks = RecordingCollection(), RecordingCollection(), RecordingCollection()
    reg = OfficialSourceRegistry(repo, ALL_SOURCES)  # type: ignore[arg-type]
    await reg.seed()
    stored = await repo.get_source("cascais-pdm")
    assert stored == next(s for s in ALL_SOURCES if s.source_id == "cascais-pdm")
    await repo.set_status("cascais-pdm", StatusChange(status="retired", operator="ops", reason="test", at=datetime.now(UTC)))
    await reg.seed()  # re-seeding keeps the operator's decision
    assert (await repo.get_source("cascais-pdm")).status == "retired"
