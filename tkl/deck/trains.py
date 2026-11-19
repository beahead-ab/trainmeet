"""The trains, the lines and what waits, for the page Nu, from Drift and the interlocking.

The train keys show a train from Drift and the timetable (SD7): what the hub's snapshot says
about it, and where the interlocking has its number. Its next step (SD8, SD10):

- väntas: planned, not yet on its way. A press sets the entry all the same (TKL71);
- lägg infart: on its way here, or standing on the line at the entry signal;
- infart lagd: the entry route is set for it; kör: it runs on a route;
- ankommit?: at levels 1–2 it stands at the end of its entry route (Ankommit, SD10). At level 3
  with LocoNet the arrival is the entry route released after the passage, so the step is not
  there: the train stands on its track;
- begär klart: it stands on its track; a press asks for clearance with TKL's clearance as it is
  (SD14). Without Hubben there is no clearance, and the step is lägg utfart;
- väntar på klart, then klart · lägg ut: the exit route is the next press;
- utfart lagd, and har lämnat, dimmed until it has arrived at the neighbour.

A train a part has announced ready to send (TKL108) is marked on its key, on the page Nu and
nowhere else (SD62, TKL111).

The order is what happens next first (port of cda-tkl's turn list, stream-deck-turns.test.mjs):
the trains the interlocking has, those on their way, those at the station, then the timetable's
in time order, and those that have left last. A train leaves the list when it is done, and the
track where a train stands wins over the planned one.

Dagens vägar (SD23): from the meet's timetable through the snapshot, the entry and the exit of
every train on its planned track, as pairs of places.

Pure Python without I/O, using only the contracts and the engine. No code here names a station
(RS13).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from contracts import station
from contracts.tkl import TklInterlocking, TklSetRoute
from tkl.deck.places import Geography
from tkl.stallverk import Plant

OPEN: Final = (station.ClearanceStatus.WAITING, station.ClearanceStatus.APPROVED)


class Step(StrEnum):
    WAITING = "vantas"
    COMING = "hit"
    ENTRY = "infart"
    RUNNING = "kor"
    ARRIVE = "ankommit"
    IN = "inne"
    ASKED = "begart"
    CLEARED = "klart"
    EXIT = "utfart"
    LEFT = "lamnat"


@dataclass(frozen=True)
class Turn:
    """A train on turn, with its next step."""

    number: str
    step: Step
    call: station.CallHere | None = None
    kind: str | None = None
    time: str = ""
    origin: str | None = None
    """The place it comes in at: an exit."""
    goal: str | None = None
    """The place it leaves at: an exit."""
    track: str | None = None
    """The track place where it stands or will stand."""
    planned: str | None = None
    route: int | None = None
    train: int | None = None
    clearance: station.Clearance | None = None
    section: str | None = None
    """The hub's section towards the next station, for asking clearance."""
    ready: bool = False
    """Klart att skicka (SD62, TKL111): a part has announced it ready to send."""


@dataclass(frozen=True)
class Line:
    """A line to a neighbour (SD13): from the snapshot's sections."""

    section: station.SectionHere
    code: str
    place: str | None
    asks: station.Clearance | None
    asked: station.Clearance | None
    coming: str | None
    left: str | None
    ask_for: station.CallHere | None


@dataclass(frozen=True)
class Case:
    """Something waiting on the alarm key (SD15): a neighbour's question, or a fault."""

    kind: str
    """"clearance" or "fault"."""
    top: str
    text: str
    under: str
    clearance: station.Clearance | None = None


@dataclass(frozen=True)
class Daily:
    """A route of Dagens vägar (SD23): from a place to a place, for a train."""

    origin: str
    goal: str
    number: str
    time: str
    entry: bool


def exit_place(
    snapshot: station.Snapshot, other: str | None, plant: Plant, geo: Geography
) -> str | None:
    """The place of the exit towards a neighbouring place, through the section's exit."""
    if other is None:
        return None
    for section in snapshot.sections:
        if section.other_place != other or section.exit is None:
            continue
        for exit_id, found in plant.exits.items():
            if found.outside == section.exit and exit_id in geo.exit_place:
                return geo.exit_place[exit_id]
    return None


def track_place(name: str | None, plant: Plant, geo: Geography) -> str | None:
    """The place of a track by the timetable's name for it: its id, its id in the outside, or
    its label."""
    if not name:
        return None
    for track in plant.model.station_tracks:
        names = {track.id, track.label, plant.track_outside.get(track.id, track.id)}
        if name in names and track.id in geo.track_place:
            return geo.track_place[track.id]
    return None


def _mine(snapshot: station.Snapshot, call: str) -> station.Clearance | None:
    here = snapshot.place.place
    return next(
        (
            c
            for c in snapshot.clearances
            if c.call == call and c.from_place == here and c.status in OPEN and not c.departed
        ),
        None,
    )


