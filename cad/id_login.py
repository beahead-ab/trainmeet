"""Logging in with TrainMeet ID: OpenID Connect's code flow with PKCE, the same flow as Catalog.

    GET /api/cad/1/id/login?next=/moduler&lang=sv   to ID, with state, nonce and PKCE
    GET /api/cad/1/id/callback?code=...&state=...   back from ID: the code is exchanged for tokens
                                                    with CAD's client secret, the ID token is
                                                    checked, and CAD's session starts

The person's id in CAD is ID's subject. ID must say that the e-mail address is verified
(KONTO-10). CAD keeps the name, never the address; ID's token is kept with the session only to
log out of ID too, and goes with it.

A login that fails sends the browser back to the login page with ?inloggning=fel. Why goes to
the log, never a token, a code or an address.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
import jwt

from cad.db import Database
from cad.login import initials, key_hash
from cad.settings import IdSettings
from contracts.cad import CadAccount

COOKIE = "cad_id_login"
COOKIE_PATH = "/api/cad/1/id"
LIFETIME_SECONDS = 600
LOGIN_PAGE = "/logga-in"
NO_NAME = "Utan namn"
LANGUAGES = ("sv", "en")
_KEYS_AGAIN_AFTER = 60.0


class LoginFailed(Exception):
    """The login with ID did not go through. The message is for the log, the page for the
    browser."""

    def __init__(self, message: str, next_path: str = "/") -> None:
        super().__init__(message)
        self.next_path = next_path

    @property
    def back(self) -> str:
        query = {"inloggning": "fel"}
        if self.next_path != "/":
            query["next"] = self.next_path
        return f"{LOGIN_PAGE}?{urlencode(query)}"


def safe_next(value: str | None) -> str:
    """One of CAD's own pages to come back to, never another site or the API."""
    if (
        not value
        or len(value) > 500
        or not value.startswith("/")
        or value.startswith("//")
        or value.startswith("/api/")
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return "/"
    return value


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def account_from(claims: dict[str, Any]) -> CadAccount:
    """CAD's account from ID's checked claims."""
    try:
        subject = UUID(str(claims["sub"]))
    except (KeyError, ValueError) as error:
        raise LoginFailed("ID:s token har inget giltigt sub.") from error
    name = claims.get("name")
    if not isinstance(name, str) or not name.strip():
        parts = [claims.get("given_name"), claims.get("family_name")]
        name = " ".join(part for part in parts if isinstance(part, str))
    name = " ".join(name.split())[:80].strip() or NO_NAME
    return CadAccount(id=subject, name=name, initials=initials(name))


@dataclass(frozen=True)
class Started:
    key: str
    """Goes to the browser as a cookie, so only this browser can finish the login."""
    address: str
    """ID's login page."""


@dataclass(frozen=True)
class Finished:
    account: CadAccount
    id_token: str
    next_path: str


class IdLogin:
    def __init__(
        self, db: Database, settings: IdSettings, *, http: httpx.Client | None = None
    ) -> None:
        self.db = db
        self.settings = settings
        self.http = http if http is not None else httpx.Client(timeout=10.0)
        self._keys: dict[str, jwt.PyJWK] = {}
        self._keys_read: float | None = None
        self._lock = threading.Lock()

    def start(self, next_path: str, language: str | None = None) -> Started:
        key = secrets.token_urlsafe(32)
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(48)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM id_login WHERE expires_at < now()")
            conn.execute(
                "INSERT INTO id_login (key_hash, state, nonce, verifier, next_path, expires_at) "
                "VALUES (%s, %s, %s, %s, %s, now() + make_interval(secs => %s))",
                (key_hash(key), state, nonce, verifier, safe_next(next_path), LIFETIME_SECONDS),
            )
        query = {
            "client_id": self.settings.client,
            "redirect_uri": self.settings.redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
        }
        if language in LANGUAGES:
            query["ui_locales"] = str(language)
        address = f"{self.settings.issuer}/protocol/openid-connect/auth?{urlencode(query)}"
        return Started(key=key, address=address)

    def finish(
        self, key: str | None, state: str | None, code: str | None, error: str | None
    ) -> Finished:
        attempt = self._take(key)
        if attempt is None:
            raise LoginFailed(
                "Inloggningen hittades inte i den här webbläsaren eller är för gammal."
            )
        next_path = str(attempt["next_path"])
        if error:
            raise LoginFailed(f"ID svarade {error[:40]!r}.", next_path)
        if not state or not secrets.compare_digest(state, str(attempt["state"])):
            raise LoginFailed("Fel state tillbaka från ID.", next_path)
        if not code:
            raise LoginFailed("Ingen kod tillbaka från ID.", next_path)
        id_token = self._exchange(code, str(attempt["verifier"]), next_path)
        claims = self._check(id_token, str(attempt["nonce"]), next_path)
        try:
            account = account_from(claims)
        except LoginFailed as failed:
            raise LoginFailed(str(failed), next_path) from failed
        return Finished(account=account, id_token=id_token, next_path=next_path)

    def _take(self, key: str | None) -> dict[str, Any] | None:
        """The login this browser started, used once."""
        if not key or len(key) > 200:
            return None
        with self.db.transaction() as conn:
            row = conn.execute(
                "DELETE FROM id_login WHERE key_hash = %s "
                "RETURNING state, nonce, verifier, next_path, expires_at > now() AS valid",
                (key_hash(key),),
            ).fetchone()
        if row is None or not row["valid"]:
            return None
        return dict(row)

    def _exchange(self, code: str, verifier: str, next_path: str) -> str:
        try:
            answer = self.http.post(
                f"{self.settings.internal}/protocol/openid-connect/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.settings.redirect_uri,
                    "code_verifier": verifier,
                },
                auth=(self.settings.client, self.settings.secret),
            )
        except httpx.HTTPError as error:
            raise LoginFailed(f"ID svarar inte: {type(error).__name__}.", next_path) from error
        if answer.status_code != 200:
            reason = ""
            if answer.headers.get("content-type", "").startswith("application/json"):
                reason = str(answer.json().get("error", ""))[:40]
            raise LoginFailed(f"ID:s token svarade {answer.status_code} {reason}.", next_path)
        id_token = answer.json().get("id_token")
        if not isinstance(id_token, str):
            raise LoginFailed("ID gav ingen ID-token.", next_path)
        return id_token

    def _check(self, id_token: str, nonce: str, next_path: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(id_token)
            key = self._key(str(header.get("kid", "")))
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key=key,
                algorithms=[key.algorithm_name],  # the key's own: never a shared secret
                audience=self.settings.client,
                issuer=self.settings.issuer,
                leeway=30,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except (jwt.PyJWTError, httpx.HTTPError, LookupError) as error:
            raise LoginFailed(
                f"ID:s token godtas inte: {type(error).__name__}.", next_path
            ) from error
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise LoginFailed("Fel nonce i ID:s token.", next_path)
        if claims.get("azp", self.settings.client) != self.settings.client:
            raise LoginFailed("ID:s token är till en annan app.", next_path)
        if claims.get("email_verified") is not True:
            raise LoginFailed("E-posten är inte verifierad i ID.", next_path)
        return claims

    def _key(self, kid: str) -> jwt.PyJWK:
        """ID's signing key, read again when ID has a new one, at most once a minute."""
        with self._lock:
            stale = (
                self._keys_read is None or time.monotonic() - self._keys_read > _KEYS_AGAIN_AFTER
            )
            if kid not in self._keys and stale:
                answer = self.http.get(f"{self.settings.internal}/protocol/openid-connect/certs")
                answer.raise_for_status()
                keys: dict[str, jwt.PyJWK] = {}
                for item in answer.json().get("keys", []):
                    if item.get("use", "sig") == "sig" and "kid" in item:
                        try:
                            keys[str(item["kid"])] = jwt.PyJWK(item)
                        except jwt.PyJWTError:
                            continue  # a key type CAD does not use
                self._keys = keys
                self._keys_read = time.monotonic()
            return self._keys[kid]

    def logout_address(self, id_token: str) -> str:
        """Where the browser goes so that ID logs out too, and then comes back (KONTO-01)."""
        query = {
            "id_token_hint": id_token,
            "client_id": self.settings.client,
            "post_logout_redirect_uri": self.settings.public_url + "/",
        }
        return f"{self.settings.issuer}/protocol/openid-connect/logout?{urlencode(query)}"
