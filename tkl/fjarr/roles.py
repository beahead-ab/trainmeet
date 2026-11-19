"""The remote role, kept on the computer (#36 del c, FR1, TKL47).

TKL started in the remote role has the same first start, PIN and lock as a station's TKL, and its
own row in TKL's store: the remote interlocking's name stands as the station's. What makes it
the remote interlocking is kept here, beside TKL's store, per slot: the name it has in Klienter
and the remote area it asks for. A station's TKL has no row here.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from threading import Lock

from contracts.tkl import TklRemote

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS remote_role (slot TEXT PRIMARY KEY, body TEXT NOT NULL);
"""


class Roles:
    """Which slots run as a remote interlocking, and with which name and area."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._ready = False
        self._lock = Lock()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if not self._ready:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(self.path)) as db:
                    db.executescript(_SCHEMA)
                self.path.chmod(0o600)
                self._ready = True
            with closing(sqlite3.connect(self.path)) as db, db:
                yield db

    def role(self, slot: str | None) -> TklRemote | None:
        """The remote interlocking the slot runs as; None for a station's TKL."""
        if not slot:
            return None
        with self._transaction() as db:
            row = db.execute("SELECT body FROM remote_role WHERE slot=?", (slot,)).fetchone()
        return TklRemote.model_validate_json(row[0]) if row else None

    def keep(self, slot: str, remote: TklRemote) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO remote_role VALUES (?, ?)", (slot, remote.model_dump_json())
            )
