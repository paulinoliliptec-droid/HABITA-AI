"""Permit Intelligence workflow: GOAL → CHECKLIST → TOOLS → EVIDENCE → DRAFT → VERIFICATION.

``run`` advances a matter from its *persisted* state until it reaches a stable
state (NEEDS_INPUT, VERIFIED, ESCALATE, FAILED). Every step persists its output
before the state changes, so a crash, a timeout or a NEEDS_INPUT pause resumes
from the saved checklist and evidence instead of starting over:

    PLANNING       planner writes the checklist (skipped if one exists)
    INVESTIGATING  baseline context tools, then a bounded tool loop, then the UNVERIFIED draft
    NEEDS_INPUT    waits for the user; ``supply_inputs`` records answers as evidence → INVESTIGATING
    DRAFT_READY    a draft exists and awaits verification
    VERIFYING      the independent verifier writes a report → VERIFIED | NEEDS_INPUT | ESCALATE,
                   or REJECTED → one revision (back to INVESTIGATING), then ESCALATE
    FAILED         records the failed state; ``run`` retries from there
"""

import json
import logging
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.core.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceNotConfiguredError,
    StorageUnavailableError,
    TrustChangedError,
    UnauthorizedError,
)
from app.core.rate_limit import ResolutionLimiter
from app.schemas.permit import (
    STABLE_STATES,
    Checklist,
    Claim,
    Conclusion,
    Condition,
    Draft,
    Evidence,
    MatterError,
    MatterState,
    MissingInput,
    NextAction,
    PermitMatter,
    ProcedureStep,
    ProgressEvent,
    Risk,
    VerificationReport,
)
from app.services.permit import prompts, requirements
from app.services.permit.model import ReasoningModel
from app.services.permit.repository import (
    MatterAlreadyVerified,
    PermitRepository,
    hash_token,
    new_access_token,
    new_matter_id,
)
from app.services.permit.sources.base import SourceRegistry
from app.services.planning.resolver import PlanningContextService
from app.db.property_repository import PropertyIdentity
from app.services.sources.registry import OfficialSourceRegistry, TrustPin
from app.services.sources.retrieval import RegulatoryRetriever
from app.services.permit.tools import TOOL_SPECS, PermitTools, compact_evidence
from app.services.permit.admissibility import render_draft
from app.services.permit.citations import reconcile_citations
from app.services.permit.verifier import Verifier
from app.services.property_location import PropertyLocationService

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 2
MAX_REVISIONS = 1
#: Final gate + atomic VERIFIED commit attempts while the registry keeps changing (then FAILED, resumable).
COMMIT_ATTEMPTS = 3
#: Investigation/draft passes per matter. With a fixed checklist a matter needs at most
#: ~3 (ask → answer → draft, plus one revision); more means it isn't converging.
MAX_ROUNDS = 4
MAX_STEPS = 12

#: Operational labels shown to users (never model reasoning).
LABELS = {
    MatterState.PLANNING: "Planning what must be established",
    MatterState.INVESTIGATING: "Gathering evidence from jurisdiction and regulatory sources",
    MatterState.NEEDS_INPUT: "Waiting for information from you",
    MatterState.DRAFT_READY: "Draft prepared, awaiting verification",
    MatterState.VERIFYING: "Verifying the draft against its evidence",
    MatterState.VERIFIED: "Verification complete",
    MatterState.ESCALATE: "Needs review by a qualified professional",
    MatterState.REJECTED: "The draft could not be verified against its evidence",
    MatterState.FAILED: "Interrupted; it can be resumed",
}

_BASES = {"none", "general_rule", "general_planning_explanation", "authority_confirmation", "parcel_determination",
          "user_declaration"}


def _basis(entry: dict) -> dict:
    """The statement's declared planning dependency and quote (anything unexpected counts as none; rules check it)."""
    basis = entry.get("planning_basis") if entry.get("planning_basis") in _BASES else "none"
    quote = entry.get("quote") if isinstance(entry.get("quote"), str) else None
    return {"planning_basis": basis, "quote": quote}


