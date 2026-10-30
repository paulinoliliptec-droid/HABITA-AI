"""Operational commands.

    python -m app.maintenance purge-expired
    python -m app.maintenance list-duplicates
    python -m app.maintenance merge <keep_property_id> <duplicate_property_id>
    python -m app.maintenance resume-merges
    python -m app.maintenance ingest-sources [jurisdiction_id]
    python -m app.maintenance list-sources
    python -m app.maintenance set-source-status <source_id> <status> <operator> <reason…>
    python -m app.maintenance protocol-floor
    python -m app.maintenance raise-protocol-floor <min_protocol> <operator> <reason…>
    python -m app.maintenance apply-validator
    python -m app.maintenance migrate-floor <min_protocol> <operator> <reason…> [--apply --backup-manifest <file>]

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
protocol-floor   shows the verification protocol floor (MU-9) and the protocols it admits.
raise-protocol-floor  raises the floor (never lowers it; statement-v1 stays known unsafe), installs the
                 permit_verifications validator (a VERIFIED report needs an admitted protocol) and flags
                 VERIFIED reports from protocols no longer admitted as superseded. Before running it, route
                 no traffic to (and untag) Cloud Run revisions older than the MU-9 release.
migrate-floor    MU-9 migration of an existing database: validator, stored floor, and — in one transaction —
                 superseded flags on VERIFIED reports of protocols no longer admitted (and their matters) plus an
                 audit record in maintenance_audit. Dry run by default (prints the plan, changes nothing);
                 --apply needs the manifest of a verified backup of this database. Idempotent; deletes nothing.
apply-validator  installs the permit_verifications validator for the stored floor (no-op when it is already in
                 force). For databases whose application user lacks collMod: run it with a migration user after
                 a release that changes the rule; the service refuses to start until it is in force.

Reads MONGODB_URI from the environment / repo-root .env, or from the first stdin line with --uri-from-stdin;
prints no credentials.
"""

import asyncio
import hashlib
import json
import sys

from pathlib import Path

from pydantic import SecretStr
from pymongo import AsyncMongoClient, MongoClient

from app.core.config import get_settings
from app.db.backup import matches_db
from app.db.property_repository import MongoPropertyRepository
from app.services.permit.protocol import FloorError, raise_floor
from app.services.permit.migration import migrate_floor
from app.services.permit.repository import MongoPermitRepository
from app.services.sources.catalog import ALL_SOURCES, CASCAIS
from app.services.sources.fetcher import SafeFetcher
from app.services.sources.ingest import SourceIngestor
from app.services.sources.registry import OFFICIAL_HOSTS, OfficialSourceRegistry, SourceRegistryError
from app.services.sources.repository import MongoSourceRepository


async def _run(command: str, args: list[str]) -> None:
    settings = get_settings()
    if "--uri-from-stdin" in args:  # a credential never in argv or the environment (e.g. a temporary migration user)
        args.remove("--uri-from-stdin")
        settings = settings.model_copy(update={"mongodb_uri": SecretStr(sys.stdin.readline().strip())})
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
        elif command == "protocol-floor":
            floor = await MongoPermitRepository(client, settings.mongodb_db_name).get_floor()
            print(f"floor={floor.min_protocol} admitted={','.join(floor.admitted())} "
                  f"known_unsafe={','.join(floor.known_unsafe) or '-'} changes={len(floor.history)}")
        elif command == "raise-protocol-floor" and len(args) >= 3:
            permits = MongoPermitRepository(client, settings.mongodb_db_name)
            current = await permits.get_floor()
            try:
                new = raise_floor(current, args[0], operator=args[1], reason=" ".join(args[2:]))
            except FloorError as exc:
                raise SystemExit(f"Refused: {exc}") from None
            if not await permits.raise_floor(current, new):
                raise SystemExit("Refused: the floor changed concurrently; run the command again.")
            flagged = await permits.flag_superseded(new)
            print(f"floor={new.min_protocol} admitted={','.join(new.admitted())}; validator installed; "
                  f"{flagged} VERIFIED reports flagged as superseded.")
        elif command == "migrate-floor" and len(args) >= 3:
            apply, backup = "--apply" in args, None
            words = [a for a in args if a != "--apply"]
            if "--backup-manifest" in words:
                i = words.index("--backup-manifest")
                path, words = words[i + 1], words[:i] + words[i + 2:]
                raw = open(path, "rb").read()
                manifest = json.loads(raw)
                if manifest.get("database") != settings.mongodb_db_name or manifest.get("verified") is not True:
                    raise SystemExit("Refused: the manifest is not a verified backup of this database.")
                if apply:  # right before changing data: files intact and the live database still equal to them
                    sync = MongoClient(settings.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=15000,
                                       tz_aware=True)
                    try:
                        matches_db(sync, settings.mongodb_db_name, Path(path).parent)
                    finally:
                        sync.close()
                backup = {"manifest_sha256": hashlib.sha256(raw).hexdigest(), "created_at": manifest.get("created_at"),
                          "counts": {k: v["count"] for k, v in manifest["collections"].items()}}
            if apply and backup is None:
                raise SystemExit("Refused: --apply needs --backup-manifest <verified backup manifest>.")
            if len(words) < 3:
                raise SystemExit(__doc__)
            try:
                r = await migrate_floor(client, settings.mongodb_db_name, words[0], words[1], " ".join(words[2:]),
                                        apply=apply, backup=backup)
            except FloorError as exc:
                raise SystemExit(f"Refused: {exc}") from None
            print(f"{'APPLIED' if r.applied else 'DRY RUN'} on {r.database}: floor {r.floor_before} -> {r.floor_after}"
                  f"{' (stored)' if r.floor_stored else ''}; validator was {r.validator_before}; reports to flag "
                  f"{r.reports_to_flag}; matters to flag {r.matters_to_flag}"
                  + (f"; flagged {r.flagged_reports}; audit {r.audit_id}" if r.applied else ""))
        elif command == "apply-validator" and not args:
            permits = MongoPermitRepository(client, settings.mongodb_db_name)
            floor = await permits.get_floor()
            await permits.apply_validator(floor)
            print(f"validator in force for floor={floor.min_protocol} admitted={','.join(floor.admitted())}.")
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
