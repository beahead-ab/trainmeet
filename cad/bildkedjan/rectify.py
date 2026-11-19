"""Step 6 and 8 of the chain: the measuring image (bildkedjan, Uträtning och höjd, Ljus och färg).

The measuring image is the photo straightened to a view from above in a fixed scale, MEASURE_PPM
px per mm, cut to the module with a small margin, in the module's own millimetres: x from gable
A along Kant 1, y away from Kant 1. It is made in the plane of the rails' top, so that the tracks
are measured where they lie and not where the frame is (step 6, Höjdskillnaden). It is what is
kept (CAD4), what the Foto tab and Fotot under show, and what the tracks are read from; a smaller
copy at DISPLAY_PPM is what the web app shows.

The light (step 8): the illumination is estimated with a large filter inside the module and
divided out, so an even light and a shadow look alike to the track map; the hard edge of a
shadow from outside is masked before the tracks are read, not only in the landscape. Clipped
highlights larger than a rail's glint are masked too; a shiny rail head is a clue and is kept.
The white balance is taken from the neutral surfaces (ballast and white parts).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from cad.bildkedjan.camera import Array, Camera

MEASURE_PPM = 2.0
"""The measuring image's scale (bildkedjan step 8: 2 px per mm)."""
DISPLAY_PPM = 1.0
MARGIN = 10.0
"""mm around the module."""
ILLUMINATION_MM = 150.0
"""The size of the median the illumination is estimated with, mm: larger than the ballast's
bands, so they stay, and smaller than a shadow, whose edge it keeps."""
SHADOW = 0.72
"""Darker than this share of the module's usual light is a shadow."""
SHADOW_EDGE_MM = 5.0
CLIPPED = 250
GLINT_MM2 = 25.0
"""A clipped patch larger than this, mm², is a reflection; smaller is a rail's glint."""

Image3 = NDArray[Any]
Mask = NDArray[Any]


@dataclass(frozen=True)
class Grid:
    """An image in the module's millimetres: pixel (0, 0)'s centre is at (x0, y0) mm."""

    x0: float
    y0: float
    ppm: float
    width: int
    height: int

    def to_px(self, points: Array) -> Array:
        found: Array = (points - np.array([self.x0, self.y0])) * self.ppm
        return found

    def to_mm(self, pixels: Array) -> Array:
        found: Array = pixels / self.ppm + np.array([self.x0, self.y0])
        return found

    def scaled(self, ppm: float) -> Grid:
        factor = ppm / self.ppm
        return Grid(self.x0, self.y0, ppm, round(self.width * factor), round(self.height * factor))


def grid_for(corners_mm: Array, ppm: float = MEASURE_PPM, margin: float = MARGIN) -> Grid:
    lo = corners_mm.min(axis=0) - margin
    hi = corners_mm.max(axis=0) + margin
    return Grid(
        float(lo[0]),
        float(lo[1]),
        ppm,
        math.ceil((hi[0] - lo[0]) * ppm),
        math.ceil((hi[1] - lo[1]) * ppm),
    )


def rectify(pixels: Image3, camera: Camera, grid: Grid, z: float) -> Image3:
    """The photo seen from above in the plane z mm above the frame."""
    xs, ys = np.meshgrid(
        np.arange(grid.width, dtype=np.float64), np.arange(grid.height, dtype=np.float64)
    )
    mm = grid.to_mm(np.stack([xs.ravel(), ys.ravel()], axis=1))
    px = camera.to_image(mm, z).astype(np.float32)
    map_x = px[:, 0].reshape(grid.height, grid.width)
    map_y = px[:, 1].reshape(grid.height, grid.width)
    found: Image3 = cv2.remap(pixels, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT)
    return found


def module_mask(grid: Grid, corners_mm: Array, inset: float = 0.0) -> Mask:
    """The module's own area in the image, shrunk by inset mm."""
    mask: NDArray[Any] = np.zeros((grid.height, grid.width), np.uint8)
    polygon = np.round(grid.to_px(corners_mm) * 16).astype(np.int32)
    cv2.fillPoly(mask, [polygon], 255, cv2.LINE_8, shift=4)
    if inset > 0:
        size = max(1, round(inset * grid.ppm))
        mask = cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * size + 1,) * 2))
    found: Mask = mask > 0
    return found


