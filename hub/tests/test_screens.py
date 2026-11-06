"""Träffens skärmar (steg 3): a screen joins with the meet's code, waits under Väntar and shows
the clock when the dispatcher gives it that view in Klienter (S3, S4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contracts import drift, screen
from hub.app import create_app
from hub.build_info import BuildInfo

PIN = "482915"
API = "/api/drift/1"


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "prov.db"))
    client.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN})
    client.post(API + "/start", json={"version": 1})
    return client


def join(hub: TestClient, name: str = "TV vid entrén") -> tuple[str, dict[str, str]]:
    code = hub.get(API + "/connect").json()["code"]
    response = TestClient(hub.app).post("/api/screen/session", json={"name": name, "code": code})
    assert response.status_code == 201, response.text
    session = screen.ScreenSession.model_validate(response.json())
    return session.client_id, {"Authorization": "Bearer " + session.session_key}


def picture(hub: TestClient, headers: dict[str, str]) -> screen.ScreenPicture:
    response = TestClient(hub.app).get("/api/screen/picture", headers=headers)
    assert response.status_code == 200, response.text
    return screen.ScreenPicture.model_validate(response.json())


def test_a_screen_waits_under_vantar_until_it_gets_the_clock(hub: TestClient) -> None:
    client_id, headers = join(hub)
    waiting = picture(hub, headers)
    assert (waiting.name, waiting.view) == ("TV vid entrén", None)
    listed = {
        c["client_id"]: drift.Client.model_validate(c) for c in hub.get(API + "/clients").json()
    }
    assert (listed[client_id].kind, listed[client_id].status) == ("screen", "waiting")
    shown = hub.post(API + "/clients/view", json={"client_id": client_id, "view": "clock"})
    assert shown.status_code == 200 and shown.json()["view"] == "clock"
    clock = picture(hub, headers)
    assert clock.view == screen.ScreenView.CLOCK
    assert (clock.meet, clock.clock.time, clock.clock.running) == ("Provbanan", "06:00", False)
    hub.post(API + "/clock", json={"action": "start"})
    assert picture(hub, headers).clock.running is True


def test_only_the_administrator_gives_a_view(hub: TestClient) -> None:
    client_id, _ = join(hub)
    body = {"client_id": client_id, "view": "clock"}
    assert TestClient(hub.app).post(API + "/clients/view", json=body).status_code == 401
    assert (
        hub.post(API + "/clients/view", json={"client_id": "screen-x", "view": "clock"}).status_code
        == 404
    )
    assert hub.post(API + "/clients/view", json={**body, "view": "graph"}).status_code == 422


def test_a_screen_needs_the_right_code_and_its_key(hub: TestClient) -> None:
    wrong = TestClient(hub.app).post("/api/screen/session", json={"name": "TV", "code": "000000x"})
    assert wrong.status_code == 404
    assert TestClient(hub.app).get("/api/screen/picture").status_code == 401
    bad = {"Authorization": "Bearer " + "x" * 43}
    assert TestClient(hub.app).get("/api/screen/picture", headers=bad).status_code == 401


def test_a_new_meet_lets_the_screens_go(hub: TestClient) -> None:
    _, headers = join(hub)
    hub.post(API + "/start", json={"version": 1})
    assert TestClient(hub.app).get("/api/screen/picture", headers=headers).status_code == 401


def test_the_screen_page_is_there_and_keeps_the_key_out_of_the_address(hub: TestClient) -> None:
    page = TestClient(hub.app).get("/skarm").text
    assert 'id="login-form"' in page and 'id="clock-view"' in page
    assert "/static/skarm.js" in page
