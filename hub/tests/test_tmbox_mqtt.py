"""The physical TMBoxes over MQTT (BOX-07, BOX-10, DRIFT-22, H73), ported from the old Server's
tests (test_mqtt_transport, test_terminal_liveness, test_terminal16_runtime, test_local_server):
presence is answered at the edge, stale work is skipped, and each box has a queue of its own,
so one box's hiccup never holds the others."""

from __future__ import annotations

import json
import logging
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import paho.mqtt.client as mqtt
import pytest
from fastapi.testclient import TestClient
from paho.mqtt.enums import CallbackAPIVersion

from contracts.terminal import MAX_PAYLOAD_BYTES, SESSION_IDLE_SECONDS, Ack, DisplaySize, Frame
from hub import tmbox_mqtt
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.tmbox_mqtt import BOX_QUEUE, BoxError, Bridge, Gateway, MeetBoxes, topic

PIN = "482915"
PI = Path(__file__).resolve().parents[2] / "deploy" / "pi"


def until(check: Callable[[], object], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "it never happened"
        time.sleep(0.01)


class FakeTerminals:
    """Drift as a box sees it, with a gate that can hold one box's work."""

    def __init__(self) -> None:
        self.known: set[str] = set()
        self.revision = 0
        self.presses: list[tuple[str, str]] = []
        self.hellos: list[str] = []
        self.gates: dict[str, threading.Event] = {}
        self.refuse = False

    def _frame(self, device: str) -> dict[str, Any]:
        return {"device_id": device, "revision": self.revision}

    def hello(self, device: str, name: str, display: DisplaySize | None) -> dict[str, Any]:
        if self.refuse:
            raise BoxError("full")
        self.hellos.append(device)
        self.known.add(device)
        return self._frame(device)

    def frames(self, devices: list[str], heard: set[str]) -> dict[str, dict[str, Any]]:
        return {device: self._frame(device) for device in devices if device in self.known}

    def press(self, device: str, body: dict[str, Any]) -> dict[str, Any]:
        gate = self.gates.get(device)
        if gate is not None:
            assert gate.wait(5)
        self.presses.append((device, body["command_id"]))
        self.revision += 1
        return {
            "status": "accepted",
            "message": "",
            "command_id": body["command_id"],
            "frame": self._frame(device),
        }


class Wire:
    """What the hub published, in order."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self._lock = threading.Lock()

    def publish(self, topic_name: str, body: dict[str, Any]) -> None:
        with self._lock:
            self.sent.append((topic_name, body))

    def to(self, device: str, leaf: str) -> list[dict[str, Any]]:
        with self._lock:
            return [body for name, body in self.sent if name == topic(device, leaf)]


def say(gateway: Gateway, device: str, leaf: str, **body: Any) -> None:
    gateway.on_message(topic(device, leaf), json.dumps(body).encode())


def hello(gateway: Gateway, device: str, boot: str = "b1", **extra: Any) -> None:
    say(gateway, device, "hello", device_code=device, model="TMBox", boot=boot, **extra)


def command(gateway: Gateway, device: str, n: int, boot: str = "b1") -> None:
    say(gateway, device, "command", command_id=f"{boot}-{n}", view_token="v", key="1", boot=boot)


@pytest.fixture
def wire() -> Wire:
    return Wire()


@pytest.fixture
def terminals() -> FakeTerminals:
    return FakeTerminals()


@pytest.fixture
def gateway(terminals: FakeTerminals, wire: Wire) -> Iterator[Gateway]:
    made = Gateway(terminals, wire.publish)
    yield made
    for gate in terminals.gates.values():
        gate.set()
    made.close()


def test_a_box_says_hello_gets_its_frame_and_its_presses_are_answered(
    gateway: Gateway, wire: Wire, terminals: FakeTerminals
) -> None:
    hello(gateway, "box-a1")
    until(lambda: wire.to("box-a1", "frame"))
    assert wire.to("box-a1", "frame")[0] == {"boot": "b1", "frame": terminals._frame("box-a1")}
    say(gateway, "box-a1", "presence", nonce="b1-p1", boot="b1")
    assert wire.to("box-a1", "alive") == [{"boot": "b1", "nonce": "b1-p1"}]
    command(gateway, "box-a1", 1)
    until(lambda: wire.to("box-a1", "ack"))
    ack = wire.to("box-a1", "ack")[0]
    assert (ack["status"], ack["boot"], ack["command_id"]) == ("accepted", "b1", "b1-1")
    assert terminals.presses == [("box-a1", "b1-1")]


def test_the_edge_drops_what_is_not_a_box_message(gateway: Gateway, wire: Wire) -> None:
    hello(gateway, "box-a1")
    until(lambda: wire.to("box-a1", "frame"))
    before = list(wire.sent)
    presence = {"nonce": "n", "boot": "b1"}

    def ignored(topic_name: str, payload: bytes, retained: bool = False) -> None:
        assert gateway.receive(topic_name, payload, retained=retained) is None, topic_name

    ignored(topic("box-a1", "presence"), json.dumps(presence).encode(), retained=True)
    ignored(topic("x", "presence"), json.dumps(presence).encode())
    ignored(topic("box a1", "presence"), json.dumps(presence).encode())
    ignored(topic("box-a1", "status"), json.dumps(presence).encode())
    ignored(topic("box-a1", "presence/extra"), json.dumps(presence).encode())
    ignored("tmbox/v2/box-a1/presence", json.dumps(presence).encode())
    ignored(topic("box-a1", "presence"), b"not json")
    ignored(topic("box-a1", "presence"), b"[1, 2]")
    ignored(topic("box-a1", "presence"), json.dumps({"nonce": "n"}).encode())
    ignored(topic("box-a1", "presence"), json.dumps({"boot": "b" * 65}).encode())
    # The size limit is the old Server's: 4096 bytes passes, 4097 does not.
    padded = {"nonce": "", "boot": "b1"}
    room = MAX_PAYLOAD_BYTES - len(json.dumps(padded).encode())
    padded["nonce"] = "n" * room
    assert len(json.dumps(padded).encode()) == MAX_PAYLOAD_BYTES
    assert gateway.receive(topic("box-a1", "presence"), json.dumps(padded).encode()) is not None
    padded["nonce"] += "n"
    ignored(topic("box-a1", "presence"), json.dumps(padded).encode())
    assert [name for name, _ in wire.sent[len(before) :]] == [topic("box-a1", "alive")]


def test_presence_is_answered_while_the_box_is_busy(
    gateway: Gateway, wire: Wire, terminals: FakeTerminals
) -> None:
    hello(gateway, "box-a1")
    until(lambda: wire.to("box-a1", "frame"))
    terminals.gates["box-a1"] = threading.Event()
    command(gateway, "box-a1", 1)
    started = time.monotonic()
    say(gateway, "box-a1", "presence", nonce="p", boot="b1")
    assert wire.to("box-a1", "alive") == [{"boot": "b1", "nonce": "p"}]
    assert time.monotonic() - started < 0.5
    assert wire.to("box-a1", "ack") == []
    terminals.gates["box-a1"].set()
    until(lambda: wire.to("box-a1", "ack"))


def test_a_hiccup_in_one_box_does_not_hold_the_others(
    gateway: Gateway, wire: Wire, terminals: FakeTerminals
) -> None:
    """H73, BOX-17: each box has a queue of its own. The old Server had one for all boxes."""
    for device in ("box-a1", "box-b2"):
        hello(gateway, device)
    until(lambda: wire.to("box-a1", "frame") and wire.to("box-b2", "frame"))
    terminals.gates["box-a1"] = threading.Event()
    command(gateway, "box-a1", 1)
    for n in range(1, 4):
        command(gateway, "box-b2", n)
    until(lambda: len(wire.to("box-b2", "ack")) == 3)
    assert wire.to("box-a1", "ack") == [], "box A is still stuck"
    terminals.gates["box-a1"].set()
    until(lambda: wire.to("box-a1", "ack"))


def test_key_presses_keep_their_order(gateway: Gateway, terminals: FakeTerminals) -> None:
    hello(gateway, "box-a1")
    for n in range(1, 26):
        command(gateway, "box-a1", n)
    until(lambda: len(terminals.presses) == 25)
    assert [cid for _, cid in terminals.presses] == [f"b1-{n}" for n in range(1, 26)]


def test_an_unknown_or_replaced_session_gets_no_answer(
    gateway: Gateway, wire: Wire, terminals: FakeTerminals, caplog: pytest.LogCaptureFixture
) -> None:
    say(gateway, "box-a1", "presence", nonce="p", boot="b1")
    assert wire.to("box-a1", "alive") == [], "after a restart the box must say hello again"
    hello(gateway, "box-a1", boot="b1")
    until(lambda: wire.to("box-a1", "frame"))
    late = gateway.receive(
        topic("box-a1", "command"),
        json.dumps({"command_id": "b1-9", "view_token": "v", "key": "1", "boot": "b1"}).encode(),
    )
    assert late is not None
    hello(gateway, "box-a1", boot="b2")
    say(gateway, "box-a1", "presence", nonce="old", boot="b1")
    assert wire.to("box-a1", "alive") == []
    # A press from the replaced session is never carried out afterwards.
    with caplog.at_level(logging.WARNING, logger="trainmeet.tmbox"):
        assert gateway.handle(late) is False
    assert "b1-9" in caplog.text
    assert terminals.presses == []


def test_only_the_latest_presence_is_worked(gateway: Gateway, wire: Wire) -> None:
    hello(gateway, "box-a1")
    until(lambda: wire.to("box-a1", "frame"))
    works = []
    for n in range(3):
        payload = json.dumps({"nonce": f"p{n}", "boot": "b1"}).encode()
        work = gateway.receive(topic("box-a1", "presence"), payload)
        assert work is not None
        works.append(work)
    assert len(wire.to("box-a1", "alive")) == 3, "every presence is answered at the edge"
    assert [gateway.handle(work) for work in works] == [False, False, True]


def test_a_full_queue_is_said_out_loud_not_silently_blocking(
    gateway: Gateway, terminals: FakeTerminals, caplog: pytest.LogCaptureFixture
) -> None:
    hello(gateway, "box-a1")
    terminals.gates["box-a1"] = threading.Event()
    command(gateway, "box-a1", 0)
    until(lambda: gateway.pending("box-a1") == 0)
    with caplog.at_level(logging.ERROR, logger="trainmeet.tmbox"):
        started = time.monotonic()
        for n in range(1, BOX_QUEUE + 2):
            command(gateway, "box-a1", n)
        assert time.monotonic() - started < 0.5
    assert gateway.pending("box-a1") == BOX_QUEUE
    assert "kön är full" in caplog.text


def test_frames_go_out_when_they_change_and_a_press_tells_the_other_boxes(
    gateway: Gateway, wire: Wire
) -> None:
    for device in ("box-a1", "box-b2"):
        hello(gateway, device)
    until(lambda: wire.to("box-a1", "frame") and wire.to("box-b2", "frame"))
    gateway.tick()
    assert len(wire.to("box-a1", "frame")) == 1, "nothing changed: no frame"
    command(gateway, "box-a1", 1)
    until(lambda: wire.to("box-a1", "ack"))
    assert gateway.woken.is_set(), "the other boxes are told at once"
    gateway.tick()
    assert len(wire.to("box-b2", "frame")) == 2
    assert wire.to("box-b2", "frame")[-1]["frame"]["revision"] == 1
    assert len(wire.to("box-a1", "frame")) == 1, "box A has the new frame in its ack"


def test_a_box_not_in_the_meet_any_more_joins_the_one_that_runs(
    gateway: Gateway, wire: Wire, terminals: FakeTerminals
) -> None:
    hello(gateway, "box-a1")
    until(lambda: wire.to("box-a1", "frame"))
    terminals.known.clear()  # Byt träff: the box is not in the new meet
    gateway.tick()
    assert terminals.hellos == ["box-a1", "box-a1"]
    assert len(wire.to("box-a1", "frame")) == 2


def test_a_box_the_meet_cannot_take_is_let_go(
    gateway: Gateway, wire: Wire, terminals: FakeTerminals
) -> None:
    terminals.refuse = True
    hello(gateway, "box-a1")
    until(lambda: gateway.pending("box-a1") == 0 and terminals.refuse)
    time.sleep(0.05)
    assert wire.to("box-a1", "frame") == []
    say(gateway, "box-a1", "presence", nonce="p", boot="b1")
    assert wire.to("box-a1", "alive") == [], "silence makes the box say hello again"


def test_a_quiet_box_stops_getting_frames_until_it_is_heard_again(
    terminals: FakeTerminals, wire: Wire
) -> None:
    clock = [1000.0]
    gateway = Gateway(terminals, wire.publish, now=lambda: clock[0])
    try:
        hello(gateway, "box-a1")
        until(lambda: wire.to("box-a1", "frame"))
        clock[0] += SESSION_IDLE_SECONDS + 1
        terminals.revision += 1
        gateway.tick()
        assert len(wire.to("box-a1", "frame")) == 1, "a box gone quiet gets nothing"
        say(gateway, "box-a1", "presence", nonce="p", boot="b1")
        until(lambda: gateway.pending("box-a1") == 0)
        time.sleep(0.05)
        gateway.tick()
        assert len(wire.to("box-a1", "frame")) == 2, "heard again: a picture at the next tick"
    finally:
        gateway.close()


# --- With the hub's own meet -------------------------------------------------------------------


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))
    assert client.post("/api/hub/setup", json={"name": "Pi:n", "pin": PIN}).status_code == 201
    assert client.post("/api/drift/1/start", json={"version": 1}).status_code == 201
    return client


def test_a_physical_box_waits_gets_its_place_and_asks_for_a_train(
    hub: TestClient, wire: Wire
) -> None:
    """BOX-04, BOX-10, BOX-12: no code and no key; under Väntar until the dispatcher gives it
    a place; then the same screens as TMBox web, from Drift."""
    gateway = Gateway(MeetBoxes(hub.app.state.running), wire.publish)  # type: ignore[attr-defined]
    try:
        hello(gateway, "tmbox-norrby", display={"rows": 4, "cols": 20})
        hello(gateway, "tmbox-asen")
        until(lambda: wire.to("tmbox-norrby", "frame") and wire.to("tmbox-asen", "frame"))
        first = wire.to("tmbox-norrby", "frame")[0]["frame"]
        assert (first["rows"], first["cols"]) == (4, 20)
        listed = {c["name"]: c for c in hub.get("/api/drift/1/clients").json()}
        assert listed["tmbox-norrby"]["kind"] == "tmbox"
        assert listed["tmbox-norrby"]["status"] == "waiting"
        for name, place in (("tmbox-norrby", "nby"), ("tmbox-asen", "asn")):
            response = hub.post(
                "/api/drift/1/clients/assign",
                json={"client_id": listed[name]["client_id"], "places": [place], "side": "both"},
            )
            assert response.status_code == 200, response.text
        gateway.tick()
        frame = wire.to("tmbox-norrby", "frame")[-1]["frame"]
        Frame.model_validate(frame)
        assert frame["lines"][0].strip() == "Norrby"
        # 101# at Norrby asks for clearance; Åsen's box is told without asking.
        say(
            gateway,
            "tmbox-norrby",
            "command",
            command_id="b1-1",
            view_token=frame["view_token"],
            key="#",
            train_number="101",
            entry_context=frame["entry"]["context"],
            boot="b1",
        )
        until(lambda: wire.to("tmbox-norrby", "ack"))
        ack = wire.to("tmbox-norrby", "ack")[0]
        Ack.model_validate(ack)
        assert ack["status"] == "accepted", ack
        gateway.tick()
        assert wire.to("tmbox-asen", "frame")[-1]["frame"]["lines"][0] == "Nby?101      1/1"
        # The same command again is a duplicate, not a second request.
        say(
            gateway,
            "tmbox-norrby",
            "command",
            command_id="b1-1",
            view_token=frame["view_token"],
            key="#",
            train_number="101",
            entry_context=frame["entry"]["context"],
            boot="b1",
        )
        until(lambda: len(wire.to("tmbox-norrby", "ack")) == 2)
        assert wire.to("tmbox-norrby", "ack")[1]["status"] == "duplicate"
        # A reconnect keeps the place.
        hello(gateway, "tmbox-norrby", boot="b2")
        until(lambda: any(m["boot"] == "b2" for m in wire.to("tmbox-norrby", "frame")))
        again = next(m for m in wire.to("tmbox-norrby", "frame") if m["boot"] == "b2")["frame"]
        assert (again["station"], again["station_code"]) == (
            frame["station"],
            frame["station_code"],
        )
        listed = {c["name"]: c for c in hub.get("/api/drift/1/clients").json()}
        assert listed["tmbox-norrby"]["places"] == ["nby"]
        assert len(listed) == 2
    finally:
        gateway.close()


# --- Over a real Mosquitto, as on the Pi --------------------------------------------------------


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def broker(tmp_path: Path) -> Iterator[int]:
    """A Mosquitto of its own, as the old Server's tests started it: a port and no config file
    (without one Mosquitto 2 listens on localhost only and lets anyone in). Ubuntu's AppArmor
    keeps Mosquitto from reading a config file in a test's own folder."""
    binary = shutil.which("mosquitto")
    if binary is None:
        pytest.skip("mosquitto saknas här; CI installerar den")
    port = free_port()
    said = tmp_path / "mosquitto.log"
    with said.open("wb") as log:
        process = subprocess.Popen([binary, "-p", str(port)], stdout=log, stderr=log)
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                if process.poll() is not None or time.monotonic() > deadline:
                    pytest.fail("mosquitto startade inte: " + said.read_text(errors="replace"))
                time.sleep(0.05)
        yield port
    finally:
        process.terminate()
        process.wait(timeout=5)


class FakeBox:
    """A box as the firmware is: MQTT 3.1.1, clean session, its device id as client id."""

    def __init__(self, port: int, device: str) -> None:
        self.device = device
        self.got: dict[str, list[dict[str, Any]]] = {"alive": [], "frame": [], "ack": []}
        self.client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=device,
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )
        self.client.on_message = self._message
        self.client.connect("127.0.0.1", port, keepalive=10)
        self.client.loop_start()
        for leaf in self.got:
            self.client.subscribe(topic(device, leaf), qos=1)
        time.sleep(0.2)

    def _message(self, _client: Any, _data: Any, message: mqtt.MQTTMessage) -> None:
        self.got[message.topic.rsplit("/", 1)[1]].append(json.loads(message.payload))

    def send(self, leaf: str, **body: Any) -> None:
        self.client.publish(topic(self.device, leaf), json.dumps(body), qos=1)

    def close(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()


def test_a_box_is_answered_over_a_real_broker(broker: int, terminals: FakeTerminals) -> None:
    bridge = Bridge(terminals, "127.0.0.1", broker, client_id=f"trainmeet-hub-{uuid4().hex[:6]}")
    bridge.start()
    box = FakeBox(broker, "box-a1")
    try:
        until(lambda: bridge.client.is_connected(), timeout=10)
        time.sleep(0.3)  # the hub's subscriptions
        box.send("hello", device_code="A1", model="TMBox", boot="b1")
        until(lambda: box.got["frame"], timeout=5)
        assert box.got["frame"][0]["boot"] == "b1"
        box.send("presence", nonce="b1-p1", boot="b1")
        until(lambda: box.got["alive"], timeout=5)
        assert box.got["alive"][0] == {"boot": "b1", "nonce": "b1-p1"}
        box.send("command", command_id="b1-1", view_token="v", key="1", boot="b1")
        until(lambda: box.got["ack"], timeout=5)
        assert box.got["ack"][0]["status"] == "accepted"
    finally:
        box.close()
        bridge.stop()


# --- On the Pi -----------------------------------------------------------------------------------


def test_the_boxes_find_the_hub_with_dns_sd() -> None:
    """BOX-08: what the firmware looks for, as the old Server announced it."""
    command_line = tmbox_mqtt.Announce("hub-abc123", 1883, 80).command()
    assert command_line[:4] == ["avahi-publish-service", "TrainMeet TMBox", "_tmbox._tcp", "1883"]
    assert {"protocol=2", "server_id=hub-abc123", "http=80"} <= set(command_line)


def test_no_physical_boxes_without_a_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRAINMEET_MQTT_HOST", raising=False)
    assert tmbox_mqtt.from_environment(None, lambda: "hub-x") is None  # type: ignore[arg-type]


def test_mosquitto_runs_on_the_pi_beside_the_hub() -> None:
    """DRIFT-22: Mosquitto on the Pi, anonymous on the meet's network as today (BOX-10)."""
    conf = (PI / "mosquitto.conf").read_text()
    assert "listener 1883 0.0.0.0" in conf and "allow_anonymous true" in conf
    script = (PI / "install.sh").read_text()
    assert "mosquitto" in script and "/etc/mosquitto/conf.d/trainmeet.conf" in script
    assert "avahi-utils" in script, "avahi-publish-service announces the hub to the boxes"
    settings = dict(
        line.split("=", 1)
        for line in (PI / "hub.env").read_text().splitlines()
        if line and not line.startswith("#")
    )
    assert settings["TRAINMEET_MQTT_HOST"] == "127.0.0.1"
    unit = (PI / "trainmeet-hub.service").read_text()
    assert "mosquitto.service" in unit
