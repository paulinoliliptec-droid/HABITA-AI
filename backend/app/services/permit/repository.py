"""Permit persistence: matters, checklists, evidence and verification reports.

MongoDB collections:
    permit_matters        one document per matter (state, inputs, draft, progress, lease)
    permit_checklists     one document per matter (``_id`` = matter_id)
    permit_evidence       one document per evidence record (``_id`` = "<matter_id>:<E#>")
    permit_verifications  one document per verifier run (append-only)

A matter is run by one worker at a time: ``acquire`` takes a short lease
atomically, so two simultaneous "continue" requests can't interleave steps.

Access: each matter has a capability token, returned once to its creator. Only
its SHA-256 hash is stored (``access_hash`` on the matter document, outside the
``PermitMatter`` model so it is never serialised into API responses). The token
is 256 bits of randomness, so an unsalted hash is not guessable.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.errors import ConflictError, StorageUnavailableError
from app.db.property_repository import (
    InMemoryPropertyRepository, MongoPropertyRepository, PropertyIdentity, identity_filter,
)
from app.schemas.permit import Checklist, Evidence, MatterState, PermitMatter, VerificationReport
from app.services.permit.protocol import DEFAULT_FLOOR, FLOOR_ID, Floor, validator
from app.services.sources.registry import TrustPin
from app.services.sources.repository import InMemorySourceRepository, MongoSourceRepository

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=5)
_UNAVAILABLE = "HABITA can't reach its permit store right now. Please try again shortly."


def new_matter_id() -> str:
    return "pm_" + secrets.token_hex(8)


def new_verification_id() -> str:
    return "pv_" + secrets.token_hex(8)


def new_access_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class PermitRepository(Protocol):
    async def create_matter(self, matter: PermitMatter, access_hash: str) -> None: ...
    async def has_access(self, matter_id: str, access_hash: str) -> bool: ...
    async def get_matter(self, matter_id: str) -> PermitMatter | None: ...
    async def save_matter(self, matter: PermitMatter) -> None: ...
    async def acquire(self, matter_id: str) -> bool: ...
    async def release(self, matter_id: str) -> None: ...
    async def get_checklist(self, matter_id: str) -> Checklist | None: ...
    async def save_checklist(self, checklist: Checklist) -> None: ...
    async def list_evidence(self, matter_id: str) -> list[Evidence]: ...
    async def add_evidence(self, evidence: Evidence) -> Evidence: ...
    async def save_verification(self, report: VerificationReport) -> None: ...
    async def latest_verification(self, matter_id: str) -> VerificationReport | None: ...
    async def commit_verified(self, matter: PermitMatter, report: VerificationReport, pin: TrustPin,
                              sources: Any, identity: PropertyIdentity | None, properties: Any) -> bool: ...


def _binds(identity: PropertyIdentity | None, matter: PermitMatter) -> bool:
    """A VERIFIED commit binds the matter's own property document; no identity (merged, purged, unversioned) or
    another document's identity fails closed."""
    return identity is not None and identity.property_id == matter.property_id


class _PinMoved(Exception):
    """A pinned source (or the property, C2) changed after the final gate: the VERIFIED commit must not happen."""


class CommitOutcomeUnknown(StorageUnavailableError):
    """The VERIFIED transaction may or may not have committed (``UnknownTransactionCommitResult`` persisted through
    every commit retry). Not a failure: the caller reads the matter back to learn the outcome."""


class MatterCommitConflict(ConflictError):
    """The VERIFIED commit doesn't fit the stored matter (missing, another state or revision, already VERIFIED by
    another report) or the matter/report pair is inconsistent. Nothing was written."""


class ProtocolBelowFloor(MatterCommitConflict):
    """The report's verification protocol is below the persisted floor, or known unsafe (MU-9). Nothing was
    written: a rolled-back verifier can't commit VERIFIED."""


def _check_floor(floor: Floor, report: VerificationReport) -> None:
    if not floor.admits(report.protocol):
        raise ProtocolBelowFloor(f"Verification protocol {report.protocol} is not admitted by the floor "
                                 f"({floor.min_protocol}; known unsafe: {', '.join(floor.known_unsafe) or 'none'}).")


class MatterAlreadyVerified(ConflictError):
    """A save would overwrite a VERIFIED matter. VERIFIED is terminal and written only by ``commit_verified``."""


#: Whole-transaction attempts on ``TransientTransactionError`` (pins and matter re-checked each time), and
#: ``commitTransaction`` retries on ``UnknownTransactionCommitResult`` (idempotent on the server), per MongoDB's
#: documented retry pattern for the transactions core API.
_TXN_ATTEMPTS = 3
_COMMIT_RETRIES = 5


