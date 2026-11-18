"""TrainMeet Catalog's API, trainmeet.catalog/1 (CAT-36): what the web app and others read.

Catalog is its own service with its own database (C16, CAT-30). It never calls the Hub and
the Hub never calls it (K7, CAT-37). Step 1 (#48) has the version, the session and the trial
login, and #50 the vehicles and the places at home. The mini card, the tag, the lookup and the
prototype come with their steps (#54 and #53), in this file. The trip to the meet (#55) is the
owner's own list; the link to the Hub's meet waits (CAT-174, CAT-189, VILAR).

Addresses:
    GET    /api/version                       CatalogVersion
    GET    /api/catalog/1/session             Session
    DELETE /api/catalog/1/session             Session, logged out
    GET    /api/catalog/1/trial/accounts      [Account], only with the trial login
    POST   /api/catalog/1/trial/login         TrialLogin -> Session, only with the trial login

Rules:
- The session is an HttpOnly cookie. Every changing call checks it on the server (CAT-195).
- The trial login exists only in the test environment, until TrainMeet ID (C21, CAT-214).
  Its accounts are fixed and hold no personal data.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, RootModel, StringConstraints

from contracts.common import AppKey, Contract, Text


class CatalogVersion(Contract):
    """What is running, so a tester can see which change the test environment has."""

    product: Literal["TrainMeet Catalog"] = "TrainMeet Catalog"
    version: str = Field(description="The package version, for example 0.1.0.")
    commit: str | None = Field(default=None, description="The git commit, or null locally.")
    pr: int | None = Field(default=None, description="The pull request the change came from.")
    title: str | None = Field(default=None, description="The title of that pull request.")
    built: datetime | None = Field(default=None, description="When the image was built, UTC.")


class LoginKind(StrEnum):
    """How people log in to this Catalog."""

    TRIAL = "trial"
    """The trial login in the test environment, until TrainMeet ID (CAT-214)."""
    ID = "id"
    """TrainMeet ID (#66): GET /api/catalog/1/id/login sends the browser there."""


class Account(Contract):
    """The person who is logged in, as Catalog knows them. The id comes from the login."""

    id: UUID
    name: Text = Field(max_length=80, description="The name the person shows.")
    initials: str = Field(min_length=1, max_length=3, description="For the account button.")


class Session(Contract):
    """Who is logged in, if anyone, and how one logs in here."""

    account: Account | None = None
    login: LoginKind
    simulated_tags: bool = Field(
        default=False, description="Simulated tags can be made here: the test environment."
    )
    share_url: str | None = Field(
        default=None,
        description="Where the owner shares the fleet in TrainMeet ID (CAT-44, KONTO-29).",
    )
    help_url: str | None = Field(
        default=None,
        description="Hjälp och fel in TrainMeet ID, which mails Beahead's support (KONTO-06).",
    )
    apps: list[AppKey] | None = Field(
        default=None,
        description="The app switcher's apps, as ID says (ID11); null when ID does not answer.",
    )
    tokens: int | None = Field(
        default=None,
        description=(
            "Saldot i kontomenyn (TOKEN-01): the tokens left on the person's own account in "
            "TrainMeet ID; null without ID, or when ID does not answer."
        ),
    )
    tokens_url: str | None = Field(
        default=None, description="Tokens in TrainMeet ID, where one sees the balance and buys."
    )
    logout_url: str | None = Field(
        default=None,
        description=(
            "Only in the answer to logging out: where the browser goes next, so that "
            "TrainMeet ID logs out too and sends it back (KONTO-01)."
        ),
    )


class FleetRight(StrEnum):
    """The right to a fleet (CAT-44, CAT-46): the owner's, to edit, or to look."""

    OWNER = "owner"
    EDIT = "edit"
    VIEW = "view"


class FleetChoice(Contract):
    """A fleet the person can work in: their own first, then the ones shared with them (CAT-50).
    The vehicles' addresses take ?fleet=<owner> to work in someone else's."""

    owner: UUID
    title: Text = Field(description="Whose fleet it is.")
    right: FleetRight
    share_url: str | None = Field(
        default=None,
        description="With the owner's right: where the fleet is shared in TrainMeet ID (CAT-44).",
    )


class TrialLogin(Contract):
    """Log in as one of the trial login's fixed accounts (GET /api/catalog/1/trial/accounts)."""

    account: UUID


# --- The vehicles (#50) -----------------------------------------------------------------
#
#     GET    /api/catalog/1/vehicles                 VehicleList; ?q= kind= scale= state= place=
#     POST   /api/catalog/1/vehicles                 VehicleFields -> Vehicle
#     GET    /api/catalog/1/vehicles/{id}            Vehicle
#     PUT    /api/catalog/1/vehicles/{id}            VehicleChange -> Vehicle
#     DELETE /api/catalog/1/vehicles/{id}?version=   Removed
#     POST   /api/catalog/1/vehicles/move            Move -> VehicleList
#     POST   /api/catalog/1/vehicles/{id}/lend       Lend -> Vehicle
#     POST   /api/catalog/1/vehicles/{id}/return     Return -> Vehicle
#     GET    /api/catalog/1/vehicles/{id}/events     [VehicleEvent]
#     GET    /api/catalog/1/places                   [Place]
#     POST   /api/catalog/1/places                   PlaceName -> Place
#     PUT    /api/catalog/1/places/{id}              PlaceName -> Place
#     DELETE /api/catalog/1/places/{id}              Removed
#
# Rules:
# - Only the owner sees and changes the fleet in this step. Sharing comes with ID (#49).
# - A vehicle that is not visible answers 404 (CAT-50).
# - Every change raises the version. A change built on an older version is refused with 409
#   and a message, instead of overwriting (CAT-63).
# - The number is text exactly as painted; the EVN is derived and never stored (CAT-55, CAT-58).

Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)]
"""A short field that may be empty."""


class VehicleKind(StrEnum):
    """The kinds of vehicle (CAT-54)."""

    LOCOMOTIVE = "locomotive"
    FREIGHT_WAGON = "freight_wagon"
    PASSENGER_COACH = "passenger_coach"
    MULTIPLE_UNIT = "multiple_unit"
    """Motorvagn eller tågsätt."""
    OTHER = "other"


class VehicleStatus(StrEnum):
    """A draft, or ready: ready needs a kind and a litt or number (CAT-62)."""

    DRAFT = "draft"
    READY = "ready"


class VehicleState(StrEnum):
    """Where the vehicle is (CAT-70). Packed and at the meet are set by the trip (#55)."""

    HOME = "home"
    PACKED = "packed"
    AT_MEET = "at_meet"
    LENT = "lent"


