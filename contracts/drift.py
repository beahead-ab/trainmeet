"""trainmeet.drift/1: Drift's API, for the dispatcher (Nu, Klienter, Logg) and the screens.

First version (Claude, draft). Transport is HTTP with JSON and an event stream (SSE), behind
the dispatcher's login (a local PIN until TrainMeet ID, step 6):

    POST /api/drift/1/start              StartMeet -> DriftEvent
    POST /api/drift/1/clock              ClockControl -> DriftEvent
    GET  /api/drift/1/clients            list[Client]         Väntar first
    POST /api/drift/1/clients/approve    Approve -> Client    TKL and the app (H31)
    POST /api/drift/1/clients/revoke     Revoke -> Client
    POST /api/drift/1/clients/assign     Assign -> Client     TMBoxes: place and side
    GET  /api/drift/1/automation         AutomationStatus     who works which place (F14)
    POST /api/drift/1/automation         AutomationSettings -> AutomationStatus
    POST /api/drift/1/automation/place   AutomationPlace -> AutomationStatus  leave or take back
    GET  /api/drift/1/log?place=&train=  DriftEvent list       the event log, filtered (F27)
    GET  /api/drift/1/events             DriftEvent stream    live, for Nu and Logg

Still to come, each in the step that builds it: operating changes (step 3), version switch and
takeover (steps 4–5), screen data for Klocka, Banöversikt and Tågdiagram (step 3 and later).

Every drift event is kept in order with the leader's epoch. The events are what a restart
reads back and what the Pi sends to the cloud; there is no separate audit log.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final, Literal

from pydantic import Field, model_validator

from contracts.common import BoxLanguage, Contract, Id, Text, TimeOfDay, Weekday
from contracts.station import ApprovalStatus, Clearance, Clock
from contracts.terminal import DisplaySize

PROTOCOL: Final = "trainmeet.drift/1"


class StartMeet(Contract):
    meet: Id = Field(
        default="provbanan", description="Träffen som körs: Provbanan eller en träff i Planering."
    )
    version: int = Field(ge=1, description="Versionen av träffpaketet som körs.")
    game_day: int = Field(default=1, ge=1, description="Speldygnet, Dag 1…N.")
    traffic_day: Weekday | None = Field(
        default=None, description="Trafikdagen; tomt betyder paketets förval (F8)."
    )


class ClockAction(StrEnum):
    START = "start"
    STOP = "stop"
    SPEED = "speed"
    JUMP = "jump"  # tidshopp: closes open cases, sets trains by the timetable (H37)
    UNDO_JUMP = "undo_jump"


class ClockControl(Contract):
    action: ClockAction
    speed: float | None = Field(default=None, gt=0, le=60)
    time: TimeOfDay | None = None
    game_day: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check(self) -> ClockControl:
        if self.action == ClockAction.SPEED and self.speed is None:
            raise ValueError("Hastigheten saknas.")
        if self.action == ClockAction.JUMP and self.time is None:
            raise ValueError("Tiden att hoppa till saknas.")
        return self


class Approve(Contract):
    client_id: Id
    places: list[Id] = Field(min_length=1)


class Revoke(Contract):
    client_id: Id


class Assign(Contract):
    """A TMBox gets a place and a side, as before. One box may run several places (H44).
    The language is the box's own; left out, the box keeps the one it has."""

    client_id: Id
    places: list[Id] = Field(min_length=1)
    side: Literal["both", "left", "right"] = "both"
    language: BoxLanguage | None = None


class Client(Contract):
    client_id: Id
    name: Text
    kind: Literal["tkl", "tmbox_app", "dispatch", "tmbox_web", "tmbox", "screen"]
    status: ApprovalStatus
    places: list[Id] = Field(default_factory=list)
    side: Literal["both", "left", "right"] = "both"
    language: BoxLanguage | None = Field(default=None, description="Bara för TMBoxar.")
    display: DisplaySize | None = Field(default=None, description="Bara för TMBoxar.")
    view: Text | None = Field(default=None, description="Bara för skärmar: vyn den visar.")


