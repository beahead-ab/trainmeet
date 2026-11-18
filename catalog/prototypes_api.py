"""The prototype catalog's addresses (contracts/catalog.py, #53 del a, CAT-155–CAT-165).

The catalog is for everyone who is logged in (CAT-155); the review queue only for the reviewers
TrainMeet ID names (CAT-165). The vehicle's link is a change of the vehicle: an editor in a
shared fleet links, someone who may only look does not (CAT-46, catalog/access.py), and
?fleet=<owner> works in a shared fleet as for the vehicles.

No `from __future__ import annotations` here: FastAPI reads the local dependencies from the
annotations, which must then be real objects.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from catalog.access import Access, Right, Work, shown
from catalog.fleet import Refused
from catalog.fleet_api import needs
from catalog.prototype_fields import register
from catalog.prototypes import Prototypes
from contracts.catalog import (
    Account,
    FieldRegister,
    ProblemCode,
    Prototype,
    PrototypeLink,
    PrototypeList,
    PrototypeOverrides,
    PrototypeProposal,
    PrototypeReview,
    PrototypeRevision,
    Vehicle,
    VehicleKind,
)

API = "/api/catalog/1"


def router(
    prototypes: Prototypes, logged_in: Callable[..., Account | None], access: Access
) -> APIRouter:
    def person(account: Annotated[Account | None, Depends(logged_in)]) -> UUID:
        if account is None:
            raise Refused(401, ProblemCode.LOGIN, "Logga in först.")
        return account.id

    Person = Annotated[UUID, Depends(person)]
    Edit = Annotated[Work, Depends(needs(access, logged_in, Right.EDIT))]
    routes = APIRouter(prefix=API)

    @routes.get("/prototypes/fields")
    def fields() -> FieldRegister:
        """The field register and the profiles: open to anyone, like the licence (CAT-156)."""
        return register()

    @routes.get("/prototypes")
    def catalog(
        me: Person,
        q: str = "",
        kind: Annotated[list[VehicleKind] | None, Query()] = None,
    ) -> PrototypeList:
        return prototypes.search(me, q=q[:80], kinds=kind or ())

    @routes.post("/prototypes/proposals", status_code=status.HTTP_201_CREATED)
    def propose(body: PrototypeProposal, me: Person) -> PrototypeRevision:
        return prototypes.propose(me, body)

    @routes.get("/prototypes/proposals/mine")
    def mine(me: Person) -> list[PrototypeRevision]:
        return prototypes.mine(me)

    @routes.get("/prototypes/proposals/queue")
    def queue(me: Person) -> list[PrototypeRevision]:
        return prototypes.queue(me)

    @routes.post("/prototypes/proposals/{revision}/review")
    def review(revision: UUID, body: PrototypeReview, me: Person) -> PrototypeRevision:
        return prototypes.review(me, revision, body)

    @routes.get("/prototypes/{prototype}")
    def prototype(prototype: UUID, me: Person) -> Prototype:
        return prototypes.get(me, prototype)

    @routes.post("/vehicles/{vehicle}/prototype")
    def link(vehicle: UUID, body: PrototypeLink, work: Edit) -> Vehicle:
        return shown(prototypes.link(work, vehicle, body), work)

    @routes.put("/vehicles/{vehicle}/prototype")
    def override(vehicle: UUID, body: PrototypeOverrides, work: Edit) -> Vehicle:
        return shown(prototypes.override(work, vehicle, body), work)

    @routes.delete("/vehicles/{vehicle}/prototype")
    def unlink(vehicle: UUID, version: int, work: Edit) -> Vehicle:
        return shown(prototypes.unlink(work, vehicle, version), work)

    return routes
