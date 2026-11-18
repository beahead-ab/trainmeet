"""Studio's Prova in TKL's server (#85 del c) under /api/tkl/1/studio/prova: the simulated test in
the background, Klart for Ställverket and the results invalidated when the model changes
(STUDIO-05, STUDIO-27); Provkör against the pretend LocoNet with the field mode set as if it were
the layout (STUDIO-05); and Prova only against a preview run, never a real meet (STUDIO-12).
Nothing here opens a real port, and nothing names a station (RS13).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts import station
from contracts.station_model import StationModel
from contracts.tkl import LoconetType, TklProva, TklProvaResult
from tkl.app import NOT_PREVIEW, PROVA_CODE, PROVKOR_BUSY, PROVKOR_LAYOUT
from tkl.loconet.service import REAL_MEET, Settings
from tkl.loconet.simulator import PretendLoconet
from tkl.loconet.transports import Transport
from tkl.provkor import SKIPPED, WRONG
from tkl.store import LOCAL, Connection
from tkl.tests.niva3 import level_3
from tkl.tests.test_app import API, set_up, tkl
from tkl.tests.test_app_stallverk import PLACE, PretendHub, model, with_model

P = API + "/studio/prova"
K = API + "/studio/koppla-in"
S = API + "/stallverk"
NOT_TRIED = (
    "Stationen är inte provad i Studio \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} Prova."
)


def shown(response: httpx.Response) -> TklProva:
    assert response.status_code == 200, response.text
    return TklProva.model_validate(response.json())


def finished(client: TestClient, seconds: float = 30.0) -> TklProva:
    """Prova when the run in the background is over."""
    deadline = time.monotonic() + seconds
    while True:
        found = shown(client.get(P))
        if not found.running or time.monotonic() > deadline:
            return found
        time.sleep(0.02)


def tried(client: TestClient) -> bool:
    return bool(client.get(API + "/state").json()["station"]["tried"])


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    made = tkl(tmp_path)
    assert set_up(made).status_code == 201
    return made


def test_prova_needs_a_model(client: TestClient) -> None:
    found = shown(client.get(P))
    assert found.level == 0 and found.simulator is None and found.message
    assert client.post(P + "/start").status_code == 404


def test_prova_runs_every_route_and_klart_opens_stallverket(client: TestClient) -> None:
    """STUDIO-05, STUDIO-27: before Prova, Ställverket shows the note; when every route has
    passed, the station is tried and the note goes."""
    with_model(client)
    before = shown(client.get(P))
    assert (before.simulator.value, before.total, before.tried) == ("kor", 11, False)  # type: ignore[union-attr]
    assert before.message == NOT_TRIED and not tried(client)
    started = shown(client.post(P + "/start"))
    assert started.running or started.done == started.total
    done = finished(client)
    assert (done.done, done.total, done.passed, done.failed) == (11, 11, 11, 0)
    assert done.tried and done.finished is not None
    assert done.message == "Klart: varje väg gick igenom. Stationen kan öppnas i Ställverket."
    assert all(r.result == TklProvaResult.PASSED and r.pieces for r in done.routes)
    assert tried(client), "Klart: Ställverket opens without the note"
    assert client.get(S).status_code == 200, "a note, never a lock"


def test_the_results_are_kept_and_invalidated_when_the_model_changes(
    client: TestClient, tmp_path: Path
) -> None:
    with_model(client)
    shown(client.post(P + "/start"))
    assert finished(client).tried
    again = tkl(tmp_path)
    assert again.post(API + "/unlock", json={"pin": "4711"}).status_code == 200
    assert shown(again.get(P)).tried, "kept with the station"
    other = model()
    signals = [s.model_copy(update={"lamps": 3}) if s.name == "In" else s for s in other.signals]
    with_model(client, other.model_copy(update={"signals": signals}))
    after = shown(client.get(P))
    assert after.invalidated and not after.tried and after.routes == []
    assert after.message == "Stationsmodellen har ändrats sedan Prova kördes: prova stationen igen."
    assert not tried(client)


def test_a_station_whose_routes_fail_is_not_klart(client: TestClient) -> None:
    """Failures first, each with its reason; Klart only when every route passed."""
    grey = level_3(model())
    signals = [
        s.model_copy(update={"address": None}) if s.name == "In" else s for s in grey.signals
    ]
    with_model(client, grey.model_copy(update={"signals": signals}))
    shown(client.post(P + "/start"))
    done = finished(client)
    assert done.simulator.value == "pretend"  # type: ignore[union-attr]
    assert done.failed == 2 and not done.tried and not tried(client)
    assert [r.result for r in done.routes[:2]] == [TklProvaResult.FAILED] * 2
    assert {r.start for r in done.routes[:2]} == {"In"}
    assert all("Signalen In är grå" in (r.reason or "") for r in done.routes[:2])
    assert done.message == "2 av 11 vägar gick inte igenom."


# --- Provkör, against the pretend LocoNet as if it were the layout --------------------------


class Layout:
    """The pretend LocoNet behind a LocoBuffer's port, on a clock the test moves."""

    def __init__(self) -> None:
        self.seconds = 0.0
        self.made: list[PretendLoconet] = []
        self.model: StationModel | None = None

    def clock(self) -> float:
        return self.seconds

    def open(self, kind: LoconetType, port: str, channel: int) -> Transport:
        assert kind == LoconetType.LOCOBUFFER and self.model is not None
        made = PretendLoconet.from_model(self.model, clock=self.clock, movement=0.5)
        self.made.append(made)
        return made


