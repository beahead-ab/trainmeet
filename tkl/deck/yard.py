"""Bangård (#87 del d): the shunter's deck, what its keys show and what a press does.

A deck with a part's role has the mode Bangård only (SD74): the part's tracks, its routes out,
Ände, Lämna, Klart, Ring and the train key for Klart att skicka (SD60, SD61, SD86, SD87). Every
press goes through the interlocking's own part operations, through `YardHands`: lay a switch
street, request a route out, return it, Klart, Grindar, Ring, Fika and Klart att skicka. The
interlocking says yes or no (SD1, STV-43); the deck keeps only which end is chosen, whether
Lämna waits for a track, and which train the train key shows.

What a key shows is read from the part as the interlocking shows it (TklInterlocking.parts):

- a street or a route out that cannot go now is dimmed with the mark and the reason (SD17);
- a request that waits for the station blinks, and an approved one is green;
- a no, from the interlocking at once (RANG-10) or the station's Neka, stands on the key with
  the reason for three seconds (SD18);
- while the part has fika, every key shows the cup, and a press brings the shunter back.

The train key shows the next train that by the plan departs from the part, from the same list as
/stallverk/parts/{id}/trains (TKL108, TKL110): a press announces it Klart att skicka, a hold
shows the next one (SD60).

Pure Python without I/O. No code here names a station (RS13).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from contracts.station_model import PartSide
from contracts.tkl import (
    DeckAction,
    DeckDial,
    DeckKeyType,
    DeckPageKind,
    TklDeckFace,
    TklDeckKey,
    TklDeckPage,
    TklDeckStrip,
    TklPartRequestState,
    TklPartRouteOut,
    TklPartShown,
    TklPartStreet,
    TklPartTrain,
)
from tkl.deck import look

if TYPE_CHECKING:
    from tkl.deck.logic import Deck, Hands, Said, World

K = DeckKeyType
A = DeckAction
ACTIONS: Final = frozenset(
    {A.GIVE_BACK, A.DONE, A.RING, A.GATES, A.HORN, A.FIKA, A.CLOCK, A.REQUESTS}
)
"""The shunter's actions (SD61, RANG-04). Kör is the shunter's too on a part's deck."""
KEYS: Final = frozenset({K.END, K.STREET, K.REQUEST, K.READY})
"""The shunter's keys (SD60, SD61, SD86)."""
ON_A_PARTS_DECK: Final = KEYS | frozenset({K.ACTION, K.MODE, K.NEXT, K.PAGE})
"""What a key on a part's deck may be: the shunter's, the actions and the navigation."""
END_WORD: Final = {PartSide.LEFT: "vänster", PartSide.RIGHT: "höger"}
APPROVED: Final = TklPartRequestState.APPROVED
WAITING: Final = TklPartRequestState.WAITING
STREET_BG: Final = "#1e293b"
STREET_LAID: Final = "#0369a1"
STREET_FG: Final = "#f0f9ff"
STREET_FRAME: Final = "#38bdf8"
REQUEST_FRAME: Final = "#a78bfa"
REQUEST_OWNED: Final = "#c4b5fd"
WAITING_BG: Final = "#422006"
WAITING_BLINK: Final = "#ca8a04"
HINDERED_BG: Final = "#191d21"
HINDERED_FG: Final = "#98a2ad"
READY_BG: Final = "#1d1a0b"
READY_FG: Final = "#fde68a"
READY_FRAME: Final = "#f5c518"
FIKA_BG: Final = "#1c1917"
FIKA_FG: Final = "#fef3c7"
NO_PART: Final = "Decket kan inte styra delen här."


@runtime_checkable
class YardHands(Protocol):
    """What the shunter's deck may do: the interlocking's own part operations (#87 del a)."""

    def part_street(self, part: str, street: str) -> Said: ...
    def part_request(self, part: str, route_out: str) -> Said: ...
    def part_return(self, part: str, request: int) -> Said: ...
    def part_done(self, part: str) -> Said: ...
    def part_gates(self, part: str) -> Said: ...
    def part_ring(self, part: str) -> Said: ...
    def part_fika(self, part: str, on: bool) -> Said: ...
    def part_ready(self, part: str, train: TklPartTrain) -> Said: ...


