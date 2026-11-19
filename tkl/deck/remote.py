"""Fjärr (#36 del d, SD37): the fjärrtågklarerare's deck, made from the remote catalogues.

A deck with the role Fjärrtågklareraren (DECK_REMOTE_ROLE) has the mode Fjärr only. Its profile is
computed from the remote catalogues of the stations TKL controls, as Hubben's Overview has them
for the fjärrbild, never from a station model: a page per station, a key per catalogue route in
the catalogue's order, and more pages for a station whose routes do not fit on one. The fixed keys
follow the deck's frame (tkl.deck.profile.frame): Erbjudande for a station offered to TKL (FR8),
Avbryt, the clock, ▶ to the next page and Läge, which lists the pages. On the small decks ▶ and
Läge stay, and the offer goes in among the routes.

A route blinks until the press is repeated (SD37, FR13): the first press chooses it, the second
sends route.request through the same path as the fjärrbild's /fjarr/commands, where Hubben checks
who asks and the catalogue and the station's own interlocking the safety (FR11, FR12). What a key
shows is read from Hubben's routes and the station's route.state, never from what was sent:
asked for and waiting in amber, locked green, and a no, from Hubben at once or from the station,
red with its reason for three seconds (SD18). Holding a route TKL asked for takes it away
(route.cancel). The offer key takes the station with a press and declines it with a hold.

Pure Python without I/O: the hub is reached through `RemoteHands`. No code here names a station
(RS13).
"""

from __future__ import annotations

import json
import time as clock_time
from collections.abc import Sequence
from dataclasses import dataclass, field
from secrets import token_hex
from threading import Lock
from typing import Final, Protocol

from contracts import station
from contracts.reasons import TEXT_SV, Reason
from contracts.station_outside import RemoteRoute, RouteDirection
from contracts.tkl import (
    DeckAction,
    DeckKeyType,
    DeckMode,
    DeckModelId,
    DeckPageKind,
    DeckStyle,
    TklDeckFace,
    TklDeckGrid,
    TklDeckKey,
    TklDeckPage,
    TklDeckProfile,
    TklDeckSettings,
    TklDeckView,
    TklFjarr,
)
from tkl.deck import look
from tkl.deck.logic import FLASH_SECONDS, HOLD_MS, Deck, Flash, Overlay, Said
from tkl.deck.places import Geography
from tkl.deck.profile import Builder, Frame, frame

K = DeckKeyType
A = DeckAction
MODE: Final = DeckMode.REMOTE
NOTHING_YET: Final = "Fjärr"
"""The page when TKL controls no station: only the fixed keys, and the offers."""
ROLES: Final = {"arrived": "offer", "release": "cancel", "alarm": "clock"}
"""The deck's fixed keys in the fjärrtågklarerare's role, by the frame's role (SD27, SD75)."""
WAITING_MS: Final = 1000
"""How often the deck reads again while a route blinks or waits for the station's answer."""
RESTING_MS: Final = 2000
"""How often it reads otherwise: the stations' answers come from Hubben, not from a press."""
ROUTE_BG: Final = "#1f2937"
ROUTE_FG: Final = "#e6e9ec"
WAITING_BG: Final = "#a16207"
WAITING_BLINK: Final = "#422006"
OFFER_BG: Final = "#a16207"
OFFER_BLINK: Final = "#422006"
NOT_MINE: Final = "Stationen styrs inte härifrån."
MOST: Final = 60
"""A key's text and label hold at most this many characters (KeyText)."""


@dataclass(frozen=True)
class Station:
    """A station TKL controls, as the profile is made from it: its catalogue in order."""

    place: str
    name: str
    code: str
    routes: tuple[RemoteRoute, ...]


class RemoteHands(Protocol):
    """What the fjärrtågklarerare's deck may do: station commands through Hubben, the same as
    the fjärrbild's /fjarr/commands (FR8, FR11)."""

    def command(self, place: str, action: station.Action, payload: dict[str, object]) -> Said: ...


