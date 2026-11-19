"""Utjämning (CAD-03): a polyline, drawn by hand or (part c) traced in the photo, made LINE and
ARC within a deviation, as the photo chain's step 12 fits straights and arcs directly instead of
filtering a wavy path afterwards (bildkedjan, point 10 and step 12).

The levels, in H0 (scaled by the gauge in N and 0, cad/switches.py):

- Av: the line stays as drawn, straight pieces between its points.
- Lätt: smallest radius 300 mm, at most 4 mm from the line. 300 mm is the switches' lower limit,
  so a switch's tight diverging leg is kept; 4 mm, a quarter of the gauge, keeps the result on
  the line's own rail-to-rail band, for a line that is already good.
- Normal: smallest radius 400 mm, at most 9 mm from the line (ritningen.jpg). 400 mm is the
  AnyRail import's minimum radius; 9 mm is the error of a line that follows one rail instead of
  the centre (lärdomarna, Kostnadskarta), so such a line still becomes one clean curve.
- Kraftig: smallest radius 600 mm, at most 16,5 mm from the line. A whole gauge: a line that
  wanders from rail to rail; and 600 mm, one and a half times the minimum, for the gentle
  curves of a line module where any tighter arc is a wobble.

The fit: from the line's start, with a heading, the longest run of the line that one straight or
one arc tangent to the heading holds within the deviation is taken, the arc's radius at least
the level's smallest, and the next run starts where that one ended, with its heading. So the
result is tangent-continuous everywhere, and its first point is the line's first point. A
straight is preferred when it holds nearly as long as an arc. The last part is bent to end
exactly in the line's last point. The deviation is the drawn points' distance from the result.
"""

from __future__ import annotations

import itertools
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from cad import curves
from cad.curves import Arc, Line, Seg
from cad.switches import GAUGE, H0_MIN_RADIUS, H0_SWITCH_MIN_RADIUS
from contracts.cad import Deviation, Scale, Smoothing, SmoothingLevel
from contracts.station_model import Point

LINE_PREFERENCE = 0.9
"""A straight is taken when it holds at least this share of the arc's run."""
HEADING_AGREE = math.radians(2)
"""A run ends where the curve runs within 2° of the line's own heading."""


@dataclass(frozen=True)
class Level:
    level: Smoothing
    min_radius: float
    max_deviation: float


def _h0(level: Smoothing) -> tuple[float, float]:
    gauge = GAUGE[Scale.H0]
    return {
        Smoothing.LIGHT: (H0_SWITCH_MIN_RADIUS, gauge / 4),
        Smoothing.NORMAL: (H0_MIN_RADIUS, 9.0),
        Smoothing.STRONG: (H0_MIN_RADIUS * 1.5, gauge),
    }[level]


def level_of(level: Smoothing, scale: Scale) -> Level | None:
    """The level's numbers in the scale; None for Av."""
    if level == Smoothing.OFF:
        return None
    radius, deviation = _h0(level)
    factor = GAUGE[scale] / GAUGE[Scale.H0]
    if scale != Scale.H0:
        radius = round(radius * factor / 10) * 10
        deviation = deviation * factor
    return Level(level, radius, round(deviation, 1))


def _mm(value: float) -> str:
    return f"{value:g}".replace(".", ",")


NAMES = {
    Smoothing.OFF: "Av",
    Smoothing.LIGHT: "Lätt",
    Smoothing.NORMAL: "Normal",
    Smoothing.STRONG: "Kraftig",
}


def levels(scale: Scale) -> list[SmoothingLevel]:
    """The four levels with the texts Ritningen shows."""
    found = [
        SmoothingLevel(
            level=Smoothing.OFF,
            name=NAMES[Smoothing.OFF],
            text="Av: linjen blir kvar som den ritades, raka bitar mellan punkterna.",
        )
    ]
    why = {
        Smoothing.LIGHT: "Följer linjen nära och behåller växlarnas snäva ben.",
        Smoothing.NORMAL: "Knaggliga linjer blir mjuka kurvor.",
        Smoothing.STRONG: "För en linje som vandrar mellan rälerna.",
    }
    for level in (Smoothing.LIGHT, Smoothing.NORMAL, Smoothing.STRONG):
        numbers = level_of(level, scale)
        assert numbers is not None
        found.append(
            SmoothingLevel(
                level=level,
                name=NAMES[level],
                min_radius=numbers.min_radius,
                max_deviation=numbers.max_deviation,
                text=(
                    f"{why[level]} {NAMES[level]}: minsta radie {_mm(numbers.min_radius)} mm "
                    f"och högst {_mm(numbers.max_deviation)} mm från linjen."
                ),
            )
        )
    return found


