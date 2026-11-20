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

Part c3, on real photos (the module on a floor or against a wall, with clutter and shadows):

- The chat's red numbers (saturated red, thin strokes) are painted out before the edges are
  looked for (marks, unmarked). The rough outline is found in the photo as sent: painted out,
  the border's colours that GrabCut learns from change, and with them a curve's outline.
- When the module's proportions are known (a straight module's length and width), they decide
  whether the outline is the module: a photo from above shows them to within a percent or two.
  When the outline's are off by more than PROPORTION_SLACK, the side that is wrong is looked for
  where the opposite side and the proportions put it: a line parallel to it, within
  PROPORTION_REACH of the distance, along which the colour changes most across it all the way
  (the board's edge, not a platform's or a shadow's). Side by side, as long as it gets better.
- The sides are then sharpened (sharpen): at many places along each side the colour's strongest
  change across it, the innermost where a shadow lies outside, to a fraction of a px (a
  parabola through the best three), and a line fitted through them, leaving out those far
  from it. This is what a line segment detector (LSD) does along a side it already has.
"""

from __future__ import annotations

import math
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
RED_HUE = 8
RED_SATURATION = 150
RED_VALUE = 120
"""The chat's red: within this of pure red's hue (OpenCV's 0–180), and this saturated and bright."""
RED_STROKE = 0.012
"""A red mark is strokes at most this share of the photo's short side wide (half: from the middle
of a stroke to its edge)."""
RED_MIN_PX = 30
PROPORTION_SLACK = 0.015
"""The outline's proportions may be this far off the module's (log of the ratio) before its
sides are looked for again: the reference photos show them within 1 %."""
PROPORTION_REACH = 0.04
PROPORTION_TURN = 2.0
"""A side looked for again lies within this share of where the proportions put it, and within
this many degrees of parallel to the opposite side."""
PROPORTION_WEIGHT = 20.0
EDGE_SATURATION = 12.0
"""A colour change across a side this large (Lab, lightness weighed less) counts in full."""
EDGE_LEAST = 4.0
SHARPEN_PX = 2.5
"""The sides are sharpened within this many of the small photo's px."""


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


def marks(pixels: NDArray[Any]) -> NDArray[Any]:
    """The chat's red numbers and letters drawn over the photo, as 255: saturated red in thin
    strokes (bildkedjan step 4, Mask)."""
    hsv = cv2.cvtColor(pixels, cv2.COLOR_BGR2HSV)
    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    red = (
        ((hue <= RED_HUE) | (hue >= 180 - RED_HUE))
        & (saturation >= RED_SATURATION)
        & (value >= RED_VALUE)
    ).astype(np.uint8)
    found: NDArray[Any] = np.zeros_like(red)
    if not red.any():
        return found
    count, labels, stats, _ = cv2.connectedComponentsWithStats(red, connectivity=8)
    half = cv2.distanceTransform(red, cv2.DIST_L2, 3)
    widest = RED_STROKE * min(pixels.shape[:2])
    # Each piece's widest place, all at once.
    thickest = np.zeros(count, np.float32)
    np.maximum.at(thickest, labels.ravel().astype(np.intp), half.ravel())
    keep = (stats[:, cv2.CC_STAT_AREA] >= RED_MIN_PX) & (thickest <= widest)
    keep[0] = False
    found[keep[labels]] = 255
    grown: NDArray[Any] = cv2.dilate(found, np.ones((7, 7), np.uint8))
    return grown


def unmarked(pixels: NDArray[Any]) -> NDArray[Any]:
    """The photo with the chat's red marks painted out from around them."""
    drawn = marks(pixels)
    if not drawn.any():
        return pixels
    found: NDArray[Any] = cv2.inpaint(pixels, drawn, 5, cv2.INPAINT_TELEA)
    return found


def _sample(lab: NDArray[Any], points: Array) -> NDArray[Any]:
    """The Lab image at the px points (..., 2), bilinear: (..., 3)."""
    shape = points.shape[:-1]
    flat = points.reshape(-1, 2)
    n = len(flat)
    width = 1024
    rows = max(1, -(-n // width))
    pad = rows * width - n
    xs = np.concatenate([flat[:, 0], np.zeros(pad)]).reshape(rows, width).astype(np.float32)
    ys = np.concatenate([flat[:, 1], np.zeros(pad)]).reshape(rows, width).astype(np.float32)
    found = np.stack(
        [
            cv2.remap(lab[..., c], xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            for c in range(3)
        ],
        axis=-1,
    )
    sampled: NDArray[Any] = found.reshape(-1, 3)[:n].reshape(*shape, 3)
    return sampled


def edge_strength(lab: NDArray[Any], a: Array, b: Array) -> Array:
    """How much the colour changes across the line from a to b, all along it: 0 to 1 (a full
    EDGE_SATURATION at every place), for any number of lines (..., 2)."""
    d = b - a
    length = np.linalg.norm(d, axis=-1, keepdims=True)
    u = d / np.maximum(length, 1e-9)
    n = np.stack([-u[..., 1], u[..., 0]], axis=-1)[..., None, :]
    ts = np.linspace(0.05, 0.95, 48)
    base = a[..., None, :] + ts[:, None] * d[..., None, :]
    change = np.linalg.norm(_sample(lab, base + 2.0 * n) - _sample(lab, base - 2.0 * n), axis=-1)
    found: Array = np.minimum(change / EDGE_SATURATION, 1.0).mean(axis=-1)
    return found


def proportion(corners: Array) -> float:
    """The outline's long sides over its short ones."""
    sides = np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1)
    first, second = sides[0] + sides[2], sides[1] + sides[3]
    return float(max(first, second) / max(min(first, second), 1e-9))


def _off(corners: Array, aspect: float) -> float:
    return abs(math.log(proportion(corners) / aspect))


def _score(lab: NDArray[Any], corners: Array, aspect: float) -> float:
    strength = edge_strength(lab, corners, np.roll(corners, -1, axis=0))
    return float(strength.sum()) - PROPORTION_WEIGHT * max(
        0.0, _off(corners, aspect) - PROPORTION_SLACK
    )


def _lines(corners: Array) -> list[tuple[Array, Array]]:
    found = []
    for i in range(4):
        d = corners[(i + 1) % 4] - corners[i]
        found.append((corners[i], d / np.linalg.norm(d)))
    return found


def _crossed(lines: list[tuple[Array, Array]]) -> Array:
    return np.array([intersect(lines[(i - 1) % 4], lines[i]) for i in range(4)])


def _side_again(lab: NDArray[Any], corners: Array, i: int, aspect: float) -> Array | None:
    """The outline with side i looked for again where the opposite side and the proportions
    put it: the line nearly parallel to the opposite side, about the module's width or length
    from it, along which the colour changes most."""
    lines = _lines(corners)
    sides = np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1)
    long_pair = 0 if sides[0] + sides[2] >= sides[1] + sides[3] else 1
    opposite = lines[(i + 2) % 4]
    if i % 2 == long_pair:
        # A long side: the module's width from the other long side, by that side's length.
        distance = sides[(i + 2) % 4] / aspect
    else:
        # A short side: the module's length from the other, by the long sides' distance.
        lb = lines[(i + 3) % 4]
        middle = (corners[(i + 1) % 4] + corners[(i + 2) % 4]) / 2
        distance = abs(float((middle - lb[0]) @ np.array([-lb[1][1], lb[1][0]]))) * aspect
    u = -opposite[1]
    n = np.array([-u[1], u[0]])
    if float((corners[i] - opposite[0]) @ n) < 0:
        n = -n
    turns = np.radians(np.arange(-PROPORTION_TURN, PROPORTION_TURN + 0.01, 0.5))
    shares = np.arange(1 - PROPORTION_REACH, 1 + PROPORTION_REACH + 1e-9, 0.002)
    candidates: list[Array] = []
    for turn in turns:
        c, s_ = math.cos(float(turn)), math.sin(float(turn))
        direction = np.array([u[0] * c - u[1] * s_, u[0] * s_ + u[1] * c])
        for share in shares:
            new = list(lines)
            new[i] = (opposite[0] + n * distance * float(share), direction)
            quad = _crossed(new)
            if np.isfinite(quad).all():
                candidates.append(quad)
    if not candidates:
        return None
    quads = np.array(candidates)
    strength = edge_strength(lab, quads[:, i], quads[:, (i + 1) % 4])
    found: Array = quads[int(np.argmax(strength))]
    return found


def proportioned(lab: NDArray[Any], corners: Array, aspect: float) -> Array:
    """The outline's sides looked for again, one at a time, as long as the colour changes more
    along them and their proportions come nearer the module's (part c3)."""
    best, score = corners, _score(lab, corners, aspect)
    for _ in range(6):
        options = [_side_again(lab, best, i, aspect) for i in range(4)]
        scored = [(_score(lab, q, aspect), q) for q in options if q is not None]
        if not scored:
            break
        top, quad = max(scored, key=lambda pair: pair[0])
        if top <= score + 0.02:
            break
        best, score = quad, top
    return best


def sharpen(lab: NDArray[Any], corners: Array, reach: float) -> Found:
    """Each side found again near the given corners: at SAMPLES places the strongest colour
    change across it within reach (the innermost of those at least half as strong, so that a
    shadow outside the board does not draw the side out), to a fraction of a px, and a line
    through them; the corners where the lines cross."""
    centre = corners.mean(axis=0)
    sides: list[Array] = []
    lines: list[tuple[Array, Array]] = []
    residuals: list[float] = []
    step = 0.5
    offsets = np.arange(-reach, reach + step / 2, step)
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        d = b - a
        u = d / np.linalg.norm(d)
        n = np.array([-u[1], u[0]])
        inward = float((centre - a) @ n) > 0
        ts = np.linspace(0.08, 0.92, SAMPLES)
        base = a[None, :] + ts[:, None] * d[None, :]
        values = _sample(lab, base[:, None, :] + offsets[None, :, None] * n[None, None, :])
        change = np.linalg.norm(values[:, 2:] - values[:, :-2], axis=-1)
        found = []
        for row in range(len(ts)):
            g = change[row]
            top = float(g.max())
            if top < EDGE_LEAST:
                continue
            peaks = [
                j
                for j in range(1, len(g) - 1)
                if g[j] >= g[j - 1] and g[j] >= g[j + 1] and g[j] >= 0.5 * top
            ]
            if not peaks:
                continue
            j = max(peaks) if inward else min(peaks)
            y0, y1, y2 = g[j - 1], g[j], g[j + 1]
            denominator = y0 - 2 * y1 + y2
            shift = 0.5 * (y0 - y2) / denominator if denominator < 0 else 0.0
            found.append(base[row] + (offsets[j + 1] + shift * step) * n)
        points = np.array(found).reshape(-1, 2)
        if len(points) < 8:
            return Found(corners, [99.0] * 4, [])
        line, rms, kept = _robust_line(points)
        sides.append(kept)
        lines.append(line)
        residuals.append(rms)
    return Found(_crossed(lines), residuals, sides)


def find(pixels: NDArray[Any], curve: bool = False, aspect: float | None = None) -> Found | None:
    """The module's four corners in the photo, or None when nothing four-sided stands out. A
    curve module's long sides may be arcs (curve): a side its outline shows bent is followed
    along its bow. A straight module's sides are lines, however the lens bends them. aspect: a
    straight module's length over its width, when the owner has given them."""
    h, w = pixels.shape[:2]
    factor = WORK_SIZE / max(h, w)
    size = (round(w * factor), round(h * factor))
    # The rough outline from the photo as sent; the edges are looked for with the chat's red
    # marks painted out (painted out, the border's colours GrabCut learns from change too).
    small = cv2.resize(pixels, size, interpolation=cv2.INTER_AREA)
    mask, _ = _mask(small)
    pixels = unmarked(pixels)
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
    full = _lab(pixels, 3)
    found = refine(full, corners, reach, guides)
    if curve or aspect is None or len(found.sides) != 4:
        return Found(found.corners, found.residuals, found.sides, found.bent)
    outline = clockwise(found.corners) * factor
    if _off(outline, aspect) <= PROPORTION_SLACK:
        return Found(found.corners, found.residuals, found.sides, found.bent)
    # The outline is not the module's shape: its sides looked for again (part c3).
    clean = cv2.resize(pixels, size, interpolation=cv2.INTER_AREA)
    better = proportioned(_lab(clean), outline, aspect)
    sharp = sharpen(full, better / factor, max(4.0, SHARPEN_PX / factor))
    if len(sharp.sides) != 4:
        return Found(better / factor, [99.0] * 4, [])
    return sharp


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
