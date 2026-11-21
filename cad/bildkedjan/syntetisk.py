"""Synthetic module photos with a known truth, for the tests, the browser test and the
screenshots (#89 del c1). Nothing here is a real station: the modules are made up.

A scene is a module (a rectangle or a trapezoid) with its tracks as LINE and ARC centre lines in
the module's own millimetres (x from gable A along Kant 1, y away from Kant 1). It is drawn from
above as the photo chain expects a module to look: grass, ballast, light sleepers every
SLEEPER_SPACING mm and dark rails at the scale's gauge. The sleepers and the rails lie in a plane
of their own, RAIL_HEIGHT mm above the frame, as on a real module, so that a photo shows the
parallax the chain corrects for (bildkedjan step 6).

The photo is taken with a known camera: a focal length, a turn in the image, a tilt from the
vertical, and the lens's barrel distortion (the division model, as cad/bildkedjan/camera.py).
The light is uneven, a shadow from something outside the module falls over a corner, and the
pixels have noise. The JPEG has EXIF with a camera, a focal length and a GPS position, which
the intake must remove.

    python -m cad.bildkedjan.syntetisk station foto.jpg     # one photo to a file
"""

from __future__ import annotations

import io
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image

from cad import curves
from cad.bildkedjan.camera import Shape
from cad.curves import Line, Seg
from contracts.station_model import Point

SLEEPER_SPACING = 7.09
"""The sleeper spacing the photo test measured (lärdomarna, Rektangel), in mm."""
GAUGE = 16.5
RAIL_HEAD = 1.0
"""The rail head's width in H0, mm: the rails' centres lie GAUGE + RAIL_HEAD apart."""
RAIL_HEIGHT = 7.0
"""The rails' top above the frame, mm (bildkedjan step 6: cork, sleepers and rail, 5–8 mm)."""
SLEEPER_LENGTH = 28.0
SLEEPER_WIDTH = 2.6
BALLAST = 46.0
TEXTURE = 3.0
"""The scene's texture, in px per mm, before the camera sees it."""


Image3 = NDArray[Any]
Floats = NDArray[Any]


@dataclass(frozen=True)
class TrueSwitch:
    """A switch in the scene: its points, its radius, and the gable its diverging leg heads for."""

    at: Point
    radius: float
    toward: str


@dataclass(frozen=True)
class Scene:
    name: str
    length: float
    width_a: float
    width_b: float
    offset: float
    routes: list[list[Seg]]
    gables_a: list[float]
    gables_b: list[float]
    switches: list[TrueSwitch] = field(default_factory=list)
    crossings: list[Point] = field(default_factory=list)
    ends: list[Point] = field(default_factory=list)
    curve: tuple[float, float] | None = None
    """A curve module: Kant 1's radius and the angle, Kant 1 the outer edge (part c2)."""

    @property
    def kind(self) -> str:
        if self.curve is not None:
            return "curve"
        return "straight" if self.width_a == self.width_b and self.offset == 0 else "trapezoid"

    def shape(self) -> Shape:
        radius, angle = self.curve if self.curve is not None else (None, None)
        return Shape(self.kind, self.width_a, self.width_b, self.length, self.offset, radius, angle)

    @property
    def corners(self) -> list[Point]:
        """A at Kant 1, B at Kant 1, B far, A far."""
        return [(float(x), float(y)) for x, y in self.shape().corners(self.length, self.offset)]

    @property
    def outline(self) -> list[Point]:
        return [(float(x), float(y)) for x, y in self.shape().outline(self.length, self.offset)]


def route(start: Point, head_degrees: float, *parts: tuple[float, ...]) -> list[Seg]:
    """A track as a turtle draws it: ("line", length) is (length,), an arc is (radius, degrees),
    positive to the right (y down)."""
    segs: list[Seg] = []
    at, head = start, math.radians(head_degrees)
    for part in parts:
        if len(part) == 1:
            seg: Seg = curves.line_from(at, head, part[0])
        else:
            seg = curves.arc_turning(at, head, part[0], math.radians(part[1]))
        segs.append(seg)
        at, head = seg.end, curves.end_heading(seg)
    return segs


def to_x(segs: list[Seg], x: float) -> list[Seg]:
    """The route with its last straight lengthened or shortened to end at x."""
    last = segs[-1]
    assert isinstance(last, Line)
    head = curves.start_heading(last)
    run = (x - last.start[0]) / math.cos(head)
    return [*segs[:-1], curves.line_from(last.start, head, run)]


def straight_scene() -> Scene:
    """Raka spår: 1200 × 480, double track at MMM's 140 and 197 mm from Kant 1."""
    return Scene(
        name="Rak modul",
        length=1200,
        width_a=480,
        width_b=480,
        offset=0,
        routes=[route((0, 140), 0, (1200,)), route((0, 197), 0, (1200,))],
        gables_a=[140, 197],
        gables_b=[140, 197],
    )


