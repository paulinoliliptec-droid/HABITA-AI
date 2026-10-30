"""HR-003 CX-2 (final): VERIFIED is committed atomically with the registry state the final gate decided on.

The final gate reads every applicable source's (status, trust_version) once (a ``TrustPin``); the VERIFIED report and
matter are persisted by ``commit_verified`` only while that pin still holds — under the same lock as status changes
(in memory) or in one MongoDB transaction that writes every pinned source (so a concurrent status change is a write
conflict). If anything moved, nothing is written and the gate re-runs on the new state.
"""

import asyncio
import inspect
from datetime import UTC, datetime

import pytest
from pymongo.errors import OperationFailure, PyMongoError

from app.core.errors import StorageUnavailableError
from app.schemas.permit import MatterState
from app.schemas.sources import StatusChange
from app.services.sources.catalog import ALL_SOURCES
from app.services.sources.registry import OfficialSourceRegistry, TrustPin
from app.services.sources.repository import InMemorySourceRepository, MongoSourceRepository
from tests.permit_fakes import ScriptedModel, make_client
from tests import test_permit_commit_durability as durability
from tests.test_permit_official_sources import auth, ingest_regulamento, run_matter

CIVIL = "pt-codigo-civil-propriedade-horizontal"  # the only support of unit_conversion; cited by the draft
SIMPLEX = "pt-simplex-urbanistico"  # one of two supports of licensing_procedure (mixed support); not cited
RJUE = "pt-rjue"


def workflow_of(client):
    return client.app.state.permit_workflow


def registry_of(client):
    return client.app.state.official_sources


async def retire(registry, source_id):
    await registry.change_status(source_id, "retired", operator="ops", reason="test: retired during commit")


async def restore(registry, source_id):
    for status in ("candidate", "validated", "trusted"):
        await registry.change_status(source_id, status, operator="ops", reason="test: restored")


def after_gate(client, change, *, times=1):
    """Run ``change`` right after the final gate returns (before the commit), on the first ``times`` gates."""
    wf, calls = workflow_of(client), []
    original = wf._verifier.final_gate

    async def gate(*args, **kwargs):
        report = await original(*args, **kwargs)
        pinned = len(args) >= 7 or kwargs.get("pin") is not None  # the workflow's gate (verify() runs its own too)
        if pinned:
            calls.append(report)
            if len(calls) <= times:
                await change()
        return report
    wf._verifier.final_gate = gate
    return calls


def count_commits(client):
    repo, results = workflow_of(client)._repo, []
    original = repo.commit_verified

    async def commit(*args, **kwargs):
        ok = await original(*args, **kwargs)
        results.append(ok)
        return ok
    repo.commit_verified = commit
    return results


def outcome(client, mid, token):
    matter = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
    reports = workflow_of(client)._repo.verifications.get(mid, [])
    return matter, reports


def assert_no_verified_from_stale_state(matter, reports, source_id):
    assert matter["state"] != "VERIFIED"
    assert all(r.outcome != "VERIFIED" for r in reports)  # no VERIFIED report was ever persisted
    assert any(r.trust_pin.get(source_id, "").startswith("retired@") for r in reports)


# --- the exact Codex sequence and its neighbours -------------------------------------------------------------------

def test_codex_race_retired_after_the_final_gate_before_persistence_is_never_verified():
    """1. trusted during the final gate; 2. retired after the gate, before persistence; 3. not VERIFIED."""
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        gates = after_gate(client, lambda: retire(registry_of(client), CIVIL))
        commits = count_commits(client)
        mid, token = run_matter(client)
        matter, reports = outcome(client, mid, token)
    assert gates[0].outcome == "VERIFIED" and gates[0].trust_pin[CIVIL] == "trusted@0"  # the gate did pass
    assert commits[0] is False  # ... but the commit bound to that read was refused
    assert_no_verified_from_stale_state(matter, reports, CIVIL)


def test_retired_immediately_before_persistence_is_never_verified():
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        repo, registry = workflow_of(client)._repo, registry_of(client)
        original, results = repo.commit_verified, []

        async def commit(*args, **kwargs):
            if not results:
                await retire(registry, CIVIL)  # the last await before the write
            results.append(await original(*args, **kwargs))
            return results[-1]
        repo.commit_verified = commit
        mid, token = run_matter(client)
        matter, reports = outcome(client, mid, token)
    assert results[0] is False
    assert_no_verified_from_stale_state(matter, reports, CIVIL)


