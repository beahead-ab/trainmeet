"""trainmeet.driver/1: the drivers' API, for Lokföraren and for the dispatcher's Förare page.

Lokföraren is a client of Drift of its own (LOK-10): it owns nothing. Drift owns which service a
driver runs, the check-ins, the messages, the clock and where the trains are (LOK-07); the
duties and the general instructions come from the meet package, planned in Planering. A driver
needs no account (LOK-16): the meet's QR code, a name and a level give a device key, a random
secret kept on the phone and stored by the hub only as its hash. It is never logged. TrainMeet
ID is optional and links the driver to the person. A driver without an account stays for the
meet that runs (LOK-41).

Transport: HTTP with JSON under /api/drift/1/drivers. The device key goes in the cookie the join
sets, or in the header X-Driver-Key; never in the address or the body after the join.

    POST /api/drift/1/drivers/join          DriverJoin -> DriverSession   the key, once
    GET  /api/drift/1/drivers/me            DriverMe                      my service, the clock
    POST /api/drift/1/drivers/me            DriverProfile -> DriverMe     name, level, Paus …
    POST /api/drift/1/drivers/me/photo      the picture's bytes -> DriverMe
    POST /api/drift/1/drivers/me/photo/remove  -> DriverMe
    GET  /api/drift/1/drivers/services?q=   ServiceList                   duties, or trains
    POST /api/drift/1/drivers/claim         ServiceRef -> DriverMe        first one wins
    POST /api/drift/1/drivers/release       -> DriverMe                   anywhere (LOK-25)
    GET  /api/drift/1/drivers/korplan       Korplan                       with the NU-linje
    POST /api/drift/1/drivers/checkin       CheckIn -> DriverMe
    POST /api/drift/1/drivers/framme        Framme -> DriverMe
    POST /api/drift/1/drivers/messages      DriverMessageSend -> DriverMessage
    GET  /api/drift/1/drivers/clock         DriverClock                   Drift's, never the phone's
    GET  /api/drift/1/drivers/trains        list[TrainPosition]           where the trains are
    GET  /api/drift/1/drivers/list          list[DriverPresence]          Förare, and the maps
    GET  /api/drift/1/drivers/photos/{driver}   the photo, under the same rule as the names
    GET  /api/drift/1/drivers/wait?after=   DriverWait                    long-poll, Drift's events
    GET  /api/drift/1/drivers/instructions  Instructions                  LOK-34
    GET  /api/drift/1/drivers/instructions.pdf
    POST /api/drift/1/drivers/leave         -> 204                        lämna träffen

Efter pappret (LOK-13, LOK-29, LOK-33): a duty missing from the plan, read from the driver's
photos of its pages. The price is told first: 12 tokens a page (TOKEN-14), paid by the meet or
by the driver as the meet chose in Förarna, or nothing with the hub's own AI. The photos come as
multipart/form-data, 1–4 parts named pages, and their metadata is stripped before anything is
sent. AI only suggests: a time it could not read stays empty. The planned services nearest the
paper's start come with the reading, and the driver may take one of them instead.

    GET  /api/drift/1/drivers/paper/price?pages=  PaperPrice                    before reading
    POST /api/drift/1/drivers/paper         the photos -> PaperService    read, and run by it
    GET  /api/drift/1/drivers/paper/{paper}/pages/{page}   a photo, cleaned

The dispatcher's side, Förare in Drift (TRAFIK-33), for Trafikledningen and the lokledare:

    GET  /api/drift/1/drivers/overview      DriverOverview
    POST /api/drift/1/drivers/hand-out      HandOut -> DriverOverview     also the lokledare
    POST /api/drift/1/drivers/take-back     TakeBack -> DriverOverview    also the lokledare
    POST /api/drift/1/drivers/settings      DriverSettings -> DriverOverview  Trafikledningen
    POST /api/drift/1/drivers/alarms/clear  ServiceRef -> DriverOverview
    GET  /api/drift/1/drivers/connect       Joining                       the QR code's address
    GET  /api/drift/1/drivers/connect.svg
    POST /api/drift/1/drivers/paper/{paper}/approve  PaperApprove -> DriverOverview  LOK-13
    POST /api/drift/1/drivers/paper/{paper}/reject   PaperReject -> DriverOverview

Until Trafikledningen approves a service run after the paper, only the driver and Förare see it:
no station snapshot, no clearance. Approved, it is an extra train in Drift with the paper's
calls, marked Efter pappret (paper) wherever it shows. Rejected, the driver gets the reason.

Förarna in Planering (PLAN-40, LOK-33): who pays when a driver's photos are read, per meet.

    GET  /api/planering/1/meets/{meet}/paper-reading   PaperReadingSettings
    POST /api/planering/1/meets/{meet}/paper-reading   PaperReadingChange -> PaperReadingSettings

Names and photos of drivers are shown only on the meet's network or to someone logged in, never
over the internet without logging in (LOK-37, S8): there the name, the initials and the photo
are left out.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final, Literal

from pydantic import Field

from contracts.common import Contract, Id, Text, TimeOfDay, Weekday
from contracts.drift import (
    ClaimedBy,
    DriverAlarm,
    DriverSettings,
    PaperEnd,
    PaperPayer,
    PaperRow,
    PaperStatus,
    ServiceKind,
    ServiceRef,
)
from contracts.meet import DriverLevel
from contracts.station import Clock, DriverMessageKind

PROTOCOL: Final = "trainmeet.driver/1"
KEY_HEADER: Final = "X-Driver-Key"
"""Where a client that keeps no cookie sends the device key."""

REMINDERS: Final = (20, 10)
"""Reminders before the start, in game minutes (LOK-41). The app reminds; the hub says when."""
CHANGED_MINUTES: Final = 10
"""How long the mark Ändrat stays, in game minutes (LOK-41)."""
CHECKIN_VISIBLE_MINUTES: Final = 10
CHECKIN_FADE_MINUTES: Final = 5
"""A check-in is seen 10 game minutes and fades out over 5 more (the old Server, A8)."""
PAPER_PAGES: Final = 4
"""The most pages of a duty a driver photographs at a time (LOK-29)."""
UNKNOWN_PLACE: Final = "okand"
"""The place id a körplan row or a service's end has when the place on the paper is not one of
the meet's: the name stands as it was read (LOK-29)."""

