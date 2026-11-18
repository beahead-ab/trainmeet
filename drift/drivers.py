"""Lokföraren in Drift (LOK-01–LOK-41): the services a driver chooses among, the körplan, where
the trains are, and what a driver or the dispatcher does about them.

A service is a duty from the meet package when the meet has duties, and otherwise a train with
its timetable (LOK-17, LOK-31). It has one driver at a time: the first to take it gets it, and a
driver has one service at a time (LOK-40). Trafikledningen and the lokledare hand services out
and take them back (LOK-30). A service may be released anywhere; released on the line, the train
stands without a driver and Trafikledningen gets an alarm at once (LOK-25, LOK-35).

The app never gives departure and controls no traffic (LOK-11). The one thing a driver does that
can count in the traffic is Framme, and only when the game has chosen it and only at a place
nobody works (LOK-39). The clock is always Drift's (LOK-12).

The drivers' names stay out of here: the events and the views carry the driver's id, and the
hub puts the names in where they may be shown (LOK-37).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

from contracts import drift as events
from contracts import driver as contract
from contracts import station
from contracts.meet import Call, DriverLevel, TrackKind, Train
from contracts.reasons import Reason
from drift.driver_book import Checkin, Message, Moment, key_of
from drift.engine import SECONDS_PER_DAY, Drift, Leg, Refused, leg_times, model_time, parse_time

CHANGED_SECONDS: Final = contract.CHANGED_MINUTES * 60
CHECKIN_SHOWN: Final = (contract.CHECKIN_VISIBLE_MINUTES + contract.CHECKIN_FADE_MINUTES) * 60
CHECKIN_FADES: Final = contract.CHECKIN_VISIBLE_MINUTES * 60
# A check-in counts at most a day of real time, whatever the clock does (the old Server).
CHECKIN_KEPT: Final = timedelta(days=1)
# The messages Nu and the stations show: the last 30 game minutes, at most ten in Nu.
MESSAGES_SHOWN: Final = 30 * 60
MESSAGES_IN_NOW: Final = 10


@dataclass(frozen=True)
class Part:
    """One train of a service: the calls the driver runs it, from the first to the last."""

    train: Train
    calls: list[Call]


@dataclass(frozen=True)
class Service:
    ref: events.ServiceRef
    number: str
    level: DriverLevel | None
    parts: list[Part]

    @property
    def calls(self) -> list[Call]:
        return [call for part in self.parts for call in part.calls]


def _seconds(call: Call, *, arrival_first: bool = False) -> int | None:
    time = (call.arrival or call.departure) if arrival_first else (call.departure or call.arrival)
    return None if time is None else parse_time(time) + call.day_offset * SECONDS_PER_DAY


def _part(train: Train, first: str, last: str) -> Part | None:
    ids = [call.id for call in train.calls]
    if first not in ids or last not in ids:
        return None
    start, end = ids.index(first), ids.index(last)
    if end < start:
        return None
    return Part(train, train.calls[start : end + 1])


def services(drift: Drift) -> tuple[events.ServiceKind, list[Service]]:
    """The duties when the meet has duties, with the trains that run today; else the day's
    trains (LOK-17, LOK-31). From the package Drift goes by, with the driftändringar on."""
    trains = {train.id: train for train in drift.package.trains}
    day = drift.traffic_day
    if drift.package.duties:
        found: list[Service] = []
        for duty in drift.package.duties:
            parts = [
                part
                for leg in duty.legs
                if leg.train in trains and day in trains[leg.train].days
                for part in [_part(trains[leg.train], leg.from_call, leg.to_call)]
                if part is not None
            ]
            if parts:
                ref = events.ServiceRef(kind=events.ServiceKind.DUTY, id=duty.id)
                found.append(Service(ref, duty.name, duty.level, parts))
        return events.ServiceKind.DUTY, found
    return events.ServiceKind.TRAIN, [
        Service(
            events.ServiceRef(kind=events.ServiceKind.TRAIN, id=train.id),
            train.number,
            None,
            [Part(train, list(train.calls))],
        )
        for train in drift.package.trains
        if day in train.days and len(train.calls) > 1
    ]


def find(drift: Drift, ref: events.ServiceRef) -> Service | None:
    kind, found = services(drift)
    if kind != ref.kind:
        return None
    return next((service for service in found if service.ref == ref), None)


def _stop_calls(drift: Drift, calls: list[Call]) -> list[Call]:
    return [call for call in calls if call.id in drift.calls]


def _legs(drift: Drift, part: Part) -> list[Leg]:
    """Drift's legs of the part, in order: from a stop to the next, within the part."""
    inside = {call.id for call in part.calls}
    return [
        drift.legs[call.id]
        for call in part.calls
        if call.id in drift.legs and drift.legs[call.id].arrival.id in inside
    ]


