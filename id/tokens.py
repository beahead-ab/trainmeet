"""TrainMeet tokens i ID (#79): saldot, gratiskvoten och reservationerna (TOKEN-06, TOKEN-08).

The balance is kept per person and per club (TK1, TOKEN-12). Each month in Swedish time gives a
free quota, 100 tokens for a person and 300 for a club (TOKEN-14); what is not used is not saved
(TK2). Bought tokens never run out, and the free quota is used first.

An app never draws directly: it reserves before the work, draws what the work cost, and the rest
goes back (TOKEN-24). A reservation nobody draws or returns goes back by itself after a while.
The app's own key makes it safe to ask again: the same key gives the same reservation and draws
nothing twice (TOKEN-28). Every change happens in one short transaction with the account's row
locked, so two calls at once can never spend the same token.

An app that bills its own storage over the free level (Catalog, CAT-132) reserves without a
person: the owner's account pays for what is stored, whoever uploaded it, also at the app's
daily round when no person is there. Only the apps in storage_apps may, and the meter never reads
with such a reservation (id/meter.py).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow

from contracts.id import ProblemCode
from contracts.tokens import (
    TokenBalance,
    TokenDraw,
    TokenOwner,
    TokenOwnerKind,
    TokenReservation,
    TokenReservationState,
    TokenReserve,
)
from id.db import Database
from id.roles import Refused, not_found

FREE_PERSON: Final = 100
"""Månadens gratiskvot per person (TK10, TOKEN-14)."""
FREE_CLUB: Final = 300
"""Månadens gratiskvot per klubb (TK10, TOKEN-14)."""
HOLD: Final = timedelta(minutes=30)
"""How long a reservation is held before it goes back by itself."""
STORAGE_APPS: Final = frozenset({"catalog"})
"""The apps that bill their own storage over the free level (CAT-132, TOKEN-16): they alone may
reserve without a person, from the owner's balance."""


def owner_from(text: str) -> TokenOwner:
    """person:<id> or club:<id>, as the apps ask."""
    kind, _, ident = text.partition(":")
    try:
        return TokenOwner(kind=TokenOwnerKind(kind), id=UUID(ident))
    except ValueError as error:
        raise Refused(422, ProblemCode.INVALID, "owner är person:<id> eller club:<id>.") from error


def no_tokens(available: int, needed: int) -> Refused:
    return Refused(
        402,
        ProblemCode.NO_TOKENS,
        f"Saldot räcker inte: {available} tokens kvar, {needed} behövs. "
        "Köp fler eller använd egen AI.",
    )