__all__ = [
    "PROTOCOL",
    "ClaimedBy",
    "DriverAlarm",
    "DriverLevel",
    "DriverMessageKind",
    "DriverSettings",
    "PaperEnd",
    "PaperPayer",
    "PaperRow",
    "PaperStatus",
    "ServiceKind",
    "ServiceRef",
]


class DriverState(StrEnum):
    """What the others see of a driver without a service on the line (LOK-27)."""

    PAUSE = "pause"  # Paus
    WAITING_START = "waiting_start"  # Inväntar start


LEVEL_TEXT: Final[dict[str, dict[DriverLevel, str]]] = {
    "sv": {
        DriverLevel.EASY: "Lätt",
        DriverLevel.MEDIUM: "Medel",
        DriverLevel.EXPERIENCED: "Erfaren",
    },
    "en": {
        DriverLevel.EASY: "Easy",
        DriverLevel.MEDIUM: "Medium",
        DriverLevel.EXPERIENCED: "Experienced",
    },
}
MESSAGE_TEXT: Final[dict[str, dict[DriverMessageKind, str]]] = {
    "sv": {
        DriverMessageKind.DELAYED: "Försenad",
        DriverMessageKind.STOPPED_ON_LINE: "Står på linjen",
        DriverMessageKind.NEEDS_HELP: "Behöver hjälp",
        DriverMessageKind.ENGINE_TROUBLE: "Loket krånglar",
    },
    "en": {
        DriverMessageKind.DELAYED: "Delayed",
        DriverMessageKind.STOPPED_ON_LINE: "Stopped on the line",
        DriverMessageKind.NEEDS_HELP: "Needs help",
        DriverMessageKind.ENGINE_TROUBLE: "Engine trouble",
    },
}
STATE_TEXT: Final[dict[str, dict[DriverState, str]]] = {
    "sv": {DriverState.PAUSE: "Paus", DriverState.WAITING_START: "Inväntar start"},
    "en": {DriverState.PAUSE: "Break", DriverState.WAITING_START: "Waiting to start"},
}

