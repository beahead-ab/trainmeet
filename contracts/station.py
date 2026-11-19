"""trainmeet.station/1: the station protocol, for clients that draw their own screen.

TKL, the TMBox app (iPhone and Watch) and the dispatcher's views use it. Built on the old
Server's v2 (docs/protocol/v2), with the decisions of 4 November:
- Everything points at the place (driftplats), never at a train number alone (H29, A1).
- A client is approved in Klienter and gets a key for the meet and the place. Every command
  needs it, it survives restarts and can be revoked (H31). The key travels in the HTTP header
  `Authorization: Bearer <key>`, never in the body, so it never ends up in a log.
- train.handover is gone. Drift owns the train number on the section and shows trains on their
  way here and trains that have left (H22, H32). train.approaching is an event from Drift.
- New for TKL: section.occupancy (level 3 only) and signal.exit.
- The client is told which actions each call allows right now, so it never guesses a rule.

Remote control (fjärrstyrning, #36, TKL46–TKL48, TKL89) goes in the same envelope, with the same
key. A remote interlocking (fjärrställverk, TKL47) connects as the client kind `remote`, with no
station and with its remote area in `wants`; Trafikledningen approves it for those places as an
ordinary interlocking, which only gives the right to receive them (FR4). A station's own TKL hands
the station over with `place.offer`, the one offered answers with `place.offer.answer`, and only
the station's own TKL takes it back with `place.take_back` (FR7, FR8). Whoever controls the
station asks for routes from its catalogue with `route.request` and `route.cancel`. Hubben checks
who asks and what the catalogue says, never the safety (FR11, FR12): the station's own
interlocking answers with `route.response`, and reports the state at the overview level with
`route.state`, whole each time it changes. The remote picture draws only what the station reports
(FR13). The safety stays in the station; the inside never leaves it.

    GET  /api/station/1/overview?places=a,b   Overview: the remote picture's data, for the places
                                              the client runs, controls or is approved for, and
                                              their neighbours

Transport (Claude, draft): HTTP with JSON under /api/station/1/ and an event stream (SSE):

    POST /api/station/1/connect            ConnectRequest  -> ConnectReply
    GET  /api/station/1/connect/{client}   status of the approval; the key once, when approved
    GET  /api/station/1/places/{place}     Snapshot
    POST /api/station/1/commands           Command         -> Reply (always with the snapshot)
    GET  /api/station/1/places/{place}/events   Event stream (text/event-stream)
    POST /api/station/1/places/{place}/exits    ExitAnswer -> Snapshot: which exit (H26)
    PUT  /api/station/1/places/{place}/track-display  TrackDisplayChange -> Snapshot (BOXIOS-16)
    PUT  /api/station/1/push               PushToken: the phone's address for push (F20)
    DELETE /api/station/1/push             no more push to this client

Outside the meet's network the same calls go to the cloud hub's relay, under
/relay/{hub}/api/station/1/..., with the same key (SYNK-11). The address is in ConnectReply.relay.

The snapshot is the truth; events are hints to fetch it again, as in v2. A command answered
with `duplicate` had already been carried out: the reply is the first one's.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import Field, model_validator

from contracts.common import Contract, Id, Side, Text, TimeOfDay
from contracts.meet import ClearanceMode, TrackKind
from contracts.reasons import Reason
from contracts.station_outside import StationOutside

PROTOCOL: Final = "trainmeet.station/1"

MessageId = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,120}$")]


# --- Connecting and approval ------------------------------------------------------------


class ClientKind(StrEnum):
    TKL = "tkl"
    TMBOX_APP = "tmbox_app"  # TMBox iPhone and Apple Watch
    DISPATCH = "dispatch"  # the dispatcher's views
    REMOTE = "remote"  # fjärrställverket: en TKL utan egen station (TKL47, FR1)


class PlaceMode(StrEnum):
    """Driftformen (FR5, TKL48): one per place during the meet. A station is manned or
    remote-controlled, never both (FR6)."""

    MANNED = "manned"  # Bemannad
    OFFERED = "offered"  # Erbjuden: lämnad till någon som inte svarat än (FR8)
    REMOTE = "remote"  # Fjärrstyrd
    NO_CONTACT = "no_contact"  # Kontakt saknas, med stationen eller med den som fjärrstyr
    AUTOMATIC = "automatic"  # Automatik: Drifts automatik sköter platsen (F14)


class ConnectRequest(Contract):
    """The client says what it is, which station it is and which places it wants to run.
    A TKL that is not coupled in advance sends its outside along (H28).

    A station with parts that are their own driftplatser lists them in its outside (TKL101), and
    asks for one driftplats per part besides the station's (TRAFIK-35). Without wants Hubben
    fills them in: the station's place and each part's, coupled in advance in the version or
    found by the part's id or name. Trafikledningen approves each on its own in Klienter."""

    protocol: Literal["trainmeet.station/1"] = PROTOCOL
    protocols: list[Text] = Field(
        default_factory=lambda: [PROTOCOL], description="Alla versioner klienten talar."
    )
    kind: ClientKind
    name: Text = Field(description="Det trafikledningen ser i Klienter.")
    software: Text = Field(description="Program och version, till exempel TKL 0.1.0.")
    station_id: Id | None = None
    outside: StationOutside | None = None
    wants: list[Id] = Field(
        default_factory=list,
        description="Driftplatserna den vill köra. Tomt: Hubben föreslår stationens driftplats "
        "och en per del i utsidan (TRAFIK-35).",
    )
    code: Text | None = Field(
        default=None,
        description="Provbanans kod, bara i en provkörning: den visar vilken körning det gäller.",
    )
    level: int = Field(
        default=0,
        ge=0,
        le=3,
        description="Stationens nivå i TKL (0–3). Hubben tar emot section.occupancy bara från en "
        "station på nivå 3 (DRIFT-10, KLAR-16); den gäller till nästa anslutning.",
    )
    preview_only: bool = Field(
        default=False,
        description="Prova i TKL: bara en provkörning i Provbanan, aldrig en riktig träff. Hubben "
        "säger nej till en riktig träff (STUDIO-12).",
    )
    remote_area: Id | None = Field(
        default_factory=lambda: None,
        description="Bara för ett fjärrställverk: planens fjärrområde. Utan wants föreslår "
        "Hubben dess driftplatser (FR49).",
    )

    @model_validator(mode="after")
    def _check(self) -> ConnectRequest:
        if self.kind == ClientKind.REMOTE and (self.station_id or self.outside):
            raise ValueError("Ett fjärrställverk har ingen egen station (TKL47).")
        if self.remote_area is not None and self.kind != ClientKind.REMOTE:
            raise ValueError("Bara ett fjärrställverk ansluter med ett fjärrområde.")
        return self


