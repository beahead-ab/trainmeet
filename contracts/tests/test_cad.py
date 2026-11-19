"""TrainMeet CAD's contracts (#89): scale and norm, gable profiles, the shapes, the module and
the track graph."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from contracts import cad
from contracts.cad import (
    NORM_NAMES,
    NORMS,
    ArcSegment,
    Gable,
    GableEnd,
    GableProfile,
    GraphNode,
    GraphPiece,
    LineSegment,
    NewModule,
    NewProfile,
    Norm,
    Scale,
    TrackGraph,
)
from contracts.station_model import NodeType


def test_the_scales_and_their_norms_from_the_start() -> None:
    """CAD9–CAD12, CAD-22: H0, N and 0; in H0 FREMO, MMM, USMS and the club's own, in 0 FREMO
    Spur 0, and in N FREMO N from the start (CAD14, 19 November)."""
    assert [s.value for s in Scale] == ["H0", "N", "0"]
    assert NORMS[Scale.H0] == (Norm.FREMO, Norm.MMM, Norm.USMS, Norm.CLUB)
    assert NORMS[Scale.ZERO] == (Norm.FREMO_SPUR_0,)
    assert NORMS[Scale.N] == (Norm.FREMO_N,)
    assert NORM_NAMES[Norm.FREMO_N] == "FREMO N"


def module(**change: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Övergång FREMO–MMM",
        "scale": "H0",
        "shape": {"kind": "straight", "length": 1200, "width": 500},
        "gables": [
            {"end": "A", "norm": "fremo", "tracks": [250]},
            {"end": "B", "norm": "mmm", "profile": "h0-mmm-enkelspar", "tracks": [140]},
        ],
    }
    body.update(change)
    return body


def test_a_transition_module_has_a_norm_per_gable() -> None:
    made = NewModule.model_validate(module())
    assert [g.norm for g in made.gables] == [Norm.FREMO, Norm.MMM]
    assert made.visibility == cad.Visibility.ME


def test_a_norm_must_belong_to_the_modules_scale() -> None:
    with pytest.raises(ValidationError, match="finns inte i skala 0"):
        NewModule.model_validate(module(scale="0"))


def test_a_module_has_gable_a_and_gable_b_in_order() -> None:
    gables = module()["gables"]
    with pytest.raises(ValidationError, match="gavel A och gavel B"):
        NewModule.model_validate(module(gables=[gables[1], gables[0]]))
    with pytest.raises(ValidationError):
        NewModule.model_validate(module(gables=gables[:1]))


def test_a_gables_tracks_count_from_kant_1() -> None:
    assert Gable(end=GableEnd.A, tracks=[245, 295, 345]).tracks == [245, 295, 345]
    with pytest.raises(ValidationError, match="Kant 1"):
        Gable(end=GableEnd.A, tracks=[295, 245])


def test_the_three_shapes() -> None:
    shapes = [
        {"kind": "straight", "length": 1500, "width": 700},
        {
            "kind": "curve",
            "radius": 2000,
            "angle": 30,
            "width": 500,
            "measured": {"chord": 1035, "sagitta": 68},
        },
        {"kind": "trapezoid", "length": 685, "width_a": 480, "width_b": 280},
    ]
    made = [NewModule.model_validate(module(shape=s)).shape for s in shapes]
    assert [type(s).__name__ for s in made] == ["Straight", "Curve", "Trapezoid"]
    with pytest.raises(ValidationError, match="halva snöret"):
        cad.CurveMeasure(chord=1000, sagitta=500)


def test_profiles_say_what_is_fixed_and_what_is_given_per_module() -> None:
    mmm = GableProfile.model_validate(
        {
            "id": "h0-mmm-dubbelspar",
            "name": "MMM dubbelspår",
            "kind": "norm",
            "scale": "H0",
            "norm": "mmm",
            "tracks": 2,
            "first": 140,
            "spacings": [57],
        }
    )
    assert mmm.read and mmm.uses == 0
    base = {"id": "x", "name": "X", "scale": "H0"}
    with pytest.raises(ValidationError, match="spåravstånd färre"):
        GableProfile.model_validate({**base, "kind": "general", "tracks": 2})
    with pytest.raises(ValidationError, match="ägare"):
        GableProfile.model_validate({**base, "kind": "own", "tracks": 1, "first": 100})
    with pytest.raises(ValidationError, match="normprofil"):
        GableProfile.model_validate({**base, "kind": "norm", "tracks": 1})
    with pytest.raises(ValidationError, match="Klubbens egen norm"):
        NewProfile.model_validate({"name": "Vår", "scale": "H0", "norm": "club", "tracks": [200]})


def test_the_track_graph_holds_together() -> None:
    a = GraphNode(id="n1", type=NodeType.MODULE_JOINT, at=(0, 140), gable=GableEnd.A, track=1)
    b = GraphNode(id="n2", type=NodeType.MODULE_JOINT, at=(1500, 140), gable=GableEnd.B, track=1)
    line = LineSegment(start=(0, 140), end=(1500, 140))
    piece = GraphPiece(id="s3", start="n1", end="n2", segments=[line])
    graph = TrackGraph(nodes=[a, b], pieces=[piece], issued=3)
    assert graph.geometry == "mm"
    with pytest.raises(ValidationError, match="samma id"):
        TrackGraph(nodes=[a, a.model_copy()], pieces=[])
    with pytest.raises(ValidationError, match="slutar inte i noden"):
        TrackGraph(
            nodes=[a, b.model_copy(update={"at": (1400, 140)})],
            pieces=[piece],
        )
    with pytest.raises(ValidationError, match="modulskarv"):
        GraphNode(id="n3", type=NodeType.MODULE_JOINT, at=(0, 0))
    with pytest.raises(ValidationError, match="ritar inte"):
        GraphNode(id="n3", type=NodeType.SIGNAL_POINT, at=(0, 0))
    with pytest.raises(ValidationError, match="cirkeln"):
        ArcSegment(start=(0, 0), end=(10, 0), center=(5, 100), radius=50, clockwise=True)


def test_the_track_graphs_ids_are_ids_the_station_model_takes() -> None:
    """The ids go to Studio as they are, or prefixed with the module's number in an assembly
    (CAD-10): every CAD id is a name the station model takes."""
    from contracts.station_model import TrackPiece

    for ident in ("n1", "s12", "M-001.s3"):
        node = GraphNode(id=ident, type=NodeType.JOINT, at=(0, 0))
        assert TrackPiece(id=node.id, start=node.id, end=node.id).id == ident


def test_the_drawings_change_set_is_a_list_of_operations() -> None:
    """Ritningen (#89 del b): each operation by its op, checked as it is read."""
    edit = cad.DrawingEdit.model_validate(
        {
            "base": 2,
            "operations": [
                {"op": "line", "start": [0, 140], "end": [700, 140]},
                {"op": "arc", "start": [700, 140], "radius": 800, "angle": 15},
                {
                    "op": "switch",
                    "piece": "s3",
                    "from_a": 308,
                    "radius": 705,
                    "angle": 11.4,
                    "side": "right",
                },
                {"op": "answer", "key": "open_end:n4", "answer": "stoppbock"},
                {"op": "lock", "radii": "different"},
            ],
        }
    )
    assert [type(op).__name__ for op in edit.operations] == [
        "AddLine",
        "AddArc",
        "AddSwitch",
        "AnswerCheck",
        "LockMeasures",
    ]
    with pytest.raises(ValidationError, match="tre punkter"):
        cad.AddArc.model_validate({"start": [0, 0], "radius": 500})
    with pytest.raises(ValidationError):
        cad.DrawingEdit.model_validate({"base": 1, "operations": [{"op": "rita"}]})


def test_a_versions_drawing_state_and_a_slanting_trapezoid() -> None:
    state = cad.DrawingState()
    assert state.source == cad.DrawingSource.MEASURES and state.smoothing == cad.Smoothing.NORMAL
    assert state.answers == [] and state.ids == []
    split = cad.IdChange(old=["s3"], new=["s3", "s9", "s10"], why="lock")
    assert split.new[0] == split.old[0]
    assert cad.Trapezoid(length=685, width_a=480, width_b=280).offset == 0
    graph = TrackGraph(labels=[cad.GraphLabel(id="e1", text="Lastgata", at=(10, 10))])
    with pytest.raises(ValidationError, match="samma id"):
        TrackGraph(nodes=[GraphNode(id="e1", type=NodeType.JOINT, at=(0, 0))], labels=graph.labels)
