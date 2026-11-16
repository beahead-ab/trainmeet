"""Pi:ns nät through the hub (SYNK-26, H45), ported with the old Server's HTTP tests
(tests/test_pi_network_http.py): only the administrator, only from the hub's own page, a change
only on the Pi itself or over HTTPS, and never a password back."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hub.app import create_app
from hub.build_info import BuildInfo
from synk import network
from synk.tests.test_network import MEET, FakeNetwork

PIN = "482915"
MARK = {"X-TrainMeet-Network": "1"}


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> FakeNetwork:
    fake = FakeNetwork()
    controller = network.NetworkController(fake)
    monkeypatch.setattr(network, "host_request", controller.handle)
    return fake


def hub_at(tmp_path: Path, base: str) -> TestClient:
    app = create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "prov.db")
    return TestClient(app, base_url=base)


def logged_in(client: TestClient) -> TestClient:
    assert client.post("/api/hub/setup", json={"name": "Pi:n", "pin": PIN}).status_code == 201
    return client


def test_only_the_administrator_and_not_during_setup(tmp_path: Path, backend: FakeNetwork) -> None:
    hub = hub_at(tmp_path, "https://pi.local")
    assert hub.get("/api/hub/wifi").status_code == 401
    save = {"ssid": "Test", "security": "open"}
    assert hub.post("/api/hub/wifi/save", json=save, headers=MARK).status_code == 401
    assert backend.calls == []


def test_the_administrator_manages_the_pis_net_over_https(
    tmp_path: Path, backend: FakeNetwork
) -> None:
    hub = logged_in(hub_at(tmp_path, "https://pi.local"))
    shown = hub.get("/api/hub/wifi").json()
    assert shown["supported"] and shown["can_manage"]
    assert [p["ssid"] for p in shown["profiles"]] == ["Hemma", "Träffens nät"]
    saved = hub.post(
        "/api/hub/wifi/save",
        json={"ssid": "Klubben", "security": "wpa2", "password": "private-test-password"},
        headers=MARK,
    )
    assert saved.status_code == 200, saved.text
    assert "private-test-password" not in saved.text and "password" not in saved.text
    assert "Klubben" in [p["ssid"] for p in saved.json()["profiles"]]
    # Anslut nu: a trial of 90 seconds, kept by the one who started it.
    tried = hub.post(
        "/api/hub/wifi/connect", json={"uuid": MEET, "interface": "wlan0"}, headers=MARK
    )
    trial = tried.json()["trial"]
    assert 85 <= trial["remaining"] <= 90 and trial["token"]
    kept = hub.post("/api/hub/wifi/confirm", json={"token": trial["token"]}, headers=MARK)
    assert kept.status_code == 200 and kept.json()["trial"] is None
    assert backend.connected("wlan0", MEET)
    refused = hub.post("/api/hub/wifi/delete", json={"uuid": MEET}, headers=MARK)
    assert refused.status_code == 409 and "aktiva" in refused.json()["detail"]


@pytest.mark.parametrize(
    "extra",
    [
        {"X-TrainMeet-Network": ""},
        {"Origin": "https://attacker.invalid"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_a_change_from_another_site_is_refused(
    tmp_path: Path, backend: FakeNetwork, extra: dict[str, str]
) -> None:
    hub = logged_in(hub_at(tmp_path, "https://pi.local"))
    response = hub.post(
        "/api/hub/wifi/scan", json={"interface": "wlan0"}, headers={**MARK, **extra}
    )
    assert response.status_code == 403
    assert backend.calls == []


def test_over_plain_http_from_another_machine_it_is_only_read(
    tmp_path: Path, backend: FakeNetwork
) -> None:
    hub = logged_in(hub_at(tmp_path, "http://pi.local"))
    shown = hub.get("/api/hub/wifi").json()
    assert shown["supported"] and not shown["can_manage"]
    save = {"ssid": "Klubben", "security": "wpa2", "password": "private-test-password"}
    refused = hub.post("/api/hub/wifi/save", json=save, headers=MARK)
    assert refused.status_code == 403 and "HTTPS" in refused.json()["detail"]
    assert "Klubben" not in json.dumps(backend.profiles)


def test_a_hub_without_the_helper_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = network.host_request
    nowhere = str(tmp_path / "ingen.sock")

    def without(action: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        return real(action, payload, actor, path=nowhere)

    monkeypatch.setattr(network, "host_request", without)
    hub = logged_in(hub_at(tmp_path, "https://moln.example"))
    shown = hub.get("/api/hub/wifi").json()
    assert not shown["supported"] and not shown["can_manage"]
    assert "Raspberry Pi" in shown["reason"]
    refused = hub.post("/api/hub/wifi/scan", json={"interface": "wlan0"}, headers=MARK)
    assert refused.status_code == 503
