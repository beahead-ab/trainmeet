"""The owner's deviations from the default profile (#86 del c, SD32, SD40, SD43, SD55).

The default is computed from the station model for every size (SD39, tkl.deck.profile). What the
owner changes in Studio, Inställningar, Stream Deck is kept as deviations from it, per size, in
stable ids: a key by what it is (its type and what it points at: a route start → goal, a place,
a signal, a slot, an action), a page by its kind and its name, and a cell only as where a key
goes. When the drawing changes, the default is computed again and the deviations are laid on
again; what cannot be laid on any more is Att kolla, with the reason, and kept until the owner
takes it away (SD40).

The owner may change where a key is, its text and the line under, what a press and a hold do
from the fixed list `DeckAction`, and what the key shows (SD43). Never a colour, a symbol or
what a gesture means (SD3): a deviation that tries is refused with the reason. Lös ut alla,
Noll and Nödutlösning are done with a hold, never a press (SD29), and never on a pedal (SD55).
The fixed row is the same on every page and is not changed here (SD27).

The shunter's deck, Bangård (#87 del d), has deviations of its own per part and size: its keys
are the shunter's, and a page of it takes only those.

`apply` is pure: the default, the deviations and what the station has in, the owner's profile
and Att kolla out. `diff` is its reverse, so that Studio keeps the fewest deviations that make
the owner's profile: apply(default, diff(default, profile)) is the profile.

No code here names a station (RS13).
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from threading import Lock
from typing import Final

from contracts.station_model import PartSide
from contracts.tkl import (
    DeckAction,
    DeckChange,
    DeckKeyType,
    DeckMode,
    DeckModelId,
    DeckPageKind,
    DeckPageRef,
    DeckStyle,
    Panel,
    TklDeckDeviation,
    TklDeckGrid,
    TklDeckKey,
    TklDeckPage,
    TklDeckProfile,
    TklDeckRoute,
    TklDeckToCheck,
)
from tkl.deck.places import Geography
from tkl.deck.profile import Frame, build, frame, geography_of
from tkl.stallverk import Plant
from tkl.standard import RouteKind as EngineKind

K = DeckKeyType
A = DeckAction
C = DeckChange

IDENTITY: Final = (
    "type",
    "slot",
    "point",
    "place",
    "part",
    "dx",
    "dy",
    "rect",
    "pan",
    "action",
    "function",
    "route",
    "track",
    "side",
)
"""What a key is: the fields that find it again on a page after the default is made again."""
LOOK: Final = ("text", "under", "press", "hold", "number", "dim", "confirm")
"""What the owner may change about a key, besides its place (SD43)."""
HOLD_ONLY: Final = frozenset({A.RELEASE_ALL, A.RESET, A.EMERGENCY})
"""Done with a hold, never a press (SD29); never on a pedal (SD55)."""
WITH_ROUTE: Final = frozenset({A.LAY, A.RELEASE_ROUTE})
"""Need the key's own route: only a snabbväg has one."""
PRESS: Final[dict[DeckKeyType, frozenset[DeckAction]]] = {
    K.ROUTE: frozenset({A.LAY, A.RUN, A.NOTHING}),
    K.ACTION: frozenset({A.RELEASE, A.ARRIVED, A.RUN, A.CANCEL, A.BACK, A.LOCK, A.NOTHING}),
    K.PANEL: frozenset({A.NOTHING}),
}
"""What a press may do, per type: the fixed list (SD43). Other types keep the catalogue's."""
HOLD: Final[dict[DeckKeyType, frozenset[DeckAction]]] = {
    K.ROUTE: frozenset({A.RELEASE_ROUTE, A.NOTHING}),
    K.ACTION: frozenset({A.RELEASE, A.RELEASE_ALL, A.RESET, A.EMERGENCY, A.CANCEL, A.NOTHING}),
    K.PANEL: frozenset({A.NOTHING}),
}
"""What a hold may do, per type (SD29, SD43)."""
ADDABLE: Final = frozenset(
    {
        K.TRAIN,
        K.LINE,
        K.ALARM,
        K.TRACK,
        K.PLACE,
        K.SIGNAL,
        K.DAILY,
        K.FAVOURITE,
        K.MODE,
        K.NEXT,
        K.PAGE,
        K.ACTION,
        K.PANEL,
        K.ROUTE,
        K.END,
        K.STREET,
        K.REQUEST,
        K.READY,
    }
)
"""The types the owner can put on a page from Knappar. Spårplan's squares and a part's key
are the default's: they follow the drawing."""
YARD_KEYS: Final = frozenset({K.END, K.STREET, K.REQUEST, K.READY})
"""The shunter's own keys (#87 del d): only on Bangård's pages."""
YARD_ACTIONS: Final = frozenset(
    {A.GIVE_BACK, A.DONE, A.RING, A.GATES, A.HORN, A.FIKA, A.CLOCK, A.REQUESTS}
)
"""The shunter's own actions (SD61, RANG-04): only on Bangård's pages."""
ON_YARD: Final = YARD_KEYS | frozenset({K.ACTION, K.MODE, K.NEXT, K.PAGE})
"""What a page of Bangård takes: the shunter's keys, the actions and the navigation."""
ON_A_PEDAL: Final = frozenset({K.ACTION, K.ROUTE, K.PANEL})
"""A pedal has no screen (SD55): an action, a snabbväg or a panel function."""
COLOURS: Final = frozenset(
    {"bg", "fg", "frame", "band", "line", "bar", "dot", "blink", "colour", "color", "farg", "fill"}
)
SYMBOLS: Final = frozenset({"symbol", "icon", "ikon", "star", "emoji", "shape", "form", "dashed"})
ACTION_NAMES: Final = {
    A.RELEASE: "Lös ut",
    A.ARRIVED: "Ankommit",
    A.RUN: "Kör",
    A.CANCEL: "Avbryt",
    A.BACK: "Tillbaka",
    A.LOCK: "Lås",
    A.LAY: "Lägg vägen",
    A.RELEASE_ROUTE: "Lös ut vägen",
    A.RELEASE_ALL: "Lös ut alla",
    A.RESET: "Noll",
    A.EMERGENCY: "Nödutlösning",
    A.NOTHING: "Ingenting",
    A.GIVE_BACK: "Lämna",
    A.DONE: "Klart",
    A.RING: "Ring",
    A.GATES: "Grindar",
    A.HORN: "Tuta",
    A.FIKA: "Fika",
    A.CLOCK: "Klocka",
    A.REQUESTS: "Begär",
}
TYPE_NAMES: Final = {
    K.TRAIN: "Tågknapp",
    K.LINE: "Linjeknapp",
    K.ALARM: "Larm och klocka",
    K.TRACK: "Spårknapp",
    K.PLACE: "Plats",
    K.PART: "Del",
    K.SIGNAL: "Signal",
    K.DAILY: "Dagens väg",
    K.FAVOURITE: "Favorit",
    K.TILE: "Spårplanens bit",
    K.CELL: "Utsnittets ruta",
    K.PAN: "Panorering",
    K.MODE: "Läge",
    K.NEXT: "Nästa sida",
    K.PAGE: "Nästa sida",
    K.ACTION: "Funktion",
    K.PANEL: "Panelfunktion",
    K.ROUTE: "Snabbväg",
    K.END: "Ände",
    K.STREET: "Spår",
    K.REQUEST: "Väg ut",
    K.READY: "Tågknapp, klart att skicka",
}
END_NAMES: Final = {PartSide.LEFT: "vänster", PartSide.RIGHT: "höger"}
ARROW: Final = "\N{RIGHTWARDS ARROW}"


