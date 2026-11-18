"""FastClock (F12, IMPORT-35), ported with the old Server's test_external_clock.py as facit.

A pretend FastClock answers; no real clock is ever called.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from integrationer.fastclock import (
    ExternalClock,
    FastClockError,
    Settings,
    changed,
    parse,
    provider_request,
)


def provider_status(**changes: Any) -> dict[str, Any]:
    return {
        "name": "Test",
        "time": "06:12:34",
        "speed": 4,
        "isRunning": True,
        "isPaused": False,
        "isUnavailable": False,
        "weekday": "Saturday",
        **changes,
    }


class Pretend:
    def __init__(self) -> None:
        self.now = 100.0
        self.reply: object = provider_status()
        self.calls: list[tuple[Settings, str, str]] = []
        self.clock = ExternalClock(self.transport, lambda: self.now)
        self.settings = Settings(source="fastclock", clock_name="Test")
        self.clock.configure("en", self.settings)

    def transport(self, settings: Settings, action: str = "time", reason: str = "") -> object:
        self.calls.append((settings, action, reason))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    def status(self) -> Any:
        found = self.clock.status()
        assert found is not None
        return found


@pytest.fixture
def fc() -> Pretend:
    return Pretend()


def test_read_interpolation_pause_and_resume(fc: Pretend) -> None:
    assert fc.clock.poll()
    fc.now += 1
    assert fc.status().time == "06:12:38"
    assert not fc.clock.poll(), "once per interval"
    assert len(fc.calls) == 1
    fc.reply = provider_status(time="09:00", isPaused=True, pauseReason="Lunch")
    fc.now += 2
    fc.clock.poll()
    fc.now += 1
    assert fc.status().time == "09:00:00"
    assert not fc.status().running
    assert fc.status().stopped_reason == "Lunch"


@pytest.mark.parametrize(
    ("payload", "text"),
    [
        (provider_status(message="Trafiken börjar strax"), "Trafiken börjar strax"),
        (provider_status(isPaused=True, pauseReason="Lunch"), None),
        (provider_status(message="Ändrat meddelande"), "Ändrat meddelande"),
        (provider_status(message="   "), None),
        (provider_status(), None),
    ],
)
def test_live_messages_follow_the_clock_through_a_pause(
    fc: Pretend, payload: dict[str, Any], text: str | None
) -> None:
    fc.reply = payload
    fc.clock.poll(force=True)
    status = fc.status()
    assert status.message == text
    assert status.running == (not payload.get("isPaused", False))
    assert status.stopped_reason == (None if status.running else "Lunch")


def test_message_and_pause_reason_are_separate() -> None:
    status = parse(provider_status(isPaused=True, pauseReason="Lunch", message="Vi börjar 13:00"))
    assert (status.message, status.stopped_reason) == ("Vi börjar 13:00", "Lunch")
    long = parse(provider_status(message="a" * 500)).message
    assert long is not None and len(long) == 160


@pytest.mark.parametrize(
    "placeholder", ["NoReason", "SelectStopReason", "None", "  ", "N/A", "no_reason"]
)
def test_reasons_never_become_a_message_and_placeholders_say_nothing(placeholder: str) -> None:
    running = parse(provider_status(pauseReason="None", stoppingReason="NoReason", message=""))
    assert (running.message, running.stopped_reason) == (None, None)
    assert parse(provider_status(stoppingReason="Derailment")).message is None
    stopped = parse(
        provider_status(isRunning=False, stoppingReason=placeholder, message=placeholder)
    )
    assert (stopped.running, stopped.stopped_reason, stopped.message) == (False, "", None)


def test_each_reason_belongs_to_its_own_state() -> None:
    paused = parse(provider_status(isPaused=True, pauseReason="Coffe", stoppingReason="Derailment"))
    assert paused.stopped_reason == "Coffe"
    stopped = parse(
        provider_status(isRunning=False, pauseReason="Lunch", stoppingReason="Derailment")
    )
    assert stopped.stopped_reason == "Derailment"
    done = parse(provider_status(isCompleted=True, stoppingReason="Derailment"))
    assert (done.running, done.completed, done.stopped_reason) == (False, True, "")
    assert not parse(provider_status()).completed


def test_completed_reaches_the_status(fc: Pretend) -> None:
    fc.reply = provider_status(isCompleted=True)
    fc.clock.poll(force=True)
    assert fc.status().completed
    fc.reply = provider_status()
    fc.clock.poll(force=True)
    assert not fc.status().completed


def test_a_new_message_does_not_reset_the_interpolation(fc: Pretend) -> None:
    fc.reply = provider_status(time="09:15", message="Första meddelandet")
    fc.clock.poll(force=True)
    fc.now += 3
    before = fc.status().seconds
    fc.reply = provider_status(time="09:15", message="Nytt meddelande")
    fc.clock.poll(force=True)
    assert fc.status().message == "Nytt meddelande"
    assert fc.status().seconds == before
    fc.now += 1
    assert fc.status().seconds == before + 4


def test_an_outage_keeps_the_last_time_and_never_falls_back(fc: Pretend) -> None:
    fc.clock.poll()
    fc.now += 7
    assert not fc.status().available
    assert fc.status().time == "06:12:34", "the last time received stands"
    assert fc.status().stopped_reason == "Väntar på FastClock. Senast mottagna tid visas."
    fc.reply = FastClockError("Borta")
    fc.clock.poll()
    assert not fc.status().running
    assert fc.status().stopped_reason == "Borta"
    fc.reply = provider_status(time="23:59:59")
    fc.clock.poll(force=True)
    fc.now += 1
    assert fc.status().time == "00:00:03", "over midnight"


def test_a_clock_with_only_minutes_does_not_rewind_at_every_answer(fc: Pretend) -> None:
    fc.reply = provider_status(time="09:15", speed=5, weekday="Monday")
    assert fc.clock.poll()
    assert (fc.status().weekday, fc.status().precision) == ("mon", "minute")
    previous = 9 * 3600 + 15 * 60
    for _ in range(5):
        fc.now += 2
        assert fc.clock.poll()
        current = fc.status().seconds
        assert current > previous, "equal HH:MM answers never rewind"
        previous = current
    fc.reply = provider_status(time="09:16", speed=5, weekday="Monday")
    fc.now += 2
    assert fc.clock.poll()
    assert fc.status().seconds > previous
    assert 9 * 3600 + 16 * 60 <= fc.status().seconds < 9 * 3600 + 16 * 60 + 11
    fc.now += 2
    previous = fc.status().seconds
    assert fc.clock.poll()
    assert fc.status().seconds == previous, "an answer at the same instant does not reset"
    fc.now += 2
    assert fc.status().seconds > previous


def test_seconds_are_followed_exactly(fc: Pretend) -> None:
    fc.reply = provider_status(time="09:15:25", speed=5)
    fc.clock.poll()
    assert (fc.status().time, fc.status().precision) == ("09:15:25", "second")
    fc.now += 2
    fc.reply = provider_status(time="09:15:35", speed=5)
    fc.clock.poll()
    assert fc.status().time == "09:15:35"


def test_hh_mm_00_at_every_answer_is_learnt_as_minutes(fc: Pretend) -> None:
    fc.reply = provider_status(time="09:15:00", speed=5)
    fc.clock.poll()
    fc.now += 2
    fc.clock.poll()
    assert (fc.status().precision, fc.status().time) == ("minute", "09:15:10")
    fc.now += 2
    fc.clock.poll()
    assert fc.status().time == "09:15:20"
    fc.reply = provider_status(time="09:16:00", speed=5)
    fc.now += 8
    before = fc.status().seconds
    fc.clock.poll()
    assert fc.status().seconds >= before
    assert fc.status().speed == 5


def test_a_clock_with_seconds_stays_exact_at_a_whole_minute(fc: Pretend) -> None:
    for at in ("09:14:55", "09:15:00", "09:15:05"):
        fc.reply = provider_status(time=at, speed=5)
        fc.clock.poll(force=True)
        fc.now += 1
        assert fc.status().precision == "second"


def test_no_answer_yet_is_waiting(fc: Pretend) -> None:
    assert (fc.status().time, fc.status().running) == ("--:--:--", False)
    fc.clock.configure("en", Settings())
    assert fc.clock.status() is None, "Drift's own clock"


def test_a_late_answer_is_thrown_away_after_the_meet_changes(fc: Pretend) -> None:
    entered, release = threading.Event(), threading.Event()

    def slow(*_: object) -> object:
        entered.set()
        release.wait(2)
        return provider_status()

    fc.clock.transport = slow
    worker = threading.Thread(target=fc.clock.poll)
    worker.start()
    assert entered.wait(1)
    fc.clock.configure("en annan", fc.settings)
    release.set()
    worker.join(2)
    assert fc.status().last_sync is None


def test_without_a_user_it_only_follows_and_commands_are_never_assumed(fc: Pretend) -> None:
    with pytest.raises(FastClockError):
        fc.clock.control("start")
    assert fc.calls == []
    fc.clock.configure("en", replace(fc.settings, user="Trafikledare"))
    fc.reply = provider_status(isRunning=False)
    fc.clock.control("start")
    assert [call[1] for call in fc.calls] == ["start", "time"]
    assert not fc.status().running, "only what FastClock confirms is shown"
    with pytest.raises(FastClockError):
        fc.clock.control("set")


def test_a_failed_start_is_not_retried_or_shown_as_done(fc: Pretend) -> None:
    fc.clock.configure("en", replace(fc.settings, user="Trafikledare"))
    fc.reply = FastClockError("Inget svar")
    with pytest.raises(FastClockError):
        fc.clock.control("start")
    assert [call[1] for call in fc.calls] == ["start"]
    assert not fc.status().available


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        provider_status(time="24:01"),
        provider_status(speed=float("nan")),
        provider_status(speed=True),
        provider_status(isRunning="true"),
        provider_status(isUnavailable=True),
        provider_status(isPaused="false"),
    ],
)
def test_the_answer_is_checked_strictly(data: object) -> None:
    with pytest.raises(FastClockError):
        parse(data)


def test_a_password_never_follows_to_another_clock() -> None:
    old = Settings(source="fastclock", clock_name="Test", user="En", password="hemligt")
    assert changed({"source": "fastclock"}, old).password == "hemligt"
    assert changed({"source": "fastclock", "clock_name": "Annan"}, old).password == ""
    for changes in (
        {"clock_name": ""},
        {"poll_interval": 1},
        {"poll_interval": True},
        {"password": "fel\nvärde"},
    ):
        with pytest.raises(FastClockError):
            changed({"source": "fastclock", **changes}, old)


def _opener(answer: dict[str, Any]) -> Any:
    response = MagicMock()
    response.read.return_value = json.dumps(answer).encode()
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = response
    return opener


def test_the_address_is_encoded_and_errors_never_tell_the_answer() -> None:
    settings = Settings(source="fastclock", clock_name="Klubb / A")
    opener = _opener(provider_status())
    with patch.object(urllib.request, "build_opener", return_value=opener):
        provider_request(settings)
        request = opener.open.call_args.args[0]
        assert request.full_url == (
            "https://fastclock.azurewebsites.net/api/clocks/Klubb%20%2F%20A/time"
        )
        assert request.method == "GET"
        assert opener.open.call_args.kwargs["timeout"] == 4
        provider_request(replace(settings, user="A B", password="hemligt"), "stop", "Lunch")
        request = opener.open.call_args.args[0]
        assert request.method == "PUT" and "reason=Lunch" in request.full_url
        opener.open.side_effect = RuntimeError("privat adress ?password=hemligt")
        with pytest.raises(FastClockError) as error:
            provider_request(settings)
        assert "hemligt" not in str(error.value)


@pytest.mark.parametrize(
    "bad",
    [
        "http://clock.example.org",
        "https://localhost",
        "https://127.0.0.1",
        "https://10.0.0.1",
        "https://clock.local",
        "https://user:pass@clock.example.org",
        "https://clock.example.org/path",
        "https://clock.example.org?token=privat",
        "https://clock.example.org#fragment",
        "https://clock.example.org:bad",
    ],
)
def test_only_a_public_https_address(bad: str) -> None:
    previous = Settings(source="fastclock", clock_name="Test", user="Styr", password="hemligt")
    with pytest.raises(FastClockError):
        changed({"source": "fastclock", "url": bad}, previous)


def test_another_address_drops_the_password_and_is_used() -> None:
    previous = Settings(source="fastclock", clock_name="Test", user="Styr", password="hemligt")
    settings = changed({"source": "fastclock", "url": "https://clock.example.org/"}, previous)
    assert (settings.url, settings.password) == ("https://clock.example.org", "")
    opener = _opener(provider_status())
    with patch.object(urllib.request, "build_opener", return_value=opener):
        provider_request(replace(settings, clock_name="A/B"))
    assert opener.open.call_args.args[0].full_url == (
        "https://clock.example.org/api/clocks/A%2FB/time"
    )
