"""The reading's addresses (contracts/catalog.py, #52, CAT-135–CAT-146).

Only the owner reads with AI, and a club's administrators in the club's fleet (CAT-46): the
right is checked as for the tags (catalog/access.py), 403 for someone who may look or edit.

The reading is a form, multipart/form-data, as a browser sends it: the part data is the
ReadingAsk as JSON, and the parts images are the 1–4 photos. The form is read here, in memory
and never more than four photos of 15 MB, rather than with a library for forms, which would put
the photos in temporary files on disk before their metadata is gone (CAT-124, CAT-143).

No `from __future__ import annotations` here: FastAPI reads the local dependencies from the
annotations, which must then be real objects.
"""

import re
from collections.abc import Callable
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from catalog.access import Access, Right, Work
from catalog.fleet import Refused
from catalog.fleet_api import needs
from catalog.pictures import MAX_BYTES, too_large
from catalog.reading import MAX_PICTURES, Readings, without_id
from contracts.catalog import Account, ProblemCode, Reading, ReadingAsk, ReadingConsent

API = "/api/catalog/1"
MAX_FORM: Final = MAX_PICTURES * MAX_BYTES + 64 * 1024
"""Four photos of at most 15 MB each (CAT-123), and the form around them."""
MAX_DATA: Final = 4096
_BOUNDARY: Final = re.compile(r'boundary=(?:"([^"\r\n]{1,70})"|([^\s;",]{1,70}))', re.IGNORECASE)
_NAME: Final = re.compile(r'(?:^|;)\s*name="([^"\r\n]*)"', re.IGNORECASE)


def bad_form(why: str = "Avläsningens formulär kunde inte läsas.") -> Refused:
    """A form that cannot be read: 422 bad_form, as a Problem like the rest of the API. Nothing
    was read, drawn or kept."""
    return Refused(422, ProblemCode.BAD_FORM, why)


async def _body(request: Request, refused: Callable[[], Refused] = too_large) -> bytes:
    """The form, read until it is too large: never more than MAX_FORM and one byte."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_FORM:
        raise refused()
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_FORM:
            raise refused()
    return bytes(data)


async def read_form(
    request: Request,
    refused: Callable[[], Refused] = too_large,
    bad: Callable[[], Refused] = bad_form,
) -> list[tuple[str, bytes]]:
    """The form's parts, by name, read in memory and never more than MAX_FORM (#52 del b).
    bad is the no to a form that cannot be read, in the words of the one asking."""
    body = await _body(request, refused)
    return parts(request.headers.get("content-type", ""), body, bad)


def parts(
    content_type: str, body: bytes, bad: Callable[[], Refused] = bad_form
) -> list[tuple[str, bytes]]:
    """The form's parts, by name, as multipart/form-data has them (RFC 7578). Anything that
    does not follow it is refused, rather than read as well as it goes."""
    kind = content_type.split(";", 1)[0].strip().lower()
    boundary = _BOUNDARY.search(content_type)
    if kind != "multipart/form-data" or boundary is None:
        raise bad()
    delimiter = b"\r\n--" + (boundary[1] or boundary[2]).encode("latin-1")
    chunks = (b"\r\n" + body).split(delimiter)
    # The preamble, the parts, and what follows the closing delimiter, which starts with --.
    if len(chunks) < 3 or chunks[0] or not chunks[-1].startswith(b"--"):
        raise bad()
    found: list[tuple[str, bytes]] = []
    for chunk in chunks[1:-1]:
        head, separator, data = chunk.lstrip(b" \t").partition(b"\r\n\r\n")
        if not separator or not head.startswith(b"\r\n"):
            raise bad()
        names = [
            _NAME.search(value)
            for key, _, value in (
                line.partition(":") for line in head[2:].decode("latin-1").split("\r\n")
            )
            if key.strip().lower() == "content-disposition"
        ]
        if len(names) != 1 or names[0] is None:
            raise bad()
        found.append((names[0][1], data))
    return found


def _ask(found: list[tuple[str, bytes]]) -> tuple[ReadingAsk, list[bytes]]:
    """The ReadingAsk and the photos, and nothing else."""
    data = [value for name, value in found if name == "data"]
    photos = [value for name, value in found if name == "images"]
    if len(data) != 1 or len(data) + len(photos) != len(found) or len(data[0]) > MAX_DATA:
        raise bad_form()
    if not 1 <= len(photos) <= MAX_PICTURES:
        raise bad_form("Välj 1–4 foton.")
    try:
        ask = ReadingAsk.model_validate_json(data[0], strict=True)
    except ValidationError as error:
        raise bad_form() from error
    if (ask.vehicle is None) != (ask.version is None):
        raise bad_form("Fordonet och dess version skickas tillsammans.")
    return ask, photos


def router(
    readings: Readings, logged_in: Callable[..., Account | None], access: Access
) -> APIRouter:
    Own = Annotated[Work, Depends(needs(access, logged_in, Right.OWNER))]
    routes = APIRouter(prefix=API)

    @routes.get("/readings/consent")
    def consent(work: Own) -> ReadingConsent:
        """What is sent and to whom, before the first reading (CAT-142)."""
        club = access.is_club(work.person, work.owner)
        return readings.consent(work.person, work.owner, club=club)

    @routes.post("/readings")
    async def read(request: Request, work: Own) -> Reading:
        """The AI's suggestions from the photos (CAT-136). Nothing is saved in a vehicle."""
        if not readings.available:
            raise without_id()
        body = await _body(request)
        ask, photos = _ask(parts(request.headers.get("content-type", ""), body))
        # A club's fleet pays from the club's balance (TOKEN-29); ID says which it is.
        club = await run_in_threadpool(access.is_club, work.person, work.owner)
        return await run_in_threadpool(
            lambda: readings.read(work.person, work.owner, ask, photos, club=club)
        )

    return routes
