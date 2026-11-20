"""Steps 5 and 6 of the chain: the camera and the lens, and the plane the tracks are measured
in (bildkedjan, Kamera och objektiv, Uträtning och höjd).

The camera is the pinhole camera with square pixels and the image's middle as its optical
centre, as the photo test's (lärdomarna, Trapets). Its focal length, its pose and the module's
unknown measures come out of one model: the homography from the module's plane to the photo
must be K·[r1 r2 t] with r1 and r2 orthonormal (Zhang's constraints). For a rectangle with its
width known that gives the length; for a trapezoid the length and the offset (förskjutningen).
When the photo is taken almost straight down the focal length cannot be told, but neither does
it matter there: a weak pull toward the EXIF's focal length, or a phone's usual 26 mm, decides it.

The lens: a phone's main camera is corrected in the phone, and what is left is one parameter of
the division model, p_u = c + (p_d - c) / (1 + k·r_d²) with r_d in focal lengths, found from the
module's long edges, which must be straight (the plumb-line method, "straight lines have to be
straight"). It is used only when it moves a corner more than 0,5 px (bildkedjan step 5). There is
no calibration for the user.

The height (step 6): the corners lie on the frame's top, the rails RAIL_HEIGHT higher. A point
h above the plane moves r·h/H in the photo, which is 0,3–0,5 % of the scale, as much as the
whole tolerance of the length. So the tracks are measured in a plane of their own at the rails'
height: the homography of that plane is the frame's plus h times the camera's third axis, which
keeps the frame's corners exactly where they were marked.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

Array = NDArray[Any]

PHONE_FOCAL_35MM = 26.0
"""A phone's main camera, 35 mm equivalent, when the photo says nothing (the main camera of
most phones is 24–28 mm)."""
FULL_FRAME_DIAGONAL = 43.27
FOCAL_PULL = 1e-5
"""How hard the focal length is pulled toward its starting value: enough to decide it when the
photo cannot, too little to matter when it can."""
LENS_MIN_SHIFT = 0.5
"""The lens correction is used only when it moves a corner more than this, in px."""
MAX_DISTORTION = 0.25
LENS_IMPROVEMENT = 0.7
"""The edges must be at least this much straighter, as a share, for the correction to count."""


def focal_from_35mm(size: tuple[int, int], focal_35mm: float | None) -> float:
    """The focal length in px from the 35 mm equivalent, measured on the diagonal."""
    return (focal_35mm or PHONE_FOCAL_35MM) / FULL_FRAME_DIAGONAL * math.hypot(*size)


def undistort(points: Array, centre: tuple[float, float], f: float, k: float) -> Array:
    """The photo's px to the undistorted px."""
    if k == 0:
        return points.astype(np.float64)
    c = np.array(centre)
    d = (points - c) / f
    r2 = (d * d).sum(axis=1, keepdims=True)
    found: Array = c + d / (1 + k * r2) * f
    return found


def distort(points: Array, centre: tuple[float, float], f: float, k: float) -> Array:
    """The undistorted px to the photo's px: the division model solved for r_d."""
    if k == 0:
        return points.astype(np.float64)
    c = np.array(centre)
    d = (points - c) / f
    ru = np.hypot(d[:, 0], d[:, 1])
    safe = np.maximum(ru, 1e-12)
    rd = (1 - np.sqrt(np.maximum(0.0, 1 - 4 * k * safe * safe))) / (2 * k * safe)
    scale = np.where(ru > 1e-12, rd / safe, 1.0)
    found: Array = c + d * scale[:, None] * f
    return found


def homography(src: Array, dst: Array) -> Array:
    """The homography that takes the four or more src points to dst, by the normalised DLT."""

    def normaliser(p: Array) -> Array:
        mean = p.mean(axis=0)
        spread = np.sqrt(((p - mean) ** 2).sum(axis=1)).mean() or 1.0
        s = math.sqrt(2) / spread
        return np.array([[s, 0, -s * mean[0]], [0, s, -s * mean[1]], [0, 0, 1]])

    ts, td = normaliser(src), normaliser(dst)
    a = np.c_[src, np.ones(len(src))] @ ts.T
    b = np.c_[dst, np.ones(len(dst))] @ td.T
    rows = []
    for (x, y, _), (u, v, _) in zip(a, b, strict=True):
        rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, _, vt = np.linalg.svd(np.array(rows))
    h = vt[-1].reshape(3, 3)
    found: Array = np.linalg.inv(td) @ h @ ts
    scaled: Array = found / found[2, 2]
    return scaled


def apply(h: Array, points: Array) -> Array:
    p = np.c_[points, np.ones(len(points))] @ h.T
    found: Array = p[:, :2] / p[:, 2:3]
    return found


