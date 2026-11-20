"""The photos' addresses (contracts/cad.py, part c1).

An upload is a form, multipart/form-data, as a browser sends it: the part data is the JSON (a
PhotoStart, or a PhotoCloseup), and the parts images are the photos. The form is read here, in
memory and never more than MAX_FORM, rather than with a library for forms, which would put the
photos in temporary files on disk before their metadata is gone (bildkedjan step 2), as
Catalog's reading does.

No `from __future__ import annotations` here: FastAPI reads the local dependencies from the
annotations, which must then be real objects.
"""

import re
from collections.abc import Callable
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel, ValidationError

from cad.errors import Refused
from cad.library import Who
from cad.photos import Photos
from cad.store import DiskStore, kind_of
from contracts.cad import (
    MAX_PHOTOS,
    Module,
    PhotoAnswers,
    PhotoCloseup,
    PhotoConsent,
    PhotoJob,
    PhotoRead,
    PhotoSettings,
    PhotoStart,
    ProblemCode,
    StorageUse,
)

API = "/api/cad/1"
MB: Final = 1024 * 1024
MAX_FORM: Final = MAX_PHOTOS * 30 * MB + 64 * 1024
MAX_DATA: Final = 8192
_BOUNDARY: Final = re.compile(r'boundary=(?:"([^"\r\n]{1,70})"|([^\s;",]{1,70}))', re.IGNORECASE)
_NAME: Final = re.compile(r'(?:^|;)\s*name="([^"\r\n]*)"', re.IGNORECASE)


def bad_form(why: str = "Formuläret kunde inte läsas.") -> Refused:
    return Refused(422, ProblemCode.INVALID, why)


def too_large() -> Refused:
    return Refused(413, ProblemCode.BAD_PHOTO, "Fotona är för stora. Högst 30 MB per foto.")


async def _body(request: Request) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_FORM:
        raise too_large()
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_FORM:
            raise too_large()
    return bytes(data)


def parts(content_type: str, body: bytes) -> list[tuple[str, bytes]]:
    """The form's parts by name, as multipart/form-data has them (RFC 7578); anything else is
    refused rather than read as well as it goes."""
    kind = content_type.split(";", 1)[0].strip().lower()
    boundary = _BOUNDARY.search(content_type)
    if kind != "multipart/form-data" or boundary is None:
        raise bad_form()
    delimiter = b"\r\n--" + (boundary[1] or boundary[2]).encode("latin-1")
    chunks = (b"\r\n" + body).split(delimiter)
    if len(chunks) < 3 or chunks[0] or not chunks[-1].startswith(b"--"):
        raise bad_form()
    found: list[tuple[str, bytes]] = []
    for chunk in chunks[1:-1]:
        head, separator, data = chunk.lstrip(b" \t").partition(b"\r\n\r\n")
        if not separator or not head.startswith(b"\r\n"):
            raise bad_form()
        dispositions = [
            value
            for key, _, value in (
                line.partition(":") for line in head[2:].decode("latin-1").split("\r\n")
            )
            if key.strip().lower() == "content-disposition"
        ]
        name = _NAME.search(dispositions[0]) if len(dispositions) == 1 else None
        if name is None:
            raise bad_form()
        found.append((name[1], data))
    return found


def _form[T: BaseModel](
    found: list[tuple[str, bytes]], model: type[T], most: int
) -> tuple[T, list[bytes]]:
    data = [value for name, value in found if name == "data"]
    photos = [value for name, value in found if name == "images"]
    if len(data) != 1 or len(data) + len(photos) != len(found) or len(data[0]) > MAX_DATA:
        raise bad_form()
    if not 1 <= len(photos) <= most:
        raise bad_form(f"Välj 1–{most} foton." if most > 1 else "Välj ett foto.")
    try:
        ask = model.model_validate_json(data[0])
    except ValidationError as error:
        raise bad_form() from error
    return ask, photos


def router(photos: Photos, who: Callable[..., Who], disk: DiskStore | None) -> APIRouter:
    Asker = Annotated[Who, Depends(who)]
    routes = APIRouter(prefix=API)

    @routes.get("/photos/consent")
    def consent(asker: Asker, module: UUID | None = None) -> PhotoConsent:
        return photos.consent(asker, module)

    @routes.post("/photos", status_code=201)
    async def upload(request: Request, asker: Asker) -> PhotoJob:
        body = await _body(request)
        start, images = _form(
            parts(request.headers.get("content-type", ""), body), PhotoStart, MAX_PHOTOS
        )
        return await run_in_threadpool(photos.start, asker, start, images)

    @routes.get("/photos/{job}")
    def job(job: UUID, asker: Asker) -> PhotoJob:
        return photos.job(asker, job)

    @routes.post("/photos/{job}/read")
    def read(job: UUID, body: PhotoRead, asker: Asker) -> PhotoJob:
        return photos.read(asker, job, body)

    @routes.post("/photos/{job}/answers")
    def answers(job: UUID, body: PhotoAnswers, asker: Asker) -> PhotoJob:
        return photos.answer(asker, job, body)

    @routes.post("/photos/{job}/questions/{key}/closeup")
    async def closeup(job: UUID, key: str, request: Request, asker: Asker) -> PhotoJob:
        body = await _body(request)
        ask, images = _form(parts(request.headers.get("content-type", ""), body), PhotoCloseup, 1)
        return await run_in_threadpool(photos.closeup, asker, job, key, images[0], ask.consent)

    @routes.post("/photos/{job}/recompute")
    def recompute(job: UUID, asker: Asker) -> PhotoJob:
        return photos.recompute(asker, job)

    @routes.put("/modules/{module}/photo")
    def settings(module: UUID, body: PhotoSettings, asker: Asker) -> Module:
        return photos.settings(asker, module, body)

    @routes.get("/storage")
    def storage(asker: Asker) -> StorageUse:
        return photos.storage(asker)

    @routes.get("/photos/file/{key:path}", response_model=None)
    def file(
        key: str, expires: Annotated[str, Query()] = "", sig: Annotated[str, Query()] = ""
    ) -> Response:
        """A photo on CAD's own disk, by its signed address; only without a bucket."""
        if disk is None or not disk.check(key, expires, sig):
            return PlainTextResponse("Finns inte.", status_code=404)
        path = disk.path(key)
        if path is None or not path.is_file():
            return PlainTextResponse("Finns inte.", status_code=404)
        return FileResponse(
            path,
            media_type=kind_of(key),
            headers={"Cache-Control": "private, max-age=3600"},
        )

    return routes
