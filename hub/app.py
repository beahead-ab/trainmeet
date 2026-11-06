"""The hub's web program. Start it with: uv run uvicorn hub.app:app --reload"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from hub import build_info, hubben, page, provbanan
from hub.local import LocalLogin

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    info: build_info.BuildInfo | None = None,
    *,
    preview_db: Path | None = None,
) -> FastAPI:
    info = info if info is not None else build_info.from_env()
    data_dir = provbanan.database_path(preview_db).parent
    login = LocalLogin(data_dir / "hubben.sqlite3", info.hub_name)

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
    app.include_router(provbanan.router(info, preview_db, lambda: login.state().name))

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

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok"

    @app.get("/api/version")
    def api_version() -> dict[str, object]:
        return info.as_dict()

    return app


app = create_app()
