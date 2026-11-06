"""The station protocol's snapshot: everything a client needs for one place, whole every time.

TKL, the TMBox app and the dispatcher's views draw their own screens from it. It says what each
call allows right now (`allowed_actions`), so a client never has to guess a rule (5.2). It is
worked out from Drift's state; the events only tell a client to fetch it again.
"""

from __future__ import annotations

from datetime import datetime

from contracts import station
from contracts.common import Side
from contracts.meet import Place, PlaceKind
from drift.engine import Case, Drift, Leg, model_time


def snapshot(drift: Drift, place: str, now: datetime) -> station.Snapshot:
    """The place as Drift sees it now. Raises KeyError for a place that is not a stop."""
    places = {p.id: p for p in drift.package.places}
    here = places[place]
    if here.kind == PlaceKind.HALT:
        raise KeyError(place)
    seconds = drift.clock.at(now)
    sections = [s for s in drift.package.sections if place in {s.place_a, s.place_b}]
    neighbours = []
    for section in sections:
        other = section.place_b if section.place_a == place else section.place_a
        neighbours.append(_neighbour(places[other]))
    return station.Snapshot(
        place=_neighbour(here),
        context=drift.context,
        clock=station.Clock(
            time=model_time(seconds),
            seconds=int(seconds),
            running=drift.clock.running,
            speed=drift.clock.speed,
            game_day=drift.context.game_day,
        ),
        place_revision=drift.place_revision.get(place, 0),
        sections=[_section(drift, place, section.id, places) for section in sections],
        calls=_calls(drift, place),
        on_the_way=[
            _on_section(drift, case, case.leg.departure.place)
            for case in _cases(drift)
            if case.departed and case.leg.arrival.place == place
        ],
        have_left=[
            _on_section(drift, case, case.leg.arrival.place)
            for case in _cases(drift)
            if case.departed and case.leg.departure.place == place
        ],
        clearances=[
            _clearance(drift, case)
            for case in _cases(drift)
            if place in {case.leg.departure.place, case.leg.arrival.place}
        ],
        line_messages=[
            station.LineMessage(
                message_id=line.id,
                section=line.section,
                from_place=line.from_place,
                call=line.call,
                acknowledged=line.acknowledged,
            )
            for line in drift.lines.values()
            if line.to_place == place and not line.acknowledged
        ],
        neighbours=neighbours,
        all_places=[_neighbour(p) for p in drift.package.places if p.kind != PlaceKind.HALT],
    )


def _neighbour(place: Place) -> station.Neighbour:
    return station.Neighbour(place=place.id, code=place.code, name=place.name, phone=place.phone)


def _cases(drift: Drift) -> list[Case]:
    return [case for case in drift.cases.values() if case.active]


def _section(
    drift: Drift, place: str, section_id: str, places: dict[str, Place]
) -> station.SectionHere:
    section = next(s for s in drift.package.sections if s.id == section_id)
    at_a = section.place_a == place
    other = section.place_b if at_a else section.place_a
    side: Side | None = section.side_at_a if at_a else section.side_at_b
    return station.SectionHere(
        section=section.id,
        other_place=other,
        other_code=places[other].code,
        tracks=section.tracks,
        clearance_mode=section.clearance_mode or drift.package.meet.clearance_mode,
        side=side,
        occupied=any(case.departed and case.leg.section.id == section.id for case in _cases(drift)),
    )


def _on_section(drift: Drift, case: Case, other: str) -> station.TrainOnSection:
    leg = case.leg
    return station.TrainOnSection(
        call=leg.arrival.id,
        train_number=leg.train.number,
        train_type=leg.train.train_type,
        section=leg.section.id,
        other_place=other,
        planned_track=drift.planned_track(leg),
        departed_at=drift.departed_at.get(case.id, model_time(drift.clock.seconds)),
    )


def _clearance(drift: Drift, case: Case) -> station.Clearance:
    leg = case.leg
    return station.Clearance(
        clearance_id=case.id,
        call=leg.departure.id,
        train_number=leg.train.number,
        section=leg.section.id,
        from_place=leg.departure.place,
        to_place=leg.arrival.place,
        status=case.status,
        departed=case.departed,
        requested_at=drift.requested_at.get(case.id, "00:00"),
        revision=case.revision,
    )


