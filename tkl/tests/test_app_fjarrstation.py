"""Fjärrstyrning, the station's side in TKL (#36 del b, FR5–FR8, FR12–FR15, FR20–FR29, FR42):
TKL hands its station over and takes it back through Hubben, answers the routes asked for from
afar in its own interlocking, releases a cancelled one, reports route.state when it changes,
lays no new route after 45 seconds without the controller, switches its default automat on after
90, and gives and takes back the local area. Two TKLs on one Hubben each answer only for their
own station. A pretend hub stands in for Drift, as the remote interlocking and Hubben would act.
Nothing here names a station (RS13)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts import station
from contracts.meet import ClearanceMode, TrackKind
from contracts.station_model import PanelFunction, PanelFunctionType, StationModel, to_json
from contracts.station_outside import StationOutside
from contracts.tkl import TklAnswer, TklInterlocking
from tkl.app import create_app
from tkl.station_remote import StationRemote
from tkl.store import LOCAL
from tkl.tests.test_app import API, set_up
from tkl.tests.test_app_stallverk import model as made_up

CONTEXT = station.MeetContext(meet_id="provmote", version=1, game_day=1, epoch=0)
REMOTE = station.Receiver(client_id="fjarr-1", kind=station.ClientKind.REMOTE, name="Fjärr Västra")
S = API + "/stallverk"


def with_area() -> StationModel:
    """The made-up station with a local release of track 2 (FR41)."""
    release = PanelFunction(
        type=PanelFunctionType.LOCAL_RELEASE,
        name="Lokal frigivning",
        track_circuits=["Spår 2"],
        signals=["21", "22", "D"],
    )
    return made_up().model_copy(update={"functions": [release]})


class Place:
    """One station's place in the pretend hub, as Drift keeps it for remote control."""

    def __init__(self, place: str, client_id: str, key: str) -> None:
        self.place = place
        self.client_id = client_id
        self.key = key
        self.mode = station.PlaceMode.MANNED
        self.controller: station.Receiver | None = None
        self.offer: station.OfferHere | None = None
        self.silent: int | None = None
        self.routes: dict[str, station.RemoteRouteHere] = {}
        self.state: station.RouteState | None = None
        self.asked: list[station.AutomatAsked] = []
        self.local: list[station.LocalRequestHere] = []
        self.calls: list[station.CallHere] = []
        self.coming: list[station.TrainOnSection] = []
        self.clearances: list[station.Clearance] = []
        # #36 del d: the controller's answers to the parts and its changes to the ready list.
        self.part_answers: list[station.PartAnswered] = []
        self.ready_asks: list[station.ReadyAsked] = []

    def snapshot(self) -> station.Snapshot:
        sections = [
            station.SectionHere(
                section=f"s-{self.place}-{exit_id}",
                other_place=exit_id,
                other_code=exit_id,
                tracks=TrackKind.SINGLE,
                clearance_mode=ClearanceMode.REQUESTED,
                exit=exit_id,
            )
            for exit_id in ("v", "o")
        ]
        return station.Snapshot(
            place=station.Neighbour(place=self.place, code=self.place.upper(), name="Exempelby"),
            context=CONTEXT,
            clock=station.Clock(time="09:00", seconds=32400, running=True, speed=4, game_day=1),
            place_revision=1,
            sections=sections,
            calls=self.calls,
            on_the_way=self.coming,
            clearances=self.clearances,
            mode=self.mode,
            remote=station.RemoteHere(
                controllable=True,
                controller=self.controller,
                offer=self.offer,
                receivers=[] if self.controller else [REMOTE],
                controller_silent=self.silent if self.controller else None,
                routes=list(self.routes.values()),
                route_state=self.state,
                automats_asked=self.asked,
                local_requests=self.local,
                part_answers=self.part_answers,
                ready_asks=self.ready_asks,
            ),
        )

    # --- what the one who controls the station does, through Hubben --------------------------

    def accept(self) -> None:
        self.offer, self.controller, self.silent = None, REMOTE, 0
        self.mode = station.PlaceMode.REMOTE

    def ask(self, request_id: str, route: str, call: str | None = None) -> None:
        self.routes[request_id] = station.RemoteRouteHere(
            request_id=request_id,
            route=route,
            call=call,
            state=station.RemoteRouteState.REQUESTED,
            by=REMOTE.client_id,
            asked_at="09:00",
            answer_in=10,
        )

    def cancel(self, request_id: str) -> None:
        self.routes[request_id] = self.routes[request_id].model_copy(
            update={"state": station.RemoteRouteState.CANCELLED}
        )

    def decide(self, code: str, on: bool) -> None:
        self.asked = [a for a in self.asked if a.code != code]
        self.asked.append(station.AutomatAsked(code=code, on=on))