class ApprovalStatus(StrEnum):
    WAITING = "waiting"  # under Väntar in Klienter
    APPROVED = "approved"
    REFUSED = "refused"
    REVOKED = "revoked"


class ClientPlace(Contract):
    """En driftplats som en TKL eller appen vill köra, med trafikledningens svar för just den
    (TRAFIK-35). En del av stationen som är egen driftplats står för sig, med stationens
    driftplats (PLAN-34). Klienter visar dem, och klienten själv får dem i ConnectReply, så att
    en TKL vet vilken driftplats som är stationens och vilken som är en dels."""

    place: Id
    status: ApprovalStatus = Field(
        description="Väntar, godkänd eller nekad för den här driftplatsen; återkallad när hela "
        "klienten är det."
    )
    part: Id | None = Field(
        default=None, description="Delen av stationen, med delens id i utsidan."
    )
    part_of: Id | None = Field(
        default=None, description="Stationens driftplats, när driftplatsen är en del av den."
    )


class ConnectReply(Contract):
    protocol: Literal["trainmeet.station/1"] = PROTOCOL
    client_id: Id
    status: ApprovalStatus
    places: list[Id] = Field(
        default_factory=list,
        description="Godkända driftplatser. Godkännandet gäller per driftplats, så en del som "
        "godkänns senare kommer med här, med samma nyckel (TRAFIK-35).",
    )
    wanted: list[ClientPlace] = Field(
        default_factory=list,
        description="Varje driftplats klienten vill köra eller är godkänd för, med svaret för "
        "just den och vilken del av stationen den är (TRAFIK-35, PLAN-34). Tomt från en äldre "
        "hubb.",
    )
    key: str | None = Field(
        default=None,
        description="Nyckeln, bara en gång: i första svaret efter godkännandet. Skrivs aldrig ut.",
    )
    message: Text | None = None
    relay: Text | None = Field(
        default=None,
        description="Adressen utanför träffens nät: molnhubbens relä till den här hubben, där "
        "samma anrop görs med samma nyckel (SYNK-11). Tomt när hubben inte är kopplad till molnet.",
    )
    preview: bool = Field(
        default=False,
        description="Körningen är en provkörning i Provbanan, inte en riktig träff (STUDIO-12).",
    )


# --- Commands ------------------------------------------------------------------------------