def test_retired_during_model_review_is_never_verified():
    """The reviewer approves while the source is retired (the earlier CX-2 race) — still caught."""
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        model, registry = workflow_of(client)._model, registry_of(client)
        approve = model.verification

        def retiring_review(payload):
            registry.repository.sources[CIVIL].status = "retired"  # lands during the model call
            registry.repository.sources[CIVIL].trust_version += 1
            return approve(payload)
        model.verification = retiring_review
        mid, token = run_matter(client)
        matter, reports = outcome(client, mid, token)
    assert_no_verified_from_stale_state(matter, reports, CIVIL)


def test_retired_and_restored_between_gate_and_commit_re_gates_then_verifies_on_the_current_state():
    """Same status, newer version (ABA): the stale commit is refused; the re-run gate on the restored state verifies."""
    async def flip():
        await retire(registry_of(client), CIVIL)
        await restore(registry_of(client), CIVIL)

    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        gates = after_gate(client, flip)
        commits = count_commits(client)
        mid, token = run_matter(client)
        matter, reports = outcome(client, mid, token)
    assert commits == [False, True]
    assert matter["state"] == "VERIFIED"
    [verified] = [r for r in reports if r.outcome == "VERIFIED"]
    assert verified.trust_pin[CIVIL] == "trusted@4" and gates[0].trust_pin[CIVIL] == "trusted@0"


def test_two_concurrent_changes_after_the_gate_are_never_verified():
    async def both():
        await asyncio.gather(retire(registry_of(client), CIVIL), retire(registry_of(client), RJUE))

    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        after_gate(client, both)
        mid, token = run_matter(client)
        matter, reports = outcome(client, mid, token)
    assert_no_verified_from_stale_state(matter, reports, CIVIL)
    assert any(r.trust_pin.get(RJUE, "").startswith("retired@") for r in reports)


@pytest.mark.parametrize("retirement_first", [True, False], ids=["retire-then-commit", "commit-then-retire"])
def test_commit_racing_a_retirement_is_serialised(retirement_first):
    """Commit and retirement started together: either the retirement wins (no VERIFIED) or the commit wins and the
    retirement is ordered after it (VERIFIED reflects the state at commit time). Never VERIFIED on a moved pin."""
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        repo, registry = workflow_of(client)._repo, registry_of(client)
        original, log = repo.commit_verified, []

        async def commit(matter, report, pin, sources, *binding):
            async def do_commit():
                ok = await original(matter, report, pin, sources, *binding)
                log.append(("commit", ok))
                return ok

            async def do_retire():
                await retire(registry, CIVIL)
                log.append(("retire", None))
            if len([e for e in log if e[0] == "commit"]) == 0:
                tasks = (do_retire(), do_commit()) if retirement_first else (do_commit(), do_retire())
                results = await asyncio.gather(*tasks)
                return next(r for r in results if isinstance(r, bool))
            return await do_commit()
        repo.commit_verified = commit
        mid, token = run_matter(client)
        matter, reports = outcome(client, mid, token)
    first_commit = next(ok for kind, ok in log if kind == "commit")
    retire_at = log.index(("retire", None))
    if matter["state"] == "VERIFIED":
        assert first_commit is True and log.index(("commit", True)) < retire_at
        [verified] = [r for r in reports if r.outcome == "VERIFIED"]
        assert verified.trust_pin[CIVIL] == "trusted@0"
    else:
        assert all(r.outcome != "VERIFIED" for r in reports)


def test_mixed_support_change_re_gates_and_verifies_exactly_on_the_new_state():
    """SIMPLEX is one of two supports of licensing_procedure: after its retirement the re-run gate still verifies,
    and the persisted VERIFIED report records the state it verified (SIMPLEX retired, its evidence excluded)."""
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        after_gate(client, lambda: retire(registry_of(client), SIMPLEX))
        commits = count_commits(client)
        mid, token = run_matter(client)
        matter, reports = outcome(client, mid, token)
        evidence = client.get(f"/api/permit/matters/{mid}/evidence", headers=auth(token)).json()
    assert commits == [False, True] and matter["state"] == "VERIFIED"
    [verified] = [r for r in reports if r.outcome == "VERIFIED"]
    assert verified.trust_pin[SIMPLEX] == "retired@1" and verified.checks["sources_trusted"]
    simplex_ids = {e["evidence_id"] for e in evidence if (e.get("provenance") or {}).get("source_id") == SIMPLEX}
    assert simplex_ids and simplex_ids <= {x["evidence_id"] for x in verified.excluded_evidence}


