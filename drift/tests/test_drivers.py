"""Lokföraren in Drift (LOK-01–LOK-41), ported from the old Server's test_lokforaren.py where the
behaviour is the same: the duties in a list, search on the paper's number, a service per driver,
the check-in that fades on the meet clock, and the photo icon. New: the first claim wins, the
hand-out, the alarm when a service is released on the line, Framme, the game's settings, the mark
Ändrat and the clock that is always Drift's.

Provbanan has five duties: 1 (Medel) is train 101 Norrby–Sjövik and back as 104; 2 and 4 are
Lätt, 3 is Erfaren and 5 Medel. The clock goes 4× from 06:00.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import pytest

from contracts import drift as events
from contracts import station
from contracts.meet import DriverLevel, Duty, MeetPackage
from contracts.reasons import Reason
from drift import drivers
from drift.engine import Caller, Drift, Refused
from drift.now import now as nu
from drift.store import PreviewStore, UnknownDriver

START = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
D1 = events.ServiceRef(kind=events.ServiceKind.DUTY, id="d1")
D2 = events.ServiceRef(kind=events.ServiceKind.DUTY, id="d2")
Action = station.Action


def at(seconds: float) -> datetime:
    """Real time, seconds after the start. The meet clock goes 4× once it runs."""
    return START + timedelta(seconds=seconds)


def provbanan() -> MeetPackage:
    raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    return MeetPackage.model_validate_json(raw)


def started(package: MeetPackage | None = None) -> Drift:
    engine = Drift(package or provbanan(), [], now=START)
    engine.start(START)
    return engine


@pytest.fixture
def drift() -> Drift:
    return started()


def send(
    drift: Drift, place: str, action: station.Action, now: datetime, **payload: object
) -> None:
    drift.command(
        station.Command(
            message_id=uuid4().hex,
            client_id=f"tkl-{place}",
            place=place,
            context=drift.context,
            action=action,
            payload=payload,
        ),
        now,
    )


def out_on_the_line(drift: Drift, now: datetime, train: str = "t101") -> None:
    """Norrby asks Åsen, Åsen gives klart, and the train leaves Norrby."""
    clearance = f"clr-{uuid4().hex[:12]}"
    call = f"{train}-nby"
    send(drift, "nby", Action.CLEARANCE_REQUEST, now, call=call, section="s-nby-asn",
         clearance_id=clearance)  # fmt: skip
    send(drift, "asn", Action.CLEARANCE_RESPONSE, now, clearance_id=clearance, approved=True)
    send(drift, "nby", Action.TRAIN_DEPARTED, now, call=call)


def numbers(listed: list[events.DriftEvent]) -> list[str]:
    return [event.kind.value for event in listed]


# --- The list -------------------------------------------------------------------------------


def test_the_duties_in_start_order_with_the_drivers_level_first(drift: Drift) -> None:
    """LOK-17, LOK-19, LOK-32: the meet has duties, so only duties; the front of the paper:
    number, start, end and difficulty; the driver's level first, then the rest in start order."""
    listed = drivers.service_list(drift, level=DriverLevel.EASY)
    assert listed.kind == events.ServiceKind.DUTY
    assert [offer.number for offer in listed.services] == ["2", "4", "1", "3", "5"]
    first = listed.services[0]
    assert (first.start.time, first.start.place_name, first.end.time, first.end.place_name) == (
        "06:05",
        "Sjövik",
        "07:29",
        "Sjövik",
    )
    assert (first.level, first.trains, first.matches_level, first.taken) == (
        DriverLevel.EASY,
        ["102", "103"],
        True,
        False,
    )


def test_the_full_list_is_not_cut_and_the_exact_number_comes_first() -> None:
    """The old Server's catalogue was not limited to thirty duties; a search on the number has
    the exact number first and then every number that holds it (LOK-18)."""
    package = provbanan()
    legs = package.duties[0].legs
    many = [Duty(id=f"k{n}", name=str(n), legs=legs) for n in range(1, 143)]
    engine = started(package.model_copy(update={"duties": many}))
    everything = drivers.service_list(engine).services
    assert len(everything) == 142 and everything[-1].number == "142"
    found = drivers.service_list(engine, query="1").services
    assert found[0].number == "1" and found[0].exact
    assert len(found) > 30
    assert [o.number for o in drivers.service_list(engine, query="13").services][:2] == [
        "13",
        "113",
    ]


