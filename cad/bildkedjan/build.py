"""Step 12 of the chain, the second half: the track graph from the network (bildkedjan,
Geometri), straights and arcs fitted directly to the photo's paths, the switches from the
switch library, and a crossing where two tracks cross.

The paths are fitted route by route. A route runs on along a track: through a switch along its
straight leg, and straight through a crossing. A route from gable to gable, or to an end, is
fitted first, with straights and arcs of at least the switches' lower radius limit and at most
FIT_DEVIATION from the path (cad/smoothing.py, the same fit as utjämning, tighter). A switch's
points then lie on its straight route, and its diverging leg is fitted from there: it leaves
tangentially, and where it runs into another switch's leg, as in a crossover, it arrives
tangentially too (straight, arc, straight, arc, straight, as Lås mått, cad/lock.py). Each piece
is drawn once: the routes are cut where their nodes are.

Everything the photo gives is a proposal (CAD-17): its origin is the photo, with the certainty
the chain gives it, until the owner approves the track plan. The path each piece was fitted to is
kept with it as a drawn line from the photo, so Ritningen shows how far the drawing lies from
the photo.
"""

from __future__ import annotations

import itertools
import math
from contextvars import ContextVar
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from cad import curves, lock, smoothing, switches
from cad.bildkedjan.network import Edge, Network, Node
from cad.bildkedjan.paths import Path
from cad.curves import Seg
from cad.editor import Drawing, EditError
from cad.editor import Node as DrawingNode
from cad.editor import Piece as DrawingPiece
from cad.editor import Switch as DrawingSwitch
from contracts.cad import (
    Certainty,
    DrawingSource,
    DrawnLine,
    GableEnd,
    GraphOrigin,
    GraphSource,
    Scale,
    Smoothing,
)
from contracts.station_model import NodeType, Point, SwitchType

FIT_DEVIATION = 0.8
"""How far a fitted straight or arc may lie from the photo's path, mm."""
LINE_STEP = 2.0
"""The kept line from the photo: a point every 2 mm."""
LOOSE_DEVIATION = 2.5
FIT_STEP = 4.0
START_MM = 40.0
LEG_REACH_MM = 400.0
"""How much of a diverging leg decides its arc, mm."""
"""The fit samples the path every 4 mm."""
LOOSER: ContextVar[float] = ContextVar("looser", default=1.0)
CURVED: ContextVar[bool] = ContextVar("curved", default=False)
"""A curve module (bildkedjan step 6): a track through it is first tried as one arc."""
ONE_ARC_MM = (2.5, 1.0)
"""A track in a curve module is drawn as one arc when the photo's path lies within this of it:
the largest distance and the RMS, mm (times LOOSER at low resolution)."""
ONE_ARC_MIN_MM = 100.0
"""How much wider the fits' tolerances are for this photo: at low resolution the photo's paths
wander as much as the tolerances are widened (measures.Quality.widen)."""
CLEAN_WINDOW = 11
CLEAN_MM = 0.5
"""A point further than this from the median of its neighbours found the wrong rail."""


@dataclass
class Route:
    edges: list[Edge]
    start: str
    end: str
    pid: int
    leg_of: list[str] = field(default_factory=list)
    """The switches whose diverging leg this route starts or ends as."""
    segs: list[Seg] = field(default_factory=list)
    photo: list[Point] = field(default_factory=list)
    """The photo's path the route was fitted to."""


def _next(net: Network, edge: Edge, node: str) -> Edge | None:
    """The edge a route goes on with through the node: a switch's straight from its trunk and
    the other way, a crossing's edge with the same paths."""
    n = net.nodes[node]
    if n.kind == "switch":
        fit = next(s for s in net.switches if s.node == node)
        if edge.id == fit.trunk:
            return net.edges[fit.straight]
        if edge.id == fit.straight:
            return net.edges[fit.trunk]
        return None
    if n.kind == "crossing":
        others = [e for e in net.edges.values() if node in (e.a, e.b) and e.id != edge.id]
        return next((e for e in others if e.members & edge.members), None)
    return None


