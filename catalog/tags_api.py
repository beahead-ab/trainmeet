"""The tags' addresses: the lookup, linking, the QR label and simulated tags (#54).

No `from __future__ import annotations`, as in fleet_api.py: FastAPI reads the local
dependencies from the annotations.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from catalog.access import Access, Right, Work
from catalog.fleet import Fleet, Refused
from catalog.fleet_api import needs
from catalog.tags import Tags
from contracts.catalog import (
    Account,
    Lookup,
    NewLabel,
    NewPending,
    PendingState,
    ProblemCode,
    Tag,
    TagEvent,
    TagLink,
    TagUnlink,
    Tell,
    Told,
    Vehicle,
)

API = "/api/catalog/1"


def lookup_json(lookup: Lookup) -> dict[str, object]:
    """The answer exactly as the whitelist says: logged out, an unknown tag says nothing more."""
    data: dict[str, object] = lookup.model_dump(mode="json")
    if data["outcome"] == "unknown" and data.get("tag_uid") is None:
        return {"outcome": "unknown"}
    return data


def router(
    fleet: Fleet, tags: Tags, logged_in: Callable[..., Account | None], access: Access
) -> APIRouter:
    def owner(account: Annotated[Account | None, Depends(logged_in)]) -> UUID:
        if account is None:
            raise Refused(401, ProblemCode.LOGIN, "Logga in först.")
        return account.id

    Owner = Annotated[UUID, Depends(owner)]
    # The tags of the fleet worked in: the owner's, or a club's administrators' (CAT-46, C39).
    Own = Annotated[Work, Depends(needs(access, logged_in, Right.OWNER))]
    Maybe = Annotated[Account | None, Depends(logged_in)]
    routes = APIRouter(prefix=API)

    @routes.post("/tags/simulated", status_code=status.HTTP_201_CREATED)
    def new_simulated(work: Own) -> Tag:
        return tags.new_simulated(work.owner)

    @routes.get("/tags/pending")
    def pending(work: Own) -> PendingState:
        return tags.pending(work.owner)

    @routes.post("/tags/pending")
    def wait_for_tag(body: NewPending, work: Own) -> PendingState:
        return tags.wait_for_tag(work.owner, body.vehicle, body.replace)

    @routes.delete("/tags/pending")
    def stop_waiting(work: Own) -> PendingState:
        return tags.stop_waiting(work.owner)

    @routes.get("/tags/{uid}", response_model=Lookup)
    def lookup(uid: str, request: Request, account: Maybe) -> JSONResponse:
        """One of five outcomes. Never kept, and private to the browser (CAT-108, CAT-110)."""
        address = request.client.host if request.client else ""
        try:
            found = tags.lookup(account.id if account else None, uid, address)
        except Refused as refused:
            if refused.status == 429:
                return JSONResponse(
                    {"code": refused.code.value, "message": refused.message},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
            raise
        return JSONResponse(lookup_json(found))

    @routes.post("/tags/{uid}/link")
    def link(uid: str, body: TagLink, work: Own) -> Vehicle:
        tags.link(work.owner, uid, body)
        return fleet.get(work.owner, body.vehicle)

    @routes.post("/tags/{uid}/notice")
    def tell(uid: str, body: Tell, me: Owner) -> Told:
        return tags.tell(me, uid, body.text)

    @routes.get("/tags/{uid}/events")
    def events(uid: str, work: Own) -> list[TagEvent]:
        return tags.events(work.owner, uid)

    @routes.get("/tags/{uid}/qr.svg", response_class=Response)
    def qr(uid: str, work: Own) -> Response:
        return Response(tags.qr_svg(work.owner, uid), media_type="image/svg+xml")

    @routes.post("/vehicles/{vehicle}/tags/qr")
    def new_label(vehicle: UUID, body: NewLabel, work: Own) -> Vehicle:
        tags.new_label(work.owner, vehicle, body.replace)
        return fleet.get(work.owner, vehicle)

    @routes.post("/vehicles/{vehicle}/tags/unlink")
    def unlink(vehicle: UUID, body: TagUnlink, work: Own) -> Vehicle:
        tags.unlink(work.owner, vehicle, body)
        return fleet.get(work.owner, vehicle)

    return routes
