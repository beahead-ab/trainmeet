"""Kant 1 and gable A on the photo (bildkedjan steps 1, 4 and 13; change 5 in (c)).

The owner taps the long side that is Kant 1 and the gable that is gable A. Gable A beside Kant 1
before it, clockwise, is the module as CAD draws it seen from above; after it, the module is
mirrored: some stations measure theirs so, with the module to the left of Kant 1 from gable A.

When the module's gables are known (the owner's measures or the norm's profile) and do not look
the same from the other side or the other end, the photo shows which way round it lies: the
tracks found at the gables are compared with the known ones in all four ways, and a clear best
is Kant 1 and gable A, derived and shown for the owner to confirm (derive). When the profile is
symmetric, as MMM's 140/197/283/340 on 480 is, or the gables are not known, the chain always
asks.

After reading, choosing another Kant 1 or gable A costs nothing (reorient): the measured module
is moved into the new frame, a mirror or a turn of its millimetres. The measuring image is the
same one, the AI's answer is the same one with its ends named anew, and nothing is read again.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import cv2
import numpy as np

from cad.bildkedjan import camera as cam
from cad.bildkedjan import chain, rectify
from cad.bildkedjan.arcs import Edges, Side
from cad.bildkedjan.camera import Array, Camera
from cad.bildkedjan.chain import Measured, Setup
from cad.bildkedjan.paths import Path, Terminal

MATCH_CAP = 30.0
"""A known track further than this from every found one counts as this far, mm."""
MISSING = 25.0
"""What a track too many or too few costs, mm."""
CLEAR_GAP = 15.0
"""The best way round must be this much better than the next, per gable, to be derived."""
CLEAR_FIT = 8.0
"""And fit the known tracks within this, on average, mm."""


@dataclass(frozen=True)
class Way:
    """One way round, relative to a frame: gable A at the other end (mirror along the module),
    and Kant 1 on the other long side (mirror across it). Both together is a half turn."""

    ends: bool
    sides: bool


WAYS = (Way(False, False), Way(True, False), Way(False, True), Way(True, True))


def sides_for(kant1: int, gable_a: int, way: Way) -> tuple[int, int]:
    """Kant 1 and gable A as photo sides after turning the frame (kant1, gable_a) the way."""
    k, a = kant1, gable_a
    if way.sides:
        k = (k + 2) % 4
        a = gable_a  # the same end, the other long side
    if way.ends:
        a = (gable_a + 2) % 4
    return k, a


def _cost(found: list[float], known: list[float]) -> float:
    if not known:
        return 0.0
    if not found:
        return MISSING * len(known)
    total = sum(min(MATCH_CAP, min(abs(k - f) for f in found)) for k in known)
    return total + MISSING * abs(len(found) - len(known))


@dataclass(frozen=True)
class Derived:
    way: Way
    decided: bool
    costs: tuple[float, ...]


def derive(
    found_a: list[float],
    found_b: list[float],
    width_a: float,
    width_b: float,
    known_a: list[float],
    known_b: list[float],
) -> Derived:
    """Which way round the module lies, from its gables' tracks as found (in the frame read)
    and as known; decided only when one way is clearly best and fits."""
    if not known_a and not known_b:
        return Derived(Way(False, False), False, ())
    costs = []
    for way in WAYS:
        a, b = (found_b, found_a) if way.ends else (found_a, found_b)
        wa, wb = (width_b, width_a) if way.ends else (width_a, width_b)
        if way.sides:
            a = [wa - v for v in a]
            b = [wb - v for v in b]
        costs.append(_cost(sorted(a), known_a) + _cost(sorted(b), known_b))
    order = sorted(range(4), key=lambda i: costs[i])
    best, second = costs[order[0]], costs[order[1]]
    tracks = max(1, len(known_a) + len(known_b))
    decided = best / tracks <= CLEAR_FIT and second - best >= CLEAR_GAP * (
        int(bool(known_a)) + int(bool(known_b))
    )
    return Derived(WAYS[order[0]], decided, tuple(round(c, 1) for c in costs))


# --- After reading: the same measuring, another frame ------------------------------------------


@dataclass(frozen=True)
class Frame:
    """mm in the frame read to mm in the new one: p' = turn · p + shift (turn orthogonal, a
    mirror when its determinant is negative)."""

    turn: Array
    shift: Array

    def points(self, points: Array) -> Array:
        found: Array = np.asarray(points, np.float64) @ self.turn.T + self.shift
        return found

    def point(self, p: tuple[float, float]) -> tuple[float, float]:
        q = self.points(np.array([p]))[0]
        return (float(q[0]), float(q[1]))

    def homogeneous(self) -> Array:
        m = np.eye(3)
        m[:2, :2] = self.turn
        m[:2, 2] = self.shift
        return m

    def heading(self, angle: float) -> float:
        d = self.turn @ np.array([math.cos(angle), math.sin(angle)])
        return math.atan2(float(d[1]), float(d[0]))


def _procrustes(source: Array, target: Array) -> Frame:
    """The orthogonal map (a mirror allowed) and shift that take source onto target best."""
    sc, tc = source.mean(axis=0), target.mean(axis=0)
    h = (source - sc).T @ (target - tc)
    u, _, vt = np.linalg.svd(h)
    turn = vt.T @ u.T
    return Frame(turn, tc - turn @ sc)


@dataclass(frozen=True)
class Reoriented:
    measured: Measured
    labels: dict[str, str]
    """The ends' names in the frame read to their names in the new one."""
    frame: Frame


