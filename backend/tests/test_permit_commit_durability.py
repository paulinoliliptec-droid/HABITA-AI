"""HR-003 CX-2 (Codex, after round 5): the VERIFIED commit is durable and coherent.

Finding 1: a MongoDB transaction can commit on the server while the client loses the acknowledgement
(``UnknownTransactionCommitResult``). That must never leave a VERIFIED report next to a FAILED matter.
Finding 2: the commit must never succeed — or leave an orphan VERIFIED report — when the matter it transitions
isn't there (or isn't the expected matter in the expected state).

The MongoDB side runs against a transactional fake (writes are buffered and applied only on commit) whose commit
outcome is scripted per call; the workflow side runs on the in-memory store with the commit outcome injected.
"""

from datetime import UTC, datetime

import pytest
from pymongo.errors import DuplicateKeyError, OperationFailure

from app.core.errors import StorageUnavailableError
from app.schemas.permit import MatterState, VerificationReport
from app.services.permit.protocol import CURRENT
from app.services.permit.repository import MongoPermitRepository
from app.services.sources.registry import TrustPin
from app.services.sources.repository import MongoSourceRepository
from tests.permit_fakes import ScriptedModel, make_client
from tests.test_permit_official_sources import auth, ingest_regulamento, run_matter
from tests.test_permit_verifier import matter as make_matter

# --- a transactional MongoDB fake ------------------------------------------------------------------------------


def _labelled(message, *labels):
    error = OperationFailure(message)
    for label in labels:
        error._add_error_label(label)
    return error


class FakeMongo:
    """Enough of a replica set: buffered transactional writes, commit outcomes scripted per commit call."""

    def __init__(self, commit_plan=()):
        self.collections: dict[str, FakeCollection] = {}
        self.commit_plan = list(commit_plan)  # "ok" | "lost_ack" | "unknown" | "transient" | "fatal"
        self.commits_attempted = self.commits_applied = self.aborts = 0
        self.fail_on: dict[str, Exception] = {}

    def __getitem__(self, name):
        return self if not self.collections or name not in self.collections else self.collections[name]

    def collection(self, name):
        return self.collections.setdefault(name, FakeCollection(self, name))

    def start_session(self):
        return FakeSession(self)


class FakeSession:
    def __init__(self, client):
        self.client, self.buffer, self.active = client, [], False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def in_transaction(self):
        return self.active

    async def start_transaction(self):
        self.buffer, self.active = [], True
        return _TxnContext(self)

    async def commit_transaction(self):
        client = self.client
        client.commits_attempted += 1
        action = client.commit_plan.pop(0) if client.commit_plan else "ok"
        if action in ("ok", "lost_ack") and self.buffer is not None:
            for apply in self.buffer:
                apply()
            client.commits_applied += 1
            self.buffer = None  # a retried commit of an applied transaction is a no-op (server semantics)
        elif action == "lost_ack" or (action == "ok" and self.buffer is None):
            pass
        self.active = action in ("unknown", "lost_ack") and False
        if action in ("lost_ack", "unknown"):
            self.active = True  # the driver still considers the transaction in progress until resolved
            raise _labelled("connection closed while awaiting commit", "UnknownTransactionCommitResult")
        if action == "transient":
            self.buffer, self.active = [], False
            raise _labelled("WriteConflict", "TransientTransactionError")
        if action == "fatal":
            self.buffer, self.active = [], False
            raise OperationFailure("Transaction numbers are only allowed on a replica set member")
        self.active = False

    async def abort_transaction(self):
        if self.active:
            self.client.aborts += 1
        self.buffer, self.active = [], False


class _TxnContext:
    """``async with await session.start_transaction()`` (the pre-fix style): commit on exit, abort on error."""

    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            await self.session.commit_transaction()
        else:
            await self.session.abort_transaction()
        return False


class _Result:
    def __init__(self, matched):
        self.matched_count = matched


def _matches(doc, flt):
    for key, want in flt.items():
        have = doc.get(key)
        if isinstance(want, dict):
            if "$in" in want and have not in want["$in"]:
                return False
            if "$ne" in want and have == want["$ne"]:
                return False
        elif have != want:
            return False
    return True


