"""TMBox web boxes and station clients on one run, ported from the old Server's
test_shared_traffic.py. There an ESP8266 box, an ESP32 box and TKL shared one clearance; here a
web box and a TKL do, through the terminal protocol and the station protocol."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts import station
from drift.store import PreviewStore
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.tests.test_station_api import Client, approve
from hub.tests.test_tmbox_web import Tab, assign, started

Action = station.Action


class Run:
    """A box at Norrby, and a TKL at Åsen and Mellanå."""

    def __init__(self, hub: TestClient) -> None:
        code = started(hub)
        self.hub = hub
        self.norrby = Tab(hub, "Box Norrby", code)
        assign(hub, self.norrby, "nby")
        self.tkl = Client(hub, code, ["asn", "mla"])
        approve(hub, self.tkl, ["asn", "mla"])
        self.tkl.poll()

    def box_requests_101(self) -> str:
        self.norrby.number("101")
        (case,) = self.tkl.snapshot("asn").clearances
        return case.clearance_id

    def answer(self, clearance: str) -> station.Reply:
        reply = self.tkl.command(
            Action.CLEARANCE_RESPONSE, "asn", clearance_id=clearance, approved=True
        )
        assert reply.status == station.ReplyStatus.ACCEPTED, reply
        return reply


@pytest.fixture
def run(tmp_path: Path) -> Run:
    return Run(TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db")))


def test_box_requests_tkl_answers_box_departs_tkl_takes_it_in(run: Run) -> None:
    clearance = run.box_requests_101()
    run.answer(clearance)
    assert "101>Ån" in run.norrby.frame()["lines"][0]
    run.norrby.press("#")  # Rapportera avgång.
    seen = run.tkl.snapshot("asn")
    assert [t.call for t in seen.on_the_way] == ["t101-asn"]
    assert next(s for s in seen.sections if s.section == "s-nby-asn").occupied
    arrived = run.tkl.command(Action.TRAIN_ARRIVED, "asn", call="t101-asn")
    assert arrived.status == station.ReplyStatus.ACCEPTED
    assert arrived.snapshot.clearances == []
    assert run.norrby.frame()["lines"][0].startswith("101 MOTTAGET")


def test_an_arrival_never_reported_departed_finishes_the_train(run: Run) -> None:
    """Since 2.1.0 the receiver can take in a cleared train whose sender forgot to report it
    departed: it jumps there, and the line is free."""
    run.answer(run.box_requests_101())
    reply = run.tkl.command(Action.TRAIN_ARRIVED, "asn", call="t101-asn")
    assert reply.status == station.ReplyStatus.ACCEPTED
    assert reply.snapshot.clearances == []
    call = next(c for c in reply.snapshot.calls if c.call == "t101-asn")
    assert call.arrival_state == station.ArrivalState.ARRIVED
    assert "101 MOTTAGET" in run.norrby.frame()["lines"][0]


def test_an_approved_case_can_be_cancelled_but_a_departed_one_cannot(run: Run) -> None:
    run.tkl.command(
        Action.CLEARANCE_REQUEST, "asn", call="t101-asn", section="s-asn-mla", clearance_id="c-1"
    )
    run.tkl.command(Action.CLEARANCE_RESPONSE, "mla", clearance_id="c-1", approved=True)
    assert run.tkl.command(Action.CLEARANCE_CANCEL, "asn", clearance_id="c-1").status == (
        station.ReplyStatus.ACCEPTED
    )
    run.tkl.command(
        Action.CLEARANCE_REQUEST, "asn", call="t101-asn", section="s-asn-mla", clearance_id="c-2"
    )
    run.tkl.command(Action.CLEARANCE_RESPONSE, "mla", clearance_id="c-2", approved=True)
    run.tkl.command(Action.TRAIN_DEPARTED, "asn", call="t101-asn")
    late = run.tkl.command(Action.CLEARANCE_CANCEL, "asn", clearance_id="c-2")
    assert (late.status, late.reason) == (station.ReplyStatus.REJECTED, "train_already_departed")


def test_the_box_confirmation_goes_stale_when_the_case_is_cancelled(run: Run) -> None:
    """The box's picture said "#Avg"; the case is gone before # is pressed. The old picture
    cannot act any more, and nothing departs."""
    clearance = run.box_requests_101()
    run.answer(clearance)
    old = run.norrby.frame()
    assert old["keys"]["#"]["label"] == "Rapportera avgång"
    refused = run.tkl.command(Action.CLEARANCE_CANCEL, "asn", clearance_id=clearance)
    assert refused.reason == "not_sender", "only Norrby may take its request back"
    run.norrby.press("*")  # Återta klartecken…
    run.norrby.press("#")  # Bekräfta återtagning.
    stale = run.hub.post(
        "/api/terminal/keys",
        json={"command_id": "late-departure", "view_token": old["view_token"], "key": "#"},
        headers=run.norrby.headers,
    ).json()
    assert stale["status"] == "rejected"
    assert run.tkl.snapshot("asn").clearances == []
    assert run.tkl.snapshot("asn").on_the_way == []


def test_opposite_trains_share_the_double_track_between_a_box_and_a_tkl(run: Run) -> None:
    code = run.hub.get("/api/provbanan/clients").json()["code"]
    asen = Tab(run.hub, "Box Åsen", code)
    # The box for Mellanå's side: 101# asks Mellanå at once (a box for both sides would
    # first offer to move 101 here, since nobody sent it from Norrby).
    response = run.hub.post(
        "/api/provbanan/clients/assign",
        json={"client_id": asen.client_id, "places": ["asn"], "side": "right"},
    )
    assert response.status_code == 200
    asen.number("101")
    opposite = run.tkl.command(
        Action.CLEARANCE_REQUEST, "mla", call="t102-mla", section="s-asn-mla", clearance_id="c-102"
    )
    assert opposite.status == station.ReplyStatus.ACCEPTED, "the double track has two channels"
    assert len(opposite.snapshot.clearances) == 2
    assert asen.frame()["requests"]["count"] == 1, "102 waits under A at Åsen"


def test_simultaneous_requests_from_two_clients_have_one_winner(tmp_path: Path) -> None:
    hub = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))
    code = started(hub)
    clients = [Client(hub, code, ["nby"]) for _ in range(2)]
    for client in clients:
        approve(hub, client, ["nby"])
        client.poll()

    def ask(client: Client) -> Any:
        return client.post(
            Action.CLEARANCE_REQUEST,
            "nby",
            None,
            call="t101-nby",
            section="s-nby-asn",
            clearance_id=f"c-{client.client_id}",
        ).json()["status"]

    with ThreadPoolExecutor(2) as pool:
        results = sorted(pool.map(ask, clients))
    assert results == ["accepted", "rejected"]
    assert len(clients[0].snapshot("nby").clearances) == 1


def test_a_failed_write_keeps_neither_the_reply_nor_the_request(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The request and its receipt are one transaction: a disk that fails keeps neither, and
    the same message can be sent again."""

    def broken(*_: object) -> None:
        raise RuntimeError("disken svarar inte")

    monkeypatch.setattr(PreviewStore, "_save", staticmethod(broken))
    payload = {"call": "t101-asn", "section": "s-asn-mla", "clearance_id": "c-1"}
    with pytest.raises(RuntimeError):
        run.tkl.post(Action.CLEARANCE_REQUEST, "asn", "the-same-message", **payload)
    monkeypatch.undo()
    assert run.tkl.snapshot("asn").clearances == []
    again = run.tkl.command(Action.CLEARANCE_REQUEST, "asn", "the-same-message", **payload)
    assert again.status == station.ReplyStatus.ACCEPTED, "not a duplicate of nothing"
