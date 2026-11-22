"""Mätaren (#79, TOKEN-28, TK17): TrainMeets AI, med reservationen från saldot.

An app sends the pages or pictures with its reservation and gets the transcription and what it
cost: 12 tokens a picture (TOKEN-14). The meter holds TrainMeet's key to Claude through Amazon
Bedrock in the EU (TK14, TOKEN-20); the apps never see it (TK7). Egen AI is the first choice and
TrainMeets AI an option (TK12): the app asks the person before the first time.

The same reservation twice gives the same answer and draws nothing twice: the answer is kept for
a day under the reservation, with its price. If Claude does not answer, the reservation goes back
and nothing is drawn. The AI is asked outside the database transaction, so a slow answer holds no
lock.

The web search (TOKEN-30, C40) is the one thing that does not go to Bedrock: Meter.search() asks
Claude's web search in Anthropic's own API (id/search.py) with the marking of a vehicle type, for
24 tokens (CAT-172), with the same reservation, hold, kept answer and give-back as a reading.
Only Catalog may search, and always with TrainMeet's key: an account's own AI has no web search.

With hold (MeterRead.hold) the meter reads and keeps the answer but draws nothing: the reservation
stays held, MeterAnswer.cost says what the app is to draw, and the app draws it, or gives it all
back when the answer came too late to be used (Catalog's reading, CAT-145). A held reservation
with a kept answer gives that answer again without asking the AI, so the app can ask again after
a lost answer. A held reservation nobody draws goes back by itself (id/tokens.py), and a draw
can never take more than was reserved.

Settings, from the environment:

ID_METER_KEY_FILE          A file in ID's vault with the AWS access key for Bedrock: its id on
                           the first line and its secret on the second. Without the file the
                           meter is off. The key may invoke the two EU profiles, and their
                           models in every EU region a profile sends a call on to.
ID_METER_REGION            Default eu-north-1, Stockholm, where the call is made. The EU profile
                           sends it on to one of the EU's regions and never outside them (TK14).
ID_METER_MODEL             Default eu.anthropic.claude-sonnet-5-5: Claude Sonnet 5.5 with the EU
                           profile, which the prices build on (TOKEN-22).
ID_METER_MODEL_HARD        Default eu.anthropic.claude-opus-5-5: Claude Opus 5.5 with the EU
                           profile, the strongest model in the EU, for CAD's hard follow-up
                           questions only (MeterRead.hard, CAD19). Claude Fable 5.2, which CAD18
                           chose, is not in the EU. The price for the person is the same 12 tokens
                           a picture; TrainMeet pays the rest.
ID_METER_HARD_FACTOR       Default 2: what a hard question's tokens cost against the standard
                           model's, at list prices (Opus 5.5 $4/$20 per million against Sonnet
                           5.5's $2/$10), so that the owner's budget (TK6, TK15) counts them right.
ID_METER_PROFILE_FACTOR    Default 1.1: what the EU profile costs against the list prices the
                           owner's prices build on. AWS takes 10 % more for it than for the global
                           profile. The web search is priced at Anthropic's list prices and is not
                           counted with it.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import quote
from uuid import UUID

import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from contracts.id import ProblemCode
from contracts.tokens import (
    HARD_APPS,
    SEARCH_APPS,
    TOKENS_PER_PAGE,
    TOKENS_PER_SEARCH,
    MeterAnswer,
    MeterRead,
    MeterSearch,
    MeterSearchAnswer,
    MeterSearchResult,
    MeterSearchState,
    MeterSearchValue,
    TokenDraw,
    TokenOwner,
    TokenReservation,
    TokenReservationState,
)
from id.db import Database
from id.roles import Refused
from id.search import NOT_CONNECTED, SENT_TO, Searched, Searcher, SearchFailed
from id.tokens import Tokens

LOGGER = logging.getLogger("id.meter")

API_VERSION: Final = "bedrock-2023-05-31"
"""The Messages API's version in the body, as Bedrock's InvokeModel takes it for Claude."""
KEPT: Final = timedelta(days=1)
"""How long an answer is kept, for an app that asks again with the same reservation."""


@dataclass(frozen=True)
class ClaudeRead:
    """Claude's text, and the tokens AWS counted for it: what the reading cost."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class Kept:
    """An answer kept under its reservation, with what it costs: 12 tokens a picture, or 0
    with own AI. Older answers, kept before the price was, have none: theirs is what was drawn."""

    text: str
    model: str
    cost: int | None


