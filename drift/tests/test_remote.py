"""Fjärrstyrning in the hub (#36 del a, TKL46–TKL48, TKL89, FR1–FR51): handing a station over,
the routes asked for from afar and the station's state, contact, and clearance across stations
that are remote-controlled. There is no TKL side yet, so pretend clients speak the station
protocol to the store, as TKL and the remote interlocking will.

Provbanan stands in for a line: Norrby – Åsen – Mellanå – Sjövik. Åsen's outside is pinned in
the version with a remote catalogue; Mellanå's TKL brings its own; Norrby's is at level 0 and has
none. The plan's remote area holds Åsen, Mellanå and Sjövik.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from contracts import drift as events
from contracts import station
from contracts.meet import ClearanceMode, MeetPackage
from contracts.reasons import Reason
from contracts.station_outside import StationOutside
from drift import store as stores
from drift.automatik import Automatik
from drift.engine import Drift, Refused

START = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)
Action = station.Action
Kind = events.EventKind

CATALOGUE = [
    {"id": "A-1", "start": "A", "end": "1", "exit": "v", "track": "1", "direction": "in"},
    {"id": "A-2", "start": "A", "end": "2", "exit": "v", "track": "2", "direction": "in"},
    {"id": "N1-B", "start": "N1", "end": "B", "exit": "o", "track": "1", "direction": "out"},
]
OVERVIEW = {
    "columns": 10,
    "rows": 2,
    "tracks": [
        {"id": "t1", "row": 0, "start": 0, "end": 10, "track": "1", "platform": True},
        {"id": "t2", "row": 1, "start": 2, "end": 8, "track": "2"},
    ],
    "links": [{"id": "l1", "from_row": 0, "from_column": 1, "to_row": 1, "to_column": 2}],
    "signals": [{"name": "A", "row": 0, "column": 0, "towards": "right"}],
    "exits": [{"exit": "v", "row": 0, "column": 0}, {"exit": "o", "row": 0, "column": 10}],
    "routes": {"A-1": ["t1"], "A-2": ["t1", "l1", "t2"]},
}


def package() -> MeetPackage:
    """Provbanan with Åsen's catalogue pinned in the version, and the plan's remote area."""
    data = json.loads(files("contracts").joinpath("examples/provbanan.meet.json").read_text())
    asen = next(p for p in data["places"] if p["id"] == "asn")
    asen["station"]["outside"].update(
        remote_routes=CATALOGUE,
        automats=[
            {"code": "A3", "kind": "a3", "default": True},
            {"code": "L01", "kind": "local_release"},
        ],
        overview=OVERVIEW,
    )
    data["remote_areas"] = [{"id": "vast", "name": "Västra", "places": ["asn", "mla", "sjv"]}]
    return MeetPackage.model_validate(data)


def outside(station_id: str, name: str, *, catalogue: bool = True) -> dict[str, Any]:
    return {
        "station_id": station_id,
        "name": name,
        "tracks": [{"id": "1", "label": "Spår 1"}, {"id": "2", "label": "Spår 2"}],
        "exits": [{"id": "v", "side": "left"}, {"id": "o", "side": "right"}],
        "remote_routes": CATALOGUE[:2] if catalogue else [],
    }


class Pretend:
    """A client of the station protocol: a TKL, or the remote interlocking."""

    def __init__(self, meet: Meet, client_id: str) -> None:
        self.meet = meet
        self.client_id = client_id
        self.key = ""

    def send(self, action: station.Action, place: str, **payload: Any) -> station.Reply:
        return self.meet.store.station_command(
            self.key,
            station.Command(
                message_id=uuid4().hex,
                client_id=self.client_id,
                place=place,
                context=self.meet.drift().context,
                action=action,
                payload=payload,
            ),
        )

    def refused(self, action: station.Action, place: str, **payload: Any) -> Reason:
        before = len(self.meet.drift().history)
        reply = self.send(action, place, **payload)
        assert reply.status == station.ReplyStatus.REJECTED, reply.message
        assert reply.reason is not None
        assert len(self.meet.drift().history) == before, "a no changes nothing"
        return reply.reason

    def snapshot(self, place: str) -> station.Snapshot:
        return self.meet.store.place_snapshot(self.key, place)


class Meet:
    """A run of Provbanan with the clocks in the test's hand: the wall clock for Drift's events
    and time limits, and the automation's clock for contact."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.wall = START
        self.mono = 0.0
        monkeypatch.setattr(stores, "now_utc", lambda: self.wall)
        self.store = stores.PreviewStore(tmp_path / "run.sqlite3", package(), automation=False)
        self.run = self.store.start()
        self.store._automatik[self.run] = Automatik(now=lambda: self.mono)
        self.code = self.store.join_code(self.run)

    def later(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.mono += seconds

    def drift(self) -> Drift:
        return self.store.state(self.run)

    def connect(
        self, kind: str, name: str, places: list[str], *, approve: bool = True, **asked: Any
    ) -> Pretend:
        reply = self.store.connect(
            station.ConnectRequest.model_validate(
                {
                    "kind": kind,
                    "name": name,
                    "software": "Prov 1",
                    "wants": places,
                    "code": self.code,
                    **asked,
                }
            )
        )
        client = Pretend(self, reply.client_id)
        if approve:
            self.store.approve(self.run, events.Approve(client_id=reply.client_id, places=places))
            key = self.store.connection(reply.client_id).key
            assert key is not None
            client.key = key
        return client

    def kinds(self, after: int = 0) -> list[str]:
        return [event.kind.value for event in self.drift().history[after:]]

    def mode(self, place: str) -> events.PlaceMode:
        status = self.store.automation(self.run)
        return next(p.mode for p in status.places if p.place == place)


@pytest.fixture
def meet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Meet]:
    yield Meet(tmp_path, monkeypatch)


