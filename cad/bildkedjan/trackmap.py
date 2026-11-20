"""Step 10 of the chain: where the tracks are (bildkedjan, Spårkarta), and the track's centre to
a fraction of a millimetre (step 13, Gavlar och norm).

The track's profile across it, from the photo test (lärdomarna, Kostnadskarta): two rails a
gauge apart and the band of sleepers between them. It is matched with normalised cross
correlation (NCC) in every direction, ANGLES of them over half a turn, so the map says for every
millimetre how much it looks like the middle of a track, and which way that track runs. A plain
darkness map puts the line on one rail, about 9 mm wrong; the profile puts it in the middle.

The map is made at MAP_PPM px per mm: the image is turned so the direction lies along x, the
profile is the same at every place along the track over TEMPLATE_LENGTH mm, so the NCC is a box
filter along the track and a short correlation across it, and the result is turned back.

The centre of a track at a place is then found in the measuring image itself (2 px per mm): the
cross section is averaged over ten millimetres along the track and matched against the profile
at quarter-millimetre shifts, with a parabola through the best three (± 0,5 mm at the gable,
lärdomarna). Once the gables' tracks are found, their own average cross section is the profile:
the photo's own sleepers and rails, whatever their colours.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from cad.bildkedjan.camera import Array
from cad.bildkedjan.rectify import Grid, Mask

ANGLES = 24
MAP_PPM = 1.0
TEMPLATE_LENGTH = 8.0
"""mm along the track that the profile is averaged over in the map."""
STEP = 0.25
"""The cross section's resolution, mm."""
SEARCH = 4.0
"""How far a centre may move when it is refined, mm."""
ALONG = 10.0
"""How long a piece of track a refined centre is averaged over, mm."""
GABLE_STRIP = (8.0, 26.0)
"""The strip at a gable where its tracks are looked for, mm in from the gable."""
TRACK_SCORE = 0.3
"""A map value over this is track."""

Floats = NDArray[Any]


@dataclass(frozen=True)
class Profile:
    """The track's cross section, from its middle out, every STEP mm."""

    values: Floats
    half: float
    """mm on each side of the middle."""
    rail: float
    """mm from the middle to a rail's middle."""
    learned: bool = False

    def at(self, ppm: float) -> Floats:
        """The profile in px of the given scale, zero mean."""
        count = max(3, round(2 * self.half * ppm) | 1)
        us = np.linspace(-self.half, self.half, count)
        grid = np.linspace(-self.half, self.half, len(self.values))
        found = np.interp(us, grid, self.values).astype(np.float32)
        return found - found.mean()


def profile_gauge(profile: Profile) -> float:
    """The distance between the rails' middles the profile was made for, mm."""
    return profile.rail * 2


def generic_profile(gauge: float, head: float | None = None) -> Profile:
    """Two dark rails a gauge apart, a lighter band of sleepers between them, ballast outside."""
    half = 1.25 * gauge
    us = np.arange(-half, half + STEP / 2, STEP)
    head = head if head is not None else gauge * 0.06
    rail = (gauge + head) / 2
    values = np.zeros_like(us)
    values[np.abs(us) < 0.85 * gauge] = 0.3
    values[np.abs(np.abs(us) - rail) <= head / 2 + STEP / 2] = -1.0
    return Profile(values.astype(np.float32), half, rail=rail)


