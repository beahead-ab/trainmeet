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
    POST /api/drift/1/day                NewDay -> DriftEvent           Starta ny dag (F7)
    POST /api/drift/1/day/settings       DaySettings -> DayStatus
    GET  /api/drift/1/phones             list[PlacePhone]               the game numbers (H30)
    POST /api/drift/1/phones             PlacePhone -> list[PlacePhone]
    POST /api/drift/1/changes            MakeChange -> DriftEvent       driftändringar (DRIFT-41)
    POST /api/drift/1/changes/{id}/force -> DriftEvent                  tvinga igenom (H38)
    POST /api/drift/1/changes/{id}/drop  -> DriftEvent                  släpp
    GET  /api/drift/1/package            MeetPackage                    the version with them on

Still to come, each in the step that builds it: the proposals to Planering and the version
switch (ärende 69), takeover (steps 4–5), screen data for Banöversikt and Tågdiagram.

Every drift event is kept in order with the leader's epoch. The events are what a restart
reads back and what the Pi sends to the cloud; there is no separate audit log.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import Field, model_validator

from contracts.common import BoxLanguage, Contract, Id, Text, TimeOfDay, Weekday
from contracts.meet import Call, ClearanceMode, TrackKind
from contracts.reasons import Reason
from contracts.station import ApprovalStatus, Clearance, ClearanceStatus, Clock, MeetContext
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
    jump: int | None = Field(
        default=None,
        ge=1,
        description="Tidshoppet att ångra, som Nu visade det; tomt betyder det senaste.",
    )

    @model_validator(mode="after")
    def _check(self) -> ClockControl:
        if self.action == ClockAction.SPEED and self.speed is None:
            raise ValueError("Hastigheten saknas.")
        if self.action == ClockAction.JUMP and self.time is None:
            raise ValueError("Tiden att hoppa till saknas.")
        return self


class DayChangeMode(StrEnum):
    MANUAL = "manual"  # förval: Trafikledningen startar nästa dag (Starta ny dag)
    AUTOMATIC = "automatic"


class DaySettings(Contract):
    """Dygnsskiftet (F7): by hand by default, automatic as a choice. The next game day starts
    an hour before its first train, never before midnight, unless a time is set here."""

    mode: DayChangeMode = DayChangeMode.MANUAL
    time: TimeOfDay | None = Field(
        default=None,
        description="Fast tid för dygnsskiftet; tomt betyder en timme före första tåget.",
    )


class NewDay(Contract):
    """Starta ny dag: the next game day, with the clock at the time given, or else the one Nu
    suggests: where the clock is after midnight, before midnight the time of the day change."""

    time: TimeOfDay | None = None


class PlacePhone(Contract):
    """A place's telephone number during the meet (H30, TRAFIK-06): the meet's game number,
    not personal data. Empty takes it away. TKL and the app read it in their phone list."""

    place: Id
    phone: Text | None = Field(default=None, max_length=24, description="Träffens leknummer.")


# --- Driftändringar (DRIFT-41, TRAFIK-02, H3, H12, H43): ten kinds. Each applies at once, on top
# of the version that runs, and becomes a proposal for the next version (4.4). Against a train
# that is out, or has an open clearance, it waits until the train is in, unless Trafikledningen
# forces it through with a warning (H38).


class CallTime(Contract):
    call: Id
    arrival: TimeOfDay | None = None
    departure: TimeOfDay | None = None


class CancelTrain(Contract):
    """Ställ in tåg: the train does not run."""

    kind: Literal["cancel"] = "cancel"
    train: Id


class ExtraTrain(Contract):
    """Extratåg (H12): a copy of a train with a new number and time, or from–to with a
    departure time, where Drift fills in the places between."""

    kind: Literal["extra"] = "extra"
    number: Text
    departure: TimeOfDay = Field(description="Avgången från första driftplatsen.")
    copy_of: Id | None = Field(default=None, description="Tåget som kopieras.")
    from_place: Id | None = None
    to_place: Id | None = None
    days: list[Weekday] | None = Field(
        default=None, description="Trafikdagarna; tomt betyder kopians dagar, eller alla."
    )

    @model_validator(mode="after")
    def _check(self) -> ExtraTrain:
        if (self.copy_of is None) == (self.from_place is None or self.to_place is None):
            raise ValueError("Ange tåget att kopiera, eller från och till.")
        if self.from_place is not None and self.from_place == self.to_place:
            raise ValueError("Från och till är samma driftplats.")
        return self


