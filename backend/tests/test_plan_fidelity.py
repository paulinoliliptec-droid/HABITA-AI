"""HR-012 plan-view fidelity criterion (proposal): zero tolerance, fail-closed.

The plan is the synthetic two-bedroom plan of the real test of 2026-11-01; ``R2_VIEW`` is the inventory of the
one-more-bedroom view made from it that day (revision 00057-jaq), as observed by Claude, not by the image service.
"""

import pytest

from app.services.concepts.fidelity import Inventory, Room, compare

PLAN = Inventory(
    rooms=[Room(id="SALA", type="living", area=32, zones=["NW", "W", "SW"]),
           Room(id="COZINHA", type="kitchen", area=15, zones=["N", "NE"]),
           Room(id="HALL", type="hall", area=5, zones=["C"]), Room(id="WC", type="bathroom", area=5, zones=["E"]),
           Room(id="QUARTO 1", type="bedroom", area=9, zones=["S"]),
           Room(id="QUARTO 2", type="bedroom", area=9, zones=["SE"])],
    connections=[("SALA", "COZINHA"), ("SALA", "HALL"), ("HALL", "QUARTO 1"), ("HALL", "WC"), ("WC", "QUARTO 2")],
    windows={"SALA": ["N", "W"], "COZINHA": ["N"], "QUARTO 1": ["S"], "QUARTO 2": ["S"]},
    entrances={"SALA": ["S"]},
)
R2_VIEW = PLAN.model_copy(update={
    "rooms": [*PLAN.rooms, Room(id="NOVO", type="bedroom", carved_from="SALA", zones=["NW"])],
    "connections": [*PLAN.connections, ("NOVO", "SALA")],
    "windows": {"SALA": ["N"], "NOVO": ["W"], "COZINHA": ["N"], "QUARTO 1": ["S"], "QUARTO 2": ["S"]},
})
LIVING_ONLY = Inventory(rooms=[Room(id="SALA", type="living", zones=["NW", "W", "SW"])], connections=[("SALA", "COZINHA")],
                        windows={"SALA": ["N", "W"]}, entrances={"SALA": ["S"]}, partial=True,
                        not_in_frame=[("SALA", "HALL")])


def view(base: Inventory = PLAN, **update) -> Inventory:
    return base.model_copy(update=update)


def codes(result) -> list[str]:
    return [d.code for d in result.defects]


def bedroom(v: Inventory):
    return compare(PLAN, v, "plan_3d_bedroom", new_room_id="NOVO")


def test_the_real_one_more_bedroom_view_passes():
    result = bedroom(R2_VIEW)
    assert result.verdict == "PASS" and result.defects == []


def test_a_faithful_3d_view_passes_and_an_added_store_room_fails():
    assert compare(PLAN, view(), "plan_3d").verdict == "PASS"
    added = view(rooms=[*PLAN.rooms, Room(id="ARRUMOS", type="storage")],
                 connections=[*PLAN.connections, ("ARRUMOS", "HALL")])
    result = compare(PLAN, added, "plan_3d")
    assert result.verdict == "FAIL" and codes(result) == ["room_added", "door_added"]


def test_a_stair_or_another_floor_fails():
    assert codes(compare(PLAN, view(stairs=True), "plan_real")) == ["stairs_added"]
    assert codes(compare(PLAN, view(floors=2), "plan_3d")) == ["floor_added"]


def test_the_realistic_image_judges_the_room_it_shows():
    assert compare(PLAN, LIVING_ONLY, "plan_real").verdict == "PASS"
    assert codes(compare(PLAN, view(LIVING_ONLY, windows={"SALA": ["N", "W", "E"]}), "plan_real")) == ["window_added"]
    hole = view(LIVING_ONLY, connections=[("SALA", "COZINHA"), ("SALA", "QUARTO 1")])
    assert codes(compare(PLAN, hole, "plan_real")) == ["door_added"]


def test_a_partial_view_cannot_hide_a_missing_opening_it_does_not_declare():
    """Codex hr012f-r1: an opening of the shown room missing from the view must not pass."""
    closed = view(LIVING_ONLY, not_in_frame=[])
    assert codes(compare(PLAN, closed, "plan_real")) == ["door_removed"]


