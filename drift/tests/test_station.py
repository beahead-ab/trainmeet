"""The station protocol in Drift, ported from the old Server's test_protocol_v2.py.

Provbanan stands in for the old fixture: Norrby – Åsen single track, Åsen – Mellanå double
track, Mellanå – Sjövik direct. Each test sends station commands as TKL or the TMBox app
would, and reads the snapshot back. Old names: movement became call, station became place.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import Any
from uuid import uuid4

import pytest

from contracts import station
from contracts.meet import MeetPackage
from contracts.reasons import Reason
from drift.engine import Drift, Outcome, Refused
from drift.snapshot import snapshot

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
Action = station.Action


@pytest.fixture
def drift() -> Drift:
    raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    engine = Drift(MeetPackage.model_validate_json(raw), [], now=NOW)
    engine.start(NOW)
    return engine


def send(
    drift: Drift,
    place: str,
    action: station.Action,
    expected: station.Revision | None = None,
    **payload: Any,
) -> Outcome:
    return drift.command(
        station.Command(
            message_id=uuid4().hex,
            client_id=f"tkl-{place}",
            place=place,
            context=drift.context,
            action=action,
            expected_revision=expected,
            payload=payload,
        ),
        NOW,
    )


def refused(drift: Drift, place: str, action: station.Action, **payload: Any) -> Reason:
    before = len(drift.history)
    with pytest.raises(Refused) as error:
        send(drift, place, action, **payload)
    assert len(drift.history) == before, "a refusal changes nothing"
    return error.value.reason


def request(drift: Drift, place: str, call: str, section: str) -> str:
    clearance = f"clr-{uuid4().hex[:12]}"
    send(drift, place, Action.CLEARANCE_REQUEST, call=call, section=section, clearance_id=clearance)
    return clearance


def call_here(drift: Drift, place: str, call: str) -> station.CallHere:
    return next(c for c in snapshot(drift, place, NOW).calls if c.call == call)


def kinds(drift: Drift) -> list[str]:
    return [event.kind.value for event in drift.history[1:]]


# --- Commands ------------------------------------------------------------------------------


def test_a_command_moves_the_call_and_raises_its_revision(drift: Drift) -> None:
    outcome = send(drift, "nby", Action.TRAIN_POSITION_SET, call="t101-nby", value=True)
    assert outcome.revision == station.Revision(
        scope=station.RevisionScope.CALL, key="t101-nby", value=1
    )
    assert call_here(drift, "nby", "t101-nby").positioned is True


def test_a_stale_call_revision_is_refused(drift: Drift) -> None:
    send(drift, "nby", Action.TRAIN_POSITION_SET, call="t101-nby", value=True)
    stale = station.Revision(scope=station.RevisionScope.CALL, key="t101-nby", value=0)
    with pytest.raises(Refused) as error:
        send(drift, "nby", Action.TRAIN_CREW_READY_SET, stale, call="t101-nby", value=True)
    assert error.value.reason == Reason.STALE_REVISION


def test_a_call_revision_is_never_judged_by_the_place_revision(drift: Drift) -> None:
    send(drift, "nby", Action.TRAIN_POSITION_SET, call="t101-nby", value=True)
    send(drift, "nby", Action.TRAIN_POSITION_SET, call="t103-nby", value=True)
    place = snapshot(drift, "nby", NOW).place_revision
    assert place != 1
    current = station.Revision(scope=station.RevisionScope.PLACE, key="nby", value=place)
    send(drift, "nby", Action.TRAIN_CREW_READY_SET, current, call="t101-nby", value=True)
    wrong = station.Revision(scope=station.RevisionScope.CALL, key="t101-nby", value=place + 1)
    with pytest.raises(Refused) as error:
        send(drift, "nby", Action.TRAIN_CREW_READY_SET, wrong, call="t101-nby", value=False)
    assert error.value.reason == Reason.STALE_REVISION


def test_a_track_change_must_name_a_track_of_the_place(drift: Drift) -> None:
    send(drift, "nby", Action.TRAIN_TRACK_CHANGE, call="t101-nby", track="2")
    assert call_here(drift, "nby", "t101-nby").track == "2"
    assert call_here(drift, "nby", "t101-nby").planned_track == "1", "the plan stays"
    assert refused(drift, "nby", Action.TRAIN_TRACK_CHANGE, call="t101-nby", track="9") == (
        Reason.UNKNOWN_TRACK
    )


def test_train_lookup_answers_from_the_place_without_touching_state(drift: Drift) -> None:
    before = len(drift.history)
    outcome = send(drift, "asn", Action.TRAIN_LOOKUP, train_number="101")
    assert len(drift.history) == before
    assert [(m.call, m.from_place, m.to_place, m.time) for m in outcome.result] == [
        ("t101-asn", "nby", "mla", "06:10")
    ]
    assert refused(drift, "asn", Action.TRAIN_LOOKUP, train_number="999") == (
        Reason.UNKNOWN_TRAIN_NUMBER
    )


def test_detection_waits_for_tkl_level_3(drift: Drift) -> None:
    assert refused(drift, "asn", Action.SECTION_OCCUPANCY, section="s-nby-asn", occupied=True) == (
        Reason.NOT_LEVEL_3
    )


def test_a_command_for_another_place_is_refused(drift: Drift) -> None:
    assert refused(drift, "asn", Action.TRAIN_POSITION_SET, call="t101-nby", value=True) == (
        Reason.WRONG_PLACE
    )
    assert refused(drift, "asn", Action.TRAIN_POSITION_SET, call="nothing", value=True) == (
        Reason.UNKNOWN_CALL
    )


# --- Clearance -----------------------------------------------------------------------------


def test_a_request_waits_for_the_other_place_to_answer(drift: Drift) -> None:
    clearance = request(drift, "nby", "t101-nby", "s-nby-asn")
    for place in ("nby", "asn"):
        (case,) = snapshot(drift, place, NOW).clearances
        assert (case.clearance_id, case.status, case.revision) == (
            clearance,
            station.ClearanceStatus.WAITING,
            1,
        )
        assert (case.from_place, case.to_place, case.requested_at) == ("nby", "asn", "06:00")
    assert call_here(drift, "nby", "t101-nby").departure_state == station.DepartureState.REQUESTED
    assert Action.CLEARANCE_RESPONSE in call_here(drift, "asn", "t101-asn").allowed_actions


def test_the_receiving_place_approves_and_both_ends_see_it(drift: Drift) -> None:
    clearance = request(drift, "nby", "t101-nby", "s-nby-asn")
    outcome = send(drift, "asn", Action.CLEARANCE_RESPONSE, clearance_id=clearance, approved=True)
    assert outcome.revision == station.Revision(
        scope=station.RevisionScope.CASE, key=clearance, value=2
    )
    assert snapshot(drift, "nby", NOW).clearances[0].status == station.ClearanceStatus.APPROVED
    assert call_here(drift, "nby", "t101-nby").departure_state == station.DepartureState.CLEARED


def test_only_the_receiver_answers_and_only_the_sender_cancels(drift: Drift) -> None:
    clearance = request(drift, "nby", "t101-nby", "s-nby-asn")
    answer = {"clearance_id": clearance, "approved": True}
    assert refused(drift, "nby", Action.CLEARANCE_RESPONSE, **answer) == Reason.NOT_RECEIVER
    assert refused(drift, "asn", Action.CLEARANCE_CANCEL, clearance_id=clearance) == (
        Reason.NOT_SENDER
    )
    send(drift, "nby", Action.CLEARANCE_CANCEL, clearance_id=clearance)
    assert snapshot(drift, "nby", NOW).clearances == []
    assert refused(drift, "asn", Action.CLEARANCE_RESPONSE, **answer) == (
        Reason.CLEARANCE_NOT_PENDING
    )


def test_a_single_track_section_has_one_shared_channel(drift: Drift) -> None:
    request(drift, "nby", "t101-nby", "s-nby-asn")
    reason = refused(
        drift,
        "asn",
        Action.CLEARANCE_REQUEST,
        call="t102-asn",
        section="s-nby-asn",
        clearance_id="clr-other",
    )
    assert reason == Reason.CHANNEL_OCCUPIED


def test_opposite_directions_on_a_double_track_never_block_each_other(drift: Drift) -> None:
    """Decision B7: directed channels from the start."""
    outbound = request(drift, "asn", "t101-asn", "s-asn-mla")
    inbound = request(drift, "mla", "t102-mla", "s-asn-mla")
    assert outbound != inbound
    assert len(snapshot(drift, "asn", NOW).clearances) == 2


def test_a_track_change_under_a_waiting_request_invalidates_it(drift: Drift) -> None:
    clearance = request(drift, "nby", "t101-nby", "s-nby-asn")
    send(drift, "nby", Action.TRAIN_TRACK_CHANGE, call="t101-nby", track="2")
    assert drift.cases[clearance].status == station.ClearanceStatus.INVALIDATED
    # Not a silent rewrite: the case is closed and the section is free.
    assert snapshot(drift, "nby", NOW).clearances == []
    assert kinds(drift) == [
        "clearance.requested",
        "train.track_changed",
        "clearance.invalidated",
    ]
    request(drift, "nby", "t101-nby", "s-nby-asn")


def test_a_request_never_lapses(drift: Drift) -> None:
    """Decided (A5): an unanswered request never runs out; it is reminded instead."""
    clearance = request(drift, "nby", "t101-nby", "s-nby-asn")
    later = NOW + timedelta(hours=6)
    assert snapshot(drift, "asn", later).clearances[0].clearance_id == clearance
    assert drift.cases[clearance].status == station.ClearanceStatus.WAITING


def test_an_arriving_train_frees_the_line_it_was_granted(drift: Drift) -> None:
    clearance = request(drift, "nby", "t101-nby", "s-nby-asn")
    send(drift, "asn", Action.CLEARANCE_RESPONSE, clearance_id=clearance, approved=True)
    send(drift, "nby", Action.TRAIN_DEPARTED, call="t101-nby")
    seen = snapshot(drift, "asn", NOW)
    assert [(t.call, t.other_place, t.departed_at) for t in seen.on_the_way] == [
        ("t101-asn", "nby", "06:00")
    ]
    assert [t.call for t in snapshot(drift, "nby", NOW).have_left] == ["t101-asn"]
    assert next(s for s in seen.sections if s.section == "s-nby-asn").occupied
    send(drift, "asn", Action.TRAIN_ARRIVED, call="t101-asn")
    seen = snapshot(drift, "asn", NOW)
    assert seen.clearances == [] and seen.on_the_way == []
    assert call_here(drift, "asn", "t101-asn").arrival_state == station.ArrivalState.ARRIVED
    request(drift, "asn", "t102-asn", "s-nby-asn")  # The section is free again.


def test_a_stale_case_revision_is_refused(drift: Drift) -> None:
    clearance = request(drift, "nby", "t101-nby", "s-nby-asn")
    stale = station.Revision(scope=station.RevisionScope.CASE, key=clearance, value=99)
    with pytest.raises(Refused) as error:
        send(drift, "asn", Action.CLEARANCE_RESPONSE, stale, clearance_id=clearance, approved=True)
    assert error.value.reason == Reason.STALE_REVISION


# --- Uppställt, föraren på plats and ledig linje -------------------------------------------


def test_ready_is_what_the_two_declarations_add_up_to(drift: Drift) -> None:
    start = call_here(drift, "nby", "t101-nby")
    assert (start.positioned, start.crew_ready) == (False, False)
    send(drift, "nby", Action.TRAIN_POSITION_SET, call="t101-nby", value=True)
    positioned = call_here(drift, "nby", "t101-nby")
    assert positioned.allowed_actions[0] == Action.TRAIN_CREW_READY_SET
    send(drift, "nby", Action.TRAIN_CREW_READY_SET, call="t101-nby", value=True)
    ready = call_here(drift, "nby", "t101-nby")
    assert (ready.positioned, ready.crew_ready) == (True, True)
    assert Action.CLEARANCE_REQUEST in ready.allowed_actions


def test_the_crew_alone_is_not_positioned(drift: Drift) -> None:
    send(drift, "nby", Action.TRAIN_CREW_READY_SET, call="t101-nby", value=True)
    alone = call_here(drift, "nby", "t101-nby")
    assert (alone.crew_ready, alone.positioned) == (True, False)
    assert Action.CLEARANCE_REQUEST in alone.allowed_actions, "never needed to depart (C4)"


def test_the_declarations_survive_a_restart(drift: Drift) -> None:
    send(drift, "nby", Action.TRAIN_POSITION_SET, call="t101-nby", value=True)
    send(drift, "nby", Action.TRAIN_CREW_READY_SET, call="t101-nby", value=True)
    again = Drift(drift.package, list(drift.history), now=NOW)
    assert snapshot(again, "nby", NOW) == snapshot(drift, "nby", NOW)


def test_a_departed_train_offers_nothing_more(drift: Drift) -> None:
    clearance = request(drift, "nby", "t101-nby", "s-nby-asn")
    send(drift, "asn", Action.CLEARANCE_RESPONSE, clearance_id=clearance, approved=True)
    send(drift, "nby", Action.TRAIN_DEPARTED, call="t101-nby")
    departed = call_here(drift, "nby", "t101-nby")
    assert departed.departure_state == station.DepartureState.DEPARTED
    assert departed.allowed_actions == []
    assert refused(drift, "nby", Action.TRAIN_POSITION_SET, call="t101-nby", value=False) == (
        Reason.TRAIN_ALREADY_DEPARTED
    )


def test_a_train_that_ends_here_offers_put_away_and_nothing_once_it_is(drift: Drift) -> None:
    send(drift, "nby", Action.TRAIN_ARRIVED, call="t102-nby")
    assert Action.TRAIN_SET_ASIDE in call_here(drift, "nby", "t102-nby").allowed_actions
    assert refused(drift, "nby", Action.TRAIN_POSITION_SET, call="t102-nby", value=True) == (
        Reason.INVALID_DEPARTURE
    )
    send(drift, "nby", Action.TRAIN_SET_ASIDE, call="t102-nby")
    assert call_here(drift, "nby", "t102-nby").allowed_actions == []


def test_line_available_never_takes_the_channel(drift: Drift) -> None:
    """A one-sided message is not a request and is never treated as one."""
    outcome = send(
        drift, "nby", Action.LINE_AVAILABLE_PUBLISH, call="t101-nby", section="s-nby-asn"
    )
    assert outcome.revision is not None and outcome.revision.scope == station.RevisionScope.CASE
    request(drift, "nby", "t101-nby", "s-nby-asn")


def test_line_available_is_acknowledged_never_answered(drift: Drift) -> None:
    outcome = send(
        drift, "nby", Action.LINE_AVAILABLE_PUBLISH, call="t101-nby", section="s-nby-asn"
    )
    assert outcome.revision is not None
    message = outcome.revision.key
    asen = snapshot(drift, "asn", NOW)
    assert asen.clearances == []
    assert [(m.message_id, m.from_place, m.call) for m in asen.line_messages] == [
        (message, "nby", "t101-nby")
    ]
    assert refused(drift, "nby", Action.LINE_AVAILABLE_ACKNOWLEDGE, message_id=message) == (
        Reason.NOT_RECEIVER
    )
    acknowledged = send(drift, "asn", Action.LINE_AVAILABLE_ACKNOWLEDGE, message_id=message)
    assert acknowledged.revision is not None and acknowledged.revision.value == 2
    assert snapshot(drift, "asn", NOW).line_messages == []
    assert refused(drift, "asn", Action.LINE_AVAILABLE_ACKNOWLEDGE, message_id=message) == (
        Reason.ALREADY_ACKNOWLEDGED
    )
    assert refused(drift, "asn", Action.LINE_AVAILABLE_ACKNOWLEDGE, message_id="line-x") == (
        Reason.UNKNOWN_LINE_MESSAGE
    )


def test_line_available_only_on_a_section_of_the_place(drift: Drift) -> None:
    assert refused(
        drift, "nby", Action.LINE_AVAILABLE_PUBLISH, call="t101-nby", section="s-mla-sjv"
    ) == (Reason.WRONG_PLACE)
    assert refused(drift, "nby", Action.LINE_AVAILABLE_PUBLISH, call="t101-nby", section="s-x") == (
        Reason.UNKNOWN_SECTION
    )


# --- One track, one train standing there (§8; Benny #197) -----------------------------------


@pytest.fixture
def standing(drift: Drift) -> Drift:
    """4501 is moved to Åsen and stands on track 1."""
    send(drift, "asn", Action.TRAIN_ARRIVED, call="t4501-asn")
    assert call_here(drift, "asn", "t4501-asn").track == "1"
    return drift


def test_a_track_another_train_stands_on_is_refused(standing: Drift) -> None:
    assert refused(standing, "asn", Action.TRAIN_TRACK_CHANGE, call="t101-asn", track="1") == (
        Reason.TRACK_OCCUPIED
    )
    assert call_here(standing, "asn", "t101-asn").track == "1", "the refusal moves nothing"


def test_a_train_due_later_does_not_hold_the_track(standing: Drift) -> None:
    """102 is due on track 2 later; only a train standing there now counts (#197)."""
    send(standing, "asn", Action.TRAIN_TRACK_CHANGE, call="t101-asn", track="2")


def test_moving_a_train_to_the_track_it_already_holds_is_no_collision(standing: Drift) -> None:
    send(standing, "asn", Action.TRAIN_TRACK_CHANGE, call="t4501-asn", track="1")
    send(standing, "asn", Action.TRAIN_TRACK_CHANGE, call="t4501-asn", track="3")
    assert call_here(standing, "asn", "t4501-asn").track == "3", "the train moves with it"
    send(standing, "asn", Action.TRAIN_TRACK_CHANGE, call="t101-asn", track="1")


def test_a_departed_train_releases_its_track(standing: Drift) -> None:
    clearance = request(standing, "asn", "t4501-asn", "s-asn-mla")
    send(standing, "mla", Action.CLEARANCE_RESPONSE, clearance_id=clearance, approved=True)
    send(standing, "asn", Action.TRAIN_DEPARTED, call="t4501-asn")
    send(standing, "asn", Action.TRAIN_TRACK_CHANGE, call="t101-asn", track="1")
    assert refused(standing, "asn", Action.TRAIN_TRACK_CHANGE, call="t4501-asn", track="2") == (
        Reason.TRAIN_ALREADY_DEPARTED
    )


def test_another_places_track_with_the_same_name_is_not_our_collision(standing: Drift) -> None:
    send(standing, "mla", Action.TRAIN_TRACK_CHANGE, call="t101-mla", track="1")


# --- The snapshot ---------------------------------------------------------------------------


def test_the_snapshot_names_the_place_its_sections_and_neighbours(drift: Drift) -> None:
    seen = snapshot(drift, "asn", NOW)
    assert (seen.place.place, seen.place.code, seen.place.name) == ("asn", "Ån", "Åsen")
    assert [(s.section, s.other_code, s.side, s.tracks) for s in seen.sections] == [
        ("s-nby-asn", "Nby", "left", "single"),
        ("s-asn-mla", "Mlå", "right", "double"),
    ]
    assert [n.place for n in seen.neighbours] == ["nby", "mla"]
    assert [p.place for p in seen.all_places] == ["nby", "asn", "mla", "sjv"]
    assert seen.clock.time == "06:00" and seen.clock.running is False
    # Every call at Åsen today, in timetable order, from where and to where.
    assert [(c.train_number, c.from_place, c.to_place) for c in seen.calls][:3] == [
        ("101", "nby", "mla"),
        ("102", "mla", "nby"),
        ("4501", "nby", "mla"),
    ]
    station.Snapshot.model_validate_json(seen.model_dump_json())


def test_a_halt_has_no_snapshot(drift: Drift) -> None:
    with pytest.raises(KeyError):
        snapshot(drift, "lvh", NOW)


def test_the_place_revision_moves_only_for_its_own_traffic(drift: Drift) -> None:
    before = {p: snapshot(drift, p, NOW).place_revision for p in ("nby", "asn", "mla", "sjv")}
    request(drift, "nby", "t101-nby", "s-nby-asn")
    after = {p: snapshot(drift, p, NOW).place_revision for p in ("nby", "asn", "mla", "sjv")}
    assert after["nby"] > before["nby"] and after["asn"] > before["asn"]
    assert (after["mla"], after["sjv"]) == (before["mla"], before["sjv"])
