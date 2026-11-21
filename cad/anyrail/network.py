"""The AnyRail layout's track as a network of legs and nodes, with the interpretation rules of
trainmeet-cad-anyrail-import.md applied in order (2. Tolkningsregler, 3. Geometrifilter):

1. Track is a part about as wide as the measure's track width (rule 1); AnyRail's own file says
   which parts are track. Parts outside the work area are side drawings and are left out.
2. Every track part becomes legs between nodes: a flex is one leg; a turnout is its straight leg
   and its diverging leg from the points, where its line and arc meet (1. Filformatet, Växel); a
   crossing part is four legs from where its lines cross. AnyRail's connections join endpoints.
3. A loop, two tracks bound by a tight arc (turning at least LOOP_TURN, tighter than the tight
   radius), is taken away, and its tracks end there (rule 4, AR4).
4. A sharp corner (tighter than SHARP_FRACTION of the tight radius, turning at least
   SHARP_TURN) is where a stall's back wall is drawn as track: the track is cut there, and a
   piece between two such corners, the wall, is taken away (rule 7).
5. A turntable is found on its pit's circles, the thin arcs around one centre. Track wholly in
   the pit through its centre is the bridge and is taken away; a track ending in the pit is a
   radial track, ending there (rule 7).
6. A flex curve tighter than the tight radius is drawn again as an even cubic with AnyRail's own
   end directions and handles a third of the chord (3.2), and the move is reported.
7. A short flex piece (under the backward length) whose chord points back against its ends'
   directions is an overlap in the drawing: it is taken away and its neighbours are joined in
   the middle (3.1). A flex drawn on top of other track, within the lateral error for nearly
   all its length, is that track drawn twice: it is taken away, and the owner confirms it.
8. Free ends are joined (rule 3): at most the join distance apart, pointing at each other
   (scalar product under JOIN_OPPOSED), and less than the lateral error apart sideways; the best
   pairs first, on the lateral error plus the angle error, both ends moved to the middle.
9. A flex that parts without a switch becomes an assumed switch (rule 5): a free end at a node,
   or on another track, heading along it.
10. Tracks that cross once, at least the crossing distance from a node, get a crossing; twice is
   a warning; under the crossing angle the crossing is flagged (rule 6).
11. Track that does not hang together with the largest part, nor through the turntable, is
   loose and left out (rule 8).
12. Every node is read: an end, a joint, a switch (AnyRail's own turnout keeps its id; three
   ends meeting are an assumed switch: the trunk the leg pointing most away from the other two,
   the straight the straightest), a crossing, or two switches back to back where four ends meet
   (rule 5), set BACK_TO_BACK apart.

Everything is in the drawing's mm, y down. The order of every loop is fixed by ids and places,
so the same file with the same measures always gives the same network (AR5).
"""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from cad import curves
from cad.anyrail import shapes
from cad.anyrail.reader import Element, Layout, Part
from cad.curves import Arc, Line, Seg
from contracts.cad import AnyRailMeasures, CheckKind
from contracts.station_model import Point

SAMPLE_STEP: Final = 10.0
VERTEX: Final = 2.0
"""mm: element ends this close are the same point in a part."""
LOOP_TURN: Final = math.radians(150)
SHARP_FRACTION: Final = 0.15
SHARP_TURN: Final = math.radians(45)
SHARP_LENGTH: Final = 200.0
JOIN_OPPOSED: Final = -0.97
CONNECTED: Final = 0.05
"""mm: ends this close are one, joined without a word (AnyRail's own file leaves its
connections to the end of the file, and the reader joins them by place)."""
BACKWARD_COS: Final = -0.5
"""A backward piece's chord points more than 120° from both its ends' directions."""
SPLIT_ANGLE: Final = math.radians(30)
"""A free end heading within this of a track it lies on parts from it (rule 5)."""
BACK_TO_BACK: Final = 1.5
"""mm between two switches back to back, whose points AnyRail draws in one place."""
PIT_SHARE: Final = 1.1
"""A pit with one circle reaches this share of its radius."""
PIT_SIDES: Final = (150.0, 1000.0)
"""mm: a pit drawn as a polygon is between these across."""


@dataclass
class Leg:
    id: int
    a: int
    b: int
    segs: list[Seg]
    refs: tuple[str, ...]
    flex: bool
    role: str = "flex"
    curve: tuple[Point, Point, Point, Point] | None = None
    """A single-Bézier flex's control points, for 3.2."""

    @property
    def length(self) -> float:
        return curves.path_length(self.segs)


@dataclass
class Node:
    id: int
    at: Point
    end: Literal["", "loop", "buffer", "pit"] = ""
    """A track end the import made: where a loop was taken away (loop, an ordinary track end,
    AR4), where a corner or a bridge was (buffer), or a radial track at the turntable (pit)."""


@dataclass
class Turnout:
    """AnyRail's own turnout part: its points node and its two legs from there."""

    part: str
    type: str
    node: int
    straight: int
    diverging: int
    side: Literal["left", "right", "y"]
    radius: float | None
    angle: float | None


@dataclass(frozen=True)
class Finding:
    """Something to show the owner: a check item, in the drawing's mm."""

    key: str
    kind: CheckKind
    at: Point
    title: str
    text: str
    refs: tuple[str, ...] = ()
    assumed: bool = False
    """Yellow: the owner confirms it in the module."""


@dataclass
class Switch:
    """A switch read from the network: AnyRail's own turnout, or assumed (rule 5)."""

    node: int
    trunk: int
    straight: int
    diverging: int
    part: str | None
    side: Literal["left", "right", "y"]
    radius: float | None
    angle: float | None

    @property
    def assumed(self) -> bool:
        return self.part is None


@dataclass
class Counts:
    gaps: int = 0
    overlaps: int = 0
    backward: int = 0
    smoothed: int = 0
    loops: int = 0
    bridges: int = 0
    walls: int = 0
    loose: int = 0
    side: int = 0
    doubled: int = 0
    arcs: int = 0
    arcs_other_way: int = 0


