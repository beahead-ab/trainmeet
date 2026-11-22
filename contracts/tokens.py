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
                                                          (utan person: lagring, CAT-132)
    POST   /api/id/1/apps/tokens/reservations/{id}/draw   TokenDraw -> TokenReservation
    POST   /api/id/1/apps/tokens/reservations/{id}/return TokenReservation
    POST   /api/id/1/apps/tokens/reservations/{id}/refund TokenReservation (CAT-172)
    POST   /api/id/1/apps/meter                           MeterRead -> MeterAnswer (TOKEN-28)
    GET    /api/id/1/apps/meter/search                    MeterSearchState (TOKEN-30)
    POST   /api/id/1/apps/meter/search                    MeterSearch -> MeterSearchAnswer

Egen AI på kontot (TOKEN-03), för personen eller klubbens administratör:
    GET    /api/id/1/tokens/own-ai?owner=                 OwnAiState, or null
    PUT    /api/id/1/tokens/own-ai?owner=                 OwnAiChange -> OwnAiState
    DELETE /api/id/1/tokens/own-ai?owner=                 null

Ägarsidan (TOKEN-05, TOKEN-18), för TrainMeets ägare:
    GET    /api/id/1/owner                                OwnerPage
    PUT    /api/id/1/owner/settings                       TokenSettings -> OwnerPage

Köpen (TOKEN-02, TOKEN-11), för personen:
    GET    /api/id/1/tokens/shop                          TokenShop
    POST   /api/id/1/tokens/purchases                     TokenPurchase -> TokenCheckout

Att köra en träff, publicera, synka och importera utan AI kostar aldrig något (TOKEN-17), så de
delarna frågar aldrig saldot.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from contracts.common import Contract, Text

TOKENS_PER_PAGE = 12
"""En sida eller bild som AI skriver av eller läser (TK10, TOKEN-14)."""
TOKENS_PER_SEARCH = 24
"""En webbsökning efter förebildsfakta i Catalog (CAT-172, C22). De kommer tillbaka när
förebilden godkänns."""


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
    """Tillbakalämnad: arbetet blev inte av, eller misslyckades, eller tiden gick ut. Också en
    webbsökning vars förebild godkändes: det dragna kom tillbaka (CAT-172)."""


ReservationKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")]


class TokenReserve(Contract):
    """En app reserverar före ett arbete som kostar (TOKEN-24). Personen som arbetar ska få
    använda saldot: sitt eget, eller klubbens som medlem i klubben.

    Utan person är det appens egen debitering av lagring över den fria nivån (CAT-132,
    TOKEN-16): ingen person arbetar, och det dras från ägarens saldo, personens eller klubbens
    (TOKEN-29). Det gäller också för den som redigerar en delad vagnpark och för appens dagliga
    runda. Bara en app som debiterar lagring får reservera utan person (Catalog), och mätaren
    läser aldrig med en sådan reservation."""

    person: UUID | None = Field(
        description="Personen som arbetar. null bara för appens egen debitering av lagring."
    )
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
#
# With hold the meter reads and keeps the answer, but draws nothing: the reservation stays held,
# and the app draws the answer's cost, or gives it all back when the answer came too late to be
# used (Catalog's reading, CAT-145). Asked again, a held reservation with a kept answer gives
# that answer without reading again. A held reservation nobody draws goes back by itself.


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
    hold: bool = Field(
        default=False,
        description="Håll reservationen: mätaren läser och behåller svaret, men drar inget. "
        "Appen drar sedan cost, eller lämnar tillbaka allt när svaret inte används (CAT-145).",
    )
    hard: bool = Field(
        default=False,
        description="En svår följdfråga från CAD, där koden är osäker: den läses av den "
        "starkaste modellen inom EU, Claude Opus 5.5 med EU-profil (CAD19). Priset är detsamma, "
        "12 tokens per bild. Bara CAD får fråga så.",
    )


HARD_APPS: Final = frozenset({"cad"})
"""The apps whose questions may be read by the strongest model (CAD18, CAD19): only CAD's hard
follow-up questions."""


class MeterAnswer(Contract):
    text: str = Field(description="Avskriften, som AI:n skrev den.")
    cost: int = Field(
        description="Det som drogs: 12 tokens per bild (TOKEN-14), 0 med egen AI. Med hold är "
        "inget draget än: det är vad appen ska dra."
    )
    model: Text
    reservation: TokenReservation


