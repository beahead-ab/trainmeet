"""Den här hubben over HTTP: first start, logging in and out, and the admin check the other
routes use. Pages send the session as an HttpOnly cookie; API clients as Authorization: Bearer.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response

from contracts import hub
from hub.local import (
    SESSION_LIFETIME,
    AlreadySetUp,
    InvalidSetup,
    LocalLogin,
    NotSetUp,
    TooManyAttempts,
    WrongPin,
)

COOKIE = "trainmeet_session"
SessionCookie = Annotated[str | None, Cookie(alias=COOKIE, max_length=120)]
Authorization = Annotated[str | None, Header(max_length=200)]


def session_of(cookie: str | None, authorization: str | None) -> str | None:
    """The session a request carries: the Bearer key if there is one, else the cookie."""
    scheme, _, key = (authorization or "").partition(" ")
    if scheme.lower() == "bearer" and key:
        return key
    return cookie


def _set_cookie(request: Request, response: Response, token: str) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )


def router(login: LocalLogin) -> APIRouter:
    routes = APIRouter(prefix="/api/hub")

    @routes.get("")
    def info(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        state = login.state()
        logged_in = login.valid(session_of(session, authorization))
        return hub.HubInfo(name=state.name, set_up=state.set_up, logged_in=logged_in).model_dump(
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

    @routes.post("/logout", status_code=204)
    def log_out(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> None:
        login.log_out(session_of(session, authorization))
        response.delete_cookie(COOKIE, path="/")

    return routes


def require_admin(login: LocalLogin, cookie: str | None, authorization: str | None) -> None:
    """Every route that changes the meet calls this first (S1: without logging in one looks)."""
    if not login.valid(session_of(cookie, authorization)):
        raise HTTPException(401, "Logga in med hubbens PIN-kod.")