def _new_setup(measured: Measured, kant1: int, gable_a: int, perm: list[int]) -> Setup:
    setup = measured.setup
    old = measured.shape.corners(measured.length, measured.offset)
    # Which old gable is the new gable A, and which long side Kant 1.
    swap_ends = perm[0] in (1, 2)
    swap_sides = perm[0] in (2, 3)
    width_a, width_b = (
        (setup.width_b, setup.width_a) if swap_ends else (setup.width_a, setup.width_b)
    )
    radius, edge = setup.radius, setup.edge
    if measured.shape.curved and swap_sides:
        assert measured.shape.radius is not None
        if edge == "outer":
            radius, edge = measured.shape.radius - setup.width_a, "inner"
        else:
            radius, edge = measured.shape.radius + setup.width_a, "outer"
    offset = setup.offset
    if not measured.shape.curved and setup.offset is not None:
        p, q = old[perm[0]], old[perm[1]]
        r = old[perm[3]]
        sy = 1.0 if r[1] >= p[1] else -1.0
        offset = float(sy * (q[1] - p[1]))
    return replace(
        setup,
        kant1=kant1,
        gable_a=gable_a,
        width_a=width_a,
        width_b=width_b,
        offset=offset,
        radius=radius,
        edge=edge,
    )


def _new_shape_numbers(measured: Measured, perm: list[int]) -> tuple[float, float]:
    """The new frame's length and offset (straight and trapezoid: from the corners)."""
    old = measured.shape.corners(measured.length, measured.offset)
    p, q, r = old[perm[0]], old[perm[1]], old[perm[3]]
    sx = 1.0 if q[0] >= p[0] else -1.0
    sy = 1.0 if r[1] >= p[1] else -1.0
    return float(sx * (q[0] - p[0])), float(sy * (q[1] - p[1]))


def _resampled(xs: Array, ys: Array) -> tuple[Array, Array]:
    """A path as y every mm of x again, from its first x to its last, both kept exactly."""
    order = np.argsort(xs, kind="stable")
    xs, ys = xs[order], ys[order]
    inner = np.arange(math.ceil(xs[0] + 1e-6), math.floor(xs[-1] - 1e-6) + 1, 1.0)
    grid = np.concatenate([[xs[0]], inner, [xs[-1]]])
    grid = np.unique(grid)
    return grid, np.interp(grid, xs, ys)