def curve_scene() -> Scene:
    """En kurva: 1500 × 600, one track that leaves gable A at 180 mm, curves R 1500 out and back,
    and reaches gable B at 300 mm."""
    # The straight between the arcs is as long as it takes to reach 300 mm.
    first = route((0, 180), 0, (250,), (1500, 9))
    end_head = curves.end_heading(first[-1])
    rise = 120 - 2 * 1500 * (1 - math.cos(math.radians(9)))
    middle = rise / math.sin(end_head)
    track = route((0, 180), 0, (250,), (1500, 9), (middle,), (1500, -9), (250,))
    track = to_x(track, 1500)
    return Scene(
        name="Kurva",
        length=1500,
        width_a=600,
        width_b=600,
        offset=0,
        routes=[track],
        gables_a=[180],
        gables_b=[round(track[-1].end[1], 3)],
    )


def trapezoid_scene() -> Scene:
    """MMM:s trapets 685 × 480/280 with Kant 1 moved 131,5 mm, and the photo test's track: 140
    from Kant 1 at both gables, straight 64 – R 645 – straight 188 at 19° – R 645 – straight
    (lärdomarna, Ren geometri)."""
    track = route((0, 140), 0, (64,), (645, 19), (188,), (645, -19), (40,))
    track = to_x(track, 685)
    return Scene(
        name="Trapets",
        length=685,
        width_a=480,
        width_b=280,
        offset=131.5,
        routes=[track],
        gables_a=[140],
        gables_b=[round(track[-1].end[1] - 131.5, 3)],
    )


def station_scene() -> Scene:
    """En station, 1500 × 600: double track at 140 and 197, a crossover from track 1 to track 2
    (two switches R 830), a siding from track 2 (R 970) to a buffer stop, and a third track
    from gable A to gable B that crosses the siding."""
    t1 = route((0, 140), 0, (1500,))
    t2 = route((0, 197), 0, (1500,))
    # Crossover: from track 1 at x 120, R 830 to the right and back, onto track 2.
    half = math.degrees(math.acos(1 - 28.5 / 830))
    crossover = route((120, 140), 0, (830, half), (830, -half))
    # Siding: from track 2 at x 700, R 970 for 9,5° to the right, then straight to its end.
    siding = route((700, 197), 0, (970, 9.5), (1.0,))
    siding = to_x(siding, 1360)
    # Track 3: from gable A at 450 to gable B at 260, a straight that crosses the siding.
    t3 = route((0, 450), math.degrees(math.atan2(-190, 1500)), (math.hypot(1500, 190),))
    crossing = _intersection(siding[-1], t3[0])
    return Scene(
        name="Station",
        length=1500,
        width_a=600,
        width_b=600,
        offset=0,
        routes=[t1, t2, crossover, siding, t3],
        gables_a=[140, 197, 450],
        gables_b=[140, 197, 260],
        switches=[
            TrueSwitch((120, 140), 830, "B"),
            TrueSwitch(crossover[-1].end, 830, "A"),
            TrueSwitch((700, 197), 970, "B"),
        ],
        crossings=[crossing],
        ends=[siding[-1].end],
    )


def long_scene() -> Scene:
    """En lång modul, 2400 × 500, double track: for a photo in two parts (bildkedjan step 7)."""
    return Scene(
        name="Lång modul",
        length=2400,
        width_a=500,
        width_b=500,
        offset=0,
        routes=[route((0, 200), 0, (2400,)), route((0, 257), 0, (2400,))],
        gables_a=[200, 257],
        gables_b=[200, 257],
    )


def curve_module_scene() -> Scene:
    """En kurvmodul, 20° with Kant 1 outermost at R 2000 and 400 mm wide, double track at 140
    and 197 mm from Kant 1: arcs R 1860 and R 1803 from gable to gable. Its owner measures the
    chord 1860·2·sin 10° and the sagitta on track 1 (part c2)."""
    radius, angle, width = 2000.0, 20.0, 400.0
    tracks = [140.0, 197.0]
    return Scene(
        name="Kurvmodul",
        length=radius * math.radians(angle),
        width_a=width,
        width_b=width,
        offset=0,
        routes=[route((0, d), 0, (radius - d, angle)) for d in tracks],
        gables_a=tracks,
        gables_b=tracks,
        curve=(radius, angle),
    )


def curve_measure(scene: Scene) -> tuple[float, float]:
    """The chord and the sagitta on track 1 of a curve scene, as the owner measures them."""
    assert scene.curve is not None
    radius = scene.curve[0] - scene.gables_a[0]
    half = math.radians(scene.curve[1]) / 2
    return 2 * radius * math.sin(half), radius * (1 - math.cos(half))


SCENES = {
    "kurvmodul": curve_module_scene,
    "rak": straight_scene,
    "kurva": curve_scene,
    "trapets": trapezoid_scene,
    "station": station_scene,
    "lang": long_scene,
}


