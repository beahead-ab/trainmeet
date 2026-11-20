"""Profile Stationsritning: a station's drawing read into a ritningsavläsning for Studio
(bildkedjan, Stationsritning R1–R4; CAD6, CAD-31; #89 del c4).

The pages come from cad/bildkedjan/ritning_in.py, as strokes, words and figures in the drawing's
own coordinates, y down. Here code reads them, the same way for a vector page (R1) and a raster
page (R2), and no AI decides anything (AI only transcribed a raster page's text):

1. The drawing's unit (unit): the text's height, or 1,2 % of the page's long side without text.
   Every distance below is in units, so a drawing in points and a picture in pixels read alike.
2. The figures (R3): closed things that are small, deduplicated (a PDF draws a filled circle and
   its outline as two). A long, low frame with two or more lamps inside, with a post and a foot,
   is a signal figure: its lamps give the type (Hsi 2, Hsi 4 …) and its foot → head the way it
   applies. Other figures are grouped by type (a green triangle, a yellow circle …).
3. The lines by colour and width (classes): the class with most long lines is the tracks; a class
   of the same colour family is tracks too. Short strokes across a track are track-circuit
   boundaries; red ones are, without asking. A class that is long, or that crosses tracks, and is
   neither, is asked about once: the legend (R1, "ask once per colour").
4. The track graph: the tracks' segments joined where they overlap, cut where a segment ends on
   another or two cross, and their ends snapped together within TOLERANCE units. A node with one
   end is a track's end, with three a switch, with four a crossing; pieces run between them, and
   short spurs of the drawing are dropped. A switch's trunk is the leg that leaves on its own
   side, and its straight leg the one that runs on most nearly from the trunk. An end at the
   drawing's west or east edge (EXIT_SHARE) is a line exit, else a buffer stop; one in between is
   asked.
5. The labels (R4): the words tied by code to the nearest object. A number by a switch is its
   number; "Spår 4" or IV by a track is its name; "Hdvsi 66 (204)", "72 (1203)", or "21" over
   "(1201)", is a signal with its type, name and address, standing at its figure or, without one,
   at the boundary stroke beside the text, facing away from the text.
6. The questions: one per line class or figure type code cannot place, the legend first, then the
   track ends. The owner's answer changes the read at once, without reading again.

The result is contracts.cad.DrawingRead's graph and lists: a TrackGraph with geometry "schema",
pieces and nodes numbered west to east. Nothing here names a station (RS13).
"""

from __future__ import annotations

import itertools
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Final, Literal

import cv2
import numpy as np
from numpy.typing import NDArray

from cad.bildkedjan.ritning_in import RGB, Box, Page, Point, Stroke, Word, family
from contracts.cad import (
    Certainty,
    DrawingBoundary,
    DrawingChoice,
    DrawingQuestion,
    DrawingQuestionKind,
    DrawingSummary,
    GraphLabel,
    GraphNode,
    GraphOrigin,
    GraphPiece,
    GraphSource,
    GraphSwitch,
    GraphSymbol,
    LineSegment,
    Segment,
    SymbolKind,
    TrackGraph,
)
from contracts.station_model import NodeType, SignalType, SwitchType

PROFILE: Final = "stationsritning"
READER_VERSION: Final = "1.0.0"
"""The reader's version: in the job's key, so a new reader is a new job."""

UNIT_SHARE: Final = 0.012
"""Without text, the unit is this share of the page's long side."""
TOLERANCE: Final = 0.25
"""Ends this close, in units, are one node; an end this close to a line ends on it."""
TOLERANCE_RASTER: Final = 0.4
"""The same on a raster page, whose lines found by LSD end a little short of each other."""
GAP: Final = 2.0
"""A line broken by less than this many tolerances (a symbol or a stroke drawn over it) is one
line."""
SPUR: Final = 0.6
"""A free end shorter than this, in units, from a switch is the drawing's overshoot."""
LONG: Final = 3.0
"""A line longer than this, in units, may be a track."""
BAR: Final = (0.8, 3.5)
"""A boundary stroke is this long, in units, and crosses a track at BAR_ANGLE or more."""
BAR_ANGLE: Final = 35.0
TRACK_SHARE: Final = 0.5
"""The track class has at least this share of the long lines' length to need no question."""
EXIT_SHARE: Final = 0.04
"""An end within this share of the drawing's width from its west or east edge is a line
exit."""
EXIT_ASK: Final = 0.08
"""An end between EXIT_SHARE and this share from an edge is asked: line exit or buffer stop."""
SWITCH_LABEL: Final = 3.0
"""A switch's number stands within this many units of its node."""
TRACK_LABEL: Final = 2.0
SIGNAL_LABEL: Final = 1.6
"""A signal's text stands within this many units of its figure or its boundary stroke."""
SNAP_SIGNAL: Final = 1.0
"""A signal this close to a boundary stroke on its track stands at the stroke."""
FIGURE_SIDE: Final = 5.0
"""A figure is at most this many units across."""
GLYPH_POINTS: Final = 12
"""A small filled figure with more points than this, and not round, is a letter drawn as an
outline."""

SIGNAL_TYPES: Final = {
    "hsi": SignalType.HSI,
    "hdvsi": SignalType.HDVSI,
    "dvsi": SignalType.DVSI,
    "fsi": SignalType.FSI,
    "sl": SignalType.STOP_LAMP,
    "spl": SignalType.STOP_LAMP,
}
SIGNAL_TEXT = re.compile(
    r"^(?:(?P<type>hdvsi|hsi|dvsi|fsi|spl|sl)\.?\s*)?(?P<name>[0-9]{1,4}[a-z]?)\s*"
    r"\((?P<address>\d{1,5})\)$",
    re.IGNORECASE,
)
TYPED_NAME = re.compile(
    r"^(?P<type>hdvsi|hsi|dvsi|fsi|spl|sl)\.?\s*(?P<name>[0-9]{1,4}[a-z]?)$", re.I
)
ADDRESS_ONLY = re.compile(r"^\((?P<address>\d{1,5})\)$")
NUMBER = re.compile(r"^[0-9]{1,4}[a-z]?$")
TRACK_NAME = re.compile(r"^(?:spår|sp\.?)\s*(?P<name>[0-9A-Za-zÅÄÖåäö]{1,6})$", re.IGNORECASE)
ROMAN: Final = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII")
LINE_WORDS = re.compile(r"linje|mot |från |utfart", re.IGNORECASE)

LINE_CHOICES: Final = [
    DrawingChoice(id="spar", text="Spår"),
    DrawingChoice(id="grans", text="Spårledningsgränser"),
    DrawingChoice(id="annat", text="Något annat: tas inte med"),
]
SYMBOL_CHOICES: Final = [
    DrawingChoice(id="hsi", text="Huvudsignal"),
    DrawingChoice(id="hdvsi", text="Huvuddvärgsignal"),
    DrawingChoice(id="dvsi", text="Dvärgsignal"),
    DrawingChoice(id="stoppbock", text="Stoppbock"),
    DrawingChoice(id="grans", text="Spårledningsgräns"),
    DrawingChoice(id="knapp", text="Knapp eller lampa på panelen: tas inte med"),
    DrawingChoice(id="annat", text="Något annat: tas inte med"),
]
END_CHOICES: Final = [
    DrawingChoice(id="linjeutfart", text="Linjeutfart: spåret går ut på linjen"),
    DrawingChoice(id="stoppbock", text="Stoppbock: spåret slutar här"),
]
SAMPLES: Final = {"circle": "●", "triangle": "▲", "rect": "■", "blob": "◆"}


