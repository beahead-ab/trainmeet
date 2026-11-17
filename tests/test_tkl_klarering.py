"""KLAR-26, TKL90: steg 2:s prov med TKL på nivå 0 som B. TKL at Åsen is B, a client at Mellanå is
A. B sees train 102 on its way here on track 2, gives clearance and presses Ankommit, and A sees
the train that has left. TKL and the hub run here in one process: TKL's server talks to the hub
over HTTP, as it does across the network, and only through the station protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts import station
from contracts.tkl import TklMode
from hub.app import create_app as create_hub
from hub.build_info import BuildInfo
from hub.tests.test_tmbox_web import started
from tkl.app import create_app as create_tkl

API = "/api/tkl/1"
HUB = "http://testserver"


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    return TestClient(create_hub(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))


@pytest.fixture
def tkl(hub: TestClient, tmp_path: Path) -> TestClient:
    made = create_tkl(
        tmp_path / "tkl", mode=TklMode.LOCAL, http=lambda: hub, discover=lambda: [HUB]
    )
    client = TestClient(made)
    answer = client.post(API + "/setup", json={"name": "Åsen", "station_id": "asen", "pin": "4711"})
    assert answer.status_code == 201, answer.text
    return client


class A:
    """The neighbour at Mellanå: a client of the station protocol, approved for its place."""

    def __init__(self, hub: TestClient, code: str) -> None:
        body = {"kind": "tmbox_app", "name": "Mellanå", "software": "prov", "code": code}
        self.hub = hub
        self.client_id = hub.post("/api/station/1/connect", json=body).json()["client_id"]
        hub.post(
            "/api/provbanan/clients/approve",
            json={"client_id": self.client_id, "places": ["mla"]},
        )
        key = hub.get(f"/api/station/1/connect/{self.client_id}").json()["key"]
        self.headers = {"Authorization": "Bearer " + key}

    def seen(self) -> station.Snapshot:
        answer = self.hub.get("/api/station/1/places/mla", headers=self.headers)
        return station.Snapshot.model_validate(answer.json())

    def send(self, action: station.Action, **payload: Any) -> station.Reply:
        body = {
            "message_id": uuid4().hex,
            "client_id": self.client_id,
            "place": "mla",
            "context": self.seen().context.model_dump(mode="json"),
            "action": action.value,
            "payload": payload,
        }
        answer = self.hub.post("/api/station/1/commands", json=body, headers=self.headers)
        return station.Reply.model_validate(answer.json())


def b_sees(tkl: TestClient) -> station.Snapshot:
    view = tkl.get(API + "/places/asn")
    assert view.status_code == 200, view.text
    assert view.json()["stale"] is False
    return station.Snapshot.model_validate(view.json()["snapshot"])


def b_sends(tkl: TestClient, action: station.Action, **payload: Any) -> station.Reply:
    seen = b_sees(tkl)
    body = {
        "message_id": uuid4().hex,
        "place": "asn",
        "context": seen.context.model_dump(mode="json"),
        "action": action.value,
        "payload": payload,
    }
    answer = tkl.post(API + "/commands", json=body)
    assert answer.status_code == 200, answer.text
    return station.Reply.model_validate(answer.json())


def approve_b(hub: TestClient) -> None:
    [b] = [c for c in hub.get("/api/provbanan/clients").json()["clients"] if c["kind"] == "tkl"]
    hub.post(
        "/api/provbanan/clients/approve", json={"client_id": b["client_id"], "places": ["asn"]}
    )


def test_steg_2_with_tkl_as_b(hub: TestClient, tkl: TestClient) -> None:
    code = started(hub)
    # TKL connects with the run's code, as over the internet: the key stays in TKL's server.
    waiting = tkl.post(API + "/connection", json={"address": HUB, "code": code})
    assert waiting.status_code == 200, waiting.text
    assert (waiting.json()["status"], waiting.json()["outside_version"]) == ("waiting", 1)
    listed = hub.get("/api/provbanan/clients").json()["clients"]
    [b] = [c for c in listed if c["kind"] == "tkl"]
    assert (b["name"], b["places"]) == ("TKL Åsen", ["asn"]), "Klienter suggests Åsen"
    approve_b(hub)
    approved = tkl.get(API + "/connection").json()
    assert (approved["status"], approved["places"]) == ("approved", ["asn"])
    assert "key" not in approved
    # Åsen is coupled in advance in Provbanan: its exits come from the version (KLAR-12).
    seen = b_sees(tkl)
    assert {s.other_place: s.exit for s in seen.sections} == {"nby": "v", "mla": "o"}
    assert seen.questions == []
    # A asks for 102 to Åsen; B gives clearance.
    a = A(hub, code)
    asked = a.send(
        station.Action.CLEARANCE_REQUEST,
        call="t102-mla",
        section="s-asn-mla",
        clearance_id="c-102",
    )
    assert asked.status == station.ReplyStatus.ACCEPTED
    [request] = [c for c in b_sees(tkl).clearances if c.to_place == "asn"]
    assert (request.train_number, request.status) == ("102", station.ClearanceStatus.WAITING)
    given = b_sends(
        tkl, station.Action.CLEARANCE_RESPONSE, clearance_id=request.clearance_id, approved=True
    )
    assert given.status == station.ReplyStatus.ACCEPTED
    # A leaves: A sees the train that has left, B sees it on its way here on track 2.
    assert a.send(station.Action.TRAIN_DEPARTED, call="t102-mla").status == "accepted"
    assert [t.train_number for t in a.seen().have_left] == ["102"]
    [coming] = b_sees(tkl).on_the_way
    assert (coming.train_number, coming.other_place, coming.planned_track) == ("102", "mla", "2")
    # B presses Ankommit: the train is in, and A no longer has it on the line.
    arrived = b_sends(tkl, station.Action.TRAIN_ARRIVED, call=coming.call)
    assert arrived.status == station.ReplyStatus.ACCEPTED, arrived.message
    assert arrived.snapshot.on_the_way == []
    here = next(c for c in arrived.snapshot.calls if c.call == coming.call)
    assert here.arrival_state == station.ArrivalState.ARRIVED
    assert a.seen().have_left == []


def test_a_refusal_comes_back_as_the_hub_said_it(hub: TestClient, tkl: TestClient) -> None:
    code = started(hub)
    tkl.post(API + "/connection", json={"address": HUB, "code": code})
    approve_b(hub)
    refused = b_sends(tkl, station.Action.TRAIN_DEPARTED, call="t101-asn")
    assert (refused.status, refused.message) == ("rejected", "Tåget saknar beviljad klarering.")
    # Revoked in Klienter: TKL says so, and keeps no key.
    [b] = [c for c in hub.get("/api/provbanan/clients").json()["clients"] if c["kind"] == "tkl"]
    hub.post("/api/provbanan/clients/revoke", json={"client_id": b["client_id"]})
    assert tkl.get(API + "/places/asn").status_code == 401
    assert tkl.get(API + "/connection").json()["status"] == "revoked"
    assert tkl.get(API + "/places/asn").status_code == 409


def test_only_a_hub_with_a_started_meet_is_found(hub: TestClient, tkl: TestClient) -> None:
    """H36: the hub announces itself on the meet's network, and TKL shows it only when its meet
    is started."""
    assert tkl.get(API + "/hubs").json() == []
    assert hub.post("/api/hub/setup", json={"name": "Pi:n", "pin": "482915"}).status_code == 201
    assert hub.post("/api/drift/1/start", json={"version": 1}).status_code == 201
    [found] = tkl.get(API + "/hubs").json()
    assert found == {"address": HUB, "name": "Pi:n", "meet": "Provbanan", "nearby": True}


def test_without_a_code_over_the_internet(hub: TestClient, tkl: TestClient) -> None:
    started(hub)
    answer = tkl.post(API + "/connection", json={"address": HUB})
    assert (answer.status_code, answer.json()["detail"]) == (
        401,
        "Över internet behövs en kod från trafikledningen.",
    )


def test_tkl_answers_hubbens_question_and_passes_the_hints_on(
    hub: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H26 in TKL: Mellanå has two exits towards Åsen, so Hubben asks, and TKL answers. The
    event stream comes through TKL's server with the key, which the browser never sees."""
    from hub import station_api

    made = create_tkl(
        tmp_path / "mla",
        http=lambda: hub,
        stream=lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=hub.app)),
        discover=lambda: [],
    )
    tkl = TestClient(made)
    tkl.post(API + "/setup", json={"name": "Mellanå", "station_id": "mellana", "pin": "4711"})
    outside = {
        "station_id": "mellana",
        "name": "Mellanå",
        "tracks": [{"id": "1", "label": "Spår 1"}, {"id": "2", "label": "Spår 2"}],
        "exits": [
            {"id": "AU", "side": "left", "name": "Åsen uppspår"},
            {"id": "AN", "side": "left", "name": "Åsen nedspår"},
            {"id": "S", "side": "right", "name": "Mot Sjövik"},
        ],
    }
    assert tkl.put(API + "/studio", json=outside).status_code == 200
    assert tkl.post(API + "/studio/version").json()["versions"][0]["number"] == 1
    code = started(hub)
    tkl.post(API + "/connection", json={"address": HUB, "code": code})
    [b] = [c for c in hub.get("/api/provbanan/clients").json()["clients"] if c["kind"] == "tkl"]
    assert b["places"] == ["mla"]
    hub.post(
        "/api/provbanan/clients/approve", json={"client_id": b["client_id"], "places": ["mla"]}
    )
    view = tkl.get(API + "/places/mla").json()
    [question] = view["snapshot"]["questions"]
    assert [a["exit"] for a in question["alternatives"]] == ["AU", "AN"]
    answered = tkl.post(API + "/places/mla/exits", json={"section": "s-asn-mla", "exit": "AN"})
    assert answered.status_code == 200, answered.text
    assert answered.json()["snapshot"]["questions"] == []
    late = tkl.post(API + "/places/mla/exits", json={"section": "s-asn-mla", "exit": "AU"})
    assert (late.status_code, late.json()["detail"]) == (
        409,
        "Frågan är redan besvarad: utfart AN.",
    )
    monkeypatch.setattr(station_api, "STREAM_SECONDS", 0)
    with tkl.stream("GET", API + "/places/mla/events") as hints:
        assert hints.status_code == 200
        assert "event: changed" in "".join(hints.iter_text())
