"""The station protocol over HTTP (contracts/station.py), on a Provbanan run.

For clients that draw their own screen: TKL, the TMBox app and the dispatcher's views. A client
connects with the run's code and waits under Väntar until the dispatcher approves it for one or
more places on Provbanan. It then fetches its key once and sends it as Authorization: Bearer
for the snapshot, the commands and the event stream. The key never travels in an address or a
body, and is never written to a log (H31).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Header, HTTPException, Path, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from contracts import station
from contracts.common import Id
from contracts.reasons import TEXT_SV, Reason
from drift.store import MissingRun, NotApproved, RunLimit, UnknownClient
from hub.stores import AnyRun

STREAM_SECONDS = 300
STREAM_INTERVAL = 0.5
HEARTBEAT_SECONDS = 15

Authorization = Annotated[str | None, Header(max_length=200)]
PlaceId = Annotated[Id, Path()]


def _key(authorization: str | None) -> str:
    scheme, _, key = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not 20 <= len(key) <= 120:
        raise HTTPException(401, "Nyckeln saknas.")
    return key


def _error(error: Exception) -> NoReturn:
    if isinstance(error, RunLimit):
        raise HTTPException(429, "Gränsen för provkörningen har nåtts.") from error
    if isinstance(error, NotApproved):
        raise HTTPException(403, TEXT_SV[Reason.NOT_APPROVED]) from error
    if isinstance(error, KeyError):
        raise HTTPException(404, "Driftplatsen finns inte, eller är en hållplats.") from error
    raise HTTPException(401, "Nyckeln gäller inte, eller provkörningen har gått ut.") from error


def router(store: AnyRun) -> APIRouter:
    routes = APIRouter(prefix="/api/station/1")
    failures = (UnknownClient, NotApproved, MissingRun, RunLimit, KeyError)

    @routes.post("/connect", status_code=201)
    def connect(request: station.ConnectRequest, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            return store.connect(request).model_dump(mode="json")
        except MissingRun as error:
            raise HTTPException(
                404, "Koden finns inte, eller provkörningen har gått ut."
            ) from error
        except RunLimit as error:
            _error(error)

    @routes.get("/connect/{client_id}")
    def connection(client_id: PlaceId, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            return store.connection(client_id).model_dump(mode="json")
        except UnknownClient as error:
            raise HTTPException(404, "Klienten finns inte.") from error

    @routes.get("/places/{place}")
    def place_snapshot(
        place: PlaceId, response: Response, authorization: Authorization = None
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            return store.place_snapshot(_key(authorization), place).model_dump(mode="json")
        except failures as error:
            _error(error)

    @routes.post("/commands")
    def command(
        command: station.Command, response: Response, authorization: Authorization = None
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            return store.station_command(_key(authorization), command).model_dump(mode="json")
        except failures as error:
            _error(error)

    @routes.get("/places/{place}/events")
    async def events(
        place: PlaceId, request: Request, authorization: Authorization = None
    ) -> StreamingResponse:
        """A hint that the place changed, never the change itself: fetch the snapshot."""
        key = _key(authorization)
        try:
            first = await run_in_threadpool(store.place_revision, key, place)
        except failures as error:
            _error(error)

        def changed(revision: int) -> str:
            return f'event: changed\ndata: {{"place_revision": {revision}}}\n\n'

        async def hints() -> AsyncIterator[str]:
            last = first
            yield changed(first)
            quiet = waited = 0.0
            while waited < STREAM_SECONDS:
                await asyncio.sleep(STREAM_INTERVAL)
                waited += STREAM_INTERVAL
                quiet += STREAM_INTERVAL
                if await request.is_disconnected():
                    return
                try:
                    current = await run_in_threadpool(store.place_revision, key, place)
                except failures:
                    yield "event: gone\ndata: {}\n\n"
                    return
                if current != last:
                    last, quiet = current, 0.0
                    yield changed(current)
                elif quiet >= HEARTBEAT_SECONDS:
                    quiet = 0.0
                    yield ": vänta\n\n"

        return StreamingResponse(
            hints(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return routes
