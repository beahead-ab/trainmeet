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
from contracts.drift import DriftEvent, ProposalStatus
from contracts.planning import Draft, Proposal, Version

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


class Home(Contract):
    """Träffens hem (H35, SYNK-16): hubben där träffen planeras och versionerna publiceras. Den
    andra hubben följer och ändrar inget i Planering."""

    meet: Id
    hub_id: Id
    hub_name: Text
    here: bool = Field(description="Är hemmet den här hubben?")
    generation: int = Field(default=0, ge=0, description="Räknas upp varje gång hemmet flyttas.")
    since: datetime | None = None


class VersionList(Contract):
    """Träffens versioner, som molnet har dem. Följaren skickar tillbaka mark och får svar när
    något har ändrats, eller när väntan är slut (long-poll)."""

    meet: Id
    meet_name: Text
    versions: list[Version]
    mark: Text = Field(description="Listans kännetecken: ändras när en version publiceras.")
    home: Home | None = Field(default=None, description="Träffens hem, som molnet ser det.")


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
    home_here: bool = Field(
        default=False, description="Träffens hem är Pi:n: här planeras och publiceras (H35)."
    )


class CloudLinkChange(Contract):
    """Koppla Pi:n till molnet: molnhubbens adress och koden därifrån."""

    address: str = Field(min_length=8, max_length=200)
    code: str = CODE


class RunEvents(Contract):
    """Under träffen (SYNK-10, DRIFT-12): Pi:n leder och skickar körningens drifthändelser i
    ordning, efter molnets senaste kvittens. Utan händelser frågar Pi:n bara efter kvittensen,
    till exempel efter en omstart."""

    version: int = Field(ge=1)
    package: str = Field(
        pattern=r"^[0-9a-f]{64}$", description="Versionens kontrollsumma: samma paket i båda."
    )
    run: Text = Field(max_length=80, description="Körningens id, som på Pi:n.")
    events: list[DriftEvent] = Field(default_factory=list, max_length=500)


class RunAck(Contract):
    """Molnets kvittens: den sista händelse det har, och Planerings svar på förslagen (4.4)."""

    run: Text
    ack: int = Field(ge=0)
    answers: dict[Id, ProposalStatus] = Field(default_factory=dict)


class SourceFile(Contract):
    """Ett underlag som det kom, med i flytten."""

    id: Id
    data: str = Field(description="Filen i base64.")


class HomeBundle(Contract):
    """Det som flyttar med hemmet: utkastet, underlagen och förslagen från Drift (H35)."""

    meet: Id
    generation: int = Field(ge=1)
    created: datetime
    draft: Draft
    sources: list[SourceFile] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)


class SentVersion(Contract):
    """En version som Pi:n publicerade som hem, upp till molnet: info och byten (SYNK-10)."""

    generation: int = Field(ge=1)
    version: Version
    package: str = Field(description="Paketet som det publicerades, som JSON-text.")
