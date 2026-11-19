"""The decks of one TKL server (#86 del a): each deck's state of the moment, by its serial
number (SD35), the start shared at a workplace (SD36), and TKL's runtime data for the decks:
how often each route is set, the routes pinned on Favoriter and Dagens vägar (SD23, SD24,
SD48, SD49).

The deck on the screen and a real deck, over USB or WebHID, are the same here: a deck is opened
by its serial number with its model, or its grid when TKL does not know the model (SD53), and
then read, pressed, held, turned and touched through the logic (tkl.deck.logic). The room also
knows how each deck is connected now (SD50), and keeps the last view of each deck for a moment,
so that its pictures are drawn from it without reading the interlocking again (#86 del b).

Only routes are counted, never people (SD24). Dagens vägar are made again when the meet's
package changes version (SD23).

Studio (#86 del c): every deck gets the owner's profile of its size, the default with the
owner's deviations laid on (tkl.deck.deviations); its settings from Studio, Deck reach it with
its next view, and Blinka lights it for a moment so that the owner sees which one it is (SD46).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from contracts import station
from contracts.tkl import (
    DeckConnection,
    DeckModelId,
    Panel,
    RouteKind,
    TklDeckCount,
    TklDeckFavourites,
    TklDeckOpen,
    TklDeckProfile,
    TklDeckRoute,
    TklDeckSettings,
    TklDeckView,
)
from tkl.deck import logic
from tkl.deck.models import model_of, size_of
from tkl.deck.places import Geography
from tkl.deck.render import Picture
from tkl.deck.trains import Daily, daily
from tkl.stallverk import Plant
from tkl.standard import RouteKind as EngineKind
from tkl.store import TklStore

COUNTS: Final = "counts"
PINNED: Final = "pinned"
DAILY: Final = "daily"
SEP: Final = "\N{UNIT SEPARATOR}"
SEEN: Final = 90.0
"""A deck in a browser, WebHID or on the screen, counts as connected this long after it was last
heard; it waits for changes at most 25 seconds at a time. A deck over USB is connected until
the driver says it is gone."""
KEPT: Final = 2.0
"""The last view of a deck is used for its pictures at most this long, in seconds."""


@dataclass(frozen=True)
class Shown:
    """A deck's view, and the panel behind Spårplan's keys when it shows any."""

    view: TklDeckView
    picture: Picture | None = None


def settings_for(known: TklDeckSettings | None, serial: str, given: TklDeckOpen) -> TklDeckSettings:
    """A deck's settings when it is opened: its model or grid, its workplace, and its role
    when it is given."""
    model: DeckModelId | None
    if given.model is not None:
        model = given.model
        grid = model_of(given.model).grid
    else:
        assert given.grid is not None
        grid = given.grid
        model = size_of(grid)
    base = known or TklDeckSettings(serial=serial, grid=grid)
    update: dict[str, object] = {"model": model, "grid": grid}
    if given.workplace is not None:
        update["workplace"] = given.workplace
    if given.role is not None:
        # The deck on a part's screen opens in the part's role (#87 del d).
        update["role"] = given.role
    return base.model_copy(update=update)


class Room:
    """The decks' state of the moment, in memory: it is not kept over a restart, and a deck
    opens again in its mode (SD65)."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.decks: dict[tuple[str, str], logic.Deck] = {}
        self.selections: dict[tuple[str, str], logic.Selection] = {}
        self.signatures: dict[tuple[str, str], tuple[object, ...]] = {}
        self.panels: dict[str, Panel | None] = {}
        self.links: dict[tuple[str, str], tuple[DeckConnection, float]] = {}
        self.kept: dict[tuple[str, str], tuple[int, float, Shown]] = {}
        self.blinks: dict[tuple[str, str], float] = {}

    def panel(self, plant: Plant, make: Callable[[], Panel | None]) -> Panel | None:
        with self.lock:
            if plant.fingerprint not in self.panels:
                if len(self.panels) > 16:
                    self.panels.clear()
                self.panels[plant.fingerprint] = make()
            return self.panels[plant.fingerprint]

    def selection(self, slot: str, workplace: str) -> logic.Selection:
        with self.lock:
            return self.selections.setdefault((slot, workplace), logic.Selection())

    def deck(
        self,
        slot: str,
        settings: TklDeckSettings,
        profile: TklDeckProfile,
        world: logic.World,
    ) -> logic.Deck:
        """The deck's state, opened afresh when it is new or its profile changed."""
        with self.lock:
            key = (slot, settings.serial)
            found = self.decks.get(key)
            if found is None or found.profile is not profile:
                found = logic.open_deck(settings, profile, world)
                if key in self.decks:
                    found.revision = self.decks[key].revision + 1
                self.decks[key] = found
            elif found.settings != settings:
                # Studio, Deck changed it, or the deck itself did and it was kept (SD46).
                found.settings = settings
            found.blink_until = self.blinks.get(key, 0.0)
            return found

    def forget(self, slot: str, serial: str) -> None:
        with self.lock:
            self.decks.pop((slot, serial), None)
            self.kept.pop((slot, serial), None)

    # --- Blinka (SD46) ------------------------------------------------------------------------

    def blink(self, slot: str, serial: str, seconds: float = logic.BLINK_SECONDS) -> None:
        """The deck lights every key for a moment, so that the owner sees which one it is."""
        with self.lock:
            until = time.monotonic() + seconds
            self.blinks[(slot, serial)] = until
            found = self.decks.get((slot, serial))
            if found is not None:
                found.blink_until = until

    def blinking(self, slot: str, serial: str) -> bool:
        with self.lock:
            return self.blinks.get((slot, serial), 0.0) > time.monotonic()

    # --- how each deck is connected now (SD50) ---------------------------------------------

    def link(self, slot: str, serial: str, connection: DeckConnection) -> None:
        with self.lock:
            self.links[(slot, serial)] = (connection, time.monotonic())

    def heard(self, slot: str, serial: str) -> None:
        """A deck in a browser asked for something: it is still there."""
        with self.lock:
            found = self.links.get((slot, serial))
            if found is not None:
                self.links[(slot, serial)] = (found[0], time.monotonic())

    def unlink(self, slot: str, serial: str) -> None:
        with self.lock:
            self.links.pop((slot, serial), None)

    def connection(self, slot: str, serial: str) -> DeckConnection | None:
        with self.lock:
            found = self.links.get((slot, serial))
        if found is None:
            return None
        how, seen = found
        if how != DeckConnection.USB and time.monotonic() - seen > SEEN:
            return None
        return how

    # --- the last view, for the pictures (#86 del b) ---------------------------------------

    def keep(self, slot: str, serial: str, shown: Shown) -> None:
        with self.lock:
            found = self.decks.get((slot, serial))
            revision = found.revision if found is not None else 0
            lasts = min(KEPT, shown.view.refresh_ms / 1000)
            self.kept[(slot, serial)] = (revision, time.monotonic() + lasts, shown)

    def kept_view(self, slot: str, serial: str, revision: int) -> Shown | None:
        """The last view while it is new and nothing has changed since."""
        with self.lock:
            found = self.kept.get((slot, serial))
        if found is None or found[0] != revision or time.monotonic() >= found[1]:
            return None
        return found[2]

    def revision(self, slot: str, serial: str, signature: tuple[object, ...]) -> int:
        """The deck's revision for waiting: up one whenever what it shows may have changed,
        here or in the interlocking, the snapshot or the start at its workplace."""
        with self.lock:
            key = (slot, serial)
            found = self.decks.get(key)
            if found is None:
                return 0
            if self.signatures.get(key) != signature:
                self.signatures[key] = signature
                found.revision += 1
            return found.revision


