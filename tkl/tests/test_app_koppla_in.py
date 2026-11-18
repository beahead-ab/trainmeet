"""Studio's Koppla in (#85) under /api/tkl/1/studio/koppla-in, against the pretend LocoNet: the
port list, connecting, Discover with the cards' modules and channels, the four states, learning
by touching, level 3 turned on, the interlocking following the layout, section.occupancy to a
pretend hub, Lyssna, and TKL in the cloud that never opens a port (STUDIO-04, STUDIO-11,
STUDIO-17, STUDIO-18, STV-10, STV-11, STV-17, TKLMOLN-08). Nothing here names a station (RS13).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts import station
from contracts.station_model import StationModel, to_json
from contracts.tkl import (
    LoconetType,
    TklAnswer,
    TklKopplaIn,
    TklListen,
    TklMode,
)
from tkl.app import create_app
from tkl.loconet.service import Settings
from tkl.loconet.transports import Transport, TransportError
from tkl.store import LOCAL, Connection
from tkl.tests.niva3 import level_3
from tkl.tests.test_app import API, set_up, tkl
from tkl.tests.test_app_stallverk import PLACE, PretendHub, model, with_model

K = API + "/studio/koppla-in"
S = API + "/stallverk"
QUICK = Settings(background=False, discover_seconds=0.05, reply_seconds=0.05, movement=0.0)


def shown(response: httpx.Response) -> TklKopplaIn:
    assert response.status_code == 200, response.text
    return TklKopplaIn.model_validate(response.json())


def row(view: TklKopplaIn, kind: str, name: str) -> Any:
    return next(o for o in view.objects if o.kind.value == kind and o.name == name)


def pump(client: TestClient) -> None:
    service = client.app.state.loconet  # type: ignore[attr-defined]
    for _ in range(10):
        service.pump()


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    made = tkl(tmp_path, loconet_settings=QUICK)
    assert set_up(made).status_code == 201
    with_model(made)
    return made


def test_koppla_in_shows_the_objects_in_their_four_states_and_the_ports(
    client: TestClient,
) -> None:
    """STUDIO-17 and STUDIO-19: the switches are yellow at their numbers by default, the rest
    grey; level 3 waits for addresses. STUDIO-11: the port list, with the pretend LocoNet."""
    view = shown(client.get(K))
    assert view.loconet.available and not view.loconet.connected
    assert view.level == 2 and not view.level_3.on and not view.level_3.possible
    switch = row(view, "switch", "1")
    assert (switch.state.value, switch.address, switch.default) == ("yellow", 1, True)
    assert row(view, "signal", "In").state.value == "grey"
    assert row(view, "track_circuit", "Spår 1").state.value == "grey"
    ports = client.get(K + "/ports").json()
    assert ports[-1] == {
        "type": "pretend",
        "port": "latsas",
        "label": "Låtsas-LocoNet: LocoNet ej ansluten, som Prova använder",
    }
    client.post(API + "/lock")
    assert client.get(K).status_code == 401
    assert client.post(K + "/connect", json={"type": "pretend"}).status_code == 401


def test_the_pretend_loconet_is_connected_discovered_and_learnt_by_touching(
    client: TestClient,
) -> None:
    """STUDIO-04, STUDIO-11, STUDIO-18: connect, Discover shows the cards with module and
    channel; a wagon asks its question, and yes makes the track green in the model; Lägg om
    and yes make the switch green; Lyssna shows it all in Swedish."""
    view = shown(client.post(K + "/connect", json={"type": "pretend"}))
    assert view.loconet.connected and view.loconet.type == LoconetType.PRETEND
    assert view.loconet.label == "LocoNet ej ansluten · låtsas-LocoNet"
    view = shown(client.post(K + "/discover"))
    assert view.message == "Discover hittade 2 kort."
    servo = next(c for c in view.cards if c.product == 9)
    assert (servo.name, servo.base) == ("MGP servokort med ingångar", 1)
    assert [(ch.channel, ch.address, ch.objects) for ch in servo.channels[:2]] == [
        (1, 1, ["växel 1"]),
        (2, 2, ["växel 2"]),
    ]
    view = shown(client.put(K + "/card", json={"card": servo.address, "module": "M01"}))
    switch = row(view, "switch", "1")
    assert (switch.card, switch.module, switch.channel) == (servo.address, "M01", 1)
    assert client.put(K + "/card", json={"card": 999, "module": "M9"}).status_code == 404
    # A wagon on track 1.
    view = shown(client.post(K + "/learn", json={"kind": "track_circuit", "name": "Spår 1"}))
    assert view.learning is not None and view.learning.text == "Ställ en vagn på Spår 1."
    view = shown(client.post(K + "/latsas", json={"track_circuit": "Spår 1"}))
    assert view.question is not None
    assert view.question.text == "Givaren 3 slog till. Är det Spår 1?"
    view = shown(client.post(K + "/answer", json={"question": view.question.id, "answer": "yes"}))
    assert view.message == "Spår 1 är grön: givare 3."
    assert row(view, "track_circuit", "Spår 1").state.value == "green"
    kept = StationModel.model_validate_json(to_json(model()))
    saved = client.get(API + "/studio/model").json()
    assert saved["summary"]["track_circuits"] == len(kept.track_circuits)
    # Lägg om switch 1.
    view = shown(client.post(K + "/learn", json={"kind": "switch", "name": "1"}))
    assert view.question is not None and view.question.text.startswith("Växel 1 ska lägga sig")
    pump(client)
    view = shown(client.get(K))
    assert view.question is not None and view.question.seen is not None
    view = shown(client.post(K + "/answer", json={"question": view.question.id, "answer": "yes"}))
    switch = row(view, "switch", "1")
    assert (switch.state.value, switch.feedback.value) == ("green", "card")
    heard = TklListen.model_validate(client.get(K + "/lyssna").json())
    assert heard.connected and heard.messages
    texts = [m.text for m in heard.messages]
    assert any(t.startswith("Givare 3: slog till") for t in texts)
    assert any("Discover" in t for t in texts)
    view = shown(client.post(K + "/disconnect"))
    assert not view.loconet.connected


def test_level_3_turns_on_when_the_addresses_pass_the_checks(client: TestClient) -> None:
    """STD-17 and §6: level 3 needs addresses, unique per bus, and every switch's feedback;
    the owner's own changes are saved in the model (STUDIO-19, STUDIO-24)."""
    refused = client.post(K + "/level", json={"level": 3})
    assert refused.status_code == 409 and "Ingen adress" in refused.json()["detail"]
    view = shown(client.put(K + "/object", json={"kind": "signal", "name": "In", "address": 201}))
    assert row(view, "signal", "In").state.value == "yellow"
    assert view.level_3.possible is False and view.level_3.problems
    for name in ("1", "2"):
        client.put(K + "/object", json={"kind": "switch", "name": name, "feedback": "none"})
    view = shown(client.get(K))
    assert any("saknar givare" in p for p in view.level_3.problems)
    for circuit in [o.name for o in view.objects if o.kind.value == "track_circuit"]:
        client.put(K + "/object", json={"kind": "track_circuit", "name": circuit, "without": True})
    view = shown(client.put(K + "/object", json={"kind": "signal", "name": "D", "without": True}))
    assert row(view, "signal", "D").state.value == "without"
    assert view.level_3.possible, view.level_3.problems
    clash = shown(client.put(K + "/object", json={"kind": "signal", "name": "Ut", "address": 201}))
    assert clash.level_3.problems == [
        "Adressen LocoNet 201 används av både signal In och signal Ut."
    ]
    refused = client.post(K + "/level", json={"level": 3})
    assert refused.status_code == 422 and refused.json()["detail"]["problems"]
    shown(client.put(K + "/object", json={"kind": "signal", "name": "Ut", "address": 202}))
    view = shown(client.post(K + "/level", json={"level": 3}))
    assert view.level == 3 and view.level_3.on
    assert client.get(API + "/state").json()["station"]["level"] == 3
    clash = client.put(K + "/object", json={"kind": "signal", "name": "Ut", "address": 201})
    assert clash.status_code == 422, "at level 3 the model may not stop running"
    assert clash.json()["detail"]["problems"] == [
        "Adressen LocoNet 201 används av både signal In och signal Ut."
    ]
    view = shown(client.post(K + "/level", json={"level": 2}))
    assert view.level == 2