# --- what a key and a page are ------------------------------------------------------------------


def identity(key: TklDeckKey) -> str:
    """What the key is, as text: the same key on the default made again has the same."""
    found = key.model_dump(mode="json", include=set(IDENTITY), exclude_none=True)
    return json.dumps(found, sort_keys=True, ensure_ascii=False)


def looks(key: TklDeckKey) -> dict[str, object]:
    return {name: getattr(key, name) for name in LOOK}


def ref_of(page: TklDeckPage) -> DeckPageRef:
    return DeckPageRef(kind=page.kind, name=page.name)


def same_ref(a: DeckPageRef | None, b: DeckPageRef | None) -> bool:
    return a is not None and b is not None and a.kind == b.kind and a.name == b.name


def describe(key: TklDeckKey | None) -> str:
    """The key in words, for Att kolla and the checks."""
    if key is None:
        return "knappen"
    match key.type:
        case K.ROUTE if key.route is not None:
            kind = "växlingsvägen" if key.route.kind.value == "shunting" else "tågvägen"
            return f"snabbvägen {key.route.start} {ARROW} {key.route.end} ({kind})"
        case K.SIGNAL:
            return f"signalen {key.point}"
        case K.PLACE | K.TRACK:
            return f"platsen {key.place}"
        case K.ACTION if key.action is not None:
            return ACTION_NAMES[key.action]
        case K.PANEL:
            return f"panelfunktionen {key.function}"
        case K.TRAIN | K.LINE | K.DAILY | K.FAVOURITE:
            return f"{TYPE_NAMES[key.type].lower()} {key.slot or ''}".strip()
        case K.PAN if key.pan is not None:
            return f"panoreringen {key.pan.value}"
        case K.STREET | K.REQUEST:
            what = "spåret" if key.type == K.STREET else "vägen ut till"
            end = f" från {END_NAMES[key.side]} ände" if key.side is not None else ""
            return f"{what} {key.track}{end}"
    return TYPE_NAMES.get(key.type, key.type.value)


