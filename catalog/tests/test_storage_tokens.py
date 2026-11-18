"""Paid storage over the free level (CAT-132, TOKEN-16, TOKEN-29, CAT-131, TOKEN-17).

Over the free level every started GB costs 20 tokens a month from the owner's balance in
TrainMeet ID. A pretend ID keeps the balances and answers the reservations as ID does: held,
then drawn, the same key giving the same reservation (TOKEN-28), 402 when the balance is short
and 429 over the day's cap. The free level and the GB are tiny here, a picture or two, so the
tests stay fast; the month comes from a clock the tests move.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from catalog.app import create_app
from catalog.backgrounds import NoSegmenter, Segmenter
from catalog.fleet import Refused
from catalog.pictures import DiskStore, PictureLimits, Pictures, prepare
from catalog.settings import Settings
from catalog.storage import PRICE_PER_GB, IdPayer, NotPaid
from catalog.tests.test_pictures import (
    API,
    PretendIdWithClubs,
    World,
    _in,
    added,
    photo,
    problem,
    upload,
    world_with,
)
from catalog.tests.test_sharing import CLUB, HBIS, A, B
from contracts.catalog import (
    CatalogVersion,
    Picture,
    PictureBackground,
    ProblemCode,
    StorageUse,
)
from contracts.tokens import (
    TokenBalance,
    TokenOwner,
    TokenOwnerKind,
    TokenReservation,
    TokenReservationState,
)

NOVEMBER = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
SIZE = prepare(photo()).size
"""What one test picture takes of the storage: the display picture and the thumbnail."""


@dataclass
class PretendTokens(PretendIdWithClubs):
    """ID's tokens for the storage: a balance per account, person:<id> or club:<id>."""

    accounts: dict[str, int] = field(default_factory=dict)
    cap: int | None = None
    """The day's cap per account (TK15), when there is one."""
    reservations: dict[str, dict[str, Any]] = field(default_factory=dict)
    keys: dict[str, str] = field(default_factory=dict)
    draws: list[tuple[str, str, int]] = field(default_factory=list)
    """What was drawn: the account, the key and the amount."""
    failing_draws: int = 0
    """How many draws to come do not get through, as when ID does not answer."""
    guard: threading.Lock = field(default_factory=threading.Lock)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if "/apps/tokens/reservations" not in request.url.path:
            return super().handle(request)
        if self.down:
            raise httpx.ConnectError("nere", request=request)
        assert request.headers["authorization"] == f"Bearer t{self.tokens}"
        body = json.loads(request.content)
        with self.guard:
            if request.url.path.endswith("/reservations"):
                return self._reserve(body)
            assert request.url.path.endswith("/draw") and body == {}
            return self._draw(request.url.path.split("/")[-2])

    def _reserve(self, body: dict[str, Any]) -> httpx.Response:
        assert body["person"] is None, "the owner pays, not the one who uploads"
        owner = f"{body['owner']['kind']}:{body['owner']['id']}"
        amount, key = body["amount"], body["key"]
        assert len(body["what"]) <= 120
        if key in self.keys:
            same = self.reservations[self.keys[key]]
            assert (same["owner"], same["amount"]) == (owner, amount)
            return self._answer(same, 200)
        if owner not in self.accounts:
            return httpx.Response(404, json={"code": "not_found", "message": "Finns inte."})
        today = sum(r["amount"] for r in self.reservations.values() if r["owner"] == owner)
        if self.cap is not None and today + amount > self.cap:
            return httpx.Response(429, json={"code": "too_many", "message": "Taket är nått."})
        if self.accounts[owner] < amount:
            return httpx.Response(402, json={"code": "no_tokens", "message": "Saldot räcker inte."})
        self.accounts[owner] -= amount
        made = {"id": str(uuid.uuid4()), "owner": owner, "amount": amount, "key": key}
        made.update(state="held", drawn=0, what=body["what"])
        self.reservations[made["id"]] = made
        self.keys[key] = made["id"]
        return self._answer(made, 201)

    def _draw(self, ident: str) -> httpx.Response:
        found = self.reservations.get(ident)
        if found is None:
            return httpx.Response(404, json={"code": "not_found", "message": "Finns inte."})
        if self.failing_draws:
            self.failing_draws -= 1
            return httpx.Response(503, json={"code": "unavailable", "message": "Nere."})
        if found["state"] == "returned":
            return httpx.Response(409, json={"code": "conflict", "message": "Tillbaka."})
        if found["state"] == "held":
            found.update(state="drawn", drawn=found["amount"])
            self.draws.append((found["owner"], found["key"], found["amount"]))
        return self._answer(found, 200)

    def expire(self, key: str) -> None:
        """The reservation for the key goes back by itself, undrawn, as after half an hour."""
        with self.guard:
            found = self.reservations[self.keys[key]]
            assert found["state"] == "held"
            found["state"] = "returned"
            self.accounts[found["owner"]] += found["amount"]

    def _answer(self, found: dict[str, Any], status: int) -> httpx.Response:
        kind, _, ident = found["owner"].partition(":")
        owner = TokenOwner(kind=TokenOwnerKind(kind), id=UUID(ident))
        left = self.accounts[found["owner"]]
        reservation = TokenReservation(
            id=found["id"],
            owner=owner,
            amount=found["amount"],
            drawn=found["drawn"],
            state=TokenReservationState(found["state"]),
            what=found["what"],
            at=NOVEMBER,
            expires=NOVEMBER + timedelta(minutes=30),
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
        return httpx.Response(status, json=reservation.model_dump(mode="json"))

    def drawn(self, owner: str) -> int:
        return sum(amount for who, _, amount in self.draws if who == owner)


@dataclass
class Paid:
    """Catalog with a pretend ID that takes tokens for the storage, and the month's clock."""

    world: World
    id: PretendTokens
    now: list[datetime]

    @property
    def pictures(self) -> Pictures:
        return self.world.pictures

    def storage(self, client: TestClient | None = None, fleet: str | None = None) -> StorageUse:
        answer = (client or self.world.a).get(_in(f"{API}/storage", fleet))
        assert answer.status_code == 200, answer.text
        return StorageUse.model_validate(answer.json())


@contextmanager
def paid_world(
    database_url: str,
    tmp_path: Path,
    limits: PictureLimits,
    accounts: dict[str, int],
    segmenter: Segmenter | None = None,
) -> Iterator[Paid]:
    pretend = PretendTokens(accounts=dict(accounts))
    with world_with(database_url, tmp_path, limits, segmenter, pretend=pretend) as world:
        now = [NOVEMBER]
        world.pictures.clock = lambda: now[0]
        yield Paid(world, pretend, now)


def key(owner: str, month: str, block: int) -> str:
    return f"catalog-lagring-{owner}-{month}-{block}"


def charges(database_url: str) -> list[tuple[str, str, int, bool, bool]]:
    """What is paid per owner and month, and whether the month is unpaid."""
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            "SELECT owner_id, month, blocks, club, unpaid FROM storage_charge "
            "ORDER BY month, owner_id"
        ).fetchall()
    return [(str(row[0]), row[1], row[2], row[3], row[4]) for row in rows]


