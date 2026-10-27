"""Server-side client for the Google Geocoding API.

Uses the server key (GOOGLE_MAPS_API_KEY). The key travels as a query
parameter, so request URLs must never be logged: see ``app.main`` which keeps
the ``httpx`` logger at WARNING, and the error paths below which log only
status values.
"""

import asyncio
import logging
import math
from dataclasses import dataclass

import httpx

from app.core.errors import AddressNotFoundError, ServiceNotConfiguredError, UpstreamServiceError

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_RETRYABLE_STATUSES = {"UNKNOWN_ERROR"}
_MAX_ATTEMPTS = 2
_UNAVAILABLE = "The address service is temporarily unavailable. Please try again."


@dataclass(frozen=True)
class AddressComponent:
    long_name: str
    short_name: str
    types: tuple[str, ...]


@dataclass(frozen=True)
class GeocodedLocation:
    place_id: str
    formatted_address: str
    lat: float
    lng: float
    location_type: str
    partial_match: bool
    components: tuple[AddressComponent, ...]
    language: str

    def component(self, component_type: str) -> AddressComponent | None:
        return next((c for c in self.components if component_type in c.types), None)

    def long_name(self, component_type: str) -> str | None:
        comp = self.component(component_type)
        return comp.long_name if comp else None

    @property
    def country_code(self) -> str | None:
        comp = self.component("country")
        return comp.short_name.upper() if comp else None


class GeocodingClient:
    def __init__(self, http: httpx.AsyncClient, api_key: str | None) -> None:
        self._http = http
        self._api_key = api_key

    async def geocode(
        self,
        *,
        language: str,
        address: str | None = None,
        place_id: str | None = None,
    ) -> GeocodedLocation:
        if not self._api_key:
            raise ServiceNotConfiguredError(
                "Address lookup is not configured on the server (GOOGLE_MAPS_API_KEY is missing)."
            )
        if bool(address) == bool(place_id):
            raise ValueError("Provide exactly one of address or place_id.")

        params = {"key": self._api_key, "language": language}
        if place_id:
            params["place_id"] = place_id
        else:
            params["address"] = address

        payload = await self._request(params)
        status = payload.get("status")
        results = payload.get("results")

        if status == "OK" and isinstance(results, list) and results:
            return _parse_result(results[0], language)
        if status in {"ZERO_RESULTS", "NOT_FOUND"} or (status == "INVALID_REQUEST" and place_id):
            raise AddressNotFoundError("We couldn't find that address. Check the spelling or add a postcode.")

        logger.warning("Geocoding API returned status=%s", status)
        raise UpstreamServiceError(_UNAVAILABLE)

    async def _request(self, params: dict[str, str]) -> dict:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await self._http.get(GEOCODE_URL, params=params)
            except httpx.TransportError as exc:
                # Exception text can contain the request URL (and the key): log the type only.
                logger.warning("Geocoding request failed: %s (attempt %d)", type(exc).__name__, attempt)
            else:
                if response.status_code < 500:
                    if response.status_code != 200:
                        logger.warning("Geocoding API HTTP %d", response.status_code)
                        break
                    try:
                        payload = response.json()
                    except ValueError:
                        logger.warning("Geocoding API returned a non-JSON body")
                        break
                    if not isinstance(payload, dict):
                        logger.warning("Geocoding API returned an unexpected envelope")
                        break
                    if payload.get("status") not in _RETRYABLE_STATUSES or attempt == _MAX_ATTEMPTS:
                        return payload
                else:
                    logger.warning("Geocoding API HTTP %d (attempt %d)", response.status_code, attempt)
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(0.25 * attempt)
        raise UpstreamServiceError(_UNAVAILABLE)


def _parse_result(result: dict, language: str) -> GeocodedLocation:
    """Validate one Geocoding result into a domain location; malformed data is an upstream error."""
    try:
        geometry = result["geometry"]
        lat = float(geometry["location"]["lat"])
        lng = float(geometry["location"]["lng"])
        place_id = result["place_id"]
        formatted_address = result["formatted_address"]
        components = tuple(
            AddressComponent(
                long_name=str(c["long_name"]),
                short_name=str(c["short_name"]),
                types=tuple(c.get("types", ())),
            )
            for c in result.get("address_components", ())
        )
        location_type = str(geometry.get("location_type", "APPROXIMATE"))
    except (KeyError, TypeError, ValueError, AttributeError):
        logger.warning("Geocoding API result failed validation")
        raise UpstreamServiceError(_UNAVAILABLE) from None

    valid = (
        isinstance(place_id, str)
        and place_id
        and isinstance(formatted_address, str)
        and formatted_address
        and math.isfinite(lat)
        and math.isfinite(lng)
        and -90 <= lat <= 90
        and -180 <= lng <= 180
    )
    if not valid:
        logger.warning("Geocoding API result failed validation")
        raise UpstreamServiceError(_UNAVAILABLE)

    return GeocodedLocation(
        place_id=place_id,
        formatted_address=formatted_address,
        lat=lat,
        lng=lng,
        location_type=location_type,
        partial_match=bool(result.get("partial_match", False)),
        components=components,
        language=language,
    )
