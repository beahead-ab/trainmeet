"""TKL i molnet med TrainMeet ID (TKL5, TKLMOLN-02, TKLMOLN-03, TKLMOLN-06, #88): the station
packages in Hubbens Synk, and the meets the account may join, asked of the cloud hub with the
person's own token from ID (TKL18, SYNK-30).

TKL speaks only the contracts with the hub (contracts/sync.py). The token goes in the
Authorization header and nowhere else, and is never written to a log. Every answer the owner
should see is said in Swedish; the rest goes to the log without the token.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import ValidationError

from contracts.sync import (
    RelayMeet,
    RelayMeets,
    StationList,
    StationPackage,
    StationVersionInfo,
    StationVersions,
)

LOGGER = logging.getLogger("tkl.moln")
STATIONS = "/api/sync/1/stations"
NO_ANSWER = "Molnhubben svarar inte. Försök igen."
LOG_IN_AGAIN = "Molnhubben godtog inte inloggningen. Logga in med TrainMeet ID igen."


class SynkError(Exception):
    """Synk said no, or could not be reached. The detail is for the owner."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Behind(SynkError):
    """A save on top of an older version (H71): Synk has a newer one, the latest."""

    def __init__(self, latest: int, detail: str) -> None:
        super().__init__(409, detail)
        self.latest = latest


def _said(answer: httpx.Response) -> str | None:
    try:
        found = answer.json().get("detail")
    except (ValueError, AttributeError):
        return None
    return found if isinstance(found, str) else None


class Synk:
    """The owner's station packages in the cloud hub, and the meets through its relay."""

    def __init__(self, http: httpx.Client, cloud: str, access: str) -> None:
        self.http = http
        self.cloud = cloud.rstrip("/")
        self.headers = {"Authorization": f"Bearer {access}"}

    def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        content: str | None = None,
    ) -> httpx.Response:
        headers = dict(self.headers)
        if content is not None:
            headers["Content-Type"] = "application/json"
        try:
            answer = self.http.request(
                method, self.cloud + path, params=params, content=content, headers=headers
            )
        except httpx.HTTPError as error:
            raise SynkError(503, NO_ANSWER) from error
        if answer.status_code == 401:
            raise SynkError(401, LOG_IN_AGAIN)
        if answer.status_code >= 400 and not (
            answer.status_code == 409 and "TrainMeet-Latest" in answer.headers
        ):
            LOGGER.warning("Molnhubben svarade %s på %s.", answer.status_code, path)
            status = answer.status_code if answer.status_code in (403, 404, 409) else 502
            raise SynkError(status, _said(answer) or "Molnhubben sa nej.")
        return answer

    def stations(self) -> list[StationVersionInfo]:
        """Dina stationer: the latest version of each station the person owns."""
        answer = self._call("GET", STATIONS)
        try:
            return StationList.model_validate(answer.json()).stations
        except (ValidationError, ValueError) as error:
            raise SynkError(502, "Molnhubben svarade inte som väntat.") from error

    def latest(self, station_id: str) -> tuple[int, StationPackage]:
        """The latest version of one of the person's stations, the outside and the inside."""
        listed = self._call("GET", f"{STATIONS}/{station_id}/versions")
        try:
            versions = StationVersions.model_validate(listed.json()).versions
        except (ValidationError, ValueError) as error:
            raise SynkError(502, "Molnhubben svarade inte som väntat.") from error
        if not versions:
            raise SynkError(404, "Stationen finns inte i molnet.")
        number = versions[-1].version
        body = self._call("GET", f"{STATIONS}/{station_id}/versions/{number}")
        try:
            return number, StationPackage.model_validate_json(body.content)
        except ValidationError as error:
            raise SynkError(502, "Stationspaketet i molnet gick inte att läsa.") from error

    def save(self, package: StationPackage, base: int) -> int:
        """A new version on top of base; Behind when Synk has a newer one (H71)."""
        answer = self._call(
            "POST",
            f"{STATIONS}/{package.station_id}/versions",
            params={"base": base},
            content=package.model_dump_json(),
        )
        latest = answer.headers.get("TrainMeet-Latest", "")
        if answer.status_code == 409 and latest.isdigit():
            raise Behind(int(latest), _said(answer) or "Molnet har en nyare version.")
        if answer.status_code != 201:
            raise SynkError(502, "Molnhubben sparade inte stationspaketet.")
        try:
            return StationVersionInfo.model_validate(answer.json()).version
        except (ValidationError, ValueError) as error:
            raise SynkError(502, "Molnhubben svarade inte som väntat.") from error

    def meets(self) -> list[RelayMeet]:
        """The meets the person may join (#78 del b), each with the way there (TKLMOLN-03)."""
        answer = self._call("GET", "/api/sync/1/relay/meets")
        try:
            return RelayMeets.model_validate(answer.json()).meets
        except (ValidationError, ValueError) as error:
            raise SynkError(502, "Molnhubben svarade inte som väntat.") from error
