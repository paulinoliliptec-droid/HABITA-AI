# HR-012 · Choosing the room to divide

Status: **built and live on 2026-11-01** (commit `7fad9a9`, backend `00059-sic`, frontend `00056-sal`; owner: "faz merge e publica no real"). Asked by the owner on 2026-11-01 ("faz a proposta
de UX para escolher a divisão"); answers ChatGPT review HABITA-REVIEW-20261101-0652, point D. The owner approved the
four proposals below on 2026-11-01 ("aprovo as 4 propostas, podes construir"). The paid real test of the chosen-room
view still needs the owner's specific approval.

## As built
- **Plan reading** (`backend/app/services/files/service.py`): the same reading also returns `rooms` (label, type from
  the closed list, area only if written in m², zones on the 3×3 grid, floor 0–4). HABITA gives the ids (R1, R2… in
  reading order). One malformed room voids the whole list (fail-closed: dropping one could make another look unique
  or the largest); labels are cleaned of control and direction characters and cut to 40 characters.
- **The list** (`backend/app/services/concepts/rooms.py`, `GET /matters/{id}/concepts/rooms/{file_id}`): only a
  living room, a bedroom or an office; each with its place in fixed words (nine places from the middle of its zones)
  and floor; "the largest" marked only when every room of that floor has an area and there is no tie, never
  preselected; "small" (under 18 m² as written, an internal caution, not a legal minimum and never shown as a number)
  adds the RGEU warning. Not offered, with the reason: other types, rooms without a place, and two rooms with the same
  type, place and floor. No list (nothing read, a plan read before 2026-11-01, floors given for some rooms only, or
  several floors drawn without saying which room is on which) means "unreadable": this view isn't offered for that
  plan, the other plan views are.
- **The request** carries `room_id` (`^R[1-9][0-9]?$`); the backend accepts it only if it is in the list it computes
  from the stored reading, refuses it for any other view, and refuses the bedroom view without one, all before any
  spend. The instruction says "divide the living room in the upper-left part of the plan [on the first floor]", from
  fixed words only; the label never reaches the image service.
- **The record** (`Concept.room`) keeps the id, the label and the fixed words; the caption shows "(dividing: SALA)";
  the PDF and the voice say "dividing the living room (upper left)" in HABITA's words only, in PT and EN.
- **The criterion**: `compare(..., divided_room_id=…)`, with the floor checked (see
  [`hr012-plan-fidelity.md`](hr012-plan-fidelity.md)).
- **The panel** (`frontend/src/features/permit/PermitRoomChoice.tsx`): floor (when several), then the room, then a
  confirmation with the notice and "uses 1 of the 3 plan views" before the paid call.

## Why
The "3D view with one more bedroom" asks the image service to divide **the largest room** (it is an instruction,
not a guarantee: the image service may not follow it). That rule is HABITA's, not the user's:
- the user may want to divide another room (a large bedroom, an office);
- on a plan without areas, or with two rooms of the same size, there is no largest room, so the view can never pass
  the fidelity criterion (sample matrix in [`hr012-plan-fidelity.md`](hr012-plan-fidelity.md));
- on a home with several floors, the largest room may be on the wrong floor.

## Recommendation
**The user picks the room from a list that HABITA reads from the plan, before the view is made.** Nothing is
preselected. If the plan can't be read room by room, this view is not offered for that plan, with a line saying why.

## The flow
1. The user chooses a plan and "3D view with one more bedroom", as today.
2. A new step appears: **"Which room do you want to divide?"**
3. The user picks one room, sees a short summary, and confirms. Only then is the (paid) view made.
4. The caption beside the view names the room: "3D view with one more bedroom (dividing: SALA)". The label is not
   burned into the image; the burned-in notices stay as they are.

```
┌─ Vista 3D com mais um quarto ──────────────────────────────┐
│ Que divisão quer dividir?                                  │
│                                                            │
│  ( ) SALA        32 m²  à esquerda          ← a maior      │
│  ( ) QUARTO 1     9 m²  em baixo, ao centro                │
│  ( ) QUARTO 2     9 m²  em baixo à direita                 │
│  Não aparecem: COZINHA, WC, HALL (não se dividem           │
│  para quarto)                                              │
│                                                            │
│  A lista foi lida da sua planta e pode ter erros.          │
│  Se a divisão não está na lista, esta vista não está       │
│  disponível para esta planta.                              │
│                                                            │
│                         [ Cancelar ]  [ Continuar ]        │
└────────────────────────────────────────────────────────────┘
```

```
┌─ Confirmar ────────────────────────────────────────────────┐
│ HABITA vai pedir uma imagem da sua casa com a SALA         │
│ dividida por uma divisória leve, com uma porta, e a nova   │
│ parte mobilada como quarto. As outras divisões, paredes,   │
│ portas e janelas mantêm-se.                                │
│                                                            │
│ É só uma ilustração: pode não corresponder exatamente à    │
│ sua planta, não é um projeto e não garante que a divisão   │
│ cumpre as regras (áreas mínimas, luz, ventilação).         │
│ Usa 1 das 3 vistas de planta deste processo.               │
│                                    [ Voltar ] [ Fazer ]    │
└────────────────────────────────────────────────────────────┘
```

**Not in the first version: tapping the room on the plan.** Codex review hr012h-r1 showed why: a tap on a 3×3 grid
doesn't identify one room (several rooms share a zone), it would bypass the room allowlist below, and a PDF plan
has no preview in the concepts panel today. It could come later with a precise point, a type the user confirms and a
PDF preview.

## Ambiguous cases

| Case | What the user sees |
|---|---|
| One room clearly largest | It is marked "a maior" but **not** preselected; the user still picks. |
| Two rooms the same size (tie) | No mark. Both listed; the user picks. |
| Plan without areas | Rooms listed without areas, no "largest" mark; the user picks. |
| The reader can't list the rooms | "Não conseguimos ler as divisões desta planta; esta vista não está disponível para ela." The other plan views stay available. |
| A room listed twice or a label unreadable | Shown as read ("QUARTO ?"), with its type, area and place on the plan (every line shows its place, and its floor on a plan with several floors). If two lines would still look the same, neither is offered. |
| Several floors | First "Which floor?" (Piso 0, Piso 1…), then the rooms of that floor. |
| Any room that isn't a living room, bedroom or office (kitchen, bathroom, hall, corridor, store room, balcony, terrace, garage, anything read as "other") | Not offered, with a line saying why ("não se dividem para quarto"). Only an **allowlist** is offered: living room, bedroom, office. A balcony or terrace is never offered (no extension, nothing on the outside). |
| A very small room | Offered, with a warning: "Pode ficar pequena demais para um quarto; confirme as áreas mínimas do RGEU com a Câmara." No number is shown until HABITA has a sourced RGEU minimum. |
| The user changes their mind after the view | They can make another (same allowance of 3); the earlier view keeps its own caption. |

## What would change
- **Plan reading (no extra call):** the same reading that already decides "is this a plan?" would also return, per
  room, the label as written, a type from a fixed list, an area if the plan shows one, its zones on the 3×3 grid and
  its floor. The answer gets a little longer, so each reading costs slightly more. It is shown to the user as "read
  from your plan, may have errors"; it is never used for the assessment.
- **Concept request:** the plan-bedroom request carries only the chosen room's **internal id** (R1, R2…, see the
  fidelity criterion below), never text from the browser. The backend checks that the id is in the stored list for
  that plan and that its type is on the allowlist.
