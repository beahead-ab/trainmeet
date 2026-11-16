"""Driftändringar on a meet package (DRIFT-41): the ten kinds, each giving a new package.

Drift lays them on the version that runs, at once; Planering takes them into the next version
when the planner says Ta med (4.4). Both do it here, the same way. Pure: no clock and no state.
A change that cannot be made raises ChangeError with the reason a person reads.

The package is copied shallowly: only the train, section or place a change touches is new, so a
change on a big meet costs little.
"""

from __future__ import annotations

from collections import deque
from itertools import pairwise
from statistics import median
from typing import Final

from contracts import drift as changes
from contracts.common import Weekday
from contracts.meet import Call, MeetPackage, PlaceKind, Section, Train
from contracts.reasons import Reason

DAY: Final = 86400
# An extra train from–to runs each section in the time the timetable's trains take, or this
# long where none runs it, and stands a minute at each place between.
DEFAULT_RUN: Final = 5 * 60
STOP: Final = 60


class ChangeError(Exception):
    def __init__(self, reason: Reason) -> None:
        self.reason = reason
        super().__init__(reason.value)


def _seconds(value: str) -> int:
    hours, minutes = map(int, value.split(":"))
    return 3600 * hours + 60 * minutes


def _clock(seconds: int) -> str:
    minutes = seconds % DAY // 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def times(call: Call) -> tuple[int | None, int | None]:
    """A call's arrival and departure in seconds from the train's first game day. A visit
    spanning midnight has one day offset, but two clock times."""
    base = call.day_offset * DAY
    arrival = _seconds(call.arrival) + base if call.arrival else None
    departure = _seconds(call.departure) + base if call.departure else None
    if arrival is not None and departure is not None and departure < arrival:
        departure += DAY
    return arrival, departure


def _with_times(call: Call, arrival: int | None, departure: int | None) -> Call:
    first = arrival if arrival is not None else departure
    if first is None:
        return call
    if first < 0 or (departure is not None and departure < 0) or first // DAY > 7:
        raise ChangeError(Reason.INVALID_TIME)
    return call.model_copy(
        update={
            "arrival": None if arrival is None else _clock(arrival),
            "departure": None if departure is None else _clock(departure),
            "day_offset": first // DAY,
        }
    )


def _in_order(calls: list[Call]) -> bool:
    previous: int | None = None
    for call in calls:
        for moment in times(call):
            if moment is None:
                continue
            if previous is not None and moment < previous:
                return False
            previous = moment
    return True


# --- Finding what a change points at ------------------------------------------------------------


def train(package: MeetPackage, train_id: str) -> Train:
    found = next((t for t in package.trains if t.id == train_id), None)
    if found is None:
        raise ChangeError(Reason.UNKNOWN_TRAIN)
    return found


def train_of_call(package: MeetPackage, call_id: str) -> tuple[Train, int]:
    for candidate in package.trains:
        for index, call in enumerate(candidate.calls):
            if call.id == call_id:
                return candidate, index
    raise ChangeError(Reason.UNKNOWN_CALL)


def _section(package: MeetPackage, section_id: str) -> Section:
    found = next((s for s in package.sections if s.id == section_id), None)
    if found is None:
        raise ChangeError(Reason.UNKNOWN_SECTION)
    return found


def _with_train(package: MeetPackage, new: Train) -> MeetPackage:
    return package.model_copy(
        update={"trains": [new if t.id == new.id else t for t in package.trains]}
    )


def _with_call(package: MeetPackage, call_id: str, **update: object) -> MeetPackage:
    owner, index = train_of_call(package, call_id)
    calls = list(owner.calls)
    calls[index] = calls[index].model_copy(update=update)
    return _with_train(package, owner.model_copy(update={"calls": calls}))


def _number_free(package: MeetPackage, number: str, days: list[Weekday], but: str) -> None:
    """Two trains with one number the same day are told apart by hand only (F9); a change
    never makes a new pair."""
    for other in package.trains:
        if other.id != but and other.number == number and set(other.days) & set(days):
            raise ChangeError(Reason.TRAIN_NUMBER_TAKEN)


# --- The ten kinds --------------------------------------------------------------------------------