class ChangeTimes(Contract):
    """Ändrade tider (tåg och möten): the whole train, or from a call on, moved some minutes;
    or new times for some calls."""

    kind: Literal["times"] = "times"
    train: Id
    minutes: int = Field(default=0, ge=-720, le=720, description="Minuter senare, eller tidigare.")
    from_call: Id | None = Field(
        default=None, description="Flytta från avgången här; tomt betyder hela tåget."
    )
    calls: list[CallTime] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _check(self) -> ChangeTimes:
        if not self.minutes and not self.calls:
            raise ValueError("Ange minuter eller nya tider.")
        return self


class ChangePlace(Contract):
    """Ändrade driftplatser och sträckor: a section closed or opened, or its clearance mode;
    or a place unmanned, left to the automation, or manned again."""

    kind: Literal["place"] = "place"
    section: Id | None = None
    closed: bool | None = None
    clearance_mode: ClearanceMode | None = None
    place: Id | None = None
    place_kind: Literal["manned", "unmanned"] | None = None

    @model_validator(mode="after")
    def _check(self) -> ChangePlace:
        on_section = self.closed is not None or self.clearance_mode is not None
        if self.section is not None and on_section and self.place is None:
            return self
        if self.place is not None and self.place_kind is not None and self.section is None:
            return self
        raise ValueError("Ange en sträcka och vad som ändras, eller en driftplats och dess typ.")


class ChangeTrack(Contract):
    """Ändrat planerat spår: another track for a call."""

    kind: Literal["track"] = "track"
    call: Id
    track: Text


class ChangeSectionTracks(Contract):
    """Enkel eller dubbel sträcka."""

    kind: Literal["tracks"] = "tracks"
    section: Id
    tracks: TrackKind


class ChangeDays(Contract):
    """Ändrade trafikdagar för ett tåg."""

    kind: Literal["days"] = "days"
    train: Id
    days: list[Weekday] = Field(min_length=1)


class ChangeNumber(Contract):
    """Byte av tågnummer: the same train, a new number."""

    kind: Literal["number"] = "number"
    train: Id
    number: Text


class NoStop(Contract):
    """Ej uppehåll: the train passes the place without stopping (genomfart), or stops again."""

    kind: Literal["no_stop"] = "no_stop"
    call: Id
    stops: bool = False


class TrainNote(Contract):
    """Anmärkning: text that follows the train, or one of its calls. Empty takes it away."""

    kind: Literal["note"] = "note"
    train: Id
    call: Id | None = None
    text: Text | None = None


DriftChange = Annotated[
    CancelTrain
    | ExtraTrain
    | ChangeTimes
    | ChangePlace
    | ChangeTrack
    | ChangeSectionTracks
    | ChangeDays
    | ChangeNumber
    | NoStop
    | TrainNote,
    Field(discriminator="kind"),
]


class MakeChange(Contract):
    """Ny driftändring from Nu (TRAFIK-02)."""

    change: DriftChange
    force: bool = Field(
        default=False,
        description="Tvinga igenom mot ett tåg som är ute eller har öppen klarering (H38).",
    )


class ChangeStatus(StrEnum):
    APPLIED = "applied"  # gäller
    WAITING = "waiting"  # väntar tills tåget är framme (H38)
    DROPPED = "dropped"  # släppt


class ProposalStatus(StrEnum):
    """Planering's answer to a driftändring (4.4, PLAN-03)."""

    WAITING = "waiting"  # väntar i Planering
    TAKEN = "taken"  # tagen med i utkastet till nästa version
    REJECTED = "rejected"  # avslagen
    WITHDRAWN = "withdrawn"  # släppt i Drift innan Planering svarat


class ChangeNow(Contract):
    """A Drift change as Nu lists it, with what it waits for."""

    change_id: Id
    change: DriftChange
    status: ChangeStatus
    forced: bool = False
    train_number: Text | None = Field(default=None, description="Tågets nummer då.")
    made: TimeOfDay = Field(description="Modelltiden när ändringen gjordes.")
    proposal: ProposalStatus | None = Field(
        default=None, description="Svaret från Planering; tomt för Provbanan."
    )
    waiting_for: list[Text] = Field(
        default_factory=list, description="Tågnumren som är ute och som ändringen väntar på."
    )


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
    DAY_SETTINGS = "day.settings"
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
    PLACE_PHONE = "place.phone"  # telefonnumret under träffen (H30)
    # Driftändringar (DRIFT-41): made, applied when the train is in, and let go.
    CHANGE_MADE = "change.made"
    CHANGE_APPLIED = "change.applied"
    CHANGE_DROPPED = "change.dropped"


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


