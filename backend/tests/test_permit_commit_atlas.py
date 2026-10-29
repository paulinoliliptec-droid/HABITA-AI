"""Opt-in, real MongoDB Atlas check of the VERIFIED commit transaction (HR-003 CX-2). Run with HABITA_LIVE_TESTS=1 and
MONGODB_URI set. Touches only documents it creates (``txn-test-*`` sources in a jurisdiction no property uses,
``pm_txntest_*`` matters and their reports) and removes all of them at the end."""

import asyncio
import os
import secrets
from datetime import UTC, datetime

import pytest
from pymongo import AsyncMongoClient

from app.core.config import Settings
from app.db.property_repository import MongoPropertyRepository, PropertyIdentity
from app.schemas.permit import MatterState, VerificationReport
from app.services.permit.protocol import CURRENT
from app.services.permit.repository import (
    MatterAlreadyVerified, MatterCommitConflict, MongoPermitRepository, hash_token,
)
from app.services.sources.catalog import ALL_SOURCES
from app.services.sources.registry import TrustPin
from app.services.sources.repository import MongoSourceRepository
from tests.test_permit_verifier import matter as make_matter

pytestmark = pytest.mark.skipif(os.getenv("HABITA_LIVE_TESTS") != "1", reason="live test: set HABITA_LIVE_TESTS=1")


def test_verified_commit_transaction_on_atlas():
    asyncio.run(_run())


async def _run():
    settings = Settings(app_env="test")
    assert settings.mongodb_uri, "MONGODB_URI missing"
    client = AsyncMongoClient(settings.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=10000)
    db = client[settings.mongodb_db_name]
    permit, src = MongoPermitRepository(client, settings.mongodb_db_name), MongoSourceRepository(client, settings.mongodb_db_name)
    props = MongoPropertyRepository(client, settings.mongodb_db_name)
    tag = secrets.token_hex(4)
    jurisdiction = f"test/txn-{tag}"
    s1, s2 = f"txn-test-{tag}-a", f"txn-test-{tag}-b"
    mids = [f"pm_txntest_{tag}_{i}" for i in range(1, 5)]
    template = ALL_SOURCES[0]
    pid = make_matter().property_id
    ident = PropertyIdentity(pid, 0)
    try:
        # The matters' property, as a final gate would read it (C2); restored to version 0 for each run.
        await db["properties"].update_one({"_id": pid}, {"$set": {"identity_version": 0, "snapshot_state": "current"},
                                                         "$unset": {"merged_into": "", "merging_into": ""}},
                                          upsert=True)
        for sid in (s1, s2):
            await src.insert_source(template.model_copy(update={
                "source_id": sid, "jurisdiction_id": jurisdiction, "status": "trusted", "status_history": [],
                "trust_version": 0, "latest_snapshot_id": None}))
        for mid in mids:
            if mid != mids[2]:  # mids[2] is never created: the "missing matter" case
                await permit.create_matter(make_matter().model_copy(update={
                    "matter_id": mid, "state": MatterState.VERIFYING, "revision": 0}), hash_token(f"t-{mid}"))

        def pair(mid, rid):
            m = make_matter().model_copy(update={"matter_id": mid, "state": MatterState.VERIFIED, "revision": 0,
                                                 "latest_verification_id": rid})
            r = VerificationReport(verification_id=rid, matter_id=mid, draft_revision=0, outcome="VERIFIED",
                                   issues=[], checks={"final_gate_passed": True}, created_at=datetime.now(UTC),
                                   protocol=CURRENT)
            return m, r

        async def reports(mid):
            return await db["permit_verifications"].count_documents({"matter_id": mid})

        async def state(mid):
            doc = await db["permit_matters"].find_one({"_id": mid})
            return doc and doc.get("state")

        pin = TrustPin({s1: ("trusted", 0), s2: ("trusted", 0)})

        # 1. Normal commit: report + matter + pinned sources, one real transaction.
        m1, r1 = pair(mids[0], f"pv_txntest_{tag}_1")
        assert await permit.commit_verified(m1, r1, pin, src, ident, props) is True
        doc = await db["permit_matters"].find_one({"_id": mids[0]})
        assert doc["state"] == "VERIFIED" and doc["latest_verification_id"] == r1.verification_id
        assert await reports(mids[0]) == 1
        for sid in (s1, s2):  # every pinned source was written inside the transaction
            assert (await db["official_sources"].find_one({"_id": sid})).get("last_verified_commit_at")

        # 2. Idempotent repeat of the same commit: success, still exactly one report.
        assert await permit.commit_verified(m1, r1, pin, src, ident, props) is True
        assert await reports(mids[0]) == 1

        # 3. VERIFIED can't be overwritten by a later save.
        with pytest.raises(MatterAlreadyVerified):
            await permit.save_matter(m1.model_copy(update={"state": MatterState.FAILED}))
        assert await state(mids[0]) == "VERIFIED"

        # 4. Pin moved (a status change after the gate): refused, nothing written.
        from app.schemas.sources import StatusChange
        await src.set_status(s1, StatusChange(status="retired", operator="txn-test", reason="atlas check",
                                              at=datetime.now(UTC)))
        m2, r2 = pair(mids[1], f"pv_txntest_{tag}_2")
        assert await permit.commit_verified(m2, r2, pin, src, ident, props) is False
        assert await state(mids[1]) == "VERIFYING" and await reports(mids[1]) == 0

        # 5. Missing matter: refused, no orphan report.
        fresh = TrustPin({s1: ("retired", 1), s2: ("trusted", 0)})
        m3, r3 = pair(mids[2], f"pv_txntest_{tag}_3")
        with pytest.raises(MatterCommitConflict):
            await permit.commit_verified(m3, r3, fresh, src, ident, props)
        assert await reports(mids[2]) == 0 and await state(mids[2]) is None

        # 6. Induced write conflict: another transaction holds a write on a pinned source.
        m4, r4 = pair(mids[3], f"pv_txntest_{tag}_4")
        async with client.start_session() as blocker:
            await blocker.start_transaction()
            await db["official_sources"].update_one({"_id": s2}, {"$set": {"txn_blocker": True}}, session=blocker)
            assert await permit.commit_verified(m4, r4, fresh, src, ident, props) is False  # conflict → retried → refused
            assert await state(mids[3]) == "VERIFYING" and await reports(mids[3]) == 0
            await blocker.abort_transaction()
        # ... and once the conflicting transaction is gone, the same commit goes through, once.
        assert await permit.commit_verified(m4, r4, fresh, src, ident, props) is True
        assert await state(mids[3]) == "VERIFIED" and await reports(mids[3]) == 1
        print(f"\nATLAS_TXN_OK tag={tag} normal=committed idempotent=1-report overwrite=refused pin-moved=refused "
              f"missing-matter=refused write-conflict=refused-then-committed")
    finally:
        await db["permit_verifications"].delete_many({"matter_id": {"$in": mids}})
        await db["permit_matters"].delete_many({"_id": {"$in": mids}})
        await db["official_sources"].delete_many({"_id": {"$in": [s1, s2]}})
        await db["properties"].delete_one({"_id": pid, "place_id": {"$exists": False}})  # the synthetic one only
        left = (await db["permit_verifications"].count_documents({"matter_id": {"$in": mids}})
                + await db["permit_matters"].count_documents({"_id": {"$in": mids}})
                + await db["official_sources"].count_documents({"_id": {"$in": [s1, s2]}}))
        print(f"ATLAS_CLEANUP tag={tag} remaining_test_documents={left}")
        await client.close()
        assert left == 0