def test_only_the_realistic_image_may_be_partial():
    """Codex hr012f-r1: a 3D view marked partial can't skip missing rooms."""
    result = compare(PLAN, view(LIVING_ONLY), "plan_3d")
    assert result.verdict == "FAIL" and "partial_not_allowed" in codes(result)


def test_anything_the_evaluator_cannot_decide_is_never_a_pass():
    assert compare(PLAN, view(unclear=["kitchen bottom wall: door or furniture?"]), "plan_3d").verdict == "UNVERIFIED"
    assert compare(PLAN, view(stairs=True, unclear=["x"]), "plan_3d").verdict == "FAIL"


def test_changed_openings_rooms_types_windows_and_entrances_fail():
    moved = view(connections=[("SALA", "COZINHA"), ("SALA", "HALL"), ("HALL", "QUARTO 1"), ("HALL", "WC"),
                              ("HALL", "QUARTO 2")])
    assert sorted(codes(compare(PLAN, moved, "plan_3d"))) == ["door_added", "door_removed"]
    gone = view(rooms=[r for r in PLAN.rooms if r.id != "WC"],
                connections=[p for p in PLAN.connections if "WC" not in p])
    assert "room_removed" in codes(compare(PLAN, gone, "plan_3d"))
    retyped = view(rooms=[r if r.id != "QUARTO 2" else Room(id="QUARTO 2", type="office") for r in PLAN.rooms])
    assert codes(compare(PLAN, retyped, "plan_3d")) == ["room_type_changed"]
    assert codes(compare(PLAN, view(entrances={"SALA": ["S"], "COZINHA": ["N"]}), "plan_3d")) == ["entrance_changed"]
    # Codex hr012f-r1: a window moved to another wall of the same room fails.
    wall = view(windows={**PLAN.windows, "QUARTO 1": ["E"]})
    assert sorted(codes(compare(PLAN, wall, "plan_3d"))) == ["window_added", "window_removed"]
    # Codex hr012f-r1: a second door between the same two rooms fails.
    assert codes(compare(PLAN, view(connections=[*PLAN.connections, ("HALL", "WC")]), "plan_3d")) == ["door_added"]


def test_the_extra_bedroom_must_be_one_room_with_one_door_out_of_the_largest_room():
    assert codes(bedroom(view())) == ["bedroom_not_added"]
    assert "door_added" in codes(bedroom(view(R2_VIEW, connections=[*R2_VIEW.connections, ("NOVO", "COZINHA")])))
    assert "door_added" in codes(bedroom(view(R2_VIEW, connections=[*R2_VIEW.connections, ("NOVO", "SALA")])))
    to_bedroom = view(R2_VIEW, connections=[*PLAN.connections, ("NOVO", "QUARTO 1")])
    assert "bedroom_not_from_largest_room" in codes(bedroom(to_bedroom))
    assert codes(bedroom(view(R2_VIEW, rooms=[*R2_VIEW.rooms, Room(id="ARRUMOS", type="storage")]))) == ["room_added"]
    assert codes(bedroom(view(R2_VIEW, windows={**R2_VIEW.windows, "NOVO": ["W", "S"]}))) == ["window_added"]


def test_the_extra_bedroom_must_be_carved_from_the_largest_room():
    """Codex hr012f-r1: where it was carved from is stated by the evaluator, not inferred from its door."""
    other = [r if r.id != "NOVO" else Room(id="NOVO", type="bedroom", carved_from="COZINHA", zones=["NW"])
             for r in R2_VIEW.rooms]
    assert codes(bedroom(view(R2_VIEW, rooms=other))) == ["bedroom_not_from_largest_room"]
    unknown = [r if r.id != "NOVO" else Room(id="NOVO", type="bedroom", zones=["NW"]) for r in R2_VIEW.rooms]
    assert codes(bedroom(view(R2_VIEW, rooms=unknown))) == ["bedroom_not_from_largest_room"]
    tie = view(rooms=[r if r.id != "COZINHA" else Room(id="COZINHA", type="kitchen", area=32, zones=["N", "NE"])
                      for r in PLAN.rooms])
    assert "bedroom_not_from_largest_room" in codes(compare(tie, R2_VIEW, "plan_3d_bedroom", new_room_id="NOVO"))


