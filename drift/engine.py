"""Drift: clock, timetable, the shared clearance rules and the station protocol's actions.

Everything is a Drift event; the state is what the events add up to, so a restart reads the
same state back. Ported from the old Server's engine and protocol_v2 with their tests.
"""

from __future__ import annotations

from collections.abc import Callable
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
from core import changes as driftchanges

VERSION: Final = 1
SECONDS_PER_DAY: Final = 86400
# An unanswered request is reminded of after this long, and then as often, real time (H39).
REMINDER_SECONDS: Final = 180
# Dygnsskiftet (F7, old Server): an hour before the new day's first train, never before
# midnight; 05:00 for a day without trains. Automatic, it waits at most 30 game minutes for
# the day's trains still out (DRIFT-46).
DAY_CHANGE_LEAD: Final = 3600
DAY_CHANGE_DEFAULT: Final = 5 * 3600
DAY_CHANGE_WAIT: Final = 30 * 60
# The automation acts through the same station commands as a box, under its own name (F14).
AUTOMATION: Final = "automatik"
# What a box or TKL may still do at a place left to the automation: look, and take it back.
_ALLOWED_WHEN_LEFT: Final = frozenset(
    {station.Action.TRAIN_LOOKUP, station.Action.PLACE_LEAVE, station.Action.PLACE_TAKE_BACK}
)


_AT_ARRIVAL: Final = frozenset(
    {
        events.EventKind.TRAIN_ARRIVED,
        events.EventKind.TRAIN_MOVED_HERE,
        events.EventKind.TRAIN_SET_ASIDE,
    }
)


# The clock is the dispatcher's: Nu, or the page of a Provbanan run (TRAFIK-01).
_DISPATCHER: Final = events.Actor(kind=events.ActorKind.DISPATCHER)
# What Ångra takes back (F6): a time jump, or a new game day.
_UNDOABLE: Final = frozenset({events.EventKind.TIME_JUMP, events.EventKind.DAY_CHANGED})


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


def next_weekday(day: Weekday) -> Weekday:
    """The traffic day of the next game day: the weekday after (DRIFT-45)."""
    days = list(Weekday)
    return days[(days.index(day) + 1) % len(days)]


def _at(time: str | None, day_offset: int) -> float | None:
    return None if time is None else parse_time(time) + day_offset * SECONDS_PER_DAY


def leg_times(leg: Leg) -> tuple[float | None, float, float] | None:
    """When the train comes to the departure call, leaves it and arrives, in model seconds of
    the game day; None for a leg without times or with an impossible running time. A visit
    spanning midnight has one day offset, but two clock times."""
    came = _at(leg.departure.arrival, leg.departure.day_offset)
    departure = _at(leg.departure.departure, leg.departure.day_offset)
    arrival = _at(leg.arrival.arrival or leg.arrival.departure, leg.arrival.day_offset)
    if departure is None or arrival is None:
        return None
    if came is not None and departure < came:
        departure += SECONDS_PER_DAY
    if arrival < departure:
        arrival += SECONDS_PER_DAY
    if not 0 < arrival - departure <= SECONDS_PER_DAY:
        return None
    return came, departure, arrival


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
    # The reminders of an unanswered request (H39): how many, and when the last one, or the
    # request, went out, in real time.
    reminders: int = 0
    since: datetime | None = None

    @property
    def active(self) -> bool:
        return not self.arrived and self.status in {
            station.ClearanceStatus.WAITING,
            station.ClearanceStatus.APPROVED,
        }


@dataclass(frozen=True)
class ChangeState:
    """A driftändring in the running meet (DRIFT-41): what it is, and whether it applies."""

    id: str
    change: events.DriftChange
    status: events.ChangeStatus
    forced: bool
    made: str
    train_number: str | None = None


