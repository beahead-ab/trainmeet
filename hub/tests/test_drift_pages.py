"""Trafikledningens sidor (steg 3): the same pages for everyone, the buttons only when logged
in (S1); the header with the meet, the clock, Anslut and Väntar (S2); Nu, Klienter, Logg (S6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contracts import drift
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.tests.test_station_api import Client
from hub.tests.test_tmbox_web import Tab

PIN = "482915"
API = "/api/drift/1"


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "prov.db"))
    client.post("/api/hub/setup", json={"name": "Hubben <i>Väst</i>", "pin": PIN})
    client.post(API + "/start", json={"version": 1})
    return client


def test_everyone_sees_nu_and_only_the_administrator_the_buttons(hub: TestClient) -> None:
    looking = TestClient(hub.app).get("/drift").text
    assert 'data-admin="nej"' in looking and 'id="clock-toggle"' not in looking
    assert 'id="connect"' not in looking and 'id="waiting"' not in looking
    assert 'href="/">Logga in' in looking
    running = hub.get("/drift").text
    assert 'data-admin="ja"' in running
    for part in ('id="clock-toggle"', 'id="connect"', 'id="waiting"', 'id="logout"', "Byt träff"):
        assert part in running, part
    assert "Hubben &lt;i&gt;Väst&lt;/i&gt;" in running, "the hub's name is never markup"


@pytest.mark.parametrize("path", ["/drift/klienter", "/drift/logg"])
def test_klienter_and_logg_ask_for_the_login(hub: TestClient, path: str) -> None:
    looking = TestClient(hub.app).get(path).text
    assert "Logga in med" in looking and 'id="clients"' not in looking and 'id="log"' not in looking
    assert ('id="clients"' in hub.get(path).text) or ('id="log"' in hub.get(path).text)


def test_the_tabs_mark_the_page(hub: TestClient) -> None:
    for path in ("/drift", "/drift/klienter", "/drift/logg"):
        text = hub.get(path).text
        assert f'<a href="{path}" aria-current=page>' in text


def test_a_box_refused_a_press_is_in_the_log(hub: TestClient) -> None:
    code = hub.get(API + "/connect").json()["code"]
    box = Tab(hub, "Box Norrby", code)
    hub.post(API + "/clients/assign", json={"client_id": box.client_id, "places": ["nby"]})
    response = hub.post(
        "/api/terminal/keys",
        json={"command_id": "old", "view_token": "x" * 24, "key": "#"},
        headers=box.headers,
    )
    assert response.json()["status"] == "rejected"
    (refusal,) = [drift.Refusal.model_validate(r) for r in hub.get(API + "/refusals").json()]
    assert (refusal.client_id, refusal.place, refusal.what) == (box.client_id, "nby", "knapp #")
    assert refusal.message.startswith("Läget ändrades")
    assert TestClient(hub.app).get(API + "/refusals").status_code == 401


def test_a_tkl_refused_a_command_is_in_the_log_with_the_reason(hub: TestClient) -> None:
    code = hub.get(API + "/connect").json()["code"]
    tkl = Client(hub, code, ["nby"])
    hub.post(API + "/clients/approve", json={"client_id": tkl.client_id, "places": ["nby"]})
    tkl.poll()
    from contracts import station

    tkl.command(station.Action.TRAIN_DEPARTED, call="t101-nby")
    (refusal,) = hub.get(API + "/refusals").json()
    assert (refusal["what"], refusal["reason"]) == ("train.departed", "departure_not_reserved")
    assert refusal["message"] == "Tåget saknar beviljad klarering."


def test_the_start_page_leads_to_the_meet(hub: TestClient) -> None:
    assert 'href="/drift">Kör träffen' in hub.get("/").text
    assert 'href="/drift">Se träffen' in TestClient(hub.app).get("/").text
