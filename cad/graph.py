"""The track graph of a module from measures (CAD-01, Bara mått), and its ids (CAD-20).

A module from measures gets its graph straight from its gables: one node per track at each gable
(a module joint), and, when both gables have the same tracks at the same places, one piece per
track from gable A to gable B: a LINE on a straight module or a trapezoid, whose Kant 1 is
straight, and an ARC on a curve. When the gables differ, the tracks in between are unknown until
the photo or the drawing (parts b and c): the nodes are there and the graph is not complete.

Ids are kept when the module is saved again (CAD-20, bildkedjan step 12): a new node is matched
against the previous version's on the same gable, by its track number when the gable has as many
tracks as before, else by the nearest position within MATCH_WITHIN mm; a piece keeps its id when
it joins the same two nodes. An id is never used again for something else: graph.issued counts
every id issued.

as_station_model() maps the graph to the station model's parts (contracts/station_model.py),
which is what part d sends to Studio (CAD-10): the same ids, the same node types, and the
segments as points, arcs sampled every SAMPLE_STEP mm as the AnyRail import does.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from cad import geometry
from contracts.cad import (
    POSITION_TOLERANCE,
    ArcSegment,
    Certainty,
    Curve,
    Gable,
    GableEnd,
    GraphNode,
    GraphOrigin,
    GraphPiece,
    GraphSource,
    LineSegment,
    Segment,
    Shape,
    TrackGraph,
)
from contracts.station_model import Node, NodeType, Origin, Point, Source, TrackPiece

MATCH_WITHIN = 30.0
"""How far in mm a track at a gable may move and still be the same track."""
SAMPLE_STEP = 10.0
"""An arc becomes points every 10 mm for the station model, as AnyRail's kink check samples."""

MEASURED = GraphOrigin(source=GraphSource.MEASURES, certainty=Certainty.PROBABLE)


def same_tracks(a: Sequence[float], b: Sequence[float]) -> bool:
    """Do the two gables have the same tracks at the same places?"""
    return len(a) == len(b) and all(
        abs(x - y) <= POSITION_TOLERANCE for x, y in zip(a, b, strict=True)
    )


def _gable_point(shape: Shape, gables: Sequence[Gable], end: GableEnd, offset: float) -> Point:
    if isinstance(shape, Curve):
        track1 = gables[0].tracks[0]
        angle = 0.0 if end == GableEnd.A else shape.angle
        return geometry.point_on(shape, track1, offset, angle)
    x = 0.0 if end == GableEnd.A else shape.length
    return (x, offset)


def _segment(shape: Shape, gables: Sequence[Gable], offset: float) -> Segment:
    start = _gable_point(shape, gables, GableEnd.A, offset)
    end = _gable_point(shape, gables, GableEnd.B, offset)
    if isinstance(shape, Curve):
        track1 = gables[0].tracks[0]
        return ArcSegment(
            start=start,
            end=end,
            center=geometry.centre(shape, track1),
            radius=geometry.line_radius(shape, track1, offset),
            clockwise=shape.edge == "outer",
        )
    return LineSegment(start=start, end=end)


class _Ids:
    def __init__(self, issued: int) -> None:
        self.issued = issued

    def new(self, prefix: str) -> str:
        self.issued += 1
        return f"{prefix}{self.issued}"


def _match(
    now: Sequence[float], before: Sequence[float], before_ids: Sequence[str | None]
) -> list[str | None]:
    """The previous id for each track now at a gable, or None for a new track."""
    if len(now) == len(before):
        return list(before_ids)
    found: list[str | None] = [None] * len(now)
    pairs = sorted(
        (abs(x - y), i, j)
        for i, x in enumerate(now)
        for j, y in enumerate(before)
        if abs(x - y) <= MATCH_WITHIN and before_ids[j] is not None
    )
    used_now: set[int] = set()
    used_before: set[int] = set()
    for _, i, j in pairs:
        if i in used_now or j in used_before:
            continue
        found[i] = before_ids[j]
        used_now.add(i)
        used_before.add(j)
    return found


