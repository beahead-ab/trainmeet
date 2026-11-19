"""The module's geometry from its measures: code measures, nothing is guessed.

A curve module is measured with a string between track 1's centre at gable A and gable B and
the sagitta from its middle (CADMOB-03, the view Kurvmodul):

    R = (c² + 4s²) / 8s        θ = 2·asin(c / 2R)

and back, from the radius and the angle, c = 2R·sin(θ/2) and s = R·(1 - cos(θ/2)). The rounded
values the view offers are R to 10 mm and θ to half a degree; "Ångra avrundning" keeps the
measured ones.

The module's own coordinates are the station model's: x from gable A along Kant 1, y away from
Kant 1, in mm, y down the drawing. A straight module's track at d mm from Kant 1 runs from
(0, d) to (L, d). A curve with Kant 1 as the outer edge turns right seen from gable A: its centre
lies at (0, R₁) under Kant 1, where R₁ = R + d₁ is Kant 1's radius and d₁ track 1's distance from
Kant 1; a line d mm from Kant 1 has the radius R₁ - d. With Kant 1 as the inner edge the curve
turns left, the centre lies at (0, -R₁) above it, R₁ = R - d₁, and the line's radius is R₁ + d.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from contracts.cad import Curve, EdgeSide, Shape, Straight, Trapezoid
from contracts.station_model import Point

RADIUS_STEP = 10.0
"""The rounded radius, in mm."""
ANGLE_STEP = 0.5
"""The rounded angle, in degrees."""
RADIUS_TOLERANCE = 0.01
"""A curve's radius may differ by 1 % from the one its measurement gives, so that it can be
rounded."""
ANGLE_TOLERANCE = 0.5
"""And its angle by half a degree."""


@dataclass(frozen=True)
class Bend:
    """A curve's radius (track 1) and angle, in mm and degrees."""

    radius: float
    angle: float


def from_chord(chord: float, sagitta: float) -> Bend:
    """The radius and angle of track 1 from the string (chord) and its sagitta."""
    if chord <= 0 or sagitta <= 0 or sagitta >= chord / 2:
        raise ValueError("Pilhöjden ska vara större än noll och mindre än halva snöret.")
    radius = (chord * chord + 4 * sagitta * sagitta) / (8 * sagitta)
    angle = math.degrees(2 * math.asin(min(1.0, chord / (2 * radius))))
    return Bend(radius=radius, angle=angle)


def to_chord(radius: float, angle: float) -> tuple[float, float]:
    """The string and sagitta of an arc with the radius and angle: the other way."""
    half = math.radians(angle) / 2
    return 2 * radius * math.sin(half), radius * (1 - math.cos(half))


def rounded(bend: Bend) -> Bend:
    """The nearest round values: R to 10 mm and the angle to half a degree."""
    return Bend(
        radius=round(bend.radius / RADIUS_STEP) * RADIUS_STEP,
        angle=round(bend.angle / ANGLE_STEP) * ANGLE_STEP,
    )


def agrees(curve: Curve) -> bool:
    """Do the curve's radius and angle agree with its measurement, rounded or not?"""
    if curve.measured is None:
        return True
    found = from_chord(curve.measured.chord, curve.measured.sagitta)
    return (
        abs(curve.radius - found.radius) <= found.radius * RADIUS_TOLERANCE
        and abs(curve.angle - found.angle) <= ANGLE_TOLERANCE
    )


def arc_length(radius: float, angle: float) -> float:
    return radius * math.radians(angle)


def edge_radius(curve: Curve, track1: float) -> float:
    """Kant 1's radius, from track 1's radius and its distance from Kant 1."""
    if curve.edge == EdgeSide.OUTER:
        return curve.radius + track1
    return curve.radius - track1


def line_radius(curve: Curve, track1: float, offset: float) -> float:
    """The radius of the line offset mm from Kant 1."""
    edge = edge_radius(curve, track1)
    return edge - offset if curve.edge == EdgeSide.OUTER else edge + offset


def centre(curve: Curve, track1: float) -> Point:
    """The curve's centre in the module's coordinates."""
    edge = edge_radius(curve, track1)
    return (0.0, edge) if curve.edge == EdgeSide.OUTER else (0.0, -edge)


def point_on(curve: Curve, track1: float, offset: float, angle: float) -> Point:
    """The point offset mm from Kant 1, angle degrees from gable A."""
    cx, cy = centre(curve, track1)
    r = line_radius(curve, track1, offset)
    phi = math.radians(angle)
    if curve.edge == EdgeSide.OUTER:
        return (cx + r * math.sin(phi), cy - r * math.cos(phi))
    return (cx + r * math.sin(phi), cy + r * math.cos(phi))


def width_at(shape: Shape, end: str) -> float:
    """The gable's width: where a track at the gable must lie within."""
    if isinstance(shape, Trapezoid):
        return shape.width_a if end == "A" else shape.width_b
    return shape.width


def length_of(shape: Shape) -> float:
    """Along Kant 1, or track 1's arc for a curve."""
    if isinstance(shape, (Straight, Trapezoid)):
        return shape.length
    return arc_length(shape.radius, shape.angle)
