"""The layout engine on a station from CAD's track graph, without signals (#91): each numbered
station track on a row of its own, at least 14 cells, in the numbers' order from the top (§3.2,
§3.3); a long track without a number that runs along the others is a track, not a crossover; and
a ladder stays a diagonal of crossovers. Through Studio's Från CAD, as the owner gets it.

The made-up station is CAD's kind of graph: every line cut at the module joints, with switches
and line ends and nothing else (CAD-09). Until #91 the engine refused it ("Villkoren för
kolumnerna går inte ihop"), as it refused a real station drawn in AnyRail. That station's graph
is not in the repo, since it is made from the owners' drawing: set TKL_CAD_GRAF to the path of
its StudioGraph JSON to lay it out here as well. Nothing here names a station (RS13)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from uuid import UUID

import pytest

from contracts.cad import (
    GableEnd,
    GraphNode,
    GraphPiece,
    GraphSwitch,
    LineSegment,
    Scale,
    StudioGraph,
    StudioModule,
    StudioSource,
    StudioSourceKind,
    TrackGraph,
)
from contracts.station_model import NodeType, Point, StationModel, SwitchType
from contracts.tkl import Panel, PanelAngle
from tkl.standard import lay_out
from tkl.standard.layout import SHORTENED, STATION_TRACK
from tkl.studio import fran_cad, rita

MODULE = UUID("5f0c2b1a-3d4e-4f60-8a71-b2c3d4e5f607")
WIDE = 15000.0
"""The station's length: a line that ends there ends at a free gable."""
GABLES = [1500.0 * k for k in range(1, 10)]
"""The module joints, every 1500 mm across every line."""
LINES = {
    # A line: its station track, and its nodes from the west at x,y in mm, y down. Station tracks
    # 1 and 5 run through; 2 and 4 leave them and come back; 3 runs from 2 to 4 with nothing but
    # joints on it. Beyond the station a ladder, l and u, rises from 5 to 1, and three long
    # tracks without numbers, u, v and x, come into it.
    "a": ("1", "va 0,0 a1 600,0 a2 5400,0 s2 6000,0 q 13000,0 oa 15000,0"),
    "b": ("5", "vb 0,300 b1 600,300 b2 5400,300 s1 6200,300 p 11000,300 ob 15000,300"),
    "c": ("2", "a1 600,0 c0 1100,75 c1 1600,75 c2 4900,75 a2 5400,0"),
    "d": ("4", "b1 600,300 d0 1100,225 d1 4400,225 d2 4900,225 b2 5400,300"),
    "e": ("3", "c1 1600,75 e0 2100,150 e1 3900,150 d1 4400,225"),
    "u": (None, "s1 6200,300 u0 6700,225 r1 11500,225 r2 12000,150 r3 12500,75 q 13000,0"),
    "v": (None, "s2 6000,0 v0 6500,150 s3 7000,150 r2 12000,150"),
    "x": (None, "s3 7000,150 x0 7500,75 r3 12500,75"),
    "l": (None, "p 11000,300 r1 11500,225"),
}
SWITCHES = {
    # node: the nodes its trunk, straight and diverging leg lead to
    "a1": ("va", "a2", "c0"),
    "a2": ("s2", "a1", "c2"),
    "b1": ("vb", "b2", "d0"),
    "b2": ("s1", "b1", "d2"),
    "c1": ("c0", "c2", "e0"),
    "d1": ("d2", "d0", "e1"),
    "s1": ("b2", "p", "u0"),
    "s2": ("a2", "q", "v0"),
    "s3": ("v0", "r2", "x0"),
    "p": ("s1", "ob", "r1"),
    "r1": ("r2", "u0", "p"),
    "r2": ("r3", "r1", "s3"),
    "r3": ("q", "r2", "x0"),
    "q": ("oa", "s2", "r3"),
}
LADDER = ["p", "r1", "r2", "r3", "q"]
LONG = ["x", "v", "u"]
"""The long tracks without numbers, from the top as drawn."""

TRUNKS = {
    # A second made-up station. A ladder rises from 5 to 2 with four switches: k1 and k2 at its
    # ends, where only a connector leaves (x1 and x2), and g1 and g2 between, where station
    # tracks 4 and 3 leave westwards. g2 and k2 lie trunk to trunk, a double switch as the
    # drawing has it. Station track 1 leaves 2 and ends at a buffer stop, with nothing but
    # joints on the way.
    "e": ("1", "t3 3000,0 e0 3500,-75 e1 4000,-150 es 7000,-150"),
    "a": ("2", "va 0,0 t3 3000,0 s2 11000,0 oa 15000,0"),
    "d": ("3", "vd 0,75 d0 7500,75 g2 8000,120"),
    "c": ("4", "vc 0,150 c0 6000,150 g1 6500,180"),
    "b": ("5", "vb 0,300 s1 3000,300 t1 6500,300 t2 12000,300 ob 15000,300"),
    "l": (None, "s1 3000,300 k1 5000,225 g1 6500,180 g2 8000,120 k2 8300,110 s2 11000,0"),
    "x1": (None, "k1 5000,225 t1 6500,300"),
    "x2": (None, "k2 8300,110 t2 12000,300"),
}
TRUNK_SWITCHES = {
    "s1": ("vb", "t1", "k1"),
    "t1": ("t2", "s1", "k1"),
    "t2": ("ob", "t1", "k2"),
    "t3": ("va", "s2", "e0"),
    "s2": ("oa", "t3", "k2"),
    "k1": ("s1", "g1", "t1"),
    "g1": ("g2", "k1", "c0"),
    "g2": ("k2", "g1", "d0"),
    "k2": ("g2", "s2", "t2"),
}


