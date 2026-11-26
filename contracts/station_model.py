"""trainmeet.station-model/1: the station model, one file per station (<station>.tkl.json).

Every station is data, never code (TKL23, TKL40). TKL Studio writes the model and the
interlocking reads it (STD-06, TKL92). All roads in, a drawing in Studio, AnyRail through CAD, a
signal plan or JMRI, end in this one model (STD-01, TKL41).

The model is a graph: track pieces run from node to node. A switch, a slip or a crossing is a
node where three or four pieces meet. A signal stands at a node and faces the trains that come
along one of its pieces, so a stop lamp can stand at the very end of a track.
Levers say which position each switch gets in + and -: two or more parts on one lever, parts that
lie reversed, and switches that drag another along in one position (STD-29, TKL104).

A station may be divided into parts (delställverk, TKL97–TKL103): a fixed area with its own
operator, its border switches and their owner, its switch streets and the routes out it may
request. The interlocking is still one, and locks every route.

Never stored: train routes, shunting routes, lever positions and conflicts. tkl/standard derives
them from the model (STD-07). The panel's layout is derived too, until the owner redraws the
track plan; then the plan is stored here as `panel` (STD-25, TKL81).

Names are the owner's own and shown as they are (STD-17): "101", "Vx4", "1/5", "Spår 31". They
are the keys inside the file, so they are free text, not ids.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Annotated, Any, Final, Literal

from pydantic import Field, StringConstraints

from contracts.common import Contract, Id, Text

FORMAT: Final = "trainmeet.station-model/1"

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
"""The owner's name of a thing in the model, used as its key: "101", "1/5", "Stopp 3"."""

Point = tuple[float, float]
"""A point in the real geometry, in millimetres, x east and y down as in the drawing."""

Cell = tuple[float, float]
"""A place on the panel's grid: column and row, counted in cells (halves allowed)."""


class Position(StrEnum):
    """A switch's two positions. + is straight (rakt), - is diverging (avvikande)."""

    PLUS = "+"
    MINUS = "-"


class Source(StrEnum):
    """Where an item in the model comes from (§2 "source", TKL41)."""

    DRAWN = "drawn"  # ritad i Studio
    PHOTO = "photo"  # uppmätt ur foto
    SIGNAL_PLAN = "signal_plan"  # ur ägarens signalplan
    ANYRAIL = "anyrail"  # ur AnyRail, genom CAD
    JMRI = "jmri"  # ur JMRI-filen
    ASSUMED = "assumed"  # antagen; syns gul i Studio tills den är bekräftad
    LAYOUT = "layout"  # inlärd på banan i Koppla in: givaren slog till, växeln lades om


class Origin(Contract):
    """The source of one item, and whether the owner has confirmed it (RS5, RS7)."""

    source: Source
    confirmed: bool = Field(
        default=False, description="Ägaren har bekräftat uppgiften. Antaget syns gult i Studio."
    )
    ref: Text | None = Field(
        default=None,
        description="Uppgiftens namn i källan, till exempel AnyRail-id 1680 eller Vx162.",
    )
    note: Text | None = None


class Address(Contract):
    """A decoder or detector address on a bus (level 3).

    Its own origin says where the address comes from and whether it is confirmed on the layout:
    in Koppla in a confirmed address is green, an address that is only given is yellow
    (STUDIO-17). The object's origin is about the object itself, as drawn or imported.
    """

    bus: Name = Field(default="LocoNet", description="Bussen adressen gäller på.")
    number: int = Field(ge=0, le=65535)
    reversed: bool = Field(
        default=False,
        description="Omvänd polaritet (STUDIO-24): växelns rakt är kortets thrown, signalens "
        "kör är kortets thrown, och givaren är belagd när den släpper.",
    )
    origin: Origin | None = Field(
        default=None,
        description="Var adressen kommer ifrån. Bekräftad på banan: grönt i Koppla in.",
    )


