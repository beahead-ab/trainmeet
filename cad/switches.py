"""What a drawing is held to in each scale, and the switch library (Växeltyp), for Ritningen
(CAD-03) and Att kolla.

The numbers and where they come from, in H0:

- Gauge 16,5 mm (bildkedjan step 9); in N 9 mm and in 0 32 mm, the NEM 010 gauges.
- The track's minimum radius 400 mm: the AnyRail import draws a curve under 400 mm again
  (trainmeet-cad-anyrail-import.md, 3.2), and Normal utjämning holds to it (ritningen.jpg).
- The switches' lower limit 300 mm: the drawing's example calls a fitted radius of 300 mm "vid
  nedre gränsen" (ritningen.jpg, Att kolla 2).
- The kink check samples every 10 mm (the AnyRail import, 3.3), so an angle jump over one step
  larger than the minimum radius gives, 10/400 rad = 1,43°, is a kink.
- A gable track more than 2 mm from its measure is shown (bildkedjan steps 13 and 15).
- A switch whose radius lies more than 10 % from every type is antagen (bildkedjan step 15,
  AR3).

The spec gives these for H0 only. In N and 0 the radii are H0's scaled by the gauge, rounded to
10 mm; they are starting values, as bildkedjan's limits are, until the spec says otherwise.

The switch library holds the types whose radius and angle the spec gives: the five switch types
of the AnyRail import's reference station (CDA, the table in 1. Filformatet), in H0. Nothing is
taken from a manufacturer's catalogue. Okänd is first: the radius is then what was drawn.
"""

from __future__ import annotations

import math
from typing import Final

from contracts.cad import UNKNOWN_DESIGN, Scale, ScaleLimits, SwitchDesign

SAMPLE_STEP: Final = 10.0
GAUGE: Final = {Scale.H0: 16.5, Scale.N: 9.0, Scale.ZERO: 32.0}
H0_MIN_RADIUS: Final = 400.0
H0_SWITCH_MIN_RADIUS: Final = 300.0
GABLE_TOLERANCE: Final = 2.0
DESIGN_TOLERANCE: Final = 0.10


def _scaled(h0: float, scale: Scale) -> float:
    if scale == Scale.H0:
        return h0
    return round(h0 * GAUGE[scale] / GAUGE[Scale.H0] / 10) * 10


def limits(scale: Scale) -> ScaleLimits:
    min_radius = _scaled(H0_MIN_RADIUS, scale)
    return ScaleLimits(
        scale=scale,
        gauge=GAUGE[scale],
        min_radius=min_radius,
        switch_min_radius=_scaled(H0_SWITCH_MIN_RADIUS, scale),
        kink=round(math.degrees(SAMPLE_STEP / min_radius), 2),
        gable_tolerance=GABLE_TOLERANCE,
        design_tolerance=DESIGN_TOLERANCE,
    )


SOURCE: Final = "Växeltyperna i en station läst ur AnyRail (specen, importen från AnyRail)."

UNKNOWN: Final = SwitchDesign(id=UNKNOWN_DESIGN, name="Okänd")


def _h0(radius_cm: float, angle: float) -> SwitchDesign:
    # The AnyRail import's table gives the radius in cm and the angle in degrees.
    radius = radius_cm * 10
    return SwitchDesign(
        id=f"h0-r{radius:.0f}-{angle * 10:.0f}",
        name=f"R {radius:.0f} · {angle:.1f}°".replace(".", ","),
        scale=Scale.H0,
        radius=radius,
        angle=angle,
        source=SOURCE,
    )


# CDA's switch types (trainmeet-cad-anyrail-import.md, 1. Filformatet): 220 cm 9,4° (21 of
# them), 210 cm 6,3° (19), 188 cm 7,2° (6), 83 cm 11,4° (2) and 97 cm 9,5° (2).
DESIGNS: Final[tuple[SwitchDesign, ...]] = (
    _h0(220, 9.4),
    _h0(210, 6.3),
    _h0(188, 7.2),
    _h0(83, 11.4),
    _h0(97, 9.5),
)

BY_ID: Final = {d.id: d for d in (UNKNOWN, *DESIGNS)}


def designs(scale: Scale) -> list[SwitchDesign]:
    """Okänd, then the scale's types by radius."""
    return [UNKNOWN, *sorted((d for d in DESIGNS if d.scale == scale), key=lambda d: d.radius or 0)]


def design(design_id: str | None) -> SwitchDesign:
    return BY_ID.get(design_id or UNKNOWN_DESIGN, UNKNOWN)


def match(radius: float | None, angle: float | None, scale: Scale) -> SwitchDesign | None:
    """The scale's type nearest the radius within the tolerance, the angle deciding between
    two; None when there is none: the switch is then antagen (AR3)."""
    if radius is None:
        return None
    found: list[tuple[float, float, str, SwitchDesign]] = []
    for known in DESIGNS:
        if known.scale != scale or known.radius is None:
            continue
        off = abs(radius - known.radius) / known.radius
        if off <= DESIGN_TOLERANCE:
            angle_off = abs((angle or 0) - (known.angle or 0)) if angle is not None else 0.0
            found.append((off, angle_off, known.id, known))
    return min(found)[3] if found else None
