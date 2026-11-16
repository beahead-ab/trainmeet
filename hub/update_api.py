"""Uppdateringen (SYNK-23, KLAR-21 för hubben): på knapptryck under kugghjulet, aldrig under en
träff.

On a Pi installed with deploy/pi the hub may start the update service, and only that one
(a polkit rule). The service fetches the latest Pi package, tries it and goes back to the one
before if the hub does not answer; it writes how it goes to a file the hub reads. The hub in the
cloud is updated by its deploy and says so.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from contracts import hub
from drift.store import MissingRun
from hub.build_info import BuildInfo
from hub.hubben import Authorization, SessionCookie, require_admin
from hub.local import LocalLogin
from hub.network_api import _same_site
from hub.running import Running

UNIT = "trainmeet-update.service"
NOT_HERE = "Hubben i molnet uppdateras när en ändring läggs ut. Uppdateringen här gäller en Pi."


def status_file() -> Path | None:
    configured = os.environ.get("TRAINMEET_UPDATE_STATUS", "").strip()
    return Path(configured) if configured else None


def start_service() -> None:
    """The update service, through systemd and the polkit rule; it runs on its own."""
    subprocess.run(
        ["systemctl", "start", "--no-block", UNIT], check=True, capture_output=True, timeout=10
    )


def meet_running(running: Running) -> bool:
    """A meet is on while its clock runs: then nothing is updated."""
    store = running.store
    try:
        return bool(store.state(store.current()).clock.running)
    except MissingRun:
        return False


def router(
    login: LocalLogin,
    running: Running,
    info: Callable[[], BuildInfo],
    start: Callable[[], None] | None = None,
) -> APIRouter:
    routes = APIRouter(prefix="/api/hub/update")

    def read() -> dict[str, Any]:
        where = status_file()
        build = info().commit
        if where is None:
            return hub.UpdateStatus(available=False, reason=NOT_HERE, build=build).model_dump(
                mode="json"
            )
        try:
            said = json.loads(where.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            said = {}
        state = said.get("status") if said.get("status") in STATES else None
        return hub.UpdateStatus(
            available=True,
            build=build,
            state=state,
            message=str(said["message"])[:300] if said.get("message") else None,
            at=said.get("at") or None,
            meet_running=meet_running(running),
        ).model_dump(mode="json")

    @routes.get("")
    def status(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        require_admin(login, session, authorization)
        return read()

    @routes.post("")
    async def update(
        request: Request,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
        marked: str | None = Header(default=None, alias="X-TrainMeet-Network"),
    ) -> dict[str, Any]:
        """Sök efter och installera: refused while a meet is on, and on a hub that cannot."""
        response.headers["Cache-Control"] = "no-store"
        await run_in_threadpool(require_admin, login, session, authorization)
        if marked != "1" or not _same_site(request):
            raise HTTPException(403, "Uppdatera från hubbens egen sida.")
        if status_file() is None:
            raise HTTPException(409, NOT_HERE)
        if await run_in_threadpool(meet_running, running):
            raise HTTPException(
                409, "En träff pågår. Uppdatera när klockan står still och träffen är slut."
            )
        try:
            await run_in_threadpool(start or start_service)
        except (OSError, subprocess.SubprocessError) as error:
            raise HTTPException(503, "Uppdateringen gick inte att starta på Pi:n.") from error
        return await run_in_threadpool(read)

    return routes


STATES = {"checking", "downloading", "installing", "restarting", "done", "current", "failed"}
