"""DXF out of CAD (#89 del d1, CAD-07, CAD-24): a module's or an assembly's geometry as an ASCII
DXF, with the track centres as real LINE and ARC (lärdomarna, Ren geometri).

The format is AutoCAD R12 (AC1009): HEADER, TABLES (LTYPE, LAYER, STYLE), an empty BLOCKS and
ENTITIES, in mm. R12 needs no handles, owners or OBJECTS section, so every CAD program and
library reads it: AutoCAD, LibreCAD, QCAD, FreeCAD, Fusion and ezdxf. Its entities are LINE, ARC,
CIRCLE, TEXT and POLYLINE with VERTEX and SEQEND; R12 has no LWPOLYLINE, so a closed outline is a
POLYLINE. Texts are in Windows-1252 ($DWGCODEPAGE ANSI_1252), and a character outside it is
written \\U+XXXX, as AutoCAD reads it.

Coordinates: everything is given in CAD's drawing coordinates (x from gable A along Kant 1, y
away from Kant 1, y down, as contracts/cad.py) and written with y turned up, so the DXF looks as
the drawing does: gable A at Kant 1 is (0, 0) and the module lies below the x axis. A module in
an assembly is placed with a Placement: shifted and turned, as PlacedModule.

The writer takes geometry, never a module id: draw_module() draws one module's shape, gables,
track graph and (if given) landscape onto a Dxf, and an assembly draws each of its modules onto
the same Dxf with its own Placement. read() parses a DXF back, for the tests.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from cad import curves, geometry
from cad.switches import GAUGE
from contracts.cad import (
    ArcSegment,
    Curve,
    CurveSides,
    EdgeSide,
    Gable,
    GableEnd,
    LandscapeArea,
    LineSegment,
    Scale,
    Shape,
    Surface,
    TrackGraph,
)
from contracts.station_model import Point

NEWLINE: Final = "\r\n"
Align = Literal["left", "centre", "right"]


@dataclass(frozen=True)
class Layer:
    """A layer: its name (A–Z, 0–9, - and _), AutoCAD's colour index and its line type."""

    name: str
    colour: int
    linetype: str = "CONTINUOUS"


OUTLINE: Final = Layer("MODUL", 7)
"""The board's outline."""
KANT1: Final = Layer("KANT1", 1)
"""Kant 1, the edge every gable measure is taken from."""
GABLES: Final = Layer("GAVEL", 3)
"""The gable marks: a tick where each track goes through the gable, its measure from Kant 1."""
CENTRES: Final = Layer("SPARMITT", 5, "DASHDOT")
"""The track centres: LINE and ARC."""
RAILS: Final = Layer("RALS", 8)
"""The rails, optional: the centres offset by half the gauge and rail head."""
SWITCHES: Final = Layer("VAXEL", 6)
TEXTS: Final = Layer("TEXT", 7)
MEASURES: Final = Layer("MATT", 4)
DRAFT: Final = Layer("UTKAST", 1)
"""Only on a draft: UTKAST over the module."""
LANDSCAPE: Final = {
    Surface.GRASS: Layer("LANDSKAP-GRAS", 3),
    Surface.BALLAST: Layer("LANDSKAP-BALLAST", 8),
    Surface.GROUND: Layer("LANDSKAP-MARK", 33),
    Surface.PLATFORM: Layer("LANDSKAP-PLATTFORM", 9),
    Surface.WATER: Layer("LANDSKAP-VATTEN", 5),
    Surface.BUILDING: Layer("LANDSKAP-BYGGNAD", 1),
    Surface.TREES: Layer("LANDSKAP-TRAD", 94),
    Surface.PATH: Layer("LANDSKAP-STIG", 41),
    Surface.UNKNOWN: Layer("LANDSKAP-OKAND", 211),
}
"""A layer per surface (Landskapet): closed POLYLINEs; the track bed is LANDSKAP-BALLAST."""

