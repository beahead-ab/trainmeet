"""The reading of a photo with AI (#52, CAT-19, CAT-20, CAT-26, CAT-46, CAT-135–CAT-146).

A pretend ID keeps the balances and answers the reservations and the meter as ID does, with hold
(contracts/tokens.py): the meter keeps the answer and says what it costs, and Catalog draws it
or gives it back. The meter's AI is a fake answer that the tests write; no test asks a real AI
(CAT-154). Ported from TrainCatalog's catalog/test_draft_ai.py and catalog/test_ai.py.
"""

from __future__ import annotations

import base64
import io
import json
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from PIL import ExifTags, Image

from catalog.app import create_app
from catalog.reading import FIELDS, PROMPT, Unreadable, question_for, understand
from catalog.settings import Settings
from catalog.tests.test_pictures import PretendIdWithClubs, World, photo, world_with
from catalog.tests.test_sharing import CLUB, HBIS, A, B
from contracts.catalog import CatalogVersion, Reading, ReadingConsent
from contracts.tokens import (
    MeterAnswer,
    TokenBalance,
    TokenOwner,
    TokenOwnerKind,
    TokenReservation,
    TokenReservationState,
)

API = "/api/catalog/1"
NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
MINE = f"person:{A}"


def said(
    value: str | None, basis: str = "visible_text", confidence: str = "high"
) -> dict[str, Any]:
    return {
        "value": value,
        "confidence": confidence,
        "basis": basis if value is not None else "unknown",
        "evidence": "Står på sidan." if value is not None else "",
    }


def answer(**fields: dict[str, Any]) -> str:
    """The AI's answer as the prompt asks for it, with the fields given and the rest null."""
    every: dict[str, Any] = {name: said(None) for name in FIELDS}
    every.update(fields)
    return json.dumps(
        {
            "summary": "En godsvagn från sidan.",
            "fields": every,
            "warnings": ["Kontrollera numret."],
            "suggested_next_photo": "Ta en närbild på numret.",
        },
        ensure_ascii=False,
    )


HBIS_READ = answer(
    kind=said("freight_wagon", "visual_inference", "medium"),
    litt=said("Hbis"),
    number=said("21 74 245 2 253-0"),
    operator=said("SJ"),
)


