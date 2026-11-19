"""The deck's logic (#86 del a): a pure state machine over a profile and the interlocking.

A deck takes a press, a hold (0.6 s by default, SD29), a dial or a touch, and calls the
interlocking's own functions through `Hands`: set a route, release it, Kör, Ankommit, a panel
function, and the station commands of TKL's clearance as it is (SD14). The interlocking says
yes or no (SD1); the deck has no route or safety logic of its own (STV-43). What a key shows is
read from the interlocking's state, its check of a route without setting it (the targets,
SD17), and the hub's snapshot:

- a route that cannot be set now is dimmed, with a mark and the interlocking's reason (SD17);
- after a no, the reason stands on the key for three seconds (SD18), and on the info line;
- without an answer from the interlocking every key says Ingen kontakt (SD21);
- when TKL is locked, the deck shows only the clock (SD30).

The modes and their pages are the profile's (tkl.deck.profile). Tågen needs Hubben (SD11,
SD63): without it the mode is not shown, and the deck opens on Platser. Läge chooses the mode,
and holding it shows every page (SD26, SD64); on Mini holding ▶ opens the page Läge (SD78).

Decks at the same workplace share the chosen start (SD36): the start is a `Selection` that the
caller keeps per workplace and gives to every deck there.

The owner's profile (#86 del c, SD40, SD43) may give a key its own text and line under, what a
press and a hold do from the fixed list, whether a snabbväg shows the train number and dims when
hindered, and whether it asks once more before a press. A pedal does only what the owner chose
for it (SD55). Blinka lights a deck so that the owner sees which one it is (SD46).

Pure Python without I/O: the interlocking is read, and changed only through Hands. No code here
names a station (RS13).
"""

from __future__ import annotations

import math
import time as clock_time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, Literal, Protocol

from contracts import station
from contracts.tkl import (
    DeckAction,
    DeckDial,
    DeckHold,
    DeckKeyType,
    DeckMode,
    DeckPageKind,
    DeckPan,
    DeckPlacesShown,
    DeckPlanDrawn,
    DeckStyle,
    RouteKind,
    TklDeckFace,
    TklDeckKey,
    TklDeckPage,
    TklDeckPart,
    TklDeckPlace,
    TklDeckProfile,
    TklDeckRoute,
    TklDeckSettings,
    TklDeckStrip,
    TklDeckTile,
    TklDeckView,
    TklInterlocking,
    TklNumberColour,
    TklTarget,
    TklTargets,
)
from tkl.deck import look
from tkl.deck.places import Geography
from tkl.deck.profile import cut_size
from tkl.deck.trains import Case, Daily, Line, Step, Turn, cases, daily, lines, turns
from tkl.stallverk import Interlocking, Plant, UnknownStart

K = DeckKeyType
HOLD_MS: Final = {DeckHold.SHORT: 400, DeckHold.NORMAL: 600, DeckHold.LONG: 1000}
"""How long a hold is (SD29): Normal is 0.6 seconds."""
FLASH_SECONDS: Final = 3.0
"""The reason stands on the key this long after a no (SD18)."""
BLINK_SECONDS: Final = 3.0
"""Blinka in Studio lights the deck this long (SD46)."""
ASK_SECONDS: Final = 3.0
"""A key that asks once more waits this long for the second press."""
HOLD_ONLY: Final = frozenset({DeckAction.RELEASE_ALL, DeckAction.RESET, DeckAction.EMERGENCY})
"""Done with a hold, never a press (SD29)."""
MODE_NAMES: Final = {
    DeckMode.TRAINS: ("Tågen", "ett tåg per knapp"),
    DeckMode.PLACES: ("Platser", "från och till i klartext"),
    DeckMode.TRACK_PLAN: ("Spårplan", "signaler och växlar"),
}
KIND_WORD: Final = {RouteKind.TRAIN: "tåg", RouteKind.SHUNTING: "växling"}
FAMILIES: Final = {
    DeckPageKind.NOW: "trains",
    DeckPageKind.DAILY: "trains",
    DeckPageKind.PLACES: "places",
    DeckPageKind.PARTS: "places",
    DeckPageKind.FAVOURITES: "favourites",
    DeckPageKind.SIGNALS: "signals",
    DeckPageKind.ALL: "signals",
    DeckPageKind.WHOLE: "plan",
    DeckPageKind.CUTOUT: "plan",
    DeckPageKind.OWN: "own",
}
"""The pages ▶ turns between on the bigger decks: those of the same kind."""
MOST_FAVOURITES: Final = 10
"""The most used routes on Favoriter, after the pinned ones (TKL70)."""


@dataclass(frozen=True)
class Said:
    """The interlocking's yes, or no with its reason."""

    accepted: bool
    message: str


class Hands(Protocol):
    """What the deck may do: the interlocking's functions, and TKL's clearance as it is."""

    def set_route(self, start: str, end: str, kind: RouteKind | None) -> Said: ...
    def release(self, route: int) -> Said: ...
    def step(self, route: int) -> Said: ...
    def arrive(self, route: int) -> Said: ...
    def function(self, name: str, on: bool) -> Said: ...
    def command(
        self,
        action: station.Action,
        payload: dict[str, object],
        revision: station.Revision | None,
    ) -> Said: ...
    def lock(self) -> Said:
        """Lås (Fika, SD30): TKL is locked for the whole station until the PIN opens it."""
        ...

    def reset(self) -> Said:
        """Noll, with a hold (SD29): the interlocking's own reset, confirmed by the hold."""
        ...

    def emergency(self, route: int) -> Said:
        """Nödutlösning of a route, with a hold (SD29): confirmed by the hold."""
        ...


@dataclass
class Selection:
    """The chosen start, shared by the decks at one workplace (SD36): a signal with its kind,
    or a place, with the train it is for and its planned track (SD20)."""

    point: str | None = None
    kind: RouteKind | None = None
    place: str | None = None
    train: str | None = None
    planned: str | None = None
    revision: int = 0

    def clear(self) -> None:
        self.point = self.kind = self.place = self.train = self.planned = None
        self.revision += 1

    @property
    def chosen(self) -> bool:
        return self.point is not None or self.place is not None


@dataclass(frozen=True)
class Overlay:
    """A page the logic makes over the profile's: Läge, every page, an alarm's case, the
    tracks for a train, or the other routes to a goal."""

    kind: Literal["modes", "pages", "case", "choose", "routes"]
    case: Case | None = None
    place: str | None = None


@dataclass
class Flash:
    until: float
    text: str
    reason: str
    page: int


@dataclass
class Deck:
    """One deck's state of the moment: its mode, page, overlay and what flashes."""

    settings: TklDeckSettings
    profile: TklDeckProfile
    mode: DeckMode | None = None
    page: int = 0
    overlay: Overlay | None = None
    sub: int = 0
    origin: tuple[int, int] = (0, 0)
    flash: dict[int, Flash] = field(default_factory=dict)
    dials: dict[int, int] = field(default_factory=dict)
    message: str | None = None
    accepted: bool | None = None
    said_at: float = 0.0
    revision: int = 0
    blink_until: float = 0.0
    """Blinka (SD46): the deck shows that it is this one until then."""
    asking: tuple[int, int, float] | None = None
    """A key that asks once more (SD43): its page, its cell and until when."""


@dataclass
class World:
    """What a deck reads: the profile's station, the interlocking (None when it does not
    answer), the hub's snapshot (None without Hubben), and the rest of the moment."""

    plant: Plant
    geo: Geography
    interlocking: Interlocking | None
    snapshot: station.Snapshot | None = None
    drift: bool = False
    """Connected to a real meet: Ankommit, never Kör (SD28)."""
    locked: bool = False
    time: str = ""
    station: str = ""
    favourites: list[TklDeckRoute] = field(default_factory=list)
    daily_kept: list[Daily] | None = None
    """Dagens vägar as TKL's runtime data keeps them (SD49); else made from the snapshot."""
    now: float = field(default_factory=clock_time.monotonic)
    _state: TklInterlocking | None = None
    _targets: dict[str, TklTargets | None] = field(default_factory=dict)
    _turns: list[Turn] | None = None
    _lines: list[Line] | None = None
    _cases: list[Case] | None = None
    _daily: list[Daily] | None = None

    @property
    def state(self) -> TklInterlocking:
        if self._state is None:
            assert self.interlocking is not None
            self._state = self.interlocking.view()
        return self._state

    def targets(self, start: str) -> TklTargets | None:
        """The interlocking's own check of every goal, without setting anything (SD17)."""
        if start not in self._targets:
            try:
                found = self.interlocking.targets(start) if self.interlocking else None
            except UnknownStart:
                found = None
            self._targets[start] = found
        return self._targets[start]

    @property
    def turns(self) -> list[Turn]:
        if self._turns is None:
            self._turns = turns(self.state, self.snapshot, self.plant, self.geo)
        return self._turns

    @property
    def lines(self) -> list[Line]:
        if self._lines is None:
            self._lines = lines(self.snapshot, self.plant, self.geo)
        return self._lines

    @property
    def cases(self) -> list[Case]:
        if self._cases is None:
            self._cases = cases(self.state, self.snapshot)
        return self._cases

    @property
    def daily(self) -> list[Daily]:
        if self._daily is None:
            kept = self.daily_kept
            self._daily = kept if kept is not None else daily(self.snapshot, self.plant, self.geo)
        return self._daily


@dataclass(frozen=True)
class Goal:
    """A goal place from a start place: the route a press would set, and whether it can."""

    place: str
    start: str
    end: str
    possible: bool
    reason: str | None
    pieces: int
    route: int | None


# --- what the modes and pages are now -----------------------------------------------------------


def modes(deck: Deck, world: World) -> list[DeckMode]:
    """The modes the deck has now: Tågen needs Hubben (SD11, SD63)."""
    return [m for m in deck.profile.modes if m != DeckMode.TRAINS or world.snapshot is not None]


def shown(page: TklDeckPage, world: World) -> bool:
    if page.kind in (DeckPageKind.NOW, DeckPageKind.DAILY):
        return world.snapshot is not None
    if page.kind == DeckPageKind.FAVOURITES:
        return bool(world.favourites)
    return True


def pages_of(deck: Deck, world: World, mode: DeckMode | None) -> list[int]:
    return [
        i
        for i, p in enumerate(deck.profile.pages)
        if p.mode == mode and p.listed and shown(p, world)
    ]


def every_page(deck: Deck, world: World) -> list[int]:
    return [i for m in modes(deck, world) for i in pages_of(deck, world, m)]


def open_deck(settings: TklDeckSettings, profile: TklDeckProfile, world: World) -> Deck:
    """A deck opens in its mode (SD65): Tågen with Hubben, else Platser on its first page
    (SD11, SD22)."""
    deck = Deck(settings=settings, profile=profile)
    have = modes(deck, world)
    start = _start_page(deck, world)
    if start is not None:
        # The page the deck opens on (SD35), when its mode is there now.
        deck.mode = profile.pages[start].mode
        deck.page = start
        return deck
    wanted = settings.opens_in
    mode = wanted if wanted in have else (have[0] if have else None)
    go_mode(deck, world, mode)
    return deck


def _start_page(deck: Deck, world: World) -> int | None:
    name = deck.settings.opens_on
    if not name:
        return None
    have = modes(deck, world)
    for i, page in enumerate(deck.profile.pages):
        wanted = deck.settings.opens_in in (None, page.mode) and page.mode in have
        if page.name == name and page.listed and wanted and shown(page, world):
            return i
    return None


def go_mode(deck: Deck, world: World, mode: DeckMode | None) -> None:
    deck.mode = mode
    found = pages_of(deck, world, mode)
    deck.page = found[0] if found else 0
    deck.overlay = None
    deck.sub = 0