LINETYPES: Final = {
    "CONTINUOUS": ("Solid line", ()),
    "DASHDOT": ("Dash dot __ . __ . __", (12.0, -3.0, 0.0, -3.0)),
}


def _number(value: float, decimals: int = 6) -> str:
    text = f"{value:.{decimals}f}"
    return "0." + "0" * decimals if text.lstrip("-").strip("0.") == "" else text


def _text(value: str) -> str:
    """A text value in Windows-1252, other characters as \\U+XXXX; never a line break."""
    found = []
    for char in value.replace("\r", " ").replace("\n", " "):
        try:
            char.encode("cp1252")
            found.append(char)
        except UnicodeEncodeError:
            found.append(f"\\U+{ord(char):04X}")
    return "".join(found)


@dataclass(frozen=True)
class Placement:
    """Where a module lies in a larger drawing: its origin (gable A at Kant 1) at at, turned angle
    degrees counterclockwise as the drawing shows it, as PlacedModule. The default is the module
    on its own."""

    at: Point = (0.0, 0.0)
    angle: float = 0.0

    def point(self, p: Point) -> Point:
        a = math.radians(self.angle)
        c, s = math.cos(a), math.sin(a)
        # y is down: a turn that looks counterclockwise is clockwise in the numbers.
        return (self.at[0] + p[0] * c + p[1] * s, self.at[1] - p[0] * s + p[1] * c)