@dataclass
class RemoteWorld:
    """What the deck reads: the fjärrbild's data (None when TKL has no contact with Hubben),
    whether TKL is locked, the clock and TKL's name."""

    fjarr: TklFjarr | None
    locked: bool = False
    time: str = ""
    name: str = ""
    now: float = field(default_factory=clock_time.monotonic)

    def place(self, place: str | None) -> station.OverviewPlace | None:
        if self.fjarr is None or self.fjarr.overview is None:
            return None
        return next((p for p in self.fjarr.overview.places if p.place.place == place), None)

    def controls(self, place: str | None) -> bool:
        return self.fjarr is not None and place in self.fjarr.controls


def stations(fjarr: TklFjarr | None) -> list[Station]:
    """The stations TKL controls, in Hubben's order, each with its remote catalogue."""
    if fjarr is None or fjarr.overview is None:
        return []
    mine = set(fjarr.controls)
    return [
        Station(
            place=p.place.place,
            name=p.place.name,
            code=p.place.code,
            routes=tuple(p.outside.remote_routes) if p.outside is not None else (),
        )
        for p in fjarr.overview.places
        if p.place.place in mine
    ]


def shown_of(fjarr: TklFjarr | None) -> str:
    """What the deck shows of the picture, in short: it changes when a key's face may, and not
    with the clock or the seconds since a station was heard, so that a deck waiting for its
    next change is not woken every second."""
    if fjarr is None or fjarr.overview is None:
        return ""
    said = {
        "controls": sorted(fjarr.controls),
        "offers": sorted(o.place for o in fjarr.offers),
        "places": [
            [
                p.place.place,
                [(r.request_id, r.state.value) for r in p.routes],
                sorted(r.route for r in p.route_state.locked) if p.route_state else [],
            ]
            for p in fjarr.overview.places
        ],
    }
    return json.dumps(said, sort_keys=True)


# --- the profile ---------------------------------------------------------------------------------


def route_text(route: RemoteRoute) -> tuple[str, str]:
    """A route on its key: start and track in, track and goal out."""
    if route.direction == RouteDirection.IN:
        return f"{route.start}\N{RIGHTWARDS ARROW}{route.track}", "in"
    return f"{route.track}\N{RIGHTWARDS ARROW}{route.end}", "ut"


def route_said(route: RemoteRoute) -> str:
    """A route as the deck's message says it, as the fjärrbild does."""
    if route.direction == RouteDirection.IN:
        to = (
            f"spår {route.track}"
            if route.end == route.track
            else f"{route.end}, spår {route.track}"
        )
        return f"{route.start} \N{RIGHTWARDS ARROW} {to}"
    return f"{route.start} (spår {route.track}) \N{RIGHTWARDS ARROW} {route.end}"


def _fixed(f: Frame) -> dict[int, TklDeckKey]:
    keys: dict[int, TklDeckKey] = {}
    for role, index in f.fixed.items():
        given = ROLES.get(role, role)
        if given == "offer":
            keys[index] = TklDeckKey(type=K.OFFER)
        elif given == "cancel":
            keys[index] = TklDeckKey(type=K.ACTION, action=A.CANCEL)
        elif given == "clock":
            keys[index] = TklDeckKey(type=K.ACTION, action=A.CLOCK)
        elif given == "page":
            keys[index] = TklDeckKey(type=K.PAGE)
        elif given == "mode":
            keys[index] = TklDeckKey(type=K.MODE)
        elif given == "next":
            keys[index] = TklDeckKey(type=K.NEXT)
    return keys


def _cells(f: Frame) -> tuple[list[int], dict[int, TklDeckKey]]:
    """The cells for the routes, and the keys a frame without them gets among its own cells:
    the offer on the small decks, and ▶ where the frame has no ▶ of its own."""
    area = list(f.area)
    extra: dict[int, TklDeckKey] = {}
    if "arrived" not in f.fixed and area:
        extra[area.pop()] = TklDeckKey(type=K.OFFER)
    if "page" not in f.fixed and "next" not in f.fixed and area:
        extra[area.pop()] = TklDeckKey(type=K.PAGE)
    return area, extra


