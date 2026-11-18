"""Ställverket's API (#84) under /api/tkl/1/stallverk: only an unlocked TKL operates, the
state survives a restart, a second screen follows with wait, the model cannot change under set
routes, a state that does not fit fails closed, and what the interlocking reports goes up to a
pretend hub as station commands (STV-10). Nothing here names a station (RS13)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts import station
from contracts.common import Side
from contracts.meet import ClearanceMode, TrackKind
from contracts.reasons import TEXT_SV, Reason
from contracts.station_model import PanelFunction, PanelFunctionType, StationModel, to_json
from contracts.tkl import TklAnswer, TklInterlocking, TklTargets, TklWait
from tkl.app import create_app
from tkl.store import LOCAL, Connection
from tkl.tests.provstation import provby
from tkl.tests.test_app import API, PIN, set_up, tkl

S = API + "/stallverk"


def model() -> StationModel:
    """The made-up station, with its exits' ids in the outside as the pretend meet has them."""
    found = provby()
    exits = [e.model_copy(update={"outside_id": e.id.lower()}) for e in found.line_exits]
    return found.model_copy(update={"line_exits": exits})


def with_model(client: TestClient, given: StationModel | None = None) -> None:
    answer = client.put(API + "/studio/model", content=to_json(given or model()))
    assert answer.status_code == 200, answer.text


def answer(response: httpx.Response) -> TklAnswer:
    assert response.status_code == 200, response.text
    return TklAnswer.model_validate(response.json())


def route_of(found: TklAnswer, start: str, end: str) -> int:
    return next(r.id for r in found.state.routes if (r.start, r.end) == (start, end))


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    made = tkl(tmp_path)
    assert set_up(made).status_code == 201
    with_model(made)
    return made


def test_only_an_unlocked_tkl_operates(tmp_path: Path) -> None:
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    assert client.get(S).status_code == 404, "level 0: no model, no interlocking"
    assert "Spårplan" in client.get(S).json()["detail"]
    with_model(client)
    assert client.get(S).status_code == 200
    client.post(API + "/lock")
    for path, body in (
        ("/route", {"start": "In", "end": "12"}),
        ("/release", {"route": 1}),
        ("/lever", {"switch": "1"}),
        ("/step", {"route": 1}),
        ("/train", {"number": "41", "exit": "V"}),
        ("/reset", {"confirm": True}),
    ):
        assert client.post(S + path, json=body).status_code == 401, path
    assert client.get(S).status_code == 401
    assert client.get(S + "/wait", params={"after": 0, "seconds": 0}).status_code == 401
    assert client.get(S + "/targets", params={"start": "In"}).status_code == 401
    assert client.post(API + "/unlock", json={"pin": PIN}).status_code == 200
    other = client.post(
        S + "/route", json={"start": "In", "end": "12"}, headers={"Origin": "https://x.invalid"}
    )
    assert other.status_code == 403, "changes come from TKL's own page"


def test_every_operation_answers_yes_or_no_with_the_state(client: TestClient) -> None:
    put = answer(client.post(S + "/train", json={"number": "41", "exit": "V"}))
    assert put.accepted and put.state.trains[0].exit == "V"
    laid = answer(client.post(S + "/route", json={"start": "In", "end": "22"}))
    assert laid.accepted and laid.route == route_of(laid, "In", "22")
    refused = answer(client.post(S + "/route", json={"start": "In2", "end": "21"}))
    assert not refused.accepted and "låst i vägen In → 22" in refused.message
    assert refused.state.revision == laid.state.revision, "a no changes nothing"
    unknown = answer(client.post(S + "/route", json={"start": "Nowhere", "end": "12"}))
    assert not unknown.accepted and "Nowhere" in unknown.message
    assert client.post(S + "/route", json={"start": "In"}).status_code == 422
    stepped = answer(client.post(S + "/step", json={"route": laid.route}))
    assert stepped.accepted and stepped.state.trains[0].section == "Vx1"
    lever = answer(client.post(S + "/lever", json={"switch": "1"}))
    assert not lever.accepted and "låst" in lever.message
    no = answer(client.post(S + "/emergency-release", json={"route": laid.route}))
    assert not no.accepted and "Bekräfta" in no.message
    yes = answer(client.post(S + "/emergency-release", json={"route": laid.route, "confirm": True}))
    assert yes.accepted and yes.state.events[0].text.startswith("Nödutlösning")
    assert TklInterlocking.model_validate(client.get(S).json()) == yes.state
    shunting = answer(
        client.post(S + "/route", json={"start": "21", "end": "Ut", "kind": "shunting"})
    )
    assert shunting.accepted and shunting.state.routes[0].kind == "shunting"


