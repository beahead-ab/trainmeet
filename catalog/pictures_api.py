"""The pictures' addresses (contracts/catalog.py, CAT-05, CAT-17, CAT-123–CAT-133).

The right is checked as for the vehicles (CAT-49, catalog/access.py): to look is enough to see
the pictures, and to edit is needed to add, choose and remove them. ?fleet=<owner> works in a
shared fleet, and the pictures are stored with its owner, within the owner's limit (CAT-133).
The tag and the messages to the owner are hidden from the others; the pictures are not.

The picture is the request's body as it is, image/jpeg, image/png or image/webp: no form, so no
library for one. At most 15 MB is read; more is refused with 413 (CAT-123).

No `from __future__ import annotations` here: FastAPI reads the local dependencies from the
annotations, which must then be real objects.
"""

import time
from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, PlainTextResponse, Response

from catalog.access import Access, Right, Work
from catalog.fleet_api import needs
from catalog.pictures import (
    FILES_PATH,
    KINDS,
    MAX_BYTES,
    DiskStore,
    Pictures,
    too_large,
    wrong_kind,
)
from contracts.catalog import Account, Picture, Removed, StorageUse

API = "/api/catalog/1"


async def _body(request: Request) -> bytes:
    """The picture, read until it is too large: never more than MAX_BYTES and one byte."""
    kind = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if kind not in KINDS:
        raise wrong_kind()
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BYTES:
        raise too_large()
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_BYTES:
            raise too_large()
    return bytes(data)


def router(
    pictures: Pictures, logged_in: Callable[..., Account | None], access: Access
) -> APIRouter:
    Look = Annotated[Work, Depends(needs(access, logged_in, Right.LOOK))]
    Edit = Annotated[Work, Depends(needs(access, logged_in, Right.EDIT))]
    routes = APIRouter(prefix=API)

    @routes.get("/vehicles/{vehicle}/pictures")
    def vehicle_pictures(vehicle: UUID, work: Look) -> list[Picture]:
        return pictures.of_vehicle(work.owner, vehicle)

    @routes.post("/vehicles/{vehicle}/pictures", status_code=status.HTTP_201_CREATED)
    async def add_picture(
        vehicle: UUID, request: Request, work: Edit, keep_original: bool = False
    ) -> Picture:
        data = await _body(request)
        # A club's fleet counts against the club's storage (TOKEN-29); ID says which it is.
        club = await run_in_threadpool(access.is_club, work.person, work.owner)
        return await run_in_threadpool(
            lambda: pictures.add(
                work.owner,
                vehicle,
                data,
                keep_original=keep_original,
                uploaded_by=work.person,
                club=club,
            )
        )

    @routes.post("/vehicles/{vehicle}/pictures/{picture}/main")
    def make_main(vehicle: UUID, picture: UUID, work: Edit) -> list[Picture]:
        return pictures.set_main(work.owner, vehicle, picture)

    @routes.delete("/vehicles/{vehicle}/pictures/{picture}")
    def remove_picture(
        vehicle: UUID, picture: UUID, work: Edit, background: BackgroundTasks
    ) -> Removed:
        pictures.remove(work.owner, vehicle, picture)
        background.add_task(pictures.sweep)
        return Removed(id=picture)

    @routes.get("/storage")
    def storage(work: Look) -> StorageUse:
        """The owner's storage: the person's, or the club's for a club's fleet (TOKEN-29)."""
        return pictures.usage(work.owner, club=access.is_club(work.person, work.owner))

    files = pictures.store if isinstance(pictures.store, DiskStore) else None

    @routes.get(FILES_PATH.removeprefix(API) + "{key:path}", response_model=None)
    def picture_file(key: str, expires: str = "", sig: str = "") -> Response:
        """A file on Catalog's own disk, for a signed address that has not expired (CAT-130).
        No login: the signature is the right. With Object Storage this is not here."""
        if files is None:
            return PlainTextResponse("Finns inte.", status_code=404)
        until = files.check(key, expires, sig)
        path = files.path(key)
        if until is None or path is None:
            return PlainTextResponse("Länken gäller inte.", status_code=403)
        if not path.is_file():
            return PlainTextResponse("Finns inte.", status_code=404)
        left = max(0, until - int(time.time()))
        return FileResponse(
            path,
            media_type="image/jpeg",
            headers={"Cache-Control": f"private, max-age={left}"},
        )

    return routes
