"""The station protocol over HTTP (contracts/station.py), on a Provbanan run.

For clients that draw their own screen: TKL, the TMBox app and the dispatcher's views. A client
connects with the run's code and waits under Väntar until the dispatcher approves it for one or
more places on Provbanan. It then fetches its key once and sends it as Authorization: Bearer
for the snapshot, the commands and the event stream. The key never travels in an address or a
body, and is never written to a log (H31).

Outside the meet's network the same calls go to the cloud hub's relay, /relay/{hub}/... (SYNK-11):
the cloud puts each call in a queue for the hub, which fetches it on its own connection and
answers it here, in relayed(). Between the cloud and the hub the key travels only as its hash.
The event stream through the relay asks the hub to wait for a change, one round at a time.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from secrets import token_hex
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Header, HTTPException, Path, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from contracts import station
from contracts.common import Id
from contracts.reasons import TEXT_SV, Reason
from contracts.sync import RELAY_WAIT, RelayAnswer, RelayCall, RelayKind
from drift.store import KeyHash, MissingRun, NotApproved, RunLimit, UnknownClient, key_hash
from hub.stores import AnyRun
from synk.relay import Relay, RelayError

STREAM_SECONDS = 300
STREAM_INTERVAL = 0.5
HEARTBEAT_SECONDS = 15

Authorization = Annotated[str | None, Header(max_length=200)]
PlaceId = Annotated[Id, Path()]
HubId = Annotated[Id, Path()]


def _key(authorization: str | None) -> str:
    scheme, _, key = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not 20 <= len(key) <= 120:
        raise HTTPException(401, "Nyckeln saknas.")
    return key


FAILURES = (UnknownClient, NotApproved, MissingRun, RunLimit, KeyError)
NO_CODE = "Koden finns inte, eller provkörningen har gått ut."
NO_CLIENT = "Klienten finns inte."


def _failure(error: Exception) -> tuple[int, str]:
    if isinstance(error, RunLimit):
        return 429, "Gränsen för provkörningen har nåtts."
    if isinstance(error, NotApproved):
        return 403, TEXT_SV[Reason.NOT_APPROVED]
    if isinstance(error, KeyError):
        return 404, "Driftplatsen finns inte, eller är en hållplats."
    return 401, "Nyckeln gäller inte, eller provkörningen har gått ut."


def _error(error: Exception) -> NoReturn:
    raise HTTPException(*_failure(error)) from error


def router(store: AnyRun, relay: Callable[[], str | None] = lambda: None) -> APIRouter:
    """The station protocol on this hub. relay: the address of the cloud's relay to this hub,
    which the client is told when it connects (ConnectReply.relay)."""
    routes = APIRouter(prefix="/api/station/1")
    failures = FAILURES

    @routes.post("/connect", status_code=201)
    def connect(request: station.ConnectRequest, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            reply = store.connect(request)
        except MissingRun as error:
            raise HTTPException(404, NO_CODE) from error
        except RunLimit as error:
            _error(error)
        return reply.model_copy(update={"relay": relay()}).model_dump(mode="json")

    @routes.get("/connect/{client_id}")
    def connection(client_id: PlaceId, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            reply = store.connection(client_id)
        except UnknownClient as error:
            raise HTTPException(404, NO_CLIENT) from error
        return reply.model_copy(update={"relay": relay()}).model_dump(mode="json")

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

    @routes.put("/push", status_code=204)
    def push(token: station.PushToken, authorization: Authorization = None) -> Response:
        """The phone's address for push (F20). Kept only here, on the hub that leads."""
        try:
            store.set_push(_key(authorization), token)
        except failures as error:
            _error(error)
        return Response(status_code=204)

    @routes.delete("/push", status_code=204)
    def push_off(authorization: Authorization = None) -> Response:
        try:
            store.set_push(_key(authorization), None)
        except failures as error:
            _error(error)
        return Response(status_code=204)

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


# --- Reläet (SYNK-11) ---------------------------------------------------------------------


