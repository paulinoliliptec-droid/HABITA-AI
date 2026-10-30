"""Location maps for the HR-006 PDF: one road map and one satellite image from the Google Maps Static API.

Both images share the same centre, zoom and size, so they cover the same ground. HABITA holds no verified parcel
geometry, so the property is drawn as a marker inside a circle sized from the geocoding precision and labelled
approximate; nothing here is a cadastral boundary. The images are fetched for the PDF being built and never stored.

Failures are reported as a short reason only: request URLs carry the API key, so neither URLs nor transport errors
are logged, raised or returned.
"""

import io
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx
from PIL import Image

from app.core.errors import RateLimitedError
from app.core.rate_limit import TokenBucket

STATIC_MAPS_URL = "https://maps.googleapis.com/maps/api/staticmap"
WIDTH, HEIGHT, SCALE = 640, 400, 2  # 1280 x 800 pixels per image
MAX_BYTES = 4_000_000
#: Geocoding precision → (zoom, radius of the approximate-location circle in metres).
FRAMING = {"rooftop": (18, 25), "interpolated": (17, 60), "area_center": (16, 150), "approximate": (15, 300)}
ATTRIBUTION = "Map data and imagery © Google (Google Maps Static API)"


@dataclass(frozen=True)
class MapImage:
    kind: str  # "roadmap" | "satellite"
    jpeg: bytes
    zoom: int


@dataclass(frozen=True)
class LocationMaps:
    lat: float
    lng: float
    precision: str
    radius_m: int
    images: tuple[MapImage, ...] = ()
    unavailable: str | None = None  # why there are no images; never set together with images


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
    """Request parameters without the key: everything but ``maptype`` is the same for both images."""
    zoom, radius = FRAMING.get(precision, FRAMING["approximate"])
    return {
        "center": f"{lat:.6f},{lng:.6f}", "zoom": str(zoom), "size": f"{WIDTH}x{HEIGHT}", "scale": str(SCALE),
        "maptype": maptype, "format": "jpg-baseline",
        "markers": f"color:0xC0392B|{lat:.6f},{lng:.6f}",
        "path": f"color:0xE0A000FF|weight:3|fillcolor:0xE0A00040|enc:{circle_polyline(lat, lng, radius)}",
    }


class StaticMapClient:
    def __init__(self, http: httpx.AsyncClient, api_key: str | None, *, timeout_seconds: float = 8.0,
                 rate_per_minute: float = 6, burst: int = 2, daily_limit: int = 200,
                 today=lambda: datetime.now(UTC).date()) -> None:
        self._http, self._key, self._timeout = http, api_key, timeout_seconds
        # Spend bounds per process; each PDF costs two paid map loads. The hard cap is the API quota in Google Cloud.
        self._bucket = TokenBucket(rate_per_minute, burst)
        self._daily_limit, self._today = daily_limit, today
        self._day: date | None = None
        self._spent = 0

    async def location_maps(self, lat: float, lng: float, precision: str) -> LocationMaps:
        zoom, radius = FRAMING.get(precision, FRAMING["approximate"])
        base = LocationMaps(lat=lat, lng=lng, precision=precision, radius_m=radius)
        if not self._key:
            return _replace(base, unavailable="No map service is configured for reports.")
        if self._today() != self._day:
            self._day, self._spent = self._today(), 0
        if self._spent >= self._daily_limit:
            return _replace(base, unavailable="Today's limit for report maps has been reached; maps were skipped.")
        try:
            self._bucket.take()
        except RateLimitedError:
            return _replace(base, unavailable="Too many reports were generated just now; maps were skipped.")
        self._spent += 1
        images = []
        for maptype in ("roadmap", "satellite"):
            image = await self._fetch(map_params(lat, lng, precision, maptype))
            if image is None:
                return _replace(base, unavailable="The map service did not return an image.")
            images.append(MapImage(kind=maptype, jpeg=image, zoom=zoom))
        return _replace(base, images=tuple(images))

    async def _fetch(self, params: dict[str, str]) -> bytes | None:
        try:
            response = await self._http.get(STATIC_MAPS_URL, params={**params, "key": self._key},
                                            timeout=self._timeout)
        except Exception:  # transport errors quote the URL, which carries the key
            return None
        body = response.content
        if (response.status_code != 200 or not response.headers.get("content-type", "").startswith("image/")
                or not body.startswith(b"\xff\xd8\xff") or len(body) > MAX_BYTES):
            return None
        try:  # a truncated or corrupt image would otherwise break the PDF instead of giving the notice
            with Image.open(io.BytesIO(body)) as image:
                image.load()
        except Exception:
            return None
        return body


def _replace(maps: LocationMaps, **changes) -> LocationMaps:
    return LocationMaps(**{**maps.__dict__, **changes})
