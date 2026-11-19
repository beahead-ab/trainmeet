"""Track centre lines as LINE and ARC, in the module's own coordinates (x from gable A, y away
from Kant 1, in mm, y down the drawing, as in contracts/cad.py).

The drawing (Ritningen), utjämning and Lås mått all work on these. A heading is an angle in
radians, 0 toward gable B along x, growing as the track turns right on the drawing (y is down),
so a right turn is a clockwise arc, as ArcSegment.clockwise says. An arc's polar angle (from its
centre) grows along a clockwise arc.

Everything here is exact plane geometry: no fitting and no tolerances except where a function
says so. The contracts' LineSegment and ArcSegment are values with checks; the maths uses the
plain Line and Arc below, and turns them into segments only at the end (segment()).
"""

from __future__ import annotations

import cmath
import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

from contracts.cad import ArcSegment, LineSegment, Segment
from contracts.station_model import Point

TAU = 2 * math.pi
EPS = 1e-9
MAX_RADIUS = 20_000.0
"""The largest radius a segment has (contracts.cad.Mm); flatter arcs are drawn as lines."""


@dataclass(frozen=True)
class Line:
    start: Point
    end: Point


@dataclass(frozen=True)
class Arc:
    start: Point
    end: Point
    center: Point
    radius: float
    clockwise: bool


Seg = Line | Arc


# --- Angles and points -------------------------------------------------------------------


def unit(angle: float) -> Point:
    return (math.cos(angle), math.sin(angle))


def wrap(angle: float) -> float:
    """The angle in (-π, π]."""
    found = math.remainder(angle, TAU)
    return math.pi if found == -math.pi else found


def heading(a: Point, b: Point) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def add(a: Point, b: Point, scale: float = 1.0) -> Point:
    return (a[0] + b[0] * scale, a[1] + b[1] * scale)


def sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def polar(center: Point, point: Point) -> float:
    return math.atan2(point[1] - center[1], point[0] - center[0])


# --- One segment -------------------------------------------------------------------------


def sweep(arc: Arc) -> float:
    """The arc's angle in radians along its direction, in (0, 2π)."""
    a0 = polar(arc.center, arc.start)
    a1 = polar(arc.center, arc.end)
    turn = (a1 - a0) if arc.clockwise else (a0 - a1)
    found = turn % TAU
    return found if found > EPS else TAU


def turn_of(seg: Seg) -> float:
    """How much the track turns along the segment: positive to the right."""
    if isinstance(seg, Line):
        return 0.0
    return sweep(seg) if seg.clockwise else -sweep(seg)


def length(seg: Seg) -> float:
    if isinstance(seg, Line):
        return math.dist(seg.start, seg.end)
    return seg.radius * sweep(seg)


def _arc_heading(arc: Arc, phi: float) -> float:
    return phi + math.pi / 2 if arc.clockwise else phi - math.pi / 2


def start_heading(seg: Seg) -> float:
    if isinstance(seg, Line):
        return heading(seg.start, seg.end)
    return wrap(_arc_heading(seg, polar(seg.center, seg.start)))


def end_heading(seg: Seg) -> float:
    if isinstance(seg, Line):
        return heading(seg.start, seg.end)
    return wrap(_arc_heading(seg, polar(seg.center, seg.end)))


def point_at(seg: Seg, s: float) -> Point:
    """The point s mm along the segment from its start."""
    if isinstance(seg, Line):
        total = length(seg)
        if total < EPS:
            return seg.start
        return add(seg.start, sub(seg.end, seg.start), s / total)
    phi = polar(seg.center, seg.start) + (s / seg.radius) * (1 if seg.clockwise else -1)
    return add(seg.center, unit(phi), seg.radius)


def heading_at(seg: Seg, s: float) -> float:
    if isinstance(seg, Line):
        return heading(seg.start, seg.end)
    phi = polar(seg.center, seg.start) + (s / seg.radius) * (1 if seg.clockwise else -1)
    return wrap(_arc_heading(seg, phi))


def reverse(seg: Seg) -> Seg:
    if isinstance(seg, Line):
        return Line(seg.end, seg.start)
    return Arc(seg.end, seg.start, seg.center, seg.radius, not seg.clockwise)


def split(seg: Seg, s: float) -> tuple[Seg, Seg]:
    """The segment cut s mm from its start."""
    at = point_at(seg, s)
    if isinstance(seg, Line):
        return Line(seg.start, at), Line(at, seg.end)
    return (
        Arc(seg.start, at, seg.center, seg.radius, seg.clockwise),
        Arc(at, seg.end, seg.center, seg.radius, seg.clockwise),
    )