def apply(package: MeetPackage, change: changes.DriftChange, change_id: str) -> MeetPackage:
    """The package with the change made. The change's id names an extra train."""
    match change:
        case changes.CancelTrain():
            train(package, change.train)
            return _without(package, change.train)
        case changes.ExtraTrain():
            if any(t.id == f"x-{change_id}" for t in package.trains):
                raise ChangeError(Reason.TRAIN_NUMBER_TAKEN)  # Already in, as a version took it.
            extra = _extra(package, change, f"x-{change_id}")
            _number_free(package, extra.number, extra.days, extra.id)
            return package.model_copy(update={"trains": [*package.trains, extra]})
        case changes.ChangeTimes():
            return _with_train(package, _times(train(package, change.train), change))
        case changes.ChangePlace():
            return _place(package, change)
        case changes.ChangeTrack():
            owner, index = train_of_call(package, change.call)
            place = next(p for p in package.places if p.id == owner.calls[index].place)
            if place.tracks and change.track not in {t.name for t in place.tracks}:
                raise ChangeError(Reason.UNKNOWN_TRACK)
            return _with_call(package, change.call, track=change.track)
        case changes.ChangeSectionTracks():
            section = _section(package, change.section)
            new = section.model_copy(update={"tracks": change.tracks})
            return package.model_copy(
                update={"sections": [new if s.id == new.id else s for s in package.sections]}
            )
        case changes.ChangeDays():
            found = train(package, change.train)
            _number_free(package, found.number, change.days, found.id)
            return _with_train(package, found.model_copy(update={"days": change.days}))
        case changes.ChangeNumber():
            found = train(package, change.train)
            _number_free(package, change.number, found.days, found.id)
            return _with_train(package, found.model_copy(update={"number": change.number}))
        case changes.NoStop():
            return _with_call(package, change.call, stops=change.stops)
        case changes.TrainNote():
            found = train(package, change.train)
            if change.call is None:
                return _with_train(package, found.model_copy(update={"note": change.text}))
            if change.call not in {c.id for c in found.calls}:
                raise ChangeError(Reason.UNKNOWN_CALL)
            return _with_call(package, change.call, note=change.text)
    raise ChangeError(Reason.UNKNOWN_ACTION)  # pragma: no cover - the union is closed


def _without(package: MeetPackage, train_id: str) -> MeetPackage:
    """The package without a train: out of its duties and its turns too, so that nothing
    points at a train that is gone."""
    return package.model_copy(
        update={
            "trains": [t for t in package.trains if t.id != train_id],
            "duties": [
                d.model_copy(update={"legs": [leg for leg in d.legs if leg.train != train_id]})
                for d in package.duties
            ],
            "turns": [
                t.model_copy(update={"trains": [x for x in t.trains if x != train_id]})
                for t in package.turns
            ],
        }
    )


def touches(package: MeetPackage, change: changes.DriftChange) -> tuple[set[str], set[str]]:
    """The trains and the sections a change touches, for the rule that it waits while one of
    them is out or has an open clearance (H38). A note and an extra train never wait."""
    match change:
        case (
            changes.CancelTrain()
            | changes.ChangeTimes()
            | changes.ChangeDays()
            | changes.ChangeNumber()
        ):
            return {change.train}, set()
        case changes.ChangeTrack() | changes.NoStop():
            return {train_of_call(package, change.call)[0].id}, set()
        case changes.ChangeSectionTracks():
            return set(), {change.section}
        case changes.ChangePlace() if change.section is not None:
            return set(), {change.section}
    return set(), set()


def _times(found: Train, change: changes.ChangeTimes) -> Train:
    calls = list(found.calls)
    if change.minutes:
        delta = change.minutes * 60
        ids = [c.id for c in calls]
        if change.from_call is not None and change.from_call not in ids:
            raise ChangeError(Reason.UNKNOWN_CALL)
        start = 0 if change.from_call is None else ids.index(change.from_call)
        for index in range(start, len(calls)):
            arrival, departure = times(calls[index])
            # From a call on: its arrival stays, its departure and everything after move.
            if index > start or change.from_call is None:
                arrival = None if arrival is None else arrival + delta
            departure = None if departure is None else departure + delta
            calls[index] = _with_times(calls[index], arrival, departure)
    for given in change.calls:
        found_at = next((i for i, c in enumerate(calls) if c.id == given.call), None)
        if found_at is None:
            raise ChangeError(Reason.UNKNOWN_CALL)
        update = {"arrival": given.arrival, "departure": given.departure}
        calls[found_at] = calls[found_at].model_copy(
            update={key: value for key, value in update.items() if value is not None}
        )
    if not _in_order(calls):
        raise ChangeError(Reason.INVALID_TIME)
    return found.model_copy(update={"calls": calls})


