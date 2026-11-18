"""TrainMeet ID's own API, trainmeet.id/1 (#67): clubs, members, and the roles per resource.

Keycloak holds the accounts and the login (#66, ID4). Next to it, at the same address, ID's API
holds the rest of what ID owns (KONTO-08): the clubs and their members (KONTO-02, KONTO-35),
the roles per resource (KONTO-03, KONTO-28, KONTO-36), and the answer to the question an app
asks: which roles does this person have for this resource (KONTO-34). ID never owns the meets,
modules, vehicles or station packages themselves (KONTO-09); a resource is only a reference.

    GET    /api/version                                   Version

For the person, with ID's session cookie (the web app at id.trainmeet.app):
    GET    /api/id/1/session                              Session
    DELETE /api/id/1/session                              Session, logged out
    GET    /api/id/1/clubs                                [Club], the person's own
    POST   /api/id/1/clubs                                ClubName -> Club; the creator is admin
    GET    /api/id/1/clubs/{club}                         ClubPage, with the club's meets
    POST   /api/id/1/clubs/{club}/meets                   NewMeet -> Meet; the admin (ID10)
    POST   /api/id/1/clubs/{club}/invitations             Invite -> Invitation
    PUT    /api/id/1/clubs/{club}/members/{person}        ClubRoleChange -> ClubPage; the admin
    DELETE /api/id/1/clubs/{club}/members/{person}        ClubPage; admin removes, member leaves
    GET    /api/id/1/fleets/{owner}                       FleetPage; the owner's sharing
    POST   /api/id/1/fleets/{owner}/invitations           FleetInvite -> Invitation
    GET    /api/id/1/meets                                [Meet], the person's clubs' (ID10)
    GET    /api/id/1/meets/{meet}                         MeetPage: the roles at the meet
    PUT    /api/id/1/meets/{meet}                         NewMeet -> MeetPage; admin, organizer
    DELETE /api/id/1/meets/{meet}                         Removed; the club's admin
    POST   /api/id/1/meets/{meet}/grants                  MeetGrant -> MeetPage (KONTO-36)
    DELETE /api/id/1/grants/{grant}                       Removed; stop sharing, takes a role
    POST   /api/id/1/help                                 HelpRequest -> HelpSent (KONTO-06, ID9)
    GET    /api/id/1/account/removal                      RemovalPlan: what goes with the account
    GET    /api/id/1/account/export                       AccountExport, as a file (KONTO-31)
    POST   /api/id/1/account/remove                       RemoveAccount -> Session (KONTO-31, ID7)
    GET    /api/id/1/invitations                          [Invitation] to the person
    POST   /api/id/1/invitations/{invitation}/answer      Answer -> Invitation
    DELETE /api/id/1/invitations/{invitation}             Removed; the inviter takes it back

For the apps, with an access token from Keycloak's client credentials (KONTO-34):
    GET    /api/id/1/apps/access?person=&resource=        Access
    GET    /api/id/1/apps/fleets?person=                  [FleetAccess], the fleets shared with
    GET    /api/id/1/apps/switcher?person=                Switcher: the apps to show (ID11)

For TrainMeet's owners, named in ID's vault (TOKEN-05), on the owner page:
    GET    /api/id/1/owner/reviewers                      [Grant]: Granskare in Catalog (ID6)
    POST   /api/id/1/owner/reviewers                      ReviewerGrant -> [Grant]
    DELETE /api/id/1/owner/reviewers/{reviewer}           [Grant]

Rules:
- Every changing call checks on the server who asks (CAT-195 for ID).
- A role always applies to one resource (KONTO-03). The resource's owner, or the admin of the
  club that owns it, hands out its roles (KONTO-36).
- An invitation gives nothing until the person it was sent to has said yes, logged in with the
  same verified address (KONTO-29, KONTO-35, CAT-45).
- Granskare of Catalog's prototypes is the role reviewer on catalog:prototypes (KONTO-30, ID6,
  CAT-165). Only TrainMeet's owners give and take it, on the owner page, to someone who has
  logged in to ID. Catalog asks for it at every call, as for a fleet.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from contracts.catalog import CatalogExport
from contracts.common import AppKey, Contract, Text
from contracts.tokens import TokenBalance

Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
"""An e-mail address, compared in lower case."""

ClubNameText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
MeetNameText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class ResourceKind(StrEnum):
    """What a role applies to (KONTO-03). ID only holds the reference, never the thing."""

    CLUB = "club"
    """A club in ID."""
    FLEET = "fleet"
    """An owner's whole fleet in Catalog, a person's or a club's (CAT-44, CAT-51)."""
    MEET = "meet"
    """A meet in the Hub."""
    STATION = "station"
    """A station in TKL."""
    MODULE = "module"
    """A module in CAD."""
    HUB = "hub"
    """A hub."""
    CATALOG = "catalog"
    """Catalog as a whole, for the reviewers of prototypes (KONTO-30)."""


