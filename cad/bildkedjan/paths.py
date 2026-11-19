"""Step 11 of the chain, the code's part: the gable tracks, the ends inside the module, and the
cheapest path on the track map between them (bildkedjan, Topologi; lärdomarna, Kopplingar).

A module's tracks go from gable to gable, or from a gable to an end inside it, and run on
along the module: within a module no track turns back on itself. So a path is y as a function
of x, from one gable or end toward the other, and the cheapest one is found column by column,
every millimetre of x, with y every half millimetre, as dynamic programming (Viterbi). A step
costs what the map says the place is not a track, and what its direction differs from the
track's there. A train never reverses on the way, and the path cannot either.

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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from cad.bildkedjan.camera import Array
from cad.bildkedjan.trackmap import TRACK_SCORE, TrackMap, sample

Y_STEP = 0.5
"""The paths' resolution across the module, mm."""
SLOPES = 4
"""The steepest step, in Y_STEP per mm of x: 2 mm per mm, 63°."""
DIRECTION_WEIGHT = 2.0
OFF_TRACK_WEIGHT = 4.0
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
SHARP_SHARE = 0.4
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
    costs: dict[bool, NDArray[Any]] = field(default_factory=dict)

    def steps(self, forward: bool) -> NDArray[Any]:
        if forward not in self.costs:
            self.costs[forward] = np.stack(
                [_step_costs(self, column, forward) for column in range(len(self.xs))]
            )
        return self.costs[forward]


def columns(
    tracks: TrackMap, x_range: tuple[float, float], y_range: tuple[float, float]
) -> Columns:
    xs = np.arange(math.floor(x_range[0]), math.ceil(x_range[1]) + 1, 1.0)
    ys = np.arange(y_range[0], y_range[1] + Y_STEP / 2, Y_STEP)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    px = tracks.grid.to_px(np.stack([gx.ravel(), gy.ravel()], axis=1))
    score = sample(tracks.score, px[:, 0], px[:, 1]).reshape(gx.shape).astype(np.float32)
    ix = np.clip(np.round(px[:, 0]).astype(int), 0, tracks.grid.width - 1)
    iy = np.clip(np.round(px[:, 1]).astype(int), 0, tracks.grid.height - 1)
    direction = tracks.direction[iy, ix].reshape(gx.shape)
    return Columns(xs, ys, score, direction)


def _step_costs(cols: Columns, column: int, forward: bool) -> NDArray[Any]:
    """The cost of arriving at each row of the column with each slope, (2·SLOPES+1, rows). A
    step toward smaller x with the rise d runs in the direction of one toward larger x with -d."""
    s = cols.score[column]
    theta = cols.direction[column]
    found = np.empty((2 * SLOPES + 1, len(s)), np.float32)
    for i, d in enumerate(range(-SLOPES, SLOPES + 1)):
        rise = d * Y_STEP
        phi = math.atan2(rise if forward else -rise, 1.0)
        length = math.hypot(1.0, rise)
        off_track = OFF_TRACK_WEIGHT * np.maximum(0.0, TRACK_SCORE - s) / TRACK_SCORE
        found[i] = length * ((1 - s) + off_track + DIRECTION_WEIGHT * np.sin(phi - theta) ** 2)
    return found


@dataclass(frozen=True)
class Run:
    """The dynamic programming from one start: the cost to every place, and the way back."""

    start: int
    step: int
    cost: NDArray[Any]
    back: NDArray[np.int8]


def run(
    cols: Columns,
    start: tuple[float, float],
    forward: bool,
    penalty: NDArray[Any] | None = None,
) -> Run:
    """The cheapest paths from start, toward larger x when forward, else toward smaller."""
    c0 = round(start[0] - cols.xs[0])
    r0 = round((start[1] - cols.ys[0]) / Y_STEP)
    rows = len(cols.ys)
    step = 1 if forward else -1
    count = (len(cols.xs) - c0) if forward else (c0 + 1)
    cost = np.full((count, rows), np.inf, np.float32)
    back = np.zeros((count, rows), np.int8)
    cost[0, max(0, min(rows - 1, r0))] = 0.0
    every = cols.steps(forward)
    for i in range(1, count):
        column = c0 + step * i
        steps = every[column]
        if penalty is not None:
            steps = steps + penalty[column]
        previous = cost[i - 1]
        candidates = np.full((2 * SLOPES + 1, rows), np.inf, np.float32)
        for j, d in enumerate(range(-SLOPES, SLOPES + 1)):
            # Arriving at row r with the rise d per mm came from row r - d.
            if d >= 0:
                candidates[j, d:] = previous[: rows - d] if d else previous
            else:
                candidates[j, :d] = previous[-d:]
            candidates[j] += steps[j]
        best = np.argmin(candidates, axis=0)
        cost[i] = candidates[best, np.arange(rows)]
        back[i] = (best - SLOPES).astype(np.int8)
    return Run(c0, step, cost, back)