@dataclass
class Network:
    measures: AnyRailMeasures
    nodes: dict[int, Node] = field(default_factory=dict)
    legs: dict[int, Leg] = field(default_factory=dict)
    turnouts: list[Turnout] = field(default_factory=list)
    crossing_nodes: set[int] = field(default_factory=set)
    switches: list[Switch] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    left_out: list[list[Point]] = field(default_factory=list)
    counts: Counts = field(default_factory=Counts)
    pits: list[tuple[Point, float]] = field(default_factory=list)
    doubled: list[list[Point]] = field(default_factory=list)
    """The tracks drawn twice that were taken away: the kept one is yellow along them."""
    moved: dict[int, float] = field(default_factory=dict)
    """Switches (by id()) whose points moved to a board's edge, and how far, in mm."""
    next_node: int = 1
    next_leg: int = 1

    # --- Looking up ------------------------------------------------------------------------

    def on(self, node: int) -> list[int]:
        """The legs at the node, a loop twice."""
        found: list[int] = []
        for leg in self.legs.values():
            if leg.a == node:
                found.append(leg.id)
            if leg.b == node:
                found.append(leg.id)
        return found

    def degree(self, node: int) -> int:
        return len(self.on(node))

    def away(self, leg: int, node: int) -> list[Seg]:
        """The leg's segments running away from the node."""
        found = self.legs[leg]
        return list(found.segs) if found.a == node else curves.reverse_path(found.segs)

    def leaving(self, leg: int, node: int) -> float:
        """The heading leaving the node along the leg."""
        return curves.start_heading(self.away(leg, node)[0])

    def outward(self, node: int) -> float:
        """At a free end: the heading out of the track, continuing it."""
        leg = self.on(node)[0]
        return curves.wrap(self.leaving(leg, node) + math.pi)

    def other(self, leg: int, node: int) -> int:
        found = self.legs[leg]
        return found.b if found.a == node else found.a

    def adjacency(self) -> dict[int, list[int]]:
        found: dict[int, list[int]] = defaultdict(list)
        for leg in self.legs.values():
            found[leg.a].append(leg.id)
            found[leg.b].append(leg.id)
        return found

    # --- Changing ------------------------------------------------------------------------

    def new_node(self, at: Point, end: Literal["", "loop", "buffer", "pit"] = "") -> int:
        made = self.next_node
        self.next_node += 1
        self.nodes[made] = Node(made, at, end)
        return made

    def add_leg(
        self,
        a: int,
        b: int,
        segs: list[Seg],
        refs: tuple[str, ...],
        *,
        flex: bool,
        role: str = "flex",
        curve: tuple[Point, Point, Point, Point] | None = None,
    ) -> Leg:
        made = Leg(self.next_leg, a, b, segs, refs, flex, role, curve)
        self.next_leg += 1
        self.legs[made.id] = made
        return made

    def remove_leg(self, leg: int, *, shown: bool = True) -> None:
        found = self.legs.pop(leg)
        if shown:
            self.left_out.append(_points(found.segs))

    def move_end(self, leg: int, node: int, to: Point) -> None:
        """The leg's end at the node moved to a point: the leg turned and scaled about its other
        end, so a LINE stays a LINE and an ARC an ARC."""
        found = self.legs[leg]
        if found.a == found.b:
            return
        start = to if found.a == node else found.segs[0].start
        end = to if found.b == node else found.segs[-1].end
        if (
            math.dist(start, found.segs[0].start) < 1e-9
            and math.dist(end, found.segs[-1].end) < 1e-9
        ):
            return
        found.segs = curves.reshaped(found.segs, start, end)
        found.curve = None

    def merge(self, keep: int, drop: int, at: Point | None = None) -> None:
        """Two nodes become one, at a point (the kept node's own by default)."""
        if keep == drop:
            return
        where = at if at is not None else self.nodes[keep].at
        for leg in list(self.legs.values()):
            for end in ("a", "b"):
                if getattr(leg, end) in (keep, drop):
                    node = getattr(leg, end)
                    if math.dist(self._end_at(leg, end), where) > 1e-9:
                        self.move_end(leg.id, node, where)
        for leg in self.legs.values():
            if leg.a == drop:
                leg.a = keep
            if leg.b == drop:
                leg.b = keep
        kept = self.nodes[keep]
        kept.at = where
        if self.nodes[drop].end and not kept.end:
            kept.end = self.nodes[drop].end
        del self.nodes[drop]

    @staticmethod
    def _end_at(leg: Leg, end: str) -> Point:
        return leg.segs[0].start if end == "a" else leg.segs[-1].end

    def split(self, leg_id: int, s: float) -> int:
        """The leg cut s mm from its start: a new node there, the first part keeps the id."""
        leg = self.legs[leg_id]
        first, second = curves.split_path(leg.segs, s)
        at = first[-1].end
        node = self.new_node(at)
        old_b = leg.b
        leg.segs = first
        leg.b = node
        leg.curve = None
        made = self.add_leg(node, old_b, second, leg.refs, flex=leg.flex, role=leg.role)
        # A switch on the old end keeps its leg: the part that still reaches it.
        for sw in self.switches:
            if sw.node == old_b:
                for role in ("trunk", "straight", "diverging"):
                    if getattr(sw, role) == leg_id:
                        setattr(sw, role, made.id)
        for t in self.turnouts:
            if t.node == old_b:
                for role in ("straight", "diverging"):
                    if getattr(t, role) == leg_id:
                        setattr(t, role, made.id)
        return node

    def drop_empty(self) -> None:
        used = {leg.a for leg in self.legs.values()} | {leg.b for leg in self.legs.values()}
        for node in [n for n in self.nodes if n not in used]:
            del self.nodes[node]

    def finding(
        self,
        kind: CheckKind,
        key: str,
        at: Point,
        title: str,
        text: str,
        refs: Iterable[str] = (),
        *,
        assumed: bool = False,
    ) -> None:
        self.findings.append(
            Finding(
                key[:120],
                kind,
                (round(at[0], 1), round(at[1], 1)),
                title,
                text,
                tuple(refs),
                assumed,
            )
        )


def _points(segs: Sequence[Seg]) -> list[Point]:
    return [(round(x, 1), round(y, 1)) for x, y in curves.sample_path(segs, 20.0)]


def _mm(value: float) -> str:
    return f"{value:.0f}"