def settle(deck: Deck, world: World) -> None:
    """After the world changed: a page that is no longer there gives way to the mode's first,
    and a mode that is gone to the first there is (Hubben came or went)."""
    have = modes(deck, world)
    if deck.mode not in have:
        wanted = deck.settings.opens_in
        go_mode(deck, world, wanted if wanted in have else (have[0] if have else None))
        return
    pages = deck.profile.pages
    if not pages:
        return
    page = pages[deck.page] if deck.page < len(pages) else None
    if page is None or page.mode != deck.mode or not shown(page, world):
        found = pages_of(deck, world, deck.mode)
        deck.page = found[0] if found else 0


def current(deck: Deck) -> TklDeckPage | None:
    pages = deck.profile.pages
    return pages[deck.page] if 0 <= deck.page < len(pages) else None


# --- places and their goals (SD66, SD67) ---------------------------------------------------------


def place_of(world: World, deck: Deck, place: str | None) -> TklDeckPlace | None:
    return next((p for p in deck.profile.places if p.id == place), None)


def goals(deck: Deck, world: World, start_place: str) -> dict[str, list[Goal]]:
    """The places a train route reaches from a place, each with the routes a press would
    try: those that can be set now first, then the shortest."""
    place = place_of(world, deck, start_place)
    found: dict[str, list[Goal]] = {}
    if place is None:
        return found
    for start in place.starts:
        targets = world.targets(start)
        if targets is None:
            continue
        for t in targets.targets:
            if t.kind != RouteKind.TRAIN:
                continue
            to = world.geo.end_place.get(t.end)
            if to is None or to == start_place:
                continue
            found.setdefault(to, []).append(
                Goal(to, start, t.end, t.possible, t.reason, len(t.pieces), t.route)
            )
    for to in found:
        found[to].sort(key=lambda g: (not g.possible, g.pieces, g.start, g.end))
    return found


def best(deck: Deck, world: World, origin: str, goal: str) -> Goal | None:
    found = goals(deck, world, origin).get(goal) or []
    return found[0] if found else None


def place_pieces(world: World, place: TklDeckPlace) -> set[str]:
    plant = world.plant
    if place.kind == "exit":
        model_id = next((m for m, p in world.geo.exit_place.items() if p == place.id), None)
        return set(plant.exits[model_id].pieces) if model_id in plant.exits else set()
    model_id = next((m for m, p in world.geo.track_place.items() if p == place.id), None)
    track = next((t for t in plant.model.station_tracks if t.id == model_id), None)
    return set(track.pieces) if track is not None else set()


def number_at(world: World, place: TklDeckPlace) -> tuple[str, Literal["green", "red", ""]]:
    """The train number on a place (SD19): red where a train stands, green where one is
    expected."""
    state = world.state
    if place.kind == "exit":
        model_id = next((m for m, p in world.geo.exit_place.items() if p == place.id), None)
        for train in state.trains:
            if train.exit is not None and train.exit == model_id:
                return train.number or "", "red"
        return "", ""
    pieces = place_pieces(world, place)
    standing = [
        n for n in state.numbers if n.colour == TklNumberColour.RED and set(n.pieces) & pieces
    ]
    if standing:
        return standing[0].number or "", "red"
    expected = [
        n for n in state.numbers if n.colour == TklNumberColour.GREEN and set(n.pieces) & pieces
    ]
    if expected:
        return expected[0].number or "", "green"
    return "", ""


# --- the faces --------------------------------------------------------------------------------


def view(deck: Deck, selection: Selection, world: World) -> TklDeckView:
    """Every key's face, the info line and the strip."""
    settle(deck, world)
    profile = deck.profile
    page = current(deck)
    faces = keys(deck, selection, world)
    flashing = [f.until for f in deck.flash.values() if f.until > world.now]
    if deck.blink_until > world.now:
        flashing.append(deck.blink_until)
    if deck.asking is not None and deck.asking[2] > world.now:
        flashing.append(deck.asking[2])
    said = ""
    if (
        deck.accepted is False
        and deck.message
        and not world.locked
        and world.now - deck.said_at < FLASH_SECONDS
    ):
        # The no on the strip for three seconds (SD18), where the deck has one.
        said = deck.message[:60]
        flashing.append(deck.said_at + FLASH_SECONDS)
    refresh = int(max(200, (min(flashing) - world.now) * 1000 + 50)) if flashing else 15000
    return TklDeckView(
        settings=deck.settings,
        revision=deck.revision,
        style=profile.style,
        modes=modes(deck, world),
        mode=deck.mode,
        page=page.name if page is not None else "",
        keys=faces,
        fixed=profile.fixed,
        info=info(deck, selection, world) if profile.grid.info else "",
        strip=strip(deck, selection, world) if profile.grid.strip or profile.grid.dials else [],
        hold_ms=HOLD_MS[deck.settings.hold],
        refresh_ms=refresh,
        locked=world.locked,
        contact=world.interlocking is not None,
        message=deck.message,
        accepted=deck.accepted,
        said=said if profile.grid.strip else "",
    )


def keys(deck: Deck, selection: Selection, world: World) -> list[TklDeckFace]:
    profile = deck.profile
    size = profile.grid.columns * profile.grid.rows
    if world.locked:
        # Locked: only the clock (SD30), where Larm och klocka is, else on the first key.
        faces = [look.EMPTY] * size
        page = current(deck)
        at = next(
            (
                i
                for i, k in enumerate(page.keys if page else [])
                if k is not None and k.type == K.ALARM
            ),
            0,
        )
        if size:
            faces[at] = look.clock(world.time, world.station)
        return faces
    if deck.blink_until > world.now:
        # Blinka (SD46): every key lit, so that the owner sees which deck this is.
        name = deck.settings.name or ""
        return [look.here(name) for _ in range(size)]
    if world.interlocking is None:
        return [look.no_contact() for _ in range(size)]
    if deck.overlay is not None:
        return _overlay(deck, selection, world)
    page = current(deck)
    if page is None:
        return [look.EMPTY] * size
    listing = _goal_list(deck, selection, world, page)
    if listing is not None:
        return listing
    faces = [face(deck, selection, world, page, k) for k in page.keys]
    if selection.chosen and page.cancel is not None and page.cancel < size:
        faces[page.cancel] = _cancel(selection, deck)
    asking = deck.asking
    if asking is not None and asking[2] > world.now and asking[0] == deck.page and asking[1] < size:
        faces[asking[1]] = look.asking(faces[asking[1]].text)
    for index, flash in deck.flash.items():
        if flash.until > world.now and flash.page == deck.page and index < size:
            faces[index] = look.refused(flash.text, flash.reason)
    return faces


def _cancel(selection: Selection, deck: Deck) -> TklDeckFace:
    under = selection.point or selection.place or ""
    if selection.train:
        under = f"{selection.train} från {under}"
    return TklDeckFace(
        type="action", text="Avbryt", under=under, bg="#1f1f1f", fg="#d4d4d4", label="Avbryt"
    )


def face(
    deck: Deck, selection: Selection, world: World, page: TklDeckPage, key: TklDeckKey | None
) -> TklDeckFace:
    found = _face(deck, selection, world, page, key)
    if key is None or found.type == "empty" or not (key.text or key.under):
        return found
    # The owner's text and line under (SD43); the colours and symbols stay the catalogue's.
    text = key.text or found.text
    update: dict[str, object] = {"text": text, "under": key.under or found.under}
    if key.text and found.label:
        update["label"] = found.label.replace(found.text, text, 1) if found.text else text
    return found.model_copy(update=update)


def _face(
    deck: Deck, selection: Selection, world: World, page: TklDeckPage, key: TklDeckKey | None
) -> TklDeckFace:
    if key is None:
        return look.EMPTY
    match key.type:
        case K.TRAIN:
            return _train_face(deck, world, _turn(world, key.slot))
        case K.LINE:
            return _line_face(_line(world, key.slot))
        case K.ALARM:
            return _alarm_face(world)
        case K.PLACE | K.TRACK:
            return _place_face(deck, selection, world, key)
        case K.PART:
            return _part_face(deck, selection, world, key)
        case K.SIGNAL:
            return _signal_face(selection, world, key.point or "")
        case K.DAILY:
            return _daily_face(deck, world, key.slot)
        case K.FAVOURITE:
            return _favourite_face(world, key.slot)
        case K.TILE:
            return _tile_face(deck, selection, world, key)
        case K.CELL:
            return _cell_face(deck, selection, world, page, key)
        case K.PAN:
            return _pan_face(key.pan)
        case K.MODE:
            return _mode_face(deck)
        case K.NEXT:
            return _next_face(deck, world, page)
        case K.PAGE:
            return _page_face(deck, world)
        case K.ACTION:
            return _action_face(deck, selection, world, key.action)
        case K.PANEL:
            return _panel_face(world, key.function or "")
        case K.ROUTE:
            return _quick_face(deck, world, key)
    return look.EMPTY


def _turn(world: World, slot: int | None) -> Turn | None:
    found = world.turns
    return found[slot - 1] if slot is not None and 0 < slot <= len(found) else None


def _line(world: World, slot: int | None) -> Line | None:
    found = world.lines
    return found[slot - 1] if slot is not None and 0 < slot <= len(found) else None


def _place_name(deck: Deck, place: str | None) -> str:
    found = next((p for p in deck.profile.places if p.id == place), None)
    return found.name if found is not None else (place or "")


def _way(turn: Turn, deck: Deck, entry: bool) -> str:
    """Where the train goes: from its exit to its track, or from its track out."""
    a, b = (turn.origin, turn.track) if entry else (turn.track, turn.goal)
    return f"{_place_name(deck, a) or '?'} \N{RIGHTWARDS ARROW} {_place_name(deck, b) or '?'}"


def _train_face(d: Deck, world: World, turn: Turn | None) -> TklDeckFace:
    """The train key (SD7): the way at the top, the number, and the next step under; a train
    that is ready to send has the green mark (SD62)."""
    if turn is None:
        return look.EMPTY
    face = _train_step_face(d, world, turn)
    if not turn.ready:
        return face
    return face.model_copy(update={"ready": True, "label": f"{face.label}, klart att skicka"})