# --- what the deck reads ------------------------------------------------------------------------


def part_of(deck: Deck, world: World) -> TklPartShown | None:
    """The deck's part as the interlocking shows it."""
    wanted = deck.profile.part
    if wanted is None or world.interlocking is None:
        return None
    return next((p for p in world.state.parts if p.id == wanted), None)


def side_of(deck: Deck, key: TklDeckKey) -> PartSide:
    """The end a key acts on: its own, else the one Ände has chosen (SD86)."""
    return key.side or deck.end


def street_of(part: TklPartShown, track: str | None, side: PartSide) -> TklPartStreet | None:
    """The switch street to a track from an end: the end's own, else one of both ends."""
    found = [s for s in part.streets if s.track == track]
    return next((s for s in found if s.side == side), None) or next(
        (s for s in found if s.side is None), None
    )


def out_of(part: TklPartShown, track: str | None, side: PartSide) -> TklPartRouteOut | None:
    """The route out to a track from an end: the end's own, else one of both ends."""
    found = [r for r in part.routes_out if r.track == track]
    return next((r for r in found if r.side == side), None) or next(
        (r for r in found if r.side is None), None
    )


def at_end(part: TklPartShown, side: PartSide) -> tuple[list[TklPartStreet], list[TklPartRouteOut]]:
    """The streets and the routes out at an end: those of the end and those of both."""
    streets = [s for s in part.streets if s.side in (side, None)]
    outs = [r for r in part.routes_out if r.side in (side, None)]
    return streets, outs


def trains(deck: Deck, world: World) -> list[TklPartTrain]:
    """The trains the train key steps through, in the plan's order: those not yet announced
    Klart att skicka (SD60)."""
    ready = {r.number for r in world.state.ready} if world.interlocking is not None else set()
    return [t for t in world.part_trains or [] if t.number not in ready]


def train_now(deck: Deck, world: World) -> tuple[TklPartTrain | None, int, int]:
    """The train the train key shows, its place in the list and how many there are."""
    found = trains(deck, world)
    if not found:
        return None, 0, 0
    at = deck.train_at % len(found)
    return found[at], at, len(found)


def _out_text(route: TklPartRouteOut, key: TklDeckKey | None = None) -> str:
    """A route out on its key (SD61): the track on a key that follows Ände, else the route's
    name, so that the two columns of XL say which end each key is (SD87)."""
    if route.side is not None and (key is None or key.side is None):
        return route.track
    return route.name


def has_fika(deck: Deck, world: World) -> bool:
    part = part_of(deck, world)
    return part is not None and part.fika


# --- the faces ----------------------------------------------------------------------------------


def face(deck: Deck, world: World, key: TklDeckKey) -> TklDeckFace:
    """A shunter's key as it is now."""
    part = part_of(deck, world)
    if key.type == K.END:
        return _end_face(deck)
    if part is None:
        return look.EMPTY
    match key.type:
        case K.STREET:
            return _street_face(deck, part, key)
        case K.REQUEST:
            return _request_face(deck, part, key)
        case K.READY:
            return _ready_face(deck, world)
    return look.EMPTY


def _end_face(deck: Deck) -> TklDeckFace:
    """Ände (SD86): which end is chosen, with an arrow towards it."""
    left = deck.end == PartSide.LEFT
    word = "Vänster" if left else "Höger"
    arrow = "\N{BLACK LEFT-POINTING TRIANGLE}" if left else "\N{BLACK RIGHT-POINTING TRIANGLE}"
    return TklDeckFace(
        type="end",
        top="Ände",
        text=word,
        under=f"{arrow} vald" if left else f"vald {arrow}",
        bg=look.TAB_ON,
        fg="#ffffff",
        line="#f8fafc",
        label=f"Ände: {word.lower()}",
    )


