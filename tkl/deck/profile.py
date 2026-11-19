"""The default profile for a deck's grid, computed from the station model (SD32, SD39, SD53).

Every grid is read the same way, so a model that comes later works too (SD53). The frame says
where Läge and the fixed keys sit (SD27, SD75, SD77, SD78):

- up to six keys, without dials or touch points (Mini, Module 6): ▶ is the last key, and
  holding it opens the page Läge;
- up to fourteen keys (Neo, +): Läge is the last key;
- 32 keys or more in three rows or more (XL, Module 32, + XL): the fixed keys in the right
  column, Larm och klocka at the top and Läge at the bottom, so that the rows to the left are
  free for the mode (SD75, SD84);
- the others (15, Module 15, Studio): the fixed row at the bottom, Ankommit, Lös ut, Larm och
  klocka, ▶ and Läge far right (SD27, SD77).

The modes (SD63, SD76) and their pages:

- Tågen: the page Nu, with the train keys, the line keys and the alarm (SD22), and Dagens vägar
  (SD23). Both need Hubben, so the logic hides the mode without it (SD11, SD63).
- Platser: the places (SD66): all of them in columns west to east on the big decks, a row per
  part and half the station per page on the 15 (SD80), a part and then its places on the small
  ones (SD79), and the nearest trains in the keys left over on + XL and Studio (SD84, SD85).
  Then Favoriter (SD24), the geographic pages of signals and Alla (SD25): they are chosen the
  same way, a start and then a goal. A station with one line has track keys (SD12).
- Spårplan, from 15 keys or with dials (SD76): Hela stationen, the plan cut in a piece per key
  (SD70), and the cut-out, a square of the plan per key with the pan keys (SD71, SD81).

A profile is data (SD5): keys from the fixed catalogue (SD4) that name a slot, a place, a signal
or a square. No code here names a station (RS13).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Final

from contracts.tkl import (
    DeckAction,
    DeckDial,
    DeckKeyType,
    DeckMode,
    DeckModelId,
    DeckPageKind,
    DeckPan,
    DeckStyle,
    Panel,
    TklDeckGrid,
    TklDeckKey,
    TklDeckPage,
    TklDeckProfile,
)
from tkl.deck.places import Geography, geography
from tkl.stallverk import Plant

K = DeckKeyType
SMALL: Final = 6
"""Up to this many keys and no dials, ▶ is the last key (Mini, Module 6)."""
MEDIUM: Final = 15
"""Below this many keys, Läge is the last key (Neo, +)."""
LARGE: Final = 32
"""From this many keys in three rows or more, the fixed keys stand in the right column."""
WIDE: Final = 9
"""From this many columns the keys left over in Platser show the nearest trains (SD84, SD85)."""
DIALS: Final[dict[DeckMode, list[DeckDial]]] = {
    DeckMode.TRAINS: [DeckDial.TRAIN, DeckDial.TRACK, DeckDial.PAGE, DeckDial.ROUTE],
    DeckMode.PLACES: [DeckDial.START, DeckDial.GOAL, DeckDial.PART, DeckDial.ROUTE],
    DeckMode.TRACK_PLAN: [DeckDial.SIDEWAYS, DeckDial.UPDOWN, DeckDial.SIGNAL, DeckDial.ROUTE],
}
FIXED_COLUMN: Final = ("alarm", "arrived", "release", "mode")
"""The right column from the top, Läge at the bottom (SD75, SD77)."""
FIXED_ROW: Final = ("arrived", "release", "alarm", "page", "mode")
"""The fixed row from the left, Läge far right (SD27, SD77)."""
PANS: Final = (DeckPan.WHOLE, DeckPan.WEST, DeckPan.EAST, DeckPan.UP, DeckPan.DOWN)


@dataclass
class Frame:
    """Where Läge and the fixed keys sit on a grid, and the rows left for the modes."""

    style: DeckStyle
    grid: TklDeckGrid
    fixed: dict[str, int] = field(default_factory=dict)
    rows: list[list[int]] = field(default_factory=list)
    """The cells left for the mode, row by row."""

    @property
    def size(self) -> int:
        return self.grid.columns * self.grid.rows

    @property
    def area(self) -> list[int]:
        return [i for row in self.rows for i in row]

    @property
    def body(self) -> tuple[int, int]:
        """The full rectangle at the top left of the cells left for the mode."""
        if not self.rows:
            return 0, 0
        width = min(len(r) for r in self.rows)
        return width, len(self.rows)

    def key(self, role: str) -> TklDeckKey | None:
        return {
            "next": TklDeckKey(type=K.NEXT),
            "mode": TklDeckKey(type=K.MODE),
            "alarm": TklDeckKey(type=K.ALARM),
            "release": TklDeckKey(type=K.ACTION, action=DeckAction.RELEASE),
            "arrived": TklDeckKey(type=K.ACTION, action=DeckAction.ARRIVED),
            "page": TklDeckKey(type=K.PAGE),
        }.get(role)


def frame(grid: TklDeckGrid) -> Frame:
    """The frame of a grid (SD27, SD75, SD77, SD78)."""
    columns, rows = grid.columns, grid.rows
    size = columns * rows
    every = [[r * columns + c for c in range(columns)] for r in range(rows)]
    if size == 0:
        return Frame(DeckStyle.NONE, grid)
    if size <= SMALL and not grid.dials and not grid.touch:
        last = size - 1
        return Frame(DeckStyle.NEXT, grid, {"next": last}, _without(every, {last}))
    if size < MEDIUM:
        last = size - 1
        return Frame(DeckStyle.LAST, grid, {"mode": last}, _without(every, {last}))
    if size >= LARGE and rows >= 3:
        right = columns - 1
        fixed = {
            role: (rows - len(FIXED_COLUMN) + i) * columns + right
            for i, role in enumerate(FIXED_COLUMN)
            if rows - len(FIXED_COLUMN) + i >= 0
        }
        column = {r * columns + right for r in range(rows)}
        return Frame(DeckStyle.COLUMN, grid, fixed, _without(every, column))
    bottom = rows - 1
    roles = FIXED_ROW[-columns:] if columns < len(FIXED_ROW) else FIXED_ROW
    first = columns - len(roles)
    fixed = {role: bottom * columns + first + i for i, role in enumerate(roles)}
    return Frame(DeckStyle.ROW, grid, fixed, _without(every, set(fixed.values())))


def _without(rows: list[list[int]], taken: set[int]) -> list[list[int]]:
    return [kept for row in rows if (kept := [i for i in row if i not in taken])]


@dataclass
class Builder:
    """Pages for one grid: each page is every key, the fixed ones included."""

    frame: Frame
    geo: Geography
    pages: list[TklDeckPage] = field(default_factory=list)

    def page(
        self,
        name: str,
        mode: DeckMode,
        kind: DeckPageKind,
        keys: dict[int, TklDeckKey],
        *,
        listed: bool = True,
        cancel: int | None = None,
        fixed: dict[int, TklDeckKey] | None = None,
        part: int | None = None,
    ) -> int:
        cells: list[TklDeckKey | None] = [None] * self.frame.size
        for role, index in self.frame.fixed.items():
            cells[index] = self.frame.key(role)
        for index, key in (fixed or {}).items():
            cells[index] = key
        for index, key in keys.items():
            cells[index] = key
        self.pages.append(
            TklDeckPage(name=name, mode=mode, kind=kind, keys=cells, listed=listed, cancel=cancel)
        )
        return len(self.pages) - 1

    def cancel_at(self, used: set[int]) -> int | None:
        """Where Avbryt stands while a start is chosen: on ▶ on Mini, else in the first free
        key from the end of the mode's keys, else on Ankommit (SD27)."""
        f = self.frame
        if f.style == DeckStyle.NEXT:
            return f.fixed.get("next")
        free = [i for i in reversed(f.area) if i not in used]
        if f.style == DeckStyle.ROW and "arrived" in f.fixed:
            return f.fixed["arrived"]
        if free:
            return free[0]
        return f.fixed.get("arrived") or f.fixed.get("release")