def test_without_duties_the_trains_are_the_services() -> None:
    """LOK-17, LOK-31: a meet with timetables only has its trains, each with its timetable."""
    engine = started(provbanan().model_copy(update={"duties": []}))
    listed = drivers.service_list(engine)
    assert listed.kind == events.ServiceKind.TRAIN
    assert [o.number for o in listed.services][:4] == ["101", "102", "4501", "103"]
    rows = drivers.korplan(engine, drivers.services(engine)[1][0], at(0), 1).rows
    assert [row.place for row in rows] == ["nby", "asn", "lvh", "mla", "sjv"]


# --- Claiming --------------------------------------------------------------------------------


def test_the_first_to_take_the_service_gets_it(drift: Drift) -> None:
    """LOK-40: one driver at a time; the other is told it is taken."""
    drivers.claim(drift, D1, "anna", at(1))
    with pytest.raises(Refused) as taken:
        drivers.claim(drift, D1, "bo", at(2))
    assert taken.value.reason == Reason.SERVICE_TAKEN
    event = drift.history[-1]
    assert (event.kind, event.actor.kind, event.actor.id, event.train) == (
        events.EventKind.SERVICE_CLAIMED,
        events.ActorKind.DRIVER,
        "anna",
        "t101",
    )
    offer = drivers.service_list(drift).services
    assert next(o for o in offer if o.number == "1").driver == "anna"


def test_a_driver_has_one_service_at_a_time(drift: Drift) -> None:
    drivers.claim(drift, D1, "anna", at(1))
    with pytest.raises(Refused) as one:
        drivers.claim(drift, D2, "anna", at(2))
    assert one.value.reason == Reason.ONE_SERVICE
    size = len(drift.history)
    drivers.claim(drift, D1, "anna", at(3))
    assert len(drift.history) == size, "taking one's own again changes nothing"
    drivers.release(drift, "anna", at(4))
    drivers.claim(drift, D2, "anna", at(5))
    assert drift.drivers.service_of("anna") is not None
    with pytest.raises(Refused) as unknown:
        drivers.claim(
            drift, events.ServiceRef(kind=events.ServiceKind.DUTY, id="nope"), "bo", at(6)
        )
    assert unknown.value.reason == Reason.UNKNOWN_SERVICE


def test_trafikledningen_and_the_lokledare_hand_out_and_take_back(drift: Drift) -> None:
    """LOK-30, LOK-40: handed out, the service is taken from whoever had it, and the driver's
    own goes back first; that is also how a driver gets it again on a new phone."""
    drivers.claim(drift, D1, "anna", at(1))
    drivers.claim(drift, D2, "bo", at(2))
    size = len(drift.history)
    drivers.claim(drift, D1, "bo", at(3), by="dispatcher")
    assert numbers(drift.history[size:]) == [
        "service.released",
        "service.released",
        "service.claimed",
    ]
    assert drift.drivers.service_of("anna") is None
    held = drift.drivers.service_of("bo")
    assert held is not None and held.service == D1 and held.by == "dispatcher"
    assert drift.history[-1].actor == events.Actor(kind=events.ActorKind.DISPATCHER)
    drivers.take_back(drift, "bo", at(4), by="loco_lead")
    assert drift.drivers.service_of("bo") is None
    assert drift.history[-1].actor == events.Actor(kind=events.ActorKind.LOCO_LEAD)
    assert drivers.alarms(drift) == [], "no alarm when they do it themselves"
    with pytest.raises(Refused) as none:
        drivers.take_back(drift, "bo", at(5), by="dispatcher")
    assert none.value.reason == Reason.NO_SERVICE