def _intersection(a: Seg, b: Seg) -> Point:
    assert isinstance(a, Line) and isinstance(b, Line)
    d1 = curves.sub(a.end, a.start)
    d2 = curves.sub(b.end, b.start)
    t = curves.cross(curves.sub(b.start, a.start), d2) / curves.cross(d1, d2)
    return curves.add(a.start, d1, t)


# --- The texture -------------------------------------------------------------------------


@dataclass(frozen=True)
class Texture:
    """The scene from above in TEXTURE px per mm: the board (z 0) and the track layer, which
    lies RAIL_HEIGHT mm higher, each with its alpha."""

    board: Image3
    board_alpha: NDArray[Any]
    tracks: Image3
    tracks_alpha: NDArray[Any]
    x0: float
    y0: float

    def pixel(self, x: Floats, y: Floats) -> tuple[Floats, Floats]:
        return (x - self.x0) * TEXTURE, (y - self.y0) * TEXTURE


def _noise(shape: tuple[int, int], rng: np.random.Generator, blur: float) -> NDArray[Any]:
    """Gaussian noise blurred by blur px, made small and enlarged when the blur is large."""
    if blur <= 2:
        found: NDArray[Any] = rng.standard_normal(shape).astype(np.float32)
        return cv2.GaussianBlur(found, (0, 0), blur) / 0.3 if blur > 0 else found
    factor = max(1, int(blur / 2))
    small: NDArray[Any] = rng.standard_normal((shape[0] // factor + 2, shape[1] // factor + 2))
    blurred: NDArray[Any] = cv2.GaussianBlur(small.astype(np.float32), (0, 0), blur / factor)
    blurred = blurred / max(float(blurred.std()), 1e-6)
    grown = cv2.resize(
        blurred, (shape[1] + 2 * factor, shape[0] + 2 * factor), interpolation=cv2.INTER_LINEAR
    )
    return np.ascontiguousarray(grown[: shape[0], : shape[1]])


def _poly(points: Sequence[Point], x0: float, y0: float) -> NDArray[Any]:
    return np.array(
        [[round((x - x0) * TEXTURE * 16), round((y - y0) * TEXTURE * 16)] for x, y in points],
        dtype=np.int32,
    )


def texture(scene: Scene, seed: int = 7) -> Texture:
    rng = np.random.default_rng(seed)
    margin = 12.0
    x0, y0 = -margin, min(0.0, scene.offset) - margin
    width = round((scene.length + 2 * margin) * TEXTURE)
    bottom = max(scene.width_a, scene.offset + scene.width_b) + margin
    if scene.curve is not None:
        hull = np.array(scene.outline)
        x0 = float(hull[:, 0].min()) - margin
        y0 = float(hull[:, 1].min()) - margin
        width = round((float(hull[:, 0].max()) + margin - x0) * TEXTURE)
        bottom = float(hull[:, 1].max()) + margin
    height = round((bottom - y0) * TEXTURE)
    shape = (height, width)
    outline = scene.outline
    # The board: grass with patches, and the frame's edge darker.
    grass: NDArray[Any] = np.zeros((*shape, 3), np.float32)
    base = np.array([62, 104, 72], np.float32)  # BGR, a muted green
    patches = _noise(shape, rng, 25 * TEXTURE)[..., None]
    fine = _noise(shape, rng, 0.8)[..., None]
    grass[:] = base + patches * np.array([8, 14, 10]) + fine * 10
    alpha = np.zeros(shape, np.uint8)
    cv2.fillPoly(alpha, [_poly(outline, x0, y0)], 255, cv2.LINE_AA, shift=4)
    edge: NDArray[Any] = np.zeros(shape, np.uint8)
    cv2.polylines(edge, [_poly(outline, x0, y0)], True, 255, round(6 * TEXTURE), cv2.LINE_AA, 4)
    grass = grass * (1 - edge[..., None] / 255.0 * 0.45)
    # Ballast under every track, on the board.
    ballast = np.zeros(shape, np.uint8)
    for segs in scene.routes:
        points = curves.sample_path(segs, 1.0)
        cv2.polylines(
            ballast,
            [_poly(points, x0, y0)],
            False,
            255,
            round(BALLAST * TEXTURE),
            cv2.LINE_AA,
            4,
        )
    ballast_colour = np.array([168, 172, 176], np.float32) + _noise(shape, rng, 0.7)[..., None] * 18
    b = (ballast.astype(np.float32) / 255.0)[..., None]
    board = grass * (1 - b) + ballast_colour * b
    # The track layer: sleepers and rails.
    tracks: NDArray[Any] = np.zeros((*shape, 3), np.float32)
    talpha: NDArray[Any] = np.zeros(shape, np.uint8)
    sleeper = np.array([196, 200, 204], np.float32)
    sleepers = np.zeros(shape, np.uint8)
    rails = np.zeros(shape, np.uint8)
    half = (GAUGE + RAIL_HEAD) / 2
    for segs in scene.routes:
        total = curves.path_length(segs)
        count = int(total / SLEEPER_SPACING)
        for k in range(count + 1):
            s = min(total, k * SLEEPER_SPACING + SLEEPER_SPACING / 2)
            c = curves.path_point(segs, s)
            h = curves.path_heading(segs, s)
            u, n = curves.unit(h), curves.unit(h + math.pi / 2)
            corners = [
                curves.add(curves.add(c, u, sx * SLEEPER_WIDTH / 2), n, sy * SLEEPER_LENGTH / 2)
                for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
            ]
            cv2.fillConvexPoly(sleepers, _poly(corners, x0, y0), 255, cv2.LINE_AA, 4)
        points = curves.sample_path(segs, 0.5)
        for side in (-1, 1):
            line = [
                curves.add(p, curves.unit(curves.path_heading(segs, s) + math.pi / 2), side * half)
                for p, s in zip(points, np.linspace(0, total, len(points)), strict=True)
            ]
            cv2.polylines(
                rails, [_poly(line, x0, y0)], False, 255, round(RAIL_HEAD * TEXTURE), cv2.LINE_AA, 4
            )
    for end in scene.ends:
        cv2.circle(
            sleepers,
            (round((end[0] - x0) * TEXTURE), round((end[1] - y0) * TEXTURE)),
            round(6 * TEXTURE),
            255,
            -1,
        )
    s_a = sleepers.astype(np.float32)[..., None] / 255.0
    r_a = rails.astype(np.float32)[..., None] / 255.0
    rail_colour = np.array([58, 56, 54], np.float32)
    tracks = sleeper * s_a * (1 - r_a) + rail_colour * r_a
    talpha = np.maximum(sleepers, rails).astype(np.float32) / 255.0
    tracks = np.where(talpha[..., None] > 0, tracks / np.maximum(talpha[..., None], 1e-6), 0)
    return Texture(
        board=np.clip(board, 0, 255).astype(np.uint8),
        board_alpha=alpha.astype(np.float32) / 255.0,
        tracks=np.clip(tracks, 0, 255).astype(np.uint8),
        tracks_alpha=talpha.astype(np.float32),
        x0=x0,
        y0=y0,
    )


# --- The camera --------------------------------------------------------------------------


@dataclass(frozen=True)
class Shot:
    """How the photo is taken."""

    size: tuple[int, int] = (4000, 3000)
    focal_35mm: float = 26.0
    turn: float = 8.0
    """The module's turn in the image, degrees."""
    tilt: float = 10.0
    """The camera's tilt from looking straight down, degrees."""
    tilt_toward: float = 30.0
    """Which way it tilts, degrees in the module's plane."""
    fill: float = 0.82
    """How much of the image's width the module's long side fills."""
    distortion: float = -0.02
    """The division model's λ: barrel for negative, in units of the focal length squared."""
    noise: float = 2.5
    shadow: bool = True
    light: bool = True
    cast: float = 0.0
    """A shadow the module casts on the floor beside its far long side, mm wide: the floor's
    own colour, darker and warmer, as the reference photos show it (part c5)."""
    rounded: float = 0.0
    """The board's corners rounded off with this radius, mm (part c5)."""
    centre: Point = (0.5, 0.5)
    """Where in the module the camera looks, as a share of its length and width."""
    seed: int = 11


CURVE_SHOT = Shot(distortion=0.0)
"""A curve module's photo: the phone has taken out its lens's distortion, as phones do. The
chain finds the lens from the module's straight edges, and a curve module's long sides are
arcs."""


@dataclass(frozen=True)
class Photo:
    """A synthetic photo and its truth."""

    jpeg: bytes
    pixels: Image3
    corners: list[Point]
    """The module's corners in the photo, in px: A at Kant 1, B at Kant 1, B far, A far."""
    focal: float
    distortion: float
    height: float
    tilt: float


def focal_px(size: tuple[int, int], focal_35mm: float) -> float:
    return focal_35mm / 43.27 * math.hypot(*size)


def _rotation(turn: float, tilt: float, toward: float) -> NDArray[Any]:
    """World to camera: looking down +z, turned in the image, then tilted."""
    c, s = math.cos(math.radians(turn)), math.sin(math.radians(turn))
    rz = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], np.float64)
    axis = np.array([math.cos(math.radians(toward)), math.sin(math.radians(toward)), 0.0])
    angle = math.radians(tilt)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    tilt_m = np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * (k @ k)
    found: NDArray[Any] = rz @ tilt_m
    return found


