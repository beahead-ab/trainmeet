"""The hub's web program. Start it with: uv run uvicorn hub.app:app --reload"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from typing import Any, Final

from fastapi import FastAPI, Response
from fastapi.responses import PlainTextResponse

from contracts import hub
from contracts.sync import Hello
from drift.store import MissingRun, PreviewStore
from hub import (
    build_info,
    drift_api,
    hubben,
    planering_api,
    provbanan,
    screen_web,
    station_api,
    synk_api,
    tmbox_web,
    web,
)
from hub.local import LocalLogin
from hub.running import Running
from hub.stores import AnyRun
from planering.store import Planning
from synk.follower import Call, Follower, urllib_call
from synk.link import Links
from synk.store import Versions

# The automation takes a step about once a second while the hub runs (F14).
TICK_SECONDS: Final = 1.0
LOGGER = logging.getLogger("hub.automatik")


def tick_once(running: Running) -> None:
    """One round of the automation for the hub's meet, if one is started, and a new version
    with only små rättelser taken at once (F5)."""
    store = running.store
    try:
        store.tick(store.current())
        running.take_small_corrections()
    except MissingRun:
        return


def _ticker(running: Running, stop: Event) -> None:
    while not stop.wait(TICK_SECONDS):
        try:
            tick_once(running)
        except Exception:
            LOGGER.exception("Automatiken kunde inte ta sitt steg")


def create_app(
    info: build_info.BuildInfo | None = None,
    *,
    preview_db: Path | None = None,
    web_root: Path | None = None,
    sync_call: Call = urllib_call,
) -> FastAPI:
    info = info if info is not None else build_info.from_env()
    preview_path = provbanan.database_path(preview_db)
    data_dir = preview_path.parent
    login = LocalLogin(data_dir / "hubben.sqlite3", info.hub_name)
    package = provbanan.package()
    # Provbanan's runs per browser: the automation starts off, since only the hub's meet
    # is ticked (F14).
    preview = PreviewStore(
        preview_path, package, package_key=provbanan.package_key(), automation=False
    )
    plans = Planning(data_dir / "planering.sqlite3")
    # Synk keeps the versions, in Planering's file (SYNK-20).
    versions = Versions(data_dir / "planering.sqlite3")
    links = Links(data_dir / "planering.sqlite3")
    # The hub's own meet: Provbanan or a published version, each in a file of its own.
    running = Running(
        data_dir, package, provbanan.package_key(), plans, versions, hub_version=info.version
    )

    def current() -> build_info.BuildInfo:
        return replace(info, hub_name=login.state().name)

    def hello() -> Hello:
        return Hello(hub_id=links.hub_id(), hub_name=login.state().name, software=info.version)

    # The Pi follows its meets in the cloud (SYNK-10): it always calls out (SYNK-13).
    follower = Follower(links, versions, hello, sync_call)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop = Event()
        thread = Thread(target=_ticker, args=(running, stop), name="automatiken", daemon=True)
        thread.start()
        synk = Thread(target=follower.run, args=(stop,), name="synken", daemon=True)
        synk.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=5)

    # The interactive API pages are off: they load scripts from another site. The contracts
    # get their own readable pages in step 1, part 2.
    app = FastAPI(
        title=build_info.PRODUCT,
        version=info.version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.running = running
    app.state.follower = follower
    app.include_router(hubben.router(login))
    app.include_router(provbanan.router(preview))
    app.include_router(drift_api.router(running, login))
    app.include_router(planering_api.router(plans, versions, links, login))
    app.include_router(synk_api.router(plans, versions, links, follower, login, hello))
    runs = AnyRun(lambda: running.store, lambda: preview)
    app.include_router(tmbox_web.router(runs))
    app.include_router(station_api.router(runs))
    app.include_router(screen_web.router(runs))

    # The pages, built in React under apps/ (H62, GRUND-36).
    app.include_router(web.router(web_root))

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok"

    @app.get("/api/version")
    def api_version(response: Response) -> dict[str, Any]:
        """What runs, with the name the hub was given at first start."""
        response.headers["Cache-Control"] = "no-store"
        return hub.Version.model_validate(current().as_dict()).model_dump(mode="json")

    return app


app = create_app()
