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

Part c5, on all seven reference photos:

- A shadow the module casts on the floor beside it is no part of it (shadowed): the shadow is
  the floor's own colour, darker and warmer, as smooth as the floor; the board begins where
  the colour changes from it (a change of material), not where the light does.
- The sides are found once more (settle) at many places along their middles, the outermost
  strong edge at each, and the corners are where the lines cross, never a rounded or chipped
  corner's own outline.
- A tilted photo's opposite sides differ: the proportions are judged as the camera model sees
  a rectangle (Zhang and He) when the plain search's outline does not have them.
- A curve module's outline is its shape (Bend: two concentric arcs and two straight gables,
  from the radii and the angle): when the outline's four corners do not fit it, it is put
  through three of them, and its sides are found again along it.
- When the outlines code found differ by more than OUTLINE_SAME, code is not sure: they are
  offered (outlines), its own first, to the AI as a question with fixed answers, or to the
  owner (cad/bildkedjan/choices.py).
- When the module's measures and the photo do not agree (misfit), the owner is told.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from cad.bildkedjan.camera import Array, distort, fit_line, focal_from_35mm, intersect, undistort

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
PROPORTION_TILTED = 0.03
"""An outline the plain search found, whose proportions as the camera model sees a rectangle
lie more than this (log of the ratio) from the module's, is a tilted photo's: its sides are
looked for again with the camera model (part c5)."""
PROPORTION_TILT = 0.15
"""The search reaches as much further as the outline's opposite sides differ, up to this (a
tilted camera), and the camera model judges the outlines found (proportion with the view,
part c5)."""
PROPORTION_TURN = 2.0
TURN_MORE = 3.0
"""Under a tilt the opposite sides converge as the other two do: the search turns as much
further, up to this many degrees (part c5)."""
"""A side looked for again lies within this share of where the proportions put it, and within
this many degrees of parallel to the opposite side."""
PROPORTION_WEIGHT = 20.0
EDGE_SATURATION = 12.0
"""A colour change across a side this large (Lab, lightness weighed less) counts in full."""
EDGE_LEAST = 4.0
SHARPEN_PX = 2.5
"""The sides are sharpened within this many of the small photo's px."""
OUTLINE_SAME = 0.01
"""Two outlines whose corners all lie within this share of the module's short side are one:
the reference photos' target for the corners (part c5)."""
MEASURES_MISFIT = 0.05
"""The photo shows the module's length over its width more than this far (log of the ratio)
from its measures: the measures or the photo are not this module, and the owner is told."""
SHADOW_DARK = 0.7
"""A cast shadow on the floor is at most this share of the floor's light beside it (part c5)."""
SHADOW_SMOOTH = 6.0
"""and smooth: the grey's spread over 7 × 7 px at most this (the floor's grain dims with it)."""
SHADOW_GREEN = 4.0
"""A shadow on the floor keeps at least half the colour (Lab a and b) of the floor lit beside
it, and is no greener (Lab a) than the floor by more than this: a dark strip of the board's own
colour, or a grey one, is no shadow."""
SHADOW_GRAIN = 16.0
"""Dark and grainier than this is the board (grass, ballast), not a shadow."""
SHADOW_STEP = 6.0
"""The board begins where the colour (Lab a and b, the light left out) changes this much from
the shadow's: a change of material, where the shadow is the floor's own colour, darker."""
SHADOW_WIDTH = 0.06
"""A shadow beside the module is at most this share of its short side wide."""
SHADOW_SHARE = 0.4
SHADOW_MOVE = 3.0
"""A side is moved past a shadow when at least this share of the places along it show one, and
the side then moves at least this many px somewhere."""
SETTLE_REACH = 0.0125
"""The sides are found again within this share of the module's short side, px (part c5)."""
SETTLE_ROWS = 96


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
    misfit: float = 0.0
    """How far the outline's proportions lie from the module's measures, as the log of their
    ratio (0 when they are not known): over MEASURES_MISFIT the photo and the measures do not
    agree, and the owner is told (part c5)."""
    seen: float | None = None
    """The outline's long sides over its short ones, as the camera sees a rectangle."""
    outlines: list[Array] = field(default_factory=list)
    """When code is not sure (part c5): the outlines it found that differ by more than
    OUTLINE_SAME of the module's short side, its own (these corners) first, to ask which one
    follows the module's edge (Vilken kontur följer modulens kant?). Empty when sure."""

    @property
    def certain(self) -> bool:
        return self.misfit <= MEASURES_MISFIT and all(r <= CORNER_RESIDUAL for r in self.residuals)


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
            return Settled(corners, [99.0] * 4, [])
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