def relayed(store: AnyRun, call: RelayCall, relay: Callable[[], str | None]) -> RelayAnswer:
    """A call that came through the cloud's relay, answered as the same call here would be."""

    def answer(status: int, detail: str | None = None, **given: Any) -> RelayAnswer:
        return RelayAnswer(id=call.id, status=status, detail=detail, **given)

    key = KeyHash(call.key_hash) if call.key_hash else None
    try:
        if call.kind == RelayKind.CONNECT and call.connect is not None:
            try:
                reply = store.connect(call.connect)
            except MissingRun:
                return answer(404, NO_CODE)
            return answer(201, connected=reply.model_copy(update={"relay": relay()}))
        if call.kind == RelayKind.CONNECTION and call.client_id is not None:
            try:
                reply = store.connection(call.client_id)
            except UnknownClient:
                return answer(404, NO_CLIENT)
            return answer(200, connected=reply.model_copy(update={"relay": relay()}))
        if key is None:
            return answer(401, "Nyckeln saknas.")
        if call.kind == RelayKind.SNAPSHOT and call.place is not None:
            return answer(200, snapshot=store.place_snapshot(key, call.place))
        if call.kind == RelayKind.COMMAND and call.command is not None:
            return answer(200, reply=store.station_command(key, call.command))
        if call.kind == RelayKind.PUSH:
            store.set_push(key, call.push)
            return answer(204)
        if call.kind == RelayKind.REVISION and call.place is not None:
            deadline = time.monotonic() + call.wait
            while True:
                revision = store.place_revision(key, call.place)
                if call.known != revision or time.monotonic() >= deadline:
                    return answer(200, revision=revision)
                time.sleep(STREAM_INTERVAL)
    except FAILURES as error:
        return answer(*_failure(error))
    return answer(422, "Anropet genom reläet saknar en del.")


def relay_router(relay: Relay) -> APIRouter:
    """In the cloud: the station protocol to a hub that is linked here, which fetches the calls
    itself. The cloud keeps nothing of them (SYNK-22)."""
    routes = APIRouter(prefix="/relay/{hub_id}/api/station/1")

    async def ask(hub_id: str, kind: RelayKind, **given: Any) -> RelayAnswer:
        call = RelayCall(id=token_hex(12), kind=kind, **given)
        try:
            answer = await relay.ask(hub_id, call)
        except RelayError as error:
            raise HTTPException(error.status, str(error)) from error
        if answer.status >= 300:
            raise HTTPException(answer.status, answer.detail or "Träffens hubb sa nej.")
        return answer

    def given(value: Any) -> dict[str, Any]:
        if value is None:
            raise HTTPException(502, "Träffens hubb svarade inte som väntat.")
        result: dict[str, Any] = value.model_dump(mode="json")
        return result

    @routes.post("/connect", status_code=201)
    async def connect(
        hub_id: HubId, request: station.ConnectRequest, response: Response
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return given((await ask(hub_id, RelayKind.CONNECT, connect=request)).connected)

    @routes.get("/connect/{client_id}")
    async def connection(hub_id: HubId, client_id: PlaceId, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return given((await ask(hub_id, RelayKind.CONNECTION, client_id=client_id)).connected)

    @routes.get("/places/{place}")
    async def place_snapshot(
        hub_id: HubId, place: PlaceId, response: Response, authorization: Authorization = None
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        hashed = key_hash(_key(authorization))
        return given((await ask(hub_id, RelayKind.SNAPSHOT, key_hash=hashed, place=place)).snapshot)

    @routes.post("/commands")
    async def command(
        hub_id: HubId,
        command: station.Command,
        response: Response,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        hashed = key_hash(_key(authorization))
        return given((await ask(hub_id, RelayKind.COMMAND, key_hash=hashed, command=command)).reply)

    @routes.put("/push", status_code=204)
    async def push(
        hub_id: HubId, token: station.PushToken, authorization: Authorization = None
    ) -> Response:
        hashed = key_hash(_key(authorization))
        await ask(hub_id, RelayKind.PUSH, key_hash=hashed, push=token)
        return Response(status_code=204)

    @routes.delete("/push", status_code=204)
    async def push_off(hub_id: HubId, authorization: Authorization = None) -> Response:
        await ask(hub_id, RelayKind.PUSH, key_hash=key_hash(_key(authorization)))
        return Response(status_code=204)

    @routes.get("/places/{place}/events")
    async def events(
        hub_id: HubId, place: PlaceId, request: Request, authorization: Authorization = None
    ) -> StreamingResponse:
        """As on the hub: a hint that the place changed. Each round the hub waits for a change
        for up to 20 seconds before it answers."""
        hashed = key_hash(_key(authorization))
        first = (await ask(hub_id, RelayKind.REVISION, key_hash=hashed, place=place)).revision

        def changed(revision: int | None) -> str:
            return f'event: changed\ndata: {{"place_revision": {revision or 0}}}\n\n'

        async def hints() -> AsyncIterator[str]:
            last = first
            yield changed(first)
            began = time.monotonic()
            while time.monotonic() - began < STREAM_SECONDS:
                if await request.is_disconnected():
                    return
                try:
                    answer = await ask(
                        hub_id,
                        RelayKind.REVISION,
                        key_hash=hashed,
                        place=place,
                        known=last or 0,
                        wait=RELAY_WAIT,
                    )
                except HTTPException:
                    yield "event: gone\ndata: {}\n\n"
                    return
                if answer.revision != last:
                    last = answer.revision
                    yield changed(last)
                else:
                    yield ": vänta\n\n"

        return StreamingResponse(
            hints(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return routes