_MADE: dict[tuple[str, str, DeckModelId | None], TklDeckProfile] = {}
_GEOGRAPHY: dict[str, Geography] = {}
_LOCK = Lock()
KEPT: Final = 64


def build(
    plant: Plant, panel: Panel | None, grid: TklDeckGrid, model: DeckModelId | None = None
) -> TklDeckProfile:
    """The default profile for a grid: the same model and grid always give the same profile,
    so it is made once (the panel follows from the model)."""
    key = (plant.fingerprint, grid.model_dump_json(), model)
    with _LOCK:
        known = _MADE.get(key)
    if known is not None:
        return known
    made = _built(plant, panel, grid, model)
    with _LOCK:
        if len(_MADE) >= KEPT:
            _MADE.clear()
        _MADE[key] = made
    return made


def geography_of(plant: Plant, panel: Panel | None) -> Geography:
    with _LOCK:
        known = _GEOGRAPHY.get(plant.fingerprint)
    if known is not None:
        return known
    made = geography(plant, panel)
    with _LOCK:
        if len(_GEOGRAPHY) >= KEPT:
            _GEOGRAPHY.clear()
        _GEOGRAPHY[plant.fingerprint] = made
    return made


def _built(
    plant: Plant, panel: Panel | None, grid: TklDeckGrid, model: DeckModelId | None
) -> TklDeckProfile:
    geo = geography_of(plant, panel)
    f = frame(grid)
    if f.style == DeckStyle.NONE:
        # Pedal: no default, nothing until the owner chooses a function per pedal (SD55).
        return TklDeckProfile(
            model=model,
            grid=grid,
            style=f.style,
            places=geo.places,
            parts=geo.parts,
            points=geo.points,
            pedals=[None] * grid.pedals,
        )
    b = Builder(f, geo)
    modes = [DeckMode.TRAINS, DeckMode.PLACES]
    _trains(b)
    _places(b)
    _favourites(b)
    _signals(b)
    if f.size >= MEDIUM or grid.dials >= 2:
        modes.append(DeckMode.TRACK_PLAN)
        _track_plan(b, panel)
    dials = {mode: DIALS[mode][: grid.dials] for mode in modes} if grid.dials else {}
    return TklDeckProfile(
        model=model,
        grid=grid,
        style=f.style,
        fixed=sorted(f.fixed.values()),
        modes=modes,
        pages=b.pages,
        dials=dials,
        places=geo.places,
        parts=geo.parts,
        points=geo.points,
        one_line=sum(1 for p in geo.places if p.kind == "exit") == 1,
        tile=geo.tile,
        tile_origin=geo.tile_origin,
        plan=geo.plan,
    )


