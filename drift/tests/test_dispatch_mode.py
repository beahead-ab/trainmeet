"""The clearance mode, the meet context and train numbers that mean two trains, ported from the
old Server's test_dispatch_mode.py and the rest of test_shared_traffic.py.

The old Server had one mode for the whole game. The new package has the meet's mode and an
exception per section (4.2, decided), so the old test "a section has no mode of its own" turns
into its opposite: the section's own mode wins, both ways.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from contracts import station
from contracts.meet import MeetPackage
from contracts.reasons import Reason
from drift.engine import Drift, Refused
from drift.terminal import Box, Boxes

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def raw() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        files("contracts").joinpath("examples/provbanan.meet.json").read_text()
    )
    return data


def started(data: dict[str, Any]) -> Drift:
    drift = Drift(MeetPackage.model_validate(data), [], now=NOW)
    drift.start(NOW)
    return drift


def ask(drift: Drift, place: str, call: str, section: str, **context: Any) -> str:
    clearance = "clr-" + uuid4().hex[:10]
    drift.command(
        station.Command(
            message_id=uuid4().hex,
            client_id="tkl",
            place=place,
            context=drift.context.model_copy(update=context),
            action=station.Action.CLEARANCE_REQUEST,
            payload={"call": call, "section": section, "clearance_id": clearance},
        ),
        NOW,
    )
    return clearance


def test_a_direct_meet_grants_every_request_at_once() -> None:
    data = raw()
    data["meet"]["clearance_mode"] = "direct"
    drift = started(data)
    clearance = ask(drift, "nby", "t101-nby", "s-nby-asn")
    assert drift.cases[clearance].status == station.ClearanceStatus.APPROVED


def test_a_requested_meet_waits_for_the_neighbour() -> None:
    drift = started(raw())
    clearance = ask(drift, "nby", "t101-nby", "s-nby-asn")
    assert drift.cases[clearance].status == station.ClearanceStatus.WAITING


def test_a_sections_own_mode_wins_both_ways() -> None:
    data = raw()
    data["meet"]["clearance_mode"] = "direct"
    section = next(s for s in data["sections"] if s["id"] == "s-asn-mla")
    section["clearance_mode"] = "requested"
    drift = started(data)
    waits = ask(drift, "asn", "t101-asn", "s-asn-mla")
    assert drift.cases[waits].status == station.ClearanceStatus.WAITING
    granted = ask(drift, "sjv", "t102-sjv", "s-mla-sjv")  # Direct in a requested meet too.
    assert drift.cases[granted].status == station.ClearanceStatus.APPROVED


def test_an_unknown_mode_is_refused_when_the_package_is_read() -> None:
    data = raw()
    data["meet"]["clearance_mode"] = "automatic"
    with pytest.raises(ValidationError):
        MeetPackage.model_validate(data)


def test_a_command_for_another_day_or_meet_is_stale() -> None:
    """An old choice never survives a change of meet or day (the old 'other day cannot
    answer an old case')."""
    drift = started(raw())
    for context in ({"game_day": 2}, {"meet_id": "another-meet"}, {"version": 2}):
        with pytest.raises(Refused) as refused:
            ask(drift, "nby", "t101-nby", "s-nby-asn", **context)
        assert refused.value.reason == Reason.STALE_MEET_CONTEXT
    assert drift.cases == {}


@pytest.fixture
def twice() -> Drift:
    """Two trains numbered 101 leave Norrby the same day."""
    data = raw()
    copy = next(t for t in data["trains"] if t["number"] == "103")
    other = json.loads(json.dumps(copy).replace("t103-", "u101-"))
    other.update(id="train-101-second", number="101")
    data["trains"].append(other)
    return started(data)


def test_a_number_that_means_two_trains_is_never_guessed_by_the_box(twice: Drift) -> None:
    box = Box(client_id="box-nby", name="Box Norrby")
    view = Boxes(twice, {box.client_id: box}, epoch="e1", now=NOW)
    view.assign(box, "nby")
    frame = view.frame(box)
    answer = view.press(
        box,
        {
            "command_id": "c-1",
            "view_token": frame["view_token"],
            "key": "#",
            "train_number": "101",
            "entry_context": frame["entry"]["context"],
        },
    )
    assert answer["frame"]["lines"][0].strip() == "FLERA TÅG ADMIN"
    assert twice.cases == {}


def test_the_lookup_answers_both_and_the_client_picks_the_call(twice: Drift) -> None:
    matches = twice.lookup("nby", "101")
    assert sorted(m.call for m in matches) == ["t101-nby", "u101-nby"]
    clearance = ask(twice, "nby", "u101-nby", "s-nby-asn")
    assert twice.cases[clearance].leg.train.id == "train-101-second"