# --- Webbsökningen (TOKEN-30, CAT-166–CAT-172, CAT-219, C40) ----------------------------------
#
#     GET    /api/id/1/apps/meter/search                    MeterSearchState
#     POST   /api/id/1/apps/meter/search                    MeterSearch -> MeterSearchAnswer
#     POST   /api/id/1/apps/tokens/reservations/{id}/refund TokenReservation
#
# The web search is the one exception from Bedrock (TK14): the meter asks Claude's web search in
# Anthropic's own API, outside the EU, with a key of its own that the apps never see (C40). Only
# Catalog may search (SEARCH_APPS), and only for a prototype's type data.
#
# The app sends the marking as data, never a prompt: the litt, the operator, the kind, the field
# profile and the fields it wants. The meter writes the prompt itself from that, so nothing else
# can leave: no pictures, no names, no vehicle numbers, no notes (CAT-166). The answer holds the
# values Claude proposes, each with the citations Claude gave for it, and every result of the
# real searches. Whether a source and its excerpt hold is for the app to check (CAT-167–CAT-169).
#
# A search costs 24 tokens (CAT-172), reserved before and drawn when the search is done; the same
# reservation twice gives the same answer and draws nothing twice (TOKEN-28), and a search that
# fails gives it all back. hold works as for a reading. The search always uses TrainMeet's key
# and costs the same with own AI on the account: an own AI has no web search of this kind. The
# caps per day and the month's budget count the search too (TOKEN-05, TK15).
#
# When the prototype the search led to is approved, the app gives the tokens back with refund
# (CAT-172): only a reservation that paid for a search can be refunded, and only once. What
# came from a month's free quota goes back within that month only (TK2).

SEARCH_APPS: Final = frozenset({"catalog"})
"""The apps that may search the web through the meter: only Catalog, for the prototypes."""

_MARKING = r"^[0-9A-Za-zÀ-ÖØ-öø-ÿ .,'()/+&-]*$"
"""What a marking is written with: letters, digits, spaces and a few signs. No line breaks,
no @, nothing that makes an address or a sentence of instructions."""


def _digits(text: str) -> int:
    return sum(1 for sign in text if sign.isdigit())


class MeterSearchField(Contract):
    """A field the search should fill: the key and what it means, from the app's own register,
    never from a person."""

    key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
    label: Annotated[str, StringConstraints(min_length=1, max_length=60, pattern=_MARKING)] = Field(
        description="What the field is, in English: Length over buffers."
    )
    unit: Annotated[str, StringConstraints(max_length=10, pattern=r"^[A-Za-z/]*$")] = Field(
        default="", description="The unit the value is given in: mm, t, km/h. Empty without one."
    )
    kind: Literal["text", "number", "integer"]


class MeterSearch(Contract):
    """Sök förebildens typuppgifter på webben. Bara märkningen skickas (CAT-166): litteran,
    bolaget, slaget och fältprofilen. Reservationen ska räcka till 24 tokens."""

    reservation: UUID
    litt: Annotated[str, StringConstraints(min_length=1, max_length=40, pattern=_MARKING)] = Field(
        description="Litteran eller UIC-typen, som den står på fordonet: Hbis, Rc6."
    )
    operator: Annotated[str, StringConstraints(max_length=80, pattern=_MARKING)] = Field(
        default="", description="Bolaget fordonet är märkt för: SJ, Green Cargo. Får vara tomt."
    )
    kind: Literal["locomotive", "freight_wagon", "passenger_coach", "multiple_unit", "other"] | None
    profile: Literal["SE", "EU", "US"] = Field(
        description="Fältprofilen: var i världen typen hör hemma, och vilka enheter som gäller."
    )
    fields: list[MeterSearchField] = Field(min_length=1, max_length=20)
    hold: bool = Field(
        default=False,
        description="Håll reservationen: mätaren söker och behåller svaret, men drar inget. "
        "Appen drar sedan cost, eller lämnar tillbaka allt när svaret inte används.",
    )

    @model_validator(mode="after")
    def _only_a_marking(self) -> Self:
        """A litt or an operator is never a vehicle's own number (CAT-155, CAT-166): a type has
        a few digits, an individual many."""
        if _digits(self.litt) > 5 or _digits(self.operator) > 4:
            raise ValueError("Märkningen är en littera och ett bolag, aldrig ett fordonsnummer.")
        if len({each.key for each in self.fields}) != len(self.fields):
            raise ValueError("Ett fält frågas bara en gång.")
        return self


class MeterCitation(Contract):
    """Where Claude says a value stands: a page from the real search, and an excerpt of it."""

    url: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    title: Annotated[str, StringConstraints(max_length=500)] = ""
    cited_text: Annotated[str, StringConstraints(max_length=2000)] = Field(
        default="", description="Utdraget ur sidan, som sökningen gav det."
    )


class MeterSearchValue(Contract):
    """A value Claude proposes for one of the fields, with its citations."""

    key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
    value: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    citations: list[MeterCitation] = Field(default_factory=list, max_length=20)


class MeterSearchResult(Contract):
    """A page the real search found."""

    url: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    title: Annotated[str, StringConstraints(max_length=500)] = ""
    page_age: Annotated[str, StringConstraints(max_length=80)] | None = None


