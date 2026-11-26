"""Koppla Pi:n till en träff genom inloggning och val av träff (F16, SYNK-02, KONTO-22).

The Pi has no address on the internet, and the person who links it is logged in on the Pi with
the hub's PIN. So the linking goes as a device's login does:

1. On the Pi, under Den här hubben → Molnet, the administrator gives the cloud's address. The
   Pi asks the cloud for an attempt and keeps its secret, and sends the browser to the cloud with
   the attempt, which the browser keeps in cookies of its own on both hubs.
2. In the cloud the person logs in, with TrainMeet ID where the cloud has it, and chooses among
   the meets that are planned there and that the person may plan (PLAN-19). The page shows the
   Pi's name and address, so that nobody chooses for a Pi they did not start. The cloud sends
   the browser back to the address the Pi gave.
3. The Pi, seeing its own attempt come back in the same browser, fetches its key with the
   secret, once, and follows the meet as with the code. The code is the reserve (F16).

Never the secret or the key in a log or a page.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Final, NoReturn
from urllib.parse import quote, urlencode, urlparse

from fastapi import APIRouter, Cookie, HTTPException, Path, Query, Request, Response
from fastapi.responses import RedirectResponse

from contracts.meet import Meet
from contracts.sync import (
    PROTOCOL,
    Hello,
    Link,
    LinkAttempt,
    LinkAttemptStart,
    LinkAttemptStarted,
    LinkChoice,
    LinkChosen,
    LinkMeetChoice,
    LinkRedeem,
)
from hub.hubben import Authorization, SessionCookie, _secure, session_of
from hub.id_login import IdLogin
from hub.id_roles import PLANS
from hub.local import LocalLogin
from hub.rights import NOT_LOGGED_IN, Rights
from planering.store import Planning, PlanningError
from synk.follower import Follower
from synk.home import Homes
from synk.link import ATTEMPT_LIFETIME, Attempt, LinkError, Links

LOGGER = logging.getLogger("synk.link")

ATTEMPT_COOKIE: Final = "trainmeet_pi_link"
CLOUD_PATH: Final = "/api/sync/1/link"
PI_PATH: Final = "/api/hub/cloud"
BACK_PATH: Final = PI_PATH + "/linked"
CHOOSE_PAGE: Final = "/planering?koppla=pi"
SETTINGS_PAGE: Final = "/installningar"
GONE = "Kopplingen har gått ut, eller började i en annan webbläsare. Börja om på Pi:n."

AttemptCookie = Annotated[str | None, Cookie(alias=ATTEMPT_COOKIE, max_length=100)]
AttemptPath = Annotated[str, Path(min_length=16, max_length=100)]


def _fail(error: LinkError | PlanningError) -> NoReturn:
    raise HTTPException(error.status, str(error)) from error


def _keep_attempt(request: Request, response: Response, attempt: str, path: str) -> None:
    response.set_cookie(
        ATTEMPT_COOKIE,
        attempt,
        max_age=int(ATTEMPT_LIFETIME.total_seconds()),
        httponly=True,
        secure=_secure(request),
        samesite="lax",  # the browser comes in from the other hub with a plain link
        path=path,
    )


def _origin(address: str) -> str:
    parts = urlparse(address)
    return f"{parts.scheme}://{parts.netloc}"


# --- In the cloud ------------------------------------------------------------------------------


def cloud_router(
    plans: Planning,
    links: Links,
    homes: Homes,
    hello: Callable[[], Hello],
    login: LocalLogin,
    may: Rights,
    with_id: IdLogin | None,
) -> APIRouter:
    routes = APIRouter(prefix=CLOUD_PATH)

    def here(meet: str) -> bool:
        me = hello()
        return homes.home(meet, me.hub_id, me.hub_name).here

    def plannable(token: str | None) -> list[Meet]:
        """The meets planned here that the one logged in may plan: all of them with the PIN,
        with ID those where ID makes the person Administratör or Arrangör (PLAN-19)."""
        held = may.roles_by_meet(token)
        found = []
        for summary in plans.meets():
            meet = summary.meet
            if held is not None:
                roles = held.get(str(meet.id_meet), set()) if meet.id_meet else set()
                if not roles & PLANS:
                    continue
            if here(meet.id):
                found.append(meet)
        return found

    def held_attempt(attempt: str | None) -> tuple[str, Attempt]:
        found = links.attempt(attempt, datetime.now(UTC)) if attempt else None
        if attempt is None or found is None:
            raise HTTPException(410, GONE)
        return attempt, found

    def logged_in(session: str | None, authorization: str | None) -> str:
        token = session_of(session, authorization)
        if login.role(token) is None:
            raise HTTPException(401, NOT_LOGGED_IN)
        return str(token)

    @routes.post("/attempts", status_code=201)
    def begin(asked: LinkAttemptStart, response: Response) -> dict[str, Any]:
        """A Pi starts linking: the attempt, and the secret it alone keeps."""
        response.headers["Cache-Control"] = "no-store"
        if PROTOCOL not in asked.hello.protocols:
            raise HTTPException(426, f"Hubben talar {PROTOCOL}.")
        back = urlparse(asked.back)
        if back.scheme not in ("http", "https") or not back.netloc or back.path != BACK_PATH:
            raise HTTPException(422, f"Adressen tillbaka ska vara Pi:ns {BACK_PATH}.")
        if back.query or back.fragment or back.params:
            raise HTTPException(422, "Adressen tillbaka har inga parametrar.")
        try:
            attempt, secret, expires = links.begin(asked.hello, asked.back, datetime.now(UTC))
        except LinkError as error:
            _fail(error)
        # The Pi may reach the cloud at an address the browser cannot, as Låtsas-Pi does in the
        # test environment; the browser goes to the address ID knows the cloud by.
        opened = f"{CLOUD_PATH}/attempts/{quote(attempt, safe='')}/open"
        address = f"{with_id.settings.public_url}{opened}" if with_id is not None else None
        started = LinkAttemptStarted(
            attempt=attempt, secret=secret, expires=expires, address=address
        )
        return started.model_dump(mode="json")

    @routes.get("/attempts/{attempt}/open", response_class=RedirectResponse, status_code=303)
    def open_attempt(
        request: Request, attempt: AttemptPath, session: SessionCookie = None
    ) -> Response:
        """The browser comes from the Pi: the attempt goes in a cookie here, and the person
        logs in, with ID where the cloud has it, and chooses the meet."""
        page = CHOOSE_PAGE
        if with_id is not None and login.role(session) is None:
            page = "/api/hub/id/login?" + urlencode({"next": CHOOSE_PAGE})
        response = RedirectResponse(page, status_code=303)
        _keep_attempt(request, response, attempt, CLOUD_PATH)
        return response

    @routes.get("/attempt")
    def shown(
        response: Response,
        attempt: AttemptCookie = None,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """The Pi that asks, and the meets the one logged in may link it to."""
        response.headers["Cache-Control"] = "no-store"
        _, found = held_attempt(attempt)
        token = logged_in(session, authorization)
        choices = [
            LinkMeetChoice(meet=meet.id, name=meet.name, first_date=meet.first_date)
            for meet in plannable(token)
        ]
        return LinkAttempt(
            hub_name=found.hello.hub_name,
            software=found.hello.software,
            address=_origin(found.back),
            expires=found.expires,
            meets=choices,
            chosen=found.meet,
        ).model_dump(mode="json")

    @routes.post("/attempt")
    def choose(
        choice: LinkChoice,
        response: Response,
        attempt: AttemptCookie = None,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Välj träff: the Pi will follow it. Back to the Pi, which then fetches its key."""
        response.headers["Cache-Control"] = "no-store"
        key, found = held_attempt(attempt)
        token = logged_in(session, authorization)
        try:
            meet = plans.draft(choice.meet).meet
        except PlanningError as error:
            _fail(error)
        may.require_planner(token, meet.id_meet)
        if not here(meet.id):
            raise HTTPException(409, "Träffens hem är inte här. Koppla Pi:n där.")
        if not links.choose(key, meet.id, datetime.now(UTC)):
            raise HTTPException(410, GONE)
        LOGGER.info("En Pi kopplas till %s.", meet.id)
        response.delete_cookie(ATTEMPT_COOKIE, path=CLOUD_PATH)
        back = found.back + "?" + urlencode({"attempt": key})
        return LinkChosen(back=back).model_dump(mode="json")

    @routes.post("/attempts/{attempt}/redeem")
    def redeem(attempt: AttemptPath, given: LinkRedeem, response: Response) -> dict[str, Any]:
        """The Pi's key, once, for the secret only the Pi has."""
        response.headers["Cache-Control"] = "no-store"
        try:
            meet, key = links.redeem_attempt(attempt, given.secret, datetime.now(UTC))
            name = plans.draft(meet).meet.name
        except (LinkError, PlanningError) as error:
            _fail(error)
        return Link(meet=meet, meet_name=name, key=key, hello=hello()).model_dump(mode="json")

    return routes


