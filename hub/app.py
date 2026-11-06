"""The hub's web program. Start it with: uv run uvicorn hub.app:app --reload"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from contracts.common import Id
from drift.store import PreviewStore
from hub import (
    build_info,
    drift_api,
    drift_pages,
    hubben,
    page,
    planering_api,
    planering_pages,
    provbanan,
    screen_web,
    station_api,
    tmbox_web,
)
from hub.local import LocalLogin
from hub.running import Running
from hub.stores import AnyRun
from planering.store import Planning

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    info: build_info.BuildInfo | None = None,
    *,
    preview_db: Path | None = None,
) -> FastAPI:
    info = info if info is not None else build_info.from_env()
    preview_path = provbanan.database_path(preview_db)
    data_dir = preview_path.parent
    login = LocalLogin(data_dir / "hubben.sqlite3", info.hub_name)
    package = provbanan.package()
    preview = PreviewStore(preview_path, package, package_key=provbanan.package_key())
    plans = Planning(data_dir / "planering.sqlite3")
    # The hub's own meet: Provbanan or a published version, each in a file of its own.
    running = Running(data_dir, package, provbanan.package_key(), plans)

    def current() -> build_info.BuildInfo:
        return replace(info, hub_name=login.state().name)

    # The interactive API pages are off: they load scripts from another site. The contracts
    # get their own readable pages in step 1, part 2.
    app = FastAPI(
        title=build_info.PRODUCT,
        version=info.version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(hubben.router(login))
    app.include_router(provbanan.router(info, preview, lambda: login.state().name))
    app.include_router(drift_api.router(running, login))
    app.include_router(planering_api.router(plans, login))
    runs = AnyRun(lambda: running.store, lambda: preview)
    app.include_router(tmbox_web.router(runs, current))
    app.include_router(station_api.router(runs))
    app.include_router(screen_web.router(runs))

    @app.get("/", response_class=HTMLResponse)
    def start_page(
        session: hubben.SessionCookie = None, authorization: hubben.Authorization = None
    ) -> str:
        state = login.state()
        return page.render_start_page(
            replace(info, hub_name=state.name),
            set_up=state.set_up,
            logged_in=login.valid(hubben.session_of(session, authorization)),
        )

    def logged_in(session: str | None, authorization: str | None) -> bool:
        return login.valid(hubben.session_of(session, authorization))

    @app.get("/drift", response_class=HTMLResponse)
    def nu_page(
        session: hubben.SessionCookie = None, authorization: hubben.Authorization = None
    ) -> str:
        return drift_pages.render_nu(current(), logged_in(session, authorization))

    @app.get("/drift/klienter", response_class=HTMLResponse)
    def clients_page(
        session: hubben.SessionCookie = None, authorization: hubben.Authorization = None
    ) -> str:
        return drift_pages.render_klienter(current(), logged_in(session, authorization))

    @app.get("/drift/logg", response_class=HTMLResponse)
    def log_page(
        session: hubben.SessionCookie = None, authorization: hubben.Authorization = None
    ) -> str:
        return drift_pages.render_logg(current(), logged_in(session, authorization))

    @app.get("/planering", response_class=HTMLResponse)
    def planning_page(
        session: hubben.SessionCookie = None, authorization: hubben.Authorization = None
    ) -> str:
        return planering_pages.render_meets(current(), logged_in(session, authorization))

    @app.get("/planering/{meet}", response_class=HTMLResponse)
    def sources_page(
        meet: Id, session: hubben.SessionCookie = None, authorization: hubben.Authorization = None
    ) -> str:
        return planering_pages.render_sources(current(), meet, logged_in(session, authorization))

    @app.get("/planering/{meet}/data", response_class=HTMLResponse)
    def data_page(
        meet: Id, session: hubben.SessionCookie = None, authorization: hubben.Authorization = None
    ) -> str:
        return planering_pages.render_data(current(), meet, logged_in(session, authorization))

    @app.get("/planering/{meet}/versioner", response_class=HTMLResponse)
    def versions_page(
        meet: Id, session: hubben.SessionCookie = None, authorization: hubben.Authorization = None
    ) -> str:
        return planering_pages.render_versions(current(), meet, logged_in(session, authorization))

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok"

    @app.get("/api/version")
    def api_version() -> dict[str, object]:
        return info.as_dict()

    return app


app = create_app()