class Action(StrEnum):
    # DRIFT-40: when a station with parts (delställverk, TKL97) is remote-controlled, the parts'
    # requests and the list of trains ready to send travel in route.state (TKL100, TKL108); the
    # station forwards them (#36 del b).
    TRAIN_LOOKUP = "train.lookup"
    TRAIN_TRACK_CHANGE = "train.track.change"
    TRAIN_DEPARTED = "train.departed"
    TRAIN_ARRIVED = "train.arrived"
    TRAIN_POSITION_SET = "train.position.set"
    TRAIN_CREW_READY_SET = "train.crew_ready.set"
    TRAIN_SET_ASIDE = "train.set_aside"  # Ställ undan: a train that ended here frees its track
    CLEARANCE_REQUEST = "clearance.request"
    CLEARANCE_RESPONSE = "clearance.response"
    CLEARANCE_CANCEL = "clearance.cancel"
    LINE_AVAILABLE_PUBLISH = "line.available.publish"
    LINE_AVAILABLE_ACKNOWLEDGE = "line.available.acknowledge"
    SECTION_OCCUPANCY = "section.occupancy"
    SIGNAL_EXIT = "signal.exit"
    PLACE_LEAVE = "place.leave"  # lämna till automatiken (F14)
    PLACE_TAKE_BACK = "place.take_back"  # ta tillbaka från automatiken, och från fjärr (FR7)
    # Fjärrstyrning (#36, TKL89)
    PLACE_OFFER = "place.offer"  # stationens egen TKL lämnar över (FR8)
    PLACE_OFFER_ANSWER = "place.offer.answer"  # den som erbjuds tar emot eller avböjer
    ROUTE_REQUEST = "route.request"  # den som styr begär en tågväg ur katalogen (FR11)
    ROUTE_CANCEL = "route.cancel"  # den som styr tar bort en begärd eller låst väg
    ROUTE_RESPONSE = "route.response"  # stationens ställverk: låst, eller nej med skäl
    ROUTE_STATE = "route.state"  # stationens läge i översiktsnivå, helt varje gång


class RevisionScope(StrEnum):
    """Three separate revision spaces, as in v2 §5: never one global counter."""

    CALL = "call"
    CASE = "case"
    PLACE = "place"


class Revision(Contract):
    scope: RevisionScope
    key: Id
    value: int = Field(ge=0)


class MeetContext(Contract):
    """Which meet, version and game day the client saw. A command for another is refused
    with stale_meet_context, so an old choice never survives a change of meet or day."""

    meet_id: Id
    version: int = Field(ge=1)
    game_day: int = Field(ge=1)
    epoch: int = Field(ge=0, description="Ledarskapets epok; byts vid övertag.")


class Command(Contract):
    protocol: Literal["trainmeet.station/1"] = PROTOCOL
    message_id: MessageId = Field(description="Unikt per klient. Samma id ger samma svar.")
    client_id: Id
    place: Id
    context: MeetContext
    action: Action
    expected_revision: Revision | None = Field(
        default=None, description="Exakt en scope och nyckel; utelämnas för train.lookup."
    )
    payload: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> Command:
        model = PAYLOADS.get(self.action)
        if model is not None:
            model.model_validate(self.payload)
        return self


class TrainLookup(Contract):
    train_number: Text = Field(pattern=r"^[0-9]{1,5}$")


class TrackChange(Contract):
    call: Id
    track: Id = Field(description="Stationens spår-id, eller planens spårnamn utan station.")


class CallOnly(Contract):
    call: Id


class PlaceOnly(Contract):
    """Lämna or ta tillbaka: the command's own place, nothing more."""


class Arrival(Contract):
    call: Id
    track: Id | None = Field(default=None, description="Utan spår: första lediga standardspår.")


class Flag(Contract):
    call: Id
    value: bool


class ClearanceRequest(Contract):
    call: Id
    section: Id
    clearance_id: Id = Field(description="Klienten väljer id, så att omsändning blir dubblett.")


class ClearanceResponse(Contract):
    clearance_id: Id
    approved: bool


class ClearanceCancel(Contract):
    clearance_id: Id


class LineAvailable(Contract):
    call: Id
    section: Id


class LineAcknowledge(Contract):
    message_id: Id


class SectionOccupancy(Contract):
    """Level 3 only: a section's detection. The section is free when every part is empty.
    Accepted from a client that connected at level 3, for a section from its place (DRIFT-10).
    It stops direct clearance and the automation on the section, and never frees anything by
    itself (DRIFT-16)."""

    section: Id
    occupied: bool
    parts: dict[Id, bool] = Field(default_factory=dict)


class ExitSignalAspect(StrEnum):
    STOP = "stop"
    PROCEED = "proceed"
    UNKNOWN = "unknown"


