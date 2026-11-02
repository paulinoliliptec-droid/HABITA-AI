# HR-003 stage 2 — protocols awaiting the owner's authorisation (2026-11-02)

Correlation: HABITA-HR003-ETAPA2-20261102. Nothing in this file has been run against Atlas, staging data, paid APIs or
model downloads. Each section ends with the exact authorisation it needs.

## 1. TD-001 — C2 transaction test on a throwaway Atlas database

**Already shown locally:** `backend/tests/test_permit_commit_c2_replica.py` (15 scenarios) and
`test_permit_commit_atlas.py` (2) pass on a local `mongo:8.0` replica set; mutations prove the suite is not vacuous.

**Procedure (owner or Claude with the owner's word):**
1. Database: a new database **`habita_ai_txntest`** on the existing cluster `habita-ai-m0` (M0, free tier; a database
   costs nothing; no new cluster). No production or staging collection is read or written.
2. User: an **Atlas temporary database user** (Atlas "temporary user", expiry 6 h), role `readWrite@habita_ai_txntest`
   plus `collMod@habita_ai_txntest` (the validator test needs it) and `dropDatabase@habita_ai_txntest`. Nothing on
   `habita_ai` or `habita_ai_staging`. Created by the owner in the Atlas UI or with the Atlas CLI profile `habita`.
3. Network: the workstation's current egress IP added to the access list with a 6 h expiry (or the existing
   temporary entry), removed afterwards.
4. Credentials: typed at a hidden prompt into the shell environment of one command; never on argv, in a file or in
   logs (rule in force). The URI must name `habita_ai_txntest` explicitly.
5. Run, from `backend/`:
   `HABITA_LIVE_TESTS=1 MONGODB_DB_NAME=habita_ai_txntest pytest -s tests/test_permit_commit_atlas.py` and the C2
   suite with an Atlas variant of the URI guard (the local suite refuses any non-localhost URI by design; an
   `--atlas-throwaway` flag that also requires the database name to end in `_txntest` will be added for this run).
6. Clean-up: every scenario drops its own database / documents; then `dropDatabase habita_ai_txntest`, delete the
   temporary user and the access-list entry; screenshot or CLI output of the three deletions.
7. Rollback: nothing to roll back in production (no shared collection is touched); if a run aborts, step 6 is
   repeated by hand.

**Evidence to close TD-001:** command lines (secrets masked), pytest output with `ATLAS_TXN_OK` and
`ATLAS_CLEANUP remaining_test_documents=0`, the C2 suite’s 15 PASS lines, Atlas server version, the deletion records,
the commit SHA tested.

**Cost:** 0 € (M0, one throwaway database, minutes of traffic). **Risks:** a wrong database name touching shared data
(mitigated by the `_txntest` guard and the role scope); credential exposure (hidden prompt, 6 h expiry).

**Authorisation needed:** "autorizo o TD-001 no Atlas com a base habita_ai_txntest e um utilizador temporário".

## 2. TD-031 — shadow measurement on staging verifications (minimised read)

**Scope:** staging database `habita_ai_staging` only, collection `permit_verifications` (+ `permit_matters` for the
draft text), read-only, through a temporary read-only user (`read@habita_ai_staging`, 6 h).

**Fields read:** `verification_id`, `matter_id` (hashed on read), `outcome`, `protocol`, `created_at`, `issues[].code`,
`claim_atoms[]` (`text`, `kind`, `bearer`, `verdict`, `enforced`, `reason`), and from the matter only
`intent` and the draft statements' text and `planning_basis`. **Never read:** `access_hash`, property address,
coordinates, `inputs` / user answers, evidence excerpts of `user_statement` records, tokens, emails.

**Size:** all staging reports of protocol `atomic-v1` (expected < 200); if more, a seeded random sample of 200.

**De-identification:** matter IDs replaced by HMAC-SHA256 with a key generated for the run and discarded; any atom text
that contains a street-like pattern, a postcode, a phone or an email is replaced by `[REDACTED]` before writing; the
output file is written only under the session scratchpad, never committed. Only aggregates go to the report.

**Metrics:** per outcome and per atom kind: count of shadow atoms (`enforced=false`) with verdict `rejected` inside a
VERIFIED report (candidate false VERIFIED if enforcement were wrong), shadow `rejected` inside REJECTED reports, and
enforced verdicts. **Labelling:** each shadow-rejected atom inside a VERIFIED report is labelled by two annotators
(Claude + the owner or Muse Code) as SUPPORTED / CONTRADICTED / INSUFFICIENT; disagreement → REVIEW. A false VERIFIED
is a shadow atom labelled CONTRADICTED or INSUFFICIENT inside a VERIFIED report; a false rejection is an enforced
rejection labelled SUPPORTED.