class FieldSource(StrEnum):
    """Where a core field's value came from (CAT-64)."""

    OWNER = "owner"
    AI = "ai"
    PROTOTYPE = "prototype"
    IMPORT = "import"


class DccFunction(Contract):
    """A locomotive's function: F0 light, F2 horn ... (CAT-66)."""

    number: int = Field(ge=0, le=68)
    name: Short


class VehicleFields(Contract):
    """The core fields the owner writes (CAT-53). The pictures and the tag have addresses of
    their own; the prototype comes later."""

    status: VehicleStatus = VehicleStatus.DRAFT
    kind: VehicleKind | None = None
    litt: Short = ""
    number: Short = Field(default="", description="As painted: leading zeros, spaces, dashes kept.")
    operator: Short = Field(default="", description="The operator as text. No logos (CAT-61).")
    epoch: Annotated[str, StringConstraints(strip_whitespace=True, max_length=12)] = ""
    scale: Annotated[str, StringConstraints(strip_whitespace=True, max_length=12)] = ""
    maker: Short = Field(default="", description="The model's maker.")
    article_number: Short = ""
    note: Annotated[str, StringConstraints(max_length=2000)] = Field(
        default="", description="Private. Never in a mini card or an export to others (CAT-191)."
    )
    dcc_address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=8)] = Field(
        default="", description="Locomotives and multiple units: the DCC address as text."
    )
    functions: list[DccFunction] = Field(default_factory=list, max_length=69)
    place: UUID | None = Field(default=None, description="The place at home.")


class VehicleChange(VehicleFields):
    """A change: all the core fields, and the version the change was built on."""

    version: int = Field(ge=1)


class EvnParts(Contract):
    """The EVN read from the number (CAT-57). Derived every time, never stored."""

    text: str = Field(description="For example 21 74 245 2 253-0, with the computed check digit.")
    interop: str
    country: str
    country_letters: str = Field(description="For example S for 74. Empty when unknown.")
    serial: str
    check: int
    given: int | None = Field(description="The painted check digit, or null when not painted.")
    valid: bool = Field(description="False only when the painted check digit is wrong (CAT-59).")


class Lending(Contract):
    """Who has the vehicle: the owner's own note (CAT-74, CAT-75)."""

    to: Text
    since: datetime
    until: date | None = None


class TagKind(StrEnum):
    """An NFC tag, a QR label or a simulated tag (CAT-78, CAT-96, CAT-121)."""

    NFC = "nfc"
    QR = "qr"
    SIM = "sim"


class VehicleTag(Contract):
    """A tag on the vehicle, as the card shows it (CAT-97)."""

    assignment: UUID = Field(description="The link. A change carries it (CAT-89).")
    tag: UUID
    uid: str = Field(description="What stands after /t/ in the address.")
    name: str
    kind: TagKind
    address: str = Field(description="For example https://trainmeet.app/t/04a1b2c3d4e5f6.")
    linked_at: datetime


class Notice(Contract):
    """Någon sa till: where someone saw the vehicle, without who said it (CAT-113)."""

    id: UUID
    text: str
    at: datetime


class PictureLinks(Contract):
    """The vehicle's main picture, for the lists and the card (CAT-125). Signed addresses that
    expire (CAT-130): read the vehicle again for new ones."""

    thumb_url: str = Field(description="The thumbnail, at most 360×240 pixels (CAT-126).")
    display_url: str = Field(description="The display picture, at most 1800 pixels (CAT-126).")


class Vehicle(VehicleFields):
    """A vehicle as its owner sees it."""

    id: UUID = Field(description="Permanent, never reused, kept when the tag changes (CAT-52).")
    version: int
    state: VehicleState
    place_name: str | None = None
    lending: Lending | None = None
    evn: EvnParts | None = None
    field_sources: dict[str, FieldSource] = Field(default_factory=dict)
    tags: list[VehicleTag] = Field(
        default_factory=list, description="At most one NFC, one QR. Only the owner sees them."
    )
    tagged: bool = Field(
        default=False,
        description="The vehicle has a tag: what someone it is shared with sees (CAT-47).",
    )
    notices: list[Notice] = Field(default_factory=list, description="Newest first.")
    picture: PictureLinks | None = Field(
        default=None,
        description="The main picture, or null without pictures. Seen with every right.",
    )
    created_at: datetime
    updated_at: datetime


class VehicleList(Contract):
    """The fleet, filtered, with the count per state over the whole fleet."""

    vehicles: list[Vehicle]
    counts: dict[VehicleState, int]
    total: int


class Move(Contract):
    """Move several vehicles to a place at home at once (CAT-73). Null: home without a place."""

    vehicles: list[UUID] = Field(min_length=1, max_length=500)
    place: UUID | None = None


class Lend(Contract):
    version: int = Field(ge=1)
    to: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    until: date | None = Field(default=None, description="Back at the latest, if the owner wants.")


class Return(Contract):
    """The vehicle is back: it gets its earlier place (CAT-76)."""

    version: int = Field(ge=1)


class VehicleEvent(Contract):
    """A change of state or place, with its time. Only the owner sees them (CAT-77)."""

    at: datetime
    state: VehicleState
    place_name: str | None = None
    lent_to: str | None = None
    meet_name: str | None = Field(
        default=None,
        description="The meet whose trip moved the vehicle, as it was named then (CAT-182).",
    )


class Place(Contract):
    """A named place at home: a box or a shelf (CAT-71)."""

    id: UUID
    name: Text
    vehicles_home: int = Field(description="How many vehicles are at home here now.")
    vehicles: int = Field(description="How many vehicles live here, wherever they are now.")


class PlaceName(Contract):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class Removed(Contract):
    id: UUID


