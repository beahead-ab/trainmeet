"""The reminder of an unanswered request (H39, DRIFT-33): after 3 minutes and then every 3
minutes, real time, in TKL, the app and Nu; the 16×2 box is unchanged. Only while the clock
runs (DRIFT-44). The old Server had no reminder; the decision is the spec."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from contracts import drift as events
from contracts import station
from contracts.meet import MeetPackage
from drift.engine import Drift
from drift.now import now as nu
from drift.snapshot import snapshot

START = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
Action = station.Action


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


@pytest.fixture
def drift() -> Drift:
    raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    engine = Drift(MeetPackage.model_validate_json(raw), [], now=START)
    engine.start(START)
    engine.control_clock(events.ClockControl(action=events.ClockAction.START), START)
    return engine


def send(
    drift: Drift,
    place: str,
    action: station.Action,
    when: datetime,
    expected: station.Revision | None = None,
    **payload: Any,
) -> None:
    drift.command(
        station.Command(
            message_id=uuid4().hex,
            client_id=f"tkl-{place}",
            place=place,
            context=drift.context,
            action=action,
            expected_revision=expected,
            payload=payload,
        ),
        when,
    )


def request(drift: Drift, when: datetime) -> str:
    clearance = f"clr-{uuid4().hex[:12]}"
    send(
        drift,
        "nby",
        Action.CLEARANCE_REQUEST,
        when,
        call="t101-nby",
        section="s-nby-asn",
        clearance_id=clearance,
    )
    return clearance


def reminders(drift: Drift) -> list[int]:
    return [
        int(str(event.data["count"]))
        for event in drift.history
        if event.kind == events.EventKind.CLEARANCE_REMINDED
    ]


def tick(drift: Drift, *seconds: float) -> None:
    for second in seconds:
        drift.remind(at(second))


def test_reminded_after_three_minutes_and_then_every_three(drift: Drift) -> None:
    request(drift, at(0))
    tick(drift, 60, 179)
    assert reminders(drift) == []
    tick(drift, 180, 181, 300)
    assert reminders(drift) == [1]
    tick(drift, 359, 360, 539, 540)
    assert reminders(drift) == [1, 2, 3]


def test_the_count_is_in_the_snapshot_and_in_nu_and_both_places_read_again(
    drift: Drift,
) -> None:
    clearance = request(drift, at(0))
    before = {place: snapshot(drift, place, at(1)).place_revision for place in ("nby", "asn")}
    tick(drift, 180)
    for place in ("nby", "asn"):
        seen = snapshot(drift, place, at(181))
        assert seen.place_revision > before[place], place
        (case,) = seen.clearances
        assert (case.clearance_id, case.reminders) == (clearance, 1)
    (shown,) = nu(drift, at(181)).clearances
    assert shown.reminders == 1


def test_a_reminder_is_no_answer_so_an_answer_on_its_way_still_counts(drift: Drift) -> None:
    clearance = request(drift, at(0))
    (case,) = snapshot(drift, "asn", at(1)).clearances
    expected = station.Revision(
        scope=station.RevisionScope.CASE, key=clearance, value=case.revision
    )
    tick(drift, 180)
    send(
        drift,
        "asn",
        Action.CLEARANCE_RESPONSE,
        at(190),
        expected,
        clearance_id=clearance,
        approved=True,
    )
    tick(drift, 400, 800)
    assert reminders(drift) == [1], "an answered request is not reminded of"


def test_nothing_goes_out_while_the_clock_stands(drift: Drift) -> None:
    request(drift, at(0))
    drift.control_clock(events.ClockControl(action=events.ClockAction.STOP), at(100))
    tick(drift, 180, 600)
    assert reminders(drift) == []
    # Running again, the waiting starts over from the start of the clock.
    drift.control_clock(events.ClockControl(action=events.ClockAction.START), at(1000))
    tick(drift, 1100, 1179)
    assert reminders(drift) == []
    tick(drift, 1180)
    assert reminders(drift) == [1]


def test_a_speed_change_does_not_start_the_waiting_over(drift: Drift) -> None:
    request(drift, at(0))
    drift.control_clock(events.ClockControl(action=events.ClockAction.SPEED, speed=8), at(120))
    tick(drift, 180)
    assert reminders(drift) == [1]


def test_direct_clearance_and_a_cancelled_request_are_not_reminded_of(drift: Drift) -> None:
    clearance = request(drift, at(0))
    send(drift, "nby", Action.CLEARANCE_CANCEL, at(10), clearance_id=clearance)
    direct = f"clr-{uuid4().hex[:12]}"
    send(
        drift,
        "sjv",
        Action.CLEARANCE_REQUEST,
        at(20),
        call="t102-sjv",
        section="s-mla-sjv",
        clearance_id=direct,
    )
    tick(drift, 400, 800)
    assert reminders(drift) == []


def test_the_log_keeps_the_reminders_and_a_replay_gives_the_same_count(drift: Drift) -> None:
    request(drift, at(0))
    tick(drift, 180, 360)
    again = Drift(drift.package, drift.history, now=at(361))
    (case,) = [c for c in again.cases.values() if c.active]
    assert case.reminders == 2
    tick(again, 539)
    assert reminders(again) == [1, 2], "the next one is three minutes after the last"
    tick(again, 540)
    assert reminders(again) == [1, 2, 3]


def test_a_reminder_counts_from_one_in_the_contract() -> None:
    with pytest.raises(ValueError):
        events.DriftEvent(
            seq=1,
            epoch=0,
            meet_id="provbanan",
            version=1,
            game_day=1,
            model_time="06:00",
            wall_time=START,
            kind=events.EventKind.CLEARANCE_REMINDED,
            actor=events.Actor(kind=events.ActorKind.SYSTEM),
            data={"clearance_id": "x", "count": 0},
        )


def test_the_hubs_tick_reminds_also_with_the_automation_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store's round every second sends the reminders, whether the automation is on or not."""
    from drift import store as stores

    raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    store = stores.PreviewStore(
        tmp_path / "run.sqlite3", MeetPackage.model_validate_json(raw), automation=False
    )
    clock = {"now": START}
    monkeypatch.setattr(stores, "now_utc", lambda: clock["now"])
    run = store.start()
    store.clock(run, events.ClockControl(action=events.ClockAction.START))
    context = store.state(run).context
    store.command(
        run,
        station.Command(
            message_id="message-1",
            client_id="tkl-nby",
            place="nby",
            context=context,
            action=Action.CLEARANCE_REQUEST,
            payload={"call": "t101-nby", "section": "s-nby-asn", "clearance_id": "clr-1"},
        ),
    )
    assert not store.state(run).automation.enabled
    clock["now"] = at(181)
    store.tick(run)
    (reminded,) = [e for e in store.log(run) if e.kind == events.EventKind.CLEARANCE_REMINDED]
    assert (reminded.actor.kind, reminded.place, reminded.train) == (
        events.ActorKind.SYSTEM,
        "asn",
        "t101",
    )
    assert store.log(run, place="asn")[0].kind == events.EventKind.CLEARANCE_REMINDED
