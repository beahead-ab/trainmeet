"""Kopplingen mellan Pi:n och molnet (SYNK-02, SYNK-13, H11, F16).

In the cloud: the Pi asks for an attempt, and someone who may plan a meet here logs in and
chooses the meet for it (F16, KONTO-22); the Pi then gets a key of its own with the attempt's
secret, which only the Pi has. Or, as the reserve, the administrator asks for a six-digit code
for a meet and the Pi gives it. Only the hashes of the key, the attempt and the secret are kept,
the code and the attempt are used once and last 15 minutes, and too many wrong ones make the
cloud wait (as the PIN does).

On the Pi: the cloud's address and the key, per meet it follows, and an attempt's secret until
it is used. The key never leaves Synk's file and is never shown or written to a log.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Final

from contracts.drift import ProposalStatus
from contracts.sync import CloudLink, Follower, Hello, LinkCode
from core.sqlite import connect, prepare, reading

CODE_LIFETIME: Final = timedelta(minutes=15)
ATTEMPT_LIFETIME: Final = timedelta(minutes=15)
MAX_ATTEMPTS: Final = 50  # open attempts at once, before the cloud waits
MAX_FAILURES: Final = 10  # wrong codes within FAILURE_WINDOW before the cloud waits
FAILURE_WINDOW: Final = timedelta(minutes=15)

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS sync_self (hub_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sync_code (
    code_hash TEXT PRIMARY KEY, meet_id TEXT NOT NULL, expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_failure (at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sync_follower (
    key_hash TEXT PRIMARY KEY, meet_id TEXT NOT NULL, hub_id TEXT NOT NULL,
    hello TEXT NOT NULL, linked REAL NOT NULL, heard REAL
);
CREATE TABLE IF NOT EXISTS sync_answer (
    meet_id TEXT NOT NULL, change_id TEXT NOT NULL, status TEXT NOT NULL,
    PRIMARY KEY (meet_id, change_id)
);
CREATE TABLE IF NOT EXISTS sync_attempt (
    attempt_hash TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, hello TEXT NOT NULL,
    back TEXT NOT NULL, expires REAL NOT NULL, meet_id TEXT
);
CREATE TABLE IF NOT EXISTS sync_pending (
    attempt TEXT PRIMARY KEY, address TEXT NOT NULL, secret TEXT NOT NULL, expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_leader (
    meet_id TEXT PRIMARY KEY, address TEXT NOT NULL, key TEXT NOT NULL,
    meet_name TEXT NOT NULL, cloud TEXT NOT NULL, linked REAL NOT NULL,
    heard REAL, problem TEXT
);
"""


class LinkError(Exception):
    """The message is for the person linking the Pi. reason: the same, in a word, for the
    Pi's page after the browser comes back from the cloud (F16)."""

    status = 409
    reason = "nej"


class WrongCode(LinkError):
    status = 403
    reason = "gick-ut"


class TooManyTries(LinkError):
    status = 429
    reason = "vanta"


class NotChosen(LinkError):
    """The Pi came for its key before a meet was chosen in the cloud."""

    reason = "ingen-traff"


class Unanswered(LinkError):
    reason = "svarar-inte"


class NotYet(LinkError):
    """The cloud is older, and links only with the code."""

    reason = "gammal"


class BadAddress(LinkError):
    reason = "adress"


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _time(at: float | None) -> datetime | None:
    return None if at is None else datetime.fromtimestamp(at, UTC)


@dataclass(frozen=True)
class Attempt:
    """An attempt to link a Pi, as the cloud keeps it: never the secret."""

    hello: Hello
    back: str
    expires: datetime
    meet: str | None


@dataclass(frozen=True)
class Reach:
    """Where the Pi reaches the cloud for a meet, and with which key."""

    meet: str
    address: str
    key: str


