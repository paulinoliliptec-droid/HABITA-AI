"""PlanningContextResolver: which planning classification applies at a coordinate.

Zoning is a fact only an official source can state. A resolver returns ``resolved``
only when a *trusted*, machine-readable layer connector returns exactly one zoning
feature at a precisely located point that is not near a class boundary. In every
other case it returns ``requires_manual_confirmation`` with the exact official
documents to check, why automatic classification wasn't possible, the competent
authority and when the sources were verified. The model never supplies zoning.

``LayerConnector`` is the seam for future WMS / WFS / API connectors; Cascais ships
without one because no official machine-readable zoning service has been verified.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from app.schemas.property import ResolvedProperty
from app.schemas.sources import (
    MANUAL_REASON_TEXT,
    AuthorityRef,
    DocumentToConsult,
    ManualReason,
    OfficialSource,
    PlanningConstraint,
    PlanningContext,
    PlanningInstrument,
    ZoningClassification,
)
from app.services.sources.registry import OfficialSourceRegistry

PRECISE = {"rooftop", "interpolated"}


@dataclass(frozen=True)
class LayerFeature:
    classification: ZoningClassification
    feature_ref: str


@dataclass(frozen=True)
class LayerQueryResult:
    features: list[LayerFeature]
    #: Distance from the point to the nearest class boundary, if the service can tell.
    boundary_distance_m: float | None
    constraints: list[PlanningConstraint] = field(default_factory=list)
    retrieved_at: datetime | None = None


class LayerConnector(Protocol):
    #: Registry source that publishes the layer; it must be trusted to be used.
    source_id: str

    async def query_point(self, lat: float, lng: float) -> LayerQueryResult: ...


class PlanningContextResolver(Protocol):
    jurisdiction_id: str
    name: str
    version: int

    async def resolve(self, prop: ResolvedProperty) -> PlanningContext: ...


def decide(
    result: LayerQueryResult | None, precision: str, tolerance_m: float
) -> tuple[list[ManualReason], LayerFeature | None]:
    """The only path to ``resolved``. Returns the reasons it can't be resolved (empty if it can)."""
    if result is None:
        return ["no_machine_readable_layer"], None
    reasons: list[ManualReason] = []
    if precision not in PRECISE:
        reasons.append("low_geocode_precision")
    if not result.features:
        reasons.append("no_feature_at_point")
    elif len(result.features) > 1:
        # CX-5: exactly one feature, not one class: two overlapping features (even of the same class) leave the
        # reference ambiguous, so the first one is never picked as the determination.
        reasons.append("multiple_features")
    distance = result.boundary_distance_m
    if distance is None or not math.isfinite(distance) or distance < 0:
        reasons.append("boundary_distance_unknown")  # CX-5: NaN, ±Infinity or negative is not a distance
    elif distance < tolerance_m:
        reasons.append("near_class_boundary")
    return reasons, (result.features[0] if not reasons else None)


@dataclass(frozen=True)
class ManualDocument:
    source_id: str
    reason: str


