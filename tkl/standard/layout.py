"""The layout engine (§3): every station on the same grid by the same rules, as the engine's
first proposal for the panel (STD-02, STD-09). The owner may redraw it as a track plan, and then
the panel is built from the plan instead (tkl/standard/plan.py).

The grid (STD-20). A cell is 24 px. Tracks run horizontally on rows three cells apart. A
transition (a switch's diverging leg, a crossover, a line that turns off) takes 3 cells
sideways per row at 45° and 6 at the flat 1:2, and a panel has one angle. The engine takes flat
if the station fits on 1920 × 1080 and 45° otherwise (STD-11). If it still does not fit it
shortens the station tracks down to 8 cells, never the crossovers, and then splits the station
into fields on the same grid; the overview always shows the whole station (STD-03).

Rows follow the station's drawing (STD-10). The model is cut into strands: runs of track that
go straight through joints, signals, a switch's trunk and straight leg and one of a crossing's
two ways (the longer run keeps the crossing). A Y switch ends its trunk's strand, and both legs
leave it. A ladder, a strand with nothing but switches of its own, gives each switch to the
track that leaves it, so the switches stand on one diagonal. Each strand with a node of its own
gets a row; a connector between two others gets none.

A track holds its row without signals too, as in a station from CAD's track graph, which has
none (CAD-09). A strand between two others with nothing of its own but switches and joints, a
ladder or a connector by the rules above, is a track all the same where it carries a numbered
station track: it lies on a row of its own from its first node on the station track to its
last, as it would between signals (one row per station track, at least 14 cells, §3.2–3.3). So
is a connector, with no switch of its own either, that the drawing shows running level
east–west for at least as far as a station track is long against the rows it goes sideways (14
cells to 3): a track, not a crossover, held on its row by the ends of that stretch. A ladder
stays a ladder, its crossovers exact.

The drawing order comes from the real geometry (TrackPiece.geometry) where the model has it:
which of two strands side by side lies above the other, compared at the same places east–west
(so a curved station keeps its order), and which side a leg leaves on where they do not run
side by side. A piece whose shape does not meet its nodes, as a rewired one keeps the old
drawing's shape (TKL82), says nothing about the order. Where the model has no usable geometry,
the order of the station tracks in the model is the drawing order, and a diverging leg goes
below. From the top, each strand takes the first row below every strand that must be above it
and beside nothing it lies beside; a strand that leaves another gets a new row next to it
rather than skipping rows, and then moves row by row towards it while the rows are free: a stub
extends the nearest row. A line that leaves at an angle gets the top or the bottom row where it
can get there without crossing anything.

Columns come from the longest path over inequality constraints (STD-20), solved with
Bellman–Ford: every piece runs from west to east, a block is at least 2 cells, a station track at
least 14 (8 shortened), a crossover exactly 3 or 6 cells per row, and signals in the same
position stand in one column where that is possible. A transition runs diagonally from the end
where its strand leaves another, and horizontally into its own nodes and into the turntable. A
transition that passes another row asks the strands there to end before it or start after it,
and strands that share a row keep their order. Where a loop of crossovers cannot close exactly
(over the turntable, say), one of them is let to be longer. If two tracks still meet off a node,
the one further west is made to end before the other begins, and the columns are solved again;
the engine never hands over a panel that breaks the grid's rules (tkl/standard/grid.py).

Labels stand in fixed places (§3.4, STD-13, STD-15). Curves are straight in the schematic view;
each line also carries its real shape for the soft view (STD-12).

Nothing here names a station (RS13).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from contracts.station_model import Cell, NodeType, Point, SignalType, StationModel, SwitchType
from contracts.tkl import (
    LabelSide,
    Panel,
    PanelAngle,
    PanelField,
    PanelLabel,
    PanelLine,
    PanelNode,
    PanelSignal,
    PanelSource,
    PanelSwitch,
    PanelTable,
    PanelTrackName,
)
from tkl.standard.graph import SLIP_TYPES, Graph, length
from tkl.standard.grid import Hit, describe, hits

CELL_PX = 24
ROW = 3
"""Cells between two rows."""
SIDEWAYS = {PanelAngle.STEEP: 3, PanelAngle.FLAT: 6}
"""Cells sideways per row in a transition (TKL6)."""
SCREEN = (1920, 1080)
FITS = (SCREEN[0] // CELL_PX, SCREEN[1] // CELL_PX)
"""The panel screen in cells: 80 × 45."""
STATION_TRACK = 14
SHORTENED = 8
BLOCK = 2
MARGIN = (3, 2)
"""Cells around the tracks for the labels: left and right, top and bottom."""
TABLE_RIM = 1.0
TABLE_RAY = 2.5
"""The turntable's radius and how far its stall tracks reach from its centre, in cells."""
TABLE_SPAN = 3
ALIGN_MM = 80.0
"""Signals facing the same way within this many millimetres east–west line up."""
HORIZONTAL = 0.97
"""A turntable track this close to east–west (|cos|) carries the table on its row."""
LEVEL = 0.02
"""A piece runs level in the drawing when it rises or falls less than this per mm along."""
ALONG = STATION_TRACK / ROW
"""A connector that runs level this many times as far as it goes sideways is a track: on the
panel that is a station track's 14 cells against the 3 of a row."""

SOFT = frozenset({NodeType.JOINT, NodeType.MODULE_JOINT, NodeType.BLOCK_BOUNDARY})
JUNCTIONS = frozenset({NodeType.SWITCH, NodeType.CROSSING})
"""Where a transition starts at once, and between two of which it is exactly 3 or 6 per row."""
PASSING = frozenset(
    {
        NodeType.JOINT,
        NodeType.MODULE_JOINT,
        NodeType.BLOCK_BOUNDARY,
        NodeType.SIGNAL_POINT,
        NodeType.STOP_POINT,
    }
)


class LayoutError(Exception):
    """The engine cannot lay out the station; the message says why, in Swedish."""

    def __init__(self, message: str, cycle: list[tuple[str, str, float, str]] | None = None):
        super().__init__(message)
        self.cycle = cycle or []


TABLE_WAY = "vid vändskivan: "
EXACT = "exakt: "
"""Marks the upper half of an exact constraint, the one a loop of transitions may give up."""


# --- Small geometry ---------------------------------------------------------------------


def _unit(dx: float, dy: float) -> tuple[float, float]:
    d = math.hypot(dx, dy)
    return (dx / d, dy / d) if d > 0 else (1.0, 0.0)


def _up(direction: tuple[float, float]) -> tuple[float, float]:
    """Left of the direction of travel, in the drawing's y-down coordinates."""
    return (direction[1], -direction[0])


def _dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _sub(a: Point, b: Point) -> tuple[float, float]:
    return (a[0] - b[0], a[1] - b[1])


# --- The model as strands ---------------------------------------------------------------


@dataclass
class Strand:
    """A run of track that goes straight through, west to east, with a row of its own unless it
    is only a connector between two others."""

    id: int
    pieces: list[str]
    nodes: list[str]
    """West to east: one more than the pieces."""
    attached: tuple[bool, bool] = (False, False)
    """The west and the east end belong to another strand: it leaves that one there."""
    kind: str = "track"  # "track", or "table": the turntable alone, when no track carries it
    row: int | None = None

    @property
    def west(self) -> str:
        return self.nodes[0]

    @property
    def east(self) -> str:
        return self.nodes[-1]

    def own(self) -> list[str]:
        """The nodes this strand places: all but the ends where it leaves another strand."""
        first = 1 if self.attached[0] else 0
        last = len(self.nodes) - 1 if self.attached[1] else len(self.nodes)
        return self.nodes[first:last]


@dataclass
class Section:
    """Where a strand leaves the row of another: from the node it leaves at to its first node
    on its own row, over the pieces between. A connector is one section from end to end."""

    strand: int
    start: str
    end: str
    pieces: list[str]
    nodes: list[str]
    """From start to end: the soft nodes between are placed along the way."""


@dataclass
class Shape:
    """What the engine knows about the station before it places anything."""

    model: StationModel
    graph: Graph
    eastward: dict[str, bool]
    """Each piece: True if it runs from its start in the west to its end in the east."""
    strands: list[Strand]
    owner: dict[str, int]
    """Each placed node: the strand whose row it is on."""
    stall: dict[str, float]
    """The turntable's stall tracks, drawn as rays: piece and angle in degrees."""
    real: dict[str, Point]
    """Each node's point in the drawing, where the model has a usable geometry."""
    geometry: bool
    tables: dict[str, int] = field(default_factory=dict)
    """Each turntable node: the strand that carries it."""
    extent: dict[int, tuple[float, float]] = field(default_factory=dict)
    """Each strand's reach east–west in the drawing, in millimetres."""
    trusted: set[str] = field(default_factory=set)
    """The pieces whose shape in the drawing meets their nodes."""
    reach: _Reach | None = None
    """Which nodes lie west of which: set once the strands are made."""
    held: set[str] = field(default_factory=set)
    """Soft nodes that hold a track on its row, as its signals would."""

    def shape_of(self, piece: str) -> list[Point]:
        """A piece's shape in the drawing, if it can be trusted for the order."""
        return list(self.graph.pieces[piece].geometry) if piece in self.trusted else []


