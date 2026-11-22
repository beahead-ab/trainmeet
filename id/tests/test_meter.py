"""Mätaren (#79, TOKEN-28): TrainMeets AI med reservationen från saldot.

A pretend Claude answers the meter in ID, and Claude in Amazon Bedrock is answered by a mock
transport that checks the request: the address in the EU, AWS's signature, the EU profile and the
picture. No real AI is called.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from contracts.tokens import MeterAnswer
from id.app import create_app
from id.meter import BedrockClaude, ClaudeRead, MeterFailed, MeterSettings, settings_from
from id.settings import Settings
from id.tests.test_api import INTERNAL, ISSUER, PUBLIC, SECRET, World, log_in
from id.tests.test_tokens import app_post, reserve, storage

PICTURE = base64.b64encode(b"\x89PNG en sida").decode()


@dataclass
class PretendClaude:
    text: str = "Värnamo 07.12 avg 101"
    failing: bool = False
    calls: list[tuple[str, int]] = field(default_factory=list)
    hard: list[bool] = field(default_factory=list)
    profile_factor: float = 1.0

    @property
    def model(self) -> str:
        return "eu.anthropic.claude-sonnet-5-5"

    @property
    def hard_model(self) -> str:
        return "eu.anthropic.claude-opus-5-5"

    @property
    def hard_factor(self) -> float:
        return 2.0

    def read(
        self,
        prompt: str,
        images: Sequence[tuple[str, str]],
        max_tokens: int,
        *,
        hard: bool = False,
    ) -> ClaudeRead:
        self.calls.append((prompt, len(images)))
        self.hard.append(hard)
        if self.failing:
            raise MeterFailed("TrainMeets AI svarar inte just nu.")
        return ClaudeRead(self.text, 7000 * len(images), 3000 * len(images))


@dataclass
class Metered:
    world: World
    claude: PretendClaude
    app: TestClient

    def read(
        self,
        reservation: str,
        images: int = 1,
        *,
        hold: bool = False,
        app: str = "hub",
        hard: bool = False,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.world.keycloak.app_token(app)}"}
        body: dict[str, Any] = {
            "reservation": reservation,
            "prompt": "Skriv av stationslistan.",
            "images": [{"media_type": "image/png", "data": PICTURE}] * images,
        }
        if hold:
            body["hold"] = True
        if hard:
            body["hard"] = True
        answer: httpx.Response = self.app.post("/api/id/1/apps/meter", json=body, headers=headers)
        return answer

    def balance(self, person: str) -> int:
        headers = {"Authorization": f"Bearer {self.world.keycloak.app_token('hub')}"}
        found = self.app.get(
            "/api/id/1/apps/tokens",
            params={"person": person, "owner": f"person:{person}"},
            headers=headers,
        ).json()
        available: int = found["available"]
        return available


@pytest.fixture
def metered(world: World, tmp_path: Path) -> Iterator[Metered]:
    claude = PretendClaude()
    settings = Settings(
        database_url=world.url,
        issuer=ISSUER,
        internal=INTERNAL,
        client="id",
        secret=SECRET,
        public_url=PUBLIC,
        apps=("catalog", "hub", "cad"),
        web_dir=tmp_path,
    )
    http = httpx.Client(transport=httpx.MockTransport(world.keycloak.handle))
    app = create_app(settings, http=http, mailer=world.mail, claude=claude)
    with TestClient(app, base_url=PUBLIC) as client:
        yield Metered(world, claude, client)


def person(world: World) -> str:
    kim = log_in(world, "Kim Ek", "kim@example.com")
    found: str = kim.client.get("/api/id/1/session").json()["account"]["id"]
    return found


def test_the_meter_reads_the_picture_and_draws_what_it_cost(metered: Metered) -> None:
    """TOKEN-28: the app sends the picture with its reservation and gets the transcription and
    the cost, 12 tokens a picture. The same reservation again gives the same answer."""
    kim = person(metered.world)
    held = reserve(metered.world, kim, f"person:{kim}", 24, "sida-1-2").json()["id"]
    read = metered.read(held, images=2)
    assert read.status_code == 200, read.text
    answer = MeterAnswer.model_validate(read.json())
    assert (answer.text, answer.cost, answer.model) == (
        "Värnamo 07.12 avg 101",
        24,
        "eu.anthropic.claude-sonnet-5-5",
    )
    assert (answer.reservation.state, answer.reservation.balance.available) == ("drawn", 76)
    again = MeterAnswer.model_validate(metered.read(held, images=2).json())
    assert (again.text, again.reservation.balance.available) == (answer.text, 76)
    assert len(metered.claude.calls) == 1, "asked once"


def test_cads_hard_question_is_read_by_the_strongest_model_at_the_same_price(
    metered: Metered,
) -> None:
    """CAD19: CAD's hard follow-up question, where the code was unsure, is read by Claude Opus
    5.5 with the EU profile; the person pays the same 12 tokens a picture."""
    kim = person(metered.world)
    headers = {"Authorization": f"Bearer {metered.world.keycloak.app_token('cad')}"}
    body = {
        "person": kim,
        "owner": {"kind": "person", "id": kim},
        "amount": 12,
        "key": "foljdfraga",
        "what": "1 bild i CAD",
    }
    made = metered.app.post("/api/id/1/apps/tokens/reservations", json=body, headers=headers)
    assert made.status_code in (200, 201), made.text
    held = made.json()["id"]
    read = metered.read(held, app="cad", hard=True)
    assert read.status_code == 200, read.text
    answer = MeterAnswer.model_validate(read.json())
    assert (answer.cost, answer.model) == (12, "eu.anthropic.claude-opus-5-5")
    assert metered.claude.hard == [True]


def test_only_cad_may_ask_the_strongest_model(metered: Metered) -> None:
    """CAD18: only CAD's hard follow-up questions; the hub's import reads with the standard
    model, and a hard question from it is refused before anything is read or drawn."""
    kim = person(metered.world)
    held = reserve(metered.world, kim, f"person:{kim}", 12, "sida-1").json()["id"]
    refused = metered.read(held, app="hub", hard=True)
    assert refused.status_code == 422, refused.text
    assert "CAD:s svåra följdfrågor" in refused.json()["message"]
    assert metered.claude.calls == []
    read = metered.read(held, app="hub")
    assert MeterAnswer.model_validate(read.json()).model == "eu.anthropic.claude-sonnet-5-5"
    assert metered.claude.hard == [False]


def test_when_the_ai_does_not_answer_nothing_is_drawn(metered: Metered) -> None:
    kim = person(metered.world)
    metered.claude.failing = True
    held = reserve(metered.world, kim, f"person:{kim}", 12, "sida-3").json()["id"]
    failed = metered.read(held)
    assert failed.status_code == 502
    assert failed.json()["message"] == "TrainMeets AI svarar inte just nu. Inget drogs."
    headers = {"Authorization": f"Bearer {metered.world.keycloak.app_token('hub')}"}
    balance = metered.app.get(
        "/api/id/1/apps/tokens", params={"person": kim, "owner": f"person:{kim}"}, headers=headers
    ).json()
    assert balance["available"] == 100
    assert metered.read(held).status_code == 409, "the reservation went back"


def test_a_reservation_must_cover_every_picture(metered: Metered) -> None:
    kim = person(metered.world)
    held = reserve(metered.world, kim, f"person:{kim}", 12, "liten").json()["id"]
    short = metered.read(held, images=2)
    assert short.status_code == 422
    assert short.json()["message"] == "Reservationen räcker inte: 24 tokens behövs för 2 bilder."
    assert metered.claude.calls == []


def test_without_a_key_the_meter_is_off(world: World) -> None:
    kim = person(world)
    held = reserve(world, kim, f"person:{kim}", 12, "av").json()["id"]
    headers = {"Authorization": f"Bearer {world.keycloak.app_token('hub')}"}
    body = {
        "reservation": held,
        "prompt": "Skriv av.",
        "images": [{"media_type": "image/png", "data": PICTURE}],
    }
    off = world.browser().post("/api/id/1/apps/meter", json=body, headers=headers)
    assert (off.status_code, off.json()["code"]) == (503, "unavailable")


# --- Claude in Amazon Bedrock ------------------------------------------------------------------


def bedrock(tmp_path: Path, handle: Any) -> BedrockClaude:
    key = tmp_path / "nyckel"
    key.write_text("AKIAPROVET\nhemlig-nyckel-for-provet\n")
    settings = MeterSettings(key_file=key)
    return BedrockClaude(settings, http=httpx.Client(transport=httpx.MockTransport(handle)))


def test_bedrock_is_asked_in_the_eu_signed_and_with_the_picture(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "Rad 1"}, {"type": "text", "text": "\nRad 2"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 6900, "output_tokens": 2100},
            },
        )

    claude = bedrock(tmp_path, handle)
    read = claude.read("Skriv av.", [("image/png", PICTURE)], 4096)
    assert (read.text, read.input_tokens, read.output_tokens) == ("Rad 1\nRad 2", 6900, 2100)
    request = seen[0]
    # TK14: Claude Sonnet 5.5 with the EU profile, called from Stockholm; the profile sends the
    # call on to one of the EU's regions and never outside them.
    assert str(request.url) == (
        "https://bedrock-runtime.eu-north-1.amazonaws.com"
        "/model/eu.anthropic.claude-sonnet-5-5/invoke"
    )
    signature = request.headers["authorization"]
    assert signature.startswith("AWS4-HMAC-SHA256 Credential=AKIAPROVET/")
    assert "/eu-north-1/bedrock/aws4_request" in signature
    assert "hemlig-nyckel" not in json.dumps(dict(request.headers))
    body = json.loads(request.content)
    assert body["anthropic_version"] == "bedrock-2023-05-31"
    assert "model" not in body, "InvokeModel takes the model in the address"
    assert body["output_config"] == {"effort": "low"}
    assert "temperature" not in body, "Claude Sonnet 5.5 takes no sampling settings"
    assert body["messages"][0]["content"] == [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PICTURE}},
        {"type": "text", "text": "Skriv av."},
    ]


def test_a_hard_question_goes_to_the_strongest_model_with_room_to_think(tmp_path: Path) -> None:
    """CAD19: the strongest model in the EU, Claude Opus 5.5 with the EU profile, always thinks,
    and its thinking counts in max_tokens, so a short answer still gets room; it reads carefully
    (effort high)."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "blå"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1500, "output_tokens": 400},
            },
        )

    claude = bedrock(tmp_path, handle)
    assert claude.hard_model == "eu.anthropic.claude-opus-5-5"
    read = claude.read("Vilken kontur?", [("image/png", PICTURE)], 256, hard=True)
    assert read.text == "blå"
    assert str(seen[0].url) == (
        "https://bedrock-runtime.eu-north-1.amazonaws.com/model/eu.anthropic.claude-opus-5-5/invoke"
    )
    body = json.loads(seen[0].content)
    assert "model" not in body
    assert body["output_config"] == {"effort": "high"}
    assert body["max_tokens"] == 16_000
    assert "thinking" not in body and "temperature" not in body


