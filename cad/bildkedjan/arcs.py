"""Step 6 of the chain for a curve module: are its edges circular arcs once straightened?
(bildkedjan, Uträtning och höjd, Kurvmodul.)

A curve module is straightened from its four corners and the owner's chord and sagitta, which
give Kant 1's radius and the angle exactly (CAD16). Its long sides are arcs about one centre;
when the corners or the measures are wrong, the straightening bends them into other curves. So
the edges are looked for in the measuring image, across where the arcs should be, and fitted
with a circle: an edge that lies further than EDGE_MM from its arc, or is no circle, means the
corners or the measures are wrong, and the owner is asked (bildkedjan step 15, Hörn osäkra).

Scenery over an edge (grass, a platform) hides it in places: a side with too few clear edge
points is left out, and the check rests on the other.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from cad.bildkedjan.camera import Array, Shape
from cad.bildkedjan.rectify import Grid
from cad.bildkedjan.trackmap import sample

EDGE_MM = 3.0
"""An edge further than this from its arc is not where the measures put it."""
ROUND_MM = 1.5
"""A found edge that lies on no circle within this (RMS) is no clear edge: scenery over it."""
RADIUS_SHARE = 0.012
"""and its circle's radius within this share of the arc's, or within what moves the arc's
sagitta EDGE_MM / 2 when that is more: a corner off bends both long sides, but on a short arc
the radius says little (the synthetic curve, 20°: 0,4 % with the true corners and the lens, 3 %
without the lens, and 2–3 % for a corner 5 mm off, where the edges lie 0,3–0,6 mm off)."""
REACH_MM = 9.0
"""How far across the expected arc the edge is looked for, mm (the measuring image has a
margin of 10 mm around the module)."""
SAMPLES = 48
MIN_SHARE = 0.4
"""A side counts when at least this share of its places show a clear edge."""
EDGE_CONTRAST = 6.0
CHECK_PPM = 2.0
"""The edges are looked for in the frame's plane at this scale, px per mm."""


@dataclass(frozen=True)
class Side:
    name: str
    """kant1 or far"""
    expected: float
    """The arc's radius, mm."""
    found: float | None
    """The circle fitted to the edge, mm."""
    deviation: float
    """The edge's distance from the expected arc, mm: 90 % of the places lie within it."""
    roundness: float
    """The edge's RMS distance from its own circle, mm."""
    places: int
    allowed: float = RADIUS_SHARE
    """How far its circle's radius may lie from the arc's, as a share: RADIUS_SHARE, or what
    moves the arc's sagitta EDGE_MM / 2 on a short arc, whichever is more."""


@dataclass(frozen=True)
class Edges:
    sides: list[Side] = field(default_factory=list)

    @property
    def deviation(self) -> float:
        return max((s.deviation for s in self.sides), default=0.0)

    @property
    def clear(self) -> list[Side]:
        """The sides whose edge was found as a clear line: an edge under grass or a platform
        scatters, and says nothing about the arc."""
        return [s for s in self.sides if s.roundness <= ROUND_MM]

    @property
    def round(self) -> bool:
        """The clear sides where their arcs should be, with their own radius; true when no side
        is clear enough to say."""
        return all(
            s.deviation <= EDGE_MM
            and (s.found is None or abs(s.found / s.expected - 1) <= s.allowed)
            for s in self.clear
        )

    def text(self) -> str:
        mm = f"{self.deviation:.1f}".replace(".", ",")
        return (
            f"Kurvans kanter blir inte cirkelbågar när fotot rätas ut: de ligger upp till {mm} mm "
            "från bågarna som kordan och pilhöjden ger. Hörnen eller kurvans mått stämmer inte. "
            "Dra hörnen rätt, eller mät kordan och pilhöjden igen."
        )

    def as_json(self) -> list[list[Any]]:
        return [
            [s.name, s.expected, s.found, s.deviation, s.roundness, s.places, s.allowed]
            for s in self.sides
        ]

    @classmethod
    def of(cls, data: list[list[Any]]) -> Edges:
        return cls(
            [
                Side(
                    str(side[0]),
                    float(side[1]),
                    None if side[2] is None else float(side[2]),
                    float(side[3]),
                    float(side[4]),
                    int(side[5]),
                    float(side[6]) if len(side) > 6 else RADIUS_SHARE,
                )
                for side in data
            ]
        )


