"""Operational commands.

    python -m app.maintenance purge-expired
    python -m app.maintenance list-duplicates
    python -m app.maintenance merge <keep_property_id> <duplicate_property_id>
    python -m app.maintenance resume-merges

purge-expired    removes expired Google-derived fields (the running service also does this).
list-duplicates  shows properties flagged as possible duplicates at creation.
merge            folds a *reviewed* duplicate into the property to keep; the duplicate's
                 ID keeps resolving to it. Safe to re-run: an interrupted merge completes.
                 Never run without checking both properties.
resume-merges    completes merges interrupted by a failure (the service also does this).

Reads MONGODB_URI from the environment / repo-root .env; prints no credentials.
"""

import asyncio
import sys

from pymongo import AsyncMongoClient

from app.core.config import get_settings
from app.db.property_repository import MongoPropertyRepository


async def _run(command: str, args: list[str]) -> None:
    settings = get_settings()
    if not settings.mongodb_uri:
        raise SystemExit("MONGODB_URI is not set.")
    client = AsyncMongoClient(
        settings.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=settings.mongodb_timeout_ms, tz_aware=True
    )
    repo = MongoPropertyRepository(client, settings.mongodb_db_name)
    try:
        if command == "purge-expired":
            print(f"Purged expired Google-derived fields from {await repo.purge_expired()} properties.")
        elif command == "resume-merges":
            print(f"Completed {await repo.resume_pending_merges()} interrupted merges.")
        elif command == "list-duplicates":
            collection = client[settings.mongodb_db_name]["properties"]
            async for doc in collection.find(
                {"possible_duplicates": {"$exists": True, "$ne": []}, "merged_into": {"$exists": False}},
                {"formatted_address": 1, "possible_duplicates": 1},
            ):
                print(f"{doc['_id']}  {doc.get('formatted_address', '(expired)')}  possible duplicate of {doc['possible_duplicates']}")
        elif command == "merge" and len(args) == 2:
            await repo.merge(keep=args[0], duplicate=args[1])
            print(f"Merged {args[1]} into {args[0]}.")
        else:
            raise SystemExit(__doc__)
    finally:
        await client.close()


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit(__doc__)
    asyncio.run(_run(argv[0], argv[1:]))


if __name__ == "__main__":
    main(sys.argv[1:])
