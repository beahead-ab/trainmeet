"""What TKL keeps on the computer (KLAR-08): the station, its outside and its versions, the PIN
that locks it, and the connection to a meet with the key from the approval.

From level 1 the station also has its model (contracts/station_model.py, #83). It is kept with
the station and versioned with the outside: a new version of the outside holds the model as it
was, and both go to the cloud together as the station package (SYNK-30). While the station has
a model, its outside is derived from the model's station tracks and line exits (STD-08, TKL92)
and the list cannot be written by hand; without the model, the last outside is the list again.

The station's Manöver settings (STV-46) belong with its model: the symbols, the owner's labels
and what is shown, the same on every screen. They are versioned with the model, so a version of
the outside holds them as they were; the defaults are not stored.

At level 3 a local TKL keeps how it last reached LocoNet and the MGP cards Discover found, with
the module the owner said each sits in (#85). The addresses themselves belong to the model.

A station with parts that are their own driftplatser is approved per driftplats (TRAFIK-35):
the connection keeps each place TKL asked for with the dispatcher's answer and the part it is,
and when TKL last asked the hub, so that it keeps following without asking too often.

Rita (#85) keeps the owner's drawing as a draft until it is taken into use: the station model
with its panel plan, problems and all. Taking it into use saves it as the station's model like
an import; a new model, imported or taken from a reference station, or none, leaves no draft
behind.

Studio's Dela stationen (#87 del b) keeps the parts as a draft too, until Använd makes them the
model's (TKL97–TKL103): the stored model with the draft's parts, under the same rules as any
model, never under set routes or train numbers. A drawing in Rita's draft gets the same parts, so
that taking the drawing into use later keeps them. A new model, or none, leaves no draft of the
parts behind.

Studio's Prova keeps its results with the station for the model they tried (#85 del c): the
model's fingerprint goes with them, and they no longer count once the model changes. The station
is Klart (tried) when every route passed for the model as it is now.

At level 1–2 the station also has its interlocking's state of the moment (#84): the set routes,
the locks, the switch positions and the train numbers, so that a restart keeps them. It belongs
to one model: while routes are set or train numbers stand on the panel, the model cannot be
replaced or taken away, and a state that does not belong to the model fails closed.

Stream Deck (#86, SD49): which deck shows what is kept on this computer, one row per deck by its
serial number (SD35); how often each route is set, the routes pinned on Favoriter and Dagens
vägar are TKL's runtime data, kept here too and never in the station package. Only routes are
counted, never people (SD24). The owner's deviations from the default profiles, per size, belong
with the model like Manöver's settings (SD40, SD49): versioned with it, in the package's inside.

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
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import token_bytes, token_urlsafe
from threading import Lock
from typing import Final, TypeVar

from contracts import station
from contracts.common import Side
from contracts.station_model import StationModel, StationPart, to_json
from contracts.station_outside import Exit, StationOutside, StationTrack
from contracts.tkl import (
    OutsideVersion,
    TklDeckDeviations,
    TklDeckSettings,
    TklDelaEdit,
    TklDrawing,
    TklInterlocking,
    TklManover,
    TklStation,
    TklStudio,
)
from tkl.stallverk import Interlocking, fingerprint, plant_of
from tkl.standard import outside_of

LOCAL: Final = "lokal"
SESSION_LIFETIME: Final = timedelta(hours=12)
SLOT_LIFETIME: Final = timedelta(days=30)
FAILURE_WINDOW: Final = timedelta(minutes=10)
MAX_FAILURES: Final = 10
MAX_SLOTS: Final = 500
MAX_VERSIONS: Final = 200
MAX_DECKS: Final = 16
"""The decks a station keeps (cda-tkl's MAX_DECKS): the one seen longest ago goes first."""
PIN_PATTERN: Final = re.compile(r"[0-9]{4,12}")
T = TypeVar("T")

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
CREATE TABLE IF NOT EXISTS station_lock (
    slot TEXT PRIMARY KEY REFERENCES station(slot) ON DELETE CASCADE, at REAL NOT NULL
);
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
CREATE TABLE IF NOT EXISTS manover (
    slot TEXT PRIMARY KEY REFERENCES station(slot) ON DELETE CASCADE, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS manover_version (
    slot TEXT NOT NULL, number INTEGER NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (slot, number),
    FOREIGN KEY (slot, number) REFERENCES outside_version(slot, number) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS streamdeck (
    slot TEXT PRIMARY KEY REFERENCES station(slot) ON DELETE CASCADE, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS streamdeck_version (
    slot TEXT NOT NULL, number INTEGER NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (slot, number),
    FOREIGN KEY (slot, number) REFERENCES outside_version(slot, number) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS dela (
    slot TEXT PRIMARY KEY REFERENCES station(slot) ON DELETE CASCADE, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rita (
    slot TEXT PRIMARY KEY REFERENCES station(slot) ON DELETE CASCADE, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interlocking (
    slot TEXT PRIMARY KEY REFERENCES station(slot) ON DELETE CASCADE,
    revision INTEGER NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS loconet (
    slot TEXT PRIMARY KEY REFERENCES station(slot) ON DELETE CASCADE, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prova (
    slot TEXT PRIMARY KEY REFERENCES station(slot) ON DELETE CASCADE,
    model TEXT NOT NULL, tried INTEGER NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deck (
    slot TEXT NOT NULL REFERENCES station(slot) ON DELETE CASCADE,
    serial TEXT NOT NULL, body TEXT NOT NULL, seen REAL NOT NULL,
    PRIMARY KEY (slot, serial)
);
CREATE TABLE IF NOT EXISTS deck_drift (
    slot TEXT PRIMARY KEY REFERENCES station(slot) ON DELETE CASCADE, body TEXT NOT NULL
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


class HasModel(Exception):
    """The station has a model: its outside is derived from it, not written as a list."""


class NoModel(Exception):
    """The station has no model: nothing at level 1–2 can be kept for it."""


class InterlockingBusy(Exception):
    """Routes are set or train numbers stand in the interlocking: the model stays as it is."""


class Full(Exception):
    """TKL in the cloud has as many stations as it takes."""


class NotConnected(Exception):
    """TKL is not connected to a meet, or not approved yet."""


def now_utc() -> datetime:
    return datetime.now(UTC)


def body_fingerprint(body: str) -> str:
    """The fingerprint of a model as it is kept: the same as tkl.stallverk.fingerprint."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _migrate(db: sqlite3.Connection) -> None:
    """Columns that came after a table was first made."""
    columns = {str(row[1]) for row in db.execute("PRAGMA table_info(connection)")}
    if "preview" not in columns:
        db.execute("ALTER TABLE connection ADD COLUMN preview INTEGER NOT NULL DEFAULT 0")
    if "wanted" not in columns:
        db.execute("ALTER TABLE connection ADD COLUMN wanted TEXT NOT NULL DEFAULT '[]'")
    if "asked" not in columns:
        db.execute("ALTER TABLE connection ADD COLUMN asked REAL NOT NULL DEFAULT 0")


def _wanted_json(wanted: list[station.ClientPlace]) -> str:
    return json.dumps([w.model_dump(mode="json") for w in wanted])


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
    preview: bool = False
    """A preview run in Provbanan, never a real meet (STUDIO-12)."""
    wanted: list[station.ClientPlace] = field(default_factory=list)
    """Each place TKL asked for, with the dispatcher's answer and the part it is (TRAFIK-35)."""
    asked: float = 0.0
    """When TKL last asked the hub how the approval stands, as a timestamp."""


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
                    _migrate(db)
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
            tried = row is not None and self._tried(db, slot)
        if row is None:
            return None
        return TklStation(station_id=row[0], name=row[1], level=row[2], tried=tried)

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
        """The PIN opens TKL: a session for this browser, and the station's lock is gone (SD30)."""
        with self._transaction() as db:
            right = self._pin_right(db, slot, pin)
            if right:
                db.execute("DELETE FROM station_lock WHERE slot=?", (slot,))
            token = self._new_session(db, slot) if right else ""
        if not right:
            raise WrongPin()
        return token

    def lock_station(self, slot: str) -> None:
        """Lås, in TKL or on a deck (Fika, SD30): TKL is locked for the whole station. Every
        session ends, every deck shows only the clock, and only the PIN opens it again. The
        lock is kept over a restart."""
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM station WHERE slot=?", (slot,)).fetchone() is None:
                return
            db.execute(
                "INSERT OR REPLACE INTO station_lock VALUES (?, ?)", (slot, now_utc().timestamp())
            )
            db.execute("DELETE FROM session WHERE slot=?", (slot,))

    def station_locked(self, slot: str | None) -> bool:
        if not slot:
            return False
        with self._transaction() as db:
            row = db.execute("SELECT 1 FROM station_lock WHERE slot=?", (slot,)).fetchone()
        return row is not None

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
                "SELECT 1 FROM session WHERE token_hash=? AND slot=? AND expires>? AND NOT EXISTS "
                "(SELECT 1 FROM station_lock WHERE station_lock.slot=session.slot)",
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
        manover = self._manover(db, slot)
        latest_manover = self._manover_of(db, slot, versions[0][0]) if versions else None
        deck = self._streamdeck(db, slot)
        latest_deck = self._streamdeck_of(db, slot, versions[0][0]) if versions else None
        return TklStudio(
            draft=draft,
            versions=[
                OutsideVersion(number=number, saved=datetime.fromtimestamp(saved, UTC))
                for number, saved, _ in versions
            ],
            changed=latest != draft
            or latest_model != model
            or latest_manover != manover
            or latest_deck != deck,
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

    @staticmethod
    def _manover(db: sqlite3.Connection, slot: str) -> str | None:
        row = db.execute("SELECT body FROM manover WHERE slot=?", (slot,)).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _manover_of(db: sqlite3.Connection, slot: str, number: int) -> str | None:
        row = db.execute(
            "SELECT body FROM manover_version WHERE slot=? AND number=?", (slot, number)
        ).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _streamdeck(db: sqlite3.Connection, slot: str) -> str | None:
        row = db.execute("SELECT body FROM streamdeck WHERE slot=?", (slot,)).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _streamdeck_of(db: sqlite3.Connection, slot: str, number: int) -> str | None:
        row = db.execute(
            "SELECT body FROM streamdeck_version WHERE slot=? AND number=?", (slot, number)
        ).fetchone()
        return None if row is None else str(row[0])

    # --- The station's model (#83): kept with the station, versioned with the outside ------

    def station_model(self, slot: str) -> StationModel | None:
        with self._transaction() as db:
            body = self._model(db, slot)
        return None if body is None else StationModel.model_validate_json(body)

    def save_model(self, slot: str, model: StationModel) -> StationModel:
        """The station's model, with the station's own id and name, and the outside derived
        from it as the draft (STD-08). The station's level follows the model: 1, 2, or 3 once
        the owner has turned it on in Koppla in (#85). The model must give an outside
        (tkl.standard.checks), else OutsideError."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT station_id, name FROM station WHERE slot=?", (slot,)
            ).fetchone()
            if row is None:
                raise NotSetUp()
            kept = model.model_copy(update={"station_id": row[0], "name": row[1]})
            draft = outside_of(kept, row[0], row[1])
            self._new_interlocking(db, slot, kept)
            db.execute("INSERT OR REPLACE INTO station_model VALUES (?, ?)", (slot, to_json(kept)))
            db.execute("DELETE FROM rita WHERE slot=?", (slot,))
            db.execute("DELETE FROM dela WHERE slot=?", (slot,))
            db.execute(
                "UPDATE station SET level=?, draft=? WHERE slot=?",
                (kept.level, draft.model_dump_json(), slot),
            )
        return kept

    def forget_model(self, slot: str) -> None:
        """Back to level 0: the last outside, derived from the model, is the list again. The
        Manöver settings and the Stream Deck deviations go with the model; the versions keep
        theirs."""
        with self._transaction() as db:
            self._new_interlocking(db, slot, None)
            db.execute("DELETE FROM station_model WHERE slot=?", (slot,))
            db.execute("DELETE FROM rita WHERE slot=?", (slot,))
            db.execute("DELETE FROM dela WHERE slot=?", (slot,))
            db.execute("DELETE FROM manover WHERE slot=?", (slot,))
            db.execute("DELETE FROM streamdeck WHERE slot=?", (slot,))
            db.execute("UPDATE station SET level=0 WHERE slot=?", (slot,))

    # --- Rita (#85): the drawing, kept as a draft until it is taken into use ----------------

    def drawing(self, slot: str) -> TklDrawing | None:
        """The owner's draft, if there is one. A draft TKL can no longer read is dropped."""
        with self._transaction() as db:
            row = db.execute("SELECT body FROM rita WHERE slot=?", (slot,)).fetchone()
        if row is None:
            return None
        try:
            return TklDrawing.model_validate_json(row[0])
        except ValueError:
            self.forget_drawing(slot)
            return None

    def save_drawing(self, slot: str, drawing: TklDrawing) -> None:
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM station WHERE slot=?", (slot,)).fetchone() is None:
                raise NotSetUp()
            db.execute(
                "INSERT OR REPLACE INTO rita VALUES (?, ?)", (slot, drawing.model_dump_json())
            )

    def forget_drawing(self, slot: str) -> None:
        with self._transaction() as db:
            db.execute("DELETE FROM rita WHERE slot=?", (slot,))

    # --- Dela stationen (#87 del b): the parts, kept as a draft until Använd ----------------

    def parts_draft(self, slot: str) -> list[StationPart] | None:
        """The owner's draft of the parts, if there is one. One TKL can no longer read is
        dropped."""
        with self._transaction() as db:
            row = db.execute("SELECT body FROM dela WHERE slot=?", (slot,)).fetchone()
        if row is None:
            return None
        try:
            return list(TklDelaEdit.model_validate_json(row[0]).parts)
        except ValueError:
            self.forget_parts_draft(slot)
            return None

    def save_parts_draft(self, slot: str, parts: list[StationPart]) -> None:
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM station WHERE slot=?", (slot,)).fetchone() is None:
                raise NotSetUp()
            body = TklDelaEdit(parts=parts).model_dump_json()
            db.execute("INSERT OR REPLACE INTO dela VALUES (?, ?)", (slot, body))

    def forget_parts_draft(self, slot: str) -> None:
        with self._transaction() as db:
            db.execute("DELETE FROM dela WHERE slot=?", (slot,))

    def save_parts(self, slot: str, parts: list[StationPart]) -> StationModel:
        """Använd: the parts become the model's, which gives the interlocking its model and the
        outside its parts, never under set routes or train numbers (InterlockingBusy). Rita's
        draft gets the same parts; the parts' draft is gone."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT station_id, name FROM station WHERE slot=?", (slot,)
            ).fetchone()
            body = self._model(db, slot)
            if row is None:
                raise NotSetUp()
            if body is None:
                raise NoModel()
            kept = StationModel.model_validate_json(body).model_copy(update={"parts": parts})
            draft = outside_of(kept, row[0], row[1])
            self._new_interlocking(db, slot, kept)
            db.execute("INSERT OR REPLACE INTO station_model VALUES (?, ?)", (slot, to_json(kept)))
            db.execute("UPDATE station SET draft=? WHERE slot=?", (draft.model_dump_json(), slot))
            db.execute("DELETE FROM dela WHERE slot=?", (slot,))
            drawn = db.execute("SELECT body FROM rita WHERE slot=?", (slot,)).fetchone()
            if drawn is not None:
                try:
                    drawing = TklDrawing.model_validate_json(drawn[0])
                except ValueError:
                    drawing = None
                if drawing is not None:
                    model = drawing.model.model_copy(update={"parts": parts})
                    db.execute(
                        "UPDATE rita SET body=? WHERE slot=?",
                        (drawing.model_copy(update={"model": model}).model_dump_json(), slot),
                    )
        return kept

    def model_fingerprint(self, slot: str) -> str | None:
        """The fingerprint of the station's model as it is kept: what Prova's results belong to."""
        with self._transaction() as db:
            body = self._model(db, slot)
        return None if body is None else body_fingerprint(body)

    # --- Studio's Prova (#85 del c): the results, for one model -----------------------------

    def _tried(self, db: sqlite3.Connection, slot: str) -> bool:
        body = self._model(db, slot)
        row = db.execute("SELECT model, tried FROM prova WHERE slot=?", (slot,)).fetchone()
        return (
            body is not None
            and row is not None
            and bool(row[1])
            and str(row[0]) == body_fingerprint(body)
        )

    def prova(self, slot: str) -> tuple[str, str] | None:
        """Prova's kept results: the fingerprint of the model they tried, and their body."""
        with self._transaction() as db:
            row = db.execute("SELECT model, body FROM prova WHERE slot=?", (slot,)).fetchone()
        return None if row is None else (str(row[0]), str(row[1]))

    def save_prova(self, slot: str, model: str, tried: bool, body: str) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO prova VALUES (?, ?, ?, ?)", (slot, model, int(tried), body)
            )

    # --- Manöver (STV-46): the owner's settings, with the model ------------------------------

    def manover(self, slot: str) -> TklManover:
        """The station's Manöver settings as the owner left them; the defaults when none."""
        with self._transaction() as db:
            body = self._manover(db, slot)
        return TklManover() if body is None else TklManover.model_validate_json(body)

    def save_manover(self, slot: str, settings: TklManover) -> TklManover:
        """Kept with the station's model, as it is: the caller has checked it against the
        panel. The defaults are not stored, and the same settings are always the same text, so
        that only a real change counts as one since the latest version."""
        with self._transaction() as db:
            if self._model(db, slot) is None:
                raise NoModel()
            if settings == TklManover():
                db.execute("DELETE FROM manover WHERE slot=?", (slot,))
            else:
                body = settings.model_dump(mode="json", exclude_defaults=True)
                db.execute(
                    "INSERT OR REPLACE INTO manover VALUES (?, ?)",
                    (slot, json.dumps(body, ensure_ascii=False, sort_keys=True)),
                )
        return settings

    def manover_of_version(self, slot: str, number: int) -> TklManover | None:
        """The Manöver settings a version of the outside holds, if the owner had any."""
        with self._transaction() as db:
            body = self._manover_of(db, slot, number)
        return None if body is None else TklManover.model_validate_json(body)

    # --- Stream Deck in Studio (#86 del c): the owner's deviations, with the model --------

    def deck_deviations(self, slot: str) -> TklDeckDeviations:
        """The owner's deviations per size (SD40); none when the owner has changed nothing. A
        body TKL can no longer read is none too."""
        with self._transaction() as db:
            body = self._streamdeck(db, slot)
        if body is None:
            return TklDeckDeviations()
        try:
            return TklDeckDeviations.model_validate_json(body)
        except ValueError:
            return TklDeckDeviations()

    def deck_deviations_body(self, slot: str) -> str:
        """The deviations as they are kept: what a deck's profile follows."""
        with self._transaction() as db:
            return self._streamdeck(db, slot) or ""

    def save_deck_deviations(self, slot: str, kept: TklDeckDeviations) -> TklDeckDeviations:
        """Kept with the station's model, as Manöver's settings: the caller has checked them
        (SD43). None at all is not stored, and the same deviations are always the same text, so
        that only a real change counts as one since the latest version."""
        sizes = {size: found for size, found in kept.sizes.items() if found}
        # The shunter's decks (#87 del d): per part and size, kept the same way.
        parts = {
            part: mine
            for part, by_size in kept.parts.items()
            if (mine := {size: found for size, found in by_size.items() if found})
        }
        made = TklDeckDeviations(sizes=sizes, parts=parts)
        with self._transaction() as db:
            if self._model(db, slot) is None:
                raise NoModel()
            if not sizes and not parts:
                db.execute("DELETE FROM streamdeck WHERE slot=?", (slot,))
            else:
                body = made.model_dump(mode="json", exclude_defaults=True)
                db.execute(
                    "INSERT OR REPLACE INTO streamdeck VALUES (?, ?)",
                    (slot, json.dumps(body, ensure_ascii=False, sort_keys=True)),
                )
        return made

    def deck_deviations_of_version(self, slot: str, number: int) -> TklDeckDeviations | None:
        """The deviations a version of the outside holds, if the owner had any."""
        with self._transaction() as db:
            body = self._streamdeck_of(db, slot, number)
        return None if body is None else TklDeckDeviations.model_validate_json(body)

    # --- The interlocking's state (#84) -----------------------------------------------------

    @staticmethod
    def _interlocking(db: sqlite3.Connection, slot: str) -> tuple[int, str | None]:
        row = db.execute("SELECT revision, body FROM interlocking WHERE slot=?", (slot,)).fetchone()
        return (0, None) if row is None else (int(row[0]), str(row[1]))

    def _new_interlocking(
        self, db: sqlite3.Connection, slot: str, model: StationModel | None
    ) -> None:
        """A new model, or none: the interlocking starts over, but never under set routes or
        train numbers (InterlockingBusy). The same model again changes nothing."""
        revision, body = self._interlocking(db, slot)
        if body is None:
            return
        try:
            saved: TklInterlocking | None = TklInterlocking.model_validate_json(body)
        except ValueError:
            saved = None
        if saved is not None and model is not None and saved.model == fingerprint(model):
            return
        if saved is None or saved.routes or saved.trains:
            raise InterlockingBusy()
        if model is None:
            db.execute("DELETE FROM interlocking WHERE slot=?", (slot,))
            return
        fresh = Interlocking(plant_of(model))
        fresh.revision = revision + 1
        db.execute(
            "UPDATE interlocking SET revision=?, body=? WHERE slot=?",
            (fresh.revision, fresh.view().model_dump_json(), slot),
        )

    def interlocking(self, slot: str) -> tuple[StationModel | None, int, str | None]:
        """The station's model, and the interlocking's revision and saved state, if any."""
        with self._transaction() as db:
            body = self._model(db, slot)
            revision, state = self._interlocking(db, slot)
        model = None if body is None else StationModel.model_validate_json(body)
        return model, revision, state

    def interlocking_revision(self, slot: str) -> int | None:
        """The interlocking's revision, cheaply, for waiting; None without a model."""
        with self._transaction() as db:
            if self._model(db, slot) is None:
                return None
            return self._interlocking(db, slot)[0]

    def change_interlocking(
        self,
        slot: str,
        change: Callable[[StationModel | None, int, str | None], tuple[TklInterlocking | None, T]],
    ) -> T:
        """One change to the interlocking, in one transaction: `change` gets the model, the
        revision and the saved state, and gives the new state to keep, or None to keep it as
        it was, and what to answer."""
        with self._transaction() as db:
            body = self._model(db, slot)
            model = None if body is None else StationModel.model_validate_json(body)
            revision, state = self._interlocking(db, slot)
            kept, answer = change(model, revision, state)
            if kept is not None:
                db.execute(
                    "INSERT OR REPLACE INTO interlocking VALUES (?, ?, ?)",
                    (slot, kept.revision, kept.model_dump_json()),
                )
        return answer

    # --- LocoNet (#85): how TKL reached it, and the cards ------------------------------------

    def loconet(self, slot: str) -> dict[str, object]:
        """The LocoNet settings as last kept: empty when none."""
        with self._transaction() as db:
            row = db.execute("SELECT body FROM loconet WHERE slot=?", (slot,)).fetchone()
        if row is None:
            return {}
        found = json.loads(row[0])
        return found if isinstance(found, dict) else {}

    def save_loconet(self, slot: str, settings: dict[str, object]) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO loconet VALUES (?, ?)",
                (slot, json.dumps(settings, ensure_ascii=False, sort_keys=True)),
            )

    def save_draft(self, slot: str, outside: StationOutside) -> TklStudio:
        """The list as it stands, saved on the computer. Its id and name are the station's.
        A station with a model has no list to write: HasModel."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT station_id, name FROM station WHERE slot=?", (slot,)
            ).fetchone()
            if row is None:
                raise NotSetUp()
            if self._model(db, slot) is not None:
                raise HasModel()
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
                manover = self._manover(db, slot)
                if model is not None and manover is not None:
                    db.execute(
                        "INSERT INTO manover_version VALUES (?, ?, ?)", (slot, number, manover)
                    )
                deck = self._streamdeck(db, slot)
                if model is not None and deck is not None:
                    db.execute(
                        "INSERT INTO streamdeck_version VALUES (?, ?, ?)", (slot, number, deck)
                    )
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
                "message, key, preview, wanted, asked FROM connection WHERE slot=?",
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
            preview=bool(row[9]),
            wanted=[station.ClientPlace.model_validate(w) for w in json.loads(row[10])],
            asked=float(row[11]),
        )

    def connected(self, slot: str, made: Connection) -> None:
        """A new connection replaces the one before, and what was seen with it."""
        with self._transaction() as db:
            db.execute("DELETE FROM seen WHERE slot=?", (slot,))
            db.execute(
                "INSERT OR REPLACE INTO connection (slot, address, relay, hub_name, client_id, "
                "status, places, key, outside_version, message, preview, wanted, asked) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    int(made.preview),
                    _wanted_json(made.wanted),
                    made.asked,
                ),
            )

    def approval(
        self,
        slot: str,
        status: station.ApprovalStatus,
        places: list[str],
        key: str | None,
        message: str | None = None,
        wanted: list[station.ClientPlace] | None = None,
    ) -> None:
        """How the approval stands. A key arrives once and is kept; a revoked one is dropped.
        wanted: each place with its answer, as the hub gave it; None keeps what was known."""
        with self._transaction() as db:
            if key is not None:
                db.execute("UPDATE connection SET key=? WHERE slot=?", (key, slot))
            if status in (station.ApprovalStatus.REVOKED, station.ApprovalStatus.REFUSED):
                db.execute("UPDATE connection SET key=NULL WHERE slot=?", (slot,))
            db.execute(
                "UPDATE connection SET status=?, places=?, message=?, asked=? WHERE slot=?",
                (status.value, json.dumps(places), message, now_utc().timestamp(), slot),
            )
            if wanted is not None:
                db.execute(
                    "UPDATE connection SET wanted=? WHERE slot=?", (_wanted_json(wanted), slot)
                )

    def asked(self, slot: str) -> None:
        """TKL asked the hub how the approval stands, and got no answer that changed it."""
        with self._transaction() as db:
            db.execute("UPDATE connection SET asked=? WHERE slot=?", (now_utc().timestamp(), slot))

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

    # --- Stream Deck (#86): the decks on this computer and TKL's runtime data (SD49) -------

    def decks(self, slot: str) -> list[TklDeckSettings]:
        with self._transaction() as db:
            rows = db.execute(
                "SELECT body FROM deck WHERE slot=? ORDER BY serial", (slot,)
            ).fetchall()
        return [TklDeckSettings.model_validate_json(r[0]) for r in rows]

    def deck(self, slot: str, serial: str) -> TklDeckSettings | None:
        with self._transaction() as db:
            row = db.execute(
                "SELECT body FROM deck WHERE slot=? AND serial=?", (slot, serial)
            ).fetchone()
        return None if row is None else TklDeckSettings.model_validate_json(row[0])

    def save_deck(self, slot: str, settings: TklDeckSettings) -> None:
        """A deck, known by its serial number (SD35). A new one beyond MAX_DECKS takes the
        place of the one seen longest ago."""
        with self._transaction() as db:
            known = db.execute(
                "SELECT 1 FROM deck WHERE slot=? AND serial=?", (slot, settings.serial)
            ).fetchone()
            if known is None:
                count = db.execute("SELECT COUNT(*) FROM deck WHERE slot=?", (slot,)).fetchone()
                if int(count[0]) >= MAX_DECKS:
                    db.execute(
                        "DELETE FROM deck WHERE slot=? AND serial=(SELECT serial FROM deck "
                        "WHERE slot=? ORDER BY seen LIMIT 1)",
                        (slot, slot),
                    )
            db.execute(
                "INSERT OR REPLACE INTO deck VALUES (?, ?, ?, ?)",
                (slot, settings.serial, settings.model_dump_json(), now_utc().timestamp()),
            )

    def forget_deck(self, slot: str, serial: str) -> bool:
        """Glöm deck (SD46): the deck's settings on this computer go; True when there were any."""
        with self._transaction() as db:
            gone = db.execute("DELETE FROM deck WHERE slot=? AND serial=?", (slot, serial))
            return gone.rowcount > 0

    def deck_drift(self, slot: str) -> dict[str, object]:
        """TKL's runtime data for the decks: counted routes, pinned ones and Dagens vägar."""
        with self._transaction() as db:
            row = db.execute("SELECT body FROM deck_drift WHERE slot=?", (slot,)).fetchone()
        if row is None:
            return {}
        found = json.loads(row[0])
        return found if isinstance(found, dict) else {}

    def change_deck_drift(
        self, slot: str, change: Callable[[dict[str, object]], dict[str, object]]
    ) -> dict[str, object]:
        with self._transaction() as db:
            row = db.execute("SELECT body FROM deck_drift WHERE slot=?", (slot,)).fetchone()
            found = json.loads(row[0]) if row is not None else {}
            made = change(found if isinstance(found, dict) else {})
            db.execute(
                "INSERT OR REPLACE INTO deck_drift VALUES (?, ?)",
                (slot, json.dumps(made, ensure_ascii=False, sort_keys=True)),
            )
        return made
