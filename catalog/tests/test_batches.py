"""Several photos in a batch (#52 del b, CAT-146–CAT-153): the queue, the drafts that are not
vehicles, the same file once, Godkänn alla, the tokens running out, and someone who edits
without AI.

The pretend ID and the fake AI are test_reading.py's: ID keeps the balances and answers the
reservations and the meter with hold, and the AI's answer is text the tests write; no test asks a
real AI (CAT-154). The queue runs when a test says so (Batches.work()), except where Catalog is
started again with its worker thread, as after a restart. Ported from TrainCatalog's
catalog/test_batch.py.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from catalog.app import create_app
from catalog.batches import Batches
from catalog.db import Database
from catalog.fleet import Fleet
from catalog.settings import Settings
from catalog.tests.test_pictures import World, photo, problem, world_with
from catalog.tests.test_reading import (
    HBIS_READ,
    MINE,
    PretendMeter,
    answer,
    read,
    rows,
    said,
    send,
)
from catalog.tests.test_sharing import HBIS, A, B
from contracts.catalog import Batch, BatchCard, CatalogVersion

API = "/api/catalog/1"
TOKENS_OUT = "Tokens tog slut. Fyll i resten för hand eller köp tokens i TrainMeet ID."
BY_HAND = "Utan AI: fyll i fälten för hand."
OTHER_NUMBER = "21 74 245 2 254-8"


def without_warnings(text: str) -> str:
    found = json.loads(text)
    found["warnings"] = []
    return json.dumps(found, ensure_ascii=False)


CLEAR_READ = without_warnings(
    answer(
        kind=said("freight_wagon", "visual_inference"),
        litt=said("Hbis"),
        number=said("21 74 245 2 253-0"),
        operator=said("SJ"),
    )
)
"""A photo read with nothing to check."""


@dataclass
class QueueMeter(PretendMeter):
    """test_reading.py's ID, which can also say that the day's cap is reached (TK15)."""

    capped: bool = False

    def _reserve(self, body: dict[str, Any]) -> httpx.Response:
        if self.capped:
            self.reserved.append(body)
            return httpx.Response(429, json={"code": "too_many", "message": "Taket är nått."})
        return super()._reserve(body)


class Crash(BaseException):
    """The process stops in the middle of a reading: nothing after it runs."""


@pytest.fixture
def pretend() -> QueueMeter:
    return QueueMeter(text=CLEAR_READ)


@pytest.fixture
def world(database_url: str, tmp_path: Path, pretend: QueueMeter) -> Iterator[World]:
    with world_with(database_url, tmp_path, pretend=pretend, batch_queue=False) as made:
        yield made


def app_of(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


@pytest.fixture
def queue(world: World) -> Batches:
    return cast(Batches, app_of(world.a).state.batches)


def many(count: int, start: int = 0) -> list[bytes]:
    """Photos that are different files: each its own size."""
    return [photo(size=(64 + n, 48)) for n in range(start, start + count)]


def sent(
    client: TestClient,
    photos: list[bytes],
    *,
    ident: str | UUID | None = None,
    ai: bool = True,
    consent: bool = True,
    fleet: str | None = None,
) -> httpx.Response:
    data = {"id": str(ident or uuid.uuid4()), "ai": ai, "consent": consent}
    files = [("images", (f"foto{n}.jpg", p, "image/jpeg")) for n, p in enumerate(photos)]
    path = f"{API}/batches" + (f"?fleet={fleet}" if fleet else "")
    answered: httpx.Response = client.post(path, data={"data": json.dumps(data)}, files=files)
    return answered


def batch(answered: httpx.Response) -> Batch:
    assert answered.status_code == 200, answered.text
    return Batch.model_validate(answered.json())


def card_of(answered: httpx.Response) -> BatchCard:
    assert answered.status_code == 200, answered.text
    return BatchCard.model_validate(answered.json())


def _in(path: str, fleet: str | None) -> str:
    return f"{API}{path}" + (f"?fleet={fleet}" if fleet else "")


def shown(client: TestClient, ident: UUID, fleet: str | None = None) -> Batch:
    return batch(client.get(_in(f"/batches/{ident}", fleet)))


def change(
    client: TestClient, card: BatchCard, fleet: str | None = None, **values: Any
) -> httpx.Response:
    body = {"values": {**card.values.model_dump(mode="json"), **values}, "version": card.version}
    answered: httpx.Response = client.post(
        _in(f"/batches/{card.batch}/cards/{card.id}", fleet), json=body
    )
    return answered


def approve(client: TestClient, found: Batch, fleet: str | None = None) -> httpx.Response:
    cards = [
        {"id": str(card.id), "version": card.version}
        for card in found.cards
        if card.status != "approved"
    ]
    answered: httpx.Response = client.post(
        _in(f"/batches/{found.id}/approve", fleet), json={"cards": cards}
    )
    return answered


def retry(client: TestClient, card: BatchCard, fleet: str | None = None) -> httpx.Response:
    answered: httpx.Response = client.post(
        _in(f"/batches/{card.batch}/cards/{card.id}/retry", fleet)
    )
    return answered


def until(check: Callable[[], bool], seconds: float = 10.0) -> None:
    """Wait for the worker thread."""
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, "the queue did not get there in time"
        time.sleep(0.05)


# --- The queue (CAT-147, CAT-19, CAT-143) ------------------------------------------------------


def test_thirty_photos_are_read_one_at_a_time_in_the_order_they_came(
    world: World, pretend: QueueMeter, queue: Batches, database_url: str
) -> None:
    pretend.accounts[MINE] = 1000
    made = batch(sent(world.a, many(30)))
    assert [card.position for card in made.cards] == list(range(30))
    assert {card.status for card in made.cards} == {"waiting"}
    assert (made.ai, made.mine, made.already) == (True, True, [])
    assert pretend.reserved == [] and world.a.get(f"{API}/vehicles").json()["total"] == 0

    assert queue.work() == 30
    after = shown(world.a, made.id)
    assert {card.status for card in after.cards} == {"ready"}
    first = after.cards[0]
    assert first.values.model_dump(
        mode="json", include={"status", "kind", "litt", "number", "operator"}
    ) == {**HBIS, "operator": "SJ"}
    assert (first.attempts, first.version, first.message) == (1, 2, "")
    # In order, each photo a reading of its own, reserved and drawn once (CAT-19, CAT-20).
    order = rows(database_url, "SELECT reading_id FROM batch_card ORDER BY position")
    assert [r["key"] for r in pretend.reserved] == [f"catalog-avlasning-{r}" for (r,) in order]
    assert {r["what"] for r in pretend.reserved} == {"Avläsning av 1 bild i en omgång i Catalog"}
    assert pretend.draws == [(MINE, 12)] * 30 and pretend.accounts[MINE] == 640
    assert rows(database_url, "SELECT count(*), bool_and(batch) FROM reading") == [(30, True)]
    # Each reading sent its card's own photo, the one kept without metadata (CAT-124).
    for card, asked in zip(after.cards, pretend.reads, strict=True):
        (image,) = asked["images"]
        assert card.picture is not None
        kept = world.nobody.get(card.picture.display_url).content
        assert base64.b64decode(image["data"]) == kept

    # Thirty photos is the most in a batch (CAT-147).
    more = sent(world.a, many(1, start=30), ident=made.id)
    assert problem(more) == (422, "too_many_pictures")
    assert sent(world.a, many(31, start=40)).status_code == 422
    assert len(shown(world.a, made.id).cards) == 30


def test_the_same_file_never_becomes_two_drafts(
    world: World, pretend: QueueMeter, queue: Batches, database_url: str
) -> None:
    """CAT-149: by the SHA-256 of the file as it came, per owner, in a retry or a new batch."""
    one, two, three = many(3)
    first = batch(sent(world.a, [one, two, one]))
    assert len(first.cards) == 2 and first.already == []
    again = batch(sent(world.a, [one, two], ident=first.id))  # the same request once more
    assert [card.id for card in again.cards] == [card.id for card in first.cards]
    assert again.already == [card.id for card in first.cards]
    other = batch(sent(world.a, [two, three]))
    assert len(other.cards) == 1 and other.already == [first.cards[1].id]
    assert rows(database_url, "SELECT count(*) FROM batch_card") == [(3,)]
    assert len(world.stored()) == 6  # a display picture and a thumbnail per draft
    assert queue.work() == 3 and len(pretend.reads) == 3
    # Someone else's same file is a draft of their own.
    assert len(batch(sent(world.b, [one])).cards) == 1


def test_when_the_tokens_run_out_the_rest_are_filled_in_by_hand(
    world: World, pretend: QueueMeter, queue: Batches
) -> None:
    """CAT-152: two photos are paid for, and the rest become manual with a clear message."""
    pretend.accounts[MINE] = 30
    made = batch(sent(world.a, many(5)))
    assert queue.work() == 3
    after = shown(world.a, made.id)
    assert [card.status for card in after.cards] == ["ready", "ready", "manual", "manual", "manual"]
    assert {card.message for card in after.cards[2:]} == {TOKENS_OUT}
    assert pretend.draws == [(MINE, 12), (MINE, 12)] and pretend.accounts[MINE] == 6
    assert len(pretend.reserved) == 2, "the balance said no before anything was reserved"
    # With tokens bought, a photo left can be read after all.
    pretend.accounts[MINE] += 100
    assert card_of(retry(world.a, after.cards[2])).status == "waiting"
    assert queue.work() == 1
    assert [card.status for card in shown(world.a, made.id).cards][2:] == [
        "ready",
        "manual",
        "manual",
    ]


def test_the_hours_limit_makes_the_queue_wait_and_never_turns_photos_manual(
    world: World, pretend: QueueMeter, queue: Batches, database_url: str
) -> None:
    """CAT-146: 30 of a batch's readings in an hour, apart from the single readings' 10."""
    for _ in range(30):
        rows(
            database_url,
            "INSERT INTO reading (id, owner_id, person_id, kind, basis, pictures, status, month, "
            "expires_at, created_at, batch) VALUES (%s, %s, %s, 'image', %s, 1, 'failed', "
            "'2026-11', now(), now() - interval '10 minutes', true)",
            str(uuid.uuid4()),
            A,
            A,
            "0" * 64,
        )
    made = batch(sent(world.a, many(2)))
    assert queue.work() == 1
    waiting = shown(world.a, made.id)
    assert {card.status for card in waiting.cards} == {"waiting"}
    assert waiting.message == (
        "Högst 30 avläsningar i timmen för en omgång. Omgången fortsätter om 50 minuter."
    )
    assert waiting.waiting_until is not None
    assert pretend.reserved == []
    assert queue.work() == 0, "the queue waits for the batch"
    # A single reading has its own limit.
    assert read(send(world.a)).cost == 12
    # An hour later the queue goes on by itself.
    rows(database_url, "UPDATE reading SET created_at = created_at - interval '1 hour'")
    rows(database_url, "UPDATE batch SET wait_until = now() - interval '1 second'")
    assert queue.work() == 2
    done = shown(world.a, made.id)
    assert {card.status for card in done.cards} == {"ready"}
    assert (done.message, done.waiting_until) == (None, None)


def test_the_days_cap_in_id_makes_the_queue_wait_too(
    world: World, pretend: QueueMeter, queue: Batches, database_url: str
) -> None:
    pretend.capped = True
    made = batch(sent(world.a, many(1)))
    assert queue.work() == 1
    waiting = shown(world.a, made.id)
    assert waiting.cards[0].status == "waiting"
    assert waiting.message == (
        "Taket för tokens per dygn är nått i TrainMeet ID. Omgången fortsätter om en timme."
    )
    assert pretend.draws == [] and pretend.accounts[MINE] == 100
    assert rows(database_url, "SELECT status FROM reading") == [("failed",)]
    pretend.capped = False
    rows(database_url, "UPDATE batch SET wait_until = now() - interval '1 second'")
    assert queue.work() == 1
    assert shown(world.a, made.id).cards[0].status == "ready"


def test_after_a_restart_a_photo_cut_off_is_given_back_and_read_again(
    world: World, pretend: QueueMeter, queue: Batches, database_url: str, tmp_path: Path
) -> None:
    """CAT-151: the process stops while the AI reads. After a restart the reservation that ran
    out goes back, the photo fails, and it is read again by the worker thread, drawn once."""
    made = batch(sent(world.a, many(1)))

    def crash() -> None:
        raise Crash()

    pretend.during_read = crash
    with pytest.raises(Crash):
        queue.work()
    pretend.during_read = None
    assert shown(world.a, made.id).cards[0].status == "reading"
    (held,) = pretend.reservations.values()
    assert held["state"] == "held" and pretend.accounts[MINE] == 88
    rows(database_url, "UPDATE reading SET expires_at = now() - interval '1 second'")

    with world_with(database_url, tmp_path, pretend=pretend) as again:  # with the worker thread
        until(lambda: shown(again.a, made.id).cards[0].status != "reading")
        (card,) = shown(again.a, made.id).cards
        assert (card.status, card.message) == (
            "failed",
            "Avläsningen avbröts. Läs av igen: inget dras två gånger.",
        )
        assert held["state"] == "returned" and pretend.accounts[MINE] == 100
        assert card_of(retry(again.a, card)).status == "waiting"
        until(lambda: shown(again.a, made.id).cards[0].status == "ready")
    assert pretend.draws == [(MINE, 12)] and pretend.accounts[MINE] == 88
    assert rows(database_url, "SELECT status FROM reading ORDER BY created_at") == [
        ("failed",),
        ("done",),
    ]


# --- Godkänn alla (CAT-150, CAT-136, CAT-143) --------------------------------------------------


def test_approve_all_is_all_or_nothing(world: World, queue: Batches, database_url: str) -> None:
    made = batch(sent(world.a, many(3), ai=False))
    assert {(card.status, card.message) for card in made.cards} == {("manual", BY_HAND)}
    first, second, third = made.cards
    card_of(change(world.a, first, **HBIS))
    card_of(change(world.a, second, status="ready", litt="Rc6"))  # ready, but without a kind
    card_of(change(world.a, third, **{**HBIS, "number": OTHER_NUMBER}))
    seen = shown(world.a, made.id)

    refused = approve(world.a, seen)
    assert refused.status_code == 422
    assert refused.json() == {
        "code": "not_ready",
        "message": "Inget godkändes. Ett utkast behöver ändras först: Ett klart fordon behöver "
        "slag och littera eller nummer.",
        "cards": [str(second.id)],
    }
    assert world.a.get(f"{API}/vehicles").json()["total"] == 0
    assert rows(database_url, "SELECT count(*) FROM picture") == [(0,)]
    assert {card.status for card in shown(world.a, made.id).cards} == {"manual"}
    # What the owner has not seen is not approved (CAT-136).
    stale = seen.model_copy(update={"cards": [first, *seen.cards[1:]]})
    assert problem(approve(world.a, stale)) == (409, "changed")
    part = seen.model_copy(update={"cards": seen.cards[:2]})
    assert problem(approve(world.a, part)) == (409, "changed")

    card_of(change(world.a, seen.cards[1], kind="locomotive"))
    done = batch(approve(world.a, shown(world.a, made.id)))
    assert {card.status for card in done.cards} == {"approved"}
    assert all(card.vehicle is not None and card.picture is None for card in done.cards)
    assert world.a.get(f"{API}/vehicles").json()["total"] == 3
    # Once is enough: the same approval again makes nothing more.
    assert problem(approve(world.a, seen)) == (409, "changed")
    assert world.a.get(f"{API}/vehicles").json()["total"] == 3
    assert world.a.get(f"{API}/batches").json() == []
    # A photo still in the queue stops it too.
    waiting = batch(sent(world.a, many(1, start=9)))
    assert problem(approve(world.a, waiting)) == (409, "reading_busy")


def test_an_approved_card_is_a_vehicle_with_its_photo_and_the_ais_values_marked(
    world: World, pretend: QueueMeter, queue: Batches
) -> None:
    pretend.text = HBIS_READ  # with a warning, to check
    made = batch(sent(world.a, many(1)))
    queue.work()
    (card,) = shown(world.a, made.id).cards
    assert (card.status, card.warnings) == ("review", ["Kontrollera numret."])
    assert card.suggestions["litt"].value == "Hbis" and card.values.status == "ready"
    assert card.picture is not None
    photo_kept = world.nobody.get(card.picture.display_url).content
    card = card_of(change(world.a, card, operator="Green Cargo"))  # the owner sets it right

    (done,) = batch(approve(world.a, shown(world.a, made.id))).cards
    assert done.status == "approved" and done.vehicle is not None and done.picture is None
    vehicle = world.a.get(f"{API}/vehicles/{done.vehicle}").json()
    assert (vehicle["status"], vehicle["litt"], vehicle["operator"]) == (
        "ready",
        "Hbis",
        "Green Cargo",
    )
    assert vehicle["field_sources"] == {
        "kind": "ai",
        "litt": "ai",
        "number": "ai",
        "operator": "owner",
    }
    (picture,) = world.a.get(f"{API}/vehicles/{done.vehicle}/pictures").json()
    assert (picture["main"], picture["background"]) == (True, "original")
    assert world.nobody.get(picture["display_url"]).content == photo_kept
    assert vehicle["picture"]["display_url"] == picture["display_url"]
    # It counts in the storage from now on (CAT-131).
    usage = world.a.get(f"{API}/storage").json()
    assert (usage["pictures"], usage["used"]) == (1, picture["bytes"])
    # Its files are the vehicle's: they stay with it, and go with it.
    world.pictures.sweep()
    assert len(world.stored()) == 2
    removed = world.a.delete(f"{API}/vehicles/{done.vehicle}?version={vehicle['version']}")
    assert removed.status_code == 200
    assert world.stored() == [] and shown(world.a, made.id).cards == []


# --- Drafts are not vehicles (CAT-148) --------------------------------------------------------


def test_drafts_are_not_in_lists_sharing_tags_lookup_trips_export_or_storage(
    world: World, queue: Batches
) -> None:
    world.id.roles[(B, A)] = "viewer"
    made = batch(sent(world.a, many(1), ai=False))
    card = card_of(change(world.a, made.cards[0], **HBIS))
    draft = str(card.id)
    # The vehicle list, and the vehicle by its id.
    assert world.a.get(f"{API}/vehicles").json()["total"] == 0
    assert world.a.get(f"{API}/vehicles?q=Hbis").json()["vehicles"] == []
    assert world.a.get(f"{API}/vehicles/{draft}").status_code == 404
    # The sharing: who looks sees no vehicle, and no batch at all.
    assert world.b.get(f"{API}/vehicles?fleet={A}").json()["total"] == 0
    assert world.b.get(f"{API}/batches?fleet={A}").status_code == 403
    assert world.b.get(f"{API}/batches/{made.id}?fleet={A}").status_code == 403
    # The tags and the lookup: no tag is linked to a draft, and a tag says nothing of it.
    tag = world.a.post(f"{API}/tags/simulated").json()["uid"]
    linked = world.a.post(f"{API}/tags/{tag}/link", json={"vehicle": draft, "confirm": True})
    assert linked.status_code == 404
    assert world.a.post(f"{API}/tags/pending", json={"vehicle": draft}).status_code == 404
    assert world.a.post(f"{API}/vehicles/{draft}/tags/qr", json={}).status_code == 404
    assert world.a.get(f"{API}/tags/{tag}").json()["outcome"] == "unknown"
    # The trip to the meet: a draft is not packed.
    meet = world.a.post(f"{API}/meets", json={"name": "Vårträffen", "date": "2026-12-05"})
    packed = world.a.post(f"{API}/meets/{meet.json()['id']}/vehicles", json={"vehicles": [draft]})
    assert packed.status_code == 404
    # The export, and the storage until it is approved.
    exported = Fleet(cast(Database, app_of(world.a).state.db)).export(UUID(A))
    assert (exported.vehicles, exported.history) == ([], [])
    usage = world.a.get(f"{API}/storage").json()
    assert (usage["pictures"], usage["used"]) == (0, 0)


# --- Someone who edits (CAT-153, CAT-46) ------------------------------------------------------


def test_someone_who_edits_leaves_photos_without_ai_and_never_sees_the_owners_drafts(
    world: World, pretend: QueueMeter, queue: Batches
) -> None:
    world.id.roles[(B, A)] = "editor"
    owners = batch(sent(world.a, many(1)))
    assert problem(sent(world.b, many(1, start=5), fleet=A)) == (403, "forbidden")
    left = batch(sent(world.b, many(2, start=5), ai=False, consent=False, fleet=A))
    assert (left.ai, left.mine) == (False, True)
    assert {(card.status, card.message) for card in left.cards} == {("manual", BY_HAND)}
    assert all(card.picture is not None for card in left.cards)
    # Only the owner's photo is read, with the owner's tokens; B's are never sent to an AI.
    assert queue.work() == 1
    assert [asked["person"] for asked in pretend.reserved] == [A]
    assert len(pretend.reads) == 1 and pretend.accounts[f"person:{B}"] == 100

    # B sees the batch B left, never the owner's.
    listed = world.b.get(f"{API}/batches?fleet={A}").json()
    assert [(found["id"], found["mine"]) for found in listed] == [(str(left.id), True)]
    assert world.b.get(f"{API}/batches/{owners.id}?fleet={A}").status_code == 404
    owners_card = owners.cards[0]
    assert change(world.b, owners_card, fleet=A, litt="X").status_code == 404
    path = f"{API}/batches/{owners.id}/cards/{owners_card.id}?fleet={A}"
    assert world.b.delete(path).status_code == 404
    # B fills in what B left, but the place stays the owner's (CAT-71).
    place = world.a.post(f"{API}/places", json={"name": "Lådan"}).json()["id"]
    filled = card_of(change(world.b, left.cards[0], fleet=A, **HBIS, place=place))
    assert (filled.values.litt, filled.values.place) == ("Hbis", None)
    # Only the owner reads again and approves.
    assert retry(world.b, left.cards[0], fleet=A).status_code == 403
    assert approve(world.b, shown(world.b, left.id, fleet=A), fleet=A).status_code == 403

    # The owner sees both, and approves what B left.
    mine = {found["id"]: found["mine"] for found in world.a.get(f"{API}/batches").json()}
    assert mine == {str(owners.id): True, str(left.id): False}
    other = shown(world.a, left.id)
    assert not other.mine
    card_of(change(world.a, other.cards[1], **{**HBIS, "number": OTHER_NUMBER}))
    approved = batch(approve(world.a, shown(world.a, left.id)))
    assert {card.status for card in approved.cards} == {"approved"}
    # Approved, they are vehicles, which B sees as such; the drafts B no longer sees.
    assert world.b.get(f"{API}/vehicles?fleet={A}").json()["total"] == 2
    assert shown(world.b, left.id, fleet=A).cards == []
    assert world.b.get(f"{API}/batches?fleet={A}").json() == []
    # To look gives no batches at all.
    world.id.roles[(B, A)] = "viewer"
    assert world.b.get(f"{API}/batches?fleet={A}").status_code == 403


# --- Removing (CAT-148, CAT-193) -----------------------------------------------------------


def test_removing_a_card_a_batch_or_the_account_removes_its_files(
    world: World, pretend: QueueMeter, queue: Batches, database_url: str
) -> None:
    photos = many(3)
    made = batch(sent(world.a, photos, ai=False))
    assert len(world.stored()) == 6
    first = made.cards[0]
    assert world.a.delete(f"{API}/batches/{made.id}/cards/{first.id}").status_code == 200
    assert len(world.stored()) == 4
    assert [card.id for card in shown(world.a, made.id).cards] == [c.id for c in made.cards[1:]]
    # Its draft gone, the same file may come again.
    back = batch(sent(world.a, photos[:1], ident=made.id, ai=False))
    assert len(back.cards) == 3 and back.already == []
    assert world.a.delete(f"{API}/batches/{made.id}").status_code == 200
    assert world.stored() == []
    assert world.a.get(f"{API}/batches/{made.id}").status_code == 404

    # A photo removed while the AI reads it: the answer is not used and costs nothing (CAT-145).
    reading = batch(sent(world.a, many(1, start=7)))

    def removed() -> None:
        assert world.a.delete(f"{API}/batches/{reading.id}").status_code == 200

    pretend.during_read = removed
    assert queue.work() == 1
    assert pretend.draws == [] and len(pretend.returned) == 1 and pretend.accounts[MINE] == 100
    assert rows(database_url, "SELECT status FROM reading") == [("discarded",)]
    assert world.stored() == []

    # The account: its batches go with it, and their files (CAT-193). What someone left in
    # another's fleet stays with that owner, to fill in by hand.
    pretend.during_read = None
    world.id.roles[(A, B)] = "editor"
    batch(sent(world.a, many(2, start=10), ai=False))
    batch(sent(world.a, many(1, start=12), ai=False, fleet=B))
    assert len(world.stored()) == 6
    Fleet(cast(Database, app_of(world.a).state.db)).remove_owners([UUID(A)])
    world.pictures.sweep()
    assert len(world.stored()) == 2
    assert rows(database_url, "SELECT owner_id::text, created_by::text, ai FROM batch") == [
        (B, str(UUID(int=0)), False)
    ]


# --- What a batch needs (CAT-142, CAT-46) ---------------------------------------------------


def test_reading_with_ai_needs_the_consent_and_the_form_is_read_strictly(
    world: World, queue: Batches, database_url: str
) -> None:
    refused = sent(world.a, many(1), consent=False)
    assert problem(refused) == (422, "consent_required")
    assert rows(database_url, "SELECT count(*) FROM batch") == [(0,)] and world.stored() == []
    batch(sent(world.a, many(1)))
    assert rows(database_url, "SELECT person_id::text, kind FROM privacy_event") == [
        (A, "ai_reading_consent")
    ]
    assert batch(sent(world.a, many(1, start=1), consent=False)).ai  # said yes before
    # A photo that cannot be read refuses them all, and nothing is kept.
    bad = sent(world.a, [photo(size=(90, 60)), b"inte en bild"])
    assert problem(bad) == (415, "bad_picture")
    assert bad.json()["message"].startswith("Foto 2: ")
    assert rows(database_url, "SELECT count(*) FROM batch_card") == [(2,)]
    # The same id is the same person's batch, read the same way.
    manual = batch(sent(world.a, many(1, start=20), ai=False))
    assert problem(sent(world.a, many(1, start=21), ident=manual.id)) == (409, "changed")
    world.id.roles[(B, A)] = "editor"
    taken = sent(world.b, many(1, start=22), ident=manual.id, ai=False, fleet=A)
    assert problem(taken) == (409, "changed")
    # The form: the ask and 1–30 photos, nothing else.
    nothing = world.a.post(f"{API}/batches", data={"data": json.dumps({"id": str(uuid.uuid4())})})
    assert nothing.status_code == 422
    assert world.a.post(f"{API}/batches", json={"id": str(uuid.uuid4())}).status_code == 422
    assert world.nobody.post(f"{API}/batches").status_code == 401


def test_without_id_photos_are_left_but_not_read(database_url: str, tmp_path: Path) -> None:
    settings = Settings(
        database_url=database_url,
        migrate="auto",
        trial_login=True,
        web_dir=tmp_path,
        build=CatalogVersion(version="0.1.0"),
        pictures_dir=tmp_path / "bilder",
    )
    with TestClient(create_app(settings, batch_queue=False)) as client:
        assert client.post(f"{API}/trial/login", json={"account": A}).status_code == 200
        assert problem(sent(client, many(1))) == (503, "unavailable")
        left = batch(sent(client, many(1), ai=False))
        assert left.cards[0].status == "manual"
