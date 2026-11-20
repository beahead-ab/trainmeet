"""Landskapet's and Exportera's addresses (contracts/cad.py, part d1), under CAD's own prefix.

No `from __future__ import annotations` here: FastAPI reads the local dependencies from the
annotations, which must then be real objects.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from cad.export import Exports, disposition
from cad.landscapes import Landscapes
from cad.library import Who
from contracts.cad import Landscape, LandscapeEdit, LandscapeMake, ModuleExport

API = "/api/cad/1"


def router(landscapes: Landscapes, exports: Exports, who: Callable[..., Who]) -> APIRouter:
    Asker = Annotated[Who, Depends(who)]
    routes = APIRouter(prefix=API + "/modules/{module}")

    @routes.get("/landscape")
    def landscape(module: UUID, asker: Asker, version: int | None = None) -> Landscape:
        return landscapes.get(asker, module, version)

    @routes.post("/landscape")
    def preview(module: UUID, body: LandscapeEdit, asker: Asker) -> Landscape:
        return landscapes.preview(asker, module, body)

    @routes.post("/landscape/make")
    def make(module: UUID, body: LandscapeMake, asker: Asker) -> Landscape:
        return landscapes.make(asker, module, body)

    @routes.post("/landscape/save")
    def save(module: UUID, body: LandscapeEdit, asker: Asker) -> Landscape:
        return landscapes.save(asker, module, body)

    @routes.post("/landscape/approve")
    def approve(module: UUID, body: LandscapeEdit, asker: Asker) -> Landscape:
        return landscapes.save(asker, module, body, approve=True)

    @routes.get("/export")
    def export(module: UUID, asker: Asker, version: int | None = None) -> ModuleExport:
        return exports.summary(asker, module, version)

    @routes.get("/export/{version}/{name}", response_model=None)
    def export_file(
        module: UUID,
        version: int,
        name: str,
        asker: Asker,
        rails: bool = False,
        landscape: bool = True,
    ) -> Response:
        found = exports.file(asker, module, version, name, rails=rails, landscape=landscape)
        return Response(
            found.data,
            media_type=found.media_type,
            headers={
                "Content-Disposition": disposition(found.name, found.attachment),
                "Cache-Control": "private, no-store",
            },
        )

    return routes
