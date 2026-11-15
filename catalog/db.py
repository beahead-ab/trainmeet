"""Catalog's PostgreSQL: a pool of connections and short transactions (CAT-40).

Every write is a short transaction that locks the owner's row first, then vehicle and tag, so
two changes at the same time never give half a result. owner_transaction() takes that first
lock. A transaction that waits too long for a lock, or runs too long, is stopped by the
database instead of holding others up.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

# Short transactions (CAT-40): no write waits more than 5 s for a lock or runs over 15 s.
SESSION_OPTIONS = (
    "-c lock_timeout=5s -c statement_timeout=15s -c idle_in_transaction_session_timeout=30s"
)


class UnknownOwner(LookupError):
    """The owner has no row in Catalog."""


class Database:
    def __init__(self, url: str, *, min_size: int = 1, max_size: int = 10) -> None:
        kwargs: dict[str, Any] = {"row_factory": dict_row, "options": SESSION_OPTIONS}
        self.pool: ConnectionPool[Connection[DictRow]] = ConnectionPool(
            url,
            connection_class=Connection[DictRow],
            kwargs=kwargs,
            min_size=min_size,
            max_size=max_size,
            open=False,
            name="catalog",
        )

    def open(self, timeout: float = 30.0) -> None:
        self.pool.open(wait=True, timeout=timeout)

    def close(self) -> None:
        self.pool.close()

    @contextmanager
    def transaction(self) -> Iterator[Connection[DictRow]]:
        """One short transaction: committed when the block ends, rolled back on an error."""
        with self.pool.connection() as conn, conn.transaction():
            yield conn

    @contextmanager
    def owner_transaction(self, owner: UUID) -> Iterator[Connection[DictRow]]:
        """A write for an owner: the owner's row is locked first (CAT-40)."""
        with self.transaction() as conn:
            row = conn.execute("SELECT id FROM owner WHERE id = %s FOR UPDATE", (owner,)).fetchone()
            if row is None:
                raise UnknownOwner(str(owner))
            yield conn

    def ping(self) -> bool:
        """Does the database answer?"""
        try:
            with self.pool.connection(timeout=3.0) as conn:
                conn.execute("SELECT 1").fetchone()
        except Exception:
            return False
        return True
