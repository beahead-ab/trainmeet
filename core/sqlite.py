"""The hub's SQLite files, opened the same way by every store.

Several stores share one file (Planering's: Planning, and Synk's Versions, Links, Homes and
Stations, SYNK-20), and the hub's threads use them at once: the requests, the automation and
Synk in the background. Each store opens a connection per transaction. So that they never
stand in each other's way:

- The file is made ready when its store is made, before any thread runs (prepare): write-ahead
  logging, then the store's tables. Nothing is created later, inside a request.
- Changing a file to write-ahead logging takes the whole file, and SQLite does not wait for
  that as it waits for a write: while another connection writes, it says at once that the
  database is locked. That is why it is done here, and tried again until the wait is over.
- Columns that came after a table's first version are added under the file's write lock
  (add_columns), so that two processes starting on a new file at once never add the same one.
- A transaction waits up to BUSY_SECONDS for another connection's write (connect), rather than
  sqlite3's five seconds: a big import on a Pi can hold the write that long.
- A transaction that only reads (reading) takes no write lock. With write-ahead logging it then
  neither waits for a write nor holds one up: the hub's check of a session on every request
  goes on while an import writes. It sees the file as it was when it first read, to the end,
  and SQLite refuses it a write.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Final

BUSY_SECONDS: Final = 30.0
_AGAIN_SECONDS: Final = 0.01


def connect(path: Path) -> sqlite3.Connection:
    """A connection to the file, whose transactions wait up to BUSY_SECONDS for another
    connection's write before they say that the database is locked."""
    return sqlite3.connect(path, timeout=BUSY_SECONDS)


@contextmanager
def reading(path: Path) -> Iterator[sqlite3.Connection]:
    """A transaction that only reads: deferred, without the write lock that BEGIN IMMEDIATE
    takes, and on a connection that may not write (query_only)."""
    with closing(connect(path)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        try:
            yield db
        finally:
            db.rollback()


def prepare(path: Path, schema: str) -> None:
    """Make the file ready for a store, when the store is made: its folder, write-ahead logging
    and the store's tables (CREATE TABLE IF NOT EXISTS, so that every store on a shared file
    can do it)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as db:
        _write_ahead(db)
        db.executescript(schema)


def add_columns(path: Path, table: str, columns: Iterable[tuple[str, str]]) -> None:
    """Add the columns the table does not have yet, in order. The table is read and changed in
    one write transaction, so a second process that starts on the same file at the same time
    waits, then finds the columns there and adds nothing."""
    with closing(connect(path)) as db:
        db.execute("BEGIN IMMEDIATE")
        present = {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})")}
        for column, kind in columns:
            if column not in present:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        db.commit()


def _write_ahead(db: sqlite3.Connection) -> None:
    """Write-ahead logging, which the file keeps once it has it: a write no longer waits for
    the readers to commit, and nothing changes the file's journal while the hub runs. A busy
    file is tried again until BUSY_SECONDS have passed, since SQLite does not wait here."""
    deadline = time.monotonic() + BUSY_SECONDS
    while True:
        try:
            db.execute("PRAGMA journal_mode=WAL").fetchall()
            return
        except sqlite3.OperationalError as error:
            busy = error.sqlite_errorcode & 0xFF == sqlite3.SQLITE_BUSY
            if not busy or time.monotonic() >= deadline:
                raise
        time.sleep(_AGAIN_SECONDS)