def distort(points: NDArray[Any], centre: Point, f: float, lam: float) -> NDArray[Any]:
    """Undistorted px to the photo's px, the division model's inverse."""
    if lam == 0:
        return points
    d = (points - np.array(centre)) / f
    ru = np.hypot(d[:, 0], d[:, 1])
    rd = np.where(
        ru > 1e-12,
        (1 - np.sqrt(np.maximum(0.0, 1 - 4 * lam * ru * ru))) / (2 * lam * np.maximum(ru, 1e-12)),
        0.0,
    )
    scale = np.where(ru > 1e-12, rd / np.maximum(ru, 1e-12), 1.0)
    found: NDArray[Any] = np.array(centre) + d * scale[:, None] * f
    return found


def take(scene: Scene, shot: Shot | None = None, tex: Texture | None = None) -> Photo:
    """The photo of the scene from the shot's camera."""
    shot = shot or Shot()
    tex = tex or texture(scene)
    w, h = shot.size
    f = focal_px(shot.size, shot.focal_35mm)
    cx, cy = w / 2, h / 2
    k = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1]], np.float64)
    r = _rotation(shot.turn, shot.tilt, shot.tilt_toward)
    width = max(scene.width_a, scene.offset + scene.width_b) - min(0.0, scene.offset)
    target = np.array(
        [
            scene.length * shot.centre[0],
            min(0.0, scene.offset) + width * shot.centre[1],
            0.0,
        ]
    )
    # The distance that makes the module fill the share of the image asked for.
    distance = f * scene.length / (shot.fill * w)
    axis = r.T @ np.array([0.0, 0.0, 1.0])
    camera = target - distance * axis
    t = -r @ camera
    # Every pixel of the photo: undistorted, then a ray to each plane.
    us, vs = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    dx, dy = (us - cx) / f, (vs - cy) / f
    if shot.distortion:
        shrink = 1 / (1 + shot.distortion * (dx * dx + dy * dy))
        dx, dy = dx * shrink, dy * shrink
    rt = r.astype(np.float32)
    # The ray in the world is R^T · (dx, dy, 1).
    rays = [rt[0, i] * dx + rt[1, i] * dy + rt[2, i] for i in range(3)]
    layers: list[tuple[NDArray[Any], NDArray[Any]]] = []
    for z, image, alpha in (
        (0.0, tex.board, tex.board_alpha),
        (-RAIL_HEIGHT, tex.tracks, tex.tracks_alpha),
    ):
        lam = (np.float32(z - camera[2])) / rays[2]
        x = np.float32(camera[0]) + lam * rays[0]
        y = np.float32(camera[1]) + lam * rays[1]
        mx, my = tex.pixel(x, y)
        colour = cv2.remap(image, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        a = cv2.remap(alpha, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        layers.append((colour.astype(np.float32), a.astype(np.float32)))
    # The floor, 20 mm under the frame: planks of wood.
    lam = np.float32(20.0 - camera[2]) / rays[2]
    fx = np.float32(camera[0]) + lam * rays[0]
    fy = np.float32(camera[1]) + lam * rays[1]
    rng = np.random.default_rng(shot.seed)
    plank = np.floor((fy + 37) / 140)
    grain = np.sin(fx / 9 + plank * 1.7) * 0.5 + np.sin(fx / 2.3 + fy / 31) * 0.25
    tone = 0.85 + 0.15 * np.sin(plank * 2.1)
    floor = (
        np.stack([110 + 18 * grain, 160 + 22 * grain, 196 + 20 * grain], axis=-1) * tone[..., None]
    )
    seams = (np.abs(((fy + 37) % 140) - 0.5) < 1.2)[..., None]
    floor = np.where(seams, floor * 0.6, floor).astype(np.float32)
    (board, board_a), (tracks, tracks_a) = layers
    if shot.cast > 0 and scene.curve is None:
        # The module's own shadow on the floor beside its far side: darker, the wood's colour
        # deeper (light from the floor around it), as smooth as the floor.
        far = max(scene.width_a, scene.offset + scene.width_b)
        inside = ((fy > far) & (fy < far + shot.cast) & (fx > 0) & (fx < scene.length)).astype(
            np.float32
        )
        inside = cv2.GaussianBlur(inside, (0, 0), 1.0)[..., None]
        floor = floor * (1 - inside) + floor * np.array([0.2, 0.28, 0.4], np.float32) * inside
    if shot.rounded > 0 and scene.curve is None:
        # The board's corners rounded off: the floor shows there.
        lam0 = np.float32(-camera[2]) / rays[2]
        bx = np.float32(camera[0]) + lam0 * rays[0]
        by = np.float32(camera[1]) + lam0 * rays[1]
        radius = np.float32(shot.rounded)
        cut = np.zeros_like(board_a, dtype=bool)
        for cx, cy in scene.corners:
            sx = 1.0 if cx <= 0 else -1.0
            sy = 1.0 if cy <= 0 else -1.0
            u = (bx - np.float32(cx)) * np.float32(sx)
            v = (by - np.float32(cy)) * np.float32(sy)
            cut |= (u < radius) & (v < radius) & ((radius - u) ** 2 + (radius - v) ** 2 > radius**2)
        board_a = np.where(cut, 0.0, board_a).astype(np.float32)
        tracks_a = np.where(cut, 0.0, tracks_a).astype(np.float32)
    out = floor * (1 - board_a[..., None]) + board * board_a[..., None]
    out = out * (1 - tracks_a[..., None]) + tracks * tracks_a[..., None]
    if shot.light:
        gradient = 0.82 + 0.28 * (us / w) + 0.08 * np.sin(vs / h * 3.1)
        out *= gradient[..., None].astype(np.float32)
    if shot.shadow:
        # Something outside the module throws a soft shadow over its corner at B and Kant 1,
        # with an edge that runs slantwise over the tracks.
        lam = np.float32(-camera[2]) / rays[2]
        bx = np.float32(camera[0]) + lam * rays[0]
        by = np.float32(camera[1]) + lam * rays[1]
        width = max(scene.width_a, scene.width_b)
        inside = ((bx - 0.72 * scene.length) > 1.6 * (by - 0.1 * width)).astype(np.float32)
        inside = cv2.GaussianBlur(inside, (0, 0), 6)
        out *= (1 - 0.42 * inside)[..., None]
    out += rng.standard_normal(out.shape, dtype=np.float32) * np.float32(shot.noise)
    pixels = np.clip(out, 0, 255).astype(np.uint8)
    corners_world = np.array([[x, y, 0.0] for x, y in scene.corners])
    cam = (r @ corners_world.T).T + t
    projected = (k @ cam.T).T
    undistorted = projected[:, :2] / projected[:, 2:3]
    corners_px = distort(undistorted, (cx, cy), f, shot.distortion)
    tilt = math.degrees(math.acos(abs(float(r[2, 2]))))
    return Photo(
        jpeg=jpeg_with_exif(pixels, shot.focal_35mm),
        pixels=pixels,
        corners=[(float(x), float(y)) for x, y in corners_px],
        focal=f,
        distortion=shot.distortion,
        height=float(abs(camera[2])),
        tilt=tilt,
    )


def jpeg_with_exif(pixels: Image3, focal_35mm: float, quality: int = 92) -> bytes:
    """The pixels as a phone writes them: JPEG with the camera, the focal length, the time and a
    GPS position in its EXIF. The position is made up."""
    image = Image.fromarray(cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB))
    exif = Image.Exif()
    exif[0x010F] = "Provtelefon"  # Make
    exif[0x0110] = "Syntetisk 1"  # Model
    exif[0x0132] = "2026:11:19 12:58:00"  # DateTime
    exif[0x0112] = 1  # Orientation
    sub = exif.get_ifd(0x8769)
    sub[0xA405] = round(focal_35mm)  # FocalLengthIn35mmFilm
    sub[0x920A] = round(focal_35mm / 7.0, 2)  # FocalLength
    sub[0xA434] = "Provobjektiv 26 mm"  # LensModel
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (57.0, 42.0, 12.5)
    gps[3] = "E"
    gps[4] = (11.0, 58.0, 3.25)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality, exif=exif.tobytes())
    return out.getvalue()


