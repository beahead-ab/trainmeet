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
    digital = hub.post(
        API + "/clients/view", json={"client_id": client_id, "view": "clock_digital"}
    )
    assert digital.status_code == 200
    assert picture(hub, headers).view == screen.ScreenView.CLOCK_DIGITAL, "the two styles (H74)"


def test_the_clock_has_the_qr_codes_and_the_wifi_only_on_the_meets_network(
    hub: TestClient,
) -> None:
    """SKARM-18: 1 · Wi-Fi and 2 · Träffen in the clock's corner. The Wi-Fi code only for a
    screen on the meet's network (S8); the other views have no codes."""
    client_id, headers = join(hub)
    hub.post(API + "/clients/view", json={"client_id": client_id, "view": "clock"})
    assert picture(hub, headers).share == screen.ScreenShare(
        wifi=False, link="http://testserver/"
    ), "no Wi-Fi entered yet"
    assert hub.post("/api/hub/meet-wifi", json={"name": "Träffen", "open": True}).status_code == 200
    on_site = TestClient(hub.app, client=("192.168.4.30", 50000))
    near = screen.ScreenPicture.model_validate(
        on_site.get("/api/screen/picture", headers=headers).json()
    )
    assert near.share is not None and near.share.wifi is True
    over_internet = TestClient(hub.app, client=("192.168.4.30", 50000))
    far = screen.ScreenPicture.model_validate(
        over_internet.get(
            "/api/screen/picture", headers={**headers, "X-Forwarded-For": "8.8.8.8"}
        ).json()
    )
    assert far.share is not None and far.share.wifi is False
    hub.post(API + "/clients/view", json={"client_id": client_id, "view": "tracks"})
    assert picture(hub, headers).share is None


def test_banoversikten_gets_the_meet_as_it_runs_and_the_package(hub: TestClient) -> None:
    """SKARM-09: the views that draw the line get Nu with the picture and the package once; the
    package's key changes with a driftändring."""
    client_id, headers = join(hub)
    assert picture(hub, headers).now is None, "not before it has a view"
    hub.post(API + "/clients/view", json={"client_id": client_id, "view": "clock"})
    assert picture(hub, headers).now is None, "the clock needs only the time"
    hub.post(API + "/clients/view", json={"client_id": client_id, "view": "tracks"})
    seen = picture(hub, headers)
    assert seen.view == screen.ScreenView.TRACKS and seen.now is not None and seen.package
    assert {leg.train_number for leg in seen.now.legs} >= {"101", "102"}
    drawn = TestClient(hub.app).get("/api/screen/package", headers=headers)
    assert drawn.status_code == 200 and drawn.json()["meet"]["name"] == "Provbanan"
    assert TestClient(hub.app).get("/api/screen/package").status_code == 401
    for view in ("graph", "overview"):
        hub.post(API + "/clients/view", json={"client_id": client_id, "view": view})
        assert picture(hub, headers).now is not None, f"{view} draws on the meet as it runs"
    cancel = {"change": {"kind": "cancel", "train": "t108"}}
    assert hub.post(API + "/changes", json=cancel).status_code == 200
    assert picture(hub, headers).package != seen.package, "fetched again after a driftändring"


def test_only_the_administrator_gives_a_view(hub: TestClient) -> None:
    client_id, _ = join(hub)
    body = {"client_id": client_id, "view": "clock"}
    assert TestClient(hub.app).post(API + "/clients/view", json=body).status_code == 401
    assert (
        hub.post(API + "/clients/view", json={"client_id": "screen-x", "view": "clock"}).status_code
        == 404
    )
    assert hub.post(API + "/clients/view", json={**body, "view": "karta"}).status_code == 422


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