# --- Small geometry --------------------------------------------------------------------------


def slug(text: str) -> str:
    """A colour's name as a question's key: a–z only."""
    return text.translate(str.maketrans("åäöÅÄÖ", "aaoaao")).lower()


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _unit(v: Point) -> Point:
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n) if n > 0 else (0.0, 0.0)


def project(p: Point, a: Point, b: Point) -> tuple[float, Point, float]:
    """The point's distance to the segment, the nearest point on it, and its parameter 0–1."""
    d = _sub(b, a)
    length2 = _dot(d, d)
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, _dot(_sub(p, a), d) / length2))
    q = (a[0] + t * d[0], a[1] + t * d[1])
    return math.dist(p, q), q, t


def crossing(a: Point, b: Point, c: Point, d: Point) -> tuple[float, float] | None:
    """Where segment ab crosses segment cd, as the parameters on each, or None."""
    r, s = _sub(b, a), _sub(d, c)
    denominator = r[0] * s[1] - r[1] * s[0]
    if abs(denominator) < 1e-12:
        return None
    q = _sub(c, a)
    t = (q[0] * s[1] - q[1] * s[0]) / denominator
    u = (q[0] * r[1] - q[1] * r[0]) / denominator
    if 0 <= t <= 1 and 0 <= u <= 1:
        return t, u
    return None


def _angle(a: Point, b: Point) -> float:
    """The angle between two directions, 0–90°, as lines (without their sense)."""
    ua, ub = _unit(a), _unit(b)
    return math.degrees(math.acos(min(1.0, abs(_dot(ua, ub)))))


def polyline_distance(p: Point, points: list[Point]) -> tuple[float, Point, float]:
    """The point's distance to a polyline, the nearest point, and how far along it that is."""
    best = (math.inf, points[0], 0.0)
    walked = 0.0
    for a, b in itertools.pairwise(points):
        d, q, t = project(p, a, b)
        if d < best[0]:
            best = (d, q, walked + t * math.dist(a, b))
        walked += math.dist(a, b)
    return best


def _gap(a: Box, b: Box) -> float:
    """The distance between two boxes, 0 when they overlap."""
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return math.hypot(dx, dy)


def _grow(box: Box, by: float) -> Box:
    return (box[0] - by, box[1] - by, box[2] + by, box[3] + by)


def _inside(p: Point, box: Box) -> bool:
    return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]


# --- 1. The unit ------------------------------------------------------------------------------


