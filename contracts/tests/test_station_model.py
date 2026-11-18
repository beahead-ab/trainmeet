"""trainmeet.station-model/1: a model file reads into the model and writes back the same."""

from __future__ import annotations

import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from contracts.generate import SCHEMA_DIR, STATION_MODEL, filename
from contracts.station_model import (
    FORMAT,
    Address,
    FeedbackType,
    StationModel,
    SwitchFeedback,
    dump,
    to_json,
)

SMALL: dict[str, Any] = {
    "format": FORMAT,
    "station_id": "provby",
    "name": "Provby",
    "level": 2,
    "origin": {"source": "drawn"},
    "nodes": [
        {"id": "V", "type": "line_exit"},
        {"id": "W", "type": "signal_point"},
        {"id": "1", "type": "switch"},
        {"id": "A", "type": "buffer_stop"},
        {"id": "B", "type": "buffer_stop"},
    ],
    "pieces": [
        {"id": "a", "start": "V", "end": "W", "geometry": [[0.0, 0.0], [100.0, 0.0]]},
        {"id": "b", "start": "W", "end": "1", "track": "1"},
        {"id": "c", "start": "1", "end": "A"},
        {"id": "d", "start": "1", "end": "B", "origin": {"source": "assumed"}},
    ],
    "switches": [
        {"number": "1", "type": "ordinary", "node": "1", "trunk": "b", "straight": "c",
         "diverging": "d", "feedback": {"type": "none"}},
    ],
    "levers": [{"id": "1", "plus": {"1": "+"}, "minus": {"1": "-"}}],
    "signals": [
        {"name": "In", "type": "hsi", "lamps": 4, "node": "W", "approach": "a",
         "address": {"number": 1201}},
    ],
    "track_circuits": [{"name": "Vx1", "pieces": ["b", "c", "d"]}],
    "line_exits": [{"id": "V", "node": "V", "neighbour": "Västby", "signals": ["In"]}],
    "functions": [{"type": "signal_stop", "name": "Signalstopp", "track_circuits": ["Vx1"]}],
}  # fmt: skip


def test_a_model_file_round_trips() -> None:
    model = StationModel.model_validate(SMALL)
    assert dump(model) == SMALL
    assert StationModel.model_validate_json(to_json(model)) == model
    assert to_json(StationModel.model_validate_json(to_json(model))) == to_json(model)


def test_defaults_are_left_out_and_the_format_comes_first() -> None:
    data = dump(StationModel.model_validate(SMALL))
    assert next(iter(data)) == "format"
    assert "control" not in data["switches"][0], "TKL lays it: the default"
    assert "confirmed" not in data["pieces"][3]["origin"]


def test_the_bus_is_loconet_unless_another_is_named() -> None:
    model = StationModel.model_validate(SMALL)
    address = model.signals[0].address
    assert isinstance(address, Address) and address.bus == "LocoNet"
    other = {**SMALL["signals"][0], "address": {"bus": "XpressNet", "number": 3}}
    data = dump(StationModel.model_validate({**SMALL, "signals": [other]}))
    assert data["signals"][0]["address"] == {"bus": "XpressNet", "number": 3}


def test_level_3_has_feedback_polarity_and_without() -> None:
    """#85: the switch's feedback, the address's polarity and its own origin (green in Koppla
    in), and Utan adress for a virtual signal (STUDIO-17, STUDIO-24, TKL26)."""
    switch = {
        **SMALL["switches"][0],
        "address": {
            "number": 1,
            "reversed": True,
            "origin": {"source": "layout", "confirmed": True},
        },
        "feedback": {"type": "sensors", "straight": {"number": 11}, "diverging": {"number": 12}},
    }
    signal = {**SMALL["signals"][0], "address": "without"}
    model = StationModel.model_validate({**SMALL, "switches": [switch], "signals": [signal]})
    assert model.signals[0].address == "without"
    address = model.switches[0].address
    assert address is not None and address.reversed and address.origin is not None
    assert address.origin.confirmed
    assert model.switches[0].feedback == SwitchFeedback(
        type=FeedbackType.SENSORS, straight=Address(number=11), diverging=Address(number=12)
    )
    data = dump(model)
    assert data["switches"][0]["feedback"]["type"] == "sensors"
    assert data["signals"][0]["address"] == "without"
    assert "reversed" not in dump(StationModel.model_validate(SMALL))["signals"][0]["address"]


def test_points_and_names_stay_on_one_line() -> None:
    text = to_json(StationModel.model_validate(SMALL))
    assert "[0.0, 0.0]," in text
    assert '"pieces": ["b", "c", "d"]' in text


def test_the_small_model_follows_the_published_schema() -> None:
    schema = json.loads((SCHEMA_DIR / filename(STATION_MODEL)).read_text("utf-8"))
    assert sorted(Draft202012Validator(schema).iter_errors(SMALL), key=str) == []


def test_never_stored_routes_and_lever_positions_are_not_fields() -> None:
    """STD-07: routes, shunting routes, lever positions and conflicts are derived."""
    fields = set(StationModel.model_fields)
    assert not fields & {"routes", "train_routes", "shunting_routes", "conflicts", "positions"}


@pytest.mark.parametrize(
    "change",
    [
        {"level": 4},
        {"format": "trainmeet.station-model/2"},
        {"signals": [{**SMALL["signals"][0], "type": "Hsi 4"}]},
    ],
)
def test_a_wrong_value_is_refused(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        StationModel.model_validate({**SMALL, **change})