@pytest.fixture
def on_layout(tmp_path: Path) -> tuple[TestClient, Layout]:
    layout = Layout()
    settings = Settings(
        background=False,
        opener=layout.open,
        listing=lambda: [],
        clock=layout.clock,
        movement=0.5,
        discover_seconds=0.05,
        reply_seconds=0.05,
    )
    client = tkl(tmp_path, loconet_settings=settings)
    assert set_up(client).status_code == 201
    layout.model = level_3(model())
    with_model(client, layout.model)
    return client, layout


def run(client: TestClient, layout: Layout, seconds: float = 1.5) -> None:
    service = client.app.state.loconet  # type: ignore[attr-defined]
    end = layout.seconds + seconds
    while layout.seconds < end:
        layout.seconds += 0.05
        for _ in range(5):
            service.pump()


def test_provkor_needs_loconet_to_the_layout(on_layout: tuple[TestClient, Layout]) -> None:
    client, _ = on_layout
    found = shown(client.get(P))
    assert not found.provkor.available and found.provkor.reason == PROVKOR_LAYOUT
    assert client.post(K + "/connect", json={"type": "pretend"}).status_code == 200
    assert shown(client.get(P)).provkor.reason == PROVKOR_LAYOUT, "the pretend LocoNet is Prova"
    started = client.post(P + "/provkor/start")
    assert (started.status_code, started.json()["detail"]) == (409, PROVKOR_LAYOUT)


def test_provkor_sets_each_route_on_the_layout_and_asks_the_owner(
    on_layout: tuple[TestClient, Layout],
) -> None:
    """STUDIO-05, STUDIO-27: TKL orders the switches and waits for their feedback, then asks
    the owner about the signal and the path; right, wrong or skip, and the next route."""
    client, layout = on_layout
    connected = client.post(K + "/connect", json={"type": "locobuffer", "port": "/dev/ttyACM0"})
    assert connected.status_code == 200, connected.text
    run(client, layout, 0.5)
    assert shown(client.get(P)).provkor.available
    first = shown(client.post(P + "/provkor/start")).provkor
    assert first.running and first.total == 11 and first.route is not None
    assert client.get(S).json()["field"]["mode"] == "loconet", "as on the layout"
    answers = ["wrong", "skip"] + ["right"] * 9
    for i, answer in enumerate(answers):
        run(client, layout)
        now = shown(client.get(P)).provkor
        assert now.running and now.done == i and now.route is not None, now
        assert now.question and now.waiting is None, now
        route = now.route
        state = client.get(S).json()
        [laid] = state["routes"]
        pretend = layout.made[-1]
        for part, position in laid["positions"].items():
            assert pretend.position(part).value == position, (route, part)  # type: ignore[union-attr]
        if route.start in ("In", "In2", "11", "12", "21", "22", "D"):
            assert pretend.proceed(route.start), route
            assert f"Visar signalen {route.start}" in now.question
        answered = client.post(P + "/provkor/answer", json={"answer": answer})
        assert answered.status_code == 200, answered.text
    done = shown(client.get(P)).provkor
    assert not done.running and done.done == 11 and done.finished is not None
    results = [(r.result, r.reason) for r in done.routes]
    assert results[0] == (TklProvaResult.FAILED, WRONG)
    assert results[1] == (TklProvaResult.SKIPPED, SKIPPED)
    assert {r for r, _ in results[2:]} == {TklProvaResult.PASSED}
    assert client.get(S).json()["routes"] == [], "every route released after it"
    assert shown(client.get(P)).provkor.routes == done.routes, "kept with the station"
    assert client.post(P + "/provkor/answer", json={"answer": "right"}).status_code == 409


