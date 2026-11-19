"""Fjärrstyrning over HTTP (#36 del a, TRAFIK-34, FR4, FR9): a remote interlocking and a
station's TKL on the hub's meet, as pretend clients of the station protocol. Trafikledningen sees
the remote client in Klienter with its area, approves it, and takes the station over and gives it
back in Nu; the remote picture reads the overview, also through the cloud's relay."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from contracts import drift, station, sync
from drift.store import key_hash
from hub import station_api
from hub.running import Running
from hub.stores import AnyRun
from hub.tests.test_drift_api import API, code_of
from hub.tests.test_drift_api import hub as hub
from hub.tests.test_drift_api import running as running
from hub.tests.test_station_api import Client

STATION = "/api/station/1"
CATALOGUE = [
    {"id": "A-1", "start": "A", "end": "1", "exit": "v", "track": "1", "direction": "in"},
]


class Remote(Client):
    """The remote interlocking: a TKL with no station, with its area in wants (TKL47)."""

    def __init__(self, hub: TestClient, code: str, wants: list[str]) -> None:
        response = hub.post(
            STATION + "/connect",
            json={
                "kind": "remote",
                "name": "Fjärr Västra",
                "software": "TKL 0.1.0",
                "wants": wants,
                "code": code,
            },
        )
        assert response.status_code == 201, response.text
        reply = station.ConnectReply.model_validate(response.json())
        self.hub = hub
        self.client_id = reply.client_id
        self.headers: dict[str, str] = {}


def tkl_with_catalogue(hub: TestClient, code: str, place: str) -> Client:
    """A station's TKL that brings an outside with a remote catalogue."""
    response = hub.post(
        STATION + "/connect",
        json={
            "kind": "tkl",
            "name": "TKL Mellanå",
            "software": "TKL 0.1.0",
            "wants": [place],
            "code": code,
            "level": 1,
            "outside": {
                "station_id": "mellana",
                "name": "Mellanå",
                "tracks": [{"id": "1", "label": "Spår 1"}],
                "exits": [{"id": "v", "side": "left"}, {"id": "o", "side": "right"}],
                "remote_routes": CATALOGUE,
                "remote_receivers": ["remote"],
            },
        },
    )
    assert response.status_code == 201, response.text
    client = Client.__new__(Client)
    client.hub = hub
    client.client_id = station.ConnectReply.model_validate(response.json()).client_id
    client.headers = {}
    return client


def approve(hub: TestClient, client: Client, places: list[str]) -> dict[str, Any]:
    response = hub.post(
        API + "/clients/approve", json={"client_id": client.client_id, "places": places}
    )
    assert response.status_code == 200, response.text
    assert client.poll().key is not None
    answer: dict[str, Any] = response.json()
    return answer


def place_status(hub: TestClient, place: str) -> drift.AutomationPlaceStatus:
    status = drift.AutomationStatus.model_validate(hub.get(API + "/automation").json())
    return next(p for p in status.places if p.place == place)


def test_klienter_shows_the_remote_client_and_nu_takes_over_and_gives_back(
    running: TestClient,
) -> None:
    code = code_of(running)
    remote = Remote(running, code, ["asn", "mla", "sjv"])
    listed = {c["client_id"]: c for c in running.get(API + "/clients").json()}
    shown = drift.Client.model_validate(listed[remote.client_id])
    assert (shown.kind, shown.status, shown.station_id) == ("remote", "waiting", None)
    assert [w.place for w in shown.wanted] == ["asn", "mla", "sjv"]
    approved = drift.Client.model_validate(approve(running, remote, ["mla", "sjv"]))
    assert approved.places == ["mla", "sjv"]
    mellana = tkl_with_catalogue(running, code, "mla")
    approve(running, mellana, ["mla"])
    assert mellana.snapshot("mla").remote is not None
    offered = mellana.command(station.Action.PLACE_OFFER, "mla", to=remote.client_id)
    assert offered.status == station.ReplyStatus.ACCEPTED, offered.message
    taken = remote.command(station.Action.PLACE_OFFER_ANSWER, "mla", accept=True)
    assert taken.snapshot.mode == station.PlaceMode.REMOTE
    listed = {c["client_id"]: c for c in running.get(API + "/clients").json()}
    assert listed[remote.client_id]["controls"] == ["mla"]
    status = place_status(running, "mla")
    assert (status.mode, status.controller, status.controllable) == (
        drift.PlaceMode.REMOTE,
        remote.client_id,
        True,
    )
    # Ta över: the automation has it, and Trafikledningen may give it back to the controller.
    took = running.post(API + "/automation/place", json={"place": "mla", "action": "leave"})
    assert took.status_code == 200, took.text
    status = place_status(running, "mla")
    assert (status.mode, status.back_to) == (drift.PlaceMode.AUTOMATIC, remote.client_id)
    gave = running.post(
        API + "/automation/place",
        json={"place": "mla", "action": "remote", "client_id": remote.client_id},
    )
    assert gave.status_code == 200, gave.text
    assert place_status(running, "mla").controller == remote.client_id
    refused = running.post(
        API + "/automation/place",
        json={"place": "nby", "action": "remote", "client_id": remote.client_id},
    )
    assert refused.status_code == 409
    log = [e["kind"] for e in running.get(API + "/log?place=mla").json()]
    assert log[:4] == ["place.remote", "place.left", "place.offer_answered", "place.offered"]


def test_the_remote_picture_reads_the_overview_also_through_the_relay(
    running: TestClient,
) -> None:
    code = code_of(running)
    remote = Remote(running, code, ["mla"])
    approve(running, remote, ["mla"])
    seen = running.get(STATION + "/overview", params={"places": "mla,asn"}, headers=remote.headers)
    assert seen.status_code == 200, seen.text
    overview = station.Overview.model_validate(seen.json())
    assert [p.place.place for p in overview.places] == ["mla", "asn"]
    assert all(p.controller is None for p in overview.places)
    far = running.get(STATION + "/overview", params={"places": "nby"}, headers=remote.headers)
    assert far.status_code == 403, "Norrby is not next to Mellanå"
    assert running.get(STATION + "/overview").status_code == 401
    # Through the cloud's relay, the same call with the key's hash (SYNK-11).
    store = running.app.state.running.store  # type: ignore[attr-defined]
    assert isinstance(running.app.state.running, Running)  # type: ignore[attr-defined]
    key = remote.headers["Authorization"].split()[1]
    answer = station_api.relayed(
        AnyRun(lambda: store),
        sync.RelayCall(
            id="relay-1",
            kind=sync.RelayKind.OVERVIEW,
            key_hash=key_hash(key),
            places=["mla"],
        ),
        lambda: None,
    )
    assert answer.status == 200 and answer.overview is not None
    assert [p.place.place for p in answer.overview.places] == ["mla"]