def test_the_entrance_cannot_move_into_the_new_bedroom():
    """Codex hr012f-r1: entrances are never transferred to the new bedroom."""
    moved = view(R2_VIEW, entrances={"NOVO": ["S"]})
    assert sorted(codes(bedroom(moved))) == ["entrance_changed", "entrance_changed"]


def test_a_floor_or_stair_that_disappears_fails():
    """Codex hr012f-r2."""
    two = view(floors=2, stairs=True)
    assert sorted(codes(compare(two, view(), "plan_3d"))) == ["floor_removed", "stairs_removed"]


def test_a_realistic_image_must_show_a_room():
    """Codex hr012f-r2."""
    assert codes(compare(PLAN, Inventory(rooms=[], partial=True), "plan_real")) == ["nothing_shown"]


def test_without_every_area_there_is_no_largest_room():
    """Codex hr012f-r2: a room without an area could be the largest."""
    unsized = view(rooms=[r if r.id != "COZINHA" else Room(id="COZINHA", type="kitchen", zones=["N", "NE"])
                          for r in PLAN.rooms])
    assert "bedroom_not_from_largest_room" in codes(compare(unsized, R2_VIEW, "plan_3d_bedroom", new_room_id="NOVO"))


def test_rooms_keep_their_place_on_the_drawing():
    """Codex hr012f-r2: a room moved elsewhere fails; a room whose place isn't stated is undecided."""
    swapped = view(rooms=[r.model_copy(update={"zones": {"QUARTO 1": ["SE"], "QUARTO 2": ["S"]}.get(r.id, r.zones)})
                          for r in PLAN.rooms])
    assert codes(compare(PLAN, swapped, "plan_3d")) == ["room_moved", "room_moved"]
    blank = view(rooms=[r.model_copy(update={"zones": []}) if r.id == "WC" else r for r in PLAN.rooms])
    assert compare(PLAN, blank, "plan_3d").verdict == "UNVERIFIED"
    elsewhere = [r.model_copy(update={"zones": ["SE"]}) if r.id == "NOVO" else r for r in R2_VIEW.rooms]
    assert codes(bedroom(view(R2_VIEW, rooms=elsewhere))) == ["bedroom_not_from_largest_room"]
    shrunk = [r.model_copy(update={"zones": ["N"]}) if r.id == "COZINHA" else r for r in PLAN.rooms]
    assert codes(compare(PLAN, view(rooms=shrunk), "plan_3d")) == ["room_moved"]


def test_positions_and_ids_leave_no_gap():
    """Codex hr012f-r3."""
    no_zone = view(LIVING_ONLY, rooms=[Room(id="SALA", type="living")])
    assert compare(PLAN, no_zone, "plan_real").verdict == "UNVERIFIED"
    unplaced = view(rooms=[r.model_copy(update={"zones": []}) if r.id == "WC" else r for r in PLAN.rooms])
    assert compare(unplaced, view(), "plan_3d").verdict == "UNVERIFIED"
    lost = [r.model_copy(update={"zones": ["W"]}) if r.id == "SALA" else r for r in R2_VIEW.rooms]
    assert codes(bedroom(view(R2_VIEW, rooms=lost))) == ["room_removed"]
    twice = view(rooms=[*PLAN.rooms, Room(id="WC", type="bathroom", zones=["E"])])
    assert codes(compare(PLAN, twice, "plan_3d")) == ["room_added"]
    with pytest.raises(ValueError):
        compare(twice, view(), "plan_3d")


def test_what_a_partial_view_cannot_show_is_undecided_and_strays_fail():
    """Codex hr012f-r4."""
    two = view(floors=2, stairs=True)
    assert compare(two, LIVING_ONLY, "plan_real").verdict == "UNVERIFIED"
    assert codes(compare(PLAN, view(windows={**PLAN.windows, "EXTRA": ["N"]}), "plan_3d")) == ["window_added"]
    assert codes(compare(PLAN, view(entrances={**PLAN.entrances, "EXTRA": ["S"]}), "plan_3d")) == ["entrance_changed"]


def test_only_plan_views_are_judged():
    with pytest.raises(ValueError):
        compare(PLAN, view(), "new_kitchen")
