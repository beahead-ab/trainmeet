"""Efter pappret in Drift (LOK-13, LOK-29, LF16, LF22): a duty the plan does not have, read from
the driver's photos, run by the driver at once, and seen by no station until Trafikledningen has
approved it. Approved, it is an extra train with the paper's calls, marked Efter pappret wherever
it shows; rejected, the driver is told why.

The paper here is Tjänst 24 on Provbanan: G 4521 from Norrby 06:41 to Sjövik, by Åsen, Lövhult
(no stop), Mellanå and a Gårdsjö the meet does not have. Åsen's departure could not be read.
The clock goes 4× from 06:00; real time and model time are 1:4 once it runs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import pytest

from contracts import drift as events
from contracts import driver as contract
from contracts import station
from contracts.meet import MeetPackage
from contracts.reasons import Reason
from core import changes
from drift import drivers, paper
from drift.driver_book import Paper
from drift.engine import Drift, Refused
from drift.now import now as nu
from drift.snapshot import snapshot
from drift.store import PreviewStore

START = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
D3 = events.ServiceRef(kind=events.ServiceKind.DUTY, id="d3")
PAPER = "papper-0a1b2c3d4e"
REF = events.ServiceRef(kind=events.ServiceKind.PAPER, id=PAPER)
Row = events.PaperRow


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def provbanan() -> MeetPackage:
    raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    return MeetPackage.model_validate_json(raw)


def started(package: MeetPackage | None = None) -> Drift:
    engine = Drift(package or provbanan(), [], now=START)
    engine.start(START)
    return engine


def reading(start: str = "06:31", train: str | None = "G 4521") -> events.PaperReading:
    """What the AI read: the names as on the paper, a time it could not read left empty."""
    return events.PaperReading(
        number="24",
        train_number=train,
        operator="Green Cargo",
        start=events.PaperEnd(time=start, place_name="Norrby"),
        end=events.PaperEnd(time="07:20", place_name="Sjövik"),
        rows=[
            Row(place_name="Norrby", departure="06:41", track="3", note="Koppla loket."),
            Row(place_name="ÅSEN", arrival="06:49", unreadable=True),
            Row(place_name="Lövhult", departure="06:55", stops=False),
            Row(place_name="Mlå", arrival="06:59", departure="07:01"),
            Row(place_name="Gårdsjö", arrival="07:05", departure="07:06"),
            Row(place_name="Sjövik", arrival="07:10", track="2"),
        ],
    )


def read(
    drift: Drift, driver: str = "anna", *, start: str = "06:31", train: str | None = "G 4521"
) -> Paper:
    return paper.create(
        drift,
        driver,
        PAPER,
        reading(start, train),
        pages=3,
        paid_by=events.PaperPayer.MEET,
        cost=36,
        now=at(10),
    )


def everywhere(drift: Drift, now: datetime) -> list[station.Snapshot]:
    return [snapshot(drift, place, now) for place in ("nby", "asn", "mla", "sjv")]


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


# --- The driver runs after the paper (LOK-29) ------------------------------------------------


def test_the_reading_becomes_the_drivers_service_marked_after_the_paper() -> None:
    """LOK-29: the places matched to the meet's by name or signature, the service the driver's
    at once, and its körplan every row as read, marked, with the NU-linje on its times."""
    drift = started()
    found = read(drift)
    assert drift.history[-1].kind == events.EventKind.PAPER_CREATED
    assert drift.history[-1].train is None, "no train Drift knows: no station hears of it"
    assert [row.place for row in found.reading.rows] == ["nby", "asn", "lvh", "mla", None, "sjv"]
    assert found.status == events.PaperStatus.WAITING
    held = drift.drivers.service_of("anna")
    assert held is not None and held.service == REF
    service = drivers.find(drift, REF)
    assert service is not None
    offer = drivers.offer(drift, service)
    assert (offer.number, offer.paper, offer.trains, offer.operator) == (
        "24",
        events.PaperStatus.WAITING,
        ["G 4521"],
        "Green Cargo",
    )
    # The front as written: the service starts before the train leaves (LOK-19).
    assert (offer.start.time, offer.start.place_name, offer.end.time) == (
        "06:31",
        "Norrby",
        "07:20",
    )
    assert drivers.start(drift, service, at(10)).time == "06:31"
    plan = drivers.korplan(drift, service, at(10), len(drift.history))
    assert plan.paper == events.PaperStatus.WAITING
    assert [(r.place, r.place_name, r.departure) for r in plan.rows] == [
        ("nby", "Norrby", "06:41"),
        ("asn", "Åsen", None),
        ("lvh", "Lövhult", "06:55"),
        ("mla", "Mellanå", "07:01"),
        (contract.UNKNOWN_PLACE, "Gårdsjö", "07:06"),
        ("sjv", "Sjövik", None),
    ]
    assert plan.rows[0].note == "Koppla loket." and not plan.rows[2].stops
    assert plan.clock.time == "06:00", "the NU-linje follows Drift's clock"


def test_unreadable_times_stay_unknown_and_there_is_no_reality_before_approval() -> None:
    """LOK-29, LOK-20: AI only suggests, and a time it could not read is not guessed; the train
    is not in the plan, so Drift has no reality for it even when the game shows reality."""
    drift = started()
    drivers.set_settings(drift, events.DriverSettings(reality=True, clearances=True), at(1))
    read(drift)
    service = drivers.find(drift, REF)
    assert service is not None
    plan = drivers.korplan(drift, service, at(10), 1)
    asen = plan.rows[1]
    assert (asen.arrival, asen.departure) == ("06:49", None)
    assert drift.drivers.papers[PAPER].reading.rows[1].unreadable
    assert [row.unreadable for row in plan.rows] == [
        row.unreadable for row in drift.drivers.papers[PAPER].reading.rows
    ]
    assert asen.unreadable and not plan.rows[0].unreadable
    assert all(row.real is None and row.clearance is None for row in plan.rows)
    assert plan.position is None


def test_a_driver_has_one_service_and_reads_none_with_one() -> None:
    """LOK-40: checked before anything is read or paid for."""
    drift = started()
    drivers.claim(drift, D3, "anna", at(1))
    with pytest.raises(Refused) as one:
        paper.may_read(drift, "anna")
    assert one.value.reason == Reason.ONE_SERVICE
    with pytest.raises(Refused):
        read(drift)


def test_a_paper_naming_none_of_the_meets_places_is_not_run() -> None:
    drift = started()
    elsewhere = events.PaperReading(rows=[Row(place_name="Gårdsjö"), Row(place_name="Särö")])
    with pytest.raises(Refused) as none:
        paper.create(
            drift,
            "anna",
            PAPER,
            elsewhere,
            pages=1,
            paid_by=events.PaperPayer.DRIVER,
            cost=12,
            now=at(1),
        )
    assert none.value.reason == Reason.PAPER_NO_PLACES
    assert drift.drivers.papers == {}


# --- Matching first (LF16) ---------------------------------------------------------------------


def test_the_nearest_planned_services_are_offered_with_the_reading() -> None:
    """LF16, foto-saknas: no service starts there and then; the nearest at the same place first,
    then elsewhere close in time. The driver may take one of them instead."""
    drift = started()
    found = read(drift)
    view = paper.view(drift, found, names={"anna": "Anna"})
    assert (
        view.said
        == "Ingen tjänst startar 06:31 vid Norrby. Närmast: 3 kl. 06:35, 1 kl. 06:00, 2 kl. 06:05."
    )
    assert [c.number for c in view.candidates] == ["3", "1", "2"]
    assert (view.driver_name, view.status, view.pages, view.cost) == ("Anna", "waiting", 3, 36)
    assert view.rows[1].unreadable and view.rows[4].place is None
    # The driver takes service 3 instead: the paper is let go before anyone decided.
    drivers.claim(drift, D3, "anna", at(20))
    assert drift.drivers.papers[PAPER].status == events.PaperStatus.WITHDRAWN
    held = drift.drivers.service_of("anna")
    assert held is not None and held.service == D3
    assert drift.drivers.paper_of("anna") is None


def test_a_planned_service_starting_there_and_then_may_be_the_same() -> None:
    """LOK-19: the paper's number may differ from the plan's; the start says it may be the
    same service."""
    drift = started()
    found = read(drift, start="06:35")
    assert paper.view(drift, found).said == (
        "Tjänst 3 i planen startar 06:35 vid Norrby. Är det samma som pappret?"
    )


# --- Invisible to TKL until approved (LOK-13, LF22) ---------------------------------------------


def test_no_station_sees_it_until_trafikledningen_approves() -> None:
    """LOK-13: not in any snapshot, no clearance, not in Nu's trains, and the driver's messages
    about it reach no station."""
    drift = started()
    trains_before = {t.id for t in drift.package.trains}
    read(drift)
    assert {t.id for t in drift.package.trains} == trains_before
    for place in everywhere(drift, at(20)):
        assert all(call.train not in (PAPER, "G 4521") for call in place.calls)
        assert all(not call.paper for call in place.calls)
        assert place.clearances == [] and place.driver_messages == []
    drivers.message(drift, "anna", station.DriverMessageKind.DELAYED, at(30))
    drivers.check_in(drift, "anna", "nby", "3", at(31))
    assert drift.history[-2].train is None and drift.history[-1].train is None
    assert all(place.driver_messages == [] for place in everywhere(drift, at(32)))
    shown = nu(drift, at(32))
    assert all(not leg.paper for leg in shown.legs)
    assert shown.driver_messages[0].service_number == "24", "Trafikledningen hears of it in Nu"
    assert drift.lookup("nby", "4521") == []


# --- Approved: a train Drift knows, marked (LOK-13) ---------------------------------------------


def test_approved_it_is_an_extra_train_marked_after_the_paper_wherever_it_shows() -> None:
    """LOK-13, DRIFT-41, H12: an extra train with the paper's calls at the meet's places; the
    stations see and clear it, marked; the driver keeps it, now with Drift's reality."""
    drift = started()
    drivers.set_settings(drift, events.DriverSettings(reality=True, clearances=True), at(1))
    read(drift)
    extra = paper.approve(drift, PAPER, None, at(40))
    assert [e.kind for e in drift.history[-2:]] == [
        events.EventKind.CHANGE_MADE,
        events.EventKind.PAPER_APPROVED,
    ]
    assert (extra.paper, extra.number, extra.departure) == (PAPER, "G 4521", "06:41")
    train = next(t for t in drift.package.trains if t.id == f"x-c-{PAPER}")
    assert [(c.place, c.arrival, c.departure, c.track) for c in train.calls] == [
        ("nby", None, "06:41", "3"),
        ("asn", "06:49", None, None),
        ("lvh", None, "06:55", None),
        ("mla", "06:59", "07:01", None),
        ("sjv", "07:10", None, "2"),
    ]
    assert not train.calls[2].stops
    found = drift.drivers.papers[PAPER]
    assert (found.status, found.train, found.train_number) == (
        events.PaperStatus.APPROVED,
        train.id,
        "G 4521",
    )
    norrby = snapshot(drift, "nby", at(41))
    (call,) = [c for c in norrby.calls if c.train == train.id]
    assert call.paper and call.train_number == "G 4521"
    assert station.Action.CLEARANCE_REQUEST in call.allowed_actions, "the station can clear it"
    send(drift, "nby", station.Action.CLEARANCE_REQUEST, at(42), call=call.call,
         section="s-nby-asn", clearance_id="clr-papper1")  # fmt: skip
    assert [c.paper for c in snapshot(drift, "asn", at(43)).clearances] == [True]
    assert any(leg.paper for leg in nu(drift, at(43)).legs)
    # The driver keeps it, marked, with Drift's reality and the clearances' word.
    held = drift.drivers.service_of("anna")
    assert held is not None and held.service == REF
    service = drivers.find(drift, REF)
    assert service is not None and service.parts[0].train.id == train.id
    plan = drivers.korplan(drift, service, at(44), 1)
    assert plan.paper == events.PaperStatus.APPROVED
    assert plan.rows[0].call == train.calls[0].id and plan.rows[0].real is not None
    assert plan.rows[0].clearance is not None and plan.rows[0].clearance.status == "waiting"
    assert plan.rows[4].place == contract.UNKNOWN_PLACE and plan.rows[4].real is None
    assert plan.position is not None and plan.position.paper
    assert drivers.offer(drift, service).paper == events.PaperStatus.APPROVED
    # Decided once.
    with pytest.raises(Refused) as twice:
        paper.approve(drift, PAPER, None, at(45))
    assert twice.value.reason == Reason.PAPER_DECIDED


