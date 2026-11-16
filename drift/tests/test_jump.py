"""Tidshopp and Ångra (H37, F6, DRIFT-32), and where the trains stand by the timetable after
the start and a jump (DRIFT-43). Ported from the old Server's test_timetable_placement and its
time machine: every train where the timetable has it at the time, on the planned track and
counted as arrived; a train on the line by the timetable waits at its departure place without
a clearance; the open cases are closed. Unlike the old Server nothing is deleted: the jump is
a Drift event, and Ångra puts back what was before it.

Provbanan: 101 Norrby 06:00 → Åsen 06:08/06:10 → Mellanå 06:19/06:21 → Sjövik 06:29, and
102 the other way from Sjövik 06:05 to Norrby 06:34.
"""

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
from drift.automatik import Automatik
from drift.engine import Drift, Refused, model_time
from drift.now import now as nu
from drift.snapshot import snapshot

START = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
Action = station.Action
Clock = events.ClockAction


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def package(**changes: Any) -> MeetPackage:
    raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    return MeetPackage.model_validate_json(raw).model_copy(update=changes)


@pytest.fixture
def drift() -> Drift:
    engine = Drift(package(), [], now=START)
    engine.start(START)
    return engine


def jump(drift: Drift, time: str, when: datetime, **more: Any) -> None:
    drift.control_clock(events.ClockControl(action=Clock.JUMP, time=time, **more), when)


def undo(drift: Drift, when: datetime, seq: int | None = None) -> None:
    drift.control_clock(events.ClockControl(action=Clock.UNDO_JUMP, jump=seq), when)


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


def run_101(drift: Drift, when: datetime) -> str:
    """101 is asked for at Norrby, given Klart at Åsen and leaves: a real train on the line."""
    clearance = "clr-101"
    send(
        drift,
        "nby",
        Action.CLEARANCE_REQUEST,
        when,
        call="t101-nby",
        section="s-nby-asn",
        clearance_id=clearance,
    )
    send(drift, "asn", Action.CLEARANCE_RESPONSE, when, clearance_id=clearance, approved=True)
    send(drift, "nby", Action.TRAIN_DEPARTED, when, call="t101-nby")
    return clearance


def states(drift: Drift, *legs: str) -> list[str]:
    seen = {leg.leg: leg.state for leg in nu(drift, at(1)).legs}
    return [seen[leg] for leg in legs]


# --- Where the trains stand (DRIFT-43) --------------------------------------------------------


def test_a_jump_puts_each_train_where_the_timetable_says_on_its_track(drift: Drift) -> None:
    jump(drift, "06:20", at(0))
    # 101 has come to Mellanå on track 1; the way there is run.
    assert states(drift, "t101-nby", "t101-asn", "t101-mla") == ["arrived", "arrived", "planned"]
    assert drift.standing_track("t101-mla") == "1"
    # 102 came in to Mellanå on track 2 at 06:13 and is on the line to Åsen by the timetable.
    assert drift.standing_track("t102-mla") == "2"
    assert "t102-mla" in drift.held
    assert model_time(drift.clock.at(at(0))) == "06:20"


def test_a_train_on_the_line_by_the_timetable_waits_at_its_departure_place(drift: Drift) -> None:
    jump(drift, "06:12", at(0))
    assert states(drift, "t101-nby", "t101-asn") == ["arrived", "planned"]
    assert "t101-asn" in drift.held
    assert not [case for case in drift.cases.values() if case.active], "no clearance made up"
    # Åsen's TKL has 101 standing on track 1, ready to be asked for.
    calls = {call.call: call for call in snapshot(drift, "asn", at(1)).calls}
    assert calls["t101-asn"].track == "1"
    assert drift.request_block(drift.legs["t101-asn"]) is None


def test_after_its_last_arrival_a_train_stands_at_its_last_place(drift: Drift) -> None:
    jump(drift, "06:40", at(0))
    assert states(drift, "t101-mla") == ["arrived"]
    assert drift.ended_here("t101-mla")
    assert drift.occupant("sjv", "1") == drift.legs["t101-mla"]


