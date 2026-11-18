"""Väntande vagnparker (#57, CAT-204): an old TrainCatalog owner's fleet, waiting for its person.

The move (catalog/flytten.py) puts each old owner's fleet under an owner of its own in Catalog,
since Catalog's owner is the person's id in TrainMeet ID and the person may not have logged in
there yet. Beside it is a keyed hash of the old verified e-mail address: HMAC-SHA256 with a
pepper that only the environment has (CATALOG_FLYTT_PEPPER, catalog/settings.py). The address
itself is never stored, and the pepper is never written in code or logs, so a copy of the
database cannot tell whose fleet is waiting, not even by hashing addresses one tries.

When a person logs in with TrainMeet ID and ID says the e-mail address is verified, its hash is
looked up. A fleet waiting under it becomes the person's in one transaction: the vehicles with
their history, the pictures, which count in the person's storage from then on, the tags with
their links and events, and the places. Then the waiting owner goes, and its hash with it. An
address that is not verified claims nothing.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from uuid import UUID

from catalog.db import Database

WAITING_NAME = "Väntande vagnpark"
"""The waiting owner's name. Never shown to anyone: its fleet shows no name (CAT-101)."""


def normalise(email: str) -> str:
    """The address as the old TrainCatalog and TrainMeet ID both keep it: trimmed, lower case."""
    return email.strip().lower()


def email_hash(pepper: bytes, email: str) -> bytes:
    """The keyed hash of a verified e-mail address: 32 bytes."""
    return hmac.new(pepper, normalise(email).encode("utf-8"), hashlib.sha256).digest()


@dataclass(frozen=True)
class Claimed:
    """A waiting fleet that became the person's."""

    waiting: UUID
    """The waiting owner it came from, now gone."""
    vehicles: int


def claim(db: Database, person: UUID, hashed: bytes) -> Claimed | None:
    """The fleet waiting under the hash becomes the person's, in one transaction, or nothing
    happens. The person's row must exist: the login makes it first (catalog/login.py)."""
    with db.transaction() as conn:
        found = conn.execute(
            "SELECT owner_id FROM waiting_fleet WHERE email_hash = %s", (hashed,)
        ).fetchone()
        if found is None or found["owner_id"] == person:
            return None
        waiting: UUID = found["owner_id"]
        # Both owners' rows first, in the order of their ids (CAT-40). Another login of the
        # same person that came first has taken the fleet, and the waiting row is gone.
        locked = conn.execute(
            "SELECT id FROM owner WHERE id = ANY(%s) ORDER BY id FOR UPDATE", ([person, waiting],)
        ).fetchall()
        if len(locked) != 2:
            return None
        ids = {"person": person, "waiting": waiting}
        # A place with a name the person already has is the person's place.
        conn.execute(
            "UPDATE vehicle v SET place_id = mine.id FROM place theirs "
            "JOIN place mine ON mine.owner_id = %(person)s AND mine.name = theirs.name "
            "WHERE theirs.owner_id = %(waiting)s AND v.place_id = theirs.id",
            ids,
        )
        conn.execute(
            "DELETE FROM place theirs USING place mine WHERE theirs.owner_id = %(waiting)s "
            "AND mine.owner_id = %(person)s AND mine.name = theirs.name",
            ids,
        )
        conn.execute("UPDATE place SET owner_id = %(person)s WHERE owner_id = %(waiting)s", ids)
        # A new version, so a card that is open is read again (CAT-63).
        moved = conn.execute(
            "UPDATE vehicle SET owner_id = %(person)s, version = version + 1, updated_at = now() "
            "WHERE owner_id = %(waiting)s",
            ids,
        ).rowcount
        for statement in (
            "UPDATE vehicle_owner SET owner_id = %(person)s WHERE owner_id = %(waiting)s",
            "UPDATE picture SET owner_id = %(person)s WHERE owner_id = %(waiting)s",
            "UPDATE picture SET uploaded_by = %(person)s WHERE uploaded_by = %(waiting)s",
            "UPDATE tag SET owner_id = %(person)s WHERE owner_id = %(waiting)s",
            "UPDATE tag_assignment SET owner_id = %(person)s WHERE owner_id = %(waiting)s",
            "UPDATE tag_event SET by_owner = %(person)s WHERE by_owner = %(waiting)s",
            # A later run of the move adds what is new straight to the person's fleet.
            "UPDATE flytt_map SET new_id = %(person)s::text "
            "WHERE kind = 'owner' AND new_id = %(waiting)s::text",
        ):
            conn.execute(statement, ids)
        # The waiting owner goes, and the hash with it (ON DELETE CASCADE).
        conn.execute("DELETE FROM owner WHERE id = %(waiting)s", ids)
    return Claimed(waiting=waiting, vehicles=moved)