@dataclass(frozen=True)
class Camera:
    """The camera and the module's plane: the frame's homography (mm to undistorted px), the
    third axis that lifts a plane, the focal length and the lens."""

    plane: Array
    """The frame's top, z = 0: (x, y) in mm to undistorted px."""
    lift: Array
    """Added to the plane's third column times z: the plane z mm higher, toward the camera."""
    f: float
    centre: tuple[float, float]
    k: float
    tilt: float
    """Degrees from looking straight down."""
    height: float
    """The camera's height over the frame, mm."""
    residual: float
    """How far the homography is from a camera's: 0 for a perfect one."""

    def plane_at(self, z: float) -> Array:
        h = self.plane.copy()
        h[:, 2] += self.lift * z
        return h

    def to_image(self, points: Array, z: float = 0.0) -> Array:
        """Module mm (in the plane z mm above the frame) to the photo's px."""
        return distort(apply(self.plane_at(z), points), self.centre, self.f, self.k)

    def to_plane(self, pixels: Array, z: float = 0.0) -> Array:
        """The photo's px to module mm in the plane z mm above the frame."""
        h = np.linalg.inv(self.plane_at(z))
        return apply(h, undistort(pixels, self.centre, self.f, self.k))

    def px_per_mm(self, points: Array, z: float = 0.0) -> Array:
        """The photo's resolution at each point: px per mm in the plane, the geometric mean of
        the two directions."""
        found = []
        for x, y in points:
            p = self.to_image(np.array([[x, y], [x + 1, y], [x, y + 1]]), z)
            a, b = p[1] - p[0], p[2] - p[0]
            found.append(math.sqrt(abs(a[0] * b[1] - a[1] * b[0])))
        return np.array(found)


def _parts(h: Array, f: float, centre: tuple[float, float]) -> tuple[Array, Array, Array]:
    k_inv = np.array([[1 / f, 0, -centre[0] / f], [0, 1 / f, -centre[1] / f], [0, 0, 1]])
    m = k_inv @ h
    return m[:, 0], m[:, 1], m[:, 2]


def orthonormal_error(h: Array, f: float, centre: tuple[float, float]) -> float:
    """Zhang's two constraints as one number: r1 ⟂ r2 and |r1| = |r2|."""
    m1, m2, _ = _parts(h, f, centre)
    n1, n2 = float(np.linalg.norm(m1)), float(np.linalg.norm(m2))
    e1 = float(m1 @ m2) / (n1 * n2)
    e2 = (n1 - n2) / (n1 + n2)
    return e1 * e1 + e2 * e2


def nelder_mead(
    fn: Callable[[Array], float],
    start: Sequence[float] | Array,
    step: Sequence[float],
    rounds: int = 400,
) -> tuple[Array, float]:
    """The simplex method, deterministic, for a handful of parameters."""
    n = len(start)
    simplex = [np.array(start, np.float64)]
    for i in range(n):
        point = np.array(start, np.float64)
        point[i] += step[i]
        simplex.append(point)
    values = [fn(p) for p in simplex]
    for _ in range(rounds):
        order = np.argsort(values)
        simplex = [simplex[i] for i in order]
        values = [values[i] for i in order]
        if abs(values[-1] - values[0]) <= 1e-15 * (1 + abs(values[0])):
            break
        centroid = np.mean(simplex[:-1], axis=0)
        reflected = centroid + (centroid - simplex[-1])
        fr = fn(reflected)
        if fr < values[0]:
            expanded = centroid + 2 * (centroid - simplex[-1])
            fe = fn(expanded)
            simplex[-1], values[-1] = (expanded, fe) if fe < fr else (reflected, fr)
        elif fr < values[-2]:
            simplex[-1], values[-1] = reflected, fr
        else:
            contracted = centroid + 0.5 * (simplex[-1] - centroid)
            fc = fn(contracted)
            if fc < values[-1]:
                simplex[-1], values[-1] = contracted, fc
            else:
                for i in range(1, n + 1):
                    simplex[i] = simplex[0] + 0.5 * (simplex[i] - simplex[0])
                    values[i] = fn(simplex[i])
    best = int(np.argmin(values))
    return simplex[best], values[best]


