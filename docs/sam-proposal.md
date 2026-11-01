# SAM 3.1 in HABITA — the aerial view (satellite slice built 2026-11-01; "after" uses proposed)

Status: **satellite slice built 2026-11-01** (owner: DGT imagery, option a; Meta's parser as a dependency, option a); the "after" uses stay a proposal. Asked by the owner on 2026-11-01 ("vamos usar o SAM principalmente para identificar as imagens
reais dos satélites e depois podemos usar também no depois, mas ajuda-me a encaixar bem para dar sentido"). Access test passed on 2026-11-01 (`POST /v1/responses`, model `sam-3.1`, image as a data URL plus a text prompt).

## Why SAM fits HABITA
HABITA already *reasons* (Muse Spark), *hears* (Muse Voice Transcribe), *speaks* (ElevenLabs) and *shows* ideas (Muse
Image). SAM 3.1 lets it **see what is really on the ground**. The question SAM answers is the one that matters most
before buying or renovating in Portugal: *is there something built here that the papers don't show?* (an annex, a
covered terrace, a pool, an enlarged footprint). These are common sources of licensing problems.

SAM never decides anything. What it finds is an **observation from imagery**, like a file reading (HR-010): it can only
add a *condition to confirm* with the Câmara, never make an answer VERIFIED or say a construction is illegal.

## 1. Real satellite images (main use)
**Flow.**
1. For the property's point, HABITA gets one aerial image with a known scale (see "Imagery source" below).
2. SAM 3.1 segments it with fixed text prompts from a closed list: `building`, `swimming pool`, `small detached
   building` (annex, shed, garage), `covered terrace or pergola`, `solar panels`, `paved area`, `trees`. No user text
   reaches SAM.
3. HABITA keeps only masks that touch the approximate-location circle, and from the image scale computes an
   **approximate** area per mask (m², rounded, labelled "approximate, from imagery").
4. The result is shown in three places that already exist:
   - **Property profile (HR-008)**, column *observed*: "Visible from the air: one building (about 140 m²), a pool,
     a small detached building."
   - **Map with post-its (HR-004)** and **PDF (HR-006)**: the aerial image with SAM's outlines drawn by HABITA, legend
     "Approximate outlines from aerial imagery of <date>. Not a survey, not a parcel boundary, not proof of a licence."
   - **Reasoning graph (HR-005)**: an *observation* node linked to the condition it adds.
5. **Cross-check, the part that gives SAM its sense.** HABITA compares what is visible with what is declared or
   official:
   - a small detached building or a covered terrace is visible → condition: "Confirm with the Câmara that the
     annex/terrace visible from the air is licensed";
   - the visible building footprint differs from the area the user declared by more than a fixed margin → condition:
     "The building seen from the air looks larger/smaller than declared; confirm the licensed area";
   - a pool is visible → condition about the pool's licensing.
   Fixed sentences, written by HABITA, like the file checks of HR-010; SAM only chooses from the closed list.

**Imagery source (must be settled first).**
- *Google Maps Static satellite* is already integrated, but the Google Maps Platform terms restrict creating content
  derived from Google imagery (tracing outlines is the typical example). Using it as SAM input needs a terms review
  (already an open item for the PDF images). **Not recommended without that review.**
- *Recommended: the official orthophotos of the Direção-Geral do Território (DGT)* through its public WMS: official,
  dated, about 25–50 cm per pixel, and consistent with HABITA's rule of official sources. The licence (open data
  terms) must be confirmed before use.

**Limits stated to the user.** Imagery date (old images miss recent works); trees and shadows hide things; resolution
limits small structures; areas are approximate; nothing about inside the building; never a parcel boundary.

## 2. The "after" (second use)
SAM on the images HR-012 makes, to make them more honest:
- **What changed.** SAM segments the user's photo and the generated concept; HABITA draws an outline around the
  regions that differ, so the user sees exactly what the concept changed (and what it should not have touched).
- **Plan views checked automatically.** SAM segments the plan and the 3D view into rooms; HABITA builds the two
  inventories of the fidelity criterion (`docs/hr012-plan-fidelity.md`) and runs `compare`. This is option (b) the
  owner left for later; it would replace part of the manual gate, as a filter, not proof.