# --- On the Pi ---------------------------------------------------------------------------------


def pi_router(login: LocalLogin, follower: Follower) -> APIRouter:
    routes = APIRouter(prefix=PI_PATH)

    def settings(said: str) -> RedirectResponse:
        """Back to Den här hubben → Molnet, which says how it went in a word (LinkError.reason)."""
        return RedirectResponse(
            f"{SETTINGS_PAGE}?{urlencode({'molnet': said})}#molnet", status_code=303
        )

    @routes.get("/login", response_class=RedirectResponse, status_code=303)
    def log_in(
        request: Request,
        address: Annotated[str, Query(max_length=200)] = "",
        session: SessionCookie = None,
    ) -> Response:
        """Logga in och välj träff: the administrator with the Pi's PIN starts it here."""
        if not login.valid(session):
            return settings("pin")
        origin = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("host") or request.url.netloc
        try:
            started = follower.begin_link(address, f"{origin}://{host}{BACK_PATH}")
        except LinkError as error:
            LOGGER.warning("Pi:n kunde inte börja kopplingen: %s", error)
            return settings(error.reason)
        response = RedirectResponse(started.opened, status_code=303)
        _keep_attempt(request, response, started.attempt, PI_PATH)
        return response

    @routes.get("/linked", response_class=RedirectResponse, status_code=303)
    def linked(attempt: str | None = None, mine: AttemptCookie = None) -> Response:
        """Back from the cloud with the meet chosen: the key, and the Pi follows the meet."""
        if not attempt or mine != attempt:
            return settings("gick-ut")
        try:
            follower.finish_link(attempt)
        except LinkError as error:
            LOGGER.warning("Pi:n kunde inte kopplas: %s", error)
            response = settings(error.reason)
        else:
            response = settings("kopplad")
        response.delete_cookie(ATTEMPT_COOKIE, path=PI_PATH)
        return response

    return routes