class _Parity:
    """Union–find with parity: which pieces must run the same way, and which the other."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.parity: dict[str, int] = {}

    def find(self, x: str) -> tuple[str, int]:
        self.parent.setdefault(x, x)
        self.parity.setdefault(x, 0)
        path = []
        while self.parent[x] != x:
            path.append(x)
            x = self.parent[x]
        root, total = x, 0
        for node in reversed(path):
            total ^= self.parity[node]
            self.parity[node] = total
            self.parent[node] = root
        return root, self.parity[path[0]] if path else 0

    def join(self, a: str, b: str, differ: int) -> bool:
        ra, pa = self.find(a)
        rb, pb = self.find(b)
        if ra == rb:
            return (pa ^ pb) == differ
        self.parent[rb] = ra
        self.parity[rb] = pa ^ pb ^ differ
        return True


EAST = "\x00east"


def _starts(graph: Graph, piece: str, node: str) -> int:
    return 1 if graph.pieces[piece].start == node else 0


def _through_pairs(graph: Graph, node: str, real: dict[str, Point]) -> list[tuple[str, str]]:
    """A crossing's or slip's two ways straight through."""
    switch = graph.switch_at[node]
    pieces = [p for p in graph.touching.get(node, []) if p in graph.pieces]
    if switch.type == SwitchType.CROSSING or len(pieces) != 4:
        found = [path.between for path in switch.paths]
        return [(a, b) for a, b in found if a in graph.pieces and b in graph.pieces][:2]
    if node in real and all(len(graph.pieces[p].geometry) >= 2 for p in pieces):
        away = {p: _away(graph, p, node) for p in pieces}
        a = pieces[0]
        best: tuple[float, list[tuple[str, str]]] | None = None
        for b in pieces[1:]:
            rest = [p for p in pieces[1:] if p != b]
            score = _dot(away[a], away[b]) + _dot(away[rest[0]], away[rest[1]])
            pairs = [(a, b), (rest[0], rest[1])]
            if best is None or score < best[0]:
                best = (score, pairs)
        assert best is not None
        return best[1]
    same = [
        path.between
        for path in switch.paths
        if len(set(path.positions.values())) <= 1 and path.positions
    ]
    if len(same) >= 2 and not set(same[0]) & set(same[1]):
        return same[:2]
    return [path.between for path in switch.paths][:2]


def _away(graph: Graph, piece: str, node: str) -> tuple[float, float]:
    """The direction a piece leaves a node in, in the drawing; east where it has no length."""
    return _heading(graph, piece, node) or (1.0, 0.0)


def _heading(graph: Graph, piece: str, node: str) -> tuple[float, float] | None:
    """The direction a piece leaves a node in, a little way along; None without a length."""
    points = graph.pieces[piece].geometry
    if len(points) < 2:
        return None
    if graph.pieces[piece].start != node:
        points = list(reversed(points))
    origin = points[0]
    total = length(graph.pieces[piece])
    if total <= 1e-6:
        return None
    far = points[-1]
    for q in points[1:]:
        if math.dist(q, origin) > 0.3 * total:
            far = q
            break
    return _unit(*_sub(far, origin))


def _node_points(graph: Graph) -> tuple[dict[str, Point], bool, set[str]]:
    """Each node's point in the drawing, whether the geometry hangs together well enough to
    give the drawing order, and the pieces whose shape meets their nodes. A piece the owner has
    rewired keeps the drawing's old shape (TKL82); its shape says nothing about the order."""
    points: dict[str, list[Point]] = defaultdict(list)
    for piece in graph.pieces.values():
        if len(piece.geometry) >= 2:
            points[piece.start].append(piece.geometry[0])
            points[piece.end].append(piece.geometry[-1])
    every = [p for found in points.values() for p in found]
    if not every:
        return {}, False, set()
    xs, ys = [p[0] for p in every], [p[1] for p in every]
    size = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    near = 0.01 * size if size > 0 else 1.0
    real: dict[str, Point] = {}
    for node, found in points.items():
        real[node] = max(found, key=lambda p: sum(1 for q in found if math.dist(p, q) <= near))
    tables = {t.node for t in graph.model.turntables}
    trusted = {
        piece.id
        for piece in graph.pieces.values()
        if len(piece.geometry) >= 2
        and all(
            node in tables or math.dist(real[node], point) <= near
            for node, point in ((piece.start, piece.geometry[0]), (piece.end, piece.geometry[-1]))
        )
    }
    if size <= 0 or max(ys) - min(ys) <= 1e-6:
        return real, False, trusted
    shared = [n for n, found in points.items() if len(found) >= 2 and n not in tables]
    agree = [n for n in shared if all(math.dist(real[n], p) <= near for p in points[n])]
    usable = bool(shared) and len(agree) >= 0.8 * len(shared)
    return real, usable, trusted


def _orient(graph: Graph, real: dict[str, Point]) -> dict[str, bool]:
    """Which way each piece runs, west to east: from how they continue through the nodes, and
    from the drawing where nothing else says."""
    model = graph.model
    links = _Parity()
    for piece in graph.pieces:
        links.find(piece)
    for node, touching in graph.touching.items():
        pieces = [p for p in touching if p in graph.pieces]
        switch = graph.switch_at.get(node)
        pairs: list[tuple[str, str]] = []
        if switch is not None:
            if switch.type in SLIP_TYPES:
                pairs = [path.between for path in switch.paths]
            elif switch.trunk is not None:
                pairs = [
                    (switch.trunk, leg)
                    for leg in (switch.straight, switch.diverging)
                    if leg is not None and switch.trunk in graph.pieces and leg in graph.pieces
                ]
        elif graph.node_type.get(node) != NodeType.TURNTABLE and len(pieces) == 2:
            pairs = [(pieces[0], pieces[1])]
        for a, b in pairs:
            if a in graph.pieces and b in graph.pieces and a != b:
                links.join(a, b, 1 ^ _starts(graph, a, node) ^ _starts(graph, b, node))
    anchored: set[str] = set()
    for table in model.turntables:
        for track in table.tracks:
            if track.piece not in graph.pieces:
                continue
            cos = math.cos(math.radians(track.angle))
            if abs(cos) < 0.3:
                continue
            starts = _starts(graph, track.piece, table.node)
            differ = starts ^ 1 if cos > 0 else starts
            if links.join(track.piece, EAST, differ):
                anchored.add(links.find(track.piece)[0])
    east_root = links.find(EAST)[0]
    weight: dict[str, float] = defaultdict(float)
    for item in graph.pieces.values():
        root, parity = links.find(item.id)
        if len(item.geometry) >= 2:
            dx = item.geometry[-1][0] - item.geometry[0][0]
            weight[root] += dx if parity == 0 else -dx
    eastward: dict[str, bool] = {}
    for piece in graph.pieces:
        root, parity = links.find(piece)
        if root == east_root:
            _, east_parity = links.find(EAST)
            eastward[piece] = (parity ^ east_parity) == 0
        else:
            flip = weight[root] < 0
            eastward[piece] = (parity == 0) != flip
    return eastward


def _west(graph: Graph, eastward: dict[str, bool], piece: str) -> str:
    p = graph.pieces[piece]
    return p.start if eastward[piece] else p.end


def _east(graph: Graph, eastward: dict[str, bool], piece: str) -> str:
    p = graph.pieces[piece]
    return p.end if eastward[piece] else p.start


def shape(model: StationModel) -> Shape:
    """The strands, which way every piece runs, and what owns each node."""
    graph = Graph(model)
    real, usable, trusted = _node_points(graph)
    eastward = _orient(graph, real)
    degree = {n: len(ps) for n, ps in graph.touching.items()}

    # The turntable's tracks: stalls that end there are rays; the others reach the station.
    stall: dict[str, float] = {}
    carrier: dict[str, str] = {}
    approaches: dict[str, list[tuple[str, float]]] = {}
    for table in model.turntables:
        found = []
        for track in table.tracks:
            piece = graph.pieces.get(track.piece)
            if piece is None:
                continue
            other = piece.end if piece.start == table.node else piece.start
            if degree.get(other, 0) == 1:
                stall[track.piece] = track.angle
            else:
                found.append((track.piece, track.angle))
        approaches[table.node] = found
        level = [a for a in found if abs(math.cos(math.radians(a[1]))) >= HORIZONTAL]
        if level:
            best = max(level, key=lambda a: abs(math.cos(math.radians(a[1]))))
            carrier[table.node] = best[0]

    # How the pieces continue through each node, and where a piece leaves another strand.
    following: dict[tuple[str, str], str] = {}
    attaches: set[tuple[str, str]] = set()
    crossings: dict[str, list[tuple[str, str]]] = {}
    for node, touching in graph.touching.items():
        pieces = [p for p in touching if p in graph.pieces and p not in stall]
        node_type = graph.node_type.get(node)
        switch = graph.switch_at.get(node)
        if switch is not None and switch.type in SLIP_TYPES:
            pairs = _through_pairs(graph, node, real if usable else {})
            crossings[node] = pairs
            for a, b in pairs:
                following[(a, node)] = b
                following[(b, node)] = a
            continue
        if switch is not None:
            if switch.type == SwitchType.Y:
                for leg in (switch.straight, switch.diverging):
                    if leg in graph.pieces:
                        attaches.add((leg, node))
            else:
                if switch.trunk in graph.pieces and switch.straight in graph.pieces:
                    following[(switch.trunk, node)] = switch.straight
                    following[(switch.straight, node)] = switch.trunk
                if switch.diverging in graph.pieces:
                    attaches.add((switch.diverging, node))
            continue
        if node_type == NodeType.TURNTABLE:
            for ray, _ in approaches.get(node, []):
                if carrier.get(node) != ray:
                    attaches.add((ray, node))
            continue
        if len(pieces) == 2 and (node_type in PASSING or node_type is None):
            a, b = pieces
            following[(a, node)] = b
            following[(b, node)] = a

    def chain(start: str) -> list[str]:
        found = [start]
        for direction in (0, 1):
            here = start
            while True:
                end = (
                    _west(graph, eastward, here) if direction == 0 else _east(graph, eastward, here)
                )
                after = following.get((here, end))
                if after is None or after in found:
                    break
                # The next piece must continue the same way.
                if direction == 0 and _east(graph, eastward, after) != end:
                    break
                if direction == 1 and _west(graph, eastward, after) != end:
                    break
                if direction == 0:
                    found.insert(0, after)
                else:
                    found.append(after)
                here = after
        return found

    # A crossing's way straight through: the longer run keeps the node; the other leaves it.
    for node, pairs in crossings.items():
        if len(pairs) < 2:
            continue
        runs = [chain(pair[0]) for pair in pairs]
        sizes = [
            (sum(length(graph.pieces[p]) for p in run), len(run), -i) for i, run in enumerate(runs)
        ]
        keep = max(range(len(pairs)), key=lambda i: sizes[i])
        for i, pair in enumerate(pairs):
            if i == keep:
                continue
            for leaving in pair:
                following.pop((leaving, node), None)
                attaches.add((leaving, node))

    strands: list[Strand] = []
    seen: set[str] = set()
    for first in graph.pieces:
        if first in seen or first in stall:
            continue
        run = chain(first)
        seen.update(run)
        nodes = [_west(graph, eastward, run[0])] + [_east(graph, eastward, p) for p in run]
        attached = ((run[0], nodes[0]) in attaches, (run[-1], nodes[-1]) in attaches)
        strands.append(Strand(len(strands), run, nodes, attached))

    held, tracks = _held(graph, strands, model, trusted if usable else set())
    owner: dict[str, int] = {}
    for strand in strands:
        for node in strand.own():
            owner.setdefault(node, strand.id)
    _ladders(graph, strands, owner, held, tracks)
    tables: dict[str, int] = {}
    for table in model.turntables:
        if table.node in owner:
            tables[table.node] = owner[table.node]
            continue
        lone = Strand(len(strands), [], [table.node], (False, False), kind="table")
        strands.append(lone)
        owner[table.node] = lone.id
        tables[table.node] = lone.id
    for node in graph.touching:
        if node not in owner:
            # A node every strand leaves: a switch whose trunk is missing, say. Its first
            # strand carries it.
            for strand in strands:
                if node in strand.nodes:
                    owner[node] = strand.id
                    break
    made = Shape(
        model,
        graph,
        eastward,
        strands,
        owner,
        stall,
        real,
        usable,
        tables,
        trusted=trusted,
        held=held,
    )
    if usable:
        for strand in strands:
            xs = [p[0] for item in strand.pieces for p in made.shape_of(item)]
            if strand.kind == "table":
                middle = strand.nodes[0]
                xs = [
                    p[0]
                    for ray in graph.touching.get(middle, [])
                    if ray in stall
                    for p in graph.pieces[ray].geometry
                ]
                centre = real.get(middle)
                if centre is not None:
                    xs.append(centre[0])
            if xs:
                made.extent[strand.id] = (min(xs), max(xs))
    return made


