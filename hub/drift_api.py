"""Driftens API (5.4) for the hub's own meet: start the meet, run the clock, see Nu, handle the
clients, read the log and follow the events. Steg 3.

Everyone may read Nu (S1); everything else needs the local administrator's session, as a
cookie from the pages or as Authorization: Bearer. The meet lives in a file of its own, apart
from Provbanan's runs per browser (H51).
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import AsyncIterator
from typing import Any, NoReturn

import segno
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from contracts import drift
from contracts.common import Id
from contracts.reasons import TEXT_SV
from drift.engine import VERSION, Refused, now_utc
from drift.now import now
from drift.store import MissingRun, PreviewStore, RunLimit, UnknownBox, UnknownClient
from hub.hubben import Authorization, SessionCookie, require_admin
from hub.local import LocalLogin

STREAM_SECONDS = 300
STREAM_INTERVAL = 0.5
HEARTBEAT_SECONDS = 15


def _error(error: Exception) -> NoReturn:
    if isinstance(error, Refused):
        raise HTTPException(409, TEXT_SV[error.reason]) from error
    if isinstance(error, RunLimit):
        raise HTTPException(429, "Träffen har nått sin gräns.") from error
    if isinstance(error, (UnknownBox, UnknownClient)):
        raise HTTPException(404, "Klienten finns inte i träffen.") from error
    raise HTTPException(404, "Ingen träff är startad.") from error


def router(meet: PreviewStore, login: LocalLogin) -> APIRouter:
    routes = APIRouter(prefix="/api/drift/1")
    failures = (MissingRun, RunLimit, Refused, UnknownBox, UnknownClient)

    def admin(session: str | None, authorization: str | None) -> str:
        """The meet that runs, for a logged-in administrator."""
        require_admin(login, session, authorization)
        try:
            return meet.current()
        except MissingRun as error:
            _error(error)

    @routes.post("/start", status_code=201)
    def start(
        request: drift.StartMeet,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Start the meet, or a new one in its place: the old one is kept, archived."""
        response.headers["Cache-Control"] = "no-store"
        require_admin(login, session, authorization)
        if request.version != VERSION:
            raise HTTPException(409, "Den versionen av träffen finns inte i hubben.")
        try:
            run_id = meet.start(request.traffic_day, request.game_day, replace=True)
            return meet.state(run_id).history[0].model_dump(mode="json")
        except failures as error:
            _error(error)

    @routes.post("/clock")
    def clock(
        control: drift.ClockControl,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        run_id = admin(session, authorization)
        try:
            return meet.clock(run_id, control).history[-1].model_dump(mode="json")
        except failures as error:
            _error(error)

    @routes.get("/now")
    def nu(response: Response) -> dict[str, Any]:
        """Nu, open to everyone who looks (S1)."""
        response.headers["Cache-Control"] = "no-store"
        try:
            return now(meet.state(meet.current()), now_utc()).model_dump(mode="json")
        except MissingRun as error:
            _error(error)

    @routes.get("/clients")
    def clients(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> list[dict[str, Any]]:
        response.headers["Cache-Control"] = "no-store"
        return meet.clients(admin(session, authorization))

    def changed(listed: list[dict[str, Any]], client_id: str) -> dict[str, Any]:
        return next(client for client in listed if client["client_id"] == client_id)

    @routes.post("/clients/assign")
    def assign(
        change: drift.Assign,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        run_id = admin(session, authorization)
        try:
            return changed(meet.assign(run_id, change), change.client_id)
        except failures as error:
            _error(error)

    @routes.post("/clients/approve")
    def approve(
        change: drift.Approve,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        run_id = admin(session, authorization)
        try:
            return changed(meet.approve(run_id, change), change.client_id)
        except failures as error:
            _error(error)

    @routes.post("/clients/revoke")
    def revoke(
        change: drift.Revoke,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        run_id = admin(session, authorization)
        try:
            return changed(meet.revoke(run_id, change), change.client_id)
        except failures as error:
            _error(error)

    @routes.get("/log")
    def log(
        response: Response,
        place: Id | None = None,
        train: Id | None = None,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> list[dict[str, Any]]:
        response.headers["Cache-Control"] = "no-store"
        run_id = admin(session, authorization)
        return [event.model_dump(mode="json") for event in meet.log(run_id, place, train)]

    @routes.get("/connect")
    def connect(
        request: Request,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Anslut (S2): the meet's code, and the address a box opens with it."""
        response.headers["Cache-Control"] = "no-store"
        code = meet.join_code(admin(session, authorization))
        url = f"{_origin(request)}/box#kod={code}"
        return drift.Joining(code=code, url=url).model_dump(mode="json")

    @routes.get("/connect.svg")
    def connect_qr(
        request: Request, session: SessionCookie = None, authorization: Authorization = None
    ) -> Response:
        code = meet.join_code(admin(session, authorization))
        picture = io.BytesIO()
        segno.make(f"{_origin(request)}/box#kod={code}", error="m").save(
            picture, kind="svg", scale=6, border=2, dark="#0e1114", light="#ffffff"
        )
        return Response(
            picture.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"}
        )

    @routes.get("/events")
    async def events(
        request: Request, session: SessionCookie = None, authorization: Authorization = None
    ) -> StreamingResponse:
        """The meet's Drift events as they happen, from now on."""
        run_id = await run_in_threadpool(admin, session, authorization)
        start = len((await run_in_threadpool(meet.state, run_id)).history)

        async def stream() -> AsyncIterator[str]:
            seen, quiet, waited = start, 0.0, 0.0
            yield ": hubben lyssnar\n\n"
            while waited < STREAM_SECONDS:
                await asyncio.sleep(STREAM_INTERVAL)
                waited += STREAM_INTERVAL
                quiet += STREAM_INTERVAL
                if await request.is_disconnected():
                    return
                try:
                    history = (await run_in_threadpool(meet.state, run_id)).history
                except MissingRun:
                    yield "event: gone\ndata: {}\n\n"
                    return
                for event in history[seen:]:
                    quiet = 0.0
                    yield f"event: drift\ndata: {event.model_dump_json()}\n\n"
                seen = len(history)
                if quiet >= HEARTBEAT_SECONDS:
                    quiet = 0.0
                    yield ": vänta\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return routes


def _origin(request: Request) -> str:
    """The address boxes reach the hub at, as the browser that asked sees it."""
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}"
