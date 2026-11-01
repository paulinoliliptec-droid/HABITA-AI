"""HR-012 fidelity criterion: a matrix of synthetic plans and views that must pass, fail or stay undecided.

Answers ChatGPT review HABITA-REVIEW-20261101-0318 point D (negative samples: T1, T3, plans without areas, a tie for
the largest room, several floors). The plans are in ``tests/plan_samples.py`` and drawn in
``docs/evidence/hr012/samples``. The views are inventories an evaluator could write down; no image was made and no
paid call was used.
"""

from pathlib import Path

import pytest

from app.services.concepts.fidelity import Inventory, Room, compare
from tests.plan_samples import FONT, SAMPLES, draw, inventory, on_outer_wall, shared_wall

PLANS = {key: inventory(s) for key, s in SAMPLES.items()}
SAMPLE_DIR = Path(__file__).resolve().parents[2] / "docs" / "evidence" / "hr012" / "samples"


def faithful(key: str) -> Inventory:
    return PLANS[key].model_copy(deep=True)


def edit(key: str, **update) -> Inventory:
    return faithful(key).model_copy(update=update)


def drop(key: str, *ids: str, **update) -> Inventory:
    """The view lost these rooms, with their doors, windows and entrances (a typical image-service failure)."""
    v = faithful(key)
    return v.model_copy(update={
        "rooms": [r for r in v.rooms if r.id not in ids],
        "connections": [p for p in v.connections if not set(p) & set(ids)],
        "windows": {k: w for k, w in v.windows.items() if k not in ids},
        "entrances": {k: e for k, e in v.entrances.items() if k not in ids}, **update})


def carve(key: str, src: str, new_zones: list[str], door_to: str, src_zones: list[str] | None = None) -> Inventory:
    """One more bedroom (NOVO) carved out of ``src``, with one door to ``door_to``."""
    v = faithful(key)
    rooms = [r.model_copy(update={"zones": src_zones}) if r.id == src and src_zones is not None else r
             for r in v.rooms]
    return v.model_copy(update={"rooms": [*rooms, Room(id="NOVO", type="bedroom", carved_from=src, zones=new_zones)],
                                "connections": [*v.connections, ("NOVO", door_to)]})


def only(key: str, rid: str, **update) -> Inventory:
    """A realistic image of one room; the plan openings it can't show are declared outside the frame."""
    v = faithful(key)
    doors = [p for p in v.connections if rid in p]
    base = {"rooms": [r for r in v.rooms if r.id == rid], "connections": doors[:1], "not_in_frame": doors[1:],
            "windows": {rid: v.windows.get(rid, [])}, "entrances": {rid: v.entrances.get(rid, [])}, "partial": True}
    return Inventory(**{**base, **update})


def moved(key: str, **zones: list[str]) -> Inventory:
    v = faithful(key)
    return v.model_copy(update={"rooms": [r.model_copy(update={"zones": zones.get(r.id.replace(" ", "_"), r.zones)})
                                          for r in v.rooms]})


