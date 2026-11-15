"""The fleet's addresses: the vehicles and the places at home (contracts/catalog.py, #50).

Every call checks the login on the server (CAT-195). Only the owner sees the fleet in this
step, so the owner is the one logged in.

No `from __future__ import annotations` here: FastAPI reads the local dependency Owner from the
annotations, which must then be real objects.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

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


def router(fleet: Fleet, logged_in: Callable[..., Account | None]) -> APIRouter:
    def owner(account: Annotated[Account | None, Depends(logged_in)]) -> UUID:
        if account is None:
            raise Refused(401, ProblemCode.LOGIN, "Logga in först.")
        return account.id

    Owner = Annotated[UUID, Depends(owner)]
    routes = APIRouter(prefix=API)

    @routes.get("/vehicles")
    def vehicles(
        me: Owner,
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
        return fleet.search(
            me,
            q=q[:80],
            kinds=kind or (),
            scale=scale[:12],
            state=state,
            place=place_id,
            without_place=place == "none",
        )

    @routes.post("/vehicles", status_code=status.HTTP_201_CREATED)
    def add_vehicle(body: VehicleFields, me: Owner) -> Vehicle:
        return fleet.create(me, body)

    @routes.post("/vehicles/move")
    def move(body: Move, me: Owner) -> VehicleList:
        return fleet.move(me, body.vehicles, body.place)

    @routes.get("/vehicles/{vehicle}")
    def vehicle(vehicle: UUID, me: Owner) -> Vehicle:
        return fleet.get(me, vehicle)

    @routes.put("/vehicles/{vehicle}")
    def change_vehicle(vehicle: UUID, body: VehicleChange, me: Owner) -> Vehicle:
        return fleet.change(me, vehicle, body)

    @routes.delete("/vehicles/{vehicle}")
    def remove_vehicle(vehicle: UUID, version: int, me: Owner) -> Removed:
        fleet.remove(me, vehicle, version)
        return Removed(id=vehicle)

    @routes.post("/vehicles/{vehicle}/lend")
    def lend(vehicle: UUID, body: Lend, me: Owner) -> Vehicle:
        return fleet.lend(me, vehicle, body)

    @routes.post("/vehicles/{vehicle}/return")
    def give_back(vehicle: UUID, body: Return, me: Owner) -> Vehicle:
        return fleet.give_back(me, vehicle, body)

    @routes.get("/vehicles/{vehicle}/events")
    def events(vehicle: UUID, me: Owner) -> list[VehicleEvent]:
        return fleet.events(me, vehicle)

    @routes.delete("/vehicles/{vehicle}/notices/{notice}")
    def clear_notice(vehicle: UUID, notice: UUID, me: Owner) -> Removed:
        fleet.clear_notice(me, vehicle, notice)
        return Removed(id=notice)

    @routes.get("/settings")
    def settings(me: Owner) -> OwnerSettings:
        return fleet.settings(me)

    @routes.put("/settings")
    def change_settings(body: OwnerSettings, me: Owner) -> OwnerSettings:
        return fleet.change_settings(me, body)

    @routes.get("/places")
    def places(me: Owner) -> list[Place]:
        return fleet.places(me)

    @routes.post("/places", status_code=status.HTTP_201_CREATED)
    def add_place(body: PlaceName, me: Owner) -> Place:
        return fleet.add_place(me, body.name)

    @routes.put("/places/{place}")
    def rename_place(place: UUID, body: PlaceName, me: Owner) -> Place:
        return fleet.rename_place(me, place, body.name)

    @routes.delete("/places/{place}")
    def remove_place(place: UUID, me: Owner) -> Removed:
        fleet.remove_place(me, place)
        return Removed(id=place)

    return routes
