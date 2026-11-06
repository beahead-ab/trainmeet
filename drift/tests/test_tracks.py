"""Tracks, through trains and putting trains away in the Drift engine (old Server 2.1.0–4.12).

Provbanan: 101 runs Norrby → Åsen → Mellanå → Sjövik and stops on track 1 everywhere; 102 runs
the other way on track 2 and ends at Norrby. Each test here is a rule the old Server kept, told
straight to Drift with station commands, the way any client sends them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.resources import files
from uuid import uuid4

import pytest

from contracts import station
from contracts.meet import MeetPackage
from contracts.reasons import Reason
from drift.engine import Drift, Refused

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


@pytest.fixture
def drift() -> Drift:
    raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    engine = Drift(MeetPackage.model_validate_json(raw), [], now=NOW)
    engine.start(NOW)
    return engine


def send(drift: Drift, place: str, action: station.Action, **payload: object) -> None:
    drift.command(
        station.Command(
            message_id=uuid4().hex,
            client_id=f"test-{place}",
            place=place,
            context=drift.context,
            action=action,
            payload=payload,
        ),
        NOW,
    )


def request(drift: Drift, place: str, call: str, section: str) -> str:
    clearance = f"clr-{uuid4().hex}"
    send(
        drift,
        place,
        station.Action.CLEARANCE_REQUEST,
        call=call,
        section=section,
        clearance_id=clearance,
    )
    return clearance


def kinds(drift: Drift) -> list[str]:
    return [event.kind.value for event in drift.history[1:]]


def test_a_train_nobody_sent_is_moved_here_on_its_planned_track(drift: Drift) -> None:
    send(drift, "nby", station.Action.TRAIN_ARRIVED, call="t102-nby")
    assert kinds(drift) == ["train.moved_here"]
    assert drift.tracks["t102-asn"] == "2"
    assert "t102-asn" in drift.arrived


def test_an_unknown_track_is_refused(drift: Drift) -> None:
    with pytest.raises(Refused) as refused:
        send(drift, "nby", station.Action.TRAIN_ARRIVED, call="t102-nby", track="9")
    assert refused.value.reason == Reason.UNKNOWN_TRACK
    assert kinds(drift) == []


def test_an_arrival_waiting_for_an_answer_is_refused(drift: Drift) -> None:
    request(drift, "nby", "t101-nby", "s-nby-asn")
    with pytest.raises(Refused) as refused:
        send(drift, "asn", station.Action.TRAIN_ARRIVED, call="t101-asn")
    assert refused.value.reason == Reason.TRAIN_NOT_DEPARTED


def test_a_cleared_train_never_reported_departed_can_be_taken_in(drift: Drift) -> None:
    clearance = request(drift, "nby", "t101-nby", "s-nby-asn")
    send(drift, "asn", station.Action.CLEARANCE_RESPONSE, clearance_id=clearance, approved=True)
    send(drift, "asn", station.Action.TRAIN_ARRIVED, call="t101-asn", track="2")
    assert kinds(drift)[-1] == "train.arrived"
    assert drift.tracks["t101-nby"] == "2"
    assert drift.planned_track(drift.legs["t101-nby"]) == "1", "the plan is kept"
    assert drift.active_case("t101-nby") is None


def test_an_occupied_track_does_not_stop_the_arrival(drift: Drift) -> None:
    """Casper, 2026-10-02: taken in all the same; the box says so."""
    send(drift, "asn", station.Action.TRAIN_ARRIVED, call="t4501-asn")  # 4501 stands on 1.
    standing = drift.occupant("asn", "1", "t101-nby")
    assert standing is not None and standing.train.number == "4501"
    send(drift, "asn", station.Action.TRAIN_ARRIVED, call="t101-asn")
    assert drift.tracks["t101-nby"] == "1"


def test_a_train_that_went_on_no_longer_holds_its_track(drift: Drift) -> None:
    send(drift, "asn", station.Action.TRAIN_ARRIVED, call="t101-asn")
    assert drift.occupant("asn", "1") is not None
    clearance = request(drift, "asn", "t101-asn", "s-asn-mla")
    send(drift, "mla", station.Action.CLEARANCE_RESPONSE, clearance_id=clearance, approved=True)
    send(drift, "asn", station.Action.TRAIN_DEPARTED, call="t101-asn")
    assert drift.occupant("asn", "1") is None


def test_a_through_train_may_be_asked_for_while_on_its_way_in(drift: Drift) -> None:
    """Casper, 2026-10-02: the next leg can be requested before the train is seen to come."""
    first = request(drift, "nby", "t101-nby", "s-nby-asn")
    send(drift, "asn", station.Action.CLEARANCE_RESPONSE, clearance_id=first, approved=True)
    send(drift, "nby", station.Action.TRAIN_DEPARTED, call="t101-nby")
    request(drift, "asn", "t101-asn", "s-asn-mla")
    assert drift.active_case("t101-asn") is not None


def test_a_completed_leg_cannot_be_asked_for_again(drift: Drift) -> None:
    send(drift, "asn", station.Action.TRAIN_ARRIVED, call="t101-asn")
    with pytest.raises(Refused) as refused:
        request(drift, "nby", "t101-nby", "s-nby-asn")
    assert refused.value.reason == Reason.INVALID_DEPARTURE


def test_sent_on_unseen_the_train_jumps_here(drift: Drift) -> None:
    """Never seen to come in: it jumps here with the departure (old Server 2.1.0)."""
    clearance = request(drift, "asn", "t101-asn", "s-asn-mla")
    send(drift, "mla", station.Action.CLEARANCE_RESPONSE, clearance_id=clearance, approved=True)
    send(drift, "asn", station.Action.TRAIN_DEPARTED, call="t101-asn")
    assert kinds(drift)[-2:] == ["train.moved_here", "train.departed"]
    assert "t101-nby" in drift.arrived
    assert drift.tracks["t101-nby"] == "1"


def test_the_jump_ends_a_case_still_open_on_the_way_in(drift: Drift) -> None:
    """Whatever the leg in last knew, answered or sent, it is brought to its end."""
    request(drift, "nby", "t101-nby", "s-nby-asn")
    clearance = request(drift, "asn", "t101-asn", "s-asn-mla")
    send(drift, "mla", station.Action.CLEARANCE_RESPONSE, clearance_id=clearance, approved=True)
    send(drift, "asn", station.Action.TRAIN_DEPARTED, call="t101-asn")
    assert kinds(drift)[-3:] == ["clearance.answered", "train.arrived", "train.departed"]
    assert drift.active_case("t101-nby") is None
    assert "t101-nby" in drift.arrived


def test_a_train_that_ended_here_is_put_away_and_frees_its_track(drift: Drift) -> None:
    """Casper, 2026-10-10: at a manned place the operator reports it put away."""
    send(drift, "nby", station.Action.TRAIN_ARRIVED, call="t102-nby")
    assert drift.ended_here("t102-asn")
    assert drift.occupant("nby", "2") is not None
    send(drift, "nby", station.Action.TRAIN_SET_ASIDE, call="t102-nby")
    assert kinds(drift)[-1] == "train.set_aside"
    assert not drift.ended_here("t102-asn")
    assert drift.occupant("nby", "2") is None
    with pytest.raises(Refused) as refused:
        send(drift, "nby", station.Action.TRAIN_SET_ASIDE, call="t102-nby")
    assert refused.value.reason == Reason.INVALID_ARRIVAL


def test_a_train_that_goes_on_cannot_be_put_away(drift: Drift) -> None:
    send(drift, "asn", station.Action.TRAIN_ARRIVED, call="t101-asn")
    with pytest.raises(Refused) as refused:
        send(drift, "asn", station.Action.TRAIN_SET_ASIDE, call="t101-asn")
    assert refused.value.reason == Reason.INVALID_ARRIVAL


def test_only_the_place_it_stands_at_puts_it_away(drift: Drift) -> None:
    send(drift, "nby", station.Action.TRAIN_ARRIVED, call="t102-nby")
    with pytest.raises(Refused) as refused:
        send(drift, "asn", station.Action.TRAIN_SET_ASIDE, call="t102-nby")
    assert refused.value.reason == Reason.WRONG_PLACE


def test_the_track_picker_starts_on_the_plan_then_standard_tracks(drift: Drift) -> None:
    """4.9.0: the train's own track first, then the place's standard tracks, then the rest."""
    assert drift.track_choices(drift.legs["t101-nby"]) == ["1", "2", "3"]
    # 4502 has track 3 at Norrby; Norrby's standard tracks follow, the goods track first.
    leg = drift.legs["t4502-asn"]
    assert drift.track_choices(leg)[0] == "3"
    assert set(drift.track_choices(leg)) == {"1", "2", "3"}


def test_the_put_away_survives_a_replay(drift: Drift) -> None:
    send(drift, "nby", station.Action.TRAIN_ARRIVED, call="t102-nby", track="3")
    send(drift, "nby", station.Action.TRAIN_SET_ASIDE, call="t102-nby")
    replayed = Drift(drift.package, list(drift.history), now=NOW)
    assert replayed.tracks["t102-asn"] == "3"
    assert "t102-asn" in replayed.set_aside
    assert replayed.occupant("nby", "3") is None
