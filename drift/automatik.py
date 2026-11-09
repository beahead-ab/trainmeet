"""Automatiken: the places nobody works still answer and send trains (F14, F15, H41, H42).

Ported from the old Server's automatic.py (issue #115) with its tests as the key. A place
nobody operates still has to answer and send trains, or a manned neighbour waits for an
answer that never comes. While the meet clock runs, every place without a box or TKL in use
is automatic: it clears a request when the planned track is free, asks for and reports the
departure of its own trains when they are ready, and reports an arrival once the timetable's
running time has passed since the departure.

The first box or TKL that works a place makes it manned. A manned place whose operator loses
contact waits for that operator, unless the dispatcher has chosen that the automation takes
over after some minutes without contact. The dispatcher, and the place's own box or TKL, can
leave the place to the automation ("going to the toilet") and take it back; that choice
stands until someone changes it. While the automation works a place, a traffic key on its box
or TKL first asks to take the place back (Casper, 2026-10-10).

Who works a place, the settings and every act are Drift events, so a restart reads them back.
Only the contact (who was heard when) lives in memory: after a restart nobody has been heard
yet, and that is not minutes of silence. The automation acts through the same station
commands as a box, under its own name, and Drift refuses it at a manned place.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from time import monotonic
from typing import Any, Final
from uuid import uuid4

from contracts import drift as events
from contracts import station
from contracts.reasons import TEXT_SV
from drift.engine import AUTOMATION, SECONDS_PER_DAY, Drift, Leg, Refused, parse_time

# The automation asks at the earliest two model minutes before the departure (F14).
REQUEST_LEAD_SECONDS: Final = 120
# (share of the trains in percent, most extra minutes), as the old simulation's profiles (F15).
PROFILES: Final = {
    events.Disturbance.OFF: (0, 0),
    events.Disturbance.NORMAL: (25, 4),
    events.Disturbance.DISRUPTED: (65, 12),
}

Action = station.Action
Status = station.ClearanceStatus


@dataclass(frozen=True)
class Planned:
    """A leg the automation can run, with its times in model seconds."""

    leg: Leg
    departure: float
    arrival: float
    dwell: float

    @property
    def key(self) -> str:
        return self.leg.departure.id

    @property
    def duration(self) -> float:
        return self.arrival - self.departure


def _seconds(time: str | None, day_offset: int) -> float | None:
    return None if time is None else parse_time(time) + day_offset * SECONDS_PER_DAY


def plan(drift: Drift) -> dict[str, Planned]:
    """Every leg of the day the automation can run. A manual train, or a leg without times or
    with an impossible running time, is left to people and stops nothing else (F10)."""
    planned: dict[str, Planned] = {}
    for key, leg in drift.legs.items():
        if leg.train.manual:
            continue
        came = _seconds(leg.departure.arrival, leg.departure.day_offset)
        departure = _seconds(leg.departure.departure, leg.departure.day_offset)
        arrival = _seconds(leg.arrival.arrival or leg.arrival.departure, leg.arrival.day_offset)
        if departure is None or arrival is None:
            continue
        # A visit spanning midnight has one day offset, but two clock times.
        if came is not None and departure < came:
            departure += SECONDS_PER_DAY
        if arrival < departure:
            arrival += SECONDS_PER_DAY
        if not 0 < arrival - departure <= SECONDS_PER_DAY:
            continue
        dwell = departure - came if came is not None else 0.0
        planned[key] = Planned(leg, departure, arrival, dwell)
    return planned


class Automatik:
    """The automation of one running meet. `now` is a monotonic clock in real seconds."""

    def __init__(self, *, now: Callable[[], float] = monotonic) -> None:
        self.now = now
        # Contact is counted from when the hub started: after a restart nobody has been
        # heard yet, and that is not minutes of silence.
        self.started = now()
        self.seen: dict[str, tuple[str, float]] = {}
        # When the automation may answer each waiting request (clearance id -> now()).
        self.answer_at: dict[str, float] = {}
        # The trains the automation waits with, and why (call -> reason), for Nu.
        self.blocked: dict[str, str] = {}

    # --- Contact ------------------------------------------------------------------------

    def observe(self, client: str, place: str) -> None:
        """A box or TKL at work at the place: heard now."""
        self.seen[client] = (place, self.now())

    def last_heard(self, place: str) -> float:
        return max((at for here, at in self.seen.values() if here == place), default=-math.inf)

    def present(self, place: str) -> list[str]:
        """The clients in contact at the place, the one heard last first."""
        now = self.now()
        here = [
            (at, client)
            for client, (where, at) in self.seen.items()
            if where == place and now - at <= events.PRESENCE_SECONDS
        ]
        return [client for _, client in sorted(here, reverse=True)]

    def mode(self, drift: Drift, place: str) -> events.PlaceMode:
        if drift.automatic(place):
            return events.PlaceMode.AUTOMATIC
        # The owner is the first client that worked the place. Another box or TKL there
        # still works it when the owner is gone.
        if self.now() - self.last_heard(place) <= events.PRESENCE_SECONDS:
            return events.PlaceMode.MANNED
        return events.PlaceMode.NO_CONTACT

    def _silent(self, place: str) -> float:
        return self.now() - max(self.last_heard(place), self.started)

    def takes_over_in(self, drift: Drift, place: str) -> int | None:
        """Seconds until the automation takes a place out of contact; None when it never
        will (the default) or the place is not out of contact."""
        minutes = drift.automation.lost_contact_minutes
        if not minutes or self.mode(drift, place) != events.PlaceMode.NO_CONTACT:
            return None
        return max(0, math.ceil(minutes * 60 - self._silent(place)))

    # --- The traffic ----------------------------------------------------------------------

    def tick(self, drift: Drift, now: datetime) -> None:
        """One round: places out of contact too long go to the automation, then every leg it
        can run takes its next step. Nothing moves while it is off or the clock is stopped."""
        settings = drift.automation
        if not settings.enabled or not drift.clock.running:
            return
        seconds = drift.clock.at(now)
        if settings.lost_contact_minutes:
            for place, owner in sorted(drift.manned.items()):
                if self._silent(place) >= settings.lost_contact_minutes * 60:
                    drift.leave(place, events.LeftBy.LOST_CONTACT, now, owner)
        planned = plan(drift)
        start = drift.first_run if drift.first_run is not None else seconds
        order = {case_id: index for index, case_id in enumerate(drift.cases)}

        def priority(item: tuple[str, Planned]) -> tuple[int, float, str]:
            # Requests already waiting go before new timetable cases, oldest first. An
            # occupied track stops only that request, not the rest of the queue.
            key, leg = item
            case = drift.active_case(key)
            if (
                case is not None
                and case.status == Status.WAITING
                and drift.automatic(leg.leg.arrival.place)
            ):
                return (0, float(order[case.id]), case.id)
            return (1, leg.departure, key)

        blocked: dict[str, str] = {}
        for key, leg in sorted(planned.items(), key=priority):
            try:
                reason = self._step(drift, leg, planned, seconds, start, now)
            except Refused as error:
                reason = TEXT_SV[error.reason]
            if reason:
                blocked[key] = reason
        self.blocked = blocked
        # Requests answered or withdrawn elsewhere are not waited for.
        waiting = {case.id for case in drift.cases.values() if case.status == Status.WAITING}
        self.answer_at = {c: at for c, at in self.answer_at.items() if c in waiting}
        if settings.stabling:
            self._stable(drift, planned, seconds, now)

    def _act(
        self, drift: Drift, place: str, action: station.Action, now: datetime, **payload: Any
    ) -> None:
        drift.command(
            station.Command(
                message_id=f"auto-{uuid4().hex}",
                client_id=AUTOMATION,
                place=place,
                context=drift.context,
                action=action,
                payload=payload,
            ),
            now,
        )

    def _step(
        self,
        drift: Drift,
        planned: Planned,
        legs: dict[str, Planned],
        seconds: float,
        start: float,
        now: datetime,
    ) -> str:
        leg, key, settings = planned.leg, planned.key, drift.automation
        sender, receiver = leg.departure.place, leg.arrival.place
        if key in drift.arrived:
            return ""
        case = drift.active_case(key)
        if case is not None and case.departed:
            if not drift.automatic(receiver):
                return "Väntar på mottagarens ankomst"
            departed = drift.departed_seconds.get(key, planned.departure)
            if seconds < departed + planned.duration + self._delay(drift, "line", key):
                return "På väg"
            self._act(
                drift,
                receiver,
                Action.TRAIN_ARRIVED,
                now,
                call=leg.arrival.id,
                track=drift.planned_track(leg),
            )
            return ""
        ready = self._ready_at(drift, planned, legs)
        automatic_sender = drift.automatic(sender)
        if case is None and automatic_sender:
            if math.isinf(ready):
                return "Väntar på föregående ankomst"
            # A train planned before the automation started is history, not a queue to send
            # all at once.
            if leg.previous is None and planned.departure < start:
                return ""
            if seconds < ready - REQUEST_LEAD_SECONDS:
                return ""
            # A refusal is a decision, not an invitation to ask again.
            if any(
                c.leg.departure.id == key and c.status == Status.REJECTED
                for c in drift.cases.values()
            ):
                return "Begäran nekad – kräver operatörsåtgärd"
            clearance = f"auto-{uuid4().hex[:16]}"
            self._act(
                drift,
                sender,
                Action.CLEARANCE_REQUEST,
                now,
                call=key,
                section=leg.section.id,
                clearance_id=clearance,
            )
            case = drift.cases[clearance]
        if case is not None and case.status == Status.WAITING:
            # The answer comes a few real seconds after the request, so that the neighbour
            # sees it wait (Casper, 2026-10-11): as long at 4× as at 1×. Counted from when
            # the automation first saw it, so a request that waited for an operator is
            # answered at once when the place is left to the automation.
            answer_at = self.answer_at.setdefault(case.id, self.now() + settings.answer_seconds)
        if case is not None and case.status == Status.WAITING and drift.automatic(receiver):
            track = drift.planned_track(leg)
            if track is None or drift.occupant(receiver, track, key) is not None:
                return "Mottagningsspåret är upptaget"
            if self.now() < answer_at:
                return "Väntar på klartecken"
            self._act(
                drift,
                receiver,
                Action.CLEARANCE_RESPONSE,
                now,
                clearance_id=case.id,
                approved=True,
            )
            self.answer_at.pop(case.id, None)
            case = drift.cases[case.id]
        if automatic_sender and case is not None and case.status == Status.APPROVED:
            if seconds >= ready:
                self._act(drift, sender, Action.TRAIN_DEPARTED, now, call=key)
                return ""
            if seconds >= planned.departure:
                return "Stationsarbete pågår"
        if case is not None and case.status == Status.WAITING:
            return "Väntar på klartecken"
        return ""

    def _ready_at(self, drift: Drift, planned: Planned, legs: dict[str, Planned]) -> float:
        """When the train may leave: on time the timetable decides. Late, it stands its
        short stop and goes, never longer than the planned stop (Casper, 2026-10-10)."""
        previous = planned.leg.previous
        delay = self._delay(drift, "station", planned.key)
        if previous is None:
            return planned.departure + delay
        if previous not in drift.arrived:
            return math.inf
        prior = legs.get(previous)
        arrived = drift.arrived_seconds.get(
            previous, prior.arrival if prior is not None else planned.departure
        )
        stop = min(planned.dwell, drift.automation.late_stop_minutes * 60)
        return max(planned.departure, arrived + stop) + delay

    def _delay(self, drift: Drift, kind: str, key: str) -> float:
        """Extra model seconds for a train: station work before the departure ("station") or
        a longer running time before the arrival ("line"). The same key gives the same
        delays, as in the old simulation (F15)."""
        settings = drift.automation
        chance, limit = PROFILES[settings.disturbance]
        if not limit or settings.where.value not in (kind, events.DisturbanceWhere.BOTH.value):
            return 0.0
        seed = settings.seed or f"{drift.package.meet.id}:{drift.traffic_day}"
        value = int(sha256(f"{seed}:{kind}:{key}".encode()).hexdigest()[:12], 16)
        return float((1 + value // 100 % limit) * 60) if value % 100 < chance else 0.0

    def _stable(
        self, drift: Drift, planned: dict[str, Planned], seconds: float, now: datetime
    ) -> None:
        """Undanställning at an automatic terminus: a train that came in and ends there is
        put away after some model minutes, so that its track is free for the next one (H41).
        Without it, the train holds its track the rest of the day."""
        wait = drift.automation.stabling_minutes * 60
        for key, leg in planned.items():
            place = leg.leg.arrival.place
            if not drift.ended_here(key) or not drift.automatic(place):
                continue
            if seconds < drift.arrived_seconds.get(key, leg.arrival) + wait:
                continue
            try:
                self._act(drift, place, Action.TRAIN_SET_ASIDE, now, call=leg.leg.arrival.id)
            except Refused:
                continue

    # --- What Nu shows ------------------------------------------------------------------

    def status(self, drift: Drift) -> events.AutomationStatus:
        places = []
        for place in drift.package.places:
            if place.id not in drift.stops():
                continue
            left = drift.left.get(place.id)
            places.append(
                events.AutomationPlaceStatus(
                    place=place.id,
                    name=place.name,
                    code=place.code,
                    mode=self.mode(drift, place.id),
                    left_by=left.by if left else None,
                    takes_over_in=self.takes_over_in(drift, place.id),
                    operator=drift.manned.get(place.id) or (left.client_id if left else None),
                    present=self.present(place.id),
                )
            )
        trains = [
            events.AutomationTrain(
                call=key,
                train=drift.legs[key].train.number,
                from_place=drift.legs[key].departure.place,
                to_place=drift.legs[key].arrival.place,
                reason=reason,
            )
            for key, reason in sorted(self.blocked.items())
            if key in drift.legs
        ]
        return events.AutomationStatus(settings=drift.automation, places=places, trains=trains)