def test_released_on_the_line_the_train_stands_without_a_driver(drift: Drift) -> None:
    """LOK-25, LOK-35, LOK-40: released anywhere; on the line, Trafikledningen gets an alarm at
    once, in Nu too, and the service comes first in the list for the next driver."""
    drivers.claim(drift, D1, "anna", at(1))
    drivers.release(drift, "anna", at(2))
    assert drivers.alarms(drift) == [], "released in the station: no alarm"
    drivers.claim(drift, D1, "anna", at(3))
    out_on_the_line(drift, at(4))
    drivers.release(drift, "anna", at(5))
    released = events.ServiceReleased.model_validate(drift.history[-1].data)
    assert (released.on_line, released.section, released.from_place, released.to_place) == (
        True,
        "s-nby-asn",
        "nby",
        "asn",
    )
    (alarm,) = nu(drift, at(6)).driver_alarms
    assert (alarm.number, alarm.train_number, alarm.from_place, alarm.to_place) == (
        "1",
        "101",
        "nby",
        "asn",
    )
    first = drivers.service_list(drift, level=DriverLevel.EASY).services[0]
    assert (first.number, first.released_on_line) == ("1", True)
    drivers.claim(drift, D1, "bo", at(7))
    assert nu(drift, at(8)).driver_alarms == [], "someone took over"
    drivers.release(drift, "bo", at(9))
    assert len(drivers.alarms(drift)) == 1
    drivers.clear_alarm(drift, D1, at(10))
    assert nu(drift, at(11)).driver_alarms == []


# --- Framme -----------------------------------------------------------------------------------


def test_framme_is_off_by_default_and_counts_only_where_nobody_works(drift: Drift) -> None:
    """LOK-11, LOK-39: Framme counts as the arrival only when the game has chosen it, and only
    at a place nobody works, where no one presses Ankommit. The app never gives departure."""
    assert drift.drivers.settings == events.DriverSettings()
    drivers.claim(drift, D1, "anna", at(1))
    out_on_the_line(drift, at(2))
    assert drivers.framme(drift, "anna", "t101-asn", at(3)) is False
    assert "t101-nby" not in drift.arrived, "off: the train is still on the line"
    framme = drift.history[-1]
    assert (framme.kind, framme.call, framme.place, framme.data["counted"]) == (
        events.EventKind.DRIVER_ARRIVED,
        "t101-asn",
        "asn",
        False,
    )
    drivers.set_settings(drift, events.DriverSettings(arrival=True), at(4))
    assert drivers.framme(drift, "anna", "t101-asn", at(5)) is True
    assert "t101-nby" in drift.arrived
    arrival = next(e for e in drift.history if e.kind == events.EventKind.TRAIN_ARRIVED)
    assert (arrival.actor.kind, arrival.actor.id, arrival.place) == (
        events.ActorKind.DRIVER,
        "anna",
        "asn",
    )
    # Mellanå is worked by its TKL: there the driver's Framme is only a word.
    drift.man("mla", "tkl-mla", at(6))
    clearance = "clr-asn-mla-1"
    send(drift, "asn", Action.CLEARANCE_REQUEST, at(7), call="t101-asn", section="s-asn-mla",
         clearance_id=clearance)  # fmt: skip
    send(drift, "mla", Action.CLEARANCE_RESPONSE, at(7), clearance_id=clearance, approved=True)
    send(drift, "asn", Action.TRAIN_DEPARTED, at(7), call="t101-asn")
    assert drivers.framme(drift, "anna", "t101-mla", at(8)) is False
    assert "t101-asn" not in drift.arrived
    with pytest.raises(Refused) as elsewhere:
        drivers.framme(drift, "anna", "t102-mla", at(9))
    assert elsewhere.value.reason == Reason.NOT_IN_SERVICE