@pytest.fixture
def lines(meet: Meet) -> tuple[Pretend, Pretend, Pretend, Pretend]:
    """Norrby's TKL at level 0, Åsen's and Mellanå's at level 1, and the remote interlocking
    approved for its area. Each station's TKL has read its place, so it works it."""
    norrby = meet.connect(
        "tkl", "TKL Norrby", ["nby"], level=0, outside=outside("nby", "Norrby", catalogue=False)
    )
    asen = meet.connect("tkl", "TKL Åsen", ["asn"], station_id="asen", level=1)
    mellana = meet.connect(
        "tkl", "TKL Mellanå", ["mla"], level=1, outside=outside("mla", "Mellanå")
    )
    remote = meet.connect("remote", "Fjärr Västra", ["asn", "mla", "sjv"])
    for tkl, place in ((norrby, "nby"), (asen, "asn"), (mellana, "mla")):
        tkl.snapshot(place)
    return norrby, asen, mellana, remote


def hand_over(asen: Pretend, to: Pretend) -> None:
    assert asen.send(Action.PLACE_OFFER, "asn", to=to.client_id).status == "accepted"
    assert to.send(Action.PLACE_OFFER_ANSWER, "asn", accept=True).status == "accepted"


# --- The remote interlocking and its approval (FR1, FR4, TRAFIK-34) -----------------------------


def test_a_remote_interlocking_connects_with_its_area_and_only_receives(meet: Meet) -> None:
    """It connects with no station, asks for the plan's remote area, and is approved for its
    places as an ordinary interlocking. The approval gives the right to receive, nothing more:
    it reads the places, works none of them, and asks for no route until a station is handed
    to it (FR4)."""
    with pytest.raises(ValueError, match="ingen egen station"):
        station.ConnectRequest(
            kind=station.ClientKind.REMOTE, name="F", software="S", station_id="asen"
        )
    remote = meet.connect("remote", "Fjärr Västra", [], approve=False, remote_area="vast")
    [listed] = [c for c in meet.store.clients(meet.run) if c["client_id"] == remote.client_id]
    assert (listed["kind"], listed["status"]) == ("remote", "waiting")
    assert [w["place"] for w in listed["wanted"]] == ["asn", "mla", "sjv"]
    assert listed["station_id"] is None and listed["questions"] == []
    meet.store.approve(meet.run, events.Approve(client_id=remote.client_id, places=["asn", "mla"]))
    remote.key = meet.store.connection(remote.client_id).key or ""
    seen = remote.snapshot("asn")
    assert seen.remote is not None and seen.remote.controllable
    assert seen.questions == [], "Hubben asks only the station's own TKL about its exits"
    assert "asn" not in meet.drift().manned, "a remote interlocking never mans a station"
    assert meet.mode("asn") == events.PlaceMode.AUTOMATIC
    assert remote.refused(Action.ROUTE_REQUEST, "asn", request_id="r1", route="A-1") == (
        Reason.NOT_CONTROLLER
    )
    assert (
        remote.refused(
            Action.CLEARANCE_REQUEST, "asn", call="t101-asn", section="s-asn-mla", clearance_id="c1"
        )
        == Reason.NOT_APPROVED
    )
    assert remote.refused(Action.PLACE_OFFER_ANSWER, "asn", accept=True) == Reason.OFFER_NOT_PENDING


