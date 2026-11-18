"""Rita in Studio (#85 del a): the drawing becomes the station model, with everything that is not
drawn computed (STUDIO-02, STUDIO-16, STUDIO-19, STUDIO-34), and a station's model opens as a
drawing for redrawing its panel and comes back the same (STUDIO-30). Nothing here names a
station (RS13): the reference stations are found from their files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.common import Side
from contracts.station_model import NodeType, Position, Source, StationModel, to_json
from contracts.tkl import PanelAngle, TklDrawing, TklDrawingState, TklObjectKind, TklObjectRef
from tkl.standard import checks, derive, lay_out, outside_of
from tkl.standard import plan as plan_checks
from tkl.studio import drawing_of, loose_ends, model_of, ordered_like, target_of, view
from tkl.tests.ritning import drawing, reversed_and_dragging, three_on_one_lever

MODELS = Path(__file__).resolve().parents[1] / "referens"
STATIONS = sorted(p.name.removesuffix(".tkl.json") for p in MODELS.glob("*.tkl.json"))
PLUS, MINUS = Position.PLUS, Position.MINUS


def reference(station: str) -> StationModel:
    return StationModel.model_validate_json((MODELS / f"{station}.tkl.json").read_text("utf-8"))


def with_plan() -> StationModel:
    """The reference station with a track plan of its own."""
    return next(m for m in map(reference, STATIONS) if m.panel is not None)


def routes(model: StationModel) -> set[tuple[str, str, str]]:
    return {(r.kind.value, r.start.name, r.end.name) for r in derive(model)}


# --- Drawing to model ------------------------------------------------------------------------


def test_the_six_objects_become_the_model_and_the_rest_is_computed() -> None:
    """Tracks, switches, signals, a boundary, a buffer stop and line exits, drawn; the nodes'
    types, the track circuits, the exits' signals and the panel's places are computed."""
    drawn = drawing()
    # The web app need not type every node: a switch's node, a signal's and an exit's say so.
    plain = drawn.model.model_copy(
        update={
            "nodes": [
                n
                if n.type in (NodeType.BLOCK_BOUNDARY, NodeType.BUFFER_STOP)
                else n.model_copy(update={"type": NodeType.JOINT})
                for n in drawn.model.nodes
            ]
        }
    )
    model = model_of(TklDrawing(model=plain))
    assert model == model_of(drawn)
    types = {n.id: n.type for n in model.nodes}
    assert types["S1"] == NodeType.SWITCH and types["A"] == NodeType.LINE_EXIT
    assert types["a1"] == NodeType.SIGNAL_POINT and types["bb"] == NodeType.BLOCK_BOUNDARY
    assert model.level == 2, "with signals"
    assert model.origin is not None and model.origin.source == Source.DRAWN
    assert model.origin.confirmed
    # Track circuits between the boundaries, the signals and the ends, named after the track
    # and the direction, a switch's block after the switch (STUDIO-19).
    assert {c.name: c.pieces for c in model.track_circuits} == {
        "SA": ["p1"],
        "Vx1": ["p2", "p3", "q1"],
        "S1v": ["p4"],
        "S1ö": ["p5"],
        "Vx2": ["p6", "p7", "q4"],
        "SB": ["p8"],
        "Vx3": ["q2", "q3", "r1"],
        "Sr2": ["r2"],
    }
    # The main signals that lead out onto the line at each exit (§6).
    assert {e.id: e.signals for e in model.line_exits} == {"A": ["1V", "2V"], "B": ["1Ö", "2Ö"]}
    # The panel shows every signal at its node, every exit at its end, each track's name.
    plan = model.panel
    assert plan is not None
    assert set(plan.signals) == {s.name for s in model.signals} | {"A", "B"}
    assert plan.signals["1V"].model_dump() == {"piece": "p4", "at": 0.0, "reversed": True}
    assert plan.signals["A1"].model_dump() == {"piece": "p1", "at": 1.0, "reversed": False}
    assert [(t.name, t.piece) for t in plan.track_names] == [("1", "p5"), ("2", "q3")]
    found, remarks = checks(model)
    assert found == []
    assert remarks == ["Linjeutfarten A saknar grannstation."]


def test_the_drawing_is_the_panel_and_the_station_runs() -> None:
    model = model_of(drawing())
    panel = plan_checks.build(model)
    assert panel.source.value == "plan"
    assert {n.id: n.cell for n in panel.nodes}["S3"] == (15, 7)
    assert {line.piece: line.cells for line in panel.lines}["q1"] == [(8, 4), (11, 7), (12, 7)]
    assert all(not line.real for line in panel.lines), "no real shape: Foto needs CAD"
    assert panel.real_box is None


def test_station_tracks_and_exits_give_the_outside() -> None:
    model = model_of(drawing())
    outside = outside_of(model, "ritby", "Ritby")
    assert [(t.id, t.label) for t in outside.tracks] == [("1", "Spår 1"), ("2", "Spår 2")]
    exits = {e.id: e for e in outside.exits}
    assert exits["A"].side == Side.LEFT and exits["B"].side == Side.RIGHT
    assert exits["A"].tracks == ["1", "2"] and exits["B"].name == "B mot Östby"


def test_the_engine_derives_the_routes_of_the_drawing() -> None:
    """STUDIO-16: train routes and shunting routes from the drawing."""
    assert routes(model_of(drawing())) == {
        ("train", "A1", "1Ö"),
        ("train", "A1", "2Ö"),
        ("train", "A1", "Stoppbock 1"),
        ("train", "B1", "1V"),
        ("train", "B1", "2V"),
        ("shunting", "D3", "2V"),
    }
    shown = view(drawing(), TklDrawingState.DRAFT)
    assert shown.routes == {"train": 5, "shunting": 1}
    assert shown.loose == []
    assert not [f for f in shown.findings if f.problem]


def test_a_lever_with_three_parts() -> None:
    model = model_of(drawing(levers=three_on_one_lever()))
    assert checks(model)[0] == []
    laid = {(r.start.name, r.end.name): dict(r.positions) for r in derive(model)}
    # A1 → 1Ö needs 1 straight: the lever lays 2 diverging (reversed) and 3 straight with it.
    assert laid[("A1", "1Ö")] == {"1": PLUS, "2": MINUS, "3": PLUS}
    # A1 → 2Ö needs 1 diverging and 3 straight: one lever both ways, so there is no such route.
    assert ("A1", "2Ö") not in laid


def test_a_reversed_switch_and_one_that_drags_another() -> None:
    model = model_of(drawing(levers=reversed_and_dragging()))
    assert [lever.model_dump() for lever in model.levers] == [
        {"id": "1/2", "plus": {"1": "+", "2": "-"}, "minus": {"1": "-", "2": "+"}},
        {"id": "3", "plus": {"3": "+"}, "minus": {"3": "-", "1": "-"}},
    ]
    laid = {(r.start.name, r.end.name): dict(r.positions) for r in derive(model)}
    assert laid[("A1", "Stoppbock 1")] == {"1": MINUS, "2": PLUS, "3": MINUS}
    assert laid[("B1", "2V")]["2"] == MINUS and laid[("B1", "2V")]["1"] == PLUS
    # 3 diverging drags 1 diverging, so 3 cannot be diverging while 1 lies straight.
    assert ("train", "B1", "1V") in routes(model)


def test_a_circuit_keeps_its_name_while_its_track_changes() -> None:
    first = model_of(drawing())
    renamed = [
        c.model_copy(update={"name": "Spår 1 väst"}) if c.name == "S1v" else c
        for c in first.track_circuits
    ]
    kept = model_of(drawing(track_circuits=renamed))
    assert [c.name for c in kept.track_circuits] == [c.name for c in renamed]
    # Without the boundary, track 1's two circuits are one: it keeps the first one's name.
    merged = drawing(
        track_circuits=renamed,
        nodes=[
            n.model_copy(update={"type": NodeType.JOINT}) if n.id == "bb" else n
            for n in first.nodes
        ],
    )
    names = {c.name: c.pieces for c in model_of(merged).track_circuits}
    assert names["Spår 1 väst"] == ["p4", "p5"]
    assert "S1ö" not in names


def test_checks_on_a_broken_drawing_say_where() -> None:
    """A loose end is a red dot and a problem; a junction without a switch and a signal whose
    track does not reach it are problems, each with the object it is about (RS7)."""
    good = drawing()
    nodes = [
        n.model_copy(update={"type": NodeType.JOINT}) if n.id == "Stoppbock 1" else n
        for n in good.model.nodes
    ]
    switches = [s for s in good.model.switches if s.number != "3"]
    signals = [
        s.model_copy(update={"approach": "p1"}) if s.name == "B1" else s for s in good.model.signals
    ]
    broken = drawing(nodes=nodes, switches=switches, signals=signals)
    model = model_of(broken)
    assert loose_ends(model) == ["Stoppbock 1"]
    shown = view(broken, TklDrawingState.DRAFT, model)
    assert shown.loose == ["Stoppbock 1"]
    problems = {f.text: f.target for f in shown.findings if f.problem}
    loose = next(t for t in problems if t.startswith("Spåret slutar utan att nå något"))
    assert loose.startswith("Spåret slutar utan att nå något i ruta (23, 10).")
    assert problems[loose] == TklObjectRef(kind=TklObjectKind.NODE, id="Stoppbock 1")
    assert "Noden Stoppbock 1 ska ha två spårbitar men har 1." not in problems, "said once"
    assert problems["Noden S3 ska ha två spårbitar men har 3."] == TklObjectRef(
        kind=TklObjectKind.NODE, id="S3"
    )
    assert problems["Signalen B1: spårbiten p1 når inte signalen."] == TklObjectRef(
        kind=TklObjectKind.SIGNAL, id="B1"
    )


def test_the_checks_name_what_they_are_about() -> None:
    model = model_of(drawing(levers=three_on_one_lever()))

    def target(text: str) -> tuple[str, str] | None:
        found = target_of(text, model)
        return None if found is None else (found.kind.value, found.id)

    assert target("Växel 3 saknar stam.") == ("switch", "3")
    assert target("Spaken 1/2/3: växel 4 finns inte.") == ("lever", "1/2/3")
    assert target("Spåren p4 och p5 ligger på samma ruta vid (14, 4).") == ("piece", "p4")
    assert target("Tågvägen från 1Ö slutar inte vid en signal: den når B.") == ("signal", "1Ö")
    assert target("Linjeutfarten A saknar grannstation.") == ("exit", "A")
    assert target("Spårledningen Vx1 har ingen spårbit.") == ("circuit", "Vx1")
    assert target("Noden Stoppbock 1 ska ha en spårbit men har 2.") == ("node", "Stoppbock 1")
    assert target("Stationen får inte plats på skärmen.") is None


# --- A station's model as a drawing, and back (STUDIO-30) ------------------------------------


@pytest.mark.parametrize("station", STATIONS)
def test_a_reference_station_opens_and_comes_back_the_same(station: str) -> None:
    """Open in Rita, change nothing, save: the same model, to the byte."""
    model = reference(station)
    opened = drawing_of(model)
    assert opened.proposal == (model.panel is None)
    sent = TklDrawing.model_validate(json.loads(opened.model_dump_json()))
    back = model_of(sent)
    assert back == model
    assert to_json(back) == (MODELS / f"{station}.tkl.json").read_text("utf-8")


@pytest.mark.parametrize("station", STATIONS)
def test_the_engine_layout_is_the_first_proposal_and_a_valid_plan(station: str) -> None:
    """A station without a plan opens on the engine's layout. Redrawn, it is kept as the
    station's plan: every node in its cell, every piece a track on the grid at 45°, the flat
    angle a grid twice as wide, and it holds by the same rules (STD-09, STD-26)."""
    model = reference(station)
    if model.panel is not None:
        pytest.skip("Stationen har en egen spårplan.")
    opened = drawing_of(model)
    plan = opened.model.panel
    assert plan is not None
    engine = lay_out(model)
    wide = 2 if engine.angle == PanelAngle.FLAT else 1
    assert plan.grid.dx == engine.cell[0] * wide
    redrawn = model_of(opened.model_copy(update={"proposal": False}))
    assert redrawn.panel is not None
    found, _ = checks(redrawn)
    assert found == []
    assert routes(redrawn) == routes(model)


def test_a_redrawn_plan_that_breaks_the_grid_s_rules_is_said() -> None:
    """STD-26: a line exit's track flipped across its node runs through other nodes and lies
    on another track. The checks say so, by track and cell."""
    model = with_plan()
    broken = broken_plan(model)
    found, _ = checks(model_of(TklDrawing(model=broken)))
    assert any(" går genom " in p or " ligger på samma ruta " in p for p in found), found


def broken_plan(model: StationModel) -> StationModel:
    """The plan with its first horizontal line exit's track flipped across its node."""
    plan = model.panel
    assert plan is not None
    for line in model.line_exits:
        track = next(t for t in plan.tracks if line.node in (t.start, t.end))
        other = track.end if track.start == line.node else track.start
        here, there = plan.nodes.get(line.node), plan.nodes.get(other)
        if track.via or here is None or there is None or here[1] != there[1]:
            continue
        nodes = {**plan.nodes, line.node: (2 * there[0] - here[0], here[1])}
        return model.model_copy(update={"panel": plan.model_copy(update={"nodes": nodes})})
    raise AssertionError("Ingen vågrät linjeutfart att flytta.")


def test_a_changed_model_keeps_the_file_s_order() -> None:
    """A browser may reorder a map whose keys look like numbers; the file keeps its order, so
    that a change shows as a change of a few lines."""
    model = with_plan()
    plan = model.panel
    assert plan is not None
    shuffled = dict(sorted(plan.nodes.items(), key=lambda item: (not item[0].isdigit(), item[0])))
    assert list(shuffled) != list(plan.nodes)
    moved = model.model_copy(update={"panel": plan.model_copy(update={"nodes": shuffled})})
    assert moved == model and to_json(moved) != to_json(model)
    assert to_json(ordered_like(moved, model)) == to_json(model)
