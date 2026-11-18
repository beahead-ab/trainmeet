"""TrainMeet TKL's own API: between TKL's server and its web app (apps/tkl), under /api/tkl/1/.

TKL is a program of its own (ST3, KLAR-22). Its server runs on the station's computer or a
Raspberry Pi and holds what TKL owns (KLAR-08): the station's outside and the PIN that locks
it. When TKL connects to a meet it also holds the key from the approval; the key stays in the
server and never reaches the browser or a log (H31). Towards the hub TKL speaks the station
protocol (contracts/station.py), nothing else.

Level 0 (TKL21, KLAR-15): the tracks and exits are written as a list, without a drawing. The
list is the station's outside; a new version of it is made with a button (TKL25).

Level 1–2 (#83): the station's model (contracts/station_model.py) is imported in Studio and kept
with the station, versioned with the outside. The web app draws the station as a panel: the
layout engine's proposal on the grid, or the panel built from the station's own track plan
(STD-09, STD-25). The four reference stations can be looked at and used as one's own.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final, Literal

from pydantic import Field

from contracts.common import Contract, Id, Text
from contracts.station import (
    Action,
    ApprovalStatus,
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
    Point,
    Position,
    SignalType,
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
    """Studio at level 0: the list as it is on the computer, and the versions made of it."""

    draft: StationOutside
    versions: list[OutsideVersion] = Field(default_factory=list, description="Senaste först.")
    changed: bool = Field(
        description="Listan eller stationsmodellen skiljer sig från den senaste versionen."
    )
    station_model: bool = Field(
        default=False, description="Stationen har en stationsmodell (nivå 1–2, #83)."
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