View = tuple[float, tuple[float, float]]
"""The camera as find() knows it: the focal length and the photo's middle, in px."""


def proportion(corners: Array, view: View | None = None) -> float:
    """The outline's long sides over its short ones; with the camera (view), the rectangle's
    own as the camera model has it, so that a tilted photo, whose opposite sides differ, keeps
    the module's proportions (part c5)."""
    sides = np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1)
    first, second = sides[0] + sides[2], sides[1] + sides[3]
    plain = float(max(first, second) / max(min(first, second), 1e-9))
    if view is None:
        return plain
    seen = _rectangle_aspect(corners, view)
    if seen is None:
        return plain
    return max(seen, 1 / seen)


def _rectangle_aspect(corners: Array, view: View) -> float | None:
    """A rectangle's sides 0 → 1 over 1 → 2, from its four corners in a photo taken with a
    pinhole camera (Zhang and He, whiteboard scanning): None when the corners say nothing."""
    focal, centre = view
    c = np.asarray(corners, np.float64) - np.array(centre)
    # m1 (0, 0), m2 (w, 0), m3 (0, h), m4 (w, h).
    m1, m2, m4, m3 = (np.array([p[0], p[1], 1.0]) for p in c)
    below2, below3 = float(np.cross(m2, m4) @ m3), float(np.cross(m3, m4) @ m2)
    if abs(below2) < 1e-9 or abs(below3) < 1e-9:
        return None
    k2 = float(np.cross(m1, m4) @ m3) / below2
    k3 = float(np.cross(m1, m4) @ m2) / below3
    n2 = k2 * m2 - m1
    n3 = k3 * m3 - m1
    inverse = np.diag([1 / focal**2, 1 / focal**2, 1.0])
    top = float(n2 @ inverse @ n2)
    bottom = float(n3 @ inverse @ n3)
    if top <= 0 or bottom <= 0 or not math.isfinite(top / bottom):
        return None
    return math.sqrt(top / bottom)


def _off(corners: Array, aspect: float, view: View | None = None) -> float:
    return abs(math.log(proportion(corners, view) / aspect))


def _score(lab: NDArray[Any], corners: Array, aspect: float, view: View | None = None) -> float:
    strength = edge_strength(lab, corners, np.roll(corners, -1, axis=0))
    return float(strength.sum()) - PROPORTION_WEIGHT * max(
        0.0, _off(corners, aspect, view) - PROPORTION_SLACK
    )


def tilted(corners: Array) -> float:
    """How much the outline's opposite sides differ, as the log of their ratio: what a tilted
    camera does to a rectangle (part c5)."""
    sides = np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1)
    return float(max(abs(math.log(sides[k] / max(sides[k + 2], 1e-9))) for k in (0, 1)))


def _lines(corners: Array) -> list[tuple[Array, Array]]:
    found = []
    for i in range(4):
        d = corners[(i + 1) % 4] - corners[i]
        found.append((corners[i], d / np.linalg.norm(d)))
    return found


def _crossed(lines: list[tuple[Array, Array]]) -> Array:
    return np.array([intersect(lines[(i - 1) % 4], lines[i]) for i in range(4)])