def remote(drift: Drift, place: str, now: datetime, unseen: list[str]) -> None:
    """The station's TKL hands the place to a remote interlocking, and says in route.state on
    which tracks it cannot see a train come in (#36, beslut 22 november)."""
    tkl, fjarr = f"tkl-{place}", "fjarr-1"
    drift.man(place, tkl, now)
    own = Caller(kind=station.ClientKind.TKL, receivers={fjarr: station.ClientKind.REMOTE},
                 controllable=True)  # fmt: skip

    def command(client: str, action: station.Action, **payload: object) -> station.Command:
        return station.Command(message_id=uuid4().hex, client_id=client, place=place,
                               context=drift.context, action=action, payload=payload)  # fmt: skip

    drift.command(command(tkl, Action.PLACE_OFFER, to=fjarr), now, caller=own)
    drift.command(
        command(fjarr, Action.PLACE_OFFER_ANSWER, accept=True),
        now,
        caller=Caller(own=False, kind=station.ClientKind.REMOTE),
    )
    assert place in drift.remote
    drift.command(command(tkl, Action.ROUTE_STATE, unseen=unseen), now, level=1, caller=own)


def out_on_the_line_to_afar(drift: Drift, now: datetime) -> None:
    """As out_on_the_line, with klart from the remote interlocking that works Åsen."""
    clearance = f"clr-{uuid4().hex[:12]}"
    send(drift, "nby", Action.CLEARANCE_REQUEST, now, call="t101-nby", section="s-nby-asn",
         clearance_id=clearance)  # fmt: skip
    drift.command(
        station.Command(message_id=uuid4().hex, client_id="fjarr-1", place="asn",
                        context=drift.context, action=Action.CLEARANCE_RESPONSE,
                        payload={"clearance_id": clearance, "approved": True}),
        now,
        caller=Caller(own=False, kind=station.ClientKind.REMOTE),
    )  # fmt: skip
    send(drift, "nby", Action.TRAIN_DEPARTED, now, call="t101-nby")


def test_framme_counts_at_a_remote_station_that_cannot_see_the_train_come_in(
    drift: Drift,
) -> None:
    """LOK-39, beslut 22 november: on a remote-controlled station nobody presses Ankommit
    either. Where its interlocking cannot see the train come in on the track, as its route.state
    says, the driver's Framme counts as the arrival; where it can, the interlocking gives it,
    and Framme is only a word. The körplan marks the same."""
    drivers.set_settings(drift, events.DriverSettings(arrival=True), at(1))
    drivers.claim(drift, D1, "anna", at(1))
    track = drift.planned_track(drift.by_arrival["t101-asn"])
    assert track is not None
    remote(drift, "asn", at(2), unseen=[])
    assert not drift.automatic("asn"), "worked from afar"
    service = drivers.find(drift, D1)
    assert service is not None
    rows = drivers.korplan(drift, service, at(2), len(drift.history)).rows
    assert not next(r for r in rows if r.call == "t101-asn").unmanned
    out_on_the_line_to_afar(drift, at(3))
    assert drivers.framme(drift, "anna", "t101-asn", at(4)) is False, "the station sees it"
    assert "t101-nby" not in drift.arrived
    send(drift, "asn", Action.ROUTE_STATE, at(5), unseen=[track])
    rows = drivers.korplan(drift, service, at(5), len(drift.history)).rows
    assert next(r for r in rows if r.call == "t101-asn").unmanned
    assert drivers.framme(drift, "anna", "t101-asn", at(6)) is True
    assert "t101-nby" in drift.arrived
    arrival = next(e for e in drift.history if e.kind == events.EventKind.TRAIN_ARRIVED)
    assert (arrival.actor.kind, arrival.place, arrival.data["track"]) == (
        events.ActorKind.DRIVER,
        "asn",
        track,
    )


def test_framme_at_the_last_call_ends_the_service(drift: Drift) -> None:
    drivers.claim(drift, D1, "anna", at(1))
    drivers.framme(drift, "anna", "t104-nby", at(2))
    released = events.ServiceReleased.model_validate(drift.history[-1].data)
    assert (released.done, released.on_line) == (True, False)
    assert drift.drivers.service_of("anna") is None
    offer = next(o for o in drivers.service_list(drift).services if o.number == "1")
    assert (offer.done, offer.taken) == (True, False)


# --- What the körplan shows -------------------------------------------------------------------


