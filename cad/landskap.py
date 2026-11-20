"""Landskapet (#89 del d1, CAD-04, CAD-24, CAD-33): the module's surfaces, from its measuring image.

The landscape is a grid of cells over the module, CELL mm on a side (larger only for a very
large module, so that no side has more than MAX_SIDE cells), in the module's own millimetres
(x from gable A along Kant 1, y away from Kant 1). Each cell holds one byte: its surface's code
(CODES, 0 for nothing), with PAINTED set where the owner painted it. Stored as a PNG with the
module version (cad/landscapes.py).

Making it (bildkedjan step 14, lärdomarna "Förenklat landskap"):
1. The measuring image after step 8 (the light already evened out) is sampled into the cells,
   through the photo's frame when the photo was read with another Kant 1 or gable A. Each cell
   gets its colour in Lab and its texture: how much the lightness varies within TEXTURE_MM.
2. The track bed, BALLAST_HALF_WIDTH on each side of every track centre in the track plan, is
   ballast from the geometry: it never comes from the colours, and the tracks are always drawn
   from the geometry (step 14, Polygoner).
3. A surface model gives every other cell on the board its surface. TrainMeet's own model on
   CAD's server goes first when there is one (CAD8); none is trained yet, since its training
   data is approved modules whose owners said yes (CAD7). Until then ColourClustering does it:
   k-means of the cells' colour and texture into CLUSTERS groups, each group named by the
   nearest of the classes' colours (PROTOTYPES), or Okänd yta when none lies within
   UNKNOWN_DISTANCE. The position filter then keeps ballast to near the tracks: a grey surface
   farther than NEAR_TRACK_MM from every track is a platform when light and ground when dark.
4. Cleaned: a majority filter over MAJORITY_MM, and every patch smaller than MIN_AREA_MM2 given
   to the surfaces around it; so are the cells the photo does not cover and the track bed's own
   cells, so that the board has a surface under the track if the track plan moves.
5. The surfaces become polygons, simplified by SIMPLIFY_MM, without the patches under the
   minimum area.

The owner paints (a surface along a stroke), erases (nothing along a stroke, such as a shadow
classed as a bush) and fills (the connected area under a point, bounded by other surfaces, the
track bed and the board's edge). A module without a photo gets an empty landscape to paint.

Everything here is code on CAD's own server: free (CAD-18), and the same image and track plan
give the same landscape (the clustering's seed is fixed).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

import cv2
import numpy as np
from numpy.typing import NDArray

from cad import curves
from cad.switches import GAUGE
from contracts.cad import (
    SURFACE_COLOURS,
    SURFACE_NAMES,
    EraseLandscape,
    FillLandscape,
    LandscapeArea,
    LandscapeGrid,
    LandscapeMethod,
    LandscapeOp,
    PaintLandscape,
    Scale,
    Surface,
    SurfaceInfo,
    SurfaceTotal,
    TrackGraph,
)
from contracts.station_model import Point

Labels = NDArray[np.uint8]
Mask = NDArray[np.bool_]
Floats = NDArray[np.float32]

CELL: Final = 2.0
"""A cell's side, mm: half the measuring image's 2 px/mm (bildkedjan step 8)."""
MAX_SIDE: Final = 1600
"""The most cells on a side; a larger module gets larger cells."""
PAINTED: Final = 0x80
"""Set in a cell the owner painted."""
CODES: Final = {surface: number for number, surface in enumerate(Surface, start=1)}
SURFACES: Final = {number: surface for surface, number in CODES.items()}

BALLAST_HALF_WIDTH: Final = {scale: 23.0 * GAUGE[scale] / GAUGE[Scale.H0] for scale in Scale}
"""Half the track bed, mm: 46 mm of ballast in H0, as the synthetic photos draw it
(cad/bildkedjan/syntetisk.py, BALLAST); N and 0 by the gauge."""
BED_GAP_MM: Final = 16.0
"""A gap between two track beds narrower than this, mm in H0, is ballast too: double track at
57 mm (MMM) leaves 11 mm between the beds."""
NEAR_TRACK_MM: Final = 30.0
"""How far beyond the track bed a grey surface may lie and still be ballast (lägesfilter)."""
TEXTURE_MM: Final = 6.0
CLUSTERS: Final = 16
SEED: Final = 89
FIT_SAMPLES: Final = 20_000
UNKNOWN_DISTANCE: Final = 42.0
"""A group farther than this from every class's colour, in Lab (OpenCV's 8-bit scale), is Okänd
yta."""
LIGHT_GREY: Final = 172.0
"""A grey surface away from the tracks lighter than this (L, 8-bit) is a platform."""
MAJORITY_MM: Final = 10.0
MIN_AREA_MM2: Final = 400.0
"""Minsta yta (step 14, Polygoner): 2 × 2 cm."""
SIMPLIFY_MM: Final = 2.0
COLOUR_VERSION: Final = "Färgklustring 1"


# --- The grid ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Grid:
    """Cell (0, 0)'s corner at (x0, y0) mm, cell mm on a side."""

    x0: float
    y0: float
    cell: float
    width: int
    height: int

    @classmethod
    def over(cls, outline: Sequence[Point]) -> Grid:
        """The grid over a board's outline."""
        xs = [p[0] for p in outline]
        ys = [p[1] for p in outline]
        x0, y0 = math.floor(min(xs)), math.floor(min(ys))
        span = max(max(xs) - x0, max(ys) - y0)
        cell = max(CELL, math.ceil(span / MAX_SIDE))
        width = max(1, math.ceil((max(xs) - x0) / cell))
        height = max(1, math.ceil((max(ys) - y0) / cell))
        return cls(float(x0), float(y0), float(cell), width, height)

    @classmethod
    def of(cls, found: LandscapeGrid) -> Grid:
        return cls(found.x0, found.y0, found.cell, found.width, found.height)

    def contract(self) -> LandscapeGrid:
        return LandscapeGrid(
            x0=self.x0, y0=self.y0, cell=self.cell, width=self.width, height=self.height
        )

    @property
    def shape(self) -> tuple[int, int]:
        return (self.height, self.width)

    def centres(self) -> tuple[Floats, Floats]:
        """Every cell's centre, mm."""
        xs = self.x0 + (np.arange(self.width, dtype=np.float32) + 0.5) * self.cell
        ys = self.y0 + (np.arange(self.height, dtype=np.float32) + 0.5) * self.cell
        gx, gy = np.meshgrid(xs, ys)
        return gx.astype(np.float32), gy.astype(np.float32)

    def to_cells(self, p: Point) -> tuple[float, float]:
        """A point in mm in cells, the cell's corner at whole numbers."""
        return ((p[0] - self.x0) / self.cell, (p[1] - self.y0) / self.cell)

    def to_mm(self, col: float, row: float) -> Point:
        """A cell's centre (col, row) in mm."""
        return (
            round(self.x0 + (col + 0.5) * self.cell, 2),
            round(self.y0 + (row + 0.5) * self.cell, 2),
        )