def test_the_verification_validator_refuses_a_pre_mu9_verified_report_on_atlas():
    """MU-9 (M8), server side: in a throwaway database (dropped at the end), the validator that
    ``raise-protocol-floor`` installs refuses a VERIFIED report shaped like the pre-MU-9 code writes it."""
    asyncio.run(_validator_run())


async def _validator_run():
    from pymongo.errors import WriteError

    from app.services.permit.protocol import DEFAULT_FLOOR
    settings = Settings(app_env="test")
    assert settings.mongodb_uri, "MONGODB_URI missing"
    client = AsyncMongoClient(settings.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=10000)
    name = f"{settings.mongodb_db_name}_mu9test_{secrets.token_hex(4)}"
    permit = MongoPermitRepository(client, name)
    base = {"matter_id": "pm_x", "draft_revision": 0, "issues": [], "checks": {}, "created_at": datetime.now(UTC)}
    try:
        await permit.apply_validator(DEFAULT_FLOOR)
        collection = client[name]["permit_verifications"]
        with pytest.raises(WriteError):
            await collection.insert_one({"_id": "pv_old", "outcome": "VERIFIED", **base})
        with pytest.raises(WriteError):
            await collection.insert_one({"_id": "pv_v1", "outcome": "VERIFIED", "protocol": "statement-v1",
                                         "claim_atoms": [], **base})
        await collection.insert_one({"_id": "pv_rejected", "outcome": "REJECTED", **base})
        await collection.insert_one({"_id": "pv_new", "outcome": "VERIFIED", "protocol": CURRENT, "claim_atoms": [],
                                     **base})
    finally:
        await client.drop_database(name)
        await client.close()
