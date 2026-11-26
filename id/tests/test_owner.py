"""Ägarsidan (#79, TOKEN-05, TOKEN-18, TK6, TK15): faktorerna, budgeten och taken.

The owners are named by their address in a file, as in ID's vault. A pretend Claude answers the
meter and says how many tokens AWS counted, so the cost is measured as it will be.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts.tokens import OwnerPage
from id.app import create_app
from id.settings import Settings
from id.tests.test_api import (
    INTERNAL,
    ISSUER,
    PUBLIC,
    SECRET,
    Who,
    World,
    apps,
    club_with,
    log_in,
)
from id.tests.test_meter import PretendClaude
from id.tests.test_tokens import reserve

PICTURE = base64.b64encode(b"\x89PNG en sida").decode()


@dataclass
class Owned:
    world: World
    claude: PretendClaude
    app: Any

    def as_(self, who: Who) -> TestClient:
        client = TestClient(self.app, base_url=PUBLIC)
        client.cookies = who.client.cookies
        return client

    def read(self, person: str, owner: str, key: str) -> httpx.Response:
        held = reserve(self.world, person, owner, 12, key)
        assert held.status_code == 201, held.text
        headers = {"Authorization": f"Bearer {self.world.keycloak.app_token('hub')}"}
        body = {
            "reservation": held.json()["id"],
            "prompt": "Skriv av.",
            "images": [{"media_type": "image/png", "data": PICTURE}],
        }
        answer: httpx.Response = TestClient(self.app, base_url=PUBLIC).post(
            "/api/id/1/apps/meter", json=body, headers=headers
        )
        return answer


@pytest.fixture
def owned(world: World, tmp_path: Path) -> Iterator[Owned]:
    owners = tmp_path / "trainmeet_owners"
    owners.write_text("Kim@Example.com\n")
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
    app = create_app(settings, http=http, mailer=world.mail, claude=claude, owners_file=owners)
    with TestClient(app):
        yield Owned(world, claude, app)


SETTINGS = {
    "ai_factor": 2.0,
    "storage_factor": 10.0,
    "monthly_budget_sek": 1000,
    "daily_cap_person": 240,
    "daily_cap_club": 1200,
    "usd_sek": 9.7,
    "price_in_usd": 2.0,
    "price_out_usd": 10.0,
}


def test_only_the_owner_sees_and_changes_the_owner_page(owned: Owned) -> None:
    """TOKEN-05: the factors, the budget and the caps, with Claude's proposals to start with."""
    kim, _club, people = club_with(owned.world, ("Sara Holm", "sara@example.com"))
    me, sara = owned.as_(kim), owned.as_(people["Sara Holm"])
    assert me.get("/api/id/1/session").json()["owner"] is True
    assert sara.get("/api/id/1/session").json()["owner"] is False
    assert sara.get("/api/id/1/owner").status_code == 403
    page = OwnerPage.model_validate(me.get("/api/id/1/owner").json())
    assert page.settings.model_dump() == SETTINGS
    assert (page.page_tokens, page.budget_used, page.cost_per_page_sek) == (12, 0, None)
    assert len(page.months) == 2
    changed = me.put("/api/id/1/owner/settings", json={**SETTINGS, "ai_factor": 3.0})
    assert OwnerPage.model_validate(changed.json()).settings.ai_factor == 3.0
    assert sara.put("/api/id/1/owner/settings", json=SETTINGS).status_code == 403


def test_the_cap_per_day_stops_an_account(owned: Owned) -> None:
    """TK15: a cap per day for an account and a club."""
    kim = log_in(owned.world, "Kim Ek", "kim@example.com")
    kim.id = kim.client.get("/api/id/1/session").json()["account"]["id"]
    owned.as_(kim).put("/api/id/1/owner/settings", json={**SETTINGS, "daily_cap_person": 24})
    mine = f"person:{kim.id}"
    assert reserve(owned.world, kim.id, mine, 12, "dag-1").status_code == 201
    assert reserve(owned.world, kim.id, mine, 12, "dag-2").status_code == 201
    stopped = reserve(owned.world, kim.id, mine, 12, "dag-3")
    assert (stopped.status_code, stopped.json()["message"]) == (
        429,
        "Taket för i dag är nått: 24 tokens per dygn. Försök i morgon, eller använd egen AI.",
    )
    assert reserve(owned.world, kim.id, mine, 0, "dag-4").status_code == 201, "own AI goes on"


