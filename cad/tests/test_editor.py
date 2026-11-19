"""Ritningen's editing operations (CAD-03), the ids that stay (CAD-20), the switch inspector, the
switch library and Att kolla, without a database."""

from __future__ import annotations

import math
from typing import Any
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from cad import checks, curves, editor, graph, switches, views
from cad.editor import Drawing, EditError
from contracts.cad import (
    ArcSegment,
    CheckKind,
    Curve,
    DrawingSource,
    DrawingState,
    EditOp,
    Gable,
    GableEnd,
    LineSegment,
    Scale,
    Shape,
    Smoothing,
    Straight,
    TrackGraph,
    Trapezoid,
)
from contracts.station_model import NodeType, StationModel

OPS: TypeAdapter[list[EditOp]] = TypeAdapter(list[EditOp])


def drawing(
    shape: Shape | None = None,
    a: list[float] | None = None,
    b: list[float] | None = None,
    profile: str | None = None,
) -> Drawing:
    """A module from measures, ready to draw on: straight 1500 × 700, one track at 250."""
    shape = shape if shape is not None else Straight(length=1500, width=700)
    a = [250] if a is None else a
    gables = [
        Gable(end=GableEnd.A, tracks=a, profile=profile),
        Gable(end=GableEnd.B, tracks=a if b is None else b, profile=profile),
    ]
    return Drawing.of(Scale.H0, shape, gables, graph.from_measures(shape, gables), DrawingState())


def apply(d: Drawing, *ops: dict[str, Any]) -> Drawing:
    d.apply_all(OPS.validate_python(list(ops)))
    return d


def piece_at(d: Drawing, node: str) -> str:
    found = d.on(node)
    assert len(found) == 1
    return found[0]


def through_piece(d: Drawing) -> str:
    return next(iter(d.pieces))


def station_model(d: Drawing) -> StationModel:
    nodes, pieces, found = graph.as_station_model(d.graph())
    return StationModel.model_validate(
        {
            "format": "trainmeet.station-model/1",
            "station_id": "prov",
            "name": "Prov",
            "level": 1,
            "nodes": [n.model_dump(mode="json") for n in nodes],
            "pieces": [p.model_dump(mode="json") for p in pieces],
            "switches": [s.model_dump(mode="json") for s in found],
        }
    )


def a_switch(d: Drawing, **extra: Any) -> str:
    before = set(d.switches)
    apply(
        d,
        {
            "op": "switch",
            "piece": through_piece(d),
            "from_a": 400,
            "radius": 830,
            "angle": 11.4,
            "side": "right",
            **extra,
        },
    )
    return next(iter(set(d.switches) - before))


# --- The editing operations -----------------------------------------------------------------


def test_a_straight_track_joins_ends_and_makes_module_joints_on_the_gables() -> None:
    d = drawing(a=[])
    apply(d, {"op": "line", "start": [0, 400], "end": [700, 400]})
    first = next(iter(d.pieces.values()))
    start, end = d.nodes[first.start], d.nodes[first.end]
    assert start.type == NodeType.MODULE_JOINT and start.gable == GableEnd.A
    assert end.type == NodeType.JOINT and end.at == (700, 400)
    apply(d, {"op": "line", "start": [700.4, 400.3], "end": [1500, 400]})
    assert d.count(end.id) == 2  # snapped onto the free end within 1 mm
    assert len(d.nodes) == 3 and d.source == DrawingSource.DRAWN
    with pytest.raises(EditError, match="utanför modulen"):
        apply(d, {"op": "line", "start": [100, 100], "end": [100, 900]})
    with pytest.raises(EditError, match="för kort"):
        apply(d, {"op": "line", "start": [100, 100], "end": [100.5, 100]})


