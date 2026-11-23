"""The panel built from a station's own track plan (STD-25–STD-28, TKL81, TKL82), with the
checks of tools/panel.py in the spec ported as tests. The reference station with a plan is the
answer key: 34 × 12 cells, and every route can be laid in it (STD-27). Each rule is refused
with a broken copy. Nothing here names a station (RS13); it is found from the files."""

from __future__ import annotations

import math
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from contracts.station_model import (
    NodeType,
    PanelDeviation,
    PanelDeviationSwitch,
    PanelPlan,
    StationModel,
)
from contracts.tkl import PanelSource
from tkl.standard import PlanError, build, checks, derive, plan
from tkl.standard.plan import _Builder

MODELS = Path(__file__).resolve().parents[2] / "tkl" / "referens"


@cache
def planned() -> StationModel:
    """The reference station that has its own track plan."""
    found = [
        StationModel.model_validate_json(p.read_text("utf-8"))
        for p in sorted(MODELS.glob("*.tkl.json"))
    ]
    with_plan = [m for m in found if m.panel is not None]
    assert len(with_plan) == 1
    return with_plan[0]


def the_plan() -> PanelPlan:
    found = planned().panel
    assert found is not None
    return found


def with_plan(**update: Any) -> StationModel:
    return planned().model_copy(update={"panel": the_plan().model_copy(update=update)})


def with_tracks(change: dict[int, dict[str, Any]]) -> StationModel:
    tracks = list(the_plan().tracks)
    for index, fields in change.items():
        tracks[index] = tracks[index].model_copy(update=fields)
    return with_plan(tracks=tracks)


def track_of(piece: str) -> int:
    return next(i for i, t in enumerate(the_plan().tracks) if t.pieces[0].id == piece)


def refused(model: StationModel) -> list[str]:
    with pytest.raises(PlanError) as error:
        build(model)
    assert error.value.problems == plan.problems(model)
    return error.value.problems


def test_the_station_with_a_plan_builds_at_34_by_12() -> None:
    panel = build(planned())
    assert panel.source == PanelSource.PLAN
    assert (panel.width, panel.height) == (34, 12)
    assert panel.cell == (the_plan().grid.dx, the_plan().grid.dy)
    assert {line.piece for line in panel.lines} == {p.id for p in planned().pieces}
    assert len(panel.signals) == len(planned().signals)
    assert panel.platforms and panel.building is not None
    assert {t.name for t in panel.track_names} == {t.name for t in the_plan().track_names}


def test_its_checks_have_no_problems() -> None:
    assert checks(planned())[0] == []


def test_every_route_the_engine_derives_can_be_drawn_in_the_plan() -> None:
    """STD-27: every route is laid without a gap, over the turntable's bridge where it turns."""
    panel = build(planned())
    lines = {line.piece: line.cells for line in panel.lines}
    table = the_plan().turntable
    at_table = {
        p.id for p in planned().pieces if table is not None and table.node in (p.start, p.end)
    }
    routes = derive(planned())
    assert len(routes) >= 227
    for route in routes:
        for one, other in pairwise(route.steps):
            end = lines[one.piece][-1 if one.forward else 0]
            start = lines[other.piece][0 if other.forward else -1]
            if one.piece in at_table and other.piece in at_table:
                continue
            assert math.dist(end, start) < 1e-6, (route.name, one.piece, other.piece)


# --- STD-26: the grid, and the panel hangs together as the station --------------------


def test_a_track_runs_horizontally_vertically_or_diagonally() -> None:
    index = next(i for i, t in enumerate(the_plan().tracks) if not t.free and not t.via)
    track = the_plan().tracks[index]
    start = the_plan().nodes[track.start]
    knight = (start[0] + 2, start[1] + 1)
    found = refused(with_tracks({index: {"via": [knight]}}))
    assert any("går varken vågrätt, lodrätt eller diagonalt" in f for f in found), found


