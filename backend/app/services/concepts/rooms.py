"""HR-012: which room of a plan the user may choose to divide for the "3D view with one more bedroom".

Owner decision (2026-11-01, docs/hr012-room-choice-ux.md): the user picks the room from a list read from the plan;
nothing is preselected; only a living room, a bedroom or an office is offered; a plan whose rooms can't be read doesn't
get this view; a very small room is offered with a warning only.

The instruction to the image service is built only from HABITA's fixed vocabulary (the room's type, its place on the
drawing and its floor). The label read from the plan is shown to the user and never sent: a plan is user-supplied and
could carry any text. Two allowed rooms with the same description can't be told apart in an instruction, so neither is
offered.
"""

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel

from app.schemas.files import MatterFile, PlanRoom, RoomType, Zone
from app.services.i18n.translator import msg

#: The only rooms a bedroom may be carved from (owner, 2026-11-01). Never a kitchen, a bathroom, a hall, a store room
#: or anything outside the home.
ALLOWED: dict[RoomType, tuple[str, str]] = {
    "living": (msg("Living room"), msg("the living room")),
    "bedroom": (msg("Bedroom"), msg("the bedroom")),
    "office": (msg("Office"), msg("the office")),
}
#: The place of a room on the drawing, from the middle of the zones it covers: (row, column), -1 = top / left.
_AT: dict[Zone, tuple[int, int]] = {"NW": (-1, -1), "N": (-1, 0), "NE": (-1, 1), "W": (0, -1), "C": (0, 0),
                                    "E": (0, 1), "SW": (1, -1), "S": (1, 0), "SE": (1, 1)}
Place = Literal["upper_left", "upper_middle", "upper_right", "middle_left", "centre", "middle_right", "lower_left",
                "lower_middle", "lower_right"]
PLACES: dict[Place, tuple[str, str]] = {
    "upper_left": (msg("upper left"), "in the upper-left part of the plan"),
    "upper_middle": (msg("upper middle"), "in the upper-middle part of the plan"),
    "upper_right": (msg("upper right"), "in the upper-right part of the plan"),
    "middle_left": (msg("middle left"), "in the middle-left part of the plan"),
    "centre": (msg("centre"), "in the centre of the plan"),
    "middle_right": (msg("middle right"), "in the middle-right part of the plan"),
    "lower_left": (msg("lower left"), "in the lower-left part of the plan"),
    "lower_middle": (msg("lower middle"), "in the lower-middle part of the plan"),
    "lower_right": (msg("lower right"), "in the lower-right part of the plan"),
}
_GRID: list[list[Place]] = [["upper_left", "upper_middle", "upper_right"], ["middle_left", "centre", "middle_right"],
                            ["lower_left", "lower_middle", "lower_right"]]
#: The floor in the report and voice, in fixed words.
FLOOR_NAMES = {0: msg("ground floor"), 1: msg("first floor"), 2: msg("second floor"), 3: msg("third floor"),
               4: msg("fourth floor")}
FLOORS = {0: "on the ground floor", 1: "on the first floor", 2: "on the second floor", 3: "on the third floor",
          4: "on the fourth floor"}
#: Below this many m² (as written on the plan), halving the room may leave a part too small for a bedroom. A caution
#: for the user only, not a legal minimum: no figure is shown until HABITA has a sourced RGEU minimum (owner, q4).
SMALL_M2 = 18.0

Status = Literal["ok", "unreadable", "none"]
Reason = Literal["type", "no_place", "same_as_another"]


class OfferedRoom(BaseModel):
    id: str
    label: str
    type: RoomType
    type_label: str
    area: float | None
    place: Place
    place_label: str
    floor: int | None
    #: Marked, never preselected (owner, q3): only when every room of its floor has an area and it alone is the largest.
    largest: bool
    small: bool


class ExcludedRoom(BaseModel):
    label: str
    type: RoomType
    reason: Reason


class RoomOffer(BaseModel):
    status: Status
    #: The plan's floors, in order; [None] for a plan with one floor.
    floors: list[int | None]
    rooms: list[OfferedRoom]
    excluded: list[ExcludedRoom]


def place_of(zones: list[Zone]) -> Place | None:
    if not zones:
        return None
    row = sum(_AT[z][0] for z in zones) / len(zones)
    col = sum(_AT[z][1] for z in zones) / len(zones)
    snap = lambda v: 0 if abs(v) < 1 / 3 else (1 if v > 0 else -1)  # noqa: E731
    return _GRID[snap(row) + 1][snap(col) + 1]


def _largest(rooms: list[PlanRoom]) -> str | None:
    """The single largest room of one floor; None without every area, or with a tie."""
    if not rooms or any(r.area is None for r in rooms):
        return None
    top = max(r.area for r in rooms)
    biggest = [r.id for r in rooms if r.area == top]
    return biggest[0] if len(biggest) == 1 else None


def offer(plan: MatterFile) -> RoomOffer:
    rooms = plan.rooms
    unreadable = RoomOffer(status="unreadable", floors=[], rooms=[], excluded=[])
    if not rooms or len({r.id for r in rooms}) != len(rooms):
        return unreadable
    floors = {r.floor for r in rooms}
    if None in floors and len(floors) > 1:
        return unreadable  # some rooms with a floor, some without: which floor a room is on is unknown
    if floors == {None} and "several_floors" in plan.checks:
        return unreadable  # several floors drawn but no room says which: an instruction can't name the floor
    if any(f not in FLOORS for f in floors - {None}):
        return unreadable
    by_floor: dict[int | None, list[PlanRoom]] = defaultdict(list)
    for r in rooms:
        by_floor[r.floor].append(r)
    largest = {f: _largest(rs) for f, rs in by_floor.items()}

    excluded: list[ExcludedRoom] = []
    candidates: dict[tuple[str, Place, int | None], list[PlanRoom]] = defaultdict(list)
    for r in rooms:
        place = place_of(r.zones)
        if r.type not in ALLOWED:
            excluded.append(ExcludedRoom(label=r.label, type=r.type, reason="type"))
        elif place is None:
            excluded.append(ExcludedRoom(label=r.label, type=r.type, reason="no_place"))
        else:
            candidates[(r.type, place, r.floor)].append(r)
    offered: list[OfferedRoom] = []
    for (rtype, place, floor), same in candidates.items():
        if len(same) > 1:  # the instruction couldn't say which one
            excluded += [ExcludedRoom(label=r.label, type=r.type, reason="same_as_another") for r in same]
            continue
        r = same[0]
        offered.append(OfferedRoom(id=r.id, label=r.label, type=r.type, type_label=ALLOWED[rtype][0], area=r.area,
                                   place=place, place_label=PLACES[place][0], floor=floor,
                                   largest=largest[floor] == r.id, small=r.area is not None and r.area < SMALL_M2))
    offered.sort(key=lambda o: int(o.id[1:]))
    floors_used = sorted(by_floor, key=lambda f: -1 if f is None else f)
    return RoomOffer(status="ok" if offered else "none", floors=floors_used, rooms=offered, excluded=excluded)


def chosen(plan: MatterFile, room_id: str | None) -> OfferedRoom | None:
    """The offered room with this id, or None: an id that isn't offered for this plan is never used."""
    if room_id is None:
        return None
    return next((r for r in offer(plan).rooms if r.id == room_id), None)


def describe(room: OfferedRoom) -> str:
    """The room in HABITA's fixed vocabulary only, for the instruction."""
    text = f"{ALLOWED[room.type][1]} {PLACES[room.place][1]}"
    return f"{text} {FLOORS[room.floor]}" if room.floor is not None else text
