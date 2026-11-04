<p align="center">
  <img src="frontend/src/app/icon.png" width="110" height="110" alt="HABITA AI logo">
</p>

<h1 align="center">HABITA AI</h1>

<p align="center"><b>Can I build here? Answers about a real property, checked against the official rules of a real place.</b></p>

<p align="center">
  <a href="https://www.youtube.com/watch?v=UInq7hNPPz4">▶ Demo video</a> ·
  <a href="https://habita-frontend-preview-jcyiz2arua-uc.a.run.app">🌐 Live demo</a> ·
  <a href="https://habita-frontend-preview-jcyiz2arua-uc.a.run.app/demo">Guided Cascais scenario</a>
</p>

Property intelligence that knows which rules apply where: resolve an address to its jurisdiction and competent
authority, ask a permitting question, and get an answer that is shown as **verified** only when every statement is
backed by an official source that HABITA retrieved, snapshotted and checked.

Built for the Meta Global AI Developer Hackathon. `main` holds the integrated MVP (modules HR-001 … HR-012, described
below).

## For the judges, in one minute
| | |
|---|---|
| ▶ **Demo video** | [HABITA AI — Can I Build Here?](https://www.youtube.com/watch?v=UInq7hNPPz4) |
| 🌐 **Live demo** | [habita-frontend-preview-jcyiz2arua-uc.a.run.app](https://habita-frontend-preview-jcyiz2arua-uc.a.run.app). No account needed. Press "Try the live demo", or open [`/demo`](https://habita-frontend-preview-jcyiz2arua-uc.a.run.app/demo), which starts at Rua Frederico Arouca 30, Cascais, and reaches every feature |
| 🏛️ **What makes it different** | Real rules of a real place, not sample data or a fictional city: the Cascais municipal master plan (PDM) and Portuguese national law (RJUE, RGEU), retrieved from official sources and snapshotted. An answer is shown as **verified** only when the MU-9 verifier finds every statement supported by those records; otherwise HABITA says what is missing |
| 🛠️ **Built entirely during the hackathon** | Nothing was built before the event. The repository started empty on 2026-10-26, the hackathon's first day: the first commit (`041831f`, 18:39 UTC) holds only `.gitignore`, `LICENSE` and a two-line README. Every line of code, every data connector and every test came after it; see [How it was built](#how-it-was-built-one-developer-three-coding-agents-muse-code-as-reviewer) and the dated commit history |
| 📍 **Real data, nothing fictional** | The demo runs on real addresses and the real official sources of the municipality of Cascais; see [Real data from Cascais](#real-data-from-the-municipality-of-cascais) |
| 📊 **Measured** | **0 unsupported answers shown as verified** across the 294 cases of the verifier's acceptance corpus, 212 of them attacks (a changed figure, a dropped condition, words recombined from different sources, an invented fact); about 4 ms per check. The verifier is deliberately cautious: 3 of its 8 legitimate test answers are still left unverified rather than risk a false "verified". **7602 backend tests passing**, more than 340 commits since 2026-10-26. Reproduce with `cd backend && python -m tests.mu9_acceptance` and `pytest` |
| 🌍 **Proof, then scale** | **Cascais is the proof that it works**: deep, verified coverage on real official sources. **New York City, Paris and Singapore show that it scales**: the same pipeline already resolves their competent authorities, planning rules, market data and (New York, Paris) official aerial imagery from official sources, as partial coverage; see [Partial coverage](#partial-coverage-new-york-paris-and-singapore) |
| ⚖️ **Limits** | Information, not legal advice. Deep verified coverage is Cascais today; New York City, Paris and Singapore are partial coverage. Open items are listed in [Roadmap and technical debt](#roadmap-and-technical-debt) |

### Real data from the municipality of Cascais
HABITA does not use sample data, a fictional city or invented rules. What a user sees for a Cascais address comes from
real, public, official sources, retrieved and snapshotted with their origin:

| Source | Used for |
|---|---|
| Câmara Municipal de Cascais (`cascais.pt`) | The municipal master plan (PDM) and its regulation, municipal procedures and forms |
| GeoCascais, the municipality's GIS (`geocascais.cascais.pt`) | Registered as an official source; reading the zoning class from it is still planned (see the feature summary) |
| Diário da República (`diariodarepublica.pt`) | National law and the published PDM: RJUE (urban development and building), RGEU (general building regulation) |
| DGT, Direção-Geral do Território | Official aerial photos (orthophotos, WMS) read by SAM 3.1 |
| INE, Statistics Portugal (`ine.pt`) | Official housing-market statistics used in the costs and price module |

The reference address of the demo, Rua Frederico Arouca 30, is a real street in Cascais. The only synthetic files in the
project are the photos and plans we made ourselves to test the upload features (described in HR-010 and HR-012); they
are never presented as official data.

### Partial coverage: New York, Paris and Singapore
To show that HABITA grows to other places without changing how answers are checked, three cities have partial
coverage: the authority that decides on building permits, its official sources, official market prices and, where an
official aerial photo exists, the aerial view. Every source below is real and official; their links were checked on
2026-11-02. Deep, verified permit answers are still Cascais only.

| City | Who decides | Official rules | Market prices | Aerial photo |
|---|---|---|---|---|
| **New York City** | NYC Department of Buildings | NYC Zoning Resolution (Department of City Planning, `zr.planning.nyc.gov`), New York City Charter | NYC property sales, NYC Open Data (`data.cityofnewyork.us`) | NYS Statewide Digital Orthoimagery (`orthos.its.ny.gov`) |
| **Paris** | Maire de Paris | Plan Local d'Urbanisme de Paris and the Plans de Sauvegarde et de Mise en Valeur (`paris.fr`), Code de l'urbanisme | DVF property transactions (`data.gouv.fr`) | IGN Géoplateforme, BD ORTHO (`data.geopf.fr`) |
| **Singapore** | Urban Redevelopment Authority (URA) | URA Master Plan and Development Control Guidelines (`ura.gov.sg`), Building and Construction Authority (`bca.gov.sg`), Planning Act 1998 | HDB resale prices (`data.gov.sg`) | not available |

### Meta models in the product
| Meta model | What it does in HABITA |
|---|---|
| **Muse Spark** (`muse-spark-1.3`) | Plans the answer, calls tools over the official sources, drafts it, runs a review that can only make the verdict stricter, and reads the user's photos and plans |
| **Muse Spark Open** (`meta-models/muse-spark-open-1026`, open weights on Baseten) | Fallback when Muse Spark is unavailable, and a model the reader can choose for the report copilot, under the same MU-9 verifier and guards |
| **SAM 3.1** (`sam-3.1`) | Outlines buildings, annexes and pools on the official DGT aerial photo, measured from the image scale |
| **Muse Voice Transcribe** (`muse-voice-transcribe-1.0`) | Dictation of the question and the answers, in Portuguese and English |
| **Muse Image** (`muse-image-1.0`) | Before/after concepts from the user's photos and views from a plan, always labelled as AI concepts |
| **Muse Code** (1.4.13) | Independent reviewer during development: attacks on the legal verifier and an interface review (see [How it was built](#how-it-was-built-one-developer-three-coding-agents-muse-code-as-reviewer)) |

## The problem
**Anyone who wants to buy, divide, convert, renovate or invest in a home cannot easily find out what they are allowed
to do, what it will cost and whether it is legal.** The answer is scattered across municipal plans and their maps,
national law, procedures that change with the type of works, cadastral and aerial data, market statistics and the
property's own papers, photos and plans. Each piece lives with a different authority, in a different format and often
in a language of its own. Professionals spend days putting it together; owners usually guess, and a wrong guess costs
months, fines or a sale that falls through. Generic AI assistants make it worse: they answer confidently, without
sources, and cannot tell a rule from a guess.

HABITA AI brings those pieces into one place around one property, and says plainly what is verified, what is
declared, what is only observed and what is still unknown:

| Part of the problem | What HABITA does | Module |
|---|---|---|
| "Which rules apply here, and who decides?" | Resolves the address to its jurisdiction chain and competent authority | HR-001 |
| "What exactly am I asking for?" | Places the request in a closed catalogue (division into units, change of use, interior works) and asks only the facts it needs | HR-002, HR-009 |
| "Is the answer true?" | Retrieves official documents and snapshots them; MU-9 checks each statement against its cited records (official text, or records HABITA builds from them) and refuses to call an answer **verified** when they do not support it — limits listed under HR-003 | HR-003 |
| "Show me, on the ground" | Map with post-its, official aerial photo with outlines from Meta SAM 3.1, a clickable reasoning graph from property to conclusion | HR-004, HR-005 |
| "I need something to keep and share" | A PDF report with its verification record, sources and integrity seal; the same report spoken aloud | HR-006, HR-007 |
| "What do we actually know about this property?" | A profile that keeps official facts, the user's declarations and observations apart, each with its origin | HR-008 |
| "Here are my photos and plans" | Reads them as observations (never as official facts), strips location data, says what to confirm with the authority | HR-010 |
| "Can I afford it?" | Cost ranges, the user's own financing, official market statistics, every number computed by code | HR-011 |
| "What could it look like?" | Before/after concepts and views from a plan, labelled as AI concepts, never as projects | HR-012 |

The deep, verified coverage today is **Cascais (Portugal)**; the architecture (a jurisdiction chain, a registry of
official sources per jurisdiction, and a verifier that refuses what those sources do not support) is built to add
other places without changing how answers are checked.

## Architecture
| Layer | Technology | Role |
|---|---|---|
| Web app | Next.js (App Router) + React + TypeScript | landing page for the jury (`/`: a photo of Cascais, a large "Try the live demo" button with a note for the jury, how it works, Meta models used, limits, GitHub), live demo with the guided Cascais scenario (`/demo`, starting at Rua Frederico Arouca 30, which reaches every feature including the aerial view; New York, Paris and Singapore as partial-coverage examples), property workspace in areas (Question, Photos & plans, Before / after, Costs, Place; one at a time, linkable as `#costs`), map with post-its and report bar, permit questions, PDF download |
| API | Python FastAPI | property resolution, jurisdiction, official sources, permit workflow, verifier, reports |
| Database | MongoDB Atlas | properties, permit matters, evidence, verifications, official-source snapshots, file readings, concepts |
| Files | Google Cloud Storage (private bucket) | the user's photos and plans (kept without location or device data) and the generated concepts |
| Maps | Google Maps Platform | Places autocomplete, Geocoding, Maps JavaScript (map), Maps Static and Street View Static (PDF images, see HR-006) |
| AI | Meta Model API — **Muse Spark** (`muse-spark-1.3`); fallback when it is unavailable: **Muse Spark open** on Baseten (`meta-models/muse-spark-open-1026`), see [open models](infrastructure/open-models/README.md) | planning, tool calls over official sources, drafting, a review that can only make a verdict stricter; reading the user's photos and plans (observations, people, plan or photo, the rooms of a plan) |
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
municipality → parish) and the competent authority. Portugal is modelled. **New York City, Paris and Singapore have
partial coverage** (2026-11-02): HABITA names the authority that decides (building permits: NYC Department of
Buildings, Maire de Paris under the PLU or, in the safeguarded sectors, a PSMV; in Singapore, planning permission from
the URA, with building plans approved by the BCA) and the official sources to consult, each linked or cited; it has not verified their
rules, so the workspace says so and does not draft a permit answer there. They also get, from official open data:
- **the aerial view** (Meta SAM 3.1) on the official orthophoto: IGN Géoplateforme BD ORTHO for Paris (Licence Ouverte
  2.0) and the NYS Statewide Digital Orthoimagery for New York City; the source is chosen by the property's
  jurisdiction and its attribution is burned into the image. **Singapore has none**: the OneMap terms restrict storing
  and modifying the imagery, so it waits for the Singapore Land Authority's confirmation;
- **official market prices**, medians HABITA computes from real sales (snapshot of 2026-11-03,
  `python -m app.services.afford.international`): DVF 2025 for each Paris arrondissement (€/m² of single-apartment
  sales), NYC Department of Finance 2025 sales by borough (median price of homes), HDB resale flats over the last 12
  months for Singapore (S$/m², public housing only). Statistics of past sales, never a valuation.

**Why Cascais first:** a verified permit answer needs each place's official sources ingested, checked and its law
reviewed, and that takes more than the hackathon's nine days per jurisdiction. We chose depth in one municipality,
Cascais, built end to end as the reference, and gave the other cities the minimum that shows the same pipeline
working there (authority, official sources, aerial view, official prices).

**Not built there yet, by design:** verified permit answers, the request catalogue and its fixed
warnings, works costs and financing, and the PDF's aerial figure. They need each place's official sources ingested and
checked, and its law reviewed. These cities are a proof of scale: the same jurisdiction chain, source registry,
verifier, aerial pipeline and price snapshot extend to other legal systems. Other countries get a generic chain
without an authority.
Code: `backend/app/services/property_location.py`, `services/jurisdiction/`, `frontend/src/features/property/`.

### HR-002 · Permit Intelligence — Done
A question about a property becomes a private *matter* (capability token): the Meta model plans, calls retrieval
tools over the official sources, asks the user for missing facts and drafts an answer citing evidence; states are
persisted and resumable (PLANNING → NEEDS_INPUT → VERIFIED / ESCALATE / REJECTED / FAILED). Contributor-mode models
are refused. Code: `services/permit/`, `integrations/meta/`.

### HR-003 · Official sources, MU-9 legal verification — Live (fail-closed)
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
  and ingestion tests on a MongoDB 8.0 replica set. Adversarial review rounds by Codex and Muse Code found and
  closed the paths listed in the repository's history.
- **A design for the next step**, on the branch [`hr003/empirical-verification-20261101`](https://github.com/paulinoliliptec-droid/HABITA-AI/tree/hr003/empirical-verification-20261101): structured legal
  claims ([design](https://github.com/paulinoliliptec-droid/HABITA-AI/blob/hr003/empirical-verification-20261101/docs/research/hr003-structured-claims-architecture.md)) with subject, deontic operator, conditions, exceptions, validity period, official evidence,
  parcel identity and trust state, built and rendered by HABITA instead of free text; an open NLI model only in
  shadow, never able to raise a verdict. The same branch holds typed answers to the structural questions (areas bound
  to units, ownership kind, work elements), a check of reservations against their own record, and the stage-2
  protocols.

**How it behaves:**
- **Fail-closed by design:** when an answer cannot be tied word for word to an official record, it is not certified
  and stays PENDING CONFIRMATION; a correct paraphrase may be refused, a wrong one never certified.
- **General explanations of a plan's structure** ("the plan classifies land into …") are shown as explanations, not
  as verified statements.
- **Zoning** has no validated official GIS connector yet, so the classification always asks for manual confirmation.
- **Next step:** the structured claims above, so that legal statements are built from fields instead of free text.

### HR-004 · Map with post-its — Done (MVP)
Notes over the Google map, all read from the same report model as the PDF: property with coordinates and precision
(**never presented as a parcel boundary**), municipality and competent authority; analysis status (also when no
assessment exists); zoning — a classification only from a verified layer, otherwise **"Zoning not verified"** with the
official plans to consult; risks and conditions; evidence and official sources with links. Tested with headless
Chromium on the private staging. Code: `frontend/src/features/report/`.

**Added for the hackathon (2026-11-02):** a "Property under analysis" label on the marker, whose card gives the
address, municipality and precision ("a point, not a parcel boundary"), links to this browser's photos, plans and
concepts, and "Open the analysis"; one **Layers** button with the base map (map, satellite) and the overlays; the
**aerial view** as a map layer (the DGT orthophoto with HABITA's Meta SAM 3.1 outlines, placed at its own extent,
always with its source, year and "approximate, not a survey or a parcel boundary"); and "See in the graph" on every
note, which opens the reasoning graph on that note's block.

**Still limited, and why:** the municipal plan (PDM) maps are listed in Layers but unavailable, because no documented
official map service publishes Cascais's PDM plans (SNIG catalogue, DGT and the municipal GeoCascais checked on
2026-11-02) and HABITA does not probe undocumented endpoints; the official PDF plans stay linked in the notes. No
parcel outline is drawn: Cascais has only the old rustic geometric cadastre, the urban properties of the demo are not
covered, and an invented outline would mislead. Photos carry no location by design (removed on upload), so they are
not pinned on the map.

### HR-006 · PDF report — Done
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
**Polished for the hackathon (2026-11-02):** HABITA's mark on the cover and its name on every page; official sources
grouped by publisher, one line each, with the long links and the full trust pin in an audit annex (evidence provenance
stays complete, AC6.3); the reasoning graph groups evidence like the web graph and fits on the "at a glance" page; the
aerial view (DGT orthophoto with the SAM 3.1 outlines and its notice) on the location page; up to four of the
matter's before/after concept images, with their burned-in notices (matter reports only); an integrity seal: the
report's fingerprint (sha256 of its stored content) and the property's public link. The sample report went from 13 to
11 pages. Still open: fonts are Latin only (TD-021), and the Google terms for imagery in downloadable PDFs need a legal
check (TD-055).
Code: `backend/app/services/report/`, `backend/app/integrations/maps/static_maps.py`.

### HR-005 · Visual Reasoning Graph — Live
A clickable graph from the property through rules, evidence and conditions to the conclusion, documents and next steps,
built only from relations stored in the report. Selecting a block lights its flow. It never invents causality or
authorisation.
**Polished for the hackathon (2026-11-02):** HABITA's paper and forest-green colours instead of the deep blue; on phones
and tablets the same blocks and relations as a list of steps, each block opening its detail under it; all six columns
visible on laptop and desktop screens (the detail goes under the graph when both don't fit); blocks tall enough for
their text, with the full text on hover; calm motion (text fades in, only the selected flow pulses, nothing with
reduced motion); a legend for the colours and the dashed line; arrow keys move between blocks; each map note opens
its own block. Report texts arrive in the reader's language (the backend translates them); the user's own question
stays as written.
Code: `frontend/src/features/report/reasoningGraph.ts`.

**Polish for the hackathon across HR-007…HR-012 (2026-11-02):** the voice no longer cuts a sentence after an ordinal,
a decimal or an abbreviation ("2.º Trimestre", "Art. 67.º") and says a doubled end ("..", "?.") once; dictation drops
the stray full stop after a question; INE periods read "Q2 2026" / "September 2026" for English readers; plan labels
in capitals ("KITCHEN") are now translated instead of keeping the whole sentence in English (the translation check took
them for acronyms); the property profile uses HABITA's serif. Already in place and checked: the voice's spend ceiling
(daily cap shared by instances, per-minute bucket, cached sentences) and the before/after gallery on phones. Still open:
a lawyer-reviewed fixed procedure per request type (HR-009, TD-067), which HABITA does not write on its own.

### HR-007 · Voice Explanation — Live
The report can be heard with Listen, Pause, Resume, Repeat and Stop, with the sentence on screen. Audio is an
explanation, never legal proof: it opens and closes by saying so, follows the report's status rule and says every
pending item. The script is built on the backend from the stored report, and audio is requested by sentence position,
so the public endpoint cannot speak a caller's text. Each language has its own ElevenLabs voice. Spend is capped per
minute and per day, and a sentence already spoken is served from memory. If audio fails, the same sentence continues in
the browser's voice; if the report changed, the audio stops. The reader is told that the text goes to ElevenLabs.
Portuguese audio reads machine translation, labelled as such.
Code: `backend/app/services/report/voice.py`, `backend/app/integrations/speech/client.py`,
`frontend/src/features/report/VoiceExplanation.tsx`.

### HR-008 · Property Intelligence — Live
A property profile says what is known and who said it. Official facts, observations and user declarations never mix,
each with origin, date and precision, and what is unknown is shown as not confirmed. Only a registered official source
makes a fact official; a user's answer stays a declaration, visible only to whoever can read that matter. When sources
disagree, both are shown. The profile changes no status. It opens in its own panel and also appears in the PDF and the
voice. It holds few items today: no source yet gives area, year, typology or land registry data.
Code: `backend/app/services/report/profile.py`, `frontend/src/features/report/ProfilePanel.tsx`.

### HR-009 · Intent & Permits — Live
HABITA places a request in a closed catalog: dividing into units, change of use, interior works or general orientation.
It shows what it understood and the user can choose another type. New construction, extensions and demolition are not
covered yet and are stated as such, as is anything outside Cascais. HABITA holds no reviewed rule on which interior
works are exempt, so it never says they are: that stays a condition to confirm with the Câmara. MU-9 checks every type,
and many answers are conditional or rejected by design. Material warnings (for example the nullity of a horizontal
property title) are fixed text added by code, and the rules refuse an answer without them; next actions are written by
HABITA, not the model. Last real test on 2026-10-31: five cases, 4 VERIFIED with conditions; a small sample, and the
verified answers are short. The warnings have not had a legal review.
Code: `backend/app/services/permit/requirements.py`, `frontend/src/features/permit/PermitSection.tsx`.

### HR-010 · Multimodal Property Understanding — Live
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

### HR-011 · AFFORD / Financial Feasibility — Live
In a matter, the user can enter the area, their own quotes, a budget and a loan's rate, term and down payment. HABITA
shows the cost of the works as a range (lower, likely, higher), from the user's quotes when given and from a reference
table built from public price guides, cited, dated and reviewed by us on 2026-10-31 (an assumption, not a
market price). Financing
uses only the user's own rate and term, with the formula shown; there is no default rate. The market price comes from
INE official statistics for the municipality and parish (median bank valuation, median sale price over 12 months), from
a dated snapshot, each source shown apart. A municipality without statistics, or with an ambiguous name, shows no price.
Municipal fees are left to the Câmara. Every number is computed by code; no model writes one. It is an estimate with no
financial guarantee and never changes the assessment. Idealista and Casafari are not connected: they need commercial
accounts. Code: `backend/app/services/afford/`, `frontend/src/features/permit/PermitAfford.tsx`.

### HR-012 · Visual Transformation — Live
From one of their own photos (checked by the reader and found to show no people), the user can ask for a before/after
concept, choosing a change from a short list for the matter's type: new kitchen, new bathroom, floor and paint, a small
office layout, or a light partition. Nothing outside the building, nothing structural, no facade changes (a design
decision). Muse Image (`muse-image-1.0`, edit endpoint) gets the photo and HABITA's fixed instruction, never the user's
text. Every concept has a notice burned in, in Portuguese and English: "Concept generated by AI — not a project, not an
authorisation, not a promise of cost". From a plan (chosen as a plan, or recognised by the reader), the user can also
ask for a 3D view or a realistic image of the home, kept to the plan's layout, or a 3D view with one more bedroom
(made inside the home with one light partition, keeping every existing wall, column, door and window, never an
extension), with its own allowance of 3 per matter. These views carry a second burned-in notice, repeated in the PDF
and the spoken report, "May not match your plan exactly" / "Pode não corresponder exatamente à sua planta",
because in the real test of 2026-11-01 the model added a store room to one view and a stair to the other (we chose
on 2026-11-01 to publish them as illustrations with that notice, provided a view does what is asked). The
one-more-bedroom view passed its real test on 2026-11-01 (synthetic two-bedroom plan: the living room divided by a
light partition with a door, every other room, window and the entrance kept, no stairs or extension). How a view is
judged against its plan (zero tolerance, fail-closed) is set out in
[`docs/hr012-plan-fidelity.md`](docs/hr012-plan-fidelity.md) (applied by hand before each publication of plan views, our choice of 2026-11-01; not automatic), with a matrix of 27 cases on five synthetic plans (T1, T3, a plan without areas, a tie for the largest room, a duplex) that must pass, fail or stay undecided, and 8 more for the chosen room. **The user chooses the room to divide** (owner, 2026-11-01; [`docs/hr012-room-choice-ux.md`](docs/hr012-room-choice-ux.md); live since 2026-11-01, `7fad9a9`): the plan reading also lists the rooms, only a living room, a bedroom or an office is offered, nothing is preselected ("the largest" is only marked), a very small room carries an RGEU warning, a plan whose rooms can't be read doesn't get this view, and on several floors the user picks the floor first; the instruction names the room in HABITA's fixed words only (type, place, floor), never the label read from the plan;
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
| MU-9 verification, TrustPin, reviewer, final gate (HR-003) | Whole-sentence verification live (2026-11-02), limits listed in HR-003; replica-set binding tested on a local MongoDB 8.0 replica set, Atlas run pending |
| Fallback for the reasoning model when Muse Spark is unavailable: Muse Spark open on Baseten (Modal prepared, off); same MU-9 verifier | Live since 2026-11-03 (backend `00071`) — `infrastructure/open-models/` |
| Zoning classification from official GIS | Planned (no validated connector; absence stated) |
| Map with post-its (HR-004) | Done (MVP) |
| PDF report with verification record and provenance (HR-006) | Done |
| Reasoning graph (HR-005) | Live |
| PDF road map + satellite (+ Street View) images (HR-006) | Live; validated with real Google data |
| Spoken report in Portuguese and English with ElevenLabs (HR-007) | Live |
| Bilingual site, answers and PDF (Portuguese and English) | Live; Portuguese answers are labelled machine translation |
| Public live demo | Live; see [Live demo](#live-demo) |
| Property profile: official, observed, declared (HR-008) | Live |
| Request types with correction by the user (HR-009) | Live |
| Photos and plans read as observations (HR-010) | Live (consent wording not yet reviewed by a lawyer) |
| Costs, financing and market price (HR-011) | Live |
| Before/after concepts from the user's photos, views from a plan, and the room the user chooses to divide (HR-012) | Live |
| Report copilot, live (2026-11-03): bottom-right, questions by text or dictation (dictation sends by itself after 10 s of silence), the reader chooses the model, Muse Spark (Meta Model API) or Muse Spark Open (Meta's open weights, `meta-models/muse-spark-open-1026` on Baseten; same prompt, schema, limits and status/number guards; each answer names its model), answers spoken in the ElevenLabs voice of the reader's language (the server speaks only answers it gave, by an id valid 30 minutes; the browser's voice if that audio can't be had); only about the report the reader sees | Live; real checks with Muse Spark and Muse Spark Open (a zoning question answered from the report; a cost question refused; an injection asking to say VERIFIED never reached the reader). Limits: an answer naming a status the report lacks, or a number it doesn't contain, is replaced by a fixed reply; free wording isn't checked word by word, so the screen shows the report's own status beside every answer and labels it an explanation, not a verification or legal advice |
| Meta terms (2026-11-03): before the demo and the workspace, visitors confirm they are 18+ and not in Meta's restricted territories (and not in India, for Muse Image) | Live. A notice and confirmation, not network blocking (that needs a load balancer) |
| Seen from the air: DGT orthophoto + SAM 3.1 (buildings, annexes, pools; conditions to confirm) | Live since 2026-11-01 (`ac5ff3d`; `8b4b8b2`: addresses that point to an area, like a square, get a clear note asking for the door number instead of a disabled button); real analysis checked on the live candidate |
| Dictation with Muse Voice Transcribe (question and answers, PT/EN) | Live since 2026-11-01 (`b9a256b`); real transcription checked on the live candidate |
| Hackathon submission (HR-015) | Submitted |

## Live demo
**https://habita-frontend-preview-jcyiz2arua-uc.a.run.app** (no account needed)

1. On the landing page, press **Try the live demo**, or open [`/demo`](https://habita-frontend-preview-jcyiz2arua-uc.a.run.app/demo).
   Visitors first confirm Meta's terms (18+, not in a restricted territory).
2. The guided scenario starts at **Rua Frederico Arouca 30, Cascais**, a real address, and reaches every feature: the
   jurisdiction and authority, a permit question with its verification, the map with post-its, the aerial view with
   SAM 3.1, photos and plans, before/after concepts, costs, the PDF report, the spoken report and the copilot.
3. New York, Paris and Singapore are shown as **partial-coverage** examples (authority, official sources, market prices,
   and the aerial view in New York and Paris); see [Partial coverage](#partial-coverage-new-york-paris-and-singapore).

Best viewed on a computer; the phone layout still needs polish. Answers about a property's legal status are shown as
**verified** only when the verifier supports every statement; older results are never shown as current verified.
Deployment history, revisions and rollbacks: [`docs/deploy-history.md`](docs/deploy-history.md).

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
Last full run (2026-11-04, `main` at `ac52716`): backend **7602 passed, 29 skipped, 3 expected failures** (known
limitations kept as strict xfail). The verifier's acceptance corpus (`python -m tests.mu9_acceptance`): 294 cases, 220
automated, 212 attacks, **0 unsupported answers verified**, 3 of 8 legitimate answers still unverified, 4.15 ms mean per
run. On 2026-11-02 the suite also ran 23 replica-set and ingestion concurrency tests against a local MongoDB 8.0 replica
set; frontend unchanged since its last run (2026-11-01: **89 passed**, lint, typecheck and build clean). Live tests against
MongoDB Atlas and the Meta API are opt-in (`HABITA_LIVE_TESTS=1`, real credentials).

## How it was built: one developer, three coding agents, Muse Code as reviewer
HABITA was built in the hackathon by one developer directing coding agents: Claude Code implemented, and every
change went through independent review rounds before it was published. **Muse Code** (Meta's coding agent, 1.4.13)
was one of the two reviewers, alongside Codex. Its work, all during the hackathon (2026-11-01 … 2026-11-03):

- **Verifier review (TD-003, the MU-9 legal verifier):** five rounds on the hotfix branch and four on the candidate
  that went live. Muse Code read the verifier and its tests and wrote attacks: answers that change a figure, drop a
  condition, recombine words from different cited sentences, or claim a fact the case never stated. Each finding was
  reproduced as a failing test first, then fixed (commits `c16f8d1`, `2b4a8c2`, `db260b2`, `52dc4c2`, `1239fcf`,
  `91bfe45`).
- **Interface review (UX-B):** two rounds on the map and the demo (accessible marker button, Esc and focus handling,
  contrast, reduced motion, the not-legal-advice note); fixed in `b59b200` and `7ac84b3`; round 2 passed.
- **Hackathon check (2026-11-03):** read the repository against the official rules and rubric and listed the
  compliance risks (what was built during the event, rights to every asset, not legal advice); used to prepare the
  submission.

Codex reviewed the other changes; Muse Code reviewed the parts above, where a second independent reader mattered most.

## Roadmap and technical debt
- Roadmap with acceptance criteria and evidence per module: [`docs/roadmap.md`](docs/roadmap.md). HR-001 and HR-002
  are done; HR-003 is live (whole-sentence verification, fail-closed); HR-004 and HR-006 are complete as an MVP; HR-005,
  HR-007, HR-008 and HR-009 to HR-012 are live.
- Next: more jurisdictions beyond Cascais; zoning read from an official GIS connector; better answers to procedure
  questions (RJUE procedure citations); research into semantic verification (entailment, negation scope, deontic logic)
  without weakening the deterministic final gate; Google Cloud API quotas and the Maps Platform terms for imagery in
  PDFs.
- The maintainers keep a detailed technical-debt register (severity, evidence, tests, closure criteria) for these
  items.

## Repository layout
| Path | Purpose |
|---|---|
| `frontend/` | Next.js + React web app |
| `backend/` | FastAPI API, permit workflow, verifier, reports, maintenance commands |
| `docs/` | Architecture, environment, roadmap, demo runbook |
| `infrastructure/` | Container images, manual Cloud Run deployment procedure and scripts |

## Deployment and safety
There is no CI/CD: nothing deploys on push or merge; deployment is manual and authorised step by step
(`infrastructure/STAGING.md`). HABITA AI is decision support, not legal advice; its reports are not permits, licences
or authorisations — only the competent authority decides.
