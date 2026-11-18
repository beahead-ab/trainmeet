"""Förebildskatalogen (#53 del a, CAT-03, CAT-141, CAT-155–CAT-165, CAT-173, CAT-213).

Ported from TrainCatalog's catalog/prototypes.py: the snapshot, the owner's own values and the
checks of what a prototype may hold. The tables are in 0012_forebilder.sql, and the field
register in catalog/prototype_fields.py.

The catalog:
- One shared catalog of the prototypes' type data, for everyone who is logged in (CAT-155).
  Every proposal, a new prototype or a change, is a revision of its own (CAT-159) that waits in
  the review queue. Only reviewed revisions are seen by others: the proposer sees their own,
  and the reviewers the queue (CAT-164).
- The reviewer is a role in TrainMeet ID, asked at every call (CAT-165). A change built on an
  older revision than the reviewed one now cannot be approved, so a review never undoes another.
- Nothing about who proposed is shown to others than the reviewers; the catalog shows the type
  data and the source.

The vehicle:
- A link keeps a snapshot of the revision's type data, name, kind and profile (CAT-160). A new
  revision never changes it: the card says that a newer one exists, and the owner updates by
  linking again (CAT-161).
- The owner's own values are kept apart, in prototype_overrides, and the prototype never
  overwrites them. A value equal to the snapshot's is not one of them (CAT-162), also after an
  update. Unlinking takes the type data away; the core fields are the owner's and stay.
- Every write locks the owner's row first and then the vehicle (CAT-40), and raises the
  vehicle's version; a change built on an older version is refused (CAT-63).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from catalog.access import Work
from catalog.db import Database
from catalog.fleet import Fleet, Refused, changed, not_found
from catalog.prototype_fields import PROFILES, BadTypeData, clean
from contracts.catalog import (
    FieldProfile,
    ProblemCode,
    Prototype,
    PrototypeLink,
    PrototypeList,
    PrototypeOverrides,
    PrototypeProposal,
    PrototypeReview,
    PrototypeRevision,
    PrototypeSource,
    PrototypeStatus,
    PrototypeSummary,
    ReviewDecision,
    Vehicle,
    VehicleKind,
    VehiclePrototype,
)

Reviewer = Callable[[UUID], bool]
"""Is the person a reviewer, as TrainMeet ID says now (CAT-165)? Refused with 503 when ID does
not answer."""

MOST: Final = 500
"""Rows in one answer. The catalog is searched, not paged, until it grows past it."""

_REVISION: Final = (
    "r.id, r.prototype_id, r.number, r.base, r.review, r.name, r.kind, r.profile, r.fields, "
    "r.source_kind, r.source, r.created_by, r.created_at, r.comment, r.reviewed_at, "
    "o.name AS proposer"
)
_REVISIONS: Final = "prototype_revision r LEFT JOIN owner o ON o.id = r.created_by"
_SQUEEZED: Final = "lower(regexp_replace(coalesce(r.fields->>'{0}', ''), '[[:space:]]', '', 'g'))"


def no_prototype() -> Refused:
    return Refused(404, ProblemCode.NOT_FOUND, "Förebilden finns inte.")


def not_reviewer() -> Refused:
    return Refused(403, ProblemCode.FORBIDDEN, "Bara granskare granskar förebilder.")


def _bad(error: BadTypeData) -> Refused:
    return Refused(422, ProblemCode.BAD_TYPE_DATA, str(error))


def squeezed(text: str) -> str:
    """Litt and operator as they are matched: case and spaces do not matter (CAT-141)."""
    return "".join(text.split()).lower()


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _revision(row: Mapping[str, Any], person: UUID, *, named: bool = False) -> PrototypeRevision:
    mine = row["created_by"] == person
    return PrototypeRevision(
        id=row["id"],
        prototype=row["prototype_id"],
        number=row["number"],
        base=row["base"],
        status=PrototypeStatus(row["review"]),
        name=row["name"],
        kind=row["kind"],
        profile=FieldProfile(row["profile"]),
        fields=row["fields"],
        source=PrototypeSource(kind=row["source_kind"], text=row["source"]),
        mine=mine,
        proposed_by=row["proposer"] if (named or mine) else None,
        created_at=row["created_at"],
        comment=row["comment"],
        reviewed_at=row["reviewed_at"],
    )


def suggest(conn: Connection[DictRow], litt: str, operator: str) -> PrototypeSummary | None:
    """The reviewed prototype whose litt and operator are these, regardless of case and spaces
    (CAT-141). The one most vehicles are linked to, then the latest reviewed, when there are
    several. None without both."""
    wanted = (squeezed(litt), squeezed(operator))
    if not all(wanted) or "?" in wanted[0]:
        return None
    row = conn.execute(
        "SELECT p.id, r.name, r.number FROM prototype p JOIN prototype_revision r "
        "ON r.prototype_id = p.id AND r.number = p.current_revision "
        f"WHERE p.status = 'reviewed' AND {_SQUEEZED.format('litt')} = %s "
        f"AND {_SQUEEZED.format('operator')} = %s "
        "ORDER BY (SELECT count(*) FROM vehicle v WHERE v.prototype_id = p.id) DESC, "
        "r.reviewed_at DESC, p.id LIMIT 1",
        wanted,
    ).fetchone()
    if row is None:
        return None
    return PrototypeSummary(id=row["id"], name=row["name"], revision=row["number"])


def linked(conn: Connection[DictRow], vehicles: list[UUID]) -> dict[UUID, VehiclePrototype]:
    """The vehicles' links, for the card (catalog/fleet.py reads them with the vehicles)."""
    rows = conn.execute(
        "SELECT v.id, v.prototype_id, v.prototype_revision, v.prototype_snapshot, "
        "v.prototype_overrides, p.current_revision FROM vehicle v "
        "JOIN prototype p ON p.id = v.prototype_id WHERE v.id = ANY(%s)",
        (vehicles,),
    ).fetchall()
    found: dict[UUID, VehiclePrototype] = {}
    for row in rows:
        snapshot: dict[str, Any] = row["prototype_snapshot"]
        own: dict[str, str] = row["prototype_overrides"]
        shown = {**snapshot["fields"], **own}
        found[row["id"]] = VehiclePrototype(
            id=row["prototype_id"],
            name=snapshot["name"],
            kind=snapshot.get("kind"),
            profile=FieldProfile(snapshot["profile"]),
            revision=row["prototype_revision"],
            snapshot=snapshot["fields"],
            overrides=own,
            fields={key: value for key, value in shown.items() if value},
            latest=row["current_revision"],
            newer=row["current_revision"] > row["prototype_revision"],
        )
    return found


