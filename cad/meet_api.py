"""The meet's assembly to the Hub (contracts/cad.py, part d3, CAD-11, CAD-12, K4).

The cloud hub's Planering lists the planner's assemblies and fetches one as underlag for its
import, with the planner's own access token from TrainMeet ID for the client hub (#78). The
assembly comes placed and joined, with every module at the version it pins, so that the Hub can
keep it as it came and take it to the meet's Pi without asking CAD again (CAD-12, CAD-14).

Only what the person sees: the assembly by its rights (cad/assemblies.py), and every module in
it, else 422. The modules come without their owners, photos and history.

No `from __future__ import annotations` here: FastAPI reads the local dependencies from the
annotations, which must then be real objects.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from cad.assemblies import Assemblies
from cad.errors import Refused
from cad.library import Who
from contracts.cad import (
    AssemblyBrief,
    MeetAssembly,
    MeetModule,
    MeetStation,
    ProblemCode,
)

API = "/api/cad/1/meet"


def unseen() -> Refused:
    return Refused(
        422,
        ProblemCode.INVALID,
        "En modul i anläggningen syns inte för dig. Ta bort den ur anläggningen, eller be ägaren "
        "visa den, innan anläggningen blir underlag.",
    )


def meet_assembly(assemblies: Assemblies, who: Who, ident: UUID) -> MeetAssembly:
    """The assembly as the Hub keeps it: placed, joined, and its modules at their versions."""
    found = assemblies.read(who, ident)
    modules: list[MeetModule] = []
    for part in found.parts:
        if not part.seen:
            raise unseen()
        module = assemblies.modules.read(who, part.module, part.version)
        stations = {
            (used.station, used.name): None
            for used in module.used_in
            if used.kind == "station" and used.station is not None and used.id != found.id
        }
        modules.append(
            MeetModule(
                id=module.id,
                number=module.number,
                name=module.name,
                version=module.version,
                scale=module.scale,
                shape=module.shape,
                gables=module.gables,
                graph=module.graph,
                track_length=module.track_length,
                stations=[MeetStation(station_id=s, name=n) for s, n in stations],
            )
        )
    return MeetAssembly(
        id=found.id,
        name=found.name,
        scale=found.scale,
        revision=found.revision,
        changed_at=found.changed_at,
        placed=found.modules,
        joints=found.joints,
        problems=found.problems,
        graph=found.graph,
        modules=modules,
        stations=[MeetStation(station_id=s.station_id, name=s.name) for s in found.stations],
    )


def router(assemblies: Assemblies, hub_asker: Callable[..., Who]) -> APIRouter:
    Asker = Annotated[Who, Depends(hub_asker)]
    routes = APIRouter(prefix=API)

    @routes.get("/assemblies")
    def listing(asker: Asker) -> list[AssemblyBrief]:
        return assemblies.listing(asker)

    @routes.get("/assemblies/{assembly}")
    def one(assembly: UUID, asker: Asker) -> MeetAssembly:
        return meet_assembly(assemblies, asker, assembly)

    return routes