# --- Tågen: Nu and Dagens vägar (SD22, SD23) ---------------------------------------------------


def _slots(f: Frame, paged: bool) -> tuple[list[int], dict[int, TklDeckKey]]:
    """The mode's keys, and ▶ in the last of them on the big decks when the mode has more
    pages than one: the fixed column has no ▶ of its own."""
    area = f.area
    if paged and f.style == DeckStyle.COLUMN and area:
        return area[:-1], {area[-1]: TklDeckKey(type=K.PAGE)}
    return area, {}


def _trains(b: Builder) -> None:
    f = b.frame
    area, extra = _slots(f, True)
    keys: dict[int, TklDeckKey] = dict(extra)
    if f.style == DeckStyle.NEXT:
        trains, tail = area[:-2], [("alarm", area[-2]), ("release", area[-1])]
    elif f.style == DeckStyle.LAST:
        rest = ["arrived", "release"] if f.grid.info else ["alarm", "arrived", "release"]
        trains, tail = area[: -len(rest)], list(zip(rest, area[-len(rest) :], strict=True))
    else:
        trains, tail = area, []
    for role, index in tail:
        found = f.key(role)
        if found is not None:
            keys[index] = found
    lines: list[int] = []
    if f.style in (DeckStyle.ROW, DeckStyle.COLUMN) and len(f.rows) >= 2:
        last = set(f.rows[-1])
        lines = [i for i in trains if i in last]
        trains = [i for i in trains if i not in last]
    for slot, index in enumerate(trains, start=1):
        keys[index] = TklDeckKey(type=K.TRAIN, slot=slot)
    for slot, index in enumerate(lines, start=1):
        keys[index] = TklDeckKey(type=K.LINE, slot=slot)
    b.page("Nu", DeckMode.TRAINS, DeckPageKind.NOW, keys)
    area, extra = _slots(f, True)
    daily = dict(extra)
    for slot, index in enumerate(area, start=1):
        daily[index] = TklDeckKey(type=K.DAILY, slot=slot)
    b.page("Dagens vägar", DeckMode.TRAINS, DeckPageKind.DAILY, daily)