def test_learning_waits_while_routes_are_set(client: TestClient) -> None:
    shown(client.post(K + "/connect", json={"type": "pretend"}))
    assert client.post(S + "/route", json={"start": "In", "end": "12"}).status_code == 200
    busy = client.post(K + "/learn", json={"kind": "switch", "name": "1"})
    assert busy.status_code == 409 and "lagda vägar" in busy.json()["detail"]


class Echoing:
    """A LocoBuffer on a bench: every message comes back as it went out."""

    label = "bänken"

    def __init__(self) -> None:
        self.out = b""
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)
        self.out += data

    def read(self, timeout: float) -> bytes:
        data, self.out = self.out, b""
        return data

    def close(self) -> None:
        pass


def test_a_locobuffer_or_a_btlocobridge_is_opened_through_the_port_layer(tmp_path: Path) -> None:
    opened: list[tuple[LoconetType, str, int]] = []
    bench = Echoing()

    def opener(kind: LoconetType, port: str, channel: int) -> Transport:
        opened.append((kind, port, channel))
        if port == "/dev/upptagen":
            raise TransportError("/dev/upptagen kan inte öppnas: Device or resource busy.")
        return bench

    client = tkl(tmp_path, loconet_settings=Settings(background=False, opener=opener))
    set_up(client)
    with_model(client)
    busy = client.post(K + "/connect", json={"type": "locobuffer", "port": "/dev/upptagen"})
    assert busy.status_code == 409 and "kan inte öppnas" in busy.json()["detail"]
    assert shown(client.get(K)).loconet.error is not None
    view = shown(client.post(K + "/connect", json={"type": "locobuffer", "port": "/dev/ttyACM0"}))
    assert view.loconet.label == "LocoNet ansluten via LocoBuffer USB (/dev/ttyACM0)"
    assert len(bench.written) >= 1, "the interrogation went out"
    view = shown(
        client.post(
            K + "/connect", json={"type": "btlocobridge", "port": "AA:BB:CC:DD:EE:FF", "channel": 2}
        )
    )
    assert opened[-1] == (LoconetType.BTLOCOBRIDGE, "AA:BB:CC:DD:EE:FF", 2)
    assert client.post(K + "/latsas", json={"track_circuit": "Spår 1"}).status_code == 409