def cap(text: str) -> str:
    """The first letter capital, the rest as it is: signal and place names keep their case."""
    return text[:1].upper() + text[1:]


def page_words(ref: DeckPageRef | None) -> str:
    return f"sidan {ref.name}" if ref is not None else "decket"


# --- what the station has ----------------------------------------------------------------------


@dataclass(frozen=True)
class Known:
    """What a key may point at: the station's starts and goals, places, parts, panel functions
    and routes. A key that points at something else is Att kolla (SD40) and a problem (SD44)."""

    points: frozenset[str]
    places: frozenset[str]
    parts: int
    functions: frozenset[str]
    route: Callable[[TklDeckRoute], bool]
    streets: frozenset[tuple[str, PartSide | None]] = frozenset()
    """Bangård: the part's switch streets, by track and end (#87 del d)."""
    outs: frozenset[tuple[str, PartSide | None]] = frozenset()
    """Bangård: the part's routes out, by track and end."""

    def has(self, key: TklDeckKey) -> str | None:
        """Why the key points at nothing, else None."""
        match key.type:
            case K.STREET if not _at_end(self.streets, key):
                end = f" från {END_NAMES[key.side]} ände" if key.side is not None else ""
                return f"Delen har ingen växelgata till {key.track}{end}."
            case K.REQUEST if not _at_end(self.outs, key):
                end = f" från {END_NAMES[key.side]} ände" if key.side is not None else ""
                return f"Delen har ingen väg ut till {key.track}{end}."
            case K.SIGNAL if key.point not in self.points:
                return f"Signalen {key.point} finns inte i stationsmodellen."
            case K.PLACE | K.TRACK if key.place not in self.places:
                return f"Platsen {key.place} finns inte i stationsmodellen."
            case K.PART if key.part is None or key.part >= self.parts:
                return "Delen finns inte längre."
            case K.PANEL if key.function not in self.functions:
                return f"Panelfunktionen {key.function} finns inte i stationsmodellen."
            case K.ROUTE:
                if key.route is None:
                    return "Snabbvägen har ingen väg."
                if not self.route(key.route):
                    return (
                        f"Vägen {key.route.start} {ARROW} {key.route.end} finns inte i "
                        "stationsmodellen."
                    )
        return None


def _at_end(found: frozenset[tuple[str, PartSide | None]], key: TklDeckKey) -> bool:
    """A street or a route out to the key's track, from its end when it has one."""
    return any(t == key.track and (key.side is None or s in (key.side, None)) for t, s in found)


def route_exists(plant: Plant) -> Callable[[TklDeckRoute], bool]:
    def check(route: TklDeckRoute) -> bool:
        kind = EngineKind(route.kind.value)
        if route.start not in plant.points or route.end not in plant.points:
            return False
        return bool(plant.candidates(kind, route.start, route.end))

    return check