WITHOUT: Final = "without"
Detection = Address | Literal["without"]
"""An address, or "without": the owner has said that there is none (TKL26)."""


class FeedbackType(StrEnum):
    """Växelns återrapport (STUDIO-24, ur cda-tkl)."""

    CARD = "card"  # från kortet: växelrapporten på växelns egen adress, som MGP-korten sänder
    SENSORS = "sensors"  # två givare i växelmotorn: en för rakt och en för avvikande
    NONE = "none"  # ingen: TKL räknar ordern som läget
    MANUAL = "manual"  # manuell: växeln läggs för hand och har ingen adress (Utan adress)


class SwitchFeedback(Contract):
    """How a switch tells where it lies, at level 3. With two sensors, each sensor is active
    when the switch lies in its position, and both passive while it moves."""

    type: FeedbackType
    straight: Address | None = Field(default=None, description="Givaren för rakt (+).")
    diverging: Address | None = Field(default=None, description="Givaren för avvikande (-).")


# --- The graph --------------------------------------------------------------------------


class NodeType(StrEnum):
    """What is at a node. A node joins track pieces; how many depends on the type."""

    SWITCH = "switch"  # växel eller korsningsväxel: 3 eller 4 spårbitar
    CROSSING = "crossing"  # korsning utan växel: 4 spårbitar
    SIGNAL_POINT = "signal_point"  # signalpunkt: 2
    BLOCK_BOUNDARY = "block_boundary"  # gräns mellan två spårledningar: 2
    MODULE_JOINT = "module_joint"  # modulskarv: 2
    JOINT = "joint"  # skarv i ritningen utan annan betydelse: 2
    STOP_POINT = "stop_point"  # stoppunkt där vägar börjar och slutar utan signal: 1 eller 2
    BUFFER_STOP = "buffer_stop"  # stoppbock: 1
    LINE_EXIT = "line_exit"  # linjeutfart, stationens gräns mot linjen: 1
    TURNTABLE = "turntable"  # vändskivan: ett spår per stråle


class Node(Contract):
    id: Name
    type: NodeType


class TrackPiece(Contract):
    """Spårbit: a piece of track from one node to another."""

    id: Name
    start: Name = Field(description="Från-nod.")
    end: Name = Field(description="Till-nod.")
    track: Text | None = Field(default=None, description="Spårnummer, till exempel 1, 31 eller 1a.")
    geometry: list[Point] = Field(
        default_factory=list,
        description="Verklig form ur ritningen, från start till slut, för den mjuka vyn (TKL42).",
    )
    origin: Origin | None = None


class SwitchType(StrEnum):
    """Växeltyp (RS1)."""

    ORDINARY = "ordinary"  # vanlig växel
    Y = "y"  # Y-växel
    SINGLE_SLIP = "single_slip"  # enkel korsningsväxel
    DOUBLE_SLIP = "double_slip"  # dubbel korsningsväxel
    CROSSING = "crossing"  # korsning utan växel


class SwitchControl(StrEnum):
    """Who lays the switch. Only TKL's switches have a lever, and no route crosses another."""

    TKL = "tkl"  # TKL lägger den
    MANUAL = "manual"  # manuell, utan adress; TKL lägger den aldrig (TKL26, RS5)
    PLANNED = "planned"  # planerad, inte byggd än
    NOT_LAID = "not_laid"  # finns men läggs inte från ställverket, med skälet i note


class SwitchPath(Contract):
    """A way through a slip or a crossing: two of its pieces, and the positions it needs."""

    between: tuple[Name, Name]
    positions: dict[Name, Position] = Field(
        default_factory=dict, description="Delarnas lägen. Tomt för en korsning utan växel."
    )


class SlipPart(Contract):
    """One switch number in a slip, with its own position and lever, such as 22a in 22a/23."""

    number: Name
    address: Address | None = None
    feedback: SwitchFeedback | None = None


