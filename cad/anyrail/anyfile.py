"""AnyRail's own file (.any), read directly so that the owner need not export anything
(trainmeet-cad-anyrail-import.md, 7; ANYRAIL-01). The file is a Boost binary archive
(serialization::archive, AnyRail), in cm with y down.

The archive is not described anywhere, so the reader takes from it only what the specification
names and what can be checked, and refuses the rest:

- The header: Boost's signature and AnyRail's name; the work area is the first pair of lengths.
- A track part is a record with its article number and its track library (7056 and ATL02R …).
  Its endpoints follow it, each with x, y, a zero and its direction in radians into the part, and
  the library again. A flex has two endpoints and its Bézier curve's control points after them;
  a switch has three endpoints, and its legs are drawn from them: the points are the end the two
  others look back at, the straight leg continues the points' direction, and the diverging leg is
  an arc and a straight tail ending in the third end with its direction (7. AnyRails egen fil).
- The drawing's polygons (the modules' rectangles, the surfaces, the table) are runs of points,
  read as thin lines (rule 1: they are drawing, not track).
- The connections at the end of the file are not needed: ends in one place pointing at each other
  are joined by rule 3 at no distance.

Every read is checked against the file's length (Cursor): a cut or damaged file is refused with a
reason in Swedish, never read past its end. Numbers must be finite and within the drawing.
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from typing import Final

from cad import curves
from cad.anyrail.reader import (
    MAX_BYTES,
    MAX_COORDINATE,
    MAX_ENDPOINTS,
    MAX_PARTS,
    NOT_ANYRAIL,
    Element,
    Endpoint,
    Layout,
    Part,
    Unreadable,
)
from contracts.station_model import Point

SIGNATURE: Final = b"serialization::archive"
LIBRARY: Final = re.compile(rb"([\x03-\x10])\x00{7}([A-Z][A-Z0-9]{2,15})")
ARTICLE: Final = re.compile(rb"([A-Za-z0-9 .\-]{1,24})")
POINT: Final = 0x42
"""The class of a point record: x, y."""
MAX_POINT_RUN: Final = 10_000
THIN: Final = 3.2
"""mm: the width the drawing's polygons are given, as AnyRail's thin lines."""


class Cursor:
    """Reads the archive's numbers within its bounds, or refuses the file."""

    def __init__(self, data: bytes, at: int = 0) -> None:
        self.data = data
        self.at = at

    def take(self, size: int) -> bytes:
        if size < 0 or self.at + size > len(self.data):
            raise Unreadable(f"{NOT_ANYRAIL}: filen slutar mitt i en post.")
        found = self.data[self.at : self.at + size]
        self.at += size
        return found

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return int(struct.unpack("<H", self.take(2))[0])

    def u32(self) -> int:
        return int(struct.unpack("<I", self.take(4))[0])

    def u64(self) -> int:
        return int(struct.unpack("<Q", self.take(8))[0])

    def f64(self) -> float:
        value = float(struct.unpack("<d", self.take(8))[0])
        if not math.isfinite(value):
            raise Unreadable(f"{NOT_ANYRAIL}: ett tal i filen är trasigt.")
        return value

    def text(self, longest: int = 256) -> str:
        size = self.u64()
        if size > longest:
            raise Unreadable(f"{NOT_ANYRAIL}: en text i filen är för lång.")
        return self.take(size).decode("latin-1")


@dataclass(frozen=True)
class _End:
    at: int
    """Where the record's x starts."""
    x: float
    y: float
    direction: float
    """Radians, into the part."""


@dataclass(frozen=True)
class _Header:
    at: int
    article: str
    library: str
    end: int


def _check(value: float, what: str) -> float:
    if not math.isfinite(value) or abs(value) > MAX_COORDINATE:
        raise Unreadable(f"{NOT_ANYRAIL}: {what} ligger utanför ritytan.")
    return value


def _header(data: bytes) -> Cursor:
    cursor = Cursor(data)
    if cursor.u64() != len(SIGNATURE) or cursor.take(len(SIGNATURE)) != SIGNATURE:
        raise Unreadable(f"{NOT_ANYRAIL}: den är inte AnyRails egen fil.")
    cursor.take(6)  # Boost's archive version and its sizes
    if data.find(b"AnyRail", cursor.at, cursor.at + 64) < 0:
        raise Unreadable(f"{NOT_ANYRAIL}: den är inte AnyRails egen fil.")
    return cursor