@dataclass(frozen=True)
class Shape:
    """The module's outline in mm as a function of its unknowns. known: the given measures.
    unknown: names of what the photo solves for, with starting values.

    A curve module (kind "curve", bildkedjan step 6, Kurvmodul) has no unknowns: Kant 1's
    radius, the angle and the width give its four corners, as cad/geometry.py has them. With
    Kant 1 as the outer edge its centre lies at (0, radius) under Kant 1 and it turns right seen
    from gable A; as the inner edge the centre lies at (0, -radius) and it turns left."""

    kind: str
    width_a: float
    width_b: float
    length: float | None
    offset: float | None
    radius: float | None = None
    """A curve's Kant 1 radius, mm."""
    angle: float | None = None
    """A curve's angle, degrees."""
    edge: str = "outer"
    sides: str = "bent"

    @property
    def curved(self) -> bool:
        return self.kind == "curve" and self.radius is not None and self.angle is not None

    @property
    def arc_length(self) -> float:
        """A curve's length along Kant 1."""
        assert self.radius is not None and self.angle is not None
        return self.radius * math.radians(self.angle)

    def point(self, offset: float, angle: float) -> Array:
        """A curve's point offset mm from Kant 1, angle degrees from gable A."""
        assert self.radius is not None
        phi = math.radians(angle)
        if self.edge == "outer":
            r = self.radius - offset
            return np.array([r * math.sin(phi), self.radius - r * math.cos(phi)])
        r = self.radius + offset
        return np.array([r * math.sin(phi), -self.radius + r * math.cos(phi)])

    def corners(self, length: float, offset: float) -> Array:
        """A at Kant 1, B at Kant 1, B far, A far."""
        if self.curved:
            assert self.angle is not None
            return np.array(
                [
                    self.point(0.0, 0.0),
                    self.point(0.0, self.angle),
                    self.point(self.width_b, self.angle),
                    self.point(self.width_a, 0.0),
                ]
            )
        return np.array(
            [
                [0.0, 0.0],
                [length, offset],
                [length, offset + self.width_b],
                [0.0, self.width_a],
            ]
        )

    def outline(self, length: float, offset: float, steps: int = 48) -> Array:
        """The board's outline: Kant 1 from gable A, gable B, the far side back, gable A. A
        curve's long sides are arcs, unless its box has straight sides."""
        if not self.curved:
            return self.corners(length, offset)
        assert self.angle is not None
        ks = range(steps + 1) if self.sides == "bent" else (0, steps)
        edge = [self.point(0.0, self.angle * k / steps) for k in ks]
        far = [self.point(self.width_a, self.angle * k / steps) for k in ks]
        return np.array(edge + far[::-1])


def pose(h: Array, f: float, centre: tuple[float, float]) -> tuple[Array, Array, Array]:
    """The rotation, the translation (mm) and the camera's position in the world from the
    frame's homography."""
    m1, m2, m3 = _parts(h, f, centre)
    scale = 2 / (np.linalg.norm(m1) + np.linalg.norm(m2))
    if m3[2] * scale < 0:
        scale = -scale
    r1, r2, t = m1 * scale, m2 * scale, m3 * scale
    r3 = np.cross(r1, r2)
    u, _, vt = np.linalg.svd(np.c_[r1, r2, r3])
    r = u @ vt
    position = -r.T @ t
    return r, t, position


def solve(
    corners: Array,
    shape: Shape,
    size: tuple[int, int],
    focal: float,
    k: float = 0.0,
) -> tuple[Camera, float, float]:
    """The camera, and the length and the offset, from the four corners in the photo's px (A at
    Kant 1, B at Kant 1, B far, A far). The width is the owner's; the length is the owner's when
    given, else solved; a trapezoid's offset likewise."""
    centre = (size[0] / 2, size[1] / 2)
    undistorted = undistort(corners, centre, focal, k)
    # A first guess of the length from the photo's own proportions.
    sides = np.linalg.norm(undistorted[[1, 2]] - undistorted[[0, 3]], axis=1).mean()
    ends = np.linalg.norm(undistorted[[3, 2]] - undistorted[[0, 1]], axis=1).mean()
    guess_length = (
        shape.length
        if shape.length is not None
        else float(sides / max(ends, 1e-6) * (shape.width_a + shape.width_b) / 2)
    )
    solve_length = shape.length is None and not shape.curved
    solve_offset = shape.kind == "trapezoid" and shape.offset is None
    log_f0 = math.log(focal)

    def unpack(x: Array) -> tuple[float, float, float]:
        i = 0
        length = (
            shape.arc_length if shape.curved else shape.length if shape.length is not None else 0.0
        )
        offset = shape.offset or 0.0
        if solve_length:
            length = float(x[i])
            i += 1
        if solve_offset:
            offset = float(x[i])
            i += 1
        return length, offset, math.exp(float(x[i]))

    def cost(x: Array) -> float:
        length, offset, f = unpack(x)
        if length <= 1:
            return 1e9
        h = homography(shape.corners(length, offset), undistorted)
        return orthonormal_error(h, f, centre) + FOCAL_PULL * (math.log(f) - log_f0) ** 2

    start: list[float] = []
    step: list[float] = []
    if solve_length:
        start.append(guess_length)
        step.append(guess_length * 0.05)
    if solve_offset:
        start.append(0.0)
        step.append(20.0)
    start.append(log_f0)
    step.append(0.2)
    best, value = nelder_mead(cost, start, step)
    best, value = nelder_mead(cost, best, [s / 10 for s in step])
    length, offset, f = unpack(best)
    plane = homography(shape.corners(length, offset), undistorted)
    r, _, position = pose(plane, f, centre)
    # The lift: the plane z mm toward the camera is the frame's plus z times the camera's third
    # axis, scaled as the homography is.
    m1, m2, _ = _parts(plane, f, centre)
    scale = (np.linalg.norm(m1) + np.linalg.norm(m2)) / 2
    k_matrix = np.array([[f, 0, centre[0]], [0, f, centre[1]], [0, 0, 1]])
    up = -1.0 if position[2] < 0 else 1.0
    lift = k_matrix @ r[:, 2] * scale * up
    tilt = math.degrees(math.acos(min(1.0, abs(float(r[2, 2])))))
    camera = Camera(
        plane=plane,
        lift=lift,
        f=f,
        centre=centre,
        k=k,
        tilt=tilt,
        height=float(abs(position[2])),
        residual=float(math.sqrt(max(0.0, value))),
    )
    return camera, length, offset


