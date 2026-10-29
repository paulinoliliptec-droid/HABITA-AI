"""MU-9 acceptance corpus (Phase 0): loader, offline runner and metrics.

The corpus (``tests/data/mu9_acceptance.json``) is data, not code. Every case records its exact statement (or
``null`` with ``wording: "UNAVAILABLE"``), provenance, evidence sets, bases, sections, the builder's classification,
the expected outcome and what the code under test actually did.

The runner drives each statement through ``render_draft → reconcile_citations → Verifier`` with an always-approving
Reviewer, so a VERIFIED here can only come from HABITA's deterministic checks. The fixtures are self-contained, so
the corpus runs the same against ``98af6af`` and against any later tree.

    python -m tests.mu9_acceptance                      # metrics for the current tree
    python -m tests.mu9_acceptance --write-observed KEY # record observations under ``observed[KEY]``
    python -m tests.mu9_acceptance --promote            # open cases that now pass become closed (never the reverse)
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from app.services.permit.admissibility import render_draft
from app.services.permit.citations import reconcile_citations
from app.services.permit.verifier import Verifier
from tests.test_permit_admissibility import (
    ADDRESS, CENTRAL, SECTIONS, TRUSTED, in_section, planning, record, resolved_state, rjue,
)
from tests.test_permit_verifier import CHAIN, VERIFIED, Reviewer, checklist, matter

CORPUS = Path(__file__).parent / "data" / "mu9_acceptance.json"
BASES = ("none", "general_planning_explanation")

# --- Fixtures (texts identical to the HR-003 live-run records used by Codex, Muse and the builder) ------------------
E2 = record("E2", "jurisdiction_record",
            "Country: Portugal → District: Lisboa → Municipality: Cascais → Parish: União das freguesias "
            "de Cascais e Estoril", status="system_record", title="HABITA jurisdiction resolution",
            structured={"levels": [{"name": "Portugal"}, {"name": "Lisboa"}, {"name": "Cascais"},
                                   {"name": "União das freguesias de Cascais e Estoril"}]})
E3 = record("E3", "authority_record", "Câmara Municipal de Cascais: Licensing of urban operations, including "
            "building permits (licenciamento urbanístico).", status="system_record", title="Câmara Municipal de Cascais")
E13 = record("E13", "regulatory_source",
             "Artigo 120.º Dotação de estacionamento 1 - Nas operações urbanísticas de edificação, incluindo "
             "obras de ampliação e alteração de uso, sujeitas a licenciamento ou comunicação prévia, deve ser "
             "assegurada a dotação de estacionamento.", source="cascais-pdm", basis="official_text",
             authority_class="municipal_instrument", title="PDM-Cascais — Regulamento", status="official_text")
E18 = record("E18", "user_statement", "TEST DATA: licensed as one single-family dwelling (habitação).",
             status="user_declared", title="Answer to: What is the property's currently licensed use?")
E20 = planning("E20", status="resolved", classification=CENTRAL)
#: Synthetic official passage with a numeric limit and an exception (no real Cascais article says this).
E30 = record("E30", "regulatory_source",
             "Artigo 900.º Ampliação 1 - Nas moradias unifamiliares com área de construção até 200 m2, "
             "é admitida a ampliação até 20 % da área existente, exceto em edifícios classificados.",
             source="cascais-pdm", basis="official_text", authority_class="municipal_instrument",
             title="PDM-Cascais — Regulamento (TEST FIXTURE)", status="official_text")
E1 = rjue("E1")
RECORDS = [E2, E3, E13, E18, E20, E30, ADDRESS, planning("E4"), E1]

EVIDENCE_SETS = {
    "pdm": ["E13"], "auth": ["E3"], "auth+pdm": ["E3", "E13"], "none": [], "user": ["E18"],
    "user+pdm": ["E18", "E13"], "law": ["E1"], "auth+law": ["E3", "E1"], "parcel": ["E20"],
    "parcel+pdm": ["E20", "E13"], "loc": ["E2"], "num": ["E30"],
}
ALL_SETS = [name for name in EVIDENCE_SETS if name != "num"]


def load() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def expand(case: dict) -> list[tuple[str, str, str]]:
    """(evidence set, basis, section) runs of an automated case."""
    sets = ALL_SETS if case["evidence_sets"] == ["*"] else case["evidence_sets"]
    sections = SECTIONS if case["sections"] == ["*"] else case["sections"]
    bases = BASES if case["bases"] == ["*"] else case["bases"]
    return [(e, b, s) for e in sets for b in bases for s in sections]


async def outcome(text: str, evidence_set: str, basis: str, section: str) -> str:
    cites = EVIDENCE_SETS[evidence_set]
    d = render_draft(in_section(section, text, cites, basis=basis), RECORDS, matter())
    d = reconcile_citations(d, RECORDS, matter(), CHAIN, await TRUSTED.trusted_ids(CHAIN))

    async def state(_matter):
        return resolved_state() if "E20" in cites else None
    report = await Verifier(Reviewer(VERIFIED), TRUSTED, state).verify(matter(), checklist(), d, RECORDS, CHAIN)
    return report.outcome


async def observe(case: dict) -> dict:
    """Which runs ended VERIFIED, and how long the deterministic pipeline took."""
    runs = expand(case)
    started = time.perf_counter()
    verified = [f"{e}/{b}/{s}" for e, b, s in runs if await outcome(case["statement"], e, b, s) == "VERIFIED"]
    elapsed = time.perf_counter() - started
    return {"runs": len(runs), "verified": len(verified), "verified_runs": verified,
            "ms_per_run": round(1000 * elapsed / max(len(runs), 1), 2)}


def passes(case: dict, seen: dict) -> bool:
    """REJECTED: no run may verify. VERIFIED: every run must verify."""
    if case["expected"] == "REJECTED":
        return seen["verified"] == 0
    return seen["verified"] == seen["runs"]


async def metrics(corpus: dict) -> tuple[dict, dict]:
    observed, per_group = {}, {}
    attacks = legit = false_pos = false_neg = 0
    latency = []
    for case in corpus["cases"]:
        group = per_group.setdefault(case["group"], {"cases": 0, "automated": 0, "failing": 0})
        group["cases"] += 1
        if case["harness"] != "verifier":
            continue
        seen = await observe(case)
        observed[case["id"]] = seen
        group["automated"] += 1
        latency.append(seen["ms_per_run"])
        ok = passes(case, seen)
        group["failing"] += not ok
        if case["expected"] == "REJECTED":
            attacks += 1
            false_pos += not ok
        else:
            legit += 1
            false_neg += not ok
    total = len(corpus["cases"])
    automated = sum(g["automated"] for g in per_group.values())
    summary = {
        "cases": total, "automated": automated, "coverage": round(automated / total, 3),
        "attack_cases": attacks, "unsupported_verified_cases": false_pos,
        "legit_cases": legit, "legit_not_verified_cases": false_neg,
        "ms_per_run_mean": round(sum(latency) / max(len(latency), 1), 2), "ms_per_run_max": max(latency, default=0),
        "groups": per_group,
    }
    return summary, observed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-observed", metavar="KEY")
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()
    corpus = load()
    summary, observed = asyncio.run(metrics(corpus))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    for case in corpus["cases"]:
        if case["id"] not in observed:
            continue
        seen = observed[case["id"]]
        if args.write_observed:
            case.setdefault("observed", {})[args.write_observed] = {
                "verified": seen["verified"], "runs": seen["runs"], "verified_runs": seen["verified_runs"][:12],
                "passes": passes(case, seen)}
        if args.promote and case["status"] == "open" and passes(case, seen):
            case["status"] = "closed"
            print("promoted", case["id"])
    if args.write_observed or args.promote:
        CORPUS.write_text(json.dumps(corpus, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