def _work_area(data: bytes, start: int) -> tuple[float, float]:
    """The first pair of lengths after the header: the work area, cm."""
    for at in range(start, min(len(data) - 16, start + 512)):
        x, y = struct.unpack("<2d", data[at : at + 16])
        if 1 <= x <= 100_000 and 1 <= y <= 100_000 and x == round(x, 3) and y == round(y, 3):
            return x, y
    raise Unreadable(f"{NOT_ANYRAIL}: ritytan saknas.")


def _headers_and_ends(data: bytes) -> tuple[list[_Header], list[_End]]:
    headers: list[_Header] = []
    ends: list[_End] = []
    for match in LIBRARY.finditer(data):
        if int(match.group(1)[0]) != len(match.group(2)):
            continue
        start = match.start()
        library = match.group(2).decode("ascii")
        # An endpoint: x, y, a zero and its direction before the library.
        if start >= 32:
            x, y, z, a = struct.unpack("<4d", data[start - 32 : start])
            if (
                all(math.isfinite(v) for v in (x, y, z, a))
                and z == 0.0
                and -0.001 <= a <= 2 * math.pi + 0.001
                and (x != 0.0 or y != 0.0)
            ):
                ends.append(_End(start - 32, _check(x, "En ändpunkt"), _check(y, "En ändpunkt"), a))
                continue
        # A part: its article number before the library.
        for size in range(1, 25):
            at = start - 8 - size
            if at < 0:
                break
            if struct.unpack("<Q", data[at : at + 8])[0] == size and ARTICLE.fullmatch(
                data[at + 8 : start]
            ):
                headers.append(
                    _Header(at, data[at + 8 : start].decode("ascii").strip(), library, match.end())
                )
                break
    return headers, ends


def _points(data: bytes) -> list[tuple[int, Point]]:
    """Every point record: class 0x42, its object id, x and y."""
    found: list[tuple[int, Point]] = []
    for at in range(0, len(data) - 22):
        if data[at] != POINT or data[at + 1] != 0:
            continue
        x, y = struct.unpack("<2d", data[at + 6 : at + 22])
        finite = math.isfinite(x) and math.isfinite(y) and abs(x) < 1e6 and abs(y) < 1e6
        if finite and (abs(x) > 1e-9 or abs(y) > 1e-9):
            found.append((at, (x, y)))
    return found


def _runs(points: list[tuple[int, Point]]) -> list[tuple[int, list[Point]]]:
    runs: list[tuple[int, list[Point]]] = []
    for at, p in points:
        if runs and at == runs[-1][0] + 22 * len(runs[-1][1]):
            runs[-1][1].append(p)
            if len(runs[-1][1]) > MAX_POINT_RUN:
                raise Unreadable(f"{NOT_ANYRAIL}: en figur har för många punkter.")
        else:
            runs.append((at, [p]))
    return runs


def _class_id(data: bytes, name: bytes) -> bytes | None:
    """The archive's id of a class, written once before the class's name."""
    at = data.find(struct.pack("<Q", len(name)) + name)
    return data[at - 2 : at] if at >= 2 else None


def _object_id(data: bytes, header: int, part_class: bytes | None) -> str | None:
    """A part's object id in the archive, AnyRail's own id for it: the number after the part's
    class just before its article number."""
    if part_class is None:
        return None
    window = data[max(0, header - 48) : header]
    at = window.rfind(part_class)
    if at < 0 or at + 6 > len(window):
        return None
    return str(struct.unpack("<I", window[at + 2 : at + 6])[0])


def _vector(direction: float) -> Point:
    return (math.sin(direction), math.cos(direction))


def _degrees(direction: float) -> float:
    return math.degrees(direction) % 360


