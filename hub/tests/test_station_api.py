"""The station protocol over HTTP: a TKL connects to a Provbanan run, is approved for Norrby,
and runs train 101 with a TMBox web box at Åsen, each on its own side of the protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from contracts import station
from hub import station_api
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.tests.test_tmbox_web import Tab, assign, started

API = "/api/station/1"


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    return TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "prov.db"))


class Client:
    """A TKL: it connects, waits for approval and then sends its key as Bearer."""

    def __init__(self, hub: TestClient, code: str, wants: list[str]) -> None:
        response = hub.post(
            API + "/connect",
            json={
                "kind": "tkl",
                "name": "TKL Norrby",
                "software": "TKL 0.1.0",
                "wants": wants,
                "code": code,
            },
        )
        assert response.status_code == 201, response.text
        reply = station.ConnectReply.model_validate(response.json())
        assert (reply.status, reply.key) == (station.ApprovalStatus.WAITING, None)
        self.hub = hub
        self.client_id = reply.client_id
        self.headers: dict[str, str] = {}

    def poll(self) -> station.ConnectReply:
        response = self.hub.get(f"{API}/connect/{self.client_id}")
        assert response.status_code == 200, response.text
        reply = station.ConnectReply.model_validate(response.json())
        if reply.key:
            self.headers = {"Authorization": "Bearer " + reply.key}
        return reply

    def snapshot(self, place: str) -> station.Snapshot:
        response = self.hub.get(f"{API}/places/{place}", headers=self.headers)
        assert response.status_code == 200, response.text
        return station.Snapshot.model_validate(response.json())

    def command(
        self,
        action: station.Action,
        place: str = "nby",
        message_id: str | None = None,
        **payload: Any,
    ) -> station.Reply:
        response = self.post(action, place, message_id, **payload)
        assert response.status_code == 200, response.text
        return station.Reply.model_validate(response.json())

    def post(
        self, action: station.Action, place: str, message_id: str | None, **payload: Any
    ) -> Any:
        context = self.snapshot(place).context.model_dump(mode="json")
        body = {
            "message_id": message_id or uuid4().hex,
            "client_id": self.client_id,
            "place": place,
            "context": context,
            "action": action.value,
            "payload": payload,
        }
        return self.hub.post(API + "/commands", json=body, headers=self.headers)


def approve(hub: TestClient, client: Client, places: list[str]) -> dict[str, Any]:
    response = hub.post(
        "/api/provbanan/clients/approve", json={"client_id": client.client_id, "places": places}
    )
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


@pytest.fixture
def tkl(hub: TestClient) -> Client:
    """A TKL approved for Norrby, with its key."""
    code = started(hub)
    client = Client(hub, code, ["nby"])
    approve(hub, client, ["nby"])
    assert client.poll().key is not None
    return client


def test_a_client_waits_until_the_dispatcher_approves_it(hub: TestClient) -> None:
    code = started(hub)
    client = Client(hub, code, ["nby"])
    assert client.poll().status == station.ApprovalStatus.WAITING
    listed = {c["client_id"]: c for c in hub.get("/api/provbanan/clients").json()["clients"]}
    assert (listed[client.client_id]["kind"], listed[client.client_id]["status"]) == (
        "tkl",
        "waiting",
    )
    assert listed[client.client_id]["places"] == ["nby"], "what it asked for, to approve"
    answer = approve(hub, client, ["nby"])
    approved = {c["client_id"]: c for c in answer["clients"]}[client.client_id]
    assert approved["status"] == "approved"
    first = client.poll()
    assert (first.status, first.places) == (station.ApprovalStatus.APPROVED, ["nby"])
    assert first.key is not None and len(first.key) >= 40
    assert client.poll().key is None, "the key comes once"


def test_a_wrong_code_finds_no_run(hub: TestClient) -> None:
    started(hub)
    response = hub.post(
        API + "/connect",
        json={"kind": "tkl", "name": "T", "software": "TKL", "code": "000000x"},
    )
    assert response.status_code == 404


def test_only_a_stop_can_be_approved(hub: TestClient) -> None:
    code = started(hub)
    client = Client(hub, code, ["lvh"])
    response = hub.post(
        "/api/provbanan/clients/approve", json={"client_id": client.client_id, "places": ["lvh"]}
    )
    assert response.status_code == 409
    missing = hub.post(
        "/api/provbanan/clients/approve", json={"client_id": "tkl-nothing", "places": ["nby"]}
    )
    assert missing.status_code == 404


def test_the_snapshot_needs_the_key_and_the_place(tkl: Client) -> None:
    seen = tkl.snapshot("nby")
    assert seen.place.place == "nby"
    assert [c.train_number for c in seen.calls][:2] == ["101", "102"]
    assert tkl.hub.get(f"{API}/places/asn", headers=tkl.headers).status_code == 403
    assert tkl.hub.get(f"{API}/places/nby").status_code == 401
    wrong = {"Authorization": "Bearer " + "x" * 43}
    assert tkl.hub.get(f"{API}/places/nby", headers=wrong).status_code == 401


def test_the_tkl_and_a_web_box_run_train_101_together(hub: TestClient, tkl: Client) -> None:
    code = hub.get("/api/provbanan/clients").json()["code"]
    asen = Tab(hub, "Box Åsen", code)
    assign(hub, asen, "asn")
    reply = tkl.command(
        station.Action.CLEARANCE_REQUEST, call="t101-nby", section="s-nby-asn", clearance_id="c-101"
    )
    assert reply.status == station.ReplyStatus.ACCEPTED
    assert reply.revision == station.Revision(
        scope=station.RevisionScope.CASE, key="c-101", value=1
    )
    assert [c.status for c in reply.snapshot.clearances] == [station.ClearanceStatus.WAITING]
    # The box at Åsen is asked, as if a box at Norrby had asked.
    frame = asen.frame()
    assert frame["lines"][0] == "Nby?101      1/1"
    asen.press("#")
    assert tkl.snapshot("nby").clearances[0].status == station.ClearanceStatus.APPROVED
    departed = tkl.command(station.Action.TRAIN_DEPARTED, call="t101-nby")
    assert departed.status == station.ReplyStatus.ACCEPTED
    assert [t.call for t in departed.snapshot.have_left] == ["t101-asn"]
    assert "Nby▶101" in asen.frame()["lines"][0]
    asen.press("#")  # Ankomst.
    seen = tkl.snapshot("nby")
    assert seen.clearances == [] and seen.have_left == []


def test_a_resent_message_answers_the_same_without_a_second_effect(tkl: Client) -> None:
    payload = {"call": "t101-nby", "section": "s-nby-asn", "clearance_id": "c-1"}
    first = tkl.command(station.Action.CLEARANCE_REQUEST, message_id="same-message-1", **payload)
    again = tkl.command(station.Action.CLEARANCE_REQUEST, message_id="same-message-1", **payload)
    assert (first.status, again.status) == (
        station.ReplyStatus.ACCEPTED,
        station.ReplyStatus.DUPLICATE,
    )
    assert again.revision == first.revision
    assert len(again.snapshot.clearances) == 1
    other = tkl.post(
        station.Action.CLEARANCE_REQUEST, "nby", "same-message-1", **{**payload, "call": "t103-nby"}
    )
    assert other.status_code == 403, "one message id, one command"


def test_a_refusal_says_why_and_changes_nothing(tkl: Client) -> None:
    reply = tkl.command(station.Action.TRAIN_DEPARTED, call="t101-nby")
    assert (reply.status, reply.reason) == (
        station.ReplyStatus.REJECTED,
        "departure_not_reserved",
    )
    assert reply.message == "Tåget saknar beviljad klarering."
    assert reply.snapshot.clearances == []


def test_lookup_answers_with_the_calls(tkl: Client) -> None:
    reply = tkl.command(station.Action.TRAIN_LOOKUP, train_number="101")
    assert reply.result is not None
    assert [(m.call, m.to_place) for m in reply.result] == [("t101-nby", "asn")]


def test_a_client_acts_only_as_itself_and_only_where_approved(tkl: Client) -> None:
    context = tkl.snapshot("nby").context.model_dump(mode="json")
    body = {
        "message_id": uuid4().hex,
        "client_id": "tkl-someone-else",
        "place": "nby",
        "context": context,
        "action": "train.lookup",
        "payload": {"train_number": "101"},
    }
    assert tkl.hub.post(API + "/commands", json=body, headers=tkl.headers).status_code == 403
    body = {**body, "client_id": tkl.client_id, "place": "asn"}
    assert tkl.hub.post(API + "/commands", json=body, headers=tkl.headers).status_code == 403


def test_a_revoked_key_stops_working_at_once(hub: TestClient, tkl: Client) -> None:
    response = hub.post("/api/provbanan/clients/revoke", json={"client_id": tkl.client_id})
    assert response.status_code == 200
    assert hub.get(f"{API}/places/nby", headers=tkl.headers).status_code == 401
    assert tkl.poll().status == station.ApprovalStatus.REVOKED


def test_the_event_stream_says_when_to_fetch_again(
    tkl: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(station_api, "STREAM_SECONDS", 0)
    with tkl.hub.stream("GET", f"{API}/places/nby/events", headers=tkl.headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())
    assert text.startswith('event: changed\ndata: {"place_revision": ')
    forbidden = tkl.hub.get(f"{API}/places/asn/events", headers=tkl.headers)
    assert forbidden.status_code == 403