def deviation(points: Sequence[Point], segs: Sequence[Seg]) -> Deviation:
    """How far the points lie from the segments: median and largest, in mm."""
    if not points or not segs:
        return Deviation(median=0, max=0, count=0)
    found = [curves.distance(segs, p) for p in points]
    return Deviation(
        median=round(statistics.median(found), 2), max=round(max(found), 2), count=len(found)
    )


# --- The fit -----------------------------------------------------------------------------


def _clean(points: Sequence[Point]) -> list[Point]:
    found: list[Point] = []
    for p in points:
        if not found or math.dist(found[-1], p) > 0.01:
            found.append((float(p[0]), float(p[1])))
    return found


def _resample(points: Sequence[Point], step: float) -> list[Point]:
    """The polyline every step mm along it, with both ends."""
    segs: list[Seg] = [Line(a, b) for a, b in itertools.pairwise(points)]
    return curves.sample_path(segs, step)


def _off(p: Point, start: Point, head: float, k: float) -> float:
    """How far p lies from the curve from start with the heading and curvature k (1/mm,
    positive to the right), counting only what lies ahead."""
    if abs(k) < 1e-12:
        d = curves.sub(p, start)
        run = curves.dot(d, curves.unit(head))
        if run < 0:
            return math.dist(p, start)
        return abs(curves.cross(curves.unit(head), d))
    radius = 1 / abs(k)
    center = curves.add(start, curves.unit(head + (math.pi / 2 if k > 0 else -math.pi / 2)), radius)
    return abs(math.dist(center, p) - radius)


def _offs(samples: NDArray[np.float64], start: Point, head: float, k: float) -> NDArray[np.float64]:
    """_off for many points at once."""
    if not len(samples):
        return np.zeros(0)
    if abs(k) < 1e-12:
        u = np.array(curves.unit(head))
        d = samples - np.array(start)
        run = d @ u
        across = np.abs(u[0] * d[:, 1] - u[1] * d[:, 0])
        found: NDArray[np.float64] = np.where(run < 0, np.hypot(d[:, 0], d[:, 1]), across)
        return found
    radius = 1 / abs(k)
    center = np.array(
        curves.add(start, curves.unit(head + (math.pi / 2 if k > 0 else -math.pi / 2)), radius)
    )
    d = samples - center
    found = np.abs(np.hypot(d[:, 0], d[:, 1]) - radius)
    return found


def _worst(samples: NDArray[np.float64], start: Point, head: float, k: float) -> float:
    found = _offs(samples, start, head, k)
    return float(found.max()) if len(found) else 0.0


def _best_k(
    samples: NDArray[np.float64], start: Point, head: float, k_max: float
) -> tuple[float, float]:
    """The curvature in [-k_max, k_max] whose worst deviation is least (it is close to
    unimodal in k), and that deviation."""
    lo, hi = -k_max, k_max
    for _ in range(30):
        m1 = lo + (hi - lo) / 3
        m2 = hi - (hi - lo) / 3
        if _worst(samples, start, head, m1) <= _worst(samples, start, head, m2):
            hi = m2
        else:
            lo = m1
    k = (lo + hi) / 2
    return k, _worst(samples, start, head, k)


def _least_squares_k(
    samples: NDArray[np.float64], start: Point, head: float, k_max: float
) -> float:
    """The curvature whose sum of squared deviations is least: the line through the middle of
    the points rather than the one that only keeps the worst within bounds."""
    lo, hi = -k_max, k_max
    for _ in range(30):
        m1 = lo + (hi - lo) / 3
        m2 = hi - (hi - lo) / 3
        e1 = float((_offs(samples, start, head, m1) ** 2).sum())
        e2 = float((_offs(samples, start, head, m2) ** 2).sum())
        if e1 <= e2:
            hi = m2
        else:
            lo = m1
    return (lo + hi) / 2


