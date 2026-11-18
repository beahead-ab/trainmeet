"""What TKL keeps on the computer (KLAR-08): the station, its outside and its versions, the PIN
that locks it, and the connection to a meet with the key from the approval.

From level 1 the station also has its model (contracts/station_model.py, #83). It is kept with
the station and versioned with the outside: a new version of the outside holds the model as it
was, and both go to the cloud together as the station package (SYNK-30).

The PIN is never stored, only an scrypt hash with its own salt, and wrong attempts are counted
so that guessing stays slow. The key is kept here and nowhere else: it never reaches the browser
or a log (H31).

Locally TKL has one station. TKL in the cloud keeps one station per browser, behind a cookie of
its own, until TrainMeet ID gives each owner their stations (TKL5); those stations go away after
a month without use.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import token_bytes, token_urlsafe
from threading import Lock
from typing import Final

from contracts import station
from contracts.common import Side
from contracts.station_model import StationModel, to_json
from contracts.station_outside import Exit, StationOutside, StationTrack
from contracts.tkl import OutsideVersion, TklStation, TklStudio

LOCAL: Final = "lokal"
SESSION_LIFETIME: Final = timedelta(hours=12)
SLOT_LIFETIME: Final = timedelta(days=30)
FAILURE_WINDOW: Final = timedelta(minutes=10)
MAX_FAILURES: Final = 10
MAX_SLOTS: Final = 500
MAX_VERSIONS: Final = 200
PIN_PATTERN: Final = re.compile(r"[0-9]{4,12}")

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS station (
    slot TEXT PRIMARY KEY, station_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL,
    pin_salt BLOB NOT NULL, pin_hash BLOB NOT NULL, draft TEXT NOT NULL,
    created REAL NOT NULL, used REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS outside_version (
    slot TEXT NOT NULL REFERENCES station(slot) ON DELETE CASCADE,
    number INTEGER NOT NULL, saved REAL NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (slot, number)
);
CREATE TABLE IF NOT EXISTS session (
    token_hash TEXT PRIMARY KEY,
    slot TEXT NOT NULL REFERENCES station(slot) ON DELETE CASCADE,
    expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS failure (slot TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS id_login (
    key_hash TEXT PRIMARY KEY, slot TEXT NOT NULL, state TEXT NOT NULL, nonce TEXT NOT NULL,
    verifier TEXT NOT NULL, expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS id_account (
    slot TEXT PRIMARY KEY REFERENCES station(slot) ON DELETE CASCADE,
    person TEXT NOT NULL, name TEXT NOT NULL, access TEXT NOT NULL, refresh TEXT,
    access_until REAL NOT NULL, saved INTEGER
);
CREATE TABLE IF NOT EXISTS connection (
    slot TEXT PRIMARY KEY REFERENCES station(slot) ON DELETE CASCADE,
    address TEXT NOT NULL, relay TEXT, hub_name TEXT, client_id TEXT NOT NULL,
    status TEXT NOT NULL, places TEXT NOT NULL, key TEXT, outside_version INTEGER NOT NULL,
    message TEXT
);
CREATE TABLE IF NOT EXISTS station_model (
    slot TEXT PRIMARY KEY REFERENCES station(slot) ON DELETE CASCADE, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_version (
    slot TEXT NOT NULL, number INTEGER NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (slot, number),
    FOREIGN KEY (slot, number) REFERENCES outside_version(slot, number) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS seen (
    slot TEXT NOT NULL REFERENCES station(slot) ON DELETE CASCADE,
    place TEXT NOT NULL, body TEXT NOT NULL, heard REAL NOT NULL,
    PRIMARY KEY (slot, place)
);
"""


class NotSetUp(Exception):
    """No station yet: first start comes first."""


class AlreadySetUp(Exception):
    """The local TKL already has its station."""


class WrongPin(Exception):
    pass


class TooManyAttempts(Exception):
    """Too many wrong PINs lately; TKL waits before it tries again."""


class Full(Exception):
    """TKL in the cloud has as many stations as it takes."""


class NotConnected(Exception):
    """TKL is not connected to a meet, or not approved yet."""