def test_the_hard_model_and_its_price_factor_are_settings(tmp_path: Path) -> None:
    key = tmp_path / "nyckel"
    key.write_text("AKIAPROVET\nhemlig\n")
    found = settings_from({"ID_METER_KEY_FILE": str(key)})
    assert found is not None
    # CAD19: Claude Opus 5.5 with the EU profile, at twice the standard model's price, and the
    # EU profile at 10 % above the list prices (TK14).
    assert (found.hard_model, found.hard_factor) == ("eu.anthropic.claude-opus-5-5", 2.0)
    assert found.profile_factor == 1.1
    other = settings_from(
        {
            "ID_METER_KEY_FILE": str(key),
            "ID_METER_MODEL_HARD": "global.anthropic.claude-opus-5-5",
            "ID_METER_HARD_FACTOR": "1.5",
            "ID_METER_PROFILE_FACTOR": "1",
        }
    )
    assert other is not None
    assert (other.hard_model, other.hard_factor) == ("global.anthropic.claude-opus-5-5", 1.5)
    assert other.profile_factor == 1.0
    nonsense = settings_from(
        {
            "ID_METER_KEY_FILE": str(key),
            "ID_METER_HARD_FACTOR": "ingen",
            "ID_METER_PROFILE_FACTOR": "0",
        }
    )
    assert nonsense is not None and (nonsense.hard_factor, nonsense.profile_factor) == (2.0, 1.1)