def _place(package: MeetPackage, change: changes.ChangePlace) -> MeetPackage:
    if change.section is not None:
        section = _section(package, change.section)
        update: dict[str, object] = {}
        if change.closed is not None:
            update["closed"] = change.closed
        if change.clearance_mode is not None:
            update["clearance_mode"] = change.clearance_mode
        new_section = section.model_copy(update=update)
        return package.model_copy(
            update={
                "sections": [new_section if s.id == section.id else s for s in package.sections]
            }
        )
    place = next((p for p in package.places if p.id == change.place), None)
    if place is None or place.kind == PlaceKind.HALT:
        raise ChangeError(Reason.UNKNOWN_PLACE)
    assert change.place_kind is not None  # The contract asks for it with a place.
    new_place = place.model_copy(update={"kind": PlaceKind(change.place_kind)})
    return package.model_copy(
        update={"places": [new_place if p.id == place.id else p for p in package.places]}
    )


# --- Extratåg (H12) ---------------------------------------------------------------------------


def _extra(package: MeetPackage, change: changes.ExtraTrain, train_id: str) -> Train:
    start = _seconds(change.departure)
    if change.copy_of is not None:
        source = train(package, change.copy_of)
        first = next(t for c in source.calls for t in times(c) if t is not None)
        delta = start - first
        moved = [
            _with_times(call, *(None if t is None else t + delta for t in times(call)))
            for call in source.calls
        ]
        return source.model_copy(
            update={
                "id": train_id,
                "number": change.number,
                "days": change.days or source.days,
                "calls": [
                    call.model_copy(update={"id": f"{train_id}-{index}", "note": None})
                    for index, call in enumerate(moved)
                ],
                "note": None,
                "source_ids": {},
            }
        )
    assert change.from_place is not None and change.to_place is not None  # The contract asks.
    places = _route(package, change.from_place, change.to_place)
    runs = _running_times(package)
    calls: list[Call] = []
    moment = start
    for index, place in enumerate(places):
        last = index == len(places) - 1
        arrival = None if index == 0 else moment
        departure = None if last else (moment if index == 0 else moment + STOP)
        calls.append(
            _with_times(
                Call(id=f"{train_id}-{index}", place=place),
                arrival,
                departure,
            )
        )
        if not last:
            assert departure is not None
            moment = departure + runs.get(frozenset((place, places[index + 1])), DEFAULT_RUN)
    return Train(
        id=train_id,
        number=change.number,
        days=change.days or list(Weekday),
        calls=calls,
    )


def _route(package: MeetPackage, start: str, end: str) -> list[str]:
    """The fewest sections from one place to another, over the sections that are open."""
    known = {p.id for p in package.places if p.kind != PlaceKind.HALT}
    if start not in known or end not in known:
        raise ChangeError(Reason.UNKNOWN_PLACE)
    nearby: dict[str, list[str]] = {}
    for section in package.sections:
        if section.closed:
            continue
        nearby.setdefault(section.place_a, []).append(section.place_b)
        nearby.setdefault(section.place_b, []).append(section.place_a)
    came: dict[str, str | None] = {start: None}
    queue = deque([start])
    while queue:
        here = queue.popleft()
        if here == end:
            break
        for there in sorted(nearby.get(here, [])):
            if there not in came:
                came[there] = here
                queue.append(there)
    if end not in came:
        raise ChangeError(Reason.NO_ROUTE)
    way = [end]
    while (before := came[way[-1]]) is not None:
        way.append(before)
    return list(reversed(way))


def _running_times(package: MeetPackage) -> dict[frozenset[str], int]:
    """How long the timetable's trains take over each section, the middle value."""
    sections = {frozenset((s.place_a, s.place_b)) for s in package.sections}
    halts = {p.id for p in package.places if p.kind == PlaceKind.HALT}
    seen: dict[frozenset[str], list[int]] = {}
    for found in package.trains:
        stops = [c for c in found.calls if c.place not in halts]
        for here, there in pairwise(stops):
            key = frozenset((here.place, there.place))
            left, came = times(here)[1], times(there)[0]
            if key in sections and left is not None and came is not None and came > left:
                seen.setdefault(key, []).append(came - left)
    return {key: int(median(values)) for key, values in seen.items()}
