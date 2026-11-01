"""Official orthophotos of the Direção-Geral do Território (DGT), mainland Portugal, through its public WMS.

The capabilities (checked 2026-11-01) state "Fees: no conditions apply" and "AccessConstraints: None". 2018 covers the
whole mainland; 2021 covers only the north and answers blank elsewhere, so 2018 is used. The image is a fixed square
around the point, so its scale is known: that is what makes areas computable."""

import hashlib
import io
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from PIL import Image, ImageStat

logger = logging.getLogger(__name__)
SERVICE = "https://cartografia.dgterritorio.gov.pt/wms/ortos2018"
LAYER, YEAR = "Ortos2018-RGB", 2018
SIZE = 1024
#: Mainland Portugal (WMS extent).
EXTENT = (-10.1934, 36.7643, -5.70954, 42.2796)
MAX_BYTES = 6 * 1024 * 1024
_R = 6378137.0


@dataclass(frozen=True)
class Orthophoto:
    jpeg: bytes
    bbox: tuple[float, float, float, float]
    metres_per_pixel: float
    sha256: str
    retrieved_at: datetime


def covers(lat: float, lng: float) -> bool:
    w, s, e, n = EXTENT
    return w <= lng <= e and s <= lat <= n


def bbox_3857(lat: float, lng: float, half_m: float) -> tuple[float, float, float, float]:
    """A square of ``2 * half_m`` ground metres around the point, in Web Mercator (which stretches by 1/cos(lat))."""
    x = math.radians(lng) * _R
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * _R
    h = half_m / math.cos(math.radians(lat))
    return (x - h, y - h, x + h, y + h)


class DgtOrthophotoClient:
    def __init__(self, http: httpx.AsyncClient, *, timeout_seconds: float = 30.0) -> None:
        self._http, self._timeout = http, timeout_seconds

    async def fetch(self, lat: float, lng: float, half_m: float) -> Orthophoto | None:
        """The orthophoto around the point, or None outside the mainland, on failure, or when the answer is blank."""
        if not covers(lat, lng):
            return None
        bbox = bbox_3857(lat, lng, half_m)
        params = {"service": "WMS", "version": "1.3.0", "request": "GetMap", "layers": LAYER, "styles": "",
                  "crs": "EPSG:3857", "bbox": ",".join(f"{v:.2f}" for v in bbox), "width": str(SIZE),
                  "height": str(SIZE), "format": "image/jpeg"}
        try:
            r = await self._http.get(SERVICE, params=params, timeout=self._timeout)
        except httpx.HTTPError as exc:
            logger.warning("DGT orthophoto request failed: %s", type(exc).__name__)
            return None
        data = r.content
        if r.status_code != 200 or not data.startswith(b"\xff\xd8") or len(data) > MAX_BYTES:
            logger.warning("DGT orthophoto unusable: status=%d bytes=%d", r.status_code, len(data))
            return None
        try:
            with Image.open(io.BytesIO(data)) as img:
                if img.size != (SIZE, SIZE):
                    return None
                # A blank answer (no coverage) is one flat colour.
                if max(ImageStat.Stat(img.convert("L")).stddev) < 4:
                    return None
        except OSError:
            return None
        return Orthophoto(jpeg=data, bbox=bbox, metres_per_pixel=2 * half_m / SIZE,
                          sha256=hashlib.sha256(data).hexdigest(), retrieved_at=datetime.now(UTC))
