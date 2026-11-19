"""Nu: the meet as it runs, for the dispatcher's page and for everyone who only looks (S1).

Built from Drift's state like the station snapshot. It holds no names of people, no codes and
no phone numbers, so it can be shown without logging in (B13).
"""

from __future__ import annotations

from datetime import datetime

from contracts import drift as contract
from contracts import station
from contracts.meet import PlaceKind
from drift.drivers import alarms, now_messages
from drift.engine import Drift, Leg, model_time
from drift.snapshot import clearance_of


def now(drift: Drift, at: datetime) -> contract.Now:
    seconds = drift.clock.at(at)
    return contract.Now(
        meet_id=drift.package.meet.id,
        name=drift.package.meet.name,
        version=drift.version,
        traffic_day=drift.traffic_day,
        game_day=drift.game_day,
        clock=station.Clock(
            time=model_time(seconds),
            seconds=int(seconds),
            running=drift.clock.running,
            speed=drift.clock.speed,
            game_day=drift.game_day,
        ),
        places=[
            contract.NowPlace(place=p.id, code=p.code, name=p.name, part_of=p.part_of)
            for p in drift.package.places
            if p.kind != PlaceKind.HALT
        ],
        legs=[_leg(drift, leg) for leg in _in_order(drift)],
        clearances=[clearance_of(drift, case) for case in drift.cases.values() if case.active],
        jump=_jump(drift),
        day=drift.day_status(at),
        switch=contract.SwitchWaiting(
            version=drift.waiting_switch.version,
            waits_for=drift.switch_waits_for(drift.waiting_switch.version),
        )
        if drift.waiting_switch is not None
        else None,
        locked=drift.locked,
        changes=[
            contract.ChangeNow(
                change_id=state.id,
                change=state.change,
                status=state.status,
                forced=state.forced,
                train_number=state.train_number,
                made=state.made,
                waiting_for=drift.waiting_for(state.change)
                if state.status == contract.ChangeStatus.WAITING
                else [],
            )
            for state in drift.changes.values()
        ],
        # Lokföraren (LOK-23, LOK-35): no names, only the trains and the services.
        driver_alarms=alarms(drift),
        driver_messages=now_messages(drift, at),
        detected=[
            contract.DetectedSection(
                section=section.id,
                place_a=section.place_a,
                place_b=section.place_b,
                by=drift.detected_by(section.id),
            )
            for section in drift.package.sections
            if drift.detected(section.id)
        ],
    )


def _jump(drift: Drift) -> contract.LastJump | None:
    """The latest time jump or new day, while Ångra can take it back (F6)."""
    event = drift.last_jump
    if event is None:
        return None
    if event.kind == contract.EventKind.DAY_CHANGED:
        day = contract.DayChanged.model_validate(event.data)
        return contract.LastJump(
            seq=event.seq,
            kind="day",
            from_time=model_time(day.before),
            to_time=model_time(day.seconds),
            game_day=day.game_day,
            traffic_day=day.traffic_day,
            closed=len(day.closed),
            wall_time=event.wall_time,
        )
    jump = contract.TimeJumped.model_validate(event.data)
    return contract.LastJump(
        seq=event.seq,
        from_time=model_time(jump.before),
        to_time=model_time(jump.seconds),
        game_day=drift.game_day,
        traffic_day=drift.traffic_day,
        closed=len(jump.closed),
        wall_time=event.wall_time,
    )


def _in_order(drift: Drift) -> list[Leg]:
    return sorted(
        drift.legs.values(),
        key=lambda leg: (
            leg.departure.day_offset,
            leg.departure.departure or leg.departure.arrival or "99:99",
            leg.train.number,
        ),
    )


def _leg(drift: Drift, leg: Leg) -> contract.LegNow:
    key = leg.departure.id
    case = drift.active_case(key)
    state: contract.LegState = "planned"
    if key in drift.arrived:
        state = "arrived"
    elif case is not None and case.departed:
        state = "on_the_way"
    elif case is not None and case.status == station.ClearanceStatus.APPROVED:
        state = "cleared"
    elif case is not None:
        state = "requested"
    return contract.LegNow(
        leg=key,
        train=leg.train.id,
        train_number=leg.train.number,
        train_type=leg.train.train_type,
        section=leg.section.id,
        from_place=leg.departure.place,
        to_place=leg.arrival.place,
        departure=leg.departure.departure,
        arrival=leg.arrival.arrival,
        state=state,
        clearance_id=case.id if case is not None else None,
        track=drift.tracks.get(key) if key in drift.arrived else drift.planned_track(leg),
        paper=leg.train.id in drift.drivers.paper_trains,
    )