def known_of(plant: Plant, geo: Geography, part: str | None = None) -> Known:
    found = plant.parts.get(part) if part is not None else None
    return Known(
        streets=frozenset((s.track, s.side) for s in found.streets.values())
        if found
        else frozenset(),
        outs=frozenset((r.track, r.side) for r in found.routes_out.values())
        if found
        else frozenset(),
        points=frozenset(p.name for p in geo.points)
        | frozenset(plant.points)
        | frozenset(geo.start_place)
        | frozenset(geo.end_place),
        places=frozenset(p.id for p in geo.places),
        parts=len(geo.parts),
        functions=frozenset(plant.functions),
        route=route_exists(plant),
    )


# --- SD43: what may be changed, refused with the reason ------------------------------------------


def _extras(given: object) -> list[str]:
    extra = getattr(given, "model_extra", None) or {}
    return sorted(str(k) for k in extra)


def _locked(names: Iterable[str]) -> str | None:
    found = list(names)
    if not found:
        return None
    if any(n.lower() in COLOURS for n in found):
        return "Färgerna är låsta och lika på alla stationer (SD3, SD43)."
    if any(n.lower() in SYMBOLS for n in found):
        return "Symbolerna är låsta och lika på alla stationer (SD3, SD43)."
    return f"Det går inte att ändra {', '.join(found)} på en knapp (SD43)."


def _symbols(text: str | None) -> bool:
    """A symbol or an emoji in the owner's text: the symbols are locked (SD3, SD6)."""
    return bool(text) and any(unicodedata.category(c) == "So" for c in text or "")


def refused(deviation: TklDeckDeviation, size: DeckModelId | None, grid: TklDeckGrid) -> str | None:
    """Why the owner may not make this change, in Swedish; None when it may be made (SD43,
    SD29, SD55, SD27). What depends on the station, such as a route that does not exist, is not
    refused here: it is Att kolla when the deviation is laid on."""
    d = deviation
    locked = _locked(_extras(d) + (_extras(d.key) if d.key is not None else []))
    if locked:
        return locked
    pedal = grid.pedals > 0 and grid.columns * grid.rows == 0
    if d.change == C.PEDAL:
        if not pedal:
            return "Bara en pedal har pedaler (SD55)."
        if d.pedal is None or d.pedal >= grid.pedals:
            return f"Pedalen finns inte: decket har {grid.pedals} pedaler."
        return _on_pedal(d.key)
    if pedal:
        return "En pedal har inga sidor: välj en funktion per pedal (SD55)."
    if d.change in (C.MOVE, C.ADD, C.REMOVE, C.KEY) and (d.page is None or d.key is None):
        return "Ändringen behöver en sida och en knapp."
    if d.change in (C.MOVE, C.ADD) and d.cell is None:
        return "Ändringen behöver en plats på sidan."
    if d.cell is not None:
        size_of = grid.columns * grid.rows
        if d.cell >= size_of:
            return f"Decket har {size_of} knappar."
        if d.cell in frame(grid).fixed.values():
            return "Den fasta raden är densamma på alla sidor och ändras inte här (SD27)."
    if d.change == C.ADD and d.key is not None and d.key.type not in ADDABLE:
        name = TYPE_NAMES.get(d.key.type, d.key.type.value)
        return f"{name} följer ritningen och läggs inte dit."
    if d.change in (C.ADD_PAGE, C.REMOVE_PAGE) and d.page is None:
        return "Ändringen behöver en sida."
    if d.change == C.ADD_PAGE:
        assert d.page is not None
        if d.page.kind != DeckPageKind.OWN:
            return "En ny sida är ägarens egen."
        if d.mode is None:
            return "En ny sida behöver ett läge."
    if d.change == C.ORDER and not d.order:
        return "Ordningen behöver sidorna."
    key = d.key
    if key is not None and d.change in (C.ADD, C.KEY):
        return _look_refused(key, d)
    return None