def test_an_arc_by_radius_and_angle_continues_the_track_and_by_three_points() -> None:
    d = drawing(a=[])
    apply(d, {"op": "line", "start": [0, 200], "end": [300, 200]})
    end = next(n for n in d.nodes.values() if n.type == NodeType.JOINT)
    apply(d, {"op": "arc", "start": [300, 200], "start_node": end.id, "radius": 800, "angle": 20})
    arc = next(p for p in d.pieces.values() if isinstance(p.segs[0], curves.Arc))
    seg = arc.segs[0]
    assert isinstance(seg, curves.Arc) and seg.clockwise and seg.radius == 800
    assert curves.start_heading(seg) == pytest.approx(0, abs=1e-9)  # tangent to the line
    assert math.degrees(curves.end_heading(seg)) == pytest.approx(20)
    apply(d, {"op": "arc", "start": [100, 500], "through": [400, 450], "end": [700, 500]})
    three = list(d.pieces.values())[-1].segs[0]
    assert isinstance(three, curves.Arc) and three.clockwise  # bulging up: a right turn
    assert math.dist(three.center, (400, 450)) == pytest.approx(three.radius)
    with pytest.raises(ValueError, match="tre punkter"):
        OPS.validate_python([{"op": "arc", "start": [0, 0], "end": [1, 1]}])


def test_a_hand_drawn_line_is_smoothed_and_kept_for_the_level() -> None:
    d = drawing(a=[])
    wobbly = [(x, 300 + 3 * math.sin(x / 20)) for x in range(100, 1101, 10)]
    apply(d, {"op": "polyline", "points": wobbly})
    piece = next(iter(d.pieces.values()))
    assert len(piece.segs) <= 3  # Normal: one clean line, not a hundred
    assert d.lines[piece.id].points[0] == pytest.approx(wobbly[0], abs=0.001)
    apply(d, {"op": "smoothing", "level": "off"})
    assert len(d.pieces[piece.id].segs) == len(wobbly) - 1
    assert d.smoothing == Smoothing.OFF
    assert d.state().smoothing == Smoothing.OFF
    apply(d, {"op": "smoothing", "level": "normal"})
    assert len(d.pieces[piece.id].segs) <= 3 and piece.id in d.pieces


def test_a_switch_splits_its_track_and_its_leg_leaves_tangentially() -> None:
    d = drawing()
    old = through_piece(d)
    sw_id = a_switch(d)
    sw = d.switches[sw_id]
    node = d.nodes[sw.node]
    assert node.type == NodeType.SWITCH and node.at == pytest.approx((400, 250))
    assert sw.trunk == old  # the first part keeps the id
    assert sw.straight not in (old, None) and sw.diverging is not None
    leg = d.away(sw.diverging, sw.node)[0]
    assert isinstance(leg, curves.Arc) and leg.radius == pytest.approx(830)
    assert curves.start_heading(leg) == pytest.approx(0, abs=1e-9)
    assert math.degrees(curves.turn_of(leg)) == pytest.approx(11.4)
    assert d.ids[-1].old == [old] and d.ids[-1].new == [old, sw.straight]
    assert d.ids[-1].why == "switch"
    assert sw.number == "1"
    with pytest.raises(EditError, match="hamnar utanför"):
        a_switch(drawing(), from_a=1600)


def test_moving_a_switch_keeps_every_id_and_its_leg_follows() -> None:
    d = drawing()
    sw_id = a_switch(d)
    sw = d.switches[sw_id]
    ids = (set(d.nodes), set(d.pieces), set(d.switches), d.issued)
    far = d.other(sw.diverging or "", sw.node)
    far_before = d.nodes[far].at
    apply(d, {"op": "move_switch", "switch": sw_id, "from_a": 650})
    assert (set(d.nodes), set(d.pieces), set(d.switches), d.issued) == ids
    assert d.nodes[sw.node].at == pytest.approx((650, 250))
    assert d.nodes[far].at == pytest.approx((far_before[0] + 250, far_before[1]))
    total = sum(curves.path_length(d.pieces[p].segs) for p in (sw.trunk or "", sw.straight or ""))
    assert total == pytest.approx(1500)
    # A diverging leg joined at its far end keeps its end and is bent to it.
    apply(d, {"op": "line", "start": list(d.nodes[far].at), "start_node": far, "end": [1500, 500]})
    apply(d, {"op": "move_switch", "switch": sw_id, "from_a": 600})
    assert d.nodes[far].at == pytest.approx((far_before[0] + 250, far_before[1]))
    leg = d.away(sw.diverging or "", sw.node)
    assert isinstance(leg[0], curves.Arc) and leg[-1].end == pytest.approx(d.nodes[far].at)


