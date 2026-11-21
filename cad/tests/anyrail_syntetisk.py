"""A made-up AnyRail station, written as AnyRail 2.0's XML export writes it, with a known truth
(#91): the tests' and the browser test's file. The reference stations' real files (an XML export
and AnyRail's own file) are never in the repository; test_anyrail_referens.py reads them where they
lie.

The writer (Drawing) speaks AnyRail's dialect: everything in cm, y down; a part's endpoints with
their direction into the part, the vector (sin d, cos d); an arc as p1, p2, radius, angle and its
direction at p1, pointing out of the arc; a turnout as its straight line and its diverging arc
from the points; modules as thin (0.32 cm) lines from corner cross to corner cross.

station() is the station the tests read, in H0 (positions in mm, x from the west, y down):

    Ä1 [200–900] × [0–355]   1 [900–2400] × [0–700]   2a [2400–3900] × [0–350]
                             2b [2400–3900] × [350–700]   3 [3900–5400] × [0–700]
                                                          Ä2 [5400–6100] × [0–355]

- Spår 1 at y 140 and spår 2 at y 197 from outside the layout in the west (the line) to Ä2, where
  a tight loop binds them (taken away, AR4). Their pieces meet the next module with gaps of 6–10
  mm, spår 1 with a 30 mm overlap at 2a|3, and spår 2 with a backward piece there (3.1).
- Växel 1, AnyRail's right turnout on spår 2 at x 1100; its branch runs as a Bézier curve down
  into 2b and ends there.
- Växel 2, a left turnout on spår 1 at x 2250, over the joint 1|2a; its branch is a flex arc whose
  direction decides its bulge, ending in 2a.
- Växel 3, a right turnout on spår 1 at x 4000; its branch crosses spår 2 once, at 9.4°: a
  crossing.
- Växel 4 is assumed: at x 4800 a flex leaves spår 2 without a switch (rule 5).
- A loose track in a side drawing below the layout.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

TRACK = 1.65
THIN = 0.32
Point = tuple[float, float]


def _deg(vector: Point) -> float:
    """AnyRail's direction of a vector (y down): (sin d, cos d)."""
    return math.degrees(math.atan2(vector[0], vector[1])) % 360


def _unit(heading: float) -> Point:
    return (math.cos(heading), math.sin(heading))