def project(seg: Seg, p: Point) -> tuple[float, float]:
    """The nearest place on the segment: how far along it, and how far from p."""
    if isinstance(seg, Line):
        d = sub(seg.end, seg.start)
        total2 = dot(d, d)
        t = 0.0 if total2 < EPS else max(0.0, min(1.0, dot(sub(p, seg.start), d) / total2))
        at = add(seg.start, d, t)
        return t * math.sqrt(total2), math.dist(at, p)
    total = sweep(seg)
    a0 = polar(seg.center, seg.start)
    turn = (polar(seg.center, p) - a0) if seg.clockwise else (a0 - polar(seg.center, p))
    turn %= TAU
    if turn <= total:
        return turn * seg.radius, abs(math.dist(seg.center, p) - seg.radius)
    to_start = math.dist(seg.start, p)
    to_end = math.dist(seg.end, p)
    return (0.0, to_start) if to_start <= to_end else (total * seg.radius, to_end)


# --- Making segments ---------------------------------------------------------------------


def arc_turning(start: Point, head: float, radius: float, turn: float) -> Seg:
    """From start with the heading, turning turn radians (positive right) on the radius."""
    if abs(turn) < EPS:
        return Line(start, start)
    clockwise = turn > 0
    center = add(start, unit(head + (math.pi / 2 if clockwise else -math.pi / 2)), radius)
    phi = polar(center, start) + turn
    end = add(center, unit(phi), radius)
    return Arc(start, end, center, radius, clockwise)


def line_from(start: Point, head: float, run: float) -> Line:
    return Line(start, add(start, unit(head), run))


def arc_through(a: Point, m: Point, b: Point) -> Seg | None:
    """The arc from a through m to b, or a line when they lie in a row; None when two points
    are the same."""
    if min(math.dist(a, m), math.dist(m, b), math.dist(a, b)) < 1e-6:
        return None
    turn = cross(sub(m, a), sub(b, m))
    ax, ay = a
    bx, by = b
    cx, cy = m
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return Line(a, b)
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)) + (
        (cx * cx + cy * cy) * (ay - by)
    )
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)) + (
        (cx * cx + cy * cy) * (bx - ax)
    )
    center = (ux / d, uy / d)
    radius = math.dist(center, a)
    if radius > MAX_RADIUS:
        return Line(a, b)
    return Arc(a, b, center, radius, turn > 0)


def arc_tangent(a: Point, head: float, b: Point) -> Seg | None:
    """The arc that leaves a with the heading and ends in b (a line when b lies straight
    ahead), or None when b lies straight behind."""
    d = sub(b, a)
    right = unit(head + math.pi / 2)
    side = dot(d, right)
    run = dot(d, unit(head))
    if abs(side) < 1e-9 * max(1.0, abs(run)):
        return Line(a, b) if run > 0 else None
    t = dot(d, d) / (2 * side)
    radius = abs(t)
    if radius > MAX_RADIUS:
        return Line(a, b) if run > 0 else None
    center = add(a, right, t)
    return Arc(a, b, center, radius, t > 0)


def arc_then_line(
    a: Point, head: float, radius: float, right: bool, target: Point
) -> tuple[float, float] | None:
    """A switch's diverging leg to a fixed end: from a with the heading, an arc of the radius
    to the right or left and then straight to target. The arc's turn (positive right) and the
    straight's length, or None when target lies inside the circle."""
    center = add(a, unit(head + (math.pi / 2 if right else -math.pi / 2)), radius)
    distance = math.dist(center, target)
    if distance < radius - 1e-9:
        return None
    tail = math.sqrt(max(0.0, distance * distance - radius * radius))
    psi = polar(center, target)
    spread = math.acos(min(1.0, radius / distance))
    phi0 = polar(center, a)
    for phi in (psi - spread, psi + spread):
        point = add(center, unit(phi), radius)
        along = phi + math.pi / 2 if right else phi - math.pi / 2
        if tail < 1e-6 or dot(sub(target, point), unit(along)) > -1e-6:
            turn = (phi - phi0) % TAU if right else -((phi0 - phi) % TAU)
            return turn, tail
    return None


# --- Moving and reshaping ----------------------------------------------------------------


@dataclass(frozen=True)
class Similarity:
    """z → k·z + t in the complex plane: a turn, a scale and a shift, never a mirror."""

    k: complex
    t: complex

    def __call__(self, p: Point) -> Point:
        z = self.k * complex(p[0], p[1]) + self.t
        return (z.real, z.imag)

    @property
    def scale(self) -> float:
        return abs(self.k)

    @property
    def turn(self) -> float:
        return cmath.phase(self.k)


