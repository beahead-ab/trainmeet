"""Egen AI på kontot (#79, TOKEN-03, TK4): a person's or a club's own AI service, used by the
meter instead of TrainMeets AI, drawing no tokens.

A pretend AI service answers at its own address; its key is checked on every call, and the probe
draws 777 here so that the pretend service can read it back.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts.tokens import MeterAnswer, OwnAiState
from id.app import create_app
from id.own_ai import seal, sealer, unseal
from id.settings import Settings
from id.tests.test_api import INTERNAL, ISSUER, PUBLIC, SECRET, Who, World, club_with, log_in
from id.tests.test_meter import PretendClaude
from id.tests.test_tokens import reserve

KEY = "egen-nyckel-for-provet"
PICTURE = base64.b64encode(b"\x89PNG en sida").decode()


@dataclass
class PretendService:
    """An AI service with the ordinary chat API: reads the probe's 777, and writes the page."""

    asked: list[dict[str, Any]] = field(default_factory=list)
    reads: str = "777"

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {KEY}":
            return httpx.Response(401, text=f"fel nyckel {request.headers.get('authorization')}")
        body = json.loads(request.content)
        self.asked.append(body)
        if body["model"] != "en-modell":
            return httpx.Response(404, json={"error": "okänd modell"})
        prompt = body["messages"][0]["content"][0]["text"]
        text = self.reads if prompt.startswith("Vilket tal") else "Lekby 07.12 avg 101"
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@dataclass
class OwnWorld:
    world: World
    service: PretendService
    claude: PretendClaude
    app: Any

    def as_(self, who: Who) -> TestClient:
        client = TestClient(self.app, base_url=PUBLIC)
        client.cookies = who.client.cookies
        return client

    def app_post(self, path: str, body: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.world.keycloak.app_token('hub')}"}
        answer: httpx.Response = TestClient(self.app, base_url=PUBLIC).post(
            f"/api/id/1/apps/{path}", json=body, headers=headers
        )
        return answer


