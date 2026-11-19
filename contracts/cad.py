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
  FREMO, MMM, USMS and the club's own norm, in 0 FREMO Spur 0 (CAD12). The spec names no norm
  in N yet, so an N gable has no norm until it does.
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
a turn, and its ids are prefixed with the module's id.
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from contracts.common import AppKey, Contract, Id, Text
from contracts.station_model import NodeType, Point, SwitchType

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


class CadProblem(Contract):
    """The answer when CAD says no: 401, 403, 404, 409, 422 or 503."""

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


NORMS: Final[dict[Scale, tuple[Norm, ...]]] = {
    Scale.H0: (Norm.FREMO, Norm.MMM, Norm.USMS, Norm.CLUB),
    Scale.N: (),
    Scale.ZERO: (Norm.FREMO_SPUR_0,),
}
"""The norms per scale from the start (CAD11, CAD12). The spec names none in N yet (CAD-N)."""

NORM_NAMES: Final[dict[Norm, str]] = {
    Norm.FREMO: "FREMO",
    Norm.MMM: "MMM",
    Norm.USMS: "USMS",
    Norm.CLUB: "Klubbens egen",
    Norm.FREMO_SPUR_0: "FREMO Spur 0",
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
        if self.type not in CAD_NODE_TYPES:
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
    (bildkedjan, R4 and point 21). The Text tool writes them."""

    id: Id
    text: Text = Field(max_length=40)
    at: Point
    ref: Id | None = Field(default=None, description="The piece or switch it names.")
    origin: GraphOrigin | None = None


class TrackGraph(Contract):
    """Spårgraf: what CAD sends to Studio (CAD-10). Ids are never changed when the module is
    redrawn, and never used again for something else (CAD-20). geometry is "mm" for a module's
    real geometry; a drawing read by the photo chain for Studio gives "schema" (bildkedjan, 21).
    complete is false while the tracks between the gables are unknown: a module from measures
    whose gables differ waits for its photo or its drawing."""

    geometry: Literal["mm", "schema"] = "mm"
    nodes: list[GraphNode] = Field(default_factory=list)
    pieces: list[GraphPiece] = Field(default_factory=list)
    switches: list[GraphSwitch] = Field(default_factory=list)
    labels: list[GraphLabel] = Field(default_factory=list)
    complete: bool = True
    issued: int = Field(default=0, ge=0, description="Ids issued so far; the next is one more.")

    @model_validator(mode="after")
    def _linked(self) -> Self:
        node_ids = [n.id for n in self.nodes]
        piece_ids = [p.id for p in self.pieces]
        ids = node_ids + piece_ids + [s.id for s in self.switches] + [x.id for x in self.labels]
        if len(ids) != len(set(ids)):
            raise ValueError("Två delar av spårgrafen har samma id.")
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
    instead, with no answer stored (choose a switch type, open Lås mått)."""

    id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]
    text: Text = Field(max_length=60)
    closes: bool = True
    action: Literal["design", "lock"] | None = None


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


class DrawnLine(Contract):
    """The line a piece was drawn from, by hand (or, in part c, traced in the photo): utjämning
    makes it LINE and ARC again when its level changes, and the deviation is measured from it."""

    piece: Id
    points: list[Point] = Field(min_length=2, max_length=4000)
    source: Literal["hand", "photo"] = "hand"


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
    """Används i: an assembly or a meet that uses the module, at the version it pinned (part d)."""

    kind: Literal["assembly", "meet"]
    id: UUID
    name: Text
    version: int = Field(ge=1)


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


class ModuleEvent(Contract):
    """Historik: one thing that happened to the module."""

    at: datetime
    kind: ModuleEventKind
    version: int = Field(ge=1)
    by: Text = Field(description="The person's name.")
    text: Text = Field(description="What happened, in Swedish.")


class ModuleRemoved(Contract):
    id: UUID


# --- The assembly (part d) ----------------------------------------------------------------


class PlacedModule(Contract):
    """A module in an assembly, at the version it pinned (CAD-21), shifted and turned."""

    module: UUID
    version: int = Field(ge=1)
    at: Point = Field(description="Where the module's origin (gable A at Kant 1) lies, in mm.")
    angle: float = Field(description="The module's turn, in degrees, counterclockwise.")


class Joint(Contract):
    """Skarv: two modules' gables together, at an angle (CAD-06)."""

    a: tuple[int, GableEnd] = Field(description="The placed module's index, and its gable.")
    b: tuple[int, GableEnd]
    angle: float = Field(default=0, description="The angle between them, in degrees.")


class Assembly(Contract):
    """Anläggning: modules together, with joints and angles (CAD-06). One scale, and gables that
    fit together (CAD9). Only the shell in part a; part d builds it."""

    id: UUID
    name: Name
    owner: Owner
    scale: Scale
    modules: list[PlacedModule] = Field(default_factory=list)
    joints: list[Joint] = Field(default_factory=list)