@dataclass
class PretendMeter(PretendIdWithClubs):
    """ID's balances, reservations and meter, for a reading. The AI's answer is text = ..."""

    accounts: dict[str, int] = field(default_factory=lambda: {MINE: 100, f"person:{B}": 100})
    own_ai: dict[str, str] = field(default_factory=dict)
    text: str = HBIS_READ
    meter_fails: int | None = None
    """ID's status when the meter does not read, as when the AI does not answer (502)."""
    during_read: Callable[[], None] | None = None
    draw_fails: str | None = None
    """"down": ID does not draw; "lost": it draws, but its answer is lost on the way."""
    reservations: dict[str, dict[str, Any]] = field(default_factory=dict)
    reserved: list[dict[str, Any]] = field(default_factory=list)
    reads: list[dict[str, Any]] = field(default_factory=list)
    draws: list[tuple[str, int]] = field(default_factory=list)
    returned: list[str] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if not path.endswith(("/apps/tokens", "/apps/meter")) and "/reservations" not in path:
            return super().handle(request)
        assert request.headers["authorization"] == f"Bearer t{self.tokens}"
        if path.endswith("/apps/tokens"):
            return self._balance(request.url.params["person"], request.url.params["owner"])
        body = json.loads(request.content) if request.content else {}
        if path.endswith("/apps/meter"):
            return self._read(body)
        if path.endswith("/reservations"):
            return self._reserve(body)
        found = self.reservations[path.split("/")[-2]]
        if path.endswith("/draw"):
            return self._draw(found, body["amount"])
        assert path.endswith("/return")
        if found["state"] == "drawn":
            return httpx.Response(409, json={"code": "conflict", "message": "Dragen."})
        if found["state"] == "held":
            found["state"] = "returned"
            self.accounts[found["owner"]] += found["amount"]
            self.returned.append(found["id"])
        return self._answer(found)

    def _balance(self, person: str, owner: str) -> httpx.Response:
        if owner not in self.accounts or person not in (A, B):
            return httpx.Response(404, json={"code": "not_found", "message": "Finns inte."})
        kind, _, ident = owner.partition(":")
        left = self.accounts[owner]
        balance = TokenBalance(
            owner=TokenOwner(kind=TokenOwnerKind(kind), id=UUID(ident)),
            title="Västby MJK" if kind == "club" else "Provkonto",
            free_left=0,
            free_monthly=100,
            bought=left,
            reserved=0,
            available=left,
            month="2026-11",
            own_ai=self.own_ai.get(owner),
        )
        return httpx.Response(200, json=balance.model_dump(mode="json"))

    def _reserve(self, body: dict[str, Any]) -> httpx.Response:
        assert body["person"] is not None, "a reading is a person's work, never the storage's"
        self.reserved.append(body)
        owner = f"{body['owner']['kind']}:{body['owner']['id']}"
        if self.accounts[owner] < body["amount"]:
            return httpx.Response(402, json={"code": "no_tokens", "message": "Saldot räcker inte."})
        self.accounts[owner] -= body["amount"]
        made = {"id": str(uuid.uuid4()), "owner": owner, "amount": body["amount"], "drawn": 0}
        made.update(state="held", what=body["what"], key=body["key"], answer=None)
        self.reservations[made["id"]] = made
        return self._answer(made, 201)

    def _read(self, body: dict[str, Any]) -> httpx.Response:
        assert body["hold"] is True
        self.reads.append(body)
        found = self.reservations[body["reservation"]]
        if self.during_read is not None:
            self.during_read()
        if self.meter_fails is not None:
            found["state"] = "returned"
            self.accounts[found["owner"]] += found["amount"]
            # ID's own words, which Catalog never passes on.
            return httpx.Response(
                self.meter_fails, json={"code": "unavailable", "message": "hemligt fel från AI"}
            )
        own = self.own_ai.get(found["owner"])
        cost = 0 if own else 12 * len(body["images"])
        meter = MeterAnswer(
            text=self.text,
            cost=cost,
            model=f"{own} (egen AI)" if own else "anthropic.claude-sonnet-5-5",
            reservation=self._reservation(found),
        )
        return httpx.Response(200, json=meter.model_dump(mode="json"))

    def _draw(self, found: dict[str, Any], amount: int) -> httpx.Response:
        assert found["state"] == "held" and amount <= found["amount"]
        if self.draw_fails == "down":
            return httpx.Response(503, json={"code": "unavailable", "message": "Nere."})
        found.update(state="drawn", drawn=amount)
        self.accounts[found["owner"]] += found["amount"] - amount
        self.draws.append((found["owner"], amount))
        if self.draw_fails == "lost":
            return httpx.Response(503, json={"code": "unavailable", "message": "Nere."})
        return self._answer(found)

    def _reservation(self, found: dict[str, Any]) -> TokenReservation:
        kind, _, ident = found["owner"].partition(":")
        owner = TokenOwner(kind=TokenOwnerKind(kind), id=UUID(ident))
        left = self.accounts[found["owner"]]
        return TokenReservation(
            id=found["id"],
            owner=owner,
            amount=found["amount"],
            drawn=found["drawn"],
            state=TokenReservationState(found["state"]),
            what=found["what"],
            at=NOW,
            expires=NOW + timedelta(minutes=30),
            balance=TokenBalance(
                owner=owner,
                title="Saldot",
                free_left=0,
                free_monthly=100,
                bought=left,
                reserved=0,
                available=left,
                month="2026-11",
            ),
        )

    def _answer(self, found: dict[str, Any], status: int = 200) -> httpx.Response:
        return httpx.Response(status, json=self._reservation(found).model_dump(mode="json"))


@pytest.fixture
def pretend() -> PretendMeter:
    return PretendMeter()