class ProblemCode(StrEnum):
    """Why Catalog said no. The web app has the text for each in Swedish and English."""

    NOT_FOUND = "not_found"
    """The vehicle or place does not exist, or is not visible to the one asking (CAT-50)."""
    CHANGED = "changed"
    """It was changed since it was read: open it again (CAT-63)."""
    NOT_READY = "not_ready"
    """Ready needs a kind and a litt or number (CAT-62); lending needs a ready vehicle."""
    DCC_ONLY_ENGINES = "dcc_only_engines"
    """The DCC address and the functions are only for locomotives and multiple units."""
    PLACE_EXISTS = "place_exists"
    """There is already a place with that name."""
    NOT_HOME = "not_home"
    """Only a vehicle at home can be lent."""
    NOT_LENT = "not_lent"
    """Only a lent vehicle can come back."""
    LOGIN = "login"
    """Not logged in."""
    TAG_TAKEN = "tag_taken"
    """The tag is on someone else's vehicle: its owner must unlink it first (CAT-86)."""
    TAG_ON_OTHER_VEHICLE = "tag_on_other_vehicle"
    """The tag is on another of one's own vehicles; it moves after a confirmation (CAT-87)."""
    TAG_CHANGED = "tag_changed"
    """The link changed since it was shown: open the card again (CAT-89)."""
    BAD_TAG = "bad_tag"
    """Not a tag's address: an NFC serial number in hex, a QR label or a simulated tag."""
    TOO_MANY = "too_many"
    """More than 30 lookups in a minute: try again in a minute (CAT-111, CAT-112). For a picture:
    the owner's cap of tokens per day in TrainMeet ID is reached, so the storage over the free
    level cannot be paid today (TK15, CAT-132). For a reading: more than 10 in an hour, with
    Retry-After (CAT-146), or the day's cap in TrainMeet ID is reached (TK15)."""
    NOT_HERE = "not_here"
    """Simulated tags exist only in the test environment (CAT-96)."""
    FORBIDDEN = "forbidden"
    """The fleet is shared with the asker, but only the owner may do this (CAT-46, CAT-49)."""
    UNAVAILABLE = "unavailable"
    """TrainMeet ID, or the pictures' storage, does not answer just now (#49, CAT-130). For a
    reading: this Catalog has no TrainMeet ID, the account is not in ID, or TrainMeets AI cannot
    be used just now (CAT-26)."""
    BAD_PICTURE = "bad_picture"
    """Not a picture Catalog can read: JPEG, PNG or WebP (CAT-123)."""
    PICTURE_TOO_LARGE = "picture_too_large"
    """Over 15 MB (413) or over 40 megapixels (422) (CAT-123)."""
    TOO_MANY_PICTURES = "too_many_pictures"
    """The vehicle already has 10 pictures (CAT-17). For a batch: more than 30 photos in it
    (CAT-147), or more than 60 drafts waiting for the owner's approval (#52)."""
    STORAGE_FULL = "storage_full"
    """The owner's free storage is full: 100 MB for a person, 2 GB for a club (CAT-17,
    TOKEN-29), and this Catalog cannot take tokens for more: it does not reach TrainMeet ID's
    API, or ID does not know the owner, such as a trial account."""
    NO_TOKENS = "no_tokens"
    """The owner's free storage is full and the owner's balance in TrainMeet ID does not cover
    the next started GB this month, 20 tokens (CAT-132): buy tokens in ID, or remove pictures.
    Nothing was stored, and the pictures that are there stay. For a reading: the balance does
    not cover 12 tokens a picture (CAT-19); nothing was sent."""
    BACKGROUNDS_OFF = "backgrounds_off"
    """The background removal is not on at this Catalog just now: only the original background
    can be chosen (CAT-127). StorageUse.backgrounds says so before anyone tries."""
    NO_VEHICLE = "no_vehicle"
    """The background removal found no clear vehicle in the picture (CAT-129)."""
    LENT = "lent"
    """A lent vehicle cannot be packed, or ticked in the trip, before it is back (CAT-177)."""
    ON_ANOTHER_TRIP = "on_another_trip"
    """The vehicle is away on another meet's trip: tick it in Hem there first (#55)."""
    ARCHIVED = "archived"
    """The meet is archived and does not change any more (CAT-183)."""
    NOT_BACK = "not_back"
    """Something on the pack list is still away: tick it in Hem, or take it off the list."""
    CONSENT_REQUIRED = "consent_required"
    """The first reading needs the person's consent: show what is sent and to whom
    (GET /readings/consent), and send the reading again with consent (CAT-142)."""
    READING_BUSY = "reading_busy"
    """A reading is already running for the person, or for this id: one at a time (CAT-146)."""
    READING_FAILED = "reading_failed"
    """The AI could not read the photos, or its answer could not be read. Nothing was changed
    and nothing was drawn; try again with a new reading (CAT-20)."""


class Problem(Contract):
    """The answer when Catalog says no: 401, 402, 403, 404, 409, 413, 415, 422, 429, 502 or
    503."""

    code: ProblemCode
    message: str = Field(description="The same in Swedish, for logs and other readers.")
    cards: list[UUID] | None = Field(
        default=None,
        description="Only for Godkänn alla: the cards whose values do not make a vehicle, so "
        "that nothing was approved (CAT-150). Left out otherwise.",
    )


# --- The tags and the lookup (#54) ---------------------------------------------------------
#
#     GET    /api/catalog/1/tags/{uid}                  Lookup: one of five outcomes (CAT-98)
#     POST   /api/catalog/1/tags/{uid}/link             TagLink -> Vehicle
#     GET    /api/catalog/1/tags/{uid}/events           [TagEvent], the asker's own (CAT-93)
#     GET    /api/catalog/1/tags/{uid}/qr.svg           the QR code, for the tag's owner
#     POST   /api/catalog/1/tags/simulated              Tag, only in the test environment
#     GET    /api/catalog/1/tags/pending                PendingState: the vehicle waiting for a tag
#     POST   /api/catalog/1/tags/pending                NewPending -> PendingState (CAT-94)
#     DELETE /api/catalog/1/tags/pending                PendingState, nothing waiting
#     POST   /api/catalog/1/tags/{uid}/notice           Tell -> Told: Säg till ägaren (CAT-113)
#     DELETE /api/catalog/1/vehicles/{id}/notices/{n}   Removed: the owner clears a notice
#     GET    /api/catalog/1/settings                    OwnerSettings
#     PUT    /api/catalog/1/settings                    OwnerSettings -> OwnerSettings
#     POST   /api/catalog/1/vehicles/{id}/tags/qr       NewLabel -> Vehicle, a new QR label
#     POST   /api/catalog/1/vehicles/{id}/tags/unlink   TagUnlink -> Vehicle
#
# Rules:
# - The address is /t/<uid>. Case and a trailing slash do not matter (CAT-80). An NFC tag's uid
#   is its serial number in hex; Web NFC's colons are dropped (CAT-79).
# - The lookup is built from an exact whitelist per outcome, never from the owner's vehicle
#   (CAT-107), and is sent with Cache-Control: private, no-store (CAT-108). Nobody's taps are
#   kept (CAT-110). At most 30 lookups a minute per person, or per address when logged out.
# - Linking needs an explicit confirmation (CAT-83) and a ready vehicle (CAT-84). The same
#   request twice gives the same result (CAT-92).