def _decimal(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def turn(segs: Sequence[Seg]) -> float:
    """How much a chain turns, radians, right positive, through every joint."""
    total = sum(curves.turn_of(s) for s in segs)
    for before, after in itertools.pairwise(segs):
        total += curves.wrap(curves.start_heading(after) - curves.end_heading(before))
    return total


def min_radius(segs: Sequence[Seg]) -> float:
    found = [s.radius for s in segs if isinstance(s, Arc) and curves.length(s) > 0.5]
    return min(found) if found else math.inf


# --- 1–2. The parts as legs ---------------------------------------------------------------


def is_track(part: Part, measures: AnyRailMeasures) -> bool:
    if part.track is not None:
        return part.track
    width = measures.track_width
    return any(0.75 * width <= e.width <= 1.5 * width for e in part.elements)


def is_thin(part: Part, measures: AnyRailMeasures) -> bool:
    if part.track is not None:
        return not part.track
    return bool(part.elements) and all(e.width < 0.5 * measures.track_width for e in part.elements)


def element_segs(element: Element, counts: Counts | None = None) -> list[Seg]:
    if element.kind == "line":
        a, b = element.points
        return [Line(a, b)] if math.dist(a, b) > 1e-6 else []
    if element.kind == "arc":
        a, b = element.points
        found = shapes.arc(a, b, element.direction or 0.0)
        if found is None:
            return [Line(a, b)] if math.dist(a, b) > 1e-6 else []
        if counts is not None and element.radius:
            counts.arcs += 1
            naive = shapes.arc_without_direction(a, b, element.radius)
            if naive is not None and not shapes.bulges_same(found, naive):
                counts.arcs_other_way += 1
        return [found]
    return shapes.bezier(element.points)


def _outside(part: Part, layout: Layout) -> bool:
    points = [p for e in part.elements for p in e.points]
    if not points or layout.length <= 0 or layout.width <= 0:
        return False
    return all(
        not (-1 <= p[0] <= layout.length + 1 and -1 <= p[1] <= layout.width + 1) for p in points
    )


def build(layout: Layout, measures: AnyRailMeasures) -> Network:
    """The track parts as legs, joined by AnyRail's connections."""
    net = Network(measures)
    net.next_node = max(layout.endpoints, default=0) + 1
    owner: dict[int, str] = {}
    for part in layout.parts:
        if part.hidden or not is_track(part, measures):
            continue
        if _outside(part, layout):
            net.counts.side += 1
            continue
        _legs_of(net, part, layout)
        for nr in part.endpoints:
            owner[nr] = part.id
    for a, b in sorted(layout.connections):
        if a in net.nodes and b in net.nodes and a != b:
            keep, drop = min(a, b), max(a, b)
            net.merge(keep, drop)
    net.drop_empty()
    _connect_by_place(net)
    return net


def _connect_by_place(net: Network) -> None:
    """Ends in one place that point at each other are connected, as AnyRail connects them (its
    own file keeps its connections apart, at the end; the reader joins them by place)."""
    ends = free_ends(net)
    points = open_points(net)
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for n in ends:
        at = net.nodes[n].at
        grid[(round(at[0]), round(at[1]))].append(n)
    for n in ends:
        if n not in net.nodes:
            continue
        at = net.nodes[n].at
        for dx, dy in itertools.product((-1, 0, 1), repeat=2):
            for m in grid.get((round(at[0]) + dx, round(at[1]) + dy), []):
                if m <= n or m not in net.nodes or n not in net.nodes:
                    continue
                if math.dist(net.nodes[m].at, at) > CONNECTED:
                    continue
                hn = net.leaving(points[n], n) + math.pi if n in points else net.outward(n)
                hm = net.leaving(points[m], m) + math.pi if m in points else net.outward(m)
                if curves.dot(curves.unit(hn), curves.unit(hm)) < JOIN_OPPOSED:
                    net.merge(n, m)


def _legs_of(net: Network, part: Part, layout: Layout) -> None:
    ends = [(nr, layout.endpoints[nr].at) for nr in part.endpoints]
    chains = [s for s in (element_segs(e, net.counts) for e in part.elements) if s]
    if not chains or not ends:
        return
    for nr, at in ends:
        if nr not in net.nodes:
            net.nodes[nr] = Node(nr, at)
    if "crossing" in part.type.lower() and len(chains) == 2 and len(ends) == 4:
        _crossing_part(net, part, chains, ends)
        return
    # The element ends and the endpoints as the part's vertices.
    vertices: list[tuple[Point, int | None]] = [(at, nr) for nr, at in ends]

    def vertex(p: Point) -> int:
        for k, (q, _) in enumerate(vertices):
            if math.dist(p, q) <= VERTEX:
                return k
        vertices.append((p, None))
        return len(vertices) - 1

    edges = [(vertex(c[0].start), vertex(c[-1].end), c) for c in chains]
    degree: dict[int, int] = defaultdict(int)
    for a, b, _ in edges:
        degree[a] += 1
        degree[b] += 1
    for k, (_, number) in enumerate(vertices):
        if number is not None:
            degree[k] += 1
    node_of: dict[int, int] = {}
    for k, (at, number) in enumerate(vertices):
        if number is not None:
            node_of[k] = number
        elif degree[k] >= 3:
            node_of[k] = net.new_node(at)
    used: set[int] = set()
    made: list[Leg] = []
    by_vertex: dict[int, list[int]] = defaultdict(list)
    for position, (a, b, _) in enumerate(edges):
        by_vertex[a].append(position)
        by_vertex[b].append(position)
    for start in sorted(node_of):
        for first in by_vertex[start]:
            if first in used:
                continue
            path: list[Seg] = []
            here = start
            index: int | None = first
            while index is not None and index not in used:
                used.add(index)
                a, b, chain = edges[index]
                if a == here:
                    path += chain
                    here = b
                else:
                    path += curves.reverse_path(chain)
                    here = a
                if here in node_of:
                    break
                index = next((i for i in by_vertex[here] if i not in used), None)
            if here not in node_of:
                continue
            a_node, b_node = node_of[start], node_of[here]
            segs = _fitted(path, net.nodes[a_node].at, net.nodes[b_node].at)
            if curves.path_length(segs) < 0.5:
                continue
            curve = None
            if len(part.elements) == 1 and part.elements[0].kind == "bezier":
                c = part.elements[0].points
                curve = (
                    (c[0], c[1], c[2], c[3])
                    if math.dist(c[0], segs[0].start) < VERTEX
                    else (
                        c[3],
                        c[2],
                        c[1],
                        c[0],
                    )
                )
            made.append(
                net.add_leg(a_node, b_node, segs, (part.id,), flex=_flex(part), curve=curve)
            )
    if "turnout" in part.type.lower() and made:
        _turnout(net, part, made)


def _flex(part: Part) -> bool:
    return part.type.lower() == "flex" or (part.article is not None and part.type == "Flex")


def _fitted(path: list[Seg], a: Point, b: Point) -> list[Seg]:
    if math.dist(path[0].start, a) < 1e-6 and math.dist(path[-1].end, b) < 1e-6:
        return path
    if math.dist(a, b) < 1e-6:
        return path
    return curves.reshaped(path, a, b)


def _crossing_part(
    net: Network, part: Part, chains: list[list[Seg]], ends: list[tuple[int, Point]]
) -> None:
    """A crossing part: its two lines cross; four legs from there to its endpoints."""
    first, second = chains[0], chains[1]
    hit = _intersections(_points_of(first, 2.0), _points_of(second, 2.0))
    if not hit:
        return
    at = hit[0][0]
    centre = net.new_node(at)
    net.crossing_nodes.add(centre)
    for nr, p in ends:
        net.add_leg(centre, nr, [Line(at, p)], (part.id,), flex=False, role="crossing")


def _turnout(net: Network, part: Part, made: list[Leg]) -> None:
    """AnyRail's turnout: the points are where its legs meet; the straight leg the straighter."""
    counts: dict[int, int] = defaultdict(int)
    for leg in made:
        counts[leg.a] += 1
        counts[leg.b] += 1
    points = max(counts, key=lambda n: (counts[n], -n))
    legs = [leg for leg in made if points in (leg.a, leg.b) and leg.a != leg.b]
    if len(legs) < 2:
        return
    for leg in legs:
        if leg.a != points:  # from the points, so that a split keeps the id there
            leg.a, leg.b, leg.segs = leg.b, leg.a, curves.reverse_path(leg.segs)
    if len(legs) > 2:
        # A lead before the points (a Y switch's common straight) is the trunk: it points most
        # away from the two others.
        heads = {leg.id: curves.unit(curves.start_heading(leg.segs[0])) for leg in legs}
        trunk = min(
            legs,
            key=lambda leg: (
                sum(curves.dot(heads[leg.id], heads[o.id]) for o in legs if o is not leg),
                leg.id,
            ),
        )
        trunk.role = "trunk"
        legs = [leg for leg in legs if leg is not trunk]
    legs.sort(key=lambda leg: (abs(turn(leg.segs)), leg.id))
    straight, diverging = legs[0], legs[1]
    straight.role, diverging.role = "straight", "diverging"
    away = net.away(diverging.id, points)
    bend = turn(away)
    bend_straight = turn(net.away(straight.id, points))
    side: Literal["left", "right", "y"] = "right" if bend > 0 else "left"
    if abs(bend_straight) > math.radians(1) and bend_straight * bend < 0:
        side = "y"
    arcs = [s for s in away if isinstance(s, Arc)]
    net.turnouts.append(
        Turnout(
            part=part.id,
            type=part.type,
            node=points,
            straight=straight.id,
            diverging=diverging.id,
            side=side,
            radius=arcs[0].radius if arcs else None,
            angle=math.degrees(abs(sum(curves.turn_of(s) for s in arcs))) if arcs else None,
        )
    )


def _points_of(segs: Sequence[Seg], step: float) -> list[Point]:
    return curves.sample_path(segs, step)


def _intersections(p: Sequence[Point], q: Sequence[Point]) -> list[tuple[Point, float, float]]:
    """Where two polylines cross: the point, and how far along each, mm."""
    found: list[tuple[Point, float, float]] = []
    along_p = 0.0
    for a, b in itertools.pairwise(p):
        along_q = 0.0
        for c, d in itertools.pairwise(q):
            hit = _segment_hit(a, b, c, d)
            if hit is not None:
                t, u = hit
                found.append(
                    (
                        (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t),
                        along_p + t * math.dist(a, b),
                        along_q + u * math.dist(c, d),
                    )
                )
            along_q += math.dist(c, d)
        along_p += math.dist(a, b)
    return found


def _segment_hit(a: Point, b: Point, c: Point, d: Point) -> tuple[float, float] | None:
    r = curves.sub(b, a)
    s = curves.sub(d, c)
    denominator = curves.cross(r, s)
    if abs(denominator) < 1e-12:
        return None
    qp = curves.sub(c, a)
    t = curves.cross(qp, s) / denominator
    u = curves.cross(qp, r) / denominator
    if 0 <= t < 1 and 0 <= u < 1:
        return t, u
    return None


# --- 3–5. Loops, corners and the turntable --------------------------------------------------


def remove_loops(net: Network) -> None:
    """Rule 4, AR4: two tracks bound by a tight arc; the arc goes, the tracks end there."""
    tight = net.measures.tight_radius
    for leg in sorted(net.legs.values(), key=lambda x: x.id):
        if not leg.flex or leg.a == leg.b:
            continue
        # A loop turns back: its ends head opposite ways (a backward piece's do not).
        back = abs(
            curves.wrap(curves.end_heading(leg.segs[-1]) - curves.start_heading(leg.segs[0]))
        )
        if back < LOOP_TURN or min_radius(leg.segs) >= tight:
            continue
        ends = [leg.a, leg.b]
        net.remove_leg(leg.id)
        for node in ends:
            if node in net.nodes:
                net.nodes[node].end = "loop"
        net.counts.loops += 1
        at = curves.path_point(leg.segs, leg.length / 2)
        net.finding(
            CheckKind.REMOVED,
            f"removed:loop:{'+'.join(leg.refs)}",
            at,
            "Öglan togs bort",
            "Två spår var bundna med en tvär båge. Bågen togs bort och spåren slutar där, som "
            "vanliga spårändar.",
            leg.refs,
        )
    net.drop_empty()


def remove_corners(net: Network) -> None:
    """Rule 7: a stall's back wall drawn as track, cut at its sharp corners and taken away."""
    sharp = SHARP_FRACTION * net.measures.tight_radius
    cut: set[int] = set()
    for leg in sorted(net.legs.values(), key=lambda x: x.id):
        if not leg.flex or leg.length > SHARP_LENGTH:
            continue
        bend = abs(
            curves.wrap(curves.end_heading(leg.segs[-1]) - curves.start_heading(leg.segs[0]))
        )
        if min_radius(leg.segs) >= sharp or bend < SHARP_TURN:
            continue
        cut.update((leg.a, leg.b))
        net.remove_leg(leg.id)
    if not cut:
        return
    for node in cut:
        if node in net.nodes:
            net.nodes[node].end = "buffer"
    for leg in sorted(net.legs.values(), key=lambda x: x.id):
        if leg.a in cut and leg.b in cut and net.degree(leg.a) == 1 and net.degree(leg.b) == 1:
            net.remove_leg(leg.id)
            net.counts.walls += 1
            net.finding(
                CheckKind.REMOVED,
                f"removed:wall:{'+'.join(leg.refs)}",
                curves.path_point(leg.segs, leg.length / 2),
                "Stallets bakvägg togs bort",
                "Ett spår gick fram och tillbaka med skarpa hörn: bakväggen var ritad som spår. "
                "Spåren delades vid hörnen och väggen togs bort.",
                leg.refs,
            )
    net.drop_empty()


def turntable(net: Network, thin: Sequence[Part]) -> None:
    """Rule 7: the pit on its circles; the bridge through its centre goes, radial tracks end in
    it."""
    circles: dict[tuple[int, int, int], list[float]] = defaultdict(list)
    for part in thin:
        for element in part.elements:
            if element.kind != "arc":
                continue
            seg = shapes.arc(element.points[0], element.points[1], element.direction or 0.0)
            if not isinstance(seg, Arc):
                continue
            key = (round(seg.center[0] / 5), round(seg.center[1] / 5), round(seg.radius))
            circles[key].append(curves.sweep(seg))
    rings: dict[tuple[int, int], list[float]] = defaultdict(list)
    for (cx, cy, radius), sweeps in circles.items():
        if sum(sweeps) >= math.radians(300) and radius >= 3 * net.measures.track_width:
            rings[(cx, cy)].append(float(radius))
    for (cx, cy), radii in sorted(rings.items()):
        centre = (cx * 5.0, cy * 5.0)
        reach = (min(radii) + max(radii)) / 2 if len(radii) > 1 else PIT_SHARE * radii[0]
        _pit(net, centre, reach, joined=False)
        net.pits.append((centre, reach))
    # AnyRail's own file draws the pit as a surface: a closed, squarish polygon.
    for part in thin:
        lines = [e for e in part.elements if e.kind == "line"]
        if len(lines) < 4 or len(lines) != len(part.elements):
            continue
        corners = [e.points[0] for e in lines]
        if math.dist(lines[-1].points[1], corners[0]) > 1.0:
            continue
        xs, ys = [p[0] for p in corners], [p[1] for p in corners]
        span = (max(xs) - min(xs), max(ys) - min(ys))
        if not (PIT_SIDES[0] <= min(span) and max(span) <= PIT_SIDES[1]) or max(span) > 1.3 * min(
            span
        ):
            continue
        centre = (sum(xs) / len(xs), sum(ys) / len(ys))
        reach = PIT_SHARE * max(span) / 2
        if _pit(net, centre, reach, joined=True):
            net.pits.append((centre, reach))


def _continues(net: Network, node: int) -> bool:
    """Does a track go on from the node: another leg there, or another end in the same place?"""
    if net.degree(node) >= 2:
        return True
    at = net.nodes[node].at
    return any(n != node and math.dist(other.at, at) <= 1.0 for n, other in net.nodes.items())


def _pit(net: Network, centre: Point, reach: float, *, joined: bool) -> bool:
    """The bridge through the pit's centre goes; True when there was one. joined: only a bridge
    that tracks continue from at both ends (a pit drawn as a surface could be a building)."""
    near = net.measures.track_width
    found = False
    for leg in sorted(net.legs.values(), key=lambda x: x.id):
        points = curves.sample_path(leg.segs, SAMPLE_STEP)
        inside = [math.dist(p, centre) <= reach for p in points]
        if joined and not (_continues(net, leg.a) and _continues(net, leg.b)):
            continue
        if all(inside) and min(math.dist(p, centre) for p in points) <= near:
            found = True
            ends = (leg.a, leg.b)
            net.remove_leg(leg.id)
            net.counts.bridges += 1
            net.finding(
                CheckKind.REMOVED,
                f"removed:bridge:{'+'.join(leg.refs)}",
                centre,
                "Vändskivans bro togs bort",
                "Spåret gick genom vändskivans centrum: det är bron, inte ett spår.",
                leg.refs,
            )
            for node in ends:
                if node in net.nodes:
                    net.nodes[node].end = "pit"
    net.drop_empty()
    if not found and joined:
        return False
    for kept in net.nodes.values():
        if math.dist(kept.at, centre) <= reach and net.degree(kept.id) == 1:
            kept.end = "pit"
    return found


# --- 6–8. Smoothing, backward pieces and joins ----------------------------------------------


def smooth(net: Network) -> None:
    """3.2: a flex curve tighter than the tight radius drawn again as an even cubic."""
    tight = net.measures.tight_radius
    for leg in sorted(net.legs.values(), key=lambda x: x.id):
        if not leg.flex or leg.curve is None:
            continue
        if shapes.bezier_min_radius(leg.curve) >= tight:
            continue
        a, b = net.nodes[leg.a], net.nodes[leg.b]
        h0 = shapes.bezier_heading(leg.curve, 0.0)
        h1 = shapes.bezier_heading(leg.curve, 1.0)
        even = shapes.even_cubic(a.at, h0, b.at, h1)
        new = shapes.bezier(even)
        if not new:
            continue
        moved = max(curves.distance(new, p) for p in curves.sample_path(leg.segs, SAMPLE_STEP))
        leg.segs = _fitted(new, a.at, b.at)
        leg.curve = None
        net.counts.smoothed += 1
        net.finding(
            CheckKind.DRAWING_FIX,
            f"drawing_fix:smooth:{'+'.join(leg.refs)}:{moved:.0f}",
            curves.path_point(leg.segs, leg.length / 2),
            f"Flexbågen ritades om, flytt {_decimal(moved)} mm",
            f"Bågen var snävare än {_mm(tight)} mm. Den ritades om som en jämn kurva med "
            "AnyRails egna ändriktningar.",
            leg.refs,
        )


def remove_backward(net: Network) -> None:
    """3.1: a short flex whose chord points back is an overlap; it goes, the neighbours meet."""
    limit = net.measures.backward_length
    for leg in sorted(net.legs.values(), key=lambda x: x.id):
        if leg.id not in net.legs or not leg.flex or leg.length >= limit or leg.a == leg.b:
            continue
        if net.degree(leg.a) < 2 or net.degree(leg.b) < 2:
            continue
        a, b = net.nodes[leg.a].at, net.nodes[leg.b].at
        chord = curves.sub(b, a)
        size = math.hypot(*chord)
        if size < 1e-6:
            continue
        direction = (chord[0] / size, chord[1] / size)
        start = curves.unit(curves.start_heading(leg.segs[0]))
        end = curves.unit(curves.end_heading(leg.segs[-1]))
        if (
            curves.dot(direction, start) >= BACKWARD_COS
            or curves.dot(direction, end) >= BACKWARD_COS
        ):
            continue
        before = {x for x in net.on(leg.a) if x != leg.id}
        after = {x for x in net.on(leg.b) if x != leg.id}
        if not before or not after or before & after:
            continue
        middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        net.remove_leg(leg.id)
        net.merge(min(leg.a, leg.b), max(leg.a, leg.b), middle)
        net.counts.backward += 1
        net.finding(
            CheckKind.DRAWING_FIX,
            f"drawing_fix:backward:{'+'.join(leg.refs)}:{size:.0f}",
            middle,
            f"Bakåtbit på {_decimal(size / 10)} cm togs bort",
            "En kort flexbit pekade bakåt: ett överlapp i ritningen. Grannarna kopplades ihop "
            "och kortades till mittpunkten.",
            leg.refs,
        )
    net.drop_empty()


# --- 7b. One track drawn twice ---------------------------------------------------------------

DOUBLED_SHARE: Final = 0.9
"""Of a flex's length within the lateral error of other track: the flex is that track drawn
again."""
DOUBLED_LENGTH: Final = 100.0
"""mm: a shorter flex beside a track is a piece at a gap or a switch, not a track drawn twice."""
NEAR_CELL: Final = 100.0
"""mm: the grid the nearness is looked up in, at least the largest lateral error."""


def doubled(net: Network) -> None:
    """One track drawn twice: a flex that lies within the lateral error of other track for nearly
    all its length (DOUBLED_SHARE), both its ends too, is that track drawn again. Of two drawn on
    top of each other the one with fewer joined ends goes, then the shorter; the other stays and
    holds both ids. Its ends must be free or where the kept track ends too, so that nothing
    comes loose. The owner confirms it: the kept track is yellow in its module until then. Two
    tracks that only cross twice, at an angle, are not this: they part between the crossings
    (rule 6)."""
    m = net.measures
    adjacency = net.adjacency()
    samples = {leg.id: curves.sample_path(leg.segs, SAMPLE_STEP) for leg in net.legs.values()}
    grid: dict[tuple[int, int], list[tuple[int, Point, Point]]] = defaultdict(list)
    for leg_id in sorted(samples):
        for a, b in itertools.pairwise(samples[leg_id]):
            for cell in _near_cells(a, b):
                grid[cell].append((leg_id, a, b))
    gone: set[int] = set()

    def nearest(p: Point, skip: set[int]) -> int | None:
        cell = (math.floor(p[0] / NEAR_CELL), math.floor(p[1] / NEAR_CELL))
        best: tuple[float, int] | None = None
        for other, a, b in grid.get(cell, []):
            if other in skip or other in gone:
                continue
            apart = _to_segment(p, a, b)
            if apart <= m.lateral and (best is None or (apart, other) < best):
                best = (apart, other)
        return best[1] if best is not None else None

    def joined(leg: Leg) -> int:
        return sum(1 for n in (leg.a, leg.b) if len(adjacency.get(n, [])) > 1)

    flex = [leg for leg in net.legs.values() if leg.flex and leg.a != leg.b]
    for leg in sorted(flex, key=lambda x: (joined(x), x.length, -x.id)):
        points = samples[leg.id]
        if leg.length < DOUBLED_LENGTH or len(points) < 2:
            continue
        # Its own leg and those joined at its ends lie beside it there: they are not its twin.
        skip = {leg.id, *adjacency.get(leg.a, []), *adjacency.get(leg.b, [])}
        found = [nearest(p, skip) for p in points]
        twins = {x for x in found if x is not None}
        if not twins or found[0] is None or found[-1] is None:
            continue
        if sum(1 for x in found if x is not None) < DOUBLED_SHARE * len(points):
            continue
        own = set(leg.refs)
        if any(own & set(net.legs[x].refs) for x in twins):
            continue  # the legs of one part
        # Each end is free, or where the kept track ends too: nothing comes loose.
        meets = [net.nodes[n].at for x in twins for n in (net.legs[x].a, net.legs[x].b)]
        if any(
            any(x != leg.id and x not in gone for x in adjacency.get(n, []))
            and all(math.dist(net.nodes[n].at, q) > m.lateral for q in meets)
            for n in (leg.a, leg.b)
        ):
            continue
        gone.add(leg.id)
        for x in sorted(twins):
            net.legs[x].refs = tuple(sorted({*net.legs[x].refs, *own}))
        net.remove_leg(leg.id)
        net.doubled.append(points)
        net.counts.doubled += 1
        refs = tuple(sorted(own))
        net.finding(
            CheckKind.DRAWING_FIX,
            f"drawing_fix:doubled:{'+'.join(refs)}",
            points[len(points) // 2],
            "Två spår ritade ovanpå varandra lästes som ett",
            f"Ett spår på {_decimal(leg.length / 1000, 2)} m låg inom {_decimal(m.lateral)} mm "
            "från ett annat. Importen behöll det ena och tog bort det andra. Bekräfta det i "
            "modulen.",
            refs,
            assumed=True,
        )
    net.drop_empty()


def _near_cells(a: Point, b: Point) -> Iterator[tuple[int, int]]:
    """The cells within one cell of a segment: a point there is looked up in its own cell."""
    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    for cx in range(math.floor(x0 / NEAR_CELL) - 1, math.floor(x1 / NEAR_CELL) + 2):
        for cy in range(math.floor(y0 / NEAR_CELL) - 1, math.floor(y1 / NEAR_CELL) + 2):
            yield (cx, cy)


def _to_segment(p: Point, a: Point, b: Point) -> float:
    d = curves.sub(b, a)
    size = d[0] * d[0] + d[1] * d[1]
    if size < 1e-12:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / size))
    return math.dist(p, (a[0] + d[0] * t, a[1] + d[1] * t))