def _look_refused(key: TklDeckKey, d: TklDeckDeviation) -> str | None:
    texts = [key.text, key.under, d.text, d.under]
    if any(_symbols(t) for t in texts):
        return "Symbolerna är låsta (SD3, SD6): skriv med ord på knappen."
    for gesture, chosen, allowed in (
        ("ett tryck", d.press if d.press is not None else key.press, PRESS),
        ("håll in", d.hold if d.hold is not None else key.hold, HOLD),
    ):
        if chosen is None:
            continue
        if gesture == "ett tryck" and chosen in HOLD_ONLY:
            return (
                f"{ACTION_NAMES[chosen]} görs med håll in, aldrig med ett tryck (SD29). "
                "Handgreppens betydelse är låst (SD3)."
            )
        if chosen in WITH_ROUTE and key.type != K.ROUTE:
            return f"{ACTION_NAMES[chosen]} behöver en snabbväg: knappen har ingen egen väg."
        if chosen not in allowed.get(key.type, frozenset()):
            return (
                f"Vad {gesture} gör på {TYPE_NAMES.get(key.type, key.type.value).lower()} är "
                "låst och lika på alla stationer (SD3, SD43)."
            )
    if key.type == K.ACTION and key.action in WITH_ROUTE:
        return f"{ACTION_NAMES[key.action]} behöver en snabbväg."
    return None


def _on_pedal(key: TklDeckKey | None) -> str | None:
    """SD55: a pedal does nothing until chosen; never Lös ut alla, Noll or Nödutlösning."""
    if key is None:
        return None
    if key.type not in ON_A_PEDAL:
        return "En pedal har ingen skärm: välj en funktion, en snabbväg eller en panelfunktion."
    for chosen in (key.action, key.press, key.hold):
        if chosen in HOLD_ONLY:
            return f"{ACTION_NAMES[chosen]} går inte att lägga på en pedal (SD55)."
    if key.type == K.ACTION and key.action in WITH_ROUTE:
        return f"{ACTION_NAMES[key.action]} behöver en snabbväg."
    for gesture, chosen, allowed in (("ett tryck", key.press, PRESS), ("håll in", key.hold, HOLD)):
        if chosen is not None and chosen not in allowed.get(key.type, frozenset()):
            return f"Vad {gesture} gör är låst för {TYPE_NAMES[key.type].lower()} (SD3, SD43)."
    return None


def refusals(
    deviations: list[TklDeckDeviation], size: DeckModelId | None, grid: TklDeckGrid
) -> list[str]:
    """Every refused deviation, numbered from one as Studio lists them."""
    found = []
    for n, d in enumerate(deviations, start=1):
        reason = refused(d, size, grid)
        if reason:
            found.append(f"Ändring {n}: {reason}")
    return found


# --- apply: the default with the deviations laid on (SD40) ---------------------------------------


@dataclass
class _Page:
    """A page while the deviations are laid on: where it came from in the default, if it did."""

    page: TklDeckPage
    keys: list[TklDeckKey | None]
    origin: int | None

    @property
    def ref(self) -> DeckPageRef:
        return ref_of(self.page)


@dataclass(frozen=True)
class Applied:
    """The owner's profile, Att kolla, and the pages with the owner's changes."""

    profile: TklDeckProfile
    to_check: list[TklDeckToCheck] = field(default_factory=list)
    changed: frozenset[str] = frozenset()
    """The changed pages, as `ref_key` of their refs."""


def ref_key(ref: DeckPageRef) -> str:
    return f"{ref.kind.value}\N{UNIT SEPARATOR}{ref.name}"


@dataclass
class _Work:
    default: TklDeckProfile
    pages: list[_Page]
    pedals: list[TklDeckKey | None]
    frame: Frame
    known: Known | None

    def find(self, ref: DeckPageRef | None) -> _Page | None:
        if ref is None:
            return None
        return next((p for p in self.pages if same_ref(p.ref, ref)), None)

    @property
    def fixed(self) -> set[int]:
        return set(self.frame.fixed.values())

    def area(self) -> list[int]:
        return [i for i in self.frame.area if i not in self.fixed]


def _at(page: _Page, key: TklDeckKey, fixed: set[int]) -> int | None:
    wanted = identity(key)
    found = [i for i, k in enumerate(page.keys) if k is not None and identity(k) == wanted]
    free = [i for i in found if i not in fixed]
    if free:
        return free[0]
    return found[0] if found else None


def _first_free(work: _Work, page: _Page) -> int | None:
    return next((i for i in work.area() if page.keys[i] is None), None)


