"""Ladda upp ritning i Studio (#89 del c4, STUDIO-01, STUDIO-03, TKL23, TKL27, TKL81): the drawing
read by TrainMeet CAD (contracts.cad.DrawingRead) becomes a proposal for the station model, by
the standard interlocking. CAD's image chain only reads pixels; Studio knows the rules (bildkedjan,
the border between CAD and Studio).

- The tracks are the read's pieces, with their shape in the drawing's coordinates, so that the
  engine's rows follow the drawing (STD-10). A piece is cut where a track-circuit boundary or a
  signal stands on it: the boundary is a block_boundary node, a signal a signal_point, and a
  signal at a boundary stands at that boundary.
- A switch is the station model's ordinary switch, with its trunk, straight and diverging legs as
  the read gives them, and its number from the drawing (the number is the LocoNet address by
  default, STUDIO-19); a crossing gets its two ways through. A switch without a number gets the
  next free one.
- A signal gets its type from the catalogue (Hsi with its lamps, Hdvsi, Dvsi …), its name and its
  address as read, and the piece trains come on toward it: west of it when it applies to trains
  going east.
- A track's end is a line exit or a buffer stop as read; the line exits are named Väst 1, Öst 1 …
  from the top. A track's name in the drawing ("Spår 4", IV) makes a station track.
- Everything carries the origin assumed, not confirmed, with the note READ: yellow in Rita until
  the owner confirms it, one by one or all at once, and Använd ritningen is refused until then
  (rita.unconfirmed). The station is never made without the owner's yes.

The engine lays out the panel (rita.drawing_of): the proposal's grid is the engine's, which the
owner may redraw (TKL81). Pure Python without I/O, using only the contracts and the engine. No
code here names a station (RS13).
"""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from collections.abc import Callable
from typing import Final

from contracts.cad import DrawingRead, GraphPiece, SymbolKind, TrackGraph
from contracts.station_model import (
    Address,
    LineExit,
    Node,
    NodeType,
    Origin,
    Point,
    Signal,
    SignalType,
    Source,
    StationModel,
    StationTrack,
    Switch,
    SwitchPath,
    SwitchType,
    TrackPiece,
)
from contracts.tkl import TklDrawing
from tkl.studio.rita import READ, drawing_of

UNIT_SHARE: Final = 0.012
"""The drawing's unit: this share of its extent, as CAD reads it."""
SAME_PLACE: Final = 0.6
"""A signal this many units from a boundary on its piece stands at the boundary."""


def _origin(ref: str | None = None) -> Origin:
    return Origin(source=Source.ASSUMED, confirmed=False, ref=ref[:80] if ref else None, note=READ)


def _points(piece: GraphPiece) -> list[Point]:
    """A piece's shape as points: its lines' ends, and its arcs sampled."""
    found: list[Point] = [piece.segments[0].start]
    for segment in piece.segments:
        if segment.kind == "arc":
            cx, cy = segment.center
            a0 = math.atan2(segment.start[1] - cy, segment.start[0] - cx)
            a1 = math.atan2(segment.end[1] - cy, segment.end[0] - cx)
            sweep = a1 - a0
            if segment.clockwise and sweep < 0:
                sweep += 2 * math.pi
            if not segment.clockwise and sweep > 0:
                sweep -= 2 * math.pi
            steps = max(2, int(abs(sweep) / math.radians(10)))
            for k in range(1, steps):
                t = a0 + sweep * k / steps
                found.append((cx + segment.radius * math.cos(t), cy + segment.radius * math.sin(t)))
        found.append(segment.end)
    return found


def _along(points: list[Point], at: Point) -> tuple[float, Point]:
    """How far along the polyline the point's nearest point is, and that point."""
    best = (math.inf, 0.0, points[0])
    walked = 0.0
    for a, b in itertools.pairwise(points):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        t = (
            0.0
            if length == 0
            else max(0.0, min(1.0, ((at[0] - a[0]) * dx + (at[1] - a[1]) * dy) / length**2))
        )
        q = (a[0] + t * dx, a[1] + t * dy)
        d = math.dist(at, q)
        if d < best[0]:
            best = (d, walked + t * length, q)
        walked += length
    return best[1], best[2]


def _cut(points: list[Point], at: list[float]) -> list[list[Point]]:
    """The polyline cut at the given distances along it, in order."""
    parts: list[list[Point]] = []
    current: list[Point] = [points[0]]
    walked = 0.0
    cuts = list(at)
    for a, b in itertools.pairwise(points):
        length = math.dist(a, b)
        while cuts and cuts[0] <= walked + length:
            t = (cuts.pop(0) - walked) / length if length else 0.0
            q = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            current.append(q)
            parts.append(current)
            current = [q]
        current.append(b)
        walked += length
    parts.append(current)
    return parts