class FakeCollection:
    def __init__(self, client, name):
        self.client, self.name, self.docs = client, name, {}

    def _staged(self, session):
        """The document view inside a transaction: committed docs plus this transaction's buffered writes."""
        view = {k: dict(v) for k, v in self.docs.items()}
        for apply in (session.buffer or []) if session is not None else []:
            if getattr(apply, "collection", None) is self:
                apply(view)
        return view

    async def find_one(self, flt, session=None, **kw):
        if error := self.client.fail_on.get(f"{self.name}.find_one"):
            raise error
        return next((d for d in self._staged(session).values() if _matches(d, flt)), None)

    async def update_one(self, flt, update, session=None, **kw):
        if error := self.client.fail_on.get(f"{self.name}.update_one"):
            raise error
        doc = next((d for d in self._staged(session).values() if _matches(d, flt)), None)
        if doc is None:
            return _Result(0)
        key, changes = doc["_id"], update.get("$set", {})
        self._write(session, lambda view: view[key].update(changes))
        return _Result(1)

    async def insert_one(self, doc, session=None, **kw):
        if doc["_id"] in self._staged(session):
            raise DuplicateKeyError("E11000 duplicate key")
        self._write(session, lambda view: view.__setitem__(doc["_id"], dict(doc)))

    def _write(self, session, change):
        def apply(view=None):
            change(self.docs if view is None else view)
        apply.collection = self
        if session is None:
            apply()
        else:
            session.buffer.append(apply)


def stores(commit_plan=(), *, matter_state="VERIFYING", revision=0, with_matter=True):
    client = FakeMongo(commit_plan)
    permit = MongoPermitRepository.__new__(MongoPermitRepository)
    permit._client = client
    permit._matters = client.collection("permit_matters")
    permit._verifications = client.collection("permit_verifications")
    permit._policy = client.collection("verification_policy")
    src = MongoSourceRepository.__new__(MongoSourceRepository)
    src.client, src._sources = client, client.collection("official_sources")
    src._sources.docs["pt-rjue"] = {"_id": "pt-rjue", "status": "trusted", "trust_version": 2}
    if with_matter:
        permit._matters.docs["pm_1"] = {"_id": "pm_1", "matter_id": "pm_1", "state": matter_state, "revision": revision,
                                        "property_id": make_matter().property_id}
    return client, permit, src


PIN = TrustPin({"pt-rjue": ("trusted", 2)})


def verified(report_id="pv_1", matter_id="pm_1", revision=0):
    m = make_matter().model_copy(update={"matter_id": matter_id, "state": MatterState.VERIFIED, "revision": revision,
                                         "latest_verification_id": report_id})
    r = VerificationReport(verification_id=report_id, matter_id=matter_id, draft_revision=revision,
                           outcome="VERIFIED", issues=[], checks={"final_gate_passed": True},
                           created_at=datetime.now(UTC), protocol=CURRENT)
    return m, r


def persisted(permit):
    return permit._matters.docs.get("pm_1"), permit._verifications.docs


def coherent(permit):
    """Report and matter agree: either both VERIFIED (and linked) or no VERIFIED report at all."""
    matter, reports = persisted(permit)
    verified_reports = [r for r in reports.values() if r["outcome"] == "VERIFIED"]
    if matter and matter.get("state") == MatterState.VERIFIED:
        return [r["_id"] for r in verified_reports] == [matter["latest_verification_id"]]
    return not verified_reports


# --- Finding 1: unknown commit result ---------------------------------------------------------------------------

async def test_committed_but_acknowledgement_lost_is_resolved_as_committed():
    """The server applied the transaction, the response was lost; the retried commit is answered: committed."""
    client, permit, src = stores(["lost_ack", "ok"])
    m, r = verified()
    assert await permit.commit_verified(m, r, PIN, src) is True
    assert client.commits_applied == 1 and coherent(permit)
    assert persisted(permit)[0]["state"] == MatterState.VERIFIED


async def test_unknown_result_before_apply_is_retried_and_commits_once():
    client, permit, src = stores(["unknown", "ok"])
    m, r = verified()
    assert await permit.commit_verified(m, r, PIN, src) is True
    assert client.commits_attempted == 2 and client.commits_applied == 1 and coherent(permit)


