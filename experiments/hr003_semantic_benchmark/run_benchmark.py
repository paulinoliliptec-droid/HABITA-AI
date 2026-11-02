"""HR-003 semantic benchmark (dev split): the UNCHANGED MU-9 verifier against 4-class gold labels.

Zero cost: no network, no database, no model (the reviewer always approves, so a VERIFIED can only come from
HABITA's deterministic checks, as in ``tests.mu9_acceptance``). Never changes a verdict. Run from ``backend/``:

    .venv/bin/python -I ../experiments/hr003_semantic_benchmark/run_benchmark.py [cases.json] > results.json
"""
import asyncio
import collections
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

import tests.mu9_acceptance as A  # noqa: E402
from app.services.permit.admissibility import render_draft  # noqa: E402
from app.services.permit.citations import reconcile_citations  # noqa: E402
from app.services.permit.verifier import Verifier  # noqa: E402
from tests.test_permit_admissibility import SECTIONS, TRUSTED, civil, in_section, record, resolved_state  # noqa: E402
from tests.test_permit_verifier import CHAIN, VERIFIED, Reviewer, checklist, matter  # noqa: E402

HERE = Path(__file__).parent
#: Benchmark-only records (synthetic; no real Sintra article or blog says this).
E40 = record("E40", "regulatory_source", "Em solo urbano é admitida a construção de moradias unifamiliares.",
             source="sintra-pdm", basis="official_text", authority_class="municipal_instrument",
             jurisdiction="pt/lisboa/sintra", title="PDM-Sintra — Regulamento (TEST FIXTURE)", status="official_text")
E41 = record("E41", "regulatory_source", "Interior works never need a licence in Cascais.", source="blog-obras",
             basis="curated_reference", title="Blog de obras (TEST FIXTURE)")
RECORDS = [*A.RECORDS, civil("E7"), E40, E41]
SETS = {**A.EVIDENCE_SETS, "civil": ["E7"], "sintra": ["E40"], "blog": ["E41"]}


async def outcome(text, cites, basis, section, quote=None):
    ids = SETS[cites]
    d = render_draft(in_section(section, text, ids, basis=basis, quote=quote), RECORDS, matter())
    d = reconcile_citations(d, RECORDS, matter(), CHAIN, await TRUSTED.trusted_ids(CHAIN))

    async def state(_m):
        return resolved_state() if "E20" in ids else None
    report = await Verifier(Reviewer(VERIFIED), TRUSTED, state).verify(matter(), checklist(), d, RECORDS, CHAIN)
    return report.outcome, sorted({i.code for i in report.issues})


def upper95_zero(n):
    """Exact one-sided 95 % upper bound on a rate when 0 events were seen in n trials (≈ 3/n)."""
    return round(1 - 0.05 ** (1 / n), 4) if n else None


async def main(path):
    corpus = json.loads(Path(path).read_text(encoding="utf-8"))
    rows, confusion = [], collections.Counter()
    per_cat = collections.defaultdict(lambda: {"n": 0, "false_verified": 0, "false_rejected": 0})
    for case in corpus["cases"]:
        runs = [(b, s, None) for b in case.get("bases", A.BASES) for s in SECTIONS]
        if case.get("quote"):
            runs += [("general_rule", s, case["quote"]) for s in SECTIONS]
        seen = [await outcome(case["text"], case["cites"], b, s, q) for b, s, q in runs]
        quote_verified = sum(o == "VERIFIED" for (o, _), (b, _s, _q) in zip(seen, runs) if b == "general_rule")
        verified = sum(o == "VERIFIED" for o, _ in seen)
        predicted = "VERIFIED" if verified == len(runs) else "PARTIAL" if verified else "NOT_VERIFIED"
        supported = case["gold"] == "SUPPORTED_CONDITIONAL"
        false_verified = (not supported) and verified > 0
        # A supported rule is correctly handled if it verifies through the literal-quote path (MU-9 design: normative
        # content is never verified as free text); without a quote, every run must verify.
        false_rejected = supported and (quote_verified < len(SECTIONS) if case.get("quote") else verified < len(runs))
        confusion[(case["gold"], predicted)] += 1
        c = per_cat[case["cat"]]
        c["n"] += 1
        c["false_verified"] += false_verified
        c["false_rejected"] += false_rejected
        rows.append({"id": case["id"], "cat": case["cat"], "gold": case["gold"], "predicted": predicted,
                     "verified_runs": f"{verified}/{len(runs)}",
                     "quote_path_verified": f"{quote_verified}/{len(SECTIONS)}" if case.get("quote") else None, "false_verified": false_verified,
                     "false_rejected": false_rejected, "mr_of": case.get("mr_of"),
                     "issue_codes": sorted({code for _, codes in seen for code in codes})})
    negatives = [r for r in rows if r["gold"] != "SUPPORTED_CONDITIONAL"]
    positives = [r for r in rows if r["gold"] == "SUPPORTED_CONDITIONAL"]
    fv = sum(r["false_verified"] for r in negatives)
    summary = {
        "corpus": corpus["version"], "cases": len(rows), "runs_per_case": f"up to {2 * len(SECTIONS)} free-text (+{len(SECTIONS)} literal-quote when the case has a quote)",
        "negatives": len(negatives), "false_verified_cases": fv,
        "false_verified_upper95_if_zero": upper95_zero(len(negatives)) if fv == 0 else None,
        "positives": len(positives), "false_rejected_cases": sum(r["false_rejected"] for r in positives),
        "coverage_positives_fully_verified": round(sum(not r["false_rejected"] for r in positives)
                                                   / max(len(positives), 1), 3),
        "confusion": {f"{g}->{p}": n for (g, p), n in sorted(confusion.items())},
        "per_category": dict(per_cat),
        "metamorphic_pairs_direction_ok": sum(1 for r in rows if r["mr_of"] and not r["false_verified"]
                                              and r["gold"] != "SUPPORTED_CONDITIONAL"),
        "annotation": corpus["annotation"],
    }
    print(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False))


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else HERE / "cases_dev.json"))
