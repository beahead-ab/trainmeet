"""Utjämning (CAD-03): noisy lines become LINE and ARC within the level's deviation, tangent
everywhere, with the median and largest deviation reported."""

from __future__ import annotations

import math
import random

import pytest

from cad import curves, smoothing
from cad.curves import Arc, Line
from contracts.cad import Scale, Smoothing
from contracts.station_model import Point


def noisy_arc(radius: float, degrees: float, noise: float, seed: int = 1) -> list[Point]:
    """An arc from (0, 100) turning right, a point every 8 mm, each off by up to noise mm."""
    rng = random.Random(seed)
    count = int(radius * math.radians(degrees) / 8)
    points = []
    for k in range(count + 1):
        a = math.radians(degrees) * k / count
        r = radius + (rng.uniform(-noise, noise) if 0 < k < count else 0)
        points.append((r * math.sin(a), 100 + radius - r * math.cos(a)))
    return points


def noisy_s(noise: float, seed: int = 2) -> list[Point]:
    """Straight 400 mm, then a right arc R 600 over 30°: a line module's curve, hand-drawn."""
    rng = random.Random(seed)
    points = [(float(x), 200 + (rng.uniform(-noise, noise) if x else 0)) for x in range(0, 400, 10)]
    for k in range(1, 61):
        a = math.radians(30) * k / 60
        wobble = rng.uniform(-noise, noise) if k < 60 else 0
        points.append((400 + 600 * math.sin(a), 800 - 600 * math.cos(a) + wobble))
    return points


def tangent_everywhere(segs: list[curves.Seg]) -> None:
    for _, jump in curves.joints(segs):
        assert jump < 1e-6


def test_the_levels_and_their_numbers() -> None:
    found = {x.level: x for x in smoothing.levels(Scale.H0)}
    assert (found[Smoothing.NORMAL].min_radius, found[Smoothing.NORMAL].max_deviation) == (400, 9)
    assert (found[Smoothing.LIGHT].min_radius, found[Smoothing.LIGHT].max_deviation) == (300, 4.1)
    assert (found[Smoothing.STRONG].min_radius, found[Smoothing.STRONG].max_deviation) == (
        600,
        16.5,
    )
    assert found[Smoothing.OFF].min_radius is None
    n = {x.level: x for x in smoothing.levels(Scale.N)}
    assert n[Smoothing.NORMAL].min_radius == 220 and n[Smoothing.NORMAL].max_deviation == 4.9


@pytest.mark.parametrize("level", [Smoothing.NORMAL, Smoothing.STRONG])
def test_a_noisy_arc_becomes_one_clean_arc(level: Smoothing) -> None:
    points = noisy_arc(800, 60, noise=3)
    segs = smoothing.smooth(points, level, Scale.H0)
    assert len(segs) <= 2 and all(isinstance(s, Arc) for s in segs)
    assert all(abs(s.radius - 800) < 60 for s in segs if isinstance(s, Arc))
    tangent_everywhere(segs)
    assert segs[0].start == points[0] and segs[-1].end == pytest.approx(points[-1])
    found = smoothing.deviation(points, segs)
    numbers = smoothing.level_of(level, Scale.H0)
    assert numbers is not None
    assert found.max <= numbers.max_deviation + 1
    assert found.median < 3.5 and found.count == len(points)


def test_a_light_level_follows_a_good_line_closely() -> None:
    points = noisy_arc(500, 45, noise=1)
    segs = smoothing.smooth(points, Smoothing.LIGHT, Scale.H0)
    found = smoothing.deviation(points, segs)
    assert len(segs) <= 3 and found.max <= 4.1 + 0.5 and found.median <= 1.5
    tangent_everywhere(segs)


def test_a_straight_then_a_curve_keeps_its_parts_and_its_minimum_radius() -> None:
    points = noisy_s(noise=2)
    segs = smoothing.smooth(points, Smoothing.NORMAL, Scale.H0)
    assert 1 < len(segs) <= 4
    assert all(s.radius >= 400 - 1 for s in segs if isinstance(s, Arc))
    tangent_everywhere(segs[:-1])
    found = smoothing.deviation(points, segs)
    assert found.max <= 9 + 1


def test_off_keeps_the_line_as_drawn_and_a_start_heading_holds() -> None:
    points = noisy_s(noise=2)
    off = smoothing.smooth(points, Smoothing.OFF, Scale.H0)
    assert len(off) == len(points) - 1 and all(isinstance(s, Line) for s in off)
    assert smoothing.deviation(points, off).max == 0
    held = smoothing.smooth(points, Smoothing.NORMAL, Scale.H0, start_heading=0.0)
    assert curves.start_heading(held[0]) == pytest.approx(0, abs=1e-9)
    with pytest.raises(ValueError, match="för få punkter"):
        smoothing.smooth([(0, 0), (0, 0)], Smoothing.NORMAL, Scale.H0)


def test_the_same_line_always_gives_the_same_result() -> None:
    points = noisy_arc(900, 40, noise=2, seed=7)
    assert smoothing.smooth(points, Smoothing.NORMAL, Scale.H0) == smoothing.smooth(
        points, Smoothing.NORMAL, Scale.H0
    )
