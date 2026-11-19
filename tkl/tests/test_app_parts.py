"""Delställverk's API (#87) under /api/tkl/1/stallverk/parts: the part's own screen behind the
same PIN (TKL102), the five messages (TKL98), the station's answers in Ställverket, and Klart
att skicka (TKL108). Nothing here names a station (RS13)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts.tkl import TklAnswer, TklInterlocking, TklPartRequestState, TklPartTrains
from tkl.tests.provstation import bangard
from tkl.tests.test_app import API, set_up, tkl
from tkl.tests.test_app_stallverk import with_model

S = API + "/stallverk"
P = S + "/parts/bangarden"


def answer(response: httpx.Response) -> TklAnswer:
    assert response.status_code == 200, response.text
    return TklAnswer.model_validate(response.json())


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    made = tkl(tmp_path)
    assert set_up(made).status_code == 201
    with_model(made, bangard())
    return made


def test_only_an_unlocked_tkl_operates_a_part(client: TestClient) -> None:
    client.post(API + "/lock")
    for path, body in (
        ("/street", {"street": "V51"}),
        ("/request", {"route_out": "Ut"}),
        ("/return", {"request": 1}),
        ("/done", None),
        ("/gates", None),
        ("/ring", None),
        ("/fika", {"on": True}),
        ("/ready", {"number": "3795"}),
        ("/lever", {"switch": "4"}),
        ("/route", {"start": "U1", "end": "Stopp51"}),
        ("/release", {"route": 1}),
    ):
        assert client.post(P + path, json=body).status_code == 401, path
    assert client.get(P + "/trains").status_code == 401
    assert client.post(S + "/parts/reply", json={"request": 1, "approved": True}).status_code == 401
    assert client.post(S + "/ready/sent", json={"number": "1"}).status_code == 401


def test_the_part_requests_and_the_station_approves(client: TestClient) -> None:
    """The issue's test through the API: a street, a request out, Godkänn, Klart att skicka,
    the list in Ställverket, and back."""
    laid = answer(client.post(P + "/street", json={"street": "V51"}))
    assert laid.accepted, laid.message
    asked = answer(client.post(P + "/request", json={"route_out": "Ut"}))
    assert asked.accepted and asked.message == "Bangården begär 51 → V (U1 → Ut)."
    [part] = asked.state.parts
    [request] = part.requests
    assert request.state == TklPartRequestState.WAITING and request.said == "51 → V"
    assert asked.state.events[0].by == "Bangården"
    approved = answer(
        client.post(S + "/parts/reply", json={"request": request.id, "approved": True})
    )
    assert approved.accepted, approved.message
    assert [(r.start, r.end, r.part) for r in approved.state.routes] == [
        ("U1", "B", "bangarden"),
        ("B", "Ut", "bangarden"),
    ]
    held = answer(client.post(S + "/release", json={"route": approved.state.routes[0].id}))
    assert not held.accepted and "envägsregeln" in held.message
    ready = answer(client.post(P + "/ready", json={"number": "3795"}))
    assert ready.accepted and [r.number for r in ready.state.ready] == ["3795"]
    state = TklInterlocking.model_validate(client.get(S).json())
    assert state.ready[0].part_name == "Bangården", "the station sees the list"
    sent = answer(client.post(S + "/ready/sent", json={"number": "3795"}))
    assert sent.accepted and sent.state.ready == []
    returned = answer(client.post(P + "/return", json={"request": request.id}))
    assert returned.accepted, returned.message
    assert returned.state.routes == [] and returned.state.parts[0].requests == []


def test_a_request_that_cannot_go_is_refused_at_once(client: TestClient) -> None:
    """RANG-10: nothing reaches the station."""
    assert answer(client.post(S + "/route", json={"start": "In", "end": "11"})).accepted
    refused = answer(client.post(P + "/request", json={"route_out": "Ut"}))
    assert not refused.accepted and refused.message.startswith("Går inte att begära V Ut:")
    assert refused.state.parts[0].requests == []
    assert refused.state.parts[0].refused[0].text == refused.message, "the part's screen sees why"


def test_neka_ring_fika_klart_and_grindar(client: TestClient) -> None:
    asked = answer(client.post(P + "/request", json={"route_out": "Ut"}))
    request = asked.state.parts[0].requests[0].id
    refused = answer(client.post(S + "/parts/reply", json={"request": request, "approved": False}))
    assert refused.accepted and refused.state.parts[0].refused[0].text.startswith(
        "Tågklareraren nekade"
    )
    rang = answer(client.post(P + "/ring"))
    assert rang.state.parts[0].rings is not None
    answered = answer(client.post(S + "/parts/ring-answer", json={"part": "bangarden"}))
    assert answered.state.parts[0].rings is None
    fika = answer(client.post(P + "/fika", json={"on": True}))
    assert fika.state.parts[0].fika
    no = answer(client.post(P + "/street", json={"street": "V51"}))
    assert not no.accepted and "fika" in no.message
    answer(client.post(P + "/fika", json={"on": False}))
    gates = answer(client.post(P + "/gates"))
    assert gates.accepted and gates.state.switches["3"].position == "-"
    done = answer(client.post(P + "/done"))
    assert done.accepted and done.message.startswith("Bangården: klart.")


def test_the_part_lays_its_own_and_sets_routes_in_its_area(client: TestClient) -> None:
    lever = answer(client.post(P + "/lever", json={"switch": "4"}))
    assert lever.accepted
    station = answer(client.post(P + "/lever", json={"switch": "1"}))
    assert not station.accepted and "tillhör stationen" in station.message
    targets = client.get(P + "/targets", params={"start": "U1"})
    assert targets.status_code == 200
    goals = {t["end"]: (t["possible"], t.get("reason") or "") for t in targets.json()["targets"]}
    assert set(goals) == {"Stopp51", "Stopp52", "B"}, "only goals inside the area"
    assert goals["Stopp51"] == (True, "") and goals["Stopp52"] == (True, "")
    assert not goals["B"][0] and "RANG-12" in goals["B"][1], "B is the border: a request"
    laid = answer(client.post(P + "/route", json={"start": "U1", "end": "Stopp51"}))
    assert laid.accepted, laid.message
    route = laid.state.routes[0]
    assert route.part == "bangarden"
    released = answer(client.post(P + "/release", json={"route": route.id}))
    assert released.accepted and released.state.routes == []
    assert client.get(P + "/targets", params={"start": "nowhere"}).status_code == 404


def test_the_trains_without_a_hub_say_to_type_the_number(client: TestClient) -> None:
    found = TklPartTrains.model_validate(client.get(P + "/trains").json())
    assert (
        found.trains == [] and found.message == "TKL har ingen plan från Hubben. Skriv tågnumret."
    )
    assert client.get(S + "/parts/nowhere/trains").status_code == 404
    unknown = answer(client.post(S + "/parts/nowhere/ring"))
    assert not unknown.accepted and "finns inte" in unknown.message


def test_the_ready_list_moves(client: TestClient) -> None:
    for number in ("3811", "3795", "3827"):
        assert answer(client.post(P + "/ready", json={"number": number})).accepted
    moved = answer(client.post(S + "/ready/move", json={"number": "3827", "to": 0}))
    assert [r.number for r in moved.state.ready] == ["3827", "3811", "3795"]
    assert moved.state.ready[0].moved