def trace(cols: Columns, done: Run, target: tuple[float, float]) -> tuple[Array, Array] | None:
    """The path from the run's start to target, as x and y every mm of x, from smaller x."""
    i = round(target[0] - cols.xs[0])
    index = (i - done.start) * done.step
    if index < 0 or index >= len(done.cost):
        return None
    r = round((target[1] - cols.ys[0]) / Y_STEP)
    if not 0 <= r < done.cost.shape[1] or not np.isfinite(done.cost[index, r]):
        return None
    rows = [r]
    for k in range(index, 0, -1):
        r = r - int(done.back[k, r])
        rows.append(r)
    rows.reverse()
    columns_ = [done.start + done.step * k for k in range(index + 1)]
    xs = cols.xs[columns_]
    ys = cols.ys[rows]
    if done.step < 0:
        xs, ys = xs[::-1], ys[::-1]
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


def judge(path: Path, min_radius: float) -> None:
    """track, hidden or none, by the map along it and how sharply it turns."""
    on = path.scores >= TRACK_SCORE
    path.share = float(on.mean()) if len(on) else 0.0
    gap = longest = 0
    for value in on:
        gap = 0 if value else gap + 1
        longest = max(longest, gap)
    path.gap = float(longest)
    path.sharpest = sharpest_radius(path.xs, path.ys)
    if path.sharpest < SHARP_SHARE * min_radius:
        path.status = "none"
    elif path.share >= TRACK_SHARE and path.gap <= GAP_MM:
        path.status = "track"
    elif path.share >= HIDDEN_SHARE and path.gap <= HIDDEN_GAP_MM:
        path.status = "hidden"
    else:
        path.status = "none"


def _sharp_at(xs: Array, ys: Array, min_radius: float) -> float | None:
    """Where the path turns sharpest, if sharper than a switch may: x in mm."""
    if sharpest_radius(xs, ys) >= SHARP_SHARE * min_radius:
        return None
    # Where: the place the straight lines on its two sides differ most.
    run = int(KINK_RUN_MM)
    if len(ys) < 2 * run + 2:
        return None
    slopes = np.arctan(_slopes(ys, run))
    turn = np.abs(slopes[run:] - slopes[:-run])
    return float(xs[int(np.argmax(turn)) + run])


Refiner = Callable[[Array, Array], Array]
"""y along a path made exact: from the columns' half millimetres to the track's middle."""


def connect(
    cols: Columns,
    terminals: list[Terminal],
    min_radius: float,
    refiner: Refiner | None = None,
    attempts: int = 3,
) -> list[Path]:
    """Every pair of terminals the cheapest path joins, judged. A path that turns too sharply
    is tried again with that place made costly, so a smooth way round is found if there is one."""
    found: dict[tuple[str, str], Path] = {}
    by_id = {t.id: t for t in terminals}
    rows = len(cols.ys)
    for source in terminals:
        for forward in (True, False):
            targets = [
                t
                for t in terminals
                if t.id != source.id
                and ((t.at[0] > source.at[0] + 50) if forward else (t.at[0] < source.at[0] - 50))
                and not source.beyond(t)
                and not t.beyond(source)
            ]
            if not targets:
                continue
            penalty: NDArray[Any] | None = None
            pending = list(targets)
            for _ in range(attempts):
                done = run(cols, source.at, forward, penalty)
                again: list[Terminal] = []
                for target in pending:
                    pair = tuple(sorted((source.id, target.id)))
                    if pair in found and found[pair].status == "track":
                        continue
                    traced = trace(cols, done, target.at)
                    if traced is None:
                        continue
                    xs, ys = traced
                    if refiner is not None:
                        ys = refiner(xs, ys)
                    first, second = (source, target) if forward else (target, source)
                    scores = sample_map(cols, xs, ys)
                    path = Path(first.id, second.id, xs, ys, 0, 0, 0, "none", scores)
                    judge(path, min_radius)
                    sharp = _sharp_at(xs, ys, min_radius)
                    if path.status == "none" and sharp is not None:
                        again.append(target)
                        if penalty is None:
                            penalty = np.zeros((len(cols.xs), rows), np.float32)
                        c = round(sharp - cols.xs[0])
                        r = round((float(np.interp(sharp, xs, ys)) - cols.ys[0]) / Y_STEP)
                        penalty[max(0, c - 15) : c + 16, max(0, r - 40) : r + 41] += 50.0
                    previous = found.get(pair)  # type: ignore[arg-type]
                    if previous is None or _better(path, previous):
                        found[pair] = path  # type: ignore[index]
                pending = again
                if not pending:
                    break
    for path in found.values():
        path.a, path.b = sorted((path.a, path.b), key=lambda t: by_id[t].at[0])
    return sorted(found.values(), key=lambda p: p.pair)


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
    lo = outline.min(axis=0) + END_CLEAR_MM
    hi = outline.max(axis=0) - END_CLEAR_MM
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
        col, row = float(at[0]), float(at[1])
        mm = tracks.grid.to_mm(np.array([[col, row]], np.float64))[0]
        if not (lo[0] <= mm[0] <= hi[0] and lo[1] <= mm[1] <= hi[1]):
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