class Switch(Contract):
    """Växel, korsningsväxel eller korsning: the node where pieces divide or cross.

    An ordinary switch or a Y-switch has a trunk, a straight leg (+) and a diverging leg (-); its
    number is the part that a lever lays. A slip has four pieces, its parts and the paths through
    it; a crossing without a switch has only the paths.
    """

    number: Name = Field(description="Ägarens nummer, som det står (STD-17).")
    type: SwitchType
    node: Name
    trunk: Name | None = Field(default=None, description="Stam.")
    straight: Name | None = Field(default=None, description="Rakt ben, läget +.")
    diverging: Name | None = Field(default=None, description="Avvikande ben, läget -.")
    parts: list[SlipPart] = Field(default_factory=list, description="Korsningsväxelns delar.")
    paths: list[SwitchPath] = Field(default_factory=list)
    control: SwitchControl = SwitchControl.TKL
    note: Text | None = Field(default=None, description="Varför TKL inte lägger den.")
    design: Text | None = Field(default=None, description="Hand och radie som källan säger.")
    address: Address | None = Field(
        default=None,
        description="Nivå 3. Saknas den är växelns nummer adressen som förval (STUDIO-19).",
    )
    feedback: SwitchFeedback | None = Field(default=None, description="Återrapport (nivå 3).")
    origin: Origin | None = None


class Derailer(Contract):
    """Spårspärr (TKL129): it lies at a node between two pieces and derails what comes.

    It has two positions, as a switch: + is av, so the track is open, and - is på. A route over
    it lays it av; a route it protects lays it på, as flank protection (sidoskydd, STV-20). Its
    number is its lever's, and it has a lever of its own.
    """

    number: Name = Field(description="Ägarens nummer, som det står (STD-17).")
    node: Name = Field(description="Noden mellan de två spårbitarna där den ligger.")
    control: SwitchControl = SwitchControl.TKL
    note: Text | None = Field(default=None, description="Varför TKL inte lägger den.")
    address: Address | None = Field(
        default=None,
        description="Nivå 3. Saknas den är spårspärrens nummer adressen som förval (STUDIO-19).",
    )
    feedback: SwitchFeedback | None = Field(
        default=None, description="Återrapport (nivå 3), som för en växel: + av, - på."
    )
    origin: Origin | None = None


class Lever(Contract):
    """Spak: for + and -, the position each switch gets.

    The lever's own switches are in both positions. A switch that only one position names is
    dragged along by the lever in that position (drar med, TKL104) and has a lever of its own.
    An own switch that gets - in the lever's + lies reversed (omvänd).
    """

    id: Name = Field(description='Till exempel "101/102" eller "22".')
    plus: dict[Name, Position]
    minus: dict[Name, Position]


class SignalType(StrEnum):
    """The signal catalogue (§2). New types are added here for all stations (STD-19)."""

    HSI = "hsi"  # huvudsignal
    HDVSI = "hdvsi"  # huvuddvärgsignal, kombinerad
    DVSI = "dvsi"  # dvärgsignal
    FSI = "fsi"  # försignal
    STOP_LAMP = "stop_lamp"  # slutpunktsstopplykta: bara slutpunkt (RS3)


class Signal(Contract):
    name: Name
    type: SignalType
    lamps: int | None = Field(default=None, ge=1, le=9, description="Hsi 2, Hsi 3 …")
    node: Name
    approach: Name = Field(
        description="Spårbiten tåget kommer på mot signalen. Signalen gäller i den riktningen."
    )
    planned: bool = Field(default=False, description="Planerad, finns inte än.")
    address: Detection | None = Field(
        default=None,
        description="Nivå 3. Utan: en virtuell signal, som bara visas i panelen (TKL26).",
    )
    origin: Origin | None = None


DROP_DELAY_MAX: Final = 60.0
"""The longest släpptid, in seconds (STUDIO-35)."""


