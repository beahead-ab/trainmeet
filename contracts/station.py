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


class ConnectRequest(Contract):
    """The client says what it is, which station it is and which places it wants to run.
    A TKL that is not coupled in advance sends its outside along (H28)."""

    protocol: Literal["trainmeet.station/1"] = PROTOCOL
    protocols: list[Text] = Field(
        default_factory=lambda: [PROTOCOL], description="Alla versioner klienten talar."
    )
    kind: ClientKind
    name: Text = Field(description="Det trafikledningen ser i Klienter.")
    software: Text = Field(description="Program och version, till exempel TKL 0.1.0.")
    station_id: Id | None = None
    outside: StationOutside | None = None
    wants: list[Id] = Field(default_factory=list, description="Driftplatserna den vill köra.")
    code: Text | None = Field(
        default=None,
        description="Provbanans kod, bara i en provkörning: den visar vilken körning det gäller.",
    )


class ApprovalStatus(StrEnum):
    WAITING = "waiting"  # under Väntar in Klienter
    APPROVED = "approved"
    REFUSED = "refused"
    REVOKED = "revoked"


class ConnectReply(Contract):
    protocol: Literal["trainmeet.station/1"] = PROTOCOL
    client_id: Id
    status: ApprovalStatus
    places: list[Id] = Field(default_factory=list, description="Godkända driftplatser.")
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


# --- Commands ------------------------------------------------------------------------------


class Action(StrEnum):
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
    PLACE_TAKE_BACK = "place.take_back"  # ta tillbaka från automatiken


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
    """Level 3 only: a section's detection. The section is free when every part is empty."""

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
