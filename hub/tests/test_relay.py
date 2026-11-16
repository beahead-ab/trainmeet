"""Reläet (SYNK-05, SYNK-11, SYNK-13, SYNK-22): a phone outside the meet's network reaches the
Pi through the cloud. The Pi fetches the calls on its own connection and answers them; the
cloud keeps nothing. Two hubs run here in one process, as in test_synk."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts import station, sync
from hub import station_api
from hub.tests.test_planering import DRIFT
from hub.tests.test_synk import cloud, follower, pi_for, started  # noqa: F401
from synk import relay as relay_module
from synk.relay import NoAnswer, NotConnected, Relay

STATION = "/api/station/1"


@contextmanager
def relaying(pi: TestClient, cloud: TestClient) -> Iterator[None]:  # noqa: F811
    """The Pi fetches the calls the cloud keeps for it, as it does in the background."""
    stop = Event()
    [reach] = follower(pi).links.reaches()

    def loop() -> None:
        while not stop.is_set():
            follower(pi).relay(reach, wait=0.2)

    thread = Thread(target=loop, daemon=True)
    thread.start()
    relay: Relay = cloud.app.state.relay  # type: ignore[attr-defined]
    hub = follower(pi).links.hub_id()
    for _ in range(100):
        if relay.connected(hub):
            break
        time.sleep(0.05)
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)


def manned(pi: TestClient) -> str:
    package = pi.get(DRIFT + "/package").json()
    return str(next(p["id"] for p in package["places"] if p["kind"] == "manned"))


def hub_id(pi: TestClient) -> str:
    return str(follower(pi).links.hub_id())


def connect(through: TestClient, base: str, code: str, place: str) -> station.ConnectReply:
    response = through.post(
        base + "/connect",
        json={
            "kind": "tmbox_app",
            "name": "Telefonen",
            "software": "TMBox 3.0.0",
            "wants": [place],
            "code": code,
        },
    )
    assert response.status_code == 201, response.text
    return station.ConnectReply.model_validate(response.json())


def test_a_phone_outside_the_meets_network_reaches_the_pi_through_the_cloud(
    cloud: TestClient,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pi = started(pi_for(cloud, tmp_path), cloud)
    place = manned(pi)
    code = pi.get(DRIFT + "/connect").json()["code"]
    # On the meet's network the Pi tells the client the relay's address (SYNK-11).
    near = connect(pi, STATION, code, place)
    assert near.relay == f"http://moln/relay/{hub_id(pi)}"
    base = f"/relay/{hub_id(pi)}{STATION}"
    with relaying(pi, cloud):
        far = connect(cloud, base, code, place)
        assert far.status == station.ApprovalStatus.WAITING and far.relay == near.relay
        # The dispatcher approves it on the Pi, under Klienter, as any client.
        approved = pi.post(
            DRIFT + "/clients/approve", json={"client_id": far.client_id, "places": [place]}
        )
        assert approved.status_code == 200, approved.text
        reply = station.ConnectReply.model_validate(
            cloud.get(f"{base}/connect/{far.client_id}").json()
        )
        assert reply.status == station.ApprovalStatus.APPROVED and reply.key
        headers = {"Authorization": f"Bearer {reply.key}"}
        # The key came once, through the relay too.
        again = cloud.get(f"{base}/connect/{far.client_id}").json()
        assert again["key"] is None
        # The snapshot and the commands, with the same key, as on the meet's network.
        shown = cloud.get(f"{base}/places/{place}", headers=headers)
        assert shown.status_code == 200, shown.text
        snapshot = station.Snapshot.model_validate(shown.json())
        command = {
            "message_id": "relay-lookup-1",
            "client_id": far.client_id,
            "place": place,
            "context": snapshot.context.model_dump(mode="json"),
            "action": station.Action.TRAIN_LOOKUP.value,
            "payload": {"train_number": "1"},
        }
        answered = cloud.post(f"{base}/commands", json=command, headers=headers)
        assert answered.status_code == 200, answered.text
        assert station.Reply.model_validate(answered.json()).message_id == "relay-lookup-1"
        # The phone's address for push is kept on the Pi, which sends the notices (F20).
        token = {"token": "ef" * 32}
        assert cloud.put(f"{base}/push", json=token, headers=headers).status_code == 204
        store = pi.app.state.running.store  # type: ignore[attr-defined]
        assert [t.token for t, _ in store.push_targets(store.current())] == ["ef" * 32]
        assert cloud.delete(f"{base}/push", headers=headers).status_code == 204
        assert store.push_targets(store.current()) == []
        # The same key is good on the meet's network: it is one client, on the Pi.
        assert pi.get(f"{STATION}/places/{place}", headers=headers).status_code == 200
        # The event stream: a hint that the place changed.
        monkeypatch.setattr(station_api, "STREAM_SECONDS", 0)
        with cloud.stream("GET", f"{base}/places/{place}/events", headers=headers) as stream:
            assert stream.status_code == 200
            assert "event: changed" in "".join(stream.iter_text())
        # A wrong key is told so by the Pi; a place it is not approved for too.
        wrong = cloud.get(f"{base}/places/{place}", headers={"Authorization": "Bearer " + "x" * 40})
        assert wrong.status_code == 401
        other = next(
            p["id"] for p in pi.get(DRIFT + "/package").json()["places"] if p["id"] != place
        )
        assert cloud.get(f"{base}/places/{other}", headers=headers).status_code in (403, 404)


def test_the_relay_says_when_the_hub_is_not_connected(
    cloud: TestClient,  # noqa: F811
    tmp_path: Path,
) -> None:
    pi = started(pi_for(cloud, tmp_path), cloud)
    code = pi.get(DRIFT + "/connect").json()["code"]
    # A hub that has never fetched its calls, and one nobody knows, are not connected.
    for hub in (hub_id(pi), "okand-hubb"):
        refused = cloud.post(
            f"/relay/{hub}{STATION}/connect",
            json={"kind": "tkl", "name": "TKL", "software": "TKL 0.1.0", "code": code},
        )
        assert refused.status_code == 503
        assert "inte ansluten" in refused.json()["detail"]
    # Only the Pi's own key fetches its calls.
    stranger = cloud.get(
        f"/api/sync/1/meets/{follower(pi).links.reaches()[0].meet}/relay",
        headers={"Authorization": "Bearer " + "y" * 43, "TrainMeet-Sync": sync.PROTOCOL},
    )
    assert stranger.status_code == 401


def test_the_relay_keeps_nothing_and_times_out() -> None:
    """The queue in itself: a call waits for its answer, and is gone when it times out."""
    import asyncio

    relay = Relay()
    call = sync.RelayCall(id="call-1", kind=sync.RelayKind.CONNECTION, client_id="tkl-1")

    async def scenario() -> Any:
        with pytest.raises(NotConnected):
            await relay.ask("pi", call)
        assert await relay.take("pi", 0) == []
        asked = asyncio.ensure_future(relay.ask("pi", call, timeout=2))
        [taken] = await relay.take("pi", 1)
        assert taken == call
        assert relay.answer("pi", sync.RelayAnswer(id="call-1", status=404, detail="Nej."))
        answer = await asked
        assert (answer.status, answer.detail) == (404, "Nej.")
        # An answer nobody waits for is refused, and a call nobody answers times out.
        assert not relay.answer("pi", sync.RelayAnswer(id="call-1", status=200))
        with pytest.raises(NoAnswer):
            await relay.ask("pi", call, timeout=0.1)
        assert await relay.take("pi", 0) == []  # nothing is left behind
        return True

    assert asyncio.run(scenario())


def test_a_hub_that_stops_fetching_is_not_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    relay = Relay()
    asyncio.run(relay.take("pi", 0))
    assert relay.connected("pi")
    later = time.monotonic() + relay_module.GONE + 1
    monkeypatch.setattr(time, "monotonic", lambda: later)
    assert not relay.connected("pi")
