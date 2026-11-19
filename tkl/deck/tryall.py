"""Prova alla knappar in Studio (#86 del c, SD47): every key of every page of one size, pressed
against an empty interlocking, and what each did.

Each key is pressed on a fresh interlocking made from the station model: a copy with no route set
and no train, never the live one, so that nothing the owner has set in Ställverket is touched and
nothing goes out to the layout or to Hubben. The deck's own logic presses it (tkl.deck.logic), so
the same code is tried as runs on the deck. A key that is done with a hold (Lös ut alla, Noll,
Nödutlösning, SD29) is held, and one that asks once more is pressed twice. The fixed row is
pressed once, not once per page.

Each key either did what it does (the interlocking said yes, or the deck chose a start, turned a
page or opened Läge), was refused with the interlocking's reason, or did nothing, with what the
deck said. Tågen's keys need Hubben (SD63): without it a train key does nothing, and says so.

A part's deck, Bangård (#87 del d), is tried the same way: its keys go through the
interlocking's own part operations on the copy, and Ände, Lämna and Begär say what they chose.

`Runner` runs it in the background with its progress, as Studio's Prova does (tkl/prova.py).

Pure Python without I/O. No code here names a station (RS13).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from contracts import station
from contracts.station_model import PartSide
from contracts.tkl import (
    DeckKeyType,
    DeckModelId,
    DeckTried,
    RouteKind,
    TklDeckKey,
    TklDeckKeyTried,
    TklDeckProfile,
    TklDeckProva,
    TklDeckRoute,
    TklDeckSettings,
    TklFunctionAction,
    TklPartTrain,
)
from tkl.deck import logic
from tkl.deck.deviations import HOLD_ONLY, cap, describe
from tkl.deck.places import Geography
from tkl.deck.profile import frame
from tkl.deck.trains import Daily
from tkl.stallverk import Interlocking, Outcome, Plant
from tkl.standard import RouteKind as EngineKind

K = DeckKeyType
YARD_FOLLOWS: Final = frozenset({K.STREET, K.REQUEST})
"""The shunter's keys that follow Ände when they have no end of their own (#87 del d)."""
MOST_RUNNING: Final = 4
"""At most this many stations try their keys at once: TKL in the cloud has many."""
NO_HUB: Final = "Prova alla knappar når inte Hubben: Tågen och klareringen provas i drift."
NOTHING_SAID: Final = {
    K.TRAIN: "Tågen kräver Hubben (SD63).",
    K.LINE: "Tågen kräver Hubben (SD63).",
    K.ALARM: "Inget väntar: larmet kommer från Hubben.",
    K.DAILY: "Inga Dagens vägar än: de kommer ur träffens tidtabell (SD23).",
    K.FAVOURITE: "Favoriter är tom än: den fylls med de vägar som läggs (SD24).",
    K.CELL: "Ingen signal i rutan.",
    K.PAN: "Utsnittet står redan där.",
    K.PAGE: "Lägets enda sida av det slaget.",
    K.NEXT: "Ingen annan sida.",
}
"""What a key that did nothing says, by type, when the deck itself said nothing."""


class Direct:
    """The interlocking's own functions on a copy of it, recorded: what a key asked for and
    what the interlocking said. Lås and Hubben's commands are only noted, never done."""

    def __init__(self, it: Interlocking) -> None:
        self.it = it
        self.said: list[logic.Said] = []

    def _said(self, outcome: Outcome) -> logic.Said:
        found = logic.Said(outcome.accepted, outcome.message)
        self.said.append(found)
        return found

    def set_route(self, start: str, end: str, kind: RouteKind | None) -> logic.Said:
        wanted = EngineKind(kind.value) if kind is not None else None
        return self._said(self.it.set_route(start, end, wanted))

    def release(self, route: int) -> logic.Said:
        return self._said(self.it.release(route))

    def step(self, route: int) -> logic.Said:
        return self._said(self.it.step(route))

    def arrive(self, route: int) -> logic.Said:
        return self._said(self.it.arrive(route))

    def function(self, name: str, on: bool) -> logic.Said:
        action = TklFunctionAction.ON if on else TklFunctionAction.OFF
        return self._said(self.it.function(name, action, None, confirm=False))

    def command(
        self,
        action: station.Action,
        payload: dict[str, object],
        revision: station.Revision | None,
    ) -> logic.Said:
        found = logic.Said(False, NO_HUB)
        self.said.append(found)
        return found

    def lock(self) -> logic.Said:
        found = logic.Said(True, "Lås låser TKL för hela stationen; i provet låses inget.")
        self.said.append(found)
        return found

    def reset(self) -> logic.Said:
        return self._said(self.it.reset(True))

    def emergency(self, route: int) -> logic.Said:
        return self._said(self.it.emergency_release(route, True))

    # --- the shunter's deck (#87 del d): the interlocking's part operations on the copy ------

    def part_street(self, part: str, street: str) -> logic.Said:
        return self._said(self.it.part_street(part, street))

    def part_request(self, part: str, route_out: str) -> logic.Said:
        return self._said(self.it.part_request(part, route_out))

    def part_return(self, part: str, request: int) -> logic.Said:
        return self._said(self.it.part_return(part, request))

    def part_done(self, part: str) -> logic.Said:
        return self._said(self.it.part_done(part))

    def part_gates(self, part: str) -> logic.Said:
        return self._said(self.it.part_gates(part))

    def part_ring(self, part: str) -> logic.Said:
        return self._said(self.it.part_ring(part))

    def part_fika(self, part: str, on: bool) -> logic.Said:
        return self._said(self.it.part_fika(part, on))

    def part_ready(self, part: str, train: TklPartTrain) -> logic.Said:
        found = self.it.part_ready(
            part, train.number, call=train.call, track=train.track, departure=train.departure
        )
        return self._said(found)


