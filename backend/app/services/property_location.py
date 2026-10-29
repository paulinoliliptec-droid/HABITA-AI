"""Property → location → jurisdiction."""

from contextlib import nullcontext
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from app.core.rate_limit import ResolutionLimiter
from app.db.property_repository import PropertyIdentity, PropertyRepository
from app.integrations.maps.geocoding import GeocodedLocation, GeocodingClient
from app.schemas.property import (
    AuthorityOut,
    Coordinates,
    GeocodeLookup,
    JurisdictionLevelOut,
    JurisdictionOut,
    LocationPrecision,
    PropertySnapshot,
    Provenance,
    ResolutionRequestRecord,
    ResolvedProperty,
    ResolveLocationResponse,
)
from app.services.jurisdiction import Jurisdiction, JurisdictionResolver
from app.services.jurisdiction.base import slug

# Only premise-level results get an address key; a street or area match must never
# attach to someone else's property.
_PREMISE_PRECISION = {"ROOFTOP", "RANGE_INTERPOLATED"}

_PRECISION: dict[str, LocationPrecision] = {
    "ROOFTOP": "rooftop",
    "RANGE_INTERPOLATED": "interpolated",
    "GEOMETRIC_CENTER": "area_center",
    "APPROXIMATE": "approximate",
}


class PropertyLocationService:
    def __init__(
        self,
        geocoder: GeocodingClient,
        resolver: JurisdictionResolver,
        repository: PropertyRepository,
        default_language: str,
        snapshot_ttl: timedelta,
        limiter: ResolutionLimiter | None = None,
    ) -> None:
        self._geocoder = geocoder
        self._resolver = resolver
        self._repository = repository
        self._default_language = default_language
        self._snapshot_ttl = snapshot_ttl
        self._limiter = limiter

    async def resolve(self, *, address: str | None, place_id: str | None) -> ResolveLocationResponse:
        resolution = await self._resolve_snapshot(address=address, place_id=place_id)
        prop = await self._repository.save(resolution.snapshot, resolution.aliases, address_key=resolution.address_key)
        return ResolveLocationResponse(**prop.model_dump(), partial_match=resolution.partial_match)

    async def get(self, property_id: str) -> ResolvedProperty | None:
        stored = await self._repository.get(property_id)
        if stored is None:
            return None
        if stored.snapshot is not None and stored.snapshot.expires_at > datetime.now(UTC):
            return stored.snapshot
        # Expired provider content, or a document from an older schema: re-resolve from the
        # stored place ID (which may be kept) into the same property.
        resolution = await self._resolve_snapshot(address=None, place_id=stored.place_id)
        return await self._repository.save(
            resolution.snapshot, resolution.aliases, address_key=resolution.address_key, property_id=stored.property_id
        )

    async def identity(self, property_id: str) -> PropertyIdentity | None:
        """The stored identity a VERIFIED commit is bound to (HR-003 MU-9 C2)."""
        return await self._repository.identity(property_id)

    @property
    def repository(self) -> PropertyRepository:
        return self._repository

    async def purge_expired(self) -> int:
        return await self._repository.purge_expired()

    async def _resolve_snapshot(self, *, address: str | None, place_id: str | None) -> "_Resolution":
        async with self._limiter.admit() if self._limiter else nullcontext():
            lookups: list[GeocodeLookup] = []
            if place_id:
                first = await self._geocoder.geocode(place_id=place_id, language=self._default_language)
            else:
                first = await self._geocoder.geocode(address=address, language=self._default_language)
            lookups.append(_lookup(first, "place_id" if place_id else "address"))

            location = first
            adapter = self._resolver.adapter_for(first.country_code)
            if adapter.official_language and adapter.official_language != first.language:
                # Re-read the same place in the official language so names and IDs are canonical.
                location = await self._geocoder.geocode(place_id=first.place_id, language=adapter.official_language)
                lookups.append(_lookup(location, "place_id"))

        now = datetime.now(UTC)
        jurisdiction = adapter.resolve(location)
        snapshot = PropertySnapshot(
            formatted_address=location.formatted_address,
            coordinates=Coordinates(lat=location.lat, lng=location.lng),
            precision=_PRECISION.get(location.location_type, "approximate"),
            place_id=location.place_id,
            jurisdiction=_jurisdiction_out(jurisdiction),
            provenance=Provenance(
                request=ResolutionRequestRecord(address=address, place_id=place_id),
                lookups=lookups,
                adapter=adapter.key,
                adapter_version=adapter.version,
            ),
            resolved_at=now,
            expires_at=now + self._snapshot_ttl,
        )
        return _Resolution(
            snapshot=snapshot,
            aliases={lookup.place_id for lookup in lookups} | ({place_id} if place_id else set()),
            address_key=address_key(location, jurisdiction),
            # Match quality belongs to the user's request: an exact re-read by ID can't clear it.
            partial_match=any(lookup.partial_match for lookup in lookups),
        )


@dataclass(frozen=True)
class _Resolution:
    snapshot: PropertySnapshot
    aliases: set[str]
    address_key: str | None
    partial_match: bool


def address_key(location: GeocodedLocation, jurisdiction: Jurisdiction) -> str | None:
    """Deterministic premise key: jurisdiction + route + street number + unit, or None.

    Built from the official-language components (the same lookup that produced the
    jurisdiction), so the same premise yields the same key whichever entry path found it.
    """
    route = location.long_name("route")
    number = location.long_name("street_number")
    if not (route and number) or location.location_type not in _PREMISE_PRECISION or not jurisdiction.levels:
        return None
    unit = location.long_name("subpremise") or ""
    return "|".join((jurisdiction.id, slug(route), slug(number), slug(unit)))


def _lookup(location: GeocodedLocation, by: str) -> GeocodeLookup:
    return GeocodeLookup(by=by, language=location.language, place_id=location.place_id, partial_match=location.partial_match)


def _jurisdiction_out(j: Jurisdiction) -> JurisdictionOut:
    def name(level_type: str) -> str | None:
        level = j.level(level_type)  # type: ignore[arg-type]
        return level.name if level else None

    return JurisdictionOut(
        id=j.id,
        country_code=j.country_code,
        levels=[JurisdictionLevelOut(**asdict(level)) for level in j.levels],
        local_authority=AuthorityOut(**asdict(j.local_authority)) if j.local_authority else None,
        coverage=j.coverage,
        source="google_maps",
        country=name("country") or "Unknown",
        region=name("region"),
        municipality=name("municipality"),
        city=j.locality,
    )
