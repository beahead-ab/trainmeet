"""Från CAD in Studio as pure Python (#89 del d2, STUDIO-03, CAD-10, CAD-20): CAD's track graph of
an assembly becomes a proposal, everything yellow, and a re-import shows the difference while the
owner's additions on pieces whose ids are kept stay. The graph is the contract's example, made by
CAD's own code (contracts/examples/exempel.studio-graph.json). Nothing here names a station."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from contracts.cad import (
    GableEnd,
    GraphNode,
    GraphPiece,
    LineSegment,
    StudioGraph,
    StudioModule,
)
from contracts.station_model import NodeType, Signal, SignalType, StationModel
from contracts.tkl import TklDrawingState
from tkl.standard import problems
from tkl.studio import fran_cad, rita

EXAMPLE = (
    Path(__file__).resolve().parents[2] / "contracts" / "examples" / "exempel.studio-graph.json"
)
THIRD = UUID("7b0c1d2e-3f40-4a51-8b62-9c7d8e9f0a1b")


def before() -> StudioGraph:
    return StudioGraph.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))


def line(graph: StudioGraph) -> GraphPiece:
    """The line module's piece, the one the owner numbered 1 in CAD."""
    return next(p for p in graph.graph.pieces if p.track == "1")


def after(graph: StudioGraph) -> StudioGraph:
    """The line 300 mm shorter at its next version, ids kept, and a third module behind it."""
    piece = line(graph)
    end = piece.end
    x = piece.segments[-1].end[0] - 300
    nodes = [
        n.model_copy(update={"at": (x, n.at[1])}) if n.id == end else n for n in graph.graph.nodes
    ]
    third_end = GraphNode(
        id=f"{THIRD}:n2", type=NodeType.MODULE_JOINT, at=(x + 1000, 140), gable=GableEnd.B, track=1
    )
    pieces = [
        p.model_copy(update={"segments": [LineSegment(start=p.segments[0].start, end=(x, 140))]})
        if p.id == piece.id
        else p
        for p in graph.graph.pieces
    ]
    pieces.append(
        GraphPiece(
            id=f"{THIRD}:s3",
            start=end,
            end=third_end.id,
            segments=[LineSegment(start=(x, 140), end=(x + 1000, 140))],
            track="1",
        )
    )
    modules = [
        *graph.source.modules,
        StudioModule(id=THIRD, number="M-003", name="Linje bortom", version=1),
    ]
    return StudioGraph(
        source=graph.source.model_copy(update={"revision": 3, "modules": modules}),
        graph=graph.graph.model_copy(update={"nodes": [*nodes, third_end], "pieces": pieces}),
    )


def confirmed(model: StationModel) -> StationModel:
    return model.model_copy(
        update={
            key: [
                i.model_copy(update={"origin": i.origin.model_copy(update={"confirmed": True})})
                if i.origin is not None
                else i
                for i in getattr(model, key)
            ]
            for key in ("pieces", "switches", "line_exits")
        }
    )


def test_the_proposal_is_cads_graph_with_its_ids_yellow_until_confirmed() -> None:
    graph = before()
    model = fran_cad.proposal(graph, "exb", "Exempelby")
    assert {p.id for p in model.pieces} == {p.id for p in graph.graph.pieces}
    assert all(
        p.origin
        and p.origin.note == rita.FROM_CAD
        and not p.origin.confirmed
        and p.origin.ref == p.id
        for p in model.pieces
    )
    kinds = sorted(n.type.value for n in model.nodes)
    assert kinds == ["buffer_stop", "line_exit", "line_exit", "module_joint", "switch"]
    assert [e.id for e in model.line_exits] == ["Väst 1", "Öst 1"]
    assert [s.number for s in model.switches] == ["1"] and model.switches[
        0
    ].design == "R 830 · 11,4°"
    assert [(t.id, t.label) for t in model.station_tracks] == [("1", "Spår 1")]
    # The real shape for Foto, the arc as points.
    stub = next(p for p in model.pieces if p.end == "Stoppbock 1")
    assert len(stub.geometry) > 5
    view = rita.view(rita.drawing_of(model), TklDrawingState.DRAFT)
    assert [f.text for f in view.findings if f.problem] == [
        "7 saker ur TrainMeet CAD är inte bekräftade. Bekräfta dem en och en, eller alla med "
        "Bekräfta förslaget."
    ]
    assert problems(rita.model_of(rita.drawing_of(confirmed(model)))) == []


