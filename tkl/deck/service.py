"""The decks of one TKL server (#86 del a): each deck's state of the moment, by its serial
number (SD35), the start shared at a workplace (SD36), and TKL's runtime data for the decks:
how often each route is set, the routes pinned on Favoriter and Dagens vägar (SD23, SD24,
SD48, SD49).

The deck on the screen and, in del b, a real deck over USB are the same here: a deck is opened
by its serial number with its model, or its grid when TKL does not know the model (SD53), and
then read, pressed, held, turned and touched through the logic (tkl.deck.logic).

Only routes are counted, never people (SD24). Dagens vägar are made again when the meet's
package changes version (SD23).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Final

from contracts import station
from contracts.tkl import (
    DeckModelId,
    Panel,
    RouteKind,
    TklDeckCount,
    TklDeckFavourites,
    TklDeckOpen,
    TklDeckProfile,
    TklDeckRoute,
    TklDeckSettings,
)
from tkl.deck import logic
from tkl.deck.models import model_of, size_of
from tkl.deck.places import Geography
from tkl.deck.trains import Daily, daily
from tkl.stallverk import Plant
from tkl.standard import RouteKind as EngineKind
from tkl.store import TklStore

COUNTS: Final = "counts"
PINNED: Final = "pinned"
DAILY: Final = "daily"
SEP: Final = "\N{UNIT SEPARATOR}"


def settings_for(known: TklDeckSettings | None, serial: str, given: TklDeckOpen) -> TklDeckSettings:
    """A deck's settings when it is opened: its model or grid, and its workplace."""
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
            elif (
                found.settings.workplace != settings.workplace
                or found.settings.grid != settings.grid
            ):
                found.settings = settings
            return found

    def forget(self, slot: str, serial: str) -> None:
        with self.lock:
            self.decks.pop((slot, serial), None)

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