def test_jumping_back_moves_the_trains_back(drift: Drift) -> None:
    jump(drift, "06:40", at(0))
    jump(drift, "06:12", at(10))
    assert states(drift, "t101-asn", "t101-mla") == ["planned", "planned"]
    assert drift.occupant("sjv", "1") is None


def test_a_train_without_a_track_gets_a_free_standard_track_of_its_own() -> None:
    trains = []
    for train in package().trains:
        calls = [
            call.model_copy(update={"track": None})
            if call.id in {"t102-nby", "t4502-nby"}
            else call
            for call in train.calls
        ]
        trains.append(train.model_copy(update={"calls": calls}))
    drift = Drift(package(trains=trains), [], now=START)
    drift.start(START)
    jump(drift, "08:00", at(0))
    # Norrby's standard tracks towards the left: 2, and 3 for goods trains.
    assert drift.tracks["t102-asn"] == "2"
    assert drift.tracks["t4502-asn"] == "3", "2 is taken, so the goods train gets 3"


def test_at_the_start_the_trains_stand_where_the_timetable_has_them() -> None:
    clock = package().clock.model_copy(update={"start_time": "06:30"})
    drift = Drift(package(clock=clock), [], now=START)
    drift.start(START)
    assert states(drift, "t101-mla", "t102-mla", "t102-asn") == ["arrived", "arrived", "planned"]
    assert "t102-asn" in drift.held, "102 is on its way to Norrby by the timetable"
    assert drift.last_jump is None, "the start is no jump to undo"


# --- The jump: the open cases close, the clock goes on (H37) ----------------------------------


def test_the_open_cases_are_closed_and_named_in_the_event(drift: Drift) -> None:
    clearance = run_101(drift, at(0))
    before = drift.cases[clearance].revision
    jump(drift, "07:00", at(10))
    case = drift.cases[clearance]
    assert (case.status, case.revision) == (station.ClearanceStatus.CANCELLED, before + 1)
    event = drift.history[-1]
    assert (event.kind, event.actor.kind) == (
        events.EventKind.TIME_JUMP,
        events.ActorKind.DISPATCHER,
    ), "Logg says Trafikledningen made it"
    assert events.TimeJumped.model_validate(event.data).closed == [clearance]
    assert (event.model_time, nu(drift, at(11)).clearances) == ("06:00", [])
    # The train the timetable has in Sjövik since 06:29 stands there, not on the line.
    assert states(drift, "t101-nby", "t101-mla") == ["arrived", "arrived"]


def test_the_clock_goes_on_if_it_ran_and_every_client_reads_again(drift: Drift) -> None:
    drift.control_clock(events.ClockControl(action=Clock.START), at(0))
    seen = {place: snapshot(drift, place, at(1)).place_revision for place in drift.stops()}
    jump(drift, "08:00", at(60))
    assert drift.clock.running
    assert model_time(drift.clock.at(at(60 + 15))) == "08:01", "4× goes on from 08:00"
    for place, revision in seen.items():
        assert snapshot(drift, place, at(61)).place_revision > revision, place


def test_a_jump_to_another_game_day_is_the_day_change(drift: Drift) -> None:
    with pytest.raises(Refused) as refused:
        jump(drift, "08:00", at(0), game_day=2)
    assert refused.value.reason == Reason.OTHER_GAME_DAY
    jump(drift, "08:00", at(0), game_day=1)


# --- Ångra (F6): everything back, nothing deleted ---------------------------------------------


def test_undo_puts_everything_back(drift: Drift) -> None:
    clearance = run_101(drift, at(0))
    drift.control_clock(events.ClockControl(action=Clock.START), at(0))
    jump(drift, "08:00", at(120))
    jumped = drift.history[-1].seq
    shown = nu(drift, at(121)).jump
    assert shown is not None
    assert (shown.seq, shown.from_time, shown.to_time, shown.closed) == (
        jumped,
        "06:08",
        "08:00",
        1,
    )
    case_revision = drift.cases[clearance].revision
    place_revision = snapshot(drift, "asn", at(121)).place_revision
    # Something happens after the jump: 105 is asked for.
    send(
        drift,
        "nby",
        Action.CLEARANCE_REQUEST,
        at(130),
        call="t105-nby",
        section="s-nby-asn",
        clearance_id="clr-105",
    )
    size = len(drift.history)
    undo(drift, at(140), jumped)
    assert len(drift.history) == size + 1, "nothing is deleted"
    case = drift.cases[clearance]
    assert (case.status, case.departed) == (station.ClearanceStatus.APPROVED, True)
    assert case.revision > case_revision, "a client that saw the jump reads again"
    assert "clr-105" not in drift.cases
    assert states(drift, "t101-nby", "t101-asn") == ["on_the_way", "planned"]
    assert model_time(drift.clock.at(at(140))) == "06:08"
    assert drift.clock.running, "the clock runs on as it did"
    assert snapshot(drift, "asn", at(141)).place_revision > place_revision
    assert nu(drift, at(141)).jump is None


