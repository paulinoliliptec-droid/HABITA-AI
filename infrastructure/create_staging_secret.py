"""Create the staging secret mongodb-uri-staging from a password typed at a hidden prompt.

Run once, by the project owner, in an interactive terminal, from the repository root:

    backend/.venv/bin/python infrastructure/create_staging_secret.py

The password is read with getpass from the terminal and stays in this process's memory: it never appears on a
command line (argv), in the environment, a file, the shell history, a log or this program's output, errors included.
Before anything is created, the URI is checked against Atlas: its user must be habita-staging-app, holding
application privileges on habita_ai_staging only (the rule the backend applies at startup, app.db.staging). The URI
then reaches Secret Manager on gcloud's stdin, with gcloud's HTTP and file logging off. The secret is created first,
empty, then given its version; an existing secret is never replaced: its metadata is shown and nothing changes, except
that an existing env=staging secret with no version at all (a run interrupted between the two steps) can receive its
first version after you type "add". Exit codes: 0 done, 1 stopped, 2 the secret already exists (nothing changed).
"""

import getpass
import json
import os
import subprocess
import sys
import urllib.parse
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db.staging import confinement_problem  # noqa: E402

PROJECT = "habita-ai-512916"
ACCOUNT = "paulinoliliptec@gmail.com"
SECRET = "mongodb-uri-staging"
USER = "habita-staging-app"
HOST = "habita-ai-m0.mhbehnn.mongodb.net"  # cluster habita-ai-m0: atlas clusters connectionStrings describe
DB = "habita_ai_staging"


class Stop(Exception):
    pass


# Settings, not secrets: keep the request that carries the URI out of gcloud's HTTP log and log files.
QUIET_GCLOUD = {"CLOUDSDK_CORE_LOG_HTTP": "false", "CLOUDSDK_CORE_DISABLE_FILE_LOGGING": "true"}


def gcloud(*args: str, data: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["gcloud", f"--project={PROJECT}", *args], input=data, capture_output=True, text=True,
                          env={**os.environ, **QUIET_GCLOUD})


def build_uri(password: str) -> str:
    quote = lambda value: urllib.parse.quote(value, safe="")  # noqa: E731
    return (f"mongodb+srv://{quote(USER)}:{quote(password)}@{HOST}/{DB}"
            "?authSource=admin&retryWrites=true&w=majority&appName=habita-staging")


def check_user(uri: str, timeout_ms: int = 15000) -> str | None:
    """Why the URI's user is not habita-staging-app confined to habita_ai_staging, or None. Reads only."""
    from pymongo import MongoClient

    try:
        with MongoClient(uri, serverSelectionTimeoutMS=timeout_ms) as client:
            info = client.admin.command({"connectionStatus": 1, "showPrivileges": True})["authInfo"]
    except Exception as exc:  # driver messages can quote the URI: report the type only
        return f"cannot authenticate to {HOST} as {USER} ({type(exc).__name__})."
    users = [u.get("user") for u in info.get("authenticatedUsers", [])]
    if users != [USER]:
        return f"authenticated as {users}, expected [{USER!r}]."
    return confinement_problem(info, DB)


def existing_secret() -> tuple[dict, str] | None:
    """The secret's metadata and version list if it exists (never a version's content), None if it does not."""
    found = gcloud("secrets", "describe", SECRET, "--format=json")
    if found.returncode != 0:
        if "NOT_FOUND" in found.stderr:
            return None
        raise Stop(f"cannot read the secret's metadata: {found.stderr.strip()}")
    versions = gcloud("secrets", "versions", "list", SECRET, "--format=value(name.basename(),state,createTime)")
    if versions.returncode != 0:
        raise Stop(f"cannot list the secret's versions: {versions.stderr.strip()}")
    return json.loads(found.stdout), versions.stdout.strip()


def read_password() -> str:
    if not sys.stdin.isatty():
        raise Stop("run this in an interactive terminal: the password is read at a hidden prompt.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)  # never fall back to an echoing prompt
        try:
            password = getpass.getpass(f"Password for {USER} (hidden): ")
        except getpass.GetPassWarning:
            raise Stop("the terminal cannot hide input.") from None
    if not password:
        raise Stop("empty password.")
    return password


def main() -> int:
    try:
        account = subprocess.run(["gcloud", "config", "get-value", "account"], capture_output=True, text=True)
        if account.stdout.strip() != ACCOUNT:
            raise Stop(f"gcloud is signed in as {account.stdout.strip() or '(nobody)'}, expected {ACCOUNT}.")
        existing = existing_secret()
        if existing is not None:
            meta, versions = existing
            print(f"Secret {SECRET} already exists: created={meta.get('createTime')} labels={meta.get('labels', {})}\n"
                  f"versions:\n{versions or '(none)'}")
            resumable = not versions and meta.get("labels", {}).get("env") == "staging"
            if not resumable or input('It has no version. Type "add" to give it its first version: ') != "add":
                print("Nothing changed.")
                return 2
        uri = build_uri(read_password())
        problem = check_user(uri)
        if problem:
            raise Stop(problem)
        if existing is None:
            created = gcloud("secrets", "create", SECRET, "--replication-policy=automatic", "--labels=env=staging")
            if created.returncode != 0:
                raise Stop(f"gcloud could not create the secret: {created.stderr.strip()}")
        else:  # resuming: someone may have added a version since the listing above
            again = existing_secret()
            if again is None or again[1]:
                raise Stop("the secret changed while you typed (it now has a version or is gone).")
        added = gcloud("secrets", "versions", "add", SECRET, "--data-file=-", data=uri)
        del uri
        if added.returncode != 0:  # its stderr is withheld: an error message could quote part of the input
            print(f"STOP: the secret exists but has no version (gcloud versions add exited {added.returncode}; its "
                  "output is withheld). Check access with `gcloud secrets versions list`, then run the script again.",
                  file=sys.stderr)
            return 1
        enabled = gcloud("secrets", "versions", "list", SECRET, "--filter=state:ENABLED",
                         "--format=value(name.basename(),createTime)")
        if enabled.returncode != 0 or not enabled.stdout.strip():
            print(f"STOP: a version was added but its state could not be confirmed: {enabled.stderr.strip()}",
                  file=sys.stderr)
            return 1
        print(f"{SECRET} ready (user {USER}, cluster habita-ai-m0, database {DB}); enabled versions:\n"
              f"{enabled.stdout.strip()}")
        return 0
    except Stop as stop:
        print(f"STOP: {stop} Nothing was created or changed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