def _train_step_face(d: Deck, world: World, turn: Turn) -> TklDeckFace:
    label = f"Tåg {turn.number}"
    on = f"på {_place_name(d, turn.track)}" if turn.track else "på stationen"
    match turn.step:
        case Step.WAITING:
            return TklDeckFace(
                type="train",
                top=_way(turn, d, True),
                text=turn.number,
                under=turn.time or "väntas",
                bg="#1b1f24",
                fg="#e5e7eb",
                frame="#3a424a",
                label=f"{label}, väntas",
            )
        case Step.COMING:
            hindered = _entry_hindrance(d, world, turn)
            if hindered is not None:
                return TklDeckFace(
                    type="train",
                    top=_way(turn, d, True),
                    text=turn.number,
                    under=look.short(hindered),
                    bg="#191d21",
                    fg="#98a2ad",
                    frame="#5c4a12",
                    dot=look.DOT,
                    label=f"{label}: {hindered}",
                )
            at_signal = turn.train is not None
            return TklDeckFace(
                type="train",
                top=_way(turn, d, True),
                text=turn.number,
                under="väntar · lägg infart" if at_signal else "lägg infart",
                bg="#1d1a0b",
                fg="#fde68a",
                frame="#f5c518",
                blink="#3d3208" if at_signal else None,
                label=f"{label}, lägg infart",
            )
        case Step.ENTRY:
            return TklDeckFace(
                type="train",
                top=_way(turn, d, True),
                text=turn.number,
                under="infart lagd",
                bg=look.GREEN,
                fg="#ffffff",
                band=look.GREEN_BAND,
                label=f"{label}, infart lagd",
            )
        case Step.RUNNING:
            return TklDeckFace(
                type="train",
                top=on,
                text=turn.number,
                under="kör",
                bg="#14181d",
                fg="#e5e7eb",
                frame="#22c55e",
                label=f"{label} kör",
            )
        case Step.ARRIVE:
            return TklDeckFace(
                type="train",
                top=on,
                text=turn.number,
                under="ankommit?",
                bg="#2a1416",
                fg="#ffb4ab",
                frame=look.DOT,
                label=f"{label}, ankommit?",
            )
        case Step.IN:
            ask = turn.call is not None and turn.section is not None
            return TklDeckFace(
                type="train",
                top=on,
                text=turn.number,
                under="begär klart" if ask else "lägg utfart",
                bg="#2a1416",
                fg="#ffb4ab",
                frame=look.DOT,
                label=f"{label}, {'begär klart' if ask else 'lägg utfart'}",
            )
        case Step.ASKED:
            return TklDeckFace(
                type="train",
                top=on,
                text=turn.number,
                under="väntar på klart",
                bg="#2a1416",
                fg="#ffb4ab",
                frame="#5c4a12",
                label=f"{label}, väntar på klart",
            )
        case Step.CLEARED:
            return TklDeckFace(
                type="train",
                top=_way(turn, d, False),
                text=turn.number,
                under="klart · lägg ut" if turn.clearance else "lägg utfart",
                bg="#0f2a1a",
                fg="#bbf7d0",
                frame=look.LIGHT_BLUE,
                dashed=True,
                blink="#14532d" if turn.clearance else None,
                label=f"{label}, lägg utfart",
            )
        case Step.EXIT:
            return TklDeckFace(
                type="train",
                top=_way(turn, d, False),
                text=turn.number,
                under="utfart lagd" if world.drift else "utfart lagd · kör",
                bg=look.GREEN,
                fg="#ffffff",
                band=look.GREEN_BAND,
                label=f"{label}, utfart lagd",
            )
    return TklDeckFace(
        type="train",
        top=f"mot {_place_name(d, turn.goal)}" if turn.goal else "",
        text=turn.number,
        under="har lämnat",
        bg="#101316",
        fg="#8b95a1",
        dim=True,
        label=f"{label} har lämnat",
    )


def _entry_hindrance(deck: Deck, world: World, turn: Turn) -> str | None:
    """Why the train's entry cannot be set now (SD17), or None."""
    if turn.origin is None or turn.track is None:
        return None
    found = best(deck, world, turn.origin, turn.track)
    if found is None:
        return "ingen väg"
    return None if found.possible else found.reason


def _line_face(line: Line | None) -> TklDeckFace:
    """The line key (SD13): the line from Drift, and the neighbour's question blinking."""
    if line is None:
        return look.EMPTY
    base = TklDeckFace(
        type="line", top="linje", text=line.code, bg="#0f1a2b", fg="#bfdbfe", frame="#1e3a5f"
    )
    if line.asks is not None:
        return base.model_copy(
            update={
                "under": f"frågar: {line.asks.train_number}",
                "frame": look.LIGHT_BLUE,
                "dashed": True,
                "blink": "#1e3a5f",
                "label": f"Linje {line.code}: frågar om tåg {line.asks.train_number}",
            }
        )
    if line.asked is not None:
        return base.model_copy(
            update={
                "under": f"begärt för {line.asked.train_number}",
                "frame": look.LIGHT_BLUE,
                "label": f"Linje {line.code}: begärt för {line.asked.train_number}",
            }
        )
    if line.coming is not None:
        return base.model_copy(
            update={
                "under": f"{line.coming} på väg hit",
                "frame": "#f5c518",
                "label": f"Linje {line.code}: {line.coming} på väg hit",
            }
        )
    if line.left is not None:
        return base.model_copy(
            update={"under": f"{line.left} har lämnat", "label": f"Linje {line.code}"}
        )
    said = "belagd" if line.section.occupied else "fri"
    return base.model_copy(update={"under": said, "label": f"Linje {line.code}: {said}"})


def _alarm_face(world: World) -> TklDeckFace:
    """The alarm key (SD15): the clock at rest, else what waits, the oldest first."""
    found = world.cases
    if not found:
        return look.clock(world.time, world.station)
    first = found[0]
    more = f" +{len(found) - 1}" if len(found) > 1 else ""
    if first.kind == "clearance":
        return TklDeckFace(
            type="alarm",
            top=first.top,
            text=first.text,
            under=first.under + more,
            bg="#0f1a2b",
            fg="#ffffff",
            frame=look.LIGHT_BLUE,
            dashed=True,
            blink="#1e3a5f",
            label=f"Larm: {first.text} {first.under}",
        )
    return TklDeckFace(
        type="alarm",
        top=first.top,
        text=first.text,
        under=look.short(first.under) + more,
        bg="#1f2937",
        fg="#ffffff",
        frame="#f3f4f6",
        dashed=True,
        label=f"Larm: {first.under}",
    )


def _place_face(deck: Deck, selection: Selection, world: World, key: TklDeckKey) -> TklDeckFace:
    """A place (SD66): its name, its train number (SD19), and free, occupied or in a set
    route. With a start chosen: the start, the goals to press, and the hindered ones dimmed
    with the reason (SD17); in Bara valbara the rest is dark (SD68)."""
    place = place_of(world, deck, key.place)
    if place is None:
        return look.EMPTY
    number, colour = number_at(world, place)
    pieces = place_pieces(world, place)
    state = world.state
    kinds = {(state.pieces[p].state.value if p in state.pieces else "free") for p in pieces}
    if "occupied" in kinds or colour == "red":
        bar = look.BAR_OCCUPIED
    elif "train" in kinds:
        bar = look.BAR_TRAIN
    elif "shunting" in kinds:
        bar = look.BAR_SHUNT
    else:
        bar = look.BAR_FREE
    coming = ""
    if place.kind == "exit" and world.snapshot is not None and not number:
        for turn in world.turns:
            if turn.step == Step.COMING and turn.origin == place.id:
                coming = f"{turn.number} väntas"
                break
    small = " · ".join(place.signals) if deck.settings.signal_numbers else ""
    base = TklDeckFace(
        type="track" if key.type == K.TRACK else "place",
        text=place.name,
        chip=number,
        chip_colour=colour,
        under=coming,
        small=small,
        bg=look.PLACE_BG,
        fg=look.PLACE_FG,
        bar=bar,
        label=f"Plats {place.name}",
    )
    if key.type == K.TRACK and not selection.chosen:
        out = bool(number) and colour == "red"
        return base.model_copy(
            update={
                "under": (f"tåg {number} · ut" if out else "ledigt · in"),
                "label": f"Spår {place.name}: {'ut' if out else 'in'}",
            }
        )
    if selection.place is None:
        return base
    if selection.place == place.id:
        return base.model_copy(
            update={"frame": look.LIGHT_BLUE, "under": "start", "label": f"Start {place.name}"}
        )
    found = goals(deck, world, selection.place).get(place.id)
    if not found:
        if deck.settings.places_shown == DeckPlacesShown.CHOOSABLE:
            return look.EMPTY
        return base.model_copy(
            update={"fg": look.DIM_FG, "bar": "#2a2f35", "dim": True, "under": coming}
        )
    first = found[0]
    star = selection.planned == place.id
    if not first.possible:
        if deck.settings.places_shown == DeckPlacesShown.CHOOSABLE:
            return look.EMPTY
        return base.model_copy(
            update={
                "fg": "#8b95a1",
                "under": look.short(first.reason),
                "dot": look.DOT,
                "dim": True,
                "star": star,
                "bar": "#7f1d1d",
                "label": f"Mål {place.name}: {first.reason}",
            }
        )
    return base.model_copy(
        update={
            "type": "goal",
            "bg": look.CHOSEN_BG,
            "frame": look.LIGHT_BLUE,
            "under": "planerat" if star else "Lägg hit",
            "bar": "#facc15",
            "bar_dashed": True,
            "star": star,
            "label": f"Mål {place.name}",
        }
    )


def _part_face(deck: Deck, selection: Selection, world: World, key: TklDeckKey) -> TklDeckFace:
    """A part of the station (SD79): with a start chosen, how many goals it has, and why
    when they are all hindered."""
    parts = deck.profile.parts
    part = parts[key.part] if key.part is not None and key.part < len(parts) else None
    if part is None:
        return look.EMPTY
    base = TklDeckFace(
        type="part",
        text=key.text or part.name,
        under=part.said,
        bg="#1f2328",
        fg="#f3f4f6",
        label=f"Del {part.name}",
    )
    if selection.place is None:
        return base
    if selection.place in part.places:
        return base.model_copy(
            update={
                "under": f"start {_place_name(deck, selection.place)}",
                "frame": look.LIGHT_BLUE,
            }
        )
    found = goals(deck, world, selection.place)
    mine = [found[p][0] for p in part.places if p in found]
    if not mine:
        return base.model_copy(update={"fg": look.DIM_FG, "dim": True, "under": "inga mål"})
    hindered = [g for g in mine if not g.possible]
    small = f"{_place_name(deck, hindered[0].place)} hindrad" if hindered else ""
    if len(hindered) == len(mine):
        small = look.short(hindered[0].reason)
    return base.model_copy(
        update={
            "under": f"{len(mine)} mål",
            "small": small,
            "bg": look.CHOSEN_BG,
            "frame": look.LIGHT_BLUE,
            "label": f"Del {part.name}: {len(mine)} mål",
        }
    )


def _targets_of(world: World, selection: Selection) -> dict[str, TklTarget]:
    if selection.point is None:
        return {}
    found = world.targets(selection.point)
    if found is None:
        return {}
    return {t.end: t for t in found.targets if t.kind == (selection.kind or RouteKind.TRAIN)}


def _signal_face(selection: Selection, world: World, point: str) -> TklDeckFace:
    """A signal key (SD25, SD73): the station's own number; a start, then a goal."""
    state = world.state
    starts = world.targets(point)
    can = bool(starts and starts.kinds)
    if selection.point is not None:
        if point == selection.point:
            shunting = selection.kind == RouteKind.SHUNTING
            return TklDeckFace(
                type="signal",
                text=point,
                under="växling" if shunting else "tåg",
                bg=look.YELLOW if shunting else look.BLUE,
                fg="#ffffff",
                label=f"Start {point}",
            )
        target = _targets_of(world, selection).get(point)
        if target is not None:
            if not target.possible:
                return TklDeckFace(
                    type="goal",
                    text=point,
                    under=look.short(target.reason),
                    bg="#191d21",
                    fg="#98a2ad",
                    dot=look.DOT,
                    dim=True,
                    label=f"Mål {point}: {target.reason}",
                )
            return TklDeckFace(
                type="goal",
                text=point,
                under="mål",
                bg=look.GOAL_BG,
                fg=look.GOAL_FG,
                frame=look.GOAL_FRAME,
                label=f"Mål {point}",
            )
        return TklDeckFace(type="signal", text=point, bg="#121417", fg=look.DIM_FG, label=point)
    if not can:
        return TklDeckFace(
            type="signal", text=point, under="bara mål", bg="#16191c", fg="#6b7280", label=point
        )
    laid = any(r.start == point for r in state.routes)
    return TklDeckFace(
        type="signal",
        text=point,
        bg="#166534" if laid else "#2b2f33",
        fg="#f3f4f6",
        label=f"Signal {point}",
    )