def test_only_the_latest_jump_can_be_undone_and_only_once(drift: Drift) -> None:
    jump(drift, "07:00", at(0))
    first = drift.history[-1].seq
    jump(drift, "08:00", at(10))
    with pytest.raises(Refused) as refused:
        undo(drift, at(20), first)
    assert refused.value.reason == Reason.NO_JUMP_TO_UNDO
    undo(drift, at(20))
    assert model_time(drift.clock.at(at(20))) == "07:00"
    assert states(drift, "t101-mla") == ["arrived"], "as after the first jump"
    with pytest.raises(Refused):
        undo(drift, at(30))


def test_a_replay_gives_the_same_state(drift: Drift) -> None:
    run_101(drift, at(0))
    jump(drift, "08:00", at(10))
    send(drift, "nby", Action.TRAIN_ARRIVED, at(11), call="t106-nby")
    undo(drift, at(20))
    again = Drift(drift.package, drift.history, now=at(30))
    assert again.cases == drift.cases
    assert (again.arrived, again.tracks, again.held) == (drift.arrived, drift.tracks, drift.held)
    assert again.call_revision == drift.call_revision
    assert again.place_revision == drift.place_revision
    assert model_time(again.clock.at(at(30))) == model_time(drift.clock.at(at(30)))


def test_a_restored_request_is_reminded_of_from_the_undo(drift: Drift) -> None:
    send(
        drift,
        "nby",
        Action.CLEARANCE_REQUEST,
        at(0),
        call="t101-nby",
        section="s-nby-asn",
        clearance_id="clr-101",
    )
    drift.control_clock(events.ClockControl(action=Clock.START), at(0))
    jump(drift, "08:00", at(60))
    undo(drift, at(400))
    drift.remind(at(579))
    assert drift.cases["clr-101"].reminders == 0
    drift.remind(at(580))
    assert drift.cases["clr-101"].reminders == 1


# --- The automation goes on from the placed trains (old Server's test) -----------------------


def test_the_automation_continues_from_the_placed_trains(drift: Drift) -> None:
    real = {"now": 0.0}
    automatik = Automatik(now=lambda: real["now"])
    drift.set_automation(events.AutomationSettings(answer_seconds=0), at(0))
    # 101 should have left Åsen at 06:10: it stands there without a clearance.
    jump(drift, "06:12", at(0))
    drift.control_clock(events.ClockControl(action=Clock.START), at(1))
    automatik.tick(drift, at(2))
    asked = {case.leg.departure.id for case in drift.cases.values()}
    assert "t101-asn" in asked, "sent at once, late"
    assert "t101-nby" not in asked, "already in Åsen, never sent again"


def test_a_jump_back_before_the_automation_started_runs_the_trains_from_there(
    drift: Drift,
) -> None:
    automatik = Automatik(now=lambda: 0.0)
    drift.set_automation(events.AutomationSettings(enabled=False), at(0))
    jump(drift, "08:00", at(0))
    drift.control_clock(events.ClockControl(action=Clock.START), at(1))
    # Turned on at 08:00: what was planned before is history (F14).
    drift.set_automation(events.AutomationSettings(answer_seconds=0), at(1))
    jump(drift, "06:50", at(2))
    # 103 leaves Norrby 07:00 and is asked for two minutes before; 4× makes 8 minutes 120 s.
    automatik.tick(drift, at(2 + 120))
    asked = {case.leg.departure.id for case in drift.cases.values() if case.active}
    assert "t103-nby" in asked