def _side_again(
    lab: NDArray[Any], corners: Array, i: int, aspect: float, view: View | None = None
) -> Array | None:
    """The outline with side i looked for again where the opposite side and the proportions
    put it: the line nearly parallel to the opposite side, about the module's width or length
    from it (within PROPORTION_REACH, and as much more as the outline's opposite sides differ:
    a tilted photo, part c5), along which the colour changes most."""
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
    # Under a tilt the opposite sides converge as much as the other two do, about.
    a, b = lines[(i + 1) % 4][1], lines[(i + 3) % 4][1]
    converge = math.degrees(math.acos(min(1.0, abs(float(a @ b)))))
    turn = PROPORTION_TURN + (min(converge, TURN_MORE) if view is not None else 0.0)
    turns = np.radians(np.arange(-turn, turn + 0.01, 0.5))
    reach = PROPORTION_REACH + min(tilted(corners), PROPORTION_TILT)
    shares = np.arange(1 - reach, 1 + reach + 1e-9, 0.002)
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


def proportioned(
    lab: NDArray[Any], corners: Array, aspect: float, view: View | None = None
) -> Array:
    """The outline's sides looked for again, one at a time, as long as the colour changes more
    along them and their proportions, as the camera (view) sees a rectangle (part c5), come
    nearer the module's (part c3)."""
    best, score = corners, _score(lab, corners, aspect, view)
    for _ in range(6):
        options = [_side_again(lab, best, i, aspect, view) for i in range(4)]
        scored = [(_score(lab, q, aspect, view), q) for q in options if q is not None]
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


def _maps(pixels: NDArray[Any]) -> tuple[NDArray[Any], NDArray[Any], NDArray[Any]]:
    """Lab (lightness weighed less), the grey and its spread over 7 × 7 px (the texture)."""
    lab = _lab(pixels, 3)
    grey = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mean = cv2.blur(grey, (7, 7))
    spread = np.sqrt(np.maximum(cv2.blur(grey * grey, (7, 7)) - mean * mean, 0.0))
    return lab, grey, spread


def _rows(path: Array, centre: Array, rows: int) -> tuple[Array, Array]:
    """rows places along the middle of a side's path (a line is two points, an arc many), and
    the normal into the module at each."""
    lengths = np.linalg.norm(np.diff(path, axis=0), axis=1)
    total = np.concatenate([[0.0], np.cumsum(lengths)])
    at = np.linspace(0.04, 0.96, rows) * total[-1]
    base = np.stack([np.interp(at, total, path[:, 0]), np.interp(at, total, path[:, 1])], axis=1)
    if len(path) == 2:
        tangent = np.repeat(((path[1] - path[0]) / max(total[-1], 1e-9))[None, :], rows, axis=0)
    else:
        tangent = np.gradient(base, axis=0)
        tangent /= np.maximum(np.linalg.norm(tangent, axis=1), 1e-9)[:, None]
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    outward = ((centre[None, :] - base) * normal).sum(axis=1) < 0
    normal[outward] *= -1
    return base, normal


def _windowed(values: Array, size: int) -> tuple[Array, Array]:
    """The mean over the size values before each place and the size after it, along axis 1."""
    pad = np.zeros_like(values[:, :1])
    total = np.cumsum(np.concatenate([pad, values], axis=1), axis=1)
    n = values.shape[1]
    before = np.full_like(values, np.nan)
    after = np.full_like(values, np.nan)
    idx = np.arange(size, n - size)
    before[:, idx] = (total[:, idx] - total[:, idx - size]) / size
    after[:, idx] = (total[:, idx + 1 + size] - total[:, idx + 1]) / size
    return before, after


def _grey_at(image: NDArray[Any], points: Array) -> Array:
    found: Array = _sample(np.repeat(image[..., None], 3, axis=2), points)[..., 0]
    return found


