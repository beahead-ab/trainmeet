"""What TrainMeet ID says about the person, asked at every call (#67, KONTO-34, ID8).

CAD asks ID's API with a token of its own, from Keycloak's client credentials for the client
"cad", kept until shortly before it runs out. The answer is never kept: a changed club or role
applies at once. If ID does not answer, CAD says so (503); the person's own modules work as
before, since they need no answer from ID.

    clubs(person)          the person's clubs and whether they are its administrator (#67)
    module_roles(p, m)     the roles ID gives the person on the module: editor = redigera
    switcher(person)       the app switcher's apps (ID11)
    tokens(person)         the tokens left on the person's own account (TOKEN-01)
"""

from __future__ import annotations

import logging
import threading
import time
from uuid import UUID

import httpx

from cad.errors import unavailable
from cad.settings import IdSettings
from contracts.cad import ClubChoice
from contracts.id import ResourceKind

LOGGER = logging.getLogger("cad.id")


class IdRoles:
    def __init__(self, settings: IdSettings, http: httpx.Client) -> None:
        assert settings.api is not None
        self.settings = settings
        self.api = settings.api
        self.http = http
        self._token: str | None = None
        self._until = 0.0
        self._lock = threading.Lock()

    def _bearer(self) -> str:
        with self._lock:
            if self._token is None or time.monotonic() > self._until:
                try:
                    answer = self.http.post(
                        f"{self.settings.internal}/protocol/openid-connect/token",
                        data={"grant_type": "client_credentials"},
                        auth=(self.settings.client, self.settings.secret),
                    )
                except httpx.HTTPError as error:
                    LOGGER.warning("ID:s token: %s", type(error).__name__)
                    raise unavailable() from error
                if answer.status_code != 200:
                    LOGGER.warning("ID:s token svarade %s.", answer.status_code)
                    raise unavailable()
                body = answer.json()
                self._token = str(body["access_token"])
                self._until = time.monotonic() + max(int(body.get("expires_in", 60)) - 30, 5)
            return self._token

    def _get(self, path: str, params: dict[str, str]) -> object:
        """ID's answer; a refused token is made anew once. 503 when ID does not answer."""
        for attempt in (1, 2):
            try:
                answer = self.http.get(
                    f"{self.api}/api/id/1/apps/{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {self._bearer()}"},
                )
            except httpx.HTTPError as error:
                LOGGER.warning("ID:s API: %s", type(error).__name__)
                raise unavailable() from error
            if answer.status_code == 401 and attempt == 1:
                with self._lock:
                    self._token = None
                continue
            if answer.status_code != 200:
                LOGGER.warning("ID:s API svarade %s.", answer.status_code)
                raise unavailable()
            result: object = answer.json()
            return result
        raise unavailable()

    def clubs(self, person: UUID) -> list[ClubChoice]:
        body = self._get("clubs", {"person": str(person)})
        found: list[ClubChoice] = []
        for item in body if isinstance(body, list) else []:
            try:
                found.append(
                    ClubChoice(
                        id=UUID(str(item["id"])),
                        name=str(item["name"]),
                        admin=item.get("role") == "admin",
                    )
                )
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
        return found

    def module_roles(self, person: UUID, module: UUID) -> set[str]:
        resource = f"{ResourceKind.MODULE.value}:{module}"
        body = self._get("access", {"person": str(person), "resource": resource})
        roles = body.get("roles", []) if isinstance(body, dict) else []
        return {str(role) for role in roles}

    def switcher(self, person: UUID) -> list[str]:
        body = self._get("switcher", {"person": str(person)})
        apps = body.get("apps", []) if isinstance(body, dict) else []
        return [str(app) for app in apps]

    def tokens(self, person: UUID) -> int | None:
        body = self._get("tokens", {"person": str(person), "owner": f"person:{person}"})
        available = body.get("available") if isinstance(body, dict) else None
        return available if isinstance(available, int) else None
