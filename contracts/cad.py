"""TrainMeet CAD's API, trainmeet.cad/1 (#89): the module library.

CAD is a cloud service of its own on TrainMeet ID, at cad.trainmeet.app (CAD-14, stacken). It
owns the modules with their versions, the gables and the gable profiles, and the drawings as
geometry (CAD-08). It never owns the signals, addresses and routes (Studio), the stations (TKL)
or the meet's line (the Hub) (CAD-09). Code measures and decides; AI only proposes (CAD-17).

Part a of #89 has the library: a module from measures only (CAD-01, "Bara mått"), straight or
curved, its page with the gables, the visibility, the versions and the history (CAD-05), the
gable profiles (CAD-07, CAD-22), and the track graph a module from measures gets straight from
its gables. Part b has Ritningen (CAD-03): the editing operations as a change set on a version,
the switch inspector and the switch library, Att kolla, utjämning, and Lås mått with clean
geometry (CAD-24), with the ids kept and the splits recorded (CAD-20). The photo chain (part c)
and the assemblies, the export and the way to Studio (part d) add to this file; nothing here
changes meaning for them: the photo's line is a DrawnLine with the source photo, and AI's
questions are CheckItems of the kind question.

Addresses:
    GET    /api/version                                     CadVersion
    GET    /api/cad/1/session                               CadSession
    DELETE /api/cad/1/session                               CadSession, logged out
    GET    /api/cad/1/id/login?next=&lang=                  to TrainMeet ID (OIDC with PKCE)
    GET    /api/cad/1/id/callback                           back from ID, the session starts
    GET    /api/cad/1/trial/accounts                        [CadAccount], trial login only
    POST   /api/cad/1/trial/login                           CadTrialLogin -> CadSession
    GET    /api/cad/1/libraries                             [Library]: mine, my clubs', all
    GET    /api/cad/1/modules?library=&scale=&q=            ModuleList
    POST   /api/cad/1/modules                               NewModule -> Module, 201
    GET    /api/cad/1/modules/{module}                      Module, the latest version
    PUT    /api/cad/1/modules/{module}                      ModuleChange -> Module, a new version
    GET    /api/cad/1/modules/{module}/versions/{version}   Module as that version was
    GET    /api/cad/1/modules/{module}/history              [ModuleEvent], newest first
    POST   /api/cad/1/modules/{module}/approve              ModuleApproval -> Module
    PUT    /api/cad/1/modules/{module}/visibility           VisibilityChange -> Module
    DELETE /api/cad/1/modules/{module}                      ModuleRemoved; soft, history stays
    POST   /api/cad/1/modules/{module}/drawing              DrawingEdit -> DrawingView
    POST   /api/cad/1/modules/{module}/drawing/save         DrawingEdit -> Module, a new version
    POST   /api/cad/1/modules/{module}/drawing/approve      DrawingEdit -> Module, approved
    POST   /api/cad/1/modules/{module}/drawing/lock         LockAsk -> LockProposal
    GET    /api/cad/1/modules/{module}/checks?version=      [CheckItem]
    POST   /api/cad/1/smooth                                SmoothAsk -> SmoothResult
    GET    /api/cad/1/profiles?scale=                       ProfileList
    POST   /api/cad/1/profiles                              NewProfile -> GableProfile, 201

Rules:
- The session is an HttpOnly cookie; every changing call checks it on the server.
- Only the owner and those with the role redigera change a module (CAD-21): a person's own
  module, the club's administrators for a club's, and anyone TrainMeet ID gives the role editor
  on the module (KONTO-36). Whoever sees a module may use it. Who sees it follows its
  visibility: jag, klubben or alla, with the clubs from ID (#67). CAD asks ID at every call.
- Every save is a new version; a version is never changed (CAD-08). The newest is a draft until
  it is approved. An assembly pins the module versions it uses (CAD-21, part d).
- The scale sits on the module and the norm on each gable (CAD9, CAD-22): H0, N and 0; in H0
  FREMO, MMM, USMS and the club's own norm, in N FREMO N (CAD14), in 0 FREMO Spur 0 (CAD12).
- Every track piece and switch keeps its id when the module is redrawn, so that Studio keeps the
  owner's additions (CAD-20, CAD13). A piece split keeps its id on its first part, and the
  version records the split (DrawingState.ids).
- Ritningen's change set is replayed on the newest version for every call; Spara and Godkänn
  spårplanen are refused with 409 when a newer version exists. A version with open Att kolla
  items is never approved.

The track graph and the station model (contracts/station_model.py): a node is a station-model
Node with its point in mm, and its type is one of the station model's (module_joint for a track
at a gable). A piece keeps its id, start and end, and its LINE and ARC segments become the
station model's geometry by sampling the arcs (a line is its two ends). A switch is the station
model's Switch with the same trunk, straight and diverging pieces. Coordinates are the module's
own, as the station model's: x from gable A along Kant 1, y away from Kant 1, in mm, so y runs
down the drawing as in the station model. In an assembly each module is placed with a shift and
a turn, and its ids are prefixed with the module's id ("<module>:<id>"); where two gables meet,
a track is one node, the smaller of the two ids (part d).
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from contracts.common import AppKey, Contract, Id, Text
from contracts.station_model import NodeType, Point, SignalType, SwitchType

FORMAT: Final = "trainmeet.cad/1"

Mm = Annotated[float, Field(gt=0, le=20_000)]
"""A length in millimetres, greater than zero."""

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
"""A name a person gives: a module's, a profile's."""

MAX_TRACKS: Final = 12
"""The most tracks a gable has."""

ASCENDING: Final = "Spåren räknas från Kant 1: varje spår ligger längre bort än det förra."

POSITION_TOLERANCE: Final = 0.5
"""How close in mm a gable's track must lie to the profile's fixed position (the photo test found
the track in the gable to ±0,5 mm, CADMOB-16)."""


# --- Version, login, session -------------------------------------------------------------


class CadVersion(Contract):
    """What is running, so a tester can see which change the test environment has."""

    product: Literal["TrainMeet CAD"] = "TrainMeet CAD"
    version: str = Field(description="The package version, for example 0.1.0.")
    commit: str | None = Field(default=None, description="The git commit, or null locally.")
    pr: int | None = Field(default=None, description="The pull request the change came from.")
    title: str | None = Field(default=None, description="The title of that pull request.")
    built: datetime | None = Field(default=None, description="When the image was built, UTC.")


class LoginKind(StrEnum):
    """How people log in to this CAD."""

    TRIAL = "trial"
    """The trial login: fixed accounts, only in the browser test and the test environment."""
    ID = "id"
    """TrainMeet ID: GET /api/cad/1/id/login sends the browser there."""


class CadAccount(Contract):
    """The person who is logged in, as CAD knows them. The id is ID's subject."""

    id: UUID
    name: Text = Field(max_length=80)
    initials: str = Field(min_length=1, max_length=3, description="For the account button.")


class ClubChoice(Contract):
    """One of the person's clubs in TrainMeet ID (#67)."""

    id: UUID
    name: Text = Field(max_length=80)
    admin: bool = Field(description="The person is the club's administrator.")


class CadSession(Contract):
    """Who is logged in, if anyone, and how one logs in here."""

    account: CadAccount | None = None
    login: LoginKind
    clubs: list[ClubChoice] = Field(
        default_factory=list, description="The person's clubs, as ID says now."
    )
    apps: list[AppKey] | None = Field(
        default=None,
        description="The app switcher's apps, as ID says (ID11); null when ID does not answer.",
    )
    tokens: int | None = Field(
        default=None,
        description="The tokens left on the person's own account in ID (TOKEN-01); null "
        "without ID or when ID does not answer.",
    )
    tokens_url: str | None = Field(default=None, description="Tokens in TrainMeet ID.")
    help_url: str | None = Field(
        default=None, description="Hjälp och fel in TrainMeet ID (KONTO-06)."
    )
    logout_url: str | None = Field(
        default=None,
        description="Only in the answer to logging out: where the browser goes next, so that "
        "TrainMeet ID logs out too (KONTO-01).",
    )


class CadTrialLogin(Contract):
    account: UUID


class ProblemCode(StrEnum):
    """Why CAD said no. The web app has the text for each."""

    LOGIN = "login"
    """Not logged in."""
    NOT_FOUND = "not_found"
    """The module or profile does not exist, or is not visible to the one asking."""
    FORBIDDEN = "forbidden"
    """Seen, but only the owner and those with the role redigera may do this (CAD-21)."""
    CHANGED = "changed"
    """The module has a newer version than the one the change builds on: open it again."""
    INVALID = "invalid"
    """The measures do not hang together; the message says how."""
    UNAVAILABLE = "unavailable"
    """TrainMeet ID does not answer just now."""
    NO_TOKENS = "no_tokens"
    """The balance is not enough for a photo's AI reading (part c1)."""
    TOO_MANY = "too_many"
    """The day's cap in ID is reached."""
    READING_FAILED = "reading_failed"
    """The AI's reading failed; nothing was drawn."""
    BAD_PHOTO = "bad_photo"
    """The photo cannot be taken in: its format, its size or the quality gate."""
    STORAGE_FULL = "storage_full"
    """CAD's 100 MB for module photos are used (CAD-19)."""
    CONSENT_REQUIRED = "consent_required"
    """The person has not said yes to sending the photo to AI yet."""
    BUSY = "busy"
    """A photo is being read already."""
    BAD_DRAWING = "bad_drawing"
    """The drawing cannot be taken in: its format, its size or its pages (part c4)."""


class CadProblem(Contract):
    """The answer when CAD says no: 401, 402, 403, 404, 409, 413, 415, 422, 429, 502 or 503."""

    code: ProblemCode
    message: str = Field(description="In Swedish, for the person and for logs.")


# --- Scale and norm (CAD9–CAD12, CAD-22) ----------------------------------------------------


class Scale(StrEnum):
    """The module's scale (CAD10, CAD12)."""

    H0 = "H0"
    N = "N"
    ZERO = "0"


class Norm(StrEnum):
    """A gable's norm: the organisation whose rules the gable follows (CAD9, CAD11, CAD12)."""

    FREMO = "fremo"
    MMM = "mmm"
    USMS = "usms"
    """A module norm in CAD; not F26's US code in the Hub (CAD11)."""
    CLUB = "club"
    """Klubbens egen norm: a club's own gable profiles."""
    FREMO_SPUR_0 = "fremo_spur_0"
    """FREMO Spur 0, the norm in scale 0 (CAD12)."""
    FREMO_N = "fremo_n"
    """FREMO N, the norm in scale N from the start (CAD14)."""


NORMS: Final[dict[Scale, tuple[Norm, ...]]] = {
    Scale.H0: (Norm.FREMO, Norm.MMM, Norm.USMS, Norm.CLUB),
    Scale.N: (Norm.FREMO_N,),
    Scale.ZERO: (Norm.FREMO_SPUR_0,),
}
"""The norms per scale from the start (CAD11, CAD12, CAD14)."""

NORM_NAMES: Final[dict[Norm, str]] = {
    Norm.FREMO: "FREMO",
    Norm.MMM: "MMM",
    Norm.USMS: "USMS",
    Norm.CLUB: "Klubbens egen",
    Norm.FREMO_SPUR_0: "FREMO Spur 0",
    Norm.FREMO_N: "FREMO N",
}


class NormInfo(Contract):
    norm: Norm
    name: Text


# --- Gable profiles (CAD-07, CAD-22) -------------------------------------------------------

ProfileId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
"""A gable profile's id: the norms' and the general ones' are fixed words, an own one's random."""


class ProfileKind(StrEnum):
    NORM = "norm"
    """A norm's gable, as the norm says (Norm)."""
    GENERAL = "general"
    """Allmän: shared by all, the positions given per module (Allmän)."""
    OWN = "own"
    """Egen: a person's or a club's, every position measured (Egen)."""


class OwnerKind(StrEnum):
    PERSON = "person"
    CLUB = "club"


class Owner(Contract):
    """Who owns a module or an own gable profile: a person or a club in TrainMeet ID."""

    kind: OwnerKind
    id: UUID
    name: Text = Field(max_length=80)