def _place(work: _Work, page: _Page, key: TklDeckKey, cell: int) -> str | None:
    """A key onto a cell of a page: one already on the page moves there and what stood there
    takes its old cell; a new one displaces what stood there to the first free cell."""
    fixed = work.fixed
    if cell in fixed or cell >= len(page.keys):
        return "Platsen finns inte längre på sidan, eller är den fasta raden."
    here = _at(page, key, fixed)
    if here is not None:
        if here in fixed:
            return "Knappen står i den fasta raden och flyttas inte (SD27)."
        page.keys[here], page.keys[cell] = page.keys[cell], page.keys[here]
        return None
    occupant = page.keys[cell]
    if occupant is not None:
        free = _first_free(work, page)
        if free is None:
            return f"Sidan {page.page.name} är full."
        page.keys[free] = occupant
    page.keys[cell] = key
    return None


def _looked(key: TklDeckKey, d: TklDeckDeviation) -> TklDeckKey:
    update = {name: getattr(d, name) for name in LOOK if getattr(d, name) is not None}
    return key.model_copy(update=update) if update else key


def _fixed_keys(work: _Work, mode: DeckMode) -> list[TklDeckKey | None]:
    """A new page's keys: the fixed row as the mode's first ordinary page has it."""
    size = work.frame.size
    base = next(
        (
            p
            for p in work.default.pages
            if p.mode == mode and p.kind not in (DeckPageKind.CUTOUT, DeckPageKind.PART)
        ),
        next((p for p in work.default.pages if p.kind != DeckPageKind.CUTOUT), None),
    )
    keys: list[TklDeckKey | None] = [None] * size
    if base is not None:
        for i in work.fixed:
            if i < len(base.keys):
                keys[i] = base.keys[i]
    return keys


def _one(work: _Work, d: TklDeckDeviation) -> str | None:
    """Lays one deviation on; why it could not, else None."""
    if d.change == C.PEDAL:
        if d.pedal is None or d.pedal >= len(work.pedals):
            return f"Decket har {len(work.pedals)} pedaler."
        if d.key is not None and work.known is not None:
            missing = work.known.has(d.key)
            if missing:
                return missing
        work.pedals[d.pedal] = d.key
        return None
    if d.change == C.ORDER:
        return _order(work, d.order)
    if d.change == C.ADD_PAGE:
        assert d.page is not None and d.mode is not None
        if work.find(d.page) is not None:
            return f"Det finns redan en sida {d.page.name}."
        if d.mode not in work.default.modes:
            return "Decket har inte det läget i den här storleken."
        made = TklDeckPage(name=d.page.name, mode=d.mode, kind=DeckPageKind.OWN, keys=[])
        last = max((i for i, p in enumerate(work.pages) if p.page.mode == d.mode), default=-1)
        work.pages.insert(last + 1, _Page(made, _fixed_keys(work, d.mode), None))
        return None
    page = work.find(d.page)
    if page is None:
        return f"{cap(page_words(d.page))} finns inte längre."
    if d.change == C.REMOVE_PAGE:
        if page.page.kind == DeckPageKind.PART or not page.page.listed:
            return "En dels sida följer delen och tas inte bort."
        same_mode = [p for p in work.pages if p.page.mode == page.page.mode and p.page.listed]
        if len(same_mode) <= 1:
            return "Läget behöver minst en sida."
        work.pages.remove(page)
        return None
    assert d.key is not None
    if d.change == C.ADD:
        assert d.cell is not None
        wrong = _not_here(page.page, d.key)
        if wrong:
            return wrong
        if work.known is not None:
            missing = work.known.has(d.key)
            if missing:
                return missing
        return _place(work, page, d.key, d.cell)
    here = _at(page, d.key, work.fixed)
    if here is None:
        return f"{cap(describe(d.key))} finns inte längre på {page_words(d.page)}."
    if d.change == C.MOVE:
        assert d.cell is not None
        return _place(work, page, d.key, d.cell)
    if d.change == C.REMOVE:
        if here in work.fixed:
            return "Den fasta raden är densamma på alla sidor (SD27)."
        page.keys[here] = None
        return None
    if here in work.fixed:
        return "Den fasta raden är densamma på alla sidor och ändras inte här (SD27)."
    found = page.keys[here]
    assert found is not None
    page.keys[here] = _looked(found, d)
    return None


