"""What a real Stream Deck shows (#86 del b): every key, the touch strip and the info line drawn
as pictures at the deck's own size, from the same faces as the deck on the screen (SD3, SD6).

One renderer for every real deck: the local TKL's USB driver (tkl/deck/usb.py) and the browser's
WebHID bridge (apps/tkl/src/deckhid.ts) both show these pictures, so a deck looks the same
everywhere. The look is the prototype's canvas (src/streamdeck.js in the specification, `rita`):
the background, the band at the top for a route's colour, the frame, the line at the bottom for
the chosen page, the red dot for a hindered route, the green mark for a train ready to send
(SD62), and the text in the middle with a line over
and a line under. From the deck on the screen (apps/tkl/src/deck.css) come the train number's
chip, the place's bar, the star and the signal numbers, and Spårplan's keys draw their piece of
the panel with the tracks in their state, the signals as triangles and the train numbers. The
shunter's deck (#87 del d) uses the same marks, and its Fika draws a cup.

Everything is drawn at the size asked for, never a bitmap scaled: 72 px on the 15, 80 on Mini,
96 on XL and Neo, 112 on + XL, 120 on +, and 80 × 120 on Studio.

The fonts are the design system's: TrainMeet Mono for the text in the middle and the numbers,
Inter for the lines over and under. Both are under the SIL Open Font License 1.1 and lie in
tkl/deck/fonts/ with their licences. They are the web app's WOFF2 files in apps/design/src/fonts/,
unpacked once to TTF with fontTools and otherwise unchanged, so that Pillow reads them on every
computer, also where its FreeType cannot read WOFF2:

    uv run --no-project --with fonttools --with brotli python -c "from fontTools.ttLib import \
TTFont; f = TTFont('apps/design/src/fonts/inter.woff2'); f.flavor = None; \
f.save('tkl/deck/fonts/inter.ttf')"

and the same for trainmeet-mono. The fonts' Latin subsets have no arrows, triangles or stars:
those are drawn as simple shapes (SD6).
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

from PIL import Image, ImageDraw, ImageFont

from contracts.tkl import (
    DeckPlanDrawn,
    Panel,
    TklDeckFace,
    TklDeckStrip,
    TklDeckTile,
    TklDeckView,
    TklInterlocking,
)

FONTS: Final = Path(__file__).resolve().parent / "fonts"
MONO: Final = FONTS / "trainmeet-mono.ttf"
SANS: Final = FONTS / "inter.ttf"
VERSION: Final = "1"
"""The renderer's version, in every ETag: a new look gives new pictures everywhere."""
SIZES: Final = (72, 80, 96, 112, 120)
"""The keys' sizes on Elgato's decks, in pixels (docs/tkl-streamdeck-modeller.md)."""
SMALLEST: Final = 32
LARGEST: Final = 256
BLINK_SECONDS: Final = 0.5
"""A blinking key changes colour every half second, as the prototype's (SD13, SD15)."""
ON_SCREEN: Final = 64
"""The deck on the screen draws a key at 64 px: its fixed sizes are scaled from there."""
PLAN_COLOURS: Final = {
    "free": "#8a939c",
    "train": "#22c55e",
    "shunting": "#eab308",
    "occupied": "#ef4444",
    "local": "#38bdf8",
    "out_of_service": "#6b7280",
    "programming": "#a78bfa",
}
RELAY_TRACK: Final = "#4b5563"
RELAY_DARK: Final = "#1f2937"
STRIP_BG: Final = "#000000"
STRIP_LINE: Final = "#2d3238"
STRIP_LABEL: Final = "#9ca3af"
STRIP_VALUE: Final = "#f3f4f6"
INFO_FG: Final = "#93c5fd"
NO_FG: Final = "#fca5a5"
SHAPES: Final = frozenset("▶◀▲▼★→✕")
"""Characters the fonts lack, drawn as simple shapes (SD6)."""

Cell = tuple[float, float]
_LOCK = threading.Lock()


# --- the panel behind Spårplan's keys (SD70–SD72) ----------------------------------------------


@dataclass(frozen=True)
class PlanLine:
    piece: str
    cells: tuple[Cell, ...]
    state: str


@dataclass(frozen=True)
class PlanSignal:
    name: str
    symbol: Cell
    toward: Cell
    aspect: str


@dataclass(frozen=True)
class PlanNumber:
    number: str
    colour: str
    at: Cell


