"""One-time preparation of the ORIGINAL database (habita_ai) for the MU-9 code. Run by the owner, once, in an
interactive terminal on the workstation, from the repository root:

    backend/.venv/bin/python infrastructure/migrate_original.py

It does, in order, stopping at the first failure:
1. Atlas: custom role habitaPreviewMigrate (readWrite + collMod on habita_ai only), created if absent;
2. Atlas: temporary user habita-preview-migrate with that role on habita-ai-m0, deleted after 2 hours and deleted again
   at the end; its random password is generated here, typed into the Atlas CLI prompt through a pseudo-terminal and
   never shown, written to a file, or put on a command line or in the environment;
3. a fresh backup of habita_ai (read-only, operational user) verified against the live database;
4. the migration dry run (validator, floor atomic-v1, legacy statement-v1 results flagged as superseded);
5. after you type APLICAR: the migration (re-verifies the backup first; one transaction; audit record; deletes nothing);
6. after you type SIM: secretAccessor on maps-static-api-key for the original backend's account only.
Nothing here changes Cloud Run traffic. Output names counts and ids only, never credentials or document content.
"""

import asyncio
import os
import pty
import secrets
import string
import subprocess
import sys
import time
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from pymongo import AsyncMongoClient, MongoClient  # noqa: E402

from app.db.backup import export, matches_db, verify_db  # noqa: E402
from app.services.permit.migration import migrate_floor  # noqa: E402

GCP, ATLAS_PROJECT, CLUSTER, HOST = "habita-ai-512916", "6adfdf61d52b2b35f1de0cf3", "habita-ai-m0", \
    "habita-ai-m0.mhbehnn.mongodb.net"
DB, ROLE, USER = "habita_ai", "habitaPreviewMigrate", "habita-preview-migrate"
ORIGINAL_SA = "988261836110-compute@developer.gserviceaccount.com"
ATLAS = ["atlas", "--projectId", ATLAS_PROJECT, "-P", "habita"]


def step(n, text):
    print(f"\n[{n}] {text}", flush=True)


def stop(text):
    print(f"STOP: {text}", file=sys.stderr)
    sys.exit(1)


def run(cmd, data=None):
    return subprocess.run(cmd, input=data, capture_output=True, text=True)


def atlas_create_user_with_prompt(password: str, delete_after: str) -> int:
    """Run `atlas dbusers create` without --password and answer its password prompt through a pseudo-terminal."""
    cmd = ["atlas", "dbusers", "create", "--username", USER, "--role", f"{ROLE}@admin", "--scope", CLUSTER,
           "--deleteAfter", delete_after, "--desc", "HABITA temporary migration user", "--projectId", ATLAS_PROJECT,
           "-P", "habita"]
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(cmd[0], cmd)
    seen, answered, deadline = b"", False, time.time() + 60
    while time.time() < deadline:
        try:
            chunk = os.read(fd, 1024)
        except OSError:
            break
        if not chunk:
            break
        seen += chunk
        if not answered and b"assword" in seen:
            os.write(fd, password.encode() + b"\r")
            answered = True
    _, status = os.waitpid(pid, 0)
    text = seen.decode(errors="replace").replace(password, "<hidden>")
    print("   atlas:", " ".join(line.strip() for line in text.splitlines() if "successfully" in line or "rror" in line))
    return os.waitstatus_to_exitcode(status) if answered else 99


def app_uri() -> str:
    r = run(["gcloud", "secrets", "versions", "access", "latest", "--secret", "mongodb-uri", "--project", GCP])
    if r.returncode != 0 or not r.stdout.strip():
        stop("cannot read the operational connection (secret mongodb-uri).")
    return r.stdout.strip()


async def plan_or_apply(uri, apply, manifest_dir=None, backup=None):
    client = AsyncMongoClient(uri, serverSelectionTimeoutMS=20000, tz_aware=True)
    try:
        return await migrate_floor(client, DB, "atomic-v1", operator="owner (migrate_original.py)",
                                   reason="MU-9 rollout on the original: floor atomic-v1; legacy statement-v1 results "
                                          "flagged as superseded", apply=apply, backup=backup)
    finally:
        await client.close()