def routes(net: Network) -> list[Route]:
    """Every edge in exactly one route, each route from smaller x to larger."""
    done: set[str] = set()
    found: list[Route] = []
    for edge in sorted(net.edges.values(), key=lambda e: net.nodes[e.a].x):
        if edge.id in done:
            continue
        # Back to the route's start, then forward to its end.
        first = edge
        while True:
            before = _next(net, first, first.a)
            if before is None or before.id in done or before.b != first.a:
                break
            first = before
        chain = [first]
        while True:
            after = _next(net, chain[-1], chain[-1].b)
            if after is None or after.id in done or after.a != chain[-1].b or after in chain:
                break
            chain.append(after)
        for e in chain:
            done.add(e.id)
        legs = [s.node for s in net.switches if s.diverging in {e.id for e in chain}]
        found.append(Route(chain, chain[0].a, chain[-1].b, chain[0].pid, legs))
    return found


def _points(paths: list[Path], route: Route, nodes: dict[str, Node]) -> list[Point]:
    """The route's path every LINE_STEP mm between its end nodes, with the nodes themselves."""
    a, b = nodes[route.start], nodes[route.end]
    found: list[Point] = [(a.x, a.y)]
    for edge in route.edges:
        p = paths[edge.pid]
        x0, x1 = nodes[edge.a].x, nodes[edge.b].x
        xs = np.arange(math.ceil(x0 + 1), math.floor(x1 - 1) + 1, LINE_STEP)
        found.extend((float(x), float(np.interp(x, p.xs, p.ys))) for x in xs)
        if edge is not route.edges[-1]:
            n = nodes[edge.b]
            found.append((n.x, n.y))
    found.append((b.x, b.y))
    return _clean(found)


def _clean(points: list[Point]) -> list[Point]:
    """Points that lie further than CLEAN_MM from the median of their neighbours across the
    module are moved to it: where two tracks overlap the profile can find the other one's rail."""
    if len(points) < CLEAN_WINDOW + 2:
        return points
    ys = np.array([p[1] for p in points])
    half = CLEAN_WINDOW // 2
    padded = np.pad(ys, half, mode="edge")
    median = np.median(np.lib.stride_tricks.sliding_window_view(padded, CLEAN_WINDOW), axis=1)
    far = np.abs(ys - median) > CLEAN_MM * LOOSER.get()
    far[0] = far[-1] = False
    return [(p[0], float(m) if f else p[1]) for p, m, f in zip(points, median, far, strict=True)]


def _heading_on(segs: list[Seg], point: Point) -> tuple[float, float]:
    """How far along the chain the point lies, and the chain's heading there."""
    s, _ = curves.project_path(segs, point)
    return s, curves.path_heading(segs, s)


@dataclass
class Built:
    drawing: Drawing
    routes: list[Route]
    deviation: list[float]
    """Each photo point's distance from the drawing, mm."""


RANK = {
    Certainty.UNCERTAIN: 0,
    Certainty.PROBABLE: 1,
    Certainty.CERTAIN: 2,
    Certainty.CONFIRMED: 3,
}


def build(
    drawing: Drawing,
    net: Network,
    paths: list[Path],
    certainty: dict[tuple[str, str], Certainty],
    gable_tracks: dict[str, tuple[GableEnd, int]],
    looser: float = 1.0,
    curved: bool = False,
) -> Built:
    """The drawing's graph made from the network: nodes, pieces and switches, with the photo
    as their origin. drawing comes with the module's measures and no pieces. looser widens the
    fits' tolerances (low resolution); curved: a curve module, whose tracks are arcs."""
    token = LOOSER.set(max(1.0, looser))
    bent = CURVED.set(curved)
    try:
        return _build(drawing, net, paths, certainty, gable_tracks)
    finally:
        CURVED.reset(bent)
        LOOSER.reset(token)