class EventKind(StrEnum):
    MEET_STARTED = "meet.started"
    CLOCK_STARTED = "clock.started"
    CLOCK_STOPPED = "clock.stopped"
    CLOCK_SPEED = "clock.speed"
    TIME_JUMP = "clock.jump"
    TIME_JUMP_UNDONE = "clock.jump_undone"
    DAY_CHANGED = "day.changed"
    CLIENT_APPROVED = "client.approved"
    CLIENT_REVOKED = "client.revoked"
    CLIENT_ASSIGNED = "client.assigned"
    CLEARANCE_REQUESTED = "clearance.requested"
    CLEARANCE_ANSWERED = "clearance.answered"
    CLEARANCE_CANCELLED = "clearance.cancelled"
    CLEARANCE_REMINDED = "clearance.reminded"
    CLEARANCE_INVALIDATED = "clearance.invalidated"  # spårbyte på avgångsbesöket
    TRAIN_DEPARTED = "train.departed"
    TRAIN_ARRIVED = "train.arrived"
    TRAIN_MOVED_HERE = "train.moved_here"  # FLYTTA HIT: a train nobody sent
    TRAIN_TRACK_CHANGED = "train.track_changed"
    TRAIN_SET_ASIDE = "train.set_aside"  # undanställning (H41)
    TRAIN_POSITIONED = "train.positioned"  # TKL: tåget uppställt
    TRAIN_CREW_READY = "train.crew_ready"  # TKL: föraren på plats; REDO räknas fram
    LINE_AVAILABLE = "line.available"
    LINE_ACKNOWLEDGED = "line.acknowledged"
    SECTION_OCCUPANCY = "section.occupancy"
    EXIT_SIGNAL = "signal.exit"
    # Automatiken (F14): who works a place, and the dispatcher's settings for it.
    PLACE_MANNED = "place.manned"  # the first box or TKL that works the place
    PLACE_LEFT = "place.left"  # lämnad till automatiken
    PLACE_TAKEN_BACK = "place.taken_back"  # tagen tillbaka från automatiken
    AUTOMATION_SET = "automation.set"


class ActorKind(StrEnum):
    CLIENT = "client"
    DISPATCHER = "dispatcher"
    AUTOMATION = "automation"
    SYSTEM = "system"


class Actor(Contract):
    kind: ActorKind
    id: Id | None = None


class MeetStarted(Contract):
    traffic_day: Weekday
    speed: float = Field(gt=0, le=60)
    game_day: int = Field(default=1, ge=1)


class ClockChanged(Contract):
    seconds: float = Field(ge=0)
    speed: float = Field(gt=0, le=60)


class ClearanceRef(Contract):
    clearance_id: Id


class ClearanceRequested(ClearanceRef):
    section: Id
    to_place: Id


class ClearanceAnswered(ClearanceRef):
    approved: bool


class TrainArrived(ClearanceRef):
    """The train is in. Without a track it came in on the planned one (old Server 4.9.0)."""

    track: Text | None = Field(default=None, description="Spåret tåget kom in på.")


class TrainMovedHere(Contract):
    """FLYTTA HIT: a train nobody sent is placed here, so the game goes on (issue #115)."""

    track: Text | None = None


class TrainSetAside(Contract):
    """Ställ undan: a train that ended here is put away, and its track is free."""


class TrackChanged(Contract):
    """The call's track now. A train standing there moves with it."""

    track: Text


class FlagSet(Contract):
    """Uppställt or föraren på plats, set or taken back. REDO is both, never set itself."""

    value: bool


class LineAvailableSent(Contract):
    """Ledig linje: a message to the other end, never a request (old Server v2)."""

    message_id: Id
    section: Id
    to_place: Id


class LineAcknowledged(Contract):
    message_id: Id


# --- Automatiken (F14, F15, H41, H42; gamla Servers automatic.py) ---------------------------

PRESENCE_SECONDS: Final = 45


class LeftBy(StrEnum):
    DISPATCHER = "dispatcher"  # trafikledningen
    OPERATOR = "operator"  # boxen eller TKL på platsen ("går på toaletten")
    LOST_CONTACT = "lost_contact"  # automatiken, efter vald tid utan kontakt


