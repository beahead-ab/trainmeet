"""Removing the account, and the person's data as a file first (KONTO-31, ID7, ID13, CAT-193).

ID's API does it in three places, each step safe to repeat: Catalog removes the person's fleet
and the fleets of the clubs that go with the account; Keycloak removes the account; and ID's own
database removes the person, those clubs, their meets and every role on them. If Catalog or
Keycloak does not answer, nothing more is done, and the person can try again.

ID's API talks to Keycloak and Catalog with a token of its own, from client credentials for the
client "id". Its service account has one role in Keycloak: manage-users (realm update 5).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from uuid import UUID

import httpx

from contracts.catalog import CatalogExport
from contracts.id import Account, AccountExport, ProblemCode, RemovalPlan
from id.roles import Asker, Refused, Roles
from id.settings import Settings

LOGGER = logging.getLogger("id.accounts")


def unavailable(what: str) -> Refused:
    return Refused(503, ProblemCode.UNAVAILABLE, f"{what} svarar inte just nu. Försök igen.")


class Accounts:
    def __init__(self, settings: Settings, http: httpx.Client, roles: Roles) -> None:
        self.settings = settings
        self.http = http
        self.roles = roles
        self.admin = settings.internal.replace("/realms/", "/admin/realms/", 1)
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    def _bearer(self) -> dict[str, str]:
        with self._lock:
            if self._token is None or self._token[1] < time.monotonic():
                try:
                    answer = self.http.post(
                        f"{self.settings.internal}/protocol/openid-connect/token",
                        data={"grant_type": "client_credentials"},
                        auth=(self.settings.client, self.settings.secret),
                    )
                    answer.raise_for_status()
                    body = answer.json()
                    lifetime = float(body.get("expires_in", 60))
                    self._token = (str(body["access_token"]), time.monotonic() + lifetime - 30)
                except (httpx.HTTPError, KeyError, ValueError) as error:
                    LOGGER.warning("ID:s egen token: %s", type(error).__name__)
                    raise unavailable("TrainMeet ID") from error
            return {"Authorization": f"Bearer {self._token[0]}"}

    def plan(self, asker: Asker) -> RemovalPlan:
        return self.roles.removal_plan(asker.id)

    def export(self, asker: Asker, account: Account) -> AccountExport:
        clubs, grants, invitations, meets = self.roles.own_data(asker)
        catalog: CatalogExport | None = None
        if self.settings.catalog:
            try:
                answer = self.http.get(
                    f"{self.settings.catalog}/api/catalog/1/id/export",
                    params={"person": str(asker.id)},
                    headers=self._bearer(),
                )
                answer.raise_for_status()
                catalog = CatalogExport.model_validate(answer.json())
            except (httpx.HTTPError, ValueError) as error:
                LOGGER.warning("Catalogs del av filen: %s", type(error).__name__)
                raise unavailable("Catalog") from error
        return AccountExport(
            made_at=datetime.now(UTC),
            account=account,
            clubs=clubs,
            roles=grants,
            invitations=invitations,
            meets=meets,
            catalog=catalog,
        )

    def remove(self, asker: Asker) -> None:
        plan = self.roles.removal_plan(asker.id)
        if plan.clubs_blocking:
            names = ", ".join(club.name for club in plan.clubs_blocking)
            raise Refused(
                409,
                ProblemCode.CONFLICT,
                f"Ge administratörsrollen till någon annan först i: {names}.",
            )
        clubs = [club.id for club in plan.clubs_removed]
        owners: list[UUID] = [asker.id, *clubs]
        if self.settings.catalog:
            try:
                answer = self.http.post(
                    f"{self.settings.catalog}/api/catalog/1/id/removed",
                    json={"owners": [str(owner) for owner in owners]},
                    headers=self._bearer(),
                )
                answer.raise_for_status()
            except httpx.HTTPError as error:
                LOGGER.warning("Catalog tog inte bort: %s", type(error).__name__)
                raise unavailable("Catalog") from error
        try:
            gone = self.http.delete(f"{self.admin}/users/{asker.id}", headers=self._bearer())
            if gone.status_code not in (204, 404):
                gone.raise_for_status()
        except httpx.HTTPError as error:
            LOGGER.warning("Keycloak tog inte bort kontot: %s", type(error).__name__)
            raise unavailable("TrainMeet ID") from error
        self.roles.remove_person(asker.id, asker.email, clubs)
        LOGGER.info("Ett konto är borttaget, med %d klubbar.", len(clubs))
