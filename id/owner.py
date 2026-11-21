"""Ägarsidan (#79, TOKEN-05, TOKEN-18, TK6, TK15): faktorerna, budgeten och taken.

TrainMeet's owner sets the factors, the month's budget for TrainMeets AI and the caps per day for
an account and a club, and sees the cost, the revenue and what the factor makes of the measured
cost per page. The month's budget raises an alarm by mail to the owners at 80 % and stops
TrainMeets AI at 100 %; own AI goes on. Nobody can use up the owner's limits at the AI provider.

The owner also gives and takes the role Granskare in Catalog (KONTO-30, ID6, CAT-165): reviewer
on catalog:prototypes, for a person who has logged in to ID, named by their verified address.
Catalog asks for it at every call, so a change applies at once.

The owners are named by their verified address in a file in ID's vault, never in the code:

ID_OWNERS_FILE   One address per line. Without the file nobody sees the owner page.
"""

from __future__ import annotations

import logging
import math
import os
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow

from contracts.id import (
    PROTOTYPE_REVIEWERS,
    Grant,
    Person,
    ProblemCode,
    Resource,
    ResourceKind,
    Role,
)
from contracts.tokens import (
    TOKENS_PER_PAGE,
    TOKENS_PER_SEARCH,
    OwnerPage,
    TokenMonth,
    TokenSettings,
)
from id.db import Database
from id.roles import Asker, Refused, initials

LOGGER = logging.getLogger("id.owner")

TOKEN_VALUE_SEK: Final = 39.20 / 500
"""What a token brings in without VAT on the smallest package: 49 kr is 39,20 kr (TK10)."""


def owners_from(env: Mapping[str, str] | None = None) -> Path | None:
    source = os.environ if env is None else env
    found = source.get("ID_OWNERS_FILE", "").strip()
    return Path(found) if found else None