def _build(
    drawing: Drawing,
    net: Network,
    paths: list[Path],
    certainty: dict[tuple[str, str], Certainty],
    gable_tracks: dict[str, tuple[GableEnd, int]],
) -> Built:
    limits = switches.limits(drawing.scale)
    min_radius = limits.switch_min_radius
    nodes = net.nodes
    found = routes(net)
    # Routes between terminals first; legs that start at a switch after their straight routes.
    pending = list(found)
    fitted: dict[int, Route] = {}
    for _ in range(len(pending) + 2):
        for route in list(pending):
            starts_leg = nodes[route.start].kind == "switch" and route.start in route.leg_of
            ends_leg = nodes[route.end].kind == "switch" and route.end in route.leg_of
            needed = [
                n
                for n in (route.start if starts_leg else None, route.end if ends_leg else None)
                if n
            ]
            hosts = [_host(net, found, n) for n in needed]
            if any(h is None or id(h) not in fitted for h in hosts):
                continue
            route.segs = _sane(_fit(route, paths, nodes, found, net, min_radius), route, min_radius)
            fitted[id(route)] = route
            pending.remove(route)
        if not pending:
            break
    for route in pending:  # a ring of legs: fitted without tangents
        route.photo = _points(paths, route, nodes)
        route.segs = _fit_free(route.photo, min_radius)
    _place_crossings(net, found)
    pieces = _cut(found, nodes)

    def origin_of(members: frozenset[int]) -> GraphOrigin:
        """A piece is as sure as the least sure connection that runs on it."""
        found_ = [certainty.get(paths[i].pair, Certainty.PROBABLE) for i in members]
        lowest = min(found_, key=lambda c: RANK[c]) if found_ else Certainty.PROBABLE
        return GraphOrigin(source=GraphSource.PHOTO, certainty=lowest)

    deviation: list[float] = []
    ids: dict[str, str] = {}
    for node in nodes.values():
        if node.kind == "gable":
            end, track = gable_tracks[node.id]
            made = drawing.new_id("n")
            drawing.nodes[made] = DrawingNode(
                made, NodeType.MODULE_JOINT, (node.x, node.y), end, track
            )
        else:
            kind = {
                "switch": NodeType.SWITCH,
                "crossing": NodeType.CROSSING,
            }.get(node.kind, NodeType.JOINT)
            made = drawing.new_id("n")
            drawing.nodes[made] = DrawingNode(made, kind, (node.x, node.y))
        ids[node.id] = made
    edge_piece: dict[str, str] = {}
    for edge, segs, line in pieces:
        a, b = ids[edge.a], ids[edge.b]
        segs = curves.reshaped(segs, drawing.nodes[a].at, drawing.nodes[b].at)
        made = drawing.new_id("s")
        drawing.pieces[made] = DrawingPiece(made, a, b, segs, None, origin_of(edge.members))
        edge_piece[edge.id] = made
        kept = line
        if len(kept) >= 2:
            drawing.lines[made] = DrawnLine(
                piece=made,
                points=[(round(x, 2), round(y, 2)) for x, y in kept[:4000]],
                source="photo",
            )
            deviation.extend(curves.distance(segs, p) for p in kept)
    for number, fit in enumerate(sorted(net.switches, key=lambda f: nodes[f.node].x), start=1):
        leg = drawing.pieces[edge_piece[fit.diverging]]
        node_id = ids[fit.node]
        away = drawing.away(leg.id, node_id)
        angle = _leg_angle(away)
        made = drawing.new_id("v")
        drawing.switches[made] = DrawingSwitch(
            id=made,
            node=node_id,
            type=SwitchType.ORDINARY,
            trunk=edge_piece[fit.trunk],
            straight=edge_piece[fit.straight],
            diverging=edge_piece[fit.diverging],
            radius=round(fit.radius, 1) if fit.radius else None,
            angle=angle,
            origin=origin_of(net.edges[fit.diverging].members | net.edges[fit.trunk].members),
            number=str(number),
            design=None,
            toward=GableEnd(fit.toward),
        )
    drawing.source = DrawingSource.PHOTO
    drawing.smoothing = Smoothing.LIGHT
    try:
        drawing.validate()
    except EditError:
        raise
    return Built(drawing, found, deviation)


SANE_LENGTH = (0.8, 1.25)
"""A fitted route's length against its photo path's: outside this it fitted something else."""


def _sane(segs: list[Seg], route: Route, min_radius: float) -> list[Seg]:
    """The fitted route, or, when the fit ran off (a template that could not close, at low
    resolution), the photo's path fitted freely between the same ends."""
    photo = route.photo
    if len(photo) < 2:
        return segs
    along = float(sum(math.dist(a, b) for a, b in itertools.pairwise(photo)))
    total = curves.path_length(segs) if segs else 0.0
    lo, hi = SANE_LENGTH
    if along > 0 and lo * along <= total <= hi * along:
        return segs
    return _fit_free(photo, min_radius)


def _host(net: Network, found: list[Route], node: str) -> Route | None:
    """The route a switch's straight leg lies on."""
    fit = next(s for s in net.switches if s.node == node)
    return next((r for r in found if any(e.id == fit.straight for e in r.edges)), None)


