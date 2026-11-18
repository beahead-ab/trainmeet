"""Förarnas API over HTTP (trainmeet.driver/1): Lokföraren on the phone and Förare in Drift.

Ported from the old Server's test_lokforaren.py where the behaviour stays: the driver API needs
the driver's key, a POST from another site is refused, a driver chooses and checks in, the others
see it, what moves a driver is announced, and the photo icon is a small PNG, JPEG or WebP. New:
the QR code instead of an account (LOK-16), the names only on the meet's network or logged in
(LOK-37), the first claim wins (LOK-40), the alarm (LOK-35), and Trafikledningen's and the
lokledare's side (TRAFIK-33, LOK-30).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts import driver as contract
from contracts.drift import Now
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.driver_api import COOKIE

PIN = "482915"
API = "/api/drift/1/drivers"
ON_THE_MEET = ("192.168.4.20", 50000)
CLOUD = ("203.0.113.7", 50000)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
D1 = {"kind": "duty", "id": "d1"}


@pytest.fixture
def made(tmp_path: Path) -> Any:
    return create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db")


@pytest.fixture
def admin(made: Any) -> TestClient:
    """Trafikledningen with the hub's PIN, with Provbanan started as the hub's meet."""
    client = TestClient(made, client=ON_THE_MEET)
    assert client.post("/api/hub/setup", json={"name": "Pi:n", "pin": PIN}).status_code == 201
    assert client.post("/api/drift/1/start", json={"version": 1}).status_code == 201
    return client


def code_of(admin: TestClient) -> str:
    joining = admin.get(API + "/connect")
    assert joining.status_code == 200, joining.text
    found = joining.json()
    assert found["url"].endswith("/lokforaren/#kod=" + found["code"])
    return str(found["code"])


def phone(
    made: Any, admin: TestClient, name: str, level: str = "easy", where: tuple[str, int] = CLOUD
) -> TestClient:
    """A driver's phone that came in with the QR code: the key is in its cookie."""
    client = TestClient(made, client=where)
    joined = client.post(API + "/join", json={"code": code_of(admin), "name": name, "level": level})
    assert joined.status_code == 201, joined.text
    session = contract.DriverSession.model_validate(joined.json())
    assert session.driver.name == name and session.key
    return client


def test_a_driver_comes_in_with_the_qr_code_and_no_account(made: Any, admin: TestClient) -> None:
    """LOK-01, LOK-16: the QR code, a name and a level. On the meet's network the code may be
    left out; over the internet it may not, and a wrong code is no meet."""
    outside = TestClient(made, client=CLOUD)
    assert outside.post(API + "/join", json={"name": "Anna"}).status_code == 422
    assert outside.post(API + "/join", json={"code": "000000", "name": "Anna"}).status_code in {
        404,
        422,
    }
    joined = outside.post(API + "/join", json={"code": code_of(admin), "name": " Anna  Ek "})
    assert joined.status_code == 201
    cookie = joined.headers["set-cookie"]
    assert COOKIE in cookie and "HttpOnly" in cookie and "Path=/api/drift/1/drivers" in cookie
    me = contract.DriverMe.model_validate(outside.get(API + "/me").json())
    assert (me.driver.name, me.driver.initials, me.driver.level, me.service) == (
        "Anna Ek",
        "AE",
        "easy",
        None,
    )
    on_site = TestClient(made, client=ON_THE_MEET)
    assert on_site.post(API + "/join", json={"name": "Bo", "level": "medium"}).status_code == 201
    # A client without cookies sends the key in its header.
    key = joined.json()["key"]
    bare = TestClient(made, client=CLOUD)
    assert bare.get(API + "/me", headers={contract.KEY_HEADER: key}).status_code == 200


def test_the_driver_api_needs_the_key(made: Any, admin: TestClient) -> None:
    nobody = TestClient(made, client=CLOUD)
    for path in ("/me", "/services", "/korplan"):
        assert nobody.get(API + path).status_code == 401, path
    for path, body in (("/claim", D1), ("/checkin", {"place": "nby"}), ("/release", {})):
        assert nobody.post(API + path, json=body).status_code == 401, path
    wrong = {contract.KEY_HEADER: "inte-en-nyckel"}
    assert nobody.get(API + "/me", headers=wrong).status_code == 401


def test_a_driver_post_from_another_site_is_refused(made: Any, admin: TestClient) -> None:
    anna = phone(made, admin, "Anna")
    evil = {"Origin": "https://evil.example"}
    assert anna.post(API + "/claim", json=D1, headers=evil).status_code == 403
    assert anna.post(API + "/checkin", json={"place": "nby"}, headers=evil).status_code == 403