def test_the_dispatcher_gives_the_number_the_paper_lacks() -> None:
    drift = started()
    read(drift, train=None)
    with pytest.raises(Refused) as unnamed:
        paper.approve(drift, PAPER, None, at(40))
    assert unnamed.value.reason == Reason.PAPER_NO_NUMBER
    paper.approve(drift, PAPER, "9024", at(41))
    assert drift.drivers.papers[PAPER].train_number == "9024"
    with pytest.raises(Refused) as unknown:
        paper.approve(drift, "papper-ffffffffff", None, at(42))
    assert unknown.value.reason == Reason.UNKNOWN_PAPER


def test_a_paper_train_on_a_meet_without_duties_is_not_offered_as_a_train() -> None:
    """LOK-31: on a meet with trains only, the approved paper's train stays the paper's."""
    drift = started(provbanan().model_copy(update={"duties": []}))
    read(drift)
    paper.approve(drift, PAPER, None, at(40))
    listed = drivers.service_list(drift).services
    assert all(o.number != "G 4521" for o in listed)


# --- Rejected: the driver is told why -------------------------------------------------------------


def test_rejected_the_driver_no_longer_runs_it_and_is_told_why() -> None:
    drift = started()
    read(drift)
    paper.reject(drift, PAPER, "Tjänst 3 är samma. Ta den.", at(40))
    found = drift.drivers.papers[PAPER]
    assert (found.status, found.reason) == (
        events.PaperStatus.REJECTED,
        "Tjänst 3 är samma. Ta den.",
    )
    assert drift.drivers.service_of("anna") is None
    shown = drift.drivers.paper_of("anna")
    assert shown is not None and shown.reason == "Tjänst 3 är samma. Ta den."
    assert all(t.id != f"x-c-{PAPER}" for t in drift.package.trains)
    with pytest.raises(Refused) as again:
        paper.approve(drift, PAPER, None, at(41))
    assert again.value.reason == Reason.PAPER_DECIDED
    with pytest.raises(Refused):
        drivers.claim(drift, REF, "bo", at(42))
    drivers.claim(drift, D3, "anna", at(43))
    assert drift.drivers.paper_of("anna") is None