def _not_here(page: TklDeckPage, key: TklDeckKey) -> str | None:
    """The shunter's keys only on Bangård's pages, and only those there (#87 del d)."""
    shunter = key.type in YARD_KEYS or (key.type == K.ACTION and key.action in YARD_ACTIONS)
    if page.mode == DeckMode.YARD:
        if key.type not in ON_YARD:
            return "Bangård har bara rangerarens knappar."
        if key.type == K.ACTION and not shunter and key.action != A.RUN:
            return "Bangård har bara rangerarens knappar."
        return None
    if shunter:
        return "Rangerarens knappar finns bara i Bangård, på en dels deck."
    return None


def _order(work: _Work, order: list[DeckPageRef]) -> str | None:
    found = [work.find(r) for r in order]
    pages = [p for p in found if p is not None]
    if not pages:
        return "Sidorna finns inte längre."
    mode = pages[0].page.mode
    pages = [p for p in pages if p.page.mode == mode]
    slots = [i for i, p in enumerate(work.pages) if p.page.mode == mode and p.page.listed]
    rest = [work.pages[i] for i in slots if work.pages[i] not in pages]
    for i, p in zip(slots, pages + rest, strict=True):
        work.pages[i] = p
    missing = [r.name for r, p in zip(order, found, strict=True) if p is None]
    if missing:
        return f"Sidorna {', '.join(missing)} finns inte längre; de andra är i ordning."
    return None


def _cancel(work: _Work, page: _Page) -> int | None:
    """Where Avbryt stands while a start is chosen: kept when its cell is still free."""
    before = page.page.cancel
    fixed = work.fixed
    if before is not None and (before in fixed or page.keys[before] is None):
        return before
    f = work.frame
    if f.style == DeckStyle.NEXT:
        return f.fixed.get("next")
    if f.style == DeckStyle.ROW and "arrived" in f.fixed:
        return f.fixed["arrived"]
    free = [i for i in reversed(work.area()) if page.keys[i] is None]
    if free:
        return free[0]
    return f.fixed.get("arrived") or f.fixed.get("release")


def apply(
    default: TklDeckProfile, deviations: list[TklDeckDeviation], known: Known | None = None
) -> Applied:
    """The owner's profile: the default with every deviation laid on in order, and Att kolla
    for those that cannot be (SD40). Pure: the default is not changed."""
    if not deviations:
        return Applied(default)
    work = _Work(
        default=default,
        pages=[_Page(p, list(p.keys), i) for i, p in enumerate(default.pages)],
        pedals=list(default.pedals),
        frame=frame(default.grid),
        known=known,
    )
    to_check: list[TklDeckToCheck] = []
    changed: set[str] = set()
    for n, d in enumerate(deviations):
        reason = _one(work, d)
        if reason:
            to_check.append(TklDeckToCheck(deviation=n, text=reason, page=d.page, key=d.key))
            continue
        for ref in [d.page, *d.order]:
            if ref is not None:
                changed.add(ref_key(ref))
    new_index = {p.origin: i for i, p in enumerate(work.pages) if p.origin is not None}
    pages = []
    for p in work.pages:
        keys = [_repointed(k, new_index) for k in p.keys]
        pages.append(p.page.model_copy(update={"keys": keys, "cancel": _cancel(work, p)}))
    profile = default.model_copy(update={"pages": pages, "pedals": work.pedals})
    return Applied(profile, to_check, frozenset(changed))


def _repointed(key: TklDeckKey | None, new_index: dict[int, int]) -> TklDeckKey | None:
    """A part's key opens its page where the page is now."""
    if key is None or key.page is None:
        return key
    return key.model_copy(update={"page": new_index.get(key.page, key.page)})


# --- diff: the fewest deviations that make a profile ----------------------------------------------


