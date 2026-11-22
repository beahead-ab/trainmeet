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

Level 3 (#85): LocoNet, only in a local TKL, through a LocoBuffer USB or a BTLocoBridge
(STV-11, STV-27). Studio's Koppla in, under /api/tkl/1/studio/koppla-in, connects to the layout,
shows the MGP cards with module and channel (STUDIO-11, STUDIO-18) and learns the addresses by
touching (STUDIO-04): every switch, signal and track circuit is grey, yellow, green or Utan
adress (STUDIO-17). The pretend LocoNet stands in for the layout, "LocoNet ej ansluten", which
Prova uses (STUDIO-21, STUDIO-24). With LocoNet the interlocking waits for the switches' feedback,
the track circuits move the train numbers, and only green and Utan adress objects run (STV-15 –
STV-17).

Rita (#85): the owner draws the station on the grid in Studio, or redraws the panel of one that
has a model, under /api/tkl/1/studio/rita. The drawing is the station model with its panel plan;
it is kept as a draft, problems and all, until the owner takes it into use, and then it is the
station's model like an imported one (STUDIO-02, STUDIO-30).

Ladda upp ritning (#89 del c4), under /api/tkl/1/studio/ritning: TKL sends the drawing to
TrainMeet CAD's image chain with the person's access token from TrainMeet ID and passes CAD's
answer on (TklUpload, with contracts.cad.DrawingJob): the pages and the price, the questions with
the legend first, the answers, and the straightened drawing. Förslaget turns the read into Rita's
draft by the standard interlocking, everything assumed and yellow until the owner confirms it
(TKL27); the engine lays out the panel (TKL81). Without CAD's address (TKL_CAD) or a login with ID
the way in is grey, with the reason, and Rita still works (CAD6).

Studio's Prova (#85 del c), under /api/tkl/1/studio/prova: TKL's simulator runs a train through
every train route and every shunting route of the station's model, one at a time from a clean
state, in the background (STUDIO-05, STUDIO-21, STUDIO-27). At level 3 against the pretend
LocoNet, at level 1–2 with Kör. When every route has passed the station is Klart, until the model
changes. With LocoNet connected to the layout, Provkör sets each route on the real layout and
asks the owner. Prova connects only to a preview run in the hub, never to a real meet
(STUDIO-12).

Stream Deck (#86 del a), under /api/tkl/1/deck: the interlocking in the hand. Every Elgato model
is a grid of keys, with dials, a touch strip, an info line or pedals where it has them (SD52,
SD53). A profile is data, never code (SD5): the modes Tågen, Platser and Spårplan, each with its
pages of keys from a fixed catalogue (SD4, SD63), computed from the station model for the grid
(SD32, SD39). The deck's logic presses, holds, turns and touches; it calls the interlocking's
functions and shows its yes or no (SD1). What every key shows is a face with the locked colours
(SD3), the same for the deck on the screen and for a real deck.

Stream Deck (#86 del b): a real deck. A local TKL owns its decks over USB, so that a deck works
without an open tab and in every browser; TKL in the cloud never opens USB, and there Chrome and
Edge drive a deck with WebHID (SD50). Both draw the same pictures: TKL's server draws every key,
the touch strip and the info line as PNG at the deck's own size, from the same faces as the deck
on the screen. TKL is locked for the whole station with Lås, in TKL or on a deck, and opened with
the PIN; then every deck shows only the clock (SD30). A model counts as tried only after a real
deck of it has been tried; until then it is Inte provad (SD58).

Stream Deck (#87 del d): a deck opens as the tågklarerare or as a part of the station (its
role). A part's deck has the mode Bangård, the shunter's deck: the part's tracks, where a press
lays the switch street from the chosen end, its routes out, requested from the station, and
Ände, Lämna, Klart, Ring and the train key for Klart att skicka (SD60, SD61, SD74, SD86, SD87).

Fjärrstyrning (#36 del c), under /api/tkl/1/fjarr: TKL started in the remote role is a remote
interlocking with no station of its own (FR1, TKL47), and a station's own TKL controls a
neighbour with the same fjärrbild (FR3). The fjärrbild is Hubben's Overview, drawn in the skin 95
(FR31–FR38, FR47, FR48); routes from the stations' remote catalogues are asked for and taken away,
and the controlled stations are cleared, with ordinary station commands (FR11–FR14, FR17).

Fjärrstyrning, the station's side (#36 del b): Studio, Inställningar, Fjärrstyrning, under
/api/tkl/1/studio/fjarrstyrning, where the owner chooses which of the station's train routes may
be requested from afar, sets up the station automats and says who may receive the station
(FR10, FR24, FR40); kept with the model and versioned with it, and level 0 has none (FR16). The
interlocking keeps who laid each catalogue route, the automats that are on and the magazine
(FR24–FR27, FR45), and while the station is remote-controlled its own panel lays nothing (FR6,
FR17); the station automats are switched on the spot with /api/tkl/1/stallverk/automat.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from contracts.cad import DrawingJob, StudioSource, StudioSourceKind
from contracts.common import Contract, Id, Text, TimeOfDay
from contracts.station import (
    Action,
    ApprovalStatus,
    ExitSignalAspect,
    MeetContext,
    MessageId,
    OfferHere,
    Overview,
    Revision,
    RouteBy,
    Snapshot,
)
from contracts.station_model import (
    BorderSwitch,
    Cell,
    FeedbackType,
    Name,
    NodeType,
    PanelBuilding,
    PanelFunctionType,
    PartRules,
    PartSide,
    Point,
    Position,
    RouteOut,
    SignalType,
    StationModel,
    StationPart,
    SwitchControl,
    SwitchStreet,
    SwitchType,
)
from contracts.station_outside import AutomatKind, ReceiverKind, RouteDirection, StationOutside

# "Minst fyra siffror" (TKLAPP, first start). Never written to a log.
TKL_PIN = Field(pattern=r"^[0-9]{4,12}$", description="4–12 siffror. Skrivs aldrig ut.")
LEVEL_0: Final = 0


class TklMode(StrEnum):
    LOCAL = "local"  # on the station's computer or a Pi: one station
    CLOUD = "cloud"  # TKL i molnet: the station belongs to the account in TrainMeet ID (TKL5)


class TklStation(Contract):
    station_id: Id = Field(description="Stationens id: kort namn, skapat vid första start.")
    name: Text
    level: int = Field(default=LEVEL_0, ge=0, le=3)
    tried: bool = Field(
        default=False,
        description="Klart i Prova i Studio: varje väg i stationsmodellen gick igenom, och "
        "modellen har inte ändrats sedan (STUDIO-05).",
    )


class TklState(Contract):
    """What the web app needs before anything else: is TKL set up, and is it unlocked."""

    mode: TklMode
    software: Text
    set_up: bool
    unlocked: bool
    station: TklStation | None = None
    locked: bool = Field(
        default=False,
        description="Hela stationen är låst (SD30): med Lås i TKL eller på ett deck. Varje "
        "deck visar bara klockan, och PIN-koden låser upp.",
    )
    remote: TklRemote | None = Field(
        default=None,
        description="TKL körs som fjärrställverk, utan egen station (FR1, TKL47, #36 del c).",
    )
    login: bool = Field(
        default=False,
        description="TKL i molnet loggar in med TrainMeet ID i stället för första start och PIN: "
        "stationen hör till kontot och öppnas ur Hubbens Synk (TKL5, TKLMOLN-01, TKLMOLN-10).",
    )
    account: TklAccount | None = Field(
        default=None,
        description="Kontot som är inloggat i den här webbläsaren, i TKL i molnet.",
    )


class TklAccount(Contract):
    """TKL i molnet (TKL5, TKLMOLN-07): kontot i TrainMeet ID som är inloggat, och versionen i
    Synk som den öppna stationen bygger på. TKL håller bara en arbetskopia; stationspaketet ägs
    av stationsägaren och ligger i Synk (TKLMOLN-05)."""

    person: Text = Field(description="Namnet i ID. Aldrig adressen.")
    base: int | None = Field(
        default=None, ge=1, description="Versionen i Synk som arbetskopian bygger på."
    )
    changed: bool = Field(
        default=False, description="Arbetskopian har ändringar som inte är sparade i molnet."
    )


class TklCloudStation(Contract):
    """En station i Dina stationer: den senaste versionen i Synk."""

    station_id: Id
    name: Text
    version: int = Field(ge=1)
    saved: datetime


class TklCloudStations(Contract):
    """Dina stationer (TKLMOLN-02): stationspaketen som kontot äger i Hubbens Synk."""

    stations: list[TklCloudStation] = Field(default_factory=list)
    open: Id | None = Field(
        default=None, description="Stationen som är öppen i den här webbläsaren."
    )


class TklNewStation(Contract):
    """Ny station i TKL i molnet: namnet och det korta namnet. Version 1 sparas i Synk direkt."""

    name: str = Field(min_length=1, max_length=40)
    station_id: Id


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
    prova: bool = Field(
        default=False,
        description="Från Prova: bara en provkörning i Provbanan, med dess kod, aldrig en riktig "
        "träff (STUDIO-12). Gäller också när låtsas-LocoNet är ansluten.",
    )


class TklConnection(Contract):
    """How TKL stands with the hub. The key is never part of it."""

    connected: bool
    address: Text | None = None
    hub_name: Text | None = None
    status: ApprovalStatus | None = None
    places: list[Id] = Field(default_factory=list)
    # #87 del b: a station with parts that are their own driftplatser (TKL101, TRAFIK-35).
    place: Id | None = Field(
        default=None, description="Stationens egen driftplats, när den är godkänd."
    )
    parts: list[TklPartPlace] = Field(
        default_factory=list,
        description="Delarnas driftplatser, var och en med trafikledningens svar.",
    )
    outside_version: int | None = Field(default=None, description="Utsidan som följde med.")
    message: Text | None = None
    preview: bool = Field(
        default=False, description="En provkörning i Provbanan, inte en riktig träff (STUDIO-12)."
    )
    relayed: bool = Field(
        default=False,
        description="Genom molnhubbens relä till Pi:n som leder träffen (TKLMOLN-03, SYNK-11).",
    )


class TklMeetWay(StrEnum):
    """Hur TKL i molnet når en träff (TKLMOLN-03, TKLMOLN-06)."""

    HERE = "here"  # molnhubben kör träffen: direkt till den
    RELAY = "relay"  # en Pi leder träffen: genom molnhubbens relä
    NONE = "none"  # träffen körs inte just nu
    PREVIEW = "preview"  # Provbanan på molnhubben, med provkörningens kod (TKLMOLN-11)


class TklMeet(Contract):
    """En träff att ansluta till i TKL i molnet: kontots träffar enligt rollerna i ID, och
    Provbanan. Adressen är molnhubbens, eller dess relä till Pi:n; aldrig Pi:ns egen."""

    meet: Id | None = Field(default=None, description="Hubbens träff; tomt för Provbanan.")
    name: Text
    club_name: Text | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    way: TklMeetWay
    hub_name: Text | None = Field(default=None, description="Hubben som leder träffen.")
    address: Text | None = Field(default=None, description="Där TKL ansluter, med koden.")


class TklMeets(Contract):
    meets: list[TklMeet] = Field(default_factory=list)
    message: Text | None = Field(
        default=None, description="Varför kontots träffar inte går att läsa just nu."
    )


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
    bound: bool = Field(
        default=False,
        description="TKL i molnet: stationen hör till kontot, och Spara i molnet är hur den "
        "sparas (TKL5). Arbetskopian i TKL är bara en kopia.",
    )
    changed: bool = Field(default=False, description="Ändringar som inte är sparade i molnet än.")


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


# --- Rita in Studio (#85): the station drawn on the grid (STUDIO-02, STUDIO-30) -------------


class TklDrawing(Contract):
    """Rita: the station as the owner draws it, the station model with its panel plan.

    The panel plan is the drawing (STD-25, TKL81): every switch, crossing and track end in a
    cell, every track a way over the grid from node to node, horizontally, vertically or at
    45°, with the joints between its pieces. The six objects stand on it: the tracks' pieces,
    the switches, the signals, the track-circuit boundaries, the buffer stops and the line exits
    (STUDIO-02). What is not drawn is computed when the drawing becomes the model: the nodes'
    types, the track circuits between the boundaries, the signals that lead out at each exit,
    and where the panel shows the signals, the exits and the track names (tkl/studio/rita.py).
    The routes are never drawn (STD-07).

    A station without a plan of its own opens on the engine's layout, the first proposal
    (STD-09). While the owner has only named things on it, the proposal is not kept as a plan,
    and the engine lays the panel out again."""

    model: StationModel
    proposal: bool = Field(
        default=False,
        description="Rutnätet är motorns förslag och sparas inte som spårplan förrän ägaren "
        "ritar om det.",
    )


class TklDrawingState(StrEnum):
    NEW = "new"  # ingen ritning och ingen stationsmodell än
    DRAFT = "draft"  # ett utkast, sparat på datorn, som inte är stationens modell
    IN_USE = "in_use"  # ritningen är stationens modell, den Ställverket kör


class TklObjectKind(StrEnum):
    """What a finding is about, to select it in the drawing (RS7)."""

    NODE = "node"
    PIECE = "piece"
    SWITCH = "switch"  # med växelns nummer
    SIGNAL = "signal"
    CIRCUIT = "circuit"
    LEVER = "lever"
    EXIT = "exit"


class TklObjectRef(Contract):
    kind: TklObjectKind
    id: Name = Field(description="Nodens eller spårbitens id, växelns nummer eller namnet.")


class TklFinding(Contract):
    """A problem, which stops the drawing from being used, or a note, which does not, with the
    object it is about when it names one (RS7)."""

    text: Text
    problem: bool
    target: TklObjectRef | None = None


class TklRita(Contract):
    """Rita i Studio: the drawing, the model it becomes, the checks and the routes.

    Saving keeps a draft, problems and all. Använd ritningen makes it the station's model only
    without problems, as an import (STD-04); the outside is then derived from it (TKL92) and
    the interlocking gets it, never under set routes or train numbers."""

    drawing: TklDrawing
    state: TklDrawingState
    model: StationModel = Field(description="Stationsmodellen som ritningen blir.")
    loose: list[Name] = Field(
        default_factory=list,
        description="Noderna där ett spår slutar utan att nå något: röda punkter (RS7).",
    )
    findings: list[TklFinding] = Field(
        default_factory=list, description="Kontrollernas problem först, sedan det att veta."
    )
    routes: dict[RouteKind, int] = Field(description="Vägarna per slag.")
    route_list: list[TklRoute] = Field(default_factory=list)


class TklUpload(Contract):
    """Ladda upp ritning i Studio (#89 del c4, STUDIO-01, STUDIO-03, CAD6): whether the way in is
    open here and why not, and the drawing being read, as TrainMeet CAD answers it. TKL asks
    CAD for the person with the person's access token from ID; a local TKL without internet or
    without a login with ID can only Rita. The underlay comes through TKL, at underlay."""

    available: bool
    reason: Text | None = Field(default=None, description="Varför vägen in är grå.")
    job: DrawingJob | None = None
    underlay: str | None = Field(
        default=None, description="TKL:s egen adress till den uträtade ritningen."
    )


# --- Från CAD in Studio (#89 del d2, STUDIO-01, STUDIO-03, CAD-15, CAD-20) ------------------


class TklCadImage(Contract):
    """A module's measuring image from TrainMeet CAD, kept with the station so that Foto shows it
    without internet (#89 del d4, CAD-13, CAD-33). matrix, SVG's (a, b, c, d, e, f), takes the
    image's pixels ((0, 0) its top left corner, y down) to the station's real geometry in mm,
    which is the source's in CAD (contracts.cad.StudioImage.to_source); outline is the board,
    which the image is clipped to."""

    module: UUID
    version: int = Field(ge=1)
    job: UUID = Field(description="The photo it came from: a new photo is a new image.")
    title: Text = Field(max_length=120, description='"M-002 Linje".')
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    matrix: list[float] = Field(min_length=6, max_length=6)
    outline: list[Point] = Field(min_length=3)
    bytes: int = Field(ge=0)
    url: str | None = Field(
        default=None, description="TKL:s egen adress till bilden, i TklImageUnder."
    )


class TklCadLink(Contract):
    """The group of modules in TrainMeet CAD a station's track plan comes from: an assembly or a
    single module, at a revision. registered: CAD knows the station uses it (Används i)."""

    kind: StudioSourceKind
    id: UUID
    name: Text = Field(max_length=80)
    revision: int = Field(ge=1)
    registered: bool = False
    modules: dict[str, Text] = Field(
        default_factory=dict,
        description='Its modules by id, as the owner sees them: "M-002 Linje". A re-import says '
        "which module a piece that is gone was on.",
    )
    images: list[TklCadImage] = Field(
        default_factory=list,
        description="The modules' measuring images for Foto, kept with the station (part d4).",
    )
    missing: list[Text] = Field(
        default_factory=list,
        description='The modules without one, and why: "M-002 Linje: Modulen är inte fotad …".',
    )
    gauge: float | None = Field(
        default=None, gt=0, description="The source's gauge in mm, for the rails over the images."
    )


class TklCadPiece(Contract):
    """A track piece in a re-import's difference, by CAD's id, and what the owner sees of it."""

    id: Name
    text: Text = Field(description='"Linje 1500 (M-002), spår 1".')


class TklCadDiff(Contract):
    """Skillnaden (STUDIO-03): what an import from CAD changes in the station's track plan, by
    CAD's ids, which never change (CAD-20). The owner's additions on pieces whose ids are kept
    stay; what hung on a piece that is gone does not follow, and is listed in lost."""

    first: bool = Field(description="The first import from this source: everything is new.")
    added: list[TklCadPiece] = Field(default_factory=list)
    removed: list[TklCadPiece] = Field(default_factory=list)
    moved: list[TklCadPiece] = Field(
        default_factory=list, description="Same id, another shape or place: yellow again."
    )
    kept: list[Text] = Field(default_factory=list, description="The owner's additions kept.")
    lost: list[Text] = Field(
        default_factory=list, description="The owner's additions on pieces that are gone."
    )
    replaced: bool = Field(
        default=False, description="The station's own drawing, not from this source, is replaced."
    )
    panel: bool = Field(
        default=False, description="The owner's panel plan is kept; false: the engine lays it out."
    )


class TklFromCad(Contract):
    """Från CAD i Studio: whether the way in is open here and why not, the person's assemblies and
    approved modules in TrainMeet CAD, and the one the station is linked to. TKL asks CAD for the
    person with the person's access token from ID, as Ladda upp ritning; CAD never makes a
    station (TKL8, CAD-15)."""

    available: bool
    reason: Text | None = Field(default=None, description="Varför vägen in är grå.")
    sources: list[StudioSource] = Field(default_factory=list)
    link: TklCadLink | None = Field(default=None, description="The station's, in use.")
    pending: TklCadLink | None = Field(
        default=None, description="The draft's, until Använd ritningen."
    )


class TklCadImport(Contract):
    """Gör förslaget: Rita's draft from the source's track graph, everything new or moved yellow
    until the owner confirms it, and the difference against what the station had."""

    rita: TklRita
    diff: TklCadDiff
    link: TklCadLink


class TklImageUnder(Contract):
    """Mätbilden under i Foto (#89 del d4, CAD8, CAD-33): the modules' measuring images from
    TrainMeet CAD for a station that came from CAD, kept with the station, and the station's
    choice to draw them under the tracks in Foto. The choice is the station's, the same on every
    screen, off by default; it sends no order (STV-18). Grey with the reason when the station
    has no images to show."""

    available: bool
    reason: Text | None = Field(default=None, description="Varför Mätbilden under är grå.")
    on: bool = Field(description="The station's choice; drawn only while available.")
    images: list[TklCadImage] = Field(default_factory=list)
    missing: list[Text] = Field(default_factory=list, description="Modules drawn as vectors.")
    gauge: float | None = Field(
        default=None,
        gt=0,
        description="The gauge in mm of the source's scale: Foto draws its rails at it over the "
        "images, which show the real ones.",
    )
    bytes: int = Field(ge=0, description="What the images take with the station.")
    limit: int = Field(ge=0, description="The most a station keeps, in bytes.")


class TklImageUnderChoice(Contract):
    """The station's choice: Mätbilden under in Foto, or not."""

    on: bool


# --- Manöver: the owner's free panel (STV-46, TKL86) ---------------------------------------


class ManoverSymbols(StrEnum):
    """The standard skin Manöver takes its symbols and colours from, so that the same symbol
    means the same thing on every station (STV-46)."""

    SKIN_59 = "59"
    SKIN_85 = "85"
    SKIN_95 = "95"


OwnerLabel = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=24, pattern=r"^[^\x00-\x1f]+$"
    ),
]
"""The owner's own label for a track, a signal or a switch: one short line."""

MAX_LABELS: Final = 1000
"""The most labels of one kind a station keeps."""


class TklManoverShown(Contract):
    """What Manöver shows, each on or off. Everything is shown until the owner turns it off."""

    track_names: bool = Field(default=True, description="Spårnamnen.")
    switch_numbers: bool = Field(default=True, description="Växelnumren.")
    signal_ids: bool = Field(default=True, description="Signalernas id.")
    train_numbers: bool = Field(default=True, description="Tågnumren.")
    functions: bool = Field(default=True, description="Raden Panelens knappar.")


class TklManoverLabels(Contract):
    """The owner's labels in Manöver: what is shown for a track, a signal or a switch. The ids
    stay as they are, so a click still asks the interlocking with the id."""

    tracks: dict[Text, OwnerLabel] = Field(
        default_factory=dict,
        max_length=MAX_LABELS,
        description="Spårnamnet i panelen och ägarens etikett för det.",
    )
    signals: dict[Name, OwnerLabel] = Field(
        default_factory=dict,
        max_length=MAX_LABELS,
        description="Signalens id och ägarens etikett för den.",
    )
    switches: dict[Name, OwnerLabel] = Field(
        default_factory=dict,
        max_length=MAX_LABELS,
        description="Växelnumret i panelen och ägarens etikett för det.",
    )


class TklManover(Contract):
    """Manöver, the owner's free panel (STV-46, TKL86): the station's own panel, from its track
    plan when it has one, else the engine's layout, with the symbols and colours of one of the
    standard skins 59, 85 or 95, the owner's labels and what is shown. The states and the logic
    follow the chosen standard skin. Station settings, the same on every screen: kept with the
    station and versioned with its model. Every label must name something on the panel."""

    symbols: ManoverSymbols = Field(
        default=ManoverSymbols.SKIN_85, description="Standardskalet som symbolerna hämtas ur."
    )
    shown: TklManoverShown = Field(default_factory=TklManoverShown)
    labels: TklManoverLabels = Field(default_factory=TklManoverLabels)


# --- Fjärrstyrning, stationens sida (#36 del b, TKL46–TKL48, FR10, FR16, FR20–FR29, FR39–FR45) --


class TklRemoteCandidate(Contract):
    """A train route that may be in the remote catalogue (FR10): in from a line end to a
    station track, or out from a station track to a line end, through the signals between where
    it must be (TKL53). Studio lists them from the model; shunting routes never are."""

    id: Id = Field(description="Tågvägens fasta id i stationen, som i fjärrkatalogen.")
    start: Name
    end: Name
    via: list[Name] = Field(
        default_factory=list, description="Signalerna mellan, när vägen läggs genom flera."
    )
    exit: Id = Field(description="Utfartens id i utsidan.")
    exit_name: Text = Field(description="Utfarten som stationsmodellen kallar den.")
    track: Id = Field(description="Stationsspårets id i utsidan.")
    track_label: Text
    direction: RouteDirection
    chosen: bool = Field(default=False, description="I fjärrkatalogen.")


class TklAutomatSpec(Contract):
    """A station automat as the owner sets it up (FR24, FR39, FR40): A1, A2 and A3 for the
    whole station, AN and AU for the entry signals of the down and up track, and a local release
    automat for one of the station's local release functions."""

    code: Text = Field(
        min_length=1, max_length=12, description="Koden vid stationsnamnet: A3, AN21 eller L01."
    )
    kind: AutomatKind
    signals: list[Name] = Field(
        default_factory=list,
        description="Infartssignalerna automaten sköter, för AN och AU. Tomt: alla.",
    )
    function: Text | None = Field(
        default_factory=lambda: None, description="Panelfunktionen, för en lokalfrigivningsautomat."
    )
    default: bool = Field(
        default=False, description="Förvald: kopplas in efter 90 sekunder utan kontakt (FR29)."
    )


class TklFjarrChoice(Contract):
    """Studio, Inställningar, Fjärrstyrning: the owner's choice, kept with the station's model
    and versioned with it like Manöver's settings. Level 0 has none (FR16)."""

    routes: list[Id] = Field(
        default_factory=list, description="Fjärrkatalogen: de valda tågvägarnas id."
    )
    automats: list[TklAutomatSpec] = Field(default_factory=list)
    receivers: list[ReceiverKind] = Field(
        default_factory=list,
        description="Vilka som får ta emot stationen. Tomt: grannar och fjärrställverk.",
    )


class TklFjarrStudio(Contract):
    """The page in Studio: the owner's choice, the routes to choose from, the automats
    suggested, what is wrong, and the outside the choice gives."""

    settings: TklFjarrChoice
    kept: bool = Field(description="Ägaren har sparat ett val; annars är det förslaget.")
    level: int = Field(ge=0, le=3)
    candidates: list[TklRemoteCandidate] = Field(default_factory=list)
    entry_signals: list[Name] = Field(
        default_factory=list, description="Infartssignalerna, att välja för AN och AU."
    )
    functions: list[Text] = Field(
        default_factory=list, description="Stationens panelfunktioner för lokal frigivning."
    )
    suggested: list[TklAutomatSpec] = Field(
        default_factory=list, description="Förslaget ur stationens tågvägar och modell."
    )
    problems: list[Text] = Field(default_factory=list)
    outside: StationOutside | None = Field(
        default=None, description="Utsidan med fjärrkatalogen, automaterna och översikten."
    )
    note: Text | None = Field(default=None, description="Varför stationen inte har någon katalog.")


class TklAutomatOn(Contract):
    """A station automat switched on in the station's interlocking (FR24–FR27): who switched it,
    and for A1, A2, AN and AU the trains it has taken in and laid out."""

    code: Text = Field(max_length=12)
    kind: AutomatKind
    by: RouteBy
    since: datetime
    trains: list[Id] = Field(default_factory=list, description="Tågbesöken den har tagit in.")
    out: list[Id] = Field(default_factory=list, description="Tågbesöken den har lagt ut.")


class TklMagazined(Contract):
    """A route in the magazine (magasinering, FR45): it conflicts with a set route, and is laid
    by itself once that route is released, after a delay so that the train is wholly in."""

    route: Id = Field(description="Tågvägens id i fjärrkatalogen.")
    start: Name
    end: Name
    automat: Text = Field(max_length=12)
    call: Id | None = None
    since: datetime
    blocked_by: list[int] = Field(default_factory=list, description="Vägarna den krockar med.")
    free_since: datetime | None = Field(default=None, description="När de vägarna var lösta.")


class TklFjarrState(Contract):
    """The station's remote control in its interlocking (#36 del b): who controls it, the
    automats that are on and the magazine. Kept with the interlocking."""

    controller: Text | None = Field(
        default_factory=lambda: None,
        description="Fjärrstyrs från …: stationens egen panel lägger då inget (FR6, FR17).",
    )
    automats: list[TklAutomatOn] = Field(default_factory=list)
    magazine: list[TklMagazined] = Field(default_factory=list)


class TklAutomatAsk(Contract):
    """Koppla in eller ur en stationsautomat på platsen, när stationen är bemannad (FR25)."""

    code: Text = Field(max_length=12)
    on: bool


# --- Ställverket at level 1–2 (#84): the interlocking's state and its operations -----------

TrainNumber = Annotated[str, StringConstraints(pattern=r"^[0-9A-Za-z]{1,8}$")]
"""A train number in the interlocking: digits and letters, as Drift writes it (41, 9103)."""


class TklAspect(StrEnum):
    """What a signal shows. A combined signal shows SHUNT with the dwarf part (STV-24)."""

    STOP = "stop"  # stopp
    PROCEED = "proceed"  # kör, för en tågväg
    SHUNT = "shunt"  # växling, för en växlingsväg
    LOCAL = "local"  # snett höger: växling i ett lokalt frigivet område (FR41, TKL44)


class AddressState(StrEnum):
    """An object's four states in Koppla in (STUDIO-17, TKL26)."""

    GREY = "grey"  # grått: ej kopplat, ingen adress
    YELLOW = "yellow"  # gult: adressen är angiven men inte bekräftad på banan
    GREEN = "green"  # grönt: bekräftat på banan
    WITHOUT = "without"  # Utan adress: valt för manuella växlar och virtuella signaler


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
    waiting: list[Name] = Field(
        default_factory=list,
        description="Nivå 3: växlarna vägen väntar på återrapport från. Signalen visar stopp "
        "tills alla ligger rätt.",
    )
    waiting_since: datetime | None = Field(
        default=None, description="Nivå 3: när ordern till växlarna gick ut."
    )
    came_from: Name | None = Field(
        default=None,
        description="Nivå 3: sektionen tåget kom från, som ska bli fri innan vägen löses ut "
        "efter passage (STV-16).",
    )
    part: Id | None = Field(
        default=None,
        description="Delställverket vägen tillhör: lagd av delen, eller en godkänd begäran "
        "(TKL97).",
    )
    request: int | None = Field(
        default=None,
        description="Begäran vägen lades för. Envägsregeln: delen lämnar tillbaka den, och "
        "stationen löser inte ut den (RANG-09).",
    )
    # Fjärrstyrning (#36 del b): a route of the remote catalogue, and who laid it (FR33). Made
    # by factories, so that the schema gives no default and a client may leave them out.
    catalogue: Id | None = Field(
        default_factory=lambda: None, description="Tågvägens id i fjärrkatalogen."
    )
    by: RouteBy | None = Field(
        default_factory=lambda: None,
        description="Den som fjärrstyr eller en automat; tomt: på platsen.",
    )
    request_id: Id | None = Field(
        default_factory=lambda: None, description="Fjärrbegäran vägen lades för."
    )
    automat: Text | None = Field(
        default_factory=lambda: None, description="Automaten som lade den."
    )
    call: Id | None = Field(
        default_factory=lambda: None,
        description="Tågbesöket vägen lades för, i hubbens bild. Kommer ankomsten från Hubben "
        "löser stationen ut vägen in där den inte själv kan se passagen (beslut 22 november), "
        "och kommer avgången löser den utan LocoNet ut vägen ut (FR15).",
    )


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
    state: AddressState | None = Field(
        default=None,
        description="Nivå 3: grått, gult, grönt eller Utan adress, som syns i panelen (STV-17).",
    )
    reported: Position | None = Field(
        default=None,
        description="Nivå 3 med LocoNet: läget växeln har rapporterat. Inget medan den går.",
    )


class TklSignalShown(Contract):
    aspect: TklAspect = TklAspect.STOP
    state: AddressState | None = Field(
        default=None,
        description="Nivå 3: grått, gult, grönt eller Utan adress, som syns i panelen (STV-17).",
    )
    reported: TklAspect | None = Field(
        default=None, description="Nivå 3: beskedet som kortet har rapporterat."
    )
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
    by: Text | None = Field(
        default=None,
        description="Vem som gjorde det: delställverkets namn eller Tågklareraren (RANG-05).",
    )


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


class TklFieldMode(StrEnum):
    LOCONET = "loconet"  # LocoNet ansluten: banan
    PRETEND = "pretend"  # LocoNet ej ansluten: låtsas-LocoNet, som Prova använder (STUDIO-21)


class TklField(Contract):
    """Ställverket på nivå 3 med LocoNet: what the layout has reported, and what TKL has
    ordered. Unknown is None: nothing counts as free or in place until it is reported."""

    mode: TklFieldMode
    since: datetime = Field(description="När LocoNet anslöts.")
    switches: dict[Name, Position | None] = Field(
        default_factory=dict, description="Växeldelarnas återrapporterade lägen."
    )
    sections: dict[Name, bool | None] = Field(
        default_factory=dict, description="Spårledningarnas beläggning: true är belagd."
    )
    signals: dict[Name, TklAspect | None] = Field(
        default_factory=dict, description="Signalernas rapporterade besked."
    )
    ordered_switches: dict[Name, Position | None] = Field(
        default_factory=dict, description="Lägena TKL senast beordrade."
    )
    ordered_signals: dict[Name, TklAspect] = Field(
        default_factory=dict, description="Beskeden TKL senast beordrade."
    )


# --- Delställverk (#87, TKL97–TKL103): the parts' state, both screens' -----------------------

PART_REFUSALS: Final = 10
"""How many of a part's refusals are kept, the last first."""


class TklPartRequestState(StrEnum):
    WAITING = "waiting"  # begärd: väntar på svar från stationen
    APPROVED = "approved"  # godkänd: vägen ligger och är delens tills den lämnas tillbaka


class TklPartRequest(Contract):
    """Begäran (TKL98, RANG-03): a route out that a part has asked the station for."""

    id: int = Field(ge=1)
    part: Id
    route_out: Name = Field(description="Den begärda vägens id i delen.")
    said: Text = Field(
        description="Som rutan säger den: spåret delen kommer från och spåret ut, till exempel "
        "52 → 3, eller vägens namn."
    )
    start: Name
    end: Name
    state: TklPartRequestState
    route: int | None = Field(default=None, description="Den lagda vägen, när den är godkänd.")
    asked: datetime
    answered: datetime | None = None


class TklPartRefusal(Contract):
    """What the part was refused, and why: by the interlocking at once (RANG-10), or by the
    station (Neka)."""

    at: datetime
    text: Text


class TklPartStreet(Contract):
    """A switch street (RANG-02) as the part's screen shows it."""

    id: Name
    name: Text
    side: PartSide | None = None
    track: Text
    positions: dict[Name, Position] = Field(default_factory=dict)
    laid: bool = Field(default=False, description="Varje växel i gatan ligger i sitt läge.")
    possible: bool = True
    reason: Text | None = None


class TklPartRouteOut(Contract):
    """A route out (RANG-03) as the part's screen shows it: whether a request can go now, and
    the request when there is one."""

    id: Name
    name: Text
    side: PartSide | None = None
    track: Text
    start: Name
    end: Name
    possible: bool = True
    reason: Text | None = Field(default=None, description="Varför en begäran inte kan gå nu.")
    request: int | None = None
    state: TklPartRequestState | None = None


class TklPartShown(Contract):
    """Ett delställverk (TKL97–TKL103) as both screens show it: the area, the border, the
    switch streets and the routes out, with the requests, the ring and Fika."""

    id: Id
    name: Text
    own_place: bool = False
    place: Id | None = None
    pieces: list[Name] = Field(default_factory=list, description="Områdets spårbitar.")
    switches: list[Name] = Field(default_factory=list, description="Delens egna växeldelar.")
    signals: list[Name] = Field(default_factory=list)
    border: list[BorderSwitch] = Field(default_factory=list)
    rules: PartRules = Field(default_factory=PartRules)
    streets: list[TklPartStreet] = Field(default_factory=list)
    routes_out: list[TklPartRouteOut] = Field(default_factory=list)
    requests: list[TklPartRequest] = Field(default_factory=list)
    rings: datetime | None = Field(
        default=None, description="Delen ringer: sedan när, tills stationen svarar (TKL98)."
    )
    fika: bool = Field(
        default=False, description="Delen har fika: skärmen är låst tills den är tillbaka."
    )
    refused: list[TklPartRefusal] = Field(
        default_factory=list, max_length=PART_REFUSALS, description="Senaste först."
    )


class TklReady(Contract):
    """Klart att skicka (TKL108): a train a part has announced ready to send, in the station's
    list."""

    number: TrainNumber
    part: Id
    part_name: Text
    track: Text | None = Field(default=None, description="Spåret tåget står på.")
    departure: TimeOfDay | None = Field(
        default=None, description="Avgångstiden i planen. Ett inskrivet nummer har ingen."
    )
    call: Id | None = None
    at: datetime = Field(description="När det anmäldes.")
    moved: bool = Field(default=False, description="Stationen har flyttat det i listan.")


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
    field: TklField | None = Field(
        default=None,
        description="Nivå 3 med LocoNet ansluten (eller låtsas-LocoNet): spårledningarna styr "
        "tågnumren och växlarna återrapporterar (STV-15). Inget: nivå 1–2, med knapparna.",
    )
    parts: list[TklPartShown] = Field(
        default_factory=list, description="Delställverken med sitt läge (TKL97)."
    )
    ready: list[TklReady] = Field(
        default_factory=list,
        description="Klara att skicka, i stationens ordning: efter avgångstiden i planen, och "
        "som stationen har flyttat dem (TKL108).",
    )
    fjarr: TklFjarrState = Field(
        default_factory=TklFjarrState,
        description="Fjärrstyrningen: vem som styr, automaterna och magasinet (#36 del b).",
    )


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


# --- Delställverk (#87): what a part and the station ask of the interlocking ----------------


class TklPartStreetAsk(Contract):
    """Lägg en växelgata (RANG-02)."""

    street: Name


class TklPartRequestAsk(Contract):
    """Begär väg (TKL98): a route out over the border. Refused at once when it cannot go, and
    then nothing reaches the station (RANG-10)."""

    route_out: Name


class TklPartRequestRef(Contract):
    """Lämna tillbaka (TKL98): an approved request returned, or a waiting one taken back."""

    request: int = Field(ge=1)


class TklPartReply(Contract):
    """Svar (TKL98): the station approves a request, and its interlocking sets the route, or
    refuses it."""

    request: int = Field(ge=1)
    approved: bool


class TklPartRef(Contract):
    """A part, for the station: answering its ring."""

    part: Id


class TklPartFika(Contract):
    """Fika: the part's screen is locked until the part is back, and the station sees it."""

    on: bool


class TklReadyAsk(Contract):
    """Klart att skicka (TKL108): a train by its number, chosen from the plan or typed. TKL
    finds its track and planned departure in the plan when it is there."""

    number: TrainNumber
    call: Id | None = None


class TklReadyMove(Contract):
    """Flytta i listan Klara att skicka: the train to its new place, counted from 0."""

    number: TrainNumber
    to: int = Field(ge=0)


class TklReadyRef(Contract):
    """Skickat: the train leaves the list Klara att skicka."""

    number: TrainNumber


class TklPartTrain(Contract):
    """A train the part may announce ready to send: from the plan (TKL108, TKL110)."""

    number: TrainNumber
    call: Id | None = None
    track: Text | None = None
    departure: TimeOfDay | None = None
    label: Text | None = Field(default=None, description="Tågets slag, till exempel Godståg.")


class TklPartTrains(Contract):
    """The trains a part chooses among for Klart att skicka. A part that is its own driftplats
    has the trains that depart from it in the timetable (TKL108); another part has the
    station's trains that stand on a track in its area (TKL110). Another number may be typed."""

    part: Id
    trains: list[TklPartTrain] = Field(default_factory=list)
    message: Text | None = Field(default=None, description="Varför listan är tom, när den är det.")


class TklPartMessageKind(StrEnum):
    """The five messages between a part and the station (TKL98)."""

    REQUEST = "request"  # begär väg
    REPLY = "reply"  # svar: godkänt eller nekat
    RETURN = "return"  # lämna tillbaka
    READY = "ready"  # klart att skicka
    RING = "ring"  # ring


class TklPartMessage(Contract):
    """One of the five messages, as the interlocking hands it on. Locally the station's
    interlocking is the whole exchange; when the station is remote-controlled the message goes
    through Hubben to whoever remote-controls it, who answers as the station would (TKL100,
    DRIFT-40, #36)."""

    kind: TklPartMessageKind
    part: Id
    at: datetime
    request: int | None = None
    route_out: Name | None = None
    approved: bool | None = None
    number: TrainNumber | None = None
    text: Text


# --- Studio, Dela stationen (#87 del b, TKL99, TKL101, TKL103) ------------------------------
# The owner divides the station into parts in Studio: each part's area on the panel, its border
# switches with their owner and position towards the part, the rules at the border, the switch
# streets computed from the track graph and the routes out chosen from the station's routes.
# The parts belong to the station model: kept as a draft until Använd, then the model's, and
# versioned with it. The area is the same kind as local release's (TKL103).


class TklDelaState(StrEnum):
    DRAFT = "draft"  # utkast, sparat på datorn
    IN_USE = "in_use"  # används i Ställverket: stationsmodellens delar


class TklDelaRefKind(StrEnum):
    """What a check is about, so that a click on it shows it."""

    PART = "part"
    PIECE = "piece"
    SWITCH = "switch"
    SIGNAL = "signal"
    STREET = "street"
    ROUTE_OUT = "route_out"


class TklDelaCheck(Contract):
    """One of Studio's checks of the parts: a problem stops Använd, a note does not."""

    text: Text
    problem: bool = True
    part: Id | None = Field(default=None, description="Delen kontrollen gäller.")
    kind: TklDelaRefKind | None = None
    id: Text | None = Field(default=None, description="Det kontrollen gäller, att klicka på.")


class TklDelaFound(Contract):
    """What Studio works out for one part from the station's track plan: where its area meets
    the rest, and the switch streets and routes out it can be given."""

    part: Id
    edge: list[Name] = Field(
        default_factory=list, description="Noderna där området möter resten av stationen."
    )
    border_switches: list[BorderSwitch] = Field(
        default_factory=list,
        description="Växlarna vid gränsen: de leder ut ur området och ska vara gränsväxlar. Med "
        "stationen som ägare och det läge mot delen som Studio föreslår: benet som stannar i "
        "området.",
    )
    streets: list[SwitchStreet] = Field(
        default_factory=list,
        description="Växelgatorna Studio kan räkna fram ur spårgrafen: en per ände och spår.",
    )
    routes_out: list[RouteOut] = Field(
        default_factory=list,
        description="Stationens växlingsvägar som börjar i området och lämnar det.",
    )


class TklDela(Contract):
    """Studio, Dela stationen: the parts as a draft or as the model has them, the station's
    sections to click the area with, what Studio works out per part, and the checks."""

    state: TklDelaState
    parts: list[StationPart] = Field(default_factory=list)
    sections: dict[Name, list[Name]] = Field(
        default_factory=dict,
        description="Stationens sektioner med sina spårbitar: området väljs sektion för sektion.",
    )
    found: list[TklDelaFound] = Field(default_factory=list)
    checks: list[TklDelaCheck] = Field(default_factory=list)


class TklDelaEdit(Contract):
    """The parts as the owner has them now: saved as the draft."""

    parts: list[StationPart] = Field(default_factory=list, max_length=20)


class TklPartPlace(Contract):
    """A part's driftplats in Hubben, with the dispatcher's answer for it (TKL101,
    TRAFIK-35): found by its link, the part's id in the station's outside."""

    part: Id
    place: Id
    status: ApprovalStatus


class TklReportKind(StrEnum):
    DEPARTED = "departed"  # avgång, train.departed
    ARRIVED = "arrived"  # ankomst, train.arrived, eller spårbyte, train.track.change
    EXIT_SIGNAL = "exit_signal"  # utfartssignalens besked, signal.exit
    SECTION_OCCUPANCY = "section_occupancy"  # beläggningen på linjen, section.occupancy (nivå 3)


class TklReport(Contract):
    """Vad ställverket rapporterar upp till Hubben (STV-10), and how it went."""

    kind: TklReportKind
    train_number: TrainNumber | None = None
    call: Id | None = None
    exit: Id | None = Field(default=None, description="Utfartens id i utsidan.")
    track: Id | None = Field(default=None, description="Stationsspårets id i utsidan.")
    aspect: ExitSignalAspect | None = None
    occupied: bool | None = Field(
        default=None, description="Nivå 3: linjens spårledning vid utfarten är belagd."
    )
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


# --- Level 3: LocoNet and Studio's Koppla in (#85) ------------------------------------------


class ObjectKind(StrEnum):
    """What Koppla in connects: a switch part, a signal or a track circuit."""

    SWITCH = "switch"
    SIGNAL = "signal"
    TRACK_CIRCUIT = "track_circuit"


class LoconetType(StrEnum):
    """How TKL reaches LocoNet (STUDIO-22)."""

    LOCOBUFFER = "locobuffer"  # LocoBuffer USB, på en serieport
    BTLOCOBRIDGE = "btlocobridge"  # BTLocoBridge över Bluetooth: adressen eller den parade porten
    PRETEND = "pretend"  # låtsas-LocoNet: LocoNet ej ansluten, som Prova använder (STUDIO-24)


class TklPort(Contract):
    """A port in the list (STUDIO-11)."""

    type: LoconetType
    port: Text = Field(description="Serieporten under /dev, eller låtsas för låtsas-LocoNet.")
    label: Text


class TklLoconet(Contract):
    """The connection to LocoNet. TKL in the cloud never has it (TKLMOLN-08)."""

    available: bool = Field(description="LocoNet går att ansluta här: bara en lokal TKL.")
    reason: Text | None = Field(default=None, description="Varför det inte går.")
    connected: bool = False
    type: LoconetType | None = None
    port: Text | None = None
    channel: int | None = Field(default=None, description="BTLocoBridgens RFCOMM-kanal.")
    label: Text | None = Field(default=None, description="Till exempel LocoNet ansluten via …")
    error: Text | None = Field(default=None, description="Varför förbindelsen bröts senast.")
    since: datetime | None = None


class TklLoconetConnect(Contract):
    """Anslut till LocoNet: the type, the port, and the channel for a BTLocoBridge by address."""

    type: LoconetType
    port: str | None = Field(default=None, max_length=255)
    channel: int = Field(default=1, ge=1, le=30)


class TklCardChannel(Contract):
    channel: int = Field(ge=1, description="Kortets utgång, från 1.")
    address: int = Field(ge=1)
    objects: list[Text] = Field(default_factory=list, description="Objekten på utgången.")


class TklCard(Contract):
    """An MGP card from Discover, with its module and channels (STUDIO-18, STV-11)."""

    address: int = Field(ge=0, description="Kortets adress för SV2.")
    name: Text = Field(description="Till exempel MGP Signal10 SE.")
    manufacturer: int
    developer: int
    product: int
    serial: int
    base: int | None = Field(default=None, description="Basadressen i SV21: kanal 1.")
    module: Text | None = Field(default=None, description="Modulen kortet sitter i.")
    channels: list[TklCardChannel] = Field(default_factory=list)


class TklKopplaObject(Contract):
    """A switch part, a signal or a track circuit, with its address and its state."""

    kind: ObjectKind
    name: Name
    state: AddressState
    address: int | None = None
    default: bool = Field(
        default=False, description="Adressen är växelns nummer, som förval (STUDIO-19)."
    )
    reversed: bool = Field(default=False, description="Omvänd polaritet (STUDIO-24).")
    feedback: FeedbackType | None = Field(default=None, description="Växelns återrapport.")
    straight: int | None = Field(default=None, description="Givaren för rakt, med två givare.")
    diverging: int | None = Field(default=None, description="Givaren för avvikande.")
    control: SwitchControl | None = None
    card: int | None = Field(default=None, description="Kortet adressen sitter på.")
    module: Text | None = None
    channel: int | None = None
    note: Text | None = None


class TklChoice(Contract):
    value: Literal["yes", "no", "reversed"]
    label: Text


class TklQuestion(Contract):
    """A learning question as it comes (STUDIO-04): Givaren 73 slog till. Är det Spår 3?"""

    id: int = Field(ge=1)
    kind: ObjectKind
    object: Name | None = Field(default=None, description="Objektet TKL föreslår.")
    address: int
    text: Text
    seen: Text | None = Field(default=None, description="Vad banan rapporterade efter ordern.")
    answers: list[TklChoice]
    choices: list[Name] = Field(
        default_factory=list, description="Andra objekt av samma slag att välja i stället."
    )


class TklLearning(Contract):
    """The object being learnt, and what the owner does now."""

    kind: ObjectKind
    name: Name
    text: Text


class TklLevel3(Contract):
    """Nivå 3: on when the model has addresses and the owner turns it on."""

    on: bool
    possible: bool
    reason: Text | None = None
    problems: list[Text] = Field(default_factory=list)


class TklKopplaIn(Contract):
    """Studio's Koppla in: the connection, the cards, the objects in their four states, and the
    learning question as it comes."""

    loconet: TklLoconet
    level: int = Field(ge=0, le=3)
    level_3: TklLevel3
    cards: list[TklCard] = Field(default_factory=list)
    discovered: datetime | None = None
    objects: list[TklKopplaObject] = Field(default_factory=list)
    question: TklQuestion | None = None
    learning: TklLearning | None = None
    message: Text | None = Field(default=None, description="Vad som just hände.")


class TklObjectChange(Contract):
    """An object's address as the owner gives it: an address (yellow until it is confirmed on
    the layout), none (grey), or Utan adress; and the polarity and the switch's feedback."""

    kind: ObjectKind
    name: Name
    address: int | None = Field(default=None, ge=1, le=4096)
    without: bool = False
    reversed: bool | None = None
    feedback: FeedbackType | None = None
    straight: int | None = Field(default=None, ge=1, le=4096)
    diverging: int | None = Field(default=None, ge=1, le=4096)


class TklLearnAsk(Contract):
    """Lär in: Lägg om a switch, Skicka kör to a signal, or wait for a wagon on a track
    circuit."""

    kind: ObjectKind
    name: Name


class TklLearnAnswer(Contract):
    question: int = Field(ge=1)
    answer: Literal["yes", "no", "reversed"]
    object: Name | None = Field(default=None, description="Ett annat objekt än det föreslagna.")


class TklLevelAsk(Contract):
    level: int = Field(ge=2, le=3)


class TklCardModule(Contract):
    card: int = Field(ge=0)
    module: str | None = Field(default=None, max_length=40)


class TklPretendAsk(Contract):
    """Låtsas-LocoNet: a wagon put on a track circuit, or lifted off it."""

    track_circuit: Name
    occupied: bool = True


class TklHeard(Contract):
    """One LocoNet message in Lyssna, decoded in Swedish."""

    at: datetime
    direction: Literal["in", "out"]
    hex: Text
    text: Text
    objects: list[Text] = Field(default_factory=list)


class TklListen(Contract):
    """Lyssna, behind Felsök: the last messages, newest first."""

    connected: bool
    messages: list[TklHeard] = Field(default_factory=list)


# --- Studio's Prova (#85 del c, STUDIO-05, STUDIO-12, STUDIO-21, STUDIO-27) -------------------


class TklProvaResult(StrEnum):
    PASSED = "passed"  # gick igenom
    FAILED = "failed"  # gick inte, med skälet
    SKIPPED = "skipped"  # hoppades över i Provkör


class TklProvaSimulator(StrEnum):
    """How Prova runs the train: the interlocking at level 3 against the pretend LocoNet, or at
    level 1–2 with Kör."""

    PRETEND = "pretend"  # nivå 3: låtsas-LocoNet, växlarna återrapporterar, spårledningarna styr
    KOR = "kor"  # nivå 1–2: ställverket med Kör, sektion för sektion


class TklProvaWay(Contract):
    """A route Prova runs: one of the engine's train routes or shunting routes."""

    kind: RouteKind
    start: Name
    end: Name
    pieces: list[Name] = Field(default_factory=list, description="Vägens spårbitar, för panelen.")


class TklProvaRoute(TklProvaWay):
    """A route's result in Prova or Provkör: passed, or failed with the reason in Swedish."""

    result: TklProvaResult
    reason: Text | None = None


class TklProvkor(Contract):
    """Provkör (STUDIO-05, STUDIO-27): with LocoNet connected to the layout, each route is set on
    the real layout. TKL orders the switches and checks their feedback; the owner confirms the
    signal and the train's path, says it is wrong, or skips the route."""

    available: bool = Field(description="LocoNet är anslutet till banan, på nivå 3.")
    reason: Text | None = Field(default=None, description="Varför Provkör inte går nu.")
    running: bool = False
    done: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    route: TklProvaWay | None = Field(default=None, description="Vägen som provas nu.")
    waiting: Text | None = Field(
        default=None, description="Vad TKL väntar på, till exempel återrapporten från en växel."
    )
    question: Text | None = Field(default=None, description="Frågan till ägaren, när vägen ligger.")
    routes: list[TklProvaRoute] = Field(
        default_factory=list, description="Vägarna som är provkörda, de som inte gick först."
    )
    finished: datetime | None = None


class TklProva(Contract):
    """Studio's Prova: a simulated train through every route (STUDIO-05, STUDIO-27), run in the
    background with its progress, and the results kept with the station until the model
    changes. Klart (`tried`) when every route has passed: Ställverket then opens without the
    note that the station is not tried."""

    level: int = Field(ge=0, le=3)
    simulator: TklProvaSimulator | None = Field(
        default=None, description="Hur tåget körs; inget utan stationsmodell."
    )
    running: bool = False
    done: int = Field(default=0, ge=0, description="Vägarna som är provade hittills.")
    total: int = Field(default=0, ge=0, description="Vägarna i modellen.")
    routes: list[TklProvaRoute] = Field(
        default_factory=list, description="Vägarnas resultat, de som inte gick först."
    )
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    tried: bool = Field(default=False, description="Klart: varje väg gick igenom (STUDIO-05).")
    started: datetime | None = None
    finished: datetime | None = None
    invalidated: bool = Field(
        default=False,
        description="Stationsmodellen har ändrats sedan Prova kördes: resultaten gäller inte.",
    )
    message: Text | None = None
    provkor: TklProvkor


class TklProvkorAnswer(Contract):
    """The owner's answer in Provkör: the signal and the path are right, wrong, or the route is
    skipped."""

    answer: Literal["right", "wrong", "skip"]


# --- Stream Deck (#86 del a): the deck's model, its logic and the deck on the screen --------

Colour = Annotated[str, StringConstraints(pattern=r"^#[0-9a-f]{6}$")]
"""A colour on a key, from the locked palette (SD3)."""
KeyText = Annotated[str, StringConstraints(max_length=60)]
"""Text on a key: empty when the key has none."""


class DeckModelId(StrEnum):
    """Elgato's models (SD52). Module 6, 15 and 32 and the older editions of the 15 get the
    profile of the size they have (SD54)."""

    MINI = "mini"
    NEO = "neo"
    FIFTEEN = "15"  # Stream Deck 15: classic keys, Scissor Keys, MK.2 and the first one
    XL = "xl"
    PLUS = "plus"
    PLUS_XL = "plus-xl"
    PEDAL = "pedal"
    MODULE_6 = "module-6"
    MODULE_15 = "module-15"
    MODULE_32 = "module-32"
    STUDIO = "studio"


class TklDeckGrid(Contract):
    """What a deck has (SD53): the keys in columns and rows, and the dials, the touch strip,
    the info line, the touch points and the pedals. A model TKL does not know is read this
    way too, and gets the default for its grid."""

    columns: int = Field(ge=0, le=32)
    rows: int = Field(ge=0, le=8)
    dials: int = Field(default=0, ge=0, le=8)
    strip: bool = Field(default=False, description="Pekremsan, på + och + XL.")
    info: bool = Field(default=False, description="Inforaden, på Neo.")
    touch: int = Field(default=0, ge=0, le=4, description="Pekpunkterna, på Neo.")
    pedals: int = Field(default=0, ge=0, le=8)


class TklDeckModel(Contract):
    id: DeckModelId
    name: Text
    grid: TklDeckGrid
    size: DeckModelId = Field(description="Storleken vars profil modellen får (SD54).")
    tried: bool = Field(
        default=False,
        description="Provad med ett riktigt deck (SD58). Tills dess står modellen som Inte provad.",
    )


class DeckStyle(StrEnum):
    """Where Läge and the fixed keys sit (SD27, SD75, SD77, SD78)."""

    NONE = "none"  # Pedal: nothing until the owner chooses (SD55)
    NEXT = "next"  # Mini, Module 6: ▶ last, and holding it opens Läge
    LAST = "last"  # Neo, +: Läge as the last key
    ROW = "row"  # 15, Studio: the fixed row at the bottom, Läge far right
    COLUMN = "column"  # XL, + XL: the fixed keys in the right column, Läge at the bottom


class DeckMode(StrEnum):
    """Lägena (SD63): a group of pages with the same way of working. Bangård is the shunter's
    deck, for a deck with a part's role (#87 del d, SD74). Fjärr is the fjärrtågklarerare's,
    a page per station it controls (#36 del d, SD37)."""

    TRAINS = "tagen"
    PLACES = "platser"
    TRACK_PLAN = "sparplan"
    YARD = "bangard"
    REMOTE = "fjarr"


DECK_REMOTE_ROLE: Final = "fjarrtagklarerare"
"""The fjärrtågklarerare's role on a deck (#36 del d, SD37): `TklDeckSettings.role` with this id
opens the mode Fjärr. Never a part's id; a remote interlocking's decks always have it."""


class DeckPageKind(StrEnum):
    NOW = "nu"  # tågknappar, linjeknappar och larm (SD22)
    DAILY = "dagens"  # Dagens vägar (SD23)
    FAVOURITES = "favoriter"  # SD24, SD48
    PLACES = "platser"  # SD66, SD80, SD84, SD85
    PARTS = "delar"  # the first step on a small deck (SD79)
    PART = "del"  # the places of one part
    SIGNALS = "signaler"  # the geographic pages (SD25)
    ALL = "alla"  # every start (SD25)
    WHOLE = "hela"  # Spårplan, Hela stationen (SD70)
    CUTOUT = "utsnitt"  # Spårplan, the cut-out (SD71)
    OWN = "egen"  # a page the owner added in Studio (SD40)
    YARD = "bangard"  # Bangård, the shunter's deck (SD61, SD86, SD87)
    REMOTE = "fjarr"  # Fjärr: one station's catalogue routes, the fjärrtågklarerare's (SD37)


class DeckKeyType(StrEnum):
    """The fixed catalogue of keys (SD4): a new type is added for all, never for a station."""

    TRAIN = "train"  # Tågknapp: the slot-th train on turn
    LINE = "line"  # Linjeknapp: the slot-th line
    ALARM = "alarm"  # Larmknapp
    TRACK = "track"  # Spårknapp: a station track, at a station with one line
    PLACE = "place"  # Platser: an exit or a track part
    PART = "part"  # a part of the station, opening its page
    SIGNAL = "signal"  # a start, then a goal
    DAILY = "daily"  # the slot-th of Dagens vägar
    FAVOURITE = "favourite"  # the slot-th of Favoriter
    TILE = "tile"  # Spårplan, a piece of the whole station
    CELL = "cell"  # Spårplan, a square of the cut-out
    PAN = "pan"  # Spårplan: Hela, väster, öster, upp, ner
    MODE = "mode"  # Läge
    NEXT = "next"  # ▶ on Mini
    PAGE = "page"  # ▶ in the fixed row: the next page of the mode
    ACTION = "action"  # Lös ut, Ankommit, Kör, Avbryt, Tillbaka
    PANEL = "panel"  # a panel function of the station, by its name
    ROUTE = "route"  # Snabbväg: one press sets a whole route, start to goal (SD42, #86 del c)
    # Bangård, the shunter's deck (#87 del d):
    END = "ande"  # Ände: the left or the right end, and the key shows which (SD86)
    STREET = "gata"  # a track of the part: a press lays the switch street from the end (SD61)
    REQUEST = "begar"  # a route out: a press requests it from the station (SD61, RANG-03)
    READY = "klart-tag"  # the next train from the plan: a press announces it (SD60, TKL108)
    # Fjärr, the fjärrtågklarerare's deck (#36 del d, SD37):
    REMOTE_ROUTE = "fjarrvag"  # a route of a station's remote catalogue: press, then press again
    OFFER = "erbjudande"  # a station offered: press takes it, hold declines it (FR8)


class DeckAction(StrEnum):
    RELEASE = "los"  # Lös ut; hold: all (SD29)
    ARRIVED = "ankommit"  # Ankommit, in drift (SD10, SD27)
    RUN = "kor"  # Kör, only in Prova and the reference stations (SD28)
    CANCEL = "avbryt"
    BACK = "tillbaka"
    LOCK = "las"  # Lås (Fika): TKL is locked for the whole station (SD30), on the page Läge
    # What a press or a hold does, as the owner chooses it in Studio from this list (SD43):
    LAY = "lagg"  # Lägg vägen: the key's route
    RELEASE_ROUTE = "los-vagen"  # Lös ut vägen: the key's route, when it is set
    RELEASE_ALL = "los-alla"  # Lös ut alla: only with a hold, never on a pedal (SD29, SD55)
    RESET = "noll"  # Noll: the interlocking reset, only with a hold, never on a pedal
    EMERGENCY = "nodutlosning"  # Nödutlösning of the latest route: only with a hold
    NOTHING = "ingenting"
    # Bangård, the shunter's deck (#87 del d, SD61, RANG-04):
    GIVE_BACK = "lamna"  # Lämna, then a track: that route is returned
    DONE = "klart"  # Klart: every request returned and the border switches back
    RING = "ring"  # Ring: rings the station
    GATES = "grindar"  # Grindar: the border switches back, nothing returned
    HORN = "tuta"  # Tuta
    FIKA = "fika"  # Fika: the part's own, its deck dark until the shunter is back
    CLOCK = "klocka"  # Klocka
    REQUESTS = "begaran"  # Begär on Mini: opens the routes out (SD87)


class DeckPan(StrEnum):
    WHOLE = "hela"
    WEST = "vaster"
    EAST = "oster"
    UP = "upp"
    DOWN = "ner"


class DeckDial(StrEnum):
    """What a dial does in a mode (SD83): turn chooses, press does it."""

    TRAIN = "tag"
    TRACK = "spar"
    PAGE = "sida"
    ROUTE = "lagd-vag"
    START = "start"
    GOAL = "mal"
    PART = "del"
    SIDEWAYS = "sidled"
    UPDOWN = "hojdled"
    SIGNAL = "signal"
    REQUEST = "begar"  # Bangård on +: turn chooses the route out, press requests it (SD87)
    STREET = "gata"  # Bangård: turn chooses the track, press lays the street from the end
    READY = "klart-tag"  # Bangård: turn chooses the train, press announces it (SD60)


class DeckHold(StrEnum):
    """How long a hold is, per deck (SD29): Kort, Normal (0.6 s) or Lång."""

    SHORT = "kort"
    NORMAL = "normal"
    LONG = "lang"


class DeckPlacesShown(StrEnum):
    """Platser's variants (SD68)."""

    ALL = "alla"
    CHOOSABLE = "valbara"


class DeckPlanDrawn(StrEnum):
    """How Spårplan is drawn (SD72)."""

    STANDARD_85 = "85"
    RELAY = "rela"


class TklDeckRoute(Contract):
    start: Name
    end: Name
    kind: RouteKind


class TklDeckKey(Contract):
    """A key in a profile: its type from the catalogue and what it points at, as data (SD5).

    What the owner may change in Studio (SD43) is here too: the text and the line under, what a
    press and a hold do from the fixed list `DeckAction`, and what the key shows. Never the
    colours, the symbols or what a gesture means (SD3): those follow the catalogue."""

    type: DeckKeyType
    slot: int | None = Field(default=None, ge=1, description="Tåget, linjen eller vägen i tur.")
    point: Name | None = Field(default=None, description="Signalen eller punkten (SIGNAL).")
    place: Name | None = Field(default=None, description="Platsen (PLACE, TRACK).")
    part: int | None = Field(default=None, ge=0, description="Delen (PART).")
    page: int | None = Field(default=None, ge=0, description="Sidan knappen öppnar.")
    dx: int | None = Field(default=None, ge=0, description="Utsnittets kolumn (CELL).")
    dy: int | None = Field(default=None, ge=0, description="Utsnittets rad (CELL).")
    rect: tuple[float, float, float, float] | None = Field(
        default=None, description="Biten av spårplanen i rutor: x, y, bredd, höjd (TILE)."
    )
    pan: DeckPan | None = None
    action: DeckAction | None = None
    function: Text | None = Field(default=None, description="Panelfunktionens namn (PANEL).")
    route: TklDeckRoute | None = Field(default=None, description="Snabbvägens väg (ROUTE).")
    track: Name | None = Field(
        default=None,
        description="Spåret: växelgatans eller vägen ut:s spår i delen (STREET, REQUEST, #87).",
    )
    side: PartSide | None = Field(
        default=None,
        description="Änden knappen alltid gäller; inget: den ände Ände har valt (STREET, REQUEST).",
    )
    remote: Id | None = Field(
        default=None,
        description="Tågvägens id i stationens fjärrkatalog, med driftplatsen i place "
        "(REMOTE_ROUTE, #36 del d).",
    )
    text: KeyText = Field(default="", description="Knappens text, när den är given.")
    under: KeyText = Field(default="", description="Undertexten, när ägaren har gett den.")
    press: DeckAction | None = Field(
        default=None, description="Vad ett tryck gör, ur den fasta listan; annars katalogens."
    )
    hold: DeckAction | None = Field(
        default=None, description="Vad håll in gör, ur den fasta listan; annars katalogens."
    )
    number: bool | None = Field(
        default=None, description="Visa tågnumret på målspåret (snabbväg). Förval: ja."
    )
    dim: bool | None = Field(
        default=None, description="Tona ned knappen när vägen är hindrad (SD17). Förval: ja."
    )
    confirm: bool | None = Field(
        default=None, description="Fråga en gång till före trycket. Förval: nej."
    )


class TklDeckPage(Contract):
    """A page: every key of the grid, row by row, the fixed ones included."""

    name: Text
    mode: DeckMode
    kind: DeckPageKind
    keys: list[TklDeckKey | None]
    listed: bool = Field(
        default=True, description="Står bland Sidor (SD26). En dels sida gör inte det."
    )
    cancel: int | None = Field(
        default=None, ge=0, description="Där Avbryt står medan en start är vald."
    )
    part: int | None = Field(default=None, ge=0, description="Delen sidan visar (SD79).")


class TklDeckPlace(Contract):
    """A place where a train route starts or ends (SD66): an exit or a station track."""

    id: Name
    kind: Literal["exit", "track"]
    name: Name = Field(description="Exit's or track's own name (SD73).")
    part: int = Field(ge=0)
    starts: list[Name] = Field(default_factory=list, description="Tågvägarnas starter här.")
    ends: list[Name] = Field(default_factory=list, description="Tågvägarnas mål här.")
    signals: list[Name] = Field(default_factory=list, description="Signalen i var ände (SD69).")
    x: float
    y: float


class TklDeckPart(Contract):
    """A part of the station, west to east (SD79): the west exits, a group of track parts, or
    the east exits."""

    name: Text
    places: list[Name]
    said: KeyText = Field(default="", description="Platserna i korthet, till exempel A1–A4.")


class TklDeckPoint(Contract):
    """A route's start or goal where the panel has it, for the geographic pages and Spårplan."""

    name: Name
    x: float
    y: float
    start: bool


class TklDeckProfile(Contract):
    """The deck's profile for one grid (SD5, SD32, SD53): computed from the station model and
    never stored as code, with the owner's deviations laid on (SD40, tkl.deck.deviations)."""

    model: DeckModelId | None = None
    grid: TklDeckGrid
    style: DeckStyle
    fixed: list[int] = Field(default_factory=list, description="Den fasta radens knappar (SD27).")
    modes: list[DeckMode] = Field(default_factory=list, description="Lägena decket har (SD76).")
    pages: list[TklDeckPage] = Field(default_factory=list)
    dials: dict[DeckMode, list[DeckDial]] = Field(default_factory=dict)
    places: list[TklDeckPlace] = Field(default_factory=list)
    parts: list[TklDeckPart] = Field(default_factory=list)
    points: list[TklDeckPoint] = Field(default_factory=list)
    one_line: bool = Field(default=False, description="Stationen har en linje: spårknappar (SD12).")
    tile: float = Field(default=1, gt=0, description="En ruta i utsnittet, i spårplanens rutor.")
    tile_origin: tuple[float, float] = Field(
        default=(0, 0), description="Där utsnittets rutor börjar, i spårplanens rutor."
    )
    plan: tuple[float, float] = Field(default=(0, 0), description="Spårplanens storlek i rutor.")
    pedals: list[TklDeckKey | None] = Field(
        default_factory=list,
        description="Pedalernas funktioner (SD55): inget förval, ingenting förrän ägaren väljer.",
    )
    part: Id | None = Field(
        default=None,
        description="Delen profilen är för: rangerarens deck, läget Bangård (#87 del d).",
    )


class TklDeckSettings(Contract):
    """One deck, known by its serial number (SD35), as this computer keeps it (SD49)."""

    serial: Name
    model: DeckModelId | None = None
    grid: TklDeckGrid
    workplace: Name = Field(
        default="1", description="Deck på samma arbetsplats delar vald start (SD36)."
    )
    opens_in: DeckMode | None = Field(default=None, description="Läget decket öppnar i (SD65).")
    may_change_mode: bool = True
    hold: DeckHold = DeckHold.NORMAL
    places_shown: DeckPlacesShown = DeckPlacesShown.ALL
    plan_drawn: DeckPlanDrawn = DeckPlanDrawn.STANDARD_85
    signal_numbers: bool = Field(default=False, description="Signalnumren i Platser (SD69).")
    name: Text | None = Field(default=None, description="Ägarens namn på decket.")
    brightness: int = Field(default=70, ge=0, le=100, description="Ljusstyrkan, i procent (SD46).")
    sleep: int = Field(
        default=0, ge=0, le=240, description="Släcks efter så många minuter utan tryck; 0 aldrig."
    )
    lock_key: bool = Field(
        default=True,
        description="Lås (Fika) på sidan Läge (SD30). Låst TKL visar ändå bara klockan.",
    )
    opens_on: Text | None = Field(
        default=None, description="Sidan decket öppnar på (SD35); annars lägets första."
    )
    role: Id | None = Field(
        default=None,
        description="Rollen: inget för tågklareraren, en del av stationen med sitt id (#87 del "
        "d), eller fjarrtagklarerare för fjärrtågklareraren (#36 del d, SD37). Ett deck med en "
        "dels roll öppnar i Bangård och når bara delens lägen; fjärrtågklarerarens i Fjärr.",
    )


class TklDeckTile(Contract):
    """A key that draws a piece of the track plan (SD70, SD71): the rectangle in the panel's
    cells, how it is drawn, and what is lit in it."""

    x: float
    y: float
    w: float
    h: float
    drawn: DeckPlanDrawn = DeckPlanDrawn.STANDARD_85
    start: Name | None = None
    goals: list[Name] = Field(default_factory=list)
    names: list[Text] = Field(default_factory=list, description="Spåren i biten (SD70).")
    chosen: bool = False
    state: Annotated[str, StringConstraints(max_length=40)] = Field(
        default="",
        description="Spårplanens läge i biten, i korthet: ändras när ett spår, en signal eller "
        "ett tågnummer i den ändras, så att bilden ritas om (#86 del b).",
    )


DeckFaceType = Literal[
    "train",
    "line",
    "alarm",
    "track",
    "place",
    "part",
    "signal",
    "daily",
    "favourite",
    "tile",
    "cell",
    "pan",
    "mode",
    "next",
    "page",
    "action",
    "panel",
    "route",
    "here",
    "ask",
    "case",
    "answer",
    "variant",
    "goal",
    "contact",
    "clock",
    "end",
    "street",
    "request",
    "fika",
    "remote",
    "offer",
    "empty",
]
"""What kind of key a face is: the catalogue's types and the deck's own (SD4)."""


class TklDeckFace(Contract):
    """What a key shows: the prototype's look, with the locked colours (SD3, SD6)."""

    type: DeckFaceType = "empty"
    text: KeyText = ""
    top: KeyText = ""
    under: KeyText = ""
    small: KeyText = Field(default="", description="Liten text, som signalnumren (SD69).")
    bg: Colour = "#0d0f11"
    fg: Colour = "#0d0f11"
    frame: Colour | None = None
    dashed: bool = False
    band: Colour | None = Field(default=None, description="Bandet överst: vägens färg.")
    line: Colour | None = Field(default=None, description="Strecket nederst: vald sida.")
    bar: Colour | None = Field(default=None, description="Platsens stapel: fri, belagd, lagd.")
    bar_dashed: bool = False
    dot: Colour | None = Field(default=None, description="Märket för en hindrad väg (SD17).")
    star: bool = Field(default=False, description="Planerat spår bland målen (SD20).")
    chip: KeyText = Field(default="", description="Tågnumret på platsen (SD19).")
    chip_colour: Literal["green", "red", ""] = ""
    blink: Colour | None = Field(default=None, description="Blinkar mellan bg och den här.")
    ready: bool = Field(
        default=False, description="Klart att skicka (SD62): det gröna märket på tågknappen."
    )
    dim: bool = False
    tile: TklDeckTile | None = None
    label: KeyText = Field(default="", description="För skärmläsare: vad knappen är.")


class TklDeckStrip(Contract):
    """What a dial stands on, in the touch strip (SD83)."""

    label: KeyText
    value: KeyText = ""
    under: KeyText = ""


class TklDeckView(Contract):
    """The deck as it is now: every key's face, and the info line and the strip."""

    settings: TklDeckSettings
    revision: int = Field(ge=0, description="Räknar upp när något på decket ändras.")
    style: DeckStyle
    modes: list[DeckMode] = Field(default_factory=list)
    mode: DeckMode | None = None
    page: KeyText = ""
    keys: list[TklDeckFace] = Field(default_factory=list)
    fixed: list[int] = Field(default_factory=list)
    info: KeyText = Field(
        default="", description="Inforaden (SD82): klockan och sidan, eller valet."
    )
    strip: list[TklDeckStrip] = Field(default_factory=list)
    hold_ms: int = Field(default=600, ge=100, le=3000, description="Ett håll (SD29).")
    refresh_ms: int = Field(default=15000, ge=200, description="Läs om senast efter så här länge.")
    locked: bool = Field(default=False, description="TKL är låst: bara klockan (SD30).")
    contact: bool = Field(default=True, description="Ställverket svarar; annars Ingen kontakt.")
    message: Text | None = Field(default=None, description="Ställverkets senaste svar.")
    accepted: bool | None = None
    said: KeyText = Field(
        default="",
        description="Ställverkets nej i tre sekunder, för pekremsan på + och + XL (SD18).",
    )


class TklDeckPress(Contract):
    """A press, or a hold of the deck's hold time (SD29)."""

    key: int = Field(ge=0, le=255)
    hold: bool = False


class TklDeckDialAsk(Contract):
    """A dial turned some steps, or pressed (SD83)."""

    dial: int = Field(ge=0, le=7)
    turn: int = Field(default=0, ge=-20, le=20)
    press: bool = False


class TklDeckTouch(Contract):
    """Neo's touch points (SD82): -1 the left one, 1 the right one."""

    point: Literal[-1, 1]


class DeckConnection(StrEnum):
    """How a deck is connected (SD50): a local TKL owns it over USB; in the cloud the browser
    drives it with WebHID; or it is the deck on the screen (SD59)."""

    USB = "usb"
    WEBHID = "webhid"
    SCREEN = "skarm"


class TklDeckOpen(Contract):
    """A deck on this computer, by its serial number: its model, or its grid for a model TKL
    does not know (SD53), and how it is connected."""

    model: DeckModelId | None = None
    grid: TklDeckGrid | None = None
    workplace: Name | None = None
    connection: DeckConnection = DeckConnection.SCREEN
    role: Id | None = Field(
        default=None,
        description="Öppna decket i en dels roll, som decket på delens skärm (#87 del d). "
        "Inget: rollen decket har.",
    )

    @model_validator(mode="after")
    def _one(self) -> TklDeckOpen:
        if self.model is None and self.grid is None:
            raise ValueError("Ange modellen eller rutnätet.")
        return self


class TklDeckStatus(Contract):
    """One deck as Studio, Deck shows it (#86 del c): its serial number, its model, how it is
    connected now, and whether its model is tried with a real deck (SD35, SD50, SD58)."""

    serial: Name
    model: DeckModelId | None = None
    name: Text = Field(description="Modellens namn, eller rutnätet för en okänd modell.")
    grid: TklDeckGrid
    workplace: Name = "1"
    connection: DeckConnection | None = Field(
        default=None, description="Ansluten nu: över USB, med WebHID eller på skärmen."
    )
    tried: bool = Field(default=False, description="Modellen är provad med ett riktigt deck.")
    settings: TklDeckSettings | None = Field(
        default=None, description="Decket som datorn har det: ljusstyrka, hålltid och resten."
    )
    blinking: bool = Field(default=False, description="Decket blinkar just nu (Blinka).")


class TklDeckRole(Contract):
    """A role a deck opens as (#87 del d): the tågklarerare, or a part of the station by its id,
    whose deck is the shunter's, Bangård; or the fjärrtågklarerare (#36 del d, SD37), whose deck
    is made from the remote catalogues of the stations TKL controls."""

    part: Id | None = Field(
        default=None,
        description="Rollens id i decket: delens id, fjarrtagklarerare för fjärrtågklareraren; "
        "inget för tågklareraren.",
    )
    name: Text
    remote: bool = Field(default=False, description="Fjärrtågklareraren (SD37).")


class TklDecks(Contract):
    """The decks this TKL knows (SD35), and whether it owns decks over USB itself: a local TKL
    does, so that a deck works without an open tab (SD50); TKL in the cloud never opens USB."""

    usb: bool = Field(description="TKL sköter deck över USB på den här datorn.")
    usb_problem: Text | None = Field(
        default=None, description="Varför TKL inte når USB just nu, till exempel utan libhidapi."
    )
    decks: list[TklDeckStatus] = Field(default_factory=list)
    roles: list[TklDeckRole] = Field(
        default_factory=list, description="Rollerna ett deck kan ha: tågklareraren och delarna."
    )


class TklDeckCount(TklDeckRoute):
    count: int = Field(ge=0)


class TklDeckPin(TklDeckRoute):
    """Fäst på Stream Deck (SD48): a set route onto the page Favoriter, or off it."""

    pinned: bool = True


class TklDeckFavourites(Contract):
    """Favoriter (SD24, SD48): the pinned routes first, then the most used. Only routes are
    counted, never people."""

    pinned: list[TklDeckRoute] = Field(default_factory=list)
    counted: list[TklDeckCount] = Field(default_factory=list)
    shown: list[TklDeckRoute] = Field(default_factory=list, description="Sidan Favoriter.")


# --- Studio, Inställningar, Stream Deck (#86 del c): the owner's deviations, the checks, Prova

DECK_DEVIATIONS: Final = 400
"""The most deviations one size keeps."""


class DeckPageRef(Contract):
    """A page by its kind and its name, never by its place among the pages (SD40): a page the
    default makes again after the drawing changed is found by the same kind and name."""

    kind: DeckPageKind
    name: Text


class DeckChange(StrEnum):
    """What a deviation from the default does (SD40, SD43)."""

    MOVE = "flytta"  # a key to another cell of its page; what stands there takes its old cell
    ADD = "lagg-till"  # a key from Knappar onto a cell
    REMOVE = "ta-bort"  # a key off its page
    KEY = "andra"  # a key's text, the line under, press, hold and what it shows
    ADD_PAGE = "ny-sida"  # a page of the owner's own, last in its mode
    REMOVE_PAGE = "ta-bort-sida"
    ORDER = "ordning"  # the pages of a mode in the owner's order
    PEDAL = "pedal"  # what a pedal does (SD55)


class TklDeckDeviation(Contract):
    """One of the owner's changes from the default, in stable ids (SD40): a key by what it is
    (its type and what it points at: a route start → goal, a place, a signal, a slot, an
    action), a page by its kind and name. The cell is only where the key goes. Never a colour,
    a symbol or a gesture's meaning (SD3, SD43): a deviation that tries is refused."""

    change: DeckChange
    page: DeckPageRef | None = Field(default=None, description="Sidan ändringen gäller.")
    key: TklDeckKey | None = Field(
        default=None, description="Knappen, igenkänd på vad den är; hela knappen för Lägg till."
    )
    cell: int | None = Field(default=None, ge=0, le=255, description="Dit knappen flyttas.")
    text: KeyText | None = None
    under: KeyText | None = None
    press: DeckAction | None = None
    hold: DeckAction | None = None
    number: bool | None = None
    dim: bool | None = None
    confirm: bool | None = None
    mode: DeckMode | None = Field(default=None, description="Läget för en ny sida.")
    order: list[DeckPageRef] = Field(
        default_factory=list, max_length=200, description="Lägets sidor i ägarens ordning."
    )
    pedal: int | None = Field(default=None, ge=0, le=7, description="Pedalen, från vänster.")


class TklDeckDeviations(Contract):
    """The owner's deviations per size (SD32, SD40), kept with the station's model in the
    package's inside and versioned with it, as Manöver's settings are (SD49). A size is the
    model whose profile a deck gets (SD54)."""

    sizes: dict[DeckModelId, list[TklDeckDeviation]] = Field(default_factory=dict)
    parts: dict[Id, dict[DeckModelId, list[TklDeckDeviation]]] = Field(
        default_factory=dict,
        description="Ägarens ändringar av rangerarens deck, Bangård, per del och storlek (#87).",
    )


class TklDeckToCheck(Contract):
    """Att kolla (SD40): a deviation that could not be laid on again, and why."""

    deviation: int = Field(ge=0, description="Avvikelsens plats i listan.")
    text: Text
    page: DeckPageRef | None = None
    key: TklDeckKey | None = None


class DeckProblemKind(StrEnum):
    UNREACHED = "nas-inte"  # a route no page of the profile reaches
    MISSING = "finns-inte"  # a key pointing at something the station does not have


class TklDeckProblem(Contract):
    """One of Studio's checks that failed (SD44), with where it is, so that it can be clicked."""

    kind: DeckProblemKind
    text: Text
    page: int | None = Field(default=None, ge=0, description="Sidan i ägarens profil.")
    cell: int | None = Field(default=None, ge=0)
    route: TklDeckRoute | None = None


class TklDeckChecks(Contract):
    """Studio's checks of a profile (SD44): every train route and shunting route is reached
    from some page, and no key points at something that does not exist."""

    routes: int = Field(ge=0, description="Stationens vägar.")
    reached: int = Field(ge=0, description="Vägarna som nås från decket.")
    quick: int = Field(default=0, ge=0, description="Vägarna som har en snabbväg.")
    problems: list[TklDeckProblem] = Field(default_factory=list)


class DeckButtonGroup(StrEnum):
    """Knappar in Studio (SD41): the station's keys by group."""

    TRAFFIC = "trafiken"  # Tågknapp, Linjeknapp, Larm och klocka, Dagens vägar, Favoriter
    TRAIN_ROUTES = "tagvagar"
    SHUNTING_ROUTES = "vaxlingsvagar"
    PLACES = "platser"
    SIGNALS = "signaler"
    FUNCTIONS = "funktioner"  # the actions, the panel functions, Läge and ▶
    YARD_TRACKS = "bangard-spar"  # Bangård: the part's tracks with their switch streets (#87)
    YARD_OUTS = "bangard-vagar-ut"  # Bangård: the part's routes out


class TklDeckButton(Contract):
    """A row in Knappar: a key the owner can drag onto the deck, and where it is now."""

    group: DeckButtonGroup
    key: TklDeckKey
    text: Text
    where: Text = Field(default="", description="Var den ligger på decket, eller hur den nås.")
    missing: bool = Field(default=False, description="Vägen nås inte från decket (SD44).")
    pieces: list[Name] = Field(default_factory=list, description="Vägens spårbitar, för bilden.")


class TklDeckStudioPage(Contract):
    """A page of the owner's profile as Studio draws it: every key's face against an empty
    interlocking, so that the owner sees what the key is."""

    ref: DeckPageRef
    faces: list[TklDeckFace]
    changed: bool = Field(default=False, description="Sidan har egna ändringar.")


class TklDeckSize(Contract):
    """A size to choose in Studio, with its own default and the owner's changes (SD32)."""

    size: DeckModelId
    name: Text
    grid: TklDeckGrid
    decks: int = Field(default=0, ge=0, description="Deck på datorn med den här storleken.")
    deviations: int = Field(default=0, ge=0)
    to_check: int = Field(default=0, ge=0)
    problems: int = Field(
        default=0, ge=0, description="Kontrollernas problem (SD44), för storlekar som används."
    )


class TklDeckStudio(Contract):
    """Studio, Inställningar, Stream Deck, Sidor (SD38–SD45): the owner's profile for one size,
    the default's deviations, Att kolla, the checks and the list Knappar."""

    size: DeckModelId
    sizes: list[TklDeckSize] = Field(default_factory=list)
    profile: TklDeckProfile
    pages: list[TklDeckStudioPage] = Field(default_factory=list)
    deviations: list[TklDeckDeviation] = Field(default_factory=list)
    saved: bool = Field(default=True, description="Avvikelserna är de som är sparade.")
    to_check: list[TklDeckToCheck] = Field(default_factory=list)
    checks: TklDeckChecks
    buttons: list[TklDeckButton] = Field(default_factory=list)
    message: Text | None = None
    part: Id | None = Field(
        default=None, description="Delen vars deck, Bangård, visas; inget för tågklareraren."
    )
    roles: list[TklDeckRole] = Field(
        default_factory=list, description="Rollerna att välja: tågklareraren och delarna (#87)."
    )


class TklDeckEdit(Contract):
    """The owner's deviations for one size: shown before they are saved, or saved (SD40)."""

    size: DeckModelId
    deviations: list[TklDeckDeviation] = Field(default_factory=list, max_length=DECK_DEVIATIONS)
    part: Id | None = Field(
        default=None, description="Delens deck, Bangård (#87 del d); inget för tågklareraren."
    )


class DeckSuggestion(StrEnum):
    """Föreslå (SD45): the rule a page is made again by."""

    GEOGRAPHIC = "geografiskt"  # as the default lays it out, west to east
    DAILY = "dagens"  # Dagens vägar, from TKL's runtime data (SD23)
    MOST_USED = "mest-anvanda"  # the counted routes, the most used first (SD24)


class TklDeckSuggest(TklDeckEdit):
    page: DeckPageRef
    rule: DeckSuggestion


class DeckTried(StrEnum):
    DID = "gick"  # the key did what it does: the interlocking said yes, or the deck changed
    REFUSED = "nej"  # the interlocking said no, with its reason
    NOTHING = "inget"  # nothing happened, with what the deck said


class TklDeckKeyTried(Contract):
    """One key pressed by Prova alla knappar (SD47)."""

    page: int = Field(ge=0)
    page_name: Text
    cell: int = Field(ge=0)
    label: Text
    result: DeckTried
    said: Text = ""


class TklDeckProva(Contract):
    """Prova alla knappar (SD47): every key of every page of one size pressed against an empty
    interlocking, a copy that is never the live one, in the background with its progress."""

    size: DeckModelId | None = None
    running: bool = False
    done: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    did: int = Field(default=0, ge=0)
    refused: int = Field(default=0, ge=0)
    nothing: int = Field(default=0, ge=0)
    keys: list[TklDeckKeyTried] = Field(default_factory=list)
    started: datetime | None = None
    finished: datetime | None = None
    message: Text | None = None
    part: Id | None = Field(default=None, description="Delens deck, Bangård (#87 del d).")


class TklDeckProvaAsk(Contract):
    size: DeckModelId
    part: Id | None = Field(default=None, description="Delens deck, Bangård (#87 del d).")


class TklDeckChange(Contract):
    """Studio, Deck (SD46): what the owner sets for one deck on this computer. What is not
    given, or null, stays as it is; an empty name or start page takes it away."""

    name: KeyText | None = None
    brightness: int | None = Field(default=None, ge=0, le=100)
    hold: DeckHold | None = None
    sleep: int | None = Field(default=None, ge=0, le=240)
    lock_key: bool | None = None
    opens_in: DeckMode | None = None
    opens_on: KeyText | None = None
    workplace: Name | None = None
    role: KeyText | None = Field(
        default=None,
        description="Rollen (#87 del d): delens id, eller tom för tågklareraren.",
    )


# --- Fjärrstyrning (#36 del c): the remote interlocking and the fjärrbild -------------------------
# TKL started in the remote role is a remote interlocking (fjärrställverk) with no station of its
# own (FR1, TKL47): it connects as the station protocol's client kind remote with its remote
# area, and a station hands itself over to it (FR4, FR8). A station's own TKL controls a
# neighbour with the same fjärrbild (FR3). The fjärrbild is drawn from Hubben's Overview: only
# what the stations report, never what was sent (FR13). Routes are asked for and taken away,
# and the controlled stations are cleared, with ordinary station commands (FR11, FR17).


class TklRemote(Contract):
    """The remote interlocking TKL runs as, set at first start (FR1, TKL47): its name in
    Klienter and the remote area it asks for, the plan's area or driftplatser written by hand."""

    name: Text
    area: Id | None = Field(default=None, description="Planens fjärrområde (FR49).")
    places: list[Id] = Field(
        default_factory=list,
        max_length=40,
        description="Driftplatserna skrivna för hand, i ordning längs linjen. Tomt: planens "
        "fjärrområde.",
    )


class TklRemoteSetUp(Contract):
    """Första start som Fjärrställverk (ingen egen station): namnet, fjärrområdet och PIN:en.
    I TKL i molnet med TrainMeet ID låser inloggningen i stället, och PIN:en utelämnas."""

    name: str = Field(min_length=1, max_length=40)
    area: Id | None = None
    places: list[Id] = Field(default_factory=list, max_length=40)
    pin: str | None = Field(
        default=None, pattern=r"^[0-9]{4,12}$", description="4–12 siffror. Skrivs aldrig ut."
    )


class TklRemoteArea(Contract):
    """A remote area in the plan, as the hub has it (FR49, PLAN-33)."""

    id: Id
    name: Text
    places: list[Id] = Field(description="Driftplatserna i ordning längs linjen.")


class TklRemotePlace(Contract):
    """A driftplats in the plan, to choose a remote area by hand."""

    place: Id
    code: Text
    name: Text


class TklRemoteAreas(Contract):
    """The plan's remote areas and driftplatser at a hub, for Anslut (FR49)."""

    areas: list[TklRemoteArea] = Field(default_factory=list)
    places: list[TklRemotePlace] = Field(default_factory=list)
    message: Text | None = Field(
        default=None, description="Varför listan är tom, till exempel ingen träff igång."
    )


class TklRemoteConnect(Contract):
    """Anslut som fjärrställverk (FR4): the hub, the code over the internet, and the remote area,
    the plan's or driftplatser written by hand. Trafikledningen approves it per driftplats."""

    address: Text = Field(max_length=200)
    code: Text | None = Field(default=None, max_length=20)
    area: Id | None = None
    places: list[Id] = Field(default_factory=list, max_length=40)


class TklFjarr(Contract):
    """Fjärrbildens data (FR31–FR38): Hubben's overview of the places TKL controls, is offered,
    is approved for, and their neighbours, with what this TKL controls and is offered now
    (FR8). When the hub cannot be reached, the last good one is kept and marked stale."""

    overview: Overview | None = None
    client_id: Id | None = Field(
        default=None,
        description="TKL:s klient i Hubben: tågvägarna den begärt och stationerna den styr.",
    )
    controls: list[Id] = Field(default_factory=list, description="Driftplatserna TKL fjärrstyr nu.")
    offers: list[OfferHere] = Field(
        default_factory=list, description="Stationer som erbjuds TKL och väntar på svar."
    )
    stale: bool = False
    heard: datetime | None = None
    message: Text | None = None


TklState.model_rebuild()
