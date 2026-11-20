"""Profile Stationsritning, the intake: a drawing's file becomes pages of strokes and words
(bildkedjan, Stationsritning R1 and R2; #89 del c4).

A drawing comes as a PDF, an SVG, or a picture (JPEG, PNG, WebP: a photo of paper or a scan).

- R1, vector: a PDF page or an SVG with drawn lines is read by code, with pdfminer-six for the
  PDF and the standard library's XML for the SVG: every stroked line and closed figure with its
  colour, its width and its fill, and the text layer's lines with their boxes. Nothing is sent
  anywhere and nothing costs. Text drawn as figures (glyph outlines) cannot be read by code; its
  places are kept so that the read can say so.
- R2, raster: a picture, or a PDF page that is a picture, goes through the photo's intake first
  (bildkedjan step 2: its metadata gone, its checksum), and is then straightened as a document
  with the sketch profile's straightening (the paper found and made a rectangle). The light is
  made even, the ink is sorted by colour, and the lines are found with OpenCV's line segment
  detector (LSD), whose two edges of a drawn line are joined into its centre line. Figures (a
  signal's lamps, triangles, circles) are the small closed things that are not lines. The text is
  not read by code: it is transcribed by AI (cad/drawings.py, through ID's meter), with the
  question and the check of its answer here.

Every page's coordinates have y down, as the station model's: a PDF's points from the page's top
left, or the straightened picture's pixels. The pages are read again for each read: only the file
is kept, never what pdfminer made of it.
"""

from __future__ import annotations

import colorsys
import io
import json
import math
import re
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Final, Literal

import cv2
import numpy as np
from numpy.typing import NDArray

from cad.bildkedjan import intake, skiss
from contracts.cad import MAX_DRAWING_PAGES, ReadBy

Point = tuple[float, float]
RGB = tuple[float, float, float]
Box = tuple[float, float, float, float]
"""x0, y0, x1, y1 with y down."""

MAX_BYTES: Final = 30 * 1024 * 1024
MAX_STROKES: Final = 60_000
"""More drawn things on one page than this is no station drawing."""
MAX_WORDS: Final = 5_000
SATURATED: Final = 35
"""Ink with more colour than this (0–255) is coloured: a thin line in a photo is pale."""
AI_SIDE: Final = 2000
"""The picture the AI transcribes, its long side, px."""
TRANSCRIPT_VERSION: Final = "2026-11-20.1"
"""The AI transcription's question; a new text is a new version, and new transcripts."""
MAX_ANSWER: Final = 60_000
MAX_TEXTS: Final = 600


class Refused(Exception):
    """The drawing cannot be taken in; the message says why, in Swedish."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class Unreadable(Exception):
    """The AI's transcription does not follow the form. Never holds the answer."""


@dataclass
class Stroke:
    """One drawn thing: an open line, or a closed figure, with its colour, width and fill."""

    points: list[Point]
    colour: RGB | None
    width: float
    closed: bool = False
    fill: RGB | None = None
    curved: bool = False

    @property
    def box(self) -> Box:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def length(self) -> float:
        return sum(math.dist(a, b) for a, b in zip(self.points, self.points[1:], strict=False))


@dataclass
class Word:
    """A line of text with its box: from the text layer, or transcribed."""

    text: str
    box: Box
    read_by: ReadBy

    @property
    def centre(self) -> Point:
        return ((self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2)

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]


@dataclass
class Shape:
    """A figure found in a raster page: its kind, box, centre and colour."""

    kind: Literal["circle", "triangle", "rect", "figure", "blob"]
    box: Box
    centre: Point
    colour: RGB
    filled: bool
    lamps: int = 0
    head: Point | None = None
    foot: Point | None = None
    pointing: float | None = None
    """A triangle's tip direction, radians, y down."""


@dataclass
class Page:
    """One page of a drawing as code sees it."""

    number: int
    kind: Literal["vector", "raster"]
    width: float
    height: float
    strokes: list[Stroke] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)
    outlined: list[Box] = field(default_factory=list)
    """Where text is drawn as figures that code cannot read."""
    shapes: list[Shape] = field(default_factory=list)
    """A raster page's figures; a vector page's are its closed strokes."""
    pixels: NDArray[Any] | None = None
    """A raster page straightened and its light made even, BGR."""
    sha256: str | None = None
    """A raster page's clean pixels' checksum: the transcript's key."""

    @property
    def text(self) -> bool:
        return bool(self.words)


@dataclass(frozen=True)
class Taken:
    """A drawing taken in: its format, its pages as they are listed before a read, and its
    checksum."""

    format: Literal["pdf", "svg", "image"]
    sha256: str
    pages: list[Page]
    file: bytes
    """What is kept: the PDF or SVG as sent, or a picture's clean pixels as PNG."""


def sniff(data: bytes) -> Literal["pdf", "svg", "image"]:
    head = data[:1024].lstrip()
    if data[:5] == b"%PDF-":
        return "pdf"
    lowered = head.lower()
    if lowered.startswith(b"<?xml") or lowered.startswith(b"<svg") or b"<svg" in lowered:
        return "svg"
    return "image"