@pytest.fixture
def own(world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[OwnWorld]:
    monkeypatch.setattr("id.own_ai.secrets.choice", lambda digits: "7")
    service, claude = PretendService(), PretendClaude()
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

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "ai.example.test":
            return service.handle(request)
        return world.keycloak.handle(request)

    http = httpx.Client(transport=httpx.MockTransport(handle))
    app = create_app(settings, http=http, mailer=world.mail, claude=claude)
    with TestClient(app):
        yield OwnWorld(world, service, claude, app)


CONNECT = {"format": "chat", "address": "https://ai.example.test/v1", "model": "en-modell"}


def logged_in(own: OwnWorld) -> tuple[Who, TestClient]:
    kim = log_in(own.world, "Kim Ek", "kim@example.com")
    kim.id = kim.client.get("/api/id/1/session").json()["account"]["id"]
    return kim, own.as_(kim)


def test_own_ai_is_connected_after_reading_the_probe_and_its_key_is_never_shown(
    own: OwnWorld,
) -> None:
    kim, me = logged_in(own)
    mine = f"person:{kim.id}"
    assert me.get("/api/id/1/tokens/own-ai", params={"owner": mine}).json() is None
    wrong = me.put(
        "/api/id/1/tokens/own-ai",
        params={"owner": mine},
        json={**CONNECT, "model": "annan", "key": KEY},
    )
    assert (wrong.status_code, wrong.json()["message"]) == (
        422,
        "AI-tjänsten känner inte adressen eller modellen.",
    )
    no_key = me.put("/api/id/1/tokens/own-ai", params={"owner": mine}, json=CONNECT)
    assert no_key.json()["message"] == "Skriv in tjänstens nyckel."
    connected = me.put(
        "/api/id/1/tokens/own-ai", params={"owner": mine}, json={**CONNECT, "key": KEY}
    )
    assert connected.status_code == 200, connected.text
    state = OwnAiState.model_validate(connected.json())
    assert (state.model, state.key_set, state.checked is not None) == ("en-modell", True, True)
    assert KEY not in connected.text
    # Changed without the key: the one kept is used, and the probe reads again.
    again = me.put("/api/id/1/tokens/own-ai", params={"owner": mine}, json=CONNECT)
    assert again.status_code == 200 and KEY not in again.text
    assert me.get("/api/id/1/tokens").json()[0]["own_ai"] == "en-modell"
    assert me.delete("/api/id/1/tokens/own-ai", params={"owner": mine}).status_code == 200
    assert me.get("/api/id/1/tokens").json()[0]["own_ai"] is None


def test_the_meter_reads_with_the_owners_own_ai_and_draws_nothing(own: OwnWorld) -> None:
    """TK4, TOKEN-13: with own AI no AI tokens are drawn; TrainMeets AI is never asked."""
    kim, me = logged_in(own)
    mine = f"person:{kim.id}"
    me.put("/api/id/1/tokens/own-ai", params={"owner": mine}, json={**CONNECT, "key": KEY})
    held = reserve(own.world, kim.id, mine, 12, "egen-1").json()["id"]
    body = {
        "reservation": held,
        "prompt": "Skriv av stationslistan.",
        "images": [{"media_type": "image/png", "data": PICTURE}],
    }
    read = own.app_post("meter", body)
    assert read.status_code == 200, read.text
    answer = MeterAnswer.model_validate(read.json())
    assert (answer.text, answer.cost, answer.model) == (
        "Lekby 07.12 avg 101",
        0,
        "en-modell (egen AI)",
    )
    assert answer.reservation.balance.available == 100
    assert own.claude.calls == []
    asked = len(own.service.asked)
    again = MeterAnswer.model_validate(own.app_post("meter", body).json())
    assert again.text == answer.text and len(own.service.asked) == asked, "asked once"
    # An app that knows the account has own AI reserves nothing, and reads all the same.
    nothing = reserve(own.world, kim.id, mine, 0, "egen-2")
    assert nothing.status_code == 201, nothing.text
    free = own.app_post("meter", {**body, "reservation": nothing.json()["id"]})
    assert free.status_code == 200 and free.json()["cost"] == 0


def test_with_hold_and_own_ai_the_cost_is_nothing_even_when_it_is_disconnected(
    own: OwnWorld,
) -> None:
    """CAT-145 with own AI: the held answer costs 0, and keeps that price when it is given
    again, also after the own AI was disconnected in between."""
    kim, me = logged_in(own)
    mine = f"person:{kim.id}"
    me.put("/api/id/1/tokens/own-ai", params={"owner": mine}, json={**CONNECT, "key": KEY})
    held = reserve(own.world, kim.id, mine, 0, "egen-hold").json()["id"]
    body = {
        "reservation": held,
        "prompt": "Läs av fordonet.",
        "images": [{"media_type": "image/png", "data": PICTURE}],
        "hold": True,
    }
    first = MeterAnswer.model_validate(own.app_post("meter", body).json())
    assert (first.cost, first.reservation.state) == (0, "held")
    me.delete("/api/id/1/tokens/own-ai", params={"owner": mine})
    again = MeterAnswer.model_validate(own.app_post("meter", body).json())
    assert (again.text, again.cost, again.model) == (first.text, 0, "en-modell (egen AI)")
    assert own.claude.calls == []


def test_only_the_clubs_admin_connects_the_clubs_own_ai(own: OwnWorld) -> None:
    kim, club, people = club_with(own.world, ("Sara Holm", "sara@example.com"))
    sara = own.as_(people["Sara Holm"])
    clubs = f"club:{club}"
    refused = sara.put(
        "/api/id/1/tokens/own-ai", params={"owner": clubs}, json={**CONNECT, "key": KEY}
    )
    assert (refused.status_code, refused.json()["message"]) == (
        403,
        "Bara klubbens administratör ändrar klubbens egen AI.",
    )
    assert sara.get("/api/id/1/tokens/own-ai", params={"owner": f"person:{kim.id}"}).status_code
    admin = own.as_(kim).put(
        "/api/id/1/tokens/own-ai", params={"owner": clubs}, json={**CONNECT, "key": KEY}
    )
    assert admin.status_code == 200, admin.text


def test_a_sealed_key_needs_ids_own_secret() -> None:
    sealed = seal(sealer("en-hemlighet"), KEY)
    assert KEY.encode() not in sealed
    assert unseal(sealer("en-hemlighet"), sealed) == KEY
    assert unseal(sealer("en-annan-hemlighet"), sealed) is None