@dataclass(frozen=True)
class Picture:
    """The panel as Spårplan's keys draw it: the tracks in their state, the signals with their
    aspect and where the train numbers stand, in the panel's cells."""

    cell: Cell
    lines: tuple[PlanLine, ...]
    signals: tuple[PlanSignal, ...]
    numbers: tuple[PlanNumber, ...]


def _distance(a: Cell, b: Cell) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _length(cells: Sequence[Cell]) -> float:
    return sum(_distance(cells[i - 1], cells[i]) for i in range(1, len(cells)))


def _along(cells: Sequence[Cell], d: float) -> Cell:
    """The point `d` cells along a polyline from its start."""
    walked = 0.0
    for i in range(1, len(cells)):
        a, b = cells[i - 1], cells[i]
        step = _distance(a, b)
        if walked + step >= d and step:
            t = (d - walked) / step
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        walked += step
    return cells[-1]


def _above(cells: Sequence[Cell], lift: float) -> Cell:
    """A point over the middle of a line, as the panel puts a train number (stallverk.ts)."""
    total = _length(cells)
    p = _along(cells, total / 2)
    q = _along(cells, min(total, total / 2 + 0.25))
    nx, ny = -(q[1] - p[1]), q[0] - p[0]
    n = math.hypot(nx, ny)
    if not n:
        return (p[0], p[1] - lift)
    nx, ny = nx / n, ny / n
    if ny > 0 or (ny == 0 and nx > 0):
        nx, ny = -nx, -ny
    return (p[0] + nx * lift, p[1] + ny * lift)


def picture(panel: Panel, state: TklInterlocking, busy: Iterable[str] = ()) -> Picture:
    """The panel with the interlocking's state, as the panel draws it (apps/tkl/src/stallverk.ts,
    drawing): a line exit's piece is occupied when the hub says a train is on the line (`busy`),
    and the leg a switch does not lie in is not red for the trunk's occupation."""
    lines_busy = set(busy)
    by_piece = {line.piece: line for line in panel.lines}
    off_legs: dict[str, str] = {}
    for s in panel.switches:
        parts = [s.number] if s.number in state.switches else s.number.split("/")
        shown = next((state.switches[p] for p in parts if p in state.switches), None)
        position = shown.position if shown is not None else None
        if position is not None and s.trunk and s.straight and s.diverging:
            off = s.diverging if position.value == "+" else s.straight
            if off in by_piece:
                off_legs[off] = s.trunk
    outside = {piece: e.exit for e in state.exits for piece in e.pieces}
    lines: list[PlanLine] = []
    for line in panel.lines:
        shown_piece = state.pieces.get(line.piece)
        found = shown_piece.state.value if shown_piece is not None else "free"
        exit_id = outside.get(line.piece)
        if exit_id is not None and found != "occupied":
            found = "occupied" if exit_id in lines_busy else "free"
        trunk = off_legs.get(line.piece)
        trunk_state = state.pieces.get(trunk) if trunk is not None else None
        if (
            found == "occupied"
            and trunk_state is not None
            and trunk_state.state.value == "occupied"
        ):
            found = "free"
        lines.append(PlanLine(line.piece, tuple((c[0], c[1]) for c in line.cells), found))
    signals = tuple(
        PlanSignal(
            s.name,
            (s.symbol[0], s.symbol[1]),
            (s.toward[0], s.toward[1]),
            state.signals[s.name].aspect.value if s.name in state.signals else "stop",
        )
        for s in panel.signals
    )
    numbers: list[PlanNumber] = []
    for n in state.numbers:
        spot = _number_spot(panel, n.track, n.exit, n.pieces)
        if spot is not None:
            numbers.append(PlanNumber(n.number or "", n.colour.value, spot))
    return Picture((panel.cell[0], panel.cell[1]), tuple(lines), signals, tuple(numbers))


def _number_spot(
    panel: Panel, track: str | None, exit_id: str | None, pieces: Sequence[str]
) -> Cell | None:
    """Where the panel puts a train number (stallverk.ts, numberSpot)."""
    if track:
        found = next((t for t in panel.track_names if t.name == track), None)
        if found is not None:
            return (found.train_number[0] + 1.5, found.train_number[1] + 0.55)
    if exit_id:
        label = next((lb for lb in panel.labels if lb.kind == "exit" and lb.text == exit_id), None)
        if label is not None and label.anchor != "middle":
            return (label.cell[0], label.cell[1])
    wanted = set(pieces)
    lines = [line for line in panel.lines if line.piece in wanted]
    if not lines:
        return None
    longest = max(lines, key=lambda line: _length(line.cells))
    return _above([(c[0], c[1]) for c in longest.cells], 0.7)