def take(data: bytes) -> Taken:
    """The drawing taken in, with its pages, or Refused with why."""
    import hashlib

    if len(data) > MAX_BYTES:
        raise Refused("Ritningen är för stor. Högst 30 MB.", 413)
    kind = sniff(data)
    if kind == "pdf":
        pages = pdf_pages(data)
        return Taken("pdf", hashlib.sha256(data).hexdigest(), pages, data)
    if kind == "svg":
        page = svg_page(data)
        return Taken("svg", hashlib.sha256(data).hexdigest(), [page], data)
    try:
        taken = intake.take(data)
    except intake.Refused as refused:
        raise Refused(refused.message, refused.status) from refused
    page = Page(1, "raster", float(taken.width), float(taken.height), pixels=taken.pixels)
    page.sha256 = taken.clean_sha256
    # The clean pixels, never the file as sent: no metadata is kept (bildkedjan step 2).
    return Taken("image", taken.clean_sha256, [page], intake.jpeg(taken.pixels))


# --- PDF ------------------------------------------------------------------------------------


def _rgb(value: Any) -> RGB | None:
    """A PDF colour as RGB 0–1: gray, RGB or CMYK; None for a pattern or nothing."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        v = min(1.0, max(0.0, float(value)))
        return (v, v, v)
    if isinstance(value, list | tuple):
        found = [float(x) for x in value if isinstance(x, int | float) and not isinstance(x, bool)]
        found = [min(1.0, max(0.0, x)) for x in found]
        if len(found) == 1:
            return (found[0], found[0], found[0])
        if len(found) == 3:
            return (found[0], found[1], found[2])
        if len(found) == 4:
            c, m, y, k = found
            return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def _pdf_objects(data: bytes, maxpages: int) -> list[Any]:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return list(extract_pages(io.BytesIO(data), laparams=LAParams(), maxpages=maxpages))
    except Exception as error:  # pdfminer raises many kinds for a broken or locked file
        name = type(error).__name__
        if "Password" in name or "Encryption" in name:
            raise Refused("PDF:en är låst. Spara den utan lösenord och ladda upp igen.") from error
        raise Refused(
            "PDF:en kunde inte läsas. Spara den igen, eller ladda upp en bild."
        ) from error


def pdf_pages(data: bytes, only: int | None = None) -> list[Page]:
    """The PDF's pages: each vector or raster. With only, that page alone is read fully (its
    picture decoded and straightened); otherwise the pages are listed."""
    from pdfminer.layout import (
        LTCurve,
        LTFigure,
        LTImage,
        LTTextBox,
        LTTextLine,
    )

    found = _pdf_objects(data, MAX_DRAWING_PAGES if only is None else only)
    if not found:
        raise Refused("PDF:en har inga sidor.")
    pages: list[Page] = []
    for number, layout in enumerate(found, start=1):
        if only is not None and number != only:
            continue
        x0, y0, x1, y1 = (float(v) for v in layout.bbox)
        height = y1 - y0

        def flip(point: tuple[float, float], x0: float = x0, y1: float = y1) -> Point:
            return (round(float(point[0]) - x0, 3), round(y1 - float(point[1]), 3))

        page = Page(number, "vector", x1 - x0, height)
        images: list[Any] = []
        count = 0

        def walk(container: Any, page: Page = page, images: list[Any] = images) -> None:
            nonlocal count
            for item in container:
                if isinstance(item, LTFigure):
                    walk(item)
                elif isinstance(item, LTImage):
                    images.append(item)
                elif isinstance(item, LTTextBox):
                    for line in item:
                        if isinstance(line, LTTextLine):
                            text = " ".join(line.get_text().split())
                            if text:
                                bx0, by0, bx1, by1 = (float(v) for v in line.bbox)
                                a, b = flip((bx0, by1)), flip((bx1, by0))
                                page.words.append(Word(text[:80], (*a, *b), ReadBy.TEXT_LAYER))
                elif isinstance(item, LTCurve):
                    count += 1
                    if count > MAX_STROKES:
                        raise Refused("Sidan har för många streck för att vara en ritning.")
                    points = [flip(p) for p in item.pts]
                    if len(points) < 2:
                        continue
                    ops = [str(op[0]) for op in (item.original_path or [])]
                    closed = (
                        bool(ops and ops[-1] == "h")
                        or (len(points) > 2 and math.dist(points[0], points[-1]) < 1e-3)
                        or bool(item.fill and len(points) > 2)
                    )
                    page.strokes.append(
                        Stroke(
                            points=points,
                            colour=_rgb(item.stroking_color) if item.stroke else None,
                            width=float(item.linewidth or 0.0),
                            closed=closed,
                            fill=_rgb(item.non_stroking_color) if item.fill else None,
                            curved=any(op in ("c", "v", "y") for op in ops),
                        )
                    )

        walk(layout)
        if len(page.words) > MAX_WORDS:
            raise Refused("Sidan har för mycket text för att vara en ritning.")
        lines = [s for s in page.strokes if s.colour is not None and not s.closed]
        area = page.width * page.height
        picture = max(
            images,
            key=lambda i: (i.bbox[2] - i.bbox[0]) * (i.bbox[3] - i.bbox[1]),
            default=None,
        )
        covered = (
            (picture.bbox[2] - picture.bbox[0]) * (picture.bbox[3] - picture.bbox[1]) / area
            if picture is not None and area > 0
            else 0.0
        )
        if picture is not None and covered > 0.4 and len(lines) < 8 and len(page.words) < 5:
            page.kind = "raster"
            page.strokes, page.words = [], []
            if only is not None:
                pixels = _decode_image(picture)
                page.pixels = pixels
                page.width, page.height = float(pixels.shape[1]), float(pixels.shape[0])
            else:
                width, height = picture.srcsize
                page.width, page.height = float(width or 1), float(height or 1)
        pages.append(page)
    return pages


def _decode_image(image: Any) -> NDArray[Any]:
    """A PDF page's picture as BGR pixels: JPEG through the photo's intake (its metadata gone),
    or 8-bit gray or RGB pixels as they are."""
    stream = image.stream
    filters = [
        str(f[0]).strip("/'") if isinstance(f, tuple) else str(f) for f in stream.get_filters()
    ]
    data = stream.get_data()
    if not data:
        raise Refused("Sidans bild kunde inte läsas.")
    if any("DCT" in f for f in filters):
        try:
            return intake.take(bytes(data)).pixels
        except intake.Refused as refused:
            raise Refused(refused.message, refused.status) from refused
    width, height = image.srcsize
    bits = image.bits or 8
    space = str(stream.attrs.get("ColorSpace", ""))
    if not width or not height or bits != 8:
        raise Refused("Sidans bild har ett format som inte går att läsa. Ladda upp en bild.")
    raw = np.frombuffer(bytes(data), np.uint8)
    if "RGB" in space and raw.size >= width * height * 3:
        rgb = raw[: width * height * 3].reshape(height, width, 3)
        found: NDArray[Any] = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        return found
    if "Gray" in space and raw.size >= width * height:
        gray = raw[: width * height].reshape(height, width)
        made: NDArray[Any] = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        return made
    raise Refused("Sidans bild har ett format som inte går att läsa. Ladda upp en bild.")


# --- SVG ------------------------------------------------------------------------------------

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_COMMANDS = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])([^MmLlHhVvCcSsQqTtAaZz]*)")
_NAMED: Final = {
    "black": (0.0, 0.0, 0.0),
    "white": (1.0, 1.0, 1.0),
    "red": (1.0, 0.0, 0.0),
    "green": (0.0, 0.5, 0.0),
    "lime": (0.0, 1.0, 0.0),
    "blue": (0.0, 0.0, 1.0),
    "yellow": (1.0, 1.0, 0.0),
    "orange": (1.0, 0.65, 0.0),
    "purple": (0.5, 0.0, 0.5),
    "grey": (0.5, 0.5, 0.5),
    "gray": (0.5, 0.5, 0.5),
}
Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Final[Matrix] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _svg_colour(value: str | None) -> RGB | None:
    if value is None:
        return None
    text = value.strip().lower()
    if not text or text == "none" or text.startswith("url("):
        return None
    if text in _NAMED:
        return _NAMED[text]
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        if len(digits) == 6 and all(c in "0123456789abcdef" for c in digits):
            return tuple(int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
        return None
    found = re.fullmatch(r"rgb\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)", text)
    if found:
        return tuple(min(1.0, float(found[i]) / 255) for i in (1, 2, 3))  # type: ignore[return-value]
    return None


def _multiply(a: Matrix, b: Matrix) -> Matrix:
    """a then b, as SVG composes a group's transform with its child's."""
    a0, a1, a2, a3, a4, a5 = a
    b0, b1, b2, b3, b4, b5 = b
    return (
        a0 * b0 + a2 * b1,
        a1 * b0 + a3 * b1,
        a0 * b2 + a2 * b3,
        a1 * b2 + a3 * b3,
        a0 * b4 + a2 * b5 + a4,
        a1 * b4 + a3 * b5 + a5,
    )


def _transform(text: str | None) -> Matrix:
    matrix = IDENTITY
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", text or ""):
        values = [float(v) for v in _NUMBER.findall(args)]
        step: Matrix = IDENTITY
        if name == "matrix" and len(values) == 6:
            step = (values[0], values[1], values[2], values[3], values[4], values[5])
        elif name == "translate" and values:
            step = (1, 0, 0, 1, values[0], values[1] if len(values) > 1 else 0.0)
        elif name == "scale" and values:
            step = (values[0], 0, 0, values[1] if len(values) > 1 else values[0], 0, 0)
        elif name == "rotate" and values:
            angle = math.radians(values[0])
            cos, sin = math.cos(angle), math.sin(angle)
            step = (cos, sin, -sin, cos, 0, 0)
            if len(values) == 3:
                cx, cy = values[1], values[2]
                step = _multiply(_multiply((1, 0, 0, 1, cx, cy), step), (1, 0, 0, 1, -cx, -cy))
        matrix = _multiply(matrix, step)
    return matrix


def _apply(matrix: Matrix, point: Point) -> Point:
    a, b, c, d, e, f = matrix
    x, y = point
    return (round(a * x + c * y + e, 3), round(b * x + d * y + f, 3))


def _style(element: ET.Element, inherited: dict[str, str]) -> dict[str, str]:
    found = dict(inherited)
    for key in ("stroke", "fill", "stroke-width", "font-size"):
        if element.get(key) is not None:
            found[key] = str(element.get(key))
    for part in (element.get("style") or "").split(";"):
        key, _, value = part.partition(":")
        if key.strip() in ("stroke", "fill", "stroke-width", "font-size"):
            found[key.strip()] = value.strip()
    return found


def _path_points(d: str) -> tuple[list[list[Point]], list[bool], bool]:
    """A path's subpaths as points (curves by their ends and control points, sampled), whether
    each is closed, and whether it has curves."""
    subpaths: list[list[Point]] = []
    closed: list[bool] = []
    curved = False
    x = y = 0.0
    start = (0.0, 0.0)
    current: list[Point] = []
    for command, args in _COMMANDS.findall(d):
        values = [float(v) for v in _NUMBER.findall(args)]
        relative = command.islower()
        kind = command.upper()
        if kind == "Z":
            if current:
                subpaths.append(current)
                closed.append(True)
            current = []
            x, y = start
            continue
        size = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}[kind]
        for i in range(0, len(values) - size + 1, size):
            chunk = values[i : i + size]
            if kind == "M" and i == 0:
                if current:
                    subpaths.append(current)
                    closed.append(False)
                x, y = (x + chunk[0], y + chunk[1]) if relative else (chunk[0], chunk[1])
                start = (x, y)
                current = [(x, y)]
                continue
            if kind in ("M", "L", "T"):
                x, y = (x + chunk[0], y + chunk[1]) if relative else (chunk[0], chunk[1])
            elif kind == "H":
                x = x + chunk[0] if relative else chunk[0]
            elif kind == "V":
                y = y + chunk[0] if relative else chunk[0]
            elif kind in ("C", "S", "Q"):
                curved = True
                points = [
                    (x + chunk[j], y + chunk[j + 1]) if relative else (chunk[j], chunk[j + 1])
                    for j in range(0, size, 2)
                ]
                current.extend(points[:-1])
                x, y = points[-1]
            elif kind == "A":
                curved = True
                x, y = (x + chunk[5], y + chunk[6]) if relative else (chunk[5], chunk[6])
            current.append((x, y))
    if current:
        subpaths.append(current)
        closed.append(False)
    return subpaths, closed, curved


def svg_page(data: bytes) -> Page:
    """An SVG drawing as one vector page: its lines, figures and texts, in the viewBox's
    units. Entities and external references are refused before the XML is parsed."""
    text = data.decode("utf-8", errors="replace")
    if "<!ENTITY" in text or "<!DOCTYPE" in text.upper():
        raise Refused("SVG-filen har en DOCTYPE eller entiteter, som inte tas emot.")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise Refused("SVG-filen kunde inte läsas.") from error
    ns = re.compile(r"^\{[^}]*\}")

    def tag(element: ET.Element) -> str:
        return ns.sub("", element.tag)

    if tag(root) != "svg":
        raise Refused("Filen är ingen SVG-ritning.")
    view = [float(v) for v in _NUMBER.findall(root.get("viewBox") or "")]
    if len(view) == 4 and view[2] > 0 and view[3] > 0:
        base: Matrix = (1, 0, 0, 1, -view[0], -view[1])
        width, height = view[2], view[3]
    else:
        base = IDENTITY
        width = float((_NUMBER.findall(root.get("width") or "") or ["1000"])[0])
        height = float((_NUMBER.findall(root.get("height") or "") or ["1000"])[0])
    page = Page(1, "vector", width, height)
    count = 0

    def add(
        points: list[Point], closed: bool, curved: bool, style: dict[str, str], m: Matrix
    ) -> None:
        nonlocal count
        count += 1
        if count > MAX_STROKES:
            raise Refused("Ritningen har för många streck.")
        stroke = _svg_colour(style.get("stroke"))
        fill = _svg_colour(style.get("fill", "black"))
        scale = math.sqrt(abs(m[0] * m[3] - m[1] * m[2])) or 1.0
        widths = _NUMBER.findall(style.get("stroke-width", "1"))
        page.strokes.append(
            Stroke(
                points=[_apply(m, p) for p in points],
                colour=stroke,
                width=(float(widths[0]) if widths else 1.0) * scale,
                closed=closed,
                fill=fill if closed else None,
                curved=curved,
            )
        )

    def walk(element: ET.Element, inherited: dict[str, str], matrix: Matrix) -> None:
        name = tag(element)
        if name in ("defs", "clipPath", "mask", "symbol", "style", "script", "metadata"):
            return
        style = _style(element, inherited)
        m = _multiply(matrix, _transform(element.get("transform")))

        def number(key: str) -> float:
            found = _NUMBER.findall(element.get(key) or "0")
            return float(found[0]) if found else 0.0

        if name == "line":
            add(
                [(number("x1"), number("y1")), (number("x2"), number("y2"))], False, False, style, m
            )
        elif name in ("polyline", "polygon"):
            values = [float(v) for v in _NUMBER.findall(element.get("points") or "")]
            points = list(zip(values[0::2], values[1::2], strict=False))
            if len(points) >= 2:
                add(points, name == "polygon", False, style, m)
        elif name == "rect":
            x, y, w, h = number("x"), number("y"), number("width"), number("height")
            if w > 0 and h > 0:
                add([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True, False, style, m)
        elif name in ("circle", "ellipse"):
            cx, cy = number("cx"), number("cy")
            rx = number("r") if name == "circle" else number("rx")
            ry = number("r") if name == "circle" else number("ry")
            if rx > 0 and ry > 0:
                points = [
                    (cx + rx * math.cos(t), cy + ry * math.sin(t))
                    for t in np.linspace(0, 2 * math.pi, 17)[:-1]
                ]
                add(points, True, True, style, m)
        elif name == "path":
            subpaths, closed, curved = _path_points(element.get("d") or "")
            for points, shut in zip(subpaths, closed, strict=True):
                if len(points) >= 2:
                    add(points, shut, curved, style, m)
        elif name == "text":
            words = " ".join("".join(element.itertext()).split())
            if words:
                size = float((_NUMBER.findall(style.get("font-size", "10")) or ["10"])[0])
                x, y = number("x"), number("y")
                anchor = element.get("text-anchor") or ""
                w = 0.55 * size * len(words)
                left = x - w / 2 if anchor == "middle" else x - w if anchor == "end" else x
                a = _apply(m, (left, y - 0.8 * size))
                b = _apply(m, (left + w, y + 0.2 * size))
                box = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
                page.words.append(Word(words[:80], box, ReadBy.TEXT_LAYER))
            return
        for child in element:
            walk(child, style, m)

    walk(root, {}, base)
    return page


# --- Raster (R2) ----------------------------------------------------------------------------


def even_light(pixels: NDArray[Any]) -> NDArray[Any]:
    """The paper made evenly white: each channel divided by its background, the lines closed
    away and blurred (uneven light, a shadow across the sheet)."""
    side = max(pixels.shape[:2])
    size = max(15, int(side * 0.02) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
    channels = []
    for channel in cv2.split(pixels):
        background = cv2.morphologyEx(channel, cv2.MORPH_CLOSE, kernel)
        background = cv2.GaussianBlur(background, (0, 0), size / 2)
        flat = cv2.divide(channel, np.maximum(background, 1), scale=255)
        channels.append(flat)
    found: NDArray[Any] = cv2.merge(channels)
    return found


FAMILIES: Final = (
    ("röda", 0.0),
    ("orange", 30.0),
    ("gula", 58.0),
    ("gröna", 120.0),
    ("turkosa", 180.0),
    ("blå", 220.0),
    ("lila", 285.0),
    ("rosa", 330.0),
)


def family(colour: RGB | None) -> str:
    """A colour's family, by name in Swedish plural (as the questions say it): a hue for a
    coloured line, svarta or grå for one without colour."""
    if colour is None:
        return "osynliga"
    h, s, v = colorsys.rgb_to_hsv(*colour)
    if s < 0.22 or v < 0.12:
        if v < 0.35:
            return "svarta"
        if v > 0.93:
            return "vita"
        return "grå"
    hue = h * 360.0
    best = min(FAMILIES, key=lambda f: min(abs(hue - f[1]), 360 - abs(hue - f[1])))
    return best[0]


def _families_mask(pixels: NDArray[Any]) -> dict[str, NDArray[Any]]:
    """The ink by colour family, as masks: coloured ink by hue, then the black and grey ink that
    is not the soft edge of a coloured line."""
    hsv = cv2.cvtColor(pixels, cv2.COLOR_BGR2HSV)
    h, s, v = (hsv[..., i].astype(np.int32) for i in range(3))
    coloured = (s > SATURATED) & (v > 40)
    ink = (v < 205) | coloured
    masks: dict[str, NDArray[Any]] = {}
    hue = h * 2  # OpenCV's hue is 0–180
    names = [name for name, _ in FAMILIES]
    centres = np.array([c for _, c in FAMILIES], np.int32)
    distance = np.abs(hue[..., None] - centres[None, None, :])
    distance = np.minimum(distance, 360 - distance)
    nearest = np.argmin(distance, axis=-1)
    any_colour = np.zeros(ink.shape, np.uint8)
    for i, name in enumerate(names):
        mask = np.where(coloured & (nearest == i), 255, 0).astype(np.uint8)
        if int(np.count_nonzero(mask)) >= 30:
            masks[name] = mask
            any_colour |= mask
    halo = cv2.dilate(any_colour, np.ones((5, 5), np.uint8)) > 0
    plain = ink & ~coloured & ~halo
    black = np.where(plain & (v < 100), 255, 0).astype(np.uint8)
    grey = np.where(plain & (v >= 100), 255, 0).astype(np.uint8)
    for name, mask in (("svarta", black), ("grå", grey)):
        if int(np.count_nonzero(mask)) >= 30:
            masks[name] = mask
    return masks


def _mean_colour(pixels: NDArray[Any], mask: NDArray[Any]) -> RGB:
    found = cv2.mean(pixels, mask=mask)
    return (found[2] / 255, found[1] / 255, found[0] / 255)


def merge_segments(
    lines: NDArray[Any], tolerance: float, gap: float
) -> list[tuple[Point, Point, float]]:
    """LSD's segments joined: the two edges of a drawn line, and the pieces of a line broken by
    a crossing, become one centre line with its width. Segments nearly parallel (4°), within
    tolerance of each other's line, and overlapping or apart by at most gap, are one."""
    segs = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        a, b = np.array([x1, y1], np.float64), np.array([x2, y2], np.float64)
        if np.linalg.norm(b - a) >= 2.0:
            segs.append((a, b))
    segs.sort(key=lambda s: -float(np.linalg.norm(s[1] - s[0])))
    used = [False] * len(segs)
    merged: list[tuple[Point, Point, float]] = []
    cos_limit = math.cos(math.radians(4.0))
    for i, (a, b) in enumerate(segs):
        if used[i]:
            continue
        used[i] = True
        d = (b - a) / np.linalg.norm(b - a)
        n = np.array([-d[1], d[0]])
        lo, hi = 0.0, float(np.dot(b - a, d))
        offsets = [0.0]
        weights = [hi]
        grew = True
        while grew:
            grew = False
            for j in range(i + 1, len(segs)):
                if used[j]:
                    continue
                c, e = segs[j]
                dj = e - c
                length = float(np.linalg.norm(dj))
                if abs(float(np.dot(dj / length, d))) < cos_limit:
                    continue
                oc, oe = float(np.dot(c - a, n)), float(np.dot(e - a, n))
                if abs(oc) > tolerance or abs(oe) > tolerance:
                    continue
                pc, pe = sorted((float(np.dot(c - a, d)), float(np.dot(e - a, d))))
                if pc > hi + gap or pe < lo - gap:
                    continue
                used[j] = True
                lo, hi = min(lo, pc), max(hi, pe)
                offsets.append((oc + oe) / 2)
                weights.append(length)
                grew = True
        offset = float(np.average(offsets, weights=weights))
        spread = max(offsets) - min(offsets)
        start = a + d * lo + n * offset
        end = a + d * hi + n * offset
        merged.append(
            (
                (round(float(start[0]), 2), round(float(start[1]), 2)),
                (round(float(end[0]), 2), round(float(end[1]), 2)),
                max(1.0, spread),
            )
        )
    return merged


