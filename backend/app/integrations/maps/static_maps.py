"""Location images for the HR-006 PDF, from Google Maps Platform.

Two images are required: a road map and a satellite image with labels (``hybrid``), with the same centre, zoom, size,
marker and highlighted area, so they cover the same ground. A third, Street View, is added only when Google has an
outdoor panorama close to the point (free metadata request first); it shows the surroundings, nothing more.

HABITA holds no verified parcel geometry, so the property is a marker inside a circle sized from the geocoding
precision and labelled approximate; nothing here is a cadastral boundary. Google imagery proves neither ownership,
parcel limits, zoning nor a municipal licence. Images are fetched for the PDF being built and never stored.

Spend is bounded by a daily cap shared by every instance (a counter in the database: the service scales to zero, so a
per-process count would restart), plus a per-process rate and a per-property hourly cap; the hard cap is the API
quota in Google Cloud.
Request URLs carry the API key, so URLs and transport errors are never logged, raised or returned: logs carry counts,
kinds and HTTP status codes only.
"""

import io
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import httpx
from PIL import Image
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.errors import RateLimitedError
from app.core.rate_limit import TokenBucket

logger = logging.getLogger("habita.report_maps")

STATIC_MAPS_URL = "https://maps.googleapis.com/maps/api/staticmap"
STREET_VIEW_URL = "https://maps.googleapis.com/maps/api/streetview"
STREET_VIEW_METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
WIDTH, HEIGHT, SCALE = 640, 400, 2  # 1280 x 800 pixels per map image; Street View is 640 x 400
MAX_BYTES = 4_000_000
STREET_VIEW_MAX_DISTANCE_M = 50
#: Geocoding precision → (zoom, radius of the approximate-location circle in metres).
FRAMING = {"rooftop": (18, 25), "interpolated": (17, 60), "area_center": (16, 150), "approximate": (15, 300)}
ATTRIBUTION = "Map data and imagery © Google (Google Maps Static API, Street View Static API)"
#: Business points of interest hidden: the map shows streets and places, not advertising.
MAP_STYLE = "feature:poi.business|visibility:off"


@dataclass(frozen=True)
class MapImage:
    kind: str  # "roadmap" | "hybrid" | "streetview"
    jpeg: bytes
    zoom: int | None = None
    #: Street View only: panorama capture month (YYYY-MM) and its distance from the geocoded point.
    captured: str | None = None
    distance_m: int | None = None
    facing: bool = False  # the camera is turned toward the point (not when the panorama is at the point itself)


@dataclass(frozen=True)
class LocationMaps:
    lat: float
    lng: float
    precision: str
    radius_m: int
    images: tuple[MapImage, ...] = ()
    unavailable: str | None = None  # why there are no map images; never set together with images
    street_view_note: str | None = None  # why there is no Street View image, when the maps exist


def _encode(value: float) -> str:
    """One coordinate of Google's encoded-polyline format."""
    v = round(value * 1e5)
    v = ~(v << 1) if v < 0 else v << 1
    out = []
    while v >= 0x20:
        out.append(chr((0x20 | (v & 0x1F)) + 63))
        v >>= 5
    out.append(chr(v + 63))
    return "".join(out)


def circle_polyline(lat: float, lng: float, radius_m: float, points: int = 36) -> str:
    """A closed ring of ``points`` vertices around (lat, lng), as an encoded polyline."""
    coords = []
    for i in range(points + 1):
        a = 2 * math.pi * i / points
        coords.append((lat + radius_m / 111_320 * math.cos(a),
                       lng + radius_m / (111_320 * math.cos(math.radians(lat))) * math.sin(a)))
    out, prev = [], (0.0, 0.0)
    for c in coords:
        out.append(_encode(c[0] - prev[0]) + _encode(c[1] - prev[1]))
        prev = c
    return "".join(out)