def open_points(net: Network) -> dict[int, int]:
    """AnyRail turnouts whose points nothing joins yet: node -> the straight leg."""
    adjacency = net.adjacency()
    found: dict[int, int] = {}
    for t in net.turnouts:
        if t.straight not in net.legs or t.diverging not in net.legs:
            continue
        node = net.legs[t.straight].a
        if net.legs[t.diverging].a == node and sorted(adjacency.get(node, [])) == sorted(
            (t.straight, t.diverging)
        ):
            found[node] = t.straight
    return found


def free_ends(net: Network) -> list[int]:
    """Track ends that nothing joins: a track's free end, or a turnout's points without its
    trunk."""
    adjacency = net.adjacency()
    ends = {n for n, node in net.nodes.items() if len(adjacency.get(n, [])) == 1 and not node.end}
    return sorted(ends | set(open_points(net)))


def join(net: Network) -> None:
    """Rule 3: free ends joined, the best pairs first, both moved to the middle."""
    m = net.measures
    ends = free_ends(net)
    points = open_points(net)
    heads = {
        n: curves.unit(net.leaving(points[n], n) + math.pi if n in points else net.outward(n))
        for n in ends
    }
    pairs: list[tuple[float, int, int, float, float]] = []
    for i, j in itertools.combinations(ends, 2):
        p, q = net.nodes[i].at, net.nodes[j].at
        apart = math.dist(p, q)
        if apart > m.join_distance:
            continue
        hi, hj = heads[i], heads[j]
        opposed = curves.dot(hi, hj)
        if opposed >= JOIN_OPPOSED:
            continue
        d = curves.sub(q, p)
        lateral = (abs(curves.cross(hi, d)) + abs(curves.cross(hj, d))) / 2
        if lateral >= m.lateral:
            continue
        angle = math.degrees(math.pi - math.acos(max(-1.0, min(1.0, opposed))))
        ahead = curves.dot(hi, d)
        pairs.append((lateral + angle, i, j, apart, ahead))
    taken: set[int] = set()
    for _, i, j, apart, ahead in sorted(pairs):
        if i in taken or j in taken:
            continue
        taken.update((i, j))
        p, q = net.nodes[i].at, net.nodes[j].at
        middle = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        refs = tuple(sorted({r for n in (i, j) for leg in net.on(n) for r in net.legs[leg].refs}))
        net.merge(i, j, middle)
        if apart < CONNECTED:
            continue  # ends in one place: joined as AnyRail's own connection would
        overlap = ahead < 0
        if overlap:
            net.counts.overlaps += 1
        else:
            net.counts.gaps += 1
        what = "Överlapp" if overlap else "Glapp"
        net.finding(
            CheckKind.DRAWING_FIX,
            f"drawing_fix:{'overlap' if overlap else 'gap'}:{'+'.join(refs)}:{apart:.0f}",
            middle,
            f"{what} på {_decimal(apart)} mm sammanfogat",
            "Två spårändar möttes inte i ritningen. De pekade mot varandra och flyttades till "
            "mittpunkten.",
            refs,
        )