def _street_face(deck: Deck, part: TklPartShown, key: TklDeckKey) -> TklDeckFace:
    """A track (SD61): the street from the chosen end, laid, possible, or hindered with the
    reason (SD17)."""
    side = side_of(deck, key)
    track = key.track or ""
    street = street_of(part, key.track, side)
    if street is None:
        return TklDeckFace(
            type="street",
            text=track,
            under=f"inte från {END_WORD[side]}",
            bg=HINDERED_BG,
            fg=look.DIM_FG,
            dim=True,
            label=f"{track}: ingen växelgata från {END_WORD[side]} ände",
        )
    if street.laid:
        return TklDeckFace(
            type="street",
            text=track,
            under="ligger",
            bg=STREET_LAID,
            fg=STREET_FG,
            frame=STREET_FRAME,
            label=f"Växelgata {street.name} ligger",
        )
    if not street.possible:
        reason = street.reason or "Går inte nu."
        return TklDeckFace(
            type="street",
            text=track,
            under=look.short(reason),
            bg=HINDERED_BG,
            fg=HINDERED_FG,
            dot=look.DOT,
            dim=True,
            label=f"Växelgata {street.name}: {reason}",
        )
    return TklDeckFace(
        type="street",
        text=track,
        under=street.name,
        bg=STREET_BG,
        fg=STREET_FG,
        frame=STREET_FRAME,
        label=f"Växelgata {street.name} mot {street.track}",
    )


def _request_face(deck: Deck, part: TklPartShown, key: TklDeckKey) -> TklDeckFace:
    """A route out (SD61): free to request, waiting for the station, approved, or hindered
    with the reason (SD17)."""
    side = side_of(deck, key)
    route = out_of(part, key.track, side)
    if route is None:
        track = key.track or ""
        return TklDeckFace(
            type="request",
            text=track,
            under=f"inte från {END_WORD[side]}",
            bg=HINDERED_BG,
            fg=look.DIM_FG,
            dim=True,
            label=f"{track}: ingen väg ut från {END_WORD[side]} ände",
        )
    text = _out_text(route, key)
    if route.state == APPROVED:
        return TklDeckFace(
            type="request",
            text=text,
            under="lämna?" if deck.giving else "godkänd",
            bg=look.GREEN,
            fg="#ffffff",
            frame=REQUEST_OWNED,
            dashed=deck.giving,
            label=f"{route.name} godkänd"
            + (", tryck för att lämna tillbaka" if deck.giving else ""),
        )
    if route.state == WAITING:
        return TklDeckFace(
            type="request",
            text=text,
            under="väntar",
            bg=WAITING_BG,
            fg="#ffffff",
            frame=REQUEST_OWNED,
            blink=WAITING_BLINK,
            label=f"{route.name} begärd, väntar på svar",
        )
    if not route.possible:
        reason = route.reason or "Går inte nu."
        return TklDeckFace(
            type="request",
            text=text,
            under=look.short(reason),
            bg=HINDERED_BG,
            fg=HINDERED_FG,
            dot=look.DOT,
            dim=True,
            label=f"{route.name}: {reason}",
        )
    return TklDeckFace(
        type="request",
        text=text,
        under="begär",
        bg="#262b31",
        fg="#e5e7eb",
        frame=REQUEST_FRAME,
        label=f"Begär {route.name}",
    )


def _ready_face(deck: Deck, world: World) -> TklDeckFace:
    """The train key (SD60): the next train from the plan, with its track and departure."""
    train, at, count = train_now(deck, world)
    if train is None:
        return TklDeckFace(
            type="train",
            text="Tåg",
            under=(
                "ingen plan"
                if world.part_trains is None
                else "inga fler"
                if world.part_trains
                else "inga i planen"
            ),
            bg="#14181d",
            fg="#8b95a1",
            dim=True,
            label="Tåg: inga fler tåg i planen",
        )
    where = " · ".join(
        x for x in (f"spår {train.track}" if train.track else "", train.departure or "") if x
    )
    return TklDeckFace(
        type="train",
        top="klart att skicka",
        text=train.number,
        under=where or "ur planen",
        small=f"{at + 1}/{count}" if count > 1 else "",
        bg=READY_BG,
        fg=READY_FG,
        frame=READY_FRAME,
        label=f"Tåg {train.number}: anmäl klart att skicka",
    )


