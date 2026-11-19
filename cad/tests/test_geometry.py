"""The curve's maths (CADMOB-03, the view Kurvmodul): string and sagitta to radius and angle,
and back."""

from __future__ import annotations

import math

import pytest

from cad import geometry
from contracts.cad import Curve, CurveMeasure, EdgeSide


def test_the_views_example_string_and_sagitta_give_radius_and_angle() -> None:
    """Snöret 1035, pilhöjd 68: Uträknat R 2 003 mm · 29,9°, avrundat R 2000 · 30°."""
    found = geometry.from_chord(1035, 68)
    assert round(found.radius) == 2003
    assert round(found.angle, 1) == 29.9
    assert geometry.rounded(found) == geometry.Bend(radius=2000, angle=30)


def test_radius_and_angle_give_the_string_and_sagitta_back() -> None:
    chord, sagitta = geometry.to_chord(2000, 30)
    assert round(chord) == 1035  # Spår 1: rakt avstånd A → B 1 035 mm
    assert round(sagitta) == 68


@pytest.mark.parametrize(("radius", "angle"), [(2000, 30), (645, 19), (3111, 7.5), (900, 90)])
def test_there_and_back_again(radius: float, angle: float) -> None:
    chord, sagitta = geometry.to_chord(radius, angle)
    back = geometry.from_chord(chord, sagitta)
    assert back.radius == pytest.approx(radius, rel=1e-9)
    assert back.angle == pytest.approx(angle, rel=1e-9)


@pytest.mark.parametrize(("chord", "sagitta"), [(1000, 0), (1000, 500), (1000, 600), (0, 10)])
def test_a_sagitta_that_makes_no_arc_is_refused(chord: float, sagitta: float) -> None:
    with pytest.raises(ValueError):
        geometry.from_chord(chord, sagitta)


def test_the_lines_of_the_views_table() -> None:
    """Uträknat: spår 1 R 2000, spår 2 R 1950, Kant 1 ytterkanten R 2200, innerkanten R 1700, with
    their lengths along the line and straight from A to B."""
    curve = Curve(radius=2000, angle=30, width=500)
    rows = {
        "spår 1": geometry.line_radius(curve, 200, 200),
        "spår 2": geometry.line_radius(curve, 200, 250),
        "Kant 1": geometry.line_radius(curve, 200, 0),
        "innerkanten": geometry.line_radius(curve, 200, 500),
    }
    assert rows == {"spår 1": 2000, "spår 2": 1950, "Kant 1": 2200, "innerkanten": 1700}
    lengths = {k: round(geometry.arc_length(r, 30)) for k, r in rows.items()}
    assert lengths == {"spår 1": 1047, "spår 2": 1021, "Kant 1": 1152, "innerkanten": 890}
    chords = {k: round(geometry.to_chord(r, 30)[0]) for k, r in rows.items()}
    assert chords == {"spår 1": 1035, "spår 2": 1009, "Kant 1": 1139, "innerkanten": 880}
    assert round(360 / curve.angle) == 12  # 12 sådana moduler blir en hel cirkel


def test_kant_1_outside_turns_right_and_inside_turns_left_seen_from_gable_a() -> None:
    right = Curve(radius=2000, angle=30, width=500, edge=EdgeSide.OUTER)
    left = Curve(radius=2000, angle=30, width=500, edge=EdgeSide.INNER)
    assert geometry.point_on(right, 200, 200, 0) == pytest.approx((0, 200))
    assert geometry.point_on(left, 200, 200, 0) == pytest.approx((0, 200))
    end_right = geometry.point_on(right, 200, 200, 30)
    end_left = geometry.point_on(left, 200, 200, 30)
    assert end_right[1] > 200 > end_left[1]  # y runs down the drawing, away from Kant 1
    assert math.dist((0, 200), end_right) == pytest.approx(geometry.to_chord(2000, 30)[0])
    assert math.dist((0, 200), end_left) == pytest.approx(geometry.to_chord(2000, 30)[0])


def test_a_rounded_curve_agrees_with_its_measurement_and_a_wrong_one_does_not() -> None:
    measured = CurveMeasure(chord=1035, sagitta=68)
    assert geometry.agrees(Curve(radius=2000, angle=30, width=500, measured=measured))
    assert geometry.agrees(Curve(radius=2003.2, angle=29.94, width=500, measured=measured))
    assert not geometry.agrees(Curve(radius=2500, angle=30, width=500, measured=measured))
    assert not geometry.agrees(Curve(radius=2000, angle=32, width=500, measured=measured))