def test_provkor_waits_for_the_feedback_and_refuses_under_set_routes(
    on_layout: tuple[TestClient, Layout],
) -> None:
    client, layout = on_layout
    assert client.post(K + "/connect", json={"type": "locobuffer", "port": "/dev/x"}).is_success
    run(client, layout, 0.5)
    laid = client.post(S + "/route", json={"start": "In", "end": "12"})
    assert laid.json()["accepted"], laid.text
    refused = client.post(P + "/provkor/start")
    assert (refused.status_code, refused.json()["detail"]) == (409, PROVKOR_BUSY)
    route = laid.json()["state"]["routes"][0]["id"]
    run(client, layout)
    assert client.post(S + "/release", json={"route": route}).json()["accepted"]
    started = shown(client.post(P + "/provkor/start")).provkor
    assert started.route is not None and (started.route.start, started.route.end) == ("11", "Ut")
    for _ in range(2):
        run(client, layout)
        assert client.post(P + "/provkor/answer", json={"answer": "skip"}).status_code == 200
    third = shown(client.get(P)).provkor.route
    assert third is not None and (third.start, third.end) == ("21", "Ut"), "switch 1 diverging"
    run(client, layout, 0.05)
    waiting = shown(client.get(P)).provkor
    assert waiting.waiting == "Väntar på återrapport från växel 1 …" and waiting.question is None
    early = client.post(P + "/provkor/answer", json={"answer": "right"})
    assert early.status_code == 409, "nothing to answer before the switch has reported"
    run(client, layout)
    assert shown(client.get(P)).provkor.question
    stopped = shown(client.post(P + "/provkor/stop")).provkor
    assert not stopped.running
    assert client.get(S).json()["routes"] == []


# --- Prova only against a preview run (STUDIO-12) ---------------------------------------------


class Hubs(PretendHub):
    """The hub's /connect: a Provbanan run, or a real meet that refuses Prova as Drift does."""

    def __init__(self, preview: bool, refuses: bool = True) -> None:
        super().__init__()
        self.preview = preview
        self.refuses = refuses
        self.asked: list[station.ConnectRequest] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/station/1/connect" and request.method == "POST":
            asked = station.ConnectRequest.model_validate_json(request.content)
            self.asked.append(asked)
            if asked.preview_only and not self.preview and self.refuses:
                return httpx.Response(409, json={"detail": "Koden gäller en riktig träff."})
            reply = station.ConnectReply(
                client_id="tkl-1", status=station.ApprovalStatus.WAITING, preview=self.preview
            )
            return httpx.Response(201, json=reply.model_dump(mode="json"))
        if request.url.path.startswith("/api/station/1/connect/"):
            reply = station.ConnectReply(
                client_id="tkl-1",
                status=station.ApprovalStatus.APPROVED,
                places=[PLACE],
                key="hemlig-nyckel",
                preview=self.preview,
            )
            return httpx.Response(200, json=reply.model_dump(mode="json"))
        if request.url.path in ("/api/hub", "/api/drift/1/now"):
            return httpx.Response(404, json={"detail": "Finns inte."})
        return super().handle(request)


def with_hub(tmp_path: Path, hub: Hubs, **more: Any) -> TestClient:
    client = tkl(
        tmp_path, http=lambda: httpx.Client(transport=httpx.MockTransport(hub.handle)), **more
    )
    assert set_up(client).status_code == 201
    with_model(client)
    return client


def connect(client: TestClient, **body: Any) -> httpx.Response:
    answer: httpx.Response = client.post(
        API + "/connection", json={"address": "http://hubben.invalid", **body}
    )
    return answer


def test_prova_needs_the_preview_runs_code(tmp_path: Path) -> None:
    client = with_hub(tmp_path, Hubs(preview=True))
    refused = connect(client, prova=True)
    assert (refused.status_code, refused.json()["detail"]) == (422, PROVA_CODE)


def test_prova_is_refused_against_a_real_meet(tmp_path: Path) -> None:
    """STUDIO-12: the hub says no to Prova with its reason, and nothing is kept."""
    hub = Hubs(preview=False)
    client = with_hub(tmp_path, hub)
    refused = connect(client, prova=True, code="123456")
    assert (refused.status_code, refused.json()["detail"]) == (409, "Koden gäller en riktig träff.")
    assert hub.asked[-1].preview_only and hub.asked[-1].level == 2
    assert client.get(API + "/connection").json()["connected"] is False