@dataclass(frozen=True)
class Pressed:
    """A key to press: its page, its cell, and the page's name."""

    page: int
    cell: int
    name: str
    key: TklDeckKey


def keys_of(profile: TklDeckProfile) -> list[Pressed]:
    """Every key of every page, the fixed row once; a pedal's three when it has them."""
    if profile.style.value == "none":
        return [Pressed(0, i, "Pedal", k) for i, k in enumerate(profile.pedals) if k is not None]
    fixed = set(frame(profile.grid).fixed.values())
    seen: set[tuple[int, str]] = set()
    found = []
    for p, page in enumerate(profile.pages):
        for cell, key in enumerate(page.keys):
            if key is None:
                continue
            if cell in fixed:
                mark = (cell, key.model_dump_json())
                if mark in seen:
                    continue
                seen.add(mark)
            found.append(Pressed(p, cell, page.name, key))
    return found


def _state(deck: logic.Deck, selection: logic.Selection) -> tuple[object, ...]:
    return (
        deck.mode,
        deck.page,
        deck.overlay,
        deck.origin,
        selection.point,
        selection.place,
        selection.kind,
        deck.end,
        deck.giving,
        deck.train_at,
    )


def _changed(deck: logic.Deck, selection: logic.Selection, world: logic.World) -> str:
    if deck.profile.part is not None and deck.message and deck.overlay is None:
        # The shunter's deck says what it chose: the end, Lämna or the page of routes out.
        return deck.message
    if selection.point is not None:
        targets = world.targets(selection.point)
        goals = len(targets.targets) if targets is not None else 0
        if not goals:
            return ""
        return f"Valde start {selection.point}: {goals} mål."
    if selection.place is not None:
        goals = len(logic.goals(deck, world, selection.place))
        name = next((p.name for p in deck.profile.places if p.id == selection.place), "")
        return f"Valde {name or selection.place}: {goals} mål." if goals else ""
    if deck.overlay is not None:
        return {
            "modes": "Visar lägena.",
            "pages": "Visar alla sidor.",
            "case": "Visar ärendet.",
        }.get(deck.overlay.kind, "Visar ett val.")
    page = logic.current(deck)
    return f"Visar sidan {page.name}." if page is not None else "Bytte sida."


def try_key(
    profile: TklDeckProfile,
    pressed: Pressed,
    plant: Plant,
    geo: Geography,
    favourites: list[TklDeckRoute] | None = None,
    daily: list[Daily] | None = None,
) -> TklDeckKeyTried:
    """One key pressed on an empty interlocking, and what it did (SD47). A key of the shunter's
    deck that follows Ände is tried from the left end, and from the right when it did not do
    anything there (#87 del d)."""
    found = _try_key(profile, pressed, plant, geo, favourites, daily, PartSide.LEFT)
    follows = pressed.key.type in YARD_FOLLOWS and pressed.key.side is None
    if follows and found.result != DeckTried.DID:
        right = _try_key(profile, pressed, plant, geo, favourites, daily, PartSide.RIGHT)
        if right.result == DeckTried.DID:
            return right
    return found


def _try_key(
    profile: TklDeckProfile,
    pressed: Pressed,
    plant: Plant,
    geo: Geography,
    favourites: list[TklDeckRoute] | None,
    daily: list[Daily] | None,
    end: PartSide,
) -> TklDeckKeyTried:
    it = Interlocking(plant)
    world = logic.World(
        plant=plant,
        geo=geo,
        interlocking=it,
        favourites=list(favourites or []),
        daily_kept=list(daily or []),
    )
    settings = TklDeckSettings(serial="prova", grid=profile.grid, model=profile.model)
    page = profile.pages[pressed.page] if pressed.page < len(profile.pages) else None
    deck = logic.Deck(
        settings=settings,
        profile=profile,
        mode=page.mode if page is not None else None,
        page=pressed.page,
        end=end,
    )
    selection = logic.Selection()
    key = pressed.key
    label = cap(describe(key))
    if page is not None:
        shown = logic.face(deck, selection, world, page, key)
        label = shown.label or shown.text or label
    hands = Direct(it)
    hold = (key.type == K.ACTION and key.action in HOLD_ONLY) or (
        key.press is None and key.hold in HOLD_ONLY
    )
    before = _state(deck, selection)
    times = 2 if key.confirm and not hold else 1
    for _ in range(times):
        logic.press_here(deck, selection, world, hands, pressed.cell, hold)
    result, said = _result(hands, deck, selection, world, key, before)
    return TklDeckKeyTried(
        page=pressed.page,
        page_name=pressed.name,
        cell=pressed.cell,
        label=label[:200] or "Knapp",
        result=result,
        said=said[:200],
    )