def _favourites(b: Builder) -> None:
    area, extra = _slots(b.frame, True)
    keys = dict(extra)
    for slot, index in enumerate(area, start=1):
        keys[index] = TklDeckKey(type=K.FAVOURITE, slot=slot)
    b.page("Favoriter", DeckMode.PLACES, DeckPageKind.FAVOURITES, keys)


# --- Platser (SD66, SD79, SD80, SD84, SD85) ----------------------------------------------------


def _spread(base: str, count: int) -> list[str]:
    """Page names west to east."""
    if count == 1:
        return [base]
    if count == 2:
        return ["Väster", "Öster"] if base == "Platser" else [f"{base} väster", f"{base} öster"]
    if count == 3:
        sides = ["väster", "mitten", "öster"]
        return [s.capitalize() if base == "Platser" else f"{base} {s}" for s in sides]
    return [f"{base} {n}" for n in range(1, count + 1)]


def _place_key(b: Builder, place: str) -> TklDeckKey:
    one_line = sum(1 for p in b.geo.places if p.kind == "exit") == 1
    found = next(p for p in b.geo.places if p.id == place)
    kind = K.TRACK if one_line and found.kind == "track" else K.PLACE
    return TklDeckKey(type=kind, place=place)


def _places(b: Builder) -> None:
    f = b.frame
    if not b.geo.places:
        return
    if f.style in (DeckStyle.NEXT, DeckStyle.LAST):
        _two_steps(b)
    elif f.style == DeckStyle.COLUMN:
        _columns(b)
    else:
        _part_rows(b)


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), max(1, size))]


def _two_steps(b: Builder) -> None:
    """A part, then its place (SD79): the parts on the first page, each part on a page of its
    own that is not listed among Sidor. A part with more places than a page holds goes on on
    its next page, which ▶ or Tillbaka reaches."""
    f = b.frame
    area = f.area
    room = len(area) - (1 if f.style == DeckStyle.NEXT else 2)
    per_page = len(area) if f.style == DeckStyle.NEXT else len(area) - 1
    groups = _chunks([str(i) for i in range(len(b.geo.parts))], per_page)
    first_page = len(b.pages) + len(groups)
    opens: list[int] = []
    at = first_page
    for part in b.geo.parts:
        opens.append(at)
        at += len(_chunks(part.places, room))
    for name, group in zip(_spread("Platser", len(groups)), groups, strict=True):
        keys: dict[int, TklDeckKey] = {}
        for index, which in zip(area, group, strict=False):
            n = int(which)
            keys[index] = TklDeckKey(type=K.PART, part=n, page=opens[n], text=b.geo.parts[n].name)
        cancel = f.fixed.get("next") if f.style == DeckStyle.NEXT else area[-1]
        b.page(name, DeckMode.PLACES, DeckPageKind.PARTS, keys, cancel=cancel)
    for number, part in enumerate(b.geo.parts):
        pieces = _chunks(part.places, room)
        for n, piece in enumerate(pieces, start=1):
            keys = {i: _place_key(b, p) for i, p in zip(area, piece, strict=False)}
            keys[area[-1]] = TklDeckKey(type=K.ACTION, action=DeckAction.BACK)
            cancel = f.fixed.get("next") if f.style == DeckStyle.NEXT else area[-2]
            b.page(
                part.name if len(pieces) == 1 else f"{part.name} {n}",
                DeckMode.PLACES,
                DeckPageKind.PART,
                keys,
                listed=False,
                cancel=cancel,
                part=number,
            )