def reorient(measured: Measured, kant1: int, gable_a: int) -> Reoriented:
    """The measured module in the frame of another Kant 1 and gable A: no new measuring."""
    setup = measured.setup
    if (kant1, gable_a) == (setup.kant1, setup.gable):
        return Reoriented(
            measured, {t.id: t.id for t in measured.terminals}, Frame(np.eye(2), np.zeros(2))
        )
    new_order = chain.ordered(measured.corners, kant1, gable_a)
    perm = [int(np.argmin(np.linalg.norm(measured.corners - c, axis=1))) for c in new_order]
    new_setup = _new_setup(measured, kant1, gable_a, perm)
    old_corners = measured.shape.corners(measured.length, measured.offset)
    if measured.shape.curved:
        shape = new_setup.shape()
        length, offset = shape.arc_length, 0.0
    else:
        length, offset = _new_shape_numbers(measured, perm)
        shape = new_setup.shape(length)
    new_corners = shape.corners(length, offset)
    frame = _procrustes(old_corners[perm], new_corners)
    back = Frame(frame.turn.T, -frame.turn.T @ frame.shift)
    # The ends, named anew: a gable's tracks from Kant 1, the ends inside by x.
    strips = chain.strips_of(shape, length, offset)
    moved: list[Terminal] = []
    for t in measured.terminals:
        at = frame.point(t.at)
        out = frame.heading(t.out) if t.out is not None else None
        gable = t.gable
        if t.kind == "gable" and t.gable is not None:
            old_end_is_a = t.gable == "A"
            new_a = (perm[0] in (0, 3)) == old_end_is_a
            gable = "A" if new_a else "B"
        moved.append(Terminal(t.id, t.kind, at, gable, t.track, out))
    labels: dict[str, str] = {}
    renamed: list[Terminal] = []
    for end in ("A", "B"):
        own = [t for t in moved if t.kind == "gable" and t.gable == end]
        strip = strips[0 if end == "A" else 1]
        for n, t in enumerate(sorted(own, key=lambda t: chain.along_gable(strip, t.at)), start=1):
            labels[t.id] = f"{end}{n}"
            renamed.append(Terminal(f"{end}{n}", t.kind, t.at, t.gable, n, t.out))
    ends_ = sorted((t for t in moved if t.kind != "gable"), key=lambda t: (t.at[0], t.at[1]))
    for n, t in enumerate(ends_, start=1):
        labels[t.id] = f"E{n}"
        renamed.append(Terminal(f"E{n}", t.kind, t.at, t.gable, t.track, t.out))
    by_id = {t.id: t for t in renamed}
    new_paths: list[Path] = []
    for p in measured.paths:
        points = frame.points(p.points())
        xs, ys = _resampled(points[:, 0], points[:, 1])
        scores = (
            np.interp(xs, *_resampled(points[:, 0], np.asarray(p.scores, np.float64))[::1])
            if len(p.scores) == len(p.xs)
            else np.zeros(0)
        )
        a, b = labels.get(p.a, p.a), labels.get(p.b, p.b)
        if by_id[a].at[0] > by_id[b].at[0]:
            a, b = b, a
        new_paths.append(Path(a, b, xs, ys, p.share, p.gap, p.sharpest, p.status, scores))
    # The measuring image in the new frame: the same pixels, mirrored or turned.
    outline = shape.outline(length, offset)
    grid = rectify.grid_for(outline, measured.grid.ppm)
    image = measured.image
    if image is not None:
        gx, gy = np.meshgrid(
            np.arange(grid.width, dtype=np.float64), np.arange(grid.height, dtype=np.float64)
        )
        mm = back.points(grid.to_mm(np.stack([gx.ravel(), gy.ravel()], axis=1)))
        px = measured.grid.to_px(mm).astype(np.float32)
        image = cv2.remap(
            image,
            px[:, 0].reshape(grid.height, grid.width),
            px[:, 1].reshape(grid.height, grid.width),
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
    c = measured.camera
    to_old = back.homogeneous()
    camera = Camera(
        plane=c.plane @ to_old,
        lift=c.lift,
        f=c.f,
        centre=c.centre,
        k=c.k,
        tilt=c.tilt,
        height=c.height,
        residual=c.residual,
    )
    edges = measured.edges
    if edges is not None and perm[0] in (2, 3):
        names = {"kant1": "far", "far": "kant1"}
        edges = Edges(
            [
                Side(
                    names[s.name],
                    s.expected,
                    s.found,
                    s.deviation,
                    s.roundness,
                    s.places,
                    s.allowed,
                )
                for s in edges.sides
            ]
        )
    found = Measured(
        setup=new_setup,
        camera=camera,
        length=length,
        offset=offset,
        corners=np.asarray(new_order, np.float64),
        corner_sigma=measured.corner_sigma,
        grid=grid,
        quality=measured.quality,
        terminals=renamed,
        paths=sorted(new_paths, key=lambda p: p.pair),
        profile=measured.profile,
        rail_height=measured.rail_height,
        size=measured.size,
        shift=measured.shift,
        stitch_mm=measured.stitch_mm,
        photo_length=measured.photo_length,
        image=image,
        edges=edges,
    )
    return Reoriented(found, labels, frame)


def gable_positions(measured: Measured) -> tuple[list[float], list[float]]:
    """The gables' tracks from Kant 1 as the measured module has them."""
    strips = measured.strips()
    found: dict[str, list[float]] = {"A": [], "B": []}
    for t in measured.terminals:
        if t.kind == "gable" and t.gable in found:
            found[t.gable].append(chain.along_gable(strips[0 if t.gable == "A" else 1], t.at))
    return sorted(found["A"]), sorted(found["B"])


def peek(prepared: chain.Prepared, setup: Setup) -> tuple[list[float], list[float]] | None:
    """The gables' tracks at a glance, before the photo is read: the camera from the corners,
    the gables' strips straightened, and the tracks' middles where the photo's own profile
    matches (trackmap.bootstrap). Quick, for deriving Kant 1 and gable A at the upload; None
    when the corners do not give a camera."""
    from cad import switches
    from cad.bildkedjan import trackmap

    corners = np.array(setup.corners, np.float64) if setup.corners is not None else prepared.corners
    if corners is None:
        return None
    ordered = chain.ordered(corners, setup.kant1, setup.gable)
    size = prepared.size
    focal = cam.focal_from_35mm(size, prepared.focal_35mm)
    try:
        camera, length, offset = cam.solve(
            ordered - np.array(prepared.origin), setup.shape(), size, focal, prepared.lens
        )
    except (ValueError, np.linalg.LinAlgError):
        return None
    shift = np.array(prepared.origin)
    if shift.any():
        move = np.array([[1, 0, shift[0]], [0, 1, shift[1]], [0, 0, 1]], np.float64)
        camera = replace(camera, plane=move @ camera.plane, lift=move @ camera.lift)
    shape = setup.shape(length)
    outline = shape.outline(length, offset)
    rail = chain.RAIL_HEIGHT[setup.scale]
    grid = rectify.grid_for(outline)
    image = rectify.rectify(prepared.pixels, camera, grid, rail)
    inside = rectify.module_mask(grid, outline, 3.0)
    light = rectify.even_light(image, inside, grid.ppm)
    gray = cv2.cvtColor(light.image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    strips = chain.strips_of(shape, length, offset)
    boot = trackmap.bootstrap(
        gray, grid, strips, switches.GAUGE[setup.scale], chain.RAIL_HEAD[setup.scale]
    )
    if boot is None:
        return None
    a = sorted(v for i, v in boot.centres if i == 0)
    b = sorted(v for i, v in boot.centres if i == 1)
    return a, b