def shadowed(
    maps: tuple[NDArray[Any], NDArray[Any], NDArray[Any]],
    base: Array,
    normal: Array,
    short: float,
) -> Array | None:
    """Where a side lies past a cast shadow, at each place that shows one, or None (part c5).
    The board's edge is a change of material; a cast shadow on the floor beside it is the
    floor's own colour, darker, and as smooth as the floor (its grain dims with it). At each
    place along the side, within SHADOW_WIDTH of the module's short side either way, the
    board's edge is where the colour (Lab a and b) changes most from a dark, smooth stretch of
    floor: darker than SHADOW_DARK of the floor's light further out, smoother than
    SHADOW_SMOOTH. A side that shows it along SHADOW_SHARE of its places goes there, when that
    moves it SHADOW_MOVE px or more."""
    lab, grey, spread = maps
    reach = max(10.0, SHADOW_WIDTH * short)
    win = 5
    offsets = np.arange(-reach - win - 1, reach + win + 1.01, 1.0)
    points = base[:, None, :] + offsets[None, :, None] * normal[:, None, :]
    light = _grey_at(grey, points)
    smooth = _grey_at(spread, points)
    colour = _sample(lab, points)[..., 1:]
    floor = np.nanpercentile(np.where(offsets[None, :] <= 0, light, np.nan), 90, axis=1)
    before_l, _ = _windowed(light, win)
    before_s, _ = _windowed(smooth, win)
    step = np.zeros_like(light)
    shade = []
    for c in range(2):
        before, after = _windowed(colour[..., c], win)
        step += (after - before) ** 2
        shade.append(before)
    step = np.sqrt(step)
    # The floor's own colour (Lab a and b about grey) where it is lit, further out: a shadow
    # on it keeps half of it at least, and the light off the floor around makes it warmer,
    # never greener (SHADOW_GREEN).
    lit = (offsets[None, :] <= 0) & (light >= 0.9 * floor[:, None])
    tone = [np.nanmedian(np.where(lit, colour[..., c], np.nan), axis=1) - 128.0 for c in range(2)]
    rich = np.hypot(shade[0] - 128.0, shade[1] - 128.0) >= 0.5 * np.hypot(*tone)[:, None]
    warm = (shade[0] - 128.0) >= tone[0][:, None] - SHADOW_GREEN
    same_hue = rich & warm
    with np.errstate(invalid="ignore"):
        # Nothing of the board between the floor and the shadow: no dark, grainy stretch
        # further out (a dark, smooth stretch on the board itself is no shadow).
        board = (before_l <= SHADOW_DARK * floor[:, None]) & (before_s > SHADOW_GRAIN)
        # Grainy over a stretch wider than the grain is measured over: an edge alone is not.
        stretch, _ = _windowed(board.astype(np.float64), 8)
        seen = np.cumsum(np.nan_to_num(stretch) >= 0.99, axis=1) > 0
        beyond = np.zeros_like(seen)
        beyond[:, win:] = seen[:, :-win]
        ok = (
            (np.abs(offsets)[None, :] <= reach)
            & (step >= SHADOW_STEP)
            & (before_l <= SHADOW_DARK * floor[:, None])
            & (before_s <= SHADOW_SMOOTH)
            & same_hue
            & ~beyond
        )
    score = np.where(ok, step, -1.0)
    best = np.argmax(score, axis=1)
    hit = score[np.arange(len(best)), best] > 0
    if int(hit.sum()) < max(8, SHADOW_SHARE * len(base)):
        return None
    # The shadow ends, and the board begins, where the change has risen to half its height
    # from the shadow's side: the change measured over 5 px either way peaks in the middle of
    # the blur between them.
    rows = np.nonzero(hit)[0]
    moved = np.zeros(len(rows))
    for k, row in enumerate(rows):
        g = step[row]
        j = int(best[row])
        half = 0.5 * float(g[j])
        while j > 0 and np.isfinite(g[j - 1]) and g[j - 1] >= half:
            j -= 1
        if j > 0 and np.isfinite(g[j - 1]) and g[j] > g[j - 1]:
            moved[k] = offsets[j] - (g[j] - half) / (g[j] - g[j - 1])
        else:
            moved[k] = offsets[j]
    # Whether the side moves is the changes' own places: a shadow too narrow to move it is none.
    peaks = offsets[best[rows]]
    third = max(1, len(peaks) // 3)
    if max(abs(float(np.median(peaks[:third]))), abs(float(np.median(peaks[-third:])))) < (
        SHADOW_MOVE
    ):
        return None
    found: Array = base[rows] + moved[:, None] * normal[rows]
    return found


def _outer_edges(lab: NDArray[Any], base: Array, normal: Array, reach: float) -> Array:
    """At each place, the outermost of the strong colour changes across the side within reach
    (at least half the strongest there): the board's outer edge, not an edge on the board just
    inside it, to a fraction of a px."""
    step = 0.5
    offsets = np.arange(-reach - 1, reach + 1.01, step)
    values = _sample(lab, base[:, None, :] + offsets[None, :, None] * normal[:, None, :])
    change = np.linalg.norm(values[:, 2:] - values[:, :-2], axis=-1)
    middle = offsets[1:-1]
    peak = np.zeros_like(change, dtype=bool)
    peak[:, 1:-1] = (change[:, 1:-1] >= change[:, :-2]) & (change[:, 1:-1] >= change[:, 2:])
    peak &= (np.abs(middle) <= reach)[None, :] & (change >= EDGE_LEAST)
    top = np.where(peak, change, 0.0).max(axis=1)
    strong = peak & (change >= 0.5 * top[:, None])
    found = []
    for row in np.nonzero(strong.any(axis=1))[0]:
        j = int(np.argmax(strong[row]))
        g = change[row]
        y0, y1, y2 = g[j - 1], g[j], g[j + 1]
        denominator = y0 - 2 * y1 + y2
        shift = 0.5 * (y0 - y2) / denominator if denominator < 0 else 0.0
        found.append(base[row] + (middle[j] + shift * step) * normal[row])
    return np.array(found).reshape(-1, 2)


def settle(
    pixels: NDArray[Any],
    corners: Array,
    paths: list[Array] | None = None,
    arcs: list[bool] | None = None,
    reaches: list[float] | None = None,
    shadows: bool = True,
) -> Settled:
    """The sides found once more in the full photo (part c5): at SETTLE_ROWS places along the
    middle of each (its path: a line, or a curve module's arc), past a cast shadow beside it
    (shadowed), else the outermost strong colour change across it within SETTLE_REACH of the
    module's short side (or the side's own reach); a line through them, or a bow along an arc.
    The corners are where the sides cross, never a rounded or chipped corner's own outline:
    the places leave out the side's ends."""
    maps = _maps(pixels)
    corners = np.asarray(corners, np.float64)
    centre = corners.mean(axis=0)
    short = float(np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1).min())
    bent = arcs or [False] * 4
    sides: list[Array] = []
    lines: list[tuple[Array, Array]] = []
    bows: list[Bow | None] = []
    residuals: list[float] = []
    moved: list[Array | None] = []
    for i in range(4):
        path = paths[i] if paths is not None else np.array([corners[i], corners[(i + 1) % 4]])
        base, normal = _rows(path, centre, SETTLE_ROWS)
        past = shadowed(maps, base, normal, short) if shadows else None
        moved.append(past)
        reach = max(4.0, (reaches[i] if reaches is not None else SETTLE_REACH) * short)
        points = past if past is not None else _outer_edges(maps[0], base, normal, reach)
        if len(points) < 8:
            return Settled(corners, [99.0] * 4, [])
        line, rms, kept = _robust_line(points)
        bow: Bow | None = None
        if bent[i]:
            bow, rms, kept = _robust_bow(points, corners[i], corners[(i + 1) % 4])
        if past is not None:
            # Past a shadow the places are coarser than an edge's: the lens sees them on
            # their line or bow.
            if bow is not None:
                t = (kept - bow.origin) @ bow.u
                kept = bow.point(t)
            else:
                origin, direction = line
                kept = origin + np.outer((kept - origin) @ direction, direction)
        sides.append(kept)
        lines.append(line)
        bows.append(bow)
        residuals.append(rms)
    return Settled(crossings(lines, bows), residuals, sides, list(bent), past=moved)