class ExitSignal(Contract):
    """What the exit signal shows, for Lokföraren and the neighbour."""

    exit: Id
    section: Id
    aspect: ExitSignalAspect
    call: Id | None = None


# --- Fjärrstyrning (#36): handing over, and the routes asked for from afar ----------------------


class PlaceOffer(Contract):
    """place.offer: the station's own TKL hands the station to someone in Snapshot.remote's
    receivers (FR8). The offer stands for a minute (TKL125)."""

    to: Id = Field(description="Den som erbjuds: klientens id ur receivers.")


class OfferAnswer(Contract):
    """place.offer.answer: the one offered takes the station, which becomes Fjärrstyrd, or
    declines it. With the station's place as the command's place."""

    accept: bool


class RouteRequest(Contract):
    """route.request: whoever controls the station asks for a route from its catalogue (FR11).
    The id is the client's, so that a resend is a duplicate, as for clearance."""

    request_id: Id = Field(description="Klienten väljer id.")
    route: Id = Field(description="Tågvägens id i fjärrkatalogen (remote_routes).")
    call: Id | None = Field(default=None, description="Tåget, när det finns ett.")


class RouteCancel(Contract):
    """route.cancel: a route asked for or locked is taken away. The station's interlocking
    decides when it is released, as on the spot."""

    request_id: Id


class RouteResponse(Contract):
    """route.response: the station's interlocking has locked the route, or says no with a reason
    of its own: conflicting_route, switch_not_in_control, area_released or track_occupied."""

    request_id: Id
    locked: bool
    reason: Reason | None = None

    @model_validator(mode="after")
    def _check(self) -> RouteResponse:
        if self.locked == (self.reason is not None):
            raise ValueError("Ett nej har ett skäl, och bara ett nej.")
        return self


class RouteBy(StrEnum):
    """Who laid a route, or switched an automat (FR33, FR37)."""

    REMOTE = "remote"  # den som fjärrstyr, genom Hubben
    STATION = "station"  # på platsen, i stationens egen panel
    AUTOMAT = "automat"  # en stationsautomat, eller automaten av sig själv (FR29)


class LockedRoute(Contract):
    """A catalogue route the station's interlocking holds locked. It stays until the train has
    gone, also when the station is taken back (FR15)."""

    route: Id = Field(description="Tågvägens id i fjärrkatalogen.")
    by: RouteBy
    request_id: Id | None = Field(default=None, description="Begäran den svarade på.")
    automat: Text | None = Field(default=None, description="Automaten som lade den.")


class AutomatOn(Contract):
    """A station automat that is switched on, and who switched it on (FR25, FR29)."""

    code: Text = Field(max_length=12)
    by: RouteBy


class LocalArea(Contract):
    """A local area given to people on the spot (lokal frigivning, TKL44, TKL48, FR39)."""

    code: Text = Field(max_length=12, description="Lokalfrigivningens kod, till exempel L01.")
    tracks: list[Id] = Field(
        default_factory=list, description="Stationsspåren i området, för fjärrbilden."
    )


class PartRequest(Contract):
    """DRIFT-40, FR50: a part's request (begär väg) that the controller answers instead of the
    clearer, when a station with parts is remote-controlled. The station forwards it."""

    request_id: Id
    part: Id = Field(description="Delens id i utsidan.")
    text: Text = Field(description="Vad delen begär, som stationen skriver det.")


class ReadyToSend(Contract):
    """FR51: a train ready to send, as the clearer's list shows it, in the plan's order."""

    train_number: Text
    call: Id | None = None
    part: Id | None = None
    departure: TimeOfDay | None = None


class RouteState(Contract):
    """route.state: the station at the overview level, whole each time it changes (FR13). The
    catalogue routes it holds locked and who locked them, those the station or an automat laid
    too; the automats that are on; the local areas; and at level 3 the occupied tracks. The parts'
    requests and the ready list travel here when a station with parts is remote-controlled
    (DRIFT-40)."""

    locked: list[LockedRoute] = Field(default_factory=list)
    automats: list[AutomatOn] = Field(default_factory=list)
    local_areas: list[LocalArea] = Field(default_factory=list)
    occupied: list[Id] = Field(
        default_factory=list,
        description="Belagda stationsspår enligt detekteringen, bara från en station på nivå 3.",
    )
    part_requests: list[PartRequest] = Field(
        default_factory=list, description="Delarnas begäran, när stationen fjärrstyrs (FR50)."
    )
    ready_to_send: list[ReadyToSend] = Field(
        default_factory=list,
        description="Tåg som är klara att skicka, i avgångstidens ordning (FR51).",
    )


