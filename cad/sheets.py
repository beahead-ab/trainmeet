"""The module on paper (#89 del d1, CAD-07): the FREMO sheet and the print, as SVG pages in mm.

Both are A4 landscape, drawn by code from the version's geometry, and printed by the browser as
the hub prints its pages (a print view and the browser's own Skriv ut, which also saves a PDF).

FREMO-ritning (fremo_sheet): the module sheet as a module list wants it, in black lines:
- the plan from above in a round scale (1:5, 1:10 …): the board with Kant 1 drawn heavier, the
  track centres, the switches with their numbers, a mark and a measure where each track goes
  through a gable, and the main measures: the length along Kant 1 and the widths at the gables,
  a trapezoid's förskjutning, or a curve's radius and angle (exact, CAD16);
- both gables seen from outside, Kant 1 marked, with the tracks' positions as a chain of
  measures from Kant 1 (Kant 1 → spår 1, spår 1 → spår 2 …), the norm and the profile;
- the title block: name, number, owner, scale, version and status, and the drawing's scale.
Utskrift (print_sheet): the module with its landscape in colour, the track bed and the tracks on
top, the legend with each surface's area, and the module's facts.

A draft has UTKAST across the page and in the title (CAD-17).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from xml.sax.saxutils import escape

from cad import curves, geometry
from cad.dxf import outline_segments
from contracts.cad import (
    NORM_NAMES,
    SURFACE_COLOURS,
    SURFACE_NAMES,
    Curve,
    GableEnd,
    LandscapeArea,
    Module,
    ModuleStatus,
    Straight,
    Surface,
    SurfaceTotal,
    Trapezoid,
)
from contracts.station_model import Point

PAGE_W, PAGE_H = 297.0, 210.0
"""A4 landscape, mm."""
SCALES = (1, 2, 2.5, 5, 10, 20, 25, 50, 100)
FONT = "Helvetica, Arial, sans-serif"
MINUS = chr(0x2212)


def number(value: float, decimals: int = 1) -> str:
    """A measure as a Swedish reader writes it: decimal comma, no trailing zero."""
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".") if decimals else f"{value:.0f}"
    return text.replace(".", ",").replace("-", MINUS)


def size_text(module: Module) -> str:
    shape = module.shape
    if isinstance(shape, Straight):
        return f"{number(shape.length)} × {number(shape.width)} mm"
    if isinstance(shape, Trapezoid):
        return f"{number(shape.length)} × {number(shape.width_a)}/{number(shape.width_b)} mm" + (
            f", förskjutning {number(shape.offset)} mm" if shape.offset else ""
        )
    return (
        f"R {number(shape.radius, 1)} mm (spår 1) · {number(shape.angle, 2)}° · "
        f"bredd {number(shape.width)} mm"
    )


def shape_name(module: Module) -> str:
    return {"straight": "Rak", "curve": "Kurva", "trapezoid": "Trapets"}[module.shape.kind]


def status_text(module: Module) -> str:
    if module.status == ModuleStatus.APPROVED:
        day = f" {module.approved_at:%Y-%m-%d}" if module.approved_at else ""
        return f"Godkänd{day}"
    return "Utkast, inte godkänd"


@dataclass
class Svg:
    """An SVG page in mm."""

    parts: list[str]

    @classmethod
    def page(cls, title: str) -> Svg:
        return cls(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{PAGE_W:g}mm" height="{PAGE_H:g}mm" viewBox="0 0 {PAGE_W:g} {PAGE_H:g}" '
                f'font-family="{FONT}">',
                f"<title>{escape(title)}</title>",
                f'<rect width="{PAGE_W:g}" height="{PAGE_H:g}" fill="#fff"/>',
            ]
        )

    def add(self, text: str) -> None:
        self.parts.append(text)

    def text(
        self,
        at: Point,
        value: str,
        size: float,
        anchor: str = "start",
        weight: str = "normal",
        angle: float = 0.0,
        fill: str = "#111",
    ) -> None:
        turn = f' transform="rotate({angle:g} {at[0]:.2f} {at[1]:.2f})"' if angle else ""
        self.parts.append(
            f'<text x="{at[0]:.2f}" y="{at[1]:.2f}" font-size="{size:g}" '
            f'text-anchor="{anchor}" font-weight="{weight}" fill="{fill}"{turn}>'
            f"{escape(value)}</text>"
        )

    def line(self, a: Point, b: Point, width: float = 0.25, dash: str | None = None) -> None:
        dashed = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<path d="M{a[0]:.2f} {a[1]:.2f}L{b[0]:.2f} {b[1]:.2f}" stroke="#111" '
            f'stroke-width="{width:g}" fill="none"{dashed}/>'
        )

    def done(self) -> str:
        return "\n".join([*self.parts, "</svg>", ""])


@dataclass(frozen=True)
class Frame:
    """The module's mm on the paper: x' = left + (x - x0) / scale, likewise y."""

    x0: float
    y0: float
    left: float
    top: float
    scale: float

    def at(self, p: Point) -> Point:
        return (self.left + (p[0] - self.x0) / self.scale, self.top + (p[1] - self.y0) / self.scale)

    def path(self, segs: Sequence[curves.Seg]) -> str:
        found: list[str] = []
        for seg in segs:
            a, b = self.at(seg.start), self.at(seg.end)
            if not found or found[-1] != f"{a[0]:.2f} {a[1]:.2f}":
                found.append(f"M{a[0]:.2f} {a[1]:.2f}")
            if isinstance(seg, curves.Line):
                found.append(f"L{b[0]:.2f} {b[1]:.2f}")
            else:
                large = 1 if curves.sweep(seg) > math.pi else 0
                r = seg.radius / self.scale
                found.append(
                    f"A{r:.3f} {r:.3f} 0 {large} {1 if seg.clockwise else 0} {b[0]:.2f} {b[1]:.2f}"
                )
        return "".join(found)

    def ring(self, points: Sequence[Point]) -> str:
        return "M" + "L".join(f"{self.at(p)[0]:.2f} {self.at(p)[1]:.2f}" for p in points) + "Z"


def fit(module: Module, left: float, top: float, width: float, height: float) -> Frame:
    """The roundest scale at which the board fits the box, centred in it."""
    track1 = geometry.track1_of(module.gables[0].tracks)
    board = geometry.outline(module.shape, track1)
    xs, ys = [p[0] for p in board], [p[1] for p in board]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    scale = next((s for s in SCALES if w / s <= width and h / s <= height), SCALES[-1])
    return Frame(
        x0=min(xs),
        y0=min(ys),
        left=left + (width - w / scale) / 2,
        top=top + (height - h / scale) / 2,
        scale=float(scale),
    )


def _plan(svg: Svg, module: Module, frame: Frame, *, measures: bool) -> None:
    """The board, Kant 1, the tracks, the switches and the gable marks."""
    track1 = geometry.track1_of(module.gables[0].tracks)
    edge, rest = outline_segments(module.shape, track1)
    svg.add(
        f'<path d="{frame.path([*edge, *rest])}Z" fill="none" stroke="#111" stroke-width="0.3"/>'
    )
    svg.add(f'<path d="{frame.path(edge)}" fill="none" stroke="#111" stroke-width="0.9"/>')
    for piece in module.graph.pieces:
        segs = [curves.from_segment(s) for s in piece.segments]
        svg.add(
            f'<path d="{frame.path(segs)}" fill="none" stroke="#1d3fa0" stroke-width="0.5" '
            'stroke-linecap="round"/>'
        )
    nodes = {n.id: n for n in module.graph.nodes}
    for switch in module.graph.switches:
        node = nodes.get(switch.node)
        if node is None:
            continue
        at = frame.at(node.at)
        svg.add(
            f'<circle cx="{at[0]:.2f}" cy="{at[1]:.2f}" r="0.9" fill="#fff" stroke="#111" '
            'stroke-width="0.25"/>'
        )
        if switch.number:
            svg.text((at[0] + 1.4, at[1] - 1.2), switch.number, 2.2)
    for gable in module.gables:
        line = geometry.gable_line(module.shape, track1, gable.end)
        out = (-line.inward[0], -line.inward[1])
        for offset in gable.tracks:
            p = line.point(offset)
            a = frame.at(curves.add(p, out, 2.5 * frame.scale))
            b = frame.at(curves.add(p, line.inward, 2.5 * frame.scale))
            svg.line(a, b, 0.3)
            if measures:
                t = frame.at(curves.add(p, out, 6 * frame.scale))
                svg.text((t[0], t[1] + 0.8), number(offset), 2.2, "middle")
        # Under the gable's far corner, clear of the width's measure beside the gable.
        far = frame.at(line.point(line.width))
        svg.text((far[0], far[1] + 5.5), f"Gavel {gable.end.value}", 2.8, "middle", "bold")
    k = frame.at((0.0, 0.0))
    svg.text((k[0] + 1, k[1] - 1.4), "KANT 1", 2.2, weight="bold")


def _dimensions(svg: Svg, module: Module, frame: Frame) -> None:
    shape = module.shape
    track1 = geometry.track1_of(module.gables[0].tracks)
    if isinstance(shape, Curve):
        # Above the board, clear of Kant 1's arc.
        board = [frame.at(p) for p in geometry.outline(shape, track1)]
        a = ((min(p[0] for p in board) + max(p[0] for p in board)) / 2, frame.top - 6)
        svg.text((a[0], a[1] - 3.4), size_text(module), 2.6, "middle")
        if shape.measured:
            svg.text(
                (a[0], a[1]),
                f"Snöre {number(shape.measured.chord)} mm, pilhöjd "
                f"{number(shape.measured.sagitta)} mm",
                2.2,
                "middle",
            )
        return
    length = geometry.length_of(shape)
    y = frame.at((0.0, 0.0))[1] - 7
    xa, xb = frame.at((0.0, 0.0))[0], frame.at((length, 0.0))[0]
    svg.line((xa, y), (xb, y), 0.2)
    for x in (xa, xb):
        svg.line((x, y - 1.2), (x, y + 1.2), 0.2)
    svg.text(((xa + xb) / 2, y - 0.8), number(length), 2.6, "middle")
    for end in (GableEnd.A, GableEnd.B):
        line = geometry.gable_line(shape, track1, end)
        side = -1 if end == GableEnd.A else 1
        p0, p1 = frame.at(line.point(0)), frame.at(line.point(line.width))
        x = p0[0] + side * 16
        svg.line((x, p0[1]), (x, p1[1]), 0.2)
        for y_ in (p0[1], p1[1]):
            svg.line((x - 1.2, y_), (x + 1.2, y_), 0.2)
        # The text's glyphs stand on the outer side of its line.
        middle = (x + side * 1.0, (p0[1] + p1[1]) / 2)
        svg.text(middle, number(line.width), 2.6, "middle", angle=-90 if side < 0 else 90)
    if isinstance(shape, Trapezoid) and shape.offset:
        b0 = frame.at((length, shape.offset))
        svg.text((b0[0] + 2, b0[1] - 1.5), f"förskjutning {number(shape.offset)}", 2.2)


def _gable_view(svg: Svg, module: Module, end: GableEnd, left: float, top: float) -> None:
    """A gable from outside, Kant 1 to the left at A and to the right at B, with the chain of
    measures from Kant 1."""
    gable = next(g for g in module.gables if g.end == end)
    width = geometry.width_at(module.shape, end.value)
    box = 78.0
    scale = next((s for s in SCALES if width / s <= box - 6), SCALES[-1])
    w = width / scale
    x0 = left + (box - w) / 2

    def x(offset: float) -> float:
        return x0 + offset / scale if end == GableEnd.A else x0 + w - offset / scale

    norm = NORM_NAMES[gable.norm] if gable.norm else "egen norm"
    svg.text((left, top), f"Gavel {end.value} sedd utifrån · 1:{number(scale)}", 2.8, weight="bold")
    svg.text((left, top + 4), f"{gable.label} · {norm}", 2.3)
    base = top + 20
    svg.add(
        f'<rect x="{x0:.2f}" y="{base:.2f}" width="{w:.2f}" height="6" fill="none" '
        'stroke="#111" stroke-width="0.3"/>'
    )
    kant = x(0)
    svg.line((kant, base), (kant, base + 6), 1.0)
    svg.text((kant, base + 10), "KANT 1", 2.0, "start" if end == GableEnd.A else "end", "bold")
    before = 0.0
    for i, offset in enumerate(gable.tracks, start=1):
        p = x(offset)
        svg.add(
            f'<rect x="{p - 1.2:.2f}" y="{base - 1.2:.2f}" width="2.4" height="1.2" fill="#111"/>'
        )
        svg.text((p, base + 4.2), str(i), 2.2, "middle")
        y = base - 4 - (2.6 if (i % 2 == 0 and abs(offset - before) / scale < 6) else 0)
        svg.line((x(before), y), (p, y), 0.2)
        svg.line((p, y - 1), (p, base - 1.2), 0.15)
        svg.text(((x(before) + p) / 2, y - 0.6), number(offset - before), 2.2, "middle")
        before = offset
    if not gable.tracks:
        svg.text((x0 + w / 2, base - 2), "inga spår", 2.2, "middle")


def _draft(svg: Svg) -> None:
    svg.add(
        f'<text x="{PAGE_W / 2:g}" y="{PAGE_H / 2 + 12:g}" font-size="46" text-anchor="middle" '
        'font-weight="bold" fill="#c2410c" fill-opacity="0.16" '
        f'transform="rotate(-18 {PAGE_W / 2:g} {PAGE_H / 2:g})">UTKAST</text>'
    )


def _title_block(svg: Svg, module: Module, kind: str, scale: float | None) -> None:
    left, top, width = 182.0, 166.0, 105.0
    svg.add(
        f'<rect x="{left:g}" y="{top:g}" width="{width:g}" height="34" fill="none" '
        'stroke="#111" stroke-width="0.35"/>'
    )
    svg.line((left, top + 13), (left + width, top + 13), 0.2)
    svg.text((left + 3, top + 5), f"{kind} · TrainMeet CAD", 2.4)
    svg.text((left + 3, top + 10.6), module.name, 4.4, weight="bold")
    svg.text((left + 3, top + 18), f"{module.number} · version {module.version}", 2.6)
    status = status_text(module)
    svg.text(
        (left + width - 3, top + 18),
        status.upper() if module.status != ModuleStatus.APPROVED else status,
        2.6,
        "end",
        "bold",
        fill="#c2410c" if module.status != ModuleStatus.APPROVED else "#111",
    )
    svg.text((left + 3, top + 23.5), f"Ägare: {module.owner.name}", 2.4)
    svg.text((left + 3, top + 28.5), f"Skala {module.scale.value} · {shape_name(module)}", 2.4)
    if scale is not None:
        svg.text((left + width - 3, top + 28.5), f"Ritningen 1:{number(scale)}", 2.4, "end")
    svg.text((left + 3, top + 32.6), "Mått i mm, gavelmåtten från Kant 1.", 2.0, fill="#555")


def fremo_sheet(module: Module) -> str:
    """FREMO-ritning: the module sheet."""
    svg = Svg.page(f"FREMO-ritning · {module.number} {module.name}")
    svg.add(
        f'<rect x="10" y="10" width="{PAGE_W - 20:g}" height="{PAGE_H - 20:g}" fill="none" '
        'stroke="#111" stroke-width="0.5"/>'
    )
    if module.status != ModuleStatus.APPROVED:
        _draft(svg)
    frame = fit(module, 40, 34, PAGE_W - 80, 96)
    _plan(svg, module, frame, measures=True)
    _dimensions(svg, module, frame)
    svg.text((16, 18), "Ovanifrån", 3.2, weight="bold")
    svg.text(
        (16, 22.5),
        f"1:{number(frame.scale)} · spårmitt blå, Kant 1 tjock · "
        f"{len(module.graph.switches)} växlar · {number(module.track_length / 1000, 2)} m spår",
        2.3,
    )
    _gable_view(svg, module, GableEnd.A, 16, 152)
    _gable_view(svg, module, GableEnd.B, 99, 152)
    _title_block(svg, module, "FREMO-ritning", frame.scale)
    return svg.done()


@dataclass(frozen=True)
class SheetLandscape:
    areas: Sequence[LandscapeArea]
    track_bed: Sequence[Sequence[Point]]
    totals: Sequence[SurfaceTotal]


def print_sheet(module: Module, landscape: SheetLandscape | None) -> str:
    """Utskrift: the module with its landscape, the legend and the facts."""
    svg = Svg.page(f"Utskrift · {module.number} {module.name}")
    if module.status != ModuleStatus.APPROVED:
        _draft(svg)
    svg.text((14, 20), module.name, 7, weight="bold")
    svg.text(
        (14, 27),
        f"{module.number} · version {module.version} · {status_text(module)} · "
        f"skala {module.scale.value}",
        3.2,
        fill="#c2410c" if module.status != ModuleStatus.APPROVED else "#333",
    )
    frame = fit(module, 14, 36, 200, 118)
    if landscape is not None:
        for area in landscape.areas:
            rings = [area.outline, *area.holes]
            colour = SURFACE_COLOURS[area.surface]
            svg.add(
                f'<path d="{"".join(frame.ring(r) for r in rings)}" fill="{colour}" '
                f'fill-rule="evenodd" stroke="{colour}" stroke-width="0.3"/>'
            )
        if landscape.track_bed:
            colour = SURFACE_COLOURS[Surface.BALLAST]
            svg.add(
                f'<path d="{"".join(frame.ring(r) for r in landscape.track_bed)}" '
                f'fill="{colour}" fill-rule="evenodd"/>'
            )
    _plan(svg, module, frame, measures=False)
    svg.text((14, 160), f"Ovanifrån, 1:{number(frame.scale)}", 2.6, fill="#555")
    # The legend, and the facts.
    left = 226.0
    y = 40.0
    if landscape is not None and landscape.totals:
        svg.text((left, y), "Landskapet", 3.4, weight="bold")
        y += 6
        for total in landscape.totals:
            svg.add(
                f'<rect x="{left:g}" y="{y - 3:g}" width="4" height="4" '
                f'fill="{SURFACE_COLOURS[total.surface]}" stroke="#555" stroke-width="0.15"/>'
            )
            svg.text((left + 6, y), SURFACE_NAMES[total.surface], 2.8)
            svg.text(
                (left + 58, y),
                f"{number(total.area / 1e6, 2)} m² · {number(total.share * 100, 0)} %",
                2.6,
                "end",
            )
            y += 5
        y += 4
    svg.text((left, y), "Modulen", 3.4, weight="bold")
    y += 6
    facts = [
        ("Mått", size_text(module)),
        ("Form", shape_name(module)),
        ("Spår", f"{number(module.track_length / 1000, 2)} m, {len(module.graph.switches)} växlar"),
        *(
            (
                f"Gavel {g.end.value}",
                f"{g.label}: " + (" / ".join(number(t) for t in g.tracks) or "inga spår"),
            )
            for g in module.gables
        ),
        ("Ägare", module.owner.name),
    ]
    for label, value in facts:
        svg.text((left, y), label, 2.4, fill="#555")
        y += 3.6
        svg.text((left, y), value, 2.7)
        y += 5.4
    svg.text((14, 200), "TrainMeet CAD · mått i mm, gavelmåtten från Kant 1", 2.2, fill="#555")
    return svg.done()
