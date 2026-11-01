"""HR-012 plan views: a measurable fidelity criterion (proposal; not wired into the concept flow).

Origin: real test of 2026-11-01 (the image service added a store room to a 3D view and a stair to a realistic one) and
ChatGPT review HABITA-REVIEW-20261101-0052 point C. The owner chose to publish plan views as illustrations with the
notice "May not match your plan exactly" provided a view does what is asked; this module states what "does what is
asked" means, so that it can be checked the same way every time.

How it is meant to run: an inventory of the plan (rooms, doors between rooms, windows and entrances by wall, floors,
stairs) is taken before the view is made, and an inventory of the view is taken by an evaluator that did not make the
view (a person today; possibly a different model later). ``compare`` applies the rules for the requested change with
ZERO tolerance. Anything the evaluator can't decide makes the result UNVERIFIED, never PASS (fail-closed).

Granularity (stated limit): each room by its zone of the drawing (3×3 grid), windows and entrances by room and wall
side (N/E/S/W of the drawing), doors by the two rooms they join, counted one by one. Not detected: a door or window
moved along its wall, a door moved to another wall between the same two rooms, or a room shifted within its zone.
"""

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

RoomType = Literal["living", "kitchen", "bedroom", "bathroom", "hall", "storage", "office", "other"]
Side = Literal["N", "E", "S", "W"]
#: Where a room sits on the drawing, as a 3×3 grid (C = centre).
Zone = Literal["NW", "N", "NE", "W", "C", "E", "SW", "S", "SE"]
Verdict = Literal["PASS", "FAIL", "UNVERIFIED"]
DefectCode = Literal[
    "room_added", "room_removed", "room_type_changed", "bedroom_not_added", "bedroom_not_from_largest_room",
    "door_added", "door_removed", "window_added", "window_removed", "entrance_changed", "floor_added",
    "stairs_added", "floor_removed", "stairs_removed", "partial_not_allowed", "room_moved", "nothing_shown",
]
PLAN_VIEWS = ("plan_3d", "plan_real", "plan_3d_bedroom")


class Room(BaseModel):
    #: The plan's own label (e.g. "SALA", "QUARTO 1"); the view inventory reuses the plan's ids for the same rooms.
    id: str
    type: RoomType
    #: Rough floor area in the plan's units, only to find the largest room; None when the plan gives no size.
    area: float | None = None
    #: The zones of the drawing the room covers (one or more). Compared when the plan gives them; a view room without
    #: zones then counts as undecided (UNVERIFIED).
    zones: list[Zone] = Field(default_factory=list)
    #: View only, for the one-more-bedroom view: the plan room the evaluator sees the new bedroom carved out of.
    carved_from: str | None = None


class Inventory(BaseModel):
    rooms: list[Room]
    #: Doors or open passages between two rooms, one entry per opening (two doors = two entries).
    connections: list[tuple[str, str]] = Field(default_factory=list)
    #: Windows per room id, one wall side per window.
    windows: dict[str, list[Side]] = Field(default_factory=dict)
    #: Entrances from outside per room id, one wall side per entrance.
    entrances: dict[str, list[Side]] = Field(default_factory=dict)
    floors: int = 1
    stairs: bool = False
    #: Only for the realistic image, which shows one room: only the rooms listed are judged.
    partial: bool = False
    #: Partial view only: plan openings the evaluator states are outside the frame. Any other plan opening of a shown
    #: room that is missing from the view is a defect.
    not_in_frame: list[tuple[str, str]] = Field(default_factory=list)
    #: Items the evaluator could not decide (free text); any entry makes the result UNVERIFIED unless a FAIL exists.
    unclear: list[str] = Field(default_factory=list)


class Defect(BaseModel):
    code: DefectCode
    detail: str


class FidelityResult(BaseModel):
    change: str
    verdict: Verdict
    defects: list[Defect]
    unclear: list[str]


def _doors(pairs: list[tuple[str, str]]) -> Counter:
    return Counter(tuple(sorted(p)) for p in pairs)