async def test_repeated_unknown_result_never_reports_failure_while_the_outcome_is_unknown():
    """Every retry stays ambiguous: the repository says so (CommitOutcomeUnknown), it doesn't claim failure."""
    from app.services.permit.repository import CommitOutcomeUnknown
    client, permit, src = stores(["lost_ack"] + ["unknown"] * 20)
    m, r = verified()
    with pytest.raises(CommitOutcomeUnknown):
        await permit.commit_verified(m, r, PIN, src)
    assert coherent(permit)  # it did commit: report and matter are both VERIFIED and linked


async def test_transient_error_retries_the_whole_transaction_without_duplicates():
    client, permit, src = stores(["transient", "ok"])
    m, r = verified()
    assert await permit.commit_verified(m, r, PIN, src) is True
    assert list(permit._verifications.docs) == ["pv_1"] and coherent(permit)


async def test_a_definitive_error_leaves_nothing_verified():
    client, permit, src = stores(["fatal"])
    m, r = verified()
    with pytest.raises(StorageUnavailableError):
        await permit.commit_verified(m, r, PIN, src)
    matter, reports = persisted(permit)
    assert matter["state"] == "VERIFYING" and reports == {} and coherent(permit)


async def test_repeating_the_same_commit_is_idempotent():
    """A process retry of an already-committed commit: success, no second report, nothing rewritten."""
    client, permit, src = stores()
    m, r = verified()
    assert await permit.commit_verified(m, r, PIN, src) is True
    assert await permit.commit_verified(m, r, PIN, src) is True
    assert list(permit._verifications.docs) == ["pv_1"] and client.commits_applied == 1 and coherent(permit)


async def test_a_different_report_cannot_overwrite_a_verified_matter():
    client, permit, src = stores()
    m, r = verified()
    assert await permit.commit_verified(m, r, PIN, src) is True
    m2, r2 = verified("pv_2")
    from app.services.permit.repository import MatterCommitConflict
    with pytest.raises(MatterCommitConflict):
        await permit.commit_verified(m2, r2, PIN, src)
    assert list(permit._verifications.docs) == ["pv_1"] and coherent(permit)


async def test_a_moved_pin_still_aborts_with_no_writes():
    client, permit, src = stores()
    m, r = verified()
    assert await permit.commit_verified(m, r, TrustPin({"pt-rjue": ("trusted", 1)}), src) is False
    assert persisted(permit)[1] == {} and persisted(permit)[0]["state"] == "VERIFYING"


# --- Finding 2: the matter must exist, be the right one, in the expected state --------------------------------

async def test_missing_matter_never_gets_an_orphan_verified_report():
    from app.services.permit.repository import MatterCommitConflict
    client, permit, src = stores(with_matter=False)
    m, r = verified()
    with pytest.raises(MatterCommitConflict):
        await permit.commit_verified(m, r, PIN, src)
    assert permit._verifications.docs == {} and client.commits_applied == 0


async def test_matter_removed_concurrently_aborts_the_whole_transaction():
    """The matter disappears after the pins were checked: the zero-match update aborts everything."""
    from app.services.permit.repository import MatterCommitConflict
    client, permit, src = stores()
    original = permit._matters.update_one

    async def deleted_then_update(flt, update, session=None, **kw):
        permit._matters.docs.pop("pm_1", None)
        return await original(flt, update, session=session, **kw)
    permit._matters.update_one = deleted_then_update
    m, r = verified()
    with pytest.raises(MatterCommitConflict):
        await permit.commit_verified(m, r, PIN, src)
    assert permit._verifications.docs == {} and "last_verified_commit_at" not in src._sources.docs["pt-rjue"]


@pytest.mark.parametrize("state, revision", [("NEEDS_INPUT", 0), ("FAILED", 0), ("VERIFYING", 1), ("ESCALATE", 0)],
                         ids=["needs-input", "failed", "other-revision", "escalated"])
async def test_matter_in_an_unexpected_state_or_revision_fails_closed(state, revision):
    from app.services.permit.repository import MatterCommitConflict
    client, permit, src = stores(matter_state=state, revision=revision)
    m, r = verified()
    with pytest.raises(MatterCommitConflict):
        await permit.commit_verified(m, r, PIN, src)
    assert permit._verifications.docs == {} and persisted(permit)[0]["state"] == state


