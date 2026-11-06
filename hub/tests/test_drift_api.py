"""The hub's own meet through Driftens API (5.4, steg 3): only the logged-in administrator runs
it; everyone may read Nu (S1). Boxes and TKL join the meet with its code, as on Provbanan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts import drift
from hub import drift_api
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.tests.test_station_api import Client
from hub.tests.test_tmbox_web import Tab

PIN = "482915"
API = "/api/drift/1"


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "prov.db"))
    assert client.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN}).status_code == 201
    return client


@pytest.fixture
def running(hub: TestClient) -> TestClient:
    response = hub.post(API + "/start", json={"version": 1})
    assert response.status_code == 201, response.text
    return hub


def nu(client: TestClient) -> drift.Now:
    response = client.get(API + "/now")
    assert response.status_code == 200, response.text
    return drift.Now.model_validate(response.json())


def code_of(hub: TestClient) -> str:
    joining = drift.Joining.model_validate(hub.get(API + "/connect").json())
    assert joining.url.endswith("/box#kod=" + joining.code)
    return joining.code


def test_only_the_administrator_starts_the_meet(hub: TestClient) -> None:
    anonymous = TestClient(hub.app)
    assert anonymous.post(API + "/start", json={"version": 1}).status_code == 401
    assert anonymous.get(API + "/now").status_code == 404, "no meet yet"
    assert hub.post(API + "/start", json={"version": 2}).status_code == 409
    started = hub.post(API + "/start", json={"version": 1, "traffic_day": "tue"})
    event = drift.DriftEvent.model_validate(started.json())
    assert event.kind == drift.EventKind.MEET_STARTED
    assert event.data["traffic_day"] == "tue"


def test_everyone_may_read_nu_and_it_names_no_one(running: TestClient) -> None:
    seen = nu(TestClient(running.app))
    assert (seen.name, seen.traffic_day, seen.clock.time, seen.clock.running) == (
        "Provbanan",
        "mon",
        "06:00",
        False,
    )
    assert [p.code for p in seen.places] == ["Nby", "Ån", "Mlå", "Sjv"]
    first = seen.legs[0]
    assert (first.train_number, first.from_place, first.to_place, first.state) == (
        "101",
        "nby",
        "asn",
        "planned",
    )
    text = TestClient(running.app).get(API + "/now").text
    assert "phone" not in text and code_of(running) not in text


def test_the_administrator_runs_the_clock(running: TestClient) -> None:
    anonymous = TestClient(running.app)
    assert anonymous.post(API + "/clock", json={"action": "start"}).status_code == 401
    started = running.post(API + "/clock", json={"action": "start"})
    assert drift.DriftEvent.model_validate(started.json()).kind == drift.EventKind.CLOCK_STARTED
    assert nu(running).clock.running is True
    faster = running.post(API + "/clock", json={"action": "speed", "speed": 6})
    assert faster.status_code == 200 and nu(running).clock.speed == 6
    running.post(API + "/clock", json={"action": "stop"})
    assert nu(running).clock.running is False
    assert running.post(API + "/clock", json={"action": "jump", "time": "08:00"}).status_code == (
        409
    ), "the time jump comes later (F6, H37)"


def test_boxes_join_the_meet_with_its_code_and_are_assigned(running: TestClient) -> None:
    code = code_of(running)
    box = Tab(running, "Box Norrby", code)
    (waiting,) = running.get(API + "/clients").json()
    assert (waiting["client_id"], waiting["status"]) == (box.client_id, "waiting")
    assigned = running.post(
        API + "/clients/assign",
        json={"client_id": box.client_id, "places": ["nby"], "language": "en"},
    )
    assert assigned.status_code == 200
    client = drift.Client.model_validate(assigned.json())
    assert (client.status, client.places, client.language) == ("approved", ["nby"], "en")
    box.number("101")
    seen = nu(running)
    assert seen.legs[0].state == "requested"
    assert [c.train_number for c in seen.clearances] == ["101"]


def test_a_tkl_joins_the_meet_and_is_approved_through_the_api(running: TestClient) -> None:
    tkl = Client(running, code_of(running), ["asn"])
    response = running.post(
        API + "/clients/approve", json={"client_id": tkl.client_id, "places": ["asn"]}
    )
    assert response.status_code == 200 and response.json()["status"] == "approved"
    assert tkl.poll().key is not None
    assert tkl.snapshot("asn").place.name == "Åsen"
    revoked = running.post(API + "/clients/revoke", json={"client_id": tkl.client_id})
    assert revoked.json()["status"] == "revoked"
    assert (
        running.post(
            API + "/clients/approve", json={"client_id": "tkl-none", "places": ["asn"]}
        ).status_code
        == 404
    )


def test_the_meet_and_provbanan_never_mix(running: TestClient) -> None:
    """A box with a Provbanan code joins that run, not the meet (H51)."""
    trial = running.post("/api/provbanan/start", json={"version": 1}).json()
    provbana_code = running.get("/api/provbanan/clients").json()["code"]
    assert provbana_code != code_of(running)
    box = Tab(running, "Provbox", provbana_code)
    assert running.get(API + "/clients").json() == []
    listed = running.get("/api/provbanan/clients").json()["clients"]
    assert [c["client_id"] for c in listed] == [box.client_id]
    assert trial["context"]["meet_id"] == "provbanan"


def test_the_log_lists_the_meet_newest_first_for_a_place_or_train(running: TestClient) -> None:
    box = Tab(running, "Box Norrby", code_of(running))
    running.post(API + "/clients/assign", json={"client_id": box.client_id, "places": ["nby"]})
    box.number("101")
    events = [drift.DriftEvent.model_validate(e) for e in running.get(API + "/log").json()]
    assert [e.kind for e in events][:1] == [drift.EventKind.CLEARANCE_REQUESTED]
    assert events[-1].kind == drift.EventKind.MEET_STARTED
    by_place = running.get(API + "/log", params={"place": "asn"}).json()
    assert [e["kind"] for e in by_place] == ["clearance.requested"]
    assert running.get(API + "/log", params={"train": "102"}).json() == []
    assert TestClient(running.app).get(API + "/log").status_code == 401


def test_the_qr_code_opens_the_box_with_the_code(running: TestClient) -> None:
    response = running.get(API + "/connect.svg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.text.lstrip().startswith("<?xml") or "<svg" in response.text
    assert TestClient(running.app).get(API + "/connect.svg").status_code == 401
    assert TestClient(running.app).get(API + "/connect").status_code == 401


def test_a_new_meet_takes_the_place_of_the_old(running: TestClient) -> None:
    box = Tab(running, "Box", code_of(running))
    running.post(API + "/start", json={"version": 1, "traffic_day": "wed"})
    assert nu(running).traffic_day == "wed"
    assert running.get(API + "/clients").json() == [], "the new meet starts with no clients"
    gone = running.get("/api/terminal/frame", headers=box.headers)
    assert gone.status_code in {401, 404}


def test_the_meet_survives_a_restart_with_the_clock_stopped(tmp_path: Path) -> None:
    def app() -> TestClient:
        return TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))

    first = app()
    first.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN})
    first.post(API + "/start", json={"version": 1})
    first.post(API + "/clock", json={"action": "start"})
    box = Tab(first, "Box Norrby", code_of(first))
    first.post(API + "/clients/assign", json={"client_id": box.client_id, "places": ["nby"]})
    box.number("101")
    again = app()  # A new process: the hub was restarted.
    seen = nu(again)
    assert seen.clock.running is False, "the clock never runs on by itself after a restart"
    assert [c.train_number for c in seen.clearances] == ["101"]
    assert box.frame()["lines"][0].strip().endswith("101?Ån")


def test_the_event_stream_needs_the_administrator(
    running: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drift_api, "STREAM_SECONDS", 0)
    with running.stream("GET", API + "/events") as response:
        assert response.status_code == 200
        text: Any = "".join(response.iter_text())
    assert text.startswith(": hubben lyssnar")
    assert TestClient(running.app).get(API + "/events").status_code == 401
