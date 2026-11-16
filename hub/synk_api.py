"""Synkprotokollet i hubben (trainmeet.sync/1, steg 5 del 2).

In the cloud: Koppla en Pi gives a code for a meet (SYNK-02); the Pi links with it and then
follows the meet's versions with long-poll, with its own key (SYNK-10, SYNK-13). On the Pi:
Den här hubben → Molnet, where the administrator gives the cloud's address and the code, and
sees the meets the Pi follows. The key is never shown or logged.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Header, HTTPException, Query, Response
from fastapi.concurrency import run_in_threadpool

from contracts import drift
from contracts.sync import (
    HEADER,
    PROTOCOL,
    CloudLinkChange,
    Hello,
    Link,
    LinkRequest,
    RunAck,
    RunEvents,
    VersionList,
)
from drift.engine import Refused
from hub.hubben import Authorization, SessionCookie, require_admin
from hub.local import LocalLogin
from hub.running import Running
from planering.store import Planning, PlanningError
from synk.follower import Follower
from synk.link import LinkError, Links
from synk.store import SyncError, Versions

MAX_WAIT = 25.0
POLL = 0.5

SyncHeader = Annotated[str | None, Header(alias=HEADER, max_length=60)]


def _fail(error: LinkError | SyncError | PlanningError) -> NoReturn:
    raise HTTPException(error.status, str(error)) from error


def _protocol(spoken: str | None) -> None:
    if spoken is not None and spoken != PROTOCOL:
        raise HTTPException(426, f"Hubben talar {PROTOCOL}.")


def _key(authorization: str | None) -> str:
    scheme, _, key = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not key:
        raise HTTPException(401, "Pi:ns nyckel saknas.")
    return key


def mark(listed: list[dict[str, Any]]) -> str:
    """The version list's mark: changes when a version is published or withdrawn."""
    return hashlib.sha256(repr(listed).encode()).hexdigest()[:24]