def test_the_targets_from_a_start(client: TestClient) -> None:
    found = client.get(S + "/targets", params={"start": "21"})
    targets = TklTargets.model_validate(found.json())
    assert [k.value for k in targets.kinds] == ["train", "shunting"], "STV-24"
    assert {(t.kind.value, t.end) for t in targets.targets} == {
        ("train", "Ut"),
        ("shunting", "Ut"),
    }
    assert client.get(S + "/targets", params={"start": "Nowhere"}).status_code == 404


def test_the_state_survives_a_restart(tmp_path: Path) -> None:
    first = tkl(tmp_path)
    assert set_up(first).status_code == 201
    with_model(first)
    answer(first.post(S + "/train", json={"number": "41", "exit": "V"}))
    laid = answer(first.post(S + "/route", json={"start": "In", "end": "12"}))
    answer(first.post(S + "/step", json={"route": laid.route}))
    before = TklInterlocking.model_validate(first.get(S).json())
    again = tkl(tmp_path)
    assert again.post(API + "/unlock", json={"pin": PIN}).status_code == 200
    after = TklInterlocking.model_validate(again.get(S).json())
    assert after == before
    assert answer(again.post(S + "/step", json={"route": laid.route})).accepted


def test_wait_wakes_on_a_change(client: TestClient) -> None:
    """STV-05: a second screen waits for the next change and reads again."""
    revision = TklInterlocking.model_validate(client.get(S).json()).revision
    quiet = client.get(S + "/wait", params={"after": revision, "seconds": 0}).json()
    assert quiet == {"revision": revision, "changed": False}
    answer(client.post(S + "/route", json={"start": "In", "end": "12"}))
    woke = TklWait.model_validate(
        client.get(S + "/wait", params={"after": revision, "seconds": 0}).json()
    )
    assert woke.changed and woke.revision > revision
    # A waiting screen wakes when the other one changes something.
    found: dict[str, Any] = {}

    def waiting() -> None:
        found["at"] = time.monotonic()
        found["answer"] = client.get(
            S + "/wait", params={"after": woke.revision, "seconds": 20}
        ).json()
        found["done"] = time.monotonic()

    other = threading.Thread(target=waiting)
    other.start()
    time.sleep(0.5)
    changed = time.monotonic()
    answer(client.post(S + "/lever", json={"switch": "2"}))
    other.join(timeout=15)
    assert found["answer"]["changed"] is True
    assert found["done"] - changed < 5


def test_the_model_stays_while_routes_or_numbers_are_in_the_interlocking(
    client: TestClient,
) -> None:
    laid = answer(client.post(S + "/route", json={"start": "In", "end": "12"}))
    other = provby()
    refused = client.put(API + "/studio/model", content=to_json(other))
    assert refused.status_code == 409 and "Lös ut vägarna" in refused.json()["detail"]
    assert client.delete(API + "/studio/model").status_code == 409
    with_model(client)  # the same model again changes nothing
    answer(client.post(S + "/release", json={"route": laid.route}))
    answer(client.post(S + "/train", json={"number": "41", "exit": "V"}))
    assert client.put(API + "/studio/model", content=to_json(other)).status_code == 409
    reset = answer(client.post(S + "/reset", json={"confirm": True, "trains": True}))
    assert reset.accepted and reset.state.trains == []
    before = reset.state.revision
    with_model(client, other)
    fresh = TklInterlocking.model_validate(client.get(S).json())
    assert fresh.revision == before + 1 and fresh.routes == [] and fresh.problem is None