@pytest.mark.parametrize("which", ["report-for-another-matter", "matter-not-verified", "report-not-linked"])
async def test_a_wrong_matter_or_report_pair_is_refused_before_any_write(which):
    from app.services.permit.repository import MatterCommitConflict
    client, permit, src = stores()
    m, r = verified()
    if which == "report-for-another-matter":
        r = r.model_copy(update={"matter_id": "pm_2"})
    elif which == "matter-not-verified":
        m = m.model_copy(update={"state": MatterState.ESCALATE})
    else:
        m = m.model_copy(update={"latest_verification_id": "pv_other"})
    with pytest.raises(MatterCommitConflict):
        await permit.commit_verified(m, r, PIN, src)
    assert permit._verifications.docs == {} and client.commits_attempted == 0


async def test_normal_commit_writes_report_matter_and_pins_together():
    client, permit, src = stores()
    m, r = verified()
    assert await permit.commit_verified(m, r, PIN, src) is True
    matter, reports = persisted(permit)
    assert matter["state"] == MatterState.VERIFIED and matter["latest_verification_id"] == "pv_1"
    assert list(reports) == ["pv_1"] and "last_verified_commit_at" in src._sources.docs["pt-rjue"]


async def test_a_failure_part_way_leaves_no_partial_write():
    """The report insert fails after the matter update: nothing of the transaction survives."""
    client, permit, src = stores()
    client.fail_on["permit_verifications.insert_one"] = OperationFailure("disk full")
    original = permit._verifications.insert_one

    async def failing_insert(doc, session=None, **kw):
        raise OperationFailure("disk full")
    permit._verifications.insert_one = failing_insert
    m, r = verified()
    with pytest.raises(StorageUnavailableError):
        await permit.commit_verified(m, r, PIN, src)
    matter, reports = persisted(permit)
    assert matter["state"] == "VERIFYING" and reports == {} and client.commits_applied == 0
    _ = original


# --- the workflow: an in-doubt commit never leaves report and matter contradicting each other --------------------

@pytest.mark.parametrize("error", ["storage", "unknown"])
def test_workflow_commit_applied_but_error_reported_ends_verified_and_coherent(error):
    """Codex's end-to-end replay: the commit is applied, then the call errors. The matter is not marked FAILED over
    a VERIFIED report: the outcome is read back and adopted (or a FAILED write can't overwrite VERIFIED)."""
    from app.services.permit.repository import CommitOutcomeUnknown
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        repo = client.app.state.permit_workflow._repo
        original = repo.commit_verified

        async def applied_then_error(*args, **kwargs):
            await original(*args, **kwargs)
            raise (StorageUnavailableError("connection lost") if error == "storage"
                   else CommitOutcomeUnknown("commit outcome unknown"))
        repo.commit_verified = applied_then_error
        mid, token = run_matter(client)
        matter = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
        reports = repo.verifications[mid]
    assert matter["state"] == "VERIFIED"
    verified_reports = [r for r in reports if r.outcome == "VERIFIED"]
    assert [r.verification_id for r in verified_reports] == [matter["latest_verification_id"]]


def test_workflow_commit_not_applied_and_error_reported_ends_failed_without_a_verified_report():
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        repo = client.app.state.permit_workflow._repo

        async def not_applied(*args, **kwargs):
            raise StorageUnavailableError("connection lost")
        repo.commit_verified = not_applied
        mid, token = run_matter(client)
        matter = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
        reports = repo.verifications.get(mid, [])
    assert matter["state"] == "FAILED" and all(r.outcome != "VERIFIED" for r in reports)


def test_a_verified_matter_is_never_overwritten_by_a_later_save():
    """VERIFIED is written only by the atomic commit; no other save can turn it into anything else."""
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        mid, token = run_matter(client)
        wf = client.app.state.permit_workflow
        stored = client.portal.call(wf._repo.get_matter, mid)
        assert stored.state == "VERIFIED"
        stale = stored.model_copy(update={"state": MatterState.FAILED})
        from app.services.permit.repository import MatterAlreadyVerified
        with pytest.raises(MatterAlreadyVerified):
            client.portal.call(wf._repo.save_matter, stale)
        assert client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()["state"] == "VERIFIED"


