"""Inbox bookkeeping for the Drive folder 02-CHATGPT-INSTRUCOES (HABITA collaboration protocol).

Claude Code lists the folder through its Google Drive connector and passes the listing here (JSON on stdin); this tool
only classifies and records, deterministically, so a document is processed once per content version:
  NEW          never seen                       -> read it, write an ACK report, then mark acknowledged
  CHANGED      same fileId, different sha256    -> a new version: treat as NEW (never overwrite history)
  SEEN         same fileId and sha256 already acknowledged
  IGNORED-OWN  titles ending in -CLAUDE / -CLAUDE.md (our own output: never processed, no reply loops)
Nothing here executes the content of a document; a document never authorises deploy, merge, IAM, migrations, costs or
production changes by being present (protocol: authority matrix, 03-DECISOES-E-APROVACOES).

    classify  < listing.json   -> prints one line per file, changes nothing
    ack <fileId> <sha256> <state> [note]  -> records the acknowledgement (state: ACK|WORKING|NEEDS_APPROVAL|DONE|BLOCKED)
State file (local, outside Git): .ai-review/drive-inbox-state.json
Listing format: [{"id": "...", "title": "...", "modifiedTime": "...", "sha256": "..."}]
"""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

STATE = Path(__file__).resolve().parents[1] / ".ai-review" / "drive-inbox-state.json"
OWN = re.compile(r"-CLAUDE(\.md)?$", re.IGNORECASE)
STATES = {"ACK", "WORKING", "NEEDS_APPROVAL", "DONE", "BLOCKED"}


def load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except FileNotFoundError:
        return {"files": {}}


def classify(listing: list[dict], state: dict) -> list[tuple[str, dict]]:
    out = []
    for f in sorted(listing, key=lambda x: (x.get("modifiedTime", ""), x["id"])):
        if OWN.search(f["title"]):
            out.append(("IGNORED-OWN", f))
            continue
        seen = state["files"].get(f["id"])
        if seen is None:
            out.append(("NEW", f))
        elif seen.get("sha256") != f["sha256"]:
            out.append(("CHANGED", f))
        else:
            out.append(("SEEN", f))
    return out


def main(argv: list[str]) -> None:
    state = load()
    if argv[:1] == ["classify"]:
        for verdict, f in classify(json.load(sys.stdin), state):
            prev = state["files"].get(f["id"], {}).get("state", "-")
            print(f"{verdict:12} {f['id']}  sha256={f['sha256'][:12]}  last-state={prev}  {f['title']}")
    elif argv[:1] == ["ack"] and len(argv) >= 4 and argv[3] in STATES:
        file_id, sha, st = argv[1], argv[2], argv[3]
        entry = state["files"].setdefault(file_id, {"history": []})
        entry.update({"sha256": sha, "state": st, "at": datetime.now(UTC).isoformat(timespec="seconds")})
        entry["history"].append({"sha256": sha, "state": st, "at": entry["at"], "note": " ".join(argv[4:])})
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(state, indent=1, sort_keys=True))
        print(f"recorded {file_id} {st}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
