"""Beläggningen från detekteringen (#85 del c, DRIFT-10, DRIFT-16, KLAR-11, KLAR-16, STV-10).

section.occupancy is accepted only from a station whose TKL connected at level 3, for a section
from its place; Drift keeps the latest per section and place as an event, so a restart reads it
back. An occupied section stops direct clearance and the automation on it, and never frees
anything: the arrival is still Ankommit, or the entry route released after passage, which TKL
reports as train.arrived.

Provbanan: Norrby – Åsen single track, Åsen – Mellanå double track, Mellanå – Sjövik direct.
"""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.resources import files
from typing import Any
from uuid import uuid4

import pytest

from contracts import drift as events
from contracts import station
from contracts.meet import MeetPackage
from contracts.reasons import Reason
from drift.automatik import OCCUPIED
from drift.engine import Drift, Outcome, Refused
from drift.now import now
from drift.snapshot import snapshot
from drift.tests.test_automatik import World

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
Action = station.Action
DIRECT = "s-mla-sjv"
SINGLE = "s-nby-asn"


@pytest.fixture
def drift() -> Drift:
    raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    engine = Drift(MeetPackage.model_validate_json(raw), [], now=NOW)
    engine.start(NOW)
    return engine


def send(
    drift: Drift, place: str, action: station.Action, level: int = 0, **payload: Any
) -> Outcome:
    return drift.command(
        station.Command(
            message_id=uuid4().hex,
            client_id=f"tkl-{place}",
            place=place,
            context=drift.context,
            action=action,
            payload=payload,
        ),
        NOW,
        level=level,
    )


def occupy(drift: Drift, place: str, section: str, occupied: bool = True, level: int = 3) -> Any:
    return send(drift, place, Action.SECTION_OCCUPANCY, level, section=section, occupied=occupied)


def refused(drift: Drift, place: str, section: str, level: int) -> Reason:
    before = len(drift.history)
    with pytest.raises(Refused) as error:
        occupy(drift, place, section, level=level)
    assert len(drift.history) == before, "a refusal changes nothing"
    return error.value.reason


def test_occupancy_is_taken_from_a_station_at_level_3_and_refused_below(drift: Drift) -> None:
    """DRIFT-10, KLAR-11, KLAR-16: no section.occupancy at level 0, nor at level 1–2; at level 3
    it is a Drift event naming the place, for a section from the place, as signal.exit."""
    for level in (0, 1, 2):
        assert refused(drift, "asn", SINGLE, level) == Reason.NOT_LEVEL_3
    outcome = occupy(drift, "asn", SINGLE)
    assert outcome.revision is not None and outcome.revision.scope == station.RevisionScope.PLACE
    last = drift.history[-1]
    assert (last.kind, last.place) == (events.EventKind.SECTION_OCCUPANCY, "asn")
    assert last.data == {"section": SINGLE, "occupied": True, "parts": {}}
    assert drift.detected(SINGLE) and drift.detected_by(SINGLE) == ["asn"]
    before = len(drift.history)
    occupy(drift, "asn", SINGLE)
    assert len(drift.history) == before, "the same occupancy again is no new event"
    assert refused(drift, "asn", "s-nope", 3) == Reason.UNKNOWN_SECTION
    assert refused(drift, "asn", DIRECT, 3) == Reason.WRONG_PLACE


def test_the_latest_per_place_counts_and_survives_a_restart(drift: Drift) -> None:
    """The section is occupied while any station at its ends says so; one end's free report
    does not free the other's. A restart reads the events back."""
    occupy(drift, "nby", SINGLE)
    occupy(drift, "asn", SINGLE)
    occupy(drift, "asn", SINGLE, occupied=False)
    assert drift.detected(SINGLE) and drift.detected_by(SINGLE) == ["nby"]
    again = Drift(drift.package, list(drift.history), now=NOW)
    assert again.detected(SINGLE) and again.detected_by(SINGLE) == ["nby"]
    occupy(again, "nby", SINGLE, occupied=False)
    assert not again.detected(SINGLE)


def test_it_shows_in_the_snapshot_at_both_ends_and_in_nu(drift: Drift) -> None:
    before = snapshot(drift, "nby", NOW).place_revision
    occupy(drift, "asn", SINGLE)
    for place in ("nby", "asn"):
        here = next(s for s in snapshot(drift, place, NOW).sections if s.section == SINGLE)
        assert here.detected and not here.occupied, "detection, not a train on its way"
    assert snapshot(drift, "nby", NOW).place_revision > before, "the other end is told too"
    other = next(s for s in snapshot(drift, "asn", NOW).sections if s.section == "s-asn-mla")
    assert not other.detected
    seen = now(drift, NOW)
    assert [(d.section, d.place_a, d.place_b, d.by) for d in seen.detected] == [
        (SINGLE, "nby", "asn", ["asn"])
    ]
    occupy(drift, "asn", SINGLE, occupied=False)
    assert now(drift, NOW).detected == []


