"""Träffens skärmar in the browser: a TV joins with the meet's code, waits under Väntar, and
shows the view the dispatcher gives it in Klienter, drawn for 1920 × 1080. The clock needs only
the time; the views that draw the line get the meet as it runs with the picture, and the
package once from /api/screen/package (SKARM-09).

The page is the app apps/skarmar, served at /skarm by hub/web.py (SKARM-14). It keeps its key in
sessionStorage and sends it as Authorization: Bearer; it is never in an address or a log.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Response

from contracts import screen, station
from drift.engine import Drift, model_time, now_utc
from drift.now import now
from drift.store import MissingRun, RunLimit, UnknownClient
from hub.stores import AnyRun

Authorization = Annotated[str | None, Header(max_length=200)]
CLOCKS = {screen.ScreenView.CLOCK.value, screen.ScreenView.CLOCK_DIGITAL.value}


def package_key(drift: Drift) -> str:
    """Which package a screen draws on: the version and where each driftändring stands."""
    changes = ",".join(f"{c.id}:{c.status}" for c in drift.changes.values())
    return hashlib.sha256(f"{drift.version}|{changes}".encode()).hexdigest()[:16]


def router(runs: AnyRun) -> APIRouter:
    routes = APIRouter()

    @routes.post("/api/screen/session", status_code=201)
    def login(request: screen.ScreenLogin, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            client_id, key = runs.screen_login(request.name, request.code)
        except MissingRun as error:
            raise HTTPException(404, "Koden finns inte, eller träffen har bytts.") from error
        except RunLimit as error:
            raise HTTPException(429, "Träffen har redan sina skärmar.") from error
        return screen.ScreenSession(client_id=client_id, session_key=key).model_dump(mode="json")

    def shown(authorization: str | None) -> tuple[str, str | None, Drift]:
        scheme, _, key = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not 20 <= len(key) <= 120:
            raise HTTPException(401, "Nyckeln saknas.")
        try:
            return runs.screen_picture(key)
        except UnknownClient as error:
            raise HTTPException(401, "Skärmen finns inte längre. Anslut igen.") from error

    @routes.get("/api/screen/picture")
    def picture(response: Response, authorization: Authorization = None) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        name, view, drift = shown(authorization)
        at = now_utc()
        drawn = view is not None and view not in CLOCKS
        seconds = drift.clock.at(at)
        return screen.ScreenPicture(
            name=name,
            view=screen.ScreenView(view) if view else None,
            meet=drift.package.meet.name,
            traffic_day=drift.traffic_day,
            clock=station.Clock(
                time=model_time(seconds),
                seconds=int(seconds),
                running=drift.clock.running,
                speed=drift.clock.speed,
                game_day=drift.game_day,
            ),
            now=now(drift, at) if drawn else None,
            package=package_key(drift) if drawn else None,
        ).model_dump(mode="json")

    @routes.get("/api/screen/package")
    def package(response: Response, authorization: Authorization = None) -> dict[str, Any]:
        """The package the views draw on: the version with the driftändringar on top. Fetched
        once, and again when the picture's key changes."""
        response.headers["Cache-Control"] = "no-store"
        _, _, drift = shown(authorization)
        return drift.package.model_dump(mode="json")

    return routes
