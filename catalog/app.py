"""Catalog's web program: the API in contracts/catalog.py and the web app.

    uv run uvicorn catalog.app:app --port 8001     (settings in catalog/settings.py)

The web app (apps/catalog) is built with Vite and served from CATALOG_WEB_DIR. Its pages are
addresses of their own (/fordon, /traffar ...), and all of them get index.html.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Final

from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware

from catalog import login, migrate
from catalog.db import Database
from catalog.settings import Settings, from_env
from contracts.catalog import Account, CatalogVersion, LoginKind, Session, TrialLogin

LOGGER = logging.getLogger("catalog")
API = "/api/catalog/1"

# Only the app's own files run; nothing is loaded from another site (WCAG and privacy).
CONTENT_SECURITY_POLICY: Final = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
    "font-src 'self'; connect-src 'self'; manifest-src 'self'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'; object-src 'none'"
)
SECURITY_HEADERS: Final = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
NO_WEB_APP = """<!doctype html>
<html lang="sv"><meta charset="utf-8"><title>TrainMeet Catalog</title>
<h1>TrainMeet Catalog</h1><p>Webbappen är inte byggd. Kör <code>npm run build</code>.</p>
</html>
"""

SessionCookie = Annotated[str | None, Cookie(alias=login.COOKIE)]


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if request.url.path.startswith("/api/"):
            # Answers about a person are never kept by a browser or a proxy.
            response.headers["Cache-Control"] = "private, no-store"
        return response


def _web_file(web_dir: Path, path: str) -> Path | None:
    """A file in the built web app, never outside it."""
    if not path:
        return None
    root = web_dir.resolve()
    candidate = (root / path).resolve()
    if candidate.is_relative_to(root) and candidate.is_file():
        return candidate
    return None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else from_env()
    db = Database(settings.database_url)
    sessions = login.Sessions(db)
    login_kind = LoginKind.TRIAL if settings.trial_login else LoginKind.ID
    trial_by_id = {account.id: account for account in login.TRIAL_ACCOUNTS}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.migrate == "auto":
            migrate.migrate(settings.database_url)
        else:
            missing = migrate.check(settings.database_url)
            if missing:
                names = ", ".join(f"{m.version:04d}_{m.name}" for m in missing)
                raise migrate.MigrationError(
                    f"Databasen saknar migrationer: {names}. Kör python -m catalog.migrate."
                )
        db.open()
        LOGGER.info(
            "TrainMeet Catalog %s startar, databasen har migration %04d.",
            settings.build.version,
            migrate.current_version(settings.database_url),
        )
        try:
            yield
        finally:
            db.close()

    # The interactive API pages load scripts from another site, so they are off. The
    # contracts are in contracts/catalog.openapi.json.
    app = FastAPI(
        title="TrainMeet Catalog",
        version=settings.build.version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(SecurityHeaders)
    app.state.db = db

    def session_of(key: str | None) -> Session:
        return Session(account=sessions.account(key), login=login_kind)

    def set_cookie(response: Response, request: Request, key: str) -> None:
        response.set_cookie(
            login.COOKIE,
            key,
            max_age=int(login.SESSION_LIFETIME.total_seconds()),
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/",
        )

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> PlainTextResponse:
        if not db.ping():
            return PlainTextResponse("databasen svarar inte", status_code=503)
        return PlainTextResponse("ok")

    @app.get("/api/version")
    def api_version() -> CatalogVersion:
        return settings.build

    @app.get(API + "/session")
    def get_session(session: SessionCookie = None) -> Session:
        return session_of(session)

    @app.delete(API + "/session")
    def log_out(response: Response, session: SessionCookie = None) -> Session:
        sessions.end(session)
        response.delete_cookie(login.COOKIE, path="/")
        return Session(account=None, login=login_kind)

    def require_trial() -> None:
        if not settings.trial_login:
            raise HTTPException(status_code=404, detail="Provinloggningen finns bara i testmiljön.")

    @app.get(API + "/trial/accounts")
    def trial_accounts() -> list[Account]:
        require_trial()
        return list(login.TRIAL_ACCOUNTS)

    @app.post(API + "/trial/login")
    def trial_log_in(body: TrialLogin, request: Request, response: Response) -> Session:
        require_trial()
        account = trial_by_id.get(body.account)
        if account is None:
            raise HTTPException(status_code=422, detail="Det finns inget sådant provkonto.")
        key = sessions.start(account)
        set_cookie(response, request, key)
        return Session(account=account, login=login_kind)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def unknown_api(rest: str) -> JSONResponse:
        return JSONResponse({"detail": "Finns inte."}, status_code=404)

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], response_model=None)
    def web_app(path: str) -> Response:
        """The web app's files, and index.html for every page address."""
        found = _web_file(settings.web_dir, path)
        if found is not None:
            cache = (
                "public, max-age=31536000, immutable"
                if path.startswith("assets/")
                else "public, max-age=3600"
            )
            return FileResponse(found, headers={"Cache-Control": cache})
        if "." in path.rsplit("/", 1)[-1]:
            return PlainTextResponse("Finns inte.", status_code=404)
        index = settings.web_dir / "index.html"
        if not index.is_file():
            return HTMLResponse(NO_WEB_APP)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


def __getattr__(name: str) -> FastAPI:
    # uvicorn catalog.app:app builds the app from the environment when it is first asked for,
    # so importing this module in the tests needs no database.
    if name == "app":
        built = create_app()
        globals()["app"] = built
        return built
    raise AttributeError(name)
