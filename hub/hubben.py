"""Den här hubben over HTTP: first start, logging in and out, the admin check the other routes
use, and the hub's own AI service (H58). Pages send the session as an HttpOnly cookie; API
clients as Authorization: Bearer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from contracts import hub
from contracts.id import MeetRole
from hub import id_login
from hub.local import (
    ADMIN,
    DISPATCHER,
    LET_IN_LIFETIME,
    LOCO_LEAD,
    PERSON,
    SESSION_LIFETIME,
    AiSetting,
    AlreadySetUp,
    InvalidSetup,
    LocalLogin,
    NotSetUp,
    Person,
    TooManyAttempts,
    WrongPin,
)
from integrationer import ai

LOGGER = logging.getLogger("hub.id")

COOKIE = "trainmeet_session"
SessionCookie = Annotated[str | None, Cookie(alias=COOKIE, max_length=120)]
IdLoginCookie = Annotated[str | None, Cookie(alias=id_login.COOKIE, max_length=200)]
TICKET_COOKIE = "trainmeet_ticket"
"""On the meet's Pi: the ticket from ID, for logging in again without internet (KONTO-11)."""
TicketCookie = Annotated[str | None, Cookie(alias=TICKET_COOKIE, max_length=4000)]
# Room for an access token from TrainMeet ID (TKL's, SYNK-30). The hub's own keys are checked
# for their length where they are used.
Authorization = Annotated[str | None, Header(max_length=8000)]


def session_of(cookie: str | None, authorization: str | None) -> str | None:
    """The session a request carries: the Bearer key if there is one, else the cookie."""
    scheme, _, key = (authorization or "").partition(" ")
    if scheme.lower() == "bearer" and key:
        return key
    return cookie


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def _set_cookie(
    request: Request, response: Response, token: str, lifetime: timedelta = SESSION_LIFETIME
) -> None:
    secure = _secure(request)
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(lifetime.total_seconds()),
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )


def info_of(
    login: LocalLogin,
    token: str | None,
    run: str | None,
    *,
    id_login_on: bool = False,
    may_run: Callable[[str | None, str | None], bool] | None = None,
    ticket_name: str | None = None,
    tokens_of: Callable[[str], int | None] | None = None,
    tokens_url: str | None = None,
) -> hub.HubInfo:
    """Who the session is here: the administrator with the PIN, someone let in with a code in
    the meet that runs (H56), someone logged in with TrainMeet ID (#78), or no one. may_run
    asks whether the session may run the meet that runs; without it only the PIN and a let-in
    dispatcher do."""
    state = login.state()
    role = login.role(token, run)
    person = login.person(token) if role == PERSON else None
    runs = role in (ADMIN, DISPATCHER)
    if role == PERSON and may_run is not None and run is not None:
        try:
            runs = may_run(token, run)
        except HTTPException:
            runs = False  # ID does not answer: no buttons, and the page says nothing worse
    # Saldot (TOKEN-01): for someone logged in with ID in the cloud hub.
    tokens = tokens_of(person.id) if person is not None and tokens_of is not None else None
    return hub.HubInfo(
        name=state.name,
        set_up=state.set_up,
        logged_in=role is not None,
        admin=role == ADMIN,
        meet_role=MeetRole(role) if role in (DISPATCHER, LOCO_LEAD) else None,
        may_run=runs,
        person=person.name if person is not None else None,
        id_login=id_login_on,
        ticket_name=ticket_name if role is None else None,
        tokens=tokens,
        tokens_url=tokens_url if tokens is not None else None,
    )


