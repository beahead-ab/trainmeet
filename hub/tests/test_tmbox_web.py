"""TMBox web through the Hub: two tabs join one Provbanan run and drive train 101 together."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from contracts.terminal import Ack, Frame, WebSession
from hub import tmbox_web
from hub.app import create_app
from hub.build_info import BuildInfo


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    return TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "prov.db"))


def started(hub: TestClient) -> str:
    assert hub.post("/api/provbanan/start", json={"version": 1}).status_code == 201
    answer = hub.get("/api/provbanan/clients").json()
    assert answer["clients"] == []
    code = answer["code"]
    assert isinstance(code, str) and len(code) == 6 and code.isdigit()
    return code


class Tab:
    """One browser tab: its own session key, sent as Authorization: Bearer."""

    def __init__(
        self, hub: TestClient, name: str, code: str, display: dict[str, int] | None = None
    ) -> None:
        login: dict[str, Any] = {"name": name, "code": code}
        if display is not None:
            login["display"] = display
        response = hub.post("/api/terminal/session", json=login)
        assert response.status_code == 201, response.text
        session = WebSession.model_validate(response.json())
        self.hub = hub
        self.client_id = session.client_id
        self.headers = {"Authorization": "Bearer " + session.session_key}

    def frame(self) -> dict[str, Any]:
        response = self.hub.get("/api/terminal/frame", headers=self.headers)
        assert response.status_code == 200, response.text
        frame: dict[str, Any] = response.json()
        return frame

    def press(self, key: str, **extra: Any) -> dict[str, Any]:
        body = {"command_id": uuid4().hex, "view_token": self.frame()["view_token"], "key": key}
        response = self.hub.post("/api/terminal/keys", json={**body, **extra}, headers=self.headers)
        assert response.status_code == 200, response.text
        answer: dict[str, Any] = response.json()
        Ack.model_validate(answer)
        assert answer["status"] == "accepted", answer
        return answer

    def number(self, number: str) -> dict[str, Any]:
        context = self.frame()["entry"]["context"]
        return self.press("#", train_number=number, entry_context=context)


def assign(hub: TestClient, tab: Tab, place: str) -> dict[str, Any]:
    response = hub.post(
        "/api/provbanan/clients/assign",
        json={"client_id": tab.client_id, "places": [place], "side": "both"},
    )
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


def test_a_box_announces_its_size_and_the_dispatcher_picks_side_and_language(
    hub: TestClient,
) -> None:
    code = started(hub)
    tall = Tab(hub, "Box 20×4", code, {"rows": 4, "cols": 20})
    small = Tab(hub, "Box 16×2", code)
    assert (tall.frame()["rows"], tall.frame()["cols"]) == (4, 20)
    assert len(tall.frame()["lines"]) == 4
    assert (small.frame()["rows"], small.frame()["cols"]) == (2, 16)
    listed = {c["client_id"]: c for c in hub.get("/api/provbanan/clients").json()["clients"]}
    assert listed[tall.client_id]["display"] == {"rows": 4, "cols": 20}
    assert listed[small.client_id]["language"] == "sv", "the meet's country decides at first"
    response = hub.post(
        "/api/provbanan/clients/assign",
        json={"client_id": tall.client_id, "places": ["asn"], "side": "left", "language": "en"},
    )
    assert response.status_code == 200, response.text
    listed = {c["client_id"]: c for c in response.json()["clients"]}
    assert (listed[tall.client_id]["side"], listed[tall.client_id]["language"]) == ("left", "en")
    frame = tall.frame()
    Frame.model_validate(frame)
    assert frame["language"] == "en"
    assert frame["lines"][3].startswith("No# A:Q")
    for wrong in ({"side": "middle"}, {"language": "xx"}):
        body = {"client_id": small.client_id, "places": ["nby"], **wrong}
        assert hub.post("/api/provbanan/clients/assign", json=body).status_code == 422
    # A size the Hub does not know is a 16×2; the box is never turned away (old Server).
    for odd in ("4x20", {"rows": 4, "cols": 16}, {"rows": "4", "cols": "20"}, [4, 20]):
        response = hub.post(
            "/api/terminal/session", json={"name": "B", "code": code, "display": odd}
        )
        assert response.status_code == 201, odd
        other = Tab.__new__(Tab)
        other.hub, other.client_id = hub, response.json()["client_id"]
        other.headers = {"Authorization": "Bearer " + response.json()["session_key"]}
        assert (other.frame()["rows"], other.frame()["cols"]) == (2, 16), odd


def test_two_tabs_run_train_101_from_request_to_arrival(hub: TestClient) -> None:
    code = started(hub)
    norrby, asen = Tab(hub, "Box 1", code), Tab(hub, "Box 2", code)
    assert norrby.client_id != asen.client_id
    waiting = hub.get("/api/provbanan/clients").json()["clients"]
    assert [c["status"] for c in waiting] == ["waiting", "waiting"]
    assert norrby.frame()["waiting"] is True

    # 1. The dispatcher gives one box Norrby and the other Åsen.
    assign(hub, norrby, "nby")
    listed = assign(hub, asen, "asn")["clients"]
    assert {c["client_id"]: c["places"] for c in listed} == {
        norrby.client_id: ["nby"],
        asen.client_id: ["asn"],
    }
    Frame.model_validate(norrby.frame())
    assert norrby.frame()["lines"][0].strip() == "Norrby"
    assert asen.frame()["lines"][0].strip() == "Åsen"

    # 2. 101# at Norrby asks for clearance; the request shows in Åsen's box.
    norrby.number("101")
    assert "101?Ån" in norrby.frame()["lines"][0]
    assert asen.frame()["lines"][0] == "Nby?101      1/1"

    # 3. Åsen gives clearance, Norrby reports the departure: Åsen sees the train on its way.
    asen.press("#")
    assert "101>Ån" in norrby.frame()["lines"][0]
    norrby.press("#")
    assert "Nby▶101" in asen.frame()["lines"][0]

    # 4. Åsen reports the arrival: both boxes say the case is over, and the section is free.
    asen.press("#")
    assert asen.frame()["lines"][0].startswith("101 ANK SP1")
    assert norrby.frame()["lines"][0].startswith("101 MOTTAGET")
    state = hub.get("/api/provbanan").json()
    case = state["cases"][0]
    assert (case["train"], case["departed"], case["arrived"]) == ("101", True, True)
    leg = next(leg for leg in state["legs"] if leg["departure"]["id"] == "t101-nby")
    assert leg["complete"] is True
    assert state["clock"]["running"] is False


def test_the_provbanan_view_and_the_boxes_share_one_run(hub: TestClient) -> None:
    code = started(hub)
    asen = Tab(hub, "Box Åsen", code)
    assign(hub, asen, "asn")
    state = hub.get("/api/provbanan").json()
    hub.post(
        "/api/provbanan/command",
        json={
            "message_id": uuid4().hex,
            "client_id": "prov-nby",
            "place": "nby",
            "context": state["context"],
            "action": "clearance.request",
            "payload": {"call": "t101-nby", "section": "s-nby-asn", "clearance_id": "c-101"},
        },
    )
    assert asen.frame()["lines"][0] == "Nby?101      1/1"


def test_a_box_needs_its_key(hub: TestClient) -> None:
    started(hub)
    assert hub.get("/api/terminal/frame").status_code == 401
    bad = {"Authorization": "Bearer " + "x" * 40}
    assert hub.get("/api/terminal/frame", headers=bad).status_code == 401


def test_a_wrong_code_finds_no_run(hub: TestClient) -> None:
    code = started(hub)
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    response = hub.post("/api/terminal/session", json={"name": "Box", "code": wrong})
    assert response.status_code == 404


def test_a_box_can_only_be_given_a_place_of_the_run(hub: TestClient) -> None:
    code = started(hub)
    tab = Tab(hub, "Box", code)
    response = hub.post(
        "/api/provbanan/clients/assign",
        json={"client_id": tab.client_id, "places": ["okand"], "side": "both"},
    )
    assert response.status_code == 409


def test_another_browsers_run_cannot_assign_the_box(hub: TestClient, tmp_path: Path) -> None:
    code = started(hub)
    tab = Tab(hub, "Box", code)
    stranger = TestClient(hub.app)
    assert stranger.post("/api/provbanan/start", json={"version": 1}).status_code == 201
    response = stranger.post(
        "/api/provbanan/clients/assign",
        json={"client_id": tab.client_id, "places": ["nby"], "side": "both"},
    )
    assert response.status_code == 404


def test_the_event_stream_sends_the_picture(
    hub: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tmbox_web, "STREAM_SECONDS", 0)
    code = started(hub)
    tab = Tab(hub, "Box", code)
    assign(hub, tab, "nby")
    with hub.stream("GET", "/api/terminal/events", headers=tab.headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())
    event, data = text.strip().split("\n", 1)
    assert event == "event: frame"
    frame = json.loads(data.removeprefix("data: "))
    assert frame["lines"][0].strip() == "Norrby"


def test_the_box_page_keeps_the_key_out_of_addresses(hub: TestClient) -> None:
    page = hub.get("/provbanan/box")
    assert page.status_code == 200
    assert 'src="/static/tmbox.js"' in page.text
    script = hub.get("/static/tmbox.js").text
    assert "sessionStorage" in script
    assert "Authorization" in script
    assert "?key=" not in script and "session_key=" not in script


ROOT = Path(__file__).resolve().parents[2]
FROZEN_START = "/* ===== FRUSET: TMBox-skalet. Ändra inte. ===== */"
FROZEN_END = "/* ===== slut FRUSET ===== */"


def test_the_tmbox_case_is_the_old_servers_frozen_block() -> None:
    """The pink case, the blue display and the keypad look exactly like the physical TMBox.
    The block is the old Server's (terminal16_web/style.css), checked against the same
    golden file. Change it only on a deliberate change to the hardware."""
    css = (ROOT / "hub" / "static" / "tmbox.css").read_text(encoding="utf-8")
    start, end = css.index(FROZEN_START), css.index(FROZEN_END)
    golden = (ROOT / "hub" / "tests" / "tmbox_case_golden.css").read_text(encoding="utf-8")
    assert css[start:end].strip() == golden.strip()
    for selector in ("tmbox-case", "lcd-frame", "lcd", "lcd-row", "lcd-cell", "keypad", "key"):
        assert re.search(rf"\.{selector}(?![\w-])", css[end:]) is None, selector


def test_the_old_palette() -> None:
    golden = (ROOT / "hub" / "tests" / "tmbox_case_golden.css").read_text(encoding="utf-8")
    palette = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-f]+)", golden))
    assert palette == {
        "case": "#b76f80",
        "lcd-blue": "#0c4fe5",
        "lcd-text": "#b9d8ff",
        "key-panel": "#171a21",
        "key": "#090b10",
    }


def test_the_box_is_built_as_the_old_web_box() -> None:
    """tmbox-case > lcd-frame > lcd, and keypad > key ×16 with A–D as function keys."""
    html = (ROOT / "hub" / "page.py").read_text(encoding="utf-8")
    assert '<div class="tmbox-case">' in html
    assert '<div class="lcd-frame"><div id="lcd" class="lcd" role="img"></div></div>' in html
    script = (ROOT / "hub" / "static" / "tmbox.js").read_text(encoding="utf-8")
    assert '"lcd-row"' in script and '"lcd-cell"' in script
    assert '"key" + (/[A-D]/.test(key) ? " function" : "")' in script
