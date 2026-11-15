"""The fleet: an owner's vehicles and places at home (#50, CAT-52–CAT-77).

Every write is a short transaction that locks the owner's row first and then the vehicle
(CAT-40). Every change raises the vehicle's version, and a change built on an older version
is refused (CAT-63). The number is stored exactly as painted, and the EVN is derived from it
when the vehicle is read (CAT-55, CAT-58).

Only the owner sees the fleet in this step; sharing comes with TrainMeet ID (#49). A vehicle
or place that is not the asker's is answered as not found (CAT-50).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from catalog import evn
from catalog.db import Database
from contracts.catalog import (
    DccFunction,
    EvnParts,
    FieldSource,
    Lend,
    Lending,
    Notice,
    OwnerSettings,
    Place,
    ProblemCode,
    Return,
    Vehicle,
    VehicleChange,
    VehicleEvent,
    VehicleFields,
    VehicleKind,
    VehicleList,
    VehicleState,
    VehicleStatus,
    VehicleTag,
)

# The core fields that carry a source (CAT-64). The place is not one: it is where the
# vehicle lives, not something said about it.
CORE_FIELDS = (
    "kind",
    "litt",
    "number",
    "operator",
    "epoch",
    "scale",
    "maker",
    "article_number",
    "note",
    "dcc_address",
    "functions",
)
ENGINES = {VehicleKind.LOCOMOTIVE, VehicleKind.MULTIPLE_UNIT}
# Enough for any one owner's fleet. Paging comes if a fleet ever grows past it.
MOST = 5000
_COLUMNS = (
    "v.id, v.version, v.status, v.kind, v.litt, v.number, v.operator, v.epoch, v.scale, v.maker, "
    "v.article_number, v.note, v.dcc_address, v.functions, v.state, v.place_id, "
    "p.name AS place_name, v.lent_to, v.lent_since, v.lent_until, v.field_sources, "
    "v.created_at, v.updated_at"
)
_FROM = "vehicle v LEFT JOIN place p ON p.id = v.place_id"


class Refused(Exception):
    """Catalog says no. The web app shows the text for the code."""

    def __init__(self, status: int, code: ProblemCode, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def not_found() -> Refused:
    return Refused(404, ProblemCode.NOT_FOUND, "Fordonet finns inte.")


def changed() -> Refused:
    return Refused(409, ProblemCode.CHANGED, "Fordonet har ändrats. Öppna det igen.")


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _evn(number: str) -> EvnParts | None:
    found = evn.describe(number)
    if found is None:
        return None
    return EvnParts(
        text=found.text,
        interop=found.interop,
        country=found.country,
        country_letters=found.country_letters,
        serial=found.serial,
        check=found.check,
        given=found.given,
        valid=found.valid,
    )


def to_vehicle(
    row: DictRow, tags: list[VehicleTag] | None = None, notices: list[Notice] | None = None
) -> Vehicle:
    lending = None
    if row["state"] == VehicleState.LENT and row["lent_to"] and row["lent_since"]:
        lending = Lending(to=row["lent_to"], since=row["lent_since"], until=row["lent_until"])
    return Vehicle(
        id=row["id"],
        version=row["version"],
        status=row["status"],
        kind=row["kind"],
        litt=row["litt"],
        number=row["number"],
        operator=row["operator"],
        epoch=row["epoch"],
        scale=row["scale"],
        maker=row["maker"],
        article_number=row["article_number"],
        note=row["note"],
        dcc_address=row["dcc_address"],
        functions=[DccFunction.model_validate(f) for f in row["functions"]],
        place=row["place_id"],
        place_name=row["place_name"],
        state=row["state"],
        lending=lending,
        evn=_evn(row["number"]),
        field_sources={k: FieldSource(v) for k, v in row["field_sources"].items()},
        tags=tags or [],
        notices=notices or [],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _values(fields: VehicleFields) -> dict[str, Any]:
    """The core fields as they are stored."""
    return {
        "kind": fields.kind.value if fields.kind else None,
        "litt": fields.litt,
        "number": fields.number,
        "operator": fields.operator,
        "epoch": fields.epoch,
        "scale": fields.scale,
        "maker": fields.maker,
        "article_number": fields.article_number,
        "note": fields.note,
        "dcc_address": fields.dcc_address,
        "functions": [f.model_dump(mode="json") for f in fields.functions],
    }


def _check(fields: VehicleFields) -> None:
    if fields.status is VehicleStatus.READY and (
        fields.kind is None or not (fields.litt or fields.number)
    ):
        raise Refused(
            422,
            ProblemCode.NOT_READY,
            "Ett klart fordon behöver slag och littera eller nummer.",
        )
    if (fields.dcc_address or fields.functions) and fields.kind not in ENGINES:
        raise Refused(
            422,
            ProblemCode.DCC_ONLY_ENGINES,
            "DCC-adress och funktioner finns bara för lok och motorvagnar.",
        )


def _place_name(conn: Connection[DictRow], owner: UUID, place: UUID | None) -> str | None:
    if place is None:
        return None
    row = conn.execute(
        "SELECT name FROM place WHERE id = %s AND owner_id = %s", (place, owner)
    ).fetchone()
    if row is None:
        raise Refused(422, ProblemCode.NOT_FOUND, "Platsen finns inte.")
    return str(row["name"])


def _event(
    conn: Connection[DictRow],
    vehicle: UUID,
    state: VehicleState | str,
    place_name: str | None,
    lent_to: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO vehicle_event (vehicle_id, state, place_name, lent_to) "
        "VALUES (%s, %s, %s, %s)",
        (vehicle, str(state), place_name, lent_to),
    )


class Fleet:
    def __init__(self, db: Database, *, tag_base: str = "https://trainmeet.app/t/") -> None:
        self.db = db
        self.tag_base = tag_base.rstrip("/") + "/"

    # --- Reading ----------------------------------------------------------------------

    def _tags(
        self, conn: Connection[DictRow], vehicles: list[UUID]
    ) -> dict[UUID, list[VehicleTag]]:
        """The active tags per vehicle: at most one NFC and one QR each (CAT-82, CAT-97)."""
        found: dict[UUID, list[VehicleTag]] = {}
        if not vehicles:
            return found
        rows = conn.execute(
            "SELECT DISTINCT ON (a.id) a.id, a.vehicle_id, a.started_at, t.id AS tag, t.name, "
            "t.kind, i.value FROM tag_assignment a JOIN tag t ON t.id = a.tag_id "
            "JOIN tag_identifier i ON i.tag_id = t.id "
            "WHERE a.vehicle_id = ANY(%s) AND a.ended_at IS NULL ORDER BY a.id, i.namespace",
            (vehicles,),
        ).fetchall()
        for row in sorted(rows, key=lambda r: (r["kind"] == "qr", r["started_at"])):
            found.setdefault(row["vehicle_id"], []).append(
                VehicleTag(
                    assignment=row["id"],
                    tag=row["tag"],
                    uid=row["value"],
                    name=row["name"],
                    kind=row["kind"],
                    address=self.tag_base + row["value"],
                    linked_at=row["started_at"],
                )
            )
        return found

    def _with_tags(self, conn: Connection[DictRow], rows: list[DictRow]) -> list[Vehicle]:
        ids = [r["id"] for r in rows]
        tags = self._tags(conn, ids)
        notices: dict[UUID, list[Notice]] = {}
        if ids:
            for n in conn.execute(
                "SELECT id, vehicle_id, text, at FROM vehicle_notice "
                "WHERE vehicle_id = ANY(%s) ORDER BY at DESC",
                (ids,),
            ).fetchall():
                notices.setdefault(n["vehicle_id"], []).append(
                    Notice(id=n["id"], text=n["text"], at=n["at"])
                )
        return [to_vehicle(r, tags.get(r["id"]), notices.get(r["id"])) for r in rows]

    def _read(self, conn: Connection[DictRow], owner: UUID, vehicle: UUID) -> Vehicle:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM {_FROM} WHERE v.id = %s AND v.owner_id = %s",
            (vehicle, owner),
        ).fetchone()
        if row is None:
            raise not_found()
        return self._with_tags(conn, [row])[0]

    def get(self, owner: UUID, vehicle: UUID) -> Vehicle:
        with self.db.transaction() as conn:
            return self._read(conn, owner, vehicle)

    def search(
        self,
        owner: UUID,
        *,
        q: str = "",
        kinds: Iterable[VehicleKind] = (),
        scale: str = "",
        state: VehicleState | None = None,
        place: UUID | None = None,
        without_place: bool = False,
    ) -> VehicleList:
        """Free text over litt, number, operator, model and note, and filters (CAT-65)."""
        where = ["v.owner_id = %(owner)s"]
        args: dict[str, Any] = {"owner": owner}
        text = q.strip()
        if text:
            where.append(
                "(v.litt ILIKE %(q)s OR v.number ILIKE %(q)s OR v.operator ILIKE %(q)s "
                "OR v.maker ILIKE %(q)s OR v.article_number ILIKE %(q)s OR v.note ILIKE %(q)s "
                "OR (v.litt || ' ' || v.number) ILIKE %(q)s"
                + (
                    " OR regexp_replace(v.number, '\\D', '', 'g') LIKE %(digits)s"
                    if any(c.isdigit() for c in text) and not any(c.isalpha() for c in text)
                    else ""
                )
                + ")"
            )
            args["q"] = _like(text)
            args["digits"] = _like("".join(c for c in text if c.isdigit()))
        chosen = [k.value for k in kinds]
        if chosen:
            where.append("v.kind = ANY(%(kinds)s)")
            args["kinds"] = chosen
        if scale.strip():
            where.append("v.scale = %(scale)s")
            args["scale"] = scale.strip()
        if without_place:
            where.append("v.place_id IS NULL")
        elif place is not None:
            where.append("v.place_id = %(place)s")
            args["place"] = place
        filtered = " AND ".join(where)
        with self.db.transaction() as conn:
            counted = conn.execute(
                f"SELECT v.state, count(*) AS n FROM {_FROM} WHERE {filtered} GROUP BY v.state",
                args,
            ).fetchall()
            in_state = filtered + (" AND v.state = %(state)s" if state else "")
            if state:
                args["state"] = state.value
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM {_FROM} WHERE {in_state} "
                "ORDER BY lower(v.litt), v.number, v.created_at LIMIT %(most)s",
                {**args, "most": MOST},
            ).fetchall()
            vehicles = self._with_tags(conn, rows)
        counts = {s: 0 for s in VehicleState}
        for row in counted:
            counts[VehicleState(row["state"])] = int(row["n"])
        return VehicleList(vehicles=vehicles, counts=counts, total=sum(counts.values()))

    def events(self, owner: UUID, vehicle: UUID) -> list[VehicleEvent]:
        with self.db.transaction() as conn:
            self._read(conn, owner, vehicle)
            rows = conn.execute(
                "SELECT at, state, place_name, lent_to FROM vehicle_event "
                "WHERE vehicle_id = %s ORDER BY at DESC, id DESC",
                (vehicle,),
            ).fetchall()
        return [VehicleEvent.model_validate(dict(r)) for r in rows]

    # --- Writing ----------------------------------------------------------------------

    def create(self, owner: UUID, fields: VehicleFields) -> Vehicle:
        _check(fields)
        vehicle = uuid.uuid4()
        values = _values(fields)
        sources = {k: FieldSource.OWNER.value for k, v in values.items() if v not in ("", None, [])}
        with self.db.owner_transaction(owner) as conn:
            place_name = _place_name(conn, owner, fields.place)
            conn.execute(
                "INSERT INTO vehicle (id, owner_id, status, kind, litt, number, operator, epoch, "
                "scale, maker, article_number, note, dcc_address, functions, place_id, "
                "field_sources) VALUES (%(id)s, %(owner)s, %(status)s, %(kind)s, %(litt)s, "
                "%(number)s, %(operator)s, %(epoch)s, %(scale)s, %(maker)s, %(article_number)s, "
                "%(note)s, %(dcc_address)s, %(functions)s, %(place)s, %(sources)s)",
                {
                    **values,
                    "functions": Jsonb(values["functions"]),
                    "id": vehicle,
                    "owner": owner,
                    "status": fields.status.value,
                    "place": fields.place,
                    "sources": Jsonb(sources),
                },
            )
            conn.execute(
                "INSERT INTO vehicle_owner (vehicle_id, owner_id) VALUES (%s, %s)",
                (vehicle, owner),
            )
            _event(conn, vehicle, VehicleState.HOME, place_name)
            return self._read(conn, owner, vehicle)

    def _lock(self, conn: Connection[DictRow], owner: UUID, vehicle: UUID, version: int) -> Vehicle:
        """The vehicle, locked after the owner's row, at the version the change was built on."""
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM {_FROM} WHERE v.id = %s AND v.owner_id = %s FOR UPDATE OF v",
            (vehicle, owner),
        ).fetchone()
        if row is None:
            raise not_found()
        current = self._with_tags(conn, [row])[0]
        if current.version != version:
            raise changed()
        return current

    def change(self, owner: UUID, vehicle: UUID, change: VehicleChange) -> Vehicle:
        _check(change)
        values = _values(change)
        with self.db.owner_transaction(owner) as conn:
            current = self._lock(conn, owner, vehicle, change.version)
            if change.status is VehicleStatus.DRAFT and (
                current.state is VehicleState.LENT or current.tags
            ):
                raise Refused(
                    422,
                    ProblemCode.NOT_READY,
                    "Ett fordon som är utlånat eller har en tagg kan inte bli ett utkast.",
                )
            before = _values(current)
            sources = {k: v.value for k, v in current.field_sources.items()}
            for key, value in values.items():
                if value != before[key]:
                    if value in ("", None, []):
                        sources.pop(key, None)
                    else:
                        sources[key] = FieldSource.OWNER.value
            place_name = _place_name(conn, owner, change.place)
            conn.execute(
                "UPDATE vehicle SET version = version + 1, updated_at = now(), "
                "status = %(status)s, kind = %(kind)s, litt = %(litt)s, number = %(number)s, "
                "operator = %(operator)s, "
                "epoch = %(epoch)s, scale = %(scale)s, maker = %(maker)s, "
                "article_number = %(article_number)s, note = %(note)s, "
                "dcc_address = %(dcc_address)s, functions = %(functions)s, "
                "place_id = %(place)s, field_sources = %(sources)s WHERE id = %(id)s",
                {
                    **values,
                    "functions": Jsonb(values["functions"]),
                    "status": change.status.value,
                    "place": change.place,
                    "sources": Jsonb(sources),
                    "id": vehicle,
                },
            )
            if change.place != current.place:
                _event(conn, vehicle, current.state, place_name)
            return self._read(conn, owner, vehicle)

    def remove(self, owner: UUID, vehicle: UUID, version: int) -> None:
        """Remove a vehicle after the owner has confirmed. Its tags become free (CAT-68)."""
        with self.db.owner_transaction(owner) as conn:
            self._lock(conn, owner, vehicle, version)
            conn.execute(
                "INSERT INTO tag_event (tag_id, vehicle_id, by_owner, event) "
                "SELECT tag_id, NULL, %s, 'unlinked' FROM tag_assignment "
                "WHERE vehicle_id = %s AND ended_at IS NULL",
                (owner, vehicle),
            )
            conn.execute("DELETE FROM vehicle WHERE id = %s", (vehicle,))

    def move(self, owner: UUID, vehicles: list[UUID], place: UUID | None) -> VehicleList:
        """Several vehicles to one place at home at once (CAT-73)."""
        unique = list(dict.fromkeys(vehicles))
        with self.db.owner_transaction(owner) as conn:
            place_name = _place_name(conn, owner, place)
            rows = conn.execute(
                "SELECT id, state, place_id FROM vehicle WHERE owner_id = %s AND id = ANY(%s) "
                "ORDER BY id FOR UPDATE",
                (owner, unique),
            ).fetchall()
            if len(rows) != len(unique):
                raise not_found()
            for row in rows:
                if row["place_id"] == place:
                    continue
                conn.execute(
                    "UPDATE vehicle SET place_id = %s, version = version + 1, updated_at = now() "
                    "WHERE id = %s",
                    (place, row["id"]),
                )
                _event(conn, row["id"], row["state"], place_name)
            moved = conn.execute(
                f"SELECT {_COLUMNS} FROM {_FROM} WHERE v.owner_id = %s AND v.id = ANY(%s) "
                "ORDER BY lower(v.litt), v.number, v.created_at",
                (owner, unique),
            ).fetchall()
            result = self._with_tags(conn, moved)
        counts = {s: sum(1 for v in result if v.state is s) for s in VehicleState}
        return VehicleList(vehicles=result, counts=counts, total=len(result))

    def lend(self, owner: UUID, vehicle: UUID, lend: Lend) -> Vehicle:
        """Lent to someone: the owner's own note, no rights for the borrower (CAT-74, CAT-75)."""
        with self.db.owner_transaction(owner) as conn:
            current = self._lock(conn, owner, vehicle, lend.version)
            if current.status is not VehicleStatus.READY:
                raise Refused(422, ProblemCode.NOT_READY, "Bara ett klart fordon kan lånas ut.")
            if current.state is not VehicleState.HOME:
                raise Refused(422, ProblemCode.NOT_HOME, "Bara ett fordon hemma kan lånas ut.")
            conn.execute(
                "UPDATE vehicle SET state = 'lent', lent_to = %s, lent_since = now(), "
                "lent_until = %s, version = version + 1, updated_at = now() WHERE id = %s",
                (lend.to, lend.until, vehicle),
            )
            _event(conn, vehicle, VehicleState.LENT, current.place_name, lend.to)
            return self._read(conn, owner, vehicle)

    def give_back(self, owner: UUID, vehicle: UUID, back: Return) -> Vehicle:
        """Back home, to its earlier place (CAT-76)."""
        with self.db.owner_transaction(owner) as conn:
            current = self._lock(conn, owner, vehicle, back.version)
            if current.state is not VehicleState.LENT:
                raise Refused(422, ProblemCode.NOT_LENT, "Fordonet är inte utlånat.")
            conn.execute(
                "UPDATE vehicle SET state = 'home', lent_to = NULL, lent_since = NULL, "
                "lent_until = NULL, version = version + 1, updated_at = now() WHERE id = %s",
                (vehicle,),
            )
            _event(conn, vehicle, VehicleState.HOME, current.place_name)
            return self._read(conn, owner, vehicle)

    def clear_notice(self, owner: UUID, vehicle: UUID, notice: UUID) -> None:
        """The owner has read what someone said (CAT-113)."""
        with self.db.owner_transaction(owner) as conn:
            self._read(conn, owner, vehicle)
            removed = conn.execute(
                "DELETE FROM vehicle_notice WHERE id = %s AND vehicle_id = %s", (notice, vehicle)
            )
            if removed.rowcount == 0:
                raise Refused(404, ProblemCode.NOT_FOUND, "Beskedet finns inte.")

    # --- The owner's settings ----------------------------------------------------------------

    def settings(self, owner: UUID) -> OwnerSettings:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT show_name FROM owner WHERE id = %s", (owner,)).fetchone()
        return OwnerSettings(show_name=bool(row and row["show_name"]))

    def change_settings(self, owner: UUID, settings: OwnerSettings) -> OwnerSettings:
        """Visa mitt namn när någon blippar mina fordon (CAT-101)."""
        with self.db.owner_transaction(owner) as conn:
            conn.execute(
                "UPDATE owner SET show_name = %s WHERE id = %s", (settings.show_name, owner)
            )
        return self.settings(owner)

    # --- The places at home -------------------------------------------------------------

    def places(self, owner: UUID) -> list[Place]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT p.id, p.name, "
                "count(v.id) FILTER (WHERE v.state = 'home') AS vehicles_home, "
                "count(v.id) AS vehicles FROM place p LEFT JOIN vehicle v ON v.place_id = p.id "
                "WHERE p.owner_id = %s GROUP BY p.id ORDER BY lower(p.name), p.created_at",
                (owner,),
            ).fetchall()
        return [Place.model_validate(dict(r)) for r in rows]

    def _place(self, owner: UUID, place: UUID) -> Place:
        found = next((p for p in self.places(owner) if p.id == place), None)
        if found is None:
            raise Refused(404, ProblemCode.NOT_FOUND, "Platsen finns inte.")
        return found

    def _named(self, conn: Connection[DictRow], owner: UUID, name: str, other: UUID | None) -> None:
        row = conn.execute(
            "SELECT id FROM place WHERE owner_id = %s AND name = %s", (owner, name)
        ).fetchone()
        if row is not None and row["id"] != other:
            raise Refused(422, ProblemCode.PLACE_EXISTS, "Det finns redan en plats med det namnet.")

    def add_place(self, owner: UUID, name: str) -> Place:
        place = uuid.uuid4()
        with self.db.owner_transaction(owner) as conn:
            self._named(conn, owner, name, None)
            conn.execute(
                "INSERT INTO place (id, owner_id, name) VALUES (%s, %s, %s)", (place, owner, name)
            )
        return self._place(owner, place)

    def rename_place(self, owner: UUID, place: UUID, name: str) -> Place:
        with self.db.owner_transaction(owner) as conn:
            self._named(conn, owner, name, place)
            renamed = conn.execute(
                "UPDATE place SET name = %s WHERE id = %s AND owner_id = %s", (name, place, owner)
            )
            if renamed.rowcount == 0:
                raise Refused(404, ProblemCode.NOT_FOUND, "Platsen finns inte.")
        return self._place(owner, place)

    def remove_place(self, owner: UUID, place: UUID) -> None:
        """Its vehicles stay at home without a place (CAT-71)."""
        with self.db.owner_transaction(owner) as conn:
            homed = conn.execute(
                "SELECT id FROM vehicle WHERE place_id = %s AND owner_id = %s "
                "ORDER BY id FOR UPDATE",
                (place, owner),
            ).fetchall()
            removed = conn.execute(
                "DELETE FROM place WHERE id = %s AND owner_id = %s", (place, owner)
            )
            if removed.rowcount == 0:
                raise Refused(404, ProblemCode.NOT_FOUND, "Platsen finns inte.")
            for row in homed:
                conn.execute(
                    "UPDATE vehicle SET version = version + 1, updated_at = now() WHERE id = %s",
                    (row["id"],),
                )