def _inside(c: Cell, tile: TklDeckTile) -> bool:
    return tile.x <= c[0] < tile.x + tile.w and tile.y <= c[1] < tile.y + tile.h


def _touches(cells: Sequence[Cell], tile: TklDeckTile) -> bool:
    for i, c in enumerate(cells):
        if _inside(c, tile):
            return True
        if i:
            a = cells[i - 1]
            for k in range(1, 8):
                t = k / 8
                if _inside((a[0] + (c[0] - a[0]) * t, a[1] + (c[1] - a[1]) * t), tile):
                    return True
    return False


def tile_state(found: Picture, tile: TklDeckTile) -> str:
    """The panel's state in a key's piece, in short: it changes when a track, a signal or a
    train number in the piece changes, and then the key is drawn again."""
    lines = [(line.piece, line.state) for line in found.lines if _touches(line.cells, tile)]
    signals = [(s.name, s.aspect) for s in found.signals if _inside(s.symbol, tile)]
    numbers = [(n.number, n.colour) for n in found.numbers if _inside(n.at, tile)]
    text = json.dumps([lines, signals, numbers], ensure_ascii=False)
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def stamp(view: TklDeckView, found: Picture | None) -> TklDeckView:
    """Spårplan's keys with the panel's state in their piece, so that a key whose tracks change
    is drawn again (TklDeckTile.state)."""
    if found is None or not any(f.tile is not None for f in view.keys):
        return view
    keys = [
        f
        if f.tile is None
        else f.model_copy(
            update={"tile": f.tile.model_copy(update={"state": tile_state(found, f.tile)})}
        )
        for f in view.keys
    ]
    return view.model_copy(update={"keys": keys})


# --- the fonts and the text --------------------------------------------------------------------


@lru_cache(maxsize=512)
def font(mono: bool, weight: int, size: int) -> ImageFont.FreeTypeFont:
    """TrainMeet Mono or Inter at a weight and a size in pixels. The basic layout, so that a
    key is drawn the same on every computer."""
    found = ImageFont.truetype(
        str(MONO if mono else SANS), max(1, size), layout_engine=ImageFont.Layout.BASIC
    )
    found.set_variation_by_axes([weight])
    return found


def _runs(text: str) -> list[tuple[bool, str]]:
    """The text in runs of letters and of shapes: (shape, text)."""
    found: list[tuple[bool, str]] = []
    for ch in text:
        shape = ch in SHAPES
        if found and found[-1][0] == shape and not shape:
            found[-1] = (False, found[-1][1] + ch)
        else:
            found.append((shape, ch))
    return found


def _shape_width(f: ImageFont.FreeTypeFont) -> float:
    return f.size * 0.7


def width_of(text: str, f: ImageFont.FreeTypeFont) -> float:
    return sum(_shape_width(f) if shape else f.getlength(run) for shape, run in _runs(text))


def _shape(draw: ImageDraw.ImageDraw, ch: str, x: float, y: float, s: float, fill: str) -> None:
    """A character the fonts lack, as a simple shape in a box s wide, centred on y."""
    h = s * 0.62
    cx = x + s / 2
    match ch:
        case "▶":
            draw.polygon(
                [(cx - h * 0.45, y - h / 2), (cx + h * 0.55, y), (cx - h * 0.45, y + h / 2)],
                fill=fill,
            )
        case "◀":
            draw.polygon(
                [(cx + h * 0.45, y - h / 2), (cx - h * 0.55, y), (cx + h * 0.45, y + h / 2)],
                fill=fill,
            )
        case "▲":
            draw.polygon(
                [(cx - h / 2, y + h * 0.45), (cx, y - h * 0.55), (cx + h / 2, y + h * 0.45)],
                fill=fill,
            )
        case "▼":
            draw.polygon(
                [(cx - h / 2, y - h * 0.45), (cx, y + h * 0.55), (cx + h / 2, y - h * 0.45)],
                fill=fill,
            )
        case "★":
            draw.polygon(star(cx, y, h * 0.62), fill=fill)
        case "→":
            t = max(1.5, s * 0.12)
            draw.rectangle([x + s * 0.08, y - t / 2, x + s * 0.6, y + t / 2], fill=fill)
            draw.polygon(
                [(x + s * 0.48, y - h * 0.4), (x + s * 0.94, y), (x + s * 0.48, y + h * 0.4)],
                fill=fill,
            )
        case "✕":
            t = max(1, round(s * 0.1))
            draw.line(
                [(cx - h * 0.4, y - h * 0.4), (cx + h * 0.4, y + h * 0.4)], fill=fill, width=t
            )
            draw.line(
                [(cx - h * 0.4, y + h * 0.4), (cx + h * 0.4, y - h * 0.4)], fill=fill, width=t
            )