class Links:
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

    def hub_id(self) -> str:
        """This hub's id in the protocol: made at first use, not a secret."""
        with self._transaction() as db:
            row = db.execute("SELECT hub_id FROM sync_self").fetchone()
            if row is not None:
                return str(row[0])
            hub_id = f"hub-{secrets.token_hex(6)}"
            db.execute("INSERT INTO sync_self VALUES (?)", (hub_id,))
            return hub_id

    # --- In the cloud ------------------------------------------------------------------------

    def new_code(self, meet: str, now: datetime) -> LinkCode:
        """A code for the meet. A new one takes the place of the one before."""
        expires = now + CODE_LIFETIME
        with self._transaction() as db:
            db.execute(
                "DELETE FROM sync_code WHERE meet_id=? OR expires<?", (meet, now.timestamp())
            )
            while True:
                code = f"{secrets.randbelow(1_000_000):06d}"
                taken = db.execute(
                    "SELECT 1 FROM sync_code WHERE code_hash=?", (_hash(code),)
                ).fetchone()
                if taken is None:
                    break
            db.execute(
                "INSERT INTO sync_code VALUES (?, ?, ?)", (_hash(code), meet, expires.timestamp())
            )
        return LinkCode(meet=meet, code=code, expires=expires)

    def redeem(self, code: str, hello: Hello, now: datetime) -> tuple[str, str]:
        """The code gives the Pi the meet and a key of its own. Raises WrongCode or
        TooManyTries."""
        moment = now.timestamp()
        with self._transaction() as db:
            db.execute(
                "DELETE FROM sync_failure WHERE at<?", (moment - FAILURE_WINDOW.total_seconds(),)
            )
            (failures,) = db.execute("SELECT count(*) FROM sync_failure").fetchone()
            if failures >= MAX_FAILURES:
                raise TooManyTries("För många fel koder. Vänta en stund och försök igen.")
            row = db.execute(
                "SELECT meet_id FROM sync_code WHERE code_hash=? AND expires>=?",
                (_hash(code), moment),
            ).fetchone()
            if row is not None:
                meet = str(row[0])
                db.execute("DELETE FROM sync_code WHERE code_hash=?", (_hash(code),))
                return meet, self._follow(db, meet, hello, moment)
            # Counted, and kept: the refusal is raised once the failure is written.
            db.execute("INSERT INTO sync_failure VALUES (?)", (moment,))
        raise WrongCode("Koden gäller inte. Be om en ny kod i molnet.")

    @staticmethod
    def _follow(db: sqlite3.Connection, meet: str, hello: Hello, moment: float) -> str:
        """The code or the attempt is used: the Pi follows the meet with a key of its own."""
        # The same Pi linked again takes the place of its old key.
        db.execute("DELETE FROM sync_follower WHERE meet_id=? AND hub_id=?", (meet, hello.hub_id))
        key = secrets.token_urlsafe(32)
        db.execute(
            "INSERT INTO sync_follower VALUES (?, ?, ?, ?, ?, NULL)",
            (_hash(key), meet, hello.hub_id, hello.model_dump_json(), moment),
        )
        return key

    def begin(self, hello: Hello, back: str, now: datetime) -> tuple[str, str, datetime]:
        """An attempt for the Pi: the attempt, which the browser carries, and the secret, which
        stays on the Pi. Raises TooManyTries when too many are open."""
        expires = now + ATTEMPT_LIFETIME
        attempt, secret = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        with self._transaction() as db:
            db.execute("DELETE FROM sync_attempt WHERE expires<?", (now.timestamp(),))
            (open_now,) = db.execute("SELECT count(*) FROM sync_attempt").fetchone()
            if open_now >= MAX_ATTEMPTS:
                raise TooManyTries("Molnet har för många kopplingar på gång. Försök om en stund.")
            db.execute(
                "INSERT INTO sync_attempt VALUES (?, ?, ?, ?, ?, NULL)",
                (_hash(attempt), _hash(secret), hello.model_dump_json(), back, expires.timestamp()),
            )
        return attempt, secret, expires

    def attempt(self, attempt: str, now: datetime) -> Attempt | None:
        with self._reading() as db:
            row = db.execute(
                "SELECT hello, back, expires, meet_id FROM sync_attempt"
                " WHERE attempt_hash=? AND expires>=?",
                (_hash(attempt), now.timestamp()),
            ).fetchone()
        if row is None:
            return None
        hello, back, expires, meet = row
        return Attempt(
            Hello.model_validate_json(hello),
            str(back),
            datetime.fromtimestamp(expires, UTC),
            None if meet is None else str(meet),
        )

    def choose(self, attempt: str, meet: str, now: datetime) -> bool:
        """The meet the Pi is to follow, chosen in the cloud. False if the attempt is gone."""
        with self._transaction() as db:
            chosen = db.execute(
                "UPDATE sync_attempt SET meet_id=? WHERE attempt_hash=? AND expires>=?",
                (meet, _hash(attempt), now.timestamp()),
            ).rowcount
        return chosen > 0

    def redeem_attempt(self, attempt: str, secret: str, now: datetime) -> tuple[str, str]:
        """The Pi's secret gives it the chosen meet and a key of its own, once. Raises
        WrongCode, TooManyTries, or LinkError while no meet is chosen."""
        moment = now.timestamp()
        with self._transaction() as db:
            db.execute(
                "DELETE FROM sync_failure WHERE at<?", (moment - FAILURE_WINDOW.total_seconds(),)
            )
            (failures,) = db.execute("SELECT count(*) FROM sync_failure").fetchone()
            if failures >= MAX_FAILURES:
                raise TooManyTries("För många fel försök. Vänta en stund och börja om på Pi:n.")
            row = db.execute(
                "SELECT hello, meet_id FROM sync_attempt"
                " WHERE attempt_hash=? AND secret_hash=? AND expires>=?",
                (_hash(attempt), _hash(secret), moment),
            ).fetchone()
            if row is not None:
                if row[1] is None:
                    raise NotChosen("Ingen träff är vald än. Välj träffen i molnet.")
                meet = str(row[1])
                db.execute("DELETE FROM sync_attempt WHERE attempt_hash=?", (_hash(attempt),))
                return meet, self._follow(db, meet, Hello.model_validate_json(row[0]), moment)
            db.execute("INSERT INTO sync_failure VALUES (?)", (moment,))
        raise WrongCode("Försöket gäller inte längre. Börja om på Pi:n.")

    def follower(self, meet: str, key: str, now: datetime) -> Follower | None:
        """The Pi the key belongs to, if it follows the meet; heard now."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT hello, linked FROM sync_follower WHERE key_hash=? AND meet_id=?",
                (_hash(key), meet),
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE sync_follower SET heard=? WHERE key_hash=?", (now.timestamp(), _hash(key))
            )
        hello = Hello.model_validate_json(row[0])
        return Follower(
            hub_id=hello.hub_id,
            hub_name=hello.hub_name,
            software=hello.software,
            linked=datetime.fromtimestamp(row[1], UTC),
            heard=now,
        )

    def followers(self, meet: str) -> list[Follower]:
        with self._reading() as db:
            rows = db.execute(
                "SELECT hello, linked, heard FROM sync_follower WHERE meet_id=? ORDER BY linked",
                (meet,),
            ).fetchall()
        found = []
        for hello_json, linked, heard in rows:
            hello = Hello.model_validate_json(hello_json)
            found.append(
                Follower(
                    hub_id=hello.hub_id,
                    hub_name=hello.hub_name,
                    software=hello.software,
                    linked=datetime.fromtimestamp(linked, UTC),
                    heard=_time(heard),
                )
            )
        return found

    def revoke(self, meet: str, hub_id: str) -> bool:
        """Koppla bort en Pi: its key no longer works."""
        with self._transaction() as db:
            gone = db.execute(
                "DELETE FROM sync_follower WHERE meet_id=? AND hub_id=?", (meet, hub_id)
            ).rowcount
        return gone > 0

    # --- On the Pi ---------------------------------------------------------------------------

    def lead(self, address: str, key: str, meet: str, meet_name: str, cloud: Hello) -> None:
        """The Pi follows the meet in the cloud at the address, with the key it was given."""
        with self._transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO sync_leader VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)",
                (
                    meet,
                    address,
                    key,
                    meet_name,
                    cloud.model_dump_json(),
                    datetime.now(UTC).timestamp(),
                ),
            )

    def keep_attempt(self, attempt: str, address: str, secret: str, expires: datetime) -> None:
        """The attempt's secret, on the Pi until the browser comes back from the cloud."""
        with self._transaction() as db:
            db.execute("DELETE FROM sync_pending WHERE expires<?", (datetime.now(UTC).timestamp(),))
            db.execute(
                "INSERT OR REPLACE INTO sync_pending VALUES (?, ?, ?, ?)",
                (attempt, address, secret, expires.timestamp()),
            )

    def take_attempt(self, attempt: str, now: datetime) -> tuple[str, str] | None:
        """The cloud's address and the secret for the attempt, once."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT address, secret FROM sync_pending WHERE attempt=? AND expires>=?",
                (attempt, now.timestamp()),
            ).fetchone()
            db.execute("DELETE FROM sync_pending WHERE attempt=?", (attempt,))
        return None if row is None else (str(row[0]), str(row[1]))

    def reaches(self) -> list[Reach]:
        with self._reading() as db:
            rows = db.execute("SELECT meet_id, address, key FROM sync_leader").fetchall()
        return [Reach(str(m), str(a), str(k)) for m, a, k in rows]

    def clouds(self, counts: dict[str, int]) -> list[CloudLink]:
        """The meets the Pi follows, as the administrator sees them: never the key."""
        with self._reading() as db:
            rows = db.execute(
                "SELECT meet_id, address, meet_name, cloud, linked, heard, problem"
                " FROM sync_leader ORDER BY linked"
            ).fetchall()
        return [
            CloudLink(
                address=address,
                meet=meet,
                meet_name=meet_name,
                cloud_name=Hello.model_validate_json(cloud).hub_name,
                linked=datetime.fromtimestamp(linked, UTC),
                heard=_time(heard),
                versions=counts.get(meet, 0),
                problem=problem,
            )
            for meet, address, meet_name, cloud, linked, heard, problem in rows
        ]

    def heard(self, meet: str, now: datetime, problem: str | None = None) -> None:
        """How the last call to the cloud went: heard, or why not."""
        with self._transaction() as db:
            if problem is None:
                db.execute(
                    "UPDATE sync_leader SET heard=?, problem=NULL WHERE meet_id=?",
                    (now.timestamp(), meet),
                )
            else:
                db.execute("UPDATE sync_leader SET problem=? WHERE meet_id=?", (problem, meet))

    def keep_answers(self, meet: str, answers: dict[str, ProposalStatus]) -> None:
        """Planering's answers in the cloud to the Pi's driftändringar (4.4)."""
        with self._transaction() as db:
            db.executemany(
                "INSERT OR REPLACE INTO sync_answer VALUES (?, ?, ?)",
                ((meet, change, status.value) for change, status in answers.items()),
            )

    def answers(self, meet: str) -> dict[str, ProposalStatus]:
        with self._reading() as db:
            rows = db.execute(
                "SELECT change_id, status FROM sync_answer WHERE meet_id=?", (meet,)
            ).fetchall()
        return {str(change): ProposalStatus(status) for change, status in rows}

    def forget(self, meet: str) -> bool:
        """Koppla bort: the Pi no longer follows the meet. Its versions stay, frozen."""
        with self._transaction() as db:
            return db.execute("DELETE FROM sync_leader WHERE meet_id=?", (meet,)).rowcount > 0