class OfficialPlanningResolver:
    """Generic resolver for one jurisdiction's planning instrument, configured per jurisdiction."""

    version = 1

    def __init__(
        self,
        *,
        jurisdiction_id: str,
        name: str,
        instrument_source_id: str,
        registry: OfficialSourceRegistry,
        documents: Sequence[ManualDocument],
        connector: LayerConnector | None = None,
        tolerance_m: float = 15.0,
    ) -> None:
        self.jurisdiction_id = jurisdiction_id
        self.name = name
        self._instrument_id = instrument_source_id
        self._registry = registry
        self._documents = tuple(documents)
        self._connector = connector
        self._tolerance = tolerance_m

    async def resolve(self, prop: ResolvedProperty) -> PlanningContext:
        chain = [lvl.id for lvl in prop.jurisdiction.levels]
        trusted = {s.source_id: s for s in await self._registry.trusted(chain)}
        instrument = trusted.get(self._instrument_id)

        result: LayerQueryResult | None = None
        pre_reasons: list[ManualReason] = []
        if self._connector is not None:
            if self._connector.source_id not in trusted:
                pre_reasons.append("layer_source_not_trusted")
            else:
                try:
                    result = await self._connector.query_point(prop.coordinates.lat, prop.coordinates.lng)
                except Exception:
                    pre_reasons.append("layer_query_failed")
        reasons, feature = decide(result, prop.precision, self._tolerance)
        if pre_reasons:
            reasons, feature = pre_reasons + [r for r in reasons if r != "no_machine_readable_layer"], None
        if prop.precision not in PRECISE and "low_geocode_precision" not in reasons:
            reasons.append("low_geocode_precision")
            feature = None
        if instrument is None:
            # Without a trusted instrument there is nothing authoritative to classify against.
            reasons, feature = list(dict.fromkeys(["no_machine_readable_layer", *reasons])), None

        authority = prop.jurisdiction.local_authority
        documents = [
            DocumentToConsult(source_id=s.source_id, title=s.title, designation=s.designation,
                              official_url=s.official_url, reason=d.reason)
            for d in self._documents if (s := trusted.get(d.source_id))
        ]
        consulted = [s for s in trusted.values() if s.source_id == self._instrument_id or s.part_of == self._instrument_id]
        if self._connector is not None and self._connector.source_id in trusted:
            consulted.append(trusted[self._connector.source_id])
        snapshot_at = await self._snapshot_time(instrument)

        if feature is not None and result is not None:
            status, guidance = "resolved", (
                f"Planning classification from the official layer: {feature.classification.label}. "
                "This is planning context, not an approval; the competent authority decides."
            )
        else:
            status = "requires_manual_confirmation"
            instrument_name = instrument.title.split(" — ")[0] if instrument else "the municipal plan"
            guidance = (
                f"Planning classification requires confirmation against the official {instrument_name} map(s). "
                + " ".join(MANUAL_REASON_TEXT[r] for r in reasons)
                + (f" Check the documents listed below or confirm with {authority.name}." if authority else "")
            )
        return PlanningContext(
            property_id=prop.property_id,
            jurisdiction_id=self.jurisdiction_id,
            status=status,
            instrument=PlanningInstrument(
                source_id=instrument.source_id, title=instrument.title, version=instrument.version,
                effective_date=instrument.effective_date, official_url=instrument.official_url,
            ) if instrument else None,
            classification=feature.classification if feature else None,
            constraints=result.constraints if (result and feature) else [],
            coordinates=prop.coordinates,
            precision=prop.precision,
            tolerance_m=self._tolerance,
            reasons=reasons if status != "resolved" else [],
            documents_to_consult=documents if status != "resolved" else [],
            competent_authority=AuthorityRef(id=authority.id, name=authority.name) if authority else None,
            guidance=guidance,
            sources_consulted=sorted(s.source_id for s in consulted),
            sources_verified_on=max((s.provenance.verified_on for s in consulted if s.provenance.verified_on), default=None),
            source_retrieved_at=(result.retrieved_at if feature and result else None) or snapshot_at,
            raw_reference=feature.feature_ref if feature else None,
            resolver=self.name,
            resolver_version=self.version,
            resolved_at=datetime.now(UTC),
        )

    async def _snapshot_time(self, instrument: OfficialSource | None) -> datetime | None:
        if instrument is None or not instrument.latest_snapshot_id:
            return None
        snapshot = await self._registry.repository.get_snapshot(instrument.latest_snapshot_id)
        return snapshot.retrieved_at if snapshot else None


class PlanningContextService:
    """Picks the most specific resolver along the property's jurisdiction chain."""

    def __init__(self, resolvers: Sequence[PlanningContextResolver]) -> None:
        self._resolvers = {r.jurisdiction_id: r for r in resolvers}

    async def resolve(self, prop: ResolvedProperty) -> PlanningContext:
        for level in reversed(prop.jurisdiction.levels):
            resolver = self._resolvers.get(level.id)
            if resolver is not None:
                return await resolver.resolve(prop)
        return PlanningContext(
            property_id=prop.property_id, jurisdiction_id=prop.jurisdiction.id, status="not_supported",
            coordinates=prop.coordinates, precision=prop.precision,
            guidance="HABITA does not model planning instruments for this jurisdiction yet; confirm the applicable "
            "plan with the local planning authority.",
            resolver="none", resolver_version=0, resolved_at=datetime.now(UTC),
        )
