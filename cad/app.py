"""CAD's web program: the API in contracts/cad.py and the web app (apps/cad).

    uv run uvicorn cad.app:app --port 8004     (settings in cad/settings.py)

The web app is built with Vite and served from CAD_WEB_DIR. Its pages are addresses of their own
(/moduler, /gavelprofiler ...), and all of them get index.html.
"""

from __future__ import annotations

import logging
import threading
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
from starlette.types import ASGIApp

from cad import (
    assemblies_api,
    curves,
    drawings_api,
    id_login,
    login,
    matbilder_api,
    meet_api,
    migrate,
    mobile,
    mobile_api,
    photos_api,
    smoothing,
    store,
)
from cad.assemblies import Assemblies
from cad.db import Database
from cad.drawings import Drawings
from cad.errors import Refused
from cad.errors import login as login_first
from cad.export import Exports
from cad.id_roles import IdRoles
from cad.landscapes import Landscapes
from cad.landscapes_api import router as landscapes_router
from cad.library import Access, Modules, Who
from cad.matbilder import Matbilder
from cad.meter import IdMeter
from cad.photos import Photos
from cad.settings import Settings, from_env
from contracts.cad import (
    CadAccount,
    CadProblem,
    CadSession,
    CadTrialLogin,
    CadVersion,
    CheckItem,
    DrawingEdit,
    DrawingView,
    GableProfile,
    Library,
    LockAsk,
    LockProposal,
    LoginKind,
    Module,
    ModuleApproval,
    ModuleChange,
    ModuleEvent,
    ModuleList,
    ModuleRemoved,
    NewModule,
    NewProfile,
    ProblemCode,
    ProfileList,
    Scale,
    SmoothAsk,
    SmoothResult,
    VisibilityChange,
)
from contracts.common import AppKey

LOGGER = logging.getLogger("cad")
API = "/api/cad/1"
DRAWING_APPS: Final = frozenset({"tkl"})
"""The apps whose access tokens from ID may call CAD for a person: Studio in TKL, for Ladda upp
ritning (part c4) and Från CAD (part d2)."""
MEET_APPS: Final = frozenset({"hub"})
"""The apps whose access tokens from ID may fetch a meet's assembly for a person: the cloud
hub's Planering, for its import (part d3, CAD-11)."""


def content_security_policy(photos_origin: str | None = None) -> str:
    """Everything from CAD itself; the photos in Object Storage from exactly its origin."""
    images = "'self' data: blob:" + (f" {photos_origin}" if photos_origin else "")
    return (
        f"default-src 'self'; img-src {images}; style-src 'self'; script-src 'self'; "
        "font-src 'self'; connect-src 'self'; manifest-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'; object-src 'none'"
    )


CONTENT_SECURITY_POLICY: Final = content_security_policy()
SECURITY_HEADERS: Final = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
NO_WEB_APP = """<!doctype html>
<html lang="sv"><meta charset="utf-8"><title>TrainMeet CAD</title>
<h1>TrainMeet CAD</h1><p>Webbappen är inte byggd. Kör <code>npm run build -w apps/cad</code>.</p>
</html>
"""

SessionCookie = Annotated[str | None, Cookie(alias=login.COOKIE)]
PhoneCookie = Annotated[str | None, Cookie(alias=mobile.COOKIE)]
IdLoginCookie = Annotated[str | None, Cookie(alias=id_login.COOKIE)]


