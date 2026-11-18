"""TrainMeets AI i Hubben (#79, TOKEN-28, TK7, TK12): saldot och mätaren i TrainMeet ID.

The cloud hub never holds TrainMeet's AI key (TK7). Someone logged in with TrainMeet ID may
choose TrainMeets AI for a scanned file when the hub has no own AI, or instead of it: each page
is reserved from the balance of the one who owns the meet (TK16), the club for a meet in ID or
else the person, and read by the meter in ID, which draws 12 tokens a page. A page that is
already written down is never sent again and costs nothing (IMPORT-15).
"""

from __future__ import annotations

import base64
import logging
import secrets
import threading
import time
from collections.abc import Callable
from uuid import UUID

import httpx
from fastapi import HTTPException

from contracts.tokens import (
    MeterAnswer,
    TokenBalance,
    TokenOwner,
    TokenOwnerKind,
    TokenReservation,
)
from hub.id_roles import IdRoles, unavailable
from integrationer import ai

LOGGER = logging.getLogger("hub.id")

READ_TIMEOUT = 180.0
"""The meter waits for Claude; the hub waits for the meter a little longer."""


def refused(answer_status: int, body: object) -> HTTPException:
    """What ID said, as ID said it, for the planner: no tokens, or the AI did not answer."""
    message = body.get("message") if isinstance(body, dict) else None
    if answer_status in (402, 409, 422, 502, 503) and isinstance(message, str):
        return HTTPException(answer_status, message)
    LOGGER.warning("ID:s mätare svarade %s.", answer_status)
    return unavailable()


class IdTokens:
    def __init__(self, roles: IdRoles) -> None:
        self.roles = roles

    def balance(self, person: str, owner: TokenOwner) -> TokenBalance:
        answer = self.roles.call(
            "GET", "tokens", params={"person": person, "owner": f"{owner.kind}:{owner.id}"}
        )
        if answer.status_code != 200:
            raise refused(answer.status_code, _json(answer))
        return TokenBalance.model_validate(answer.json())

    def read(
        self,
        person: str,
        owner: TokenOwner,
        prompt: str,
        image: ai.Image,
        what: str,
        max_tokens: int,
        amount: int = 12,
    ) -> MeterAnswer:
        """One page through the meter: reserved, read and drawn, or given back by ID when the
        AI does not answer. With own AI on the account nothing is reserved (TK4)."""
        body = {
            "person": person,
            "owner": owner.model_dump(mode="json"),
            "amount": amount,
            "key": f"hubben-{secrets.token_hex(12)}",
            "what": what[:120],
        }
        held = self.roles.call("POST", "tokens/reservations", body=body)
        if held.status_code != 201:
            raise refused(held.status_code, _json(held))
        reservation = TokenReservation.model_validate(held.json())
        asked = {
            "reservation": str(reservation.id),
            "prompt": prompt,
            "images": [
                {"media_type": image.media_type, "data": base64.b64encode(image.data).decode()}
            ],
            "max_tokens": max_tokens,
        }
        try:
            read = self.roles.call("POST", "meter", body=asked, timeout=READ_TIMEOUT)
        except HTTPException:
            self._give_back(reservation.id)
            raise
        if read.status_code != 200:
            raise refused(read.status_code, _json(read))
        return MeterAnswer.model_validate(read.json())

    def _give_back(self, reservation: UUID) -> None:
        try:
            self.roles.call("POST", f"tokens/reservations/{reservation}/return")
        except HTTPException:
            LOGGER.warning("Reservationen gick inte att lämna tillbaka; den går ut av sig själv.")


class ShownBalance:
    """Saldot i sidhuvudet (TOKEN-01): the tokens left on the person's own account, asked of ID
    at most once a minute per person, since the header asks the hub often. None when ID does
    not answer; the header then leaves it out."""

    def __init__(
        self,
        tokens: IdTokens,
        seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.tokens = tokens
        self.seconds = seconds
        self.clock = clock
        self._seen: dict[str, tuple[float, int | None]] = {}
        self._lock = threading.Lock()

    def __call__(self, person: str) -> int | None:
        now = self.clock()
        with self._lock:
            seen = self._seen.get(person)
        if seen is not None and now - seen[0] < self.seconds:
            return seen[1]
        try:
            owner = TokenOwner(kind=TokenOwnerKind.PERSON, id=UUID(person))
            available: int | None = self.tokens.balance(person, owner).available
        except (HTTPException, ValueError):
            available = None
        with self._lock:
            if len(self._seen) > 1000:
                self._seen.clear()
            self._seen[person] = (now, available)
        return available


def _json(answer: httpx.Response) -> object:
    try:
        found: object = answer.json()
    except ValueError:
        return None
    return found