# --- The events are the state (DRIFT-21) ----------------------------------------------------------


def test_a_restart_reads_the_papers_back(tmp_path: Path) -> None:
    store = PreviewStore(tmp_path / "drift.sqlite3", provbanan())
    run = store.start()
    store.drive(run, lambda d, now: read(d))
    store.drive(run, lambda d, now: paper.approve(d, PAPER, "9024", now))
    again = store.state(run)
    found = again.drivers.papers[PAPER]
    assert (found.status, found.train_number) == (events.PaperStatus.APPROVED, "9024")
    assert f"x-c-{PAPER}" in again.drivers.paper_trains
    assert store.keep_paper_pages(run, PAPER, [(b"\xff\xd8\xff\xd9", "image/jpeg")]) == 1
    assert store.paper_pages(run, PAPER) == 1
    assert store.paper_page(run, PAPER, 1) == (b"\xff\xd8\xff\xd9", "image/jpeg")


def test_an_extra_train_from_the_paper_crosses_midnight() -> None:
    """A time more than half a day before the one before is the next game day."""
    package = provbanan()
    extra = events.ExtraTrain(
        number="9999",
        departure="23:50",
        calls=[
            events.ExtraCall(place="nby", departure="23:50"),
            events.ExtraCall(place="asn", arrival="23:58", departure="00:05"),
            events.ExtraCall(place="mla", arrival="00:15"),
        ],
        paper=PAPER,
    )
    made = changes.apply(package, extra, "c1")
    train = next(t for t in made.trains if t.id == "x-c1")
    assert [(c.arrival, c.departure, c.day_offset) for c in train.calls] == [
        (None, "23:50", 0),
        ("23:58", "00:05", 0),
        ("00:15", None, 1),
    ]
    with pytest.raises(ValueError):
        events.ExtraTrain(number="1", departure="06:00", calls=[events.ExtraCall(place="nby")])
    with pytest.raises(changes.ChangeError):
        changes.apply(
            package,
            extra.model_copy(update={"calls": [*extra.calls, events.ExtraCall(place="saro")]}),
            "c2",
        )