def test_the_budget_raises_the_alarm_at_80_and_stops_at_100(owned: Owned) -> None:
    """TK15: the month's budget for TrainMeets AI. A reading costs what AWS counted: 7 000
    tokens in and 3 000 out is 0.044 dollars, 0.43 kr."""
    kim = log_in(owned.world, "Kim Ek", "kim@example.com")
    kim.id = kim.client.get("/api/id/1/session").json()["account"]["id"]
    me = owned.as_(kim)
    me.put("/api/id/1/owner/settings", json={**SETTINGS, "monthly_budget_sek": 1})
    mine = f"person:{kim.id}"
    assert owned.read(kim.id, mine, "b1").status_code == 200
    assert owned.world.mail.help_sent == []
    assert owned.read(kim.id, mine, "b2").status_code == 200
    alarms = [(to, subject) for to, _, subject, _ in owned.world.mail.help_sent]
    assert alarms == [("kim@example.com", "TrainMeets AI har använt 80 % av månadens budget")]
    assert owned.read(kim.id, mine, "b3").status_code == 200
    stopped = owned.read(kim.id, mine, "b4")
    assert stopped.status_code == 503
    assert stopped.json()["message"].startswith("TrainMeets AI har nått månadens budget.")
    assert len(owned.claude.calls) == 3, "not asked after the budget ran out"
    subjects = [subject for _, _, subject, _ in owned.world.mail.help_sent]
    assert subjects[-1] == "TrainMeets AI har stannat: månadens budget är slut"
    assert len(subjects) == 2, "once per level"
    # Nothing was drawn for the reading that was stopped.
    balance = me.get("/api/id/1/tokens").json()[0]
    assert balance["available"] == 100 - 3 * 12

    page = OwnerPage.model_validate(me.get("/api/id/1/owner").json())
    assert page.budget_used == 128
    assert page.months[0].pages == 3 and round(page.months[0].cost_sek, 2) == 1.28
    assert page.cost_per_page_sek is not None and round(page.cost_per_page_sek, 3) == 0.427
    assert page.factor_page_tokens == 11, "0.427 kr × 2 / 7.84 öre"


def test_the_ten_percent_for_only_the_usa_is_counted_in_the_budget(owned: Owned) -> None:
    """ID_METER_GEO=us: Claude only on servers in the USA costs 10 % above the list prices the
    owner's prices build on, so a reading of 7 000 tokens in and 3 000 out counts as 0.47 kr
    in the month's budget, not 0.43."""
    owned.claude.price_factor = 1.1
    kim = log_in(owned.world, "Kim Ek", "kim@example.com")
    kim.id = kim.client.get("/api/id/1/session").json()["account"]["id"]
    me = owned.as_(kim)
    assert owned.read(kim.id, f"person:{kim.id}", "eu1").status_code == 200
    page = OwnerPage.model_validate(me.get("/api/id/1/owner").json())
    assert page.months[0].pages == 1 and round(page.months[0].cost_sek, 2) == 0.47


def test_the_owner_gives_and_takes_the_reviewer_role_in_catalog(owned: Owned) -> None:
    """KONTO-30, ID6, CAT-165: Granskare i Catalog is given and taken on the owner page, to
    someone who has logged in to ID, and Catalog sees it at once through the apps' question."""
    kim, _club, people = club_with(owned.world, ("Sara Holm", "sara@example.com"))
    me, sara = owned.as_(kim), owned.as_(people["Sara Holm"])
    sara_id = people["Sara Holm"].id
    reviewers = "/api/id/1/owner/reviewers"

    def roles() -> list[str]:
        asked = apps(owned.world, "access", person=sara_id, resource="catalog:prototypes")
        assert asked.status_code == 200, asked.text
        found: list[str] = asked.json()["roles"]
        return found

    assert roles() == []
    # Only TrainMeet's owners give it, see it and take it.
    assert sara.get(reviewers).status_code == 403
    assert sara.post(reviewers, json={"email": "sara@example.com"}).status_code == 403
    given = me.post(reviewers, json={"email": "Sara@Example.com"})
    assert given.status_code == 200, given.text
    assert [(g["person"]["name"], g["role"], g["resource"]) for g in given.json()] == [
        ("Sara Holm", "reviewer", {"kind": "catalog", "id": "prototypes"})
    ]
    assert me.post(reviewers, json={"email": "sara@example.com"}).json() == given.json()
    assert me.get(reviewers).json() == given.json()
    assert roles() == ["reviewer"]
    # Nobody who has not logged in to ID, and no address that is not one.
    unknown = me.post(reviewers, json={"email": "okand@example.com"})
    assert (unknown.status_code, unknown.json()["code"]) == (404, "not_found")
    assert me.post(reviewers, json={"email": "inte en adress"}).status_code == 422
    # The role is taken where it was given, never through the sharing's address.
    grant = given.json()[0]["id"]
    assert sara.delete(f"/api/id/1/grants/{grant}").status_code == 403
    assert sara.delete(f"{reviewers}/{sara_id}").status_code == 403
    taken = me.delete(f"{reviewers}/{sara_id}")
    assert (taken.status_code, taken.json()) == (200, [])
    assert roles() == []
    assert me.delete(f"{reviewers}/{sara_id}").status_code == 404