def _round(p: Point) -> Point:
    return (round(p[0], 2), round(p[1], 2))


def proposal(read: DrawingRead, station_id: str, name: str, file: str) -> StationModel:
    """The station model Studio proposes from the drawing read, everything assumed."""
    graph = read.graph
    xs = [n.at[0] for n in graph.nodes] or [0.0]
    ys = [n.at[1] for n in graph.nodes] or [0.0]
    unit = UNIT_SHARE * max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    nodes: dict[str, Node] = {}
    kinds = {
        NodeType.SWITCH: NodeType.SWITCH,
        NodeType.CROSSING: NodeType.CROSSING,
        NodeType.LINE_EXIT: NodeType.LINE_EXIT,
        NodeType.BUFFER_STOP: NodeType.BUFFER_STOP,
    }
    # A buffer stop is named as Rita names one, Stoppbock 1 … from the west.
    stops = [n.id for n in graph.nodes if n.type == NodeType.BUFFER_STOP]
    rename = {old: f"Stoppbock {k + 1}" for k, old in enumerate(stops)}
    for n in graph.nodes:
        nodes[n.id] = Node(id=rename.get(n.id, n.id), type=kinds.get(n.type, NodeType.JOINT))
    # Where each piece is cut: its boundaries, and its signals.
    cuts: dict[str, list[tuple[float, str, str | None]]] = defaultdict(list)
    for boundary in read.boundaries:
        if boundary.piece is not None:
            place = _place(graph, boundary.piece, boundary.at)
            cuts[boundary.piece].append((place, "boundary", boundary.id))
    signals = [s for s in graph.symbols if s.kind == SymbolKind.SIGNAL and s.piece is not None]
    for symbol in signals:
        assert symbol.piece is not None
        cuts[symbol.piece].append((_place(graph, symbol.piece, symbol.at), "signal", symbol.id))
    pieces: list[TrackPiece] = []
    ends: dict[str, tuple[str, str]] = {}
    """A read piece -> its first and last part in the model, for the switches' legs."""
    signal_node: dict[str, tuple[str, str, str]] = {}
    """A signal -> its node, and the parts before and after it along the piece."""
    for piece in graph.pieces:
        points = _points(piece)
        length = sum(math.dist(a, b) for a, b in itertools.pairwise(points))
        places: list[tuple[float, list[tuple[str, str | None]]]] = []
        for distance, kind, ref in sorted(cuts.get(piece.id, []), key=lambda c: c[0]):
            if distance <= 0.2 * unit or distance >= length - 0.2 * unit:
                continue
            if places and distance - places[-1][0] <= SAME_PLACE * unit:
                places[-1][1].append((kind, ref))
                continue
            places.append((distance, [(kind, ref)]))
        parts = _cut(points, [d for d, _ in places])
        names = (
            [piece.id] if len(parts) == 1 else [f"{piece.id}.{k + 1}" for k in range(len(parts))]
        )
        node_ids = [rename.get(piece.start, piece.start)]
        for k, (_, what) in enumerate(places):
            node = f"{piece.id}-{k + 1}"
            has_signal = any(kind == "signal" for kind, _ in what)
            nodes[node] = Node(
                id=node, type=NodeType.SIGNAL_POINT if has_signal else NodeType.BLOCK_BOUNDARY
            )
            node_ids.append(node)
            for kind, ref in what:
                if kind == "signal" and ref is not None:
                    signal_node[ref] = (node, names[k], names[k + 1])
        node_ids.append(rename.get(piece.end, piece.end))
        for k, part in enumerate(parts):
            pieces.append(
                TrackPiece(
                    id=names[k],
                    start=node_ids[k],
                    end=node_ids[k + 1],
                    track=piece.track,
                    geometry=[_round(p) for p in part],
                    origin=_origin(f"Spår {piece.track}" if piece.track else None),
                )
            )
        ends[piece.id] = (names[0], names[-1])
    by_id = {p.id: p for p in graph.pieces}

    def leg(piece: str | None, node: str) -> str | None:
        if piece is None or piece not in by_id:
            return None
        first, last = ends[piece]
        return first if by_id[piece].start == node else last

    switches: list[Switch] = []
    taken = {s.number for s in graph.switches if s.number}
    free = (str(k) for k in range(1, 10_000) if str(k) not in taken)
    for s in graph.switches:
        number = s.number or next(free)
        if s.type == SwitchType.CROSSING:
            switches.append(
                Switch(
                    number=number,
                    type=SwitchType.CROSSING,
                    node=s.node,
                    paths=_ways(graph, s.node, leg),
                    origin=_origin(s.number),
                )
            )
            continue
        switches.append(
            Switch(
                number=number,
                type=SwitchType.ORDINARY,
                node=s.node,
                trunk=leg(s.trunk, s.node),
                straight=leg(s.straight, s.node),
                diverging=leg(s.diverging, s.node),
                origin=_origin(s.number),
            )
        )
    labels = {label.id: label.text for label in graph.labels}
    model_signals: list[Signal] = []
    names_taken = {s.name for s in signals if s.name}
    spare = (f"S{k}" for k in range(1, 10_000) if f"S{k}" not in names_taken)
    used_names: set[str] = set()
    for symbol in signals:
        if symbol.id not in signal_node or symbol.signal is None:
            continue
        node, before, after = signal_node[symbol.id]
        geometry = {p.id: p.geometry for p in pieces}
        # Trains going east come from the west: the part whose far end lies further west.
        west = before if geometry[before][0][0] <= geometry[after][-1][0] else after
        east = after if west == before else before
        approach = west if symbol.facing != "west" else east
        name = symbol.name if symbol.name and symbol.name not in used_names else next(spare)
        used_names.add(name)
        model_signals.append(
            Signal(
                name=name,
                type=symbol.signal,
                lamps=symbol.lamps if symbol.signal == SignalType.HSI else None,
                node=node,
                approach=approach,
                address=Address(
                    number=symbol.address, origin=Origin(source=Source.SIGNAL_PLAN, confirmed=False)
                )
                if symbol.address is not None
                else None,
                origin=_origin(labels.get(symbol.label or "") or symbol.shape),
            )
        )
    exits: list[LineExit] = []
    centre = (min(xs) + max(xs)) / 2
    outer = sorted(
        (n for n in graph.nodes if n.type == NodeType.LINE_EXIT),
        key=lambda n: (n.at[0] >= centre, n.at[1]),
    )
    count = {"Väst": 0, "Öst": 0}
    for n in outer:
        side = "Väst" if n.at[0] < centre else "Öst"
        count[side] += 1
        exits.append(LineExit(id=f"{side} {count[side]}", node=n.id, origin=_origin()))
    tracks: dict[str, list[str]] = defaultdict(list)
    for p in pieces:
        if p.track:
            tracks[p.track].append(p.id)
    station_tracks = [
        StationTrack(id=track, label=f"Spår {track}", pieces=ids) for track, ids in tracks.items()
    ]
    return StationModel(
        station_id=station_id,
        name=name,
        level=2 if model_signals else 1,
        origin=_origin(),
        basis=[f"Ritningen {file[:200]}, läst av TrainMeet CAD: ett förslag att bekräfta."],
        nodes=list(nodes.values()),
        pieces=pieces,
        switches=switches,
        signals=model_signals,
        station_tracks=station_tracks,
        line_exits=exits,
    )


