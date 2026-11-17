"""Uppdateringen (SYNK-19, SYNK-23): hubben visar Ny version finns och uppdateras på knapptryck
under kugghjulet, aldrig under en träff, och går tillbaka vid fel.

On a Pi installed with deploy/pi the hub may start the update service, and only that one
(a polkit rule). The service fetches the latest Pi package, tries it and goes back to the one
before if the hub does not answer; it writes how it goes to a file the hub reads. The hub in the
cloud is updated by its deploy and says so.

Ny version finns: the Pi reads which change the latest Pi package holds, a short file in the
release, at most once an hour and only while someone looks at the card. Without internet it
says nothing new; during a meet the hub needs no internet at all.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Final

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
# Where install.sh fetches the Pi package; the file BUILD there says which change it holds.
RELEASE: Final = "https://github.com/beahead-ab/trainmeet/releases/download/pi-senaste"
CHECK_EVERY: Final = 3600.0
CHECK_AGAIN: Final = 300.0
_CHANGE = re.compile(r"[0-9a-f]{7,40}")


def status_file() -> Path | None:
    configured = os.environ.get("TRAINMEET_UPDATE_STATUS", "").strip()
    return Path(configured) if configured else None


def latest_source() -> str:
    """The file that says the latest change: TRAINMEET_RELEASE as install.sh reads it."""
    release = os.environ.get("TRAINMEET_RELEASE", "").strip() or RELEASE
    return release.rstrip("/") + "/BUILD"


def fetch_latest(url: str) -> str | None:
    """The change the latest Pi package holds, or None when it cannot be seen."""
    try:
        with urllib.request.urlopen(url, timeout=5) as answer:
            said = answer.read(64).decode("ascii", "replace").strip()
    except (OSError, ValueError):
        return None
    return said if _CHANGE.fullmatch(said) else None


class Latest:
    """Ny version finns (SYNK-19): the latest change, read at most once an hour; after a miss,
    again after five minutes. Nothing is read until someone asks."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._lock = Lock()
        self._change: str | None = None
        self._checked: datetime | None = None
        self._next = 0.0

    def get(self) -> tuple[str | None, datetime | None]:
        with self._lock:
            if self.clock() < self._next:
                return self._change, self._checked
            # Claimed before the read, so two pages at once read it once.
            self._next = self.clock() + CHECK_AGAIN
        change = fetch_latest(latest_source())
        with self._lock:
            if change is not None:
                self._change, self._checked = change, datetime.now(UTC)
                self._next = self.clock() + CHECK_EVERY
            return self._change, self._checked


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
    latest: Latest | None = None,
) -> APIRouter:
    routes = APIRouter(prefix="/api/hub/update")
    newest = latest or Latest()

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
        change, checked = newest.get()
        return hub.UpdateStatus(
            available=True,
            build=build,
            state=state,
            message=str(said["message"])[:300] if said.get("message") else None,
            at=said.get("at") or None,
            meet_running=meet_running(running),
            latest=change,
            newer=bool(change and build and change != build),
            checked=checked,
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
