# HABITA AI — Architecture

> **Global Property Intelligence & Permitting OS**
> Status: **pre-build design**. No components below are implemented yet. This document is the target architecture for the hackathon building window.

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

### 6.3 Muse Voice Transcribe: speech to text
- Model: `muse-voice-transcribe-1.0`. Batch: `POST /v1/asr/transcribe`. Realtime: `wss://api.meta.ai/v1/asr/realtime`.
- Role: voice-first intake, e.g. a homeowner describes the project or an inspector dictates notes. The backend proxies the audio so the browser never holds the API key. Transcripts are passed to Muse Spark.

### 6.4 Muse Image: image generation and editing
- Model: `muse-image-1.0`. Endpoints: `POST /v1/images/generations`, `POST /v1/images/edits`, or the Responses API.
- Role: visualize proposed changes (renovation or addition mock-ups) and annotate site images. Generated images are labeled as AI-generated and never presented as evidence of existing conditions.

## 7. Request flow example (target)
1. User enters an address → frontend → `POST /properties/resolve`.
2. Backend geocodes it (Maps) → upserts `properties` → resolves the jurisdiction chain (Mongo geo + Maps components).
3. User describes the project by voice → Voice Transcribe → text.
4. Orchestrator (Muse Spark) selects the jurisdiction agent(s) → the agents retrieve rules and reason → structured permit checklist with citations.
5. Optional: upload site photos → SAM 3.1 segments → features added to the agent context. Muse Image renders the proposal.
6. Results are stored in `agent_runs` / `cases` → rendered in the UI.

## 8. Deployment (Google Cloud Run)
- Two containers: `habita-frontend` (Next.js standalone output) and `habita-backend` (uvicorn).
- Images go to Artifact Registry (`$ARTIFACT_REGISTRY_REPO`). Secrets are mounted from Secret Manager as env vars. Each service runs as its own service account with minimal IAM.
- Details in [`infrastructure/README.md`](../infrastructure/README.md).

## 9. Jurisdiction agents
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

## 10. Out of scope until the build window
All of the above is design only. No routes, agents, schemas, or UI are implemented yet.
