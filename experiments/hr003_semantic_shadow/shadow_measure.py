"""TD-031 offline: measure MU-9 shadow verdicts (claim atoms with ``enforced=False``) on the acceptance corpus.

Zero cost, no network, no database: drives each automated corpus statement through the same deterministic path as
``tests.mu9_acceptance`` and records, per run, the final outcome and every claim atom's verdict and enforcement.
It never changes a verdict. Run from ``backend/``:

    .venv/bin/python -I ../experiments/hr003_semantic_shadow/shadow_measure.py > ../experiments/hr003_semantic_shadow/shadow_corpus.json
"""
import asyncio
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from app.services.permit.admissibility import render_draft  # noqa: E402
from app.services.permit.citations import reconcile_citations  # noqa: E402
from app.services.permit.verifier import Verifier  # noqa: E402
import tests.mu9_acceptance as A  # noqa: E402
from tests.test_permit_admissibility import TRUSTED, in_section, resolved_state  # noqa: E402
from tests.test_permit_verifier import CHAIN, VERIFIED, Reviewer, checklist, matter  # noqa: E402


async def report_for(text, evidence_set, basis, section):
    cites = A.EVIDENCE_SETS[evidence_set]
    d = render_draft(in_section(section, text, cites, basis=basis), A.RECORDS, matter())
    d = reconcile_citations(d, A.RECORDS, matter(), CHAIN, await TRUSTED.trusted_ids(CHAIN))

    async def state(_m):
        return resolved_state() if "E20" in cites else None
    return await Verifier(Reviewer(VERIFIED), TRUSTED, state).verify(matter(), checklist(), d, A.RECORDS, CHAIN)


async def _none():
    return None


async def main():
    corpus = A.load()
    by_case_class = collections.Counter()
    shadow_kinds = collections.Counter()
    shadow_examples = []
    runs = 0
    for case in corpus["cases"]:
        if case["harness"] != "verifier":
            continue
        for e, b, s in A.expand(case):
            runs += 1
            r = await report_for(case["statement"], e, b, s)
            shadow = [a for a in r.claim_atoms if not a.enforced]
            for a in shadow:
                key = (case["expected"], r.outcome, a.verdict)
                by_case_class[key] += 1
                shadow_kinds[(a.kind, a.verdict, a.reason or "")] += 1
                if a.verdict == "rejected" and r.outcome == "VERIFIED" and len(shadow_examples) < 40:
                    shadow_examples.append({"case": case["id"], "expected": case["expected"], "run": f"{e}/{b}/{s}",
                                            "atom": a.text, "kind": a.kind, "reason": a.reason})
    # Second set: the general planning explanations of the admissibility suite (where shadow verdicts arise).
    from tests.test_permit_admissibility import GENERAL_EXPLANATIONS, REGULATORY_SETS, SECTIONS
    general = collections.Counter()
    for text in GENERAL_EXPLANATIONS:
        for cites in REGULATORY_SETS:
            for b in A.BASES:
                for s in SECTIONS:
                    d = render_draft(in_section(s, text, cites, basis=b), A.RECORDS, matter())
                    d = reconcile_citations(d, A.RECORDS, matter(), CHAIN, await TRUSTED.trusted_ids(CHAIN))
                    r = await Verifier(Reviewer(VERIFIED), TRUSTED, lambda _m: _none()).verify(
                        matter(), checklist(), d, A.RECORDS, CHAIN)
                    sh = [a for a in r.claim_atoms if not a.enforced]
                    general[(r.outcome, "with_shadow_rejected" if any(a.verdict == "rejected" for a in sh)
                             else "no_shadow")] += 1
    out = {
        "general_explanations_runs": {"|".join(k): v for k, v in sorted(general.items())},
        "runs": runs,
        "shadow_atoms_by_expected_outcome_verdict": {"|".join(k): v for k, v in sorted(by_case_class.items())},
        "shadow_atoms_by_kind_verdict_reason": [{"kind": k, "verdict": v, "reason": r, "n": n}
                                                for (k, v, r), n in shadow_kinds.most_common()],
        "shadow_rejected_inside_verified_examples": shadow_examples,
    }
    print(json.dumps(out, indent=1, ensure_ascii=False))


asyncio.run(main())