def _num(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


@dataclass
class Part:
    id: int
    type: str
    endpoints: list[int]
    drawing: list[str]


@dataclass
class Drawing:
    """An AnyRail layout being written: positions in mm, written in cm."""

    length: float
    width: float
    parts: list[Part] = field(default_factory=list)
    endpoints: dict[int, tuple[Point, float]] = field(default_factory=dict)
    connections: list[tuple[int, int]] = field(default_factory=list)
    next_id: int = 100
    next_nr: int = 1
    own: list[tuple[str, list[int], list[Point] | None]] = field(default_factory=list)
    """The same track for AnyRail's own file: article, endpoints, Bézier control points."""
    polygons: list[list[Point]] = field(default_factory=list)
    """The drawing's rectangles for AnyRail's own file."""

    def _endpoint(self, at: Point, direction: float) -> int:
        nr = self.next_nr
        self.next_nr += 1
        self.endpoints[nr] = (at, direction % 360)
        return nr

    def _part(self, kind: str, endpoints: list[int], drawing: list[str]) -> int:
        self.next_id += 1
        self.parts.append(Part(self.next_id, kind, endpoints, drawing))
        return self.next_id

    @staticmethod
    def _p(p: Point) -> str:
        return f"{_num(p[0] / 10)}, {_num(p[1] / 10)}, 0"

    # --- Track ------------------------------------------------------------------------------

    def line(self, a: Point, b: Point, width: float = TRACK) -> tuple[int, int]:
        """A flex line from a to b: its two endpoints."""
        d = (b[0] - a[0], b[1] - a[1])
        ea = self._endpoint(a, _deg(d))
        eb = self._endpoint(b, _deg((-d[0], -d[1])))
        if width == TRACK:
            third = [(a[0] + d[0] * k / 3, a[1] + d[1] * k / 3) for k in (1, 2)]
            self.own.append(("7056", [ea, eb], [a, third[0], third[1], b]))
        self._part(
            "Flex",
            [ea, eb],
            [f'<lineCm width="{width}" p1="{self._p(a)}" p2="{self._p(b)}"></lineCm>'],
        )
        return ea, eb

    def arc(
        self, a: Point, heading: float, radius: float, turn: float
    ) -> tuple[int, int, Point, float]:
        """A flex arc from a with a heading (radians, 0 east, positive turning right on the
        drawing), turning turn radians: its endpoints, its end and its end heading."""
        end, head = self._arc_end(a, heading, radius, turn)
        ea = self._endpoint(a, _deg(_unit(heading)))
        eb = self._endpoint(end, _deg(_unit(head + math.pi)))
        out = _deg(_unit(heading + math.pi))  # at p1 = a, pointing out of the arc
        handle = 4 / 3 * math.tan(abs(turn) / 4) * radius
        self.own.append(
            (
                "7056",
                [ea, eb],
                [
                    a,
                    (a[0] + handle * math.cos(heading), a[1] + handle * math.sin(heading)),
                    (end[0] - handle * math.cos(head), end[1] - handle * math.sin(head)),
                    end,
                ],
            )
        )
        self._part(
            "Flex",
            [ea, eb],
            [
                f'<arcCm width="{TRACK}" p1="{self._p(a)}" p2="{self._p(end)}" '
                f'direction="{_num(out)}" angle="{_num(abs(math.degrees(turn)))}" '
                f'radius="{_num(radius / 10)}"></arcCm>'
            ],
        )
        return ea, eb, end, head

    @staticmethod
    def _arc_end(a: Point, heading: float, radius: float, turn: float) -> tuple[Point, float]:
        side = heading + (math.pi / 2 if turn > 0 else -math.pi / 2)
        centre = (a[0] + radius * math.cos(side), a[1] + radius * math.sin(side))
        phi = math.atan2(a[1] - centre[1], a[0] - centre[0]) + turn
        end = (centre[0] + radius * math.cos(phi), centre[1] + radius * math.sin(phi))
        return end, heading + turn

    def bezier(self, c: list[Point], width: float = TRACK) -> tuple[int, int]:
        start = math.atan2(c[1][1] - c[0][1], c[1][0] - c[0][0])
        end = math.atan2(c[3][1] - c[2][1], c[3][0] - c[2][0])
        ea = self._endpoint(c[0], _deg(_unit(start)))
        eb = self._endpoint(c[3], _deg(_unit(end + math.pi)))
        if width == TRACK:
            self.own.append(("7056", [ea, eb], list(c)))
        points = " ".join(
            f'cp{k + 1}="{_num(p[0] / 10)}, {_num(p[1] / 10)}"' for k, p in enumerate(c)
        )
        self._part("Flex", [ea, eb], [f'<bezierCm width="{width}" {points}></bezierCm>'])
        return ea, eb

    def turnout(
        self, points: Point, heading: float, side: str, radius: float = 2200.0, angle: float = 9.4
    ) -> tuple[int, int, int, Point, Point, float]:
        """AnyRail's regular turnout: straight line and diverging arc from the points. side is
        right (turning right on the drawing) or left. Its endpoints (points, straight end,
        diverging end), the straight end, the diverging end and its heading."""
        turn = math.radians(angle) * (1 if side == "right" else -1)
        div, head = self._arc_end(points, heading, radius, turn)
        straight = (
            points[0] + radius * math.sin(math.radians(angle)) * math.cos(heading),
            points[1] + radius * math.sin(math.radians(angle)) * math.sin(heading),
        )
        ep = self._endpoint(points, _deg(_unit(heading)))
        es = self._endpoint(straight, _deg(_unit(heading + math.pi)))
        ed = self._endpoint(div, _deg(_unit(head + math.pi)))
        out = _deg(_unit(head))  # at p1 = the diverging end, pointing out of the arc
        kind = "RightRegularTurnout" if side == "right" else "LeftRegularTurnout"
        self.own.append(("7025" if side == "right" else "7024", [ep, es, ed], None))
        self._part(
            kind,
            [ep, es, ed],
            [
                f'<lineCm width="{TRACK}" p1="{self._p(points)}" '
                f'p2="{self._p(straight)}"></lineCm>',
                f'<arcCm width="{TRACK}" p1="{self._p(div)}" p2="{self._p(points)}" '
                f'direction="{_num(out)}" angle="{_num(angle)}" '
                f'radius="{_num(radius / 10)}"></arcCm>',
            ],
        )
        return ep, es, ed, straight, div, head

    def connect(self, a: int, b: int) -> None:
        self.connections.append((a, b))

    # --- The drawing --------------------------------------------------------------------------

    def module(self, x: float, y: float, length: float, width: float, angle: float = 0.0) -> None:
        """A module as AnyRail's users draw it: four thin edges stopping 30 mm before each
        corner, and a thin cross on each corner."""
        a = math.radians(angle)
        along = (math.cos(a), -math.sin(a))
        across = (math.sin(a), math.cos(a))

        def at(u: float, v: float) -> Point:
            return (x + along[0] * u + across[0] * v, y + along[1] * u + across[1] * v)

        corners = [(0.0, 0.0), (length, 0.0), (length, width), (0.0, width)]
        self.polygons.append([at(u, v) for u, v in corners])
        for (u0, v0), (u1, v1) in zip(corners, corners[1:] + corners[:1], strict=True):
            du, dv = u1 - u0, v1 - v0
            size = math.hypot(du, dv)
            gap_u, gap_v = du / size * 30, dv / size * 30
            self.line(at(u0 + gap_u, v0 + gap_v), at(u1 - gap_u, v1 - gap_v), width=THIN)
        for u, v in corners:
            ends = [self._endpoint(at(u, v), 0) for _ in range(4)]
            self._part(
                "Crossing",
                ends,
                [
                    f'<lineCm width="{THIN}" p1="{self._p(at(u - 30, v))}" '
                    f'p2="{self._p(at(u + 30, v))}"></lineCm>',
                    f'<lineCm width="{THIN}" p1="{self._p(at(u, v - 30))}" '
                    f'p2="{self._p(at(u, v + 30))}"></lineCm>',
                ],
            )

    def circle(self, centre: Point, radius: float) -> None:
        """A thin circle, as four quarter arcs (a turntable's pit)."""
        for k in range(4):
            phi = k * math.pi / 2
            start = (centre[0] + radius * math.cos(phi), centre[1] + radius * math.sin(phi))
            heading = phi + math.pi / 2
            end, _ = self._arc_end(start, heading, radius, math.pi / 2)
            out = _deg(_unit(heading + math.pi))
            ea = self._endpoint(start, 0)
            eb = self._endpoint(end, 0)
            self._part(
                "Flex",
                [ea, eb],
                [
                    f'<arcCm width="{THIN}" p1="{self._p(start)}" p2="{self._p(end)}" '
                    f'direction="{_num(out)}" angle="90" radius="{_num(radius / 10)}"></arcCm>'
                ],
            )

    def any_file(self, library: str = "SYNT01") -> bytes:
        """AnyRail's own file as the reader knows it (cad/anyrail/anyfile.py): Boost's header, the
        work area, the drawing's rectangles as runs of points, and each track part with its
        article, its library (made up: SYNT01, so read as H0), its endpoints (x, y, 0, radians
        into the part) and a flex's control points, in cm. The connections are left out: the
        reader joins ends by place."""

        def u32(v: int) -> bytes:
            return struct.pack("<I", v)

        def text(v: str) -> bytes:
            return struct.pack("<Q", len(v)) + v.encode("ascii")

        def point(oid: int, p: Point) -> bytes:
            return b"\x42\x00" + u32(oid) + struct.pack("<2d", p[0] / 10, p[1] / 10)

        out = bytearray(text("serialization::archive") + b"\x11\x00\x04\x04\x04\x08")
        out += text("AnyRail") + b"\x00" * 6
        out += struct.pack("<2d", self.length / 10, self.width / 10) + b"\x00" * 32
        oid = 1000
        for polygon in self.polygons:
            out += b"\x00" * 700
            for p in polygon:
                oid += 1
                out += point(oid, p)
        out += b"\x00" * 700 + b"\x31\x00" + text("CPart") + b"\x01" + b"\x00" * 12
        for article, ends, control in self.own:
            oid += 13
            out += b"\x00" * 64 + b"\x31\x00" + u32(oid) + b"\x00" * 20
            out += text(article) + text(library) + b"\x00" * 40
            for nr in ends:
                (x, y), degrees = self.endpoints[nr]
                out += b"\x3e\x00" + u32(oid) + u32(nr)
                out += struct.pack("<4d", x / 10, y / 10, 0.0, math.radians(degrees))
                out += text(library) + b"\x00" * 8
            if control is not None:
                for p in control:
                    oid += 1
                    out += point(oid, p)
        return bytes(out + b"\x00" * 64)

    def xml(self) -> bytes:
        parts = "".join(
            f'<part type="{p.type}" id="{p.id}" hidden="false" bridge="false"><endpointNrs>'
            + "".join(f"<endpointNr>{e}</endpointNr>" for e in p.endpoints)
            + "</endpointNrs><drawing>"
            + "".join(p.drawing)
            + "</drawing></part>"
            for p in self.parts
        )
        endpoints = "".join(
            f'<endpoint nr="{nr}" coord="0,0,0" coordCm="{self._p(at)}" direction="{_num(d)}">'
            "</endpoint>"
            for nr, (at, d) in self.endpoints.items()
        )
        connections = "".join(
            f'<connection endpoint1="{a}" endpoint2="{b}"></connection>'
            for a, b in self.connections
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" ?>\n'
            f'<layout version="2.0" workAreaLengthCm="{_num(self.length / 10)}" '
            f'workAreaWidthCm="{_num(self.width / 10)}"><parts>{parts}</parts>'
            f"<endpoints>{endpoints}</endpoints><connections>{connections}</connections>"
            "<clearances></clearances></layout>"
        ).encode()


# --- The station ---------------------------------------------------------------------------

EAST = 0.0


def station() -> Drawing:
    d = Drawing(length=6400.0, width=1500.0)
    d.module(200, 0, 700, 355)  # Ä1
    d.module(900, 0, 1500, 700)  # 1
    d.module(2400, 0, 1500, 350)  # 2a
    d.module(2400, 350, 1500, 350)  # 2b
    d.module(3900, 0, 1500, 700)  # 3
    d.module(5400, 0, 700, 355)  # Ä2

    # Spår 1, y 140, from the line in the west.
    lead = math.radians(9.4)
    d.line((100, 140), (895, 140))
    _, b_end = d.line((905, 140), (2250, 140))  # gap 10 mm at Ä1|1 (rule 3)
    p2, s2, e2, _, div2, head2 = d.turnout((2250, 140), EAST, "left")  # växel 2, over 1|2a
    d.connect(b_end, p2)
    c, _ = d.line((2250 + 2200 * math.sin(lead), 140), (3915, 140))
    d.connect(s2, c)
    _, o_end = d.line((3885, 140), (4000, 140))  # 30 mm overlap at 2a|3 (rule 3)
    p3, s3, e3, _, div3, head3 = d.turnout((4000, 140), EAST, "right")  # växel 3
    d.connect(o_end, p3)
    f, _ = d.line((4000 + 2200 * math.sin(lead), 140), (5397, 140))
    d.connect(s3, f)
    _, t1_end = d.line((5403, 140), (6050, 140))  # gap 6 mm at 3|Ä2

    # Spår 2, y 197.
    d.line((100, 197), (896, 197))
    _, b2_end = d.line((904, 197), (1100, 197))  # gap 8 mm
    p1, s1, e1, _, div1, head1 = d.turnout((1100, 197), EAST, "right")  # växel 1
    d.connect(b2_end, p1)
    c2, _ = d.line((1100 + 2200 * math.sin(lead), 197), (2395, 197))
    d.connect(s1, c2)
    _, d2_end = d.line((2405, 197), (3915, 197))  # gap 10 mm at 1|2a
    back_a, back_b = d.bezier([(3915, 197), (3935, 197), (3865, 197.5), (3885, 197)])  # 3.1
    d.connect(d2_end, back_a)
    e2_, e2_end = d.line((3885, 197), (4800, 197))
    d.connect(back_b, e2_)
    f2, _ = d.line((4800, 197), (5396, 197))
    d.connect(e2_end, f2)
    _, t2_end = d.line((5404, 197), (6050, 197))  # gap 8 mm

    # The loop behind Ä2 binds spår 1 and 2 (AR4).
    la, lb = d.bezier([(6050, 140), (6090, 140), (6090, 197), (6050, 197)])
    d.connect(t1_end, la)
    d.connect(t2_end, lb)

    # Växel 1's branch: down into 2b, ending there.
    k1, k1_end = d.bezier(
        [
            div1,
            (div1[0] + 280 * math.cos(head1), div1[1] + 280 * math.sin(head1)),
            (2020, 450),
            (2300, 450),
        ]
    )
    d.connect(e1, k1)
    k2, _ = d.line((2300, 450), (2396, 450))
    d.connect(k1_end, k2)
    d.line((2404, 450), (3600, 450))  # gap 8 mm at 1|2b

    # Växel 2's branch: a flex arc back to straight, ending in 2a.
    a4, b4, end4, _ = d.arc(div2, head2, 2200.0, math.radians(9.4))
    d.connect(e2, a4)
    l4, _ = d.line(end4, (3300, end4[1]))
    d.connect(b4, l4)

    # Växel 3's branch crosses spår 2 once, at 9.4°, and ends.
    run = 340.0
    g3, _ = d.line(div3, (div3[0] + run * math.cos(head3), div3[1] + run * math.sin(head3)))
    d.connect(e3, g3)

    # Växel 4, assumed: a flex leaves spår 2 at x 4800 without a switch.
    d.bezier([(4800, 197), (5000, 197), (5100, 300), (5300, 300)])

    # A loose track in a side drawing below the layout.
    d.line((1000, 1100), (1600, 1100))
    return d


def station_xml() -> bytes:
    return station().xml()


def station_any() -> bytes:
    """The same station as AnyRail's own file."""
    return station().any_file()


if __name__ == "__main__":
    import sys
    from pathlib import Path

    # The browser test's file: python -m cad.tests.anyrail_syntetisk <file.xml>
    Path(sys.argv[1]).write_bytes(station_xml())