def test_the_games_settings_hide_or_show_reality_and_the_clearances(drift: Drift) -> None:
    """LOK-20, LOK-21: both off by default. On, the körplan has where the train is according to
    the stations, the delay, and the clearance's word: the station waits, klart, the track."""
    drivers.claim(drift, D1, "anna", at(1))
    clearance = "clr-nby-asn-1"
    send(drift, "nby", Action.CLEARANCE_REQUEST, at(2), call="t101-nby", section="s-nby-asn",
         clearance_id=clearance)  # fmt: skip
    service = drivers.find(drift, D1)
    assert service is not None
    plan = drivers.korplan(drift, service, at(3), len(drift.history))
    assert all(row.real is None and row.clearance is None for row in plan.rows)
    assert plan.position is None
    drivers.set_settings(drift, events.DriverSettings(reality=True, clearances=True), at(4))
    plan = drivers.korplan(drift, service, at(5), len(drift.history))
    norrby = plan.rows[0]
    assert norrby.clearance is not None
    assert (norrby.clearance.status, norrby.clearance.to_place, norrby.clearance.track) == (
        "waiting",
        "asn",
        "1",
    )
    assert plan.position is not None and (plan.position.state, plan.position.place) == ("at", "nby")
    send(drift, "asn", Action.CLEARANCE_RESPONSE, at(6), clearance_id=clearance, approved=True)
    send(drift, "nby", Action.TRAIN_DEPARTED, at(6), call="t101-nby")
    plan = drivers.korplan(drift, service, at(7), len(drift.history))
    assert plan.rows[0].real is not None and plan.rows[0].real.passed
    assert plan.rows[0].clearance is not None and plan.rows[0].clearance.status == "approved"
    assert plan.position is not None
    assert (plan.position.state, plan.position.from_place, plan.position.to_place) == (
        "on_the_way",
        "nby",
        "asn",
    )
    assert [row.first_of_train for row in plan.rows].count(True) == 2
    assert plan.rows[-1].last and plan.rows[-1].place == "nby"


def test_a_change_during_the_game_is_marked_for_ten_game_minutes(drift: Drift) -> None:
    """LOK-24, LOK-41: a change shows at once and is marked, with no acknowledgement; the mark
    stays ten game minutes. At 4×, that is two and a half real minutes."""
    drift.control_clock(events.ClockControl(action=events.ClockAction.START), at(0))
    drivers.claim(drift, D1, "anna", at(1))
    change = events.MakeChange(change=events.ChangeTimes(train="t101", minutes=5))
    drift.make_change(change, at(10), "chg-1")
    service = drivers.find(drift, D1)
    assert service is not None

    def marked(when: datetime) -> dict[str, bool]:
        rows = drivers.korplan(drift, service, when, len(drift.history)).rows
        return {row.call: row.changed for row in rows}

    soon = marked(at(11))
    assert soon["t101-asn"] and soon["t101-sjv"], "the train's new times"
    assert not soon["t104-sjv"], "the other train of the duty did not change"
    assert drivers.korplan(drift, service, at(11), 1).rows[1].departure == "06:15"
    assert marked(at(10 + 149))["t101-asn"], "9 game minutes 56 seconds later"
    assert not marked(at(10 + 151))["t101-asn"], "10 game minutes 4 seconds later"


def test_the_clock_is_always_drifts(drift: Drift) -> None:
    """LOK-12: the drivers get Drift's clock, never the phone's: the count-down to the start, in
    game time and in real time at the clock's speed, and nothing when the clock stands."""
    service = drivers.find(drift, D2)
    assert service is not None
    standing = drivers.start(drift, service, at(100))
    assert (standing.time, standing.in_game_seconds, standing.in_real_seconds) == (
        "06:05",
        300,
        None,
    )
    assert standing.reminders == [20, 10]
    drift.control_clock(events.ClockControl(action=events.ClockAction.START), at(100))
    going = drivers.start(drift, service, at(130))
    assert (going.in_game_seconds, going.in_real_seconds) == (180, 45)
    seen = drivers.clock(drift, at(130))
    assert (seen.time, seen.seconds, seen.running, seen.speed) == ("06:02", 21720, True, 4.0)
    assert drivers.korplan(drift, service, at(130), 1).clock == seen
    assert nu(drift, at(130)).clock == seen


