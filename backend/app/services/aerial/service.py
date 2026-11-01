"""Seen from the air (owner, 2026-11-01): the official DGT orthophoto around a property, segmented by Meta SAM 3.1.

HABITA asks SAM for a closed list of things ("building", "swimming pool"), keeps those within the geocoding's own
uncertainty of the point, measures them from the image scale, and turns what it finds into fixed sentences to confirm
with the Câmara Municipal. Nothing here touches a matter, its evidence or its verification; an aerial finding is an
observation, never a fact, a parcel boundary or proof about a licence. One analysis per property, kept with its image;
spend: a per-process rate, a daily cap across instances taken before the paid calls and given back if nothing is kept."""

from __future__ import annotations

import io
import logging
import math
import secrets
from datetime import UTC, datetime

from fastapi.concurrency import run_in_threadpool
from PIL import Image, ImageDraw, ImageFont
from pymongo.asynchronous.mongo_client import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.core.errors import (
    AppError,
    RateLimitedError,
    ServiceNotConfiguredError,
    StorageUnavailableError,
    UpstreamServiceError,
)
from app.core.rate_limit import ResolutionLimiter
from app.integrations.dgt.orthophoto import LAYER, SERVICE, SIZE, YEAR, Orthophoto, covers
from app.integrations.maps.static_maps import MemoryDailyUsage
from app.integrations.meta.segment import Segment
from app.schemas.aerial import AerialObject, AerialReport, AerialSource

logger = logging.getLogger(__name__)
PROMPTS = ("building", "swimming pool")
#: A building smaller than this, not under the point, is reported as a small separate building (annex, shed, garage).
SMALL_M2 = 40
#: By geocoding precision: (half the image side, radius kept around the point), ground metres. Coarser addresses
#: can't say which buildings are the property's, so they get no analysis.
FRAMING = {"rooftop": (60.0, 25), "interpolated": (80.0, 60)}
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BAND = 56  # two lines of 18 px text under the image
_UNAVAILABLE = "The aerial analysis is temporarily unavailable. Please try again later."


class AerialUnavailableError(AppError):
    status_code = 422
    code = "validation_error"


class InMemoryAerialRepository:
    def __init__(self) -> None:
        self._items: dict[str, AerialReport] = {}

    async def get(self, property_id: str) -> AerialReport | None:
        return self._items.get(property_id)

    async def add(self, report: AerialReport) -> bool:
        """False when the property already has one (another request won)."""
        if report.property_id in self._items:
            return False
        self._items[report.property_id] = report
        return True


class MongoAerialRepository:
    def __init__(self, client: AsyncMongoClient, db_name: str) -> None:
        self._docs = client[db_name]["property_aerial"]

    async def get(self, property_id: str) -> AerialReport | None:
        try:
            doc = await self._docs.find_one({"_id": property_id})
        except PyMongoError:
            raise StorageUnavailableError(_UNAVAILABLE) from None
        return AerialReport.model_validate(doc) if doc else None

    async def add(self, report: AerialReport) -> bool:
        from pymongo.errors import DuplicateKeyError
        try:
            await self._docs.insert_one({"_id": report.property_id, **report.model_dump(mode="python")})
        except DuplicateKeyError:
            return False
        except PyMongoError:
            raise StorageUnavailableError(_UNAVAILABLE) from None
        return True


def _key(property_id: str, aerial_id: str) -> str:
    return f"properties/{property_id}/aerial/{aerial_id}.jpg"


def measure(segment: Segment, kind_prompt: str, metres_per_pixel: float, radius_m: int,
            others: bytearray | None = None) -> AerialObject | None:
    """The object as HABITA reports it, or None when no part of it is within ``radius_m`` of the image centre.
    ``others`` marks the pixels of the other buildings: a small building within 1 m of one is part of it, not a
    separate building (Codex aerial-r1)."""
    centre = SIZE / 2
    pixels = 0
    nearest = math.inf
    at_point = False
    w = segment.width
    for i, bit in enumerate(segment.mask):
        if not bit:
            continue
        pixels += 1
        px, py = segment.left + i % w + 0.5, segment.top + i // w + 0.5
        d = math.hypot(px - centre, py - centre)
        if d < nearest:
            nearest = d
        if int(px) == int(centre) and int(py) == int(centre):
            at_point = True
    if pixels == 0:
        return None
    distance = 0 if at_point else nearest * metres_per_pixel
    if distance > radius_m:
        return None
    area = pixels * metres_per_pixel ** 2
    if kind_prompt == "swimming pool":
        kind = "pool"
    elif area < SMALL_M2 and not at_point and not _touches(segment, others, metres_per_pixel):
        kind = "small_building"
    else:
        kind = "building"
    return AerialObject(kind=kind, area_m2=max(5, int(round(area / 5) * 5)), distance_m=int(round(distance)),
                        at_point=at_point)