PROTOTYPE_REVIEWERS = "prototypes"
"""The id of the resource the reviewers of Catalog's prototypes have their role on, of the kind
catalog: catalog:prototypes (KONTO-30, ID6, CAT-165)."""


class Resource(Contract):
    """One thing a role applies to: its kind and its id in the app that owns it."""

    kind: ResourceKind
    id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")]


class Role(StrEnum):
    """The roles ID holds on one place (KONTO-28, KONTO-30, CAT-44, KONTO-35)."""

    ADMIN = "admin"
    """Administratör: a club's, and Planering's."""
    MEMBER = "member"
    """Medlem in a club."""
    ORGANIZER = "organizer"
    """Arrangör in Planering."""
    PUBLISHER = "publisher"
    """Får publicera: the Arrangör also publishes the meet's versions (PLAN-19, H16)."""
    READER = "reader"
    """Läsare in Planering."""
    DISPATCHER = "dispatcher"
    """Trafikledare for one meet (ID3)."""
    LOCO_LEAD = "loco_lead"
    """Lokledare for one meet (LF17)."""
    REMOTE_CLEARER = "remote_clearer"
    """Fjärrtågklarerare for one meet."""
    REVIEWER = "reviewer"
    """Granskare av förebilder in Catalog (KONTO-30, ID6)."""
    VIEWER = "viewer"
    """May look at a shared fleet (CAT-44)."""
    EDITOR = "editor"
    """May edit a shared fleet (CAT-44, CAT-46)."""


class Version(Contract):
    """What is running, so a tester can see which change the test environment has."""

    product: str = "TrainMeet ID"
    commit: str | None = Field(default=None, description="The git commit, or null locally.")


class Account(Contract):
    """The person who is logged in, as ID knows them."""

    id: UUID = Field(description="The account's id, the same in every app (the token's sub).")
    name: Text = Field(max_length=80)
    initials: str = Field(min_length=1, max_length=3)
    email: Email = Field(description="Verified by the code to it (KONTO-10).")


class Switcher(Contract):
    """The apps the person has something in (KONTO-38, ID11): Catalog and ID for everyone who
    is logged in; the Hub with a role at a meet or as a club's admin, Lokföraren as Lokledare,
    TKL with a role at a station and CAD with a role on a module."""

    apps: list[AppKey]


class Session(Contract):
    account: Account | None = None
    logout_url: str | None = Field(
        default=None,
        description="Only in the answer to logging out: where the browser goes next.",
    )
    apps: list[AppKey] = Field(
        default_factory=list, description="The app switcher's apps for the person (ID11)."
    )
    owner: bool = Field(
        default=False, description="TrainMeets ägare: ser ägarsidan för tokens (TOKEN-05)."
    )


class HelpKind(StrEnum):
    HELP = "help"
    """Be om hjälp."""
    FAULT = "fault"
    """Rapportera ett fel."""


class HelpRequest(Contract):
    """Hjälp och fel in the account menu of every app (KONTO-06). It goes as a mail to Beahead's
    support address, with the app, the page and the version, and the person's verified address
    to answer (ID9, ID12)."""

    kind: HelpKind
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    app: AppKey
    page: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""
    version: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""


class HelpSent(Contract):
    sent: Literal[True] = True


class Person(Contract):
    """Someone else, as a member or someone with a role: never their address."""

    id: UUID
    name: Text = Field(max_length=80)
    initials: str = Field(min_length=1, max_length=3)


