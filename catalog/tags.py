"""The tags and the lookup (#54, CAT-78–CAT-122). TrainCatalog's tag model, ported (C14).

A tag has identifiers that are unique in all of Catalog. A link between a tag and a vehicle
has a start and an end; the database keeps at most one active link per tag, and per vehicle at
most one NFC (or simulated) tag and one QR label. Every write locks the owner's row first,
then the vehicle and the tag (CAT-40). The first registration of a physical tag takes a lock
per serial number, so two owners never both get the same new tag (CAT-85).

The lookup answers from an exact whitelist per outcome, never from the owner's vehicle
(CAT-107). Nobody's taps are kept (CAT-110): the only trace is a count per person and minute.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import re
import secrets
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import segno
from psycopg import Connection
from psycopg.rows import DictRow

from catalog.db import Database
from catalog.fleet import Refused, not_found
from contracts.catalog import (
    Lookup,
    LookupFleet,
    LookupMine,
    LookupPrivate,
    LookupShared,
    LookupUnknown,
    MiniCard,
    PendingLink,
    PendingState,
    ProblemCode,
    Tag,
    TagEvent,
    TagKind,
    TagLink,
    TagUnlink,
    VehicleKind,
)

LOOKUPS_PER_MINUTE = 30
PENDING_MINUTES = 10
_HEX = re.compile(r"[0-9a-f]{2}(?:[:\-]?[0-9a-f]{2}){3,15}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# A QR label's id starts with q, which no hex serial number does, and avoids letters and
# digits that are easy to mix up when read aloud.
_QR = re.compile(r"q[a-hjkmnp-z2-9]{11}")
_QR_LETTERS = "abcdefghjkmnpqrstuvwxyz23456789"


@dataclass(frozen=True)
class Uid:
    """A tag's identifier: the namespace and the value, as stored (CAT-79)."""

    namespace: str
    value: str

    @property
    def kind(self) -> TagKind:
        return {"iso14443a_uid": TagKind.NFC, "qr": TagKind.QR, "sim": TagKind.SIM}[self.namespace]


def normalize(uid: str) -> Uid:
    """The same tag whatever the case, colons, dashes or a trailing slash (CAT-79, CAT-80)."""
    text = uid.strip().strip("/").lower()
    if text.startswith("sim:"):
        text = text[4:]
    if _UUID.fullmatch(text):
        return Uid("sim", text)
    if _QR.fullmatch(text):
        return Uid("qr", text)
    if _HEX.fullmatch(text):
        return Uid("iso14443a_uid", text.replace(":", "").replace("-", ""))
    raise Refused(
        422,
        ProblemCode.BAD_TAG,
        "Det är inte en taggs adress: ett serienummer i hex, en QR-etikett "
        "eller en simulerad tagg.",
    )


def slot_of(kind: TagKind | str) -> str:
    """NFC and simulated tags share a slot; a QR label has its own (CAT-82)."""
    return "qr" if TagKind(kind) is TagKind.QR else "nfc"


