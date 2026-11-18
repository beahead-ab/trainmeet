"""Small made-up stations for the engine's tests, written in a few lines each.

    build("a:V-W b:W-1 c:1-X", switches=[...], signals=[...])

Every piece is 100 mm straight unless `lengths` says otherwise. A node takes its type
from what stands there: a switch, a signal, a line exit, the turntable; else a buffer stop at
a track's end and a joint between two pieces.
"""

from __future__ import annotations

from typing import Any, Literal

from contracts.station_model import (
    LineExit,
    Node,
    NodeType,
    Position,
    Signal,
    SignalType,
    StationModel,
    StationTrack,
    Switch,
    SwitchType,
    TrackCircuit,
    TrackPiece,
)

PLUS, MINUS = Position.PLUS, Position.MINUS


def switch(number: str, trunk: str, straight: str, diverging: str, **more: Any) -> Switch:
    return Switch(
        number=number,
        type=more.pop("type", SwitchType.ORDINARY),
        node=more.pop("node", number),
        trunk=trunk,
        straight=straight,
        diverging=diverging,
        **more,
    )


def signal(name: str, kind: SignalType, node: str, approach: str, **more: Any) -> Signal:
    return Signal(name=name, type=kind, node=node, approach=approach, **more)


def build(
    spec: str,
    *,
    switches: list[Switch] | None = None,
    signals: list[Signal] | None = None,
    exits: dict[str, str | None] | None = None,
    types: dict[str, NodeType] | None = None,
    lengths: dict[str, float] | None = None,
    level: Literal[1, 2, 3] = 2,
    **more: Any,
) -> StationModel:
    """A model from 'piece:from-to' words; exits maps a line exit's node to its neighbour."""
    pieces = []
    for word in spec.split():
        piece, ends = word.split(":")
        start, end = ends.split("-")
        long = (lengths or {}).get(piece, 100.0)
        geometry = [(0.0, 0.0), (long, 0.0)]
        pieces.append(TrackPiece(id=piece, start=start, end=end, geometry=geometry))
    switches = switches or []
    signals = signals or []
    exits = exits or {}
    types = dict(types or {})
    touching: dict[str, int] = {}
    for p in pieces:
        for node in (p.start, p.end):
            touching[node] = touching.get(node, 0) + 1
    switch_nodes = {s.node: s for s in switches}
    signal_nodes = {s.node for s in signals}
    nodes = []
    for node, count in touching.items():
        if node in types:
            kind = types[node]
        elif node in switch_nodes:
            crossing = switch_nodes[node].type == SwitchType.CROSSING
            kind = NodeType.CROSSING if crossing else NodeType.SWITCH
        elif node in exits:
            kind = NodeType.LINE_EXIT
        elif count == 1:
            kind = NodeType.BUFFER_STOP
        elif node in signal_nodes:
            kind = NodeType.SIGNAL_POINT
        else:
            kind = NodeType.JOINT
        nodes.append(Node(id=node, type=kind))
    line_exits = [
        LineExit(
            id=node,
            node=node,
            neighbour=neighbour,
            signals=[s.name for s in signals if s.node in more.get("boundary", {}).get(node, [])],
        )
        for node, neighbour in exits.items()
    ]
    more.pop("boundary", None)
    return StationModel(
        station_id="provby",
        name="Provby",
        level=level,
        nodes=nodes,
        pieces=pieces,
        switches=switches,
        signals=signals,
        line_exits=more.pop("line_exits", line_exits),
        **more,
    )