def counted(database_url: str) -> tuple[int, int]:
    """The pictures saved, and the files waiting to be deleted."""
    with psycopg.connect(database_url) as conn:
        pictures = conn.execute("SELECT count(*) FROM picture").fetchone()
        trash = conn.execute("SELECT count(*) FROM picture_trash").fetchone()
    assert pictures is not None and trash is not None
    return int(pictures[0]), int(trash[0])


MINE = f"person:{A}"


# --- What is paid (CAT-132, TOKEN-16) ----------------------------------------------------------


def test_under_the_free_level_nothing_is_charged(database_url: str, tmp_path: Path) -> None:
    limits = PictureLimits(person=SIZE * 2, block=SIZE)
    with paid_world(database_url, tmp_path, limits, {MINE: 100}) as paid:
        car = paid.world.vehicle()
        for _ in range(2):
            added(upload(paid.world, car, photo()))
        assert paid.id.reservations == {}
        use = paid.storage()
        assert (use.used, use.over_free, use.paid_blocks, use.unpaid) == (SIZE * 2, False, 0, False)
        assert use.price_per_gb == PRICE_PER_GB == 20
        assert paid.pictures.charge_round() == 0
        assert charges(database_url) == []


def test_each_started_gb_over_the_free_level_is_drawn_once_a_month(
    database_url: str, tmp_path: Path
) -> None:
    """CAT-132, TK10: 20 tokens per started GB and month, from the owner's balance. Here a GB
    is two pictures and the free level one."""
    limits = PictureLimits(person=SIZE, block=SIZE * 2)
    with paid_world(database_url, tmp_path, limits, {MINE: 100}) as paid:
        car = paid.world.vehicle()
        first = added(upload(paid.world, car, photo()))
        assert paid.id.draws == []
        # Into the first GB over the free level: 20 tokens, once.
        second = added(upload(paid.world, car, photo()))
        assert paid.id.draws == [(MINE, key(A, "2026-11", 1), 20)]
        # The same GB holds another picture: nothing more is drawn.
        added(upload(paid.world, car, photo()))
        assert len(paid.id.draws) == 1
        # The next GB: 20 more.
        added(upload(paid.world, car, photo()))
        assert paid.id.draws[1:] == [(MINE, key(A, "2026-11", 2), 20)]
        assert paid.id.accounts[MINE] == 60
        use = paid.storage()
        assert (use.used, use.over_free, use.paid_blocks, use.unpaid) == (SIZE * 4, True, 2, False)

        # Removed and put back the same month: the GB stay paid, and nothing more is drawn.
        for picture in (first, second):
            removed = paid.world.a.delete(f"{API}/vehicles/{car}/pictures/{picture.id}")
            assert removed.status_code == 200
        assert paid.storage().paid_blocks == 2
        for _ in range(2):
            added(upload(paid.world, car, photo()))
        assert len(paid.id.draws) == 2
        assert charges(database_url) == [(A, "2026-11", 2, False, False)]
        assert paid.pictures.charge_round() == 0


