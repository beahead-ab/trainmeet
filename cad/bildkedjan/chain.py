"""The photo chain, profile Modulfoto (bildkedjan steps 2–13 and 15; step 14, the landscape,
is part d, and step 1, the phone's guidance, is #90).

Three stages, so the job can stop between them, store what it has and go on later:

1. prepare(): the intake of each photo (step 2), several photos stitched into one (step 7), and
   the module's corners found (step 4). The owner confirms the corners and marks Kant 1, and with
   it gable A, on the photo: in a photo from above, walking from gable A along Kant 1, the module
   lies to the right, so Kant 1 decides gable A.
2. measure(): the lens and the camera (step 5), the quality gate (step 3), the measuring image in
   the rails' plane (steps 6 and 8), the track map (step 10), the gables' tracks and the ends
   inside the module, and the cheapest path between every pair of them (the code's topology,
   step 11). What the AI is asked comes from here (cad/bildkedjan/questions.py).
3. assemble(): with the connections decided (the code's, the AI's or the owner's), the network
   and the drawing (step 12), the gables measured from Kant 1 (step 13), the scale and the
   control measures with a computed ± (step 9), and the checks and questions (step 15).

Reproducible (bildkedjan, Reproducerbarhet): the same photos, the same input and the same
versions give the same result; RANSAC, k-means, GrabCut and the uncertainty have fixed seeds,
and OpenCV runs on one thread in the measuring steps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from cad import curves, switches
from cad.bildkedjan import arcs, measures, network, paths, rectify, stitch, trackmap
from cad.bildkedjan import camera as cam
from cad.bildkedjan import corners as corners_
from cad.bildkedjan.build import Built, build
from cad.bildkedjan.camera import Array, Camera
from cad.bildkedjan.intake import Intake
from cad.bildkedjan.paths import Path, Terminal
from cad.bildkedjan.rectify import Grid
from cad.editor import Drawing
from contracts.cad import Certainty, GableEnd, Scale


def _array(values: Array) -> list[list[float]]:
    return [[round(float(v), 4) for v in row] for row in np.atleast_2d(values)]


CHAIN_VERSION = "3.1.0"
"""The measuring code's version: part of every job's key (bildkedjan, Jobbet är nyckeln)."""
PROFILE = "modulfoto"
RAIL_HEIGHT = {Scale.H0: 7.0, Scale.N: 4.0, Scale.ZERO: 14.0}
"""The rails' top over the frame, mm: bildkedjan step 6's example for H0 (cork, sleepers and
rail, 5–8 mm), scaled by the gauge; a starting value until the norms give theirs."""
RAIL_HEAD = {Scale.H0: 1.0, Scale.N: 0.55, Scale.ZERO: 1.9}
"""A rail head's width, mm: the rails' middles lie a gauge plus this apart (an assumption)."""
CORNER_SIGMA_OWNER = 1.5
"""How well an owner places a corner, px."""
GABLE_FIT_MM = (3.0, 60.0)
"""The stretch at a gable the track's position from Kant 1 is measured over."""
CURVE_FIT_MM = (3.0, 150.0)
"""On a curve module, where the tracks are arcs about the curve's centre and cross the gables
square, the track's distance from Kant 1 is measured about that centre over this stretch: a
longer stretch than a straight module's, so that a few millimetres the measuring image bends
at the very gable do not decide it (part c5)."""


def version_key() -> dict[str, str]:
    """The versions in a job's key: the chain's and its libraries' (bildkedjan, Koden är låst)."""
    return {"kedjan": CHAIN_VERSION, "opencv": cv2.__version__, "numpy": np.__version__}


def steady() -> None:
    """Fixed seeds and one thread for the measuring steps."""
    cv2.setNumThreads(1)
    cv2.setRNGSeed(89)


# --- 1. Prepare -----------------------------------------------------------------------------


@dataclass
class Prepared:
    pixels: NDArray[Any]
    focal_35mm: float | None
    size: tuple[int, int]
    """The first photo's size: its camera is the mosaic's."""
    origin: tuple[float, float]
    """Where the first photo's (0, 0) lies in pixels."""
    found: corners_.Found | None
    photos: int
    mosaic: stitch.Mosaic | None = None
    lens: float = 0.0
    """The lens's k, from the module's edges (one photo)."""

    @property
    def corners(self) -> Array | None:
        """The corners to show the owner: where the sides cross with the lens taken out, put
        back in the photo's px."""
        if self.found is None:
            return None
        if self.lens == 0:
            return self.found.corners
        focal = cam.focal_from_35mm(self.size, self.focal_35mm)
        centre = (self.size[0] / 2 + self.origin[0], self.size[1] / 2 + self.origin[1])
        return corners_.through_lens(self.found, centre, focal, self.lens)