# --- Handing over and taking back (FR5–FR9) ---------------------------------------------------


def test_an_offer_taken_makes_the_station_remote_controlled(meet: Meet, lines: Any) -> None:
    _, asen, mellana, remote = lines
    seen = asen.snapshot("asn")
    assert seen.mode == station.PlaceMode.MANNED and seen.remote is not None
    receivers = {r.client_id: r for r in seen.remote.receivers}
    # The neighbour's TKL, by the place it runs, and the approved remote interlocking (FR3).
    assert (receivers[mellana.client_id].name, receivers[mellana.client_id].place) == (
        "Mellanå",
        "mla",
    )
    assert receivers[remote.client_id].name == "Fjärr Västra"
    before = len(meet.drift().history)
    assert asen.send(Action.PLACE_OFFER, "asn", to=remote.client_id).status == "accepted"
    assert meet.mode("asn") == events.PlaceMode.OFFERED
    [offer] = remote.snapshot("asn").offers
    assert (offer.place, offer.to.client_id, offer.expires_in) == ("asn", remote.client_id, 60)
    assert asen.refused(Action.PLACE_OFFER, "asn", to=mellana.client_id) == Reason.OFFER_PENDING
    with pytest.raises(stores.NotApproved):
        mellana.send(Action.PLACE_OFFER_ANSWER, "asn", accept=True)
    assert remote.send(Action.PLACE_OFFER_ANSWER, "asn", accept=True).status == "accepted"
    assert meet.mode("asn") == events.PlaceMode.REMOTE
    seen = remote.snapshot("asn")
    assert seen.controls == ["asn"] and seen.mode == station.PlaceMode.REMOTE
    assert seen.remote is not None and seen.remote.controller is not None
    assert seen.remote.controller.client_id == remote.client_id
    assert seen.remote.receivers == [], "a station is remote-controlled by one at a time"
    station_side = asen.snapshot("asn").remote
    assert station_side is not None and station_side.controller_silent == 0
    assert meet.kinds(before) == ["place.offered", "place.offer_answered"]
    [listed] = [c for c in meet.store.clients(meet.run) if c["client_id"] == remote.client_id]
    assert listed["controls"] == ["asn"]
    status = next(p for p in meet.store.automation(meet.run).places if p.place == "asn")
    assert (status.controller, status.operator, status.controllable) == (
        remote.client_id,
        asen.client_id,
        True,
    )
    # A station is manned or remote-controlled, never both (FR6): clearing is the controller's.
    assert (
        asen.refused(
            Action.CLEARANCE_REQUEST, "asn", call="t101-asn", section="s-asn-mla", clearance_id="c1"
        )
        == Reason.PLACE_REMOTE
    )
    assert asen.refused(Action.PLACE_OFFER, "asn", to=mellana.client_id) == Reason.PLACE_REMOTE


def test_an_offer_declined_leaves_the_station_manned(meet: Meet, lines: Any) -> None:
    _, asen, mellana, _ = lines
    asen.snapshot("asn")
    asen.send(Action.PLACE_OFFER, "asn", to=mellana.client_id)
    # The neighbour's TKL hears of it on its own place, and answers on the station's.
    assert [o.place for o in mellana.snapshot("mla").offers] == ["asn"]
    assert mellana.send(Action.PLACE_OFFER_ANSWER, "asn", accept=False).status == "accepted"
    assert meet.mode("asn") == events.PlaceMode.MANNED and not meet.drift().remote
    answered = meet.drift().history[-1]
    assert (answered.kind, answered.data["accepted"], answered.actor.id) == (
        Kind.PLACE_OFFER_ANSWERED,
        False,
        mellana.client_id,
    )
    assert mellana.snapshot("mla").offers == []


def test_an_offer_runs_out_after_a_minute(meet: Meet, lines: Any) -> None:
    _, asen, _, remote = lines
    asen.send(Action.PLACE_OFFER, "asn", to=remote.client_id)
    meet.later(59)
    meet.store.tick(meet.run)
    assert meet.drift().offers, "it stands for a minute, the clock running or not"
    meet.later(1)
    assert remote.refused(Action.PLACE_OFFER_ANSWER, "asn", accept=True) == Reason.OFFER_NOT_PENDING
    meet.store.tick(meet.run)
    expired = meet.drift().history[-1]
    assert (expired.kind, expired.data["expired"], expired.actor.kind) == (
        Kind.PLACE_OFFER_ANSWERED,
        True,
        events.ActorKind.SYSTEM,
    )
    assert not meet.drift().offers and not meet.drift().remote


