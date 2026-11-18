"""TrainMeets AI i Hubben (#79, TOKEN-28, TK7, TK12, TK16).

In the cloud hub, someone logged in with TrainMeet ID may let TrainMeets AI write down a scanned
file: the hub says where the pages go and whose balance pays before anything is sent, reserves
each page in ID and lets the meter in ID read it. A pretend ID answers the balance and the meter
(hub/tests/test_id_roles.py); no AI is called.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi.testclient import TestClient

from contracts import planning
from contracts.tokens import (
    MeterAnswer,
    TokenBalance,
    TokenOwner,
    TokenOwnerKind,
    TokenReservation,
    TokenReservationState,
)
from hub.tests.test_id_roles import (
    API,
    AUTUMN,
    SETTINGS,
    PretendIdApi,
    make_meet,
)
from hub.tests.test_planering import varnamo_plan
from integrationer.ai import drawn
from integrationer.tests.test_scanned import transcript

CLUB = uuid.UUID(int=1)


@dataclass
class PretendIdMeter(PretendIdApi):
    """ID's balance and meter too: one balance per owner, and a transcription for each read."""

    available: dict[str, int] = field(default_factory=dict)
    reserved: list[dict[str, Any]] = field(default_factory=list)
    reads: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    failing: bool = False

    own_ai: str | None = None

    def balance(self, owner: TokenOwner) -> TokenBalance:
        key = f"{owner.kind}:{owner.id}"
        title = "Västby MJK" if owner.kind == "club" else "Provare Ett"
        left = self.available.setdefault(key, 300 if owner.kind == "club" else 100)
        return TokenBalance(
            owner=owner,
            title=title,
            free_left=left,
            free_monthly=300 if owner.kind == "club" else 100,
            bought=0,
            reserved=0,
            available=left,
            month="2026-11",
            own_ai=self.own_ai if owner.kind == "club" else None,
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host != "id-api" or not path.startswith(
            ("/api/id/1/apps/tokens", "/api/id/1/apps/meter")
        ):
            return super().handle(request)
        assert request.headers["authorization"] == "Bearer app-token"
        if request.method == "GET":
            kind, _, ident = request.url.params["owner"].partition(":")
            owner = TokenOwner.model_validate({"kind": kind, "id": ident})
            return httpx.Response(200, json=self.balance(owner).model_dump(mode="json"))
        asked: dict[str, Any] = json.loads(request.content)
        if path.endswith("/reservations"):
            self.reserved.append(asked)
            owner = TokenOwner.model_validate(asked["owner"])
            self.available[f"{owner.kind}:{owner.id}"] -= asked["amount"]
            return httpx.Response(201, json=self.reservation(owner, asked["amount"]))
        if path.endswith("/meter"):
            self.reads.append(asked)
            if self.failing:
                return httpx.Response(
                    502,
                    json={
                        "code": "unavailable",
                        "message": "TrainMeets AI svarar inte just nu. Inget drogs.",
                    },
                )
            owner = TokenOwner.model_validate(self.reserved[-1]["owner"])
            answer = MeterAnswer(
                text=self.text,
                cost=12,
                model="anthropic.claude-sonnet-5-5",
                reservation=TokenReservation.model_validate(self.reservation(owner, 12)),
            )
            return httpx.Response(200, json=answer.model_dump(mode="json"))
        return httpx.Response(
            200, json=self.reservation(TokenOwner(kind=TokenOwnerKind.CLUB, id=CLUB), 12)
        )

    def reservation(self, owner: TokenOwner, amount: int) -> dict[str, Any]:
        now = datetime(2026, 11, 18, 3, 0, tzinfo=UTC)
        return TokenReservation(
            id=uuid.uuid4(),
            owner=owner,
            amount=amount,
            state=TokenReservationState.HELD,
            what="En sida",
            at=now,
            expires=now + timedelta(minutes=30),
            balance=self.balance(owner),
        ).model_dump(mode="json")


def hub_with(pretend: PretendIdMeter, tmp_path: Any) -> tuple[TestClient, TestClient]:
    from hub.app import create_app
    from hub.build_info import BuildInfo
    from hub.tests.test_id_login import PIN, PUBLIC, back, to_id

    made = create_app(
        BuildInfo(version="0.1.0"),
        preview_db=tmp_path / "p.db",
        id_settings=SETTINGS,
        id_http=httpx.Client(transport=httpx.MockTransport(pretend.handle)),
    )
    owner = TestClient(made, base_url=PUBLIC, follow_redirects=False)
    assert owner.post("/api/hub/setup", json={"name": "Molnet", "pin": PIN}).status_code == 201
    person = TestClient(made, base_url=PUBLIC, follow_redirects=False)
    assert back(person, to_id(person, pretend)).status_code == 303
    return owner, person


PHOTO = drawn("1234")


def send(client: TestClient, meet: str, ai: str | None = None) -> httpx.Response:
    params = {"name": "Lekby.png"}
    if ai:
        params |= {"transcribe": "lists", "ai": ai}
    answer: httpx.Response = client.post(
        f"{API}/meets/{meet}/sources",
        params=params,
        content=PHOTO,
        headers={"Content-Type": "application/octet-stream"},
    )
    return answer


def test_the_club_pays_for_trainmeets_ai_after_being_told(tmp_path: Any) -> None:
    """TK12, TK16, TOKEN-28: the price, where the pages go and who pays, before anything is
    sent; the meet in ID belongs to the club, so the club's balance pays."""
    pretend = PretendIdMeter(text=transcript(varnamo_plan(), "Lek", "Lek Lekby"))
    pretend.roles = {str(AUTUMN): ["organizer"]}
    owner, person = hub_with(pretend, tmp_path)
    meet = planning.Draft.model_validate(make_meet(person).json()).meet.id

    asked = send(person, meet)
    assert asked.status_code == 202, asked.text
    offer = planning.AiPages.model_validate(asked.json()).trainmeet_ai
    assert offer == planning.TrainMeetAi(payer="Västby MJK", available=300, price=12)
    assert pretend.reserved == [] and pretend.reads == [], "nothing before the planner says so"
    # The hub's PIN is not a person in ID: no TrainMeets AI, only its own.
    assert planning.AiPages.model_validate(send(owner, meet).json()).trainmeet_ai is None

    written = send(person, meet, "trainmeet")
    assert written.status_code == 201, written.text
    seen = planning.ImportPreview.model_validate(written.json())
    assert seen.source.kind == planning.SourceKind.STATION_LISTS
    assert [(r["owner"], r["amount"]) for r in pretend.reserved] == [
        ({"kind": "club", "id": str(CLUB)}, 12)
    ]
    assert pretend.reads[0]["images"][0]["media_type"] == "image/png"
    # Written down once, the page is kept: the same file again costs nothing.
    again = planning.AiPages.model_validate(send(person, meet).json())
    assert (again.saved, again.trainmeet_ai and again.trainmeet_ai.price) == (1, 0)
    assert send(person, meet, "trainmeet").status_code == 201
    assert len(pretend.reads) == 1


def test_without_tokens_or_an_answer_the_planner_is_told(tmp_path: Any) -> None:
    """TOKEN-04: when the balance does not cover the pages, buy more or use one's own AI; when
    the AI does not answer, nothing is drawn."""
    pretend = PretendIdMeter(text="")
    pretend.roles = {str(AUTUMN): ["organizer"]}
    _, person = hub_with(pretend, tmp_path)
    meet = planning.Draft.model_validate(make_meet(person).json()).meet.id
    pretend.available[f"club:{CLUB}"] = 5
    short = send(person, meet, "trainmeet")
    assert short.status_code == 402
    assert short.json()["detail"] == (
        "Saldot räcker inte: 5 tokens kvar, 12 behövs. Köp fler eller använd egen AI."
    )
    assert pretend.reserved == []

    pretend.available[f"club:{CLUB}"] = 300
    pretend.failing = True
    failed = send(person, meet, "trainmeet")
    assert failed.status_code == 502
    assert failed.json()["detail"] == "TrainMeets AI svarar inte just nu. Inget drogs."


def test_the_clubs_own_ai_reads_for_nothing(tmp_path: Any) -> None:
    """TK4, TOKEN-03: the club has its own AI on its account in ID: the pages cost no tokens."""
    pretend = PretendIdMeter(
        text=transcript(varnamo_plan(), "Lek", "Lek Lekby"), own_ai="en-modell"
    )
    pretend.roles = {str(AUTUMN): ["organizer"]}
    _, person = hub_with(pretend, tmp_path)
    meet = planning.Draft.model_validate(make_meet(person).json()).meet.id
    offer = planning.AiPages.model_validate(send(person, meet).json()).trainmeet_ai
    assert offer is not None and (offer.price, offer.own_ai) == (0, "en-modell")
    pretend.available[f"club:{CLUB}"] = 0
    assert send(person, meet, "trainmeet").status_code == 201, "no tokens needed"
