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
    assert hub.post("/api/hub/login", json={"pin": PIN}).status_code == 409


def test_first_start_names_the_hub_and_logs_in(hub: TestClient) -> None:
    response = hub.post("/api/hub/setup", json={"name": "  Testhubben  Väst ", "pin": PIN})
    assert response.status_code == 201
    session = contract.Session.model_validate(response.json())
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Max-Age=43200" in cookie
    assert info(hub) == contract.HubInfo(name="Testhubben Väst", set_up=True, logged_in=True)
    assert hub.get("/api/version").json()["hub_name"] == "Testhubben Väst"
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
    assert hub.post("/api/hub/login", json={"pin": "000000"}).status_code == 401
    assert info(hub).logged_in is False
    assert hub.post("/api/hub/login", json={"pin": PIN}).status_code == 200
    assert info(hub).logged_in is True


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


def test_own_ai_is_connected_checked_and_its_key_never_shown(
    hub: TestClient, tmp_path: Path
) -> None:
    """Den här hubben → AI (H58, H59, H70), against a stand-in service on this machine: the hub
    checks that the model reads a picture before it keeps the setting, and the key is never
    shown again or written to the hub's log."""
    from integrationer.tests.fake_ai import KEY, FakeAi, serving

    assert hub.get("/api/hub/ai").status_code == 401
    hub.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN})
    assert hub.get("/api/hub/ai").status_code == 404
    with serving() as fake:
        given = {"format": "claude", "address": fake.address + "/", "model": "claude-x", "key": KEY}
        connected = hub.post("/api/hub/ai", json=given)
        assert connected.status_code == 200, connected.text
        seen = contract.AiService.model_validate(connected.json())
        assert (seen.format, seen.address, seen.model, seen.key_set) == (
            contract.AiFormat.CLAUDE,
            fake.address,
            "claude-x",
            True,
        )
        assert seen.checked is not None and len(fake.asked) == 1
        assert KEY not in connected.text and KEY not in hub.get("/api/hub/ai").text
        kept = hub.post("/api/hub/ai", json={**given, "format": "chat", "key": None})
        assert kept.status_code == 200 and kept.json()["format"] == "chat", "the key stays"
        wrong = hub.post("/api/hub/ai", json={**given, "key": "sk-wrong-9876"})
        assert (
            wrong.status_code == 422
            and wrong.json()["detail"] == "AI-tjänsten godtog inte nyckeln."
        )
        assert hub.get("/api/hub/ai").json()["format"] == "chat", "a failed check changes nothing"
    with serving(FakeAi(blind=True)) as blind:
        refused = hub.post("/api/hub/ai", json={**given, "address": blind.address})
        assert refused.status_code == 422 and "läste inte talet" in refused.json()["detail"]
    with sqlite3.connect(tmp_path / "hubben.sqlite3") as db:
        assert db.execute("SELECT key FROM ai").fetchone() == (KEY,), "it stays in the hub"
    assert hub.post("/api/hub/ai/disconnect").status_code == 204
    assert hub.get("/api/hub/ai").status_code == 404
    with sqlite3.connect(tmp_path / "hubben.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM ai").fetchone() == (0,), "and goes with it"