def _between(graph: Graph, strand: Strand, switches: bool = True) -> bool:
    """A strand between two others with nothing of its own but soft nodes, and switches where
    they may count: a ladder, or a connector."""
    own = strand.own()
    allowed = SOFT | {NodeType.SWITCH} if switches else SOFT
    return (
        strand.kind == "track"
        and strand.attached == (True, True)
        and bool(own)
        and all(graph.node_type.get(n) in allowed for n in own)
    )


def _held(
    graph: Graph, strands: list[Strand], model: StationModel, trusted: set[str]
) -> tuple[set[str], set[int]]:
    """Tracks without signals (§3.2): a strand between two others, with nothing of its own but
    switches and soft nodes, is a track all the same, and no ladder or connector, where it
    carries a numbered station track (one row per station track), or, with no switch of its own
    either, where the drawing shows it running level beside the others (rows follow the
    drawing). Soft nodes of its own then hold it on a row, as signals would: the first and the
    last on the station track, or the ends of its level stretch. Returns those nodes and the
    tracks."""
    found: set[str] = set()
    tracks: set[int] = set()
    for track in model.station_tracks:
        pieces = set(track.pieces)
        carriers = [s for s in strands if pieces & set(s.pieces)]
        if not carriers:
            continue
        # The track is on the strand that carries most of it.
        strand = max(
            carriers,
            key=lambda s: (sum(length(graph.pieces[p]) for p in s.pieces if p in pieces), -s.id),
        )
        if not _between(graph, strand):
            continue
        tracks.add(strand.id)
        on = [
            node
            for i, node in enumerate(strand.nodes[1:-1], start=1)
            if pieces & {strand.pieces[i - 1], strand.pieces[i]}
        ]
        found.update(n for n in on[:1] + on[-1:] if graph.node_type.get(n) in SOFT)
    for strand in strands:
        if strand.id in tracks or not _between(graph, strand, switches=False):
            continue
        level = _level(graph, strand, trusted)
        if level:
            found.update(level)
            tracks.add(strand.id)
    return found, tracks


def _level(graph: Graph, strand: Strand, trusted: set[str]) -> tuple[str, ...]:
    """Where a connector runs level east–west in the drawing between two nodes of its own, for
    at least ALONG times as far as it goes sideways over its whole length: the two nodes that
    end its longest such stretch. Nothing where a piece has no shape that can be trusted."""
    if any(p not in trusted for p in strand.pieces):
        return ()
    sideways = 0.0
    best: tuple[float, int, int] | None = None
    start: int | None = None
    run = 0.0
    for i, piece in enumerate(strand.pieces):
        steps = list(pairwise(graph.pieces[piece].geometry))
        sideways += sum(abs(b[1] - a[1]) for a, b in steps)
        level = all(abs(b[1] - a[1]) <= LEVEL * math.dist(a, b) for a, b in steps)
        if level and 0 < i < len(strand.pieces) - 1:
            if start is None:
                start, run = i, 0.0
            run += length(graph.pieces[piece])
            if best is None or run > best[0]:
                best = (run, start, i + 1)
        else:
            start = None
    if best is None or best[0] < ALONG * sideways:
        return ()
    return strand.nodes[best[1]], strand.nodes[best[2]]


def _ladders(
    graph: Graph, strands: list[Strand], owner: dict[str, int], held: set[str], tracks: set[int]
) -> None:
    """A ladder: a strand that leaves one track and joins another with nothing but switches of
    its own on the way. Its switches stand on the rows of the tracks that leave them, on one
    diagonal, as on a drawn panel; the ladder itself gets no row. A track without signals
    (_held) is no ladder, and a switch may stand on its row."""
    for ladder in strands:
        if ladder.kind != "track" or ladder.attached != (True, True) or ladder.id in tracks:
            continue
        own = [n for n in ladder.own() if owner.get(n) == ladder.id]
        if not own or any(graph.node_type.get(n) not in SOFT | {NodeType.SWITCH} for n in own):
            continue
        for node in own:
            switch = graph.switch_at.get(node)
            if switch is None or switch.type != SwitchType.ORDINARY:
                continue
            for side in strands:
                if side is ladder or not side.pieces:
                    continue
                if side.west == node and side.pieces[0] == switch.diverging:
                    end = 0
                elif side.east == node and side.pieces[-1] == switch.diverging:
                    end = 1
                else:
                    continue
                others = [n for n in side.own() if graph.node_type.get(n) not in SOFT or n in held]
                if not others:
                    break
                attached = list(side.attached)
                attached[end] = False
                side.attached = (attached[0], attached[1])
                owner[node] = side.id
                break


# --- The order of the rows --------------------------------------------------------------


def _hard(shape: Shape, node: str) -> bool:
    return shape.graph.node_type.get(node) not in SOFT


def _holds(shape: Shape, node: str) -> bool:
    """A node that holds its strand on a row: a hard one, or one that holds a track without
    signals."""
    return _hard(shape, node) or node in shape.held


def _owned(shape: Shape, strand: Strand) -> list[str]:
    """The nodes this strand places on its row."""
    return [n for n in strand.nodes if shape.owner.get(n) == strand.id]


def _needs_row(shape: Shape, strand: Strand) -> bool:
    if strand.kind == "table":
        return True
    if any(_holds(shape, n) for n in _owned(shape, strand)):
        return True
    # A connector that leaves one strand and comes back to it is a loop: it needs a row.
    ends = [shape.owner.get(strand.west), shape.owner.get(strand.east)]
    return ends[0] == ends[1]


class _Reach:
    """Which nodes lie west of which, along the pieces from west to east."""

    def __init__(self, shape: Shape) -> None:
        graph = shape.graph
        self.after: dict[str, set[str]] = defaultdict(set)
        for piece in graph.pieces:
            if piece in shape.stall:
                continue
            self.after[_west(graph, shape.eastward, piece)].add(_east(graph, shape.eastward, piece))
        self.memo: dict[str, frozenset[str]] = {}
        self.ranks: dict[str, int] = {}

    def reach(self, node: str) -> frozenset[str]:
        if node in self.memo:
            return self.memo[node]
        found: set[str] = set()
        stack = [node]
        while stack:
            here = stack.pop()
            for nxt in self.after.get(here, ()):
                if nxt not in found:
                    found.add(nxt)
                    stack.append(nxt)
        self.memo[node] = frozenset(found)
        return self.memo[node]

    def before(self, a: str, b: str) -> bool:
        """a lies west of b, or is b."""
        return a == b or b in self.reach(a)

    def rank(self, node: str) -> int:
        """How many pieces lie west of a node at most: an east–west place without a drawing."""
        if not self.ranks:
            nodes = set(self.after) | {n for after in self.after.values() for n in after}
            into: dict[str, int] = dict.fromkeys(nodes, 0)
            for after in self.after.values():
                for n in after:
                    into[n] += 1
            ready = sorted(n for n, count in into.items() if count == 0)
            ranks = dict.fromkeys(nodes, 0)
            while ready:
                here = ready.pop()
                for n in sorted(self.after.get(here, ())):
                    ranks[n] = max(ranks[n], ranks[here] + 1)
                    into[n] -= 1
                    if into[n] == 0:
                        ready.append(n)
            self.ranks = ranks
        return self.ranks.get(node, 0)


def _span(shape: Shape, strand: Strand) -> tuple[str, str]:
    return strand.west, strand.east


def _overlap(shape: Shape, reach: _Reach, a: Strand, b: Strand) -> bool:
    """Whether two strands lie side by side somewhere, east–west: in the drawing where the model
    has a geometry, else along the pieces."""
    if a.id in shape.extent and b.id in shape.extent:
        (a0, a1), (b0, b1) = shape.extent[a.id], shape.extent[b.id]
        return a1 > b0 + 1e-6 and b1 > a0 + 1e-6
    aw, ae = _span(shape, a)
    bw, be = _span(shape, b)
    return not (reach.before(ae, bw) or reach.before(be, aw))


def _near(shape: Shape, a: Strand, b: Strand) -> bool:
    """Two strands that meet, or that one piece joins: their order shows in the drawing."""
    graph = shape.graph
    ends_a = {a.west, a.east}
    ends_b = {b.west, b.east}
    if ends_a & ends_b:
        return True
    for piece in graph.pieces.values():
        if (piece.start in ends_a and piece.end in ends_b) or (
            piece.end in ends_a and piece.start in ends_b
        ):
            return True
    return False