def _fixed(points: Sequence[tuple[float, float]]) -> NDArray[np.int32]:
    """Cell coordinates for OpenCV's drawing with 4 bits of fraction, at the cells' centres."""
    return np.array([[round((x - 0.5) * 16), round((y - 0.5) * 16)] for x, y in points], np.int32)


def board(grid: Grid, outline: Sequence[Point]) -> Mask:
    """The cells whose centre lies on the board."""
    found = np.zeros(grid.shape, np.uint8)
    cv2.fillPoly(found, [_fixed([grid.to_cells(p) for p in outline])], 1, cv2.LINE_8, 4)
    return found.astype(bool)


def track_distance(grid: Grid, graph: TrackGraph) -> Floats:
    """How far each cell's centre lies from the nearest track centre, mm (a large number without
    tracks)."""
    lines = np.full(grid.shape, 255, np.uint8)
    drawn = False
    for piece in graph.pieces:
        segs = [curves.from_segment(s) for s in piece.segments]
        points = curves.sample_path(segs, max(grid.cell / 2, 0.5))
        if len(points) < 2:
            continue
        cv2.polylines(lines, [_fixed([grid.to_cells(p) for p in points])], False, 0, 1, 8, 4)
        drawn = True
    if not drawn:
        return np.full(grid.shape, 1e6, np.float32)
    found = cv2.distanceTransform(lines, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    return np.asarray(found * grid.cell, np.float32)


def track_bed(distance: Floats, scale: Scale, cell: float = CELL) -> Mask:
    """The ballast under the tracks, from the track plan: BALLAST_HALF_WIDTH on each side of
    every track centre, and the narrow gaps between beds closed, as the ballast of a double
    track lies between its tracks too (BED_GAP_MM)."""
    near = (distance <= BALLAST_HALF_WIDTH[scale]).astype(np.uint8)
    size = _odd(BED_GAP_MM * GAUGE[scale] / GAUGE[Scale.H0] / cell)
    disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    closed = cv2.morphologyEx(near, cv2.MORPH_CLOSE, disc, borderType=cv2.BORDER_REPLICATE)
    found: Mask = closed.astype(bool)
    return found


def regrid(labels: Labels, old: Grid, new: Grid) -> Labels:
    """The cells of a landscape on another grid: the board's measures changed. Cells the old one
    did not cover are empty."""
    if old == new:
        return labels.copy()
    gx, gy = new.centres()
    cols = np.floor((gx - old.x0) / old.cell).astype(np.int64)
    rows = np.floor((gy - old.y0) / old.cell).astype(np.int64)
    inside = (cols >= 0) & (cols < old.width) & (rows >= 0) & (rows < old.height)
    found = np.zeros(new.shape, np.uint8)
    found[inside] = labels[rows[inside], cols[inside]]
    return found


def encode(labels: Labels) -> bytes:
    ok, data = cv2.imencode(".png", labels, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    if not ok:
        raise ValueError("Landskapet gick inte att spara som PNG.")
    return bytes(data.tobytes())


def decode(data: bytes, grid: Grid) -> Labels:
    found = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if found is None or found.shape != grid.shape or found.dtype != np.uint8:
        raise ValueError("Landskapets celler stämmer inte med rutnätet.")
    return np.ascontiguousarray(found)


# --- The measuring image in the cells ------------------------------------------------------


@dataclass(frozen=True)
class MeasuringImage:
    """The measuring image: pixel (0, 0)'s centre at (x0, y0) mm, ppm px per mm. matrix, SVG's
    (a, b, c, d, e, f), takes the mm it was measured in to the module's (PhotoGrid.matrix)."""

    pixels: NDArray[np.uint8]
    x0: float
    y0: float
    ppm: float
    matrix: tuple[float, ...] | None = None


@dataclass(frozen=True)
class Sample:
    """What a surface model gets: the measuring image in the landscape's cells."""

    bgr: NDArray[np.uint8]
    lab: Floats
    """OpenCV's 8-bit Lab: L 0–255, a and b around 128."""
    texture: Floats
    """The lightness's standard deviation within TEXTURE_MM."""
    valid: Mask
    """On the board, in the photo and outside the track bed: the cells to give a surface."""
    distance: Floats
    """mm to the nearest track centre."""
    bed_half_width: float
    cell: float


def _odd(n: float) -> int:
    k = max(3, round(n))
    return k if k % 2 else k + 1


def sample(
    image: MeasuringImage, grid: Grid, on_board: Mask, bed: Mask, distance: Floats, scale: Scale
) -> Sample:
    """The measuring image's colour and texture in each cell."""
    pixels = image.pixels
    if pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("Mätbilden ska ha tre färger.")
    gx, gy = grid.centres()
    mx: NDArray[Any] = gx
    my: NDArray[Any] = gy
    if image.matrix is not None:
        a, b, c, d, e, f = image.matrix
        det = a * d - b * c
        if abs(det) < 1e-12:
            raise ValueError("Fotots ram går inte att vända.")
        px, py = gx - e, gy - f
        mx = (d * px - c * py) / det
        my = (-b * px + a * py) / det
    map_x = ((mx - image.x0) * image.ppm).astype(np.float32)
    map_y = ((my - image.y0) * image.ppm).astype(np.float32)
    h, w = pixels.shape[:2]
    inside = (map_x >= -0.5) & (map_x <= w - 0.5) & (map_y >= -0.5) & (map_y <= h - 0.5)
    # The cell's own colour, without the sleepers' and the grass's finest grain.
    sigma = max(0.5, grid.cell * image.ppm / 2)
    smooth = cv2.GaussianBlur(pixels, (0, 0), sigma)
    lab_full = cv2.cvtColor(smooth, cv2.COLOR_BGR2LAB).astype(np.float32)
    lightness = cv2.cvtColor(pixels, cv2.COLOR_BGR2LAB)[..., 0].astype(np.float32)
    k = _odd(TEXTURE_MM * image.ppm)
    mean = cv2.boxFilter(lightness, -1, (k, k))
    square = cv2.boxFilter(lightness * lightness, -1, (k, k))
    texture_full = np.sqrt(np.maximum(square - mean * mean, 0)).astype(np.float32)

    def at(source: NDArray[Any]) -> NDArray[Any]:
        found: NDArray[Any] = cv2.remap(
            source, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
        )
        return found

    valid = on_board & inside & ~bed
    return Sample(
        bgr=at(smooth),
        lab=at(lab_full),
        texture=at(texture_full),
        valid=valid,
        distance=distance,
        bed_half_width=BALLAST_HALF_WIDTH[scale],
        cell=grid.cell,
    )


# --- Surface models ------------------------------------------------------------------------


class SurfaceModel(Protocol):
    """A way to find the surfaces in a measuring image (CAD8). TrainMeet's own model goes first in
    MODELS when one is trained: a segmentation model on CAD's own server, as Catalog runs its
    background removal (an ONNX model on the CPU), given Sample.bgr. Nothing is sent elsewhere,
    and it costs nothing. ColourClustering answers when no model does."""

    method: LandscapeMethod
    name: str

    def surfaces(self, sample: Sample) -> Labels | None:
        """The surface's code (CODES) in each valid cell, 0 where it does not know; or None when
        it cannot answer, and the next model is asked."""
        ...


def _lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    pixel = np.array([[[rgb[2], rgb[1], rgb[0]]]], np.uint8)
    found = cv2.cvtColor(pixel, cv2.COLOR_BGR2LAB)[0, 0].astype(float)
    return (float(found[0]), float(found[1]), float(found[2]))


@dataclass(frozen=True)
class Prototype:
    """A class's colour, sRGB, and how grainy it usually is (the texture, 8-bit L)."""

    surface: Surface
    rgb: tuple[int, int, int]
    texture: float

    @property
    def lab(self) -> tuple[float, float, float]:
        return _lab(self.rgb)


PROTOTYPES: Final = (
    Prototype(Surface.GRASS, (72, 104, 62), 6),
    Prototype(Surface.GRASS, (104, 134, 72), 6),
    Prototype(Surface.GRASS, (134, 150, 86), 6),
    Prototype(Surface.TREES, (38, 62, 34), 14),
    Prototype(Surface.BALLAST, (168, 166, 160), 12),
    Prototype(Surface.BALLAST, (138, 136, 132), 12),
    Prototype(Surface.GROUND, (122, 100, 76), 6),
    Prototype(Surface.GROUND, (84, 84, 86), 3),
    Prototype(Surface.GROUND, (112, 106, 100), 5),
    Prototype(Surface.PATH, (196, 172, 128), 5),
    Prototype(Surface.PLATFORM, (208, 206, 200), 3),
    Prototype(Surface.PLATFORM, (188, 182, 172), 3),
    Prototype(Surface.WATER, (58, 98, 150), 3),
    Prototype(Surface.WATER, (72, 120, 140), 3),
    Prototype(Surface.BUILDING, (152, 62, 52), 4),
    Prototype(Surface.BUILDING, (178, 92, 70), 4),
)
"""The classes' colours on a model railway (lärdomarna: muted). A model's own colours are
learned by the clustering; these only name the groups."""

LIGHTNESS_WEIGHT: Final = 0.6
"""Lightness counts less than hue: the light varies across a photo even after step 8."""
TEXTURE_WEIGHT: Final = 0.8
CLUSTER_LIGHTNESS: Final = 1.0
"""In the clustering itself the lightness counts in full: a bush is a darker green than grass."""


def _features(lab: Floats, texture: Floats) -> Floats:
    found: Floats = np.stack(
        [lab[..., 0] * CLUSTER_LIGHTNESS, lab[..., 1], lab[..., 2], texture * TEXTURE_WEIGHT],
        axis=-1,
    ).astype(np.float32)
    return found


def name_of(lab: Sequence[float], texture: float) -> Surface:
    """The class whose colour lies nearest, or Okänd yta."""
    best, distance = Surface.UNKNOWN, UNKNOWN_DISTANCE
    for proto in PROTOTYPES:
        pl = proto.lab
        d = math.sqrt(
            ((lab[0] - pl[0]) * LIGHTNESS_WEIGHT) ** 2
            + (lab[1] - pl[1]) ** 2
            + (lab[2] - pl[2]) ** 2
            + ((texture - proto.texture) * TEXTURE_WEIGHT) ** 2
        )
        if d < distance:
            best, distance = proto.surface, d
    return best


class ColourClustering:
    """Färgklustring (CAD-24): the fallback, and for now the only one."""

    method = LandscapeMethod.COLOUR
    name = COLOUR_VERSION

    def surfaces(self, sample: Sample) -> Labels | None:
        cells = np.argwhere(sample.valid)
        found = np.zeros(sample.valid.shape, np.uint8)
        if len(cells) == 0:
            return found
        features = _features(sample.lab, sample.texture)[sample.valid]
        k = min(CLUSTERS, len(features))
        rng = np.random.default_rng(SEED)
        fit = features[rng.choice(len(features), min(FIT_SAMPLES, len(features)), replace=False)]
        cv2.setRNGSeed(SEED)
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 40, 0.2)
        _, _, centres = cv2.kmeans(
            np.ascontiguousarray(fit), k, None, criteria, 3, cv2.KMEANS_PP_CENTERS
        )
        # Every cell to its nearest group, in parts so that a large module stays small in memory.
        group = np.empty(len(features), np.int64)
        for start in range(0, len(features), 200_000):
            part = features[start : start + 200_000]
            d = ((part[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
            group[start : start + 200_000] = d.argmin(axis=1)
        names = np.array(
            [
                CODES[
                    name_of(
                        (c[0] / CLUSTER_LIGHTNESS, c[1], c[2]),
                        float(c[3] / TEXTURE_WEIGHT),
                    )
                ]
                for c in centres
            ],
            np.uint8,
        )
        values = names[group]
        # Lägesfilter: grey is ballast only near the tracks; farther away it is a platform when
        # light and ground when dark.
        far = sample.distance[sample.valid] > sample.bed_half_width + NEAR_TRACK_MM
        grey = (values == CODES[Surface.BALLAST]) & far
        light = sample.lab[..., 0][sample.valid] >= LIGHT_GREY
        values[grey & light] = CODES[Surface.PLATFORM]
        values[grey & ~light] = CODES[Surface.GROUND]
        found[sample.valid] = values
        return found


MODELS: tuple[SurfaceModel, ...] = (ColourClustering(),)


# --- Cleaning ----------------------------------------------------------------------------


def _majority(labels: Labels, where: Mask, size: int) -> Labels:
    """Each cell in where gets the surface most of its neighbours within size cells have."""
    codes = [int(c) for c in np.unique(labels[where]) if c]
    if len(codes) < 2:
        return labels
    votes = np.stack(
        [cv2.boxFilter(((labels == c) & where).astype(np.float32), -1, (size, size)) for c in codes]
    )
    found = labels.copy()
    winner = np.array(codes, np.uint8)[votes.argmax(axis=0)]
    found[where] = winner[where]
    return found


def _fill_from_nearest(labels: Labels, empty: Mask, sources: Mask) -> Labels:
    """The empty cells get the surface of the nearest source cell."""
    if not empty.any() or not sources.any():
        return labels
    src = np.where(sources, 0, 1).astype(np.uint8)
    _, nearest = cv2.distanceTransformWithLabels(
        src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
    )
    zeros = np.argwhere(sources)
    # The labels number the source cells in raster order, from 1.
    found = labels.copy()
    picked = zeros[nearest[empty] - 1]
    found[empty] = labels[picked[:, 0], picked[:, 1]]
    return found


def clean(found: Labels, on_board: Mask, cell: float) -> Labels:
    """A majority filter, patches under MIN_AREA_MM2 to the surfaces around them, and every cell
    on the board without a surface (outside the photo, under the track bed) from the nearest."""
    labels = found.copy()
    labels[~on_board] = 0
    known = on_board & (labels > 0)
    labels = _majority(labels, known, _odd(MAJORITY_MM / cell))
    smallest = MIN_AREA_MM2 / (cell * cell)
    small = np.zeros(labels.shape, bool)
    for code in [int(c) for c in np.unique(labels[known]) if c]:
        _, parts, stats, _ = cv2.connectedComponentsWithStats(
            (labels == code).astype(np.uint8), connectivity=8
        )
        tiny = np.flatnonzero(stats[1:, cv2.CC_STAT_AREA] < smallest) + 1
        if len(tiny):
            small |= np.isin(parts, tiny)
    kept = known & ~small
    if not kept.any():
        kept = known
    return _fill_from_nearest(labels, on_board & ~kept, kept)


# --- Making it -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Made:
    labels: Labels
    method: LandscapeMethod
    made_by: str


def make(
    grid: Grid,
    on_board: Mask,
    bed: Mask,
    distance: Floats,
    scale: Scale,
    image: MeasuringImage | None,
    models: Sequence[SurfaceModel] = MODELS,
) -> Made:
    """The landscape from the measuring image; empty without one."""
    if image is None:
        return Made(np.zeros(grid.shape, np.uint8), LandscapeMethod.HAND, "Målat för hand")
    found = sample(image, grid, on_board, bed, distance, scale)
    for model in models:
        answer = model.surfaces(found)
        if answer is not None:
            return Made(clean(answer, on_board, grid.cell), model.method, model.name)
    raise ValueError("Ingen modell gav landskapet.")


# --- Painting ------------------------------------------------------------------------------


class LandscapeError(ValueError):
    """An operation that cannot be done, in Swedish."""


def stroke(grid: Grid, points: Sequence[Point], radius: float) -> Mask:
    """The cells a brush of radius mm touches along the points."""
    mask = np.zeros(grid.shape, np.uint8)
    cells = [grid.to_cells(p) for p in points]
    r = max(0.5, radius / grid.cell)
    for x, y in cells:
        cv2.circle(
            mask,
            (round((x - 0.5) * 16), round((y - 0.5) * 16)),
            round(r * 16),
            1,
            -1,
            cv2.LINE_8,
            4,
        )
    if len(cells) > 1:
        cv2.polylines(mask, [_fixed(cells)], False, 1, max(1, round(2 * r)), cv2.LINE_8, 4)
    return mask.astype(bool)


def apply(labels: Labels, grid: Grid, on_board: Mask, bed: Mask, op: LandscapeOp) -> bool:
    """One operation on the cells, in place. Did it change anything?"""
    if isinstance(op, PaintLandscape | EraseLandscape):
        where = stroke(grid, op.points, op.radius) & on_board
        value = CODES[op.surface] | PAINTED if isinstance(op, PaintLandscape) else 0
        changed = bool((labels[where] != value).any())
        labels[where] = value
        return changed
    assert isinstance(op, FillLandscape)
    col, row = grid.to_cells(op.at)
    c, r = math.floor(col), math.floor(row)
    if not (0 <= c < grid.width and 0 <= r < grid.height) or not on_board[r, c] or bed[r, c]:
        raise LandscapeError("Fyll i en yta på modulen, inte på spåret eller utanför.")
    blocked = np.ones((grid.height + 2, grid.width + 2), np.uint8)
    blocked[1:-1, 1:-1] = np.where(on_board & ~bed, 0, 1)
    surface = (labels & ~np.uint8(PAINTED)).astype(np.uint8)
    flags = 4 | (2 << 8) | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE
    cv2.floodFill(surface, blocked, (c, r), 0, 0, 0, flags)
    region = blocked[1:-1, 1:-1] == 2
    value = CODES[op.surface] | PAINTED
    changed = bool((labels[region] != value).any())
    labels[region] = value
    return changed


# --- What the web app and the exports get ---------------------------------------------------


def surface_infos() -> list[SurfaceInfo]:
    return [
        SurfaceInfo(surface=s, name=SURFACE_NAMES[s], colour=SURFACE_COLOURS[s]) for s in Surface
    ]


def _ring(grid: Grid, contour: NDArray[Any]) -> list[Point]:
    simple = cv2.approxPolyDP(contour, SIMPLIFY_MM / grid.cell, True)
    return [grid.to_mm(float(p[0][0]), float(p[0][1])) for p in simple]


def _hole_area(contour: NDArray[Any]) -> float:
    """A hole's own cells, about: its contour runs through the cells around it."""
    return float(cv2.contourArea(contour) - cv2.arcLength(contour, True) / 2 + 1)


def _rings(grid: Grid, mask: Mask) -> list[tuple[list[Point], list[list[Point]], float]]:
    """The mask's polygons with their holes and their area in mm² (the cells' own), the small
    ones left out."""
    as_bytes = mask.astype(np.uint8)
    contours, hierarchy = cv2.findContours(as_bytes, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    _, parts, stats, _ = cv2.connectedComponentsWithStats(as_bytes, connectivity=8)
    found: list[tuple[list[Point], list[list[Point]], float]] = []
    tree = hierarchy[0]
    for i, contour in enumerate(contours):
        if tree[i][3] != -1:
            continue
        x, y = contour[0][0]
        area = float(stats[parts[y, x], cv2.CC_STAT_AREA]) * grid.cell * grid.cell
        if area < MIN_AREA_MM2:
            continue
        outline = _ring(grid, contour)
        if len(outline) < 3:
            continue
        # A hole for a patch too small to be drawn is no hole: the patch is drawn as around it.
        holes = [
            _ring(grid, contours[j])
            for j in range(len(contours))
            if tree[j][3] == i and _hole_area(contours[j]) * grid.cell**2 >= MIN_AREA_MM2
        ]
        found.append((outline, [h for h in holes if len(h) >= 3], round(area, 1)))
    return found


def areas(labels: Labels, grid: Grid, on_board: Mask, bed: Mask) -> list[LandscapeArea]:
    """The surfaces as polygons, outside the track bed, the owner's painted ones apart."""
    shown = np.where(on_board & ~bed, labels, 0).astype(np.uint8)
    found: list[LandscapeArea] = []
    for value in [int(v) for v in np.unique(shown) if v]:
        surface = SURFACES.get(value & ~PAINTED)
        if surface is None:
            continue
        for outline, holes, area in _rings(grid, shown == value):
            found.append(
                LandscapeArea(
                    surface=surface,
                    outline=outline,
                    holes=holes,
                    area=area,
                    painted=bool(value & PAINTED),
                )
            )
    return found


def bed_rings(grid: Grid, on_board: Mask, bed: Mask) -> list[list[Point]]:
    """The track bed's outlines and holes, for a fill with the even-odd rule."""
    rings: list[list[Point]] = []
    for outline, holes, _ in _rings(grid, on_board & bed):
        rings.append(outline)
        rings.extend(holes)
    return rings


def totals(labels: Labels, on_board: Mask, bed: Mask, cell: float) -> list[SurfaceTotal]:
    """How much of the board each surface covers, the track bed as ballast."""
    count = int(on_board.sum())
    if count == 0:
        return []
    surface = np.where(on_board & bed, CODES[Surface.BALLAST], labels & ~np.uint8(PAINTED))
    surface = np.where(on_board, surface, 0)
    found: list[SurfaceTotal] = []
    for s in Surface:
        n = int((surface == CODES[s]).sum())
        if n:
            found.append(
                SurfaceTotal(surface=s, area=round(n * cell * cell, 1), share=round(n / count, 4))
            )
    return sorted(found, key=lambda t: -t.area)