class SecurityHeaders(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, photos_origin: str | None = None) -> None:
        super().__init__(app)
        self.headers = {
            **SECURITY_HEADERS,
            "Content-Security-Policy": content_security_policy(photos_origin),
        }

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for key, value in self.headers.items():
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
    """The app. id_http is how CAD reaches TrainMeet ID; the tests give a pretend ID."""
    settings = settings if settings is not None else from_env()
    db = Database(settings.database_url)
    sessions = login.Sessions(db)
    login_kind = LoginKind.TRIAL if settings.trial_login else LoginKind.ID
    http = id_http if id_http is not None else httpx.Client(timeout=10.0)
    with_id = id_login.IdLogin(db, settings.id, http=http) if settings.id is not None else None
    id_api = settings.id if settings.id is not None and settings.id.api else None
    roles = IdRoles(id_api, http) if id_api is not None else None
    access = Access(roles)
    modules = Modules(db, access)
    trial_by_id = {account.id: account for account in login.TRIAL_ACCOUNTS}
    # The module photos (part c1): CAD's own bucket, or its disk; and ID's meter for the AI.
    s3 = settings.photos_s3
    disk = None if s3 is not None else store.disk(settings.photos_dir)
    photo_store: store.Store = (
        store.S3Store(
            s3.endpoint,
            s3.bucket,
            s3.region,
            s3.access_key,
            s3.secret_key,
            httpx.Client(timeout=30.0),
        )
        if s3 is not None
        else disk  # type: ignore[assignment]
    )
    photos = Photos(db, photo_store, IdMeter(roles) if roles is not None else None, modules)
    modules.photos = photos
    # Ladda upp ritning (part c4): Studio's drawings, in the same store, with the same meter.
    drawings = Drawings(db, photo_store, IdMeter(roles) if roles is not None else None)
    # Landskapet and Exportera (part d1): the measuring images from the same store.
    landscapes = Landscapes(db, photo_store, modules)
    exports = Exports(modules, landscapes)
    # Anläggningar and Till TKL Studio (part d2), with the library's rights.
    assemblies = Assemblies(db, modules)
    modules.uses = assemblies
    # Mätbilden i TKL:s Foto (part d4): the measuring images of what Studio has.
    matbilder = Matbilder(db, photo_store, assemblies)
    # CAD i mobilen (#90): Fota med mobilen's QR code and the phone's own session.
    handoffs = mobile.Handoffs(db, modules)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.migrate == "auto":
            migrate.migrate(settings.database_url)
        else:
            missing = migrate.check(settings.database_url)
            if missing:
                names = ", ".join(f"{m.version:04d}_{m.name}" for m in missing)
                raise migrate.MigrationError(
                    f"Databasen saknar migrationer: {names}. Kör python -m cad.migrate."
                )
        db.open()
        LOGGER.info(
            "TrainMeet CAD %s startar, databasen har migration %04d.",
            settings.build.version,
            migrate.current_version(settings.database_url),
        )
        stop = threading.Event()
        queue = threading.Thread(target=photos.run, args=(stop,), name="fotokon", daemon=True)
        drawing_queue = threading.Thread(
            target=drawings.run, args=(stop,), name="ritningskon", daemon=True
        )
        if settings.photo_queue:
            queue.start()
            drawing_queue.start()
        try:
            yield
        finally:
            stop.set()
            photos.wake()
            drawings.wake()
            for thread in (queue, drawing_queue):
                if thread.is_alive():
                    thread.join(timeout=10)
            db.close()

    # The interactive API pages load scripts from another site, so they are off. The contracts
    # are in contracts/cad.openapi.json.
    app = FastAPI(
        title="TrainMeet CAD",
        version=settings.build.version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(SecurityHeaders, photos_origin=s3.origin if s3 is not None else None)
    app.state.db = db
    app.state.photos = photos
    app.state.drawings = drawings

    @app.exception_handler(Refused)
    def refused(_: Request, error: Refused) -> JSONResponse:
        problem = CadProblem(code=error.code, message=error.message)
        return JSONResponse(problem.model_dump(mode="json"), status_code=error.status)

    def logged_in(
        request: Request, session: SessionCookie = None, phone: PhoneCookie = None
    ) -> CadAccount | None:
        # CAD i mobilen (#90): a phone's own session holds only on the mobile flow's addresses,
        # and for the modules within its reach (cad/mobile.py); anything else wants a login.
        on_phone = handoffs.session(phone) if phone else None
        if on_phone is not None and handoffs.allows(
            on_phone, request.method, request.url.path, request.url.query
        ):
            request.state.mobile_reach = lambda module: handoffs.reaches(on_phone, module)
            return on_phone.account
        account = sessions.account(session)
        if account is None and on_phone is not None:
            raise Refused(403, ProblemCode.FORBIDDEN, mobile.OUTSIDE)
        return account

    def who(account: CadAccount | None = Depends(logged_in)) -> Who:  # noqa: B008
        if account is None:
            raise login_first()
        return Who(person=account.id, name=account.name, access=access)

    def drawing_asker(
        request: Request,
        account: CadAccount | None = Depends(logged_in),  # noqa: B008
    ) -> Who:
        """Studio through TKL, with the person's access token from ID (TKL18); or CAD's own
        session."""
        authorization = request.headers.get("authorization")
        if authorization:
            found = with_id.app_account(authorization, DRAWING_APPS) if with_id else None
            if found is None:
                raise Refused(
                    401,
                    ProblemCode.LOGIN,
                    "TrainMeet ID godtog inte inloggningen. Logga in med TrainMeet ID igen.",
                )
            return Who(person=found.id, name=found.name, access=access)
        return who(account)

    def hub_asker(request: Request) -> Who:
        """The cloud hub's Planering, with the planner's access token from ID (#78), only."""
        authorization = request.headers.get("authorization")
        found = with_id.app_account(authorization, MEET_APPS) if with_id else None
        if found is None:
            raise Refused(
                401,
                ProblemCode.LOGIN,
                "TrainMeet ID godtog inte inloggningen. Logga in med TrainMeet ID igen.",
            )
        return Who(person=found.id, name=found.name, access=access)

    app_keys = {key.value for key in AppKey}

    def session_of(account: CadAccount | None) -> CadSession:
        clubs, apps, tokens = [], None, None
        if account is not None and roles is not None:
            try:
                clubs = roles.clubs(account.id)
                apps = [AppKey(a) for a in roles.switcher(account.id) if a in app_keys]
                tokens = roles.tokens(account.id)
            except Refused:
                LOGGER.info("ID svarade inte på sessionens frågor.")
        public = settings.id.id_public if settings.id is not None else None
        return CadSession(
            account=account,
            login=login_kind,
            clubs=clubs,
            apps=apps,
            tokens=tokens,
            tokens_url=f"{public}/tokens" if public and tokens is not None else None,
            help_url=f"{public}/hjalp" if public else None,
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
    def api_version() -> CadVersion:
        return settings.build

    @app.get(API + "/session")
    def get_session(account: CadAccount | None = Depends(logged_in)) -> CadSession:  # noqa: B008
        return session_of(account)

    @app.delete(API + "/session")
    def log_out(response: Response, session: SessionCookie = None) -> CadSession:
        id_token = sessions.end(session)
        response.delete_cookie(login.COOKIE, path="/")
        return CadSession(
            account=None,
            login=login_kind,
            logout_url=with_id.logout_address(id_token) if with_id and id_token else None,
        )

    # --- TrainMeet ID -------------------------------------------------------------------------

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

    # --- The trial login ----------------------------------------------------------------------

    def require_trial() -> None:
        if not settings.trial_login:
            raise HTTPException(status_code=404, detail="Provinloggningen är inte på här.")

    @app.get(API + "/trial/accounts")
    def trial_accounts() -> list[CadAccount]:
        require_trial()
        return list(login.TRIAL_ACCOUNTS)

    @app.post(API + "/trial/login")
    def trial_log_in(body: CadTrialLogin, request: Request, response: Response) -> CadSession:
        require_trial()
        account = trial_by_id.get(body.account)
        if account is None:
            raise HTTPException(status_code=422, detail="Det finns inget sådant provkonto.")
        set_cookie(response, request, sessions.start(account))
        return session_of(account)

    # --- The library --------------------------------------------------------------------------

    @app.get(API + "/libraries")
    def libraries(asker: Who = Depends(who)) -> list[Library]:  # noqa: B008
        return modules.libraries(asker)

    @app.get(API + "/modules")
    def module_list(
        asker: Who = Depends(who),  # noqa: B008
        library: str = "mine",
        scale: Scale | None = None,
        q: str | None = None,
    ) -> ModuleList:
        return modules.listing(asker, library, scale, q)

    @app.post(API + "/modules", status_code=201)
    def new_module(body: NewModule, asker: Who = Depends(who)) -> Module:  # noqa: B008
        return modules.create(asker, body)

    @app.get(API + "/modules/{module}")
    def module(module: UUID, asker: Who = Depends(who)) -> Module:  # noqa: B008
        return modules.read(asker, module)

    @app.put(API + "/modules/{module}")
    def save_module(module: UUID, body: ModuleChange, asker: Who = Depends(who)) -> Module:  # noqa: B008
        return modules.save(asker, module, body)

    @app.delete(API + "/modules/{module}")
    def remove_module(module: UUID, asker: Who = Depends(who)) -> ModuleRemoved:  # noqa: B008
        return modules.remove(asker, module)

    @app.get(API + "/modules/{module}/versions/{version}")
    def module_version(module: UUID, version: int, asker: Who = Depends(who)) -> Module:  # noqa: B008
        if version < 1:
            raise Refused(404, ProblemCode.NOT_FOUND, "Versionen finns inte.")
        return modules.read(asker, module, version)

    @app.get(API + "/modules/{module}/history")
    def module_history(module: UUID, asker: Who = Depends(who)) -> list[ModuleEvent]:  # noqa: B008
        return modules.history(asker, module)

    @app.post(API + "/modules/{module}/approve")
    def approve_module(module: UUID, body: ModuleApproval, asker: Who = Depends(who)) -> Module:  # noqa: B008
        return modules.approve(asker, module, body)

    @app.put(API + "/modules/{module}/visibility")
    def module_visibility(
        module: UUID,
        body: VisibilityChange,
        asker: Who = Depends(who),  # noqa: B008
    ) -> Module:
        return modules.set_visibility(asker, module, body)

    # --- Ritningen and Lås mått (part b) ------------------------------------------------------

    @app.post(API + "/modules/{module}/drawing")
    def module_drawing(module: UUID, body: DrawingEdit, asker: Who = Depends(who)) -> DrawingView:  # noqa: B008
        return modules.drawing(asker, module, body)

    @app.post(API + "/modules/{module}/drawing/save")
    def save_drawing(module: UUID, body: DrawingEdit, asker: Who = Depends(who)) -> Module:  # noqa: B008
        return modules.save_drawing(asker, module, body)

    @app.post(API + "/modules/{module}/drawing/approve")
    def approve_plan(module: UUID, body: DrawingEdit, asker: Who = Depends(who)) -> Module:  # noqa: B008
        return modules.save_drawing(asker, module, body, approve=True)

    @app.post(API + "/modules/{module}/drawing/lock")
    def lock_measures(module: UUID, body: LockAsk, asker: Who = Depends(who)) -> LockProposal:  # noqa: B008
        return modules.lock_preview(asker, module, body)

    @app.get(API + "/modules/{module}/checks")
    def module_checks(
        module: UUID,
        asker: Who = Depends(who),  # noqa: B008
        version: int | None = None,
    ) -> list[CheckItem]:
        return modules.checks_of(asker, module, version)

    @app.post(API + "/smooth")
    def smooth(body: SmoothAsk, asker: Who = Depends(who)) -> SmoothResult:  # noqa: B008
        try:
            segs = smoothing.smooth(body.points, body.level, body.scale)
        except ValueError as error:
            raise Refused(422, ProblemCode.INVALID, str(error)) from error
        return SmoothResult(
            level=body.level,
            segments=[curves.segment(s) for s in segs],
            deviation=smoothing.deviation(body.points, segs),
        )

    @app.get(API + "/profiles")
    def profile_list(
        asker: Who = Depends(who),  # noqa: B008
        scale: Scale = Scale.H0,
    ) -> ProfileList:
        return modules.profile_list(asker, scale)

    @app.post(API + "/profiles", status_code=201)
    def new_profile(body: NewProfile, asker: Who = Depends(who)) -> GableProfile:  # noqa: B008
        return modules.new_profile(asker, body)

    app.include_router(photos_api.router(photos, who, disk))
    app.include_router(drawings_api.router(drawings, drawing_asker))
    app.include_router(landscapes_router(landscapes, exports, who))
    app.include_router(assemblies_api.router(assemblies, who, drawing_asker))
    app.include_router(matbilder_api.router(matbilder, drawing_asker))
    app.include_router(meet_api.router(assemblies, hub_asker))

    def public_origin(request: Request) -> str:
        """CAD's own address for the QR code: as ID knows it, else as the browser asked."""
        if settings.id is not None:
            return settings.id.public_url
        return f"{request.url.scheme}://{request.url.netloc}"

    app.include_router(mobile_api.router(handoffs, who, public_origin))

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
    # uvicorn cad.app:app builds the app from the environment when it is first asked for, so
    # importing this module in the tests needs no database.
    if name == "app":
        built = create_app()
        globals()["app"] = built
        return built
    raise AttributeError(name)