# --- A hand-drawn sketch (profile Skiss, part c2) ----------------------------------------------


@dataclass(frozen=True)
class Sketch:
    """A synthetic sketch and its truth, in the first frame's module mm."""

    jpeg: bytes
    pixels: Image3
    frames: list[list[Point]]
    """Each frame's corners on the sheet, px: A at Kant 1, B at Kant 1, B far, A far."""
    length: float
    width: float
    switches: list[Point]
    crossings: list[Point]
    gables_a: list[float]
    gables_b: list[float]


SKETCH_PX = 0.55
"""The sketch's scale on the sheet, px per mm: a scan of a hand drawing at 2200 px."""
SKETCH_ORIGIN: Point = (160.0, 520.0)


def sketch_routes() -> list[list[Seg]]:
    """The first frame's tracks, 1500 × 600: double track at 150 and 250; a crossover from track
    2 at 150 up to track 1 (two switches, R 1000); a siding from track 2 at 900 back toward
    gable A, R 900, to its end; and a track from inside the module crossing both main tracks,
    from one end to another (two crossings)."""
    t1 = route((0, 150), 0, (1500,))
    t2 = route((0, 250), 0, (1500,))
    half = math.degrees(math.acos(1 - 50 / 1000))
    crossover = route((150, 250), 0, (1000, -half), (1000, half))
    siding = route((900, 250), 180, (900, -14), (1.0,))
    siding = [*siding[:-1], curves.line_from(siding[-2].end, curves.end_heading(siding[-2]), 260)]
    diagonal: list[Seg] = [curves.Line((950.0, 560.0), (1350.0, 60.0))]
    second = [route((1500, 150), 0, (1500,)), route((1500, 250), 0, (1500,))]
    second.append(route((2000, 250), 0, (1100, 9.0), (1.0,)))
    return [t1, t2, crossover, siding, diagonal, *second]