def read_any(data: bytes) -> Layout:
    """AnyRail's own file as a Layout."""
    if len(data) > MAX_BYTES:
        raise Unreadable(f"{NOT_ANYRAIL}: den är större än 20 MB.")
    cursor = _header(data)
    length, width = _work_area(data, cursor.at)
    headers, ends = _headers_and_ends(data)
    if not headers:
        raise Unreadable(f"{NOT_ANYRAIL}: den har inga spårdelar.")
    if len(headers) > MAX_PARTS or len(ends) > MAX_ENDPOINTS:
        raise Unreadable(f"{NOT_ANYRAIL}: den har för många delar.")
    runs = _runs(_points(data))
    part_class = _class_id(data, b"CPart")
    parts: list[Part] = []
    endpoints: dict[int, Endpoint] = {}
    used_runs: set[int] = set()
    libraries: list[str] = []
    for k, header in enumerate(headers):
        stop = headers[k + 1].at if k + 1 < len(headers) else len(data)
        own = [e for e in ends if header.end <= e.at < stop]
        if len(own) < 2:
            continue
        numbers: list[int] = []
        for end in own:
            nr = len(endpoints) + 1
            endpoints[nr] = Endpoint(nr, (end.x * 10, end.y * 10), _degrees(end.direction))
            numbers.append(nr)
        last = own[-1].at
        nearby = [
            (at, run)
            for at, run in runs
            if last < at < min(stop, last + 600) and at not in used_runs
        ]
        elements: tuple[Element, ...]
        if len(own) == 2:
            curve = _curve(own, nearby[0][1] if nearby else [])
            if nearby:
                used_runs.add(nearby[0][0])
            elements = (Element("bezier", curve, 16.5),)
            kind = "Flex"
        else:
            elements, kind = _switch(own, _arc_radius(data, header.end, stop))
        parts.append(
            Part(
                id=_object_id(data, header.at, part_class) or f"d{len(parts) + 1}",
                type=kind,
                endpoints=tuple(numbers),
                elements=elements,
                track=True,
                article=header.article,
            )
        )
        libraries.append(header.library)
    # The drawing: every other run of points, as a closed thin outline.
    for at, run in runs:
        if at in used_runs or len(run) < 2:
            continue
        mm = [(x * 10, y * 10) for x, y in run]
        closed = len(mm) > 2
        pairs = list(zip(mm, [*mm[1:], mm[0]] if closed else mm[1:], strict=False))
        parts.append(
            Part(
                id=f"r{len(parts) + 1}",
                type="Drawing",
                endpoints=(),
                elements=tuple(Element("line", (a, b), THIN) for a, b in pairs if a != b),
                track=False,
            )
        )
    if not any(p.track for p in parts):
        raise Unreadable(f"{NOT_ANYRAIL}: den har inga spårdelar.")
    library = max(set(libraries), key=libraries.count) if libraries else None
    return Layout(
        format="any",
        length=length * 10,
        width=width * 10,
        parts=tuple(parts),
        endpoints=endpoints,
        connections=(),
        library=library,
    )


def _curve(own: list[_End], run: list[Point]) -> tuple[Point, ...]:
    """A flex's Bézier curve in mm: its control points, or an even cubic from its ends."""
    a = (own[0].x * 10, own[0].y * 10)
    b = (own[1].x * 10, own[1].y * 10)
    points = [(x * 10, y * 10) for x, y in run]
    if len(points) == 3:
        points = [a, *points]
    if len(points) == 4:
        if math.dist(points[0], a) < 5 and math.dist(points[3], b) < 5:
            return (a, points[1], points[2], b)
        if math.dist(points[0], b) < 5 and math.dist(points[3], a) < 5:
            return (a, points[2], points[1], b)
    third = math.dist(a, b) / 3
    va, vb = _vector(own[0].direction), _vector(own[1].direction)
    return (a, curves.add(a, va, third), curves.add(b, vb, third), b)


def _arc_radius(data: bytes, start: int, stop: int) -> float | None:
    """A switch's arc in its record: the radius, the angle in radians and the length, which is
    the two multiplied; mm, or None when the record has none."""
    for at in range(start, min(stop, len(data)) - 24):
        radius, angle, length = struct.unpack("<3d", data[at : at + 24])
        if not (math.isfinite(radius) and math.isfinite(angle) and math.isfinite(length)):
            continue
        arc = 10 <= radius <= 10_000 and 0.01 < abs(angle) < math.pi / 2 and length > 0
        if arc and abs(length - radius * abs(angle)) <= 0.001 * length:
            return float(radius) * 10
    return None