def test_the_meter_is_on_only_with_its_key_in_the_vault(tmp_path: Path) -> None:
    key = tmp_path / "trainmeet_bedrock-key"
    assert settings_from({"ID_METER_KEY_FILE": str(key)}) is None
    assert settings_from({}) is None
    key.write_text("AKIAPROVET\nhemlig\n")
    found = settings_from({"ID_METER_KEY_FILE": str(key)})
    assert found is not None
    assert (found.region, found.model) == ("eu-north-1", "eu.anthropic.claude-sonnet-5-5")


@pytest.mark.parametrize(
    ("answer", "said"),
    [
        (httpx.Response(200, json={"content": [], "stop_reason": "refusal"}), "ville inte läsa"),
        (httpx.Response(200, json={"content": [], "stop_reason": "max_tokens"}), "för lång"),
        (httpx.Response(429, json={}), "för många frågor"),
        (httpx.Response(403, text="nyckeln hemlig-nyckel-for-provet nekad"), "fel 403"),
        (httpx.Response(200, text="inte json"), "inte som väntat"),
    ],
)
def test_bedrock_says_what_went_wrong_without_the_key(
    tmp_path: Path, answer: httpx.Response, said: str
) -> None:
    claude = bedrock(tmp_path, lambda request: answer)
    with pytest.raises(MeterFailed) as failed:
        claude.read("Skriv av.", [("image/png", PICTURE)], 4096)
    assert said in str(failed.value)
    assert "hemlig" not in str(failed.value)