def sketch(seed: int = 5, photographed: bool = False) -> Sketch:
    """Two module frames drawn by hand on a sheet: thin frame lines, thick black tracks,
    coloured pencil, pencil text in Norwegian with leader lines across the tracks."""
    rng = np.random.default_rng(seed)
    w, h = 2200, 1555
    k = SKETCH_PX
    ox, oy = SKETCH_ORIGIN
    sheet = np.full((h, w, 3), 252, np.float32)
    sheet += rng.standard_normal((h, w, 1)).astype(np.float32) * 2

    def px(p: Point) -> tuple[int, int]:
        return round(ox + p[0] * k), round(oy + p[1] * k)

    canvas = np.clip(sheet, 0, 255).astype(np.uint8)
    # Coloured pencil: grass along the sides and brown ballast, in strokes.
    for _ in range(900):
        x = rng.uniform(0, 3000)
        y = float(rng.choice([rng.uniform(10, 110), rng.uniform(170, 230), rng.uniform(330, 590)]))
        colour = (70, 170, 80) if y < 120 or y > 420 else (70, 100, 150)
        a = px((x, y))
        b = (a[0] + int(rng.integers(-18, 18)), a[1] + int(rng.integers(-6, 6)))
        cv2.line(canvas, a, b, colour, 1, cv2.LINE_AA)
    # The frames: two modules, 1500 × 600 each, thin black lines.
    frames = []
    for left in (0.0, 1500.0):
        corners = [(left, 0.0), (left + 1500.0, 0.0), (left + 1500.0, 600.0), (left, 600.0)]
        frames.append([(float(px(c)[0]), float(px(c)[1])) for c in corners])
        cv2.polylines(canvas, [np.array([px(c) for c in corners])], True, (30, 30, 30), 2)
    # The tracks: thick black ink.
    for segs in sketch_routes():
        points = curves.sample_path(segs, 4.0)
        cv2.polylines(canvas, [np.array([px(p) for p in points])], False, (25, 25, 25), 9)
    # Text in pencil, with leader lines across the tracks.
    for text, at, to in (
        ("BEITEMARK MED KUER", (300.0, -180.0), (400.0, 60.0)),
        ("GAMLE SKINNER", (700.0, 720.0), (640.0, 200.0)),
        ("SKOG", (2300.0, -160.0), (2250.0, 300.0)),
        ("HVILEBOD FOR RENGJORINGS PERSONALE", (1300.0, 760.0), (1100.0, 230.0)),
    ):
        cv2.putText(canvas, text, px(at), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (120, 120, 120), 2)
        cv2.line(canvas, px(at), px(to), (135, 135, 135), 1, cv2.LINE_AA)
    cv2.putText(
        canvas, "#1", px((2900.0, 680.0)), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (110, 110, 110), 2
    )
    pixels = canvas
    if photographed:
        # The sheet photographed on a table: a turn, a tilt, a darker surround.
        big = np.full((h + 500, w + 500, 3), (70, 95, 125), np.uint8)
        src = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32)
        dst = np.array([[250, 220], [w + 240, 280], [w + 280, h + 300], [210, h + 240]], np.float32)
        matrix = cv2.getPerspectiveTransform(src, dst)
        warped = cv2.warpPerspective(canvas, matrix, (w + 500, h + 500), borderValue=(0, 0, 0))
        cover = cv2.warpPerspective(np.full((h, w), 255, np.uint8), matrix, (w + 500, h + 500))
        big[cover > 0] = warped[cover > 0]
        pixels = big
        frames = [
            [
                (float(q[0]), float(q[1]))
                for q in cv2.perspectiveTransform(np.array([f], np.float32), matrix)[0]
            ]
            for f in frames
        ]
    ok, data = cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok
    half = math.degrees(math.acos(1 - 50 / 1000))
    x_end = 150 + 2 * 1000 * math.sin(math.radians(half))
    return Sketch(
        jpeg=data.tobytes(),
        pixels=pixels,
        frames=frames,
        length=1500.0,
        width=600.0,
        switches=[(150.0, 250.0), (x_end, 150.0), (900.0, 250.0)],
        crossings=[(950 + 400 * (310 / 500), 250.0), (950 + 400 * (410 / 500), 150.0)],
        gables_a=[150.0, 250.0],
        gables_b=[150.0, 250.0],
    )