def _start_heading(points: list[Point]) -> float:
    """The heading at the first point: a straight line through the first START_MM of the path."""
    first = np.array([p for p in points if math.dist(p, points[0]) <= START_MM])
    if len(first) < 3:
        return curves.heading(points[0], points[-1])
    centred = first - first.mean(axis=0)
    _, vectors = np.linalg.eigh(centred.T @ centred)
    direction = vectors[:, 1]
    if float(direction @ (first[-1] - first[0])) < 0:
        direction = -direction
    return math.atan2(float(direction[1]), float(direction[0]))


def _fit_free(points: list[Point], min_radius: float, head: float | None = None) -> list[Seg]:
    """Two fits: a loose one, and a tight one without the points the loose one shows are off
    the track, such as where two tracks overlap and the profile finds the other one."""
    if head is None:
        head = _start_heading(points)
    looser = LOOSER.get()
    loose = smoothing.fit(points, min_radius, LOOSE_DEVIATION * looser, head, FIT_STEP)
    if loose:
        off = np.array([curves.distance(loose, p) for p in points])
        spread = float(np.median(off)) * 1.4826 + 0.05
        keep = [p for p, o in zip(points, off, strict=True) if o <= max(3 * spread, 0.3)]
        if len(keep) >= 2 and keep[0] == points[0] and keep[-1] == points[-1]:
            points = keep
        elif len(keep) >= 2:
            points = [points[0], *keep[1:-1], points[-1]]
    segs = smoothing.fit(points, min_radius, FIT_DEVIATION * looser, head, FIT_STEP)
    return (
        curves.reshaped(segs, points[0], points[-1])
        if segs
        else [curves.Line(points[0], points[-1])]
    )


def _tangent(
    net: Network, found: list[Route], node: str, toward_route_end: bool
) -> tuple[Point, float]:
    """A switch's points and the heading its diverging leg leaves them with, along the leg."""
    host = _host(net, found, node)
    assert host is not None and host.segs
    n = net.nodes[node]
    s, heading = _heading_on(host.segs, (n.x, n.y))
    at = curves.path_point(host.segs, s)
    n.x, n.y = at
    return at, heading if toward_route_end else curves.wrap(heading + math.pi)


def _radius(net: Network, node: str, min_radius: float) -> float | None:
    fit = next((f for f in net.switches if f.node == node), None)
    if fit is None or fit.radius is None:
        return None
    return max(fit.radius, min_radius)


def _fit(
    route: Route,
    paths: list[Path],
    nodes: dict[str, Node],
    found: list[Route],
    net: Network,
    min_radius: float,
) -> list[Seg]:
    starts_leg = nodes[route.start].kind == "switch" and route.start in route.leg_of
    ends_leg = nodes[route.end].kind == "switch" and route.end in route.leg_of
    if starts_leg:
        p0, a0 = _tangent(net, found, route.start, True)
        nodes[route.start].x, nodes[route.start].y = p0
    if ends_leg:
        p1, a1 = _tangent(net, found, route.end, True)
        nodes[route.end].x, nodes[route.end].y = p1
    points = _points(paths, route, nodes)
    route.photo = points
    if starts_leg and ends_leg:
        r1 = _radius(net, route.start, min_radius)
        r2 = _radius(net, route.end, min_radius)
        if r1 is not None and r2 is not None:
            closed = _crossover(lock.Ends(p0, a0, p1, a1), r1, r2)
            if closed is not None:
                return closed
        try:
            return list(lock.solve(lock.Ends(p0, a0, p1, a1), points, min_radius, False).segs)
        except lock.NoSolution:
            return _fit_free(points, min_radius, a0)
    if starts_leg:
        return _leg(points, a0, _radius(net, route.start, min_radius), min_radius)
    if ends_leg:
        backward = _leg(
            points[::-1], curves.wrap(a1 + math.pi), _radius(net, route.end, min_radius), min_radius
        )
        return curves.reverse_path(backward)
    if CURVED.get():
        arc = one_arc(points, min_radius)
        if arc is not None:
            return arc
    return _fit_free(points, min_radius)


