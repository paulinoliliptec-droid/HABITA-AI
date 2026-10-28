# HABITA AI — Architecture

> **Global Property Intelligence & Permitting OS**
> Status: **in build**. Implemented so far: the *Property → Location → Jurisdiction* slice (§7, steps 1–2). Everything else here is still target design.

## 1. System overview

```
                ┌──────────────────────────────────────────────┐
  Browser  ───► │ frontend/  Next.js (React, TypeScript)       │
                │  - map UI (Google Maps JS API)               │
                │  - property / permit workflows, voice input  │
                └───────────────┬──────────────────────────────┘
                                │ HTTPS / JSON (+ WebSocket for voice)
                ┌───────────────▼──────────────────────────────┐
                │ backend/  Python FastAPI                     │
                │  ├─ API layer (REST)                         │
                │  ├─ Orchestrator  ──► Jurisdiction agents    │
                │  ├─ Meta Model API client                    │
                │  │   (Muse Spark · Muse Image ·              │
                │  │    Muse Voice Transcribe · SAM 3.1)       │
                │  ├─ Google Maps server client                │
                │  └─ Data access (MongoDB)                    │
                └──────┬───────────────┬───────────────┬───────┘
                       │               │               │
              ┌────────▼───┐   ┌───────▼──────┐  ┌─────▼──────────┐
              │ MongoDB    │   │ Meta Model   │  │ Google Maps    │
              │ Atlas      │   │ API          │  │ Platform       │
              └────────────┘   └──────────────┘  └────────────────┘

  Deployment: two Cloud Run services (frontend, backend), images in Artifact
  Registry, secrets from Secret Manager.
```

**Design rule:** the browser never calls the Meta Model API or MongoDB directly. All AI and data access goes through the backend so keys stay server-side. The only key the browser sees is the referrer-restricted Maps JavaScript key.

## 2. Frontend (`frontend/`)
- **Stack:** Next.js (App Router) + React + TypeScript.
- **Responsibilities:** address search and map exploration; property profile views; permit/jurisdiction requirement checklists; document and photo upload; voice capture (mic → backend transcription); rendering of agent results with source citations.
- **Talks to:** the backend over `NEXT_PUBLIC_API_BASE_URL`, and the Google Maps JS API with the browser key.
- **No secrets** in the client bundle apart from `NEXT_PUBLIC_*` values.

## 3. Backend (`backend/`)
- **Stack:** Python 3.12, FastAPI, Pydantic v2 for settings and schemas, an async MongoDB driver, `httpx` for outbound HTTP.
- **Planned modules** (names are indicative):
  - `api/`: HTTP routers (properties, jurisdictions, permits, media, voice).
  - `agents/`: orchestrator plus per-jurisdiction agents (§9).
  - `integrations/meta/`: thin client for the Meta Model API (text, image, ASR, SAM).
  - `integrations/maps/`: geocoding, places, and parcel/location resolution.
  - `db/`: Mongo connection, repositories, indexes.
  - `core/`: settings loaded from env, logging (with secret redaction), errors.
- **Cross-cutting:** a health endpoint for Cloud Run; structured logs that never print env values; timeouts and retries on all external calls.

