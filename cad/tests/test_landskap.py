"""Landskapet's cells (#89 del d1, CAD-04, CAD-24, CAD-33): the colour clustering on a synthetic
measuring image, the track bed from the track plan, painting, erasing and filling, and the
polygons. No database.

The tolerance: inside each true region, 6 mm in from its edge, at least 95 % of the cells get the
region's surface (the synthetic image, cad/tests/landskap_bild.py, has seven surfaces, a track,
uneven light and noise). The track bed is exactly the cells within 23 mm of the track centre.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from cad import geometry, graph, landskap
from cad.tests import landskap_bild
from contracts.cad import (
    EraseLandscape,
    FillLandscape,
    Gable,
    GableEnd,
    LandscapeMethod,
    PaintLandscape,
    Scale,
    Straight,
    Surface,
)

EDGE_MM = 6.0
RIGHT = 0.95


def module() -> tuple[landskap.Grid, landskap.Mask, landskap.Mask, landskap.Floats]:
    shape = Straight(length=landskap_bild.LENGTH, width=landskap_bild.WIDTH)
    track = landskap_bild.TRACK_Y
    built = graph.from_measures(
        shape, [Gable(end=GableEnd.A, tracks=[track]), Gable(end=GableEnd.B, tracks=[track])]
    )
    outline = geometry.outline(shape, track)
    grid = landskap.Grid.over(outline)
    distance = landskap.track_distance(grid, built)
    return grid, landskap.board(grid, outline), landskap.track_bed(distance, Scale.H0), distance


def made(pixels: np.ndarray, matrix: tuple[float, ...] | None = None) -> landskap.Made:
    grid, board, bed, distance = module()
    image = landskap.MeasuringImage(pixels, 0.0, 0.0, landskap_bild.PPM, matrix)
    return landskap.make(grid, board, bed, distance, Scale.H0, image)


def interior(mask: np.ndarray, grid: landskap.Grid) -> np.ndarray:
    """The region's cells at least EDGE_MM inside its edge."""
    size = 2 * round(EDGE_MM * landskap_bild.PPM) + 1
    inner = cv2.erode(mask.astype(np.uint8), np.ones((size, size), np.uint8)).astype(bool)
    gx, gy = grid.centres()
    rows = np.clip((gy * landskap_bild.PPM).astype(int), 0, inner.shape[0] - 1)
    cols = np.clip((gx * landskap_bild.PPM).astype(int), 0, inner.shape[1] - 1)
    found: np.ndarray = inner[rows, cols]
    return found


@pytest.mark.parametrize("seed", [3, 8])
def test_colour_clustering_finds_the_surfaces_within_the_tolerance(seed: int) -> None:
    pixels, regions = landskap_bild.image(seed)
    result = made(pixels)
    grid, board, bed, _ = module()
    assert result.method == LandscapeMethod.COLOUR
    assert result.made_by == "Färgklustring 1"
    surfaces = result.labels & ~np.uint8(landskap.PAINTED)
    for region in regions:
        cells = interior(region.mask, grid) & board & ~bed
        assert cells.sum() > 100, region.surface
        right = float((surfaces[cells] == landskap.CODES[region.surface]).mean())
        assert right >= RIGHT, (region.surface, right)
    # The same image gives the same landscape (the seed is fixed).
    assert np.array_equal(made(pixels).labels, result.labels)


def test_the_track_bed_comes_from_the_track_plan_not_the_colours() -> None:
    grid, board, bed, _ = module()
    _, gy = grid.centres()
    expected = np.abs(gy - landskap_bild.TRACK_Y) <= landskap.BALLAST_HALF_WIDTH[Scale.H0]
    # One cell's rounding at the bed's edge.
    assert ((bed != expected) & (np.abs(np.abs(gy - 140) - 23) > grid.cell)).sum() == 0
    assert landskap.BALLAST_HALF_WIDTH[Scale.N] == pytest.approx(23 * 9 / 16.5)
    pixels, _ = landskap_bild.image()
    labels = made(pixels).labels
    totals = {t.surface: t for t in landskap.totals(labels, board, bed, grid.cell)}
    assert totals[Surface.BALLAST].area >= bed.sum() * grid.cell**2
    # The cells under the bed have the surface around them, for when the track plan moves.
    assert (labels[bed & board] != 0).all()


