"""Operational commands.

    python -m app.maintenance purge-expired
    python -m app.maintenance list-duplicates
    python -m app.maintenance merge <keep_property_id> <duplicate_property_id>
    python -m app.maintenance resume-merges
    python -m app.maintenance ingest-sources [jurisdiction_id]
    python -m app.maintenance list-sources
    python -m app.maintenance set-source-status <source_id> <status> <operator> <reason…>

purge-expired    removes expired Google-derived fields (the running service also does this).
list-duplicates  shows properties flagged as possible duplicates at creation.
merge            folds a *reviewed* duplicate into the property to keep; the duplicate's
                 ID keeps resolving to it. Safe to re-run: an interrupted merge completes.
                 Never run without checking both properties.
resume-merges    completes merges interrupted by a failure (the service also does this).
ingest-sources   seeds the official source registry, then fetches the trusted machine-readable
                 sources of a jurisdiction (default pt/lisboa/cascais) through the SafeFetcher,
                 snapshots them (sha256) and indexes their passages.
list-sources     shows every registered source with its status and latest snapshot.
set-source-status  operator lifecycle change (candidate → validated → trusted → retired);
                 validation checks apply and the change is recorded with operator and reason.

Reads MONGODB_URI from the environment / repo-root .env; prints no credentials.
"""

import asyncio
import sys

from pymongo import AsyncMongoClient

from app.core.config import get_settings
from app.db.property_repository import MongoPropertyRepository
from app.services.sources.catalog import ALL_SOURCES, CASCAIS
from app.services.sources.fetcher import SafeFetcher
from app.services.sources.ingest import SourceIngestor
from app.services.sources.registry import OFFICIAL_HOSTS, OfficialSourceRegistry, SourceRegistryError
from app.services.sources.repository import MongoSourceRepository


async def _run(command: str, args: list[str]) -> None:
    settings = get_settings()
    if not settings.mongodb_uri:
        raise SystemExit("MONGODB_URI is not set.")
    client = AsyncMongoClient(
        settings.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=settings.mongodb_timeout_ms, tz_aware=True
    )
    repo = MongoPropertyRepository(client, settings.mongodb_db_name)
    sources = MongoSourceRepository(client, settings.mongodb_db_name)
    registry = OfficialSourceRegistry(sources, ALL_SOURCES)
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
        elif command == "ingest-sources" and len(args) <= 1:
            await sources.ensure_indexes()
            await registry.seed()
            fetcher = SafeFetcher(OFFICIAL_HOSTS, timeout_seconds=settings.source_fetch_timeout_seconds)
            for report in await SourceIngestor(registry, fetcher).ingest_jurisdiction(args[0] if args else CASCAIS):
                print(f"{report.source_id}: {report.outcome} {report.detail} "
                      f"snapshot={report.snapshot_id} passages={report.chunks}".rstrip())
        elif command == "list-sources":
            await registry.seed()
            for s in sorted(await sources.list_sources(), key=lambda s: (s.jurisdiction_id, s.source_id)):
                print(f"{s.status:9} {s.jurisdiction_id:20} {s.source_id:34} {s.retrieval_method:18} "
                      f"snapshot={s.latest_snapshot_id or '-'}")
        elif command == "set-source-status" and len(args) >= 4:
            try:
                changed = await registry.change_status(args[0], args[1], operator=args[2], reason=" ".join(args[3:]))
            except SourceRegistryError as exc:
                raise SystemExit(f"Refused: {exc}") from None
            print(f"{changed.source_id} is now {changed.status}.")
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
