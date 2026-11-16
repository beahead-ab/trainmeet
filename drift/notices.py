"""Push (F20, SYNK-05): what a phone approved for a place is told, made from the run's events.

Begäran hit goes to the place the train comes to, with Ge klart and Neka in the notice;
the answer goes to the place that asked, and tåg på väg to the place it is on its way to. A
request already answered is not sent: the notice would offer a choice that is gone.
"""

from __future__ import annotations

from contracts import drift as events
from contracts import station
from drift.engine import Case, Drift


def notices(drift: Drift, after: int) -> list[station.Notice]:
    """The notices of the events after seq, in order."""
    names = {place.id: place.name for place in drift.package.places}
    made: list[station.Notice] = []
    for event in drift.history:
        if event.seq <= after:
            continue
        notice = _notice(drift, event, names)
        if notice is not None:
            made.append(notice)
    return made


def _notice(drift: Drift, event: events.DriftEvent, names: dict[str, str]) -> station.Notice | None:
    if event.kind not in {
        events.EventKind.CLEARANCE_REQUESTED,
        events.EventKind.CLEARANCE_REMINDED,
        events.EventKind.CLEARANCE_ANSWERED,
        events.EventKind.TRAIN_DEPARTED,
    }:
        return None
    case = drift.cases.get(events.ClearanceRef.model_validate(event.data).clearance_id)
    if case is None:
        return None
    number = case.leg.train.number
    here, there = case.leg.arrival.place, case.leg.departure.place

    def notice(kind: station.EventKind, place: str, title: str, body: str) -> station.Notice:
        return station.Notice(
            kind=kind,
            place=place,
            title=title,
            body=body,
            train_number=number,
            clearance_id=case.id,
            context=drift.context,
            expected_revision=_revision(case) if kind in _ASKING else None,
            seq=event.seq,
        )

    waiting = case.status == station.ClearanceStatus.WAITING
    match event.kind:
        case events.EventKind.CLEARANCE_REQUESTED if waiting:
            return notice(
                station.EventKind.CLEARANCE_REQUESTED,
                here,
                f"Tåg {number} från {names.get(there, there)}",
                "Begär klart hit. Ge klart eller neka.",
            )
        case events.EventKind.CLEARANCE_REMINDED if waiting:
            return notice(
                station.EventKind.CLEARANCE_REMINDER,
                here,
                f"Tåg {number} väntar på klart",
                f"Begäran från {names.get(there, there)} är inte besvarad.",
            )
        case events.EventKind.CLEARANCE_ANSWERED:
            approved = events.ClearanceAnswered.model_validate(event.data).approved
            return notice(
                station.EventKind.CLEARANCE_ANSWERED,
                there,
                f"{'Klart' if approved else 'Nekat'} för tåg {number}",
                f"{names.get(here, here)} {'gav klart' if approved else 'nekade'}.",
            )
        case events.EventKind.TRAIN_DEPARTED:
            return notice(
                station.EventKind.TRAIN_APPROACHING,
                here,
                f"Tåg {number} på väg",
                f"Från {names.get(there, there)}.",
            )
    return None


_ASKING = {station.EventKind.CLEARANCE_REQUESTED, station.EventKind.CLEARANCE_REMINDER}


def _revision(case: Case) -> station.Revision:
    return station.Revision(scope=station.RevisionScope.CASE, key=case.id, value=case.revision)