def prepare(
    intakes: list[Intake],
    curve: bool = False,
    aspect: float | None = None,
    bend: corners_.Bend | None = None,
) -> Prepared:
    """The photos as one, and the module's corners in it, if code finds them; a curve module's
    long sides as arcs (curve); a straight module's length over its width, when known, decides
    which edges are its sides (aspect, part c3), and a curve's shape its outline (bend, part
    c5)."""
    steady()
    first = intakes[0]
    if len(intakes) == 1:
        pixels = first.pixels
        origin = (0.0, 0.0)
        mosaic = None
    else:
        mosaic = stitch.stitch([i.pixels for i in intakes])
        pixels, origin = mosaic.pixels, mosaic.origin
    found = corners_.find(pixels, curve, aspect, bend)
    size = (first.width, first.height)
    lens = 0.0
    if found is not None and len(intakes) == 1 and len(found.sides) == 4:
        # A curve module's long sides are arcs: the lens makes them circles, the others lines.
        lens = cam.lens(
            found.sides,
            found.corners,
            size,
            cam.focal_from_35mm(size, first.focal_35mm),
            found.bent,
        )
    return Prepared(pixels, first.focal_35mm, size, origin, found, len(intakes), mosaic, lens)


def aspect_of(kind: str, width: float | None, length: float | None) -> float | None:
    """A straight module's length over its width, when both are known: what decides which
    edges in the photo are its sides (corners.find)."""
    if kind != "straight" or not width or not length:
        return None
    return float(length) / float(width)


def bend_of(
    kind: str,
    width: float | None,
    edge_radius: float | None,
    angle: float | None,
    edge: str = "outer",
    sides: str = "bent",
) -> corners_.Bend | None:
    """A curve module's outline from Kant 1's radius, which edge Kant 1 is, its width and its
    angle, when known and the box's long sides are bent (corners.find, part c5)."""
    if kind != "curve" or sides != "bent" or not width or not edge_radius or not angle:
        return None
    other = edge_radius - width if edge == "outer" else edge_radius + width
    if other <= 0:
        return None
    return corners_.Bend(max(edge_radius, other), min(edge_radius, other), float(angle))


def ordered(corners: Array, kant1: int, gable_a: int | None = None) -> Array:
    """The corners as the module's: A at Kant 1, B at Kant 1, B far, A far, from four clockwise
    corners, the side (i from corner i to i + 1) that is Kant 1 and the side that is gable A,
    one of the two beside Kant 1. Gable A before Kant 1 (side kant1 - 1) is the module seen from
    above, lying to the right of Kant 1 from gable A, as CAD draws it; gable A after Kant 1 is
    the module mirrored, as some stations measure theirs (bildkedjan step 4, Kant 1 och gavel A)."""
    clockwise = corners_.clockwise(np.asarray(corners, np.float64))
    if gable_a is None or gable_a == (kant1 + 3) % 4:
        return np.array([clockwise[(kant1 + k) % 4] for k in range(4)])
    if gable_a != (kant1 + 1) % 4:
        raise ValueError("Gavel A ligger bredvid Kant 1.")
    return np.array([clockwise[(kant1 + k) % 4] for k in (1, 0, 3, 2)])


def default_kant1(corners: Array) -> int:
    """A first guess for the view: the long side lowest in the photo is Kant 1."""
    c = corners_.clockwise(np.asarray(corners, np.float64))
    lengths = [float(np.linalg.norm(c[(i + 1) % 4] - c[i])) for i in range(4)]
    long_sides = sorted(range(4), key=lambda i: -lengths[i])[:2]
    return max(long_sides, key=lambda i: c[i][1] + c[(i + 1) % 4][1])


def default_gable_a(kant1: int) -> int:
    """Gable A as CAD draws a module: the side before Kant 1, clockwise."""
    return (kant1 + 3) % 4


# --- 2. Measure -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Setup:
    """What the owner gives: the scale, the form and the known measures, the corners (None:
    the ones code found), which side is Kant 1 and which gable A. A curve module comes with
    Kant 1's radius and the angle, from the owner's chord and sagitta (CAD16: exactly, without
    rounding), which edge Kant 1 is and whether the box's long sides are bent."""

    scale: Scale
    kind: str
    width_a: float
    width_b: float
    length: float | None = None
    offset: float | None = None
    corners: tuple[tuple[float, float], ...] | None = None
    kant1: int = 0
    rail_height: float | None = None
    gable_a: int | None = None
    radius: float | None = None
    """A curve's Kant 1 radius, mm."""
    angle: float | None = None
    edge: str = "outer"
    sides: str = "bent"

    @property
    def gable(self) -> int:
        return default_gable_a(self.kant1) if self.gable_a is None else self.gable_a

    @property
    def mirrored(self) -> bool:
        """Gable A after Kant 1: the module lies to the left of Kant 1 from gable A."""
        return self.gable != default_gable_a(self.kant1)

    def shape(self, length: float | None = None) -> cam.Shape:
        return cam.Shape(
            self.kind,
            self.width_a,
            self.width_b,
            self.length if length is None else length,
            self.offset,
            self.radius,
            self.angle,
            self.edge,
            self.sides,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "scale": self.scale.value,
            "kind": self.kind,
            "width_a": self.width_a,
            "width_b": self.width_b,
            "length": self.length,
            "offset": self.offset,
            "corners": [list(c) for c in self.corners] if self.corners else None,
            "kant1": self.kant1,
            "rail_height": self.rail_height,
            "gable_a": self.gable,
            "radius": self.radius,
            "angle": self.angle,
            "edge": self.edge,
            "sides": self.sides,
        }

    @classmethod
    def of(cls, data: dict[str, Any]) -> Setup:
        return cls(
            scale=Scale(data["scale"]),
            kind=data["kind"],
            width_a=float(data["width_a"]),
            width_b=float(data["width_b"]),
            length=data["length"],
            offset=data["offset"],
            corners=tuple(tuple(c) for c in data["corners"]) if data["corners"] else None,
            kant1=int(data["kant1"]),
            rail_height=data.get("rail_height"),
            gable_a=data.get("gable_a"),
            radius=data.get("radius"),
            angle=data.get("angle"),
            edge=data.get("edge", "outer"),
            sides=data.get("sides", "bent"),
        )