class Tag(Contract):
    """A tag the owner has made: a simulated tag or a QR label."""

    id: UUID
    uid: str
    name: str
    kind: TagKind
    address: str


class MiniCard(Contract):
    """What someone else sees: exactly litt and number, kind, operator, scale and thumbnail.
    Never place, note, model, DCC address or anything about the tag (CAT-100)."""

    litt: str
    number: str
    kind: VehicleKind | None
    operator: str
    scale: str
    thumbnail: str | None = Field(description="The thumbnail's address, checked on every fetch.")


class LookupMine(Contract):
    """My vehicle: the card opens (CAT-99)."""

    outcome: Literal["mine"] = "mine"
    vehicle_id: UUID


class LookupShared(Contract):
    """Someone else's vehicle, whose owner shows their name to those logged in (CAT-101)."""

    outcome: Literal["shared"] = "shared"
    owner_name: str
    card: MiniCard


class LookupPrivate(Contract):
    """Someone else's vehicle without the owner's name, or anyone not logged in (CAT-100)."""

    outcome: Literal["private"] = "private"
    card: MiniCard


class LookupFleet(Contract):
    """A vehicle in a fleet shared with the asker: the card, with the sharing's right (CAT-104).
    Sharing comes with TrainMeet ID (#49)."""

    outcome: Literal["fleet"] = "fleet"
    vehicle_id: UUID
    right: Literal["view", "edit"]
    owner: UUID = Field(description="Whose fleet it is, as in ?fleet=: the card opens in it (#49).")


class LookupUnknown(Contract):
    """The tag is not linked. Logged in: its uid, to add or link a vehicle (CAT-105).
    Logged out: nothing more (CAT-106)."""

    outcome: Literal["unknown"] = "unknown"
    tag_uid: str | None = None


class Lookup(RootModel[LookupMine | LookupShared | LookupPrivate | LookupFleet | LookupUnknown]):
    """What /t/<uid> answers: one of five outcomes, each with its own fields (CAT-98, CAT-209)."""

    root: Annotated[
        LookupMine | LookupShared | LookupPrivate | LookupFleet | LookupUnknown,
        Field(discriminator="outcome"),
    ]


class TagLink(Contract):
    """Link the tag to one of one's own vehicles, after "Ja, koppla" (CAT-83)."""

    vehicle: UUID
    confirm: Literal[True] = Field(description="The explicit yes. Without it nothing happens.")
    replace: UUID | None = Field(
        default=None,
        description="The vehicle's link of the same kind, as seen, to end it (CAT-88, CAT-89).",
    )
    move_from: UUID | None = Field(
        default=None,
        description="This tag's link to another of one's own vehicles, as seen (CAT-87).",
    )


class TagUnlink(Contract):
    """Unlink after a confirmation; the history stays (CAT-90)."""

    assignment: UUID
    confirm: Literal[True]


class NewLabel(Contract):
    """A new QR label for the vehicle (CAT-121). replace: its QR label as seen, if it has one."""

    replace: UUID | None = None


class TagEventKind(StrEnum):
    LINKED = "linked"
    UNLINKED = "unlinked"


class TagEvent(Contract):
    """A link or unlink the asker made (CAT-93)."""

    event: TagEventKind
    at: datetime
    vehicle_id: UUID | None


class NewPending(Contract):
    """Koppla tagg on the card: the vehicle waits 10 minutes for the next tag (CAT-94)."""

    vehicle: UUID
    replace: UUID | None = Field(
        default=None, description="The vehicle's link of the same kind, as seen, to replace it."
    )


class PendingLink(Contract):
    vehicle_id: UUID
    title: str = Field(description="Litt and number, to ask: Koppla taggen till Hbis 2253?")
    replace: UUID | None
    expires_at: datetime


class PendingState(Contract):
    pending: PendingLink | None


class Tell(Contract):
    """Säg till ägaren: where the vehicle stands, in a line (CAT-113)."""

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Told(Contract):
    """The notice is with the owner. Nothing about who the owner is."""

    told: Literal[True] = True


class OwnerSettings(Contract):
    """Visa mitt namn när någon blippar mina fordon: off from the start (CAT-101)."""

    show_name: bool = False


# --- The trip to the meet (#55, CAT-174–CAT-183) ---------------------------------------------
#
#     GET    /api/catalog/1/meets                   [TripSummary], the active ones first
#     POST   /api/catalog/1/meets                   NewTrip -> Trip
#     GET    /api/catalog/1/meets/{id}              Trip
#     POST   /api/catalog/1/meets/{id}/vehicles     PackList -> Trip: the pack list (CAT-175)
#     POST   /api/catalog/1/meets/{id}/ticks        TickChange -> Trip: a press on the row
#     POST   /api/catalog/1/meets/{id}/tap          TripTap -> TripTapped: a tag tapped in a step
#     POST   /api/catalog/1/meets/{id}/archive      Trip, archived (CAT-183)
#
# Rules:
# - A meet in Catalog is the owner's own list with a name and a date, as long as the link to
#   the Hub waits (CAT-174, K7). The trip moves the vehicles and is the owner's own history
#   (CAT-77, CAT-182), so only the owner has the fleet's meets, and a club's administrators the
#   club's (C39). Someone the fleet is shared with gets 403, anyone else 404 (CAT-49).
#   ?fleet=<owner> works in a club's fleet, as for the vehicles.
# - Three steps, pack, arrive and home, and a tick per vehicle and step with its time, set by a
#   tap on the vehicle's tag or a press on its row (CAT-176). The same tick twice is one tick.
# - A tick moves the vehicle (CAT-177): Packa gives packed, På plats at the meet, and Hem home.
#   The vehicle's place stays its home place while it is away, so Hem puts it back where it was
#   before the trip. The state follows the highest step ticked, and every change is an event
#   with the meet's name (CAT-182). Taking a tick away moves the vehicle back.
# - A vehicle is away on one trip at a time: ticked in Packa or På plats and not in Hem. Other
#   meets leave it alone until then (on_another_trip). A lent vehicle cannot be packed (lent).
# - A tag that is not on one of the owner's vehicles answers unknown, and nothing is kept
#   (CAT-110). The owner's vehicle that is not on the list answers not_on_list; the same tap
#   with add puts it on the list and ticks it (CAT-181).
# - The tick that brings the last vehicle home archives the meet, once its date has come. The
#   owner may archive it by hand when nothing on it is away (CAT-183). An archived meet does
#   not change (archived), and its pack list starts the next one: NewTrip.template.