# --- TKL's runtime data (SD49) ------------------------------------------------------------------


def _key(route: TklDeckRoute) -> str:
    return SEP.join((route.start, route.end, route.kind.value))


def _route(key: str) -> TklDeckRoute | None:
    parts = key.split(SEP)
    if len(parts) != 3 or parts[2] not in {k.value for k in RouteKind}:
        return None
    return TklDeckRoute(start=parts[0], end=parts[1], kind=RouteKind(parts[2]))


def count(store: TklStore, slot: str, routes: list[TklDeckRoute]) -> None:
    """Every route set is counted, part by part for a chain (TKL70): only routes."""
    if not routes:
        return

    def change(data: dict[str, object]) -> dict[str, object]:
        counted = data.get(COUNTS)
        counts: dict[str, int] = dict(counted) if isinstance(counted, dict) else {}
        for route in routes:
            counts[_key(route)] = int(counts.get(_key(route), 0)) + 1
        return {**data, COUNTS: counts}

    store.change_deck_drift(slot, change)


def pin(store: TklStore, slot: str, route: TklDeckRoute, pinned: bool) -> None:
    """Fäst på Stream Deck (SD48): a route onto Favoriter, or off it."""

    def change(data: dict[str, object]) -> dict[str, object]:
        given = data.get(PINNED)
        found = [k for k in given if isinstance(k, str)] if isinstance(given, list) else []
        key = _key(route)
        found = [k for k in found if k != key] + ([key] if pinned else [])
        return {**data, PINNED: found}

    store.change_deck_drift(slot, change)