class GableProfile(Contract):
    """Gavelprofil: where the tracks go through a gable, measured from Kant 1. Modules with the
    same profile fit together. A position the profile leaves open is given per module."""

    id: ProfileId
    name: Name
    kind: ProfileKind
    scale: Scale
    norm: Norm | None = None
    tracks: int = Field(ge=1, le=MAX_TRACKS, description="How many tracks.")
    first: float | None = Field(
        default=None, gt=0, description="Kant 1 → spår 1 in mm; null: given per module."
    )
    spacings: list[float | None] = Field(
        default_factory=list,
        description="Spår n → spår n + 1 in mm, one fewer than the tracks; null: per module.",
    )
    read: bool = Field(
        default=True,
        description="The norm's exact measures are read in. False: they are read in before "
        "the launch (CAD-N), and what is open is given per module.",
    )
    note: Text | None = Field(default=None, description="Where the measures come from.")
    owner: Owner | None = Field(default=None, description="An own profile's owner.")
    uses: int = Field(
        default=0, ge=0, description="How many gables in the modules the person sees use it."
    )

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if len(self.spacings) != self.tracks - 1:
            raise ValueError("En gavelprofil har ett spåravstånd färre än spåren.")
        if any(s is not None and s <= 0 for s in self.spacings):
            raise ValueError("Ett spåravstånd är större än noll.")
        if self.kind == ProfileKind.NORM and (self.norm is None or self.owner is not None):
            raise ValueError("En normprofil har en norm och ingen ägare.")
        if self.kind == ProfileKind.GENERAL and (self.norm is not None or self.owner is not None):
            raise ValueError("En allmän gavelprofil har ingen norm och ingen ägare.")
        if self.kind == ProfileKind.OWN and (self.owner is None or self.first is None):
            raise ValueError("En egen gavelprofil har en ägare och alla spårens lägen.")
        if self.kind == ProfileKind.OWN and any(s is None for s in self.spacings):
            raise ValueError("En egen gavelprofil har alla spårens lägen.")
        if self.norm is not None and self.norm not in NORMS[self.scale]:
            raise ValueError(f"Normen {NORM_NAMES[self.norm]} finns inte i skala {self.scale}.")
        return self


class NewProfile(Contract):
    """An own gable profile, a person's or a club's: every track's position from Kant 1. A club's
    profile can be the club's own norm (CAD11)."""

    name: Name
    scale: Scale
    norm: Norm | None = None
    owner: UUID | None = Field(default=None, description="A club's id; null: the person's own.")
    tracks: list[Mm] = Field(
        min_length=1, max_length=MAX_TRACKS, description="Every track's position from Kant 1."
    )

    @model_validator(mode="after")
    def _ascending(self) -> Self:
        if any(b <= a for a, b in zip(self.tracks, self.tracks[1:], strict=False)):
            raise ValueError(ASCENDING)
        if self.norm is not None and self.norm not in NORMS[self.scale]:
            raise ValueError(f"Normen {NORM_NAMES[self.norm]} finns inte i skala {self.scale}.")
        if self.norm == Norm.CLUB and self.owner is None:
            raise ValueError("Klubbens egen norm hör till en klubb.")
        return self


class ProfileList(Contract):
    scale: Scale
    norms: list[NormInfo] = Field(description="The norms in this scale (CAD11, CAD12).")
    profiles: list[GableProfile]


# --- The module's shape -------------------------------------------------------------------


class Straight(Contract):
    """Rak modul: length × width."""

    kind: Literal["straight"] = "straight"
    length: Mm = Field(description="Along Kant 1, gable A to gable B.")
    width: Mm = Field(description="Gable width, Kant 1 to the far side.")


class CurveMeasure(Contract):
    """The owner's measurement of a curve: a string between track 1's centre at A and B, and the
    sagitta (pilhöjd) from the string's middle to the track (CADMOB-03)."""

    chord: Mm
    sagitta: Mm

    @model_validator(mode="after")
    def _arc(self) -> Self:
        if self.sagitta >= self.chord / 2:
            raise ValueError("Pilhöjden är mindre än halva snöret.")
        return self


class EdgeSide(StrEnum):
    """Which edge of a curve module is Kant 1."""

    OUTER = "outer"
    INNER = "inner"


class CurveSides(StrEnum):
    """The box's long sides."""

    BENT = "bent"
    STRAIGHT = "straight"


class Curve(Contract):
    """Kurvmodul: track 1's radius and the angle, from the string and sagitta or given directly.
    With Kant 1 as the outer edge the curve turns right seen from gable A, as in the drawing."""

    kind: Literal["curve"] = "curve"
    radius: Mm = Field(description="Track 1's centre line, in mm.")
    angle: float = Field(gt=0, lt=180, description="The angle, in degrees.")
    width: Mm = Field(description="The module body's width, Kant 1 to the other edge.")
    edge: EdgeSide = EdgeSide.OUTER
    sides: CurveSides = CurveSides.BENT
    measured: CurveMeasure | None = Field(
        default=None, description="The string and sagitta the radius and angle came from."
    )


class Trapezoid(Contract):
    """A trapezoid, as MMM's (685 × 480/280): the gables parallel, length apart, width_a and
    width_b wide. Gable B's corner at Kant 1 lies offset mm from gable A's across the module (y
    down), the förskjutning the photo test solved for (lärdomarna, Trapets). With offset 0 Kant 1
    is straight and at right angles to the gables, and only the far side slants. A track at the
    same distance from Kant 1 in both gables of a slanting Kant 1 has to bend: Lås mått makes it
    straight, arc, straight, arc, straight (CAD-24)."""

    kind: Literal["trapezoid"] = "trapezoid"
    length: Mm
    width_a: Mm
    width_b: Mm
    offset: float = Field(
        default=0,
        ge=-20_000,
        le=20_000,
        description="Förskjutning: gable B's Kant 1 corner across the module from gable A's, mm.",
    )


Shape = Annotated[Straight | Curve | Trapezoid, Field(discriminator="kind")]


# --- Gables -------------------------------------------------------------------------------


class GableEnd(StrEnum):
    A = "A"
    B = "B"


class Gable(Contract):
    """Gavel: a module's end, with its norm, its profile and where the tracks go through it, in
    mm from Kant 1, track 1 nearest Kant 1. Without a profile it is an own gable, measured here."""

    end: GableEnd
    norm: Norm | None = None
    profile: ProfileId | None = Field(default=None, description="Null: egen gavel.")
    tracks: list[Mm] = Field(default_factory=list, max_length=MAX_TRACKS)

    @model_validator(mode="after")
    def _ascending(self) -> Self:
        if any(b <= a for a, b in zip(self.tracks, self.tracks[1:], strict=False)):
            raise ValueError(ASCENDING)
        return self


class GableLabel(Contract):
    """A gable as the library shows it: "FREMO dubbelspår", "Egen gavel · 3 spår"."""

    end: GableEnd
    label: Text
    norm: Norm | None = None
    profile: ProfileId | None = None
    tracks: list[float]


class GableCount(Contract):
    """Gavlar i biblioteket: how many gables of one kind."""

    label: Text
    profile: ProfileId | None = None
    count: int = Field(ge=0)


# --- The track graph (CAD-08, CAD-10, CAD-20) --------------------------------------------


class LineSegment(Contract):
    """LINE: a straight piece of track centre, in mm."""

    kind: Literal["line"] = "line"
    start: Point
    end: Point


class ArcSegment(Contract):
    """ARC: a circular piece of track centre, in mm, as DXF's ARC. clockwise is as the drawing
    shows it, with y down."""

    kind: Literal["arc"] = "arc"
    start: Point
    end: Point
    center: Point
    radius: Mm
    clockwise: bool

    @model_validator(mode="after")
    def _on_circle(self) -> Self:
        for point in (self.start, self.end):
            off = math.dist(point, self.center) - self.radius
            if abs(off) > max(0.5, self.radius * 1e-6):
                raise ValueError("Bågens ändar ligger inte på cirkeln.")
        return self


Segment = Annotated[LineSegment | ArcSegment, Field(discriminator="kind")]

SwitchDesignId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]
"""A switch type's id in the switch library (Växeltyp)."""

CAD_NODE_TYPES: Final = frozenset(
    {
        NodeType.MODULE_JOINT,
        NodeType.SWITCH,
        NodeType.CROSSING,
        NodeType.BUFFER_STOP,
        NodeType.JOINT,
    }
)
"""The station model's node types CAD draws. Signals, stop points and line exits are Studio's
(CAD-09); a track at the gable is a module joint until Studio says it is the station's border."""

SCHEMA_NODE_TYPES: Final = frozenset(
    {
        NodeType.SWITCH,
        NodeType.CROSSING,
        NodeType.BUFFER_STOP,
        NodeType.LINE_EXIT,
        NodeType.JOINT,
    }
)
"""The node types of a drawing read for Studio (geometry "schema", bildkedjan R4): switch,
crossing, buffer stop, line exit, and a joint where a track only bends. A track's end is a
buffer stop or a line exit, with its certainty; there are no gables in a drawing."""


class Certainty(StrEnum):
    """How sure a fact is, as in the import and the photo chain (bildkedjan, principle 4)."""

    CERTAIN = "certain"
    """Säker: two independent sources agree."""
    PROBABLE = "probable"
    """Trolig: measured by code within the tolerance."""
    UNCERTAIN = "uncertain"
    """Osäker: only AI, assumed, or outside the tolerance. Orange until the owner approves."""
    CONFIRMED = "confirmed"
    """Bekräftad: the owner has approved or locked it."""


class GraphSource(StrEnum):
    """Where a piece of the graph comes from."""

    MEASURES = "measures"
    """The owner's measures and gables (CAD-01, Bara mått)."""
    PHOTO = "photo"
    SKETCH = "sketch"
    ANYRAIL = "anyrail"
    DRAWN = "drawn"
    """Drawn or changed in the drawing (part b)."""
    DRAWING = "drawing"
    """Read from a station drawing uploaded in Studio (profile Stationsritning, part c4)."""


class ReadBy(StrEnum):
    """How a label's text came out of a drawing (bildkedjan R4): the PDF's or SVG's own text
    layer, read by code; OCR; or transcribed by AI from a raster page."""

    TEXT_LAYER = "text_layer"
    OCR = "ocr"
    AI = "ai"


class GraphOrigin(Contract):
    source: GraphSource
    certainty: Certainty


class GraphNode(Contract):
    """Nod: where pieces meet or end. A track at a gable is a module joint with its gable and
    its track number there."""

    id: Id
    type: NodeType
    at: Point
    gable: GableEnd | None = None
    track: int | None = Field(default=None, ge=1, le=MAX_TRACKS, description="Spår n i gaveln.")

    @model_validator(mode="after")
    def _kind(self) -> Self:
        if self.type not in CAD_NODE_TYPES | SCHEMA_NODE_TYPES:
            raise ValueError(f"CAD ritar inte noder av typen {self.type.value}.")
        if (self.type == NodeType.MODULE_JOINT) != (self.gable is not None):
            raise ValueError("En nod i gaveln är en modulskarv, och en modulskarv sitter i gaveln.")
        return self


class GraphPiece(Contract):
    """Spårbit: track centre from one node to another, as LINE and ARC segments in order."""

    id: Id
    start: Id
    end: Id
    segments: list[Segment] = Field(min_length=1)
    track: Text | None = Field(default=None, description="Spårnummer, när ägaren har gett det.")
    origin: GraphOrigin | None = None

    @model_validator(mode="after")
    def _continuous(self) -> Self:
        for before, after in zip(self.segments, self.segments[1:], strict=False):
            if math.dist(before.end, after.start) > 0.5:
                raise ValueError(f"Spårbiten {self.id} har ett glapp mellan två delar.")
        return self


class GraphSwitch(Contract):
    """Växel, korsningsväxel eller korsning, at a node: the station model's Switch with CAD's
    ids. The diverging leg's radius and angle, when known. The node is the points (tungspetsen);
    the diverging leg leaves the through track tangentially toward gable A or B (lärdomarna,
    Växlar). design is the switch type from the switch library (Växeltyp), null while Okänd."""

    id: Id
    node: Id
    type: SwitchType
    trunk: Id | None = None
    straight: Id | None = None
    diverging: Id | None = None
    radius: Mm | None = None
    angle: float | None = Field(default=None, gt=0, lt=90)
    origin: GraphOrigin | None = None
    number: Text | None = Field(default=None, max_length=20, description="Växelnummer.")
    design: SwitchDesignId | None = Field(default=None, description="Växeltyp; null: Okänd.")
    toward: GableEnd | None = Field(
        default=None, description="The gable the diverging leg heads for."
    )
    locked: bool = Field(
        default=False,
        description="Lås växelns läge när kurvorna räknas om: Lås mått keeps the points where "
        "they are.",
    )


