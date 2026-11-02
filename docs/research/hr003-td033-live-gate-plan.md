# TD-033 — formal pre-demo live gate: plan (NOT RUN; needs the owner's specific approval and budget)

Target: the **staging** pair first, then the original only on the owner's word. Each run is a paid Muse Spark call
(drafter + verifier review) plus Google geocoding; budget to approve: **≤ 12 permit runs** (≈ 6 positive, 6 negative).

| # | Flow | Expected | Evidence to capture |
|---|---|---|---|
| G1 | Cascais address, change of use → NEEDS_INPUT | missing keys listed, nothing VERIFIED | matter id, state, checklist |
| G2 | answer the inputs (typed values) → official research → assessment | VERIFIED **conditional** only if the final gate passes; zoning "not verified" shown | report id, protocol atomic-v1, trust_pin, claim_atoms |
| G3 | same with an answer "yes" to floors/area | today accepted as a user declaration (TD-061); record the behaviour | — |
| G4 | negative: exemption question ("no licence needed?") | REJECTED or ESCALATE, never VERIFIED | issues |
| G5 | negative: another municipality's address | inapplicable / escalate | issues |
| G6 | negative: source retired between gate and commit (staging only, operator action) | commit refused, re-run | logs |
| G7 | read-time: VERIFIED report reread after a floor raise | superseded flag shown | API JSON |
| G8 | browser: map label, PDF (status, warnings, DGT attribution), graph, voice reading of the status | same status everywhere | screenshots / PDF |
| G9 | latency | p50/p95 of the continue call | timings |

Pass: no VERIFIED outside G2; every surface shows the same status; no secret in logs/PDF. Fail: HR-003 stays
IN PROGRESS; the demo is limited to the scenes already shown to work.