- **Instruction (fixed text, no free text from the plan):** the instruction is built only from a fixed vocabulary:
  the room's type ("the living room", "the bedroom"), its place on the drawing ("in the upper-left part of the
  plan") and, for several floors, the floor ("on the ground floor"). The label read from the plan is shown to the user
  but never put into the instruction, since a plan is user-supplied and could carry any text. If two allowed rooms
  get the same description (same type, place and floor), neither is offered and the user is told why.
- **Fidelity criterion:** `compare` would take the chosen room in place of "the largest", and each room would record
  its floor. Rooms would get a unique internal id (R1, R2…) from the stored list, separate from the label shown, so
  two rooms read with the same label stay two rooms; that id is used in the selection and in both inventories. The
  bedroom must be carved from **that** room, on **its** floor (closing the stated limit that zones don't carry a
  floor), which removes the "no areas / tie can never pass" problem for plans where the user chose. The manual gate
  (option a) still applies.
- **Report and voice:** the concept line names the divided room.
- **Translation:** every new text in PT and EN.

## What it does not do
- It does not check that the new bedroom is legal (areas, light, ventilation). The notice says so.
- It does not let the user draw the partition. Where the wall goes stays the image service's choice, and the view is
  still an illustration.
- It does not change the photo concepts.

## The owner's decisions (2026-11-01: all four proposals approved)
1. Is the allowlist right: living room, bedroom, office only? (Proposal: yes; a kitchen divided into a bedroom is
   unusual and raises ventilation questions, and nothing outside the home is ever offered.)
2. Is it acceptable that a plan whose rooms can't be read doesn't get this view? (Proposal: yes for the first
   version; the tap-on-the-plan fallback needs a precise point, a confirmed type and a PDF preview.)
3. Should the largest room be preselected when it is clear? (Proposal: no; an explicit choice is the point.)
4. Is one sentence of warning enough for very small rooms, or should they be hidden? (Proposal: warning only, until
   a sourced RGEU minimum is in HABITA.)

## Effort, if approved
About one to two days: plan reading fields and tests, the request field and fixed-vocabulary instruction, the two
new frontend steps, the criterion parameter, translations, and one paid real test of the chosen-room view (needs the
owner's specific approval).