# (case, sample, change, view, verdict, codes that must be among the defects)
MATRIX = [
    ("t1 3D faithful", "t1", "plan_3d", lambda: faithful("t1"), "PASS", set()),
    ("t1 one more bedroom from the living room", "t1", "plan_3d_bedroom",
     lambda: carve("t1", "SALA", ["SW"], "SALA", ["NW", "W"]), "PASS", set()),
    ("t1 bedroom taken from the bedroom", "t1", "plan_3d_bedroom",
     lambda: carve("t1", "QUARTO", ["SE"], "QUARTO"), "FAIL", {"bedroom_not_from_largest_room"}),
    ("t1 kitchen left out (drawn as part of the living room)", "t1", "plan_3d", lambda: drop("t1", "COZINHA"), "FAIL",
     {"room_removed", "door_removed", "window_removed"}),
    ("t1 realistic living room", "t1", "plan_real", lambda: only("t1", "SALA"), "PASS", set()),
    ("t1 realistic living room with a stair", "t1", "plan_real", lambda: only("t1", "SALA", stairs=True), "FAIL",
     {"stairs_added"}),
    ("t1 realistic living room missing its entrance", "t1", "plan_real",
     lambda: only("t1", "SALA", entrances={}), "FAIL", {"entrance_changed"}),
    ("t3 3D faithful", "t3", "plan_3d", lambda: faithful("t3"), "PASS", set()),
    ("t3 store room left out", "t3", "plan_3d", lambda: drop("t3", "ARRUMOS"), "FAIL",
     {"room_removed", "door_removed"}),
    ("t3 a window of bedroom 3 lost", "t3", "plan_3d",
     lambda: edit("t3", windows={**PLANS["t3"].windows, "QUARTO 3": ["S"]}), "FAIL", {"window_removed"}),
    ("t3 one more bedroom from the living room, door to the hall", "t3", "plan_3d_bedroom",
     lambda: carve("t3", "SALA", ["W"], "HALL", ["NW"]), "PASS", set()),
    ("t3 bedroom taken from the kitchen", "t3", "plan_3d_bedroom",
     lambda: carve("t3", "COZINHA", ["NE"], "COZINHA"), "FAIL", {"bedroom_not_from_largest_room"}),
    ("t3 bedroom 2 and the bathroom swapped", "t3", "plan_3d", lambda: moved("t3", WC=["S"], QUARTO_2=["SE"]),
     "FAIL", {"room_moved"}),
    ("t3 bedroom 2 door moved from the hall to the living room", "t3", "plan_3d",
     lambda: edit("t3", connections=[("SALA", "QUARTO 2") if p == ("HALL", "QUARTO 2") else p
                                     for p in PLANS["t3"].connections]), "FAIL", {"door_added", "door_removed"}),
    ("t3 a second bathroom door", "t3", "plan_3d",
     lambda: edit("t3", connections=[*PLANS["t3"].connections, ("SALA", "WC 2")]), "FAIL", {"door_added"}),
    ("t3 evaluator unsure", "t3", "plan_3d",
     lambda: edit("t3", unclear=["store room: door or cupboard?"]), "UNVERIFIED", set()),
    ("t1 unmeasured 3D faithful", "t1-unmeasured", "plan_3d", lambda: faithful("t1-unmeasured"), "PASS", set()),
    ("t1 unmeasured one more bedroom", "t1-unmeasured", "plan_3d_bedroom",
     lambda: carve("t1-unmeasured", "SALA", ["SW"], "SALA", ["NW", "W"]), "FAIL",
     {"bedroom_not_from_largest_room"}),
    ("tie 3D faithful", "t2-tie", "plan_3d", lambda: faithful("t2-tie"), "PASS", set()),
    ("tie bedroom from the living room", "t2-tie", "plan_3d_bedroom",
     lambda: carve("t2-tie", "SALA", ["NW"], "SALA"), "FAIL", {"bedroom_not_from_largest_room"}),
    ("tie bedroom from bedroom 1", "t2-tie", "plan_3d_bedroom",
     lambda: carve("t2-tie", "QUARTO 1", ["NE"], "HALL"), "FAIL", {"bedroom_not_from_largest_room"}),
    ("duplex 3D faithful", "duplex", "plan_3d", lambda: faithful("duplex"), "PASS", set()),
    ("duplex 3D of the ground floor only", "duplex", "plan_3d",
     lambda: drop("duplex", "QUARTO 1", "QUARTO 2", "PATAMAR", "WC", floors=1), "FAIL",
     {"room_removed", "door_removed", "window_removed", "floor_removed"}),
    ("duplex stairs left out", "duplex", "plan_3d", lambda: edit("duplex", stairs=False), "FAIL", {"stairs_removed"}),
    ("duplex a third floor", "duplex", "plan_3d", lambda: edit("duplex", floors=3), "FAIL", {"floor_added"}),
    ("duplex realistic living room", "duplex", "plan_real", lambda: only("duplex", "SALA"), "UNVERIFIED", set()),
    ("duplex one more bedroom from the living room", "duplex", "plan_3d_bedroom",
     lambda: carve("duplex", "SALA", ["C"], "SALA", ["NW", "N", "W"]), "PASS", set()),
]


@pytest.mark.parametrize("case,key,change,make,verdict,must", MATRIX, ids=[m[0] for m in MATRIX])
def test_matrix(case, key, change, make, verdict, must):
    result = compare(PLANS[key], make(), change, new_room_id="NOVO" if change == "plan_3d_bedroom" else None)
    assert result.verdict == verdict, (case, result.defects, result.unclear)
    assert must <= {d.code for d in result.defects}, (case, result.defects)