def _shapes(pixels: NDArray[Any], masks: dict[str, NDArray[Any]], unit: float) -> list[Shape]:
    """The small closed things: circles, triangles and rectangles of one colour, and signal
    figures, a frame with lamps inside, a post and a foot (R3)."""
    found: list[Shape] = []
    small = 3.2 * unit
    tiny = (0.12 * unit) ** 2
    for name, mask in masks.items():
        colour = _mean_colour(pixels, mask)
        contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if hierarchy is None:
            continue
        for index, contour in enumerate(contours):
            if hierarchy[0][index][3] != -1:
                continue  # a hole
            x, y, w, h = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)
            if max(w, h) > small or area < tiny or max(w, h) < 0.25 * unit:
                continue
            (_, _), (rw, rh), _ = cv2.minAreaRect(contour)
            if max(rw, rh) > 3.0 * max(min(rw, rh), 1.0):
                continue  # a stroke, not a figure
            solid = area / max(cv2.contourArea(cv2.convexHull(contour)), 1.0)
            if name in ("svarta", "grå") and solid < 0.8:
                continue  # a letter or a digit in dark ink, not a solid figure
            hole = 0.0
            child = hierarchy[0][index][2]
            while child != -1:
                hole += cv2.contourArea(contours[child])
                child = hierarchy[0][child][0]
            filled = hole < 0.3 * max(area, 1.0)
            perimeter = cv2.arcLength(contour, True)
            round_ = 4 * math.pi * area / max(perimeter * perimeter, 1e-6)
            approx = cv2.approxPolyDP(contour, 0.08 * perimeter, True)
            centre = (x + w / 2, y + h / 2)
            box = (float(x), float(y), float(x + w), float(y + h))
            kind: Literal["circle", "triangle", "rect", "figure", "blob"]
            pointing = None
            if round_ > 0.72 and 0.75 < w / max(h, 1) < 1.33:
                kind = "circle"
            elif len(approx) == 3:
                kind = "triangle"
                corners = approx.reshape(-1, 2).astype(np.float64)
                middle = corners.mean(axis=0)
                # The tip is the corner opposite the shortest side.
                sides = [
                    np.linalg.norm(corners[(k + 1) % 3] - corners[(k + 2) % 3]) for k in range(3)
                ]
                tip = corners[int(np.argmin(sides))]
                pointing = math.atan2(float(tip[1] - middle[1]), float(tip[0] - middle[0]))
            elif len(approx) == 4:
                kind = "rect"
            else:
                kind = "blob"
            found.append(Shape(kind, box, centre, colour, filled, pointing=pointing))
    # Signal figures: a long, low frame of grey or black ink with two or more lamps inside.
    circles = [s for s in found if s.kind == "circle"]
    figures: list[Shape] = []
    for name in ("grå", "svarta"):
        ink = masks.get(name)
        if ink is None:
            continue
        count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
        for label in range(1, count):
            x, y, w, h, area = stats[label]
            if max(w, h) > 5 * unit or max(w, h) < 0.8 * unit or min(w, h) > 1.6 * unit:
                continue
            inside = [c for c in circles if x <= c.centre[0] <= x + w and y <= c.centre[1] <= y + h]
            distinct: list[Shape] = []
            for c in inside:
                if all(math.dist(c.centre, d.centre) > 0.2 * unit for d in distinct):
                    distinct.append(c)
            if len(distinct) < 2:
                continue
            head = (
                sum(c.centre[0] for c in distinct) / len(distinct),
                sum(c.centre[1] for c in distinct) / len(distinct),
            )
            ys, xs = np.nonzero(labels[y : y + h, x : x + w] == label)
            points = np.stack([xs + x, ys + y], axis=1).astype(np.float64)
            far = points[int(np.argmax(np.linalg.norm(points - np.array(head), axis=1)))]
            figures.append(
                Shape(
                    "figure",
                    (float(x), float(y), float(x + w), float(y + h)),
                    (x + w / 2, y + h / 2),
                    _mean_colour(pixels, np.where(labels == label, 255, 0).astype(np.uint8)),
                    False,
                    lamps=len(distinct),
                    head=head,
                    foot=(float(far[0]), float(far[1])),
                )
            )
    near = [_grown(f.box, 0.5 * unit) for f in figures]
    kept = [x for x in found if not any(_inside_box(x.centre, box) for box in near)]
    return kept + figures


