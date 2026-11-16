"""A PDF's text layer and lines, read with code (pdfminer.six), never with AI (4c1, IMPORT-15).

What the import needs from a page: the words with their boxes, the straight lines with their
widths, and the small round marks the planning program draws for a place. Nothing in a file is
ever run; only the first pages are read, and a file that is not a PDF is refused.

Coordinates are in points from the page's top left corner, as on the screen: y grows
downwards.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Final

from pdfminer.high_level import extract_pages
from pdfminer.layout import (
    LAParams,
    LTChar,
    LTComponent,
    LTCurve,
    LTFigure,
    LTLine,
    LTPage,
    LTTextContainer,
    LTTextLine,
)

MAX_BYTES: Final = 20 * 1024 * 1024
MAX_PAGES: Final = 40
MARK: Final = (2.0, 8.0)  # a place's mark: a small round shape, this wide and high
TRACK: Final = 2.0  # thinner lines are frames and rules, not track


class PdfError(ValueError):
    """The file is not a PDF that can be read. The message is for the planner."""


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    size: float

    @property
    def middle(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.top + self.bottom) / 2)

    def distance(self, x: float, y: float) -> float:
        """From a point to the word's box; 0 inside it."""
        dx = max(self.x0 - x, 0.0, x - self.x1)
        dy = max(self.top - y, 0.0, y - self.bottom)
        return float((dx * dx + dy * dy) ** 0.5)


@dataclass(frozen=True)
class Segment:
    a: tuple[float, float]
    b: tuple[float, float]
    width: float


@dataclass
class Page:
    number: int
    width: float
    height: float
    words: list[Word] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    marks: list[tuple[float, float]] = field(default_factory=list)


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def pages(data: bytes, *, limit: int = MAX_PAGES) -> list[Page]:
    """The first pages of the PDF, read. Raises PdfError when it cannot be read."""
    if len(data) > MAX_BYTES:
        raise PdfError("Filen är större än 20 MB.")
    if not is_pdf(data):
        raise PdfError("Filen är inte en PDF.")
    try:
        layouts = list(extract_pages(io.BytesIO(data), maxpages=limit, laparams=LAParams()))
    except Exception as error:  # pdfminer raises many kinds for a broken file
        raise PdfError("PDF:en gick inte att läsa.") from error
    return [_page(number, layout) for number, layout in enumerate(layouts, 1)]


def _page(number: int, layout: LTPage) -> Page:
    page = Page(number=number, width=float(layout.width), height=float(layout.height))
    marks: set[tuple[float, float]] = set()

    def flip(x: float, y: float) -> tuple[float, float]:
        return (round(float(x), 1), round(page.height - float(y), 1))

    def walk(items: LTComponent) -> None:
        for item in items:  # type: ignore[attr-defined]
            if isinstance(item, LTFigure):
                walk(item)
            elif isinstance(item, LTTextContainer):
                for line in item:
                    if isinstance(line, LTTextLine):
                        page.words.extend(_words(line, page.height))
            elif isinstance(item, LTLine):
                if item.linewidth >= TRACK and len(item.pts) == 2:
                    a, b = (flip(*point) for point in item.pts)
                    page.segments.append(Segment(a, b, float(item.linewidth)))
            elif isinstance(item, LTCurve):
                w, h = float(item.width), float(item.height)
                if MARK[0] <= w <= MARK[1] and MARK[0] <= h <= MARK[1] and abs(w - h) < 1:
                    marks.add(flip((item.x0 + item.x1) / 2, (item.y0 + item.y1) / 2))

    walk(layout)
    page.marks = sorted(marks)
    return page


def _words(line: LTTextLine, height: float) -> list[Word]:
    """A line of text as its words: pdfminer gives a space between words as a separate
    character, or none at all."""
    out: list[Word] = []
    current: list[LTChar] = []
    for char in [*line, None]:
        if isinstance(char, LTChar) and not char.get_text().isspace():
            current.append(char)
            continue
        if current:
            out.append(
                Word(
                    text="".join(c.get_text() for c in current),
                    x0=round(float(current[0].x0), 1),
                    top=round(height - max(float(c.y1) for c in current), 1),
                    x1=round(float(current[-1].x1), 1),
                    bottom=round(height - min(float(c.y0) for c in current), 1),
                    size=round(float(current[0].size), 1),
                )
            )
        current = []
    return out