# --- Coming in -------------------------------------------------------------------------------


class DriverJoin(Contract):
    """Kom in (LOK-01, LOK-16): QR-koden på träffen, namnet och nivån. Koden behövs inte på
    träffens nät, där föraren kommer till träffen som kör."""

    code: str | None = Field(
        default=None, pattern=r"^[0-9]{6}$", description="Förarnas kod ur QR-koden."
    )
    name: Text = Field(max_length=40, description="Namnet föraren skriver.")
    level: DriverLevel = DriverLevel.EASY


class Driver(Contract):
    """En förare på träffen. Namn, initialer och foto bara där reglerna tillåter (LOK-37)."""

    id: Id
    name: Text | None = Field(default=None, description="Tomt över internet utan inloggning.")
    initials: Text | None = None
    level: DriverLevel
    state: DriverState | None = None
    photo: str | None = Field(default=None, description="Adressen till fotot, om det finns.")
    linked: bool = Field(default=False, description="Kopplad till en person i TrainMeet ID.")
    joined: datetime


class DriverSession(Contract):
    """Svaret på Kom in: föraren och nyckeln, som visas en gång och sparas på telefonen."""

    driver: Driver
    key: str = Field(description="Telefonens nyckel. Hubben sparar bara ett kontrollvärde.")


class DriverProfile(Contract):
    """Det föraren själv ändrar: namnet, nivån och Paus eller Inväntar start. Fält som inte
    skickas ändras inte; state null tar bort läget."""

    name: Text | None = Field(default=None, max_length=40)
    level: DriverLevel | None = None
    state: DriverState | None = None
    clear_state: bool = Field(default=False, description="Ta bort Paus eller Inväntar start.")


# --- The services ----------------------------------------------------------------------------


class ServiceEnd(Contract):
    """Där tjänsten startar eller slutar, som på framsidan: tid och driftplats."""

    time: TimeOfDay | None = None
    place: Id
    place_name: Text


class ServiceOffer(Contract):
    """En tjänst som listan visar den, med samma uppgifter som papprets framsida: nummer, start,
    slut, bolag och svårighet (LOK-19). Tagen visar att någon kör den."""

    service: ServiceRef
    number: Text = Field(description="Papprets nummer, eller tågets nummer.")
    start: ServiceEnd
    end: ServiceEnd
    operator: Text | None = None
    level: DriverLevel | None = None
    trains: list[Text] = Field(default_factory=list, description="Tågnumren, i ordning.")
    taken: bool = False
    driver: Id | None = Field(default=None, description="Föraren som har tjänsten.")
    driver_name: Text | None = Field(default=None, description="Bara där namn får visas.")
    released_on_line: bool = Field(
        default=False, description="Släppt på linjen: står först i listan (LOK-40)."
    )
    matches_level: bool = Field(default=False, description="Passar förarens nivå (LOK-32).")
    exact: bool = Field(default=False, description="Numret är exakt det som söktes.")
    done: bool = Field(default=False, description="Klar: Framme vid sista tågbesöket.")
    paper: PaperStatus | None = Field(
        default=None, description="Efter pappret: tjänsten finns inte i planen (LOK-13)."
    )