def _route_face(
    world: World,
    start: str,
    end: str,
    kind: RouteKind,
    text: str,
    under: str,
    typ: Literal["daily", "favourite", "route"],
    dim: bool = True,
) -> TklDeckFace:
    """A one-press route, as the prototype's snabbväg: green or yellow when set, dimmed with
    the reason when it cannot be set now (SD17), or only marked when the owner chose so."""
    shunting = kind == RouteKind.SHUNTING
    laid = next((r for r in world.state.routes if r.start == start and r.end == end), None)
    if laid is not None:
        return TklDeckFace(
            type=typ,
            text=text,
            under="kör" if laid.at >= 0 else "lagd",
            bg=look.YELLOW if shunting else look.GREEN,
            fg="#ffffff",
            band=look.YELLOW_BAND if shunting else look.GREEN_BAND,
            label=f"{text} lagd",
        )
    targets = world.targets(start)
    target = next(
        (t for t in (targets.targets if targets else []) if t.end == end and t.kind == kind), None
    )
    if target is None or not target.possible:
        reason = target.reason if target is not None else "Vägen finns inte."
        return TklDeckFace(
            type=typ,
            text=text,
            under=look.short(reason),
            bg="#191d21" if dim else "#262b31",
            fg="#98a2ad" if dim else "#e5e7eb",
            band="#3a424a" if dim else ("#eab308" if shunting else "#22c55e"),
            dot=look.DOT,
            dim=dim,
            label=f"{text}: {reason}",
        )
    return TklDeckFace(
        type=typ,
        text=text,
        under=under or KIND_WORD[kind],
        bg="#262b31",
        fg="#e5e7eb",
        band="#eab308" if shunting else "#22c55e",
        label=text,
    )


def _daily_face(deck: Deck, world: World, slot: int | None) -> TklDeckFace:
    """Dagens vägar (SD23): the entry and the exit of a train on its planned track."""
    found = world.daily
    if slot is None or not 0 < slot <= len(found):
        return look.EMPTY
    route = found[slot - 1]
    goal = best(deck, world, route.origin, route.goal)
    text = f"{_place_name(deck, route.origin)}\N{RIGHTWARDS ARROW}{_place_name(deck, route.goal)}"
    under = f"{route.number} · {route.time}" if route.time else route.number
    if goal is None:
        return TklDeckFace(
            type="daily", text=text, under="ingen väg", bg="#191d21", fg="#98a2ad", dim=True
        )
    return _route_face(world, goal.start, goal.end, RouteKind.TRAIN, text, under, "daily")


def _favourite_face(world: World, slot: int | None) -> TklDeckFace:
    found = world.favourites
    if slot is None or not 0 < slot <= len(found):
        return look.EMPTY
    route = found[slot - 1]
    text = f"{route.start}\N{RIGHTWARDS ARROW}{route.end}"
    return _route_face(world, route.start, route.end, route.kind, text, "", "favourite")


def _quick_face(deck: Deck, world: World, key: TklDeckKey) -> TklDeckFace:
    """Snabbväg (SD42): the whole route with one press, with the train number on its goal when
    the owner wants it (SD19, SD43)."""
    route = key.route
    if route is None:
        return look.EMPTY
    text = f"{route.start}\N{RIGHTWARDS ARROW}{route.end}"
    found = _route_face(
        world, route.start, route.end, route.kind, text, "", "route", key.dim is not False
    )
    if key.number is False:
        return found
    place = place_of(world, deck, world.geo.end_place.get(route.end))
    if place is None:
        return found
    number, colour = number_at(world, place)
    if not number:
        return found
    return found.model_copy(update={"chip": number, "chip_colour": colour})


def _cut(deck: Deck) -> tuple[int, int]:
    page = next((p for p in deck.profile.pages if p.kind == DeckPageKind.CUTOUT), None)
    return cut_size(page) if page is not None else (0, 0)


def _lit(world: World, selection: Selection) -> tuple[str | None, list[str]]:
    if selection.point is None:
        return None, []
    return selection.point, [
        t for t, found in _targets_of(world, selection).items() if found.possible
    ]


def _tile_face(deck: Deck, selection: Selection, world: World, key: TklDeckKey) -> TklDeckFace:
    """Hela stationen (SD70): a piece of the track plan, with the names of its tracks."""
    x, y, w, h = key.rect or (0.0, 0.0, 0.0, 0.0)
    start, lit = _lit(world, selection)
    return TklDeckFace(
        type="tile",
        bg="#000000",
        fg="#f3f4f6",
        tile=TklDeckTile(
            x=x,
            y=y,
            w=w,
            h=h,
            drawn=deck.settings.plan_drawn,
            start=start,
            goals=lit,
            names=key.text.split() if key.text else [],
        ),
        label=f"Spårplanen: {key.text}" if key.text else "Spårplanen",
    )


def _cell_rect(deck: Deck, key: TklDeckKey) -> tuple[float, float, float, float]:
    tile = deck.profile.tile
    bx, by = deck.profile.tile_origin
    ox, oy = deck.origin
    return (bx + (ox + (key.dx or 0)) * tile, by + (oy + (key.dy or 0)) * tile, tile, tile)


def _points_in(deck: Deck, rect: tuple[float, float, float, float]) -> list[str]:
    x, y, w, h = rect
    return [p.name for p in deck.profile.points if x <= p.x < x + w and y <= p.y < y + h]


def _cell_face(
    deck: Deck, selection: Selection, world: World, page: TklDeckPage, key: TklDeckKey
) -> TklDeckFace:
    """The cut-out (SD71): a square of the track plan, with the signals where they stand."""
    x, y, w, h = _cell_rect(deck, key)
    start, lit = _lit(world, selection)
    inside = _points_in(deck, (x, y, w, h))
    chosen = start in inside or any(g in inside for g in lit)
    return TklDeckFace(
        type="cell",
        bg="#000000",
        fg="#f3f4f6",
        frame=look.LIGHT_BLUE if chosen else None,
        tile=TklDeckTile(
            x=x,
            y=y,
            w=w,
            h=h,
            drawn=deck.settings.plan_drawn,
            start=start if start in inside else None,
            goals=[g for g in lit if g in inside],
            names=inside,
            chosen=chosen,
        ),
        label=f"Ruta {', '.join(inside)}" if inside else "Ruta",
    )


PAN_FACES: Final = {
    DeckPan.WHOLE: ("\N{SINGLE LEFT-POINTING ANGLE QUOTATION MARK} Hela", "Hela stationen"),
    DeckPan.WEST: ("\N{BLACK LEFT-POINTING TRIANGLE}", "Väster"),
    DeckPan.EAST: ("\N{BLACK RIGHT-POINTING TRIANGLE}", "Öster"),
    DeckPan.UP: ("\N{BLACK UP-POINTING TRIANGLE}", "Uppåt"),
    DeckPan.DOWN: ("\N{BLACK DOWN-POINTING TRIANGLE}", "Nedåt"),
}


def _pan_face(pan: DeckPan | None) -> TklDeckFace:
    if pan is None:
        return look.EMPTY
    text, label = PAN_FACES[pan]
    return TklDeckFace(type="pan", text=text, bg="#1e293b", fg="#cbd5e1", label=label)


def _mode_face(deck: Deck) -> TklDeckFace:
    """Läge (SD64): the mode's name."""
    name = MODE_NAMES[deck.mode][0] if deck.mode is not None else ""
    open_ = deck.overlay is not None and deck.overlay.kind == "modes"
    return TklDeckFace(
        type="mode",
        top="Läge",
        text=name,
        bg=look.CHOSEN_BG if open_ else "#1d2125",
        fg="#ffffff",
        frame=look.LIGHT_BLUE if open_ else None,
        label=f"Läge {name}",
    )


def _next_page(deck: Deck, world: World) -> int | None:
    page = current(deck)
    found = pages_of(deck, world, deck.mode)
    if page is not None and not page.listed:
        # A part's page: the next page of the same part, else back to the parts.
        following = deck.page + 1
        pages = deck.profile.pages
        if (
            following < len(pages)
            and pages[following].part == page.part
            and not pages[following].listed
        ):
            return following
        return next((i for i in found if pages[i].kind == DeckPageKind.PARTS), None)
    if page is not None and deck.profile.style != DeckStyle.NEXT:
        # ▶ in the fixed row turns the pages of the same kind: the halves of Platser (SD80),
        # Nu and Dagens vägar, the signal pages. Every page is a hold on Läge away (SD26).
        family = FAMILIES.get(page.kind, page.kind.value)
        found = [i for i in found if FAMILIES.get(deck.profile.pages[i].kind) == family]
    if len(found) < 2:
        return None
    if deck.page not in found:
        return found[0]
    return found[(found.index(deck.page) + 1) % len(found)]


def _next_face(deck: Deck, world: World, page: TklDeckPage) -> TklDeckFace:
    """▶ on Mini: the next page, its name under; hold opens Läge (SD78)."""
    following = _next_page(deck, world)
    name = deck.profile.pages[following].name if following is not None else ""
    return TklDeckFace(
        type="next",
        text="\N{BLACK RIGHT-POINTING TRIANGLE}",
        under=name or "håll in: Läge",
        bg="#1e293b",
        fg="#cbd5e1",
        label=f"Nästa sida {name}".strip(),
    )


def _page_face(deck: Deck, world: World) -> TklDeckFace:
    """▶ in the fixed row: the next page of the mode (SD80)."""
    following = _next_page(deck, world)
    if following is None or following == deck.page:
        return TklDeckFace(type="page", bg="#14181d", fg="#14181d", dim=True)
    name = deck.profile.pages[following].name
    return TklDeckFace(
        type="page",
        text="\N{BLACK RIGHT-POINTING TRIANGLE}",
        under=name,
        bg="#1d2125",
        fg="#cbd5e1",
        label=f"Nästa sida {name}",
    )


def _arrivable(world: World) -> tuple[int, str] | None:
    """The route whose train stands at its end: Ankommit's (SD10)."""
    state = world.state
    for route in state.routes:
        if route.train is not None and route.at == len(route.sections) - 1 and route.leaves is None:
            train = next((t for t in state.trains if t.id == route.train), None)
            return route.id, (train.number or "") if train else ""
    return None


def _runnable(world: World) -> int | None:
    """The latest route with a train: Kör's (SD28)."""
    found = [r for r in world.state.routes if r.train is not None]
    return found[-1].id if found else None


def _action_face(
    deck: Deck, selection: Selection, world: World, action: DeckAction | None
) -> TklDeckFace:
    state = world.state
    match action:
        case DeckAction.RELEASE:
            return TklDeckFace(
                type="action",
                text="Lös ut",
                under="håll: alla",
                bg="#3f2a0b",
                fg="#fde68a",
                dim=not state.routes,
                label="Lös ut",
            )
        case DeckAction.ARRIVED if not world.drift:
            # Kör only in Prova and the reference stations (SD28): outside a real meet.
            return TklDeckFace(
                type="action",
                text="Kör",
                under="senaste",
                bg="#052e16",
                fg="#86efac",
                dim=_runnable(world) is None,
                label="Kör",
            )
        case DeckAction.ARRIVED:
            found = _arrivable(world)
            return TklDeckFace(
                type="action",
                text="Ankommit",
                under=found[1] if found else "",
                bg="#052e16",
                fg="#86efac",
                dim=found is None,
                label="Ankommit",
            )
        case DeckAction.RUN:
            return TklDeckFace(
                type="action", text="Kör", under="senaste", bg="#052e16", fg="#86efac", label="Kör"
            )
        case DeckAction.CANCEL:
            if selection.chosen:
                return _cancel(selection, deck)
            return TklDeckFace(
                type="action", text="Avbryt", bg="#1f1f1f", fg="#4b5563", dim=True, label="Avbryt"
            )
        case DeckAction.BACK:
            return TklDeckFace(
                type="action", text="Tillbaka", bg="#1f1f1f", fg="#d4d4d4", label="Tillbaka"
            )
        case DeckAction.LOCK:
            return look.LOCK
    return look.EMPTY


