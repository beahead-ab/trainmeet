"""The physical TMBoxes over MQTT (BOX-07, BOX-10, DRIFT-22, H73): Mosquitto on the Pi, and
here the hub's side of the terminal protocol, exactly as the old Server's terminal16 over MQTT
(contracts/terminal.py), so boxes with firmware 0.7 or later work without reflashing.

Ported from the old Server (src/tmbox_gateway: mqtt_transport, mqtt_session, terminal16_mqtt),
with its lesson: the box asks "is the server there?" every five seconds and gives up after
fifteen without an answer. When that question waited behind all other work, one stall made
every box drop at once, and the reconnects kept the collapse going. So:

- The edge answers presence at once, on the network thread, with no database and no lock
  that work holds. The answer means "the hub knows your session", not "the hub has caught up".
- Work that has gone stale is skipped: anything from a replaced session, and every presence
  but the latest. A key press from a session that is gone is never carried out afterwards.
- New in the next generation (H73, BOX-17): each box has a queue of its own, worked by a
  small pool. One box's hiccup holds its own queue, never the others. The old Server had one
  queue for every box.

Frames go out on hello, after a key press and whenever a box's frame changes, checked twice a
second for every box in one go. Physical boxes are accepted without a key, as today (BOX-10);
they find the hub with DNS-SD, `_tmbox._tcp` (BOX-08), and join whatever meet the hub runs,
under Väntar until the dispatcher gives them a place (BOX-04, BOX-12).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Protocol

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from contracts.terminal import (
    MAX_PAYLOAD_BYTES,
    MAX_SESSIONS,
    SESSION_IDLE_SECONDS,
    TOPIC_PREFIX,
    DisplaySize,
    known_size,
)
from drift.store import MissingRun, RunLimit, UnknownBox

if TYPE_CHECKING:
    from hub.running import Running

LOG = logging.getLogger("trainmeet.tmbox")

LEAVES: Final = ("hello", "presence", "command")
SUBSCRIPTIONS: Final = tuple(TOPIC_PREFIX + "+/" + leaf for leaf in LEAVES)
DEVICE: Final = re.compile(r"[A-Za-z0-9._:-]{3,64}")
# Work waiting for one box. A box sends a presence every five seconds and a key press now and
# then; more than this means its work is stuck, and the rest is dropped and said out loud.
BOX_QUEUE: Final = 64
WORKERS: Final = 8
TICK_SECONDS: Final = 0.5
# The broker drops a client after 1.5 × keepalive; a Pi under load needs the margin. A short
# drop keeps the session and its subscriptions (the old Server, mqtt_session).
KEEPALIVE_SECONDS: Final = 60
SESSION_EXPIRY_SECONDS: Final = 300
PORT: Final = 1883

Publish = Callable[[str, dict[str, Any]], None]


class BoxError(Exception):
    """The box cannot be answered now: no meet runs, the meet is full, or the box is not in
    it. The box is let go and says hello again."""


class Terminals(Protocol):
    """Drift as the boxes see it."""

    def hello(self, device: str, name: str, display: DisplaySize | None) -> dict[str, Any]: ...

    def frames(self, devices: list[str], heard: set[str]) -> dict[str, dict[str, Any]]: ...

    def press(self, device: str, body: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class Work:
    device: str
    leaf: str
    body: dict[str, Any]
    sequence: int


@dataclass
class _Edge:
    boot: str
    seen: float
    presence: int = 0


@dataclass
class _Connection:
    boot: str
    seen: float
    frame: dict[str, Any] | None = None


@dataclass
class _Queue:
    items: deque[Work] = field(default_factory=deque)
    running: bool = False


def topic(device: str, leaf: str) -> str:
    return f"{TOPIC_PREFIX}{device}/{leaf}"


class Gateway:
    """Two stages: receive on the network thread, work on the box's own queue."""

    def __init__(
        self,
        terminals: Terminals,
        publish: Publish,
        *,
        workers: int = WORKERS,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.terminals = terminals
        self.publish = publish
        self.now = now
        # Set when a box changed Drift, so every box is told at once instead of at the tick.
        self.woken = threading.Event()
        self._edges: dict[str, _Edge] = {}
        self._edge_lock = threading.Lock()
        self._sequence = 0
        self._connections: dict[str, _Connection] = {}
        self._hellos: dict[str, tuple[str, DisplaySize | None]] = {}
        self._heard: set[str] = set()
        self._lock = threading.Lock()
        self._queues: dict[str, _Queue] = {}
        self._queue_lock = threading.Lock()
        self._tick_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tmbox")

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def on_message(
        self, topic_name: str, payload: bytes | bytearray, *, retained: bool = False
    ) -> None:
        work = self.receive(topic_name, payload, retained=retained)
        if work is not None:
            self.submit(work)

    # --- The network thread: never waits for anything -------------------------------------

    def receive(
        self, topic_name: str, payload: bytes | bytearray, *, retained: bool = False
    ) -> Work | None:
        """Read the message, answer a presence, and hand on what work remains."""
        if retained or not topic_name.startswith(TOPIC_PREFIX) or len(payload) > MAX_PAYLOAD_BYTES:
            return None
        parts = topic_name[len(TOPIC_PREFIX) :].split("/")
        if len(parts) != 2 or not DEVICE.fullmatch(parts[0]) or parts[1] not in LEAVES:
            return None
        device, leaf = parts
        try:
            body = json.loads(payload)
        except (ValueError, UnicodeError):
            return None
        if not isinstance(body, dict):
            return None
        boot = body.get("boot")
        if not isinstance(boot, str) or not 1 <= len(boot) <= 64:
            return None
        now = self.now()
        replaced: str | None = None
        with self._edge_lock:
            edge = self._edges.get(device)
            if leaf == "hello":
                if edge is None and len(self._edges) >= MAX_SESSIONS:
                    self._expire_edges(now)
                    if len(self._edges) >= MAX_SESSIONS:
                        return None
                replaced = edge.boot if edge else None
                edge = self._edges[device] = _Edge(boot=boot, seen=now)
            elif edge is None or edge.boot != boot:
                # A session the hub does not know: after a restart, or one already replaced.
                # The silence is what makes the box connect again and say hello.
                return None
            edge.seen = now
            self._sequence += 1
            sequence = self._sequence
            if leaf == "presence":
                edge.presence = sequence
        if leaf == "hello":
            if replaced is None:
                LOG.info("TMBox %s ansluten (session %s)", device, boot)
            elif replaced != boot:
                LOG.info("TMBox %s kopplade upp igen (session %s)", device, boot)
        elif leaf == "presence":
            self.publish(topic(device, "alive"), {"boot": boot, "nonce": body.get("nonce")})
        return Work(device, leaf, body, sequence)

    def _expire_edges(self, now: float) -> None:
        for device in [d for d, e in self._edges.items() if now - e.seen > SESSION_IDLE_SECONDS]:
            del self._edges[device]

    def _forget(self, device: str, boot: str) -> None:
        """Stop answering a session that could not be served, so the box connects again
        instead of waiting for ever for a picture."""
        with self._edge_lock:
            edge = self._edges.get(device)
            if edge is not None and edge.boot == boot:
                del self._edges[device]
        with self._lock:
            self._connections.pop(device, None)

    # --- One queue per box (H73) -----------------------------------------------------------

    def submit(self, work: Work) -> None:
        with self._queue_lock:
            queue = self._queues.setdefault(work.device, _Queue())
            if len(queue.items) >= BOX_QUEUE:
                LOG.error(
                    "TMBox %s: kön är full, så %s kastades. Boxens arbete står still.",
                    work.device,
                    work.leaf,
                )
                return
            queue.items.append(work)
            if queue.running:
                return
            queue.running = True
        self._pool.submit(self._drain, work.device)

    def _drain(self, device: str) -> None:
        while True:
            with self._queue_lock:
                queue = self._queues[device]
                if not queue.items:
                    queue.running = False
                    return
                work = queue.items.popleft()
            try:
                self.handle(work)
            except Exception:
                LOG.exception("TMBox %s: %s gick inte att hantera", device, work.leaf)

    def pending(self, device: str) -> int:
        with self._queue_lock:
            queue = self._queues.get(device)
            return len(queue.items) if queue else 0

    # --- The work ----------------------------------------------------------------------------

    def handle(self, work: Work) -> bool:
        """Do the work if it is still wanted. False when it was skipped."""
        boot = work.body["boot"]
        with self._edge_lock:
            edge = self._edges.get(work.device)
            current = edge is not None and edge.boot == boot
            if current and edge is not None and work.leaf == "presence":
                # A newer presence from the same box is already further back in its queue.
                current = edge.presence == work.sequence
        if not current:
            if work.leaf == "command":
                # The box has already given up on the answer and shows that nothing happened.
                # Carrying it out now would do something the operator does not know of.
                LOG.warning(
                    "TMBox %s: kommandot %s kom från en avslutad session och utfördes inte",
                    work.device,
                    work.body.get("command_id"),
                )
            return False
        if work.leaf == "hello":
            self._hello(work.device, boot, work.body)
        elif work.leaf == "presence":
            self._seen(work.device, boot)
        else:
            self._command(work.device, boot, work.body)
        return True

    def _hello(self, device: str, boot: str, body: dict[str, Any]) -> None:
        name = str(body.get("device_code") or device).strip()[:64] or device
        display = known_size(body.get("display"))
        LOG.info(
            "TMBox %s: %s, firmware %s",
            device,
            str(body.get("model") or "TMBox")[:80],
            str(body.get("firmware_version") or "?")[:32],
        )
        try:
            frame = self.terminals.hello(device, name, display)
        except BoxError as error:
            # Before a meet runs, the box tries again every fifteen seconds and joins then.
            LOG.info("TMBox %s kunde inte tas emot: %s", device, error)
            self._forget(device, boot)
            return
        with self._lock:
            self._hellos[device] = (name, display)
            self._connections[device] = _Connection(boot=boot, seen=self.now(), frame=frame)
            self._heard.add(device)
        self.publish(topic(device, "frame"), {"boot": boot, "frame": frame})

    def _seen(self, device: str, boot: str) -> _Connection:
        """The box is in contact. A connection that ran out while its queue was behind is
        made again, so the box gets a picture at the next tick instead of only answers."""
        with self._lock:
            connection = self._connections.get(device)
            if connection is None or connection.boot != boot:
                connection = self._connections[device] = _Connection(boot=boot, seen=self.now())
            connection.seen = self.now()
            self._heard.add(device)
            return connection

    def _command(self, device: str, boot: str, body: dict[str, Any]) -> None:
        self._seen(device, boot)
        press = {key: value for key, value in body.items() if key != "boot"}
        try:
            answer = self.terminals.press(device, press)
        except BoxError as error:
            LOG.warning("TMBox %s: kommandot kunde inte tas emot: %s", device, error)
            self._forget(device, boot)
            return
        with self._lock:
            connection = self._connections.get(device)
            if connection is not None and connection.boot == boot:
                connection.frame = answer.get("frame")
        self.publish(
            topic(device, "ack"), {**answer, "boot": boot, "command_id": body.get("command_id")}
        )
        # Drift changed: the other boxes are told now, not at the next tick.
        self.woken.set()

    # --- The tick: every box's frame, in one go ----------------------------------------------

    def tick(self) -> None:
        if not self._tick_lock.acquire(blocking=False):
            return
        try:
            now = self.now()
            with self._lock:
                gone = [
                    device
                    for device, connection in self._connections.items()
                    if now - connection.seen > SESSION_IDLE_SECONDS
                ]
                for device in gone:
                    del self._connections[device]
                devices = list(self._connections)
                heard, self._heard = self._heard, set()
            if devices:
                self._push(devices, heard)
        finally:
            self._tick_lock.release()

    def _push(self, devices: list[str], heard: set[str]) -> None:
        try:
            frames = self.terminals.frames(devices, heard)
        except BoxError:
            return
        missing: list[str] = []
        for device in devices:
            frame = frames.get(device)
            with self._lock:
                connection = self._connections.get(device)
                if connection is None:
                    continue
                if frame is None:
                    missing.append(device)
                    continue
                if frame == connection.frame:
                    continue
                connection.frame = frame
                boot = connection.boot
            self.publish(topic(device, "frame"), {"boot": boot, "frame": frame})
        for device in missing:
            self._rejoin(device)

    def _rejoin(self, device: str) -> None:
        """A box that is not in the meet any more, after Byt träff (B14): it joins the meet
        that runs now, under Väntar, as at its hello."""
        with self._lock:
            known = self._hellos.get(device)
            connection = self._connections.get(device)
        if connection is None:
            return
        if known is None:
            self._forget(device, connection.boot)
            return
        try:
            frame = self.terminals.hello(device, *known)
        except BoxError:
            self._forget(device, connection.boot)
            return
        with self._lock:
            connection.frame = frame
        self.publish(topic(device, "frame"), {"boot": connection.boot, "frame": frame})


class MeetBoxes:
    """The hub's meet, as the boxes see it: whichever meet runs now."""

    def __init__(self, running: Running) -> None:
        self.running = running

    def _run(self) -> tuple[Any, str]:
        store = self.running.store
        try:
            return store, store.current()
        except MissingRun as error:
            raise BoxError("Ingen träff körs.") from error

    def hello(self, device: str, name: str, display: DisplaySize | None) -> dict[str, Any]:
        store, run_id = self._run()
        try:
            return dict(store.device_hello(run_id, device, name, display))
        except (MissingRun, RunLimit) as error:
            raise BoxError("Träffen tar inte emot fler boxar.") from error

    def frames(self, devices: list[str], heard: set[str]) -> dict[str, dict[str, Any]]:
        store, run_id = self._run()
        try:
            return dict(store.device_frames(run_id, devices, heard))
        except MissingRun as error:
            raise BoxError("Ingen träff körs.") from error

    def press(self, device: str, body: dict[str, Any]) -> dict[str, Any]:
        store, run_id = self._run()
        try:
            return dict(store.device_press(run_id, device, body))
        except (MissingRun, RunLimit, UnknownBox) as error:
            raise BoxError("Boxen är inte med i träffen.") from error


class Bridge:
    """The hub's client of Mosquitto, and the ticker."""

    def __init__(self, terminals: Terminals, host: str, port: int, client_id: str) -> None:
        self.host, self.port = host, port
        self.client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv5,
            reconnect_on_failure=True,
        )
        self.client.reconnect_delay_set(min_delay=1, max_delay=8)
        self.client.on_connect = self._connected
        self.client.on_message = self._message
        self.gateway = Gateway(terminals, self.publish)
        self._stop = threading.Event()
        self._ticker: threading.Thread | None = None

    def publish(self, topic_name: str, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        self.client.publish(topic_name, payload, qos=1, retain=False)

    def _connected(
        self, client: mqtt.Client, _data: Any, _flags: Any, reason: Any, _props: Any
    ) -> None:
        if reason.is_failure:
            LOG.warning("MQTT: mäklaren svarade %s", reason)
            return
        client.subscribe([(name, 1) for name in SUBSCRIPTIONS])
        LOG.info("MQTT: ansluten till mäklaren")

    def _message(self, _client: mqtt.Client, _data: Any, message: mqtt.MQTTMessage) -> None:
        self.gateway.on_message(message.topic, message.payload, retained=bool(message.retain))

    def _tick(self) -> None:
        while not self._stop.is_set():
            self.gateway.woken.wait(TICK_SECONDS)
            self.gateway.woken.clear()
            if self._stop.is_set():
                return
            try:
                self.gateway.tick()
            except Exception:
                LOG.exception("TMBoxarnas bilder gick inte att räkna fram")

    def start(self) -> None:
        properties = Properties(PacketTypes.CONNECT)  # type: ignore[no-untyped-call]
        properties.SessionExpiryInterval = SESSION_EXPIRY_SECONDS
        # Asynchronously: the hub starts even before Mosquitto does, and reconnects by itself.
        self.client.connect_async(
            self.host,
            self.port,
            keepalive=KEEPALIVE_SECONDS,
            clean_start=False,
            properties=properties,
        )
        self.client.loop_start()
        self._ticker = threading.Thread(target=self._tick, name="tmbox-bilder", daemon=True)
        self._ticker.start()

    def stop(self) -> None:
        self._stop.set()
        self.gateway.woken.set()
        if self._ticker is not None:
            self._ticker.join(timeout=5)
        self.client.disconnect()
        self.client.loop_stop()
        self.gateway.close()


class Announce:
    """DNS-SD, so the boxes find the hub (BOX-08): `_tmbox._tcp` on the broker's port, with
    the TXT records the firmware looks for. Through avahi on the Pi, as the old Server did."""

    def __init__(self, server_id: str, port: int = PORT, http_port: int = 80) -> None:
        self.server_id, self.port, self.http_port = server_id, port, http_port
        self._process: subprocess.Popen[bytes] | None = None

    def command(self) -> list[str]:
        return [
            "avahi-publish-service",
            "TrainMeet TMBox",
            "_tmbox._tcp",
            str(self.port),
            "protocol=2",
            f"server_id={self.server_id}",
            f"http={self.http_port}",
        ]

    def start(self) -> None:
        if shutil.which("avahi-publish-service") is None:
            LOG.warning("avahi-publish-service saknas: boxarna hittar inte hubben av sig själva")
            return
        self._process = subprocess.Popen(
            self.command(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(0.05)
        if self._process.poll() is not None:
            LOG.warning("DNS-SD för boxarna gick inte att starta (avahi-daemon?)")
            self._process = None

    def stop(self) -> None:
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None


class Boxes:
    """The bridge and the announcement together, started and stopped with the hub."""

    def __init__(self, bridge: Bridge, announce: Announce | None) -> None:
        self.bridge, self.announce = bridge, announce

    def start(self) -> None:
        self.bridge.start()
        if self.announce is not None:
            self.announce.start()

    def stop(self) -> None:
        if self.announce is not None:
            self.announce.stop()
        self.bridge.stop()


def from_environment(running: Running, hub_id: Callable[[], str]) -> Boxes | None:
    """The physical boxes, when TRAINMEET_MQTT_HOST says where Mosquitto is: on the Pi it is
    127.0.0.1 (deploy/pi/hub.env). Without it, as in the cloud, there are no physical boxes."""
    host = os.environ.get("TRAINMEET_MQTT_HOST", "").strip()
    if not host:
        return None
    port = int(os.environ.get("TRAINMEET_MQTT_PORT", "").strip() or PORT)
    hub = hub_id()
    bridge = Bridge(MeetBoxes(running), host, port, client_id=f"trainmeet-{hub}")
    announce = None
    if os.environ.get("TRAINMEET_TMBOX_ANNOUNCE", "1").strip() != "0":
        http = int(os.environ.get("TRAINMEET_HTTP_PORT", "").strip() or 80)
        announce = Announce(hub, port, http)
    return Boxes(bridge, announce)