class GraphLabel(Contract):
    """Etikett: a text in the drawing at a point in mm, on a piece or a switch or free
    (bildkedjan, R4 and point 21). The Text tool writes them. In a drawing read for Studio the
    point is in the drawing's own coordinates, ref is the object code tied it to (the nearest
    one), and read_by says how the text was read."""

    id: Id
    text: Text = Field(max_length=40)
    at: Point
    ref: Id | None = Field(default=None, description="The piece, switch, node or symbol it names.")
    origin: GraphOrigin | None = None
    read_by: ReadBy | None = Field(
        default=None, description="Textlager, OCR eller AI; null: written in CAD."
    )


class SymbolKind(StrEnum):
    """What a symbol in a drawing is, classed against the standard interlocking's catalogue
    (bildkedjan R3, contracts/station_model.py)."""

    SIGNAL = "signal"
    """A signal of the catalogue's types (SignalType: Hsi, Hdvsi, Dvsi, Fsi, stop lamp)."""
    BUFFER_STOP = "buffer_stop"
    UNKNOWN = "unknown"
    """Not in the catalogue, or not yet answered: a question per symbol type."""


class GraphSymbol(Contract):
    """Symbol: a figure in a drawing (a signal figure, a triangle, a circle), with its class from
    the catalogue, the way it faces, the track it stands by and how sure the class is (R3, R4).
    A signal's name and address are those read from its label, when there is one."""

    id: Id
    kind: SymbolKind
    signal: SignalType | None = Field(default=None, description="The catalogue's class.")
    lamps: int | None = Field(default=None, ge=1, le=9, description="Hsi 2, Hsi 4 …")
    facing: Literal["east", "west"] | None = Field(
        default=None, description="The way it applies: trains going east or west."
    )
    at: Point
    piece: Id | None = Field(default=None, description="The track it stands by.")
    name: Text | None = Field(default=None, max_length=20)
    address: int | None = Field(default=None, ge=0, le=65535)
    label: Id | None = Field(default=None, description="The label it was named by.")
    shape: Text | None = Field(
        default=None, max_length=40, description="What it looks like: signalfigur, ▲, ● …"
    )
    origin: GraphOrigin | None = None


class TrackGraph(Contract):
    """Spårgraf: what CAD sends to Studio (CAD-10). Ids are never changed when the module is
    redrawn, and never used again for something else (CAD-20). geometry is "mm" for a module's
    real geometry; a drawing read by the photo chain for Studio gives "schema" (bildkedjan, 21),
    in the drawing's own coordinates with y down, with its labels and its symbols, and line exits
    and buffer stops at the tracks' ends. The same format goes both ways to Studio.
    complete is false while the tracks between the gables are unknown: a module from measures
    whose gables differ waits for its photo or its drawing."""

    geometry: Literal["mm", "schema"] = "mm"
    nodes: list[GraphNode] = Field(default_factory=list)
    pieces: list[GraphPiece] = Field(default_factory=list)
    switches: list[GraphSwitch] = Field(default_factory=list)
    labels: list[GraphLabel] = Field(default_factory=list)
    symbols: list[GraphSymbol] = Field(
        default_factory=list, description="Symbols read from a drawing (bildkedjan R3, 21)."
    )
    complete: bool = True
    issued: int = Field(default=0, ge=0, description="Ids issued so far; the next is one more.")

    @model_validator(mode="after")
    def _linked(self) -> Self:
        node_ids = [n.id for n in self.nodes]
        piece_ids = [p.id for p in self.pieces]
        ids = (
            node_ids
            + piece_ids
            + [s.id for s in self.switches]
            + [x.id for x in self.labels]
            + [x.id for x in self.symbols]
        )
        if len(ids) != len(set(ids)):
            raise ValueError("Två delar av spårgrafen har samma id.")
        for kind in {n.type for n in self.nodes}:
            if self.geometry == "mm" and kind not in CAD_NODE_TYPES:
                raise ValueError(f"En modul har inga noder av typen {kind.value}.")
            if self.geometry == "schema" and kind not in SCHEMA_NODE_TYPES:
                raise ValueError(f"En ritning har inga noder av typen {kind.value}.")
        for symbol in self.symbols:
            if symbol.piece is not None and symbol.piece not in piece_ids:
                raise ValueError(f"Symbolen {symbol.id} står vid ett spår som inte finns.")
        nodes = {n.id: n for n in self.nodes}
        for piece in self.pieces:
            ends = ((piece.start, piece.segments[0].start), (piece.end, piece.segments[-1].end))
            for end, at in ends:
                node = nodes.get(end)
                if node is None:
                    raise ValueError(f"Spårbiten {piece.id} går till en nod som inte finns.")
                if math.dist(node.at, at) > 0.5:
                    raise ValueError(f"Spårbiten {piece.id} slutar inte i noden {end}.")
        pieces = set(piece_ids)
        for switch in self.switches:
            if switch.node not in nodes:
                raise ValueError(f"Växeln {switch.id} står i en nod som inte finns.")
            for leg in (switch.trunk, switch.straight, switch.diverging):
                if leg is not None and leg not in pieces:
                    raise ValueError(f"Växeln {switch.id} har ett ben som inte finns.")
        return self


# --- The drawing (part b): Ritningen and Lås mått (CAD-03, CAD-20, CAD-24) ---------------


class ScaleLimits(Contract):
    """What the code holds a drawing in a scale to (cad/switches.py says where each comes from):
    the track's minimum radius and the kink check, the switches' lower limit, and the gauge."""

    scale: Scale
    gauge: float = Field(gt=0, description="Spårvidd, mm.")
    min_radius: float = Field(gt=0, description="Minsta radie för spår, mm.")
    switch_min_radius: float = Field(gt=0, description="Växelns nedre gräns för radien, mm.")
    kink: float = Field(gt=0, description="Största vinkelhopp på 10 mm innan det är en knyck, °.")
    gable_tolerance: float = Field(
        gt=0, description="Hur långt ett gavelspår får ligga från gavelns mått innan det visas, mm."
    )
    design_tolerance: float = Field(
        gt=0, description="How far a switch's radius may lie from a type's, as a fraction."
    )


class SwitchDesign(Contract):
    """Växeltyp: a known switch in the switch library, with the diverging leg's radius and angle,
    and where the numbers come from (bildkedjan step 12). Okänd has neither."""

    id: SwitchDesignId
    name: Text = Field(max_length=40)
    scale: Scale | None = Field(default=None, description="Null: every scale (Okänd).")
    radius: float | None = Field(default=None, gt=0)
    angle: float | None = Field(default=None, gt=0, lt=90)
    source: Text | None = Field(default=None, description="Where the radius and angle come from.")


UNKNOWN_DESIGN: Final = "okand"
"""Okänd: the switch type is not known; the radius is what was drawn or measured."""


class Smoothing(StrEnum):
    """Utjämning: how a drawn or traced line becomes LINE and ARC (bildkedjan step 12)."""

    OFF = "off"
    """Av: the line stays as drawn, straight pieces between its points."""
    LIGHT = "light"
    """Lätt."""
    NORMAL = "normal"
    """Normal: minsta radie 400 mm och högst 9 mm från linjen, in H0."""
    STRONG = "strong"
    """Kraftig."""


class SmoothingLevel(Contract):
    """One level of utjämning in a scale: the smallest radius it draws and how far the result
    may lie from the line, and the explanation the view shows."""

    level: Smoothing
    name: Text = Field(max_length=20)
    min_radius: float | None = Field(default=None, gt=0)
    max_deviation: float | None = Field(default=None, gt=0)
    text: Text


class Deviation(Contract):
    """How far one line lies from another: the median and the largest distance, in mm, over
    count points."""

    median: float = Field(ge=0)
    max: float = Field(ge=0)
    count: int = Field(ge=0)


class CheckKind(StrEnum):
    """Att kolla: what the code found, or (part c) what AI asks."""

    SHORT_RAIL = "short_rail"
    """A rail ends short of a gable, more than a few mm, with no joint there."""
    OPEN_END = "open_end"
    """A track end that meets nothing: not joined, not a buffer stop, not at a gable."""
    SWITCH_RADIUS = "switch_radius"
    """A switch's radius at or below the scale's lower limit."""
    SWITCH_ASSUMED = "switch_assumed"
    """A switch whose radius matches no switch type: antagen (AR3)."""
    KINK = "kink"
    """An angle jump on 10 mm larger than the minimum radius gives (the AnyRail kink check)."""
    TIGHT_RADIUS = "tight_radius"
    """A radius over 50 mm under the scale's minimum radius."""
    GABLE_POSITION = "gable_position"
    """A gable track that does not meet its gable's measure or profile."""
    QUESTION = "question"
    """A question with fixed answers from the photo chain's AI (part c)."""


class CheckSource(StrEnum):
    CODE = "code"
    """The code measured it."""
    AI = "ai"
    """AI asks it (part c); never millimetres, only fixed answers."""


class CheckChoice(Contract):
    """An answer button. closes: the answer settles the item; action: what the view does
    instead, with no answer stored (choose a switch type, open Lås mått, or answer the photo's
    question in Osäkert parti)."""

    id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]
    text: Text = Field(max_length=60)
    closes: bool = True
    action: Literal["design", "lock", "photo"] | None = None


class CheckAnswer(Contract):
    """Ägarens svar på en sak att kolla: kept with the version, by the item's key."""

    key: Text = Field(max_length=120)
    answer: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]
    by: Text | None = Field(default=None, max_length=80)


class CheckItem(Contract):
    """Att kolla: one thing the owner answers before the track plan is approved. The key names
    the kind, the parts and the measured value, so a changed value asks again."""

    key: Text = Field(max_length=120)
    kind: CheckKind
    source: CheckSource = CheckSource.CODE
    at: Point = Field(description="The place in mm, in the module's coordinates.")
    title: Text
    text: Text
    refs: list[Id] = Field(default_factory=list, description="The nodes, pieces and switches.")
    choices: list[CheckChoice] = Field(min_length=1)
    answer: CheckAnswer | None = None
    assumed: bool = Field(
        default=False, description="Antagen (AR3): yellow; otherwise orange, as a proposal."
    )


class DrawingSource(StrEnum):
    """Where the track plan comes from: the badge in Ritningen."""

    MEASURES = "measures"
    """Ur måtten (CAD-01)."""
    DRAWN = "drawn"
    """Ritad: drawn or changed in Ritningen."""
    PHOTO = "photo"
    """AI-förslag from the photo (part c)."""
    SKETCH = "sketch"
    """Förslag from a hand-drawn sketch, ± 20 mm (part c2)."""


class DrawnLine(Contract):
    """The line a piece was drawn from, by hand (or, in part c, traced in the photo or the
    sketch): utjämning makes it LINE and ARC again when its level changes, and the deviation is
    measured from it."""

    piece: Id
    points: list[Point] = Field(min_length=2, max_length=4000)
    source: Literal["hand", "photo", "sketch"] = "hand"


class IdChange(Contract):
    """A piece split or replaced (CAD-20): Lås mått, a switch or a cut. The first new id is the
    first old one, so Studio follows the owner's additions (signals, boundaries) along."""

    old: list[Id] = Field(min_length=1)
    new: list[Id] = Field(min_length=1)
    why: Literal["lock", "switch", "cut", "switch_removed"]


class LockedMeasure(Contract):
    """Låst mått: a gable track's position from Kant 1, locked by the owner (CAD-24)."""

    gable: GableEnd
    track: int = Field(ge=1, le=MAX_TRACKS)
    value: float = Field(gt=0)
    line: float | None = Field(default=None, description="What the line said before, mm.")


class DrawingState(Contract):
    """What a version keeps of its drawing besides the graph: where it came from, the
    utjämning, the owner's answers, the drawn lines, the locked measures, and the ids this
    version split or replaced."""

    source: DrawingSource = DrawingSource.MEASURES
    smoothing: Smoothing = Smoothing.NORMAL
    answers: list[CheckAnswer] = Field(default_factory=list)
    lines: list[DrawnLine] = Field(default_factory=list)
    locks: list[LockedMeasure] = Field(default_factory=list)
    ids: list[IdChange] = Field(default_factory=list, description="This version's splits.")
    plan_approved: bool = Field(default=False, description="Godkänn spårplanen gave this one.")
    questions: list[CheckItem] = Field(
        default_factory=list,
        description="The photo chain's questions (part c1): Att kolla items of the kind question, "
        "source code or ai, kept with the version.",
    )
    photo: UUID | None = Field(
        default=None, description="The photo job the drawing came from (part c1)."
    )


