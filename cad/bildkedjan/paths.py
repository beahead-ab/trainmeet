"""Step 11 of the chain, the code's part: the gable tracks, the ends inside the module, and the
cheapest path on the track map between them (bildkedjan, Topologi; lärdomarna, Kopplingar).

A module's tracks go from gable to gable, or from a gable to an end inside it, and run on
along the module: within a module no track turns back on itself. So a path is y as a function
of x, from one gable or end toward the other, and the cheapest one is found column by column,
every DX mm of x, with y every half millimetre, as dynamic programming (Viterbi). A step costs
what the map says the place is not a track, and what its direction differs from the track's
there. A train never reverses on the way, and the path cannot either.

The path also carries its slope from step to step, and the slope changes by at most one step
of SLOPE_BIN at a time, at a cost (del c2): a track bends, it never jumps. At low resolution the
map is weak where a switch's legs overlap, and a path that may jump takes the short way across
to the next track there; one that must bend follows the leg (bildkedjan, Vad fotona visar,
point 10: fit to the track map, with the path only as the start).

A path between two ends is accepted as a connection when it stays on track (TRACK_SHARE of it
over the map's TRACK_SCORE, and no gap longer than GAP_MM) and never turns sharper than a
switch may (the scale's lower limit for a switch radius). A path with a longer gap, but not too
long, is a hidden part: under something or in a shadow, an Osäkert parti (bildkedjan step 15,
Spår dolt). Everything else is no connection.

The ends inside the module are found where the map's ridge (the line of its highest values
across the track) ends and nothing continues ahead of it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from cad.bildkedjan.camera import Array, Shape
from cad.bildkedjan.trackmap import TRACK_SCORE, GableStrip, TrackMap, sample

Y_STEP = 0.5
"""The paths' resolution across the module, mm."""
DX = 8
"""The paths' step along the module, mm."""
KMAX = 16
"""The steepest slope, in Y_STEP per DX: 1 mm per mm, 45°."""
SLOPE_BIN = Y_STEP / DX
"""One step of slope: 0,125 mm per mm, 7°."""
BEND_COST = 10.0
"""What a change of slope by one step costs: a long weak stretch on a track, where a switch's
legs overlap, is cheaper than a bend across to the next track and back."""
WIDEN_MM = 5.0
START_SLOPE = 1
"""A track leaves a gable nearly square: its first slope at most this many steps."""
DIRECTION_WEIGHT = 2.0
OFF_TRACK_WEIGHT = 1.5
"""What a millimetre off the track costs more than one on a track's poorer stretch, such as
where two tracks overlap in a switch."""
TRACK_SHARE = 0.9
GAP_MM = 30.0
"""Spår dolt: a gap longer than this is a hidden part (bildkedjan step 15)."""
HIDDEN_SHARE = 0.75
HIDDEN_GAP_MM = 120.0
END_CLEAR_MM = 40.0
"""An end inside the module lies at least this far from the gables and sides."""
END_AHEAD_MM = 40.0
END_FOLLOW_MM = 30.0
"""How far an end found where the ridge stops is moved on along the track while the map still
sees it, mm: the ridge often stops a few millimetres short (part c2)."""
END_RIDGE_AHEAD_MM = 100.0
"""Nor may a ridge in line with it go on within this far: a track that only breaks where it
crosses another, at a shallow angle, goes on beyond the crossing."""
END_RIDGE_CONE = 6.0
END_RIDGE_ALIGN = 25.0
END_MERGE_MM = 30.0
END_SIDE_MM = 8.0
BRANCH_MM = 25.0
"""A ridge's end must run this far before it forks to be a track's end."""
KINK_RUN_MM = 20.0
"""How long a straight line is fitted on each side of a bend: the columns' half millimetres
average out over it."""
KINK_GAP_MM = 6.0
STEP_MM = 1.25
"""A step across, mm per mm of x, steeper than any track in a module."""
SMOOTH_MM = 4.0
SHARP_SHARE = 0.8
"""A bend sharper than this share of the lower limit for a switch radius is no track: two
tracks crossing, or a jump between them."""
RIDGE_SCORE = 0.35
"""The map's ridge counts from here: the track's middle, not the ballast's edge beside it."""
RIDGE_MIN_MM = 60.0


@dataclass(frozen=True)
class Terminal:
    """Where a track starts or ends: a gable's track (A1, B2 …) or an end inside (E1 …)."""

    id: str
    kind: str
    """gable or end"""
    at: tuple[float, float]
    gable: str | None = None
    track: int | None = None
    out: float | None = None
    """An end's heading out of the track, beyond its end, in radians: no path leaves that way."""

    def beyond(self, other: Terminal) -> bool:
        """The other terminal lies past this end, where the track does not go."""
        if self.kind != "end" or self.out is None:
            return False
        return (other.at[0] - self.at[0]) * math.cos(self.out) > 0


