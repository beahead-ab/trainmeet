"""AnyRail's drawn elements as track centre lines (cad/curves.py's LINE and ARC), in mm.

- A line is a LINE.
- An arc is drawn from p1 with its direction: the tangent at p1, pointing out of the arc, read as
  the vector (sin d, cos d) with y down (1. Filformatet, Bågens riktning). An arc with given
  ends and radius can bulge either way; the direction decides it.
- A bezier is a cubic Bézier curve through its four control points, made LINE and ARC as a chain
  of biarcs within FIT_TOLERANCE of the curve, tangent to it at every joint, so that a flex track
  keeps AnyRail's own end directions exactly.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from typing import Final

from cad import curves
from cad.curves import Arc, Line, Seg
from contracts.station_model import Point

FIT_TOLERANCE: Final = 0.1
"""mm: how far the biarcs may lie from AnyRail's Bézier curve."""
MAX_DEPTH: Final = 12


def anyrail_vector(direction: float) -> Point:
    """AnyRail's direction in degrees as a unit vector, y down."""
    d = math.radians(direction)
    return (math.sin(d), math.cos(d))


def anyrail_heading(direction: float) -> float:
    """AnyRail's direction as a heading in cad/curves.py's sense (0 along x, positive turning
    right on the drawing)."""
    v = anyrail_vector(direction)
    return math.atan2(v[1], v[0])


def arc(p1: Point, p2: Point, direction: float) -> Seg | None:
    """The arc from p1 to p2 that leaves p1 against its direction (which points out of the
    arc), so it bulges the way AnyRail drew it."""
    head = anyrail_heading(direction) + math.pi
    return curves.arc_tangent(p1, head, p2)


def arc_without_direction(p1: Point, p2: Point, radius: float) -> Seg | None:
    """The arc a reader would draw from the ends and the radius alone: the shorter arc, turning
    left from p1 to p2 on the drawing. For the report of how many bulge the other way."""
    half = math.dist(p1, p2) / 2
    if half < 1e-9 or radius < half:
        return None
    mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    along = curves.heading(p1, p2)
    rise = math.sqrt(radius * radius - half * half)
    center = curves.add(mid, curves.unit(along - math.pi / 2), rise)
    return Arc(p1, p2, center, radius, False)


def bulges_same(a: Seg, b: Seg) -> bool:
    """Do two segments between the same ends bulge to the same side?"""
    ma = curves.point_at(a, curves.length(a) / 2)
    mb = curves.point_at(b, curves.length(b) / 2)
    side = curves.sub(a.end, a.start)
    return (curves.cross(side, curves.sub(ma, a.start)) >= 0) == (
        curves.cross(side, curves.sub(mb, a.start)) >= 0
    )


# --- Bézier curves ---------------------------------------------------------------------------


def bezier_point(c: Sequence[Point], t: float) -> Point:
    u = 1 - t
    a, b, d, e = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (
        a * c[0][0] + b * c[1][0] + d * c[2][0] + e * c[3][0],
        a * c[0][1] + b * c[1][1] + d * c[2][1] + e * c[3][1],
    )


def bezier_heading(c: Sequence[Point], t: float) -> float:
    """The curve's heading at t; where a handle has no length, the chord ahead or behind."""
    u = 1 - t
    dx = 3 * (
        u * u * (c[1][0] - c[0][0]) + 2 * u * t * (c[2][0] - c[1][0]) + t * t * (c[3][0] - c[2][0])
    )
    dy = 3 * (
        u * u * (c[1][1] - c[0][1]) + 2 * u * t * (c[2][1] - c[1][1]) + t * t * (c[3][1] - c[2][1])
    )
    if math.hypot(dx, dy) > 1e-9:
        return math.atan2(dy, dx)
    if t < 0.5:
        return curves.heading(bezier_point(c, t), bezier_point(c, t + 1e-3))
    return curves.heading(bezier_point(c, t - 1e-3), bezier_point(c, t))