def provby(**more: Any) -> StationModel:
    """Two station tracks between two single lines, with a dwarf signal on track 2.

    V -a- W -b- 1 -c- X1 -e- Y1 -g- 2 -i- Z -j- O
                 \\d- X2 -f1- M -f2- Y2 -h-/
    """
    hsi, hdvsi, dvsi = SignalType.HSI, SignalType.HDVSI, SignalType.DVSI
    spec = "a:V-W b:W-1 c:1-X1 e:X1-Y1 g:Y1-2 i:2-Z j:Z-O d:1-X2 f1:X2-M f2:M-Y2 h:Y2-2"
    settings: dict[str, Any] = {
        "switches": [switch("1", "b", "c", "d"), switch("2", "i", "g", "h")],
        "signals": [
            signal("In", hsi, "W", "a", lamps=4),
            signal("Ut", hsi, "W", "b", lamps=2),
            signal("11", hsi, "X1", "e"),
            signal("12", hsi, "Y1", "e"),
            signal("21", hdvsi, "X2", "f1"),
            signal("22", hdvsi, "Y2", "f2"),
            signal("D", dvsi, "M", "f1"),
            signal("Ut2", hsi, "Z", "i"),
            signal("In2", hsi, "Z", "j"),
        ],
        "exits": {"V": "Västby", "O": "Östby"},
        "boundary": {"V": ["W"], "O": ["Z"]},
        "track_circuits": [
            TrackCircuit(name="Infart V", pieces=["a"]),
            TrackCircuit(name="Vx1", pieces=["b", "c", "d"]),
            TrackCircuit(name="Spår 1", pieces=["e"]),
            TrackCircuit(name="Spår 2", pieces=["f1", "f2"]),
            TrackCircuit(name="Vx2", pieces=["g", "h", "i"]),
            TrackCircuit(name="Infart O", pieces=["j"]),
        ],
        "station_tracks": [
            StationTrack(id="1", label="Spår 1", pieces=["e"]),
            StationTrack(id="2", label="Spår 2", pieces=["f1", "f2"]),
        ],
    }
    settings.update(more)
    spec = settings.pop("spec", spec)
    return build(spec, **settings)


def drawn(
    nodes: dict[str, tuple[float, float]],
    spec: str,
    *,
    switches: list[Switch] | None = None,
    signals: list[Signal] | None = None,
    exits: list[str] | None = None,
    tracks: dict[str, list[str]] | None = None,
    **more: Any,
) -> StationModel:
    """A model with a drawing: each node at its point in millimetres, each piece straight
    between its nodes. The engine reads the drawing order from it."""
    pieces = []
    for word in spec.split():
        piece, ends = word.split(":")
        start, end = ends.split("-")
        pieces.append(
            TrackPiece(id=piece, start=start, end=end, geometry=[nodes[start], nodes[end]])
        )
    model = build(
        " ".join(f"{p.id}:{p.start}-{p.end}" for p in pieces),
        switches=switches,
        signals=signals,
        exits=dict.fromkeys(exits or [], "Grannby"),
        station_tracks=[
            StationTrack(id=track, label=f"Spår {track}", pieces=found)
            for track, found in (tracks or {}).items()
        ],
        **more,
    )
    return model.model_copy(update={"pieces": pieces})


def ekby(**more: Any) -> StationModel:
    """Two station tracks between two lines, a siding below track 2, and the drawing.

    W ─ Vs ─ A ════════ track 1 ════════ B ─ Os ─ O
              \\                        /
               C ──── track 2 ──── D
                \\
                 F ── Stopp
    """
    hsi, dvsi = SignalType.HSI, SignalType.DVSI
    nodes = {
        "W": (0.0, 100.0),
        "Vs": (300.0, 100.0),
        "A": (600.0, 100.0),
        "B": (2400.0, 100.0),
        "Os": (2700.0, 100.0),
        "O": (3000.0, 100.0),
        "C": (800.0, 160.0),
        "C1": (1100.0, 160.0),
        "D1": (1900.0, 160.0),
        "D": (2200.0, 160.0),
        "F": (1000.0, 220.0),
        "Stopp": (1500.0, 220.0),
        "T1": (900.0, 100.0),
        "T2": (2100.0, 100.0),
    }
    spec = (
        "a:W-Vs b:Vs-A c:A-T1 d:T1-T2 e:T2-B f:B-Os g:Os-O "
        "h:A-C i:C-C1 j:C1-D1 k:D1-D l:D-B m:C-F n:F-Stopp"
    )
    settings: dict[str, Any] = {
        "switches": [
            switch("1", "b", "c", "h", node="A"),
            switch("2", "h", "i", "m", node="C"),
            switch("4", "f", "e", "l", node="B"),
        ],
        "signals": [
            signal("In V", hsi, "Vs", "a"),
            signal("Ut V", hsi, "Vs", "b"),
            signal("11", hsi, "T1", "c"),
            signal("12", hsi, "T2", "e"),
            signal("21", hsi, "C1", "i"),
            signal("22", hsi, "D1", "k"),
            signal("D", dvsi, "F", "m"),
            signal("In O", hsi, "Os", "g"),
            signal("Ut O", hsi, "Os", "f"),
        ],
        "exits": ["W", "O"],
        "tracks": {"1": ["d"], "2": ["j"]},
        "boundary": {"W": ["Vs"], "O": ["Os"]},
    }
    settings.update(more)
    return drawn(nodes, spec, **settings)
