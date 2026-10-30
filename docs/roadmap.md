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
| HR-004 | Intelligent Map Experience | interactive map, highlighted property, informative post-its, planning conditions, risks and consultable legal sources; zoning layers only as verified official data, otherwise the absence is stated (owner, 2026-10-29) | AC4.1–AC4.8 below | **MVP COMPLETE** — tested headless on staging; owner's real-browser check pending (TD-049) |
| HR-005 | — | **PENDING DEFINITION** | **PENDING** | not started |
| HR-006 | Premium PDF Report | professional export: property identification, analysis summary, conditions, risks, official sources, verifiable references and conclusion status; VERIFIED / REJECTED / pending clearly distinct; evidence provenance and version preserved (owner, 2026-10-29) | AC6.1–AC6.9 below | **IN PROGRESS** — all criteria met in tests; AC6.8 real map images pending the Maps Static API (TD-047) |
| HR-007 … HR-015 | — | **PENDING DEFINITION** (no approved scope in the repository) | **PENDING** | not started |

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

## HR-004 and HR-006 acceptance criteria (proposed by the builder from the owner's scope, 2026-10-29)

Common architecture (owner): one shared structure of legal results feeds the map and the PDF; no duplication of the
RAG, the MU-9 verifier or the legal decision logic; HR-003 and its safeguards preserved; map, post-its and PDF tested for
consistency; demo data only when clearly labelled.

**Shared report model.** Built only from what HABITA already stored: the property, its planning context, the official
sources of its jurisdiction chain and, for an assessment, the matter's draft, evidence and latest verification report.
It never calls the model, the retriever or the verifier. Status vocabulary: **VERIFIED** (the matter is VERIFIED and its
verification report is VERIFIED for the same draft revision), **REJECTED** (the matter or its latest report is
REJECTED), **PENDING CONFIRMATION** (anything else; unverified draft content is labelled "not verified").

| ID | HR-004 Intelligent Map Experience |
|---|---|
| AC4.1 | The resolved property is highlighted on the interactive map (marker + label) at its stored coordinates. |
| AC4.2 | Post-its show: the property and its competent authority; the planning context; the assessment status when an assessment is open; the official sources — all read from the shared report model. |
| AC4.3 | Zoning: a classification appears only when the planning context is `resolved` by a trusted machine-readable connector; otherwise the post-it states that no verified zoning layer exists and lists the official maps to consult. No polygon, class or parcel limit is ever drawn without one. |
| AC4.4 | Every legal source in a post-it opens its official URL; evidence ids match the report model's. |
| AC4.5 | The status shown is exactly the report model's (same vocabulary as the PDF). |
| AC4.6 | Tests: post-it model unit tests; consistency with the report model; frontend lint, typecheck, build; no backend regression. |
| AC4.7 | Demo data, if used, is visibly labelled as such. |
| AC4.8 | (owner, 2026-10-30) The property post-it shows location (coordinates, never as a parcel boundary) and municipality; an analysis-status post-it appears also without an assessment; unverified zoning reads "Zoning not verified". |

| ID | HR-006 Premium PDF Report |
|---|---|
| AC6.1 | A server-generated PDF from the shared report model: property identification (address, coordinates, precision, jurisdiction chain, authority), planning context, analysis summary, conditions, risks, procedure and next actions, official sources and evidence references, generation time. |
| AC6.2 | The status is unmistakable: VERIFIED only under the rule above (with verification date, protocol and trust pin); REJECTED with its issues; otherwise PENDING CONFIRMATION, with unverified content marked "not verified"; the planning manual-confirmation reasons shown as pending. |
| AC6.3 | Provenance of every evidence item: source id, version, snapshot id, sha256, locator, retrieval date, verification status, official URL. |
| AC6.4 | No new legal content: the PDF renders only stored statements; no model, retriever or verifier call. |
| AC6.5 | Access: an assessment report needs the matter's capability token; a property-only report is public, like the property. A decision-support disclaimer (not legal advice, not a permit) is always present. |
| AC6.6 | Tests: report model per status (VERIFIED / REJECTED / pending / no assessment); adversarial: an unverified or rejected draft is never labelled VERIFIED; the PDF's extracted text carries the same status, evidence ids and provenance as the JSON and the map post-its. |
| AC6.7 | A download action in the workspace. |
| AC6.8 | (owner, 2026-10-30) Two embedded location images — road map and satellite — with the same centre, zoom and size, highlighting the analysed area; a real polygon only from verified official parcel geometry, otherwise a marker and a circle labelled approximate, never a cadastral boundary; legend and map attribution; when the map service is unavailable or unconfigured, an explicit notice and no substitute image; no key or token in the PDF. |
| AC6.9 | (owner, 2026-10-30) A professional cover: property, status, municipality, authority, zoning state, and a permanent warning that there is no municipal confirmation. |