class ServiceList(Contract):
    """Tjänsterna att välja bland: köruppdragen när träffen har sådana, annars tågen (LOK-17,
    LOK-31). Släppta på linjen först, sedan de som passar förarens nivå, i startordning."""

    kind: ServiceKind
    services: list[ServiceOffer] = Field(default_factory=list)


class HandOut(Contract):
    """Trafikledningen eller lokledaren delar ut en tjänst (LOK-30). Har någon annan den, flyttas
    den; har föraren en annan, lämnas den tillbaka först."""

    driver: Id
    service: ServiceRef


class TakeBack(Contract):
    """Trafikledningen eller lokledaren tar tillbaka förarens tjänst."""

    driver: Id


# --- Check-in, Framme and the messages -------------------------------------------------------


class CheckIn(Contract):
    """Förarens egen incheckning på en driftplats (LOK-22)."""

    place: Id
    track: Text | None = Field(default=None, max_length=12)


class CheckedIn(Contract):
    """Förarens senaste incheckning, så länge den syns: 10 spelminuter och sedan 5 till medan
    den tonar ut (A8)."""

    place: Id
    place_name: Text
    track: Text | None = None
    train: Id | None = None
    train_number: Text | None = None
    model_time: TimeOfDay
    age_seconds: float = Field(ge=0, description="Spelsekunder sedan incheckningen.")
    fading: bool = Field(default=False, description="Tonar ut.")


class Framme(Contract):
    """Framme vid ett tågbesök i tjänsten (LOK-04). Vid tjänstens sista tågbesök är tjänsten
    klar. Det räknas som ankomst bara när trafikspelet valt det och platsen är obemannad."""

    call: Id


class DriverMessageSend(Contract):
    kind: DriverMessageKind


class DriverMessage(Contract):
    """Ett meddelande till trafikledningen: förare, tjänst, tåg och tid (LOK-23)."""

    seq: int = Field(ge=1)
    kind: DriverMessageKind
    driver: Id
    driver_name: Text | None = None
    service: ServiceRef | None = None
    service_number: Text | None = None
    train: Id | None = None
    train_number: Text | None = None
    model_time: TimeOfDay
    wall_time: datetime


# --- The clock and the körplan ---------------------------------------------------------------


class DriverClock(Contract):
    """Träffklockan ur Drift (LOK-12). Telefonen räknar fram från seconds med speed och sin egen
    tid sedan svaret, aldrig från sitt eget klockslag."""

    clock: Clock
    traffic_day: Weekday
    read: datetime = Field(description="När hubben läste klockan.")


class Start(Contract):
    """När tjänsten startar, för nedräkningen och påminnelserna 20 och 10 minuter före (LOK-41).
    Verklig tid bredvid nedräkningen."""

    time: TimeOfDay
    seconds: int = Field(description="Starten i sekunder in på speldygnet.")
    in_game_seconds: int = Field(description="Spelsekunder kvar; negativt när den passerats.")
    in_real_seconds: int | None = Field(
        default=None, description="Verkliga sekunder kvar med klockans fart; tomt när den står."
    )
    reminders: list[int] = Field(default_factory=lambda: list(REMINDERS))


class TrainPosition(Contract):
    """Var tåget är enligt stationerna: på en driftplats, eller på väg mellan två (LOK-20).
    Förseningen i hela minuter."""

    train: Id
    train_number: Text
    state: Literal["planned", "at", "on_the_way", "done"] = Field(
        description="Inte iväg än, står på en driftplats, på väg, eller framme vid slutet."
    )
    place: Id | None = Field(default=None, description="Driftplatsen tåget står på.")
    from_place: Id | None = None
    to_place: Id | None = None
    section: Id | None = None
    delay: int | None = Field(default=None, description="Minuter sent; tomt när det inte vet.")
    paper: bool = Field(
        default=False, description="Efter pappret: tåget finns inte i planen (LOK-13)."
    )