def _columns(b: Builder) -> None:
    """The big decks: a column per part west to east, the places top to bottom; a part with
    more places than rows goes on in the next column, at the bottom (SD66, SD2)."""
    f = b.frame
    width, height = f.body
    columns: list[list[tuple[int, str]]] = []
    starts: list[int] = []
    for part in b.geo.parts:
        starts.append(len(columns))
        head, rest = part.places[:height], part.places[height:]
        columns.append(list(enumerate(head)))
        for piece in _chunks(rest, height):
            columns.append([(height - len(piece) + i, p) for i, p in enumerate(piece)])
    pages: list[list[list[tuple[int, str]]]] = []
    current: list[list[tuple[int, str]]] = []
    for number, _ in enumerate(b.geo.parts):
        end = starts[number + 1] if number + 1 < len(starts) else len(columns)
        mine = columns[starts[number] : end]
        if current and len(current) + len(mine) > width:
            pages.append(current)
            current = []
        for column in mine:
            if len(current) == width:
                pages.append(current)
                current = []
            current.append(column)
    if current:
        pages.append(current)
    trains = f.grid.columns >= WIDE
    for name, page in zip(_spread("Platser", len(pages)), pages, strict=True):
        keys: dict[int, TklDeckKey] = {}
        for c, column in enumerate(page):
            for r, place in column:
                keys[f.rows[r][c]] = _place_key(b, place)
        if trains and len(page) < width:
            for slot, r in enumerate(range(height), start=1):
                keys[f.rows[r][width - 1]] = TklDeckKey(type=K.TRAIN, slot=slot)
        b.page(name, DeckMode.PLACES, DeckPageKind.PLACES, keys, cancel=b.cancel_at(set(keys)))


def _part_rows(b: Builder) -> None:
    """The fixed row at the bottom: a row per part, a part sharing the row before when it
    fits, and as many rows per page as there are (SD80). On a wide deck the keys left over
    show the nearest trains (SD85)."""
    f = b.frame
    rows: list[list[str]] = []
    widths = [len(r) for r in f.rows]
    for part in b.geo.parts:
        if rows and len(rows[-1]) + len(part.places) <= widths[(len(rows) - 1) % len(widths)]:
            rows[-1].extend(part.places)
            continue
        rest = list(part.places)
        while rest:
            width = widths[len(rows) % len(widths)]
            rows.append(rest[:width])
            rest = rest[width:]
    per_page = len(f.rows)
    pages = _chunks([str(i) for i in range(len(rows))], per_page)
    trains = f.grid.columns >= WIDE
    for name, page in zip(_spread("Platser", len(pages)), pages, strict=True):
        keys: dict[int, TklDeckKey] = {}
        for r, which in enumerate(page):
            for index, place in zip(f.rows[r], rows[int(which)], strict=False):
                keys[index] = _place_key(b, place)
        if trains:
            free = [i for i in f.area if i not in keys]
            for slot, index in enumerate(free, start=1):
                keys[index] = TklDeckKey(type=K.TRAIN, slot=slot)
        b.page(name, DeckMode.PLACES, DeckPageKind.PLACES, keys, cancel=b.cancel_at(set(keys)))


# --- The geographic pages and Alla (SD25, SD73) ------------------------------------------------


def _signals(b: Builder) -> None:
    f = b.frame
    starts = [p for p in b.geo.points if p.start]
    if not starts:
        return
    area, extra = _slots(f, True)
    height = len(f.rows)
    capacity = len(area)
    by_x = sorted(starts, key=lambda p: (p.x, p.y))
    groups = [by_x[i : i + capacity] for i in range(0, len(by_x), capacity)]
    for name, group in zip(_spread("Signaler", len(groups)), groups, strict=True):
        keys: dict[int, TklDeckKey] = dict(extra)
        columns = [group[i : i + height] for i in range(0, len(group), height)]
        width = max(len(r) for r in f.rows)
        if len(columns) <= width:
            for c, column in enumerate(columns):
                for r, point in enumerate(sorted(column, key=lambda p: p.y)):
                    row = f.rows[r]
                    if c < len(row) and row[c] not in keys:
                        keys[row[c]] = TklDeckKey(type=K.SIGNAL, point=point.name)
        placed = {k.point for k in keys.values() if k.point}
        free = [i for i in area if i not in keys]
        for index, point in zip(free, [p for p in group if p.name not in placed], strict=False):
            keys[index] = TklDeckKey(type=K.SIGNAL, point=point.name)
        b.page(name, DeckMode.PLACES, DeckPageKind.SIGNALS, keys, cancel=b.cancel_at(set(keys)))
    every = sorted((p.name for p in starts), key=_natural_key)
    pages = _chunks(every, capacity)
    names = ["Alla"] + [f"Alla {n}" for n in range(2, len(pages) + 1)]
    for name, page in zip(names, pages, strict=True):
        keys = dict(extra)
        for index, name_of in zip(area, page, strict=False):
            keys[index] = TklDeckKey(type=K.SIGNAL, point=name_of)
        b.page(name, DeckMode.PLACES, DeckPageKind.ALL, keys, cancel=b.cancel_at(set(keys)))


