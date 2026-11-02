# HR-003 decision matrix (2026-11-01)

Rule that never changes: no new model, NLI score or LLM judge can promote a statement to VERIFIED. MU-9's
deterministic rules and final gate decide; anything new can only tighten (reject or escalate) after it is proven.

| Option | What | Evidence so far | Cost | Risk | Recommendation |
|---|---|---|---|---|---|
| **A — baseline MU-9** (+ TD-003 fixes) | current rules, final gate, TrustPin, C2 binding, atomic-v1 floor | corpus 294: 0 unsupported VERIFIED (211 attack cases), 3 known legit not verified; dev benchmark 40: 0 false VERIFIED on 32 negatives; C2 replica set 14/14 | none | availability loss: translations, inferences ("without its own exit…"), curated sources can't verify free-text rules | **GO** (keep) |
| **B — Semantic Evidence Auditor, SHADOW** | per-atom NLI/alignment score (SUPPORTS / CONTRADICTS / INSUFFICIENT) recorded next to the verdict, never deciding | none yet (not run) | local model download (AlignScore-large ≈ 1.4 GB weights, torch in a separate venv), CPU/GPU time; no paid API | English-trained models on PT-PT text; licence of weights to confirm; supply chain of old torch pins | **PROPOSED**, needs owner decision to download and run in an isolated venv; then measured on dev + holdout; NO-GO if any false "SUPPORTS" on a CONTRADICTED case it would be used to flag |
| **C — Evidence graph / proof-carrying assessment** | norm → version → article → exception → condition → parcel → authority, revalidated before commit | design reference only (SAT-Graph API, qualitative PoC) | large | new production service, schema migration | **NO-GO now**; research note only, after the contest |

## Patches of this stage
| Patch | Decision | Evidence |
|---|---|---|
| TD-003 a: a restriction ("only/apenas/exceto…") no longer grounds a negation | GO (local, not pushed) | Codex r1 P1 repro → red test → green; corpus unchanged |
| TD-003 b: a negation is grounded only by one cited sentence holding the same negation and every content word | GO (local, not pushed) | Codex r2 P1 repro → red test → green |
| TD-003 c: "without", "sem", "neither" are negations | GO (local, not pushed) | Codex r2 P1 repro |
| TD-003 d: `save_snapshot` never deletes chunks of an overlapping same-ID call; BulkWriteError handled; returns the stored snapshot only if content matches | GO (local, not pushed) | Codex r1/r2 repro on a real mongo:8.0 replica set: 0 chunks before, 3 after |
| TD-061 typed structural answers ("yes" for floors/area) | NEXT (Phase 3), not started | — |
| Removing refused sentences (TD-066) | NO-GO (unchanged: opens false VERIFIED) | `.ai-review/patches/…rejected-design.patch` |

## Known cost of the fixes (fail-closed)
"Without its own exit, a unit can't be in horizontal property" (a correct inference from the Código Civil record)
no longer verifies. Recorded as dev case D38 (restriction_complement_inference, false REJECTED) for TD-045.