def test_a_change_to_a_source_of_another_jurisdiction_does_not_disturb_the_commit():
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        registry = registry_of(client)
        porto = registry.repository.sources[RJUE].model_copy(update={
            "source_id": "porto-pdm", "jurisdiction_id": "pt/porto/porto", "status": "trusted", "trust_version": 0})
        client.portal.call(registry.repository.insert_source, porto)

        async def change_porto():
            await registry.repository.set_status("porto-pdm", StatusChange(
                status="retired", operator="ops", reason="test", at=datetime.now(UTC)))
        after_gate(client, change_porto)
        commits = count_commits(client)
        mid, token = run_matter(client)
        matter, reports = outcome(client, mid, token)
    assert commits == [True] and matter["state"] == "VERIFIED"
    [verified] = [r for r in reports if r.outcome == "VERIFIED"]
    assert "porto-pdm" not in verified.trust_pin


def test_a_registry_that_keeps_changing_ends_failed_and_resumable_never_verified():
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        registry = registry_of(client)

        async def bump():  # an unrelated, applicable source changes after every gate
            source = registry.repository.sources["cascais-pdm-planta-02-05"]
            await registry.repository.set_status(source.source_id, StatusChange(
                status=source.status, operator="ops", reason="test: churn", at=datetime.now(UTC)))
        after_gate(client, bump, times=99)
        mid, token = run_matter(client)
        matter, reports = outcome(client, mid, token)
    assert matter["state"] == "FAILED" and matter["error"]["code"] == "trust_changed"
    assert all(r.outcome != "VERIFIED" for r in reports)


# --- no window: a retirement injected at every await point from the review to the commit ----------------------------

class Instrumented:
    """Proxies a repository; before each awaited call (once armed) it may inject the retirement."""

    def __init__(self, target, hook):
        self._target, self._hook = target, hook

    def __getattr__(self, name):
        attr = getattr(self._target, name)
        if not inspect.iscoroutinefunction(attr):
            return attr

        async def call(*args, **kwargs):
            await self._hook(name)
            return await attr(*args, **kwargs)
        return call


def _run_with_injection(k):
    """Retire CIVIL just before the k-th awaited repository/registry call after the model review."""
    with make_client(ScriptedModel()) as client:
        ingest_regulamento(client)
        wf, registry = workflow_of(client), registry_of(client)
        state = {"armed": False, "n": 0, "busy": False, "log": []}

        async def hook(name):
            if not state["armed"] or state["busy"]:
                return
            state["n"] += 1
            if state["n"] == k:
                state["busy"] = True
                await retire(registry, CIVIL)
                state["log"].append("retire")
                state["busy"] = False

        wf._repo = Instrumented(wf._repo, hook)
        registry._repo = Instrumented(registry._repo, hook)
        original_verify, original_commit = wf._verifier.verify, wf._repo.commit_verified

        async def verify(*args, **kwargs):
            report = await original_verify(*args, **kwargs)
            state["armed"] = True  # from the end of the model review on
            return report
        wf._verifier.verify = verify

        async def commit(*args, **kwargs):
            ok = await original_commit(*args, **kwargs)
            state["log"].append(("commit", ok))
            return ok
        wf._repo.commit_verified = commit
        mid, token = run_matter(client)
        matter = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
        reports = wf._repo._target.verifications.get(mid, [])
    return matter, reports, state


def test_there_is_no_window_between_verification_and_persistence():
    """Exhaustive: for every await point between the end of the model review and the VERIFIED commit, retiring the
    relied-on source there never yields VERIFIED; VERIFIED happens only when the retirement comes after the commit."""
    injected_before_commit = 0
    for k in range(1, 200):
        matter, reports, state = _run_with_injection(k)
        if "retire" not in state["log"]:
            assert matter["state"] == "VERIFIED"  # k is past the end of the window: nothing was injected
            break
        retire_at = state["log"].index("retire")
        committed_at = next((i for i, e in enumerate(state["log"]) if e == ("commit", True)), None)
        if matter["state"] == "VERIFIED":
            assert committed_at is not None and committed_at < retire_at, (k, state["log"])
            [verified] = [r for r in reports if r.outcome == "VERIFIED"]
            assert verified.trust_pin[CIVIL] == "trusted@0"
        else:
            injected_before_commit += 1
            assert all(r.outcome != "VERIFIED" for r in reports), k
    else:
        pytest.fail("the injection points never ran past the commit")
    assert injected_before_commit >= 5  # the window really was exercised at several points


