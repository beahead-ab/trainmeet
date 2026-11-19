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
    FeedbackType,
    Name,
    NodeType,
    PanelBuilding,
    PanelFunctionType,
    Point,
    Position,
    SignalType,
    StationModel,
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
    outside_version: int | None = Field(default=None, description="Utsidan som följde med.")
    message: Text | None = None
    preview: bool = Field(
        default=False, description="En provkörning i Provbanan, inte en riktig träff (STUDIO-12)."
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
    """Lägena (SD63): a group of pages with the same way of working. Bangård comes with the
    shunter's deck (#87)."""

    TRAINS = "tagen"
    PLACES = "platser"
    TRACK_PLAN = "sparplan"


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


class DeckAction(StrEnum):
    RELEASE = "los"  # Lös ut; hold: all (SD29)
    ARRIVED = "ankommit"  # Ankommit, in drift (SD10, SD27)
    RUN = "kor"  # Kör, only in Prova and the reference stations (SD28)
    CANCEL = "avbryt"
    BACK = "tillbaka"
    LOCK = "las"  # Lås (Fika): TKL is locked for the whole station (SD30), on the page Läge


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


class TklDeckKey(Contract):
    """A key in a profile: its type from the catalogue and what it points at, as data (SD5)."""

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
    text: KeyText = Field(default="", description="Knappens text, när den är given.")


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
    never stored as code. The owner's changes in Studio come in del c."""

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


class TklDeckFace(Contract):
    """What a key shows: the prototype's look, with the locked colours (SD3, SD6)."""

    type: Literal[
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
        "case",
        "answer",
        "variant",
        "goal",
        "contact",
        "clock",
        "empty",
    ] = "empty"
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


class TklDecks(Contract):
    """The decks this TKL knows (SD35), and whether it owns decks over USB itself: a local TKL
    does, so that a deck works without an open tab (SD50); TKL in the cloud never opens USB."""

    usb: bool = Field(description="TKL sköter deck över USB på den här datorn.")
    usb_problem: Text | None = Field(
        default=None, description="Varför TKL inte når USB just nu, till exempel utan libhidapi."
    )
    decks: list[TklDeckStatus] = Field(default_factory=list)


class TklDeckRoute(Contract):
    start: Name
    end: Name
    kind: RouteKind


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
