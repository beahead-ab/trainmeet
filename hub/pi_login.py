"""Logga in med TrainMeet ID på träffens Pi, och igen utan internet (KONTO-11, KONTO-37, F18).

The Pi is on the meet's own network and has no address of its own on the internet, so it logs in
through the cloud hub it follows (Synk, SYNK-02), which is ID's client:

1. The Pi asks its cloud hub, over the link and with the Pi's key, for an attempt, and sends the
   browser to the cloud's login with ID. The browser keeps the attempt in a cookie of its own, so
   only this browser can finish it.
2. The cloud logs the person in with ID, asks ID for a ticket for this Pi with the person's roles
   at the meet (hub/id_roles.py), keeps it with the attempt, and sends the browser back to the
   address the Pi gave when it asked. Only the Pi that asked, with its key, gets the ticket.
3. The Pi fetches the ticket and ID's public keys from the cloud, checks the ticket against the
   keys, and starts a session with the ticket's roles. The ticket goes to the browser as an
   HttpOnly cookie for its 30 days.
4. Without internet the Pi checks the ticket against the keys it already has, and lets the person
   in again with the same roles: a role taken back in ID holds on the Pi until the ticket runs out
   or the person logs in with internet again (KONTO-37). Logga ut forgets the ticket.

Never a ticket, a key or a token in the log.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final
from urllib.parse import quote, urlencode, urlparse
from uuid import UUID

import jwt
from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from contracts import hub
from contracts.sync import HEADER, PROTOCOL, PiLoginStart, PiLoginStarted, PiTicket
from hub.hubben import _secure, _set_cookie
from hub.id_login import IdLogin
from hub.id_roles import IdRoles
from hub.local import LocalLogin, Person
from synk.follower import Call, Unreachable
from synk.link import Links

LOGGER = logging.getLogger("hub.id")

TICKET_COOKIE: Final = "trainmeet_ticket"
ATTEMPT_COOKIE: Final = "trainmeet_pi_login"
BACK_PATH: Final = "/api/hub/id/back"
AUDIENCE_PREFIX: Final = "trainmeet-hub:"
TICKET_TYPE: Final = "trainmeet-pi-ticket"

TicketCookie = Annotated[str | None, Cookie(alias=TICKET_COOKIE, max_length=4000)]
AttemptCookie = Annotated[str | None, Cookie(alias=ATTEMPT_COOKIE, max_length=100)]


@dataclass(frozen=True)
class Checked:
    person: Person
    roles: dict[str, list[str]]
    expires: datetime


class TicketRefused(Exception):
    """The ticket does not hold: not ID's, not for this Pi, or run out."""


