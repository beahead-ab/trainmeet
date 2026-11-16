"""trainmeet.sync/1: Synkprotokollet (5.6, SYNK-10), Pi:n mot molnet (H11).

Följaren ringer alltid ut till den den följer; ingen port öppnas på träffen (SYNK-13). Steg 5
del 2: en Pi kopplas till en träff i molnet med en sexsiffrig kod (SYNK-02, fram till steg 6),
får en egen nyckel och följer sedan träffens versioner med long-poll. Kontrollsumman avgör om
ett paket är helt (SYNK-10). Varje anrop bär protokollets version, så att en Pi och molnet i
olika programversioner förstår varandra eller säger att de inte gör det (GRUND-18, F19).
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from pydantic import Field

from contracts.common import Contract, Id, Text
from contracts.planning import Version

PROTOCOL: Final = "trainmeet.sync/1"
HEADER: Final = "TrainMeet-Sync"  # the protocol each call speaks
CODE = Field(pattern=r"^[0-9]{6}$", description="Sex siffror. Gäller en gång, i 15 minuter.")


class Hello(Contract):
    """Vem som ringer: hubben, dess program och de versioner av protokollet den talar."""

    protocols: list[Text] = Field(default_factory=lambda: [PROTOCOL], min_length=1)
    hub_id: Id = Field(description="Hubbens id: slumpat vid första start, inte hemligt.")
    hub_name: Text
    software: Text = Field(description="Hubbens programversion, till exempel 0.1.0.")


class LinkCode(Contract):
    """Koppla en Pi (SYNK-02): koden som administratören i molnet ger Pi:n."""

    meet: Id
    code: str = CODE
    expires: datetime


class LinkRequest(Contract):
    code: str = CODE
    hello: Hello


class Link(Contract):
    """Molnets svar: träffen Pi:n nu följer och dess nyckel, som bara ges här, en gång."""

    meet: Id
    meet_name: Text
    key: Text = Field(min_length=32, description="Pi:ns nyckel mot molnet. Skrivs aldrig ut.")
    hello: Hello = Field(description="Molnets hälsning.")


class VersionList(Contract):
    """Träffens versioner, som molnet har dem. Följaren skickar tillbaka mark och får svar när
    något har ändrats, eller när väntan är slut (long-poll)."""

    meet: Id
    meet_name: Text
    versions: list[Version]
    mark: Text = Field(description="Listans kännetecken: ändras när en version publiceras.")


class Follower(Contract):
    """En Pi som följer träffen, som molnets administratör ser den."""

    hub_id: Id
    hub_name: Text
    software: Text
    linked: datetime
    heard: datetime | None = Field(default=None, description="När Pi:n senast hördes av.")


class CloudLink(Contract):
    """Molnet, som Pi:n ser det: en träff Pi:n följer. Nyckeln visas aldrig."""

    address: Text = Field(
        description="Molnhubbens adress, till exempel https://test.hub.trainmeet.app."
    )
    meet: Id
    meet_name: Text
    cloud_name: Text
    linked: datetime
    heard: datetime | None = None
    versions: int = Field(default=0, ge=0, description="Versioner Pi:n har av träffen.")
    problem: Text | None = Field(default=None, description="Varför Pi:n inte når molnet just nu.")


class CloudLinkChange(Contract):
    """Koppla Pi:n till molnet: molnhubbens adress och koden därifrån."""

    address: str = Field(min_length=8, max_length=200)
    code: str = CODE