def action_face(deck: Deck, world: World, action: DeckAction | None) -> TklDeckFace:
    """Lämna, Klart, Ring, Grindar, Tuta, Fika, Klocka, Begär and Kör (SD61, RANG-04)."""
    part = part_of(deck, world)
    match action:
        case A.GIVE_BACK:
            approved = [r for r in part.requests if r.state == APPROVED] if part else []
            return TklDeckFace(
                type="action",
                text="Lämna",
                under="välj spår" if deck.giving else "tillbaka",
                bg="#a16207" if deck.giving else "#1f2937",
                fg="#fef3c7",
                dim=not approved and not deck.giving,
                label="Lämna: välj spåret" if deck.giving else "Lämna",
            )
        case A.DONE:
            return TklDeckFace(
                type="action",
                text="Klart",
                under="lämna tillbaka",
                bg="#14532d",
                fg="#dcfce7",
                label="Klart",
            )
        case A.RING:
            ringing = part is not None and part.rings is not None
            return TklDeckFace(
                type="action",
                text="Ring",
                under="ringer" if ringing else "tågklareraren",
                bg="#1e1b4b",
                fg="#c7d2fe",
                blink="#312e81" if ringing else None,
                label="Ringer tågklareraren" if ringing else "Ring tågklareraren",
            )
        case A.GATES:
            return TklDeckFace(
                type="action",
                text="Grindar",
                under="tillbaka",
                bg="#1e3a8a",
                fg="#dbeafe",
                label="Grindar",
            )
        case A.HORN:
            return TklDeckFace(type="action", text="Tuta", bg=FIKA_BG, fg=READY_FG, label="Tuta")
        case A.FIKA:
            return fika_key()
        case A.CLOCK:
            return look.clock(world.time, part.name if part is not None else world.station)
        case A.REQUESTS:
            return TklDeckFace(
                type="action",
                text="Begär",
                under="vägar ut",
                bg="#262b31",
                fg="#e5e7eb",
                frame=REQUEST_FRAME,
                label="Begär en väg ut",
            )
        case A.RUN:
            route = _runnable(deck, world)
            return TklDeckFace(
                type="action",
                text="Kör",
                under="bara i Prova" if world.drift else "senaste",
                bg="#052e16",
                fg="#86efac",
                dim=world.drift or route is None,
                label="Kör",
            )
    return look.EMPTY


def fika_key() -> TklDeckFace:
    """Fika: the part's own (RANG-04), not TKL's Lås for the whole station."""
    return TklDeckFace(
        type="fika", text="Fika", under="ta paus", bg=FIKA_BG, fg=FIKA_FG, label="Fika"
    )


def fika_faces(size: int) -> list[TklDeckFace]:
    """The deck dark with a cup while the shunter has fika: a press brings them back."""
    cup = TklDeckFace(
        type="fika",
        text="Fika",
        under="tryck: tillbaka",
        bg=FIKA_BG,
        fg="#a8a29e",
        label="Fika: tryck för att komma tillbaka",
    )
    return [cup] * size


def _runnable(deck: Deck, world: World) -> int | None:
    """Kör on the shunter's deck: the part's latest route with a train (SD28)."""
    if world.interlocking is None:
        return None
    found = [r for r in world.state.routes if r.part == deck.profile.part and r.train is not None]
    return found[-1].id if found else None


# --- the station's no, for three seconds on the key (SD18) ---------------------------------------


def observe(deck: Deck, world: World, page: TklDeckPage | None) -> None:
    """A request the deck saw waiting that the station refused: the key shows the reason for
    three seconds, as after the interlocking's own no (SD18)."""
    from tkl.deck.logic import FLASH_SECONDS, Flash

    part = part_of(deck, world)
    if part is None:
        return
    newest: datetime | None = part.refused[0].at if part.refused else None
    gone = {
        route: request
        for route, request in deck.waiting.items()
        if not any(r.id == request for r in part.requests)
    }
    if gone and newest is not None and newest != deck.refusal_seen:
        text = part.refused[0].text
        deck.message, deck.accepted, deck.said_at = text, False, world.now
        for cell, key in enumerate(page.keys if page is not None else []):
            if key is None or key.type != K.REQUEST:
                continue
            route = out_of(part, key.track, side_of(deck, key))
            if route is not None and route.id in gone:
                deck.flash[cell] = Flash(
                    world.now + FLASH_SECONDS, _out_text(route, key), look.short(text), deck.page
                )
    deck.refusal_seen = newest
    deck.waiting = {r.route_out: r.id for r in part.requests if r.state == WAITING}