@dataclass
class Dxf:
    """An ASCII DXF R12 drawing in mm, built in CAD's drawing coordinates (y down)."""

    layers: dict[str, Layer] = field(default_factory=dict)
    _entities: list[str] = field(default_factory=list)
    _xs: list[float] = field(default_factory=list)
    _ys: list[float] = field(default_factory=list)

    def layer(self, layer: Layer) -> str:
        known = self.layers.setdefault(layer.name, layer)
        return known.name

    def _pairs(self, *pairs: tuple[int, str | float | int]) -> None:
        for code, value in pairs:
            if isinstance(value, float):
                value = _number(value, 8 if code in (50, 51) else 6)
            self._entities.append(f"{code:>3}{NEWLINE}{value}{NEWLINE}")

    def _seen(self, *points: Point) -> None:
        for x, y in points:
            self._xs.append(x)
            self._ys.append(-y)

    def line(self, layer: Layer, start: Point, end: Point) -> None:
        self._seen(start, end)
        self._pairs(
            (0, "LINE"),
            (8, self.layer(layer)),
            (10, float(start[0])),
            (20, float(-start[1])),
            (30, 0.0),
            (11, float(end[0])),
            (21, float(-end[1])),
            (31, 0.0),
        )

    def circle(self, layer: Layer, centre: Point, radius: float) -> None:
        self._seen(
            (centre[0] - radius, centre[1] - radius), (centre[0] + radius, centre[1] + radius)
        )
        self._pairs(
            (0, "CIRCLE"),
            (8, self.layer(layer)),
            (10, float(centre[0])),
            (20, float(-centre[1])),
            (30, 0.0),
            (40, float(radius)),
        )

    def arc(
        self, layer: Layer, centre: Point, radius: float, start: Point, end: Point, clockwise: bool
    ) -> None:
        """An arc from start to end around centre, clockwise as the drawing shows it. DXF's ARC
        runs counterclockwise from its start angle to its end angle, with y up; the picture is
        the same, so a clockwise arc is DXF's from end to start."""
        if math.dist(start, end) < 1e-9:
            self.circle(layer, centre, radius)
            return
        seg = curves.Arc(start, end, centre, radius, clockwise)
        total = curves.length(seg)
        self._seen(*(curves.point_at(seg, total * k / 16) for k in range(17)))

        def angle(p: Point) -> float:
            return math.degrees(math.atan2(-(p[1] - centre[1]), p[0] - centre[0])) % 360.0

        first, last = (end, start) if clockwise else (start, end)
        self._pairs(
            (0, "ARC"),
            (8, self.layer(layer)),
            (10, float(centre[0])),
            (20, float(-centre[1])),
            (30, 0.0),
            (40, float(radius)),
            (50, angle(first)),
            (51, angle(last)),
        )

    def segment(
        self,
        layer: Layer,
        seg: LineSegment | ArcSegment | curves.Seg,
        place: Placement | None = None,
    ) -> None:
        """A track piece's LINE or ARC, placed."""
        place = place or Placement()
        if isinstance(seg, LineSegment | curves.Line):
            self.line(layer, place.point(seg.start), place.point(seg.end))
            return
        self.arc(
            layer,
            place.point(seg.center),
            seg.radius,
            place.point(seg.start),
            place.point(seg.end),
            seg.clockwise,
        )

    def polyline(self, layer: Layer, points: Sequence[Point], closed: bool = False) -> None:
        if len(points) < 2:
            return
        self._seen(*points)
        name = self.layer(layer)
        self._pairs(
            (0, "POLYLINE"),
            (8, name),
            (66, 1),
            (10, 0.0),
            (20, 0.0),
            (30, 0.0),
            (70, 1 if closed else 0),
        )
        for x, y in points:
            self._pairs((0, "VERTEX"), (8, name), (10, float(x)), (20, float(-y)), (30, 0.0))
        self._pairs((0, "SEQEND"), (8, name))

    def text(
        self,
        layer: Layer,
        at: Point,
        height: float,
        value: str,
        angle: float = 0.0,
        align: Align = "left",
    ) -> None:
        """A line of text at at (its baseline's left, middle or right), turned angle degrees
        counterclockwise."""
        self._seen(at)
        justify = {"left": 0, "centre": 1, "right": 2}[align]
        pairs: list[tuple[int, str | float | int]] = [
            (0, "TEXT"),
            (8, self.layer(layer)),
            (10, float(at[0])),
            (20, float(-at[1])),
            (30, 0.0),
            (40, float(height)),
            (1, _text(value)),
        ]
        if angle:
            pairs.append((50, float(angle % 360.0)))
        if justify:
            pairs += [(72, justify), (11, float(at[0])), (21, float(-at[1])), (31, 0.0)]
        self._pairs(*pairs)

    def write(self) -> bytes:
        """The whole file."""
        out: list[str] = []

        def pair(code: int, value: str | float | int) -> None:
            if isinstance(value, float):
                value = _number(value)
            out.append(f"{code:>3}{NEWLINE}{value}{NEWLINE}")

        xs = self._xs or [0.0]
        ys = self._ys or [0.0]
        pair(0, "SECTION")
        pair(2, "HEADER")
        pair(9, "$ACADVER")
        pair(1, "AC1009")
        pair(9, "$DWGCODEPAGE")
        pair(3, "ANSI_1252")
        pair(9, "$INSBASE")
        for code in (10, 20, 30):
            pair(code, 0.0)
        pair(9, "$EXTMIN")
        pair(10, float(min(xs)))
        pair(20, float(min(ys)))
        pair(30, 0.0)
        pair(9, "$EXTMAX")
        pair(10, float(max(xs)))
        pair(20, float(max(ys)))
        pair(30, 0.0)
        pair(0, "ENDSEC")
        pair(0, "SECTION")
        pair(2, "TABLES")
        pair(0, "TABLE")
        pair(2, "LTYPE")
        pair(70, len(LINETYPES))
        for name, (description, pattern) in LINETYPES.items():
            pair(0, "LTYPE")
            pair(2, name)
            pair(70, 0)
            pair(3, description)
            pair(72, 65)
            pair(73, len(pattern))
            pair(40, float(sum(abs(d) for d in pattern)))
            for dash in pattern:
                pair(49, float(dash))
        pair(0, "ENDTAB")
        layers = [Layer("0", 7), *(v for k, v in self.layers.items() if k != "0")]
        pair(0, "TABLE")
        pair(2, "LAYER")
        pair(70, len(layers))
        for layer in layers:
            pair(0, "LAYER")
            pair(2, layer.name)
            pair(70, 0)
            pair(62, layer.colour)
            pair(6, layer.linetype)
        pair(0, "ENDTAB")
        pair(0, "TABLE")
        pair(2, "STYLE")
        pair(70, 1)
        pair(0, "STYLE")
        pair(2, "STANDARD")
        pair(70, 0)
        pair(40, 0.0)
        pair(41, 1.0)
        pair(50, 0.0)
        pair(71, 0)
        pair(42, 2.5)
        pair(3, "txt")
        pair(4, "")
        pair(0, "ENDTAB")
        pair(0, "ENDSEC")
        pair(0, "SECTION")
        pair(2, "BLOCKS")
        pair(0, "ENDSEC")
        pair(0, "SECTION")
        pair(2, "ENTITIES")
        body = "".join(out) + "".join(self._entities)
        tail: list[str] = []
        for code, value in ((0, "ENDSEC"), (0, "EOF")):
            tail.append(f"{code:>3}{NEWLINE}{value}{NEWLINE}")
        return (body + "".join(tail)).encode("cp1252")