def _section_to(snapshot: station.Snapshot, other: str | None) -> str | None:
    return next((s.section for s in snapshot.sections if s.other_place == other), None)


def turns(
    state: TklInterlocking, snapshot: station.Snapshot | None, plant: Plant, geo: Geography
) -> list[Turn]:
    """The trains on turn, what happens next first, each marked when it is ready to send."""
    ready = {r.number for r in state.ready}
    return [
        replace(t, ready=True) if t.number in ready else t
        for t in _turns(state, snapshot, plant, geo)
    ]


def _turns(
    state: TklInterlocking, snapshot: station.Snapshot | None, plant: Plant, geo: Geography
) -> list[Turn]:
    calls = {c.train_number: c for c in snapshot.calls} if snapshot is not None else {}
    by_call = {c.call: c for c in snapshot.calls} if snapshot is not None else {}
    found: list[tuple[int, str, Turn]] = []
    seen: set[str] = set()
    for train in state.trains:
        call = by_call.get(train.call or "") or calls.get(train.number or "")
        number = train.number or (call.train_number if call else "")
        if not number:
            continue
        seen.add(number)
        found.append(
            (0, _time(call), _in_interlocking(state, train.id, call, snapshot, plant, geo))
        )
    if snapshot is None:
        return [t for _, _, t in sorted(found, key=lambda f: (f[0], f[1]))]
    coming = {t.call: t for t in snapshot.on_the_way}
    left = {t.call: t for t in snapshot.have_left}
    for call in snapshot.calls:
        if call.train_number in seen:
            continue
        origin = exit_place(snapshot, call.from_place, plant, geo)
        goal = exit_place(snapshot, call.to_place, plant, geo)
        planned = track_place(call.planned_track or call.track, plant, geo)
        track = track_place(call.track, plant, geo) or planned
        base = Turn(
            number=call.train_number,
            step=Step.WAITING,
            call=call,
            kind=call.train_label or call.train_type,
            time=_time(call),
            origin=origin,
            goal=goal,
            track=track,
            planned=planned,
            section=_section_to(snapshot, call.to_place),
        )
        if call.call in left:
            found.append((4, base.time, replace(base, step=Step.LEFT)))
        elif call.departure_state == station.DepartureState.DEPARTED:
            continue
        elif call.call in coming:
            on = coming[call.call]
            from_here = exit_place(snapshot, on.other_place, plant, geo) or origin
            found.append((1, base.time, replace(base, step=Step.COMING, origin=from_here)))
        elif call.arrival_state == station.ArrivalState.ARRIVED or (
            not call.from_place and call.positioned
        ):
            if not call.to_place:
                continue  # it ends here: nothing more on the deck
            found.append((2, base.time, _standing(base, snapshot, call)))
        else:
            found.append((3, base.time, base))
    return [t for _, _, t in sorted(found, key=lambda f: (f[0], f[1]))]


def _time(call: station.CallHere | None) -> str:
    if call is None:
        return ""
    arrived = call.arrival_state == station.ArrivalState.ARRIVED
    if call.arrival and not arrived:
        return call.arrival
    return call.departure or call.arrival or ""


def _standing(turn: Turn, snapshot: station.Snapshot | None, call: station.CallHere | None) -> Turn:
    """A train standing on its track: begär klart, väntar på klart, or klart · lägg ut."""
    if snapshot is None or call is None:
        return replace(turn, step=Step.CLEARED)
    clearance = _mine(snapshot, call.call)
    if clearance is not None and clearance.status == station.ClearanceStatus.APPROVED:
        return replace(turn, step=Step.CLEARED, clearance=clearance)
    if clearance is not None:
        return replace(turn, step=Step.ASKED, clearance=clearance)
    return replace(turn, step=Step.IN)