# --- what a press does ------------------------------------------------------------------------


def _hands(deck: Deck, world: World, hands: Hands) -> YardHands | None:
    from tkl.deck.logic import _say

    if isinstance(hands, YardHands):
        return hands
    _say(deck, world, NO_PART)
    return None


def _part(deck: Deck, world: World) -> TklPartShown | None:
    from tkl.deck.logic import _say

    part = part_of(deck, world)
    if part is None:
        _say(deck, world, f"Delen {deck.profile.part or ''} finns inte i stationsmodellen.")
    return part


def back_from_fika(deck: Deck, world: World, hands: Hands) -> None:
    """Any key brings the shunter back from fika."""
    from tkl.deck.logic import _said

    found = _hands(deck, world, hands)
    part = part_of(deck, world)
    if found is not None and part is not None:
        _said(deck, world, found.part_fika(part.id, False), None, "Fika")


def press_key(
    deck: Deck, world: World, hands: Hands, key: TklDeckKey, index: int | None, hold: bool
) -> None:
    """A press, or a hold, on one of the shunter's keys."""
    from tkl.deck.logic import _said, _say

    if key.type == K.END:
        deck.end = PartSide.RIGHT if deck.end == PartSide.LEFT else PartSide.LEFT
        deck.giving = False
        _say(deck, world, f"Ände: {END_WORD[deck.end]}.")
        return
    part = _part(deck, world)
    found = _hands(deck, world, hands)
    if part is None or found is None:
        return
    side = side_of(deck, key)
    match key.type:
        case K.STREET:
            street = street_of(part, key.track, side)
            text = key.track or ""
            if deck.giving:
                _say(deck, world, "Lämna: välj vägen ut som ska lämnas tillbaka.")
                return
            if street is None:
                said = f"{part.name} har ingen växelgata till {text} från {END_WORD[side]} ände."
                _said(deck, world, _no(said), index, text)
                return
            _said(deck, world, found.part_street(part.id, street.id), index, text)
        case K.REQUEST:
            route = out_of(part, key.track, side)
            if route is None:
                text = key.track or ""
                said = f"{part.name} har ingen väg ut till {text} från {END_WORD[side]} ände."
                _said(deck, world, _no(said), index, text)
                return
            request_route(deck, world, found, part, route, index, hold, key)
        case K.READY:
            announce(deck, world, found, part, index, hold)


def request_route(
    deck: Deck,
    world: World,
    hands: YardHands,
    part: TklPartShown,
    route: TklPartRouteOut,
    index: int | None,
    hold: bool,
    key: TklDeckKey | None = None,
) -> None:
    """A route out (SD61, RANG-03, RANG-09): a free one is requested, and refused at once with
    the reason when it cannot go (RANG-10); a waiting one is taken back; an approved one is
    returned after Lämna, or with a hold, as in the prototype."""
    from tkl.deck.logic import _said, _say

    text = _out_text(route, key)
    if route.state == APPROVED and route.request is not None:
        if deck.giving or hold:
            deck.giving = False
            _said(deck, world, hands.part_return(part.id, route.request), index, text)
            return
        _say(
            deck,
            world,
            f"{route.name} ligger. Tryck Lämna och sedan spåret för att lämna tillbaka.",
        )
        return
    if deck.giving:
        deck.giving = False
        _say(deck, world, f"{route.name} är inte godkänd: det finns inget att lämna tillbaka.")
        return
    if route.state == WAITING and route.request is not None:
        _said(deck, world, hands.part_return(part.id, route.request), index, text)
        return
    _said(deck, world, hands.part_request(part.id, route.id), index, text)