_MADE: dict[str, TklDeckProfile] = {}
_LOCK = Lock()
KEPT: Final = 64


def build(grid: TklDeckGrid, model: DeckModelId | None, found: Sequence[Station]) -> TklDeckProfile:
    """The fjärrtågklarerare's profile for a grid, from the stations TKL controls: the same
    stations and grid always give the same profile, so that the deck keeps its state."""
    key = json.dumps(
        [
            grid.model_dump(mode="json"),
            model,
            [
                [s.place, s.name, s.code, [r.model_dump(mode="json") for r in s.routes]]
                for s in found
            ],
        ]
    )
    with _LOCK:
        known = _MADE.get(key)
    if known is not None:
        return known
    made = _built(grid, model, found)
    with _LOCK:
        if len(_MADE) >= KEPT:
            _MADE.clear()
        _MADE[key] = made
    return made


def _built(
    grid: TklDeckGrid, model: DeckModelId | None, found: Sequence[Station]
) -> TklDeckProfile:
    f = frame(grid)
    if f.style == DeckStyle.NONE:
        # Pedal: nothing until the owner chooses (SD55); no fjärr deck on a pedal.
        return TklDeckProfile(model=model, grid=grid, style=f.style, pedals=[None] * grid.pedals)
    b = Builder(f, Geography([], [], [], {}, {}, 1.0, (0.0, 0.0), (0.0, 0.0), {}, {}))
    fixed = _fixed(f)
    cells, extra = _cells(f)
    room = max(1, len(cells))
    for here in found:
        routes = list(here.routes)
        chunks = [routes[i : i + room] for i in range(0, len(routes), room)] or [[]]
        for n, chunk in enumerate(chunks, start=1):
            keys = dict(extra)
            for cell, route in zip(cells, chunk, strict=False):
                text, under = route_text(route)
                keys[cell] = TklDeckKey(
                    type=K.REMOTE_ROUTE, place=here.place, remote=route.id, text=text, under=under
                )
            name = here.name if len(chunks) == 1 else f"{here.name} {n}"
            b.page(name, MODE, DeckPageKind.REMOTE, keys, fixed=fixed)
    if not found:
        b.page(NOTHING_YET, MODE, DeckPageKind.REMOTE, dict(extra), fixed=fixed)
    return TklDeckProfile(
        model=model,
        grid=grid,
        style=f.style,
        fixed=sorted(f.fixed.values()),
        modes=[MODE],
        pages=b.pages,
    )


# --- the deck's state ----------------------------------------------------------------------------


def open_deck(settings: TklDeckSettings, profile: TklDeckProfile) -> Deck:
    """The deck opens on its start page when the profile has it, else on the first (SD35)."""
    deck = Deck(settings=settings, profile=profile, mode=MODE)
    named = next(
        (i for i, p in enumerate(profile.pages) if p.name == settings.opens_on),
        None,
    )
    deck.page = named or 0
    return deck


def carry(old: Deck, new: Deck) -> None:
    """The pages changed, a station taken or given back: the deck keeps what it said, the
    routes it waits for, and its page when the new profile has one of the same name; a station
    just taken opens on its first page."""
    new.message, new.accepted, new.said_at = old.message, old.accepted, old.said_at
    new.sent_routes = dict(old.sent_routes)
    names = [p.name for p in new.profile.pages]
    was = old.profile.pages[old.page].name if 0 <= old.page < len(old.profile.pages) else None
    if was in names:
        new.page = names.index(was)
        return
    known = {p.name for p in old.profile.pages}
    fresh = next((i for i, name in enumerate(names) if name not in known), None)
    new.page = fresh if fresh is not None else 0


def _page(deck: Deck) -> TklDeckPage | None:
    pages = deck.profile.pages
    return pages[deck.page] if 0 <= deck.page < len(pages) else None