def test_a_short_balance_refuses_and_stores_nothing(database_url: str, tmp_path: Path) -> None:
    """CAT-132: 402 from ID; and the day's cap (TK15), and ID that does not answer."""
    limits = PictureLimits(person=SIZE, block=SIZE * 10)
    with paid_world(database_url, tmp_path, limits, {MINE: 19}) as paid:
        car = paid.world.vehicle()
        added(upload(paid.world, car, photo()))
        before = paid.world.stored()

        refused = upload(paid.world, car, photo())
        assert problem(refused) == (402, "no_tokens")
        message = refused.json()["message"]
        assert message.startswith("Den fria lagringen på ")
        assert message.endswith(
            "är full, och saldot räcker inte till mer: 20 tokens per påbörjad GB och månad. "
            "Köp tokens i TrainMeet ID, eller ta bort bilder."
        )
        assert paid.world.stored() == before
        assert counted(database_url) == (1, 0)
        use = paid.storage()
        assert (use.used, use.over_free, use.paid_blocks, use.unpaid) == (SIZE, False, 0, False)

        # The day's cap in ID is reached (TK15).
        paid.id.accounts[MINE], paid.id.cap = 100, 10
        capped = upload(paid.world, car, photo())
        assert problem(capped) == (429, "too_many")
        assert capped.json()["message"].startswith("Taket för tokens per dygn är nått")
        # ID does not answer.
        paid.id.cap, paid.id.down = None, True
        assert problem(upload(paid.world, car, photo())) == (503, "unavailable")
        paid.id.down = False
        assert paid.world.stored() == before
        assert counted(database_url) == (1, 0)
        assert paid.id.draws == []

        added(upload(paid.world, car, photo()))
        assert paid.id.draws == [(MINE, key(A, "2026-11", 1), 20)]


