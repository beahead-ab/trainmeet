"""The clubs, the shared fleets and the roles per resource in ID's API (#67).

The rules (KONTO-03, KONTO-29, KONTO-35, KONTO-36, CAT-44, CAT-45):
- A role always applies to one resource. A club's members are roles on the club.
- The one who creates a club becomes its admin. Members are invited with their address and are
  in when they say yes. The admin removes members, and a member can leave. A club always keeps
  an admin.
- A fleet is shared by its owner, or by the admin of the club that owns it, with one person to
  look at or to edit. The sharing applies when that person has said yes.
- An invitation gives nothing until it is answered by someone logged in with the very address
  it was sent to, verified by ID (KONTO-10).
- Whoever may not see a resource gets 404, and whoever sees it but may not do this gets 403.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from psycopg import Connection
from psycopg.errors import UniqueViolation
from psycopg.rows import DictRow

from contracts.id import (
    Access,
    Account,
    Club,
    ClubPage,
    ClubRole,
    FleetAccess,
    FleetAccessRole,
    FleetPage,
    FleetRole,
    Grant,
    Invitation,
    InvitationState,
    Member,
    Person,
    ProblemCode,
    Removed,
    Resource,
    ResourceKind,
    Role,
)
from id.db import Database

LOGGER = logging.getLogger("id.roles")


class Refused(Exception):
    """ID says no. The status and the code go to the caller, the message to the person."""

    def __init__(self, status: int, code: ProblemCode, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def not_found() -> Refused:
    return Refused(404, ProblemCode.NOT_FOUND, "Finns inte.")


def forbidden(message: str) -> Refused:
    return Refused(403, ProblemCode.FORBIDDEN, message)


def initials(name: str) -> str:
    parts = [part for part in name.split() if part[:1].isalnum()]
    return "".join(part[0] for part in parts[:2]).upper() or "?"


def hidden(email: str) -> str:
    """An address as others see it: k***@example.com."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


class Mailer(Protocol):
    def invitation(self, to: str, title: str, sender: str, link: str) -> None: ...


@dataclass(frozen=True)
class Asker:
    """The person who asks, as the session says."""

    id: UUID
    email: str