class Drift:
    def __init__(
        self,
        package: MeetPackage,
        history: list[events.DriftEvent],
        *,
        now: datetime,
        version: int = VERSION,
        packages: Callable[[int], MeetPackage] | None = None,
    ) -> None:
        # The version that runs, and the package Drift goes by: the version with the
        # driftändringar laid on top, in the order they applied (DRIFT-41).
        self.base = package
        self.package = package
        self.version = version
        # The run's first version, and how to read another one for a version switch (DRIFT-29).
        self.start_package, self.start_version = package, version
        self.packages = packages
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
        # The automation (F14): who works each place, the places left to it, its settings,
        # when it first ran (model seconds), and the model time each train left and came in.
        self.manned: dict[str, str] = {}
        self.left: dict[str, events.PlaceLeft] = {}
        self.automation = events.AutomationSettings()
        self.first_run: float | None = None
        self.departed_seconds: dict[str, float] = {}
        self.arrived_seconds: dict[str, float] = {}
        # When the clock last started, in real time: the reminders count from there (H39).
        self.running_since = now
        # The legs the timetable had on the line when the trains were last placed: the train
        # waits at the departure place for a clearance (DRIFT-43). And the latest time jump,
        # while it can be undone (F6).
        self.held: set[str] = set()
        self.last_jump: events.DriftEvent | None = None
        self.day_settings = events.DaySettings()
        # The places' game numbers changed during the meet (H30); the rest are the package's.
        self.phones: dict[str, str | None] = {}
        self.changes: dict[str, ChangeState] = {}
        self.applied: list[str] = []
        # Places a driftändring made unmanned: the automation runs them (F2).
        self.unmanned: set[str] = set()
        # Påbörjat och klart (DRIFT-47), and a version switch waiting for trains that are out.
        self.transition: str | None = None
        self.waiting_switch: events.VersionSwitch | None = None
        self._set_traffic_day(self.traffic_day)
        for event in history:
            self._apply(event)
        # Begun and never done: Drift starts locked and says so, rather than run a mixed state.
        self.locked = self.transition

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
        place: str | None = None,
        actor: events.Actor | None = None,
        train: str | None = None,
    ) -> None:
        if train is None and call is not None:
            train = self.calls[call][0].id if call in self.calls else None
        elif train is None and leg is not None:
            train = leg.train.id
            call = leg.arrival.id if kind in _AT_ARRIVAL else leg.departure.id
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
                actor=actor or self._actor(command),
                message_id=command.message_id if command else None,
                place=command.place if command else place,
                train=train,
                call=call,
                data=data,
            )
        )

    @staticmethod
    def _actor(command: station.Command | None) -> events.Actor:
        if command is None:
            return events.Actor(kind=events.ActorKind.SYSTEM)
        if command.client_id == AUTOMATION:
            return events.Actor(kind=events.ActorKind.AUTOMATION, id=AUTOMATION)
        return events.Actor(kind=events.ActorKind.CLIENT, id=command.client_id)

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
        self._writable()
        if control.action == events.ClockAction.JUMP:
            self._transition("jump", now, lambda: self._jump(control, now))
            self._apply_if_waiting(now)
            return
        if control.action == events.ClockAction.UNDO_JUMP:
            self._transition("undo", now, lambda: self._undo_jump(control, now))
            self._apply_if_waiting(now)
            return
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
        self._record(
            kind, {"seconds": seconds, "speed": speed}, now, seconds=seconds, actor=_DISPATCHER
        )

    # --- Påbörjat och klart (DRIFT-47) -----------------------------------------------------

    def _transition(
        self,
        kind: str,
        now: datetime,
        action: Callable[[], None],
        actor: events.Actor | None = None,
    ) -> None:
        """A version switch, a time jump, Ångra or a new day, between two events. Written in one
        transaction, so a restart sees both or neither; should it ever see only the first,
        Drift starts locked."""
        who = actor or _DISPATCHER
        self._record(events.EventKind.TRANSITION_BEGUN, {"kind": kind}, now, actor=who)
        action()
        self._record(events.EventKind.TRANSITION_DONE, {"kind": kind}, now, actor=who)

    def _writable(self) -> None:
        if self.locked is not None:
            raise Refused(Reason.DRIFT_LOCKED)

    def unlock(self, now: datetime) -> None:
        """Lås upp: Trafikledningen has looked at the state and lets Drift go on from it."""
        if self.locked is None:
            raise Refused(Reason.NOT_LOCKED)
        self._record(
            events.EventKind.TRANSITION_DONE,
            {"kind": self.locked, "unlocked": True},
            now,
            actor=_DISPATCHER,
        )

    # --- Versionsbyte (TRAFIK-03, DRIFT-29, H2, H4, H38, H66) ---------------------------------

    def _version(self, number: int) -> MeetPackage:
        if number == self.start_version:
            return self.start_package
        try:
            if self.packages is None:
                raise LookupError(number)
            return self.packages(number)
        except LookupError as error:
            raise Refused(Reason.UNKNOWN_VERSION) from error

    def switch_waits_for(self, number: int) -> list[str]:
        """The trains the new version changes that are out or have an open clearance (H38)."""
        new = self._version(number)
        old_trains = {t.id: t for t in self.base.trains}
        new_trains = {t.id: t for t in new.trains}
        trains = {
            k
            for k in old_trains.keys() | new_trains.keys()
            if old_trains.get(k) != new_trains.get(k)
        }
        old_sections = {s.id: s for s in self.base.sections}
        new_sections = {s.id: s for s in new.sections}
        sections = {
            k
            for k in old_sections.keys() | new_sections.keys()
            if old_sections.get(k) != new_sections.get(k)
        }
        return sorted(
            {
                case.leg.train.number
                for case in self.cases.values()
                if case.active and (case.leg.train.id in trains or case.leg.section.id in sections)
            }
        )

    def small_correction(self, number: int) -> bool:
        """Små rättelser (F5, DRIFT-31): the version changes only times and tracks, and only of
        trains that have not run yet and have no open clearance. Such a version is taken at
        once; anything else waits for Trafikledningen."""
        new = self._version(number)
        same = ("places", "sections", "duties", "turns")
        if any(getattr(new, part) != getattr(self.base, part) for part in same):
            return False
        if new.meet.clearance_mode != self.base.meet.clearance_mode:
            return False
        old_trains = {t.id: t for t in self.base.trains}
        new_trains = {t.id: t for t in new.trains}
        if old_trains.keys() != new_trains.keys():
            return False
        ran = {leg.train.id for key, leg in self.legs.items() if key in self.arrived}
        ran |= {case.leg.train.id for case in self.cases.values() if case.active or case.departed}

        def bare(call: Call) -> Call:
            return call.model_copy(
                update={"arrival": None, "departure": None, "track": None, "day_offset": 0}
            )

        changed = False
        for train_id, old in old_trains.items():
            new_train = new_trains[train_id]
            if old == new_train:
                continue
            changed = True
            if train_id in ran:
                return False
            if old.model_copy(update={"calls": []}) != new_train.model_copy(update={"calls": []}):
                return False
            if [bare(c) for c in old.calls] != [bare(c) for c in new_train.calls]:
                return False
        return changed

    def switch_version(
        self,
        request: events.SwitchVersion,
        included: list[str],
        now: datetime,
        *,
        small: bool = False,
    ) -> None:
        """Byt till en ny version (DRIFT-29): the clock, where the trains stand and the open
        clearances go with it. The changes the planner took into it fall away, those let go
        too; the rest stay on top (H4, H66). A train that the version changes and that is out
        makes the switch wait until it is in, unless it is forced through (H38)."""
        self._writable()
        if request.version == self.version:
            raise Refused(Reason.SAME_VERSION)
        waits = self.switch_waits_for(request.version)
        switch = {
            "version": request.version,
            "drop": [c for c in request.drop if c in self.changes],
            "included": [c for c in included if c in self.changes],
            "forced": bool(waits) and request.force,
            "small": small,
        }
        if waits and not request.force:
            self._record(events.EventKind.VERSION_WAITING, switch, now, actor=_DISPATCHER)
            return
        self._transition(
            "version",
            now,
            lambda: self._record(events.EventKind.VERSION_SWITCHED, switch, now, actor=_DISPATCHER),
        )
        self._apply_if_waiting(now)

    def force_switch(self, now: datetime) -> None:
        """Tvinga igenom the waiting switch, with what was kept and let go (H38)."""
        self._writable()
        waiting = self.waiting_switch
        if waiting is None:
            raise Refused(Reason.NO_SWITCH_WAITING)
        forced = waiting.model_copy(update={"forced": True}).model_dump(mode="json")
        self._transition(
            "version",
            now,
            lambda: self._record(events.EventKind.VERSION_SWITCHED, forced, now, actor=_DISPATCHER),
        )
        self._apply_if_waiting(now)

    def call_off_switch(self, now: datetime) -> None:
        """Avbryt bytet: the waiting switch is not made."""
        self._writable()
        if self.waiting_switch is None:
            raise Refused(Reason.NO_SWITCH_WAITING)
        self._record(events.EventKind.VERSION_CALLED_OFF, {}, now, actor=_DISPATCHER)

    def _jump(self, control: events.ClockControl, now: datetime) -> None:
        """Tidshopp (H37, F6): one event, so it is all or nothing. The open cases are closed
        and the trains placed by the timetable at the new time; the clock goes on from there
        if it ran. Logg shows it at the time it was made."""
        if control.game_day not in (None, self.game_day):
            raise Refused(Reason.OTHER_GAME_DAY)
        assert control.time is not None  # The contract asks for it.
        before = self.clock.at(now)
        closed = [case.id for case in self.cases.values() if case.active]
        self._record(
            events.EventKind.TIME_JUMP,
            {"before": before, "seconds": float(parse_time(control.time)), "closed": closed},
            now,
            seconds=before,
            actor=_DISPATCHER,
        )

    def _undo_jump(self, control: events.ClockControl, now: datetime) -> None:
        """Ångra (F6): only the latest jump, until the next one. Asked for by number, a jump
        someone else has made since is not undone by mistake."""
        jump = self.last_jump
        if jump is None or control.jump not in (None, jump.seq):
            raise Refused(Reason.NO_JUMP_TO_UNDO)
        day = jump.kind == events.EventKind.DAY_CHANGED
        model = events.DayChanged if day else events.TimeJumped
        before = model.model_validate(jump.data).before
        self._record(
            events.EventKind.TIME_JUMP_UNDONE,
            {"jump": jump.seq, "seconds": before, "kind": "day" if day else "time"},
            now,
            actor=_DISPATCHER,
        )

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
                self.last_jump = None
                self._place(self.clock.seconds)
            case events.EventKind.TIME_JUMP:
                jump = events.TimeJumped.model_validate(event.data)
                self._close_cases()
                self.clock = replace(self.clock, seconds=jump.seconds, updated=event.wall_time)
                self._place(jump.seconds)
                self._touch_everything()
                if self.first_run is not None:
                    # Back before the automation started: the trains from there are no history.
                    self.first_run = min(self.first_run, jump.seconds)
                self.last_jump = event
            case events.EventKind.DAY_CHANGED:
                changed = events.DayChanged.model_validate(event.data)
                self._close_cases()
                self._set_traffic_day(changed.traffic_day)
                self.game_day = changed.game_day
                self.clock = replace(self.clock, seconds=changed.seconds, updated=event.wall_time)
                self._place(changed.placed)
                self._touch_everything()
                if self.first_run is not None:
                    # The automation runs the new day from its first train (old new_day).
                    self.first_run = changed.placed
                self.last_jump = event
            case events.EventKind.DAY_SETTINGS:
                self.day_settings = events.DaySettings.model_validate(event.data)
            case events.EventKind.TRANSITION_BEGUN:
                self.transition = events.Transition.model_validate(event.data).kind
            case events.EventKind.TRANSITION_DONE:
                self.transition = None
                self.locked = None
            case events.EventKind.VERSION_WAITING:
                self.waiting_switch = events.VersionSwitch.model_validate(event.data)
            case events.EventKind.VERSION_CALLED_OFF:
                self.waiting_switch = None
            case events.EventKind.VERSION_SWITCHED:
                switch = events.VersionSwitch.model_validate(event.data)
                self.base = self._version(switch.version)
                self.version = switch.version
                for change_id in (*switch.drop, *switch.included):
                    state = self.changes.get(change_id)
                    if state is not None:
                        self.changes[change_id] = replace(state, status=events.ChangeStatus.DROPPED)
                self.waiting_switch = None
                # Ångra goes no further back than a version switch.
                self.last_jump = None
                self._relay()
            case events.EventKind.CHANGE_MADE:
                made = events.ChangeMade.model_validate(event.data)
                self.changes[made.change_id] = ChangeState(
                    made.change_id,
                    made.change,
                    events.ChangeStatus.WAITING if made.waiting else events.ChangeStatus.APPLIED,
                    made.forced,
                    event.model_time,
                    made.train_number,
                )
                if not made.waiting:
                    self._lay(made.change_id)
            case events.EventKind.CHANGE_APPLIED:
                ref = events.ChangeRef.model_validate(event.data)
                state = self.changes[ref.change_id]
                self.changes[ref.change_id] = replace(
                    state,
                    status=events.ChangeStatus.APPLIED,
                    forced=state.forced or ref.forced,
                )
                self._lay(ref.change_id)
            case events.EventKind.CHANGE_DROPPED:
                change_id = events.ChangeRef.model_validate(event.data).change_id
                state = self.changes[change_id]
                self.changes[change_id] = replace(state, status=events.ChangeStatus.DROPPED)
                if change_id in self.applied:
                    self._relay()
            case events.EventKind.PLACE_PHONE:
                assert event.place is not None
                self.phones[event.place] = events.PhoneChanged.model_validate(event.data).phone
                # Every TKL and app has every place's number in its phone list (H24).
                self._touch_places(*self.stops())
            case events.EventKind.TIME_JUMP_UNDONE:
                undone = events.TimeJumpUndone.model_validate(event.data)
                before = self.history[: undone.jump - 1]
                assert self.history[undone.jump - 1].kind in _UNDOABLE
                self._restore(
                    # From the version itself: the driftändringar before the jump are in the
                    # events and are laid on again as they replay.
                    Drift(
                        self.start_package,
                        before,
                        now=event.wall_time,
                        version=self.start_version,
                        packages=self.packages,
                    ),
                    undone.seconds,
                    event.wall_time,
                )
                self.last_jump = None
            case (
                events.EventKind.CLOCK_STARTED
                | events.EventKind.CLOCK_STOPPED
                | events.EventKind.CLOCK_SPEED
            ):
                clock = events.ClockChanged.model_validate(event.data)
                running = event.kind == events.EventKind.CLOCK_STARTED or (
                    self.clock.running and event.kind == events.EventKind.CLOCK_SPEED
                )
                if running and not self.clock.running:
                    self.running_since = event.wall_time
                self.clock = Clock(clock.seconds, clock.speed, running, event.wall_time)
                if running and self.first_run is None and self.automation.enabled:
                    self.first_run = clock.seconds
                self._touch_places(*{call.place for _, call in self.calls.values()})
            case events.EventKind.CLEARANCE_REQUESTED:
                requested = events.ClearanceRequested.model_validate(event.data)
                assert event.call is not None
                self.cases[requested.clearance_id] = Case(
                    requested.clearance_id, self.legs[event.call], since=event.wall_time
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
            case events.EventKind.CLEARANCE_REMINDED:
                reminded = events.ClearanceReminded.model_validate(event.data)
                case = self.cases[reminded.clearance_id]
                # A reminder is no answer: the case keeps its revision, so an answer on its
                # way is not refused as stale; the places are told to read again.
                self.cases[case.id] = replace(case, reminders=reminded.count, since=event.wall_time)
                self._touch_places(case.leg.departure.place, case.leg.arrival.place)
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
                self.departed_seconds[case.leg.departure.id] = self.clock.at(event.wall_time)
                self._touch(case.leg)
            case events.EventKind.TRAIN_ARRIVED:
                arrival = events.TrainArrived.model_validate(event.data)
                case = self.cases[arrival.clearance_id]
                self.cases[case.id] = replace(
                    case, departed=True, arrived=True, revision=case.revision + 1
                )
                self._arrive(case.leg, arrival.track)
                self.arrived_seconds[case.leg.departure.id] = self.clock.at(event.wall_time)
                self._touch(case.leg)
            case events.EventKind.TRAIN_MOVED_HERE:
                assert event.call is not None
                moved = events.TrainMovedHere.model_validate(event.data)
                self._arrive(self.by_arrival[event.call], moved.track)
                self.arrived_seconds[self.by_arrival[event.call].departure.id] = self.clock.at(
                    event.wall_time
                )
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
            case events.EventKind.PLACE_MANNED:
                assert event.place is not None
                self.manned[event.place] = events.PlaceManned.model_validate(event.data).client_id
                self._touch_places(event.place)
            case events.EventKind.PLACE_LEFT:
                assert event.place is not None
                self.left[event.place] = events.PlaceLeft.model_validate(event.data)
                self.manned.pop(event.place, None)
                self._touch_places(event.place)
            case events.EventKind.PLACE_TAKEN_BACK:
                assert event.place is not None
                back = events.PlaceTakenBack.model_validate(event.data)
                self.left.pop(event.place, None)
                self.manned[event.place] = back.client_id
                self._touch_places(event.place)
            case events.EventKind.AUTOMATION_SET:
                self.automation = events.AutomationSettings.model_validate(event.data)
                if self.automation.enabled and self.first_run is None and self.clock.running:
                    # Trains planned before the automation first ran are history.
                    self.first_run = self.clock.at(event.wall_time)
                self._touch_places(*self.stops())
            case _:
                raise ValueError(f"Okänd händelse i Provbanans logg: {event.kind}")
        self.history.append(event)

    # --- The automation's state (F14): who works a place --------------------------------

    def stops(self) -> list[str]:
        return [p.id for p in self.package.places if p.kind != PlaceKind.HALT]

    def automatic(self, place: str) -> bool:
        """Does the automation work the place? Left to it, or never worked by a box or TKL.
        A manned place out of contact is still manned: it waits for its operator."""
        return place in self.unmanned or place in self.left or place not in self.manned

    def left_here(self, place: str) -> bool:
        """What a box or TKL at the place goes by: the automation is on and someone left
        this place to it. A place nobody has worked yet is automatic too, but the first box
        or TKL there simply mans it."""
        return self.automation.enabled and (place in self.left or place in self.unmanned)

    def man(self, place: str, client: str, now: datetime) -> bool:
        """The first box or TKL that works a place mans it. Not a place left to the
        automation: whoever is there takes it back first."""
        if place in self.manned or place in self.left or place not in self.stops():
            return False
        self._record(
            events.EventKind.PLACE_MANNED,
            {"client_id": client},
            now,
            place=place,
            actor=events.Actor(kind=events.ActorKind.CLIENT, id=client),
        )
        return True

    def leave(
        self, place: str, by: events.LeftBy, now: datetime, client: str | None = None
    ) -> bool:
        """Lämna till automatiken: until someone takes it back, also over a new day."""
        if place not in self.stops():
            raise Refused(Reason.WRONG_PLACE)
        if by == events.LeftBy.OPERATOR and not self.automation.enabled:
            raise Refused(Reason.AUTOMATION_OFF)
        if place in self.left:
            return False
        actor = (
            events.Actor(kind=events.ActorKind.DISPATCHER)
            if by == events.LeftBy.DISPATCHER
            else events.Actor(kind=events.ActorKind.AUTOMATION, id=AUTOMATION)
            if by == events.LeftBy.LOST_CONTACT
            else events.Actor(kind=events.ActorKind.CLIENT, id=client)
        )
        owner = client or self.manned.get(place)
        data: dict[str, object] = {"by": by.value}
        if owner:
            data["client_id"] = owner
        self._record(events.EventKind.PLACE_LEFT, data, now, place=place, actor=actor)
        return True

    def take_back(self, place: str, client: str, by: str, now: datetime) -> None:
        """Ta tillbaka: a box or TKL in contact at the place works it again."""
        if place not in self.stops():
            raise Refused(Reason.WRONG_PLACE)
        actor = (
            events.Actor(kind=events.ActorKind.DISPATCHER)
            if by == "dispatcher"
            else events.Actor(kind=events.ActorKind.CLIENT, id=client)
        )
        self._record(
            events.EventKind.PLACE_TAKEN_BACK,
            {"by": by, "client_id": client},
            now,
            place=place,
            actor=actor,
        )

    def set_automation(self, settings: events.AutomationSettings, now: datetime) -> None:
        self._record(
            events.EventKind.AUTOMATION_SET,
            settings.model_dump(mode="json"),
            now,
            actor=_DISPATCHER,
        )

    def _arrive(self, leg: Leg, track: str | None) -> None:
        self.arrived.add(leg.departure.id)
        if track is not None:
            self.tracks[leg.departure.id] = track

    # --- Where the trains stand by the timetable (DRIFT-43), and Ångra (F6) ---------------

    def _place(self, seconds: float) -> None:
        """Every train where the timetable has it at the time, as the old Server's
        timetable_placement: what it should have run is run, and it stands where it last came
        in, on the planned track, counted as arrived. A train the timetable has on the line
        has no clearance and waits at the departure place (held). One without a track gets a
        free standard track of its own. What was reported before is let go: the hand-set
        tracks, TKL's two declarations, the trains put away and ledig linje."""
        self.arrived.clear()
        self.held.clear()
        self.tracks.clear()
        self.set_aside.clear()
        self.assigned.clear()
        self.positioned.clear()
        self.crew_ready.clear()
        self.lines.clear()
        self.departed_seconds.clear()
        self.arrived_seconds.clear()
        arrivals: dict[str, float] = {}
        for key, leg in self.legs.items():
            times = leg_times(leg)
            if times is None or (leg.previous in self.legs and leg.previous not in self.arrived):
                continue  # Without times the train stops here, as in the old Server.
            _, departure, arrival = times
            if arrival <= seconds:
                self.arrived.add(key)
                arrivals[key] = arrival
            elif departure < seconds:
                self.held.add(key)
        for key in sorted(arrivals, key=lambda found: (arrivals[found], found)):
            leg = self.legs[key]
            track = leg.arrival.track if self._gone_on(key) else self.planned_track(leg)
            if track is not None:
                self.tracks[key] = track

    def _close_cases(self) -> None:
        """A jump or a new day closes the open cases (H37)."""
        for case in list(self.cases.values()):
            if case.active:
                self.cases[case.id] = replace(
                    case, status=station.ClearanceStatus.CANCELLED, revision=case.revision + 1
                )

    # --- Dygnsskiftet (F7, DRIFT-45): the next game day and its traffic day -----------------

    def _first(self, day: Weekday, *, departures: bool) -> float | None:
        """The day's first train movement in its timetable: an arrival or a departure, or only
        a departure, before midnight's calls of the night after."""
        times = [
            parse_time(time)
            for train in self.package.trains
            if day in train.days
            for call in train.calls
            if call.day_offset == 0
            for time in ((call.departure,) if departures else (call.arrival, call.departure))
            if time
        ]
        return min(times, default=None)

    def day_change_at(self) -> tuple[float, bool]:
        """When the next game day starts, in seconds after midnight, and whether the time is
        set by Trafikledningen."""
        if self.day_settings.time is not None:
            return float(parse_time(self.day_settings.time)), True
        first = self._first(next_weekday(self.traffic_day), departures=False)
        if first is None:
            return float(DAY_CHANGE_DEFAULT), False
        return float(max(0, first - DAY_CHANGE_LEAD)), False

    def day_running(self) -> bool:
        """Do the day's trains still run (old Server's _old_day_running)? An open clearance, a
        ledig linje not yet acknowledged, or a train that has left for real and has calls
        after midnight still to come."""
        if any(case.active for case in self.cases.values()):
            return True
        if any(not line.acknowledged for line in self.lines.values()):
            return True
        by_train: dict[str, list[Leg]] = {}
        for leg in self.legs.values():
            by_train.setdefault(leg.train.id, []).append(leg)
        for legs in by_train.values():
            if not any(leg.arrival.day_offset for leg in legs):
                continue
            run = any(
                leg.departure.id in self.departed_seconds
                or leg.departure.id in self.arrived_seconds
                for leg in legs
            )
            if run and legs[-1].departure.id not in self.arrived:
                return True
        return False

    def day_status(self, now: datetime) -> events.DayStatus:
        clock = self.clock.at(now)
        change, fixed = self.day_change_at()
        passed = clock >= SECONDS_PER_DAY + change
        manual = self.day_settings.mode == events.DayChangeMode.MANUAL
        first = self._first(next_weekday(self.traffic_day), departures=False)
        return events.DayStatus(
            mode=self.day_settings.mode,
            time=model_time(change),
            fixed=fixed,
            first=None if first is None else model_time(first),
            next_game_day=self.game_day + 1,
            next_traffic_day=next_weekday(self.traffic_day),
            suggested=model_time(clock - SECONDS_PER_DAY if clock >= SECONDS_PER_DAY else change),
            due=manual and passed,
            waiting=not manual and passed and self.day_running(),
        )

    def new_day(self, request: events.NewDay, now: datetime, *, automatic: bool = False) -> None:
        """Starta ny dag (old Server's start_new_day), or the automatic day change. The clock
        stands at the time asked for and goes on if it ran. Every train stands where the
        timetable has it just before the day's first departure, so each is at its start
        (DRIFT-43). Started from Nu, a train still out stops it: it runs to the end first."""
        self._writable()
        if not automatic and self.day_running():
            raise Refused(Reason.DAY_STILL_RUNNING)
        clock = self.clock.at(now)
        change, _ = self.day_change_at()
        if request.time is not None:
            seconds = float(parse_time(request.time))
        else:
            seconds = clock - SECONDS_PER_DAY if clock >= SECONDS_PER_DAY else change
        day = next_weekday(self.traffic_day)
        first = self._first(day, departures=True)
        placed = seconds if first is None else max(0.0, min(seconds, first - 1))
        who = events.Actor(kind=events.ActorKind.SYSTEM) if automatic else _DISPATCHER

        def record() -> None:
            self._record(
                events.EventKind.DAY_CHANGED,
                {
                    "game_day": self.game_day + 1,
                    "traffic_day": day.value,
                    "before": clock,
                    "seconds": seconds,
                    "placed": placed,
                    "closed": [case.id for case in self.cases.values() if case.active],
                    "automatic": automatic,
                },
                now,
                seconds=clock,
                actor=events.Actor(kind=events.ActorKind.SYSTEM) if automatic else _DISPATCHER,
            )

        self._transition("day", now, record, actor=who)
        self._apply_if_waiting(now)

    def day_tick(self, now: datetime) -> None:
        """The automatic day change, in the hub's round: when the clock passes the time after
        midnight, unless the day's trains are still out; for them it waits at most 30 game
        minutes (old Server). By hand, Nu only says it is time (due)."""
        if not self.clock.running or self.day_settings.mode != events.DayChangeMode.AUTOMATIC:
            return
        clock = self.clock.at(now)
        change, _ = self.day_change_at()
        if clock < SECONDS_PER_DAY + change:
            return
        if clock < SECONDS_PER_DAY + change + DAY_CHANGE_WAIT and self.day_running():
            return
        self.new_day(events.NewDay(), now, automatic=True)

    # --- Driftändringar (DRIFT-41, TRAFIK-02, H38) -------------------------------------------

    def waiting_for(self, change: events.DriftChange) -> list[str]:
        """The trains a change touches that are out or have an open clearance (H38)."""
        trains, sections = driftchanges.touches(self.package, change)
        return sorted(
            {
                case.leg.train.number
                for case in self.cases.values()
                if case.active and (case.leg.train.id in trains or case.leg.section.id in sections)
            }
        )

    def make_change(self, request: events.MakeChange, now: datetime, change_id: str) -> None:
        """A driftändring from Nu. It applies at once, or waits until the trains it touches
        are in, unless it is forced through (H38). One that cannot be made is refused."""
        self._writable()
        try:
            driftchanges.apply(self.package, request.change, change_id)
            busy = self.waiting_for(request.change)
        except driftchanges.ChangeError as error:
            raise Refused(error.reason) from error
        train, place = self._target(request.change)
        self._record(
            events.EventKind.CHANGE_MADE,
            {
                "change_id": change_id,
                "change": request.change.model_dump(mode="json"),
                "waiting": bool(busy) and not request.force,
                "forced": bool(busy) and request.force,
                "train_number": self._number(train),
            },
            now,
            actor=_DISPATCHER,
            train=train,
            place=place,
        )
        self.apply_waiting(now)

    def drop_change(self, change_id: str, now: datetime) -> None:
        """Släpp: the change no longer applies. The version that runs is as before it."""
        self._writable()
        state = self.changes.get(change_id)
        if state is None or state.status == events.ChangeStatus.DROPPED:
            raise Refused(Reason.UNKNOWN_CHANGE)
        train, place = self._target(state.change)
        self._record(
            events.EventKind.CHANGE_DROPPED,
            {"change_id": change_id},
            now,
            actor=_DISPATCHER,
            train=train,
            place=place,
        )

    def force_change(self, change_id: str, now: datetime) -> None:
        """Tvinga igenom (H38): a waiting change applies now, though its train is out. What no
        longer runs is closed."""
        self._writable()
        state = self.changes.get(change_id)
        if state is None or state.status != events.ChangeStatus.WAITING:
            raise Refused(Reason.UNKNOWN_CHANGE)
        try:
            driftchanges.apply(self.package, state.change, change_id)
        except driftchanges.ChangeError as error:
            raise Refused(error.reason) from error
        train, place = self._target(state.change)
        self._record(
            events.EventKind.CHANGE_APPLIED,
            {"change_id": change_id, "forced": True},
            now,
            actor=_DISPATCHER,
            train=train,
            place=place,
        )

    def _number(self, train: str | None) -> str | None:
        return next((t.number for t in self.package.trains if t.id == train), None)

    def apply_waiting(self, now: datetime) -> None:
        """A waiting change applies as soon as the trains it touches are in (H38). One that
        can no longer be made, because what it pointed at is gone, is let go."""
        for state in list(self.changes.values()):
            if state.status != events.ChangeStatus.WAITING or self.waiting_for(state.change):
                continue
            try:
                driftchanges.apply(self.package, state.change, state.id)
                kind = events.EventKind.CHANGE_APPLIED
            except driftchanges.ChangeError:
                kind = events.EventKind.CHANGE_DROPPED
            train, place = self._target(state.change)
            self._record(kind, {"change_id": state.id}, now, train=train, place=place)

    def _target(self, change: events.DriftChange) -> tuple[str | None, str | None]:
        """What Logg files a change under: its train, or its place."""
        train = getattr(change, "train", None)
        call = getattr(change, "call", None)
        if train is None and call is not None:
            try:
                train = driftchanges.train_of_call(self.package, call)[0].id
            except driftchanges.ChangeError:
                train = None
        if train is not None:
            return train, None
        place = getattr(change, "place", None) or getattr(change, "from_place", None)
        return None, place if isinstance(place, str) else None

    def _lay(self, change_id: str) -> None:
        state = self.changes[change_id]
        self.package = driftchanges.apply(self.package, state.change, change_id)
        self.applied.append(change_id)
        self._rebuild()

    def _relay(self) -> None:
        """A change let go: the version again, with the others laid on in their order. One that
        leaned on the change let go goes too."""
        self.package = self.base
        kept: list[str] = []
        for change_id in self.applied:
            state = self.changes[change_id]
            if state.status != events.ChangeStatus.APPLIED:
                continue
            try:
                self.package = driftchanges.apply(self.package, state.change, change_id)
                kept.append(change_id)
            except driftchanges.ChangeError:
                self.changes[change_id] = replace(state, status=events.ChangeStatus.DROPPED)
        self.applied = kept
        self._rebuild()

    def _rebuild(self) -> None:
        """The day's legs again from the package, and what the trains had done, for those
        still there. A case on a leg that is gone is closed; the rest see their new leg."""
        self._set_traffic_day(self.traffic_day)
        self._prune()
        base_kinds = {p.id: p.kind for p in self.base.places}
        self.unmanned = {
            p.id
            for p in self.package.places
            if p.kind == PlaceKind.UNMANNED and base_kinds.get(p.id) != PlaceKind.UNMANNED
        }
        self._touch_everything()

    def _prune(self) -> None:
        legs, calls = set(self.legs), set(self.calls)
        self.arrived &= legs
        self.held &= legs
        self.set_aside &= legs
        self.tracks = {key: track for key, track in self.tracks.items() if key in legs}
        self.departed_seconds = {k: v for k, v in self.departed_seconds.items() if k in legs}
        self.arrived_seconds = {k: v for k, v in self.arrived_seconds.items() if k in legs}
        self.assigned = {key: track for key, track in self.assigned.items() if key in calls}
        self.positioned &= calls
        self.crew_ready &= calls
        for case in list(self.cases.values()):
            if not case.active:
                continue
            leg = self.legs.get(case.leg.departure.id)
            if leg is None:
                self.cases[case.id] = replace(
                    case, status=station.ClearanceStatus.CANCELLED, revision=case.revision + 1
                )
            else:
                self.cases[case.id] = replace(case, leg=leg)

    def phone(self, place: str) -> str | None:
        """The place's game number: as changed during the meet, else the package's (H30)."""
        if place in self.phones:
            return self.phones[place]
        return next((p.phone for p in self.package.places if p.id == place), None)

    def set_phone(self, change: events.PlacePhone, now: datetime) -> None:
        """Trafikledningen changes a place's number during the meet (TRAFIK-06)."""
        self._writable()
        if change.place not in self.stops():
            raise Refused(Reason.UNKNOWN_PLACE)
        phone = (change.phone or "").strip() or None
        if phone == self.phone(change.place):
            return
        self._record(
            events.EventKind.PLACE_PHONE,
            {"phone": phone},
            now,
            place=change.place,
            actor=_DISPATCHER,
        )

    def set_day(self, settings: events.DaySettings, now: datetime) -> None:
        self._writable()
        self._record(
            events.EventKind.DAY_SETTINGS, settings.model_dump(mode="json"), now, actor=_DISPATCHER
        )

    def _touch_everything(self) -> None:
        """Every call and place has changed: each client reads again."""
        for call in self.calls:
            self.call_revision[call] = self.call_revision.get(call, 0) + 1
        self._touch_places(*self.stops())

    def _restore(self, before: Drift, seconds: float, now: datetime) -> None:
        """Ångra (F6): the trains, the cases and the messages as they were before the jump,
        and the clock at the time it showed then. Who works each place, the automation's
        settings and the clock's speed and running stay as they are. Every revision goes up,
        so that no client acts on what it saw in between."""
        # The driftändringar are Trafikledningen's, like its settings: they stay.
        self.traffic_day = before.traffic_day
        self.game_day = before.game_day
        self.cases = {
            case.id: replace(
                case,
                revision=max(case.revision, getattr(self.cases.get(case.id), "revision", 0)) + 1,
            )
            for case in before.cases.values()
        }
        self.arrived, self.tracks, self.set_aside = before.arrived, before.tracks, before.set_aside
        self.assigned, self.positioned = before.assigned, before.positioned
        self.crew_ready, self.lines, self.held = before.crew_ready, before.lines, before.held
        self.requested_at, self.departed_at = before.requested_at, before.departed_at
        self.departed_seconds = before.departed_seconds
        self.arrived_seconds = before.arrived_seconds
        if before.first_run is not None:
            self.first_run = before.first_run
        elif self.automation.enabled and self.clock.running:
            self.first_run = seconds
        self.clock = replace(self.clock, seconds=seconds, updated=now)
        # A restored request waits anew: the reminders count from now (H39).
        self.running_since = now
        self._set_traffic_day(self.traffic_day)
        self._prune()
        self._touch_everything()

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
        if leg.section.closed:
            return Reason.SECTION_CLOSED
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

    def remind(self, now: datetime) -> None:
        """Remind of every request still unanswered: after 3 minutes and then every 3 minutes,
        real time (H39, DRIFT-33). Only while the clock runs; when it stands, nothing goes out
        (DRIFT-44), and the waiting starts over when it runs again."""
        if not self.clock.running:
            return
        for case in list(self.cases.values()):
            if case.status != station.ClearanceStatus.WAITING or case.departed:
                continue
            since = max(case.since or now, self.running_since)
            if (now - since).total_seconds() >= REMINDER_SECONDS:
                # The place that should answer, as Logg shows it.
                self._record(
                    events.EventKind.CLEARANCE_REMINDED,
                    {"clearance_id": case.id, "count": case.reminders + 1},
                    now,
                    leg=case.leg,
                    place=case.leg.arrival.place,
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
        # What was forgotten is done here, and marked as moved forward in Logg (DRIFT-42).
        if case.status == station.ClearanceStatus.WAITING:
            self._record(
                events.EventKind.CLEARANCE_ANSWERED,
                {"clearance_id": case.id, "approved": True, "forward": True},
                now,
                command=command,
                leg=leg,
            )
        self._record(
            events.EventKind.TRAIN_ARRIVED,
            {"clearance_id": case.id, "track": track, "forward": True},
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
            # Cleared but never reported departed: it came in all the same (DRIFT-42).
            data: dict[str, object] = {"clearance_id": case.id, "track": track}
            if not case.departed:
                data["forward"] = True
            self._record(events.EventKind.TRAIN_ARRIVED, data, now, command=command, leg=leg)

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
        """Carry out one station command, or refuse it with a reason and change nothing. A
        driftändring waiting for the train applies as soon as it is in (H38)."""
        self._writable()
        outcome = self._command(command, now)
        self._apply_if_waiting(now)
        return outcome

    def _apply_if_waiting(self, now: datetime) -> None:
        if any(state.status == events.ChangeStatus.WAITING for state in self.changes.values()):
            self.apply_waiting(now)
        waiting = self.waiting_switch
        if waiting is not None and not self.switch_waits_for(waiting.version):
            self._transition(
                "version",
                now,
                lambda: self._record(
                    events.EventKind.VERSION_SWITCHED,
                    waiting.model_dump(mode="json"),
                    now,
                    actor=_DISPATCHER,
                ),
            )

    def _command(self, command: station.Command, now: datetime) -> Outcome:
        if command.context != self.context:
            raise Refused(Reason.STALE_MEET_CONTEXT)
        if command.client_id == AUTOMATION:
            if not self.automatic(command.place):
                raise Refused(Reason.PLACE_MANNED)
        elif self.left_here(command.place) and command.action not in _ALLOWED_WHEN_LEFT:
            # Ask first: the operator takes the place back, then acts (Casper, 2026-10-10).
            raise Refused(Reason.PLACE_AUTOMATIC)
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
            case station.Action.PLACE_LEAVE:
                self.leave(command.place, events.LeftBy.OPERATOR, now, command.client_id)
                return Outcome(revision=self._place_revision(command.place))
            case station.Action.PLACE_TAKE_BACK:
                if command.place in self.left:
                    self.take_back(command.place, command.client_id, "operator", now)
                return Outcome(revision=self._place_revision(command.place))
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

    def _place_revision(self, place: str) -> station.Revision:
        return station.Revision(
            scope=station.RevisionScope.PLACE, key=place, value=self.place_revision.get(place, 0)
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