class TripStep(StrEnum):
    """The trip's three steps (CAT-176)."""

    PACK = "pack"
    """Packa: the vehicle is in the bag. A tick gives the state packed."""
    ARRIVE = "arrive"
    """På plats: the vehicle is on the layout. A tick gives the state at the meet."""
    HOME = "home"
    """Hem: the vehicle is back in its box. A tick puts it home, at its place."""


class TickBy(StrEnum):
    """How a tick was set (CAT-176)."""

    TAP = "tap"
    """Blippad: the vehicle's tag was tapped."""
    PRESS = "press"
    """A press on the vehicle's row."""


class Tick(Contract):
    """A bock: one per vehicle and step, with its time (CAT-176)."""

    step: TripStep
    at: datetime
    by: TickBy


class TripRow(Contract):
    """A vehicle on the pack list, with its ticks."""

    vehicle: Vehicle = Field(
        description="The vehicle as its owner sees it: its place, state and picture, and what "
        "someone who found it said (CAT-180)."
    )
    added_at: datetime
    ticks: list[Tick] = Field(description="At most one per step, in the steps' order.")
    last: Tick | None = Field(
        default=None,
        description="The latest tick: when, and in which step, the vehicle was last ticked. "
        "Saknas at Hem shows it (CAT-179).",
    )
    missing: bool = Field(
        description="Saknas: not ticked in Hem. When the trip is at Hem these come first (CAT-179)."
    )


class TripSummary(Contract):
    """A meet in the list of meets: the owner's own, with a name and a date (CAT-174)."""

    id: UUID
    name: Text = Field(max_length=80)
    date: date
    archived_at: datetime | None = Field(
        default=None,
        description="When the pack list was archived (CAT-183). An archived meet does not change.",
    )
    created_at: datetime
    template_of: UUID | None = Field(
        default=None, description="The meet whose pack list this one started from (CAT-183)."
    )
    vehicles: int = Field(description="How many vehicles are on the pack list.")
    done: dict[TripStep, int] = Field(
        description="How many are ticked in each step, for 3 av 4 (CAT-178)."
    )
    step: TripStep = Field(
        description="The step the trip is at: the latest one ticked in, or the next when that "
        "one is done. The web app opens it, and a tap without a step ticks in it."
    )


class Trip(TripSummary):
    """A meet with its pack list and its three steps (CAT-174–CAT-180)."""

    rows: list[TripRow] = Field(
        description="In the pack list's order; when the trip is at Hem, Saknas first (CAT-179)."
    )


class NewTrip(Contract):
    """A new meet: a name and a date (CAT-174), and perhaps an earlier meet's pack list."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    date: date
    template: UUID | None = Field(
        default=None,
        description="Ny träff från den här: the pack list starts as this meet's (CAT-183).",
    )


class PackList(Contract):
    """The pack list: all the vehicles that go to the meet (CAT-175). A vehicle taken off the
    list while it is away on this trip comes home."""

    vehicles: list[UUID] = Field(max_length=500)


class TickChange(Contract):
    """A press on the row: tick the vehicle in a step, or take the tick away (CAT-176)."""

    vehicle: UUID
    step: TripStep
    ticked: bool = Field(
        default=True, description="False takes the tick away, and moves the vehicle back."
    )


class TripTap(Contract):
    """A tag tapped in a step (CAT-176): Web NFC's serial number, a QR label's id or a simulated
    tag, as after /t/ in the address."""

    uid: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    step: TripStep | None = Field(
        default=None, description="The step shown; null ticks in the step the trip is at."
    )
    add: bool = Field(
        default=False,
        description="Lägg till: put the vehicle on the pack list first when it is not (CAT-181).",
    )


class TapOutcome(StrEnum):
    """What a tap in the trip did."""

    TICKED = "ticked"
    """The vehicle is ticked in the step."""
    NOT_ON_LIST = "not_on_list"
    """The owner's vehicle, not on the pack list: ask Lägg till, and tap again with add."""
    UNKNOWN = "unknown"
    """Not a tag on one of the owner's vehicles. Nothing more is said, and nothing is kept."""


class TripTapped(Contract):
    """The answer to a tap in the trip (CAT-176, CAT-181)."""

    outcome: TapOutcome
    vehicle_id: UUID | None = None
    title: str | None = Field(
        default=None, description="Litt and number, to ask: Lägg till Hbis 2253?"
    )
    trip: Trip


# --- The person's data (KONTO-31, CAT-193) ----------------------------------------------------


class VehicleHistory(Contract):
    """One vehicle's events, in the file with the person's data."""

    vehicle: UUID
    events: list[VehicleEvent]


class CatalogExport(Contract):
    """Everything Catalog holds for one owner, for the file the person fetches before removing the
    account (KONTO-31, ID7). Only TrainMeet ID asks, with a token of its own."""

    owner: UUID
    vehicles: list[Vehicle]
    history: list[VehicleHistory]
    places: list[Place]
    settings: OwnerSettings
    trips: list[Trip] = Field(
        default_factory=list, description="The meets with their pack lists and ticks (#55)."
    )


class OwnersRemoved(Contract):
    """TrainMeet ID says that these owners are gone: a removed account, and the clubs that went
    with it (CAT-193, ID13). Catalog removes their vehicles, places, tags and the rest."""

    owners: Annotated[list[UUID], Field(min_length=1, max_length=50)]


class RemovedCount(Contract):
    removed: int = Field(description="How many of the owners Catalog had.")