class MeterFailed(Exception):
    """Claude did not give a transcription. The message is for the person; never the key."""


@dataclass(frozen=True)
class MeterSettings:
    key_file: Path
    region: str = "eu-north-1"
    model: str = "eu.anthropic.claude-sonnet-5-5"
    hard_model: str = "eu.anthropic.claude-opus-5-5"
    hard_factor: float = 2.0
    profile_factor: float = 1.1


def settings_from(env: Mapping[str, str] | None = None) -> MeterSettings | None:
    source = os.environ if env is None else env
    key_file = source.get("ID_METER_KEY_FILE", "").strip()
    if not key_file or not Path(key_file).is_file():
        return None
    return MeterSettings(
        key_file=Path(key_file),
        region=source.get("ID_METER_REGION", "").strip() or "eu-north-1",
        model=source.get("ID_METER_MODEL", "").strip() or MeterSettings.model,
        hard_model=source.get("ID_METER_MODEL_HARD", "").strip() or MeterSettings.hard_model,
        hard_factor=_factor(source.get("ID_METER_HARD_FACTOR", ""), MeterSettings.hard_factor),
        profile_factor=_factor(
            source.get("ID_METER_PROFILE_FACTOR", ""), MeterSettings.profile_factor
        ),
    )


def _factor(given: str, otherwise: float) -> float:
    try:
        factor = float(given.strip())
    except ValueError:
        return otherwise
    return factor if factor >= 1 else otherwise


class Claude(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def hard_model(self) -> str:
        """The strongest model in the EU, for CAD's hard follow-up questions (CAD19)."""
        ...

    @property
    def hard_factor(self) -> float:
        """What the strongest model's tokens cost against the standard model's."""
        ...

    @property
    def profile_factor(self) -> float:
        """What the way to Claude costs against the list prices: the EU profile's 10 %."""
        ...

    def read(
        self,
        prompt: str,
        images: Sequence[tuple[str, str]],
        max_tokens: int,
        *,
        hard: bool = False,
    ) -> ClaudeRead:
        """The model's text for the pictures (media type, base64), with the strongest model
        when hard. Raises MeterFailed."""
        ...


class Budget(Protocol):
    def allow(self) -> None: ...

    def record(
        self,
        pages: int,
        input_tokens: int,
        output_tokens: int,
        *,
        searches: int = 0,
        extra_usd: float = 0.0,
    ) -> None:
        """What a reading or a web search cost: the tokens at the owner's prices, and for a
        search what the searches cost beside them."""
        ...


@dataclass
class BedrockClaude:
    """Claude in Amazon Bedrock with the EU profile (TK14, TOKEN-20): InvokeModel at
    bedrock-runtime in the region, which sends the call on to one of the EU's regions and never
    outside them. Bedrock's Messages API at bedrock-mantle has these models only outside the EU.
    Signed with AWS's own SigV4 (botocore). Called with httpx, as the rest of ID, rather than
    with Anthropic's SDK, whose HTTP library would change the test client for the whole
    project."""

    settings: MeterSettings
    http: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=120.0), repr=False)

    @property
    def model(self) -> str:
        return self.settings.model

    @property
    def hard_model(self) -> str:
        return self.settings.hard_model

    @property
    def hard_factor(self) -> float:
        return self.settings.hard_factor

    @property
    def profile_factor(self) -> float:
        return self.settings.profile_factor

    def address(self, model: str) -> str:
        """InvokeModel for the model or profile, in the region the call is made from."""
        return (
            f"https://bedrock-runtime.{self.settings.region}.amazonaws.com"
            f"/model/{quote(model, safe='')}/invoke"
        )

    def read(
        self,
        prompt: str,
        images: Sequence[tuple[str, str]],
        max_tokens: int,
        *,
        hard: bool = False,
    ) -> ClaudeRead:
        try:
            key_id, secret = self.settings.key_file.read_text(encoding="utf-8").split()[:2]
        except (OSError, ValueError) as error:
            raise MeterFailed("TrainMeets AI är inte inkopplad.") from error
        content: list[dict[str, Any]] = [
            {"type": "image", "source": {"type": "base64", "media_type": kind, "data": data}}
            for kind, data in images
        ]
        content.append({"type": "text", "text": prompt})
        model = self.settings.hard_model if hard else self.settings.model
        address = self.address(model)
        body = json.dumps(
            {
                # InvokeModel takes the model in the address and the version in the body.
                "anthropic_version": API_VERSION,
                # Claude Opus 5.5 always thinks, and its thinking counts in max_tokens: a short
                # answer still needs room (CAD18, CAD19).
                "max_tokens": max(max_tokens, 16_000) if hard else max_tokens,
                # A transcription needs no long thinking; the price counts a page (TOKEN-22). A
                # hard follow-up question is where the code was unsure: it reads carefully.
                "output_config": {"effort": "high" if hard else "low"},
                "messages": [{"role": "user", "content": content}],
            }
        ).encode()
        signed = AWSRequest(
            method="POST",
            url=address,
            data=body,
            headers={"content-type": "application/json", "accept": "application/json"},
        )
        SigV4Auth(Credentials(key_id, secret), "bedrock", self.settings.region).add_auth(signed)
        try:
            answer = self.http.post(address, content=body, headers=dict(signed.headers))
        except httpx.HTTPError as error:
            raise MeterFailed("TrainMeets AI svarar inte just nu.") from error
        if answer.status_code == 429:
            raise MeterFailed("TrainMeets AI har för många frågor just nu.")
        if answer.status_code != 200:
            # The refusal's own words are not passed on: they are for the operator's log.
            LOGGER.warning("Bedrock svarade %s.", answer.status_code)
            raise MeterFailed(f"TrainMeets AI svarade med fel {answer.status_code}.")
        try:
            message = answer.json()
            stop = message.get("stop_reason")
            text = "".join(
                block.get("text", "") for block in message["content"] if block.get("type") == "text"
            )
            usage = message.get("usage") or {}
            used = (int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)))
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise MeterFailed("TrainMeets AI svarade, men inte som väntat.") from error
        if stop == "refusal":
            raise MeterFailed("TrainMeets AI ville inte läsa bilden.")
        if stop == "max_tokens":
            raise MeterFailed("Avskriften blev för lång för en fråga.")
        return ClaudeRead(text, *used)


