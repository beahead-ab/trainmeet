"""TrainMeet Catalog's API, trainmeet.catalog/1 (CAT-36): what the web app and others read.

Catalog is its own service with its own database (C16, CAT-30). It never calls the Hub and
the Hub never calls it (K7, CAT-37). Step 1 (#48) has the version, the session and the trial
login, and #50 the vehicles and the places at home. The mini card, the tag, the lookup and the
prototype come with their steps (#54 and #53), in this file. A meet's vehicles wait for the
link to the Hub (CAT-189, VILAR).

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

from contracts.common import Contract, Text


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
    """The core fields the owner writes (CAT-53). Images, tag and prototype come later."""

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
    """More than 30 lookups in a minute: try again in a minute (CAT-111, CAT-112)."""
    NOT_HERE = "not_here"
    """Simulated tags exist only in the test environment (CAT-96)."""
    FORBIDDEN = "forbidden"
    """The fleet is shared with the asker, but only the owner may do this (CAT-46, CAT-49)."""
    UNAVAILABLE = "unavailable"
    """TrainMeet ID does not answer, so nothing shared can be shown just now (#49)."""


class Problem(Contract):
    """The answer when Catalog says no: 401, 403, 404, 409, 422 or 503."""

    code: ProblemCode
    message: str = Field(description="The same in Swedish, for logs and other readers.")


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
