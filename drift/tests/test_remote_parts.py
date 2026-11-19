"""Fjärrstyrning in the hub, the parts of a remote-controlled station (#36 del d, DRIFT-40, FR37,
FR50, FR51, TKL100): the station forwards its parts' waiting requests and its list Klara att skicka
in route.state; whoever controls it answers with part.answer and changes the list with ready.move
and ready.sent. Hubben checks who sends and what the station's route.state says, never decides,
and keeps the answer until the station's route.state says it is done. Pretend clients speak the
station protocol to the store, with del a's fixtures (drift/tests/test_remote.py)."""

from __future__ import annotations

from typing import Any

import pytest

from contracts import drift as events
from contracts import station
from contracts.reasons import Reason
from drift import store as stores
from drift.tests.test_remote import Meet, Pretend, hand_over, lines, meet

Action = station.Action
__all__ = ["lines", "meet"]

REQUEST = {
    "request_id": "7",
    "part": "bangarden",
    "part_name": "Bangården",
    "said": "51 → V",
    "text": "Bangården begär 51 → V.",
}
READY = [
    {"train_number": "9103", "part": "bangarden", "part_name": "Bangården", "departure": "06:40"},
    {"train_number": "9105", "part": "bangarden", "part_name": "Bangården", "departure": "07:10"},
]


def forwarded(lines: Any) -> tuple[Pretend, Pretend]:
    """Åsen handed to the remote interlocking, with a part's request and two trains ready."""
    _, asen, _, remote = lines
    hand_over(asen, remote)
    state = {"part_requests": [REQUEST], "ready_to_send": READY}
    assert asen.send(Action.ROUTE_STATE, "asn", **state).status == "accepted"
    return asen, remote


def test_the_parts_requests_reach_the_controller_through_route_state(
    meet: Meet, lines: Any
) -> None:
    """FR50, FR51: the station forwards its parts' requests and the list in route.state, which
    whoever controls it reads in its snapshot and in the overview; Logg has the request, by the
    station (FR37)."""
    before = len(meet.drift().history)
    asen, remote = forwarded(lines)
    seen = remote.snapshot("asn").remote
    assert seen.route_state is not None
    assert [r.said for r in seen.route_state.part_requests] == ["51 → V"]
    assert [r.train_number for r in seen.route_state.ready_to_send] == ["9103", "9105"]
    here = next(p for p in meet.store.overview(remote.key, []).places if p.place.place == "asn")
    assert here.route_state is not None and here.route_state.part_requests[0].part == "bangarden"
    asked = next(
        e for e in meet.drift().history[before:] if e.kind == events.EventKind.PART_REQUESTED
    )
    assert asked.data["text"] == "Bangården begär 51 → V." and asked.actor.id == asen.client_id


def test_part_answer_approves_and_the_station_does_it(meet: Meet, lines: Any) -> None:
    """part.answer: Hubben keeps the controller's Godkänn, with who answered, until the station's
    route.state says it is done: the request no longer waits."""
    asen, remote = forwarded(lines)
    reply = remote.send(Action.PART_ANSWER, "asn", part="bangarden", request_id="7", approve=True)
    assert reply.status == "accepted", reply.message
    answered = meet.drift().history[-1]
    assert answered.kind == events.EventKind.PART_ANSWERED
    assert answered.actor.id == remote.client_id, "Logg says who answered (FR37)"
    [answer] = asen.snapshot("asn").remote.part_answers
    assert (answer.request_id, answer.approve, answer.by) == ("7", True, "Fjärr Västra")
    assert (
        remote.refused(Action.PART_ANSWER, "asn", part="bangarden", request_id="7", approve=False)
        == Reason.PART_REQUEST_NOT_PENDING
    ), "one answer at a time"
    assert asen.send(Action.ROUTE_STATE, "asn", ready_to_send=READY).status == "accepted"
    assert asen.snapshot("asn").remote.part_answers == []