@pytest.mark.parametrize("balance", [40, 20])
def test_two_uploads_at_a_gb_edge_are_never_both_unpaid_and_never_pay_twice(
    database_url: str, tmp_path: Path, balance: int
) -> None:
    """CAT-131, CAT-132: two uploads into the same new GB pay it once, with the same key; the
    one that is saved second finds that the first took the room, and pays the next GB under
    its own key, or is refused when the balance is short. Both files are stored before either
    is saved."""
    limits = PictureLimits(person=SIZE, block=SIZE)
    with paid_world(database_url, tmp_path, limits, {MINE: balance}) as paid:
        car = UUID(paid.world.vehicle())
        added(upload(paid.world, str(car), photo()))
        inner = paid.pictures.store
        assert isinstance(inner, DiskStore)
        meet = threading.Barrier(2, timeout=10)

        class Together:
            """Each file waits for the other upload's, so both pay before either is saved."""

            def put(self, key: str, content: bytes, content_type: str = "image/jpeg") -> None:
                inner.put(key, content, content_type)
                meet.wait()

            def get(self, key: str) -> bytes:
                return inner.get(key)

            def size(self, key: str) -> int:
                return inner.size(key)

            def delete(self, key: str) -> None:
                inner.delete(key)

            def url(self, key: str, now: float | None = None) -> str:
                return inner.url(key, now)

        pictures = Pictures(
            paid.pictures.db,
            Together(),
            limits,
            payer=paid.pictures.payer,
            clock=paid.pictures.clock,
        )
        data = photo()
        results: list[Picture | Refused] = []

        def add() -> None:
            try:
                results.append(
                    pictures.add(
                        UUID(A), car, data, keep_original=False, uploaded_by=UUID(A), club=False
                    )
                )
            except Refused as refused:
                results.append(refused)

        threads = [threading.Thread(target=add) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        saved, trash = counted(database_url)
        needed = saved - 1  # a GB per picture over the free level of one
        assert paid.id.draws == [(MINE, key(A, "2026-11", n), 20) for n in range(1, needed + 1)]
        assert charges(database_url)[0][2] == needed
        assert paid.id.accounts[MINE] == balance - 20 * needed
        assert trash == 0
        winners = [r for r in results if isinstance(r, Picture)]
        losers = [r for r in results if isinstance(r, Refused)]
        if balance == 40:
            assert (len(winners), saved) == (2, 3)
        else:
            assert (len(winners), saved) == (1, 2)
            assert losers[0].code is ProblemCode.NO_TOKENS
        assert len(paid.world.stored()) == 2 * saved  # the display picture and the thumbnail


# --- A new month (CAT-132, TK2) ----------------------------------------------------------------


def test_a_new_month_charges_again(database_url: str, tmp_path: Path) -> None:
    """The month is Swedish time, as in ID. An owner still over the free level is charged the
    first time it is needed: at the daily round, or at the next upload."""
    limits = PictureLimits(person=SIZE, block=SIZE * 10)
    with paid_world(database_url, tmp_path, limits, {MINE: 100}) as paid:
        paid.now[0] = datetime(2026, 11, 30, 22, 50, tzinfo=UTC)  # 23.50 in Sweden
        car = paid.world.vehicle()
        for _ in range(2):
            added(upload(paid.world, car, photo()))
        assert paid.id.draws == [(MINE, key(A, "2026-11", 1), 20)]

        paid.now[0] += timedelta(minutes=15)  # December in Sweden, still November in UTC
        use = paid.storage()
        assert (use.over_free, use.paid_blocks, use.unpaid) == (True, 0, False)
        assert paid.pictures.charge_round() == 1
        assert paid.id.draws[-1] == (MINE, key(A, "2026-12", 1), 20)
        assert paid.pictures.charge_round() == 0  # once a month
        added(upload(paid.world, car, photo()))  # within the paid GB
        assert len(paid.id.draws) == 2
        assert paid.storage().paid_blocks == 1

        # January: the first upload pays the month, before the round does.
        paid.now[0] = datetime(2027, 1, 2, 12, 0, tzinfo=UTC)
        added(upload(paid.world, car, photo()))
        assert paid.id.draws[-1] == (MINE, key(A, "2027-01", 1), 20)
        assert paid.pictures.charge_round() == 0
        assert paid.id.accounts[MINE] == 40
        assert [(c[1], c[2], c[4]) for c in charges(database_url)] == [
            ("2026-11", 1, False),
            ("2026-12", 1, False),
            ("2027-01", 1, False),
        ]


def test_an_unpaid_month_refuses_growth_but_allows_removal(
    database_url: str, tmp_path: Path
) -> None:
    """TK15: when the balance is out, the pictures stay, but nothing that grows the storage is
    saved until the month is paid. Removing always works."""
    limits = PictureLimits(person=SIZE, block=SIZE * 10)
    with paid_world(database_url, tmp_path, limits, {MINE: 20}) as paid:
        car = paid.world.vehicle()
        added(upload(paid.world, car, photo()))
        second = added(upload(paid.world, car, photo()))
        assert paid.id.accounts[MINE] == 0

        paid.now[0] = datetime(2026, 12, 1, 6, 0, tzinfo=UTC)
        assert paid.pictures.charge_round() == 0
        use = paid.storage()
        assert (use.over_free, use.paid_blocks, use.unpaid) == (True, 0, True)
        assert (A, "2026-12", 0, False, True) in charges(database_url)
        assert paid.pictures.charge_round() == 0  # asked again, still short: nothing drawn

        assert problem(upload(paid.world, car, photo())) == (402, "no_tokens")
        assert len(paid.world.a.get(f"{API}/vehicles/{car}/pictures").json()) == 2
        removed = paid.world.a.delete(f"{API}/vehicles/{car}/pictures/{second.id}")
        assert removed.status_code == 200
        use = paid.storage()
        assert (use.over_free, use.unpaid) == (False, False)

        # Tokens are bought: the next upload pays the month.
        paid.id.accounts[MINE] = 100
        added(upload(paid.world, car, photo()))
        assert paid.id.draws[-1] == (MINE, key(A, "2026-12", 1), 20)
        use = paid.storage()
        assert (use.over_free, use.paid_blocks, use.unpaid) == (True, 1, False)
        assert (A, "2026-12", 1, False, False) in charges(database_url)


# --- Who pays (CAT-133, TOKEN-29) --------------------------------------------------------------


def test_a_club_fleet_pays_from_the_clubs_account(database_url: str, tmp_path: Path) -> None:
    """TOKEN-29: a fleet a club owns counts against the club's free level, and over it the
    club's balance pays, also for an upload by someone the fleet is shared with to edit. The
    daily round charges the club the same way."""
    limits = PictureLimits(person=SIZE * 5, club=SIZE, block=SIZE * 10)
    accounts = {MINE: 100, f"person:{B}": 100, f"club:{CLUB}": 100}
    with paid_world(database_url, tmp_path, limits, accounts) as paid:
        world = paid.world
        world.id.roles[(B, CLUB)] = "admin"
        world.id.roles[(A, CLUB)] = "editor"
        world.id.clubs.add(CLUB)
        assert world.b.get(f"{API}/fleets").status_code == 200  # the club gets an owner row
        in_club = world.vehicle(world.b, CLUB)
        added(upload(world, in_club, photo(), client=world.b, fleet=CLUB))
        added(upload(world, in_club, photo(), client=world.a, fleet=CLUB))
        assert paid.id.draws == [(f"club:{CLUB}", key(CLUB, "2026-11", 1), 20)]
        assert (paid.id.accounts[MINE], paid.id.accounts[f"person:{B}"]) == (100, 100)
        use = paid.storage(world.a, CLUB)
        assert (use.club, use.over_free, use.paid_blocks, use.unpaid) == (True, True, 1, False)
        assert charges(database_url) == [(CLUB, "2026-11", 1, True, False)]

        paid.now[0] = datetime(2026, 12, 3, 12, 0, tzinfo=UTC)
        assert paid.pictures.charge_round() == 1
        assert paid.id.draws[-1] == (f"club:{CLUB}", key(CLUB, "2026-12", 1), 20)
        assert paid.id.accounts[f"club:{CLUB}"] == 60


def test_an_editors_upload_is_paid_by_the_fleets_owner(database_url: str, tmp_path: Path) -> None:
    """CAT-133: the pictures are stored with the owner, and the owner's balance pays."""
    limits = PictureLimits(person=SIZE, block=SIZE * 10)
    with paid_world(database_url, tmp_path, limits, {MINE: 100, f"person:{B}": 100}) as paid:
        paid.world.id.roles[(B, A)] = "editor"
        car = paid.world.vehicle()
        added(upload(paid.world, car, photo()))
        added(upload(paid.world, car, photo(), client=paid.world.b, fleet=A))
        assert paid.id.draws == [(MINE, key(A, "2026-11", 1), 20)]
        assert paid.id.accounts[f"person:{B}"] == 100
        assert paid.storage(paid.world.b, A).paid_blocks == 1


def test_the_background_removal_is_free_and_only_what_it_keeps_is_paid(
    database_url: str, tmp_path: Path
) -> None:
    """TOKEN-17: the background removal itself draws nothing. A new background that grows the
    storage over the free level pays the GB as any upload; one that shrinks it never does."""
    from catalog.tests.test_backgrounds import PretendSegmenter, change, png, scene, send

    pretend = PretendSegmenter()
    data = png(scene())
    original = prepare(data, segmenter=pretend).size
    white = prepare(data, background=PictureBackground.WHITE, segmenter=pretend).size
    assert white > original
    limits = PictureLimits(person=original, block=SIZE * 100)
    with paid_world(database_url, tmp_path, limits, {MINE: 100}, pretend) as paid:
        car = paid.world.vehicle()
        first = added(send(paid.world, car, data))
        assert pretend.calls > 0 and paid.id.reservations == {}
        changed = change(paid.world, car, first.id, "white")
        assert changed.status_code == 200, changed.text
        assert paid.id.draws == [(MINE, key(A, "2026-11", 1), 20)]
        back = change(paid.world, car, first.id, "original")
        assert back.status_code == 200
        assert len(paid.id.draws) == 1


# --- When ID cannot take the tokens -----------------------------------------------------------


def test_a_gb_whose_reservation_went_back_gets_a_new_key_and_is_paid_once(
    database_url: str, tmp_path: Path
) -> None:
    """TOKEN-28: an answer that was lost is asked again with the same key, and draws the same
    reservation. One that went back by itself before it was drawn gets a key made anew."""
    limits = PictureLimits(person=SIZE, block=SIZE)
    with paid_world(database_url, tmp_path, limits, {MINE: 100}) as paid:
        car = paid.world.vehicle()
        added(upload(paid.world, car, photo()))
        paid.id.failing_draws = 1
        assert problem(upload(paid.world, car, photo())) == (503, "unavailable")
        assert counted(database_url) == (1, 0)
        added(upload(paid.world, car, photo()))  # the held reservation is drawn now
        assert paid.id.draws == [(MINE, key(A, "2026-11", 1), 20)]

        paid.id.failing_draws = 1
        assert problem(upload(paid.world, car, photo())) == (503, "unavailable")
        paid.id.expire(key(A, "2026-11", 2))
        added(upload(paid.world, car, photo()))
        assert paid.id.draws[1:] == [(MINE, key(A, "2026-11", 2) + ".2", 20)]
        assert paid.id.accounts[MINE] == 60
        assert charges(database_url) == [(A, "2026-11", 2, False, False)]


def test_without_id_it_behaves_as_today(database_url: str, tmp_path: Path) -> None:
    """Without ID's API (the trial login, locally) nothing is paid: over the free level Catalog
    says no, as before CAT-132. An owner ID does not know is refused so too (test_pictures)."""
    settings = Settings(
        database_url=database_url,
        migrate="auto",
        trial_login=True,
        web_dir=tmp_path / "web",
        build=CatalogVersion(version="0.1.0"),
        pictures_dir=tmp_path / "bilder",
    )
    limits = PictureLimits(person=SIZE, block=SIZE)
    app = create_app(settings, picture_limits=limits, segmenter=NoSegmenter())
    with TestClient(app) as a:
        assert a.post(f"{API}/trial/login", json={"account": A}).status_code == 200
        car = a.post(f"{API}/vehicles", json=HBIS).json()["id"]
        path = f"{API}/vehicles/{car}/pictures"
        headers = {"Content-Type": "image/jpeg"}
        assert a.post(path, content=photo(), headers=headers).status_code == 201
        full = a.post(path, content=photo(), headers=headers)
        assert problem(full) == (422, "storage_full")
        assert full.json()["message"].startswith("Den fria lagringen på ")
        use = StorageUse.model_validate(a.get(f"{API}/storage").json())
        assert (use.over_free, use.paid_blocks, use.unpaid) == (False, 0, False)
        pictures: Pictures = app.state.pictures
        assert pictures.payer is None and pictures.charge_round() == 0
    assert charges(database_url) == []


def test_the_payer_reserves_without_a_person_for_the_owner() -> None:
    """The reservation names the owner's account and no person (contracts/tokens.py)."""
    from catalog.id_roles import IdRoles
    from catalog.settings import IdSettings

    pretend = PretendTokens(accounts={MINE: 30})
    settings = IdSettings(
        issuer="https://id.example.test/realms/trainmeet",
        client="catalog",
        secret="hemlighet",
        public_url="https://catalog.example.test",
        internal="http://id:8080/realms/trainmeet",
        api="http://id-api:8080",
    )
    payer = IdPayer(IdRoles(settings, httpx.Client(transport=httpx.MockTransport(pretend.handle))))
    mine = TokenOwner(kind=TokenOwnerKind.PERSON, id=UUID(A))
    payer.pay(mine, key(A, "2026-11", 1), 20, "Bildlagring")
    payer.pay(mine, key(A, "2026-11", 1), 20, "Bildlagring")  # asked again: drawn once
    assert pretend.draws == [(MINE, key(A, "2026-11", 1), 20)]
    with pytest.raises(NotPaid) as short:
        payer.pay(mine, key(A, "2026-11", 2), 20, "Bildlagring")
    assert short.value.why == "balance"
    with pytest.raises(NotPaid) as unknown:
        payer.pay(TokenOwner(kind=TokenOwnerKind.CLUB, id=uuid.uuid4()), "k", 20, "Bildlagring")
    assert unknown.value.why == "account"