class ClubRole(StrEnum):
    """A person's role in a club (KONTO-35)."""

    ADMIN = "admin"
    MEMBER = "member"


class ClubName(Contract):
    name: ClubNameText


class Club(Contract):
    id: UUID
    name: ClubNameText
    role: ClubRole = Field(description="The person's role in the club.")


class Member(Contract):
    person: Person
    role: ClubRole
    since: datetime


class InvitationState(StrEnum):
    WAITING = "waiting"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class Invitation(Contract):
    """An invitation to a club (KONTO-35) or to a shared fleet (KONTO-29). Gives nothing
    until the person it was sent to has said yes."""

    id: UUID
    resource: Resource
    role: Role
    title: Text = Field(description="What it is about: the club's name, or whose fleet.")
    sent_to: str = Field(description="The address, partly hidden to anyone but its owner.")
    sent_by: Person
    state: InvitationState
    at: datetime


class MeetRole(StrEnum):
    """The roles per meet that ID hands out until the Hub logs in with ID (ID10, KONTO-28)."""

    ORGANIZER = "organizer"
    """Arrangör: plans the meet, and hands out Trafikledare and Lokledare for it (KONTO-36)."""
    PUBLISHER = "publisher"
    """Får publicera: the Arrangör also publishes the meet's versions, a choice per meet as in
    the old Cloud (PLAN-19, PLAN-24, H16). Given only to the meet's Arrangör, by the club's
    admin; only counts together with Arrangör."""
    READER = "reader"
    """Läsare: looks at the meet's plan in Planering and changes nothing (PLAN-19, H16)."""
    DISPATCHER = "dispatcher"
    """Trafikledare (ID3, KONTO-16)."""
    LOCO_LEAD = "loco_lead"
    """Lokledare: hands out duties, runs no traffic (LF17)."""
    REMOTE_CLEARER = "remote_clearer"
    """Fjärrtågklarerare."""


class NewMeet(Contract):
    """A meet as ID holds it: a reference with name, dates and club (ID10). The meet itself, its
    plan and its traffic, belongs to the Hub (KONTO-09)."""

    name: MeetNameText
    starts_on: date
    ends_on: date

    @model_validator(mode="after")
    def _in_order(self) -> Self:
        if self.ends_on < self.starts_on:
            raise ValueError("Träffen slutar innan den börjar.")
        if (self.ends_on - self.starts_on).days > 30:
            raise ValueError("En träff är högst en månad.")
        return self


class Meet(NewMeet):
    id: UUID
    club: UUID
    club_name: ClubNameText
    roles: list[MeetRole] = Field(description="The person's own roles at the meet.")
    club_admin: bool = Field(
        default=False,
        description="The person is the club's admin, with the admin's say at its meets "
        "(KONTO-36). The Hub plans the meet then, as it does for the organizer (#78).",
    )


class MeetPage(Contract):
    """A meet's roles, as the club's members see them (ID10). Whoever may hand out roles also
    gets the club's members to choose from (KONTO-17: clubs are kept apart)."""

    meet: Meet
    grants: list[Grant]
    may_give: list[MeetRole] = Field(
        description="The roles the person may hand out here: the club's admin all of them, "
        "the organizer Trafikledare and Lokledare (KONTO-36)."
    )
    may_change: bool = Field(description="May change the name and the dates.")
    may_remove: bool = Field(description="May remove the meet: the club's admin.")
    members: list[Person] = Field(
        default_factory=list, description="The club's members, when the person may hand out."
    )


class MeetGrant(Contract):
    """Hand out a role at the meet to one of the club's members."""

    person: UUID
    role: MeetRole


class ClubPage(Contract):
    """A club as its members see it. Only the admin sees the waiting invitations."""

    club: Club
    members: list[Member]
    invitations: list[Invitation] = Field(default_factory=list)
    meets: list[Meet] = Field(default_factory=list, description="The club's meets (ID10).")


class ClubRoleChange(Contract):
    """The admin gives a member the admin's role, or takes it back. A club always keeps an
    admin (KONTO-02, KONTO-35)."""

    role: ClubRole


class Invite(Contract):
    """Invite someone to the club with their e-mail address (KONTO-35)."""

    email: Email


class FleetRole(StrEnum):
    VIEWER = "viewer"
    EDITOR = "editor"


