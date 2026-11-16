"""USB-kopian (DRIFT-21): each accepted drift event is also on the USB stick, if one is in,
before Drift answers. Without a stick Drift goes on as before."""

from __future__ import annotations

import json
import logging
from importlib.resources import files
from pathlib import Path

import pytest

from contracts import drift as events
from contracts import station
from contracts.meet import MeetPackage
from drift.copy import FOLDER, EventCopy
from drift.engine import Refused
from drift.store import PreviewStore, epoch_of


def store_with(tmp_path: Path, usb: Path) -> PreviewStore:
    raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    return PreviewStore(
        tmp_path / "run.sqlite3",
        MeetPackage.model_validate_json(raw),
        automation=False,
        copy=EventCopy(usb, "provbanan-v1"),
    )


def copied(usb: Path, run: str) -> list[events.DriftEvent]:
    path = usb / FOLDER / f"provbanan-v1-{epoch_of(run)}.jsonl"
    if not path.exists():
        return []
    return [
        events.DriftEvent.model_validate(json.loads(line)) for line in path.read_text().splitlines()
    ]


def test_every_accepted_event_is_on_the_stick(tmp_path: Path) -> None:
    usb = tmp_path / "usb"
    usb.mkdir()
    store = store_with(tmp_path, usb)
    run = store.start()
    store.clock(run, events.ClockControl(action=events.ClockAction.START))
    store.command(
        run,
        station.Command(
            message_id="message-1",
            client_id="tkl-nby",
            place="nby",
            context=store.state(run).context,
            action=station.Action.CLEARANCE_REQUEST,
            payload={"call": "t101-nby", "section": "s-nby-asn", "clearance_id": "clr-1"},
        ),
    )
    assert copied(usb, run) == store.events_after(run, 0)
    assert len(copied(usb, run)) >= 3
    assert store.copy is not None and store.copy.state().writing
    # The run id itself is never in the file name: it is the browser's key in Provbanan.
    assert run not in " ".join(p.name for p in (usb / FOLDER).iterdir())


def test_a_refused_command_leaves_nothing_on_the_stick(tmp_path: Path) -> None:
    usb = tmp_path / "usb"
    usb.mkdir()
    store = store_with(tmp_path, usb)
    run = store.start()
    before = copied(usb, run)
    with pytest.raises(Refused):
        store.command(
            run,
            station.Command(
                message_id="message-2",
                client_id="tkl-asn",
                place="asn",
                context=store.state(run).context,
                action=station.Action.CLEARANCE_RESPONSE,
                payload={"clearance_id": "finns-inte", "approved": True},
            ),
        )
    assert copied(usb, run) == before == store.events_after(run, 0)


def test_without_a_stick_drift_goes_on_and_says_so_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    usb = tmp_path / "usb"  # not plugged in
    store = store_with(tmp_path, usb)
    caplog.set_level(logging.INFO)
    run = store.start()
    store.clock(run, events.ClockControl(action=events.ClockAction.START))
    store.clock(run, events.ClockControl(action=events.ClockAction.STOP))
    assert store.copy is not None
    state = store.copy.state()
    assert (state.writing, state.problem) == (False, "Inget USB-minne")
    assert caplog.text.count("kopieras inte") == 1
    # The stick is put in: the copy goes on from the next event.
    usb.mkdir()
    store.clock(run, events.ClockControl(action=events.ClockAction.START))
    on_stick = copied(usb, run)
    assert on_stick and on_stick == store.events_after(run, 0)[-len(on_stick) :]
    assert store.copy.state().writing and "kopieras till USB-minnet" in caplog.text