def star(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    """A five-pointed star (SD20), point up."""
    points = []
    for i in range(10):
        radius = r if i % 2 == 0 else r * 0.42
        angle = -math.pi / 2 + i * math.pi / 5
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def text_at(
    draw: ImageDraw.ImageDraw,
    text: str,
    f: ImageFont.FreeTypeFont,
    x: float,
    y: float,
    fill: str,
    anchor: Literal["l", "m", "r"] = "m",
) -> None:
    """The text with its shapes, its middle on y, starting, centred or ending at x."""
    total = width_of(text, f)
    at = x - total / 2 if anchor == "m" else (x - total if anchor == "r" else x)
    for shape, run in _runs(text):
        if shape:
            _shape(draw, run, at, y, _shape_width(f), fill)
            at += _shape_width(f)
        else:
            draw.text((at, y), run, font=f, fill=fill, anchor="lm")
            at += f.getlength(run)


def fitted(
    text: str, mono: bool, weight: int, size: int, room: float, least: int
) -> tuple[ImageFont.FreeTypeFont, str]:
    """The prototype's rule: smaller, a pixel at a time, until the text fits the room; at the
    least size what does not fit ends with an ellipsis, as the screen's text-overflow."""
    while size > least and width_of(text, font(mono, weight, size)) > room:
        size -= 1
    f = font(mono, weight, size)
    if width_of(text, f) <= room:
        return f, text
    cut = text
    while cut and width_of(cut + "…", f) > room:
        cut = cut[:-1]
    return f, (cut.rstrip() + "…") if cut else ""


# --- the colours --------------------------------------------------------------------------------


def rgb(colour: str) -> tuple[int, int, int]:
    c = colour.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def blend(fg: str, bg: str, alpha: float) -> str:
    """The text's colour at the prototype's opacity over the key's background."""
    a, b = rgb(fg), rgb(bg)
    mixed = (round(a[i] * alpha + b[i] * (1 - alpha)) for i in range(3))
    return "#" + "".join(f"{v:02x}" for v in mixed)


# --- one key ---------------------------------------------------------------------------------


def background(face: TklDeckFace, phase: int) -> str:
    """The colour the key has now: a blinking key shows `blink` every other half second."""
    return face.blink if face.blink and phase % 2 else face.bg


def key(
    face: TklDeckFace,
    width: int,
    height: int | None = None,
    found: Picture | None = None,
    phase: int = 0,
) -> Image.Image:
    """One key's picture, at the deck's own size (SD3, SD6)."""
    with _LOCK:
        return _key(face, width, height or width, found, phase)


def _key(face: TklDeckFace, w: int, h: int, found: Picture | None, phase: int) -> Image.Image:
    bg = background(face, phase)
    image = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(image)
    unit = min(w, h) / ON_SCREEN
    if face.tile is not None and found is not None:
        _tile(draw, face.tile, found, w, h)
    if face.band:
        draw.rectangle([0, 0, w - 1, max(4, round(h * 0.07)) - 1], fill=face.band)
    if face.line:
        thick = max(3, round(h * 0.04))
        top = round(h * 0.9)
        draw.rectangle([round(w * 0.2), top, round(w * 0.8) - 1, top + thick - 1], fill=face.line)
    if face.frame:
        _frame(draw, w, h, face.frame, face.dashed)
    fg = face.fg
    text = face.text
    if face.type == "fika":
        # Fika on the shunter's deck (RANG-04): a cup, a shape and never an emoji (SD6).
        _cup(draw, w / 2, h * 0.33, min(w, h) * 0.34, fg)
        if text:
            f, shown = fitted(text, True, 700, round(h * 0.18), w * 0.9, 8)
            text_at(draw, shown, f, w / 2, h * 0.63, fg)
        if face.under:
            f, shown = fitted(face.under, False, 600, round(h * 0.13), w * 0.92, 7)
            text_at(draw, shown, f, w / 2, h * 0.83, blend(fg, bg, 0.85))
        return image
    if text:
        n = len(text)
        ratio = 0.2 if n > 6 else 0.25 if n > 4 else 0.3 if n > 2 else 0.38
        f, shown = fitted(text, True, 700, round(h * ratio), w * 0.9, 8)
        y = h * 0.5 if face.top else (h * 0.42 if face.under or face.chip else h * 0.5)
        text_at(draw, shown, f, w / 2, y, fg)
    if face.top:
        f, shown = fitted(face.top, False, 600, round(h * 0.14), w * 0.92, 7)
        text_at(draw, shown, f, w / 2, h * 0.2, blend(fg, bg, 0.9))
    if face.dot:
        r = max(4.0, w * 0.055)
        cx, cy = w * 0.86, h * 0.17
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=face.dot)
    if face.ready:
        _ready_mark(draw, w, h)
    if face.under:
        f, shown = fitted(face.under, False, 600, round(h * 0.15), w * 0.92, 7)
        text_at(draw, shown, f, w / 2, h * (0.8 if face.top else 0.76), blend(fg, bg, 0.85))
    star_r = 12 * unit * 0.45
    if face.small:
        # Beside the star when there is one, so that neither hides the other.
        right = w * 0.94 - (2.4 * star_r if face.star else 0)
        f, shown = fitted(face.small, False, 600, round(7 * unit), right - w * 0.3, 6)
        text_at(draw, shown, f, right, h * 0.04 + f.size * 0.6, blend(fg, bg, 0.8), "r")
    if face.star:
        draw.polygon(star(w * 0.94 - star_r, h * 0.03 + star_r, star_r), fill="#facc15")
    if face.chip:
        _chip(draw, face.chip, face.chip_colour, w / 2, h * (0.5 if face.tile else 0.6), unit)
    if face.bar:
        _bar(draw, w, h, face.bar, face.bar_dashed, unit)
    return image


