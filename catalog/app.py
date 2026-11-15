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
from uuid import UUID

import httpx
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from starlette.middleware.base import BaseHTTPMiddleware

from catalog import fleet_api, id_login, login, migrate, tags_api
from catalog.access import Access
from catalog.db import Database, UnknownOwner
from catalog.fleet import Fleet, Refused
from catalog.id_roles import IdRoles
from catalog.settings import Settings, from_env
from catalog.tags import Tags
from contracts.catalog import (
    Account,
    CatalogVersion,
    FleetChoice,
    FleetRight,
    LoginKind,
    Problem,
    ProblemCode,
    Session,
    TrialLogin,
)
from contracts.common import AppKey

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
IdLoginCookie = Annotated[str | None, Cookie(alias=id_login.COOKIE)]


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


def create_app(settings: Settings | None = None, *, id_http: httpx.Client | None = None) -> FastAPI:
    """The app. id_http is how Catalog reaches TrainMeet ID; the tests give a pretend ID."""
    settings = settings if settings is not None else from_env()
    db = Database(settings.database_url)
    sessions = login.Sessions(db)
    login_kind = LoginKind.TRIAL if settings.trial_login else LoginKind.ID
    http = id_http if id_http is not None else httpx.Client(timeout=10.0)
    with_id = id_login.IdLogin(db, settings.id, http=http) if settings.id is not None else None
    # Shared fleets: Catalog asks ID at every call (#49, KONTO-34). Without ID nothing is shared.
    id_api = settings.id if settings.id is not None and settings.id.api else None
    access = Access(IdRoles(id_api, http) if id_api is not None else None)
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

    @app.exception_handler(Refused)
    def refused(_: Request, error: Refused) -> JSONResponse:
        problem = Problem(code=error.code, message=error.message)
        return JSONResponse(problem.model_dump(mode="json"), status_code=error.status)

    @app.exception_handler(UnknownOwner)
    def unknown_owner(_: Request, __: UnknownOwner) -> JSONResponse:
        # A session whose owner is gone: log in again.
        problem = Problem(code=ProblemCode.LOGIN, message="Logga in igen.")
        return JSONResponse(problem.model_dump(mode="json"), status_code=401)

    def logged_in(session: SessionCookie = None) -> Account | None:
        return sessions.account(session)

    def share_address(owner: UUID) -> str | None:
        """Where a fleet is shared in TrainMeet ID (CAT-44)."""
        return f"{id_api.id_public}/vagnparker/{owner}" if id_api is not None else None

    app_keys = {key.value for key in AppKey}

    def apps_of(account: Account) -> list[AppKey] | None:
        """The app switcher's apps from ID (ID11). Without an answer the switcher shows all."""
        if access.roles is None:
            return None
        try:
            return [AppKey(app) for app in access.roles.switcher(account.id) if app in app_keys]
        except Refused:
            return None

    def session_of(key: str | None) -> Session:
        account = sessions.account(key)
        share = share_address(account.id) if account is not None else None
        return Session(
            account=account,
            login=login_kind,
            simulated_tags=settings.simulated_tags,
            share_url=share,
            help_url=f"{settings.id.id_public}/hjalp" if settings.id is not None else None,
            apps=apps_of(account) if account is not None else None,
        )

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
        id_token = sessions.end(session)
        response.delete_cookie(login.COOKIE, path="/")
        return Session(
            account=None,
            login=login_kind,
            simulated_tags=settings.simulated_tags,
            logout_url=with_id.logout_address(id_token) if with_id and id_token else None,
        )

    # --- TrainMeet ID (#66, KONTO-27) -------------------------------------------------------

    @app.get(API + "/id/login", response_class=RedirectResponse, status_code=303)
    def id_log_in(request: Request, next: str | None = None, lang: str | None = None) -> Response:
        if with_id is None:
            raise HTTPException(status_code=404, detail="Inloggningen med ID är inte på här.")
        started = with_id.start(id_login.safe_next(next), lang)
        response = RedirectResponse(started.address, status_code=303)
        response.set_cookie(
            id_login.COOKIE,
            started.key,
            max_age=id_login.LIFETIME_SECONDS,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",  # ID sends the browser back with a plain link
            path=id_login.COOKIE_PATH,
        )
        return response

    @app.get(API + "/id/callback", response_class=RedirectResponse, status_code=303)
    def id_callback(
        request: Request,
        attempt: IdLoginCookie = None,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> Response:
        if with_id is None:
            raise HTTPException(status_code=404, detail="Inloggningen med ID är inte på här.")
        try:
            done = with_id.finish(attempt, state, code, error)
        except id_login.LoginFailed as failed:
            LOGGER.warning("Inloggningen med ID gick inte: %s", failed)
            response = RedirectResponse(failed.back, status_code=303)
        else:
            response = RedirectResponse(done.next_path, status_code=303)
            set_cookie(response, request, sessions.start(done.account, done.id_token))
        response.delete_cookie(id_login.COOKIE, path=id_login.COOKIE_PATH)
        return response

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
        return Session(account=account, login=login_kind, simulated_tags=settings.simulated_tags)

    fleet = Fleet(db, tag_base=settings.tag_base)
    tags = Tags(
        db,
        base=settings.tag_base,
        simulated=settings.simulated_tags,
        shared_with=access.shared_with,
    )

    @app.get(API + "/fleets")
    def fleets(account: Account | None = Depends(logged_in)) -> list[FleetChoice]:  # noqa: B008
        """The fleets the person can work in: their own, then the shared ones (CAT-50)."""
        if account is None:
            raise Refused(401, ProblemCode.LOGIN, "Logga in först.")
        mine = FleetChoice(
            owner=account.id,
            title=f"Vagnparken · {account.name}",
            right=FleetRight.OWNER,
            share_url=share_address(account.id),
        )
        if access.roles is None:
            return [mine]
        rights = {"owner": FleetRight.OWNER, "editor": FleetRight.EDIT}
        shared = [
            FleetChoice(
                owner=found.owner,
                title=found.title,
                right=rights.get(found.role, FleetRight.VIEW),
                share_url=share_address(found.owner) if found.role == "owner" else None,
            )
            for found in access.roles.shared_fleets(account.id)
        ]
        # A club's fleet has an owner in Catalog from the first time someone opens it (CAT-51).
        fleet.ensure_owners([(f.owner, f.title.removeprefix("Vagnparken · ")) for f in shared])
        return [mine, *shared]

    app.include_router(fleet_api.router(fleet, logged_in, access))
    app.include_router(tags_api.router(fleet, tags, logged_in, access))

    @app.api_route(
        "/api/{rest:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def unknown_api(rest: str) -> JSONResponse:
        return JSONResponse({"detail": "Finns inte."}, status_code=404)

    @app.api_route(
        "/{path:path}", methods=["GET", "HEAD"], response_model=None, include_in_schema=False
    )
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