class Disturbance(StrEnum):
    OFF = "off"  # av
    NORMAL = "normal"  # vart fjärde tåg 1–4 min
    DISRUPTED = "disrupted"  # två av tre tåg 1–12 min


class DisturbanceWhere(StrEnum):
    BOTH = "both"
    STATION = "station"  # stationsarbete före avgången
    LINE = "line"  # längre gångtid före ankomsten


class AutomationSettings(Contract):
    """Trafikledningens val för automatiken, med gamla Servers förval (H42)."""

    enabled: bool = Field(default=True, description="Av: automatiken rör ingenting.")
    lost_contact_minutes: Literal[0, 2, 5, 10] = Field(
        default=0, description="Övertag efter Kontakt saknas; 0 är aldrig."
    )
    disturbance: Disturbance = Disturbance.OFF
    where: DisturbanceWhere = DisturbanceWhere.BOTH
    seed: str = Field(default="", max_length=40, description="Scenarionyckel.")
    stabling: bool = Field(default=True, description="Undanställning vid slutstationen.")
    stabling_minutes: int = Field(default=5, ge=1, le=60, description="Spelminuter.")
    late_stop_minutes: int = Field(
        default=2, ge=1, le=10, description="Ett försenat tåg står så här länge (spelminuter)."
    )
    answer_seconds: int = Field(
        default=3, ge=0, le=30, description="Klartecken efter så här många verkliga sekunder."
    )


class PlaceManned(Contract):
    """The first box or TKL that works a place mans it (F14)."""

    client_id: Id


class PlaceLeft(Contract):
    """Lämnad till automatiken, until someone takes it back, also over a new day."""

    by: LeftBy
    client_id: Id | None = None


class PlaceTakenBack(Contract):
    by: Literal["dispatcher", "operator"]
    client_id: Id


class AutomationPlace(Contract):
    """Trafikledningen lämnar en plats till automatiken eller ger den till en ansluten klient."""

    place: Id
    action: Literal["leave", "take_back"]
    client_id: Id | None = Field(default=None, description="Vid take_back: klienten som tar den.")


class PlaceMode(StrEnum):
    MANNED = "manned"  # bemannad
    NO_CONTACT = "no_contact"  # Kontakt saknas
    AUTOMATIC = "automatic"  # automatiken sköter den


class AutomationPlaceStatus(Contract):
    place: Id
    name: Text
    code: Text
    mode: PlaceMode
    left_by: LeftBy | None = None
    takes_over_in: int | None = Field(
        default=None, description="Sekunder tills automatiken tar över; null är aldrig."
    )
    operator: Id | None = None
    present: list[Id] = Field(default_factory=list, description="Klienter i kontakt här.")


class AutomationTrain(Contract):
    call: Id
    train: Text
    from_place: Id
    to_place: Id
    reason: Text


class AutomationStatus(Contract):
    settings: AutomationSettings
    places: list[AutomationPlaceStatus] = Field(default_factory=list)
    trains: list[AutomationTrain] = Field(
        default_factory=list, description="Tåg som automatiken väntar med, och varför."
    )


EVENT_PAYLOADS: dict[EventKind, type[Contract]] = {
    EventKind.MEET_STARTED: MeetStarted,
    EventKind.CLOCK_STARTED: ClockChanged,
    EventKind.CLOCK_STOPPED: ClockChanged,
    EventKind.CLOCK_SPEED: ClockChanged,
    EventKind.CLEARANCE_REQUESTED: ClearanceRequested,
    EventKind.CLEARANCE_ANSWERED: ClearanceAnswered,
    EventKind.CLEARANCE_CANCELLED: ClearanceRef,
    EventKind.TRAIN_DEPARTED: ClearanceRef,
    EventKind.TRAIN_ARRIVED: TrainArrived,
    EventKind.TRAIN_MOVED_HERE: TrainMovedHere,
    EventKind.TRAIN_SET_ASIDE: TrainSetAside,
    EventKind.TRAIN_TRACK_CHANGED: TrackChanged,
    EventKind.TRAIN_POSITIONED: FlagSet,
    EventKind.TRAIN_CREW_READY: FlagSet,
    EventKind.CLEARANCE_INVALIDATED: ClearanceRef,
    EventKind.LINE_AVAILABLE: LineAvailableSent,
    EventKind.LINE_ACKNOWLEDGED: LineAcknowledged,
    EventKind.PLACE_MANNED: PlaceManned,
    EventKind.PLACE_LEFT: PlaceLeft,
    EventKind.PLACE_TAKEN_BACK: PlaceTakenBack,
    EventKind.AUTOMATION_SET: AutomationSettings,
}