def test_only_the_stations_own_tkl_takes_it_back(meet: Meet, lines: Any) -> None:
    """Bara stationens egen TKL kan göra stationen bemannad (FR7); grannen kan inte ta en
    station (FR8). The state the station reported stays (FR15)."""
    _, asen, mellana, remote = lines
    hand_over(asen, remote)
    asen.send(Action.ROUTE_STATE, "asn", locked=[{"route": "A-1", "by": "station"}])
    assert remote.refused(Action.PLACE_TAKE_BACK, "asn") == Reason.NOT_STATION
    with pytest.raises(stores.NotApproved):
        mellana.send(Action.PLACE_TAKE_BACK, "asn")
    assert remote.refused(Action.PLACE_OFFER, "asn", to=mellana.client_id) == Reason.NOT_STATION
    app = meet.connect("tmbox_app", "Appen Åsen", ["asn"])
    assert app.refused(Action.PLACE_TAKE_BACK, "asn") == Reason.NOT_STATION
    assert asen.send(Action.PLACE_TAKE_BACK, "asn").status == "accepted"
    back = meet.drift().history[-1]
    assert (back.kind, back.data["controller"], back.actor.id) == (
        Kind.PLACE_TAKEN_BACK,
        remote.client_id,
        asen.client_id,
    )
    assert meet.mode("asn") == events.PlaceMode.MANNED
    assert remote.snapshot("sjv").controls == []
    with pytest.raises(stores.NotApproved):
        mellana.snapshot("asn")
    route_state = asen.snapshot("asn").remote
    assert route_state is not None and route_state.route_state is not None
    assert [r.route for r in route_state.route_state.locked] == ["A-1"]


def test_trafikledningen_takes_over_and_gives_back(meet: Meet, lines: Any) -> None:
    """Trafikledningen i Drift kan alltid ta över och lämna tillbaka (FR9, TRAFIK-34)."""
    _, asen, mellana, remote = lines
    hand_over(asen, remote)
    taken = meet.store.automation_place(
        meet.run, events.AutomationPlace(place="asn", action="leave")
    )
    status = next(p for p in taken.places if p.place == "asn")
    assert (status.mode, status.left_by, status.controller, status.back_to) == (
        events.PlaceMode.AUTOMATIC,
        events.LeftBy.DISPATCHER,
        None,
        remote.client_id,
    )
    assert (
        remote.refused(Action.ROUTE_REQUEST, "asn", request_id="r1", route="A-1")
        == Reason.NOT_CONTROLLER
    )
    given = meet.store.automation_place(
        meet.run, events.AutomationPlace(place="asn", action="remote", client_id=remote.client_id)
    )
    status = next(p for p in given.places if p.place == "asn")
    assert (status.mode, status.controller) == (events.PlaceMode.REMOTE, remote.client_id)
    given_event = meet.drift().history[-1]
    assert (given_event.kind, given_event.actor.kind) == (
        Kind.PLACE_REMOTE,
        events.ActorKind.DISPATCHER,
    )
    # Only to someone who may receive it: not to a stranger, not a station without catalogue.
    with pytest.raises(Refused) as stranger:
        meet.store.automation_place(
            meet.run, events.AutomationPlace(place="asn", action="remote", client_id="tkl-okand")
        )
    assert stranger.value.reason == Reason.UNKNOWN_RECEIVER
    with pytest.raises(Refused) as level_zero:
        meet.store.automation_place(
            meet.run,
            events.AutomationPlace(place="nby", action="remote", client_id=remote.client_id),
        )
    assert level_zero.value.reason == Reason.NO_CATALOG
    # Given back to the station's own TKL, in contact there.
    meet.store.automation_place(
        meet.run, events.AutomationPlace(place="asn", action="take_back", client_id=asen.client_id)
    )
    assert meet.mode("asn") == events.PlaceMode.MANNED and "asn" not in meet.drift().remote
    del mellana


