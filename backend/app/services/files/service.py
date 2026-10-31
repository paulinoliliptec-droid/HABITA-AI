"""HR-010: photos, plans and documents a user adds to a matter.

Flow: consent → content check → capture date and GPS read → kept copy without location or device data → Muse Spark
reads the image → observations recorded, labelled as from the user's file. Nothing here touches the matter, its
checklist, evidence or verification, so a file can never make an answer VERIFIED (AC10.6); the report adds one
condition to confirm what was read."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fastapi.concurrency import run_in_threadpool
from pymongo import ASCENDING
from pymongo.asynchronous.mongo_client import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.core.errors import (
    AppError,
    ConflictError,
    NotFoundError,
    RateLimitedError,
    StorageUnavailableError,
    UpstreamServiceError,
)
from app.core.rate_limit import ResolutionLimiter
from app.integrations.maps.static_maps import MemoryDailyUsage
from app.schemas.files import CHECK_TEXT, CONSENT_VERSION, FileKind, MatterFile
from app.services.files.inspect import MAX_FILES, NEAR_METRES, FileRejected, distance_m, inspect
from app.services.files.storage import FileStorage
from app.services.permit.model import ReasoningModel

logger = logging.getLogger(__name__)
_UNAVAILABLE = "File storage is temporarily unavailable. Please try again."


class InvalidFileError(AppError):
    status_code = 422
    code = "validation_error"


READER = """\
You are HABITA's file READER. You see one photo, plan or document a user added about their property.
Say only what is visible, as short neutral sentences (at most 6), in English. Examples: "A kitchen with wall units.",
"The plan shows two floors.", "A window faces the street."
- Never state a legal conclusion, a licence, an exemption, a zoning class or whether works are allowed.
- Never give measurements as facts. If a figure is written on the file, say "The plan shows the number 60 m2", never
  "the area is 60 m2".