def test_moving_a_node_a_piece_and_a_label_reshapes_without_new_ids() -> None:
    d = drawing(a=[])
    apply(d, {"op": "line", "start": [0, 300], "end": [600, 300]})
    apply(d, {"op": "arc", "start": [600, 300], "through": [800, 330], "end": [1000, 400]})
    piece_ids = list(d.pieces)
    joint = next(n for n in d.nodes.values() if n.type == NodeType.JOINT and d.count(n.id) == 2)
    issued = d.issued
    apply(d, {"op": "move", "target": joint.id, "by": [0, 20]})
    assert list(d.pieces) == piece_ids and d.issued == issued
    arc = d.pieces[piece_ids[1]].segs[0]
    assert isinstance(arc, curves.Arc) and arc.start == pytest.approx((600, 320))
    gable_end = d.pieces[piece_ids[0]].start
    apply(d, {"op": "move", "target": gable_end, "by": [50, 10]})
    assert d.nodes[gable_end].at == pytest.approx((0, 310))  # only along the gable
    apply(d, {"op": "move", "target": piece_ids[1], "by": [0, -20]})
    assert d.pieces[piece_ids[1]].segs[0].start == pytest.approx((600, 300))
    apply(d, {"op": "label", "at": [200, 100], "text": "Lastgata"})
    label = next(iter(d.labels))
    apply(d, {"op": "move", "target": label, "by": [10, 10]})
    assert d.labels[label].at == (210, 110)


def test_delete_removes_and_never_reuses_an_id() -> None:
    d = drawing()
    sw_id = a_switch(d)
    sw = d.switches[sw_id]
    trunk, straight, diverging = sw.trunk, sw.straight, sw.diverging
    used = set(d.nodes) | set(d.pieces) | set(d.switches)
    with pytest.raises(EditError, match="Ta bort växeln först"):
        apply(d, {"op": "delete", "target": straight})
    apply(d, {"op": "delete", "target": sw_id})
    assert sw_id not in d.switches and diverging not in d.pieces and straight not in d.pieces
    assert trunk in d.pieces
    assert d.ids[-1].old == [trunk, straight] and d.ids[-1].new == [trunk]
    assert curves.path_length(d.pieces[trunk or ""].segs) == pytest.approx(1500)
    apply(d, {"op": "line", "start": [100, 500], "end": [300, 500]})
    fresh = (set(d.nodes) | set(d.pieces)) - used
    assert fresh and all(int(x[1:]) > d.issued - len(fresh) - 1 for x in fresh)
    assert not fresh & used
    with pytest.raises(EditError, match="Ändra måtten"):
        apply(d, {"op": "delete", "target": d.pieces[trunk or ""].start})


def test_join_two_ends_and_cut_a_piece() -> None:
    d = drawing(a=[])
    apply(d, {"op": "line", "start": [0, 300], "end": [500, 300]})
    apply(d, {"op": "line", "start": [520, 310], "end": [1500, 310]})
    ends = [n.id for n in d.nodes.values() if n.type == NodeType.JOINT]
    apply(d, {"op": "join", "a": ends[0], "b": ends[1]})
    joint = d.nodes[ends[0]]
    assert ends[1] not in d.nodes and d.count(joint.id) == 2
    assert joint.at == pytest.approx((510, 305))
    first = next(iter(d.pieces))
    apply(d, {"op": "cut", "piece": first, "at": [200, 300]})
    assert d.ids[-1].why == "cut" and d.ids[-1].old == [first]
    assert d.ids[-1].new[0] == first and len(d.pieces) == 3
    assert curves.path_length(d.pieces[first].segs) == pytest.approx(200, abs=0.5)
    with pytest.raises(EditError, match="Välj två olika ändar"):
        apply(d, {"op": "join", "a": joint.id, "b": joint.id})


def test_text_labels_on_a_track_a_switch_and_free() -> None:
    d = drawing()
    sw_id = a_switch(d)
    trunk = d.switches[sw_id].trunk or ""
    apply(
        d,
        {"op": "label", "target": trunk, "text": "1"},
        {"op": "label", "target": sw_id, "text": "Vx 4"},
        {"op": "label", "at": [700, 600], "text": "Godsmagasin"},
    )
    built = d.graph()
    assert next(p for p in built.pieces if p.id == trunk).track == "1"
    assert built.switches[0].number == "Vx 4"
    assert [x.text for x in built.labels] == ["Godsmagasin"]
    apply(d, {"op": "label", "target": built.labels[0].id, "text": ""})
    assert d.graph().labels == []


