"""Drift: clock, timetable, the shared clearance rules and the station protocol's actions.

Everything is a Drift event; the state is what the events add up to, so a restart reads the
same state back. Ported from the old Server's engine and protocol_v2 with their tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from hashlib import sha256
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


@dataclass
class LineMessage:
    """Ledig linje: told to the other end, acknowledged there, never answered."""

    id: str
    section: str
    from_place: str
    to_place: str
    call: str | None
    acknowledged: bool = False


@dataclass(frozen=True)
class Outcome:
    """What a command gives back besides the snapshot: the revision it raised, or for
    train.lookup the calls the number means here."""

    revision: station.Revision | None = None
    result: list[station.LookupMatch] = field(default_factory=list)


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
        version: int = VERSION,
    ) -> None:
        self.package = package
        self.version = version
        self.history: list[events.DriftEvent] = []
        self.traffic_day = package.meet.traffic_week.start_weekday
        self.game_day = 1
        self.clock = Clock(parse_time(package.clock.start_time), package.clock.speed, False, now)
        self.cases: dict[str, Case] = {}
        self.arrived: set[str] = set()
        self.legs: dict[str, Leg] = {}
        self.by_arrival: dict[str, Leg] = {}
        self.next_leg: dict[str, str] = {}
        # Where each arrived train stands (leg key -> track), and the ones put away.
        self.tracks: dict[str, str] = {}
        self.set_aside: set[str] = set()
        # The station protocol: a call's track set by hand, TKL's two declarations, the
        # times shown for the cases, ledig linje, and the call and place revisions.
        self.assigned: dict[str, str] = {}
        self.positioned: set[str] = set()
        self.crew_ready: set[str] = set()
        self.requested_at: dict[str, str] = {}
        self.departed_at: dict[str, str] = {}
        self.lines: dict[str, LineMessage] = {}
        self.call_revision: dict[str, int] = {}
        self.place_revision: dict[str, int] = {}
        self.calls: dict[str, tuple[Train, Call]] = {}
        self._set_traffic_day(self.traffic_day)
        for event in history:
            self._apply(event)

    @property
    def context(self) -> station.MeetContext:
        return station.MeetContext(
            meet_id=self.package.meet.id, version=self.version, game_day=self.game_day, epoch=0
        )

    def _set_traffic_day(self, day: Weekday) -> None:
        self.traffic_day = day
        stops = {p.id for p in self.package.places if p.kind != PlaceKind.HALT}
        sections = {frozenset((s.place_a, s.place_b)): s for s in self.package.sections}
        self.legs.clear()
        self.by_arrival.clear()
        self.next_leg.clear()
        self.calls.clear()
        for train in self.package.trains:
            if day not in train.days:
                continue
            for call in train.calls:
                if call.place in stops:
                    self.calls[call.id] = (train, call)
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
        call: str | None = None,
    ) -> None:
        if call is not None:
            train: str | None = self.calls[call][0].id if call in self.calls else None
        elif leg is not None:
            train = leg.train.id
            call = leg.arrival.id if kind in _AT_ARRIVAL else leg.departure.id
        else:
            train = None
        self._apply(
            events.DriftEvent(
                seq=len(self.history) + 1,
                epoch=self.context.epoch,
                meet_id=self.package.meet.id,
                version=self.version,
                game_day=self.context.game_day,
                model_time=model_time(self.clock.at(now) if seconds is None else seconds),
                wall_time=now,
                kind=kind,
                actor=events.Actor(kind=events.ActorKind.CLIENT, id=command.client_id)
                if command
                else events.Actor(kind=events.ActorKind.SYSTEM),
                message_id=command.message_id if command else None,
                place=command.place if command else None,
                train=train,
                call=call,
                data=data,
            )
        )

    def start(self, now: datetime, traffic_day: Weekday | None = None, game_day: int = 1) -> None:
        """The meet starts on a traffic day (F8: the package's first by default) and a game
        day, with the clock stopped at the package's start time."""
        self._record(
            events.EventKind.MEET_STARTED,
            {
                "traffic_day": (traffic_day or self.traffic_day).value,
                "speed": self.clock.speed,
                "game_day": game_day,
            },
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
                self.game_day = meet.game_day
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
                self._touch_places(*{call.place for _, call in self.calls.values()})
            case events.EventKind.CLEARANCE_REQUESTED:
                requested = events.ClearanceRequested.model_validate(event.data)
                assert event.call is not None
                self.cases[requested.clearance_id] = Case(
                    requested.clearance_id, self.legs[event.call]
                )
                self.requested_at[requested.clearance_id] = event.model_time
                self._touch(self.legs[event.call])
            case events.EventKind.CLEARANCE_ANSWERED:
                answer = events.ClearanceAnswered.model_validate(event.data)
                case = self.cases[answer.clearance_id]
                status = (
                    station.ClearanceStatus.APPROVED
                    if answer.approved
                    else (station.ClearanceStatus.REJECTED)
                )
                self.cases[case.id] = replace(case, status=status, revision=case.revision + 1)
                self._touch(case.leg)
            case events.EventKind.CLEARANCE_CANCELLED | events.EventKind.CLEARANCE_INVALIDATED:
                case = self.cases[events.ClearanceRef.model_validate(event.data).clearance_id]
                status = (
                    station.ClearanceStatus.CANCELLED
                    if event.kind == events.EventKind.CLEARANCE_CANCELLED
                    else station.ClearanceStatus.INVALIDATED
                )
                self.cases[case.id] = replace(case, status=status, revision=case.revision + 1)
                self._touch(case.leg)
            case events.EventKind.TRAIN_DEPARTED:
                case = self.cases[events.ClearanceRef.model_validate(event.data).clearance_id]
                self.cases[case.id] = replace(case, departed=True, revision=case.revision + 1)
                self.departed_at[case.id] = event.model_time
                self._touch(case.leg)
            case events.EventKind.TRAIN_ARRIVED:
                arrival = events.TrainArrived.model_validate(event.data)
                case = self.cases[arrival.clearance_id]
                self.cases[case.id] = replace(
                    case, departed=True, arrived=True, revision=case.revision + 1
                )
                self._arrive(case.leg, arrival.track)
                self._touch(case.leg)
            case events.EventKind.TRAIN_MOVED_HERE:
                assert event.call is not None
                moved = events.TrainMovedHere.model_validate(event.data)
                self._arrive(self.by_arrival[event.call], moved.track)
                self._touch(self.by_arrival[event.call])
            case events.EventKind.TRAIN_SET_ASIDE:
                assert event.call is not None
                self.set_aside.add(self.by_arrival[event.call].departure.id)
                self._touch_call(event.call)
            case events.EventKind.TRAIN_TRACK_CHANGED:
                assert event.call is not None
                track = events.TrackChanged.model_validate(event.data).track
                self.assigned[event.call] = track
                arriving = self.by_arrival.get(event.call)
                if arriving is not None and arriving.departure.id in self.arrived:
                    self.tracks[arriving.departure.id] = track  # The train moves with it.
                self._touch_call(event.call)
            case events.EventKind.TRAIN_POSITIONED | events.EventKind.TRAIN_CREW_READY:
                assert event.call is not None
                flags = (
                    self.positioned
                    if event.kind == events.EventKind.TRAIN_POSITIONED
                    else self.crew_ready
                )
                if events.FlagSet.model_validate(event.data).value:
                    flags.add(event.call)
                else:
                    flags.discard(event.call)
                self._touch_call(event.call)
            case events.EventKind.LINE_AVAILABLE:
                sent = events.LineAvailableSent.model_validate(event.data)
                assert event.place is not None
                self.lines[sent.message_id] = LineMessage(
                    sent.message_id, sent.section, event.place, sent.to_place, event.call
                )
                self._touch_places(event.place, sent.to_place)
            case events.EventKind.LINE_ACKNOWLEDGED:
                line = self.lines[events.LineAcknowledged.model_validate(event.data).message_id]
                line.acknowledged = True
                self._touch_places(line.from_place, line.to_place)
            case _:
                raise ValueError(f"Okänd händelse i Provbanans logg: {event.kind}")
        self.history.append(event)

    def _arrive(self, leg: Leg, track: str | None) -> None:
        self.arrived.add(leg.departure.id)
        if track is not None:
            self.tracks[leg.departure.id] = track

    # --- Revisions: per call, per case and per place, never one counter (v2 §5) -------

    def _touch_places(self, *places: str) -> None:
        for place in set(places):
            self.place_revision[place] = self.place_revision.get(place, 0) + 1

    def _touch_call(self, call: str) -> None:
        self.call_revision[call] = self.call_revision.get(call, 0) + 1
        if call in self.calls:
            self._touch_places(self.calls[call][1].place)

    def _touch(self, leg: Leg) -> None:
        for call in (leg.departure.id, leg.arrival.id):
            self.call_revision[call] = self.call_revision.get(call, 0) + 1
        self._touch_places(leg.departure.place, leg.arrival.place)

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
        """The track set by hand, else the timetable's, else the first free standard track
        for the train (4.9.0)."""
        if leg.arrival.id in self.assigned:
            return self.assigned[leg.arrival.id]
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

    # --- The station protocol's other actions (old Server protocol_v2) ------------------

    def standing_track(self, call: str) -> str | None:
        """Where the train of this call stands, or will stand when it comes."""
        arriving = self.by_arrival.get(call)
        if arriving is not None and arriving.departure.id in self.arrived:
            return self.tracks.get(arriving.departure.id)
        if call in self.assigned:
            return self.assigned[call]
        return self.calls[call][1].track if call in self.calls else None

    def departed_from(self, call: str) -> bool:
        """Has the train left this call: its next leg reported departed, or finished?"""
        if call not in self.legs:
            return False
        case = self.active_case(call)
        return call in self.arrived or (case is not None and case.departed)

    def _call_here(self, command: station.Command, call: str) -> tuple[Train, Call]:
        found = self.calls.get(call)
        if found is None:
            raise Refused(Reason.UNKNOWN_CALL)
        if found[1].place != command.place:
            raise Refused(Reason.WRONG_PLACE)
        return found

    def lookup(self, place: str, number: str) -> list[station.LookupMatch]:
        """The calls at this place a train number means, still to come or still here.
        Never touches the state; two trains with one number are both answered."""
        matches = []
        for train, call in self.calls.values():
            if call.place != place or train.number != number or self.departed_from(call.id):
                continue
            arriving, leaving = self.by_arrival.get(call.id), self.legs.get(call.id)
            if leaving is None and arriving is not None and arriving.departure.id in self.arrived:
                continue  # Ended here and in: nothing more to look up.
            matches.append(
                station.LookupMatch(
                    call=call.id,
                    train_number=train.number,
                    from_place=arriving.departure.place if arriving else None,
                    to_place=leaving.arrival.place if leaving else None,
                    time=call.departure or call.arrival,
                )
            )
        return matches

    def _track_change(self, command: station.Command, now: datetime) -> None:
        """Another track for a call. An unknown track and one another train stands on are
        refused, the second unlike an arrival (old Server; Benny #197). A request still
        open for the departure from here is invalidated: it was asked for another track."""
        change = station.TrackChange.model_validate(command.payload)
        _, call = self._call_here(command, change.call)
        if self.departed_from(call.id):
            raise Refused(Reason.TRAIN_ALREADY_DEPARTED)
        names = self.track_names(call.place)
        if names and change.track not in names:
            raise Refused(Reason.UNKNOWN_TRACK)
        arriving = self.by_arrival.get(call.id)
        own = arriving.departure.id if arriving else None
        if self.occupant(call.place, change.track, own) is not None:
            raise Refused(Reason.TRACK_OCCUPIED)
        self._record(
            events.EventKind.TRAIN_TRACK_CHANGED,
            {"track": change.track},
            now,
            command=command,
            call=call.id,
        )
        case = self.active_case(call.id)
        if case is not None and not case.departed:
            self._record(
                events.EventKind.CLEARANCE_INVALIDATED,
                {"clearance_id": case.id},
                now,
                command=command,
                leg=case.leg,
            )

    def _flag(self, command: station.Command, now: datetime) -> None:
        """Uppställt and föraren på plats, for a train that leaves from here. REDO is what
        both add up to and is never set; neither is needed to depart (C4)."""
        flag = station.Flag.model_validate(command.payload)
        _, call = self._call_here(command, flag.call)
        if call.id not in self.legs:
            raise Refused(Reason.INVALID_DEPARTURE)
        if self.departed_from(call.id):
            raise Refused(Reason.TRAIN_ALREADY_DEPARTED)
        kind = (
            events.EventKind.TRAIN_POSITIONED
            if command.action == station.Action.TRAIN_POSITION_SET
            else events.EventKind.TRAIN_CREW_READY
        )
        self._record(kind, {"value": flag.value}, now, command=command, call=call.id)

    def _line_available(self, command: station.Command, now: datetime) -> str:
        """Ledig linje to the other end of a section: a message, never a request, so it
        never takes the channel (old Server v2)."""
        line = station.LineAvailable.model_validate(command.payload)
        section = next((s for s in self.package.sections if s.id == line.section), None)
        if section is None:
            raise Refused(Reason.UNKNOWN_SECTION)
        if command.place not in {section.place_a, section.place_b}:
            raise Refused(Reason.WRONG_PLACE)
        if line.call not in self.calls:
            raise Refused(Reason.UNKNOWN_CALL)
        other = section.place_b if command.place == section.place_a else section.place_a
        digest = sha256(f"{command.client_id}:{command.message_id}".encode()).hexdigest()
        message_id = "line-" + digest[:16]
        self._record(
            events.EventKind.LINE_AVAILABLE,
            {"message_id": message_id, "section": section.id, "to_place": other},
            now,
            command=command,
            call=line.call,
        )
        return message_id

    def _line_acknowledge(self, command: station.Command, now: datetime) -> str:
        message_id = station.LineAcknowledge.model_validate(command.payload).message_id
        line = self.lines.get(message_id)
        if line is None:
            raise Refused(Reason.UNKNOWN_LINE_MESSAGE)
        if command.place != line.to_place:
            raise Refused(Reason.NOT_RECEIVER)
        if line.acknowledged:
            raise Refused(Reason.ALREADY_ACKNOWLEDGED)
        self._record(
            events.EventKind.LINE_ACKNOWLEDGED, {"message_id": message_id}, now, command=command
        )
        return message_id

    def _check_revision(self, command: station.Command) -> None:
        """A command made on an old picture is refused with stale_revision: each scope is
        judged by its own number, never by another's (v2 §5)."""
        expected = command.expected_revision
        if expected is None:
            return
        match expected.scope:
            case station.RevisionScope.CALL:
                current = self.call_revision.get(expected.key, 0)
            case station.RevisionScope.PLACE:
                current = self.place_revision.get(expected.key, 0)
            case _:
                case = self.cases.get(expected.key)
                line = self.lines.get(expected.key)
                current = case.revision if case else (2 if line and line.acknowledged else 1)
        if expected.value != current:
            raise Refused(Reason.STALE_REVISION)

    def command(self, command: station.Command, now: datetime) -> Outcome:
        """Carry out one station command, or refuse it with a reason and change nothing."""
        if command.context != self.context:
            raise Refused(Reason.STALE_MEET_CONTEXT)
        self._check_revision(command)
        call: str | None = None
        case_id: str | None = None
        match command.action:
            case station.Action.TRAIN_LOOKUP:
                number = station.TrainLookup.model_validate(command.payload).train_number
                matches = self.lookup(command.place, number)
                if not matches:
                    raise Refused(Reason.UNKNOWN_TRAIN_NUMBER)
                return Outcome(result=matches)
            case station.Action.CLEARANCE_REQUEST:
                self._request(command, now)
                case_id = station.ClearanceRequest.model_validate(command.payload).clearance_id
            case station.Action.CLEARANCE_RESPONSE | station.Action.CLEARANCE_CANCEL:
                self._case_action(command, now)
                case_id = str(command.payload["clearance_id"])
            case station.Action.TRAIN_DEPARTED:
                self._departure(command, now)
                call = station.CallOnly.model_validate(command.payload).call
            case station.Action.TRAIN_ARRIVED:
                self._arrival(command, now)
                call = station.Arrival.model_validate(command.payload).call
            case station.Action.TRAIN_SET_ASIDE:
                self._set_aside(command, now)
                call = station.CallOnly.model_validate(command.payload).call
            case station.Action.TRAIN_TRACK_CHANGE:
                self._track_change(command, now)
                call = station.TrackChange.model_validate(command.payload).call
            case station.Action.TRAIN_POSITION_SET | station.Action.TRAIN_CREW_READY_SET:
                self._flag(command, now)
                call = station.Flag.model_validate(command.payload).call
            case station.Action.LINE_AVAILABLE_PUBLISH:
                line = self._line_available(command, now)
                return Outcome(revision=self._line_revision(line))
            case station.Action.LINE_AVAILABLE_ACKNOWLEDGE:
                line = self._line_acknowledge(command, now)
                return Outcome(revision=self._line_revision(line))
            case station.Action.SECTION_OCCUPANCY | station.Action.SIGNAL_EXIT:
                raise Refused(Reason.NOT_LEVEL_3)  # Detection comes with TKL level 3.
            case _:
                raise Refused(Reason.UNKNOWN_ACTION)
        if case_id is not None:
            revision = self.cases[case_id].revision
            return Outcome(
                revision=station.Revision(
                    scope=station.RevisionScope.CASE, key=case_id, value=revision
                )
            )
        assert call is not None
        return Outcome(
            revision=station.Revision(
                scope=station.RevisionScope.CALL, key=call, value=self.call_revision.get(call, 0)
            )
        )

    def _line_revision(self, message_id: str) -> station.Revision:
        value = 2 if self.lines[message_id].acknowledged else 1
        return station.Revision(scope=station.RevisionScope.CASE, key=message_id, value=value)

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