# --- 9. Flex that parts without a switch -------------------------------------------------


def parting(net: Network) -> None:
    """Rule 5: a free end at a node, or on another track, heading along it: the track parts there
    without a switch, and the node becomes an assumed switch later."""
    m = net.measures
    reach = max(m.lateral, VERTEX)
    for end in free_ends(net):
        if end not in net.nodes or net.degree(end) != 1:
            continue
        at = net.nodes[end].at
        inward = net.leaving(net.on(end)[0], end)
        own = net.on(end)[0]
        best: tuple[float, int, float] | None = None
        for node in sorted(net.nodes):
            if node == end or net.degree(node) < 2 or net.nodes[node].end:
                continue
            apart = math.dist(net.nodes[node].at, at)
            if apart > reach:
                continue
            heading = any(_along(inward, net.leaving(leg, node)) for leg in net.on(node))
            if heading and (best is None or apart < best[0]):
                best = (apart, node, 0.0)
        if best is not None:
            net.merge(best[1], end)
            continue
        for leg in sorted(net.legs.values(), key=lambda x: x.id):
            if leg.id == own:
                continue
            s, off = curves.project_path(leg.segs, at)
            if off > reach or s < 1.0 or s > leg.length - 1.0:
                continue
            tangent = curves.path_heading(leg.segs, s)
            if not (_along(inward, tangent) or _along(inward, tangent + math.pi)):
                continue
            if best is None or off < best[0]:
                best = (off, leg.id, s)
        if best is not None:
            node = net.split(best[1], best[2])
            net.merge(node, end)


