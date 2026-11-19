"""The track graph of a module from measures (CAD-01), its ids (CAD-20) and how it maps to the
station model for Studio (CAD-10)."""

from __future__ import annotations

import math

import pytest

from cad import graph
from contracts.cad import (
    ArcSegment,
    Curve,
    Gable,
    GableEnd,
    LineSegment,
    Straight,
    TrackGraph,
    Trapezoid,
)
from contracts.station_model import NodeType, Source, StationModel


def gables(a: list[float], b: list[float] | None = None) -> list[Gable]:
    return [
        Gable(end=GableEnd.A, tracks=a),
        Gable(end=GableEnd.B, tracks=a if b is None else b),
    ]


def test_a_straight_module_gets_one_straight_track_per_gable_track() -> None:
    made = graph.from_measures(Straight(length=1500, width=500), gables([140, 197]))
    assert made.complete and made.geometry == "mm"
    assert [(n.gable, n.track, n.at) for n in made.nodes] == [
        (GableEnd.A, 1, (0, 140)),
        (GableEnd.A, 2, (0, 197)),
        (GableEnd.B, 1, (1500, 140)),
        (GableEnd.B, 2, (1500, 197)),
    ]
    assert all(n.type == NodeType.MODULE_JOINT for n in made.nodes)
    assert [p.segments for p in made.pieces] == [
        [LineSegment(start=(0, 140), end=(1500, 140))],
        [LineSegment(start=(0, 197), end=(1500, 197))],
    ]
    assert graph.track_length(made) == 3000


def test_a_curve_gets_concentric_arcs() -> None:
    curve = Curve(radius=2000, angle=30, width=500)
    made = graph.from_measures(curve, gables([200, 250]))
    arcs = [p.segments[0] for p in made.pieces]
    assert all(isinstance(a, ArcSegment) for a in arcs)
    assert [a.radius for a in arcs if isinstance(a, ArcSegment)] == [2000, 1950]
    assert graph.track_length(made) == pytest.approx(
        2000 * math.pi / 6 + 1950 * math.pi / 6, rel=1e-9
    )
    first = arcs[0]
    assert isinstance(first, ArcSegment) and first.clockwise  # right curve from gable A


def test_a_trapezoid_keeps_kant_1_straight_and_its_track_with_it() -> None:
    """MMM's trapezoid, 685 × 480/280: the track at 140 mm in both gables."""
    made = graph.from_measures(Trapezoid(length=685, width_a=480, width_b=280), gables([140]))
    assert made.pieces[0].segments == [LineSegment(start=(0, 140), end=(685, 140))]


def test_gables_that_differ_leave_the_tracks_between_for_the_photo() -> None:
    """Rak modul: 2 spår in vid A, 3 spår ut vid B; hur de går emellan vet vi först när modulen
    är fotad."""
    made = graph.from_measures(
        Straight(length=1500, width=700), gables([330, 380], [245, 295, 345])
    )
    assert not made.complete
    assert made.pieces == []
    assert len(made.nodes) == 5


def test_a_module_without_tracks_is_complete_and_empty() -> None:
    made = graph.from_measures(Straight(length=600, width=500), gables([]))
    assert made.complete and made.nodes == [] and made.pieces == []


def test_the_ids_stay_when_the_measures_are_corrected() -> None:
    shape = Straight(length=1500, width=500)
    first_gables = gables([250, 300])
    first = graph.from_measures(shape, first_gables)
    again = graph.from_measures(
        Straight(length=1520, width=500), gables([252, 302]), (first, first_gables)
    )
    assert [n.id for n in again.nodes] == [n.id for n in first.nodes]
    assert [p.id for p in again.pieces] == [p.id for p in first.pieces]
    assert again.issued == first.issued


def test_a_new_track_gets_a_new_id_and_the_old_ones_stay() -> None:
    shape = Straight(length=1500, width=500)
    first_gables = gables([250])
    first = graph.from_measures(shape, first_gables)
    more_gables = gables([200, 251])
    more = graph.from_measures(shape, more_gables, (first, first_gables))
    old_piece = first.pieces[0].id
    assert old_piece in [p.id for p in more.pieces]
    kept = next(p for p in more.pieces if p.id == old_piece)
    assert kept.segments[0].start == (0, 251)
    new_ids = {n.id for n in more.nodes} - {n.id for n in first.nodes}
    assert len(new_ids) == 2


def test_an_id_is_never_used_again_for_something_else() -> None:
    shape = Straight(length=1500, width=500)
    one = gables([250])
    first = graph.from_measures(shape, one)
    none = gables([])
    empty = graph.from_measures(shape, none, (first, one))
    back = graph.from_measures(shape, one, (empty, none))
    used_before = {n.id for n in first.nodes} | {p.id for p in first.pieces}
    used_now = {n.id for n in back.nodes} | {p.id for p in back.pieces}
    assert not used_before & used_now
    assert back.issued > first.issued


def test_the_graph_maps_to_the_station_models_parts_with_the_same_ids() -> None:
    """CAD → Studio is a mapping (CAD-10): the station model's nodes and pieces, with CAD's ids,
    the module joints, and the arcs as points every 10 mm."""
    curve = Curve(radius=2000, angle=30, width=500)
    made = graph.from_measures(curve, gables([200, 250]))
    nodes, pieces = graph.as_station_model(made)
    assert [n.id for n in nodes] == [n.id for n in made.nodes]
    assert {n.type for n in nodes} == {NodeType.MODULE_JOINT}
    assert [(p.id, p.start, p.end) for p in pieces] == [(p.id, p.start, p.end) for p in made.pieces]
    track1 = pieces[0]
    assert track1.geometry[0] == made.pieces[0].segments[0].start
    assert track1.geometry[-1] == made.pieces[0].segments[0].end
    steps = [math.dist(a, b) for a, b in zip(track1.geometry, track1.geometry[1:], strict=False)]
    assert max(steps) <= graph.SAMPLE_STEP + 0.01
    assert track1.origin is not None and track1.origin.source == Source.ASSUMED
    # The station model takes the parts as they are.
    model = StationModel.model_validate(
        {
            "format": "trainmeet.station-model/1",
            "station_id": "prov",
            "name": "Prov",
            "level": 1,
            "nodes": [n.model_dump(mode="json") for n in nodes],
            "pieces": [p.model_dump(mode="json") for p in pieces],
        }
    )
    assert len(model.pieces) == 2


def test_the_graph_round_trips_through_its_contract() -> None:
    made = graph.from_measures(Curve(radius=2000, angle=30, width=500), gables([200]))
    assert TrackGraph.model_validate_json(made.model_dump_json()) == made