## 4. MongoDB Atlas
- Dedicated Atlas project **"HABITA AI"**, isolated from other projects.
- **Candidate collections:** `properties` (normalized address, geo point, attributes), `jurisdictions` (hierarchy country → state/province → county → municipality, plus rule sources), `permit_requirements`, `projects`/`cases` (a user's permitting workflow), `documents` (uploads + extracted data), `agent_runs` (inputs, outputs, citations, model used: the audit trail).
- **Geo:** `2dsphere` index on property and jurisdiction geometries for point-in-polygon jurisdiction lookup.
- **Optional:** Atlas Vector Search over regulation/code text for agent retrieval.
- **Access:** connection string only via `MONGODB_URI` from Secret Manager. Network access is restricted. Use a least-privilege DB user.

### 4.1 `properties` (implemented, schema v2)
- **Identity.** `_id` is a HABITA ID (`prp_` + 16 hex), generated when a location is first resolved and never derived from a provider ID. A property is a *resolved premise*: address and building level, with units kept apart when Google returns one. A resolution attaches to an existing property, in order:
  1. by `property_id` (refresh);
  2. by **alias**: any Google place ID of this resolution in `place_ids` (unique multikey index), preferring the owner of the resolved primary ID; aliases recorded on a merging or merged duplicate resolve to its target;
  3. by **address**: the same deterministic `address_key` (`jurisdiction.id | route | street number | unit`, from the official-language components; only for rooftop/interpolated results with a street number) **and** exactly one candidate within 50 m.

  Otherwise a new property is created. Near-misses (same key but farther apart, or several candidates) are recorded as `possible_duplicates` and never merged automatically. Units are part of the key, so a unit never merges with another unit or with the building record.
- **Concurrent creation.** The first property for an address key holds `premise_key` (unique partial index). Simultaneous creations of one premise collide on it, and the loser's retry attaches to the winner. Far-away homonyms are still created, without the claim.
- **Reconciliation.** `python -m app.maintenance list-duplicates`, `merge <keep> <duplicate>` and `resume-merges`. The merge is an idempotent three-step state machine (`merging` → aliases attached → `merged`):
  - the aliases stay recorded on the duplicate throughout;
  - reads and alias lookups follow the target in every state;
  - re-running, or the service's startup maintenance, completes an interrupted merge.
- **Snapshot lifecycle.** Google-derived fields (formatted address, coordinates, GeoJSON point, precision, jurisdiction, address and premise keys) form a snapshot with `resolved_at` and `expires_at` (30 days).
  - **Guaranteed:** an expired snapshot is never served as current. `GET` refreshes it from the stored place ID into the same property, and a write only replaces an older snapshot. Address matching may use an expired, not-yet-purged property's key and point *as identity evidence only*; its data is replaced by the fresh snapshot in the same save.
  - **Best effort (hackathon):** physical removal of expired fields (`snapshot_state: "purged"`; HABITA ID, place IDs, request provenance and timestamps are kept). It runs at backend startup and every 6 h while an instance runs, and on demand via `python -m app.maintenance purge-expired` or the token-protected `POST /internal/maintenance/run` (enabled by `MAINTENANCE_TOKEN`). A scaled-to-zero service with no traffic does not purge until its next start; a fixed schedule (e.g. Cloud Scheduler calling the endpoint) is the production step.
- **Request-scoped data.** `partial_match` describes one request. It is returned by `POST /resolve-location` and never stored. The frontend carries it in the workspace URL (`?match=partial`). `provenance` describes how the *current snapshot* was produced, including `identity` (`new | alias | address | refresh`).
- **Concurrency.** Saves converge: a duplicate-key race (alias or premise) is retried and attaches to the winner, and alias additions skip IDs owned by another property instead of failing.
- **Versioning.** Schema-0/1 documents are upgraded in place on their next resolution or read, keeping `_id`, URL and `created_at`.
- **Retention basis (to be confirmed by the owner).** Place IDs are kept indefinitely; other Google content expires after 30 days. Which Maps service terms apply (EEA or non-EEA) depends on the billing account and must be confirmed before production.
- **Storage required.** The backend refuses to start without `MONGODB_URI` unless `ALLOW_EPHEMERAL_STORAGE=true` (local dev/tests only).

## 5. Google Maps Platform
- **Browser (Maps JavaScript API):** interactive map, markers, drawn areas.
- **Server:** Geocoding (address → lat/lng + components), Places (autocomplete/details), optionally Static Maps / aerial imagery as inputs to SAM 3.1.
- Geocoded address components feed **jurisdiction resolution** (§9).
- Two separate keys (browser and server), each restricted to its APIs. Respect the Maps Platform terms on caching and storing content.

## 6. Meta Model API (shared integration)
- Base URL `https://api.meta.ai/v1`, auth `Authorization: Bearer $META_API_KEY`.
- Supports the Responses, Chat Completions and Messages protocols for text models. `GET /v1/models` lists the models enabled for the team.
- One backend client owns auth, retries, timeouts, and per-call logging of model ID, latency and tokens. Logs never include the key.
- Model IDs come from config (`META_*_MODEL`) so they can be swapped without code changes.

### 6.1 Muse Spark: reasoning and agents
- Model: `muse-spark-1.3` (current recommended). Multimodal input: text, image, video, audio, PDF.
- Role: the reasoning engine behind the orchestrator and jurisdiction agents. It reads regulations, PDFs and photos, plans steps, calls tools (geocode, DB lookup, retrieval), and produces structured outputs (JSON schemas) with citations.
- Contributor-mode variants (`-contributor`) allow Meta to train on our data, so **don't use them** with user property data.

### 6.2 SAM 3.1: segmentation
- Model: `sam-3.1` via `POST /v1/responses`. The Files API lets us reuse uploaded clips.
- Role: segment site photos, aerial imagery or plans into structures, footprints, pools, driveways and similar. Results feed measurements and permit-relevant feature detection, e.g. "detached structure present".
- **Imagery reference (contract for the SAM slice, not implemented).** Every SAM input is an explicit image reference: `{provider, source_id/url, captured_at, center {lat,lng} or bbox, zoom, ground_resolution_m_per_px, license}`. Styled interactive-map pixels are never a segmentation input. The workspace's Map/Satellite toggle is a view concern only.
- **Attachment point.** Segmentation outputs (masks, measured features) are stored on `cases` / `agent_runs` and reference `property_id` plus the imagery reference. They never mutate the property document.

### 6.3 Muse Voice Transcribe: speech to text
- Model: `muse-voice-transcribe-1.0`. Batch: `POST /v1/asr/transcribe`. Realtime: `wss://api.meta.ai/v1/asr/realtime`.
- Role: voice-first intake, e.g. a homeowner describes the project or an inspector dictates notes. The backend proxies the audio so the browser never holds the API key. Transcripts are passed to Muse Spark.
- **Transport constraint for the voice slice.** The current API is one JSON request → one JSON response, and CORS allows only `GET`/`POST` with `Content-Type`. Voice needs a WebSocket or chunked-upload route with its own partial/final message envelope, a CORS and header update (multipart for uploads), and a check of Cloud Run's behaviour for long-lived connections (request timeout, HTTP/2, session affinity).

### 6.4 Muse Image: image generation and editing
- Model: `muse-image-1.0`. Endpoints: `POST /v1/images/generations`, `POST /v1/images/edits`, or the Responses API.
- Role: visualize proposed changes (renovation or addition mock-ups) and annotate site images. Generated images are labeled as AI-generated and never presented as evidence of existing conditions.

## 7. Request flow example (target)
1. User enters an address (Places Autocomplete suggests, optional) → frontend → `POST /api/property/resolve-location`. **Implemented.**
2. Backend geocodes it (Geocoding API), re-reads it in the country's official language when a jurisdiction adapter asks for one, resolves the jurisdiction chain from Maps components (`backend/app/services/jurisdiction/`), and upserts `properties`. **Implemented** (Maps components only; Mongo geo lookup not yet).
3. User describes the project by voice → Voice Transcribe → text.
4. Orchestrator (Muse Spark) selects the jurisdiction agent(s) → the agents retrieve rules and reason → structured permit checklist with citations.
5. Optional: upload site photos → SAM 3.1 segments → features added to the agent context. Muse Image renders the proposal.
6. Results are stored in `agent_runs` / `cases` → rendered in the UI.

## 8. Deployment (Google Cloud Run)
- Two containers: `habita-frontend` (Next.js standalone output) and `habita-backend` (uvicorn).
- Images go to Artifact Registry (`$ARTIFACT_REGISTRY_REPO`). Secrets are mounted from Secret Manager as env vars. Each service runs as its own service account with minimal IAM.
- Details in [`infrastructure/README.md`](../infrastructure/README.md).

## 9. Jurisdiction model and agents

### 9.1 Jurisdiction model (implemented)
`backend/app/services/jurisdiction/base.py` defines a country-neutral contract that per-country adapters fill in:
- **`levels`**, from the country down, typed `country`, `region`, `subregion`, `municipality`, `subdivision` and `overlay` (overlay is reserved; nothing produces it yet). Each level has a local display `label` ("District", "County", "Commune"). `municipality` always means the permit-competent local government unit, never a postal place standing in for one. The postal place goes in `locality` (API: `city`).
- **IDs.** Every level has an ID: a lowercase path such as `pt/lisboa/cascais`. Adapters build IDs from official-language names, so they don't depend on the user's language. `jurisdiction.id` is the governing level (the municipality when known). IDs from the generic fallback (`coverage: "unmodelled"`) are provisional. National statistical codes (e.g. INE codes for Portuguese municipalities) can be added as attributes when rule retrieval needs them.
- **Authority entity.** `local_authority` is `{id, name, kind, jurisdiction_id, competence, sources[]}`, e.g. `pt/lisboa/cascais:camara-municipal` with the RJUE art. 5.º competence basis. Display formatting (Portuguese prepositions) lives in the adapter's helper; the entity is the contract.
- **Adapters.** Portugal is modelled. Future adapters (France/Paris: région → département → commune → arrondissement; UK/London: country → region → borough; US/San Francisco: state → county → city) map onto the same level types. The generic adapter reports what Google returns under neutral labels and never asserts a municipality or authority.

### 9.2 Jurisdiction agents
Permitting rules are local. HABITA models them as **agents scoped to a jurisdiction level**, coordinated by an orchestrator:

| Layer | Scope | Examples of concerns |
|---|---|---|
| Orchestrator | Request | Classify the project type, resolve the jurisdiction chain, fan out to agents, merge and deduplicate results, resolve conflicts (the stricter rule wins and is flagged). |
| National agent | Country | National building codes, energy and accessibility standards. |
| Regional agent | State / province | State amendments, licensing, environmental overlays. |
| Local agent | County / municipality | Zoning, setbacks, height limits, permit types, fees, submission portals. |
| Special-district agent | Overlay | Historic districts, coastal and flood zones, HOA (where data exists). |

- **Agent contract (planned):** input = property and project context plus jurisdiction ID. Output = a typed list of requirements, each with `source_url`/`source_doc`, confidence, and the date retrieved.
- **Knowledge:** curated jurisdiction records in MongoDB plus retrieved documents. Agents must cite sources and say "unknown" rather than guess.
- **Extensibility:** a new jurisdiction is a new data record plus optional prompt or config overrides, not new code, wherever possible.
- **Safety:** output is decision support, not legal advice. The UI states this and links to the official sources.

### 9.3 Permit Intelligence workflow (HR-002, implemented foundation)
`backend/app/services/permit/` implements the first agentic workflow: **GOAL → CHECKLIST → TOOLS → EVIDENCE → DRAFT (UNVERIFIED) → INDEPENDENT VERIFICATION → FINAL STATE**.

- **Model.** Meta **Muse Spark** (`muse-spark-1.3`, standard mode; `-contributor` variants are refused) via the Meta Model API Chat Completions endpoint, with function tools and strict JSON-schema structured output (`integrations/meta/client.py`). The workflow depends on a provider-neutral `ReasoningModel` protocol; tests use a scripted implementation.
- **States** (persisted on `permit_matters`): `PLANNING → INVESTIGATING → (NEEDS_INPUT) → DRAFT_READY → VERIFYING → VERIFIED | ESCALATE | NEEDS_INPUT`, and `FAILED` with the state to resume. A verifier `REJECTED` sends the draft back for one revision, then escalates. Each step persists its output before changing state, so `continue` resumes from saved checklist and evidence instead of starting over. A per-matter lease prevents concurrent runs.
- **Checklist.** Canonical requirements per intent (`requirements.py`) with fixed IDs and an information owner (USER / SYSTEM_TOOL / AUTHORITY / DOCUMENT / UNKNOWN). Status is reconciled from evidence in code: satisfied, needs_input (USER only), blocked_external (a condition for the authority) or open (an evidence gap). Only USER items become questions; matters converge within a bounded number of rounds to VERIFIED, NEEDS_INPUT, ESCALATE or REJECTED.
- **Roles.**
  - **Planner:** classifies the intent and may rephrase canonical questions; it can't add items.
  - **Investigator:** a bounded tool loop. Baseline context tools always run first.
  - **Drafter:** writes a structured draft that is always `UNVERIFIED`.
  - **Verifier:** separate, and never sees the executor's conversation. Deterministic rules run first: checklist coverage, every material claim citing existing evidence, evidence jurisdiction within the property's chain, authority consistency, and a conclusion proportionate to what is missing. Then an independent Muse Spark review that can only tighten the outcome.
- **Tools.** `get_property_context`, `get_jurisdiction_context`, `get_competent_authority`, `get_available_evidence`, `get_planning_context`, `search_regulatory_sources`, `request_missing_information`. HABITA executes them; the model only requests them. No tool takes a URL or changes a source's trust status.
- **Evidence.** One record per fact (`permit_evidence`), cited by ID (`E1…`), with source type, title, reference/URL, jurisdiction, authority, retrieval time, the claim it supports, an excerpt, and a status: `system_record` (HABITA data), `curated_reference` (reviewed summary of an official source, not its live text), `official_text` (a passage of a retrieved official document, pinned to a snapshot hash) or `user_declared`. Regulatory and planning evidence carries a `provenance` block (registry source, trust status, version, locator, snapshot and sha256) that the verifier re-checks against the registry (§9.4).
- **Sources.** `sources/base.py` defines providers filtered by the jurisdiction chain. `sources/portugal.py` ships curated references for Portugal (RJUE, Simplex Urbanístico, Código Civil on horizontal property, RGEU) and Cascais (PDM). A new jurisdiction is a new provider.
- **Collections.** `permit_matters`, `permit_checklists`, `permit_evidence`, `permit_verifications`.
- **Scope.** Unit conversions and general orientation for Portuguese properties, with Cascais municipal sources. Other intents and jurisdictions escalate. No SAM, Live, Afford, image generation or automatic submission.

### 9.4 Official sources, planning context and retrieval (HR-003)
Google Maps determines location; HABITA determines jurisdiction; official sources determine the rules; Muse Spark reasons over validated evidence. The model is never the source of a legal or zoning fact.

- **Official source registry** (`app/services/sources/`, collection `official_sources`). Each source records jurisdiction, authority, type, verified official URL, publisher, geographic and regulatory scope, version, retrieval method, machine-readability, authority class and a verification record. Lifecycle `candidate → validated → trusted → retired`: only `trusted` sources produce evidence; discovered sources can only enter as `candidate`; validation requires https on an allowlisted official host publishing for that jurisdiction (or an ancestor); promotion is an operator command recorded in `status_history`. Seeds come from reviewed code (`catalog.py`) and never override an operator's status.
- **Cascais corpus.** The PDM-Cascais Regulamento (official text, indexed by article), the official urbanism FAQ (procedure, indexed), the PDM's ordering and constraint maps and its amending avisos (metadata and verified links only; not spatially interpreted), and the national RJUE, Simplex, Código Civil and RGEU as curated references. GeoCascais is registered as a `candidate`: we have not yet verified an official machine-readable service that can reliably classify an arbitrary Cascais coordinate against the PDM zoning layers.
- **Fetching and ingestion.** Only `SafeFetcher` fetches, only registry URLs, from maintenance (`python -m app.maintenance ingest-sources`), never during a Permit run: https on 443 to allowlisted hosts, public IPs only, each redirect re-checked, size and content-type limits. Text PDFs are parsed with `pypdf` (no OCR); a document becomes a `source_snapshots` record (sha256, final URL, retrieval time, version hint) and its passages go to `regulatory_chunks`. A changed document is a new snapshot; old passages are kept.
- **Retrieval.** Jurisdiction-aware, not a global index: latest snapshots of trusted sources in the property's chain whose scope matches the topics, ranked deterministically (BM25 over topic vocabulary plus the query's own words).
- **Planning context** (`app/services/planning/`). `PlanningContextResolver` per jurisdiction; `resolved` only when a trusted machine-readable layer returns exactly one zoning feature for a precisely located point away from class boundaries. Otherwise `requires_manual_confirmation` with the instrument and version, the exact official maps to check, the reasons, the competent authority and verification dates. `GET /api/property/{id}/planning-context` exposes it with the trusted sources consulted. The `planning_constraints` checklist item is settled only by a resolved context; otherwise it remains a condition naming those maps.
- **Verifier.** Rule `untrusted_source`: cited regulatory or planning evidence must come from a source trusted *at verification time* for the jurisdiction chain, and official text must carry its snapshot hash.

## 10. Implementation status
- **Done (HR-001):**
  - design system and app shell; address entry with Places Autocomplete;
  - `POST /api/property/resolve-location` and `GET /api/property/{id}`;
  - the jurisdiction model of §9.1 with a Portugal adapter and a generic fallback;
  - property identity, snapshots and provenance of §4.1;
  - an in-process spend limiter (429), structured errors with CORS on every path, and a readiness check;
  - property workspace with map; privacy & terms page.
- **Done (HR-002 foundation):** Permit Intelligence workflow (§9.3) with Muse Spark, tools, evidence, independent verifier, resumable state and the workspace's Permit section.
- **Done (HR-003 foundation):** official source registry with trust lifecycle, SafeFetcher, PDF ingestion and snapshots, jurisdiction-aware retrieval, PlanningContextResolver (Cascais: manual-confirmation fallback), provenance on evidence and the verifier's trust rule, planning context in the Jurisdiction section (§9.4).
- **Not started:** SAM 3.1, voice, Muse Image, Afford, HABITA Live, broader jurisdiction coverage and sources.
