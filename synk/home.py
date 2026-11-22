"""Träffens hem (H35, SYNK-03, SYNK-16): the hub where the meet is planned and its versions
are published. It moves with one button, to the Pi before the meet and back after, so there is
never a version 5 made in two places.

Each move counts the meet's generation up. A hub that is not the home only looks; what it is
sent from an older generation is refused. A meet with no move noted has its home where it was
made.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Final

from contracts.sync import Home
from core.sqlite import connect, prepare, reading

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS sync_home (
    meet_id TEXT PRIMARY KEY, hub_id TEXT NOT NULL, hub_name TEXT NOT NULL,
    generation INTEGER NOT NULL, since REAL NOT NULL
);
"""


class HomeError(Exception):
    """The message is for the planner."""

    status = 409


class Homes:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        # Ready before any thread uses Planering's file, which the stores share (core/sqlite.py).
        prepare(path, _SCHEMA)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, closing(connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    @contextmanager
    def _reading(self) -> Iterator[sqlite3.Connection]:
        """A transaction that only reads: it takes no write lock, so a write does not hold it up
        (core/sqlite.py)."""
        with reading(self.path) as db:
            yield db

    def home(self, meet: str, me: str, my_name: str) -> Home:
        """The meet's home, as this hub (me) sees it."""
        with self._reading() as db:
            row = db.execute(
                "SELECT hub_id, hub_name, generation, since FROM sync_home WHERE meet_id=?",
                (meet,),
            ).fetchone()
        if row is None:
            return Home(meet=meet, hub_id=me, hub_name=my_name, here=True)
        hub_id, hub_name, generation, since = row
        return Home(
            meet=meet,
            hub_id=hub_id,
            hub_name=hub_name,
            here=hub_id == me,
            generation=generation,
            since=datetime.fromtimestamp(since, UTC),
        )

    def move(self, meet: str, hub_id: str, hub_name: str, generation: int) -> None:
        """The home is now the hub, at the generation."""
        with self._transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO sync_home VALUES (?, ?, ?, ?, ?)",
                (meet, hub_id, hub_name, generation, datetime.now(UTC).timestamp()),
            )

    def elsewhere(self, me: str) -> dict[str, str]:
        """The meets whose home is another hub: the meet and the home's name."""
        with self._reading() as db:
            rows = db.execute(
                "SELECT meet_id, hub_name FROM sync_home WHERE hub_id!=?", (me,)
            ).fetchall()
        return {str(meet): str(name) for meet, name in rows}