@dataclass(frozen=True)
class Settled(Found):
    """The sides found once more (settle), and those moved past a shadow."""

    past: list[Array | None] = field(default_factory=lambda: [None] * 4)


@dataclass(frozen=True)
class Bend:
    """A curve module's outline (part c5): its long sides' radii, mm, and its angle, degrees,
    from the owner's chord and sagitta (or the module's radius and angle) and its width."""

    outer: float
    inner: float
    angle: float

    def outline(self, places: int = 48) -> tuple[Array, list[Array]]:
        """The corners in the module's plane (outer at gable A, outer at B, inner at B, inner
        at A) and each side's path from corner i to i + 1: the outer arc, gable B, the inner
        arc and gable A."""
        turn = np.linspace(0.0, math.radians(self.angle), places)
        outer = np.stack([self.outer * np.cos(turn), self.outer * np.sin(turn)], axis=1)
        inner = np.stack([self.inner * np.cos(turn), self.inner * np.sin(turn)], axis=1)
        corners = np.array([outer[0], outer[-1], inner[-1], inner[0]])
        return corners, [outer, corners[[1, 2]], inner[::-1], corners[[3, 0]]]


BEND_FIT = 0.03
"""A curve's four corners that a turned and scaled outline of its shape does not fit within
this share of their diagonal hold one that is wrong: the outline is put through three of them
instead, the one that follows the photo's edges best (part c5)."""
GABLE_REACH = 0.03
"""A gable put by the curve's shape is looked for within this share of the short side."""