def main():
    if not sys.stdin.isatty():
        stop("run this in an interactive terminal.")
    step(0, "Checks")
    who = run(["atlas", "auth", "whoami", "-P", "habita"])
    if who.returncode != 0:
        stop("Atlas CLI profile 'habita' is not signed in: run `atlas auth login --profile habita` first.")
    print("  ", who.stdout.strip())
    if run(["gcloud", "config", "get-value", "account"]).stdout.strip() != "paulinoliliptec@gmail.com":
        stop("gcloud must be signed in as paulinoliliptec@gmail.com.")

    step(1, f"Atlas role {ROLE} (readWrite + collMod on {DB} only)")
    roles = run(ATLAS[:1] + ["customDbRoles", "list", "-o", "json"] + ATLAS[1:])
    if f'"roleName": "{ROLE}"' not in roles.stdout and f'"roleName":"{ROLE}"' not in roles.stdout:
        r = run(ATLAS[:1] + ["customDbRoles", "create", ROLE, "--privilege", f"COLL_MOD@{DB}",
                             "--inheritedRole", f"readWrite@{DB}"] + ATLAS[1:])
        if r.returncode != 0:
            stop(f"role creation failed: {r.stderr.strip()[:200]}")
    print("   role ready")

    step(2, f"Temporary Atlas user {USER} (deleted after 2 hours, and at the end)")
    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for _ in range(32))
    delete_after = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if atlas_create_user_with_prompt(password, delete_after) != 0:
        stop("the temporary user could not be created (no password prompt or Atlas error).")
    mig_uri = (f"mongodb+srv://{USER}:{urllib.parse.quote(password, safe='')}@{HOST}/{DB}"
               "?authSource=admin&retryWrites=true&w=majority&appName=habita-migration")
    del password
    try:
        for _ in range(30):  # Atlas applies new users within seconds to a minute
            try:
                MongoClient(mig_uri, serverSelectionTimeoutMS=5000).admin.command("ping")
                break
            except Exception:
                time.sleep(5)
        else:
            stop("the temporary user did not become usable in time.")
        print("   temporary user ready")

        step(3, "Fresh backup of habita_ai (read-only) verified against the live database")
        backup_dir = Path.home() / "habita-backups" / f"habita_ai-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
        backup_dir.mkdir(parents=True, mode=0o700)
        app = MongoClient(app_uri(), serverSelectionTimeoutMS=20000, tz_aware=True)
        try:
            export(app, DB, backup_dir)
            manifest = verify_db(app, DB, backup_dir)
        finally:
            app.close()
        print(f"   backup verified in {backup_dir}: "
              + ", ".join(f"{n}={c['count']}" for n, c in sorted(manifest["collections"].items())))

        step(4, "Migration dry run (nothing is changed)")
        plan = asyncio.run(plan_or_apply(mig_uri, apply=False))
        print(f"   floor {plan.floor_before} -> {plan.floor_after}; validator {plan.validator_before}; "
              f"legacy reports to flag {plan.reports_to_flag}; matters {plan.matters_to_flag}")
        if input("   Type APLICAR to apply the migration: ").strip() != "APLICAR":
            stop("not applied (nothing was changed in the data).")

        step(5, "Applying (backup re-verified first; one transaction; audit record)")
        check = MongoClient(mig_uri, serverSelectionTimeoutMS=20000, tz_aware=True)
        try:
            matches_db(check, DB, backup_dir)
        finally:
            check.close()
        import hashlib
        raw = (backup_dir / "manifest.json").read_bytes()
        summary = {"manifest_sha256": hashlib.sha256(raw).hexdigest(), "dir": str(backup_dir),
                   "counts": {n: c["count"] for n, c in manifest["collections"].items()}}
        done = asyncio.run(plan_or_apply(mig_uri, apply=True, backup=summary))
        print(f"   APPLIED: floor stored={done.floor_stored}; flagged reports {done.flagged_reports} "
              f"{done.reports_to_flag}; matters {done.matters_to_flag}; audit {done.audit_id}")
    finally:
        r = run(ATLAS[:1] + ["dbusers", "delete", USER, "--force"] + ATLAS[1:])
        print(f"\n   temporary user deleted: {r.returncode == 0}")

    step(6, f"Access to maps-static-api-key for the original backend ({ORIGINAL_SA}) only")
    if input("   Type SIM to grant it: ").strip() == "SIM":
        r = run(["gcloud", "secrets", "add-iam-policy-binding", "maps-static-api-key", "--project", GCP,
                 f"--member=serviceAccount:{ORIGINAL_SA}", "--role=roles/secretmanager.secretAccessor",
                 "--condition=None", "--format=none"])
        print("   granted" if r.returncode == 0 else f"   not granted: {r.stderr.strip()[:200]}")
    print("\nDone. Tell Claude: feito (it will deploy without traffic, test, then switch traffic).")


if __name__ == "__main__":
    main()
