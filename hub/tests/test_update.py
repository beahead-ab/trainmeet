"""Uppdateringen på Pi:n (SYNK-19, SYNK-23) and the Pi's installation (deploy/pi, DRIFT-20,
SYNK-26): Ny version finns, on a button, never during a meet, and only on a Pi installed for it."""

from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import update_api
from hub.app import create_app
from hub.build_info import BuildInfo

PIN = "482915"
MARK = {"X-TrainMeet-Network": "1"}
PI = Path(__file__).resolve().parents[2] / "deploy" / "pi"
READ_LATEST = update_api.fetch_latest


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))
    assert client.post("/api/hub/setup", json={"name": "Pi:n", "pin": PIN}).status_code == 201
    return client


class Release:
    """pi-senaste as the Pi sees it: unreachable until a test says which change it holds."""

    def __init__(self) -> None:
        self.change: str | None = None
        self.asked: list[str] = []

    def fetch(self, url: str) -> str | None:
        self.asked.append(url)
        return self.change


@pytest.fixture(autouse=True)
def release(monkeypatch: pytest.MonkeyPatch) -> Release:
    shown = Release()
    monkeypatch.setattr(update_api, "fetch_latest", shown.fetch)
    return shown


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


def test_the_hub_shows_ny_version_finns(
    tmp_path: Path, release: Release, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SYNK-19: the Pi says when pi-senaste holds another change than the one it runs, reads it
    at most once an hour, and says nothing new without internet."""
    monkeypatch.setenv("TRAINMEET_UPDATE_STATUS", str(tmp_path / "update.json"))
    running = BuildInfo(version="0.1.0", commit="abc123def456")
    app = create_app(running, preview_db=tmp_path / "p.db")
    now = [1000.0]
    app.state.latest.clock = lambda: now[0]
    pi = TestClient(app)
    assert pi.post("/api/hub/setup", json={"name": "Pi:n", "pin": PIN}).status_code == 201

    # No internet: nothing new is said, and it is tried again after five minutes.
    shown = pi.get("/api/hub/update").json()
    assert (shown["latest"], shown["newer"], shown["checked"]) == (None, False, None)
    assert release.asked == [update_api.RELEASE + "/BUILD"]
    release.change = "fedcba987654"
    pi.get("/api/hub/update")
    assert len(release.asked) == 1
    now[0] += update_api.CHECK_AGAIN
    shown = pi.get("/api/hub/update").json()
    assert (shown["build"], shown["latest"], shown["newer"]) == (
        "abc123def456",
        "fedcba987654",
        True,
    )
    assert shown["checked"] is not None

    # Then once an hour; a miss keeps what was seen.
    release.change = None
    now[0] += update_api.CHECK_AGAIN
    assert pi.get("/api/hub/update").json()["latest"] == "fedcba987654"
    assert len(release.asked) == 2
    now[0] += update_api.CHECK_EVERY
    release.change = "abc123def456"
    shown = pi.get("/api/hub/update").json()
    assert (shown["latest"], shown["newer"]) == ("abc123def456", False)


def test_the_latest_change_is_read_with_care(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a change name is believed; anything else, or no answer, says nothing new."""
    bodies = {"/ok/BUILD": b"fedcba987654\n", "/html/BUILD": b"<html>Not Found</html>"}

    class Answer(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = bodies.get(self.path)
            self.send_response(200 if body else 404)
            self.end_headers()
            self.wfile.write(body or b"")

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Answer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        monkeypatch.setenv("TRAINMEET_RELEASE", base + "/ok/")
        assert update_api.latest_source() == base + "/ok/BUILD"
        assert READ_LATEST(update_api.latest_source()) == "fedcba987654"
        assert READ_LATEST(base + "/html/BUILD") is None
        assert READ_LATEST(base + "/missing/BUILD") is None
    finally:
        server.shutdown()
        server.server_close()
    assert READ_LATEST(base + "/ok/BUILD") is None, "no answer at all"
    monkeypatch.delenv("TRAINMEET_RELEASE")
    assert update_api.latest_source() == update_api.RELEASE + "/BUILD"


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