class LateOncoming(Contract):
    """Ett mötande tåg som är sent (LOK-20)."""

    train: Id
    train_number: Text
    delay: int = Field(ge=1)


class RowReality(Contract):
    """Verkligheten från Drift på en rad, när trafikspelet valt det (LOK-20)."""

    passed: bool = Field(default=False, description="Tåget har lämnat eller passerat.")
    here: bool = Field(default=False, description="Tåget står här nu.")
    arrived: TimeOfDay | None = None
    departed: TimeOfDay | None = None
    delay: int | None = None
    late_oncoming: list[LateOncoming] = Field(default_factory=list)


class RowClearance(Contract):
    """Tågklareringens besked för avgången härifrån, när trafikspelet valt det (LOK-21): klart är
    en upplysning, avgång ger tågklareraren eller signalen (LOK-11)."""

    status: Literal["waiting", "approved", "rejected"] = Field(
        description="Stationen väntar på klart, sträckan är klar, eller nej."
    )
    to_place: Id
    track: Text | None = Field(default=None, description="Spåret tåget tas in på.")


class KorplanRow(Contract):
    """Ett tågbesök i körplanen."""

    call: Id
    train: Id
    train_number: Text
    place: Id
    place_code: Text
    place_name: Text
    arrival: TimeOfDay | None = None
    departure: TimeOfDay | None = None
    track: Text | None = None
    stops: bool = True
    note: Text | None = None
    first_of_train: bool = Field(default=False, description="Här börjar ett nytt tåg.")
    last: bool = Field(default=False, description="Tjänstens sista tågbesök.")
    unmanned: bool = Field(
        default=False,
        description="Ingen trycker Ankommit här: ingen arbetar driftplatsen nu, eller den "
        "fjärrstyrs och stationen kan inte se tåget komma in. Här kan Framme räknas som ankomst "
        "(LOK-39, beslut 22 november).",
    )
    changed: bool = Field(default=False, description="Ändrat de senaste 10 spelminuterna.")
    unreadable: bool = Field(
        default=False,
        description="Efter pappret: tiden stod på pappret men gick inte att läsa (LOK-29). "
        "Den visas som okänd, aldrig gissad.",
    )
    real: RowReality | None = None
    clearance: RowClearance | None = None


class Korplan(Contract):
    """Körplanen ur köruppdragets delar, eller ur tågets tidtabell. NU-linjen följer bara
    träffklockan (LOK-20); verkligheten och klareringens besked bara när trafikspelet valt det."""

    service: ServiceRef
    number: Text
    rows: list[KorplanRow] = Field(default_factory=list)
    clock: Clock
    settings: DriverSettings
    position: TrainPosition | None = Field(
        default=None, description="Tågets läge enligt Drift, när verkligheten visas."
    )
    checkin: CheckedIn | None = Field(
        default=None, description="Förarens egen incheckning, bredvid tågets läge (LOK-22)."
    )
    revision: int = Field(ge=0, description="Senaste drifthändelsen.")
    paper: PaperStatus | None = Field(
        default=None,
        description="Efter pappret: avläst ur förarens foton och inte i planen. Utan "
        "verklighet från Drift tills trafikledningen har godkänt den (LOK-13).",
    )


# --- Efter pappret (LOK-13, LOK-29, LOK-33) ------------------------------------------------