# --- Check-in --------------------------------------------------------------------------------


def test_a_check_in_lasts_fifteen_game_minutes_on_the_meet_clock(drift: Drift) -> None:
    """Spelminuter (Casper 2026-11-01, A8): seen ten game minutes, fading five more. A stopped
    clock holds it; a clock set back past it makes it old; a day of real time ends it."""
    drift.control_clock(events.ClockControl(action=events.ClockAction.START), at(0))
    drivers.check_in(drift, "anna", "asn", "1", at(0))

    def seen(when: datetime) -> float | None:
        found = drivers.checked_in(drift, drift.drivers.checkins.get("anna"), when)
        return None if found is None else found.age_seconds

    assert seen(at(0)) == 0.0
    assert seen(at(149)) == 596.0
    found = drivers.checked_in(drift, drift.drivers.checkins.get("anna"), at(151))
    assert found is not None and found.fading
    assert seen(at(224)) == 896.0
    assert seen(at(226)) is None
    # The clock stops: three real hours later it is still as new as when it stopped.
    stopped = started()
    stopped.control_clock(events.ClockControl(action=events.ClockAction.START), at(0))
    drivers.check_in(stopped, "anna", "asn", None, at(0))
    stopped.control_clock(events.ClockControl(action=events.ClockAction.STOP), at(10))
    later = drivers.checked_in(stopped, stopped.drivers.checkins.get("anna"), at(3 * 3600))
    assert later is not None and later.age_seconds == 40.0
    # A day of real time is the end, whatever the clock does.
    assert drivers.checked_in(stopped, stopped.drivers.checkins.get("anna"), at(86460)) is None
    # Set back past the check-in: no longer where the driver is.
    stopped.control_clock(
        events.ClockControl(action=events.ClockAction.JUMP, time="05:30"), at(3 * 3600)
    )
    assert drivers.checked_in(stopped, stopped.drivers.checkins.get("anna"), at(3 * 3600)) is None


def test_only_the_latest_place_counts_and_it_names_the_train(drift: Drift) -> None:
    drivers.claim(drift, D1, "anna", at(1))
    drivers.check_in(drift, "anna", "nby", None, at(2))
    drivers.check_in(drift, "anna", "asn", "1", at(3))
    found = drivers.checked_in(drift, drift.drivers.checkins.get("anna"), at(4))
    assert found is not None
    assert (found.place, found.place_name, found.track, found.train_number) == (
        "asn",
        "Åsen",
        "1",
        "101",
    )
    with pytest.raises(Refused) as nowhere:
        drivers.check_in(drift, "anna", "  ", None, at(5))
    assert nowhere.value.reason == Reason.UNKNOWN_PLACE


# --- Messages -------------------------------------------------------------------------------


def test_a_message_goes_to_nu_and_to_the_clearers_concerned(drift: Drift) -> None:
    """LOK-23, DRIFT-38: Försenad, Står på linjen, Behöver hjälp, Loket krånglar: an event with
    the driver, the service, the train and the time; in Nu without a name; to the places the
    train is between."""
    drivers.claim(drift, D1, "anna", at(1))
    out_on_the_line(drift, at(2))
    before = dict(drift.place_revision)
    event = drivers.message(drift, "anna", station.DriverMessageKind.STOPPED_ON_LINE, at(3))
    assert (event.kind, event.actor.id, event.train, event.data["service"]) == (
        events.EventKind.DRIVER_MESSAGE,
        "anna",
        "t101",
        {"kind": "duty", "id": "d1"},
    )
    seen = nu(drift, at(4))
    (said,) = seen.driver_messages
    assert (said.kind, said.train_number, said.service_number, said.model_time) == (
        station.DriverMessageKind.STOPPED_ON_LINE,
        "101",
        "1",
        "06:00",
    )
    assert "anna" not in seen.model_dump_json()
    assert [m.train_number for m in drivers.messages_here(drift, "asn", at(4))] == ["101"]
    assert drivers.messages_here(drift, "sjv", at(4)) == []
    assert drift.place_revision["asn"] > before.get("asn", 0), "Åsen's TKL reads again"