def _id(name: str) -> str:
    return f"{MODULE}:{name}"


def studio(
    numbered: bool = True,
    lines: dict[str, tuple[str | None, str]] | None = None,
    turnouts: dict[str, tuple[str, str, str]] | None = None,
) -> StudioGraph:
    """CAD's track graph of a made-up station, the first unless others are given: each line
    cut where it crosses a module joint, and a line's end at a free gable a module joint."""
    lines = LINES if lines is None else lines
    turnouts = SWITCHES if turnouts is None else turnouts
    at: dict[str, Point] = {}
    joints: set[str] = set()
    pieces: list[GraphPiece] = []
    toward: dict[tuple[str, str], str] = {}
    """A node and the node a line leads to from it: the piece that leaves it that way."""
    for line, (number, spec) in lines.items():
        words = spec.split()
        points: list[tuple[str, Point]] = [
            (name, (float(x), float(y)))
            for name, (x, y) in zip(words[::2], (w.split(",") for w in words[1::2]), strict=True)
        ]
        for (a, p), (b, q) in pairwise(points):
            cut = [(a, p)]
            for x in GABLES:
                if p[0] < x < q[0]:
                    joint = f"{line}{x:.0f}"
                    joints.add(joint)
                    cut.append((joint, (x, p[1] + (q[1] - p[1]) * (x - p[0]) / (q[0] - p[0]))))
            cut.append((b, q))
            for (m, mp), (n, nq) in pairwise(cut):
                piece = _id(f"{line}-{len(pieces)}")
                at[m], at[n] = mp, nq
                toward.setdefault((a, b), piece)
                toward[(b, a)] = piece
                pieces.append(
                    GraphPiece(
                        id=piece,
                        start=_id(m),
                        end=_id(n),
                        segments=[LineSegment(start=mp, end=nq)],
                        track=number if numbered else None,
                    )
                )
    nodes = []
    for name, point in at.items():
        if name in turnouts:
            kind = NodeType.SWITCH
        elif name in joints or point[0] in (0.0, WIDE):
            kind = NodeType.MODULE_JOINT
        else:
            kind = NodeType.JOINT
        gable = GableEnd.A if kind == NodeType.MODULE_JOINT else None
        nodes.append(
            GraphNode(id=_id(name), type=kind, at=point, gable=gable, track=1 if gable else None)
        )
    switches = [
        GraphSwitch(
            id=_id(f"w{node}"),
            node=_id(node),
            type=SwitchType.ORDINARY,
            trunk=toward[(node, trunk)],
            straight=toward[(node, straight)],
            diverging=toward[(node, diverging)],
        )
        for node, (trunk, straight, diverging) in turnouts.items()
    ]
    source = StudioSource(
        kind=StudioSourceKind.ASSEMBLY,
        id=UUID("6a1d2c3b-4e5f-4071-8b92-c3d4e5f60718"),
        name="Provanläggning",
        scale=Scale.H0,
        owner="Provkonto A",
        revision=1,
        modules=[StudioModule(id=MODULE, number="M-001", name="Provmodul", version=1)],
        ready=True,
        changed_at=datetime(2026, 11, 21, 12, 0, tzinfo=UTC),
    )
    graph = TrackGraph(nodes=nodes, pieces=pieces, switches=switches)
    return StudioGraph(source=source, graph=graph)


def proposal(graph: StudioGraph) -> StationModel:
    """Från CAD's proposal, laid out as Studio does it for Rita."""
    model = fran_cad.proposal(graph, "prov", "Prov")
    assert rita.drawing_of(model).proposal
    return model


def station_tracks(model: StationModel, panel: Panel) -> list[tuple[str, float, float]]:
    """Each station track: the row it lies on, and how many cells long it is there."""
    lines = {line.piece: line.cells for line in panel.lines}
    found = []
    for track in model.station_tracks:
        flat = [
            (a, b)
            for piece in track.pieces
            for a, b in pairwise(lines[piece])
            if abs(a[1] - b[1]) < 1e-6
        ]
        ys = [a[1] for a, _ in flat]
        row = max(set(ys), key=ys.count)
        xs = [x for a, b in flat if a[1] == row for x in (a[0], b[0])]
        found.append((track.id, row, max(xs) - min(xs)))
    return found


