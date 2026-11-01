"""HR-012: the changes a concept may show, by request type, each with HABITA's fixed instruction (AC12.2, AC12.6).

Nothing on the outside of the building, nothing structural and nothing needing a new floor or an extension: the
owner decided on 2026-10-31 that facade changes stay out, since they usually need prior control."""

from app.services.i18n.translator import msg

_RULES = ("Edit this photo of a room. Keep the camera, the room's shape, walls, windows, doors, ceiling and anything "
          "outside exactly as they are. Do not add, remove or move any wall, window or door. Do not add any person, "
          "animal, text, logo or brand. Photorealistic. Change only: ")

CHANGES: dict[str, tuple[str, str]] = {
    "new_kitchen": (msg("New kitchen units and worktop"),
                    "the kitchen units and worktop, to simple modern ones in the same layout."),
    "new_bathroom": (msg("New bathroom tiles and fittings"),
                     "the bathroom tiles, washbasin, toilet and shower, to simple modern ones in the same places."),
    "floor_and_paint": (msg("New floor and wall paint"),
                        "the floor finish to light wood and the wall paint to a light neutral colour."),
    "office_layout": (msg("Furnished as a small office"),
                      "the loose furniture, to two desks, chairs and shelves for a small office."),
    "light_partition": (msg("A light partition dividing the room"),
                        "add one light, non-structural partition with a door dividing the room in two, without "
                        "touching any existing wall, window or door."),
}

BY_INTENT: dict[str, tuple[str, ...]] = {
    "interior_works": ("new_kitchen", "new_bathroom", "floor_and_paint"),
    "change_of_use": ("office_layout", "floor_and_paint"),
    "unit_conversion": ("light_partition", "new_kitchen", "floor_and_paint"),
    "general_overview": ("floor_and_paint",),
}


def options(intent: str | None) -> list[str]:
    return list(BY_INTENT.get(intent or "", ()))


#: From a plan (owner, 2026-11-01): a 3D view and a realistic image of the home, kept to the plan's layout, and a 3D
#: view with one more bedroom (owner, 2026-11-01: "quero aumentar mais um quarto"). The plan itself is never redrawn:
#: an AI-edited plan could pass for a project. The extra bedroom is made inside the home, never as an extension.
_NO_PEOPLE = "Simple neutral furniture. Do not add any person, animal, text, label, logo or brand."
_KEEP = ("Keep the layout of this floor plan exactly: do not add, remove, enlarge or move any room, wall, door or "
         "window, and add no floor. ")
_ONE_MORE = ("Keep the outer walls, every existing interior wall, column, door and window, and every other room of "
             "this floor plan exactly; remove or move no wall; add no floor, no extension, no stairs and no other room. ")
_3D = ("Turn this floor plan into a 3D isometric cutaway view of the same home, seen from above at an angle with the "
       "walls cut at mid height.")
PLAN_CHANGES: dict[str, tuple[str, str]] = {
    "plan_3d": (msg("3D view of the plan"), _3D + " " + _KEEP),
    "plan_real": (msg("Realistic image of the home"),
                  "Turn this floor plan into one photorealistic photograph of the inside of the same home: its largest "
                  "room as drawn, at eye level, in daylight. " + _KEEP),
    "plan_3d_bedroom": (msg("3D view with one more bedroom"),
                        _3D + " Show exactly one more bedroom than the plan has: divide {room} with one light, "
                        "non-structural partition with its only new door in that partition, and furnish the new part "
                        "as a bedroom with a bed. " + _ONE_MORE),
}
ALL_CHANGES = {**CHANGES, **PLAN_CHANGES}
#: The second line burned into a view from a plan: the image service doesn't follow a plan exactly (real test,
#: 2026-11-01: it added a store room in one view and a stair in another), so the view is labelled as such.
PLAN_NOTICE_EN = msg("May not match your plan exactly")


def plan_options(intent: str | None) -> list[str]:
    return list(PLAN_CHANGES) if (intent or "") in BY_INTENT else []


def is_plan_change(change: str) -> bool:
    return change in PLAN_CHANGES


#: The views that need the user to choose a room first (owner, 2026-11-01: the user picks; HABITA never assumes).
NEEDS_ROOM = frozenset({"plan_3d_bedroom"})


def instruction(change: str, room: str | None = None) -> str:
    """``room`` is HABITA's fixed description of the chosen room (rooms.describe), never text from the plan."""
    if (change in NEEDS_ROOM) != (room is not None):
        raise ValueError(f"{change}: a room is {'required' if change in NEEDS_ROOM else 'not allowed'}")
    if change in PLAN_CHANGES:
        text = PLAN_CHANGES[change][1]
        return (text.replace("{room}", room) if room is not None else text) + _NO_PEOPLE
    return _RULES + CHANGES[change][1]
