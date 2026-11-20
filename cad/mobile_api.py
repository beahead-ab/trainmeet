"""CAD i mobilen's addresses (contracts/cad.py, #90): the QR code for the computer, and the
phone's own session (cad/mobile.py).

No `from __future__ import annotations` here: FastAPI reads the local dependencies from the
annotations, which must then be real objects.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response

from cad.errors import Refused
from cad.library import Who
from cad.mobile import COOKIE, NO_SESSION, SESSION_LIFETIME, Handoffs, MobileSession
from contracts.cad import (
    MobileExchange,
    MobileFlow,
    MobileHandoff,
    MobileProgress,
    MobileStart,
    ProblemCode,
)

API = "/api/cad/1"
COOKIE_PATH = API


def router(
    handoffs: Handoffs, who: Callable[..., Who], origin: Callable[[Request], str]
) -> APIRouter:
    Asker = Annotated[Who, Depends(who)]
    PhoneCookie = Annotated[str | None, Cookie(alias=COOKIE)]
    routes = APIRouter(prefix=API + "/mobile")

    def phone_of(key: str | None) -> MobileSession:
        found = handoffs.session(key)
        if found is None:
            raise Refused(401, ProblemCode.LOGIN, NO_SESSION)
        return found

    # --- The computer: Fota med mobilen -------------------------------------------------------

    @routes.post("/handoffs", status_code=201)
    def create(body: MobileStart, request: Request, asker: Asker) -> MobileHandoff:
        return handoffs.create(asker, body, origin(request))

    @routes.get("/handoffs/{handoff}")
    def status(handoff: UUID, asker: Asker) -> MobileHandoff:
        return handoffs.status(asker, handoff)

    @routes.delete("/handoffs/{handoff}")
    def cancel(handoff: UUID, asker: Asker) -> MobileHandoff:
        return handoffs.cancel(asker, handoff)

    # --- The phone ----------------------------------------------------------------------------

    @routes.post("/exchange")
    def exchange(body: MobileExchange, request: Request, response: Response) -> MobileFlow:
        address = request.client.host if request.client else ""
        key, flow = handoffs.exchange(body.code, address)
        response.set_cookie(
            COOKIE,
            key,
            max_age=int(SESSION_LIFETIME.total_seconds()),
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            path=COOKIE_PATH,
        )
        return flow

    @routes.get("/flow")
    def flow(phone: PhoneCookie = None) -> MobileFlow:
        return handoffs.flow(phone_of(phone))

    @routes.put("/flow")
    def progress(body: MobileProgress, phone: PhoneCookie = None) -> MobileFlow:
        return handoffs.progress(phone_of(phone), body)

    @routes.delete("/flow")
    def end(response: Response, phone: PhoneCookie = None) -> MobileFlow:
        ended = handoffs.end(phone_of(phone))
        response.delete_cookie(COOKIE, path=COOKIE_PATH)
        return ended

    return routes
