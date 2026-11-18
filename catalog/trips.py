"""The trip to the meet (#55, CAT-174–CAT-183): the owner's meets, the pack list and the steps.

A meet in Catalog is the owner's own list with a name and a date, as long as the link to the
Hub waits (CAT-174, K7). The pack list points out the vehicles (CAT-175). The trip has three
steps, pack, arrive and home, and a tick per vehicle and step with its time, set by a tap on
the vehicle's tag or a press on its row (CAT-176).

Rules:
- Every write locks the owner's row first, then the vehicles (CAT-40).
- The same tick twice is one tick: the first one stands, and nothing moves again.
- A tick moves the vehicle through Fleet's own code, so its state and the event are the
  owner's own history (CAT-177, CAT-182). Only the owner's own taps are kept, never anyone
  else's (CAT-110): a tag that is not on one of the owner's vehicles leaves nothing behind.
- The state follows the highest step ticked: Hem gives home, På plats at the meet and Packa
  packed, and with no tick the vehicle is home. Hem leaves the place alone: a vehicle's place
  is its home place also while it is away, so it comes back to the place it had before.
- A vehicle is away on at most one trip at a time: ticked in Packa or På plats and not in Hem.
  While it is, other meets leave it alone. A lent vehicle is never ticked.
- The tick that brings the last vehicle home archives the meet once its date has come, in
  Swedish time (CAT-183). The owner may archive it by hand when nothing on it is away. An
  archived meet does not change; its pack list can start the next one.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow

from catalog.db import Database
from catalog.fleet import Fleet, Refused, not_found
from catalog.tags import normalize
from contracts.catalog import (
    NewTrip,
    ProblemCode,
    TapOutcome,
    Tick,
    TickBy,
    TickChange,
    Trip,
    TripRow,
    TripStep,
    TripSummary,
    TripTap,
    TripTapped,
    VehicleState,
)

STEPS = (TripStep.PACK, TripStep.ARRIVE, TripStep.HOME)
STATE_OF = {
    TripStep.PACK: VehicleState.PACKED,
    TripStep.ARRIVE: VehicleState.AT_MEET,
    TripStep.HOME: VehicleState.HOME,
}
# The meet's date has come when it is that day or later in Sweden.
TODAY = "(now() AT TIME ZONE 'Europe/Stockholm')::date"
_SUMMARY = (
    "SELECT m.id, m.name, m.date, m.archived_at, m.created_at, m.template_of, "
    "(SELECT count(*) FROM meet_vehicle mv WHERE mv.meet_id = m.id) AS vehicles, "
    "(SELECT count(*) FROM meet_tick t WHERE t.meet_id = m.id AND t.step = 'pack') AS pack, "
    "(SELECT count(*) FROM meet_tick t WHERE t.meet_id = m.id AND t.step = 'arrive') AS arrive, "
    "(SELECT count(*) FROM meet_tick t WHERE t.meet_id = m.id AND t.step = 'home') AS home "
    "FROM meet m"
)


def no_meet() -> Refused:
    return Refused(404, ProblemCode.NOT_FOUND, "Träffen finns inte.")


def state_of(steps: set[TripStep]) -> VehicleState:
    """Where the ticks put the vehicle: the highest step ticked, or home without a tick."""
    for step in reversed(STEPS):
        if step in steps:
            return STATE_OF[step]
    return VehicleState.HOME


def away(steps: set[TripStep]) -> bool:
    """Ticked in Packa or På plats and not yet in Hem: out on this trip."""
    return bool(steps) and TripStep.HOME not in steps


def current_step(vehicles: int, done: Mapping[TripStep, int]) -> TripStep:
    """The step the trip is at: the latest one ticked in, or the next when that one is done."""
    if done[TripStep.HOME] or (vehicles and done[TripStep.ARRIVE] >= vehicles):
        return TripStep.HOME
    if done[TripStep.ARRIVE] or (vehicles and done[TripStep.PACK] >= vehicles):
        return TripStep.ARRIVE
    return TripStep.PACK


def _summary(row: DictRow) -> TripSummary:
    done = {step: int(row[step.value]) for step in STEPS}
    return TripSummary(
        id=row["id"],
        name=row["name"],
        date=row["date"],
        archived_at=row["archived_at"],
        created_at=row["created_at"],
        template_of=row["template_of"],
        vehicles=int(row["vehicles"]),
        done=done,
        step=current_step(int(row["vehicles"]), done),
    )


def _title(vehicle: DictRow) -> str | None:
    return f"{vehicle['litt']} {vehicle['number']}".strip() or None


class Trips:
    def __init__(self, db: Database, fleet: Fleet) -> None:
        self.db = db
        self.fleet = fleet

    # --- Reading ----------------------------------------------------------------------------

    def meets(self, owner: UUID) -> list[TripSummary]:
        """The active meets first, the next one at the top, then the archived ones, newest
        first (CAT-183)."""
        with self.db.transaction() as conn:
            rows = conn.execute(
                f"{_SUMMARY} WHERE m.owner_id = %s ORDER BY m.archived_at IS NOT NULL, "
                "CASE WHEN m.archived_at IS NULL THEN m.date END, m.date DESC, m.created_at DESC",
                (owner,),
            ).fetchall()
        return [_summary(row) for row in rows]

    def get(self, owner: UUID, meet: UUID) -> Trip:
        with self.db.transaction() as conn:
            return self._read(conn, owner, meet)

    def export(self, owner: UUID) -> list[Trip]:
        """Every meet with its pack list and ticks, for the person's file (KONTO-31)."""
        with self.db.transaction() as conn:
            found = conn.execute(
                "SELECT id FROM meet WHERE owner_id = %s ORDER BY date, created_at", (owner,)
            ).fetchall()
            return [self._read(conn, owner, row["id"]) for row in found]

    def _summary(self, conn: Connection[DictRow], owner: UUID, meet: UUID) -> TripSummary:
        row = conn.execute(
            f"{_SUMMARY} WHERE m.id = %s AND m.owner_id = %s", (meet, owner)
        ).fetchone()
        if row is None:
            raise no_meet()
        return _summary(row)

    def _read(self, conn: Connection[DictRow], owner: UUID, meet: UUID) -> Trip:
        summary = self._summary(conn, owner, meet)
        listed = conn.execute(
            "SELECT mv.vehicle_id, mv.added_at FROM meet_vehicle mv "
            "JOIN vehicle v ON v.id = mv.vehicle_id WHERE mv.meet_id = %s "
            "ORDER BY mv.added_at, lower(v.litt), v.number, v.created_at",
            (meet,),
        ).fetchall()
        vehicles = self.fleet.read_many(conn, owner, [r["vehicle_id"] for r in listed])
        ticks: dict[UUID, list[Tick]] = {}
        for tick in conn.execute(
            "SELECT vehicle_id, step, at, by FROM meet_tick WHERE meet_id = %s", (meet,)
        ).fetchall():
            ticks.setdefault(tick["vehicle_id"], []).append(
                Tick(step=tick["step"], at=tick["at"], by=tick["by"])
            )
        rows: list[TripRow] = []
        for item in listed:
            vehicle = vehicles[item["vehicle_id"]]
            own = sorted(ticks.get(vehicle.id, []), key=lambda t: STEPS.index(t.step))
            rows.append(
                TripRow(
                    vehicle=vehicle.model_copy(update={"tagged": bool(vehicle.tags)}),
                    added_at=item["added_at"],
                    ticks=own,
                    last=max(own, key=lambda t: (t.at, STEPS.index(t.step)), default=None),
                    missing=all(t.step is not TripStep.HOME for t in own),
                )
            )
        if summary.step is TripStep.HOME:
            # Vid hemfärden står det som saknas överst (CAT-179).
            rows.sort(key=lambda r: not r.missing)
        return Trip(**summary.model_dump(), rows=rows)

    # --- Writing ----------------------------------------------------------------------------

    def _meet(self, conn: Connection[DictRow], owner: UUID, meet: UUID) -> DictRow:
        row = conn.execute(
            "SELECT id, name, date, archived_at FROM meet WHERE id = %s AND owner_id = %s",
            (meet, owner),
        ).fetchone()
        if row is None:
            raise no_meet()
        return row

    def _open(self, conn: Connection[DictRow], owner: UUID, meet: UUID) -> DictRow:
        row = self._meet(conn, owner, meet)
        if row["archived_at"] is not None:
            raise Refused(409, ProblemCode.ARCHIVED, "Träffen är arkiverad och ändras inte längre.")
        return row

    def _vehicle(self, conn: Connection[DictRow], owner: UUID, vehicle: UUID) -> DictRow:
        """The vehicle, locked after the owner's row (CAT-40)."""
        row = conn.execute(
            "SELECT id, state, litt, number FROM vehicle WHERE id = %s AND owner_id = %s "
            "FOR UPDATE",
            (vehicle, owner),
        ).fetchone()
        if row is None:
            raise not_found()
        return row

    def _steps(self, conn: Connection[DictRow], meet: UUID, vehicle: UUID) -> set[TripStep]:
        return {
            TripStep(row["step"])
            for row in conn.execute(
                "SELECT step FROM meet_tick WHERE meet_id = %s AND vehicle_id = %s",
                (meet, vehicle),
            ).fetchall()
        }

    def _away_on(self, conn: Connection[DictRow], vehicle: UUID, but: UUID) -> str | None:
        """The other active meet the vehicle is out on, if any."""
        row = conn.execute(
            "SELECT m.name FROM meet m JOIN meet_tick t ON t.meet_id = m.id "
            "WHERE t.vehicle_id = %s AND m.id <> %s AND m.archived_at IS NULL "
            "GROUP BY m.id, m.name HAVING NOT bool_or(t.step = 'home') LIMIT 1",
            (vehicle, but),
        ).fetchone()
        return str(row["name"]) if row else None

    def _add(self, conn: Connection[DictRow], meet: UUID, vehicles: list[UUID]) -> None:
        for vehicle in vehicles:
            conn.execute(
                "INSERT INTO meet_vehicle (meet_id, vehicle_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                (meet, vehicle),
            )

    def _change(
        self,
        conn: Connection[DictRow],
        meet: DictRow,
        vehicle: DictRow,
        step: TripStep,
        ticked: bool,
        by: TickBy,
    ) -> None:
        """Tick or untick, and move the vehicle where its ticks say (CAT-177, CAT-182)."""
        if vehicle["state"] == VehicleState.LENT:
            raise Refused(
                422,
                ProblemCode.LENT,
                "Ett utlånat fordon kan inte packas. Ta tillbaka det först."
                if step is TripStep.PACK
                else "Fordonet är utlånat. Ta tillbaka det först.",
            )
        other = self._away_on(conn, vehicle["id"], meet["id"])
        if other is not None:
            raise Refused(
                409,
                ProblemCode.ON_ANOTHER_TRIP,
                f"Fordonet är med på {other}. Bocka av det i Hem där först.",
            )
        if ticked:
            conn.execute(
                "INSERT INTO meet_tick (meet_id, vehicle_id, step, by) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (meet["id"], vehicle["id"], step.value, by.value),
            )
        else:
            conn.execute(
                "DELETE FROM meet_tick WHERE meet_id = %s AND vehicle_id = %s AND step = %s",
                (meet["id"], vehicle["id"], step.value),
            )
        state = state_of(self._steps(conn, meet["id"], vehicle["id"]))
        if state != vehicle["state"]:
            self.fleet.trip_state(conn, vehicle["id"], state, meet["name"])
        if ticked and step is TripStep.HOME:
            # Allt är hemma och träffen är slut: packlistan arkiveras (CAT-183).
            conn.execute(
                "UPDATE meet SET archived_at = now() WHERE id = %(m)s AND archived_at IS NULL "
                f"AND date <= {TODAY} "
                "AND EXISTS (SELECT 1 FROM meet_vehicle WHERE meet_id = %(m)s) "
                "AND NOT EXISTS (SELECT 1 FROM meet_vehicle mv WHERE mv.meet_id = %(m)s "
                "AND NOT EXISTS (SELECT 1 FROM meet_tick t WHERE t.meet_id = mv.meet_id "
                "AND t.vehicle_id = mv.vehicle_id AND t.step = 'home'))",
                {"m": meet["id"]},
            )

    def create(self, owner: UUID, new: NewTrip) -> Trip:
        """A new meet (CAT-174), perhaps with an earlier meet's pack list (CAT-183)."""
        meet = uuid.uuid4()
        with self.db.owner_transaction(owner) as conn:
            if new.template is not None:
                self._meet(conn, owner, new.template)
            conn.execute(
                "INSERT INTO meet (id, owner_id, name, date, template_of) "
                "VALUES (%s, %s, %s, %s, %s)",
                (meet, owner, new.name, new.date, new.template),
            )
            if new.template is not None:
                conn.execute(
                    "INSERT INTO meet_vehicle (meet_id, vehicle_id) "
                    "SELECT %s, vehicle_id FROM meet_vehicle WHERE meet_id = %s",
                    (meet, new.template),
                )
            return self._read(conn, owner, meet)

    def pack_list(self, owner: UUID, meet: UUID, vehicles: list[UUID]) -> Trip:
        """The vehicles that go to the meet (CAT-175). A vehicle taken off the list while it is
        away on this trip comes home, with an event like any other."""
        wanted = list(dict.fromkeys(vehicles))
        with self.db.owner_transaction(owner) as conn:
            row = self._open(conn, owner, meet)
            listed = {
                r["vehicle_id"]
                for r in conn.execute(
                    "SELECT vehicle_id FROM meet_vehicle WHERE meet_id = %s", (meet,)
                ).fetchall()
            }
            locked = {
                r["id"]: r
                for r in conn.execute(
                    "SELECT id, state FROM vehicle WHERE owner_id = %s AND id = ANY(%s) "
                    "ORDER BY id FOR UPDATE",
                    (owner, sorted(set(wanted) | listed)),
                ).fetchall()
            }
            if any(vehicle not in locked for vehicle in wanted):
                raise not_found()
            for gone in sorted(listed - set(wanted)):
                state = locked[gone]["state"]
                if away(self._steps(conn, meet, gone)) and state != VehicleState.LENT:
                    self.fleet.trip_state(conn, gone, VehicleState.HOME, row["name"])
                conn.execute(
                    "DELETE FROM meet_vehicle WHERE meet_id = %s AND vehicle_id = %s",
                    (meet, gone),
                )
            self._add(conn, meet, [vehicle for vehicle in wanted if vehicle not in listed])
            return self._read(conn, owner, meet)

    def tick(self, owner: UUID, meet: UUID, change: TickChange) -> Trip:
        """A press on the row: tick, or take the tick away (CAT-176)."""
        with self.db.owner_transaction(owner) as conn:
            row = self._open(conn, owner, meet)
            vehicle = self._vehicle(conn, owner, change.vehicle)
            listed = conn.execute(
                "SELECT 1 FROM meet_vehicle WHERE meet_id = %s AND vehicle_id = %s",
                (meet, change.vehicle),
            ).fetchone()
            if listed is None:
                raise Refused(404, ProblemCode.NOT_FOUND, "Fordonet står inte på packlistan.")
            self._change(conn, row, vehicle, change.step, change.ticked, TickBy.PRESS)
            return self._read(conn, owner, meet)

    def tap(self, owner: UUID, meet: UUID, tap: TripTap) -> TripTapped:
        """A tag tapped in a step (CAT-176). Only the owner's own vehicles are found, and
        nothing is kept about any other tag (CAT-110). Not on the list: ask first (CAT-181)."""
        found = normalize(tap.uid)
        with self.db.owner_transaction(owner) as conn:
            row = self._open(conn, owner, meet)
            hit = conn.execute(
                "SELECT v.id FROM tag_identifier i "
                "JOIN tag_assignment a ON a.tag_id = i.tag_id AND a.ended_at IS NULL "
                "JOIN vehicle v ON v.id = a.vehicle_id "
                "WHERE i.namespace = %s AND i.value = %s AND v.owner_id = %s",
                (found.namespace, found.value, owner),
            ).fetchone()
            if hit is None:
                return TripTapped(outcome=TapOutcome.UNKNOWN, trip=self._read(conn, owner, meet))
            vehicle = self._vehicle(conn, owner, hit["id"])
            listed = conn.execute(
                "SELECT 1 FROM meet_vehicle WHERE meet_id = %s AND vehicle_id = %s",
                (meet, vehicle["id"]),
            ).fetchone()
            if listed is None and not tap.add:
                return TripTapped(
                    outcome=TapOutcome.NOT_ON_LIST,
                    vehicle_id=vehicle["id"],
                    title=_title(vehicle),
                    trip=self._read(conn, owner, meet),
                )
            step = tap.step or self._summary(conn, owner, meet).step
            if listed is None:
                self._add(conn, meet, [vehicle["id"]])
            self._change(conn, row, vehicle, step, True, TickBy.TAP)
            return TripTapped(
                outcome=TapOutcome.TICKED,
                vehicle_id=vehicle["id"],
                title=_title(vehicle),
                trip=self._read(conn, owner, meet),
            )

    def archive(self, owner: UUID, meet: UUID) -> Trip:
        """Archive the pack list by hand, when nothing on it is away (CAT-183). Again is the
        same."""
        with self.db.owner_transaction(owner) as conn:
            row = self._meet(conn, owner, meet)
            if row["archived_at"] is None:
                out = conn.execute(
                    "SELECT 1 FROM meet_tick WHERE meet_id = %s GROUP BY vehicle_id "
                    "HAVING NOT bool_or(step = 'home') LIMIT 1",
                    (meet,),
                ).fetchone()
                if out is not None:
                    raise Refused(
                        422,
                        ProblemCode.NOT_BACK,
                        "Allt är inte hemma än. Bocka av det i Hem, eller ta bort det från "
                        "packlistan.",
                    )
                conn.execute("UPDATE meet SET archived_at = now() WHERE id = %s", (meet,))
            return self._read(conn, owner, meet)