class TrackCircuit(Contract):
    """Spårledning.

    Its släpptid (STUDIO-35, trainmeet #274) is for a sensor that sees only what is in front of
    it, such as an IR sensor, which is free in every gap between the wagons: the circuit counts
    as occupied until its sensor has been free that long. It only keeps a circuit occupied
    longer, so occupancy still frees nothing by itself (STV-16)."""

    name: Name
    pieces: list[Name]
    detection: Detection | None = Field(default=None, description="Givare, eller utan.")
    drop_delay: float = Field(
        default=0,
        ge=0,
        le=DROP_DELAY_MAX,
        description="Släpptid i sekunder (STUDIO-35): spårledningen räknas som belagd tills "
        "givaren har varit fri så länge, för en IR-givare som släpper mellan vagnarna. 0 är "
        "ingen.",
    )
    origin: Origin | None = None


class StationTrack(Contract):
    """Stationsspår: what the station's outside is made of (TKL92).

    Its id in the outside is its short name, or `outside_id` when the model gives one, so that
    the owner can rename the track and keep the id the meets know (tkl/standard/outside.py).
    """

    id: Id = Field(description="Det korta namnet, till exempel 1a.")
    label: Text = Field(description="Till exempel Spår 1a.")
    pieces: list[Name] = Field(default_factory=list)
    outside_id: Id | None = Field(
        default=None,
        description="Spårets fasta id i utsidan, när det ska vara ett annat än det korta namnet. "
        "Behåller id:t när spåret byter namn.",
    )


class LineExit(Contract):
    """Linjeutfart: where a track leaves the station for the line.

    Its id is the owner's free text, such as "Väst 1"; the outside's exit gets an id derived
    from it, or `outside_id` when the model gives one (tkl/standard/outside.py).
    """

    id: Name = Field(description="Bokstav eller id, till exempel A1.")
    node: Name
    neighbour: Text | None = Field(default=None, description="Grannstationen.")
    tracks: list[Name] = Field(default_factory=list, description="Stationsspåren som når hit.")
    signals: list[Name] = Field(default_factory=list, description="Signalerna vid gränsen.")
    outside_id: Id | None = Field(
        default=None,
        description="Utfartens fasta id i utsidan. Saknas det räknas det fram ur id: "
        "Väst 1 blir Vast-1. Behåller id:t när utfarten byter namn.",
    )
    origin: Origin | None = None


class TurntableTrack(Contract):
    piece: Name
    angle: float = Field(description="Strålens vinkel i grader, moturs från öster.")


class Turntable(Contract):
    """Vändskivan (RS4): its node and its tracks, with their angles."""

    id: Name
    node: Name
    diameter: float | None = Field(default=None, description="I millimeter.")
    tracks: list[TurntableTrack]
    origin: Origin | None = None


class PanelFunctionType(StrEnum):
    """The panel functions' catalogue. New functions are added here for all (STD-19)."""

    SIGNAL_STOP = "signal_stop"  # signalstopp (område)
    LOCAL_RELEASE = "local_release"  # lokal frigivning (TKL44, STD-14)
    TRACTION_CURRENT = "traction_current"  # körström
    OUT_OF_SERVICE = "out_of_service"  # spår ur drift
    EMERGENCY_RELEASE = "emergency_release"  # nödutlösning
    TURNTABLE = "turntable"  # vändskiva
    PROGRAMMING_TRACK = "programming_track"  # programmeringsspår (STV-53, TKL106)


