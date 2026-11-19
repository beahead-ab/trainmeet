"""Lås mått (CAD-24): a track's positions at both gables locked, and the curve between them made
clean geometry: straight, arc, straight, arc, straight, fitted to the line it replaces (the photo
test's MMM trapezoid became straight 64 – R 645 – straight 188 at 19° – R 645 – straight 25,
median 0,5 mm off the photo's line; lärdomarna, Ren geometri).

The template from P0 with the heading a0 (at right angles to gable A, into the module) to P1
with the heading a1 (at right angles to gable B, out of it):

    s1 straight,  arc R1 turning t1,  s2 straight,  arc R2 turning t2,  s3 straight

with t1 + t2 = a1 - a0, so the direction at gable B is right by construction. An arc of radius R
turning t from the heading h moves the track by the chord 2R·sin(|t|/2) in the direction
h + t/2. Given t1, R1, R2 and s1, the rest is linear:

    s2·u(a0 + t1) + s3·u(a1) = P1 - P0 - s1·u(a0) - chord1 - chord2

two equations in s2 and s3, with the determinant sin(t2). So every candidate ends exactly at P1
with the heading a1, and is tangent at every joint, and the free parameters (t1, R1, R2, s1; or
R1 = R2 with Samma radie) are chosen to lie closest to the old line: the least mean square of
its points' distances, over a coarse grid and then the simplex method (Nelder and Mead), all
deterministic. A candidate is allowed when every straight is at least 0 and every radius at
least the scale's minimum.

There is no solution when no candidate is allowed. Between parallel gables the reason is plain:
moving a track h mm sideways with radii of at least R takes 2R·sin(acos(1 - h/2R)) mm along it
(2R when h ≥ 2R), and a module shorter than that cannot hold it.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from cad import curves
from cad.curves import Line, Seg
from contracts.station_model import Point

BIG = 1e12
MIN_PART = 1e-6
"""A straight or an arc shorter than this, in mm, is nothing and left out of the geometry."""


@dataclass(frozen=True)
class Template:
    s1: float
    r1: float
    t1: float
    s2: float
    r2: float
    t2: float
    s3: float


@dataclass(frozen=True)
class Ends:
    p0: Point
    a0: float
    p1: Point
    a1: float

    @property
    def turn(self) -> float:
        return curves.wrap(self.a1 - self.a0)


def _chord(radius: float, head: float, turn: float) -> Point:
    if abs(turn) < 1e-12:
        return (0.0, 0.0)
    length = 2 * radius * math.sin(abs(turn) / 2)
    return curves.add((0.0, 0.0), curves.unit(head + turn / 2), length)


def build(ends: Ends, t1: float, r1: float, r2: float, s1: float) -> Template | None:
    """The template with these free parameters, or None where it cannot close."""
    t2 = ends.turn - t1
    det = math.sin(t2)
    if abs(det) < 1e-9:
        return None
    beta = ends.a0 + t1
    rest = curves.sub(ends.p1, ends.p0)
    rest = curves.sub(rest, curves.add((0.0, 0.0), curves.unit(ends.a0), s1))
    rest = curves.sub(rest, _chord(r1, ends.a0, t1))
    rest = curves.sub(rest, _chord(r2, beta, t2))
    s2 = curves.cross(rest, curves.unit(ends.a1)) / det
    s3 = curves.cross(curves.unit(beta), rest) / det
    return Template(s1, r1, t1, s2, r2, t2, s3)


def segments(ends: Ends, t: Template) -> list[Seg]:
    """The template as LINE and ARC, parts shorter than MIN_PART left out."""
    found: list[Seg] = []
    at, head = ends.p0, ends.a0
    for kind, size, turn in (
        ("s", t.s1, 0.0),
        ("a", t.r1, t.t1),
        ("s", t.s2, 0.0),
        ("a", t.r2, t.t2),
        ("s", t.s3, 0.0),
    ):
        if kind == "s":
            if size < MIN_PART:
                continue
            seg: Seg = curves.line_from(at, head, size)
        else:
            if size * abs(turn) < MIN_PART:
                continue
            seg = curves.arc_turning(at, head, size, turn)
        found.append(seg)
        at, head = seg.end, curves.end_heading(seg)
    if found:
        # The last end is P1 up to rounding; make it exactly so.
        last = found[-1]
        if isinstance(last, Line):
            found[-1] = Line(last.start, ends.p1)
    return found


def allowed(t: Template, min_radius: float) -> float:
    """0 when the template is allowed, else how far it is from that."""
    worst = 0.0
    for s in (t.s1, t.s2, t.s3):
        worst += max(0.0, -s)
    for r in (t.r1, t.r2):
        worst += max(0.0, min_radius - r) + max(0.0, r - curves.MAX_RADIUS)
    return worst


def _cost(ends: Ends, t: Template, points: Sequence[Point]) -> float:
    segs = segments(ends, t)
    if not segs:
        return BIG
    return sum(curves.distance(segs, p) ** 2 for p in points) / max(1, len(points))


def _nelder_mead(
    f: Callable[[list[float]], float], start: list[float], step: list[float], rounds: int = 400
) -> tuple[list[float], float]:
    """The simplex method, plain and deterministic."""
    simplex = [list(start)]
    for i, size in enumerate(step):
        corner = list(start)
        corner[i] += size
        simplex.append(corner)
    values = [f(x) for x in simplex]
    n = len(start)
    for _ in range(rounds):
        order = sorted(range(n + 1), key=lambda i: values[i])
        simplex = [simplex[i] for i in order]
        values = [values[i] for i in order]
        if abs(values[-1] - values[0]) < 1e-10 * (1 + abs(values[0])):
            break
        centre = [sum(x[i] for x in simplex[:-1]) / n for i in range(n)]
        worst = simplex[-1]
        reflected = [c + (c - w) for c, w in zip(centre, worst, strict=True)]
        fr = f(reflected)
        if fr < values[0]:
            expanded = [c + 2 * (c - w) for c, w in zip(centre, worst, strict=True)]
            fe = f(expanded)
            simplex[-1], values[-1] = (expanded, fe) if fe < fr else (reflected, fr)
        elif fr < values[-2]:
            simplex[-1], values[-1] = reflected, fr
        else:
            contracted = [c + 0.5 * (w - c) for c, w in zip(centre, worst, strict=True)]
            fc = f(contracted)
            if fc < values[-1]:
                simplex[-1], values[-1] = contracted, fc
            else:
                best = simplex[0]
                simplex = [best] + [
                    [b + 0.5 * (x - b) for b, x in zip(best, xs, strict=True)] for xs in simplex[1:]
                ]
                values = [values[0]] + [f(x) for x in simplex[1:]]
    index = min(range(n + 1), key=lambda i: values[i])
    return simplex[index], values[index]


@dataclass(frozen=True)
class Solution:
    template: Template
    segs: list[Seg]
    deviation: list[float]
    """The old line's points' distances from the new geometry."""

    @property
    def median(self) -> float:
        return statistics.median(self.deviation) if self.deviation else 0.0

    @property
    def worst(self) -> float:
        return max(self.deviation, default=0.0)


class NoSolution(Exception):
    """Lås mått cannot close the curve; the message says why, in Swedish."""


def _straight(ends: Ends) -> Template | None:
    """The plain straight, when the gables are parallel and in line."""
    d = curves.sub(ends.p1, ends.p0)
    if abs(ends.turn) > 1e-6 or abs(curves.cross(curves.unit(ends.a0), d)) > 0.05:
        return None
    run = curves.dot(curves.unit(ends.a0), d)
    if run <= 0:
        return None
    return Template(run, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def why_not(ends: Ends, min_radius: float) -> str:
    d = curves.sub(ends.p1, ends.p0)
    along = curves.dot(curves.unit(ends.a0), d)
    side = abs(curves.cross(curves.unit(ends.a0), d))
    if abs(ends.turn) < 1e-6:
        if side <= 2 * min_radius:
            need = 2 * min_radius * math.sin(math.acos(1 - side / (2 * min_radius)))
        else:
            need = 2 * min_radius
        if along < need:
            return (
                f"Spåret ska flytta {side:.0f} mm i sidled mellan gavlarna. Med minsta radien "
                f"{min_radius:.0f} mm behövs minst {need:.0f} mm mellan gavlarna, och här är "
                f"det {max(0.0, along):.0f} mm."
            )
    return (
        f"Inget spår med raka bitar och två bågar på minst R {min_radius:.0f} mm går från gavel A "
        "till gavel B och möter båda gavlarna i rät vinkel."
    )


def solve(ends: Ends, old: Sequence[Point], min_radius: float, same_radius: bool) -> Solution:
    """The template closest to the old line's points, or NoSolution with why."""
    straight = _straight(ends)
    if straight is not None:
        segs = segments(ends, straight)
        return Solution(straight, segs, [curves.distance(segs, p) for p in old])
    coarse = list(old[:: max(1, len(old) // 24)]) or [ends.p0, ends.p1]
    span = math.dist(ends.p0, ends.p1)

    def candidate(x: Sequence[float]) -> Template | None:
        t1 = x[0]
        r1 = math.exp(x[1])
        r2 = math.exp(x[2]) if not same_radius else r1
        s1 = x[-1]
        return build(ends, t1, r1, r2, s1)

    def penalised(points: Sequence[Point]) -> Callable[[list[float]], float]:
        def f(x: list[float]) -> float:
            t = candidate(x)
            if t is None:
                return BIG
            off = allowed(t, min_radius)
            if off > 0:
                return BIG * (1 + off)
            return _cost(ends, t, points)

        return f

    radii = [
        min_radius * 1.25**k for k in range(0, 40) if min_radius * 1.25**k <= curves.MAX_RADIUS
    ]
    turns = [math.radians(d) for d in range(-85, 86, 5) if d != 0]
    starts: list[tuple[float, list[float]]] = []
    f_coarse = penalised(coarse)
    for t1 in turns:
        for r in radii:
            base = build(ends, t1, r, r, 0.0)
            if base is None:
                continue
            for share in (0.0, 0.25, 0.5, 0.75):
                s1 = share * max(0.0, base.s3)
                x = [t1, math.log(r)] + ([] if same_radius else [math.log(r)]) + [s1]
                value = f_coarse(x)
                if value < BIG:
                    starts.append((value, x))
    if not starts:
        raise NoSolution(why_not(ends, min_radius))
    starts.sort(key=lambda item: item[0])
    f_all = penalised(old)
    best: tuple[float, list[float]] | None = None
    for _, x in starts[:4]:
        step = [math.radians(2), 0.1] + ([] if same_radius else [0.1]) + [max(1.0, span * 0.02)]
        found, value = _nelder_mead(f_all, x, step)
        if best is None or value < best[0]:
            best = (value, found)
    assert best is not None
    template = candidate(best[1])
    assert template is not None and allowed(template, min_radius) == 0
    segs = segments(ends, template)
    return Solution(template, segs, [curves.distance(segs, p) for p in old])