## How the Meta tools then fit together (for the judges)
| Sense | Meta tool | In HABITA |
|---|---|---|
| Reason | Muse Spark | plans, consults official sources, drafts, reviews; reads photos and plans |
| Hear | Muse Voice Transcribe | the user dictates the question |
| See | **SAM 3.1** | what is really built, from the air; what a concept changed |
| Show | Muse Image | before/after concepts and plan views |
| Resilience and privacy | open-weight Meta models | fallback when the main model fails; sensitive data (polish stage) |
| Quality | Muse Code | general code review (polish stage) |

## Effort and order
1. Access test of `sam-3.1` with one image (paid, small) and the DGT licence check: half a day.
2. Satellite slice (imagery, segmentation, areas, profile, map/PDF overlay, conditions, PT/EN, tests): about 2 days.
3. The "after" uses: about 1 day each.

## As built (satellite slice)
- `backend/app/integrations/dgt/orthophoto.py`: DGT WMS `ortos2018`, layer `Ortos2018-RGB`, a 1024 px square of 120 m
  (rooftop addresses, 0.117 m/px) or 160 m (interpolated); blank answers refused; mainland only.
- `backend/app/integrations/meta/segment.py`: SAM 3.1 through the Responses API; records parsed and masks decoded with
  Meta's `meta-sam-parser` 0.0.5; malformed or out-of-image records skipped.
- `backend/app/services/aerial/service.py`: prompts `building` and `swimming pool`; objects within 25 m (rooftop) or
  60 m (interpolated) of the point; area from the mask's pixels; a building under 40 m² not under the point is a
  "small separate building"; fixed conditions for small buildings and pools; the image with HABITA's outlines and the
  source line burned in; one analysis per property; one paid attempt per property and day and a daily cap of 40, both taken before the
  calls and given back only when no SAM call was made; a malformed SAM answer is an error, never "nothing found"; a
  small building within 1 m of another building is part of it, not separate.
  Coarser addresses and places outside the mainland get no analysis.
- API: `GET/POST /api/property/{id}/aerial`, `GET …/aerial/image`. The report adds the conditions (PDF, voice,
  post-its). Panel "Seen from the air" in the property workspace. PT/EN.
- Not built yet: comparison with the declared area, the "after" uses.

## Real run (2026-11-01)
A residential street in Cascais (38.7065, -9.4440, rooftop framing, 0.117 m/px), real DGT and SAM calls through the
service: a building of about 190 m² at 1 m from the point, a pool of about 25 m² at 8 m, buildings of 140, 780 and
655 m², and a small separate building of about 20 m² at 25 m; conditions for the small building and the pool.
Image: [`evidence/aerial/cascais-real-20261101.jpg`](evidence/aerial/cascais-real-20261101.jpg).

## Terms checked (2026-11-01, before publication)
- **DGT:** dados.gov.pt lists "Ortofotos 25 cm - Portugal Continental - 2018" (DGT) under **CC BY** with the WMS as one
  of its resources; the WMS capabilities say "Fees: no conditions apply", "AccessConstraints: None". DGT's open-data
  page: free use with the obligation to name DGT as the owner. HABITA shows "Informação geográfica cedida pela
  Direção-Geral do Território (CC BY 4.0)" on the image, the panel and the report, and states the change ("outlines
  added by HABITA").
- **Meta Model API terms** (dev.meta.ai, updated 2026-10-09) and geographic policy (2026-10-12): SAM 3.1, Muse Voice
  Transcribe and Muse Image are Standard models (no training on request content, §5.1); outputs are ours (§4.1); no
  restriction for Portugal or the EU (Muse Image is restricted in India only). Relevant duties: disclose limitations
  and keep labels/provenance (AUP), no professional legal advice, no decisions on individuals' rights without
  qualified review, end users must be 18+, no access from restricted territories, no Meta marks as branding (§7).
  Open items for the polish stage: an 18+ notice, geo-restriction of restricted territories, and confirming the
  non-commercial demo under §1 (the services are "intended for your commercial use").