# The editing operations (Ritningen). A change set is a list of them, applied in order on the
# version it builds on; each is checked, and the graph is validated after each (CAD-20: what is
# moved, reshaped or recomputed keeps its id, only new things get new ids).


class AddLine(Contract):
    """Rakt spår: a LINE from start to end. start_node and end_node join it to an end there;
    a point on a gable becomes a module joint."""

    op: Literal["line"] = "line"
    start: Point
    end: Point
    start_node: Id | None = None
    end_node: Id | None = None


class AddArc(Contract):
    """Båge: an ARC from start, by radius and angle (turning right for a positive angle, as
    seen along the track with y down) from the heading at start, or through three points."""

    op: Literal["arc"] = "arc"
    start: Point
    start_node: Id | None = None
    end: Point | None = None
    end_node: Id | None = None
    through: Point | None = None
    radius: Mm | None = None
    angle: float | None = Field(default=None, ge=-359, le=359, description="Degrees.")
    heading: float | None = Field(
        default=None, description="Degrees, 0 toward gable B, positive down; null: the track's."
    )

    @model_validator(mode="after")
    def _one_way(self) -> Self:
        three = self.through is not None and self.end is not None
        turned = self.radius is not None and self.angle is not None
        if three == turned:
            raise ValueError("En båge ges av tre punkter, eller av radie och vinkel.")
        return self


class AddPolyline(Contract):
    """A hand-drawn line: utjämning makes it LINE and ARC at the version's level."""

    op: Literal["polyline"] = "polyline"
    points: list[Point] = Field(min_length=2, max_length=4000)
    start_node: Id | None = None
    end_node: Id | None = None


class AddSwitch(Contract):
    """Växel: the diverging leg leaves the piece's track tangentially at from_a mm from gable A,
    with its radius. Either with its angle, to the left or right as seen toward the gable it
    heads for, or drawn to a point: an arc of the radius and then straight to to, which also
    gives the side and the gable it heads for (a track drawn from the middle of another)."""

    op: Literal["switch"] = "switch"
    piece: Id
    from_a: float = Field(ge=0, description="Tungspetsen, mm från gavel A.")
    radius: Mm
    angle: float | None = Field(default=None, gt=0, lt=90)
    side: Literal["left", "right"] | None = None
    toward: GableEnd = GableEnd.B
    design: SwitchDesignId | None = None
    tail: float = Field(default=0, ge=0, le=20_000, description="Straight after the arc, mm.")
    to: Point | None = Field(default=None, description="Where the diverging leg ends.")
    to_node: Id | None = None

    @model_validator(mode="after")
    def _leg(self) -> Self:
        if self.to is None and (self.angle is None or self.side is None):
            raise ValueError("En växel ges av vinkel och sida, eller av vart benet går.")
        return self


class MoveSwitch(Contract):
    """Flytta växel: the points slide along their track; the legs follow."""

    op: Literal["move_switch"] = "move_switch"
    switch: Id
    from_a: float = Field(ge=0)


class Move(Contract):
    """Move a node, a piece, a switch or a label by a vector in mm. What hangs on it is
    reshaped, never replaced."""

    op: Literal["move"] = "move"
    target: Id
    by: Point


class Delete(Contract):
    """Delete a piece, a switch, an end or a label. The ids are never used again."""

    op: Literal["delete"] = "delete"
    target: Id


class Join(Contract):
    """Join two ends: both move to the middle and become one node."""

    op: Literal["join"] = "join"
    a: Id
    b: Id


class Cut(Contract):
    """Cut a piece in two at the point nearest at: the first part keeps the id."""

    op: Literal["cut"] = "cut"
    piece: Id
    at: Point


class SetLabel(Contract):
    """Text: a piece's track number, a switch's number, or a free label at a point. An empty
    text removes it."""

    op: Literal["label"] = "label"
    target: Id | None = None
    at: Point | None = None
    text: str = Field(default="", max_length=40)


class SetEnd(Contract):
    """Make a free end a buffer stop, or a plain end again."""

    op: Literal["end"] = "end"
    node: Id
    type: Literal["buffer_stop", "joint"]


class SetSwitch(Contract):
    """Växelinspektören: the diverging radius, the switch type ("okand" for Okänd), and Lås
    växelns läge."""

    op: Literal["set_switch"] = "set_switch"
    switch: Id
    radius: Mm | None = None
    design: SwitchDesignId | None = None
    locked: bool | None = None


class AnswerCheck(Contract):
    """Answer an item in Att kolla with one of its choices."""

    op: Literal["answer"] = "answer"
    key: Text = Field(max_length=120)
    answer: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]


class SetSmoothing(Contract):
    """Utjämning: the level, kept on the version; the drawn lines are made again at it."""

    op: Literal["smoothing"] = "smoothing"
    level: Smoothing


class LockRadii(StrEnum):
    SAME = "same"
    """Samma radie i båda bågarna."""
    DIFFERENT = "different"
    """Olika radier."""


class LockMeasures(Contract):
    """Lås mått (CAD-24): the track through piece, from gable A to gable B, gets its positions
    a and b from Kant 1 locked, and the curve between is made straight, arc, straight, arc,
    straight, fitted to the line it replaces. Null a or b: the gable's measure."""

    op: Literal["lock"] = "lock"
    piece: Id | None = Field(default=None, description="Null: the first track from A to B.")
    a: float | None = Field(default=None, gt=0)
    b: float | None = Field(default=None, gt=0)
    radii: LockRadii = LockRadii.SAME


EditOp = Annotated[
    AddLine
    | AddArc
    | AddPolyline
    | AddSwitch
    | MoveSwitch
    | Move
    | Delete
    | Join
    | Cut
    | SetLabel
    | SetEnd
    | SetSwitch
    | AnswerCheck
    | SetSmoothing
    | LockMeasures,
    Field(discriminator="op"),
]

MAX_OPERATIONS: Final = 2000


class DrawingEdit(Contract):
    """A change set: the operations on top of version base, the newest the person read. The
    view sends the whole list every time, so undo is one less and the result is always the
    same for the same list. Refused with 409 when a newer version exists."""

    base: int = Field(ge=1)
    operations: list[EditOp] = Field(default_factory=list, max_length=MAX_OPERATIONS)


class SwitchInfo(Contract):
    """Växelinspektören: one switch as the inspector shows it."""

    id: Id
    number: Text
    leaves: Text = Field(description='The track it leaves and toward which: "spår från A4 mot A3".')
    from_a: float = Field(description="Tungspetsen, mm från gavel A.")
    radius: float | None = None
    angle: float | None = None
    side: Literal["left", "right"] | None = None
    toward: GableEnd | None = None
    design: SwitchDesignId = Field(description='The chosen type, or "okand".')
    matched: SwitchDesignId | None = Field(
        default=None, description="The type its radius matches within the tolerance."
    )
    assumed: bool = Field(description="Antagen (AR3): Okänd and no type within the tolerance.")
    locked: bool
    at: Point
    origin: GraphOrigin | None = None


class DrawingStats(Contract):
    """The canvas's bottom line: Spår totalt, antal växlar, and how far the drawing lies from
    its drawn lines (part c: from the photo)."""

    track_length: float = Field(ge=0)
    switches: int = Field(ge=0)
    deviation: Deviation | None = None