def _check_pair(matter: PermitMatter, report: VerificationReport) -> None:
    """The VERIFIED matter and its report must describe each other before anything is written: same matter, the
    report linked as the matter's latest, and the same draft revision (matter revision and draft revision)."""
    if (report.outcome != "VERIFIED" or matter.state != MatterState.VERIFIED or report.matter_id != matter.matter_id
            or matter.latest_verification_id != report.verification_id
            or report.draft_revision != matter.revision
            or (matter.draft is not None and matter.draft.revision != report.draft_revision)):
        raise MatterCommitConflict("The VERIFIED report and matter don't belong together; nothing was committed.")


def _already_committed(stored: dict | PermitMatter | None, report: VerificationReport) -> bool:
    if stored is None:
        return False
    get = stored.get if isinstance(stored, dict) else lambda k: getattr(stored, k, None)
    return get("state") == MatterState.VERIFIED and get("latest_verification_id") == report.verification_id


async def _abort(session) -> None:
    if session.in_transaction:
        await session.abort_transaction()


async def _commit_with_retry(session) -> None:
    """``commitTransaction`` is retried while its result is unknown (it is idempotent on the server)."""
    for _ in range(_COMMIT_RETRIES):
        try:
            await session.commit_transaction()
            return
        except PyMongoError as exc:
            if not exc.has_error_label("UnknownTransactionCommitResult"):
                raise
    raise CommitOutcomeUnknown("HABITA couldn't confirm whether the verified result was saved.")


class InMemoryPermitRepository:
    def __init__(self) -> None:
        self.matters: dict[str, PermitMatter] = {}
        self.checklists: dict[str, Checklist] = {}
        self.evidence: dict[str, list[Evidence]] = {}
        self.verifications: dict[str, list[VerificationReport]] = {}
        self.access_hashes: dict[str, str] = {}
        self._leases: dict[str, datetime] = {}
        #: The persisted protocol floor (MU-9); the Mongo store keeps it in ``verification_policy``.
        self.floor: Floor = DEFAULT_FLOOR

    async def create_matter(self, matter: PermitMatter, access_hash: str) -> None:
        self.matters[matter.matter_id] = matter.model_copy(deep=True)
        self.access_hashes[matter.matter_id] = access_hash

    async def has_access(self, matter_id: str, access_hash: str) -> bool:
        stored = self.access_hashes.get(matter_id)
        return stored is not None and hmac.compare_digest(stored, access_hash)

    async def get_matter(self, matter_id: str) -> PermitMatter | None:
        matter = self.matters.get(matter_id)
        return matter.model_copy(deep=True) if matter else None

    async def save_matter(self, matter: PermitMatter) -> None:
        stored = self.matters.get(matter.matter_id)
        if stored is not None and stored.state == MatterState.VERIFIED:
            raise MatterAlreadyVerified("This matter is already VERIFIED.")
        self.matters[matter.matter_id] = matter.model_copy(deep=True)

    async def acquire(self, matter_id: str) -> bool:
        now = datetime.now(UTC)
        if self._leases.get(matter_id, now) > now:
            return False
        self._leases[matter_id] = now + LEASE
        return True

    async def release(self, matter_id: str) -> None:
        self._leases.pop(matter_id, None)

    async def get_checklist(self, matter_id: str) -> Checklist | None:
        checklist = self.checklists.get(matter_id)
        return checklist.model_copy(deep=True) if checklist else None

    async def save_checklist(self, checklist: Checklist) -> None:
        self.checklists[checklist.matter_id] = checklist.model_copy(deep=True)

    async def list_evidence(self, matter_id: str) -> list[Evidence]:
        return [e.model_copy(deep=True) for e in self.evidence.get(matter_id, [])]

    async def add_evidence(self, evidence: Evidence) -> Evidence:
        records = self.evidence.setdefault(evidence.matter_id, [])
        existing = next((e for e in records if e.dedupe_key == evidence.dedupe_key), None)
        if existing:
            return existing.model_copy(deep=True)
        stored = evidence.model_copy(update={"evidence_id": f"E{len(records) + 1}"})
        records.append(stored)
        return stored.model_copy(deep=True)

    async def save_verification(self, report: VerificationReport) -> None:
        self.verifications.setdefault(report.matter_id, []).append(report.model_copy(deep=True))

    async def commit_verified(self, matter: PermitMatter, report: VerificationReport, pin: TrustPin,
                              sources: InMemorySourceRepository, identity: PropertyIdentity | None,
                              properties: InMemoryPropertyRepository) -> bool:
        """Persist the VERIFIED report and matter only if every pinned source and the property the gate read
        (``identity``, C2) are unchanged, atomically with respect to status changes (same lock). Returns False,
        writing nothing, if either moved after the gate or the property has no identity to bind to."""
        _check_pair(matter, report)
        async with sources.trust_lock:
            stored = self.matters.get(matter.matter_id)
            if _already_committed(stored, report):
                return True  # idempotent: this exact commit already happened
            _check_floor(self.floor, report)
            if not sources.pin_holds(pin.versions):
                return False
            if not _binds(identity, matter) or not properties.identity_holds(identity):
                return False
            if (stored is None or stored.state != MatterState.VERIFYING or stored.revision != matter.revision
                    or stored.property_id != matter.property_id):
                raise MatterCommitConflict("The matter is missing or no longer in the state that was verified.")
            self.verifications.setdefault(report.matter_id, []).append(report.model_copy(deep=True))
            self.matters[matter.matter_id] = matter.model_copy(deep=True)
            return True

    async def latest_verification(self, matter_id: str) -> VerificationReport | None:
        reports = self.verifications.get(matter_id)
        return reports[-1].model_copy(deep=True) if reports else None


