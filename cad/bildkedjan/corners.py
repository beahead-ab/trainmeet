"""Step 4 of the chain: find the module in the photo (bildkedjan, Hitta modulen).

The module is the large four-sided thing in the middle of the photo that differs from what lies
around it. The photo is made small, the colours along its border are the background (the floor,
the wall, the clutter), and what differs most from them is the module. Its outline is reduced
to four corners, and each side is then found again in the full photo: the strongest edge along
the side's normal, at many places along it, with a straight line fitted through them. The
corners are where the lines cross.

A side whose edge points lie more than CORNER_RESIDUAL px from their line is uncertain: the
owner drags the handles there (bildkedjan step 15, Hörn osäkra). The owner confirms the corners
in any case, and marks Kant 1 (and so gable A, cad/bildkedjan/chain.py).

The edge points are also the plumb lines the lens is found from (camera.lens).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from cad.bildkedjan.camera import Array, distort, fit_line, intersect, undistort

WORK_SIZE = 1000
"""The photo's long side while the module is looked for, px."""
CORNER_RESIDUAL = 2.0
"""A side whose edge lies more than this from its line, in px, is uncertain (bildkedjan step 15)."""
SAMPLES = 48
LIGHTNESS_WEIGHT = 0.35
EDGE_CONTRAST = 6.0
"""How much more the inside must differ from the background than the outside does."""
BENT_PX = 4.0
"""A side of the module's outline that bows more than this from its chord, in the photo's px, is
an arc (a curve module's long side, bildkedjan step 6, part c2): its edge is looked for along
the arc, and its corners are where its tangents at the ends cross the gables."""
BENT_SHARE = 0.7
"""And its edge points lie this much nearer the bow than the straight line (RMS)."""


@dataclass(frozen=True)
class Bow:
    """A side as a parabola over its chord: offset c[0]·t² + c[1]·t + c[2] toward n at origin
    + t·u."""

    origin: Array
    u: Array
    n: Array
    c: Array

    def point(self, t: Array) -> Array:
        off = np.polyval(self.c, t)
        found: Array = self.origin + np.outer(t, self.u) + np.outer(off, self.n)
        return found

    def normal(self, t: Array) -> Array:
        """Into the module, at each t."""
        slope = 2 * self.c[0] * t + self.c[1]
        tangent = self.u[None, :] + slope[:, None] * self.n[None, :]
        tangent /= np.linalg.norm(tangent, axis=1)[:, None]
        found: Array = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
        return found

    def tangent(self, near: Array) -> tuple[Array, Array]:
        """The tangent line where the parabola passes nearest the point."""
        t = np.array([float((near - self.origin) @ self.u)])
        slope = float(2 * self.c[0] * t[0] + self.c[1])
        direction = self.u + slope * self.n
        return self.point(t)[0], direction / np.linalg.norm(direction)


def bow_of(points: Array, a: Array, b: Array, least: float = BENT_PX) -> Bow | None:
    """The parabola through the side's points from a to b, when it bows more than least px."""
    d = b - a
    length = float(np.linalg.norm(d))
    if length < 10 or len(points) < 8:
        return None
    u = d / length
    n = np.array([-u[1], u[0]])
    t = (points - a) @ u
    off = (points - a) @ n
    inside = (t > 0.03 * length) & (t < 0.97 * length)
    if int(inside.sum()) < 8:
        return None
    c = np.polyfit(t[inside], off[inside], 2)
    if abs(float(c[0])) * (length / 2) ** 2 < least:
        return None
    return Bow(a, u, n, c)


def _robust_bow(points: Array, a: Array, b: Array) -> tuple[Bow | None, float, Array]:
    """The parabola through the edge points, leaving out those far from it; the RMS of those
    kept. None when the side is straight after all."""
    kept = points
    bow = bow_of(kept, a, b, 0.0)
    if bow is None:
        return None, 99.0, points
    for _ in range(3):
        t = (points - bow.origin) @ bow.u
        off = np.abs((points - bow.origin) @ bow.n - np.polyval(bow.c, t))
        cut = max(1.0, 3 * float(np.median(off)) * 1.4826)
        kept = points[off <= cut]
        if len(kept) < 8:
            kept = points
            break
        bow = bow_of(kept, a, b, 0.0) or bow
    t = (kept - bow.origin) @ bow.u
    rms = float(np.sqrt(np.mean(((kept - bow.origin) @ bow.n - np.polyval(bow.c, t)) ** 2)))
    return bow, rms, kept


