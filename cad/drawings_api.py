"""The drawings' addresses (contracts/cad.py, Ladda upp ritning, part c4), under CAD's own prefix.

Studio calls them through TKL's server with the person's access token from TrainMeet ID
(Authorization: Bearer, TKL18); a browser logged in to CAD may call them with its session. The
upload is a form, multipart/form-data, read in memory as the photos' is (cad/photos_api.py): the
part data is a DrawingStart and the part file the drawing.

No `from __future__ import annotations` here: FastAPI reads the local dependencies from the
annotations, which must then be real objects.
"""

from collections.abc import Callable
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import ValidationError

from cad.drawings import Drawings
from cad.errors import Refused
from cad.library import Who
from cad.photos_api import bad_form, parts
from contracts.cad import (
    DrawingAnswers,
    DrawingJob,
    DrawingReadAsk,
    DrawingStart,
    ProblemCode,
)

API = "/api/cad/1"
MB: Final = 1024 * 1024
MAX_FORM: Final = 30 * MB + 64 * 1024
MAX_DATA: Final = 4096


async def _body(request: Request) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_FORM:
        raise _too_large()
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_FORM:
            raise _too_large()
    return bytes(data)


def _too_large() -> Refused:
    return Refused(413, ProblemCode.BAD_DRAWING, "Ritningen är för stor. Högst 30 MB.")


def _form(content_type: str, body: bytes) -> tuple[DrawingStart, bytes]:
    found = parts(content_type, body)
    data = [value for name, value in found if name == "data"]
    files = [value for name, value in found if name == "file"]
    if len(data) > 1 or len(files) != 1 or len(data) + len(files) != len(found):
        raise bad_form("Välj en ritning: en PDF, en SVG eller en bild.")
    if data and len(data[0]) > MAX_DATA:
        raise bad_form()
    try:
        start = DrawingStart.model_validate_json(data[0]) if data else DrawingStart()
    except ValidationError as error:
        raise bad_form() from error
    return start, files[0]


def router(drawings: Drawings, asker: Callable[..., Who]) -> APIRouter:
    Asker = Annotated[Who, Depends(asker)]
    routes = APIRouter(prefix=API)

    @routes.post("/drawings", status_code=201)
    async def upload(request: Request, who: Asker) -> DrawingJob:
        body = await _body(request)
        start, data = _form(request.headers.get("content-type", ""), body)
        return await run_in_threadpool(drawings.start, who, start, data)

    @routes.get("/drawings/{job}")
    def job(job: UUID, who: Asker) -> DrawingJob:
        return drawings.job(who, job)

    @routes.post("/drawings/{job}/read")
    def read(job: UUID, body: DrawingReadAsk, who: Asker) -> DrawingJob:
        return drawings.read(who, job, body)

    @routes.post("/drawings/{job}/answers")
    def answers(job: UUID, body: DrawingAnswers, who: Asker) -> DrawingJob:
        return drawings.answer(who, job, body)

    @routes.get("/drawings/{job}/underlay", response_model=None)
    def underlay(job: UUID, who: Asker) -> Response:
        data, media = drawings.underlay(who, job)
        return Response(data, media_type=media, headers={"Cache-Control": "private, no-store"})

    return routes
