"""Mätaren (#79, TOKEN-28, TK17): TrainMeets AI, med reservationen från saldot.

An app sends the pages or pictures with its reservation and gets the transcription and what it
cost: 12 tokens a picture (TOKEN-14). The meter holds TrainMeet's key to Claude through Amazon
Bedrock in the EU (TK14, TOKEN-20); the apps never see it (TK7). Egen AI is the first choice and
TrainMeets AI an option (TK12): the app asks the person before the first time.

The same reservation twice gives the same answer and draws nothing twice: the answer is kept for
a day under the reservation, with its price. If Claude does not answer, the reservation goes back
and nothing is drawn. The AI is asked outside the database transaction, so a slow answer holds no
lock.

With hold (MeterRead.hold) the meter reads and keeps the answer but draws nothing: the reservation
stays held, MeterAnswer.cost says what the app is to draw, and the app draws it, or gives it all
back when the answer came too late to be used (Catalog's reading, CAT-145). A held reservation
with a kept answer gives that answer again without asking the AI, so the app can ask again after
a lost answer. A held reservation nobody draws goes back by itself (id/tokens.py), and a draw
can never take more than was reserved.

Settings, from the environment:

ID_METER_KEY_FILE          A file in ID's vault with the AWS access key for Bedrock: its id on
                           the first line and its secret on the second. Without the file the
                           meter is off.
ID_METER_REGION            Default eu-north-1, Stockholm, where the data is processed.
ID_METER_MODEL             Default anthropic.claude-sonnet-5-5, which the prices build on
                           (TOKEN-22).
ID_METER_MODEL_HARD        Default anthropic.claude-fable-5-2: the strongest model, for CAD's
                           hard follow-up questions only (MeterRead.hard, CAD18). The price for
                           the person is the same 12 tokens a picture; TrainMeet pays the rest.
ID_METER_HARD_FACTOR       Default 4: what a hard question's tokens cost against the standard
                           model's, at list prices (Fable 5.2 $8/$40 per million against Sonnet
                           5.5's $2/$10), so that the owner's budget (TK6, TK15) counts them right.
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
from uuid import UUID

import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from contracts.id import ProblemCode
from contracts.tokens import (
    HARD_APPS,
    TOKENS_PER_PAGE,
    MeterAnswer,
    MeterRead,
    TokenDraw,
    TokenOwner,
    TokenReservation,
    TokenReservationState,
)
from id.db import Database
from id.roles import Refused
from id.tokens import Tokens

LOGGER = logging.getLogger("id.meter")

API_VERSION: Final = "2026-10-21"
"""The Messages API's version, as Claude in Amazon Bedrock takes it."""
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
    model: str = "anthropic.claude-sonnet-5-5"
    hard_model: str = "anthropic.claude-fable-5-2"
    hard_factor: float = 4.0


def settings_from(env: Mapping[str, str] | None = None) -> MeterSettings | None:
    source = os.environ if env is None else env
    key_file = source.get("ID_METER_KEY_FILE", "").strip()
    if not key_file or not Path(key_file).is_file():
        return None
    return MeterSettings(
        key_file=Path(key_file),
        region=source.get("ID_METER_REGION", "").strip() or "eu-north-1",
        model=source.get("ID_METER_MODEL", "").strip() or "anthropic.claude-sonnet-5-5",
        hard_model=source.get("ID_METER_MODEL_HARD", "").strip() or "anthropic.claude-fable-5-2",
        hard_factor=_factor(source.get("ID_METER_HARD_FACTOR", "")),
    )


def _factor(given: str) -> float:
    try:
        factor = float(given.strip())
    except ValueError:
        return 4.0
    return factor if factor >= 1 else 4.0


class Claude(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def hard_model(self) -> str:
        """The strongest model, for CAD's hard follow-up questions (CAD18)."""
        ...

    @property
    def hard_factor(self) -> float:
        """What the strongest model's tokens cost against the standard model's."""
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

    def record(self, pages: int, input_tokens: int, output_tokens: int) -> None: ...


@dataclass
class BedrockClaude:
    """Claude in Amazon Bedrock: the Messages API at bedrock-mantle in the region, signed with
    AWS's own SigV4 (botocore). Called with httpx, as the rest of ID, rather than with
    Anthropic's SDK, whose HTTP library would change the test client for the whole project."""

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
    def address(self) -> str:
        return f"https://bedrock-mantle.{self.settings.region}.api.aws/anthropic/v1/messages"

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
        body = json.dumps(
            {
                "model": self.settings.hard_model if hard else self.settings.model,
                # The strongest model always thinks, and its thinking counts in max_tokens: a
                # short answer still needs room (CAD18).
                "max_tokens": max(max_tokens, 16_000) if hard else max_tokens,
                # A transcription needs no long thinking; the price counts a page (TOKEN-22). A
                # hard follow-up question is where the code was unsure: it reads carefully.
                "output_config": {"effort": "high" if hard else "low"},
                "messages": [{"role": "user", "content": content}],
            }
        ).encode()
        signed = AWSRequest(
            method="POST",
            url=self.address,
            data=body,
            headers={"content-type": "application/json", "anthropic-version": API_VERSION},
        )
        SigV4Auth(Credentials(key_id, secret), "bedrock-mantle", self.settings.region).add_auth(
            signed
        )
        try:
            answer = self.http.post(self.address, content=body, headers=dict(signed.headers))
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
    ) -> None:
        self.db = db
        self.tokens = tokens
        self.claude = claude
        self.own_ai = own_ai
        self.budget = budget

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
        factor = self.claude.hard_factor if asked.hard else 1.0
        if self.budget is not None:
            # The owner's budget is priced in the standard model's tokens: a hard question's
            # count as many as they cost (CAD18).
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

    def _keep(self, reservation: UUID, text: str, model: str, cost: int) -> Kept:
        """The first answer for the reservation is the one: two at once give the same."""
        now = datetime.now(UTC)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM meter_answer WHERE at < %s", (now - KEPT,))
            conn.execute(
                "INSERT INTO meter_answer (reservation_id, text, model, cost, at) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (reservation_id) DO NOTHING",
                (reservation, text, model, cost, now),
            )
            row = conn.execute(
                "SELECT text, model, cost FROM meter_answer WHERE reservation_id = %s",
                (reservation,),
            ).fetchone()
        assert row is not None
        return Kept(str(row["text"]), str(row["model"]), row["cost"])

    def _kept(self, reservation: UUID) -> Kept | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT text, model, cost FROM meter_answer WHERE reservation_id = %s AND at >= %s",
                (reservation, datetime.now(UTC) - KEPT),
            ).fetchone()
        return Kept(str(row["text"]), str(row["model"]), row["cost"]) if row else None
