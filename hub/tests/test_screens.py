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


def test_the_screen_is_the_app_from_apps_skarmar(tmp_path: Path) -> None:
    """SKARM-14: /skarm is the React app; its own addresses get its index.html, its files come
    as they are, and it loads only its own files."""
    built = tmp_path / "web" / "skarmar"
    (built / "assets").mkdir(parents=True)
    (built / "index.html").write_text("<!doctype html><title>TrainMeet · Skärm</title>")
    (built / "assets" / "index-abc.js").write_text("console.log('skärm')")
    hub = TestClient(
        create_app(
            BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db", web_root=tmp_path / "web"
        )
    )
    for address in ("/skarm", "/skarm/", "/skarm/vilken-sida-som-helst"):
        page = hub.get(address)
        assert page.status_code == 200 and "TrainMeet · Skärm" in page.text, address
        assert "script-src 'self'" in page.headers["content-security-policy"]
        assert page.headers["cache-control"] == "no-cache"
    script = hub.get("/skarm/assets/index-abc.js")
    assert "immutable" in script.headers["cache-control"]
    assert hub.get("/skarm/assets/finns-inte.js").status_code == 404
    assert hub.get("/skarm/../app.py").status_code == 404
    assert hub.get("/static/skarm.js").status_code == 404  # the old page is gone


def test_without_a_built_app_the_hub_says_so(tmp_path: Path) -> None:
    hub = TestClient(
        create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db", web_root=tmp_path)
    )
    assert "npm run build" in hub.get("/skarm").text
