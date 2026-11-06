"""Provbanan through the Hub, including the old Server's shared clearance cases."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from drift import store
from hub import provbanan
from hub.app import create_app

API = "/api/provbanan"


def start(client: TestClient) -> dict[str, Any]:
    response = client.post(API + "/start", json={"version": 1})
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


def command(
    client: TestClient,
    state: dict[str, Any],
    place: str,
    action: str,
    payload: dict[str, object],
    message_id: str | None = None,
) -> Response:
    response = client.post(
        API + "/command",
        json={
            "message_id": message_id or uuid4().hex,
            "client_id": f"box-{place}",
            "place": place,
            "context": state["context"],
            "action": action,
            "payload": payload,
        },
    )
    return cast(Response, response)


def request(
    client: TestClient,
    state: dict[str, Any],
    call: str,
    case: str,
    message_id: str | None = None,
) -> Response:
    leg = next(leg for leg in state["legs"] if leg["departure"]["id"] == call)
    return command(
        client,
        state,
        leg["departure"]["place"],
        "clearance.request",
        {"call": call, "section": leg["section"], "clearance_id": case},
        message_id,
    )


def reply(
    client: TestClient,
    state: dict[str, Any],
    case: str,
    place: str,
    approved: bool,
) -> Response:
    return command(
        client,
        state,
        place,
        "clearance.response",
        {
            "clearance_id": case,
            "approved": approved,
        },
    )


def test_provbanan_is_linked_and_each_browser_has_its_own_run(tmp_path: Path) -> None:
    app = create_app(preview_db=tmp_path / "drift.sqlite3")
    a, b = TestClient(app), TestClient(app)
    assert 'href="/provbanan"' in a.get("/").text
    assert "Starta provkörning" in a.get("/provbanan").text
    assert a.get("/static/provbanan.js").status_code == 200
    assert a.get(API).status_code == 404
    first = start(a)
    second = start(b)
    assert len({leg["train"] for leg in first["legs"]}) == 10
    assert first["traffic_day"] == "mon"
    assert not first["clock"]["running"]
    assert request(a, first, "t101-nby", "norrby-1").status_code == 200
    assert b.get(API).json()["cases"] == second["cases"] == []
    assert a.get(API).headers["cache-control"] == "no-store"


def test_requested_clearance_waits_for_the_neighbour_and_arrival_releases_section(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(preview_db=tmp_path / "drift.sqlite3"))
    state = start(client)
    assert request(client, state, "t101-nby", "case-1", "same-message").status_code == 200
    before = client.get(API).json()
    assert before["cases"][0]["status"] == "waiting"
    assert request(client, state, "t101-nby", "case-1", "same-message").json() == before
    assert request(client, state, "t101-nby", "another-case").status_code == 409
    assert request(client, state, "t103-nby", "case-3").status_code == 409
    assert reply(client, state, "case-1", "nby", True).status_code == 409
    assert command(client, state, "nby", "train.departed", {"call": "t101-nby"}).status_code == 409
    assert reply(client, state, "case-1", "asn", True).json()["cases"][0]["status"] == "approved"
    departure = command(client, state, "nby", "train.departed", {"call": "t101-nby"})
    assert departure.json()["cases"][0]["departed"]
    assert (
        command(client, state, "nby", "clearance.cancel", {"clearance_id": "case-1"}).status_code
        == 409
    )
    arrival = command(client, state, "asn", "train.arrived", {"call": "t101-asn"})
    assert arrival.json()["cases"][0]["arrived"]
    assert request(client, state, "t103-nby", "case-4").status_code == 200


def test_direct_clearance_does_not_wait_for_confirmation(tmp_path: Path) -> None:
    client = TestClient(create_app(preview_db=tmp_path / "drift.sqlite3"))
    state = start(client)
    result = request(client, state, "t102-sjv", "case-direct")
    assert result.json()["cases"][0]["status"] == "approved"
    assert command(client, state, "sjv", "train.departed", {"call": "t102-sjv"}).status_code == 200
    assert command(client, state, "mla", "train.arrived", {"call": "t102-mla"}).status_code == 200


def test_denial_and_cancellation_release_the_section(tmp_path: Path) -> None:
    client = TestClient(create_app(preview_db=tmp_path / "drift.sqlite3"))
    state = start(client)
    assert request(client, state, "t101-nby", "denied").status_code == 200
    assert reply(client, state, "denied", "asn", False).json()["cases"][0]["status"] == "rejected"
    assert request(client, state, "t101-nby", "cancelled").status_code == 200
    cancelled = command(client, state, "nby", "clearance.cancel", {"clearance_id": "cancelled"})
    assert cancelled.json()["cases"][1]["status"] == "cancelled"
    assert request(client, state, "t103-nby", "available").status_code == 200


def test_two_simultaneous_requests_on_one_channel_have_one_winner(tmp_path: Path) -> None:
    client = TestClient(create_app(preview_db=tmp_path / "drift.sqlite3"))
    state = start(client)
    with ThreadPoolExecutor(2) as executor:
        first = executor.submit(request, client, state, "t101-nby", "first")
        second = executor.submit(request, client, state, "t103-nby", "second")
    assert sorted((first.result().status_code, second.result().status_code)) == [200, 409]
    assert len(client.get(API).json()["cases"]) == 1


def test_restart_restores_the_case_and_leaves_the_clock_stopped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 11, 6, 10, tzinfo=UTC)

    def current_time() -> datetime:
        return now

    monkeypatch.setattr(store, "now_utc", current_time)
    monkeypatch.setattr(provbanan, "now_utc", current_time)
    db = tmp_path / "drift.sqlite3"
    client = TestClient(create_app(preview_db=db))
    state = start(client)
    assert client.post(API + "/clock", json={"action": "start"}).json()["clock"]["running"]
    now += timedelta(seconds=30)
    result = client.post(API + "/clock", json={"action": "speed", "speed": 2})
    assert result.json()["clock"]["time"] == "06:02"
    now += timedelta(seconds=30)
    assert request(client, state, "t101-nby", "keep", "remember-message").status_code == 200
    now += timedelta(hours=1)
    restarted = TestClient(create_app(preview_db=db), cookies=client.cookies)
    restored = restarted.get(API).json()
    assert restored["cases"][0]["status"] == "waiting"
    assert restored["clock"]["time"] == "06:03"
    assert not restored["clock"]["running"]
    assert request(restarted, state, "t101-nby", "keep", "remember-message").json() == restored
    assert reply(restarted, state, "keep", "asn", True).status_code == 200


def test_opposite_trains_can_use_the_double_track_at_the_same_time(tmp_path: Path) -> None:
    client = TestClient(create_app(preview_db=tmp_path / "drift.sqlite3"))
    state = start(client)
    assert request(client, state, "t101-nby", "west-in").status_code == 200
    assert reply(client, state, "west-in", "asn", True).status_code == 200
    assert command(client, state, "nby", "train.departed", {"call": "t101-nby"}).status_code == 200
    assert command(client, state, "asn", "train.arrived", {"call": "t101-asn"}).status_code == 200
    assert request(client, state, "t102-sjv", "east-in").status_code == 200
    assert command(client, state, "sjv", "train.departed", {"call": "t102-sjv"}).status_code == 200
    assert command(client, state, "mla", "train.arrived", {"call": "t102-mla"}).status_code == 200
    assert request(client, state, "t101-asn", "eastbound").status_code == 200
    assert request(client, state, "t102-mla", "westbound").status_code == 200