class PaperService(Contract):
    """En tjänst efter pappret, som föraren och Förare ser den: framsidan och tidtabellen som
    AI:n läste dem, var den står, och de tjänster i planen som startar närmast (LF16). Inga
    stationer ser den förrän trafikledningen har godkänt den (LOK-13)."""

    paper: Id
    service: ServiceRef
    status: PaperStatus
    driver: Id
    driver_name: Text | None = Field(default=None, description="Bara där namn får visas.")
    number: Text | None = Field(default=None, description="Tjänstens nummer på pappret.")
    train_number: Text | None = Field(
        default=None, description="Tågnumret: på pappret, eller det trafikledningen gav."
    )
    operator: Text | None = None
    start: PaperEnd
    end: PaperEnd
    rows: list[PaperRow] = Field(default_factory=list)
    pages: int = Field(ge=1, le=PAPER_PAGES)
    photos: list[str] = Field(default_factory=list, description="Adresserna till fotona.")
    paid_by: PaperPayer
    cost: int = Field(ge=0, description="Tokens som drogs för läsningen.")
    said: Text = Field(
        description="Pappret jämfört med planen: ingen tjänst startar där och då, eller "
        "vilken som gör det."
    )
    candidates: list[ServiceOffer] = Field(
        default_factory=list,
        description="Tjänsterna i planen som startar närmast papprets start (LF16). Föraren kan "
        "ta en av dem i stället.",
    )
    reason: Text | None = Field(default=None, description="Avslagen: trafikledningens skäl.")
    train: Id | None = Field(default=None, description="Godkänd: tåget i Drift.")
    model_time: TimeOfDay = Field(description="När pappret lästes, på träffklockan.")
    wall_time: datetime


class PaperPrice(Contract):
    """Priset innan något läses (TOKEN-14): 12 tokens per sida, ur träffens saldo eller förarens
    eget som träffen valt (LOK-33), eller inget med hubbens egen AI. ready säger om det går."""

    pages: int = Field(ge=1, le=PAPER_PAGES)
    price: int = Field(ge=0, description="Tokens för sidorna.")
    per_page: int = Field(ge=0)
    paid_by: PaperPayer | None = None
    payer: Text | None = Field(
        default=None, description="Vems saldo: klubbens, personens, eller hubbens egen AI."
    )
    available: int | None = Field(default=None, description="Saldot som är kvar.")
    ready: bool = Field(description="Går att läsa nu.")
    message: Text | None = Field(default=None, description="Varför inte, och vad föraren gör.")
    log_in: bool = Field(
        default=False,
        description="Förarens egna tokens betalar och föraren är inte inloggad: inloggning med "
        "TrainMeet ID gör att pappret går att läsa (LOK-33).",
    )


class PaperApprove(Contract):
    """Godkänn tjänsten efter pappret (LOK-13): den blir ett extratåg i Drift med papprets
    tågbesök, och tågklarerarna ser det märkt Efter pappret."""

    train_number: Text | None = Field(
        default=None,
        max_length=20,
        description="Tågnumret hos tågklarerarna; tomt betyder det som står på pappret.",
    )


class PaperReject(Contract):
    """Avslå tjänsten efter pappret: föraren får skälet."""

    reason: Text = Field(max_length=200)


PaperReadingPayer = Literal["meet", "driver"]


class PaperReadingSettings(Contract):
    """Förarna i Planering (PLAN-40, LOK-33): vem som står för AI-läsningen när en förare fotar
    ett köruppdrag som saknas i planen. Förarens egna tokens är förval."""

    payer: PaperReadingPayer = "driver"
    payer_title: Text | None = Field(
        default=None, description="Träffens saldo: klubbens namn, eller personens."
    )
    available: int | None = Field(default=None, description="Det som är kvar på träffens saldo.")
    per_page: int = Field(ge=0, description="Tokens per fotad sida (TOKEN-14).")
    own_ai: Text | None = Field(
        default=None,
        description="Hubbens egen AI, när den finns: den läser då utan tokens (TOKEN-13).",
    )
    trainmeet_ai: bool = Field(
        default=False, description="Hubben når mätaren i TrainMeet ID (molnhubben)."
    )
    may_change: bool = Field(default=False, description="Den som frågar får ändra valet.")


class PaperReadingChange(Contract):
    """Träffens tokens eller förarens egna. Träffens tokens väljs inloggad med TrainMeet ID:
    då betalar klubben för en träff i ID, annars den som valde (TK16)."""

    payer: PaperReadingPayer