def router(
    login: LocalLogin,
    current_run: Callable[[], str | None] = lambda: None,
    with_id: id_login.IdLogin | None = None,
    may_run: Callable[[str | None, str | None], bool] | None = None,
    *,
    pi_offers: Callable[[], bool] = lambda: False,
    pi_finish: Callable[[str, Person], str] | None = None,
    ticket_name: Callable[[str | None], str | None] = lambda ticket: None,
    tokens_of: Callable[[str], int | None] | None = None,
) -> APIRouter:
    """current_run: the meet that runs, or None; a let-in role holds only there (H56).
    with_id: the login with TrainMeet ID, if the hub is set up for it (#78). may_run: whether
    a session may run the meet that runs, with the roles from ID. On a meet's Pi, pi_offers
    says that it logs in through its cloud hub and ticket_name whose ticket the browser has; in
    the cloud, pi_finish gives a Pi its ticket (hub/pi_login.py). tokens_of: the balance in
    ID for the header (TOKEN-01), where the hub has ID's API."""
    routes = APIRouter(prefix="/api/hub")

    def info_now(token: str | None, ticket: str | None = None) -> hub.HubInfo:
        return info_of(
            login,
            token,
            current_run(),
            id_login_on=bool(with_id) or pi_offers(),
            may_run=may_run,
            ticket_name=ticket_name(ticket),
            tokens_of=tokens_of,
            tokens_url=f"{with_id.settings.id_public}/tokens" if with_id is not None else None,
        )

    @routes.get("")
    def info(
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
        ticket: TicketCookie = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return info_now(session_of(session, authorization), ticket).model_dump(mode="json")

    @routes.post("/setup", status_code=201)
    def set_up(setup: hub.SetUp, request: Request, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            token = login.set_up(setup.name, setup.pin)
        except AlreadySetUp as error:
            raise HTTPException(409, "Hubben har redan en PIN-kod. Logga in.") from error
        except InvalidSetup as error:
            raise HTTPException(422, str(error)) from error
        _set_cookie(request, response, token)
        return hub.Session(session_key=token).model_dump(mode="json")

    @routes.post("/login")
    def log_in(credentials: hub.LogIn, request: Request, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            token = login.log_in(credentials.pin)
        except NotSetUp as error:
            raise HTTPException(409, "Hubben har ingen PIN-kod än. Välj en först.") from error
        except TooManyAttempts as error:
            raise HTTPException(429, "För många fel försök. Vänta tio minuter.") from error
        except WrongPin as error:
            raise HTTPException(401, "Fel PIN-kod.") from error
        _set_cookie(request, response, token)
        return hub.Session(session_key=token).model_dump(mode="json")

    @routes.post("/login/code")
    def log_in_with_code(
        credentials: hub.CodeLogIn, request: Request, response: Response
    ) -> dict[str, Any]:
        """Engångskoden (H56, F18): the role the dispatcher gave, in the meet that runs."""
        response.headers["Cache-Control"] = "no-store"
        run = current_run()
        if run is None:
            raise HTTPException(409, "Ingen träff är startad. En engångskod gäller bara i träffen.")
        try:
            token = login.log_in_with_code(credentials.code, run)
        except NotSetUp as error:
            raise HTTPException(409, "Hubben har ingen PIN-kod än. Välj en först.") from error
        except TooManyAttempts as error:
            raise HTTPException(429, "För många fel försök. Vänta tio minuter.") from error
        except WrongPin as error:
            raise HTTPException(
                401, "Koden stämmer inte, eller har gått ut. Be trafikledningen om en ny."
            ) from error
        _set_cookie(request, response, token, LET_IN_LIFETIME)
        return hub.Session(session_key=token).model_dump(mode="json")

    @routes.post("/name")
    def rename(
        change: hub.Rename,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """På den här hubben (SYNK-07): the hub's name."""
        response.headers["Cache-Control"] = "no-store"
        require_admin(login, session, authorization)
        try:
            login.rename(change.name)
        except InvalidSetup as error:
            raise HTTPException(422, str(error)) from error
        return info_now(session_of(session, authorization)).model_dump(mode="json")

    @routes.post("/pin", status_code=204)
    def change_pin(
        change: hub.PinChange, session: SessionCookie = None, authorization: Authorization = None
    ) -> None:
        """Byt PIN (SYNK-07): the current one again, then the new. The one who changed it stays
        logged in; every other session ends."""
        require_admin(login, session, authorization)
        try:
            login.change_pin(change.pin, change.new_pin, session_of(session, authorization))
        except TooManyAttempts as error:
            raise HTTPException(429, "För många fel försök. Vänta tio minuter.") from error
        except WrongPin as error:
            raise HTTPException(403, "Den nuvarande PIN-koden stämmer inte.") from error
        except InvalidSetup as error:
            raise HTTPException(422, str(error)) from error

    @routes.get("/ai")
    def ai_service(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> dict[str, Any]:
        """Egen AI (H58): what is set, never the key."""
        response.headers["Cache-Control"] = "no-store"
        require_admin(login, session, authorization)
        found = login.ai()
        if found is None:
            raise HTTPException(404, "Ingen egen AI är inkopplad.")
        return _ai_view(found)

    @routes.post("/ai")
    def connect_ai(
        change: hub.AiServiceChange,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Koppla in egen AI: the hub checks that the model reads an image (H70), and only then
        keeps the setting. Without a new key the one set before stays."""
        response.headers["Cache-Control"] = "no-store"
        require_admin(login, session, authorization)
        before = login.ai()
        key = change.key.strip() if change.key else before.key if before else ""
        if not key:
            raise HTTPException(422, "Lägg in nyckeln till AI-tjänsten.")
        try:
            address = ai.check_address(change.address)
            service = ai.Service(change.format.value, address, change.model.strip(), key)
            ai.probe(service)
        except ai.AiError as error:
            raise HTTPException(422, str(error)) from None
        setting = AiSetting(service.format, service.address, service.model, key, datetime.now(UTC))
        login.set_ai(setting)
        return _ai_view(setting)

    @routes.post("/ai/disconnect", status_code=204)
    def disconnect_ai(session: SessionCookie = None, authorization: Authorization = None) -> None:
        """Koppla bort: the setting and the key are gone from the hub."""
        require_admin(login, session, authorization)
        login.clear_ai()

    @routes.post("/logout")
    def log_out(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> dict[str, Any]:
        """Logga ut. A login with ID logs out of ID too: the browser goes there next."""
        response.headers["Cache-Control"] = "no-store"
        id_token = login.log_out(session_of(session, authorization))
        response.delete_cookie(COOKIE, path="/")
        response.delete_cookie(TICKET_COOKIE, path="/api/hub")  # on the Pi: this browser forgets
        address = with_id.logout_address(id_token) if with_id and id_token else None
        return hub.LoggedOut(logout_url=address).model_dump(mode="json")

    # --- TrainMeet ID (#78, KONTO-27) -------------------------------------------------------

    @routes.get("/id/login", response_class=RedirectResponse, status_code=303)
    def id_log_in(
        request: Request, next: str | None = None, lang: str | None = None, pi: str | None = None
    ) -> Response:
        """To ID's login page, and back to the page asked for. pi: a meet's Pi sent the browser
        here, and gets a ticket instead (hub/pi_login.py)."""
        if with_id is None:
            raise HTTPException(404, "Hubben har ingen inloggning med TrainMeet ID.")
        if pi is not None and (pi_finish is None or login.pi_attempt(pi) is None):
            raise HTTPException(410, "Inloggningen för Pi:n har gått ut. Börja om på Pi:n.")
        started = with_id.start(id_login.safe_next(next), lang, pi)
        response = RedirectResponse(started.address, status_code=303)
        response.set_cookie(
            id_login.COOKIE,
            started.key,
            max_age=id_login.LIFETIME_SECONDS,
            httponly=True,
            secure=_secure(request),
            samesite="lax",  # ID sends the browser back with a plain link
            path=id_login.COOKIE_PATH,
        )
        return response

    @routes.get("/id/callback", response_class=RedirectResponse, status_code=303)
    def id_callback(
        request: Request,
        attempt: IdLoginCookie = None,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> Response:
        """Back from ID: the hub's session starts, as an HttpOnly cookie."""
        if with_id is None:
            raise HTTPException(404, "Hubben har ingen inloggning med TrainMeet ID.")
        try:
            done = with_id.finish(attempt, state, code, error)
        except id_login.LoginFailed as failed:
            LOGGER.warning("Inloggningen med ID gick inte: %s", failed)
            response = RedirectResponse(failed.back, status_code=303)
        else:
            if done.pi_attempt is not None and pi_finish is not None:
                # For a meet's Pi: no session here, the ticket waits for the Pi (KONTO-11).
                response = RedirectResponse(pi_finish(done.pi_attempt, done.person), 303)
                response.delete_cookie(id_login.COOKIE, path=id_login.COOKIE_PATH)
                return response
            response = RedirectResponse(done.next_path, status_code=303)
            session = login.log_in_with_id(done.person, done.id_token, done.access)
            _set_cookie(request, response, session)
        response.delete_cookie(id_login.COOKIE, path=id_login.COOKIE_PATH)
        return response

    return routes


def service_of(setting: AiSetting) -> ai.Service:
    """The stored setting as the service to ask."""
    form: ai.Format = "claude" if setting.format == "claude" else "chat"
    return ai.Service(form, setting.address, setting.model, setting.key)


def _ai_view(setting: AiSetting) -> dict[str, Any]:
    return hub.AiService(
        format=hub.AiFormat(setting.format),
        address=setting.address,
        model=setting.model,
        key_set=bool(setting.key),
        checked=setting.checked,
    ).model_dump(mode="json")


def require_admin(login: LocalLogin, cookie: str | None, authorization: str | None) -> None:
    """Every route that changes the hub or the meet's plan calls this first (S1: without
    logging in one looks). Only the one with the hub's PIN (H18)."""
    if not login.valid(session_of(cookie, authorization)):
        raise HTTPException(401, "Logga in med hubbens PIN-kod.")
