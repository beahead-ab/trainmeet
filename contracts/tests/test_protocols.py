"""The station protocol, the terminal protocol, Drift's API and the reasons."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from contracts import drift, station, terminal
from contracts.reasons import TEXT_SV, Reason

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "contracts" / "examples"


def example(name: str) -> dict[str, Any]:
    data = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


# --- Station protocol -------------------------------------------------------------------


def test_handover_and_approaching_are_not_commands() -> None:
    actions = {a.value for a in station.Action}
    assert "train.handover" not in actions  # H22
    assert "train.approaching" not in actions  # an event from Drift (H32)
    assert station.EventKind.TRAIN_APPROACHING.value == "train.approaching"


def test_the_actions_kept_from_v2_and_the_new_ones_for_tkl() -> None:
    kept = {
        "train.lookup",
        "train.track.change",
        "train.departed",
        "train.arrived",
        "clearance.request",
        "clearance.response",
        "clearance.cancel",
        "line.available.publish",
        "line.available.acknowledge",
        "train.position.set",
        "train.crew_ready.set",
    }
    new = {"section.occupancy", "signal.exit"}
    assert {a.value for a in station.Action} == kept | new


def test_every_action_has_a_payload() -> None:
    assert set(station.PAYLOADS) == set(station.Action)


def test_a_command_with_the_wrong_payload_is_refused() -> None:
    data = example("station-1.command.json")
    del data["payload"]["section"]
    with pytest.raises(ValidationError, match="section"):
        station.Command.model_validate(data)


def test_the_key_never_travels_in_a_command() -> None:
    fields = set(station.Command.model_fields)
    assert not fields & {"key", "token", "device_token", "authorization"}


def test_a_rejected_reply_has_a_reason_and_only_then() -> None:
    data = example("station-1.reply.json")
    data["status"] = "rejected"
    with pytest.raises(ValidationError, match="skäl"):
        station.Reply.model_validate(data)
    data["reason"] = "channel_occupied"
    station.Reply.model_validate(data)


def test_the_snapshot_has_the_phone_numbers_and_trains_on_the_sections() -> None:
    snapshot = station.Reply.model_validate(example("station-1.reply.json")).snapshot
    assert snapshot.place.phone == "101"
    assert [n.code for n in snapshot.neighbours] == ["Ån"]
    assert "on_the_way" in station.Snapshot.model_fields
    assert "have_left" in station.Snapshot.model_fields


def test_a_train_number_for_lookup_is_one_to_five_digits() -> None:
    station.TrainLookup.model_validate({"train_number": "12345"})
    with pytest.raises(ValidationError):
        station.TrainLookup.model_validate({"train_number": "123456"})


# --- Terminal protocol ------------------------------------------------------------------


def test_the_values_are_the_old_servers() -> None:
    """The table "Värden" in the old Server's terminal16 README, which the firmware follows."""
    assert terminal.TOPIC_PREFIX == "tmbox/terminal/device/"
    assert (terminal.MAX_SESSIONS, terminal.SESSION_IDLE_SECONDS) == (256, 45)
    assert (terminal.MAX_PAYLOAD_BYTES, terminal.INPUT_GUARD_MS) == (4096, 500)
    assert (terminal.NOTICE_SECONDS, terminal.ENTRY_MAX_LENGTH) == (3, 5)
    assert terminal.ATTENTION_WINDOW_SECONDS == 2
    assert (terminal.DEVICE_ONLINE_SECONDS, terminal.DEVICE_OFFLINE_SECONDS) == (20, 900)


def test_the_example_frame_has_full_lines_and_matching_cells() -> None:
    frame = terminal.FrameMessage.model_validate(example("terminal16.frame-message.json")).frame
    assert len(frame.lines) == frame.rows
    assert all(len(line) == frame.cols for line in frame.lines)
    assert frame.lcd.cells == [[ord(c) for c in line] for line in frame.lines]


def test_a_box_without_a_display_size_counts_as_16x2() -> None:
    hello = example("terminal16.hello.json")
    del hello["display"]
    assert terminal.Hello.model_validate(hello).display is None
    assert terminal.DisplaySize() == terminal.DisplaySize(rows=2, cols=16)


def test_a_key_press_is_one_key() -> None:
    terminal.KeyPress.model_validate({"command_id": "b-1", "view_token": "v", "key": "#"})
    with pytest.raises(ValidationError):
        terminal.KeyPress.model_validate({"command_id": "b-1", "view_token": "v", "key": "E"})


# --- Drift's API --------------------------------------------------------------------------


def test_a_time_jump_needs_a_time_and_speed_needs_a_speed() -> None:
    with pytest.raises(ValidationError, match="Tiden"):
        drift.ClockControl.model_validate({"action": "jump"})
    with pytest.raises(ValidationError, match="Hastigheten"):
        drift.ClockControl.model_validate({"action": "speed"})
    drift.ClockControl.model_validate({"action": "jump", "time": "08:00"})


def test_the_drift_event_carries_the_epoch_and_the_command() -> None:
    event = drift.DriftEvent.model_validate(example("drift-1.event.json"))
    assert event.epoch == 0
    assert event.message_id == "tkl-nby-2026-0001"


# --- Reasons --------------------------------------------------------------------------------


def test_every_reason_has_a_text() -> None:
    assert set(TEXT_SV) == set(Reason)
    assert all(text.endswith(".") for text in TEXT_SV.values())


def test_the_reasons_named_in_the_spec_are_there() -> None:
    for code in ("channel_occupied", "track_occupied", "ambiguous_train_number", "stale_revision"):
        assert Reason(code)


def test_the_contracts_document_their_routes() -> None:
    for module in (station, terminal, drift):
        assert module.__doc__ is not None
        assert re.search(r"(GET|POST) +/api/", module.__doc__)