class MongoPermitRepository:
    def __init__(self, client: AsyncMongoClient, db_name: str) -> None:
        self._client = client
        db = client[db_name]
        self._matters = db["permit_matters"]
        self._checklists = db["permit_checklists"]
        self._evidence = db["permit_evidence"]
        self._verifications = db["permit_verifications"]
        self._policy = db["verification_policy"]

    async def ensure_indexes(self) -> None:
        await self._matters.create_index([("property_id", ASCENDING), ("created_at", DESCENDING)])
        await self._evidence.create_index([("matter_id", ASCENDING), ("seq", ASCENDING)])
        await self._evidence.create_index([("matter_id", ASCENDING), ("dedupe_key", ASCENDING)], unique=True)
        await self._verifications.create_index([("matter_id", ASCENDING), ("created_at", DESCENDING)])
        # MU-9 (M8): the server-side VERIFIED rule is installed by every deployment of this code, so a later rollback
        # to a pre-MU-9 revision can't commit VERIFIED even if nobody ran raise-protocol-floor. Fail closed: without
        # it, rollback protection would silently be absent, so the service does not start (the database user needs
        # the collMod privilege on this database).
        try:
            await self.apply_validator(await self.get_floor())
        except StorageUnavailableError:
            logger.error("MU-9: could not install the permit_verifications validator; refusing to start without "
                         "server-side rollback protection. Grant collMod on the database or run raise-protocol-floor.")
            raise

    async def create_matter(self, matter: PermitMatter, access_hash: str) -> None:
        await self._call(self._matters.insert_one(
            {"_id": matter.matter_id, "access_hash": access_hash, **matter.model_dump(mode="python")}
        ))

    async def has_access(self, matter_id: str, access_hash: str) -> bool:
        doc = await self._call(self._matters.find_one({"_id": matter_id}, {"access_hash": 1}))
        stored = doc.get("access_hash") if doc else None
        return isinstance(stored, str) and hmac.compare_digest(stored, access_hash)

    async def get_matter(self, matter_id: str) -> PermitMatter | None:
        doc = await self._call(self._matters.find_one({"_id": matter_id}))
        return PermitMatter.model_validate(doc) if doc else None

    async def save_matter(self, matter: PermitMatter) -> None:
        result = await self._call(self._matters.update_one(
            {"_id": matter.matter_id, "state": {"$ne": MatterState.VERIFIED.value}},
            {"$set": matter.model_dump(mode="python")}))
        if result.matched_count == 0:
            stored = await self._call(self._matters.find_one({"_id": matter.matter_id}))
            if stored is not None and stored.get("state") == MatterState.VERIFIED:
                raise MatterAlreadyVerified("This matter is already VERIFIED.")

    async def acquire(self, matter_id: str) -> bool:
        now = datetime.now(UTC)
        result = await self._call(
            self._matters.update_one(
                {"_id": matter_id, "$or": [{"lease_until": {"$exists": False}}, {"lease_until": {"$lt": now}}]},
                {"$set": {"lease_until": now + LEASE}},
            )
        )
        return result.matched_count == 1

    async def release(self, matter_id: str) -> None:
        await self._call(self._matters.update_one({"_id": matter_id}, {"$unset": {"lease_until": ""}}))

    async def get_checklist(self, matter_id: str) -> Checklist | None:
        doc = await self._call(self._checklists.find_one({"_id": matter_id}))
        return Checklist.model_validate(doc) if doc else None

    async def save_checklist(self, checklist: Checklist) -> None:
        await self._call(
            self._checklists.replace_one(
                {"_id": checklist.matter_id}, {"_id": checklist.matter_id, **checklist.model_dump(mode="python")}, upsert=True
            )
        )

    async def list_evidence(self, matter_id: str) -> list[Evidence]:
        docs = await self._call(self._evidence.find({"matter_id": matter_id}).sort("seq", ASCENDING).to_list(None))
        return [Evidence.model_validate(doc) for doc in docs]

    async def add_evidence(self, evidence: Evidence) -> Evidence:
        # Runs under the matter lease, so sequence numbers can't race.
        existing = await self._call(
            self._evidence.find_one({"matter_id": evidence.matter_id, "dedupe_key": evidence.dedupe_key})
        )
        if existing:
            return Evidence.model_validate(existing)
        seq = await self._call(self._evidence.count_documents({"matter_id": evidence.matter_id})) + 1
        stored = evidence.model_copy(update={"evidence_id": f"E{seq}"})
        await self._call(
            self._evidence.insert_one(
                {"_id": f"{evidence.matter_id}:{stored.evidence_id}", "seq": seq, **stored.model_dump(mode="python")}
            )
        )
        return stored

    async def save_verification(self, report: VerificationReport) -> None:
        await self._call(
            self._verifications.insert_one({"_id": report.verification_id, **report.model_dump(mode="python")})
        )

    async def get_floor(self) -> Floor:
        return Floor.from_doc(await self._call(self._policy.find_one({"_id": FLOOR_ID})))

    async def store_floor(self, current: Floor, new: Floor) -> bool:
        """Write ``new`` only if the stored floor is still ``current`` (no concurrent change); True if written."""
        if current == DEFAULT_FLOOR and not current.history:
            exists = await self._call(self._policy.find_one({"_id": FLOOR_ID}))
            if exists is None:
                await self._call(self._policy.insert_one(new.to_doc()))
                return True
        result = await self._call(self._policy.replace_one(
            {"_id": FLOOR_ID, "min_protocol": current.min_protocol, "known_unsafe": list(current.known_unsafe)},
            new.to_doc()))
        return result.matched_count == 1

    async def apply_validator(self, floor: Floor) -> None:
        """Install the server-side VERIFIED rule (``protocol.validator``); existing documents are not re-checked."""
        db = self._verifications.database
        rule = validator(floor)
        if "permit_verifications" not in await self._call(db.list_collection_names()):
            await self._call(db.create_collection("permit_verifications", validator=rule,
                                                  validationLevel="moderate", validationAction="error"))
            return
        await self._call(db.command("collMod", "permit_verifications", validator=rule,
                                    validationLevel="moderate", validationAction="error"))

    async def raise_floor(self, current: Floor, new: Floor) -> bool:
        """Install the stricter validator first, then store the floor: if storing fails, the server is already at
        least as strict as the stored floor (never the other way round). True if the floor was stored."""
        await self.apply_validator(new)
        return await self.store_floor(current, new)

    async def flag_superseded(self, floor: Floor) -> int:
        """Mark VERIFIED reports from protocols the floor no longer admits (including pre-MU-9 ones, which have no
        protocol field) as superseded, and their matters with them: both stay as history, flagged for
        re-verification, so no client reads them as currently verified. ``superseded_protocol: None`` matches both
        a missing field (pre-MU-9) and the ``null`` that current reports store."""
        stale = {"outcome": "VERIFIED", "superseded_protocol": None,
                 "$or": [{"protocol": {"$exists": False}}, {"protocol": {"$nin": floor.admitted()}}]}
        by_protocol: dict[str, list[str]] = {}
        async for d in self._verifications.find(stale, {"_id": 1, "protocol": 1}):
            by_protocol.setdefault(d.get("protocol") or "statement-v1", []).append(d["_id"])
        flagged = 0
        for protocol, ids in by_protocol.items():
            # Matters first: if the report update then fails, a rerun still finds these reports (still unflagged)
            # and repeats both; the matter update is idempotent.
            await self._call(self._matters.update_many(
                {"state": MatterState.VERIFIED.value, "latest_verification_id": {"$in": ids}},
                {"$set": {"superseded_protocol": protocol}}))
            result = await self._call(self._verifications.update_many(
                {"_id": {"$in": ids}}, {"$set": {"superseded_protocol": protocol}}))
            flagged += result.modified_count
        return flagged

    async def latest_verification(self, matter_id: str) -> VerificationReport | None:
        doc = await self._call(
            self._verifications.find_one({"matter_id": matter_id}, sort=[("created_at", DESCENDING)])
        )
        return VerificationReport.model_validate(doc) if doc else None

    async def commit_verified(self, matter: PermitMatter, report: VerificationReport, pin: TrustPin,
                              sources: MongoSourceRepository, identity: PropertyIdentity | None,
                              properties: MongoPropertyRepository) -> bool:
        """One multi-document transaction (MongoDB core API, with the documented retry pattern):

        - idempotent: a matter already VERIFIED by this report is success, with no writes;
        - the report's protocol must be admitted by the persisted floor (read in the transaction; MU-9), else
          ``ProtocolBelowFloor``; the collection validator enforces the same server-side;
        - every pinned source is matched on its (status, trust_version) and written, so a concurrent status change
          is a write conflict, never a silent interleaving (CX-2);
        - the property is matched on the identity the gate read (version, active, no merge in flight) and written
          the same way, so a save, merge or purge after the gate aborts the commit (C2, ``identity_filter``);
        - the matter must match exactly ``{_id, state: VERIFYING, revision, property_id}``; anything else aborts
          everything;
        - then the report is inserted.

        Returns False (nothing written) if a pin or the property moved, or the property has no identity to bind to. ``TransientTransactionError`` re-runs the whole transaction;
        ``UnknownTransactionCommitResult`` retries only the commit, and if it stays unknown raises
        ``CommitOutcomeUnknown`` (never a failure: the caller reads the matter back). Other errors abort and raise
        ``StorageUnavailableError``; ``MatterCommitConflict`` aborts and is raised. Never a partial write."""
        _check_pair(matter, report)
        if not _binds(identity, matter):
            return False
        now = datetime.now(UTC)
        async with self._client.start_session() as session:
            for attempt in range(_TXN_ATTEMPTS):
                last = attempt + 1 == _TXN_ATTEMPTS
                try:
                    await session.start_transaction()
                    stored = await self._matters.find_one({"_id": matter.matter_id}, session=session)
                    if _already_committed(stored, report):
                        await _abort(session)
                        return True
                    _check_floor(Floor.from_doc(await self._policy.find_one({"_id": FLOOR_ID}, session=session)),
                                 report)
                    for source_id, (status, version) in sorted(pin.versions.items()):
                        result = await sources.collection.update_one(
                            sources.pin_filter(source_id, status, version),
                            {"$set": {"last_verified_commit_at": now}}, session=session)
                        if result.matched_count != 1:
                            raise _PinMoved(source_id)
                    result = await properties.collection.update_one(
                        identity_filter(identity), {"$set": {"last_verified_commit_at": now}}, session=session)
                    if result.matched_count != 1:
                        raise _PinMoved(identity.property_id)
                    result = await self._matters.update_one(
                        {"_id": matter.matter_id, "state": MatterState.VERIFYING.value, "revision": matter.revision,
                         "property_id": matter.property_id},
                        {"$set": matter.model_dump(mode="python")}, session=session)
                    if result.matched_count != 1:
                        raise MatterCommitConflict("The matter is missing or no longer in the state that was verified.")
                    await self._verifications.insert_one(
                        {"_id": report.verification_id, **report.model_dump(mode="python")}, session=session)
                except _PinMoved:
                    await _abort(session)
                    return False
                except MatterCommitConflict:
                    await _abort(session)
                    raise
                except DuplicateKeyError:
                    await _abort(session)
                    raise MatterCommitConflict("This verification report already exists.") from None
                except PyMongoError as exc:
                    await _abort(session)
                    if exc.has_error_label("TransientTransactionError"):
                        if last:
                            return False  # nothing committed; the caller re-runs the gate
                        continue
                    raise StorageUnavailableError(_UNAVAILABLE) from None
                try:
                    await _commit_with_retry(session)
                except PyMongoError as exc:
                    if exc.has_error_label("TransientTransactionError"):  # not committed
                        if last:
                            return False
                        continue
                    raise StorageUnavailableError(_UNAVAILABLE) from None
                return True
        return False

    @staticmethod
    async def _call(awaitable):
        try:
            return await awaitable
        except PyMongoError:
            raise StorageUnavailableError(_UNAVAILABLE) from None
