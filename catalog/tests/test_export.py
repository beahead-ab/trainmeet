"""Kontoexport (#56, CAT-188): everything the owner has, as one ZIP with catalog.json and the
pictures' files, only for the owner, and never with another owner's data.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from catalog.account_export import DATA, Export, Exports
from catalog.fleet import Refused
from catalog.pictures import Stored
from catalog.tests.test_pictures import World, photo, problem, upload, world_with
from catalog.tests.test_prototypes import (
    C,
    Catalog,
    PretendReviewers,
    new_vehicle,
    proposed,
    reviewed,
    vehicle_of,
)
from catalog.tests.test_prototypes import link as link_prototype
from catalog.tests.test_sharing import A, B
from contracts.catalog import CatalogExport, OwnerSettings, PictureBackground, ProblemCode

API = "/api/catalog/1"
NFC = "04a1b2c3d4e5f6"


@pytest.fixture
def world(database_url: str, tmp_path: Path) -> Iterator[World]:
    with world_with(database_url, tmp_path, batch_queue=False) as made:
        yield made


@pytest.fixture
def reviewing(database_url: str, tmp_path: Path) -> Iterator[Catalog]:
    """Catalog with a reviewer of the prototypes, Provkonto C, as in test_prototypes.py."""
    pretend = PretendReviewers()
    with world_with(database_url, tmp_path, pretend=pretend) as made:
        c = TestClient(made.nobody.app)
        assert c.post(f"{API}/trial/login", json={"account": C}).status_code == 200
        pretend.reviewers.add(C)
        yield Catalog(made, pretend, made.a, made.b, c)


def made(client: TestClient, litt: str, number: str, **fields: Any) -> str:
    body = {"status": "ready", "kind": "freight_wagon", "litt": litt, "number": number, **fields}
    answer = client.post(f"{API}/vehicles", json=body)
    assert answer.status_code == 201, answer.text
    return str(answer.json()["id"])


def link(client: TestClient, uid: str, vehicle: str) -> dict[str, Any]:
    answer = client.post(f"{API}/tags/{uid}/link", json={"vehicle": vehicle, "confirm": True})
    assert answer.status_code == 200, answer.text
    tags: list[dict[str, Any]] = answer.json()["tags"]
    return next(tag for tag in tags if tag["uid"] == uid)


def unlink(client: TestClient, vehicle: str, assignment: str) -> None:
    answer = client.post(
        f"{API}/vehicles/{vehicle}/tags/unlink", json={"assignment": assignment, "confirm": True}
    )
    assert answer.status_code == 200, answer.text


def opened(client: TestClient, fleet: str | None = None) -> tuple[zipfile.ZipFile, CatalogExport]:
    answer = client.get(f"{API}/export" + (f"?fleet={fleet}" if fleet else ""))
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"] == "application/zip"
    assert answer.headers["cache-control"] == "private, no-store"
    disposition = answer.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="trainmeet-catalog-20')
    archive = zipfile.ZipFile(io.BytesIO(answer.content))
    assert archive.testzip() is None
    return archive, CatalogExport.model_validate_json(archive.read(DATA))


def test_the_zip_has_the_owners_data_and_the_pictures(world: World) -> None:
    place = world.a.post(f"{API}/places", json={"name": "Låda 1"}).json()["id"]
    gbs = made(world.a, "Gbs", "21 74 150 3 087-3", place=place, note="Köpt 2019")
    hbis = made(world.a, "Hbis", "21 74 245 2 253-0")
    side = upload(world, gbs, photo((90, 60), (200, 40, 40)), keep_original=True).json()
    end = upload(world, gbs, photo((60, 40), (40, 40, 200))).json()
    sim = world.a.post(f"{API}/tags/simulated").json()
    link(world.a, sim["uid"], gbs)
    label = world.a.post(f"{API}/vehicles/{hbis}/tags/qr", json={}).json()["tags"][0]
    trip = world.a.post(f"{API}/meets", json={"name": "Höstträffen", "date": "2026-11-28"}).json()
    packed = world.a.post(f"{API}/meets/{trip['id']}/vehicles", json={"vehicles": [gbs]})
    assert packed.status_code == 200, packed.text

    archive, data = opened(world.a)
    assert data.owner == UUID(A)
    assert [v.litt for v in data.vehicles] == ["Gbs", "Hbis"]
    assert data.vehicles[0].note == "Köpt 2019" and data.vehicles[0].place_name == "Låda 1"
    # The addresses expire, so they are left out: the files are in the ZIP (CAT-130).
    assert all(vehicle.picture is None for vehicle in data.vehicles)
    assert all(row.vehicle.picture is None for trip in data.trips for row in trip.rows)
    assert [p.name for p in data.places] == ["Låda 1"]
    assert [t.name for t in data.trips] == ["Höstträffen"]
    assert {h.vehicle for h in data.history} == {UUID(gbs), UUID(hbis)}
    assert data.settings == OwnerSettings(show_name=False)

    # The tags, with their links and the owner's own events (CAT-93).
    tags = {tag.uid: tag for tag in data.tags}
    assert set(tags) == {sim["uid"], label["uid"]}
    assert tags[label["uid"]].kind == "qr"
    assert [(a.vehicle, a.ended_at) for a in tags[sim["uid"]].assignments] == [(UUID(gbs), None)]
    assert [e.event for e in tags[sim["uid"]].events] == ["linked"]

    # The pictures: the display picture of each, and the original that was kept (CAT-17).
    by_id = {picture.id: picture for picture in data.pictures}
    assert set(by_id) == {UUID(side["id"]), UUID(end["id"])}
    first = by_id[UUID(side["id"])]
    assert (first.vehicle, first.main, first.position) == (UUID(gbs), True, 0)
    assert first.display == f"bilder/{gbs}/{side['id']}.jpg"
    assert first.original == f"bilder/{gbs}/{side['id']}-original.jpg"
    assert by_id[UUID(end["id"])].original is None
    names = archive.namelist()
    assert names[-1] == DATA
    assert sorted(names[:-1]) == sorted(
        [first.display, first.original, by_id[UUID(end["id"])].display]
    )
    # The files are the pictures as Catalog keeps them.
    assert archive.read(first.display) == world.nobody.get(side["display_url"]).content
    assert archive.read(first.original) == world.nobody.get(side["original_url"]).content
    # Stored as they are: the pictures are compressed already.
    assert archive.getinfo(first.display).compress_type == zipfile.ZIP_STORED
    assert archive.getinfo(DATA).compress_type == zipfile.ZIP_DEFLATED


def test_the_prototype_links_are_in_it_with_their_type_data(reviewing: Catalog) -> None:
    revision = reviewed(reviewing, proposed(reviewing.a))
    car = vehicle_of(link_prototype(reviewing.a, new_vehicle(reviewing.a), revision))
    _, data = opened(reviewing.a)
    (vehicle,) = data.vehicles
    assert vehicle.id == car.id and vehicle.prototype is not None
    assert (vehicle.prototype.id, vehicle.prototype.revision) == (revision.prototype, 1)
    assert vehicle.prototype.fields["max_speed"] == "100"


def test_only_the_owner_exports(world: World) -> None:
    made(world.a, "Gbs", "3087")
    world.id.roles[(B, A)] = "editor"
    assert problem(world.b.get(f"{API}/export?fleet={A}")) == (403, "forbidden")
    world.id.roles[(B, A)] = "viewer"
    assert problem(world.b.get(f"{API}/export?fleet={A}")) == (403, "forbidden")
    del world.id.roles[(B, A)]
    assert problem(world.b.get(f"{API}/export?fleet={A}")) == (404, "not_found")
    assert problem(world.nobody.get(f"{API}/export")) == (401, "login")
    # A club's administrators have the owner's right to the club's fleet (C39).
    world.id.roles[(B, A)] = "admin"
    _, data = opened(world.b, fleet=A)
    assert [v.litt for v in data.vehicles] == ["Gbs"]


def test_another_owners_data_is_never_included(world: World) -> None:
    mine = made(world.a, "Gbs", "3087")
    theirs = made(world.b, "Hbis", "2253", note="B:s egen anteckning")
    upload(world, theirs, photo((70, 50)), client=world.b)
    # A physical tag A used, and unlinked, is B's now (CAT-91): A keeps A's own history only.
    first = link(world.a, NFC, mine)
    unlink(world.a, mine, first["assignment"])
    link(world.b, NFC, theirs)
    # B edits A's fleet: B's picture there is the owner's, and so in A's file, not B's.
    world.id.roles[(B, A)] = "editor"
    left = upload(world, mine, photo((50, 50)), client=world.b, fleet=A).json()
    trip = world.b.post(f"{API}/meets", json={"name": "B:s träff", "date": "2026-11-28"})
    assert trip.status_code == 201

    archive, data = opened(world.a)
    assert [str(v.id) for v in data.vehicles] == [mine]
    assert [str(p.id) for p in data.pictures] == [left["id"]]
    (tag,) = data.tags
    assert tag.uid == NFC
    assert [(a.vehicle, a.ended_at is not None) for a in tag.assignments] == [(UUID(mine), True)]
    assert [(e.event, e.vehicle_id) for e in tag.events] == [
        ("linked", UUID(mine)),
        ("unlinked", UUID(mine)),
    ]
    assert data.trips == []
    whole = b"".join(archive.read(name) for name in archive.namelist()).decode("latin-1")
    for other in (theirs, "B:s egen anteckning", "B:s träff", "Hbis"):
        assert other not in whole

    _, own = opened(world.b)
    assert [str(v.id) for v in own.vehicles] == [theirs]
    assert left["id"] not in {str(p.id) for p in own.pictures}
    (tag,) = own.tags
    assert [a.vehicle for a in tag.assignments] == [UUID(theirs)]
    assert [e.vehicle_id for e in tag.events] == [UUID(theirs)]


def test_the_data_is_read_before_the_zip_is_written(world: World) -> None:
    """Everything is read before the first byte is sent; the pictures are listed as their files
    go into the ZIP."""
    car = made(world.a, "Gbs", "3087")
    upload(world, car, photo())
    sim = world.a.post(f"{API}/tags/simulated").json()
    link(world.a, sim["uid"], car)
    app = cast(Any, world.a.app)
    exports: Exports = app.state.exports
    export = exports.read(UUID(A))
    assert [t.uid for t in export.data.tags] == [sim["uid"]]
    assert export.data.pictures == []
    assert len(export.stored) == 1


class _Store:
    """The pictures' store, as the export fetches from it: one file is gone."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def fetch(self, key: str) -> bytes:
        if key not in self.files:
            raise Refused(503, ProblemCode.UNAVAILABLE, "Bilderna går inte att nå just nu.")
        return self.files[key]