def test_occupancy_stops_direct_clearance(drift: Drift) -> None:
    """DRIFT-16: on the direct section the request waits for the receiver while the section is
    occupied; a free report does not answer it. Free, the next request is direct again."""
    occupy(drift, "sjv", DIRECT)
    first = "clr-first"
    send(
        drift, "mla", Action.CLEARANCE_REQUEST, call="t101-mla", section=DIRECT, clearance_id=first
    )
    assert drift.cases[first].status == station.ClearanceStatus.WAITING
    occupy(drift, "sjv", DIRECT, occupied=False)
    assert drift.cases[first].status == station.ClearanceStatus.WAITING, "nothing by itself"
    send(drift, "sjv", Action.CLEARANCE_RESPONSE, clearance_id=first, approved=True)
    assert drift.cases[first].status == station.ClearanceStatus.APPROVED
    send(drift, "mla", Action.TRAIN_DEPARTED, call="t101-mla")
    send(drift, "sjv", Action.TRAIN_ARRIVED, call="t101-sjv")
    second = "clr-second"
    send(
        drift, "sjv", Action.CLEARANCE_REQUEST, call="t102-sjv", section=DIRECT, clearance_id=second
    )
    assert drift.cases[second].status == station.ClearanceStatus.APPROVED, "free: direct again"


def test_occupancy_never_frees_anything(drift: Drift) -> None:
    """DRIFT-16: a train on its way stays on its way when the section goes free, and its
    arrival is still the station's train.arrived, occupied or not."""
    clearance = "clr-101"
    asked: dict[str, Any] = {"call": "t101-nby", "section": SINGLE, "clearance_id": clearance}
    send(drift, "nby", Action.CLEARANCE_REQUEST, **asked)
    send(drift, "asn", Action.CLEARANCE_RESPONSE, clearance_id=clearance, approved=True)
    send(drift, "nby", Action.TRAIN_DEPARTED, call="t101-nby")
    occupy(drift, "asn", SINGLE)
    occupy(drift, "asn", SINGLE, occupied=False)
    assert "t101-nby" not in drift.arrived
    assert [t.call for t in snapshot(drift, "asn", NOW).on_the_way] == ["t101-asn"]
    assert drift.cases[clearance].active
    occupy(drift, "asn", SINGLE)
    send(drift, "asn", Action.TRAIN_ARRIVED, call="t101-asn")
    assert "t101-nby" in drift.arrived, "an arrival is taken while the section is occupied"
    assert drift.detected(SINGLE), "and the occupancy stays until the station says free"


def detect(world: World, occupied: bool = True) -> None:
    """Åsen's TKL at level 3 reports the single track to Norrby."""
    world.drift.command(
        station.Command(
            message_id=uuid4().hex,
            client_id="tkl-asn",
            place="asn",
            context=world.drift.context,
            action=Action.SECTION_OCCUPANCY,
            payload={"section": SINGLE, "occupied": occupied},
        ),
        world.now,
        level=3,
    )


def test_occupancy_stops_the_automation_on_the_section() -> None:
    """DRIFT-16, F14: the automation asks for no clearance onto an occupied section and sends
    no train onto it; the rest of the timetable goes on. Free again, it goes on there too."""
    world = World()
    detect(world)
    world.until("06:20")
    assert not any(c.leg.section.id == SINGLE for c in world.drift.cases.values())
    assert world.auto.blocked["t101-nby"] == OCCUPIED
    assert "t102-sjv" in world.drift.arrived, "the rest of the line runs as before"
    detect(world, occupied=False)
    world.until("06:45")
    assert "t101-nby" in world.drift.arrived


def test_occupancy_holds_the_automations_answer() -> None:
    """A request already waiting is not answered by the automation while the section is
    occupied."""
    world = World(settings={"answer_seconds": 30})
    world.wait(1)
    assert world.case("t101-nby").status == station.ClearanceStatus.WAITING
    detect(world)
    world.wait(60)
    assert world.case("t101-nby").status == station.ClearanceStatus.WAITING
    assert world.auto.blocked["t101-nby"] == OCCUPIED


def test_occupancy_holds_the_automations_departure() -> None:
    """A cleared train is not sent onto an occupied section."""
    world = World(settings={"answer_seconds": 0})
    world.until("06:59")
    assert world.case("t103-nby").status == station.ClearanceStatus.APPROVED
    assert not world.case("t103-nby").departed
    detect(world)
    world.until("07:05")
    assert not world.case("t103-nby").departed
    assert world.auto.blocked["t103-nby"] == OCCUPIED
    detect(world, occupied=False)
    world.until("07:06")
    assert world.case("t103-nby").departed