class PhotoGrid(Contract):
    """Where a measuring image lies in the module's millimetres: pixel (0, 0)'s centre at
    (x0, y0) mm, ppm px per mm. A photo read with another Kant 1 or gable A than the owner
    chose afterwards keeps its image (part c2): matrix, SVG's (a, b, c, d, e, f), takes the mm
    it was measured in to the module's."""

    x0: float
    y0: float
    ppm: float = Field(gt=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    matrix: list[float] | None = Field(default=None, min_length=6, max_length=6)


class PhotoLayer(Contract):
    """Fotot under: the measuring image under the drawing, in the module's millimetres."""

    job: UUID
    url: str = Field(description="The measuring image at 1 px per mm, a signed address.")
    grid: PhotoGrid


class DrawingView(Contract):
    """Ritningen: the working drawing after a change set, with what to check and the
    inspector's facts. Nothing is saved until Spara."""

    module: UUID
    base: int = Field(ge=1)
    latest: int = Field(ge=1)
    scale: Scale
    shape: Shape
    gables: list[Gable] = Field(min_length=2, max_length=2)
    graph: TrackGraph
    drawing: DrawingState
    checks: list[CheckItem] = Field(default_factory=list)
    switches: list[SwitchInfo] = Field(default_factory=list)
    designs: list[SwitchDesign] = Field(default_factory=list)
    smoothing_levels: list[SmoothingLevel] = Field(default_factory=list)
    limits: ScaleLimits
    stats: DrawingStats
    changed: bool = Field(description="The operations changed something.")
    photo: PhotoLayer | None = Field(default=None, description="Fotot under (part c1).")


class LockAsk(DrawingEdit):
    """Lås mått, the preview: the change set so far and the lock to try."""

    lock: LockMeasures


class LockPart(Contract):
    """One row in Kurvan's table: Rakt från gavel A, Båge R, Rakt mm · vinkel, Båge R, Rakt
    till gavel B."""

    kind: Literal["straight", "arc"]
    label: Text
    length: float = Field(ge=0)
    radius: float | None = None
    angle: float = Field(description="Degrees: the straight's angle to gable A, or the arc's.")


class LockGable(Contract):
    """LÅSTA MÅTT: a gable track, the value locked and what the line said."""

    gable: GableEnd
    track: int = Field(ge=1, le=MAX_TRACKS)
    value: float
    line: float
    norm: Norm | None = None
    profile: Text | None = Field(default=None, description="The profile's name, when it fixes it.")


class LockProposal(Contract):
    """Lås ett mått, räkna om kurvan: the new geometry beside the old line, or why there is
    none. Använd geometrin saves it (the operation lock); Behåll linjen keeps the old."""

    solved: bool
    why: Text = Field(description="The sentence under LÅSTA MÅTT, or why there is no solution.")
    radii: LockRadii
    gables: list[LockGable] = Field(default_factory=list)
    parts: list[LockPart] = Field(default_factory=list)
    old: list[Point] = Field(default_factory=list, description="The line it replaces.")
    new: list[Segment] = Field(default_factory=list)
    tangents: list[Point] = Field(default_factory=list, description="The tangent points.")
    deviation: Deviation | None = None
    lock: LockMeasures


class SmoothAsk(Contract):
    """Utjämning of one line, to see what a level does."""

    points: list[Point] = Field(min_length=2, max_length=4000)
    level: Smoothing = Smoothing.NORMAL
    scale: Scale = Scale.H0


class SmoothResult(Contract):
    level: Smoothing
    segments: list[Segment]
    deviation: Deviation


# --- The module ---------------------------------------------------------------------------


class Visibility(StrEnum):
    """Vem ser modulen (CAD-05): bara jag, min klubb, alla i TrainMeet."""

    ME = "me"
    CLUB = "club"
    ALL = "all"


class ModuleStatus(StrEnum):
    DRAFT = "draft"
    """Utkast: the newest version is not approved."""
    APPROVED = "approved"
    """Godkänd: the owner approved the newest version."""


class UsedIn(Contract):
    """Används i: an assembly or a meet that uses the module, at the version it pinned (part d);
    or a station in TKL that took the module into use, alone or in an assembly (CAD-15)."""

    kind: Literal["assembly", "meet", "station"]
    id: UUID = Field(description="The assembly or meet; for a station, what it took.")
    name: Text
    version: int = Field(ge=1)
    station: Id | None = Field(default=None, description="The station's id in TKL.")


class ModuleBrief(Contract):
    """A module as the library lists it."""

    id: UUID
    number: str = Field(pattern=r"^M-\d{3,}$", description="M-001, per owner.")
    name: Name
    owner: Owner
    visibility: Visibility
    scale: Scale
    shape: Shape
    gables: list[GableLabel] = Field(min_length=2, max_length=2)
    graph: TrackGraph
    status: ModuleStatus
    version: int = Field(ge=1)
    photographed: bool = Field(
        default=False, description="Verifierad mot foto (part c). Dashed track until then."
    )
    track_length: float = Field(ge=0, description="The track pieces' length, in mm.")
    changed_at: datetime


class ModulePhoto(Contract):
    """The Foto tab (part c1): the measuring image the version came from, and what is kept."""

    job: UUID
    measure_url: str = Field(description="The measuring image, 2 px per mm, a signed address.")
    display_url: str = Field(description="The measuring image, 1 px per mm.")
    grid: PhotoGrid
    chain: Text = Field(description="The chain's version that read it.")
    newer_chain: bool = Field(description="A newer version of the chain can read it again.")
    original_until: datetime | None = Field(
        default=None, description="When the original goes, unless it is kept (CAD4)."
    )
    original_kept: bool = Field(description="The original is kept: Spara original.")
    taken_at: datetime


class Module(ModuleBrief):
    """Modul: one version of it, with its page's facts (CAD-05)."""

    club: UUID | None = Field(
        default=None, description="The club that sees it with the visibility klubben."
    )
    club_name: Text | None = None
    approved_version: int | None = Field(default=None, ge=1)
    approved_at: datetime | None = None
    approved_by: Text | None = None
    created_at: datetime
    used_in: list[UsedIn] = Field(default_factory=list)
    may_edit: bool = Field(description="The person may change it (CAD-21).")
    latest: int = Field(ge=1, description="The newest version; version is the one shown.")
    drawing: DrawingState = Field(default_factory=DrawingState)
    checks: list[CheckItem] = Field(
        default_factory=list, description="Att kolla in this version, answered or not."
    )
    photo: ModulePhoto | None = Field(default=None, description="The Foto tab (part c1).")
    keep_original: bool = Field(
        default=False, description="Spara original: the photo's original is kept (CAD4)."
    )
    training_at: datetime | None = Field(
        default=None,
        description="When the owner said yes to training TrainMeet's track model on it (CAD7, "
        "CAD-32); null: no.",
    )


class Library(Contract):
    """Ett modulbibliotek: the person's own, a club's, or everything the person sees."""

    id: Annotated[str, StringConstraints(pattern=r"^(mine|all|club:[0-9a-f-]{36})$")]
    name: Text
    kind: Literal["mine", "club", "all"]
    club: UUID | None = None
    may_add: bool = Field(description="New modules can be added here.")


class ModuleList(Contract):
    library: Library
    modules: list[ModuleBrief]
    gables: list[GableCount] = Field(description="Gavlar i biblioteket, most first.")


class _ModuleFields(Contract):
    name: Name
    scale: Scale
    shape: Shape
    gables: list[Gable] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def _gables(self) -> Self:
        if [g.end for g in self.gables] != [GableEnd.A, GableEnd.B]:
            raise ValueError("En modul har gavel A och gavel B, i den ordningen.")
        for gable in self.gables:
            if gable.norm is not None and gable.norm not in NORMS[self.scale]:
                raise ValueError(
                    f"Normen {NORM_NAMES[gable.norm]} finns inte i skala {self.scale}."
                )
        return self


class NewModule(_ModuleFields):
    """Ny modul, bara mått (CAD-01). owner a club's id makes it the club's: the club's
    administrator may. club is the club that sees it with the visibility klubben."""

    owner: UUID | None = None
    visibility: Visibility = Visibility.ME
    club: UUID | None = None


class ModuleChange(_ModuleFields):
    """Spara: a new version on top of base, the newest the person read. Refused with 409 when a
    newer version exists."""

    base: int = Field(ge=1)


class ModuleApproval(Contract):
    """Godkänn: the person approves the newest version."""

    version: int = Field(ge=1)


class VisibilityChange(Contract):
    visibility: Visibility
    club: UUID | None = None


class ModuleEventKind(StrEnum):
    CREATED = "created"
    SAVED = "saved"
    APPROVED = "approved"
    VISIBILITY = "visibility"
    REMOVED = "removed"
    PHOTO = "photo"
    """A photo read, or its settings changed (part c1)."""


class ModuleEvent(Contract):
    """Historik: one thing that happened to the module."""

    at: datetime
    kind: ModuleEventKind
    version: int = Field(ge=1)
    by: Text = Field(description="The person's name.")
    text: Text = Field(description="What happened, in Swedish.")


class ModuleRemoved(Contract):
    id: UUID


# --- The photo chain, profiles Modulfoto and Skiss (parts c1 and c2) -------------------------
#
#     GET    /api/cad/1/photos/consent?module=                 PhotoConsent
#     POST   /api/cad/1/photos                                 form: data PhotoStart, images
#                                                              1–4 photos, or one sketch
#                                                              -> PhotoJob, 201
#     GET    /api/cad/1/photos/{job}                           PhotoJob
#     POST   /api/cad/1/photos/{job}/read                      PhotoRead -> PhotoJob
#     POST   /api/cad/1/photos/{job}/orientation               PhotoOrientation -> PhotoJob:
#                                                              another Kant 1 or gable A after
#                                                              reading, at no cost (part c2)
#     POST   /api/cad/1/photos/{job}/answers                   PhotoAnswers -> PhotoJob
#     POST   /api/cad/1/photos/{job}/questions/{key}/closeup   form: data PhotoCloseup, images
#                                                              one photo -> PhotoJob
#     POST   /api/cad/1/photos/{job}/recompute                 PhotoJob: Räkna om
#     PUT    /api/cad/1/modules/{module}/photo                 PhotoSettings -> Module
#     GET    /api/cad/1/storage                                StorageUse
#
# Code measures; AI reads only which tracks connect, with fixed answers, never millimetres
# (CAD2). A measuring image read by AI costs 12 tokens, once, with its follow-up questions
# (CAD3, CAD-29); the same image again costs nothing, and the account's own AI costs nothing.
# Everything the photo gives is a proposal until the owner approves (CAD-17).

MAX_PHOTOS: Final = 4
"""Photos of one module: 2–4 for a long one (bildkedjan step 7)."""


class PhotoJobState(StrEnum):
    CORNERS = "corners"
    """The photo is taken in: the owner confirms the corners and Kant 1, and starts."""
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    """Read: the track plan is a new version of the module, with its questions."""
    FAILED = "failed"


class PhotoLevel(StrEnum):
    OK = "ok"
    LOW = "low"
    """Låg upplösning: the tolerances are widened."""
    WARN = "warn"
    REFUSE = "refuse"
    """A new photo is needed."""


class PhotoGate(Contract):
    """One row of the quality gate (bildkedjan step 3)."""

    key: Literal["resolution", "tilt", "sharpness", "clipped", "corners", "stitch", "curve"]
    level: PhotoLevel
    value: float
    text: Text


class PhotoQuality(Contract):
    px_per_mm: float = Field(ge=0)
    tilt: float = Field(ge=0, description="Degrees from straight down.")
    gates: list[PhotoGate]
    length_from_photo: bool = Field(description="False under 1 px per mm: no length from it.")


class PhotoCorners(Contract):
    """The module's corners in the preview's pixels (the photo, or the photos stitched, made
    smaller), clockwise as seen, the side that is Kant 1 and the side that is gable A: side i
    runs from corner i to corner i + 1. Gable A is one of the two sides beside Kant 1: the one
    before it is the module as CAD draws it seen from above (from gable A along Kant 1 the
    module lies to the right); the one after it is the module mirrored (part c2)."""

    corners: list[Point] = Field(min_length=4, max_length=4)
    kant1: int = Field(ge=0, le=3)
    gable_a: int | None = Field(
        default=None, ge=0, le=3, description="Null: the side before Kant 1 (part c1)."
    )
    found: bool = Field(description="Code found them; false: a guess to drag into place.")
    certain: bool = Field(description="Every side's edge fits its line within 2 px.")
    derived: bool = Field(
        default=False,
        description="Kant 1 and gable A derived from the gables' tracks and the module's known "
        "gables (an asymmetric profile), shown for the owner to confirm.",
    )
    why: Text | None = Field(
        default=None, description="Why they were derived, or why the owner must tap them."
    )


class PhotoFrame(Contract):
    """A module's frame on a sketch (profile Skiss): its four corners in the preview's pixels,
    clockwise, and the long side the chain takes as Kant 1."""

    corners: list[Point] = Field(min_length=4, max_length=4)
    kant1: int = Field(ge=0, le=3)


class FactSource(StrEnum):
    """Where a fact comes from (bildkedjan, principle 4)."""

    PHOTO = "photo"
    OWNER = "owner"
    NORM = "norm"
    AI = "ai"
    CODE = "code"
    SKETCH = "sketch"
    """Read from a hand-drawn sketch: ± 20 mm until the owner measures (part c2)."""


class PhotoFact(Contract):
    """A fact with its origin and certainty: säker, trolig, osäker or bekräftad, and its ±."""

    key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.:-]{0,59}$")]
    label: Text
    value: float | None = None
    text: Text | None = None
    plus_minus: float | None = Field(default=None, ge=0)
    source: FactSource
    certainty: Certainty


class PhotoMeasure(Contract):
    """Dina mått mot fotot: the owner's measure, or the norm's, against the photo's."""

    key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.:-]{0,59}$")]
    label: Text
    owner: float | None = Field(default=None, description="The owner's or the norm's; null: none.")
    owner_source: FactSource | None = None
    photo: float
    plus_minus: float = Field(ge=0)
    agrees: bool
    gable: GableEnd | None = None
    track: int | None = Field(default=None, ge=1, le=MAX_TRACKS)


class PhotoChoice(Contract):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]
    text: Text = Field(max_length=60)
    hint: Text | None = Field(default=None, description="What it means, under the choice.")
    sketch: (
        Literal["two_switches", "crossing", "single_slip", "double_slip", "joined", "apart"] | None
    ) = None


class PhotoQuestionKind(StrEnum):
    CONNECTION = "connection"
    """Do these two ends connect? Code and AI said differently, or there was no AI."""
    NODE = "node"
    """Korsning, enkel eller dubbel korsningsväxel, eller två växlar? (Osäkert parti)"""
    HIDDEN = "hidden"
    """Spår dolt: the track is hidden over more than 30 mm."""
    SCALE = "scale"
    """The owner's measure and the gauge differ more than 1 %."""
    GAUGE = "gauge"
    """The gauge along a stretch differs more than 5 %: something else was followed."""
    SWITCH_FIT = "switch_fit"
    """The switch's fit lies more than 1 mm from the photo."""
    SLEEPERS = "sleepers"
    """The sleepers' spacing differs on straight and slanting tracks."""
    CURVE = "curve"
    """A curve module's edges are no circular arcs once straightened: the corners or the
    chord and sagitta are wrong (part c2)."""
    ORIENTATION = "orientation"
    """The gables' tracks show the module the other way round than Kant 1 and gable A say."""


class PhotoQuestion(Contract):
    """A question from the chain (bildkedjan step 15, När AI ska fråga): a fixed set of answers,
    what code and AI each say, and the owner's answer. A topology question changes the track
    plan; it stops Godkänn spårplanen until it is answered."""

    key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.:-]{0,79}$")]
    kind: PhotoQuestionKind
    source: CheckSource
    title: Text
    text: Text = Field(description="What the AI or the code sees.")
    choices: list[PhotoChoice] = Field(min_length=1)
    code: str | None = Field(default=None, description="The choice the code makes.")
    ai: str | None = Field(default=None, description="The choice the AI makes.")
    answer: str | None = Field(default=None, description="The owner's.")
    at: Point = Field(description="The place in mm, in the module's coordinates.")
    topology: bool = Field(description="The answer changes the track plan.")
    closeup: bool = Field(default=False, description="Ta en närbild helps here.")
    closeup_ai: str | None = Field(default=None, description="What the AI says from the close-up.")


class PhotoPrice(Contract):
    """The price before start (CAD-18, CAD-29): 12 tokens per measuring image read by AI."""

    tokens: int = Field(ge=0)
    why: Literal["first", "included", "same", "own_ai", "no_ai"]
    text: Text


class PhotoConsent(Contract):
    """What is sent and to whom, before a photo is first sent to AI, as Catalog's (CAT-142)."""

    available: bool = Field(description="AI can be used here: ID's meter answers.")
    given: bool
    version: Text
    sent_to: Text
    text: Text
    own_ai: Text | None = None
    price: int = Field(ge=0)
    balance: int | None = None
    payer: Text | None = None
    message: Text | None = Field(default=None, description="Why AI cannot be used now.")
    may_read: bool = Field(
        default=True,
        description="Only the owner reads with AI, and a club's administrators for its modules.",
    )