def test_the_meter_never_reads_with_a_reservation_for_storage(metered: Metered) -> None:
    """CAT-132: a reservation without a person pays for an app's storage, never for AI."""
    kim = person(metered.world)
    held = storage(metered.world, f"person:{kim}", 20, "catalog-lagring-kim-2026-11-1").json()
    headers = {"Authorization": f"Bearer {metered.world.keycloak.app_token('catalog')}"}
    body = {
        "reservation": held["id"],
        "prompt": "Skriv av stationslistan.",
        "images": [{"media_type": "image/png", "data": PICTURE}],
    }
    refused = metered.app.post("/api/id/1/apps/meter", json=body, headers=headers)
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "invalid"
    assert metered.claude.calls == []
    # Still held for the storage, which Catalog draws itself.
    drawn = app_post(metered.world, f"reservations/{held['id']}/draw", {}, app="catalog")
    assert drawn.json()["balance"]["available"] == 80


# --- Hold: the app draws after it has looked at the answer (CAT-145) ---------------------------


def test_with_hold_the_meter_reads_but_the_app_draws(metered: Metered) -> None:
    """The meter keeps the answer and says what it costs, and the reservation stays held. Asked
    again, the held reservation gives the same answer without asking Claude; the app then draws
    the cost, and the same reservation still gives the same answer."""
    kim = person(metered.world)
    held = reserve(metered.world, kim, f"person:{kim}", 24, "avlasning-1", app="catalog")
    reservation = held.json()["id"]
    read = metered.read(reservation, images=2, hold=True, app="catalog")
    assert read.status_code == 200, read.text
    answer = MeterAnswer.model_validate(read.json())
    assert (answer.text, answer.cost) == ("Värnamo 07.12 avg 101", 24)
    assert (answer.reservation.state, answer.reservation.drawn) == ("held", 0)
    assert answer.reservation.balance.available == 76, "still reserved"

    again = MeterAnswer.model_validate(
        metered.read(reservation, images=2, hold=True, app="catalog").json()
    )
    assert (again.text, again.cost, again.reservation.state) == (answer.text, 24, "held")
    assert len(metered.claude.calls) == 1, "asked once"

    drawn = app_post(metered.world, f"reservations/{reservation}/draw", {"amount": 24}, "catalog")
    assert (drawn.status_code, drawn.json()["state"], drawn.json()["drawn"]) == (200, "drawn", 24)
    after = MeterAnswer.model_validate(metered.read(reservation, images=2, app="catalog").json())
    assert (after.text, after.cost, after.reservation.state) == (answer.text, 24, "drawn")
    assert metered.balance(kim) == 76
    assert len(metered.claude.calls) == 1