class PanelFunction(Contract):
    """A button on the panel, from the catalogue, with its parameters."""

    type: PanelFunctionType
    name: Text
    track_circuits: list[Name] = Field(default_factory=list, description="Området.")
    switches: list[Name] = Field(
        default_factory=list, description="Lokala växlar, som läggs med knappar på modulerna."
    )
    locked: dict[Name, Position] = Field(
        default_factory=dict, description="Skyddsväxlarnas spakar och läget de låses i."
    )
    signals: list[Name] = Field(default_factory=list, description="Signaler som visar växling.")
    pieces: list[Name] = Field(default_factory=list, description="Spåret funktionen gäller.")
    at: Name | None = Field(default=None, description="Platsen för knappen, till exempel en nod.")
    modes: list[Text] = Field(default_factory=list, description="Körströmmens lägen, 2R och 3R.")
    codes: dict[Name, Text] = Field(
        default_factory=dict, description="Knappens kod per skal, till exempel L01 i 95."
    )
    note: Text | None = None
    origin: Origin | None = None


# --- The panel's track plan (STD-25–STD-28, TKL81, TKL82) --------------------------------


class PanelGrid(Contract):
    dx: float = Field(gt=0, description="Rutans bredd.")
    dy: float = Field(gt=0, description="Rutans höjd.")


class PanelTurntable(Contract):
    node: Name
    radius: float = Field(gt=0)


class PanelPiece(Contract):
    id: Name
    reversed: bool = Field(default=False, description="Spårbiten går åt andra hållet längs vägen.")


class PanelTrack(Contract):
    """A track on the grid: from a node to another, over the cells where it turns."""

    start: Name
    end: Name
    pieces: list[PanelPiece]
    via: list[Cell] = Field(default_factory=list)
    joints: list[float] = Field(
        default_factory=list, description="Skarvarna mellan spårbitarna, i rutor längs vägen."
    )
    link: bool = Field(default=False, description="Länken mellan två växlar i en korsväxel.")
    free: bool = Field(default=False, description="Får gå i vilken vinkel som helst.")


class PanelPlacement(Contract):
    piece: Name
    at: float = Field(ge=0, le=1, description="Läget längs spårbiten, 0 i början och 1 i slutet.")
    reversed: bool = Field(default=False, description="Mot spårbitens riktning.")


class PanelTrackName(Contract):
    name: Text
    piece: Name
    at: float = Field(ge=0, le=1)


class PanelBuilding(Contract):
    cells: tuple[float, float, float, float]
    name: Text


class PanelHidden(Contract):
    pieces: list[Name] = Field(default_factory=list)
    switches: list[Name] = Field(default_factory=list)
    crossings: list[Name] = Field(default_factory=list)


class PanelDeviationSwitch(Contract):
    drawing_number: Name | None = Field(
        default=None, description="Växelns nummer i ritningen. Saknas: växeln är ny."
    )


class PanelDeviation(Contract):
    """Where the plan departs from the drawing, said out loud (TKL82, STD-28).

    The names here are the drawing's, so a piece that is not shown need not be in the model.
    """

    reason: Text
    not_shown: PanelHidden = Field(default_factory=PanelHidden)
    rewired: list[Name] = Field(default_factory=list, description="Omkopplade spårbitar.")
    new_pieces: list[Name] = Field(default_factory=list)
    switches: dict[Name, PanelDeviationSwitch] = Field(
        default_factory=dict, description="Nya växlar och växlar med ett annat nummer."
    )
    knots: list[Name] = Field(default_factory=list, description="Noder mitt på ett annat spår.")


class PanelPlan(Contract):
    """Spårplan: the schematic panel, as the owner has redrawn it on the grid.

    Del b builds and checks the panel from it; the model only holds it.
    """

    basis: Text | None = Field(default=None, description="Vad planen är ritad efter.")
    grid: PanelGrid
    turntable: PanelTurntable | None = None
    nodes: dict[Name, Cell]
    tracks: list[PanelTrack]
    signals: dict[Name, PanelPlacement] = Field(
        default_factory=dict,
        description="Var signalerna och de andra namngivna punkterna står: stoppunkter, "
        "utfarter och stoppbockar.",
    )
    track_names: list[PanelTrackName] = Field(default_factory=list)
    name_offset: float | None = Field(default=None, description="Spårnamnet över spåret.")
    platforms: list[tuple[float, float, float, float]] = Field(default_factory=list)
    building: PanelBuilding | None = None
    function_sides: dict[Text, Literal["over", "under"]] = Field(
        default_factory=dict, description="Panelfunktionens knapp över eller under spåret."
    )
    deviation: PanelDeviation | None = None