def _reach(
    samples: NDArray[np.float64],
    first: int,
    start: Point,
    head: float,
    k_max: float,
    tol: float,
) -> tuple[int, float]:
    """The furthest sample the curve from start holds within tol, and its curvature."""

    def holds(last: int) -> tuple[bool, float]:
        part = samples[first : last + 1]
        if k_max == 0:
            return _worst(part, start, head, 0.0) <= tol, 0.0
        k, worst = _best_k(part, start, head, k_max)
        return worst <= tol, k

    good, best = first, 0.0
    ok, k = holds(first)
    if not ok:
        return first - 1, 0.0
    best = k
    step = 1
    while good + step < len(samples):
        ok, k = holds(good + step)
        if not ok:
            break
        good, best = good + step, k
        step *= 2
    lo, hi = good, min(good + step, len(samples))
    while hi - lo > 1:
        mid = (lo + hi) // 2
        ok, k = holds(mid)
        if ok:
            lo, best = mid, k
        else:
            hi = mid
    return lo, best


def _piece(start: Point, head: float, k: float, to: Point) -> Seg:
    """The curve from start, ended where to projects onto it."""
    if abs(k) < 1e-12:
        run = max(0.0, curves.dot(curves.sub(to, start), curves.unit(head)))
        return curves.line_from(start, head, run)
    radius = 1 / abs(k)
    full = curves.arc_turning(start, head, radius, math.pi if k > 0 else -math.pi)
    assert isinstance(full, Arc)
    phi0 = curves.polar(full.center, start)
    phi = curves.polar(full.center, to)
    turn = (phi - phi0) % curves.TAU if k > 0 else -((phi0 - phi) % curves.TAU)
    return curves.arc_turning(start, head, radius, turn)


def _curve_heading(p: Point, start: Point, head: float, k: float) -> float:
    """The curve's heading where p projects onto it."""
    if abs(k) < 1e-12:
        return head
    center = curves.add(
        start, curves.unit(head + (math.pi / 2 if k > 0 else -math.pi / 2)), 1 / abs(k)
    )
    phi = curves.polar(center, p)
    return phi + math.pi / 2 if k > 0 else phi - math.pi / 2


def _line_headings(samples: Sequence[Point], step: float) -> list[float]:
    """The line's own heading at each sample, over a chord of about 40 mm."""
    w = max(1, math.ceil(20 / step))
    last = len(samples) - 1
    return [
        curves.heading(samples[max(0, i - w)], samples[min(last, i + w)]) for i in range(last + 1)
    ]


def _close_end(
    samples: Sequence[Point] | NDArray[np.float64],
    heads: Sequence[float],
    first: int,
    last: int,
    curve: tuple[Point, float, float],
    tol: float,
) -> int:
    """The furthest sample up to last where the curve passes close to the line and runs along
    it, so that the next run starts on the line, heading its way."""
    start, head, k = curve
    for index in range(last, first, -1):
        p = samples[index]
        if _off(p, start, head, k) > tol:
            continue
        if abs(curves.wrap(_curve_heading(p, start, head, k) - heads[index])) <= HEADING_AGREE:
            return index
    for index in range(last, first, -1):
        if _off(samples[index], start, head, k) <= tol:
            return index
    return last