def _touches(segment: Segment, others: bytearray | None, metres_per_pixel: float) -> bool:
    """Whether any pixel of the segment lies within 1 m of another building's pixel."""
    if others is None:
        return False
    limit = 1.0 / metres_per_pixel  # 1 m, in pixels, as a true distance (Codex aerial-r2)
    reach = max(1, math.ceil(limit))
    w = segment.width
    for i, bit in enumerate(segment.mask):
        if not bit:
            continue
        x, y = segment.left + i % w, segment.top + i // w
        for dy in range(-reach, reach + 1):
            yy = y + dy
            if not 0 <= yy < SIZE:
                continue
            row = yy * SIZE
            for dx in range(-reach, reach + 1):
                xx = x + dx
                if dx * dx + dy * dy <= limit * limit and 0 <= xx < SIZE and others[row + xx]:
                    return True
    return False


def _occupancy(segments: list[Segment], skip: Segment) -> bytearray:
    grid = bytearray(SIZE * SIZE)
    for seg in segments:
        if seg is skip:
            continue
        for i, bit in enumerate(seg.mask):
            if bit:
                grid[(seg.top + i // seg.width) * SIZE + seg.left + i % seg.width] = 1
    return grid


_FILL = {"building": (255, 110, 0, 110), "small_building": (255, 40, 120, 140), "pool": (0, 170, 255, 150)}


def overlay(photo: Orthophoto, kept: list[tuple[Segment, AerialObject]], radius_m: int) -> bytes:
    """The orthophoto with HABITA's drawing of the kept outlines, the radius, and the source line burned in."""
    with Image.open(io.BytesIO(photo.jpeg)) as src:
        base = src.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for seg, obj in kept:
        *rgb, alpha = _FILL[obj.kind]
        mask = Image.frombytes("L", (seg.width, seg.height), bytes(alpha if b else 0 for b in seg.mask))
        layer.paste(Image.new("RGBA", (seg.width, seg.height), (*rgb, 255)), (seg.left, seg.top), mask)
    r = radius_m / photo.metres_per_pixel
    c = SIZE / 2
    draw.ellipse((c - r, c - r, c + r, c + r), outline=(255, 230, 0, 255), width=3)
    draw.line((c - 8, c, c + 8, c), fill=(255, 255, 255, 255), width=2)
    draw.line((c, c - 8, c, c + 8), fill=(255, 255, 255, 255), width=2)
    out = Image.alpha_composite(base, layer).convert("RGB")
    font = ImageFont.truetype(FONT, 18)
    band = Image.new("RGB", (SIZE, SIZE + BAND), (20, 20, 20))
    band.paste(out, (0, 0))
    # CC BY 4.0 (dados.gov.pt, "Ortofotos 25 cm - Portugal Continental - 2018"): attribution, and the change stated.
    pen = ImageDraw.Draw(band)
    pen.text((10, SIZE + 6), f"Informação geográfica cedida pela Direção-Geral do Território (CC BY 4.0) · Ortos {YEAR}",
             font=font, fill=(255, 255, 255))
    pen.text((10, SIZE + 30), "Outlines added by HABITA with Meta SAM 3.1: approximate, not a survey or a parcel boundary",
             font=font, fill=(255, 255, 255))
    buf = io.BytesIO()
    band.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def analyse(photo: Orthophoto, found: dict[str, list[Segment]], radius_m: int) -> tuple[list[AerialObject], bytes]:
    kept: list[tuple[Segment, AerialObject]] = []
    buildings = found.get("building", [])
    for prompt in PROMPTS:
        for seg in found.get(prompt, []):
            others = _occupancy(buildings, seg) if prompt == "building" else None
            obj = measure(seg, prompt, photo.metres_per_pixel, radius_m, others)
            if obj is not None:
                kept.append((seg, obj))
    kept.sort(key=lambda so: (so[1].distance_m, -so[1].area_m2))
    return [o for _, o in kept], overlay(photo, kept, radius_m)


class AerialAnalysis:
    def __init__(self, repository, storage, orthophotos, segmenter, *, limiter: ResolutionLimiter | None = None,
                 usage=None, daily_limit: int = 40) -> None:
        self._repo, self._storage, self._ortho, self._sam = repository, storage, orthophotos, segmenter
        self._limiter = limiter or ResolutionLimiter(4, 2, 1)
        self._usage = usage or MemoryDailyUsage()
        self._daily = daily_limit

    async def get(self, property_id: str) -> AerialReport | None:
        return await self._repo.get(property_id)

    async def image(self, property_id: str) -> bytes | None:
        report = await self._repo.get(property_id)
        return await self._storage.get(_key(property_id, report.aerial_id)) if report else None

    async def create(self, prop) -> AerialReport:
        """``prop`` is a resolved property. Every refusal comes before any spend."""
        existing = await self._repo.get(prop.property_id)
        if existing is not None:
            return existing
        framing = FRAMING.get(prop.precision)
        if framing is None:
            raise AerialUnavailableError("This address is too imprecise to say which buildings belong to it, so the "
                                         "aerial view isn't available for it.")
        lat, lng = prop.coordinates.lat, prop.coordinates.lng
        if not covers(lat, lng):
            raise AerialUnavailableError("The aerial view uses the DGT orthophotos, which cover mainland Portugal only.")
        if not self._sam.configured():
            raise ServiceNotConfiguredError("The aerial analysis is not configured on the server (META_API_KEY).")
        half, radius = framing
        async with self._limiter.admit():
            day = datetime.now(UTC).date().isoformat()
            # One paid attempt per property and day, taken first on every instance: concurrent requests and repeated
            # failures can't buy more SAM calls (Codex aerial-r1). Then the shared daily cap.
            mine = f"{day}:property:{prop.property_id}"
            taken: list[str] = []
            try:
                if await self._usage.take(mine, 1) is None:
                    raise RateLimitedError("The aerial analysis of this property was already tried today. Please try "
                                           "again tomorrow.")
                taken.append(mine)
                if await self._usage.take(day, self._daily) is None:
                    raise RateLimitedError("Today's limit for aerial analyses has been reached. Please try again "
                                           "tomorrow.")
                taken.append(day)
            except RateLimitedError:
                await self._give_back(taken)
                raise
            except Exception:  # noqa: BLE001 - without a reliable count, spend is not allowed
                await self._give_back(taken)
                raise StorageUnavailableError(_UNAVAILABLE) from None
            spent = [False]
            try:
                return await self._make(prop.property_id, lat, lng, half, radius, spent)
            except BaseException:
                if not spent[0]:  # nothing was paid (no SAM call): the attempt doesn't count
                    await self._give_back(taken)
                raise

    async def _give_back(self, keys: list[str]) -> None:
        for key in keys:
            try:
                await self._usage.give_back(key)
            except Exception:  # noqa: BLE001 - a lost refund only makes the limit stricter
                logger.warning("Aerial analysis could not give back a count")

    async def _make(self, property_id: str, lat: float, lng: float, half: float, radius: int,
                    spent: list[bool]) -> AerialReport:
        photo = await self._ortho.fetch(lat, lng, half)
        if photo is None:
            raise UpstreamServiceError("The DGT orthophoto could not be obtained for this place. Please try again later.")
        reach = radius / photo.metres_per_pixel + 1
        c = SIZE / 2

        def near(left: int, top: int, right: int, bottom: int) -> bool:
            """Only boxes that come within the radius are decoded."""
            dx = max(left - c, 0, c - right)
            dy = max(top - c, 0, c - bottom)
            return math.hypot(dx, dy) <= reach

        # Buildings touching a kept one matter for the separation test, so buildings get a wider reach.
        def near_buildings(left: int, top: int, right: int, bottom: int) -> bool:
            dx = max(left - c, 0, c - right)
            dy = max(top - c, 0, c - bottom)
            return math.hypot(dx, dy) <= reach + 2 / photo.metres_per_pixel

        spent[0] = True
        found = {p: await self._sam.segment(photo.jpeg, p, SIZE, SIZE,
                                            near_buildings if p == "building" else near) for p in PROMPTS}
        objects, image = await run_in_threadpool(analyse, photo, found, radius)
        checks = []
        if any(o.kind == "small_building" for o in objects):
            checks.append("aerial_small_building")
        if any(o.kind == "pool" for o in objects):
            checks.append("aerial_pool")
        report = AerialReport(
            aerial_id=f"ae_{secrets.token_hex(8)}", property_id=property_id, created_at=datetime.now(UTC),
            source=AerialSource(service=SERVICE, layer=LAYER, year=YEAR, bbox=photo.bbox, width=SIZE, height=SIZE,
                                metres_per_pixel=round(photo.metres_per_pixel, 4), sha256=photo.sha256,
                                retrieved_at=photo.retrieved_at),
            model_id=self._sam.model_id, prompts=list(PROMPTS), radius_m=radius, objects=objects, checks=checks)
        key = _key(property_id, report.aerial_id)
        await self._storage.put(key, image, "image/jpeg")
        try:
            added = await self._repo.add(report)
        except BaseException:
            await self._storage.delete(key)
            raise
        if not added:  # another request made it first: keep that one
            await self._storage.delete(key)
            winner = await self._repo.get(property_id)
            if winner is None:
                raise StorageUnavailableError(_UNAVAILABLE)
            return winner
        return report