def test_two_tracks_may_not_lie_on_the_same_cell() -> None:
    """A track drawn back over another one's cells."""
    tracks = the_plan().tracks
    index = next(
        i
        for i, t in enumerate(tracks)
        if not t.free and not t.via and the_plan().nodes[t.start][1] == the_plan().nodes[t.end][1]
    )
    track = tracks[index]
    a, b = the_plan().nodes[track.start], the_plan().nodes[track.end]
    detour = [(b[0], a[1] + 1), (a[0], a[1] + 1), (a[0], a[1]), (b[0], b[1])]
    found = refused(with_tracks({index: {"via": detour}}))
    assert any("ligger på samma ruta" in f or "går genom" in f for f in found), found


def test_no_crossing_without_a_crossing() -> None:
    """Move a switch one cell up: its tracks now cut across their neighbours."""
    nodes = dict(the_plan().nodes)
    switch = next(s for s in planned().switches if s.type.value == "ordinary" and s.node in nodes)
    x, y = nodes[switch.node]
    nodes[switch.node] = (x, y + 0.5)
    found = refused(with_plan(nodes=nodes))
    assert found


def test_the_tracks_follow_the_station() -> None:
    """Two tracks that swap their pieces no longer run between the nodes the pieces join."""
    tracks = the_plan().tracks
    one = next(i for i, t in enumerate(tracks) if len(t.pieces) == 1 and not t.free and not t.link)
    other = next(
        i
        for i, t in enumerate(tracks)
        if len(t.pieces) == 1 and not t.free and not t.link and i != one
    )
    found = refused(
        with_tracks({one: {"pieces": tracks[other].pieces}, other: {"pieces": tracks[one].pieces}})
    )
    assert any("hänger inte ihop som i stationen" in f for f in found), found


def test_every_piece_has_a_place_and_only_one() -> None:
    tracks = list(the_plan().tracks)
    dropped = tracks.pop(track_of(tracks[0].pieces[0].id))
    found = refused(with_plan(tracks=tracks))
    assert any(dropped.pieces[0].id in f and "utan plats" in f for f in found), found
    twice = [*the_plan().tracks, the_plan().tracks[0]]
    assert any("står i två spår" in f for f in refused(with_plan(tracks=twice)))


def test_a_switch_s_legs_reach_it() -> None:
    """A switch whose cell is away from where its tracks meet."""
    nodes = dict(the_plan().nodes)
    switch = next(s for s in planned().switches if s.type.value == "ordinary")
    tracks = [
        t.model_copy(update={"end": "X"}) if t.end == switch.node else t for t in the_plan().tracks
    ]
    tracks = [t.model_copy(update={"start": "X"}) if t.start == switch.node else t for t in tracks]
    nodes["X"] = nodes[switch.node]
    nodes[switch.node] = (nodes[switch.node][0] + 40, nodes[switch.node][1] + 40)
    found = refused(with_plan(nodes=nodes, tracks=tracks))
    assert any(f"Växel {switch.number}: benet" in f for f in found), found


def test_a_crossing_carries_its_ways_to_the_panel() -> None:
    """As a slip does (STV-22): the panel has the ways through it, here without positions."""
    ways = {s.node: s.paths for s in planned().switches if s.type.value == "crossing"}
    found = {s.node: s.paths for s in build(planned()).switches if s.node in ways}
    assert ways and found == ways


def test_four_tracks_meet_in_a_crossing() -> None:
    nodes = dict(the_plan().nodes)
    crossing = next(s for s in planned().switches if s.type.value == "crossing")
    tracks = [
        t.model_copy(update={"end": "Y"}) if t.end == crossing.node else t
        for t in the_plan().tracks
    ]
    tracks = [
        t.model_copy(update={"start": "Y"}) if t.start == crossing.node else t for t in tracks
    ]
    nodes["Y"] = nodes[crossing.node]
    nodes[crossing.node] = (nodes[crossing.node][0] + 40, nodes[crossing.node][1] + 40)
    found = refused(with_plan(nodes=nodes, tracks=tracks))
    assert any(f"Korsningen {crossing.number}: fyra spår" in f for f in found), found


def test_the_joints_are_counted_along_the_track() -> None:
    index = next(i for i, t in enumerate(the_plan().tracks) if len(t.pieces) == 2)
    found = refused(with_tracks({index: {"joints": []}}))
    assert any("kräver 1 skarvar, har 0" in f for f in found), found
    found = refused(with_tracks({index: {"joints": [1000.0]}}))
    assert any("skarvarna ligger inte i ordning" in f for f in found), found