def test_a_colour_that_is_no_class_is_okand_yta() -> None:
    pixels, _ = landskap_bild.image()
    purple = pixels.copy()
    purple[500:620, 1100:1300] = (200, 40, 190)  # BGR: a violet sign, 100 × 60 mm
    labels = made(purple).labels
    grid, *_ = module()
    cell = grid.to_cells((600.0, 280.0))
    assert labels[int(cell[1]), int(cell[0])] == landskap.CODES[Surface.UNKNOWN]


def test_the_measuring_image_is_read_through_the_photos_frame() -> None:
    """A photo read with gable A at the other end keeps its image; the frame mirrors it into the
    module (PhotoGrid.matrix)."""
    pixels, _ = landskap_bild.image()
    straight = made(pixels).labels
    mirrored = np.ascontiguousarray(pixels[:, ::-1])
    width = (pixels.shape[1] - 1) / landskap_bild.PPM
    flipped = made(mirrored, (-1.0, 0.0, 0.0, 1.0, width, 0.0)).labels
    assert float((straight == flipped).mean()) > 0.99


def test_a_model_goes_first_and_the_clustering_answers_when_it_cannot() -> None:
    grid, board, bed, distance = module()
    pixels, _ = landskap_bild.image()
    image = landskap.MeasuringImage(pixels, 0.0, 0.0, landskap_bild.PPM)

    class Silent:
        method = LandscapeMethod.MODEL
        name = "Egen modell 0"

        def surfaces(self, sample: landskap.Sample) -> landskap.Labels | None:
            return None

    class Water(Silent):
        def surfaces(self, sample: landskap.Sample) -> landskap.Labels | None:
            return np.where(sample.valid, landskap.CODES[Surface.WATER], 0).astype(np.uint8)

    fallback = landskap.make(
        grid, board, bed, distance, Scale.H0, image, [Silent(), landskap.ColourClustering()]
    )
    assert fallback.method == LandscapeMethod.COLOUR
    own = landskap.make(grid, board, bed, distance, Scale.H0, image, [Water()])
    assert own.method == LandscapeMethod.MODEL and own.made_by == "Egen modell 0"
    assert (own.labels[board] == landskap.CODES[Surface.WATER]).all()
    empty = landskap.make(grid, board, bed, distance, Scale.H0, None)
    assert empty.method == LandscapeMethod.HAND and not empty.labels.any()


def test_paint_erase_and_fill() -> None:
    grid, board, bed, _ = module()
    labels = np.zeros(grid.shape, np.uint8)
    # Fill the empty side beyond the track: it stops at the track bed.
    fill = FillLandscape(surface=Surface.GRASS, at=(400.0, 300.0))
    assert landskap.apply(labels, grid, board, bed, fill)
    grass = landskap.CODES[Surface.GRASS] | landskap.PAINTED
    gx, gy = grid.centres()
    assert (labels[(gy > 170) & board] == grass).all()
    assert not labels[gy < 110].any()
    # Paint a pond: a 30 mm brush along a stroke, painted by the owner.
    paint = PaintLandscape(
        surface=Surface.WATER, radius=30, points=[(300.0, 300.0), (500.0, 300.0)]
    )
    assert landskap.apply(labels, grid, board, bed, paint)
    water = landskap.CODES[Surface.WATER] | landskap.PAINTED
    inside = (np.abs(gy - 300) < 28) & (gx > 300) & (gx < 500)
    assert (labels[inside] == water).all()
    assert labels[((gx - 400) ** 2 + (gy - 300) ** 2) < 25].min() == water
    # The same stroke again changes nothing; erasing a shadow leaves nothing there.
    assert not landskap.apply(labels, grid, board, bed, paint)
    erase = EraseLandscape(radius=10, points=[(400.0, 300.0)])
    assert landskap.apply(labels, grid, board, bed, erase)
    assert labels[((gx - 400) ** 2 + (gy - 300) ** 2) < 64].max() == 0
    # A fill of the water bounded by grass replaces only the water.
    before_grass = int((labels == grass).sum())
    landskap.apply(labels, grid, board, bed, FillLandscape(surface=Surface.PATH, at=(320.0, 300.0)))
    assert int((labels == grass).sum()) == before_grass
    assert (labels == water).sum() == 0
    # Not on the track or outside the board.
    for at in ((400.0, 140.0), (900.0, 100.0)):
        with pytest.raises(landskap.LandscapeError):
            landskap.apply(labels, grid, board, bed, FillLandscape(surface=Surface.GRASS, at=at))


