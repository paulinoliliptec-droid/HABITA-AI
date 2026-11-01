"""HR-012: before/after concepts from the user's own photos.

Only a photo the reader looked at and found no person in can be used (AC12.7). The instruction is HABITA's fixed text
for a change in the matter's catalog (AC12.2, AC12.6). The result is checked as an image, gets the notice burned in and
is kept privately next to the photo (AC12.3, AC12.9). Nothing here touches the matter, its evidence or its
verification (AC12.4). Spend: a per-process rate, a daily cap across instances and a cap per matter, all taken before
the paid call (AC12.8)."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime

from fastapi.concurrency import run_in_threadpool
from pymongo import ASCENDING
from pymongo.asynchronous.mongo_client import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.core.errors import NotFoundError, RateLimitedError, StorageUnavailableError, UpstreamServiceError
from app.core.rate_limit import ResolutionLimiter
from app.integrations.maps.static_maps import MemoryDailyUsage
from app.schemas.concepts import Concept, ConceptRoom
from app.services.concepts import catalog, rooms
from app.services.concepts.label import PLAN_NOTICE_PT, burn, for_editing
from app.services.files.inspect import FileRejected, inspect
from app.services.files.service import InvalidFileError, MatterFiles
from app.services.files.storage import FileStorage

logger = logging.getLogger(__name__)
_UNAVAILABLE = "Storage is temporarily unavailable. Please try again."


class InMemoryConceptRepository:
    def __init__(self) -> None:
        self._items: dict[str, Concept] = {}

    async def add(self, concept: Concept) -> None:
        self._items[concept.concept_id] = concept

    async def list(self, matter_id: str) -> list[Concept]:
        return sorted((c for c in self._items.values() if c.matter_id == matter_id), key=lambda c: c.created_at)

    async def remove(self, matter_id: str, concept_id: str) -> None:
        if (c := self._items.get(concept_id)) is not None and c.matter_id == matter_id:
            del self._items[concept_id]


class MongoConceptRepository:
    def __init__(self, client: AsyncMongoClient, db_name: str) -> None:
        self._docs = client[db_name]["matter_concepts"]

    async def ensure_indexes(self) -> None:
        await self._call(self._docs.create_index([("matter_id", ASCENDING), ("created_at", ASCENDING)]))

    async def add(self, concept: Concept) -> None:
        await self._call(self._docs.insert_one({"_id": concept.concept_id, **concept.model_dump(mode="python")}))

    async def list(self, matter_id: str) -> list[Concept]:
        cursor = self._docs.find({"matter_id": matter_id}).sort("created_at", ASCENDING)
        return [Concept.model_validate(d) for d in await self._call(cursor.to_list(100))]

    async def remove(self, matter_id: str, concept_id: str) -> None:
        await self._call(self._docs.delete_one({"_id": concept_id, "matter_id": matter_id}))

    @staticmethod
    async def _call(awaitable):
        try:
            return await awaitable
        except PyMongoError:
            raise StorageUnavailableError(_UNAVAILABLE) from None


def _key(matter_id: str, concept_id: str) -> str:
    return f"matters/{matter_id}/concepts/{concept_id}"


class Concepts:
    def __init__(self, repository, storage: FileStorage, files: MatterFiles, editor, *,
                 limiter: ResolutionLimiter | None = None, usage=None, daily_limit: int = 50,
                 per_matter: int = 3) -> None:
        self._repo, self._storage, self._files, self._editor = repository, storage, files, editor
        self._limiter = limiter or ResolutionLimiter(4, 3, 2)
        self._usage = usage or MemoryDailyUsage()
        self._daily, self._per_matter = daily_limit, per_matter

    async def list(self, matter_id: str) -> list[Concept]:
        return await self._repo.list(matter_id)

    async def rooms(self, matter_id: str, file_id: str) -> rooms.RoomOffer:
        """The rooms the user may choose to divide on this plan (HR-012, owner 2026-11-01)."""
        plan = next((f for f in await self._files.list(matter_id) if f.file_id == file_id), None)
        if plan is None:
            raise NotFoundError("This file doesn't exist.")
        if not (plan.kind == "plan" or plan.is_plan is True):
            raise InvalidFileError("These views are made only from a plan.")
        return rooms.offer(plan)

    async def create(self, matter_id: str, intent: str | None, file_id: str, change: str,
                     room_id: str | None = None) -> Concept:
        # Every refusal comes before any spend.
        from_plan = catalog.is_plan_change(change)
        if change not in (catalog.plan_options(intent) if from_plan else catalog.options(intent)):
            raise InvalidFileError("This change is not covered for this type of request.")
        photo = next((f for f in await self._files.list(matter_id) if f.file_id == file_id), None)
        if photo is None:
            raise NotFoundError("This file doesn't exist.")
        looks_like_plan = photo.kind == "plan" or photo.is_plan is True
        if from_plan and not looks_like_plan:
            raise InvalidFileError("These views are made only from a plan.")
        if not from_plan and (photo.kind != "photo" or photo.is_plan is not False
                              or photo.content_type not in ("image/jpeg", "image/png")):
            # An AI-edited plan could pass for a project: plans get their own views, never a redrawn plan.
            raise InvalidFileError("Concepts of a change are made only from your photos; for a plan, use the 3D view "
                                   "or the realistic image.")
        if photo.people_visible is not False:
            raise InvalidFileError("HABITA makes concepts only from photos it has checked and found no people in.")
        # The room to divide: chosen by the user from the rooms read on this plan, never assumed (owner, 2026-11-01).
        room = rooms.chosen(photo, room_id) if change in catalog.NEEDS_ROOM else None
        if change in catalog.NEEDS_ROOM and room is None:
            raise InvalidFileError("Choose the room to divide from the list read from your plan.")
        if change not in catalog.NEEDS_ROOM and room_id is not None:
            raise InvalidFileError("A room is chosen only for the view with one more bedroom.")
        prompt = catalog.instruction(change, rooms.describe(room) if room is not None else None)
        # The rate comes first and the whole job holds a concurrency slot, so repeated requests can't pile up decodes.
        # The photo is prepared before any count is taken, so a missing or unreadable photo costs nothing.
        slots = self._limiter.admit()
        async with slots:
            _, original = await self._files.content(matter_id, file_id)
            try:
                if photo.content_type == "application/pdf":  # the plan's image, as the reader saw it
                    original = (await run_in_threadpool(inspect, original)).readable
                    if original is None:
                        raise ValueError("no readable image in this PDF")
                source = await run_in_threadpool(for_editing, original)
            except (OSError, ValueError, FileRejected):
                raise InvalidFileError("This file can't be used for a concept.") from None
            day = datetime.now(UTC).date().isoformat()
            # Plan views have their own allowance per matter, beside the photo concepts.
            lifetime = f"{'plan_lifetime' if from_plan else 'lifetime'}:{matter_id}"
            try:
                # The day first: a full day takes nothing from the matter. The matter's cap is for its whole life.
                if await self._usage.take(day, self._daily) is None:
                    raise RateLimitedError(f"At most {self._daily} concepts are made a day. Please try again tomorrow.")
                if await self._usage.take(lifetime, self._per_matter) is None:
                    await self._usage.give_back(day)
                    raise RateLimitedError(f"A matter can have at most {self._per_matter} concepts.")
            except RateLimitedError:
                raise
            except Exception:  # noqa: BLE001 - without a reliable count, spend is not allowed
                raise StorageUnavailableError(_UNAVAILABLE) from None
            try:
                generated = await self._editor.edit(source, prompt)
            except UpstreamServiceError:
                # The image service refused or failed, so nothing was made: the attempt doesn't count.
                await self._give_back(lifetime, day)
                raise UpstreamServiceError("The image service could not make this concept. It does not count "
                                           "against your limit; please try again.") from None
        try:
            extra = (PLAN_NOTICE_PT, catalog.PLAN_NOTICE_EN) if from_plan else None
            labelled = await run_in_threadpool(burn, generated, extra)
        except Exception:  # noqa: BLE001 - whatever came back is not shown unless it is an image we could label
            logger.warning("HR-012 concept was not a usable image")
            raise UpstreamServiceError("The image service returned an unusable image. Please try again.") from None
        # AC12.7 holds for the result too: the reader checks it, and a person, or any doubt, means it is not kept.
        if await self._files.shows_people(labelled):
            raise UpstreamServiceError("The concept could not be kept because it may show a person. Please try "
                                       "another change or photo.")
        # The photo may have been deleted while the image was being made: then the concept goes with it.
        if not any(f.file_id == file_id for f in await self._files.list(matter_id)):
            raise NotFoundError("This photo was deleted while the concept was being made.")
        concept = Concept(concept_id=f"cn_{secrets.token_hex(8)}", matter_id=matter_id, file_id=file_id,
                          change=change, change_label=catalog.ALL_CHANGES[change][0], created_at=datetime.now(UTC),
                          model_id=self._editor.model_id,
                          room=ConceptRoom(id=room.id, label=room.label, type=room.type, type_label=room.type_label,
                                           place=room.place, place_label=room.place_label, floor=room.floor)
                          if room else None)
        await self._repo.add(concept)
        try:
            await self._storage.put(_key(matter_id, concept.concept_id), labelled, "image/jpeg")
        except BaseException:
            await self._storage.delete(_key(matter_id, concept.concept_id))  # never an object without a record
            await self._repo.remove(matter_id, concept.concept_id)
            raise
        # The record or the photo may have gone while the image was being written (a delete of either). Then the object
        # is removed directly, whether or not its record still exists, so nothing is left that no one can reach.
        photo_left = any(f.file_id == file_id for f in await self._files.list(matter_id))
        record_left = any(c.concept_id == concept.concept_id for c in await self._repo.list(matter_id))
        if not (photo_left and record_left):
            await self._storage.delete(_key(matter_id, concept.concept_id))
            await self._repo.remove(matter_id, concept.concept_id)
            raise NotFoundError("This photo or concept was deleted while the concept was being made.")
        return concept

    async def _give_back(self, lifetime: str, day: str) -> None:
        try:
            await self._usage.give_back(lifetime)
            await self._usage.give_back(day)
        except Exception:  # noqa: BLE001 - a lost refund only makes the limit stricter
            logger.warning("HR-012 could not give back a concept count")

    async def content(self, matter_id: str, concept_id: str) -> bytes:
        found = any(c.concept_id == concept_id for c in await self._repo.list(matter_id))
        data = await self._storage.get(_key(matter_id, concept_id)) if found else None
        if data is None:
            raise NotFoundError("This concept doesn't exist.")
        return data

    async def delete(self, matter_id: str, concept_id: str) -> None:
        if not any(c.concept_id == concept_id for c in await self._repo.list(matter_id)):
            raise NotFoundError("This concept doesn't exist.")
        await self._storage.delete(_key(matter_id, concept_id))
        await self._repo.remove(matter_id, concept_id)

    async def delete_for_file(self, matter_id: str, file_id: str) -> None:
        for c in await self._repo.list(matter_id):
            if c.file_id == file_id:
                await self.delete(matter_id, c.concept_id)
