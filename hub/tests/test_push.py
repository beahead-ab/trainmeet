"""Push (F20, SYNK-05, BOXIOS-12): a phone approved for a place is told of a request to it, the
answer and a train on its way, and answers Ge klart or Neka from the notice. Without Apple's key
the notices go to a pretend service; a Pi sends its notices to the cloud."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from contracts import station, sync
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.push import Pusher, Senders
from hub.tests.test_drift_api import API, PIN, code_of
from hub.tests.test_synk import cloud, follower, pi_for, started  # noqa: F401
from synk.push import ApnsPush, ApnsSettings, FakePush, payload

STATION = "/api/station/1"
PHONE = "ab" * 32
TKL = "cd" * 32


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "prov.db"))
    assert client.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN}).status_code == 201
    assert client.post(API + "/start", json={"version": 1}).status_code == 201
    return client


class Recorder:
    name = "recorder"

    def __init__(self) -> None:
        self.sent: list[sync.Push] = []

    def send(self, pushes: list[sync.Push]) -> None:
        self.sent.extend(pushes)


def approved(hub: TestClient, name: str, place: str) -> tuple[str, dict[str, str]]:
    connected = hub.post(
        STATION + "/connect",
        json={
            "kind": "tmbox_app",
            "name": name,
            "software": "TMBox 3.0.0",
            "wants": [place],
            "code": code_of(hub),
        },
    )
    client_id = connected.json()["client_id"]
    approval = {"client_id": client_id, "places": [place]}
    assert hub.post(API + "/clients/approve", json=approval).status_code == 200
    key = hub.get(f"{STATION}/connect/{client_id}").json()["key"]
    return client_id, {"Authorization": f"Bearer {key}"}


def command(
    hub: TestClient, client: str, headers: dict[str, str], place: str, action: str, **body: Any
) -> station.Reply:
    snapshot = station.Snapshot.model_validate(
        hub.get(f"{STATION}/places/{place}", headers=headers).json()
    )
    sent = {
        "message_id": f"{action}-{place}-{len(body)}",
        "client_id": client,
        "place": place,
        "context": body.pop("context", snapshot.context.model_dump(mode="json")),
        "action": action,
        **(
            {"expected_revision": body.pop("expected_revision")}
            if "expected_revision" in body
            else {}
        ),
        "payload": body,
    }
    answered = hub.post(STATION + "/commands", json=sent, headers=headers)
    assert answered.status_code == 200, answered.text
    return station.Reply.model_validate(answered.json())


def test_the_phone_is_told_and_answers_ge_klart_from_the_notice(hub: TestClient) -> None:
    pusher: Pusher = hub.app.state.pusher  # type: ignore[attr-defined]
    recorder = Recorder()
    pusher.sender = recorder
    norrby, at_norrby = approved(hub, "TKL Norrby", "nby")
    phone, at_asen = approved(hub, "Telefonen Åsen", "asn")
    token = {"token": PHONE, "sandbox": True}
    assert hub.put(STATION + "/push", json=token, headers=at_asen).status_code == 204
    assert hub.put(STATION + "/push", json=token).status_code == 401
    assert hub.put(STATION + "/push", json={"token": "nej"}, headers=at_asen).status_code == 422
    pusher.round()  # the run is seen: from now on
    request = {"call": "t101-nby", "section": "s-nby-asn", "clearance_id": "c-101"}
    command(hub, norrby, at_norrby, "nby", "clearance.request", **request)
    assert pusher.round() == 1
    [push] = recorder.sent
    notice = push.notice
    assert (push.token.token, push.token.sandbox) == (PHONE, True)
    assert (notice.kind, notice.place, notice.train_number) == (
        station.EventKind.CLEARANCE_REQUESTED,
        "asn",
        "101",
    )
    assert notice.title.startswith("Tåg 101 från ") and "Ge klart" in notice.body
    assert payload(notice)["aps"]["category"] == "CLEARANCE_REQUEST"
    # Ge klart, straight from the notice: its context and revision, the phone's key.
    answer = command(
        hub,
        phone,
        at_asen,
        "asn",
        "clearance.response",
        clearance_id=notice.clearance_id,
        approved=True,
        context=notice.context.model_dump(mode="json"),
        expected_revision=notice.expected_revision.model_dump(mode="json")
        if notice.expected_revision
        else None,
    )
    assert answer.status == station.ReplyStatus.ACCEPTED, answer.message
    # Norrby has no push: the answer is told to nobody. With an address it is.
    assert pusher.round() == 0
    assert hub.put(STATION + "/push", json={"token": TKL}, headers=at_norrby).status_code == 204
    command(hub, norrby, at_norrby, "nby", "train.departed", call="t101-nby")
    assert pusher.round() == 1
    on_its_way = recorder.sent[-1].notice
    assert (on_its_way.kind, on_its_way.place, recorder.sent[-1].token.token) == (
        station.EventKind.TRAIN_APPROACHING,
        "asn",
        PHONE,
    )
    assert "category" not in payload(on_its_way)["aps"]
    # The phone stops push: nothing more to it.
    assert hub.delete(STATION + "/push", headers=at_asen).status_code == 204
    assert (
        hub.app.state.running.store.push_targets(  # type: ignore[attr-defined]
            hub.app.state.running.store.current()  # type: ignore[attr-defined]
        )[0][0].token
        == TKL
    )


def test_without_a_key_the_notices_go_to_the_pretend_service(hub: TestClient) -> None:
    pusher: Pusher = hub.app.state.pusher  # type: ignore[attr-defined]
    senders = pusher.sender
    assert isinstance(senders, Senders) and senders.name == "fake"
    norrby, at_norrby = approved(hub, "TKL Norrby", "nby")
    _, at_asen = approved(hub, "Telefonen Åsen", "asn")
    hub.put(STATION + "/push", json={"token": PHONE}, headers=at_asen)
    pusher.round()
    request = {"call": "t101-nby", "section": "s-nby-asn", "clearance_id": "c-101"}
    command(hub, norrby, at_norrby, "nby", "clearance.request", **request)
    assert pusher.round() == 1
    shown = hub.get("/api/hub/push").json()
    assert shown["service"] == "fake"
    [seen] = shown["recent"]
    assert (seen["place"], seen["kind"], seen["device"]) == (
        "asn",
        "clearance.requested",
        "…" + PHONE[-6:],
    )
    assert PHONE not in json.dumps(shown)
    assert TestClient(hub.app).get("/api/hub/push").status_code == 401


def test_a_pi_sends_its_notices_to_the_cloud(
    cloud: TestClient,  # noqa: F811
    tmp_path: Path,
) -> None:
    pi = started(pi_for(cloud, tmp_path), cloud)
    senders: Senders = pi.app.state.pusher.sender  # type: ignore[attr-defined]
    assert senders.name == "cloud"
    context = station.MeetContext(meet_id="varnamo-moduldagar", version=1, game_day=1, epoch=0)
    notice = station.Notice(
        kind=station.EventKind.TRAIN_APPROACHING,
        place="p2",
        title="Tåg 1 på väg",
        body="Från Skovborg.",
        train_number="1",
        context=context,
        seq=3,
    )
    senders.send([sync.Push(token=station.PushToken(token=PHONE), notice=notice)])
    [seen] = cloud.get("/api/hub/push").json()["recent"]
    assert (seen["title"], seen["device"]) == ("Tåg 1 på väg", "…" + PHONE[-6:])
    # Only a Pi the cloud knows sends through it.
    batch = sync.PushBatch(pushes=[]).model_dump(mode="json")
    stranger = cloud.post(
        "/api/sync/1/meets/varnamo-moduldagar/push",
        json=batch,
        headers={"Authorization": "Bearer " + "z" * 43},
    )
    assert stranger.status_code == 401
    assert follower(pi).links.reaches()


def test_apns_gets_a_signed_token_and_the_notice(caplog: pytest.LogCaptureFixture) -> None:
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    env = {
        "TRAINMEET_APNS_KEY_ID": "ABC123DEFG",
        "TRAINMEET_APNS_TEAM_ID": "TEAM123456",
        "TRAINMEET_APNS_TOPIC": "app.trainmeet.tmbox",
        "TRAINMEET_APNS_KEY": pem.replace("\n", "\\n"),
    }
    settings = ApnsSettings.from_env(env)
    assert settings is not None and "PRIVATE" not in repr(settings)
    assert ApnsSettings.from_env({**env, "TRAINMEET_APNS_KEY": ""}) is None
    posted: list[tuple[str, dict[str, str], bytes]] = []

    def post(url: str, headers: Any, body: bytes) -> tuple[int, bytes]:
        posted.append((url, dict(headers), body))
        return (200, b"") if len(posted) == 1 else (410, b'{"reason":"Unregistered"}')

    apns = ApnsPush(settings, post)
    context = station.MeetContext(meet_id="m", version=1, game_day=1, epoch=0)
    notice = station.Notice(
        kind=station.EventKind.CLEARANCE_REQUESTED,
        place="asn",
        title="Tåg 101 från Norrby",
        body="Begär klart hit. Ge klart eller neka.",
        train_number="101",
        clearance_id="c-101",
        context=context,
        expected_revision=station.Revision(scope=station.RevisionScope.CASE, key="c-101", value=1),
        seq=5,
    )
    caplog.set_level(logging.INFO)
    pushes = [
        sync.Push(token=station.PushToken(token=PHONE, sandbox=True), notice=notice),
        sync.Push(token=station.PushToken(token=TKL), notice=notice),
    ]
    apns.send(pushes)
    (url, headers, body), (second, _, _) = posted
    assert url == f"https://api.sandbox.push.apple.com/3/device/{PHONE}"
    assert second == f"https://api.push.apple.com/3/device/{TKL}"
    assert (headers["apns-topic"], headers["apns-push-type"]) == ("app.trainmeet.tmbox", "alert")
    signed = headers["authorization"].removeprefix("bearer ")
    assert jwt.get_unverified_header(signed)["kid"] == "ABC123DEFG"
    claims = jwt.decode(signed, private.public_key(), algorithms=["ES256"])
    assert claims["iss"] == "TEAM123456"
    sent = json.loads(body)
    assert sent["aps"]["category"] == "CLEARANCE_REQUEST"
    assert sent["trainmeet"]["clearance_id"] == "c-101"
    # Apple said no to the second: said in the log, without the phone's address or the key.
    assert "Unregistered" in caplog.text
    assert TKL not in caplog.text and PHONE not in caplog.text and "PRIVATE" not in caplog.text


def test_the_pretend_service_keeps_only_the_last() -> None:
    fake = FakePush(kept=2)
    context = station.MeetContext(meet_id="m", version=1, game_day=1, epoch=0)
    for n in range(3):
        notice = station.Notice(
            kind=station.EventKind.TRAIN_APPROACHING,
            place="asn",
            title=f"Tåg {n} på väg",
            body="Från Norrby.",
            train_number=str(n),
            context=context,
            seq=n + 1,
        )
        fake.send([sync.Push(token=station.PushToken(token=PHONE), notice=notice)])
    assert [seen["title"] for seen in fake.recent()] == ["Tåg 2 på väg", "Tåg 1 på väg"]