def announce(
    deck: Deck, world: World, hands: YardHands, part: TklPartShown, index: int | None, hold: bool
) -> None:
    """The train key (SD60): a press announces the train Klart att skicka (TKL108); a hold shows
    the next one."""
    from tkl.deck.logic import _said, _say

    train, _, count = train_now(deck, world)
    if train is None:
        _say(deck, world, "Inga fler tåg i planen. Skriv tågnumret på delens skärm.")
        return
    if hold:
        deck.train_at = (deck.train_at + 1) % max(1, count)
        following, _, _ = train_now(deck, world)
        _say(deck, world, f"Nästa tåg: {following.number if following else ''}.")
        return
    said = _said(deck, world, hands.part_ready(part.id, train), index, train.number)
    if said.accepted:
        deck.train_at = 0


def press_action(
    deck: Deck, world: World, hands: Hands, page: TklDeckPage, action: DeckAction, index: int | None
) -> None:
    """Lämna, Klart, Ring, Grindar, Tuta, Fika, Klocka, Begär and Kör."""
    from tkl.deck.logic import _said, _say

    if action == A.CLOCK:
        _say(deck, world, f"Klockan är {world.time}.")
        return
    if action == A.REQUESTS:
        deck.giving = False
        _open_requests(deck, page)
        return
    if action == A.RUN:
        if world.drift:
            _say(deck, world, "Kör finns bara utanför en riktig träff (SD28).")
            return
        route = _runnable(deck, world)
        if route is None:
            _say(deck, world, "Ingen väg med tåg att köra.")
            return
        _said(deck, world, hands.step(route), index, "Kör")
        return
    if action == A.HORN:
        _said(deck, world, _yes("Tut!"), None, "Tuta")
        return
    part = _part(deck, world)
    found = _hands(deck, world, hands)
    if part is None or found is None:
        return
    match action:
        case A.GIVE_BACK:
            give_back(deck, world, found, part, page)
        case A.DONE:
            deck.giving = False
            _said(deck, world, found.part_done(part.id), index, "Klart")
        case A.RING:
            _said(deck, world, found.part_ring(part.id), index, "Ring")
        case A.GATES:
            _said(deck, world, found.part_gates(part.id), index, "Grindar")
        case A.FIKA:
            _said(deck, world, found.part_fika(part.id, True), index, "Fika")


def give_back(
    deck: Deck, world: World, hands: YardHands, part: TklPartShown, page: TklDeckPage
) -> None:
    """Lämna (SD61): the one approved route is returned at once; with several, the next press
    on a route out chooses it, and Lämna again lets it be. A small deck shows its routes out."""
    from tkl.deck.logic import _said, _say

    approved = [r for r in part.requests if r.state == APPROVED]
    if not approved:
        deck.giving = False
        _say(deck, world, "Ingen godkänd väg att lämna tillbaka.")
        return
    if len(approved) == 1 and not deck.giving:
        _said(deck, world, hands.part_return(part.id, approved[0].id), None, "Lämna")
        return
    deck.giving = not deck.giving
    if not deck.giving:
        _say(deck, world, "Lämna är avbrutet.")
        return
    _say(deck, world, "Välj vägen ut som ska lämnas tillbaka.")
    if not _requests_on(page):
        _open_requests(deck, page)


def _requests_on(page: TklDeckPage) -> bool:
    return any(k is not None and k.type == K.REQUEST for k in page.keys)


def _open_requests(deck: Deck, page: TklDeckPage) -> None:
    """The first page with the routes out: Begär's own, else the first that has them."""
    opens = next(
        (k.page for k in page.keys if k is not None and k.action == A.REQUESTS and k.page),
        None,
    )
    if opens is None:
        opens = next((i for i, p in enumerate(deck.profile.pages) if _requests_on(p)), None)
    if opens is not None and opens < len(deck.profile.pages):
        deck.page = opens