class FleetInvite(Contract):
    """Share the whole fleet with one person, to look at or to edit (CAT-44, KONTO-29)."""

    email: Email
    role: FleetRole


class Grant(Contract):
    """A role someone has for a resource."""

    id: UUID
    person: Person
    role: Role
    resource: Resource
    at: datetime


class FleetPage(Contract):
    """Who the fleet is shared with, and who is invited (CAT-44, CAT-45)."""

    owner: Resource
    title: Text
    grants: list[Grant]
    invitations: list[Invitation]


class ReviewerGrant(Contract):
    """The owner page gives the role Granskare in Catalog to a person, by the verified address
    they log in to ID with (KONTO-30, ID6)."""

    email: Email


class Answer(Contract):
    accept: bool


class Removed(Contract):
    id: UUID


class TicketRequest(Contract):
    """The Hub asks for a ticket for someone who logged in on a meet's Pi with internet
    (KONTO-11, KONTO-37, #78): for which Pi, and the meets in ID whose roles go in it."""

    person: UUID
    hub: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")]
    meets: list[UUID] = Field(default_factory=list, max_length=10)


class Ticket(Contract):
    """Biljetten: signed by ID, checked by the Pi against ID's public keys, fetched before
    (KONTO-11). It lasts 30 days and holds the roles as they were (KONTO-37)."""

    ticket: str = Field(description="A signed JWT (ES256). Never written to a log.")
    expires: datetime


class TicketKeys(Contract):
    """ID's public keys for the tickets, open to anyone, as a JWK set (KONTO-11). The Pi gets
    them through its cloud hub while it has internet."""

    keys: list[dict[str, Any]]


class Access(Contract):
    """What ID says now: the roles a person has for a resource (KONTO-34). Empty: none.

    For a club's fleet the club's roles count too (CAT-51, C36): its administrators have admin,
    which is the owner's right, and its members viewer."""

    person: UUID
    resource: Resource
    roles: list[Role]


class FleetAccessRole(StrEnum):
    """How a person may work in a fleet that is not their own."""

    VIEWER = "viewer"
    EDITOR = "editor"
    OWNER = "owner"
    """A club's administrators have the owner's right to the club's fleet (C36, C39)."""


class FleetAccess(Contract):
    """A fleet the person may work in besides their own: shared with them, or their club's
    (CAT-50, CAT-51)."""

    owner: Resource = Field(description="Kind fleet: the owner's id, a person's or a club's.")
    title: Text = Field(description="Whose fleet it is, as the owner shows it.")
    role: FleetAccessRole
    club: bool = Field(
        default=False,
        description=(
            "The owner is a club: the fleet's pictures count against the club's 2 GB, not a "
            "person's 100 MB (TOKEN-29, TK17)."
        ),
    )


class ProblemCode(StrEnum):
    LOGIN = "login"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    INVALID = "invalid"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"
    TOO_MANY = "too_many"
    NO_TOKENS = "no_tokens"
    """Saldot räcker inte (TOKEN-04): köp fler eller använd egen AI. HTTP 402."""


class Problem(Contract):
    code: ProblemCode
    message: Text


class ClubBrief(Contract):
    id: UUID
    name: ClubNameText


class RemovalPlan(Contract):
    """What removing the account takes with it (KONTO-31, ID7, ID13). A club where the person
    is the only member goes too, with its meets and its fleet. A club where the person is the
    only admin among other members stops the removal until someone else has the role."""

    clubs_removed: list[ClubBrief]
    clubs_blocking: list[ClubBrief]


class RemoveAccount(Contract):
    """The person has typed the word that confirms (TA BORT)."""

    confirm: Literal[True]


class AccountExport(Contract):
    """Everything TrainMeet holds for the person, as one file before the account is removed
    (KONTO-31, ID7): ID's own, and Catalog's."""

    made_at: datetime
    account: Account
    clubs: list[Club]
    roles: list[Grant]
    invitations: list[Invitation]
    meets: list[Meet]
    catalog: CatalogExport | None = Field(
        default=None, description="Catalog's data, where Catalog runs beside ID."
    )
    tokens: TokenBalance | None = Field(
        default=None, description="The person's own balance of TrainMeet tokens (#79)."
    )