# --- the MongoDB transaction (logic against a transactional fake; atomicity itself is MongoDB's) ------------------
# The fake (buffered writes, scripted commit outcomes) lives in test_permit_commit_durability.


async def test_mongo_commit_writes_everything_only_while_every_pin_holds():
    client, permit, src = durability.stores()
    src._sources.docs["legacy"] = {"_id": "legacy", "status": "trusted"}  # written before trust_version: version 0
    m, r = durability.verified()
    pin = TrustPin({"pt-rjue": ("trusted", 2), "legacy": ("trusted", 0)})
    assert await permit.commit_verified(m, r, pin, src, durability.IDENT, durability.props(client))
    assert client.commits_applied == 1 and "pv_1" in permit._verifications.docs
    assert permit._matters.docs["pm_1"]["state"] == MatterState.VERIFIED
    assert all("last_verified_commit_at" in src._sources.docs[sid] for sid in ("pt-rjue", "legacy"))


@pytest.mark.parametrize("pin", [{"pt-rjue": ("trusted", 1)}, {"pt-rjue": ("retired", 2)},
                                 {"pt-rjue": ("trusted", 2), "gone": ("trusted", 0)}],
                         ids=["version-moved", "status-moved", "source-missing"])
async def test_mongo_commit_aborts_and_writes_nothing_when_a_pin_moved(pin):
    client, permit, src = durability.stores()
    m, r = durability.verified()
    assert await permit.commit_verified(m, r, TrustPin(pin), src, durability.IDENT, durability.props(client)) is False
    assert client.commits_applied == 0 and "pv_1" not in permit._verifications.docs
    assert permit._matters.docs["pm_1"]["state"] == "VERIFYING"
    assert "last_verified_commit_at" not in src._sources.docs["pt-rjue"]


async def test_mongo_write_conflict_with_a_status_change_is_a_refused_commit():
    """A pinned-source write conflict (a concurrent status change) is retried as a whole; if it persists, the commit
    is refused (nothing written) and the caller re-runs the gate."""
    client, permit, src = durability.stores()
    conflict = OperationFailure("WriteConflict")
    conflict._add_error_label("TransientTransactionError")
    client.fail_on["official_sources.update_one"] = conflict
    m, r = durability.verified()
    assert await permit.commit_verified(m, r, TrustPin({"pt-rjue": ("trusted", 2)}), src, durability.IDENT, durability.props(client)) is False
    assert "pv_1" not in permit._verifications.docs and client.commits_applied == 0


async def test_mongo_other_storage_errors_fail_closed():
    client, permit, src = durability.stores()
    client.fail_on["official_sources.update_one"] = PyMongoError("down")
    m, r = durability.verified()
    with pytest.raises(StorageUnavailableError):
        await permit.commit_verified(m, r, TrustPin({"pt-rjue": ("trusted", 2)}), src, durability.IDENT, durability.props(client))
    assert "pv_1" not in permit._verifications.docs


async def test_status_changes_bump_the_trust_version_atomically():
    repo = InMemorySourceRepository()
    registry = OfficialSourceRegistry(repo, ALL_SOURCES)
    await registry.seed()
    await retire(registry, CIVIL)
    await restore(registry, CIVIL)
    assert repo.sources[CIVIL].status == "trusted" and repo.sources[CIVIL].trust_version == 4
    pin = await registry.pin(["pt", "pt/lisboa", "pt/lisboa/cascais"])
    assert pin.versions[CIVIL] == ("trusted", 4) and CIVIL in pin.trusted_ids
    # Re-seeding never resets the operational version.
    await registry.seed()
    assert repo.sources[CIVIL].trust_version == 4


def test_mongo_status_change_increments_the_version_in_the_same_update():
    calls = []

    class Recording:
        async def update_one(self, flt, update, **kw):
            calls.append((flt, update))
    src = MongoSourceRepository.__new__(MongoSourceRepository)
    src._sources = Recording()
    asyncio.run(src.set_status("a", StatusChange(status="retired", operator="ops", reason="r", at=datetime.now(UTC))))
    [(flt, update)] = calls
    assert flt == {"_id": "a"} and update["$inc"] == {"trust_version": 1} and update["$set"]["status"] == "retired"
    assert MongoSourceRepository.pin_filter("a", "trusted", 0) == {"_id": "a", "status": "trusted",
                                                                  "trust_version": {"$in": [0, None]}}