def test_a_reimport_shows_the_difference_and_keeps_the_owners_additions() -> None:
    graph = before()
    first = rita.model_of(rita.drawing_of(confirmed(fran_cad.proposal(graph, "exb", "Exempelby"))))
    # The owner's additions in Studio: a signal on the switch module's first piece, the west exit
    # renamed, and the line exit at the line's far end, which the third module will run on from.
    trunk = next(p for p in first.pieces if p.id == first.switches[0].trunk)
    owned = first.model_copy(
        update={
            "signals": [
                Signal(name="A1", type=SignalType.HSI, lamps=2, node=trunk.end, approach=trunk.id)
            ],
            "line_exits": [
                e.model_copy(update={"id": "Mot Väster"}) if e.id == "Väst 1" else e
                for e in first.line_exits
            ],
        }
    )
    changed = after(graph)
    merged, diff = fran_cad.reimport(owned, fran_cad.proposal(changed, "exb", "Exempelby"), changed)
    assert not diff.first
    assert [p.text for p in diff.added] == ["M-003 Linje bortom · spår 1"]
    assert [p.text for p in diff.moved] == ["M-002 Linje · spår 1"]
    assert diff.removed == [] and diff.lost == []
    assert diff.kept == ["en signal", "en linjeutfart med ditt namn", "3 bekräftade spårbitar"]
    assert [s.name for s in merged.signals] == ["A1"]
    assert {e.id for e in merged.line_exits} == {"Mot Väster", "Öst 1"}
    moved = next(p for p in merged.pieces if p.id == line(graph).id)
    assert moved.origin is not None and not moved.origin.confirmed
    assert moved.geometry[-1][0] == line(graph).segments[-1].end[0] - 300
    kept = next(p for p in merged.pieces if p.id == trunk.id)
    assert kept.origin is not None and kept.origin.confirmed
    assert rita.unconfirmed(merged) == 3
    # Back again: the third module's piece is gone, and the exit moves back with its name.
    again, back = fran_cad.reimport(
        confirmed(merged),
        fran_cad.proposal(graph, "exb", "Exempelby"),
        graph,
        fran_cad.modules_of(changed),
    )
    assert [p.text for p in back.removed] == ["M-003 Linje bortom · spår 1"]
    assert [p.text for p in back.moved] == ["M-002 Linje · spår 1"]
    assert {e.id for e in again.line_exits} == {"Mot Väster", "Öst 1"}


def test_what_hung_on_a_piece_that_is_gone_is_lost_and_said() -> None:
    graph = before()
    first = rita.model_of(rita.drawing_of(confirmed(fran_cad.proposal(graph, "exb", "Exempelby"))))
    stub = next(p for p in first.pieces if p.end == "Stoppbock 1")
    owned = first.model_copy(
        update={
            "signals": [Signal(name="S9", type=SignalType.DVSI, node=stub.start, approach=stub.id)]
        }
    )
    gone = graph.model_copy(
        update={
            "graph": graph.graph.model_copy(
                update={
                    "pieces": [p for p in graph.graph.pieces if p.id != stub.id],
                    "nodes": [n for n in graph.graph.nodes if n.type != NodeType.JOINT],
                    "switches": [],
                }
            )
        }
    )
    merged, diff = fran_cad.reimport(owned, fran_cad.proposal(gone, "exb", "Exempelby"), gone)
    assert [p.id for p in diff.removed] == [stub.id]
    assert diff.lost == ["Signal S9"] and merged.signals == []
    assert diff.panel is False


def test_the_first_import_over_a_drawn_station_replaces_it() -> None:
    graph = before()
    drawn = StationModel(station_id="exb", name="Exempelby", level=1, nodes=[], pieces=[])
    model, diff = fran_cad.reimport(drawn, fran_cad.proposal(graph, "exb", "Exempelby"), graph)
    assert diff.first and not diff.replaced and len(diff.added) == len(graph.graph.pieces)
    assert model.pieces[0].origin is not None