def test_the_cloud_never_opens_a_port_and_shows_level_3_as_unavailable(tmp_path: Path) -> None:
    """TKLMOLN-08, STV-27: TKL in the cloud never has LocoNet; the objects and their addresses
    can still be shown and given."""
    opened: list[object] = []

    def opener(kind: LoconetType, port: str, channel: int) -> Transport:
        opened.append(kind)
        raise AssertionError("the cloud must never open a port")

    app = create_app(
        tmp_path, mode=TklMode.CLOUD, discover=lambda: [], loconet_settings=Settings(opener=opener)
    )
    client = TestClient(app)
    assert set_up(client).status_code == 201
    with_model(client)
    assert app.state.loconet is None
    view = shown(client.get(K))
    assert not view.loconet.available and "aldrig LocoNet" in (view.loconet.reason or "")
    assert not view.level_3.possible and view.level_3.reason == view.loconet.reason
    assert client.get(K + "/ports").json() == []
    for path, body in (
        ("/connect", {"type": "locobuffer", "port": "/dev/ttyACM0"}),
        ("/connect", {"type": "pretend"}),
        ("/discover", None),
        ("/learn", {"kind": "switch", "name": "1"}),
        ("/level", {"level": 3}),
        ("/latsas", {"track_circuit": "Spår 1"}),
    ):
        answer = client.post(K + path, json=body)
        assert answer.status_code == 409 and "aldrig LocoNet" in answer.json()["detail"], path
    assert opened == []
    view = shown(client.put(K + "/object", json={"kind": "signal", "name": "In", "address": 201}))
    assert row(view, "signal", "In").state.value == "yellow"
    assert TklListen.model_validate(client.get(K + "/lyssna").json()).connected is False


