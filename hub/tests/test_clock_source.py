"""Träffens klocka (F12, IMPORT-35, issue 93): FastClock as the meet's clock, in the hub.

A pretend FastClock answers, with a clock the test moves; no real clock is ever called. The
hub reads FastClock once a second in a thread of its own; here each round is taken by hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts import drift, hub
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.tests.test_drift_api import API, PIN, nu
from integrationer.fastclock import ExternalClock, FastClockError, Settings
from integrationer.tests.test_fastclock import provider_status

SOURCE = "/api/hub/clock-source"
TEST = {"source": "fastclock", "clock_name": "Träffen"}


class Pretend:
    def __init__(self) -> None:
        self.now = 100.0
        self.reply: object = provider_status(time="09:15:00", speed=5, weekday="Saturday")
        self.calls: list[tuple[str, str]] = []

    def transport(self, settings: Settings, action: str, reason: str) -> object:
        self.calls.append((action, settings.password))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply if action == "time" else None


class Hub:
    def __init__(self, tmp_path: Path) -> None:
        self.fc = Pretend()
        clock = ExternalClock(self.fc.transport, lambda: self.fc.now)
        app = create_app(
            BuildInfo(version="0.1.0"), preview_db=tmp_path / "prov.db", external_clock=clock
        )
        self.client = TestClient(app)
        setup = self.client.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN})
        assert setup.status_code == 201
        assert self.client.post(API + "/start", json={"version": 1}).status_code == 201

    def round(self, seconds: float = 2.0) -> drift.Now:
        self.fc.now += seconds
        self.client.app.state.clock.round()  # type: ignore[attr-defined]
        return nu(self.client)

    def save(self, **given: Any) -> Any:
        return self.client.post(SOURCE, json=given)


@pytest.fixture
def h(tmp_path: Path) -> Hub:
    return Hub(tmp_path)


def test_drift_follows_fastclock_and_nu_says_so(h: Hub) -> None:
    before = hub.ClockSourceSettings.model_validate(h.client.get(SOURCE).json())
    assert (before.source, before.meet, before.has_password) == ("drift", "provbanan", False)
    assert nu(h.client).external_clock is None
    saved = h.save(**TEST)
    assert saved.status_code == 200, saved.text
    assert h.fc.calls[0][0] == "time", "read before it is saved"
    seen = h.round(0)
    assert seen.external_clock is not None
    assert (seen.external_clock.name, seen.external_clock.available) == ("Träffen", True)
    assert (seen.clock.time, seen.clock.running, seen.clock.speed) == ("09:15", True, 5)
    assert seen.external_clock.weekday == "sat" and seen.traffic_day == "mon", "shown, not used"
    # FastClock pauses: Drift's clock stands with it, and the reason is shown.
    h.fc.reply = provider_status(time="09:20", speed=5, isPaused=True, pauseReason="Lunch")
    seen = h.round()
    assert (seen.clock.time, seen.clock.running) == ("09:20", False)
    assert seen.external_clock is not None and seen.external_clock.reason == "Lunch"


def test_without_an_answer_the_last_time_stands_with_a_warning(h: Hub) -> None:
    h.save(**TEST)
    h.round(0)
    h.fc.reply = FastClockError("FastClock kunde inte läsas.")
    seen = h.round(2)
    assert seen.external_clock is not None and not seen.external_clock.available
    assert seen.external_clock.warning == "FastClock kunde inte läsas."
    assert not seen.clock.running and seen.clock.time == "09:15", "no other clock takes over"
    h.fc.reply = provider_status(time="09:30:00", speed=5)
    seen = h.round(2)
    assert (seen.clock.time, seen.clock.running) == ("09:30", True)


def test_only_fastclock_that_answers_is_saved_and_only_by_the_dispatcher(h: Hub) -> None:
    anonymous = TestClient(h.client.app)
    assert anonymous.get(SOURCE).status_code == 401
    assert anonymous.post(SOURCE, json=TEST).status_code == 401
    bad = h.save(**TEST, url="https://10.0.0.1")
    assert (bad.status_code, bad.json()["detail"]) == (
        422,
        "FastClock-adressen får inte peka på ett lokalt eller privat nät.",
    )
    h.fc.reply = FastClockError("FastClock kunde inte läsas.")
    assert h.save(**TEST).status_code == 422
    assert h.client.get(SOURCE).json()["source"] == "drift", "nothing saved"


def test_start_and_stop_go_to_fastclock_and_the_time_is_set_there(h: Hub) -> None:
    h.save(**TEST)
    h.round(0)
    refused = h.client.post(API + "/clock", json={"action": "stop"})
    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("Ange en användare i FastClock")
    jump = h.client.post(API + "/clock", json={"action": "jump", "time": "10:00"})
    assert jump.status_code == 409
    h.save(**TEST, user="Trafikledare", password="hemligt")
    shown = h.client.get(SOURCE)
    assert shown.json()["has_password"] is True and "hemligt" not in shown.text
    h.fc.reply = provider_status(time="09:16:00", speed=5, isRunning=False)
    stopped = h.client.post(API + "/clock", json={"action": "stop"})
    assert stopped.status_code == 200, stopped.text
    assert [a for a, _ in h.fc.calls][-2:] == ["stop", "time"]
    assert h.fc.calls[-2][1] == "hemligt", "sent to FastClock only"
    assert not nu(h.client).clock.running
    # Another clock's name: the password does not follow.
    h.save(**{**TEST, "clock_name": "Annan"}, user="Trafikledare")
    assert h.client.get(SOURCE).json()["has_password"] is False


def test_back_to_drifts_clock_keeps_the_time_and_stops(h: Hub) -> None:
    h.save(**TEST)
    assert h.round(0).clock.running
    back = h.save(source="drift")
    assert back.status_code == 200, back.text
    seen = nu(h.client)
    assert (seen.clock.time, seen.clock.running, seen.external_clock) == ("09:15", False, None)
    started = h.client.post(API + "/clock", json={"action": "start"})
    assert drift.DriftEvent.model_validate(started.json()).kind == drift.EventKind.CLOCK_STARTED