def _text_rows(mask: NDArray[Any], unit: float) -> list[Box]:
    """Where dark ink is text: small marks side by side on one baseline, two or more, as letters
    are. Code cannot read them; without AI their places are kept."""
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    marks = [
        (float(x), float(y), float(x + w), float(y + h))
        for x, y, w, h, area in stats[1:count]
        if 0.15 * unit <= h <= 1.3 * unit and w <= 1.5 * unit and area >= 4
    ]
    marks.sort()
    rows: list[list[Box]] = []
    for box in marks:
        for row in rows:
            last = row[-1]
            same_line = abs((box[1] + box[3]) / 2 - (last[1] + last[3]) / 2) < 0.5 * unit
            if same_line and 0 <= box[0] - last[2] < 0.8 * unit:
                row.append(box)
                break
        else:
            rows.append([box])
    return [
        (
            min(b[0] for b in row),
            min(b[1] for b in row),
            max(b[2] for b in row),
            max(b[3] for b in row),
        )
        for row in rows
        if len(row) >= 2
    ]


def _near_line(centre: Point, lines: list[tuple[Point, Point, float]], reach: float) -> bool:
    for a, b, _ in lines:
        d = (b[0] - a[0], b[1] - a[1])
        length2 = d[0] * d[0] + d[1] * d[1]
        if length2 == 0:
            continue
        t = max(0.0, min(1.0, ((centre[0] - a[0]) * d[0] + (centre[1] - a[1]) * d[1]) / length2))
        q = (a[0] + t * d[0], a[1] + t * d[1])
        if math.dist(centre, q) <= reach:
            return True
    return False