def _similar(source: Array, target: Array) -> tuple[float, Array, Array]:
    """The turn, scale and shift (no mirroring) that put the source points nearest the target
    points (Umeyama): scale, rotation, shift."""
    ms, mt = source.mean(axis=0), target.mean(axis=0)
    s, t = source - ms, target - mt
    u, sigma, vt = np.linalg.svd(t.T @ s / len(source))
    d = np.eye(2)
    if np.linalg.det(u @ vt) < 0:
        d[1, 1] = -1
    rotation = u @ d @ vt
    scale = float(np.trace(np.diag(sigma) @ d) / max((s**2).sum() / len(source), 1e-12))
    return scale, rotation, mt - scale * rotation @ ms


def _along(lab: NDArray[Any], path: Array) -> float:
    """How much the colour changes across a path, all along it: 0 to 1."""
    tangent = np.gradient(path, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1), 1e-9)[:, None]
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    change = np.linalg.norm(
        _sample(lab, path + 2 * normal) - _sample(lab, path - 2 * normal), axis=1
    )
    return float(np.minimum(change / EDGE_SATURATION, 1.0).mean())


def bent_outline(
    lab: NDArray[Any], quad: Array, bend: Bend
) -> tuple[Array, list[Array], list[bool]] | None:
    """The curve's outline put on the photo's four corners (clockwise), when they do not fit
    its shape: through the three of them, and the way round, whose outline follows the edges
    best (part c5). The corners, each side's path and which sides are arcs; None when the four
    fit the shape within BEND_FIT."""
    shape, paths = bend.outline()
    diagonal = float(np.linalg.norm(quad[0] - quad[2]))
    tried: list[tuple[float, float, Array, list[Array], list[bool]]] = []
    for mirror in (1.0, -1.0):
        flip = np.array([1.0, mirror])
        corners_m, paths_m = shape * flip, [p * flip for p in paths]
        for turn in range(4):
            order = [(turn + k) % 4 for k in range(4)]
            target = quad[order]
            for left_out in (None, 0, 1, 2, 3):
                keep = [k for k in range(4) if k != left_out]
                scale, rotation, shift = _similar(corners_m[keep], target[keep])
                placed = (scale * (rotation @ corners_m.T)).T + shift
                misfit = float(np.linalg.norm(placed[keep] - target[keep], axis=1).max())
                sides = [(scale * (rotation @ p.T)).T + shift for p in paths_m]
                corners_out = np.zeros((4, 2))
                paths_out: list[Array] = [np.zeros((0, 2))] * 4
                arcs = [False] * 4
                for k in range(4):
                    corners_out[order[k]] = placed[k]
                    paths_out[order[k]] = sides[k]
                    arcs[order[k]] = k in (0, 2)
                if left_out is None:
                    tried.append((-1.0, misfit, corners_out, paths_out, arcs))
                    continue
                score = float(np.mean([_along(lab, p) for p in sides]))
                tried.append((score - 2 * misfit / diagonal, misfit, corners_out, paths_out, arcs))
    fitting = min((t for t in tried if t[0] == -1.0), key=lambda t: t[1])
    if fitting[1] <= BEND_FIT * diagonal:
        return None
    best = max((t for t in tried if t[0] != -1.0), key=lambda t: t[0])
    return best[2], best[3], best[4]


