"""HR-003 backlog CX-3: concurrent status changes can't undo a retirement.

``change_status`` validates the transition on a read; ``set_status`` now writes only while the source still has the
(status, trust_version) that read saw (compare-and-swap), otherwise nothing is written and the operator re-reads."""

from datetime import UTC, datetime

import pytest

from app.schemas.sources import StatusChange
from app.services.sources.registry import SourceRegistryError
from app.services.sources.repository import MongoSourceRepository, StatusChangedConcurrently
from tests import test_permit_commit_durability as durability
from tests.test_sources import registry, source


async def test_a_stale_promotion_cannot_undo_a_concurrent_retirement():
    """The review's interleaving: validated → trusted and validated → retired both validated on the same read; the
    retirement lands first, so the promotion must be refused and the source stay retired."""
    reg = await registry()
    await reg.repository.insert_source(source())
    await reg.change_status("cascais-test", "validated", operator="ops", reason="checked")
    stale = await reg.repository.get_source("cascais-test")  # what the promoting operator read
    await reg.change_status("cascais-test", "retired", operator="ops2", reason="withdrawn")

    real_get = reg.repository.get_source

    async def stale_once(source_id):
        reg.repository.get_source = real_get
        return stale.model_copy(deep=True)
    reg.repository.get_source = stale_once
    with pytest.raises(SourceRegistryError, match="concurrently"):
        await reg.change_status("cascais-test", "trusted", operator="ops", reason="reviewed")
    current = await reg.repository.get_source("cascais-test")
    assert current.status == "retired" and [c.status for c in current.status_history] == ["validated", "retired"]


async def test_an_unconditional_status_write_still_works_for_maintenance():
    reg = await registry()
    await reg.repository.insert_source(source())
    await reg.repository.set_status("cascais-test", StatusChange(status="retired", operator="ops", reason="r",
                                                                 at=datetime.now(UTC)))
    assert (await reg.repository.get_source("cascais-test")).status == "retired"


def _mongo():
    client = durability.FakeMongo()
    repo = MongoSourceRepository.__new__(MongoSourceRepository)
    repo._sources = client.collection("official_sources")
    repo._sources.docs["s"] = {"_id": "s", "status": "validated", "trust_version": 3}
    return repo


async def test_the_mongo_status_write_is_a_compare_and_swap():
    repo = _mongo()
    change = StatusChange(status="trusted", operator="ops", reason="r", at=datetime.now(UTC))
    with pytest.raises(StatusChangedConcurrently):
        await repo.set_status("s", change, expected=("validated", 2))  # the version moved since the read
    assert repo._sources.docs["s"]["status"] == "validated"
    await repo.set_status("s", change, expected=("validated", 3))
    assert repo._sources.docs["s"]["status"] == "trusted"


# --- Codex backlog review, round 1 (2026-10-29) ---------------------------------------------------------------------

async def test_an_existing_text_less_snapshot_is_never_made_current():
    """P2: re-ingesting content whose stored snapshot has no text reports no_text and leaves the current one."""
    import hashlib

    from tests.pdf_fixture import REGULAMENTO_PAGES, make_pdf
    from tests.test_sources import ingestor
    from tests.test_sources_ingest_concurrency import snapshot as make_snapshot
    reg = await registry()
    body = make_pdf(REGULAMENTO_PAGES)
    snap, chunks = make_snapshot("ss_scan")
    snap = snap.model_copy(update={"text_extracted": False, "sha256": hashlib.sha256(body).hexdigest()})
    await reg.repository.save_snapshot(snap, chunks)
    ing, _ = ingestor(reg, body)
    report = await ing.ingest("cascais-pdm")
    assert report.outcome == "no_text" and (await reg.repository.get_source("cascais-pdm")).latest_snapshot_id != "ss_scan"
