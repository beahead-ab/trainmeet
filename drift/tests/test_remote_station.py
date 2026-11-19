"""Fjärrstyrning in the hub, the station automats and the local area (#36 del b, FR20–FR25,
FR37, FR39, FR42, FR44): automat.set from afar, local_release.request, .response and .end, and
how the station's route.state shows what was decided. Pretend clients speak the station protocol
to the store, as in del a's tests (drift/tests/test_remote.py), whose fixtures this uses: Åsen's
outside has the automats A3 and L01."""

from __future__ import annotations

from typing import Any

from contracts import station
from contracts.reasons import Reason
from drift.tests.test_remote import Meet, Pretend, hand_over, lines, meet

Action = station.Action
__all__ = ["lines", "meet"]


def remote_controlled(lines: Any) -> tuple[Pretend, Pretend]:
    _, asen, _, remote = lines
    hand_over(asen, remote)
    return asen, remote


def test_automat_set_comes_from_afar_and_the_station_shows_it(meet: Meet, lines: Any) -> None:
    """FR25: the one who controls the station switches its automat from the remote picture;
    Hubben keeps the decision until the station's route.state shows it, and Logg has one line
    for it, by the controller (FR37)."""
    asen, remote = remote_controlled(lines)
    assert asen.refused(Action.AUTOMAT_SET, "asn", code="A3", on=True) == Reason.NOT_CONTROLLER
    assert remote.refused(Action.AUTOMAT_SET, "asn", code="A9", on=True) == Reason.UNKNOWN_AUTOMAT
    before = len(meet.drift().history)
    assert remote.send(Action.AUTOMAT_SET, "asn", code="A3", on=True).status == "accepted"
    seen = asen.snapshot("asn").remote
    assert seen is not None
    assert [(a.code, a.on) for a in seen.automats_asked] == [("A3", True)]
    state = {"automats": [{"code": "A3", "by": "remote"}]}
    assert asen.send(Action.ROUTE_STATE, "asn", **state).status == "accepted"
    seen = asen.snapshot("asn").remote
    assert seen is not None and seen.automats_asked == []
    switched = [e for e in meet.drift().history[before:] if e.kind.value == "automat.set"]
    assert len(switched) == 1, "the decision is the line in Logg; the station's state adds none"
    assert switched[0].data["by"] == "remote" and switched[0].data["asked"] is True
    # The station switches it off on the spot when it is manned again: that is its own line.
    assert asen.send(Action.PLACE_TAKE_BACK, "asn").status == "accepted"
    assert asen.send(Action.ROUTE_STATE, "asn").status == "accepted"
    kinds = [e.kind.value for e in meet.drift().history[before:]]
    assert kinds.count("automat.set") == 2


def test_a_manned_station_switches_its_own_automats(meet: Meet, lines: Any) -> None:
    """On the spot the station's own panel switches them, and nothing goes through Hubben but
    the route.state; automat.set and local_release.request are for a remote-controlled station."""
    _, asen, _, _ = lines
    assert asen.refused(Action.AUTOMAT_SET, "asn", code="A3", on=True) == Reason.NOT_CONTROLLER
    assert asen.refused(Action.LOCAL_RELEASE_REQUEST, "asn", code="L01") == Reason.PLACE_MANNED
    state = {"automats": [{"code": "A3", "by": "station"}]}
    before = len(meet.drift().history)
    assert asen.send(Action.ROUTE_STATE, "asn", **state).status == "accepted"
    [switched] = [e for e in meet.drift().history[before:] if e.kind.value == "automat.set"]
    assert switched.data == {"code": "A3", "on": True, "by": "station"}


