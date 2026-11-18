"""FastClock as the meet's clock (F12, IMPORT-35): Drift's clock follows the external one.

The hub reads FastClock (integrationer/fastclock.py) and hands Drift the time; here Drift is
given it directly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from contracts import drift as events
from drift.engine import Drift
from drift.tests.test_jump import package

START = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


@pytest.fixture
def drift() -> Drift:
    engine = Drift(package(), [], now=START)
    engine.start(START)
    return engine


def by_fastclock(drift: Drift) -> list[events.DriftEvent]:
    return [e for e in drift.history if e.actor and e.actor.id == "fastclock"]


def test_drift_follows_fastclock_and_writes_only_what_changes(drift: Drift) -> None:
    assert drift.follow_clock(9 * 3600 + 15 * 60, 5, True, at(0))
    assert (drift.clock.at(at(0)), drift.clock.running, drift.clock.speed) == (33300, True, 5)
    # FastClock and Drift agree within a few model seconds: nothing is written.
    assert not drift.follow_clock(33300 + 5 * 2 + 3, 5, True, at(2))
    # A new speed, then a pause in FastClock.
    assert drift.follow_clock(33310, 4, True, at(2))
    assert drift.clock.speed == 4
    assert drift.follow_clock(33318, 4, False, at(4))
    assert (drift.clock.running, drift.clock.at(at(60))) == (False, 33318)
    kinds = [e.kind for e in by_fastclock(drift)]
    assert kinds == [
        events.EventKind.CLOCK_STARTED,
        events.EventKind.CLOCK_SPEED,
        events.EventKind.CLOCK_STOPPED,
    ]
    assert all(e.actor and e.actor.kind == events.ActorKind.SYSTEM for e in by_fastclock(drift))


def test_without_an_answer_the_clock_stands_where_it_is(drift: Drift) -> None:
    """No other clock takes over: the time shown stands, and FastClock's next answer goes on."""
    drift.follow_clock(36000, 5, True, at(0))
    assert drift.follow_clock(None, 1, False, at(4))
    assert (drift.clock.running, drift.clock.at(at(100))) == (False, 36020)
    assert not drift.follow_clock(None, 1, False, at(8)), "already standing"
    drift.follow_clock(36100, 5, True, at(20))
    assert drift.clock.running and drift.clock.at(at(20)) == 36100


def test_the_game_day_goes_on_over_midnight(drift: Drift) -> None:
    """FastClock's time is laid on the game day nearest Drift's, so the clock passes midnight
    instead of going back 24 hours."""
    drift.follow_clock(23 * 3600 + 59 * 60 + 50, 5, True, at(0))
    drift.follow_clock(30, 5, True, at(10))
    assert drift.clock.at(at(10)) == pytest.approx(86400 + 30, abs=5)
    # Set to 06:00 in FastClock, the clock goes there on the same game day.
    drift.follow_clock(6 * 3600, 5, True, at(12))
    assert drift.clock.at(at(12)) == 86400 + 6 * 3600
    # And back to 23:00 it goes back to the evening before, not on to the next.
    drift.follow_clock(23 * 3600, 5, True, at(14))
    assert drift.clock.at(at(14)) == 23 * 3600