def now_utc() -> datetime:
    return datetime.now(UTC)


def _hash_pin(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def first_outside(station_id: str, name: str) -> StationOutside:
    """The list a new station starts with: two tracks and an exit on each side."""
    return StationOutside(
        station_id=station_id,
        name=name,
        tracks=[StationTrack(id="1", label="Spår 1"), StationTrack(id="2", label="Spår 2")],
        exits=[Exit(id="A", side=Side.LEFT), Exit(id="B", side=Side.RIGHT)],
    )


@dataclass(frozen=True)
class IdAccount:
    """Who is logged in with TrainMeet ID for the station, and ID's tokens. Never shown."""

    person: str
    name: str
    access: str = field(repr=False)
    refresh: str | None = field(repr=False)
    access_until: float
    saved: int | None


@dataclass(frozen=True)
class Connection:
    address: str
    relay: str | None
    hub_name: str | None
    client_id: str
    status: station.ApprovalStatus
    places: list[str]
    outside_version: int
    message: str | None
    key: str | None = field(default=None, repr=False)


class TklStore:
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
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("BEGIN IMMEDIATE")
                yield db

    # --- The station and the PIN ------------------------------------------------------------

    def station_of(self, slot: str | None) -> TklStation | None:
        if not slot:
            return None
        with self._transaction() as db:
            row = db.execute(
                "SELECT station_id, name, level FROM station WHERE slot=?", (slot,)
            ).fetchone()
        return None if row is None else TklStation(station_id=row[0], name=row[1], level=row[2])

    def set_up(self, slot: str, station_id: str, name: str, pin: str) -> str:
        """Första start: the station and the PIN. Returns a session for the one who did it."""
        name = " ".join(name.split())
        if not PIN_PATTERN.fullmatch(pin):
            raise WrongPin()
        salt = token_bytes(16)
        now = now_utc()
        draft = first_outside(station_id, name)
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM station WHERE slot=?", (slot,)).fetchone():
                raise AlreadySetUp()
            db.execute("DELETE FROM station WHERE used<?", ((now - SLOT_LIFETIME).timestamp(),))
            if db.execute("SELECT count(*) FROM station").fetchone()[0] >= MAX_SLOTS:
                raise Full()
            db.execute(
                "INSERT INTO station VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?)",
                (
                    slot,
                    station_id,
                    name,
                    salt,
                    _hash_pin(pin, salt),
                    draft.model_dump_json(),
                    now.timestamp(),
                    now.timestamp(),
                ),
            )
            return self._new_session(db, slot)

    def unlock(self, slot: str, pin: str) -> str:
        with self._transaction() as db:
            right = self._pin_right(db, slot, pin)
            token = self._new_session(db, slot) if right else ""
        if not right:
            raise WrongPin()
        return token

    def change_pin(self, slot: str, pin: str, new_pin: str, keep: str) -> None:
        """Byt PIN: the current one first. Every other session ends."""
        if not PIN_PATTERN.fullmatch(new_pin):
            raise WrongPin()
        with self._transaction() as db:
            right = self._pin_right(db, slot, pin)
            if right:
                salt = token_bytes(16)
                db.execute(
                    "UPDATE station SET pin_salt=?, pin_hash=? WHERE slot=?",
                    (salt, _hash_pin(new_pin, salt), slot),
                )
                db.execute(
                    "DELETE FROM session WHERE slot=? AND token_hash!=?", (slot, token_hash(keep))
                )
        if not right:
            raise WrongPin()

    def _pin_right(self, db: sqlite3.Connection, slot: str, pin: str) -> bool:
        now = now_utc()
        row = db.execute("SELECT pin_salt, pin_hash FROM station WHERE slot=?", (slot,)).fetchone()
        if row is None:
            raise NotSetUp()
        db.execute("DELETE FROM failure WHERE at<?", ((now - FAILURE_WINDOW).timestamp(),))
        failures = db.execute("SELECT count(*) FROM failure WHERE slot=?", (slot,)).fetchone()[0]
        if failures >= MAX_FAILURES:
            raise TooManyAttempts()
        salt, expected = row
        if not PIN_PATTERN.fullmatch(pin) or not hmac.compare_digest(
            _hash_pin(pin, salt), expected
        ):
            db.execute("INSERT INTO failure VALUES (?, ?)", (slot, now.timestamp()))
            return False
        return True

    def _new_session(self, db: sqlite3.Connection, slot: str) -> str:
        now = now_utc()
        db.execute("DELETE FROM session WHERE expires<=?", (now.timestamp(),))
        token = token_urlsafe(32)
        db.execute(
            "INSERT INTO session VALUES (?, ?, ?)",
            (token_hash(token), slot, (now + SESSION_LIFETIME).timestamp()),
        )
        db.execute("UPDATE station SET used=? WHERE slot=?", (now.timestamp(), slot))
        return token

    def unlocked(self, slot: str | None, session: str | None) -> bool:
        if not slot or not session or len(session) > 120:
            return False
        with self._transaction() as db:
            row = db.execute(
                "SELECT 1 FROM session WHERE token_hash=? AND slot=? AND expires>?",
                (token_hash(session), slot, now_utc().timestamp()),
            ).fetchone()
        return row is not None

    def lock(self, session: str | None) -> None:
        if session:
            with self._transaction() as db:
                db.execute("DELETE FROM session WHERE token_hash=?", (token_hash(session),))

    # --- Studio at level 0: the list and its versions (TKL21, TKL25) ------------------------

    def studio(self, slot: str) -> TklStudio:
        with self._transaction() as db:
            return self._studio(db, slot)

    def _studio(self, db: sqlite3.Connection, slot: str) -> TklStudio:
        row = db.execute("SELECT draft FROM station WHERE slot=?", (slot,)).fetchone()
        if row is None:
            raise NotSetUp()
        draft = StationOutside.model_validate_json(row[0])
        versions = db.execute(
            "SELECT number, saved, body FROM outside_version WHERE slot=? ORDER BY number DESC",
            (slot,),
        ).fetchall()
        latest = StationOutside.model_validate_json(versions[0][2]) if versions else None
        model = self._model(db, slot)
        latest_model = self._model_of(db, slot, versions[0][0]) if versions else None
        return TklStudio(
            draft=draft,
            versions=[
                OutsideVersion(number=number, saved=datetime.fromtimestamp(saved, UTC))
                for number, saved, _ in versions
            ],
            changed=latest != draft or latest_model != model,
            station_model=model is not None,
        )

    @staticmethod
    def _model(db: sqlite3.Connection, slot: str) -> str | None:
        row = db.execute("SELECT body FROM station_model WHERE slot=?", (slot,)).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _model_of(db: sqlite3.Connection, slot: str, number: int) -> str | None:
        row = db.execute(
            "SELECT body FROM model_version WHERE slot=? AND number=?", (slot, number)
        ).fetchone()
        return None if row is None else str(row[0])

    # --- The station's model (#83): kept with the station, versioned with the outside ------

    def station_model(self, slot: str) -> StationModel | None:
        with self._transaction() as db:
            body = self._model(db, slot)
        return None if body is None else StationModel.model_validate_json(body)

    def save_model(self, slot: str, model: StationModel) -> StationModel:
        """The station's model, with the station's own id and name. The station's level
        follows it: 1 or 2; level 3 needs the addresses on the bus, which come later."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT station_id, name FROM station WHERE slot=?", (slot,)
            ).fetchone()
            if row is None:
                raise NotSetUp()
            kept = model.model_copy(update={"station_id": row[0], "name": row[1]})
            db.execute("INSERT OR REPLACE INTO station_model VALUES (?, ?)", (slot, to_json(kept)))
            db.execute("UPDATE station SET level=? WHERE slot=?", (min(kept.level, 2), slot))
        return kept

    def forget_model(self, slot: str) -> None:
        """Back to level 0: the list without a model."""
        with self._transaction() as db:
            db.execute("DELETE FROM station_model WHERE slot=?", (slot,))
            db.execute("UPDATE station SET level=0 WHERE slot=?", (slot,))

    def save_draft(self, slot: str, outside: StationOutside) -> TklStudio:
        """The list as it stands, saved on the computer. Its id and name are the station's."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT station_id, name FROM station WHERE slot=?", (slot,)
            ).fetchone()
            if row is None:
                raise NotSetUp()
            kept = outside.model_copy(update={"station_id": row[0], "name": row[1]})
            db.execute("UPDATE station SET draft=? WHERE slot=?", (kept.model_dump_json(), slot))
            return self._studio(db, slot)

    def new_version(self, slot: str) -> TklStudio:
        """Ny version av utsidan: the list as it is becomes the next version. The same list
        again makes no new one."""
        with self._transaction() as db:
            studio = self._studio(db, slot)
            if studio.changed:
                number = (studio.versions[0].number if studio.versions else 0) + 1
                if number > MAX_VERSIONS:
                    db.execute(
                        "DELETE FROM outside_version WHERE slot=? AND number<=?",
                        (slot, number - MAX_VERSIONS),
                    )
                db.execute(
                    "INSERT INTO outside_version VALUES (?, ?, ?, ?)",
                    (slot, number, now_utc().timestamp(), studio.draft.model_dump_json()),
                )
                model = self._model(db, slot)
                if model is not None:
                    db.execute("INSERT INTO model_version VALUES (?, ?, ?)", (slot, number, model))
            return self._studio(db, slot)

    def latest_outside(self, slot: str) -> tuple[int, StationOutside]:
        """The latest version, made from the list if there is none yet."""
        number, outside, _ = self.latest_package(slot)
        return number, outside

    def latest_package(self, slot: str) -> tuple[int, StationOutside, StationModel | None]:
        """The latest version: the outside, and the model as it was then, if any."""
        studio = self.studio(slot)
        if not studio.versions:
            studio = self.new_version(slot)
        number = studio.versions[0].number
        with self._transaction() as db:
            body = db.execute(
                "SELECT body FROM outside_version WHERE slot=? AND number=?", (slot, number)
            ).fetchone()[0]
            model = self._model_of(db, slot, number)
        return (
            number,
            StationOutside.model_validate_json(body),
            None if model is None else StationModel.model_validate_json(model),
        )

    # --- TrainMeet ID (TKL18, #78) and the cloud (SYNK-30) -------------------------------------

    def begin_id_login(self, slot: str, state: str, nonce: str, verifier: str) -> str:
        """Keeps a login with ID while the browser is at ID. Returns the browser's key to it."""
        key = token_urlsafe(32)
        now = now_utc().timestamp()
        with self._transaction() as db:
            db.execute("DELETE FROM id_login WHERE expires<=?", (now,))
            db.execute(
                "INSERT INTO id_login VALUES (?, ?, ?, ?, ?, ?)",
                (token_hash(key), slot, state, nonce, verifier, now + 600),
            )
        return key

    def take_id_login(self, key: str | None) -> tuple[str, str, str, str] | None:
        """The slot, state, nonce and verifier of the login this browser started, once."""
        if not key or len(key) > 120:
            return None
        with self._transaction() as db:
            row = db.execute(
                "SELECT slot, state, nonce, verifier FROM id_login WHERE key_hash=? AND expires>?",
                (token_hash(key), now_utc().timestamp()),
            ).fetchone()
            db.execute("DELETE FROM id_login WHERE key_hash=?", (token_hash(key),))
        return (str(row[0]), str(row[1]), str(row[2]), str(row[3])) if row else None

    def keep_account(
        self,
        slot: str,
        person: str,
        name: str,
        access: str,
        refresh: str | None,
        access_until: float,
    ) -> None:
        """The person from ID, with the station. A new person starts over in the cloud."""
        with self._transaction() as db:
            before = db.execute("SELECT person FROM id_account WHERE slot=?", (slot,)).fetchone()
            saved = None
            if before is not None and str(before[0]) == person:
                saved = db.execute("SELECT saved FROM id_account WHERE slot=?", (slot,)).fetchone()[
                    0
                ]
            db.execute(
                "INSERT OR REPLACE INTO id_account VALUES (?, ?, ?, ?, ?, ?, ?)",
                (slot, person, name, access, refresh, access_until, saved),
            )

    def account(self, slot: str) -> IdAccount | None:
        with self._transaction() as db:
            row = db.execute(
                "SELECT person, name, access, refresh, access_until, saved FROM id_account "
                "WHERE slot=?",
                (slot,),
            ).fetchone()
        if row is None:
            return None
        return IdAccount(str(row[0]), str(row[1]), str(row[2]), row[3], float(row[4]), row[5])

    def new_tokens(self, slot: str, access: str, refresh: str | None, until: float) -> None:
        with self._transaction() as db:
            db.execute(
                "UPDATE id_account SET access=?, refresh=?, access_until=? WHERE slot=?",
                (access, refresh, until, slot),
            )

    def saved_in_cloud(self, slot: str, version: int) -> None:
        with self._transaction() as db:
            db.execute("UPDATE id_account SET saved=? WHERE slot=?", (version, slot))

    def forget_account(self, slot: str) -> None:
        with self._transaction() as db:
            db.execute("DELETE FROM id_account WHERE slot=?", (slot,))

    # --- The connection to a meet ------------------------------------------------------------

    def connection(self, slot: str) -> Connection | None:
        with self._transaction() as db:
            row = db.execute(
                "SELECT address, relay, hub_name, client_id, status, places, outside_version, "
                "message, key FROM connection WHERE slot=?",
                (slot,),
            ).fetchone()
        if row is None:
            return None
        return Connection(
            address=row[0],
            relay=row[1],
            hub_name=row[2],
            client_id=row[3],
            status=station.ApprovalStatus(row[4]),
            places=list(json.loads(row[5])),
            outside_version=row[6],
            message=row[7],
            key=row[8],
        )

    def connected(self, slot: str, made: Connection) -> None:
        """A new connection replaces the one before, and what was seen with it."""
        with self._transaction() as db:
            db.execute("DELETE FROM seen WHERE slot=?", (slot,))
            db.execute(
                "INSERT OR REPLACE INTO connection VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    slot,
                    made.address,
                    made.relay,
                    made.hub_name,
                    made.client_id,
                    made.status.value,
                    json.dumps(made.places),
                    made.key,
                    made.outside_version,
                    made.message,
                ),
            )

    def approval(
        self,
        slot: str,
        status: station.ApprovalStatus,
        places: list[str],
        key: str | None,
        message: str | None = None,
    ) -> None:
        """How the approval stands. A key arrives once and is kept; a revoked one is dropped."""
        with self._transaction() as db:
            if key is not None:
                db.execute("UPDATE connection SET key=? WHERE slot=?", (key, slot))
            if status in (station.ApprovalStatus.REVOKED, station.ApprovalStatus.REFUSED):
                db.execute("UPDATE connection SET key=NULL WHERE slot=?", (slot,))
            db.execute(
                "UPDATE connection SET status=?, places=?, message=? WHERE slot=?",
                (status.value, json.dumps(places), message, slot),
            )

    def disconnect(self, slot: str) -> None:
        with self._transaction() as db:
            db.execute("DELETE FROM connection WHERE slot=?", (slot,))
            db.execute("DELETE FROM seen WHERE slot=?", (slot,))

    def remember(self, slot: str, snapshot: station.Snapshot) -> datetime:
        """The last good snapshot of a place, for when the hub cannot be reached."""
        heard = now_utc()
        with self._transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO seen VALUES (?, ?, ?, ?)",
                (slot, snapshot.place.place, snapshot.model_dump_json(), heard.timestamp()),
            )
        return heard

    def last_seen(self, slot: str, place: str) -> tuple[station.Snapshot, datetime] | None:
        with self._transaction() as db:
            row = db.execute(
                "SELECT body, heard FROM seen WHERE slot=? AND place=?", (slot, place)
            ).fetchone()
        if row is None:
            return None
        return station.Snapshot.model_validate_json(row[0]), datetime.fromtimestamp(row[1], UTC)