# --- The pictures (CAT-05, CAT-17, CAT-123–CAT-133) -------------------------------------------
#
#     GET    /api/catalog/1/vehicles/{id}/pictures                    [Picture], in order
#     POST   /api/catalog/1/vehicles/{id}/pictures?keep_original=&background=
#                                                                     the picture -> Picture
#     POST   /api/catalog/1/vehicles/{id}/pictures/{picture}/main     [Picture]
#     POST   /api/catalog/1/vehicles/{id}/pictures/{picture}/background
#                                                                     BackgroundChange -> Picture
#     DELETE /api/catalog/1/vehicles/{id}/pictures/{picture}          Removed
#     GET    /api/catalog/1/storage                                   StorageUse
#     GET    /api/catalog/1/pictures/file/{key}?expires=&sig=         the picture, only when
#                                                                     Catalog keeps them on disk
#
# Rules:
# - The picture is the request's body, as image/jpeg, image/png or image/webp: at most 15 MB
#   and 40 megapixel (CAT-123). Its metadata, such as position and camera, is removed before
#   anything is saved (CAT-124).
# - A display picture and a thumbnail are made at the upload; the original is kept only with
#   keep_original=true, Spara original, and counts in the storage (CAT-17, CAT-126).
# - At most 10 pictures per vehicle. The first is the main picture, and the database keeps it
#   to one (CAT-125). Removing the main picture makes the first of the rest the main one.
# - The storage counts per owner: 100 MB free for a person, 2 GB for a club (CAT-17, TOKEN-29).
#   Someone who edits a shared fleet stores with the owner, within the owner's limit (CAT-133).
# - The pictures are private and fetched with signed addresses that expire (CAT-130). The same
#   picture keeps its address for half an hour, so the browser can keep it.
# - The background removal (friläggning) runs on Catalog's own server with the U2NetP model and
#   costs no tokens; nothing is sent to an AI provider (CAT-18, CAT-127). Its mask gives the
#   vehicle's outline, and the vehicle's colours come only from the photo itself.
# - Five backgrounds (CAT-128): original, white, grey, transparent and rails. One is chosen at
#   the upload, original by default, and can be changed later without uploading again. With the
#   mask, the display picture and the thumbnail are cropped around the vehicle, so it stands in
#   the middle and fills them (CAT-129); the original background is cropped within the photo.
#   Transparent is a WebP with an alpha channel; the others are JPEG.
# - What is kept to change the background again, the photo at display size and the mask, counts
#   in the storage. A change that makes the picture larger needs room for it; one that does not
#   is always possible. Without the model only the original background can be chosen
#   (backgrounds_off, StorageUse.backgrounds); the uploads work as before.
# - To look is enough to see the pictures; to edit is needed to add, choose and remove them and
#   to change their background. ?fleet=<owner> works in a shared fleet, as for the vehicles
#   (#49).


class PictureBackground(StrEnum):
    """The picture's background (CAT-128). All but the original need the background removal."""

    ORIGINAL = "original"
    """The photo's own background, cropped around the vehicle when the mask is there."""
    WHITE = "white"
    GREY = "grey"
    TRANSPARENT = "transparent"
    """No background: a WebP with an alpha channel."""
    RAILS = "rails"
    """Räls: the vehicle stands on a track with sleepers, drawn by Catalog itself."""


class Picture(Contract):
    """One of the vehicle's pictures (CAT-05)."""

    id: UUID
    main: bool = Field(description="The vehicle's main picture: exactly one has it (CAT-125).")
    position: int = Field(ge=0, description="The order the pictures were added in.")
    width: int = Field(description="The display picture's width in pixels.")
    height: int = Field(description="The display picture's height in pixels.")
    bytes: int = Field(
        description="What the picture takes of the owner's storage, all its sizes (CAT-131)."
    )
    display_url: str = Field(description="The display picture, at most 1800 pixels (CAT-126).")
    thumb_url: str = Field(description="The thumbnail, at most 360×240 pixels (CAT-126).")
    original_url: str | None = Field(
        default=None, description="The original, only with Spara original (CAT-17)."
    )
    background: PictureBackground = Field(
        description="The background the display picture and the thumbnail have (CAT-128)."
    )


class StorageUse(Contract):
    """The owner's storage: what the pictures take, the free level, and what is paid over it
    this month (CAT-17, CAT-131, CAT-132)."""

    used: int = Field(description="Bytes the owner's pictures take, drafts' included.")
    limit: int = Field(description="The free level in bytes: 100 MB, or 2 GB for a club.")
    club: bool = Field(description="The owner is a club (TOKEN-29).")
    pictures: int = Field(description="How many pictures the owner has.")
    backgrounds: bool = Field(
        description="The background removal is on at this Catalog, so the other backgrounds "
        "than the original can be chosen (CAT-127, CAT-128)."
    )
    over_free: bool = Field(description="The pictures take more than the free level (CAT-132).")
    paid_blocks: int = Field(
        ge=0,
        description="Started GB over the free level that are paid this month, in Swedish time "
        "(CAT-132). They stay paid for the month, also when pictures are removed.",
    )
    price_per_gb: int = Field(
        description="Tokens a started GB over the free level costs a month: 20 (TK10)."
    )
    unpaid: bool = Field(
        description="This month's storage over the free level could not be drawn from the "
        "owner's balance: the pictures stay, but nothing that makes the storage larger is saved "
        "until it is paid (TK15)."
    )


class BackgroundChange(Contract):
    """A new background for a picture, made from what was kept at the upload (CAT-128)."""

    background: PictureBackground


# --- The reading of a photo with AI (#52, CAT-19, CAT-20, CAT-26, CAT-135–CAT-146) -------------
#
#     GET    /api/catalog/1/readings/consent        ReadingConsent: what is sent, to whom, the price
#     POST   /api/catalog/1/readings                multipart: data (ReadingAsk, JSON) and
#                                                   1–4 images -> Reading
#
# Rules:
# - The AI only suggests (CAT-136). A reading is a record of its own, apart from the vehicle: it
#   makes no vehicle and stores no picture (CAT-143). The web app fills the form with the
#   suggestions, and Spara saves them through the vehicle's own addresses.
# - The photos are read in TrainMeet ID's meter: TrainMeets AI, Claude through Amazon Bedrock in
#   the EU, or the account's own AI (CAT-26, TK4). Catalog never holds a key. Each photo is made
#   anew without position, camera or other metadata before it is sent (CAT-124), and is never
#   stored.
# - 12 tokens a picture, 0 with own AI (CAT-19), from the owner's balance: the person's, or the
#   club's for a club's fleet. They are reserved before the AI is asked and given back when it
#   fails (CAT-20), or when the answer comes after the vehicle changed (CAT-145, 409 changed).
# - The id comes from the client (CAT-144): the same id and the same photos again give the same
#   reading, without reading or drawing again. The same id with other photos is refused (409).
# - One reading at a time per person (409 reading_busy), and at most 10 an hour (429 too_many
#   with Retry-After) (CAT-146). A batch's photos have their own 30 an hour (see below).
# - The first time, the person sees what is sent and to whom, and the consent is kept as a
#   privacy event (CAT-142). Without it the reading answers 422 consent_required.
# - Only the owner reads with AI, and a club's administrators in the club's fleet (CAT-46): 403
#   for someone who may look or edit, 404 for someone who does not see the fleet. ?fleet=<owner>
#   as for the vehicles.
# - Without TrainMeet ID's API the reading is not available (503 unavailable).
# - What the AI may suggest: kind, litt, number, operator, maker and article_number (CAT-137).
#   An unreadable character is a ?, never a guess (CAT-138). Litt and number come only from
#   legible text, never from how the vehicle looks; maker and article number only from a
#   legible label or box (CAT-139). Anything else the AI says is dropped, and an answer that
#   cannot be read fails closed: nothing is suggested and nothing is drawn.
# - An uncertain digit in an EVN becomes a question, with the options whose check digit adds
#   up (CAT-140).