@dataclass
class Measured:
    """What stage 2 gives, all of it kept with the job so that stage 3 can run again on the
    owner's answers without measuring anew."""

    setup: Setup
    camera: Camera
    length: float
    offset: float
    corners: Array
    corner_sigma: float
    grid: Grid
    quality: measures.Quality
    terminals: list[Terminal]
    paths: list[Path]
    profile: trackmap.Profile
    rail_height: float
    size: tuple[int, int]
    """The first photo's size: its camera."""
    shift: tuple[float, float]
    """Where the first photo's (0, 0) lies in the mosaic."""
    stitch_mm: float | None = None
    photo_length: float | None = None
    """The photo's own length, also when the owner gave one: to compare them."""
    image: NDArray[Any] | None = field(default=None, repr=False)
    """The measuring image, MEASURE_PPM px per mm, in the rails' plane."""
    edges: arcs.Edges | None = None
    """A curve's long sides against their arcs (bildkedjan step 6, Kurvmodul)."""

    @property
    def shape(self) -> cam.Shape:
        return self.setup.shape(self.length)

    @property
    def outline(self) -> Array:
        """The board's outline in mm: four corners, or a curve's arcs."""
        return self.shape.outline(self.length, self.offset)

    def strips(self) -> list[trackmap.GableStrip]:
        return strips_of(self.shape, self.length, self.offset)

    def strip(self, gable: str) -> trackmap.GableStrip:
        return self.strips()[0 if gable == "A" else 1]

    def code_pairs(self) -> set[tuple[str, str]]:
        return {p.pair for p in self.paths if p.status == "track"}

    def gray(self) -> NDArray[Any]:
        assert self.image is not None
        return cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY).astype(np.float32)


class Stop(Exception):
    """The chain cannot go on with this photo: a gate refused it. The message says why."""


def strips_of(shape: cam.Shape, length: float, offset: float) -> list[trackmap.GableStrip]:
    """Gable A and gable B as lines in the module, seen from inside it."""
    c = shape.corners(length, offset)

    def unit(v: Array) -> tuple[float, float]:
        n = float(np.linalg.norm(v)) or 1.0
        return (float(v[0] / n), float(v[1] / n))

    if shape.curved:
        assert shape.angle is not None
        inward_a = unit(shape.point(0.0, 0.01) - shape.point(0.0, 0.0))
        inward_b = unit(shape.point(0.0, shape.angle - 0.01) - shape.point(0.0, shape.angle))
    else:
        inward_a, inward_b = (1.0, 0.0), (-1.0, 0.0)
    return [
        trackmap.GableStrip(
            (float(c[0][0]), float(c[0][1])), unit(c[3] - c[0]), inward_a, shape.width_a
        ),
        trackmap.GableStrip(
            (float(c[1][0]), float(c[1][1])), unit(c[2] - c[1]), inward_b, shape.width_b
        ),
    ]


def along_gable(strip: trackmap.GableStrip, point: tuple[float, float]) -> float:
    """How far along its gable from Kant 1 a point lies, mm."""
    return (point[0] - strip.corner[0]) * strip.along[0] + (
        point[1] - strip.corner[1]
    ) * strip.along[1]


def _gable_terminals(
    tracks: trackmap.TrackMap, strips: list[trackmap.GableStrip], gauge: float
) -> list[Terminal]:
    found: list[Terminal] = []
    for end, strip in zip(("A", "B"), strips, strict=True):
        peaks = trackmap.strip_peaks(tracks, strip, gauge)
        for n, v in enumerate(peaks, start=1):
            at = strip.points(np.array([v]), 0.0)[0]
            found.append(Terminal(f"{end}{n}", "gable", (float(at[0]), float(at[1])), end, n))
    return found


LEARN_DEPTH = 20.0
"""How far inside its gable a track's own cross section is learned, mm."""
MAP_FLOOR = 0.05
LIFT_PERCENTILE = 25.0
"""The map is lifted so that the weaker of the tracks it was learned from are clear too."""

