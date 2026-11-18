"""TrainMeet TKL's own API: between TKL's server and its web app (apps/tkl), under /api/tkl/1/.

TKL is a program of its own (ST3, KLAR-22). Its server runs on the station's computer or a
Raspberry Pi and holds what TKL owns (KLAR-08): the station's outside and the PIN that locks
it. When TKL connects to a meet it also holds the key from the approval; the key stays in the
server and never reaches the browser or a log (H31). Towards the hub TKL speaks the station
protocol (contracts/station.py), nothing else.

Level 0 (TKL21, KLAR-15): the tracks and exits are written as a list, without a drawing. The
list is the station's outside; a new version of it is made with a button (TKL25).

Level 1–2 (#83): the station's model (contracts/station_model.py) is imported in Studio and kept
with the station, versioned with the outside, which is then derived from it (STD-08, TKL92).
The web app draws the station as a panel: the layout engine's proposal on the grid, or the
panel built from the station's own track plan (STD-09, STD-25). The four reference stations
can be looked at and used as one's own.

Ställverket at level 1–2 (#84): TKL's server holds the interlocking's state of the moment, set
routes, locks, switch positions, signal aspects and the train numbers (STV-08), under
/api/tkl/1/stallverk. Every operation answers yes, or no with the reason in Swedish; the
interlocking's functions are the one place where safety is checked (STV-43, STV-44). The
clearance, the timetable and the train number on the line stay Hubben's (STV-09).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import Field, StringConstraints, model_validator

from contracts.common import Contract, Id, Text
from contracts.station import (
    Action,
    ApprovalStatus,
    ExitSignalAspect,
    MeetContext,
    MessageId,
    Revision,
    Snapshot,
)
from contracts.station_model import (
    Cell,
    Name,
    NodeType,
    PanelBuilding,
    PanelFunctionType,
    Point,
    Position,
    SignalType,
    SwitchControl,
    SwitchType,
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
    """Studio's outside: the list as it is on the computer, and the versions made of it.

    While the station has a model, the draft is derived from it (STD-08, TKL92) and is not
    written as a list; without the model, the last outside is the list again.
    """

    draft: StationOutside
    versions: list[OutsideVersion] = Field(default_factory=list, description="Senaste först.")
    changed: bool = Field(
        description="Listan eller stationsmodellen skiljer sig från den senaste versionen."
    )
    station_model: bool = Field(
        default=False,
        description="Stationen har en stationsmodell (nivå 1–2, #83). Utsidan räknas då fram "
        "ur den, och listan går inte att skriva (TKL92).",
    )


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


class TklIdState(Contract):
    """TrainMeet ID i TKL (TKL18, #78) och stationspaketet i molnet (SYNK-30)."""

    available: bool = Field(description="Har TKL inloggning med TrainMeet ID?")
    person: Text | None = Field(default=None, description="Den som är inloggad: namnet.")
    cloud: Text | None = Field(default=None, description="Molnhubben där stationspaketen sparas.")
    saved: int | None = Field(
        default=None, description="Den senaste versionen i molnet som TKL har sparat eller sett."
    )
    local: int | None = Field(default=None, description="Utsidans senaste version på datorn.")


class TklSave(Contract):
    """Spara i molnet: utsidans senaste version som ett nytt stationspaket (SYNK-06). on_top:
    spara ovanpå den versionen när molnet har en nyare än TKL känner (H71). Utelämnat: ovanpå
    den TKL känner, och en nyare i molnet nekar."""

    on_top: int | None = Field(default=None, ge=0)


class TklSaved(Contract):
    version: int | None = Field(default=None, description="Sparad som den versionen i molnet.")
    behind: int | None = Field(
        default=None, description="Molnet har en nyare version, sparad från en annan dator."
    )
    message: Text | None = None


# --- The panel: the station on the grid (#83, §3 of the standard interlocking) ------------


class PanelAngle(StrEnum):
    """The one transition angle of a panel (TKL6, STD-11)."""

    STEEP = "45"  # 45°: 3 rutor i sidled per spår
    FLAT = "1:2"  # flackt 1:2, ca 27°: 6 rutor i sidled per spår


class PanelSource(StrEnum):
    ENGINE = "engine"  # motorns förslag (STD-09)
    PLAN = "plan"  # byggd ur stationens spårplan (STD-25)


LabelSide = Literal["over", "under"]
Anchor = Literal["start", "middle", "end"]


class PanelLine(Contract):
    """A track piece on the panel: its way over the grid, and its real shape for the soft view."""

    piece: Name
    track: Text | None = None
    cells: list[Cell] = Field(min_length=2, description="Från spårbitens början till slutet.")
    real: list[Point] = Field(default_factory=list, description="Ritningens form (TKL42).")
    free: bool = Field(default=False, description="Vid vändskivan: i vilken vinkel som helst.")


class PanelNode(Contract):
    id: Name
    type: NodeType
    cell: Cell
    real: Point | None = None


class PanelSwitch(Contract):
    """A switch, slip or crossing, with its legs and where its number stands (§3.4)."""

    number: Name
    type: SwitchType
    node: Name
    cell: Cell
    real: Point | None = None
    trunk: Name | None = None
    straight: Name | None = None
    diverging: Name | None = None
    pieces: list[Name] = Field(default_factory=list, description="Korsningens fyra spårbitar.")
    label: Cell = Field(description="Växelnumret, vid knuten.")
    laid: bool = Field(default=True, description="TKL lägger den.")


class PanelSignal(Contract):
    """A signal: its symbol in the track line, or beside it for a stop lamp (TKL45), and its id
    over the track for a signal towards the east and under for one towards the west, outside
    the pair on a double-track line (TKL43)."""

    name: Name
    type: SignalType
    node: Name
    cell: Cell
    toward: Cell = Field(description="Färdriktningen som signalen gäller, i rutor.")
    symbol: Cell
    label: Cell
    side: LabelSide
    planned: bool = False
    real: Point | None = None
    real_toward: Point | None = None


class PanelLabel(Contract):
    """A text in a fixed place: an exit at its row's end, a stop point, a buffer stop."""

    text: Text
    kind: Literal["exit", "point"]
    cell: Cell
    anchor: Anchor = "middle"
    real: Point | None = None


class PanelTrackName(Contract):
    """The track number mid-track, with the train number's box right after it (§3.4)."""

    name: Text
    cell: Cell
    train_number: Cell
    real: Point | None = None


class PanelTable(Contract):
    """The turntable: its centre and radius on the grid and in the drawing."""

    id: Name
    node: Name
    cell: Cell
    radius: float = Field(gt=0, description="I rutor, vågrätt.")
    real: Point | None = None
    real_radius: float | None = None


class PanelFunctionButton(Contract):
    """A panel function's button in the track plan, beside the node it belongs to: on the side
    the plan's `function_sides` says, else under the track (STV-04, STV-53)."""

    name: Text
    type: PanelFunctionType
    node: Name
    cell: Cell = Field(description="Knappens mitt.")
    side: LabelSide


class PanelField(Contract):
    """A part of a station too wide for the screen, on the same grid (STD-03)."""

    name: Text
    start: float
    end: float


class Panel(Contract):
    """The station on the grid: the engine's proposal or the panel built from the station's
    track plan. Columns grow to the east and rows downwards, in cells; a cell is `cell` wide
    and high in pixels."""

    source: PanelSource
    width: float = Field(description="I rutor.")
    height: float = Field(description="I rutor.")
    cell: tuple[float, float] = Field(description="Rutans bredd och höjd i bildpunkter.")
    angle: PanelAngle | None = Field(
        default=None, description="Motorns vinkel. Spårplanens: inget."
    )
    rows: int = Field(default=0, ge=0, description="Spårraderna, i motorns förslag.")
    shortened: bool = Field(default=False, description="Stationsspåren är kortade (STD-03).")
    fields: list[PanelField] = Field(
        default_factory=list, description="Fälten, när stationen inte får plats (STD-03)."
    )
    lines: list[PanelLine]
    nodes: list[PanelNode]
    switches: list[PanelSwitch] = Field(default_factory=list)
    signals: list[PanelSignal] = Field(default_factory=list)
    labels: list[PanelLabel] = Field(default_factory=list)
    track_names: list[PanelTrackName] = Field(default_factory=list)
    tables: list[PanelTable] = Field(default_factory=list)
    platforms: list[tuple[float, float, float, float]] = Field(default_factory=list)
    building: PanelBuilding | None = None
    functions: list[PanelFunctionButton] = Field(
        default_factory=list,
        description="Panelfunktionernas knappar i spårplanen, de som hör till en nod.",
    )
    real_box: tuple[float, float, float, float] | None = Field(
        default=None, description="Ritningens ram för den mjuka vyn: x, y, bredd, höjd i mm."
    )


# --- The station's model in Studio, and the reference stations (#83) -----------------------


class TklChecks(Contract):
    """The checks before the model may run (§6, STD-04)."""

    problems: list[Text] = Field(default_factory=list, description="Stoppar körningen.")
    notes: list[Text] = Field(default_factory=list, description="Visas men stoppar inte.")


class RouteKind(StrEnum):
    TRAIN = "train"  # tågväg
    SHUNTING = "shunting"  # växlingsväg


class TklRoute(Contract):
    """A route the engine derived: read-only, for showing on the panel (STD-07)."""

    kind: RouteKind
    start: Name
    end: Name
    pieces: list[Name]
    positions: dict[Name, Position] = Field(default_factory=dict)
    turntable: Name | None = None


class TklModelSummary(Contract):
    station_id: Id
    name: Text
    level: int = Field(ge=1, le=3)
    pieces: int = Field(ge=0)
    switches: int = Field(ge=0)
    levers: int = Field(ge=0)
    signals: int = Field(ge=0)
    track_circuits: int = Field(ge=0)
    station_tracks: list[Text] = Field(default_factory=list)
    line_exits: list[Name] = Field(default_factory=list)
    turntables: int = Field(default=0, ge=0)
    plan: bool = Field(description="Stationen har en egen spårplan (STD-25).")


class TklTrackPlan(Contract):
    """Spårplan i Studio: the model's summary, the checks, the routes and the panel."""

    summary: TklModelSummary
    checks: TklChecks
    routes: dict[RouteKind, int] = Field(description="Vägarna per slag.")
    route_list: list[TklRoute] = Field(default_factory=list)
    panel: Panel | None = Field(default=None, description="Inget när panelen inte går att bygga.")


class TklReference(Contract):
    """A reference station (TKL40): for trying, read-only."""

    id: Id
    name: Text
    level: int = Field(ge=1, le=3)
    plan: bool


# --- Ställverket at level 1–2 (#84): the interlocking's state and its operations -----------

TrainNumber = Annotated[str, StringConstraints(pattern=r"^[0-9A-Za-z]{1,8}$")]
"""A train number in the interlocking: digits and letters, as Drift writes it (41, 9103)."""


class TklAspect(StrEnum):
    """What a signal shows. A combined signal shows SHUNT with the dwarf part (STV-24)."""

    STOP = "stop"  # stopp
    PROCEED = "proceed"  # kör, för en tågväg
    SHUNT = "shunt"  # växling, för en växlingsväg
    LOCAL = "local"  # snett höger: växling i ett lokalt frigivet område (FR41, TKL44)


class TklSectionPart(Contract):
    """A section of a set route, in the order the route runs through it: a track circuit, or
    where the model has none, the pieces between two switches, signals or ends (spårdel). It
    is released behind the train, one at a time (STV-29)."""

    section: Name
    pieces: list[Name] = Field(description="Vägens spårbitar i delen, i färdriktningen.")
    released: bool = False


class TklSetRoute(Contract):
    """Lagd väg: a train route or shunting route the interlocking has set and locked."""

    id: int = Field(ge=1)
    kind: RouteKind
    start: Name
    end: Name
    chain: int | None = Field(
        default=None,
        description="Den sammansatta vägens första del, när vägen är en del av en (TKL53).",
    )
    sections: list[TklSectionPart] = Field(min_length=1)
    positions: dict[Name, Position] = Field(
        description="Växlarna vägen lägger: sina egna, de kopplade och de som dras med (TKL104)."
    )
    locked: dict[Name, Position] = Field(
        default_factory=dict, description="Växlarna vägen fortfarande låser."
    )
    protection: list[Name] = Field(
        default_factory=list,
        description="Växlar vägen låser utan att gå över dem, som spakens andra halva "
        "(skyddsväxlar, STV-20).",
    )
    crossings: list[Name] = Field(
        default_factory=list, description="Korsningar och korsningsväxlar vägen håller."
    )
    turntable: Name | None = Field(
        default=None, description="Vändskivans spår som bryggan står mot, medan vägen håller."
    )
    train: int | None = Field(default=None, description="Tåget som tar vägen, när det är känt.")
    at: int = Field(
        default=-1,
        ge=-1,
        description="Delen där tågets front är: -1 innan tåget har passerat starten.",
    )
    aspect: TklAspect = Field(description="Vad startsignalen visar för vägen just nu.")
    held: Text | None = Field(
        default=None,
        description="Vägen ligger kvar med sina lås men signalerna visar stopp, med skälet: "
        "signalstopp eller ett spår ur drift. Den visar kör igen först när den läggs på nytt.",
    )
    passed: list[Name] = Field(
        default_factory=list,
        description="Signaler i färdriktningen som visar vägens besked tills tåget har "
        "passerat dem (STV-19).",
    )
    leaves: Name | None = Field(
        default=None, description="Linjeutfarten vägen leder ut till: förbi målet är linjen."
    )
    enters: Name | None = Field(default=None, description="Linjeutfarten vägen kommer in från.")
    set_at: datetime


class TklTrain(Contract):
    """Ett tåg i ställverket: its number, if any, and where its front is. Without detection
    (level 1–2) the number follows the buttons (STV-15). On a section, or on the line outside
    an exit, on its way in."""

    id: int = Field(ge=1)
    number: TrainNumber | None = Field(default=None, description="Utan nummer: en växling.")
    call: Id | None = Field(default=None, description="Tågbesöket i hubbens bild, när det är känt.")
    section: Name | None = None
    exit: Name | None = Field(default=None, description="På linjen utanför linjeutfarten.")

    @model_validator(mode="after")
    def _one_place(self) -> TklTrain:
        if (self.section is None) == (self.exit is None):
            raise ValueError("Ett tåg står på ett spår eller på linjen vid en utfart.")
        return self


class TklSwitchShown(Contract):
    """A switch part as the panel shows it."""

    position: Position | None = Field(description="Okänt för en växel TKL inte lägger.")
    control: SwitchControl = SwitchControl.TKL
    routes: list[int] = Field(default_factory=list, description="Vägarna som låser växeln.")
    protection: bool = Field(
        default=False,
        description="Låst som skydd, av en väg som inte går över den eller av en lokal "
        "frigivning: kort gult vid knuten (STV-20, TKL44).",
    )
    local: bool = Field(
        default=False,
        description="Lokalt frigiven: läggs med knappen på modulen, inte av ställverket. Blått "
        "streck vid knuten (FR41, TKL44).",
    )
    function: Name | None = Field(
        default=None, description="Panelfunktionen som låser växeln eller friger den."
    )


class TklSignalShown(Contract):
    aspect: TklAspect = TklAspect.STOP
    end: bool = Field(default=False, description="Slutpunkt för en lagd väg: röd i 85 och 95.")
    blocked: bool = Field(
        default=False,
        description="Spärrad i stopp: i signalstopp, eller infartssignal till ett lokalt "
        "frigivet område (FR41). Fylld röd i 85 och 95.",
    )


class TklPieceState(StrEnum):
    TRAIN = "train"  # låst i en tågväg: grönt
    SHUNTING = "shunting"  # låst i en växlingsväg: gult
    OCCUPIED = "occupied"  # tåget står här: rött, före vägens färg
    LOCAL = "local"  # frigivet för växling (TKL44): blått i 85 och 95
    OUT_OF_SERVICE = "out_of_service"  # spår ur drift: streckat
    PROGRAMMING = "programming"  # programmeringsspår (STV-53): blått


class TklPieceShown(Contract):
    state: TklPieceState
    route: int | None = None


class TklNumberColour(StrEnum):
    RED = "red"  # där tåget är
    GREEN = "green"  # framför tåget, där tågvägen är lagd för det (STV-21)


class TklNumber(Contract):
    """Var ett tågnummer står (STV-06, STV-21): the section or the exit, its pieces, and the
    station track when the section is on one, where the track's name is hidden (STV-57)."""

    number: TrainNumber | None = None
    train: int = Field(ge=1)
    colour: TklNumberColour
    section: Name | None = None
    exit: Name | None = None
    pieces: list[Name] = Field(default_factory=list)
    track: Name | None = Field(default=None, description="Stationsspåret, med modellens namn.")
    route: int | None = None
    estimated: bool = Field(
        default=True,
        description="Numret följer knapparna, inte detekteringen: en uppskattad position.",
    )


class TklExitShown(Contract):
    """A line exit: the line's pieces outside the entry signal, which belong to the line and
    never turn green with a route (STV-54), and what goes up to Hubben as signal.exit."""

    exit: Name
    outside: Id = Field(description="Utfartens id i utsidan.")
    pieces: list[Name] = Field(default_factory=list)
    aspect: ExitSignalAspect = ExitSignalAspect.STOP


class TklHappening(Contract):
    at: datetime
    text: Text


class TklFunctionMode(Contract):
    """One of a function's positions: a traction current's mode, or a turntable's track."""

    value: Name
    label: Text


class TklFunctionShown(Contract):
    """A panel function from the catalogue (STV-04) with its state of the moment: what the
    panel draws and what is saved with the interlocking. The parameters are the model's."""

    name: Text = Field(description="Funktionens namn, som i stationsmodellen. Unikt i stationen.")
    type: PanelFunctionType
    on: bool = Field(
        default=False,
        description="Inkopplad: signalstopp, lokal frigivning, ur drift eller programmeringsspår.",
    )
    mode: Name | None = Field(
        default=None, description="Körströmmens läge, eller spåret vändskivans brygga står mot."
    )
    modes: list[TklFunctionMode] = Field(default_factory=list, description="Lägena att välja.")
    pieces: list[Name] = Field(
        default_factory=list, description="Spårbitarna funktionen gäller: området eller spåret."
    )
    signals: list[Name] = Field(
        default_factory=list, description="Signalerna i stopp, eller som visar växling."
    )
    blocked: list[Name] = Field(
        default_factory=list,
        description="Infartssignalerna som spärras medan området är lokalt frigivet (FR41).",
    )
    switches: list[Name] = Field(
        default_factory=list, description="De lokala växlarna, som läggs med knappar på modulerna."
    )
    locked: dict[Name, Position] = Field(
        default_factory=dict, description="Skyddsväxlarnas spakar och läget de låses i."
    )
    at: Name | None = Field(default=None, description="Noden knappen hör till i spårplanen.")
    codes: dict[Name, Text] = Field(
        default_factory=dict, description="Knappens kod per skal, till exempel L01 i 95."
    )
    note: Text | None = None


class TklInterlocking(Contract):
    """Ställverkets läge i stunden (STV-08): everything the panel draws, kept with the station
    so that a restart keeps it. Never the model, the clearance or the timetable (STV-09)."""

    station_id: Id
    level: int = Field(ge=1, le=3)
    model: str = Field(description="Stationsmodellens fingeravtryck: läget gäller den.")
    revision: int = Field(ge=0, description="Räknar upp vid varje ändring; väntan följer den.")
    problem: Text | None = Field(
        default=None,
        description="Läget gäller inte stationsmodellen: allt utom nollställning nekas.",
    )
    switches: dict[Name, TklSwitchShown] = Field(default_factory=dict)
    levers: dict[Name, Position | None] = Field(
        default_factory=dict, description="Spakarnas lägen; inget när spakens växlar ligger i kors."
    )
    turntables: dict[Name, Name | None] = Field(
        default_factory=dict, description="Spåret vändskivans brygga står mot."
    )
    routes: list[TklSetRoute] = Field(default_factory=list)
    trains: list[TklTrain] = Field(default_factory=list)
    signals: dict[Name, TklSignalShown] = Field(default_factory=dict)
    pieces: dict[Name, TklPieceShown] = Field(
        default_factory=dict, description="Spårbitar som inte är lediga."
    )
    numbers: list[TklNumber] = Field(default_factory=list)
    exits: list[TklExitShown] = Field(default_factory=list)
    tracks: dict[Name, Name] = Field(
        default_factory=dict,
        description="Sektionerna på stationsspåren, med spårets namn: där ett tåg kan sättas ut.",
    )
    sections: dict[Name, list[Name]] = Field(
        default_factory=dict,
        description="Sektionerna med sina spårbitar: där 59 har sina lampor, en till fyra per "
        "spårledning, och avbrotten mellan spårledningarna.",
    )
    functions: list[TklFunctionShown] = Field(
        default_factory=list,
        description="Panelfunktionerna ur katalogen, med sitt läge (STV-04, STV-53).",
    )
    events: list[TklHappening] = Field(default_factory=list, description="Senaste först.")
    last_id: int = Field(default=0, ge=0, description="Det senaste id:t för en väg eller ett tåg.")


class TklRouteAsk(Contract):
    """Lägg en väg: start och mål (STV-01). The goal may be several signals away (TKL53).
    Without a kind it is a train route where there is one, else a shunting route (STV-24)."""

    start: Name
    end: Name
    kind: RouteKind | None = None


class TklRouteRef(Contract):
    route: int = Field(ge=1)


class TklEmergencyRelease(Contract):
    """Nödutlösning: releases the route even with a train in it, when confirmed. Logged."""

    route: int = Field(ge=1)
    confirm: bool = False


class TklLeverAsk(Contract):
    """Klicka på en växel: lägg hela spaken (STV-01, STV-52). Without a position it is laid
    over to the other one."""

    switch: Name
    position: Position | None = None


class TklTrainPut(Contract):
    """Sätt ut ett tågnummer på ett spår eller på linjen vid en utfart. A train on its way here
    is put by its call; TKL finds its exit in Hubben's snapshot (STV-10)."""

    number: TrainNumber | None = None
    call: Id | None = None
    section: Name | None = None
    exit: Name | None = None


class TklTrainRef(Contract):
    train: int = Field(ge=1)


class TklReset(Contract):
    """Nollställ ställverket: every route released, the switches where they are. With trains,
    the train numbers go too. Confirmed and logged."""

    confirm: bool = False
    trains: bool = False


class TklFunctionAction(StrEnum):
    ON = "on"  # koppla in: signalstopp, lokal frigivning, ur drift, programmeringsspår
    OFF = "off"  # koppla ur
    SET = "set"  # välj läge: körströmmen, eller spåret vändskivan vrids mot
    LAY = "lay"  # en lokal växel lagd med knappen på modulen, medan området är frigivet
    RELEASE = "release"  # nödutlös spårledningarna, bekräftat


class TklFunctionAsk(Contract):
    """Manövrera en panelfunktion (STV-04): koppla in eller ur, välj läge, lägg en lokal växel
    eller nödutlös. The interlocking says yes, or no with the reason."""

    function: Text = Field(description="Funktionens namn.")
    action: TklFunctionAction
    value: Name | None = Field(default=None, description="Läget, spåret eller växeln.")
    confirm: bool = Field(default=False, description="Nödutlösningen är bekräftad.")


class TklReportKind(StrEnum):
    DEPARTED = "departed"  # avgång, train.departed
    ARRIVED = "arrived"  # ankomst, train.arrived, eller spårbyte, train.track.change
    EXIT_SIGNAL = "exit_signal"  # utfartssignalens besked, signal.exit


class TklReport(Contract):
    """Vad ställverket rapporterar upp till Hubben (STV-10), and how it went."""

    kind: TklReportKind
    train_number: TrainNumber | None = None
    call: Id | None = None
    exit: Id | None = Field(default=None, description="Utfartens id i utsidan.")
    track: Id | None = Field(default=None, description="Stationsspårets id i utsidan.")
    aspect: ExitSignalAspect | None = None
    action: Action | None = Field(default=None, description="Kommandot som skickades.")
    sent: bool = False
    accepted: bool | None = None
    message: Text | None = None


class TklAnswer(Contract):
    """Ja, eller nej med skälet: the interlocking's answer to every operation (STV-43)."""

    accepted: bool
    message: Text
    route: int | None = Field(default=None, description="Den första vägen som lades.")
    state: TklInterlocking
    reports: list[TklReport] = Field(default_factory=list)


class TklTarget(Contract):
    """A goal from a start, for choosing and for showing the way before it is set."""

    end: Name
    kind: RouteKind
    via: list[Name] = Field(default_factory=list, description="Signalerna emellan (TKL53).")
    pieces: list[Name] = Field(default_factory=list)
    possible: bool
    reason: Text | None = None
    route: int | None = Field(default=None, description="Vägen, när den redan är lagd.")


class TklTargets(Contract):
    start: Name
    kinds: list[RouteKind] = Field(
        default_factory=list,
        description="Vägslagen från starten, tågväg först: ett klick till byter till "
        "växlingsväg (STV-24).",
    )
    targets: list[TklTarget] = Field(default_factory=list)


class TklWait(Contract):
    """Svaret på väntan: ställverket har ändrats efter after, eller tiden gick ut."""

    revision: int = Field(ge=0)
    changed: bool
