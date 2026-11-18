"""What Drift keeps of the drivers (LOK-07): who has which service, the alarms for trains left
without a driver on the line, the check-ins, the messages, Framme, the game's settings and when
a train or call last changed during the game.

Everything here is added up from the Drift events, like the rest of Drift's state, so a restart
reads the same back. The drivers themselves (name, level, key) are kept beside the events, in
the store: the events carry only the driver's id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from contracts import drift as events
from contracts.station import DriverMessageKind

DRIVER_EVENTS: Final = frozenset(
    {
        events.EventKind.SERVICE_CLAIMED,
        events.EventKind.SERVICE_RELEASED,
        events.EventKind.SERVICE_ALARM_CLEARED,
        events.EventKind.DRIVER_CHECKED_IN,
        events.EventKind.DRIVER_MESSAGE,
        events.EventKind.DRIVER_ARRIVED,
        events.EventKind.DRIVER_SETTINGS,
    }
)
# The messages kept for Nu, the log of Förare and the stations: the latest ones.
MESSAGES_KEPT: Final = 200


def key_of(service: events.ServiceRef) -> str:
    return f"{service.kind.value}:{service.id}"


@dataclass(frozen=True)
class Moment:
    """When on the meet clock: the game day and the model seconds into it, the clock time and
    the real time."""

    game_day: int
    seconds: float
    model_time: str
    wall_time: datetime


@dataclass(frozen=True)
class Holding:
    driver: str
    service: events.ServiceRef
    by: str
    seq: int


@dataclass(frozen=True)
class Alarm:
    """A service released on the line: the train stands without a driver (LOK-35)."""

    service: events.ServiceRef
    driver: str
    section: str | None
    from_place: str | None
    to_place: str | None
    train: str | None
    seq: int
    at: Moment


@dataclass(frozen=True)
class Checkin:
    driver: str
    place: str
    track: str | None
    train: str | None
    service: events.ServiceRef | None
    seq: int
    at: Moment


@dataclass(frozen=True)
class Message:
    driver: str
    kind: DriverMessageKind
    service: events.ServiceRef | None
    train: str | None
    seq: int
    at: Moment


@dataclass
class DriverBook:
    settings: events.DriverSettings = field(default_factory=events.DriverSettings)
    # Service key -> who has it, and driver -> the key of their service (LOK-40).
    holders: dict[str, Holding] = field(default_factory=dict)
    by_driver: dict[str, str] = field(default_factory=dict)
    alarms: dict[str, Alarm] = field(default_factory=dict)
    # Released on the line and not taken again: first in the list (LOK-40).
    on_line: set[str] = field(default_factory=set)
    # Ended with Framme at its last call.
    done: set[str] = field(default_factory=set)
    # Framme said at these calls, per service.
    framme: dict[str, set[str]] = field(default_factory=dict)
    checkins: dict[str, Checkin] = field(default_factory=dict)
    messages: list[Message] = field(default_factory=list)
    # A train (driftändring) or a call (spårbyte) changed during the game: when (LOK-24).
    changed: dict[str, Moment] = field(default_factory=dict)

    def mark(self, ref: str | None, at: Moment) -> None:
        if ref:
            self.changed[ref] = at

    def apply(self, event: events.DriftEvent, at: Moment) -> None:
        match event.kind:
            case events.EventKind.DRIVER_SETTINGS:
                self.settings = events.DriverSettings.model_validate(event.data)
            case events.EventKind.SERVICE_CLAIMED:
                claimed = events.ServiceClaimed.model_validate(event.data)
                key = key_of(claimed.service)
                self._free(key)
                self._drop(claimed.driver)
                self.holders[key] = Holding(claimed.driver, claimed.service, claimed.by, event.seq)
                self.by_driver[claimed.driver] = key
                self.alarms.pop(key, None)
                self.on_line.discard(key)
                self.done.discard(key)
            case events.EventKind.SERVICE_RELEASED:
                released = events.ServiceReleased.model_validate(event.data)
                key = key_of(released.service)
                self._free(key)
                if released.done:
                    self.done.add(key)
                if released.on_line:
                    self.on_line.add(key)
                    if released.by == "driver":
                        self.alarms[key] = Alarm(
                            released.service,
                            released.driver,
                            released.section,
                            released.from_place,
                            released.to_place,
                            event.train,
                            event.seq,
                            at,
                        )
            case events.EventKind.SERVICE_ALARM_CLEARED:
                cleared = events.AlarmCleared.model_validate(event.data)
                self.alarms.pop(key_of(cleared.service), None)
            case events.EventKind.DRIVER_CHECKED_IN:
                checked = events.DriverCheckedIn.model_validate(event.data)
                assert event.place is not None
                self.checkins[checked.driver] = Checkin(
                    checked.driver,
                    event.place,
                    checked.track,
                    event.train,
                    checked.service,
                    event.seq,
                    at,
                )
            case events.EventKind.DRIVER_MESSAGE:
                sent = events.DriverMessageSent.model_validate(event.data)
                self.messages.append(
                    Message(sent.driver, sent.kind, sent.service, event.train, event.seq, at)
                )
                del self.messages[:-MESSAGES_KEPT]
            case events.EventKind.DRIVER_ARRIVED:
                arrived = events.DriverArrived.model_validate(event.data)
                assert event.call is not None
                self.framme.setdefault(key_of(arrived.service), set()).add(event.call)

    def _free(self, key: str) -> None:
        """Nobody has the service any more."""
        held = self.holders.pop(key, None)
        if held is not None and self.by_driver.get(held.driver) == key:
            del self.by_driver[held.driver]

    def _drop(self, driver: str) -> None:
        """The driver has no service any more."""
        key = self.by_driver.pop(driver, None)
        if key is not None:
            self.holders.pop(key, None)

    def service_of(self, driver: str) -> Holding | None:
        key = self.by_driver.get(driver)
        return None if key is None else self.holders.get(key)