class Tokens:
    def __init__(
        self,
        db: Database,
        clock: Callable[[], datetime] | None = None,
        caps: Callable[[], tuple[int, int]] | None = None,
        storage_apps: frozenset[str] = STORAGE_APPS,
    ) -> None:
        """caps: the caps per day for an account and a club (TK15), from the owner page.
        storage_apps: the apps that may reserve without a person, for their storage."""
        self.db = db
        self.clock = clock if clock is not None else lambda: datetime.now(UTC)
        self.caps = caps
        self.storage_apps = storage_apps

    # --- Reading ----------------------------------------------------------------------------

    def balances_for(self, person: UUID) -> list[TokenBalance]:
        """The person's own balance and their clubs', for the web app (TOKEN-01)."""
        with self.db.transaction() as conn:
            clubs = conn.execute(
                "SELECT DISTINCT c.id, c.name FROM role_grant g JOIN club c "
                "ON c.id::text = g.resource_id WHERE g.resource_kind = 'club' "
                "AND g.person_id = %s AND g.role IN ('admin', 'member') ORDER BY c.name",
                (person,),
            ).fetchall()
            owners = [TokenOwner(kind=TokenOwnerKind.PERSON, id=person)]
            owners += [TokenOwner(kind=TokenOwnerKind.CLUB, id=row["id"]) for row in clubs]
            return [self._balance(conn, self._account(conn, owner)) for owner in owners]

    def balance(self, person: UUID, owner: TokenOwner) -> TokenBalance:
        """What an app asks before it starts, to show the price and the balance (TOKEN-01)."""
        with self.db.transaction() as conn:
            self._may_use(conn, person, owner)
            return self._balance(conn, self._account(conn, owner))

    # --- Reserve, draw and return -----------------------------------------------------------

    def reserve(self, app: str, asked: TokenReserve) -> TokenReservation:
        """Hold the amount for the work. Without a person it is the app's own billing of its
        storage (CAT-132), which only the apps in storage_apps may do; the caps per day count
        all the same (TK15)."""
        with self.db.transaction() as conn:
            if asked.person is None:
                self._may_bill_storage(app)
            else:
                self._may_use(conn, asked.person, asked.owner)
            account = self._account(conn, asked.owner)
            same = conn.execute(
                "SELECT * FROM token_reservation WHERE app = %s AND key = %s",
                (app, asked.key),
            ).fetchone()
            if same is not None:
                if same["account_id"] != account["id"] or same["amount"] != asked.amount:
                    raise Refused(
                        409, ProblemCode.CONFLICT, "Nyckeln används redan för en annan reservation."
                    )
                return self._out(conn, account, same)
            month = self._month(conn)
            free_left = self._free_monthly(account) - self._free_used(conn, account, month)
            available = free_left + account["bought"]
            if asked.amount > available:
                raise no_tokens(available, asked.amount)
            if self.caps is not None and asked.amount:
                person_cap, club_cap = self.caps()
                cap = person_cap if asked.owner.kind == TokenOwnerKind.PERSON else club_cap
                today = self._used_today(conn, account["id"])
                if today + asked.amount > cap:
                    raise Refused(
                        429,
                        ProblemCode.TOO_MANY,
                        f"Taket för i dag är nått: {cap} tokens per dygn. Försök i morgon, "
                        "eller använd egen AI.",
                    )
            from_free = min(asked.amount, free_left)
            from_bought = asked.amount - from_free
            conn.execute(
                "INSERT INTO token_month (account_id, month, free_used) VALUES (%s, %s, %s) "
                "ON CONFLICT (account_id, month) DO UPDATE "
                "SET free_used = token_month.free_used + excluded.free_used",
                (account["id"], month, from_free),
            )
            conn.execute(
                "UPDATE token_account SET bought = bought - %s WHERE id = %s",
                (from_bought, account["id"]),
            )
            now = self.clock()
            row = conn.execute(
                "INSERT INTO token_reservation (id, account_id, app, key, person_id, amount, "
                "month, from_free, from_bought, what, at, expires) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                (
                    uuid.uuid4(),
                    account["id"],
                    app,
                    asked.key,
                    asked.person,
                    asked.amount,
                    month,
                    from_free,
                    from_bought,
                    asked.what,
                    now,
                    now + HOLD,
                ),
            ).fetchone()
            assert row is not None
            return self._out(conn, self._account(conn, asked.owner), row)

    def draw(self, app: str, reservation: UUID, asked: TokenDraw) -> TokenReservation:
        """Draw what the work cost; the rest goes back. Asking again gives the same answer."""
        with self.db.transaction() as conn:
            row, account = self._held(conn, app, reservation)
            amount = row["amount"] if asked.amount is None else asked.amount
            if row["state"] == TokenReservationState.DRAWN.value:
                if amount != row["drawn"]:
                    raise Refused(409, ProblemCode.CONFLICT, "Reservationen är redan dragen.")
                return self._out(conn, account, row)
            if row["state"] == TokenReservationState.RETURNED.value:
                raise Refused(
                    409,
                    ProblemCode.CONFLICT,
                    "Reservationen är tillbakalämnad, eller har gått ut. Reservera igen.",
                )
            if amount > row["amount"]:
                raise Refused(
                    422, ProblemCode.INVALID, "Det går inte att dra mer än det reserverade."
                )
            # The free quota was used first, so what is drawn is taken from it first.
            free_drawn = min(amount, row["from_free"])
            self._give_back(
                conn,
                account,
                row,
                row["from_free"] - free_drawn,
                row["from_bought"] - amount + free_drawn,
            )
            settled = conn.execute(
                "UPDATE token_reservation SET state = 'drawn', drawn = %s, settled_at = %s "
                "WHERE id = %s RETURNING *",
                (amount, self.clock(), row["id"]),
            ).fetchone()
            assert settled is not None
            return self._out(conn, self._account_by_id(conn, account["id"]), settled)

    def reservation(self, app: str, reservation: UUID) -> TokenReservation:
        """The app's own reservation as it is now, after the ones that ran out went back."""
        with self.db.transaction() as conn:
            row, account = self._held(conn, app, reservation)
            return self._out(conn, account, row)

    def has_person(self, app: str, reservation: UUID) -> bool:
        """Is the app's reservation for a person's work? One without a person is the app's own
        billing of its storage (CAT-132), or its person's account is removed: the meter never
        reads with it."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT person_id FROM token_reservation WHERE id = %s AND app = %s",
                (reservation, app),
            ).fetchone()
        if row is None:
            raise not_found()
        return row["person_id"] is not None

    def give_back(self, app: str, reservation: UUID) -> TokenReservation:
        """The work did not happen, or failed: everything goes back (TOKEN-24)."""
        with self.db.transaction() as conn:
            row, account = self._held(conn, app, reservation)
            if row["state"] == TokenReservationState.RETURNED.value:
                return self._out(conn, account, row)
            if row["state"] == TokenReservationState.DRAWN.value:
                raise Refused(409, ProblemCode.CONFLICT, "Reservationen är redan dragen.")
            row = self._return(conn, account, row)
            return self._out(conn, self._account_by_id(conn, account["id"]), row)

    def may_manage(self, conn: Connection[DictRow], person: UUID, owner: TokenOwner) -> None:
        """Who changes an account's own AI: the person their own, the club's admin the club's."""
        if owner.kind == TokenOwnerKind.PERSON:
            if owner.id != person:
                raise Refused(403, ProblemCode.FORBIDDEN, "Det här är någon annans konto.")
            return
        admin = conn.execute(
            "SELECT 1 FROM role_grant WHERE resource_kind = 'club' AND resource_id = %s "
            "AND person_id = %s AND role = 'admin'",
            (str(owner.id), person),
        ).fetchone()
        if admin is None:
            raise Refused(
                403, ProblemCode.FORBIDDEN, "Bara klubbens administratör ändrar klubbens egen AI."
            )

    def account_id(self, conn: Connection[DictRow], owner: TokenOwner) -> UUID:
        """The owner's account in a transaction of the caller's, made the first time."""
        found: UUID = self._account(conn, owner)["id"]
        return found

    # --- Inside -----------------------------------------------------------------------------

    def _may_bill_storage(self, app: str) -> None:
        """A reservation without a person: only an app that bills its own storage (CAT-132)."""
        if app not in self.storage_apps:
            raise Refused(
                403,
                ProblemCode.FORBIDDEN,
                "Bara en app som tar betalt för sin lagring reserverar utan en person.",
            )

    def _may_use(self, conn: Connection[DictRow], person: UUID, owner: TokenOwner) -> None:
        """A person uses their own balance, and their club's as its member or admin."""
        if owner.kind == TokenOwnerKind.PERSON:
            if owner.id != person:
                raise Refused(
                    403, ProblemCode.FORBIDDEN, "Ett saldo används bara av den som äger det."
                )
            return
        member = conn.execute(
            "SELECT 1 FROM role_grant WHERE resource_kind = 'club' AND resource_id = %s "
            "AND person_id = %s AND role IN ('admin', 'member')",
            (str(owner.id), person),
        ).fetchone()
        if member is None:
            raise Refused(
                403, ProblemCode.FORBIDDEN, "Klubbens saldo används bara av klubbens medlemmar."
            )

    def _account(self, conn: Connection[DictRow], owner: TokenOwner) -> dict[str, Any]:
        """The owner's account, made the first time, with its row locked for the transaction."""
        column = "person_id" if owner.kind == TokenOwnerKind.PERSON else "club_id"
        table = "person" if owner.kind == TokenOwnerKind.PERSON else "club"
        if conn.execute(f"SELECT 1 FROM {table} WHERE id = %s", (owner.id,)).fetchone() is None:
            raise not_found()
        conn.execute(
            f"INSERT INTO token_account (id, {column}) VALUES (%s, %s) "
            f"ON CONFLICT ({column}) DO NOTHING",
            (uuid.uuid4(), owner.id),
        )
        row = conn.execute(
            f"SELECT * FROM token_account WHERE {column} = %s FOR UPDATE", (owner.id,)
        ).fetchone()
        assert row is not None
        account = dict(row)
        self._expire(conn, account)
        return self._account_by_id(conn, account["id"])

    def _account_by_id(self, conn: Connection[DictRow], account: UUID) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM token_account WHERE id = %s FOR UPDATE", (account,)
        ).fetchone()
        assert row is not None
        return dict(row)

    def _held(
        self, conn: Connection[DictRow], app: str, reservation: UUID
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """The app's own reservation, after the ones that ran out have gone back."""
        found = conn.execute(
            "SELECT account_id FROM token_reservation WHERE id = %s AND app = %s",
            (reservation, app),
        ).fetchone()
        if found is None:
            raise not_found()
        account = self._account_by_id(conn, found["account_id"])
        self._expire(conn, account)
        row = conn.execute(
            "SELECT * FROM token_reservation WHERE id = %s", (reservation,)
        ).fetchone()
        assert row is not None
        return dict(row), self._account_by_id(conn, account["id"])

    def _expire(self, conn: Connection[DictRow], account: dict[str, Any]) -> None:
        for row in conn.execute(
            "SELECT * FROM token_reservation WHERE account_id = %s AND state = 'held' "
            "AND expires <= %s",
            (account["id"], self.clock()),
        ).fetchall():
            self._return(conn, account, dict(row))

    def _return(
        self, conn: Connection[DictRow], account: dict[str, Any], row: dict[str, Any]
    ) -> dict[str, Any]:
        self._give_back(conn, account, row, row["from_free"], row["from_bought"])
        returned = conn.execute(
            "UPDATE token_reservation SET state = 'returned', settled_at = %s WHERE id = %s "
            "RETURNING *",
            (self.clock(), row["id"]),
        ).fetchone()
        assert returned is not None
        return dict(returned)

    def _give_back(
        self,
        conn: Connection[DictRow],
        account: dict[str, Any],
        row: dict[str, Any],
        free: int,
        bought: int,
    ) -> None:
        """Back to where it came from. The free quota only goes back within its own month:
        last month's quota is not saved (TK2)."""
        if free and row["month"] == self._month(conn):
            conn.execute(
                "UPDATE token_month SET free_used = greatest(free_used - %s, 0) "
                "WHERE account_id = %s AND month = %s",
                (free, account["id"], row["month"]),
            )
        if bought:
            conn.execute(
                "UPDATE token_account SET bought = bought + %s WHERE id = %s",
                (bought, account["id"]),
            )

    def _used_today(self, conn: Connection[DictRow], account: UUID) -> int:
        """What an account has reserved or drawn today, in Swedish time (TK15)."""
        row = conn.execute(
            "SELECT coalesce(sum(CASE state WHEN 'held' THEN amount WHEN 'drawn' THEN drawn "
            "ELSE 0 END), 0) AS used FROM token_reservation WHERE account_id = %s AND "
            "(at AT TIME ZONE 'Europe/Stockholm')::date = (%s::timestamptz AT TIME ZONE "
            "'Europe/Stockholm')::date",
            (account, self.clock()),
        ).fetchone()
        return int(row["used"]) if row else 0

    def _month(self, conn: Connection[DictRow]) -> str:
        """The month in Swedish time, from the database, which always has the time zones."""
        row = conn.execute(
            "SELECT to_char(%s::timestamptz AT TIME ZONE 'Europe/Stockholm', 'YYYY-MM') AS m",
            (self.clock(),),
        ).fetchone()
        assert row is not None
        return str(row["m"])

    @staticmethod
    def _free_monthly(account: dict[str, Any]) -> int:
        return FREE_PERSON if account["person_id"] is not None else FREE_CLUB

    def _free_used(self, conn: Connection[DictRow], account: dict[str, Any], month: str) -> int:
        row = conn.execute(
            "SELECT free_used FROM token_month WHERE account_id = %s AND month = %s",
            (account["id"], month),
        ).fetchone()
        return int(row["free_used"]) if row else 0

    def _balance(self, conn: Connection[DictRow], account: dict[str, Any]) -> TokenBalance:
        month = self._month(conn)
        monthly = self._free_monthly(account)
        free_left = max(monthly - self._free_used(conn, account, month), 0)
        held = conn.execute(
            "SELECT coalesce(sum(amount), 0) AS held FROM token_reservation "
            "WHERE account_id = %s AND state = 'held'",
            (account["id"],),
        ).fetchone()
        if account["person_id"] is not None:
            owner = TokenOwner(kind=TokenOwnerKind.PERSON, id=account["person_id"])
            named = conn.execute(
                "SELECT name FROM person WHERE id = %s", (account["person_id"],)
            ).fetchone()
        else:
            owner = TokenOwner(kind=TokenOwnerKind.CLUB, id=account["club_id"])
            named = conn.execute(
                "SELECT name FROM club WHERE id = %s", (account["club_id"],)
            ).fetchone()
        own = conn.execute(
            "SELECT model FROM own_ai WHERE account_id = %s", (account["id"],)
        ).fetchone()
        return TokenBalance(
            owner=owner,
            title=str(named["name"]) if named else "Saldot",
            own_ai=str(own["model"]) if own else None,
            free_left=free_left,
            free_monthly=monthly,
            bought=account["bought"],
            reserved=int(held["held"]) if held else 0,
            available=free_left + account["bought"],
            month=month,
        )

    def _out(
        self, conn: Connection[DictRow], account: dict[str, Any], row: Any
    ) -> TokenReservation:
        return TokenReservation(
            id=row["id"],
            owner=self._balance(conn, account).owner,
            amount=row["amount"],
            drawn=row["drawn"],
            state=TokenReservationState(row["state"]),
            what=row["what"],
            at=row["at"],
            expires=row["expires"],
            balance=self._balance(conn, account),
        )