@dataclass
class Path:
    a: str
    b: str
    xs: Array
    ys: Array
    share: float
    gap: float
    sharpest: float
    """The smallest radius it turns with, mm."""
    status: str = "track"
    """track, hidden or none."""
    scores: Array = field(default_factory=lambda: np.zeros(0))

    @property
    def pair(self) -> tuple[str, str]:
        return (self.a, self.b) if self.a < self.b else (self.b, self.a)

    def points(self) -> Array:
        return np.stack([self.xs, self.ys], axis=1)


@dataclass
class Columns:
    """The map in columns: x every mm, y every Y_STEP, with each place's score and direction,
    and the steps' costs once worked out, the same for every start."""

    xs: Array
    ys: Array
    score: NDArray[Any]
    direction: NDArray[Any]
    costs: NDArray[Any] | None = None

    def steps(self) -> NDArray[Any]:
        """The cost of arriving at each coarse column (every DX mm), row and slope, from the
        column before: (columns, 2·KMAX + 1, rows)."""
        if self.costs is None:
            self.costs = _step_costs(self)
        return self.costs


def columns(
    tracks: TrackMap, x_range: tuple[float, float], y_range: tuple[float, float]
) -> Columns:
    xs = np.arange(math.floor(x_range[0]), math.ceil(x_range[1]) + 1, 1.0)
    ys = np.arange(y_range[0], y_range[1] + Y_STEP / 2, Y_STEP)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    px = tracks.grid.to_px(np.stack([gx.ravel(), gy.ravel()], axis=1))
    # The map's ridge is a millimetre or two wide; a path whose slope comes in steps of
    # SLOPE_BIN runs beside it now and then. Widened, it stays on the track; the track's middle
    # is found to a fraction of a millimetre afterwards (trackmap.refine_path).
    wide = round(WIDEN_MM * tracks.grid.ppm) | 1
    widened = cv2.dilate(tracks.score, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (wide, wide)))
    score = sample(widened, px[:, 0], px[:, 1]).reshape(gx.shape).astype(np.float32)
    ix = np.clip(np.round(px[:, 0]).astype(int), 0, tracks.grid.width - 1)
    iy = np.clip(np.round(px[:, 1]).astype(int), 0, tracks.grid.height - 1)
    direction = tracks.direction[iy, ix].reshape(gx.shape)
    return Columns(xs, ys, score, direction)


def _step_costs(cols: Columns) -> NDArray[Any]:
    """Each coarse column's cost for each slope k (rows per DX) and row it arrives at: the mm
    of x before it, each at the row the slope gives there, costing what the map says it is not
    a track, off a track more, and what the slope differs from the map's direction."""
    s = cols.score
    unit = (1 - s) + OFF_TRACK_WEIGHT * np.maximum(0.0, TRACK_SCORE - s) / TRACK_SCORE
    count = (len(cols.xs) - 1) // DX + 1
    rows = len(cols.ys)
    found = np.full((count, 2 * KMAX + 1, rows), np.inf, np.float32)
    found[0] = 0.0
    starts = np.arange(1, count) * DX
    for j, k in enumerate(range(-KMAX, KMAX + 1)):
        rise = k * Y_STEP / DX
        phi = math.atan(rise)
        length = math.hypot(1.0, rise)
        total = np.zeros((count - 1, rows), np.float32)
        for t in range(1, DX + 1):
            # t mm into the step that arrives at row r, the path is at row r - k·(DX - t)/DX.
            back = round(k * (DX - t) / DX)
            column = starts - DX + t
            costs = unit[column] + DIRECTION_WEIGHT * np.sin(phi - cols.direction[column]) ** 2
            shifted = np.full((count - 1, rows), np.inf, np.float32)
            if back >= 0:
                shifted[:, back:] = costs[:, : rows - back] if back else costs
            else:
                shifted[:, :back] = costs[:, -back:]
            total += shifted * length
        found[1:, j] = total
    return found


@dataclass(frozen=True)
class Run:
    """The dynamic programming from one start: the cost to every place and slope, and the way
    back, from the start's coarse column on."""

    start: int
    cost: NDArray[Any]
    back: NDArray[np.int8]


