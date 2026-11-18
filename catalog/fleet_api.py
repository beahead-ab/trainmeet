"""The fleet's addresses: the vehicles and the places at home (contracts/catalog.py, #50).

Every call checks the login on the server (CAT-195), and the right in one place (CAT-49,
catalog/access.py): ?fleet=<owner> works in a fleet shared with the person (#49), and without
it the person works in their own.

No `from __future__ import annotations` here: FastAPI reads the local dependency Owner from the
annotations, which must then be real objects.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status

from catalog.access import Access, Right, Work, shown, shown_list
from catalog.fleet import Fleet, Refused
from contracts.catalog import (
    Account,
    Lend,
    Move,
    OwnerSettings,
    Place,
    PlaceName,
    ProblemCode,
    Removed,
    Return,
    Vehicle,
    VehicleChange,
    VehicleEvent,
    VehicleFields,
    VehicleKind,
    VehicleList,
    VehicleState,
)

API = "/api/catalog/1"


def needs(
    access: Access, logged_in: Callable[..., Account | None], right: Right
) -> Callable[..., Work]:
    """A route's need: the person, the fleet from ?fleet=, and at least this right (CAT-49)."""

    def check(
        account: Annotated[Account | None, Depends(logged_in)],
        fleet_owner: Annotated[UUID | None, Query(alias="fleet")] = None,
    ) -> Work:
        if account is None:
            raise Refused(401, ProblemCode.LOGIN, "Logga in först.")
        return access.work(account.id, fleet_owner, right)

    return check


def router(
    fleet: Fleet,
    logged_in: Callable[..., Account | None],
    access: Access,
    *,
    sweep: Callable[[], object] | None = None,
) -> APIRouter:
    """sweep deletes the removed pictures' files, after the answer has gone (CAT-130)."""

    def person(account: Annotated[Account | None, Depends(logged_in)]) -> UUID:
        if account is None:
            raise Refused(401, ProblemCode.LOGIN, "Logga in först.")
        return account.id

    Person = Annotated[UUID, Depends(person)]

    Look = Annotated[Work, Depends(needs(access, logged_in, Right.LOOK))]
    Edit = Annotated[Work, Depends(needs(access, logged_in, Right.EDIT))]
    Own = Annotated[Work, Depends(needs(access, logged_in, Right.OWNER))]
    routes = APIRouter(prefix=API)

    @routes.get("/vehicles")
    def vehicles(
        work: Look,
        q: str = "",
        kind: Annotated[list[VehicleKind] | None, Query()] = None,
        scale: str = "",
        state: VehicleState | None = None,
        place: str = "",
    ) -> VehicleList:
        """The fleet. place is a place's id, or none for the vehicles without a place."""
        place_id: UUID | None = None
        if place and place != "none":
            try:
                place_id = UUID(place)
            except ValueError as error:
                raise Refused(422, ProblemCode.NOT_FOUND, "Platsen finns inte.") from error
        found = fleet.search(
            work.owner,
            q=q[:80],
            kinds=kind or (),
            scale=scale[:12],
            state=state,
            place=place_id,
            without_place=place == "none",
        )
        return shown_list(found, work)

    @routes.post("/vehicles", status_code=status.HTTP_201_CREATED)
    def add_vehicle(body: VehicleFields, work: Edit) -> Vehicle:
        if not work.own:  # the places are the owner's (CAT-71)
            body = body.model_copy(update={"place": None})
        return shown(fleet.create(work.owner, body), work)

    @routes.post("/vehicles/move")
    def move(body: Move, work: Own) -> VehicleList:
        return fleet.move(work.owner, body.vehicles, body.place)

    @routes.get("/vehicles/{vehicle}")
    def vehicle(vehicle: UUID, work: Look) -> Vehicle:
        return shown(fleet.get(work.owner, vehicle), work)

    @routes.put("/vehicles/{vehicle}")
    def change_vehicle(vehicle: UUID, body: VehicleChange, work: Edit) -> Vehicle:
        if not work.own:  # the core fields, but the place stays the owner's (CAT-46, CAT-71)
            body = body.model_copy(update={"place": fleet.get(work.owner, vehicle).place})
        return shown(fleet.change(work.owner, vehicle, body), work)

    @routes.delete("/vehicles/{vehicle}")
    def remove_vehicle(
        vehicle: UUID, version: int, work: Own, background: BackgroundTasks
    ) -> Removed:
        fleet.remove(work.owner, vehicle, version)
        if sweep is not None:
            background.add_task(sweep)
        return Removed(id=vehicle)

    @routes.post("/vehicles/{vehicle}/lend")
    def lend(vehicle: UUID, body: Lend, work: Own) -> Vehicle:
        return shown(fleet.lend(work.owner, vehicle, body), work)

    @routes.post("/vehicles/{vehicle}/return")
    def give_back(vehicle: UUID, body: Return, work: Own) -> Vehicle:
        return shown(fleet.give_back(work.owner, vehicle, body), work)

    @routes.get("/vehicles/{vehicle}/events")
    def events(vehicle: UUID, work: Own) -> list[VehicleEvent]:
        return fleet.events(work.owner, vehicle)

    @routes.delete("/vehicles/{vehicle}/notices/{notice}")
    def clear_notice(vehicle: UUID, notice: UUID, work: Own) -> Removed:
        fleet.clear_notice(work.owner, vehicle, notice)
        return Removed(id=notice)

    @routes.get("/settings")
    def settings(me: Person) -> OwnerSettings:
        return fleet.settings(me)

    @routes.put("/settings")
    def change_settings(body: OwnerSettings, me: Person) -> OwnerSettings:
        return fleet.change_settings(me, body)

    @routes.get("/places")
    def places(work: Look) -> list[Place]:
        return fleet.places(work.owner)

    @routes.post("/places", status_code=status.HTTP_201_CREATED)
    def add_place(body: PlaceName, work: Own) -> Place:
        return fleet.add_place(work.owner, body.name)

    @routes.put("/places/{place}")
    def rename_place(place: UUID, body: PlaceName, work: Own) -> Place:
        return fleet.rename_place(work.owner, place, body.name)

    @routes.delete("/places/{place}")
    def remove_place(place: UUID, work: Own) -> Removed:
        fleet.remove_place(work.owner, place)
        return Removed(id=place)

    return routes
