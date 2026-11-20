"""Ladda upp ritning (#89 del c4, CAD6, STUDIO-01, STUDIO-03): Studio's drawing read by TrainMeet
CAD's image chain, asked by TKL's server on the person's behalf with the person's own access
token from TrainMeet ID (TKL18), as TKL asks the cloud hub's Synk (tkl/moln.py).

TKL speaks only the contract with CAD (contracts/cad.py, Ladda upp ritning). The token goes in the
Authorization header and nowhere else, and is never written to a log; nor is the drawing. CAD's
answer is said to the owner in Swedish, as CAD said it.

Från CAD (#89 del d2, STUDIO-03, CAD-15) asks the same CAD the same way: the person's assemblies
and approved modules, the track graph of the one the owner picks, and, when the owner has taken
it into use, which station uses it, for CAD's Används i. CAD never makes a station. Part d4 asks
for the modules' measuring images too, for Foto (CAD-13, CAD-33): the list, and each image as
JPEG, never larger than the limit TKL gives.

TKL_CAD is CAD's address. Without it, or without a login with ID, the ways in are shut, and Rita
still works: a local TKL without internet can only Rita (CAD6).
"""

from __future__ import annotations

import logging
from typing import Final
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError

from contracts.cad import (
    STUDIO_IMAGE_TYPE,
    DrawingAnswers,
    DrawingJob,
    DrawingReadAsk,
    DrawingStart,
    StationUseAsk,
    StudioGraph,
    StudioImages,
    StudioSource,
    StudioSourceKind,
    StudioSources,
)

LOGGER = logging.getLogger("tkl.cad")
DRAWINGS: Final = "/api/cad/1/drawings"
STUDIO: Final = "/api/cad/1/studio"
TIMEOUT: Final = 60.0
"""An upload of up to 30 MB to CAD, and its intake."""
NO_ANSWER: Final = "TrainMeet CAD svarar inte. Försök igen om en stund."
LOG_IN_AGAIN: Final = "TrainMeet CAD godtog inte inloggningen. Logga in med TrainMeet ID igen."
UNEXPECTED: Final = "TrainMeet CAD svarade inte som väntat."


class CadError(Exception):
    """CAD said no, or could not be reached. The detail is for the owner."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _said(answer: httpx.Response) -> str | None:
    try:
        found = answer.json().get("message")
    except (ValueError, AttributeError):
        return None
    return found if isinstance(found, str) else None


def _read[M: BaseModel](model: type[M], answer: httpx.Response) -> M:
    try:
        return model.model_validate_json(answer.content)
    except ValidationError as error:
        raise CadError(502, UNEXPECTED) from error


class Cad:
    """The person's drawings, assemblies and modules in TrainMeet CAD."""

    def __init__(self, http: httpx.Client, address: str, access: str) -> None:
        self.http = http
        self.address = address.rstrip("/")
        self.headers = {"Authorization": f"Bearer {access}"}

    def _call(
        self,
        method: str,
        path: str,
        *,
        json_body: BaseModel | None = None,
        files: list[tuple[str, tuple[str | None, bytes, str]]] | None = None,
    ) -> httpx.Response:
        headers = dict(self.headers)
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        try:
            answer = self.http.request(
                method,
                self.address + path,
                headers=headers,
                content=json_body.model_dump_json() if json_body is not None else None,
                files=files,
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as error:
            LOGGER.warning("CAD svarar inte: %s", type(error).__name__)
            raise CadError(503, NO_ANSWER) from error
        if answer.status_code == 401:
            raise CadError(401, LOG_IN_AGAIN)
        if answer.status_code >= 400:
            LOGGER.warning("CAD svarade %s.", answer.status_code)
            known = (402, 404, 409, 413, 415, 422, 429)
            status = answer.status_code if answer.status_code in known else 502
            raise CadError(status, _said(answer) or "TrainMeet CAD sa nej.")
        return answer

    def _job(self, answer: httpx.Response) -> DrawingJob:
        return _read(DrawingJob, answer)

    def upload(self, name: str, data: bytes, content_type: str) -> DrawingJob:
        start = DrawingStart(name=name[:120] or None)
        files = [
            ("data", (None, start.model_dump_json().encode(), "application/json")),
            ("file", (name or "ritning", data, content_type or "application/octet-stream")),
        ]
        return self._job(self._call("POST", DRAWINGS, files=files))

    def job(self, job: UUID) -> DrawingJob:
        return self._job(self._call("GET", f"{DRAWINGS}/{job}"))

    def read(self, job: UUID, ask: DrawingReadAsk) -> DrawingJob:
        return self._job(self._call("POST", f"{DRAWINGS}/{job}/read", json_body=ask))

    def answers(self, job: UUID, answers: DrawingAnswers) -> DrawingJob:
        return self._job(self._call("POST", f"{DRAWINGS}/{job}/answers", json_body=answers))

    def underlay(self, job: UUID) -> tuple[bytes, str]:
        answer = self._call("GET", f"{DRAWINGS}/{job}/underlay")
        kind = answer.headers.get("content-type", "")
        if kind not in ("image/png", "image/jpeg"):
            raise CadError(502, UNEXPECTED)
        return answer.content, kind

    # --- Från CAD (#89 del d2) ---------------------------------------------------------------

    def sources(self) -> StudioSources:
        """The person's assemblies and approved modules."""
        return _read(StudioSources, self._call("GET", STUDIO))

    def graph(self, kind: StudioSourceKind, source: UUID) -> StudioGraph:
        """The track graph of one, with ids CAD never changes (CAD-10, CAD-20)."""
        return _read(StudioGraph, self._call("GET", f"{STUDIO}/{kind.value}/{source}"))

    def station_use(self, kind: StudioSourceKind, source: UUID, ask: StationUseAsk) -> StudioSource:
        """The station took it into use: CAD's Används i (CAD-15)."""
        answer = self._call("PUT", f"{STUDIO}/{kind.value}/{source}/station", json_body=ask)
        return _read(StudioSource, answer)

    # --- Mätbilden i Foto (#89 del d4) -------------------------------------------------------

    def images(self, kind: StudioSourceKind, source: UUID) -> StudioImages:
        """Each module's measuring image where the source puts it, and those without one."""
        return _read(StudioImages, self._call("GET", f"{STUDIO}/{kind.value}/{source}/images"))

    def image(
        self, kind: StudioSourceKind, source: UUID, module: UUID, version: int, limit: int
    ) -> bytes:
        """One module's measuring image as JPEG; CadError 413 when it is larger than limit."""
        answer = self._call("GET", f"{STUDIO}/{kind.value}/{source}/images/{module}/{version}")
        if answer.headers.get("content-type", "").split(";")[0].strip() != STUDIO_IMAGE_TYPE:
            raise CadError(502, UNEXPECTED)
        if len(answer.content) > limit:
            raise CadError(413, "Mätbilden är för stor.")
        if answer.content[:3] != b"\xff\xd8\xff":
            raise CadError(502, UNEXPECTED)
        return answer.content