def find(
    pixels: NDArray[Any],
    curve: bool = False,
    aspect: float | None = None,
    bend: Bend | None = None,
) -> Found | None:
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
    if curve:
        outline = None
        if bend is not None and len(found.sides) == 4:
            clean = cv2.resize(pixels, size, interpolation=cv2.INTER_AREA)
            outline = bent_outline(_lab(clean), clockwise(found.corners) * factor, bend)
        if outline is None:
            return Found(found.corners, found.residuals, found.sides, found.bent)
        # A corner the outline missed: the curve's shape put through the other three, and its
        # sides found again along it, the gables within GABLE_REACH (part c5).
        placed, paths, arcs = outline
        settled = settle(
            pixels,
            placed / factor,
            [p / factor for p in paths],
            arcs,
            [SETTLE_REACH if a else GABLE_REACH for a in arcs],
        )
        if len(settled.sides) != 4:
            return Found(placed / factor, [99.0] * 4, [])
        return replace(settled, outlines=_candidates([settled.corners, found.corners]))
    if len(found.sides) != 4:
        return found
    outline = clockwise(found.corners) * factor
    # The camera as a phone's: the photo's middle, and its focal length from the size.
    view = (focal_from_35mm((w, h), None) * factor, (w * factor / 2, h * factor / 2))
    if aspect is not None and _off(outline, aspect) > PROPORTION_SLACK:
        # The outline is not the module's shape: its sides looked for again (part c3).
        clean = cv2.resize(pixels, size, interpolation=cv2.INTER_AREA)
        better = proportioned(_lab(clean), outline, aspect)
        if _off(better, aspect, view) > PROPORTION_TILTED:
            # A tilted photo: the camera model does not see the module's proportions in the
            # outline found, so its sides are looked for as the camera model has them (c5).
            better = proportioned(_lab(clean), outline, aspect, view)
        if min(_off(better, aspect), _off(better, aspect, view)) > 2 * PROPORTION_SLACK:
            # No edges where the measures put the sides: the photo's own outline, and how far
            # its proportions lie from the measures (part c5).
            return _measured(found, factor, aspect, view)
        sharp = sharpen(full, better / factor, max(4.0, SHARPEN_PX / factor))
        if len(sharp.sides) != 4:
            # No edge where the measures put the side: the photo's own outline, and how far
            # its proportions lie from the measures (part c5).
            return _measured(found, factor, aspect, view)
        found = sharp
    settled = settle(pixels, clockwise(found.corners))
    if len(settled.sides) != 4:
        return _measured(found, factor, aspect, view)
    options = [settled.corners, found.corners]
    if any(p is not None for p in settled.past):
        # The same without moving past the shadows: the edge as the colour's strongest change.
        plain = settle(pixels, clockwise(found.corners), shadows=False)
        if len(plain.sides) == 4:
            options.insert(1, plain.corners)
    return _measured(replace(settled, outlines=_candidates(options)), factor, aspect, view)


def _candidates(options: list[Array]) -> list[Array]:
    """The outlines that differ by more than OUTLINE_SAME of the short side, the first (code's
    own) first; none when they all agree."""
    first = clockwise(np.asarray(options[0], np.float64))
    short = float(np.linalg.norm(np.roll(first, -1, axis=0) - first, axis=1).min())
    kept = [first]
    for option in options[1:]:
        quad = clockwise(np.asarray(option, np.float64))
        if all(
            float(np.linalg.norm(quad - other, axis=1).max()) > OUTLINE_SAME * short
            for other in kept
        ):
            kept.append(quad)
    return kept if len(kept) > 1 else []


def _measured(found: Found, factor: float, aspect: float | None, view: View) -> Found:
    """The outline with its proportions as the camera sees them, and how far they lie from
    the module's measures."""
    outline = clockwise(found.corners) * factor
    seen = proportion(outline, view)
    misfit = abs(math.log(seen / aspect)) if aspect is not None else 0.0
    return replace(found, misfit=misfit, seen=seen)


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
