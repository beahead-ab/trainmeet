"""The files' addresses (contracts/catalog.py, #56, CAT-185, CAT-186, CAT-188): a vehicle as a file
in Tellurian's format, files in that format as drafts, and the owner's account export.

The right is checked in one place (catalog/access.py). To export, a vehicle or everything, is the
owner's (CAT-46), and a club's administrators' in the club's fleet: 403 for someone who may look
or edit. To import is to add vehicles, so to edit is enough, as for the photos without AI; the
owner approves the drafts (CAT-153).

The import is a form, multipart/form-data, as for the photos (catalog/batches_api.py): the part
data is the TellurianAsk as JSON, and the parts files are the 1–50 files, each with its name. It
is read in memory and never more than 60 MB.

No `from __future__ import annotations` here: FastAPI reads the local dependencies from the
annotations, which must then be real objects.
"""

import json
from collections.abc import Callable
from typing import Annotated, Final
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from catalog import tellurian
from catalog.access import Access, Right, Work
from catalog.account_export import Exports
from catalog.batches import Batches
from catalog.fleet import Fleet, Refused
from catalog.fleet_api import needs
from catalog.pictures import MB, Pictures
from catalog.reading_api import MAX_DATA, MAX_FORM, bad_form, read_named_form
from contracts.catalog import (
    MAX_TELLURIAN_FILES,
    Account,
    ProblemCode,
    TellurianAsk,
    TellurianImport,
)

API = "/api/catalog/1"
FORM_MB: Final = MAX_FORM // MB
NAME_LENGTH: Final = 120


def attachment(name: str) -> str:
    """Content-Disposition for a file to download, also when its name is outside Latin-1, as
    ČD's or ŽSR's (RFC 6266): a plain name for old browsers, and the name itself in UTF-8."""
    plain = name.encode("ascii", "replace").decode("ascii").replace("?", "_").replace('"', "_")
    return f"attachment; filename=\"{plain}\"; filename*=utf-8''{quote(name, safe='')}"


def _too_large() -> Refused:
    return Refused(
        413,
        ProblemCode.FILES_TOO_LARGE,
        f"Filerna är större än {FORM_MB} MB tillsammans. Importera färre åt gången.",
    )


def _bad_form(why: str = "Importens formulär kunde inte läsas.") -> Refused:
    return bad_form(why)


def _name(sent: str, number: int) -> str:
    """The file's name as the browser sent it, without a folder, and never empty."""
    name = sent.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name[:NAME_LENGTH] or f"fil-{number}.json"


def _ask(found: list[tuple[str, str, bytes]]) -> tuple[TellurianAsk, list[tuple[str, bytes]]]:
    """The TellurianAsk and the files with their names, and nothing else."""
    data = [value for name, _, value in found if name == "data"]
    files = [(sent, value) for name, sent, value in found if name == "files"]
    if len(data) != 1 or len(data) + len(files) != len(found) or len(data[0]) > MAX_DATA:
        raise _bad_form()
    if not 1 <= len(files) <= MAX_TELLURIAN_FILES:
        raise _bad_form(f"Välj 1–{MAX_TELLURIAN_FILES} filer i Tellurians format.")
    try:
        ask = TellurianAsk.model_validate_json(data[0], strict=True)
    except ValidationError as error:
        raise _bad_form() from error
    return ask, [(_name(sent, n), value) for n, (sent, value) in enumerate(files, start=1)]


def router(
    fleet: Fleet,
    batches: Batches,
    pictures: Pictures,
    exports: Exports,
    logged_in: Callable[..., Account | None],
    access: Access,
) -> APIRouter:
    Edit = Annotated[Work, Depends(needs(access, logged_in, Right.EDIT))]
    Own = Annotated[Work, Depends(needs(access, logged_in, Right.OWNER))]
    routes = APIRouter(prefix=API)

    @routes.get("/vehicles/{vehicle}/tellurian", response_class=Response)
    def tellurian_file(vehicle: UUID, work: Own) -> Response:
        """The vehicle as a file in Tellurian's format, named after its litt and number."""
        found = fleet.get(work.owner, vehicle)
        main = pictures.main_file(work.owner, vehicle)
        picture = tellurian.as_jpeg(main) if main is not None else None
        wagon = tellurian.to_tellurian(found, fleet.owner_name(work.owner), picture)
        return Response(
            json.dumps(wagon, ensure_ascii=False, indent=2).encode("utf-8"),
            media_type="application/json",
            headers={"Content-Disposition": attachment(tellurian.file_name(found))},
        )

    @routes.post("/batches/tellurian")
    async def import_tellurian(request: Request, work: Edit) -> TellurianImport:
        """Each file a draft in a batch of files, or why not (CAT-186, CAT-149)."""
        ask, files = _ask(await read_named_form(request, _too_large, _bad_form))
        return await run_in_threadpool(lambda: batches.add_files(work, ask, files))

    @routes.get("/export", response_class=StreamingResponse)
    def account_export(work: Own) -> StreamingResponse:
        """Everything the owner has, as one ZIP, written while it is sent (CAT-188)."""
        made = exports.read(work.owner)
        return StreamingResponse(
            exports.zip(made),
            media_type="application/zip",
            headers={"Content-Disposition": attachment(made.file_name)},
        )

    return routes