SuggestedField = Literal["kind", "litt", "number", "operator", "maker", "article_number"]
"""The core fields the AI suggests from a photo (CAT-137, CAT-139)."""


class ReadingStatus(StrEnum):
    PENDING = "pending"
    """The AI is reading."""
    DONE = "done"
    """Read: the suggestions are there."""
    FAILED = "failed"
    """The AI or its answer failed, or it took too long. Nothing was drawn."""
    DISCARDED = "discarded"
    """The answer came after the vehicle changed and was not used (CAT-145). Nothing was drawn."""


class Confidence(StrEnum):
    """The AI's own judgement, not a probability."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SuggestionBasis(StrEnum):
    """What a suggestion rests on."""

    VISIBLE_TEXT = "visible_text"
    """Legible text in the photo: a marking, a label or a box."""
    VISUAL_INFERENCE = "visual_inference"
    """What is seen of the shape or the colours. Never for litt, number, maker or article number
    (CAT-138, CAT-139)."""
    UNKNOWN = "unknown"


class Suggestion(Contract):
    """A value the AI suggests for a core field. Never saved before the owner has seen it."""

    value: Annotated[str, StringConstraints(min_length=1, max_length=80)] = Field(
        description="As for the field: kind is a VehicleKind; the number as painted, with ? for "
        "a character that could not be read (CAT-138)."
    )
    confidence: Confidence
    basis: SuggestionBasis
    evidence: Annotated[str, StringConstraints(max_length=400)] = Field(
        default="", description="Where in the photo it stands, in the AI's words."
    )


class ReadingQuestion(Contract):
    """An uncertain digit, asked of the owner (CAT-140)."""

    field: Literal["number"]
    options: list[str] = Field(
        min_length=1,
        max_length=10,
        description="The number as painted, with the digit that was uncertain filled in so that "
        "the EVN's check digit adds up.",
    )


class Reading(Contract):
    """What the AI suggests from the photos (CAT-136, CAT-137). Nothing of it is saved in a
    vehicle until the owner saves the form."""

    id: UUID = Field(description="The client's id for the reading (CAT-144).")
    status: ReadingStatus
    suggestions: dict[SuggestedField, Suggestion] = Field(
        default_factory=dict, description="Only the fields the AI could read, by the rules."
    )
    question: ReadingQuestion | None = None
    summary: Annotated[str, StringConstraints(max_length=1000)] = ""
    warnings: list[Annotated[str, StringConstraints(max_length=400)]] = Field(
        default_factory=list, max_length=12, description="What the owner should check."
    )
    suggested_next_photo: Annotated[str, StringConstraints(max_length=400)] = Field(
        default="", description="Another photo the AI asks for, such as a close-up (CAT-135)."
    )
    cost: int = Field(ge=0, description="Tokens drawn: 12 a picture, 0 with own AI (CAT-19).")
    model: Text = Field(description="The AI that read the photos.")


class ReadingAsk(Contract):
    """The part data of the reading's form, as JSON. The photos are the parts images."""

    id: UUID = Field(description="Made by the client, new for each reading (CAT-144).")
    consent: bool = Field(
        default=False,
        description="The person has seen what is sent and to whom, and says yes (CAT-142).",
    )
    vehicle: UUID | None = Field(
        default=None, description="The vehicle the photos are of, when it is saved already."
    )
    version: int | None = Field(
        default=None,
        ge=1,
        description="The vehicle's version, required with the vehicle: an answer after a change "
        "of the vehicle is not used (CAT-145).",
    )


class ReadingConsent(Contract):
    """What is sent and to whom, before the first reading (CAT-142), and the price."""

    available: bool = Field(description="The reading can be used here now.")
    message: str | None = Field(default=None, description="Why not, when it cannot be used.")
    given: bool = Field(description="The person has said yes before.")
    version: str = Field(description="The version of what the person says yes to.")
    sent_to: Text = Field(
        description="Who reads the photos: TrainMeets AI, or the account's own AI."
    )
    text: Text = Field(description="What is sent and to whom, as the person reads it.")
    own_ai: Text | None = Field(
        default=None, description="The model of the account's own AI, when it is connected."
    )
    price_per_picture: int = Field(ge=0, description="12 tokens, or 0 with own AI (CAT-19).")
    balance: int | None = Field(
        default=None, description="Tokens left on the balance that pays, when ID says."
    )
    payer: Text | None = Field(
        default=None, description="Whose balance pays: the person's, or the club's."
    )


