"""Step 7 of the chain: several photos of one long module become one measuring image
(bildkedjan, Sammanfogning av flera foton).

Two to four photos, each overlapping the next by at least 30 %, each with a gable or a pair of
corners. Common points (ORB) are matched between neighbours and a homography is found robustly
(RANSAC, with a fixed seed). The photos are put in the first photo's image plane, which keeps the
first photo's camera: the mosaic is what that camera would have seen with a larger sensor, so the
camera model and the module's corners work in it as in one photo.

Then a common adjustment: each photo's homography is fitted again by least squares to the
positions its common points have in all the photos that see them, the first photo held still,
so a chain of three does not let its errors add up. Each mosaic pixel comes from the photo whose
middle is nearest, the photo taken most straight on there.

The gate (step 15): after the adjustment, the common points of two photos must agree within
GATE_MM on the module; more, and the chain asks for new photos.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from cad.bildkedjan.camera import Array, apply

FEATURES = 6000
RATIO = 0.75
RANSAC_PX = 3.0
MIN_MATCHES = 25
MAX_MOSAIC_PIXELS = 30_000_000
GATE_MM = 1.0
"""The largest disagreement in the overlap, mm (bildkedjan step 7)."""


class StitchError(Exception):
    """The photos do not go together; the message says why, in Swedish."""


@dataclass(frozen=True)
class Mosaic:
    pixels: NDArray[Any]
    homographies: list[Array]
    """Each photo's px to the mosaic's px."""
    origin: tuple[float, float]
    """Where the first photo's (0, 0) lies in the mosaic."""
    ties: list[tuple[int, int, Array, Array]]
    """For each pair of neighbours: their indices and their common points, in each photo's px."""


def _match(a: NDArray[Any], b: NDArray[Any]) -> tuple[Array, Array]:
    orb = cv2.ORB.create(nfeatures=FEATURES)
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    ka, da = orb.detectAndCompute(ga, None)
    kb, db = orb.detectAndCompute(gb, None)
    if da is None or db is None:
        return np.zeros((0, 2)), np.zeros((0, 2))
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(da, db, k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < RATIO * n.distance]
    pa = np.array([ka[m.queryIdx].pt for m in good], np.float64)
    pb = np.array([kb[m.trainIdx].pt for m in good], np.float64)
    return pa.reshape(-1, 2), pb.reshape(-1, 2)


def stitch(photos: list[NDArray[Any]]) -> Mosaic:
    """The photos in the first photo's plane, or StitchError."""
    cv2.setRNGSeed(89)
    to_first: list[Array] = [np.eye(3)]
    ties: list[tuple[int, int, Array, Array]] = []
    for i in range(1, len(photos)):
        pa, pb = _match(photos[i - 1], photos[i])
        if len(pa) < MIN_MATCHES:
            raise StitchError(
                f"Foto {i} och {i + 1} har för lite gemensamt. Ta fotona så att de "
                "överlappar minst en tredjedel."
            )
        h, inliers = cv2.findHomography(
            pb, pa, cv2.RANSAC, RANSAC_PX, maxIters=4000, confidence=0.999
        )
        if h is None or inliers is None or int(inliers.sum()) < MIN_MATCHES:
            raise StitchError(f"Foto {i} och {i + 1} går inte att lägga ihop.")
        keep = inliers.ravel() > 0
        ties.append((i - 1, i, pa[keep], pb[keep]))
        to_first.append(to_first[-1] @ h)
    to_first = _adjust(to_first, ties)
    # The mosaic's extent.
    corners = []
    for photo, h in zip(photos, to_first, strict=True):
        hh, ww = photo.shape[:2]
        corners.append(apply(h, np.array([[0, 0], [ww, 0], [ww, hh], [0, hh]], np.float64)))
    every = np.concatenate(corners)
    lo, hi = every.min(axis=0), every.max(axis=0)
    width, height = math.ceil(hi[0] - lo[0]), math.ceil(hi[1] - lo[1])
    if width * height > MAX_MOSAIC_PIXELS:
        raise StitchError("Fotona blir för stora tillsammans. Ta färre eller mindre foton.")
    shift = np.array([[1, 0, -lo[0]], [0, 1, -lo[1]], [0, 0, 1]], np.float64)
    homographies = [shift @ h for h in to_first]
    # Each pixel from the photo whose middle is nearest.
    centres = []
    for photo, h in zip(photos, homographies, strict=True):
        hh, ww = photo.shape[:2]
        centres.append(apply(h, np.array([[ww / 2, hh / 2]], np.float64))[0])
    mosaic = np.zeros((height, width, 3), np.uint8)
    best = np.full((height, width), np.inf, np.float32)
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    for photo, h, centre in zip(photos, homographies, centres, strict=True):
        warped = cv2.warpPerspective(photo, h, (width, height), flags=cv2.INTER_LINEAR)
        cover = cv2.warpPerspective(
            np.full(photo.shape[:2], 255, np.uint8), h, (width, height), flags=cv2.INTER_NEAREST
        )
        distance = (xs - centre[0]) ** 2 + (ys - centre[1]) ** 2
        take = (cover > 0) & (distance < best)
        mosaic[take] = warped[take]
        best[take] = distance[take]
    return Mosaic(mosaic, homographies, (float(-lo[0]), float(-lo[1])), ties)


def _adjust(to_first: list[Array], ties: list[tuple[int, int, Array, Array]]) -> list[Array]:
    """Each photo's homography fitted again to where its common points lie in the first
    photo's plane, seen through all the photos that see them; the first photo stays."""
    found = list(to_first)
    for _ in range(3):
        for k in range(1, len(found)):
            src: list[Array] = []
            dst: list[Array] = []
            for i, j, pi, pj in ties:
                if j == k:
                    src.append(pj)
                    dst.append((apply(found[i], pi) + apply(found[j], pj)) / 2)
                elif i == k:
                    src.append(pi)
                    dst.append((apply(found[i], pi) + apply(found[j], pj)) / 2)
            if not src:
                continue
            h, _ = cv2.findHomography(np.concatenate(src), np.concatenate(dst), 0)
            if h is not None:
                found[k] = h
    return found


def residual_mm(mosaic: Mosaic, to_mm: Array) -> float:
    """The 95th percentile of how far the common points of neighbouring photos lie apart on
    the module, mm, through the mosaic's homography to millimetres."""
    errors: list[Array] = []
    for i, j, pi, pj in mosaic.ties:
        a = apply(to_mm, apply(mosaic.homographies[i], pi))
        b = apply(to_mm, apply(mosaic.homographies[j], pj))
        errors.append(np.linalg.norm(a - b, axis=1))
    if not errors:
        return 0.0
    every = np.concatenate(errors)
    return float(np.percentile(every, 95)) if len(every) else 0.0
