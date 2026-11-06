"""Träffens skärmar (TV, 1920 × 1080): a screen joins with the meet's code, waits under Väntar
and shows the view the dispatcher gives it in Klienter (S3, S4). Steg 3 has the clock; the
track overview, the train graph and the overview come later.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from contracts.common import Contract, Id, Text, Weekday
from contracts.station import Clock


class ScreenView(StrEnum):
    CLOCK = "clock"


class ScreenLogin(Contract):
    name: str = Field(min_length=1, max_length=40)
    code: Text = Field(description="Träffens kod. Skrivs aldrig ut i loggen.")


class ScreenSession(Contract):
    client_id: Id
    session_key: Text = Field(description="Skärmens nyckel. Skrivs aldrig ut i loggen.")


class ShowView(Contract):
    """The dispatcher gives a screen its view; none sends it back to Väntar."""

    client_id: Id
    view: ScreenView | None = None


class ScreenPicture(Contract):
    """What the screen shows now. Without a view it waits, and says its name."""

    name: Text
    view: ScreenView | None = None
    meet: Text
    traffic_day: Weekday
    clock: Clock
