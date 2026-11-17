"""TrainMeet TKL's own API: between TKL's server and its web app (apps/tkl), under /api/tkl/1/.

TKL is a program of its own (ST3, KLAR-22). Its server runs on the station's computer or a
Raspberry Pi and holds what TKL owns (KLAR-08): the station's outside and the PIN that locks
it. When TKL connects to a meet it also holds the key from the approval; the key stays in the
server and never reaches the browser or a log (H31). Towards the hub TKL speaks the station
protocol (contracts/station.py), nothing else.

Level 0 (TKL21, KLAR-15): the tracks and exits are written as a list, without a drawing. The
list is the station's outside; a new version of it is made with a button (TKL25).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final

from pydantic import Field

from contracts.common import Contract, Id, Text
from contracts.station import (
    Action,
    ApprovalStatus,
    MeetContext,
    MessageId,
    Revision,
    Snapshot,
)
from contracts.station_outside import StationOutside

# "Minst fyra siffror" (TKLAPP, first start). Never written to a log.
TKL_PIN = Field(pattern=r"^[0-9]{4,12}$", description="4–12 siffror. Skrivs aldrig ut.")
LEVEL_0: Final = 0


class TklMode(StrEnum):
    LOCAL = "local"  # on the station's computer or a Pi: one station
    CLOUD = "cloud"  # TKL i molnet: one station per browser until TrainMeet ID (TKL5)


class TklStation(Contract):
    station_id: Id = Field(description="Stationens id: kort namn, skapat vid första start.")
    name: Text
    level: int = Field(default=LEVEL_0, ge=0, le=3)


class TklState(Contract):
    """What the web app needs before anything else: is TKL set up, and is it unlocked."""

    mode: TklMode
    software: Text
    set_up: bool
    unlocked: bool
    station: TklStation | None = None


class TklSetUp(Contract):
    """Första start, tre rutor: stationen och PIN:en. TrainMeet ID comes later (#78)."""

    name: str = Field(min_length=1, max_length=40)
    station_id: Id
    pin: str = TKL_PIN


class TklUnlock(Contract):
    pin: str = TKL_PIN


class TklPinChange(Contract):
    old: str = TKL_PIN
    new: str = TKL_PIN


class OutsideVersion(Contract):
    number: int = Field(ge=1)
    saved: datetime


class TklStudio(Contract):
    """Studio at level 0: the list as it is on the computer, and the versions made of it."""

    draft: StationOutside
    versions: list[OutsideVersion] = Field(default_factory=list, description="Senaste först.")
    changed: bool = Field(description="Listan skiljer sig från den senaste versionen.")


class FoundHub(Contract):
    """A hub with a started meet (H36): found on the meet's network, or one TKL in the cloud
    may reach over the internet."""

    address: Text
    name: Text
    meet: Text | None = None
    nearby: bool = Field(description="På träffnätet. Annars behövs en kod (S2).")


class TklConnect(Contract):
    address: Text = Field(max_length=200)
    code: Text | None = Field(default=None, max_length=20)


class TklConnection(Contract):
    """How TKL stands with the hub. The key is never part of it."""

    connected: bool
    address: Text | None = None
    hub_name: Text | None = None
    status: ApprovalStatus | None = None
    places: list[Id] = Field(default_factory=list)
    outside_version: int | None = Field(default=None, description="Utsidan som följde med.")
    message: Text | None = None


class TklView(Contract):
    """The place's snapshot from the hub. When the hub cannot be reached, the last good one is
    kept and marked stale (old TKL: keep the last good data, say it is old)."""

    snapshot: Snapshot | None = None
    stale: bool = False
    heard: datetime | None = None
    message: Text | None = None


class TklCommand(Contract):
    """A station command from the web app. TKL's server adds its client id and key."""

    message_id: MessageId
    place: Id
    context: MeetContext
    action: Action
    expected_revision: Revision | None = None
    payload: dict[str, object] = Field(default_factory=dict)