def test_every_route_can_be_followed_without_a_gap() -> None:
    """The safety net behind the others: a piece drawn off its place leaves a gap."""
    builder = _Builder(planned(), the_plan())
    assert builder.check() == []
    route = next(r for r in derive(planned()) if len(r.steps) > 2)
    piece = route.steps[1].piece
    builder.paths[piece] = [(c[0] + 5, c[1]) for c in builder.paths[piece]]
    assert any("glapp" in f for f in builder._routes())


# --- STD-28: a deviation said out loud -------------------------------------------------


def deviation() -> PanelDeviation:
    found = the_plan().deviation
    assert found is not None
    return found


def with_deviation(**update: Any) -> StationModel:
    return with_plan(deviation=deviation().model_copy(update=update))


def test_without_its_deviation_the_plan_is_not_built() -> None:
    """The rewired pieces keep the old drawing's shape: without the deviation they do not hang
    together as the drawing."""
    found = refused(with_plan(deviation=None))
    assert any("hänger inte ihop som i ritningen" in f for f in found), found
    rewired = refused(with_deviation(rewired=[]))
    assert any("ritningen" in f for f in rewired), rewired


def test_a_track_that_is_not_shown_may_carry_no_route() -> None:
    """Hide a piece that routes use: it is still in a track, and routes go over it."""
    used = derive(planned())[0].pieces[0]
    hidden = deviation().not_shown.model_copy(
        update={"pieces": [*deviation().not_shown.pieces, used]}
    )
    found = refused(with_deviation(not_shown=hidden))
    assert any("går över ett spår som inte visas" in f for f in found) or any(
        "under avviker som något som inte visas" in f for f in found
    ), found


def test_a_hidden_switch_has_no_lever_and_no_leg_shown() -> None:
    lever = planned().levers[0]
    part = next(iter(lever.plus))
    hidden = deviation().not_shown.model_copy(
        update={"switches": [*deviation().not_shown.switches, part]}
    )
    found = refused(with_deviation(not_shown=hidden))
    assert any(f"Spaken {lever.id} har en växel som inte visas" in f for f in found), found


def test_a_rewired_track_is_fixed_at_both_ends() -> None:
    """A rewired piece that ends in a bare joint: it ends in the air."""
    model = planned()
    piece = next(
        p
        for p in model.pieces
        if any(n.id == p.end and n.type == NodeType.BUFFER_STOP for n in model.nodes)
    )
    nodes = [
        n.model_copy(update={"type": NodeType.JOINT}) if n.id == piece.end else n
        for n in model.nodes
    ]
    broken = model.model_copy(update={"nodes": nodes})
    plan_ = the_plan().model_copy(
        update={"deviation": deviation().model_copy(update={"rewired": [piece.id]})}
    )
    broken = broken.model_copy(update={"panel": plan_})
    found = plan.problems(broken)
    assert f"Det omkopplade spåret {piece.id} slutar i tomma luften." in found, found


def test_a_renumbered_switch_must_not_take_a_number_in_use() -> None:
    switches = {
        number: renamed
        for number, renamed in deviation().switches.items()
        if renamed.drawing_number is not None
    }
    assert switches, "the reference plan renumbers a switch"
    number, renamed = next(iter(switches.items()))
    taken = renamed.drawing_number
    left = {n: r for n, r in deviation().switches.items() if n != taken}
    found = refused(with_deviation(switches=left))
    assert f"Växel {number} har nummer {taken} i ritningen, men {taken} finns redan." in found


def test_a_knot_lies_under_the_nodes() -> None:
    found = refused(with_deviation(knots=["Ingenstans"]))
    assert "Knuten Ingenstans saknas under noder." in found


def test_a_new_switch_must_exist() -> None:
    switches = {**deviation().switches, "999": PanelDeviationSwitch()}
    found = refused(with_deviation(switches=switches))
    assert "Avvikelsen nämner växel 999, som inte finns i stationen." in found


def test_a_station_without_a_plan_has_no_plan_problems() -> None:
    assert plan.problems(planned().model_copy(update={"panel": None})) == []
    with pytest.raises(PlanError):
        build(planned().model_copy(update={"panel": None}))