def sample(image: Floats, xs: Array, ys: Array, *, border: float = 0.0) -> Array:
    """The image at the px (xs, ys), bilinear, for any number of points."""
    flat_x = np.asarray(xs, np.float32).ravel()
    flat_y = np.asarray(ys, np.float32).ravel()
    n = len(flat_x)
    if n == 0:
        return np.zeros(0)
    width = 1024
    rows = -(-n // width)
    pad = rows * width - n
    map_x = np.concatenate([flat_x, np.full(pad, -10, np.float32)]).reshape(rows, width)
    map_y = np.concatenate([flat_y, np.full(pad, -10, np.float32)]).reshape(rows, width)
    found = cv2.remap(
        image, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=border
    )
    return found.ravel()[:n].astype(np.float64)


@dataclass(frozen=True)
class TrackMap:
    """How much each millimetre looks like a track's middle, and the track's direction there
    (radians, 0 along x, modulo π). In the grid's millimetres at MAP_PPM."""

    score: Floats
    direction: Floats
    grid: Grid

    def at(self, points: Array) -> tuple[Array, Array]:
        """The score and direction at points in mm, bilinear for the score."""
        px = self.grid.to_px(points)
        score = sample(self.score, px[:, 0], px[:, 1])
        ix = np.clip(np.round(px[:, 0]).astype(int), 0, self.grid.width - 1)
        iy = np.clip(np.round(px[:, 1]).astype(int), 0, self.grid.height - 1)
        return score, self.direction[iy, ix].astype(np.float64)


def _shift_y(image: Floats, by: float) -> Floats:
    """The image moved by px down (a fraction of a px too)."""
    found: Floats = cv2.warpAffine(
        image,
        np.array([[1, 0, 0], [0, 1, by]], np.float32),
        (image.shape[1], image.shape[0]),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return found


def _scores_along_x(
    image: Floats, profile: Floats, length: int, rail: float
) -> tuple[Floats, Floats]:
    """For a track along x: the NCC of the profile across y, the same along length px of x,
    times how clearly both rails are there, rail px above and below; for dark rails and for
    light ones. One rail and the edge of the ballast match the profile half as well, a rail's
    distance beside the middle: the two-rail factor tells them apart."""
    width = len(profile)
    along = cv2.blur(image, (length, 1))
    numerator = cv2.filter2D(along, -1, profile.reshape(-1, 1), borderType=cv2.BORDER_REFLECT)
    mean = cv2.blur(along, (1, width))
    square = cv2.blur(cv2.blur(image * image, (length, 1)), (1, width))
    variance = np.maximum(square - mean * mean, 1e-3)
    norm = float(np.sqrt((profile * profile).sum()))
    spread = np.sqrt(variance)
    ncc = numerator / (spread * math.sqrt(width) * norm)
    # A rail is a thin line: darker (or lighter) than what lies 2 px on both sides of it. An
    # edge, darker on one side only, is no rail.
    above, below = _shift_y(along, 2.0), _shift_y(along, -2.0)
    dip = np.minimum(above, below) - along
    bump = along - np.maximum(above, below)
    dark = np.clip(
        np.minimum(_shift_y(dip, rail), _shift_y(dip, -rail)) / (RAIL_CLEAR * spread), 0, 1
    )
    light = np.clip(
        np.minimum(_shift_y(bump, rail), _shift_y(bump, -rail)) / (RAIL_CLEAR * spread), 0, 1
    )
    return (ncc * dark).astype(np.float32), (-ncc * light).astype(np.float32)


RAIL_CLEAR = 0.25
"""How deep a rail's dip must be, as a share of the window's spread, to count fully."""


QUIET = 0.6
"""What the map counts for over a shadow's edge or a reflection (bildkedjan step 8)."""


def track_map(
    gray: Floats, grid: Grid, inside: Mask, profile: Profile, quiet: Mask | None = None
) -> TrackMap:
    """The map from the measuring image's grey at MAP_PPM. Where quiet is set (a shadow's edge,
    a reflection) the map counts for less."""
    h, w = gray.shape
    p = profile.at(grid.ppm)
    length = max(3, round(TEMPLATE_LENGTH * grid.ppm))
    diagonal = math.ceil(math.hypot(h, w)) + 4
    centre = (w / 2, h / 2)
    rail = (profile_gauge(profile) / 2) * grid.ppm
    best = np.full((h, w), -1.0, np.float32)
    worst = np.full((h, w), -1.0, np.float32)
    best_at = np.zeros((h, w), np.int32)
    worst_at = np.zeros((h, w), np.int32)
    fill = float(np.median(gray[inside])) if inside.any() else 0.0
    for k in range(ANGLES):
        theta = math.pi * k / ANGLES
        # Turn the image so the direction theta lies along x.
        turn = cv2.getRotationMatrix2D(centre, math.degrees(theta), 1.0)
        turn[0, 2] += (diagonal - w) / 2
        turn[1, 2] += (diagonal - h) / 2
        turned = cv2.warpAffine(
            gray, turn, (diagonal, diagonal), flags=cv2.INTER_LINEAR, borderValue=fill
        )
        dark, light = _scores_along_x(turned, p, length, rail)
        back = cv2.invertAffineTransform(turn)
        for found, at, score in (
            (best, best_at, cv2.warpAffine(dark, back, (w, h), flags=cv2.INTER_LINEAR)),
            (worst, worst_at, cv2.warpAffine(light, back, (w, h), flags=cv2.INTER_LINEAR)),
        ):
            better = score > found
            found[better] = score[better]
            at[better] = k
    # The rails' polarity is the photo's own: darker or lighter than the sleepers.
    positive = float(np.percentile(best[inside], 99.5)) if inside.any() else 0.0
    negative = float(np.percentile(worst[inside], 99.5)) if inside.any() else 0.0
    if negative > positive * 1.15:
        best, best_at = worst, worst_at
    score = np.where(inside, np.clip(best, 0, 1), 0).astype(np.float32)
    if quiet is not None:
        score = np.where(quiet, score * QUIET, score).astype(np.float32)
    direction = (best_at.astype(np.float32) * (math.pi / ANGLES)).astype(np.float32)
    return TrackMap(score, direction, grid)


# --- The centre to a fraction of a millimetre -------------------------------------------------


def cross_sections(gray: Floats, grid: Grid, points: Array, headings: Array, half: float) -> Floats:
    """The cross section at each point, averaged over ALONG mm of track, every STEP mm from
    -half to half."""
    us = np.arange(-half, half + STEP / 2, STEP)
    ts = np.arange(-ALONG / 2, ALONG / 2 + 0.25, 0.5)
    cos, sin = np.cos(headings), np.sin(headings)
    # x = p + t·u + s·n, with u along the track and n across it.
    x = (
        points[:, 0, None, None]
        + ts[None, :, None] * cos[:, None, None]
        - us[None, None, :] * sin[:, None, None]
    )
    y = (
        points[:, 1, None, None]
        + ts[None, :, None] * sin[:, None, None]
        + us[None, None, :] * cos[:, None, None]
    )
    px = (x - grid.x0) * grid.ppm
    py = (y - grid.y0) * grid.ppm
    n = len(points)
    border = float(gray[::16, ::16].mean())
    values = sample(gray, px, py, border=border)
    found: Floats = values.reshape(n, len(ts), len(us)).mean(axis=1).astype(np.float32)
    return found


@dataclass(frozen=True)
class Refined:
    shift: Array
    """How far each centre moved across its track, mm (positive to the right of its heading)."""
    score: Array
    """The NCC at the best shift."""


def refine(gray: Floats, grid: Grid, points: Array, headings: Array, profile: Profile) -> Refined:
    """Each point moved across its track to the track's middle, by the profile."""
    if not len(points):
        return Refined(np.zeros(0), np.zeros(0))
    sections = cross_sections(gray, grid, points, headings, profile.half + SEARCH)
    template = profile.at(1 / STEP)
    t = template - template.mean()
    t_norm = float(np.sqrt((t * t).sum()))
    width = len(t)
    shifts = sections.shape[1] - width + 1
    windows = np.lib.stride_tricks.sliding_window_view(sections, width, axis=1)
    centred = windows - windows.mean(axis=2, keepdims=True)
    norms = np.sqrt((centred * centred).sum(axis=2)) * t_norm
    ncc = (centred @ t) / np.maximum(norms, 1e-6)
    best = np.argmax(ncc, axis=1)
    fraction = np.zeros(len(points))
    rows = np.arange(len(points))
    inner = (best > 0) & (best < shifts - 1)
    y0 = ncc[rows[inner], best[inner] - 1]
    y1 = ncc[rows[inner], best[inner]]
    y2 = ncc[rows[inner], best[inner] + 1]
    denominator = y0 - 2 * y1 + y2
    fraction[inner] = np.where(
        denominator < 0, 0.5 * (y0 - y2) / np.where(denominator < 0, denominator, -1), 0
    )
    offset = (best + fraction - (shifts - 1) / 2) * STEP
    return Refined(offset.astype(np.float64), ncc[rows, best].astype(np.float64))


def learn(
    gray: Floats, grid: Grid, points: Array, headings: Array, half: float, rail: float
) -> Profile | None:
    """The photo's own cross section, the average at the given track middles."""
    if not len(points):
        return None
    sections = cross_sections(gray, grid, points, headings, half)
    mean = sections.mean(axis=0)
    # Symmetric, as a track is.
    mean = (mean + mean[::-1]) / 2
    return Profile(mean.astype(np.float32), half, rail=rail, learned=True)


def across(heading: float) -> Array:
    """The unit vector to the right of a heading (y down)."""
    return np.array([-math.sin(heading), math.cos(heading)])


def strip_peaks(
    tracks: TrackMap, line_x: float, inward: float, y_range: tuple[float, float], gauge: float
) -> list[float]:
    """The tracks' positions across a gable, from the map in the strip just inside it: y in mm
    where the map, averaged along its own direction over the strip, has its peaks over
    TRACK_SCORE, at least 1,5 gauges apart."""
    lo, hi = GABLE_STRIP
    middle = line_x + inward * (lo + hi) / 2
    ys = np.arange(y_range[0], y_range[1], 0.5)
    centres = np.stack([np.full(len(ys), middle), ys], axis=1)
    _, theta = tracks.at(centres)
    ts = np.arange(-(hi - lo) / 2, (hi - lo) / 2 + 0.5, 1.0)
    points = (
        centres[:, None, :]
        + ts[None, :, None] * np.stack([np.cos(theta), np.sin(theta)], axis=1)[:, None, :]
    ).reshape(-1, 2)
    score, _ = tracks.at(points)
    profile = score.reshape(len(ys), len(ts)).mean(axis=1)
    found: list[float] = []
    for i in np.argsort(-profile):
        if profile[i] < TRACK_SCORE:
            break
        if not 0 < i < len(profile) - 1:
            continue
        if profile[i] < profile[i - 1] or profile[i] < profile[i + 1]:
            continue
        y = float(ys[i])
        if all(abs(y - other) >= 1.5 * gauge for other in found):
            found.append(y)
    return sorted(found)


REFINE_LIMIT = 2.5
"""How far a path's point may move to the track's middle, mm: further is another track."""
REFINE_SCORE = 0.4


def refine_path(gray: Floats, grid: Grid, xs: Array, ys: Array, profile: Profile) -> Array:
    """y along a path (x every mm) moved to the track's middle where the profile is clear, and
    smoothed: the columns' half millimetres become a fraction of one."""
    if len(xs) < 5:
        return ys
    from cad.bildkedjan.paths import headings, smoothed  # the paths use this module too

    heads = headings(xs, smoothed(ys, 3.0), 6.0)
    found = refine(gray, grid, np.stack([xs, ys], axis=1), heads, profile)
    good = (np.abs(found.shift) <= REFINE_LIMIT) & (found.score >= REFINE_SCORE)
    moved = ys + np.where(good, found.shift / np.maximum(np.cos(heads), 0.3), 0.0)
    # A median over five millimetres takes out the odd point that found the wrong rail.
    padded = np.pad(moved, 2, mode="edge")
    median = np.median(np.lib.stride_tricks.sliding_window_view(padded, 5), axis=1)
    return smoothed(median, 1.5)