def run(cols: Columns, start: tuple[float, float], slopes: tuple[int, int] | None = None) -> Run:
    """The cheapest smooth paths from start toward larger x. slopes: the first slope's range,
    in steps; None: square to a gable."""
    every = cols.steps()
    count, k2, rows = every.shape
    c0 = max(0, min(count - 1, round((start[0] - cols.xs[0]) / DX)))
    r0 = max(0, min(rows - 1, round((start[1] - cols.ys[0]) / Y_STEP)))
    lo, hi = slopes if slopes is not None else (-START_SLOPE, START_SLOPE)
    cost = np.full((count - c0, k2, rows), np.inf, np.float32)
    back = np.zeros((count - c0, k2, rows), np.int8)
    for k in range(max(-KMAX, lo), min(KMAX, hi) + 1):
        cost[0, k + KMAX, r0] = 0.0
    bend = np.float32(BEND_COST)
    for i in range(1, count - c0):
        previous = cost[i - 1]
        here = every[c0 + i]
        for j in range(k2):
            k = j - KMAX
            # Arriving at row r with the slope k came from row r - k, with the slope k, or one
            # step either side.
            options = []
            for d in (-1, 0, 1):
                jp = j + d
                if not 0 <= jp < k2:
                    continue
                came = np.full(rows, np.inf, np.float32)
                if k >= 0:
                    came[k:] = previous[jp, : rows - k] if k else previous[jp]
                else:
                    came[:k] = previous[jp, -k:]
                options.append((d, came + (bend if d else 0)))
            stack = np.stack([o for _, o in options])
            best = np.argmin(stack, axis=0)
            cost[i, j] = stack[best, np.arange(rows)] + here[j]
            back[i, j] = np.array([d for d, _ in options], np.int8)[best]
    return Run(c0, cost, back)


def trace(cols: Columns, done: Run, target: tuple[float, float]) -> tuple[Array, Array] | None:
    """The path from the run's start to target, as x and y every mm of x, from smaller x."""
    index = round((target[0] - cols.xs[0]) / DX) - done.start
    if index == len(done.cost) and target[0] <= cols.xs[-1] + DX:
        index -= 1  # the last coarse column, within a step of the module's end
    if index <= 0 or index >= len(done.cost):
        return None
    r = round((target[1] - cols.ys[0]) / Y_STEP)
    if not 0 <= r < done.cost.shape[2]:
        return None
    j = int(np.argmin(done.cost[index, :, r]))
    if not np.isfinite(done.cost[index, j, r]):
        return None
    rows = [r]
    for i in range(index, 0, -1):
        k = j - KMAX
        j = j + int(done.back[i, j, r])
        r = r - k
        rows.append(r)
    rows.reverse()
    coarse_x = cols.xs[0] + (done.start + np.arange(index + 1)) * DX
    coarse_y = cols.ys[np.clip(rows, 0, len(cols.ys) - 1)]
    xs = np.arange(coarse_x[0], coarse_x[-1] + 0.5, 1.0)
    ys = np.interp(xs, coarse_x, coarse_y)
    return xs.astype(np.float64), ys.astype(np.float64)


def headings(xs: Array, ys: Array, window: float = 6.0) -> Array:
    """The path's heading at each point, from the points window mm before and after it."""
    n = len(xs)
    w = max(1, int(window))
    lo = np.clip(np.arange(n) - w, 0, n - 1)
    hi = np.clip(np.arange(n) + w, 0, n - 1)
    found: Array = np.arctan2(ys[hi] - ys[lo], xs[hi] - xs[lo])
    return found


def smoothed(ys: Array, sigma: float = SMOOTH_MM) -> Array:
    """y with the half-millimetre steps of the columns smoothed away (x every mm)."""
    if len(ys) < 3:
        return ys
    radius = int(3 * sigma)
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(ys, radius, mode="edge")
    found: Array = np.convolve(padded, kernel, mode="valid")
    return found


def _slopes(ys: Array, length: int) -> Array:
    """The least squares slope of y over each run of length points (x every mm)."""
    t = np.arange(length, dtype=np.float64)
    weights = (t - t.mean()) / ((t - t.mean()) ** 2).sum()
    found: Array = np.lib.stride_tricks.sliding_window_view(ys, length) @ weights
    return found


def _kinks_in(ys: Array) -> Array:
    run, gap = int(KINK_RUN_MM), int(KINK_GAP_MM)
    if len(ys) < 2 * (run + gap) + 2:
        return np.zeros(0)
    slopes = _slopes(ys, run)
    before = slopes[: len(slopes) - run - 2 * gap]
    after = slopes[run + 2 * gap :]
    count = min(len(before), len(after))
    found: Array = np.abs(np.arctan(after[:count]) - np.arctan(before[:count]))
    return found