# --- The lens (plumb lines) ------------------------------------------------------------------


def _line_error(points: Array) -> float:
    """The mean squared distance from the best straight line (total least squares)."""
    centred = points - points.mean(axis=0)
    values = np.linalg.eigvalsh(centred.T @ centred)
    return float(values[0]) / len(points)


def _circle_error(points: Array) -> float:
    """The mean squared distance from the best circle (Kåsa): a curve module's long side, an arc
    seen nearly from above (part c2)."""
    x, y = points[:, 0], points[:, 1]
    a = np.c_[2 * x, 2 * y, np.ones(len(x))]
    (cx, cy, c), *_ = np.linalg.lstsq(a, x * x + y * y, rcond=None)
    r = math.sqrt(max(1e-9, float(c + cx * cx + cy * cy)))
    off = np.hypot(x - cx, y - cy) - r
    return float(np.mean(off * off))


def lens(
    sides: Sequence[Array],
    corners: Array,
    size: tuple[int, int],
    focal: float,
    bent: Sequence[bool] | None = None,
) -> float:
    """The division model's k from the module's edges, which are straight lines (or arcs, for
    the sides bent: a curve module's long sides); 0 when the correction moves no corner more
    than LENS_MIN_SHIFT px or does not make the edges clearly straighter. Each side counts by
    how much straighter it gets, so a side with scenery over its edge does not drown the
    others."""
    centre = (size[0] / 2, size[1] / 2)
    flags = list(bent) if bent is not None else [False] * len(sides)
    usable = [(s, f) for s, f in zip(sides, flags, strict=True) if len(s) >= 12]
    if len(usable) < 2:
        return 0.0

    def side_error(points: Array, arc: bool) -> float:
        return _circle_error(points) if arc else _line_error(points)

    floor = [max(side_error(s, f), 1e-3) for s, f in usable]

    def error(k: float) -> float:
        return sum(
            side_error(undistort(s, centre, focal, k), f) / base
            for (s, f), base in zip(usable, floor, strict=True)
        ) / len(usable)

    lo, hi = -MAX_DISTORTION, MAX_DISTORTION
    for _ in range(60):
        m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        if error(m1) <= error(m2):
            hi = m2
        else:
            lo = m1
    k = (lo + hi) / 2
    # At the bound the edges asked for more than any lens: no estimate (part c2).
    if error(k) > LENS_IMPROVEMENT or abs(k) >= 0.98 * MAX_DISTORTION:
        return 0.0
    moved = np.linalg.norm(undistort(corners, centre, focal, k) - corners, axis=1)
    return k if float(moved.max()) > LENS_MIN_SHIFT else 0.0


def intersect(a: tuple[Array, Array], b: tuple[Array, Array]) -> Array:
    """Where two lines (a point and a direction each) cross."""
    (p, d), (q, e) = a, b
    m = np.array([[d[0], -e[0]], [d[1], -e[1]]])
    t = np.linalg.solve(m, q - p)
    found: Array = p + t[0] * d
    return found


def fit_line(points: Array) -> tuple[Array, Array]:
    """The total least squares line: a point on it and its direction."""
    mean = points.mean(axis=0)
    _, vectors = np.linalg.eigh((points - mean).T @ (points - mean))
    return mean, vectors[:, 1]
