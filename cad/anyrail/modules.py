"""The modules in AnyRail's drawing (rule 2, ANYRAIL-02, ANYRAIL-14): AnyRail has no module part,
so the modules are built from the thin lines and checked against the standard sizes. Each is a
proposal the owner approves.

The thin lines (and the thin arcs and curves, as short lines) are joined where they run in a row
with gaps of at most GAP (AnyRail's modules are often drawn edge by edge, with a cross at each
corner), lengthened by REACH at both ends so that corners close, and cut where they cross. The
faces of that arrangement are the candidate boards. A face with four right corners is a
rectangle; any other face (a board with a bump, a stall drawn against its edge) is its box along
its longest edge, and is not standard. A board is a module when it holds track and is at least
MIN_SIDE on each side.

A module's frame: its long side points east (x of the drawing growing), gable A is its western
end and Kant 1 its upper long side, as AnyRail draws a station from the west with its tracks
numbered from the top (AR2). Its origin, gable A at Kant 1, and its turn counterclockwise on the
screen are where an assembly places it.

Numbering from the west (AR1, ANYRAIL-20, generic, never by a station's name): the end modules
(the end module's standard size) Ä1, Ä2 … by their western edge, the upper first; the others 1,
2 … by their western edge, and modules that share the same span (SPAN_SHARE of the shorter)
get a, b … from the top.
"""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from cad import curves
from cad.anyrail import shapes
from cad.anyrail.reader import Part
from contracts.cad import Scale
from contracts.station_model import Point

GAP: Final = 60.0
"""mm: lines in a row with gaps up to this are one edge."""
REACH: Final = 45.0
"""mm: an edge is lengthened this much at each end, so that drawn corners close (AnyRail's
corner crosses leave 30 mm)."""
MIN_SIDE: Final = 200.0
SIZE_TOLERANCE: Final = 10.0
"""mm: a board within this of a standard size is that size."""
RIGHT: Final = math.radians(3)
SPAN_SHARE: Final = 0.9
END_SPAN_SHARE: Final = 0.5
"""End modules side by side (sharing half their span) are numbered from the top."""

STANDARD: Final[dict[Scale, tuple[tuple[float, float], ...]]] = {
    Scale.H0: ((1500.0, 700.0), (1500.0, 350.0), (700.0, 355.0)),
    Scale.N: ((1500.0, 700.0), (1500.0, 350.0), (700.0, 355.0)),
    Scale.ZERO: ((1500.0, 600.0), (1500.0, 750.0)),
}
"""The standard sizes per scale (ANYRAIL-14): in H0 1500 × 700, 1500 × 350 and the end module
700 × 355; in 0 1500 × 600 (FREMO Spur 0) and 750 with the shelf. N has no sizes of its
own in the specification and is checked against H0's."""
END_MODULE: Final[dict[Scale, tuple[float, float]]] = {
    Scale.H0: (700.0, 355.0),
    Scale.N: (700.0, 355.0),
}


@dataclass(frozen=True)
class Board:
    """A module's board in the drawing: its frame and its outline as drawn."""

    origin: Point
    """Gable A at Kant 1."""
    along: Point
    """Unit vector from gable A toward gable B."""
    length: float
    width: float
    outline: tuple[Point, ...]
    rectangular: bool

    @property
    def across(self) -> Point:
        """Unit vector from Kant 1 into the board (y down on the screen for an unturned one)."""
        return (-self.along[1], self.along[0])

    @property
    def angle(self) -> float:
        """The board's turn, degrees counterclockwise on the screen, as PlacedModule.angle."""
        return math.degrees(math.atan2(-self.along[1], self.along[0]))

    def local(self, p: Point) -> Point:
        d = curves.sub(p, self.origin)
        return (curves.dot(d, self.along), curves.dot(d, self.across))

    def world(self, p: Point) -> Point:
        return curves.add(curves.add(self.origin, self.along, p[0]), self.across, p[1])

    def contains(self, p: Point, margin: float = 0.0) -> bool:
        x, y = self.local(p)
        return -margin <= x <= self.length + margin and -margin <= y <= self.width + margin

    def corners(self) -> list[Point]:
        return [
            self.world((0.0, 0.0)),
            self.world((self.length, 0.0)),
            self.world((self.length, self.width)),
            self.world((0.0, self.width)),
        ]

    @property
    def centre(self) -> Point:
        return self.world((self.length / 2, self.width / 2))