def test_the_zip_is_written_a_picture_at_a_time() -> None:
    """Each picture goes as soon as it is written, so the ZIP is never held in memory, and
    catalog.json lists only the pictures whose files are in it."""
    owner, vehicle = uuid4(), uuid4()
    files = {f"{owner}/{n}.jpg": bytes([n]) * 200_000 for n in range(5)}
    stored = [
        Stored(uuid4(), vehicle, n == 0, n, 10, 10, PictureBackground.ORIGINAL, key, None)
        for n, key in enumerate([*files, f"{owner}/borta.jpg"])
    ]
    data = CatalogExport(owner=owner, vehicles=[], history=[], places=[], settings=OwnerSettings())
    exports = Exports(cast(Any, None), cast(Any, None), cast(Any, None), cast(Any, _Store(files)))
    parts = list(exports.zip(Export(data, stored, datetime(2026, 11, 18, tzinfo=UTC))))
    assert len(parts) >= 6
    assert max(len(part) for part in parts) < 250_000
    archive = zipfile.ZipFile(io.BytesIO(b"".join(parts)))
    assert archive.testzip() is None
    # No data descriptors: the headers are finished before each part is sent.
    assert all(info.flag_bits & 0x08 == 0 for info in archive.infolist())
    listed = json.loads(archive.read(DATA))["pictures"]
    assert len(listed) == 5
    assert f"bilder/{vehicle}/{stored[5].id}.jpg" not in archive.namelist()
    assert archive.read(listed[2]["display"]) == bytes([2]) * 200_000
