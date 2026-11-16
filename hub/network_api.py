"""Pi:ns nät (SYNK-07, SYNK-26, H45): the Pi's own Wi-Fi under the gear, through the helper.

Only the logged-in administrator, even while the hub is being set up. A change carries the
header X-TrainMeet-Network and comes from the hub's own page, so that another site cannot make
the browser send one. And it is only made in the browser on the Pi itself or over HTTPS: a
password never crosses the meet's network in the clear. Over plain HTTP from another machine
the list can be read, but not changed. No password ever comes back.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from contracts import hub
from hub.hubben import Authorization, SessionCookie, require_admin, session_of
from hub.local import LocalLogin
from synk import network

HostRequest = Callable[[str, dict[str, Any], str], dict[str, Any]]
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
FORWARDED = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto")


def safe_transport(request: Request) -> bool:
    """HTTPS, or the browser on the Pi itself with no proxy between."""
    if request.url.scheme == "https":
        return True
    client = request.client.host if request.client else ""
    return client in LOOPBACK and not any(request.headers.get(name) for name in FORWARDED)


def _same_site(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin and origin.split("://", 1)[-1] != request.headers.get("host", ""):
        return False
    return request.headers.get("sec-fetch-site", "same-origin") in {"same-origin", "none"}


def router(login: LocalLogin, ask: HostRequest | None = None) -> APIRouter:
    routes = APIRouter(prefix="/api/hub/wifi")

    def host(action: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        if ask is not None:
            return ask(action, payload, actor)
        return network.host_request(action, payload, actor)

    def actor(session: str | None, authorization: str | None) -> str:
        """Which administrator: the trial's token goes only to the one who started it."""
        token = session_of(session, authorization) or ""
        return "admin-" + hashlib.sha256(token.encode()).hexdigest()[:32]

    async def answer(
        request: Request, action: str, payload: dict[str, Any], who: str
    ) -> dict[str, Any]:
        try:
            result = await run_in_threadpool(host, action, payload, who)
        except network.NetworkError as error:
            status = 503 if error.code == "host_unavailable" else 409
            raise HTTPException(status, str(error)) from None
        shown = hub.WifiStatus.model_validate(
            {**result, "can_manage": safe_transport(request) and bool(result.get("supported"))}
        )
        return shown.model_dump(mode="json")

    @routes.get("")
    async def status(
        request: Request,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        await run_in_threadpool(require_admin, login, session, authorization)
        return await answer(request, "status", {}, actor(session, authorization))

    async def change(
        request: Request,
        action: str,
        payload: dict[str, Any],
        session: str | None,
        authorization: str | None,
        marked: str | None,
    ) -> dict[str, Any]:
        await run_in_threadpool(require_admin, login, session, authorization)
        if marked != "1" or not _same_site(request):
            raise HTTPException(403, "Ändra Pi:ns nät från hubbens egen sida.")
        if not safe_transport(request):
            raise HTTPException(403, "Ändra Pi:ns nät i webbläsaren på Pi:n, eller över HTTPS.")
        return await answer(request, action, payload, actor(session, authorization))

    @routes.post("/save")
    async def save(
        profile: hub.WifiProfileChange,
        request: Request,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
        marked: str | None = Header(default=None, alias="X-TrainMeet-Network"),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        payload = profile.model_dump(exclude_none=True)
        return await change(request, "save", payload, session, authorization, marked)

    @routes.post("/{action}")
    async def act(
        action: Literal["scan", "delete", "order", "connect", "confirm", "rollback"],
        given: hub.WifiAction,
        request: Request,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
        marked: str | None = Header(default=None, alias="X-TrainMeet-Network"),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        payload = given.model_dump(exclude_none=True)
        return await change(request, action, payload, session, authorization, marked)

    return routes
