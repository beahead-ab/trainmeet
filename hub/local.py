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
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import randbelow, token_bytes, token_urlsafe
from threading import Lock
from typing import Final

from integrationer import fastclock

SESSION_LIFETIME: Final = timedelta(hours=12)
FAILURE_WINDOW: Final = timedelta(minutes=10)
MAX_FAILURES: Final = 10
PIN_PATTERN: Final = re.compile(r"[0-9]{6,12}")
CODE_PATTERN: Final = re.compile(r"[0-9]{6}")
CODE_LIFETIME: Final = timedelta(minutes=15)
# A let-in role holds until the meet ends (H56); this is only an outer bound, for a meet that
# never ends.
LET_IN_LIFETIME: Final = timedelta(days=7)
ADMIN: Final = "admin"
DISPATCHER: Final = "dispatcher"
LOCO_LEAD: Final = "loco_lead"
"""Lokledare (LOK-30, LF17): hands out the drivers' services and runs no traffic."""
PERSON: Final = "person"
"""Logged in with TrainMeet ID (#78): the roles at a meet come from ID, not from the hub."""
ID_LOGIN_LIFETIME: Final = timedelta(minutes=10)
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
CREATE TABLE IF NOT EXISTS one_time_code (
    code_hash TEXT PRIMARY KEY,
    run TEXT NOT NULL,
    role TEXT NOT NULL,
    name TEXT,
    expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS login_failure (at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS pi_login (
    attempt_hash TEXT PRIMARY KEY,
    meet TEXT NOT NULL,
    pi TEXT NOT NULL,
    back TEXT NOT NULL,
    ticket TEXT,
    expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS id_keys (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    jwks TEXT NOT NULL,
    fetched REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS id_login (
    key_hash TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    nonce TEXT NOT NULL,
    verifier TEXT NOT NULL,
    next_path TEXT NOT NULL,
    expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ai (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    format TEXT NOT NULL,
    address TEXT NOT NULL,
    model TEXT NOT NULL,
    key TEXT NOT NULL,
    checked REAL
);
CREATE TABLE IF NOT EXISTS meet_wifi (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL,
    open INTEGER NOT NULL,
    password TEXT
);
CREATE TABLE IF NOT EXISTS tellurian (
    meet TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    address TEXT NOT NULL,
    test_instance INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS clock_source (
    meet TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    clock_name TEXT NOT NULL,
    url TEXT NOT NULL,
    user TEXT NOT NULL,
    password TEXT NOT NULL,
    poll_interval INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_reading (
    meet TEXT PRIMARY KEY,
    payer TEXT NOT NULL,
    person TEXT
);
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
class AiSetting:
    """Egen AI as stored (H58). The key stays in the hub and is never shown."""

    format: str
    address: str
    model: str
    key: str = field(repr=False)
    checked: datetime | None = None


@dataclass(frozen=True)
class PaperReading:
    """Who pays when a driver's photos of a duty missing from the plan are read (LOK-33,
    PLAN-40): the driver's own tokens by default, or the meet's. For the meet's, the person in
    TrainMeet ID who chose it, as ID's id: their club's balance pays for a meet in ID, else
    their own (TK16)."""

    payer: str = "driver"
    person: str | None = None


@dataclass(frozen=True)
class MeetWifi:
    """Träffens Wi-Fi as stored (H45): what participants and screens show, not the Pi's own
    network. The password is shown on the meet's network, so it is no secret there."""

    name: str
    open: bool
    password: str | None = field(default=None, repr=False)


# Columns the session table got after its first version (#78), in order.
_SESSION_COLUMNS: Final = (
    ("role", "TEXT NOT NULL DEFAULT 'admin'"),
    ("run", "TEXT"),
    ("since", "REAL"),
    ("name", "TEXT"),
    ("person", "TEXT"),
    ("id_token", "TEXT"),
    ("ticket_roles", "TEXT"),
    # ID's access and refresh token for the client hub, for TrainMeet CAD (#89 del d3, CAD-11).
    ("access", "TEXT"),
    ("refresh", "TEXT"),
    ("access_until", "REAL"),
)
# Columns the login with ID got after its first version (#78).
_ID_LOGIN_COLUMNS: Final = (("pi_attempt", "TEXT"),)


@dataclass(frozen=True)
class IdAttempt:
    """A login with TrainMeet ID this browser started: what comes back must match it."""

    state: str
    nonce: str
    verifier: str
    next_path: str
    pi_attempt: str | None = None
    """For a meet's Pi: the Pi's attempt, which gets a ticket instead of a session here."""


@dataclass(frozen=True)
class PiAttempt:
    """In the cloud: a Pi that sent someone here to log in with ID (KONTO-11)."""

    meet: str
    pi: str
    back: str


@dataclass(frozen=True)
class IdAccess:
    """ID's access token for the client hub, its refresh token and when it runs out (epoch
    seconds). Never written to the log."""

    token: str = field(repr=False)
    refresh: str | None = field(default=None, repr=False)
    until: float = 0.0


@dataclass(frozen=True)
class Person:
    """Who is logged in with TrainMeet ID: ID's subject and the name, never the address."""

    id: str
    name: str


@dataclass(frozen=True)
class LetIn:
    """Someone let in with a one-time code: never the code, only who and until when."""

    person: str
    name: str | None
    role: str
    since: datetime
    until: datetime


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
                    # A hub from before #78 has sessions without a role: they are the local
                    # administrator's. Later columns are added the same way, one at a time.
                    columns = {row[1] for row in db.execute("PRAGMA table_info(session)")}
                    for column, kind in _SESSION_COLUMNS:
                        if column not in columns:
                            db.execute(f"ALTER TABLE session ADD COLUMN {column} {kind}")
                    columns = {row[1] for row in db.execute("PRAGMA table_info(id_login)")}
                    for column, kind in _ID_LOGIN_COLUMNS:
                        if column not in columns:
                            db.execute(f"ALTER TABLE id_login ADD COLUMN {column} {kind}")
                    db.commit()
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
        with self._transaction() as db:
            wrong = not self._pin_right(db, pin)
            if not wrong:
                token = self._new_session(db)
        if wrong:
            raise WrongPin()
        return token

    def _pin_right(self, db: sqlite3.Connection, pin: str) -> bool:
        """Is the PIN the hub's? A wrong one counts against the hub, so guessing stays slow.
        Raises NotSetUp and TooManyAttempts."""
        now = _now()
        row = db.execute("SELECT pin_salt, pin_hash FROM hub WHERE id=1").fetchone()
        if row is None:
            raise NotSetUp()
        db.execute("DELETE FROM login_failure WHERE at<?", ((now - FAILURE_WINDOW).timestamp(),))
        failures = db.execute("SELECT count(*) FROM login_failure").fetchone()[0]
        if failures >= MAX_FAILURES:
            raise TooManyAttempts()
        salt, expected = row
        if not PIN_PATTERN.fullmatch(pin) or not hmac.compare_digest(
            _hash_pin(pin, salt), expected
        ):
            db.execute("INSERT INTO login_failure VALUES (?)", (now.timestamp(),))
            return False
        return True

    def rename(self, name: str) -> str:
        """På den här hubben: a new name for the hub. The name as kept."""
        name = " ".join(name.split())
        if not 1 <= len(name) <= NAME_LIMIT:
            raise InvalidSetup("Hubbens namn är 1–40 tecken.")
        with self._transaction() as db:
            if db.execute("UPDATE hub SET name=? WHERE id=1", (name,)).rowcount == 0:
                raise NotSetUp()
        return name

    def change_pin(self, pin: str, new_pin: str, keep: str | None) -> None:
        """Byt PIN: the current one first. Every other session ends; keep goes on."""
        if not PIN_PATTERN.fullmatch(new_pin):
            raise InvalidSetup("PIN-koden är 6–12 siffror.")
        with self._transaction() as db:
            wrong = not self._pin_right(db, pin)
            if not wrong:
                self._set_pin(db, new_pin, keep)
        if wrong:
            raise WrongPin()

    def reset_pin(self, new_pin: str) -> None:
        """A forgotten PIN, with physical access to the hub (H46, SYNK-27): a command on the
        Pi or a file on a USB stick. Every session ends; the failed attempts are forgotten."""
        if not PIN_PATTERN.fullmatch(new_pin):
            raise InvalidSetup("PIN-koden är 6–12 siffror.")
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM hub WHERE id=1").fetchone() is None:
                raise NotSetUp()
            self._set_pin(db, new_pin, None)
            db.execute("DELETE FROM login_failure")

    def _set_pin(self, db: sqlite3.Connection, pin: str, keep: str | None) -> None:
        salt = token_bytes(16)
        db.execute("UPDATE hub SET pin_salt=?, pin_hash=? WHERE id=1", (salt, _hash_pin(pin, salt)))
        kept = _token_hash(keep) if keep else ""
        db.execute("DELETE FROM session WHERE token_hash!=?", (kept,))

    def _new_session(
        self,
        db: sqlite3.Connection,
        role: str = ADMIN,
        run: str | None = None,
        lifetime: timedelta = SESSION_LIFETIME,
        name: str | None = None,
    ) -> str:
        now = _now()
        db.execute("DELETE FROM session WHERE expires<=?", (now.timestamp(),))
        token = token_urlsafe(32)
        db.execute(
            "INSERT INTO session (token_hash, expires, role, run, since, name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_token_hash(token), (now + lifetime).timestamp(), role, run, now.timestamp(), name),
        )
        return token

    # --- Engångskoden (H56, KONTO-19, F18) ------------------------------------------------

    def issue_code(
        self, run: str, role: str = DISPATCHER, name: str | None = None
    ) -> tuple[str, datetime]:
        """Six digits, once, for 15 minutes, for the meet that runs. Only its hash is kept."""
        name = " ".join(name.split())[:NAME_LIMIT] if name else None
        now = _now()
        expires = now + CODE_LIFETIME
        with self._transaction() as db:
            db.execute("DELETE FROM one_time_code WHERE expires<=?", (now.timestamp(),))
            while True:
                code = f"{randbelow(10**6):06d}"
                taken = db.execute(
                    "SELECT 1 FROM one_time_code WHERE code_hash=?", (_token_hash(code),)
                ).fetchone()
                if taken is None:
                    break
            db.execute(
                "INSERT INTO one_time_code (code_hash, run, role, name, expires) "
                "VALUES (?, ?, ?, ?, ?)",
                (_token_hash(code), run, role, name or None, expires.timestamp()),
            )
        return code, expires

    def log_in_with_code(self, code: str, run: str) -> str:
        """The code gives its role in the meet that runs, until the meet ends or the dispatcher
        takes it away (H56). A wrong code counts like a wrong PIN, so guessing stays slow."""
        now = _now()
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM hub WHERE id=1").fetchone() is None:
                raise NotSetUp()
            db.execute(
                "DELETE FROM login_failure WHERE at<?", ((now - FAILURE_WINDOW).timestamp(),)
            )
            if db.execute("SELECT count(*) FROM login_failure").fetchone()[0] >= MAX_FAILURES:
                raise TooManyAttempts()
            row = None
            if CODE_PATTERN.fullmatch(code):
                row = db.execute(
                    "SELECT role, name FROM one_time_code "
                    "WHERE code_hash=? AND run=? AND expires>?",
                    (_token_hash(code), run, now.timestamp()),
                ).fetchone()
            if row is None:
                db.execute("INSERT INTO login_failure VALUES (?)", (now.timestamp(),))
                token = None
            else:
                db.execute("DELETE FROM one_time_code WHERE code_hash=?", (_token_hash(code),))
                token = self._new_session(db, str(row[0]), run, LET_IN_LIFETIME, row[1])
        if token is None:
            raise WrongPin()
        return token

    def role(self, token: str | None, run: str | None = None) -> str | None:
        """The session's role: the administrator's anywhere, a let-in role only in its meet."""
        if not token or len(token) > 120:
            return None
        with self._transaction() as db:
            row = db.execute(
                "SELECT role, run FROM session WHERE token_hash=? AND expires>?",
                (_token_hash(token), _now().timestamp()),
            ).fetchone()
        if row is None:
            return None
        role, bound = str(row[0]), row[1]
        if bound is not None and bound != run:
            return None
        return role

    def let_in(self, run: str) -> list[LetIn]:
        """Who was let in to the meet with a code, and still is."""
        with self._transaction() as db:
            rows = db.execute(
                "SELECT token_hash, name, role, since, expires FROM session "
                "WHERE run=? AND expires>? ORDER BY since",
                (run, _now().timestamp()),
            ).fetchall()
        return [
            LetIn(
                person=str(row[0])[:12],
                name=row[1],
                role=str(row[2]),
                since=datetime.fromtimestamp(row[3] or row[4], UTC),
                until=datetime.fromtimestamp(row[4], UTC),
            )
            for row in rows
        ]

    def take_away(self, run: str, person: str) -> bool:
        """The dispatcher takes a let-in role away at once (H56)."""
        if not re.fullmatch(r"[0-9a-f]{12}", person):
            return False
        with self._transaction() as db:
            gone = db.execute(
                "DELETE FROM session WHERE run=? AND substr(token_hash, 1, 12)=?", (run, person)
            ).rowcount
        return bool(gone)

    def valid(self, token: str | None) -> bool:
        """The local administrator: the one with the PIN (H18), who may do everything."""
        return self.role(token) == ADMIN

    def ai(self) -> AiSetting | None:
        with self._transaction() as db:
            row = db.execute("SELECT format, address, model, key, checked FROM ai").fetchone()
        if row is None:
            return None
        checked = datetime.fromtimestamp(row[4], UTC) if row[4] is not None else None
        return AiSetting(row[0], row[1], row[2], row[3], checked)

    def set_ai(self, setting: AiSetting) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO ai VALUES (1, ?, ?, ?, ?, ?)",
                (
                    setting.format,
                    setting.address,
                    setting.model,
                    setting.key,
                    setting.checked.timestamp() if setting.checked else None,
                ),
            )

    def tellurian(self, meet: str) -> tuple[str, str, bool]:
        """Tellurian Dispatch for a meet (IMPORT-06): mode, address and test instance. Off by
        default, and never sent to the cloud."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT mode, address, test_instance FROM tellurian WHERE meet=?", (meet,)
            ).fetchone()
        if row is None:
            return "off", "", False
        return ("shadow" if row[0] == "shadow" else "off"), str(row[1]), bool(row[2])

    def set_tellurian(self, meet: str, mode: str, address: str, test_instance: bool) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO tellurian VALUES (?, ?, ?, ?)",
                (meet, mode, address, int(test_instance)),
            )

    def clock_source(self, meet: str) -> fastclock.Settings:
        """Träffens klocka (F12): per meet, so another meet never gets a clock's name or
        password. The password stays here and is never shown."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT source, clock_name, url, user, password, poll_interval FROM clock_source "
                "WHERE meet=?",
                (meet,),
            ).fetchone()
        if row is None:
            return fastclock.Settings()
        return fastclock.Settings(
            source="fastclock" if row[0] == "fastclock" else "drift",
            clock_name=row[1],
            url=row[2],
            user=row[3],
            password=row[4],
            poll_interval=int(row[5]),
        )

    def set_clock_source(self, meet: str, settings: fastclock.Settings) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO clock_source VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    meet,
                    settings.source,
                    settings.clock_name,
                    settings.url,
                    settings.user,
                    settings.password,
                    settings.poll_interval,
                ),
            )

    def paper_reading(self, meet: str) -> PaperReading:
        """Who pays for reading a driver's paper at the meet (LOK-33): the driver by default."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT payer, person FROM paper_reading WHERE meet=?", (meet,)
            ).fetchone()
        if row is None or row[0] != "meet":
            return PaperReading()
        return PaperReading("meet", row[1])

    def set_paper_reading(self, meet: str, choice: PaperReading) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO paper_reading VALUES (?, ?, ?)",
                (meet, choice.payer, choice.person if choice.payer == "meet" else None),
            )

    def meet_wifi(self) -> MeetWifi | None:
        with self._transaction() as db:
            row = db.execute("SELECT name, open, password FROM meet_wifi").fetchone()
        return None if row is None else MeetWifi(row[0], bool(row[1]), row[2])

    def set_meet_wifi(self, wifi: MeetWifi | None) -> None:
        """Träffens Wi-Fi, or none: then it is not shared."""
        with self._transaction() as db:
            db.execute("DELETE FROM meet_wifi")
            if wifi is not None:
                db.execute(
                    "INSERT INTO meet_wifi VALUES (1, ?, ?, ?)",
                    (wifi.name, int(wifi.open), wifi.password),
                )

    def clear_ai(self) -> None:
        with self._transaction() as db:
            db.execute("DELETE FROM ai")

    def log_out(self, token: str | None) -> str | None:
        """Ends the session. Returns ID's token if it was a login with ID, to log out there too."""
        if not token or len(token) > 120:
            return None
        with self._transaction() as db:
            row = db.execute(
                "SELECT id_token FROM session WHERE token_hash=?", (_token_hash(token),)
            ).fetchone()
            db.execute("DELETE FROM session WHERE token_hash=?", (_token_hash(token),))
        return str(row[0]) if row is not None and row[0] else None

    # --- TrainMeet ID (#78, KONTO-27) -----------------------------------------------------

    def begin_id_login(
        self,
        state: str,
        nonce: str,
        verifier: str,
        next_path: str,
        pi_attempt: str | None = None,
    ) -> str:
        """Keeps a login with ID while the browser is at ID. Returns the browser's key to it."""
        key = token_urlsafe(32)
        now = _now()
        with self._transaction() as db:
            db.execute("DELETE FROM id_login WHERE expires<=?", (now.timestamp(),))
            db.execute(
                "INSERT INTO id_login (key_hash, state, nonce, verifier, next_path, expires, "
                "pi_attempt) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _token_hash(key),
                    state,
                    nonce,
                    verifier,
                    next_path,
                    (now + ID_LOGIN_LIFETIME).timestamp(),
                    pi_attempt,
                ),
            )
        return key

    def take_id_login(self, key: str | None) -> IdAttempt | None:
        """The login this browser started, used once, if it has not run out."""
        if not key or len(key) > 200:
            return None
        with self._transaction() as db:
            row = db.execute(
                "SELECT state, nonce, verifier, next_path, expires, pi_attempt FROM id_login "
                "WHERE key_hash=?",
                (_token_hash(key),),
            ).fetchone()
            db.execute("DELETE FROM id_login WHERE key_hash=?", (_token_hash(key),))
        if row is None or row[4] <= _now().timestamp():
            return None
        return IdAttempt(str(row[0]), str(row[1]), str(row[2]), str(row[3]), row[5])

    # --- Biljetten för Pi:n (KONTO-11, KONTO-37) ----------------------------------------------

    def begin_pi_login(self, meet: str, pi: str, back: str) -> str:
        """In the cloud: a linked Pi sends someone here to log in with ID. Returns the attempt,
        which the Pi fetches the ticket with once the person is back."""
        attempt = token_urlsafe(24)
        now = _now()
        with self._transaction() as db:
            db.execute("DELETE FROM pi_login WHERE expires<=?", (now.timestamp(),))
            db.execute(
                "INSERT INTO pi_login (attempt_hash, meet, pi, back, expires) "
                "VALUES (?, ?, ?, ?, ?)",
                (_token_hash(attempt), meet, pi, back, (now + ID_LOGIN_LIFETIME).timestamp()),
            )
        return attempt

    def pi_attempt(self, attempt: str | None) -> PiAttempt | None:
        if not attempt or len(attempt) > 100:
            return None
        with self._transaction() as db:
            row = db.execute(
                "SELECT meet, pi, back FROM pi_login WHERE attempt_hash=? AND expires>?",
                (_token_hash(attempt), _now().timestamp()),
            ).fetchone()
        return PiAttempt(str(row[0]), str(row[1]), str(row[2])) if row is not None else None

    def keep_pi_ticket(self, attempt: str, ticket: str) -> None:
        with self._transaction() as db:
            db.execute(
                "UPDATE pi_login SET ticket=? WHERE attempt_hash=?", (ticket, _token_hash(attempt))
            )

    def take_pi_ticket(self, attempt: str, meet: str, pi: str) -> str | None:
        """The ticket for the Pi's attempt, once; only for the Pi that started it."""
        if not attempt or len(attempt) > 100:
            return None
        with self._transaction() as db:
            row = db.execute(
                "SELECT ticket FROM pi_login WHERE attempt_hash=? AND meet=? AND pi=? "
                "AND expires>? AND ticket IS NOT NULL",
                (_token_hash(attempt), meet, pi, _now().timestamp()),
            ).fetchone()
            if row is None:
                return None
            db.execute("DELETE FROM pi_login WHERE attempt_hash=?", (_token_hash(attempt),))
        return str(row[0])

    def log_in_with_ticket(self, person: Person, roles: dict[str, list[str]]) -> str:
        """On the Pi: a session for someone with a ticket from ID, with its roles (KONTO-37)."""
        with self._transaction() as db:
            token = self._new_session(db, PERSON, name=person.name)
            db.execute(
                "UPDATE session SET person=?, ticket_roles=? WHERE token_hash=?",
                (person.id, json.dumps(roles), _token_hash(token)),
            )
        return token

    def ticket_roles(self, token: str | None) -> dict[str, set[str]] | None:
        """The roles from the ticket the session was started with, or None for no ticket."""
        if not token or len(token) > 120:
            return None
        with self._transaction() as db:
            row = db.execute(
                "SELECT ticket_roles FROM session WHERE token_hash=? AND expires>?",
                (_token_hash(token), _now().timestamp()),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        data = json.loads(row[0])
        return {str(meet): {str(r) for r in held} for meet, held in data.items()}

    def keep_id_keys(self, jwks: str) -> None:
        """ID's public keys, fetched while there is internet, for the tickets (KONTO-11)."""
        with self._transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO id_keys VALUES (1, ?, ?)", (jwks, _now().timestamp())
            )

    def id_keys(self) -> str | None:
        with self._transaction() as db:
            row = db.execute("SELECT jwks FROM id_keys WHERE id=1").fetchone()
        return str(row[0]) if row is not None else None

    def log_in_with_id(self, person: Person, id_token: str, access: IdAccess | None = None) -> str:
        """A session for someone ID vouched for. The hub keeps ID's token only to log out of ID
        too, and the access token for the client hub only to ask TrainMeet CAD for the person
        (CAD-11); both go with the session and are never shown."""
        with self._transaction() as db:
            token = self._new_session(db, PERSON, name=person.name)
            db.execute(
                "UPDATE session SET person=?, id_token=?, access=?, refresh=?, access_until=? "
                "WHERE token_hash=?",
                (
                    person.id,
                    id_token,
                    access.token if access else None,
                    access.refresh if access else None,
                    access.until if access else None,
                    _token_hash(token),
                ),
            )
        return token

    def id_access(self, token: str | None) -> IdAccess | None:
        """The access token from ID the session holds for the person, if any."""
        if not token or len(token) > 120:
            return None
        with self._transaction() as db:
            row = db.execute(
                "SELECT access, refresh, access_until FROM session WHERE token_hash=? "
                "AND expires>? AND person IS NOT NULL AND access IS NOT NULL",
                (_token_hash(token), _now().timestamp()),
            ).fetchone()
        if row is None:
            return None
        return IdAccess(str(row[0]), str(row[1]) if row[1] else None, float(row[2] or 0))

    def new_access(self, token: str, access: IdAccess) -> None:
        """A renewed access token for the session."""
        with self._transaction() as db:
            db.execute(
                "UPDATE session SET access=?, refresh=?, access_until=? WHERE token_hash=?",
                (access.token, access.refresh, access.until, _token_hash(token)),
            )

    def person(self, token: str | None) -> Person | None:
        """Who the session is, if it is a login with ID."""
        if not token or len(token) > 120:
            return None
        with self._transaction() as db:
            row = db.execute(
                "SELECT person, name FROM session WHERE token_hash=? AND expires>? "
                "AND person IS NOT NULL",
                (_token_hash(token), _now().timestamp()),
            ).fetchone()
        return Person(str(row[0]), str(row[1] or "")) if row is not None else None
