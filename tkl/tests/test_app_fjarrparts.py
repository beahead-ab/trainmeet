"""Fjärrstyrning, a station with parts in TKL (#36 del d, DRIFT-40, FR50, FR51, TKL100): while the
station is remote-controlled its TKL forwards the parts' waiting requests and the list Klara att
skicka in route.state, at once through `forward`; it does the controller's part.answer,
ready.move and ready.sent exactly as the clearer's Godkänn, Neka, move and Skickat in the box,
once each, and says so in route.state; and the station's own box is read-only meanwhile. The
pretend hub of del b's tests stands in for Drift. Nothing here names a station (RS13)."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts import station
from contracts.tkl import TklAnswer, TklPartRequestState
from tkl.stallverk import Interlocking
from tkl.stallverk.interlocking import Outcome
from tkl.tests.provstation import bangard
from tkl.tests.test_app_fjarrstation import (
    REMOTE,
    Place,
    PretendHub,
    S,
    connect,
    interlocking,
    step,
)

P = S + "/parts/bangarden"


@pytest.fixture
def hub() -> PretendHub:
    return PretendHub()


@pytest.fixture
def home(hub: PretendHub) -> Place:
    return hub.add("exb", "exb")


@pytest.fixture
def client(tmp_path: Path, hub: PretendHub, home: Place) -> TestClient:
    return connect(tmp_path, hub, home, bangard())


def answer(response: httpx.Response) -> TklAnswer:
    assert response.status_code == 200, response.text
    return TklAnswer.model_validate(response.json())


def asks(client: TestClient) -> int:
    """The part lays its street and asks for its route out; the request's id."""
    assert answer(client.post(P + "/street", json={"street": "V51"})).accepted
    asked = answer(client.post(P + "/request", json={"route_out": "Ut"}))
    assert asked.accepted, asked.message
    [request] = asked.state.parts[0].requests
    return request.id


def forwarded(home: Place, seconds: float = 3.0) -> station.RouteState:
    """route.state as the pretend hub has it once the station's look has sent up both the
    request and the list."""
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if home.state is not None and home.state.part_requests and home.state.ready_to_send:
            return home.state
        time.sleep(0.05)
    assert home.state is not None
    return home.state


def test_part_requests_are_forwarded_when_remote_controlled(
    client: TestClient, hub: PretendHub, home: Place
) -> None:
    """FR50, FR51: manned, the clearer answers in the box and nothing goes up; remote-controlled,
    the waiting request and the list go up in route.state at once, from forward, not at the next
    look."""
    request = asks(client)
    step(client)
    assert home.state is None or home.state.part_requests == [], "manned: the box answers"
    home.accept()
    step(client)
    assert answer(client.post(P + "/ready", json={"number": "3795"})).accepted
    state = forwarded(home)
    [asked] = state.part_requests
    assert (asked.request_id, asked.part, asked.part_name, asked.said) == (
        str(request),
        "bangarden",
        "Bangården",
        "51 → V",
    )
    assert [r.train_number for r in state.ready_to_send] == ["3795"]
    assert state.ready_to_send[0].part_name == "Bangården"


def test_the_box_is_read_only_while_remote_controlled(client: TestClient, home: Place) -> None:
    """The station's own Godkänn, Neka, move and Skickat say why they are not done here."""
    request = asks(client)
    assert answer(client.post(P + "/ready", json={"number": "3795"})).accepted
    home.accept()
    step(client)
    for path, body in (
        ("/parts/reply", {"request": request, "approved": True}),
        ("/parts/reply", {"request": request, "approved": False}),
        ("/ready/move", {"number": "3795", "to": 0}),
        ("/ready/sent", {"number": "3795"}),
    ):
        said = answer(client.post(S + path, json=body))
        assert not said.accepted, path
        assert said.message.startswith(f"Stationen fjärrstyrs från {REMOTE.name}."), said.message
    state = interlocking(client)
    assert state.parts[0].requests[0].state == TklPartRequestState.WAITING
    assert [r.number for r in state.ready] == ["3795"]