PAYLOADS: dict[Action, type[Contract]] = {
    Action.TRAIN_LOOKUP: TrainLookup,
    Action.TRAIN_TRACK_CHANGE: TrackChange,
    Action.TRAIN_DEPARTED: CallOnly,
    Action.TRAIN_ARRIVED: Arrival,
    Action.TRAIN_POSITION_SET: Flag,
    Action.TRAIN_CREW_READY_SET: Flag,
    Action.TRAIN_SET_ASIDE: CallOnly,
    Action.CLEARANCE_REQUEST: ClearanceRequest,
    Action.CLEARANCE_RESPONSE: ClearanceResponse,
    Action.CLEARANCE_CANCEL: ClearanceCancel,
    Action.LINE_AVAILABLE_PUBLISH: LineAvailable,
    Action.LINE_AVAILABLE_ACKNOWLEDGE: LineAcknowledge,
    Action.SECTION_OCCUPANCY: SectionOccupancy,
    Action.SIGNAL_EXIT: ExitSignal,
    Action.PLACE_LEAVE: PlaceOnly,
    Action.PLACE_TAKE_BACK: PlaceOnly,
    Action.PLACE_OFFER: PlaceOffer,
    Action.PLACE_OFFER_ANSWER: OfferAnswer,
    Action.ROUTE_REQUEST: RouteRequest,
    Action.ROUTE_CANCEL: RouteCancel,
    Action.ROUTE_RESPONSE: RouteResponse,
    Action.ROUTE_STATE: RouteState,
}


# --- The snapshot --------------------------------------------------------------------------


class Clock(Contract):
    time: TimeOfDay
    seconds: int = Field(ge=0, description="Sekunder sedan speldygnets midnatt; kan gå över 24 h.")
    running: bool = Field(description="Falskt betyder stoppad klocka, inte tappad kontakt.")
    speed: float = Field(gt=0)
    game_day: int = Field(ge=1)


class Neighbour(Contract):
    """A place and its game number, for the telephone list in TKL and the app (H24)."""

    place: Id
    code: Text
    name: Text
    phone: Text | None = None


class SectionHere(Contract):
    section: Id
    other_place: Id
    other_code: Text
    tracks: TrackKind
    clearance_mode: ClearanceMode
    side: Side | None = None
    exit: Id | None = Field(
        default=None,
        description="Stationens utfart för sträckan: kopplad i förväg, gissad eller besvarad "
        "(H26).",
    )
    occupied: bool = False
    detected: bool = Field(
        default=False,
        description="Belagd enligt detekteringen: en station på nivå 3 har rapporterat sträckan "
        "belagd (section.occupancy). Stoppar direktklarering och automatiken (DRIFT-16).",
    )


class DepartureState(StrEnum):
    PLANNED = "planned"
    REQUESTED = "requested"
    CLEARED = "cleared"
    DEPARTED = "departed"


class ArrivalState(StrEnum):
    NONE = "none"
    ON_THE_WAY = "on_the_way"  # på väg hit
    ARRIVED = "arrived"


class CallHere(Contract):
    """A call at this place, with what the client may do with it right now."""

    call: Id
    train: Id
    train_number: Text
    train_label: Text | None = Field(default=None, description="Till exempel IC 116 (F9).")
    train_type: Text | None = None
    manual: bool = False
    arrival: TimeOfDay | None = None
    departure: TimeOfDay | None = None
    day_offset: int = 0
    planned_track: Text | None = None
    track: Id | None = Field(default=None, description="Var tåget står eller ska stå nu.")
    from_place: Id | None = None
    to_place: Id | None = None
    arrival_state: ArrivalState = ArrivalState.NONE
    departure_state: DepartureState = DepartureState.PLANNED
    positioned: bool = False
    crew_ready: bool = False
    revision: int = Field(ge=0)
    allowed_actions: list[Action] = Field(default_factory=list)
    paper: bool = Field(
        default=False,
        description="Efter pappret: tåget finns inte i planen, och trafikledningen har godkänt "
        "det (LOK-13).",
    )


class TrainOnSection(Contract):
    """A train on its way here or that has left, from the departure to the arrival (H32)."""

    call: Id
    train_number: Text
    train_type: Text | None = None
    section: Id
    other_place: Id
    planned_track: Text | None = Field(default=None, description="Spåret vid ankomsten.")
    departed_at: TimeOfDay
    paper: bool = Field(
        default=False,
        description="Efter pappret: tåget finns inte i planen, och trafikledningen har godkänt "
        "det (LOK-13).",
    )


class ClearanceStatus(StrEnum):
    WAITING = "waiting"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    INVALIDATED = "invalidated"  # spårbyte på avgångsbesöket