def test_prova_refuses_a_real_meet_also_when_the_hub_does_not(tmp_path: Path) -> None:
    """An older hub that does not know Prova says it is a real meet: TKL says no itself."""
    client = with_hub(tmp_path, Hubs(preview=False, refuses=False))
    refused = connect(client, prova=True, code="123456")
    assert (refused.status_code, refused.json()["detail"]) == (409, NOT_PREVIEW)
    assert client.get(API + "/connection").json()["connected"] is False


def test_prova_is_accepted_against_provbanan(tmp_path: Path) -> None:
    hub = Hubs(preview=True)
    client = with_hub(tmp_path, hub)
    made = connect(client, prova=True, code="123456")
    assert made.status_code == 200, made.text
    assert made.json()["preview"] is True and made.json()["connected"] is True
    assert hub.asked[-1].preview_only and hub.asked[-1].code == "123456"


def test_tkl_tells_the_hub_its_level(tmp_path: Path) -> None:
    """DRIFT-10: the hub takes section.occupancy only from a station that connected at level 3."""
    hub = Hubs(preview=False)
    client = with_hub(tmp_path, hub)
    assert connect(client, code="123456").status_code == 200
    assert (hub.asked[-1].level, hub.asked[-1].preview_only) == (2, False)
    with_model(client, level_3(model()))
    assert connect(client, code="123456").status_code == 200
    assert hub.asked[-1].level == 3, "connecting again brings the new level"


def test_the_pretend_loconet_is_prova(tmp_path: Path) -> None:
    """STUDIO-12, STUDIO-24: while the pretend LocoNet is connected, Anslut is Prova's; the
    pretend LocoNet is refused while TKL is connected to a real meet; and nothing it reports
    goes up to a real meet."""
    quick = Settings(background=False, discover_seconds=0.05, reply_seconds=0.05, movement=0.0)
    hub = Hubs(preview=False)
    client = with_hub(tmp_path, hub, loconet_settings=quick)
    with_model(client, level_3(model()))
    assert connect(client, code="123456").status_code == 200, "a real meet, without Prova"
    refused = client.post(K + "/connect", json={"type": "pretend"})
    assert (refused.status_code, refused.json()["detail"]) == (409, REAL_MEET)
    assert client.delete(API + "/connection").status_code == 200
    assert client.post(K + "/connect", json={"type": "pretend"}).status_code == 200
    plain = connect(client)
    assert (plain.status_code, plain.json()["detail"]) == (422, PROVA_CODE)
    store = client.app.state.store  # type: ignore[attr-defined]
    service = client.app.state.loconet  # type: ignore[attr-defined]

    def meet(preview: bool) -> None:
        made = Connection(
            address="http://hubben.invalid",
            relay=None,
            hub_name="Hubben",
            client_id="tkl-1",
            status=station.ApprovalStatus.APPROVED,
            places=[PLACE],
            outside_version=1,
            message=None,
            key="hemlig-nyckel",
            preview=preview,
        )
        store.connected(LOCAL, made)

    def out() -> list[station.Command]:
        answer = client.post(S + "/route", json={"start": "12", "end": "Ut2"}).json()
        assert answer["accepted"], answer["message"]
        for _ in range(10):
            service.pump()
        state = client.get(S).json()
        assert next(e for e in state["exits"] if e["exit"] == "O")["aspect"] == "proceed"
        return [c for c in hub.commands if c.action == station.Action.SIGNAL_EXIT]

    meet(preview=False)
    assert out() == [], "nothing went up to the real meet"
    route = client.get(S).json()["routes"][0]["id"]
    assert client.post(S + "/release", json={"route": route}).json()["accepted"]
    meet(preview=True)
    assert json.loads(client.get(API + "/connection").text)["preview"] is True
    assert [c.payload["aspect"] for c in out()] == ["proceed"], "a preview run takes them"


def test_the_model_is_unchanged_by_prova(client: TestClient) -> None:
    """Prova keeps its results beside the model, never in it, and the interlocking stays as it
    was: the simulator has its own."""
    with_model(client)
    before = client.get(API + "/studio/model").json()
    state = client.get(S).json()
    shown(client.post(P + "/start"))
    finished(client)
    assert client.get(API + "/studio/model").json() == before
    assert client.get(S).json()["revision"] == state["revision"]