def _frame(draw: ImageDraw.ImageDraw, w: int, h: int, colour: str, dashed: bool) -> None:
    """The prototype's frame, a stroke of w/18 at the edge; dashed as the screen's outline."""
    lw = max(3, round(w / 18))
    if not dashed:
        for i in range(lw):
            draw.rectangle([i, i, w - 1 - i, h - 1 - i], outline=colour)
        return
    dash, gap = lw * 3, lw * 2
    for start in range(0, w, dash + gap):
        end = min(w - 1, start + dash - 1)
        draw.rectangle([start, 0, end, lw - 1], fill=colour)
        draw.rectangle([start, h - lw, end, h - 1], fill=colour)
    for start in range(0, h, dash + gap):
        end = min(h - 1, start + dash - 1)
        draw.rectangle([0, start, lw - 1, end], fill=colour)
        draw.rectangle([w - lw, start, w - 1, end], fill=colour)


READY: Final = "#22c55e"


def _cup(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, colour: str) -> None:
    """A cup on a saucer with steam, s wide, its middle at (cx, cy)."""
    t = max(1, round(s * 0.07))
    top, bottom = cy - s * 0.18, cy + s * 0.3
    left, right = cx - s * 0.36, cx + s * 0.22
    draw.polygon(
        [(left, top), (right, top), (right - s * 0.06, bottom), (left + s * 0.06, bottom)],
        fill=colour,
    )
    draw.arc(
        [right - s * 0.12, top + s * 0.04, right + s * 0.2, top + s * 0.3],
        start=-90,
        end=90,
        fill=colour,
        width=t,
    )
    draw.line([(cx - s * 0.5, bottom + t), (cx + s * 0.38, bottom + t)], fill=colour, width=t)
    for dx in (-0.2, -0.04):
        x = cx + s * dx
        draw.line([(x, top - s * 0.08), (x + s * 0.05, top - s * 0.3)], fill=colour, width=t)


def _ready_mark(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """Klart att skicka (SD62): a green disc with a white tick, top left on the train key."""
    r = max(4.0, w * 0.075)
    cx, cy = w * 0.14, h * 0.17
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=READY)
    tick = [(cx - r * 0.5, cy), (cx - r * 0.1, cy + r * 0.45), (cx + r * 0.55, cy - r * 0.45)]
    draw.line(tick, fill="#ffffff", width=max(1, round(r * 0.35)))


