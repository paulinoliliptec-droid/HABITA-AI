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
| CX-3, CX-4, CX-5 backlog | met offline (Codex backlog review, final NO P1) | TD-016…018; `test_sources_concurrency.py`, `test_sources_ingest_concurrency.py`, `test_planning_context.py` |

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

### Preparation of the next modules (no requirement invented)

What each candidate needs before it can start, from what the repository already has:

| Module | Already in place | Needs from the owner |
|---|---|---|
| Voice input (Muse Voice Transcribe) | `integrations/meta/` client; Permit question entry point; architecture §1 voice path (WebSocket) | HR number, scope (languages, max duration, consent/retention), acceptance criteria, Meta ASR model access |
| Segmentation (SAM 3.1) | Meta client; property workspace with map | HR number, input source (user photos vs imagery), output use, acceptance criteria |
| Muse Image (visualisation) | Meta client | HR number, scope (renovation visualisation?), disclaimers, acceptance criteria |
| Afford | — | definition |
| HABITA Live | — | definition |

HR-003 items that remain need real services: Atlas transaction run (TD-001), shadow measurement on live output
(TD-031), pre-demo live gate / preview (TD-033).

## MVP execution matrix (state of the code, 2026-10-29)

Inventory of the components the owner asked about, from the code on `mu9/structural-verification`. "Implemented" means
code + tests in the repository; nothing here adds a requirement to HR-004 … HR-015.

| Component | Real state | Evidence in the code | Gap to a demo |
|---|---|---|---|
| Property map | **Implemented** (HR-001) | `frontend/src/features/property/PropertyMap.tsx` (Google Maps JS, styled, HTML marker), `AddressSearch.tsx` (Places autocomplete), `lib/google-maps/loader.ts` | none for location display |
| "Intelligent" map (planning layers on the map) | **Not started** | planning context is shown as text (`PlanningContextBlock.tsx`); no layer/polygon on the map; Cascais has no validated zoning connector (manual confirmation, owner decision 2026-10-28) | needs a definition and a trusted machine-readable layer; CX-5 fixed, so a connector could be enabled once one exists |
| Visual graph (evidence / jurisdiction graph) | **Not started** | Permit shows a 4-phase stepper (`PermitProgress.tsx`) and an evidence list with anchors (`PermitResult.tsx`); no graph library in `package.json` | needs a definition |
| PDF reports (export of an assessment) | **Not started** | only PDF *ingestion* of official sources (`pypdf`, `sources/normalize.py`); no report generation, no print stylesheet | needs a definition |
| Voice input | **Not started** | named in architecture §1/§6.3; no audio capture, endpoint or transcription client | needs a definition + Meta ASR access |
| Multimodal (photos, SAM 3.1, Muse Image) | **Not started** | named in architecture §6.2/§6.4; no upload endpoint, no image client | needs a definition + model access |
| Meta AI integration | **Partial** | `integrations/meta/client.py`: Muse Spark chat with tools, used by the Permit workflow; no image, ASR or segmentation calls | live runs need the Meta key (opt-in `test_permit_live.py`) |
| Permit Intelligence + MU-9 verification | **Implemented offline** (HR-002, HR-003) | workflow, independent verifier, final gate, TrustPin, C2 binding; 6525 tests, corpus 294 / 0 unsupported VERIFIED | live validation pending (below) |
| Official sources & planning context (Cascais) | **Implemented** (HR-003) | registry, SafeFetcher, PDF snapshots, retrieval, manual-confirmation resolver, CX-3/4/5 fixed | — |
| Jurisdiction adapters (location) | **Implemented** (HR-001) | `backend/app/services/jurisdiction/base.py` (`JurisdictionAdapter`), Portugal and generic adapters, `resolver.py` | the *legal-research* extension (architecture §9.5) is a proposal, not started |
| Deployment (Cloud Run preview) | **Partial** | `.ai-review/REVIEW_BOARD.md` HR-003 row: preview rev backend-00016 / frontend-00011 on `main` @ `98af6af` (before MU-9); `docs/demo-runbook.md` names the preview services; `infrastructure/README.md` records no provisioning-as-code | redeploy of the current code needs authorisation (MU-5) |

### 1. Implemented
Address search, property resolution, jurisdiction and competent authority, property workspace with map; Permit
Intelligence workflow (questions, evidence, verification, conditional answers, citations); official sources and
planning context for Cascais with manual confirmation; MU-9 structural verification (offline).

### 2. Partially implemented
Meta AI integration (text/tools only); deployment (preview not on current code); HR-003 live validations.

### 3. Not started
Intelligent map layers, visual graph, PDF reports, voice, photos/SAM 3.1/Muse Image, Afford, HABITA Live, the
legal-research extension of the jurisdiction adapters — all **pending definition** (no HR scope approved).

### 4. Blocked on credentials or authorisation
| Item | Needs |
|---|---|
| C2 transaction test on Atlas (`test_permit_commit_atlas.py`) | authorisation + `MONGODB_URI` (replica set) |
| Live Permit runs / shadow measurement / pre-demo gate (MU-1) | authorisation + Meta key (`HABITA_META_LIVE=1`); the full run also needs Atlas and Google |
| Live smoke (`test_live_smoke.py`: geocoding, autocomplete, Atlas) | authorisation + Google server and browser keys, Atlas |
| Preview redeploy and visual QA (MU-5) | authorisation (GCP) |
| Push / merge of `mu9/structural-verification` | authorisation |
| Voice, image, segmentation | model access + HR definitions |

### 5. Tests required before a real demonstration
1. Offline: backend suite, acceptance corpus (0 unsupported VERIFIED), frontend tests, lint, typecheck, `next build`.
2. `HABITA_LIVE_TESTS=1 pytest tests/test_permit_commit_atlas.py` on the demo database (C2 + CX-2 transactions).
3. `HABITA_LIVE_TESTS=1 HABITA_META_LIVE=1 pytest tests/test_live_smoke.py tests/test_permit_live.py` (geocoding,
   autocomplete, Atlas, Meta; the Meta tests run only with `HABITA_META_LIVE=1`).
4. Pre-demo live gate (MU-1): one Cascais NEEDS_INPUT → VERIFIED conditional run on the deployed preview asserting
   conditional answer, manual planning confirmation, no model-authored zoning and trusted provenance.
5. Demo runbook rehearsal (`docs/demo-runbook.md`) and visual QA of the workspace (MU-5). The runbook has no
   REJECTED-outcome fallback yet: adding that narration is MU-4.

### Most efficient sequence to a demonstrable MVP (proposal)
1. **Stabilise what exists** (no new scope): authorise steps 2–3 above, redeploy the preview on the current code,
   run the live gate and rehearse (closes TD-001, TD-031 partially, TD-033).
2. **Define the next milestone** (owner): the cheapest demonstrable additions reuse what is built — e.g. a PDF/print
   export of an existing Permit result, or voice input feeding the existing Permit question — but which one, and its
   criteria, are the owner's decision.
3. Then the other candidates by dependency (multimodal after a definition and model access; map layers after a
   trusted connector).

## Progress (calculable)

- Formally concluded: **2 of 15** milestones (HR-001, HR-002) = **13.3 %**.
- Weighted progress: **not calculable** (HR-004…HR-015 have no criteria).