@pytest.fixture
def world(database_url: str, tmp_path: Path, pretend: PretendMeter) -> Iterator[World]:
    with world_with(database_url, tmp_path, pretend=pretend) as made:
        yield made


def send(
    client: TestClient,
    *,
    ident: str | None = None,
    consent: object = True,
    photos: list[bytes] | None = None,
    fleet: str | None = None,
    **more: Any,
) -> httpx.Response:
    data = {"id": ident or str(uuid.uuid4()), "consent": consent, **more}
    files = [
        ("images", (f"foto{i}.jpg", p, "image/jpeg")) for i, p in enumerate(photos or [photo()])
    ]
    path = f"{API}/readings" + (f"?fleet={fleet}" if fleet else "")
    answered: httpx.Response = client.post(path, data={"data": json.dumps(data)}, files=files)
    return answered


def read(answered: httpx.Response) -> Reading:
    assert answered.status_code == 200, answered.text
    return Reading.model_validate(answered.json())


def rows(database_url: str, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(database_url, autocommit=True) as conn:
        cursor = conn.execute(sql, args)
        return cursor.fetchall() if cursor.description is not None else []


def located() -> bytes:
    """A photo that says where and with what it was taken (CAT-124)."""
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "Kameran AB"
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (59.0, 19.0, 30.0)
    out = io.BytesIO()
    Image.new("RGB", (640, 480), (120, 60, 40)).save(out, "JPEG", exif=exif)
    return out.getvalue()


# --- A reading (CAT-136, CAT-137, CAT-143, CAT-19, CAT-20) -------------------------------------


def test_one_photo_gives_suggestions_and_draws_twelve_tokens_once(
    world: World, pretend: PretendMeter, database_url: str
) -> None:
    reading = read(send(world.a, photos=[located()]))
    assert reading.status == "done"
    assert {name: s.value for name, s in reading.suggestions.items()} == {
        "kind": "freight_wagon",
        "litt": "Hbis",
        "number": "21 74 245 2 253-0",
        "operator": "SJ",
    }
    assert (reading.cost, reading.model, reading.question) == (
        12,
        "anthropic.claude-sonnet-5-5",
        None,
    )
    assert reading.suggested_next_photo == "Ta en närbild på numret."  # CAT-135
    # Reserved with the person who reads, from the owner's balance, and drawn once (CAT-20).
    (reserved,) = pretend.reserved
    assert (reserved["person"], reserved["owner"]["id"], reserved["amount"]) == (A, A, 12)
    assert reserved["key"] == f"catalog-avlasning-{reading.id}"
    assert reserved["what"] == "Avläsning av 1 bild i Catalog"
    assert pretend.draws == [(MINE, 12)]
    assert pretend.accounts[MINE] == 88
    # The photo sent is a JPEG without the position or the camera (CAT-124).
    (asked,) = pretend.reads
    (image,) = asked["images"]
    assert image["media_type"] == "image/jpeg"
    sent = Image.open(io.BytesIO(base64.b64decode(image["data"])))
    assert sent.format == "JPEG" and not sent.getexif()
    assert "Provkonto" not in json.dumps(asked), "nothing about the person goes to the AI"
    assert asked["prompt"].endswith(PROMPT)
    # Nothing is saved as a vehicle or a picture (CAT-136, CAT-143).
    assert world.a.get(f"{API}/vehicles").json()["total"] == 0
    assert world.stored() == []
    assert rows(database_url, "SELECT count(*) FROM picture") == [(0,)]
    assert rows(database_url, "SELECT status, pictures, kind FROM reading") == [
        ("done", 1, "image")
    ]


def test_the_same_id_again_gives_the_same_reading_without_reading_or_drawing(
    world: World, pretend: PretendMeter
) -> None:
    """CAT-144: a retry neither reads nor draws twice. Other photos with the same id are not
    the same reading."""
    ident = str(uuid.uuid4())
    first = send(world.a, ident=ident)
    again = send(world.a, ident=ident)
    assert again.status_code == 200 and again.json() == first.json()
    assert (len(pretend.reserved), len(pretend.reads), len(pretend.draws)) == (1, 1, 1)
    other = send(world.a, ident=ident, photos=[photo(color=(200, 10, 10))])
    assert (other.status_code, other.json()["code"]) == (409, "changed")
    assert len(pretend.reads) == 1


def test_when_the_meter_fails_the_tokens_go_back_and_the_message_is_catalogs_own(
    world: World, pretend: PretendMeter, database_url: str
) -> None:
    pretend.meter_fails = 502
    ident = str(uuid.uuid4())
    failed = send(world.a, ident=ident)
    assert (failed.status_code, failed.json()["code"]) == (502, "reading_failed")
    assert "hemligt" not in failed.text
    assert (
        failed.json()["message"] == "AI:n kunde inte läsa fotona just nu. Inget drogs. Försök igen."
    )
    assert pretend.draws == [] and pretend.accounts[MINE] == 100
    assert rows(database_url, "SELECT status FROM reading") == [("failed",)]
    # The same id is over; a new one reads again.
    assert send(world.a, ident=ident).json()["code"] == "changed"
    pretend.meter_fails = 503
    off = send(world.a)
    assert (off.status_code, off.json()["code"]) == (503, "unavailable")
    pretend.meter_fails = None
    assert read(send(world.a)).cost == 12


def test_an_answer_after_the_vehicle_changed_is_not_used_and_costs_nothing(
    world: World, pretend: PretendMeter, database_url: str
) -> None:
    """CAT-145: the vehicle is changed while the AI reads. The reservation goes back."""
    car = world.vehicle()

    def changed() -> None:
        rows(database_url, "UPDATE vehicle SET version = version + 1 WHERE id = %s", car)

    pretend.during_read = changed
    late = send(world.a, vehicle=car, version=1)
    assert (late.status_code, late.json()["code"]) == (409, "changed")
    assert len(pretend.reads) == 1 and pretend.draws == []
    assert len(pretend.returned) == 1 and pretend.accounts[MINE] == 100
    assert rows(database_url, "SELECT status FROM reading") == [("discarded",)]
    # A reading of the vehicle as it is now is used; an old version is refused at once.
    pretend.during_read = None
    stale = send(world.a, vehicle=car, version=1)
    assert (stale.status_code, stale.json()["code"]) == (409, "changed")
    assert len(pretend.reads) == 1
    assert read(send(world.a, vehicle=car, version=2)).cost == 12
    assert world.a.get(f"{API}/vehicles/{car}").json()["number"] == HBIS["number"]
    other = send(world.a, vehicle=str(uuid.uuid4()), version=1)
    assert other.status_code == 404


def test_when_the_draw_fails_the_reading_is_paid_only_if_id_drew_it(
    world: World, pretend: PretendMeter, database_url: str
) -> None:
    """ID does not draw: the tokens go back and the reading fails. ID drew, but its answer was
    lost: ID says so when the tokens are to go back, and the reading is done."""
    pretend.draw_fails = "down"
    down = send(world.a)
    assert (down.status_code, down.json()["code"]) == (503, "unavailable")
    assert pretend.draws == [] and len(pretend.returned) == 1 and pretend.accounts[MINE] == 100
    pretend.draw_fails = "lost"
    assert read(send(world.a)).cost == 12
    assert pretend.draws == [(MINE, 12)] and pretend.accounts[MINE] == 88
    assert rows(database_url, "SELECT status FROM reading ORDER BY created_at") == [
        ("failed",),
        ("done",),
    ]


# --- What the AI may suggest (CAT-138, CAT-139, CAT-140) --------------------------------------


def test_only_what_the_rules_allow_is_suggested(world: World, pretend: PretendMeter) -> None:
    """An unreadable character stays a ?. A maker guessed from the model's look is dropped, and
    so is a field that does not exist; a maker read from the box is kept."""
    fields = {
        "kind": said("freight_wagon", "visual_inference"),
        "number": said("21 74 245 2 2?3-0", confidence="low"),
        "litt": said("Hbis", "visual_inference"),
        "maker": said("Märklin", "visual_inference"),
        "article_number": said("4740"),
        "scale": said("H0"),
        "dcc_address": said("3"),
    }
    every: dict[str, Any] = {name: said(None) for name in FIELDS} | fields
    pretend.text = (
        "```json\n"
        + json.dumps({"summary": "", "fields": every, "warnings": [], "suggested_next_photo": ""})
        + "\n```"
    )
    reading = read(send(world.a))
    assert {name: s.value for name, s in reading.suggestions.items()} == {
        "kind": "freight_wagon",
        "number": "21 74 245 2 2?3-0",
        "article_number": "4740",
    }
    assert reading.suggestions["number"].confidence == "low"
    # The EVN's check digit says which digit adds up (CAT-140).
    assert reading.question is not None
    assert (reading.question.field, reading.question.options) == ("number", ["21 74 245 2 253-0"])


@pytest.mark.parametrize(
    "text",
    [
        "Jag ser en godsvagn.",
        '{"summary": "", "fields": {}',
        json.dumps({"summary": "", "fields": {}, "warnings": [], "suggested_next_photo": ""}),
        answer(kind=said("tank_engine", "visual_inference")),
        answer(
            number={"value": "1", "confidence": "säker", "basis": "visible_text", "evidence": ""}
        ),
        answer(number=said("x" * 81)),
        answer(number=said("21\n74")),
        HBIS_READ.replace('"warnings": ["Kontrollera numret."]', '"warnings": "Kontrollera"'),
        HBIS_READ.replace('"summary": "En godsvagn från sidan."', '"summary": NaN'),
    ],
)
def test_an_answer_that_does_not_follow_the_form_fails_closed(text: str) -> None:
    with pytest.raises(Unreadable):
        understand(text)


def test_a_malformed_answer_fails_and_the_tokens_go_back(
    world: World, pretend: PretendMeter, database_url: str
) -> None:
    pretend.text = "Det här är ingen JSON."
    failed = send(world.a)
    assert (failed.status_code, failed.json()) == (
        502,
        {"code": "reading_failed", "message": "AI-svaret kunde inte läsas. Inget har ändrats."},
    )
    assert pretend.draws == [] and len(pretend.returned) == 1 and pretend.accounts[MINE] == 100
    assert rows(database_url, "SELECT status FROM reading") == [("failed",)]


def test_the_evn_question_offers_only_the_digits_whose_check_digit_adds_up() -> None:
    """CAT-140: one uncertain digit in a twelve-digit EVN, and the painted check digit."""
    question = question_for("21 74 245 2 2?3-0")
    assert question is not None and question.options == ["21 74 245 2 253-0"]
    assert question_for("31 74 3?3 3 013-1") is not None
    # The check digit itself unreadable: the one that adds up is computed.
    check = question_for("21 74 245 2 253-?")
    assert check is not None and check.options == ["21 74 245 2 253-0"]
    # Nothing tells the digits apart without a painted check digit, or with two ?.
    assert question_for("21 74 245 2 2?3") is None
    assert question_for("21 74 245 2 ??3-0") is None
    assert question_for("21 74 245 2 253-0") is None
    assert question_for("Rc6 13?7") is None


# --- One at a time, ten an hour (CAT-146) -------------------------------------------------------


def pending(database_url: str, pretend: PretendMeter, person: str) -> tuple[str, str]:
    """A reading still running, as another request would leave it, with its reservation."""
    owner = f"person:{person}"
    reservation = str(uuid.uuid4())
    held: dict[str, Any] = {"id": reservation, "owner": owner, "amount": 12, "drawn": 0}
    held.update(state="held", what="Avläsning av 1 bild i Catalog", key="k", answer=None)
    pretend.reservations[reservation] = held
    pretend.accounts[owner] -= 12
    ident = str(uuid.uuid4())
    rows(
        database_url,
        "INSERT INTO reading (id, owner_id, person_id, kind, basis, pictures, month, reservation, "
        "expires_at) VALUES (%s, %s, %s, 'image', %s, 1, '2026-11', %s, "
        "now() + interval '5 minutes') RETURNING id",
        ident,
        person,
        person,
        "0" * 64,
        reservation,
    )
    return ident, reservation


def test_one_reading_at_a_time_per_person(
    world: World, pretend: PretendMeter, database_url: str
) -> None:
    running, reservation = pending(database_url, pretend, A)
    busy = send(world.a)
    assert (busy.status_code, busy.json()["code"]) == (409, "reading_busy")
    assert pretend.reserved == []
    assert read(send(world.b)).cost == 12, "another person reads at the same time"
    # A reading that never finished is given up, its tokens go back, and the next one goes ahead.
    rows(
        database_url,
        "UPDATE reading SET expires_at = now() - interval '1 second' WHERE id = %s",
        running,
    )
    assert read(send(world.a)).cost == 12
    assert rows(database_url, "SELECT status FROM reading WHERE id = %s", running) == [("failed",)]
    assert pretend.returned == [reservation]
    assert pretend.accounts[MINE] == 88


def test_at_most_ten_readings_an_hour(
    world: World, pretend: PretendMeter, database_url: str
) -> None:
    for _ in range(9):
        rows(
            database_url,
            "INSERT INTO reading (id, owner_id, person_id, kind, basis, pictures, status, month, "
            "expires_at, created_at) VALUES (%s, %s, %s, 'image', %s, 1, 'failed', '2026-11', "
            "now(), now() - interval '10 minutes')",
            str(uuid.uuid4()),
            A,
            A,
            "0" * 64,
        )
    assert read(send(world.a)).cost == 12  # the tenth
    eleventh = send(world.a)
    assert (eleventh.status_code, eleventh.json()["code"]) == (429, "too_many")
    assert 3000 <= int(eleventh.headers["Retry-After"]) <= 3000 + 60
    assert len(pretend.reserved) == 1


# --- The consent (CAT-142) ----------------------------------------------------------------------


def test_the_first_reading_needs_the_consent_which_is_kept_once(
    world: World, pretend: PretendMeter, database_url: str
) -> None:
    before = ReadingConsent.model_validate(world.a.get(f"{API}/readings/consent").json())
    assert (before.available, before.given, before.price_per_picture) == (True, False, 12)
    assert before.text == (
        "Fotona, utan platsuppgifter och annan metadata, skickas till TrainMeets AI: Claude från "
        "Anthropic via Amazon Bedrock i EU."
    )
    assert (before.balance, before.own_ai) == (100, None)

    refused = send(world.a, consent=False)
    assert (refused.status_code, refused.json()["code"]) == (422, "consent_required")
    assert pretend.reserved == [] and pretend.reads == []
    read(send(world.a, consent=True))
    read(send(world.a, consent=True))
    read(send(world.a, consent=False))
    assert rows(database_url, "SELECT person_id::text, kind FROM privacy_event") == [
        (A, "ai_reading_consent")
    ]
    after = ReadingConsent.model_validate(world.a.get(f"{API}/readings/consent").json())
    assert after.given is True


def test_with_own_ai_the_consent_names_it_and_nothing_is_drawn(
    world: World, pretend: PretendMeter
) -> None:
    pretend.own_ai[MINE] = "en-modell"
    consent = ReadingConsent.model_validate(world.a.get(f"{API}/readings/consent").json())
    assert (consent.sent_to, consent.price_per_picture) == ("din egen AI (en-modell)", 0)
    assert consent.text.endswith("skickas till din egen AI (en-modell).")
    reading = read(send(world.a, photos=[photo(), photo(color=(1, 2, 3))]))
    assert (reading.cost, reading.model) == (0, "en-modell (egen AI)")
    assert [r["amount"] for r in pretend.reserved] == [0]
    assert pretend.draws == [(MINE, 0)] and pretend.accounts[MINE] == 100


def test_a_short_balance_reads_nothing(world: World, pretend: PretendMeter) -> None:
    pretend.accounts[MINE] = 20
    short = send(world.a, photos=[photo(), photo(color=(9, 9, 9))])
    assert (short.status_code, short.json()["code"]) == (402, "no_tokens")
    assert "24 tokens och 20 finns kvar" in short.json()["message"]
    assert pretend.reserved == [] and pretend.reads == []


# --- Who may read (CAT-46) ----------------------------------------------------------------------


def test_only_the_owner_reads_with_ai(world: World, pretend: PretendMeter) -> None:
    for role, status in (("editor", 403), ("viewer", 403), (None, 404)):
        if role is None:
            world.id.roles.pop((B, A), None)
        else:
            world.id.roles[(B, A)] = role
        assert send(world.b, fleet=A).status_code == status
        assert world.b.get(f"{API}/readings/consent?fleet={A}").status_code == status
    assert pretend.reserved == []
    assert world.nobody.post(f"{API}/readings").status_code == 401


def test_a_clubs_administrator_reads_in_the_clubs_fleet_from_its_balance(
    world: World, pretend: PretendMeter
) -> None:
    world.id.roles[(B, CLUB)] = "admin"
    world.id.clubs.add(CLUB)
    pretend.accounts[f"club:{CLUB}"] = 300
    assert world.b.get(f"{API}/fleets").status_code == 200  # the club gets its owner row
    consent = world.b.get(f"{API}/readings/consent?fleet={CLUB}").json()
    assert (consent["payer"], consent["balance"]) == ("Västby MJK", 300)
    assert read(send(world.b, fleet=CLUB)).cost == 12
    (reserved,) = pretend.reserved
    assert (reserved["person"], reserved["owner"]) == (B, {"kind": "club", "id": CLUB})
    assert pretend.draws == [(f"club:{CLUB}", 12)]


def test_a_person_id_does_not_know_cannot_read(world: World, pretend: PretendMeter) -> None:
    """A trial account in the test environment: ID does not know it, so there is no balance."""
    del pretend.accounts[MINE]
    consent = world.a.get(f"{API}/readings/consent").json()
    assert (consent["available"], consent["message"]) == (
        False,
        "AI-avläsningen kräver ett konto i TrainMeet ID.",
    )
    refused = send(world.a)
    assert (refused.status_code, refused.json()["code"]) == (503, "unavailable")


def test_without_id_there_is_no_reading(database_url: str, tmp_path: Path) -> None:
    settings = Settings(
        database_url=database_url,
        migrate="auto",
        trial_login=True,
        web_dir=tmp_path,
        build=CatalogVersion(version="0.1.0"),
        pictures_dir=tmp_path / "bilder",
    )
    with TestClient(create_app(settings)) as client:
        assert client.post(f"{API}/trial/login", json={"account": A}).status_code == 200
        consent = client.get(f"{API}/readings/consent").json()
        assert (consent["available"], consent["message"]) == (
            False,
            "AI-avläsningen kräver TrainMeet ID.",
        )
        off = send(client)
        assert (off.status_code, off.json()["code"]) == (503, "unavailable")


# --- The form -----------------------------------------------------------------------------------


def test_the_form_is_read_strictly(world: World, pretend: PretendMeter) -> None:
    assert send(world.a, photos=[photo()] * 5).status_code == 422
    assert send(world.a, vehicle=str(uuid.uuid4())).status_code == 422  # without its version
    assert send(world.a, consent="ja").status_code == 422
    nothing = world.a.post(f"{API}/readings", data={"data": json.dumps({"id": str(uuid.uuid4())})})
    assert nothing.status_code == 422
    plain = world.a.post(f"{API}/readings", json={"id": str(uuid.uuid4())})
    assert plain.status_code == 422
    other = send(world.a, photos=[b"inte en bild"])
    assert (other.status_code, other.json()["code"]) == (415, "bad_picture")
    assert pretend.reserved == []