def test_a_held_answer_that_is_not_used_costs_nothing(metered: Metered) -> None:
    """CAT-145: the app gives back the reservation, and nothing is drawn; the answer is not
    given again for a reservation that went back."""
    kim = person(metered.world)
    reservation = reserve(metered.world, kim, f"person:{kim}", 12, "avlasning-2").json()["id"]
    assert metered.read(reservation, hold=True).status_code == 200
    back = app_post(metered.world, f"reservations/{reservation}/return", {})
    assert (back.status_code, back.json()["state"]) == (200, "returned")
    assert metered.balance(kim) == 100
    assert metered.read(reservation, hold=True).status_code == 409


def test_a_held_reservation_never_draws_more_than_was_reserved(metered: Metered) -> None:
    kim = person(metered.world)
    reservation = reserve(metered.world, kim, f"person:{kim}", 12, "avlasning-3").json()["id"]
    assert MeterAnswer.model_validate(metered.read(reservation, hold=True).json()).cost == 12
    more = app_post(metered.world, f"reservations/{reservation}/draw", {"amount": 13})
    assert (more.status_code, more.json()["code"]) == (422, "invalid")
    assert metered.balance(kim) == 88, "still held, nothing drawn"


def test_a_held_answer_is_drawn_by_a_read_without_hold(metered: Metered) -> None:
    """An app that asks again without hold gets the kept answer, and its cost is drawn."""
    kim = person(metered.world)
    reservation = reserve(metered.world, kim, f"person:{kim}", 12, "avlasning-4").json()["id"]
    assert metered.read(reservation, hold=True).status_code == 200
    drawn = MeterAnswer.model_validate(metered.read(reservation).json())
    assert (drawn.cost, drawn.reservation.state, drawn.reservation.drawn) == (12, "drawn", 12)
    assert len(metered.claude.calls) == 1


def test_a_held_reservation_goes_back_by_itself(metered: Metered) -> None:
    """A held reservation nobody draws goes back after half an hour, as any other."""
    kim = person(metered.world)
    reservation = reserve(metered.world, kim, f"person:{kim}", 12, "avlasning-5").json()["id"]
    assert metered.read(reservation, hold=True).status_code == 200
    with psycopg.connect(metered.world.url, autocommit=True) as conn:
        conn.execute(
            "UPDATE token_reservation SET expires = now() - interval '1 minute' WHERE id = %s",
            (reservation,),
        )
    assert metered.balance(kim) == 100
    late = app_post(metered.world, f"reservations/{reservation}/draw", {"amount": 12})
    assert late.status_code == 409


def test_when_the_ai_fails_with_hold_the_reservation_goes_back(metered: Metered) -> None:
    kim = person(metered.world)
    metered.claude.failing = True
    reservation = reserve(metered.world, kim, f"person:{kim}", 12, "avlasning-6").json()["id"]
    failed = metered.read(reservation, hold=True)
    assert failed.status_code == 502
    assert metered.balance(kim) == 100
    assert metered.read(reservation, hold=True).status_code == 409
