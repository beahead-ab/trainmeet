"""TrainMeet ID i TKL (TKL18, #78) och stationspaketen i molnet (SYNK-06, SYNK-18, SYNK-30).

TKL logs in with ID as the public client "tkl": OpenID Connect's code flow with PKCE and no
secret, since TKL also runs on the station's own computer, which cannot keep one. TKL keeps the
person's id, name and ID's tokens with the station, never the address, and never shows a token.
With them TKL saves the station package in the cloud hub (Spara i molnet): the latest version of
the outside as a new version on top of the latest one the cloud has, linear (H71). A save on top
of an older version is refused, and the owner chooses whether to save on top.

Settings, from the environment; without TKL_ID_ISSUER TKL has no login with ID:

TKL_ID_ISSUER     ID's realm, for example https://id.trainmeet.app/realms/trainmeet.
TKL_ID_INTERNAL   Where TKL itself reaches the realm, if not at the issuer's address.
TKL_ID_CLIENT     TKL's client in ID. Default "tkl".
TKL_PUBLIC_URL    TKL's own address, where ID sends the browser back. Default
                  http://localhost:8090, the station's own computer.
TKL_MOLNHUBB      The cloud hub where the station packages are kept. In the cloud, the first of
                  TKL_HUBBAR if not set.
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
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlencode
from uuid import UUID

import httpx
import jwt

LOGGER = logging.getLogger("tkl.id")

COOKIE: Final = "tkl_id_login"
COOKIE_PATH: Final = "/api/tkl/1/id"
LIFETIME_SECONDS: Final = 600
_KEYS_AGAIN_AFTER: Final = 60.0


@dataclass(frozen=True)
class TklIdSettings:
    issuer: str
    internal: str
    public_url: str
    client: str = "tkl"
    cloud: str | None = None

    @property
    def redirect_uri(self) -> str:
        return self.public_url + "/api/tkl/1/id/callback"


def settings_from(
    env: Mapping[str, str] | None = None, hubs: list[str] | None = None
) -> TklIdSettings | None:
    source = os.environ if env is None else env
    issuer = source.get("TKL_ID_ISSUER", "").strip().rstrip("/")
    if not issuer:
        return None
    cloud = source.get("TKL_MOLNHUBB", "").strip().rstrip("/") or (hubs[0] if hubs else None)
    return TklIdSettings(
        issuer=issuer,
        internal=source.get("TKL_ID_INTERNAL", "").strip().rstrip("/") or issuer,
        public_url=source.get("TKL_PUBLIC_URL", "").strip().rstrip("/") or "http://localhost:8090",
        client=source.get("TKL_ID_CLIENT", "").strip() or "tkl",
        cloud=cloud,
    )


class IdFailed(Exception):
    """The login with ID did not go through. The message is for the log."""


@dataclass(frozen=True)
class Tokens:
    person: str
    name: str
    access: str
    refresh: str | None
    access_until: float


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class TklIdLogin:
    def __init__(self, settings: TklIdSettings, http: httpx.Client) -> None:
        self.settings = settings
        self.http = http
        self._keys: dict[str, jwt.PyJWK] = {}
        self._keys_read: float | None = None
        self._lock = threading.Lock()

    def address(self, state: str, nonce: str, verifier: str) -> str:
        query = {
            "client_id": self.settings.client,
            "redirect_uri": self.settings.redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
            "ui_locales": "sv",
        }
        return f"{self.settings.issuer}/protocol/openid-connect/auth?{urlencode(query)}"

    def _token(self, form: dict[str, str]) -> dict[str, Any]:
        try:
            answer = self.http.post(
                f"{self.settings.internal}/protocol/openid-connect/token",
                data={**form, "client_id": self.settings.client},
            )
        except httpx.HTTPError as error:
            raise IdFailed(f"ID svarar inte: {type(error).__name__}.") from error
        if answer.status_code != 200:
            raise IdFailed(f"ID:s token svarade {answer.status_code}.")
        found: dict[str, Any] = answer.json()
        return found

    def finish(self, code: str, verifier: str, nonce: str) -> Tokens:
        """Back from ID: the code for tokens, and the ID token checked."""
        body = self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.redirect_uri,
                "code_verifier": verifier,
            }
        )
        id_token, access = body.get("id_token"), body.get("access_token")
        if not isinstance(id_token, str) or not isinstance(access, str):
            raise IdFailed("ID gav inga token.")
        try:
            header = jwt.get_unverified_header(id_token)
            key = self._key(str(header.get("kid", "")))
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key=key,
                algorithms=[key.algorithm_name],
                audience=self.settings.client,
                issuer=self.settings.issuer,
                leeway=30,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            person = str(UUID(str(claims["sub"])))
        except (jwt.PyJWTError, httpx.HTTPError, LookupError, ValueError) as error:
            raise IdFailed(f"ID:s token godtas inte: {type(error).__name__}.") from error
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise IdFailed("Fel nonce i ID:s token.")
        if claims.get("email_verified") is not True:
            raise IdFailed("E-posten är inte verifierad i ID.")
        name = " ".join(str(claims.get("name") or "").split())[:80] or "Utan namn"
        return Tokens(
            person,
            name,
            access,
            body.get("refresh_token") if isinstance(body.get("refresh_token"), str) else None,
            time.time() + int(body.get("expires_in", 60)),
        )

    def refreshed(self, refresh: str) -> tuple[str, str | None, float]:
        """A new access token with the refresh token, when the old has run out."""
        body = self._token({"grant_type": "refresh_token", "refresh_token": refresh})
        access = body.get("access_token")
        if not isinstance(access, str):
            raise IdFailed("ID gav ingen ny token.")
        new_refresh = body.get("refresh_token")
        return (
            access,
            new_refresh if isinstance(new_refresh, str) else refresh,
            time.time() + int(body.get("expires_in", 60)),
        )

    def _key(self, kid: str) -> jwt.PyJWK:
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
                            continue
                self._keys = keys
                self._keys_read = time.monotonic()
            return self._keys[kid]
