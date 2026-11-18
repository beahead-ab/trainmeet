"""What TrainMeet ID says about the roles at a meet, asked at every call (#78, ID10, KONTO-34).

The Hub asks ID's API with a token of its own, from Keycloak's client credentials for the client
"hub", kept until shortly before it runs out, as Catalog does (catalog/id_roles.py). The answer is
never kept: a role taken back in ID ends at once (C35). If ID does not answer, someone logged in
with ID may do nothing that needs a role (503), while the hub's own PIN works as before.

The hub's meet is linked to ID's meet (Meet.id_meet, ID10). The roles count as:

- Administratör, the club's admin: everything at the club's meets (KONTO-36, PLAN-19).
- Arrangör: plans the meet in Planering and publishes its versions (PLAN-19).
- Trafikledare: runs the meet in Drift (ID3).
"""

from __future__ import annotations

import logging
import threading
import time
from uuid import UUID

import httpx
from fastapi import HTTPException

from contracts import id as id_contract
from hub.id_login import IdSettings

LOGGER = logging.getLogger("hub.id")

ADMIN = "admin"
ORGANIZER = "organizer"
DISPATCHER = "dispatcher"

PLANS = frozenset({ADMIN, ORGANIZER})
"""Who plans a meet and publishes its versions (PLAN-19)."""
RUNS = frozenset({ADMIN, DISPATCHER})
"""Who runs a meet in Drift (ID3)."""


def unavailable() -> HTTPException:
    return HTTPException(503, "TrainMeet ID svarar inte just nu. Försök igen.")


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
                    self._token = None  # a new token, once
                continue
            if answer.status_code != 200:
                LOGGER.warning("ID:s API svarade %s.", answer.status_code)
                raise unavailable()
            result: object = answer.json()
            return result
        raise unavailable()

    def at_meet(self, person: str, id_meet: UUID) -> set[str]:
        """The person's roles at ID's meet, as ID says now. The club's admin has admin."""
        body = self._get("access", {"person": person, "resource": f"meet:{id_meet}"})
        roles = body.get("roles", []) if isinstance(body, dict) else []
        return {str(role) for role in roles}

    def meets(self, person: str) -> list[id_contract.Meet]:
        """The meets of the person's clubs, with the person's roles at each (ID10)."""
        body = self._get("meets", {"person": person})
        found: list[id_contract.Meet] = []
        for item in body if isinstance(body, list) else []:
            try:
                found.append(id_contract.Meet.model_validate(item))
            except ValueError:
                continue
        return found


def roles_of(meet: id_contract.Meet) -> set[str]:
    """The roles an entry from meets() gives, the club's admin as admin."""
    held = {role.value for role in meet.roles}
    if meet.club_admin:
        held.add(ADMIN)
    return held