def _turn(deck: Deck, step: int) -> None:
    count = len(deck.profile.pages)
    if count:
        deck.page = (deck.page + step) % count
    deck.overlay = None


def _route(world: RemoteWorld, key: TklDeckKey) -> RemoteRoute | None:
    place = world.place(key.place)
    if place is None or place.outside is None:
        return None
    return next((r for r in place.outside.remote_routes if r.id == key.remote), None)


def _asked(world: RemoteWorld, key: TklDeckKey) -> station.RemoteRouteHere | None:
    """The route as Hubben has it now: the latest ask for it that stands."""
    place = world.place(key.place)
    if place is None:
        return None
    standing = (station.RemoteRouteState.REQUESTED, station.RemoteRouteState.LOCKED)
    return next(
        (r for r in place.routes if r.route == key.remote and r.state in standing),
        None,
    )


def _locked(world: RemoteWorld, key: TklDeckKey) -> bool:
    """Locked in the station's interlocking, as its route.state says (FR13)."""
    place = world.place(key.place)
    state = place.route_state if place is not None else None
    return state is not None and any(r.route == key.remote for r in state.locked)


def _where(deck: Deck, place: str, route: str) -> tuple[int, int] | None:
    """The page and cell of a route's key, the current page first."""
    pages = list(enumerate(deck.profile.pages))
    pages.sort(key=lambda found: found[0] != deck.page)
    for number, page in pages:
        for cell, key in enumerate(page.keys):
            if (
                key is not None
                and key.type == K.REMOTE_ROUTE
                and (key.place, key.remote)
                == (
                    place,
                    route,
                )
            ):
                return number, cell
    return None


def reason_text(reason: Reason | str | None, message: str | None = None) -> str:
    if message:
        return message
    if reason is None:
        return "Nej."
    try:
        return TEXT_SV.get(Reason(reason), str(reason))
    except ValueError:
        return str(reason)


def _refused(deck: Deck, world: RemoteWorld, place: str, route: str, said: str) -> None:
    """A no on the route's key for three seconds (SD18), and in the deck's message."""
    deck.message, deck.accepted, deck.said_at = said, False, world.now
    found = _where(deck, place, route)
    if found is None:
        return
    number, cell = found
    key = deck.profile.pages[number].keys[cell]
    text = key.text if key is not None else ""
    deck.flash[cell] = Flash(world.now + FLASH_SECONDS, text, look.short(said), number)


def observe(deck: Deck, world: RemoteWorld) -> None:
    """The stations' answers to the routes this deck asked for: a no stands on the key with the
    station's reason for three seconds; an answer of any kind ends the wait."""
    if world.fjarr is None:
        return
    for request, (place, route) in list(deck.sent_routes.items()):
        found = world.place(place)
        if found is None:
            continue
        asked = next((r for r in found.routes if r.request_id == request), None)
        if asked is None or asked.state == station.RemoteRouteState.REQUESTED:
            continue
        del deck.sent_routes[request]
        deck.revision += 1
        if asked.state == station.RemoteRouteState.REFUSED:
            _refused(deck, world, place, route, reason_text(asked.reason, asked.message))


# --- what a press does ---------------------------------------------------------------------------


def press(
    deck: Deck, world: RemoteWorld, hands: RemoteHands, index: int, hold: bool = False
) -> None:
    """A press or a hold on the fjärrtågklarerare's deck."""
    if world.locked or world.fjarr is None:
        return
    observe(deck, world)
    deck.revision += 1
    if deck.overlay is not None:
        _press_overlay(deck, index)
        return
    page = _page(deck)
    key = page.keys[index] if page is not None and index < len(page.keys) else None
    if key is None:
        return
    match key.type:
        case K.REMOTE_ROUTE:
            _press_route(deck, world, hands, key, hold)
        case K.OFFER:
            _press_offer(deck, world, hands, hold)
        case K.PAGE:
            _turn(deck, 1)
        case K.NEXT:
            if hold:
                deck.chosen_route = None
                deck.overlay = Overlay("pages")
            else:
                _turn(deck, 1)
        case K.MODE:
            # Läge: a chosen route is dropped first; else the pages, one key each.
            if deck.chosen_route is not None:
                deck.chosen_route = None
                deck.message, deck.accepted = "Valet är borttaget.", True
            else:
                deck.overlay = Overlay("pages")
        case K.ACTION if key.action == A.CANCEL:
            deck.chosen_route = None
            deck.message, deck.accepted = "Valet är borttaget.", True
        case _:
            return