@dataclass(frozen=True)
class Light:
    """The measuring image with even light and balanced colour, and the masks."""

    image: Image3
    shadow_edge: Mask
    reflections: Mask
    shadow_share: float
    clipped_share: float
    gains: tuple[float, float, float]


def illumination(values: NDArray[Any], inside: Mask, size: float) -> NDArray[Any]:
    """The light falling on the module: a median over size px, which keeps a shadow's hard
    edge where a blur would smear it, from inside the module only, then lightly smoothed."""
    small = 8
    h, w = values.shape
    shape = (max(1, w // small), max(1, h // small))
    sv = cv2.resize(values, shape, interpolation=cv2.INTER_AREA)
    sm = cv2.resize(inside.astype(np.uint8), shape, interpolation=cv2.INTER_NEAREST) > 0
    usual = float(np.median(sv[sm])) if sm.any() else 128.0
    # Outside the module the light is taken as the module's usual, so its edge is no shadow.
    sv = np.where(sm, sv, usual).astype(np.float32)
    k = max(3, int(size / small) | 1)
    median: NDArray[Any] = cv2.medianBlur(np.clip(sv, 0, 255).astype(np.uint8), min(k, 255))
    median = median.astype(np.float32)
    median = cv2.GaussianBlur(median, (0, 0), 1.0)
    found = cv2.resize(median, (w, h), interpolation=cv2.INTER_LINEAR)
    return found.astype(np.float32)


def even_light(image: Image3, inside: Mask, ppm: float) -> Light:
    """The light normalised, the white balanced, and the shadow edges and reflections masked."""
    work = image.astype(np.float32)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    light = illumination(gray, inside, ILLUMINATION_MM * ppm)
    usual = float(np.median(light[inside])) if inside.any() else 128.0
    shadow = (light < SHADOW * usual) & inside
    edge = np.zeros_like(inside)
    if shadow.any():
        band = max(1, round(SHADOW_EDGE_MM * ppm))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * band + 1,) * 2)
        shadow_u8 = shadow.astype(np.uint8)
        grown = cv2.dilate(shadow_u8, kernel) > 0
        shrunk = cv2.erode(shadow_u8, kernel) > 0
        edge = grown & ~shrunk & inside
    evened = work * (usual / np.maximum(light, 1.0))[..., None]
    # The white balance from the neutral surfaces: light and with little colour.
    hsv = cv2.cvtColor(np.clip(evened, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV)
    neutral = inside & (hsv[..., 1] < 40) & (hsv[..., 2] > 120)
    gains = (1.0, 1.0, 1.0)
    if int(neutral.sum()) > 200:
        means = evened[neutral].mean(axis=0)
        grey = float(means.mean())
        gains = tuple(float(np.clip(grey / max(m, 1.0), 0.7, 1.4)) for m in means)  # type: ignore[assignment]
        evened = evened * np.array(gains, np.float32)
    clipped = (image.max(axis=2) >= CLIPPED) & inside
    reflections = np.zeros_like(inside)
    if clipped.any():
        _count, labels, stats, _ = cv2.connectedComponentsWithStats(clipped.astype(np.uint8))
        large = np.nonzero(stats[1:, cv2.CC_STAT_AREA] > GLINT_MM2 * ppm * ppm)[0] + 1
        if len(large):
            reflections = np.isin(labels, large)
            grow = max(1, round(2 * ppm))
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1,) * 2)
            reflections = cv2.dilate(reflections.astype(np.uint8), kernel) > 0
    area = max(1, int(inside.sum()))
    return Light(
        image=np.clip(evened, 0, 255).astype(np.uint8),
        shadow_edge=edge,
        reflections=reflections,
        shadow_share=float(shadow.sum()) / area,
        clipped_share=float(clipped.sum()) / area,
        gains=gains,
    )