"""The map's background is at least this, when one map is chosen over another by how clearly
its tracks stand out."""


def _learned(
    terminals: list[Terminal],
    tracks: trackmap.TrackMap,
    strips: list[trackmap.GableStrip],
    gray: NDArray[Any],
    grid: Grid,
    profile: trackmap.Profile,
) -> tuple[trackmap.Profile | None, Array]:
    """The photo's own cross section at the gables' tracks, and the tracks' middles there."""
    points, heads = [], []
    for t in terminals:
        if t.kind != "gable":
            continue
        strip = strips[0 if t.gable == "A" else 1]
        q = np.array(
            [[t.at[0] + strip.inward[0] * LEARN_DEPTH, t.at[1] + strip.inward[1] * LEARN_DEPTH]]
        )
        _, d = tracks.at(q)
        r = trackmap.refine(gray, grid, q, d, profile)
        points.append(q[0] + r.shift[0] * trackmap.across(float(d[0])))
        heads.append(float(d[0]))
    if not points:
        return None, np.zeros((0, 2))
    middles = np.array(points)
    learned = trackmap.learn(gray, grid, middles, np.array(heads), profile.half, profile.rail)
    return learned, middles


def measure(prepared: Prepared, setup: Setup) -> Measured:
    """The camera, the quality, the measuring image, the track map and the code's paths.

    A mirrored module (gable A after Kant 1) is measured as CAD draws it, with the ends
    swapped, and turned into the owner's frame afterwards (orient.reorient): the paths are
    traced from the same end whichever way the owner names the gables, so the same photo gives
    the same tracks and switches whichever gable is A."""
    if setup.mirrored:
        from cad.bildkedjan import orient

        plain = replace(
            setup,
            gable_a=default_gable_a(setup.kant1),
            width_a=setup.width_b,
            width_b=setup.width_a,
            offset=-setup.offset if setup.offset is not None else None,
        )
        return orient.reorient(_measure(prepared, plain), setup.kant1, setup.gable).measured
    return _measure(prepared, setup)


