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
    exit: Id | None = Field(default=None, description="Stationens utfart för sträckan.")
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


class TrainOnSection(Contract):
    """A train on its way here or that has left, from the departure to the arrival (H32)."""

    call: Id
    train_number: Text
    train_type: Text | None = None
    section: Id
    other_place: Id
    planned_track: Text | None = Field(default=None, description="Spåret vid ankomsten.")
    departed_at: TimeOfDay


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


class LineMessage(Contract):
    message_id: Id
    section: Id
    from_place: Id
    call: Id | None = None
    acknowledged: bool = False


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
