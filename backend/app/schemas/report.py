"""The shared report model (HR-004 map post-its, HR-006 PDF report).

One structure, built only from what HABITA already stored (property, planning context, official sources and, for an
assessment, the matter's draft, evidence and latest verification report). Nothing here is new legal content."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

#: The only status words the map and the PDF use.
ReportStatus = Literal["VERIFIED", "REJECTED", "PENDING_CONFIRMATION"]


class ReportProperty(BaseModel):
    property_id: str
    address: str
    lat: float
    lng: float
    precision: str
    jurisdiction_id: str
    jurisdiction: list[str]  # "Label: Name", country first
    authority: str | None = None


class ReportDocument(BaseModel):
    title: str
    designation: str | None = None
    url: str | None = None
    reason: str


class ReportPlanning(BaseModel):
    status: str  # the planning context's own status
    #: True only when a trusted machine-readable connector resolved the classification.
    verified_zoning: bool
    classification: str | None = None  # set only when verified_zoning
    instrument: str | None = None
    instrument_version: str | None = None
    reasons: list[str] = Field(default_factory=list)
    documents_to_consult: list[ReportDocument] = Field(default_factory=list)
    guidance: str


class ReportSource(BaseModel):
    source_id: str
    title: str
    publisher: str | None = None
    url: str | None = None
    version: str | None = None
    status: str
    verified_on: date | None = None


class ReportEvidence(BaseModel):
    evidence_id: str
    title: str
    reference: str
    url: str | None = None
    source_type: str
    verification_status: str
    retrieved_at: datetime
    excerpt: str
    source_id: str | None = None
    trust_status: str | None = None
    version: str | None = None
    snapshot_id: str | None = None
    sha256: str | None = None
    locator: str | None = None


class ReportStatement(BaseModel):
    section: Literal["finding", "procedure", "risk", "next_action"]
    label: str  # K1, procedure 1, risk 1 …
    text: str
    step: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ReportVerification(BaseModel):
    verification_id: str
    outcome: str
    draft_revision: int
    created_at: datetime
    protocol: str
    trust_pin: dict[str, str] = Field(default_factory=dict)
    #: False: an earlier or superseded record, shown as history, never as the assessment's status.
    current: bool


class ReportAssessment(BaseModel):
    matter_id: str
    question: str
    intent: str | None = None
    state: str
    status: ReportStatus
    status_reason: str
    #: False: the draft's content has not passed verification and is shown as "not verified".
    content_verified: bool
    conclusion_answer: str | None = None
    conclusion_summary: str | None = None
    conclusion_evidence_ids: list[str] = Field(default_factory=list)
    statements: list[ReportStatement] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)  # why it was rejected
    verification: ReportVerification | None = None
    evidence: list[ReportEvidence] = Field(default_factory=list)


class ReportTranslation(BaseModel):
    available: bool
    kept_original: int
    note: str | None


ProfileKind = Literal["official", "observation", "declaration"]


class ProfileItem(BaseModel):
    """HR-008: one thing known about the property, with who said it. ``value`` None: not confirmed."""

    key: str
    label: str
    value: str | None = None
    kind: ProfileKind
    #: Who said it, or where to confirm it when the value is None.
    origin: str
    as_of: date | None = None
    precision: str | None = None
    url: str | None = None
    #: Sources disagree on this item; every side is in the profile.
    conflict: bool = False


class PermitReport(BaseModel):
    generated_at: datetime
    property: ReportProperty
    planning: ReportPlanning
    sources: list[ReportSource] = Field(default_factory=list)
    assessment: ReportAssessment | None = None
    profile: list[ProfileItem] = Field(default_factory=list)
    #: What only the authority (or the user) can still settle.
    pending: list[str] = Field(default_factory=list)
    #: Set when any part comes from labelled demonstration data.
    demo: bool = False
    disclaimer: str
    #: The language this report is shown in. Statuses stay the fields above, whatever the language.
    language: Literal["en", "pt"] = "en"
    translation: ReportTranslation | None = None


class VoiceScript(BaseModel):
    """HR-007: the sentences spoken from a report. ``audio``: synthesised speech exists for this language."""

    version: str
    lines: list[str]
    audio: bool
