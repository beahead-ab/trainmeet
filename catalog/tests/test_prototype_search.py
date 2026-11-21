"""Webbsökningen i förebildskatalogen (#53 del b, CAT-166–CAT-172, CAT-219, C40).

A pretend ID keeps the balances and answers the reservations, the meter's web search and the
refund as ID does (contracts/tokens.py). The search's answer is what the tests write: values
with citations, and the results of the pretend search. No test asks a real search (CAT-154).
The people log in with the trial login: Provkonto A and B search and propose, and Provkonto C
reviews. Ported from TrainCatalog's catalog/test_research.py (ResearchTests).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from catalog.app import create_app
from catalog.id_roles import unavailable
from catalog.prototype_search import Searches
from catalog.publishers import PUBLISHERS
from catalog.settings import Settings
from catalog.tests.test_pictures import world_with
from catalog.tests.test_prototypes import (
    API,
    C,
    Catalog,
    PretendReviewers,
    listed,
    proposal,
    proposed,
    reviewed,
)
from catalog.tests.test_reading import MINE, read, send
from catalog.tests.test_sharing import A
from contracts.catalog import (
    CatalogVersion,
    DroppedReason,
    Prototype,
    PrototypeRevision,
    PrototypeSearch,
    PrototypeSearchConsent,
    PublisherKind,
)
from contracts.tokens import MeterSearchAnswer

MUSEUM = "https://museum.example.org/fordon/hbis"
WIKI = "https://sv.wikipedia.example/wiki/Hbis"
INVENTED = "https://museum.example.org/fordon/finns-inte"
SEARCH = f"{API}/prototypes/search"


def cited(url: str, text: str, title: str = "") -> dict[str, str]:
    return {"url": url, "title": title, "cited_text": text}


VALUES: list[dict[str, Any]] = [
    {
        "key": "length_over_buffers",
        "value": "14020",
        "citations": [cited(MUSEUM, "Längd över buffertar 14 020 mm", "Hbis – Museet")],
    },
    {
        "key": "max_speed",
        "value": "100",
        "citations": [cited(WIKI, "Största tillåtna hastighet 100 km/h", "Hbis – Wikipedia")],
    },
    {"key": "axles", "value": "2", "citations": [cited(MUSEUM, "En tvåaxlig godsvagn")]},
    # The AI's own inventions, which Catalog refuses (CAT-167, CAT-169):
    {"key": "weight", "value": "14.5", "citations": [cited(INVENTED, "Egenvikt 14,5 ton")]},
    {"key": "built", "value": "1970", "citations": [cited(MUSEUM, "Beställdes 1970 av SJ")]},
    {"key": "brake", "value": "KE-GP", "citations": []},
]
RESULTS = [
    {"url": MUSEUM, "title": "Hbis – Museet", "page_age": "April 30, 2025"},
    {"url": WIKI, "title": "Hbis – Wikipedia"},
]


@dataclass
class PretendSearcher(PretendReviewers):
    """ID, whose meter also searches the web: the answer is values = ... and results = ..."""

    connected: bool = True
    values: list[dict[str, Any]] = field(default_factory=lambda: list(VALUES))
    results: list[dict[str, Any]] = field(default_factory=lambda: list(RESULTS))
    search_fails: int | None = None
    garbled: bool = False
    """The meter answers 200 with something that is not the contract."""
    refund_fails: int | None = None
    during_search: Callable[[], None] | None = None
    searches: list[dict[str, Any]] = field(default_factory=list)
    refunds: list[str] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/apps/meter/search"):
            assert request.headers["authorization"] == f"Bearer t{self.tokens}"
            if self.down:
                raise httpx.ConnectError("nere", request=request)
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "available": self.connected,
                        "price": 24,
                        "sent_to": "Claudes webbsökning hos Anthropic, utanför EU",
                        "message": None if self.connected else "Webbsökningen är inte inkopplad.",
                    },
                )
            return self._search(json.loads(request.content))
        if path.endswith("/refund"):
            if self.down:
                raise httpx.ConnectError("nere", request=request)
            return self._refund(self.reservations[path.split("/")[-2]])
        return super().handle(request)

    def _search(self, body: dict[str, Any]) -> httpx.Response:
        assert body["hold"] is True
        self.searches.append(body)
        found = self.reservations[body["reservation"]]
        assert found["state"] == "held" and found["amount"] == 24
        if self.during_search is not None:
            self.during_search()
        if not self.connected or self.search_fails is not None:
            found["state"] = "returned"
            self.accounts[found["owner"]] += found["amount"]
            # ID's own words, which Catalog never passes on.
            return httpx.Response(
                self.search_fails or 503,
                json={"code": "unavailable", "message": "hemligt fel från sökningen"},
            )
        found["search"] = True
        if self.garbled:
            return httpx.Response(200, json={"values": "inte en lista", "cost": 24})
        answer = MeterSearchAnswer.model_validate(
            {
                "values": self.values,
                "results": self.results,
                "searches": 2,
                "cost": 24,
                "model": "claude-sonnet-5-5",
                "reservation": self._reservation(found).model_dump(mode="json"),
            }
        )
        return httpx.Response(200, json=answer.model_dump(mode="json"))

    def _refund(self, found: dict[str, Any]) -> httpx.Response:
        if self.refund_fails is not None:
            return httpx.Response(
                self.refund_fails, json={"code": "invalid", "message": "Inte en sökning."}
            )
        assert found.get("search"), "only a search is refunded"
        if found["state"] == "drawn":
            self.accounts[found["owner"]] += found["drawn"]
            found.update(state="returned", drawn=0)
            self.refunds.append(found["id"])
        return self._answer(found)


@dataclass
class Searching(Catalog):
    """The catalog with a meter that searches, the database and Catalog's own searches."""

    id: PretendSearcher
    url: str = ""

    @property
    def searches(self) -> Searches:
        found: Searches = self.world.nobody.app.state.searches  # type: ignore[attr-defined]
        return found


