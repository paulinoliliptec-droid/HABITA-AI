"""Permit Intelligence domain and API models (HR-002).

Workflow: GOAL → CHECKLIST → TOOLS → EVIDENCE → DRAFT (UNVERIFIED) → INDEPENDENT
VERIFICATION → FINAL STATE. Every persisted object here is plain data so the
workflow can stop at any state and resume later.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field, field_validator

from app.schemas.sources import SourceProvenance


class MatterState(StrEnum):
    PLANNING = "PLANNING"
    INVESTIGATING = "INVESTIGATING"
    NEEDS_INPUT = "NEEDS_INPUT"
    DRAFT_READY = "DRAFT_READY"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    ESCALATE = "ESCALATE"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


#: States in which a run stops: converged (VERIFIED, NEEDS_INPUT, ESCALATE, REJECTED) or FAILED (retryable).
STABLE_STATES = {
    MatterState.NEEDS_INPUT, MatterState.VERIFIED, MatterState.ESCALATE, MatterState.REJECTED, MatterState.FAILED,
}

Intent = Literal["unit_conversion", "general_overview", "out_of_scope"]

ChecklistArea = Literal[
    "current_use",
    "intended_use",
    "jurisdiction",
    "competent_authority",
    "planning_framework",
    "licensing_procedure",
    "restrictions",
    "required_documents",
    "missing_information",
    "evidence_needed",
]
#: open: no evidence yet (a gap); satisfied: evidence exists; needs_input: only the user can answer;
#: blocked_external: only an authority or official document can settle it (a condition, not a question).
ChecklistStatus = Literal["open", "satisfied", "needs_input", "blocked_external", "not_applicable"]
#: Who can supply the information an item needs.
Owner = Literal["USER", "SYSTEM_TOOL", "AUTHORITY", "DOCUMENT", "UNKNOWN"]


class ChecklistItem(BaseModel):
    #: Canonical machine ID from the requirement catalog (e.g. "current_licensed_use"). Never model-generated.
    key: str
    area: ChecklistArea
    question: str
    required: bool
    owner: Owner
    #: Computed by deterministic reconciliation against evidence, never set by the model.
    status: ChecklistStatus = "open"
    evidence_ids: list[str] = Field(default_factory=list)


class Checklist(BaseModel):
    matter_id: str
    intent: Intent
    intent_summary: str
    items: list[ChecklistItem]
    model_id: str
    created_at: datetime
    updated_at: datetime


SourceType = Literal[
    "property_record",
    "jurisdiction_record",
    "authority_record",
    "regulatory_source",
    "planning_context",
    "user_statement",
]
VerificationStatus = Literal["system_record", "curated_reference", "official_text", "user_declared"]


class Evidence(BaseModel):
    evidence_id: str  # "E1", "E2", …: stable within the matter; cited by claims
    matter_id: str
    source_type: SourceType
    source_title: str
    source_reference: str
    source_url: str | None = None
    jurisdiction_id: str
    authority_id: str | None = None
    retrieved_at: datetime
    claim_supported: str
    excerpt: str
    structured: dict[str, Any] = Field(default_factory=dict)
    confidence: Literal["high", "medium", "low"]
    #: system_record: HABITA's own resolved data. curated_reference: a reviewed summary of
    #: an authoritative source, not its live official text. official_text: a passage of a
    #: retrieved official document (snapshot-pinned). user_declared: stated by the user.
    verification_status: VerificationStatus
    #: Deduplication key: one evidence record per underlying fact.
    dedupe_key: str
    #: Registry source behind regulatory and planning evidence (HR-003); checked by the verifier.
    provenance: SourceProvenance | None = None


class MissingInput(BaseModel):
    #: The canonical checklist key this question answers.
    input_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,48}$")
    question: str
    reason: str
    required: bool = True
    owner: Literal["USER"] = "USER"


#: A statement's declared planning dependency (HR-003 CX-1), checked in code, never trusted:
#: - none: no planning content; must be grounded in its cited non-planning evidence;
#: - general_rule: a planning or regulatory rule, rendered by HABITA as a verbatim quote of cited evidence;
#: - general_planning_explanation: how planning works in general (model wording, framed by HABITA as general); it may
#:   cite only regulatory records and must not refer to this property or any particular place;
#: - user_declaration: the user's own answer, rendered verbatim and attributed ("You stated …, not verified"); user
#:   answers can support nothing else (never planning);
#: - authority_confirmation: defers the parcel's planning to the authority, rendered as HABITA's own condition;
#: - parcel_determination: rendered by HABITA from an admissible authoritative determination for this property.
PlanningBasis = Literal[
    "none", "general_rule", "general_planning_explanation", "authority_confirmation", "parcel_determination",
    "user_declaration"]


class _Statement(BaseModel):
    planning_basis: PlanningBasis = "none"
    #: general_rule only: the verbatim passage (from a cited record) that HABITA renders as the statement.
    quote: str | None = None
    #: The model's own wording, kept for audit when HABITA rendered the statement from a structured basis.
    model_text: str | None = None


class Claim(_Statement):
    claim_id: str
    text: str
    #: Set by HABITA, never by the model: every model-written claim is material and must cite evidence.
    material: bool = True
    evidence_ids: list[str]


class ProcedureStep(_Statement):
    step: str
    description: str
    evidence_ids: list[str] = Field(default_factory=list)


class Risk(_Statement):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


ConclusionAnswer = Literal["likely_possible", "conditional", "likely_not_possible", "undetermined"]


class Conclusion(_Statement):
    answer: ConclusionAnswer
    summary: str
    evidence_ids: list[str] = Field(default_factory=list)


class NextAction(_Statement):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class Condition(BaseModel):
    """Something only an authority or document can settle; derived from the checklist by code."""

    item_key: str
    text: str


class CitationLink(BaseModel):
    """Audit record of HABITA's claim-to-evidence reconciliation for one general planning explanation that the model
    left without admissible official text. Added by the system, never by the model; IDs only from this matter."""

    statement: str  # label: conclusion, K1, procedure 1, risk 1, next action 1
    outcome: Literal["linked", "ambiguous", "no_match"]
    evidence_id: str | None = None  # set only when linked
    score: int = 0  # shared planning concepts with the best passage
    coverage: float = 0.0  # share of the statement's planning concepts found in that passage
    matched: list[str] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)  # best-scoring passages (more than one = ambiguous)
    method: str = "concept-overlap-v1"
    added_by: Literal["system"] = "system"


class Draft(BaseModel):
    """The executor's result. Always UNVERIFIED: only the verifier can change a matter's outcome."""

    status: Literal["UNVERIFIED"] = "UNVERIFIED"
    revision: int
    conclusion: Conclusion
    claims: list[Claim]
    conditions: list[Condition]
    procedure: list[ProcedureStep]
    risks: list[Risk]
    next_actions: list[NextAction]
    model_id: str
    created_at: datetime
    #: Citations HABITA added or declined to add (see CitationLink); empty when nothing needed reconciling.
    citation_reconciliation: list[CitationLink] = Field(default_factory=list)


VerifierOutcome = Literal["VERIFIED", "NEEDS_INPUT", "ESCALATE", "REJECTED"]


class VerificationIssue(BaseModel):
    code: str
    message: str
    claim_id: str | None = None
    item_key: str | None = None
    evidence_id: str | None = None
    origin: Literal["rule", "model"]


class FollowUp(BaseModel):
    """A requirement the verifier suggests; recorded for review, never added to the active checklist."""

    area: ChecklistArea
    text: str


class ClaimAtom(BaseModel):
    """One atomic legal claim of a model statement and its deterministic verdict (MU-9)."""

    statement: str
    text: str
    kind: str
    bearer: str
    supported_by: list[str] = Field(default_factory=list)
    verdict: Literal["supported", "no_support_needed", "rejected"]
    #: False: a shadow verdict, recorded for measurement and not (yet) enforced.
    enforced: bool = True
    reason: str | None = None


class VerificationReport(BaseModel):
    verification_id: str
    matter_id: str
    draft_revision: int
    outcome: VerifierOutcome
    issues: list[VerificationIssue]
    checks: dict[str, bool]
    #: Checklist keys not satisfied at verification time (conditions and gaps).
    unresolved: list[str] = Field(default_factory=list)
    #: Records kept as history but not admissible at verification time (retired or untrusted source,
    #: foreign jurisdiction, another property's planning context): {"evidence_id", "reason"}.
    excluded_evidence: list[dict[str, str]] = Field(default_factory=list)
    suggested_follow_up: list[FollowUp] = Field(default_factory=list)
    model_review: dict[str, Any] | None = None
    model_id: str | None = None
    created_at: datetime
    #: The registry state the final gate decided on, {source_id: "status@trust_version"}; a VERIFIED report is
    #: committed only while every one of these is unchanged (HR-003 CX-2).
    trust_pin: dict[str, str] = Field(default_factory=dict)
    #: The verification protocol that produced the report; reports from before MU-9 carry none and read as
    #: ``statement-v1``.
    protocol: str = "statement-v1"
    #: Set by ``raise-protocol-floor`` on a VERIFIED report whose protocol the floor no longer admits: history only,
    #: the matter must be re-verified.
    superseded_protocol: str | None = None
    #: Every atomic legal claim of the draft and its verdict, recomputed by the final gate.
    claim_atoms: list[ClaimAtom] = Field(default_factory=list)


class ProgressEvent(BaseModel):
    state: MatterState
    label: str
    at: datetime


class MatterError(BaseModel):
    code: str
    message: str
    failed_state: MatterState


class PermitMatter(BaseModel):
    matter_id: str
    property_id: str
    question: str
    state: MatterState
    intent: Intent | None = None
    jurisdiction_id: str
    authority_id: str | None = None
    inputs: dict[str, str] = Field(default_factory=dict)
    missing_inputs: list[MissingInput] = Field(default_factory=list)
    draft: Draft | None = None
    revision: int = 0
    #: Investigation/draft passes so far; bounded so a matter always converges.
    rounds: int = 0
    #: The model-driven tool loop runs once per matter; resumes reuse its evidence.
    tool_loop_done: bool = False
    unresolved_items: list[str] = Field(default_factory=list)
    verifier_feedback: list[VerificationIssue] = Field(default_factory=list)
    escalation_reason: str | None = None
    progress: list[ProgressEvent] = Field(default_factory=list)
    error: MatterError | None = None
    latest_verification_id: str | None = None
    #: Set by ``raise-protocol-floor`` when this VERIFIED matter's report came from a protocol the floor no longer
    #: admits (MU-9): the matter must be re-verified and is not presented as currently verified.
    superseded_protocol: str | None = None
    created_at: datetime
    updated_at: datetime

    # What the outcome means, stated in the API itself. VERIFIED is about HABITA's
    # assessment passing its evidence and verification checks; it is never a permit.
    @computed_field
    @property
    def assessment_status(self) -> str:
        if self.state == MatterState.VERIFIED and self.superseded_protocol:
            return "superseded_assessment"  # MU-9: verified by a protocol no longer admitted; re-verify
        return {
            MatterState.VERIFIED: "verified_assessment",
            MatterState.REJECTED: "assessment_not_verified",
            MatterState.ESCALATE: "needs_professional_review",
            MatterState.NEEDS_INPUT: "awaiting_user_information",
        }.get(self.state, "in_progress")

    @computed_field
    @property
    def authority_approval(self) -> Literal["not_obtained"]:
        """HABITA never obtains or represents an authority's approval."""
        return "not_obtained"

    @computed_field
    @property
    def outcome_note(self) -> str | None:
        if self.state != MatterState.VERIFIED:
            return None
        if self.superseded_protocol:
            return ("Superseded assessment: it was verified under an earlier verification protocol "
                    f"({self.superseded_protocol}) that HABITA no longer accepts. It must be verified again before it "
                    "is relied on. It is not a permit and not an approval by the competent authority.")
        note = ("Verified assessment: HABITA's analysis passed its evidence and verification checks. "
                "It is not a permit and not an approval by the competent authority.")
        if self.draft and self.draft.conditions:
            note += " Conditions remain to be confirmed with the authority before proceeding."
        return note


# --- API requests ---------------------------------------------------------------------


class CreateMatterRequest(BaseModel):
    property_id: str = Field(pattern=r"^prp_[0-9a-f]{16}$")
    question: str = Field(min_length=8, max_length=500)

    @field_validator("question")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class SupplyInputsRequest(BaseModel):
    inputs: dict[str, str] = Field(min_length=1, max_length=20)

    @field_validator("inputs")
    @classmethod
    def _non_empty(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned = {k.strip(): v.strip() for k, v in value.items()}
        if any(not v or len(v) > 2000 for v in cleaned.values()):
            raise ValueError("Each answer must be between 1 and 2000 characters.")
        return cleaned


class CreateMatterResponse(BaseModel):
    matter: PermitMatter
    #: Capability for this matter, returned only here. Send it as "Authorization: Bearer <token>".
    access_token: str
    #: "pt" or "en" when the question's language was recognised, for the UI to follow it; never stored.
    detected_language: str | None = None


class MatterTranslation(BaseModel):
    """A labelled reading view of a matter's texts. What was verified stays the English text in the matter."""

    lang: str
    available: bool
    #: True only when the matter presents a current verified assessment.
    verified: bool
    kept_original: int
    note: str | None
    texts: dict[str, str]  # English text → text to show