def test_a_level_0_station_cannot_be_remote_controlled(meet: Meet, lines: Any) -> None:
    """En station på nivå 0 har inget ställverk som låser vägar, och därför ingen katalog
    (FR16), and is shown as manned (FR38)."""
    norrby, asen, mellana, remote = lines
    assert norrby.refused(Action.PLACE_OFFER, "nby", to=asen.client_id) == Reason.NO_CATALOG
    seen = norrby.snapshot("nby").remote
    assert seen is not None and not seen.controllable and seen.receivers == []
    # A TKL at level 0 that brings a catalogue all the same is still not offered.
    low = meet.connect("tkl", "TKL Sjövik", ["sjv"], level=0, outside=outside("sjv", "Sjövik"))
    low.snapshot("sjv")
    assert low.refused(Action.PLACE_OFFER, "sjv", to=remote.client_id) == Reason.NO_CATALOG
    # Nor to someone who may not receive it: the area must hang together (FR2).
    assert asen.refused(Action.PLACE_OFFER, "asn", to=asen.client_id) == Reason.UNKNOWN_RECEIVER
    overview = meet.store.overview(remote.key, ["nby", "asn"])
    norrby_seen = next(p for p in overview.places if p.place.place == "nby")
    assert (norrby_seen.controllable, norrby_seen.mode) == (False, station.PlaceMode.MANNED)
    del mellana


def test_the_area_hangs_together_along_the_line(meet: Meet, lines: Any) -> None:
    """A station may be handed to a neighbour, to whoever already controls a neighbour, or to
    an approved remote interlocking, so long as what it controls hangs together (FR2, FR3)."""
    _, asen, mellana, remote = lines
    sjovik = meet.connect("tkl", "TKL Sjövik", ["sjv"], level=1, outside=outside("sjv", "Sjövik"))
    sjovik.snapshot("sjv")
    sjovik.send(Action.PLACE_OFFER, "sjv", to=remote.client_id)
    remote.send(Action.PLACE_OFFER_ANSWER, "sjv", accept=True)
    # Sjövik is the remote interlocking's; Åsen is not next to it, so it is not offered there.
    receivers = {
        r.client_id for r in (asen.snapshot("asn").remote or station.RemoteHere()).receivers
    }
    assert remote.client_id not in receivers and mellana.client_id in receivers
    # Mellanå's TKL takes Åsen; then Mellanå is handed on, and Åsen hangs on to it.
    hand_over(asen, mellana)
    assert mellana.snapshot("mla").controls == ["asn"]


# --- The routes asked for from afar (FR11–FR15) --------------------------------------------------


def test_a_route_not_in_the_catalogue_is_refused_at_once(meet: Meet, lines: Any) -> None:
    _, asen, mellana, remote = lines
    hand_over(asen, remote)
    assert (
        remote.refused(Action.ROUTE_REQUEST, "asn", request_id="r1", route="B-9")
        == Reason.NOT_IN_CATALOG
    )
    # Neither the station nor someone else may ask; a manned station lays its own routes.
    with pytest.raises(stores.NotApproved):
        mellana.send(Action.ROUTE_REQUEST, "asn", request_id="r2", route="A-1")
    assert (
        asen.refused(Action.ROUTE_REQUEST, "asn", request_id="r3", route="A-1")
        == Reason.NOT_CONTROLLER
    )
    assert (
        mellana.refused(Action.ROUTE_REQUEST, "mla", request_id="r4", route="A-1")
        == Reason.NOT_CONTROLLER
    )
    seen = asen.snapshot("asn").remote
    assert seen is not None and seen.routes == []


def test_a_route_is_passed_to_the_station_and_answered_locked(meet: Meet, lines: Any) -> None:
    _, asen, _, remote = lines
    hand_over(asen, remote)
    before = len(meet.drift().history)
    reply = remote.send(Action.ROUTE_REQUEST, "asn", request_id="r1", route="A-1", call="t102-asn")
    assert reply.status == "accepted"
    assert (
        remote.refused(Action.ROUTE_REQUEST, "asn", request_id="r2", route="A-1")
        == Reason.ROUTE_ALREADY_REQUESTED
    )
    seen = asen.snapshot("asn")
    assert seen.remote is not None
    [asked] = seen.remote.routes
    assert (asked.route, asked.state, asked.train_number, asked.by, asked.answer_in) == (
        "A-1",
        station.RemoteRouteState.REQUESTED,
        "102",
        remote.client_id,
        10,
    )
    # The remote picture draws only what the station reports (FR13): nothing yet.
    assert seen.remote.route_state is None
    assert (
        asen.send(Action.ROUTE_RESPONSE, "asn", request_id="r1", locked=True).status == "accepted"
    )
    [answered] = (remote.snapshot("asn").remote or station.RemoteHere()).routes
    assert answered.state == station.RemoteRouteState.LOCKED
    assert (
        asen.refused(Action.ROUTE_RESPONSE, "asn", request_id="r1", locked=True)
        == Reason.ROUTE_NOT_PENDING
    )
    requested, response = meet.drift().history[before:]
    assert (requested.kind, requested.actor.id, requested.place, requested.call) == (
        Kind.ROUTE_REQUESTED,
        remote.client_id,
        "asn",
        "t102-asn",
    )
    assert (response.kind, response.actor.id, response.data["locked"]) == (
        Kind.ROUTE_ANSWERED,
        asen.client_id,
        True,
    )
    # Taken away: the station's interlocking releases it when it may, and says so.
    assert remote.send(Action.ROUTE_CANCEL, "asn", request_id="r1").status == "accepted"
    assert remote.refused(Action.ROUTE_CANCEL, "asn", request_id="r1") == Reason.ROUTE_NOT_PENDING
    asen.send(
        Action.ROUTE_STATE, "asn", locked=[{"route": "A-1", "by": "remote", "request_id": "r1"}]
    )
    asen.send(Action.ROUTE_STATE, "asn", locked=[])
    assert meet.kinds(before + 2) == [
        "route.cancelled",
        "route.state",
        "route.state",
        "route.released",
    ]
    [released] = (remote.snapshot("asn").remote or station.RemoteHere()).routes
    assert released.state == station.RemoteRouteState.RELEASED


