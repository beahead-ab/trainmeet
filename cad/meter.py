"""TrainMeet ID's tokens and meter, as CAD uses them for a photo (CAD-13, CAD-18, CAD-29).

CAD never holds a key to an AI. A photo is read in ID's meter (contracts/tokens.py): TrainMeets
AI, which is Claude in Anthropic's own API, outside the EU, or the account's own AI, which costs
nothing (TK4). As Catalog's reading (#52): reserve before the call, read with hold so the meter
keeps the answer but draws nothing, check the answer failing closed, then draw what it cost, or
give it all back when anything failed. A reservation nobody draws goes back by itself.
"""

from __future__ import annotations

import logging
from typing import Final, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel

from cad.errors import Refused, unavailable
from cad.id_roles import IdRoles
from contracts.cad import ProblemCode
from contracts.tokens import (
    MeterAnswer,
    MeterRead,
    TokenBalance,
    TokenOwner,
    TokenReservation,
    TokenReserve,
)

LOGGER = logging.getLogger("cad.meter")
READ_TIMEOUT: Final = 150.0
"""How long CAD waits for the meter, in seconds: longer than ID waits for the AI."""


class Meter(Protocol):
    def balance(self, person: UUID, owner: TokenOwner) -> TokenBalance: ...

    def reserve(self, asked: TokenReserve) -> TokenReservation: ...

    def read(self, asked: MeterRead) -> MeterAnswer: ...

    def draw(self, reservation: UUID, amount: int) -> None: ...

    def give_back(self, reservation: UUID) -> bool: ...


def no_tokens(needed: int | None = None, left: int | None = None) -> Refused:
    said = f": avläsningen kostar {needed} tokens och {left} finns kvar" if needed else ""
    return Refused(
        402,
        ProblemCode.NO_TOKENS,
        f"Saldot räcker inte{said}. Köp tokens i TrainMeet ID, koppla in egen AI, eller läs "
        "utan AI och svara själv på frågorna.",
    )


def failed(message: str = "AI:n kunde inte läsa fotot. Inget drogs.") -> Refused:
    return Refused(502, ProblemCode.READING_FAILED, message)


def _ids_no(status: int) -> Refused:
    if status == 402:
        return no_tokens()
    if status == 429:
        return Refused(
            429,
            ProblemCode.TOO_MANY,
            "Taket för i dag är nått i TrainMeet ID. Försök i morgon, eller koppla in egen AI.",
        )
    if status in (403, 404, 422):
        if status != 404:
            LOGGER.warning("ID sa nej till fotots saldo: %s.", status)
        return Refused(
            503, ProblemCode.UNAVAILABLE, "AI-avläsningen kräver ett konto i TrainMeet ID."
        )
    LOGGER.warning("ID svarade %s om fotots tokens.", status)
    return unavailable()


def _read[T: BaseModel](kind: type[T], answer: httpx.Response) -> T:
    try:
        return kind.model_validate(answer.json())
    except ValueError as error:
        LOGGER.warning("ID:s svar om fotot gick inte att läsa.")
        raise unavailable() from error


class IdMeter:
    def __init__(self, roles: IdRoles) -> None:
        self.roles = roles

    def balance(self, person: UUID, owner: TokenOwner) -> TokenBalance:
        answer = self.roles.call(
            "GET", "tokens", params={"person": str(person), "owner": f"{owner.kind}:{owner.id}"}
        )
        if answer.status_code != 200:
            raise _ids_no(answer.status_code)
        return _read(TokenBalance, answer)

    def reserve(self, asked: TokenReserve) -> TokenReservation:
        answer = self.roles.call("POST", "tokens/reservations", body=asked.model_dump(mode="json"))
        if answer.status_code not in (200, 201):
            raise _ids_no(answer.status_code)
        return _read(TokenReservation, answer)

    def read(self, asked: MeterRead) -> MeterAnswer:
        answer = self.roles.call(
            "POST", "meter", body=asked.model_dump(mode="json"), timeout=READ_TIMEOUT
        )
        if answer.status_code == 200:
            return _read(MeterAnswer, answer)
        LOGGER.warning("Mätaren svarade %s.", answer.status_code)
        if answer.status_code == 503:
            raise Refused(
                503,
                ProblemCode.UNAVAILABLE,
                "TrainMeets AI går inte att använda just nu. Inget drogs.",
            )
        raise failed()

    def draw(self, reservation: UUID, amount: int) -> None:
        answer = self.roles.call(
            "POST", f"tokens/reservations/{reservation}/draw", body={"amount": amount}
        )
        if answer.status_code != 200:
            LOGGER.warning("ID svarade %s när fotot skulle dras.", answer.status_code)
            raise unavailable()

    def give_back(self, reservation: UUID) -> bool:
        answer = self.roles.call("POST", f"tokens/reservations/{reservation}/return")
        if answer.status_code == 409:
            return False
        if answer.status_code != 200:
            LOGGER.warning("ID svarade %s när fotot lämnades tillbaka.", answer.status_code)
            raise unavailable()
        return True