def test_choose_check_in_say_framme_and_tell_trafikledningen(made: Any, admin: TestClient) -> None:
    """The old test choose_activate_and_check_in, with the first claim winning (LOK-40), the
    messages (LOK-23) and Framme (LOK-39)."""
    anna, bo = phone(made, admin, "Anna", "medium"), phone(made, admin, "Bo")
    listed = contract.ServiceList.model_validate(anna.get(API + "/services").json())
    assert [s.number for s in listed.services] == ["1", "5", "2", "3", "4"], "Medel first"
    assert [s["number"] for s in anna.get(API + "/services?q=5").json()["services"]] == ["5"]
    mine = anna.post(API + "/claim", json=D1)
    assert mine.status_code == 200, mine.text
    me = contract.DriverMe.model_validate(mine.json())
    assert me.service is not None and me.service.number == "1"
    assert me.start is not None and me.start.time == "06:00"
    taken = bo.post(API + "/claim", json=D1)
    assert (taken.status_code, taken.json()["detail"], taken.headers["X-Reason"]) == (
        409,
        "Tjänsten är tagen.",
        "service_taken",
    )
    plan = contract.Korplan.model_validate(anna.get(API + "/korplan").json())
    assert (plan.number, len(plan.rows), plan.rows[0].place_name) == ("1", 10, "Norrby")
    checked = anna.post(API + "/checkin", json={"place": "asn", "track": "1"})
    me = contract.DriverMe.model_validate(checked.json())
    assert me.checkin is not None and (me.checkin.place_name, me.checkin.train_number) == (
        "Åsen",
        "101",
    )
    sent = anna.post(API + "/messages", json={"kind": "needs_help"})
    assert sent.status_code == 201
    message = contract.DriverMessage.model_validate(sent.json())
    assert (message.driver_name, message.train_number, message.service_number) == (
        "Anna",
        "101",
        "1",
    )
    seen = Now.model_validate(TestClient(made, client=CLOUD).get("/api/drift/1/now").json())
    assert [(m.kind, m.train_number) for m in seen.driver_messages] == [("needs_help", "101")]
    assert "Anna" not in str(seen.model_dump()), "Nu is open: no names (B13)"
    framme = anna.post(API + "/framme", json={"call": "t101-asn"})
    assert framme.status_code == 200
    log = admin.get("/api/drift/1/log").json()
    assert {"driver.arrived", "driver.message", "driver.checked_in", "service.claimed"} <= {
        e["kind"] for e in log
    }
    assert all(e["kind"] != "train.arrived" for e in log), "Framme is off by default"
    released = contract.DriverMe.model_validate(anna.post(API + "/release", json={}).json())
    assert released.service is None
    assert bo.post(API + "/claim", json=D1).status_code == 200


def test_names_and_photos_only_on_the_meets_network_or_logged_in(
    made: Any, admin: TestClient
) -> None:
    """LOK-37, S8: over the internet without logging in, a driver is no name and no photo; on
    the meet's network, or logged in, the name and the photo. One's own always."""
    anna = phone(made, admin, "Anna Ek")
    assert anna.post(API + "/me/photo", content=PNG).status_code == 200
    me = contract.DriverMe.model_validate(anna.get(API + "/me").json())
    assert me.driver.photo is not None
    photo = me.driver.photo

    def names(client: TestClient) -> list[str | None]:
        return [row["driver"]["name"] for row in client.get(API + "/list").json()]

    looker = TestClient(made, client=CLOUD)
    assert names(looker) == [None]
    assert looker.get(photo).status_code == 404
    assert looker.get(API + "/list").json()[0]["driver"]["photo"] is None
    assert names(TestClient(made, client=ON_THE_MEET)) == ["Anna Ek"]
    shown = TestClient(made, client=ON_THE_MEET).get(photo)
    assert (shown.status_code, shown.content, shown.headers["cache-control"]) == (
        200,
        PNG,
        "private, max-age=300",
    )
    assert looker.post("/api/hub/login", json={"pin": PIN}).status_code == 200
    assert names(looker) == ["Anna Ek"]
    # Her own phone over the internet: her own name and photo, and no one else's.
    bo = phone(made, admin, "Bo")
    assert [(r["driver"]["name"], r["me"]) for r in anna.get(API + "/list").json()] == [
        ("Anna Ek", True),
        (None, False),
    ]
    assert anna.get(photo).status_code == 200
    assert bo.get(photo).status_code == 404


