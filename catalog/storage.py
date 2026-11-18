"""Paid storage over the free level (CAT-132, TOKEN-16, TOKEN-29, TK10): every started GB over
the owner's free level costs 20 tokens a month, drawn from the owner's balance in TrainMeet ID.

The free level is 100 MB for a person and 2 GB for a club's fleet (TOKEN-16, TOKEN-29). Above
it the storage is counted in started GB per calendar month in Swedish time, as ID counts its
months. What is paid is kept per owner and month in storage_charge (0008_lagring.sql), and a
month's paid GB never go down: a picture removed and put back costs nothing more that month.

Each GB of each month is drawn with a key of its own in ID, catalog-lagring-<owner>-<month>-<n>,
and ID gives the same reservation for the same key (TOKEN-28). So the same GB is never paid
twice: not when two uploads pay at once, not when an answer was lost and Catalog asks again.
The GB are paid one by one, in order, outside any database transaction; the picture is then
saved under the owner's lock only if what is paid covers it (catalog/pictures.py, CAT-131).

The owner pays, not the one who uploads: the reservation has no person (contracts/tokens.py),
also for someone who edits a shared fleet (CAT-133) and at the daily round. A club's fleet pays
from the club's balance (TOKEN-29). The background removal itself is free (TOKEN-17); only what
it keeps counts in the storage.

When ID says the balance is short, or the day's cap is reached (TK15), nothing is drawn and
nothing grows: the pictures stay, removing them always works, and the month is marked unpaid
until it is paid. When ID cannot bill the owner at all, such as a trial account it does not
know, Catalog refuses over the free level as it does without ID.
"""

from __future__ import annotations

import logging
from typing import Final, Literal, Protocol
from uuid import UUID

from pydantic import ValidationError

from catalog.id_roles import IdRoles, unavailable
from contracts.tokens import TokenOwner, TokenReservation, TokenReservationState

LOGGER = logging.getLogger("catalog.storage")

GB: Final = 1024 * 1024 * 1024
PRICE_PER_GB: Final = 20
"""Tokens per started GB over the free level and month (TK10, CAT-132)."""
_GENERATIONS: Final = 5
"""How many times a GB's key is made anew after its reservation went back undrawn."""

Why = Literal["balance", "cap", "account"]


class NotPaid(Exception):
    """ID drew nothing: the balance is short, the day's cap is reached, or ID cannot bill the
    owner. Never holds a key or a token."""

    def __init__(self, why: Why) -> None:
        super().__init__(why)
        self.why: Why = why


class Payer(Protocol):
    def pay(self, owner: TokenOwner, key: str, amount: int, what: str) -> None:
        """Draw the amount from the owner's balance for the key, once: the same key again draws
        nothing more. Raises NotPaid, or Refused (503) when ID does not answer."""
        ...


def storage_key(owner: UUID, month: str, block: int) -> str:
    """The key in ID for one started GB of one month: the same GB always has the same key."""
    return f"catalog-lagring-{owner}-{month}-{block}"


class IdPayer:
    """The storage paid in TrainMeet ID: reserved without a person and drawn at once."""

    def __init__(self, roles: IdRoles) -> None:
        self.roles = roles

    def pay(self, owner: TokenOwner, key: str, amount: int, what: str) -> None:
        for generation in range(1, _GENERATIONS + 1):
            # A reservation that went back before it was drawn (it was held for half an hour
            # while ID did not answer) keeps its key: the GB gets a key made anew, the same for
            # every call that finds it so.
            asked = key if generation == 1 else f"{key}.{generation}"
            held = self.roles.call(
                "POST",
                "tokens/reservations",
                body={
                    "person": None,
                    "owner": owner.model_dump(mode="json"),
                    "amount": amount,
                    "key": asked,
                    "what": what[:120],
                },
            )
            if held.status_code not in (200, 201):
                raise _refused(held.status_code)
            reservation = _reservation(held.json())
            if reservation.state is TokenReservationState.DRAWN:
                return  # paid before, by this call or another
            if reservation.state is TokenReservationState.RETURNED:
                continue
            drawn = self.roles.call("POST", f"tokens/reservations/{reservation.id}/draw", body={})
            if drawn.status_code == 200:
                return
            if drawn.status_code != 409:  # 409: it went back in the meantime
                LOGGER.warning("ID svarade %s när lagringen skulle dras.", drawn.status_code)
                raise unavailable()
        LOGGER.warning("Lagringens reservation gick tillbaka gång på gång.")
        raise unavailable()


def _reservation(body: object) -> TokenReservation:
    try:
        return TokenReservation.model_validate(body)
    except ValidationError as error:
        LOGGER.warning("ID:s svar om lagringen gick inte att läsa.")
        raise unavailable() from error


def _refused(status: int) -> Exception:
    """What ID's no means for the storage."""
    if status == 402:
        return NotPaid("balance")
    if status == 429:
        return NotPaid("cap")
    if status in (403, 404, 422):
        # The owner is not in ID (a trial account), or ID does not bill Catalog's storage.
        if status != 404:
            LOGGER.warning("ID tar inte betalt för Catalogs lagring: %s.", status)
        return NotPaid("account")
    LOGGER.warning("ID svarade %s när lagringen skulle reserveras.", status)
    return unavailable()