_ON_A_CALL: Final = frozenset(
    {EventKind.TRAIN_TRACK_CHANGED, EventKind.TRAIN_POSITIONED, EventKind.TRAIN_CREW_READY}
)
_ON_A_PLACE: Final = frozenset(
    {EventKind.PLACE_MANNED, EventKind.PLACE_LEFT, EventKind.PLACE_TAKEN_BACK}
)


class DriftEvent(Contract):
    protocol: Literal["trainmeet.drift/1"] = PROTOCOL
    seq: int = Field(ge=1, description="Händelsens nummer i den körande träffen.")
    epoch: int = Field(ge=0, description="Ledarens epok; högre epok vinner.")
    meet_id: Id
    version: int = Field(ge=1)
    game_day: int = Field(ge=1)
    model_time: TimeOfDay
    wall_time: datetime
    kind: EventKind
    actor: Actor
    message_id: Text | None = Field(default=None, description="Kommandots id, för spårbarhet.")
    place: Id | None = None
    train: Id | None = None
    call: Id | None = None
    data: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_data(self) -> DriftEvent:
        if self.kind == EventKind.CLEARANCE_REQUESTED and self.call is None:
            raise ValueError("Klareringsbegäran måste ange avgångens tågbesök.")
        if self.kind in (EventKind.TRAIN_MOVED_HERE, EventKind.TRAIN_SET_ASIDE) and not self.call:
            raise ValueError("Händelsen måste ange ankomstens tågbesök.")
        if self.kind in _ON_A_CALL and not self.call:
            raise ValueError("Händelsen måste ange tågbesöket.")
        if self.kind in _ON_A_PLACE and not self.place:
            raise ValueError("Händelsen måste ange driftplatsen.")
        model = EVENT_PAYLOADS.get(self.kind)
        if model is not None:
            model.model_validate(self.data)
        return self


# --- Nu: what the dispatcher and everyone else sees of the meet (S1, steg 3) -----------------

LegState = Literal["planned", "requested", "cleared", "on_the_way", "arrived"]


class NowPlace(Contract):
    place: Id
    code: Text
    name: Text


class LegNow(Contract):
    """One train between two places today, and where it stands."""

    leg: Id = Field(description="Avgångens tågbesök; nyckeln för sträckan.")
    train: Id
    train_number: Text
    train_type: Text | None = None
    section: Id
    from_place: Id
    to_place: Id
    departure: TimeOfDay | None = None
    arrival: TimeOfDay | None = None
    state: LegState
    clearance_id: Id | None = None
    track: Text | None = Field(default=None, description="Ankomstspåret, planerat eller faktiskt.")


class Now(Contract):
    """The meet as it runs: open to everyone, so it holds no names of people, no codes and no
    phone numbers (B13)."""

    meet_id: Id
    name: Text
    version: int = Field(default=1, ge=1, description="Versionen av träffpaketet som körs.")
    traffic_day: Weekday
    game_day: int
    clock: Clock
    places: list[NowPlace]
    legs: list[LegNow]
    clearances: list[Clearance]


class Joining(Contract):
    """Anslut (S2): the meet's code and the address a box opens with it. Only for the
    dispatcher; the code is never shown to those who only look (B13)."""

    code: Text
    url: Text


class Refusal(Contract):
    """A command a client was told no to, and why (B15). Kept beside the Drift events: it
    changed nothing, but it explains a complaint after the meet."""

    wall_time: datetime
    model_time: TimeOfDay
    client_id: Id
    place: Id | None = None
    what: Text = Field(description="Åtgärden, eller knappen på en box.")
    reason: Text | None = Field(default=None, description="Skälet som kod, när Drift sa nej.")
    message: Text