def _tamper(tmp_path: Path, change: Any) -> None:
    with sqlite3.connect(tmp_path / "tkl.sqlite3") as db:
        body = db.execute("SELECT body FROM interlocking WHERE slot=?", (LOCAL,)).fetchone()[0]
        db.execute("UPDATE interlocking SET body=? WHERE slot=?", (change(body), LOCAL))


def test_ported_a_state_that_does_not_fit_fails_closed(tmp_path: Path) -> None:
    """Ported: 'durable locks survive process restart; corrupt or changed state fails closed'
    (cda-tkl test/engine.test.mjs). A state for another model, or one that cannot be read,
    refuses everything but a reset."""
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    with_model(client)
    answer(client.post(S + "/route", json={"start": "In", "end": "12"}))

    def other_model(body: str) -> str:
        data = json.loads(body)
        data["model"] = "0" * 64
        return json.dumps(data)

    _tamper(tmp_path, other_model)
    stale = TklInterlocking.model_validate(client.get(S).json())
    assert stale.problem is not None and "Nollställ" in stale.problem
    assert len(stale.routes) == 1, "the saved routes are shown as they were"
    refused = answer(client.post(S + "/route", json={"start": "In2", "end": "21"}))
    assert not refused.accepted and refused.message == stale.problem
    assert answer(client.post(S + "/reset", json={"confirm": True})).accepted
    assert TklInterlocking.model_validate(client.get(S).json()).problem is None
    _tamper(tmp_path, lambda body: "{broken")
    broken = TklInterlocking.model_validate(client.get(S).json())
    assert broken.problem is not None and "går inte att läsa" in broken.problem
    assert client.put(API + "/studio/model", content=to_json(provby())).status_code == 409
    assert answer(client.post(S + "/reset", json={"confirm": True})).accepted
    assert TklInterlocking.model_validate(client.get(S).json()).problem is None


# --- the station protocol towards a pretend hub (STV-10) ---------------------------------------

CONTEXT = station.MeetContext(meet_id="provmote", version=1, game_day=1, epoch=0)
PLACE = "prv"