class Prototypes:
    def __init__(self, db: Database, fleet: Fleet, reviewer: Reviewer) -> None:
        self.db = db
        self.fleet = fleet
        self.reviewer = reviewer

    def _may_review(self, person: UUID) -> bool:
        """For what is only shown to reviewers: no when ID does not answer."""
        try:
            return self.reviewer(person)
        except Refused:
            return False

    # --- The catalog (CAT-173) -----------------------------------------------------------------

    _PROTOTYPE: Final = (
        "SELECT p.id, p.status, p.current_revision, p.created_at, r.name, r.kind, r.profile, "
        "r.fields, r.source_kind, r.source, r.reviewed_at, r.created_by, "
        "(SELECT count(*) FROM vehicle v WHERE v.prototype_id = p.id) AS vehicles, "
        "(SELECT count(*) FROM prototype_revision w WHERE w.prototype_id = p.id "
        "AND w.review = 'proposed' AND (w.created_by = %(person)s OR %(reviewer)s)) AS waiting "
        "FROM prototype p JOIN prototype_revision r ON r.prototype_id = p.id "
        "AND r.number = coalesce(p.current_revision, 1) "
    )

    @staticmethod
    def _prototype(row: Mapping[str, Any]) -> Prototype:
        return Prototype(
            id=row["id"],
            status=PrototypeStatus(row["status"]),
            revision=row["current_revision"],
            name=row["name"],
            kind=row["kind"],
            profile=FieldProfile(row["profile"]),
            fields=row["fields"],
            source=PrototypeSource(kind=row["source_kind"], text=row["source"]),
            reviewed_at=row["reviewed_at"] if row["current_revision"] is not None else None,
            vehicles=row["vehicles"],
            waiting=row["waiting"],
        )

    def search(
        self, person: UUID, *, q: str = "", kinds: Sequence[VehicleKind] = ()
    ) -> PrototypeList:
        """The reviewed prototypes, and the person's own proposals for new ones, searched on the
        name, the litt, the operator and the description (CAT-173)."""
        reviewer = self._may_review(person)
        where = ["(p.status = 'reviewed' OR (p.status = 'proposed' AND r.created_by = %(person)s))"]
        args: dict[str, Any] = {"person": person, "reviewer": reviewer, "most": MOST}
        text = q.strip()
        if text:
            where.append(
                "(r.name ILIKE %(q)s OR r.fields->>'litt' ILIKE %(q)s "
                "OR r.fields->>'operator' ILIKE %(q)s OR r.fields->>'description' ILIKE %(q)s "
                f"OR {_SQUEEZED.format('litt')} LIKE %(squeezed)s)"
            )
            args["q"] = _like(text)
            args["squeezed"] = _like(squeezed(text))
        if kinds:
            where.append("r.kind = ANY(%(kinds)s)")
            args["kinds"] = [kind.value for kind in kinds]
        with self.db.transaction() as conn:
            rows = conn.execute(
                self._PROTOTYPE + "WHERE " + " AND ".join(where) + " "
                "ORDER BY lower(r.name), p.created_at LIMIT %(most)s",
                args,
            ).fetchall()
            waiting = (
                conn.execute(
                    "SELECT count(*) AS n FROM prototype_revision WHERE review = 'proposed'"
                ).fetchone()
                if reviewer
                else None
            )
        return PrototypeList(
            prototypes=[self._prototype(row) for row in rows],
            reviewer=reviewer,
            to_review=int(waiting["n"]) if waiting else 0,
        )

    def get(self, person: UUID, prototype: UUID) -> Prototype:
        """A prototype with its revisions: the reviewed ones for everyone, and the proposals for
        their proposer and the reviewers (CAT-164)."""
        reviewer = self._may_review(person)
        args = {"person": person, "reviewer": reviewer, "id": prototype}
        with self.db.transaction() as conn:
            row = conn.execute(self._PROTOTYPE + "WHERE p.id = %(id)s", args).fetchone()
            if row is None:
                raise no_prototype()
            if row["status"] != PrototypeStatus.REVIEWED and not (
                reviewer or row["created_by"] == person
            ):
                raise no_prototype()
            revisions = conn.execute(
                f"SELECT {_REVISION} FROM {_REVISIONS} WHERE r.prototype_id = %s "
                "ORDER BY r.number DESC",
                (prototype,),
            ).fetchall()
        shown = [
            _revision(r, person, named=reviewer)
            for r in revisions
            if r["review"] == PrototypeStatus.REVIEWED or reviewer or r["created_by"] == person
        ]
        return self._prototype(row).model_copy(update={"revisions": shown})

    # --- Proposals and the review (CAT-163, CAT-164, CAT-165) ----------------------------------

    def propose(self, person: UUID, proposal: PrototypeProposal) -> PrototypeRevision:
        """A new prototype, or a change of a reviewed one built on its current revision. Either
        way a revision that waits for review."""
        try:
            fields = clean(proposal.profile, proposal.fields)
        except BadTypeData as error:
            raise _bad(error) from None
        with self.db.owner_transaction(person) as conn:
            if proposal.prototype is None:
                if proposal.base is not None:
                    raise no_prototype()
                prototype, number = uuid.uuid4(), 1
                conn.execute("INSERT INTO prototype (id) VALUES (%s)", (prototype,))
            else:
                prototype = proposal.prototype
                found = conn.execute(
                    "SELECT status, current_revision FROM prototype WHERE id = %s FOR UPDATE",
                    (prototype,),
                ).fetchone()
                if found is None or found["status"] != PrototypeStatus.REVIEWED:
                    raise no_prototype()
                if proposal.base != found["current_revision"]:
                    raise Refused(
                        409,
                        ProblemCode.CHANGED,
                        "Förebilden har en nyare revision. Öppna den igen och föreslå "
                        "ändringen där.",
                    )
                last = conn.execute(
                    "SELECT max(number) AS n FROM prototype_revision WHERE prototype_id = %s",
                    (prototype,),
                ).fetchone()
                assert last is not None
                number = int(last["n"]) + 1
            revision = uuid.uuid4()
            conn.execute(
                "INSERT INTO prototype_revision (id, prototype_id, number, base, name, kind, "
                "profile, fields, source_kind, source, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    revision,
                    prototype,
                    number,
                    proposal.base,
                    proposal.name,
                    proposal.kind.value if proposal.kind else None,
                    proposal.profile.value,
                    Jsonb(fields),
                    proposal.source.kind.value,
                    proposal.source.text,
                    person,
                ),
            )
            return self._read_revision(conn, person, revision)

    @staticmethod
    def _read_revision(
        conn: Connection[DictRow], person: UUID, revision: UUID, *, named: bool = False
    ) -> PrototypeRevision:
        row = conn.execute(
            f"SELECT {_REVISION} FROM {_REVISIONS} WHERE r.id = %s", (revision,)
        ).fetchone()
        if row is None:
            raise no_prototype()
        return _revision(row, person, named=named)

    def mine(self, person: UUID) -> list[PrototypeRevision]:
        """The person's own proposals, newest first, with the reviewers' answers."""
        with self.db.transaction() as conn:
            rows = conn.execute(
                f"SELECT {_REVISION} FROM {_REVISIONS} WHERE r.created_by = %s "
                "ORDER BY r.created_at DESC LIMIT %s",
                (person, MOST),
            ).fetchall()
        return [_revision(row, person) for row in rows]

    def queue(self, person: UUID) -> list[PrototypeRevision]:
        """Granskningskön, oldest first: only for reviewers (CAT-164, CAT-165)."""
        if not self.reviewer(person):
            raise not_reviewer()
        with self.db.transaction() as conn:
            rows = conn.execute(
                f"SELECT {_REVISION} FROM {_REVISIONS} WHERE r.review = 'proposed' "
                "ORDER BY r.created_at, r.number LIMIT %s",
                (MOST,),
            ).fetchall()
        return [_revision(row, person, named=True) for row in rows]

    def review(self, person: UUID, revision: UUID, review: PrototypeReview) -> PrototypeRevision:
        """Approve or reject a proposal, with a comment (CAT-164). Approved, it is the revision
        everyone sees; a vehicle linked to an older one keeps its snapshot (CAT-161)."""
        if not self.reviewer(person):
            raise not_reviewer()
        with self.db.owner_transaction(person) as conn:
            found = conn.execute(
                "SELECT p.id, p.status, p.current_revision FROM prototype p "
                "JOIN prototype_revision r ON r.prototype_id = p.id WHERE r.id = %s "
                "FOR UPDATE OF p",
                (revision,),
            ).fetchone()
            if found is None:
                raise no_prototype()
            row = conn.execute(
                "SELECT number, base, review FROM prototype_revision WHERE id = %s FOR UPDATE",
                (revision,),
            ).fetchone()
            assert row is not None
            if row["review"] != PrototypeStatus.PROPOSED:
                raise Refused(409, ProblemCode.CHANGED, "Förslaget är redan granskat.")
            approve = review.decision is ReviewDecision.APPROVE
            if approve and row["base"] != found["current_revision"]:
                raise Refused(
                    409,
                    ProblemCode.CHANGED,
                    "Förebilden har ändrats sedan förslaget. Avslå det, så kan ändringen "
                    "föreslås igen på den nya revisionen.",
                )
            outcome = PrototypeStatus.REVIEWED if approve else PrototypeStatus.REJECTED
            conn.execute(
                "UPDATE prototype_revision SET review = %s, reviewer = %s, comment = %s, "
                "reviewed_at = now() WHERE id = %s",
                (outcome.value, person, review.comment, revision),
            )
            if approve:
                conn.execute(
                    "UPDATE prototype SET status = 'reviewed', current_revision = %s WHERE id = %s",
                    (row["number"], found["id"]),
                )
            elif found["status"] == PrototypeStatus.PROPOSED:
                conn.execute(
                    "UPDATE prototype SET status = 'rejected' WHERE id = %s", (found["id"],)
                )
            return self._read_revision(conn, person, revision, named=True)

    # --- The vehicle's link (CAT-160, CAT-161, CAT-162) -----------------------------------------

    def _lock(
        self, conn: Connection[DictRow], work: Work, vehicle: UUID, version: int
    ) -> Mapping[str, Any]:
        """The vehicle, locked after the owner's row, at the version the change was built on."""
        row = conn.execute(
            "SELECT version, prototype_id, prototype_snapshot, prototype_overrides FROM vehicle "
            "WHERE id = %s AND owner_id = %s FOR UPDATE",
            (vehicle, work.owner),
        ).fetchone()
        if row is None:
            raise not_found()
        if row["version"] != version:
            raise changed()
        return row

    def _read(self, conn: Connection[DictRow], work: Work, vehicle: UUID) -> Vehicle:
        return self.fleet.read_many(conn, work.owner, [vehicle])[vehicle]

    def link(self, work: Work, vehicle: UUID, link: PrototypeLink) -> Vehicle:
        """Koppla förebild, or Uppdatera: the vehicle gets a snapshot of a reviewed revision
        (CAT-160). Linked to the same prototype already, the owner's own values are kept, but a
        value now equal to the prototype's is no longer one of them (CAT-162)."""
        with self.db.owner_transaction(work.owner) as conn:
            current = self._lock(conn, work, vehicle, link.version)
            revision = conn.execute(
                "SELECT name, kind, profile, fields FROM prototype_revision "
                "WHERE prototype_id = %s AND number = %s AND review = 'reviewed'",
                (link.prototype, link.revision),
            ).fetchone()
            if revision is None:
                raise no_prototype()
            snapshot = {
                "name": revision["name"],
                "kind": revision["kind"],
                "profile": revision["profile"],
                "fields": revision["fields"],
            }
            kept: dict[str, str] = (
                current["prototype_overrides"] if current["prototype_id"] == link.prototype else {}
            )
            own = {k: v for k, v in kept.items() if v != revision["fields"].get(k, "")}
            conn.execute(
                "UPDATE vehicle SET prototype_id = %s, prototype_revision = %s, "
                "prototype_snapshot = %s, prototype_overrides = %s, version = version + 1, "
                "updated_at = now() WHERE id = %s",
                (link.prototype, link.revision, Jsonb(snapshot), Jsonb(own), vehicle),
            )
            return self._read(conn, work, vehicle)

    def override(self, work: Work, vehicle: UUID, given: PrototypeOverrides) -> Vehicle:
        """The type data as the owner wants them on the vehicle (CAT-162). A value equal to the
        snapshot's inherits, any other is the owner's own, an empty one too. Own values for keys
        outside the snapshot's profile, from an earlier link, are kept as they are."""
        with self.db.owner_transaction(work.owner) as conn:
            current = self._lock(conn, work, vehicle, given.version)
            snapshot = current["prototype_snapshot"]
            if snapshot is None:
                raise Refused(
                    409, ProblemCode.CHANGED, "Fordonet har ingen förebild längre. Öppna det igen."
                )
            profile = FieldProfile(snapshot["profile"])
            try:
                wanted = clean(profile, given.fields, empty=True)
            except BadTypeData as error:
                raise _bad(error) from None
            keys = PROFILES[profile].keys
            own = {k: v for k, v in current["prototype_overrides"].items() if k not in keys} | {
                k: v for k, v in wanted.items() if v != snapshot["fields"].get(k, "")
            }
            conn.execute(
                "UPDATE vehicle SET prototype_overrides = %s, version = version + 1, "
                "updated_at = now() WHERE id = %s",
                (Jsonb(own), vehicle),
            )
            return self._read(conn, work, vehicle)

    def unlink(self, work: Work, vehicle: UUID, version: int) -> Vehicle:
        """Koppla bort: the type data go from the vehicle; its core fields stay."""
        with self.db.owner_transaction(work.owner) as conn:
            current = self._lock(conn, work, vehicle, version)
            if current["prototype_id"] is not None:
                conn.execute(
                    "UPDATE vehicle SET prototype_id = NULL, prototype_revision = NULL, "
                    "prototype_snapshot = NULL, prototype_overrides = '{}', "
                    "version = version + 1, updated_at = now() WHERE id = %s",
                    (vehicle,),
                )
            return self._read(conn, work, vehicle)
