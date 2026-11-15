"""Trafikledningen (TRAFIK-21): the start page and Nu, Klienter and Logg are the app
apps/trafikledning, served by the hub; what the pages show is tested in the app. Here: the
addresses, and what Logg reads from Driftens API (B15)."""

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


def test_trafikledning_is_the_app_on_its_addresses(tmp_path: Path) -> None:
    """/, Provbanan and Drift's pages get the app's index.html; Provbanan's boxes, Planering and
    the API keep their own addresses."""
    built = tmp_path / "web"
    for folder, title in (("trafikledning", "Trafikledningen"), ("tmbox-webb", "TMBox")):
        (built / folder).mkdir(parents=True)
        (built / folder / "index.html").write_text(f"<!doctype html><title>{title}</title>")
    hub = TestClient(
        create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db", web_root=built)
    )
    for address in ("/", "/provbanan", "/drift", "/drift/", "/drift/klienter", "/drift/logg"):
        page = hub.get(address)
        assert page.status_code == 200 and "Trafikledningen" in page.text, address
        assert "script-src 'self'" in page.headers["content-security-policy"]
    assert "TMBox" in hub.get("/provbanan/box").text
    assert hub.get("/planering").status_code == 200
    assert "Trafikledningen" not in hub.get("/planering").text
    assert hub.get("/api/hub").json()["set_up"] is False
    assert hub.get("/healthz").text == "ok"
    for old in ("/static/drift.js", "/static/hubben.js", "/static/provbanan.js"):
        assert hub.get(old).status_code == 404, old  # the old pages are gone


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
