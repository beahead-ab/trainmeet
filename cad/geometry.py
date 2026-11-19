"""The module's geometry from its measures: code measures, nothing is guessed.

A curve module is measured with a string between track 1's centre at gable A and gable B and
the sagitta from its middle (CADMOB-03, the view Kurvmodul):

    R = (c² + 4s²) / 8s        θ = 2·asin(c / 2R)

and back, from the radius and the angle, c = 2R·sin(θ/2) and s = R·(1 - cos(θ/2)). The radius
and the angle are kept exactly as computed, without rounding (CAD16, CAD-35).

The module's own coordinates are the station model's: x from gable A along Kant 1, y away from
Kant 1, in mm, y down the drawing. A straight module's track at d mm from Kant 1 runs from
(0, d) to (L, d). A curve with Kant 1 as the outer edge turns right seen from gable A: its centre
lies at (0, R₁) under Kant 1, where R₁ = R + d₁ is Kant 1's radius and d₁ track 1's distance from
Kant 1; a line d mm from Kant 1 has the radius R₁ - d. With Kant 1 as the inner edge the curve
turns left, the centre lies at (0, -R₁) above it, R₁ = R - d₁, and the line's radius is R₁ + d.
A trapezoid's gables are parallel, at x = 0 and x = L, and gable B's corner at Kant 1 lies at
(L, offset): its tracks lie at y = offset + d.

The drawing (part b) measures a point from the gables: from_a is how far it lies from gable A
along the module (x, or on a curve the arc at the point's own radius from gable A's radial
line), and kant1_offset how far a point at a gable lies from Kant 1 along that gable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from contracts.cad import Curve, CurveSides, EdgeSide, GableEnd, Shape, Straight, Trapezoid
from contracts.station_model import Point

RADIUS_TOLERANCE = 0.0005
"""A curve's radius may differ by 0,05 % from the one its measurement gives: what the numbers
lose on their way, never a rounding (CAD16)."""
ANGLE_TOLERANCE = 0.01
"""And its angle by a hundredth of a degree."""


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


def agrees(curve: Curve) -> bool:
    """Do the curve's radius and angle agree with its measurement, as computed (CAD16)?"""
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


def track1_of(tracks_a: list[float] | tuple[float, ...]) -> float:
    """Track 1's distance from Kant 1 at gable A: where a curve's string is measured."""
    return tracks_a[0] if tracks_a else 0.0


@dataclass(frozen=True)
class GableLine:
    """A gable as a line in the module: its corner at Kant 1, the direction along it away
    from Kant 1, the direction into the module, and its width."""

    end: GableEnd
    corner: Point
    along: Point
    inward: Point
    width: float

    def point(self, offset: float) -> Point:
        """The point offset mm from Kant 1 on the gable."""
        return (self.corner[0] + self.along[0] * offset, self.corner[1] + self.along[1] * offset)

    def offset(self, p: Point) -> float:
        """How far along the gable p lies from Kant 1."""
        return (p[0] - self.corner[0]) * self.along[0] + (p[1] - self.corner[1]) * self.along[1]

    def depth(self, p: Point) -> float:
        """How far into the module p lies from the gable (negative: outside it)."""
        return (p[0] - self.corner[0]) * self.inward[0] + (p[1] - self.corner[1]) * self.inward[1]


def gable_line(shape: Shape, track1: float, end: GableEnd) -> GableLine:
    width = width_at(shape, end.value)
    if isinstance(shape, Curve):
        angle = 0.0 if end == GableEnd.A else shape.angle
        corner = point_on(shape, track1, 0, angle)
        far = point_on(shape, track1, 1, angle)
        along = (far[0] - corner[0], far[1] - corner[1])
        phi = math.radians(angle)
        tangent = (
            (math.cos(phi), math.sin(phi))
            if shape.edge == EdgeSide.OUTER
            else (math.cos(phi), -math.sin(phi))
        )
        inward = tangent if end == GableEnd.A else (-tangent[0], -tangent[1])
        return GableLine(end, corner, along, inward, width)
    if end == GableEnd.A:
        return GableLine(end, (0.0, 0.0), (0.0, 1.0), (1.0, 0.0), width)
    shift = shape.offset if isinstance(shape, Trapezoid) else 0.0
    return GableLine(end, (shape.length, shift), (0.0, 1.0), (-1.0, 0.0), width)


def from_a(shape: Shape, track1: float, p: Point) -> float:
    """How far p lies from gable A along the module, in mm (a switch's points, Tungspetsar)."""
    if not isinstance(shape, Curve):
        return p[0]
    cx, cy = centre(shape, track1)
    r = math.dist((cx, cy), p)
    if shape.edge == EdgeSide.OUTER:
        phi = math.atan2(p[1] - cy, p[0] - cx) + math.pi / 2
    else:
        phi = math.pi / 2 - math.atan2(p[1] - cy, p[0] - cx)
    return r * phi


def outline(shape: Shape, track1: float, steps: int = 48) -> list[Point]:
    """The board's outline, Kant 1 first from gable A, as the web app draws it."""
    if isinstance(shape, Straight):
        return [(0, 0), (shape.length, 0), (shape.length, shape.width), (0, shape.width)]
    if isinstance(shape, Trapezoid):
        o = shape.offset
        return [(0, 0), (shape.length, o), (shape.length, o + shape.width_b), (0, shape.width_a)]
    bent = shape.sides == CurveSides.BENT
    ks = range(steps + 1) if bent else (0, steps)
    edge = [point_on(shape, track1, 0, shape.angle * k / steps) for k in ks]
    far = [point_on(shape, track1, shape.width, shape.angle * k / steps) for k in ks]
    return edge + far[::-1]


def _segment_distance(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    total = dx * dx + dy * dy
    t = 0.0 if total == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / total))
    return math.dist(p, (a[0] + dx * t, a[1] + dy * t))


def inside(shape: Shape, track1: float, p: Point, margin: float = 1.0) -> bool:
    """Does p lie on the board, or within margin mm of its edge?"""
    poly = outline(shape, track1)
    crossings = False
    for a, b in zip(poly, poly[1:] + poly[:1], strict=True):
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if p[0] < x:
                crossings = not crossings
    if crossings:
        return True
    return any(
        _segment_distance(p, a, b) <= margin for a, b in zip(poly, poly[1:] + poly[:1], strict=True)
    )