def kinks(xs: Array, ys: Array) -> Array:
    """How much the path turns, every place it can be told: the angle between straight lines
    fitted over KINK_RUN_MM on each side of a point, within the stretches between steps; and
    across each step, where the path moves from one track to the next where they overlap in a
    switch, the angle between the lines before and after it. A crossing's corner is a turn
    without a step."""
    step = np.abs(np.diff(ys)) >= STEP_MM
    found: list[Array] = []
    start = 0
    run = int(KINK_RUN_MM)
    edges = [int(i) for i in np.nonzero(step)[0]] + [len(ys) - 1]
    for edge in edges:
        found.append(_kinks_in(ys[start : edge + 1]))
        if edge < len(ys) - 1:
            lo, hi = max(0, edge - run), edge + 1
            after_lo, after_hi = edge + 1, min(len(ys), edge + 1 + run)
            if hi - lo >= run // 2 and after_hi - after_lo >= run // 2:
                t0 = np.arange(hi - lo, dtype=np.float64)
                t1 = np.arange(after_hi - after_lo, dtype=np.float64)
                a = np.polyfit(t0, ys[lo:hi], 1)[0]
                b = np.polyfit(t1, ys[after_lo:after_hi], 1)[0]
                # Across a step the turn counts over the span the lines are apart.
                turn = abs(math.atan(b) - math.atan(a))
                found.append(np.array([turn]))
        start = edge + 1
    return np.concatenate(found) if found else np.zeros(0)


KINK_SPAN = KINK_RUN_MM + 2 * KINK_GAP_MM
"""The distance between the two lines' middles, mm."""


def sharpest_radius(xs: Array, ys: Array) -> float:
    """The smallest radius the path's bends correspond to, mm: a turn of the angle a between
    lines KINK_SPAN mm apart is a radius KINK_SPAN / a."""
    found = kinks(xs, ys)
    worst = float(found.max()) if len(found) else 0.0
    return KINK_SPAN / worst if worst > 1e-9 else math.inf


def judge(path: Path, min_radius: float, looser: float = 1.0) -> None:
    """track, hidden or none, by the map along it and how sharply it turns. looser: at low
    resolution the map is weak over a switch's overlap for longer (bildkedjan step 3: the
    tolerances are widened), so a longer gap and a little less share are a track."""
    on = path.scores >= TRACK_SCORE
    path.share = float(on.mean()) if len(on) else 0.0
    gap = longest = 0
    for value in on:
        gap = 0 if value else gap + 1
        longest = max(longest, gap)
    path.gap = float(longest)
    path.sharpest = sharpest_radius(path.xs, path.ys)
    looser = max(1.0, looser)
    share = TRACK_SHARE - (LOW_SHARE if looser > 1.0 else 0.0)
    if path.sharpest < SHARP_SHARE * min_radius:
        path.status = "none"
    elif path.share >= share and path.gap <= GAP_MM * looser:
        path.status = "track"
    elif path.share >= HIDDEN_SHARE and path.gap <= HIDDEN_GAP_MM * looser:
        path.status = "hidden"
    else:
        path.status = "none"


LOW_SHARE = 0.05
"""How much less of a path must be clear on the map at low resolution."""


CONCENTRIC_STEP = 1.0
"""A curve module's track as a concentric arc is sampled every this many mm of x."""
CONCENTRIC_SIDE_MM = 3.0
"""And may lie this far beside the arc and still be on it, where the photo's track wanders."""


def _on_arc(
    cols: Columns, shape: Shape, v_a: float, v_b: float
) -> tuple[Array, Array, float, int, Array] | None:
    """The arc from gable A to gable B, its distance from Kant 1 going from v_a to v_b, when
    the map is on it as for any path (TRACK_SHARE, GAP_MM), within CONCENTRIC_SIDE_MM beside
    it: x, y, the share on it, the longest gap and the map along it."""
    assert shape.angle is not None
    angles = np.linspace(0.0, shape.angle, 400)
    arc = np.array([shape.point(v_a + (v_b - v_a) * a / shape.angle, float(a)) for a in angles])
    if (np.diff(arc[:, 0]) <= 0).any():
        return None
    xs = np.arange(math.ceil(arc[0, 0]), math.floor(arc[-1, 0]) + 1, CONCENTRIC_STEP)
    if len(xs) < 20:
        return None
    ys = np.interp(xs, arc[:, 0], arc[:, 1])
    best = np.max(
        np.stack(
            [
                sample_map(cols, xs, ys + side)
                for side in np.arange(-CONCENTRIC_SIDE_MM, CONCENTRIC_SIDE_MM + 0.01, Y_STEP)
            ]
        ),
        axis=0,
    )
    on = best >= TRACK_SCORE
    share = float(on.mean())
    gap = longest = 0
    for value in on:
        gap = 0 if value else gap + 1
        longest = max(longest, gap)
    if share < TRACK_SHARE or longest > GAP_MM:
        return None
    return xs, ys, share, longest, best


