"""The first Drift slice: clock, timetable and the shared clearance rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any, Final

from contracts import drift as events
from contracts import station
from contracts.common import Side, Weekday
from contracts.meet import Call, ClearanceMode, MeetPackage, PlaceKind, Section, TrackKind, Train
from contracts.reasons import Reason

VERSION: Final = 1
SECONDS_PER_DAY: Final = 86400


_AT_ARRIVAL: Final = frozenset(
    {
        events.EventKind.TRAIN_ARRIVED,
        events.EventKind.TRAIN_MOVED_HERE,
        events.EventKind.TRAIN_SET_ASIDE,
    }
)


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
        self.by_arrival: dict[str, Leg] = {}
        self.next_leg: dict[str, str] = {}
        # Where each arrived train stands (leg key -> track), and the ones put away.
        self.tracks: dict[str, str] = {}
        self.set_aside: set[str] = set()
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
        self.by_arrival.clear()
        self.next_leg.clear()
        for train in self.package.trains:
            if day not in train.days:
                continue
            previous = None
            for departure, arrival in pairwise(c for c in train.calls if c.place in stops):
                section = sections.get(frozenset((departure.place, arrival.place)))
                if section is not None:
                    leg = Leg(train, departure, arrival, section, previous)
                    self.legs[departure.id] = leg
                    self.by_arrival[arrival.id] = leg
                    if previous is not None:
                        self.next_leg[previous] = departure.id
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
                call=(leg.arrival.id if kind in _AT_ARRIVAL else leg.departure.id) if leg else None,
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
            case events.EventKind.TRAIN_DEPARTED:
                case = self.cases[events.ClearanceRef.model_validate(event.data).clearance_id]
                self.cases[case.id] = replace(case, departed=True, revision=case.revision + 1)
            case events.EventKind.TRAIN_ARRIVED:
                arrival = events.TrainArrived.model_validate(event.data)
                case = self.cases[arrival.clearance_id]
                self.cases[case.id] = replace(
                    case, departed=True, arrived=True, revision=case.revision + 1
                )
                self._arrive(case.leg, arrival.track)
            case events.EventKind.TRAIN_MOVED_HERE:
                assert event.call is not None
                moved = events.TrainMovedHere.model_validate(event.data)
                self._arrive(self.by_arrival[event.call], moved.track)
            case events.EventKind.TRAIN_SET_ASIDE:
                assert event.call is not None
                self.set_aside.add(self.by_arrival[event.call].departure.id)
            case _:
                raise ValueError(f"Okänd händelse i Provbanans logg: {event.kind}")
        self.history.append(event)

    def _arrive(self, leg: Leg, track: str | None) -> None:
        self.arrived.add(leg.departure.id)
        if track is not None:
            self.tracks[leg.departure.id] = track

    # --- Tracks: where the trains stand (old Server 4.9.0 and 4.12.2) ------------------

    def active_case(self, key: str) -> Case | None:
        return next(
            (c for c in self.cases.values() if c.active and c.leg.departure.id == key), None
        )

    def _gone_on(self, key: str) -> bool:
        """Has the train that came in on this leg left again on its next leg?"""
        following = self.next_leg.get(key)
        if following is None:
            return False
        case = self.active_case(following)
        return following in self.arrived or (case is not None and case.departed)

    def occupant(self, place: str, track: str, but: str | None = None) -> Leg | None:
        """Another train standing on the track now: in and not gone on, and not put away.
        A train due on the track later in the day does not count."""
        for key, standing in self.tracks.items():
            leg = self.legs[key]
            if (
                key != but
                and standing == track
                and leg.arrival.place == place
                and key not in self.set_aside
                and not self._gone_on(key)
            ):
                return leg
        return None

    def ended_here(self, key: str) -> bool:
        """A train that arrived on this leg and goes no further today."""
        return key in self.arrived and key not in self.next_leg and key not in self.set_aside

    def track_names(self, place: str) -> list[str]:
        found = next(p for p in self.package.places if p.id == place)
        return [t.name for t in sorted(found.tracks, key=lambda t: t.sort_order)]

    def planned_track(self, leg: Leg) -> str | None:
        """The timetable's track, else the first free standard track for the train (4.9.0)."""
        if leg.arrival.track:
            return leg.arrival.track
        for track in self.default_tracks(leg):
            if self.occupant(leg.arrival.place, track, leg.departure.id) is None:
                return track
        return None

    def default_tracks(self, leg: Leg) -> list[str]:
        place = next(p for p in self.package.places if p.id == leg.arrival.place)
        towards = self._travel_side(leg)
        return [
            d.track
            for d in place.default_tracks
            if (d.train_type in (None, leg.train.train_type))
            and (d.towards is None or d.towards == towards)
        ]

    def _travel_side(self, leg: Leg) -> Side | None:
        """The side of the arrival place the train is heading towards."""
        section = leg.section
        came_from = section.side_at_b if leg.arrival.place == section.place_b else section.side_at_a
        if came_from is None:
            return None
        return Side.RIGHT if came_from == Side.LEFT else Side.LEFT

    def track_choices(self, leg: Leg) -> list[str]:
        """The track picker: the train's track first, then standard tracks, then the rest."""
        order: list[str] = []
        planned = self.planned_track(leg)
        for track in [planned, *self.default_tracks(leg), *self.track_names(leg.arrival.place)]:
            if track and track not in order:
                order.append(track)
        return order

    def _arrival_track(self, leg: Leg, requested: str | None) -> str | None:
        if requested is None:
            return self.planned_track(leg)
        names = self.track_names(leg.arrival.place)
        if names and requested not in names:
            raise Refused(Reason.UNKNOWN_TRACK)
        return requested

    def request_block(self, leg: Leg) -> Reason | None:
        # A through train's next leg may be asked for while it is still on its way in; sent
        # on, it jumps here with the departure (old Server, Casper 2026-10-02).
        if leg.departure.id in self.arrived:
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

    def _finish(self, leg: Leg, command: station.Command, now: datetime) -> None:
        """Bring a leg to its end, whatever it last knew, so the train is here (old _finish_leg)."""
        case = self.active_case(leg.departure.id)
        track = self.planned_track(leg)
        if case is None:
            self._record(
                events.EventKind.TRAIN_MOVED_HERE, {"track": track}, now, command=command, leg=leg
            )
            return
        if case.status == station.ClearanceStatus.WAITING:
            self._record(
                events.EventKind.CLEARANCE_ANSWERED,
                {"clearance_id": case.id, "approved": True},
                now,
                command=command,
                leg=leg,
            )
        self._record(
            events.EventKind.TRAIN_ARRIVED,
            {"clearance_id": case.id, "track": track},
            now,
            command=command,
            leg=leg,
        )

    def _departure(self, command: station.Command, now: datetime) -> None:
        call = station.CallOnly.model_validate(command.payload).call
        case = self.active_case(call)
        if case is None:
            raise Refused(Reason.DEPARTURE_NOT_RESERVED)
        if command.place != case.leg.departure.place:
            raise Refused(Reason.WRONG_PLACE)
        if case.departed:
            raise Refused(Reason.TRAIN_ALREADY_DEPARTED)
        if case.status != station.ClearanceStatus.APPROVED:
            raise Refused(Reason.DEPARTURE_NOT_RESERVED)
        # Not seen to come in: it jumps here with the departure, and every earlier part of
        # the route still open here is brought to its end (old Server 2.1.0).
        previous = self.legs.get(case.leg.previous or "")
        if previous is not None and previous.departure.id not in self.arrived:
            self._finish(previous, command, now)
        self._record(
            events.EventKind.TRAIN_DEPARTED,
            {"clearance_id": case.id},
            now,
            command=command,
            leg=case.leg,
        )

    def _arrival(self, command: station.Command, now: datetime) -> None:
        """An arrival can always be taken (old Server 2.1.0): sent and departed, cleared but
        never reported departed, or never sent at all. An occupied track does not stop it."""
        arrival = station.Arrival.model_validate(command.payload)
        leg = self.by_arrival.get(arrival.call)
        if leg is None:
            raise Refused(Reason.UNKNOWN_CALL)
        if command.place != leg.arrival.place:
            raise Refused(Reason.WRONG_PLACE)
        if leg.departure.id in self.arrived:
            raise Refused(Reason.INVALID_ARRIVAL)
        track = self._arrival_track(leg, arrival.track)
        case = self.active_case(leg.departure.id)
        if case is None:
            self._record(
                events.EventKind.TRAIN_MOVED_HERE, {"track": track}, now, command=command, leg=leg
            )
        elif case.status == station.ClearanceStatus.WAITING:
            raise Refused(Reason.TRAIN_NOT_DEPARTED)
        else:
            self._record(
                events.EventKind.TRAIN_ARRIVED,
                {"clearance_id": case.id, "track": track},
                now,
                command=command,
                leg=leg,
            )

    def _set_aside(self, command: station.Command, now: datetime) -> None:
        call = station.CallOnly.model_validate(command.payload).call
        leg = self.by_arrival.get(call)
        if leg is None:
            raise Refused(Reason.UNKNOWN_CALL)
        if command.place != leg.arrival.place:
            raise Refused(Reason.WRONG_PLACE)
        if not self.ended_here(leg.departure.id):
            raise Refused(Reason.INVALID_ARRIVAL)
        self._record(events.EventKind.TRAIN_SET_ASIDE, {}, now, command=command, leg=leg)

    def command(self, command: station.Command, now: datetime) -> None:
        if command.context != self.context:
            raise Refused(Reason.STALE_MEET_CONTEXT)
        match command.action:
            case station.Action.CLEARANCE_REQUEST:
                self._request(command, now)
            case station.Action.CLEARANCE_RESPONSE | station.Action.CLEARANCE_CANCEL:
                self._case_action(command, now)
            case station.Action.TRAIN_DEPARTED:
                self._departure(command, now)
            case station.Action.TRAIN_ARRIVED:
                self._arrival(command, now)
            case station.Action.TRAIN_SET_ASIDE:
                self._set_aside(command, now)
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
