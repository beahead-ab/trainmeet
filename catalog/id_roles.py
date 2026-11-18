"""What TrainMeet ID says about the roles, asked at every call (#49, KONTO-34, CAT-48).

Catalog asks ID's API with a token of its own, from Keycloak's client credentials, kept until
shortly before it runs out. The answer is never kept: a changed sharing applies at once. If ID
does not answer, nothing shared is shown (503), while the owner's own fleet works as before.
The same token reserves and draws the tokens for the storage over the free level (CAT-132,
catalog/storage.py).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from uuid import UUID

import httpx

from catalog.fleet import Refused
from catalog.settings import IdSettings
from contracts.catalog import ProblemCode

LOGGER = logging.getLogger("catalog.id")


def unavailable() -> Refused:
    return Refused(503, ProblemCode.UNAVAILABLE, "TrainMeet ID svarar inte just nu. Försök igen.")


@dataclass(frozen=True)
class SharedFleet:
    owner: UUID
    title: str
    role: str
    club: bool = False
    """The owner is a club: its pictures count against the club's storage (TOKEN-29)."""


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

    def call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> httpx.Response:
        """ID's answer to the app's call, whatever it says; a refused token is made anew once.
        Refused with 503 when ID does not answer."""
        for attempt in (1, 2):
            try:
                answer = self.http.request(
                    method,
                    f"{self.api}/api/id/1/apps/{path}",
                    params=params,
                    json=body,
                    headers={"Authorization": f"Bearer {self._bearer()}"},
                )
            except httpx.HTTPError as error:
                LOGGER.warning("ID:s API: %s", type(error).__name__)
                raise unavailable() from error
            if answer.status_code == 401 and attempt == 1:
                with self._lock:
                    self._token = None  # a new token, once
                continue
            return answer
        raise unavailable()

    def _get(self, path: str, params: dict[str, str]) -> object:
        answer = self.call("GET", path, params=params)
        if answer.status_code != 200:
            LOGGER.warning("ID:s API svarade %s.", answer.status_code)
            raise unavailable()
        result: object = answer.json()
        return result

    def fleet_roles(self, person: UUID, owner: UUID) -> set[str]:
        """The person's roles for the owner's fleet, as ID says now."""
        body = self._get("access", {"person": str(person), "resource": f"fleet:{owner}"})
        roles = body.get("roles", []) if isinstance(body, dict) else []
        return {str(role) for role in roles}

    def switcher(self, person: UUID) -> list[str]:
        """The apps the person has something in, for the app switcher (ID11)."""
        body = self._get("switcher", {"person": str(person)})
        apps = body.get("apps", []) if isinstance(body, dict) else []
        return [str(app) for app in apps]

    def tokens(self, person: UUID) -> int | None:
        """Saldot i kontomenyn (TOKEN-01): the tokens left on the person's own account."""
        body = self._get("tokens", {"person": str(person), "owner": f"person:{person}"})
        available = body.get("available") if isinstance(body, dict) else None
        return available if isinstance(available, int) else None

    def shared_fleets(self, person: UUID) -> list[SharedFleet]:
        body = self._get("fleets", {"person": str(person)})
        found: list[SharedFleet] = []
        for item in body if isinstance(body, list) else []:
            try:
                found.append(
                    SharedFleet(
                        UUID(item["owner"]["id"]),
                        str(item["title"]),
                        str(item["role"]),
                        club=item.get("club") is True,
                    )
                )
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
        return found
