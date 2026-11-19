"""Steps 3 and 9 of the chain: the quality gate, the scale and the control measures
(bildkedjan, Kvalitetsgrind; Skala och kontrollmått).

The quality gate, with the document's starting values:

    resolution on the module   ≥ 2 px/mm normal; 1–2 low: the tolerances are widened by 2/ppm
                               and shown; < 1 only the topology and rough measures, no length
    tilt from the vertical     ≤ 20° normal; 20–35° a warning; > 35° a new photo
    sharpness                  blurrier than SHARPNESS_REFUSE: a new photo
    clipped pixels             > 2 % a warning; a reflection over the tracks is masked (step 8)

The scale's sources, in order: the owner's locked and given measures, then the gauge averaged
over long straight stretches (one measurement varies ± 1,5 %), then the sleeper spacing, which
belongs to the track system and is an absolute scale only when that is known. The checks: the
sleeper spacing must be the same on straight and slanting tracks (the straightening is right),
and the owner's measures and the gauge may differ at most 1 % before it is a question.

The uncertainty per measure is computed, not a fixed ± 6 mm: the corners are moved by their own
uncertainty many times, with a fixed seed, and the camera solved each time, so the spread of
each measure shows how the corners' errors reach it, growing away from them (Criminisi's error
model for planes). The rails' height adds its part, and the profile's own precision at the gable.
The ± shown is two standard deviations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from cad import curves
from cad.bildkedjan.camera import Array, Camera, Shape, solve
from cad.bildkedjan.rectify import Grid
from cad.bildkedjan.trackmap import STEP, Profile, cross_sections, sample
from cad.curves import Line, Seg

RESOLUTION_NORMAL = 2.0
RESOLUTION_LOW = 1.0
TILT_WARN = 20.0
TILT_REFUSE = 35.0
SHARPNESS_WARN = 0.45
SHARPNESS_REFUSE = 0.6
"""The blur measure (Crété-Roffet): about 0,2 for a sharp photo, 0,5 blurred by 2 px."""
MOSAIC_WIDEN = 8.0
"""A mosaic's tolerances are this much wider: the photos are joined at the board, and the rails
lie a few millimetres above it, seen from two places (the synthetic two-photo test: up to 7 mm
where one photo gives 1). Each photo's lens is not taken out before they are joined either."""
CLIPPED_WARN = 0.02
SCALE_AGREE = 0.01
"""The owner's measure and the gauge may differ this much (1 %) before it is a question."""
GAUGE_LOCAL = 0.05
"""A stretch whose gauge differs more than 5 % followed something else: an uncertain part."""
SLEEPER_AGREE = 0.015
GAUGE_BLOCK_MM = 50.0
SAMPLES = 32
SEED = 89
RAIL_HEIGHT_SIGMA = 2.0
"""How well the rails' height is known, mm."""
PROFILE_SIGMA = 0.15
"""How well the profile finds a track's middle, mm."""


@dataclass(frozen=True)
class Gate:
    key: str
    value: float
    level: str
    """ok, low, warn or refuse"""
    text: str


@dataclass(frozen=True)
class Quality:
    px_per_mm: float
    tilt: float
    sharpness: float
    clipped: float
    gates: list[Gate]
    stitched: bool = False

    @property
    def refused(self) -> list[Gate]:
        return [g for g in self.gates if g.level == "refuse"]

    @property
    def widen(self) -> float:
        """How much the tolerances are widened at low resolution."""
        mosaic = MOSAIC_WIDEN if self.stitched else 1.0
        if self.px_per_mm >= RESOLUTION_NORMAL:
            return mosaic
        return mosaic * RESOLUTION_NORMAL / max(self.px_per_mm, 0.1)

    @property
    def length_from_photo(self) -> bool:
        return self.px_per_mm >= RESOLUTION_LOW


