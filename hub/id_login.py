"""Logga in med TrainMeet ID i Hubben (#78, KONTO-27): OpenID Connect's code flow with PKCE,
the same flow as Catalog's (catalog/id_login.py), with the hub's own storage.

    GET /api/hub/id/login?next=/drift   to ID, with state, nonce and PKCE
    GET /api/hub/id/callback            back from ID: the code is exchanged for tokens, the ID
                                        token is checked, and the hub's session starts

ID must say that the e-mail address is verified (KONTO-10). The hub keeps the person's id (the
token's sub) and name, never the address. ID's token is kept with the session only to log out
of ID too. A login that fails sends the browser back to the start page with ?inloggning=fel; why
goes to the log, never a token, a code or an address.

The hub's PIN stays what it was (H18): the one who has it is the hub's own administrator. A login
with ID gives the roles ID holds at the meet (ID10, KONTO-34), asked of ID's API.

Settings, from the environment; without TRAINMEET_ID_ISSUER the hub has no login with ID:

TRAINMEET_ID_ISSUER    ID's realm, for example https://id.trainmeet.app/realms/trainmeet.
TRAINMEET_ID_INTERNAL  Where the hub itself reaches the same realm, if not at the issuer's
                       address (in the test environment, http://id:8080/realms/trainmeet).
TRAINMEET_ID_CLIENT    The hub's client in ID. Default "hub".
TRAINMEET_ID_SECRET    The client's secret. Never written to the log.
TRAINMEET_ID_API       ID's own API, which the hub asks about the roles at a meet.
TRAINMEET_PUBLIC_URL   The hub's own address, where ID sends the browser back.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
import jwt

from hub.local import IdAccess, LocalLogin, Person

LOGGER = logging.getLogger("hub.id")

COOKIE = "trainmeet_id_login"
COOKIE_PATH = "/api/hub/id"
LIFETIME_SECONDS = 600
START_PAGE = "/"
NO_NAME = "Utan namn"
LANGUAGES = ("sv", "en")
_KEYS_AGAIN_AFTER = 60.0


@dataclass(frozen=True)
class IdSettings:
    issuer: str
    secret: str = field(repr=False)
    public_url: str
    internal: str
    client: str = "hub"
    api: str | None = None

    @property
    def redirect_uri(self) -> str:
        return self.public_url + "/api/hub/id/callback"

    @property
    def id_public(self) -> str:
        """ID's web app: the issuer's address without the realm."""
        return self.issuer.split("/realms/", 1)[0]


def settings_from(env: Mapping[str, str] | None = None) -> IdSettings | None:
    """The login with ID, if the hub is set up for it. Half a setting is said in the log and
    leaves the login out, so that the hub still starts."""
    source = os.environ if env is None else env
    issuer = source.get("TRAINMEET_ID_ISSUER", "").strip().rstrip("/")
    if not issuer:
        return None
    secret = source.get("TRAINMEET_ID_SECRET", "").strip()
    public = source.get("TRAINMEET_PUBLIC_URL", "").strip().rstrip("/")
    if not secret or not public:
        LOGGER.warning(
            "TRAINMEET_ID_ISSUER är satt men TRAINMEET_ID_SECRET eller TRAINMEET_PUBLIC_URL "
            "saknas, så hubben loggar inte in med ID."
        )
        return None
    internal = source.get("TRAINMEET_ID_INTERNAL", "").strip().rstrip("/") or issuer
    client = source.get("TRAINMEET_ID_CLIENT", "").strip() or "hub"
    api = source.get("TRAINMEET_ID_API", "").strip().rstrip("/") or None
    return IdSettings(issuer, secret, public, internal, client, api)


class LoginFailed(Exception):
    """The login with ID did not go through. The message is for the log, the page for the
    browser."""

    def __init__(self, message: str, next_path: str = START_PAGE) -> None:
        super().__init__(message)
        self.next_path = next_path

    @property
    def back(self) -> str:
        query = {"inloggning": "fel"}
        if self.next_path != START_PAGE:
            query["next"] = self.next_path
        return f"{START_PAGE}?{urlencode(query)}"


def safe_next(value: str | None) -> str:
    """One of the hub's own pages to come back to, never another site or the API."""
    if (
        not value
        or len(value) > 500
        or not value.startswith("/")
        or value.startswith("//")
        or value.startswith("/api/")
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return START_PAGE
    return value


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def person_from(claims: dict[str, Any]) -> Person:
    """The person from ID's checked claims: the id and a name, never the address."""
    try:
        subject = str(UUID(str(claims["sub"])))
    except (KeyError, ValueError) as error:
        raise LoginFailed("ID:s token har inget giltigt sub.") from error
    name = claims.get("name")
    if not isinstance(name, str) or not name.strip():
        parts = [claims.get("given_name"), claims.get("family_name")]
        name = " ".join(part for part in parts if isinstance(part, str))
    name = " ".join(name.split())[:80].strip() or NO_NAME
    return Person(subject, name)


def _access(body: Mapping[str, Any], refresh: str | None) -> IdAccess | None:
    """ID's access token from the token endpoint's answer, with when it runs out."""
    token = body.get("access_token")
    if not isinstance(token, str):
        return None
    renewed = body.get("refresh_token")
    lifetime = body.get("expires_in")
    seconds = float(lifetime) if isinstance(lifetime, int | float) else 60.0
    return IdAccess(
        token=token,
        refresh=renewed if isinstance(renewed, str) else refresh,
        until=time.time() + seconds,
    )


@dataclass(frozen=True)
class Started:
    key: str
    """Goes to the browser as a cookie, so only this browser can finish the login."""
    address: str
    """ID's login page."""


@dataclass(frozen=True)
class Finished:
    person: Person
    id_token: str
    next_path: str
    pi_attempt: str | None = None
    """For a meet's Pi (hub/pi_login.py): a ticket for the Pi instead of a session here."""
    access: IdAccess | None = None
    """ID's access token for the client hub, for TrainMeet CAD (CAD-11)."""


class IdLogin:
    def __init__(
        self, login: LocalLogin, settings: IdSettings, *, http: httpx.Client | None = None
    ) -> None:
        self.login = login
        self.settings = settings
        self.http = http if http is not None else httpx.Client(timeout=10.0)
        self._keys: dict[str, jwt.PyJWK] = {}
        self._keys_read: float | None = None  # never yet: monotonic time starts at boot
        self._lock = threading.Lock()

    # --- To ID ------------------------------------------------------------------------------

    def start(
        self, next_path: str, language: str | None = None, pi_attempt: str | None = None
    ) -> Started:
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(48)
        key = self.login.begin_id_login(state, nonce, verifier, safe_next(next_path), pi_attempt)
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

    # --- Back from ID -----------------------------------------------------------------------

    def finish(
        self, key: str | None, state: str | None, code: str | None, error: str | None
    ) -> Finished:
        attempt = self.login.take_id_login(key)
        if attempt is None:
            raise LoginFailed(
                "Inloggningen hittades inte i den här webbläsaren eller är för gammal."
            )
        next_path = attempt.next_path
        if error:
            raise LoginFailed(f"ID svarade {error[:40]!r}.", next_path)
        if not state or not secrets.compare_digest(state, attempt.state):
            raise LoginFailed("Fel state tillbaka från ID.", next_path)
        if not code:
            raise LoginFailed("Ingen kod tillbaka från ID.", next_path)
        id_token, access = self._exchange(code, attempt.verifier, next_path)
        claims = self._check(id_token, attempt.nonce, next_path)
        try:
            person = person_from(claims)
        except LoginFailed as failed:
            raise LoginFailed(str(failed), next_path) from failed
        return Finished(
            person=person,
            id_token=id_token,
            next_path=next_path,
            pi_attempt=attempt.pi_attempt,
            access=access,
        )

    def refreshed(self, refresh: str) -> IdAccess | None:
        """A new access token with the refresh token, when the old has run out; None when ID
        says no or does not answer. Why goes to the log, never a token."""
        try:
            answer = self.http.post(
                f"{self.settings.internal}/protocol/openid-connect/token",
                data={"grant_type": "refresh_token", "refresh_token": refresh},
                auth=(self.settings.client, self.settings.secret),
            )
        except httpx.HTTPError as error:
            LOGGER.info("ID svarar inte på förnyelsen: %s", type(error).__name__)
            return None
        if answer.status_code != 200:
            LOGGER.info("ID förnyade inte inloggningen: %s", answer.status_code)
            return None
        return _access(answer.json(), refresh)

    def _exchange(self, code: str, verifier: str, next_path: str) -> tuple[str, IdAccess | None]:
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
        body = answer.json()
        id_token = body.get("id_token")
        if not isinstance(id_token, str):
            raise LoginFailed("ID gav ingen ID-token.", next_path)
        return id_token, _access(body, None)

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
                            continue  # a key type the hub does not use
                self._keys = keys
                self._keys_read = time.monotonic()
            return self._keys[kid]

    # --- An app's token (TKL18, SYNK-30) ----------------------------------------------------

    def app_subject(self, authorization: str | None, apps: frozenset[str]) -> str | None:
        """The person an app's access token from ID belongs to: signed by ID, not run out, and
        issued to one of the apps (azp). None for anything else; never why in the answer."""
        scheme, _, token = (authorization or "").partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token or len(token) > 8000:
            return None
        try:
            header = jwt.get_unverified_header(token)
            key = self._key(str(header.get("kid", "")))
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=[key.algorithm_name],
                issuer=self.settings.issuer,
                leeway=30,
                options={"require": ["exp", "iat", "iss", "sub"], "verify_aud": False},
            )
            subject = str(UUID(str(claims["sub"])))
        except (jwt.PyJWTError, httpx.HTTPError, LookupError, ValueError) as error:
            LOGGER.info("En apps token godtas inte: %s", type(error).__name__)
            return None
        return subject if claims.get("azp") in apps else None

    # --- Logging out ------------------------------------------------------------------------

    def logout_address(self, id_token: str) -> str:
        """Where the browser goes so that ID logs out too, and then comes back (KONTO-01)."""
        query = {
            "id_token_hint": id_token,
            "client_id": self.settings.client,
            "post_logout_redirect_uri": self.settings.public_url + "/",
        }
        return f"{self.settings.issuer}/protocol/openid-connect/logout?{urlencode(query)}"
