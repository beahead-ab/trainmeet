"""Efter pappret over HTTP (LOK-13, LOK-29, LOK-33, PLAN-40, TOKEN-14).

A driver photographs a duty missing from the plan. The price is told first; the photos are
cleaned of their metadata before anything is sent; the hub's own AI reads them, or TrainMeets AI
through the meter in ID on the meet's tokens or the driver's own, as the meet chose in Förarna.
Reserved, read, and drawn only when the reading became the driver's service, else given back.
The planned services nearest the paper's start come with the reading. Trafikledningen approves
or rejects it in Förare; until it approves, no station sees it.

No AI provider is called: the pretend ID of the import's tests answers the balance and the
meter, and the hub's own AI is the stand-in of integrationer/tests/fake_ai.py.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts import driver as contract
from contracts import planning, station
from contracts.drift import Now
from contracts.tokens import MeterAnswer, TokenOwner, TokenOwnerKind, TokenReservation
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.paper_reading import LOG_IN, NO_AI
from hub.tests.test_id_roles import AUTUMN, make_meet
from hub.tests.test_planering import VARNAMO
from hub.tests.test_station_api import Client
from hub.tests.test_trainmeet_ai import CLUB, PretendIdMeter, hub_with
from integrationer.ai import drawn
from integrationer.tests.fake_ai import KEY, FakeAi, serving

API = "/api/drift/1/drivers"
PLAN = "/api/planering/1"
PIN = "482915"
ON_THE_MEET = ("192.168.4.20", 50000)
CLOUD = ("203.0.113.7", 50000)
CAMERA = b"GPS 57.1834 N 14.0432 E, Pixel 9"
D3 = {"kind": "duty", "id": "d3"}


def page(number: str = "4521") -> bytes:
    """A photo of a page, as a phone's camera might send it: a PNG with a text chunk saying
    where it was taken. Cleaned, it is the picture alone: drawn(number)."""
    picture = drawn(number)
    body = b"Comment\x00" + CAMERA
    chunk = struct.pack(">I", len(body)) + b"tEXt" + body
    chunk += struct.pack(">I", zlib.crc32(b"tEXt" + body) & 0xFFFFFFFF)
    return picture[:33] + chunk + picture[33:]


def form(*pages: bytes) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("pages", (f"sida{n}.png", data, "image/png")) for n, data in enumerate(pages, 1)]


def answer(**changed: Any) -> str:
    """What the AI wrote for Tjänst 24 on Provbanan: Åsen's departure could not be read."""
    said: dict[str, Any] = {
        "number": "24",
        "train": "G 4521",
        "operator": "Green Cargo",
        "start": {"time": "06:31", "place": "Norrby"},
        "end": {"time": "07:20", "place": "Sjövik"},
        "rows": [
            {"place": "Norrby", "departure": "06:41", "track": "3", "note": "Koppla loket."},
            {"place": "Åsen", "arrival": "06:49", "departure": "06:5?"},
            {"place": "Mellanå", "arrival": "06:59", "departure": "07:01"},
            {"place": "Sjövik", "arrival": "07:10", "track": "2"},
        ],
    }
    return "Här är avskriften:\n" + json.dumps({**said, **changed}, ensure_ascii=False)


VARNAMO_PAPER = json.dumps(
    {
        "number": "24",
        "train": "G 4521",
        "start": {"time": "06:44", "place": "Munkerød"},
        "end": {"time": "07:30", "place": "Gårdsjö"},
        "rows": [
            {"place": "Munkerød", "departure": "06:50", "track": "3"},
            {"place": "Lekby", "arrival": "?", "departure": "07:02"},
            {"place": "Gårdsjö", "arrival": "07:10"},
        ],
    }
)


# --- In the cloud hub: TrainMeets AI on the meet's tokens or the driver's own -----------------


@dataclass
class Meter(PretendIdMeter):
    """ID's meter as the pretend ID of the import's tests, which also counts the draws and the
    reservations given back, and costs 12 tokens a picture."""

    draws: list[int] = field(default_factory=list)
    returns: int = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        club = TokenOwner(kind=TokenOwnerKind.CLUB, id=CLUB)
        if request.url.host == "id-api" and path.endswith("/draw"):
            self.draws.append(json.loads(request.content)["amount"])
            return httpx.Response(200, json=self.reservation(club, self.draws[-1]))
        if request.url.host == "id-api" and path.endswith("/return"):
            self.returns += 1
            return httpx.Response(200, json=self.reservation(club, 0))
        if request.url.host == "id-api" and path.endswith("/meter") and not self.failing:
            asked = json.loads(request.content)
            self.reads.append(asked)
            owner = TokenOwner.model_validate(self.reserved[-1]["owner"])
            read = MeterAnswer(
                text=self.text,
                cost=12 * len(asked["images"]),
                model="anthropic.claude-sonnet-5-5",
                reservation=TokenReservation.model_validate(self.reservation(owner, 12)),
            )
            return httpx.Response(200, json=read.model_dump(mode="json"))
        return super().handle(request)