def concentric(
    cols: Columns,
    terminals: list[Terminal],
    found: list[Path],
    strips: Sequence[GableStrip],
    shape: Shape,
    gauge: float,
) -> tuple[list[Terminal], list[Path]]:
    """A curve module's tracks follow its arcs (bildkedjan step 6, part c3): a gable's track
    that no smooth path joins to the other gable is tried as the concentric arc from it, at
    its distance from Kant 1 (or to the other gable's track within a gauge of that), and is a
    track when the map is on it as for any path (TRACK_SHARE, GAP_MM), within
    CONCENTRIC_SIDE_MM beside it. A track the other gable's strip did not show gets a gable
    end there. The gables' tracks are numbered again from Kant 1."""
    assert shape.angle is not None
    gables = {g: [t for t in terminals if t.kind == "gable" and t.gable == g] for g in "AB"}

    def along(t: Terminal) -> float:
        strip = strips[0 if t.gable == "A" else 1]
        return float(
            (t.at[0] - strip.corner[0]) * strip.along[0]
            + (t.at[1] - strip.corner[1]) * strip.along[1]
        )

    made: list[Terminal] = []
    added: list[Path] = []
    for start_end, other_end in (("A", "B"), ("B", "A")):
        for t in gables[start_end]:
            v = along(t)
            others = gables[other_end] + [m for m in made if m.gable == other_end]
            near = min(others, key=lambda o: abs(along(o) - v), default=None)
            if any(t.id in (p.a, p.b) for p in added) or any(
                t.id in (p.a, p.b) and p.status == "track" for p in found
            ):
                continue
            # To the other gable's track within a gauge, else (or when that is no arc the map
            # follows: a peak in its strip that is something else, part c5) at its own
            # distance from Kant 1, with a new gable end there.
            tries: list[Terminal | None] = [None]
            if near is not None and abs(along(near) - v) <= gauge:
                tries.insert(0, near)
            chosen: tuple[Terminal | None, Array, Array, float, int, Array] | None = None
            for target in tries:
                v_other = along(target) if target is not None else v
                v_a, v_b = (v, v_other) if start_end == "A" else (v_other, v)
                if not (0 < v_a < shape.width_a and 0 < v_b < shape.width_b):
                    continue
                on_arc = _on_arc(cols, shape, v_a, v_b)
                if on_arc is not None:
                    chosen = (target, *on_arc)
                    break
            if chosen is None:
                continue
            target, xs, ys, share, longest, best = chosen
            v_other = along(target) if target is not None else v
            v_a, v_b = (v, v_other) if start_end == "A" else (v_other, v)
            if target is None:
                strip = strips[1 if start_end == "A" else 0]
                at = strip.points(np.array([v]), 0.0)[0]
                target = Terminal(
                    f"{other_end}+{len(made) + 1}",
                    "gable",
                    (float(at[0]), float(at[1])),
                    other_end,
                    None,
                )
                made.append(target)
            first, last = (t, target) if t.at[0] <= target.at[0] else (target, t)
            radius = shape.radius - (v_a + v_b) / 2 if shape.radius is not None else math.inf
            added.append(
                Path(first.id, last.id, xs, ys, share, float(longest), radius, "track", best)
            )
    if not added:
        return terminals, found
    pairs = {p.pair for p in added}
    kept_paths = [p for p in found if p.pair not in pairs] + added
    everything = terminals + made
    # The gables' tracks numbered again from Kant 1.
    rename: dict[str, str] = {}
    renumbered: list[Terminal] = []
    for end in ("A", "B"):
        own = sorted((t for t in everything if t.kind == "gable" and t.gable == end), key=along)
        for n, t in enumerate(own, start=1):
            rename[t.id] = f"{end}{n}"
            renumbered.append(Terminal(f"{end}{n}", t.kind, t.at, t.gable, n, t.out))
    renumbered.extend(t for t in everything if t.kind != "gable")
    for p in kept_paths:
        p.a, p.b = rename.get(p.a, p.a), rename.get(p.b, p.b)
    return renumbered, sorted(kept_paths, key=lambda p: p.pair)


Refiner = Callable[[Array, Array], Array]
"""y along a path made exact: from the columns' half millimetres to the track's middle."""


def _first_slopes(source: Terminal) -> tuple[int, int] | None:
    """A gable's track leaves it square; an end's track leaves it away from its end."""
    if source.kind != "end" or source.out is None:
        return None
    back = source.out + math.pi
    slope = math.tan(back) if math.cos(back) > 0.2 else 0.0
    k = round(max(-1.0, min(1.0, slope)) / SLOPE_BIN)
    return (k - 2, k + 2)


