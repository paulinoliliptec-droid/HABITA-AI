# HABITA AI
Property intelligence that knows which rules apply where: resolve an address to its jurisdiction and competent
authority, ask a permitting question, and get an answer that is shown as **verified** only when every statement is
backed by an official source that HABITA retrieved, snapshotted and checked.

Built for the Meta Global AI Developer Hackathon. `main` holds the integrated MVP (HR-001 … HR-012 as described
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
| Web app | Next.js (App Router) + React + TypeScript | landing page for the jury (`/`: how it works, Meta models used, limits, GitHub), live demo with the guided Cascais scenario (`/demo`), property workspace in areas (Question, Photos & plans, Before / after, Costs, Place; one at a time, linkable as `#costs`), map with post-its and report bar, permit questions, PDF download |
| API | Python FastAPI | property resolution, jurisdiction, official sources, permit workflow, verifier, reports |
| Database | MongoDB Atlas | properties, permit matters, evidence, verifications, official-source snapshots, file readings, concepts |
| Files | Google Cloud Storage (private bucket) | the user's photos and plans (kept without location or device data) and the generated concepts |
| Maps | Google Maps Platform | Places autocomplete, Geocoding, Maps JavaScript (map), Maps Static and Street View Static (PDF images, see HR-006) |
| AI | Meta Model API — **Muse Spark** (`muse-spark-1.3`) | planning, tool calls over official sources, drafting, a review that can only make a verdict stricter; reading the user's photos and plans (observations, people, plan or photo, the rooms of a plan) |
| Images | Meta Model API — **Muse Image** (`muse-image-1.0`, edit endpoint) | before/after concepts from the user's photos and views from a plan (3D, realistic, 3D with one more bedroom in the room the user chooses), always from HABITA's fixed instruction, with notices burned in (HR-012) |
| Language | Google Cloud Translation | Portuguese reading view of answers; fixed texts in reviewed catalogs |
| Aerial view | DGT official orthophotos (WMS, 2018) + Meta Model API — **SAM 3.1** (`sam-3.1`, masks decoded with Meta's `meta-sam-parser`) | buildings, small separate buildings and pools around the address point, measured from the image scale; observations that only add conditions to confirm with the Câmara |
| Voice input | Meta Model API — **Muse Voice Transcribe** (`muse-voice-transcribe-1.0`) | dictating the question or an answer instead of typing; the text goes into the box to review before sending; the recording is not kept |
| Voice output | ElevenLabs | spoken report, one voice per language; the browser's own voice as fallback |
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

### HR-003 · Official sources, MU-9 legal verification — In progress (controlled validation)
- **Official sources:** a registry of Cascais and national sources (PDM regulation, amendments, planning maps, RJUE,
  RGEU…) with lifecycle states (candidate → validated → trusted → retired); trusted documents are fetched,
  snapshotted (sha256, version) and indexed for retrieval.
- **MU-9 structural verification:** every draft statement is decomposed and checked against the literal text of its
  cited evidence; trust pins, a single transactional commit with property-identity binding, an independent reviewer
  and a final gate decide the status. **A model cannot mark its own answer verified.** Definitive answers without
  property evidence are never VERIFIED; normative statements must use official wording.
**For the hackathon, HABITA has:**
- **Whole-sentence verification of model text (live since 2026-11-02):** a sentence written by the model is VERIFIED
  only when it is one whole sentence of its cited record, word for word and with its punctuation, or a sentence HABITA
  itself builds from a structured record (who is competent, where the property is). A question or a reservation
  ("Confirm whether …", "… must be confirmed") can carry only "this", "the conditions" or one whole cited sentence.
  Rewording a record into a false fact no longer passes: "The owner sold the south unit." from "The owner of the
  south unit sold the north unit.", or a sentence that drops its condition, time or scope.
- **Measured results:** 0 of 14 structural attacks verify, in any of the five report sections (13 of 14 did before);
  0 false VERIFIED on the 32 negative cases of the dev benchmark; 7,514 backend tests pass, plus the identity-binding
  and ingestion tests on a MongoDB 8.0 replica set. Four rounds of independent review by Codex and Muse found and
  closed the paths listed in the repository's history.
- **A design for the next step**, on the branch [`hr003/empirical-verification-20261101`](https://github.com/paulinoliliptec-droid/HABITA-AI/tree/hr003/empirical-verification-20261101): structured legal
  claims ([design](https://github.com/paulinoliliptec-droid/HABITA-AI/blob/hr003/empirical-verification-20261101/docs/research/hr003-structured-claims-architecture.md)) with subject, deontic operator, conditions, exceptions, validity period, official evidence,
  parcel identity and trust state, built and rendered by HABITA instead of free text; an open NLI model only in
  shadow, never able to raise a verdict. The same branch holds typed answers to the structural questions (areas bound
  to units, ownership kind, work elements), a check of reservations against their own record, and the stage-2
  protocols.

**We still have these limitations, because verification is lexical and not semantic:**
- **Correct answers can be refused:** a faithful paraphrase, or a single clause of a longer cited sentence, is not
  certified (fail-closed). This costs availability, never safety.
- **Some residual cases depend on the records themselves:** a cited record that is itself a question, a record's
  title, or a jurisdiction level combined with another record's address could still be read as support. HABITA writes
  or curates these records, so the model alone cannot create them; they are tracked, and the last review round still
  reported them.
- **General explanations of a plan's structure** ("the plan classifies land into …") are advisory rather than
  enforced: enforcing them with today's rules would block every general explanation.
- **Zoning** has no validated official GIS connector, so the classification always asks for manual confirmation.
- **Not yet run:** the identity binding on Atlas, a shadow measurement on real answers and the live gate. Until then
  HR-003 stays in controlled validation; the structured claims above are the planned way out of word-level checks.

### HR-004 · Map with post-its — Done (MVP); owner browser check pending
Notes over the Google map, all read from the same report model as the PDF: property with coordinates and precision
(**never presented as a parcel boundary**), municipality and competent authority; analysis status (also when no
assessment exists); zoning — a classification only from a verified layer, otherwise **"Zoning not verified"** with the
official plans to consult; risks and conditions; evidence and official sources with links. Tested with headless
Chromium on the private staging. Code: `frontend/src/features/report/`.

### HR-006 · PDF report — Done; real Google images validated on the private staging
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
per-minute and per-property limits). **On the private staging** (commit `5734adc`, 2026-10-30) the PDF downloaded from
the workspace contains the three images. If the map service is unavailable or unconfigured, the PDF says so and shows
no substitute image.
Code: `backend/app/services/report/`, `backend/app/integrations/maps/static_maps.py`.

### HR-005 · Visual Reasoning Graph — Live; acceptance pending
A clickable graph from the property through rules, evidence and conditions to the conclusion, documents and next steps,
built only from relations stored in the report. Selecting a block lights its flow. It never invents causality or
authorisation.
Code: `frontend/src/features/report/reasoningGraph.ts`.

### HR-007 · Voice Explanation — Live; owner's listening test pending
The report can be heard with Listen, Pause, Resume, Repeat and Stop, with the sentence on screen. Audio is an
explanation, never legal proof: it opens and closes by saying so, follows the report's status rule and says every
pending item. The script is built on the backend from the stored report, and audio is requested by sentence position,
so the public endpoint cannot speak a caller's text. Each language has its own ElevenLabs voice. Spend is capped per
minute and per day, and a sentence already spoken is served from memory. If audio fails, the same sentence continues in
the browser's voice; if the report changed, the audio stops. The reader is told that the text goes to ElevenLabs.
Portuguese audio reads machine translation, labelled as such.
Code: `backend/app/services/report/voice.py`, `backend/app/integrations/speech/client.py`,
`frontend/src/features/report/VoiceExplanation.tsx`.

### HR-008 · Property Intelligence — Live; acceptance pending
A property profile says what is known and who said it. Official facts, observations and user declarations never mix,
each with origin, date and precision, and what is unknown is shown as not confirmed. Only a registered official source
makes a fact official; a user's answer stays a declaration, visible only to whoever can read that matter. When sources
disagree, both are shown. The profile changes no status. It opens in its own panel and also appears in the PDF and the
voice. It holds few items today: no source yet gives area, year, typology or land registry data.
Code: `backend/app/services/report/profile.py`, `frontend/src/features/report/ProfilePanel.tsx`.

### HR-009 · Intent & Permits — Live; acceptance pending
HABITA places a request in a closed catalog: dividing into units, change of use, interior works or general orientation.
It shows what it understood and the user can choose another type. New construction, extensions and demolition are not
covered yet and are stated as such, as is anything outside Cascais. HABITA holds no reviewed rule on which interior
works are exempt, so it never says they are: that stays a condition to confirm with the Câmara. MU-9 checks every type,
and many answers are conditional or rejected by design. Material warnings (for example the nullity of a horizontal
property title) are fixed text added by code, and the rules refuse an answer without them; next actions are written by
HABITA, not the model. Last real test on 2026-10-31: five cases, 4 VERIFIED with conditions; a small sample, and the
verified answers are short. The warnings have not had a legal review.
Code: `backend/app/services/permit/requirements.py`, `frontend/src/features/permit/PermitSection.tsx`.

### HR-010 · Multimodal Property Understanding — Live; acceptance pending
In a matter, the user can add photos and plans (JPEG, PNG, PDF; up to 10 files of 10 MB) after a consent notice that
says what goes to Meta and what HABITA keeps. The type is checked from the content, not the name. Capture date and GPS
are read first; a GPS point far from the property is shown as a mismatch that proves nothing. The kept copy, in a
private Cloud Storage bucket, has no location or device data: images are re-encoded from their pixels, PDFs lose their
document info. Each file keeps its SHA-256, date, kind and consent version. Muse Spark describes what is visible; HABITA
records it as an observation from the user's file, in the profile, the PDF and the voice, never as an official fact.
Files never reach the permit verification: they only add conditions to the report. When a file clearly shows an
entrance count, a possibly structural wall, a kitchen or bathroom, a facade or window, or several floors, the model picks
that from a closed list and HABITA adds its own fixed sentence saying what to confirm with the Câmara. Several files can
be chosen at once; they are read one after another. Real test on 2026-10-31: the kitchen pictures pointed to a
kitchen and a window, the plans to a kitchen, each with its fixed sentence in English and Portuguese. The user can view and
delete each file; deleting removes the kept copy. Readings are capped per minute, per day and per matter, and only a
file that passed its checks uses the daily budget. PDF plans are read only from a plain JPEG image; other PDFs are kept
but not read. Real test on 2026-10-31 with four synthetic files (a plan as PNG and as PDF, two room pictures with GPS
near and far): four Muse Spark readings, labels and figures described as shown and not as facts, GPS far shown as a
mismatch, no metadata left in the bucket copies, and every copy gone after deletion.
Code: `backend/app/services/files/`, `frontend/src/features/permit/PermitFiles.tsx`.

### HR-011 · AFFORD / Financial Feasibility — Live; acceptance pending
In a matter, the user can enter the area, their own quotes, a budget and a loan's rate, term and down payment. HABITA
shows the cost of the works as a range (lower, likely, higher), from the user's quotes when given and from a reference
table built from public price guides, cited, dated and approved by the owner on 2026-10-31 (an assumption, not a
market price). Financing
uses only the user's own rate and term, with the formula shown; there is no default rate. The market price comes from
INE official statistics for the municipality and parish (median bank valuation, median sale price over 12 months), from
a dated snapshot, each source shown apart. A municipality without statistics, or with an ambiguous name, shows no price.
Municipal fees are left to the Câmara. Every number is computed by code; no model writes one. It is an estimate with no
financial guarantee and never changes the assessment. Idealista and Casafari are not connected: they need the owner's
accounts. Code: `backend/app/services/afford/`, `frontend/src/features/permit/PermitAfford.tsx`.

### HR-012 · Visual Transformation — Live; acceptance pending
From one of their own photos (checked by the reader and found to show no people), the user can ask for a before/after
concept, choosing a change from a short list for the matter's type: new kitchen, new bathroom, floor and paint, a small
office layout, or a light partition. Nothing outside the building, nothing structural, no facade changes (owner
decision). Muse Image (`muse-image-1.0`, edit endpoint) gets the photo and HABITA's fixed instruction, never the user's
text. Every concept has a notice burned in, in Portuguese and English: "Concept generated by AI — not a project, not an
authorisation, not a promise of cost". From a plan (chosen as a plan, or recognised by the reader), the user can also
ask for a 3D view or a realistic image of the home, kept to the plan's layout, or a 3D view with one more bedroom
(made inside the home with one light partition, keeping every existing wall, column, door and window, never an
extension), with its own allowance of 3 per matter. These views carry a second burned-in notice, repeated in the PDF
and the spoken report, "May not match your plan exactly" / "Pode não corresponder exatamente à sua planta",
because in the real test of 2026-11-01 the model added a store room to one view and a stair to the other (owner chose
on 2026-11-01 to publish them as illustrations with that notice, provided a view does what is asked). The
one-more-bedroom view passed its real test on 2026-11-01 (synthetic two-bedroom plan: the living room divided by a
light partition with a door, every other room, window and the entrance kept, no stairs or extension). How a view is
judged against its plan (zero tolerance, fail-closed) is set out in
[`docs/hr012-plan-fidelity.md`](docs/hr012-plan-fidelity.md) (applied by hand before each publication of plan views, owner's choice of 2026-11-01; not automatic), with a matrix of 27 cases on five synthetic plans (T1, T3, a plan without areas, a tie for the largest room, a duplex) that must pass, fail or stay undecided, and 8 more for the chosen room. **The user chooses the room to divide** (owner, 2026-11-01; [`docs/hr012-room-choice-ux.md`](docs/hr012-room-choice-ux.md); live since 2026-11-01, `7fad9a9`): the plan reading also lists the rooms, only a living room, a bedroom or an office is offered, nothing is preselected ("the largest" is only marked), a very small room carries an RGEU warning, a plan whose rooms can't be read doesn't get this view, and on several floors the user picks the floor first; the instruction names the room in HABITA's fixed words only (type, place, floor), never the label read from the plan;
a plan is never redrawn by a photo change, since an AI-edited plan could pass for a project. The original and the
concept are shown side by side, and open large on a
click. The panel picks up a new photo as soon as it is added. At most 3 per matter and 50
a day; refusals and failed image calls cost nothing. Concepts are kept privately, go with their photo, and change nothing in the assessment.
Real test on 2026-10-31: two concepts (new kitchen; floor and paint) from a synthetic kitchen photo kept the room's
shape and window, showed no people and carried the notice.
Code: `backend/app/services/concepts/`, `frontend/src/features/permit/PermitConcepts.tsx`.

### Feature summary
| Feature | State |
|---|---|
| Address search, geocoding, jurisdiction, authority (HR-001) | Done |
| Permit matters with Muse Spark, follow-up questions, resume (HR-002) | Done |
| Official-source registry, snapshots, retrieval (HR-003) | Done for Cascais; other jurisdictions planned |
| MU-9 verification, TrustPin, reviewer, final gate (HR-003) | Tested offline and on staging; whole-sentence verification live (2026-11-02), limits listed in HR-003; replica-set binding tested on a local MongoDB 8.0 replica set, Atlas run pending |
| Zoning classification from official GIS | Planned (no validated connector; absence stated) |
| Map with post-its (HR-004) | Done (MVP); owner browser check pending |
| PDF report with verification record and provenance (HR-006) | Done; tested on staging |
| Reasoning graph (HR-005) | Live; acceptance pending |
| PDF road map + satellite (+ Street View) images (HR-006) | Validated with real Google data locally and on the private staging |
| Spoken report in Portuguese and English with ElevenLabs (HR-007) | Live; real audio generated, full listening test pending |
| Bilingual site, answers and PDF (Portuguese and English) | Live; Portuguese answers are labelled machine translation |
| Private staging on Cloud Run | Done (IAM-authenticated, isolated database) |
| Original (public demo) | Live; last updated 2026-11-01 (commit `8b4b8b2`) |
| Property profile: official, observed, declared (HR-008) | Live; acceptance pending |
| Request types with correction by the user (HR-009) | Live; acceptance pending |
| Photos and plans read as observations (HR-010) | Live; acceptance pending (consent wording not legally reviewed) |
| Costs, financing and market price (HR-011) | Live; acceptance pending |
| Before/after concepts from the user's photos, views from a plan, and the room the user chooses to divide (HR-012) | Live; acceptance pending |
| Seen from the air: DGT orthophoto + SAM 3.1 (buildings, annexes, pools; conditions to confirm) | Live since 2026-11-01 (`ac5ff3d`; `8b4b8b2`: addresses that point to an area, like a square, get a clear note asking for the door number instead of a disabled button); real analysis checked on the live candidate |
| Dictation with Muse Voice Transcribe (question and answers, PT/EN) | Live since 2026-11-01 (`b9a256b`); real transcription checked on the live candidate; owner's browser test pending |
| HR-013 … HR-015 | Pending definition |

## Private staging demo (authenticated)
A private staging runs on Cloud Run (`habita-backend-staging`, `habita-frontend-staging`) on an isolated database
(`habita_ai_staging`, its own least-privilege MongoDB user): no anonymous access, no public URL to open. It runs
commit `5734adc` (deployed and tested end to end on 2026-10-30).

## Live demo (original)
**https://habita-frontend-preview-jcyiz2arua-uc.a.run.app** — backend updated on 2026-11-02 to commit `1d03ab3`
(revision `00065`, TD-003 structural containment; `00063` is NOT a safe rollback: it brings back the old
verifier with the known false-VERIFIED paths, so a backend problem is fixed forward), frontend updated on 2026-11-02 to commit
`1917af1` (revision `00066`: landing page at `/`, live demo with the guided Cascais scenario at `/demo`, workspace
areas, "Property under analysis" map marker, graph and profile in HABITA colours; rollback revision `00064`), with the aerial view (DGT orthophotos + Meta SAM 3.1), dictation (Muse Voice Transcribe),, with the reasoning graph, the spoken report, the property profile, request types, photos and plans, costs and price, before/after concepts, and views from a plan (3D, realistic, 3D with one more bedroom in the room the user chooses). The MU-9 migration of its database
ran on 2026-10-30 (verified backup, audit, nothing deleted). Known open item: phone layout needs polish.
Tested there on 2026-10-30: address search in Cascais, map and satellite view, post-its, a real permit question (VERIFIED under the
current protocol) and the PDF with road map, satellite and Street View. A frontend rollback to its previous revision
is one command (`infrastructure/STAGING.md`); a backend rollback must not go to a revision older than `00065`. Historical results verified under the old protocol are never shown
as current VERIFIED: they read as superseded (legacy, not revalidated), with their original provenance.

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
4. Demo path: open `/demo` (or "Launch live demo" on `/`), choose "Praça 5 de Outubro, Cascais" → workspace with map and post-its → ask a permitting question in the
   Question area (opened first) → answer the follow-up questions → download the PDF report; photos and plans,
   before/after and costs each have their own area. See [`docs/demo-runbook.md`](docs/demo-runbook.md).

## Tests
No credential is needed for the default suites:
```bash
cd backend && pytest                                   # offline suite, incl. an end-to-end Cascais run with a scripted model
cd frontend && npm test && npm run lint && npm run typecheck && npm run build
```
Last full run (2026-11-02, TD-003 structural containment): backend **7514 passed, 29 skipped, 3 expected
failures** (known limitations kept as strict xfail), plus 23 replica-set and ingestion concurrency tests against a local
MongoDB 8.0 replica set; frontend unchanged since its last run (2026-11-01: **89 passed**, lint, typecheck and build clean). Live tests against
MongoDB Atlas and the Meta API are opt-in (`HABITA_LIVE_TESTS=1`, real credentials).

## Roadmap and technical debt
- Roadmap with acceptance criteria and evidence per module: [`docs/roadmap.md`](docs/roadmap.md) — HR-001/HR-002
  done; HR-003 in controlled validation (whole-sentence verification live; Atlas, shadow and live gates not run); HR-004 and HR-006 MVP complete (why, and what would make them full: roadmap "Why HR-004 and HR-006 are MVP complete"); HR-005, HR-007, HR-008 and HR-009 to HR-012 live, acceptance pending;
  HR-013…HR-015 pending definition.
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