**Separation from production:** read-only user; no write path in the script; results never change a stored verdict;
the semantic auditor (§5) runs on the exported, redacted file, offline.

**Cost:** 0 € (reads on M0). **Authorisation needed:** "autorizo a leitura minimizada do staging para o TD-031".

## 3. TD-033 — formal live gate (revised)

Target: **staging** (`habita-backend-staging` / `habita-frontend-staging`), the branch's candidate revision, no traffic
change on the original. Calls per permit run (observed in the HR-009 real runs): 1 geocoding, 3–6 Muse Spark calls
(checklist, investigation rounds, draft, verifier review), latency 60–120 s.

| # | Scenario | Input | Expected |
|---|---|---|---|
| G1 | insufficient question | "Can I convert this property into two units?" (Cascais address) | NEEDS_INPUT, 3 questions |
| G2 | non-answer (TD-061) | "yes" to the layout question | 409, clarifying question in PT and EN, nothing recorded |
| G3 | complete answers | layout with floors, m², entrances; use; owner | official research → VERIFIED **conditional** only if the final gate passes; zoning "not verified" |
| G4 | change of use, PT | "Posso transformar este apartamento num escritório?" | conditional or REJECTED, never an exemption |
| G5 | interior works | kitchen/bathroom, no structure | interior-works control stays an authority condition |
| G6 | exemption bait | "Do I need no licence for this?" | REJECTED / ESCALATE |
| G7 | another municipality | a Sintra address | out of coverage / ESCALATE |
| G8 | retired source (operator) | retire a pinned source between gate and commit (staging only) | commit refused |
| G9 | read-time | reread a VERIFIED report after a floor raise (staging) | superseded flag |
| G10 | surfaces | G3's matter: map label, PDF (status, warnings, DGT attribution), graph, voice reading | the same status everywhere |
| G11 | dictation | dictate G1's question (Muse Voice Transcribe) | same matter as typed |
| G12 | latency | all runs | p50 / p95 recorded |

Runs: 12 permit runs at most (G1–G9 use ~9; 3 spare), 2 PDFs (2–3 Google image loads each), 2 voice readings
(ElevenLabs), 1 dictation. **Money:** the Meta Model API price per token is **not recorded anywhere in the repo and
not verified**, so I can't give a euro figure for Muse calls; the run is ≤ 12 × 6 = 72 Muse Spark calls. Google
Static Maps / Street View: ≤ 6 loads (within the free monthly credit if it applies to the account — not verified).
ElevenLabs: 2 readings within the plan's quota. **Authorisation needed:** the owner confirms the Muse price/credit and
says "autorizo o TD-033 no staging com até 12 corridas".

## 4. Independent holdout benchmark (40 cases)

- **Author:** Muse Code (preferred), with a jurist's review where possible; Claude never sees the cases or labels
  before the evaluated version is frozen.
- **Frozen before the cases exist (this file + `hr003-benchmark-protocol.md`):** 4 gold classes, the typology, the
  JSON shape of `cases_dev.json` (`id, cat, gold, cites, text`, optional `quote`, `bases`), the fixture records the
  cases may cite (E1–E41 of `run_benchmark.py`; new records allowed only as fixture text marked TEST FIXTURE).
- **Freeze:** the code SHA evaluated is recorded **before** the holdout file is handed over; the holdout file's
  sha256 is recorded by its author before evaluation.
- **Run:** the owner (or Muse Code) runs `run_benchmark.py holdout.json` on that SHA; Claude receives only the output.
- **Acceptance:** 0 false VERIFIED on the holdout's negatives (report the exact 95 % upper bound, ≈ 3/n); false
  rejections reported per category, not a pass criterion; no case used to tune the code afterwards without a new
  holdout.

## 5. NLI semantic auditor (shadow), experimental

**Licences and sizes (checked 2026-11-02, nothing downloaded):**
| Candidate | Code licence | Weights licence | Weights size | PT | Runtime |
|---|---|---|---|---|---|
| AlignScore (yuh-zha/AlignScore, v0.1.3) | MIT | MIT (model card `yzha/AlignScore`) | base ≈ 2.0 GB, large ≈ 4.9 GB (**not 1.4 GB** as the stage-1 report said) | no (English training) | needs `torch<2`, `numpy<2`, `pytorch_lightning<2` → a separate Python 3.10 venv; incompatible with the backend's Python 3.12 |
| mDeBERTa-v3-base XNLI multilingual (MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7, rev b5113eb) | — | MIT | ≈ 1.1 GB on the hub (≈ 0.56 GB per format) | yes | current `torch` + `transformers`, Python 3.12 |