def shift(by: Point) -> Similarity:
    return Similarity(1 + 0j, complex(by[0], by[1]))


def mapping(p0: Point, p1: Point, q0: Point, q1: Point) -> Similarity:
    """The similarity that takes p0 to q0 and p1 to q1 (a shift when p0 and p1 are one)."""
    a, b = complex(*p0), complex(*p1)
    c, d = complex(*q0), complex(*q1)
    if abs(b - a) < 1e-9:
        return Similarity(1 + 0j, c - a)
    k = (d - c) / (b - a)
    return Similarity(k, c - k * a)


def moved(seg: Seg, how: Similarity) -> Seg:
    if isinstance(seg, Line):
        return Line(how(seg.start), how(seg.end))
    return Arc(how(seg.start), how(seg.end), how(seg.center), seg.radius * how.scale, seg.clockwise)


def reshaped(segs: Sequence[Seg], start: Point, end: Point) -> list[Seg]:
    """The chain of segments turned and scaled so that it runs from start to end."""
    how = mapping(segs[0].start, segs[-1].end, start, end)
    return [moved(s, how) for s in segs]


# --- Chains of segments ------------------------------------------------------------------


def path_length(segs: Sequence[Seg]) -> float:
    return sum(length(s) for s in segs)


def locate(segs: Sequence[Seg], s: float) -> tuple[int, float]:
    """Which segment s mm along the chain lies in, and how far into it."""
    for index, seg in enumerate(segs):
        run = length(seg)
        if s <= run or index == len(segs) - 1:
            return index, max(0.0, min(s, run))
        s -= run
    raise ValueError("Tom kedja.")


def path_point(segs: Sequence[Seg], s: float) -> Point:
    index, local = locate(segs, s)
    return point_at(segs[index], local)


def path_heading(segs: Sequence[Seg], s: float) -> float:
    index, local = locate(segs, s)
    return heading_at(segs[index], local)


def split_path(segs: Sequence[Seg], s: float) -> tuple[list[Seg], list[Seg]]:
    """The chain cut s mm from its start; s strictly inside it."""
    index, local = locate(segs, s)
    seg = segs[index]
    run = length(seg)
    before = list(segs[:index])
    after = list(segs[index + 1 :])
    if local <= EPS:
        return before, [seg, *after]
    if local >= run - EPS:
        return [*before, seg], after
    first, second = split(seg, local)
    return [*before, first], [second, *after]


def reverse_path(segs: Sequence[Seg]) -> list[Seg]:
    return [reverse(s) for s in reversed(segs)]


def project_path(segs: Sequence[Seg], p: Point) -> tuple[float, float]:
    """The nearest place on the chain: how far along it, and how far from p."""
    best = (0.0, math.inf)
    done = 0.0
    for seg in segs:
        along, off = project(seg, p)
        if off < best[1]:
            best = (done + along, off)
        done += length(seg)
    return best


def distance(segs: Sequence[Seg], p: Point) -> float:
    return project_path(segs, p)[1]


def sample_path(segs: Sequence[Seg], step: float) -> list[Point]:
    """Points every step mm along the chain, with both ends."""
    total = path_length(segs)
    count = max(1, math.ceil(total / step))
    return [path_point(segs, total * k / count) for k in range(count + 1)]


def joints(segs: Sequence[Seg]) -> list[tuple[Point, float]]:
    """Where one segment meets the next, with the angle jump there in radians."""
    found: list[tuple[Point, float]] = []
    for before, after in itertools.pairwise(segs):
        found.append((after.start, abs(wrap(start_heading(after) - end_heading(before)))))
    return found


# --- To and from the contracts -----------------------------------------------------------


def _r(p: Point) -> Point:
    return (round(p[0], 3) + 0.0, round(p[1], 3) + 0.0)


def segment(seg: Seg) -> Segment:
    """The contract's segment, rounded to a thousandth of a millimetre."""
    if isinstance(seg, Line) or seg.radius > MAX_RADIUS:
        return LineSegment(start=_r(seg.start), end=_r(seg.end))
    return ArcSegment(
        start=_r(seg.start),
        end=_r(seg.end),
        center=_r(seg.center),
        radius=round(seg.radius, 3),
        clockwise=seg.clockwise,
    )


def from_segment(seg: Segment) -> Seg:
    if isinstance(seg, LineSegment):
        return Line(seg.start, seg.end)
    return Arc(seg.start, seg.end, seg.center, seg.radius, seg.clockwise)