def raster_page(pixels: NDArray[Any], number: int = 1) -> Page:
    """A raster page straightened as a document, its light made even, and its lines (LSD,
    joined to centre lines) and figures found. No text: that is the AI's (R2); where dark marks
    stand in rows as letters do, they are kept as text code cannot read."""
    import hashlib

    sheet = skiss.prepare(pixels)
    flat = even_light(sheet.pixels)
    height, width = flat.shape[:2]
    unit = 0.012 * max(width, height)
    masks = _families_mask(flat)
    page = Page(number, "raster", float(width), float(height), pixels=flat)
    page.sha256 = hashlib.sha256(flat.tobytes()).hexdigest()
    lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    lines: dict[str, list[tuple[Point, Point, float]]] = {}
    for name, mask in masks.items():
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        found = lsd.detect(cv2.GaussianBlur(closed, (3, 3), 0))[0]
        if found is None:
            continue
        lines[name] = [
            line
            for line in merge_segments(found, tolerance=max(3.0, 0.35 * unit), gap=0.35 * unit)
            if math.dist(line[0], line[1]) >= 0.5 * unit
        ]
    if "svarta" in masks:
        page.outlined = _text_rows(masks["svarta"], unit)
    long = {
        name: [x for x in found if math.dist(x[0], x[1]) > 2 * unit]
        for name, found in lines.items()
    }
    shapes = []
    for shape in _shapes(flat, masks, unit):
        name = family(shape.colour)
        if any(_inside_box(shape.centre, _grown(box, 0.1 * unit)) for box in page.outlined):
            continue  # a letter
        if shape.kind != "figure" and _near_line(shape.centre, long.get(name, []), 0.3 * unit):
            continue  # a bit of a line, where it meets another
        shapes.append(shape)
    page.shapes = shapes
    figure_boxes = [x.box for x in shapes if x.kind in ("figure", "circle", "triangle", "rect")]
    for name, found_lines in lines.items():
        colour = _mean_colour(flat, masks[name])
        for a, b, wide in found_lines:
            middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if math.dist(a, b) < 3 * unit and any(
                _inside_box(middle, _grown(box, 2.0)) for box in figure_boxes + page.outlined
            ):
                continue  # a side of a figure, or a letter
            page.strokes.append(Stroke([a, b], colour, wide))
        if len(page.strokes) > MAX_STROKES:
            raise Refused("Sidan har för många streck för att vara en ritning.")
    return page


