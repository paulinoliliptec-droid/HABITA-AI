# HR-012 · Fidelity criterion for views from a plan (proposal)

Status: **owner chose option (a) on 2026-11-01: a manual gate.** Before each new publication of plan views and after
each real test, a person other than the image service applies the checklist below and records the result in this
document. It is not automatic in the product. The code (`backend/app/services/concepts/fidelity.py`) and its
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
7. (Só o olho apanha; o critério não vê.) **Reprovada** se o quarto novo não estiver fechado por uma divisória (só
   pousado por cima da sala), se alguma parede entre duas divisões tiver sido aberta por inteiro (cozinha aberta para
   a sala), ou se uma porta ou janela tiver mudado de sítio na mesma parede.

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

## Synthetic sample matrix (negative cases)
Five synthetic plans, drawn from the same geometry that gives their inventory, so the picture and the inventory can't
drift apart (`backend/tests/plan_samples.py`; redraw with `python -m tests.plan_samples` from `backend/`):
[T1](evidence/hr012/samples/plan-t1.png), [T3](evidence/hr012/samples/plan-t3.png),
[T1 without areas](evidence/hr012/samples/plan-t1-unmeasured.png),
[T2 with two rooms of 30 m²](evidence/hr012/samples/plan-t2-tie.png) and
[a duplex with stairs](evidence/hr012/samples/plan-duplex.png). The views are inventories an evaluator could write
down; no image was made and no paid call was used. 27 cases plus 3 stated limits, in `backend/tests/test_plan_fidelity_samples.py`:

| Plan | Must PASS | Must FAIL | Must stay UNVERIFIED |
|---|---|---|---|
| T1 | faithful 3D; one more bedroom from the living room; realistic living room | bedroom taken from the bedroom; kitchen left out (drawn as part of the living room); a stair in the realistic image; realistic image without its entrance | |
| T3 | faithful 3D; one more bedroom from the living room with its door to the hall | store room left out; a window lost; bedroom taken from the kitchen; bedroom 2 door moved from the hall to the living room; bedroom and bathroom swapped; an extra bathroom door | evaluator unsure (door or cupboard?) |
| T1 without areas | faithful 3D | one more bedroom (no room can be called the largest) | |
| T2 with a tie | faithful 3D | one more bedroom, from either of the two largest rooms | |
| Duplex | faithful 3D; one more bedroom from the living room; realistic hall with the stairs and the floor above seen | ground floor only; stairs left out; a third floor | realistic image of any room where the other floor and the stairs aren't seen |

What the matrix shows:
- **Without areas, or with a tie, the one-more-bedroom view can never pass.** "Divide the largest room" has no
  answer there. Before such views are offered on plans like these, the user should choose the room to divide
  (polish item); until then the evaluator records them as FAIL.
- **A realistic image of a home with several floors stays UNVERIFIED** unless the evaluator records the other floor
  and the stairs as seen in it (for example a hall with the stairs going up). One room usually can't show them.
- **Stated limits, kept as tests that PASS** (`test_stated_limits_pass_and_need_the_evaluator`), so only the
  evaluator's eye catches them:
  - a new bedroom that overlaps the living room instead of dividing it. At the 3×3 grid this looks the same as a
    real division, which is also how the real PASS view of 00057-jaq is recorded;
  - a wall between two rooms opened wide into an open-plan room, both rooms kept. An opening is recorded by the two
    rooms it joins, not by its width.
  - a door moved along its wall, between the same two rooms.
- **Not covered:** a room chosen by the user to divide. `compare` only knows "the largest room"; a user's choice
  would need its own parameter, which waits for the UX proposal (ChatGPT review 0527, point D).
- **Stated limit:** zones are per floor, but a room's floor is not recorded. In a duplex, a bedroom carved
  upstairs but declared as carved from the living room would only be caught by the evaluator's `carved_from`.

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

Decision (owner, 2026-11-01): **(a)**. Options (b) and (c) are not planned; (b) would first need a cost, latency,
privacy and false-PASS estimate and the owner's approval.

Known gaps (ChatGPT review 0318): one synthetic PASS is an example, not a general guarantee. The evaluator's inventory
can itself be wrong. The "largest room" rule is HABITA's choice, not the user's: letting the user choose the room to
divide is a polish item. Negative samples (T1/T3, unmeasured plans, ties, several floors): see "Synthetic sample
matrix" above.
