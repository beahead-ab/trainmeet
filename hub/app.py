"""The hub's web program. Start it with: uv run uvicorn hub.app:app --reload"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from drift.store import PreviewStore
from hub import (
    build_info,
    drift_api,
    drift_pages,
    hubben,
    page,
    provbanan,
    screen_web,
    station_api,
    tmbox_web,
)
from hub.local import LocalLogin
from hub.stores import AnyRun

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
    preview = PreviewStore(preview_path, package)
    # The hub's own meet: Provbanan until import comes in step 4. A file of its own, no end.
    meet = PreviewStore(
        data_dir / "traff.sqlite3",
        package,
        lifetime=timedelta(days=3650),
        max_runs=64,
        max_actions=1_000_000,
    )

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
    app.include_router(drift_api.router(meet, login))
    runs = AnyRun(meet, preview)
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

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok"

    @app.get("/api/version")
    def api_version() -> dict[str, object]:
        return info.as_dict()

    return app


app = create_app()
