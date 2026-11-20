"""Studio turns a drawing read by TrainMeet CAD into a proposal for the station model (#89 del c4,
TKL23, TKL27, TKL81): the tracks with their boundaries and signals, the switches with their legs
and numbers, the signals with type, name, address and the way they apply, the line exits and the
station tracks; everything assumed and yellow until the owner confirms it, and the engine lays out
the panel. The read is the contract's example: CAD's reader on its synthetic signal plan
(contracts/examples/exempelby.drawing-read.json). Nothing here names a station (RS13)."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from contracts.cad import DrawingRead
from contracts.station_model import (
    Address,
    NodeType,
    SignalType,
    Source,
    StationModel,
    SwitchType,
)
from contracts.tkl import TklDrawingState
from tkl.standard import derive, problems
from tkl.studio import rita
from tkl.studio import ritning as studio

EXAMPLE = Path(__file__).resolve().parents[2] / "contracts/examples/exempelby.drawing-read.json"


@cache
def example() -> DrawingRead:
    return DrawingRead.model_validate(json.loads(EXAMPLE.read_text(encoding="utf-8")))


def proposal() -> StationModel:
    return studio.proposal(example(), "exb", "Exempelby", "plan.pdf")


def test_the_read_becomes_the_station_model_by_the_standard() -> None:
    model = proposal()
    assert model.level == 2
    kinds = [n.type for n in model.nodes]
    assert kinds.count(NodeType.SWITCH) == 5
    assert kinds.count(NodeType.LINE_EXIT) == 4
    assert kinds.count(NodeType.BUFFER_STOP) == 1
    # Each boundary cuts its track; the seven signals stand at seven of the nine boundaries.
    assert kinds.count(NodeType.SIGNAL_POINT) == 7
    assert kinds.count(NodeType.BLOCK_BOUNDARY) == 2
    numbers = sorted(s.number for s in model.switches)
    assert numbers == ["1", "2", "3", "4", "5"]
    assert all(
        s.type == SwitchType.ORDINARY and s.trunk and s.straight and s.diverging
        for s in model.switches
    )
    signals = {s.name: s for s in model.signals}
    assert set(signals) == {"11", "12", "13", "14", "15", "21", "22"}
    assert (signals["13"].type, signals["13"].lamps) == (SignalType.HSI, 3)
    assert (signals["21"].type, signals["21"].lamps) == (SignalType.HDVSI, None)
    assert signals["22"].type == SignalType.DVSI
    address = signals["11"].address
    assert isinstance(address, Address) and address.number == 101
    pieces = {p.id: p for p in model.pieces}
    for name, west in (("11", True), ("12", False), ("21", False), ("22", True)):
        signal = signals[name]
        approach = pieces[signal.approach]
        # A signal for trains going east is approached from the west, and the other way.
        node_x = (
            approach.geometry[-1][0] if approach.end == signal.node else approach.geometry[0][0]
        )
        far_x = approach.geometry[0][0] if approach.end == signal.node else approach.geometry[-1][0]
        assert (far_x < node_x) == west, name
    assert sorted(e.id for e in model.line_exits) == ["Väst 1", "Väst 2", "Öst 1", "Öst 2"]
    assert sorted(t.id for t in model.station_tracks) == ["1", "2", "3", "4"]


def test_everything_is_a_proposal_until_the_owner_confirms_it() -> None:
    model = proposal()
    origins = [p.origin for p in model.pieces] + [s.origin for s in model.switches]
    origins += [s.origin for s in model.signals] + [e.origin for e in model.line_exits]
    assert all(
        o is not None and o.source == Source.ASSUMED and not o.confirmed and o.note == rita.READ
        for o in origins
    )
    assert rita.unconfirmed(model) == len(origins)
    assert rita.unconfirmed_problems(model)
    confirmed = model.model_copy(
        update={
            key: [
                i.model_copy(update={"origin": i.origin.model_copy(update={"confirmed": True})})
                for i in getattr(model, key)
            ]
            for key in ("pieces", "switches", "signals", "line_exits")
        }
    )
    assert rita.unconfirmed(confirmed) == 0 and rita.unconfirmed_problems(confirmed) == []


def test_the_engine_lays_out_the_panel_and_the_routes_follow() -> None:
    """TKL23, TKL81: the proposal's grid is the engine's first proposal; the model has no
    problems but the owner's confirmation, and the routes are derived."""
    made = studio.drawing(example(), "exb", "Exempelby", "plan.pdf")
    assert made.proposal and made.model.panel is not None
    view = rita.view(made, TklDrawingState.DRAFT)
    assert view.loose == []
    blocking = [f.text for f in view.findings if f.problem]
    assert blocking == rita.unconfirmed_problems(view.model)
    assert problems(view.model) == []
    routes = derive(view.model)
    assert len([r for r in routes if r.kind.value == "train"]) >= 4
