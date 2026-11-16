"""Banbilden (4c1, IMPORT-33, I4): the page Topologi in the planning program's PDF, read with
code. Underlagsnivå 2.

The planning program draws each place as a small round mark with its signature beside it
("Mkd", "Lek", "Gdö"), and the track between places as straight lines: one line for single
track, two side by side for double track. What the picture gives:

- the places on the map, by signature, with where they stand (the map in Bana, PLAN-26);
- which places the track joins, so the places between two stations are known;
- double track where two lines run side by side.

Ported from the old Cloud (cloud/overview_import.py), which read only the signatures; the lines
are new. The picture has no names, only signatures.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Final

from integrationer.pdf_page import Page, PdfError, Segment, pages

HEADINGS: Final = {"topologi", "topology", "topologie"}
# A signature: short, with a capital first ("Mkd", "R", "Ørm", "Gdö").
LABEL: Final = re.compile(r"[A-ZÆØÅÄÖÜ][a-zæøåäöü]{0,3}|[A-ZÆØÅÄÖÜ]{1,4}")
MIN_PLACES: Final = 3
NEAR: Final = 3.0  # a line ends at a mark when it ends this close to its middle
BESIDE: Final = 6.0  # a signature stands this close to its mark
SIDE: Final = 0.5  # two lines this far either side of the middle are double track
LEVEL: Final = 2


class PictureError(ValueError):
    """The file has no track picture that can be read. The message is for the planner."""


@dataclass
class Picture:
    page: int
    places: dict[str, tuple[float, float]] = field(default_factory=dict)
    links: dict[frozenset[str], bool] = field(default_factory=dict)  # the pair: double track

    def path(self, a: str, b: str, through: set[str]) -> list[str] | None:
        """The shortest way from a to b on the picture, passing only the places in through."""
        if a not in self.places or b not in self.places:
            return None
        nearby: dict[str, set[str]] = defaultdict(set)
        for pair in self.links:
            x, y = tuple(pair)
            nearby[x].add(y)
            nearby[y].add(x)
        came: dict[str, str | None] = {a: None}
        queue = deque([a])
        while queue:
            here = queue.popleft()
            for there in sorted(nearby[here]):
                if there in came:
                    continue
                came[there] = here
                if there == b:
                    way: list[str] = [b]
                    while (back := came[way[-1]]) is not None:
                        way.append(back)
                    return way[::-1]
                if there in through:
                    queue.append(there)
        return None

    def branches(self, code: str) -> int:
        return sum(1 for pair in self.links if code in pair)


def is_picture(data: bytes) -> bool:
    try:
        return any(_heading(page) is not None for page in pages(data, limit=12))
    except PdfError:
        return False


def read(data: bytes) -> Picture:
    """The first page Topologi in the file. Raises PictureError when there is none."""
    try:
        found = pages(data, limit=12)
    except PdfError as error:
        raise PictureError(str(error)) from error
    for page in found:
        heading = _heading(page)
        if heading is None:
            continue
        picture = _picture(page, heading)
        if len(picture.places) >= MIN_PLACES:
            return picture
    raise PictureError("PDF:en har ingen sida Topologi med driftplatser och linjer.")


def _heading(page: Page) -> float | None:
    """The bottom of the heading Topologi, where the map begins."""
    for word in page.words:
        if word.text.casefold() in HEADINGS:
            return word.bottom
    return None


def _picture(page: Page, top: float) -> Picture:
    marks = [m for m in page.marks if m[1] > top]
    nodes = _nodes(marks, page.segments)
    used = {node for pair in nodes.values() for node in pair}
    names = _names(page, top, [m for m in marks if m in used])
    picture = Picture(page=page.number)
    for mark, code in names.items():
        picture.places[code] = mark
    sides: dict[frozenset[str], set[int]] = defaultdict(set)
    for segment, (a, b) in nodes.items():
        if a in names and b in names and names[a] != names[b]:
            pair = frozenset((names[a], names[b]))
            offset = _offset(segment, a, b)
            sides[pair].add(0 if abs(offset) < SIDE else 1 if offset > 0 else -1)
    for pair, seen in sides.items():
        picture.links[pair] = {-1, 1} <= seen
    return picture


def _nodes(
    marks: list[tuple[float, float]], segments: list[Segment]
) -> dict[Segment, tuple[tuple[float, float], tuple[float, float]]]:
    """The two marks each line of track joins. A line that does not end at two marks is not
    track between places (a legend, a frame)."""
    out: dict[Segment, tuple[tuple[float, float], tuple[float, float]]] = {}
    if not marks:
        return out
    for segment in segments:
        ends = []
        for point in (segment.a, segment.b):
            mark = min(marks, key=lambda m: math.dist(m, point))
            if math.dist(mark, point) <= NEAR:
                ends.append(mark)
        if len(ends) == 2 and ends[0] != ends[1]:
            out[segment] = (ends[0], ends[1])
    return out


def _names(
    page: Page, top: float, marks: list[tuple[float, float]]
) -> dict[tuple[float, float], str]:
    """Each mark's signature: the nearest one, above, below or beside it. Nearest first, so
    that two places close together each get their own."""
    labels = [w for w in page.words if w.top > top and LABEL.fullmatch(w.text)]
    pairs = sorted(
        (word.distance(*mark), mark, word.text)
        for mark in marks
        for word in labels
        if word.distance(*mark) <= BESIDE
    )
    names: dict[tuple[float, float], str] = {}
    taken: set[str] = set()
    for _, mark, text in pairs:
        if mark in names or text in taken:
            continue
        names[mark] = text
        taken.add(text)
    return names


def _offset(segment: Segment, a: tuple[float, float], b: tuple[float, float]) -> float:
    """How far the line runs beside the straight way between the two marks, to the left (plus) or
    right (minus). Double track is two lines, one either side."""
    length = math.dist(a, b) or 1.0
    nx, ny = -(b[1] - a[1]) / length, (b[0] - a[0]) / length
    mx = (segment.a[0] + segment.b[0]) / 2 - (a[0] + b[0]) / 2
    my = (segment.a[1] + segment.b[1]) / 2 - (a[1] + b[1]) / 2
    return mx * nx + my * ny
