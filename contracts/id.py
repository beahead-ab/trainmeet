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
    GET    /api/id/1/clubs/{club}                         ClubPage
    POST   /api/id/1/clubs/{club}/invitations             Invite -> Invitation
    DELETE /api/id/1/clubs/{club}/members/{person}        ClubPage; admin removes, member leaves
    GET    /api/id/1/fleets/{owner}                       FleetPage; the owner's sharing
    POST   /api/id/1/fleets/{owner}/invitations           FleetInvite -> Invitation
    DELETE /api/id/1/grants/{grant}                       Removed; stop sharing, takes a role
    GET    /api/id/1/invitations                          [Invitation] to the person
    POST   /api/id/1/invitations/{invitation}/answer      Answer -> Invitation
    DELETE /api/id/1/invitations/{invitation}             Removed; the inviter takes it back

For the apps, with an access token from Keycloak's client credentials (KONTO-34):
    GET    /api/id/1/apps/access?person=&resource=        Access
    GET    /api/id/1/apps/fleets?person=                  [FleetAccess], the fleets shared with

Rules:
- Every changing call checks on the server who asks (CAT-195 for ID).
- A role always applies to one resource (KONTO-03). The resource's owner, or the admin of the
  club that owns it, hands out its roles (KONTO-36).
- An invitation gives nothing until the person it was sent to has said yes, logged in with the
  same verified address (KONTO-29, KONTO-35, CAT-45).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from contracts.common import Contract, Text

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


class Session(Contract):
    account: Account | None = None
    logout_url: str | None = Field(
        default=None,
        description="Only in the answer to logging out: where the browser goes next.",
    )


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


class ClubPage(Contract):
    """A club as its members see it. Only the admin sees the waiting invitations."""

    club: Club
    members: list[Member]
    invitations: list[Invitation] = Field(default_factory=list)


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


class Answer(Contract):
    accept: bool


class Removed(Contract):
    id: UUID


class Access(Contract):
    """What ID says now: the roles a person has for a resource (KONTO-34). Empty: none."""

    person: UUID
    resource: Resource
    roles: list[Role]


class FleetAccess(Contract):
    """A fleet that is shared with the person, and how (CAT-50)."""

    owner: Resource = Field(description="Kind fleet: the owner's id, a person's or a club's.")
    title: Text = Field(description="Whose fleet it is, as the owner shows it.")
    role: FleetRole


class ProblemCode(StrEnum):
    LOGIN = "login"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    INVALID = "invalid"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


class Problem(Contract):
    code: ProblemCode
    message: Text
