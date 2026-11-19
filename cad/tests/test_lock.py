"""Lås mått (CAD-24): the locked gable measures and the clean geometry between them, exact at
both gables and tangent at every joint, fitted to the line it replaces, or why there is none."""

from __future__ import annotations

import itertools
import math
import random

import pytest
from pydantic import TypeAdapter

from cad import curves, graph, lock, views
from cad.curves import Arc, Line
from cad.editor import Drawing, EditError
from contracts.cad import (
    Curve,
    DrawingState,
    EditOp,
    Gable,
    GableEnd,
    LockMeasures,
    LockRadii,
    Scale,
    Trapezoid,
)
from contracts.station_model import NodeType, Point

OPS: TypeAdapter[list[EditOp]] = TypeAdapter(list[EditOp])

# The photo test's MMM trapezoid (lärdomarna, Ren geometri): 685 × 480/280, the track 140 mm from
# Kant 1 in both gables, and the photo's line straight 64 – R 645 – straight 188 at 19° – R 645 –
# straight 25. That line moves the track 2·645·(1 - cos 19°) + 188·sin 19° = 131,5 mm sideways,
# so gable B's corner lies 131,5 mm across from gable A's.
OFFSET = 131.5
MMM = Trapezoid(length=685, width_a=480, width_b=280, offset=OFFSET)


def photo_line(seed: int = 3) -> list[Point]:
    """The photo's line as the photo test saw it: 138 mm at gable A, 141 at B, and the
    table's shape, with the photo's ±0,5 mm."""
    ends = lock.Ends((0, 138), 0.0, (685, OFFSET + 141), 0.0)
    shape = lock.build(ends, math.radians(19), 645, 645, 64)
    assert shape is not None
    rng = random.Random(seed)
    return [
        (x, y + rng.uniform(-0.5, 0.5))
        for x, y in curves.sample_path(lock.segments(ends, shape), 10)
    ]


def mmm_drawing() -> Drawing:
    """The trapezoid with the photo's line as its track, from 138 to 141 mm."""
    gables = [
        Gable(end=GableEnd.A, tracks=[140], profile="h0-mmm-enkelspar"),
        Gable(end=GableEnd.B, tracks=[140], profile="h0-mmm-enkelspar"),
    ]
    d = Drawing.of(Scale.H0, MMM, gables, graph.from_measures(MMM, gables), DrawingState())
    track = next(iter(d.pieces))
    d.apply_all(
        OPS.validate_python(
            [
                {"op": "delete", "target": track},
                {"op": "move", "target": "n1", "by": [0, -2]},
                {"op": "move", "target": "n2", "by": [0, 1]},
                {"op": "polyline", "points": photo_line(), "start_node": "n1", "end_node": "n2"},
                {"op": "smoothing", "level": "off"},
            ]
        )
    )
    return d


def check_template(ends: lock.Ends, segs: list[curves.Seg]) -> None:
    assert segs[0].start == pytest.approx(ends.p0, abs=1e-6)
    assert segs[-1].end == pytest.approx(ends.p1, abs=1e-6)
    assert curves.start_heading(segs[0]) == pytest.approx(ends.a0, abs=1e-9)
    assert curves.end_heading(segs[-1]) == pytest.approx(ends.a1, abs=1e-9)
    for before, after in itertools.pairwise(segs):
        assert after.start == pytest.approx(before.end, abs=1e-6)
        assert curves.start_heading(after) == pytest.approx(curves.end_heading(before), abs=1e-9)


def test_any_candidate_closes_exactly_at_both_gables_and_is_tangent_at_every_joint() -> None:
    ends = lock.Ends((0, 140), 0.0, (685, 140 + OFFSET), 0.0)
    checked = 0
    for degrees in range(5, 60, 5):
        for r1, r2, s1 in ((645, 645, 64), (900, 500, 20), (450, 520, 30), (400, 400, 0)):
            found = lock.build(ends, math.radians(degrees), r1, r2, s1)
            if found is None or lock.allowed(found, 400) > 0:
                continue
            segs = lock.segments(ends, found)
            assert [type(s) for s in segs] == [Line, Arc, Line, Arc, Line][-len(segs) :]
            check_template(ends, segs)
            checked += 1
    assert checked >= 8


def test_the_photo_tests_trapezoid_with_140_at_both_gables_gives_the_tables_shape() -> None:
    d = mmm_drawing()
    plan = d.lock_plan(LockMeasures())
    assert (plan.a, plan.b) == (140, 140)  # from MMM's profile
    assert plan.a_line == pytest.approx(138, abs=0.6) and plan.b_line == pytest.approx(141, abs=0.6)
    assert plan.solution is not None
    t = plan.solution.template
    assert [type(s) for s in plan.solution.segs] == [Line, Arc, Line, Arc, Line]
    assert t.r1 == t.r2 and 560 < t.r1 < 720
    assert math.degrees(t.t1) == pytest.approx(19, abs=1.5)
    assert math.degrees(t.t2) == pytest.approx(-19, abs=1.5)
    assert 40 < t.s1 < 110 and 150 < t.s2 < 240 and 0 < t.s3 < 60
    assert plan.solution.median < 1.0 and plan.solution.worst < 3.5
    check_template(lock.Ends((0, 140), 0.0, (685, OFFSET + 140), 0.0), plan.solution.segs)
    shown = views.lock_proposal(d, LockMeasures(), plan)
    assert [p.label for p in shown.parts] == [
        "Rakt från gavel A",
        "Båge",
        "Rakt",
        "Båge",
        "Rakt till gavel B",
    ]
    assert shown.parts[2].angle == pytest.approx(19, abs=1.5)
    assert len(shown.tangents) == 4 and shown.solved
    assert shown.why == (
        "MMM-normen säger 140 mm från Kant 1. Linjen låg 2 mm ifrån, så måttet låses och "
        "kurvan räknas om."
    )
    assert [(g.value, round(g.line)) for g in shown.gables] == [(140, 138), (140, 141)]