CHIP_TEXT: Final = {"red": "#b91c1c", "green": "#15803d", "": "#111827"}


def _chip(
    draw: ImageDraw.ImageDraw, text: str, colour: str, cx: float, cy: float, unit: float
) -> None:
    """The train number on a place (SD19): red where a train stands, green where one comes."""
    f = font(True, 700, max(7, round(9 * unit)))
    tw = width_of(text, f)
    px, py = 4 * unit, 1 * unit + f.size * 0.1
    half_h = f.size * 0.62 + py
    box = [cx - tw / 2 - px, cy - half_h, cx + tw / 2 + px, cy + half_h]
    draw.rounded_rectangle(box, radius=6 * unit, fill="#f3f4f6")
    text_at(draw, text, f, cx, cy, CHIP_TEXT.get(colour, "#111827"))


def _bar(draw: ImageDraw.ImageDraw, w: int, h: int, colour: str, dashed: bool, unit: float) -> None:
    """The place's bar (SD66): free, occupied or in a set route; dashed for a goal."""
    thick = max(3.0, 4 * unit)
    bottom = h - h * 0.07
    left, right = w * 0.1, w * 0.9
    if not dashed:
        draw.rounded_rectangle([left, bottom - thick, right, bottom], radius=2 * unit, fill=colour)
        return
    x = left
    while x < right:
        draw.rectangle([x, bottom - thick, min(right, x + 6 * unit), bottom], fill=colour)
        x += 9 * unit


