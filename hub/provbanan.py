"""HTTP entry points for the isolated Provbanan preview on the Hub."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from contracts import drift, station
from contracts.meet import MeetPackage
from contracts.reasons import TEXT_SV
from drift.engine import VERSION, Drift, Refused, now_utc
from drift.store import RUN_LIFETIME, MissingRun, PreviewStore, RunLimit
from hub import page
from hub.build_info import BuildInfo

COOKIE = "trainmeet_provbanan"
RunCookie = Annotated[str | None, Cookie(alias=COOKIE, max_length=48)]


def _error(error: MissingRun | RunLimit | Refused) -> NoReturn:
    if isinstance(error, Refused):
        raise HTTPException(409, TEXT_SV[error.reason]) from error
    if isinstance(error, RunLimit):
        raise HTTPException(429, "Gränsen för provkörningar eller åtgärder har nåtts.") from error
    raise HTTPException(404, "Starta en provkörning först.") from error


def router(info: BuildInfo, db_path: Path | None = None) -> APIRouter:
    path = (
        db_path
        if db_path is not None
        else Path(
            os.environ.get("TRAINMEET_PREVIEW_DB")
            or (Path(tempfile.gettempdir()) / "trainmeet-provbanan.sqlite3")
        )
    )
    fixture = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    store = PreviewStore(path, MeetPackage.model_validate_json(fixture))
    routes = APIRouter()

    def snapshot(
        response: Response,
        run_id: str | None,
        operation: Callable[[str], Drift],
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            if not run_id:
                raise MissingRun()
            engine = operation(run_id)
        except (MissingRun, RunLimit, Refused) as error:
            _error(error)
        return engine.preview(now_utc())

    @routes.get("/provbanan", response_class=HTMLResponse)
    def preview() -> str:
        return page.render_preview(info)

    @routes.get("/api/provbanan")
    def state(response: Response, run: RunCookie = None) -> dict[str, Any]:
        return snapshot(response, run, store.state)

    @routes.post("/api/provbanan/start", status_code=201)
    def start(control: drift.StartMeet, request: Request, response: Response) -> dict[str, Any]:
        day = store.package.meet.traffic_week.start_weekday
        if (
            control.version != VERSION
            or control.game_day != 1
            or control.traffic_day
            not in (
                None,
                day,
            )
        ):
            raise HTTPException(422, "Provbanan kör version 1, speldag 1 och måndag.")
        try:
            run = store.start()
        except RunLimit as error:
            _error(error)
        response.set_cookie(
            COOKIE,
            run,
            path="/api/provbanan",
            max_age=int(RUN_LIFETIME.total_seconds()),
            secure=request.url.scheme == "https",
            httponly=True,
            samesite="strict",
        )
        return snapshot(response, run, store.state)

    @routes.post("/api/provbanan/clock")
    def clock(
        control: drift.ClockControl, response: Response, run: RunCookie = None
    ) -> dict[str, Any]:
        return snapshot(response, run, lambda run_id: store.clock(run_id, control))

    @routes.post("/api/provbanan/command")
    def command(
        command: station.Command,
        response: Response,
        run: RunCookie = None,
    ) -> dict[str, Any]:
        return snapshot(response, run, lambda run_id: store.command(run_id, command))

    return routes