# --- Delställverk: a station in parts (TKL97–TKL103) ---------------------------------------


class PartOwner(StrEnum):
    """Who steers a border switch (TKL99)."""

    STATION = "station"  # stationens ställverk, tågklareraren: förvalet
    PART = "part"  # delen


class BorderSwitch(Contract):
    """Gränsväxel (grindväxel): a switch at the border between a part's area and the station's.

    Its owner lays it both ways. The other side may always lay it towards the part's area, where
    it keeps the two apart, and never out (TKL99, RANG-12); Klart and Grindar lay it back there.
    A route out over it is a request that the station's interlocking sets."""

    switch: Name = Field(description="Växelns nummer, eller en korsningsväxels del.")
    owner: PartOwner = PartOwner.STATION
    towards_part: Position = Field(
        description="Läget mot delens område, som skiljer delen från stationen: dit får den som "
        "inte äger växeln alltid lägga den, aldrig ut."
    )


class PartRules(Contract):
    """The rules at the border, set per station in Studio (TKL99). The defaults are those of
    the first station divided into parts (TKL99): the station steers the border switches, the
    part may lay them towards its area and never out, and an approved request can only be
    returned."""

    lays_towards_part: bool = Field(
        default=True,
        description="Delen får lägga stationens gränsväxlar mot sitt område, aldrig ut (RANG-12). "
        "Annars lägger bara stationen dem.",
    )
    one_way: bool = Field(
        default=True,
        description="Envägsregeln (RANG-09): en godkänd begäran kan delen bara lämna tillbaka, "
        "aldrig lägga själv, och stationen tar inte tillbaka den medan den är delens.",
    )


class PartSide(StrEnum):
    """Ände: the end of the part a switch street or a route out belongs to (TKL109, TKL122)."""

    LEFT = "left"  # vänster, väster
    RIGHT = "right"  # höger, öster


class SwitchStreet(Contract):
    """Växelgata (RANG-02): the part's switches laid straight out to a track with one press,
    without a route, a lock or a signal, as in old TKL. A switch in it that lies in a locked
    route refuses the whole street."""

    id: Name = Field(description="Till exempel V51.")
    name: Text = Field(description="Som knappen säger det, till exempel V 51.")
    side: PartSide | None = Field(default=None, description="Änden gatan hör till.")
    track: Text = Field(description="Spåret gatan leder till, till exempel 51 eller Lastspår 1.")
    positions: dict[Name, Position] = Field(description="Växlarna i gatan, med sina lägen.")


class RouteOut(Contract):
    """Begärd väg (RANG-03): a station route out over the border that the part may request.
    The station's interlocking sets it when the request is approved; until the part returns it
    the route is the part's (envägsregeln)."""

    id: Name = Field(description="Till exempel H3.")
    name: Text = Field(description="Som knappen säger det, till exempel H 3.")
    side: PartSide | None = Field(default=None, description="Änden vägen går ut från.")
    track: Text = Field(description="Stationens spår vägen leder till, till exempel 3.")
    start: Name = Field(description="Vägens start, en signal i delens område.")
    end: Name = Field(description="Vägens mål på stationen.")