def standard_of(length: float, width: float, scale: Scale) -> str | None:
    for size in STANDARD[scale]:
        if abs(length - size[0]) <= SIZE_TOLERANCE and abs(width - size[1]) <= SIZE_TOLERANCE:
            return f"{size[0]:.0f} × {size[1]:.0f}"
    return None


def is_end(board: Board, scale: Scale) -> bool:
    size = END_MODULE.get(scale)
    if size is None:
        return False
    return (
        abs(board.length - size[0]) <= SIZE_TOLERANCE
        and abs(board.width - size[1]) <= SIZE_TOLERANCE
    )


# --- The thin lines as edges -------------------------------------------------------------


Lines = list[tuple[Point, Point]]


def thin_lines(parts: Sequence[Part]) -> tuple[Lines, list[list[Point]]]:
    """Every thin element: the lines as they are, and the arcs and curves as polylines every
    20 mm."""
    lines: Lines = []
    chains: list[list[Point]] = []
    for part in parts:
        for element in part.elements:
            if element.kind == "line":
                a, b = element.points
                if math.dist(a, b) > 1.0:
                    lines.append((a, b))
                continue
            if element.kind == "arc":
                seg = shapes.arc(element.points[0], element.points[1], element.direction or 0.0)
                segs = [seg] if seg is not None else []
            else:
                segs = shapes.bezier(element.points)
            if not segs or curves.path_length(segs) < 1.0:
                continue
            chains.append(curves.sample_path(segs, 20.0))
    return lines, chains


def _clusters(values: list[tuple[float, int]], tolerance: float) -> list[list[int]]:
    """Indices grouped where sorted values lie within the tolerance of the one before."""
    found: list[list[int]] = []
    last = -math.inf
    for value, index in sorted(values):
        if found and value - last <= tolerance:
            found[-1].append(index)
        else:
            found.append([index])
        last = value
    return found


def _edges(drawn: tuple[Lines, list[list[Point]]]) -> Lines:
    """Lines in a row joined across gaps up to GAP and lengthened by REACH; a curve's chords as
    they are, lengthened at the curve's two ends only."""
    lines, chains = drawn
    info: list[tuple[float, float, float, float]] = []
    for a, b in lines:
        angle = math.atan2(b[1] - a[1], b[0] - a[0]) % math.pi
        if angle > math.pi - math.radians(0.25):
            angle -= math.pi
        direction = (math.cos(angle), math.sin(angle))
        normal = (-direction[1], direction[0])
        s0, s1 = sorted((curves.dot(a, direction), curves.dot(b, direction)))
        info.append((angle, curves.dot(a, normal), s0, s1))
    found: Lines = []
    for by_angle in _clusters([(x[0], k) for k, x in enumerate(info)], math.radians(0.3)):
        for group in _clusters([(info[k][1], k) for k in by_angle], 1.5):
            angle = sum(info[k][0] for k in group) / len(group)
            offset = sum(info[k][1] for k in group) / len(group)
            direction = (math.cos(angle), math.sin(angle))
            normal = (-direction[1], direction[0])
            base = curves.add((0.0, 0.0), normal, offset)
            runs: list[list[float]] = []
            for s0, s1 in sorted((info[k][2], info[k][3]) for k in group):
                if runs and s0 <= runs[-1][1] + GAP:
                    runs[-1][1] = max(runs[-1][1], s1)
                else:
                    runs.append([s0, s1])
            for s0, s1 in runs:
                found.append(
                    (
                        curves.add(base, direction, s0 - REACH),
                        curves.add(base, direction, s1 + REACH),
                    )
                )
    for chain in chains:
        points = list(chain)
        if len(points) < 2:
            continue
        first = curves.heading(points[1], points[0])
        last = curves.heading(points[-2], points[-1])
        points[0] = curves.add(points[0], curves.unit(first), REACH)
        points[-1] = curves.add(points[-1], curves.unit(last), REACH)
        found += [(a, b) for a, b in itertools.pairwise(points) if math.dist(a, b) > 1e-6]
    return found


