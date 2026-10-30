# HABITA AI
Property intelligence that knows which rules apply where: resolve an address to its jurisdiction and competent
authority, ask a permitting question, and get an answer that is shown as **verified** only when every statement is
backed by an official source that HABITA retrieved, snapshotted and checked.

Built for the Meta Global AI Developer Hackathon. `main` holds the integrated MVP (HR-001 … HR-006 as described
below); development continues on the branch `mu9/structural-verification` and reaches `main` only by an explicit merge.

## The problem
Before buying, renovating or extending a property, owners and professionals must work out which municipality and
plan apply, what the plan says for that parcel, which procedure (licence, prior communication, exemption) the works
need, and which official documents back each answer. In Portugal that means reading the municipal master plan
(PDM), its maps and amendments, and national law (RJUE, RGEU) by hand. Generic AI assistants answer confidently and
without sources. HABITA answers with citations to official documents and refuses to call an answer verified when
the evidence does not support it.

## Architecture
| Layer | Technology | Role |
|---|---|---|
| Web app | Next.js (App Router) + React + TypeScript | address search, property workspace, map with post-its, permit questions, PDF download |
| API | Python FastAPI | property resolution, jurisdiction, official sources, permit workflow, verifier, reports |
| Database | MongoDB Atlas | properties, permit matters, evidence, verifications, official-source snapshots |
| Maps | Google Maps Platform | Places autocomplete, Geocoding, Maps JavaScript (map), Maps Static and Street View Static (PDF images, see HR-006) |
| AI | Meta Model API — **Muse Spark** (`muse-spark-1.3`) | planning, tool calls over official sources, drafting, a review that can only make a verdict stricter |
| Hosting | Google Cloud Run + Artifact Registry + Secret Manager | containers deployed manually; private staging with IAM authentication |

Details: [`docs/architecture.md`](docs/architecture.md), [`docs/environment.md`](docs/environment.md).

## Modules and their real state
Status words: **Done** = implemented and tested, including on real services where it applies · **Tested offline**
= implemented with automated tests, real-service validation pending · **Partial** · **Planned** = not implemented.

### HR-001 · Location and jurisdiction discovery — Done
Address search with Google Places autocomplete, Google geocoding, a jurisdiction chain (country → district →
municipality → parish) and the competent authority. Portugal is modelled; other countries get a generic chain.
Code: `backend/app/services/property_location.py`, `services/jurisdiction/`, `frontend/src/features/property/`.

### HR-002 · Permit Intelligence — Done
A question about a property becomes a private *matter* (capability token): the Meta model plans, calls retrieval
tools over the official sources, asks the user for missing facts and drafts an answer citing evidence; states are
persisted and resumable (PLANNING → NEEDS_INPUT → VERIFIED / ESCALATE / REJECTED / FAILED). Contributor-mode models
are refused. Code: `services/permit/`, `integrations/meta/`.

### HR-003 · Official sources, MU-9 legal verification — Partial (controlled validation)
- **Official sources:** a registry of Cascais and national sources (PDM regulation, amendments, planning maps, RJUE,
  RGEU…) with lifecycle states (candidate → validated → trusted → retired); trusted documents are fetched,
  snapshotted (sha256, version) and indexed for retrieval.
- **MU-9 structural verification:** every draft statement is decomposed and checked against the literal text of its
  cited evidence; trust pins, a single transactional commit with property-identity binding, an independent reviewer
  and a final gate decide the status. **A model cannot mark its own answer verified.** Definitive answers without
  property evidence are never VERIFIED; normative statements must use official wording.
- **Limitations (honest):** verification is structural and lexical, not semantic entailment, so some correct answers
  are rejected (fail-closed) and a few structural descriptions stay advisory; zoning has **no validated GIS
  connector**, so the classification always requires manual confirmation; the real MongoDB replica-set run of the
  identity binding is pending. These are tracked as research and debt items (see Roadmap).

### HR-004 · Map with post-its — Done (MVP); owner browser check pending
Notes over the Google map, all read from the same report model as the PDF: property with coordinates and precision
(**never presented as a parcel boundary**), municipality and competent authority; analysis status (also when no
assessment exists); zoning — a classification only from a verified layer, otherwise **"Zoning not verified"** with the
official plans to consult; risks and conditions; evidence and official sources with links. Tested with headless
Chromium on the private staging. Code: `frontend/src/features/report/`.

### HR-006 · PDF report — Done; real Google images validated locally, not yet on staging
A server-generated PDF from the same model: cover (status, municipality, authority, zoning state, and a permanent
warning that there is **no municipal confirmation**), property identification, a location page, planning context,
analysis, conditions, risks, verification record (protocol, TrustPin), evidence provenance (source, version,
snapshot, sha256, locator) and official sources, with the disclaimer on every page.

The location page embeds two images from the **Google Maps Static API** — a road map and a satellite image with
labels — with the same centre, zoom, size and marker, and a circle labelled **approximate location, not a cadastral
boundary** (HABITA holds no verified parcel geometry). A third image from **Street View** is added only when an outdoor
panorama exists within 50 m of the point, with its capture date. The legend states that Google imagery proves neither
ownership, parcel limits, zoning nor a municipal licence.