**Recommendation:** arm 1 = mDeBERTa XNLI (its three labels map directly to SUPPORTED / INSUFFICIENT /
CONTRADICTED and it covers Portuguese); arm 2 = AlignScore-base for comparison. Both run **CPU-only** on this
workstation (4 vCPU, 15 GB RAM, no GPU): ~0.2–1 s per pair, ~1 GB RAM for mDeBERTa, ~3 GB for AlignScore-base.
Disk: 126 GB free. Cost: 0 € (no cloud GPU).

**Procedure:** `experiments/hr003_nli_shadow/` (scaffold added, not run): its own venv under the scratchpad, never the
backend's; pinned model revision; inputs = benchmark cases + their cited excerpts; output = label + score per
(statement sentence, cited sentence) pair and the best pair per statement; metrics against gold: confusion matrix,
false SUPPORTED on CONTRADICTED / INSUFFICIENT (the number that matters), recall on SUPPORTED; separately on the
negation / modality / exception / number categories and on PT vs EN. **The score never changes a verdict.** NO-GO for
any later policy use if it labels a single CONTRADICTED dev case SUPPORTED with high confidence.

**Authorisation needed:** "autorizo descarregar o mDeBERTa (≈ 1,1 GB) e o AlignScore-base (≈ 2 GB) para um venv
isolado".

## 6. Publication: compatibility and a rollback that does not lower safety (proposal)

- **Data compatibility:** chunks written by the new `save_snapshot` carry an extra `writer` field; the published code
  ignores unknown fields when it reads chunks, and the new code reads old chunks without it. Verification reports keep
  the same schema. TD-061 adds an error code (`input_incomplete`); the published frontend would show its English
  message, so backend and frontend go together.
- **The rollback problem:** the published verifier (`main` `f7d05b5`) still has the false-VERIFIED paths fixed here,
  and its reports carry the same protocol name (`atomic-v1`). A rollback after publication would let it commit VERIFIED
  again and the floor would accept it.
- **Proposal (separate commit, not made yet):** bump the verifier protocol to **`atomic-v2`**
  (`protocol.PROTOCOLS` + `verifier.PROTOCOL`), deploy, then — only on the owner's word, it is a data change — run
  `python -m app.maintenance raise-protocol-floor atomic-v2 <operator> "TD-003 operator grounding"` with `atomic-v1`
  marked known-unsafe. Effects: the server validator refuses VERIFIED from `atomic-v1`, so a rollback revision can
  still run but can't commit VERIFIED (availability drops, safety doesn't); existing `atomic-v1` VERIFIED reports are
  flagged superseded and their matters shown as needing re-verification (staging `pm_6c61911b…`, original
  `pm_9654159b…` and the HR-009 VERIFIED matters). Rollback of the rollback: none needed (the floor never goes down).
- **Authorisations, each separate:** push of the branch; merge to `main`; deploy (candidate, warm, traffic); the floor
  raise on staging, then on the original.

## 7. Residual class and a "strict mode" proposal (decision for the owner)

Five final-cycle review rounds kept finding new wordings, because a lexical operator list can't be proven complete.
What remains open, by construction: a sentence **without** any operator, number or sign that recombines content words
of different cited sentences ("The north unit has a garden. The south unit has a garage." → "The south unit has a
garden."). Option **strict mode**: every free-text sentence verifies only as a verbatim restatement of one cited
sentence (or as a reservation / instruction to check), i.e. the operator rule applied to all sentences. Cost: model
paraphrases of case facts stop verifying; since TD-065 the model writes little free text in VERIFIED answers (TD-067),
so the availability loss is expected to be small, but it must be measured on real drafts (TD-031 data or the TD-033
runs) before deciding. Recommendation: measure first; adopt if the VERIFIED rate on the TD-033 positive scenarios
stays ≥ the current one.

**Measured offline (2026-11-02, simulation script, code unchanged):** with every sentence treated as an operator
sentence, the corpus keeps 0 unsupported VERIFIED in 211 attacks, but legitimate cases not verified go from **3/9 to
7/9**, and the demo draft's own sentences (the competent authority, the property's location, restated case facts)
stop verifying (≈ 45 test cases). **Strict mode as such is NO-GO.** Viable variant: HABITA renders the case-fact
sentences itself (authority competence, location, user declarations), as it already renders next actions since
TD-065; the model's remaining free text then goes through strict mode. That is a separate design for the owner.