def _in_interlocking(
    state: TklInterlocking,
    train_id: int,
    call: station.CallHere | None,
    snapshot: station.Snapshot | None,
    plant: Plant,
    geo: Geography,
) -> Turn:
    train = next(t for t in state.trains if t.id == train_id)
    mine = [r for r in state.routes if r.train == train_id]
    number = train.number or (call.train_number if call else "")
    planned = track_place(call.planned_track or call.track, plant, geo) if call else None
    goal = exit_place(snapshot, call.to_place, plant, geo) if snapshot and call else None
    base = Turn(
        number=number,
        step=Step.WAITING,
        call=call,
        kind=(call.train_label or call.train_type) if call else None,
        time=_time(call),
        goal=goal,
        planned=planned,
        track=planned,
        train=train_id,
        section=_section_to(snapshot, call.to_place) if snapshot and call else None,
    )
    if train.exit is not None:
        origin = geo.exit_place.get(train.exit)
        waiting = next((r for r in mine if r.at < 0), None)
        if waiting is not None:
            return replace(base, step=Step.ENTRY, origin=origin, route=waiting.id)
        return replace(base, step=Step.COMING, origin=origin)
    track_id = plant.track_of.get(train.section or "")
    here = geo.track_place.get(track_id) if track_id else None
    base = replace(base, track=here or planned)
    moving = next((r for r in mine if r.at >= 0), None)
    if moving is not None:
        if moving.at < len(moving.sections) - 1 or moving.leaves is not None:
            return replace(base, step=Step.RUNNING, route=moving.id)
        if state.field is None:
            # Ankommit at levels 1–2, and at level 3 without LocoNet (SD10).
            return replace(base, step=Step.ARRIVE, route=moving.id)
    out = next((r for r in mine if r.at < 0), None)
    if out is not None:
        return replace(base, step=Step.EXIT, route=out.id)
    if call is None or snapshot is None:
        return replace(base, step=Step.CLEARED)
    return _standing(base, snapshot, call)


def route_of(state: TklInterlocking, route: int | None) -> TklSetRoute | None:
    return next((r for r in state.routes if r.id == route), None)


def lines(snapshot: station.Snapshot | None, plant: Plant, geo: Geography) -> list[Line]:
    """The lines to the neighbours, west first (SD13)."""
    if snapshot is None:
        return []
    here = snapshot.place.place
    found: list[Line] = []
    sections = sorted(snapshot.sections, key=lambda s: (str(s.side or ""), s.exit or "", s.section))
    for section in sections:
        neighbour = next((n for n in snapshot.neighbours if n.place == section.other_place), None)
        open_ = [
            c
            for c in snapshot.clearances
            if c.section == section.section and c.status == station.ClearanceStatus.WAITING
        ]
        asks = next((c for c in open_ if c.to_place == here), None)
        asked = next((c for c in open_ if c.from_place == here), None)
        coming = next(
            (t.train_number for t in snapshot.on_the_way if t.section == section.section), None
        )
        left = next(
            (t.train_number for t in snapshot.have_left if t.section == section.section), None
        )
        ask_for = next(
            (
                c
                for c in snapshot.calls
                if c.to_place == section.other_place
                and c.departure_state == station.DepartureState.PLANNED
                and (c.arrival_state == station.ArrivalState.ARRIVED or not c.from_place)
                and station.Action.CLEARANCE_REQUEST in c.allowed_actions
            ),
            None,
        )
        found.append(
            Line(
                section=section,
                code=neighbour.code if neighbour else section.other_code,
                place=exit_place(snapshot, section.other_place, plant, geo),
                asks=asks,
                asked=asked,
                coming=coming,
                left=left,
                ask_for=ask_for,
            )
        )
    return found


def cases(state: TklInterlocking, snapshot: station.Snapshot | None) -> list[Case]:
    """What waits on the alarm key, the oldest first (SD15): the neighbours' clearance
    questions and the faults. A train at the signal is on its train key, not here."""
    found: list[Case] = []
    if snapshot is not None:
        here = snapshot.place.place
        for c in sorted(snapshot.clearances, key=lambda c: c.requested_at):
            if c.to_place == here and c.status == station.ClearanceStatus.WAITING:
                neighbour = next((n for n in snapshot.neighbours if n.place == c.from_place), None)
                found.append(
                    Case(
                        kind="clearance",
                        top="klarering",
                        text=neighbour.code if neighbour else c.from_place,
                        under=f"frågar: {c.train_number}",
                        clearance=c,
                    )
                )
    if state.problem:
        found.append(Case(kind="fault", top="Fel", text="Ställverket", under=state.problem))
    for route in state.routes:
        if route.held:
            found.append(Case(kind="fault", top="Fel", text=route.start, under=route.held))
    return found


def daily(snapshot: station.Snapshot | None, plant: Plant, geo: Geography) -> list[Daily]:
    """Dagens vägar (SD23): the entry and the exit of every train on its planned track."""
    if snapshot is None:
        return []
    found: list[tuple[str, int, Daily]] = []
    for call in snapshot.calls:
        track = track_place(call.planned_track or call.track, plant, geo)
        if track is None:
            continue
        origin = exit_place(snapshot, call.from_place, plant, geo)
        goal = exit_place(snapshot, call.to_place, plant, geo)
        if origin is not None:
            time = call.arrival or call.departure or ""
            found.append((time, 0, Daily(origin, track, call.train_number, time, True)))
        if goal is not None:
            time = call.departure or call.arrival or ""
            found.append((time, 1, Daily(track, goal, call.train_number, time, False)))
    return [d for _, _, d in sorted(found, key=lambda f: (f[0], f[1], f[2].number))]
