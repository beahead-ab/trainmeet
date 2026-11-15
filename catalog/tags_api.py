"""The tags' addresses: the lookup, linking, the QR label and simulated tags (#54).

No `from __future__ import annotations`, as in fleet_api.py: FastAPI reads the local
dependencies from the annotations.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from catalog.fleet import Fleet, Refused
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
    Vehicle,
)

API = "/api/catalog/1"


def lookup_json(lookup: Lookup) -> dict[str, object]:
    """The answer exactly as the whitelist says: logged out, an unknown tag says nothing more."""
    data: dict[str, object] = lookup.model_dump(mode="json")
    if data["outcome"] == "unknown" and data.get("tag_uid") is None:
        return {"outcome": "unknown"}
    return data


def router(fleet: Fleet, tags: Tags, logged_in: Callable[..., Account | None]) -> APIRouter:
    def owner(account: Annotated[Account | None, Depends(logged_in)]) -> UUID:
        if account is None:
            raise Refused(401, ProblemCode.LOGIN, "Logga in först.")
        return account.id

    Owner = Annotated[UUID, Depends(owner)]
    Maybe = Annotated[Account | None, Depends(logged_in)]
    routes = APIRouter(prefix=API)

    @routes.post("/tags/simulated", status_code=status.HTTP_201_CREATED)
    def new_simulated(me: Owner) -> Tag:
        return tags.new_simulated(me)

    @routes.get("/tags/pending")
    def pending(me: Owner) -> PendingState:
        return tags.pending(me)

    @routes.post("/tags/pending")
    def wait_for_tag(body: NewPending, me: Owner) -> PendingState:
        return tags.wait_for_tag(me, body.vehicle, body.replace)

    @routes.delete("/tags/pending")
    def stop_waiting(me: Owner) -> PendingState:
        return tags.stop_waiting(me)

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
    def link(uid: str, body: TagLink, me: Owner) -> Vehicle:
        tags.link(me, uid, body)
        return fleet.get(me, body.vehicle)

    @routes.get("/tags/{uid}/events")
    def events(uid: str, me: Owner) -> list[TagEvent]:
        return tags.events(me, uid)

    @routes.get("/tags/{uid}/qr.svg", response_class=Response)
    def qr(uid: str, me: Owner) -> Response:
        return Response(tags.qr_svg(me, uid), media_type="image/svg+xml")

    @routes.post("/vehicles/{vehicle}/tags/qr")
    def new_label(vehicle: UUID, body: NewLabel, me: Owner) -> Vehicle:
        tags.new_label(me, vehicle, body.replace)
        return fleet.get(me, vehicle)

    @routes.post("/vehicles/{vehicle}/tags/unlink")
    def unlink(vehicle: UUID, body: TagUnlink, me: Owner) -> Vehicle:
        tags.unlink(me, vehicle, body)
        return fleet.get(me, vehicle)

    return routes
