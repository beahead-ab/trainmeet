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
from cad.bildkedjan import camera as cam
from cad.bildkedjan import corners as corners_
from cad.bildkedjan import measures, network, paths, rectify, stitch, trackmap
from cad.bildkedjan.build import Built, build
from cad.bildkedjan.camera import Array, Camera
from cad.bildkedjan.intake import Intake
from cad.bildkedjan.paths import Path, Terminal
from cad.bildkedjan.rectify import Grid
from cad.editor import Drawing
from contracts.cad import Certainty, GableEnd, Scale


def _array(values: Array) -> list[list[float]]:
    return [[round(float(v), 4) for v in row] for row in np.atleast_2d(values)]


CHAIN_VERSION = "1.0.0"
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


def prepare(intakes: list[Intake]) -> Prepared:
    """The photos as one, and the module's corners in it, if code finds them."""
    steady()
    first = intakes[0]
    if len(intakes) == 1:
        pixels = first.pixels
        origin = (0.0, 0.0)
        mosaic = None
    else:
        mosaic = stitch.stitch([i.pixels for i in intakes])
        pixels, origin = mosaic.pixels, mosaic.origin
    found = corners_.find(pixels)
    size = (first.width, first.height)
    lens = 0.0
    if found is not None and len(intakes) == 1:
        lens = cam.lens(
            found.sides, found.corners, size, cam.focal_from_35mm(size, first.focal_35mm)
        )
    return Prepared(pixels, first.focal_35mm, size, origin, found, len(intakes), mosaic, lens)


def ordered(corners: Array, kant1: int) -> Array:
    """The corners as the module's: A at Kant 1, B at Kant 1, B far, A far, from four clockwise
    corners and the side (i from corner i to i + 1) that is Kant 1."""
    clockwise = corners_.clockwise(np.asarray(corners, np.float64))
    return np.array([clockwise[(kant1 + k) % 4] for k in range(4)])


def default_kant1(corners: Array) -> int:
    """A first guess for the view: the long side lowest in the photo is Kant 1."""
    c = corners_.clockwise(np.asarray(corners, np.float64))
    lengths = [float(np.linalg.norm(c[(i + 1) % 4] - c[i])) for i in range(4)]
    long_sides = sorted(range(4), key=lambda i: -lengths[i])[:2]
    return max(long_sides, key=lambda i: c[i][1] + c[(i + 1) % 4][1])


# --- 2. Measure -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Setup:
    """What the owner gives: the scale, the form and the known measures, the corners (None:
    the ones code found) and which side is Kant 1."""

    scale: Scale
    kind: str
    width_a: float
    width_b: float
    length: float | None = None
    offset: float | None = None
    corners: tuple[tuple[float, float], ...] | None = None
    kant1: int = 0
    rail_height: float | None = None

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
        }


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

    @property
    def outline(self) -> Array:
        return cam.Shape(
            self.setup.kind, self.setup.width_a, self.setup.width_b, None, None
        ).corners(self.length, self.offset)

    def code_pairs(self) -> set[tuple[str, str]]:
        return {p.pair for p in self.paths if p.status == "track"}

    def gray(self) -> NDArray[Any]:
        assert self.image is not None
        return cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY).astype(np.float32)


class Stop(Exception):
    """The chain cannot go on with this photo: a gate refused it. The message says why."""


def _gable_terminals(
    tracks: trackmap.TrackMap, setup: Setup, length: float, offset: float, gauge: float
) -> list[Terminal]:
    found: list[Terminal] = []
    for end, x, inward, base, width in (
        ("A", 0.0, 1.0, 0.0, setup.width_a),
        ("B", length, -1.0, offset, setup.width_b),
    ):
        peaks = trackmap.strip_peaks(tracks, x, inward, (base + 2, base + width - 2), gauge)
        for n, y in enumerate(peaks, start=1):
            found.append(Terminal(f"{end}{n}", "gable", (x, y), end, n))
    return found


def measure(prepared: Prepared, setup: Setup) -> Measured:
    """The camera, the quality, the measuring image, the track map and the code's paths."""
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
        corners = ordered(given, setup.kant1)
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
        corners = ordered(through, setup.kant1)
    shape = cam.Shape(setup.kind, setup.width_a, setup.width_b, setup.length, setup.offset)
    local = corners - centre_shift
    camera, length, offset = cam.solve(local, shape, size, focal, k)
    photo_length = length
    if setup.length is not None:
        free = cam.Shape(setup.kind, setup.width_a, setup.width_b, None, setup.offset)
        _, photo_length, _ = cam.solve(local, free, size, focal, k)
    camera = _shifted(camera, centre_shift)
    outline = shape.corners(length, offset)
    quality = measures.quality(pixels, corners, camera, outline)
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
    tracks = trackmap.track_map(gray1, small, inside1, generic, quiet)
    terminals = _gable_terminals(tracks, setup, length, offset, gauge)
    # The photo's own cross section, learned at the gables' tracks.
    profile = generic
    if terminals:
        points, heads = [], []
        for t in terminals:
            inward = 1.0 if t.gable == "A" else -1.0
            q = np.array([[t.at[0] + inward * 20, t.at[1]]])
            _, d = tracks.at(q)
            r = trackmap.refine(gray2, grid, q, d, generic)
            points.append(q[0] + r.shift[0] * trackmap.across(float(d[0])))
            heads.append(float(d[0]))
        learned = trackmap.learn(
            gray2, grid, np.array(points), np.array(heads), generic.half, generic.rail
        )
        profile = learned or generic
    for i, (x, y, out) in enumerate(paths.ends(tracks, outline, gauge), start=1):
        terminals.append(Terminal(f"E{i}", "end", (x, y), out=out))
    y_lo = float(outline[:, 1].min())
    y_hi = float(outline[:, 1].max())
    cols = paths.columns(tracks, (0.0, length), (y_lo, y_hi))
    min_radius = switches.limits(setup.scale).switch_min_radius
    found_paths = paths.connect(cols, terminals, min_radius)
    for p in found_paths:
        p.ys = trackmap.refine_path(gray2, grid, p.xs, p.ys, profile)
    terminals = _measured_gables(terminals, found_paths, length)
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
        photo_length=photo_length,
        image=light.image,
    )


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