def _panel_face(world: World, name: str) -> TklDeckFace:
    found = next((f for f in world.state.functions if f.name == name), None)
    if found is None:
        return look.EMPTY
    return TklDeckFace(
        type="panel",
        text=name,
        under="på" if found.on else "av",
        bg="#9a3412" if found.on else "#292524",
        fg="#fed7aa",
        label=f"{name} {'på' if found.on else 'av'}",
    )


def _goal_list(
    deck: Deck, selection: Selection, world: World, page: TklDeckPage
) -> list[TklDeckFace] | None:
    """A signal start whose goals are not all on the page: the start and its goals as a list
    (the prototype's rule 5), a page of them at a time with ▶ for more."""
    if selection.point is None or page.kind not in (DeckPageKind.SIGNALS, DeckPageKind.ALL):
        return None
    on_page = {k.point for k in page.keys if k is not None and k.type == K.SIGNAL}
    targets = _targets_of(world, selection)
    if selection.point in on_page and all(t in on_page for t in targets):
        return None
    size = deck.profile.grid.columns * deck.profile.grid.rows
    room = max(1, size - 2)
    listed = [selection.point, *targets]
    count = max(1, math.ceil(len(listed) / room))
    deck.sub %= count
    piece = listed[deck.sub * room : deck.sub * room + room]
    faces = [_signal_face(selection, world, p) for p in piece]
    faces += [look.EMPTY] * (size - 2 - len(faces))
    more = TklDeckFace(
        type="next",
        text="\N{BLACK RIGHT-POINTING TRIANGLE}",
        under="fler mål" if count > 1 else "",
        bg="#1e293b",
        fg="#cbd5e1",
        dim=count < 2,
        label="Fler mål",
    )
    return [*faces, more, _cancel(selection, deck)][:size]


# --- the overlays -----------------------------------------------------------------------------


def _overlay(deck: Deck, selection: Selection, world: World) -> list[TklDeckFace]:
    profile = deck.profile
    size = profile.grid.columns * profile.grid.rows
    overlay = deck.overlay
    assert overlay is not None
    back = TklDeckFace(type="action", text="Tillbaka", bg="#1f1f1f", fg="#d4d4d4", label="Tillbaka")
    faces = [look.EMPTY] * size
    if overlay.kind == "modes":
        for i, m in enumerate(modes(deck, world)[: size - 1]):
            name, said = MODE_NAMES[m]
            on = m == deck.mode
            faces[i] = TklDeckFace(
                type="mode",
                text=name,
                under=said,
                bg=look.CHOSEN_BG if on else "#1f2328",
                fg="#ffffff",
                frame=look.LIGHT_BLUE if on else None,
                label=f"Byt läge till {name}",
            )
            below = i + profile.grid.columns
            variant = _variant_face(deck, m)
            if variant is not None and profile.style != DeckStyle.NEXT and below < size:
                faces[below] = variant
        if profile.style == DeckStyle.NEXT:
            faces[size - 2] = TklDeckFace(
                type="page", text="Sidor", bg="#1f2328", fg="#ffffff", label="Sidor"
            )
            faces[size - 1] = back
        else:
            here = current(deck)
            mode_at = next(
                (i for i, k in enumerate(here.keys if here else []) if k and k.type == K.MODE),
                size - 1,
            )
            faces[mode_at] = _mode_face(deck)
        # Lås (SD30) on the last free key of the page Läge: the default pages stay as they are.
        free = [i for i, f in enumerate(faces) if f.type == "empty"]
        if free and deck.settings.lock_key:
            faces[free[-1]] = look.LOCK
        return faces
    if overlay.kind == "pages":
        listed = every_page(deck, world)
        room = size - 1
        count = max(1, math.ceil(len(listed) / room))
        deck.sub %= count
        shown_pages = listed[deck.sub * room : deck.sub * room + room]
        for i, p in enumerate(shown_pages):
            page = profile.pages[p]
            faces[i] = look.tab(page.name, MODE_NAMES[page.mode][0], p == deck.page)
        if count > 1 and len(shown_pages) == room:
            faces[room - 1] = TklDeckFace(
                type="next",
                text="\N{BLACK RIGHT-POINTING TRIANGLE}",
                under="fler sidor",
                bg="#1e293b",
                fg="#cbd5e1",
                label="Fler sidor",
            )
        faces[size - 1] = back
        return faces
    if overlay.kind == "case" and overlay.case is not None:
        case = overlay.case
        faces[0] = TklDeckFace(
            type="case",
            top=case.top,
            text=case.text,
            under=look.short(case.under) if case.kind == "fault" else case.under,
            bg="#0f1a2b" if case.kind == "clearance" else "#1f2937",
            fg="#ffffff",
            frame=look.LIGHT_BLUE,
            label=f"{case.top}: {case.text} {case.under}",
        )
        if case.kind == "clearance" and size >= 4:
            faces[1] = TklDeckFace(
                type="answer",
                text="Klart",
                bg=look.GREEN,
                fg="#ffffff",
                band=look.GREEN_BAND,
                label="Klart",
            )
            faces[2] = TklDeckFace(
                type="answer", text="Nej", bg=look.RED, fg="#ffffff", label="Nej"
            )
        faces[size - 1] = back
        return faces
    if overlay.kind in ("choose", "routes"):
        return _choices(deck, selection, world, overlay, size, back)
    return faces


def _variant_face(deck: Deck, mode: DeckMode) -> TklDeckFace | None:
    """Each mode's variant under it (SD64): Platser visar Alla or Valbara (SD68), Spårplan
    ritas som 85 or Relä (SD72)."""
    if mode == DeckMode.PLACES:
        value = "Alla" if deck.settings.places_shown == DeckPlacesShown.ALL else "Valbara"
        return TklDeckFace(
            type="variant",
            top="Platser visar",
            text=value,
            bg="#1f2328",
            fg="#ffffff",
            label=f"Platser visar {value}",
        )
    if mode == DeckMode.TRACK_PLAN:
        value = "85" if deck.settings.plan_drawn == DeckPlanDrawn.STANDARD_85 else "Relä"
        return TklDeckFace(
            type="variant",
            top="Ritas som",
            text=value,
            bg="#1f2328",
            fg="#ffffff",
            label=f"Ritas som {value}",
        )
    return None


def _choice_list(deck: Deck, selection: Selection, world: World, overlay: Overlay) -> list[Goal]:
    if overlay.kind == "routes" and selection.place is not None and overlay.place is not None:
        return goals(deck, world, selection.place).get(overlay.place, [])
    if selection.place is None:
        return []
    found = goals(deck, world, selection.place)
    order = {p.id: i for i, p in enumerate(deck.profile.places)}
    return [found[p][0] for p in sorted(found, key=lambda p: order.get(p, 0))]


def _choices(
    deck: Deck,
    selection: Selection,
    world: World,
    overlay: Overlay,
    size: int,
    back: TklDeckFace,
) -> list[TklDeckFace]:
    """The tracks for a train (hold on the train key, SD8): the goals light, the planned one
    with a star (SD20) and an occupied one dimmed with a red dot. Or, held on a goal, the
    other routes there (SD67)."""
    found = _choice_list(deck, selection, world, overlay)
    faces = [look.EMPTY] * size
    room = size - 1
    for i, goal in enumerate(found[:room]):
        name = _place_name(deck, goal.place)
        star = selection.planned == goal.place
        if overlay.kind == "routes":
            text, under = f"{goal.start}\N{RIGHTWARDS ARROW}{goal.end}", name
        else:
            text, under = name, ("planerat" if star else "ledigt")
        if not goal.possible:
            faces[i] = TklDeckFace(
                type="goal",
                text=text,
                under=look.short(goal.reason),
                bg="#191d21",
                fg="#98a2ad",
                dot=look.DOT,
                dim=True,
                star=star,
                label=f"Mål {name}: {goal.reason}",
            )
        else:
            faces[i] = TklDeckFace(
                type="goal",
                text=text,
                under=under,
                bg=look.GOAL_BG,
                fg=look.GOAL_FG,
                frame=look.GOAL_FRAME,
                star=star,
                label=f"Mål {name}",
            )
    faces[size - 1] = _cancel(selection, deck) if selection.chosen else back
    return faces


# --- the info line and the strip (SD18, SD82, SD83) ---------------------------------------------


def info(deck: Deck, selection: Selection, world: World) -> str:
    """Neo's info line: the clock and the page, or the choice when a start is chosen, and the
    latest no for three seconds (SD18, SD82)."""
    if world.locked:
        return world.time
    if deck.accepted is False and deck.message and world.now - deck.said_at < FLASH_SECONDS:
        return f"{world.time}  Nej: {deck.message}"[:60]
    if selection.chosen:
        start = selection.point or _place_name(deck, selection.place)
        return f"{world.time}  Start {start} · välj mål"[:60]
    page = current(deck)
    return f"{world.time}  {page.name if page else ''}".strip()[:60]


def strip(deck: Deck, selection: Selection, world: World) -> list[TklDeckStrip]:
    """What each dial stands on (SD83)."""
    if world.locked or world.interlocking is None or deck.mode is None:
        return []
    found: list[TklDeckStrip] = []
    for n, dial in enumerate(deck.profile.dials.get(deck.mode, [])):
        found.append(_strip_part(deck, selection, world, n, dial))
    return found


def _strip_part(
    deck: Deck, selection: Selection, world: World, n: int, dial: DeckDial
) -> TklDeckStrip:
    at = deck.dials.get(n, 0)
    state = world.state
    match dial:
        case DeckDial.TRAIN:
            turn = _turn(world, at + 1)
            if turn is None:
                return TklDeckStrip(label="Tåg", value="Inga")
            return TklDeckStrip(
                label="Tåg", value=f"{turn.number}", under=turn.time or turn.step.value
            )
        case DeckDial.TRACK | DeckDial.GOAL:
            choice = _dial_goal(deck, selection, world, at)
            label = "Spår" if dial == DeckDial.TRACK else "Mål"
            if choice is None:
                return TklDeckStrip(label=label, value="–")
            star = " \N{BLACK STAR}" if selection.planned == choice.place else ""
            return TklDeckStrip(
                label=label,
                value=_place_name(deck, choice.place) + star,
                under="ledigt" if choice.possible else look.short(choice.reason),
            )
        case DeckDial.PAGE:
            found = pages_of(deck, world, deck.mode)
            page = current(deck)
            number = found.index(deck.page) + 1 if deck.page in found else 1
            return TklDeckStrip(
                label="Sida", value=page.name if page else "", under=f"{number} av {len(found)}"
            )
        case DeckDial.ROUTE:
            if not state.routes:
                return TklDeckStrip(label="Lagd väg", value="Ingen")
            route = state.routes[at % len(state.routes)]
            return TklDeckStrip(
                label="Lagd väg",
                value=f"{route.start}\N{RIGHTWARDS ARROW}{route.end}",
                under="tryck: lös ut",
            )
        case DeckDial.START:
            name = _place_name(deck, selection.place) if selection.place else "–"
            return TklDeckStrip(label="Start", value=name)
        case DeckDial.PART:
            part = _dial_part(deck, at)
            return TklDeckStrip(label="Del", value=part.name if part else "–")
        case DeckDial.SIDEWAYS:
            return TklDeckStrip(label="Sidled", value=str(deck.origin[0]))
        case DeckDial.UPDOWN:
            return TklDeckStrip(label="Höjdled", value=str(deck.origin[1]))
        case DeckDial.SIGNAL:
            point = _dial_signal(deck, at)
            return TklDeckStrip(label="Signal", value=point or "–")
    return TklDeckStrip(label=dial.value)