### HR-004 / HR-006 implementation status (2026-10-29, offline-tested; not deployed)
| Criteria | State | Evidence |
|---|---|---|
| AC6.1–AC6.6 | met offline | `backend/app/services/report/`, `api/report.py`; `tests/test_report.py` (status rule incl. superseded protocol and older records, rejected, pending, no assessment; PDF text = JSON status, ids, sha256; no model call; token required); mutation checks on the status and zoning rules |
| AC6.7 | met | "PDF report" button on the map (capability in the header) |
| AC4.1–AC4.5 | met offline | `frontend/src/features/report/` post-its from the same report; tests on the backend's own report for an end-to-end Cascais run (fixture guarded by a backend schema test) |
| AC4.6 | met | frontend tests, lint, typecheck, build; backend suite |
| AC4.7 | met in the model (`demo` flag → labelled in PDF and map); no demo dataset shipped |
| Visual QA in a browser | **pending** | headless Chromium lacks libxkbcommon here; needs the redeployed preview or a local browser |
| Non-Latin characters in the PDF | TD-021 (P2) | Portugal scope covered by the standard fonts |
| Map polygons / zoning layers | not drawn by design | no validated GIS connector; the absence is stated |

### HR-004 / HR-006 status update (2026-10-30)
| Criteria | State | Evidence |
|---|---|---|
| AC4.1–AC4.5, AC4.7 | met; **tested on staging** | headless Chromium through the authenticated proxies: map rendered, post-its, no console errors (`infrastructure/STAGING.md` Setup log) |
| AC4.8 | met; tested | `postits.test.ts`; screenshot of the local frontend against the staging backend (not yet deployed to staging, TD-050) |
| AC6.1–AC6.7 | met; **tested on staging** | real property PDF and a real VERIFIED matter PDF from staging (text, TrustPin, evidence ids, disclaimer on every page) |
| AC6.8 | met with a simulated map service | `tests/test_report_maps.py` (16): two embedded JPEGs, same framing, approximate legend, failures → notice, no key leak, daily cap; **real images pending** the Maps Static API (TD-047) |
| AC6.9 | met | cover rendered and checked (pdftoppm); warning always present |
| Visual QA in the owner's browser | **pending** | TD-049 |
| Open items | central register | `.ai-review/HABITA-AI-TECHNICAL-DEBT.md` (local, git-ignored): TD-044 … TD-052 |

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

### Live validation log (2026-10-29, development environment, demo addresses only)
| Test | Result | Notes |
|---|---|---|
| Google Geocoding (server key) via `/api/property/resolve-location` | **PASS** | "Praça 5 de Outubro, Cascais" → area_center, `pt/lisboa/cascais`, Câmara Municipal de Cascais, 388 ms; "Avenida Marginal 8, Cascais" → rooftop, 316 ms |
| Planning context on a real geocode | **PASS** | `requires_manual_confirmation` (no machine-readable layer, low precision): no zoning invented |
| Property PDF from real Google data | **PASS** | 4 pages, "No verified zoning layer" stated, 26 official sources |
| Atlas (`test_live_smoke.py`, `test_permit_live.py`, `test_permit_commit_atlas.py`) | **NOT RUN** | no `MONGODB_URI` in the development environment; the URI exists only in Secret Manager (`mongodb-uri`) and reading it needs the owner's authorisation. Local storage was in-memory |
| Muse Spark live (`HABITA_META_LIVE=1`) | **NOT RUN** | no `META_API_KEY` locally (Secret Manager `meta-api-key`); `/api/permit/status` → `available: false` |
| Database identity | checked | local `.env`: `APP_ENV=development`, `MONGODB_DB_NAME=habita_ai`, no URI (so no database reached); preview: `APP_ENV=preview`, `MONGODB_DB_NAME=habita_ai`. Live tests must use a separate database name (see `infrastructure/STAGING.md`) |

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
