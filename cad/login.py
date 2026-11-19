"""Who is logged in: the session cookie and the trial login.

The session key is random and shown to the browser once, as an HttpOnly cookie. Only its SHA-256
is stored, so a copy of the database logs no one in. The login itself is TrainMeet ID
(cad/id_login.py); the trial login's fixed accounts are for the browser test and the test
environment, and hold no personal data.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from uuid import UUID, uuid5

from cad.db import Database
from contracts.cad import CadAccount

COOKIE = "cad_session"
SESSION_LIFETIME = timedelta(days=30)
_TRIAL_NAMESPACE = UUID("3c9a5e1d-89a0-5d2b-8e1f-7a6b5c4d3e2f")


def initials(name: str) -> str:
    parts = [part for part in name.split() if part[:1].isalnum()]
    letters = "".join(part[0] for part in parts[:2]).upper()
    return letters or "?"


def trial_account(letter: str) -> CadAccount:
    name = f"Provkonto {letter}"
    return CadAccount(
        id=uuid5(_TRIAL_NAMESPACE, f"trial-{letter}"), name=name, initials=initials(name)
    )


TRIAL_ACCOUNTS: tuple[CadAccount, ...] = tuple(trial_account(letter) for letter in "ABCD")


def key_hash(key: str) -> bytes:
    return hashlib.sha256(key.encode("utf-8")).digest()


class Sessions:
    def __init__(self, db: Database) -> None:
        self.db = db

    def start(self, account: CadAccount, id_token: str | None = None) -> str:
        """Log the account in. Its person row is made the first time, and its name kept."""
        key = secrets.token_urlsafe(32)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM login_session WHERE expires_at < now()")
            conn.execute(
                "INSERT INTO person (id, name) VALUES (%s, %s) "
                "ON CONFLICT (id) DO UPDATE SET name = excluded.name",
                (account.id, account.name),
            )
            conn.execute(
                "INSERT INTO login_session (key_hash, person_id, expires_at, id_token) "
                "VALUES (%s, %s, now() + %s, %s)",
                (key_hash(key), account.id, SESSION_LIFETIME, id_token),
            )
        return key

    def account(self, key: str | None) -> CadAccount | None:
        """The account a session key belongs to, if the session is still valid."""
        if not key or len(key) > 200:
            return None
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT person.id, person.name FROM login_session "
                "JOIN person ON person.id = login_session.person_id "
                "WHERE key_hash = %s AND expires_at > now()",
                (key_hash(key),),
            ).fetchone()
        if row is None:
            return None
        name = str(row["name"])
        return CadAccount(id=row["id"], name=name, initials=initials(name))

    def end(self, key: str | None) -> str | None:
        """Log out here. Gives ID's token, if the session came from ID, to log out there too."""
        if not key or len(key) > 200:
            return None
        with self.db.transaction() as conn:
            row = conn.execute(
                "DELETE FROM login_session WHERE key_hash = %s RETURNING id_token",
                (key_hash(key),),
            ).fetchone()
        return str(row["id_token"]) if row is not None and row["id_token"] else None