**Validated with real Google data (2026-10-30, local backend):** for "Praça 5 de Outubro, Cascais" the two maps and a
Street View image (panorama 6 m away, July 2024) were returned by Google for the geocoded centre and embedded in the
PDF, pixel-identical to Google's responses; no key appears in the PDF or the logs. A dedicated server key restricted to
Maps Static and Street View Static is kept in Secret Manager. Spend is capped (a daily limit shared by all instances,
per-minute and per-property limits). **Not yet on staging:** it needs an access grant for the staging backend and a
new deploy. If the map service is unavailable or unconfigured, the PDF says so and shows no substitute image.
Code: `backend/app/services/report/`, `backend/app/integrations/maps/static_maps.py`.

### Feature summary
| Feature | State |
|---|---|
| Address search, geocoding, jurisdiction, authority (HR-001) | Done |
| Permit matters with Muse Spark, follow-up questions, resume (HR-002) | Done |
| Official-source registry, snapshots, retrieval (HR-003) | Done for Cascais; other jurisdictions planned |
| MU-9 verification, TrustPin, reviewer, final gate (HR-003) | Tested offline and on staging; real replica-set binding run pending |
| Zoning classification from official GIS | Planned (no validated connector; absence stated) |
| Map with post-its (HR-004) | Done (MVP); owner browser check pending |
| PDF report with verification record and provenance (HR-006) | Done; tested on staging |
| PDF road map + satellite (+ Street View) images (HR-006) | Validated with real Google data locally; **staging pending** (access grant + deploy) |
| Private staging on Cloud Run | Done (IAM-authenticated, isolated database) |
| SAM 3.1 segmentation, Muse Voice Transcribe, Muse Image | Planned (integration points only) |
| HR-005, HR-007 … HR-015 | Pending definition |

## Private staging demo (authenticated)
A private staging runs on Cloud Run (`habita-backend-staging`, `habita-frontend-staging`) on an isolated database
(`habita_ai_staging`, its own least-privilege MongoDB user): no anonymous access, no public URL to open. It was
deployed from commit `1182201` and tested end to end on 2026-10-30 (address search in Cascais, map with post-its,
property and permit PDFs, a real VERIFIED matter). The HR-004/HR-006 changes after that commit are **not yet
deployed** there.

Access requires an authorised Google account and the official proxy, on the computer where the browser runs:
```bash
gcloud components install cloud-run-proxy
gcloud run services proxy habita-backend-staging  --region us-central1 --project habita-ai-512916 --port 8081
gcloud run services proxy habita-frontend-staging --region us-central1 --project habita-ai-512916 --port 3000
# then open http://localhost:3000 (a private window avoids conflicts between several Google accounts)
```
Procedure, checks, rollback and costs: [`infrastructure/STAGING.md`](infrastructure/STAGING.md).

## Run it locally
1. `cp .env.example .env` and fill in your own values. **Never commit secrets.** Without `MONGODB_URI` the backend
   uses in-memory storage (`ALLOW_EPHEMERAL_STORAGE=true`); without `META_API_KEY` Permit Intelligence reports that it
   is unavailable; without `MAPS_STATIC_API_KEY` (dedicated Maps Static + Street View key) the PDF states that the
   maps are unavailable.
2. Backend ([`backend/README.md`](backend/README.md)):
   ```bash
   cd backend && python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements-dev.txt
   python -m app.maintenance ingest-sources   # seeds and snapshots the official sources
   uvicorn app.main:app --reload --port 8000
   ```
3. Frontend ([`frontend/README.md`](frontend/README.md)): `cd frontend && npm ci && npm run dev` → http://localhost:3000
4. Demo path: search "Praça 5 de Outubro, Cascais" → workspace with map and post-its → ask a permitting question →
   answer the follow-up questions → download the PDF report. See [`docs/demo-runbook.md`](docs/demo-runbook.md).

## Tests
No credential is needed for the default suites:
```bash
cd backend && pytest                                   # offline suite, incl. an end-to-end Cascais run with a scripted model
cd frontend && npm test && npm run lint && npm run typecheck && npm run build
```
Last full run (2026-10-30, branch head before this README): backend **6605 passed, 14 skipped, 3 expected failures**
(known limitations kept as strict xfail); frontend **38 passed**, lint, typecheck and build clean. Live tests against
MongoDB Atlas and the Meta API are opt-in (`HABITA_LIVE_TESTS=1`, real credentials).

## Roadmap and technical debt
- Roadmap with acceptance criteria and evidence per module: [`docs/roadmap.md`](docs/roadmap.md) — HR-001/HR-002
  done; HR-003 in controlled validation; HR-004 MVP complete; HR-006 pending the real-map validation; HR-005 and
  HR-007…HR-015 pending definition.
- Main open items: redeploy staging with the latest HR-004/HR-006 code (including the real PDF images); set Google
  Cloud API quotas and review the Maps Platform terms for imagery in PDFs; improve answers to procedure questions (repeated zoning conditions, missing RJUE
  procedure citations); research semantic verification (entailment, negation scope, deontic logic) without weakening
  the deterministic final gate; validate an official GIS connector for zoning; real replica-set run of the identity
  binding.
- The maintainers keep a detailed technical-debt register (severity, evidence, tests, closure criteria) for these
  items.

## Repository layout
| Path | Purpose |
|---|---|
| `frontend/` | Next.js + React web app |
| `backend/` | FastAPI API, permit workflow, verifier, reports, maintenance commands |
| `docs/` | Architecture, environment, roadmap, demo runbook |
| `infrastructure/` | Container images, manual Cloud Run staging procedure and deploy script |

## Deployment and safety
There is no CI/CD: nothing deploys on push or merge; deployment is manual and authorised step by step
(`infrastructure/STAGING.md`). HABITA AI is decision support, not legal advice; its reports are not permits, licences
or authorisations — only the competent authority decides.