def _dial_goal(deck: Deck, selection: Selection, world: World, at: int) -> Goal | None:
    if selection.place is None:
        return None
    found = _choice_list(deck, selection, world, Overlay(kind="choose"))
    return found[at % len(found)] if found else None


def _dial_part(deck: Deck, at: int) -> TklDeckPart | None:
    parts = deck.profile.parts
    return parts[at % len(parts)] if parts else None


def _dial_signal(deck: Deck, at: int) -> str | None:
    w, h = _cut(deck)
    tile = deck.profile.tile
    bx, by = deck.profile.tile_origin
    ox, oy = deck.origin
    rect = (bx + ox * tile, by + oy * tile, w * tile, h * tile)
    inside = [
        p
        for p in _points_in(deck, rect)
        if any(q.name == p and q.start for q in deck.profile.points)
    ]
    return inside[at % len(inside)] if inside else None


# --- what a press does --------------------------------------------------------------------------


def _said(deck: Deck, world: World, said: Said, index: int | None, text: str) -> Said:
    deck.message = said.message
    deck.accepted = said.accepted
    deck.said_at = world.now
    if not said.accepted and index is not None:
        deck.flash[index] = Flash(
            world.now + FLASH_SECONDS, text, look.short(said.message), deck.page
        )
    return said


def _say(deck: Deck, world: World, text: str) -> None:
    deck.message = text
    deck.accepted = None
    deck.said_at = world.now


def press(
    deck: Deck,
    selection: Selection,
    world: World,
    hands: Hands,
    index: int,
    hold: bool = False,
) -> None:
    """A press, or a hold, on a key. Nothing is done when TKL is locked (SD30) or the
    interlocking does not answer (SD21)."""
    settle(deck, world)
    press_here(deck, selection, world, hands, index, hold)


def press_here(
    deck: Deck,
    selection: Selection,
    world: World,
    hands: Hands,
    index: int,
    hold: bool = False,
) -> None:
    """A press on the page the deck shows, as it is: Prova alla knappar presses every page's
    keys this way, Tågen's too without Hubben (SD47)."""
    deck.revision += 1
    deck.flash = {i: f for i, f in deck.flash.items() if f.until > world.now}
    if world.locked or world.interlocking is None:
        return
    if deck.profile.style == DeckStyle.NONE:
        _press_pedal(deck, selection, world, hands, index, hold)
        return
    size = deck.profile.grid.columns * deck.profile.grid.rows
    if not 0 <= index < size:
        return
    if deck.overlay is not None:
        _press_overlay(deck, selection, world, hands, index, hold)
        return
    page = current(deck)
    if page is None:
        return
    if selection.point is not None and page.kind in (DeckPageKind.SIGNALS, DeckPageKind.ALL):
        listed = _goal_list(deck, selection, world, page)
        if listed is not None:
            _press_list(deck, selection, world, hands, index, size)
            return
    if selection.chosen and page.cancel == index:
        selection.clear()
        return
    key = page.keys[index] if index < len(page.keys) else None
    if key is None:
        return
    if key.confirm and not hold:
        # Fråga en gång till (SD43): the first press asks, the second within three seconds does.
        asked = deck.asking
        if asked is None or asked[:2] != (deck.page, index) or asked[2] <= world.now:
            deck.asking = (deck.page, index, world.now + ASK_SECONDS)
            _say(deck, world, "Tryck igen för att göra det.")
            return
    deck.asking = None
    _press_key(deck, selection, world, hands, page, key, index, hold)


def _press_pedal(
    deck: Deck, selection: Selection, world: World, hands: Hands, index: int, hold: bool
) -> None:
    """A pedal does what the owner chose for it, and nothing before that (SD55). A hold does
    only what the owner chose for the hold: Lös ut alla is never on a pedal."""
    pedals = deck.profile.pedals
    key = pedals[index] if 0 <= index < len(pedals) else None
    if key is None:
        _say(deck, world, "Pedalen gör ingenting förrän en funktion är vald i Studio.")
        return
    page = current(deck) or TklDeckPage(
        name="Pedal", mode=DeckMode.PLACES, kind=DeckPageKind.OWN, keys=[]
    )
    if hold and key.hold is None:
        return
    _press_key(deck, selection, world, hands, page, key, None, hold)


def _press_list(
    deck: Deck, selection: Selection, world: World, hands: Hands, index: int, size: int
) -> None:
    room = max(1, size - 2)
    targets = list(_targets_of(world, selection))
    listed = [selection.point or "", *targets]
    if index == size - 1:
        selection.clear()
        deck.sub = 0
        return
    if index == size - 2:
        deck.sub += 1
        return
    at = deck.sub * room + index
    if at < len(listed):
        _choose_point(deck, selection, world, hands, listed[at], index)


def _press_key(
    deck: Deck,
    selection: Selection,
    world: World,
    hands: Hands,
    page: TklDeckPage,
    key: TklDeckKey,
    index: int | None,
    hold: bool,
) -> None:
    chosen = key.hold if hold else key.press
    if chosen is not None:
        # What the owner chose from the fixed list (SD43).
        _do(deck, selection, world, hands, page, key, chosen, index, hold)
        return
    if index is None:
        # A pedal: only what can be done without a screen.
        if key.type == K.ACTION:
            _press_action(deck, selection, world, hands, page, key.action, None, False)
        elif key.type == K.ROUTE:
            _press_quick(deck, world, hands, key, None, False)
        elif key.type == K.PANEL:
            _press_panel(deck, world, hands, key, None)
        return
    match key.type:
        case K.TRAIN:
            _press_train(deck, selection, world, hands, _turn(world, key.slot), index, hold)
        case K.LINE:
            _press_line(deck, world, hands, _line(world, key.slot), index)
        case K.ALARM:
            if world.cases:
                deck.overlay = Overlay(kind="case", case=world.cases[0])
        case K.PLACE:
            _press_place(deck, selection, world, hands, key.place or "", index, hold)
        case K.TRACK:
            _press_track(deck, selection, world, hands, key.place or "", index, hold)
        case K.PART:
            if key.page is not None:
                deck.page = key.page
        case K.SIGNAL:
            _choose_point(deck, selection, world, hands, key.point or "", index)
        case K.DAILY:
            _press_daily(deck, world, hands, key.slot, index, hold)
        case K.FAVOURITE:
            _press_favourite(deck, world, hands, key.slot, index, hold)
        case K.TILE:
            _open_cutout(deck, key)
        case K.CELL:
            _press_cell(deck, selection, world, hands, key, index)
        case K.PAN:
            _pan(deck, key.pan)
        case K.MODE:
            if hold:
                deck.overlay, deck.sub = Overlay(kind="pages"), 0
            elif not deck.settings.may_change_mode:
                _say(deck, world, "Läget går inte att byta på det här decket.")
            else:
                deck.overlay = Overlay(kind="modes")
        case K.NEXT:
            if hold:
                deck.overlay = Overlay(kind="modes")
                return
            following = _next_page(deck, world)
            if following is not None:
                deck.page = following
        case K.PAGE:
            if hold:
                deck.overlay, deck.sub = Overlay(kind="pages"), 0
                return
            following = _next_page(deck, world)
            if following is not None:
                deck.page = following
        case K.ACTION:
            _press_action(deck, selection, world, hands, page, key.action, index, hold)
        case K.PANEL:
            _press_panel(deck, world, hands, key, index)
        case K.ROUTE:
            _press_quick(deck, world, hands, key, index, hold)


def _press_panel(
    deck: Deck, world: World, hands: Hands, key: TklDeckKey, index: int | None
) -> None:
    found = next((f for f in world.state.functions if f.name == key.function), None)
    if found is not None:
        _said(deck, world, hands.function(found.name, not found.on), index, found.name)


def _laid(world: World, route: TklDeckRoute) -> int | None:
    found = next(
        (r for r in world.state.routes if r.start == route.start and r.end == route.end), None
    )
    return None if found is None else (found.chain or found.id)


def _press_quick(
    deck: Deck, world: World, hands: Hands, key: TklDeckKey, index: int | None, hold: bool
) -> None:
    """Snabbväg (SD42): a press sets the whole route, and again runs it outside drift as
    Favoriter's do; holding releases it (SD29)."""
    route = key.route
    if route is None:
        return
    text = f"{route.start}\N{RIGHTWARDS ARROW}{route.end}"
    laid = next(
        (r for r in world.state.routes if r.start == route.start and r.end == route.end), None
    )
    if hold:
        if laid is not None:
            _said(deck, world, hands.release(laid.chain or laid.id), index, text)
        return
    if laid is not None and not world.drift:
        _said(deck, world, hands.step(laid.id), index, text)
        return
    _set(deck, world, hands, route.start, route.end, route.kind, index, text)


def _do(
    deck: Deck,
    selection: Selection,
    world: World,
    hands: Hands,
    page: TklDeckPage,
    key: TklDeckKey,
    action: DeckAction,
    index: int | None,
    hold: bool,
) -> None:
    """A press or a hold the owner chose from the fixed list (SD43). Lös ut alla, Noll and
    Nödutlösning only with a hold (SD29)."""
    route = key.route
    text = f"{route.start}\N{RIGHTWARDS ARROW}{route.end}" if route is not None else ""
    match action:
        case DeckAction.NOTHING:
            return
        case DeckAction.LAY:
            if route is not None:
                _set(deck, world, hands, route.start, route.end, route.kind, index, text)
        case DeckAction.RELEASE_ROUTE:
            laid = _laid(world, route) if route is not None else None
            if laid is None:
                _say(deck, world, "Vägen ligger inte.")
                return
            _said(deck, world, hands.release(laid), index, text)
        case DeckAction.RUN if route is not None:
            found = next(
                (r for r in world.state.routes if r.start == route.start and r.end == route.end),
                None,
            )
            if found is None:
                _say(deck, world, "Vägen ligger inte.")
                return
            _said(deck, world, hands.step(found.id), index, text)
        case _:
            _press_action(deck, selection, world, hands, page, action, index, hold)


