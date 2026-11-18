"""Den här hubben over HTTP: first start, logging in and out, the admin check the other routes
use, and the hub's own AI service (H58). Pages send the session as an HttpOnly cookie; API
clients as Authorization: Bearer.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response

from contracts import hub
from contracts.id import MeetRole
from hub.local import (
    ADMIN,
    DISPATCHER,
    LET_IN_LIFETIME,
    SESSION_LIFETIME,
    AiSetting,
    AlreadySetUp,
    InvalidSetup,
    LocalLogin,
    NotSetUp,
    TooManyAttempts,
    WrongPin,
)
from integrationer import ai

COOKIE = "trainmeet_session"
SessionCookie = Annotated[str | None, Cookie(alias=COOKIE, max_length=120)]
Authorization = Annotated[str | None, Header(max_length=200)]


def session_of(cookie: str | None, authorization: str | None) -> str | None:
    """The session a request carries: the Bearer key if there is one, else the cookie."""
    scheme, _, key = (authorization or "").partition(" ")
    if scheme.lower() == "bearer" and key:
        return key
    return cookie


def _set_cookie(
    request: Request, response: Response, token: str, lifetime: timedelta = SESSION_LIFETIME
) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(lifetime.total_seconds()),
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )


def info_of(login: LocalLogin, token: str | None, run: str | None) -> hub.HubInfo:
    """Who the session is here: the administrator with the PIN, someone let in with a code in
    the meet that runs (H56), or no one."""
    state = login.state()
    role = login.role(token, run)
    return hub.HubInfo(
        name=state.name,
        set_up=state.set_up,
        logged_in=role is not None,
        admin=role == ADMIN,
        meet_role=MeetRole(role) if role is not None and role != ADMIN else None,
    )


def router(login: LocalLogin, current_run: Callable[[], str | None] = lambda: None) -> APIRouter:
    """current_run: the meet that runs, or None; a let-in role holds only there (H56)."""
    routes = APIRouter(prefix="/api/hub")

    @routes.get("")
    def info(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return info_of(login, session_of(session, authorization), current_run()).model_dump(
            mode="json"
        )

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
        state = login.state()
        return hub.HubInfo(
            name=state.name, set_up=state.set_up, logged_in=True, admin=True
        ).model_dump(mode="json")

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

    @routes.post("/logout", status_code=204)
    def log_out(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> None:
        login.log_out(session_of(session, authorization))
        response.delete_cookie(COOKIE, path="/")

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


def require_dispatcher(
    login: LocalLogin, cookie: str | None, authorization: str | None, run: str
) -> None:
    """Drift in the meet that runs: the administrator, or someone the dispatcher let in with a
    one-time code (H56). The code gives at most the dispatcher's own role."""
    if login.role(session_of(cookie, authorization), run) not in (ADMIN, DISPATCHER):
        raise HTTPException(
            401, "Logga in med hubbens PIN-kod, eller med en engångskod från trafikledningen."
        )