def test_the_photo_is_a_small_png_jpeg_or_webp_and_nothing_else(
    made: Any, admin: TestClient
) -> None:
    anna = phone(made, admin, "Anna")
    assert anna.post(API + "/me/photo", content=JPEG).status_code == 200
    webp = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 16
    assert anna.post(API + "/me/photo", content=webp).status_code == 200
    for bad in (b"<svg onload=alert(1)>", b"<html>", b""):
        assert anna.post(API + "/me/photo", content=bad).status_code == 415
    assert anna.post(API + "/me/photo", content=PNG + b"\x00" * 200_000).status_code == 413
    removed = contract.DriverMe.model_validate(anna.post(API + "/me/photo/remove").json())
    assert removed.driver.photo is None


def test_paus_and_invantar_start_and_the_level(made: Any, admin: TestClient) -> None:
    """LOK-27, LOK-32: the others see Paus or Inväntar start; the level orders the list."""
    anna = phone(made, admin, "Anna")
    changed = anna.post(API + "/me", json={"state": "pause", "level": "experienced"})
    me = contract.DriverMe.model_validate(changed.json())
    assert (me.driver.state, me.driver.level) == ("pause", "experienced")
    assert anna.get(API + "/services").json()["services"][0]["number"] == "3"
    cleared = contract.DriverMe.model_validate(
        anna.post(API + "/me", json={"clear_state": True}).json()
    )
    assert cleared.driver.state is None


def test_what_moves_a_driver_is_announced(made: Any, admin: TestClient) -> None:
    """The phone waits for Drift's next event and reads again (the old /v1/events "drivers")."""
    anna = phone(made, admin, "Anna")
    revision = contract.DriverMe.model_validate(anna.get(API + "/me").json()).revision
    quiet = anna.get(API + "/wait", params={"after": revision, "seconds": 0}).json()
    assert quiet == {"revision": revision, "changed": False}
    for path, body in (("/claim", D1), ("/checkin", {"place": "nby"}), ("/release", {})):
        assert anna.post(API + path, json=body).status_code == 200, path
        woke = contract.DriverWait.model_validate(
            anna.get(API + "/wait", params={"after": revision, "seconds": 0}).json()
        )
        assert woke.changed and woke.revision > revision, path
        revision = woke.revision


def test_the_clock_and_the_trains_come_from_drift(made: Any, admin: TestClient) -> None:
    """LOK-12: the clock is Drift's: the same as Nu, whatever the phone says the time is."""
    looker = TestClient(made, client=CLOUD)
    assert admin.post("/api/drift/1/clock", json={"action": "start"}).status_code == 200
    seen = contract.DriverClock.model_validate(
        looker.get(API + "/clock", headers={"Date": "Mon, 01 Jan 2001 00:00:00 GMT"}).json()
    )
    now = Now.model_validate(looker.get("/api/drift/1/now").json())
    assert (seen.clock.running, seen.clock.speed, seen.traffic_day) == (True, 4.0, now.traffic_day)
    assert abs(seen.clock.seconds - now.clock.seconds) <= 8
    trains = [contract.TrainPosition.model_validate(p) for p in looker.get(API + "/trains").json()]
    assert {(t.train_number, t.state) for t in trains} >= {("101", "planned")}


def test_trafikledningen_sees_hands_out_and_chooses_what_the_drivers_see(
    made: Any, admin: TestClient
) -> None:
    """TRAFIK-33: the drivers, their services and messages; hand out and take back; the game's
    two settings and Framme, off by default."""
    anna, bo = phone(made, admin, "Anna"), phone(made, admin, "Bo")
    assert TestClient(made, client=CLOUD).get(API + "/overview").status_code == 401
    seen = contract.DriverOverview.model_validate(admin.get(API + "/overview").json())
    assert [row.driver.name for row in seen.drivers] == ["Anna", "Bo"]
    assert seen.settings == contract.DriverSettings()
    assert (seen.may_hand_out, seen.may_set) == (True, True)
    anna_id, bo_id = (row.driver.id for row in seen.drivers)
    anna.post(API + "/claim", json=D1)
    handed = admin.post(API + "/hand-out", json={"driver": bo_id, "service": D1})
    assert handed.status_code == 200, handed.text
    rows = {r.driver.name: r for r in contract.DriverOverview.model_validate(handed.json()).drivers}
    assert rows["Anna"].service is None
    service = rows["Bo"].service
    assert service is not None and (service.number, service.driver_name) == ("1", "Bo")
    assert contract.DriverMe.model_validate(bo.get(API + "/me").json()).service is not None
    back = admin.post(API + "/take-back", json={"driver": bo_id})
    assert all(
        r.service is None for r in contract.DriverOverview.model_validate(back.json()).drivers
    )
    assert admin.post(API + "/take-back", json={"driver": anna_id}).status_code == 409
    settings = {"reality": True, "clearances": True, "arrival": True}
    chosen = admin.post(API + "/settings", json=settings)
    assert contract.DriverOverview.model_validate(chosen.json()).settings.model_dump() == settings
    qr = admin.get(API + "/connect.svg")
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg+xml")


