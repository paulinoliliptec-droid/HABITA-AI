# HABITA AI
Property intelligence that knows which rules apply where: resolve an address to its jurisdiction and competent
authority, ask a permitting question, and get an answer that is shown only as **verified** when every statement is
backed by an official source that HABITA retrieved and checked.

Built for the Meta Global AI Developer Hackathon. Development happens on the branch `mu9/structural-verification`;
`main` holds the first vertical slice.

## What works today (real, tested)
| Feature | What it does | Where |
|---|---|---|
| Property → location → jurisdiction | Address search with Google Places autocomplete, Google geocoding, jurisdiction chain (country → municipality) and competent authority; Portugal modelled, other countries generic. | `backend/app/services/property_location.py`, `services/jurisdiction/`, `frontend/src/features/property/` |
| Property map | Google Maps workspace with the highlighted property. | `PropertyMap.tsx` |
| Official sources & planning context | A registry of official sources (Cascais PDM, national legislation); trusted PDFs are fetched, snapshotted (sha256, version) and indexed. Zoning is **never guessed**: without a validated machine-readable layer, HABITA says so and lists the official maps to consult. | `services/sources/`, `services/planning/` |
| Permit Intelligence | A question about a property becomes a private *matter*: the Meta model (Muse Spark) plans, calls retrieval tools over the official sources, asks the user for missing facts and drafts an answer citing evidence. | `services/permit/`, `integrations/meta/` |
| MU-9 structural verification | Every draft statement is decomposed and checked against the literal text of its cited evidence; trust pins, a single transactional commit and a final gate decide VERIFIED / NEEDS_INPUT / ESCALATE / REJECTED. A model cannot mark its own answer verified. | `services/permit/verifier*.py`, `docs/architecture.md` |
| Map post-its (HR-004) | Notes over the map: property and authority, zoning (or its verified absence), assessment status, risks, legal sources with official links. | `frontend/src/features/report/` |
| PDF report (HR-006) | A server-generated report from the same model as the post-its: status banner (VERIFIED / REJECTED / PENDING CONFIRMATION), analysis, conditions, risks, verification record with trust pin, evidence provenance (source, version, snapshot, sha256, locator). | `backend/app/services/report/` |

## Meta AI technologies
- **Used:** the Meta Model API with **Muse Spark** (`META_TEXT_MODEL`, default `muse-spark-1.3`) for the permit
  workflow: planning, tool calls over official sources, drafting and a model review that can only make a verdict
  stricter. Contributor-mode models are refused (`integrations/meta/client.py`).
- **Planned, not implemented:** SAM 3.1 segmentation, Muse Voice Transcribe, Muse Image (named in
  `docs/architecture.md`; no code yet — see `docs/roadmap.md`).

## Limitations (honest)
- Zoning layers: no validated GIS connector exists yet, so no zoning polygon or classification is ever shown; the
  planning classification always requires manual confirmation.
- Live validation of HR-003 against MongoDB Atlas and the Meta API is opt-in and pending (see `docs/roadmap.md`).
- HABITA is decision support, not legal advice; reports are not permits.
- Roadmap: HR-001/002 done, HR-003 in controlled validation, HR-004/006 in progress, others pending definition.

## Repository layout
| Path | Purpose |
|---|---|
| `frontend/` | Next.js + React web app |
| `backend/` | Python FastAPI API, permit workflow, verifier, reports |
| `docs/` | Architecture, environment, roadmap, demo runbook |
| `infrastructure/` | Container images and the manual Cloud Run procedure |

## Run it locally (reproduce the demo)
1. `cp .env.example .env` and fill in your own values. **Never commit secrets.** Without `MONGODB_URI` the backend
   uses in-memory storage (`ALLOW_EPHEMERAL_STORAGE=true`); without `META_API_KEY` Permit Intelligence says it is
   unavailable and everything else works.
2. Backend: see `backend/README.md` (`pip install -r requirements-dev.txt`, `uvicorn app.main:app --port 8000`;
   `python -m app.maintenance ingest-sources` seeds and snapshots the official sources).
3. Frontend: see `frontend/README.md` (`npm ci`, `npm run dev` → http://localhost:3000).
4. Demo path: search "Praça 5 de Outubro, Cascais" → workspace with map and post-its → ask a permitting question →
   answer the follow-up questions → download the PDF report.

Tests without any credential: `cd backend && pytest` (offline suite, includes an end-to-end Cascais run with a
scripted model) and `cd frontend && npm test && npm run lint && npm run typecheck`.

There is no CI/CD: nothing deploys on push or merge. Deployment is manual (`infrastructure/STAGING.md`).
