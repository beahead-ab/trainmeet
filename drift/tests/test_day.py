"""Dygnsskiftet (F7, TRAFIK-22, DRIFT-45), ported from the old Server's calendar: by hand by
default with Starta ny dag, automatic as a choice. The next game day starts an hour before its
first train, never before midnight, and the night belongs to the day before until then. The
trains stand where the timetable has them just before the day's first departure (DRIFT-43).
Automatic, it waits at most 30 game minutes for the day's trains still out.

Provbanan runs on Mondays only, so here every train runs every day unless a test says else:
the first train leaves Norrby 06:00, so the day changes at 05:00.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import Any
from uuid import uuid4

import pytest

from contracts import drift as events
from contracts import station
from contracts.common import Weekday
from contracts.meet import MeetPackage
from contracts.reasons import Reason
from drift.automatik import Automatik
from drift.engine import Drift, Refused, model_time, next_weekday, parse_time
from drift.now import now as nu

START = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
Action = station.Action
DAY = 86400


def last(drift: Drift, kind: events.EventKind) -> events.DriftEvent:
    """The latest event of a kind: a jump or a new day is written between begun and done."""
    return next(event for event in reversed(drift.history) if event.kind == kind)


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def package(daily: set[str] | None = None) -> MeetPackage:
    """Provbanan with the trains running every day: all of them, or those named."""
    raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    plain = MeetPackage.model_validate_json(raw)
    trains = [
        train.model_copy(update={"days": list(Weekday)})
        if daily is None or train.id in daily
        else train
        for train in plain.trains
    ]
    return plain.model_copy(update={"trains": trains})


def started(pkg: MeetPackage | None = None) -> Drift:
    drift = Drift(pkg or package(), [], now=START)
    drift.start(START)
    drift.control_clock(events.ClockControl(action=events.ClockAction.START), START)
    return drift


def real(model: float) -> float:
    """Real seconds from the start until the 4× clock shows the model seconds (06:00 + …)."""
    return (model - parse_time("06:00")) / 4


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


def run_101(drift: Drift, when: datetime) -> None:
    """101 asked for, given Klart and gone: a train out on the line."""
    send(
        drift,
        "nby",
        Action.CLEARANCE_REQUEST,
        when,
        call="t101-nby",
        section="s-nby-asn",
        clearance_id="clr-101",
    )
    send(drift, "asn", Action.CLEARANCE_RESPONSE, when, clearance_id="clr-101", approved=True)
    send(drift, "nby", Action.TRAIN_DEPARTED, when, call="t101-nby")


# --- When the next day starts -----------------------------------------------------------------


def test_the_day_changes_an_hour_before_the_new_days_first_train() -> None:
    # On Tuesday only 103 and later run: the first train leaves 07:00.
    later = {"t103", "t104", "t4502", "t105", "t106", "t107", "t108"}
    drift = started(package(daily=later))
    assert next_weekday(drift.traffic_day) == Weekday.TUE
    assert drift.day_change_at() == (parse_time("06:00"), False)
    assert started(package()).day_change_at() == (parse_time("05:00"), False)
    # A Monday-only meet has no train on Tuesday: then 05:00.
    assert started(package(daily=set())).day_change_at() == (parse_time("05:00"), False)


def test_never_before_midnight_and_a_set_time_wins() -> None:
    pkg = package()
    early = [
        call.model_copy(update={"departure": "00:30"}) if call.id == "t101-nby" else call
        for call in pkg.trains[0].calls
    ]
    pkg = pkg.model_copy(
        update={"trains": [pkg.trains[0].model_copy(update={"calls": early}), *pkg.trains[1:]]}
    )
    drift = started(pkg)
    assert drift.day_change_at() == (0.0, False)
    drift.set_day(events.DaySettings(time="03:30"), START)
    assert drift.day_change_at() == (parse_time("03:30"), True)
    assert drift.history[-1].actor.kind == events.ActorKind.DISPATCHER


# --- By hand: Nu says it is time, Starta ny dag starts it ----------------------------------------


def test_by_hand_nu_says_it_is_time_and_starta_ny_dag_starts_the_next_day() -> None:
    drift = started()
    change = DAY + parse_time("05:00")
    status = drift.day_status(at(real(change) - 1))
    assert (status.mode, status.time, status.due) == (events.DayChangeMode.MANUAL, "05:00", False)
    assert (status.next_game_day, status.next_traffic_day, status.first) == (
        2,
        Weekday.TUE,
        "06:00",
    )
    drift.day_tick(at(real(change + 3600)))
    assert drift.game_day == 1, "by hand it never changes by itself"
    status = drift.day_status(at(real(change + 600)))
    assert (status.due, status.suggested) == (True, "05:10"), "where the clock is"
    drift.new_day(events.NewDay(), at(real(change + 600)))
    event = last(drift, events.EventKind.DAY_CHANGED)
    assert (event.kind, event.actor.kind) == (
        events.EventKind.DAY_CHANGED,
        events.ActorKind.DISPATCHER,
    )
    assert (drift.game_day, drift.traffic_day, drift.context.game_day) == (2, Weekday.TUE, 2)
    assert model_time(drift.clock.at(at(real(change + 600)))) == "05:10"
    assert drift.clock.running, "the clock goes on"
    # The night belonged to the day before: the next change is a day later (DRIFT-45).
    assert not drift.day_status(at(real(change + 700))).due


def test_before_midnight_starta_ny_dag_suggests_the_time_of_the_change() -> None:
    drift = started()
    assert drift.day_status(at(real(parse_time("22:00")))).suggested == "05:00"
    drift.new_day(events.NewDay(), at(real(parse_time("22:00"))))
    assert model_time(drift.clock.seconds) == "05:00"
    drift.new_day(events.NewDay(time="04:15"), at(real(parse_time("22:00")) + 10))
    assert (drift.game_day, model_time(drift.clock.seconds)) == (3, "04:15")


def test_the_trains_stand_just_before_the_days_first_departure() -> None:
    drift = started()
    run_101(drift, at(10))
    send(drift, "asn", Action.TRAIN_ARRIVED, at(20), call="t101-asn")
    drift.new_day(events.NewDay(time="09:30"), at(30))
    seen = nu(drift, at(31))
    assert {leg.state for leg in seen.legs} == {"planned"}, "every train at its start"
    assert not drift.held and not drift.arrived
    assert model_time(drift.clock.at(at(31))) == "09:30", "the clock stands where asked"
    placed = events.DayChanged.model_validate(last(drift, events.EventKind.DAY_CHANGED).data).placed
    assert model_time(placed) == "05:59", "just before 101 leaves Norrby 06:00"


def test_a_train_still_out_stops_starta_ny_dag() -> None:
    drift = started()
    run_101(drift, at(10))
    with pytest.raises(Refused) as refused:
        drift.new_day(events.NewDay(), at(20))
    assert refused.value.reason == Reason.DAY_STILL_RUNNING
    send(drift, "asn", Action.TRAIN_ARRIVED, at(30), call="t101-asn")
    send(
        drift,
        "asn",
        Action.CLEARANCE_REQUEST,
        at(40),
        call="t101-asn",
        section="s-asn-mla",
        clearance_id="clr-101b",
    )
    with pytest.raises(Refused):
        drift.new_day(events.NewDay(), at(50))  # An open request is the day still running.
    send(drift, "asn", Action.CLEARANCE_CANCEL, at(60), clearance_id="clr-101b")
    drift.new_day(events.NewDay(), at(70))
    assert drift.game_day == 2


# --- Automatic: by itself, waiting for the trains still out -----------------------------------


def test_automatic_changes_the_day_by_itself_and_waits_for_trains_out() -> None:
    drift = started()
    drift.set_day(events.DaySettings(mode=events.DayChangeMode.AUTOMATIC), at(0))
    # Ledig linje to Åsen, never acknowledged: the day still runs.
    send(drift, "nby", Action.LINE_AVAILABLE_PUBLISH, at(5), section="s-nby-asn", call="t101-nby")
    change = DAY + parse_time("05:00")
    drift.day_tick(at(real(change) - 1))
    assert drift.game_day == 1
    drift.day_tick(at(real(change)))
    assert drift.game_day == 1, "it waits for what is out"
    assert drift.day_status(at(real(change))).waiting
    drift.day_tick(at(real(change + 1800) - 1))
    assert drift.game_day == 1
    drift.day_tick(at(real(change + 1800)))
    assert drift.game_day == 2, "at most 30 game minutes"
    event = last(drift, events.EventKind.DAY_CHANGED)
    assert event.actor.kind == events.ActorKind.SYSTEM
    assert events.DayChanged.model_validate(event.data).automatic
    assert not drift.lines, "ledig linje is let go with the day"


def test_automatic_without_anything_out_changes_at_the_time() -> None:
    drift = started()
    drift.set_day(events.DaySettings(mode=events.DayChangeMode.AUTOMATIC), at(0))
    drift.day_tick(at(real(DAY + parse_time("05:00"))))
    assert (drift.game_day, drift.traffic_day) == (2, Weekday.TUE)
    assert model_time(drift.clock.seconds) == "05:00"


def test_the_clock_must_run_for_the_day_to_change_by_itself() -> None:
    drift = started()
    drift.set_day(events.DaySettings(mode=events.DayChangeMode.AUTOMATIC), at(0))
    when = at(real(DAY + parse_time("05:00")))
    drift.control_clock(events.ClockControl(action=events.ClockAction.STOP), when)
    drift.day_tick(when + timedelta(hours=1))
    assert drift.game_day == 1


# --- After the change ---------------------------------------------------------------------------


def test_a_new_day_can_be_undone() -> None:
    drift = started()
    run_101(drift, at(10))
    send(drift, "asn", Action.TRAIN_ARRIVED, at(20), call="t101-asn")
    drift.new_day(events.NewDay(), at(30))
    shown = nu(drift, at(31)).jump
    assert shown is not None
    assert (shown.kind, shown.game_day, shown.traffic_day, shown.to_time) == (
        "day",
        2,
        Weekday.TUE,
        "05:00",
    )
    drift.control_clock(events.ClockControl(action=events.ClockAction.UNDO_JUMP), at(40))
    undone = last(drift, events.EventKind.TIME_JUMP_UNDONE)
    assert events.TimeJumpUndone.model_validate(undone.data).kind == "day"
    assert (drift.game_day, drift.traffic_day) == (1, Weekday.MON)
    assert "t101-nby" in drift.arrived, "yesterday as it was"
    assert model_time(drift.clock.at(at(40))) == "06:02"


def test_the_events_belong_to_their_game_day() -> None:
    drift = started()
    drift.new_day(events.NewDay(), at(10))
    send(
        drift,
        "nby",
        Action.CLEARANCE_REQUEST,
        at(20),
        call="t101-nby",
        section="s-nby-asn",
        clearance_id="clr-tue",
    )
    assert drift.history[-1].game_day == 2
    assert [e.game_day for e in drift.history if e.kind == events.EventKind.MEET_STARTED] == [1]


def test_the_automation_runs_the_new_day_from_its_first_train() -> None:
    drift = started()
    automatik = Automatik(now=lambda: 0.0)
    drift.set_automation(events.AutomationSettings(answer_seconds=0), at(0))
    drift.new_day(events.NewDay(), at(1))  # 05:00 on Tuesday
    # 101 leaves Norrby 06:00 and is asked for two minutes before: 58 minutes at 4×.
    automatik.tick(drift, at(1 + 58 * 60 / 4))
    asked = {case.leg.departure.id for case in drift.cases.values() if case.active}
    assert "t101-nby" in asked


def test_old_logs_without_day_settings_read_as_by_hand() -> None:
    drift = started()
    again = Drift(drift.package, drift.history, now=at(1))
    assert again.day_settings == events.DaySettings()
