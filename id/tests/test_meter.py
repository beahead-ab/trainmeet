"""Mätaren (#79, TOKEN-28): TrainMeets AI med reservationen från saldot.

A pretend Claude answers the meter in ID, and Claude in Amazon Bedrock is answered by a mock
transport that checks the request: the address in the EU, AWS's signature, the model and the
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
import pytest
from fastapi.testclient import TestClient

from contracts.tokens import MeterAnswer
from id.app import create_app
from id.meter import BedrockClaude, MeterFailed, MeterSettings, settings_from
from id.settings import Settings
from id.tests.test_api import INTERNAL, ISSUER, PUBLIC, SECRET, World, log_in
from id.tests.test_tokens import reserve

PICTURE = base64.b64encode(b"\x89PNG en sida").decode()


@dataclass
class PretendClaude:
    text: str = "Värnamo 07.12 avg 101"
    failing: bool = False
    calls: list[tuple[str, int]] = field(default_factory=list)

    @property
    def model(self) -> str:
        return "anthropic.claude-sonnet-5-5"

    def read(self, prompt: str, images: Sequence[tuple[str, str]], max_tokens: int) -> str:
        self.calls.append((prompt, len(images)))
        if self.failing:
            raise MeterFailed("TrainMeets AI svarar inte just nu.")
        return self.text


@dataclass
class Metered:
    world: World
    claude: PretendClaude
    app: TestClient

    def read(self, reservation: str, images: int = 1) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.world.keycloak.app_token('hub')}"}
        body = {
            "reservation": reservation,
            "prompt": "Skriv av stationslistan.",
            "images": [{"media_type": "image/png", "data": PICTURE}] * images,
        }
        answer: httpx.Response = self.app.post("/api/id/1/apps/meter", json=body, headers=headers)
        return answer


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
        apps=("catalog", "hub"),
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
        "anthropic.claude-sonnet-5-5",
    )
    assert (answer.reservation.state, answer.reservation.balance.available) == ("drawn", 76)
    again = MeterAnswer.model_validate(metered.read(held, images=2).json())
    assert (again.text, again.reservation.balance.available) == (answer.text, 76)
    assert len(metered.claude.calls) == 1, "asked once"


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
            },
        )

    claude = bedrock(tmp_path, handle)
    assert claude.read("Skriv av.", [("image/png", PICTURE)], 4096) == "Rad 1\nRad 2"
    request = seen[0]
    assert str(request.url) == "https://bedrock-mantle.eu-north-1.api.aws/anthropic/v1/messages"
    assert request.headers["anthropic-version"] == "2026-10-21"
    signature = request.headers["authorization"]
    assert signature.startswith("AWS4-HMAC-SHA256 Credential=AKIAPROVET/")
    assert "/eu-north-1/bedrock-mantle/aws4_request" in signature
    assert "hemlig-nyckel" not in json.dumps(dict(request.headers))
    body = json.loads(request.content)
    assert body["model"] == "anthropic.claude-sonnet-5-5"
    assert body["output_config"] == {"effort": "low"}
    assert "temperature" not in body, "Claude Sonnet 5.5 takes no sampling settings"
    assert body["messages"][0]["content"] == [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PICTURE}},
        {"type": "text", "text": "Skriv av."},
    ]


def test_the_meter_is_on_only_with_its_key_in_the_vault(tmp_path: Path) -> None:
    key = tmp_path / "trainmeet_bedrock-key"
    assert settings_from({"ID_METER_KEY_FILE": str(key)}) is None
    assert settings_from({}) is None
    key.write_text("AKIAPROVET\nhemlig\n")
    found = settings_from({"ID_METER_KEY_FILE": str(key)})
    assert found is not None
    assert (found.region, found.model) == ("eu-north-1", "anthropic.claude-sonnet-5-5")


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