def _press_overlay(deck: Deck, index: int) -> None:
    """Läge's pages: a page's key opens it; Läge, ▶ or an empty key goes back."""
    pages = _overlay_pages(deck)
    chosen = pages.get(index)
    deck.overlay = None
    if chosen is not None:
        deck.page = chosen


def _press_route(
    deck: Deck, world: RemoteWorld, hands: RemoteHands, key: TklDeckKey, hold: bool
) -> None:
    place, route_id = key.place or "", key.remote or ""
    route = _route(world, key)
    if route is None or not world.controls(place):
        _refused(deck, world, place, route_id, NOT_MINE)
        return
    asked = _asked(world, key)
    me = world.fjarr.client_id if world.fjarr is not None else None
    if hold:
        # Ta bort: a route TKL asked for and that stands is taken away (route.cancel).
        if asked is None or asked.by != me:
            _refused(deck, world, place, route_id, "Tågvägen är inte lagd härifrån.")
            return
        said = hands.command(place, station.Action.ROUTE_CANCEL, {"request_id": asked.request_id})
        deck.chosen_route = None
        if said.accepted:
            deck.message, deck.accepted, deck.said_at = (
                f"{route_said(route)} tas bort.",
                True,
                world.now,
            )
        else:
            _refused(deck, world, place, route_id, said.message)
        return
    if asked is not None or _locked(world, key):
        _refused(deck, world, place, route_id, TEXT_SV[Reason.ROUTE_ALREADY_REQUESTED])
        return
    if deck.chosen_route != (place, route_id):
        # The first press chooses: the key blinks until the press is repeated (SD37, FR13).
        deck.chosen_route = (place, route_id)
        deck.message = f"{route_said(route)} blinkar. Tryck igen för att lägga den."
        deck.accepted, deck.said_at = True, world.now
        return
    deck.chosen_route = None
    request = f"sd-{token_hex(6)}"
    said = hands.command(
        place, station.Action.ROUTE_REQUEST, {"request_id": request, "route": route_id}
    )
    if not said.accepted:
        _refused(deck, world, place, route_id, said.message)
        return
    deck.sent_routes[request] = (place, route_id)
    deck.message = f"{route_said(route)} är begärd. Väntar på stationens ställverk."
    deck.accepted, deck.said_at = True, world.now


def _press_offer(deck: Deck, world: RemoteWorld, hands: RemoteHands, hold: bool) -> None:
    """Erbjudande (FR8): a press takes the first station offered, a hold declines it."""
    offers = world.fjarr.offers if world.fjarr is not None else []
    if not offers:
        deck.message, deck.accepted, deck.said_at = "Ingen station erbjuds.", False, world.now
        return
    offer = offers[0]
    said = hands.command(offer.place, station.Action.PLACE_OFFER_ANSWER, {"accept": not hold})
    name = _name(world, offer.place)
    if said.accepted:
        done = f"{name} är tagen: den fjärrstyrs härifrån." if not hold else f"{name} är avböjd."
        deck.message, deck.accepted = done, True
    else:
        deck.message, deck.accepted = said.message, False
    deck.said_at = world.now


def dial(deck: Deck, world: RemoteWorld, turn: int) -> None:
    """A dial turns the pages (SD83)."""
    if world.locked or not turn:
        return
    deck.revision += 1
    _turn(deck, 1 if turn > 0 else -1)


