"""STV-10 with the real hub: TKL at level 2 is B at Åsen in Provbanan, as in the level-0 test
(tests/test_tkl_klarering.py). Train 102 comes from Mellanå: TKL puts it on the line at its
exit by its call, sets the entry route, runs it in with Kör and presses Ankommit, and Hubben
has the train in on track 2. Cleared towards Norrby, TKL sets the route out, Drift takes the exit
signal's proceed at level 2 (DRIFT-10), and TKL runs the train out on the line, and Norrby sees
it on its way. Only the station protocol is between them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from contracts import station
from contracts.station_model import to_json
from contracts.tkl import TklAnswer, TklMode, TklReportKind
from hub.app import create_app as create_hub
from hub.build_info import BuildInfo
from hub.tests.test_tmbox_web import started
from tkl.app import create_app as create_tkl
from tkl.tests.provstation import provby

API = "/api/tkl/1"
S = API + "/stallverk"
HUB = "http://testserver"


class Client:
    """A neighbour: a client of the station protocol, approved for its place."""

    def __init__(self, hub: TestClient, code: str, place: str) -> None:
        body = {"kind": "tmbox_app", "name": place, "software": "prov", "code": code}
        self.hub, self.place = hub, place
        self.client_id = hub.post("/api/station/1/connect", json=body).json()["client_id"]
        hub.post(
            "/api/provbanan/clients/approve",
            json={"client_id": self.client_id, "places": [place]},
        )
        key = hub.get(f"/api/station/1/connect/{self.client_id}").json()["key"]
        self.headers = {"Authorization": "Bearer " + key}

    def seen(self) -> station.Snapshot:
        answer = self.hub.get(f"/api/station/1/places/{self.place}", headers=self.headers)
        return station.Snapshot.model_validate(answer.json())

    def send(self, action: station.Action, **payload: Any) -> station.Reply:
        body = {
            "message_id": uuid4().hex,
            "client_id": self.client_id,
            "place": self.place,
            "context": self.seen().context.model_dump(mode="json"),
            "action": action.value,
            "payload": payload,
        }
        answer = self.hub.post("/api/station/1/commands", json=body, headers=self.headers)
        return station.Reply.model_validate(answer.json())


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    return TestClient(create_hub(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))


def b_sees(tkl: TestClient) -> station.Snapshot:
    view = tkl.get(API + "/places/asn")
    assert view.status_code == 200, view.text
    return station.Snapshot.model_validate(view.json()["snapshot"])


def b_sends(tkl: TestClient, action: station.Action, **payload: Any) -> station.Reply:
    body = {
        "message_id": uuid4().hex,
        "place": "asn",
        "context": b_sees(tkl).context.model_dump(mode="json"),
        "action": action.value,
        "payload": payload,
    }
    answer = tkl.post(API + "/commands", json=body)
    assert answer.status_code == 200, answer.text
    return station.Reply.model_validate(answer.json())


def operate(tkl: TestClient, path: str, **body: Any) -> TklAnswer:
    answer = tkl.post(S + path, json=body)
    assert answer.status_code == 200, answer.text
    found = TklAnswer.model_validate(answer.json())
    assert found.accepted, found.message
    return found


def test_a_train_in_and_out_through_the_interlocking(hub: TestClient, tmp_path: Path) -> None:
    tkl = TestClient(
        create_tkl(tmp_path / "tkl", mode=TklMode.LOCAL, http=lambda: hub, discover=lambda: [])
    )
    made = tkl.post(API + "/setup", json={"name": "Åsen", "station_id": "asen", "pin": "4711"})
    assert made.status_code == 201, made.text
    # The made-up station as Åsen's model: tracks 1 and 2, the exits v (west) and o (east).
    model = provby()
    exits = [e.model_copy(update={"outside_id": e.id.lower()}) for e in model.line_exits]
    imported = tkl.put(
        API + "/studio/model", content=to_json(model.model_copy(update={"line_exits": exits}))
    )
    assert imported.status_code == 200, imported.text
    code = started(hub)
    assert tkl.post(API + "/connection", json={"address": HUB, "code": code}).status_code == 200
    [b] = [c for c in hub.get("/api/provbanan/clients").json()["clients"] if c["kind"] == "tkl"]
    hub.post(
        "/api/provbanan/clients/approve", json={"client_id": b["client_id"], "places": ["asn"]}
    )
    # Mellanå asks for 102 to Åsen; Åsen gives clearance in Klarering, as at level 0.
    mellana = Client(hub, code, "mla")
    asked = mellana.send(
        station.Action.CLEARANCE_REQUEST, call="t102-mla", section="s-asn-mla", clearance_id="c1"
    )
    assert asked.status == station.ReplyStatus.ACCEPTED, asked.message
    [request] = [c for c in b_sees(tkl).clearances if c.to_place == "asn"]
    given = b_sends(
        tkl, station.Action.CLEARANCE_RESPONSE, clearance_id=request.clearance_id, approved=True
    )
    assert given.status == station.ReplyStatus.ACCEPTED, given.message
    assert mellana.send(station.Action.TRAIN_DEPARTED, call="t102-mla").status == "accepted"
    [coming] = b_sees(tkl).on_the_way
    assert coming.train_number == "102"
    # The interlocking takes it from the snapshot onto the line at its exit, and in.
    put = operate(tkl, "/train", call=coming.call)
    assert [(t.number, t.exit) for t in put.state.trains] == [("102", "O")]
    entry = operate(tkl, "/route", start="In2", end="21").route
    operate(tkl, "/step", route=entry)
    operate(tkl, "/step", route=entry)
    arrived = operate(tkl, "/arrive", route=entry)
    assert [(r.action, r.accepted) for r in arrived.reports] == [
        (station.Action.TRAIN_ARRIVED, True)
    ], arrived.reports
    here = next(c for c in b_sees(tkl).calls if c.call == coming.call)
    assert (here.arrival_state, here.track) == (station.ArrivalState.ARRIVED, "2")
    assert mellana.seen().have_left == []
    # Cleared towards Norrby: the route out, and Kör out on the line.
    norrby = Client(hub, code, "nby")
    asked = b_sends(
        tkl,
        station.Action.CLEARANCE_REQUEST,
        call="t102-asn",
        section="s-nby-asn",
        clearance_id="c2",
    )
    assert asked.status == station.ReplyStatus.ACCEPTED, asked.message
    answered = norrby.send(station.Action.CLEARANCE_RESPONSE, clearance_id="c2", approved=True)
    assert answered.status == station.ReplyStatus.ACCEPTED, answered.message
    laid = operate(tkl, "/route", start="21", end="Ut")
    out = laid.route
    # The exit signal goes up as signal.exit, and Drift takes it at level 2 (DRIFT-10).
    signalled = [r for r in laid.reports if r.kind == TklReportKind.EXIT_SIGNAL]
    assert [(r.aspect, r.sent, r.accepted) for r in signalled] == [
        (station.ExitSignalAspect.PROCEED, True, True)
    ], laid.reports
    operate(tkl, "/step", route=out)
    left = operate(tkl, "/step", route=out)
    departed = [r for r in left.reports if r.action == station.Action.TRAIN_DEPARTED]
    assert [(r.sent, r.accepted) for r in departed] == [(True, True)], left.reports
    assert left.state.trains == [] and left.state.routes == []
    assert [t.train_number for t in norrby.seen().on_the_way] == ["102"]
    assert [t.train_number for t in b_sees(tkl).have_left] == ["102"]
