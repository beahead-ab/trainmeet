"""The first Drift slice: clock, timetable and the shared clearance rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any, Final

from contracts import drift as events
from contracts import station
from contracts.common import Weekday
from contracts.meet import Call, ClearanceMode, MeetPackage, PlaceKind, Section, TrackKind, Train
from contracts.reasons import Reason

VERSION: Final = 1
SECONDS_PER_DAY: Final = 86400


class Refused(Exception):
    def __init__(self, reason: Reason) -> None:
        self.reason = reason
        super().__init__(reason.value)


def model_time(seconds: float) -> str:
    minutes = int(seconds) % SECONDS_PER_DAY // 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_time(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return 3600 * hour + 60 * minute


@dataclass(frozen=True)
class Clock:
    seconds: float
    speed: float
    running: bool
    updated: datetime

    def at(self, now: datetime) -> float:
        if self.running:
            return self.seconds + max(0, (now - self.updated).total_seconds()) * self.speed
        return self.seconds


@dataclass(frozen=True)
class Leg:
    train: Train
    departure: Call
    arrival: Call
    section: Section
    previous: str | None

    @property
    def channel(self) -> tuple[str, str | None]:
        side = self.departure.place if self.section.tracks == TrackKind.DOUBLE else None
        return self.section.id, side


@dataclass(frozen=True)
class Case:
    id: str
    leg: Leg
    status: station.ClearanceStatus = station.ClearanceStatus.WAITING
    departed: bool = False
    arrived: bool = False
    revision: int = 1

    @property
    def active(self) -> bool:
        return not self.arrived and self.status in {
            station.ClearanceStatus.WAITING,
            station.ClearanceStatus.APPROVED,
        }


class Drift:
    def __init__(
        self,
        package: MeetPackage,
        history: list[events.DriftEvent],
        *,
        now: datetime,
    ) -> None:
        self.package = package
        self.history: list[events.DriftEvent] = []
        self.traffic_day = package.meet.traffic_week.start_weekday
        self.clock = Clock(parse_time(package.clock.start_time), package.clock.speed, False, now)
        self.cases: dict[str, Case] = {}
        self.arrived: set[str] = set()
        self.legs: dict[str, Leg] = {}
        self._set_traffic_day(self.traffic_day)
        for event in history:
            self._apply(event)

    @property
    def context(self) -> station.MeetContext:
        return station.MeetContext(
            meet_id=self.package.meet.id, version=VERSION, game_day=1, epoch=0
        )

    def _set_traffic_day(self, day: Weekday) -> None:
        self.traffic_day = day
        stops = {p.id for p in self.package.places if p.kind != PlaceKind.HALT}
        sections = {frozenset((s.place_a, s.place_b)): s for s in self.package.sections}
        self.legs.clear()
        for train in self.package.trains:
            if day not in train.days:
                continue
            previous = None
            for departure, arrival in pairwise(c for c in train.calls if c.place in stops):
                section = sections.get(frozenset((departure.place, arrival.place)))
                if section is not None:
                    self.legs[departure.id] = Leg(train, departure, arrival, section, previous)
                previous = departure.id

    def _record(
        self,
        kind: events.EventKind,
        data: dict[str, object],
        now: datetime,
        *,
        command: station.Command | None = None,
        leg: Leg | None = None,
        seconds: float | None = None,
    ) -> None:
        self._apply(
            events.DriftEvent(
                seq=len(self.history) + 1,
                epoch=self.context.epoch,
                meet_id=self.package.meet.id,
                version=VERSION,
                game_day=self.context.game_day,
                model_time=model_time(self.clock.at(now) if seconds is None else seconds),
                wall_time=now,
                kind=kind,
                actor=events.Actor(kind=events.ActorKind.CLIENT, id=command.client_id)
                if command
                else events.Actor(kind=events.ActorKind.SYSTEM),
                message_id=command.message_id if command else None,
                place=command.place if command else None,
                train=leg.train.id if leg else None,
                call=(
                    leg.arrival.id if kind == events.EventKind.TRAIN_ARRIVED else leg.departure.id
                )
                if leg
                else None,
                data=data,
            )
        )

    def start(self, now: datetime) -> None:
        self._record(
            events.EventKind.MEET_STARTED,
            {"traffic_day": self.traffic_day.value, "speed": self.clock.speed},
            now,
        )

    def control_clock(self, control: events.ClockControl, now: datetime) -> None:
        match control.action:
            case events.ClockAction.START:
                kind = events.EventKind.CLOCK_STARTED
            case events.ClockAction.STOP:
                kind = events.EventKind.CLOCK_STOPPED
            case events.ClockAction.SPEED:
                kind = events.EventKind.CLOCK_SPEED
            case _:
                raise Refused(Reason.UNKNOWN_ACTION)
        seconds = self.clock.at(now)
        speed = control.speed if control.action == events.ClockAction.SPEED else self.clock.speed
        self._record(kind, {"seconds": seconds, "speed": speed}, now, seconds=seconds)

    def pause_after_restart(self, now: datetime) -> None:
        if self.clock.running:
            seconds = self.clock.at(self.history[-1].wall_time)
            self._record(
                events.EventKind.CLOCK_STOPPED,
                {"seconds": seconds, "speed": self.clock.speed},
                now,
                seconds=seconds,
            )

    def _apply(self, event: events.DriftEvent) -> None:
        match event.kind:
            case events.EventKind.MEET_STARTED:
                meet = events.MeetStarted.model_validate(event.data)
                self._set_traffic_day(meet.traffic_day)
                self.clock = Clock(parse_time(event.model_time), meet.speed, False, event.wall_time)
            case (
                events.EventKind.CLOCK_STARTED
                | events.EventKind.CLOCK_STOPPED
                | events.EventKind.CLOCK_SPEED
            ):
                clock = events.ClockChanged.model_validate(event.data)
                running = event.kind == events.EventKind.CLOCK_STARTED or (
                    self.clock.running and event.kind == events.EventKind.CLOCK_SPEED
                )
                self.clock = Clock(clock.seconds, clock.speed, running, event.wall_time)
            case events.EventKind.CLEARANCE_REQUESTED:
                requested = events.ClearanceRequested.model_validate(event.data)
                assert event.call is not None
                self.cases[requested.clearance_id] = Case(
                    requested.clearance_id, self.legs[event.call]
                )
            case events.EventKind.CLEARANCE_ANSWERED:
                answer = events.ClearanceAnswered.model_validate(event.data)
                case = self.cases[answer.clearance_id]
                status = (
                    station.ClearanceStatus.APPROVED
                    if answer.approved
                    else (station.ClearanceStatus.REJECTED)
                )
                self.cases[case.id] = replace(case, status=status, revision=case.revision + 1)
            case events.EventKind.CLEARANCE_CANCELLED:
                case = self.cases[events.ClearanceRef.model_validate(event.data).clearance_id]
                self.cases[case.id] = replace(
                    case, status=station.ClearanceStatus.CANCELLED, revision=case.revision + 1
                )
            case events.EventKind.TRAIN_DEPARTED | events.EventKind.TRAIN_ARRIVED:
                case = self.cases[events.ClearanceRef.model_validate(event.data).clearance_id]
                arrived = event.kind == events.EventKind.TRAIN_ARRIVED
                self.cases[case.id] = replace(
                    case, departed=True, arrived=arrived, revision=case.revision + 1
                )
                if arrived:
                    self.arrived.add(case.leg.departure.id)
            case _:
                raise ValueError(f"Okänd händelse i Provbanans logg: {event.kind}")
        self.history.append(event)

    def request_block(self, leg: Leg) -> Reason | None:
        if leg.departure.id in self.arrived or (leg.previous and leg.previous not in self.arrived):
            return Reason.INVALID_DEPARTURE
        if any(
            case.active and case.leg.departure.id == leg.departure.id
            for case in self.cases.values()
        ):
            return Reason.CALL_ALREADY_REQUESTED
        if any(case.active and case.leg.channel == leg.channel for case in self.cases.values()):
            return Reason.CHANNEL_OCCUPIED
        return None

    def _request(self, command: station.Command, now: datetime) -> None:
        payload = station.ClearanceRequest.model_validate(command.payload)
        leg = self.legs.get(payload.call)
        if leg is None:
            raise Refused(Reason.UNKNOWN_CALL)
        if command.place != leg.departure.place:
            raise Refused(Reason.WRONG_PLACE)
        if payload.section != leg.section.id:
            raise Refused(Reason.UNKNOWN_SECTION)
        if payload.clearance_id in self.cases:
            raise Refused(Reason.CALL_ALREADY_REQUESTED)
        if reason := self.request_block(leg):
            raise Refused(reason)
        self._record(
            events.EventKind.CLEARANCE_REQUESTED,
            {
                "clearance_id": payload.clearance_id,
                "section": leg.section.id,
                "to_place": leg.arrival.place,
            },
            now,
            command=command,
            leg=leg,
        )
        mode = leg.section.clearance_mode or self.package.meet.clearance_mode
        if mode == ClearanceMode.DIRECT:
            self._record(
                events.EventKind.CLEARANCE_ANSWERED,
                {"clearance_id": payload.clearance_id, "approved": True},
                now,
                leg=leg,
            )

    def _case_action(self, command: station.Command, now: datetime) -> None:
        if command.action == station.Action.CLEARANCE_RESPONSE:
            answer = station.ClearanceResponse.model_validate(command.payload)
            clearance_id = answer.clearance_id
        else:
            clearance_id = station.ClearanceCancel.model_validate(command.payload).clearance_id
        case = self.cases.get(clearance_id)
        if case is None:
            raise Refused(Reason.UNKNOWN_CLEARANCE)
        revision = command.expected_revision
        if revision is not None and (
            revision.scope != station.RevisionScope.CASE
            or revision.key != case.id
            or revision.value != case.revision
        ):
            raise Refused(Reason.STALE_REVISION)
        data: dict[str, object] = {"clearance_id": case.id}
        if command.action == station.Action.CLEARANCE_RESPONSE:
            if command.place != case.leg.arrival.place:
                raise Refused(Reason.NOT_RECEIVER)
            if case.status != station.ClearanceStatus.WAITING:
                raise Refused(Reason.CLEARANCE_NOT_PENDING)
            data["approved"] = station.ClearanceResponse.model_validate(command.payload).approved
            kind = events.EventKind.CLEARANCE_ANSWERED
        else:
            if command.place != case.leg.departure.place:
                raise Refused(Reason.NOT_SENDER)
            if case.departed:
                raise Refused(Reason.TRAIN_ALREADY_DEPARTED)
            if not case.active:
                raise Refused(Reason.CLEARANCE_NOT_PENDING)
            kind = events.EventKind.CLEARANCE_CANCELLED
        self._record(kind, data, now, command=command, leg=case.leg)

    def _movement(self, command: station.Command, now: datetime) -> None:
        departure = command.action == station.Action.TRAIN_DEPARTED
        if departure:
            call = station.CallOnly.model_validate(command.payload).call
        else:
            arrival = station.Arrival.model_validate(command.payload)
            if arrival.track is not None:
                raise Refused(Reason.UNKNOWN_ACTION)
            call = arrival.call
        matches = [
            case
            for case in self.cases.values()
            if case.active and (case.leg.departure.id if departure else case.leg.arrival.id) == call
        ]
        if not matches:
            raise Refused(Reason.DEPARTURE_NOT_RESERVED if departure else Reason.TRAIN_NOT_DEPARTED)
        case = matches[0]
        place = case.leg.departure.place if departure else case.leg.arrival.place
        if command.place != place:
            raise Refused(Reason.WRONG_PLACE)
        if departure:
            if case.status != station.ClearanceStatus.APPROVED:
                raise Refused(Reason.DEPARTURE_NOT_RESERVED)
            if case.departed:
                raise Refused(Reason.TRAIN_ALREADY_DEPARTED)
            kind = events.EventKind.TRAIN_DEPARTED
        else:
            if not case.departed:
                raise Refused(Reason.TRAIN_NOT_DEPARTED)
            kind = events.EventKind.TRAIN_ARRIVED
        self._record(kind, {"clearance_id": case.id}, now, command=command, leg=case.leg)

    def command(self, command: station.Command, now: datetime) -> None:
        if command.context != self.context:
            raise Refused(Reason.STALE_MEET_CONTEXT)
        match command.action:
            case station.Action.CLEARANCE_REQUEST:
                self._request(command, now)
            case station.Action.CLEARANCE_RESPONSE | station.Action.CLEARANCE_CANCEL:
                self._case_action(command, now)
            case station.Action.TRAIN_DEPARTED | station.Action.TRAIN_ARRIVED:
                self._movement(command, now)
            case _:
                raise Refused(Reason.UNKNOWN_ACTION)

    def preview(self, now: datetime) -> dict[str, Any]:
        seconds = self.clock.at(now)
        return {
            "revision": len(self.history),
            "context": self.context.model_dump(mode="json"),
            "traffic_day": self.traffic_day,
            "places": {place.id: place.name for place in self.package.places},
            "stations": [p.id for p in self.package.places if p.kind != PlaceKind.HALT],
            "sections": {
                section.id: (section.clearance_mode or self.package.meet.clearance_mode).value
                for section in self.package.sections
            },
            "clock": {
                "seconds": seconds,
                "time": model_time(seconds),
                "speed": self.clock.speed,
                "running": self.clock.running,
            },
            "legs": [
                {
                    "train": leg.train.number,
                    "departure": leg.departure.model_dump(mode="json"),
                    "arrival": leg.arrival.model_dump(mode="json"),
                    "section": leg.section.id,
                    "blocked": self.request_block(leg),
                    "complete": leg.departure.id in self.arrived,
                }
                for leg in self.legs.values()
            ],
            "cases": [
                {
                    "id": case.id,
                    "train": case.leg.train.number,
                    "departure": case.leg.departure.id,
                    "arrival": case.leg.arrival.id,
                    "from_place": case.leg.departure.place,
                    "to_place": case.leg.arrival.place,
                    "status": case.status,
                    "departed": case.departed,
                    "arrived": case.arrived,
                    "revision": case.revision,
                }
                for case in self.cases.values()
            ],
        }


def now_utc() -> datetime:
    return datetime.now(UTC)