class PhotoImage(Contract):
    id: UUID
    url: str
    width: int
    height: int


class PhotoSummary(Contract):
    """Spårplanen: what the chain read."""

    tracks_a: int = Field(ge=0)
    tracks_b: int = Field(ge=0)
    switches: int = Field(ge=0)
    crossings: int = Field(ge=0)
    ends: int = Field(ge=0)
    track_length: float = Field(ge=0)
    deviation: Deviation | None = None


class SleeperCheck(Contract):
    """The sleepers' spacing on straight and slanting tracks: the same, or the straightening
    is wrong (bildkedjan step 9)."""

    straight: float | None = None
    slanting: float | None = None
    slanting_angle: float | None = None
    agree: bool | None = None


class GaugeCheck(Contract):
    """The gauge averaged over the straight stretches, against the scale's (step 9)."""

    value: float | None = None
    nominal: float
    places: int = Field(ge=0)
    agrees: bool | None = None


class PhotoJob(Contract):
    """One run of the chain on a module's photos: its state and what it found. The same photos,
    input and versions give the same job, at no cost (bildkedjan, Reproducerbarhet)."""

    id: UUID
    module: UUID
    profile: Literal["modulfoto", "skiss"] = Field(
        default="modulfoto", description="A photo of the module, or a sketch (part c2)."
    )
    state: PhotoJobState
    progress: int = Field(ge=0, le=100)
    step: Text = Field(description="What it does now, in Swedish.")
    created_at: datetime
    photos: list[PhotoImage] = Field(description="The photos as taken in, while they are kept.")
    preview: PhotoImage | None = Field(
        default=None, description="The photos as one, for the corners."
    )
    corners: PhotoCorners | None = None
    frames: list[PhotoFrame] = Field(
        default_factory=list, description="A sketch's module frames; corners is the chosen one."
    )
    frame: int | None = Field(default=None, ge=0, description="The sketch's frame read.")
    quality: PhotoQuality | None = None
    length: float | None = None
    length_plus_minus: float | None = None
    length_given: bool = Field(description="The owner gave the length; false: the photo's.")
    offset: float | None = None
    measure: PhotoLayer | None = None
    tracks_on_photo: list[list[Point]] = Field(
        default_factory=list, description="The track plan drawn on the preview, in its px."
    )
    facts: list[PhotoFact] = Field(default_factory=list)
    measures: list[PhotoMeasure] = Field(default_factory=list)
    questions: list[PhotoQuestion] = Field(default_factory=list)
    summary: PhotoSummary | None = None
    sleepers: SleeperCheck | None = None
    gauge: GaugeCheck | None = None
    price: PhotoPrice
    cost: int = Field(ge=0, description="Tokens drawn for this job.")
    ai: Text | None = Field(default=None, description="The AI that read it, or null.")
    version: int | None = Field(default=None, ge=1, description="The module version it made.")
    chain: Text
    key: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    message: Text | None = Field(default=None, description="Why it stopped, in Swedish.")


class PhotoStart(Contract):
    """The form's data part: a new module from the photo, or a photo for a module. A curve
    module comes with the chord and sagitta measured on track 1, and track 1's distance from
    Kant 1 at gable A (part c2, bildkedjan step 6). A sketch (profile skiss) needs the module's
    length: its frame gives the sketch its scale."""

    module: UUID | None = None
    profile: Literal["modulfoto", "skiss"] = "modulfoto"
    name: Name | None = None
    scale: Scale = Scale.H0
    kind: Literal["straight", "trapezoid", "curve"] = "straight"
    width: Mm | None = Field(default=None, description="Gable A's width; null: the module's.")
    width_b: Mm | None = None
    length: Mm | None = Field(default=None, description="Null: the photo gives it.")
    offset: float | None = Field(default=None, ge=-20_000, le=20_000)
    chord: Mm | None = Field(default=None, description="A curve's chord on track 1.")
    sagitta: Mm | None = Field(default=None, description="A curve's sagitta on track 1.")
    track1: Mm | None = Field(default=None, description="Track 1 from Kant 1 at gable A.")
    edge: EdgeSide = EdgeSide.OUTER
    keep_original: bool = False
    owner: UUID | None = None


class PhotoRead(Contract):
    """Läs av: the corners, Kant 1 and gable A as the owner confirmed them, in the preview's
    pixels, with or without AI; on a sketch, the frame that is this module."""

    corners: list[Point] = Field(min_length=4, max_length=4)
    kant1: int = Field(ge=0, le=3)
    gable_a: int | None = Field(default=None, ge=0, le=3, description="Null: before Kant 1.")
    frame: int | None = Field(default=None, ge=0)
    ai: bool = True
    consent: bool = False


class PhotoOrientation(Contract):
    """Another Kant 1 or gable A for a photo already read: the same measuring, mirrored or
    turned, at no cost (part c2)."""

    kant1: int = Field(ge=0, le=3)
    gable_a: int = Field(ge=0, le=3)


class PhotoAnswer(Contract):
    key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.:-]{0,79}$")]
    answer: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]


class PhotoAnswers(Contract):
    answers: list[PhotoAnswer] = Field(min_length=1, max_length=50)


class PhotoCloseup(Contract):
    consent: bool = False


class PhotoSettings(Contract):
    """Spara original and the training opt-in (CAD4, CAD7)."""

    keep_original: bool | None = None
    training: bool | None = None


class StorageUse(Contract):
    """CAD's own storage for module photos, 100 MB per person (CAD-19); the originals waiting
    for approval do not count (CAD4)."""

    used: int = Field(ge=0)
    limit: int = Field(ge=0)
    waiting: int = Field(ge=0, description="Originals kept until approval, not counted.")


# --- Ladda upp ritning: the profile Stationsritning (part c4, CAD6, CAD-31) ---------------
#
# Studio's Ladda upp ritning sends a signal plan, a panel drawing or a track plan here and gets
# a ritningsavläsning back (bildkedjan, Stationsritning R1–R4). The chain never makes a station:
# Studio turns the read into its station model by the standard interlocking, everything a
# proposal until the owner confirms it (TKL23, TKL27). TKL calls on the person's behalf with
# the person's own access token from TrainMeet ID (TKL18), as Authorization: Bearer; a browser
# logged in to CAD may call the same addresses with its session.
#
#     POST   /api/cad/1/drawings                    form: data DrawingStart, file one PDF, SVG,
#                                                   JPEG, PNG or WebP -> DrawingJob, 201; the
#                                                   same file again is the same job
#     GET    /api/cad/1/drawings/{job}              DrawingJob
#     POST   /api/cad/1/drawings/{job}/read         DrawingReadAsk -> DrawingJob
#     POST   /api/cad/1/drawings/{job}/answers      DrawingAnswers -> DrawingJob
#     GET    /api/cad/1/drawings/{job}/underlay     the straightened drawing, image/png or jpeg
#
# R1: a page with drawn lines and a text layer is read by code, free (as the import's known
# formats). R2: a raster page (an image, a scanned PDF, a photo of paper) is straightened, its
# lines found by code and its text transcribed by AI: 12 tokens a page through ID's meter, or
# nothing with the account's own AI or without AI. The same page again costs nothing.

MAX_DRAWING_PAGES: Final = 20
"""The most pages of a PDF taken in; one page is read at a time."""


class DrawingJobState(StrEnum):
    WAITING = "waiting"
    """Taken in: the pages and the price are shown, and the owner starts."""
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class DrawingPageKind(StrEnum):
    VECTOR = "vector"
    """Drawn lines and a text layer: read by code (R1)."""
    RASTER = "raster"
    """Pixels: straightened, lines by code, text by AI (R2)."""


class DrawingPage(Contract):
    number: int = Field(ge=1, le=MAX_DRAWING_PAGES)
    kind: DrawingPageKind
    width: float = Field(gt=0, description="In the page's own units: pt, or px for pixels.")
    height: float = Field(gt=0)
    text: bool = Field(description="The page has a text layer that code reads.")
    tokens: int = Field(ge=0, description="What reading it with TrainMeets AI costs.")


class DrawingPrice(Contract):
    """The price before start (CAD-29, bildkedjan Pris): a vector page is free, a raster page
    12 tokens when TrainMeets AI transcribes its text."""

    tokens: int = Field(ge=0)
    why: Literal["vector", "first", "same", "own_ai", "no_ai"]
    text: Text


class DrawingAi(Contract):
    """Whether AI can transcribe a raster page here, what is sent and to whom, and the yes
    (as the photo's, CAT-142)."""

    available: bool
    given: bool
    version: Text
    sent_to: Text
    text: Text
    balance: int | None = None
    message: Text | None = Field(default=None, description="Why AI cannot be used now.")


class DrawingQuestionKind(StrEnum):
    LEGEND = "legend"
    """Teckenförklaringen: what a colour of line, or a symbol type, means in this drawing."""
    END = "end"
    """A track's end: a buffer stop or a line exit."""


class DrawingChoice(Contract):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]
    text: Text = Field(max_length=60)


class DrawingQuestion(Contract):
    """A question from the drawing's read: one per colour of line or symbol type that code
    cannot place (R3: "Vad betyder ▲ i den här ritningen?"), the legend's first. The code's
    choice stands until the owner answers; the answer changes the read without reading again,
    at no cost."""

    key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.:-]{0,79}$")]
    kind: DrawingQuestionKind
    title: Text
    text: Text
    choices: list[DrawingChoice] = Field(min_length=1)
    code: str | None = Field(default=None, description="The choice the code makes.")
    answer: str | None = Field(default=None, description="The owner's.")
    sample: Text | None = Field(default=None, max_length=40, description="▲, ●, a colour …")
    count: int = Field(ge=0, description="How many there are in the drawing.")
    at: Point | None = Field(default=None, description="One of them, in the drawing.")


class DrawingAnswer(Contract):
    key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.:-]{0,79}$")]
    answer: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]


class DrawingAnswers(Contract):
    answers: list[DrawingAnswer] = Field(min_length=1, max_length=50)


class DrawingBoundary(Contract):
    """Spårledningsgräns where the drawing shows one: a stroke across a track."""

    id: Id
    at: Point
    piece: Id | None = Field(default=None, description="The track it crosses.")
    origin: GraphOrigin


class DrawingUnderlay(Contract):
    """The straightened drawing, for Studio to show under Rita: the image, its size, and the
    affine transform from the drawing's coordinates to the image's pixels (a, b, c, d, e, f as
    SVG's matrix)."""

    url: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    transform: tuple[float, float, float, float, float, float]


class DrawingSummary(Contract):
    pieces: int = Field(ge=0)
    switches: int = Field(ge=0)
    crossings: int = Field(ge=0)
    line_exits: int = Field(ge=0)
    buffer_stops: int = Field(ge=0)
    signals: int = Field(ge=0)
    boundaries: int = Field(ge=0)
    labels: int = Field(ge=0)
    unknown_symbols: int = Field(ge=0)


class DrawingRead(Contract):
    """Ritningsavläsning (bildkedjan R4): what the chain read from one page, for Studio. The
    track graph is "schema": pieces, nodes and switches in the drawing's coordinates, the labels
    with the object each names and how it was read, and the symbols with their class. Then the
    track-circuit boundaries, the questions with the legend's first, the straightened drawing,
    and the job and its price. Everything is a proposal until the owner confirms it in Studio."""

    job: UUID
    page: int = Field(ge=1)
    kind: DrawingPageKind
    graph: TrackGraph
    boundaries: list[DrawingBoundary] = Field(default_factory=list)
    questions: list[DrawingQuestion] = Field(default_factory=list)
    underlay: DrawingUnderlay | None = None
    summary: DrawingSummary
    price: DrawingPrice
    cost: int = Field(ge=0, description="Tokens drawn for this read.")
    notes: list[Text] = Field(default_factory=list, description="What else to know, in Swedish.")

    @model_validator(mode="after")
    def _schema(self) -> Self:
        if self.graph.geometry != "schema":
            raise ValueError("En ritningsavläsning har spårgrafen i ritningens koordinater.")
        return self