def check_ticket(ticket: str, kept: str | None, hub_id: str) -> Checked:
    """The ticket, checked against ID's keys the Pi has, with no call out (KONTO-11)."""
    if not kept:
        raise TicketRefused("Pi:n har inga nycklar från ID.")
    try:
        stored = json.loads(kept)
        header = jwt.get_unverified_header(ticket)
        key = next(
            jwt.PyJWK(item)
            for item in stored.get("keys", [])
            if item.get("kid") == header.get("kid") and item.get("alg") == "ES256"
        )
        claims: dict[str, Any] = jwt.decode(
            ticket,
            key=key,
            algorithms=["ES256"],
            audience=AUDIENCE_PREFIX + hub_id,
            issuer=str(stored.get("issuer", "")),
            leeway=60,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        person = Person(str(UUID(str(claims["sub"]))), str(claims.get("name") or "Utan namn"))
        roles = {
            str(UUID(str(meet))): [str(role) for role in held]
            for meet, held in dict(claims.get("roles", {})).items()
        }
    except (StopIteration, jwt.PyJWTError, ValueError, TypeError, AttributeError) as error:
        raise TicketRefused(f"Biljetten godtas inte: {type(error).__name__}.") from error
    if claims.get("typ") != TICKET_TYPE:
        raise TicketRefused("Det är ingen biljett för Pi:n.")
    return Checked(person, roles, datetime.fromtimestamp(int(claims["exp"]), UTC))


# --- In the cloud ------------------------------------------------------------------------------


class PiTickets:
    """The cloud's part: attempts from linked Pis, and the tickets ID signs for them."""

    def __init__(
        self,
        login: LocalLogin,
        roles: IdRoles,
        id_meet_of: Callable[[str], UUID | None],
    ) -> None:
        self.login = login
        self.roles = roles
        self.id_meet_of = id_meet_of

    def finish(self, attempt: str, person: Person) -> str:
        """Back from ID for a Pi's attempt: the ticket is kept for the Pi, and the browser goes
        back to the Pi. Returns where."""
        found = self.login.pi_attempt(attempt)
        if found is None:
            raise HTTPException(410, "Inloggningen för Pi:n har gått ut. Börja om på Pi:n.")
        id_meet = self.id_meet_of(found.meet)
        ticket = self.roles.ticket(person.id, found.pi, [id_meet] if id_meet else [])
        self.login.keep_pi_ticket(attempt, ticket)
        return found.back + "?" + urlencode({"attempt": attempt})


def cloud_router(
    login: LocalLogin, links: Links, with_id: IdLogin, tickets: PiTickets
) -> APIRouter:
    routes = APIRouter()

    def follower_of(meet: str, authorization: str | None) -> str:
        scheme, _, key = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not key:
            raise HTTPException(401, "Pi:ns nyckel saknas.")
        found = links.follower(meet, key, datetime.now(UTC))
        if found is None:
            raise HTTPException(401, "Molnhubben känner inte den här Pi:n.")
        return found.hub_id

    @routes.post("/api/sync/1/meets/{meet}/id-login")
    def start(
        meet: str,
        asked: PiLoginStart,
        response: Response,
        authorization: Annotated[str | None, Header(max_length=200)] = None,
    ) -> dict[str, Any]:
        """A linked Pi sends someone here to log in with ID (KONTO-11)."""
        response.headers["Cache-Control"] = "no-store"
        pi = follower_of(meet, authorization)
        back = urlparse(asked.back)
        if back.scheme not in ("http", "https") or not back.netloc or back.path != BACK_PATH:
            raise HTTPException(422, f"Adressen tillbaka ska vara Pi:ns {BACK_PATH}.")
        if back.query or back.fragment:
            raise HTTPException(422, "Adressen tillbaka har inga parametrar.")
        attempt = login.begin_pi_login(meet, pi, asked.back)
        address = f"{with_id.settings.public_url}/api/hub/id/login?" + urlencode({"pi": attempt})
        return PiLoginStarted(attempt=attempt, address=address).model_dump(mode="json")

    @routes.get("/api/sync/1/meets/{meet}/id-login/{attempt}")
    def ticket(
        meet: str,
        attempt: str,
        response: Response,
        authorization: Annotated[str | None, Header(max_length=200)] = None,
    ) -> dict[str, Any]:
        """The ticket, once, to the Pi that asked, with ID's keys to check it with."""
        response.headers["Cache-Control"] = "no-store"
        pi = follower_of(meet, authorization)
        found = login.take_pi_ticket(attempt, meet, pi)
        if found is None:
            raise HTTPException(404, "Ingen biljett för det försöket.")
        issuer = str(jwt.decode(found, options={"verify_signature": False}).get("iss", ""))
        return PiTicket(ticket=found, issuer=issuer, keys=tickets.roles.keys()).model_dump(
            mode="json"
        )

    return routes


# --- On the Pi ---------------------------------------------------------------------------------


def pi_router(
    login: LocalLogin,
    links: Links,
    meet_now: Callable[[], str | None],
    call: Call,
) -> APIRouter:
    """meet_now: the meet the Pi runs, to log in through its cloud hub."""
    routes = APIRouter(prefix="/api/hub/id")

    def reach() -> tuple[str, str, str]:
        reaches = links.reaches()
        now = meet_now()
        found = next((r for r in reaches if r.meet == now), reaches[0] if reaches else None)
        if found is None:
            raise HTTPException(404, "Pi:n är inte kopplad till någon molnhubb.")
        return found.address, found.meet, found.key

    def ask(method: str, path: str, body: bytes | None) -> dict[str, Any]:
        address, meet, key = reach()
        headers = {"Content-Type": "application/json", HEADER: PROTOCOL}
        headers["Authorization"] = f"Bearer {key}"
        url = f"{address}/api/sync/1/meets/{quote(meet, safe='')}/{path}"
        try:
            status, answer = call(method, url, headers, body, 15.0)
        except Unreachable as error:
            raise HTTPException(503, "Molnhubben svarar inte. Pi:n behöver internet.") from error
        if status != 200:
            LOGGER.warning("Molnhubben svarade %s på inloggningen för Pi:n.", status)
            raise HTTPException(502, "Molnhubben loggade inte in.")
        data: dict[str, Any] = json.loads(answer)
        return data

    def fail(why: str) -> RedirectResponse:
        LOGGER.warning("Inloggningen med ID på Pi:n gick inte: %s", why)
        return RedirectResponse("/?inloggning=fel", status_code=303)

    @routes.get("/login", response_class=RedirectResponse, status_code=303)
    def log_in(request: Request) -> Response:
        """Logga in med TrainMeet ID on the Pi: through the cloud hub, with internet."""
        reach()  # 404 for a hub that follows no cloud: it has no login with ID
        origin = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("host") or request.url.netloc
        back = PiLoginStart(back=f"{origin}://{host}{BACK_PATH}")
        try:
            started = PiLoginStarted.model_validate(
                ask("POST", "id-login", back.model_dump_json().encode())
            )
        except HTTPException as error:
            return fail(str(error.detail))
        response = RedirectResponse(started.address, status_code=303)
        response.set_cookie(
            ATTEMPT_COOKIE,
            started.attempt,
            max_age=600,
            httponly=True,
            secure=_secure(request),
            samesite="lax",  # the cloud sends the browser back with a plain link
            path="/api/hub/id",
        )
        return response

    @routes.get("/back", response_class=RedirectResponse, status_code=303)
    def back(request: Request, attempt: str | None = None, mine: AttemptCookie = None) -> Response:
        """Back from the cloud: the ticket, checked, and a session with its roles."""
        if not attempt or mine != attempt:
            return fail("inloggningen började inte i den här webbläsaren")
        try:
            given = PiTicket.model_validate(ask("GET", f"id-login/{quote(attempt, safe='')}", None))
        except HTTPException as error:
            return fail(str(error.detail))
        login.keep_id_keys(json.dumps({"issuer": given.issuer, **given.keys}))
        try:
            checked = check_ticket(given.ticket, login.id_keys(), links.hub_id())
        except TicketRefused as error:
            return fail(str(error))
        response = RedirectResponse("/", status_code=303)
        _set_cookie(request, response, login.log_in_with_ticket(checked.person, checked.roles))
        _keep_ticket(request, response, given.ticket, checked.expires)
        response.delete_cookie(ATTEMPT_COOKIE, path="/api/hub/id")
        return response

    @routes.post("/again")
    def again(request: Request, response: Response, ticket: TicketCookie = None) -> dict[str, Any]:
        """Logga in igen, without internet: the ticket the browser has, checked with the keys
        the Pi already has (KONTO-11, KONTO-37)."""
        response.headers["Cache-Control"] = "no-store"
        if not ticket:
            raise HTTPException(401, "Ingen biljett i den här webbläsaren. Logga in med internet.")
        try:
            checked = check_ticket(ticket, login.id_keys(), links.hub_id())
        except TicketRefused as error:
            raise HTTPException(
                401, "Biljetten gäller inte längre. Logga in med TrainMeet ID med internet."
            ) from error
        token = login.log_in_with_ticket(checked.person, checked.roles)
        _set_cookie(request, response, token)
        return hub.Session(session_key=token).model_dump(mode="json")

    return routes


def ticket_name(login: LocalLogin, links: Links) -> Callable[[str | None], str | None]:
    """Whose ticket the browser has, for Logga in igen som …, if it still holds."""

    def name(ticket: str | None) -> str | None:
        if not ticket:
            return None
        try:
            return check_ticket(ticket, login.id_keys(), links.hub_id()).person.name
        except TicketRefused:
            return None

    return name


def _keep_ticket(request: Request, response: Response, ticket: str, expires: datetime) -> None:
    seconds = max(int((expires - datetime.now(UTC)).total_seconds()), 0)
    response.set_cookie(
        TICKET_COOKIE,
        ticket,
        max_age=seconds,
        httponly=True,
        secure=_secure(request),
        samesite="strict",
        path="/api/hub",
    )


def forget_ticket(response: Response) -> None:
    """Logga ut on the Pi forgets the ticket in this browser too."""
    response.delete_cookie(TICKET_COOKIE, path="/api/hub")
