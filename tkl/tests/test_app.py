"""TKL on its own, without a hub: första start, the PIN lock (TKL18, KLAR-21), the list at level
0 and its versions (TKL21, TKL25), and TKL in the cloud with one station per browser."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts.tkl import TklMode
from tkl.app import create_app

API = "/api/tkl/1"
PIN = "4711"
NOWHERE: list[str] = []


def tkl(tmp_path: Path, mode: TklMode = TklMode.LOCAL, **given: Any) -> TestClient:
    given.setdefault("discover", lambda: NOWHERE)
    return TestClient(create_app(tmp_path, mode=mode, **given))


def set_up(client: TestClient, name: str = "Exempelby", station_id: str = "exb") -> Any:
    return client.post(API + "/setup", json={"name": name, "station_id": station_id, "pin": PIN})


def test_first_start_locks_with_a_pin(tmp_path: Path) -> None:
    client = tkl(tmp_path)
    state = client.get(API + "/state").json()
    assert (state["set_up"], state["unlocked"], state["mode"]) == (False, False, "local")
    assert client.get(API + "/studio").status_code == 401
    made = set_up(client)
    assert made.status_code == 201, made.text
    assert made.json()["station"] == {
        "station_id": "exb",
        "name": "Exempelby",
        "level": 0,
        "tried": False,
    }
    assert made.json()["unlocked"] is True
    assert set_up(client).status_code == 409, "one station on the computer"
    # Locked: the PIN opens it again; a wrong one does not.
    assert client.post(API + "/lock").json()["unlocked"] is False
    assert client.get(API + "/studio").status_code == 401
    assert client.post(API + "/unlock", json={"pin": "0000"}).status_code == 401
    assert client.post(API + "/unlock", json={"pin": "12"}).status_code == 422, "minst fyra"
    assert client.post(API + "/unlock", json={"pin": PIN}).json()["unlocked"] is True
    # Byt PIN: the old one first.
    assert client.post(API + "/pin", json={"old": "0000", "new": "8642"}).status_code == 401
    assert client.post(API + "/pin", json={"old": PIN, "new": "8642"}).status_code == 204
    assert client.post(API + "/lock").status_code == 200
    assert client.post(API + "/unlock", json={"pin": PIN}).status_code == 401
    assert client.post(API + "/unlock", json={"pin": "8642"}).status_code == 200


def test_guessing_the_pin_stays_slow(tmp_path: Path) -> None:
    client = tkl(tmp_path)
    set_up(client)
    client.post(API + "/lock")
    for _ in range(10):
        assert client.post(API + "/unlock", json={"pin": "0000"}).status_code == 401
    assert client.post(API + "/unlock", json={"pin": PIN}).status_code == 429


def test_the_list_at_level_0_and_its_versions(tmp_path: Path) -> None:
    """KLAR-01, TKL21, TKL25: tracks and exits as a list, saved on the computer; Ny version av
    utsidan makes the next version, and the same list again makes none."""
    client = tkl(tmp_path)
    set_up(client)
    studio = client.get(API + "/studio").json()
    assert [t["id"] for t in studio["draft"]["tracks"]] == ["1", "2"]
    assert [(e["id"], e["side"]) for e in studio["draft"]["exits"]] == [
        ("A", "left"),
        ("B", "right"),
    ]
    assert (studio["versions"], studio["changed"]) == ([], True)
    outside = {
        "station_id": "something-else",
        "name": "Annat namn",
        "tracks": [{"id": "1", "label": "Spår 1"}, {"id": "3a", "label": "Spår 3a"}],
        "exits": [
            {"id": "A", "side": "left", "name": "Mot Västby"},
            {"id": "BU", "side": "right", "name": "Östby uppspår"},
        ],
    }
    saved = client.put(API + "/studio", json=outside).json()
    assert (saved["draft"]["station_id"], saved["draft"]["name"]) == ("exb", "Exempelby")
    first = client.post(API + "/studio/version").json()
    assert [v["number"] for v in first["versions"]] == [1] and first["changed"] is False
    again = client.post(API + "/studio/version").json()
    assert [v["number"] for v in again["versions"]] == [1]
    twice = {**outside, "exits": [*outside["exits"], {"id": "A", "side": "right"}]}
    assert client.put(API + "/studio", json=twice).status_code == 422, "two exits named A"


def test_not_connected_says_so(tmp_path: Path) -> None:
    client = tkl(tmp_path)
    set_up(client)
    assert client.get(API + "/connection").json() == {
        "connected": False,
        "address": None,
        "hub_name": None,
        "status": None,
        "places": [],
        "place": None,
        "parts": [],
        "outside_version": None,
        "message": None,
        "preview": False,
        "relayed": False,
    }
    assert client.get(API + "/places/exb").status_code == 409
    assert client.get(API + "/hubs").json() == []
    bad = client.post(API + "/connection", json={"address": "file:///etc/passwd"})
    assert bad.status_code == 422


def test_in_the_cloud_each_browser_has_its_station(tmp_path: Path) -> None:
    """TKL in the cloud without TrainMeet ID (#76): a station per browser, and only the hubs TKL
    is set up for. With ID the station belongs to the account (tests/test_tkl_moln.py)."""
    cloud = create_app(
        tmp_path, mode=TklMode.CLOUD, over_internet=["https://hub.invalid"], discover=lambda: []
    )
    one, two = TestClient(cloud), TestClient(cloud)
    assert set_up(one, "Västby", "vby").status_code == 201
    assert two.get(API + "/state").json()["set_up"] is False
    assert set_up(two, "Östby", "oby").status_code == 201
    assert one.get(API + "/state").json()["station"]["name"] == "Västby"
    assert two.get(API + "/state").json()["station"]["name"] == "Östby"
    assert two.post(API + "/unlock", json={"pin": PIN}).status_code == 200
    elsewhere = one.post(API + "/connection", json={"address": "http://hub:8080"})
    assert elsewhere.status_code == 422, "never an address someone types, in the cloud"
    # A stranger without the station's cookie has nothing to unlock.
    assert TestClient(cloud).post(API + "/unlock", json={"pin": PIN}).status_code == 404


def test_changes_come_from_tkls_own_page(tmp_path: Path) -> None:
    client = tkl(tmp_path)
    set_up(client)
    other = client.post(API + "/lock", headers={"Origin": "https://example.invalid"})
    assert other.status_code == 403


@pytest.mark.parametrize("path", ["/", "/stallverket", "/studio"])
def test_the_web_app_or_a_note_that_it_is_not_built(
    tmp_path: Path, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    web = tmp_path / "web"
    monkeypatch.setenv("TKL_WEB_DIR", str(web))
    client = tkl(tmp_path)
    assert client.get(path).status_code == 503
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>TKL</title>", encoding="utf-8")
    assert "<title>TKL</title>" in client.get(path).text
    assert client.get("/api/tkl/1/nothing").status_code == 404
