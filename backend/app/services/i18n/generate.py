"""Build the Portuguese catalogs of the fixed texts with Google Translate.

    python -m app.services.i18n.generate

Fixed texts are the literals in ``t("…")`` and ``msg("…")`` calls in the backend and the frontend. They are translated
once and kept in the repository, so a demo depends on no network for them and the cost is paid once: only new texts
call the service. ``pinned.json`` (statuses, warnings, the disclaimer) always wins and is never sent. A text that fails
``fidelity_problems`` is left out and listed: pin it by hand. Exits non-zero while any text has no entry.
"""

import ast
import asyncio
import json
import re
import sys
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.integrations.translate.client import GoogleTranslateClient
from app.services.i18n.translator import HERE, PINNED, TARGET, _decode, _encode, fidelity_problems

BACKEND = HERE.parents[1]
FRONTEND = HERE.parents[3] / "frontend" / "src"
FRONTEND_CATALOG = FRONTEND / "i18n" / "pt.json"
_js_call = re.compile(r'(?<![\w.])(?:t|msg)\(\s*"((?:[^"\\]|\\.)*)"')


def backend_texts() -> set[str]:
    found: set[str] = set()
    for path in BACKEND.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("t", "msg")
                    and node.args):
                found |= {c.value for c in ast.walk(node.args[0])
                          if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    return found - {""}


def frontend_texts() -> set[str]:
    found: set[str] = set()
    for path in FRONTEND.rglob("*.ts*"):
        if ".test." not in path.name:
            found |= {json.loads(f'"{m}"') for m in _js_call.findall(path.read_text(encoding="utf-8"))}
    return found


async def _translate(texts: list[str], client: GoogleTranslateClient) -> tuple[dict[str, str], dict[str, list[str]]]:
    out, failed = {}, {}
    raw = await client.translate([_encode(t) for t in texts], TARGET["pt"])
    for source, translated in zip(texts, raw, strict=True):
        text = _decode(translated)
        if problems := fidelity_problems(source, text):
            failed[source] = problems
        else:
            out[source] = text
    return out, failed


async def main() -> int:
    settings = get_settings()
    if not settings.google_translate_api_key:
        raise SystemExit("GOOGLE_TRANSLATE_API_KEY is not set.")
    backend, frontend = backend_texts(), frontend_texts()
    path = HERE / "pt.json"
    known = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    known |= {k: v for k, v in (json.loads(FRONTEND_CATALOG.read_text(encoding="utf-8")).items()
                                if FRONTEND_CATALOG.exists() else ()) if k not in PINNED}
    new = sorted((backend | frontend) - set(PINNED) - set(known))
    async with httpx.AsyncClient() as http:
        client = GoogleTranslateClient(http, settings.google_translate_api_key.get_secret_value(),
                                       timeout_seconds=60, rate_per_minute=600, burst=100, daily_limit=100)
        added, failed = await _translate(new, client) if new else ({}, {})
    known |= added
    path.write_text(json.dumps({k: known[k] for k in sorted(backend & set(known))}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    FRONTEND_CATALOG.parent.mkdir(exist_ok=True)
    merged = known | PINNED
    FRONTEND_CATALOG.write_text(json.dumps({k: merged[k] for k in sorted((frontend & set(merged)) | set(PINNED))}, ensure_ascii=False,
                                           indent=2) + "\n", encoding="utf-8")
    print(f"{len(new)} new, {len(added)} translated, {len(failed)} to pin by hand")
    for source, problems in failed.items():
        print(f"  {problems}: {source}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