- Don't identify people, faces or number plates; don't describe people at all.
- If nothing about the property can be seen, return no observations.
Also return "checks": only the items below that the file clearly shows; none if unsure.
- "several_entrances": more than one entrance door to the property or to separate parts of it.
- "possible_structural_wall": a thick wall, a column or a beam that may carry weight.
- "kitchen_or_bathroom": a kitchen or a bathroom.
- "facade_or_window": an outside wall, a window or a balcony.
- "several_floors": more than one floor or level.
"""

READER_SCHEMA = {
    "type": "object",
    "properties": {
        "observations": {"type": "array", "items": {"type": "string"}},
        "checks": {"type": "array", "items": {"type": "string", "enum": sorted(CHECK_TEXT)}},
    },
    "required": ["observations", "checks"],
    "additionalProperties": False,
}


class FileRepository(Protocol):
    async def add(self, record: MatterFile) -> None: ...
    async def list(self, matter_id: str) -> list[MatterFile]: ...
    async def remove(self, matter_id: str, file_id: str) -> bool: ...
    async def replace(self, record: MatterFile) -> None: ...


class InMemoryFileRepository:
    def __init__(self) -> None:
        self._files: dict[str, MatterFile] = {}

    async def add(self, record: MatterFile) -> None:
        self._files[record.file_id] = record

    async def list(self, matter_id: str) -> list[MatterFile]:
        return sorted((f for f in self._files.values() if f.matter_id == matter_id), key=lambda f: f.added_at)

    async def replace(self, record: MatterFile) -> None:
        if record.file_id in self._files:
            self._files[record.file_id] = record

    async def remove(self, matter_id: str, file_id: str) -> bool:
        found = self._files.get(file_id)
        if found is None or found.matter_id != matter_id:
            return False
        del self._files[file_id]
        return True


class MongoFileRepository:
    def __init__(self, client: AsyncMongoClient, db_name: str) -> None:
        self._files = client[db_name]["matter_files"]

    async def ensure_indexes(self) -> None:
        await self._call(self._files.create_index([("matter_id", ASCENDING), ("added_at", ASCENDING)]))

    async def add(self, record: MatterFile) -> None:
        await self._call(self._files.insert_one({"_id": record.file_id, **record.model_dump(mode="python")}))

    async def list(self, matter_id: str) -> list[MatterFile]:
        cursor = self._files.find({"matter_id": matter_id}).sort("added_at", ASCENDING)
        return [MatterFile.model_validate(d) for d in await self._call(cursor.to_list(MAX_FILES * 2))]

    async def replace(self, record: MatterFile) -> None:
        await self._call(self._files.replace_one({"_id": record.file_id, "matter_id": record.matter_id},
                                                 {"_id": record.file_id, **record.model_dump(mode="python")}))

    async def remove(self, matter_id: str, file_id: str) -> bool:
        result = await self._call(self._files.delete_one({"_id": file_id, "matter_id": matter_id}))
        return result.deleted_count == 1

    @staticmethod
    async def _call(awaitable):
        try:
            return await awaitable
        except PyMongoError:
            raise StorageUnavailableError(_UNAVAILABLE) from None


def _key(record: MatterFile) -> str:
    return _object(record.matter_id, record.file_id)


def _object(matter_id: str, file_id: str) -> str:
    return f"matters/{matter_id}/{file_id}"


#: A file still being added can't be deleted yet, so its copy can't land after the delete; after this, an
#: interrupted upload can be.
READING_GRACE = timedelta(minutes=5)


class MatterFiles:
    """Spend on readings is bounded by a per-process rate and concurrency, a daily cap shared by every instance, and a
    daily cap per matter, so deleting and adding again can't buy unlimited readings."""

    def __init__(self, repository: FileRepository, storage: FileStorage, model: ReasoningModel, *,
                 limiter: ResolutionLimiter | None = None, usage=None, daily_limit: int = 200,
                 per_matter_daily: int = 20) -> None:
        self._repo = repository
        self._storage = storage
        self._model = model
        self._limiter = limiter or ResolutionLimiter(10, 5, 2)
        self._usage = usage or MemoryDailyUsage()
        self._daily_limit, self._per_matter = daily_limit, per_matter_daily

    async def _spend(self, matter_id: str) -> None:
        """The daily budgets, taken only for a file that passed its checks and will be read: a refused or invalid
        upload never uses them up."""
        day = datetime.now(UTC).date().isoformat()
        try:
            matter_ok = await self._usage.take(f"{day}:{matter_id}", self._per_matter)
            total_ok = matter_ok is not None and await self._usage.take(day, self._daily_limit)
        except Exception:  # without a reliable count, spend is not allowed  # noqa: BLE001
            raise StorageUnavailableError(_UNAVAILABLE) from None
        if not matter_ok or not total_ok:
            raise RateLimitedError("Today's limit for reading files has been reached. Please try again tomorrow.")

    async def list(self, matter_id: str) -> list[MatterFile]:
        return await self._repo.list(matter_id)

    async def admit(self, matter_id: str, consent: str):
        """Everything that can refuse an upload without its body: consent, the file count and the reading budget.
        Returns the concurrency slot the whole upload (receiving, checking, reading) must hold."""
        if consent != CONSENT_VERSION:
            raise InvalidFileError("Accept the notice about your files before adding one.")
        if len(await self._repo.list(matter_id)) >= MAX_FILES:  # cheap early refusal; the real check is below
            raise InvalidFileError(f"A matter can have at most {MAX_FILES} files.")
        return self._limiter.admit()  # the per-process rate: raises RateLimitedError

    async def add(self, matter_id: str, property_point: tuple[float, float], kind: FileKind, consent: str,
                  data: bytes) -> MatterFile:
        async with await self.admit(matter_id, consent):
            return await self.add_admitted(matter_id, property_point, kind, consent, data)

    async def add_admitted(self, matter_id: str, property_point: tuple[float, float], kind: FileKind, consent: str,
                           data: bytes) -> MatterFile:
        """Called only inside the slot ``admit`` returned."""
        try:
            checked = await run_in_threadpool(inspect, data)  # CPU-bound: off the event loop
        except FileRejected as exc:
            raise InvalidFileError(str(exc)) from None
        if checked.readable is not None:
            await self._spend(matter_id)
        gps_check, gps_distance = "none", None
        if checked.gps is not None:
            gps_distance = distance_m(checked.gps, property_point)
            gps_check = "near" if gps_distance <= NEAR_METRES else "far"
        record = MatterFile(
            file_id=f"fl_{secrets.token_hex(8)}", matter_id=matter_id, kind=kind, content_type=checked.content_type,
            size=len(checked.kept), sha256=hashlib.sha256(data).hexdigest(), added_at=datetime.now(UTC),
            consent_version=consent, captured_at=checked.captured_at, gps_check=gps_check,
            gps_distance_m=gps_distance, read_status="reading")
        # The record comes first, so a copy always has a record the user can list and delete, even if the request is
        # interrupted. Counting after inserting reserves the place: concurrent uploads past the limit, on any
        # instance, see more than the limit and withdraw.
        await self._repo.add(record)
        try:
            if len(await self._repo.list(matter_id)) > MAX_FILES:
                raise InvalidFileError(f"A matter can have at most {MAX_FILES} files.")
            # Stored before the paid reading, so an unconfigured or failing store costs nothing.
            await self._storage.put(_key(record), checked.kept, checked.content_type)
            if not any(f.file_id == record.file_id for f in await self._repo.list(matter_id)):
                raise NotFoundError("This file was deleted while it was being added.")
        except BaseException:
            await self._storage.delete(_key(record))
            await self._repo.remove(matter_id, record.file_id)
            raise
        status, observations, checks, model_id = await self._read(checked.readable)
        record = record.model_copy(update={"read_status": status, "observations": observations, "checks": checks,
                                           "model_id": model_id})
        await self._repo.replace(record)
        return record

    async def content(self, matter_id: str, file_id: str) -> tuple[MatterFile, bytes]:
        record = next((f for f in await self._repo.list(matter_id) if f.file_id == file_id), None)
        data = await self._storage.get(_key(record)) if record else None
        if record is None or data is None:
            raise NotFoundError("This file doesn't exist.")
        return record, data

    async def delete(self, matter_id: str, file_id: str) -> None:
        record = next((f for f in await self._repo.list(matter_id) if f.file_id == file_id), None)
        if record is None:
            raise NotFoundError("This file doesn't exist.")
        if record.read_status == "reading" and datetime.now(UTC) - record.added_at < READING_GRACE:
            raise ConflictError("This file is still being added. Try again in a moment.")
        await self._storage.delete(_key(record))  # the copy first: a record without a copy is harmless
        await self._repo.remove(matter_id, file_id)

    async def _read(self, picture: bytes | None) -> tuple[str, list[str], list[str], str | None]:
        if picture is None:
            return "unreadable", [], [], None
        url = "data:image/jpeg;base64," + base64.b64encode(picture).decode()
        try:
            result = await self._model.chat(
                [{"role": "system", "content": READER},
                 {"role": "user", "content": [{"type": "text", "text": "Describe what is visible."},
                                              {"type": "image_url", "image_url": {"url": url}}]}],
                response_schema=READER_SCHEMA, schema_name="file_reading")
            parsed = json.loads(result.content or "")
            observations = [o.strip()[:300] for o in parsed["observations"] if isinstance(o, str) and o.strip()][:6]
            # Only known keys count, whatever the model returned; their text is HABITA's.
            checks = list(dict.fromkeys(c for c in parsed.get("checks", []) if c in CHECK_TEXT))
        except (UpstreamServiceError, ValueError, KeyError, TypeError, AttributeError):
            logger.warning("HR-010 file reading failed")
            return "failed", [], [], None
        except Exception:  # noqa: BLE001 - a model fault must not lose the user's file
            logger.exception("HR-010 file reading failed unexpectedly")
            return "failed", [], [], None
        return "read", observations, checks, self._model.model_id
