"""HR-011: the figures a user entered for a matter, one document per matter."""

from typing import Protocol

from pymongo.asynchronous.mongo_client import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.core.errors import StorageUnavailableError
from app.schemas.afford import AffordInputs

_UNAVAILABLE = "Storage is temporarily unavailable. Please try again."


class AffordRepository(Protocol):
    async def get(self, matter_id: str) -> AffordInputs | None: ...
    async def save(self, matter_id: str, inputs: AffordInputs) -> None: ...


class InMemoryAffordRepository:
    def __init__(self) -> None:
        self._inputs: dict[str, AffordInputs] = {}

    async def get(self, matter_id: str) -> AffordInputs | None:
        return self._inputs.get(matter_id)

    async def save(self, matter_id: str, inputs: AffordInputs) -> None:
        self._inputs[matter_id] = inputs


class MongoAffordRepository:
    def __init__(self, client: AsyncMongoClient, db_name: str) -> None:
        self._docs = client[db_name]["matter_afford"]

    async def get(self, matter_id: str) -> AffordInputs | None:
        try:
            doc = await self._docs.find_one({"_id": matter_id})
        except PyMongoError:
            raise StorageUnavailableError(_UNAVAILABLE) from None
        return AffordInputs.model_validate(doc["inputs"]) if doc else None

    async def save(self, matter_id: str, inputs: AffordInputs) -> None:
        try:
            await self._docs.replace_one({"_id": matter_id}, {"_id": matter_id, "inputs": inputs.model_dump()},
                                         upsert=True)
        except PyMongoError:
            raise StorageUnavailableError(_UNAVAILABLE) from None