def test_the_switch_inspector_and_its_type() -> None:
    d = drawing(a=[250, 400], b=[250, 400])
    pieces = list(d.pieces)
    sw_id = a_switch(d, side="right", radius=700, angle=12)
    sw = d.switches[sw_id]
    far = d.other(sw.diverging or "", sw.node)
    target = d.nodes[next(n for n in d.nodes if d.nodes[n].track == 2)]
    assert target.at == (0, 400) or target.gable is not None
    info = views.switch_infos(d)[0]
    assert info.number == "1" and info.from_a == 400 and info.radius == 700
    assert info.leaves == "spår från A1 mot änden"
    assert info.design == "okand" and info.matched is None and info.assumed
    assert not info.locked and info.side == "right"
    # Choosing a type gives the switch its radius and angle.
    apply(d, {"op": "set_switch", "switch": sw_id, "design": "h0-r830-114", "locked": True})
    info = views.switch_infos(d)[0]
    assert info.design == "h0-r830-114" and info.radius == 830 and info.angle == 11.4
    assert info.locked and not info.assumed
    leg = d.away(sw.diverging or "", sw.node)[0]
    assert isinstance(leg, curves.Arc) and leg.radius == pytest.approx(830)
    apply(d, {"op": "set_switch", "switch": sw_id, "radius": 1000})
    assert d.switches[sw_id].radius == 1000 and d.nodes[far].at != pytest.approx((0, 0))
    assert pieces[0] in d.pieces


def test_the_switch_types_and_how_a_radius_matches_them() -> None:
    names = [d.name for d in switches.designs(Scale.H0)]
    assert names[0] == "Okänd" and "R 2200 · 9,4°" in names and len(names) == 6
    assert all(d.source for d in switches.designs(Scale.H0)[1:])
    assert switches.designs(Scale.N) == [switches.UNKNOWN]
    assert switches.match(2150, 9.0, Scale.H0) is not None
    assert switches.match(2100 * 1.09, None, Scale.H0) is not None
    assert switches.match(705, None, Scale.H0) is None  # no type within 10 %: antagen
    assert switches.match(830, None, Scale.N) is None
    limits = switches.limits(Scale.H0)
    assert (limits.min_radius, limits.switch_min_radius, limits.kink) == (400, 300, 1.43)


# --- Att kolla ------------------------------------------------------------------------------


def kinds(d: Drawing) -> dict[CheckKind, list[Any]]:
    found: dict[CheckKind, list[Any]] = {}
    for item in checks.find(d):
        if item.answer is None:
            found.setdefault(item.kind, []).append(item)
    return found


def test_a_rail_short_of_a_gable_and_both_answers() -> None:
    for answer, piece_count in (("passbit", 2), ("hela-vagen", 1)):
        d = drawing(a=[])
        apply(d, {"op": "line", "start": [51, 400], "end": [1500, 400]})
        item = kinds(d)[CheckKind.SHORT_RAIL][0]
        assert item.title == "Rälsen slutar 51 mm före gavel A"
        assert [c.text for c in item.choices] == ["Det är en passbit", "Rälsen går ända fram"]
        apply(d, {"op": "answer", "key": item.key, "answer": answer})
        assert len(d.pieces) == piece_count
        assert CheckKind.SHORT_RAIL not in kinds(d)
        reached = [n for n in d.nodes.values() if n.gable == GableEnd.A]
        assert len(reached) == 1 and d.count(reached[0].id) == 1


def test_an_open_end_and_a_buffer_stop() -> None:
    d = drawing(a=[])
    apply(d, {"op": "line", "start": [0, 400], "end": [700, 400]})
    item = kinds(d)[CheckKind.OPEN_END][0]
    assert item.title == "Spåret slutar utan att mötas"
    apply(d, {"op": "answer", "key": item.key, "answer": "stoppbock"})
    assert any(n.type == NodeType.BUFFER_STOP for n in d.nodes.values())
    assert CheckKind.OPEN_END not in kinds(d)
    with pytest.raises(EditError, match="finns inte längre"):
        apply(d, {"op": "answer", "key": "open_end:n99", "answer": "slutar"})