def _press_overlay(
    deck: Deck, selection: Selection, world: World, hands: Hands, index: int, hold: bool
) -> None:
    overlay = deck.overlay
    assert overlay is not None
    profile = deck.profile
    size = profile.grid.columns * profile.grid.rows
    page = current(deck)
    if overlay.kind == "modes":
        shown_now = _overlay(deck, selection, world)
        if 0 <= index < len(shown_now) and shown_now[index] == look.LOCK:
            deck.overlay = None
            _said(deck, world, hands.lock(), None, "Lås")
            return
        have = modes(deck, world)
        mode_at = next(
            (i for i, k in enumerate(page.keys if page else []) if k and k.type == K.MODE), None
        )
        if profile.style == DeckStyle.NEXT and index == size - 2:
            deck.overlay, deck.sub = Overlay(kind="pages"), 0
            return
        if (index == size - 1 and profile.style == DeckStyle.NEXT) or index == mode_at:
            deck.overlay = None
            if hold and index == mode_at:
                deck.overlay, deck.sub = Overlay(kind="pages"), 0
            return
        if index < len(have) and index < size - 1:
            go_mode(deck, world, have[index])
            return
        column = index - profile.grid.columns
        if profile.style != DeckStyle.NEXT and 0 <= column < len(have):
            _toggle_variant(deck, have[column])
        return
    if overlay.kind == "pages":
        listed = every_page(deck, world)
        room = size - 1
        count = max(1, math.ceil(len(listed) / room))
        if index == size - 1:
            deck.overlay = None
            return
        if count > 1 and index == room - 1:
            deck.sub = (deck.sub + 1) % count
            return
        at = deck.sub * room + index
        if at < len(listed):
            chosen = profile.pages[listed[at]]
            deck.mode = chosen.mode
            deck.page = listed[at]
            deck.overlay = None
        return
    if overlay.kind == "case":
        case = overlay.case
        if index == size - 1:
            deck.overlay = None
            return
        if case is not None and case.kind == "clearance" and case.clearance and index in (1, 2):
            c = case.clearance
            said = hands.command(
                station.Action.CLEARANCE_RESPONSE,
                {"clearance_id": c.clearance_id, "approved": index == 1},
                station.Revision(
                    scope=station.RevisionScope.CASE, key=c.clearance_id, value=c.revision
                ),
            )
            _said(deck, world, said, None, "Klart" if index == 1 else "Nej")
            deck.overlay = None
        return
    if overlay.kind in ("choose", "routes"):
        if index == size - 1:
            selection.clear()
            deck.overlay = None
            return
        found = _choice_list(deck, selection, world, overlay)
        if index < len(found) and index < size - 1:
            goal = found[index]
            said = hands.set_route(goal.start, goal.end, RouteKind.TRAIN)
            _said(deck, world, said, index, _place_name(deck, goal.place))
            if said.accepted:
                selection.clear()
                deck.overlay = None


def _toggle_variant(deck: Deck, mode: DeckMode) -> None:
    s = deck.settings
    if mode == DeckMode.PLACES:
        shown_now = (
            DeckPlacesShown.CHOOSABLE
            if s.places_shown == DeckPlacesShown.ALL
            else DeckPlacesShown.ALL
        )
        deck.settings = s.model_copy(update={"places_shown": shown_now})
    elif mode == DeckMode.TRACK_PLAN:
        drawn = (
            DeckPlanDrawn.RELAY
            if s.plan_drawn == DeckPlanDrawn.STANDARD_85
            else DeckPlanDrawn.STANDARD_85
        )
        deck.settings = s.model_copy(update={"plan_drawn": drawn})


def _set(
    deck: Deck,
    world: World,
    hands: Hands,
    start: str,
    end: str,
    kind: RouteKind | None,
    index: int | None,
    text: str,
) -> Said:
    return _said(deck, world, hands.set_route(start, end, kind), index, text)


def _set_places(
    deck: Deck, world: World, hands: Hands, origin: str, goal: str, index: int | None, text: str
) -> Said:
    """The route from a place to a place: the first that can be set, else the interlocking's
    no for the preferred one."""
    found = best(deck, world, origin, goal)
    if found is None:
        said = Said(
            False,
            f"Ingen tågväg går från {_place_name(deck, origin)} till {_place_name(deck, goal)}.",
        )
        return _said(deck, world, said, index, text)
    return _set(deck, world, hands, found.start, found.end, RouteKind.TRAIN, index, text)


def _press_train(
    deck: Deck,
    selection: Selection,
    world: World,
    hands: Hands,
    turn: Turn | None,
    index: int,
    hold: bool,
) -> None:
    """The train key's next step (SD8, SD10): lay the entry, ask for clearance, lay the exit.
    Hold chooses another track. It never sets anything without a press (SD9)."""
    if turn is None:
        return
    text = turn.number
    match turn.step:
        case Step.WAITING | Step.COMING:
            if hold or turn.origin is None or turn.track is None:
                _choose(deck, selection, world, turn.origin, turn)
                return
            _set_places(deck, world, hands, turn.origin, turn.track, index, text)
        case Step.ENTRY | Step.EXIT:
            if hold and turn.route is not None:
                _said(deck, world, hands.release(turn.route), index, text)
            elif not world.drift and turn.route is not None:
                _said(deck, world, hands.step(turn.route), index, text)
            else:
                _say(deck, world, "Vägen ligger · håll in för att lösa ut")
        case Step.RUNNING:
            if not world.drift and turn.route is not None:
                _said(deck, world, hands.step(turn.route), index, text)
            else:
                _say(deck, world, f"Tåg {turn.number} kör.")
        case Step.ARRIVE:
            if turn.route is not None:
                _said(deck, world, hands.arrive(turn.route), index, text)
        case Step.IN:
            if hold:
                _choose(deck, selection, world, turn.track, turn)
                return
            if turn.call is not None and turn.section is not None and world.snapshot is not None:
                call = turn.call
                said = hands.command(
                    station.Action.CLEARANCE_REQUEST,
                    {
                        "call": call.call,
                        "section": turn.section,
                        "clearance_id": f"tkl-deck-{call.call}-{call.revision}",
                    },
                    station.Revision(
                        scope=station.RevisionScope.CALL, key=call.call, value=call.revision
                    ),
                )
                _said(deck, world, said, index, text)
                return
            _exit(deck, selection, world, hands, turn, index)
        case Step.ASKED:
            if hold:
                _choose(deck, selection, world, turn.track, turn)
            else:
                _say(deck, world, f"Tåg {turn.number} väntar på klart.")
        case Step.CLEARED:
            if hold:
                _choose(deck, selection, world, turn.track, turn)
                return
            _exit(deck, selection, world, hands, turn, index)
        case Step.LEFT:
            _say(deck, world, f"Tåg {turn.number} har lämnat.")


def _exit(
    deck: Deck, selection: Selection, world: World, hands: Hands, turn: Turn, index: int
) -> None:
    if turn.track is None:
        _say(deck, world, f"Tåg {turn.number} står inte på ett spår i stationsmodellen.")
        return
    if turn.goal is None:
        _choose(deck, selection, world, turn.track, turn)
        return
    _set_places(deck, world, hands, turn.track, turn.goal, index, turn.number)


def _choose(
    deck: Deck, selection: Selection, world: World, place: str | None, turn: Turn | None
) -> None:
    """Another track for a train: its goals light (SD8, SD20)."""
    if place is None:
        _say(deck, world, "Decket vet inte var tåget kommer in. Välj start i Platser.")
        return
    selection.clear()
    selection.place = place
    selection.train = turn.number if turn else None
    selection.planned = turn.planned if turn else None
    deck.overlay = Overlay(kind="choose")


def _press_line(deck: Deck, world: World, hands: Hands, line: Line | None, index: int) -> None:
    """The line key (SD13, SD14): the neighbour's question opens with Klart and Nej as keys of
    their own, so that clearance is never given with a single press; else clearance is asked
    for the next train out."""
    if line is None:
        return
    if line.asks is not None:
        deck.overlay = Overlay(
            kind="case",
            case=Case(
                kind="clearance",
                top="klarering",
                text=line.code,
                under=f"frågar: {line.asks.train_number}",
                clearance=line.asks,
            ),
        )
        return
    call = line.ask_for
    if call is None:
        _say(deck, world, f"Inget tåg att begära klart för mot {line.code}.")
        return
    said = hands.command(
        station.Action.CLEARANCE_REQUEST,
        {
            "call": call.call,
            "section": line.section.section,
            "clearance_id": f"tkl-deck-{call.call}-{call.revision}",
        },
        station.Revision(scope=station.RevisionScope.CALL, key=call.call, value=call.revision),
    )
    _said(deck, world, said, index, line.code)


def _press_place(
    deck: Deck,
    selection: Selection,
    world: World,
    hands: Hands,
    place: str,
    index: int,
    hold: bool,
) -> None:
    """Platser (SD67): a press on the start lights the goals, and a press on a goal sets the
    whole route through the signals between. Hold on a goal shows the other routes there."""
    name = _place_name(deck, place)
    if selection.place is None:
        found = place_of(world, deck, place)
        if found is None or not found.starts:
            _say(deck, world, f"Inga tågvägar börjar vid {name}.")
            return
        selection.clear()
        selection.place = place
        return
    if selection.place == place:
        selection.clear()
        return
    targets = goals(deck, world, selection.place)
    if place not in targets:
        _say(deck, world, f"{name} går inte att nå från {_place_name(deck, selection.place)}.")
        return
    if hold:
        deck.overlay = Overlay(kind="routes", place=place)
        return
    said = _set_places(deck, world, hands, selection.place, place, index, name)
    if said.accepted:
        selection.clear()


def _press_track(
    deck: Deck,
    selection: Selection,
    world: World,
    hands: Hands,
    place: str,
    index: int,
    hold: bool,
) -> None:
    """The track key at a station with one line (SD12): a free track takes a train in, an
    occupied one lets it out. Hold releases the route on the track."""
    found = place_of(world, deck, place)
    line = next((p for p in deck.profile.places if p.kind == "exit"), None)
    if found is None or line is None:
        return
    pieces = place_pieces(world, found)
    state = world.state
    on_track = [r for r in state.routes if any(set(s.pieces) & pieces for s in r.sections)]
    if hold:
        for route in on_track[-1:]:
            _said(deck, world, hands.release(route.chain or route.id), index, found.name)
        return
    if selection.chosen:
        _press_place(deck, selection, world, hands, place, index, hold)
        return
    number, colour = number_at(world, found)
    if number and colour == "red":
        _set_places(deck, world, hands, place, line.id, index, found.name)
    else:
        _set_places(deck, world, hands, line.id, place, index, found.name)


def _choose_point(
    deck: Deck, selection: Selection, world: World, hands: Hands, point: str, index: int
) -> None:
    """A signal (the prototype's valjSignal): the start, again for a shunting route and once
    more to cancel; then a goal sets the route (STV-24)."""
    if selection.point is None:
        targets = world.targets(point)
        if targets is None or not targets.kinds:
            _say(deck, world, f"Inga vägar från {point}.")
            return
        selection.clear()
        selection.point, selection.kind = point, RouteKind(targets.kinds[0].value)
        deck.sub = 0
        return
    if selection.point == point:
        targets = world.targets(point)
        kinds = [RouteKind(k.value) for k in (targets.kinds if targets else [])]
        other = next((k for k in kinds if k != selection.kind), None)
        if other is not None and selection.kind == RouteKind.TRAIN:
            selection.kind = other
            selection.revision += 1
            deck.sub = 0
            return
        selection.clear()
        return
    start, kind = selection.point, selection.kind
    if point not in _targets_of(world, selection):
        _say(deck, world, f"{point} går inte att nå från {start}.")
        return
    said = _set(deck, world, hands, start, point, kind, index, point)
    if said.accepted:
        selection.clear()
        deck.sub = 0


def _press_daily(
    deck: Deck, world: World, hands: Hands, slot: int | None, index: int, hold: bool
) -> None:
    found = world.daily
    if slot is None or not 0 < slot <= len(found):
        return
    route = found[slot - 1]
    text = route.number
    goal = best(deck, world, route.origin, route.goal)
    if hold:
        laid = next(
            (r for r in world.state.routes if goal and r.start == goal.start and r.end == goal.end),
            None,
        )
        if laid is not None:
            _said(deck, world, hands.release(laid.chain or laid.id), index, text)
        return
    _set_places(deck, world, hands, route.origin, route.goal, index, text)


def _press_favourite(
    deck: Deck, world: World, hands: Hands, slot: int | None, index: int, hold: bool
) -> None:
    found = world.favourites
    if slot is None or not 0 < slot <= len(found):
        return
    route = found[slot - 1]
    laid = next(
        (r for r in world.state.routes if r.start == route.start and r.end == route.end), None
    )
    text = f"{route.start}\N{RIGHTWARDS ARROW}{route.end}"
    if hold:
        if laid is not None:
            _said(deck, world, hands.release(laid.chain or laid.id), index, text)
        return
    if laid is not None and not world.drift:
        _said(deck, world, hands.step(laid.id), index, text)
        return
    _set(deck, world, hands, route.start, route.end, route.kind, index, text)