class PretendHub:
    """A hub that keeps one place's snapshot and answers station commands like Drift: train
    41 on its way here from the east, and on to the west once it is cleared."""

    def __init__(self) -> None:
        self.commands: list[station.Command] = []
        self.cleared = False
        self.arrived = False
        self.departed = False

    def snapshot(self) -> station.Snapshot:
        call = station.CallHere(
            call="c41",
            train="t41",
            train_number="41",
            from_place="ost",
            to_place="vby",
            track="2",
            arrival_state=(
                station.ArrivalState.ARRIVED if self.arrived else station.ArrivalState.ON_THE_WAY
            ),
            departure_state=(
                station.DepartureState.DEPARTED
                if self.departed
                else station.DepartureState.CLEARED
                if self.cleared
                else station.DepartureState.PLANNED
            ),
            revision=3,
            allowed_actions=[
                station.Action.TRAIN_ARRIVED,
                station.Action.TRAIN_TRACK_CHANGE,
                *([station.Action.TRAIN_DEPARTED] if self.cleared else []),
            ],
        )
        coming = station.TrainOnSection(
            call="c41",
            train_number="41",
            section="s-ost",
            other_place="ost",
            planned_track="2",
            departed_at="06:00",
        )
        clearance = station.Clearance(
            clearance_id="k41",
            call="c41",
            train_number="41",
            section="s-vast",
            from_place=PLACE,
            to_place="vby",
            status=station.ClearanceStatus.APPROVED,
            requested_at="06:05",
            revision=2,
        )
        return station.Snapshot(
            place=station.Neighbour(place=PLACE, code="Pr", name="Provby"),
            context=CONTEXT,
            clock=station.Clock(time="06:10", seconds=22200, running=True, speed=4, game_day=1),
            place_revision=7,
            sections=[
                station.SectionHere(
                    section=section,
                    other_place=other,
                    other_code=other,
                    tracks=TrackKind.SINGLE,
                    clearance_mode=ClearanceMode.REQUESTED,
                    side=side,
                    exit=exit,
                )
                for section, other, side, exit in (
                    ("s-vast", "vby", Side.LEFT, "v"),
                    ("s-ost", "ost", Side.RIGHT, "o"),
                )
            ],
            calls=[call],
            on_the_way=[] if self.arrived else [coming],
            clearances=[clearance] if self.cleared and not self.departed else [],
            track_display=station.TrackDisplay(
                revision=1, tracks=[station.TrackShown(track=t) for t in ("1", "2")]
            ),
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer hemlig-nyckel"
        if request.method == "GET" and request.url.path == f"/api/station/1/places/{PLACE}":
            return httpx.Response(200, json=self.snapshot().model_dump(mode="json"))
        if request.method == "POST" and request.url.path == "/api/station/1/commands":
            command = station.Command.model_validate_json(request.content)
            self.commands.append(command)
            reason = None
            if command.action == station.Action.TRAIN_ARRIVED:
                self.arrived = True
            elif command.action == station.Action.TRAIN_DEPARTED:
                self.departed = True
            elif command.action == station.Action.SIGNAL_EXIT:
                reason = Reason.NOT_LEVEL_3
            reply = station.Reply(
                message_id=command.message_id,
                status=station.ReplyStatus.REJECTED if reason else station.ReplyStatus.ACCEPTED,
                reason=reason,
                message=TEXT_SV[reason] if reason else None,
                snapshot=self.snapshot(),
            )
            return httpx.Response(200, json=reply.model_dump(mode="json"))
        return httpx.Response(404, json={"detail": "Finns inte."})


@pytest.fixture
def connected(tmp_path: Path) -> tuple[TestClient, PretendHub]:
    hub = PretendHub()
    app = create_app(
        tmp_path,
        http=lambda: httpx.Client(transport=httpx.MockTransport(hub.handle)),
        discover=lambda: [],
    )
    client = TestClient(app)
    assert set_up(client).status_code == 201
    with_model(client)
    app.state.store.connected(
        LOCAL,
        Connection(
            address="http://hubben.invalid",
            relay=None,
            hub_name="Hubben",
            client_id="tkl-1",
            status=station.ApprovalStatus.APPROVED,
            places=[PLACE],
            outside_version=1,
            message=None,
            key="hemlig-nyckel",
        ),
    )
    return client, hub


def test_arrival_and_departure_go_up_to_the_hub(connected: tuple[TestClient, PretendHub]) -> None:
    """STV-10: a train on its way here is put at its exit by its call; Ankommit reports the
    arrival with the track it stands on; Kör out on the line reports the departure. The exit
    signal's aspect goes up as signal.exit, which this hub, like Drift today, takes only at
    level 3: its no comes back as it was given."""
    client, hub = connected
    put = answer(client.post(S + "/train", json={"call": "c41"}))
    assert put.accepted, put.message
    assert [(t.number, t.call, t.exit) for t in put.state.trains] == [("41", "c41", "O")]
    entry = answer(client.post(S + "/route", json={"start": "In2", "end": "21"})).route
    answer(client.post(S + "/step", json={"route": entry}))
    answer(client.post(S + "/step", json={"route": entry}))
    arrived = answer(client.post(S + "/arrive", json={"route": entry}))
    [report] = arrived.reports
    assert (report.action, report.sent, report.accepted) == (
        station.Action.TRAIN_ARRIVED,
        True,
        True,
    )
    sent = hub.commands[-1]
    assert (sent.action, sent.payload, sent.client_id, sent.place) == (
        station.Action.TRAIN_ARRIVED,
        {"call": "c41", "track": "2"},
        "tkl-1",
        PLACE,
    )
    assert sent.expected_revision == station.Revision(
        scope=station.RevisionScope.CALL, key="c41", value=3
    )
    assert sent.context == CONTEXT
    assert arrived.state.events[0].text == "Ankomsten för tåg 41: Hubben tog emot den."
    # Cleared towards the west: the route out, Kör, and out on the line.
    hub.cleared = True
    out = answer(client.post(S + "/route", json={"start": "21", "end": "Ut"}))
    [signal] = out.reports
    assert (signal.action, signal.sent, signal.accepted) == (
        station.Action.SIGNAL_EXIT,
        True,
        False,
    )
    assert hub.commands[-1].payload == {
        "exit": "v",
        "section": "s-vast",
        "aspect": "proceed",
        "call": "c41",
    }
    answer(client.post(S + "/step", json={"route": out.route}))
    assert hub.commands[-1].payload["aspect"] == "stop", "the train has passed the signal"
    left = answer(client.post(S + "/step", json={"route": out.route}))
    departed = [r for r in left.reports if r.action == station.Action.TRAIN_DEPARTED]
    assert [(r.sent, r.accepted) for r in departed] == [(True, True)]
    assert hub.commands[-1].action == station.Action.TRAIN_DEPARTED
    assert hub.commands[-1].payload == {"call": "c41"}
    assert left.state.trains == [] and hub.departed
    assert not [c for c in hub.commands if c.action == station.Action.SECTION_OCCUPANCY]


def test_a_departure_by_another_exit_than_the_clearance_is_not_reported(
    connected: tuple[TestClient, PretendHub],
) -> None:
    client, hub = connected
    hub.cleared, hub.arrived = True, True
    answer(client.post(S + "/train", json={"number": "41", "section": "Spår 2"}))
    out = answer(client.post(S + "/route", json={"start": "22", "end": "Ut2"}))
    left = answer(client.post(S + "/depart", json={"route": out.route}))
    [departed] = [r for r in left.reports if r.kind.value == "departed"]
    assert not departed.sent and "klarering mot utfarten v" in (departed.message or "")
    assert not [c for c in hub.commands if c.action == station.Action.TRAIN_DEPARTED]


def test_without_a_meet_the_interlocking_works_and_says_nothing_went_up(
    client: TestClient,
) -> None:
    answer(client.post(S + "/train", json={"number": "41", "section": "Spår 1"}))
    out = answer(client.post(S + "/route", json={"start": "12", "end": "Ut2"}))
    assert out.accepted
    left = answer(client.post(S + "/depart", json={"route": out.route}))
    assert left.accepted and left.state.trains == []
    assert all(not r.sent for r in left.reports)
    assert all("inte ansluten" in (r.message or "") for r in left.reports)
    unknown = answer(client.post(S + "/train", json={"call": "c99"}))
    assert not unknown.accepted and "inte ansluten" in unknown.message


def test_a_panel_function_is_operated_through_the_api_and_kept(tmp_path: Path) -> None:
    """POST /stallverk/function (STV-04): yes or no with the reason and the state, which lists
    the functions with theirs; it is kept with the station like the rest of the state."""
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    stop = PanelFunction(type=PanelFunctionType.SIGNAL_STOP, name="Signalstopp", signals=["In"])
    with_model(client, model().model_copy(update={"functions": [stop]}))
    assert [f["name"] for f in client.get(S).json()["functions"]] == ["Signalstopp"]
    on = answer(client.post(S + "/function", json={"function": "Signalstopp", "action": "on"}))
    assert on.accepted and on.state.functions[0].on and on.state.signals["In"].blocked
    refused = answer(client.post(S + "/route", json={"start": "In", "end": "12"}))
    assert not refused.accepted and "signalstopp" in refused.message
    unknown = answer(client.post(S + "/function", json={"function": "Nej", "action": "on"}))
    assert not unknown.accepted and "finns inte" in unknown.message
    wrong = client.post(S + "/function", json={"function": "Signalstopp", "action": "turn"})
    assert wrong.status_code == 422
    again = tkl(tmp_path)
    assert again.post(API + "/unlock", json={"pin": PIN}).status_code == 200
    assert TklInterlocking.model_validate(again.get(S).json()).functions[0].on
    client.post(API + "/lock")
    locked = client.post(S + "/function", json={"function": "Signalstopp", "action": "off"})
    assert locked.status_code == 401