def diff(default: TklDeckProfile, profile: TklDeckProfile) -> list[TklDeckDeviation]:
    """The deviations that make `profile` from `default`, in stable ids: the pages removed and
    added, their order, then every page's keys, then the pedals. apply(default, diff) is the
    profile again."""
    found: list[TklDeckDeviation] = []
    default_refs = [ref_of(p) for p in default.pages]
    profile_refs = [ref_of(p) for p in profile.pages]
    work = _Work(
        default=default,
        pages=[_Page(p, list(p.keys), i) for i, p in enumerate(default.pages)],
        pedals=list(default.pedals),
        frame=frame(default.grid),
        known=None,
    )

    def lay(d: TklDeckDeviation) -> None:
        reason = _one(work, d)
        assert reason is None, reason
        found.append(d)

    for ref in default_refs:
        if not any(same_ref(ref, r) for r in profile_refs):
            lay(TklDeckDeviation(change=C.REMOVE_PAGE, page=ref))
    for p in profile.pages:
        if not any(same_ref(ref_of(p), r) for r in default_refs):
            lay(TklDeckDeviation(change=C.ADD_PAGE, page=ref_of(p), mode=p.mode))
    for mode in profile.modes:
        wanted = [ref_of(p) for p in profile.pages if p.mode == mode and p.listed]
        now = [p.ref for p in work.pages if p.page.mode == mode and p.page.listed]
        if [ref_key(r) for r in wanted] != [ref_key(r) for r in now]:
            lay(TklDeckDeviation(change=C.ORDER, order=wanted))
    fixed = work.fixed
    for p in profile.pages:
        page = work.find(ref_of(p))
        assert page is not None
        ref = ref_of(p)
        wanted_ids = {identity(k) for k in p.keys if k is not None}
        for i, k in enumerate(list(page.keys)):
            if k is not None and i not in fixed and identity(k) not in wanted_ids:
                lay(TklDeckDeviation(change=C.REMOVE, page=ref, key=k))
        for cell, k in enumerate(p.keys):
            if k is None or cell in fixed:
                continue
            here = _at(page, k, fixed)
            if here is None:
                lay(TklDeckDeviation(change=C.ADD, page=ref, key=k, cell=cell))
                continue
            if here != cell:
                lay(TklDeckDeviation(change=C.MOVE, page=ref, key=k, cell=cell))
            there = page.keys[cell]
            assert there is not None
            change = {
                name: value for name, value in looks(k).items() if value != getattr(there, name)
            }
            if change:
                made = TklDeckDeviation(change=C.KEY, page=ref, key=k)
                lay(made.model_copy(update=change))
    for i, pedal in enumerate(profile.pedals):
        if i < len(work.pedals) and pedal != work.pedals[i]:
            lay(TklDeckDeviation(change=C.PEDAL, pedal=i, key=pedal))
    return found


def tidy(
    default: TklDeckProfile, deviations: list[TklDeckDeviation], known: Known | None
) -> tuple[list[TklDeckDeviation], Applied]:
    """The fewest deviations that make the same profile, and Att kolla's own kept after them so
    that the owner decides what becomes of each (SD40)."""
    first = apply(default, deviations, known)
    kept = [deviations[c.deviation] for c in first.to_check]
    made = diff(default, first.profile) + kept
    return made, apply(default, made, known)


# --- the owner's profile, made once per default and deviations ------------------------------------


_MADE: dict[tuple[str, str, DeckModelId | None, str, str | None], Applied] = {}
_LOCK = Lock()
KEPT: Final = 64


def owned(
    plant: Plant,
    panel: Panel | None,
    grid: TklDeckGrid,
    model: DeckModelId | None,
    deviations: list[TklDeckDeviation],
    part: str | None = None,
) -> Applied:
    """The owner's profile for a deck: the default for its grid with the owner's deviations for
    its size, or for a part's deck the shunter's (#87 del d). The same default and deviations
    always give the same profile object, so that a deck's state is kept until one of them
    changes."""
    default = build(plant, panel, grid, model, part)
    if not deviations:
        return Applied(default)
    said = json.dumps([d.model_dump(mode="json") for d in deviations], sort_keys=True)
    key = (plant.fingerprint, grid.model_dump_json(), model, said, part)
    with _LOCK:
        known_made = _MADE.get(key)
    if known_made is not None:
        return known_made
    made = apply(default, deviations, known_of(plant, geography_of(plant, panel), part))
    with _LOCK:
        if len(_MADE) >= KEPT:
            _MADE.clear()
        _MADE[key] = made
    return made


__all__ = [
    "Applied",
    "Known",
    "apply",
    "cap",
    "describe",
    "diff",
    "identity",
    "known_of",
    "owned",
    "ref_of",
    "refusals",
    "refused",
    "tidy",
]