def _hit(a: Point, b: Point, c: Point, d: Point) -> float | None:
    r = curves.sub(b, a)
    s = curves.sub(d, c)
    den = curves.cross(r, s)
    if abs(den) < 1e-9:
        return None
    qp = curves.sub(c, a)
    t = curves.cross(qp, s) / den
    u = curves.cross(qp, r) / den
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return t
    return None


def faces(drawn: tuple[Lines, list[list[Point]]]) -> list[list[Point]]:
    """The bounded faces of the edges' arrangement, as polygons."""
    edges = _edges(drawn)
    vertices: list[Point] = []
    index: dict[tuple[int, int], int] = {}

    def vertex(p: Point) -> int:
        key = (round(p[0] * 2), round(p[1] * 2))
        for dx, dy in itertools.product((-1, 0, 1), repeat=2):
            found = index.get((key[0] + dx, key[1] + dy))
            if found is not None and math.dist(vertices[found], p) <= 0.75:
                return found
        vertices.append(p)
        index[key] = len(vertices) - 1
        return len(vertices) - 1

    cuts: list[list[float]] = [[0.0, 1.0] for _ in edges]
    for i, j in itertools.combinations(range(len(edges)), 2):
        a, b = edges[i]
        c, d = edges[j]
        if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]):
            continue
        if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
            continue
        t = _hit(a, b, c, d)
        if t is None:
            continue
        u = _hit(c, d, a, b)
        cuts[i].append(t)
        if u is not None:
            cuts[j].append(u)
    graph: dict[int, set[int]] = defaultdict(set)
    for (a, b), ts in zip(edges, cuts, strict=True):
        points = [vertex(curves.add(a, curves.sub(b, a), t)) for t in sorted(set(ts))]
        for u, v in itertools.pairwise(points):
            if u != v:
                graph[u].add(v)
                graph[v].add(u)
    # Dangling edges (the lengthened ends) bound no face.
    changed = True
    while changed:
        changed = False
        for v in [v for v, near in graph.items() if len(near) <= 1]:
            for u in graph.pop(v, set()):
                graph[u].discard(v)
            changed = True
    order: dict[int, list[int]] = {
        v: sorted(
            near,
            key=lambda u: math.atan2(
                vertices[u][1] - vertices[v][1], vertices[u][0] - vertices[v][0]
            ),
        )
        for v, near in graph.items()
    }
    used: set[tuple[int, int]] = set()
    found: list[list[Point]] = []
    for start in sorted(graph):
        for nxt in order[start]:
            if (start, nxt) in used:
                continue
            ring = [start]
            u, v = start, nxt
            while (u, v) not in used:
                used.add((u, v))
                around = order[v]
                k = around.index(u)
                w = around[(k - 1) % len(around)]
                ring.append(v)
                u, v = v, w
                if len(ring) > 10_000:
                    break
            polygon = (
                [vertices[k] for k in ring[:-1]]
                if ring[-1] == ring[0]
                else [vertices[k] for k in ring]
            )
            if len(polygon) >= 3 and _area(polygon) > 0:
                found.append(polygon)
    return found


def _area(polygon: Sequence[Point]) -> float:
    """Signed area, positive for a face traversed with its inside on the right on the screen."""
    total = 0.0
    for (x0, y0), (x1, y1) in zip(polygon, [*polygon[1:], polygon[0]], strict=True):
        total += x0 * y1 - x1 * y0
    return total / 2


def _simplified(polygon: list[Point]) -> list[Point]:
    """Corners only: vertices where the outline turns more than a degree."""
    points = polygon
    changed = True
    while changed and len(points) > 3:
        changed = False
        for k in range(len(points)):
            a, b, c = points[k - 1], points[k], points[(k + 1) % len(points)]
            if math.dist(a, b) < 1e-6:
                points = points[:k] + points[k + 1 :]
                changed = True
                break
            turn = abs(curves.wrap(curves.heading(b, c) - curves.heading(a, b)))
            if turn < math.radians(1):
                points = points[:k] + points[k + 1 :]
                changed = True
                break
    return points


