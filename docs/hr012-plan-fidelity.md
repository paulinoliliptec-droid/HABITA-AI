# HR-012 · Fidelity criterion for views from a plan (proposal)

Status: **proposed, not yet a gate in the product.** The code (`backend/app/services/concepts/fidelity.py`) and its
tests are in place. No paid call was made to prepare it. Using it on every view needs the owner's decision (see
"Options" below).

## Why
A view from a plan (3D, realistic, 3D with one more bedroom) is an AI illustration. In the real test of 2026-11-01 the
image service added a store room to one 3D view and a stair opening to a realistic image. The owner chose to publish
plan views with the notice "May not match your plan exactly", provided a view does what is asked. This document says
what "does what is asked" means, so that every view is judged the same way. It answers ChatGPT review
HABITA-REVIEW-20261101-0052, point C.

## The criterion
1. **Plan inventory, before the view is made**: every room (its label, type, area, and the zones of the drawing it
   covers on a 3×3 grid), every door or open
   passage between two rooms (one entry per opening), the windows and outside entrances of each room by wall side
   (N/E/S/W of the drawing), the number of floors, and whether there are stairs.
2. **View inventory, by an evaluator that did not make the view**: a person today (the owner or Claude), later perhaps
   a different model. The evaluator uses the plan's labels for the same rooms.
3. **Comparison with zero tolerance** (`compare`):

| Change | Allowed | Everything else |
|---|---|---|
| `plan_3d` 3D view | nothing | FAIL |
| `plan_real` realistic image (one room) | nothing, in the rooms it shows. Only this view may be partial; a plan opening of a shown room that is missing must be declared "outside the frame" by the evaluator, otherwise it fails | FAIL |
| `plan_3d_bedroom` one more bedroom | exactly one new bedroom, which the evaluator sees carved out of the plan's single largest room, with exactly one door (to that room or a hall) and no entrance; its windows count as the largest room's, on the same walls | FAIL |

   Defects: a room added, removed or changed in type; an opening added, removed or joining other rooms; a window added,
   removed or on another wall; an entrance changed; an extra floor; stairs or an opening to another floor; for the
   bedroom view, no new bedroom, more than one door, an entrance in it, or a bedroom taken from a room other than the
   largest (a tie for largest, or a room without an area, also fails); a room in other zones of the drawing; a floor or
   stairs added or removed; a realistic image that shows no room of the plan. A room whose zones the evaluator doesn't
   state makes the view UNVERIFIED.

   Stated limit (granularity): a door or window moved along its wall, a door moved to another wall between the same
   two rooms, or a room shifted within its zone is not detected.
4. **Verdict**: PASS (no defect, nothing unclear), FAIL (any defect), or UNVERIFIED (no defect, but something the
   evaluator could not decide). UNVERIFIED is never shown as PASS (fail-closed).

## Checklist for the evaluator (PT)
Para cada vista, com a planta ao lado:
1. Contei as divisões da planta e as da vista. Há alguma divisão a mais ou a menos? (Na vista "mais um quarto",
   só pode haver **um** quarto a mais, tirado da maior divisão.)
2. Cada divisão continua com o mesmo uso (sala, cozinha, quarto, WC, hall)?
3. As portas e passagens ligam as mesmas divisões que na planta? Há alguma abertura nova ou fechada?
4. As janelas e a entrada estão nas mesmas divisões, e com o mesmo número?
5. Aparece uma escada, um buraco no chão ou um segundo piso?
6. Há alguma coisa que não consigo decidir? Se sim, a vista fica **por verificar**, nunca aprovada.

## Applied to the real views so far
| Date | View | Plan | Verdict | Notes |
|---|---|---|---|---|
| 2026-11-01 | `plan_3d` (00055-vik) | earlier sample, not kept | FAIL | store room, closed corridor and separate shower not in the plan |
| 2026-11-01 | `plan_real` (00055-vik) | earlier sample, not kept | FAIL | stair opening in the floor (another floor suggested) |
| 2026-11-01 | `plan_3d_bedroom` (00056-kes, old wording) | earlier sample, not kept | not judged | the plan image was lost with the earlier session |
| 2026-11-01 | `plan_3d_bedroom` (00057-jaq, live wording) | synthetic two-bedroom plan | **PASS** | living room split by one slatted partition with a door; every other room, door, window and the entrance kept. The objects at the kitchen's lower wall are a table and chairs, not a door |

The last row is a test in the repository (`tests/test_plan_fidelity.py::test_the_real_one_more_bedroom_view_passes`).
The plan and the view are in the repository for anyone to check against the checklist:
[`evidence/hr012/plan-t2-synthetic.png`](evidence/hr012/plan-t2-synthetic.png) and
[`evidence/hr012/plan_3d_bedroom-00057-jaq.jpg`](evidence/hr012/plan_3d_bedroom-00057-jaq.jpg) (synthetic, no
private data). The earlier failed views stay in the git-ignored review folder, because their plan was not kept.

## Options for using it in the product (owner's decision)
- **(a) Manual sample (no cost, now):** apply the checklist to each new real test and before each publication;
  record the result here. The product doesn't change.
- **(b) Automatic check before showing a view:** the file reader already reads the plan, so it would also return the
  plan inventory. A second reading by a *different* model returns the view inventory, and `compare` decides. A FAIL or
  UNVERIFIED view is not shown: the user is told the view could not be made faithfully and the allowance is refunded.
  Cost: one extra model reading per view (the view itself is the expensive call). Limit: a model evaluator can miss
  things; it is a filter, not proof.
- **(c) Deterministic 3D from a confirmed plan (later):** the user confirms the rooms on the plan, HABITA draws the 3D
  geometry itself, and AI only adds materials. Exact geometry, but several days of work. Not for the hackathon.

Recommendation: (a) now; (b) only if the owner wants plan views to stay on after the hackathon.