def from_measures(
    shape: Shape,
    gables: Sequence[Gable],
    previous: tuple[TrackGraph, Sequence[Gable]] | None = None,
) -> TrackGraph:
    """The graph of a module from measures, with the previous version's ids where they fit."""
    old_graph, old_gables = previous if previous is not None else (TrackGraph(), [])
    ids = _Ids(old_graph.issued)
    old_nodes = {(n.gable, n.track): n.id for n in old_graph.nodes if n.gable is not None}
    old_pieces = {frozenset((p.start, p.end)): p.id for p in old_graph.pieces}
    nodes: list[GraphNode] = []
    by_end: dict[GableEnd, list[str]] = {}
    for gable in gables:
        before = next((g.tracks for g in old_gables if g.end == gable.end), [])
        before_ids = [old_nodes.get((gable.end, n + 1)) for n in range(len(before))]
        kept = _match(gable.tracks, before, before_ids)
        made: list[str] = []
        for n, (offset, old) in enumerate(zip(gable.tracks, kept, strict=True)):
            node_id = old or ids.new("n")
            made.append(node_id)
            nodes.append(
                GraphNode(
                    id=node_id,
                    type=NodeType.MODULE_JOINT,
                    at=_gable_point(shape, gables, gable.end, offset),
                    gable=gable.end,
                    track=n + 1,
                )
            )
        by_end[gable.end] = made
    a, b = gables[0].tracks, gables[1].tracks
    through = same_tracks(a, b)
    pieces: list[GraphPiece] = []
    if through:
        for offset, start, end in zip(a, by_end[GableEnd.A], by_end[GableEnd.B], strict=True):
            piece_id = old_pieces.get(frozenset((start, end))) or ids.new("s")
            pieces.append(
                GraphPiece(
                    id=piece_id,
                    start=start,
                    end=end,
                    segments=[_segment(shape, gables, offset)],
                    origin=MEASURED,
                )
            )
    return TrackGraph(
        nodes=nodes,
        pieces=pieces,
        complete=through or (not a and not b),
        issued=ids.issued,
    )


def segment_length(segment: Segment) -> float:
    if isinstance(segment, LineSegment):
        return math.dist(segment.start, segment.end)
    return segment.radius * _sweep(segment)


def _sweep(arc: ArcSegment) -> float:
    """The arc's angle in radians, along its direction."""
    a0 = math.atan2(arc.start[1] - arc.center[1], arc.start[0] - arc.center[0])
    a1 = math.atan2(arc.end[1] - arc.center[1], arc.end[0] - arc.center[0])
    turn = (a1 - a0) if arc.clockwise else (a0 - a1)
    # With y down a clockwise turn on the screen is a growing angle.
    return turn % (2 * math.pi)


def track_length(graph: TrackGraph) -> float:
    return sum(segment_length(s) for piece in graph.pieces for s in piece.segments)


def sample(segment: Segment, step: float = SAMPLE_STEP) -> list[Point]:
    """The segment as points from start to end: a line's two ends, an arc every step mm."""
    if isinstance(segment, LineSegment):
        return [segment.start, segment.end]
    sweep = _sweep(segment)
    count = max(1, math.ceil(segment.radius * sweep / step))
    a0 = math.atan2(segment.start[1] - segment.center[1], segment.start[0] - segment.center[0])
    sign = 1.0 if segment.clockwise else -1.0
    points = [
        (
            round(segment.center[0] + segment.radius * math.cos(a0 + sign * sweep * k / count), 2),
            round(segment.center[1] + segment.radius * math.sin(a0 + sign * sweep * k / count), 2),
        )
        for k in range(count + 1)
    ]
    points[0], points[-1] = segment.start, segment.end
    return points


STUDIO_SOURCE: dict[GraphSource, Source] = {
    GraphSource.MEASURES: Source.ASSUMED,
    GraphSource.PHOTO: Source.PHOTO,
    GraphSource.SKETCH: Source.ASSUMED,
    GraphSource.ANYRAIL: Source.ANYRAIL,
    GraphSource.DRAWN: Source.DRAWN,
}
"""The piece's source in the station model. Measures alone and a sketch say where a track goes
but not how it lies, so Studio shows them as assumed until the owner confirms them."""


def as_station_model(graph: TrackGraph) -> tuple[list[Node], list[TrackPiece]]:
    """The graph as the station model's nodes and track pieces, with the same ids (CAD-10)."""
    nodes = [Node(id=n.id, type=n.type) for n in graph.nodes]
    pieces: list[TrackPiece] = []
    for piece in graph.pieces:
        points: list[Point] = []
        for segment in piece.segments:
            sampled = sample(segment)
            points.extend(sampled if not points else sampled[1:])
        origin = None
        if piece.origin is not None:
            origin = Origin(
                source=STUDIO_SOURCE[piece.origin.source],
                confirmed=piece.origin.certainty == Certainty.CONFIRMED,
                ref=piece.id,
            )
        pieces.append(
            TrackPiece(
                id=piece.id,
                start=piece.start,
                end=piece.end,
                track=piece.track,
                geometry=points,
                origin=origin,
            )
        )
    return nodes, pieces