def _largest(plan: Inventory) -> str | None:
    sized = [r for r in plan.rooms if r.area is not None]
    if not sized or len(sized) != len(plan.rooms):
        return None  # a room without an area could be the largest
    top = max(r.area for r in sized)
    biggest = [r.id for r in sized if r.area == top]
    return biggest[0] if len(biggest) == 1 else None  # a tie has no single "largest room"


def compare(plan: Inventory, view: Inventory, change: str, *, new_room_id: str | None = None) -> FidelityResult:
    """Apply the zero-tolerance rules for ``change`` (plan_3d, plan_real or plan_3d_bedroom).

    For plan_3d_bedroom, ``new_room_id`` names the bedroom the evaluator sees as new. It must be carved out of the
    plan's largest room (``carved_from``), have exactly one door, to that room or a hall, and no entrance; it is the
    only allowed addition. Its windows count as the largest room's, on the same walls."""
    if change not in PLAN_VIEWS:
        raise ValueError(f"not a plan view: {change}")
    out: list[Defect] = []
    if view.partial and change != "plan_real":
        out.append(Defect(code="partial_not_allowed", detail=f"{change} must show the whole home"))
    partial = view.partial and change == "plan_real"
    if partial and not view.rooms:
        out.append(Defect(code="nothing_shown", detail="the realistic image shows no room of the plan"))
    if len({r.id for r in plan.rooms}) != len(plan.rooms):
        raise ValueError("the plan inventory repeats a room id")
    plan_rooms = {r.id: r for r in plan.rooms}
    view_rooms = {r.id: r for r in view.rooms}
    for rid, n in sorted(Counter(r.id for r in view.rooms).items()):
        if n > 1:
            out.append(Defect(code="room_added", detail=f"{rid} appears {n} times in the view"))
    added = set(view_rooms) - set(plan_rooms)
    removed = set() if partial else set(plan_rooms) - set(view_rooms)

    new: str | None = None
    largest = _largest(plan)
    if change == "plan_3d_bedroom":
        if new_room_id is None or new_room_id not in added or view_rooms[new_room_id].type != "bedroom":
            out.append(Defect(code="bedroom_not_added", detail="no new bedroom identified in the view"))
        else:
            new = new_room_id
            src = view_rooms[new].carved_from
            if largest is None or src != largest or largest not in view_rooms:
                out.append(Defect(code="bedroom_not_from_largest_room",
                                  detail=f"new bedroom carved from {src!r}; the plan's largest room is {largest!r}"))
            new_doors = [p for p in view.connections if new in p]
            ends = {b if a == new else a for a, b in new_doors}
            if len(new_doors) != 1:
                out.append(Defect(code="door_added" if len(new_doors) > 1 else "door_removed",
                                  detail=f"the new bedroom has {len(new_doors)} doors; exactly one is allowed"))
            elif not ends <= {largest, *(r.id for r in plan.rooms if r.type == "hall")}:
                out.append(Defect(code="bedroom_not_from_largest_room",
                                  detail=f"the new bedroom opens onto {sorted(ends)}, not the largest room or a hall"))
            if view.entrances.get(new):
                out.append(Defect(code="entrance_changed", detail="the new bedroom has an entrance from outside"))
    for rid in sorted(added - {new}):
        out.append(Defect(code="room_added", detail=f"{rid} ({view_rooms[rid].type}) is not in the plan"))
    for rid in sorted(removed):
        out.append(Defect(code="room_removed", detail=f"{rid} ({plan_rooms[rid].type}) is missing from the view"))
    unclear = list(view.unclear)
    for rid in sorted(set(plan_rooms) & set(view_rooms)):
        if plan_rooms[rid].type != view_rooms[rid].type:
            out.append(Defect(code="room_type_changed",
                              detail=f"{rid}: {plan_rooms[rid].type} in the plan, {view_rooms[rid].type} in the view"))
        pz, vz = set(plan_rooms[rid].zones), set(view_rooms[rid].zones)
        if not pz or not vz:
            unclear.append(f"{rid}: position not stated in the {'plan' if not pz else 'view'}")
        elif pz and vz and vz != pz and not (rid == largest and new and vz < pz):
            # Only the room the new bedroom was carved from may cover fewer zones than on the plan.
            out.append(Defect(code="room_moved", detail=f"{rid}: {sorted(pz)} on the plan, {sorted(vz)} in the view"))
    if new and largest and plan_rooms[largest].zones:
        nz = set(view_rooms[new].zones)
        if not nz:
            unclear.append(f"{new}: position not stated in the view")
        elif not nz <= set(plan_rooms[largest].zones):
            out.append(Defect(code="bedroom_not_from_largest_room",
                              detail=f"the new bedroom covers {sorted(nz)}, outside {largest}'s zones"))
        elif largest in view_rooms and not set(plan_rooms[largest].zones) <= nz | set(view_rooms[largest].zones):
            out.append(Defect(code="room_removed",
                              detail=f"part of {largest} is neither {largest} nor the new bedroom in the view"))

    shown = set(view_rooms) if partial else set(plan_rooms) | set(view_rooms)
    plan_doors = Counter({p: n for p, n in _doors(plan.connections).items() if set(p) & shown})
    if partial:
        plan_doors -= _doors(view.not_in_frame)
    view_doors = Counter({p: n for p, n in _doors(view.connections).items() if new not in p})
    for p, n in sorted((view_doors - plan_doors).items()):
        out.append(Defect(code="door_added", detail=f"{n} new opening(s) between {p[0]} and {p[1]}"))
    for p, n in sorted((plan_doors - view_doors).items()):
        out.append(Defect(code="door_removed", detail=f"{n} opening(s) missing between {p[0]} and {p[1]}"))

    for field, counts, code in (("windows", view.windows, "window_added"), ("entrances", view.entrances,
                                                                               "entrance_changed")):
        for rid in sorted(set(counts) - set(view_rooms)):
            if counts[rid]:
                out.append(Defect(code=code, detail=f"{field} on {rid}, which is not a room of the view"))
    view_windows = {k: list(v) for k, v in view.windows.items()}
    if new and largest:
        view_windows[largest] = view_windows.get(largest, []) + view_windows.pop(new, [])
    for field, plan_c, view_c, more, fewer in (
            ("windows", plan.windows, view_windows, "window_added", "window_removed"),
            ("entrances", plan.entrances, view.entrances, "entrance_changed", "entrance_changed")):
        for rid in sorted(shown - {new}):
            a, b = Counter(plan_c.get(rid, [])), Counter(view_c.get(rid, []))
            if b - a:
                out.append(Defect(code=more, detail=f"{rid}: {field} {sorted((b - a).elements())} not in the plan"))
            if a - b:
                out.append(Defect(code=fewer, detail=f"{rid}: {field} {sorted((a - b).elements())} missing"))

    if view.floors > plan.floors:
        out.append(Defect(code="floor_added", detail=f"{plan.floors} floor(s) in the plan, {view.floors} in the view"))
    elif view.floors < plan.floors:
        if partial:
            unclear.append("the plan has more than one floor; the image can't show whether they were kept")
        else:
            out.append(Defect(code="floor_removed",
                              detail=f"{plan.floors} floor(s) in the plan, {view.floors} in the view"))
    if view.stairs and not plan.stairs:
        out.append(Defect(code="stairs_added", detail="the view shows stairs or an opening to another floor"))
    elif plan.stairs and not view.stairs:
        if partial:
            unclear.append("the plan has stairs; the image can't show whether they were kept")
        else:
            out.append(Defect(code="stairs_removed", detail="the plan's stairs are missing from the view"))

    verdict: Verdict = "FAIL" if out else ("UNVERIFIED" if unclear else "PASS")
    return FidelityResult(change=change, verdict=verdict, defects=out, unclear=unclear)