class TimeJumped(Contract):
    """Tidshopp (H37, F6, DRIFT-32): the open cases are closed and every train is placed where
    the timetable has it at the new time (DRIFT-43). Nothing is deleted, so it can be undone."""

    before: float = Field(ge=0, description="Klockan före hoppet, sekunder in på speldygnet.")
    seconds: float = Field(ge=0, description="Klockan efter hoppet.")
    closed: list[Id] = Field(default_factory=list, description="Klareringarna som stängdes.")


class TimeJumpUndone(Contract):
    """Ångra (F6): everything is as it was before the jump, and the clock shows the time it
    showed then. The events in between stay in the log."""

    jump: int = Field(ge=1, description="Tidshoppets eller den nya dagens händelsenummer.")
    seconds: float = Field(ge=0, description="Klockan efter ångrandet, som före hoppet.")
    kind: Literal["time", "day"] = Field(default="time", description="Tidshopp eller ny dag.")


class DayChanged(Contract):
    """Dygnsskiftet (F7, DRIFT-45): the next game day with its traffic day. The open cases are
    closed and every train stands where the timetable has it just before the day's first
    departure (DRIFT-43). Yesterday's events stay; it can be undone as a time jump (F6)."""

    game_day: int = Field(ge=1, description="Det nya speldygnet.")
    traffic_day: Weekday = Field(description="Det nya speldygnets trafikdag.")
    before: float = Field(ge=0, description="Klockan före, sekunder in på förra speldygnet.")
    seconds: float = Field(ge=0, description="Klockan efter, sekunder in på det nya speldygnet.")
    placed: float = Field(ge=0, description="Tiden tågen ställdes efter.")
    closed: list[Id] = Field(default_factory=list, description="Klareringarna som stängdes.")
    automatic: bool = Field(default=False, description="Skiftet kom av sig själv, inte från Nu.")


class PhoneChanged(Contract):
    """A place's game number changed during the meet (H30); the event names the place."""

    phone: Text | None = Field(default=None, max_length=24)


class ChangeMade(Contract):
    """A Drift change made from Nu (DRIFT-41). It applies at once, or waits for the trains it
    touches to be in (H38)."""

    change_id: Id
    change: DriftChange
    waiting: bool = False
    forced: bool = False
    train_number: Text | None = Field(
        default=None, description="Tågets nummer när ändringen gjordes, för Logg."
    )


class ChangeRef(Contract):
    """A waiting change that now applies, or a change let go."""

    change_id: Id
    forced: bool = Field(default=False, description="Tvingad igenom medan tåget var ute (H38).")


class ClearanceRef(Contract):
    clearance_id: Id


class ClearanceRequested(ClearanceRef):
    section: Id
    to_place: Id


class ClearanceAnswered(ClearanceRef):
    approved: bool
    forward: bool = Field(
        default=False,
        description="Flyttat fram: ett steg glömdes, och Drift gjorde det i samma händelse.",
    )


class ClearanceReminded(ClearanceRef):
    """A request still unanswered (H39): after 3 minutes and then every 3 minutes, real time."""

    count: int = Field(ge=1, description="Vilken påminnelse i ordningen, från 1.")


class TrainArrived(ClearanceRef):
    """The train is in. Without a track it came in on the planned one (old Server 4.9.0)."""

    track: Text | None = Field(default=None, description="Spåret tåget kom in på.")
    forward: bool = Field(
        default=False,
        description="Flyttat fram: ett steg glömdes, och Drift gjorde det i samma händelse.",
    )


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
    EventKind.TIME_JUMP: TimeJumped,
    EventKind.TIME_JUMP_UNDONE: TimeJumpUndone,
    EventKind.DAY_CHANGED: DayChanged,
    EventKind.DAY_SETTINGS: DaySettings,
    EventKind.PLACE_PHONE: PhoneChanged,
    EventKind.CHANGE_MADE: ChangeMade,
    EventKind.CHANGE_APPLIED: ChangeRef,
    EventKind.CHANGE_DROPPED: ChangeRef,
    EventKind.CLEARANCE_REQUESTED: ClearanceRequested,
    EventKind.CLEARANCE_ANSWERED: ClearanceAnswered,
    EventKind.CLEARANCE_CANCELLED: ClearanceRef,
    EventKind.CLEARANCE_REMINDED: ClearanceReminded,
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
    {
        EventKind.PLACE_MANNED,
        EventKind.PLACE_LEFT,
        EventKind.PLACE_TAKEN_BACK,
        EventKind.PLACE_PHONE,
    }
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


