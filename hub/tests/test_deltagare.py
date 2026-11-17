"""Deltagarna (DELT-01–DELT-20): träffens Wi-Fi under the gear, and what the participant page may
show the one who looks (S1, S8). Over the internet, without logging in, only the traffic; on the
meet's network, or logged in, also träffens Wi-Fi."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import deltagare
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.local import MeetWifi

PIN = "482915"
ON_THE_MEET = ("192.168.4.20", 50000)
CLOUD = ("203.0.113.7", 50000)
PROXIED = {"X-Forwarded-For": "203.0.113.7"}


@pytest.fixture
def app(tmp_path: Path) -> object:
    made = create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db")
    admin = TestClient(made, client=ON_THE_MEET)
    assert admin.post("/api/hub/setup", json={"name": "Pi:n", "pin": PIN}).status_code == 201
    response = admin.post(
        "/api/hub/meet-wifi", json={"name": 'Träff; "ÅÄÖ"', "password": "test-only:secret"}
    )
    assert response.status_code == 200, response.text
    return made


def visitor(app: object, client: tuple[str, int], **headers: str) -> TestClient:
    return TestClient(app, client=client, headers=headers)  # type: ignore[arg-type]


def test_over_the_internet_only_the_traffic(app: object) -> None:
    """S8: without logging in, over the internet, the Wi-Fi is not shown, and its QR code is
    refused. The traffic itself is open to everyone (S1)."""
    for outside in (visitor(app, CLOUD), visitor(app, ON_THE_MEET, **PROXIED)):
        shown = outside.get("/api/deltagare").json()
        assert (shown["full"], shown["logged_in"], shown["wifi"]) == (False, False, None)
        assert outside.get("/api/deltagare/wifi.svg").status_code == 403
        assert outside.get("/api/drift/1/package").status_code in {200, 404}
    # Logged in over the internet: all of it.
    outside = visitor(app, CLOUD)
    assert outside.post("/api/hub/login", json={"pin": PIN}).status_code == 200
    shown = outside.get("/api/deltagare").json()
    assert (shown["full"], shown["logged_in"]) == (True, True)
    assert shown["wifi"]["password"] == "test-only:secret"


def test_on_the_meets_network_the_wifi_is_shared(app: object) -> None:
    """DELT-02, DELT-03: on the meet's network the page shows träffens Wi-Fi, so a box or a phone
    can join it, and its QR code as the old Server wrote it."""
    on_site = visitor(app, ON_THE_MEET)
    shown = on_site.get("/api/deltagare").json()
    assert shown["full"] is True and shown["logged_in"] is False
    assert shown["wifi"] == {"name": 'Träff; "ÅÄÖ"', "open": False, "password": "test-only:secret"}
    qr = on_site.get("/api/deltagare/wifi.svg")
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg+xml")
    meet = on_site.get("/api/deltagare/traffen.svg", params={"address": "http://trainmeet.local/"})
    assert meet.status_code == 200
    assert (
        on_site.get("/api/deltagare/traffen.svg", params={"address": "javascript:alert(1)"})
    ).status_code == 422


def test_the_wifi_qr_is_what_a_phone_joins_with() -> None:
    """The payloads of the old Server (server-ui.js), with \\ ; , " and : escaped."""
    assert (
        deltagare.wifi_qr(MeetWifi(name='Träff; "ÅÄÖ"', open=False, password="test-only:secret"))
        == 'WIFI:T:WPA;S:Träff\\; \\"ÅÄÖ\\";P:test-only\\:secret;;'
    )
    assert deltagare.wifi_qr(MeetWifi(name="Öppet", open=True)) == "WIFI:T:nopass;S:Öppet;;"


def test_the_meet_wifi_is_set_under_the_gear_and_never_sent_back(app: object) -> None:
    admin = visitor(app, ON_THE_MEET)
    assert TestClient(app, client=ON_THE_MEET).get("/api/hub/meet-wifi").status_code == 401  # type: ignore[arg-type]
    assert admin.post("/api/hub/login", json={"pin": PIN}).status_code == 200
    seen = admin.get("/api/hub/meet-wifi").json()
    assert seen == {"name": 'Träff; "ÅÄÖ"', "open": False, "has_password": True}
    assert "test-only" not in admin.get("/api/hub/meet-wifi").text
    # A new name keeps the password; a short one is refused; another site may not change it.
    assert admin.post("/api/hub/meet-wifi", json={"name": "Grimslöv"}).json()["has_password"]
    short = admin.post("/api/hub/meet-wifi", json={"name": "Grimslöv", "password": "kort"})
    assert short.status_code == 422
    elsewhere = admin.post(
        "/api/hub/meet-wifi", json={"name": "X"}, headers={"Origin": "https://example.invalid"}
    )
    assert elsewhere.status_code == 403
    # An open network has no password; no name means träffens Wi-Fi is not shared.
    opened = admin.post("/api/hub/meet-wifi", json={"name": "Öppet", "open": True}).json()
    assert opened == {"name": "Öppet", "open": True, "has_password": False}
    assert visitor(app, ON_THE_MEET).get("/api/deltagare").json()["wifi"]["password"] is None
    assert admin.post("/api/hub/meet-wifi", json={"name": ""}).json()["name"] == ""
    assert visitor(app, ON_THE_MEET).get("/api/deltagare").json()["wifi"] is None
    assert visitor(app, ON_THE_MEET).get("/api/deltagare/wifi.svg").status_code == 404
    # An open network that gets a password back needs one typed again.
    again = admin.post("/api/hub/meet-wifi", json={"name": "Grimslöv"})
    assert again.status_code == 422


def test_the_meets_network_is_a_private_address_with_no_proxy() -> None:
    """The old Server's test for public clients: private, link-local or loopback, straight."""

    class Seen:
        def __init__(self, host: str, headers: dict[str, str] | None = None) -> None:
            self.client = type("C", (), {"host": host})()
            self.headers = headers or {}

    near = ("192.168.1.10", "10.0.0.2", "172.16.5.1", "169.254.3.3", "127.0.0.1", "::1", "fd00::5")
    for host in near:
        assert deltagare.on_meet_network(Seen(host)), host  # type: ignore[arg-type]
    for host in ("203.0.113.7", "8.8.8.8", "2001:db8::1", "testclient", ""):
        assert not deltagare.on_meet_network(Seen(host)), host  # type: ignore[arg-type]
    for proxy in ("x-forwarded-for", "forwarded", "x-real-ip", "x-forwarded-host"):
        assert not deltagare.on_meet_network(Seen("10.0.0.2", {proxy: "x"}))  # type: ignore[arg-type]