def _result(
    hands: Direct,
    deck: logic.Deck,
    selection: logic.Selection,
    world: logic.World,
    key: TklDeckKey,
    before: tuple[object, ...],
) -> tuple[DeckTried, str]:
    if hands.said:
        last = hands.said[-1]
        return (DeckTried.DID if last.accepted else DeckTried.REFUSED), last.message
    if _state(deck, selection) != before:
        said = _changed(deck, selection, world)
        if said:
            return DeckTried.DID, said
        start = selection.point or selection.place or ""
        return DeckTried.REFUSED, f"Inga mål från {start}."
    return DeckTried.NOTHING, deck.message or NOTHING_SAID.get(key.type, "Gjorde ingenting.")


@dataclass
class Job:
    """One station's run for one size: its progress and its results so far."""

    size: DeckModelId
    total: int
    started: datetime
    keys: list[TklDeckKeyTried] = field(default_factory=list)
    part: str | None = None
    """The part whose deck, Bangård, is tried (#87 del d); None for the tågklarerare's."""
    finished: datetime | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self.finished is None


class Busy(Exception):
    """Too many stations try their keys at once."""


class Runner:
    """Prova alla knappar in the background, one run per station, with the progress and the
    last results in memory."""

    def __init__(self, *, most: int = MOST_RUNNING) -> None:
        self.most = most
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def job(self, slot: str) -> Job | None:
        with self._lock:
            return self._jobs.get(slot)

    def start(
        self,
        slot: str,
        size: DeckModelId,
        profile: TklDeckProfile,
        plant: Plant,
        geo: Geography,
        favourites: list[TklDeckRoute],
        daily: list[Daily],
    ) -> Job:
        """A new run, unless one runs for the station: then that one."""
        with self._lock:
            running = self._jobs.get(slot)
            if running is not None and running.running:
                return running
            if sum(1 for j in self._jobs.values() if j.running) >= self.most:
                raise Busy()
            pressed = keys_of(profile)
            job = Job(size=size, total=len(pressed), started=datetime.now(UTC), part=profile.part)
            self._jobs[slot] = job

        def run() -> None:
            try:
                for one in pressed:
                    if job.stop.is_set():
                        break
                    job.keys.append(try_key(profile, one, plant, geo, favourites, daily))
            finally:
                job.finished = datetime.now(UTC)

        job.thread = threading.Thread(target=run, name=f"prova-knappar-{slot[:8]}", daemon=True)
        job.thread.start()
        return job

    def stop(self, slot: str) -> None:
        job = self.job(slot)
        if job is not None:
            job.stop.set()

    def close(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.stop.set()
        for job in jobs:
            if job.thread is not None:
                job.thread.join(timeout=5)


ORDER: Final = {DeckTried.REFUSED: 0, DeckTried.NOTHING: 1, DeckTried.DID: 2}


def view(
    job: Job | None,
    size: DeckModelId | None = None,
    part: str | None = None,
    *,
    any_part: bool = False,
) -> TklDeckProva:
    """Prova alla knappar as Studio shows it: the refused first, then those that did nothing.
    For one size and one role: the tågklarerare's deck, or a part's (#87 del d)."""
    if (
        job is None
        or (size is not None and job.size != size)
        or (not any_part and job.part != part)
    ):
        return TklDeckProva(
            size=size,
            part=part,
            message="Prova alla knappar trycker på varje knapp mot ett tomt ställverk.",
        )
    keys = list(job.keys)
    counted = {r: sum(1 for k in keys if k.result == r) for r in DeckTried}
    ordered = sorted(keys, key=lambda k: (ORDER[k.result], k.page, k.cell))
    if job.running:
        message = f"Provar knapp {len(keys)} av {job.total} …"
    elif len(keys) < job.total:
        message = f"Provet avbröts efter {len(keys)} av {job.total} knappar."
    elif counted[DeckTried.REFUSED]:
        message = f"{counted[DeckTried.REFUSED]} av {job.total} knappar fick nej av ställverket."
    else:
        message = f"Alla {job.total} knappar är provade."
    return TklDeckProva(
        size=job.size,
        part=job.part,
        running=job.running,
        done=len(keys),
        total=job.total,
        did=counted[DeckTried.DID],
        refused=counted[DeckTried.REFUSED],
        nothing=counted[DeckTried.NOTHING],
        keys=ordered,
        started=job.started,
        finished=job.finished,
        message=message,
    )


__all__ = ["Busy", "Direct", "Job", "Pressed", "Runner", "keys_of", "try_key", "view"]