class PermitWorkflow:
    def __init__(
        self,
        *,
        repository: PermitRepository,
        properties: PropertyLocationService,
        sources: SourceRegistry,
        official: OfficialSourceRegistry,
        retriever: RegulatoryRetriever,
        planning: PlanningContextService,
        model: ReasoningModel,
        limiter: ResolutionLimiter | None = None,
    ) -> None:
        self._repo = repository
        self._properties = properties
        self._sources = sources
        self._official = official
        self._retriever = retriever
        self._planning = planning
        self._model = model
        self._verifier = Verifier(model, official, self._planning_state)
        self._limiter = limiter

    async def _planning_state(self, matter: PermitMatter):
        """The resolver's answer for the property *now*; a parcel determination must still agree with it."""
        prop = await self._properties.get(matter.property_id)
        return await self._planning.resolve(prop) if prop is not None else None

    # --- public operations ----------------------------------------------------------

    async def create(self, property_id: str, question: str) -> tuple[PermitMatter, str]:
        """Create a matter; returns it with its capability token (shown once, stored only as a hash)."""
        prop = await self._properties.get(property_id)
        if prop is None:
            raise NotFoundError("This property hasn't been resolved yet.")
        now = datetime.now(UTC)
        authority = prop.jurisdiction.local_authority
        matter = PermitMatter(
            matter_id=new_matter_id(),
            property_id=prop.property_id,
            question=question,
            state=MatterState.PLANNING,
            jurisdiction_id=prop.jurisdiction.id,
            authority_id=authority.id if authority else None,
            progress=[ProgressEvent(state=MatterState.PLANNING, label=LABELS[MatterState.PLANNING], at=now)],
            created_at=now,
            updated_at=now,
        )
        token = new_access_token()
        await self._repo.create_matter(matter, hash_token(token))
        return matter, token

    async def authorize(self, matter_id: str, token: str | None) -> None:
        """Require the matter's capability. Unknown matters and wrong tokens are indistinguishable."""
        if not token:
            raise UnauthorizedError("This permit matter needs its access token.")
        if not await self._repo.has_access(matter_id, hash_token(token)):
            raise ForbiddenError("This permit matter isn't available with these credentials.")

    async def get(self, matter_id: str) -> PermitMatter:
        matter = await self._repo.get_matter(matter_id)
        if matter is None:
            raise NotFoundError("This permit matter doesn't exist.")
        return matter

    async def checklist(self, matter_id: str) -> Checklist | None:
        await self.get(matter_id)
        return await self._repo.get_checklist(matter_id)

    async def evidence(self, matter_id: str) -> list[Evidence]:
        await self.get(matter_id)
        return await self._repo.list_evidence(matter_id)

    async def verification(self, matter_id: str):
        await self.get(matter_id)
        return await self._repo.latest_verification(matter_id)

    async def supply_inputs(self, matter_id: str, inputs: dict[str, str]) -> PermitMatter:
        matter = await self.get(matter_id)
        if matter.state != MatterState.NEEDS_INPUT:
            raise ConflictError("This matter isn't waiting for information.")
        expected = {m.input_key for m in matter.missing_inputs}
        unknown = sorted(set(inputs) - expected)
        if unknown:
            raise ConflictError(f"Unexpected information: {', '.join(unknown)}. Expected: {', '.join(sorted(expected))}.")
        if not await self._repo.acquire(matter_id):
            raise ConflictError("This matter is being processed. Please wait.")
        try:
            matter = await self.get(matter_id)
            questions = {m.input_key: m for m in matter.missing_inputs}
            for key, answer in inputs.items():
                await self._repo.add_evidence(
                    Evidence(
                        evidence_id="pending",
                        matter_id=matter_id,
                        source_type="user_statement",
                        source_title="Information supplied by the user",
                        source_reference=f"Answer to: {questions[key].question}",
                        jurisdiction_id=matter.jurisdiction_id,
                        retrieved_at=datetime.now(UTC),
                        claim_supported=key,
                        excerpt=answer,
                        structured={"input_key": key, "answer": answer},
                        confidence="medium",
                        verification_status="user_declared",
                        dedupe_key=f"input:{key}:{answer}",
                    )
                )
                matter.inputs[key] = answer
            matter.missing_inputs = [m for m in matter.missing_inputs if m.input_key not in matter.inputs]
            # Resume from the existing checklist and evidence: back to investigation, not planning.
            await self._transition(matter, MatterState.INVESTIGATING if not matter.missing_inputs else MatterState.NEEDS_INPUT)
            return matter
        finally:
            await self._repo.release(matter_id)

    async def run(self, matter_id: str) -> PermitMatter:
        matter = await self.get(matter_id)
        if matter.state in STABLE_STATES and matter.state != MatterState.FAILED:
            return matter
        # Spend boundary: one admission per run (a run makes several model calls).
        async with self._limiter.admit() if self._limiter else nullcontext():
            return await self._run_locked(matter_id)

    async def _run_locked(self, matter_id: str) -> PermitMatter:
        if not await self._repo.acquire(matter_id):
            raise ConflictError("This matter is being processed. Please wait.")
        try:
            matter = await self.get(matter_id)
            if matter.state == MatterState.FAILED and matter.error:
                matter.error, resume_at = None, matter.error.failed_state
                await self._transition(matter, resume_at)
            for _ in range(MAX_STEPS):
                if matter.state in STABLE_STATES:
                    break
                try:
                    await self._step(matter)
                except ServiceNotConfiguredError:
                    raise
                except AppError as exc:
                    matter.error = MatterError(code=exc.code, message=exc.message, failed_state=matter.state)
                    await self._transition(matter, MatterState.FAILED)
                except (ValidationError, ValueError, KeyError, TypeError):
                    logger.warning("Permit step %s produced invalid model output", matter.state)
                    matter.error = MatterError(code="invalid_model_output", failed_state=matter.state,
                                               message="The reasoning step returned an invalid result. It can be retried.")
                    await self._transition(matter, MatterState.FAILED)
            logger.info("Permit run matter=%s state=%s rounds=%d", matter.matter_id, matter.state, matter.rounds)
            return matter
        finally:
            await self._repo.release(matter_id)

    # --- steps --------------------------------------------------------------------

    async def _step(self, matter: PermitMatter) -> None:
        if matter.state == MatterState.PLANNING:
            await self._plan(matter)
        elif matter.state == MatterState.INVESTIGATING:
            await self._investigate(matter)
        elif matter.state in (MatterState.DRAFT_READY, MatterState.VERIFYING):
            await self._verify(matter)

    async def _plan(self, matter: PermitMatter) -> None:
        tools = self._tools(matter)
        chain = await tools.jurisdiction_chain()
        if not self._sources.covers(chain):
            await self._escalate(matter, "HABITA has no regulatory sources for this jurisdiction yet.")
            return
        checklist = await self._repo.get_checklist(matter.matter_id)
        if checklist is None:
            prop = await tools.property()
            context = {
                "goal": matter.question,
                "property": prop.formatted_address,
                "jurisdiction": [f"{lvl.label}: {lvl.name}" for lvl in prop.jurisdiction.levels],
                "checklist_keys": {
                    intent: [{"key": r.key, "owner": r.owner, "question": r.question} for r in reqs]
                    for intent, reqs in requirements.CATALOG.items()
                },
            }
            result = await self._call_model(prompts.PLANNER, context, prompts.CHECKLIST_SCHEMA, "checklist")
            checklist = self._checklist_from(matter, result)
            await self._repo.save_checklist(checklist)
        matter.intent = checklist.intent
        if checklist.intent == "out_of_scope":
            await self._escalate(matter, "HABITA's permit foundation covers unit conversions and general orientation only.")
            return
        await self._transition(matter, MatterState.INVESTIGATING)

    def _checklist_from(self, matter: PermitMatter, result: dict[str, Any]) -> Checklist:
        intent = result["intent"]
        valid = requirements.requirements_for(intent)
        wording: dict[str, str] = {}
        for q in result.get("questions", []):
            key = q.get("key") if isinstance(q, dict) else None
            if key in valid and isinstance(q.get("question"), str) and q["question"].strip():
                wording[key] = q["question"].strip()[:300]
            else:
                # Unknown or foreign keys are rejected: never persisted, never turned into new items.
                logger.info("Planner proposed an unknown checklist key; ignored")
        now = datetime.now(UTC)
        return Checklist(matter_id=matter.matter_id, intent=intent, intent_summary=result["intent_summary"],
                         items=requirements.build_checklist_items(intent, wording),
                         model_id=self._model.model_id, created_at=now, updated_at=now)

    async def _investigate(self, matter: PermitMatter) -> None:
        checklist = await self._repo.get_checklist(matter.matter_id)
        if checklist is None:
            await self._transition(matter, MatterState.PLANNING)
            return
        matter.rounds += 1
        if matter.rounds > MAX_ROUNDS:
            await self._escalate(matter, "The investigation reached its round limit without converging.", checklist)
            return

        tools = self._tools(matter, checklist)
        # Baseline facts come from tools, deterministically, before the model reasons.
        for name in ("get_property_context", "get_jurisdiction_context", "get_competent_authority", "get_planning_context"):
            await tools.execute(name, {})
        if not matter.tool_loop_done:
            await self._tool_loop(matter, checklist, tools)
            matter.tool_loop_done = True
        # Whatever the model didn't search for, HABITA searches deterministically for each requirement.
        await self._fill_gaps(checklist, tools)

        # Only evidence admissible now (trusted, in-chain sources) settles items or reaches the drafter.
        evidence = await tools.admissible_evidence()
        checklist.items = requirements.reconcile(checklist.intent, checklist.items, evidence)
        checklist.updated_at = datetime.now(UTC)
        await self._repo.save_checklist(checklist)

        questions = _user_questions(matter, checklist, tools.requested)
        if questions:
            matter.missing_inputs = questions
            await self._transition(matter, MatterState.NEEDS_INPUT)
            return
        gaps = [i.key for i in checklist.items if i.required and i.status == "open"]
        if gaps:
            await self._escalate(matter, "HABITA could not find evidence for: " + ", ".join(gaps) + ".", checklist)
            return
        matter.missing_inputs = []
        matter.draft = await self._draft(matter, checklist, evidence, tools)
        await self._transition(matter, MatterState.DRAFT_READY)

    async def _fill_gaps(self, checklist: Checklist, tools: PermitTools) -> None:
        evidence = await tools.admissible_evidence()
        current = requirements.reconcile(checklist.intent, checklist.items, evidence)
        reqs = requirements.requirements_for(checklist.intent)
        for item in current:
            req = reqs.get(item.key)
            if req and req.search_topics and not item.evidence_ids:
                await tools.execute("search_regulatory_sources", {"topics": list(req.search_topics), "query": item.question})

    async def _tool_loop(self, matter: PermitMatter, checklist: Checklist, tools: PermitTools) -> None:
        evidence = await tools.admissible_evidence()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": prompts.INVESTIGATOR},
            {"role": "user", "content": json.dumps({
                "goal": matter.question,
                "user_answers": matter.inputs,
                "checklist": [{"key": i.key, "owner": i.owner, "question": i.question} for i in checklist.items],
                "evidence_so_far": compact_evidence(evidence),
            }, ensure_ascii=False)},
        ]
        for _ in range(MAX_TOOL_ROUNDS):
            result = await self._model.chat(messages, tools=TOOL_SPECS)
            if not result.tool_calls:
                return
            messages.append({
                "role": "assistant",
                "content": result.content or "",
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                    for c in result.tool_calls
                ],
            })
            for call in result.tool_calls:
                # Operational trace: tool name only (arguments may contain user text).
                logger.info("Permit model tool call matter=%s tool=%s", matter.matter_id, call.name)
                output = await tools.execute(call.name, call.arguments)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(output, ensure_ascii=False)})

    async def _draft(self, matter: PermitMatter, checklist: Checklist, evidence: list[Evidence],
                     tools: PermitTools) -> Draft:
        conditions = requirements.conditions_for(checklist.intent, checklist.items, evidence)
        linked = {eid for i in checklist.items for eid in i.evidence_ids}
        payload = {
            "goal": matter.question,
            "intent": checklist.intent,
            "user_answers": matter.inputs,
            "checklist": [{"key": i.key, "question": i.question, "owner": i.owner, "status": i.status,
                           "evidence": i.evidence_ids} for i in checklist.items],
            "conditions": conditions,
            "evidence": compact_evidence(evidence, only=linked),
            "verifier_feedback": [i.model_dump(include={"code", "message", "claim_id"}) for i in matter.verifier_feedback],
        }
        result = await self._call_model(prompts.DRAFTER, payload, prompts.DRAFT_SCHEMA, "draft")
        # The executor's draft is UNVERIFIED by construction; conditions come from the checklist, not the model.
        draft = Draft(
            revision=matter.revision,
            conclusion=Conclusion(answer=result["conclusion"]["answer"], summary=result["conclusion"]["summary"],
                                  evidence_ids=list(result["conclusion"]["evidence_ids"]),
                                  **_basis(result["conclusion"])),
            # Materiality is HABITA's rule, not the model's label: any "material" flag in the output is ignored.
            claims=[Claim(claim_id=f"K{n}", text=c["text"], evidence_ids=list(c["evidence_ids"]), material=True,
                          **_basis(c))
                    for n, c in enumerate(result["claims"], start=1)],
            conditions=[Condition(**c) for c in conditions],
            procedure=[ProcedureStep(step=p["step"], description=p["description"], evidence_ids=list(p["evidence_ids"]),
                                     **_basis(p))
                       for p in result["procedure"]],
            risks=[Risk(text=r["text"], evidence_ids=list(r["evidence_ids"]), **_basis(r)) for r in result["risks"]],
            next_actions=[NextAction(text=a["text"], evidence_ids=list(a["evidence_ids"]), **_basis(a))
                          for a in result["next_actions"]],
            model_id=self._model.model_id,
            created_at=datetime.now(UTC),
        )
        # Structured planning statements carry HABITA-derived text (quote, condition, determination), never the
        # model's wording (CX-1); general explanations get HABITA's frame; the verifier checks all of them.
        draft = render_draft(draft, evidence, matter)
        # Evidence-first: a general explanation the model left without its official passage gets it linked by
        # HABITA from this matter's admissible official text, when the match is strong and unambiguous (audited).
        chain = await tools.jurisdiction_chain()
        trusted = await self._official.trusted_ids(chain)
        return reconcile_citations(draft, evidence, matter, chain, trusted)

    async def _verify(self, matter: PermitMatter) -> None:
        if matter.state == MatterState.DRAFT_READY:
            await self._transition(matter, MatterState.VERIFYING)
        checklist = await self._repo.get_checklist(matter.matter_id)
        if matter.draft is None or checklist is None:
            await self._transition(matter, MatterState.INVESTIGATING)
            return
        tools = self._tools(matter)
        # The checklist is reconciled against evidence admissible *now* (a source retired since retrieval no
        # longer counts); the verifier gets the full history to re-check every citation and report exclusions.
        checklist.items = requirements.reconcile(checklist.intent, checklist.items, await tools.admissible_evidence())
        await self._repo.save_checklist(checklist)
        evidence = await self._repo.list_evidence(matter.matter_id)
        chain = await tools.jurisdiction_chain()
        report = await self._verifier.verify(matter, checklist.model_copy(deep=True), matter.draft, evidence, chain)
        if report.outcome == "VERIFIED":
            # Final gate (CX-2): reconcile against evidence admissible now, read the registry once (``pin``: every
            # applicable source's status and trust_version), re-run every rule on that read, and commit VERIFIED
            # atomically *only while that pin still holds*. If a source changed after the gate, nothing is written
            # and the gate re-runs on the new state; VERIFIED is never persisted from a stale read.
            reviewed = report
            for _ in range(COMMIT_ATTEMPTS):
                checklist.items = requirements.reconcile(checklist.intent, checklist.items, await tools.admissible_evidence())
                await self._repo.save_checklist(checklist)
                # C2: refresh the property if needed, then read the identity the commit will be bound to, before
                # the pin and the gate's own reads; any property write after this read makes the commit refuse.
                await self._properties.get(matter.property_id)
                identity = await self._properties.identity(matter.property_id)
                pin = await self._official.pin(chain)
                report = await self._verifier.final_gate(
                    reviewed, matter, checklist.model_copy(deep=True), matter.draft,
                    await self._repo.list_evidence(matter.matter_id), chain, pin)
                report = report.model_copy(update={"unresolved": [i.key for i in checklist.items if i.status != "satisfied"]})
                if report.outcome != "VERIFIED":
                    break
                if await self._commit_verified(matter, report, pin, identity):
                    return
                logger.info("Permit VERIFIED commit refused, sources or the property changed after the final gate: "
                            "matter=%s", matter.matter_id)
            else:
                raise TrustChangedError("Official sources or the property changed while this assessment was being "
                                        "verified. It can be resumed.")
        await self._repo.save_verification(report)
        matter.latest_verification_id = report.verification_id
        matter.unresolved_items = report.unresolved

        if report.outcome == "VERIFIED":
            matter.verifier_feedback = []
            await self._transition(matter, MatterState.VERIFIED)
        elif report.outcome == "NEEDS_INPUT":
            matter.missing_inputs = _user_questions(matter, checklist, [])
            if matter.missing_inputs:
                await self._transition(matter, MatterState.NEEDS_INPUT)
            else:
                await self._escalate(matter, "Verification found missing information that HABITA can't request.", checklist)
        elif report.outcome == "REJECTED":
            if matter.revision < MAX_REVISIONS and matter.rounds < MAX_ROUNDS:
                matter.revision += 1
                matter.verifier_feedback = report.issues
                await self._transition(matter, MatterState.INVESTIGATING)
            else:
                matter.escalation_reason = "The draft could not be verified against its evidence: " + "; ".join(
                    i.message for i in report.issues[:3])
                await self._transition(matter, MatterState.REJECTED)
        else:
            reasons = [i.message for i in report.issues if i.code in ("evidence_gap", "undetermined")] or [
                i.message for i in report.issues[:2]]
            await self._escalate(matter, " ".join(reasons) or "The available sources do not settle this question.", checklist)

    async def _commit_verified(self, matter: PermitMatter, report: VerificationReport, pin: TrustPin,
                               identity: PropertyIdentity | None) -> bool:
        """Persist the report and the VERIFIED transition as one atomic step bound to ``pin`` (see the repository's
        ``commit_verified``). The in-memory matter changes only if the commit happened."""
        now = datetime.now(UTC)
        committed = matter.model_copy(deep=True)
        committed.latest_verification_id = report.verification_id
        committed.unresolved_items = report.unresolved
        committed.verifier_feedback = []
        committed.state = MatterState.VERIFIED
        committed.updated_at = now
        committed.progress.append(ProgressEvent(state=MatterState.VERIFIED, label=LABELS[MatterState.VERIFIED], at=now))
        try:
            ok = await self._repo.commit_verified(committed, report, pin, self._official.repository, identity,
                                                  self._properties.repository)
        except StorageUnavailableError:
            # The outcome may be unknown (lost acknowledgement): read it back before treating it as a failure.
            if await self._adopt_if_committed(matter, report.verification_id):
                return True
            raise
        if not ok:
            return False
        for field in ("latest_verification_id", "unresolved_items", "verifier_feedback", "state", "updated_at", "progress"):
            setattr(matter, field, getattr(committed, field))
        return True

    async def _adopt_if_committed(self, matter: PermitMatter, verification_id: str | None = None) -> bool:
        """If the stored matter is VERIFIED (by ``verification_id``, when given), take it as this run's state."""
        stored = await self._repo.get_matter(matter.matter_id)
        if stored is None or stored.state != MatterState.VERIFIED or (
                verification_id is not None and stored.latest_verification_id != verification_id):
            return False
        for field in type(matter).model_fields:
            setattr(matter, field, getattr(stored, field))
        return True

    async def _escalate(self, matter: PermitMatter, reason: str, checklist: Checklist | None = None) -> None:
        matter.escalation_reason = reason
        if checklist is not None:
            matter.unresolved_items = [i.key for i in checklist.items if i.status != "satisfied"]
        await self._transition(matter, MatterState.ESCALATE)

    # --- helpers --------------------------------------------------------------------

    async def _call_model(self, system: str, payload: dict[str, Any], schema: dict[str, Any], name: str) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            result = await self._model.chat(
                [{"role": "system", "content": system},
                 {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}],
                response_schema=schema,
                schema_name=name,
            )
            parsed = json.loads(result.content or "")
            if not isinstance(parsed, dict):
                raise ValueError("structured output must be an object")
            return parsed

        return await call()

    def _tools(self, matter: PermitMatter, checklist: Checklist | None = None) -> PermitTools:
        return PermitTools(matter=matter, repository=self._repo, properties=self._properties, sources=self._sources,
                           official=self._official, retriever=self._retriever, planning=self._planning,
                           checklist={i.key: i for i in checklist.items} if checklist else {})

    async def _transition(self, matter: PermitMatter, state: MatterState) -> None:
        now = datetime.now(UTC)
        matter.state = state
        matter.updated_at = now
        matter.progress.append(ProgressEvent(state=state, label=LABELS[state], at=now))
        try:
            await self._repo.save_matter(matter)
        except MatterAlreadyVerified:
            # Only the atomic commit writes VERIFIED, and nothing overwrites it (e.g. a FAILED after an in-doubt
            # commit that did commit): the stored, coherent VERIFIED matter wins.
            await self._adopt_if_committed(matter)


def _user_questions(matter: PermitMatter, checklist: Checklist, requested: list[MissingInput]) -> list[MissingInput]:
    """Questions for required, user-owned items still unanswered: the only source of user questions.

    The model's phrasing (accepted through request_missing_information) is used when
    available; otherwise the canonical question.
    """
    phrased = {m.input_key: m for m in requested}
    questions = []
    for item in checklist.items:
        if item.owner == "USER" and item.required and item.status == "needs_input" and item.key not in matter.inputs:
            questions.append(phrased.get(item.key) or MissingInput(
                input_key=item.key, question=item.question, reason="Only you can provide this."))
    return questions
