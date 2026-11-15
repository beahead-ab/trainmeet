"""Who asks ID's API: a person through the web app, or an app with its own token (#67).

The person logs in to ID's web app the same way as to Catalog (catalog/id_login.py): OpenID
Connect's code flow with PKCE, state and nonce against ID's own realm, and a session key in an
HttpOnly cookie, of which only the SHA-256 is stored. The address must be verified (KONTO-10).

An app asks about roles with an access token from Keycloak's client credentials (KONTO-34):
signed by the realm, unexpired, and issued to one of the apps ID_API_APPS names.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
import jwt

from contracts.id import Account
from id.db import Database
from id.roles import initials
from id.settings import Settings

LOGGER = logging.getLogger("id.login")

COOKIE = "id_session"
ATTEMPT_COOKIE = "id_login"
ATTEMPT_PATH = "/api/id/1/login"
SESSION_LIFETIME = timedelta(days=30)
ATTEMPT_SECONDS = 600
_KEYS_AGAIN_AFTER = 60.0


class LoginFailed(Exception):
    def __init__(self, message: str, next_path: str = "/") -> None:
        super().__init__(message)
        self.next_path = next_path

    @property
    def back(self) -> str:
        return "/?" + urlencode({"inloggning": "fel"})


def key_hash(key: str) -> bytes:
    return hashlib.sha256(key.encode("utf-8")).digest()


def safe_next(value: str | None) -> str:
    """One of the web app's own pages to come back to, never another site or the API."""
    if (
        not value
        or len(value) > 500
        or not value.startswith("/")
        or value.startswith("//")
        or value.startswith("/api/")
        or value.startswith("/realms/")
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return "/"
    return value


class Keys:
    """The realm's signing keys, read again when it has a new one, at most once a minute."""

    def __init__(self, http: httpx.Client, address: str) -> None:
        self.http = http
        self.address = address
        self._keys: dict[str, jwt.PyJWK] = {}
        self._read: float | None = None
        self._lock = threading.Lock()

    def get(self, kid: str) -> jwt.PyJWK:
        with self._lock:
            stale = self._read is None or time.monotonic() - self._read > _KEYS_AGAIN_AFTER
            if kid not in self._keys and stale:
                answer = self.http.get(self.address)
                answer.raise_for_status()
                keys: dict[str, jwt.PyJWK] = {}
                for item in answer.json().get("keys", []):
                    if item.get("use", "sig") == "sig" and "kid" in item:
                        try:
                            keys[str(item["kid"])] = jwt.PyJWK(item)
                        except jwt.PyJWTError:
                            continue
                self._keys = keys
                self._read = time.monotonic()
            return self._keys[kid]

    def decode(self, token: str, *, issuer: str, audience: str | None = None) -> dict[str, Any]:
        header = jwt.get_unverified_header(token)
        key = self.get(str(header.get("kid", "")))
        claims: dict[str, Any] = jwt.decode(
            token,
            key=key,
            algorithms=[key.algorithm_name],
            issuer=issuer,
            audience=audience,
            leeway=30,
            options={"require": ["exp", "iat", "iss", "sub"], "verify_aud": audience is not None},
        )
        return claims


def account_from(claims: dict[str, Any]) -> Account:
    try:
        subject = UUID(str(claims["sub"]))
    except (KeyError, ValueError) as error:
        raise LoginFailed("ID:s token har inget giltigt sub.") from error
    email = str(claims.get("email", "")).strip().lower()
    if claims.get("email_verified") is not True or "@" not in email:
        raise LoginFailed("E-posten är inte verifierad i ID.")
    name = claims.get("name")
    if not isinstance(name, str) or not name.strip():
        name = "Utan namn"
    name = " ".join(name.split())[:80]
    return Account(id=subject, name=name, initials=initials(name), email=email)


@dataclass(frozen=True)
class Started:
    key: str
    address: str


class Login:
    def __init__(self, db: Database, settings: Settings, http: httpx.Client | None = None) -> None:
        self.db = db
        self.settings = settings
        self.http = http if http is not None else httpx.Client(timeout=10.0)
        self.keys = Keys(self.http, settings.internal + "/protocol/openid-connect/certs")

    # --- The web app's login ---------------------------------------------------------------

    def start(self, next_path: str, language: str | None = None) -> Started:
        key, state, nonce = (
            secrets.token_urlsafe(32),
            secrets.token_urlsafe(24),
            secrets.token_urlsafe(24),
        )
        verifier = secrets.token_urlsafe(48)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM login_attempt WHERE expires_at < now()")
            conn.execute(
                "INSERT INTO login_attempt "
                "(key_hash, state, nonce, verifier, next_path, expires_at) "
                "VALUES (%s, %s, %s, %s, %s, now() + make_interval(secs => %s))",
                (key_hash(key), state, nonce, verifier, safe_next(next_path), ATTEMPT_SECONDS),
            )
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        query = {
            "client_id": self.settings.client,
            "redirect_uri": self.settings.redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge.rstrip(b"=").decode(),
            "code_challenge_method": "S256",
        }
        if language in ("sv", "en"):
            query["ui_locales"] = str(language)
        address = f"{self.settings.issuer}/protocol/openid-connect/auth?{urlencode(query)}"
        return Started(key=key, address=address)

    def finish(
        self, key: str | None, state: str | None, code: str | None, error: str | None
    ) -> tuple[Account, str, str]:
        """The account, ID's token and the page to go to. Raises LoginFailed."""
        if not key or len(key) > 200:
            raise LoginFailed("Inloggningen hittades inte i den här webbläsaren.")
        with self.db.transaction() as conn:
            row = conn.execute(
                "DELETE FROM login_attempt WHERE key_hash = %s "
                "RETURNING state, nonce, verifier, next_path, expires_at > now() AS valid",
                (key_hash(key),),
            ).fetchone()
        if row is None or not row["valid"]:
            raise LoginFailed("Inloggningen hittades inte eller är för gammal.")
        next_path = str(row["next_path"])
        if error:
            raise LoginFailed(f"ID svarade {error[:40]!r}.", next_path)
        if not state or not secrets.compare_digest(state, str(row["state"])) or not code:
            raise LoginFailed("Fel state eller ingen kod tillbaka.", next_path)
        try:
            answer = self.http.post(
                f"{self.settings.internal}/protocol/openid-connect/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.settings.redirect_uri,
                    "code_verifier": str(row["verifier"]),
                },
                auth=(self.settings.client, self.settings.secret),
            )
        except httpx.HTTPError as failure:
            raise LoginFailed(f"ID svarar inte: {type(failure).__name__}.", next_path) from failure
        if answer.status_code != 200:
            raise LoginFailed(f"ID:s token svarade {answer.status_code}.", next_path)
        id_token = answer.json().get("id_token")
        if not isinstance(id_token, str):
            raise LoginFailed("ID gav ingen ID-token.", next_path)
        try:
            claims = self.keys.decode(
                id_token, issuer=self.settings.issuer, audience=self.settings.client
            )
        except (jwt.PyJWTError, httpx.HTTPError, LookupError) as failure:
            raise LoginFailed(
                f"ID:s token godtas inte: {type(failure).__name__}.", next_path
            ) from failure
        if not secrets.compare_digest(str(claims.get("nonce", "")), str(row["nonce"])):
            raise LoginFailed("Fel nonce i ID:s token.", next_path)
        try:
            account = account_from(claims)
        except LoginFailed as failed:
            raise LoginFailed(str(failed), next_path) from failed
        return account, id_token, next_path

    def logout_address(self, id_token: str) -> str:
        query = {
            "id_token_hint": id_token,
            "client_id": self.settings.client,
            "post_logout_redirect_uri": self.settings.public_url + "/",
        }
        return f"{self.settings.issuer}/protocol/openid-connect/logout?{urlencode(query)}"

    # --- Sessions ---------------------------------------------------------------------------

    def start_session(self, account: Account, id_token: str) -> str:
        key = secrets.token_urlsafe(32)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM login_session WHERE expires_at < now()")
            conn.execute(
                "INSERT INTO login_session (key_hash, person_id, expires_at, id_token) "
                "VALUES (%s, %s, now() + %s, %s)",
                (key_hash(key), account.id, SESSION_LIFETIME, id_token),
            )
        return key

    def account(self, key: str | None) -> Account | None:
        if not key or len(key) > 200:
            return None
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT person.id, person.name, person.email FROM login_session "
                "JOIN person ON person.id = login_session.person_id "
                "WHERE key_hash = %s AND expires_at > now()",
                (key_hash(key),),
            ).fetchone()
        if row is None:
            return None
        name = str(row["name"])
        return Account(id=row["id"], name=name, initials=initials(name), email=str(row["email"]))

    def end_session(self, key: str | None) -> str | None:
        if not key or len(key) > 200:
            return None
        with self.db.transaction() as conn:
            row = conn.execute(
                "DELETE FROM login_session WHERE key_hash = %s RETURNING id_token", (key_hash(key),)
            ).fetchone()
        return str(row["id_token"]) if row is not None and row["id_token"] else None

    # --- The apps (KONTO-34) ----------------------------------------------------------------

    def app(self, authorization: str | None) -> str | None:
        """The app a bearer token belongs to, if it is one of ID's apps; otherwise None."""
        if not authorization or not authorization.lower().startswith("bearer "):
            return None
        token = authorization[7:].strip()
        try:
            claims = self.keys.decode(token, issuer=self.settings.issuer)
        except (jwt.PyJWTError, httpx.HTTPError, LookupError) as failure:
            LOGGER.info("En apps token godtas inte: %s", type(failure).__name__)
            return None
        app = str(claims.get("azp", ""))
        return app if app in self.settings.apps else None
