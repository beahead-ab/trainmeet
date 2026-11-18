"""ID's API and web app (#67), next to Keycloak at the same address.

    uv run uvicorn id.app:app --port 8002     (settings in id/settings.py)

Keycloak answers /realms/ and /resources/; everything else at the address comes here: the API
under /api/id/1 (contracts/id.py) and the web app's pages (apps/id).
"""

# No "from __future__ import annotations": FastAPI must see the local Person and App aliases.
import logging
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Final, Protocol
from uuid import UUID

import httpx
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from starlette.middleware.base import BaseHTTPMiddleware

from contracts.id import (
    Access,
    AccountExport,
    Answer,
    Club,
    ClubName,
    ClubPage,
    ClubRoleChange,
    FleetAccess,
    FleetInvite,
    FleetPage,
    HelpRequest,
    HelpSent,
    Invitation,
    Invite,
    Meet,
    MeetGrant,
    MeetPage,
    NewMeet,
    Problem,
    ProblemCode,
    RemovalPlan,
    RemoveAccount,
    Removed,
    Resource,
    ResourceKind,
    Session,
    Switcher,
    Ticket,
    TicketKeys,
    TicketRequest,
    Version,
)
from contracts.tokens import (
    TokenBalance,
    TokenDraw,
    TokenReservation,
    TokenReserve,
)
from id import login as id_login
from id import migrate
from id.accounts import Accounts
from id.db import Database
from id.help import HelpDesk, HelpMailer
from id.mail import SmtpMailer
from id.roles import Asker, Mailer, Refused, Roles
from id.settings import Settings, from_env
from id.tickets import Tickets
from id.tokens import Tokens, owner_from

LOGGER = logging.getLogger("id")
API = "/api/id/1"

CONTENT_SECURITY_POLICY: Final = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'; object-src 'none'"
)
SECURITY_HEADERS: Final = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
NO_WEB_APP = """<!doctype html>
<html lang="sv"><meta charset="utf-8"><title>TrainMeet ID</title>
<h1>TrainMeet ID</h1><p>Webbappen är inte byggd. Kör <code>npm run build</code>.</p>
</html>
"""

SessionCookie = Annotated[str | None, Cookie(alias=id_login.COOKIE)]
AttemptCookie = Annotated[str | None, Cookie(alias=id_login.ATTEMPT_COOKIE)]


class AllMail(Mailer, HelpMailer, Protocol):
    """Invitations and Hjälp och fel, from the same mail server."""


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "private, no-store"
        return response