class Owner:
    def __init__(
        self,
        db: Database,
        owners_file: Path | None,
        alarm: Callable[[str, str, str], None] = lambda to, subject, body: None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db = db
        self.owners_file = owners_file
        self.alarm = alarm
        self.clock = clock if clock is not None else lambda: datetime.now(UTC)

    # --- Who --------------------------------------------------------------------------------

    def owners(self) -> set[str]:
        if self.owners_file is None:
            return set()
        try:
            lines = self.owners_file.read_text(encoding="utf-8").split()
        except OSError:
            return set()
        return {line.strip().lower() for line in lines if "@" in line}

    def is_owner(self, email: str) -> bool:
        return email.lower() in self.owners()

    def _require(self, asker: Asker) -> None:
        if not self.is_owner(asker.email):
            raise Refused(403, ProblemCode.FORBIDDEN, "Ägarsidan är för TrainMeets ägare.")

    # --- The settings -----------------------------------------------------------------------

    def settings(self, conn: Connection[DictRow] | None = None) -> TokenSettings:
        if conn is None:
            with self.db.transaction() as own:
                return self.settings(own)
        row = conn.execute("SELECT * FROM token_settings WHERE id = 1").fetchone()
        assert row is not None
        return TokenSettings(
            ai_factor=float(row["ai_factor"]),
            storage_factor=float(row["storage_factor"]),
            monthly_budget_sek=int(row["monthly_budget_sek"]),
            daily_cap_person=int(row["daily_cap_person"]),
            daily_cap_club=int(row["daily_cap_club"]),
            usd_sek=float(row["usd_sek"]),
            price_in_usd=float(row["price_in_usd"]),
            price_out_usd=float(row["price_out_usd"]),
        )

    def caps(self) -> tuple[int, int]:
        """The caps per day: an account's, and a club's (TK15)."""
        found = self.settings()
        return found.daily_cap_person, found.daily_cap_club

    def change(self, asker: Asker, given: TokenSettings) -> OwnerPage:
        self._require(asker)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE token_settings SET ai_factor = %s, storage_factor = %s, "
                "monthly_budget_sek = %s, daily_cap_person = %s, daily_cap_club = %s, "
                "usd_sek = %s, price_in_usd = %s, price_out_usd = %s, changed_at = %s, "
                "changed_by = %s WHERE id = 1",
                (
                    given.ai_factor,
                    given.storage_factor,
                    given.monthly_budget_sek,
                    given.daily_cap_person,
                    given.daily_cap_club,
                    given.usd_sek,
                    given.price_in_usd,
                    given.price_out_usd,
                    self.clock(),
                    asker.id,
                ),
            )
        return self.page(asker)

    # --- Granskare i Catalog (KONTO-30, ID6, CAT-165) ----------------------------------------

    REVIEWERS: Final = Resource(kind=ResourceKind.CATALOG, id=PROTOTYPE_REVIEWERS)

    def reviewers(self, asker: Asker) -> list[Grant]:
        """The people who review Catalog's prototypes."""
        self._require(asker)
        with self.db.transaction() as conn:
            return self._reviewers(conn)

    def _reviewers(self, conn: Connection[DictRow]) -> list[Grant]:
        rows = conn.execute(
            "SELECT g.id AS grant_id, g.at, p.id, p.name FROM role_grant g "
            "JOIN person p ON p.id = g.person_id WHERE g.resource_kind = %s "
            "AND g.resource_id = %s AND g.role = %s ORDER BY lower(p.name), g.at",
            (self.REVIEWERS.kind.value, self.REVIEWERS.id, Role.REVIEWER.value),
        ).fetchall()
        return [
            Grant(
                id=row["grant_id"],
                person=Person(id=row["id"], name=row["name"], initials=initials(row["name"])),
                role=Role.REVIEWER,
                resource=self.REVIEWERS,
                at=row["at"],
            )
            for row in rows
        ]

    def give_reviewer(self, asker: Asker, email: str) -> list[Grant]:
        """The role to the person with the address, who must have logged in to ID once. Given
        twice, it is still one role."""
        self._require(asker)
        with self.db.transaction() as conn:
            found = conn.execute("SELECT id FROM person WHERE email = %s", (email,)).fetchone()
            if found is None:
                raise Refused(
                    404,
                    ProblemCode.NOT_FOUND,
                    "Ingen med den adressen har loggat in i TrainMeet ID än.",
                )
            conn.execute(
                "INSERT INTO role_grant (id, person_id, role, resource_kind, resource_id, "
                "granted_by) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (
                    uuid.uuid4(),
                    found["id"],
                    Role.REVIEWER.value,
                    self.REVIEWERS.kind.value,
                    self.REVIEWERS.id,
                    asker.id,
                ),
            )
            return self._reviewers(conn)

    def take_reviewer(self, asker: Asker, person: UUID) -> list[Grant]:
        """The role taken back. It applies at once in Catalog."""
        self._require(asker)
        with self.db.transaction() as conn:
            gone = conn.execute(
                "DELETE FROM role_grant WHERE person_id = %s AND role = %s "
                "AND resource_kind = %s AND resource_id = %s RETURNING id",
                (person, Role.REVIEWER.value, self.REVIEWERS.kind.value, self.REVIEWERS.id),
            ).fetchall()
            if not gone:
                raise Refused(404, ProblemCode.NOT_FOUND, "Personen är inte granskare.")
            return self._reviewers(conn)

    # --- The budget -------------------------------------------------------------------------

    def allow(self) -> None:
        """Before TrainMeets AI is asked: the month's budget stops it at 100 % (TK15)."""
        with self.db.transaction() as conn:
            month = self._month(conn)
            used = self._used(conn, month)
        if used >= 100:
            self._alarm(month, 100)
            raise Refused(
                503,
                ProblemCode.UNAVAILABLE,
                "TrainMeets AI har nått månadens budget. Använd egen AI, eller försök nästa månad.",
            )

    def record(
        self,
        pages: int,
        input_tokens: int,
        output_tokens: int,
        *,
        searches: int = 0,
        extra_usd: float = 0.0,
    ) -> None:
        """What a reading cost, in kronor, as AWS counts the tokens; or a web search, as
        Anthropic counts the tokens, with what the searches cost beside them (TOKEN-30)."""
        with self.db.transaction() as conn:
            found = self.settings(conn)
            usd = (input_tokens * found.price_in_usd + output_tokens * found.price_out_usd) / 1e6
            usd += max(extra_usd, 0.0)
            month = self._month(conn)
            conn.execute(
                "INSERT INTO meter_usage (at, month, pages, searches, input_tokens, "
                "output_tokens, cost_sek) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    self.clock(),
                    month,
                    pages,
                    searches,
                    input_tokens,
                    output_tokens,
                    usd * found.usd_sek,
                ),
            )
            used = self._used(conn, month)
        if used >= 80:
            self._alarm(month, 80 if used < 100 else 100)

    def _used(self, conn: Connection[DictRow], month: str) -> int:
        budget = self.settings(conn).monthly_budget_sek
        cost = self._cost(conn, month)
        if budget <= 0:
            return 100 if cost > 0 else 0
        return math.floor(100 * cost / budget)

    def _cost(self, conn: Connection[DictRow], month: str) -> float:
        row = conn.execute(
            "SELECT coalesce(sum(cost_sek), 0) AS cost FROM meter_usage WHERE month = %s", (month,)
        ).fetchone()
        return float(row["cost"]) if row else 0.0

    def _alarm(self, month: str, level: int) -> None:
        """Once per month and level, by mail to the owners."""
        with self.db.transaction() as conn:
            first = conn.execute(
                "INSERT INTO budget_alarm (month, level, at) VALUES (%s, %s, %s) "
                "ON CONFLICT DO NOTHING RETURNING level",
                (month, level, self.clock()),
            ).fetchone()
        if first is None:
            return
        LOGGER.warning("TrainMeets AI har använt %s %% av budgeten för %s.", level, month)
        subject = (
            f"TrainMeets AI har använt {level} % av månadens budget"
            if level < 100
            else "TrainMeets AI har stannat: månadens budget är slut"
        )
        body = f"TrainMeets AI har använt {level} % av budgeten för {month}. " + (
            "Den stannar vid 100 %, och egen AI fungerar som förut."
            if level < 100
            else "Den läser inget mer den här månaden. Egen AI fungerar som förut. "
            "Budgeten ändras på ägarsidan i TrainMeet ID."
        )
        for to in sorted(self.owners()):
            try:
                self.alarm(to, subject, body)
            except Exception:
                LOGGER.warning("Larmet om budgeten gick inte att skicka.")

    # --- The page ---------------------------------------------------------------------------

    def page(self, asker: Asker) -> OwnerPage:
        self._require(asker)
        with self.db.transaction() as conn:
            found = self.settings(conn)
            month = self._month(conn)
            last = self._month(conn, "1 month")
            # A row is a reading's pages or a search's searches, never both.
            measured = conn.execute(
                "SELECT coalesce(sum(cost_sek) FILTER (WHERE pages > 0), 0) AS cost, "
                "coalesce(sum(pages), 0) AS pages, "
                "coalesce(sum(cost_sek) FILTER (WHERE searches > 0), 0) AS search_cost, "
                "count(*) FILTER (WHERE searches > 0) AS searched "
                "FROM meter_usage WHERE at >= %s::timestamptz - interval '30 days'",
                (self.clock(),),
            ).fetchone()
            assert measured is not None
            per_page = (
                float(measured["cost"]) / int(measured["pages"]) if measured["pages"] else None
            )
            per_search = (
                float(measured["search_cost"]) / int(measured["searched"])
                if measured["searched"]
                else None
            )
            months = [self._month_out(conn, m) for m in (month, last)]
            used = self._used(conn, month)
        return OwnerPage(
            settings=found,
            page_tokens=TOKENS_PER_PAGE,
            cost_per_page_sek=round(per_page, 4) if per_page is not None else None,
            factor_page_tokens=(
                max(1, math.ceil(per_page * found.ai_factor / TOKEN_VALUE_SEK))
                if per_page is not None
                else None
            ),
            search_tokens=TOKENS_PER_SEARCH,
            cost_per_search_sek=round(per_search, 4) if per_search is not None else None,
            factor_search_tokens=(
                max(1, math.ceil(per_search * found.ai_factor / TOKEN_VALUE_SEK))
                if per_search is not None
                else None
            ),
            budget_used=used,
            months=months,
        )

    def _month_out(self, conn: Connection[DictRow], month: str) -> TokenMonth:
        paid = conn.execute(
            "SELECT coalesce(sum(price_sek) FILTER (WHERE mode = 'live'), 0) AS live, "
            "coalesce(sum(price_sek) FILTER (WHERE mode = 'test'), 0) AS test FROM token_purchase "
            "WHERE state = 'paid' AND to_char(paid_at AT TIME ZONE 'Europe/Stockholm', "
            "'YYYY-MM') = %s",
            (month,),
        ).fetchone()
        used = conn.execute(
            "SELECT coalesce(sum(pages), 0) AS pages, "
            "count(*) FILTER (WHERE searches > 0) AS searches "
            "FROM meter_usage WHERE month = %s",
            (month,),
        ).fetchone()
        assert paid is not None and used is not None
        return TokenMonth(
            month=month,
            revenue_sek=float(paid["live"]),
            test_revenue_sek=float(paid["test"]),
            cost_sek=round(self._cost(conn, month), 2),
            pages=int(used["pages"]),
            searches=int(used["searches"]),
        )

    def _month(self, conn: Connection[DictRow], back: str = "0 months") -> str:
        row = conn.execute(
            "SELECT to_char((%s::timestamptz - %s::interval) AT TIME ZONE 'Europe/Stockholm', "
            "'YYYY-MM') AS m",
            (self.clock(), back),
        ).fetchone()
        assert row is not None
        return str(row["m"])
