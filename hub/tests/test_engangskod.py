"""Släpp in med engångskod (H56, KONTO-19, F18): the dispatcher gives six digits under Klienter;
they work once, for 15 minutes, and give at most the dispatcher's own role, in the meet that
runs, until it ends or the dispatcher takes the role away. The hub keeps only a hash."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts import hub as contract
from contracts.id import MeetRole
from hub import local
from hub.app import create_app
from hub.build_info import BuildInfo

PIN = "482915"
CODES = "/api/drift/1/codes"


@pytest.fixture
def made(tmp_path: Path) -> Any:
    return create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db")


@pytest.fixture
def admin(made: Any) -> TestClient:
    """The one with the hub's PIN, with the hub's own meet started."""
    client = TestClient(made)
    assert client.post("/api/hub/setup", json={"name": "Pi:n", "pin": PIN}).status_code == 201
    assert client.post("/api/drift/1/start", json={"version": 1}).status_code == 201
    return client


def info(client: TestClient) -> contract.HubInfo:
    return contract.HubInfo.model_validate(client.get("/api/hub").json())


def give(client: TestClient, name: str | None = None) -> contract.OneTimeCode:
    answer = client.post(CODES, json={"name": name} if name else {})
    assert answer.status_code == 201, answer.text
    return contract.OneTimeCode.model_validate(answer.json())


def let_in(made: Any, code: str) -> TestClient:
    client = TestClient(made)
    answer = client.post("/api/hub/login/code", json={"code": code})
    assert answer.status_code == 200, answer.text
    return client


def test_the_dispatcher_lets_someone_in_with_a_code(made: Any, admin: TestClient) -> None:
    assert info(admin) == contract.HubInfo(
        name="Pi:n", set_up=True, logged_in=True, admin=True, may_run=True
    )
    given = give(admin, "  Sjövik,   Anna ")
    assert len(given.code) == 6 and given.code.isdigit()
    assert given.role == MeetRole.DISPATCHER
    assert timedelta(minutes=14) < given.expires - datetime.now(UTC) <= timedelta(minutes=15)

    stranger = TestClient(made)
    assert info(stranger).logged_in is False
    answer = stranger.post("/api/hub/login/code", json={"code": given.code})
    assert answer.status_code == 200, answer.text
    cookie = answer.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Max-Age=604800" in cookie
    seen = info(stranger)
    assert (seen.logged_in, seen.admin, seen.meet_role) == (True, False, MeetRole.DISPATCHER)
    assert seen.may_run is True
    assert stranger.get("/api/deltagare").json()["logged_in"] is True

    # Trafikledare: runs the traffic, and may let the next one in.
    assert stranger.get("/api/drift/1/clients").status_code == 200
    assert stranger.get("/api/drift/1/connect").status_code == 200
    assert stranger.post("/api/drift/1/clock", json={"action": "start"}).status_code == 200
    assert give(stranger).role == MeetRole.DISPATCHER

    # Never the hub's own settings, the plan, another meet or a take-over (H18).
    assert stranger.post("/api/hub/name", json={"name": "Min"}).status_code == 401
    assert stranger.get("/api/hub/ai").status_code == 401
    assert stranger.post("/api/drift/1/start", json={"version": 1}).status_code == 401
    assert stranger.post("/api/drift/1/takeover", json={"confirm": "x"}).status_code == 401
    assert stranger.get("/api/hub/meet-wifi").status_code == 401

    # The list says who is in and since when, never the code.
    listed = stranger.get("/api/drift/1/let-in")
    assert listed.status_code == 200
    people = [contract.LetIn.model_validate(found) for found in listed.json()]
    assert [(p.name, p.role) for p in people] == [("Sjövik, Anna", MeetRole.DISPATCHER)]
    assert people[0].until - people[0].since == timedelta(days=7)
    assert given.code not in listed.text


def test_a_code_works_once(made: Any, admin: TestClient) -> None:
    given = give(admin)
    let_in(made, given.code)
    again = TestClient(made).post("/api/hub/login/code", json={"code": given.code})
    assert again.status_code == 401
    assert again.json()["detail"] == (
        "Koden stämmer inte, eller har gått ut. Be trafikledningen om en ny."
    )


def test_a_code_lasts_15_minutes(
    made: Any, admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    given = give(admin)
    later = datetime.now(UTC) + timedelta(minutes=15, seconds=1)
    monkeypatch.setattr(local, "_now", lambda: later)
    gone = TestClient(made).post("/api/hub/login/code", json={"code": given.code})
    assert gone.status_code == 401


def test_the_dispatcher_takes_the_role_away(made: Any, admin: TestClient) -> None:
    other = let_in(made, give(admin, "Åsen").code)
    person = admin.get("/api/drift/1/let-in").json()[0]["person"]
    assert admin.post(f"/api/drift/1/let-in/{person}/remove").status_code == 204
    assert info(other).logged_in is False
    assert other.get("/api/drift/1/clients").status_code == 401
    assert admin.get("/api/drift/1/let-in").json() == []
    assert admin.post(f"/api/drift/1/let-in/{person}/remove").status_code == 404
    assert admin.post("/api/drift/1/let-in/inte-ett-id/remove").status_code == 404


def test_the_role_ends_with_the_meet(made: Any, admin: TestClient) -> None:
    other = let_in(made, give(admin).code)
    unused = give(admin)
    # Byt träff: a new run. The let-in role and the unused code belonged to the old one.
    assert admin.post("/api/drift/1/start", json={"version": 1}).status_code == 201
    assert info(other).logged_in is False
    assert other.get("/api/drift/1/clients").status_code == 401
    assert admin.get("/api/drift/1/let-in").json() == []
    assert TestClient(made).post("/api/hub/login/code", json={"code": unused.code}).status_code == (
        401
    )
    # The administrator's own login holds in every meet.
    assert info(admin).admin is True


def test_wrong_codes_count_like_wrong_pins(made: Any, admin: TestClient) -> None:
    given = give(admin)
    guesser = TestClient(made)
    wrong = "000000" if given.code != "000000" else "111111"
    for _ in range(local.MAX_FAILURES):
        assert guesser.post("/api/hub/login/code", json={"code": wrong}).status_code == 401
    stopped = guesser.post("/api/hub/login/code", json={"code": given.code})
    assert stopped.status_code == 429
    assert guesser.post("/api/hub/login/code", json={"code": "12345"}).status_code == 422


def test_without_a_meet_there_is_no_code(made: Any) -> None:
    client = TestClient(made)
    assert client.post(CODES, json={}).status_code == 401
    assert client.post("/api/hub/setup", json={"name": "Pi:n", "pin": PIN}).status_code == 201
    if client.get("/api/drift/1/clients").status_code == 200:
        pytest.skip("the hub starts with a meet running")
    assert client.post(CODES, json={}).status_code == 404
    refused = TestClient(made).post("/api/hub/login/code", json={"code": "123456"})
    assert refused.status_code == 409


def test_a_hub_from_before_keeps_its_logins(tmp_path: Path) -> None:
    """Sessions from before the one-time code have no role: they are the administrator's."""
    path = tmp_path / "hubben.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE session (token_hash TEXT PRIMARY KEY, expires REAL NOT NULL)")
        db.execute(
            "INSERT INTO session VALUES (?, ?)",
            (local._token_hash("gammal"), (datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        )
    db.close()
    login = local.LocalLogin(path, "Hubben")
    assert login.valid("gammal") is True
    assert login.role("gammal", "en-träff") == local.ADMIN
