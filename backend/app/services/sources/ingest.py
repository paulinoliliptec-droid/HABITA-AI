"""Ingestion: fetch a trusted, machine-readable source, snapshot it, index its passages.

Runs from maintenance (``python -m app.maintenance ingest-sources``), never inside a
Permit run. A document whose SHA-256 is unchanged reuses its snapshot; a changed
document becomes a new snapshot, and the old one's passages stay stored so evidence
that cited them remains reproducible.
"""

import asyncio
import hashlib
import logging
import secrets
from dataclasses import dataclass

from app.schemas.sources import PassageLocator, RegulatoryChunk, SourceSnapshot
from app.services.sources.fetcher import FetchError, SafeFetcher
from app.services.sources.normalize import extract_pdf
from app.services.sources.registry import OfficialSourceRegistry

logger = logging.getLogger("habita.sources")


@dataclass(frozen=True)
class IngestReport:
    source_id: str
    outcome: str  # "new_snapshot" | "unchanged" | "no_text" | "skipped" | "failed"
    detail: str = ""
    snapshot_id: str | None = None
    chunks: int = 0


class SourceIngestor:
    def __init__(self, registry: OfficialSourceRegistry, fetcher: SafeFetcher) -> None:
        self._registry = registry
        self._repo = registry.repository
        self._fetcher = fetcher

    async def ingest(self, source_id: str) -> IngestReport:
        source = await self._registry.get(source_id)
        if source is None:
            return IngestReport(source_id, "skipped", "unknown source")
        if source.status != "trusted":
            return IngestReport(source_id, "skipped", f"status is {source.status}; only trusted sources are ingested")
        if source.retrieval_method != "http_pdf" or not source.official_url:
            return IngestReport(source_id, "skipped", f"no connector for {source.retrieval_method}")
        try:
            fetched = await self._fetcher.fetch(source.official_url)
        except FetchError as exc:
            logger.warning("Source fetch refused or failed source=%s reason=%s", source_id, exc)
            return IngestReport(source_id, "failed", str(exc))
        if fetched.content_type != "application/pdf":
            return IngestReport(source_id, "failed", f"expected a PDF, got {fetched.content_type}")

        digest = hashlib.sha256(fetched.body).hexdigest()
        existing = await self._repo.find_snapshot(source_id, digest)
        if existing is not None:
            await self._repo.set_latest_snapshot(source_id, existing.snapshot_id)
            return IngestReport(source_id, "unchanged", snapshot_id=existing.snapshot_id, chunks=existing.chunk_count)

        try:
            document = await asyncio.to_thread(extract_pdf, fetched.body)
        except Exception as exc:  # malformed PDF: record nothing, report the failure
            logger.warning("Source parse failed source=%s error=%s", source_id, type(exc).__name__)
            return IngestReport(source_id, "failed", f"could not read the PDF ({type(exc).__name__})")

        snapshot_id = "ss_" + secrets.token_hex(8)
        chunks = [
            RegulatoryChunk(
                chunk_id=f"{snapshot_id}:{n}", source_id=source_id, snapshot_id=snapshot_id,
                jurisdiction_id=source.jurisdiction_id,
                locator=PassageLocator(page=p.page, article=p.article, heading=p.heading, part=p.part), text=p.text,
            )
            for n, p in enumerate(document.passages, 1)
        ]
        snapshot = SourceSnapshot(
            snapshot_id=snapshot_id, source_id=source_id, retrieved_at=fetched.retrieved_at,
            requested_url=fetched.requested_url, final_url=fetched.final_url, http_status=fetched.status,
            content_type=fetched.content_type, bytes=len(fetched.body), sha256=digest,
            version_detected=document.version_detected, pages=document.pages,
            text_extracted=document.text_extracted, chunk_count=len(chunks),
        )
        stored = await self._repo.save_snapshot(snapshot, chunks)
        if stored.snapshot_id != snapshot_id:
            # Another worker published the same content first (CX-4): use its snapshot (never one without text).
            if not stored.text_extracted:
                return IngestReport(source_id, "no_text", "no extractable text (scanned PDF?)", stored.snapshot_id)
            await self._repo.set_latest_snapshot(source_id, stored.snapshot_id)
            return IngestReport(source_id, "unchanged", snapshot_id=stored.snapshot_id, chunks=stored.chunk_count)
        if not document.text_extracted:
            # Recorded for audit, but never made current: there is no text to cite (no OCR in HR-003).
            return IngestReport(source_id, "no_text", "no extractable text (scanned PDF?)", snapshot_id)
        await self._repo.set_latest_snapshot(source_id, snapshot_id)
        return IngestReport(source_id, "new_snapshot", snapshot_id=snapshot_id, chunks=len(chunks))

    async def ingest_jurisdiction(self, jurisdiction_id: str) -> list[IngestReport]:
        sources = await self._registry.trusted([jurisdiction_id])
        return [await self.ingest(s.source_id) for s in sources if s.retrieval_method == "http_pdf"]
