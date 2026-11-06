"""Den här hubben: the hub's name and the local administrator's PIN (first start, H52).

The one who first opens a new hub chooses its name and a PIN, and becomes the local
administrator. Logging in gives a session, kept in an HttpOnly cookie for the pages and usable
as Authorization: Bearer for the Drift API (5.4). Without logging in one can only look (S1).

The PIN is never stored, only an scrypt hash with its own salt. Failed attempts are counted
for the whole hub, so guessing is slow even from many addresses. TrainMeet ID replaces this in
step 6; the local administrator stays as a fallback (section 11).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import token_bytes, token_urlsafe
from threading import Lock
from typing import Final

SESSION_LIFETIME: Final = timedelta(hours=12)
FAILURE_WINDOW: Final = timedelta(minutes=10)
MAX_FAILURES: Final = 10
PIN_PATTERN: Final = re.compile(r"[0-9]{6,12}")
NAME_LIMIT: Final = 40

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hub (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL,
    pin_salt BLOB NOT NULL,
    pin_hash BLOB NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS session (
    token_hash TEXT PRIMARY KEY,
    expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS login_failure (at REAL NOT NULL);
"""


class AlreadySetUp(Exception):
    """The hub already has a PIN; first start cannot be done again from the web."""


class NotSetUp(Exception):
    """The hub has no PIN yet: first start comes first."""


class WrongPin(Exception):
    pass


class TooManyAttempts(Exception):
    """Too many wrong PINs lately; the hub waits before it tries again."""


class InvalidSetup(ValueError):
    pass


@dataclass(frozen=True)
class HubState:
    set_up: bool
    name: str


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_pin(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class LocalLogin:
    def __init__(self, path: Path, default_name: str) -> None:
        self.path = path
        self.default_name = default_name
        self._ready = False
        self._lock = Lock()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if not self._ready:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(self.path)) as db:
                    db.executescript(_SCHEMA)
                self._ready = True
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                yield db

    def state(self) -> HubState:
        with self._transaction() as db:
            row = db.execute("SELECT name FROM hub WHERE id=1").fetchone()
        return HubState(set_up=row is not None, name=row[0] if row else self.default_name)

    def set_up(self, name: str, pin: str) -> str:
        """First start: the hub's name and the PIN. Returns a session for the one who did it."""
        name = " ".join(name.split())
        if not 1 <= len(name) <= NAME_LIMIT:
            raise InvalidSetup("Hubbens namn är 1–40 tecken.")
        if not PIN_PATTERN.fullmatch(pin):
            raise InvalidSetup("PIN-koden är 6–12 siffror.")
        salt = token_bytes(16)
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM hub WHERE id=1").fetchone():
                raise AlreadySetUp()
            db.execute(
                "INSERT INTO hub VALUES (1, ?, ?, ?, ?)",
                (name, salt, _hash_pin(pin, salt), _now().timestamp()),
            )
            return self._new_session(db)

    def log_in(self, pin: str) -> str:
        now = _now()
        with self._transaction() as db:
            row = db.execute("SELECT pin_salt, pin_hash FROM hub WHERE id=1").fetchone()
            if row is None:
                raise NotSetUp()
            db.execute(
                "DELETE FROM login_failure WHERE at<?", ((now - FAILURE_WINDOW).timestamp(),)
            )
            failures = db.execute("SELECT count(*) FROM login_failure").fetchone()[0]
            if failures >= MAX_FAILURES:
                raise TooManyAttempts()
            salt, expected = row
            if not PIN_PATTERN.fullmatch(pin) or not hmac.compare_digest(
                _hash_pin(pin, salt), expected
            ):
                db.execute("INSERT INTO login_failure VALUES (?)", (now.timestamp(),))
                wrong = True
            else:
                wrong = False
                token = self._new_session(db)
        if wrong:
            raise WrongPin()
        return token

    def _new_session(self, db: sqlite3.Connection) -> str:
        now = _now()
        db.execute("DELETE FROM session WHERE expires<=?", (now.timestamp(),))
        token = token_urlsafe(32)
        db.execute(
            "INSERT INTO session VALUES (?, ?)",
            (_token_hash(token), (now + SESSION_LIFETIME).timestamp()),
        )
        return token

    def valid(self, token: str | None) -> bool:
        if not token or len(token) > 120:
            return False
        with self._transaction() as db:
            row = db.execute(
                "SELECT 1 FROM session WHERE token_hash=? AND expires>?",
                (_token_hash(token), _now().timestamp()),
            ).fetchone()
        return row is not None

    def log_out(self, token: str | None) -> None:
        if not token:
            return
        with self._transaction() as db:
            db.execute("DELETE FROM session WHERE token_hash=?", (_token_hash(token),))