def connect(
    cols: Columns,
    terminals: list[Terminal],
    min_radius: float,
    refiner: Refiner | None = None,
    looser: float = 1.0,
) -> list[Path]:
    """Every pair of terminals the cheapest smooth path joins, judged, from the one at the
    smaller x."""
    found: dict[tuple[str, str], Path] = {}
    for source in terminals:
        targets = [
            t
            for t in terminals
            if t.id != source.id
            and t.at[0] > source.at[0] + 50
            and not source.beyond(t)
            and not t.beyond(source)
        ]
        if not targets:
            continue
        done = run(cols, source.at, _first_slopes(source))
        for target in targets:
            pair = (source.id, target.id) if source.id < target.id else (target.id, source.id)
            traced = trace(cols, done, target.at)
            if traced is None:
                continue
            xs, ys = traced
            if refiner is not None:
                ys = refiner(xs, ys)
            scores = sample_map(cols, xs, ys)
            path = Path(source.id, target.id, xs, ys, 0, 0, 0, "none", scores)
            judge(path, min_radius, looser)
            previous = found.get(pair)
            if previous is None or _better(path, previous):
                found[pair] = path
    return sorted(found.values(), key=lambda p: p.pair)


OVERLAP_GAUGES = 2.0
"""Two paths closer than this many gauges share their rails' surroundings: a switch's points
and its frog, where the map is weak because three or four rails lie in the profile."""
OVERLAP_SHARE = 0.6
SAME_MM = 1.5
"""Two paths closer than this run on the same track."""
"""A path whose map is clear over less than this share, even where it overlaps, is no track."""
PARTING_MM = 80.0
"""Where two paths part, they ran as one for this far before: a switch's points and its legs'
first stretch, from the blade tips to where the legs lie SAME_MM apart (R 1880: about 75 mm),
where the map is as weak as where they lie beside each other (part c6)."""


def overlaps(found: list[Path], gauge: float, min_radius: float) -> None:
    """The paths judged again where they overlap another smooth path (bildkedjan step 11). In a
    switch the diverging leg runs within a gauge of the straight one for some distance, and at
    low resolution the map is weak there over more than GAP_MM: that gap belongs to the switch,
    not to a hidden part. A path that is smooth (never sharper than a switch may turn), clear on
    the map elsewhere, and whose weak stretches all lie where another smooth path runs beside it,
    is a track."""
    smooth = [p for p in found if p.sharpest >= SHARP_SHARE * min_radius and len(p.xs) > 1]
    limit = OVERLAP_GAUGES * gauge
    for path in smooth:
        if path.status == "track" or not len(path.scores):
            continue
        near = np.zeros(len(path.xs), bool)
        for other in smooth:
            if other is path:
                continue
            lo, hi = float(other.xs[0]), float(other.xs[-1])
            inside = (path.xs >= lo) & (path.xs <= hi)
            if not inside.any():
                continue
            ys = np.interp(path.xs, other.xs, other.ys)
            apart = np.abs(ys - path.ys)
            # Beside it, not on the same track: the same route twice is no switch. But where
            # the two part, the stretch they ran as one just before is the switch's too.
            beside = inside & (apart <= limit) & (apart >= SAME_MM)
            near |= beside | _before_parting(path.xs, inside & (apart < SAME_MM), beside)
        on = (path.scores >= TRACK_SCORE) | near
        share = float(on.mean())
        gap = longest = 0
        for value in on:
            gap = 0 if value else gap + 1
            longest = max(longest, gap)
        clear = path.scores[~near]
        clear_share = float((clear >= TRACK_SCORE).mean()) if len(clear) else 0.0
        if share >= TRACK_SHARE and longest <= GAP_MM and clear_share >= OVERLAP_SHARE:
            path.status = "track"
            path.gap = float(longest)


def _before_parting(xs: Array, same: Array, beside: Array) -> Array:
    """Where two paths run as one within PARTING_MM of where they part: the end of a run of
    same next to beside, on either side."""
    found = np.zeros(len(xs), bool)
    edges = np.diff(np.concatenate([[0], same.astype(np.int8), [0]]))
    for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True):
        run = xs[start:end]
        if start > 0 and beside[start - 1]:
            found[start:end] |= run <= run[0] + PARTING_MM
        if end < len(same) and beside[end]:
            found[start:end] |= run >= run[-1] - PARTING_MM
    return found


def _better(path: Path, other: Path) -> bool:
    rank = {"track": 2, "hidden": 1, "none": 0}
    return (rank[path.status], path.share) > (rank[other.status], other.share)