def exists(plant: Plant) -> Callable[[TklDeckRoute], bool]:
    def check(route: TklDeckRoute) -> bool:
        kind = EngineKind(route.kind.value)
        if route.start not in plant.points or route.end not in plant.points:
            return False
        return bool(plant.candidates(kind, route.start, route.end))

    return check


def favourites(store: TklStore, slot: str, plant: Plant) -> TklDeckFavourites:
    """Favoriter (SD24, SD48): the pinned routes, then the most used."""
    data = store.deck_drift(slot)
    given = data.get(PINNED)
    pinned = [
        r
        for r in (
            _route(k) for k in (given if isinstance(given, list) else []) if isinstance(k, str)
        )
        if r is not None
    ]
    counted_raw = data.get(COUNTS)
    counted: dict[tuple[str, str, RouteKind], int] = {}
    listed: list[TklDeckCount] = []
    for key, n in counted_raw.items() if isinstance(counted_raw, dict) else []:
        route = _route(str(key))
        if route is None or not isinstance(n, int):
            continue
        counted[(route.start, route.end, route.kind)] = n
        listed.append(TklDeckCount(start=route.start, end=route.end, kind=route.kind, count=n))
    listed.sort(key=lambda c: (-c.count, c.start, c.end))
    shown = logic.favourites(pinned, counted, exists(plant))
    return TklDeckFavourites(pinned=pinned, counted=listed, shown=shown)


def counts(store: TklStore, slot: str) -> dict[tuple[str, str, RouteKind], int]:
    """How often each route has been set (SD24): Mest använda in Studio's Föreslå."""
    counted = store.deck_drift(slot).get(COUNTS)
    found: dict[tuple[str, str, RouteKind], int] = {}
    for key, n in counted.items() if isinstance(counted, dict) else []:
        route = _route(str(key))
        if route is not None and isinstance(n, int):
            found[(route.start, route.end, route.kind)] = n
    return found


def kept_daily(store: TklStore, slot: str) -> list[Daily]:
    """Dagens vägar as TKL's runtime data last kept them (SD23, SD49), whatever meet they were
    made for: Studio's Föreslå and Prova alla knappar use them without Hubben."""
    kept = store.deck_drift(slot).get(DAILY)
    listed = kept.get("routes") if isinstance(kept, dict) else None
    found = []
    for item in listed if isinstance(listed, list) else []:
        if isinstance(item, list) and len(item) == 5:
            found.append(
                Daily(str(item[0]), str(item[1]), str(item[2]), str(item[3]), bool(item[4]))
            )
    return found


def todays(
    store: TklStore,
    slot: str,
    snapshot: station.Snapshot | None,
    plant: Plant,
    geo: Geography,
) -> list[Daily]:
    """Dagens vägar (SD23), kept in TKL's runtime data for the meet's version and made again
    when it changes."""
    if snapshot is None:
        return []
    made_for = f"{snapshot.context.meet_id}{SEP}{snapshot.context.version}{SEP}{plant.fingerprint}"
    data = store.deck_drift(slot)
    kept = data.get(DAILY)
    found: list[Daily] = []
    if isinstance(kept, dict) and kept.get("for") == made_for:
        listed = kept.get("routes")
        for item in listed if isinstance(listed, list) else []:
            if isinstance(item, list) and len(item) == 5:
                found.append(
                    Daily(str(item[0]), str(item[1]), str(item[2]), str(item[3]), bool(item[4]))
                )
    known = {(d.origin, d.goal, d.number) for d in found}
    new = [d for d in daily(snapshot, plant, geo) if (d.origin, d.goal, d.number) not in known]
    if not new and found:
        return found
    found = sorted(found + new, key=lambda d: (d.time, not d.entry, d.number))

    def change(data: dict[str, object]) -> dict[str, object]:
        routes = [[d.origin, d.goal, d.number, d.time, d.entry] for d in found]
        return {**data, DAILY: {"for": made_for, "routes": routes}}

    store.change_deck_drift(slot, change)
    return found
