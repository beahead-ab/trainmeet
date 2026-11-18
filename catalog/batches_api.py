"""The batches' addresses (contracts/catalog.py, #52 del b, CAT-146–CAT-153).

The right is checked as for the vehicles (catalog/access.py): to edit is needed to leave photos,
see one's batches and fill in their cards; the owner's right, a club's administrators' in the
club's fleet included, to read with AI, read again and approve (CAT-46, CAT-153). To look gives
403; a fleet not seen, 404.

The photos come as a form, multipart/form-data, as for one reading (catalog/reading_api.py): the
part data is the BatchAsk as JSON, and the parts images are the photos. It is read in memory and
never more than 60 MB, so the web app sends 30 large photos in several requests with the same
batch id. The removed cards' files are deleted after the answer has gone.

No `from __future__ import annotations` here: FastAPI reads the local dependencies from the
annotations, which must then be real objects.
"""

from collections.abc import Callable
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from catalog.access import Access, Right, Work
from catalog.batches import Batches
from catalog.fleet import Refused
from catalog.fleet_api import needs
from catalog.pictures import MB
from catalog.reading_api import MAX_DATA, MAX_FORM, read_form
from contracts.catalog import (
    MAX_BATCH_PHOTOS,
    Account,
    Batch,
    BatchApproval,
    BatchAsk,
    BatchCard,
    BatchCardChange,
    BatchSummary,
    ProblemCode,
    Removed,
)

API = "/api/catalog/1"
FORM_MB: Final = MAX_FORM // MB
"""What one request may carry, in MB: four photos of the largest kind (CAT-123)."""


def _too_large() -> Refused:
    return Refused(
        413,
        ProblemCode.PICTURE_TOO_LARGE,
        f"Fotona är för stora för ett anrop: högst {FORM_MB} MB åt gången. Skicka resten i ett "
        "nytt anrop med samma omgång.",
    )


def _bad_form(why: str = "Omgångens formulär kunde inte läsas.") -> HTTPException:
    return HTTPException(status_code=422, detail=why)


def _ask(found: list[tuple[str, bytes]]) -> tuple[BatchAsk, list[bytes]]:
    """The BatchAsk and the photos, and nothing else."""
    data = [value for name, value in found if name == "data"]
    photos = [value for name, value in found if name == "images"]
    if len(data) != 1 or len(data) + len(photos) != len(found) or len(data[0]) > MAX_DATA:
        raise _bad_form()
    if not 1 <= len(photos) <= MAX_BATCH_PHOTOS:
        raise _bad_form(f"Välj 1–{MAX_BATCH_PHOTOS} foton.")
    try:
        ask = BatchAsk.model_validate_json(data[0], strict=True)
    except ValidationError as error:
        raise _bad_form() from error
    return ask, photos


def router(
    batches: Batches,
    logged_in: Callable[..., Account | None],
    access: Access,
    *,
    sweep: Callable[[], object] | None = None,
) -> APIRouter:
    """sweep deletes the removed cards' files, after the answer has gone (CAT-130)."""
    Edit = Annotated[Work, Depends(needs(access, logged_in, Right.EDIT))]
    Own = Annotated[Work, Depends(needs(access, logged_in, Right.OWNER))]
    routes = APIRouter(prefix=API)

    def swept(background: BackgroundTasks) -> None:
        if sweep is not None:
            background.add_task(sweep)

    @routes.get("/batches")
    def batch_list(work: Edit) -> list[BatchSummary]:
        """The batches with photos to approve: someone who edits sees only their own."""
        return batches.batches(work)

    @routes.post("/batches")
    async def add_photos(request: Request, work: Edit) -> Batch:
        """A new batch, or more photos for the same id (CAT-147, CAT-149)."""
        ask, photos = _ask(await read_form(request, _too_large))
        # A club's fleet pays from the club's balance (TOKEN-29); ID says which it is.
        club = await run_in_threadpool(access.is_club, work.person, work.owner)
        return await run_in_threadpool(lambda: batches.add(work, ask, photos, club=club))

    @routes.get("/batches/{batch}")
    def batch(batch: UUID, work: Edit) -> Batch:
        return batches.get(work, batch)

    @routes.delete("/batches/{batch}")
    def remove_batch(batch: UUID, work: Edit, background: BackgroundTasks) -> Removed:
        """The batch's cards not approved, with their files (CAT-148)."""
        batches.remove(work, batch)
        swept(background)
        return Removed(id=batch)

    @routes.post("/batches/{batch}/cards/{card}")
    def change_card(batch: UUID, card: UUID, body: BatchCardChange, work: Edit) -> BatchCard:
        return batches.change(work, batch, card, body)

    @routes.delete("/batches/{batch}/cards/{card}")
    def remove_card(batch: UUID, card: UUID, work: Edit, background: BackgroundTasks) -> Removed:
        batches.remove_card(work, batch, card)
        swept(background)
        return Removed(id=card)

    @routes.post("/batches/{batch}/cards/{card}/retry")
    def retry(batch: UUID, card: UUID, work: Own) -> BatchCard:
        """Read the photo again: one that failed, or was left when the tokens ran out."""
        return batches.retry(work, batch, card)

    @routes.post("/batches/{batch}/approve")
    def approve(batch: UUID, body: BatchApproval, work: Own) -> Batch:
        """Godkänn alla: every open card becomes a vehicle, or none does (CAT-150)."""
        club = access.is_club(work.person, work.owner)
        return batches.approve(work, batch, body, club=club)

    return routes