def blur(gray: NDArray[Any]) -> float:
    """The no-reference blur measure (Crété-Roffet): how much a blur by 9 px takes away of the
    differences between neighbours; 0 sharp, 1 already blurred."""
    g = gray.astype(np.float32)
    found = 0.0
    for kernel, axis in (((9, 1), 1), ((1, 9), 0)):
        smooth = cv2.blur(g, kernel)
        di = np.abs(np.diff(g, axis=axis))
        db = np.abs(np.diff(smooth, axis=axis))
        total = float(di.sum()) or 1.0
        found = max(found, (total - float(np.maximum(0, di - db).sum())) / total)
    return found


def quality(pixels: NDArray[Any], corners: Array, camera: Camera, outline: Array) -> Quality:
    """The quality gate on the photo and its camera."""
    ppm = float(camera.px_per_mm(outline).min())
    mask = np.zeros(pixels.shape[:2], np.uint8)
    cv2.fillPoly(mask, [np.round(corners).astype(np.int32)], 255)
    ys, xs = np.nonzero(mask)
    if len(xs):
        cx, cy = int(np.median(xs)), int(np.median(ys))
        half = 400
        crop = pixels[max(0, cy - half) : cy + half, max(0, cx - half) : cx + half]
        sharp = blur(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))
        inside = pixels[mask > 0]
        clipped = float((inside.max(axis=1) >= 250).mean())
    else:
        sharp, clipped = 1.0, 0.0
    gates: list[Gate] = []
    mm = f"{ppm:.1f}".replace(".", ",")
    if ppm >= RESOLUTION_NORMAL:
        gates.append(Gate("resolution", ppm, "ok", f"{mm} px per mm på modulen"))
    elif ppm >= RESOLUTION_LOW:
        gates.append(
            Gate(
                "resolution",
                ppm,
                "low",
                f"Låg upplösning: {mm} px per mm. Toleranserna är bredare, och ett nytt foto "
                "närmare ger bättre mått.",
            )
        )
    else:
        gates.append(
            Gate(
                "resolution",
                ppm,
                "low",
                f"Mycket låg upplösning: {mm} px per mm. Fotot ger spåren men inte längden. Ta "
                "ett nytt foto närmare.",
            )
        )
    tilt = camera.tilt
    degrees = f"{tilt:.0f}°"
    if tilt <= TILT_WARN:
        gates.append(Gate("tilt", tilt, "ok", f"Taget {degrees} från rakt ovanifrån"))
    elif tilt <= TILT_REFUSE:
        gates.append(
            Gate(
                "tilt",
                tilt,
                "warn",
                f"Taget snett, {degrees} från rakt ovanifrån. Rakare ger bättre mått.",
            )
        )
    else:
        gates.append(
            Gate(
                "tilt",
                tilt,
                "refuse",
                f"Taget för snett, {degrees} från rakt ovanifrån. Ta ett nytt foto mer rakt "
                "ovanifrån.",
            )
        )
    if sharp >= SHARPNESS_REFUSE:
        gates.append(
            Gate(
                "sharpness",
                sharp,
                "refuse",
                "Fotot är suddigt. Ta ett nytt foto, stilla och i fokus.",
            )
        )
    elif sharp >= SHARPNESS_WARN:
        gates.append(Gate("sharpness", sharp, "warn", "Fotot är lite suddigt."))
    else:
        gates.append(Gate("sharpness", sharp, "ok", "Skarpt"))
    share = f"{clipped * 100:.0f} %"
    if clipped > CLIPPED_WARN:
        gates.append(
            Gate(
                "clipped", clipped, "warn", f"{share} av modulen är överexponerad. Reflexer maskas."
            )
        )
    else:
        gates.append(Gate("clipped", clipped, "ok", "Ingen överexponering att tala om"))
    return Quality(ppm, tilt, sharp, clipped, gates)


# --- The gauge and the sleepers ---------------------------------------------------------------


@dataclass(frozen=True)
class GaugeResult:
    value: float | None
    """The mean gauge, mm, in the measuring image's scale."""
    spread: float
    places: int
    """How many 50 mm stretches it is averaged over."""
    worst: tuple[float, float] | None = None
    """The stretch whose gauge differs most, and where (mm, x)."""
    worst_at: tuple[float, float] | None = None