# --- Flera foton i en omgång (#52 del b, CAT-146–CAT-153) ---------------------------------------
#
#     GET    /api/catalog/1/batches                             [BatchSummary]: the open batches
#     POST   /api/catalog/1/batches                             multipart: data (BatchAsk, JSON)
#                                                               and 1–30 images -> Batch
#     GET    /api/catalog/1/batches/{batch}                     Batch, with its cards
#     DELETE /api/catalog/1/batches/{batch}                     Removed: its cards not approved
#     POST   /api/catalog/1/batches/{batch}/cards/{card}        BatchCardChange -> BatchCard
#     DELETE /api/catalog/1/batches/{batch}/cards/{card}        Removed
#     POST   /api/catalog/1/batches/{batch}/cards/{card}/retry  BatchCard, in the queue again
#     POST   /api/catalog/1/batches/{batch}/approve             BatchApproval -> Batch
#
# Rules:
# - Up to 30 photos in a batch, one per vehicle (CAT-147). Each becomes a card: a draft of its
#   own, kept apart from the vehicles. The drafts are not vehicles: they are not in the vehicle
#   list, the sharing, the tags, the lookup, the trips or the export until the owner has
#   approved them (CAT-148).
# - The batch's id comes from the client. The photos may be sent in several requests with the
#   same id, each at most 60 MB, and each photo at most 15 MB and 40 megapixel (CAT-123). Each
#   photo is made anew without metadata when it comes (CAT-124), and only that picture is kept.
# - The same original file, by its SHA-256, gives one card per owner: sent again, in a retry or
#   in a new batch, it gives the card it already is, listed in Batch.already (CAT-149).
# - The photos are read by the AI in a queue, one at a time and in the order they came, as
#   readings of their own (CAT-143): 12 tokens a photo, 0 with own AI, reserved and drawn or
#   given back as for one reading (CAT-19, CAT-20). The queue is in the database: after a
#   restart, reservations that ran out are given back, and a photo that was cut off is failed
#   and can be read again without anything being drawn twice (CAT-151).
# - At most 30 readings an hour for a batch (CAT-146). Then, and when the day's cap in TrainMeet
#   ID is reached, the queue waits and goes on by itself (Batch.waiting_until).
# - When the tokens run out, the photos that are left become drafts to fill in by hand, with a
#   message to say so (CAT-152).
# - Only the owner reads with AI, and a club's administrators in the club's fleet (CAT-46); the
#   first time with the consent, as for one reading (CAT-142). Someone who edits a shared fleet
#   may leave photos for the owner without AI: their cards are manual, read by no AI and cost no
#   tokens. They see only the batches they left, and those cards only until they are approved;
#   never the owner's drafts (CAT-153). To look gives no batches at all.
# - Godkänn alla is all or nothing (CAT-150): it carries every open card of the batch with the
#   version the owner saw, and either all of them become vehicles, in one transaction, or none
#   does. A card still waiting or being read stops it (409), and so do values that do not make a
#   vehicle (422, Problem.cards names the cards). Each vehicle gets the values the owner saw and
#   kept (CAT-136), with the source ai for a value the AI suggested and nobody changed, and the
#   photo as its main picture, which counts in the owner's storage from then on (CAT-131).
# - Removing a card or a batch removes its files; so does removing the account (CAT-193).
#   Removing a batch removes its cards that are not approved; the vehicles stay.
# - ?fleet=<owner> works in a shared fleet, as for the vehicles.

MAX_BATCH_PHOTOS = 30
"""Photos in one batch (CAT-147)."""


class BatchCardStatus(StrEnum):
    """Where a photo of a batch is (CAT-147–CAT-153)."""

    WAITING = "waiting"
    """In the queue: the AI reads the photos one at a time, in turn."""
    READING = "reading"
    """The AI reads it now."""
    READY = "ready"
    """Read: the suggestions are in the values, and nothing needs checking."""
    REVIEW = "review"
    """Read, but something to check: a warning, an uncertain field, a question about a digit,
    or no kind, or no litt or number."""
    FAILED = "failed"
    """The reading failed, or was cut off. Nothing was drawn. Read it again, or fill it in."""
    MANUAL = "manual"
    """To fill in by hand, without AI: left by someone who edits the fleet, a batch without
    AI, or the tokens ran out (CAT-152, CAT-153)."""
    APPROVED = "approved"
    """A vehicle now (CAT-150)."""


class BatchCard(Contract):
    """One photo of a batch: a draft of one vehicle, not a vehicle (CAT-147, CAT-148)."""

    id: UUID
    batch: UUID
    position: int = Field(ge=0, description="The order the photos came in, and are read in.")
    status: BatchCardStatus
    version: int = Field(
        ge=1,
        description="Raised by every change of the values, also by the AI's. A change and "
        "Godkänn alla carry the version seen, so nothing unseen is saved (CAT-136).",
    )
    values: VehicleFields = Field(
        description="What the vehicle becomes when it is approved: the AI's suggestions, and "
        "then what the owner writes."
    )
    suggestions: dict[SuggestedField, Suggestion] = Field(
        default_factory=dict, description="What the AI suggested, as for one reading."
    )
    question: ReadingQuestion | None = None
    warnings: list[Annotated[str, StringConstraints(max_length=400)]] = Field(
        default_factory=list, max_length=12, description="What the owner should check."
    )
    message: str = Field(
        default="",
        description="Why the card is as it is, in Swedish: such as why the reading failed, or "
        "that the tokens ran out (CAT-152).",
    )
    picture: PictureLinks | None = Field(
        default=None,
        description="The photo, without metadata, at most 1800 pixels: signed addresses that "
        "expire (CAT-130). Null once approved: the vehicle has it then.",
    )
    vehicle: UUID | None = Field(default=None, description="The vehicle, once approved.")
    attempts: int = Field(ge=0, description="How many times the AI has been asked to read it.")


class Batch(Contract):
    """A batch of photos and its cards (CAT-147)."""

    id: UUID = Field(description="Made by the client (CAT-149).")
    ai: bool = Field(description="The photos are read with AI; else they are filled in by hand.")
    mine: bool = Field(description="The person asking made the batch.")
    created_at: datetime
    cards: list[BatchCard] = Field(
        description="In order. Someone who edits the fleet sees only the cards not approved."
    )
    waiting_until: datetime | None = Field(
        default=None,
        description="The queue waits for the hour's limit or the day's cap, and goes on by "
        "itself then (CAT-146).",
    )
    message: str | None = Field(default=None, description="Why the queue waits, in Swedish.")
    already: list[UUID] = Field(
        default_factory=list,
        description="Only in the answer to POST: the cards that photos sent this time already "
        "were, in this batch or another, since the same file is never two drafts (CAT-149).",
    )


class BatchSummary(Contract):
    """A batch in the list: one with photos still to approve."""

    id: UUID
    ai: bool
    mine: bool
    created_at: datetime
    cards: int = Field(description="Its cards, approved ones included.")
    open: int = Field(description="Its cards not yet approved.")
    counts: dict[BatchCardStatus, int] = Field(description="Its cards per status.")


class BatchAsk(Contract):
    """The part data of the batch's form, as JSON. The photos are the parts images."""

    id: UUID = Field(description="Made by the client. Sent again, the photos are added to it.")
    ai: bool = Field(
        default=True,
        description="Read the photos with AI. Only the owner, or a club's administrator; "
        "someone who edits the fleet sends false (CAT-153).",
    )
    consent: bool = Field(
        default=False,
        description="The person has seen what is sent and to whom, and says yes (CAT-142).",
    )


class BatchCardChange(Contract):
    """The values of a card, as the owner writes them, and the version they were seen at."""

    values: VehicleFields
    version: int = Field(ge=1)


class BatchCardSeen(Contract):
    """A card as the owner saw it before Godkänn alla."""

    id: UUID
    version: int = Field(ge=1)


class BatchApproval(Contract):
    """Godkänn alla: every open card of the batch, as seen (CAT-150)."""

    cards: list[BatchCardSeen] = Field(min_length=1, max_length=MAX_BATCH_PHOTOS)