def map_params(lat: float, lng: float, precision: str, maptype: str) -> dict[str, str]:
    """Request parameters without the key: everything but ``maptype`` is the same for both map images."""
    zoom, radius = FRAMING.get(precision, FRAMING["approximate"])
    return {
        "center": f"{lat:.6f},{lng:.6f}", "zoom": str(zoom), "size": f"{WIDTH}x{HEIGHT}", "scale": str(SCALE),
        "maptype": maptype, "format": "jpg-baseline", "style": MAP_STYLE,
        "markers": f"color:0xC0392B|{lat:.6f},{lng:.6f}",
        "path": f"color:0xE0A000FF|weight:3|fillcolor:0xE0A00040|enc:{circle_polyline(lat, lng, radius)}",
    }


def _distance_and_bearing(lat1: float, lng1: float, lat2: float, lng2: float) -> tuple[float, float]:
    """Metres and compass bearing (degrees) from point 1 to point 2 (equirectangular; fine at street scale)."""
    dy = (lat2 - lat1) * 111_320
    dx = (lng2 - lng1) * 111_320 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy), (math.degrees(math.atan2(dx, dy)) + 360) % 360


class MemoryDailyUsage:
    """Daily counter for one process (local runs and tests)."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    async def take(self, day: str, limit: int) -> int | None:
        """Count one PDF with maps for ``day``; the new count, or None when the limit was already reached."""
        n = self._counts.get(day, 0)
        if n >= limit:
            return None
        self._counts[day] = n + 1
        return n + 1


class MongoDailyUsage:
    """Daily counter shared by every instance: one document per UTC day, incremented atomically below the limit."""

    def __init__(self, collection) -> None:
        self._collection = collection

    async def take(self, day: str, limit: int) -> int | None:
        try:
            doc = await self._collection.find_one_and_update(
                {"_id": f"report-maps:{day}", "count": {"$lt": limit}}, {"$inc": {"count": 1}},
                upsert=True, return_document=ReturnDocument.AFTER)
        except DuplicateKeyError:  # the day's document exists at the limit, so the upsert could not match it
            return None
        return int(doc["count"])


class StaticMapClient:
    def __init__(self, http: httpx.AsyncClient, api_key: str | None, *, timeout_seconds: float = 8.0,
                 rate_per_minute: float = 6, burst: int = 2, daily_limit: int = 200, per_location_hourly: int = 6,
                 street_view: bool = True, usage=None, today=lambda: datetime.now(UTC).date(),
                 clock=time.monotonic) -> None:
        self._http, self._key, self._timeout, self._street_view = http, api_key, timeout_seconds, street_view
        self._bucket = TokenBucket(rate_per_minute, burst)  # one token per PDF (2 or 3 paid image loads)
        self._daily_limit, self._today = daily_limit, today
        self._usage = usage if usage is not None else MemoryDailyUsage()
        self._per_location, self._clock = per_location_hourly, clock
        self._recent: dict[str, deque[float]] = {}  # rolling, never reset at midnight
        self._count = 0

    async def _admit(self, place: str) -> str | None:
        """Why this PDF gets no maps (a spend bound), or None once the spend is counted."""
        recent = self._recent.setdefault(place, deque())
        now = self._clock()
        while recent and now - recent[0] > 3600:
            recent.popleft()
        if len(recent) >= self._per_location:
            return "Maps for this property were generated several times in the last hour; maps were skipped."
        recent.append(now)  # reserved before any await, so concurrent requests can't all pass the check
        try:
            self._bucket.take()
        except RateLimitedError:
            recent.remove(now)
            return "Too many reports were generated just now; maps were skipped."
        try:
            count = await self._usage.take(self._today().isoformat(), self._daily_limit)
        except Exception:  # without a reliable count, spend is not allowed
            recent.remove(now)
            logger.warning("report maps skipped: the usage counter is unavailable")
            return "The map usage counter is unavailable; maps were skipped."
        if count is None:
            recent.remove(now)
            return "Today's limit for report maps has been reached; maps were skipped."
        self._count = count
        return None

    async def location_maps(self, lat: float, lng: float, precision: str, place: str | None = None) -> LocationMaps:
        """``place`` identifies the property for the hourly cap (default: its coordinates)."""
        zoom, radius = FRAMING.get(precision, FRAMING["approximate"])
        base = LocationMaps(lat=lat, lng=lng, precision=precision, radius_m=radius)
        if not self._key:
            return replace(base, unavailable="No map service is configured for reports.")
        if reason := await self._admit(place or f"{lat:.5f},{lng:.5f}"):
            logger.warning("report maps skipped: %s", reason)
            return replace(base, unavailable=reason)
        images = []
        for maptype in ("roadmap", "hybrid"):
            image, status = await self._image(STATIC_MAPS_URL, map_params(lat, lng, precision, maptype))
            if image is None:
                logger.warning("report maps unavailable: %s image failed (%s)", maptype, status)
                return replace(base, unavailable="The map service did not return an image.")
            images.append(MapImage(kind=maptype, jpeg=image, zoom=zoom))
        note = None
        if self._street_view:
            street, note = await self._street(lat, lng)
            if street is not None:
                images.append(street)
        logger.info("report maps: %s at zoom %d (%d/%d today)", "+".join(i.kind for i in images), zoom,
                    self._count, self._daily_limit)
        return replace(base, images=tuple(images), street_view_note=note)

    async def _street(self, lat: float, lng: float) -> tuple[MapImage | None, str | None]:
        """A Street View image facing the point from the nearest outdoor panorama, or why there is none."""
        meta, status = await self._get(STREET_VIEW_METADATA_URL, {
            "location": f"{lat:.6f},{lng:.6f}", "radius": str(STREET_VIEW_MAX_DISTANCE_M), "source": "outdoor"})
        try:
            data = meta.json() if meta is not None and meta.status_code == 200 else {}
        except ValueError:
            data = {}
        found = data.get("status")
        if found in ("ZERO_RESULTS", "NOT_FOUND"):
            logger.info("street view: no panorama near the point")
            return None, "No Street View panorama is available near this location."
        if found != "OK" or "location" not in data or "pano_id" not in data:
            logger.warning("street view check failed (%s)", found or status)
            return None, "Street View could not be checked (map service error)."
        p = data["location"]
        distance, _ = _distance_and_bearing(lat, lng, p["lat"], p["lng"])
        if distance > STREET_VIEW_MAX_DISTANCE_M:
            return None, "No Street View panorama is available near this location."
        params = {"pano": str(data["pano_id"]), "size": f"{WIDTH}x{HEIGHT}", "fov": "80", "pitch": "5",
                  "return_error_code": "true"}
        facing = distance >= 2  # at the point itself there is no direction to face
        if facing:
            params["heading"] = f"{_distance_and_bearing(p['lat'], p['lng'], lat, lng)[1]:.0f}"
        image, status = await self._image(STREET_VIEW_URL, params)
        if image is None:
            logger.warning("street view image failed (%s)", status)
            return None, "The Street View image could not be retrieved."
        return MapImage(kind="streetview", jpeg=image, captured=data.get("date"), distance_m=round(distance),
                        facing=facing), None

    async def _get(self, url: str, params: dict[str, str]) -> tuple[httpx.Response | None, str]:
        try:
            response = await self._http.get(url, params={**params, "key": self._key}, timeout=self._timeout)
        except Exception as exc:  # transport errors quote the URL, which carries the key: keep the type only
            return None, type(exc).__name__
        return response, f"HTTP {response.status_code}"

    async def _image(self, url: str, params: dict[str, str]) -> tuple[bytes | None, str]:
        response, status = await self._get(url, params)
        if response is None:
            return None, status
        body = response.content
        if (response.status_code != 200 or not response.headers.get("content-type", "").startswith("image/")
                or not body.startswith(b"\xff\xd8\xff") or len(body) > MAX_BYTES):
            return None, status
        try:  # a truncated or corrupt image would otherwise break the PDF instead of giving the notice
            with Image.open(io.BytesIO(body)) as image:
                image.load()
        except Exception:
            return None, "undecodable image"
        return body, status