def touching(net: Network) -> None:
    """Rule 5: two tracks that run through one point side by side, where AnyRail joined each
    pair of ends but not the four, are four ends meeting: they become one node (two switches back
    to back, read later). Tracks through one point at an angle cross there instead (rule 6)."""
    adjacency = net.adjacency()
    plain = sorted(n for n, legs in adjacency.items() if len(legs) == 2 and not net.nodes[n].end)
    for i, j in itertools.combinations(plain, 2):
        if i not in net.nodes or j not in net.nodes:
            continue
        if math.dist(net.nodes[i].at, net.nodes[j].at) > 1.0:
            continue
        hi = net.leaving(net.on(i)[0], i)
        hj = net.leaving(net.on(j)[0], j)
        apart = abs(curves.wrap(hi - hj))
        apart = min(apart, math.pi - apart)
        if math.degrees(apart) < net.measures.crossing_angle:
            net.merge(i, j)


def _along(a: float, b: float) -> bool:
    return abs(curves.wrap(a - b)) <= SPLIT_ANGLE


# --- 10. Crossings -------------------------------------------------------------------------

CELL: Final = 100.0
ON_TOP: Final = math.radians(0.5)
"""Tracks that touch at less than this lie on top of each other: no crossing."""


def strands(net: Network) -> list[list[int]]:
    """The tracks as strands: legs in a row through plain joints (two legs, no crossing)."""
    adjacency = net.adjacency()
    plain = {n for n, legs in adjacency.items() if len(legs) == 2 and n not in net.crossing_nodes}
    seen: set[int] = set()
    found: list[list[int]] = []
    for start in sorted(net.legs):
        if start in seen:
            continue
        seen.add(start)
        chain = [start]
        for forward in (True, False):
            leg = net.legs[start]
            node = leg.b if forward else leg.a
            here = start
            while node in plain:
                nxt = next((x for x in adjacency[node] if x != here), None)
                if nxt is None or nxt in seen:
                    break
                seen.add(nxt)
                if forward:
                    chain.append(nxt)
                else:
                    chain.insert(0, nxt)
                node = net.other(nxt, node)
                here = nxt
        found.append(chain)
    return found