# --- One module --------------------------------------------------------------------------


def offset(seg: curves.Seg, distance: float) -> curves.Seg | None:
    """The segment moved distance mm to its right (negative: left), as a rail beside the
    centre; None when an arc would have no radius left."""
    if isinstance(seg, curves.Line):
        head = curves.heading(seg.start, seg.end)
        n = curves.unit(head + math.pi / 2)
        return curves.Line(curves.add(seg.start, n, distance), curves.add(seg.end, n, distance))
    radius = seg.radius - distance if seg.clockwise else seg.radius + distance
    if radius <= 0:
        return None

    def out(p: Point) -> Point:
        return curves.add(seg.center, curves.sub(p, seg.center), radius / seg.radius)

    return curves.Arc(out(seg.start), out(seg.end), seg.center, radius, seg.clockwise)


def outline_segments(shape: Shape, track1: float) -> tuple[list[curves.Seg], list[curves.Seg]]:
    """The board's outline as LINE and ARC: Kant 1, and the rest (the gables and the far side)."""
    if isinstance(shape, Curve) and shape.sides == CurveSides.BENT:
        centre = geometry.centre(shape, track1)
        clockwise = shape.edge == EdgeSide.OUTER
        a0, a1 = (
            geometry.point_on(shape, track1, 0, 0),
            geometry.point_on(shape, track1, 0, shape.angle),
        )
        b0, b1 = (
            geometry.point_on(shape, track1, shape.width, 0),
            geometry.point_on(shape, track1, shape.width, shape.angle),
        )
        kant1 = curves.Arc(a0, a1, centre, geometry.edge_radius(shape, track1), clockwise)
        far = curves.Arc(
            b0, b1, centre, geometry.line_radius(shape, track1, shape.width), clockwise
        )
        return [kant1], [curves.Line(a1, b1), far, curves.Line(b0, a0)]
    corners = geometry.outline(shape, track1)
    lines: list[curves.Seg] = [
        curves.Line(a, b) for a, b in zip(corners, corners[1:] + corners[:1], strict=True)
    ]
    return lines[:1], lines[1:]


@dataclass(frozen=True)
class ModuleSheet:
    """What draw_module writes beside the geometry."""

    title: str = ""
    """Under the module: its number, name and version."""
    draft: bool = False
    """UTKAST over the module (a draft exports with Utkast, CAD-17)."""
    rails: bool = False
    landscape: Sequence[LandscapeArea] = ()
    track_bed: Sequence[Sequence[Point]] = ()