class MeterSearchAnswer(Contract):
    values: list[MeterSearchValue] = Field(
        description="Det Claude föreslår, per fält. Ett fält utan uppgift står inte med."
    )
    results: list[MeterSearchResult] = Field(
        description="Allt de verkliga sökningarna gav: en källa som inte står här är påhittad."
    )
    searches: int = Field(ge=0, description="Hur många sökningar Claude gjorde.")
    cost: int = Field(
        description="Det som drogs: 24 tokens (CAT-172). Med hold är inget draget än."
    )
    model: Text
    reservation: TokenReservation


class MeterSearchTrial(Contract):
    """Ett fall ur provet av webbsökningen med den riktiga nyckeln (CAT-172), som en fil: ID:s
    prov (id/prov_webbsokning.py) sparar det, och Catalogs prov (catalog/prov_webbsokning.py)
    läser det och kontrollerar belägget på samma svar. Inget API: provet körs för hand. Bara
    märkningen, Claudes svar och vad det kostade, aldrig nyckeln."""

    asked: MeterSearch
    model: Text
    tool: Text
    text: str = Field(default="", max_length=20_000, description="Claudes svar som det skrevs.")
    values: list[MeterSearchValue]
    results: list[MeterSearchResult]
    searches: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0, description="Tokens och sökavgift, i dollar.")
    cost_sek: float = Field(ge=0)
    tokens: int = Field(ge=0, description="Kostnaden i TrainMeet-tokens med faktorn (TK6).")


class MeterSearchState(Contract):
    """Går webbsökningen att använda här, och vad kostar den (CAT-219)?"""

    available: bool = Field(description="False utan nyckeln till Anthropics API hos mätaren.")
    price: int = Field(description="24 tokens (CAT-172).")
    sent_to: Text = Field(description="Vem som söker, som personen läser det före första gången.")
    message: str | None = Field(default=None, description="Varför inte, när den inte går.")


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


# --- Ägarsidan (TOKEN-05, TOKEN-18, TK6, TK15) ------------------------------------------------
#
#     GET    /api/id/1/owner                                OwnerPage, for TrainMeet's owners
#     PUT    /api/id/1/owner/settings                       TokenSettings -> OwnerPage
#
# The owner sets the factors, the month's budget and the caps per day, and sees the cost, the
# revenue and what the factor makes of the measured cost per page. The month's budget raises an
# alarm at 80 % and stops TrainMeets AI at 100 %; own AI goes on (TK15).


class TokenSettings(Contract):
    ai_factor: float = Field(ge=1, le=100, description="Påslaget för AI (TK6), startvärde ×2.")
    storage_factor: float = Field(ge=1, le=100, description="Påslaget för lagring, ×10.")
    monthly_budget_sek: int = Field(
        ge=0, le=10_000_000, description="Månadens budget för TrainMeets AI, i kronor."
    )
    daily_cap_person: int = Field(ge=0, le=1_000_000, description="Tak per dygn för ett konto.")
    daily_cap_club: int = Field(ge=0, le=1_000_000, description="Tak per dygn för en klubb.")
    usd_sek: float = Field(gt=0, le=100, description="Kronor per dollar, för kostnaden.")
    price_in_usd: float = Field(ge=0, le=1000, description="Dollar per miljon tokens in.")
    price_out_usd: float = Field(ge=0, le=1000, description="Dollar per miljon tokens ut.")


class TokenMonth(Contract):
    month: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}$")]
    revenue_sek: float = Field(description="Betalda köp, med moms. Testläget räknas inte.")
    test_revenue_sek: float = Field(description="Köp i Stripes testläge, utan riktiga pengar.")
    cost_sek: float = Field(description="Vad TrainMeets AI kostade, uppmätt.")
    pages: int = Field(description="Sidor och bilder som TrainMeets AI läste.")
    searches: int = Field(default=0, description="Webbsökningar som mätaren gjorde (TOKEN-30).")


class OwnerPage(Contract):
    settings: TokenSettings
    page_tokens: int = Field(description="Tokens per AI-sida nu (TK10, startvärde 12).")
    cost_per_page_sek: float | None = Field(
        default=None, description="Uppmätt kostnad per sida de senaste 30 dagarna."
    )
    factor_page_tokens: int | None = Field(
        default=None,
        description="Vad faktorn gör av den uppmätta kostnaden, i tokens per sida (TK6).",
    )
    search_tokens: int = Field(
        default=TOKENS_PER_SEARCH, description="Tokens per webbsökning nu (CAT-172)."
    )
    cost_per_search_sek: float | None = Field(
        default=None,
        description="Uppmätt kostnad per webbsökning de senaste 30 dagarna, med sökavgiften.",
    )
    factor_search_tokens: int | None = Field(
        default=None,
        description="Vad faktorn gör av den uppmätta kostnaden, i tokens per webbsökning (TK6): "
        "priset stäms av mot det (CAT-172).",
    )
    budget_used: int = Field(ge=0, description="Hur mycket av månadens budget som är använd, %.")
    months: list[TokenMonth] = Field(description="Den här månaden och förra.")