class Roles:
    def __init__(self, db: Database, mailer: Mailer, public_url: str) -> None:
        self.db = db
        self.mailer = mailer
        self.public_url = public_url.rstrip("/")

    # --- People -----------------------------------------------------------------------------

    def seen(self, account: Account) -> None:
        """Keeps the person's name and address as ID says them at login."""
        with self.db.transaction() as conn:
            # An address moved to another account in Keycloak leaves the old row without it.
            conn.execute(
                "UPDATE person SET email = 'gammal-' || id || '@ingen.invalid' "
                "WHERE email = %s AND id <> %s",
                (account.email, account.id),
            )
            conn.execute(
                "INSERT INTO person (id, name, email) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET name = excluded.name, email = excluded.email, "
                "seen_at = now()",
                (account.id, account.name, account.email),
            )

    @staticmethod
    def _person(row: dict[str, Any], prefix: str = "") -> Person:
        name = str(row[prefix + "name"])
        return Person(id=row[prefix + "id"], name=name, initials=initials(name))

    # --- Clubs ------------------------------------------------------------------------------

    def clubs(self, asker: Asker) -> list[Club]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT club.id, club.name, g.role FROM role_grant g "
                "JOIN club ON club.id::text = g.resource_id "
                "WHERE g.resource_kind = 'club' AND g.person_id = %s "
                "AND g.role IN ('admin', 'member') ORDER BY lower(club.name), g.role",
                (asker.id,),
            ).fetchall()
        found: dict[UUID, Club] = {}
        for row in rows:
            if row["id"] not in found:  # admin before member
                found[row["id"]] = Club(id=row["id"], name=row["name"], role=ClubRole(row["role"]))
        return list(found.values())

    def create_club(self, asker: Asker, name: str) -> Club:
        club = uuid.uuid4()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO club (id, name, created_by) VALUES (%s, %s, %s)",
                (club, name, asker.id),
            )
            self._grant(
                conn, asker.id, Role.ADMIN, Resource(kind=ResourceKind.CLUB, id=str(club)), asker.id
            )
        return Club(id=club, name=name, role=ClubRole.ADMIN)

    def _club_role(self, conn: Connection[DictRow], asker: Asker, club: UUID) -> Role:
        """The asker's role in the club, or 404: a club is only seen by its members (KONTO-17)."""
        row = conn.execute(
            "SELECT role FROM role_grant WHERE resource_kind = 'club' AND resource_id = %s "
            "AND person_id = %s AND role IN ('admin', 'member') ORDER BY role LIMIT 1",
            (str(club), asker.id),
        ).fetchone()
        if row is None:
            raise not_found()
        return Role(row["role"])

    def club_page(self, asker: Asker, club: UUID) -> ClubPage:
        with self.db.transaction() as conn:
            role = self._club_role(conn, asker, club)
            return self._club_page(conn, club, role)

    def _club_page(self, conn: Connection[DictRow], club: UUID, role: Role) -> ClubPage:
        row = conn.execute("SELECT id, name FROM club WHERE id = %s", (club,)).fetchone()
        if row is None:
            raise not_found()
        members = conn.execute(
            "SELECT person.id, person.name, g.role, g.at FROM role_grant g "
            "JOIN person ON person.id = g.person_id WHERE g.resource_kind = 'club' "
            "AND g.resource_id = %s AND g.role IN ('admin', 'member') "
            "ORDER BY g.role, lower(person.name)",
            (str(club),),
        ).fetchall()
        seen: set[UUID] = set()
        listed: list[Member] = []
        for member in members:
            if member["id"] in seen:
                continue
            seen.add(member["id"])
            listed.append(
                Member(
                    person=self._person(member),
                    role=ClubRole(member["role"]),
                    since=member["at"],
                )
            )
        resource = Resource(kind=ResourceKind.CLUB, id=str(club))
        invitations = self._invitations(conn, resource) if role == Role.ADMIN else []
        return ClubPage(
            club=Club(id=row["id"], name=row["name"], role=ClubRole(role.value)),
            members=listed,
            invitations=invitations,
        )

    def invite_to_club(self, asker: Asker, club: UUID, email: str) -> Invitation:
        with self.db.transaction() as conn:
            if self._club_role(conn, asker, club) != Role.ADMIN:
                raise forbidden("Bara klubbens administratör bjuder in.")
            row = conn.execute("SELECT name FROM club WHERE id = %s", (club,)).fetchone()
            assert row is not None
            resource = Resource(kind=ResourceKind.CLUB, id=str(club))
            if self._has_person_with(conn, resource, email, (Role.ADMIN, Role.MEMBER)):
                raise Refused(409, ProblemCode.CONFLICT, "Adressen är redan medlem i klubben.")
            return self._invite(conn, asker, resource, Role.MEMBER, str(row["name"]), email)

    def remove_member(self, asker: Asker, club: UUID, member: UUID) -> ClubPage | None:
        """The admin removes a member, or a member leaves. None: the asker has left."""
        with self.db.transaction() as conn:
            role = self._club_role(conn, asker, club)
            if member != asker.id and role != Role.ADMIN:
                raise forbidden("Bara klubbens administratör tar bort medlemmar.")
            resource = Resource(kind=ResourceKind.CLUB, id=str(club))
            conn.execute("SELECT id FROM club WHERE id = %s FOR UPDATE", (club,))
            admins = conn.execute(
                "SELECT person_id FROM role_grant WHERE resource_kind = 'club' "
                "AND resource_id = %s AND role = 'admin'",
                (str(club),),
            ).fetchall()
            if [a["person_id"] for a in admins] == [member]:
                raise Refused(
                    409,
                    ProblemCode.CONFLICT,
                    "Klubben behöver en administratör. Ge rollen till någon annan först.",
                )
            gone = conn.execute(
                "DELETE FROM role_grant WHERE resource_kind = 'club' AND resource_id = %s "
                "AND person_id = %s AND role IN ('admin', 'member') RETURNING id",
                (resource.id, member),
            ).fetchall()
            if not gone:
                raise not_found()
            if member == asker.id:
                return None
            return self._club_page(conn, club, role)

    # --- Fleets (CAT-44, KONTO-29) -----------------------------------------------------------

    def _fleet_title(self, conn: Connection[DictRow], asker: Asker, owner: UUID) -> str:
        """Whose fleet it is, if the asker may share it; otherwise 404 or 403 (KONTO-36)."""
        if owner == asker.id:
            row = conn.execute("SELECT name FROM person WHERE id = %s", (owner,)).fetchone()
            return f"Vagnparken · {row['name']}" if row else "Vagnparken"
        club = conn.execute("SELECT name FROM club WHERE id = %s", (owner,)).fetchone()
        if club is None:
            raise not_found()
        if self._club_role(conn, asker, owner) != Role.ADMIN:
            raise forbidden("Bara klubbens administratör delar klubbens vagnpark.")
        return f"Vagnparken · {club['name']}"

    def fleet_page(self, asker: Asker, owner: UUID) -> FleetPage:
        with self.db.transaction() as conn:
            title = self._fleet_title(conn, asker, owner)
            resource = Resource(kind=ResourceKind.FLEET, id=str(owner))
            return FleetPage(
                owner=resource,
                title=title,
                grants=self._grants(conn, resource),
                invitations=self._invitations(conn, resource),
            )

    def invite_to_fleet(self, asker: Asker, owner: UUID, email: str, role: FleetRole) -> Invitation:
        with self.db.transaction() as conn:
            title = self._fleet_title(conn, asker, owner)
            if email == asker.email:
                raise Refused(422, ProblemCode.INVALID, "Det är din egen adress.")
            resource = Resource(kind=ResourceKind.FLEET, id=str(owner))
            if self._has_person_with(conn, resource, email, (Role.VIEWER, Role.EDITOR)):
                raise Refused(
                    409, ProblemCode.CONFLICT, "Vagnparken är redan delad med den adressen."
                )
            return self._invite(conn, asker, resource, Role(role.value), title, email)

    def remove_grant(self, asker: Asker, grant: UUID) -> Removed:
        """Stop sharing: the owner or the club's admin takes the role, or its holder drops it.
        It applies at once, since the apps ask ID at every call (CAT-48)."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT person_id, role, resource_kind, resource_id FROM role_grant WHERE id = %s",
                (grant,),
            ).fetchone()
            if row is None:
                raise not_found()
            if row["resource_kind"] != "fleet":
                raise forbidden("Den här rollen tas bort där den delades ut.")
            if row["person_id"] != asker.id:
                self._fleet_title(conn, asker, UUID(row["resource_id"]))
            conn.execute("DELETE FROM role_grant WHERE id = %s", (grant,))
        return Removed(id=grant)

    # --- Invitations --------------------------------------------------------------------------

    def _invite(
        self,
        conn: Connection[DictRow],
        asker: Asker,
        resource: Resource,
        role: Role,
        title: str,
        email: str,
    ) -> Invitation:
        invitation = uuid.uuid4()
        try:
            with conn.transaction():
                row = conn.execute(
                    "INSERT INTO invitation (id, resource_kind, resource_id, role, title, email, "
                    "sent_by) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING at",
                    (
                        invitation,
                        resource.kind.value,
                        resource.id,
                        role.value,
                        title,
                        email,
                        asker.id,
                    ),
                ).fetchone()
        except UniqueViolation as error:
            raise Refused(
                409, ProblemCode.CONFLICT, "Adressen har redan en inbjudan som väntar."
            ) from error
        assert row is not None
        sender = conn.execute("SELECT id, name FROM person WHERE id = %s", (asker.id,)).fetchone()
        assert sender is not None
        self.mailer.invitation(email, title, str(sender["name"]), self.public_url + "/inbjudningar")
        return Invitation(
            id=invitation,
            resource=resource,
            role=role,
            title=title,
            sent_to=email,
            sent_by=self._person(sender),
            state=InvitationState.WAITING,
            at=row["at"],
        )

    def _invitation(self, row: dict[str, Any], show: bool) -> Invitation:
        return Invitation(
            id=row["id"],
            resource=Resource(kind=ResourceKind(row["resource_kind"]), id=row["resource_id"]),
            role=Role(row["role"]),
            title=row["title"],
            sent_to=row["email"] if show else hidden(row["email"]),
            sent_by=Person(
                id=row["sender_id"], name=row["sender_name"], initials=initials(row["sender_name"])
            ),
            state=InvitationState(row["state"]),
            at=row["at"],
        )

    _INVITATION = (
        "SELECT i.id, i.resource_kind, i.resource_id, i.role, i.title, i.email, i.state, i.at, "
        "p.id AS sender_id, p.name AS sender_name FROM invitation i "
        "JOIN person p ON p.id = i.sent_by "
    )

    def _invitations(self, conn: Connection[DictRow], resource: Resource) -> list[Invitation]:
        rows = conn.execute(
            self._INVITATION + "WHERE i.resource_kind = %s AND i.resource_id = %s "
            "AND i.state = 'waiting' ORDER BY i.at",
            (resource.kind.value, resource.id),
        ).fetchall()
        # The one sharing knows the address; the page shows it partly hidden all the same.
        return [self._invitation(row, show=False) for row in rows]

    def invitations_for(self, asker: Asker) -> list[Invitation]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                self._INVITATION + "WHERE i.email = %s AND i.state = 'waiting' ORDER BY i.at",
                (asker.email,),
            ).fetchall()
        return [self._invitation(row, show=True) for row in rows]

    def answer(self, asker: Asker, invitation: UUID, accept: bool) -> Invitation:
        with self.db.transaction() as conn:
            row = conn.execute(
                self._INVITATION + "WHERE i.id = %s FOR UPDATE OF i", (invitation,)
            ).fetchone()
            # Someone else's invitation is not even seen (CAT-45).
            if row is None or row["email"] != asker.email:
                raise not_found()
            if row["state"] != "waiting":
                raise Refused(409, ProblemCode.CONFLICT, "Inbjudan är redan besvarad.")
            state = InvitationState.ACCEPTED if accept else InvitationState.DECLINED
            conn.execute(
                "UPDATE invitation SET state = %s, answered_at = now() WHERE id = %s",
                (state.value, invitation),
            )
            if accept:
                resource = Resource(kind=ResourceKind(row["resource_kind"]), id=row["resource_id"])
                self._grant(conn, asker.id, Role(row["role"]), resource, row["sender_id"])
            return self._invitation({**row, "state": state.value}, show=True)

    def withdraw(self, asker: Asker, invitation: UUID) -> Removed:
        """The sender, or whoever may share the resource, takes back a waiting invitation."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT sent_by, resource_kind, resource_id, state FROM invitation WHERE id = %s",
                (invitation,),
            ).fetchone()
            if row is None or row["state"] != "waiting":
                raise not_found()
            if row["sent_by"] != asker.id:
                resource_id = UUID(row["resource_id"])
                if row["resource_kind"] == "club":
                    if self._club_role(conn, asker, resource_id) != Role.ADMIN:
                        raise forbidden("Bara klubbens administratör tar tillbaka inbjudningar.")
                else:
                    self._fleet_title(conn, asker, resource_id)
            conn.execute("DELETE FROM invitation WHERE id = %s", (invitation,))
        return Removed(id=invitation)

    # --- Grants -----------------------------------------------------------------------------

    def _grant(
        self, conn: Connection[DictRow], person: UUID, role: Role, resource: Resource, by: UUID
    ) -> None:
        conn.execute(
            "INSERT INTO role_grant (id, person_id, role, resource_kind, resource_id, granted_by) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (uuid.uuid4(), person, role.value, resource.kind.value, resource.id, by),
        )

    def _grants(self, conn: Connection[DictRow], resource: Resource) -> list[Grant]:
        rows = conn.execute(
            "SELECT g.id AS grant_id, g.role, g.at, p.id, p.name FROM role_grant g "
            "JOIN person p ON p.id = g.person_id WHERE g.resource_kind = %s AND g.resource_id = %s "
            "ORDER BY lower(p.name), g.role",
            (resource.kind.value, resource.id),
        ).fetchall()
        return [
            Grant(
                id=row["grant_id"],
                person=self._person(row),
                role=Role(row["role"]),
                resource=resource,
                at=row["at"],
            )
            for row in rows
        ]

    @staticmethod
    def _has_person_with(
        conn: Connection[DictRow], resource: Resource, email: str, roles: tuple[Role, ...]
    ) -> bool:
        row = conn.execute(
            "SELECT 1 FROM role_grant g JOIN person p ON p.id = g.person_id "
            "WHERE g.resource_kind = %s AND g.resource_id = %s AND p.email = %s "
            "AND g.role = ANY(%s)",
            (resource.kind.value, resource.id, email, [r.value for r in roles]),
        ).fetchone()
        return row is not None

    # --- What the apps ask (KONTO-34) ---------------------------------------------------------

    def access(self, person: UUID, resource: Resource) -> Access:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT DISTINCT role FROM role_grant WHERE person_id = %s "
                "AND resource_kind = %s AND resource_id = %s",
                (person, resource.kind.value, resource.id),
            ).fetchall()
            roles = {Role(r["role"]) for r in rows}
            if resource.kind == ResourceKind.FLEET:
                # A club's fleet: the club's roles count (CAT-51, C36).
                club = conn.execute(
                    "SELECT role FROM role_grant WHERE resource_kind = 'club' "
                    "AND resource_id = %s AND person_id = %s AND role IN ('admin', 'member')",
                    (resource.id, person),
                ).fetchall()
                for row in club:
                    roles.add(Role.ADMIN if row["role"] == "admin" else Role.VIEWER)
        return Access(person=person, resource=resource, roles=sorted(roles))

    def fleets_for(self, person: UUID) -> list[FleetAccess]:
        """The fleets the person may work in besides their own: shared with them, and their
        clubs' (CAT-50, CAT-51). The strongest right counts."""
        strength = {FleetAccessRole.VIEWER: 1, FleetAccessRole.EDITOR: 2, FleetAccessRole.OWNER: 3}
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT g.resource_id AS owner, g.role, coalesce(c.name, p.name) AS whose "
                "FROM role_grant g LEFT JOIN club c ON c.id::text = g.resource_id "
                "LEFT JOIN person p ON p.id::text = g.resource_id "
                "WHERE g.person_id = %s AND g.resource_kind = 'fleet' "
                "AND g.role IN ('viewer', 'editor') "
                "UNION ALL "
                "SELECT c.id::text, "
                "CASE g.role WHEN 'admin' THEN 'owner' ELSE 'viewer' END, c.name "
                "FROM role_grant g JOIN club c ON c.id::text = g.resource_id "
                "WHERE g.person_id = %s AND g.resource_kind = 'club' "
                "AND g.role IN ('admin', 'member')",
                (person, person),
            ).fetchall()
        found: dict[str, FleetAccess] = {}
        for row in rows:
            role = FleetAccessRole(row["role"])
            current = found.get(row["owner"])
            if current is None or strength[role] > strength[current.role]:
                found[row["owner"]] = FleetAccess(
                    owner=Resource(kind=ResourceKind.FLEET, id=row["owner"]),
                    title=f"Vagnparken · {row['whose'] or 'okänd'}",
                    role=role,
                )
        return sorted(found.values(), key=lambda f: f.title.lower())