def router(
    plans: Planning,
    versions: Versions,
    links: Links,
    follower: Follower,
    running: Running,
    login: LocalLogin,
    hello: Callable[[], Hello],
) -> APIRouter:
    routes = APIRouter()

    def admin(session: str | None, authorization: str | None) -> None:
        require_admin(login, session, authorization)

    def known(meet: str, key: str) -> None:
        if links.follower(meet, key, datetime.now(UTC)) is None:
            raise HTTPException(401, "Molnhubben känner inte den här Pi:n.")

    # --- In the cloud: Koppla en Pi (SYNK-02) ------------------------------------------------

    @routes.post("/api/sync/1/meets/{meet}/code", status_code=201)
    def code(
        meet: str,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Koppla en Pi: a six-digit code for the meet, for 15 minutes."""
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        try:
            plans.draft(meet)  # the meet's home is this hub
        except PlanningError as error:
            _fail(error)
        return links.new_code(meet, datetime.now(UTC)).model_dump(mode="json")

    @routes.get("/api/sync/1/meets/{meet}/followers")
    def followers(meet: str, response: Response) -> list[dict[str, Any]]:
        response.headers["Cache-Control"] = "no-store"
        return [f.model_dump(mode="json") for f in links.followers(meet)]

    @routes.post("/api/sync/1/meets/{meet}/followers/{hub_id}/revoke", status_code=204)
    def revoke(
        meet: str, hub_id: str, session: SessionCookie = None, authorization: Authorization = None
    ) -> None:
        """Koppla bort en Pi: its key no longer works here."""
        admin(session, authorization)
        if not links.revoke(meet, hub_id):
            raise HTTPException(404, "Pi:n följer inte träffen.")

    @routes.post("/api/sync/1/link")
    def link(request: LinkRequest, response: Response) -> dict[str, Any]:
        """A Pi gives its code and gets the meet and a key of its own."""
        response.headers["Cache-Control"] = "no-store"
        if PROTOCOL not in request.hello.protocols:
            raise HTTPException(426, f"Hubben talar {PROTOCOL}.")
        try:
            meet, key = links.redeem(request.code, request.hello, datetime.now(UTC))
            name = plans.draft(meet).meet.name
        except (LinkError, PlanningError) as error:
            _fail(error)
        return Link(meet=meet, meet_name=name, key=key, hello=hello()).model_dump(mode="json")

    @routes.get("/api/sync/1/meets/{meet}/versions")
    async def listed(
        meet: str,
        response: Response,
        known_mark: Annotated[str, Query(alias="known", max_length=64)] = "",
        wait: Annotated[float, Query(ge=0, le=MAX_WAIT)] = 0,
        authorization: Authorization = None,
        spoken: SyncHeader = None,
    ) -> dict[str, Any]:
        """The meet's versions, as soon as they differ from what the Pi knows (long-poll)."""
        response.headers["Cache-Control"] = "no-store"
        _protocol(spoken)
        await run_in_threadpool(known, meet, _key(authorization))
        until = time.monotonic() + wait
        while True:
            found = [
                v.model_dump(mode="json") for v in await run_in_threadpool(versions.versions, meet)
            ]
            now_mark = mark(found)
            if now_mark != known_mark or time.monotonic() >= until:
                break
            await asyncio.sleep(POLL)
        try:
            name = (await run_in_threadpool(plans.draft, meet)).meet.name
        except PlanningError as error:
            _fail(error)
        return VersionList.model_validate(
            {"meet": meet, "meet_name": name, "versions": found, "mark": now_mark}
        ).model_dump(mode="json")

    @routes.get("/api/sync/1/meets/{meet}/versions/{number}")
    def version(
        meet: str,
        number: int,
        authorization: Authorization = None,
        spoken: SyncHeader = None,
    ) -> Response:
        """A version as the bytes it was published as: the follower checks the checksum."""
        _protocol(spoken)
        known(meet, _key(authorization))
        try:
            kept, data = versions.stored(meet, number)
        except SyncError as error:
            _fail(error)
        return Response(
            data,
            media_type="application/json",
            headers={"Cache-Control": "no-store", "X-Checksum": kept.checksum},
        )

    # --- Under träffen: molnet följer Pi:n live (SYNK-04, SYNK-14, DRIFT-12) -------------------

    @routes.post("/api/sync/1/meets/{meet}/runs")
    def runs(
        meet: str,
        sent: RunEvents,
        response: Response,
        authorization: Authorization = None,
        spoken: SyncHeader = None,
    ) -> dict[str, Any]:
        """The Pi's drift events for the run it leads, kept as they came. A driftändring
        becomes a proposal in Planering here, and the answers go back down (4.4)."""
        response.headers["Cache-Control"] = "no-store"
        _protocol(spoken)
        pi = links.follower(meet, _key(authorization), datetime.now(UTC))
        if pi is None:
            raise HTTPException(401, "Molnhubben känner inte den här Pi:n.")
        try:
            kept, _ = versions.stored(meet, sent.version)
        except SyncError as error:
            _fail(error)
        if kept.checksum != sent.package:
            raise HTTPException(409, "Pi:n kör en annan version än den molnhubben har.")
        store = running.mirror(meet, sent.version)
        try:
            ack, taken = store.receive(sent.run, pi.hub_name, sent.events)
        except Refused as error:
            raise HTTPException(409, "Molnhubben kör själv den körningen.") from error
        for event in taken:
            if event.kind == drift.EventKind.CHANGE_MADE:
                made = drift.ChangeMade.model_validate(event.data)
                plans.propose(meet, sent.version, made.change_id, made.change, made.train_number)
            elif event.kind == drift.EventKind.CHANGE_DROPPED:
                plans.withdraw(meet, drift.ChangeRef.model_validate(event.data).change_id)
        if running.meet == meet:
            running.follow(meet, sent.version)
        return RunAck(run=sent.run, ack=ack, answers=plans.answers(meet)).model_dump(mode="json")

    # --- On the Pi: Den här hubben → Molnet ---------------------------------------------------

    def clouds() -> list[dict[str, Any]]:
        counts = {meet: len(found) for meet, found in versions.meets().items()}
        return [c.model_dump(mode="json") for c in links.clouds(counts)]

    @routes.get("/api/hub/cloud")
    def cloud(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> list[dict[str, Any]]:
        """The meets the Pi follows in the cloud, and how the synk goes."""
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        return clouds()

    @routes.post("/api/hub/cloud")
    def connect(
        change: CloudLinkChange,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> list[dict[str, Any]]:
        """Koppla till molnet: the cloud's address and the code from it."""
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        try:
            follower.link(change.address, change.code)
        except LinkError as error:
            _fail(error)
        return clouds()

    @routes.post("/api/hub/cloud/{meet}/disconnect")
    def disconnect(
        meet: str,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> list[dict[str, Any]]:
        """Koppla bort: the Pi no longer follows the meet. Its versions stay."""
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        if not links.forget(meet):
            raise HTTPException(404, "Pi:n följer inte den träffen.")
        return clouds()

    return routes