def _samples(shape: Shape, strand: Strand) -> list[tuple[Point, tuple[float, float]]]:
    """Points along a strand in the drawing, each with the strand's direction there, east."""
    found: list[tuple[Point, tuple[float, float]]] = []
    for piece in strand.pieces:
        points = shape.shape_of(piece)
        if len(points) < 2:
            continue
        if not shape.eastward[piece]:
            points.reverse()
        step = max(1, len(points) // 6)
        chosen = points[::step]
        if chosen[-1] != points[-1]:
            chosen.append(points[-1])
        for a, b in pairwise(chosen):
            found.append((a, _unit(*_sub(b, a))))
        found.append((chosen[-1], found[-1][1] if found else (1.0, 0.0)))
    if not found and strand.kind == "table" and strand.nodes[0] in shape.real:
        found.append((shape.real[strand.nodes[0]], (1.0, 0.0)))
    return found


def _above(shape: Shape, upper: Strand, lower: Strand) -> float:
    """How far `upper` lies above `lower` in the drawing: positive if it does. Where they run
    side by side east–west, compared at the same places along; else where they come closest."""
    one = _samples(shape, upper)
    other = _samples(shape, lower)
    if not one or not other:
        return 0.0
    a = [p for p, _ in one]
    b = [p for p, _ in other]
    lo = max(min(p[0] for p in a), min(p[0] for p in b))
    hi = min(max(p[0] for p in a), max(p[0] for p in b))
    if hi - lo > 1e-6:
        found = []
        for i in range(9):
            x = lo + (hi - lo) * (i + 0.5) / 9
            ya, yb = _y_at(a, x), _y_at(b, x)
            if ya is not None and yb is not None:
                found.append(yb - ya)
        if found:
            return sum(found) / len(found)
    pairs: list[tuple[float, float]] = []
    for point, direction in other:
        best = min(one, key=lambda q: math.dist(q[0], point))
        pairs.append((math.dist(best[0], point), _dot(_sub(best[0], point), _up(direction))))
    pairs.sort()
    return sum(offset for _, offset in pairs[:3])


def _beside(shape: Shape, upper: Strand, lower: Strand) -> float | None:
    """Like _above, but only where the two run side by side east–west for a while."""
    a = [p for p, _ in _samples(shape, upper)]
    b = [p for p, _ in _samples(shape, lower)]
    if not a or not b:
        return None
    lo = max(min(p[0] for p in a), min(p[0] for p in b))
    hi = min(max(p[0] for p in a), max(p[0] for p in b))
    shorter = min(
        max(p[0] for p in a) - min(p[0] for p in a), max(p[0] for p in b) - min(p[0] for p in b)
    )
    if hi - lo <= 0.2 * shorter or hi - lo <= 1e-6:
        return None
    return _above(shape, upper, lower)


def _y_at(points: Sequence[Point], x: float) -> float | None:
    """Where a run of points passes x, its y; None if it does not."""
    for p, q in pairwise(points):
        if min(p[0], q[0]) - 1e-9 <= x <= max(p[0], q[0]) + 1e-9:
            if abs(q[0] - p[0]) < 1e-9:
                return (p[1] + q[1]) / 2
            return p[1] + (q[1] - p[1]) * (x - p[0]) / (q[0] - p[0])
    return None


def _leaves_above(shape: Shape, strand: Strand, node: str) -> float:
    """At the node where `strand` leaves its owner: how far above the owner it goes."""
    graph = shape.graph
    owner = shape.strands[shape.owner[node]]
    point = shape.real.get(node)
    if point is None:
        return 0.0
    if owner.kind == "table":
        return _above(shape, strand, owner)
    # The owner's direction, east, at the node: along its longest piece there.
    direction: tuple[float, float] | None = None
    best = -1.0
    for piece in owner.pieces:
        if node not in (graph.pieces[piece].start, graph.pieces[piece].end):
            continue
        heading = _heading(graph, piece, node) if piece in shape.trusted else None
        if heading is None or length(graph.pieces[piece]) <= best:
            continue
        best = length(graph.pieces[piece])
        east = _west(graph, shape.eastward, piece) == node
        direction = heading if east else (-heading[0], -heading[1])
    if direction is None:
        return _above(shape, strand, owner)
    # How far the leaving strand has gone off sideways, a little way along.
    piece = strand.pieces[0] if strand.west == node else strand.pieces[-1]
    far: Point | None = None
    walk = strand.pieces if strand.west == node else list(reversed(strand.pieces))
    gone = 0.0
    for p in walk:
        geometry = shape.shape_of(p)
        if len(geometry) < 2:
            continue
        gone += length(graph.pieces[p])
        end = (
            _east(graph, shape.eastward, p)
            if strand.west == node
            else _west(graph, shape.eastward, p)
        )
        far = shape.real.get(end, far)
        if gone > 150 or _hard(shape, end):
            break
    if far is None:
        geometry = shape.shape_of(piece)
        if len(geometry) < 2:
            return _above(shape, strand, owner)
        far = geometry[-1] if graph.pieces[piece].start == node else geometry[0]
    return _dot(_sub(far, point), _up(direction))


def _index(shape: Shape) -> dict[int, int]:
    """Without a usable geometry: each strand's place in the order of the station tracks."""
    place = {
        piece: i for i, track in enumerate(shape.model.station_tracks) for piece in track.pieces
    }
    found: dict[int, int] = {}
    for strand in shape.strands:
        found_at = [place[p] for p in strand.pieces if p in place]
        if found_at:
            found[strand.id] = min(found_at)
    return found


def _order(
    shape: Shape, rowed: list[Strand], reach: _Reach
) -> tuple[list[Strand], dict[tuple[int, int], float]]:
    """The strands from the top down, as the drawing has them."""
    index = _index(shape) if not shape.geometry else {}
    relations: dict[tuple[int, int], float] = {}

    def relate(upper: int, lower: int, weight: float) -> None:
        if upper == lower:
            return
        if (lower, upper) in relations:
            if relations[(lower, upper)] >= weight:
                return
            del relations[(lower, upper)]
        relations[(upper, lower)] = max(weight, relations.get((upper, lower), 0.0))

    ids = {s.id for s in rowed}
    by_id = {s.id: s for s in shape.strands}
    # Where a strand leaves another.
    for strand in rowed:
        for end, attached in ((strand.west, strand.attached[0]), (strand.east, strand.attached[1])):
            if not attached or end not in shape.owner:
                continue
            owner = shape.owner[end]
            if owner not in ids or owner == strand.id:
                continue
            if shape.geometry:
                beside = _beside(shape, strand, shape.strands[owner])
                offset = beside if beside is not None else _leaves_above(shape, strand, end)
                if abs(offset) > 1e-6:
                    relate(strand.id, owner, abs(offset) + 1e6) if offset > 0 else relate(
                        owner, strand.id, abs(offset) + 1e6
                    )
            else:
                mine, theirs = index.get(strand.id), index.get(owner)
                if mine is not None and theirs is not None and mine != theirs:
                    relate(strand.id, owner, 1e6) if mine < theirs else relate(
                        owner, strand.id, 1e6
                    )
                else:
                    relate(owner, strand.id, 1e6)
    # Side by side, or next to each other.
    for i, a in enumerate(rowed):
        for b in rowed[i + 1 :]:
            if not _overlap(shape, reach, a, b) and not _near(shape, a, b):
                continue
            if (a.id, b.id) in relations or (b.id, a.id) in relations:
                continue
            if shape.geometry:
                offset = _above(shape, a, b)
                if abs(offset) > 1e-6:
                    relate(a.id, b.id, abs(offset)) if offset > 0 else relate(
                        b.id, a.id, abs(offset)
                    )
            else:
                ia, ib = index.get(a.id), index.get(b.id)
                if ia is not None and ib is not None and ia != ib:
                    relate(a.id, b.id, 1.0) if ia < ib else relate(b.id, a.id, 1.0)
    # Break any cycle at its weakest link.
    while True:
        cycle = _cycle(ids, relations)
        if not cycle:
            break
        weakest = min(pairwise([*cycle, cycle[0]]), key=lambda e: relations.get(e, 0.0))
        relations.pop(weakest, None)

    def height(strand: Strand) -> tuple[float, float, int]:
        if not shape.geometry:
            return (float(index.get(strand.id, 10_000)), 0.0, strand.id)
        points = [p for p, _ in _samples(shape, strand)]
        if not points:
            return (0.0, 0.0, strand.id)
        return (sum(p[1] for p in points) / len(points), 0.0, strand.id)

    above: dict[int, set[int]] = defaultdict(set)
    for upper, lower in relations:
        above[lower].add(upper)
    placed: list[Strand] = []
    left = {s.id for s in rowed}
    while left:
        ready = [by_id[i] for i in left if not (above[i] & left)]
        chosen = min(ready, key=height)
        placed.append(chosen)
        left.discard(chosen.id)
    return placed, relations


def _cycle(ids: set[int], relations: dict[tuple[int, int], float]) -> list[int]:
    nxt: dict[int, list[int]] = defaultdict(list)
    for a, b in relations:
        nxt[a].append(b)
    state: dict[int, int] = {}
    stack_path: list[int] = []

    def visit(n: int) -> list[int]:
        state[n] = 1
        stack_path.append(n)
        for m in nxt[n]:
            if state.get(m) == 1:
                return stack_path[stack_path.index(m) :]
            if m not in state:
                found = visit(m)
                if found:
                    return found
        state[n] = 2
        stack_path.pop()
        return []

    for n in sorted(ids):
        if n not in state:
            found = visit(n)
            if found:
                return found
    return []


def _rows(
    shape: Shape, order: list[Strand], reach: _Reach, relations: dict[tuple[int, int], float]
) -> int:
    """From the top down, each strand on the first row below every strand above it that it
    lies beside, where nothing it lies beside is (STD-10). A stub thus extends the nearest row,
    and a line that leaves at an angle keeps a row of its own. Returns the number of rows."""
    above: dict[int, set[int]] = defaultdict(set)
    for upper, lower in relations:
        above[lower].add(upper)
    by_id = {s.id: s for s in shape.strands}
    links = _connections(shape)
    rows: dict[int, list[Strand]] = defaultdict(list)
    below_of: dict[int, set[int]] = defaultdict(set)
    for upper, lower in relations:
        below_of[upper].add(lower)
    for strand in order:
        row = 1 + max(
            (by_id[u].row or 0 for u in above[strand.id] if by_id[u].row is not None),
            default=-1,
        )
        leaves = strand.attached != (False, False)
        while True:
            beside = [
                other
                for other in rows[row]
                if _overlap(shape, reach, strand, other) or (strand.id, other.id) in links
            ]
            if not beside:
                break
            if leaves or any(other.id in below_of[strand.id] for other in beside):
                # Keep it next to what it leaves, or above what it must be above: a new row.
                for other in order:
                    if other.row is not None and other.row >= row:
                        other.row += 1
                rows = defaultdict(list)
                for other in order:
                    if other.row is not None:
                        rows[other.row].append(other)
                break
            row += 1
        strand.row = row
        rows[row].append(strand)
    _gravity(shape, order, relations, reach, links)
    _lines_out(shape, order, relations, reach, links)
    return len({s.row for s in order})


def _angled(shape: Shape, line: Strand, owner: Strand) -> bool:
    """A line leaves at an angle when its far end lies well away from the track it left: more
    than a tenth of its own length. Only the drawing can tell."""
    if not shape.geometry:
        return False
    graph = shape.graph
    far = [
        shape.real[n]
        for n in line.nodes
        if graph.node_type.get(n) == NodeType.LINE_EXIT and n in shape.real
    ]
    points = [p for p, _ in _samples(shape, owner)]
    if not far or not points:
        return False
    gone = min(math.dist(far[0], p) for p in points)
    return gone > 0.1 * max(1.0, sum(length(graph.pieces[p]) for p in line.pieces))


def _gravity(
    shape: Shape,
    order: list[Strand],
    relations: dict[tuple[int, int], float],
    reach: _Reach,
    links: set[tuple[int, int]],
) -> None:
    """A strand that leaves another moves row by row towards it, while the rows on the way are
    free and the drawing's order holds: the nearest row it fits on (STD-10)."""
    by_id = {s.id: s for s in order}
    above: dict[int, set[int]] = defaultdict(set)
    below: dict[int, set[int]] = defaultdict(set)
    for upper, lower in relations:
        above[lower].add(upper)
        below[upper].add(lower)

    def free(strand: Strand, row: int) -> bool:
        if any((by_id[u].row or 0) >= row for u in above[strand.id] if u in by_id):
            return False
        if any((by_id[d].row or 0) <= row for d in below[strand.id] if d in by_id):
            return False
        return not any(
            other.row == row
            and other is not strand
            and (_overlap(shape, reach, strand, other) or (strand.id, other.id) in links)
            for other in order
        )

    for _ in range(4 * len(order)):
        moved = False
        for strand in order:
            owners = [
                shape.owner[end]
                for end, attached in (
                    (strand.west, strand.attached[0]),
                    (strand.east, strand.attached[1]),
                )
                if attached and end in shape.owner and shape.owner[end] in by_id
            ]
            if not owners or strand.row is None:
                continue
            target = by_id[owners[0]].row
            if target is None:
                continue
            step = 1 if target > strand.row else -1
            if abs(target - strand.row) <= 1:
                continue
            if free(strand, strand.row + step):
                strand.row += step
                moved = True
        if not moved:
            break


def _lines_out(
    shape: Shape,
    order: list[Strand],
    relations: dict[tuple[int, int], float],
    reach: _Reach,
    links: set[tuple[int, int]],
) -> None:
    """A line that leaves another track at an angle gets a row of its own at the top or the
    bottom (§3.2): it may share that row only with what it does not lie beside."""
    graph = shape.graph
    for strand in order:
        exits = [n for n in strand.nodes if graph.node_type.get(n) == NodeType.LINE_EXIT]
        if not exits or strand.attached == (False, False):
            continue
        leaves = [
            end
            for end, attached in (
                (strand.west, strand.attached[0]),
                (strand.east, strand.attached[1]),
            )
            if attached and end in shape.owner
        ]
        if not leaves:
            continue
        owner = shape.owner[leaves[0]]
        if not _angled(shape, strand, shape.strands[owner]):
            continue
        up = (strand.id, owner) in relations
        down = (owner, strand.id) in relations
        if not (up or down):
            continue
        rows = [s.row for s in order if s.row is not None]
        edge = min(rows) if up else max(rows)
        if strand.row == edge:
            continue
        here = strand.row or 0
        between = range(edge + 1, here) if up else range(here + 1, edge)
        if any(
            s.row in between and _overlap(shape, reach, strand, s) for s in order if s is not strand
        ):
            continue
        sharing = [s for s in order if s.row == edge and s is not strand]
        clear = not any(
            _overlap(shape, reach, strand, s) or (strand.id, s.id) in links for s in sharing
        )
        must = [
            other
            for (upper, lower) in relations
            for other in order
            if (up and lower == strand.id and other.id == upper)
            or (down and upper == strand.id and other.id == lower)
        ]
        if clear and not must:
            strand.row = edge
        elif up:
            for s in order:
                if s.row is not None:
                    s.row += 1
            strand.row = 0
        else:
            strand.row = edge + 1
    used = sorted({s.row for s in order if s.row is not None})
    renumber = {r: i for i, r in enumerate(used)}
    for s in order:
        if s.row is not None:
            s.row = renumber[s.row]


def _connections(shape: Shape) -> set[tuple[int, int]]:
    """Pairs of strands joined by a connector: they may never share a row."""
    found: set[tuple[int, int]] = set()
    for strand in shape.strands:
        if strand.attached == (True, True):
            a, b = shape.owner.get(strand.west), shape.owner.get(strand.east)
            if a is not None and b is not None:
                found.add((a, b))
                found.add((b, a))
            for end in (a, b):
                if end is not None:
                    found.add((strand.id, end))
                    found.add((end, strand.id))
    return found


# --- The columns ------------------------------------------------------------------------


@dataclass
class _Constraints:
    """col(b) >= col(a) + gap, for each (a, b, gap)."""

    items: list[tuple[str, str, float, str]] = field(default_factory=list)

    def at_least(self, a: str, b: str, gap: float, why: str = "") -> None:
        self.items.append((a, b, gap, why))

    def exactly(self, a: str, b: str, gap: float, why: str = "") -> None:
        self.items.append((a, b, gap, why))
        self.items.append((b, a, -gap, EXACT + why))

    def at_most(self, a: str, b: str, gap: float, why: str = "") -> None:
        self.items.append((b, a, -gap, why))


def _solve(
    nodes: Iterable[str], constraints: list[tuple[str, str, float, str]]
) -> dict[str, float]:
    """The least columns that keep every constraint: the longest path (Bellman–Ford)."""
    column = dict.fromkeys(nodes, 0.0)
    edges = [(a, b, gap, why) for a, b, gap, why in constraints if a in column and b in column]
    before: dict[str, tuple[str, float, str]] = {}
    last = ""
    for _ in range(len(column) + 1):
        changed = False
        for a, b, gap, why in edges:
            if column[a] + gap > column[b] + 1e-9:
                column[b] = column[a] + gap
                before[b] = (a, gap, why)
                changed = True
                last = b
        if not changed:
            low = min(column.values(), default=0.0)
            return {n: c - low for n, c in column.items()}
    cycle = _cycle_of(before, last)
    reasons = list(
        dict.fromkeys(
            why.removeprefix(EXACT).removeprefix(TABLE_WAY) for _, _, _, why in cycle if why
        )
    )
    raise LayoutError(
        "Villkoren för kolumnerna går inte ihop: " + "; ".join(reasons[:4]) + ".", cycle
    )


def _cycle_of(
    before: dict[str, tuple[str, float, str]], last: str
) -> list[tuple[str, str, float, str]]:
    """The constraints that contradict each other: a cycle that only grows."""
    node = last
    for _ in range(len(before) + 1):
        node = before.get(node, (node, 0.0, ""))[0]
    found: list[tuple[str, str, float, str]] = []
    seen: set[str] = set()
    while node not in seen:
        seen.add(node)
        previous, gap, why = before.get(node, (node, 0.0, ""))
        found.append((previous, node, gap, why))
        node = previous
    return found


def _solve_loose(
    nodes: Iterable[str], constraints: list[tuple[str, str, float, str]]
) -> dict[str, float]:
    """Solve, and where transitions make a loop that cannot close exactly, let the loop's
    transitions be longer, one at a time (a triangle or a loop over the turntable)."""
    placed = list(nodes)
    rules = list(constraints)
    for _ in range(20):
        try:
            return _solve(placed, rules)
        except LayoutError as error:
            loose = [edge for edge in error.cycle if edge[3].startswith(EXACT)]
            if not loose:
                raise
            loose.sort(key=lambda edge: not edge[3].startswith(EXACT + TABLE_WAY))
            rules.remove(loose[0])
    return _solve(placed, rules)


@dataclass
class _Plan:
    """The rows and sections, before the columns."""

    shape: Shape
    rows: int
    node_row: dict[str, int]
    sections: list[Section]
    interpolated: set[str]


def _sections(shape: Shape) -> _Plan:
    """The transitions: wherever a strand goes from one row to another between two of its
    fixed nodes. The soft nodes on the way are placed along it."""
    node_row: dict[str, int] = {}
    for node, strand_id in shape.owner.items():
        row = shape.strands[strand_id].row
        if row is not None:
            node_row[node] = row
    sections: list[Section] = []
    interpolated: set[str] = set()
    for strand in shape.strands:
        if strand.kind != "track" or not strand.pieces:
            continue
        nodes = strand.nodes
        last = len(nodes) - 1
        fixed = [
            i
            for i, n in enumerate(nodes)
            if i in (0, last)
            or (n in node_row and (_holds(shape, n) or shape.owner[n] != strand.id))
        ]
        for i, j in pairwise(fixed):
            a, b = nodes[i], nodes[j]
            if a not in node_row or b not in node_row:
                raise LayoutError(
                    f"Spårbitarna {', '.join(strand.pieces[i:j])} hänger inte ihop med något spår."
                )
            if node_row[a] == node_row[b]:
                for between in nodes[i + 1 : j]:
                    node_row.setdefault(between, node_row[a])
                continue
            sections.append(Section(strand.id, a, b, strand.pieces[i:j], nodes[i : j + 1]))
            interpolated.update(nodes[i + 1 : j])
    for node in interpolated:
        node_row.pop(node, None)
    rows = max((s.row for s in shape.strands if s.row is not None), default=0) + 1
    return _Plan(shape, rows, node_row, sections, interpolated)


def _junction(shape: Shape, node: str) -> bool:
    return shape.graph.node_type.get(node) in JUNCTIONS


@dataclass
class _Layout:
    plan: _Plan
    angle: PanelAngle
    shortened: bool
    column: dict[str, float]
    cells: dict[str, Cell] = field(default_factory=dict)
    paths: dict[str, list[Cell]] = field(default_factory=dict)


def _columns(plan: _Plan, angle: PanelAngle, shortened: bool, reach: _Reach) -> _Layout:
    shape = plan.shape
    graph = shape.graph
    k = SIDEWAYS[angle]
    rules = _Constraints()
    in_section = {p for s in plan.sections for p in s.pieces}
    placed = set(plan.node_row)
    # Pieces on a row: at least a block between hard nodes, a cell otherwise.
    for piece in graph.pieces:
        if piece in shape.stall or piece in in_section:
            continue
        west = _west(graph, shape.eastward, piece)
        east = _east(graph, shape.eastward, piece)
        if west not in placed or east not in placed:
            continue
        gap = BLOCK if _hard(shape, west) and _hard(shape, east) else 1
        if graph.node_type.get(west) == NodeType.TURNTABLE:
            gap = max(gap, 2)
        if graph.node_type.get(east) == NodeType.TURNTABLE:
            gap = max(gap, 2)
        rules.at_least(west, east, gap, f"spårbiten {piece}")
    # Transitions.
    for section in plan.sections:
        a, b = section.start, section.end
        if a not in placed or b not in placed:
            raise LayoutError(f"Spårbitarna {', '.join(section.pieces)} hänger inte ihop.")
        rows = abs(plan.node_row[a] - plan.node_row[b])
        gap = k * rows
        first = section.pieces[0] if section.pieces else None
        west_first = first is not None and _west(graph, shape.eastward, first) == a
        west, east = (a, b) if west_first else (b, a)
        exact = _exact(plan, section)
        tables = {t.node for t in shape.model.turntables}
        why = f"övergång {', '.join(section.pieces)}"
        if a in tables or b in tables:
            why = TABLE_WAY + why
        if rows == 0:
            rules.at_least(west, east, max(BLOCK, len(section.pieces)), why)
        elif exact:
            rules.exactly(west, east, gap, why)
        else:
            rules.at_least(west, east, gap + 1, why)
    # Station tracks.
    least = SHORTENED if shortened else STATION_TRACK
    for track in shape.model.station_tracks:
        ends = _track_ends(shape, plan, track.pieces)
        if ends is not None:
            rules.at_least(ends[0], ends[1], least, f"stationsspåret {track.id}")
    # Transitions that pass other rows.
    _passing(plan, reach, k, rules)
    # Signals in the same position.
    alignment = _alignment(shape, plan)
    try:
        column = _solve(placed, rules.items + alignment)
    except LayoutError:
        column = _solve_loose(placed, rules.items)
    keep = rules.items + alignment
    for _ in range(24):
        found = _Layout(plan, angle, shortened, column)
        extra = _separate(found)
        if not extra:
            return found
        keep = keep + extra
        try:
            column = _solve(placed, keep)
        except LayoutError:
            keep = [rule for rule in keep if rule[3] != "signaler i linje"]
            column = _solve_loose(placed, keep)
    return _Layout(plan, angle, shortened, column)


def _track_ends(shape: Shape, plan: _Plan, pieces: Sequence[str]) -> tuple[str, str] | None:
    graph = shape.graph
    nodes = [
        n
        for p in pieces
        if p in graph.pieces
        for n in (_west(graph, shape.eastward, p), _east(graph, shape.eastward, p))
        if n in plan.node_row
    ]
    if len(set(nodes)) < 2:
        return None
    rows = [plan.node_row[n] for n in nodes]
    row = max(set(rows), key=rows.count)
    nodes = [n for n in nodes if plan.node_row[n] == row]
    westmost = [n for n in nodes if not any(m != n and n in _after(shape, m) for m in nodes)]
    eastmost = [n for n in nodes if not any(m != n and m in _after(shape, n) for m in nodes)]
    if not westmost or not eastmost or westmost[0] == eastmost[0]:
        return None
    return westmost[0], eastmost[0]


def _after(shape: Shape, node: str) -> frozenset[str]:
    if shape.reach is None:
        shape.reach = _Reach(shape)
    return shape.reach.reach(node)


def _diagonal(plan: _Plan, section: Section) -> tuple[str, str, bool]:
    """Where a transition's diagonal is: at the end where the strand leaves another, so that it
    runs on its own row into its own nodes; away from the turntable, which a track reaches on
    the table's row; at a connector's junction end. Returns the diagonal's node, the far node,
    and whether the diagonal's node is west."""
    shape = plan.shape
    graph = shape.graph
    a, b = section.start, section.end
    a_west = _west(graph, shape.eastward, section.pieces[0]) == a
    tables = {t.node for t in shape.model.turntables}
    own_a = shape.owner.get(a) == section.strand
    own_b = shape.owner.get(b) == section.strand
    if b in tables and a not in tables:
        at_a = True
    elif a in tables:
        at_a = False
    elif own_b != own_a:
        at_a = own_b
    else:
        at_a = _junction(shape, a) or not _junction(shape, b)
    return (a, b, a_west) if at_a else (b, a, not a_west)


def _exact(plan: _Plan, section: Section) -> bool:
    """A crossover between two junctions, which the strand only passes: exactly 3 or 6 cells
    per row (§3.3)."""
    shape = plan.shape
    a, b = section.start, section.end
    tables = {t.node for t in shape.model.turntables}
    return (
        shape.owner.get(a) != section.strand
        and shape.owner.get(b) != section.strand
        and (_junction(shape, a) or a in tables)
        and (_junction(shape, b) or b in tables)
    )


def _real_x(shape: Shape, pieces: Iterable[str]) -> tuple[float, float] | None:
    xs = [p[0] for piece in pieces for p in shape.shape_of(piece)]
    return (min(xs), max(xs)) if xs and shape.geometry else None


def _row_anchors(plan: _Plan, strand: Strand) -> tuple[str, str] | None:
    """The westmost and eastmost nodes a strand places on its row."""
    placed = [n for n in strand.nodes if plan.node_row.get(n) == strand.row]
    own = [n for n in placed if plan.shape.owner.get(n) == strand.id]
    if not own:
        return None
    return own[0], own[-1]


def _passing(plan: _Plan, reach: _Reach, k: int, rules: _Constraints) -> None:
    """A transition crosses the rows between its ends and runs along the row it goes to: the
    strands there must end before it or start after it. Strands that share a row keep their
    order from west to east, a block apart."""
    shape = plan.shape
    rows: dict[int, list[Strand]] = defaultdict(list)
    for strand in shape.strands:
        if strand.row is not None and _row_anchors(plan, strand) is not None:
            rows[strand.row].append(strand)
    for row, strands in rows.items():
        ordered = sorted(strands, key=lambda st: _sort_x(plan, reach, st))
        for one, other in pairwise(ordered):
            first, second = _row_anchors(plan, one), _row_anchors(plan, other)
            assert first is not None and second is not None
            gap = TABLE_SPAN if "table" in (one.kind, other.kind) else BLOCK
            rules.at_least(first[1], second[0], gap, f"två spår på rad {row + 1}")
    for section in plan.sections:
        d, h, d_west = _diagonal(plan, section)
        rd, rh = plan.node_row[d], plan.node_row[h]
        span = abs(rh - rd)
        mine = {section.strand, shape.owner.get(d), shape.owner.get(h)}
        real = _real_x(shape, section.pieces)
        step = 1 if rh > rd else -1
        for row in range(rd + step, rh + step, step):
            sideways = k * abs(row - rd)
            target = row == rh
            for other in rows.get(row, []):
                if other.id in mine:
                    continue
                ends = _row_anchors(plan, other)
                assert ends is not None
                west_end, east_end = ends
                if real is not None and other.id in shape.extent:
                    o0, o1 = shape.extent[other.id]
                    west = (o0 + o1) < (real[0] + real[1])
                else:
                    middle = sum(reach.rank(n) for n in section.nodes) / len(section.nodes)
                    west = _sort_x(plan, reach, other)[0] < middle
                why = "ett spår vid en övergång"
                if d_west:
                    if west:
                        limit = k * span - 1 if target else sideways - 1
                        rules.at_most(d, east_end, limit, why)
                    elif target:
                        rules.at_least(h, west_end, 1, why)
                    else:
                        rules.at_least(d, west_end, sideways + 1, why)
                elif west:
                    if target:
                        rules.at_least(east_end, h, 1, why)
                    else:
                        rules.at_least(east_end, d, sideways + 1, why)
                else:
                    limit = -(k * span) + 1 if target else -sideways + 1
                    rules.at_least(d, west_end, limit, why)


def _sort_x(plan: _Plan, reach: _Reach, strand: Strand) -> tuple[float, int]:
    """Where a strand lies east–west: the middle of its reach in the drawing, else of its
    nodes' places along the pieces."""
    shape = plan.shape
    if strand.id in shape.extent:
        a, b = shape.extent[strand.id]
        return ((a + b) / 2, strand.id)
    ranks = [reach.rank(n) for n in strand.nodes]
    return (sum(ranks) / len(ranks), strand.id)


def _alignment(shape: Shape, plan: _Plan) -> list[tuple[str, str, float, str]]:
    """Signals facing the same way at the same place in the drawing, on different rows."""
    if not shape.geometry:
        return []
    graph = shape.graph
    found: list[tuple[str, str, float, str]] = []
    facing: dict[bool, list[tuple[float, str, int]]] = defaultdict(list)
    for signal in shape.model.signals:
        node = signal.node
        if (
            node not in plan.node_row
            or node not in shape.real
            or signal.approach not in graph.pieces
        ):
            continue
        east = _east(graph, shape.eastward, signal.approach) == node
        facing[east].append((shape.real[node][0], node, plan.node_row[node]))
    for group in facing.values():
        group.sort()
        for (x1, n1, r1), (x2, n2, r2) in pairwise(group):
            if abs(x2 - x1) <= ALIGN_MM and r1 != r2 and n1 != n2:
                found.append((n1, n2, 0.0, "signaler i linje"))
                found.append((n2, n1, 0.0, "signaler i linje"))
    return found


def _paths(layout: _Layout) -> dict[str, list[Cell]]:
    """Every piece's way over the grid, from its start to its end."""
    plan = layout.plan
    shape = plan.shape
    graph = shape.graph
    k = SIDEWAYS[layout.angle]
    column = layout.column
    cells: dict[str, Cell] = {
        n: (column[n], ROW * plan.node_row[n]) for n in plan.node_row if n in column
    }
    paths: dict[str, list[Cell]] = {}
    for section in plan.sections:
        a, b = section.start, section.end
        pa, pb = cells[a], cells[b]
        rows = abs(pb[1] - pa[1]) / ROW
        sideways = k * rows
        d, _, _ = _diagonal(plan, section)
        direction = 1.0 if pb[0] >= pa[0] else -1.0
        if d == a:
            corner = (pa[0] + direction * sideways, pb[1])
        else:
            corner = (pb[0] - direction * sideways, pa[1])
        way = [pa, corner, pb]
        if math.dist(corner, pb) < 1e-9 or math.dist(corner, pa) < 1e-9 or rows == 0:
            way = [pa, pb]
        total = sum(math.dist(p, q) for p, q in pairwise(way))
        lengths = [max(length(graph.pieces[p]), 1.0) for p in section.pieces]
        weights = lengths if shape.geometry else [1.0] * len(lengths)
        marks = [0.0]
        for w in weights:
            marks.append(marks[-1] + w)
        scale = total / marks[-1] if marks[-1] else 0.0
        positions = [m * scale for m in marks]
        for node, at in zip(section.nodes[1:-1], positions[1:-1], strict=True):
            cells[node] = _along(way, at)
        for i, piece in enumerate(section.pieces):
            part = _part(way, positions[i], positions[i + 1])
            if graph.pieces[piece].start != section.nodes[i]:
                part.reverse()
            paths[piece] = part
    for piece in graph.pieces:
        if piece in paths or piece in shape.stall:
            continue
        p = graph.pieces[piece]
        if p.start in cells and p.end in cells:
            paths[piece] = [cells[p.start], cells[p.end]]
    # The turntable's stall tracks, as rays from its rim.
    for table in shape.model.turntables:
        if table.node not in cells:
            continue
        centre = cells[table.node]
        for track in table.tracks:
            if track.piece not in shape.stall:
                continue
            angle = math.radians(track.angle)
            dx, dy = math.cos(angle), -math.sin(angle)
            rim = (centre[0] + dx * TABLE_RIM, centre[1] + dy * TABLE_RIM)
            end = (centre[0] + dx * TABLE_RAY, centre[1] + dy * TABLE_RAY)
            ray = graph.pieces[track.piece]
            rim = (round(rim[0], 3), round(rim[1], 3))
            end = (round(end[0], 3), round(end[1], 3))
            paths[track.piece] = [rim, end] if ray.start == table.node else [end, rim]
            other = ray.end if ray.start == table.node else ray.start
            cells[other] = end
    layout.cells = cells
    layout.paths = paths
    return paths


def _along(way: Sequence[Cell], at: float) -> Cell:
    gone = 0.0
    for p, q in pairwise(way):
        d = math.dist(p, q)
        if gone + d >= at - 1e-9 and d > 0:
            f = (at - gone) / d
            return (round(p[0] + (q[0] - p[0]) * f, 4), round(p[1] + (q[1] - p[1]) * f, 4))
        gone += d
    return way[-1]


def _part(way: Sequence[Cell], start: float, end: float) -> list[Cell]:
    found = [_along(way, start)]
    gone = 0.0
    for p, q in pairwise(way):
        gone += math.dist(p, q)
        if start + 1e-9 < gone < end - 1e-9:
            found.append(q)
    found.append(_along(way, end))
    return found


def _separate(layout: _Layout) -> list[tuple[str, str, float, str]]:
    """Where two tracks still meet off a node, the one further west must be done before the
    other begins: a constraint for the next round."""
    plan = layout.plan
    shape = plan.shape
    graph = shape.graph
    paths = _paths(layout)
    cells = layout.cells
    ends = {p.id: (p.start, p.end) for p in shape.model.pieces}
    found = hits(paths, ends, cells)
    if not found:
        return []
    item: dict[str, tuple[str, str]] = {}
    for section in plan.sections:
        a, b = section.start, section.end
        a_west = _west(graph, shape.eastward, section.pieces[0]) == a
        for piece in section.pieces:
            item[piece] = (a, b) if a_west else (b, a)
    column = layout.column
    extra: list[tuple[str, str, float, str]] = []
    for hit in found:
        if hit.kind == "through":
            continue
        pair = []
        for piece in (hit.a, hit.b):
            if piece in item:
                pair.append(item[piece])
            elif piece in graph.pieces and piece not in shape.stall:
                pair.append(
                    (_west(graph, shape.eastward, piece), _east(graph, shape.eastward, piece))
                )
        if len(pair) != 2 or set(pair[0]) & set(pair[1]):
            continue
        first, second = sorted(
            pair, key=lambda span: (column.get(span[0], 0.0), column.get(span[1], 0.0))
        )
        if first[1] in column and second[0] in column:
            extra.append((first[1], second[0], 1.0, "två spår som möts"))
    return extra


# --- Labels -----------------------------------------------------------------------------


def _signals(layout: _Layout, cells: dict[str, Cell]) -> list[PanelSignal]:
    plan = layout.plan
    shape = plan.shape
    graph = shape.graph
    outside = _double_track(layout, cells)
    found: list[PanelSignal] = []
    at_node: dict[str, list[str]] = defaultdict(list)
    for signal in shape.model.signals:
        at_node[signal.node].append(signal.name)
    for signal in shape.model.signals:
        node = signal.node
        if node not in cells or signal.approach not in graph.pieces:
            continue
        cell = cells[node]
        toward = _toward(layout, signal.approach, node)
        east = toward[0] > 1e-9 or (abs(toward[0]) <= 1e-9 and toward[1] < 0)
        side: LabelSide = outside.get(signal.name) or ("over" if east else "under")
        if signal.type == SignalType.STOP_LAMP:
            # Beside the track, to the left of the direction it applies in (TKL45).
            left = (toward[1], -toward[0])
            symbol = (cell[0] + left[0] * 0.6, cell[1] + left[1] * 0.6)
        else:
            shift = 0.5 if len(at_node[node]) > 1 else 0.0
            symbol = (cell[0] - toward[0] * shift, cell[1] - toward[1] * shift)
        label_y = cell[1] - 1.1 if side == "over" else cell[1] + 1.5
        label = (symbol[0], label_y)
        real, real_toward = _real_signal(shape, signal.approach, node)
        found.append(
            PanelSignal(
                name=signal.name,
                type=signal.type,
                node=node,
                cell=cell,
                toward=_round(toward),
                symbol=_round(symbol),
                label=_round(label),
                side=side,
                planned=signal.planned,
                real=real,
                real_toward=real_toward,
            )
        )
    return found


def _round(point: tuple[float, float]) -> Cell:
    return (round(point[0], 3), round(point[1], 3))


def _toward(layout: _Layout, approach: str, node: str) -> tuple[float, float]:
    """The direction of travel past a signal, on the panel: along its approach piece, into the
    node."""
    path = layout.paths.get(approach)
    if not path or len(path) < 2:
        return (1.0, 0.0)
    piece = layout.plan.shape.graph.pieces[approach]
    if piece.end == node:
        a, b = path[-2], path[-1]
    else:
        a, b = path[1], path[0]
    return _unit(*_sub(b, a))


def _real_signal(shape: Shape, approach: str, node: str) -> tuple[Point | None, Point | None]:
    piece = shape.graph.pieces[approach]
    points = piece.geometry
    if len(points) < 2:
        return None, None
    if piece.end == node:
        a, b = points[-2], points[-1]
    else:
        a, b = points[1], points[0]
    return b, _round(_unit(*_sub(b, a)))


def _double_track(layout: _Layout, cells: dict[str, Cell]) -> dict[str, LabelSide]:
    """On a line with double track the signals stand outside the pair (TKL43): the upper
    track's above and the lower track's below, whichever way they face. A double track is two
    line exits at the same end, on rows next to each other, whose tracks do not join there."""
    shape = layout.plan.shape
    exits = [e for e in shape.model.line_exits if e.node in cells and e.node in shape.owner]
    found: dict[str, LabelSide] = {}
    paired: set[str] = set()
    for i, one in enumerate(exits):
        for other in exits[i + 1 :]:
            if one.id in paired or other.id in paired:
                continue
            a, b = cells[one.node], cells[other.node]
            if abs(abs(a[1] - b[1]) - ROW) > 1e-6 or abs(a[0] - b[0]) > 1e-6:
                continue
            first = shape.strands[shape.owner[one.node]]
            second = shape.strands[shape.owner[other.node]]
            if _joined(shape, first, second):
                continue
            paired.update({one.id, other.id})
            upper, lower = (one, other) if a[1] < b[1] else (other, one)
            for name in upper.signals:
                found[name] = "over"
            for name in lower.signals:
                found[name] = "under"
    return found


def _joined(shape: Shape, one: Strand, other: Strand) -> bool:
    """One strand leaves the other."""
    for strand, there in ((one, other), (other, one)):
        for end, attached in ((strand.west, strand.attached[0]), (strand.east, strand.attached[1])):
            if attached and shape.owner.get(end) == there.id:
                return True
    return False


def _switches(
    layout: _Layout, cells: dict[str, Cell], paths: dict[str, list[Cell]]
) -> list[PanelSwitch]:
    shape = layout.plan.shape
    graph = shape.graph
    found: list[PanelSwitch] = []
    for switch in shape.model.switches:
        if switch.node not in cells:
            continue
        cell = cells[switch.node]
        below = False
        leg = switch.diverging if switch.type == SwitchType.ORDINARY else None
        if leg and leg in paths:
            path = paths[leg]
            far = path[-1] if graph.pieces[leg].start == switch.node else path[0]
            below = far[1] > cell[1]
        label = (cell[0], cell[1] - 1.1) if below or leg is None else (cell[0], cell[1] + 1.5)
        if switch.type in SLIP_TYPES:
            label = (cell[0], cell[1] - 1.1)
            number = "/".join(p.number for p in switch.parts) or switch.number
        else:
            number = switch.number
        found.append(
            PanelSwitch(
                number=number if switch.type in SLIP_TYPES else switch.number,
                type=switch.type,
                node=switch.node,
                cell=cell,
                real=shape.real.get(switch.node),
                trunk=switch.trunk,
                straight=switch.straight,
                diverging=switch.diverging,
                pieces=[p for p in graph.touching.get(switch.node, []) if p in graph.pieces]
                if switch.type in SLIP_TYPES
                else [],
                label=_round(label),
                laid=graph.laid_by_tkl(switch),
            )
        )
    return found


def _labels(
    layout: _Layout, cells: dict[str, Cell], paths: dict[str, list[Cell]]
) -> list[PanelLabel]:
    """Exits at the row's end, stop points and buffer stops by their names."""
    shape = layout.plan.shape
    graph = shape.graph
    found: list[PanelLabel] = []
    exits = {e.node: e.id for e in shape.model.line_exits}
    for node in shape.model.nodes:
        if node.id not in cells:
            continue
        cell = cells[node.id]
        pieces = graph.touching.get(node.id, [])
        if node.type == NodeType.LINE_EXIT:
            west = bool(pieces) and _west(graph, shape.eastward, pieces[0]) == node.id
            at = (cell[0] - 0.6, cell[1] + 0.35) if west else (cell[0] + 0.6, cell[1] + 0.35)
            found.append(
                PanelLabel(
                    text=exits.get(node.id, node.id),
                    kind="exit",
                    cell=_round(at),
                    anchor="end" if west else "start",
                    real=shape.real.get(node.id),
                )
            )
        elif node.type in (NodeType.BUFFER_STOP, NodeType.STOP_POINT) and len(pieces) == 1:
            west = _west(graph, shape.eastward, pieces[0]) == node.id
            if pieces[0] in shape.stall:
                path = paths[pieces[0]]
                end = path[0] if graph.pieces[pieces[0]].start == node.id else path[-1]
                other = path[-1] if end is path[0] else path[0]
                direction = _unit(*_sub(end, other))
                at = (end[0] + direction[0] * 0.8, end[1] + direction[1] * 0.8 + 0.3)
                anchor = (
                    "start" if direction[0] > 0.3 else "end" if direction[0] < -0.3 else "middle"
                )
            else:
                at = (cell[0] - 0.6, cell[1] + 0.35) if west else (cell[0] + 0.6, cell[1] + 0.35)
                anchor = "end" if west else "start"
            found.append(
                PanelLabel(
                    text=node.id,
                    kind="point",
                    cell=_round(at),
                    anchor=anchor,  # type: ignore[arg-type]
                    real=shape.real.get(node.id),
                )
            )
    return found


def _track_names(layout: _Layout, cells: dict[str, Cell]) -> list[PanelTrackName]:
    """The track number mid-track, with the train number's box right after it (§3.4)."""
    shape = layout.plan.shape
    found: list[PanelTrackName] = []
    for track in shape.model.station_tracks:
        ends = _track_ends(shape, layout.plan, track.pieces)
        if ends is None:
            points = [
                cells[n]
                for p in track.pieces
                if p in shape.graph.pieces
                for n in (shape.graph.pieces[p].start, shape.graph.pieces[p].end)
                if n in cells
            ]
            if not points:
                continue
            mid = (sum(p[0] for p in points) / len(points), min(p[1] for p in points))
        else:
            a, b = cells[ends[0]], cells[ends[1]]
            mid = ((a[0] + b[0]) / 2, a[1])
        found.append(
            PanelTrackName(
                name=track.id,
                cell=_round((mid[0] - 0.3, mid[1] - 0.6)),
                train_number=_round((mid[0] + 0.3, mid[1] - 1.4)),
                real=_real_mid(shape, track.pieces),
            )
        )
    return found


def _real_mid(shape: Shape, pieces: Sequence[str]) -> Point | None:
    points = [
        p
        for piece in pieces
        if piece in shape.graph.pieces
        for p in shape.graph.pieces[piece].geometry
    ]
    if not points:
        return None
    return points[len(points) // 2]


def _fields(width: float, paths: dict[str, list[Cell]], cells: dict[str, Cell]) -> list[PanelField]:
    """Cuts across the station where no transition is under way and no node stands, each field
    at most a screen wide (STD-03)."""
    if width <= FITS[0]:
        return []
    busy: set[int] = set()
    for path in paths.values():
        for p, q in pairwise(path):
            if abs(p[1] - q[1]) > 1e-9:
                for c in range(math.floor(min(p[0], q[0])), math.ceil(max(p[0], q[0])) + 1):
                    busy.add(c)
    for cell in cells.values():
        for c in (math.floor(cell[0]) - 1, math.floor(cell[0]), math.ceil(cell[0])):
            busy.add(c)
    found: list[PanelField] = []
    start = 0.0
    number = 1
    while width - start > FITS[0]:
        limit = int(start + FITS[0])
        cut = next((c for c in range(limit, int(start) + FITS[0] // 2, -1) if c not in busy), limit)
        found.append(PanelField(name=f"Fält {number}", start=start, end=float(cut)))
        start = float(cut)
        number += 1
    found.append(PanelField(name=f"Fält {number}", start=start, end=width))
    return found


# --- The whole --------------------------------------------------------------------------


def _try(shape: Shape, plan: _Plan, angle: PanelAngle, shortened: bool, reach: _Reach) -> Panel:
    layout = _columns(plan, angle, shortened, reach)
    paths = _paths(layout)
    return _panel(layout, paths, layout.cells)


def _panel(layout: _Layout, paths: dict[str, list[Cell]], cells: dict[str, Cell]) -> Panel:
    plan = layout.plan
    shape = plan.shape
    xs = [p[0] for path in paths.values() for p in path] + [c[0] for c in cells.values()]
    ys = [p[1] for path in paths.values() for p in path] + [c[1] for c in cells.values()]
    if not xs:
        raise LayoutError("Stationen har inga spårbitar att lägga ut.")
    dx = MARGIN[0] - min(xs)
    dy = MARGIN[1] - min(ys)

    def moved(p: Cell) -> Cell:
        return (round(p[0] + dx, 4), round(p[1] + dy, 4))

    paths = {k: [moved(p) for p in v] for k, v in paths.items()}
    cells = {k: moved(v) for k, v in cells.items()}
    width = math.ceil(max(xs) + dx + MARGIN[0])
    height = math.ceil(max(ys) + dy + MARGIN[1])
    layout.paths = paths
    lines = [
        PanelLine(
            piece=piece.id,
            track=piece.track,
            cells=paths[piece.id],
            real=list(piece.geometry),
            free=piece.id in shape.stall,
        )
        for piece in shape.model.pieces
        if piece.id in paths
    ]
    nodes = [
        PanelNode(id=n.id, type=n.type, cell=cells[n.id], real=shape.real.get(n.id))
        for n in shape.model.nodes
        if n.id in cells
    ]
    tables = []
    for table in shape.model.turntables:
        if table.node not in cells:
            continue
        tables.append(
            PanelTable(
                id=table.id,
                node=table.node,
                cell=cells[table.node],
                radius=TABLE_RIM,
                real=shape.real.get(table.node) or _table_centre(shape, table.node),
                real_radius=(table.diameter / 2) if table.diameter else None,
            )
        )
    every = [p for piece in shape.model.pieces for p in piece.geometry]
    box = None
    if every:
        x0, y0 = min(p[0] for p in every), min(p[1] for p in every)
        box = (x0, y0, max(p[0] for p in every) - x0, max(p[1] for p in every) - y0)
    return Panel(
        source=PanelSource.ENGINE,
        width=width,
        height=height,
        cell=(CELL_PX, CELL_PX),
        angle=layout.angle,
        rows=plan.rows,
        shortened=layout.shortened,
        fields=_fields(width, paths, cells),
        lines=lines,
        nodes=nodes,
        switches=_switches(layout, cells, paths),
        signals=_signals(layout, cells),
        labels=_labels(layout, cells, paths),
        track_names=_track_names(layout, cells),
        tables=tables,
        real_box=box,
    )


def _table_centre(shape: Shape, node: str) -> Point | None:
    """The turntable's centre in the drawing: where its tracks point to."""
    graph = shape.graph
    points = []
    for piece in graph.touching.get(node, []):
        geometry = graph.pieces[piece].geometry
        if len(geometry) >= 2:
            points.append(geometry[0] if graph.pieces[piece].start == node else geometry[-1])
    if not points:
        return None
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def prepare(model: StationModel) -> tuple[Shape, _Plan, _Reach]:
    """The strands in their rows, ready for the columns."""
    found = shape(model)
    reach = _Reach(found)
    found.reach = reach
    rowed = [s for s in found.strands if _needs_row(found, s)]
    if not rowed:
        raise LayoutError("Stationen har inga spår med egna noder att lägga ut.")
    order, relations = _order(found, rowed, reach)
    rows = _rows(found, order, reach, relations)
    plan = _sections(found)
    plan.rows = rows
    return found, plan, reach


def fits(panel: Panel) -> bool:
    """On the panel screen, 1920 × 1080."""
    return panel.width <= FITS[0] and panel.height <= FITS[1]


def lay_out(
    model: StationModel, angle: PanelAngle | None = None, shortened: bool | None = None
) -> Panel:
    """The engine's panel for the station (STD-02, STD-03, STD-11).

    Without arguments the engine chooses: flat if the station fits on the screen, else 45°,
    else 45° with the station tracks shortened, and if it still does not fit, fields. An angle
    or shortening may be asked for, to compare the variants.
    """
    found, plan, reach = prepare(model)
    if angle is not None:
        return _checked(found, _try(found, plan, angle, bool(shortened), reach))
    flat = _try(found, plan, PanelAngle.FLAT, False, reach)
    if fits(flat):
        return _checked(found, flat)
    steep = _try(found, plan, PanelAngle.STEEP, False, reach)
    if fits(steep) or shortened is False:
        return _checked(found, steep)
    return _checked(found, _try(found, plan, PanelAngle.STEEP, True, reach))


def _checked(shape: Shape, panel: Panel) -> Panel:
    """The engine never hands over a panel that breaks the grid's rules (STD-26)."""
    faults = panel_hits(panel, shape.model)
    if faults:
        raise LayoutError(
            "Motorn kan inte lägga ut stationen utan att spår möts fel: "
            + " ".join(describe(h) for h in faults[:3])
        )
    return panel


def panel_hits(panel: Panel, model: StationModel) -> list[Hit]:
    """Where the panel's tracks meet other than at a node they share."""
    lines = {line.piece: line.cells for line in panel.lines}
    ends = {p.id: (p.start, p.end) for p in model.pieces}
    nodes = {node.id: node.cell for node in panel.nodes}
    return hits(lines, ends, nodes)
