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
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.errors import ConflictError, StorageUnavailableError
from app.schemas.permit import Checklist, Evidence, MatterState, PermitMatter, VerificationReport
from app.services.sources.registry import TrustPin
from app.services.sources.repository import InMemorySourceRepository, MongoSourceRepository

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
                              sources: Any) -> bool: ...


class _PinMoved(Exception):
    """A pinned source changed after the final gate: the VERIFIED commit must not happen."""


class CommitOutcomeUnknown(StorageUnavailableError):
    """The VERIFIED transaction may or may not have committed (``UnknownTransactionCommitResult`` persisted through
    every commit retry). Not a failure: the caller reads the matter back to learn the outcome."""


class MatterCommitConflict(ConflictError):
    """The VERIFIED commit doesn't fit the stored matter (missing, another state or revision, already VERIFIED by
    another report) or the matter/report pair is inconsistent. Nothing was written."""


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
                              sources: InMemorySourceRepository) -> bool:
        """Persist the VERIFIED report and matter only if every pinned source is unchanged, atomically with respect
        to status changes (same lock). Returns False, writing nothing, if the registry moved after the gate."""
        _check_pair(matter, report)
        async with sources.trust_lock:
            stored = self.matters.get(matter.matter_id)
            if _already_committed(stored, report):
                return True  # idempotent: this exact commit already happened
            if not sources.pin_holds(pin.versions):
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

    async def ensure_indexes(self) -> None:
        await self._matters.create_index([("property_id", ASCENDING), ("created_at", DESCENDING)])
        await self._evidence.create_index([("matter_id", ASCENDING), ("seq", ASCENDING)])
        await self._evidence.create_index([("matter_id", ASCENDING), ("dedupe_key", ASCENDING)], unique=True)
        await self._verifications.create_index([("matter_id", ASCENDING), ("created_at", DESCENDING)])

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

    async def latest_verification(self, matter_id: str) -> VerificationReport | None:
        doc = await self._call(
            self._verifications.find_one({"matter_id": matter_id}, sort=[("created_at", DESCENDING)])
        )
        return VerificationReport.model_validate(doc) if doc else None

    async def commit_verified(self, matter: PermitMatter, report: VerificationReport, pin: TrustPin,
                              sources: MongoSourceRepository) -> bool:
        """One multi-document transaction (MongoDB core API, with the documented retry pattern):

        - idempotent: a matter already VERIFIED by this report is success, with no writes;
        - every pinned source is matched on its (status, trust_version) and written, so a concurrent status change
          is a write conflict, never a silent interleaving (CX-2);
        - the matter must match exactly ``{_id, state: VERIFYING, revision, property_id}``; anything else aborts
          everything;
        - then the report is inserted.

        Returns False (nothing written) if a pin moved. ``TransientTransactionError`` re-runs the whole transaction;
        ``UnknownTransactionCommitResult`` retries only the commit, and if it stays unknown raises
        ``CommitOutcomeUnknown`` (never a failure: the caller reads the matter back). Other errors abort and raise
        ``StorageUnavailableError``; ``MatterCommitConflict`` aborts and is raised. Never a partial write."""
        _check_pair(matter, report)
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
                    for source_id, (status, version) in sorted(pin.versions.items()):
                        result = await sources.collection.update_one(
                            sources.pin_filter(source_id, status, version),
                            {"$set": {"last_verified_commit_at": now}}, session=session)
                        if result.matched_count != 1:
                            raise _PinMoved(source_id)
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
