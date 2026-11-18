"""A small station drawn in Rita, written out as the web app saves it (#85): the station model
with its panel plan, every node in a cell and every piece a track of its own on the grid.

    A —A1— 1 —1V—|—1Ö— 2 —B1— B          track 1 between switches 1 and 2, a boundary on it
            \\              /
             2V— 3 —2Ö—--               track 2, from switch 1 through switch 3 to switch 2
                  \\
                   —D3— Stoppbock 1     a siding with a dwarf signal

Nothing here names a real station (RS13).
"""

from __future__ import annotations

from typing import Any

from contracts.station_model import (
    Cell,
    Lever,
    LineExit,
    Node,
    NodeType,
    Origin,
    PanelGrid,
    PanelPiece,
    PanelPlan,
    PanelTrack,
    Position,
    Signal,
    SignalType,
    Source,
    StationModel,
    StationTrack,
    Switch,
    SwitchType,
    TrackPiece,
)
from contracts.tkl import TklDrawing

PLUS, MINUS = Position.PLUS, Position.MINUS
DRAWN = Origin(source=Source.DRAWN, confirmed=True)

NODES: dict[str, tuple[NodeType, Cell]] = {
    "A": (NodeType.LINE_EXIT, (2, 4)),
    "a1": (NodeType.SIGNAL_POINT, (5, 4)),
    "S1": (NodeType.SWITCH, (8, 4)),
    "v1": (NodeType.SIGNAL_POINT, (10, 4)),
    "bb": (NodeType.BLOCK_BOUNDARY, (14, 4)),
    "o1": (NodeType.SIGNAL_POINT, (20, 4)),
    "S2": (NodeType.SWITCH, (24, 4)),
    "b1": (NodeType.SIGNAL_POINT, (27, 4)),
    "B": (NodeType.LINE_EXIT, (30, 4)),
    "v2": (NodeType.SIGNAL_POINT, (12, 7)),
    "S3": (NodeType.SWITCH, (15, 7)),
    "o2": (NodeType.SIGNAL_POINT, (19, 7)),
    "d3": (NodeType.SIGNAL_POINT, (20, 10)),
    "Stoppbock 1": (NodeType.BUFFER_STOP, (23, 10)),
}
PIECES: list[tuple[str, str, str, list[Cell]]] = [
    ("p1", "A", "a1", []),
    ("p2", "a1", "S1", []),
    ("p3", "S1", "v1", []),
    ("p4", "v1", "bb", []),
    ("p5", "bb", "o1", []),
    ("p6", "o1", "S2", []),
    ("p7", "S2", "b1", []),
    ("p8", "b1", "B", []),
    ("q1", "S1", "v2", [(11, 7)]),
    ("q2", "v2", "S3", []),
    ("q3", "S3", "o2", []),
    ("q4", "o2", "S2", [(21, 7)]),
    ("r1", "S3", "d3", [(18, 10)]),
    ("r2", "d3", "Stoppbock 1", []),
]
TRACKS = {"1": ["p3", "p4", "p5", "p6"], "2": ["q1", "q2", "q3", "q4"]}


def switch(number: str, node: str, trunk: str, straight: str, diverging: str) -> Switch:
    return Switch(
        number=number,
        type=SwitchType.ORDINARY,
        node=node,
        trunk=trunk,
        straight=straight,
        diverging=diverging,
    )


def drawing(**more: Any) -> TklDrawing:
    """The drawing as the web app sends it; `more` replaces parts of the model."""
    on_track = {p: t for t, pieces in TRACKS.items() for p in pieces}
    model = StationModel(
        station_id="ritby",
        name="Ritby",
        level=1,
        origin=DRAWN,
        nodes=[Node(id=n, type=t) for n, (t, _) in NODES.items()],
        pieces=[TrackPiece(id=p, start=a, end=b, track=on_track.get(p)) for p, a, b, _ in PIECES],
        switches=[
            switch("1", "S1", "p2", "p3", "q1"),
            switch("2", "S2", "p7", "p6", "q4"),
            switch("3", "S3", "q2", "q3", "r1"),
        ],
        signals=[
            Signal(name="A1", type=SignalType.HSI, lamps=2, node="a1", approach="p1"),
            Signal(name="B1", type=SignalType.HSI, lamps=2, node="b1", approach="p8"),
            Signal(name="1V", type=SignalType.HSI, lamps=2, node="v1", approach="p4"),
            Signal(name="1Ö", type=SignalType.HSI, lamps=2, node="o1", approach="p5"),
            Signal(name="2V", type=SignalType.HSI, lamps=2, node="v2", approach="q2"),
            Signal(name="2Ö", type=SignalType.HSI, lamps=2, node="o2", approach="q3"),
            Signal(name="D3", type=SignalType.DVSI, node="d3", approach="r2"),
        ],
        station_tracks=[
            StationTrack(id=t, label=f"Spår {t}", pieces=pieces) for t, pieces in TRACKS.items()
        ],
        line_exits=[LineExit(id="A", node="A"), LineExit(id="B", node="B", neighbour="Östby")],
        panel=PanelPlan(
            basis="Ritad i Studio.",
            grid=PanelGrid(dx=24, dy=24),
            nodes={n: c for n, (_, c) in NODES.items()},
            tracks=[
                PanelTrack(start=a, end=b, pieces=[PanelPiece(id=p)], via=via)
                for p, a, b, via in PIECES
            ],
        ),
    )
    return TklDrawing(model=model.model_copy(update=more))


def three_on_one_lever() -> list[Lever]:
    """Switches 1, 2 and 3 on one lever, with 2 lying reversed (STUDIO-02, STUDIO-34)."""
    plus = {"1": PLUS, "2": MINUS, "3": PLUS}
    minus = {"1": MINUS, "2": PLUS, "3": MINUS}
    return [Lever(id="1/2/3", plus=plus, minus=minus)]


def reversed_and_dragging() -> list[Lever]:
    """1 and 2 on one lever with 2 reversed; 3 to diverging drags 1 to diverging (TKL104)."""
    return [
        Lever(id="1/2", plus={"1": PLUS, "2": MINUS}, minus={"1": MINUS, "2": PLUS}),
        Lever(id="3", plus={"3": PLUS}, minus={"3": MINUS, "1": MINUS}),
    ]