def test_the_polygons_are_simplified_with_their_holes_and_the_small_ones_left_out() -> None:
    grid, board, bed, _ = module()
    labels = np.zeros(grid.shape, np.uint8)
    landskap.apply(
        labels, grid, board, bed, FillLandscape(surface=Surface.GRASS, at=(400.0, 300.0))
    )
    landskap.apply(
        labels,
        grid,
        board,
        bed,
        PaintLandscape(surface=Surface.WATER, radius=40, points=[(400.0, 300.0)]),
    )
    landskap.apply(
        labels,
        grid,
        board,
        bed,
        PaintLandscape(surface=Surface.PATH, radius=4, points=[(700.0, 300.0)]),
    )
    found = landskap.areas(labels, grid, board, bed)
    kinds = sorted(a.surface for a in found)
    assert kinds == [Surface.GRASS, Surface.WATER]  # the 8 mm dot of path is under 4 cm²
    grass = next(a for a in found if a.surface == Surface.GRASS)
    water = next(a for a in found if a.surface == Surface.WATER)
    assert len(grass.holes) == 1 and grass.painted
    assert water.area == pytest.approx(math.pi * 40**2, rel=0.05)
    assert len(water.outline) < 40  # simplified, not one point per cell
    totals = {t.surface: t for t in landskap.totals(labels, board, bed, grid.cell)}
    assert totals[Surface.WATER].area == pytest.approx(math.pi * 40**2, rel=0.05)
    # The side before the track is not painted: nothing there.
    empty = float((board & ~bed & (labels == 0)).sum() / board.sum())
    assert empty == pytest.approx(117 / 400, abs=0.01)
    assert sum(t.share for t in totals.values()) == pytest.approx(1 - empty, abs=0.001)
    rings = landskap.bed_rings(grid, board, bed)
    assert len(rings) == 1 and min(p[1] for p in rings[0]) == pytest.approx(118, abs=2)


def test_the_cells_keep_their_place_when_the_board_grows() -> None:
    grid, board, bed, _ = module()
    labels = np.zeros(grid.shape, np.uint8)
    landskap.apply(
        labels,
        grid,
        board,
        bed,
        PaintLandscape(surface=Surface.WATER, radius=20, points=[(100.0, 300.0)]),
    )
    larger = landskap.Grid.over(geometry.outline(Straight(length=1000, width=400), 140))
    moved = landskap.regrid(labels, grid, larger)
    assert moved.shape == (200, 500)
    assert np.array_equal(moved[:, :400], labels) and not moved[:, 400:].any()
    assert landskap.decode(landskap.encode(moved), larger).tobytes() == moved.tobytes()


def test_a_double_tracks_ballast_lies_between_its_tracks_too() -> None:
    """MMM's double track, 140 and 197 mm from Kant 1: the 11 mm between the beds is ballast."""
    shape = Straight(length=800, width=400)
    gables = [Gable(end=GableEnd.A, tracks=[140, 197]), Gable(end=GableEnd.B, tracks=[140, 197])]
    outline = geometry.outline(shape, 140)
    grid = landskap.Grid.over(outline)
    distance = landskap.track_distance(grid, graph.from_measures(shape, gables))
    bed = landskap.track_bed(distance, Scale.H0, grid.cell)
    _, gy = grid.centres()
    assert bed[(gy > 118) & (gy < 219)].all()
    assert not bed[(gy < 114) | (gy > 223)].any()