class LastJump(Contract):
    """The latest time jump or new day, while it can be undone (F6): until the next one."""

    seq: int = Field(ge=1, description="Händelsens nummer, för Ångra.")
    kind: Literal["time", "day"] = Field(default="time", description="Tidshopp eller ny dag.")
    from_time: TimeOfDay
    to_time: TimeOfDay
    game_day: int = Field(ge=1, description="Speldygnet efter.")
    traffic_day: Weekday = Field(description="Trafikdagen efter.")
    closed: int = Field(ge=0, description="Antalet klareringar som stängdes.")
    wall_time: datetime


class DayStatus(Contract):
    """Dygnsskiftet as Nu shows it (F7): when the next game day starts, and whether it is time."""

    mode: DayChangeMode
    time: TimeOfDay = Field(description="När nästa speldygn börjar, efter midnatt.")
    fixed: bool = Field(description="Tiden är satt av trafikledningen, inte räknad.")
    first: TimeOfDay | None = Field(
        default=None, description="Nästa dags första tåg; tomt om dagen saknar tåg."
    )
    next_game_day: int = Field(ge=1)
    next_traffic_day: Weekday
    suggested: TimeOfDay = Field(description="Klockan som Starta ny dag föreslår.")
    due: bool = Field(description="Manuellt: tiden har passerats, och nästa dag kan startas.")
    waiting: bool = Field(
        description="Automatiskt: tiden har passerats, men dagens tåg är ute (högst 30 min)."
    )


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
    jump: LastJump | None = Field(
        default=None, description="Det senaste tidshoppet eller nya dygnet, att ångra."
    )
    day: DayStatus | None = Field(default=None, description="Dygnsskiftet.")
    changes: list[ChangeNow] = Field(
        default_factory=list, description="Driftändringarna ovanpå versionen (DRIFT-41)."
    )


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


# --- Provbanan (steg 2) -------------------------------------------------------------------
# A run of Provbanan per browser, kept for a day (H51): the page acts from each place in turn.


class PreviewClock(Contract):
    seconds: float = Field(ge=0, description="Sekunder sedan speldygnets midnatt.")
    time: TimeOfDay
    speed: float = Field(gt=0, le=60)
    running: bool


class PreviewLeg(Contract):
    """A leg of the timetable: from one call to the next, over one section."""

    train: Text = Field(description="Tågnumret, för visning.")
    departure: Call
    arrival: Call
    section: Id
    blocked: Reason | None = Field(
        default=None, description="Varför klarering inte kan begäras nu."
    )
    complete: bool = Field(description="Tåget har kommit fram på sträckan.")


class PreviewCase(Contract):
    """A clearance in the run, from the request to the arrival."""

    id: Id
    train: Text
    departure: Id
    arrival: Id
    from_place: Id
    to_place: Id
    status: ClearanceStatus
    departed: bool
    arrived: bool
    revision: int = Field(ge=0)


class Preview(Contract):
    """The run as the Provbanan page sees it (GET /api/provbanan)."""

    revision: int = Field(ge=0, description="Ändras när något har hänt i körningen.")
    context: MeetContext
    traffic_day: Weekday
    places: dict[Id, Text] = Field(description="Driftplatsernas namn.")
    stations: list[Id] = Field(description="Driftplatserna en box eller TKL kan få.")
    sections: dict[Id, ClearanceMode] = Field(description="Klareringsläget per sträcka.")
    clock: PreviewClock
    legs: list[PreviewLeg]
    cases: list[PreviewCase]


class PreviewClients(Contract):
    """The run's code and its clients: boxes, TKL and the TMBox app (H31)."""

    code: Text
    clients: list[Client]
