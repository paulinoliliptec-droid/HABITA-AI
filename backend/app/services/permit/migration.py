"""MU-9 protocol-floor migration for an existing database (e.g. the original ``habita_ai``).

Order, following the MU-9 rule that the server is never less strict than the stored floor:
1. install the ``permit_verifications`` validator for the target floor (collMod; cannot run inside a transaction);
2. in ONE transaction: store the floor (compare-and-swap; skipped when it is already the target), flag VERIFIED
   reports of protocols the floor no longer admits (pre-MU-9 / statement-v1) and their matters as superseded, and
   write the audit record listing exactly what changed — all or nothing. If the transaction fails, only the
   validator (stricter, and idempotent) remains, and a rerun repeats the whole step.

Nothing is deleted: superseded documents stay as history (the API and reports present them as legacy, not
revalidated). Re-running is safe: already-flagged documents no longer match, so a rerun flags nothing and records a
no-op audit entry. A dry run (the default) reports the plan and changes nothing.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pymongo import AsyncMongoClient

from app.schemas.permit import MatterState
from app.services.permit.protocol import Floor, raise_floor, validator
from app.services.permit.repository import MongoPermitRepository

AUDIT_COLLECTION = "maintenance_audit"


@dataclass
class MigrationReport:
    database: str
    applied: bool
    floor_before: str
    floor_after: str
    floor_stored: bool = False
    validator_before: str = "absent"  # absent | different | current
    reports_to_flag: list[str] = field(default_factory=list)
    matters_to_flag: list[str] = field(default_factory=list)
    flagged_reports: int = 0
    audit_id: str | None = None


def _stale(floor: Floor) -> dict:
    return {"outcome": "VERIFIED", "superseded_protocol": None,
            "$or": [{"protocol": {"$exists": False}}, {"protocol": {"$nin": floor.admitted()}}]}


async def _validator_state(db, floor: Floor) -> str:
    found = await (await db.list_collections(filter={"name": "permit_verifications"})).to_list()
    if not found:
        return "absent"
    options = found[0].get("options", {})
    wanted = {"validator": validator(floor), "validationLevel": "moderate", "validationAction": "error"}
    if not options.get("validator"):
        return "absent"
    return "current" if {k: options.get(k) for k in wanted} == wanted else "different"


async def migrate_floor(client: AsyncMongoClient, db_name: str, min_protocol: str, operator: str, reason: str, *,
                        apply: bool = False, backup: dict | None = None) -> MigrationReport:
    """Plan (dry run) or apply the migration to ``min_protocol``. ``backup`` is the verified backup manifest summary
    (database, sha256) recorded in the audit; ``apply`` without it is refused by the caller."""
    db = client[db_name]
    permits = MongoPermitRepository(client, db_name)
    current = await permits.get_floor()
    stored = await db["verification_policy"].find_one({"_id": "floor"}) is not None
    target = current if (stored and current.min_protocol == min_protocol) else raise_floor(
        current, min_protocol, operator=operator, reason=reason)
    report = MigrationReport(database=db_name, applied=apply, floor_before=current.min_protocol if stored else
                             f"{current.min_protocol} (default, not stored)", floor_after=target.min_protocol,
                             validator_before=await _validator_state(db, target))
    report.reports_to_flag = [d["_id"] async for d in db["permit_verifications"].find(_stale(target), {"_id": 1})]
    report.matters_to_flag = [d["_id"] async for d in db["permit_matters"].find(
        {"state": MatterState.VERIFIED.value, "latest_verification_id": {"$in": report.reports_to_flag}}, {"_id": 1})]
    if not apply:
        return report

    await permits.apply_validator(target)  # 1. stricter server first
    audit_id = f"mig_{uuid.uuid4().hex[:16]}"

    async def flag_and_audit(session) -> None:  # 2. one transaction: floor + flags + the audit record of exactly them
        report.floor_stored = False
        if target is not current or not stored:  # CAS: a concurrent floor change aborts the whole transaction
            if not await permits.store_floor(current, target, session=session):
                raise RuntimeError("The protocol floor changed concurrently; nothing was changed. Run it again.")
            report.floor_stored = True
        report.reports_to_flag = [d["_id"] async for d in db["permit_verifications"].find(
            _stale(target), {"_id": 1}, session=session)]
        report.matters_to_flag = [d["_id"] async for d in db["permit_matters"].find(
            {"state": MatterState.VERIFIED.value, "latest_verification_id": {"$in": report.reports_to_flag}},
            {"_id": 1}, session=session)]
        report.flagged_reports = await permits.flag_superseded(target, session=session)
        await db[AUDIT_COLLECTION].insert_one({
            "_id": audit_id, "kind": "protocol_floor_migration", "at": datetime.now(UTC), "operator": operator,
            "reason": reason, "database": db_name, "floor_before": report.floor_before,
            "floor_after": target.min_protocol, "floor_stored": report.floor_stored,
            "validator_before": report.validator_before, "flagged_report_ids": report.reports_to_flag,
            "flagged_matter_ids": report.matters_to_flag, "flagged_reports": report.flagged_reports,
            "backup": backup or {},
        }, session=session)

    async with client.start_session() as session:
        await session.with_transaction(flag_and_audit)
    report.audit_id = audit_id
    return report