def draw_module(
    doc: Dxf,
    shape: Shape,
    gables: Sequence[Gable],
    graph: TrackGraph,
    scale: Scale,
    place: Placement | None = None,
    sheet: ModuleSheet | None = None,
) -> None:
    """One module onto the drawing: the outline and Kant 1, the gable marks with their measures
    from Kant 1, the track centres as LINE and ARC, the rails if asked, the switches, the texts,
    and the landscape's surfaces if given."""
    place = place or Placement()
    sheet = sheet or ModuleSheet()
    track1 = geometry.track1_of(gables[0].tracks if gables else [])
    for area in sheet.landscape:
        layer = LANDSCAPE[area.surface]
        doc.polyline(layer, [place.point(p) for p in area.outline], closed=True)
        for hole in area.holes:
            doc.polyline(layer, [place.point(p) for p in hole], closed=True)
    for ring in sheet.track_bed:
        doc.polyline(LANDSCAPE[Surface.BALLAST], [place.point(p) for p in ring], closed=True)
    edge, rest = outline_segments(shape, track1)
    for seg in edge:
        doc.segment(KANT1, seg, place)
    for seg in rest:
        doc.segment(OUTLINE, seg, place)
    size = max(geometry.length_of(shape), max(geometry.width_at(shape, e) for e in "AB"))
    letters = max(4.0, min(12.0, size / 120))
    for gable in gables:
        line = geometry.gable_line(shape, track1, gable.end)
        out = (-line.inward[0], -line.inward[1])
        for at in gable.tracks:
            p = line.point(at)
            doc.line(
                GABLES,
                place.point(curves.add(p, out, 6)),
                place.point(curves.add(p, line.inward, 6)),
            )
            mark = curves.add(p, out, 8 + letters)
            doc.text(GABLES, place.point(mark), letters * 0.8, f"{at:g}", place.angle, "centre")
        middle = line.point(line.width / 2)
        doc.text(
            GABLES,
            place.point(curves.add(middle, out, 10 + 3 * letters)),
            letters * 1.2,
            gable.end.value,
            place.angle,
            "centre",
        )
    doc.text(TEXTS, place.point((4.0, -4.0)), letters, "KANT 1", place.angle)
    half = (GAUGE[scale] + GAUGE[scale] / 16.5) / 2
    for piece in graph.pieces:
        for segment in piece.segments:
            doc.segment(CENTRES, segment, place)
            if sheet.rails:
                seg = curves.from_segment(segment)
                for side in (-half, half):
                    rail = offset(seg, side)
                    if rail is not None:
                        doc.segment(RAILS, rail, place)
    nodes = {n.id: n for n in graph.nodes}
    for switch in graph.switches:
        node = nodes.get(switch.node)
        if node is None:
            continue
        doc.circle(SWITCHES, place.point(node.at), max(2.0, letters / 2))
        if switch.number:
            doc.text(
                SWITCHES,
                place.point((node.at[0] + letters, node.at[1] - letters)),
                letters * 0.8,
                switch.number,
                place.angle,
            )
    for label in graph.labels:
        doc.text(TEXTS, place.point(label.at), letters * 0.8, label.text, place.angle)
    _measures(doc, shape, track1, place, letters)
    low = max(p[1] for p in geometry.outline(shape, track1))
    if sheet.title:
        doc.text(
            TEXTS, place.point((0.0, low + 6 * letters)), letters * 1.4, sheet.title, place.angle
        )
    if sheet.draft:
        xs = [p[0] for p in geometry.outline(shape, track1)]
        ys = [p[1] for p in geometry.outline(shape, track1)]
        middle = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        doc.text(DRAFT, place.point(middle), size / 8, "UTKAST", place.angle, "centre")
        doc.text(
            DRAFT,
            place.point((0.0, low + 9 * letters)),
            letters,
            "Utkast: modulen är inte godkänd",
            place.angle,
        )


