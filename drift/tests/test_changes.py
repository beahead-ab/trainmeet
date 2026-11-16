"""Driftändringar in the running meet (DRIFT-41, TRAFIK-02, H38): each applies at once on top
of the version. Against a train that is out or has an open clearance it waits until the train
is in, unless Trafikledningen forces it through. Släpp takes it away again."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import Any
from uuid import uuid4

import pytest

from contracts import drift as events
from contracts import station
from contracts.meet import ClearanceMode, MeetPackage
from contracts.reasons import Reason
from drift.engine import Drift, Refused
from drift.now import now as nu

START = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
Action = station.Action
Status = events.ChangeStatus


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


@pytest.fixture
def drift() -> Drift:
    raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    engine = Drift(MeetPackage.model_validate_json(raw), [], now=START)
    engine.start(START)
    return engine


def change(drift: Drift, made: Any, when: datetime, *, force: bool = False, name: str = "") -> str:
    change_id = name or f"c{uuid4().hex[:6]}"
    drift.make_change(events.MakeChange(change=made, force=force), when, change_id)
    return change_id


def send(drift: Drift, place: str, action: station.Action, when: datetime, **payload: Any) -> None:
    drift.command(
        station.Command(
            message_id=uuid4().hex,
            client_id=f"tkl-{place}",
            place=place,
            context=drift.context,
            action=action,
            payload=payload,
        ),
        when,
    )


def request_101(drift: Drift, when: datetime) -> None:
    send(
        drift,
        "nby",
        Action.CLEARANCE_REQUEST,
        when,
        call="t101-nby",
        section="s-nby-asn",
        clearance_id="clr-101",
    )


def trains(drift: Drift) -> set[str]:
    return {leg.train_number for leg in nu(drift, at(1)).legs}


def status(drift: Drift, change_id: str) -> events.ChangeNow:
    return next(c for c in nu(drift, at(1)).changes if c.change_id == change_id)


def test_a_change_applies_at_once_and_logg_files_it_under_the_train(drift: Drift) -> None:
    made = change(drift, events.CancelTrain(train="t101"), at(1))
    assert "101" not in trains(drift)
    event = drift.history[-1]
    assert (event.kind, event.train, event.actor.kind) == (
        events.EventKind.CHANGE_MADE,
        "t101",
        events.ActorKind.DISPATCHER,
    )
    assert status(drift, made).status == Status.APPLIED
    assert drift.base.trains != drift.package.trains, "the version itself is never changed"


def test_an_extra_train_runs_like_the_others(drift: Drift) -> None:
    change(
        drift,
        events.ExtraTrain(number="9101", copy_of="t101", departure="07:30"),
        at(1),
        name="c1",
    )
    assert "9101" in trains(drift)
    send(
        drift,
        "nby",
        Action.CLEARANCE_REQUEST,
        at(2),
        call="x-c1-0",
        section="s-nby-asn",
        clearance_id="clr-9101",
    )
    assert drift.cases["clr-9101"].active


def test_against_a_train_with_an_open_clearance_it_waits_until_the_train_is_in(
    drift: Drift,
) -> None:
    request_101(drift, at(1))
    made = change(drift, events.ChangeTimes(train="t101", minutes=10), at(2))
    seen = status(drift, made)
    assert (seen.status, seen.waiting_for) == (Status.WAITING, ["101"])
    assert nu(drift, at(3)).legs[0].departure == "06:00", "not yet"
    send(drift, "asn", Action.CLEARANCE_RESPONSE, at(4), clearance_id="clr-101", approved=True)
    send(drift, "nby", Action.TRAIN_DEPARTED, at(5), call="t101-nby")
    assert status(drift, made).status == Status.WAITING
    send(drift, "asn", Action.TRAIN_ARRIVED, at(6), call="t101-asn")
    assert status(drift, made).status == Status.APPLIED, "as soon as it is in"
    assert drift.history[-1].kind == events.EventKind.CHANGE_APPLIED
    leg = next(leg for leg in nu(drift, at(7)).legs if leg.leg == "t101-asn")
    assert leg.departure == "06:20"
    assert "t101-nby" in drift.arrived, "what the train did stays"


def test_forced_through_it_applies_at_once_and_closes_what_no_longer_runs(drift: Drift) -> None:
    request_101(drift, at(1))
    made = change(drift, events.CancelTrain(train="t101"), at(2), force=True)
    seen = status(drift, made)
    assert (seen.status, seen.forced) == (Status.APPLIED, True)
    assert drift.cases["clr-101"].status == station.ClearanceStatus.CANCELLED
    assert not nu(drift, at(3)).clearances


def test_a_waiting_change_can_be_forced_through_later(drift: Drift) -> None:
    request_101(drift, at(1))
    made = change(drift, events.CancelTrain(train="t101"), at(2))
    assert status(drift, made).train_number == "101", "named, though it will be gone"
    drift.force_change(made, at(3))
    seen = status(drift, made)
    assert (seen.status, seen.forced) == (Status.APPLIED, True)
    assert drift.cases["clr-101"].status == station.ClearanceStatus.CANCELLED
    with pytest.raises(Refused):
        drift.force_change(made, at(4))


def test_a_closed_section_takes_no_clearance(drift: Drift) -> None:
    change(drift, events.ChangePlace(section="s-nby-asn", closed=True), at(1))
    with pytest.raises(Refused) as refused:
        request_101(drift, at(2))
    assert refused.value.reason == Reason.SECTION_CLOSED
    assert drift.request_block(drift.legs["t101-nby"]) == Reason.SECTION_CLOSED


def test_direct_clearance_on_a_section_answers_at_once(drift: Drift) -> None:
    change(
        drift, events.ChangePlace(section="s-nby-asn", clearance_mode=ClearanceMode.DIRECT), at(1)
    )
    request_101(drift, at(2))
    assert drift.cases["clr-101"].status == station.ClearanceStatus.APPROVED


def test_an_unmanned_place_is_left_to_the_automation(drift: Drift) -> None:
    drift.man("asn", "tkl-asn", at(1))
    assert not drift.automatic("asn")
    change(drift, events.ChangePlace(place="asn", place_kind="unmanned"), at(2))
    assert drift.automatic("asn")
    with pytest.raises(Refused) as refused:
        request_101(drift, at(3))
        send(drift, "asn", Action.CLEARANCE_RESPONSE, at(4), clearance_id="clr-101", approved=True)
    assert refused.value.reason == Reason.PLACE_AUTOMATIC, "the TKL is told who runs it now"
    change(drift, events.ChangePlace(place="asn", place_kind="manned"), at(5))
    assert not drift.automatic("asn")


def test_släpp_puts_the_version_back_and_a_change_leaning_on_it_goes_too(drift: Drift) -> None:
    cancel = change(drift, events.CancelTrain(train="t102"), at(1))
    extra = change(
        drift, events.ExtraTrain(number="9101", copy_of="t101", departure="07:30"), at(2)
    )
    later = change(drift, events.ChangeTimes(train=f"x-{extra}", minutes=5), at(3))
    drift.drop_change(cancel, at(4))
    assert "102" in trains(drift)
    drift.drop_change(extra, at(5))
    assert "9101" not in trains(drift)
    assert status(drift, later).status == Status.DROPPED, "it changed the extra train"
    with pytest.raises(Refused) as refused:
        drift.drop_change(cancel, at(6))
    assert refused.value.reason == Reason.UNKNOWN_CHANGE


def test_a_change_that_cannot_be_made_is_refused_and_logs_nothing(drift: Drift) -> None:
    size = len(drift.history)
    with pytest.raises(Refused) as refused:
        change(drift, events.CancelTrain(train="t999"), at(1))
    assert (refused.value.reason, len(drift.history)) == (Reason.UNKNOWN_TRAIN, size)


def test_the_changes_stay_through_a_jump_ångra_a_new_day_and_a_replay(drift: Drift) -> None:
    change(drift, events.ChangeNumber(train="t101", number="111"), at(1))
    drift.control_clock(events.ClockControl(action=events.ClockAction.JUMP, time="08:00"), at(2))
    drift.control_clock(events.ClockControl(action=events.ClockAction.UNDO_JUMP), at(3))
    assert "111" in trains(drift)
    drift.new_day(events.NewDay(), at(4))
    assert any(t.number == "111" for t in drift.package.trains)
    again = Drift(drift.base, drift.history, now=at(5))
    assert again.package == drift.package
    assert [c.status for c in again.changes.values()] == [Status.APPLIED]
