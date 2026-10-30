"""Verifiable MongoDB backup and restore (canonical Extended JSON, manifest with digests); see infrastructure/db_backup.py
for the command line. Output and errors name collections and counts only, never document content or credentials."""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from bson import json_util
from pymongo import MongoClient

OPTIONS = json_util.CANONICAL_JSON_OPTIONS


def _lines(collection) -> list[str]:
    """Documents in _id order, each with its fields in their original order (restored exactly as stored)."""
    return [json_util.dumps(d, json_options=OPTIONS) for d in collection.find().sort("_id", 1)]


def _digest(lines: list[str]) -> str:
    """Content digest independent of field order: each document re-serialised with sorted keys."""
    h = hashlib.sha256()
    for line in lines:
        doc = json_util.loads(line, json_options=OPTIONS)
        h.update(json_util.dumps(doc, json_options=OPTIONS, sort_keys=True).encode() + b"\n")
    return h.hexdigest()


def _index_spec(index) -> dict:
    """An index with its key as an ordered list of [field, direction] pairs: compound key order matters."""
    spec = json.loads(json_util.dumps({k: v for k, v in index.items() if k != "key"}, json_options=OPTIONS))
    spec["key"] = [[field, direction] for field, direction in index["key"].items()]
    return spec


def export(client, db_name: str, out: Path) -> dict:
    db = client[db_name]
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"database": db_name, "created_at": datetime.now(UTC).isoformat(), "verified": False,
                "format": "habita-backup-1", "collections": {}}
    for info in sorted(db.list_collections(), key=lambda i: i["name"]):
        name = info["name"]
        if name.startswith("system."):
            continue
        lines = _lines(db[name])
        path = out / f"{name}.jsonl"
        path.write_text("".join(f"{line}\n" for line in lines))
        indexes = [_index_spec(i) for i in db[name].list_indexes()]
        manifest["collections"][name] = {
            "count": len(lines), "sha256": _digest(lines), "file": path.name,
            "options": json.loads(json_util.dumps(info.get("options", {}), json_options=OPTIONS)),
            "indexes": indexes,
        }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return manifest


def verify_files(out: Path) -> dict:
    manifest = json.loads((out / "manifest.json").read_text())
    for name, c in manifest["collections"].items():
        lines = (out / c["file"]).read_text().splitlines()
        if len(lines) != c["count"] or _digest(lines) != c["sha256"]:
            raise SystemExit(f"Backup file for {name} does not match the manifest.")
    return manifest


def matches_db(client, db_name: str, out: Path) -> dict:
    """Read-only: files intact and the live database equal to the backup (documents, collection options, indexes)."""
    manifest = verify_files(out)
    if manifest["database"] != db_name:
        raise SystemExit(f"The backup is of {manifest['database']}, not {db_name}.")
    db = client[db_name]
    infos = {i["name"]: i for i in db.list_collections() if not i["name"].startswith("system.")}
    if sorted(infos) != sorted(manifest["collections"]):
        raise SystemExit(f"Collections differ: live {sorted(infos)} vs backup {sorted(manifest['collections'])}.")
    for name, c in manifest["collections"].items():
        options = json.loads(json_util.dumps(infos[name].get("options", {}), json_options=OPTIONS))
        indexes = [_index_spec(i) for i in db[name].list_indexes()]
        if options != c["options"] or indexes != c["indexes"]:
            raise SystemExit(f"{name}: collection options or indexes changed since the backup; take a new one.")
        if _digest(_lines(db[name])) != c["sha256"]:
            raise SystemExit(f"{name} changed since the backup; take a new one.")
    return manifest


def verify_db(client, db_name: str, out: Path) -> dict:
    manifest = matches_db(client, db_name, out)
    manifest["verified"], manifest["verified_at"] = True, datetime.now(UTC).isoformat()
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return manifest


def restore(client, out: Path, db_name: str, replace: bool) -> dict:
    manifest = verify_files(out)
    db = client[db_name]
    present = {n for n in db.list_collection_names() if not n.startswith("system.")}
    if present and not replace:
        raise SystemExit(f"{db_name} is not empty ({sorted(present)}); restore needs an empty database or --replace.")
    if unrelated := present - set(manifest["collections"]):
        raise SystemExit(f"{db_name} has collections that are not in the backup ({sorted(unrelated)}): wrong target?")
    existing = present
    for name, c in manifest["collections"].items():
        if name in existing:
            db.drop_collection(name)
        options = json_util.loads(json.dumps(c["options"]), json_options=OPTIONS)
        db.create_collection(name, **options)
        for index in c["indexes"]:
            keys = [(field, direction) for field, direction in index["key"]]
            spec = json_util.loads(json.dumps({k: v for k, v in index.items() if k != "key"}), json_options=OPTIONS)
            if spec["name"] == "_id_":
                continue
            spec.pop("v", None)
            spec.pop("ns", None)
            db[name].create_index(keys, **spec)
        docs = [json_util.loads(line, json_options=OPTIONS) for line in (out / c["file"]).read_text().splitlines()]
        if docs:
            db[name].insert_many(docs, ordered=True)
        if _digest(_lines(db[name])) != c["sha256"]:
            raise SystemExit(f"Restored {name} does not match the backup.")
    return manifest
