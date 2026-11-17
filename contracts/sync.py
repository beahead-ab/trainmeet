"""trainmeet.sync/1: Synkprotokollet (5.6, SYNK-10), Pi:n mot molnet (H11).

Följaren ringer alltid ut till den den följer; ingen port öppnas på träffen (SYNK-13). Steg 5
del 2: en Pi kopplas till en träff i molnet med en sexsiffrig kod (SYNK-02, fram till steg 6),
får en egen nyckel och följer sedan träffens versioner med long-poll. Kontrollsumman avgör om
ett paket är helt (SYNK-10). Varje anrop bär protokollets version, så att en Pi och molnet i
olika programversioner förstår varandra eller säger att de inte gör det (GRUND-18, F19).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final

from pydantic import Field, model_validator

from contracts import station
from contracts.common import Contract, Id, Text
from contracts.drift import DriftEvent, ProposalStatus
from contracts.planning import Draft, Proposal, Version
from contracts.station_outside import StationOutside

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


class RunFeed(Contract):
    """Körningen som molnet leder efter ett övertag (H9): ledarens händelser, för en Pi som
    följer från nu."""

    leader: Text
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


# --- Reläet (SYNK-05, SYNK-11) ------------------------------------------------------------

RELAY_WAIT: Final = 20.0  # seconds a relayed revision may wait for a change
KEY_HASH = Field(
    default=None,
    pattern=r"^[0-9a-f]{64}$",
    description="Klientens nyckel som SHA-256: nyckeln själv följer aldrig med (H31).",
)


class RelayKind(StrEnum):
    CONNECT = "connect"
    CONNECTION = "connection"
    SNAPSHOT = "snapshot"
    COMMAND = "command"
    REVISION = "revision"  # waits until the place changes, for the event stream
    PUSH = "push"  # the phone's address for push, or none to stop
    EXIT = "exit"  # TKL answers which exit a section has (H26)


class RelayCall(Contract):
    """Ett anrop i stationsprotokollet från en telefon eller molnets TKL utanför träffens nät.
    Molnet ställer det i kö till hubben som leder, och den hämtar det på sin egen förbindelse
    (SYNK-11, SYNK-13). Molnet sparar ingenting av trafiken (SYNK-22)."""

    id: Id
    kind: RelayKind
    key_hash: str | None = KEY_HASH
    place: Id | None = None
    client_id: Id | None = None
    connect: station.ConnectRequest | None = None
    command: station.Command | None = None
    known: int | None = Field(default=None, ge=0, description="Platsens revision som klienten har.")
    wait: float = Field(default=0.0, ge=0.0, le=RELAY_WAIT)
    push: station.PushToken | None = None
    exit: station.ExitAnswer | None = None


class RelayCalls(Contract):
    calls: list[RelayCall] = Field(default_factory=list, max_length=100)


class RelayAnswer(Contract):
    """Hubbens svar på ett anrop genom reläet, som molnet ger klienten som det är."""

    id: Id
    status: int = Field(ge=200, le=599, description="HTTP-status, som om klienten frågat hubben.")
    detail: Text | None = Field(default=None, description="Varför, när status inte är 2xx.")
    connected: station.ConnectReply | None = None
    snapshot: station.Snapshot | None = None
    reply: station.Reply | None = None
    revision: int | None = Field(default=None, ge=0)


# --- Push (SYNK-05, F20) -----------------------------------------------------------------------


class Push(Contract):
    """En notis till en telefon. Pi:n har ingen nyckel till Apple, så den skickar sina notiser
    till molnet, som skickar dem vidare: push går samma väg som reläet (SYNK-11)."""

    token: station.PushToken
    notice: station.Notice


class PushBatch(Contract):
    pushes: list[Push] = Field(default_factory=list, max_length=500)


# --- Stationspaketen (SYNK-06, SYNK-12, SYNK-18, H71, SYNK-30) -----------------------------------


class StationPackage(Contract):
    """Hela stationspaketet från TKL: utsidan, som går vidare till en träff eller en Pi, och
    insidan, som stannar hos ägaren. Synk sparar insidan som den kom, utan att läsa den."""

    station_id: Id
    outside: StationOutside
    inside: dict[str, object] = Field(
        default_factory=dict, description="Spårplan, signaler och adresser: TKL:s egna."
    )

    @model_validator(mode="after")
    def _same_station(self) -> StationPackage:
        if self.outside.station_id != self.station_id:
            raise ValueError("Utsidan hör till en annan station.")
        return self


class StationVersionInfo(Contract):
    station_id: Id
    version: int = Field(ge=1)
    saved: datetime
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: Text


class StationVersions(Contract):
    """Ägarens privata versioner av stationen, den senaste sist."""

    station_id: Id
    versions: list[StationVersionInfo] = Field(default_factory=list)
