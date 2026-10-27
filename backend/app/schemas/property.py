from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# How exactly the geocoder pinned the point, mapped from Google's location_type.
LocationPrecision = Literal["rooftop", "interpolated", "area_center", "approximate"]


class ResolveLocationRequest(BaseModel):
    address: str | None = Field(default=None, min_length=3, max_length=300)
    # A Google place ID, e.g. from Places Autocomplete. Takes precedence over address.
    place_id: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="before")
    @classmethod
    def _strip(cls, data: object) -> object:
        if isinstance(data, dict):
            return {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}
        return data

    @model_validator(mode="after")
    def _require_one(self) -> "ResolveLocationRequest":
        if not self.address and not self.place_id:
            raise ValueError("Provide an address or a place_id.")
        return self


class Coordinates(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)


class JurisdictionLevelOut(BaseModel):
    type: Literal["country", "region", "subregion", "municipality", "subdivision", "overlay"]
    id: str
    name: str
    label: str


class SourceRefOut(BaseModel):
    title: str
    reference: str | None = None
    url: str | None = None


class AuthorityOut(BaseModel):
    id: str
    name: str
    kind: str
    jurisdiction_id: str
    competence: str
    sources: list[SourceRefOut]


class JurisdictionOut(BaseModel):
    """Agent-facing: ``id``, ``levels`` and ``local_authority``. The flat name fields are a display summary."""

    id: str
    country_code: str
    levels: list[JurisdictionLevelOut]
    local_authority: AuthorityOut | None
    coverage: Literal["modelled", "unmodelled"]
    source: Literal["google_maps"] = "google_maps"
    # Display summary derived from levels/locality.
    country: str
    region: str | None
    municipality: str | None
    city: str | None


class GeocodeLookup(BaseModel):
    by: Literal["address", "place_id"]
    language: str
    place_id: str
    partial_match: bool


class ResolutionRequestRecord(BaseModel):
    """The input as received, so a resolution can be reproduced and audited."""

    address: str | None = None
    place_id: str | None = None


# How a resolution was attached to its property: a fresh property, a known place-ID
# alias, the deterministic address match, or a refresh of a known property ID.
IdentityMatch = Literal["new", "alias", "address", "refresh"]


class Provenance(BaseModel):
    """How the *current snapshot* was produced (the latest resolution, not every request)."""

    provider: Literal["google_maps_geocoding"] = "google_maps_geocoding"
    request: ResolutionRequestRecord
    lookups: list[GeocodeLookup]
    adapter: str
    adapter_version: int
    identity: IdentityMatch | None = None


class PropertySnapshot(BaseModel):
    """One resolution of a location, before it is attached to a HABITA property identity."""

    formatted_address: str
    coordinates: Coordinates
    precision: LocationPrecision
    # Primary provider ID for this snapshot. A property may have several aliases (stored, not exposed).
    place_id: str
    jurisdiction: JurisdictionOut
    provenance: Provenance
    resolved_at: datetime
    # Provider content is refreshed from the place ID after this time.
    expires_at: datetime


class ResolvedProperty(PropertySnapshot):
    property_id: str


class ResolveLocationResponse(ResolvedProperty):
    # Match quality of *this* request (any lookup partial ⇒ partial). Request-scoped,
    # so it is returned to the caller but never stored as a property attribute.
    partial_match: bool