def _measures(doc: Dxf, shape: Shape, track1: float, place: Placement, letters: float) -> None:
    """The main measures as plain lines and texts (no DIMENSION entities): the length along
    Kant 1 and the widths at the gables, or a curve's radius and angle."""
    if isinstance(shape, Curve):
        text = f"R {shape.radius:.1f} mm (spår 1) · {shape.angle:.2f}° · bredd {shape.width:g} mm"
        doc.text(MEASURES, place.point((0.0, -6 * letters)), letters, text, place.angle)
        return
    gap = 4 * letters
    length = geometry.length_of(shape)
    doc.line(MEASURES, place.point((0.0, -gap)), place.point((length, -gap)))
    for x in (0.0, length):
        doc.line(
            MEASURES, place.point((x, -gap - letters / 2)), place.point((x, -gap + letters / 2))
        )
    doc.text(
        MEASURES,
        place.point((length / 2, -gap - letters / 2)),
        letters,
        f"{length:g}",
        place.angle,
        "centre",
    )
    for end in (GableEnd.A, GableEnd.B):
        line = geometry.gable_line(shape, track1, end)
        out = (-line.inward[0], -line.inward[1])
        a = curves.add(line.point(0), out, gap)
        b = curves.add(line.point(line.width), out, gap)
        doc.line(MEASURES, place.point(a), place.point(b))
        middle = curves.add(line.point(line.width / 2), out, gap + letters / 2)
        doc.text(
            MEASURES, place.point(middle), letters, f"{line.width:g}", place.angle + 90, "centre"
        )


# --- Reading it back ---------------------------------------------------------------------


@dataclass
class Entity:
    kind: str
    layer: str
    values: dict[int, list[str]] = field(default_factory=dict)
    vertices: list[Point] = field(default_factory=list)

    def number(self, code: int, index: int = 0) -> float:
        return float(self.values[code][index])

    def point(self, x: int = 10) -> Point:
        """A point, with y turned back down as CAD's drawing has it."""
        return (self.number(x), -self.number(x + 10))


@dataclass
class Read:
    version: str
    layers: dict[str, int]
    entities: list[Entity]

    def of(self, kind: str, layer: str | None = None) -> list[Entity]:
        return [e for e in self.entities if e.kind == kind and (layer is None or e.layer == layer)]


def _pairs(data: bytes) -> Iterable[tuple[int, str]]:
    lines = data.decode("cp1252").splitlines()
    for i in range(0, len(lines) - 1, 2):
        yield int(lines[i].strip()), lines[i + 1].strip()


def read(data: bytes) -> Read:
    """A DXF's version, layers and entities (LINE, ARC, CIRCLE, TEXT, POLYLINE with its
    vertices). Enough to check what this writer writes; not a general reader."""
    pairs = list(_pairs(data))
    version = ""
    layers: dict[str, int] = {}
    entities: list[Entity] = []
    section = ""
    current: Entity | None = None
    polyline: Entity | None = None
    for i, (code, value) in enumerate(pairs):
        if code == 2 and i and pairs[i - 1] == (0, "SECTION"):
            section = value
        if code == 9 and value == "$ACADVER" and i + 1 < len(pairs):
            version = pairs[i + 1][1]
        if code == 0:
            if current is not None and section in ("TABLES", "ENTITIES"):
                if current.kind == "LAYER":
                    layers[current.values[2][0]] = int(current.values[62][0])
                elif current.kind == "VERTEX" and polyline is not None:
                    polyline.vertices.append(current.point())
                elif current.kind in ("LINE", "ARC", "CIRCLE", "TEXT"):
                    entities.append(current)
                elif current.kind == "POLYLINE":
                    polyline = current
                    entities.append(current)
            if value == "SEQEND":
                polyline = None
            current = Entity(kind=value, layer="")
            continue
        if current is not None:
            current.values.setdefault(code, []).append(value)
            if code == 8:
                current.layer = value
    return Read(version=version, layers=layers, entities=entities)


def arc_ends(entity: Entity) -> tuple[Point, Point]:
    """An ARC's two ends, counterclockwise order as DXF has them, in CAD's coordinates."""
    cx, cy = entity.number(10), entity.number(20)
    r = entity.number(40)
    found: list[Point] = []
    for code in (50, 51):
        a = math.radians(entity.number(code))
        found.append((cx + r * math.cos(a), -(cy + r * math.sin(a))))
    return found[0], found[1]