def create_app(
    settings: Settings | None = None,
    *,
    http: httpx.Client | None = None,
    mailer: AllMail | None = None,
) -> FastAPI:
    """The app. The tests give a pretend Keycloak (http) and a pretend mail server."""
    settings = settings if settings is not None else from_env()
    db = Database(settings.database_url)
    http = http if http is not None else httpx.Client(timeout=10.0)
    login = id_login.Login(db, settings, http)
    mail: AllMail = mailer if mailer is not None else SmtpMailer(settings.smtp)
    roles = Roles(db, mail, settings.public_url)
    tickets = Tickets(db, roles, settings.public_url)
    tokens = Tokens(db)
    help_desk = HelpDesk(mail, settings.support)
    accounts = Accounts(settings, http, roles)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.migrate == "auto":
            migrate.migrate(settings.database_url)
        elif missing := migrate.check(settings.database_url):
            names = ", ".join(f"{m.version:04d}_{m.name}" for m in missing)
            raise migrate.MigrationError(f"Databasen saknar migrationer: {names}.")
        db.open()
        LOGGER.info("ID:s API startar.")
        try:
            yield
        finally:
            db.close()

    app = FastAPI(
        title="TrainMeet ID",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(SecurityHeaders)

    @app.exception_handler(Refused)
    def refused(_: Request, error: Refused) -> JSONResponse:
        problem = Problem(code=error.code, message=error.message)
        return JSONResponse(problem.model_dump(mode="json"), status_code=error.status)

    def asker(session: SessionCookie = None) -> Asker:
        account = login.account(session)
        if account is None:
            raise Refused(401, ProblemCode.LOGIN, "Logga in först.")
        return Asker(id=account.id, email=account.email)

    Person = Annotated[Asker, Depends(asker)]

    def app_client(authorization: Annotated[str | None, Header()] = None) -> str:
        app_name = login.app(authorization)
        if app_name is None:
            raise Refused(401, ProblemCode.LOGIN, "En app frågar med sin token från ID.")
        return app_name

    App = Annotated[str, Depends(app_client)]

    @app.get("/api/version")
    def version() -> Version:
        commit = os.environ.get("TRAINMEET_COMMIT", "").strip().lower()
        return Version(commit=commit if re.fullmatch(r"[0-9a-f]{7,40}", commit) else None)

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> PlainTextResponse:
        if not db.ping():
            return PlainTextResponse("databasen svarar inte", status_code=503)
        return PlainTextResponse("ok")

    # --- The session ------------------------------------------------------------------------

    @app.get(API + "/session")
    def get_session(session: SessionCookie = None) -> Session:
        account = login.account(session)
        apps = roles.switcher(account.id).apps if account else []
        return Session(account=account, apps=apps)

    @app.delete(API + "/session")
    def log_out(response: Response, session: SessionCookie = None) -> Session:
        id_token = login.end_session(session)
        response.delete_cookie(id_login.COOKIE, path="/")
        return Session(logout_url=login.logout_address(id_token) if id_token else None)

    @app.get(API + "/login", response_class=RedirectResponse, status_code=303)
    def log_in(request: Request, next: str | None = None, lang: str | None = None) -> Response:
        started = login.start(id_login.safe_next(next), lang)
        response = RedirectResponse(started.address, status_code=303)
        response.set_cookie(
            id_login.ATTEMPT_COOKIE,
            started.key,
            max_age=id_login.ATTEMPT_SECONDS,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path=id_login.ATTEMPT_PATH,
        )
        return response

    @app.get(API + "/login/callback", response_class=RedirectResponse, status_code=303)
    def login_callback(
        request: Request,
        attempt: AttemptCookie = None,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> Response:
        try:
            account, id_token, next_path = login.finish(attempt, state, code, error)
        except id_login.LoginFailed as failed:
            LOGGER.warning("Inloggningen gick inte: %s", failed)
            response = RedirectResponse(failed.back, status_code=303)
        else:
            roles.seen(account)
            response = RedirectResponse(next_path, status_code=303)
            response.set_cookie(
                id_login.COOKIE,
                login.start_session(account, id_token),
                max_age=int(id_login.SESSION_LIFETIME.total_seconds()),
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="lax",
                path="/",
            )
        response.delete_cookie(id_login.ATTEMPT_COOKIE, path=id_login.ATTEMPT_PATH)
        return response

    # --- Clubs (KONTO-02, KONTO-35) -----------------------------------------------------------

    @app.get(API + "/clubs")
    def clubs(person: Person) -> list[Club]:
        return roles.clubs(person)

    @app.post(API + "/clubs", status_code=201)
    def create_club(body: ClubName, person: Person) -> Club:
        return roles.create_club(person, body.name)

    @app.get(API + "/clubs/{club}")
    def club_page(club: UUID, person: Person) -> ClubPage:
        return roles.club_page(person, club)

    @app.post(API + "/clubs/{club}/invitations", status_code=201)
    def invite_to_club(club: UUID, body: Invite, person: Person) -> Invitation:
        return roles.invite_to_club(person, club, body.email)

    @app.put(API + "/clubs/{club}/members/{member}")
    def change_role(club: UUID, member: UUID, body: ClubRoleChange, person: Person) -> ClubPage:
        return roles.change_role(person, club, member, body.role)

    @app.delete(API + "/clubs/{club}/members/{member}", response_model=None)
    def remove_member(club: UUID, member: UUID, person: Person) -> ClubPage | Response:
        page = roles.remove_member(person, club, member)
        return page if page is not None else Response(status_code=204)

    # --- Fleets (CAT-44, KONTO-29) ------------------------------------------------------------

    @app.get(API + "/fleets/{owner}")
    def fleet_page(owner: UUID, person: Person) -> FleetPage:
        return roles.fleet_page(person, owner)

    @app.post(API + "/fleets/{owner}/invitations", status_code=201)
    def invite_to_fleet(owner: UUID, body: FleetInvite, person: Person) -> Invitation:
        return roles.invite_to_fleet(person, owner, body.email, body.role)

    @app.delete(API + "/grants/{grant}")
    def remove_grant(grant: UUID, person: Person) -> Removed:
        return roles.remove_grant(person, grant)

    # --- Meets (ID10) -------------------------------------------------------------------------

    @app.post(API + "/clubs/{club}/meets", status_code=201)
    def create_meet(club: UUID, body: NewMeet, person: Person) -> Meet:
        return roles.create_meet(person, club, body)

    @app.get(API + "/meets")
    def meets(person: Person) -> list[Meet]:
        return roles.meets(person)

    @app.get(API + "/meets/{meet}")
    def meet_page(meet: UUID, person: Person) -> MeetPage:
        return roles.meet_page(person, meet)

    @app.put(API + "/meets/{meet}")
    def change_meet(meet: UUID, body: NewMeet, person: Person) -> MeetPage:
        return roles.change_meet(person, meet, body)

    @app.delete(API + "/meets/{meet}")
    def remove_meet(meet: UUID, person: Person) -> Removed:
        return roles.remove_meet(person, meet)

    @app.post(API + "/meets/{meet}/grants")
    def give_at_meet(meet: UUID, body: MeetGrant, person: Person) -> MeetPage:
        return roles.give_at_meet(person, meet, body)

    # --- Removing the account (KONTO-31, ID7, ID13) --------------------------------------------

    @app.get(API + "/account/removal")
    def removal_plan(person: Person) -> RemovalPlan:
        return accounts.plan(person)

    @app.get(API + "/account/export", response_model=AccountExport)
    def export(session: SessionCookie = None) -> JSONResponse:
        account = login.account(session)
        if account is None:
            raise Refused(401, ProblemCode.LOGIN, "Logga in först.")
        file = accounts.export(Asker(id=account.id, email=account.email), account)
        file = file.model_copy(update={"tokens": tokens.balances_for(account.id)[0]})
        return JSONResponse(
            file.model_dump(mode="json"),
            headers={
                "Content-Disposition": 'attachment; filename="trainmeet-mina-uppgifter.json"',
                "Cache-Control": "no-store",
            },
        )

    @app.post(API + "/account/remove")
    def remove_account(body: RemoveAccount, response: Response, person: Person) -> Session:
        accounts.remove(person)
        response.delete_cookie(id_login.COOKIE, path="/")
        return Session()

    # --- Hjälp och fel (KONTO-06, ID9) ---------------------------------------------------------

    @app.post(API + "/help")
    def send_help(body: HelpRequest, session: SessionCookie = None) -> HelpSent:
        account = login.account(session)
        if account is None:
            raise Refused(401, ProblemCode.LOGIN, "Logga in först.")
        return help_desk.send(account, body)

    # --- Invitations --------------------------------------------------------------------------

    @app.get(API + "/invitations")
    def invitations(person: Person) -> list[Invitation]:
        return roles.invitations_for(person)

    @app.post(API + "/invitations/{invitation}/answer")
    def answer(invitation: UUID, body: Answer, person: Person) -> Invitation:
        return roles.answer(person, invitation, body.accept)

    @app.delete(API + "/invitations/{invitation}")
    def withdraw(invitation: UUID, person: Person) -> Removed:
        return roles.withdraw(person, invitation)

    # --- The apps (KONTO-34) ------------------------------------------------------------------

    @app.get(API + "/apps/access")
    def access(person: UUID, resource: str, _: App) -> Access:
        kind, _sep, ident = resource.partition(":")
        try:
            wanted = Resource(kind=ResourceKind(kind), id=ident)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="resource är kind:id.") from error
        return roles.access(person, wanted)

    @app.get(API + "/apps/switcher")
    def switcher(person: UUID, _: App) -> Switcher:
        return roles.switcher(person)

    @app.get(API + "/apps/meets")
    def app_meets(person: UUID, _: App) -> list[Meet]:
        """The meets the Hub may link its own meet to, with the person's roles (ID10, #78)."""
        return roles.meets_for(person)

    @app.post(API + "/apps/tickets")
    def ticket(body: TicketRequest, app_name: App) -> Ticket:
        """Biljetten för Pi:n (KONTO-11, KONTO-37, #78), asked for by the Hub."""
        return tickets.issue(app_name, body.person, body.hub, body.meets)

    @app.get(API + "/keys")
    def ticket_keys() -> TicketKeys:
        """The public keys the Pi checks tickets with, open to anyone (KONTO-11)."""
        return TicketKeys.model_validate(tickets.jwks())

    @app.get(API + "/apps/fleets")
    def fleets(person: UUID, _: App) -> list[FleetAccess]:
        return roles.fleets_for(person)

    # --- TrainMeet tokens (#79, TOKEN-08) ------------------------------------------------------

    @app.get(API + "/tokens")
    def my_tokens(person: Person) -> list[TokenBalance]:
        """The person's balance and their clubs' (TOKEN-01)."""
        return tokens.balances_for(person.id)

    @app.get(API + "/apps/tokens")
    def app_tokens(person: UUID, owner: str, _: App) -> TokenBalance:
        return tokens.balance(person, owner_from(owner))

    @app.post(API + "/apps/tokens/reservations", status_code=201)
    def reserve_tokens(body: TokenReserve, app_name: App) -> TokenReservation:
        return tokens.reserve(app_name, body)

    @app.post(API + "/apps/tokens/reservations/{reservation}/draw")
    def draw_tokens(reservation: UUID, body: TokenDraw, app_name: App) -> TokenReservation:
        return tokens.draw(app_name, reservation, body)

    @app.post(API + "/apps/tokens/reservations/{reservation}/return")
    def return_tokens(reservation: UUID, app_name: App) -> TokenReservation:
        return tokens.give_back(app_name, reservation)

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
        root = settings.web_dir.resolve()
        if path:
            candidate = (root / path).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                cache = (
                    "public, max-age=31536000, immutable"
                    if path.startswith("assets/")
                    else "public, max-age=3600"
                )
                return FileResponse(candidate, headers={"Cache-Control": cache})
            if "." in path.rsplit("/", 1)[-1]:
                return PlainTextResponse("Finns inte.", status_code=404)
        index = root / "index.html"
        if not index.is_file():
            return HTMLResponse(NO_WEB_APP)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


def __getattr__(name: str) -> FastAPI:
    if name == "app":
        built = create_app()
        globals()["app"] = built
        return built
    raise AttributeError(name)