def _lab(image: NDArray[Any]) -> NDArray[Any]:
    lab = cv2.cvtColor(cv2.GaussianBlur(image, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    lab[..., 0] *= 0.35
    return lab


def circle(points: Array) -> tuple[Array, float, float]:
    """The circle through the points by least squares (Kåsa), its centre, radius and RMS."""
    x, y = points[:, 0], points[:, 1]
    a = np.c_[2 * x, 2 * y, np.ones(len(x))]
    b = x * x + y * y
    (cx, cy, c), *_ = np.linalg.lstsq(a, b, rcond=None)
    r = math.sqrt(max(1e-9, c + cx * cx + cy * cy))
    off = np.hypot(x - cx, y - cy) - r
    return np.array([cx, cy]), r, float(np.sqrt(np.mean(off * off)))


def _side(lab: NDArray[Any], grid: Grid, shape: Shape, offset_mm: float, name: str) -> Side | None:
    assert shape.angle is not None and shape.radius is not None
    centre = shape.point(0.0, 0.0) + (
        np.array([0.0, shape.radius]) if shape.edge == "outer" else np.array([0.0, -shape.radius])
    )
    angles = np.linspace(0.06, 0.94, SAMPLES) * shape.angle
    points = np.array([shape.point(offset_mm, float(a)) for a in angles])
    radial = points - centre
    radial /= np.linalg.norm(radial, axis=1, keepdims=True)
    # Outward: away from the module, across its edge.
    outer_edge = (shape.edge == "outer") == (offset_mm == 0.0)
    normal = radial if outer_edge else -radial
    step = 0.5
    offs = np.arange(-REACH_MM, REACH_MM + step / 2, step)
    found: list[Array] = []
    distances: list[float] = []
    for p, n in zip(points, normal, strict=True):
        line = p[None, :] + offs[:, None] * n[None, :]
        px = grid.to_px(line)
        colours = np.stack([sample(lab[..., c], px[:, 0], px[:, 1]) for c in range(3)], axis=1)
        # From outside in: the first clear change from the colour just outside.
        outside = colours[-4:].mean(axis=0)
        inside = colours[:4].mean(axis=0)
        if float(np.linalg.norm(outside - inside)) < EDGE_CONTRAST:
            continue
        grad = np.linalg.norm(np.diff(colours, axis=0), axis=1)
        i = int(np.argmax(grad))
        shift = 0.0
        if 0 < i < len(grad) - 1:
            y0, y1, y2 = grad[i - 1], grad[i], grad[i + 1]
            d = y0 - 2 * y1 + y2
            shift = 0.5 * (y0 - y2) / d if d < 0 else 0.0
        o = float(offs[i] + step / 2 + shift * step)
        distances.append(o)
        found.append(p + o * n)
    if len(found) < MIN_SHARE * SAMPLES:
        return None
    pts = np.array(found)
    d = np.array(distances)
    # Leave out what scenery over the edge put far off: the median's neighbourhood decides.
    keep = np.abs(d - np.median(d)) <= max(
        2.0, 3 * 1.4826 * float(np.median(np.abs(d - np.median(d))))
    )
    if keep.sum() < MIN_SHARE * SAMPLES:
        return None
    _, r, rms = circle(pts[keep])
    expected = float(np.linalg.norm(points[0] - centre))
    sagitta = expected * (1 - math.cos(math.radians(shape.angle) / 2))
    return Side(
        name,
        round(expected, 1),
        round(r, 1),
        round(float(np.median(np.abs(d[keep]))), 2),
        round(rms, 2),
        int(keep.sum()),
        round(max(RADIUS_SHARE, EDGE_MM / 2 / max(sagitta, 1e-6)), 4),
    )


def check(image: NDArray[Any], grid: Grid, shape: Shape) -> Edges:
    """The curve's long sides found in the measuring image and compared with their arcs."""
    lab = _lab(image)
    sides = [
        s
        for s in (
            _side(lab, grid, shape, 0.0, "kant1"),
            _side(lab, grid, shape, shape.width_a, "far"),
        )
        if s is not None
    ]
    return Edges(sides)