def _calls(drift: Drift, place: str) -> list[station.CallHere]:
    """Every call at the place on the traffic day, in timetable order."""
    found = []
    for train, call in drift.calls.values():
        if call.place != place:
            continue
        arriving, leaving = drift.by_arrival.get(call.id), drift.legs.get(call.id)
        found.append(
            (
                call.day_offset,
                call.arrival or call.departure or "99:99",
                train.number,
                station.CallHere(
                    call=call.id,
                    train=train.id,
                    train_number=train.number,
                    train_type=train.train_type,
                    manual=train.manual,
                    arrival=call.arrival,
                    departure=call.departure,
                    day_offset=call.day_offset,
                    planned_track=call.track,
                    track=drift.standing_track(call.id),
                    from_place=arriving.departure.place if arriving else None,
                    to_place=leaving.arrival.place if leaving else None,
                    arrival_state=_arrival_state(drift, arriving),
                    departure_state=_departure_state(drift, leaving),
                    positioned=call.id in drift.positioned,
                    crew_ready=call.id in drift.crew_ready,
                    revision=drift.call_revision.get(call.id, 0),
                    allowed_actions=allowed_actions(drift, call.id),
                ),
            )
        )
    return [item for *_, item in sorted(found, key=lambda entry: entry[:3])]


def _arrival_state(drift: Drift, arriving: Leg | None) -> station.ArrivalState:
    if arriving is None:
        return station.ArrivalState.NONE
    if arriving.departure.id in drift.arrived:
        return station.ArrivalState.ARRIVED
    case = drift.active_case(arriving.departure.id)
    if case is not None and case.departed:
        return station.ArrivalState.ON_THE_WAY
    return station.ArrivalState.NONE


def _departure_state(drift: Drift, leaving: Leg | None) -> station.DepartureState:
    if leaving is None:
        return station.DepartureState.PLANNED
    if drift.departed_from(leaving.departure.id):
        return station.DepartureState.DEPARTED
    case = drift.active_case(leaving.departure.id)
    if case is None:
        return station.DepartureState.PLANNED
    if case.status == station.ClearanceStatus.WAITING:
        return station.DepartureState.REQUESTED
    return station.DepartureState.CLEARED


def allowed_actions(drift: Drift, call: str) -> list[station.Action]:
    """What a client at the call's place may do with it now. Nothing once the train has
    left; the declarations still to make come first (old Server v2)."""
    action = station.Action
    arriving, leaving = drift.by_arrival.get(call), drift.legs.get(call)
    allowed: list[station.Action] = []
    if arriving is not None and arriving.departure.id in drift.set_aside:
        return allowed  # Put away: the train is out of the game here.
    if arriving is not None and arriving.departure.id not in drift.arrived:
        coming = drift.active_case(arriving.departure.id)
        if coming is not None and coming.status == station.ClearanceStatus.WAITING:
            allowed.append(action.CLEARANCE_RESPONSE)
        else:
            allowed.append(action.TRAIN_ARRIVED)  # Also a train nobody sent (2.1.0).
    if leaving is not None:
        if drift.departed_from(call):
            return allowed
        flags = [
            (call in drift.positioned, action.TRAIN_POSITION_SET),
            (call in drift.crew_ready, action.TRAIN_CREW_READY_SET),
        ]
        allowed += [flag for done, flag in sorted(flags, key=lambda item: item[0])]
        case = drift.active_case(call)
        if case is None:
            if drift.request_block(leaving) is None:
                allowed.append(action.CLEARANCE_REQUEST)
        elif case.status == station.ClearanceStatus.WAITING:
            allowed.append(action.CLEARANCE_CANCEL)
        else:
            allowed += [action.TRAIN_DEPARTED, action.CLEARANCE_CANCEL]
        allowed.append(action.LINE_AVAILABLE_PUBLISH)
    elif arriving is not None and drift.ended_here(arriving.departure.id):
        allowed.append(action.TRAIN_SET_ASIDE)
    allowed.append(action.TRAIN_TRACK_CHANGE)
    return allowed
