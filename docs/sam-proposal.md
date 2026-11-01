# SAM 3.1 in HABITA — proposal (polish stage, not built)

Status: **proposal**, asked by the owner on 2026-11-01 ("vamos usar o SAM principalmente para identificar as imagens
reais dos satélites e depois podemos usar também no depois, mas ajuda-me a encaixar bem para dar sentido"). Nothing is
built; building it needs the owner's approval and a paid access test of `sam-3.1`.

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