def _place(graph: TrackGraph, piece_id: str, at: Point) -> float:
    piece = next(p for p in graph.pieces if p.id == piece_id)
    return _along(_points(piece), at)[0]


def _ways(
    graph: TrackGraph, node: str, leg: Callable[[str | None, str], str | None]
) -> list[SwitchPath]:
    """A crossing's two ways through: each piece with the one most nearly opposite it."""
    at = next(n.at for n in graph.nodes if n.id == node)
    legs: list[tuple[str, tuple[float, float]]] = []
    for p in graph.pieces:
        if node not in (p.start, p.end):
            continue
        points = _points(p)
        far = points[1] if p.start == node else points[-2]
        dx, dy = far[0] - at[0], far[1] - at[1]
        n = math.hypot(dx, dy) or 1.0
        name = leg(p.id, node)
        if name is not None:
            legs.append((name, (dx / n, dy / n)))
    ways: list[SwitchPath] = []
    left = list(legs)
    while len(left) >= 2:
        first = left.pop(0)
        other = min(left, key=lambda x: first[1][0] * x[1][0] + first[1][1] * x[1][1])
        left.remove(other)
        ways.append(SwitchPath(between=(first[0], other[0])))
    return ways


def drawing(read: DrawingRead, station_id: str, name: str, file: str) -> TklDrawing:
    """The proposal as Rita's draft: the model, and the panel the engine lays out (TKL23,
    TKL81). Raises LayoutError when the engine cannot lay it out."""
    return drawing_of(proposal(read, station_id, name, file))
