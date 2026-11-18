"""TrainMeet tokens i ID (#79): saldot, gratiskvoten och reservationerna (TOKEN-06, TOKEN-08).

Saldot finns per person och per klubb (TK1, TOKEN-12). Varje månad får personen 100 och klubben
300 tokens gratis; det som inte används sparas inte. Köpta tokens förfaller inte, och
gratiskvoten används först (TOKEN-14, docs/trainmeet-tokens.md avsnitt 5).

En app drar aldrig direkt. Den reserverar först, gör arbetet, och drar sedan det som det
kostade, eller lämnar tillbaka allt om det misslyckades, som TrainCatalog redan gör (TOKEN-24).
En reservation som ingen drar eller lämnar tillbaka går tillbaka av sig själv efter en stund.
Samma nyckel två gånger ger samma reservation och drar inte två gånger (TOKEN-28).

För personen, med ID:s sessionskaka:
    GET    /api/id/1/tokens                               [TokenBalance]: eget och klubbarnas

För apparna, med en token från Keycloaks client credentials (KONTO-34):
    GET    /api/id/1/apps/tokens?person=&owner=           TokenBalance
    POST   /api/id/1/apps/tokens/reservations             TokenReserve -> TokenReservation
    POST   /api/id/1/apps/tokens/reservations/{id}/draw   TokenDraw -> TokenReservation
    POST   /api/id/1/apps/tokens/reservations/{id}/return TokenReservation

Att köra en träff, publicera, synka och importera utan AI kostar aldrig något (TOKEN-17), så de
delarna frågar aldrig saldot.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from contracts.common import Contract, Text

TOKENS_PER_PAGE = 12
"""En sida eller bild som AI skriver av eller läser (TK10, TOKEN-14)."""


class TokenOwnerKind(StrEnum):
    """Vems saldo (TK1): personens, för egna fordon och moduler, eller klubbens, för
    träffarnas import (TK16)."""

    PERSON = "person"
    CLUB = "club"


class TokenOwner(Contract):
    kind: TokenOwnerKind
    id: UUID


class TokenBalance(Contract):
    """Saldot som det ser ut nu (TOKEN-01, TOKEN-12)."""

    owner: TokenOwner
    title: Text = Field(description="Vems saldo, som det visas: personens namn eller klubbens.")
    free_left: int = Field(
        ge=0, description="Det som är kvar av månadens gratiskvot. Sparas inte till nästa månad."
    )
    free_monthly: int = Field(
        ge=0, description="Månadens gratiskvot: 100 per person, 300 per klubb."
    )
    bought: int = Field(ge=0, description="Köpta tokens som är kvar. De förfaller inte.")
    reserved: int = Field(
        ge=0, description="Hålls av reservationer som inte är dragna eller tillbakalämnade än."
    )
    available: int = Field(ge=0, description="Det som går att använda nu: gratis och köpt.")
    month: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}$")] = Field(
        description="Månaden gratiskvoten gäller, i svensk tid."
    )


class TokenReservationState(StrEnum):
    HELD = "held"
    """Reserverad: arbetet pågår."""
    DRAWN = "drawn"
    """Dragen: det som arbetet kostade är draget, och resten tillbakalämnat."""
    RETURNED = "returned"
    """Tillbakalämnad: arbetet blev inte av, eller misslyckades, eller tiden gick ut."""


ReservationKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")]


class TokenReserve(Contract):
    """En app reserverar före ett arbete som kostar (TOKEN-24). Personen som arbetar ska få
    använda saldot: sitt eget, eller klubbens som medlem i klubben."""

    person: UUID
    owner: TokenOwner
    amount: int = Field(gt=0, le=100_000)
    key: ReservationKey = Field(
        description="Appens egen nyckel för arbetet. Samma nyckel igen ger samma reservation."
    )
    what: Text = Field(
        max_length=120, description="Vad det gäller, som det visas: t.ex. 12 sidor i importen."
    )


class TokenDraw(Contract):
    """Dra det som arbetet kostade. Resten lämnas tillbaka. Utan belopp dras allt."""

    amount: int | None = Field(default=None, ge=0)


class TokenReservation(Contract):
    id: UUID
    owner: TokenOwner
    amount: int = Field(description="Det reserverade.")
    drawn: int = Field(default=0, description="Det dragna, när reservationen är dragen.")
    state: TokenReservationState
    what: Text
    at: datetime
    expires: datetime = Field(description="När en reservation som ingen drar går tillbaka.")
    balance: TokenBalance = Field(description="Saldot efter det här.")
