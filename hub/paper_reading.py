"""Vem som står för AI-läsningen när en förare fotar ett köruppdrag som saknas i planen (LOK-33,
PLAN-40, TK16).

The hub's own AI comes first, as everywhere (TOKEN-13): it reads at no token cost. Without it,
in the cloud hub with TrainMeet ID, TrainMeets AI reads through the meter in ID (#79), and the
meet chose in Förarna whose tokens pay:

- the driver's own, the default: the driver must be logged in with TrainMeet ID;
- the meet's: chosen by someone logged in with ID, whose club pays for a meet in ID, and else
  they themselves, as for the import (TK16). The driver needs no account.

The price is 12 tokens a page (TOKEN-14), nothing when the account's own AI reads (TK4). The
choice is kept per meet in the hub's own store (hub/local.py), beside the meet's other local
settings: it names a person in ID, so it stays out of the meet package, and it is made in
Planering before any run exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException

from contracts import driver as contract
from contracts.drift import PaperPayer
from contracts.tokens import TOKENS_PER_PAGE, TokenOwner, TokenOwnerKind
from hub.id_roles import IdRoles
from hub.id_tokens import IdTokens
from hub.local import LocalLogin, PaperReading

NO_AI = "Hubben har ingen AI som kan läsa pappret. Be trafikledningen om hjälp."
NOT_SET = "Träffens tokens är inte kopplade till något saldo än. Be trafikledningen om hjälp."
LOG_IN = (
    "Pappret läses med dina egna tokens. Logga in med TrainMeet ID, eller be trafikledningen "
    "om hjälp."
)
OWN_AI = "Hubbens egen AI"


class NoPayer(Exception):
    """The reading cannot be paid for: why, in Swedish, and the HTTP status to say it with."""

    def __init__(self, status: int, message: str, *, log_in: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.log_in = log_in


@dataclass(frozen=True)
class Payment:
    """How a reading is paid: by whom, from whose balance, and whether it is free (the hub's
    own AI, or own AI on the account in ID)."""

    paid_by: PaperPayer
    title: str
    available: int | None
    free: bool
    person: str | None = None
    owner: TokenOwner | None = None

    def price(self, pages: int) -> int:
        return 0 if self.free else TOKENS_PER_PAGE * pages


class PaperReadings:
    def __init__(self, login: LocalLogin, tokens: IdTokens | None, roles: IdRoles | None) -> None:
        self.login = login
        self.tokens = tokens
        self.roles = roles

    @property
    def metered(self) -> bool:
        """TrainMeets AI through the meter in ID: the cloud hub."""
        return self.tokens is not None and self.roles is not None

    def owner(self, person: str, id_meet: UUID | None) -> TokenOwner:
        """The meet's owner (TK16): the club of the meet in ID, else the person."""
        if id_meet is not None and self.roles is not None:
            club = next((m.club for m in self.roles.meets(person) if m.id == id_meet), None)
            if club is not None:
                return TokenOwner(kind=TokenOwnerKind.CLUB, id=club)
        return TokenOwner(kind=TokenOwnerKind.PERSON, id=UUID(person))

    def payment(self, meet: str, id_meet: UUID | None, driver_person: str | None) -> Payment:
        """How the driver's paper would be read now. Raises NoPayer, or HTTPException when ID
        does not answer."""
        own = self.login.ai()
        if own is not None:
            return Payment(PaperPayer.HUB, OWN_AI, None, free=True)
        if self.tokens is None or not self.metered:
            raise NoPayer(422, NO_AI)
        choice = self.login.paper_reading(meet)
        if choice.payer == "meet":
            if choice.person is None:
                raise NoPayer(422, NOT_SET)
            person, paid_by = choice.person, PaperPayer.MEET
            owner = self.owner(person, id_meet)
        else:
            if driver_person is None:
                raise NoPayer(403, LOG_IN, log_in=True)
            person, paid_by = driver_person, PaperPayer.DRIVER
            owner = TokenOwner(kind=TokenOwnerKind.PERSON, id=UUID(person))
        balance = self.tokens.balance(person, owner)
        return Payment(
            paid_by,
            balance.title,
            balance.available,
            free=balance.own_ai is not None,
            person=person,
            owner=owner,
        )

    def settings(
        self, meet: str, id_meet: UUID | None, may_change: bool
    ) -> contract.PaperReadingSettings:
        """The meet's choice for Förarna. The meet's balance only to whoever may change it:
        everyone may look at the plan (S1), not at a club's tokens."""
        choice = self.login.paper_reading(meet)
        own = self.login.ai()
        title = available = None
        if may_change and choice.payer == "meet" and choice.person and self.tokens:
            try:
                balance = self.tokens.balance(choice.person, self.owner(choice.person, id_meet))
                title, available = balance.title, balance.available
            except HTTPException:
                title = available = None
        return contract.PaperReadingSettings(
            payer="meet" if choice.payer == "meet" else "driver",
            payer_title=title,
            available=available,
            per_page=TOKENS_PER_PAGE,
            own_ai=own.model if own is not None else None,
            trainmeet_ai=self.metered,
            may_change=may_change,
        )

    def choose(self, meet: str, payer: str, person: str | None) -> None:
        """Träffens tokens or the driver's own. The meet's are chosen logged in with ID where
        the hub reaches the meter: whose club pays is known only then (TK16)."""
        if payer == "meet" and person is None and self.metered:
            raise NoPayer(
                422,
                "Välj träffens tokens inloggad med TrainMeet ID: klubbens saldo används av "
                "klubbens medlemmar.",
            )
        self.login.set_paper_reading(
            meet, PaperReading("meet", person) if payer == "meet" else PaperReading()
        )

    def price(
        self, meet: str, id_meet: UUID | None, driver_person: str | None, pages: int
    ) -> contract.PaperPrice:
        """The price before anything is read (TOKEN-14), or why it cannot be read."""
        try:
            found = self.payment(meet, id_meet, driver_person)
        except NoPayer as error:
            return contract.PaperPrice(
                pages=pages,
                price=TOKENS_PER_PAGE * pages,
                per_page=TOKENS_PER_PAGE,
                ready=False,
                message=error.message,
                log_in=error.log_in,
            )
        cost = found.price(pages)
        short = found.available is not None and found.available < cost
        return contract.PaperPrice(
            pages=pages,
            price=cost,
            per_page=0 if found.free else TOKENS_PER_PAGE,
            paid_by=found.paid_by,
            payer=found.title,
            available=found.available,
            ready=not short,
            message=short_of(found.available or 0, cost) if short else None,
        )


def short_of(available: int, cost: int) -> str:
    return (
        f"Saldot räcker inte: {available} tokens kvar, {cost} behövs. Be trafikledningen om hjälp."
    )