def straight_runs(segs: list[Seg], min_length: float) -> list[Line]:
    return [s for s in segs if isinstance(s, Line) and curves.length(s) >= min_length]


def _rails(section: NDArray[Any], half: float, rail: float, dark: bool) -> float | None:
    """The distance between the rails' middles in a cross section, mm, or None."""
    us = np.arange(-half, half + STEP / 2, STEP)
    values = -section if dark else section
    found: list[float] = []
    for sign in (-1, 1):
        window = (us * sign >= rail - 3) & (us * sign <= rail + 3)
        idx = np.nonzero(window)[0]
        if len(idx) < 5:
            return None
        k = idx[int(np.argmax(values[idx]))]
        if k in (idx[0], idx[-1]):
            return None
        y0, y1, y2 = values[k - 1], values[k], values[k + 1]
        d = y0 - 2 * y1 + y2
        shift = 0.5 * (y0 - y2) / d if d < 0 else 0.0
        found.append(float(us[k] + shift * STEP))
    return found[1] - found[0]


def gauge(
    gray: NDArray[Any],
    grid: Grid,
    runs: list[Line],
    profile: Profile,
    head: float,
) -> GaugeResult:
    """The gauge over the straight runs: each 50 mm averaged across, the rails' middles found
    to a fraction of a millimetre, less a rail head's width."""
    dark = float(
        profile.values[
            np.argmin(
                np.abs(np.linspace(-profile.half, profile.half, len(profile.values)) - profile.rail)
            )
        ]
    ) < float(profile.values[len(profile.values) // 2])
    values: list[tuple[float, float, float]] = []
    for line in runs:
        length = curves.length(line)
        heading = curves.start_heading(line)
        count = int(length // GAUGE_BLOCK_MM)
        for k in range(count):
            s0 = k * GAUGE_BLOCK_MM + 10
            ss = np.arange(s0, s0 + GAUGE_BLOCK_MM - 20, 5.0)
            points = np.array([curves.point_at(line, float(s)) for s in ss])
            sections = cross_sections(
                gray, grid, points, np.full(len(points), heading), profile.half
            )
            found = _rails(sections.mean(axis=0), profile.half, profile.rail, dark)
            if found is not None:
                mid = curves.point_at(line, s0 + GAUGE_BLOCK_MM / 2)
                values.append((found - head, mid[0], mid[1]))
    if not values:
        return GaugeResult(None, 0.0, 0)
    gauges = np.array([v[0] for v in values])
    median = float(np.median(gauges))
    keep = np.abs(gauges - median) <= max(
        0.6, 3 * float(np.median(np.abs(gauges - median))) * 1.4826
    )
    mean = float(gauges[keep].mean())
    worst_i = int(np.argmax(np.abs(gauges - mean)))
    return GaugeResult(
        mean,
        float(gauges[keep].std() / math.sqrt(max(1, int(keep.sum())))),
        int(keep.sum()),
        (float(gauges[worst_i]), float(values[worst_i][1])),
        (values[worst_i][1], values[worst_i][2]),
    )


@dataclass(frozen=True)
class Sleepers:
    straight: float | None
    slanting: float | None
    slanting_angle: float | None
    agree: bool | None


def sleeper_spacing(gray: NDArray[Any], grid: Grid, line: Line, gauge_mm: float) -> float | None:
    """The sleepers' spacing along a straight, from the brightness along its middle (FFT)."""
    length = curves.length(line)
    if length < 120:
        return None
    heading = curves.start_heading(line)
    ss = np.arange(10, length - 10, 0.25)
    across = np.linspace(-0.3 * gauge_mm, 0.3 * gauge_mm, 7)
    u = np.array([math.cos(heading), math.sin(heading)])
    n = np.array([-math.sin(heading), math.cos(heading)])
    pts = np.array(line.start) + ss[:, None, None] * u + across[None, :, None] * n
    px = grid.to_px(pts.reshape(-1, 2))
    values = sample(gray, px[:, 0], px[:, 1]).reshape(len(ss), len(across)).mean(axis=1)
    values = values - np.convolve(values, np.ones(41) / 41, mode="same")
    window = np.hanning(len(values))
    spectrum = np.abs(np.fft.rfft(values * window))
    freqs = np.fft.rfftfreq(len(values), d=0.25)
    lo, hi = 1 / (0.75 * gauge_mm), 1 / (0.25 * gauge_mm)
    band = (freqs >= lo) & (freqs <= hi)
    if not band.any():
        return None
    idx = np.nonzero(band)[0]
    k = idx[int(np.argmax(spectrum[idx]))]
    if spectrum[k] < 4 * float(np.median(spectrum[idx])):
        return None
    shift = 0.0
    if 0 < k < len(spectrum) - 1:
        y0, y1, y2 = np.log(spectrum[k - 1 : k + 2] + 1e-9)
        d = y0 - 2 * y1 + y2
        shift = 0.5 * (y0 - y2) / d if d < 0 else 0.0
    frequency = (k + shift) * (freqs[1] - freqs[0])
    return 1 / frequency if frequency > 0 else None


def sleepers(gray: NDArray[Any], grid: Grid, runs: list[Line], gauge_mm: float) -> Sleepers:
    straight: list[float] = []
    slanting: list[tuple[float, float]] = []
    for line in runs:
        found = sleeper_spacing(gray, grid, line, gauge_mm)
        if found is None:
            continue
        angle = abs(math.degrees(curves.start_heading(line)))
        angle = min(angle, 180 - angle)
        if angle < 3:
            straight.append(found)
        else:
            slanting.append((found, angle))
    a = float(np.median(straight)) if straight else None
    b = float(np.median([s for s, _ in slanting])) if slanting else None
    slant = float(np.median([x for _, x in slanting])) if slanting else None
    agree = abs(a - b) / a <= SLEEPER_AGREE if a and b else None
    return Sleepers(a, b, slant, agree)


# --- The uncertainty --------------------------------------------------------------------------


@dataclass(frozen=True)
class Spread:
    length: float | None
    offset: float | None
    points: Array
    """Each measured point's spread in mm, one standard deviation in x and in y."""
    samples: int = 0


@dataclass
class Monte:
    corners: Array
    shape: Shape
    size: tuple[int, int]
    focal: float
    k: float
    sigma: float
    rail_height: float
    points_px: Array
    seed: int = SEED
    count: int = SAMPLES
    lengths: list[float] = field(default_factory=list)

    def run(self) -> Spread:
        """Each measure's spread when the corners move by their own uncertainty."""
        rng = np.random.default_rng(self.seed)
        lengths: list[float] = []
        offsets: list[float] = []
        moved: list[Array] = []
        for _ in range(self.count):
            noisy = self.corners + rng.normal(0, self.sigma, self.corners.shape)
            camera, length, offset = solve(noisy, self.shape, self.size, self.focal, self.k)
            lengths.append(length)
            offsets.append(offset)
            if len(self.points_px):
                h = self.rail_height + rng.normal(0, RAIL_HEIGHT_SIGMA)
                moved.append(camera.to_plane(self.points_px, h))
        if moved:
            stack = np.stack(moved)
            spread = np.sqrt(stack.var(axis=0) + PROFILE_SIGMA**2)
        else:
            spread = np.zeros((0, 2))
        return Spread(
            float(np.std(lengths)) if self.shape.length is None else None,
            float(np.std(offsets))
            if self.shape.kind == "trapezoid" and self.shape.offset is None
            else None,
            spread,
            self.count,
        )


def plus_minus(sigma: float, widen: float = 1.0) -> float:
    """The ± shown: two standard deviations, at least 0,3 mm, widened at low resolution."""
    return round(max(0.3, 2 * sigma) * widen, 1)