class OwnAiLookup(Protocol):
    def __call__(self, owner: TokenOwner) -> OwnAiUse | None: ...


class OwnAiUse(Protocol):
    @property
    def model(self) -> str: ...

    def read(self, prompt: str, images: Sequence[tuple[str, str]], max_tokens: int) -> str: ...


class Meter:
    def __init__(
        self,
        db: Database,
        tokens: Tokens,
        claude: Claude | None,
        own_ai: OwnAiLookup = lambda owner: None,
        budget: Budget | None = None,
        searcher: Searcher | None = None,
    ) -> None:
        self.db = db
        self.tokens = tokens
        self.claude = claude
        self.own_ai = own_ai
        self.budget = budget
        self.searcher = searcher

    def read(self, app: str, asked: MeterRead) -> MeterAnswer:
        held = self.tokens.reservation(app, asked.reservation)
        if not self.tokens.has_person(app, asked.reservation):
            # The app's own billing of its storage (CAT-132) pays for storage, never for AI.
            raise Refused(
                422, ProblemCode.INVALID, "Reservationen gäller lagring och läses inte med AI."
            )
        if held.state == TokenReservationState.DRAWN:
            drawn = self._kept(asked.reservation)
            if drawn is None:
                raise Refused(409, ProblemCode.CONFLICT, "Reservationen är redan dragen.")
            return MeterAnswer(
                text=drawn.text, cost=held.drawn, model=drawn.model, reservation=held
            )
        if held.state == TokenReservationState.RETURNED:
            raise Refused(
                409,
                ProblemCode.CONFLICT,
                "Reservationen är tillbakalämnad, eller har gått ut. Reservera igen.",
            )
        kept = self._kept(asked.reservation)
        if kept is None:
            kept = self._ask(app, asked, held)
        return self._answer(app, asked, kept)

    def _ask(self, app: str, asked: MeterRead, held: TokenReservation) -> Kept:
        """Read with the owner's own AI, or with TrainMeets AI, and keep the answer with its
        price. If the AI does not answer, the reservation goes back and nothing is drawn."""
        own = self.own_ai(held.owner)
        if own is not None:
            return self._own(app, asked, own)
        if self.claude is None:
            raise Refused(503, ProblemCode.UNAVAILABLE, "TrainMeets AI är inte inkopplad här.")
        if asked.hard and app not in HARD_APPS:
            raise Refused(
                422,
                ProblemCode.INVALID,
                "Den starkaste modellen läser bara CAD:s svåra följdfrågor.",
            )
        cost = TOKENS_PER_PAGE * len(asked.images)
        if held.amount < cost:
            raise Refused(
                422,
                ProblemCode.INVALID,
                f"Reservationen räcker inte: {cost} tokens behövs för {len(asked.images)} bilder.",
            )
        if self.budget is not None:
            try:
                self.budget.allow()
            except Refused:
                self.tokens.give_back(app, asked.reservation)
                raise
        try:
            read = self.claude.read(
                asked.prompt,
                [(i.media_type, i.data) for i in asked.images],
                asked.max_tokens,
                hard=asked.hard,
            )
        except MeterFailed as error:
            self.tokens.give_back(app, asked.reservation)
            raise Refused(502, ProblemCode.UNAVAILABLE, f"{error} Inget drogs.") from None
        factor = (self.claude.hard_factor if asked.hard else 1.0) * self.claude.profile_factor
        if self.budget is not None:
            # The owner's budget is priced in the standard model's tokens at list prices: a hard
            # question's count as many as they cost (CAD18, CAD19), and the EU profile's 10 %
            # with them (TK14).
            self.budget.record(
                len(asked.images),
                round(read.input_tokens * factor),
                round(read.output_tokens * factor),
            )
        model = self.claude.hard_model if asked.hard else self.claude.model
        return self._keep(asked.reservation, read.text, model, cost)

    def _own(self, app: str, asked: MeterRead, own: OwnAiUse) -> Kept:
        """The owner's own AI (TK4): read with it, and it costs nothing. Without hold the
        reservation is drawn with nothing, so that the same reservation again gives the same
        answer."""
        try:
            text = own.read(
                asked.prompt, [(i.media_type, i.data) for i in asked.images], asked.max_tokens
            )
        except MeterFailed as error:
            self.tokens.give_back(app, asked.reservation)
            raise Refused(502, ProblemCode.UNAVAILABLE, f"{error} Inget drogs.") from None
        return self._keep(asked.reservation, text, own.model, 0)

    def _answer(self, app: str, asked: MeterRead, kept: Kept) -> MeterAnswer:
        """The kept answer for a held reservation. With hold the reservation stays held and the
        app draws the cost itself; without, the cost is drawn now and the rest goes back."""
        cost = kept.cost if kept.cost is not None else TOKENS_PER_PAGE * len(asked.images)
        if asked.hold:
            reservation = self.tokens.reservation(app, asked.reservation)
        else:
            reservation = self.tokens.draw(app, asked.reservation, TokenDraw(amount=cost))
        return MeterAnswer(text=kept.text, cost=cost, model=kept.model, reservation=reservation)

    def _keep(
        self, reservation: UUID, text: str, model: str, cost: int, kind: str = "read"
    ) -> Kept:
        """The first answer for the reservation is the one: two at once give the same. A
        search's answer also marks its reservation as one that paid for a web search, the only
        kind that can be refunded (CAT-172)."""
        now = datetime.now(UTC)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM meter_answer WHERE at < %s", (now - KEPT,))
            conn.execute(
                "INSERT INTO meter_answer (reservation_id, text, model, cost, at, kind) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (reservation_id) DO NOTHING",
                (reservation, text, model, cost, now, kind),
            )
            row = conn.execute(
                "SELECT text, model, cost, kind FROM meter_answer WHERE reservation_id = %s",
                (reservation,),
            ).fetchone()
            assert row is not None
            if row["kind"] != kind:
                raise _other_use()
            if kind == "search":
                conn.execute(
                    "UPDATE token_reservation SET search = true WHERE id = %s", (reservation,)
                )
        return Kept(str(row["text"]), str(row["model"]), row["cost"])

    def _kept(self, reservation: UUID, kind: str = "read") -> Kept | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT text, model, cost, kind FROM meter_answer "
                "WHERE reservation_id = %s AND at >= %s",
                (reservation, datetime.now(UTC) - KEPT),
            ).fetchone()
        if row is None:
            return None
        if row["kind"] != kind:
            raise _other_use()
        return Kept(str(row["text"]), str(row["model"]), row["cost"])

    # --- The web search (TOKEN-30, CAT-166, CAT-172, C40) --------------------------------------

    def search_state(self) -> MeterSearchState:
        """Can the web search be used here, and what does it cost (CAT-219)?"""
        on = self.searcher is not None
        return MeterSearchState(
            available=on,
            price=TOKENS_PER_SEARCH,
            sent_to=SENT_TO,
            message=None if on else NOT_CONNECTED,
        )

    def search(self, app: str, asked: MeterSearch) -> MeterSearchAnswer:
        """Search the web for the marking's type data: 24 tokens, the same reservation twice
        gives the same answer and draws nothing twice (TOKEN-28)."""
        if app not in SEARCH_APPS:
            raise Refused(403, ProblemCode.FORBIDDEN, "Bara Catalog söker på webben här.")
        held = self.tokens.reservation(app, asked.reservation)
        if not self.tokens.has_person(app, asked.reservation):
            raise Refused(
                422, ProblemCode.INVALID, "Reservationen gäller lagring och söker inte med AI."
            )
        if held.state == TokenReservationState.DRAWN:
            drawn = self._kept(asked.reservation, "search")
            if drawn is None:
                raise Refused(409, ProblemCode.CONFLICT, "Reservationen är redan dragen.")
            return self._searched(drawn, held.drawn, held)
        if held.state == TokenReservationState.RETURNED:
            raise Refused(
                409,
                ProblemCode.CONFLICT,
                "Reservationen är tillbakalämnad, eller har gått ut. Reservera igen.",
            )
        kept = self._kept(asked.reservation, "search")
        if kept is None:
            kept = self._search(app, asked, held)
        cost = kept.cost if kept.cost is not None else TOKENS_PER_SEARCH
        if asked.hold:
            reservation = self.tokens.reservation(app, asked.reservation)
        else:
            reservation = self.tokens.draw(app, asked.reservation, TokenDraw(amount=cost))
        return self._searched(kept, cost, reservation)

    def _search(self, app: str, asked: MeterSearch, held: TokenReservation) -> Kept:
        """Ask Claude's web search, always with TrainMeet's own key, and keep the answer with
        its price. Whatever fails gives the reservation back, and nothing is drawn."""
        if self.searcher is None:
            self.tokens.give_back(app, asked.reservation)
            raise Refused(503, ProblemCode.UNAVAILABLE, NOT_CONNECTED)
        if held.amount < TOKENS_PER_SEARCH:
            raise Refused(
                422,
                ProblemCode.INVALID,
                f"Reservationen räcker inte: {TOKENS_PER_SEARCH} tokens behövs för en webbsökning.",
            )
        if self.budget is not None:
            try:
                self.budget.allow()
            except Refused:
                self.tokens.give_back(app, asked.reservation)
                raise
        try:
            found = self.searcher.search(asked)
        except SearchFailed as error:
            self.tokens.give_back(app, asked.reservation)
            raise Refused(502, ProblemCode.UNAVAILABLE, f"{error} Inget drogs.") from None
        if self.budget is not None:
            self.budget.record(
                0,
                found.input_tokens,
                found.output_tokens,
                searches=max(found.searches, 1),
                extra_usd=found.searches * self.searcher.price_usd / 1000,
            )
        return self._keep(
            asked.reservation, _packed(found), self.searcher.model, TOKENS_PER_SEARCH, "search"
        )

    @staticmethod
    def _searched(kept: Kept, cost: int, reservation: TokenReservation) -> MeterSearchAnswer:
        try:
            found = json.loads(kept.text)
            return MeterSearchAnswer(
                values=[MeterSearchValue.model_validate(value) for value in found["values"]],
                results=[MeterSearchResult.model_validate(each) for each in found["results"]],
                searches=int(found["searches"]),
                cost=cost,
                model=kept.model,
                reservation=reservation,
            )
        except (ValueError, KeyError, TypeError) as error:
            raise Refused(
                409, ProblemCode.CONFLICT, "Det sparade svaret går inte att läsa."
            ) from error


def _other_use() -> Refused:
    return Refused(409, ProblemCode.CONFLICT, "Reservationen är redan använd för något annat.")


def _packed(found: Searched) -> str:
    """A search's answer as it is kept under its reservation."""
    return json.dumps(
        {
            "values": [value.model_dump(mode="json") for value in found.values],
            "results": [each.model_dump(mode="json") for each in found.results],
            "searches": found.searches,
        },
        ensure_ascii=False,
    )