def _open_cutout(deck: Deck, key: TklDeckKey) -> None:
    """A press on a piece of Hela opens the cut-out there (SD70)."""
    page = next(
        (i for i, p in enumerate(deck.profile.pages) if p.kind == DeckPageKind.CUTOUT), None
    )
    if page is None or key.rect is None:
        return
    x, y, w, h = key.rect
    tile = deck.profile.tile
    bx, by = deck.profile.tile_origin
    cw, ch = _cut(deck)
    deck.page = page
    # The cut-out with the piece in its middle.
    deck.origin = (
        math.floor((x + w / 2 - bx) / tile - cw / 2),
        math.floor((y + h / 2 - by) / tile - ch / 2),
    )
    _clamp(deck)


def _clamp(deck: Deck) -> None:
    w, h = _cut(deck)
    pw, ph = deck.profile.plan
    tile = deck.profile.tile
    most_x = max(0, math.ceil(pw / tile) - w)
    most_y = max(0, math.ceil(ph / tile) - h)
    deck.origin = (min(max(0, deck.origin[0]), most_x), min(max(0, deck.origin[1]), most_y))


def _pan(deck: Deck, pan: DeckPan | None) -> None:
    """The pan keys (SD71, SD81): half a cut-out sideways; up and down a whole one, round."""
    w, h = _cut(deck)
    _, ph = deck.profile.plan
    tile = deck.profile.tile
    ox, oy = deck.origin
    most_y = max(0, math.ceil(ph / tile) - h)
    match pan:
        case DeckPan.WHOLE:
            found = next(
                (i for i, p in enumerate(deck.profile.pages) if p.kind == DeckPageKind.WHOLE), None
            )
            if found is not None:
                deck.page = found
            return
        case DeckPan.WEST:
            ox -= max(1, w // 2)
        case DeckPan.EAST:
            ox += max(1, w // 2)
        case DeckPan.UP:
            oy = oy - h if oy > 0 else most_y
        case DeckPan.DOWN:
            oy = oy + h if oy < most_y else 0
    deck.origin = (ox, oy)
    _clamp(deck)


def _press_cell(
    deck: Deck,
    selection: Selection,
    world: World,
    hands: Hands,
    key: TklDeckKey,
    index: int,
) -> None:
    """A square of the cut-out: start and goal as in the panel (SD71)."""
    inside = _points_in(deck, _cell_rect(deck, key))
    if not inside:
        return
    if selection.point is not None:
        targets = _targets_of(world, selection)
        goal = next((p for p in inside if p in targets), None)
        if goal is not None or selection.point in inside:
            _choose_point(deck, selection, world, hands, goal or selection.point, index)
            return
    starts = [p for p in inside if any(q.name == p and q.start for q in deck.profile.points)]
    if starts:
        selection.clear()
        _choose_point(deck, selection, world, hands, starts[0], index)


def _press_action(
    deck: Deck,
    selection: Selection,
    world: World,
    hands: Hands,
    page: TklDeckPage,
    action: DeckAction | None,
    index: int | None,
    hold: bool,
) -> None:
    state = world.state
    if action in HOLD_ONLY and not hold:
        name = {
            DeckAction.RELEASE_ALL: "Lös ut alla",
            DeckAction.RESET: "Noll",
            DeckAction.EMERGENCY: "Nödutlösning",
        }[action]
        _say(deck, world, f"Håll in för {name}.")
        return
    match action:
        case DeckAction.RELEASE:
            roots = list(dict.fromkeys((r.chain or r.id) for r in state.routes))
            if not roots:
                _say(deck, world, "Inga vägar att lösa ut.")
                return
            for route in reversed(roots) if hold else roots[-1:]:
                _said(deck, world, hands.release(route), index, "Lös ut")
        case DeckAction.ARRIVED if not world.drift:
            runnable = _runnable(world)
            if runnable is None:
                _say(deck, world, "Ingen väg att köra.")
                return
            _said(deck, world, hands.step(runnable), index, "Kör")
        case DeckAction.ARRIVED:
            found = _arrivable(world)
            if found is None:
                _say(deck, world, "Inget tåg att anmäla.")
                return
            _said(deck, world, hands.arrive(found[0]), index, "Ankommit")
        case DeckAction.RUN:
            runnable = _runnable(world)
            if runnable is not None:
                _said(deck, world, hands.step(runnable), index, "Kör")
        case DeckAction.CANCEL:
            selection.clear()
        case DeckAction.BACK:
            parts = next(
                (
                    i
                    for i, p in enumerate(deck.profile.pages)
                    if p.mode == page.mode and p.kind == DeckPageKind.PARTS
                ),
                None,
            )
            if parts is not None:
                deck.page = parts
        case DeckAction.LOCK:
            # Lås (Fika, SD30), where the owner has put it in Studio (#86 del c).
            _said(deck, world, hands.lock(), None, "Lås")
        case DeckAction.RELEASE_ALL:
            roots = list(dict.fromkeys((r.chain or r.id) for r in state.routes))
            if not roots:
                _say(deck, world, "Inga vägar att lösa ut.")
                return
            for route in reversed(roots):
                _said(deck, world, hands.release(route), index, "Lös ut alla")
        case DeckAction.RESET:
            _said(deck, world, hands.reset(), index, "Noll")
        case DeckAction.EMERGENCY:
            latest = list(dict.fromkeys((r.chain or r.id) for r in state.routes))
            if not latest:
                _say(deck, world, "Ingen väg att nödutlösa.")
                return
            _said(deck, world, hands.emergency(latest[-1]), index, "Nödutlösning")


# --- dials and touch (SD82, SD83) ----------------------------------------------------------------


def dial(
    deck: Deck,
    selection: Selection,
    world: World,
    hands: Hands,
    number: int,
    turn: int = 0,
    pushed: bool = False,
) -> None:
    """A dial: turn chooses, press does it (SD83)."""
    settle(deck, world)
    deck.revision += 1
    if world.locked or world.interlocking is None or deck.mode is None:
        return
    found = deck.profile.dials.get(deck.mode, [])
    if not 0 <= number < len(found):
        return
    what = found[number]
    at = deck.dials.get(number, 0) + turn
    deck.dials[number] = at
    state = world.state
    match what:
        case DeckDial.TRAIN:
            if pushed:
                _press_train(
                    deck,
                    selection,
                    world,
                    hands,
                    _turn(world, at % max(1, len(world.turns)) + 1),
                    -1,
                    False,
                )
        case DeckDial.TRACK | DeckDial.GOAL:
            if what == DeckDial.TRACK and turn and selection.place is None:
                current_turn = _turn(world, deck.dials.get(0, 0) % max(1, len(world.turns)) + 1)
                if current_turn is not None:
                    selection.clear()
                    selection.place = current_turn.origin or current_turn.track
                    selection.train = current_turn.number
                    selection.planned = current_turn.planned
            if pushed:
                goal = _dial_goal(deck, selection, world, at)
                if goal is not None:
                    said = _set(
                        deck, world, hands, goal.start, goal.end, RouteKind.TRAIN, None, goal.place
                    )
                    if said.accepted:
                        selection.clear()
        case DeckDial.PAGE:
            if pushed:
                deck.overlay, deck.sub = Overlay(kind="pages"), 0
            elif turn:
                listed = pages_of(deck, world, deck.mode)
                if listed:
                    here = listed.index(deck.page) if deck.page in listed else 0
                    deck.page = listed[(here + turn) % len(listed)]
        case DeckDial.ROUTE:
            if pushed and state.routes:
                route = state.routes[at % len(state.routes)]
                _said(deck, world, hands.release(route.chain or route.id), None, "Lös ut")
        case DeckDial.START:
            places = deck.profile.places
            if turn and places:
                selection.clear()
                selection.place = places[at % len(places)].id
        case DeckDial.PART:
            parts = [i for i, p in enumerate(deck.profile.pages) if p.kind == DeckPageKind.PART]
            if pushed:
                found_parts = next(
                    (i for i, p in enumerate(deck.profile.pages) if p.kind == DeckPageKind.PARTS),
                    None,
                )
                if found_parts is not None:
                    deck.page = found_parts
            elif turn and parts:
                deck.page = parts[at % len(parts)]
        case DeckDial.SIDEWAYS:
            if pushed:
                _pan(deck, DeckPan.WHOLE)
            else:
                deck.origin = (deck.origin[0] + turn, deck.origin[1])
                _clamp(deck)
        case DeckDial.UPDOWN:
            deck.origin = (deck.origin[0], deck.origin[1] + turn)
            _clamp(deck)
        case DeckDial.SIGNAL:
            point = _dial_signal(deck, at)
            if pushed and point is not None:
                _choose_point(deck, selection, world, hands, point, -1)


def touch(deck: Deck, world: World, point: int) -> None:
    """Neo's touch points (SD82): the pages of the mode, back and forth."""
    settle(deck, world)
    deck.revision += 1
    if world.locked or world.interlocking is None:
        return
    listed = pages_of(deck, world, deck.mode)
    if not listed:
        return
    deck.overlay = None
    here = listed.index(deck.page) if deck.page in listed else 0
    deck.page = listed[(here + point) % len(listed)]


# --- holding a key (SD29), for a deck that reports down and up --------------------------------


@dataclass
class Holds:
    """A key held for the deck's hold time is a hold, else a press (SD29). For a deck that
    reports when a key goes down and up (del b), with the time in seconds."""

    seconds: float = 0.6
    down: dict[int, float] = field(default_factory=dict)
    held: set[int] = field(default_factory=set)

    def pressed(self, key: int, at: float) -> None:
        self.down[key] = at
        self.held.discard(key)

    def tick(self, at: float) -> list[int]:
        """The keys that have just been held long enough: a hold, while still down."""
        found = [k for k, t in self.down.items() if at - t >= self.seconds and k not in self.held]
        self.held.update(found)
        return found

    def released(self, key: int, at: float) -> Literal["press", "hold"] | None:
        """A key let go: a press when it was short, a hold when tick has not said so already,
        else nothing."""
        began = self.down.pop(key, None)
        if began is None:
            return None
        if key in self.held:
            self.held.discard(key)
            return None
        return "hold" if at - began >= self.seconds else "press"


def favourites(
    pinned: list[TklDeckRoute],
    counted: dict[tuple[str, str, RouteKind], int],
    exists: Callable[[TklDeckRoute], bool],
) -> list[TklDeckRoute]:
    """Favoriter (TKL70, SD24): the pinned routes first, then those set at least twice, the
    most used first. Only routes that still exist."""
    shown_routes = [r for r in pinned if exists(r)]
    keys = {(r.start, r.end, r.kind) for r in shown_routes}
    most = sorted(
        ((k, n) for k, n in counted.items() if n >= 2 and k not in keys),
        key=lambda item: (-item[1], item[0][0], item[0][1]),
    )
    for (start, end, kind), _ in most:
        route = TklDeckRoute(start=start, end=end, kind=kind)
        if exists(route):
            shown_routes.append(route)
        if len(shown_routes) >= len(pinned) + MOST_FAVOURITES:
            break
    return shown_routes


__all__ = [
    "Deck",
    "Hands",
    "Holds",
    "Overlay",
    "Said",
    "Selection",
    "World",
    "dial",
    "favourites",
    "open_deck",
    "press",
    "press_here",
    "touch",
    "view",
]
