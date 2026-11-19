"""CAD's PostgreSQL: a pool of connections and short transactions, as Catalog's (CAT-40).

A save locks the module's row first, so two saves at the same time never make the same version
twice. A transaction that waits too long for a lock, or runs too long, is stopped by the
database instead of holding others up.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

SESSION_OPTIONS = (
    "-c lock_timeout=5s -c statement_timeout=15s -c idle_in_transaction_session_timeout=30s"
)


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
            name="cad",
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

    def ping(self) -> bool:
        """Does the database answer?"""
        try:
            with self.pool.connection(timeout=3.0) as conn:
                conn.execute("SELECT 1").fetchone()
        except Exception:
            return False
        return True
