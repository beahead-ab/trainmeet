"""TrainMeet tokens i ID (#79): saldot, gratiskvoten och reservationerna.

TOKEN-01, TOKEN-08, TOKEN-12, TOKEN-14, TOKEN-24 and TOKEN-28, against a fresh PostgreSQL per
test, as the rest of ID's tests (id/tests/test_api.py).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest

from contracts.tokens import (
    TokenBalance,
    TokenDraw,
    TokenOwner,
    TokenOwnerKind,
    TokenReservation,
    TokenReserve,
)
from id.db import Database
from id.roles import Refused
from id.tests.test_api import API, World, club_with, log_in
from id.tokens import Tokens


def app_post(world: World, path: str, body: Any, app: str = "hub") -> httpx.Response:
    headers = {"Authorization": f"Bearer {world.keycloak.app_token(app)}"}
    answer: httpx.Response = world.browser().post(
        f"{API}/apps/tokens/{path}", json=body, headers=headers
    )
    return answer


def reserve(
    world: World, person: str, owner: str, amount: int, key: str, app: str = "hub"
) -> httpx.Response:
    kind, _, ident = owner.partition(":")
    body = {
        "person": person,
        "owner": {"kind": kind, "id": ident},
        "amount": amount,
        "key": key,
        "what": f"{amount // 12} sidor i importen",
    }
    return app_post(world, "reservations", body, app)


def test_a_person_and_a_club_have_their_own_balance_with_the_free_quota(world: World) -> None:
    """TOKEN-01, TOKEN-12, TOKEN-14: 100 tokens a month for a person, 300 for a club."""
    kim, _club, people = club_with(world, ("Sara Holm", "sara@example.com"))
    seen = [TokenBalance.model_validate(b) for b in kim.client.get(f"{API}/tokens").json()]
    assert [(b.owner.kind, b.title, b.available, b.free_monthly) for b in seen] == [
        (TokenOwnerKind.PERSON, "Kim Ek", 100, 100),
        (TokenOwnerKind.CLUB, "Västby MJK", 300, 300),
    ]
    sara = people["Sara Holm"]
    assert [b["title"] for b in sara.client.get(f"{API}/tokens").json()] == [
        "Sara Holm",
        "Västby MJK",
    ]
    olle = log_in(world, "Olle Berg", "olle@example.com")
    assert [b["title"] for b in olle.client.get(f"{API}/tokens").json()] == ["Olle Berg"]
    assert world.browser().get(f"{API}/tokens").status_code == 401


def test_an_app_reserves_draws_what_it_cost_and_the_rest_goes_back(world: World) -> None:
    """TOKEN-08, TOKEN-24: reserve before the work, draw what it cost, the rest goes back."""
    kim, club, _ = club_with(world)
    held = reserve(world, kim.id, f"club:{club}", 36, "import-1")
    assert held.status_code == 201, held.text
    reservation = TokenReservation.model_validate(held.json())
    assert (reservation.state, reservation.balance.available) == ("held", 264)
    assert reservation.balance.reserved == 36

    # Two of the three pages were read: 24 tokens, and 12 go back.
    drawn = app_post(world, f"reservations/{reservation.id}/draw", {"amount": 24})
    assert drawn.status_code == 200, drawn.text
    done = TokenReservation.model_validate(drawn.json())
    assert (done.state, done.drawn, done.balance.available, done.balance.reserved) == (
        "drawn",
        24,
        276,
        0,
    )
    # Asking again gives the same answer and draws nothing more (TOKEN-28).
    again = app_post(world, f"reservations/{reservation.id}/draw", {"amount": 24})
    assert TokenReservation.model_validate(again.json()).balance.available == 276
    assert app_post(world, f"reservations/{reservation.id}/draw", {"amount": 36}).status_code == 409
    assert app_post(world, f"reservations/{reservation.id}/return", None).status_code == 409

    # The work failed: everything goes back.
    failed = TokenReservation.model_validate(
        reserve(world, kim.id, f"club:{club}", 12, "k2").json()
    )
    back = app_post(world, f"reservations/{failed.id}/return", None)
    assert TokenReservation.model_validate(back.json()).balance.available == 276
    assert app_post(world, f"reservations/{failed.id}/draw", {}).status_code == 409


def test_the_same_key_gives_the_same_reservation(world: World) -> None:
    """TOKEN-28: an app that asks again after a lost answer is not charged twice."""
    kim = log_in(world, "Kim Ek", "kim@example.com")
    kim.id = kim.client.get(f"{API}/session").json()["account"]["id"]
    first = reserve(world, kim.id, f"person:{kim.id}", 12, "sida-7")
    second = reserve(world, kim.id, f"person:{kim.id}", 12, "sida-7")
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["balance"]["available"] == 88
    assert reserve(world, kim.id, f"person:{kim.id}", 24, "sida-7").status_code == 409
    # Another app's key is its own.
    other = reserve(world, kim.id, f"person:{kim.id}", 12, "sida-7", app="catalog")
    assert other.status_code == 201 and other.json()["id"] != first.json()["id"]
    # And another app does not reach the first app's reservation.
    reservation = first.json()["id"]
    assert app_post(world, f"reservations/{reservation}/draw", {}, app="catalog").status_code == 404


def test_without_enough_tokens_the_work_does_not_start(world: World) -> None:
    """TOKEN-04: when the balance is out, buy more or use one's own AI."""
    kim = log_in(world, "Kim Ek", "kim@example.com")
    kim.id = kim.client.get(f"{API}/session").json()["account"]["id"]
    refused = reserve(world, kim.id, f"person:{kim.id}", 108, "stor")
    assert refused.status_code == 402
    assert refused.json() == {
        "code": "no_tokens",
        "message": "Saldot räcker inte: 100 tokens kvar, 108 behövs. "
        "Köp fler eller använd egen AI.",
    }
    assert reserve(world, kim.id, f"person:{kim.id}", 96, "nastan").status_code == 201
    assert reserve(world, kim.id, f"person:{kim.id}", 12, "en-till").status_code == 402