def one_arc(
    points: list[Point], min_radius: float, within: tuple[float, float] | None = None
) -> list[Seg] | None:
    """The one arc from the path's first point to its last that lies nearest the path, when
    the path lies within ONE_ARC_MM of it (or within: the largest distance and the RMS, mm):
    a curve module's track from gable to gable."""
    if len(points) < 10 or math.dist(points[0], points[-1]) < ONE_ARC_MIN_MM:
        return None
    a, b = np.array(points[0]), np.array(points[-1])
    chord = float(np.linalg.norm(b - a))
    u = (b - a) / chord
    n = np.array([-u[1], u[0]])
    pts = np.array(points, np.float64)
    t = np.clip((pts - a) @ u / chord, 0.0, 1.0)
    off = (pts - a) @ n
    basis = 4 * t * (1 - t)
    mid = (a + b) / 2

    def misses(sag: float) -> NDArray[np.float64]:
        if abs(sag) < 1e-3:
            flat: NDArray[np.float64] = np.abs(off)
            return flat
        radius = (chord * chord / 4 + sag * sag) / (2 * sag)
        centre = mid + n * (sag - radius)
        found: NDArray[np.float64] = np.abs(np.linalg.norm(pts - centre, axis=1) - abs(radius))
        return found

    # The parabola through both ends is the start; a golden search refines the sagitta.
    sag = float(basis @ off / max(1e-9, float(basis @ basis)))
    lo, hi = sag - 0.2 * abs(sag) - 2.0, sag + 0.2 * abs(sag) + 2.0
    golden = (math.sqrt(5) - 1) / 2
    for _ in range(40):
        x1, x2 = hi - golden * (hi - lo), lo + golden * (hi - lo)
        if float(np.mean(misses(x1) ** 2)) <= float(np.mean(misses(x2) ** 2)):
            hi = x2
        else:
            lo = x1
    sag = (lo + hi) / 2
    found = misses(sag)
    most, rms = within or ONE_ARC_MM
    looser = LOOSER.get()
    if float(found.max()) > most * looser or float(np.sqrt(np.mean(found**2))) > rms * looser:
        return None
    if abs(sag) < 1e-3:
        return [curves.Line(points[0], points[-1])]
    middle = (float(mid[0] + n[0] * sag), float(mid[1] + n[1] * sag))
    arc = curves.arc_through(points[0], middle, points[-1])
    if arc is None or (isinstance(arc, curves.Arc) and arc.radius < min_radius):
        return None
    return [arc]


def _crossover(ends: lock.Ends, r1: float, r2: float) -> list[Seg] | None:
    """Two switches' legs that meet, as in a crossover: an arc of the first switch's radius,
    a straight, and an arc of the second's, tangent at both points (cad/lock.py's template
    without its first and last straights)."""
    best: tuple[float, float] | None = None
    previous: tuple[float, float] | None = None
    for degrees in np.arange(-60.0, 60.01, 0.25):
        t1 = math.radians(float(degrees))
        if abs(t1) < 1e-6:
            continue
        t = lock.build(ends, t1, r1, r2, 0.0)
        if t is None:
            previous = None
            continue
        if previous is not None and previous[1] * t.s3 <= 0 and t.s2 >= 0:
            lo, hi = previous[0], t1
            for _ in range(50):
                mid = (lo + hi) / 2
                tm = lock.build(ends, mid, r1, r2, 0.0)
                if tm is None:
                    break
                if (tm.s3 > 0) == (previous[1] > 0):
                    lo = mid
                else:
                    hi = mid
            candidate = lock.build(ends, (lo + hi) / 2, r1, r2, 0.0)
            if (
                candidate is not None
                and candidate.s2 >= -0.5
                and abs(candidate.s3) < 0.5
                and (best is None or abs(candidate.t1) < abs(best[0]))
            ):
                best = ((lo + hi) / 2, candidate.s2)
        previous = (t1, t.s3)
    if best is None:
        return None
    template = lock.build(ends, best[0], r1, r2, 0.0)
    assert template is not None
    template = lock.Template(0.0, r1, template.t1, max(0.0, template.s2), r2, template.t2, 0.0)
    return lock.segments(ends, template)