def test_the_local_area_is_asked_for_given_and_taken_back(meet: Meet, lines: Any) -> None:
    """FR20, FR22, FR23: the people on site ask, the controller gives, the station switches it
    in and says so in route.state, and the controller takes it back; one line each in Logg."""
    asen, remote = remote_controlled(lines)
    assert remote.refused(Action.LOCAL_RELEASE_REQUEST, "asn", code="L01") == Reason.NOT_STATION
    assert asen.refused(Action.LOCAL_RELEASE_REQUEST, "asn", code="A3") == Reason.UNKNOWN_AUTOMAT
    assert asen.refused(Action.LOCAL_RELEASE_END, "asn", code="L01") == (
        Reason.LOCAL_AREA_NOT_GIVEN
    )
    before = len(meet.drift().history)
    reply = asen.send(Action.LOCAL_RELEASE_REQUEST, "asn", code="L01", all_day=True)
    assert reply.status == "accepted"
    [asked] = remote.snapshot("asn").remote.local_requests
    assert (asked.code, asked.all_day) == ("L01", True)
    assert asen.refused(Action.LOCAL_RELEASE_RESPONSE, "asn", code="L01", give=True) == (
        Reason.NOT_CONTROLLER
    )
    assert remote.send(Action.LOCAL_RELEASE_RESPONSE, "asn", code="L01", give=True).status == (
        "accepted"
    )
    seen = asen.snapshot("asn").remote
    assert seen is not None and seen.local_requests == []
    assert [(a.code, a.on) for a in seen.automats_asked] == [("L01", True)]
    given = {"local_areas": [{"code": "L01", "tracks": ["2"]}]}
    assert asen.send(Action.ROUTE_STATE, "asn", **given).status == "accepted"
    assert asen.snapshot("asn").remote.automats_asked == []
    # Taken back by the controller, after a question in its picture: switched out when empty.
    assert remote.send(Action.LOCAL_RELEASE_END, "asn", code="L01").status == "accepted"
    assert [(a.code, a.on) for a in asen.snapshot("asn").remote.automats_asked] == [("L01", False)]
    assert asen.send(Action.ROUTE_STATE, "asn").status == "accepted"
    kinds = [e.kind.value for e in meet.drift().history[before:]]
    assert [k for k in kinds if k.startswith("local_release")] == [
        "local_release.requested",
        "local_release.answered",
        "local_release.ended",
    ]


def test_a_refused_local_area_is_logged_and_nothing_is_kept(meet: Meet, lines: Any) -> None:
    asen, remote = remote_controlled(lines)
    assert asen.send(Action.LOCAL_RELEASE_REQUEST, "asn", code="L01").status == "accepted"
    assert remote.send(Action.LOCAL_RELEASE_RESPONSE, "asn", code="L01", give=False).status == (
        "accepted"
    )
    seen = asen.snapshot("asn").remote
    assert seen is not None and seen.local_requests == [] and seen.automats_asked == []
    last = meet.drift().history[-1]
    assert (last.kind.value, last.data["given"]) == ("local_release.answered", False)


def test_taking_the_station_back_drops_what_waited(meet: Meet, lines: Any) -> None:
    """A decision the station has not shown yet, or a request not answered, goes when the
    station is manned again: the station decides on the spot then (FR7)."""
    asen, remote = remote_controlled(lines)
    assert remote.send(Action.AUTOMAT_SET, "asn", code="A3", on=True).status == "accepted"
    assert asen.send(Action.LOCAL_RELEASE_REQUEST, "asn", code="L01").status == "accepted"
    assert asen.send(Action.PLACE_TAKE_BACK, "asn").status == "accepted"
    seen = asen.snapshot("asn").remote
    assert seen is not None and seen.automats_asked == [] and seen.local_requests == []


def test_a_refusal_carries_the_interlockings_own_words(meet: Meet, lines: Any) -> None:
    """route.response with route_refused and the interlocking's text; the one who asked sees
    both (#36 del b)."""
    asen, remote = remote_controlled(lines)
    assert remote.send(Action.ROUTE_REQUEST, "asn", request_id="r1", route="A-1").status == (
        "accepted"
    )
    said = "Signalen A är i signalstopp (Signalstopp väster)."
    reply = asen.send(
        Action.ROUTE_RESPONSE,
        "asn",
        request_id="r1",
        locked=False,
        reason="route_refused",
        message=said,
    )
    assert reply.status == "accepted"
    [route] = remote.snapshot("asn").remote.routes
    assert (route.state, route.reason, route.message) == ("refused", "route_refused", said)
