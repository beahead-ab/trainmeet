"""trainmeet.drift/1: Drift's API, for the dispatcher (Nu, Klienter, Logg) and the screens.

First version (Claude, draft). Transport is HTTP with JSON and an event stream (SSE), behind
the dispatcher's login (a local PIN until TrainMeet ID, step 6):

    POST /api/drift/1/start              StartMeet            version and game day
    POST /api/drift/1/clock              ClockControl         start, stop, speed, jump, undo
    GET  /api/drift/1/clients            the list in Klienter, Väntar first
    POST /api/drift/1/clients/approve    Approve              TKL and the app (H31)
    POST /api/drift/1/clients/revoke     Revoke
    POST /api/drift/1/clients/assign     Assign               TMBoxes: place and side
    GET  /api/drift/1/log?place=&train=  DriftEvent list       the event log, filtered (F27)
    GET  /api/drift/1/events             DriftEvent stream    live, for Nu and Logg

Still to come, each in the step that builds it: operating changes (step 3), version switch and
takeover (steps 4–5), screen data for Klocka, Banöversikt and Tågdiagram (step 3 and later).

Every drift event is kept in order with the leader's epoch. The events are what a restart
reads back and what the Pi sends to the cloud; there is no separate audit log.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final, Literal

from pydantic import Field, model_validator

from contracts.common import Contract, Id, Text, TimeOfDay, Weekday

PROTOCOL: Final = "trainmeet.drift/1"


class StartMeet(Contract):
    version: int = Field(ge=1, description="Versionen av träffpaketet som körs.")
    game_day: int = Field(default=1, ge=1, description="Speldygnet, Dag 1…N.")
    traffic_day: Weekday | None = Field(
        default=None, description="Trafikdagen; tomt betyder paketets förval (F8)."
    )


class ClockAction(StrEnum):
    START = "start"
    STOP = "stop"
    SPEED = "speed"
    JUMP = "jump"  # tidshopp: closes open cases, sets trains by the timetable (H37)
    UNDO_JUMP = "undo_jump"


class ClockControl(Contract):
    action: ClockAction
    speed: float | None = Field(default=None, gt=0, le=60)
    time: TimeOfDay | None = None
    game_day: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check(self) -> ClockControl:
        if self.action == ClockAction.SPEED and self.speed is None:
            raise ValueError("Hastigheten saknas.")
        if self.action == ClockAction.JUMP and self.time is None:
            raise ValueError("Tiden att hoppa till saknas.")
        return self


class Approve(Contract):
    client_id: Id
    places: list[Id] = Field(min_length=1)


class Revoke(Contract):
    client_id: Id


class Assign(Contract):
    """A TMBox gets a place and a side, as before. One box may run several places (H44)."""

    client_id: Id
    places: list[Id] = Field(min_length=1)
    side: Literal["both", "left", "right"] = "both"


class EventKind(StrEnum):
    MEET_STARTED = "meet.started"
    CLOCK_STARTED = "clock.started"
    CLOCK_STOPPED = "clock.stopped"
    CLOCK_SPEED = "clock.speed"
    TIME_JUMP = "clock.jump"
    TIME_JUMP_UNDONE = "clock.jump_undone"
    DAY_CHANGED = "day.changed"
    CLIENT_APPROVED = "client.approved"
    CLIENT_REVOKED = "client.revoked"
    CLIENT_ASSIGNED = "client.assigned"
    CLEARANCE_REQUESTED = "clearance.requested"
    CLEARANCE_ANSWERED = "clearance.answered"
    CLEARANCE_CANCELLED = "clearance.cancelled"
    CLEARANCE_REMINDED = "clearance.reminded"
    TRAIN_DEPARTED = "train.departed"
    TRAIN_ARRIVED = "train.arrived"
    TRAIN_MOVED_HERE = "train.moved_here"  # FLYTTA HIT: a train nobody sent
    TRAIN_TRACK_CHANGED = "train.track_changed"
    TRAIN_SET_ASIDE = "train.set_aside"  # undanställning (H41)
    LINE_AVAILABLE = "line.available"
    SECTION_OCCUPANCY = "section.occupancy"
    EXIT_SIGNAL = "signal.exit"


class ActorKind(StrEnum):
    CLIENT = "client"
    DISPATCHER = "dispatcher"
    AUTOMATION = "automation"
    SYSTEM = "system"


class Actor(Contract):
    kind: ActorKind
    id: Id | None = None


class DriftEvent(Contract):
    protocol: Literal["trainmeet.drift/1"] = PROTOCOL
    seq: int = Field(ge=1, description="Händelsens nummer i den körande träffen.")
    epoch: int = Field(ge=0, description="Ledarens epok; högre epok vinner.")
    meet_id: Id
    version: int = Field(ge=1)
    game_day: int = Field(ge=1)
    model_time: TimeOfDay
    wall_time: datetime
    kind: EventKind
    actor: Actor
    message_id: Text | None = Field(default=None, description="Kommandots id, för spårbarhet.")
    place: Id | None = None
    train: Id | None = None
    call: Id | None = None
    data: dict[str, object] = Field(default_factory=dict)
