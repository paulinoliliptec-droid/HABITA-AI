"""Verifiable MongoDB backup and restore for one HABITA database (e.g. the original ``habita_ai``).

The connection URI is read from stdin (never argv or the environment), e.g.:

    gcloud secrets versions access latest --secret mongodb-uri | \
      backend/.venv/bin/python infrastructure/db_backup.py export habita_ai /secure/dir

Commands
  export <db> <dir>             one canonical Extended-JSON file per collection (documents sorted by _id), with the
                                collection options (validator) and indexes, and manifest.json (counts, sha256 per
                                file, database digest). Read-only on the database.
  verify <dir>                  re-hashes every file against manifest.json (no database needed: run with </dev/null).
  verify-db <db> <dir>          read-only: the live database still equals the backup (same digest per collection);
                                on success marks the manifest "verified": true.
  restore <dir> <db> [--replace]  recreates collections (options, indexes) and documents into <db>. Refuses a
                                non-empty <db> unless --replace (which drops only the collections in the backup).
Output names collections and counts only; no document content and no credential is printed.
"""

import sys
from pathlib import Path

from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db.backup import export, restore, verify_db, verify_files  # noqa: E402


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[0] not in {"export", "verify", "verify-db", "restore"}:
        raise SystemExit(__doc__)
    cmd = argv[0]
    if cmd == "verify":
        m = verify_files(Path(argv[1]))
        print(f"files match the manifest: {len(m['collections'])} collections, "
              f"{sum(c['count'] for c in m['collections'].values())} documents, verified={m['verified']}")
        return
    uri = sys.stdin.read().strip()
    client = MongoClient(uri, serverSelectionTimeoutMS=15000, tz_aware=True)
    del uri
    try:
        if cmd == "export":
            m = export(client, argv[1], Path(argv[2]))
        elif cmd == "verify-db":
            m = verify_db(client, argv[1], Path(argv[2]))
        else:
            m = restore(client, Path(argv[1]), argv[2], "--replace" in argv)
    finally:
        client.close()
    print(f"{cmd} ok: " + ", ".join(f"{n}={c['count']}" for n, c in sorted(m["collections"].items())))


if __name__ == "__main__":
    main(sys.argv[1:])