def test_only_the_owner_and_the_clubs_members_use_a_balance(world: World) -> None:
    kim, club, people = club_with(world, ("Sara Holm", "sara@example.com"))
    sara = people["Sara Holm"]
    olle = log_in(world, "Olle Berg", "olle@example.com")
    olle.id = olle.client.get(f"{API}/session").json()["account"]["id"]
    assert reserve(world, sara.id, f"club:{club}", 12, "s1").status_code == 201
    assert reserve(world, olle.id, f"club:{club}", 12, "o1").status_code == 403
    assert reserve(world, sara.id, f"person:{kim.id}", 12, "s2").status_code == 403
    headers = {"Authorization": f"Bearer {world.keycloak.app_token('hub')}"}
    seen = world.browser().get(
        f"{API}/apps/tokens", params={"person": sara.id, "owner": f"club:{club}"}, headers=headers
    )
    assert seen.status_code == 200 and seen.json()["available"] == 288
    bad = world.browser().get(
        f"{API}/apps/tokens", params={"person": sara.id, "owner": "klubb:x"}, headers=headers
    )
    assert bad.status_code == 422
    nobody = world.browser().get(
        f"{API}/apps/tokens", params={"person": sara.id, "owner": f"club:{club}"}
    )
    assert nobody.status_code == 401


@pytest.fixture
def at(world: World) -> Iterator[tuple[Tokens, list[datetime]]]:
    """The tokens with a clock the test moves."""
    now = [datetime(2026, 11, 30, 22, 50, tzinfo=UTC)]
    db = Database(world.url)
    db.open()
    try:
        yield Tokens(db, clock=lambda: now[0]), now
    finally:
        db.close()


def test_the_free_quota_is_used_first_and_a_new_month_gives_a_new_one(
    world: World, at: tuple[Tokens, list[datetime]]
) -> None:
    """TK2, TOKEN-12: last month's free quota is not saved; bought tokens stay."""
    tokens, now = at
    kim = log_in(world, "Kim Ek", "kim@example.com")
    person = UUID(kim.client.get(f"{API}/session").json()["account"]["id"])
    mine = TokenOwner(kind=TokenOwnerKind.PERSON, id=person)
    with tokens.db.transaction() as conn:
        conn.execute(
            "INSERT INTO token_account (id, person_id, bought) VALUES (%s, %s, 500)",
            (person, person),
        )

    def ask(amount: int, key: str) -> TokenReservation:
        what = "sidor"
        return tokens.reserve(
            "hub", TokenReserve(person=person, owner=mine, amount=amount, key=key, what=what)
        )

    # 30 November, 23:50 in Sweden: the free quota first, then the bought ones.
    first = ask(120, "nov")
    assert (first.balance.free_left, first.balance.bought, first.balance.month) == (
        0,
        480,
        "2026-11",
    )
    # A quarter of an hour later it is December in Sweden: a new free quota.
    now[0] += timedelta(minutes=15)
    december = tokens.balance(person, mine)
    assert (december.month, december.free_left, december.bought) == ("2026-12", 100, 480)
    # November's free part does not come back in December; the bought part does.
    back = tokens.give_back("hub", first.id)
    assert (back.balance.free_left, back.balance.bought) == (100, 500)


def test_a_reservation_nobody_draws_goes_back_by_itself(
    world: World, at: tuple[Tokens, list[datetime]]
) -> None:
    tokens, now = at
    now[0] = datetime(2026, 11, 18, 3, 0, tzinfo=UTC)
    kim = log_in(world, "Kim Ek", "kim@example.com")
    person = UUID(kim.client.get(f"{API}/session").json()["account"]["id"])
    mine = TokenOwner(kind=TokenOwnerKind.PERSON, id=person)
    held = tokens.reserve(
        "hub", TokenReserve(person=person, owner=mine, amount=60, key="glomd", what="sidor")
    )
    assert held.balance.available == 40
    now[0] += timedelta(minutes=31)
    assert tokens.balance(person, mine).available == 100
    with pytest.raises(Refused) as late:
        tokens.draw("hub", held.id, TokenDraw())
    assert late.value.status == 409