class PretendHub:
    """Hubben for one or two stations, each TKL with its own key and place."""

    def __init__(self) -> None:
        self.places: dict[str, Place] = {}
        self.commands: list[station.Command] = []

    def add(self, place: str, client_id: str) -> Place:
        found = Place(place, client_id, f"nyckel-{client_id}")
        self.places[place] = found
        return found

    def of_client(self, client_id: str) -> Place:
        return next(p for p in self.places.values() if p.client_id == client_id)

    def sent(self, action: station.Action, place: str | None = None) -> list[station.Command]:
        return [
            c for c in self.commands if c.action == action and (place is None or c.place == place)
        ]

    def reply_for(self, place: Place) -> station.ConnectReply:
        return station.ConnectReply(
            client_id=place.client_id,
            status=station.ApprovalStatus.APPROVED,
            places=[place.place],
            key=place.key,
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/api/station/1/connect":
            asked = station.ConnectRequest.model_validate_json(request.content)
            found = next(p for p in self.places.values() if p.client_id == asked.station_id)
            return httpx.Response(200, json=self.reply_for(found).model_dump(mode="json"))
        if request.method == "GET" and path.startswith("/api/station/1/connect/"):
            found = self.of_client(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=self.reply_for(found).model_dump(mode="json"))
        key = request.headers.get("Authorization", "").removeprefix("Bearer ")
        caller = next((p for p in self.places.values() if p.key == key), None)
        if caller is None:
            return httpx.Response(401, json={"detail": "Ingen nyckel."})
        if request.method == "GET" and path.startswith("/api/station/1/places/"):
            place = path.rsplit("/", 1)[1]
            if place != caller.place:
                return httpx.Response(403, json={"detail": "Inte godkänd."})
            return httpx.Response(200, json=caller.snapshot().model_dump(mode="json"))
        if request.method == "POST" and path == "/api/station/1/commands":
            command = station.Command.model_validate_json(request.content)
            assert command.client_id == caller.client_id and command.place == caller.place
            self.commands.append(command)
            self.act(caller, command)
            reply = station.Reply(
                message_id=command.message_id,
                status=station.ReplyStatus.ACCEPTED,
                snapshot=caller.snapshot(),
            )
            return httpx.Response(200, json=reply.model_dump(mode="json"))
        return httpx.Response(404, json={"detail": "Finns inte."})

    @staticmethod
    def act(place: Place, command: station.Command) -> None:
        """What Drift does with the station's own commands, as far as these tests need."""
        payload = command.payload
        match command.action:
            case station.Action.PLACE_OFFER:
                place.mode = station.PlaceMode.OFFERED
                place.offer = station.OfferHere(place=place.place, to=REMOTE, expires_in=60)
            case station.Action.PLACE_TAKE_BACK:
                place.offer, place.controller, place.asked, place.local = None, None, [], []
                place.mode = station.PlaceMode.MANNED
            case station.Action.ROUTE_RESPONSE:
                answer = station.RouteResponse.model_validate(payload)
                state = (
                    station.RemoteRouteState.LOCKED
                    if answer.locked
                    else station.RemoteRouteState.REFUSED
                )
                place.routes[answer.request_id] = place.routes[answer.request_id].model_copy(
                    update={"state": state, "reason": answer.reason, "answer_in": None}
                )
            case station.Action.ROUTE_STATE:
                place.state = station.RouteState.model_validate(payload)
                waiting = {r.request_id for r in place.state.part_requests}
                done = set(place.state.answered)
                place.part_answers = [
                    a for a in place.part_answers if a.seq not in done and a.request_id in waiting
                ]
                place.ready_asks = [a for a in place.ready_asks if a.seq not in done]
                shown = {a.code for a in place.state.automats}
                shown |= {a.code for a in place.state.local_areas}
                place.asked = [a for a in place.asked if (a.code in shown) != a.on]
            case station.Action.LOCAL_RELEASE_REQUEST:
                asked = station.LocalReleaseRequest.model_validate(payload)
                place.local.append(
                    station.LocalRequestHere(
                        code=asked.code, all_day=asked.all_day, asked_at="09:00"
                    )
                )
            case _:
                pass


def connect(tmp_path: Path, hub: PretendHub, place: Place, model: StationModel) -> TestClient:
    """A TKL whose station id is its place's client, with its catalogue in the outside it
    connects with: every route in and out, and A3 as the default automat."""
    app = create_app(
        tmp_path,
        http=lambda: httpx.Client(transport=httpx.MockTransport(hub.handle)),
        discover=lambda: [],
    )
    client = TestClient(app)
    assert set_up(client, station_id=place.client_id).status_code == 201
    assert client.put(API + "/studio/model", content=to_json(model)).status_code == 200
    candidates = [c["id"] for c in client.get(API + "/studio/fjarrstyrning").json()["candidates"]]
    chosen = {
        "routes": candidates,
        "automats": [{"code": "A3", "kind": "a3", "default": True}],
    }
    assert client.put(API + "/studio/fjarrstyrning", json=chosen).status_code == 200
    assert client.post(API + "/studio/version").status_code == 200
    made = client.post(API + "/connection", json={"address": "http://hubben.invalid"})
    assert made.status_code == 200, made.text
    return client


def remote_of(client: TestClient) -> StationRemote:
    found = client.app.state.station_remote  # type: ignore[attr-defined]
    assert isinstance(found, StationRemote)
    return found


def step(client: TestClient) -> Any:
    return remote_of(client).step(LOCAL)


def interlocking(client: TestClient) -> TklInterlocking:
    return TklInterlocking.model_validate(client.get(S).json())


def command(client: TestClient, action: str, **payload: Any) -> dict[str, Any]:
    answer = client.post(
        API + "/commands",
        json={
            "message_id": f"m-{action}-{len(str(payload))}",
            "place": "exb",
            "context": CONTEXT.model_dump(mode="json"),
            "action": action,
            "payload": payload,
        },
    )
    assert answer.status_code == 200, answer.text
    return dict(answer.json())


@pytest.fixture
def hub() -> PretendHub:
    return PretendHub()


@pytest.fixture
def home(hub: PretendHub) -> Place:
    return hub.add("exb", "exb")


@pytest.fixture
def client(tmp_path: Path, hub: PretendHub, home: Place) -> TestClient:
    return connect(tmp_path, hub, home, with_area())


def test_the_outside_tkl_connects_with_has_the_catalogue(client: TestClient) -> None:
    store = client.app.state.store  # type: ignore[attr-defined]
    _, outside = store.latest_outside(LOCAL)
    assert isinstance(outside, StationOutside)
    assert "In-12" in {r.id for r in outside.remote_routes}
    assert [(a.code, a.default) for a in outside.automats] == [("A3", True), ("L1", False)]


def test_offer_withdraw_accept_and_take_back(
    client: TestClient, hub: PretendHub, home: Place
) -> None:
    """FR5–FR8: Lämna till … goes as place.offer; Ta tillbaka withdraws it; once taken, the
    station is Fjärrstyrd and its own panel lays nothing; Ta tillbaka makes it manned again."""
    seen = command(client, "place.offer", to=REMOTE.client_id)
    assert seen["snapshot"]["mode"] == "offered"
    assert seen["snapshot"]["remote"]["offer"]["expires_in"] == 60
    seen = command(client, "place.take_back")
    assert seen["snapshot"]["mode"] == "manned" and seen["snapshot"]["remote"]["offer"] is None
    command(client, "place.offer", to=REMOTE.client_id)
    home.accept()
    step(client)
    assert interlocking(client).fjarr.controller == "Fjärr Västra"
    refused = TklAnswer.model_validate(
        client.post(S + "/route", json={"start": "In", "end": "12"}).json()
    )
    assert not refused.accepted and "fjärrstyrs från Fjärr Västra" in refused.message
    command(client, "place.take_back")
    step(client)
    assert interlocking(client).fjarr.controller is None
    assert TklAnswer.model_validate(
        client.post(S + "/route", json={"start": "In", "end": "12"}).json()
    ).accepted


def test_routes_asked_for_are_answered_and_the_state_reported(
    client: TestClient, hub: PretendHub, home: Place
) -> None:
    """FR12–FR15: locked, refused with the interlocking's reason, cancelled and released; the
    state goes up whole when it changes, and only then; a route laid from afar stays after
    the station is taken back."""
    command(client, "place.offer", to=REMOTE.client_id)
    home.accept()
    home.ask("r1", "In-12")
    step(client)
    [answer] = [
        station.RouteResponse.model_validate(c.payload)
        for c in hub.sent(station.Action.ROUTE_RESPONSE)
    ]
    assert (answer.request_id, answer.locked) == ("r1", True)
    assert home.state is not None
    assert [(r.route, r.by, r.request_id) for r in home.state.locked] == [
        ("In-12", station.RouteBy.REMOTE, "r1")
    ]
    home.ask("r2", "In2-11")
    step(client)
    refused = station.RouteResponse.model_validate(
        hub.sent(station.Action.ROUTE_RESPONSE)[-1].payload
    )
    assert (refused.request_id, refused.locked) == ("r2", False)
    assert refused.reason == "conflicting_route" and refused.message
    states = len(hub.sent(station.Action.ROUTE_STATE))
    step(client)
    assert len(hub.sent(station.Action.ROUTE_STATE)) == states, "sent only when it changes"
    home.cancel("r1")
    step(client)
    assert home.state is not None and home.state.locked == []
    assert len(hub.sent(station.Action.ROUTE_STATE)) == states + 1
    # FR15: laid from afar, kept after the station is taken back.
    home.ask("r3", "In-22")
    step(client)
    command(client, "place.take_back")
    step(client)
    assert [(r.route, r.by) for r in home.state.locked] == [("In-22", station.RouteBy.REMOTE)]


def test_a_train_hubben_has_arrived_has_its_route_in_released(
    client: TestClient, home: Place
) -> None:
    """Beslut 22 november: without LocoNet the station says in route.state that it cannot see a
    train come in on its tracks, and the route laid from afar to bring a train in is released
    when Hubben has the train's arrival: the driver's Framme or the controller's Ankommit."""
    command(client, "place.offer", to=REMOTE.client_id)
    home.accept()
    home.ask("r1", "In-12", call="t101-exb")
    home.ask("r2", "22-Ut2", call="t103-exb")
    step(client)
    assert home.state is not None
    assert home.state.unseen == ["1", "2"]
    assert [r.route for r in home.state.locked] == ["In-12", "22-Ut2"]
    arrived = station.ArrivalState.ARRIVED
    home.calls = [
        station.CallHere(call="t101-exb", train="t101", train_number="101", revision=2,
                         arrival_state=arrived),
        station.CallHere(call="t103-exb", train="t103", train_number="103", revision=2,
                         arrival_state=arrived),
    ]  # fmt: skip
    step(client)
    assert [r.route for r in home.state.locked] == ["22-Ut2"], "a route out is no arrival's"
    assert any(
        e.text == "Tåg 101 har kommit fram till spår 1 enligt Hubben. Vägen In → 12 är utlöst."
        for e in interlocking(client).events
    )


def test_45_seconds_without_the_controller_no_new_routes_and_90_the_default_automat(
    client: TestClient, hub: PretendHub, home: Place
) -> None:
    """FR28, FR29: after 45 seconds without the one who controls the station no new remote
    route is laid; after 90 the station switches on its default automat, by the automat."""
    command(client, "place.offer", to=REMOTE.client_id)
    home.accept()
    home.silent = 50
    home.ask("r1", "In-12")
    step(client)
    answer = station.RouteResponse.model_validate(
        hub.sent(station.Action.ROUTE_RESPONSE)[-1].payload
    )
    assert (answer.locked, answer.reason) == (False, "no_contact")
    assert interlocking(client).routes == []
    assert home.state is None or home.state.automats == []
    home.silent = 95
    step(client)
    assert home.state is not None
    assert [(a.code, a.by) for a in home.state.automats] == [("A3", station.RouteBy.AUTOMAT)]


def test_an_automat_from_afar_and_on_the_spot(
    client: TestClient, hub: PretendHub, home: Place
) -> None:
    """FR25: on the spot while manned, from the remote picture while remote-controlled."""
    switched = TklAnswer.model_validate(
        client.post(S + "/automat", json={"code": "A3", "on": True}).json()
    )
    assert switched.accepted, switched.message
    assert [a.code for a in switched.state.fjarr.automats] == ["A3"]
    step(client)
    assert home.state is not None and [(a.code, a.by) for a in home.state.automats] == [
        ("A3", station.RouteBy.STATION)
    ]
    command(client, "place.offer", to=REMOTE.client_id)
    home.accept()
    step(client)
    refused = TklAnswer.model_validate(
        client.post(S + "/automat", json={"code": "A3", "on": False}).json()
    )
    assert not refused.accepted, "the one who controls the station switches them now"
    home.decide("A3", False)
    step(client)
    assert home.state.automats == [] and home.asked == []


def test_the_local_area_over_the_protocol(client: TestClient, hub: PretendHub, home: Place) -> None:
    """FR20–FR23, FR39, FR42, FR44: asked for on site, given from afar, switched in, a route out
    from its border, and taken back when it is empty."""
    command(client, "place.offer", to=REMOTE.client_id)
    home.accept()
    step(client)
    seen = command(client, "local_release.request", code="L1", all_day=True)
    assert seen["snapshot"]["remote"]["local_requests"][0]["code"] == "L1"
    put = client.post(S + "/train", json={"number": "41", "section": "Spår 2"})
    assert TklAnswer.model_validate(put.json()).accepted, "a train is reported on site"
    home.local = []
    home.decide("L1", True)
    step(client)
    assert home.state is not None
    assert [(a.code, a.tracks) for a in home.state.local_areas] == [("L1", ["2"])]
    home.ask("r1", "In-22")
    home.ask("r2", "22-Ut2")
    step(client)
    answers = {
        a.request_id: a
        for a in (
            station.RouteResponse.model_validate(c.payload)
            for c in hub.sent(station.Action.ROUTE_RESPONSE)
        )
    }
    assert (answers["r1"].locked, answers["r1"].reason) == (False, "area_released")
    assert answers["r2"].locked, "out from the border (FR22)"
    home.decide("L1", False)
    step(client)
    assert [a.code for a in home.state.local_areas] == ["L1"], "not while a train is in it"
    train = interlocking(client).trains[0].id
    assert TklAnswer.model_validate(
        client.post(S + "/train/remove", json={"train": train}).json()
    ).accepted
    step(client)
    assert home.state.local_areas == []


def test_two_tkls_on_one_hub_answer_only_for_their_own_station(
    tmp_path: Path, hub: PretendHub, home: Place, client: TestClient
) -> None:
    other_place = hub.add("nby", "nby")
    other = connect(tmp_path / "andra", hub, other_place, with_area())
    command(client, "place.offer", to=REMOTE.client_id)
    home.accept()
    other_place.accept()
    home.ask("r1", "In-12")
    other_place.ask("r9", "In2-21")
    step(client)
    step(other)
    by_place = {(c.place, c.client_id) for c in hub.sent(station.Action.ROUTE_RESPONSE)}
    assert by_place == {("exb", "exb"), ("nby", "nby")}
    [mine] = hub.sent(station.Action.ROUTE_RESPONSE, "exb")
    [theirs] = hub.sent(station.Action.ROUTE_RESPONSE, "nby")
    assert mine.payload["request_id"] == "r1" and theirs.payload["request_id"] == "r9"