def _measure(prepared: Prepared, setup: Setup) -> Measured:
    steady()
    pixels = prepared.pixels
    size = prepared.size
    focal = cam.focal_from_35mm(size, prepared.focal_35mm)
    # The camera's centre is the first photo's middle, wherever it lies in a mosaic.
    centre_shift = np.array(prepared.origin)
    if setup.corners is not None:
        given = np.array(setup.corners, np.float64)
        sigma = CORNER_SIGMA_OWNER
        k = prepared.lens
        corners = ordered(given, setup.kant1, setup.gable)
    else:
        if prepared.found is None:
            raise Stop("Modulens hörn hittades inte. Dra hörnen till rätt plats i fotot.")
        found = prepared.found
        k = prepared.lens
        through = prepared.corners
        assert through is not None
        # A corner is where two fitted sides cross: much surer than a single edge point.
        counts = [max(1, len(side)) for side in found.sides] or [1]
        sigma = max(0.3, float(np.mean(found.residuals)) / math.sqrt(min(counts) / 4))
        corners = ordered(through, setup.kant1, setup.gable)
    shape = setup.shape()
    local = corners - centre_shift
    camera, length, offset = cam.solve(local, shape, size, focal, k)
    photo_length = length
    if setup.length is not None and not shape.curved:
        free = cam.Shape(setup.kind, setup.width_a, setup.width_b, None, setup.offset)
        _, photo_length, _ = cam.solve(local, free, size, focal, k)
    camera = _shifted(camera, centre_shift)
    shape = setup.shape(length)
    outline = shape.outline(length, offset)
    seen = camera.to_image(outline)
    quality = measures.quality(pixels, seen, camera, outline)
    if quality.refused:
        raise Stop(quality.refused[0].text)
    rail = setup.rail_height if setup.rail_height is not None else RAIL_HEIGHT[setup.scale]
    grid = rectify.grid_for(outline)
    image = rectify.rectify(pixels, camera, grid, rail)
    inside = rectify.module_mask(grid, outline, 3.0)
    light = rectify.even_light(image, inside, grid.ppm)
    gray2 = cv2.cvtColor(light.image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    small = grid.scaled(trackmap.MAP_PPM)
    gray1 = cv2.resize(gray2, (small.width, small.height), interpolation=cv2.INTER_AREA)
    inside1 = (
        cv2.resize(
            inside.astype(np.uint8), (small.width, small.height), interpolation=cv2.INTER_NEAREST
        )
        > 0
    )
    quiet = (
        cv2.resize(
            (light.shadow_edge | light.reflections).astype(np.uint8),
            (small.width, small.height),
            interpolation=cv2.INTER_NEAREST,
        )
        > 0
    )
    gauge = switches.GAUGE[setup.scale]
    head = RAIL_HEAD[setup.scale]
    generic = trackmap.generic_profile(gauge, head)
    strips = strips_of(shape, length, offset)
    # The photo's own track (bildkedjan step 10). The generic profile finds the gables' tracks
    # in a photo like the photo test's; their own cross section is then the profile the map is
    # made with, so the map sees this photo's tracks, at low resolution too. A photo whose
    # tracks look nothing like the generic profile (dark sleepers on cork) gets its profile
    # from the gables' strips instead.
    tracks = trackmap.track_map(gray1, small, inside1, generic, quiet)
    found_first = _gable_terminals(tracks, strips, gauge)
    known, known_middles = _learned(found_first, tracks, strips, gray2, grid, generic)
    boot = trackmap.bootstrap(gray2, grid, strips, gauge, head)
    options: list[tuple[trackmap.Profile, Array]] = []
    if known is not None:
        options.append((known, known_middles))
    if boot is not None:
        boot_middles = np.array(
            [strips[i].points(np.array([v]), LEARN_DEPTH)[0] for i, v in boot.centres]
        )
        options.append((boot.profile, boot_middles))
    best: tuple[float, trackmap.TrackMap, trackmap.Profile] | None = None
    for option, middles in options:
        candidate = trackmap.track_map(
            gray1, small, inside1, option, quiet, trackmap.rail_kind(option)
        )
        level = trackmap.level_at(candidate, middles)
        background = float(np.percentile(candidate.score[inside1], 90)) if inside1.any() else 1.0
        # How clearly the tracks the profile was learned from stand out, and how many of them:
        # a profile that matches the grass finds few tracks, and weakly.
        clear = level / max(background, MAP_FLOOR) * math.sqrt(len(middles))
        if best is None or clear > best[0]:
            weak = trackmap.level_at(candidate, middles, LIFT_PERCENTILE)
            best = (clear, trackmap.lifted(candidate, weak), option)
    first = generic
    if best is not None:
        _, tracks, first = best
    terminals = _gable_terminals(tracks, strips, gauge)
    # The photo's own cross section, learned again at the gables' tracks, for the middles.
    profile = first
    if terminals:
        learned, _ = _learned(terminals, tracks, strips, gray2, grid, first)
        profile = learned or first
    for i, (x, y, out) in enumerate(paths.ends(tracks, outline, gauge), start=1):
        terminals.append(Terminal(f"E{i}", "end", (x, y), out=out))
    cols = paths.columns(
        tracks,
        (float(outline[:, 0].min()), float(outline[:, 0].max())),
        (float(outline[:, 1].min()), float(outline[:, 1].max())),
    )
    min_radius = switches.limits(setup.scale).switch_min_radius
    found_paths = paths.connect(cols, terminals, min_radius, looser=quality.widen)
    paths.overlaps(found_paths, gauge, min_radius)
    if shape.curved:
        # A curve module's tracks follow its arcs (part c3).
        terminals, found_paths = paths.concentric(
            cols, terminals, found_paths, strips, shape, gauge
        )
    terminals, found_paths = _kept(terminals, found_paths)
    for p in found_paths:
        # Only what can be drawn without an answer is made exact; a path that is no track is
        # drawn only if the owner says so, as it was found.
        if p.status != "none":
            p.ys = trackmap.refine_path(gray2, grid, p.xs, p.ys, profile)
    terminals = _measured_gables(terminals, found_paths, strips, shape.curved)
    stitch_mm = None
    if prepared.mosaic is not None:
        stitch_mm = stitch.residual_mm(prepared.mosaic, np.linalg.inv(camera.plane_at(rail)))
        if stitch_mm > stitch.GATE_MM:
            raise Stop(
                f"Fotona går inte ihop: de skiljer {stitch_mm:.1f} mm på modulen. Ta nya foton "
                "med mer överlapp.".replace(".", ",", 1)
            )
        quality = replace(
            quality,
            stitched=True,
            gates=[
                *quality.gates,
                measures.Gate(
                    "stitch",
                    stitch_mm,
                    "warn",
                    f"{prepared.photos} foton ihopsydda: spårens lägen kan avvika några "
                    "millimeter, så toleranserna är bredare. Mät gavlarna själv.",
                ),
            ],
        )
    edges = None
    if shape.curved and shape.sides == "bent":
        # The edges are the frame's: looked for in the frame's own plane, not the rails'.
        frame_grid = rectify.grid_for(outline, arcs.CHECK_PPM)
        frame_image = rectify.rectify(pixels, camera, frame_grid, 0.0)
        edges = arcs.check(frame_image, frame_grid, shape)
        if not edges.round:
            quality = replace(
                quality,
                gates=[
                    *quality.gates,
                    measures.Gate("curve", edges.deviation, "warn", edges.text()),
                ],
            )
    return Measured(
        setup=setup,
        camera=camera,
        length=length,
        offset=offset,
        corners=corners,
        corner_sigma=sigma,
        grid=grid,
        quality=quality,
        terminals=terminals,
        paths=found_paths,
        profile=profile,
        rail_height=rail,
        size=size,
        shift=(float(centre_shift[0]), float(centre_shift[1])),
        stitch_mm=stitch_mm,
        photo_length=None if shape.curved else photo_length,
        image=light.image,
        edges=edges,
    )


def _kept(terminals: list[Terminal], found: list[Path]) -> tuple[list[Terminal], list[Path]]:
    """The gables' tracks that a track (or a hidden part) leaves from, numbered again from
    Kant 1: a peak in the strip that leads nowhere was something else (a platform's edge, a
    shadow). The paths are renamed with them."""
    used = {t for p in found if p.status != "none" for t in (p.a, p.b)}
    rename: dict[str, str] = {}
    kept: list[Terminal] = []
    for end in ("A", "B"):
        own = [t for t in terminals if t.kind == "gable" and t.gable == end and t.id in used]
        for n, t in enumerate(sorted(own, key=lambda t: t.track or 0), start=1):
            rename[t.id] = f"{end}{n}"
            kept.append(Terminal(f"{end}{n}", t.kind, t.at, t.gable, n, t.out))
    kept.extend(t for t in terminals if t.kind != "gable")
    renamed: list[Path] = []
    gable_ids = {t.id for t in terminals if t.kind == "gable"}
    for p in found:
        if (p.a in gable_ids and p.a not in rename) or (p.b in gable_ids and p.b not in rename):
            continue
        p.a, p.b = rename.get(p.a, p.a), rename.get(p.b, p.b)
        renamed.append(p)
    return kept, renamed


def _shifted(camera: Camera, shift: Array) -> Camera:
    """The camera solved in the first photo's px, used in the mosaic's: moved by its origin."""
    if not shift.any():
        return camera
    move = np.array([[1, 0, shift[0]], [0, 1, shift[1]], [0, 0, 1]], np.float64)
    return Camera(
        plane=move @ camera.plane,
        lift=move @ camera.lift,
        f=camera.f,
        centre=(camera.centre[0] + shift[0], camera.centre[1] + shift[1]),
        k=camera.k,
        tilt=camera.tilt,
        height=camera.height,
        residual=camera.residual,
    )


def _curve_centre(strips: list[trackmap.GableStrip]) -> Array | None:
    """Where a curve module's gables cross: its centre, when they are not near parallel."""
    a, b = strips
    if abs(a.along[0] * b.along[1] - a.along[1] * b.along[0]) < math.sin(math.radians(1.0)):
        return None
    found: Array = cam.intersect(
        (np.array(a.corner), np.array(a.along)), (np.array(b.corner), np.array(b.along))
    )
    return found


def _measured_gables(
    terminals: list[Terminal],
    found: list[Path],
    strips: list[trackmap.GableStrip],
    curved: bool = False,
) -> list[Terminal]:
    """Each gable's track where its path, fitted as a straight line over GABLE_FIT_MM, meets
    the gable: the position from Kant 1 to a fraction of a millimetre (bildkedjan step 13). On
    a curve module the position is the path's distance from Kant 1 about the curve's centre,
    over CURVE_FIT_MM (part c5)."""
    centre = _curve_centre(strips) if curved else None
    measured: list[Terminal] = []
    for t in terminals:
        if t.kind != "gable":
            measured.append(t)
            continue
        strip = strips[0 if t.gable == "A" else 1]
        own = [p for p in found if t.id in (p.a, p.b) and p.status == "track"]
        corner = np.array(strip.corner)
        along = np.array(strip.along)
        inward = np.array(strip.inward)
        vs: list[float] = []
        for p in own:
            pts = p.points() - corner
            depth = pts @ inward
            v = pts @ along
            near, far = GABLE_FIT_MM
            if centre is not None:
                # About the centre: how far the path lies from Kant 1's arc.
                out = corner - centre
                sign = 1.0 if float(along @ out) < 0 else -1.0
                v = sign * (
                    float(np.linalg.norm(out)) - np.linalg.norm(p.points() - centre, axis=1)
                )
                near, far = CURVE_FIT_MM
            sel = (depth >= near) & (depth <= far)
            if sel.sum() >= 10:
                _, intercept = np.polyfit(depth[sel], v[sel], 1)
                vs.append(float(intercept))
        v0 = float(np.median(vs)) if vs else along_gable(strip, t.at)
        at = corner + along * v0
        measured.append(
            Terminal(t.id, t.kind, (float(at[0]), float(at[1])), t.gable, t.track, t.out)
        )
    for p in found:
        for side, tid in (("a", p.a), ("b", p.b)):
            t = next(x for x in measured if x.id == tid)
            if t.kind != "gable":
                continue
            strip = strips[0 if t.gable == "A" else 1]
            depth = (p.points() - np.array(strip.corner)) @ np.array(strip.inward)
            keep = depth > 0.5
            if side == "a":
                p.xs = np.concatenate([[t.at[0]], p.xs[keep]])
                p.ys = np.concatenate([[t.at[1]], p.ys[keep]])
            else:
                p.xs = np.concatenate([p.xs[keep], [t.at[0]]])
                p.ys = np.concatenate([p.ys[keep], [t.at[1]]])
    return measured


# --- 3. Assemble ----------------------------------------------------------------------------


@dataclass
class Assembled:
    built: Built
    net: network.Network
    gauge: measures.GaugeResult
    sleepers: measures.Sleepers
    spread: measures.Spread
    gable_positions: dict[str, float]
    """Each gable track's position from Kant 1, mm."""
    gable_plus_minus: dict[str, float]
    switch_points: dict[str, tuple[float, float]]
    """Each switch number's points (the blade tips where the rails show them) from gable A, mm,
    and its ±."""
    switch_tips: dict[str, tuple[float, float]] = field(default_factory=dict)
    """Each switch number's blade tips (or its node) in the module's mm."""


def assemble(
    measured: Measured,
    connections: set[tuple[str, str]],
    drawing: Drawing,
    certainty: dict[tuple[str, str], Certainty] | None = None,
) -> Assembled:
    """The drawing from the connections decided, and the measures with their ±."""
    steady()
    setup = measured.setup
    gauge_mm = switches.GAUGE[setup.scale]
    chosen = [p for p in measured.paths if p.pair in connections]
    used = {t for p in chosen for t in (p.a, p.b)}
    terminals = [t for t in measured.terminals if t.id in used]
    gray = measured.gray()
    # The switches are read from their legs' rails in the measuring image, and fitted with the
    # library's types (part c3).
    seen = network.Seen.of(gray, measured.grid, measured.profile, measured.quality.px_per_mm)
    designs = [d for d in switches.designs(setup.scale) if d.radius is not None]
    net = network.build(chosen, terminals, gauge_mm, seen, designs)
    gable_tracks = {
        t.id: (GableEnd(t.gable), t.track or 1)
        for t in terminals
        if t.kind == "gable" and t.gable is not None
    }
    built = build(
        drawing,
        net,
        chosen,
        certainty or {},
        gable_tracks,
        measured.quality.widen,
        measured.shape.curved,
    )
    runs: list[curves.Line] = []
    for piece in built.drawing.pieces.values():
        runs.extend(measures.straight_runs(piece.segs, 120.0))
    found_gauge = measures.gauge(
        gray, measured.grid, runs, measured.profile, RAIL_HEAD[setup.scale]
    )
    found_sleepers = measures.sleepers(gray, measured.grid, runs, gauge_mm)
    positions: dict[str, float] = {}
    strips = measured.strips()
    for t in measured.terminals:
        if t.kind == "gable":
            positions[t.id] = along_gable(strips[0 if t.gable == "A" else 1], t.at)
    # The blade tips (tungspetsarna) where the rails show them, else the drawn node: the switches
    # are numbered in the drawing as their fits by x (build).
    fits = sorted(net.switches, key=lambda f: net.nodes[f.node].x)
    switch_at: dict[str, tuple[float, float]] = {}
    tips_spread: dict[str, float] = {}
    for sw in built.drawing.switches.values():
        number = sw.number or sw.id
        at = built.drawing.nodes[sw.node].at
        index = int(number) - 1 if number.isdigit() else -1
        fit = fits[index] if 0 <= index < len(fits) else None
        if fit is not None and fit.tips is not None:
            straight = chosen[net.edges[fit.straight].pid]
            at = (fit.tips, float(np.interp(fit.tips, straight.xs, straight.ys)))
            tips_spread[number] = fit.tips_spread
        switch_at[number] = at
    gables = [t for t in measured.terminals if t.kind == "gable"]
    points_mm = np.array([t.at for t in gables] + list(switch_at.values()), np.float64).reshape(
        -1, 2
    )
    points_px = (
        measured.camera.to_image(points_mm, measured.rail_height) if len(points_mm) else points_mm
    )
    shape = setup.shape()
    shift = np.array(measured.shift)
    monte = measures.Monte(
        corners=measured.corners - shift,
        shape=shape,
        size=measured.size,
        focal=measured.camera.f,
        k=measured.camera.k,
        sigma=measured.corner_sigma,
        rail_height=measured.rail_height,
        points_px=points_px - shift if len(points_px) else points_px,
    )
    spread = monte.run()
    widen = measured.quality.widen
    # A gable's track is measured along the gable, from Kant 1: its spread in y.
    plus_minus = {
        t.id: measures.plus_minus(
            float(spread.points[i][1]) if i < len(spread.points) else 0.2, widen
        )
        for i, t in enumerate(gables)
    }
    switch_points: dict[str, tuple[float, float]] = {}
    for k, (number, at) in enumerate(switch_at.items()):
        i = len(gables) + k
        # A switch's points are measured from gable A: their spread in x.
        sigma = float(spread.points[i][0]) if i < len(spread.points) else 0.5
        # And where the blade tips can lie between the arc's tangent point and the rails' slope.
        pm = max(measures.plus_minus(sigma, widen), round(tips_spread.get(number, 0.0), 1))
        switch_points[number] = (at[0], pm)
    return Assembled(
        built,
        net,
        found_gauge,
        found_sleepers,
        spread,
        positions,
        plus_minus,
        switch_points,
        switch_at,
    )


def pairs_text(pairs: set[tuple[str, str]]) -> str:
    return ", ".join(f"{a}–{b}" for a, b in sorted(pairs))


def length_plus_minus(measured: Measured, spread: measures.Spread) -> float | None:
    if spread.length is None:
        return None
    return measures.plus_minus(spread.length, measured.quality.widen)


def as_float(value: float) -> float:
    return float(round(value, 3)) if math.isfinite(value) else 0.0


# --- Kept with the job ------------------------------------------------------------------------


def to_json(measured: Measured) -> dict[str, Any]:
    """Everything stage 3 needs, as JSON: the measuring image is kept as a file of its own."""
    c = measured.camera
    q = measured.quality
    return {
        "setup": measured.setup.as_dict(),
        "camera": {
            "plane": _array(c.plane),
            "lift": [float(v) for v in c.lift],
            "f": c.f,
            "centre": list(c.centre),
            "k": c.k,
            "tilt": c.tilt,
            "height": c.height,
            "residual": c.residual,
        },
        "length": measured.length,
        "offset": measured.offset,
        "corners": _array(measured.corners),
        "corner_sigma": measured.corner_sigma,
        "grid": [
            measured.grid.x0,
            measured.grid.y0,
            measured.grid.ppm,
            measured.grid.width,
            measured.grid.height,
        ],
        "quality": {
            "px_per_mm": q.px_per_mm,
            "tilt": q.tilt,
            "sharpness": q.sharpness,
            "clipped": q.clipped,
            "gates": [[g.key, g.value, g.level, g.text] for g in q.gates],
            "stitched": q.stitched,
        },
        "terminals": [
            [t.id, t.kind, list(t.at), t.gable, t.track, t.out] for t in measured.terminals
        ],
        "paths": [
            {
                "a": p.a,
                "b": p.b,
                "xs": [round(float(x), 2) for x in p.xs],
                "ys": [round(float(y), 3) for y in p.ys],
                "share": p.share,
                "gap": p.gap,
                "sharpest": p.sharpest if math.isfinite(p.sharpest) else None,
                "status": p.status,
            }
            for p in measured.paths
        ],
        "profile": {
            "values": [round(float(v), 3) for v in measured.profile.values],
            "half": measured.profile.half,
            "rail": measured.profile.rail,
            "learned": measured.profile.learned,
        },
        "rail_height": measured.rail_height,
        "size": list(measured.size),
        "shift": list(measured.shift),
        "stitch_mm": measured.stitch_mm,
        "photo_length": measured.photo_length,
        "edges": measured.edges.as_json() if measured.edges is not None else None,
    }


def from_json(data: dict[str, Any], image: NDArray[Any] | None) -> Measured:
    setup = Setup.of(data["setup"])
    c = data["camera"]
    camera = Camera(
        plane=np.array(c["plane"], np.float64),
        lift=np.array(c["lift"], np.float64),
        f=float(c["f"]),
        centre=(float(c["centre"][0]), float(c["centre"][1])),
        k=float(c["k"]),
        tilt=float(c["tilt"]),
        height=float(c["height"]),
        residual=float(c["residual"]),
    )
    g = data["grid"]
    q = data["quality"]
    quality = measures.Quality(
        float(q["px_per_mm"]),
        float(q["tilt"]),
        float(q["sharpness"]),
        float(q["clipped"]),
        [
            measures.Gate(str(k), float(v), str(level), str(text))
            for k, v, level, text in q["gates"]
        ],
        bool(q.get("stitched", False)),
    )
    found_paths = [
        Path(
            p["a"],
            p["b"],
            np.array(p["xs"], np.float64),
            np.array(p["ys"], np.float64),
            float(p["share"]),
            float(p["gap"]),
            float(p["sharpest"]) if p["sharpest"] is not None else math.inf,
            str(p["status"]),
        )
        for p in data["paths"]
    ]
    pr = data["profile"]
    return Measured(
        setup=setup,
        camera=camera,
        length=float(data["length"]),
        offset=float(data["offset"]),
        corners=np.array(data["corners"], np.float64),
        corner_sigma=float(data["corner_sigma"]),
        grid=Grid(float(g[0]), float(g[1]), float(g[2]), int(g[3]), int(g[4])),
        quality=quality,
        terminals=[
            Terminal(
                t[0],
                t[1],
                (float(t[2][0]), float(t[2][1])),
                t[3],
                t[4],
                t[5] if len(t) > 5 else None,
            )
            for t in data["terminals"]
        ],
        paths=found_paths,
        profile=trackmap.Profile(
            np.array(pr["values"], np.float32),
            float(pr["half"]),
            float(pr["rail"]),
            bool(pr["learned"]),
        ),
        rail_height=float(data["rail_height"]),
        size=(int(data["size"][0]), int(data["size"][1])),
        shift=(float(data["shift"][0]), float(data["shift"][1])),
        stitch_mm=data["stitch_mm"],
        photo_length=data["photo_length"],
        image=image,
        edges=arcs.Edges.of(data["edges"]) if data.get("edges") else None,
    )