def test_part_answer_approves_as_the_box_does(client: TestClient, home: Place) -> None:
    """part.answer approved: the station's interlocking lays the route out, which is the part's,
    with the controller's name in the events (FR37, FR50); route.state says the answer is done,
    and it is done once only."""
    request = asks(client)
    home.accept()
    step(client)
    home.part_answers = [
        station.PartAnswered(
            seq=41, part="bangarden", request_id=str(request), approve=True, by=REMOTE.name
        )
    ]
    looked = step(client)
    assert looked is not None and looked.done == [41]
    state = interlocking(client)
    assert [(r.start, r.end, r.part) for r in state.routes] == [
        ("U1", "B", "bangarden"),
        ("B", "Ut", "bangarden"),
    ]
    assert state.events[0].by == REMOTE.name
    assert state.events[0].text.startswith(f"{REMOTE.name} godkände Bangårdens begäran 51 → V.")
    assert home.state is not None and home.state.part_requests == []
    assert home.part_answers == [], "Hubben has dropped it: the request no longer waits"
    again = step(client)
    assert again is not None and again.done == []


def test_part_answer_refuses_with_the_reason(client: TestClient, home: Place) -> None:
    request = asks(client)
    home.accept()
    step(client)
    home.part_answers = [
        station.PartAnswered(
            seq=42,
            part="bangarden",
            request_id=str(request),
            approve=False,
            reason="Tåg 102 kommer.",
            by=REMOTE.name,
        )
    ]
    step(client)
    state = interlocking(client)
    assert state.parts[0].requests == []
    said = f"{REMOTE.name} nekade Bangårdens begäran 51 → V: Tåg 102 kommer."
    assert state.parts[0].refused[0].text == said, "the part reads why"
    assert state.events[0].by == REMOTE.name


def test_an_approval_that_cannot_be_laid_waits_with_the_interlockings_words(
    client: TestClient, home: Place, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As in the box: a route the interlocking cannot lay now is a no to the one who answered,
    and the request waits; route.state says the answer is done and why, on the request."""
    request = asks(client)
    home.accept()
    step(client)
    said = "Vägen U1 → Ut kan inte läggas nu: spåret är belagt."

    def cannot(self: Interlocking, *_: object, **__: object) -> Outcome:
        self.revision += 1
        return Outcome(False, said)

    monkeypatch.setattr(Interlocking, "remote_reply", cannot)
    home.part_answers = [
        station.PartAnswered(
            seq=43, part="bangarden", request_id=str(request), approve=True, by=REMOTE.name
        )
    ]
    step(client)
    assert home.state is not None and home.state.answered == [43]
    [waiting] = home.state.part_requests
    assert waiting.note == said
    assert home.part_answers == [], "done: the controller may answer again"


def test_ready_to_send_moved_and_sent_from_afar(client: TestClient, home: Place) -> None:
    """FR51: the controller's move and Skickat are the station's own, by the controller's name."""
    for number in ("3795", "3797"):
        assert answer(client.post(P + "/ready", json={"number": number})).accepted
    home.accept()
    step(client)
    home.ready_asks = [
        station.ReadyAsked(seq=51, train_number="3797", to=0, by=REMOTE.name),
        station.ReadyAsked(seq=52, train_number="3795", by=REMOTE.name),
    ]
    looked = step(client)
    assert looked is not None and looked.done == [51, 52]
    state = interlocking(client)
    assert [(r.number, r.moved) for r in state.ready] == [("3797", True)]
    assert state.events[0].text == "Tåg 3795 från Bangården är skickat."
    assert state.events[0].by == REMOTE.name
    assert home.state is not None
    assert [(r.train_number, r.moved) for r in home.state.ready_to_send] == [("3797", True)]
    assert home.ready_asks == []