def touch(deck: Deck, world: RemoteWorld, point: int) -> None:
    """Neo's touch points turn the pages (SD82)."""
    if world.locked:
        return
    deck.revision += 1
    _turn(deck, point)


# --- what the keys show --------------------------------------------------------------------------


def _name(world: RemoteWorld, place: str) -> str:
    found = world.place(place)
    return found.place.name if found is not None else place


def _overlay_pages(deck: Deck) -> dict[int, int]:
    """Läge's keys: every page, one key each, in the cells for the routes."""
    f = frame(deck.profile.grid)
    cells, _ = _cells(f)
    return dict(zip(cells, range(len(deck.profile.pages)), strict=False))


def _label(text: str) -> str:
    """What a screen reader says of a key: as much as a key's label holds."""
    return text if len(text) <= MOST else text[: MOST - 1] + "\N{HORIZONTAL ELLIPSIS}"


def route_face(deck: Deck, world: RemoteWorld, key: TklDeckKey) -> TklDeckFace:
    place = world.place(key.place)
    code = place.place.code if place is not None else ""
    label = f"{_name(world, key.place or '')}: tågväg {key.text}"
    if not world.controls(key.place) or _route(world, key) is None:
        return TklDeckFace(
            type="remote",
            text=key.text,
            top=code,
            under="styrs inte",
            bg=ROUTE_BG,
            fg=look.DIM_FG,
            dim=True,
            label=_label(f"{label}, styrs inte härifrån"),
        )
    if deck.chosen_route == (key.place, key.remote):
        return TklDeckFace(
            type="remote",
            text=key.text,
            top=code,
            under="tryck igen",
            bg=look.BLUE,
            fg="#ffffff",
            frame=look.LIGHT_BLUE,
            blink="#0b1220",
            label=_label(f"{label}, vald: tryck igen för att lägga den"),
        )
    if _locked(world, key):
        return TklDeckFace(
            type="remote",
            text=key.text,
            top=code,
            under="låst",
            bg=look.GREEN,
            fg="#ffffff",
            band=look.GREEN_BAND,
            label=_label(f"{label}, låst"),
        )
    asked = _asked(world, key)
    if asked is not None:
        return TklDeckFace(
            type="remote",
            text=key.text,
            top=code,
            under="begärd",
            bg=WAITING_BG,
            fg="#ffffff",
            blink=WAITING_BLINK,
            label=_label(f"{label}, begärd: väntar på stationen"),
        )
    return TklDeckFace(
        type="remote",
        text=key.text,
        top=code,
        under=key.under,
        bg=ROUTE_BG,
        fg=ROUTE_FG,
        label=_label(label),
    )


def offer_face(world: RemoteWorld) -> TklDeckFace:
    offers = world.fjarr.offers if world.fjarr is not None else []
    if not offers:
        return TklDeckFace(
            type="offer",
            text="Erbj.",
            under="inga",
            bg="#111827",
            fg=look.TAB_FG,
            dim=True,
            label="Inga stationer erbjuds",
        )
    offer = offers[0]
    name = _name(world, offer.place)
    left = f"{offer.expires_in // 60}:{offer.expires_in % 60:02d}"
    more = f" +{len(offers) - 1}" if len(offers) > 1 else ""
    return TklDeckFace(
        type="offer",
        text=name[:MOST],
        top=f"erbjuden{more}",
        under=f"ta emot · {left}",
        bg=OFFER_BG,
        fg="#ffffff",
        blink=OFFER_BLINK,
        label=_label(f"{name} erbjuds, {left} kvar: tryck tar emot, håll avböjer"),
    )


