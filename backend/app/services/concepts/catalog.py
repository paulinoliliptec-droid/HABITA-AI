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




#: From a plan (owner, 2026-11-01): a 3D view and a realistic image of the home, kept to the plan's layout. The plan
#: itself is never redrawn: an AI-edited plan could pass for a project.
_PLAN_RULES = ("Keep the layout of this floor plan exactly: do not add, remove, enlarge or move any room, wall, door or "
               "window, and add no floor. Simple neutral furniture. Do not add any person, animal, text, label, logo "
               "or brand. ")
PLAN_CHANGES: dict[str, tuple[str, str]] = {
    "plan_3d": (msg("3D view of the plan"),
                "Turn this floor plan into a 3D isometric cutaway view of the same home, seen from above at an angle "
                "with the walls cut at mid height."),
    "plan_real": (msg("Realistic image of the home"),
                  "Turn this floor plan into one photorealistic photograph of the inside of the same home: its largest "
                  "room as drawn, at eye level, in daylight."),
}
ALL_CHANGES = {**CHANGES, **PLAN_CHANGES}


def plan_options(intent: str | None) -> list[str]:
    return list(PLAN_CHANGES) if (intent or "") in BY_INTENT else []


def is_plan_change(change: str) -> bool:
    return change in PLAN_CHANGES


def instruction(change: str) -> str:
    if change in PLAN_CHANGES:
        return PLAN_CHANGES[change][1] + " " + _PLAN_RULES
    return _RULES + CHANGES[change][1]