def board_of(polygon: list[Point]) -> Board | None:
    """The face as a board: a rectangle, or the box along its longest edge."""
    corners = _simplified(polygon)
    rectangular = len(corners) == 4 and all(
        abs(
            abs(
                curves.wrap(
                    curves.heading(corners[k], corners[(k + 1) % 4])
                    - curves.heading(corners[k - 1], corners[k])
                )
            )
            - math.pi / 2
        )
        <= RIGHT
        for k in range(4)
    )
    pairs = list(zip(corners, [*corners[1:], corners[0]], strict=True))
    a, b = max(pairs, key=lambda e: math.dist(*e))
    angle = math.atan2(b[1] - a[1], b[0] - a[0])
    along = curves.unit(angle)
    if along[0] < -1e-9 or (abs(along[0]) <= 1e-9 and along[1] > 0):
        along = (-along[0], -along[1])
    across = (-along[1], along[0])
    xs = [curves.dot(p, along) for p in polygon]
    ys = [curves.dot(p, across) for p in polygon]
    length, width = max(xs) - min(xs), max(ys) - min(ys)
    if length < width:
        # The longest edge was a gable: turn the frame a quarter.
        along = (
            (across[0], across[1])
            if across[0] > 1e-9 or (abs(across[0]) <= 1e-9 and across[1] < 0)
            else (-across[0], -across[1])
        )
        across = (-along[1], along[0])
        xs = [curves.dot(p, along) for p in polygon]
        ys = [curves.dot(p, across) for p in polygon]
        length, width = max(xs) - min(xs), max(ys) - min(ys)
    if min(length, width) < MIN_SIDE:
        return None
    origin = curves.add(curves.add((0.0, 0.0), along, min(xs)), across, min(ys))
    return Board(
        origin=(round(origin[0], 3), round(origin[1], 3)),
        along=along,
        length=round(length, 1),
        width=round(width, 1),
        outline=tuple((round(p[0], 1), round(p[1], 1)) for p in corners),
        rectangular=rectangular,
    )


COVERED: Final = 0.6
"""A standard board's four sides are drawn along at least this share of their length."""
OVERLAP: Final = 0.2


def _runs(
    drawn: tuple[Lines, list[list[Point]]], vertical: bool
) -> dict[float, list[tuple[float, float]]]:
    """The drawing's straight lines across or along the station: their place, and the stretches
    they cover."""
    lines, _ = drawn
    places: list[tuple[float, int]] = []
    stretches: list[tuple[float, float]] = []
    for a, b in lines:
        if vertical and abs(a[0] - b[0]) <= 0.5:
            places.append(((a[0] + b[0]) / 2, len(stretches)))
            stretches.append((min(a[1], b[1]), max(a[1], b[1])))
        elif not vertical and abs(a[1] - b[1]) <= 0.5:
            places.append(((a[1] + b[1]) / 2, len(stretches)))
            stretches.append((min(a[0], b[0]), max(a[0], b[0])))
    where = dict((k, p) for p, k in places)
    found: dict[float, list[tuple[float, float]]] = {}
    for group in _clusters(places, 1.0):
        # Where the long lines are: a short line nearby does not move an edge.
        weights = [max(1e-3, stretches[k][1] - stretches[k][0]) for k in group]
        at = sum(where[k] * w for k, w in zip(group, weights, strict=True)) / sum(weights)
        found[round(at, 3)] = [stretches[k] for k in group]
    return found


def _covered(
    runs: dict[float, list[tuple[float, float]]], at: float, lo: float, hi: float
) -> float:
    pieces = sorted(
        (max(a, lo), min(b, hi))
        for key, stretches in runs.items()
        if abs(key - at) <= 2.0
        for a, b in stretches
        if b > lo and a < hi
    )
    total, reach = 0.0, lo
    for a, b in pieces:
        if b > reach:
            total += b - max(a, reach)
            reach = b
    return total / (hi - lo) if hi > lo else 0.0