def assert_station_tracks(model: StationModel) -> None:
    """One row per station track, in the numbers' order from the top, and at least a station
    track long there: 14 cells, or 8 where the engine shortened them (§3.2, §3.3, §3.6)."""
    for panel in (lay_out(model), *(lay_out(model, angle, False) for angle in PanelAngle)):
        found = station_tracks(model, panel)
        assert len({row for _, row, _ in found}) == len(found), found
        assert [t for t, _, _ in sorted(found, key=lambda f: f[1])] == sorted(
            (t for t, _, _ in found), key=int
        )
        least = SHORTENED if panel.shortened else STATION_TRACK
        assert all(cells >= least - 1e-6 for _, _, cells in found), (panel.angle, found)


@pytest.mark.parametrize("numbered", [True, False], ids=["med spårnummer", "utan spårnummer"])
def test_a_station_from_cad_without_signals_lays_out_by_its_tracks(numbered: bool) -> None:
    model = proposal(studio(numbered))
    assert not model.signals and not any(n.type == NodeType.STOP_POINT for n in model.nodes)
    assert len(model.station_tracks) == (5 if numbered else 0)
    assert_station_tracks(model)
    panel = lay_out(model)
    cells = {node.id: node.cell for node in panel.nodes}
    lines = {line.piece: line.cells for line in panel.lines}
    # The ladder is a diagonal of crossovers: each switch a row higher, further east.
    ladder = [cells[_id(n)] for n in LADDER]
    assert all(a[0] < b[0] and a[1] > b[1] for a, b in pairwise(ladder)), ladder
    # The long tracks without numbers lie along rows of their own, between 1 and 5 as drawn:
    # their pieces from the module joint at 9 m on are level.
    middle = [
        lines[piece.id]
        for line in LONG
        for piece in model.pieces
        if piece.start == _id(f"{line}9000")
    ]
    assert all(len({c[1] for c in way}) == 1 for way in middle), middle
    rows = [cells[_id("va")][1], *(way[0][1] for way in middle), cells[_id("vb")][1]]
    assert rows == sorted(set(rows)), rows


def test_a_ladder_with_two_switches_trunk_to_trunk_rises_all_the_way() -> None:
    """A ladder keeps the switches where only a connector leaves on its own row, at one end of
    the diagonal: k1. k2, at the other end past g1 and g2, stands on g2's row, trunk to trunk
    with it, so that the diagonal rises all the way as drawn and does not come back to k1's row.
    Until the change it went down two rows from g2 to k2 and up again."""
    model = proposal(studio(lines=TRUNKS, turnouts=TRUNK_SWITCHES))
    for panel in (lay_out(model), *(lay_out(model, angle, False) for angle in PanelAngle)):
        cells = {node.id: node.cell for node in panel.nodes}
        k1, g1, g2, k2, s2 = (cells[_id(n)] for n in ("k1", "g1", "g2", "k2", "s2"))
        assert k1[1] > g1[1] > g2[1] > s2[1], (panel.angle, k1, g1, g2, s2)
        assert k2[1] == g2[1] and k2[0] > g2[0], (panel.angle, g2, k2)


def test_a_numbered_stub_to_a_buffer_stop_is_a_station_track_on_its_row() -> None:
    """Station track 1 leaves 2 and ends at a buffer stop with only joints on the way: it goes
    off 2 at once, and lies at least 14 cells on its row up to the buffer stop (§3.2, §3.3).
    Until the change it ran on the slant all the way, with a cell on its row."""
    model = proposal(studio(lines=TRUNKS, turnouts=TRUNK_SWITCHES))
    assert_station_tracks(model)
    stop = next(n.id for n in model.nodes if n.type == NodeType.BUFFER_STOP)
    for panel in (lay_out(model), *(lay_out(model, angle, False) for angle in PanelAngle)):
        found = {t: (row, cells) for t, row, cells in station_tracks(model, panel)}
        row, cells = found["1"]
        least = SHORTENED if panel.shortened else STATION_TRACK
        assert cells >= least - 1e-6, (panel.angle, found)
        assert {node.id: node.cell for node in panel.nodes}[stop][1] == row


def test_the_station_from_its_owners_drawing_lays_out() -> None:
    """Local only: a real station's graph from CAD, in the file TKL_CAD_GRAF names."""
    given = os.environ.get("TKL_CAD_GRAF", "").strip()
    if not given:
        pytest.skip("TKL_CAD_GRAF saknas: ingen stations spårgraf ur CAD att lägga ut.")
    model = proposal(StudioGraph.model_validate_json(Path(given).read_text(encoding="utf-8")))
    assert model.station_tracks and not model.signals
    assert_station_tracks(model)