def test_part_answer_refuses_with_a_reason(meet: Meet, lines: Any) -> None:
    """Neka, with the controller's reason for the part to read. An approval the station could not
    lay yet is done all the same: the station lists it in answered, with its note."""
    asen, remote = forwarded(lines)
    reply = remote.send(
        Action.PART_ANSWER,
        "asn",
        part="bangarden",
        request_id="7",
        approve=False,
        reason="Tåg 102 kommer.",
    )
    assert reply.status == "accepted", reply.message
    assert meet.drift().history[-1].data["reason"] == "Tåg 102 kommer."
    [answer] = asen.snapshot("asn").remote.part_answers
    noted = {**REQUEST, "note": "Vägen kan inte läggas nu."}
    state = {"part_requests": [noted], "ready_to_send": READY, "answered": [answer.seq]}
    assert asen.send(Action.ROUTE_STATE, "asn", **state).status == "accepted"
    assert asen.snapshot("asn").remote.part_answers == []
    seen = remote.snapshot("asn").remote.route_state
    assert seen is not None and seen.part_requests[0].note == "Vägen kan inte läggas nu."


def test_only_the_controller_answers_the_parts(meet: Meet, lines: Any) -> None:
    """Refused from anyone who does not control the station, the station's own TKL included,
    and for a request the station does not list as waiting (FR50)."""
    norrby, asen, mellana, remote = lines
    payload = {"part": "bangarden", "request_id": "7", "approve": True}
    assert remote.refused(Action.PART_ANSWER, "asn", **payload) == Reason.NOT_CONTROLLER
    hand_over(asen, remote)
    assert remote.refused(Action.PART_ANSWER, "asn", **payload) == Reason.PART_REQUEST_NOT_PENDING
    state = {"part_requests": [REQUEST], "ready_to_send": READY}
    assert asen.send(Action.ROUTE_STATE, "asn", **state).status == "accepted"
    assert asen.refused(Action.PART_ANSWER, "asn", **payload) == Reason.NOT_CONTROLLER
    with pytest.raises(stores.NotApproved):
        mellana.send(Action.PART_ANSWER, "asn", **payload)
    assert asen.refused(Action.READY_SENT, "asn", train_number="9103") == Reason.NOT_CONTROLLER
    other = {**payload, "part": "annan"}
    assert remote.refused(Action.PART_ANSWER, "asn", **other) == Reason.PART_REQUEST_NOT_PENDING
    del norrby


def test_ready_to_send_moved_and_sent(meet: Meet, lines: Any) -> None:
    """FR51: the controller moves a train in the list and marks one Skickat; Hubben keeps both
    until the station shows them, and refuses a train the list does not have."""
    asen, remote = forwarded(lines)
    assert (
        remote.refused(Action.READY_MOVE, "asn", train_number="9999", to=0)
        == Reason.NOT_READY_TO_SEND
    )
    moved = remote.send(Action.READY_MOVE, "asn", train_number="9105", to=0)
    assert moved.status == "accepted", moved.message
    sent = remote.send(Action.READY_SENT, "asn", train_number="9103")
    assert sent.status == "accepted", sent.message
    kinds = [e.kind for e in meet.drift().history[-2:]]
    assert kinds == [events.EventKind.READY_MOVED, events.EventKind.READY_SENT]
    asks = asen.snapshot("asn").remote.ready_asks
    assert [(a.train_number, a.to) for a in asks] == [("9105", 0), ("9103", None)]
    # The station moved 9105 first and sent 9103: it says the move is done, and the sent train
    # is gone from the list.
    state = {"ready_to_send": [{**READY[1], "moved": True}], "answered": [asks[0].seq]}
    assert asen.send(Action.ROUTE_STATE, "asn", **state).status == "accepted"
    assert asen.snapshot("asn").remote.ready_asks == []


def test_taking_the_station_back_drops_what_was_not_done(meet: Meet, lines: Any) -> None:
    """The station is manned again: the clearer answers in its own box, and nothing kept for the
    station from afar stays (FR7)."""
    asen, remote = forwarded(lines)
    remote.send(Action.PART_ANSWER, "asn", part="bangarden", request_id="7", approve=True)
    remote.send(Action.READY_SENT, "asn", train_number="9103")
    assert asen.send(Action.PLACE_TAKE_BACK, "asn").status == "accepted"
    seen = asen.snapshot("asn").remote
    assert seen.part_answers == [] and seen.ready_asks == []
