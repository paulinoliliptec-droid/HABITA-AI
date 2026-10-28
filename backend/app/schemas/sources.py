"""Official sources, snapshots, regulatory passages and planning context (HR-003).

LOCATION (Google) → JURISDICTION (HABITA) → OFFICIAL SOURCE REGISTRY → SNAPSHOTS →
PASSAGES / PLANNING CONTEXT → EVIDENCE. Google is never a legal or zoning authority;
only ``trusted`` registry sources can produce evidence the Permit agent may cite.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.property import Coordinates, LocationPrecision

Topic = Literal[
    "licensing_procedure",
    "change_of_use",
    "unit_division",
    "horizontal_property",
    "habitability",
    "land_use_planning",
    "competent_authority",
]

OfficialSourceType = Literal[
    "legislation",
    "municipal_regulation",
    "planning_instrument",
    "planning_map",
    "gis_service",
    "official_html",
    "official_pdf",
    "official_api",
    "procedure_page",
]
#: candidate: discovered or proposed, unchecked. validated: passed the automatic checks.
#: trusted: promoted by an operator; the only status that can produce evidence. retired: withdrawn.
SourceStatus = Literal["candidate", "validated", "trusted", "retired"]
#: How HABITA obtains the content. "curated" = a reviewed summary kept in code (no fetch);
#: "manual" = a document a person must consult (e.g. a PDF map that isn't machine-interpretable).
RetrievalMethod = Literal["http_pdf", "http_html", "wms_getfeatureinfo", "wfs", "curated", "manual"]
AuthorityClass = Literal["primary_law", "municipal_instrument", "official_dataset", "official_guidance"]


class SourceVerification(BaseModel):
    added_by: Literal["curated", "discovery"]
    verified_on: date | None = None
    verified_by: str | None = None
    notes: str = ""


class StatusChange(BaseModel):
    status: SourceStatus
    operator: str
    reason: str
    at: datetime


class OfficialSource(BaseModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,80}$")
    jurisdiction_id: str
    authority_id: str | None = None
    title: str
    source_type: OfficialSourceType
    #: Only verified official URLs; None when no stable official URL was verified.
    official_url: str | None = None
    publisher: str
    geographic_scope: str
    regulatory_scope: list[Topic] = Field(default_factory=list)
    effective_date: date | None = None
    version: str | None = None
    retrieval_method: RetrievalMethod
    machine_readable: bool
    status: SourceStatus
    authority_class: AuthorityClass
    provenance: SourceVerification
    #: For parts of a larger instrument (e.g. a PDM map): the instrument's source_id.
    part_of: str | None = None
    #: Official designation inside the instrument, e.g. "Planta 01-02".
    designation: str | None = None
    latest_snapshot_id: str | None = None
    status_history: list[StatusChange] = Field(default_factory=list)
    #: Incremented atomically with every status change (operator lifecycle). A VERIFIED commit is bound to the
    #: (status, trust_version) of every applicable source the final gate read (HR-003 CX-2).
    trust_version: int = 0


class SourceSnapshot(BaseModel):
    snapshot_id: str
    source_id: str
    retrieved_at: datetime
    requested_url: str
    final_url: str
    http_status: int
    content_type: str
    bytes: int
    sha256: str
    #: Version hint read from the document itself (e.g. the PDF's modification date).
    version_detected: str | None = None
    pages: int = 0
    text_extracted: bool = False
    chunk_count: int = 0


class PassageLocator(BaseModel):
    page: int
    article: str | None = None
    heading: str | None = None
    part: int | None = None

    def label(self) -> str:
        bits = [self.article, self.heading]
        text = " — ".join(b for b in bits if b)
        where = f"p. {self.page}" + (f", part {self.part}" if self.part else "")
        return f"{text} ({where})" if text else where


class RegulatoryChunk(BaseModel):
    chunk_id: str
    source_id: str
    snapshot_id: str
    jurisdiction_id: str
    locator: PassageLocator
    text: str


class SourceProvenance(BaseModel):
    """Where a piece of evidence comes from, checked against the registry by the verifier."""

    source_id: str
    basis: Literal["official_text", "curated_reference", "planning_context"]
    trust_status: SourceStatus
    authority_class: AuthorityClass | None = None
    official_url: str | None = None
    version: str | None = None
    locator: str | None = None
    snapshot_id: str | None = None
    sha256: str | None = None
    retrieved_at: datetime | None = None


# --- planning context ---------------------------------------------------------------

PlanningStatus = Literal["resolved", "partial", "requires_manual_confirmation", "not_supported"]
ManualReason = Literal[
    "no_machine_readable_layer",
    "layer_source_not_trusted",
    "low_geocode_precision",
    "no_feature_at_point",
    "multiple_features",
    "near_class_boundary",
    "boundary_distance_unknown",
    "layer_query_failed",
]

MANUAL_REASON_TEXT: dict[str, str] = {
    "no_machine_readable_layer": "HABITA has not yet verified an official machine-readable service that can "
    "classify this coordinate against the plan's zoning layers.",
    "layer_source_not_trusted": "The zoning layer's source has not been validated and trusted.",
    "low_geocode_precision": "The property's location is not precise enough to classify the parcel.",
    "no_feature_at_point": "The official layer returned no zoning feature at this point.",
    "multiple_features": "The official layer returned more than one zoning class at this point.",
    "near_class_boundary": "The point lies close to a boundary between zoning classes.",
    "boundary_distance_unknown": "The distance to the nearest zoning boundary could not be determined.",
    "layer_query_failed": "The official zoning layer could not be queried.",
}


class PlanningInstrument(BaseModel):
    source_id: str
    title: str
    version: str | None = None
    effective_date: date | None = None
    official_url: str | None = None


class ZoningClassification(BaseModel):
    land_class: str | None = None  # e.g. "Solo urbano"
    category: str | None = None  # e.g. "Espaços centrais"
    subcategory: str | None = None
    code: str | None = None
    label: str


class PlanningConstraint(BaseModel):
    layer: str
    value: str
    source_id: str


class DocumentToConsult(BaseModel):
    source_id: str
    title: str
    designation: str | None = None
    official_url: str | None = None
    reason: str


class AuthorityRef(BaseModel):
    id: str
    name: str


class PlanningContext(BaseModel):
    property_id: str
    jurisdiction_id: str
    status: PlanningStatus
    instrument: PlanningInstrument | None = None
    classification: ZoningClassification | None = None
    constraints: list[PlanningConstraint] = Field(default_factory=list)
    coordinates: Coordinates
    precision: LocationPrecision
    tolerance_m: float | None = None
    reasons: list[ManualReason] = Field(default_factory=list)
    documents_to_consult: list[DocumentToConsult] = Field(default_factory=list)
    competent_authority: AuthorityRef | None = None
    #: User-facing summary of the status; HABITA-written, never model-written.
    guidance: str
    sources_consulted: list[str] = Field(default_factory=list)
    #: When the official sources behind this context were last verified / retrieved.
    sources_verified_on: date | None = None
    source_retrieved_at: datetime | None = None
    #: For a resolved context: the raw reference returned by the connector (layer, feature id).
    raw_reference: str | None = None
    resolver: str
    resolver_version: int
    resolved_at: datetime


class OfficialSourceOut(BaseModel):
    source_id: str
    jurisdiction_id: str
    title: str
    source_type: OfficialSourceType
    publisher: str
    official_url: str | None
    version: str | None
    designation: str | None
    retrieval_method: RetrievalMethod
    machine_readable: bool
    status: SourceStatus
    verified_on: date | None
    snapshot_retrieved_at: datetime | None = None


class PlanningContextResponse(BaseModel):
    planning_context: PlanningContext
    sources: list[OfficialSourceOut]