class DriverMe(Contract):
    """Föraren själv: tjänsten, klockan, incheckningen och vad trafikspelet visar."""

    driver: Driver
    service: ServiceOffer | None = None
    claimed_by: ClaimedBy | None = Field(
        default=None,
        description="Vem som gav föraren tjänsten: föraren själv, trafikledningen eller "
        "lokledaren (LOK-30).",
    )
    start: Start | None = None
    checkin: CheckedIn | None = None
    clock: Clock
    settings: DriverSettings
    revision: int = Field(ge=0, description="Senaste drifthändelsen, för väntan på nästa.")
    paper: PaperService | None = Field(
        default=None,
        description="Förarens tjänst efter pappret: den föraren kör, eller den senast avslagna "
        "med skälet så länge föraren inte har tagit en annan (LOK-13).",
    )


class DriverWait(Contract):
    """Svaret på väntan: det har hänt något efter after, eller tiden gick ut."""

    revision: int = Field(ge=0)
    changed: bool


class DriverPresence(Contract):
    """En förare som de andra ser den, på kartorna och i Förare (LOK-27)."""

    driver: Driver
    service_number: Text | None = None
    train_number: Text | None = None
    checkin: CheckedIn | None = None
    me: bool = False


class Instructions(Contract):
    """De allmänna instruktionerna som köruppdragen hänvisar till (LOK-34): text och PDF ur
    träffpaketet. Lokföraren visar det som finns."""

    text: dict[str, str] = Field(default_factory=dict, description="Texten per språk.")
    pdf: str | None = Field(default=None, description="Adressen till PDF:en, om den finns.")
    filename: Text | None = None


# --- Förare in Drift (TRAFIK-33) --------------------------------------------------------------


class DriverRow(Contract):
    """En förare i trafikledningens lista: tjänsten, incheckningen, läget och senaste
    meddelandet."""

    driver: Driver
    service: ServiceOffer | None = None
    checkin: CheckedIn | None = None
    position: TrainPosition | None = None
    message: DriverMessage | None = None


class DriverOverview(Contract):
    """Förare i Drift: förarna, tjänsterna och vem som kör dem, meddelandena, larmen och
    trafikspelets val. Lokledaren ser och delar ut, men ändrar inte valen (LOK-30)."""

    drivers: list[DriverRow] = Field(default_factory=list)
    services: ServiceList
    messages: list[DriverMessage] = Field(default_factory=list, description="Nyast först.")
    alarms: list[DriverAlarm] = Field(default_factory=list)
    settings: DriverSettings
    may_hand_out: bool = False
    may_set: bool = Field(default=False, description="Får ändra trafikspelets val.")
    names_shown: bool = Field(default=True, description="Namnen visas här (LOK-37).")
    papers: list[PaperService] = Field(
        default_factory=list,
        description="Tjänsterna efter pappret, de som väntar på godkännande först (LOK-13). "
        "Trafikledningen godkänner eller avslår.",
    )


__all__ += [
    "CheckIn",
    "CheckedIn",
    "Driver",
    "DriverClock",
    "DriverJoin",
    "DriverMe",
    "DriverMessage",
    "DriverMessageSend",
    "DriverOverview",
    "DriverPresence",
    "DriverProfile",
    "DriverRow",
    "DriverSession",
    "DriverState",
    "DriverWait",
    "Framme",
    "HandOut",
    "Instructions",
    "Korplan",
    "KorplanRow",
    "LateOncoming",
    "PaperApprove",
    "PaperPrice",
    "PaperReadingChange",
    "PaperReadingPayer",
    "PaperReadingSettings",
    "PaperReject",
    "PaperService",
    "RowClearance",
    "RowReality",
    "ServiceEnd",
    "ServiceList",
    "ServiceOffer",
    "Start",
    "TakeBack",
    "TrainPosition",
]