class DrawingJob(Contract):
    """One drawing taken in, and its read. The same file, page and input give the same job, at
    no new cost (bildkedjan, Reproducerbarhet)."""

    id: UUID
    name: Text = Field(max_length=120, description="The file's name, as the owner gave it.")
    state: DrawingJobState
    progress: int = Field(ge=0, le=100)
    step: Text
    created_at: datetime
    format: Literal["pdf", "svg", "image"]
    pages: list[DrawingPage] = Field(min_length=1, max_length=MAX_DRAWING_PAGES)
    page: int = Field(ge=1, description="The page read, or to read.")
    price: DrawingPrice
    ai: DrawingAi
    read: DrawingRead | None = None
    cost: int = Field(ge=0)
    chain: Text
    key: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    message: Text | None = Field(default=None, description="Why it stopped, in Swedish.")


class DrawingStart(Contract):
    """The form's data part."""

    name: Text | None = Field(default=None, max_length=120, description="The file's name.")


class DrawingReadAsk(Contract):
    """Läs ritningen: the page, with AI for a raster page's text or without."""

    page: int = Field(default=1, ge=1, le=MAX_DRAWING_PAGES)
    ai: bool = True
    consent: bool = False


# --- Landskapet and Exportera (part d1, CAD-04, CAD-07, CAD-08, CAD-24, CAD-33) -------------
#
#     GET    /api/cad/1/modules/{module}/landscape?version=   Landscape
#     POST   /api/cad/1/modules/{module}/landscape/make       LandscapeMake -> Landscape: a new
#                                                             version with the landscape made from
#                                                             the measuring image, or empty to
#                                                             paint by hand without a photo
#     POST   /api/cad/1/modules/{module}/landscape            LandscapeEdit -> Landscape, the
#                                                             change set shown; nothing is saved
#     POST   /api/cad/1/modules/{module}/landscape/save       LandscapeEdit -> Landscape, a new
#                                                             version
#     POST   /api/cad/1/modules/{module}/landscape/approve    LandscapeEdit -> Landscape: saved if
#                                                             it changes something, and the
#                                                             version approved
#     GET    /api/cad/1/modules/{module}/export?version=      ModuleExport
#     GET    /api/cad/1/modules/{module}/export/{version}/{file}
#                                                             the file (EXPORT_FILES): modul.dxf
#                                                             (?rails=&landscape=), fremo.svg,
#                                                             utskrift.svg, moduldatabas.json,
#                                                             moduldatabas.csv, mmm.csv
#
# Landskapet (CAD-04): the module's surfaces from the measuring image, in surface classes
# (bildkedjan step 14). TrainMeet's own model on CAD's server makes them when there is one;
# until then, and whenever it cannot, colour clustering of the measuring image (CAD8, CAD-24,
# CAD-33). It is free (CAD-18). The owner paints and erases (Måla, Sudda, Fyll). The ballast under
# the tracks comes from the track plan, never from the colours, and the tracks are always drawn
# from the geometry. The landscape belongs to the module version (CAD-08): every save is a new
# version, and a later version keeps the landscape until a new one is saved. It is a proposal
# (orange) until the version is approved (CAD-17): Godkänn landskapet, or the module's Godkänn.
#
# Exportera (CAD-07): whoever sees the module exports it, free. A module with an approved version
# exports that one; a draft exports with Utkast on every file.


class Surface(StrEnum):
    """Ytklass: what a part of the landscape is (bildkedjan step 14)."""

    GRASS = "grass"
    BALLAST = "ballast"
    GROUND = "ground"
    """Mark och väg."""
    PLATFORM = "platform"
    WATER = "water"
    BUILDING = "building"
    TREES = "trees"
    """Buske och träd."""
    PATH = "path"
    """Stig."""
    UNKNOWN = "unknown"
    """Okänd yta: a colour that is none of the classes; the owner names it by painting."""


SURFACE_NAMES: Final = {
    Surface.GRASS: "Gräs",
    Surface.BALLAST: "Ballast",
    Surface.GROUND: "Mark och väg",
    Surface.PLATFORM: "Plattform",
    Surface.WATER: "Vatten",
    Surface.BUILDING: "Byggnad",
    Surface.TREES: "Buske och träd",
    Surface.PATH: "Stig",
    Surface.UNKNOWN: "Okänd yta",
}

SURFACE_COLOURS: Final = {
    Surface.GRASS: "#7fa860",
    Surface.BALLAST: "#a8a39a",
    Surface.GROUND: "#9c8466",
    Surface.PLATFORM: "#d6d2c8",
    Surface.WATER: "#5b8fc7",
    Surface.BUILDING: "#b0645a",
    Surface.TREES: "#3f6b3a",
    Surface.PATH: "#d2b98a",
    Surface.UNKNOWN: "#c9b8d9",
}
"""The surfaces' colours in Landskapet, the print and the exports: muted, as a model's
landscape."""


class LandscapeMethod(StrEnum):
    """How the landscape was made (CAD8)."""

    MODEL = "model"
    """TrainMeet's own model for the surfaces, on CAD's server. None is trained yet."""
    COLOUR = "colour"
    """Färgklustring of the measuring image: the fallback (CAD-24)."""
    HAND = "hand"
    """No photo: an empty landscape, painted by hand."""


class LandscapeStatus(StrEnum):
    NONE = "none"
    """The version has no landscape yet."""
    PROPOSAL = "proposal"
    """Förslag (orange): the version is not approved (CAD-17)."""
    APPROVED = "approved"
    """Godkänt: the version that holds it is approved."""


class SurfaceInfo(Contract):
    """A surface class as Landskapet shows it: its name and colour."""

    surface: Surface
    name: Text
    colour: Annotated[str, StringConstraints(pattern=r"^#[0-9a-f]{6}$")]


class LandscapeGrid(Contract):
    """The landscape's cells in the module's millimetres: cell (0, 0)'s corner at (x0, y0), cell
    mm on a side. Painting changes whole cells."""

    x0: float
    y0: float
    cell: float = Field(gt=0, le=50)
    width: int = Field(ge=1, le=4000)
    height: int = Field(ge=1, le=4000)


class LandscapeArea(Contract):
    """Yta: one connected surface as a polygon in mm, simplified, with its holes. painted: the
    owner painted it; otherwise it is what the photo gave."""

    surface: Surface
    outline: list[Point] = Field(min_length=3)
    holes: list[list[Point]] = Field(default_factory=list)
    area: float = Field(ge=0, description="mm².")
    painted: bool = False


class SurfaceTotal(Contract):
    """How much of the board a surface covers: the legend. The ballast counts the track bed."""

    surface: Surface
    area: float = Field(ge=0, description="mm².")
    share: float = Field(ge=0, le=1)


class Landscape(Contract):
    """Landskapet of one module version: its surfaces, the ballast under the tracks from the
    track plan, and the measuring image to paint over."""

    module: UUID
    version: int = Field(ge=1, description="The version shown.")
    latest: int = Field(ge=1)
    saved_in: int | None = Field(
        default=None,
        ge=1,
        description="The version the landscape was saved in; an earlier "
        "one when the version keeps it.",
    )
    status: LandscapeStatus
    method: LandscapeMethod | None = None
    made_by: Text | None = Field(default=None, description="What made it: Färgklustring 1 …")
    grid: LandscapeGrid | None = None
    areas: list[LandscapeArea] = Field(default_factory=list)
    track_bed: list[list[Point]] = Field(
        default_factory=list, description="The ballast under the tracks, from the track plan."
    )
    totals: list[SurfaceTotal] = Field(default_factory=list)
    surfaces: list[SurfaceInfo] = Field(default_factory=list, description="Every class, in order.")
    photo: PhotoLayer | None = Field(default=None, description="The measuring image under.")
    may_edit: bool
    changed: bool = Field(default=False, description="The operations changed something.")


class PaintLandscape(Contract):
    """Måla: the surface along a stroke, with a brush radius mm."""

    op: Literal["paint"] = "paint"
    surface: Surface
    radius: float = Field(ge=1, le=500)
    points: list[Point] = Field(min_length=1, max_length=2000)


class EraseLandscape(Contract):
    """Sudda: nothing along the stroke, as a shadow wrongly classed (CAD-04)."""

    op: Literal["erase"] = "erase"
    radius: float = Field(ge=1, le=500)
    points: list[Point] = Field(min_length=1, max_length=2000)


class FillLandscape(Contract):
    """Fyll: the connected area under the point, of the same surface or empty, becomes the
    surface."""

    op: Literal["fill"] = "fill"
    surface: Surface
    at: Point


LandscapeOp = Annotated[PaintLandscape | EraseLandscape | FillLandscape, Field(discriminator="op")]


class LandscapeEdit(Contract):
    """The landscape's change set on top of base, the newest version the person read, as in
    Ritningen: replayed for every call and refused with 409 when a newer version exists."""

    base: int = Field(ge=1)
    operations: list[LandscapeOp] = Field(default_factory=list, max_length=500)


class LandscapeMake(Contract):
    """Gör landskapet: from the measuring image, or empty without one. Replaces the landscape."""

    base: int = Field(ge=1)


class ExportKind(StrEnum):
    """Exportera (CAD-07)."""

    FREMO = "fremo"
    """FREMO-ritning: the module sheet with the plan, the measures and the gables."""
    DATABASE = "database"
    """Moduldatabasen: the module as a record (ModuleRecord), JSON or CSV."""
    MMM = "mmm"
    """The gables' measures and track distances as MMM gives them. The MMM forms are planned."""
    DXF = "dxf"
    """DXF R12 in mm with real LINE and ARC (CAD-24)."""
    PRINT = "print"
    """Utskrift: the module with its landscape on a page, printed by the browser."""


EXPORT_FILES: Final = {
    "fremo.svg": (ExportKind.FREMO, "image/svg+xml"),
    "utskrift.svg": (ExportKind.PRINT, "image/svg+xml"),
    "moduldatabas.json": (ExportKind.DATABASE, "application/json"),
    "moduldatabas.csv": (ExportKind.DATABASE, "text/csv; charset=utf-8"),
    "mmm.csv": (ExportKind.MMM, "text/csv; charset=utf-8"),
    "modul.dxf": (ExportKind.DXF, "application/dxf"),
}
"""The files a module exports, by the name in the address."""

RECORD_FORMAT: Final = "trainmeet.cad.moduldatabas/1"


class ExportFile(Contract):
    kind: ExportKind
    name: Text = Field(description="FREMO-ritning (SVG) …")
    file: Text = Field(description="The name it is saved as.")
    url: str
    media_type: str


class ExportVersion(Contract):
    """A version that can be exported: the approved one, and the newest draft."""

    version: int = Field(ge=1)
    status: ModuleStatus
    label: Text


class RecordGable(Contract):
    end: GableEnd
    norm: Norm | None = None
    profile: ProfileId | None = None
    label: Text
    width: float = Field(gt=0, description="mm.")
    tracks: list[float] = Field(default_factory=list, description="From Kant 1, mm.")


class ModuleRecord(Contract):
    """Moduldatabasen: one module as a row in a module list (format RECORD_FORMAT). The JSON is
    this record; the CSV has the same fields in RECORD_COLUMNS' order, comma-separated, UTF-8,
    decimal point, the gables' tracks joined with /."""

    format: Literal["trainmeet.cad.moduldatabas/1"] = RECORD_FORMAT
    id: UUID
    number: str
    name: Name
    owner: Text
    scale: Scale
    shape: Literal["straight", "curve", "trapezoid"]
    length: float = Field(ge=0, description="Along Kant 1; a curve: track 1's arc, mm.")
    radius: float | None = Field(default=None, description="A curve's track 1, mm, exact.")
    angle: float | None = Field(default=None, description="A curve's angle, degrees, exact.")
    offset: float | None = Field(default=None, description="A trapezoid's förskjutning, mm.")
    gables: list[RecordGable] = Field(min_length=2, max_length=2)
    track_length: float = Field(ge=0, description="mm.")
    switches: int = Field(ge=0)
    crossings: int = Field(ge=0)
    landscape: bool = Field(description="The version has a landscape.")
    version: int = Field(ge=1)
    status: ModuleStatus
    approved_at: datetime | None = None


RECORD_COLUMNS: Final = (
    "format",
    "id",
    "number",
    "name",
    "owner",
    "scale",
    "shape",
    "length",
    "radius",
    "angle",
    "offset",
    "gable_a_norm",
    "gable_a_profile",
    "gable_a_width",
    "gable_a_tracks",
    "gable_b_norm",
    "gable_b_profile",
    "gable_b_width",
    "gable_b_tracks",
    "track_length",
    "switches",
    "crossings",
    "landscape",
    "version",
    "status",
    "approved_at",
)
"""Moduldatabasen as CSV: a header row with these names, then the module's row."""


