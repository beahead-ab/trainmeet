"""Versionsbyte under träffen (TRAFIK-03, DRIFT-29, H2, H4, H38, H66) and påbörjat och klart
(DRIFT-47). The clock, where the trains stand and the open clearances go with the switch. Each
driftändring is kept unless let go; one the planner took into the new version falls away. A
version that changes a train that is out waits until it is in, unless it is forced through.

Version 2 of Provbanan here: 103 runs ten minutes later, 101 has a note, and the extra train
9101 that Drift's change c3 made is in it, as Planering would have it after Ta med."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import Any
from uuid import uuid4

import pytest

from contracts import drift as events
from contracts import station
from contracts.meet import MeetPackage
from contracts.reasons import Reason
from core.changes import apply
from drift.engine import Drift, Refused
from drift.now import now as nu
from drift.tests.test_day import last

START = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
Action = station.Action
Status = events.ChangeStatus
EXTRA = events.ExtraTrain(number="9101", copy_of="t101", departure="10:00")


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def first() -> MeetPackage:
    raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    return MeetPackage.model_validate_json(raw)


def corrected() -> MeetPackage:
    """Version 3: only små rättelser, 105 ten minutes later and on another track."""
    package = apply(first(), events.ChangeTimes(train="t105", minutes=10), "p4")
    return apply(package, events.ChangeTrack(call="t105-nby", track="2"), "p5")


def second() -> MeetPackage:
    package = apply(first(), events.ChangeTimes(train="t103", minutes=10), "p1")
    package = apply(package, events.TrainNote(train="t101", text="Ånglok"), "p2")
    return apply(package, EXTRA, "c3")


VERSIONS = {1: first(), 2: second(), 3: corrected()}


@pytest.fixture
def drift() -> Drift:
    engine = Drift(VERSIONS[1], [], now=START, packages=VERSIONS.__getitem__)
    engine.start(START)
    return engine


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


def request(drift: Drift, train: str, place: str, section: str, when: datetime) -> str:
    clearance = f"clr-{train}"
    send(
        drift,
        place,
        Action.CLEARANCE_REQUEST,
        when,
        call=f"{train}-{place}",
        section=section,
        clearance_id=clearance,
    )
    return clearance


def switch(
    drift: Drift,
    when: datetime,
    *,
    drop: list[str] | None = None,
    included: list[str] | None = None,
    force: bool = False,
) -> None:
    drift.switch_version(
        events.SwitchVersion(version=2, drop=drop or [], force=force), included or [], when
    )


def test_the_clock_the_trains_and_the_open_clearances_go_with_the_switch(drift: Drift) -> None:
    drift.control_clock(events.ClockControl(action=events.ClockAction.START), at(0))
    clearance = request(drift, "t101", "nby", "s-nby-asn", at(1))
    send(drift, "asn", Action.CLEARANCE_RESPONSE, at(2), clearance_id=clearance, approved=True)
    send(drift, "nby", Action.TRAIN_DEPARTED, at(3), call="t101-nby")
    send(drift, "asn", Action.TRAIN_ARRIVED, at(4), call="t101-asn")
    open_one = request(drift, "t102", "sjv", "s-mla-sjv", at(5))
    before = drift.clock.at(at(10))
    switch(drift, at(10))
    assert (drift.version, drift.context.version) == (2, 2)
    assert drift.clock.at(at(10)) == before and drift.clock.running
    assert "t101-nby" in drift.arrived, "where the trains stand goes with it"
    assert drift.cases[open_one].active, "and the open clearances"
    seen = nu(drift, at(11))
    assert seen.version == 2
    assert next(leg for leg in seen.legs if leg.leg == "t103-nby").departure == "07:10"
    kinds = [e.kind for e in drift.history[-3:]]
    assert kinds == [
        events.EventKind.TRANSITION_BEGUN,
        events.EventKind.VERSION_SWITCHED,
        events.EventKind.TRANSITION_DONE,
    ], "påbörjat och klart (DRIFT-47)"


def test_kept_dropped_and_taken_in_driftändringar(drift: Drift) -> None:
    drift.make_change(events.MakeChange(change=events.CancelTrain(train="t104")), at(1), "c1")
    drift.make_change(
        events.MakeChange(change=events.TrainNote(train="t105", text="x")), at(2), "c2"
    )
    drift.make_change(events.MakeChange(change=EXTRA), at(3), "c3")
    switch(drift, at(4), drop=["c2"], included=["c3"])
    statuses = {c.change_id: c.status for c in nu(drift, at(5)).changes}
    assert statuses == {"c1": Status.APPLIED, "c2": Status.DROPPED, "c3": Status.DROPPED}
    numbers = [t.number for t in drift.package.trains]
    assert "104" not in numbers, "kept on top of the new version (H66)"
    assert numbers.count("9101") == 1, "in the version once, not laid on again (H4)"
    assert next(t for t in drift.package.trains if t.id == "t105").note is None


def test_a_train_out_that_the_version_changes_makes_the_switch_wait(drift: Drift) -> None:
    clearance = request(drift, "t103", "nby", "s-nby-asn", at(1))
    switch(drift, at(2))
    assert drift.version == 1
    waiting = nu(drift, at(3)).switch
    assert waiting is not None and (waiting.version, waiting.waits_for) == (2, ["103"])
    send(drift, "asn", Action.CLEARANCE_RESPONSE, at(4), clearance_id=clearance, approved=True)
    send(drift, "nby", Action.TRAIN_DEPARTED, at(5), call="t103-nby")
    assert drift.version == 1
    send(drift, "asn", Action.TRAIN_ARRIVED, at(6), call="t103-asn")
    assert drift.version == 2, "made as soon as it is in"
    assert nu(drift, at(7)).switch is None


def test_a_train_the_version_does_not_change_does_not_hold_it(drift: Drift) -> None:
    request(drift, "t102", "sjv", "s-mla-sjv", at(1))
    switch(drift, at(2))
    assert drift.version == 2


def test_forced_through_and_called_off(drift: Drift) -> None:
    request(drift, "t103", "nby", "s-nby-asn", at(1))
    switch(drift, at(2))
    drift.call_off_switch(at(3))
    assert nu(drift, at(4)).switch is None
    with pytest.raises(Refused) as refused:
        drift.call_off_switch(at(5))
    assert refused.value.reason == Reason.NO_SWITCH_WAITING
    switch(drift, at(6), drop=["nothing"])
    drift.force_switch(at(7))
    assert drift.version == 2
    switched = next(
        e for e in reversed(drift.history) if e.kind == events.EventKind.VERSION_SWITCHED
    )
    assert events.VersionSwitch.model_validate(switched.data).forced


def test_the_same_version_or_one_not_there_is_refused(drift: Drift) -> None:
    for version, reason in ((1, Reason.SAME_VERSION), (7, Reason.UNKNOWN_VERSION)):
        with pytest.raises(Refused) as refused:
            drift.switch_version(events.SwitchVersion(version=version), [], at(1))
        assert refused.value.reason == reason


def test_a_replay_runs_the_new_version_and_ångra_goes_no_further_back(drift: Drift) -> None:
    drift.control_clock(events.ClockControl(action=events.ClockAction.JUMP, time="07:00"), at(1))
    switch(drift, at(2))
    with pytest.raises(Refused):
        drift.control_clock(events.ClockControl(action=events.ClockAction.UNDO_JUMP), at(3))
    drift.control_clock(events.ClockControl(action=events.ClockAction.JUMP, time="08:00"), at(4))
    drift.control_clock(events.ClockControl(action=events.ClockAction.UNDO_JUMP), at(5))
    assert drift.version == 2, "Ångra after the switch stays in the new version"
    again = Drift(VERSIONS[1], drift.history, now=at(6), packages=VERSIONS.__getitem__)
    assert (again.version, again.package) == (2, drift.package)


def test_begun_and_never_done_starts_locked_until_unlocked(drift: Drift) -> None:
    switch(drift, at(1))
    begun = next(
        i for i, e in enumerate(drift.history) if e.kind == events.EventKind.TRANSITION_BEGUN
    )
    cut = drift.history[: begun + 2]  # The switch written, but never done.
    locked = Drift(VERSIONS[1], cut, now=at(2), packages=VERSIONS.__getitem__)
    assert locked.locked == "version"
    assert nu(locked, at(2)).locked == "version"
    for attempt in (
        lambda: request(locked, "t101", "nby", "s-nby-asn", at(3)),
        lambda: locked.control_clock(events.ClockControl(action=events.ClockAction.START), at(3)),
        lambda: locked.make_change(events.MakeChange(change=EXTRA), at(3), "c9"),
    ):
        with pytest.raises(Refused) as refused:
            attempt()
        assert refused.value.reason == Reason.DRIFT_LOCKED
    locked.unlock(at(4))
    assert locked.locked is None
    request(locked, "t101", "nby", "s-nby-asn", at(5))
    with pytest.raises(Refused) as refused:
        locked.unlock(at(6))
    assert refused.value.reason == Reason.NOT_LOCKED


def test_små_rättelser_are_told_from_other_versions(drift: Drift) -> None:
    """F5, DRIFT-31: a version that only moves times and tracks of trains that have not run is
    taken at once; one with a new train or a note waits for Trafikledningen."""
    assert drift.small_correction(3)
    assert not drift.small_correction(2), "a new train and a note"
    drift.switch_version(events.SwitchVersion(version=3), [], at(1), small=True)
    switched = last(drift, events.EventKind.VERSION_SWITCHED)
    assert events.VersionSwitch.model_validate(switched.data).small
    assert drift.version == 3


def test_a_train_that_has_run_makes_it_no_small_correction(drift: Drift) -> None:
    clearance = request(drift, "t105", "nby", "s-nby-asn", at(1))
    assert not drift.small_correction(3), "105 is out"
    send(drift, "asn", Action.CLEARANCE_RESPONSE, at(2), clearance_id=clearance, approved=True)
    send(drift, "nby", Action.TRAIN_DEPARTED, at(3), call="t105-nby")
    send(drift, "asn", Action.TRAIN_ARRIVED, at(4), call="t105-asn")
    assert not drift.small_correction(3), "105 has run"