def current_part(drift: Drift, service: Service) -> Part:
    """The part the driver is on: the first whose train has not come to its last stop."""
    for part in service.parts:
        legs = _legs(drift, part)
        if legs and legs[-1].departure.id not in drift.arrived:
            return part
    return service.parts[-1]


def on_line(drift: Drift, service: Service) -> Leg | None:
    """The leg the service's train is on now, out on the line between two places: departed and
    not yet arrived."""
    for part in service.parts:
        for leg in _legs(drift, part):
            case = drift.active_case(leg.departure.id)
            if case is not None and case.departed and leg.departure.id not in drift.arrived:
                return leg
    return None


# --- What the list shows ------------------------------------------------------------------


def _end(drift: Drift, call: Call, *, arrival: bool) -> contract.ServiceEnd:
    place = next(p for p in drift.package.places if p.id == call.place)
    time = (call.arrival or call.departure) if arrival else (call.departure or call.arrival)
    return contract.ServiceEnd(time=time, place=place.id, place_name=place.name)


def start_seconds(service: Service) -> int:
    first = service.calls[0]
    found = _seconds(first)
    return found if found is not None else SECONDS_PER_DAY * 8


def offer(
    drift: Drift,
    service: Service,
    *,
    level: DriverLevel | None = None,
    names: Mapping[str, str | None] | None = None,
    query: str | None = None,
) -> contract.ServiceOffer:
    """The service as the paper's front shows it (LOK-19)."""
    key = key_of(service.ref)
    held = drift.drivers.holders.get(key)
    calls = service.calls
    operator = next((p.train.operator for p in service.parts if p.train.operator), None)
    return contract.ServiceOffer(
        service=service.ref,
        number=service.number,
        start=_end(drift, calls[0], arrival=False),
        end=_end(drift, calls[-1], arrival=True),
        operator=operator,
        level=service.level,
        trains=list(dict.fromkeys(part.train.number for part in service.parts)),
        taken=held is not None,
        driver=held.driver if held else None,
        driver_name=(names or {}).get(held.driver) if held else None,
        released_on_line=key in drift.drivers.on_line,
        matches_level=level is not None and service.level == level,
        exact=query is not None and service.number.casefold() == query.casefold(),
        done=key in drift.drivers.done,
    )


def _number_key(number: str) -> tuple[int, str]:
    digits = "".join(ch for ch in number if ch.isdigit())
    return (int(digits) if digits else 0, number)


def service_list(
    drift: Drift,
    *,
    level: DriverLevel | None = None,
    query: str | None = None,
    names: Mapping[str, str | None] | None = None,
) -> contract.ServiceList:
    """The list in start order, with what fits first: a service released on the line, then
    the free services of the driver's level (LOK-32, LOK-40). Taken and done ones stay in the
    list, after. A search on the paper's number has the exact number first (LOK-18)."""
    kind, found = services(drift)
    asked = (query or "").strip().casefold()
    if asked:
        found = [s for s in found if asked in s.number.casefold()]
    offers = [
        (service, offer(drift, service, level=level, names=names, query=asked or None))
        for service in found
    ]
    offers.sort(
        key=lambda pair: (
            not pair[1].exact,
            not pair[1].released_on_line,
            pair[1].done,
            pair[1].taken,
            not pair[1].matches_level,
            start_seconds(pair[0]),
            _number_key(pair[0].number),
        )
    )
    return contract.ServiceList(kind=kind, services=[made for _, made in offers])


