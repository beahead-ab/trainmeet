"""TKL's side of the parts in Hubben (#87 del b, TKL101, TRAFIK-35): a station with a part
that is its own driftplats asks for both places, keeps following the approval after it has its
key, tells the station's place from the part's by the part's link, and the part's Klart att
skicka lists the part's own departures. A report the part's snapshot knows goes as the part's
place. A pretend hub stands in for Drift. Nothing here names a station (RS13)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts import station
from contracts.tkl import TklAnswer, TklConnection, TklPartTrains, TklReportKind
from tkl import hub_places
from tkl.app import create_app
from tkl.tests.provstation import bangard
from tkl.tests.test_app import API, set_up
from tkl.tests.test_app_stallverk import with_model

HOME, YARD, PART = "exb", "exb-bgd", "bangarden"
KEY = "hemlig-nyckel"
CONTEXT = station.MeetContext(meet_id="provmote", version=1, game_day=1, epoch=0)
P = API + "/stallverk/parts/" + PART


class PartsHub:
    """A hub with the station's place and its part's, each approved on its own."""

    def __init__(self) -> None:
        self.answers: dict[str, station.ApprovalStatus] = {
            HOME: station.ApprovalStatus.WAITING,
            YARD: station.ApprovalStatus.WAITING,
        }
        self.key_given = False
        self.asked = 0
        self.commands: list[station.Command] = []

    def approve(self, place: str) -> None:
        self.answers[place] = station.ApprovalStatus.APPROVED

    def refuse(self, place: str) -> None:
        self.answers[place] = station.ApprovalStatus.REFUSED

    def reply(self) -> station.ConnectReply:
        approved = [p for p, s in self.answers.items() if s == station.ApprovalStatus.APPROVED]
        key = None
        if approved and not self.key_given:
            key, self.key_given = KEY, True
        return station.ConnectReply(
            client_id="tkl-1",
            status=station.ApprovalStatus.APPROVED if approved else station.ApprovalStatus.WAITING,
            places=approved,
            wanted=[
                station.ClientPlace(place=HOME, status=self.answers[HOME]),
                station.ClientPlace(place=YARD, status=self.answers[YARD], part=PART, part_of=HOME),
            ],
            key=key,
        )

    def call(self, place: str, number: str, **more: Any) -> station.CallHere:
        return station.CallHere(
            call=f"c{number}-{place}", train=f"t{number}", train_number=number, revision=1, **more
        )

    def snapshot(self, place: str) -> station.Snapshot:
        if place == YARD:
            calls = [
                self.call(YARD, "9901", to_place=HOME, departure="06:40", track="51"),
                self.call(YARD, "9903", to_place=HOME, departure="06:20", track="52"),
            ]
        else:
            calls = [
                self.call(HOME, "41", from_place="ost", to_place="vby", departure="06:10"),
                self.call(
                    HOME, "9901", from_place=YARD, to_place="vby", arrival="06:43", track="1"
                ),
            ]
        return station.Snapshot(
            place=station.Neighbour(place=place, code=place, name=place),
            context=CONTEXT,
            clock=station.Clock(time="06:10", seconds=22200, running=True, speed=4, game_day=1),
            place_revision=1,
            calls=calls,
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/api/station/1/connect":
            asked = station.ConnectRequest.model_validate_json(request.content)
            assert [p.id for p in asked.outside.parts] == [PART] if asked.outside else False
            return httpx.Response(200, json=self.reply().model_dump(mode="json"))
        if request.method == "GET" and path == "/api/station/1/connect/tkl-1":
            self.asked += 1
            return httpx.Response(200, json=self.reply().model_dump(mode="json"))
        if request.headers.get("Authorization") != f"Bearer {KEY}":
            return httpx.Response(401, json={"detail": "Ingen nyckel."})
        for place in (HOME, YARD):
            if request.method == "GET" and path == f"/api/station/1/places/{place}":
                if self.answers[place] != station.ApprovalStatus.APPROVED:
                    return httpx.Response(403, json={"detail": "Inte godkänd."})
                return httpx.Response(200, json=self.snapshot(place).model_dump(mode="json"))
        if request.method == "POST" and path == "/api/station/1/commands":
            command = station.Command.model_validate_json(request.content)
            self.commands.append(command)
            reply = station.Reply(
                message_id=command.message_id,
                status=station.ReplyStatus.ACCEPTED,
                snapshot=self.snapshot(command.place),
            )
            return httpx.Response(200, json=reply.model_dump(mode="json"))
        return httpx.Response(404, json={"detail": "Finns inte."})


@pytest.fixture
def connected(tmp_path: Path) -> tuple[TestClient, PartsHub]:
    hub = PartsHub()
    app = create_app(
        tmp_path,
        http=lambda: httpx.Client(transport=httpx.MockTransport(hub.handle)),
        discover=lambda: [],
    )
    client = TestClient(app)
    assert set_up(client).status_code == 201
    with_model(client, bangard())
    made = client.post(API + "/connection", json={"address": "http://hubben.invalid"})
    assert made.status_code == 200, made.text
    return client, hub


def connection(client: TestClient) -> TklConnection:
    answer = client.get(API + "/connection")
    assert answer.status_code == 200, answer.text
    return TklConnection.model_validate(answer.json())


def trains(client: TestClient) -> TklPartTrains:
    answer = client.get(P + "/trains")
    assert answer.status_code == 200, answer.text
    return TklPartTrains.model_validate(answer.json())


def test_the_station_and_its_part_are_two_places_approved_on_their_own(
    connected: tuple[TestClient, PartsHub], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, hub = connected
    waiting = connection(client)
    assert waiting.status == station.ApprovalStatus.WAITING and waiting.place is None
    assert [(p.part, p.place, p.status) for p in waiting.parts] == [
        (PART, YARD, station.ApprovalStatus.WAITING)
    ]
    # The station first: its place is the station's, the part waits.
    hub.approve(HOME)
    first = connection(client)
    assert (first.status, first.place, first.places) == (
        station.ApprovalStatus.APPROVED,
        HOME,
        [HOME],
    )
    assert first.parts[0].status == station.ApprovalStatus.WAITING
    # Before the part is approved, its trains are the calls at the station that come from it.
    before = trains(client)
    assert [(t.number, t.departure) for t in before.trains] == [("9901", "06:43")]
    # The part later, with the same key: TKL follows, but not more often than it should.
    hub.approve(YARD)
    asked = hub.asked
    assert connection(client).parts[0].status == station.ApprovalStatus.WAITING
    assert hub.asked == asked, "asked a moment ago: not again yet"
    monkeypatch.setattr(hub_places, "FOLLOW_WAITING", 0.0)
    later = connection(client)
    assert hub.asked == asked + 1
    assert (later.place, sorted(later.places)) == (HOME, sorted([HOME, YARD]))
    assert later.parts[0].status == station.ApprovalStatus.APPROVED
    # The part's Klart att skicka: its own departures, from its own place, the earliest first.
    own = trains(client)
    assert [(t.number, t.departure, t.track) for t in own.trains] == [
        ("9903", "06:20", "52"),
        ("9901", "06:40", "51"),
    ]
    ready = client.post(P + "/ready", json={"number": "9901", "call": own.trains[1].call})
    assert ready.status_code == 200 and ready.json()["accepted"], ready.text
    listed = TklAnswer.model_validate(ready.json()).state.ready
    assert [(r.number, r.departure, r.track) for r in listed] == [("9901", "06:40", "51")]


def test_a_refused_part_does_not_stop_the_station(
    connected: tuple[TestClient, PartsHub], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, hub = connected
    monkeypatch.setattr(hub_places, "FOLLOW_WAITING", 0.0)
    hub.approve(HOME)
    hub.refuse(YARD)
    shown = connection(client)
    assert shown.place == HOME and shown.status == station.ApprovalStatus.APPROVED
    assert shown.parts[0].status == station.ApprovalStatus.REFUSED
    assert client.get(API + f"/places/{HOME}").status_code == 200
    assert client.get(API + f"/places/{YARD}").status_code == 403


def test_after_everything_is_answered_tkl_asks_more_seldom(
    connected: tuple[TestClient, PartsHub], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, hub = connected
    monkeypatch.setattr(hub_places, "FOLLOW_WAITING", 0.0)
    hub.approve(HOME)
    hub.approve(YARD)
    assert connection(client).parts[0].status == station.ApprovalStatus.APPROVED
    asked = hub.asked
    for _ in range(3):
        connection(client)
    assert hub.asked == asked, "every place answered: TKL waits FOLLOW_SETTLED between"
    monkeypatch.setattr(hub_places, "FOLLOW_SETTLED", 0.0)
    connection(client)
    assert hub.asked == asked + 1


def test_a_report_the_parts_snapshot_knows_goes_as_the_parts_place(
    connected: tuple[TestClient, PartsHub], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Train 9903 departs from the part in the plan, and the station's snapshot does not know
    it: when it leaves on the line from the yard's border, its departure goes up as the
    part's place."""
    client, hub = connected
    monkeypatch.setattr(hub_places, "FOLLOW_WAITING", 0.0)
    hub.approve(HOME)
    hub.approve(YARD)
    connection(client)
    put = client.post(API + "/stallverk/train", json={"number": "9903", "section": "w"})
    assert put.status_code == 200 and put.json()["accepted"], put.text
    laid = TklAnswer.model_validate(
        client.post(API + "/stallverk/route", json={"start": "B", "end": "Ut"}).json()
    )
    assert laid.accepted, laid.message
    out = next(r.id for r in laid.state.routes if r.end == "Ut")
    left = TklAnswer.model_validate(
        client.post(API + "/stallverk/depart", json={"route": out}).json()
    )
    assert left.accepted, left.message
    [departed] = [r for r in left.reports if r.kind == TklReportKind.DEPARTED]
    assert departed.sent and departed.accepted, departed.message
    assert [(c.place, c.action, c.payload) for c in hub.commands] == [
        (YARD, station.Action.TRAIN_DEPARTED, {"call": f"c9903-{YARD}"})
    ]
