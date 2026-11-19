"""Fjärrstyrning in TKL (#36 del c, FR1–FR4, FR8, FR11–FR14, FR17, FR28): TKL started in the
remote role connects as the station protocol's client kind remote with its remote area, waits for
the approval and follows it; it takes or declines an offer, asks for a route from a station's
remote catalogue and takes it away, and clears for the whole station it controls. A station's
own TKL reads the same fjärrbild when it controls a neighbour (FR3). A pretend hub stands in for
Drift and for the station's interlocking, which answers the routes: locked, no with a reason, or
not at all until Hubben's ten seconds are up. Nothing here names a station (RS13)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts import station
from contracts.reasons import Reason
from contracts.station_outside import StationOutside
from contracts.tkl import TklConnection, TklFjarr, TklRemoteAreas, TklState
from tkl.app import create_app
from tkl.tests.test_app import API, PIN, set_up

KEY = "fjarr-nyckel"
HUB = "http://hubben.invalid"
RELAY = "http://relaet.invalid/relay/hubben"
CONTEXT = station.MeetContext(meet_id="provmote", version=1, game_day=1, epoch=0)
CLOCK = station.Clock(time="06:10", seconds=22200, running=True, speed=4, game_day=1)
HOME, NEXT, FAR = "vby", "mby", "oby"
NAMES = {HOME: "Västby", NEXT: "Mittby", FAR: "Östby"}


def outside_of(place: str) -> StationOutside:
    """A station with two tracks, an exit on each side and a catalogue of four routes."""
    routes = [("11-1", "11", "V", "1"), ("11-2", "11", "V", "2"), ("12-1", "12", "O", "1")]
    routes.append(("13-2", "13", "O", "2"))
    return StationOutside.model_validate(
        {
            "station_id": place,
            "name": NAMES[place],
            "tracks": [{"id": "1", "label": "Spår 1"}, {"id": "2", "label": "Spår 2"}],
            "exits": [{"id": "V", "side": "left"}, {"id": "O", "side": "right"}],
            "remote_routes": [
                {"id": i, "start": s, "end": t, "exit": e, "track": t, "direction": "in"}
                for i, s, e, t in routes
            ],
            "overview": {
                "columns": 12,
                "rows": 2,
                "tracks": [
                    {"id": "t1", "row": 0, "start": 2, "end": 10, "track": "1"},
                    {"id": "t2", "row": 1, "start": 2, "end": 10, "track": "2"},
                ],
                "signals": [
                    {"name": "11", "row": 0, "column": 1, "towards": "right"},
                    {"name": "12", "row": 0, "column": 11, "towards": "left"},
                    {"name": "13", "row": 1, "column": 11, "towards": "left"},
                ],
                "exits": [
                    {"exit": "V", "row": 0, "column": 0},
                    {"exit": "O", "row": 0, "column": 12},
                ],
                "routes": {i: [f"t{t}"] for i, _, _, t in routes},
            },
        }
    )


class PretendHub:
    """Hubben with three stations along a line, and the stations' own interlockings: a route
    whose track holds a locked route is refused, one in `silent` gets no answer."""

    def __init__(self) -> None:
        self.requests: list[station.ConnectRequest] = []
        self.commands: list[station.Command] = []
        self.approved: list[str] = []
        self.key_given = False
        self.kind = station.ClientKind.REMOTE
        self.offers: dict[str, int] = {}
        self.controls: list[str] = []
        self.asks: dict[str, station.RemoteRouteHere] = {}
        self.locked: dict[str, list[station.LockedRoute]] = {}
        self.silent: set[str] = set()
        self.down: set[str] = set()
        self.meet = True
        self.overviews = 0
        self.revoked = False

    @property
    def client_id(self) -> str:
        return f"{self.kind.value}-1"

    def reply(self) -> station.ConnectReply:
        key = None
        if self.approved and not self.key_given:
            key, self.key_given = KEY, True
        status = (
            station.ApprovalStatus.APPROVED if self.approved else station.ApprovalStatus.WAITING
        )
        return station.ConnectReply(
            client_id=self.client_id, status=status, places=self.approved, key=key, relay=RELAY
        )

    def place(self, place: str) -> station.OverviewPlace:
        mine = place in self.controls
        controller = (
            station.Receiver(client_id=self.client_id, kind=self.kind, name="Fjärr")
            if mine
            else None
        )
        locked = self.locked.get(place, [])
        return station.OverviewPlace(
            place=station.Neighbour(place=place, code=place, name=NAMES[place]),
            mode=station.PlaceMode.REMOTE
            if mine
            else station.PlaceMode.OFFERED
            if place in self.offers
            else station.PlaceMode.MANNED,
            controllable=True,
            controller=controller,
            level=2,
            outside=outside_of(place),
            route_state=station.RouteState(locked=locked),
            routes=[a for key, a in self.asks.items() if key.endswith("@" + place)],
        )

    def overview(self) -> station.Overview:
        self.overviews += 1
        return station.Overview(
            context=CONTEXT, clock=CLOCK, places=[self.place(p) for p in (HOME, NEXT, FAR)]
        )

    def offer(self, place: str) -> station.OfferHere:
        return station.OfferHere(
            place=place,
            to=station.Receiver(client_id=self.client_id, kind=self.kind, name="Fjärr"),
            expires_in=self.offers[place],
        )

    def snapshot(self, place: str) -> station.Snapshot:
        return station.Snapshot(
            place=station.Neighbour(place=place, code=place, name=NAMES[place]),
            context=CONTEXT,
            clock=CLOCK,
            place_revision=1,
            mode=station.PlaceMode.REMOTE if place in self.controls else station.PlaceMode.MANNED,
            offers=[self.offer(p) for p in self.offers],
            controls=list(self.controls),
        )

    def answer(self, place: str, ask: station.RouteRequest) -> station.Reply | None:
        """The station's interlocking: locks the route, or says no with its reason."""
        key = f"{ask.request_id}@{place}"
        here = station.RemoteRouteHere(
            request_id=ask.request_id,
            route=ask.route,
            state=station.RemoteRouteState.REQUESTED,
            by=self.client_id,
            asked_at="06:10",
            answer_in=10,
        )
        if ask.route in self.silent:
            self.asks[key] = here
            return None
        track = outside_of(place).remote_routes
        wanted = next(r for r in track if r.id == ask.route)
        busy = {r.track for held in self.locked.get(place, []) for r in track if r.id == held.route}
        if wanted.track in busy:
            self.asks[key] = here.model_copy(
                update={
                    "state": station.RemoteRouteState.REFUSED,
                    "reason": Reason.CONFLICTING_ROUTE,
                    "answer_in": None,
                }
            )
            return None
        self.asks[key] = here.model_copy(
            update={"state": station.RemoteRouteState.LOCKED, "answer_in": None}
        )
        self.locked.setdefault(place, []).append(
            station.LockedRoute(
                route=ask.route, by=station.RouteBy.REMOTE, request_id=ask.request_id
            )
        )
        return None

    def ten_seconds(self) -> None:
        """Hubben's ten seconds are up: a route the station did not answer is a no (FR14)."""
        for key, ask in list(self.asks.items()):
            if ask.state == station.RemoteRouteState.REQUESTED:
                self.asks[key] = ask.model_copy(
                    update={
                        "state": station.RemoteRouteState.REFUSED,
                        "reason": Reason.STATION_NOT_ANSWERING,
                        "answer_in": None,
                    }
                )

    def command(self, command: station.Command) -> station.Reply:
        self.commands.append(command)
        place = command.place

        def rejected(reason: Reason) -> station.Reply:
            return station.Reply(
                message_id=command.message_id,
                status=station.ReplyStatus.REJECTED,
                reason=reason,
                message=reason.value,
                snapshot=self.snapshot(place),
            )

        if command.action == station.Action.PLACE_OFFER_ANSWER:
            if place not in self.offers:
                return rejected(Reason.OFFER_NOT_PENDING)
            del self.offers[place]
            if station.OfferAnswer.model_validate(command.payload).accept:
                self.controls.append(place)
        elif command.action == station.Action.ROUTE_REQUEST:
            if place not in self.controls:
                return rejected(Reason.NOT_CONTROLLER)
            if "contact" in self.down:
                self.down.discard("contact")
                return rejected(Reason.NO_CONTACT)
            self.answer(place, station.RouteRequest.model_validate(command.payload))
        elif command.action == station.Action.ROUTE_CANCEL:
            ref = station.RouteCancel.model_validate(command.payload)
            key = f"{ref.request_id}@{place}"
            ask = self.asks[key]
            self.asks[key] = ask.model_copy(update={"state": station.RemoteRouteState.CANCELLED})
            self.locked[place] = [
                r for r in self.locked.get(place, []) if r.request_id != ref.request_id
            ]
        return station.Reply(
            message_id=command.message_id,
            status=station.ReplyStatus.ACCEPTED,
            snapshot=self.snapshot(place),
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        base = f"{request.url.scheme}://{request.url.host}"
        if base in self.down:
            raise httpx.ConnectError("no route to host", request=request)
        path = request.url.path.removeprefix("/relay/hubben")
        if request.method == "GET" and path == "/api/hub":
            return httpx.Response(200, json={"name": "Provhubben"})
        if request.method == "GET" and path == "/api/drift/1/now":
            return httpx.Response(200, json={"name": "Provmötet"})
        if request.method == "GET" and path == "/api/drift/1/package":
            if not self.meet:
                return httpx.Response(404, json={"detail": "Ingen träff."})
            return httpx.Response(
                200,
                json={
                    "places": [
                        {"id": p, "code": p.capitalize(), "name": n, "kind": "manned"}
                        for p, n in NAMES.items()
                    ]
                    + [{"id": "hpl", "code": "Hpl", "name": "Hållplatsen", "kind": "halt"}],
                    "remote_areas": [
                        {"id": "ost", "name": "Östra", "places": [NEXT, FAR]},
                        {"id": "trasig", "name": "", "places": []},
                    ],
                },
            )
        if request.method == "POST" and path == "/api/station/1/connect":
            self.requests.append(station.ConnectRequest.model_validate_json(request.content))
            self.kind = self.requests[-1].kind
            return httpx.Response(201, json=self.reply().model_dump(mode="json"))
        if request.method == "GET" and path == f"/api/station/1/connect/{self.client_id}":
            return httpx.Response(200, json=self.reply().model_dump(mode="json"))
        if request.headers.get("Authorization") != f"Bearer {KEY}":
            return httpx.Response(401, json={"detail": "Nyckeln gäller inte."})
        if request.method == "GET" and path == "/api/station/1/overview":
            if self.revoked:
                return httpx.Response(401, json={"detail": "Nyckeln gäller inte."})
            return httpx.Response(200, json=self.overview().model_dump(mode="json"))
        if request.method == "GET" and path.startswith("/api/station/1/places/"):
            place = path.rsplit("/", 1)[1]
            reach = {*self.approved, *self.controls, *self.offers}
            if place not in reach:
                return httpx.Response(403, json={"detail": "Inte godkänd för driftplatsen."})
            return httpx.Response(200, json=self.snapshot(place).model_dump(mode="json"))
        if request.method == "POST" and path == "/api/station/1/commands":
            command = station.Command.model_validate_json(request.content)
            return httpx.Response(200, json=self.command(command).model_dump(mode="json"))
        return httpx.Response(404, json={"detail": "Finns inte."})


def tkl_with(tmp_path: Path, hub: PretendHub) -> TestClient:
    app = create_app(
        tmp_path,
        http=lambda: httpx.Client(transport=httpx.MockTransport(hub.handle)),
        discover=lambda: [],
    )
    return TestClient(app)


def remote_set_up(client: TestClient, **more: Any) -> TklState:
    given = {"name": "Fjärr Östra", "pin": PIN, **more}
    made = client.post(API + "/fjarr/setup", json=given)
    assert made.status_code == 201, made.text
    return TklState.model_validate(made.json())


def picture(client: TestClient) -> TklFjarr:
    answer = client.get(API + "/fjarr")
    assert answer.status_code == 200, answer.text
    return TklFjarr.model_validate(answer.json())


def command(client: TestClient, place: str, action: str, **payload: Any) -> station.Reply:
    sent = client.post(
        API + "/fjarr/commands",
        json={
            "message_id": f"fj-{uuid4().hex}",
            "place": place,
            "context": CONTEXT.model_dump(mode="json"),
            "action": action,
            "payload": payload,
        },
    )
    assert sent.status_code == 200, sent.text
    return station.Reply.model_validate(sent.json())


def route_of(seen: TklFjarr, place: str, request_id: str) -> station.RemoteRouteHere:
    assert seen.overview is not None
    here = next(p for p in seen.overview.places if p.place.place == place)
    return next(r for r in here.routes if r.request_id == request_id)


def locked_at(seen: TklFjarr, place: str) -> list[str]:
    assert seen.overview is not None
    here = next(p for p in seen.overview.places if p.place.place == place)
    return [r.route for r in (here.route_state.locked if here.route_state else [])]


@pytest.fixture
def remote(tmp_path: Path) -> tuple[TestClient, PretendHub]:
    """The remote interlocking, connected and approved for its area."""
    hub = PretendHub()
    client = tkl_with(tmp_path, hub)
    remote_set_up(client, area="ost")
    made = client.post(API + "/fjarr/connection", json={"address": HUB})
    assert made.status_code == 200, made.text
    hub.approved = [NEXT, FAR]
    assert client.get(API + "/connection").json()["status"] == "approved"
    return client, hub


def test_the_remote_role_connects_with_its_area_and_waits_for_the_approval(
    tmp_path: Path,
) -> None:
    """FR1, FR4: first start offers the remote role with a name and a remote area; it connects
    as the client kind remote with no station, waits under Väntar and follows after the key."""
    hub = PretendHub()
    client = tkl_with(tmp_path, hub)
    state = remote_set_up(client, area="ost")
    assert state.unlocked and state.remote is not None
    assert (state.remote.name, state.remote.area, state.remote.places) == ("Fjärr Östra", "ost", [])
    assert state.station is not None and state.station.station_id == "fjarr-ostra"
    assert client.post(API + "/fjarr/setup", json={"name": "X", "pin": PIN}).status_code == 409
    # The plan's remote areas at the hub, and its places to write by hand; never a halt.
    areas = TklRemoteAreas.model_validate(
        client.get(API + "/fjarr/areas", params={"address": HUB}).json()
    )
    assert [(a.id, a.places) for a in areas.areas] == [("ost", [NEXT, FAR])]
    assert [p.place for p in areas.places] == [HOME, NEXT, FAR]
    hub.meet = False
    none = TklRemoteAreas.model_validate(
        client.get(API + "/fjarr/areas", params={"address": HUB}).json()
    )
    assert (none.areas, none.message) == (
        [],
        "Hubben har ingen träff igång. Skriv driftplatserna i stället.",
    )
    # Anslut: the area chosen at first start, as the client kind remote with no station.
    made = client.post(API + "/fjarr/connection", json={"address": HUB, "code": " 123456 "})
    assert made.status_code == 200, made.text
    asked = hub.requests[-1]
    assert (asked.kind, asked.remote_area, asked.wants, asked.code) == (
        "remote",
        "ost",
        [],
        "123456",
    )
    assert (asked.station_id, asked.outside, asked.name) == (None, None, "Fjärr Östra")
    shown = TklConnection.model_validate(made.json())
    assert (shown.connected, shown.status, shown.places) == (True, "waiting", [])
    assert client.get(API + "/fjarr").status_code == 409, "no key before the approval"
    # Approved: the key comes once and stays in TKL's server; TKL keeps following.
    hub.approved = [NEXT, FAR]
    followed = TklConnection.model_validate(client.get(API + "/connection").json())
    assert (followed.status, followed.places) == ("approved", [NEXT, FAR])
    assert KEY not in client.get(API + "/connection").text
    seen = picture(client)
    assert seen.overview is not None and seen.client_id == "remote-1"
    assert [p.place.place for p in seen.overview.places] == [HOME, NEXT, FAR]
    assert (seen.controls, seen.offers, seen.stale) == ([], [], False)
    # Driftplatser written by hand go as wants, without the plan's area.
    client.post(API + "/fjarr/connection", json={"address": HUB, "places": [FAR, NEXT, FAR]})
    asked = hub.requests[-1]
    assert (asked.wants, asked.remote_area) == ([FAR, NEXT], None)


def test_a_station_has_no_remote_connection_but_reads_the_same_picture(tmp_path: Path) -> None:
    """FR3: a station's own TKL controls a neighbour with the same fjärrbild, as the same client;
    its own place's snapshot says what it controls, so the web app shows the tab Fjärr."""
    hub = PretendHub()
    client = tkl_with(tmp_path, hub)
    assert set_up(client).status_code == 201
    assert client.get(API + "/state").json()["remote"] is None
    refused = client.post(API + "/fjarr/connection", json={"address": HUB})
    assert refused.status_code == 409
    assert client.post(API + "/connection", json={"address": HUB}).status_code == 200
    assert hub.requests[-1].kind == "tkl"
    hub.approved = [HOME]
    client.get(API + "/connection")
    hub.offers[NEXT] = 45
    view = client.get(API + f"/places/{HOME}").json()
    assert [o["place"] for o in view["snapshot"]["offers"]] == [NEXT], "the tab Fjärr shows"
    seen = picture(client)
    assert [o.place for o in seen.offers] == [NEXT]
    taken = command(client, NEXT, "place.offer.answer", accept=True)
    assert taken.status == "accepted" and taken.snapshot.controls == [NEXT]
    seen = picture(client)
    assert seen.controls == [NEXT] and seen.offers == []
    assert hub.commands[-1].client_id == "tkl-1"
    view = client.get(API + f"/places/{HOME}").json()
    assert view["snapshot"]["controls"] == [NEXT]


def test_offers_are_taken_or_declined(remote: tuple[TestClient, PretendHub]) -> None:
    """FR8: the offers wait with the time left; Ta emot makes the station Fjärrstyrd and
    Avböj leaves it; an offer that has run out is refused by Hubben."""
    client, hub = remote
    hub.offers = {NEXT: 52, FAR: 7}
    seen = picture(client)
    assert [(o.place, o.expires_in) for o in seen.offers] == [(NEXT, 52), (FAR, 7)]
    assert seen.overview is not None
    assert [p.mode for p in seen.overview.places] == ["manned", "offered", "offered"]
    taken = command(client, NEXT, "place.offer.answer", accept=True)
    assert taken.status == "accepted"
    declined = command(client, FAR, "place.offer.answer", accept=False)
    assert declined.status == "accepted"
    seen = picture(client)
    assert (seen.controls, seen.offers) == ([NEXT], [])
    assert seen.overview is not None
    assert [p.mode for p in seen.overview.places] == ["manned", "remote", "manned"]
    late = command(client, FAR, "place.offer.answer", accept=True)
    assert (late.status, late.reason) == ("rejected", "offer_not_pending")
    assert [c.client_id for c in hub.commands] == ["remote-1"] * 3


def test_a_route_is_locked_refused_or_not_answered(remote: tuple[TestClient, PretendHub]) -> None:
    """FR11–FR14: TKL asks with its own request id; the picture shows only what the station
    reports: locked, a no with the station's reason, or Hubben's no after ten seconds. A route
    refused leaves the picture as it was. Out of contact Hubben says no (FR28), and the same
    route asked again goes through."""
    client, hub = remote
    hub.offers = {NEXT: 50}
    command(client, NEXT, "place.offer.answer", accept=True)
    asked = command(client, NEXT, "route.request", request_id="fj-1", route="11-1")
    assert asked.status == "accepted"
    sent = hub.commands[-1]
    assert (sent.place, sent.action, sent.payload) == (
        NEXT,
        "route.request",
        {"request_id": "fj-1", "route": "11-1"},
    )
    seen = picture(client)
    assert route_of(seen, NEXT, "fj-1").state == "locked"
    assert locked_at(seen, NEXT) == ["11-1"]
    # A route over the same track: the station's interlocking says no; nothing else changes.
    command(client, NEXT, "route.request", request_id="fj-2", route="12-1")
    seen = picture(client)
    no = route_of(seen, NEXT, "fj-2")
    assert (no.state, no.reason) == ("refused", "conflicting_route")
    assert locked_at(seen, NEXT) == ["11-1"]
    # No answer: requested until Hubben's ten seconds are up, then a no (FR14).
    hub.silent.add("13-2")
    command(client, NEXT, "route.request", request_id="fj-3", route="13-2")
    assert route_of(picture(client), NEXT, "fj-3").state == "requested"
    hub.ten_seconds()
    late = route_of(picture(client), NEXT, "fj-3")
    assert (late.state, late.reason) == ("refused", "station_not_answering")
    assert locked_at(picture(client), NEXT) == ["11-1"]
    # Out of contact: Hubben's no comes back at once, and the next try goes through (FR28).
    hub.silent.clear()
    hub.down.add("contact")
    first = command(client, NEXT, "route.request", request_id="fj-4", route="13-2")
    assert (first.status, first.reason) == ("rejected", "no_contact")
    again = command(client, NEXT, "route.request", request_id="fj-5", route="13-2")
    assert again.status == "accepted"
    assert locked_at(picture(client), NEXT) == ["11-1", "13-2"]


def test_ta_bort_cancels_a_route(remote: tuple[TestClient, PretendHub]) -> None:
    """Ta bort is route.cancel with the request's id; the station releases the route, and the
    picture shows that only when the station reports it."""
    client, hub = remote
    hub.offers = {NEXT: 50}
    command(client, NEXT, "place.offer.answer", accept=True)
    command(client, NEXT, "route.request", request_id="fj-1", route="11-2")
    assert locked_at(picture(client), NEXT) == ["11-2"]
    gone = command(client, NEXT, "route.cancel", request_id="fj-1")
    assert gone.status == "accepted"
    assert hub.commands[-1].payload == {"request_id": "fj-1"}
    seen = picture(client)
    assert route_of(seen, NEXT, "fj-1").state == "cancelled"
    assert locked_at(seen, NEXT) == []


def test_the_overview_comes_through_the_relay_and_stays_when_the_hub_is_gone(
    remote: tuple[TestClient, PretendHub],
) -> None:
    """The overview through the cloud's relay when the hub's own address cannot be reached
    (SYNK-11), and the last good picture, marked old, when neither can."""
    client, hub = remote
    first = picture(client)
    hub.down.add(HUB)
    through = picture(client)
    assert through.stale is False and through.overview is not None
    assert hub.overviews == 2
    hub.down.add("http://relaet.invalid")
    kept = picture(client)
    assert (kept.stale, kept.message) == (True, "Ingen kontakt med hubben.")
    assert kept.overview == through.overview == first.overview


def test_clearance_for_a_controlled_station(remote: tuple[TestClient, PretendHub]) -> None:
    """FR17: the one who controls a station clears for the whole station, with the normal
    clearance actions and the station as the place; Hubben decides what it may read."""
    client, hub = remote
    assert client.get(API + f"/fjarr/places/{HOME}").status_code == 403
    hub.offers = {HOME: 30}
    command(client, HOME, "place.offer.answer", accept=True)
    view = client.get(API + f"/fjarr/places/{HOME}")
    assert view.status_code == 200, view.text
    assert view.json()["snapshot"]["place"]["place"] == HOME
    answered = command(client, HOME, "clearance.response", clearance_id="k-1", approved=True)
    assert answered.status == "accepted"
    sent = hub.commands[-1]
    assert (sent.client_id, sent.place, sent.action, sent.payload) == (
        "remote-1",
        HOME,
        "clearance.response",
        {"clearance_id": "k-1", "approved": True},
    )


def test_a_revoked_key_ends_the_connection(remote: tuple[TestClient, PretendHub]) -> None:
    """Hubben no longer knows the key: TKL drops it and says so, and asks to connect again."""
    client, hub = remote
    picture(client)
    hub.revoked = True
    gone = client.get(API + "/fjarr")
    assert (gone.status_code, gone.json()["detail"]) == (401, "Nyckeln gäller inte.")
    assert client.get(API + "/fjarr").status_code == 409, "no key any more"
