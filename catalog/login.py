"""Who is logged in: the session cookie and the trial login (CAT-214, CAT-195).

The session key is random and shown to the browser once, as an HttpOnly cookie. Only its
SHA-256 is stored, so a copy of the database logs no one in. TrainMeet ID replaces the trial
login in #49; the session stays the same.

The trial login's accounts are fixed, and hold no personal data. Anyone who can open the test
environment can log in as them, so the test environment holds only test data.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from uuid import UUID, uuid5

from catalog.db import Database
from contracts.catalog import Account

COOKIE = "catalog_session"
SESSION_LIFETIME = timedelta(days=30)
_TRIAL_NAMESPACE = UUID("6f1d2c1e-6a43-5b8e-9c5a-0c3a7d4f9b21")


def initials(name: str) -> str:
    parts = [part for part in name.split() if part[:1].isalnum()]
    letters = "".join(part[0] for part in parts[:2]).upper()
    return letters or "?"


def trial_account(letter: str) -> Account:
    name = f"Provkonto {letter}"
    return Account(
        id=uuid5(_TRIAL_NAMESPACE, f"trial-{letter}"), name=name, initials=initials(name)
    )


TRIAL_ACCOUNTS: tuple[Account, ...] = tuple(trial_account(letter) for letter in "ABCD")


def key_hash(key: str) -> bytes:
    return hashlib.sha256(key.encode("utf-8")).digest()


class Sessions:
    def __init__(self, db: Database) -> None:
        self.db = db

    def start(self, account: Account) -> str:
        """Log the account in. Its owner row is made the first time (the empty fleet)."""
        key = secrets.token_urlsafe(32)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM login_session WHERE expires_at < now()")
            conn.execute(
                "INSERT INTO owner (id, name) VALUES (%s, %s) "
                "ON CONFLICT (id) DO UPDATE SET name = excluded.name",
                (account.id, account.name),
            )
            conn.execute(
                "INSERT INTO login_session (key_hash, owner_id, expires_at) "
                "VALUES (%s, %s, now() + %s)",
                (key_hash(key), account.id, SESSION_LIFETIME),
            )
        return key

    def account(self, key: str | None) -> Account | None:
        """The account a session key belongs to, if the session is still valid."""
        if not key or len(key) > 200:
            return None
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT owner.id, owner.name FROM login_session "
                "JOIN owner ON owner.id = login_session.owner_id "
                "WHERE key_hash = %s AND expires_at > now()",
                (key_hash(key),),
            ).fetchone()
        if row is None:
            return None
        name = str(row["name"])
        return Account(id=row["id"], name=name, initials=initials(name))

    def end(self, key: str | None) -> None:
        if not key or len(key) > 200:
            return
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM login_session WHERE key_hash = %s", (key_hash(key),))