class Clearance(Contract):
    clearance_id: Id
    call: Id
    train_number: Text
    section: Id
    from_place: Id
    to_place: Id
    status: ClearanceStatus
    departed: bool = False
    requested_at: TimeOfDay
    reminders: int = Field(default=0, ge=0, description="Påminnelser hittills (H39).")
    revision: int = Field(ge=0)
    paper: bool = Field(
        default=False,
        description="Efter pappret: tåget finns inte i planen, och trafikledningen har godkänt "
        "det (LOK-13).",
    )


class ExitChoice(Contract):
    exit: Id
    side: Side
    name: Text | None = None


class ExitQuestion(Contract):
    """Hubben är osäker på vilken av stationens utfarter en sträcka har (H26, PLAN-31). Den
    gissar på grannens namn, sidan och förra träffens svar, och frågar annars. Stationen i TKL
    eller trafikledningen i Klienter svarar, och det första svaret gäller (TRAFIK-05)."""

    station_id: Id
    place: Id
    section: Id
    other_place: Id
    other_name: Text
    side: Side | None = Field(default=None, description="Sträckans sida vid driftplatsen.")
    alternatives: list[ExitChoice] = Field(min_length=1)


class ExitAnswer(Contract):
    """Svaret från TKL: POST /api/station/1/places/{place}/exits med nyckeln."""

    section: Id
    exit: Id


class TrackShown(Contract):
    track: Text = Field(description="Spårets namn i planen, som tågbesöken använder.")
    visible: bool = True


class TrackDisplay(Contract):
    """Spår-vyn (BOXIOS-16, H65): every track of the place in the station's order, the hidden
    ones too. Set once per meet and place and shared by every app there; only presentation, it
    changes nothing in the traffic. Ported from the old Server (docs/tmbox-sparvisning.md)."""

    revision: int = Field(ge=0, description="Räknar upp vid varje sparning och återställning.")
    customized: bool = False
    tracks: list[TrackShown] = Field(default_factory=list)


class TrackDisplayChange(Contract):
    """PUT /api/station/1/places/{place}/track-display med nyckeln. Every current track exactly
    once, in the new order; without tracks the meet's own order comes back (Återställ). A
    revision other than the current one is refused, so no one's choice is overwritten."""

    revision: int = Field(ge=0, description="Revisionen klienten läste.")
    tracks: list[TrackShown] | None = None


class LineMessage(Contract):
    message_id: Id
    section: Id
    from_place: Id
    call: Id | None = None
    acknowledged: bool = False


class DriverMessageKind(StrEnum):
    """Förarens färdiga meddelanden till trafikledningen (LOK-23, DRIFT-38)."""

    DELAYED = "delayed"  # Försenad
    STOPPED_ON_LINE = "stopped_on_line"  # Står på linjen
    NEEDS_HELP = "needs_help"  # Behöver hjälp
    ENGINE_TROUBLE = "engine_trouble"  # Loket krånglar


class DriverMessageHere(Contract):
    """Ett meddelande från föraren på ett tåg som är här, på väg hit eller har lämnat (KLAR-27,
    DRIFT-38). Bara till TKL, inte till TMBox. Utan förarens namn."""

    kind: DriverMessageKind
    train: Id | None = None
    train_number: Text | None = None
    model_time: TimeOfDay
    seq: int = Field(ge=1, description="Drifthändelsen meddelandet är.")


class Receiver(Contract):
    """Someone a station can be handed to, or who controls it (FR3, TKL47)."""

    client_id: Id
    kind: ClientKind
    name: Text = Field(
        description="Driftplatsen grannens TKL kör, eller fjärrställverkets namn i Klienter."
    )
    place: Id | None = Field(
        default=None, description="Grannens driftplats, när det är en granne som tar emot."
    )


class OfferHere(Contract):
    """An offer that stands: the station, who it is offered to, and how long it stands."""

    place: Id
    to: Receiver
    expires_in: int = Field(ge=0, description="Sekunder kvar av minuten (FR8).")


class RemoteRouteState(StrEnum):
    REQUESTED = "requested"  # begärd, stationen har inte svarat
    LOCKED = "locked"  # låst i stationens ställverk
    REFUSED = "refused"  # nekad, med skäl; också när stationen inte svarade (FR14)
    CANCELLED = "cancelled"  # borttagen av den som styr; stationen löser upp den
    RELEASED = "released"  # upplöst, efter tåget eller efter borttagningen


class RemoteRouteHere(Contract):
    """A route asked for from afar, and how it stands."""

    request_id: Id
    route: Id
    call: Id | None = None
    train_number: Text | None = None
    state: RemoteRouteState
    reason: Reason | None = Field(default=None, description="Skälet till ett nej.")
    by: Id = Field(description="Klienten som begärde.")
    asked_at: TimeOfDay
    answer_in: int | None = Field(
        default=None, description="Sekunder kvar för stationen att svara (FR14)."
    )


