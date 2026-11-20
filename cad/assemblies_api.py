"""Anläggningar's and Till TKL Studio's addresses (contracts/cad.py, part d2), under CAD's own
prefix.

The assemblies are CAD's own page's, with CAD's session. The studio addresses are also Studio's:
TKL's server calls them with the person's access token from TrainMeet ID (Authorization:
Bearer, TKL18), as Ladda upp ritning does; a browser logged in to CAD may call them with its
session, for Till TKL Studio.

No `from __future__ import annotations` here: FastAPI reads the local dependencies from the
annotations, which must then be real objects.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from cad import export
from cad.assemblies import Assemblies
from cad.library import Who
from contracts.cad import (
    EXPORT_FILES,
    Assembly,
    AssemblyBrief,
    AssemblyChange,
    AssemblyRemoved,
    NewAssembly,
    StationUseAsk,
    StudioGraph,
    StudioSource,
    StudioSourceKind,
    StudioSources,
)

API = "/api/cad/1"


def router(
    assemblies: Assemblies, who: Callable[..., Who], studio_asker: Callable[..., Who]
) -> APIRouter:
    Person = Annotated[Who, Depends(who)]
    Asker = Annotated[Who, Depends(studio_asker)]
    routes = APIRouter(prefix=API)

    @routes.get("/assemblies")
    def listing(person: Person) -> list[AssemblyBrief]:
        return assemblies.listing(person)

    @routes.post("/assemblies", status_code=201)
    def create(body: NewAssembly, person: Person) -> Assembly:
        return assemblies.create(person, body)

    @routes.get("/assemblies/{assembly}")
    def read(assembly: UUID, person: Person) -> Assembly:
        return assemblies.read(person, assembly)

    @routes.put("/assemblies/{assembly}")
    def save(assembly: UUID, body: AssemblyChange, person: Person) -> Assembly:
        return assemblies.save(person, assembly, body)

    @routes.delete("/assemblies/{assembly}")
    def remove(assembly: UUID, person: Person) -> AssemblyRemoved:
        return assemblies.remove(person, assembly)

    @routes.get("/assemblies/{assembly}/dxf", response_model=None)
    def assembly_dxf(assembly: UUID, person: Person, rails: bool = False) -> Response:
        """The assembly as DXF (CAD-06): Exportera's writer, each module from its pinned version
        where the joints put it. Free, for whoever sees the assembly (CAD-18)."""
        found = assemblies.read(person, assembly)
        seen = {
            part.module: assemblies.modules.read(person, part.module, part.version)
            for part in found.parts
            if part.seen
        }
        return Response(
            export.assembly_dxf(found, seen, rails=rails),
            media_type=EXPORT_FILES["modul.dxf"][1],
            headers={
                "Content-Disposition": export.disposition(f"{found.name}.dxf"),
                "Cache-Control": "private, no-store",
            },
        )

    @routes.get("/studio")
    def sources(asker: Asker) -> StudioSources:
        return assemblies.sources(asker)

    @routes.get("/studio/{kind}/{source}")
    def graph(kind: StudioSourceKind, source: UUID, asker: Asker) -> StudioGraph:
        return assemblies.studio_graph(asker, kind, source)

    @routes.put("/studio/{kind}/{source}/station")
    def station(
        kind: StudioSourceKind, source: UUID, body: StationUseAsk, asker: Asker
    ) -> StudioSource:
        return assemblies.station_use(asker, kind, source, body)

    return routes