def unit_of(page: Page) -> float:
    heights = sorted(w.height for w in page.words if 0 < w.height < 0.2 * page.height)
    if len(heights) >= 3:
        return float(heights[len(heights) // 2])
    return UNIT_SHARE * max(page.width, page.height)


# --- 2. The figures (R3) --------------------------------------------------------------------


@dataclass
class Figure:
    """A symbol in the drawing: a signal figure, or a small closed figure of some type."""

    kind: Literal["signal", "circle", "triangle", "rect", "blob"]
    box: Box
    centre: Point
    colour: str
    """The fill's colour family, or the outline's for an outline."""
    lamps: int = 0
    head: Point | None = None
    foot: Point | None = None
    pointing: float | None = None
    long: float | None = None
    """The figure's long side and short side, turned as it is drawn."""
    short: float = 0.0

    @property
    def type_key(self) -> str:
        return f"{self.kind}-{slug(self.colour)}"


def _corners(points: list[Point]) -> int:
    """The corners of a closed polygon: its points without the closing one and the straight
    ones."""
    found = list(points)
    if len(found) > 1 and math.dist(found[0], found[-1]) < 1e-6:
        found = found[:-1]
    corners = 0
    for i, p in enumerate(found):
        a, b = found[i - 1], found[(i + 1) % len(found)]
        if _angle(_sub(p, a), _sub(b, p)) > 10:
            corners += 1
    return corners


def _sides(points: list[Point]) -> tuple[float, float]:
    """A figure's long and short side, turned as it is drawn (the smallest rectangle)."""
    (_, _), (w, h), _ = cv2.minAreaRect(np.array(points, np.float32))
    return float(max(w, h)), float(min(w, h))


def _round(s: Stroke) -> bool:
    long, short = _sides(s.points)
    return s.curved and long < 1.3 * max(short, 1e-6) and len(s.points) <= 17


def _vector_figures(page: Page, unit: float) -> tuple[list[Figure], set[int]]:
    """A vector page's figures, and the strokes they are made of (so they are no lines). A PDF
    often draws a figure twice, filled and outlined: the two are one. Small filled figures with
    many points are letters drawn as outlines; their places are kept, as text code cannot
    read."""
    side = FIGURE_SIDE * unit
    area = page.width * page.height
    used: set[int] = set()
    shapes: list[tuple[list[int], Box, RGB | None, RGB | None, Stroke]] = []
    candidates: list[tuple[int, Stroke]] = []
    for i, s in enumerate(page.strokes):
        if not s.closed:
            continue
        x0, y0, x1, y1 = s.box
        w, h = x1 - x0, y1 - y0
        if max(w, h) > side or w * h > 0.3 * area or max(w, h) < 0.1 * unit:
            continue
        if s.fill is not None and len(s.points) > GLYPH_POINTS and not _round(s):
            page.outlined.append(s.box)
            used.add(i)
            continue
        candidates.append((i, s))
    # A letter with few points (an o, a parenthesis) is filled without an outline, among others.
    words = [_grow(w, 0.4 * unit) for w in _words_of(page.outlined, unit)]
    for i, s in candidates:
        if s.colour is None and s.fill is not None and any(_gap(s.box, w) == 0 for w in words):
            page.outlined.append(s.box)
            used.add(i)
            continue
        same = next(
            (
                k
                for k, x in enumerate(shapes)
                if max(abs(a - b) for a, b in zip(x[1], s.box, strict=True)) < 0.15 * unit
            ),
            None,
        )
        if same is not None:
            indices, box, fill, outline, first = shapes[same]
            shapes[same] = (
                [*indices, i],
                box,
                fill if fill is not None else s.fill,
                outline if outline is not None else s.colour,
                first,
            )
            continue
        shapes.append(([i], s.box, s.fill, s.colour, s))
    figures: list[Figure] = []
    for indices, box, fill, outline, s in shapes:
        x0, y0, x1, y1 = box
        aspect = (x1 - x0) / max(y1 - y0, 1e-6)
        colour = family(fill) if fill is not None and family(fill) != "vita" else family(outline)
        if colour == "osynliga" and fill is not None:
            colour = family(fill)
        kind: Literal["signal", "circle", "triangle", "rect", "blob"]
        if _round(s):
            kind = "circle"
        else:
            corners = _corners(s.points)
            if corners == 3:
                kind = "triangle"
            elif corners == 4 or (s.curved and (aspect > 1.4 or aspect < 0.7)):
                kind = "rect"
            else:
                kind = "blob"
        figure = Figure(kind, box, ((x0 + x1) / 2, (y0 + y1) / 2), colour)
        figure.long, figure.short = _sides(s.points)
        if kind == "rect" and s.curved and figure.long < 1.4 * figure.short:
            figure.kind = kind = "blob"
        elif kind == "blob" and figure.long >= 1.6 * figure.short and len(s.points) <= 12:
            figure.kind = kind = "rect"
        if kind == "triangle":
            pts = s.points[:-1] if math.dist(s.points[0], s.points[-1]) < 1e-6 else s.points
            if len(pts) == 3:
                sides = [math.dist(pts[(k + 1) % 3], pts[(k + 2) % 3]) for k in range(3)]
                tip = pts[int(np.argmin(sides))]
                figure.pointing = math.atan2(tip[1] - figure.centre[1], tip[0] - figure.centre[0])
        figures.append(figure)
        used.update(indices)
    return _signal_figures(page, figures, unit, used), used


def _signal_figures(page: Page, figures: list[Figure], unit: float, used: set[int]) -> list[Figure]:
    """Frames with lamps inside become signal figures, with their post and foot from the open
    lines that touch the frame (a vector page)."""
    circles = [f for f in figures if f.kind == "circle"]
    kept: list[Figure] = []
    taken: set[int] = set()
    for frame in figures:
        if frame.kind not in ("rect", "blob") or frame.long is None:
            continue
        if frame.long > 3 * unit or frame.short > 1.2 * unit or frame.long < 1.4 * frame.short:
            continue
        inside = [c for c in circles if _inside(c.centre, _grow(frame.box, 0.05 * unit))]
        distinct: list[Figure] = []
        for c in inside:
            if all(math.dist(c.centre, d.centre) > 0.15 * unit for d in distinct):
                distinct.append(c)
        if len(distinct) < 2:
            continue
        for c in inside:
            taken.add(id(c))
        taken.add(id(frame))
        head = frame.centre
        foot = None
        # The post: an open line with one end at the frame; the foot at its other end.
        near = _grow(frame.box, 0.2 * unit)
        for i, s in enumerate(page.strokes):
            if i in used or s.closed or s.colour is None or s.length > 2 * unit:
                continue
            a, b = s.points[0], s.points[-1]
            if _inside(a, near) != _inside(b, near):
                far = b if _inside(a, near) else a
                foot = far
                used.add(i)
                for j, t in enumerate(page.strokes):
                    if j in used or t.closed or t.length > 1.2 * unit:
                        continue
                    if (
                        min(math.dist(far, t.points[0]), math.dist(far, t.points[-1])) < 0.1 * unit
                        or project(far, t.points[0], t.points[-1])[0] < 0.1 * unit
                    ):
                        used.add(j)
                break
        box = frame.box
        if foot is not None:
            box = (
                min(box[0], foot[0]),
                min(box[1], foot[1]),
                max(box[2], foot[0]),
                max(box[3], foot[1]),
            )
        kept.append(
            Figure(
                "signal",
                box,
                frame.centre,
                frame.colour,
                lamps=len(distinct),
                head=head,
                foot=foot,
            )
        )
    return [f for f in figures if id(f) not in taken] + kept


def _raster_figures(page: Page) -> list[Figure]:
    found: list[Figure] = []
    for s in page.shapes:
        if s.kind == "figure":
            found.append(
                Figure("signal", s.box, s.centre, family(s.colour), s.lamps, s.head, s.foot)
            )
        else:
            kind: Literal["circle", "triangle", "rect", "blob"] = s.kind
            found.append(Figure(kind, s.box, s.centre, family(s.colour), pointing=s.pointing))
    return found


# --- 3. The lines by class ------------------------------------------------------------------


@dataclass
class LineClass:
    key: str
    colour: str
    thick: bool
    strokes: list[int] = field(default_factory=list)
    total: float = 0.0
    long: float = 0.0
    crossing: int = 0
    short: int = 0
    role: Literal["track", "boundary", "other"] = "other"
    certain: bool = True
    touches: bool = False


def _segments(points: list[Point]) -> list[tuple[Point, Point]]:
    return [(a, b) for a, b in itertools.pairwise(points) if math.dist(a, b) > 1e-6]


def _classes(
    page: Page, unit: float, tol: float, used: set[int], answers: dict[str, str]
) -> list[LineClass]:
    lines = [
        (i, s)
        for i, s in enumerate(page.strokes)
        if i not in used and s.colour is not None and not s.closed
    ]
    widths = sorted(s.width for _, s in lines if s.length > LONG * unit)
    base = widths[len(widths) // 2] if widths else 1.0
    classes: dict[str, LineClass] = {}
    for i, s in lines:
        colour = family(s.colour)
        if colour in ("vita", "osynliga"):
            continue
        thick = s.width > 1.8 * max(base, 0.3)
        key = f"{slug(colour)}-{'tjocka' if thick else 'tunna'}"
        found = classes.setdefault(key, LineClass(key, colour, thick))
        found.strokes.append(i)
        found.total += s.length
        if s.length > LONG * unit:
            found.long += s.length
    ranked = sorted(classes.values(), key=lambda c: -c.long)
    if not ranked or ranked[0].long <= 0:
        return list(classes.values())
    tracks = ranked[0]
    tracks.role = "track"
    all_long = sum(c.long for c in ranked) or 1.0
    tracks.certain = tracks.long / all_long >= TRACK_SHARE
    track_segments = [seg for i in tracks.strokes for seg in _segments(page.strokes[i].points)]
    for c in ranked[1:]:
        if c.colour == tracks.colour and not c.thick:
            c.role, c.certain = "track", True
            track_segments += [seg for i in c.strokes for seg in _segments(page.strokes[i].points)]
    # Tracks broken where a stroke is drawn over them are whole again before strokes cross them.
    track_segments = _merge_collinear(track_segments, tol)
    for c in ranked[1:]:
        if c.role == "track":
            continue
        for i in c.strokes:
            s = page.strokes[i]
            if BAR[0] * unit <= s.length <= BAR[1] * unit:
                c.short += 1
                if _crosses_track(s, track_segments):
                    c.crossing += 1
            ends = (s.points[0], s.points[-1])
            if s.length > LONG * unit and any(
                project(p, a, b)[0] <= TOLERANCE * unit for p in ends for a, b in track_segments
            ):
                c.touches = True
        if c.short and c.crossing >= 0.6 * c.short and (c.crossing >= 2 or c.colour == "röda"):
            c.role = "boundary"
            c.certain = c.colour in ("röda", "orange")
        elif c.long > 0.05 * tracks.long and c.touches:
            c.role, c.certain = "track", False
        elif c.long > 0.15 * tracks.long:
            c.role, c.certain = "other", False
    for c in classes.values():
        said = answers.get(f"linje.{c.key}")
        if said == "spar":
            c.role = "track"
        elif said == "grans":
            c.role = "boundary"
        elif said == "annat":
            c.role = "other"
    return list(classes.values())


def _crosses_track(s: Stroke, track_segments: list[tuple[Point, Point]]) -> bool:
    for a, b in _segments(s.points):
        for c, d in track_segments:
            hit = crossing(a, b, c, d)
            if (
                hit is not None
                and 0.1 <= hit[0] <= 0.9
                and _angle(_sub(b, a), _sub(d, c)) >= BAR_ANGLE
            ):
                return True
    return False


# --- 4. The track graph -----------------------------------------------------------------------


@dataclass
class Edge:
    a: int
    b: int
    points: list[Point]

    @property
    def length(self) -> float:
        return sum(math.dist(p, q) for p, q in zip(self.points, self.points[1:], strict=False))


@dataclass
class Graph:
    nodes: dict[int, Point]
    edges: list[Edge]

    def touching(self, node: int) -> list[int]:
        return [i for i, e in enumerate(self.edges) if node in (e.a, e.b)]

    def degree(self, node: int) -> int:
        return sum((e.a == node) + (e.b == node) for e in self.edges)


def _merge_collinear(segments: list[tuple[Point, Point]], tol: float) -> list[tuple[Point, Point]]:
    """Segments on one line that overlap or touch, joined: a track drawn twice, or in parts."""
    work = [seg for seg in segments if math.dist(*seg) > tol / 4]
    changed = True
    while changed:
        changed = False
        work.sort(key=lambda seg: -math.dist(*seg))
        out: list[tuple[Point, Point]] = []
        for a, b in work:
            for k, (c, d) in enumerate(out):
                if _angle(_sub(b, a), _sub(d, c)) > 1.5:
                    continue
                if _line_distance(a, c, d) > tol / 2 or _line_distance(b, c, d) > tol / 2:
                    continue
                direction = _unit(_sub(d, c))
                length = _dot(_sub(d, c), direction)
                ta, tb = sorted((_dot(_sub(a, c), direction), _dot(_sub(b, c), direction)))
                if tb < -GAP * tol or ta > length + GAP * tol:
                    continue
                lo, hi = min(0.0, ta), max(length, tb)
                out[k] = (
                    (c[0] + direction[0] * lo, c[1] + direction[1] * lo),
                    (c[0] + direction[0] * hi, c[1] + direction[1] * hi),
                )
                changed = True
                break
            else:
                out.append((a, b))
        work = out
    return work


def _line_distance(p: Point, a: Point, b: Point) -> float:
    """The point's distance to the infinite line through a and b."""
    d = _unit(_sub(b, a))
    v = _sub(p, a)
    return abs(v[0] * d[1] - v[1] * d[0])


def build_graph(lines: list[list[Point]], tol: float, unit: float) -> Graph:
    """The tracks' graph from their drawn lines (step 4)."""
    segments = _merge_collinear([seg for line in lines for seg in _segments(line)], tol)
    cuts: list[list[float]] = [[0.0, 1.0] for _ in segments]
    for i, (a, b) in enumerate(segments):
        length = math.dist(a, b)
        for j, (c, d) in enumerate(segments):
            if i == j:
                continue
            for p in (c, d):
                dist, _, t = project(p, a, b)
                if dist <= tol and tol < t * length < length - tol:
                    cuts[i].append(t)
            hit = crossing(a, b, c, d)
            if hit is not None:
                t, u = hit
                other = math.dist(c, d)
                if tol < t * length < length - tol and tol < u * other < other - tol:
                    cuts[i].append(t)
    pieces: list[tuple[Point, Point]] = []
    for (a, b), ts in zip(segments, cuts, strict=True):
        ordered = sorted(set(round(t, 6) for t in ts))
        for t0, t1 in itertools.pairwise(ordered):
            p = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0)
            q = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
            if math.dist(p, q) > tol / 2:
                pieces.append((p, q))
    # The ends snapped together: union-find on the distance.
    points = [p for seg in pieces for p in seg]
    parent = list(range(len(points)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(len(points)), key=lambda i: points[i])
    for k, i in enumerate(order):
        for j in order[k + 1 :]:
            if points[j][0] - points[i][0] > tol:
                break
            if math.dist(points[i], points[j]) <= tol:
                parent[root(i)] = root(j)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(points)):
        groups[root(i)].append(i)
    node_of: dict[int, int] = {}
    nodes: dict[int, Point] = {}
    for number, members in enumerate(groups.values()):
        xs = [points[i][0] for i in members]
        ys = [points[i][1] for i in members]
        nodes[number] = (round(sum(xs) / len(xs), 3), round(sum(ys) / len(ys), 3))
        for i in members:
            node_of[i] = number
    edges: list[Edge] = []
    seen: set[tuple[int, int]] = set()
    for k in range(len(pieces)):
        first, last = node_of[2 * k], node_of[2 * k + 1]
        if first == last or (min(first, last), max(first, last)) in seen:
            continue
        seen.add((min(first, last), max(first, last)))
        edges.append(Edge(first, last, [nodes[first], nodes[last]]))
    graph = Graph(nodes, edges)
    _prune(graph, unit)
    _chain(graph)
    return graph


def _prune(graph: Graph, unit: float) -> None:
    """Short free ends at a switch or a crossing are the drawing's overshoot."""
    changed = True
    while changed:
        changed = False
        for i, e in enumerate(graph.edges):
            for end, other in ((e.a, e.b), (e.b, e.a)):
                if graph.degree(end) == 1 and graph.degree(other) >= 3 and e.length < SPUR * unit:
                    del graph.edges[i]
                    changed = True
                    break
            if changed:
                break


def _chain(graph: Graph) -> None:
    """Edges joined through nodes with two of them into pieces: a node where a track only
    bends is no node of the graph."""
    changed = True
    while changed:
        changed = False
        for node in list(graph.nodes):
            touching = graph.touching(node)
            if len(touching) != 2:
                continue
            i, j = touching
            e, f = graph.edges[i], graph.edges[j]
            if e is f or {e.a, e.b} == {f.a, f.b}:
                continue
            first = e.points if e.b == node else list(reversed(e.points))
            second = f.points if f.a == node else list(reversed(f.points))
            start = e.a if e.b == node else e.b
            end = f.b if f.a == node else f.a
            joined = Edge(start, end, first + second[1:])
            for k in sorted((i, j), reverse=True):
                del graph.edges[k]
            graph.edges.append(joined)
            del graph.nodes[node]
            changed = True
            break
    used = {n for e in graph.edges for n in (e.a, e.b)}
    for node in list(graph.nodes):
        if node not in used:
            del graph.nodes[node]


def _leaving(edge: Edge, node: int, unit: float) -> Point:
    """The direction a piece leaves a node, judged over its first unit or so."""
    points = edge.points if edge.a == node else list(reversed(edge.points))
    start = points[0]
    for p in points[1:]:
        if math.dist(start, p) >= 0.8 * unit:
            return _unit(_sub(p, start))
    return _unit(_sub(points[-1], start))


# --- The read --------------------------------------------------------------------------------


@dataclass
class Signal:
    name: str | None
    address: int | None
    type: SignalType | None
    lamps: int | None
    facing: Literal["east", "west"] | None
    at: Point
    piece: int | None
    label: int | None
    figure: Figure | None
    certainty: Certainty


@dataclass
class Read:
    """What code read from a page: the graph, the figures, the labels and the questions, before
    they are the contract."""

    unit: float
    graph: Graph
    classes: list[LineClass]
    figures: list[Figure]
    ends: dict[int, tuple[NodeType, Certainty, bool]]
    """A track's end -> what it is, how sure, and whether it is asked."""
    switches: dict[int, tuple[int | None, int | None, int | None]]
    crossings: dict[int, list[tuple[int, int]]]
    boundaries: list[tuple[Point, int, Certainty]]
    signals: list[Signal]
    numbers: dict[int, int]
    """A switch's node -> its number's word."""
    track_names: dict[int, str]
    """A piece -> the track's name."""
    label_refs: dict[int, tuple[str, int] | None]
    """A word -> the object it names: ("piece" | "node" | "signal" | "figure", index)."""
    questions: list[DrawingQuestion]
    unknown: list[Figure]
    notes: list[str]


def read(page: Page, answers: dict[str, str] | None = None) -> Read:
    """Code reads the page, with the owner's answers to its questions."""
    answers = answers or {}
    unit = unit_of(page)
    tol = (TOLERANCE if page.kind == "vector" else TOLERANCE_RASTER) * unit
    if page.kind == "vector":
        figures, used = _vector_figures(page, unit)
    else:
        texts = [_grow(w.box, 0.15 * unit) for w in page.words]
        figures = [
            f for f in _raster_figures(page) if not any(_inside(f.centre, box) for box in texts)
        ]
        used = set()
    classes = _classes(page, unit, tol, used, answers)
    track_lines = [page.strokes[i].points for c in classes if c.role == "track" for i in c.strokes]
    graph = build_graph(track_lines, tol, unit)
    _order_west_east(graph)
    switches, crossings = _switch_legs(graph, unit)
    ends = _ends(graph, page, unit, answers)
    boundaries = _boundaries(page, classes, graph, unit)
    words = list(page.words)
    numbers, track_names, signals, label_refs = _labels(words, graph, figures, boundaries, unit)
    unknown, more = _answered_figures(figures, answers, graph, unit)
    boundaries += more.boundaries
    signals += more.signals
    for node in more.buffer_stops:
        ends[node] = (NodeType.BUFFER_STOP, Certainty.CONFIRMED, False)
    questions = _questions(classes, figures, ends, graph, page, unit, answers)
    notes: list[str] = []
    read_words = [_grow(w.box, 0.3 * unit) for w in page.words]
    unread = [
        box
        for box in _words_of(page.outlined, unit)
        if not any(_gap(box, w) == 0 for w in read_words)
    ]
    if unread and page.kind == "vector":
        notes.append(
            f"{_count(len(unread), 'text', 'texter')} i ritningen är ritade som figurer och kan "
            "inte läsas av koden. Skriv in dem i Studio."
        )
    elif unread:
        notes.append(
            f"{_count(len(unread), 'text', 'texter')} i ritningen är inte avskrivna. Läs "
            "ritningen med AI, så skriver AI:n av dem, eller skriv in dem i Studio."
        )
    return Read(
        unit,
        graph,
        classes,
        figures,
        ends,
        switches,
        crossings,
        boundaries,
        signals,
        numbers,
        track_names,
        label_refs,
        questions,
        unknown,
        notes,
    )


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _words_of(boxes: list[Box], unit: float) -> list[Box]:
    """Glyphs drawn as figures grouped into words."""
    words: list[Box] = []
    for box in sorted(boxes):
        for k, w in enumerate(words):
            if _gap(w, box) < 0.6 * unit:
                words[k] = (
                    min(w[0], box[0]),
                    min(w[1], box[1]),
                    max(w[2], box[2]),
                    max(w[3], box[3]),
                )
                break
        else:
            words.append(box)
    return words


def _order_west_east(graph: Graph) -> None:
    """Nodes and pieces numbered west to east (R4), then north to south."""
    order = sorted(graph.nodes, key=lambda n: (round(graph.nodes[n][0], 1), graph.nodes[n][1]))
    renumber = {old: new for new, old in enumerate(order)}
    graph.nodes = {renumber[n]: graph.nodes[n] for n in order}
    for e in graph.edges:
        e.a, e.b = renumber[e.a], renumber[e.b]
        if (graph.nodes[e.a][0], graph.nodes[e.a][1]) > (graph.nodes[e.b][0], graph.nodes[e.b][1]):
            e.a, e.b = e.b, e.a
            e.points.reverse()
    graph.edges.sort(
        key=lambda e: (
            round(min(p[0] for p in e.points), 1),
            round(sum(p[1] for p in e.points) / len(e.points), 1),
        )
    )


def _switch_legs(
    graph: Graph, unit: float
) -> tuple[dict[int, tuple[int | None, int | None, int | None]], dict[int, list[tuple[int, int]]]]:
    """Each switch's trunk, straight leg and diverging leg; each crossing's two ways through."""
    switches: dict[int, tuple[int | None, int | None, int | None]] = {}
    crossings: dict[int, list[tuple[int, int]]] = {}
    for node in graph.nodes:
        touching = graph.touching(node)
        if len(touching) == 3:
            dirs = {i: _leaving(graph.edges[i], node, unit) for i in touching}
            pairs = [(i, j) for k, i in enumerate(touching) for j in touching[k + 1 :]]
            legs = max(pairs, key=lambda p: _dot(dirs[p[0]], dirs[p[1]]))
            trunk = next(i for i in touching if i not in legs)
            back = (-dirs[trunk][0], -dirs[trunk][1])
            straight = max(legs, key=lambda i: _dot(dirs[i], back))
            diverging = legs[0] if straight == legs[1] else legs[1]
            switches[node] = (trunk, straight, diverging)
        elif len(touching) >= 4:
            dirs = {i: _leaving(graph.edges[i], node, unit) for i in touching}
            ways: list[tuple[int, int]] = []
            left = list(touching)
            while len(left) >= 2:
                i = left.pop(0)
                j = min(left, key=lambda k: _dot(dirs[i], dirs[k]))
                left.remove(j)
                ways.append((i, j))
            crossings[node] = ways
    return switches, crossings


def _ends(
    graph: Graph, page: Page, unit: float, answers: dict[str, str]
) -> dict[int, tuple[NodeType, Certainty, bool]]:
    """Each track's end: a line exit at the drawing's west or east edge, a buffer stop
    inside."""
    if not graph.nodes:
        return {}
    xs = [p[0] for p in graph.nodes.values()]
    west, east = min(xs), max(xs)
    width = max(east - west, 1e-6)
    found: dict[int, tuple[NodeType, Certainty, bool]] = {}
    for node, at in graph.nodes.items():
        if graph.degree(node) != 1:
            continue
        edge = graph.edges[graph.touching(node)[0]]
        inward = _leaving(edge, node, unit)
        share = min(at[0] - west, east - at[0]) / width
        outward = (at[0] - west < east - at[0] and inward[0] > 0.2) or (
            at[0] - west >= east - at[0] and inward[0] < -0.2
        )
        named = any(
            LINE_WORDS.search(w.text) and _gap(w.box, (at[0], at[1], at[0], at[1])) < 4 * unit
            for w in page.words
        )
        if (share <= EXIT_SHARE and outward) or named:
            found[node] = (NodeType.LINE_EXIT, Certainty.PROBABLE, False)
        elif share <= EXIT_ASK and outward:
            found[node] = (NodeType.LINE_EXIT, Certainty.UNCERTAIN, True)
        else:
            found[node] = (NodeType.BUFFER_STOP, Certainty.PROBABLE, False)
        said = answers.get(f"ande.{_node_key(at)}")
        asked = found[node][2]
        if said == "linjeutfart":
            found[node] = (NodeType.LINE_EXIT, Certainty.CONFIRMED, asked)
        elif said == "stoppbock":
            found[node] = (NodeType.BUFFER_STOP, Certainty.CONFIRMED, asked)
    return found


def _node_key(at: Point) -> str:
    """A track end's key in a question: its place, which stays when the graph is read again."""
    return f"{round(at[0])}-{round(at[1])}"


def _boundaries(
    page: Page, classes: list[LineClass], graph: Graph, unit: float
) -> list[tuple[Point, int, Certainty]]:
    """Each stroke of a boundary class where it crosses a track piece."""
    found: list[tuple[Point, int, Certainty]] = []
    for c in classes:
        if c.role != "boundary":
            continue
        certainty = Certainty.PROBABLE if c.certain else Certainty.UNCERTAIN
        for i in c.strokes:
            s = page.strokes[i]
            if not BAR[0] * unit * 0.5 <= s.length <= BAR[1] * unit * 1.5:
                continue
            for a, b in _segments(s.points):
                for k, edge in enumerate(graph.edges):
                    for c0, d0 in _segments(edge.points):
                        hit = crossing(a, b, c0, d0)
                        if hit is None or _angle(_sub(b, a), _sub(d0, c0)) < BAR_ANGLE:
                            continue
                        at = (c0[0] + (d0[0] - c0[0]) * hit[1], c0[1] + (d0[1] - c0[1]) * hit[1])
                        if all(math.dist(at, f[0]) > 0.6 * unit for f in found):
                            found.append(((round(at[0], 2), round(at[1], 2)), k, certainty))
    return found


# --- 5. The labels ----------------------------------------------------------------------------


def _nearest_piece(p: Point, graph: Graph) -> tuple[int | None, float, Point]:
    best: tuple[int | None, float, Point] = (None, math.inf, p)
    for k, edge in enumerate(graph.edges):
        d, q, _ = polyline_distance(p, edge.points)
        if d < best[1]:
            best = (k, d, q)
    return best


def _labels(
    words: list[Word],
    graph: Graph,
    figures: list[Figure],
    boundaries: list[tuple[Point, int, Certainty]],
    unit: float,
) -> tuple[dict[int, int], dict[int, str], list[Signal], dict[int, tuple[str, int] | None]]:
    refs: dict[int, tuple[str, int] | None] = {i: None for i in range(len(words))}
    # A name over its address: "21" and "(1201)" on two lines are one signal's text.
    pairs: dict[int, int] = {}
    for i, w in enumerate(words):
        if not ADDRESS_ONLY.match(w.text):
            continue
        best = None
        for j, v in enumerate(words):
            if j == i or not (NUMBER.match(v.text) or TYPED_NAME.match(v.text)):
                continue
            above = v.box[3] <= w.box[1] + 0.3 * unit and w.box[1] - v.box[3] < 0.8 * unit
            below = w.box[3] <= v.box[1] + 0.3 * unit and v.box[1] - w.box[3] < 0.8 * unit
            if (above or below) and abs(v.box[0] - w.box[0]) < 1.5 * unit:
                gap = _gap(v.box, w.box)
                if best is None or gap < best[0]:
                    best = (gap, j)
        if best is not None:
            pairs[best[1]] = i
    signals: list[Signal] = []
    signal_words: set[int] = set()
    used_figures: set[int] = set()
    signal_figures = [k for k, f in enumerate(figures) if f.kind == "signal"]
    for i, w in enumerate(words):
        if i in pairs.values():
            continue
        text = w.text
        box = w.box
        if i in pairs:
            partner = words[pairs[i]]
            text = f"{w.text} {partner.text}"
            box = (
                min(box[0], partner.box[0]),
                min(box[1], partner.box[1]),
                max(box[2], partner.box[2]),
                max(box[3], partner.box[3]),
            )
        found = SIGNAL_TEXT.match(text) or TYPED_NAME.match(text)
        if found is None:
            continue
        kind = found.group("type")
        address = found.groupdict().get("address")
        signal_type = SIGNAL_TYPES.get(kind.lower()) if kind else None
        # Its figure, beside the text; else the boundary stroke beside it.
        figure = min(
            (
                k
                for k in signal_figures
                if k not in used_figures and _gap(figures[k].box, box) <= SIGNAL_LABEL * unit
            ),
            key=lambda k: _gap(figures[k].box, box),
            default=None,
        )
        signal: Signal | None = None
        if figure is not None:
            used_figures.add(figure)
            signal = _from_figure(figures[figure], graph, boundaries, unit)
            signal.figure = figures[figure]
        else:
            stroke = min(
                range(len(boundaries)),
                key=lambda k: _gap((*boundaries[k][0], *boundaries[k][0]), box),
                default=None,
            )
            if (
                stroke is not None
                and _gap((*boundaries[stroke][0], *boundaries[stroke][0]), box)
                <= SIGNAL_LABEL * unit
            ):
                at, piece, _ = boundaries[stroke]
                centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
                facing: Literal["east", "west"] = "east" if centre[0] < at[0] else "west"
                signal = Signal(
                    None, None, None, None, facing, at, piece, None, None, Certainty.PROBABLE
                )
        if signal is None:
            continue
        signal.name = found.group("name")
        signal.address = int(address) if address else None
        signal.type = signal_type or signal.type or SignalType.HSI
        signal.label = i
        if signal_type is None and signal.lamps is None:
            signal.certainty = Certainty.UNCERTAIN
        if signal_type in (SignalType.HDVSI, SignalType.DVSI):
            signal.lamps = None
        signals.append(signal)
        signal_words.add(i)
        refs[i] = ("signal", len(signals) - 1)
        if i in pairs:
            refs[pairs[i]] = ("signal", len(signals) - 1)
    # Signal figures without a text that code can read: signals without a name.
    for k in signal_figures:
        if k in used_figures:
            continue
        signal = _from_figure(figures[k], graph, boundaries, unit)
        signal.figure = figures[k]
        signal.certainty = Certainty.UNCERTAIN
        signals.append(signal)
    # Switch numbers: the nearest switch, each number to one switch.
    switch_nodes = [n for n in graph.nodes if graph.degree(n) >= 3]
    candidates = []
    for i, w in enumerate(words):
        if i in signal_words or i in pairs.values() or not NUMBER.match(w.text):
            continue
        for n in switch_nodes:
            d = math.dist(w.centre, graph.nodes[n])
            if d <= SWITCH_LABEL * unit:
                candidates.append((d, i, n))
    numbers: dict[int, int] = {}
    taken_words: set[int] = set()
    for _, i, n in sorted(candidates):
        if n in numbers or i in taken_words:
            continue
        numbers[n] = i
        taken_words.add(i)
        refs[i] = ("node", n)
    # Track names: the nearest piece.
    track_names: dict[int, str] = {}
    for i, w in enumerate(words):
        if refs[i] is not None:
            continue
        name = None
        match = TRACK_NAME.match(w.text)
        if match:
            name = match.group("name")
        elif w.text in ROMAN:
            name = str(ROMAN.index(w.text) + 1)
        nearest, d, _ = _nearest_piece(w.centre, graph)
        if nearest is None:
            continue
        if name is not None and d <= TRACK_LABEL * unit:
            track_names.setdefault(nearest, name)
            refs[i] = ("piece", nearest)
        elif d <= TRACK_LABEL * unit:
            refs[i] = ("piece", nearest)
    return numbers, track_names, signals, refs


def _from_figure(
    figure: Figure, graph: Graph, boundaries: list[tuple[Point, int, Certainty]], unit: float
) -> Signal:
    """A signal at its figure: on the nearest track at the foot, facing from foot to head, at
    the boundary stroke when one is that close on the same track."""
    foot = figure.foot or figure.centre
    head = figure.head or figure.centre
    piece, _, at = _nearest_piece(foot, graph)
    facing: Literal["east", "west"] | None = None
    if abs(head[0] - foot[0]) > 0.05 * unit:
        facing = "east" if head[0] > foot[0] else "west"
    for b_at, b_piece, _ in boundaries:
        if b_piece == piece and math.dist(b_at, at) <= SNAP_SIGNAL * unit:
            at = b_at
            break
    lamps = figure.lamps or None
    return Signal(
        None,
        None,
        SignalType.HSI,
        lamps,
        facing,
        (round(at[0], 2), round(at[1], 2)),
        piece,
        None,
        figure,
        Certainty.PROBABLE,
    )


@dataclass
class _More:
    signals: list[Signal] = field(default_factory=list)
    boundaries: list[tuple[Point, int, Certainty]] = field(default_factory=list)
    buffer_stops: list[int] = field(default_factory=list)


def _answered_figures(
    figures: list[Figure], answers: dict[str, str], graph: Graph, unit: float
) -> tuple[list[Figure], _More]:
    """The figures of a type the owner has said what it is, as that; the rest unknown."""
    more = _More()
    unknown: list[Figure] = []
    for f in figures:
        if f.kind == "signal":
            continue
        said = answers.get(f"symbol.{f.type_key}")
        piece, d, at = _nearest_piece(f.centre, graph)
        if said in ("hsi", "hdvsi", "dvsi") and piece is not None and d <= 2 * unit:
            facing: Literal["east", "west"] | None = None
            if f.pointing is not None and abs(math.cos(f.pointing)) > 0.3:
                facing = "east" if math.cos(f.pointing) > 0 else "west"
            more.signals.append(
                Signal(
                    None,
                    None,
                    SIGNAL_TYPES[said],
                    None,
                    facing,
                    at,
                    piece,
                    None,
                    f,
                    Certainty.CONFIRMED,
                )
            )
        elif said == "grans" and piece is not None and d <= 2 * unit:
            more.boundaries.append(((round(at[0], 2), round(at[1], 2)), piece, Certainty.CONFIRMED))
        elif said == "stoppbock":
            ends = [n for n in graph.nodes if graph.degree(n) == 1]
            near = min(ends, key=lambda n: math.dist(graph.nodes[n], f.centre), default=None)
            if near is not None and math.dist(graph.nodes[near], f.centre) <= 2 * unit:
                more.buffer_stops.append(near)
        elif said in ("knapp", "annat"):
            continue
        else:
            unknown.append(f)
    return unknown, more


# --- 6. The questions -------------------------------------------------------------------------


def _questions(
    classes: list[LineClass],
    figures: list[Figure],
    ends: dict[int, tuple[NodeType, Certainty, bool]],
    graph: Graph,
    page: Page,
    unit: float,
    answers: dict[str, str],
) -> list[DrawingQuestion]:
    """The legend first: a question per line class or figure type code cannot place; then the
    track ends it cannot tell."""
    found: list[DrawingQuestion] = []
    for c in sorted(classes, key=lambda c: -c.total):
        if c.certain:
            continue
        what = "strecken" if c.thick else "linjerna"
        code = {"track": "spar", "boundary": "grans", "other": "annat"}[c.role]
        sample = page.strokes[c.strokes[0]].points
        found.append(
            DrawingQuestion(
                key=f"linje.{c.key}",
                kind=DrawingQuestionKind.LEGEND,
                title=f"Vad är de {c.colour} {what}?",
                text=(
                    f"Ritningen har {_count(len(c.strokes), 'sådant streck', 'sådana streck')}. "
                    "Koden tror att de är "
                    + {"spar": "spår", "grans": "spårledningsgränser", "annat": "något annat"}[code]
                    + "."
                ),
                choices=LINE_CHOICES,
                code=code,
                answer=answers.get(f"linje.{c.key}"),
                sample=f"{c.colour} {what}",
                count=len(c.strokes),
                at=(round(sample[0][0], 2), round(sample[0][1], 2)),
            )
        )
    types: dict[str, list[Figure]] = defaultdict(list)
    for f in figures:
        if f.kind != "signal":
            types[f.type_key].append(f)
    for key, members in sorted(types.items(), key=lambda kv: -len(kv[1])):
        first = members[0]
        looks = f"{SAMPLES[first.kind]} {first.colour}"
        found.append(
            DrawingQuestion(
                key=f"symbol.{key}",
                kind=DrawingQuestionKind.LEGEND,
                title=f"Vad betyder {SAMPLES[first.kind]} i den här ritningen?",
                text=(
                    f"Ritningen har {_count(len(members), 'sådan figur', 'sådana figurer')} "
                    f"({looks}). Den finns inte i standardställverkets katalog."
                ),
                choices=SYMBOL_CHOICES,
                code=None,
                answer=answers.get(f"symbol.{key}"),
                sample=looks,
                count=len(members),
                at=(round(first.centre[0], 2), round(first.centre[1], 2)),
            )
        )
    for node, (kind, _, asked) in ends.items():
        if not asked:
            continue
        at = graph.nodes[node]
        found.append(
            DrawingQuestion(
                key=f"ande.{_node_key(at)}",
                kind=DrawingQuestionKind.END,
                title="Hur slutar spåret här?",
                text="Spåret slutar nära ritningens kant. Koden ser inte om det går ut på linjen.",
                choices=END_CHOICES,
                code="linjeutfart" if kind == NodeType.LINE_EXIT else "stoppbock",
                answer=answers.get(f"ande.{_node_key(at)}"),
                sample=None,
                count=1,
                at=(round(at[0], 2), round(at[1], 2)),
            )
        )
    return found


# --- 7. The contract --------------------------------------------------------------------------


@dataclass
class Assembled:
    graph: TrackGraph
    boundaries: list[DrawingBoundary]
    questions: list[DrawingQuestion]
    summary: DrawingSummary
    notes: list[str]


def _origin(certainty: Certainty) -> GraphOrigin:
    return GraphOrigin(source=GraphSource.DRAWING, certainty=certainty)


def assemble(found: Read, page: Page) -> Assembled:
    """The read as the contract: the schema graph numbered west to east, its labels and
    symbols, the boundaries and the questions (R4)."""
    node_id = {n: f"n{k + 1}" for k, n in enumerate(found.graph.nodes)}
    piece_id = {k: f"p{k + 1}" for k in range(len(found.graph.edges))}
    nodes: list[GraphNode] = []
    for n, at in found.graph.nodes.items():
        degree = found.graph.degree(n)
        if degree == 1:
            kind = found.ends.get(n, (NodeType.BUFFER_STOP, Certainty.UNCERTAIN, False))[0]
        elif degree == 3:
            kind = NodeType.SWITCH
        elif degree >= 4:
            kind = NodeType.CROSSING
        else:
            kind = NodeType.JOINT
        nodes.append(GraphNode(id=node_id[n], type=kind, at=(round(at[0], 2), round(at[1], 2))))
    pieces: list[GraphPiece] = []
    for k, e in enumerate(found.graph.edges):
        points = [found.graph.nodes[e.a], *e.points[1:-1], found.graph.nodes[e.b]]
        segments: list[Segment] = [
            LineSegment(
                start=(round(a[0], 2), round(a[1], 2)), end=(round(b[0], 2), round(b[1], 2))
            )
            for a, b in itertools.pairwise(points)
            if math.dist(a, b) > 0.01
        ]
        if not segments:
            continue
        pieces.append(
            GraphPiece(
                id=piece_id[k],
                start=node_id[e.a],
                end=node_id[e.b],
                segments=segments,
                track=found.track_names.get(k),
                origin=_origin(Certainty.PROBABLE),
            )
        )
    words = list(page.words)
    switches: list[GraphSwitch] = []
    for n, (trunk, straight, diverging) in found.switches.items():
        number = found.numbers.get(n)
        switches.append(
            GraphSwitch(
                id=f"v{len(switches) + 1}",
                node=node_id[n],
                type=SwitchType.ORDINARY,
                trunk=piece_id.get(trunk) if trunk is not None else None,
                straight=piece_id.get(straight) if straight is not None else None,
                diverging=piece_id.get(diverging) if diverging is not None else None,
                number=words[number].text[:20] if number is not None else None,
                origin=_origin(Certainty.PROBABLE if number is not None else Certainty.UNCERTAIN),
            )
        )
    for n in found.crossings:
        number = found.numbers.get(n)
        switches.append(
            GraphSwitch(
                id=f"v{len(switches) + 1}",
                node=node_id[n],
                type=SwitchType.CROSSING,
                number=words[number].text[:20] if number is not None else None,
                origin=_origin(Certainty.UNCERTAIN),
            )
        )
    symbols: list[GraphSymbol] = []
    signal_symbol: dict[int, str] = {}
    for k, s in enumerate(found.signals):
        sid = f"s{len(symbols) + 1}"
        signal_symbol[k] = sid
        symbols.append(
            GraphSymbol(
                id=sid,
                kind=SymbolKind.SIGNAL,
                signal=s.type,
                lamps=s.lamps,
                facing=s.facing,
                at=s.at,
                piece=piece_id.get(s.piece) if s.piece is not None else None,
                name=s.name,
                address=s.address,
                label=f"t{s.label + 1}" if s.label is not None else None,
                shape="signalfigur"
                if s.figure is not None and s.figure.kind == "signal"
                else (SAMPLES.get(s.figure.kind) if s.figure is not None else "text"),
                origin=_origin(s.certainty),
            )
        )
    for f in found.unknown:
        piece, d, _ = _nearest_piece(f.centre, found.graph)
        symbols.append(
            GraphSymbol(
                id=f"s{len(symbols) + 1}",
                kind=SymbolKind.UNKNOWN,
                at=(round(f.centre[0], 2), round(f.centre[1], 2)),
                piece=piece_id.get(piece) if piece is not None and d <= 2 * found.unit else None,
                shape=f"{SAMPLES[f.kind]} {f.colour}",
                origin=_origin(Certainty.UNCERTAIN),
            )
        )
    labels: list[GraphLabel] = []
    for i, w in enumerate(words):
        ref = found.label_refs.get(i)
        target: str | None = None
        if ref is not None:
            kind_, index = ref
            if kind_ == "piece":
                target = piece_id.get(index)
            elif kind_ == "node":
                target = node_id.get(index)
            elif kind_ == "signal":
                target = signal_symbol.get(index)
        labels.append(
            GraphLabel(
                id=f"t{i + 1}",
                text=w.text[:40],
                at=(round(w.centre[0], 2), round(w.centre[1], 2)),
                ref=target,
                origin=_origin(
                    Certainty.PROBABLE if w.read_by == "text_layer" else Certainty.UNCERTAIN
                ),
                read_by=w.read_by,
            )
        )
    graph = TrackGraph(
        geometry="schema",
        nodes=nodes,
        pieces=pieces,
        switches=switches,
        labels=labels,
        symbols=symbols,
        complete=True,
        issued=len(nodes) + len(pieces) + len(switches) + len(labels) + len(symbols),
    )
    boundaries = [
        DrawingBoundary(id=f"g{k + 1}", at=at, piece=piece_id.get(piece), origin=_origin(c))
        for k, (at, piece, c) in enumerate(found.boundaries)
    ]
    kinds = Counter(n.type for n in nodes)
    summary = DrawingSummary(
        pieces=len(pieces),
        switches=kinds[NodeType.SWITCH],
        crossings=kinds[NodeType.CROSSING],
        line_exits=kinds[NodeType.LINE_EXIT],
        buffer_stops=kinds[NodeType.BUFFER_STOP],
        signals=len(found.signals),
        boundaries=len(boundaries),
        labels=len(labels),
        unknown_symbols=len(found.unknown),
    )
    return Assembled(graph, boundaries, found.questions, summary, found.notes)


# --- The underlay -------------------------------------------------------------------------

FONT: Final = Path(__file__).parent / "fonts" / "inter.ttf"
"""Inter, the design system's face (SIL Open Font License 1.1, LICENSE-inter.txt beside it):
the same TTF as TKL's deck, so the underlay writes å, ä and ö."""


@cache
def font(size: int) -> Any:
    from PIL import ImageFont

    return ImageFont.truetype(str(FONT), size)


def render(
    page: Page, side: int = 2400
) -> tuple[NDArray[Any], tuple[float, float, float, float, float, float]]:
    """A vector page drawn as a picture for Studio's underlay: its lines, figures and text on
    white, and the transform from the drawing's coordinates to the picture's pixels. A raster
    page is its straightened picture as it is."""
    if page.kind == "raster" and page.pixels is not None:
        return page.pixels, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    from PIL import Image, ImageDraw

    scale = min(4.0, side / max(page.width, page.height, 1.0))
    width, height = max(1, round(page.width * scale)), max(1, round(page.height * scale))
    picture = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(picture)

    def colour(c: RGB) -> tuple[int, int, int]:
        return (round(c[0] * 255), round(c[1] * 255), round(c[2] * 255))

    for s in page.strokes:
        points = [(x * scale, y * scale) for x, y in s.points]
        if s.closed and s.fill is not None and len(points) >= 3:
            draw.polygon(points, fill=colour(s.fill))
        if s.colour is not None and len(points) >= 2:
            line = points + ([points[0]] if s.closed else [])
            draw.line(line, fill=colour(s.colour), width=max(1, round(s.width * scale)))
    for w in page.words:
        size = max(8, round((w.box[3] - w.box[1]) * scale * 0.9))
        draw.text((w.box[0] * scale, w.box[1] * scale), w.text, fill=(0, 0, 0), font=font(size))
    pixels = np.asarray(picture)[:, :, ::-1].copy()
    return pixels, (scale, 0.0, 0.0, scale, 0.0, 0.0)


def underlay_matrix(
    transform: tuple[float, ...],
) -> tuple[float, float, float, float, float, float]:
    a, b, c, d, e, f = (float(v) for v in transform)
    return (a, b, c, d, e, f)


def summary_json(found: Read) -> dict[str, Any]:
    """What a read found, for the log and the reference tests: counts only, never text."""
    return {
        "pieces": len(found.graph.edges),
        "switches": len(found.switches),
        "crossings": len(found.crossings),
        "signals": len(found.signals),
        "boundaries": len(found.boundaries),
        "questions": len(found.questions),
    }