class StationPart(Contract):
    """Delställverk (TKL97–TKL103): a fixed area of the station with its own operator, against
    the station's one interlocking, which locks every route.

    Its area is the same kind of area as local release's (TKL103): track circuits or pieces,
    the switches the part lays freely and the signals in it. Its border is the border switches,
    with their owner, and the signals at the border. The part may be its own driftplats in
    Hubben (TKL101). Its switch streets and the routes out it may request belong to it."""

    id: Id = Field(description="Delens id, till exempel rangerbangarden. Skärmen nås på /del/<id>.")
    name: Text = Field(description="Till exempel Rangerbangården.")
    track_circuits: list[Name] = Field(default_factory=list, description="Området.")
    pieces: list[Name] = Field(default_factory=list, description="Området, utan spårledningar.")
    switches: list[Name] = Field(
        default_factory=list, description="Delens egna växlar, som den lägger fritt."
    )
    signals: list[Name] = Field(default_factory=list, description="Signalerna i området.")
    border: list[BorderSwitch] = Field(default_factory=list, description="Gränsväxlarna.")
    border_signals: list[Name] = Field(
        default_factory=list, description="Signalerna vid gränsen, där vägarna ut går över."
    )
    own_place: bool = Field(
        default=False,
        description="En egen driftplats i Hubben, som bemannas för sig (TKL101). Annars syns "
        "delen inte i Hubben.",
    )
    place: Id | None = Field(
        default=None, description="Driftplatsens id i Hubben, när delen är en egen driftplats."
    )
    code: Text | None = Field(
        default=None,
        description="Driftplatsens signatur i Hubben, när delen är en egen driftplats (TKL101). "
        "Tomt: namnet används.",
    )
    rules: PartRules = Field(default_factory=PartRules)
    streets: list[SwitchStreet] = Field(default_factory=list, description="Växelgatorna.")
    routes_out: list[RouteOut] = Field(
        default_factory=list, description="Vägarna ut över gränsen som delen får begära."
    )
    note: Text | None = None
    origin: Origin | None = None


# --- The station ------------------------------------------------------------------------


class StationModel(Contract):
    """Stationsmodellen: one station, level 1 or 2; level 3 adds the addresses, learnt and
    confirmed in Studio's Koppla in."""

    format: Literal["trainmeet.station-model/1"] = FORMAT
    station_id: Id
    name: Text
    level: Literal[1, 2, 3]
    origin: Origin | None = Field(default=None, description="Källan för allt utan egen.")
    basis: list[Text] = Field(default_factory=list, description="Underlaget modellen bygger på.")
    nodes: list[Node]
    pieces: list[TrackPiece]
    switches: list[Switch] = Field(default_factory=list)
    derailers: list[Derailer] = Field(
        default_factory=list, description="Spårspärrarna (TKL129): + av, - på."
    )
    levers: list[Lever] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    track_circuits: list[TrackCircuit] = Field(default_factory=list)
    station_tracks: list[StationTrack] = Field(default_factory=list)
    line_exits: list[LineExit] = Field(default_factory=list)
    turntables: list[Turntable] = Field(default_factory=list)
    functions: list[PanelFunction] = Field(default_factory=list)
    parts: list[StationPart] = Field(
        default_factory=list,
        description="Delställverken (TKL97): fasta områden med en egen operatör, mot stationens "
        "enda ställverk.",
    )
    panel: PanelPlan | None = None


def dump(model: StationModel) -> dict[str, Any]:
    """The model as JSON data, with the defaults left out: the form a model file is saved in."""
    data = model.model_dump(mode="json", exclude_defaults=True)
    return {"format": FORMAT, **data}


# An indented array of plain values, such as a point [x, y]: written on one line.
_FLAT_ARRAY = re.compile(r"\[\n[^\[\]{}]*\]")


def to_json(model: StationModel) -> str:
    """The text of a model file: the same model always gives the same bytes.

    Indented, with each point and each list of names on one line, so that a change shows as a
    change of a few lines.
    """
    text = json.dumps(dump(model), ensure_ascii=False, indent=1)
    flat = _FLAT_ARRAY.sub(lambda m: json.dumps(json.loads(m.group(0)), ensure_ascii=False), text)
    return flat + "\n"