@pytest.fixture(autouse=True)
def a_pretend_museum(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pretend search's sources are made up, so the known publisher among them is a pretend
    museum, on the list for the test: no real publisher is given words it never wrote."""
    monkeypatch.setitem(PUBLISHERS, "museum.example.org", PublisherKind.MUSEUM)


@pytest.fixture
def pretend() -> PretendSearcher:
    return PretendSearcher()


@pytest.fixture
def cat(database_url: str, tmp_path: Path, pretend: PretendSearcher) -> Iterator[Searching]:
    with world_with(database_url, tmp_path, pretend=pretend) as made:
        c = TestClient(made.nobody.app)
        assert c.post(f"{API}/trial/login", json={"account": C}).status_code == 200
        pretend.reviewers.add(C)
        yield Searching(made, pretend, made.a, made.b, c, url=database_url)


def ask(client: TestClient, ident: str | None = None, **change: Any) -> httpx.Response:
    body = {
        "id": ident or str(uuid.uuid4()),
        "litt": "Hbis",
        "operator": "Green Cargo",
        "kind": "freight_wagon",
        "profile": "SE",
        "consent": True,
        **change,
    }
    answered: httpx.Response = client.post(SEARCH, json=body)
    return answered


def found(answered: httpx.Response) -> PrototypeSearch:
    assert answered.status_code == 200, answered.text
    return PrototypeSearch.model_validate(answered.json())


def send_on(client: TestClient, search: PrototypeSearch, **change: Any) -> httpx.Response:
    """Skicka till granskning: the search's fields as a proposal, as the web app sends it."""
    body = proposal(
        **{
            "name": "Hbis",
            "fields": search.fields,
            "source": {"kind": "web_search", "text": "Webbsökning"},
            "search": str(search.id),
            **change,
        }
    )
    answered: httpx.Response = client.post(f"{API}/prototypes/proposals", json=body)
    return answered


def sent(client: TestClient, search: PrototypeSearch, **change: Any) -> PrototypeRevision:
    answered = send_on(client, search, **change)
    assert answered.status_code == 201, answered.text
    return PrototypeRevision.model_validate(answered.json())


def rows(cat: Searching, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(cat.url, autocommit=True) as conn:
        cursor = conn.execute(sql, args)
        return cursor.fetchall() if cursor.description is not None else []


# --- Only the marking is sent (CAT-166) ----------------------------------------------------------


def test_a_search_sends_only_the_marking_to_the_meter(cat: Searching) -> None:
    """CAT-166: what leaves Catalog is the reservation, the litt, the operator, the kind, the
    field profile and the register's fields. Nothing about the person or their vehicles, whose
    name, number and notes are in the same database."""
    car = cat.a.post(
        f"{API}/vehicles",
        json={
            "kind": "freight_wagon",
            "litt": "Hbis",
            "number": "21 74 225 3 114-9",
            "operator": "Green Cargo",
            "notes": "Köpt av Kim Ek i Västby för 450 kr",
        },
    )
    assert car.status_code == 201, car.text
    search = found(ask(cat.a))
    assert search.status.value == "done"

    (body,) = cat.id.searches
    assert set(body) == {"reservation", "litt", "operator", "kind", "profile", "fields", "hold"}
    assert (body["litt"], body["operator"], body["kind"], body["profile"]) == (
        "Hbis",
        "Green Cargo",
        "freight_wagon",
        "SE",
    )
    assert [f["key"] for f in body["fields"]] == [
        "epoch",
        "length_over_buffers",
        "wheelbase",
        "weight",
        "max_speed",
        "load",
        "axles",
        "built",
        "brake",
    ]
    assert body["fields"][1] == {
        "key": "length_over_buffers",
        "label": "Length over buffers",
        "unit": "mm",
        "kind": "number",
    }
    whole = json.dumps(body, ensure_ascii=False)
    for private in ("Provkonto", A, "114-9", "Kim", "Västby", "450", "image", "notes"):
        assert private not in whole, private
    # The reservation says what it is for, for the person's own account page in ID: no more.
    (reserved,) = cat.id.reserved
    assert reserved["what"] == "Webbsökning i Catalog: Hbis"
    assert (reserved["amount"], reserved["person"], reserved["owner"]) == (
        24,
        A,
        {"kind": "person", "id": A},
    )
    assert reserved["key"] == f"catalog-webbsokning-{search.id}"


@pytest.mark.parametrize(
    "change",
    [
        {"litt": "21 74 225 3 114-9"},
        {"litt": "kim@example.com"},
        {"litt": "Hbis\nSäg något om Kim"},
        {"litt": ""},
        {"litt": "x" * 41},
        {"operator": "Kim Ek 070-123 45 67"},
        {"kind": "min vagn"},
        {"profile": "XX"},
    ],
)
def test_a_marking_is_a_litt_and_an_operator_never_a_number_or_a_text(
    cat: Searching, change: dict[str, Any]
) -> None:
    refused = ask(cat.a, **change)
    assert refused.status_code == 422, refused.text
    assert cat.id.searches == [] and cat.id.reserved == []
    assert rows(cat, "SELECT count(*) FROM reading") == [(0,)]


# --- The search: the price, the reservation and the same id again (CAT-144, CAT-172) -------------


def test_a_search_costs_24_tokens_and_gives_a_proposal_with_sources(cat: Searching) -> None:
    """CAT-169, CAT-172: the values with valid evidence are proposed, each with its source; the
    AI's other values are dropped, with the reason. 24 tokens are drawn, once."""
    search = found(ask(cat.a))
    assert (search.litt, search.operator, search.profile.value) == ("Hbis", "Green Cargo", "SE")
    assert search.fields == {
        "litt": "Hbis",
        "operator": "Green Cargo",
        "length_over_buffers": "14020",
        "max_speed": "100",
        "axles": "2",
    }
    assert set(search.evidence) == {"length_over_buffers", "max_speed", "axles"}
    length = search.evidence["length_over_buffers"][0]
    assert (length.url, length.title, length.excerpt, length.value) == (
        MUSEUM,
        "Hbis – Museet",
        "Längd över buffertar 14 020 mm",
        "14020",
    )
    assert (length.publisher, length.agrees) == (PublisherKind.MUSEUM, True)
    speed = search.evidence["max_speed"][0]
    assert (speed.url, speed.publisher) == (WIKI, PublisherKind.UNKNOWN)
    assert {d.key: d.reason for d in search.dropped} == {
        "weight": DroppedReason.INVENTED_SOURCE,
        "built": DroppedReason.UNSUPPORTED,
        "brake": DroppedReason.NO_SOURCE,
    }
    assert (search.cost, search.model, search.sources) == (24, "claude-sonnet-5-5", 2)
    assert (search.revision, search.prototype, search.refunded) == (None, None, False)
    assert cat.id.draws == [(MINE, 24)] and cat.id.accounts[MINE] == 76
    # A reading record of the kind web search (CAT-143): no vehicle, no picture, no prototype.
    assert rows(cat, "SELECT kind, pictures, status, month FROM reading") == [
        ("web_search", 0, "done", rows(cat, "SELECT to_char(now(), 'YYYY-MM')")[0][0])
    ]
    assert rows(cat, "SELECT count(*) FROM prototype") == [(0,)]
    assert rows(cat, "SELECT count(*) FROM vehicle") == [(0,)]
    assert listed(cat.b).prototypes == [], "the search wrote nothing in the catalog"
    # The person's own search again, as when the page is opened later.
    again = cat.a.get(f"{SEARCH}/{search.id}")
    assert found(again) == search
    assert cat.b.get(f"{SEARCH}/{search.id}").status_code == 404, "only one's own"


def test_the_same_id_again_gives_the_same_search_without_searching_or_drawing(
    cat: Searching,
) -> None:
    """CAT-144: a retry with the same id and marking neither searches nor draws again."""
    ident = str(uuid.uuid4())
    first = found(ask(cat.a, ident))
    again = found(ask(cat.a, ident))
    assert again == first
    assert len(cat.id.searches) == 1 and cat.id.draws == [(MINE, 24)]
    # The same id for another marking, or for a photo, is refused.
    other = ask(cat.a, ident, litt="Gbs")
    assert (other.status_code, other.json()["code"]) == (409, "changed")
    photo = send(cat.a, ident=ident)
    assert (photo.status_code, photo.json()["code"]) == (409, "changed")
    assert len(cat.id.searches) == 1 and cat.id.reads == []


def test_when_the_search_fails_the_tokens_go_back_and_the_message_is_catalogs_own(
    cat: Searching,
) -> None:
    cat.id.search_fails = 502
    failed = ask(cat.a)
    assert (failed.status_code, failed.json()["code"]) == (502, "reading_failed")
    assert failed.json()["message"] == (
        "Webbsökningen gav inget svar just nu. Inget drogs. Försök igen."
    )
    assert "hemligt" not in failed.text
    assert cat.id.accounts[MINE] == 100 and cat.id.draws == []
    assert rows(cat, "SELECT status, result FROM reading") == [("failed", None)]


def test_an_answer_that_does_not_follow_the_contract_fails_and_costs_nothing(
    cat: Searching,
) -> None:
    cat.id.garbled = True
    failed = ask(cat.a)
    assert (failed.status_code, failed.json()["code"]) == (503, "unavailable")
    assert cat.id.accounts[MINE] == 100 and cat.id.draws == []
    assert rows(cat, "SELECT status FROM reading") == [("failed",)]


def test_a_search_that_finds_nothing_is_still_a_search(cat: Searching) -> None:
    """Nothing with valid evidence: the proposal is empty but for the marking, and says what was
    dropped. The search was made, and costs its 24 tokens (CAT-172)."""
    cat.id.values = [VALUES[3], VALUES[5]]
    search = found(ask(cat.a))
    assert search.fields == {"litt": "Hbis", "operator": "Green Cargo"}
    assert search.evidence == {} and len(search.dropped) == 2
    assert cat.id.accounts[MINE] == 76


def test_a_short_balance_searches_nothing(cat: Searching) -> None:
    cat.id.accounts[MINE] = 23
    short = ask(cat.a)
    assert (short.status_code, short.json()["code"]) == (402, "no_tokens")
    assert short.json()["message"] == (
        "Saldot räcker inte: webbsökningen kostar 24 tokens och 23 finns kvar. "
        "Köp tokens i TrainMeet ID."
    )
    assert cat.id.searches == [] and cat.id.reserved == []


def test_one_search_or_reading_at_a_time_and_ten_searches_an_hour(cat: Searching) -> None:
    """CAT-146: one at a time per person, a reading of a photo counted too; ten an hour."""
    cat.id.accounts[MINE] = 1000
    during: list[tuple[int, str]] = []

    def meanwhile() -> None:
        for answered in (ask(cat.a), send(cat.a)):
            during.append((answered.status_code, answered.json()["code"]))

    cat.id.during_search = meanwhile
    first = found(ask(cat.a))
    assert during == [(409, "reading_busy"), (409, "reading_busy")]
    cat.id.during_search = None
    for _ in range(9):
        found(ask(cat.a))
    eleventh = ask(cat.a)
    assert (eleventh.status_code, eleventh.json()["code"]) == (429, "too_many")
    assert "Högst 10 webbsökningar i timmen" in eleventh.json()["message"]
    assert int(eleventh.headers["retry-after"]) > 0
    assert len(cat.id.searches) == 10
    # The hour's searches are not the hour's readings: a photo is still read (CAT-146).
    assert read(send(cat.a)).status.value == "done"
    assert found(cat.a.get(f"{SEARCH}/{first.id}")) == first


# --- The consent, and when the search is not connected (CAT-142, CAT-219) ------------------------


def test_the_first_search_needs_the_consent_which_says_what_is_sent_and_to_whom(
    cat: Searching,
) -> None:
    consent = PrototypeSearchConsent.model_validate(cat.a.get(SEARCH).json())
    assert (consent.available, consent.given, consent.price) == (True, False, 24)
    assert (consent.balance, consent.payer, consent.own_ai) == (100, "Provkonto", None)
    assert consent.sent_to == "Claudes webbsökning hos Anthropic, utanför EU"
    assert consent.text.startswith("Bara märkningen skickas: littera, bolag, slag och fältprofil.")
    assert "Inga bilder" in consent.text and "utanför EU" in consent.text
    without = ask(cat.a, consent=False)
    assert (without.status_code, without.json()["code"]) == (422, "consent_required")
    assert cat.id.searches == []
    search = found(ask(cat.a))
    # Kept once as a privacy event of its own, apart from the photos' consent.
    assert rows(cat, "SELECT kind, version FROM privacy_event") == [
        ("web_search_consent", "2026-11-21")
    ]
    after = PrototypeSearchConsent.model_validate(cat.a.get(SEARCH).json())
    assert (after.given, after.balance) == (True, 76)
    assert found(ask(cat.a, consent=False)).status.value == "done", "the yes is remembered"
    assert read(send(cat.a, consent=True)).status.value == "done"
    # A search that is not sent yet is listed, so that it is never lost.
    assert [(u.id, u.litt, u.fields) for u in after.unsent] == [(search.id, "Hbis", 3)]


def test_with_own_ai_the_search_still_goes_to_trainmeets_and_costs_24(cat: Searching) -> None:
    """TK4, C40: an account's own AI has no web search. The consent says so, and the price is
    the same."""
    cat.id.own_ai[MINE] = "egen-modell"
    consent = PrototypeSearchConsent.model_validate(cat.a.get(SEARCH).json())
    assert (consent.available, consent.price, consent.own_ai) == (True, 24, "egen-modell")
    assert found(ask(cat.a)).cost == 24
    assert cat.id.reserved[0]["amount"] == 24 and cat.id.accounts[MINE] == 76


def test_without_the_key_the_search_is_not_connected_and_says_so(cat: Searching) -> None:
    """CAT-219: the meter has no key for the web search. Catalog says that it is not connected,
    before anyone tries and when someone does, and nothing is drawn."""
    cat.id.connected = False
    consent = PrototypeSearchConsent.model_validate(cat.a.get(SEARCH).json())
    assert (consent.available, consent.message) == (
        False,
        "Webbsökningen är inte inkopplad här. Föreslå förebilden för hand.",
    )
    off = ask(cat.a)
    assert (off.status_code, off.json()["code"]) == (503, "search_off")
    assert off.json()["message"] == (
        "Webbsökningen är inte inkopplad här. Föreslå förebilden för hand."
    )
    assert cat.id.accounts[MINE] == 100 and cat.id.draws == []
    # The prototype is proposed by hand, as before.
    assert proposed(cat.a).status.value == "proposed"


def test_without_id_there_is_no_search(database_url: str, tmp_path: Path) -> None:
    settings = Settings(
        database_url=database_url,
        migrate="auto",
        trial_login=True,
        web_dir=tmp_path / "web",
        build=CatalogVersion(version="0.1.0"),
        pictures_dir=tmp_path / "bilder",
    )
    with TestClient(create_app(settings)) as client:
        assert client.post(f"{API}/trial/login", json={"account": A}).status_code == 200
        consent = PrototypeSearchConsent.model_validate(client.get(SEARCH).json())
        assert (consent.available, consent.message) == (
            False,
            "Webbsökningen kräver TrainMeet ID.",
        )
        refused = ask(client)
        assert (refused.status_code, refused.json()["code"]) == (503, "unavailable")
        assert client.post(f"{API}/prototypes/proposals", json=proposal()).status_code == 201


def test_the_search_is_for_those_who_are_logged_in(cat: Searching) -> None:
    nobody = cat.world.nobody
    assert nobody.get(SEARCH).status_code == 401
    assert ask(nobody).status_code == 401
    assert cat.id.searches == []


# --- The result becomes a proposal in the review queue (CAT-171) ---------------------------------


def test_a_search_is_sent_to_the_review_queue_with_its_evidence_per_field(cat: Searching) -> None:
    """CAT-171: the search fills the catalog through the review queue, never directly and never
    a vehicle. The reviewer sees each field's value, source, publisher and excerpt."""
    search = found(ask(cat.a))
    revision = sent(cat.a, search)
    assert (revision.status.value, revision.number, revision.base) == ("proposed", 1, None)
    assert revision.source.kind.value == "web_search"
    # Catalog writes the source's text: when it was searched, and where the sources stand.
    assert re.fullmatch(
        r"Webbsökning \d{4}-\d{2}-\d{2}\. Källorna står per fält\.", revision.source.text
    )
    assert revision.fields == search.fields
    assert revision.evidence == search.evidence

    # Only the proposer and the reviewers see it, until it is reviewed (CAT-164).
    assert listed(cat.b).prototypes == []
    assert cat.b.get(f"{API}/prototypes/{revision.prototype}").status_code == 404
    queued = cat.c.get(f"{API}/prototypes/proposals/queue").json()
    (waiting,) = [PrototypeRevision.model_validate(each) for each in queued]
    assert waiting.id == revision.id and waiting.proposed_by == "Provkonto A"
    shown = {
        key: [(e.value, e.url, e.publisher.value, e.excerpt, e.agrees) for e in items]
        for key, items in waiting.evidence.items()
    }
    assert shown == {
        "length_over_buffers": [
            ("14020", MUSEUM, "museum", "Längd över buffertar 14 020 mm", True)
        ],
        "max_speed": [("100", WIKI, "unknown", "Största tillåtna hastighet 100 km/h", True)],
        "axles": [("2", MUSEUM, "museum", "En tvåaxlig godsvagn", True)],
    }
    # The search knows the proposal it was sent as, and is no longer waiting to be sent.
    again = found(cat.a.get(f"{SEARCH}/{search.id}"))
    assert (again.revision, again.prototype, again.refunded) == (
        revision.id,
        revision.prototype,
        False,
    )
    assert PrototypeSearchConsent.model_validate(cat.a.get(SEARCH).json()).unsent == []
    assert rows(cat, "SELECT count(*) FROM vehicle") == [(0,)]


def test_the_evidence_is_catalogs_own_never_what_a_browser_sends(cat: Searching) -> None:
    """The proposal names the search; its evidence is the stored one. A value the search did not
    find has no evidence, and evidence sent along is not kept."""
    search = found(ask(cat.a))
    forged = {
        "weight": [
            {
                "value": "14.5",
                "url": "https://museum.example.org/datablad",
                "title": "Datablad",
                "publisher": "operator",
                "excerpt": "Egenvikt 14,5 ton",
                "searched_at": "2026-11-21T09:00:00Z",
                "agrees": True,
            }
        ]
    }
    revision = sent(
        cat.a,
        search,
        fields={**search.fields, "weight": "14.5"},
        evidence=forged,
        source={"kind": "web_search", "text": "Källa: ett eget datablad"},
    )
    assert revision.fields["weight"] == "14.5"
    assert set(revision.evidence) == {"length_over_buffers", "max_speed", "axles"}
    assert revision.source.text.startswith("Webbsökning 20")


def test_a_search_is_sent_once_and_only_by_the_one_who_searched(cat: Searching) -> None:
    search = found(ask(cat.a))
    assert send_on(cat.b, search).status_code == 404, "someone else's search"
    sent(cat.a, search)
    twice = send_on(cat.a, search)
    assert (twice.status_code, twice.json()["code"]) == (409, "changed")
    assert twice.json()["message"] == "Sökningen är redan skickad som ett förslag."
    assert rows(cat, "SELECT count(*) FROM prototype_revision") == [(1,)]
    # The source Webbsökning is only for a proposal sent from a search, and a search's proposal
    # has no other source.
    no_search = cat.a.post(
        f"{API}/prototypes/proposals",
        json=proposal(source={"kind": "web_search", "text": "Jag sökte själv"}),
    )
    assert (no_search.status_code, no_search.json()["code"]) == (422, "bad_type_data")
    other = found(ask(cat.a))
    own_source = send_on(cat.a, other, source={"kind": "own", "text": "Egen mätning"})
    assert own_source.status_code == 422
    unknown = cat.a.post(
        f"{API}/prototypes/proposals",
        json=proposal(source={"kind": "web_search", "text": "x"}, search=str(uuid.uuid4())),
    )
    assert unknown.status_code == 404


# --- The tokens come back when the prototype is approved (CAT-172) -------------------------------


def test_the_tokens_come_back_when_the_proposal_is_approved(cat: Searching) -> None:
    search = found(ask(cat.a))
    revision = sent(cat.a, search)
    assert cat.id.accounts[MINE] == 76 and cat.id.refunds == []
    approved = reviewed(cat, revision)
    assert approved.status.value == "reviewed"
    assert cat.id.accounts[MINE] == 100, "the 24 tokens are back"
    assert len(cat.id.refunds) == 1
    after = found(cat.a.get(f"{SEARCH}/{search.id}"))
    assert (after.refunded, after.prototype) == (True, revision.prototype)
    # Now it is a prototype that everyone sees, with its evidence.
    seen = Prototype.model_validate(cat.b.get(f"{API}/prototypes/{revision.prototype}").json())
    assert seen.status.value == "reviewed" and seen.source.kind.value == "web_search"
    assert seen.evidence["length_over_buffers"][0].url == MUSEUM
    assert listed(cat.b).prototypes[0].evidence["max_speed"][0].publisher is PublisherKind.UNKNOWN
    # Asked once: another approval gives nothing back again.
    change = proposed(
        cat.b,
        prototype=str(revision.prototype),
        base=1,
        fields={**search.fields, "load": "26"},
    )
    reviewed(cat, change)
    assert len(cat.id.refunds) == 1 and cat.id.accounts[MINE] == 100


def test_the_tokens_do_not_come_back_when_the_proposal_is_rejected(cat: Searching) -> None:
    search = found(ask(cat.a))
    revision = sent(cat.a, search)
    rejected = reviewed(cat, revision, "reject", "Källorna räcker inte.")
    assert rejected.status.value == "rejected"
    assert cat.id.refunds == [] and cat.id.accounts[MINE] == 76
    assert found(cat.a.get(f"{SEARCH}/{search.id}")).refunded is False
    # Nor later: a rejected proposal is never one to refund, and a search is sent once.
    assert cat.searches.settle() == 0
    assert cat.id.accounts[MINE] == 76
    assert send_on(cat.a, search).status_code == 409


def test_a_proposal_by_hand_gives_no_tokens_back(cat: Searching) -> None:
    found(ask(cat.a))
    reviewed(cat, proposed(cat.a))
    assert cat.id.refunds == [] and cat.id.accounts[MINE] == 76


def test_when_id_does_not_answer_the_review_stands_and_the_tokens_come_back_later(
    cat: Searching,
) -> None:
    """The review is never held up by the refund: what did not go back is given back later."""
    search = found(ask(cat.a))
    revision = sent(cat.a, search)
    meter: Any = cat.searches.meter
    answers = meter.refund

    def silent(reservation: Any) -> bool | None:
        raise unavailable()

    meter.refund = silent
    assert reviewed(cat, revision).status.value == "reviewed"
    assert cat.id.accounts[MINE] == 76 and cat.id.refunds == []
    assert found(cat.a.get(f"{SEARCH}/{search.id}")).refunded is False
    meter.refund = answers
    assert cat.searches.settle() == 1
    assert cat.id.accounts[MINE] == 100
    assert found(cat.a.get(f"{SEARCH}/{search.id}")).refunded is True
    assert cat.searches.settle() == 0, "once"


def test_a_reservation_id_will_not_refund_is_not_asked_about_again(cat: Searching) -> None:
    search = found(ask(cat.a))
    revision = sent(cat.a, search)
    cat.id.refund_fails = 422
    assert reviewed(cat, revision).status.value == "reviewed"
    cat.id.refund_fails = None
    assert cat.searches.settle() == 0
    assert cat.id.accounts[MINE] == 76
    assert found(cat.a.get(f"{SEARCH}/{search.id}")).refunded is False


# --- Does the evidence still agree with the value (CAT-170)? -------------------------------------


def test_a_value_changed_before_it_is_sent_no_longer_agrees_with_its_evidence(
    cat: Searching,
) -> None:
    """Ändra först: the proposer changes a value the search found. The evidence follows the
    field, and the reviewer sees that it no longer holds the value that stands there."""
    search = found(ask(cat.a))
    revision = sent(cat.a, search, fields={**search.fields, "max_speed": "120"})
    assert revision.fields["max_speed"] == "120"
    (speed,) = revision.evidence["max_speed"]
    assert (speed.value, speed.excerpt, speed.agrees) == (
        "100",
        "Största tillåtna hastighet 100 km/h",
        False,
    )
    assert revision.evidence["axles"][0].agrees is True
    (waiting,) = cat.c.get(f"{API}/prototypes/proposals/queue").json()
    assert waiting["evidence"]["max_speed"][0]["agrees"] is False


def test_a_later_change_keeps_the_evidence_and_shows_where_it_no_longer_agrees(
    cat: Searching,
) -> None:
    """CAT-170: a prototype from a search is changed later, by hand. The evidence of the fields
    that are kept follows the new revision; where the value was changed it no longer agrees,
    in the review and in the catalog. A field that is emptied loses its evidence."""
    search = found(ask(cat.a))
    first = reviewed(cat, sent(cat.a, search))
    fields = {k: v for k, v in search.fields.items() if k != "axles"}
    change = proposed(
        cat.b,
        prototype=str(first.prototype),
        base=1,
        fields={**fields, "length_over_buffers": "14 520", "max_speed": "100"},
    )
    assert change.source.kind.value == "own", "the change itself is the proposer's own"
    assert set(change.evidence) == {"length_over_buffers", "max_speed"}
    assert change.evidence["length_over_buffers"][0].agrees is False
    assert change.evidence["max_speed"][0].agrees is True
    reviewed(cat, change)
    page = Prototype.model_validate(cat.a.get(f"{API}/prototypes/{first.prototype}").json())
    assert page.revision == 2 and page.fields["length_over_buffers"] == "14520"
    (length,) = page.evidence["length_over_buffers"]
    assert (length.value, length.agrees, length.url) == ("14020", False, MUSEUM)
    assert page.evidence["max_speed"][0].agrees is True
    assert "axles" not in page.evidence
    # The first revision still shows its own values with evidence that agrees.
    old = next(r for r in page.revisions if r.number == 1)
    assert all(e.agrees for items in old.evidence.values() for e in items)
    # The value put back as the source has it agrees again.
    back = proposed(
        cat.a,
        prototype=str(first.prototype),
        base=2,
        fields={**fields, "max_speed": "100.0", "length_over_buffers": "14020"},
    )
    assert back.evidence["length_over_buffers"][0].agrees is True


def test_a_prototype_proposed_by_hand_has_no_evidence(cat: Searching) -> None:
    by_hand = proposed(cat.a)
    assert by_hand.evidence == {}
    reviewed(cat, by_hand)
    assert listed(cat.a).prototypes[0].evidence == {}