class MmmTrack(Contract):
    """One track in a gable, as MMM measures it: from Kant 1, the distance to the track before,
    MMM's position for it and how far the gable lies from it."""

    track: int = Field(ge=1, le=MAX_TRACKS)
    from_kant1: float
    spacing: float | None = Field(default=None, description="To the track before, c/c, mm.")
    mmm: float | None = Field(default=None, description="MMM's position, mm.")
    deviation: float | None = Field(default=None, description="from_kant1 - mmm, mm.")


class MmmGable(Contract):
    end: GableEnd
    norm: Norm | None = None
    label: Text
    width: float = Field(gt=0)
    tracks: list[MmmTrack] = Field(default_factory=list)


class ModuleExport(Contract):
    """Exportera: the version exported, the files and what they hold. draft: every file is
    marked Utkast."""

    module: UUID
    number: str
    name: Name
    version: int = Field(ge=1)
    status: ModuleStatus
    versions: list[ExportVersion] = Field(min_length=1)
    files: list[ExportFile]
    record: ModuleRecord
    mmm: list[MmmGable] = Field(min_length=2, max_length=2)
    landscape: bool


# --- The assembly (part d): Anläggningar and Till TKL Studio (CAD-06, CAD-10, CAD-15, CAD-21) --
#
#     GET    /api/cad/1/assemblies                     [AssemblyBrief]: mine and my clubs'
#     POST   /api/cad/1/assemblies                     NewAssembly -> Assembly, 201
#     GET    /api/cad/1/assemblies/{assembly}          Assembly, placed and checked
#     PUT    /api/cad/1/assemblies/{assembly}          AssemblyChange -> Assembly, the next
#                                                      revision; 409 when base is not the newest
#     DELETE /api/cad/1/assemblies/{assembly}          AssemblyRemoved; soft, as a module
#     GET    /api/cad/1/studio                         StudioSources: what Studio's Från CAD lists
#     GET    /api/cad/1/studio/{kind}/{id}             StudioGraph: the track graph Studio gets
#     PUT    /api/cad/1/studio/{kind}/{id}/station     StationUseAsk -> StudioSource: Används i
#
# An assembly puts modules together gable to gable (CAD-06). It has one scale, and its gables must
# fit (CAD9): the same number of tracks, the same norm where both gables have one, and each track
# where the other's is, measured from Kant 1, within JOINT_TOLERANCE. Facing gables meet Kant 1
# to Kant 1 when one is A and the other B; A to A or B to B turns the second module round, and its
# tracks are then measured from its far edge. A curve gives the angle; a joint may add one. The
# first module of each group lies where the owner put it, and every other one where its joints
# put it. A joint between two modules already placed closes a loop and is checked as it lies.
#
# The assembly pins each module's version (CAD-21): a module is added at its newest approved
# version, and a newer approved one is offered, never taken silently. Only those who see a module
# may use it; only the owner changes the assembly: a person's own, or for a club's its
# administrators. Who sees an assembly: its owner, and a club's members.
#
# Till TKL Studio sends the track graph only (CAD-10): the modules' graphs joined at the joints,
# placed in the assembly's mm, each id prefixed with its module's id ("<module>:s3"), and a track
# where two gables meet one node, the smaller of the two ids, so that the ids never change while
# the modules keep theirs (CAD-20). Signals, buffer stops and routes are worked out in Studio
# (CAD-09). CAD never makes a station (TKL8, CAD-15): Studio's Från CAD lists the person's
# assemblies and approved modules with the person's access token from ID, as Ladda upp ritning
# does, the owner confirms the proposal in Studio, and Studio then tells CAD which station uses
# it, for Används i.

JOINT_TOLERANCE: Final = 2 * POSITION_TOLERANCE
"""How far apart in mm two tracks that meet in a joint may lie: each gable may be 0,5 mm from the
norm's position (POSITION_TOLERANCE), so two of them up to 1 mm from each other."""

CLOSING_TURN: Final = 0.5
"""How many degrees a joint that closes a loop may turn more or less than its angle says."""

MAX_JOINT_ANGLE: Final = 15.0
"""The largest angle in degrees a joint adds, either way: the range the page takes."""

MAX_ASSEMBLY_MODULES: Final = 200


class JointEnd(Contract):
    """One side of a joint: a module in the assembly, and its gable."""

    module: UUID
    gable: GableEnd


class Joint(Contract):
    """Skarv: two modules' gables together, at an angle (CAD-06). The angle turns b's module
    counterclockwise about the middle of the tracks in the joint; 0 is flush."""

    a: JointEnd
    b: JointEnd
    angle: float = Field(
        default=0,
        ge=-MAX_JOINT_ANGLE,
        le=MAX_JOINT_ANGLE,
        description="What the joint adds, in degrees counterclockwise.",
    )


class PlacedModule(Contract):
    """A module in an assembly, at the version it pinned (CAD-21), shifted and turned."""

    module: UUID
    version: int = Field(ge=1)
    at: Point = Field(description="Where the module's origin (gable A at Kant 1) lies, in mm.")
    angle: float = Field(description="The module's turn, in degrees, counterclockwise.")


class StationUse(Contract):
    """Används i: a station in TKL that took an assembly or a module into use, as Studio told CAD
    when the owner confirmed it (CAD-15). The station's id is TKL's, the station's own."""

    station_id: Id
    name: Text = Field(max_length=80)
    revision: int = Field(ge=1, description="The assembly's revision, or the module's version.")
    at: datetime


class GableAt(Contract):
    """A placed module's gable in the assembly, in the assembly's mm: its corners and where its
    tracks meet the next module, to draw it and to join it."""

    end: GableEnd
    corner: Point = Field(description="The corner at Kant 1.")
    far: Point = Field(description="The other corner.")
    tracks: list[Point] = Field(default_factory=list, description="Spår 1 first.")
    label: Text = Field(description='"MMM enkelspår", "Egen gavel · 2 spår".')
    norm: Norm | None = None
    joined: bool = Field(description="A joint uses it.")


class AssemblyModule(Contract):
    """A module in the assembly as the page shows it, at its pinned version."""

    module: UUID
    version: int = Field(ge=1)
    seen: bool = Field(
        description="The person sees the module now. Unseen it is only an outline: it cannot "
        "be used, and the assembly cannot go to Studio."
    )
    number: str | None = Field(default=None, pattern=r"^M-\d{3,}$")
    name: Text | None = Field(default=None, max_length=80)
    owner: Text | None = Field(default=None, max_length=80, description="The module's owner.")
    placed: Literal["first", "joint", "free"] = Field(
        description="The first module, placed by a joint, or lying free where the owner put it."
    )
    outline: list[Point] = Field(default_factory=list, description="The board, Kant 1 first.")
    gables: list[GableAt] = Field(default_factory=list)
    newer: int | None = Field(
        default=None, ge=1, description="A newer approved version, offered; never taken silently."
    )


class JointCheck(Contract):
    """Skarven kontrollerad (CAD9): whether the gables fit, and why not."""

    joint: int = Field(ge=0, description="The joint's place in the list.")
    fits: bool
    problems: list[Text] = Field(default_factory=list)
    gap: float = Field(ge=0, description="The farthest two tracks that meet lie apart, in mm.")
    turn: float = Field(
        default=0, ge=0, description="A closing joint's turn beyond its angle, in degrees."
    )
    closing: bool = Field(default=False, description="It joins two modules already placed.")


class Assembly(Contract):
    """Anläggning: modules together, with joints and angles (CAD-06). One scale, and gables that
    fit together (CAD9). The modules' placement is worked out from the joints; graph is the track
    graph Till TKL Studio sends (CAD-10)."""

    id: UUID
    name: Name
    owner: Owner
    scale: Scale
    modules: list[PlacedModule] = Field(default_factory=list)
    joints: list[Joint] = Field(default_factory=list)
    revision: int = Field(default=1, ge=1, description="Every change is the next revision.")
    changed_at: datetime | None = None
    may_edit: bool = Field(default=False, description="The person may change it (CAD-21).")
    parts: list[AssemblyModule] = Field(default_factory=list, description="As the page shows.")
    checks: list[JointCheck] = Field(default_factory=list, description="One per joint.")
    problems: list[Text] = Field(
        default_factory=list, description="What keeps it from Studio; empty: it may go."
    )
    graph: TrackGraph = Field(default_factory=TrackGraph)
    stations: list[StationUse] = Field(default_factory=list, description="Används i.")


class AssemblyBrief(Contract):
    """An assembly as the list on Anläggningar shows it."""

    id: UUID
    name: Name
    owner: Owner
    scale: Scale
    modules: int = Field(ge=0)
    problems: int = Field(ge=0, description="How many things keep it from Studio.")
    revision: int = Field(ge=1)
    changed_at: datetime
    may_edit: bool
    stations: list[StationUse] = Field(default_factory=list)


class NewAssembly(Contract):
    """Ny anläggning. owner a club's id makes it the club's: the club's administrator may."""

    name: Name
    scale: Scale
    owner: UUID | None = None


class AssemblyPart(Contract):
    """A module in a change: the version it pins, null for its newest approved one (adding it,
    or taking the newer one offered); and where it lies when no joint places it."""

    module: UUID
    version: int | None = Field(default=None, ge=1)
    at: Point = (0.0, 0.0)
    angle: float = Field(default=0, ge=-360, le=360)


class AssemblyChange(Contract):
    """Spara: the whole assembly as the page has it, on top of base, the newest revision the
    person read. Refused with 409 when a newer revision exists."""

    base: int = Field(ge=1)
    name: Name
    modules: list[AssemblyPart] = Field(default_factory=list, max_length=MAX_ASSEMBLY_MODULES)
    joints: list[Joint] = Field(default_factory=list, max_length=2 * MAX_ASSEMBLY_MODULES)

    @model_validator(mode="after")
    def _joints(self) -> Self:
        ids = [m.module for m in self.modules]
        if len(ids) != len(set(ids)):
            raise ValueError("En modul finns bara en gång i anläggningen.")
        used: set[tuple[UUID, GableEnd]] = set()
        for joint in self.joints:
            for side in (joint.a, joint.b):
                if side.module not in ids:
                    raise ValueError("En skarv går till en modul som inte finns i anläggningen.")
                if (side.module, side.gable) in used:
                    raise ValueError(
                        f"Gavel {side.gable} på samma modul finns redan i en annan skarv."
                    )
                used.add((side.module, side.gable))
            if joint.a.module == joint.b.module:
                raise ValueError("En modul skarvas inte mot sig själv.")
        return self


class AssemblyRemoved(Contract):
    id: UUID


class StudioSourceKind(StrEnum):
    """What Studio's Från CAD connects to a station: a group of modules (STUDIO-03)."""

    ASSEMBLY = "assembly"
    MODULE = "module"
    """A single approved module, the person's own."""


class StudioModule(Contract):
    """A module in what Studio gets: its id is the prefix of its ids in the graph."""

    id: UUID
    number: str = Field(pattern=r"^M-\d{3,}$")
    name: Text = Field(max_length=80)
    version: int = Field(ge=1)


class StudioSource(Contract):
    """Från CAD: an assembly or a single module the person may connect to a station."""

    kind: StudioSourceKind
    id: UUID
    name: Text = Field(max_length=80)
    scale: Scale
    owner: Text = Field(max_length=80)
    revision: int = Field(ge=1, description="The assembly's revision, or the module's version.")
    modules: list[StudioModule] = Field(default_factory=list)
    ready: bool = Field(description="It may go to Studio: no problems.")
    problems: list[Text] = Field(default_factory=list)
    stations: list[StationUse] = Field(default_factory=list, description="Används i.")
    changed_at: datetime


class StudioSources(Contract):
    """Från CAD's list: the person's assemblies and approved modules, newest first."""

    sources: list[StudioSource] = Field(default_factory=list)


class StudioGraph(Contract):
    """Till TKL Studio (CAD-10): the source and its track graph, in mm, with ids CAD never
    changes. Only the graph follows; Studio works out the signals, buffer stops and routes."""

    source: StudioSource
    graph: TrackGraph


class StationUseAsk(Contract):
    """Studio tells CAD that a station took the source into use, at a revision (CAD-15)."""

    station_id: Id
    name: Text = Field(max_length=80)
    revision: int = Field(ge=1)