def test_a_switch_at_the_lower_limit_and_an_assumed_switch() -> None:
    d = drawing()
    sw_id = a_switch(d, radius=300, angle=12)
    item = kinds(d)[CheckKind.SWITCH_RADIUS][0]
    assert item.title == "Växel 1: radien blev 300 mm" and item.assumed
    assert "vid nedre gränsen" in item.text
    assert [c.action for c in item.choices] == ["design", None]
    apply(d, {"op": "set_switch", "switch": sw_id, "radius": 705})
    assumed = kinds(d)[CheckKind.SWITCH_ASSUMED][0]
    assert assumed.title == "Växel 1 är antagen, R 705 mm"
    with pytest.raises(EditError, match="Svaret finns inte"):
        apply(d, {"op": "answer", "key": assumed.key, "answer": "valj-typ"})
    apply(d, {"op": "answer", "key": assumed.key, "answer": "radien-stammer"})
    assert CheckKind.SWITCH_ASSUMED not in kinds(d)
    apply(d, {"op": "set_switch", "switch": sw_id, "radius": 720})
    assert CheckKind.SWITCH_ASSUMED in kinds(d)  # a new radius asks again
    apply(d, {"op": "set_switch", "switch": sw_id, "design": "h0-r970-95"})
    assert CheckKind.SWITCH_ASSUMED not in kinds(d)


def test_a_kink_and_a_radius_under_the_minimum() -> None:
    d = drawing(a=[])
    apply(d, {"op": "line", "start": [0, 300], "end": [600, 300]})
    end = next(n.id for n in d.nodes.values() if n.type == NodeType.JOINT)
    apply(d, {"op": "line", "start": [600, 300], "start_node": end, "end": [1500, 400]})
    kink = kinds(d)[CheckKind.KINK][0]
    assert kink.title == "Knyck 6,3°" and kink.refs == [end]
    d = drawing(a=[])
    apply(d, {"op": "arc", "start": [0, 300], "heading": 0, "radius": 300, "angle": 60})
    tight = kinds(d)[CheckKind.TIGHT_RADIUS][0]
    assert tight.title == "Snäv radie: R 300 mm"
    assert "minsta radien 400 mm" in tight.text
    d = drawing(a=[])
    apply(d, {"op": "arc", "start": [0, 300], "heading": 0, "radius": 400, "angle": 60})
    assert CheckKind.TIGHT_RADIUS not in kinds(d) and CheckKind.KINK not in kinds(d)


def test_a_gable_track_off_its_measure_and_off_the_norm() -> None:
    d = drawing(a=[140], profile="h0-mmm-enkelspar")
    track = through_piece(d)
    apply(d, {"op": "move", "target": d.pieces[track].start, "by": [0, -2.5]})
    item = kinds(d)[CheckKind.GABLE_POSITION][0]
    assert item.title == "Gavel A · spår 1 ligger 138 mm från Kant 1"
    assert item.text.startswith("MMM-normen säger 140 mm.")
    assert [(c.text, c.action) for c in item.choices] == [
        ("Lås måttet", "lock"),
        ("Behåll läget", None),
    ]
    apply(d, {"op": "answer", "key": item.key, "answer": "behall"})
    assert CheckKind.GABLE_POSITION not in kinds(d)
    d = drawing(a=[])
    apply(d, {"op": "line", "start": [0, 300], "end": [1500, 300]})
    stray = kinds(d)[CheckKind.GABLE_POSITION][0]
    assert stray.title == "Gavel A: ett spår 300 mm från Kant 1 som gaveln inte har"


def test_a_module_from_measures_has_nothing_to_check_until_drawn() -> None:
    assert checks.find(drawing()) == []
    differ = drawing(a=[330, 380], b=[245, 295, 345])
    assert checks.find(differ) == []  # waiting for the photo, not asked about yet
    apply(differ, {"op": "line", "start": [0, 330], "end": [1500, 245]})
    opened = kinds(differ)[CheckKind.OPEN_END]
    assert len(opened) == 3 and all("går inte in i modulen" in i.title for i in opened)


# --- The station model ----------------------------------------------------------------------