def test_the_matrix_covers_every_sample_and_every_verdict():
    assert {m[1] for m in MATRIX} == set(SAMPLES)
    assert {m[4] for m in MATRIX} == {"PASS", "FAIL", "UNVERIFIED"}
    for key in SAMPLES:
        assert {m[4] for m in MATRIX if m[1] == key} & {"FAIL", "UNVERIFIED"}, f"{key} has no negative case"


def test_the_bedroom_view_never_passes_without_a_single_largest_room():
    """Unmeasured plans and ties: the rule 'divide the largest room' has no answer, so the view can't pass."""
    for key in ("t1-unmeasured", "t2-tie"):
        for room in PLANS[key].rooms:
            if room.zones:
                result = compare(PLANS[key], carve(key, room.id, room.zones[:1], room.id), "plan_3d_bedroom",
                                 new_room_id="NOVO")
                assert result.verdict == "FAIL", (key, room.id)


def test_a_realistic_image_of_a_duplex_is_undecided_unless_floors_and_stairs_are_seen():
    """Codex hr012g-r1: one room usually can't show the other floor and the stairs, so it stays undecided; it only
    passes when the evaluator records both as seen (for example a living room with the stairs going up)."""
    for room in PLANS["duplex"].rooms:
        assert compare(PLANS["duplex"], only("duplex", room.id), "plan_real").verdict == "UNVERIFIED", room.id
    seen = only("duplex", "HALL", floors=2, stairs=True)
    assert compare(PLANS["duplex"], seen, "plan_real").verdict == "PASS"


# Stated limits (Codex hr012g-r1): these views are wrong but PASS, because the criterion only sees rooms by zone of a
# 3×3 grid and openings by the two rooms they join. For the last two, the evaluator's inventory of the wrong view is
# the plan's own: nothing in it can say how wide an opening is or where along the wall it sits. They are kept as tests
# so that a change in either direction shows.
LIMITS = [
    ("a new bedroom that overlaps the living room instead of dividing it",
     "t1", "plan_3d_bedroom", lambda: carve("t1", "SALA", ["SW"], "SALA")),
    ("the kitchen wall opened wide into an open-plan room, the kitchen kept",
     "t1", "plan_3d", lambda: faithful("t1")),
    ("a door moved along its wall, between the same two rooms", "t3", "plan_3d", lambda: faithful("t3")),
]


@pytest.mark.parametrize("case,key,change,make", LIMITS, ids=[m[0] for m in LIMITS])
def test_stated_limits_pass_and_need_the_evaluator(case, key, change, make):
    result = compare(PLANS[key], make(), change, new_room_id="NOVO" if change == "plan_3d_bedroom" else None)
    assert result.verdict == "PASS", case


def test_the_drawings_match_the_inventories():
    for key, s in SAMPLES.items():
        assert (SAMPLE_DIR / f"plan-{key}.png").is_file(), key
        assert len({r.id for r in s.rooms}) == len(s.rooms), key
        for a, b in s.doors:
            assert shared_wall(s.room(a), s.room(b)), (key, a, b)
        for field in (s.windows, s.entrances):
            for rid, sides in field.items():
                for side in sides:
                    assert on_outer_wall(s, s.room(rid), side), (key, rid, side)
        for room in PLANS[key].rooms:
            assert room.zones, (key, room.id)
        assert (all(r.area for r in PLANS[key].rooms)) == s.measured, key


def test_the_committed_drawings_are_redrawn_identically(tmp_path):
    """Codex hr012g-r2/r3: a geometry change without a redraw must not pass unnoticed, so a missing font fails."""
    from PIL import Image, ImageChops

    assert Path(FONT).is_file(), f"install the DejaVu fonts ({FONT}) to check the sample drawings"

    for key, s in SAMPLES.items():
        draw(s, tmp_path / f"{key}.png")
        with Image.open(tmp_path / f"{key}.png") as new, Image.open(SAMPLE_DIR / f"plan-{key}.png") as kept:
            assert new.size == kept.size, key
            assert ImageChops.difference(new.convert("RGB"), kept.convert("RGB")).getbbox() is None, \
                f"{key}: redraw with `python -m tests.plan_samples`"