def test_released_on_the_line_dispatch_gets_the_alarm(made: Any, admin: TestClient) -> None:
    """LOK-35: the train stands without a driver; Nu shows it, and Förare can clear it."""
    from contracts import station
    from hub.tests.test_station_api import Client  # A TKL at Norrby and one at Åsen.

    anna = phone(made, admin, "Anna")
    anna.post(API + "/claim", json=D1)
    join = admin.get("/api/drift/1/connect").json()["code"]
    norrby, asen = Client(admin, join, ["nby"]), Client(admin, join, ["asn"])
    for tkl, place in ((norrby, "nby"), (asen, "asn")):
        approved = admin.post(
            "/api/drift/1/clients/approve", json={"client_id": tkl.client_id, "places": [place]}
        )
        assert approved.status_code == 200, approved.text
        tkl.poll()
    norrby.command(
        station.Action.CLEARANCE_REQUEST,
        "nby",
        call="t101-nby",
        section="s-nby-asn",
        clearance_id="clr-forare-1",
    )
    asen.command(
        station.Action.CLEARANCE_RESPONSE, "asn", clearance_id="clr-forare-1", approved=True
    )
    norrby.command(station.Action.TRAIN_DEPARTED, "nby", call="t101-nby")
    assert anna.post(API + "/release", json={}).status_code == 200
    (alarm,) = Now.model_validate(admin.get("/api/drift/1/now").json()).driver_alarms
    assert (alarm.number, alarm.train_number, alarm.from_place, alarm.to_place) == (
        "1",
        "101",
        "nby",
        "asn",
    )
    cleared = admin.post(API + "/alarms/clear", json=D1)
    assert contract.DriverOverview.model_validate(cleared.json()).alarms == []
    # The messages reach the TKL at Åsen, the station concerned (DRIFT-38).
    anna.post(API + "/claim", json=D1)
    anna.post(API + "/messages", json={"kind": "engine_trouble"})
    assert [m.kind for m in asen.snapshot("asn").driver_messages] == ["engine_trouble"]


def test_the_lokledare_hands_out_but_does_not_choose_for_the_game(
    made: Any, admin: TestClient
) -> None:
    """LOK-30: a role per meet, from ID or let in with a one-time code from Förare. The lokledare
    sees the drivers and hands out services, and runs no traffic."""
    phone(made, admin, "Anna")
    given = admin.post("/api/drift/1/codes", json={"name": "Lokledaren", "role": "loco_lead"})
    assert given.status_code == 201 and given.json()["role"] == "loco_lead"
    lead = TestClient(made, client=CLOUD)
    assert lead.post("/api/hub/login/code", json={"code": given.json()["code"]}).status_code == 200
    assert lead.get("/api/hub").json()["meet_role"] == "loco_lead"
    seen = contract.DriverOverview.model_validate(lead.get(API + "/overview").json())
    assert (seen.may_hand_out, seen.may_set, seen.drivers[0].driver.name) == (True, False, "Anna")
    anna_id = seen.drivers[0].driver.id
    handed = lead.post(API + "/hand-out", json={"driver": anna_id, "service": D1})
    assert handed.status_code == 200
    claimed = [e for e in admin.get("/api/drift/1/log").json() if e["kind"] == "service.claimed"]
    assert claimed[0]["actor"]["kind"] == "loco_lead"
    assert lead.post(API + "/settings", json={"reality": True}).status_code == 403
    assert lead.post("/api/drift/1/clock", json={"action": "start"}).status_code in {401, 403}
    assert lead.get("/api/drift/1/clients").status_code in {401, 403}


def test_the_key_is_never_written_out(made: Any, admin: TestClient, tmp_path: Path) -> None:
    """LOK-16: only the hash of the key is in the hub's files."""
    joined = TestClient(made, client=CLOUD).post(
        API + "/join", json={"code": code_of(admin), "name": "Anna"}
    )
    key = joined.json()["key"]
    found = b"".join(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    assert key.encode() not in found
    assert hashlib.sha256(key.encode()).hexdigest().encode() in found