def crossings(lines: list[tuple[Array, Array]], bows: list[Bow | None]) -> Array:
    """The corners where the sides cross: lines, or a bent side's tangent nearest the corner."""
    corners = np.array([intersect(lines[(i - 1) % 4], lines[i]) for i in range(4)])
    if not any(bows):
        return corners
    for _ in range(4):
        found = []
        for i in range(4):
            before, after = bows[(i - 1) % 4], bows[i]
            first = before.tangent(corners[i]) if before is not None else lines[(i - 1) % 4]
            second = after.tangent(corners[i]) if after is not None else lines[i]
            found.append(intersect(first, second))
        corners = np.array(found)
    return corners


@dataclass(frozen=True)
class Found:
    corners: Array
    """Four corners in the photo's px, clockwise as seen, the first nearest the top left."""
    residuals: list[float]
    """Each side's edge points' distance from its line, px (RMS), side i from corner i to i+1."""
    sides: list[Array]
    """The edge points of each side, for the lens."""
    bent: list[bool] = field(default_factory=lambda: [False] * 4)
    """Which sides the outline shows bent (a curve module's long sides): arcs for the lens, and
    their corners where their tangents cross the gables (part c2)."""

    @property
    def certain(self) -> bool:
        return all(r <= CORNER_RESIDUAL for r in self.residuals)


def _clockwise_order(corners: Array) -> list[int]:
    """The indices that put the corners clockwise as seen, the first nearest the top left."""
    ordered = clockwise(corners)
    return [int(np.argmin(np.linalg.norm(corners - c, axis=1))) for c in ordered]


def clockwise(corners: Array) -> Array:
    """The corners in clockwise order as seen (y down), the first nearest the top left."""
    centre = corners.mean(axis=0)
    angles = np.arctan2(corners[:, 1] - centre[1], corners[:, 0] - centre[0])
    ordered = corners[np.argsort(angles)]
    first = int(np.argmin(ordered.sum(axis=1)))
    found: Array = np.roll(ordered, -first, axis=0)
    return found


def _lab(pixels: NDArray[Any], blur: int = 5) -> NDArray[Any]:
    lab = cv2.cvtColor(cv2.GaussianBlur(pixels, (blur, blur), 0), cv2.COLOR_BGR2LAB)
    found = lab.astype(np.float32)
    # The light varies over a photo more than the colours do: lightness counts for less.
    found[..., 0] *= LIGHTNESS_WEIGHT
    return found