class RemoteHere(Contract):
    """Fjärrstyrningen vid platsen: who controls it, the offer out, whom it can be handed to,
    the routes asked for and the station's last route.state, which Hubben keeps (FR15)."""

    controllable: bool = Field(
        default=False,
        description="Stationen har en fjärrkatalog och kan fjärrstyras. En station som inte kan "
        "det visas alltid som bemannad (FR16, FR38).",
    )
    controller: Receiver | None = None
    offer: OfferHere | None = None
    receivers: list[Receiver] = Field(
        default_factory=list, description="Vilka stationen kan lämnas till just nu."
    )
    controller_silent: int | None = Field(
        default=None,
        description="Sekunder sedan den som fjärrstyr hördes av. Efter 45 går inga nya "
        "fjärrtågvägar (FR28), efter 90 kopplar stationen in sin förvalda automat (FR29).",
    )
    routes: list[RemoteRouteHere] = Field(
        default_factory=list, description="Fjärrtågvägarna, senaste först."
    )
    route_state: RouteState | None = Field(
        default=None, description="Stationens senaste route.state."
    )


class Snapshot(Contract):
    """Everything a client needs for one place, replaced whole every time."""

    protocol: Literal["trainmeet.station/1"] = PROTOCOL
    place: Neighbour
    context: MeetContext
    clock: Clock
    place_revision: int = Field(ge=0)
    sections: list[SectionHere] = Field(default_factory=list)
    calls: list[CallHere] = Field(default_factory=list)
    on_the_way: list[TrainOnSection] = Field(default_factory=list, description="På väg hit.")
    have_left: list[TrainOnSection] = Field(default_factory=list, description="Har lämnat.")
    clearances: list[Clearance] = Field(default_factory=list)
    line_messages: list[LineMessage] = Field(default_factory=list)
    neighbours: list[Neighbour] = Field(default_factory=list)
    all_places: list[Neighbour] = Field(default_factory=list)
    automatic: bool = Field(
        default=False,
        description="Automatiken sköter driftplatsen; ta tillbaka den innan något annat (F14).",
    )
    questions: list[ExitQuestion] = Field(
        default_factory=list, description="Hubbens frågor om stationens utfarter (H26)."
    )
    track_display: TrackDisplay = Field(
        default_factory=lambda: TrackDisplay(revision=0),
        description="Spår-vyn: platsens spår i stationens ordning (BOXIOS-16).",
    )
    driver_messages: list[DriverMessageHere] = Field(
        default_factory=list,
        description="Förarnas meddelanden om tåg som rör platsen, de senaste 30 spelminuterna. "
        "Bara till TKL (KLAR-27, DRIFT-38).",
    )
    # Made by factories, so that the schema gives no default and a client may leave them out.
    mode: PlaceMode = Field(
        default_factory=lambda: PlaceMode.MANNED,
        description="Driftformen (FR5), i stället för automatic.",
    )
    remote: RemoteHere = Field(
        default_factory=RemoteHere,
        description="Fjärrstyrningen vid platsen; tom från en äldre hubb.",
    )
    offers: list[OfferHere] = Field(
        default_factory=list,
        description="Stationer som just den här klienten är erbjuden och kan svara på.",
    )
    controls: list[Id] = Field(
        default_factory=list, description="Driftplatserna just den här klienten fjärrstyr."
    )


# --- The remote picture's data (fjärrbilden, FR31–FR38) -----------------------------------------


class TrainOnTrack(Contract):
    """A train number on a station track: red where the train is, green for the one expected
    (FR35)."""

    track: Text = Field(description="Spårets namn i planen.")
    train_number: Text
    call: Id
    expected: bool = Field(description="Väntat tåg, inte här än.")


class SectionOverview(Contract):
    """A section from the place: which way a train goes on it and whether it is occupied."""

    section: Id
    other_place: Id
    exit: Id | None = None
    occupied: bool = False
    detected: bool = False
    towards: Id | None = Field(default=None, description="Driftplatsen tåget på sträckan går mot.")
    train_number: Text | None = None


