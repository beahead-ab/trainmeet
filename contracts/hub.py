"""Den här hubben: the hub's name, first start and the local login (H52, section 11).

Until TrainMeet ID (step 6), the local administrator is the one who chose the PIN at first
start. A session works as an HttpOnly cookie in the pages and as Authorization: Bearer for the
Drift API.
"""

from __future__ import annotations

from datetime import datetime

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


class Version(Contract):
    """What runs (GET /api/version): the version, the hub's name and the change it was built
    from. A local build has no commit and no pull request."""

    product: Text
    version: Text
    hub_name: Text
    commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,40}$")
    pr: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, max_length=500)
    built: datetime | None = None
    pr_url: str | None = Field(default=None, description="Ändringen på GitHub.")
    commit_url: str | None = Field(default=None, description="Committen på GitHub.")
