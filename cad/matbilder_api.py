"""Mätbilden i TKL:s Foto's addresses (contracts/cad.py, part d4), under Till TKL Studio's.

TKL's server calls them with the person's access token from TrainMeet ID (Authorization: Bearer,
TKL18), as Från CAD does; a browser logged in to CAD may call them with its session. Another
app's token is refused with 401, as for the graph.

No `from __future__ import annotations` here: FastAPI reads the local dependencies from the
annotations, which must then be real objects.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from cad.library import Who
from cad.matbilder import Matbilder
from contracts.cad import STUDIO_IMAGE_TYPE, StudioImages, StudioSourceKind

API = "/api/cad/1"


def router(matbilder: Matbilder, studio_asker: Callable[..., Who]) -> APIRouter:
    Asker = Annotated[Who, Depends(studio_asker)]
    routes = APIRouter(prefix=API + "/studio/{kind}/{source}/images")

    @routes.get("")
    def listing(kind: StudioSourceKind, source: UUID, asker: Asker) -> StudioImages:
        return matbilder.listing(asker, kind, source)

    @routes.get("/{module}/{version}", response_model=None)
    def image(
        kind: StudioSourceKind, source: UUID, module: UUID, version: int, asker: Asker
    ) -> Response:
        data = matbilder.image(asker, kind, source, module, version)
        return Response(
            data, media_type=STUDIO_IMAGE_TYPE, headers={"Cache-Control": "private, no-store"}
        )

    return routes