def test_different_radii_fit_at_least_as_close() -> None:
    d = mmm_drawing()
    same = d.lock_plan(LockMeasures(radii=LockRadii.SAME)).solution
    different = d.lock_plan(LockMeasures(radii=LockRadii.DIFFERENT)).solution
    assert same is not None and different is not None
    assert different.template.r1 != different.template.r2

    def mean(found: lock.Solution) -> float:
        return sum(x * x for x in found.deviation) / len(found.deviation)

    assert mean(different) <= mean(same) + 1e-6
    check_template(lock.Ends((0, 140), 0.0, (685, OFFSET + 140), 0.0), different.segs)


def test_using_the_geometry_keeps_the_first_id_and_records_the_split() -> None:
    d = mmm_drawing()
    old = next(iter(d.pieces))
    gable_nodes = {d.pieces[old].start, d.pieces[old].end}
    d.apply_all(OPS.validate_python([{"op": "lock"}]))
    change = d.ids[-1]
    assert change.why == "lock" and change.old == [old]
    assert change.new[0] == old and len(change.new) == 5
    assert set(d.pieces) == set(change.new)
    tangents = [n for n in d.nodes.values() if n.type == NodeType.JOINT]
    assert len(tangents) == 4 and all(d.count(n.id) == 2 for n in tangents)
    assert {n.id for n in d.nodes.values() if n.type == NodeType.MODULE_JOINT} == gable_nodes
    a = d.gable_line(GableEnd.A)
    b = d.gable_line(GableEnd.B)
    ends = [d.nodes[n].at for n in sorted(gable_nodes, key=lambda n: d.nodes[n].at[0])]
    assert a.offset(ends[0]) == pytest.approx(140) and b.offset(ends[1]) == pytest.approx(140)
    assert [(x.gable, x.value, round(x.line or 0)) for x in d.locks] == [
        (GableEnd.A, 140, 138),
        (GableEnd.B, 140, 141),
    ]
    # Locking again keeps the ids it has and never reuses one.
    issued = d.issued
    d.apply_all(OPS.validate_python([{"op": "lock", "piece": change.new[2]}]))
    assert d.ids[-1].new[0] == old and not set(d.ids[-1].new[1:]) & set(change.new)
    assert d.issued > issued


def test_a_lock_the_norm_refuses_and_a_curve_without_room_says_why() -> None:
    d = mmm_drawing()
    with pytest.raises(EditError, match="140 mm från Kant 1"):
        d.apply_all(OPS.validate_python([{"op": "lock", "a": 150}]))
    ends = lock.Ends((0, 140), 0.0, (200, 540), 0.0)
    with pytest.raises(lock.NoSolution) as no:
        lock.solve(ends, [(0, 140), (200, 540)], 400, True)
    assert str(no.value) == (
        "Spåret ska flytta 400 mm i sidled mellan gavlarna. Med minsta radien 400 mm behövs minst "
        "693 mm mellan gavlarna, och här är det 200 mm."
    )
    short = Trapezoid(length=150, width_a=480, width_b=280, offset=OFFSET)
    gables = [Gable(end=GableEnd.A, tracks=[140]), Gable(end=GableEnd.B, tracks=[140])]
    tight = Drawing.of(Scale.H0, short, gables, graph.from_measures(short, gables), DrawingState())
    plan = tight.lock_plan(LockMeasures())
    assert plan.solution is None and "behövs minst" in plan.why
    shown = views.lock_proposal(tight, LockMeasures(), plan)
    assert not shown.solved and shown.why == plan.why and shown.parts == []
    with pytest.raises(EditError, match="behövs minst"):
        tight.apply_all(OPS.validate_python([{"op": "lock"}]))


def test_a_straight_track_in_line_stays_one_straight() -> None:
    from contracts.cad import Straight

    shape = Straight(length=1500, width=500)
    gables = [Gable(end=GableEnd.A, tracks=[250]), Gable(end=GableEnd.B, tracks=[250])]
    d = Drawing.of(Scale.H0, shape, gables, graph.from_measures(shape, gables), DrawingState())
    plan = d.lock_plan(LockMeasures())
    assert plan.solution is not None and [type(s) for s in plan.solution.segs] == [Line]
    shown = views.lock_proposal(d, LockMeasures(), plan)
    assert [p.label for p in shown.parts] == ["Rakt från gavel A till gavel B"]


def test_a_curve_module_locked_closer_to_kant_1() -> None:
    shape = Curve(radius=2000, angle=30, width=500)
    gables = [Gable(end=GableEnd.A, tracks=[200]), Gable(end=GableEnd.B, tracks=[200])]
    d = Drawing.of(Scale.H0, shape, gables, graph.from_measures(shape, gables), DrawingState())
    plan = d.lock_plan(LockMeasures(a=140, b=140))
    assert plan.solution is not None
    a, b = d.gable_line(GableEnd.A), d.gable_line(GableEnd.B)
    segs = plan.solution.segs
    assert a.offset(segs[0].start) == pytest.approx(140) and b.offset(
        segs[-1].end
    ) == pytest.approx(140)
    assert curves.start_heading(segs[0]) == pytest.approx(0, abs=1e-9)
    assert curves.end_heading(segs[-1]) == pytest.approx(math.radians(30), abs=1e-9)
    for before, after in itertools.pairwise(segs):
        assert curves.start_heading(after) == pytest.approx(curves.end_heading(before), abs=1e-9)
    assert plan.solution.worst <= 60 + 1e-6  # never further than the concentric arc