def face(deck: Deck, world: RemoteWorld, key: TklDeckKey | None) -> TklDeckFace:
    if key is None:
        return look.EMPTY
    pages = deck.profile.pages
    match key.type:
        case K.REMOTE_ROUTE:
            return route_face(deck, world, key)
        case K.OFFER:
            return offer_face(world)
        case K.ACTION if key.action == A.CLOCK:
            return look.clock(world.time, world.name)
        case K.ACTION if key.action == A.CANCEL:
            chosen = deck.chosen_route is not None
            return TklDeckFace(
                type="action",
                text="Avbryt",
                bg="#374151" if chosen else "#111827",
                fg="#ffffff" if chosen else look.TAB_FG,
                dim=not chosen,
                label="Avbryt valet",
            )
        case K.PAGE | K.NEXT:
            page = _page(deck)
            return TklDeckFace(
                type="page" if key.type == K.PAGE else "next",
                text="\N{BLACK RIGHT-POINTING TRIANGLE}",
                under=f"{deck.page + 1}/{len(pages)}" if pages else "",
                bg=look.TAB_BG,
                fg="#ffffff",
                label=_label(f"Nästa sida, nu {page.name if page else ''}"),
            )
        case K.MODE:
            return TklDeckFace(
                type="mode",
                text="Läge",
                under="Fjärr" if deck.chosen_route is None else "avbryt",
                bg=look.TAB_BG,
                fg="#ffffff",
                label="Läge: sidorna",
            )
        case _:
            return look.EMPTY


def keys(deck: Deck, world: RemoteWorld) -> list[TklDeckFace]:
    grid = deck.profile.grid
    size = grid.columns * grid.rows
    if world.locked:
        faces = [look.EMPTY] * size
        if size:
            faces[0] = look.clock(world.time, world.name)
        return faces
    if deck.blink_until > world.now:
        return [look.here(deck.settings.name or "") for _ in range(size)]
    if world.fjarr is None:
        return [look.no_contact() for _ in range(size)]
    page = _page(deck)
    if page is None:
        return [look.EMPTY] * size
    faces = [face(deck, world, k) for k in page.keys]
    if deck.overlay is not None:
        faces = [look.EMPTY] * size
        for cell, number in _overlay_pages(deck).items():
            faces[cell] = look.tab(deck.profile.pages[number].name, "Fjärr", number == deck.page)
        for i, k in enumerate(page.keys):
            if k is not None and k.type in (K.MODE, K.NEXT):
                faces[i] = TklDeckFace(
                    type="mode", text="Tillbaka", bg=look.TAB_BG, fg="#ffffff", label="Tillbaka"
                )
        return faces
    for index, flash in deck.flash.items():
        if flash.until > world.now and flash.page == deck.page and index < size:
            faces[index] = look.refused(flash.text, flash.reason)
    return faces


def view(deck: Deck, world: RemoteWorld) -> TklDeckView:
    """Every key's face, the info line and how soon to read again."""
    observe(deck, world)
    page = _page(deck)
    faces = keys(deck, world)
    waiting = deck.chosen_route is not None or bool(deck.sent_routes)
    flashing = [f.until for f in deck.flash.values() if f.until > world.now]
    if deck.blink_until > world.now:
        flashing.append(deck.blink_until)
    refresh = WAITING_MS if waiting else RESTING_MS
    if flashing:
        refresh = min(refresh, int(max(200, (min(flashing) - world.now) * 1000 + 50)))
    said = ""
    if deck.accepted is False and deck.message and world.now - deck.said_at < FLASH_SECONDS:
        said = deck.message[:60]
    grid = deck.profile.grid
    info = ""
    if grid.info:
        info = said or f"{world.time} · {page.name if page else ''}".strip(" ·")
    return TklDeckView(
        settings=deck.settings,
        revision=deck.revision,
        style=deck.profile.style,
        modes=[MODE],
        mode=MODE,
        page=page.name if page is not None else "",
        keys=faces,
        fixed=deck.profile.fixed,
        info=info[:60],
        strip=[],
        hold_ms=HOLD_MS[deck.settings.hold],
        refresh_ms=refresh,
        locked=world.locked,
        contact=world.fjarr is not None,
        message=deck.message,
        accepted=deck.accepted,
        said=said if grid.strip else "",
    )