# --- The store: the drivers beside the events -------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> PreviewStore:
    return PreviewStore(tmp_path / "drift.sqlite3", provbanan())


def test_the_key_is_kept_only_as_its_hash(store: PreviewStore, tmp_path: Path) -> None:
    """LOK-16: the phone's key is a random secret; the hub keeps only its hash, and neither the
    key nor the name is in a Drift event."""
    run = store.start()
    anna, key = store.join_driver(run, "Anna Ek", DriverLevel.MEDIUM)
    store.drive(run, lambda drift, now: drivers.claim(drift, D1, anna.id, now))
    assert store.driver_by_key(key) == anna
    with closing(sqlite3.connect(tmp_path / "drift.sqlite3")) as db:
        rows = db.execute("SELECT * FROM driver").fetchall()
        bodies = [body for (body,) in db.execute("SELECT body FROM preview_event")]
    assert key not in repr(rows)
    assert hashlib.sha256(key.encode()).hexdigest() in repr(rows)
    assert all(key not in body and "Anna" not in body for body in bodies)
    assert any(anna.id in body for body in bodies)
    with pytest.raises(UnknownDriver):
        store.driver_by_key("fel-" + key)


def test_a_driver_stays_for_the_meet_and_a_new_meet_needs_a_new_join(store: PreviewStore) -> None:
    """LOK-41: without an account the driver is kept as long as the meet runs. Byt träff lets the
    drivers go, as it does the boxes (B14)."""
    run = store.start(replace=True)
    anna, key = store.join_driver(run, "Anna", DriverLevel.EASY)
    store.drive(run, lambda drift, now: drivers.claim(drift, D1, anna.id, now))
    assert store.driver_by_key(key).run_id == run
    code = store.driver_code(run)
    assert store.driver_code(run) == code and store.driver_run(code) == run
    store.start(replace=True)
    with pytest.raises(UnknownDriver):
        store.driver_by_key(key)


def test_the_messages_go_to_tkl_and_not_to_the_tmbox_app(store: PreviewStore) -> None:
    """DRIFT-38, KLAR-27: TKL's snapshot has the drivers' messages; the TMBox app's has none."""
    run = store.start(replace=True)
    keys = {}
    for kind in (station.ClientKind.TKL, station.ClientKind.TMBOX_APP):
        reply = store.connect(
            station.ConnectRequest(kind=kind, name=f"{kind} Åsen", software="prov 1"), here=True
        )
        store.approve(run, events.Approve(client_id=reply.client_id, places=["asn"]))
        key = store.connection(reply.client_id).key
        assert key is not None
        keys[kind] = key
    anna, _ = store.join_driver(run, "Anna", DriverLevel.EASY)
    store.drive(run, lambda drift, now: drivers.claim(drift, D1, anna.id, now))
    store.drive(
        run,
        lambda drift, now: drivers.message(
            drift, anna.id, station.DriverMessageKind.ENGINE_TROUBLE, now
        ),
    )
    tkl = store.place_snapshot(keys[station.ClientKind.TKL], "asn")
    assert [(m.kind, m.train_number) for m in tkl.driver_messages] == [
        (station.DriverMessageKind.ENGINE_TROUBLE, "101")
    ]
    assert store.place_snapshot(keys[station.ClientKind.TMBOX_APP], "asn").driver_messages == []


def test_the_korplan_says_where_nobody_works(drift: Drift) -> None:
    """LOK-39, for Lokföraren's Framme: a place nobody works is marked; one worked by its TKL is
    not."""
    drivers.claim(drift, D1, "anna", at(1))
    drift.man("mla", "tkl-mla", at(2))
    service = drivers.find(drift, D1)
    assert service is not None
    rows = drivers.korplan(drift, service, at(3), len(drift.history)).rows
    assert {row.place for row in rows if not row.unmanned} == {"mla"}
    assert any(row.unmanned and row.place == "asn" for row in rows)