@dataclass(frozen=True)
class DepotSketch:
    """A sketch like the reference depot's module 12 (part c5), and its truth."""

    jpeg: bytes
    pixels: Image3
    frame: list[Point]
    """The frame's corners on the sheet, px, where its lines cross: A at Kant 1, B at Kant 1, B
    far, A far (the corner A far is cut)."""
    switches: int
    """Code's reading: the wedge where track 3 runs into track 2 at the bridge, and the track
    parting under it."""


def depot_sketch(seed: int = 9) -> DepotSketch:
    """One module, 1500 × 700, its frame in faint pencil with the corner at A far cut and
    coloured pencil over it in places; track 1 straight at 150; tracks 2 and 3 from gable A at
    300 and 420, track 3 running into track 2 (their ink a wedge) at the left side of a bridge
    drawn over the tracks (two thin dark lines 120 mm apart, hatched), and under the bridge a
    track parting from track 2 at 15°, to gable B at 548."""
    rng = np.random.default_rng(seed)
    w, h = 2200, 1555
    k = SKETCH_PX
    ox, oy = SKETCH_ORIGIN

    def px(p: Point) -> tuple[int, int]:
        return round(ox + p[0] * k), round(oy + p[1] * k)

    sheet = np.full((h, w, 3), 252, np.float32)
    sheet += rng.standard_normal((h, w, 1)).astype(np.float32) * 2
    canvas = np.clip(sheet, 0, 255).astype(np.uint8)
    for _ in range(700):
        x = rng.uniform(0, 1500)
        y = float(rng.choice([rng.uniform(-30, 100), rng.uniform(600, 690)]))
        a = px((x, y))
        b = (a[0] + int(rng.integers(-18, 18)), a[1] + int(rng.integers(-6, 6)))
        cv2.line(canvas, a, b, (70, 170, 80), 1, cv2.LINE_AA)
    # The frame in faint pencil, its corner at A far cut.
    outline = [(0.0, 0.0), (1500.0, 0.0), (1500.0, 700.0), (140.0, 700.0), (0.0, 560.0)]
    cv2.polylines(canvas, [np.array([px(p) for p in outline])], True, (172, 172, 172), 2)
    # Coloured pencil over the frame's line in places.
    for x in np.arange(300.0, 700.0, 9.0):
        a = px((float(x), -6.0))
        cv2.line(canvas, a, (a[0] + 4, a[1] + 7), (60, 160, 90), 1, cv2.LINE_AA)
    track1 = route((0, 150), 0, (1500,))
    half = math.degrees(2 * math.atan(120 / 585))
    radius = 585 / (2 * math.sin(math.radians(half)))
    track2 = route((0, 300), 0, (1500,))
    track3 = route((0, 420), 0, (radius, -half), (radius, half))
    slope = math.radians(15)
    parting = [curves.Line((575.0, 300.0), (1500.0, 300.0 + 925.0 * math.tan(slope)))]
    for segs in (track1, track2, track3, parting):
        points = curves.sample_path(segs, 4.0)
        cv2.polylines(canvas, [np.array([px(p) for p in points])], False, (25, 25, 25), 9)
    # The bridge: 120 mm wide at 60° to the tracks, hatched, over them.
    centre = np.array([600.0, 350.0])
    along = np.array([0.5, -math.sqrt(3) / 2])
    normal = np.array([math.sqrt(3) / 2, 0.5])
    ends = [centre + t * along for t in (-430.0, 430.0)]
    band = [
        ends[0] - 60 * normal,
        ends[1] - 60 * normal,
        ends[1] + 60 * normal,
        ends[0] + 60 * normal,
    ]
    cv2.fillPoly(
        canvas, [np.array([px((float(p[0]), float(p[1]))) for p in band])], (214, 214, 214)
    )
    for t in np.arange(-420.0, 420.0, 14.0):
        a = centre + t * along - 58 * normal
        b = centre + t * along + 58 * normal
        cv2.line(
            canvas,
            px((float(a[0]), float(a[1]))),
            px((float(b[0]), float(b[1]))),
            (160, 160, 160),
            1,
            cv2.LINE_AA,
        )
    for side in (-60.0, 60.0):
        first = ends[0] + side * normal
        last = ends[1] + side * normal
        cv2.line(
            canvas,
            px((float(first[0]), float(first[1]))),
            px((float(last[0]), float(last[1]))),
            (60, 60, 60),
            2,
            cv2.LINE_AA,
        )
    # Text in pencil, a leader line across the tracks.
    cv2.putText(
        canvas, "BRU", px((900.0, -150.0)), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (120, 120, 120), 2
    )
    cv2.line(canvas, px((900.0, -150.0)), px((640.0, 330.0)), (135, 135, 135), 1, cv2.LINE_AA)
    ok, data = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok
    frame = [(0.0, 0.0), (1500.0, 0.0), (1500.0, 700.0), (0.0, 700.0)]
    return DepotSketch(
        jpeg=data.tobytes(),
        pixels=canvas,
        frame=[(float(px(p)[0]), float(px(p)[1])) for p in frame],
        switches=2,
    )


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "skiss":
        with open(argv[2], "wb") as file:
            file.write(sketch().jpeg)
        return 0
    if len(argv) != 3 or argv[1] not in SCENES:
        print(
            f"python -m cad.bildkedjan.syntetisk {{{','.join(SCENES)},skiss}} foto.jpg",
            file=sys.stderr,
        )
        return 2
    photo = take(SCENES[argv[1]](), CURVE_SHOT if argv[1] == "kurvmodul" else None)
    with open(argv[2], "wb") as file:
        file.write(photo.jpeg)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