# --- Where the trains are ------------------------------------------------------------------


def _minutes(late: float | None) -> int | None:
    return None if late is None else max(0, int(late // 60))


def position(drift: Drift, train: Train, now: datetime) -> contract.TrainPosition:
    """Where the train is according to the stations, and how late (LOK-20)."""
    at = drift.clock.at(now)
    legs = [drift.legs[c.id] for c in train.calls if c.id in drift.legs]
    for index, leg in enumerate(legs):
        key = leg.departure.id
        if key in drift.arrived:
            continue
        times = leg_times(leg)
        case = drift.active_case(key)
        late: float | None = None
        if case is not None and case.departed:
            if times is not None:
                late = max(at - times[2], drift.departed_seconds.get(key, at) - times[1])
            return contract.TrainPosition(
                train=train.id,
                train_number=train.number,
                state="on_the_way",
                from_place=leg.departure.place,
                to_place=leg.arrival.place,
                section=leg.section.id,
                delay=_minutes(late),
            )
        if index == 0 and case is None:
            return contract.TrainPosition(
                train=train.id,
                train_number=train.number,
                state="planned",
                place=leg.departure.place,
            )
        if times is not None:
            late = at - times[1]
            if index:
                came = drift.arrived_seconds.get(legs[index - 1].departure.id)
                before = leg_times(legs[index - 1])
                if came is not None and before is not None:
                    late = max(late, came - before[2])
        return contract.TrainPosition(
            train=train.id,
            train_number=train.number,
            state="at",
            place=leg.departure.place,
            delay=_minutes(late),
        )
    if not legs:
        return contract.TrainPosition(train=train.id, train_number=train.number, state="planned")
    last = legs[-1]
    times = leg_times(last)
    came = drift.arrived_seconds.get(last.departure.id)
    finished = came - times[2] if came is not None and times is not None else None
    return contract.TrainPosition(
        train=train.id,
        train_number=train.number,
        state="done",
        place=last.arrival.place,
        delay=_minutes(finished),
    )


def positions(drift: Drift, now: datetime) -> list[contract.TrainPosition]:
    """Every train of the day, where it is (LOK-08). Open like Nu: no names."""
    return [
        position(drift, train, now)
        for train in drift.package.trains
        if drift.traffic_day in train.days
    ]


# --- The körplan ---------------------------------------------------------------------------


def _recent(at: Moment | None, drift: Drift, seconds: float) -> bool:
    """Within the last ten game minutes of the same game day (LOK-24, LOK-41)."""
    if at is None or at.game_day != drift.game_day:
        return False
    return 0 <= seconds - at.seconds <= CHANGED_SECONDS


def _differs(drift: Drift, train: Train, call: Call) -> bool:
    """Has the call changed from the version that runs: its times, track, stop or note."""
    base = next((t for t in drift.base.trains if t.id == train.id), None)
    if base is None:
        return True
    before = next((c for c in base.calls if c.id == call.id), None)
    if before is None:
        return True
    fields = ("arrival", "departure", "track", "stops", "note")
    return any(getattr(before, name) != getattr(call, name) for name in fields)


def _late_oncoming(drift: Drift, leg: Leg, at: float) -> list[contract.LateOncoming]:
    """Trains coming the other way on a single-track section that should be here before this
    one leaves, and are late (LOK-20)."""
    mine = leg_times(leg)
    if mine is None or leg.section.tracks != TrackKind.SINGLE:
        return []
    found: list[contract.LateOncoming] = []
    for other in drift.legs.values():
        if other.train.id == leg.train.id or other.section.id != leg.section.id:
            continue
        if other.departure.place != leg.arrival.place or other.departure.id in drift.arrived:
            continue
        times = leg_times(other)
        if times is None or times[2] > mine[1]:
            continue
        late = _minutes(at - times[2])
        if late:
            found.append(
                contract.LateOncoming(
                    train=other.train.id, train_number=other.train.number, delay=late
                )
            )
    return found


_SAID: Final[dict[station.ClearanceStatus, Literal["waiting", "approved", "rejected"]]] = {
    station.ClearanceStatus.WAITING: "waiting",
    station.ClearanceStatus.APPROVED: "approved",
    station.ClearanceStatus.REJECTED: "rejected",
}


def _clearance(drift: Drift, call: Call) -> contract.RowClearance | None:
    """Tågklareringens besked for the departure from the call (LOK-21)."""
    leg = drift.legs.get(call.id)
    if leg is None or call.id in drift.arrived:
        return None
    cases = [case for case in drift.cases.values() if case.leg.departure.id == call.id]
    if not cases:
        return None
    case = cases[-1]
    status = _SAID.get(case.status)
    if status is None or case.arrived:
        return None
    return contract.RowClearance(
        status=status,
        to_place=leg.arrival.place,
        track=drift.standing_track(leg.arrival.id),
    )


def _reality(drift: Drift, call: Call, at: float, ahead: bool) -> contract.RowReality:
    """Drift's reality on a row (LOK-20): came, left, how late and late trains to meet."""
    coming = drift.by_arrival.get(call.id)
    going = drift.legs.get(call.id)
    came = coming is not None and coming.departure.id in drift.arrived
    case = drift.active_case(call.id) if going is not None else None
    left = going is not None and (call.id in drift.arrived or (case is not None and case.departed))
    arrived_at = drift.arrived_seconds.get(coming.departure.id) if coming and came else None
    departed_at = drift.departed_seconds.get(call.id) if left else None
    delay = None
    planned_arrival = _seconds(call, arrival_first=True)
    planned_departure = _seconds(call)
    if departed_at is not None and planned_departure is not None:
        delay = _minutes(departed_at - planned_departure)
    elif arrived_at is not None and planned_arrival is not None:
        delay = _minutes(arrived_at - planned_arrival)
    oncoming = _late_oncoming(drift, going, at) if going is not None and ahead and not left else []
    return contract.RowReality(
        passed=left,
        here=came and not left,
        arrived=model_time(arrived_at) if arrived_at is not None else None,
        departed=model_time(departed_at) if departed_at is not None else None,
        delay=delay,
        late_oncoming=oncoming,
    )


def korplan(drift: Drift, service: Service, now: datetime, revision: int) -> contract.Korplan:
    """The körplan from the duty's parts, or the train's timetable (LOK-03). Under the game's
    settings, Drift's reality and the clearances' word beside the plan (LOK-20, LOK-21)."""
    at = drift.clock.at(now)
    settings = drift.drivers.settings
    places = {place.id: place for place in drift.package.places}
    rows: list[contract.KorplanRow] = []
    last = service.calls[-1].id
    current = current_part(drift, service)
    for part in service.parts:
        ahead = part is current
        for index, call in enumerate(part.calls):
            place = places[call.place]
            changed = _recent(drift.drivers.changed.get(call.id), drift, at) or (
                _recent(drift.drivers.changed.get(part.train.id), drift, at)
                and _differs(drift, part.train, call)
            )
            rows.append(
                contract.KorplanRow(
                    call=call.id,
                    train=part.train.id,
                    train_number=part.train.number,
                    place=place.id,
                    place_code=place.code,
                    place_name=place.name,
                    arrival=call.arrival,
                    departure=call.departure,
                    track=drift.assigned.get(call.id, call.track),
                    stops=call.stops,
                    note=call.note,
                    first_of_train=index == 0,
                    last=call.id == last,
                    changed=changed,
                    real=_reality(drift, call, at, ahead)
                    if settings.reality and call.id in drift.calls
                    else None,
                    clearance=_clearance(drift, call) if settings.clearances else None,
                )
            )
    return contract.Korplan(
        service=service.ref,
        number=service.number,
        rows=rows,
        clock=clock(drift, now),
        settings=settings,
        position=position(drift, current.train, now) if settings.reality else None,
        revision=revision,
    )


def clock(drift: Drift, now: datetime) -> station.Clock:
    seconds = drift.clock.at(now)
    return station.Clock(
        time=model_time(seconds),
        seconds=int(seconds),
        running=drift.clock.running,
        speed=drift.clock.speed,
        game_day=drift.game_day,
    )


def start(drift: Drift, service: Service, now: datetime) -> contract.Start:
    """When the service starts, for the countdown and the reminders (LOK-41)."""
    begins = start_seconds(service)
    left = int(begins - drift.clock.at(now))
    real = int(left / drift.clock.speed) if drift.clock.running else None
    return contract.Start(
        time=model_time(begins), seconds=begins, in_game_seconds=left, in_real_seconds=real
    )


def checked_in(drift: Drift, found: Checkin | None, now: datetime) -> contract.CheckedIn | None:
    """The latest check-in while it is seen: 10 game minutes, then 5 more as it fades. A clock
    set back past it, or another game day, makes it old; a day of real time ends it."""
    if found is None or found.at.game_day != drift.game_day:
        return None
    if now - found.at.wall_time > CHECKIN_KEPT:
        return None
    age = drift.clock.at(now) - found.at.seconds
    if age < -60 or age > CHECKIN_SHOWN:
        return None
    age = max(0.0, age)
    place = next((p for p in drift.package.places if p.id == found.place), None)
    number = next((t.number for t in drift.package.trains if t.id == found.train), None)
    return contract.CheckedIn(
        place=found.place,
        place_name=place.name if place else found.place,
        track=found.track,
        train=found.train,
        train_number=number,
        model_time=found.at.model_time,
        age_seconds=round(age, 1),
        fading=age > CHECKIN_FADES,
    )


# --- The messages -------------------------------------------------------------------------


def _train_number(drift: Drift, train: str | None) -> str | None:
    return next((t.number for t in drift.package.trains if t.id == train), None)


def _service_number(drift: Drift, ref: events.ServiceRef | None) -> str | None:
    if ref is None:
        return None
    found = find(drift, ref)
    return found.number if found else None


def message_of(
    drift: Drift, found: Message, names: Mapping[str, str | None] | None = None
) -> contract.DriverMessage:
    return contract.DriverMessage(
        seq=found.seq,
        kind=found.kind,
        driver=found.driver,
        driver_name=(names or {}).get(found.driver),
        service=found.service,
        service_number=_service_number(drift, found.service),
        train=found.train,
        train_number=_train_number(drift, found.train),
        model_time=found.at.model_time,
        wall_time=found.at.wall_time,
    )


def _fresh(drift: Drift, found: Message, at: float) -> bool:
    return found.at.game_day == drift.game_day and 0 <= at - found.at.seconds <= MESSAGES_SHOWN


def now_messages(drift: Drift, now: datetime) -> list[events.NowDriverMessage]:
    """The drivers' messages of the last 30 game minutes, newest first, for Nu (LOK-23)."""
    at = drift.clock.at(now)
    shown = [m for m in reversed(drift.drivers.messages) if _fresh(drift, m, at)]
    return [
        events.NowDriverMessage(
            kind=m.kind,
            train=m.train,
            train_number=_train_number(drift, m.train),
            service_number=_service_number(drift, m.service),
            model_time=m.at.model_time,
            seq=m.seq,
        )
        for m in shown[:MESSAGES_IN_NOW]
    ]


def messages_here(drift: Drift, place: str, now: datetime) -> list[station.DriverMessageHere]:
    """For a station: the messages about trains that are here, on their way here or have just
    left, of the last 30 game minutes (DRIFT-38, KLAR-27)."""
    at = drift.clock.at(now)
    return [
        station.DriverMessageHere(
            kind=m.kind,
            train=m.train,
            train_number=_train_number(drift, m.train),
            model_time=m.at.model_time,
            seq=m.seq,
        )
        for m in reversed(drift.drivers.messages)
        if m.train is not None
        and _fresh(drift, m, at)
        and place in drift.places_of_train_now(m.train)
    ]


def alarms(drift: Drift) -> list[events.DriverAlarm]:
    """The trains that stand without a driver on the line (LOK-35)."""
    found: list[events.DriverAlarm] = []
    for alarm in drift.drivers.alarms.values():
        service = find(drift, alarm.service)
        found.append(
            events.DriverAlarm(
                service=alarm.service,
                number=service.number if service else alarm.service.id,
                train=alarm.train,
                train_number=_train_number(drift, alarm.train),
                section=alarm.section,
                from_place=alarm.from_place,
                to_place=alarm.to_place,
                since=alarm.at.model_time,
                seq=alarm.seq,
            )
        )
    return found


# --- What a driver, Trafikledningen and the lokledare do -----------------------------------


def actor_of(by: events.ClaimedBy, driver: str) -> events.Actor:
    if by == "dispatcher":
        return events.Actor(kind=events.ActorKind.DISPATCHER)
    if by == "loco_lead":
        return events.Actor(kind=events.ActorKind.LOCO_LEAD)
    return events.Actor(kind=events.ActorKind.DRIVER, id=driver)


def _mine(drift: Drift, driver: str) -> Service:
    held = drift.drivers.service_of(driver)
    if held is None:
        raise Refused(Reason.NO_SERVICE)
    service = find(drift, held.service)
    if service is None:
        raise Refused(Reason.UNKNOWN_SERVICE)
    return service


def release(
    drift: Drift,
    driver: str,
    now: datetime,
    *,
    by: events.ClaimedBy = "driver",
    done: bool = False,
) -> None:
    """Släpp tjänsten, var som helst (LOK-25). Released by the driver out on the line, the
    train stands without a driver, and Trafikledningen gets an alarm at once (LOK-35)."""
    held = drift.drivers.service_of(driver)
    if held is None:
        raise Refused(Reason.NO_SERVICE)
    service = find(drift, held.service)
    leg = on_line(drift, service) if service is not None else None
    train = leg.train.id if leg else (current_part(drift, service).train.id if service else None)
    drift.record_driver(
        events.EventKind.SERVICE_RELEASED,
        events.ServiceReleased(
            driver=driver,
            service=held.service,
            by=by,
            on_line=leg is not None,
            section=leg.section.id if leg else None,
            from_place=leg.departure.place if leg else None,
            to_place=leg.arrival.place if leg else None,
            done=done,
        ).model_dump(mode="json"),
        now,
        actor=actor_of(by, driver),
        train=train,
    )


def claim(
    drift: Drift,
    ref: events.ServiceRef,
    driver: str,
    now: datetime,
    *,
    by: events.ClaimedBy = "driver",
) -> None:
    """Ta tjänsten. The first one gets it, and the other is told it is taken; a driver has one
    service at a time (LOK-40). Handed out by Trafikledningen or the lokledare, it is taken
    from the one who has it, and the driver's own goes back first (LOK-30)."""
    service = find(drift, ref)
    if service is None:
        raise Refused(Reason.UNKNOWN_SERVICE)
    held = drift.drivers.holders.get(key_of(ref))
    if held is not None and held.driver == driver:
        return
    if by == "driver":
        if held is not None:
            raise Refused(Reason.SERVICE_TAKEN)
        if drift.drivers.service_of(driver) is not None:
            raise Refused(Reason.ONE_SERVICE)
    else:
        if held is not None:
            release(drift, held.driver, now, by=by)
        if drift.drivers.service_of(driver) is not None:
            release(drift, driver, now, by=by)
    drift.record_driver(
        events.EventKind.SERVICE_CLAIMED,
        events.ServiceClaimed(driver=driver, service=ref, by=by).model_dump(mode="json"),
        now,
        actor=actor_of(by, driver),
        train=current_part(drift, service).train.id,
    )


def take_back(drift: Drift, driver: str, now: datetime, *, by: events.ClaimedBy) -> None:
    """Trafikledningen or the lokledare takes the service back. No alarm: they know."""
    release(drift, driver, now, by=by)


def check_in(drift: Drift, driver: str, place: str, track: str | None, now: datetime) -> None:
    """Förarens egen incheckning (LOK-22): it controls nothing."""
    if place not in {p.id for p in drift.package.places}:
        raise Refused(Reason.UNKNOWN_PLACE)
    held = drift.drivers.service_of(driver)
    service = find(drift, held.service) if held is not None else None
    train = None
    if service is not None:
        current = current_part(drift, service)
        here = [p for p in service.parts if any(c.place == place for c in p.calls)]
        if current in here:
            train = current.train.id
        elif here:
            train = here[-1].train.id
    drift.record_driver(
        events.EventKind.DRIVER_CHECKED_IN,
        events.DriverCheckedIn(
            driver=driver, service=held.service if held else None, track=track or None
        ).model_dump(mode="json"),
        now,
        actor=actor_of("driver", driver),
        train=train,
        place=place,
    )


def message(
    drift: Drift, driver: str, kind: station.DriverMessageKind, now: datetime
) -> events.DriftEvent:
    """Ett färdigt meddelande (LOK-23): to Drift's log and Nu, and to the clearers concerned
    (DRIFT-38). An event with the driver, the service, the train and the time."""
    held = drift.drivers.service_of(driver)
    service = find(drift, held.service) if held is not None else None
    train = current_part(drift, service).train if service is not None else None
    where = drift.places_of_train_now(train.id) if train is not None else set()
    leg = on_line(drift, service) if service is not None else None
    place = leg.departure.place if leg else (sorted(where)[0] if len(where) == 1 else None)
    return drift.record_driver(
        events.EventKind.DRIVER_MESSAGE,
        events.DriverMessageSent(
            driver=driver, kind=kind, service=held.service if held else None
        ).model_dump(mode="json"),
        now,
        actor=actor_of("driver", driver),
        train=train.id if train else None,
        place=place,
    )


def framme(drift: Drift, driver: str, call: str, now: datetime) -> bool:
    """Framme (LOK-04, LOK-11, LOK-39). It counts as the train's arrival only when the game has
    chosen it, and only at a place nobody works. At the service's last call the service is
    done. True when it counted as the arrival."""
    service = _mine(drift, driver)
    found = next((c for c in service.calls if c.id == call), None)
    if found is None:
        raise Refused(Reason.NOT_IN_SERVICE)
    actor = actor_of("driver", driver)
    counted = drift.drivers.settings.arrival and drift.arrive_by_driver(call, now, actor)
    drift.record_driver(
        events.EventKind.DRIVER_ARRIVED,
        events.DriverArrived(driver=driver, service=service.ref, counted=counted).model_dump(
            mode="json"
        ),
        now,
        actor=actor,
        call=call,
        place=found.place,
    )
    if call == service.calls[-1].id:
        release(drift, driver, now, done=True)
    return counted


def set_settings(drift: Drift, settings: events.DriverSettings, now: datetime) -> None:
    """Trafikledningen's choices for the game (LOK-20, LOK-21, LOK-39)."""
    if settings == drift.drivers.settings:
        return
    drift.record_driver(
        events.EventKind.DRIVER_SETTINGS,
        settings.model_dump(mode="json"),
        now,
        actor=events.Actor(kind=events.ActorKind.DISPATCHER),
    )


def clear_alarm(drift: Drift, ref: events.ServiceRef, now: datetime) -> None:
    """Trafikledningen has taken care of the train without a driver."""
    alarm = drift.drivers.alarms.get(key_of(ref))
    if alarm is None:
        raise Refused(Reason.UNKNOWN_SERVICE)
    drift.record_driver(
        events.EventKind.SERVICE_ALARM_CLEARED,
        events.AlarmCleared(service=ref).model_dump(mode="json"),
        now,
        actor=events.Actor(kind=events.ActorKind.DISPATCHER),
        train=alarm.train,
    )