def test_every_drawing_the_editor_makes_maps_to_the_station_model_with_switches() -> None:
    d = drawing(a=[250, 400], b=[250, 400])
    sw_id = a_switch(d, side="right", radius=830, angle=11.4)
    apply(
        d,
        {
            "op": "switch",
            "piece": d.switches[sw_id].straight,
            "from_a": 1000,
            "radius": 970,
            "angle": 9.5,
            "side": "left",
            "toward": "A",
        },
        {"op": "label", "target": sw_id, "text": "3"},
    )
    model = station_model(d)
    assert [s.number for s in model.switches] == ["3", "2"]
    assert all(s.trunk and s.straight and s.diverging for s in model.switches)
    assert model.switches[0].design == "R 830 · 11,4°"
    ids = {n.id for n in model.nodes}
    assert {s.node for s in model.switches} <= ids
    for piece in model.pieces:
        assert piece.start in ids and piece.end in ids and len(piece.geometry) >= 2
    assert TrackGraph.model_validate_json(d.graph().model_dump_json()) == d.graph()


def test_a_trapezoid_with_an_offset_gets_its_gable_b_where_the_corner_is() -> None:
    shape = Trapezoid(length=685, width_a=480, width_b=280, offset=131.5)
    d = drawing(shape, a=[140])
    track = d.pieces[through_piece(d)].segs[0]
    assert isinstance(track, curves.Line) and track.end == (685, 271.5)
    assert graph.from_measures(shape, d.gables).pieces[0].segments == [
        LineSegment(start=(0, 140), end=(685, 271.5))
    ]


def test_a_curve_measures_from_gable_a_along_its_own_radius() -> None:
    shape = Curve(radius=2000, angle=30, width=500)
    d = drawing(shape, a=[200, 250])
    assert isinstance(d.graph().pieces[0].segments[0], ArcSegment)
    sw_id = a_switch(d, from_a=500)
    at = d.nodes[d.switches[sw_id].node].at
    assert d.from_a(at) == pytest.approx(500, abs=0.01)
    assert math.dist(at, (0, 2200)) == pytest.approx(2000, abs=0.01)


def test_the_view_says_what_the_canvas_needs() -> None:
    d = drawing()
    a_switch(d)
    shown = views.view(uuid4(), 1, 1, d)
    assert shown.stats.switches == 1 and shown.stats.track_length > 1500
    assert [x.level for x in shown.smoothing_levels] == list(Smoothing)
    normal = next(x for x in shown.smoothing_levels if x.level == Smoothing.NORMAL)
    assert normal.text == (
        "Knaggliga linjer blir mjuka kurvor. Normal: minsta radie 400 mm och högst 9 mm från "
        "linjen."
    )
    assert shown.designs[0].id == "okand" and shown.changed


def test_a_refused_operation_says_which_and_why() -> None:
    d = drawing()
    with pytest.raises(EditError, match=r"Ändring 2 går inte: Spårbiten finns inte\."):
        apply(
            d,
            {"op": "line", "start": [100, 500], "end": [300, 500]},
            {"op": "cut", "piece": "s99", "at": [0, 0]},
        )
    assert editor.SNAP == 1.0


def test_a_track_drawn_from_the_middle_of_another_makes_a_switch_to_its_end() -> None:
    d = drawing(a=[250, 500], b=[250, 500])
    lower = next(p for p in d.pieces.values() if d.nodes[p.start].track == 2)
    upper = next(p for p in d.pieces.values() if d.nodes[p.start].track == 1)
    apply(
        d,
        {"op": "delete", "target": lower.id},
        {
            "op": "switch",
            "piece": upper.id,
            "from_a": 300,
            "radius": 830,
            "to": [1500, 500],
            "to_node": lower.end,
        },
    )
    sw = next(iter(d.switches.values()))
    assert sw.toward == GableEnd.B and sw.angle is not None and 0 < sw.angle < 90
    leg = d.away(sw.diverging or "", sw.node)
    assert isinstance(leg[0], curves.Arc) and leg[0].clockwise  # down the drawing: right
    assert leg[-1].end == (1500, 500) and d.other(sw.diverging or "", sw.node) == lower.end
    assert curves.end_heading(leg[0]) == pytest.approx(curves.start_heading(leg[-1]))
    info = views.switch_infos(d)[0]
    assert info.leaves == "spår från A1 mot B2" and info.side == "right"
    with pytest.raises(EditError, match="når inte dit"):
        apply(
            d,
            {
                "op": "switch",
                "piece": sw.straight,
                "from_a": 1000,
                "radius": 830,
                "to": [1100, 270],
            },
        )