def _natural_key(name: str) -> tuple[tuple[int, str], ...]:
    parts: list[tuple[int, str]] = []
    digits = ""
    for character in name + "\0":
        if character.isdigit():
            digits += character
            continue
        if digits:
            parts.append((0, f"{int(digits):08d}"))
            digits = ""
        if character != "\0":
            parts.append((1, character))
    return tuple(parts)


# --- Spårplan (SD70, SD71, SD81, SD84) ---------------------------------------------------------


def _track_plan(b: Builder, panel: Panel | None) -> None:
    f = b.frame
    if panel is None:
        return
    width, height = f.body
    if not width or not height:
        return
    whole_keys: dict[int, TklDeckKey] = {}
    tw, th = panel.width / width, panel.height / height
    names = [(n.name, n.cell) for n in panel.track_names]
    names += [(label.text, label.cell) for label in panel.labels if label.kind == "exit"]
    for r in range(height):
        for c in range(width):
            x, y = c * tw, r * th
            inside = [n for n, (nx, ny) in names if x <= nx < x + tw and y <= ny < y + th]
            whole_keys[f.rows[r][c]] = TklDeckKey(
                type=K.TILE, rect=(x, y, tw, th), text=" ".join(inside)[:60]
            )
    b.page("Hela", DeckMode.TRACK_PLAN, DeckPageKind.WHOLE, whole_keys)
    keys: dict[int, TklDeckKey] = {}
    fixed: dict[int, TklDeckKey] = {}
    pan_at: list[int] = []
    cut_rows = [row[:width] for row in f.rows[:height]]
    if f.grid.dials >= 2:
        # The dials pan (SD83, SD84): no arrows; Hela where a key is left over.
        if f.style == DeckStyle.LAST:
            cut_rows = f.rows[:1]
        left = [i for i in f.area if i not in {j for row in cut_rows for j in row}]
        pan_at = left[:1]
    elif f.style == DeckStyle.ROW and len(f.rows) == f.grid.rows - 1 and f.grid.columns >= 5:
        # The 15 (SD81): the fixed row becomes Hela, väster, öster, nedåt and Läge.
        bottom = (f.grid.rows - 1) * f.grid.columns
        row = list(range(bottom, bottom + f.grid.columns))
        for index in row:
            fixed[index] = TklDeckKey(type=K.ACTION, action=DeckAction.CANCEL)
        pans = (DeckPan.WHOLE, DeckPan.WEST, DeckPan.EAST, DeckPan.DOWN)
        for index, pan in zip(row[-5:-1], pans, strict=True):
            fixed[index] = TklDeckKey(type=K.PAN, pan=pan)
        fixed[row[-1]] = TklDeckKey(type=K.MODE)
        for index in row[:-5]:
            del fixed[index]
    elif len(cut_rows) >= 3:
        pan_at = cut_rows[-1][: len(PANS)]
        cut_rows = cut_rows[:-1]
    else:
        top = f.rows[0]
        pan_at = top[len(top) - len(PANS) :] if len(top) > len(PANS) else []
        keep = min(min(len(r) for r in f.rows), len(top) - len(pan_at))
        cut_rows = [row[:keep] for row in f.rows]
    for r, row in enumerate(cut_rows):
        for c, index in enumerate(row):
            keys[index] = TklDeckKey(type=K.CELL, dx=c, dy=r)
    for index, pan in zip(pan_at, PANS, strict=False):
        keys[index] = TklDeckKey(type=K.PAN, pan=pan)
    cancel = next((i for i in reversed(f.area) if i not in keys), None)
    if cancel is None:
        cancel = f.fixed.get("arrived") or f.fixed.get("release")
    b.page(
        "Utsnitt",
        DeckMode.TRACK_PLAN,
        DeckPageKind.CUTOUT,
        keys,
        cancel=cancel,
        fixed=fixed,
    )


def cut_size(page: TklDeckPage) -> tuple[int, int]:
    """The cut-out's width and height in squares."""
    cells = [k for k in page.keys if k is not None and k.type == K.CELL]
    if not cells:
        return 0, 0
    return max(k.dx or 0 for k in cells) + 1, max(k.dy or 0 for k in cells) + 1
