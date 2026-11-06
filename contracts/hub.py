"""Den här hubben: the hub's name, first start and the local login (H52, section 11).

Until TrainMeet ID (step 6), the local administrator is the one who chose the PIN at first
start. A session works as an HttpOnly cookie in the pages and as Authorization: Bearer for the
Drift API.
"""

from __future__ import annotations

from pydantic import Field

from contracts.common import Contract, Text

PIN = Field(pattern=r"^[0-9]{6,12}$", description="6–12 siffror. Skrivs aldrig ut i loggen.")


class HubInfo(Contract):
    name: Text
    set_up: bool = Field(description="Har hubben fått namn och PIN vid första start?")
    logged_in: bool


class SetUp(Contract):
    """First start: only possible while the hub has no PIN."""

    name: str = Field(min_length=1, max_length=40)
    pin: str = PIN


class LogIn(Contract):
    pin: str = PIN


class Session(Contract):
    session_key: Text = Field(
        description="Visas en gång. Gäller 12 timmar, eller tills utloggning."
    )