def _leg(points: list[Point], head: float, radius: float | None, min_radius: float) -> list[Seg]:
    """A switch's diverging leg from its points: an arc of the switch's radius turning toward
    the leg as long as the photo follows it, and then the leg fitted on from there."""
    p0 = points[0]
    if radius is None or len(points) < 10:
        return _fit_free(points, min_radius, head)
    reach = [p for p in points if math.dist(p, p0) <= LEG_REACH_MM]
    ahead = [p for p in points if 40 <= math.dist(p, p0) <= LEG_REACH_MM]
    if len(ahead) < 4:
        return _fit_free(points, min_radius, head)
    side = (
        1.0
        if np.mean([curves.cross(curves.unit(head), curves.sub(p, p0)) for p in ahead]) > 0
        else -1.0
    )

    def cost(turn: float) -> float:
        arc = curves.arc_turning(p0, head, radius, side * turn)
        line = curves.line_from(arc.end, curves.end_heading(arc), LEG_REACH_MM)
        return float(np.mean([min(curves.distance([arc, line], p), 3.0) for p in reach]))

    turns = np.radians(np.arange(0.5, 35.01, 0.5))
    costs = [cost(float(t)) for t in turns]
    best = float(turns[int(np.argmin(costs))])
    lo, hi = max(0.002, best - math.radians(0.5)), best + math.radians(0.5)
    for _ in range(30):
        m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        if cost(m1) <= cost(m2):
            hi = m2
        else:
            lo = m1
    arc = curves.arc_turning(p0, head, radius, side * (lo + hi) / 2)
    arc_length = curves.length(arc)
    rest = [
        p
        for p in points
        if curves.project_path([arc], p)[0] >= arc_length - 1e-6
        and math.dist(p, p0) > arc_length * 0.9
    ]
    end = points[-1]
    if not rest or math.dist(arc.end, end) < 2:
        return [arc]
    rest = (
        [arc.end, *[p for p in rest if math.dist(p, arc.end) > 1], end]
        if rest[-1] != end
        else [arc.end, *[p for p in rest[:-1] if math.dist(p, arc.end) > 1], end]
    )
    after = _fit_free(rest, min_radius, curves.end_heading(arc))
    return [arc, *after]


def _place_crossings(net: Network, found: list[Route]) -> None:
    """A crossing where its two routes' fitted geometry crosses."""
    for node in net.crossings:
        through = [r for r in found if any(node in (e.a, e.b) for e in r.edges)]
        if len(through) != 2 or not all(r.segs for r in through):
            continue
        a = curves.sample_path(through[0].segs, 1.0)
        b_segs = through[1].segs
        n = net.nodes[node]
        near = min(
            a,
            key=lambda p: (
                (curves.distance(b_segs, p), math.dist(p, (n.x, n.y)))
                if math.dist(p, (n.x, n.y)) < 60
                else (math.inf, 0)
            ),
        )
        s, _ = curves.project_path(b_segs, near)
        on_b = curves.path_point(b_segs, s)
        n.x, n.y = (near[0] + on_b[0]) / 2, (near[1] + on_b[1]) / 2


def _cut(found: list[Route], nodes: dict[str, Node]) -> list[tuple[Edge, list[Seg], list[Point]]]:
    """Each route cut at its nodes into the pieces of its edges, each with the photo's points
    that lie along it."""
    pieces: list[tuple[Edge, list[Seg], list[Point]]] = []
    for route in found:
        segs = route.segs
        total = curves.path_length(segs)
        cuts = [0.0]
        for edge in route.edges[:-1]:
            n = nodes[edge.b]
            s, _ = curves.project_path(segs, (n.x, n.y))
            cuts.append(min(max(s, cuts[-1] + 0.5), total - 0.5))
        cuts.append(total)
        along = [curves.project_path(segs, p)[0] for p in route.photo]
        rest = list(segs)
        done = 0.0
        for k, edge in enumerate(route.edges):
            hi = cuts[k + 1]
            if k < len(route.edges) - 1:
                part, rest = curves.split_path(rest, hi - done)
                done = hi
            else:
                part = rest
            lo = cuts[k]
            line = [p for p, s in zip(route.photo, along, strict=True) if lo < s < hi]
            pieces.append((edge, part, line))
    return pieces


def _leg_angle(away: list[Seg]) -> float | None:
    """The diverging leg's angle: how much it has turned where its first arc ends."""
    turn = 0.0
    for seg in away:
        if isinstance(seg, curves.Arc):
            turn += abs(curves.turn_of(seg))
            break
    if turn <= 0:
        start = curves.start_heading(away[0])
        end = curves.end_heading(away[-1])
        turn = abs(curves.wrap(end - start))
    degrees = math.degrees(turn)
    return round(degrees, 2) if 0 < degrees < 90 else None


def scale_of(drawing: Drawing) -> Scale:
    return drawing.scale
