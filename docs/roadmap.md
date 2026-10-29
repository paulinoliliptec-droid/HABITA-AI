# HABITA AI — Global roadmap (HR-001 … HR-015)

Consolidated from approved definitions only: the review files in `.ai-review/reviews/` (scope and outcome of each
milestone) and `docs/architecture.md`. **Nothing here invents a requirement.** Where a milestone has no approved
definition or acceptance criteria, it is marked **PENDING DEFINITION** until the owner provides it.

Progress is counted on milestones with a formal outcome on the review board. MU-9 phases (HR-003's verification work)
are not global milestones.

## Status

| ID | Milestone | Approved scope (source) | Acceptance criteria | Status |
|---|---|---|---|---|
| HR-001 | Property Location & Jurisdiction Foundation | address → Google Maps → geocoding → jurisdiction resolution → property workspace: design system and app shell; Places autocomplete; `POST /api/property/resolve-location`, `GET /api/property/{id}`; jurisdiction abstraction (Portugal adapter + generic fallback); property persistence (MongoDB + in-memory); workspace with map, jurisdiction hierarchy and competent authority (`reviews/HR-001-…`) | review HR-001: Codex ACCEPTED, Muse ACCEPTED, round 5 | **DONE** (RESOLVED, 2026-10-27) |
| HR-002 | Meta-powered Permit Intelligence Foundation | first agentic workflow GOAL → CHECKLIST → TOOLS → EVIDENCE → DRAFT → INDEPENDENT VERIFICATION → FINAL STATE on Muse Spark: persisted states and resume, structured tools, evidence model, regulatory-source abstraction (curated PT/Cascais), independent verifier, MongoDB, API, Permit section (`reviews/HR-002-…`) | review HR-002: Codex ACCEPTED, Muse ACCEPTED | **DONE** (RESOLVED / CLOSED, `main` @ `c556334`) |
| HR-003 | Official Sources, Zoning & Regulatory Retrieval Foundation | coordinates → jurisdiction → official source registry → planning context → provenance-bearing evidence → Permit workflow, **Cascais only**; owner decisions of 2026-10-28 (manual confirmation without a validated connector; `pypdf`, no OCR; initial trusted corpus) (`reviews/HR-003-…`, `plans/HR-003-official-sources-plan.md`); MU-9 structural verification as its follow-up (`plans/HR-003-MU9-final-candidate.md`) | see below | **IN PROGRESS** |
| HR-004 … HR-015 | — | **PENDING DEFINITION** (no approved scope in the repository) | **PENDING** | not started |

### HR-003 acceptance status

| Criterion (approved source) | Status | Evidence |
|---|---|---|
| Official source registry, trust lifecycle, SafeFetcher, PDF snapshots, jurisdiction-aware retrieval, planning context with manual-confirmation fallback | met (integrated in `main` @ `98af6af`) | review HR-003 rounds 1–7 |
| CX-1, CX-2 assessment integrity | met | review HR-003; `test_permit_trust_commit.py`, `test_permit_commit_durability.py` |
| MU-9 Phase 1: atomic legal claims, capability model, enforcement; acceptance corpus 0 unsupported VERIFIED | met offline, operationally closed | `.ai-review/reviews/HR-003-MU9-phase-1-operational-closure.md`; corpus 294 cases |
| MU-9 Phase 2: C2 identity binding (ACC-BIND), FP-3/FP-4, conclusion gate (ACC-CONC) | met offline | `test_property_identity_binding.py`, `test_permit_false_positives.py`, `test_permit_conclusion_gate.py` |
| C2 on a real replica set (`test_permit_commit_atlas.py`) | **PENDING** (needs authorisation + credentials) | TD-001 |
| Shadow measurement on live drafter output | **PENDING** (needs live runs) | TD-031 |
| Pre-demo live gate, preview redeploy and visual QA (MU-1/4/5) | **PENDING** (needs authorisation) | TD-033 |
| CX-3, CX-4, CX-5 backlog | in work (offline) | TD-016…018 |

## Candidate modules named in the approved architecture (not yet assigned to HR numbers)

Named in `docs/architecture.md` §1/§6/§10 and in the HR-001/HR-002 out-of-scope lists. They have **no approved
scope or acceptance criteria** yet; numbering and order are the owner's decision.

| Module | Where it is named | What is defined |
|---|---|---|
| SAM 3.1 segmentation | architecture §6.2 | integration point only |
| Muse Voice Transcribe (voice input) | architecture §6.3, §1 | integration point only |
| Muse Image (image generation/editing, renovation visualisation) | architecture §6.4 | integration point only |
| Afford (affordability) | README, HR-001/HR-002 out-of-scope | name only |
| HABITA Live | HR-001/HR-002 out-of-scope, architecture §10 | name only |
| Broader jurisdictions (JurisdictionAdapter) | architecture §9.1, §9.5 (proposal) | proposal; after a stable Cascais MVP |

### Dependency order (proposal, for the owner to confirm)

1. Finish HR-003's offline items (CX-3 → CX-5 → CX-4), then its live validations once authorised.
2. Modules that only *read* a resolved property and need no new legal reasoning are the most demonstrable and least
   risky: voice input (feeds the existing Permit question), then segmentation/visualisation (SAM 3.1 → Muse Image).
3. Afford and HABITA Live once defined.
4. JurisdictionAdapter after the Cascais MVP is stable.

## Progress (calculable)

- Formally concluded: **2 of 15** milestones (HR-001, HR-002) = **13.3 %**.
- Weighted progress: **not calculable** (HR-004…HR-015 have no criteria).