def _switch(own: list[_End], radius: float | None) -> tuple[tuple[Element, ...], str]:
    """A switch's legs from its three endpoints: the points the end the others look back at."""
    ends = own[:3]

    def looks_back(i: int) -> float:
        into = _vector(ends[i].direction)
        return sum(
            -(into[0] * _vector(ends[j].direction)[0] + into[1] * _vector(ends[j].direction)[1])
            for j in range(3)
            if j != i
        )

    k = max(range(3), key=looks_back)
    points = ends[k]
    others = [ends[j] for j in range(3) if j != k]
    p = (points.x * 10, points.y * 10)
    head = math.atan2(_vector(points.direction)[1], _vector(points.direction)[0])

    def bend(end: _End) -> float:
        arrive = math.atan2(-_vector(end.direction)[1], -_vector(end.direction)[0])
        return curves.wrap(arrive - head)

    others.sort(key=lambda e: abs(bend(e)))
    straightest = others[0]
    y_switch = abs(bend(straightest)) > math.radians(1)
    legs: list[tuple[Point, list[Element]]] = []
    for end in others:
        e = (end.x * 10, end.y * 10)
        turn = bend(end)
        if abs(turn) <= math.radians(0.5):
            legs.append((e, [Element("line", (p, e), 16.5)]))
        else:
            legs.append((e, _arc_and_tail(p, head, e, turn, radius)))
    elements = _parted(p, head, legs)
    kind = (
        "YTurnout"
        if y_switch
        else ("RightRegularTurnout" if bend(others[1]) > 0 else "LeftRegularTurnout")
    )
    return tuple(elements), kind


def _parted(p: Point, head: float, legs: list[tuple[Point, list[Element]]]) -> list[Element]:
    """The switch's elements. Where every curved leg starts with the same straight lead (the
    arc begins a little in from the part's end), the tracks part there: the lead once, then each
    leg from where they part, so that the points lie where the legs separate."""
    curved = [els for _, els in legs if any(x.kind == "arc" for x in els)]
    leads = [els[0] for els in curved if els[0].kind == "line"]
    lengths = [math.dist(*lead.points) for lead in leads]
    if not curved or len(leads) != len(curved) or max(lengths) - min(lengths) > 1.0:
        return [x for _, els in legs for x in els]
    split = curves.add(p, curves.unit(head), min(lengths))
    found = [Element("line", (p, split), 16.5)]
    for e, els in legs:
        if not any(x.kind == "arc" for x in els):
            found.append(Element("line", (split, e), 16.5))
            continue
        first = els[1]
        found.append(
            Element(
                first.kind,
                (split, first.points[1]),
                first.width,
                first.radius,
                first.angle,
                first.direction,
            )
        )
        found += els[2:]
    return found


def _arc_and_tail(
    p: Point, head: float, end: Point, turn: float, known: float | None = None
) -> list[Element]:
    """The diverging leg: straight, an arc turning turn, and straight to the end. With the arc's
    radius from the record, the two straights follow from where the end lies; without it, the leg
    starts with the arc and the radius follows."""
    d = curves.sub(end, p)
    along = curves.unit(head)
    side = curves.unit(head + (math.pi / 2 if turn > 0 else -math.pi / 2))
    u, v = curves.dot(d, along), curves.dot(d, side)
    t = abs(turn)
    if known is not None and math.sin(t) > 1e-9:
        tail = (v - known * (1 - math.cos(t))) / math.sin(t)
        lead = u - known * math.sin(t) - tail * math.cos(t)
        if lead >= -1.0 and tail >= -1.0:
            return _leg(p, head, end, t, turn, known, max(0.0, lead), max(0.0, tail))
    # end = R (sin t, 1 - cos t) + L (cos t, sin t) in (along, side)
    det = math.sin(t) * math.sin(t) - (1 - math.cos(t)) * math.cos(t)
    if abs(det) < 1e-12:
        return [Element("line", (p, end), 16.5)]
    radius = (u * math.sin(t) - v * math.cos(t)) / det
    tail = ((1 - math.cos(t)) * -u + math.sin(t) * v) / det
    if radius <= 0 or tail < -1.0:
        return [Element("line", (p, end), 16.5)]
    return _leg(p, head, end, t, turn, radius, 0.0, tail)


def _leg(
    p: Point,
    head: float,
    end: Point,
    t: float,
    turn: float,
    radius: float,
    lead: float,
    tail: float,
) -> list[Element]:
    along = curves.unit(head)
    side = curves.unit(head + (math.pi / 2 if turn > 0 else -math.pi / 2))
    found: list[Element] = []
    start = p
    if lead > 0.5:
        start = curves.add(p, along, lead)
        found.append(Element("line", (p, start), 16.5))
    arc_end = curves.add(
        curves.add(start, along, radius * math.sin(t)), side, radius * (1 - math.cos(t))
    )
    out = (math.cos(head + math.pi), math.sin(head + math.pi))
    direction = math.degrees(math.atan2(out[0], out[1])) % 360
    found.append(
        Element(
            "arc",
            (start, arc_end),
            16.5,
            radius=radius,
            angle=math.degrees(t),
            direction=direction,
        )
    )
    if tail > 0.5:
        found.append(Element("line", (arc_end, end), 16.5))
    return found