def test_a_route_the_station_says_no_to(meet: Meet, lines: Any) -> None:
    _, asen, _, remote = lines
    hand_over(asen, remote)
    remote.send(Action.ROUTE_REQUEST, "asn", request_id="r1", route="A-2")
    no = asen.send(
        Action.ROUTE_RESPONSE, "asn", request_id="r1", locked=False, reason="conflicting_route"
    )
    assert no.status == "accepted"
    [answered] = (remote.snapshot("asn").remote or station.RemoteHere()).routes
    assert (answered.state, answered.reason) == (
        station.RemoteRouteState.REFUSED,
        Reason.CONFLICTING_ROUTE,
    )
    # Refused, it may be asked for again.
    assert (
        remote.send(Action.ROUTE_REQUEST, "asn", request_id="r2", route="A-2").status == "accepted"
    )


def test_no_answer_in_ten_seconds_is_a_no(meet: Meet, lines: Any) -> None:
    """Svarar stationen inte inom tio sekunder blir det nej, och bilden ändras inte (FR14)."""
    _, asen, _, remote = lines
    hand_over(asen, remote)
    remote.send(Action.ROUTE_REQUEST, "asn", request_id="r1", route="A-1")
    meet.later(9)
    meet.store.tick(meet.run)
    assert meet.drift().history[-1].kind == Kind.ROUTE_REQUESTED
    meet.later(1)
    meet.store.tick(meet.run)
    timed_out = meet.drift().history[-1]
    assert (timed_out.kind, timed_out.actor.kind, timed_out.data) == (
        Kind.ROUTE_ANSWERED,
        events.ActorKind.SYSTEM,
        {"request_id": "r1", "locked": False, "reason": "station_not_answering", "timed_out": True},
    )
    seen = remote.snapshot("asn").remote
    assert seen is not None and seen.route_state is None, "the picture does not change"
    assert seen.routes[0].reason == Reason.STATION_NOT_ANSWERING
    assert (
        asen.refused(Action.ROUTE_RESPONSE, "asn", request_id="r1", locked=True)
        == Reason.ROUTE_NOT_PENDING
    )


def test_route_state_is_kept_and_passed_on(meet: Meet, lines: Any) -> None:
    """route.state, whole each time: the locked routes and who, the automats on, the local
    areas and at level 3 the occupied tracks. Hubben keeps the latest per station and gives it
    to whoever controls the station or watches the area (FR13), and says what changed in Logg
    (FR37). DRIFT-40's fields travel with it."""
    norrby, asen, mellana, remote = lines
    hand_over(asen, remote)
    state = {
        "locked": [{"route": "A-1", "by": "automat", "automat": "A3"}],
        "automats": [{"code": "A3", "by": "remote"}],
        "local_areas": [{"code": "L01", "tracks": ["2"]}],
        "part_requests": [{"request_id": "d1", "part": "bangard", "text": "Väg ut mot spår 1"}],
        "ready_to_send": [{"train_number": "9103", "departure": "06:40"}],
    }
    before = len(meet.drift().history)
    assert asen.send(Action.ROUTE_STATE, "asn", **state).status == "accepted"
    assert asen.send(Action.ROUTE_STATE, "asn", **state).status == "accepted"
    assert meet.kinds(before) == [
        "route.state",
        "automat.set",
        "local_release.answered",
        "part.requested",
    ], "the same state again changes nothing; a part's request forwarded is in Logg (#36 del d)"
    assert asen.refused(Action.ROUTE_STATE, "asn", occupied=["1"]) == Reason.NOT_LEVEL_3
    for reader in (remote, asen):
        seen = reader.snapshot("asn").remote
        assert seen is not None and seen.route_state == station.RouteState.model_validate(state)
    overview = meet.store.overview(remote.key, [])
    assert [p.place.place for p in overview.places] == ["nby", "asn", "mla", "sjv"]
    here = next(p for p in overview.places if p.place.place == "asn")
    assert here.route_state is not None and here.route_state.automats[0].code == "A3"
    assert here.outside is not None and [r.id for r in here.outside.remote_routes] == [
        "A-1",
        "A-2",
        "N1-B",
    ]
    assert here.controller is not None and here.controller.client_id == remote.client_id
    assert here.mode == station.PlaceMode.REMOTE and here.level == 1
    # A neighbour's TKL watches its neighbours too, but no further.
    assert [p.place.place for p in meet.store.overview(norrby.key, []).places] == ["nby", "asn"]
    with pytest.raises(stores.NotApproved):
        meet.store.overview(norrby.key, ["sjv"])
    # The automat off and the area ended, and a route laid by the automat released.
    asen.send(Action.ROUTE_STATE, "asn")
    assert meet.kinds(before + 4) == [
        "route.state",
        "route.released",
        "automat.set",
        "local_release.ended",
    ]
    off = meet.drift().history[-2]
    assert (off.data, off.actor.id) == ({"code": "A3", "on": False}, asen.client_id)
    del mellana


