"""Import från AnyRail's addresses (contracts/cad.py, #91), under CAD's own prefix, for the person
logged in to CAD. The upload is a form, multipart/form-data, read in memory as the drawings' is
(cad/drawings_api.py): the part data is an AnyRailStart and the part file the AnyRail file, at
most MAX_FILE (20 MB).

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

from cad.anyrail.reader import MAX_BYTES
from cad.anyrail.service import AnyRailImports
from cad.errors import Refused
from cad.export import disposition
from cad.library import Who
from cad.photos_api import bad_form, parts
from contracts.cad import (
    AnyRailCreate,
    AnyRailCreated,
    AnyRailImport,
    AnyRailSettings,
    AnyRailStart,
    ProblemCode,
)

API = "/api/cad/1"
MAX_FILE: Final = MAX_BYTES
MAX_FORM: Final = MAX_FILE + 64 * 1024
MAX_DATA: Final = 8192


def _too_large() -> Refused:
    return Refused(413, ProblemCode.BAD_DRAWING, "Filen är för stor. Högst 20 MB.")


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


def _form(content_type: str, body: bytes) -> tuple[AnyRailStart, bytes]:
    found = parts(content_type, body)
    data = [value for name, value in found if name == "data"]
    files = [value for name, value in found if name == "file"]
    if len(data) > 1 or len(files) != 1 or len(data) + len(files) != len(found):
        raise bad_form("Välj en AnyRail-fil: AnyRails egen fil (.any) eller exporten som XML.")
    if data and len(data[0]) > MAX_DATA:
        raise bad_form()
    if len(files[0]) > MAX_FILE:
        raise _too_large()
    try:
        start = AnyRailStart.model_validate_json(data[0]) if data else AnyRailStart()
    except ValidationError as error:
        raise bad_form() from error
    return start, files[0]


def router(imports: AnyRailImports, asker: Callable[..., Who]) -> APIRouter:
    Asker = Annotated[Who, Depends(asker)]
    routes = APIRouter(prefix=API + "/anyrail")

    @routes.post("", status_code=201)
    async def upload(request: Request, who: Asker) -> AnyRailImport:
        body = await _body(request)
        start, data = _form(request.headers.get("content-type", ""), body)
        return await run_in_threadpool(imports.upload, who, start.name or "AnyRail", data, start)

    @routes.get("/{ident}")
    def read(ident: UUID, who: Asker) -> AnyRailImport:
        return imports.read(who, ident)

    @routes.put("/{ident}")
    def settings(ident: UUID, body: AnyRailSettings, who: Asker) -> AnyRailImport:
        return imports.settings(who, ident, body)

    @routes.post("/{ident}/create")
    def create(ident: UUID, body: AnyRailCreate, who: Asker) -> AnyRailCreated:
        return imports.create(who, ident, body)

    @routes.get("/{ident}/files/{name}", response_model=None)
    def file(ident: UUID, name: str, who: Asker) -> Response:
        found = imports.file(who, ident, name)
        return Response(
            found.data,
            media_type=found.media_type,
            headers={
                "Content-Disposition": disposition(found.name),
                "Cache-Control": "private, no-store",
            },
        )

    return routes