def test_unknown_outcome_not_applied_then_process_retry_commits_exactly_once():
    """Unknown and not applied → read back: not committed → FAILED (coherent, no VERIFIED report); resuming the
    matter re-runs the gate and commits once."""
    from app.services.permit.repository import CommitOutcomeUnknown
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        repo = client.app.state.permit_workflow._repo
        original, calls = repo.commit_verified, []

        async def first_unknown(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise CommitOutcomeUnknown("commit outcome unknown")
            return await original(*args, **kwargs)
        repo.commit_verified = first_unknown
        mid, token = run_matter(client)
        failed = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
        assert failed["state"] == "FAILED" and all(r.outcome != "VERIFIED" for r in repo.verifications.get(mid, []))
        resumed = client.post(f"/api/permit/matters/{mid}/continue", headers=auth(token)).json()
        reports = repo.verifications[mid]
    assert resumed["state"] == "VERIFIED"
    assert [r.verification_id for r in reports if r.outcome == "VERIFIED"] == [resumed["latest_verification_id"]]


# --- report/matter linkage: property and revision (round 7) -------------------------------------------------------

async def test_mongo_stored_matter_of_another_property_aborts_everything():
    from app.services.permit.repository import MatterCommitConflict
    client, permit, src = stores()
    permit._matters.docs["pm_1"]["property_id"] = "prp_ffffffffffffffff"
    m, r = verified()
    with pytest.raises(MatterCommitConflict):
        await permit.commit_verified(m, r, PIN, src)
    assert permit._verifications.docs == {} and permit._matters.docs["pm_1"]["state"] == "VERIFYING"
    assert "last_verified_commit_at" not in src._sources.docs["pt-rjue"] and client.commits_applied == 0


def _with_draft(m, revision):
    from tests.test_permit_verifier import draft
    return m.model_copy(update={"draft": draft().model_copy(update={"revision": revision})})


@pytest.mark.parametrize("case", ["report-revision", "matter-revision", "draft-revision"])
async def test_mongo_revision_mismatch_is_refused_before_any_write(case):
    from app.services.permit.repository import MatterCommitConflict
    client, permit, src = stores()
    m, r = verified()
    if case == "report-revision":
        r = r.model_copy(update={"draft_revision": 1})
    elif case == "matter-revision":
        m = m.model_copy(update={"revision": 1})
    else:
        m = _with_draft(m, 1)  # the matter's draft is not the draft the report verified
    with pytest.raises(MatterCommitConflict):
        await permit.commit_verified(m, r, PIN, src)
    assert permit._verifications.docs == {} and client.commits_attempted == 0


async def test_mongo_matching_draft_revision_commits():
    client, permit, src = stores()
    m, r = verified()
    assert await permit.commit_verified(_with_draft(m, 0), r, PIN, src) is True
    assert list(permit._verifications.docs) == ["pv_1"] and coherent(permit)


@pytest.mark.parametrize("case", ["stored-other-property", "report-revision", "draft-revision"])
async def test_in_memory_linkage_mismatch_aborts_without_writes(case):
    from app.services.permit.repository import InMemoryPermitRepository, MatterCommitConflict
    from app.services.sources.repository import InMemorySourceRepository
    repo, sources = InMemoryPermitRepository(), InMemorySourceRepository()
    stored = make_matter().model_copy(update={"matter_id": "pm_1", "state": MatterState.VERIFYING, "revision": 0})
    if case == "stored-other-property":
        stored = stored.model_copy(update={"property_id": "prp_ffffffffffffffff"})
    repo.matters["pm_1"] = stored
    m, r = verified()
    if case == "report-revision":
        r = r.model_copy(update={"draft_revision": 1})
    elif case == "draft-revision":
        m = _with_draft(m, 1)
    with pytest.raises(MatterCommitConflict):
        await repo.commit_verified(m, r, TrustPin({}), sources)
    assert repo.verifications == {} and repo.matters["pm_1"].state == MatterState.VERIFYING