def sample_map(cols: Columns, xs: Array, ys: Array) -> Array:
    ci = np.clip(np.round(xs - cols.xs[0]).astype(int), 0, len(cols.xs) - 1)
    ry = (ys - cols.ys[0]) / Y_STEP
    r0 = np.clip(np.floor(ry).astype(int), 0, len(cols.ys) - 1)
    r1 = np.clip(r0 + 1, 0, len(cols.ys) - 1)
    t = np.clip(ry - r0, 0, 1)
    found: Array = cols.score[ci, r0] * (1 - t) + cols.score[ci, r1] * t
    return found


# --- The ends inside the module ----------------------------------------------------------------


def thin(image: NDArray[Any]) -> NDArray[Any]:
    """Zhang and Suen's thinning: a ridge a pixel wide, so that its ends have one neighbour."""
    img = (image > 0).astype(np.uint8)
    while True:
        changed = False
        for step in (0, 1):
            p = np.pad(img, 1)
            n = [
                p[:-2, 1:-1],
                p[:-2, 2:],
                p[1:-1, 2:],
                p[2:, 2:],
                p[2:, 1:-1],
                p[2:, :-2],
                p[1:-1, :-2],
                p[:-2, :-2],
            ]  # P2 … P9, clockwise from above
            b = sum(x.astype(np.int16) for x in n)
            a = sum(((n[i] == 0) & (n[(i + 1) % 8] == 1)).astype(np.int16) for i in range(8))
            if step == 0:
                c = n[0] * n[2] * n[4]
                d = n[2] * n[4] * n[6]
            else:
                c = n[0] * n[2] * n[6]
                d = n[0] * n[4] * n[6]
            remove = (img == 1) & (b >= 2) & (b <= 6) & (a == 1) & (c == 0) & (d == 0)
            if remove.any():
                img[remove] = 0
                changed = True
        if not changed:
            return img


def crossings(image: NDArray[Any]) -> NDArray[np.int16]:
    """For each pixel of a thin line, how many separate runs of line pixels lie around it:
    1 at an end, 2 along the line, 3 or more at a fork. A step of a staircase is 2."""
    p = np.pad((image > 0).astype(np.int16), 1)
    n = [
        p[:-2, 1:-1],
        p[:-2, 2:],
        p[1:-1, 2:],
        p[2:, 2:],
        p[2:, 1:-1],
        p[2:, :-2],
        p[1:-1, :-2],
        p[:-2, :-2],
    ]
    found: NDArray[np.int16] = sum(
        ((n[i] == 0) & (n[(i + 1) % 8] == 1)).astype(np.int16) for i in range(8)
    )
    return found


def _branch(ridge: NDArray[Any], neighbours: NDArray[np.int16], row: int, col: int) -> int:
    """How many pixels the ridge runs from an end before it forks."""
    h, w = ridge.shape
    seen = {(row, col)}
    at = (row, col)
    for steps in range(1, 200):
        r, c = at
        nxt = [
            (r + dr, c + dc)
            for dr in (-1, 0, 1)
            for dc in (-1, 0, 1)
            if (dr or dc)
            and 0 <= r + dr < h
            and 0 <= c + dc < w
            and ridge[r + dr, c + dc]
            and (r + dr, c + dc) not in seen
        ]
        if not nxt or neighbours[at] >= 3:
            return steps
        # Along a staircase a step has two pixels ahead: the nearer one, straight on.
        at = min(nxt, key=lambda q: abs(q[0] - r) + abs(q[1] - c))
        seen.add(at)
        if neighbours[at] >= 3:
            return steps
        r, c = at
    return 200


def _along_ridge(ridge: NDArray[Any], row: int, col: int, steps: int) -> list[tuple[int, int]]:
    """The ridge's pixels within steps of (row, col), walking along the ridge."""
    h, w = ridge.shape
    seen = {(row, col)}
    edge = [(row, col)]
    for _ in range(steps):
        nxt: list[tuple[int, int]] = []
        for r, c in edge:
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    q = (r + dr, c + dc)
                    if q not in seen and 0 <= q[0] < h and 0 <= q[1] < w and ridge[q]:
                        seen.add(q)
                        nxt.append(q)
        if not nxt:
            break
        edge = nxt
    return sorted(seen)


def _ridge_ahead(
    ridge: NDArray[Any], theta: NDArray[Any], at: Array, out: Array, ppm: float
) -> bool:
    """A ridge in line ahead of an end, running the same way: the track goes on. The end's own
    ridge lies behind it."""
    h, w = ridge.shape
    heading = math.atan2(out[1], out[0])
    for d in np.arange(12.0, END_RIDGE_AHEAD_MM, 1.0) * ppm:
        for turn in np.radians(np.arange(-END_RIDGE_CONE, END_RIDGE_CONE + 0.1, 1.5)):
            x = round(at[0] + d * math.cos(heading + turn))
            y = round(at[1] + d * math.sin(heading + turn))
            if not (0 <= x < w and 0 <= y < h):
                continue
            window = ridge[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2]
            if not window.any():
                continue
            hits = np.argwhere(window > 0) + np.array([max(0, y - 1), max(0, x - 1)])
            for r, c in hits:
                along = abs(math.remainder(float(theta[r, c]) - heading, math.pi))
                if math.degrees(along) <= END_RIDGE_ALIGN:
                    return True
    return False


