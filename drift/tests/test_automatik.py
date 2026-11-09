"""Automatiken (F14, F15, H41, H42), ported from the old Server's tests as the key:
test_automatic_stations, test_station_automatic_queue, test_automatic_disturbance and the
station part of test_station_automatic. The box's part is in hub/tests/test_tmbox_automatik.py.

Provbanan stands in for the old fixture: Norrby – Åsen single track, Åsen – Mellanå double
track, Mellanå – Sjövik direct. The meet clock runs at 4×, so a model minute is 15 real
seconds. Real time is a fake monotonic clock and a wall clock that move together.
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
from drift.automatik import Automatik, plan
from drift.engine import AUTOMATION, Drift, Refused, model_time, parse_time
from drift.snapshot import snapshot

START = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
Action = station.Action


class World:
    """A meet, its automation and the two clocks: the wall clock and the monotonic one."""

    def __init__(self, *, run: bool = True, settings: dict[str, Any] | None = None) -> None:
        raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
        self.real = 0.0
        self.drift = Drift(MeetPackage.model_validate_json(raw), [], now=START)
        self.drift.start(START)
        self.auto = Automatik(now=lambda: self.real)
        if settings is not None:
            self.drift.set_automation(events.AutomationSettings(**settings), START)
        if run:
            self.drift.control_clock(events.ClockControl(action=events.ClockAction.START), START)

    @property
    def now(self) -> datetime:
        return START + timedelta(seconds=self.real)

    @property
    def time(self) -> str:
        return model_time(self.drift.clock.at(self.now))

    def wait(self, seconds: float, *, step: float = 1.0) -> None:
        """Real seconds pass, with a round of the automation every step."""
        end = self.real + seconds
        while self.real < end:
            self.real = min(end, self.real + step)
            self.auto.tick(self.drift, self.now)

    def until(self, time: str, *, step: float = 1.0) -> None:
        """Run to a model time (HH:MM)."""
        target = parse_time(time)
        while self.drift.clock.at(self.now) < target:
            self.wait(step, step=step)

    def man(self, place: str, client: str | None = None) -> str:
        client = client or f"box-{place}"
        self.auto.observe(client, place)
        self.drift.man(place, client, self.now)
        return client

    def send(
        self, place: str, action: station.Action, client: str | None = None, **payload: Any
    ) -> None:
        self.drift.command(
            station.Command(
                message_id=uuid4().hex,
                client_id=client or f"box-{place}",
                place=place,
                context=self.drift.context,
                action=action,
                payload=payload,
            ),
            self.now,
        )

    def kinds(self, train: str) -> list[tuple[str, str | None]]:
        """What happened to a train: (kind, place) of its events."""
        return [
            (event.kind.value, event.place) for event in self.drift.history if event.train == train
        ]

    def at(self, kind: str, call: str) -> str:
        return next(e.model_time for e in self.drift.history if e.kind == kind and e.call == call)

    def case(self, call: str) -> Any:
        return next(c for c in self.drift.cases.values() if c.leg.departure.id == call)


def test_the_plan_leaves_out_manual_trains_and_knows_the_times() -> None:
    world = World(run=False)
    legs = plan(world.drift)
    leg = legs["t101-asn"]
    assert (leg.departure, leg.arrival, leg.dwell) == (6 * 3600 + 600, 6 * 3600 + 19 * 60, 120)
    assert "t101-sjv" not in legs, "the terminus starts no leg"


def test_two_unmanned_places_run_the_timetable() -> None:
    world = World()
    world.until("06:30")
    # Departures are told at the departure call, arrivals at the arrival call.
    assert world.at("train.departed", "t101-nby") == "06:00"
    assert world.at("train.arrived", "t101-asn") == "06:08"
    assert world.at("train.departed", "t101-asn") == "06:10"
    assert world.at("train.arrived", "t101-mla") == "06:19"
    assert "t101-asn" in world.drift.arrived and "t101-mla" in world.drift.arrived
    actors = {e.actor.kind for e in world.drift.history if e.train == "t101"}
    # The direct section's answer is Drift's own (system).
    assert actors == {events.ActorKind.AUTOMATION, events.ActorKind.SYSTEM}


def test_a_manned_receiver_answers_and_reports_the_arrival_itself() -> None:
    world = World()
    world.man("asn")
    world.wait(30)
    case = world.case("t101-nby")
    assert case.status == station.ClearanceStatus.WAITING, "the automation does not answer for asn"
    assert world.auto.blocked["t101-nby"] == "Väntar på klartecken"
    world.send("asn", Action.CLEARANCE_RESPONSE, clearance_id=case.id, approved=True)
    world.until("06:20")
    assert world.case("t101-nby").departed
    assert "t101-nby" not in world.drift.arrived, "the manned receiver reports the arrival"
    assert world.auto.blocked["t101-nby"] == "Väntar på mottagarens ankomst"
    world.send("asn", Action.TRAIN_ARRIVED, call="t101-asn")
    assert "t101-nby" in world.drift.arrived


def test_a_manned_sender_is_answered_and_its_train_arrives_after_the_running_time() -> None:
    world = World()
    world.man("nby")
    world.until("06:01")
    assert not world.drift.cases, "the automation never asks for a manned place"
    world.send(
        "nby",
        Action.CLEARANCE_REQUEST,
        call="t101-nby",
        section="s-nby-asn",
        clearance_id="clr-101",
    )
    world.wait(4)
    assert world.drift.cases["clr-101"].status == station.ClearanceStatus.APPROVED
    world.send("nby", Action.TRAIN_DEPARTED, call="t101-nby")
    departed = world.drift.clock.at(world.now)
    world.until(model_time(departed + 7 * 60))
    assert "t101-nby" not in world.drift.arrived
    world.wait(40)
    assert "t101-nby" in world.drift.arrived


def test_the_automation_is_refused_on_a_manned_place() -> None:
    world = World()
    world.man("nby")
    with pytest.raises(Refused) as error:
        world.send(
            "nby",
            Action.CLEARANCE_REQUEST,
            client=AUTOMATION,
            call="t101-nby",
            section="s-nby-asn",
            clearance_id="clr-auto",
        )
    assert error.value.reason == Reason.PLACE_MANNED


def test_a_lost_operator_is_waited_for_until_the_place_is_left() -> None:
    world = World()
    world.man("asn")
    world.wait(60)
    assert world.auto.mode(world.drift, "asn") == events.PlaceMode.NO_CONTACT
    assert world.auto.takes_over_in(world.drift, "asn") is None, "never, by default"
    world.wait(600)
    assert world.case("t101-nby").status == station.ClearanceStatus.WAITING
    world.drift.leave("asn", events.LeftBy.DISPATCHER, world.now)
    world.wait(2)
    assert world.case("t101-nby").status == station.ClearanceStatus.APPROVED, (
        "a request that waited is answered at once once the place is left"
    )


def test_a_signal_box_working_a_place_mans_it() -> None:
    world = World()
    assert world.auto.mode(world.drift, "asn") == events.PlaceMode.AUTOMATIC
    world.man("asn", "tkl-asn")
    assert world.auto.mode(world.drift, "asn") == events.PlaceMode.MANNED
    assert world.drift.manned["asn"] == "tkl-asn"
    assert not world.drift.man("asn", "box-asn", world.now), "the first one mans it, once"


def test_trains_planned_before_the_automation_started_are_not_sent() -> None:
    world = World(settings={"enabled": False})
    world.until("06:40")
    assert not world.drift.cases
    world.drift.set_automation(events.AutomationSettings(), world.now)
    world.until("07:01")
    asked = {case.leg.departure.id for case in world.drift.cases.values()}
    assert "t101-nby" not in asked and "t4501-nby" not in asked
    assert "t103-nby" in asked


def test_switched_off_nothing_moves() -> None:
    world = World(settings={"enabled": False})
    world.until("06:30")
    assert not world.drift.cases


def test_a_stopped_clock_stops_the_automation() -> None:
    world = World(run=False)
    world.wait(120)
    assert not world.drift.cases


def test_three_real_seconds_unless_the_dispatcher_chooses_otherwise() -> None:
    assert events.AutomationSettings().answer_seconds == 3
    world = World()
    world.man("nby")
    world.send(
        "nby",
        Action.CLEARANCE_REQUEST,
        call="t101-nby",
        section="s-nby-asn",
        clearance_id="clr-101",
    )
    world.wait(2)
    assert world.case("t101-nby").status == station.ClearanceStatus.WAITING
    assert world.auto.blocked["t101-nby"] == "Väntar på klartecken"
    world.wait(2)
    status: station.ClearanceStatus = world.drift.cases["clr-101"].status
    assert status == station.ClearanceStatus.APPROVED


def test_zero_answers_at_once() -> None:
    world = World(settings={"answer_seconds": 0})
    world.man("nby")
    world.send(
        "nby",
        Action.CLEARANCE_REQUEST,
        call="t101-nby",
        section="s-nby-asn",
        clearance_id="clr-101",
    )
    world.wait(1)
    assert world.drift.cases["clr-101"].status == station.ClearanceStatus.APPROVED


def test_the_dispatcher_chooses_zero_to_thirty_whole_seconds() -> None:
    with pytest.raises(ValueError):
        events.AutomationSettings(answer_seconds=31)
    with pytest.raises(ValueError):
        events.AutomationSettings(lost_contact_minutes=3)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        events.AutomationSettings(disturbance="lite")  # type: ignore[arg-type]
    assert events.AutomationSettings(answer_seconds=30).answer_seconds == 30


def test_an_occupied_track_holds_the_answer_but_a_train_due_there_later_does_not() -> None:
    world = World()
    world.man("nby")
    # 101 stands on asn track 1 when 4501 asks for the same track; nobody moves 101 on.
    world.man("asn")
    world.send("asn", Action.TRAIN_ARRIVED, call="t101-asn")
    world.send(
        "nby",
        Action.CLEARANCE_REQUEST,
        call="t4501-nby",
        section="s-nby-asn",
        clearance_id="clr-4501",
    )
    world.drift.leave("asn", events.LeftBy.DISPATCHER, world.now)
    world.wait(5)
    assert world.drift.cases["clr-4501"].status == station.ClearanceStatus.WAITING
    assert world.auto.blocked["t4501-nby"] == "Mottagningsspåret är upptaget"


def test_after_the_chosen_minutes_the_automation_takes_over() -> None:
    world = World(settings={"lost_contact_minutes": 2})
    world.man("asn")
    world.wait(100)
    assert world.auto.mode(world.drift, "asn") == events.PlaceMode.NO_CONTACT
    assert 0 < (world.auto.takes_over_in(world.drift, "asn") or 0) <= 20
    world.wait(25)
    left = world.drift.left["asn"]
    assert left.by == events.LeftBy.LOST_CONTACT and left.client_id == "box-asn"
    assert world.auto.mode(world.drift, "asn") == events.PlaceMode.AUTOMATIC


def test_another_box_still_at_the_place_keeps_it() -> None:
    world = World(settings={"lost_contact_minutes": 2})
    world.man("asn", "box-1")
    for _ in range(20):
        world.wait(10)
        world.auto.observe("box-2", "asn")
    assert "asn" not in world.drift.left
    assert world.auto.mode(world.drift, "asn") == events.PlaceMode.MANNED


def test_a_restart_is_not_minutes_without_contact() -> None:
    world = World(settings={"lost_contact_minutes": 2})
    world.man("asn")
    world.wait(110)
    # The hub restarts: a new automation reads the same events, and counts from now.
    world.drift = Drift(world.drift.package, world.drift.history, now=world.now)
    world.auto = Automatik(now=lambda: world.real)
    world.wait(30)
    assert "asn" not in world.drift.left
    world.wait(100)
    assert world.drift.left["asn"].by == events.LeftBy.LOST_CONTACT


def test_who_works_which_place_is_read_back_after_a_restart() -> None:
    world = World()
    world.man("asn")
    world.drift.leave("nby", events.LeftBy.DISPATCHER, world.now)
    again = Drift(world.drift.package, world.drift.history, now=world.now)
    assert again.manned == {"asn": "box-asn"}
    assert again.left["nby"].by == events.LeftBy.DISPATCHER


# --- Lämna and ta tillbaka with the station commands (TKL and the app) ---------------------


def test_the_tkl_leaves_and_takes_back_its_place() -> None:
    world = World()
    world.man("asn", "tkl-asn")
    world.send("asn", Action.PLACE_LEAVE, client="tkl-asn")
    assert world.drift.left["asn"] == events.PlaceLeft(
        by=events.LeftBy.OPERATOR, client_id="tkl-asn"
    )
    assert snapshot(world.drift, "asn", world.now).automatic, "TKL and the app see it too"
    with pytest.raises(Refused) as error:
        world.send(
            "asn", Action.CLEARANCE_RESPONSE, client="tkl-asn", clearance_id="x", approved=True
        )
    assert error.value.reason == Reason.PLACE_AUTOMATIC, "a step there asks to take it back first"
    world.send("asn", Action.TRAIN_LOOKUP, client="tkl-asn", train_number="101")
    world.send("asn", Action.PLACE_TAKE_BACK, client="tkl-asn")
    assert "asn" not in world.drift.left and world.drift.manned["asn"] == "tkl-asn"


def test_refused_while_the_automation_is_switched_off() -> None:
    world = World(settings={"enabled": False})
    world.man("asn", "tkl-asn")
    with pytest.raises(Refused) as error:
        world.send("asn", Action.PLACE_LEAVE, client="tkl-asn")
    assert error.value.reason == Reason.AUTOMATION_OFF


def test_switching_the_automation_off_gives_the_place_back_to_its_box() -> None:
    world = World()
    world.man("asn")
    world.send("asn", Action.PLACE_LEAVE)
    world.drift.set_automation(events.AutomationSettings(enabled=False), world.now)
    assert not world.drift.left_here("asn")
    world.send("asn", Action.TRAIN_ARRIVED, call="t101-asn")  # not refused


# --- Störningar och undanställning (F15, H41) ---------------------------------------------


def test_the_default_is_no_disturbance_and_stabling_after_five_minutes() -> None:
    settings = events.AutomationSettings()
    assert settings.disturbance == events.Disturbance.OFF
    assert (settings.stabling, settings.stabling_minutes, settings.late_stop_minutes) == (
        True,
        5,
        2,
    )


def test_station_work_holds_the_departure_and_the_same_key_gives_the_same_minutes() -> None:
    def departure(seed: str) -> str:
        world = World(settings={"disturbance": "disrupted", "where": "station", "seed": seed})
        world.until("07:30")
        return world.at("train.departed", "t103-nby")

    times = {seed: departure(seed) for seed in ("a", "b", "c", "d")}
    assert any(time > "07:00" for time in times.values()), times
    assert departure("a") == times["a"]


def test_a_disturbance_on_the_line_makes_the_arrival_later() -> None:
    world = World(settings={"disturbance": "disrupted", "where": "line", "seed": "x"})
    world.until("08:00")
    late = [
        call
        for call in ("t101-nby", "t102-sjv", "t103-nby", "t104-sjv")
        if call in world.drift.arrived_seconds
        and world.drift.arrived_seconds[call] > plan(world.drift)[call].arrival
    ]
    assert late, "two of three trains are late on the line"
    assert world.at("train.departed", "t101-nby") == "06:00", "the departure is on time"


def test_a_terminating_train_is_stabled_and_its_track_is_free() -> None:
    world = World()
    world.until("06:30")
    assert "t101-mla" in world.drift.arrived and world.drift.ended_here("t101-mla")
    world.until("06:36")
    assert "t101-mla" in world.drift.set_aside
    event = next(e for e in world.drift.history if e.kind == events.EventKind.TRAIN_SET_ASIDE)
    assert event.model_time == "06:34" and event.actor.kind == events.ActorKind.AUTOMATION


def test_without_stabling_the_terminating_train_holds_the_track() -> None:
    world = World(settings={"stabling": False})
    world.until("06:40")
    assert world.drift.ended_here("t101-mla")


def test_a_manned_terminus_is_not_stabled() -> None:
    world = World()
    world.man("sjv")
    world.until("06:28")
    world.send("sjv", Action.TRAIN_ARRIVED, call="t101-sjv")
    world.until("06:45")
    assert world.drift.ended_here("t101-mla")