class Limiter:
    """At most 30 lookups a minute per person (CAT-111) or, logged out, per address (CAT-112).

    People are counted in the database, one window each. Addresses are counted here in memory
    under a keyed hash, so no address is ever stored or logged.
    """

    def __init__(self, db: Database, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.db = db
        self.clock = clock
        self._key = secrets.token_bytes(32)
        self._windows: dict[bytes, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def allow_person(self, owner: UUID) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute(
                "INSERT INTO tag_lookup_counter (owner_id, window_start, count) "
                "VALUES (%(o)s, now(), 1) ON CONFLICT (owner_id) DO UPDATE SET "
                "window_start = CASE WHEN tag_lookup_counter.window_start "
                "<= now() - interval '1 minute' THEN now() "
                "ELSE tag_lookup_counter.window_start END, "
                "count = CASE WHEN tag_lookup_counter.window_start "
                "<= now() - interval '1 minute' THEN 1 "
                "ELSE tag_lookup_counter.count + 1 END RETURNING count",
                {"o": owner},
            ).fetchone()
        return row is not None and int(row["count"]) <= LOOKUPS_PER_MINUTE

    def allow_address(self, address: str) -> bool:
        key = hmac.new(self._key, address.encode(), hashlib.sha256).digest()
        now = self.clock()
        with self._lock:
            if len(self._windows) > 10_000:
                self._windows = {k: v for k, v in self._windows.items() if now - v[0] < 60}
            start, count = self._windows.get(key, (now, 0))
            if now - start >= 60:
                start, count = now, 0
            self._windows[key] = (start, count + 1)
            return count + 1 <= LOOKUPS_PER_MINUTE


def _too_many() -> Refused:
    return Refused(429, ProblemCode.TOO_MANY, "För många uppslag. Försök igen om en minut.")


class Tags:
    def __init__(
        self,
        db: Database,
        *,
        base: str,
        simulated: bool,
        shared_with: Callable[[UUID, UUID], str | None] = lambda asker, owner: None,
    ) -> None:
        self.db = db
        self.base = base.rstrip("/") + "/"
        self.simulated = simulated
        self.limiter = Limiter(db)
        # Which right the asker has to the owner's fleet. Sharing comes with TrainMeet ID (#49).
        self.shared_with = shared_with

    def address(self, uid: str) -> str:
        return self.base + uid

    # --- The lookup -------------------------------------------------------------------------

    def lookup(self, asker: UUID | None, uid: str, client_address: str) -> Lookup:
        """What /t/<uid> answers (CAT-98–CAT-112)."""
        allowed = (
            self.limiter.allow_person(asker)
            if asker is not None
            else self.limiter.allow_address(client_address)
        )
        if not allowed:
            raise _too_many()
        found = normalize(uid)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT a.owner_id, o.name AS owner_name, o.show_name, v.id AS vehicle_id, "
                "v.litt, v.number, v.kind, v.operator, v.scale FROM tag_identifier i "
                "JOIN tag_assignment a ON a.tag_id = i.tag_id AND a.ended_at IS NULL "
                "JOIN vehicle v ON v.id = a.vehicle_id JOIN owner o ON o.id = a.owner_id "
                "WHERE i.namespace = %s AND i.value = %s",
                (found.namespace, found.value),
            ).fetchone()
        if row is None:
            return Lookup(LookupUnknown(tag_uid=found.value if asker is not None else None))
        return Lookup(self.outcome(asker, row))

    def outcome(
        self, asker: UUID | None, row: DictRow
    ) -> LookupMine | LookupShared | LookupPrivate | LookupFleet:
        """The whitelist per outcome (CAT-107). Only these fields ever leave."""
        owner: UUID = row["owner_id"]
        if asker == owner:
            return LookupMine(vehicle_id=row["vehicle_id"])
        right = self.shared_with(asker, owner) if asker is not None else None
        if right in ("view", "edit"):
            return LookupFleet(
                vehicle_id=row["vehicle_id"], right="edit" if right == "edit" else "view"
            )
        card = MiniCard(
            litt=row["litt"],
            number=row["number"],
            kind=VehicleKind(row["kind"]) if row["kind"] else None,
            operator=row["operator"],
            scale=row["scale"],
            thumbnail=None,
        )
        if asker is not None and row["show_name"]:
            return LookupShared(owner_name=row["owner_name"], card=card)
        return LookupPrivate(card=card)

    # --- Linking ----------------------------------------------------------------------------

    def _vehicle(self, conn: Connection[DictRow], owner: UUID, vehicle: UUID) -> DictRow:
        row = conn.execute(
            "SELECT id, status FROM vehicle WHERE id = %s AND owner_id = %s FOR UPDATE",
            (vehicle, owner),
        ).fetchone()
        if row is None:
            raise not_found()
        return row

    def _end(self, conn: Connection[DictRow], assignment: DictRow, by: UUID) -> None:
        conn.execute(
            "UPDATE tag_assignment SET ended_at = now() WHERE id = %s", (assignment["id"],)
        )
        conn.execute(
            "INSERT INTO tag_event (tag_id, vehicle_id, by_owner, event) "
            "VALUES (%s, %s, %s, 'unlinked')",
            (assignment["tag_id"], assignment["vehicle_id"], by),
        )

    def _start(
        self, conn: Connection[DictRow], owner: UUID, tag: UUID, kind: str, vehicle: UUID
    ) -> None:
        conn.execute(
            "INSERT INTO tag_assignment (id, owner_id, tag_id, vehicle_id, slot) "
            "VALUES (%s, %s, %s, %s, %s)",
            (uuid.uuid4(), owner, tag, vehicle, slot_of(kind)),
        )
        conn.execute(
            "INSERT INTO tag_event (tag_id, vehicle_id, by_owner, event) "
            "VALUES (%s, %s, %s, 'linked')",
            (tag, vehicle, owner),
        )

    def _make_room(
        self,
        conn: Connection[DictRow],
        owner: UUID,
        vehicle: UUID,
        kind: str,
        replace: UUID | None,
    ) -> None:
        """End the vehicle's link of the same kind, if it is the one seen (CAT-88, CAT-89)."""
        current = conn.execute(
            "SELECT id, tag_id, vehicle_id FROM tag_assignment "
            "WHERE vehicle_id = %s AND slot = %s AND ended_at IS NULL FOR UPDATE",
            (vehicle, slot_of(kind)),
        ).fetchone()
        if current is None and replace is None:
            return
        if current is None or current["id"] != replace:
            raise Refused(
                409, ProblemCode.TAG_CHANGED, "Kopplingen har ändrats. Öppna kortet igen."
            )
        self._end(conn, current, owner)

    def link(self, owner: UUID, uid: str, body: TagLink) -> None:
        """Link a tag to one of one's own vehicles (CAT-83–CAT-92)."""
        found = normalize(uid)
        with self.db.owner_transaction(owner) as conn:
            vehicle = self._vehicle(conn, owner, body.vehicle)
            if vehicle["status"] != "ready":
                raise Refused(
                    422, ProblemCode.NOT_READY, "Spara fordonet som klart innan du kopplar en tagg."
                )
            # One registration at a time per physical tag, across all owners (CAT-85).
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"tag:{found.namespace}:{found.value}",),
            )
            tag = conn.execute(
                "SELECT t.id, t.owner_id, t.kind FROM tag_identifier i "
                "JOIN tag t ON t.id = i.tag_id "
                "WHERE i.namespace = %s AND i.value = %s FOR UPDATE OF t",
                (found.namespace, found.value),
            ).fetchone()
            if tag is None:
                if found.kind is not TagKind.NFC:
                    raise Refused(404, ProblemCode.NOT_FOUND, "Taggen finns inte.")
                tag_id = uuid.uuid4()
                conn.execute(
                    "INSERT INTO tag (id, owner_id, name, kind) VALUES (%s, %s, %s, 'nfc')",
                    (tag_id, owner, f"NFC {found.value[-6:].upper()}"),
                )
                conn.execute(
                    "INSERT INTO tag_identifier (namespace, value, tag_id) VALUES (%s, %s, %s)",
                    (found.namespace, found.value, tag_id),
                )
                kind = TagKind.NFC.value
            else:
                tag_id, kind = tag["id"], tag["kind"]
                active = conn.execute(
                    "SELECT id, owner_id, tag_id, vehicle_id FROM tag_assignment "
                    "WHERE tag_id = %s AND ended_at IS NULL FOR UPDATE",
                    (tag_id,),
                ).fetchone()
                if active is not None and active["vehicle_id"] == body.vehicle:
                    return  # The same request again: the same result (CAT-92).
                if active is not None and active["owner_id"] != owner:
                    raise Refused(
                        409,
                        ProblemCode.TAG_TAKEN,
                        "Taggen är redan kopplad. Ägaren måste koppla bort den först.",
                    )
                if active is not None:
                    if body.move_from != active["id"]:
                        raise Refused(
                            409,
                            ProblemCode.TAG_ON_OTHER_VEHICLE,
                            "Taggen sitter på ett annat av dina fordon.",
                        )
                    self._end(conn, active, owner)
                elif tag["owner_id"] != owner:
                    if kind == TagKind.SIM.value:
                        raise Refused(
                            409, ProblemCode.TAG_TAKEN, "Den simulerade taggen är någon annans."
                        )
                    # A physical tag that was unlinked can get a new owner. Old events keep
                    # the one who made them (CAT-91).
                    conn.execute("UPDATE tag SET owner_id = %s WHERE id = %s", (owner, tag_id))
            self._make_room(conn, owner, body.vehicle, kind, body.replace)
            self._start(conn, owner, tag_id, kind, body.vehicle)
            conn.execute(
                "DELETE FROM pending_link WHERE owner_id = %s AND vehicle_id = %s",
                (owner, body.vehicle),
            )

    # --- Koppla tagg: the vehicle that waits for a tag (CAT-94) -------------------------------

    def pending(self, owner: UUID) -> PendingState:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT p.vehicle_id, p.replace, p.expires_at, v.litt, v.number "
                "FROM pending_link p JOIN vehicle v ON v.id = p.vehicle_id "
                "WHERE p.owner_id = %s AND p.expires_at > now() AND v.status = 'ready'",
                (owner,),
            ).fetchone()
        if row is None:
            return PendingState(pending=None)
        return PendingState(
            pending=PendingLink(
                vehicle_id=row["vehicle_id"],
                title=f"{row['litt']} {row['number']}".strip(),
                replace=row["replace"],
                expires_at=row["expires_at"],
            )
        )

    def wait_for_tag(self, owner: UUID, vehicle: UUID, replace: UUID | None) -> PendingState:
        with self.db.owner_transaction(owner) as conn:
            row = self._vehicle(conn, owner, vehicle)
            if row["status"] != "ready":
                raise Refused(
                    422, ProblemCode.NOT_READY, "Spara fordonet som klart innan du kopplar en tagg."
                )
            conn.execute(
                "INSERT INTO pending_link (owner_id, vehicle_id, replace, expires_at) "
                "VALUES (%(o)s, %(v)s, %(r)s, now() + make_interval(mins => %(m)s)) "
                "ON CONFLICT (owner_id) DO UPDATE SET vehicle_id = excluded.vehicle_id, "
                "replace = excluded.replace, expires_at = excluded.expires_at",
                {"o": owner, "v": vehicle, "r": replace, "m": PENDING_MINUTES},
            )
        return self.pending(owner)

    def stop_waiting(self, owner: UUID) -> PendingState:
        with self.db.owner_transaction(owner) as conn:
            conn.execute("DELETE FROM pending_link WHERE owner_id = %s", (owner,))
        return PendingState(pending=None)

    def unlink(self, owner: UUID, vehicle: UUID, body: TagUnlink) -> None:
        """The link gets an end and the history stays (CAT-90). Again is the same (CAT-92)."""
        with self.db.owner_transaction(owner) as conn:
            self._vehicle(conn, owner, vehicle)
            assignment = conn.execute(
                "SELECT id, tag_id, vehicle_id, ended_at FROM tag_assignment "
                "WHERE id = %s AND vehicle_id = %s AND owner_id = %s FOR UPDATE",
                (body.assignment, vehicle, owner),
            ).fetchone()
            if assignment is None:
                raise Refused(
                    409, ProblemCode.TAG_CHANGED, "Kopplingen har ändrats. Öppna kortet igen."
                )
            if assignment["ended_at"] is None:
                self._end(conn, assignment, owner)

    def new_label(self, owner: UUID, vehicle: UUID, replace: UUID | None) -> None:
        """A new QR label, linked to the vehicle at once (CAT-121)."""
        value = "q" + "".join(secrets.choice(_QR_LETTERS) for _ in range(11))
        with self.db.owner_transaction(owner) as conn:
            row = self._vehicle(conn, owner, vehicle)
            if row["status"] != "ready":
                raise Refused(
                    422, ProblemCode.NOT_READY, "Spara fordonet som klart innan det får en etikett."
                )
            self._make_room(conn, owner, vehicle, TagKind.QR.value, replace)
            tag_id = uuid.uuid4()
            conn.execute(
                "INSERT INTO tag (id, owner_id, name, kind) VALUES (%s, %s, %s, 'qr')",
                (tag_id, owner, f"QR {value[1:5].upper()}"),
            )
            conn.execute(
                "INSERT INTO tag_identifier (namespace, value, tag_id) VALUES ('qr', %s, %s)",
                (value, tag_id),
            )
            self._start(conn, owner, tag_id, TagKind.QR.value, vehicle)

    def new_simulated(self, owner: UUID) -> Tag:
        """A simulated tag, to try the flows without hardware, only in the test environment."""
        if not self.simulated:
            raise Refused(403, ProblemCode.NOT_HERE, "Simulerade taggar finns bara i testmiljön.")
        tag_id, value = uuid.uuid4(), str(uuid.uuid4())
        with self.db.owner_transaction(owner) as conn:
            row = conn.execute(
                "SELECT count(*) AS n FROM tag WHERE owner_id = %s AND kind = 'sim'", (owner,)
            ).fetchone()
            name = f"SIM-{(int(row['n']) if row else 0) + 1:03d}"
            conn.execute(
                "INSERT INTO tag (id, owner_id, name, kind) VALUES (%s, %s, %s, 'sim')",
                (tag_id, owner, name),
            )
            conn.execute(
                "INSERT INTO tag_identifier (namespace, value, tag_id) VALUES ('sim', %s, %s)",
                (value, tag_id),
            )
        return Tag(id=tag_id, uid=value, name=name, kind=TagKind.SIM, address=self.address(value))

    # --- The tag's own pages ----------------------------------------------------------------

    def events(self, owner: UUID, uid: str) -> list[TagEvent]:
        """Only the events the asker made (CAT-93)."""
        found = normalize(uid)
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT e.event, e.at, e.vehicle_id FROM tag_identifier i "
                "JOIN tag_event e ON e.tag_id = i.tag_id "
                "WHERE i.namespace = %s AND i.value = %s AND e.by_owner = %s ORDER BY e.at, e.id",
                (found.namespace, found.value, owner),
            ).fetchall()
        return [TagEvent.model_validate(dict(r)) for r in rows]

    def qr_svg(self, owner: UUID, uid: str) -> bytes:
        """The QR code with the tag's address, for the tag's owner only."""
        found = normalize(uid)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT t.owner_id FROM tag_identifier i JOIN tag t ON t.id = i.tag_id "
                "WHERE i.namespace = %s AND i.value = %s",
                (found.namespace, found.value),
            ).fetchone()
        if row is None or row["owner_id"] != owner:
            raise Refused(404, ProblemCode.NOT_FOUND, "Taggen finns inte.")
        picture = io.BytesIO()
        segno.make(self.address(found.value), error="m").save(
            picture, kind="svg", scale=8, border=2, dark="#111317", light="#ffffff"
        )
        return picture.getvalue()