def _mask(small: NDArray[Any]) -> tuple[NDArray[Any], NDArray[Any]]:
    """What differs from the photo's border: the module, as 255. The colours far from every
    colour along the border start as the module, and GrabCut's colour models settle it."""
    lab = _lab(small)
    h, w = lab.shape[:2]
    band = max(4, int(0.04 * min(h, w)))
    border = np.concatenate(
        [
            lab[:band].reshape(-1, 3),
            lab[-band:].reshape(-1, 3),
            lab[:, :band].reshape(-1, 3),
            lab[:, -band:].reshape(-1, 3),
        ]
    )
    cv2.setRNGSeed(89)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, _, centres = cv2.kmeans(border, 6, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    distance = np.full((h, w), np.inf, np.float32)
    for centre in centres:
        distance = np.minimum(distance, np.linalg.norm(lab - centre, axis=2))
    scaled = np.clip(distance * (255.0 / max(float(np.percentile(distance, 99)), 1.0)), 0, 255)
    _, otsu = cv2.threshold(scaled.astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    marks = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    marks[otsu > 0] = cv2.GC_PR_FGD
    inner_y, inner_x = slice(int(0.3 * h), int(0.7 * h)), slice(int(0.3 * w), int(0.7 * w))
    marks[inner_y, inner_x] = cv2.GC_PR_FGD
    marks[:band] = marks[-band:] = cv2.GC_BGD
    marks[:, :band] = marks[:, -band:] = cv2.GC_BGD
    background = np.zeros((1, 65), np.float64)
    foreground = np.zeros((1, 65), np.float64)
    cv2.setRNGSeed(89)
    cv2.grabCut(  # type: ignore[call-overload]
        small, marks, None, background, foreground, 4, cv2.GC_INIT_WITH_MASK
    )
    chosen = (marks == cv2.GC_FGD) | (marks == cv2.GC_PR_FGD)
    mask: NDArray[Any] = np.where(chosen, 255, 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
    # The largest piece, with its holes filled.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count <= 1:
        return np.zeros_like(mask), centres
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    found = np.where(labels == largest, 255, 0).astype(np.uint8)
    contours, _ = cv2.findContours(found, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(found)
    cv2.drawContours(filled, contours, -1, 255, -1)
    return filled, centres


def _quad(mask: NDArray[Any]) -> Array | None:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    hull = cv2.convexHull(max(contours, key=cv2.contourArea))
    perimeter = cv2.arcLength(hull, True)
    lo, hi = 0.001, 0.2
    best: Array | None = None
    for _ in range(40):
        mid = (lo + hi) / 2
        approx = cv2.approxPolyDP(hull, mid * perimeter, True)
        if len(approx) > 4:
            lo = mid
        else:
            hi = mid
            if len(approx) == 4:
                best = approx.reshape(4, 2).astype(np.float64)
    return best


def _edge_points(
    lab: NDArray[Any], a: Array, b: Array, reach: float, bow: Bow | None = None
) -> Array:
    """Points where the colour first leaves the colour just outside the side from a to b, at
    SAMPLES places: the module's outer edge, also where its frame or scenery has edges of its
    own just inside, and whatever the light does over the photo. A bent side is followed along
    its bow."""
    d = b - a
    length = float(np.linalg.norm(d))
    if length < 10:
        return np.zeros((0, 2))
    u = d / length
    ts = np.linspace(0.08, 0.92, SAMPLES)
    step = 0.5
    offsets = np.arange(-reach, reach + step / 2, step)
    if bow is None:
        middle = a[None, :] + ts[:, None] * d[None, :]
        normals = np.repeat(np.array([[-u[1], u[0]]]), len(ts), axis=0)  # into the module
    else:
        middle = bow.point(ts * length)
        normals = bow.normal(ts * length)
    xs = (middle[:, None, 0] + offsets[None, :] * normals[:, None, 0]).astype(np.float32)
    ys = (middle[:, None, 1] + offsets[None, :] * normals[:, None, 1]).astype(np.float32)
    sampled = np.stack(
        [
            cv2.remap(lab[..., c], xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            for c in range(3)
        ],
        axis=-1,
    )
    near = 6
    found = []
    for row in range(len(ts)):
        outside = sampled[row, :near].mean(axis=0)
        distance = np.linalg.norm(sampled[row] - outside, axis=1)
        noise = float(distance[:near].std()) + float(distance[:near].mean())
        level = max(EDGE_CONTRAST, 4 * noise)
        over = distance >= level
        # The first place it stays over the level for three samples.
        steady = over[:-2] & over[1:-1] & over[2:]
        hits = np.nonzero(steady)[0]
        if not len(hits) or hits[0] < near:
            continue
        first = int(hits[0])
        grad = np.diff(distance)
        lo, hi = max(0, first - 4), min(len(grad), first + 3)
        i = lo + int(np.argmax(grad[lo:hi]))
        shift = 0.0
        if 0 < i < len(grad) - 1:
            y0, y1, y2 = grad[i - 1], grad[i], grad[i + 1]
            denominator = y0 - 2 * y1 + y2
            shift = 0.5 * (y0 - y2) / denominator if denominator < 0 else 0.0
        found.append(middle[row] + (offsets[i] + step / 2 + shift * step) * normals[row])
    return np.array(found).reshape(-1, 2)


def _robust_line(points: Array) -> tuple[tuple[Array, Array], float, Array]:
    """The line through the points, leaving out those far from it; the RMS of those kept."""
    kept = points
    for _ in range(3):
        line = fit_line(kept)
        normal = np.array([-line[1][1], line[1][0]])
        off = np.abs((points - line[0]) @ normal)
        cut = max(1.0, 3 * float(np.median(off)) * 1.4826)
        kept = points[off <= cut]
        if len(kept) < 6:
            kept = points
            break
    line = fit_line(kept)
    normal = np.array([-line[1][1], line[1][0]])
    rms = float(np.sqrt(np.mean(((kept - line[0]) @ normal) ** 2)))
    return line, rms, kept


def refine(
    lab: NDArray[Any], corners: Array, reach: float, guides: list[Bow | None] | None = None
) -> Found:
    """The four sides found again in the full photo near the given corners; a side the outline
    shows bent (guides) along its bow."""
    sides: list[Array] = []
    lines: list[tuple[Array, Array]] = []
    bows: list[Bow | None] = []
    residuals: list[float] = []
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        guide = guides[i] if guides is not None else None
        points = _edge_points(lab, a, b, reach, guide)
        if len(points) < 8:
            return Found(corners, [99.0] * 4, [])
        line, rms, kept = _robust_line(points)
        bow: Bow | None = None
        if guide is not None:
            bow, bent_rms, bent_kept = _robust_bow(points, a, b)
            if (
                bow is not None
                and abs(float(bow.c[0])) * (float(np.linalg.norm(b - a)) / 2) ** 2 >= BENT_PX
                and bent_rms < BENT_SHARE * rms
            ):
                rms, kept = bent_rms, bent_kept
            else:
                bow = None
        sides.append(kept)
        lines.append(line)
        bows.append(bow)
        residuals.append(rms)
    # A side followed along its bow is an arc for the lens, whether or not its edge points
    # bettered the line for the corners.
    arced = [g is not None for g in guides] if guides is not None else [False] * 4
    found = crossings(lines, bows)
    if np.max(np.linalg.norm(found - corners, axis=1)) > 4 * reach:
        return Found(corners, [99.0] * 4, sides, arced)
    return Found(found, residuals, sides, arced)


def _guides(mask: NDArray[Any], quad: Array, factor: float) -> list[Bow | None]:
    """Each long side's bow as the outline shows it, in the full photo's px: None for a
    straight side and for the gables, which are straight on a curve module too."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return [None] * 4
    outline = max(contours, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
    count = len(outline)
    at = [int(np.argmin(np.linalg.norm(outline - q, axis=1))) for q in quad]
    found: list[Bow | None] = []
    lengths = [float(np.linalg.norm(quad[(i + 1) % 4] - quad[i])) for i in range(4)]
    long_sides = sorted(range(4), key=lambda i: -lengths[i])[:2]
    for i in range(4):
        if i not in long_sides:
            found.append(None)
            continue
        start, end = at[i], at[(i + 1) % 4]
        others = {at[(i + 2) % 4], at[(i + 3) % 4]}
        forward = [(start + k) % count for k in range((end - start) % count + 1)]
        if others & set(forward):
            forward = [(start - k) % count for k in range((start - end) % count + 1)]
        points = outline[forward] / factor
        found.append(bow_of(points, quad[i] / factor, quad[(i + 1) % 4] / factor))
    return found


def find(pixels: NDArray[Any], curve: bool = False) -> Found | None:
    """The module's four corners in the photo, or None when nothing four-sided stands out. A
    curve module's long sides may be arcs (curve): a side its outline shows bent is followed
    along its bow. A straight module's sides are lines, however the lens bends them."""
    h, w = pixels.shape[:2]
    factor = WORK_SIZE / max(h, w)
    small = cv2.resize(pixels, (round(w * factor), round(h * factor)), interpolation=cv2.INTER_AREA)
    mask, _ = _mask(small)
    quad = _quad(mask)
    if quad is None:
        return None
    area = cv2.contourArea(quad.astype(np.float32))
    if area < 0.05 * small.shape[0] * small.shape[1]:
        return None
    order = _clockwise_order(quad)
    quad = quad[order]
    corners = quad / factor
    reach = max(10.0, 8 / factor)
    guides = _guides(mask, quad, factor) if curve else None
    found = refine(_lab(pixels, 3), corners, reach, guides)
    return Found(found.corners, found.residuals, found.sides, found.bent)


def through_lens(found: Found, centre: tuple[float, float], f: float, k: float) -> Array:
    """The corners where the sides cross once the lens is taken out: straight lines in the
    undistorted photo, the crossings put back in the photo's px."""
    if k == 0 or len(found.sides) != 4:
        return found.corners
    straight = [undistort(side, centre, f, k) for side in found.sides]
    lines = [fit_line(side) for side in straight]
    corners = undistort(found.corners, centre, f, k)
    bows = [
        bow_of(side, corners[i], corners[(i + 1) % 4], 0.0) if found.bent[i] else None
        for i, side in enumerate(straight)
    ]
    return distort(crossings(lines, bows), centre, f, k)
