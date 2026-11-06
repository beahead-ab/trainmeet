"""TMBox web on the test hub: the 16×2 box in the browser, joined to a Provbanan run.

As the terminal contract says (contracts/terminal.py): each tab logs in with the run's code
and becomes its own box under Väntar. The dispatcher assigns it a place on Provbanan. The tab
keeps its session key in its own storage and sends it as Authorization: Bearer for the
picture, the keys and the event stream; it never travels in an address or a log.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, StreamingResponse

from contracts import terminal
from drift.store import MissingRun, PreviewStore, RunLimit, UnknownBox
from hub import page
from hub.build_info import BuildInfo

STREAM_SECONDS = 300
STREAM_INTERVAL = 0.5
HEARTBEAT_SECONDS = 15

Authorization = Annotated[str | None, Header(max_length=200)]


def _key(authorization: str | None) -> str:
    scheme, _, key = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not 20 <= len(key) <= 120:
        raise HTTPException(401, "Boxen är inte inloggad.")
    return key


def _box_error(error: UnknownBox | MissingRun | RunLimit) -> NoReturn:
    if isinstance(error, RunLimit):
        raise HTTPException(429, "Gränsen för provkörningen har nåtts.") from error
    raise HTTPException(401, "Boxen är inte inloggad, eller provkörningen har gått ut.") from error


def _changed(old: dict[str, Any], new: dict[str, Any]) -> bool:
    fields = ("lines", "view_token", "attention", "keys", "status")
    return any(old.get(name) != new.get(name) for name in fields)


def router(store: PreviewStore, info: BuildInfo) -> APIRouter:
    routes = APIRouter()

    @routes.get("/provbanan/box", response_class=HTMLResponse)
    def box_page() -> str:
        return page.render_box(info)

    @routes.post("/api/terminal/session", status_code=201)
    def session(login: terminal.WebLogin, response: Response) -> dict[str, str]:
        response.headers["Cache-Control"] = "no-store"
        try:
            client_id, key = store.login(login.name, login.code, login.display)
        except MissingRun as error:
            raise HTTPException(
                404, "Koden finns inte, eller provkörningen har gått ut."
            ) from error
        except RunLimit as error:
            raise HTTPException(429, "Provkörningen har redan så många boxar som går.") from error
        return terminal.WebSession(client_id=client_id, session_key=key).model_dump()

    @routes.get("/api/terminal/frame")
    def frame(response: Response, authorization: Authorization = None) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            return store.box_frame(_key(authorization))
        except (UnknownBox, MissingRun, RunLimit) as error:
            _box_error(error)

    @routes.post("/api/terminal/keys")
    def keys(
        press: terminal.KeyPress, response: Response, authorization: Authorization = None
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        body = press.model_dump(mode="json", exclude_none=True)
        try:
            return store.box_press(_key(authorization), body)
        except (UnknownBox, MissingRun, RunLimit) as error:
            _box_error(error)

    @routes.get("/api/terminal/events")
    async def stream(request: Request, authorization: Authorization = None) -> StreamingResponse:
        key = _key(authorization)
        try:
            first = await run_in_threadpool(store.box_frame, key)
        except (UnknownBox, MissingRun, RunLimit) as error:
            _box_error(error)

        def event(frame: dict[str, Any]) -> str:
            return "event: frame\ndata: " + json.dumps(frame, ensure_ascii=False) + "\n\n"

        async def frames() -> AsyncIterator[str]:
            # The stream ends after a while and the tab opens a new one, so a forgotten tab
            # never holds the hub for ever.
            last = first
            yield event(first)
            quiet = 0.0
            waited = 0.0
            while waited < STREAM_SECONDS:
                await asyncio.sleep(STREAM_INTERVAL)
                waited += STREAM_INTERVAL
                quiet += STREAM_INTERVAL
                if await request.is_disconnected():
                    return
                try:
                    current = await run_in_threadpool(store.box_frame, key)
                except (UnknownBox, MissingRun, RunLimit):
                    yield "event: gone\ndata: {}\n\n"
                    return
                if _changed(last, current):
                    last = current
                    quiet = 0.0
                    yield event(current)
                elif quiet >= HEARTBEAT_SECONDS:
                    quiet = 0.0
                    yield ": vänta\n\n"

        return StreamingResponse(
            frames(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return routes