def _inside_box(p: Point, box: Box) -> bool:
    return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]


def _grown(box: Box, by: float) -> Box:
    return (box[0] - by, box[1] - by, box[2] + by, box[3] + by)


# --- The AI's transcription of a raster page's text (R2) -----------------------------------


def ai_picture(page: Page) -> tuple[bytes, float]:
    """The picture the AI transcribes, as JPEG, and its pixels per page pixel."""
    assert page.pixels is not None
    height, width = page.pixels.shape[:2]
    factor = min(1.0, AI_SIDE / max(height, width))
    small = cv2.resize(
        page.pixels, (round(width * factor), round(height * factor)), interpolation=cv2.INTER_AREA
    )
    return intake.jpeg(small, 90), factor


def transcript_prompt() -> str:
    return (
        "Bilden är en ritning av en järnvägsstation: en signalplan, en ställverkspanel eller en "
        "spårplan. Skriv av all text som står i ritningen, ord för ord som den står, till exempel "
        "växelnummer, spårnamn, signalnamn med typ och adress som »Hdvsi 66 (204)«. Gissa aldrig "
        "en text som inte går att läsa. Ange var varje text står som en ruta i bildens "
        "koordinater från 0 till 1000, med x åt höger och y nedåt från bildens övre vänstra "
        "hörn. Svara bara med JSON i den här formen: "
        '{"texter": [{"text": "113", "x": 120, "y": 340, "b": 18, "h": 9}]}, där x och y är '
        "rutans övre vänstra hörn och b och h dess bredd och höjd."
    )


