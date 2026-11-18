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
    POST   /api/id/1/apps/meter                           MeterRead -> MeterAnswer (TOKEN-28)

Egen AI på kontot (TOKEN-03), för personen eller klubbens administratör:
    GET    /api/id/1/tokens/own-ai?owner=                 OwnAiState, or null
    PUT    /api/id/1/tokens/own-ai?owner=                 OwnAiChange -> OwnAiState
    DELETE /api/id/1/tokens/own-ai?owner=                 null

Köpen (TOKEN-02, TOKEN-11), för personen:
    GET    /api/id/1/tokens/shop                          TokenShop
    POST   /api/id/1/tokens/purchases                     TokenPurchase -> TokenCheckout

Att köra en träff, publicera, synka och importera utan AI kostar aldrig något (TOKEN-17), så de
delarna frågar aldrig saldot.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
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
    own_ai: Text | None = Field(
        default=None,
        description="Modellen i kontots egen AI, om den är inkopplad: då dras inga AI-tokens.",
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
    amount: int = Field(
        ge=0,
        le=100_000,
        description="Noll när kontot har egen AI: mätaren läser då med den och drar inget (TK4).",
    )
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


# --- Mätaren (TOKEN-28, TK17) ----------------------------------------------------------------
#
#     POST   /api/id/1/apps/meter                           MeterRead -> MeterAnswer
#
# TrainMeets AI (TK12, TK14): an app sends the page or the picture with its reservation and gets
# the transcription and what it cost. The meter holds TrainMeet's key to Claude through Amazon
# Bedrock in the EU; the apps never see it (TK7). The same reservation twice gives the same
# answer and draws nothing twice.


class MeterImage(Contract):
    media_type: Literal["image/png", "image/jpeg", "image/webp", "image/gif"]
    data: str = Field(
        min_length=1, max_length=14_000_000, description="Bilden i base64, högst cirka 10 MB."
    )


class MeterRead(Contract):
    """Läs bilderna med TrainMeets AI. Reservationen ska räcka till 12 tokens per bild."""

    reservation: UUID
    prompt: str = Field(min_length=1, max_length=20_000, description="Vad AI:n ska göra.")
    images: list[MeterImage] = Field(min_length=1, max_length=4)
    max_tokens: int = Field(default=8192, ge=16, le=16_000)


class MeterAnswer(Contract):
    text: str = Field(description="Avskriften, som AI:n skrev den.")
    cost: int = Field(description="Det som drogs: 12 tokens per bild (TOKEN-14).")
    model: Text
    reservation: TokenReservation


# --- Köp (TOKEN-02, TOKEN-11, TK10) ---------------------------------------------------------
#
#     GET    /api/id/1/tokens/shop                          TokenShop
#     POST   /api/id/1/tokens/purchases                     TokenPurchase -> TokenCheckout
#     POST   /api/id/1/stripe/webhook                       Stripe's event, signed by Stripe
#
# The person pays by card with Stripe Checkout, and Stripe sends the receipt by e-mail. The
# tokens come when Stripe says the payment is done, once. Buying is open only in Stripe's test
# mode until the question MOMS is decided (#79, #92).


class TokenPackage(Contract):
    tokens: Literal[500, 1500, 5000]
    price_sek: int = Field(description="Priset i kronor, med moms (TK10).")


PACKAGES: tuple[TokenPackage, ...] = (
    TokenPackage(tokens=500, price_sek=49),
    TokenPackage(tokens=1500, price_sek=129),
    TokenPackage(tokens=5000, price_sek=399),
)


class TokenShop(Contract):
    mode: Literal["off", "test"] = Field(
        description="Av: inga köp. Test: Stripes testläge, inga riktiga pengar dras."
    )
    packages: list[TokenPackage]


class TokenPurchase(Contract):
    """Köp ett paket till sitt eget saldo, eller till klubbens som dess administratör."""

    owner: TokenOwner
    tokens: Literal[500, 1500, 5000]


class TokenCheckout(Contract):
    url: str = Field(description="Stripes betalsida, dit webbläsaren går för att betala.")


# --- Egen AI på kontot (TOKEN-03, TOKEN-10, TK4) ---------------------------------------------
#
#     GET    /api/id/1/tokens/own-ai?owner=                 OwnAiState, or null
#     PUT    /api/id/1/tokens/own-ai?owner=                 OwnAiChange -> OwnAiState
#     DELETE /api/id/1/tokens/own-ai?owner=                 null
#
# A person's or a club's own AI service. The meter reads with it instead of TrainMeets AI and
# draws no tokens. The key is sent when it is put in or changed, and never shown again.

OwnAiFormat = Literal["chat", "claude"]


class OwnAiState(Contract):
    owner: TokenOwner
    format: OwnAiFormat = Field(
        description="chat: det vanliga chatt-API:t. claude: Claudes eget API (H59)."
    )
    address: Text
    model: Text
    key_set: bool = Field(description="False om nyckeln behöver läggas in igen.")
    checked: datetime | None = Field(
        default=None, description="När ID senast provade att modellen läser bilder (H70)."
    )


class OwnAiChange(Contract):
    format: OwnAiFormat
    address: str = Field(min_length=8, max_length=300)
    model: str = Field(min_length=1, max_length=120)
    key: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Skickas när den läggs in eller byts; annars står den kvar.",
    )
