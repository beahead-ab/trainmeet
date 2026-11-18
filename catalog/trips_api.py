"""The trip's addresses: the meets, the pack list, the ticks and the tap (#55, CAT-174–CAT-183).

The meets are the owner's own (CAT-174), and the trip moves the vehicles, which is the owner's
own history (CAT-77, CAT-182). So every address needs the owner's right: the person's own
fleet, or a club's as its administrator (C39). Someone the fleet is shared with to look or to
edit gets 403, anyone else 404 (CAT-46, CAT-49).

No `from __future__ import annotations` here, as in fleet_api.py: FastAPI reads the local
dependencies from the annotations.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from catalog.access import Access, Right, Work
from catalog.fleet_api import needs
from catalog.trips import Trips
from contracts.catalog import (
    Account,
    NewTrip,
    PackList,
    TickChange,
    Trip,
    TripSummary,
    TripTap,
    TripTapped,
)

API = "/api/catalog/1"


def router(trips: Trips, logged_in: Callable[..., Account | None], access: Access) -> APIRouter:
    Own = Annotated[Work, Depends(needs(access, logged_in, Right.OWNER))]
    routes = APIRouter(prefix=API)

    @routes.get("/meets")
    def meets(work: Own) -> list[TripSummary]:
        return trips.meets(work.owner)

    @routes.post("/meets", status_code=status.HTTP_201_CREATED)
    def new_trip(body: NewTrip, work: Own) -> Trip:
        return trips.create(work.owner, body)

    @routes.get("/meets/{meet}")
    def trip(meet: UUID, work: Own) -> Trip:
        return trips.get(work.owner, meet)

    @routes.post("/meets/{meet}/vehicles")
    def pack_list(meet: UUID, body: PackList, work: Own) -> Trip:
        return trips.pack_list(work.owner, meet, list(body.vehicles))

    @routes.post("/meets/{meet}/ticks")
    def tick(meet: UUID, body: TickChange, work: Own) -> Trip:
        return trips.tick(work.owner, meet, body)

    @routes.post("/meets/{meet}/tap")
    def tap(meet: UUID, body: TripTap, work: Own) -> TripTapped:
        return trips.tap(work.owner, meet, body)

    @routes.post("/meets/{meet}/archive")
    def archive(meet: UUID, work: Own) -> Trip:
        return trips.archive(work.owner, meet)

    return routes