@dataclass
class Cloud:
    pretend: Meter
    owner: TestClient
    person: TestClient
    meet: str

    def phone(self, name: str, client: TestClient | None = None) -> TestClient:
        """A driver's phone that came in with the meet's code."""
        phone = client or TestClient(self.owner.app, base_url=str(self.owner.base_url))
        code = self.owner.get(API + "/connect").json()["code"]
        joined = phone.post(API + "/join", json={"code": code, "name": name})
        assert joined.status_code == 201, joined.text
        return phone


@pytest.fixture
def cloud(tmp_path: Path) -> Cloud:
    """The cloud hub with ID's API, running Höstträffen: the club's meet in ID, planned from
    Värnamo's plan by its organizer, published and started with the hub's PIN."""
    pretend = Meter(text=VARNAMO_PAPER)
    pretend.roles = {str(AUTUMN): ["organizer"]}
    owner, person = hub_with(pretend, tmp_path)
    meet = planning.Draft.model_validate(make_meet(person).json()).meet.id
    sent = person.post(
        f"{PLAN}/meets/{meet}/sources",
        params={"name": "Värnamo.json.gz"},
        content=VARNAMO,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert sent.status_code == 201, sent.text
    source = sent.json()["source"]["id"]
    assert person.post(f"{PLAN}/meets/{meet}/sources/{source}/apply").status_code == 200
    assert owner.post(f"{PLAN}/meets/{meet}/versions").status_code == 201
    started = owner.post("/api/drift/1/start", json={"meet": meet, "version": 1})
    assert started.status_code == 201, started.text
    return Cloud(pretend, owner, person, meet)


def sent_bytes(read: dict[str, Any]) -> bytes:
    return b"".join(base64.b64decode(image["data"]) for image in read["images"])


def test_the_price_is_told_first_and_the_driver_pays_with_their_own(cloud: Cloud) -> None:
    """LOK-33, TOKEN-14: the driver's own tokens by default, 12 a page, told before anything is
    read; not logged in with TrainMeet ID, the driver is told to log in or ask Trafikledningen.
    The photos go to the meter without the camera's text, and the planned services nearest the
    paper's start come with the reading (LF16)."""
    pretend = cloud.pretend
    chosen = contract.PaperReadingSettings.model_validate(
        cloud.person.get(f"{PLAN}/meets/{cloud.meet}/paper-reading").json()
    )
    assert (chosen.payer, chosen.per_page, chosen.trainmeet_ai, chosen.own_ai) == (
        "driver",
        12,
        True,
        None,
    )
    bo = cloud.phone("Bo")
    price = contract.PaperPrice.model_validate(bo.get(API + "/paper/price?pages=2").json())
    assert (price.ready, price.message, price.price) == (False, LOG_IN, 24)
    refused = bo.post(API + "/paper", files=form(page(), page("4522")))
    assert (refused.status_code, refused.json()["detail"]) == (403, LOG_IN)
    assert pretend.reserved == [] and pretend.reads == []

    # Logged in with TrainMeet ID, the driver's own balance pays.
    me = cloud.phone("Provare Ett", cloud.person)
    price = contract.PaperPrice.model_validate(me.get(API + "/paper/price?pages=2").json())
    assert (price.ready, price.price, price.per_page, price.paid_by, price.payer) == (
        True,
        24,
        12,
        "driver",
        "Provare Ett",
    )
    assert price.available == 100
    assert pretend.reserved == [], "the price is told before anything is reserved"
    read = me.post(API + "/paper", params={"price": 24}, files=form(page(), page("4522")))
    assert read.status_code == 201, read.text
    found = contract.PaperService.model_validate(read.json())
    assert (found.status, found.paid_by, found.cost, found.pages, found.number) == (
        "waiting",
        "driver",
        24,
        2,
        "24",
    )
    assert [(r.place_name, r.arrival, r.unreadable) for r in found.rows] == [
        ("Munkerød", None, False),
        ("Lekby", None, True),
        ("Gårdsjö", "07:10", False),
    ]
    assert found.candidates[0].number == "39"
    assert found.said.startswith("Ingen tjänst startar 06:44 vid Munkerød. Närmast: 39 kl. 06:41")
    (reserved,) = pretend.reserved
    person = TokenOwner.model_validate(reserved["owner"])
    assert (person.kind, reserved["amount"]) == ("person", 24)
    (meter,) = pretend.reads
    assert meter["hold"] is True and len(meter["images"]) == 2
    assert CAMERA not in sent_bytes(meter), "cleaned before anything is sent"
    assert sent_bytes(meter) == drawn("4521") + drawn("4522")
    assert (pretend.draws, pretend.returns) == ([24], 0), "drawn once it is the driver's service"
    mine = contract.DriverMe.model_validate(me.get(API + "/me").json())
    assert mine.service is not None and mine.service.paper == "waiting"
    assert mine.paper is not None and mine.paper.paper == found.paper
    plan = contract.Korplan.model_validate(me.get(API + "/korplan").json())
    assert plan.paper == "waiting" and plan.rows[0].place_name == "Munkerød"


def test_the_meets_tokens_pay_and_the_driver_needs_no_account(cloud: Cloud) -> None:
    """LOK-33, PLAN-40, TK16: the planner chooses the meet's tokens in Förarna, logged in with
    TrainMeet ID; the club of the meet in ID pays, and the driver needs no account."""
    pretend = cloud.pretend
    by_pin = cloud.owner.post(f"{PLAN}/meets/{cloud.meet}/paper-reading", json={"payer": "meet"})
    assert by_pin.status_code == 422 and "TrainMeet ID" in by_pin.json()["detail"]
    chosen = cloud.person.post(f"{PLAN}/meets/{cloud.meet}/paper-reading", json={"payer": "meet"})
    assert chosen.status_code == 200, chosen.text
    settings = contract.PaperReadingSettings.model_validate(chosen.json())
    assert (settings.payer, settings.payer_title, settings.available) == ("meet", "Västby MJK", 300)
    looker = TestClient(cloud.owner.app, base_url=str(cloud.owner.base_url))
    seen = looker.get(f"{PLAN}/meets/{cloud.meet}/paper-reading").json()
    assert (seen["payer"], seen["payer_title"], seen["available"]) == ("meet", None, None)
    assert looker.post(
        f"{PLAN}/meets/{cloud.meet}/paper-reading", json={"payer": "driver"}
    ).status_code in (401, 403)

    bo = cloud.phone("Bo")
    price = contract.PaperPrice.model_validate(bo.get(API + "/paper/price?pages=1").json())
    assert (price.ready, price.price, price.paid_by, price.payer) == (
        True,
        12,
        "meet",
        "Västby MJK",
    )
    read = bo.post(API + "/paper", files=form(page()))
    assert read.status_code == 201, read.text
    assert contract.PaperService.model_validate(read.json()).paid_by == "meet"
    (reserved,) = pretend.reserved
    assert (reserved["owner"], reserved["amount"]) == ({"kind": "club", "id": str(CLUB)}, 12)
    assert reserved["person"] == pretend.subject, "the planner who chose it, for the club"
    assert pretend.draws == [12]


def test_reserved_drawn_on_success_and_given_back_on_failure(cloud: Cloud) -> None:
    """TOKEN-24, TOKEN-04: a reading that cannot be used is given back, as is one the AI did
    not answer; a short balance or a higher price than shown reads nothing; nothing is read for
    a driver who already has a service."""
    pretend = cloud.pretend
    me = cloud.phone("Provare Ett", cloud.person)
    pretend.text = "Jag ser ingen tidtabell."
    unusable = me.post(API + "/paper", files=form(page()))
    assert unusable.status_code == 422 and "tidtabell" in unusable.json()["detail"]
    assert (len(pretend.reserved), pretend.draws, pretend.returns) == (1, [], 1)

    pretend.failing = True
    silent = me.post(API + "/paper", files=form(page()))
    assert (silent.status_code, silent.json()["detail"]) == (
        502,
        "TrainMeets AI svarar inte just nu. Inget drogs.",
    )
    assert (len(pretend.reserved), pretend.draws, pretend.returns) == (2, [], 2)
    pretend.failing = False

    pretend.available[f"person:{pretend.subject}"] = 5
    short = me.post(API + "/paper", files=form(page()))
    assert short.status_code == 402 and "5 tokens kvar, 12 behövs" in short.json()["detail"]
    pretend.available[f"person:{pretend.subject}"] = 100
    dearer = me.post(API + "/paper", params={"price": 0}, files=form(page()))
    assert dearer.status_code == 409 and "12 tokens" in dearer.json()["detail"]
    assert len(pretend.reserved) == 2, "nothing more reserved"

    pretend.text = VARNAMO_PAPER
    assert me.post(API + "/paper", files=form(page())).status_code == 201
    assert (pretend.draws, pretend.returns) == ([12], 2)
    again = me.post(API + "/paper", files=form(page()))
    assert (again.status_code, again.json()["detail"]) == (
        409,
        "Du har redan en tjänst. Släpp den först.",
    )
    assert len(pretend.reserved) == 3, "one service at a time, checked before it costs"


# --- On the meet's hub with its own AI: Trafikledningen decides ------------------------------


@pytest.fixture
def made(tmp_path: Path) -> Any:
    return create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db")


@pytest.fixture
def admin(made: Any) -> TestClient:
    """Trafikledningen with the hub's PIN, with Provbanan started as the hub's meet."""
    client = TestClient(made, client=ON_THE_MEET)
    assert client.post("/api/hub/setup", json={"name": "Pi:n", "pin": PIN}).status_code == 201
    assert client.post("/api/drift/1/start", json={"version": 1}).status_code == 201
    return client


def phone(made: Any, admin: TestClient, name: str) -> TestClient:
    client = TestClient(made, client=CLOUD)
    code = admin.get(API + "/connect").json()["code"]
    assert client.post(API + "/join", json={"code": code, "name": name}).status_code == 201
    return client


def tkl(admin: TestClient, place: str) -> Client:
    """A TKL at the place, approved by Trafikledningen."""
    join = admin.get("/api/drift/1/connect").json()["code"]
    client = Client(admin, join, [place])
    approved = admin.post(
        "/api/drift/1/clients/approve", json={"client_id": client.client_id, "places": [place]}
    )
    assert approved.status_code == 200, approved.text
    client.poll()
    return client


def own_ai(admin: TestClient, fake: FakeAi) -> None:
    given = {"format": "chat", "address": fake.address, "model": "en-modell", "key": KEY}
    assert admin.post("/api/hub/ai", json=given).status_code == 200


def overview(admin: TestClient) -> contract.DriverOverview:
    return contract.DriverOverview.model_validate(admin.get(API + "/overview").json())


def test_the_hubs_own_ai_reads_and_no_station_sees_it_until_approved(
    made: Any, admin: TestClient
) -> None:
    """TOKEN-13, LOK-13, LF22: the hub's own AI reads for nothing; Förare sees the paper with a
    mark and Godkänn or Avslå; the stations see the train only once it is approved, marked."""
    anna = phone(made, admin, "Anna")
    price = contract.PaperPrice.model_validate(anna.get(API + "/paper/price?pages=1").json())
    assert (price.ready, price.message) == (False, NO_AI)
    assert anna.post(API + "/paper", files=form(page())).json()["detail"] == NO_AI
    norrby, asen = tkl(admin, "nby"), tkl(admin, "asn")
    fake = FakeAi(answers={hashlib.sha256(drawn("4521")).hexdigest(): answer()})
    with serving(fake):
        own_ai(admin, fake)
        price = contract.PaperPrice.model_validate(anna.get(API + "/paper/price?pages=1").json())
        assert (price.ready, price.price, price.paid_by, price.payer) == (
            True,
            0,
            "hub",
            "Hubbens egen AI",
        )
        read = anna.post(API + "/paper", files=form(page()))
        assert read.status_code == 201, read.text
    found = contract.PaperService.model_validate(read.json())
    assert (found.paid_by, found.cost, found.status) == ("hub", 0, "waiting")
    assert [c.number for c in found.candidates] == ["3", "1", "2"]
    assert (
        found.said
        == "Ingen tjänst startar 06:31 vid Norrby. Närmast: 3 kl. 06:35, 1 kl. 06:00, 2 kl. 06:05."
    )
    assert found.rows[1].departure is None and found.rows[1].unreadable
    sent = fake.asked[-1]["body"]["messages"][0]["content"]
    assert CAMERA.decode() not in json.dumps(sent)

    # Not seen by the stations: no call, no clearance, not in Nu's trains.
    for client, place in ((norrby, "nby"), (asen, "asn")):
        seen = client.snapshot(place)
        assert all(call.train_number != "G 4521" for call in seen.calls)
        assert all(not call.paper for call in seen.calls) and seen.clearances == []
    assert all(
        not leg.paper for leg in Now.model_validate(admin.get("/api/drift/1/now").json()).legs
    )

    # Förare: the paper with its mark, the photos, and the planned services beside it.
    (waiting,) = overview(admin).papers
    assert (waiting.status, waiting.driver_name, waiting.number) == ("waiting", "Anna", "24")
    (row,) = [r for r in overview(admin).drivers if r.driver.name == "Anna"]
    assert row.service is not None and row.service.paper == "waiting"
    photo = admin.get(waiting.photos[0])
    assert (photo.status_code, photo.content) == (200, drawn("4521"))
    assert anna.get(waiting.photos[0]).status_code == 200, "the driver's own"
    assert TestClient(made, client=CLOUD).get(waiting.photos[0]).status_code == 404

    approved = admin.post(f"{API}/paper/{found.paper}/approve", json={})
    assert approved.status_code == 200, approved.text
    (decided,) = contract.DriverOverview.model_validate(approved.json()).papers
    assert decided.status == "approved" and decided.train is not None
    again = admin.post(f"{API}/paper/{found.paper}/approve", json={})
    assert (again.status_code, again.headers["X-Reason"]) == (409, "paper_decided")

    # Now the stations see it, marked, and can clear it.
    (call,) = [c for c in norrby.snapshot("nby").calls if c.train_number == "G 4521"]
    assert call.paper and station.Action.CLEARANCE_REQUEST in call.allowed_actions
    norrby.command(
        station.Action.CLEARANCE_REQUEST,
        "nby",
        call=call.call,
        section="s-nby-asn",
        clearance_id="clr-papper-1",
    )
    assert [c.paper for c in asen.snapshot("asn").clearances] == [True]
    now = Now.model_validate(admin.get("/api/drift/1/now").json())
    assert any(leg.paper for leg in now.legs)
    assert any(change.change.kind == "extra" and change.change.paper for change in now.changes)
    mine = contract.DriverMe.model_validate(anna.get(API + "/me").json())
    assert mine.service is not None and mine.service.paper == "approved"
    plan = contract.Korplan.model_validate(anna.get(API + "/korplan").json())
    assert plan.paper == "approved" and plan.rows[0].call == call.call


def test_a_rejected_paper_tells_the_driver_why(made: Any, admin: TestClient) -> None:
    """LOK-13: rejected, the driver no longer runs it and reads the reason. A driver who takes
    a planned service instead lets the paper go before anyone decided (LF16)."""
    anna, bo = phone(made, admin, "Anna"), phone(made, admin, "Bo")
    fake = FakeAi(answers={hashlib.sha256(drawn("4521")).hexdigest(): answer()})
    with serving(fake):
        own_ai(admin, fake)
        first = contract.PaperService.model_validate(
            anna.post(API + "/paper", files=form(page())).json()
        )
        bo.post(API + "/paper", files=form(page()))
    lead = TestClient(made, client=ON_THE_MEET)
    assert lead.post(f"{API}/paper/{first.paper}/reject", json={"reason": "x"}).status_code in (
        401,
        403,
    )
    rejected = admin.post(
        f"{API}/paper/{first.paper}/reject", json={"reason": "Tjänst 3 är samma. Ta den."}
    )
    assert rejected.status_code == 200, rejected.text
    mine = contract.DriverMe.model_validate(anna.get(API + "/me").json())
    assert mine.service is None
    assert mine.paper is not None and (mine.paper.status, mine.paper.reason) == (
        "rejected",
        "Tjänst 3 är samma. Ta den.",
    )
    # Bo takes service 3 in its place: his paper is let go.
    taken = bo.post(API + "/claim", json=D3)
    assert taken.status_code == 200, taken.text
    statuses = sorted(p.status for p in overview(admin).papers)
    assert statuses == ["rejected", "withdrawn"]


def test_the_photos_come_as_a_form_of_one_to_four_pictures(made: Any, admin: TestClient) -> None:
    anna = phone(made, admin, "Anna")
    five = anna.post(API + "/paper", files=form(*(page() for _ in range(5))))
    assert (five.status_code, five.json()["detail"]) == (422, "Fota 1–4 sidor.")
    gif = anna.post(
        API + "/paper", files=[("pages", ("sida.gif", b"GIF89a" + b"0" * 40, "image/gif"))]
    )
    assert gif.status_code == 422 and "JPEG, PNG eller WebP" in gif.json()["detail"]
    bare = anna.post(API + "/paper", content=page(), headers={"Content-Type": "image/png"})
    assert bare.status_code == 422
    other = anna.post(
        API + "/paper", files=form(page()), headers={"Origin": "https://evil.example"}
    )
    assert other.status_code == 403
    assert (
        TestClient(made, client=CLOUD).post(API + "/paper", files=form(page())).status_code == 401
    )
    assert anna.get(API + "/paper/price?pages=5").status_code == 422