def next_page(deck: Deck, page: TklDeckPage) -> int | None:
    """▶ on a page of routes out that Begär opened: its next page, else back to Begär's."""
    pages = deck.profile.pages
    following = deck.page + 1
    if following < len(pages) and not pages[following].listed:
        return following
    return next(
        (
            i
            for i, p in enumerate(pages)
            if p.listed
            and p.kind == DeckPageKind.YARD
            and any(k is not None and k.action == A.REQUESTS for k in p.keys)
        ),
        None,
    )


def _no(text: str) -> Said:
    from tkl.deck.logic import Said

    return Said(False, text)


def _yes(text: str) -> Said:
    from tkl.deck.logic import Said

    return Said(True, text)


# --- the dials, the strip and the info line (SD82, SD83, SD87) -------------------------------


def strip_part(deck: Deck, world: World, what: DeckDial, at: int) -> TklDeckStrip | None:
    """What a Bangård dial stands on: the route out, the street or the train."""
    part = part_of(deck, world)
    if what not in (DeckDial.REQUEST, DeckDial.STREET, DeckDial.READY):
        return None
    if part is None:
        return TklDeckStrip(label="Del", value="–")
    if what == DeckDial.READY:
        train, _, _ = train_now(deck, world)
        if train is None:
            return TklDeckStrip(label="Tåg", value="Inga")
        return TklDeckStrip(
            label="Tåg", value=train.number, under=train.departure or (train.track or "")
        )
    if what == DeckDial.REQUEST:
        _, outs = at_end(part, deck.end)
        if not outs:
            return TklDeckStrip(label="Begär", value="–")
        route = outs[at % len(outs)]
        state = (
            "godkänd"
            if route.state == APPROVED
            else "väntar"
            if route.state == WAITING
            else "tryck: begär"
            if route.possible
            else look.short(route.reason)
        )
        return TklDeckStrip(label="Begär", value=route.name, under=state)
    streets, _ = at_end(part, deck.end)
    if not streets:
        return TklDeckStrip(label="Gata", value="–")
    street = streets[at % len(streets)]
    under = (
        "ligger" if street.laid else "tryck: lägg" if street.possible else look.short(street.reason)
    )
    return TklDeckStrip(label="Gata", value=street.name, under=under)


def dial(
    deck: Deck,
    world: World,
    hands: Hands,
    what: DeckDial,
    at: int,
    turn: int,
    pushed: bool,
) -> bool:
    """A Bangård dial: turn chooses, press does it (SD83, SD87). False when it is not one."""
    from tkl.deck.logic import _said

    if what not in (DeckDial.REQUEST, DeckDial.STREET, DeckDial.READY):
        return False
    if what == DeckDial.READY:
        if turn:
            deck.train_at = max(0, deck.train_at + turn)
        if pushed:
            part = _part(deck, world)
            found = _hands(deck, world, hands)
            if part is not None and found is not None:
                announce(deck, world, found, part, None, False)
        return True
    if not pushed:
        return True
    part = _part(deck, world)
    found = _hands(deck, world, hands)
    if part is None or found is None:
        return True
    streets, outs = at_end(part, deck.end)
    if what == DeckDial.REQUEST:
        if outs:
            request_route(deck, world, found, part, outs[at % len(outs)], None, False)
        return True
    if streets:
        street = streets[at % len(streets)]
        _said(deck, world, found.part_street(part.id, street.id), None, street.track)
    return True


def info(deck: Deck, world: World) -> str:
    """Neo's info line in Bangård: the clock, the page and the end, or Lämna's question."""
    from tkl.deck.logic import current

    if deck.giving:
        return f"{world.time}  Lämna: välj vägen ut"[:60]
    page = current(deck)
    name = page.name if page is not None else ""
    return f"{world.time}  {name} · {END_WORD[deck.end]} ände"[:60]


__all__ = [
    "ACTIONS",
    "KEYS",
    "ON_A_PARTS_DECK",
    "YardHands",
    "action_face",
    "at_end",
    "back_from_fika",
    "dial",
    "face",
    "fika_faces",
    "has_fika",
    "info",
    "next_page",
    "observe",
    "part_of",
    "press_action",
    "press_key",
    "strip_part",
    "trains",
]