def crossings(net: Network) -> None:
    """Rule 6: tracks that cross once, at least the crossing distance from a switch or an end,
    cross at a crossing; twice is a warning, no crossing."""
    m = net.measures
    found_strands = strands(net)
    adjacency = net.adjacency()
    polylines: dict[int, list[Point]] = {}
    ends_of: dict[int, set[int]] = {}
    for k, chain in enumerate(found_strands):
        points: list[Point] = []
        nodes: set[int] = set()
        for leg_id in chain:
            leg = net.legs[leg_id]
            sampled = curves.sample_path(leg.segs, 5.0)
            if points and math.dist(points[-1], sampled[-1]) < math.dist(points[-1], sampled[0]):
                sampled.reverse()
            points += sampled if not points else sampled[1:]
            nodes.update((leg.a, leg.b))
        polylines[k] = points
        ends_of[k] = {n for n in nodes if len(adjacency.get(n, [])) != 2 or n in net.crossing_nodes}
    grid: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for k, points in polylines.items():
        for i, (a, b) in enumerate(itertools.pairwise(points)):
            for cell in _cells(a, b):
                grid[cell].append((k, i))
    hits: dict[tuple[int, int], list[Point]] = defaultdict(list)
    seen: set[tuple[int, int, int, int]] = set()
    for cell in sorted(grid):
        for (k1, i1), (k2, i2) in itertools.combinations(grid[cell], 2):
            if k1 == k2:
                continue
            if k1 > k2:
                k1, i1, k2, i2 = k2, i2, k1, i1
            if (k1, i1, k2, i2) in seen:
                continue
            seen.add((k1, i1, k2, i2))
            p, q = polylines[k1], polylines[k2]
            hit = _segment_hit(p[i1], p[i1 + 1], q[i2], q[i2 + 1])
            if hit is None:
                continue
            t = hit[0]
            point = (
                p[i1][0] + (p[i1 + 1][0] - p[i1][0]) * t,
                p[i1][1] + (p[i1 + 1][1] - p[i1][1]) * t,
            )
            if all(math.dist(point, h) > 1.0 for h in hits[(k1, k2)]):
                hits[(k1, k2)].append(point)
    planned: list[tuple[list[int], list[int], Point, float]] = []
    for (k1, k2), points in sorted(hits.items()):
        ends = ends_of[k1] | ends_of[k2]
        far = [
            h for h in points if all(math.dist(h, net.nodes[n].at) >= m.crossing_node for n in ends)
        ]
        if not far:
            continue
        refs = tuple(
            sorted({r for k in (k1, k2) for leg in found_strands[k] for r in net.legs[leg].refs})
        )
        if len(far) >= 2:
            net.finding(
                CheckKind.CROSSING_DOUBT,
                f"crossing_doubt:twice:{'+'.join(refs)}",
                far[0],
                "Två spår möts två gånger",
                "Spåren är ritade nästan ovanpå varandra. Det blev ingen korsning; rätta ritningen "
                "eller svara att det stämmer.",
                refs,
            )
            continue
        point = far[0]
        h1 = _heading_near(net, found_strands[k1], point)
        h2 = _heading_near(net, found_strands[k2], point)
        angle = abs(curves.wrap(h1 - h2))
        angle = min(angle, math.pi - angle)
        if angle < ON_TOP:
            net.finding(
                CheckKind.CROSSING_DOUBT,
                f"crossing_doubt:on_top:{'+'.join(refs)}",
                point,
                "Två spår ligger ovanpå varandra",
                "Spåren rör vid varandra utan vinkel. Det blev ingen korsning; rätta ritningen "
                "eller svara att det stämmer.",
                refs,
            )
            continue
        planned.append((found_strands[k1], found_strands[k2], point, math.degrees(angle)))
    for first_legs, second_legs, point, angle in planned:
        first = _cut_at(net, first_legs, point)
        second = _cut_at(net, second_legs, point)
        if first is None or second is None or first == second:
            continue
        net.merge(min(first, second), max(first, second), point)
        crossing = min(first, second)
        net.crossing_nodes.add(crossing)
        if angle < m.crossing_angle:
            net.finding(
                CheckKind.CROSSING_DOUBT,
                f"crossing_doubt:angle:{point[0]:.0f}:{point[1]:.0f}:{angle:.1f}",
                point,
                f"Korsning på {_decimal(angle)}°, troligen ett ritfel",
                f"Spåren korsar under {_decimal(m.crossing_angle)}°. Kontrollera ritningen.",
                (),
            )


def _heading_near(net: Network, chain: list[int], point: Point) -> float:
    best = min(
        (curves.project_path(net.legs[leg].segs, point)[1], leg) for leg in chain if leg in net.legs
    )
    leg = net.legs[best[1]]
    return curves.path_heading(leg.segs, curves.project_path(leg.segs, point)[0])


def _cut_at(net: Network, chain: list[int], point: Point) -> int | None:
    """The node on the strand at the point: a plain joint already there, or a new cut. The strand
    may have been cut by an earlier crossing: its legs are those with its parts' ids nearby."""
    refs = {r for leg in chain if leg in net.legs for r in net.legs[leg].refs}
    for leg in chain:
        if leg not in net.legs:
            continue
        for node in (net.legs[leg].a, net.legs[leg].b):
            if math.dist(net.nodes[node].at, point) <= 1.0 and net.degree(node) == 2:
                return node
    best: tuple[float, int, float] | None = None
    for candidate in net.legs.values():
        if candidate.id not in chain and not (set(candidate.refs) & refs):
            continue
        s, off = curves.project_path(candidate.segs, point)
        if off < 1.0 and 0.5 < s < candidate.length - 0.5 and (best is None or off < best[0]):
            best = (off, candidate.id, s)
    if best is None:
        return None
    node = net.split(best[1], best[2])
    chain.append(net.next_leg - 1)
    return node


def _cells(a: Point, b: Point) -> Iterator[tuple[int, int]]:
    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    for cx in range(math.floor(x0 / CELL), math.floor(x1 / CELL) + 1):
        for cy in range(math.floor(y0 / CELL), math.floor(y1 / CELL) + 1):
            yield (cx, cy)


# --- 11. Loose parts -----------------------------------------------------------------------