def _measured_gables(terminals: list[Terminal], found: list[Path], length: float) -> list[Terminal]:
    """Each gable's track where its path, fitted as a straight line over GABLE_FIT_MM, meets
    the gable: the position from Kant 1 to a fraction of a millimetre (bildkedjan step 13)."""
    measured: list[Terminal] = []
    for t in terminals:
        if t.kind != "gable":
            measured.append(t)
            continue
        own = [p for p in found if t.id in (p.a, p.b) and p.status == "track"]
        if not own:
            measured.append(t)
            continue
        x_gable = 0.0 if t.gable == "A" else length
        ys: list[float] = []
        for p in own:
            if t.gable == "A":
                sel = (p.xs >= x_gable + GABLE_FIT_MM[0]) & (p.xs <= x_gable + GABLE_FIT_MM[1])
            else:
                sel = (p.xs <= x_gable - GABLE_FIT_MM[0]) & (p.xs >= x_gable - GABLE_FIT_MM[1])
            if sel.sum() >= 10:
                slope, intercept = np.polyfit(p.xs[sel], p.ys[sel], 1)
                ys.append(float(slope * x_gable + intercept))
        y = float(np.median(ys)) if ys else t.at[1]
        measured.append(Terminal(t.id, t.kind, (x_gable, y), t.gable, t.track, t.out))
    for p in found:
        for side, tid in (("a", p.a), ("b", p.b)):
            t = next(x for x in measured if x.id == tid)
            if t.kind != "gable":
                continue
            if side == "a":
                keep = p.xs > t.at[0]
                p.xs = np.concatenate([[t.at[0]], p.xs[keep]])
                p.ys = np.concatenate([[t.at[1]], p.ys[keep]])
            else:
                keep = p.xs < t.at[0]
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
    """Each switch number's points from gable A, mm, and its ±."""


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
    net = network.build(chosen, terminals, gauge_mm)
    gable_tracks = {
        t.id: (GableEnd(t.gable), t.track or 1)
        for t in terminals
        if t.kind == "gable" and t.gable is not None
    }
    built = build(drawing, net, chosen, certainty or {}, gable_tracks)
    gray = measured.gray()
    runs: list[curves.Line] = []
    for piece in built.drawing.pieces.values():
        runs.extend(measures.straight_runs(piece.segs, 120.0))
    found_gauge = measures.gauge(
        gray, measured.grid, runs, measured.profile, RAIL_HEAD[setup.scale]
    )
    found_sleepers = measures.sleepers(gray, measured.grid, runs, gauge_mm)
    positions: dict[str, float] = {}
    for t in measured.terminals:
        if t.kind == "gable":
            positions[t.id] = t.at[1] - (measured.offset if t.gable == "B" else 0.0)
    switch_at = {
        sw.number or sw.id: built.drawing.nodes[sw.node].at
        for sw in built.drawing.switches.values()
    }
    gables = [t for t in measured.terminals if t.kind == "gable"]
    points_mm = np.array([t.at for t in gables] + list(switch_at.values()), np.float64).reshape(
        -1, 2
    )
    points_px = (
        measured.camera.to_image(points_mm, measured.rail_height) if len(points_mm) else points_mm
    )
    shape = cam.Shape(setup.kind, setup.width_a, setup.width_b, setup.length, setup.offset)
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
        switch_points[number] = (at[0], measures.plus_minus(sigma, widen))
    return Assembled(
        built, net, found_gauge, found_sleepers, spread, positions, plus_minus, switch_points
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
    }


def from_json(data: dict[str, Any], image: NDArray[Any] | None) -> Measured:
    s = data["setup"]
    setup = Setup(
        scale=Scale(s["scale"]),
        kind=s["kind"],
        width_a=float(s["width_a"]),
        width_b=float(s["width_b"]),
        length=s["length"],
        offset=s["offset"],
        corners=tuple(tuple(c) for c in s["corners"]) if s["corners"] else None,
        kant1=int(s["kant1"]),
        rail_height=s["rail_height"],
    )
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
    )