def _tile(draw: ImageDraw.ImageDraw, tile: TklDeckTile, found: Picture, w: int, h: int) -> None:
    """A piece of the panel on a key (SD70, SD71), stretched to the key as the screen's SVG:
    85 with thin tracks in their state, or Relä with a lamp per track piece (SD72)."""
    cw, ch = found.cell
    if tile.w <= 0 or tile.h <= 0:
        return
    sx, sy = w / (tile.w * cw), h / (tile.h * ch)
    ox, oy = tile.x * cw, tile.y * ch
    unit = min(w, h) / ON_SCREEN

    def at(c: Cell) -> tuple[float, float]:
        return ((c[0] * cw - ox) * sx, (c[1] * ch - oy) * sy)

    relay = tile.drawn == DeckPlanDrawn.RELAY
    lines = [line for line in found.lines if _touches(line.cells, tile)]
    for line in lines:
        colour = RELAY_TRACK if relay else PLAN_COLOURS.get(line.state, PLAN_COLOURS["free"])
        draw.line(
            [at(c) for c in line.cells],
            fill=colour,
            width=max(1, round((2 if relay else 4) * unit)),
            joint="curve",
        )
    if relay:
        for line in lines:
            a, b = line.cells[0], line.cells[-1]
            mx, my = at(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
            rx, ry = cw * 0.12 * sx, ch * 0.12 * sy
            lit = PLAN_COLOURS.get(line.state, RELAY_DARK) if line.state != "free" else RELAY_DARK
            draw.ellipse([mx - rx, my - ry, mx + rx, my + ry], fill=lit, outline="#9ca3af")
    goals = set(tile.goals)
    for s in found.signals:
        if not _inside(s.symbol, tile):
            continue
        tx, ty = s.toward
        n = math.hypot(tx, ty) or 1.0
        ux, uy = tx / n * cw * 0.3, ty / n * ch * 0.3
        px, py = -uy * 0.6, ux * 0.6
        cx, cy = s.symbol[0] * cw, s.symbol[1] * ch
        corners = [(cx + ux, cy + uy), (cx - ux + px, cy - uy + py), (cx - ux - px, cy - uy - py)]
        fill = (
            "#2563eb"
            if tile.start == s.name
            else "#22c55e"
            if s.name in goals or s.aspect == "proceed"
            else "#e5e7eb"
            if s.aspect == "shunt"
            else "#000000"
        )
        points = [((x - ox) * sx, (y - oy) * sy) for x, y in corners]
        draw.polygon(points, fill=fill, outline="#ffffff", width=max(1, round(1.5 * unit)))
    numbers = [n for n in found.numbers if _inside(n.at, tile)]
    if numbers:
        first = numbers[0]
        _chip(draw, first.number, first.colour, w / 2, h * 0.5, unit)
    if tile.names:
        f, shown = fitted(" ".join(tile.names), True, 600, round(8 * unit), w * 0.9, 6)
        text_at(draw, shown, f, w * 0.06, h * 0.95 - f.size * 0.6, "#f3f4f6", "l")


# --- the touch strip and the info line (SD18, SD33, SD34, SD82, SD83) ------------------------


def strip(
    parts: Sequence[TklDeckStrip],
    dials: int,
    width: int,
    height: int,
    *,
    said: str = "",
    contact: bool = True,
) -> Image.Image:
    """The touch strip of + and + XL: a segment per dial with what it stands on (SD33, SD83);
    the interlocking's no across it for three seconds (SD18); Ingen kontakt without an answer
    (SD21). Locked, it is dark (SD30)."""
    with _LOCK:
        image = Image.new("RGB", (width, height), STRIP_BG)
        draw = ImageDraw.Draw(image)
        if not contact:
            f, shown = fitted("Ingen kontakt", False, 600, round(height * 0.3), width * 0.9, 8)
            text_at(draw, shown, f, width / 2, height / 2, "#8b95a1")
            return image
        if said:
            f, shown = fitted(f"Nej: {said}", False, 600, round(height * 0.3), width * 0.94, 8)
            text_at(draw, shown, f, width / 2, height / 2, NO_FG)
            return image
        count = max(1, dials)
        each = width / count
        for i in range(count):
            left = i * each
            if i:
                draw.line([(left, 0), (left, height)], fill=STRIP_LINE, width=1)
            if i >= len(parts):
                continue
            part = parts[i]
            cx = left + each / 2
            f, shown = fitted(part.label, False, 500, round(height * 0.2), each * 0.9, 7)
            text_at(draw, shown, f, cx, height * 0.2, STRIP_LABEL)
            f, shown = fitted(part.value, True, 700, round(height * 0.34), each * 0.9, 8)
            text_at(draw, shown, f, cx, height * 0.52, STRIP_VALUE)
            if part.under:
                f, shown = fitted(part.under, False, 500, round(height * 0.18), each * 0.9, 7)
                text_at(draw, shown, f, cx, height * 0.82, STRIP_LABEL)
        return image


def info(text: str, width: int, height: int, *, contact: bool = True) -> Image.Image:
    """Neo's info line (SD34, SD82): the clock and the page, or the choice, and the latest no
    for three seconds in red (SD18)."""
    with _LOCK:
        image = Image.new("RGB", (width, height), STRIP_BG)
        draw = ImageDraw.Draw(image)
        shown = text if contact else "Ingen kontakt"
        colour = INFO_FG if contact else "#8b95a1"
        clock, _, rest = shown.partition("  ")
        pad = height * 0.18
        if contact and rest and len(clock) == 5 and clock[2] == ":":
            f = font(True, 700, round(height * 0.38))
            text_at(draw, clock, f, pad, height / 2, colour, "l")
            left = pad + width_of(clock, f) + height * 0.25
            said = rest.startswith("Nej:")
            g, cut = fitted(rest, False, 600, round(height * 0.34), width - left - pad, 8)
            text_at(draw, cut, g, left, height / 2, NO_FG if said else colour, "l")
        else:
            f, cut = fitted(shown, False, 600, round(height * 0.36), width - 2 * pad, 8)
            text_at(draw, cut, f, pad, height / 2, colour, "l")
        return image


# --- the pictures as files ----------------------------------------------------------------------


def png(image: Image.Image) -> bytes:
    with io.BytesIO() as out:
        image.save(out, "PNG", optimize=False, compress_level=6)
        return out.getvalue()


def etag(*parts: object) -> str:
    """A picture's ETag: the renderer's version and everything the picture is drawn from."""
    text = json.dumps([VERSION, *parts], ensure_ascii=False, sort_keys=True, default=str)
    return '"' + hashlib.sha1(text.encode()).hexdigest()[:24] + '"'


def key_etag(face: TklDeckFace, width: int, height: int, phase: int) -> str:
    """The same face at the same size is the same picture; the phase only matters when the
    face blinks."""
    return etag("key", face.model_dump(mode="json"), width, height, phase % 2 if face.blink else 0)


def blinks(faces: Iterable[TklDeckFace]) -> bool:
    return any(f.blink for f in faces)


def phase_at(now: float) -> int:
    return int(now / BLINK_SECONDS) % 2


__all__ = [
    "SIZES",
    "Picture",
    "blinks",
    "etag",
    "info",
    "key",
    "key_etag",
    "phase_at",
    "picture",
    "png",
    "stamp",
    "strip",
    "tile_state",
]
