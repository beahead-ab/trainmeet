"""Uppdateringen på Pi:n (SYNK-23) and the Pi's installation (deploy/pi, DRIFT-20, SYNK-26):
on a button, never during a meet, and only on a Pi installed for it."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import update_api
from hub.app import create_app
from hub.build_info import BuildInfo

PIN = "482915"
MARK = {"X-TrainMeet-Network": "1"}
PI = Path(__file__).resolve().parents[2] / "deploy" / "pi"


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))
    assert client.post("/api/hub/setup", json={"name": "Pi:n", "pin": PIN}).status_code == 201
    return client


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []
    monkeypatch.setattr(update_api, "start_service", lambda: calls.append(True))
    return calls


def test_the_hub_in_the_cloud_is_updated_by_its_deploy(
    hub: TestClient, started: list[bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRAINMEET_UPDATE_STATUS", raising=False)
    shown = hub.get("/api/hub/update").json()
    assert not shown["available"] and "molnet" in shown["reason"]
    assert hub.post("/api/hub/update", headers=MARK).status_code == 409
    assert started == []


def test_a_pi_updates_on_the_button_and_says_how_it_went(
    hub: TestClient, started: list[bool], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status = tmp_path / "update.json"
    monkeypatch.setenv("TRAINMEET_UPDATE_STATUS", str(status))
    assert hub.get("/api/hub/update").json()["state"] is None
    assert TestClient(hub.app).post("/api/hub/update", headers=MARK).status_code == 401
    assert hub.post("/api/hub/update").status_code == 403
    assert hub.post("/api/hub/update", headers=MARK).status_code == 200
    assert started == [True]
    status.write_text(
        json.dumps(
            {"status": "done", "message": "Hubben kör version abc", "at": "2026-11-16T07:00:00Z"}
        )
    )
    shown = hub.get("/api/hub/update").json()
    assert (shown["available"], shown["state"], shown["message"]) == (
        True,
        "done",
        "Hubben kör version abc",
    )


def test_never_during_a_meet(
    hub: TestClient, started: list[bool], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRAINMEET_UPDATE_STATUS", str(tmp_path / "update.json"))
    assert hub.post("/api/drift/1/start", json={"version": 1}).status_code == 201
    assert hub.post("/api/drift/1/clock", json={"action": "start"}).status_code == 200
    assert hub.get("/api/hub/update").json()["meet_running"]
    refused = hub.post("/api/hub/update", headers=MARK)
    assert refused.status_code == 409 and "träff pågår" in refused.json()["detail"]
    assert started == []
    # The clock stands: now it may.
    assert hub.post("/api/drift/1/clock", json={"action": "stop"}).status_code == 200
    assert hub.post("/api/hub/update", headers=MARK).status_code == 200


# --- The Pi's installation, read as it is shipped ----------------------------------------------


def test_the_install_script_is_valid_and_careful() -> None:
    script = (PI / "install.sh").read_text()
    subprocess.run(["sh", "-n", str(PI / "install.sh")], check=True)
    assert "sha256sum -c" in script, "a package that did not come whole is never installed"
    assert "--require-hashes" in script, "only the locked dependencies"
    assert "systemctl is-active --quiet NetworkManager.service" in script
    assert "network-manager" not in script.lower().replace("networkmanager", "")
    assert "/healthz" in script and "PREVIOUS" in script, "a version that does not answer goes back"


def test_the_services_are_locked_down() -> None:
    hub_unit = (PI / "trainmeet-hub.service").read_text()
    assert "User=trainmeet" in hub_unit and "ProtectSystem=strict" in hub_unit
    assert "CapabilityBoundingSet=CAP_NET_BIND_SERVICE" in hub_unit
    network = (PI / "trainmeet-network.service").read_text()
    assert "RestrictAddressFamilies=AF_UNIX" in network and "ProtectSystem=strict" in network
    assert "python -m synk.network_host" in network
    rule = (PI / "50-trainmeet-update.rules").read_text()
    assert '"trainmeet-update.service"' in rule and '"start"' in rule


def test_the_usb_stick_is_mounted_where_the_hub_looks() -> None:
    settings = dict(
        line.split("=", 1)
        for line in (PI / "hub.env").read_text().splitlines()
        if line and not line.startswith("#")
    )
    assert settings["TRAINMEET_USB_DIR"] in (PI / "90-trainmeet-usb.rules").read_text()
    assert settings["TRAINMEET_UPDATE_STATUS"].startswith("/var/lib/trainmeet/")
    script = (PI / "install.sh").read_text()
    assert "STATE=/var/lib/trainmeet" in script and 'STATUS="$STATE/update.json"' in script
