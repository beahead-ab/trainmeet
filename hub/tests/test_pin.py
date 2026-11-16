"""På den här hubben (SYNK-07): the hub's name and its PIN, and a forgotten PIN with physical
access to the hub, a command or a file on a USB stick (H46, SYNK-27)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contracts import hub as contract
from hub import pin as forgotten
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.local import LocalLogin

PIN = "482915"
NEW = "735190"


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "prov.db"))
    assert client.post("/api/hub/setup", json={"name": "Testhubben", "pin": PIN}).status_code == 201
    return client


def logged_in(hub: TestClient) -> bool:
    return bool(contract.HubInfo.model_validate(hub.get("/api/hub").json()).logged_in)


def test_the_administrator_renames_the_hub(hub: TestClient) -> None:
    assert TestClient(hub.app).post("/api/hub/name", json={"name": "Pi:n"}).status_code == 401
    renamed = hub.post("/api/hub/name", json={"name": "  Pi:n   hemma "})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Pi:n hemma"
    assert hub.get("/api/version").json()["hub_name"] == "Pi:n hemma"
    assert hub.post("/api/hub/name", json={"name": "   "}).status_code == 422


def test_a_new_pin_ends_every_other_login(hub: TestClient) -> None:
    other = TestClient(hub.app)
    assert other.post("/api/hub/login", json={"pin": PIN}).status_code == 200
    assert logged_in(other)
    wrong = hub.post("/api/hub/pin", json={"pin": "111111", "new_pin": NEW})
    assert wrong.status_code == 403 and "nuvarande" in wrong.json()["detail"]
    assert hub.post("/api/hub/pin", json={"pin": PIN, "new_pin": "12"}).status_code == 422
    assert hub.post("/api/hub/pin", json={"pin": PIN, "new_pin": NEW}).status_code == 204
    # The one who changed it stays logged in; the other session is gone.
    assert logged_in(hub) and not logged_in(other)
    assert other.post("/api/hub/login", json={"pin": PIN}).status_code == 401
    assert other.post("/api/hub/login", json={"pin": NEW}).status_code == 200
    assert (
        TestClient(hub.app).post("/api/hub/pin", json={"pin": NEW, "new_pin": PIN}).status_code
        == 401
    )


def test_a_forgotten_pin_is_set_with_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    login = LocalLogin(tmp_path / "hubben.sqlite3", "Hubben")
    login.set_up("Pi:n", PIN)
    session = login.log_in(PIN)
    answers = iter([NEW, NEW])
    assert forgotten.main(lambda _: next(answers), tmp_path) == 0
    assert "PIN-koden är bytt" in capsys.readouterr().out
    assert not login.valid(session)
    assert login.log_in(NEW)
    differ = iter([PIN, "999999"])
    assert forgotten.main(lambda _: next(differ), tmp_path) == 1
    short = iter(["12", "12"])
    assert forgotten.main(lambda _: next(short), tmp_path) == 1
    assert login.log_in(NEW)
    out = capsys.readouterr()
    assert NEW not in out.out + out.err and PIN not in out.out + out.err


def test_a_forgotten_pin_is_set_with_a_file_on_the_usb_stick(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    login = LocalLogin(tmp_path / "hubben.sqlite3", "Hubben")
    login.set_up("Pi:n", PIN)
    usb = tmp_path / "usb"
    usb.mkdir()
    assert not forgotten.take_pin_file(usb, login)  # no file, nothing happens
    (usb / forgotten.FILE).write_text(f"{NEW}\n")
    assert forgotten.take_pin_file(usb, login)
    # The PIN is not left on the stick, and the stick says it worked.
    assert not (usb / forgotten.FILE).exists()
    assert "PIN-koden är bytt" in (usb / forgotten.DONE).read_text()
    assert login.log_in(NEW)
    (usb / forgotten.FILE).write_text("abc\n")
    assert not forgotten.take_pin_file(usb, login)
    assert not (usb / forgotten.FILE).exists()
    assert "6–12 siffror" in (usb / forgotten.FAILED).read_text()
    assert login.log_in(NEW)
    assert NEW not in caplog.text and "abc" not in caplog.text