def biarc(p0: Point, h0: float, p1: Point, h1: float) -> list[Seg]:
    """Two arcs from p0 with heading h0 to p1 with heading h1, tangent where they meet (the
    equal-tangent biarc); a line when the ends lie straight ahead."""
    v = curves.sub(p1, p0)
    if math.hypot(*v) < 1e-9:
        return []
    t0, t1 = curves.unit(h0), curves.unit(h1)
    if (
        abs(curves.wrap(h1 - h0)) < 1e-9
        and abs(curves.cross(t0, v)) < 1e-6 * max(1.0, math.hypot(*v))
        and curves.dot(t0, v) > 0
    ):
        return [Line(p0, p1)]
    t = (t0[0] + t1[0], t0[1] + t1[1])
    vt = curves.dot(v, t)
    vv = curves.dot(v, v)
    tt = 2 * (1 - curves.dot(t0, t1))
    if tt < 1e-12:
        if abs(vt) < 1e-12:
            return [Line(p0, p1)]
        d = vv / (2 * vt)
    else:
        d = (-vt + math.sqrt(max(0.0, vt * vt + tt * vv))) / tt
    q0 = curves.add(p0, t0, d)
    q1 = curves.add(p1, t1, -d)
    joint = ((q0[0] + q1[0]) / 2, (q0[1] + q1[1]) / 2)
    first = curves.arc_tangent(p0, h0, joint)
    back = curves.arc_tangent(p1, h1 + math.pi, joint)
    if first is None or back is None:
        return [Line(p0, p1)]
    found = [s for s in (first, curves.reverse(back)) if curves.length(s) > 1e-6]
    return found or [Line(p0, p1)]


def bezier(c: Sequence[Point]) -> list[Seg]:
    """The Bézier curve as LINE and ARC, within FIT_TOLERANCE, with its own end headings."""

    def fit(ta: float, tb: float, depth: int) -> list[Seg]:
        points = [bezier_point(c, ta + (tb - ta) * k / 8) for k in range(9)]
        run = sum(math.dist(a, b) for a, b in itertools.pairwise(points))
        if run < 1e-6:
            return []
        segs = biarc(points[0], bezier_heading(c, ta), points[-1], bezier_heading(c, tb))
        good = bool(segs) and curves.path_length(segs) <= 1.2 * run + 0.5
        if good:
            worst = max(curves.distance(segs, p) for p in points[1:-1])
            good = worst <= FIT_TOLERANCE
        if good:
            return segs
        if depth >= MAX_DEPTH:
            # A curve no biarc follows (a cusp): straight between its points.
            return [Line(a, b) for a, b in itertools.pairwise(points) if a != b]
        middle = (ta + tb) / 2
        return fit(ta, middle, depth + 1) + fit(middle, tb, depth + 1)

    return fit(0.0, 1.0, 0)


def bezier_min_radius(c: Sequence[Point], steps: int = 64) -> float:
    """The smallest radius of curvature along the curve."""
    smallest = math.inf
    for k in range(steps + 1):
        t = k / steps
        u = 1 - t
        d1 = [
            3
            * (
                u * u * (c[1][i] - c[0][i])
                + 2 * u * t * (c[2][i] - c[1][i])
                + t * t * (c[3][i] - c[2][i])
            )
            for i in (0, 1)
        ]
        d2 = [
            6 * (u * (c[2][i] - 2 * c[1][i] + c[0][i]) + t * (c[3][i] - 2 * c[2][i] + c[1][i]))
            for i in (0, 1)
        ]
        speed = math.hypot(d1[0], d1[1])
        bend = abs(d1[0] * d2[1] - d1[1] * d2[0])
        if speed > 1e-9 and bend > 1e-12:
            smallest = min(smallest, speed**3 / bend)
    return smallest


def even_cubic(p0: Point, h0: float, p1: Point, h1: float) -> tuple[Point, Point, Point, Point]:
    """3.2 Utjämning: a smooth cubic with the ends' own headings and handles a third of the chord
    long."""
    third = math.dist(p0, p1) / 3
    return (p0, curves.add(p0, curves.unit(h0), third), curves.add(p1, curves.unit(h1), -third), p1)


def sample(segs: Sequence[Seg], step: float) -> list[Point]:
    return curves.sample_path(segs, step)