@pytest.fixture
def level_3_with_hub(tmp_path: Path) -> tuple[TestClient, PretendHub]:
    hub = PretendHub()
    app = create_app(
        tmp_path,
        http=lambda: httpx.Client(transport=httpx.MockTransport(hub.handle)),
        discover=lambda: [],
        loconet_settings=QUICK,
    )
    client = TestClient(app)
    assert set_up(client).status_code == 201
    with_model(client, level_3(model()))
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
            preview=True,
        ),
    )
    return client, hub


def test_at_level_3_the_interlocking_follows_the_pretend_layout_and_reports_occupancy(
    level_3_with_hub: tuple[TestClient, PretendHub],
) -> None:
    """STV-11, STV-15, STV-10: connected at level 3, a route waits for its switch and then
    clears; the train number follows the circuits; the line's occupancy goes up to the hub as
    section.occupancy."""
    client, hub = level_3_with_hub
    view = shown(client.post(K + "/connect", json={"type": "pretend"}))
    assert view.level_3.on
    state = client.get(S).json()
    assert state["field"]["mode"] == "pretend"
    pump(client)
    answer = TklAnswer.model_validate(
        client.post(S + "/route", json={"start": "In", "end": "22"}).json()
    )
    assert answer.accepted and answer.state.routes[0].waiting == ["1"]
    pump(client)
    after = client.get(S).json()
    assert after["routes"][0]["aspect"] == "proceed", after["routes"][0]
    assert after["switches"]["1"]["reported"] == "-"
    service = client.app.state.loconet  # type: ignore[attr-defined]
    assert service.pretend.proceed("In")
    occupancy = [c for c in hub.commands if c.action == station.Action.SECTION_OCCUPANCY]
    assert [c.payload for c in occupancy] == [
        {"section": "s-vast", "occupied": False},
        {"section": "s-ost", "occupied": False},
    ], "what the interrogation said on connecting"
    client.post(K + "/latsas", json={"track_circuit": "Infart V"})
    occupancy = [c for c in hub.commands if c.action == station.Action.SECTION_OCCUPANCY]
    assert occupancy[-1].payload == {"section": "s-vast", "occupied": True}
    client.post(K + "/latsas", json={"track_circuit": "Vx1"})
    state = client.get(S).json()
    assert state["routes"][0]["at"] == 0 and state["numbers"][0]["section"] == "Vx1"
    step = TklAnswer.model_validate(
        client.post(S + "/step", json={"route": state["routes"][0]["id"]}).json()
    )
    assert not step.accepted and "spårledningarna" in step.message
    shown(client.post(K + "/disconnect"))
    assert client.get(S).json()["field"] is None


def test_the_connection_has_a_thread_of_its_own_that_ends_with_it(tmp_path: Path) -> None:
    """As TKL runs: the layout's answers come in on the connection's own thread, so that the
    card's report after Lägg om shows without anyone asking; disconnecting ends the thread."""
    settings = Settings(discover_seconds=0.05, reply_seconds=0.05, movement=0.05)
    client = tkl(tmp_path, loconet_settings=settings)
    set_up(client)
    with_model(client)
    shown(client.post(K + "/connect", json={"type": "pretend"}))
    service = client.app.state.loconet  # type: ignore[attr-defined]
    thread = service._thread
    assert thread is not None and thread.is_alive()
    shown(client.post(K + "/learn", json={"kind": "switch", "name": "1"}))
    for _ in range(100):
        view = shown(client.get(K))
        if view.question is not None and view.question.seen == (
            "Kortet rapporterade avvikande (\N{MINUS SIGN})."
        ):
            break
        time.sleep(0.02)
    else:
        raise AssertionError("the card's report never came")
    shown(client.post(K + "/disconnect"))
    thread.join(timeout=2)
    assert not thread.is_alive()