def loose(net: Network) -> None:
    """Rule 8: what does not hang together with the largest part, nor through the turntable."""
    adjacency = net.adjacency()
    group: dict[int, int] = {}
    groups: list[list[int]] = []
    for start in sorted(net.nodes):
        if start in group:
            continue
        found = [start]
        group[start] = len(groups)
        queue = [start]
        while queue:
            here = queue.pop()
            for leg_id in adjacency.get(here, []):
                there = net.other(leg_id, here)
                if there not in group:
                    group[there] = len(groups)
                    found.append(there)
                    queue.append(there)
        groups.append(found)
    if not groups:
        return
    # The turntable joins the groups whose radial tracks end in its pit.
    parent = list(range(len(groups)))

    def root(k: int) -> int:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for centre, reach in net.pits:
        inside = sorted(
            {
                group[n]
                for n, node in net.nodes.items()
                if node.end == "pit" and math.dist(node.at, centre) <= reach
            }
        )
        for k in inside[1:]:
            parent[root(k)] = root(inside[0])
    length: dict[int, float] = defaultdict(float)
    for leg in net.legs.values():
        length[root(group[leg.a])] += leg.length
    if not length:
        return
    main = max(length, key=lambda k: (length[k], -k))
    for leg in sorted(net.legs.values(), key=lambda x: x.id):
        if root(group[leg.a]) == main:
            continue
        net.remove_leg(leg.id)
    for k in sorted({root(g) for g in range(len(groups))}):
        if k == main or length.get(k, 0) <= 0:
            continue
        members = [n for g in range(len(groups)) if root(g) == k for n in groups[g]]
        xs = [net.nodes[n].at[0] for n in members if n in net.nodes]
        ys = [net.nodes[n].at[1] for n in members if n in net.nodes]
        if not xs:
            continue
        net.counts.loose += 1
        at = (sum(xs) / len(xs), sum(ys) / len(ys))
        net.finding(
            CheckKind.LOOSE_PART,
            f"loose_part:{k}:{length[k]:.0f}",
            at,
            f"Lös del, {_decimal(length[k] / 1000, 2)} m spår, togs inte med",
            "Spåren hänger inte ihop med resten av anläggningen. De är en sidoritning eller ett "
            "utkast och tas inte med.",
            (),
        )
    net.drop_empty()


# --- 12. Reading the nodes -------------------------------------------------------------------


def read_nodes(net: Network) -> None:
    """Switches: AnyRail's own, assumed where three ends meet, back to back where four do."""
    by_node: dict[int, list[Turnout]] = defaultdict(list)
    for t in net.turnouts:
        if t.straight in net.legs and t.diverging in net.legs:
            straight, diverging = net.legs[t.straight], net.legs[t.diverging]
            if straight.a == diverging.a:
                t.node = straight.a
                by_node[t.node].append(t)
    for node in sorted(net.nodes):
        if node not in net.nodes:
            continue
        legs = net.on(node)
        here = by_node.get(node, [])
        if len(legs) == 3:
            _switch(net, node, legs, here[0] if here else None)
        elif len(legs) == 4 and node not in net.crossing_nodes:
            _back_to_back(net, node, legs, here)


def _switch(net: Network, node: int, legs: list[int], turnout: Turnout | None) -> None:
    if turnout is not None and {turnout.straight, turnout.diverging} <= set(legs):
        trunk = next(leg for leg in legs if leg not in (turnout.straight, turnout.diverging))
        net.switches.append(
            Switch(
                node,
                trunk,
                turnout.straight,
                turnout.diverging,
                turnout.part,
                turnout.side,
                turnout.radius,
                turnout.angle,
            )
        )
        return
    heads = {leg: curves.unit(net.leaving(leg, node)) for leg in legs}
    # The trunk points most away from the other two; the straight is the straightest.
    trunk = min(
        legs,
        key=lambda leg: (sum(curves.dot(heads[leg], heads[o]) for o in legs if o != leg), leg),
    )
    rest = [leg for leg in legs if leg != trunk]
    back = (-heads[trunk][0], -heads[trunk][1])
    rest.sort(
        key=lambda leg: (
            -round(curves.dot(heads[leg], back), 6),
            abs(turn(_first(net.away(leg, node), 200.0))),
            leg,
        )
    )
    straight, diverging = rest[0], rest[1]
    bend = turn(_first(net.away(diverging, node), 200.0))
    side_of = curves.cross(back, heads[diverging])
    side: Literal["left", "right", "y"] = "right" if (side_of or bend) > 0 else "left"
    arcs = [s for s in _first(net.away(diverging, node), 400.0) if isinstance(s, Arc)]
    net.switches.append(
        Switch(
            node,
            trunk,
            straight,
            diverging,
            None,
            side,
            round(min(a.radius for a in arcs), 1) if arcs else None,
            None,
        )
    )


def _first(segs: list[Seg], run: float) -> list[Seg]:
    if curves.path_length(segs) <= run:
        return segs
    return curves.split_path(segs, run)[0]


def _back_to_back(net: Network, node: int, legs: list[int], turnouts: list[Turnout]) -> None:
    """Four ends in one place: two switches back to back, BACK_TO_BACK apart, with a short trunk
    between them. AnyRail's own turnout keeps its legs."""
    heads = {leg: curves.unit(net.leaving(leg, node)) for leg in legs}
    options: list[tuple[float, tuple[int, int], tuple[int, int]]] = []
    for pair in itertools.combinations(sorted(legs), 2):
        rest = tuple(leg for leg in sorted(legs) if leg not in pair)
        if pair > rest:
            continue
        same = curves.dot(heads[pair[0]], heads[pair[1]]) + curves.dot(
            heads[rest[0]], heads[rest[1]]
        )
        mean_p = curves.add(heads[pair[0]], heads[pair[1]])
        mean_r = curves.add(heads[rest[0]], heads[rest[1]])
        opposed = curves.dot(mean_p, mean_r)
        for turnout in turnouts:
            if {turnout.straight, turnout.diverging} in ({*pair}, {*rest}):
                same += 10
        options.append((-(same - opposed), pair, (rest[0], rest[1])))
    if not options:
        return
    _, first, second = min(options)
    at = net.nodes[node].at
    sides: list[int] = []
    for pair in (first, second):
        mean = curves.add(heads[pair[0]], heads[pair[1]])
        size = math.hypot(*mean) or 1.0
        to = curves.add(at, (mean[0] / size, mean[1] / size), BACK_TO_BACK / 2)
        made = net.new_node(to)
        for leg in pair:
            found = net.legs[leg]
            net.move_end(leg, node, to)
            if found.a == node:
                found.a = made
            if found.b == node:
                found.b = made
        sides.append(made)
    a, b = net.nodes[sides[0]].at, net.nodes[sides[1]].at
    refs: tuple[str, ...] = tuple(sorted({r for leg in legs for r in net.legs[leg].refs}))
    link = net.add_leg(sides[0], sides[1], [Line(a, b)], refs, flex=False, role="trunk")
    del net.nodes[node]
    for side, pair in zip(sides, (first, second), strict=True):
        own = next((t for t in turnouts if {t.straight, t.diverging} == set(pair)), None)
        if own is not None:
            own.node = side
        _switch(net, side, [*pair, link.id], own)


def run(layout: Layout, measures: AnyRailMeasures, thin: Sequence[Part]) -> Network:
    """The whole network, every rule in order."""
    net = build(layout, measures)
    remove_loops(net)
    remove_corners(net)
    turntable(net, thin)
    smooth(net)
    remove_backward(net)
    doubled(net)
    join(net)
    parting(net)
    touching(net)
    crossings(net)
    loose(net)
    read_nodes(net)
    return net