def ends(tracks: TrackMap, outline: Array, gauge: float) -> list[tuple[float, float, float]]:
    """Where a track ends inside the module, and its heading out past the end: the ridge of the
    map (its highest values across the track) ends there, nothing track-like lies ahead within
    END_AHEAD_MM, and no ridge goes on in line with it within END_RIDGE_AHEAD_MM, away from the
    gables and the sides."""
    score = tracks.score
    theta = tracks.direction
    h, w = score.shape
    nx = (-np.sin(theta)).astype(np.float32)
    ny = np.cos(theta).astype(np.float32)
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    # The middle is the highest across the track for more than a rail's distance on each side:
    # one rail alone matches the profile half as well, a rail's distance beside the middle.
    top = score >= RIDGE_SCORE
    for k in (0.1, 0.4, 0.7, 1.0, 1.3):
        step = k * gauge * tracks.grid.ppm
        for sign in (1, -1):
            other = cv2.remap(score, gx + sign * nx * step, gy + sign * ny * step, cv2.INTER_LINEAR)
            top &= score >= other
    ridge = top.astype(np.uint8)
    ridge = thin(ridge)
    ppm = tracks.grid.ppm
    polygon = outline.astype(np.float32).reshape(-1, 1, 2)
    found: list[tuple[float, float, float]] = []
    _count, labels, stats, _ = cv2.connectedComponentsWithStats(ridge, connectivity=8)
    neighbours = crossings(ridge)
    candidates: list[tuple[Array, Array]] = []
    for row, col in np.argwhere((ridge > 0) & (neighbours == 1)):
        label = labels[row, col]
        if stats[label, cv2.CC_STAT_AREA] < RIDGE_MIN_MM * ppm / 2:
            continue
        if _branch(ridge, neighbours, row, col) < BRANCH_MM * ppm:
            continue  # a spur of the thinning, not a track's end
        # The direction out of the end: from the ridge a little way back, along the ridge itself,
        # so that another track's ridge close beside it does not count.
        near = _along_ridge(ridge, int(row), int(col), 12)
        if len(near) < 6:
            continue
        back = np.mean(near, axis=0)
        out = np.array([col - back[1], row - back[0]], np.float64)
        if np.linalg.norm(out) < 1e-6:
            continue
        candidates.append((np.array([col, row], np.float64), out / np.linalg.norm(out)))
    for at, out in candidates:
        # The ridge can stop short of where the track ends: the map is followed on along the
        # heading while it still sees track (part c2).
        for _ in range(int(END_FOLLOW_MM)):
            ahead = at + out * ppm
            if float(sample(score, ahead[None, 0], ahead[None, 1])[0]) < TRACK_SCORE:
                break
            at = ahead
        col, row = float(at[0]), float(at[1])
        mm = tracks.grid.to_mm(np.array([[col, row]], np.float64))[0]
        clear = cv2.pointPolygonTest(polygon, (float(mm[0]), float(mm[1])), True)
        if clear < END_CLEAR_MM:
            continue
        # Nothing track-like ahead of it, in a cone: at a switch or a crossing the ridge breaks
        # where the tracks overlap, but the map still sees track there.
        ds = np.arange(8.0, END_AHEAD_MM, 1.0) * ppm
        lateral = np.arange(-4.0, 4.5, 1.0) * ppm
        heading = math.atan2(out[1], out[0])
        blocked = False
        for turn in np.radians([-20.0, -10.0, 0.0, 10.0, 20.0]):
            way = np.array([math.cos(heading + turn), math.sin(heading + turn)])
            side = np.array([-way[1], way[0]])
            points = (
                at[None, None, :]
                + ds[:, None, None] * way[None, None, :]
                + lateral[None, :, None] * side[None, None, :]
            ).reshape(-1, 2)
            if float(sample(score, points[:, 0], points[:, 1]).max()) >= TRACK_SCORE:
                blocked = True
                break
        if blocked or _ridge_ahead(ridge, theta, at, out, ppm):
            continue
        point = (float(mm[0]), float(mm[1]))
        if all(math.dist(point, other[:2]) > END_MERGE_MM for other in found):
            found.append((*point, heading))
    return sorted(found)