def _fit(
    points: Sequence[Point], head: float, level: Level, heads: Sequence[float]
) -> tuple[list[Seg], float]:
    """The fit from samples[0] with the heading, and its mean squared deviation.

    Each run is as long as one straight or arc holds the line within the deviation, and ends
    where the curve passes within a quarter of it, so that the next run starts on the line.
    When nothing tangent holds even the next point, the run before is made shorter and tried
    again; only when that cannot help does the line get a corner, as drawn."""
    k_max = 1 / level.min_radius
    tol = level.max_deviation
    samples = np.asarray(points, np.float64)
    count = len(samples)
    done: list[tuple[int, Point, float, Seg, int]] = []
    caps: dict[int, int] = {}
    first, start = 0, (float(samples[0][0]), float(samples[0][1]))
    for _ in range(20 * count):
        if first >= count - 1:
            break
        part = samples[: caps.get(first, count - 1) + 1]
        line_end, _ = _reach(part, first + 1, start, head, 0.0, tol)
        arc_end, k = _reach(part, first + 1, start, head, k_max, tol)
        if max(line_end, arc_end) <= first:
            while done and done[-1][4] - done[-1][0] <= 1 and len(done) > 1:
                done.pop()
            if done and done[-1][4] - done[-1][0] > 1:
                was_first, start, head, _, was_last = done.pop()
                caps[was_first] = was_first + (was_last - was_first) // 2
                first = was_first
                continue
            if done:
                start, head = done[-1][3].end, curves.end_heading(done[-1][3])
                first = done[-1][4]
            last, k = first + 1, 0.0
            head = curves.heading(start, samples[last])
        elif line_end > first and (line_end - first) >= LINE_PREFERENCE * (arc_end - first):
            last, k = line_end, 0.0
        else:
            last = arc_end
            run = samples[first + 1 : last + 1]
            middle = _least_squares_k(run, start, head, k_max)
            if _worst(run, start, head, middle) <= tol:
                k = middle
        if last < count - 1:
            last = _close_end(samples, heads, first, last, (start, head, k), tol / 4)
        seg = _piece(start, head, k, (float(samples[last][0]), float(samples[last][1])))
        if curves.length(seg) > 1e-6:
            done.append((first, start, head, seg, last))
            start = seg.end
            head = curves.end_heading(seg)
        first = last
    segs = [d[3] for d in done]
    if not segs:
        return segs, 0.0
    return segs, sum(curves.distance(segs, p) ** 2 for p in points) / len(points)


def _end_at(segs: list[Seg], end: Point) -> list[Seg]:
    """The last part bent so that the chain ends exactly in end, keeping its start tangent."""
    if not segs:
        return segs
    last = segs[-1]
    head = curves.start_heading(last)
    bent = curves.arc_tangent(last.start, head, end)
    if bent is None or curves.length(bent) < 1e-6:
        return (
            [*segs[:-1], Line(last.start, end)] if math.dist(last.start, end) > 1e-6 else segs[:-1]
        )
    return [*segs[:-1], bent]


def smooth(
    points: Sequence[Point],
    level: Smoothing,
    scale: Scale,
    start_heading: float | None = None,
) -> list[Seg]:
    """The line as LINE and ARC at the level, from its first point to its last. start_heading
    holds the start to a track it continues."""
    clean = _clean(points)
    if len(clean) < 2:
        raise ValueError("Linjen har för få punkter.")
    numbers = level_of(level, scale)
    if numbers is None:
        return [Line(a, b) for a, b in itertools.pairwise(clean)]
    return _smooth(clean, numbers, start_heading)


def fit(
    points: Sequence[Point],
    min_radius: float,
    max_deviation: float,
    start_heading: float | None = None,
    step: float | None = None,
) -> list[Seg]:
    """The line as LINE and ARC with the given smallest radius and largest deviation: the
    photo chain's fit of a track it traced (bildkedjan step 12), tighter than any level. step
    is how often the line is sampled, mm."""
    clean = _clean(points)
    if len(clean) < 2:
        raise ValueError("Linjen har för få punkter.")
    return _smooth(clean, Level(Smoothing.LIGHT, min_radius, max_deviation), start_heading, step)


def _smooth(
    clean: list[Point], numbers: Level, start_heading: float | None, step: float | None = None
) -> list[Seg]:
    step = step or max(1.0, min(5.0, numbers.max_deviation / 2))
    samples = _resample(clean, step)
    if start_heading is not None:
        segs, _ = _fit(samples, start_heading, numbers, _line_headings(samples, step))
    else:
        ahead = next(
            (
                p
                for p in samples
                if math.dist(p, samples[0])
                >= min(
                    30.0,
                    curves.path_length([Line(a, b) for a, b in itertools.pairwise(clean)]) / 3,
                )
            ),
            samples[-1],
        )
        chord = curves.heading(samples[0], ahead)
        heads = _line_headings(samples, step)
        best: tuple[tuple[int, int, float], list[Seg]] | None = None
        tries = [chord + math.radians(d) for d in (0, -1, 1, -3, 3, -6, 6)]
        tries.append(curves.heading(samples[0], samples[-1]))
        for head in tries:
            segs, spread = _fit(samples, head, numbers, heads)
            # Fewest parts first, then straights before arcs (clean geometry), then closest.
            rank = (len(segs), sum(isinstance(x, Arc) for x in segs), spread)
            if best is None or rank < best[0]:
                best = (rank, segs)
        assert best is not None
        segs = best[1]
    return _end_at(segs, clean[-1])