# --- Contact (FR28–FR30) --------------------------------------------------------------------------


def test_after_45_seconds_of_silence_no_new_route_goes(meet: Meet, lines: Any) -> None:
    _, asen, _, remote = lines
    hand_over(asen, remote)
    meet.later(46)
    asen.snapshot("asn")  # The station is heard; the one who controls it is not.
    assert meet.mode("asn") == events.PlaceMode.NO_CONTACT
    station_side = asen.snapshot("asn").remote
    assert station_side is not None and station_side.controller_silent == 46, (
        "what the station reads, to switch in its default automat after 90 seconds (FR29)"
    )
    assert (
        remote.refused(Action.ROUTE_REQUEST, "asn", request_id="r1", route="A-1")
        == Reason.NO_CONTACT
    )
    # Heard again, it reads the picture and asks anew.
    assert meet.mode("asn") == events.PlaceMode.REMOTE
    assert (
        remote.send(Action.ROUTE_REQUEST, "asn", request_id="r2", route="A-1").status == "accepted"
    )
    # The station not heard: it cannot answer, so the hub says no at once.
    meet.later(46)
    remote.snapshot("asn")
    assert (
        remote.refused(Action.ROUTE_REQUEST, "asn", request_id="r3", route="A-2")
        == Reason.STATION_NOT_ANSWERING
    )


def test_kontakt_saknas_goes_to_the_automation_and_the_station_takes_back(
    meet: Meet, lines: Any
) -> None:
    """Efter träffens tid för Kontakt saknas tar Drifts automatik över klareringen, och
    stationens egen TKL kan ta tillbaka direkt (FR30)."""
    _, asen, _, remote = lines
    hand_over(asen, remote)
    meet.store.clock(meet.run, events.ClockControl(action=events.ClockAction.START))
    meet.store.set_automation(meet.run, events.AutomationSettings(lost_contact_minutes=2))
    meet.later(100)
    asen.snapshot("asn")
    meet.store.tick(meet.run)
    status = next(p for p in meet.store.automation(meet.run).places if p.place == "asn")
    assert (status.mode, status.takes_over_in) == (events.PlaceMode.NO_CONTACT, 20)
    meet.later(20)
    asen.snapshot("asn")
    meet.store.tick(meet.run)
    left = next(e for e in meet.drift().history if e.kind == Kind.PLACE_LEFT and e.place == "asn")
    assert (left.data["by"], left.data["controller"], left.actor.kind) == (
        "lost_contact",
        remote.client_id,
        events.ActorKind.AUTOMATION,
    )
    assert meet.mode("asn") == events.PlaceMode.AUTOMATIC and not meet.drift().remote
    assert asen.send(Action.PLACE_TAKE_BACK, "asn").status == "accepted"
    assert meet.mode("asn") == events.PlaceMode.MANNED


# --- Clearance (FR17–FR19) ------------------------------------------------------------------------


