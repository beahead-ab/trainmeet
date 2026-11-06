"""First start, logging in and out (H52, S1). The PIN is never stored or shown."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contracts import hub as contract
from hub import local
from hub.app import create_app
from hub.build_info import BuildInfo

PIN = "482915"


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    return TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "prov.db"))


def info(hub: TestClient) -> contract.HubInfo:
    return contract.HubInfo.model_validate(hub.get("/api/hub").json())


def test_a_new_hub_asks_for_a_name_and_a_pin(hub: TestClient) -> None:
    assert info(hub) == contract.HubInfo(name="Hubben", set_up=False, logged_in=False)
    page = hub.get("/").text
    assert 'id="setup-form"' in page and 'id="login-form"' not in page
    assert hub.post("/api/hub/login", json={"pin": PIN}).status_code == 409


def test_first_start_names_the_hub_and_logs_in(hub: TestClient) -> None:
    response = hub.post("/api/hub/setup", json={"name": "  Testhubben  Väst ", "pin": PIN})
    assert response.status_code == 201
    session = contract.Session.model_validate(response.json())
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Max-Age=43200" in cookie
    assert info(hub) == contract.HubInfo(name="Testhubben Väst", set_up=True, logged_in=True)
    assert "Testhubben Väst" in hub.get("/").text
    assert "Testhubben Väst" in hub.get("/provbanan").text, "every page has the name"
    # The key works as Bearer too, for the Drift API.
    other = TestClient(hub.app)
    headers = {"Authorization": "Bearer " + session.session_key}
    assert other.get("/api/hub", headers=headers).json()["logged_in"] is True


def test_first_start_happens_once(hub: TestClient) -> None:
    hub.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN})
    again = TestClient(hub.app).post("/api/hub/setup", json={"name": "Min", "pin": "111111"})
    assert again.status_code == 409
    assert info(hub).name == "Hubben"


@pytest.mark.parametrize("pin", ["12345", "1234567890123", "abcdef", "12 345"])
def test_a_pin_is_six_to_twelve_digits(hub: TestClient, pin: str) -> None:
    assert hub.post("/api/hub/setup", json={"name": "Hubben", "pin": pin}).status_code == 422
    assert info(hub).set_up is False


def test_log_out_and_in_again(hub: TestClient) -> None:
    hub.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN})
    assert hub.post("/api/hub/logout").status_code == 204
    assert info(hub).logged_in is False
    assert 'id="login-form"' in hub.get("/").text
    assert hub.post("/api/hub/login", json={"pin": "000000"}).status_code == 401
    assert info(hub).logged_in is False
    assert hub.post("/api/hub/login", json={"pin": PIN}).status_code == 200
    assert info(hub).logged_in is True
    assert 'id="logout"' in hub.get("/").text


def test_a_logged_out_key_stops_working(hub: TestClient) -> None:
    key = hub.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN}).json()["session_key"]
    headers = {"Authorization": "Bearer " + key}
    assert hub.post("/api/hub/logout", headers=headers).status_code == 204
    assert TestClient(hub.app).get("/api/hub", headers=headers).json()["logged_in"] is False


def test_guessing_is_slowed_for_the_whole_hub(hub: TestClient) -> None:
    hub.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN})
    hub.post("/api/hub/logout")
    for guess in range(local.MAX_FAILURES):
        assert hub.post("/api/hub/login", json={"pin": f"{guess:06d}"}).status_code == 401
    assert hub.post("/api/hub/login", json={"pin": PIN}).status_code == 429, "even the right one"


def test_the_pin_is_never_stored(hub: TestClient, tmp_path: Path) -> None:
    key = hub.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN}).json()["session_key"]
    raw = (tmp_path / "hubben.sqlite3").read_bytes()
    assert PIN.encode() not in raw and key.encode() not in raw
    with sqlite3.connect(tmp_path / "hubben.sqlite3") as db:
        (stored,) = db.execute("SELECT pin_hash FROM hub").fetchone()
    assert len(stored) == 32


def test_a_session_expires(hub: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    hub.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN})
    later = local._now() + local.SESSION_LIFETIME
    monkeypatch.setattr(local, "_now", lambda: later)
    assert info(hub).logged_in is False