def standard_boards(drawn: tuple[Lines, list[list[Point]]], scale: Scale) -> list[Board]:
    """Boards of a standard size along the station whose four sides are drawn (COVERED), even
    where lines inside them (stalls, platforms) cut their face."""
    across = _runs(drawn, vertical=True)
    along = _runs(drawn, vertical=False)
    xs = sorted(across)
    ys = sorted(along)
    found: list[Board] = []
    for length, width in STANDARD[scale]:
        for x1 in xs:
            for x2 in (x for x in xs if abs(x - x1 - length) <= SIZE_TOLERANCE):
                for y1 in ys:
                    for y2 in (y for y in ys if abs(y - y1 - width) <= SIZE_TOLERANCE):
                        sides = (
                            _covered(along, y1, x1, x2),
                            _covered(along, y2, x1, x2),
                            _covered(across, x1, y1, y2),
                            _covered(across, x2, y1, y2),
                        )
                        if min(sides) < COVERED:
                            continue
                        found.append(
                            Board(
                                origin=(float(x1), float(y1)),
                                along=(1.0, 0.0),
                                length=float(x2 - x1),
                                width=float(y2 - y1),
                                outline=((x1, y1), (x2, y1), (x2, y2), (x1, y2)),
                                rectangular=True,
                            )
                        )
    return found


def _share_inside(small: Board, big: Board) -> float:
    """How much of a board lies inside another, sampled on a grid."""
    inside = 0
    steps = 10
    for i in range(steps):
        for j in range(steps):
            p = small.world(((i + 0.5) * small.length / steps, (j + 0.5) * small.width / steps))
            inside += big.contains(p)
    return inside / (steps * steps)


def boards(parts: Sequence[Part], scale: Scale = Scale.H0) -> list[Board]:
    """The boards in the drawing, from the west: the standard ones whose sides are drawn, then
    every face of the thin lines that no chosen board already covers."""
    drawn = thin_lines(parts)
    chosen: list[Board] = []
    for board in sorted(
        standard_boards(drawn, scale), key=lambda b: (b.length * b.width, b.origin)
    ):
        if all(
            _share_inside(board, c) <= OVERLAP and _share_inside(c, board) <= OVERLAP
            for c in chosen
        ):
            chosen.append(board)
    faced = [b for b in (board_of(f) for f in faces(drawn)) if b is not None]
    for board in sorted(faced, key=lambda b: (-b.length * b.width, b.origin)):
        if all(_share_inside(board, c) <= OVERLAP for c in chosen):
            chosen.append(board)
    return sorted(chosen, key=lambda b: (round(b.centre[0], 1), round(b.centre[1], 1)))


def numbered(chosen: Sequence[Board], scale: Scale) -> list[str]:
    """Each board's number from the west: Ä1 … for end modules, 1, 2a/2b … for the others."""

    def west(b: Board) -> float:
        return min(p[0] for p in b.corners())

    def east(b: Board) -> float:
        return max(p[0] for p in b.corners())

    def top(b: Board) -> float:
        return min(p[1] for p in b.corners())

    def spans(members: list[int], share: float) -> list[list[int]]:
        groups: list[list[int]] = []
        for k in sorted(members, key=lambda k: (round(west(chosen[k]), 1), top(chosen[k]))):
            b = chosen[k]
            for group in groups:
                g = chosen[group[0]]
                shared = min(east(b), east(g)) - max(west(b), west(g))
                shorter = min(east(b) - west(b), east(g) - west(g))
                if shorter > 0 and shared >= share * shorter:
                    group.append(k)
                    break
            else:
                groups.append([k])
        return [sorted(g, key=lambda k: top(chosen[k])) for g in groups]

    numbers: dict[int, str] = {}
    ends = [k for k, b in enumerate(chosen) if is_end(b, scale)]
    n = 0
    for group in spans(ends, END_SPAN_SHARE):
        for k in group:
            n += 1
            numbers[k] = f"Ä{n}"
    groups = spans([k for k in range(len(chosen)) if k not in numbers], SPAN_SHARE)
    for n, group in enumerate(groups, start=1):
        if len(group) == 1:
            numbers[group[0]] = str(n)
            continue
        for letter, k in zip(
            "abcdefghijklmnopqrstuvwxyz", sorted(group, key=lambda k: top(chosen[k])), strict=False
        ):
            numbers[k] = f"{n}{letter}"
    return [numbers[k] for k in range(len(chosen))]