def test_the_controller_clears_for_the_whole_station(meet: Meet, lines: Any) -> None:
    """När en station fjärrstyrs klarerar den som fjärrstyr för hela stationen (FR17). Against
    a manned station clearance is as usual (FR19)."""
    norrby, asen, _, remote = lines
    hand_over(asen, remote)
    norrby.send(
        Action.CLEARANCE_REQUEST, "nby", call="t101-nby", section="s-nby-asn", clearance_id="c1"
    )
    [case] = meet.drift().cases.values()
    assert case.status == station.ClearanceStatus.WAITING, "Norrby is manned: as usual"
    # Each is told what it may do with the train coming in: the controller answers.
    allowed = {
        who.client_id: next(c for c in who.snapshot("asn").calls if c.call == "t101-asn")
        for who in (asen, remote)
    }
    assert Action.CLEARANCE_RESPONSE in allowed[remote.client_id].allowed_actions
    assert Action.CLEARANCE_RESPONSE not in allowed[asen.client_id].allowed_actions
    assert (
        asen.refused(Action.CLEARANCE_RESPONSE, "asn", clearance_id="c1", approved=True)
        == Reason.NOT_RECEIVER
    )
    assert (
        remote.send(Action.CLEARANCE_RESPONSE, "asn", clearance_id="c1", approved=True).status
        == "accepted"
    )
    answered = meet.drift().history[-1]
    assert (answered.kind, answered.actor.id) == (Kind.CLEARANCE_ANSWERED, remote.client_id)
    assert next(iter(meet.drift().cases.values())).status == station.ClearanceStatus.APPROVED


def test_both_ends_from_the_same_place_clear_directly(meet: Meet, lines: Any) -> None:
    """Styrs båda ändarna av en sträcka från samma ställe går sträckan i klareringsläget direkt
    (FR18): Mellanå's TKL runs Mellanå and remote-controls Åsen."""
    _, asen, mellana, _ = lines
    section = next(s for s in mellana.snapshot("mla").sections if s.section == "s-asn-mla")
    assert section.clearance_mode == ClearanceMode.REQUESTED
    hand_over(asen, mellana)
    section = next(s for s in mellana.snapshot("mla").sections if s.section == "s-asn-mla")
    assert section.clearance_mode == ClearanceMode.DIRECT
    mellana.send(
        Action.CLEARANCE_REQUEST, "asn", call="t101-asn", section="s-asn-mla", clearance_id="c1"
    )
    [case] = meet.drift().cases.values()
    assert case.status == station.ClearanceStatus.APPROVED, "Drift ger klart direkt"
    assert meet.kinds()[-2:] == ["clearance.requested", "clearance.answered"]
    # Norrby–Åsen still goes the usual way: Norrby is its own.
    nby = next(s for s in mellana.snapshot("asn").sections if s.section == "s-nby-asn")
    assert nby.clearance_mode == ClearanceMode.REQUESTED


# --- The events (FR37) ----------------------------------------------------------------------------


def test_every_handover_and_route_is_an_event_with_who_did_it(meet: Meet, lines: Any) -> None:
    _, asen, _, remote = lines
    before = len(meet.drift().history)
    hand_over(asen, remote)
    remote.send(Action.ROUTE_REQUEST, "asn", request_id="r1", route="A-1")
    asen.send(Action.ROUTE_RESPONSE, "asn", request_id="r1", locked=True)
    asen.send(Action.PLACE_TAKE_BACK, "asn")
    written = meet.drift().history[before:]
    assert [(e.kind.value, e.place, e.actor.kind.value, e.actor.id) for e in written] == [
        ("place.offered", "asn", "client", asen.client_id),
        ("place.offer_answered", "asn", "client", remote.client_id),
        ("route.requested", "asn", "client", remote.client_id),
        ("route.answered", "asn", "client", asen.client_id),
        ("place.taken_back", "asn", "client", asen.client_id),
    ]
    # Read back after a restart: the same state.
    again = Drift(meet.store.package, meet.drift().history, now=meet.wall)
    assert again.route_asks == meet.drift().route_asks and not again.remote
    assert [e.kind for e in meet.store.log(meet.run, place="asn")][:2] == [
        Kind.PLACE_TAKEN_BACK,
        Kind.ROUTE_ANSWERED,
    ]


def test_an_old_outside_and_an_old_package_still_read() -> None:
    raw = files("contracts").joinpath("examples/asen.station-outside.json").read_text()
    old = StationOutside.model_validate_json(raw)
    assert (old.remote_routes, old.automats, old.overview, old.remote_receivers) == (
        [],
        [],
        None,
        [],
    )
    plan = MeetPackage.model_validate_json(
        files("contracts").joinpath("examples/provbanan.meet.json").read_text()
    )
    assert plan.remote_areas == [] and all(p.remote_area is None for p in plan.places)