class OverviewPlace(Contract):
    """One place in the remote picture. No names of people, as Nu (B13)."""

    place: Neighbour
    mode: PlaceMode
    controllable: bool = False
    controller: Receiver | None = None
    level: int | None = Field(default=None, ge=0, le=3, description="Stationens nivå i TKL.")
    heard: int | None = Field(
        default=None, description="Sekunder sedan stationen hördes av, för pricken."
    )
    outside: StationOutside | None = Field(
        default=None, description="Utsidan träffen kör med, med fjärrkatalogen och översikten."
    )
    route_state: RouteState | None = None
    routes: list[RemoteRouteHere] = Field(default_factory=list)
    trains: list[TrainOnTrack] = Field(default_factory=list)
    sections: list[SectionOverview] = Field(default_factory=list)


class Overview(Contract):
    """GET /api/station/1/overview?places=a,b: the remote picture's data, for the places the
    client runs, controls, is offered or is approved for, and their neighbours."""

    protocol: Literal["trainmeet.station/1"] = PROTOCOL
    context: MeetContext
    clock: Clock
    places: list[OverviewPlace] = Field(default_factory=list)


# --- The reply and the events -------------------------------------------------------------


class ReplyStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class LookupMatch(Contract):
    call: Id
    train_number: Text
    train_label: Text | None = None
    from_place: Id | None = None
    to_place: Id | None = None
    time: TimeOfDay | None = None


class Reply(Contract):
    protocol: Literal["trainmeet.station/1"] = PROTOCOL
    message_id: MessageId
    status: ReplyStatus
    reason: Reason | None = None
    message: Text | None = Field(default=None, description="Texten att visa, på klientens språk.")
    revision: Revision | None = None
    result: list[LookupMatch] | None = Field(default=None, description="Bara för train.lookup.")
    snapshot: Snapshot

    @model_validator(mode="after")
    def _check(self) -> Reply:
        if (self.status == ReplyStatus.REJECTED) != (self.reason is not None):
            raise ValueError("Ett avvisat svar har ett skäl, och bara då.")
        return self


class EventKind(StrEnum):
    CHANGED = "changed"  # fetch the snapshot again
    TRAIN_APPROACHING = "train.approaching"  # a train left the neighbour for here
    CLEARANCE_REQUESTED = "clearance.requested"
    CLEARANCE_ANSWERED = "clearance.answered"
    CLEARANCE_REMINDER = "clearance.reminder"  # unanswered for 3 minutes (H39)
    LINE_AVAILABLE = "line.available"
    APPROVAL = "approval"  # the client's approval changed
    # Fjärrstyrning (#36): hints like changed; the snapshot is still the truth.
    PLACE_OFFERED = "place.offered"  # till den som erbjuds
    ROUTE_REQUESTED = "route.requested"  # till stationen
    ROUTE_ANSWERED = "route.answered"  # till den som frågade
    LOCAL_RELEASE_REQUESTED = "local_release.requested"  # till den som fjärrstyr


class Event(Contract):
    protocol: Literal["trainmeet.station/1"] = PROTOCOL
    seq: int = Field(ge=0, description="Ökar per händelseström; ingen uppspelning av missade.")
    kind: EventKind
    place: Id
    place_revision: int = Field(ge=0)
    clearance_id: Id | None = None
    call: Id | None = None
    train_number: Text | None = None


# --- Push (SYNK-05, BOXIOS-12, F20) ---------------------------------------------------------

NOTICE_KINDS: Final = (
    EventKind.CLEARANCE_REQUESTED,
    EventKind.CLEARANCE_REMINDER,
    EventKind.CLEARANCE_ANSWERED,
    EventKind.TRAIN_APPROACHING,
)


class PushToken(Contract):
    """Telefonens adress för push, som appen ger hubben när den är godkänd:
    PUT /api/station/1/push med nyckeln, DELETE för att sluta. Den finns bara hos hubben som
    leder och skrivs aldrig ut."""

    platform: Literal["apns"] = "apns"
    token: str = Field(pattern=r"^[0-9a-fA-F]{64,200}$")
    sandbox: bool = Field(
        default=False, description="Apples utvecklingsmiljö, för en app som är byggd för prov."
    )


class Notice(Contract):
    """Det en notis säger, till en telefon som är godkänd för platsen (F20): begäran hit,
    påminnelsen, klart eller nekat, och tåg på väg. En begäran besvaras med Ge klart eller Neka
    direkt i notisen: appen skickar clearance.response med sin nyckel, detta context och denna
    expected_revision."""

    kind: EventKind
    place: Id
    title: Text
    body: Text
    train_number: Text
    clearance_id: Id | None = None
    context: MeetContext
    expected_revision: Revision | None = None
    seq: int = Field(ge=1, description="Drifthändelsen notisen kommer från.")

    @model_validator(mode="after")
    def _check(self) -> Notice:
        if self.kind not in NOTICE_KINDS:
            raise ValueError("Push finns för begäran, påminnelsen, svaret och tåg på väg.")
        return self
