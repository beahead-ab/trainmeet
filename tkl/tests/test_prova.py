"""Studio's Prova (#85 del c, STUDIO-05, STUDIO-21, STUDIO-27): TKL's simulator runs a train
through every train route and every shunting route, one at a time from a clean state. At level 3
the interlocking runs against the pretend LocoNet through the same bus and link as on the layout;
at level 1–2 with Kör.

The made-up Provby is the small station; the reference stations are found from their model files
(RS13): nothing here names a station.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from contracts.station_model import (
    Address,
    FeedbackType,
    Position,
    StationModel,
    SwitchFeedback,
)
from contracts.tkl import (
    AddressState,
    ObjectKind,
    TklProvaResult,
    TklProvaSimulator,
)
from tkl import prova
from tkl.loconet.messages import SensorReport, SwitchRequest, decode
from tkl.loconet.objects import changed, confirmed, objects
from tkl.loconet.simulator import PretendLoconet
from tkl.provkor import idle
from tkl.stallverk import plant_of
from tkl.standard import problems
from tkl.tests.niva3 import level_3
from tkl.tests.provstation import provby

MODELS = Path(__file__).resolve().parents[2] / "tkl" / "referens"
STATIONS = sorted(p.name.removesuffix(".tkl.json") for p in MODELS.glob("*.tkl.json"))
PASSED, FAILED = TklProvaResult.PASSED, TklProvaResult.FAILED
NO_FEEDBACK = "Ingen återrapport från växel 1 inom 6 sekunder."


def reference(station: str) -> StationModel:
    return StationModel.model_validate_json((MODELS / f"{station}.tkl.json").read_text("utf-8"))


def addressed(model: StationModel) -> StationModel:
    """Every object of a reference station given a made-up address, confirmed on the layout,
    and the station at level 3."""
    numbers = {ObjectKind.SWITCH: 1, ObjectKind.SIGNAL: 1001, ObjectKind.TRACK_CIRCUIT: 2001}
    for o in objects(model):
        if o.state == AddressState.WITHOUT:
            continue
        address = confirmed(Address(number=numbers[o.kind]))
        numbers[o.kind] += 1
        if o.kind == ObjectKind.SWITCH:
            feedback = SwitchFeedback(type=FeedbackType.CARD)
            model = changed(model, o.kind, o.name, address=address, feedback=feedback)
        else:
            model = changed(model, o.kind, o.name, address=address)
    return model.model_copy(update={"level": 3})


def test_every_route_passes_on_a_made_up_station_at_level_3() -> None:
    """STUDIO-27: a train through every train route and every shunting route, against the
    pretend LocoNet (STUDIO-21)."""
    model = level_3(provby())
    tried = prova.try_all(model)
    assert len(tried) == len(plant_of(model).preferred())
    assert {r.kind.value for r in tried} == {"train", "shunting"}
    assert [r.reason for r in tried if r.result != PASSED] == []
    assert all(r.pieces for r in tried)
    assert tried[0].kind.value == "train" and tried[-1].kind.value == "shunting"
    assert prova.simulator(model.level) == TklProvaSimulator.PRETEND


def test_every_route_passes_with_kor_at_level_2() -> None:
    """For a station at level 1–2, the same interlocking with Kör stepping."""
    model = provby()
    tried = prova.try_all(model)
    assert len(tried) == len(plant_of(model).preferred())
    assert all(r.result == PASSED for r in tried)
    assert prova.simulator(model.level) == TklProvaSimulator.KOR


def test_the_train_runs_on_the_pretend_layout() -> None:
    """The switch moves and reports, the signal clears, the train occupies and frees the track
    circuits, and the route ends with the arrival: all as LocoNet messages (STUDIO-21)."""
    model = level_3(provby())
    made: list[PretendLoconet] = []

    def layout(found: StationModel) -> PretendLoconet:
        made.append(PretendLoconet.from_model(found))
        return made[-1]

    way = next(w for w in prova.ways(model) if (w.start, w.end) == ("In", "22"))
    tried = prova.try_route(model, way, layout)
    assert tried.result == PASSED, tried.reason
    [pretend] = made
    sent = [decode(d) for d in pretend.received()]
    ordered = [m for m in sent if isinstance(m, SwitchRequest) and m.on]
    assert any(m.address == 1 for m in ordered), "switch 1 was ordered"
    assert pretend.position("1") == Position.MINUS
    sensors = [m for r in pretend.recorded if r.direction == "in" for m in [decode(r.data)]]
    assert any(isinstance(m, SensorReport) and m.active for m in sensors), "a circuit occupied"
    assert pretend.occupied("Spår 2") and not pretend.occupied("Vx1"), "the train has arrived"
    assert not pretend.proceed("In"), "In went back to stop behind the train"


def test_a_broken_switch_fails_with_its_reason() -> None:
    """A switch whose feedback never comes holds every route over it, with the reason; the
    others pass, and the failures come first."""
    model = level_3(provby())

    def silent(_found: StationModel) -> PretendLoconet:
        return PretendLoconet.from_model(level_3(provby(), feedback=FeedbackType.NONE))

    tried = prova.try_all(model, layout=silent)
    over = {(w.start, w.end) for w in prova.ways(model) if "1" in w.route.positions}
    over_1 = [r for r in tried if (r.start, r.end) in over]
    assert over_1 and all(r.result == FAILED for r in over_1)
    assert {r.reason for r in over_1 if (r.start, r.end) == ("In", "12")} == {NO_FEEDBACK}
    shunting = next(r for r in tried if (r.start, r.end) == ("D", "22"))
    assert shunting.result == PASSED, "a route over no switch runs"
    ordered = prova.failures_first(tried)
    assert [r.result for r in ordered] == sorted(
        (r.result for r in tried), key=lambda result: result != FAILED
    )


def test_a_grey_object_fails_with_the_interlockings_reason() -> None:
    """STV-17: a route over an object without an address is refused, and Prova says why."""
    model = changed(level_3(provby()), ObjectKind.SIGNAL, "In", address=None)
    tried = {(r.start, r.end): r for r in prova.try_all(model)}
    assert tried[("In", "12")].result == FAILED
    assert tried[("In", "12")].reason == (
        "Signalen In är grå: den har ingen adress. Koppla in den i Studio "
        "\N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} Koppla in (STV-17)."
    )
    assert tried[("12", "Ut2")].result == PASSED


@pytest.mark.parametrize("station", STATIONS)
def test_the_reference_stations_routes_all_pass_in_the_simulator(station: str) -> None:
    """At the station's own level, and at level 3 against the pretend LocoNet when every
    section has a track circuit and every object an address."""
    model = reference(station)
    tried = prova.try_all(model)
    assert len(tried) == len(plant_of(model).preferred()) > 0
    assert [(r.start, r.end, r.reason) for r in tried if r.result != PASSED] == []
    lifted = addressed(model)
    if not all(s.circuit for s in plant_of(lifted).sections.values()):
        return
    assert problems(lifted) == []
    tried = prova.try_all(lifted)
    assert [(r.start, r.end, r.reason) for r in tried if r.result != PASSED] == []


def test_the_runner_runs_in_the_background_with_its_progress() -> None:
    """Prova runs in the background: the page sees the routes so far, failures first, and the
    result is kept when the run is over."""
    model = level_3(provby())
    gate, waiting = threading.Event(), threading.Event()
    calls = []

    def layout(found: StationModel) -> PretendLoconet:
        calls.append(found)
        if len(calls) == 3:
            waiting.set()
            gate.wait(10)
        return PretendLoconet.from_model(found)

    runner = prova.Runner(layout=layout)
    kept: list[prova.Saved] = []

    def finish(job: prova.Job, complete: bool) -> None:
        assert complete
        kept.append(prova.saved_of(job, None))

    job = runner.start("slot", model, "fp", finish)
    assert waiting.wait(10)
    shown = prova.view(model, "fp", None, runner.job("slot"), idle(False, None))
    assert (shown.running, shown.done, shown.total) == (True, 2, 11)
    assert runner.start("slot", model, "fp", finish) is job, "one run per station"
    gate.set()
    assert job.thread is not None
    job.thread.join(10)
    assert runner.job("slot") is None
    [saved] = kept
    assert saved.tried and len(saved.routes) == 11
    done = prova.view(model, "fp", ("fp", saved), None, idle(False, None))
    assert done.tried and not done.running and done.passed == 11
    assert done.message == "Klart: varje väg gick igenom. Stationen kan öppnas i Ställverket."
    other = prova.view(model, "another", ("fp", saved), None, idle(False, None))
    assert other.invalidated and not other.tried and other.routes == []


def test_the_runner_takes_a_few_stations_at_a_time() -> None:
    model = provby()
    gate = threading.Event()
    runner = prova.Runner(most=1)
    finished = threading.Event()

    def finish(_job: prova.Job, _complete: bool) -> None:
        gate.wait(10)
        finished.set()

    runner.start("a", model, "fp", finish)
    with pytest.raises(prova.Busy):
        runner.start("b", model, "fp", finish)
    gate.set()
    assert finished.wait(10)
    runner.close()