def understand(answer: str, page: Page) -> list[Word]:
    """The AI's transcription read failing closed: anything that is not the form makes the
    whole answer unreadable, and nothing of it is used."""
    if len(answer) > MAX_ANSWER:
        raise Unreadable()
    text = answer.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{") :]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise Unreadable()
    try:
        data = json.loads(text[start : end + 1], parse_constant=lambda _: None)
    except ValueError as error:
        raise Unreadable() from error
    items = data.get("texter") if isinstance(data, dict) else None
    if not isinstance(items, list) or len(items) > MAX_TEXTS:
        raise Unreadable()
    words: list[Word] = []
    sx, sy = page.width / 1000, page.height / 1000
    for item in items:
        if not isinstance(item, dict):
            raise Unreadable()
        said = item.get("text")
        values = [item.get(k) for k in ("x", "y", "b", "h")]
        if not isinstance(said, str) or not all(
            isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)
            for v in values
        ):
            raise Unreadable()
        x, y, b, h = (float(v) for v in values)  # type: ignore[arg-type]
        if not (0 <= x <= 1000 and 0 <= y <= 1000 and 0 < b <= 1000 and 0 < h <= 1000):
            raise Unreadable()
        cleaned = " ".join(said.split())
        if not cleaned or len(cleaned) > 80 or any(ord(c) < 32 for c in cleaned):
            raise Unreadable()
        words.append(
            Word(
                cleaned,
                (
                    round(x * sx, 2),
                    round(y * sy, 2),
                    round((x + b) * sx, 2),
                    round((y + h) * sy, 2),
                ),
                ReadBy.AI,
            )
        )
    return words
