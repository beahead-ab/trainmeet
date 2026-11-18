"""The vehicles' pictures (CAT-05, CAT-17, CAT-123–CAT-133): uploads without metadata, the main
picture, the storage per owner and per club, the shared fleets, the signed addresses, and the
files that go when their pictures go.

The pictures lie on disk in tmp_path (DiskStore), and a pretend ID says who may do what, as in
test_sharing.py. Object Storage (S3Store) is tried against a pretend server.
"""

from __future__ import annotations

import hashlib
import io
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import botocore.auth
import httpx
import psycopg
import pytest
from botocore.auth import S3SigV4QueryAuth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from fastapi.testclient import TestClient
from PIL import ExifTags, Image, ImageCms

from catalog.app import CONTENT_SECURITY_POLICY, content_security_policy, create_app
from catalog.backgrounds import NoSegmenter, Segmenter
from catalog.fleet import Fleet, Refused
from catalog.pictures import (
    LINK_LIFETIME,
    MAX_BYTES,
    DiskStore,
    PictureLimits,
    Pictures,
    S3Store,
    StoreFailed,
    new_key,
    prepare,
    signed_at,
)
from catalog.settings import IdSettings, S3Settings, Settings, SettingsError, from_env
from catalog.tests.test_sharing import CLUB, HBIS, A, B, PretendId
from contracts.catalog import CatalogVersion, Picture, ProblemCode, StorageUse, Vehicle

API = "/api/catalog/1"
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


@dataclass
class PretendIdWithClubs(PretendId):
    """ID, which also says which owners are clubs (TOKEN-29)."""

    clubs: set[str] = field(default_factory=set)

    def handle(self, request: httpx.Request) -> httpx.Response:
        answer = super().handle(request)
        if request.url.path.endswith("/apps/fleets"):
            listed = [{**f, "club": f["owner"]["id"] in self.clubs} for f in answer.json()]
            return httpx.Response(200, json=listed)
        return answer


@dataclass
class World:
    id: PretendIdWithClubs
    a: TestClient
    b: TestClient
    nobody: TestClient
    pictures: Pictures
    files: Path

    def vehicle(self, client: TestClient | None = None, fleet: str | None = None) -> str:
        answer = (client or self.a).post(_in(f"{API}/vehicles", fleet), json=HBIS)
        assert answer.status_code == 201, answer.text
        return str(answer.json()["id"])

    def stored(self) -> list[Path]:
        return sorted(self.files.rglob("*.jpg"))


def _in(path: str, fleet: str | None) -> str:
    return path if fleet is None else f"{path}{'&' if '?' in path else '?'}fleet={fleet}"


@contextmanager
def world_with(
    database_url: str,
    tmp_path: Path,
    limits: PictureLimits | None = None,
    segmenter: Segmenter | None = None,
    pretend: PretendIdWithClubs | None = None,
    batch_queue: bool = True,
) -> Iterator[World]:
    """Catalog with a pretend ID. This one bills no storage, as for an owner ID does not know,
    so Catalog refuses over the free level; test_storage_tokens.py gives one that does.
    batch_queue False leaves the batches' queue to the test (test_batches.py)."""
    pretend = pretend if pretend is not None else PretendIdWithClubs()
    settings = Settings(
        database_url=database_url,
        migrate="auto",
        trial_login=True,
        web_dir=tmp_path / "web",
        id=IdSettings(
            issuer="https://id.example.test/realms/trainmeet",
            client="catalog",
            secret="hemlighet",
            public_url="https://catalog.example.test",
            internal="http://id:8080/realms/trainmeet",
            api="http://id-api:8080",
        ),
        build=CatalogVersion(version="0.1.0"),
        simulated_tags=True,
        pictures_dir=tmp_path / "bilder",
    )
    app = create_app(
        settings,
        id_http=httpx.Client(transport=httpx.MockTransport(pretend.handle)),
        picture_limits=limits,
        segmenter=segmenter if segmenter is not None else NoSegmenter(),
        batch_queue=batch_queue,
    )
    with TestClient(app) as a, TestClient(app) as b:
        for client, who in ((a, A), (b, B)):
            assert client.post(f"{API}/trial/login", json={"account": who}).status_code == 200
        pictures: Pictures = app.state.pictures
        yield World(pretend, a, b, TestClient(app), pictures, tmp_path / "bilder")


@pytest.fixture
def world(database_url: str, tmp_path: Path) -> Iterator[World]:
    with world_with(database_url, tmp_path) as made:
        yield made


def photo(size: tuple[int, int] = (64, 48), color: tuple[int, int, int] = (40, 90, 160)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG", quality=90)
    return out.getvalue()


def upload(
    world: World,
    vehicle: str,
    data: bytes,
    *,
    kind: str = "image/jpeg",
    client: TestClient | None = None,
    fleet: str | None = None,
    keep_original: bool = False,
) -> httpx.Response:
    path = f"{API}/vehicles/{vehicle}/pictures" + ("?keep_original=true" if keep_original else "")
    answer: httpx.Response = (client or world.a).post(
        _in(path, fleet), content=data, headers={"Content-Type": kind}
    )
    return answer


def added(answer: httpx.Response) -> Picture:
    assert answer.status_code == 201, answer.text
    return Picture.model_validate(answer.json())


def problem(answer: httpx.Response) -> tuple[int, str]:
    return answer.status_code, answer.json()["code"]


def fetched(world: World, url: str) -> Image.Image:
    answer = world.nobody.get(url)
    assert answer.status_code == 200, answer.text
    return Image.open(io.BytesIO(answer.content))


# --- An upload (CAT-123, CAT-124, CAT-126) -------------------------------------------------


def test_a_photo_loses_its_position_camera_and_profile_and_stands_upright(world: World) -> None:
    image = Image.new("RGB", (640, 480), (180, 40, 40))
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "Kameran AB"
    exif[ExifTags.Base.Model] = "Modell 7"
    exif[ExifTags.Base.Orientation] = 6  # taken on its side
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (59.0, 19.0, 30.0)
    gps[ExifTags.GPS.GPSLongitudeRef] = "E"
    gps[ExifTags.GPS.GPSLongitude] = (18.0, 4.0, 10.0)
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif, icc_profile=SRGB, comment=b"Hemligt garage")
    data = out.getvalue()
    sent = Image.open(io.BytesIO(data))
    assert sent.getexif().get_ifd(ExifTags.IFD.GPSInfo)  # the photo has a position to lose

    picture = added(upload(world, world.vehicle(), data))
    assert (picture.width, picture.height) == (480, 640)  # upright (CAT-124)
    assert picture.main and picture.original_url is None
    for url in (picture.display_url, picture.thumb_url):
        shown = fetched(world, url)
        assert dict(shown.getexif()) == {}
        assert "icc_profile" not in shown.info and "comment" not in shown.info
    for path in world.stored():
        raw = path.read_bytes()
        assert b"Exif" not in raw and b"Kameran" not in raw and b"Hemligt" not in raw
    assert fetched(world, picture.thumb_url).size == (180, 240)
    assert len(world.stored()) == 2  # the display picture and the thumbnail (CAT-126)


def test_png_and_webp_are_taken_and_transparency_becomes_white(world: World) -> None:
    car = world.vehicle()
    clear = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    clear.paste((200, 0, 0, 255), (30, 20, 70, 60))
    png = io.BytesIO()
    clear.save(png, "PNG")
    webp = io.BytesIO()
    Image.new("RGB", (120, 90), (20, 160, 60)).save(webp, "WEBP")

    from_png = added(upload(world, car, png.getvalue(), kind="image/png"))
    corner = fetched(world, from_png.display_url).convert("RGB").getpixel((0, 0))
    assert isinstance(corner, tuple) and min(corner) > 240
    from_webp = added(upload(world, car, webp.getvalue(), kind="image/webp"))
    shown = fetched(world, from_webp.display_url)
    assert (shown.format, shown.size) == ("JPEG", (120, 90))


def test_too_large_too_many_megapixels_and_not_a_picture_are_refused(world: World) -> None:
    car = world.vehicle()
    too_big = upload(world, car, b"\xff" * (MAX_BYTES + 1))
    assert problem(too_big) == (413, "picture_too_large")
    streamed = world.a.post(
        f"{API}/vehicles/{car}/pictures",
        content=iter([b"\xff" * (1024 * 1024)] * 16),
        headers={"Content-Type": "image/jpeg"},
    )
    assert problem(streamed) == (413, "picture_too_large")

    def png(size: tuple[int, int]) -> bytes:
        out = io.BytesIO()
        Image.new("1", size).save(out, "PNG")
        return out.getvalue()

    # Just over 40 megapixel, and far over: Pillow's own bomb protection (CAT-123).
    for size in ((8000, 5001), (9000, 10000)):
        refused = upload(world, car, png(size), kind="image/png")
        assert problem(refused) == (422, "picture_too_large"), size
        assert "40 megapixel" in refused.json()["message"]
    gif = io.BytesIO()
    Image.new("RGB", (10, 10)).save(gif, "GIF")
    assert problem(upload(world, car, gif.getvalue(), kind="image/gif")) == (415, "bad_picture")
    assert problem(upload(world, car, gif.getvalue(), kind="image/png")) == (415, "bad_picture")
    assert problem(upload(world, car, b"inte en bild")) == (415, "bad_picture")
    broken = upload(world, car, photo((400, 300))[:600])
    assert problem(broken) == (422, "bad_picture")
    assert "kunde inte läsas" in broken.json()["message"]
    assert world.stored() == []
    assert world.a.get(f"{API}/vehicles/{car}/pictures").json() == []


def test_the_eleventh_picture_is_refused(world: World) -> None:
    """10 pictures per vehicle, for everyone (CAT-17)."""
    car = world.vehicle()
    for _ in range(10):
        added(upload(world, car, photo()))
    refused = upload(world, car, photo())
    assert problem(refused) == (422, "too_many_pictures")
    assert "högst 10 bilder" in refused.json()["message"]
    assert len(world.a.get(f"{API}/vehicles/{car}/pictures").json()) == 10
    assert len(world.stored()) == 20
    added(upload(world, world.vehicle(), photo()))  # another vehicle has room


# --- The storage (CAT-17, CAT-131, CAT-133, TOKEN-29) ----------------------------------------


def test_the_free_storage_counts_per_owner_and_a_club_has_its_own(
    database_url: str, tmp_path: Path
) -> None:
    size = prepare(photo()).size
    limits = PictureLimits(person=size * 2 + size // 2, club=size * 4 + size // 2)
    with world_with(database_url, tmp_path, limits) as world:
        mine = world.a.get(f"{API}/storage").json()
        assert mine == {
            "used": 0,
            "limit": limits.person,
            "club": False,
            "pictures": 0,
            "backgrounds": False,
            "over_free": False,
            "paid_blocks": 0,
            "price_per_gb": 20,
            "unpaid": False,
        }
        car = world.vehicle()
        for _ in range(2):
            added(upload(world, car, photo()))
        full = upload(world, car, photo())
        assert problem(full) == (422, "storage_full")
        assert full.json()["message"].startswith("Den fria lagringen på ")
        used = StorageUse.model_validate(world.a.get(f"{API}/storage").json())
        assert (used.used, used.pictures, used.club) == (size * 2, 2, False)

        # B is the club's administrator: the club's fleet counts against the club's 2 GB.
        world.id.roles[(B, CLUB)] = "admin"
        world.id.clubs.add(CLUB)
        assert world.b.get(f"{API}/fleets").status_code == 200  # the club gets an owner row
        in_club = world.vehicle(world.b, CLUB)
        for _ in range(4):
            added(upload(world, in_club, photo(), client=world.b, fleet=CLUB))
        refused = upload(world, in_club, photo(), client=world.b, fleet=CLUB)
        assert problem(refused) == (422, "storage_full")
        assert refused.json()["message"].startswith("Klubbens fria lagring på ")
        club = world.b.get(_in(f"{API}/storage", CLUB)).json()
        assert club == {
            "used": size * 4,
            "limit": limits.club,
            "club": True,
            "pictures": 4,
            "backgrounds": False,
            "over_free": False,
            "paid_blocks": 0,
            "price_per_gb": 20,
            "unpaid": False,
        }
        assert world.b.get(f"{API}/storage").json()["used"] == 0  # not B's own

    # The real free level: 100 MB for a person, 2 GB for a club.
    assert (PictureLimits().person, PictureLimits().club) == (100 * 1024**2, 2 * 1024**3)


def test_an_editor_stores_with_the_owner_within_the_owners_limit(
    database_url: str, tmp_path: Path
) -> None:
    """CAT-133: the pictures are the owner's, under the owner's id, in the owner's storage."""
    size = prepare(photo()).size
    with world_with(database_url, tmp_path, PictureLimits(person=size * 2)) as world:
        car = world.vehicle()
        world.id.roles[(B, A)] = "editor"
        picture = added(upload(world, car, photo(), client=world.b, fleet=A))
        assert all(path.parent.name == A for path in world.stored())
        assert world.a.get(f"{API}/storage").json()["used"] == size
        assert world.b.get(_in(f"{API}/storage", A)).json()["used"] == size
        assert world.b.get(f"{API}/storage").json()["used"] == 0
        with psycopg.connect(database_url) as conn:
            row = conn.execute("SELECT owner_id, uploaded_by FROM picture").fetchone()
        assert row is not None and (str(row[0]), str(row[1])) == (A, B)
        # The owner's limit counts, also for the one the fleet is shared with.
        added(upload(world, car, photo()))
        assert problem(upload(world, car, photo(), client=world.b, fleet=A)) == (
            422,
            "storage_full",
        )
        # The editor chooses and removes too.
        assert world.b.post(_in(f"{API}/vehicles/{car}/pictures/{picture.id}/main", A)).is_success
        assert world.b.delete(_in(f"{API}/vehicles/{car}/pictures/{picture.id}", A)).is_success


def test_a_viewer_sees_the_pictures_but_changes_nothing(world: World) -> None:
    car = world.vehicle()
    picture = added(upload(world, car, photo()))
    world.id.roles[(B, A)] = "viewer"

    seen = world.b.get(_in(f"{API}/vehicles/{car}/pictures", A))
    assert seen.status_code == 200
    assert [p["id"] for p in seen.json()] == [str(picture.id)]
    assert fetched(world, seen.json()[0]["thumb_url"]).format == "JPEG"
    listed = world.b.get(_in(f"{API}/vehicles", A)).json()["vehicles"][0]
    assert listed["picture"]["thumb_url"] == picture.thumb_url  # the same address for a while
    assert world.b.get(_in(f"{API}/vehicles/{car}", A)).json()["picture"] is not None
    assert world.b.get(_in(f"{API}/storage", A)).status_code == 200
    for answer in (
        upload(world, car, photo(), client=world.b, fleet=A),
        world.b.post(_in(f"{API}/vehicles/{car}/pictures/{picture.id}/main", A)),
        world.b.delete(_in(f"{API}/vehicles/{car}/pictures/{picture.id}", A)),
    ):
        assert problem(answer) == (403, "forbidden")
    # Someone the fleet is not shared with sees nothing, and is not told it is there.
    del world.id.roles[(B, A)]
    assert world.b.get(_in(f"{API}/vehicles/{car}/pictures", A)).status_code == 404
    assert world.b.get(f"{API}/vehicles/{car}/pictures").status_code == 404
    assert world.nobody.get(f"{API}/vehicles/{car}/pictures").status_code == 401


# --- The main picture (CAT-125) ------------------------------------------------------------


def test_the_first_is_main_another_can_be_chosen_and_removing_it_promotes_the_next(
    world: World, database_url: str
) -> None:
    car = world.vehicle()
    first, second, third = (
        added(upload(world, car, photo(color=(i * 60, 0, 0)))) for i in (1, 2, 3)
    )
    assert [p.main for p in (first, second, third)] == [True, False, False]
    assert [p.position for p in (first, second, third)] == [0, 1, 2]
    vehicle = Vehicle.model_validate(world.a.get(f"{API}/vehicles/{car}").json())
    assert vehicle.picture is not None and vehicle.picture.thumb_url == first.thumb_url

    chosen = world.a.post(f"{API}/vehicles/{car}/pictures/{third.id}/main")
    assert chosen.status_code == 200
    assert [(p["id"], p["main"]) for p in chosen.json()] == [
        (str(first.id), False),
        (str(second.id), False),
        (str(third.id), True),
    ]
    listed = world.a.get(f"{API}/vehicles").json()["vehicles"][0]
    assert listed["picture"]["display_url"] == third.display_url

    # Removing the main picture makes the first of the rest the main one.
    assert world.a.delete(f"{API}/vehicles/{car}/pictures/{third.id}").status_code == 200
    left = world.a.get(f"{API}/vehicles/{car}/pictures").json()
    assert [(p["id"], p["main"]) for p in left] == [(str(first.id), True), (str(second.id), False)]
    assert world.a.delete(f"{API}/vehicles/{car}/pictures/{second.id}").status_code == 200
    assert [p["main"] for p in world.a.get(f"{API}/vehicles/{car}/pictures").json()] == [True]
    assert len(world.stored()) == 2  # the removed pictures' files are gone
    gone = world.a.delete(f"{API}/vehicles/{car}/pictures/{second.id}")
    assert problem(gone) == (404, "not_found")

    # The database keeps it to one main picture per vehicle.
    added(upload(world, car, photo()))
    with psycopg.connect(database_url) as conn, pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("UPDATE picture SET is_main = true WHERE vehicle_id = %s", (car,))
    # A vehicle without pictures has none in the list.
    world.vehicle()
    pictures = [v["picture"] for v in world.a.get(f"{API}/vehicles").json()["vehicles"]]
    assert sorted(p is None for p in pictures) == [False, True]


# --- Removing, and the files that go with it -------------------------------------------------


def test_removing_a_vehicle_or_an_owner_deletes_the_files(world: World, database_url: str) -> None:
    car = world.vehicle()
    added(upload(world, car, photo()))
    added(upload(world, car, photo(), keep_original=True))
    assert len(world.stored()) == 5
    version = world.a.get(f"{API}/vehicles/{car}").json()["version"]
    assert world.a.delete(f"{API}/vehicles/{car}?version={version}").status_code == 200
    assert world.stored() == []

    # An owner removed in ID: the pictures go with the fleet, through the trash and the sweep.
    added(upload(world, world.vehicle(), photo()))
    assert len(world.stored()) == 2
    fleet = Fleet(world.pictures.db)
    assert fleet.remove_owners([UUID(A)]) == 1
    assert world.pictures.sweep() == 2
    assert world.stored() == []
    with psycopg.connect(database_url) as conn:
        assert conn.execute("SELECT count(*) FROM picture_trash").fetchone() == (0,)


def test_a_signed_address_that_has_expired_or_was_changed_is_refused(world: World) -> None:
    """CAT-130: the files are private; the signature and its expiry are the right."""
    car = world.vehicle()
    picture = added(upload(world, car, photo()))
    good = world.nobody.get(picture.display_url)
    assert good.status_code == 200 and good.headers["content-type"] == "image/jpeg"
    cache = good.headers["cache-control"]
    assert cache.startswith("private, max-age=")
    assert LINK_LIFETIME // 2 - 5 <= int(cache.rsplit("=", 1)[1]) <= LINK_LIFETIME

    path, query = picture.display_url.split("?", 1)
    other_path = picture.thumb_url.split("?", 1)[0]
    signature = parse_qs(query)["sig"][0]
    flipped = signature[:-1] + ("0" if signature[-1] != "0" else "1")
    store = world.pictures.store
    assert isinstance(store, DiskStore)
    key = path.rsplit("/file/", 1)[1]
    expired = store.url(key, now=time.time() - 2 * LINK_LIFETIME)
    for refused in (
        f"{path}?{query.replace(signature, flipped)}",
        f"{other_path}?{query}",  # another file with this signature
        f"{path}?expires=9999999999&sig={signature}",  # a later expiry, not signed
        f"{path}?expires=abc&sig={signature}",
        path,
        expired,
    ):
        assert world.nobody.get(refused).status_code == 403, refused
    assert world.nobody.get(f"{API}/pictures/file/../../etc/passwd?sig=x").status_code in (403, 404)


def test_two_uploads_at_the_edge_never_both_get_in(world: World, database_url: str) -> None:
    """CAT-131: the owner's row is locked first, so two uploads at once cannot both pass the
    limit. Both have stored their files when they meet the lock; the loser's files go."""
    car = UUID(world.vehicle())
    data = photo()
    size = prepare(data).size
    inner = world.pictures.store
    assert isinstance(inner, DiskStore)
    meet = threading.Barrier(2, timeout=10)

    class Together:
        """Each file waits for the other upload's, so both are stored before either is saved."""

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

    pictures = Pictures(world.pictures.db, Together(), PictureLimits(person=size + size // 2))
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
    winners = [r for r in results if isinstance(r, Picture)]
    losers = [r for r in results if isinstance(r, Refused)]
    assert len(winners) == 1 and len(losers) == 1
    assert losers[0].code is ProblemCode.STORAGE_FULL
    assert len(world.stored()) == 2  # only the winner's files
    with psycopg.connect(database_url) as conn:
        assert conn.execute("SELECT count(*) FROM picture").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM picture_trash").fetchone() == (0,)


def test_an_upload_the_store_fails_leaves_nothing_behind(world: World, database_url: str) -> None:
    car = UUID(world.vehicle())
    inner = world.pictures.store
    assert isinstance(inner, DiskStore)

    class FailsSecond:
        def __init__(self) -> None:
            self.puts = 0

        def put(self, key: str, content: bytes, content_type: str = "image/jpeg") -> None:
            self.puts += 1
            if self.puts == 2:
                raise StoreFailed("nere")
            inner.put(key, content, content_type)

        def get(self, key: str) -> bytes:
            return inner.get(key)

        def size(self, key: str) -> int:
            return inner.size(key)

        def delete(self, key: str) -> None:
            inner.delete(key)

        def url(self, key: str, now: float | None = None) -> str:
            return inner.url(key, now)

    pictures = Pictures(world.pictures.db, FailsSecond())
    with pytest.raises(Refused) as refused:
        pictures.add(UUID(A), car, photo(), keep_original=False, uploaded_by=UUID(A), club=False)
    assert (refused.value.status, refused.value.code) == (503, ProblemCode.UNAVAILABLE)
    assert world.stored() == []
    with psycopg.connect(database_url) as conn:
        assert conn.execute("SELECT count(*) FROM picture").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM picture_trash").fetchone() == (0,)


def test_an_upload_that_stopped_halfway_is_swept_when_it_is_due(
    world: World, database_url: str
) -> None:
    """An upload marks its files before it stores them. If it never gets to save the picture,
    even when the process stops, the sweep deletes the files once the mark is due."""
    key = new_key(UUID(A))
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "INSERT INTO picture_trash (key, due_at) VALUES (%s, now() + interval '1 hour')",
            (key,),
        )
    world.pictures.store.put(key, photo())
    assert world.pictures.sweep() == 0  # not yet due: the upload may still be running
    with psycopg.connect(database_url) as conn:
        conn.execute("UPDATE picture_trash SET due_at = now()")
    assert world.pictures.sweep() == 1
    assert world.stored() == []


def test_keep_original_stores_and_counts_the_original(world: World) -> None:
    """Spara original (CAT-17, CAT-126): the original too, without metadata, in the storage."""
    car = world.vehicle()
    plain = added(upload(world, car, photo((2400, 1600))))
    assert plain.original_url is None and (plain.width, plain.height) == (1800, 1200)
    kept = added(upload(world, car, photo((2400, 1600)), keep_original=True))
    assert kept.original_url is not None
    original = fetched(world, kept.original_url)
    assert original.size == (2400, 1600) and dict(original.getexif()) == {}
    files = {p.name: p.stat().st_size for p in world.stored()}
    assert len(files) == 5
    assert kept.bytes > plain.bytes
    assert sum(files.values()) == plain.bytes + kept.bytes
    use = world.a.get(f"{API}/storage").json()
    assert (use["used"], use["pictures"]) == (plain.bytes + kept.bytes, 2)


# --- Object Storage (CAT-130) --------------------------------------------------------------


def test_object_storage_signs_its_requests_and_presigns_the_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200 if request.method == "PUT" else 204)

    http = httpx.Client(transport=httpx.MockTransport(answer))
    store = S3Store("https://s3.nl-ams.scw.cloud", "tm-bilder", "nl-ams", "SCWAKEY", "hemlig", http)
    assert "hemlig" not in repr(store) and "SCWAKEY" not in repr(store)
    key = new_key(UUID(A))
    store.put(key, b"jpeg")
    store.delete(key)
    put, delete = seen
    assert (put.method, str(put.url)) == ("PUT", f"https://s3.nl-ams.scw.cloud/tm-bilder/{key}")
    assert (delete.method, delete.url) == ("DELETE", put.url)
    assert put.content == b"jpeg" and put.headers["content-type"] == "image/jpeg"
    assert put.headers["x-amz-content-sha256"] == hashlib.sha256(b"jpeg").hexdigest()
    for request in (put, delete):
        auth = request.headers["authorization"]
        assert auth.startswith("AWS4-HMAC-SHA256 Credential=SCWAKEY/")
        assert "/nl-ams/s3/aws4_request" in auth and "Signature=" in auth
        assert "hemlig" not in auth
        signed = auth.split("SignedHeaders=", 1)[1].split(",", 1)[0].split(";")
        assert {"host", "x-amz-date", "x-amz-content-sha256"} <= set(signed)
        assert all(name in request.headers for name in signed)

    now = 1_795_000_000.0
    url = store.url(key, now)
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert (parts.scheme, parts.netloc, parts.path) == (
        "https",
        "s3.nl-ams.scw.cloud",
        f"/tm-bilder/{key}",
    )
    assert query["X-Amz-Expires"] == ["3600"] and query["X-Amz-Signature"][0]
    assert query["X-Amz-Credential"][0].startswith("SCWAKEY/") and "hemlig" not in url
    assert store.url(key, now + 60) == url  # the same address for a while, for the browser
    assert store.url(key, now + LINK_LIFETIME) != url
    # Exactly the address botocore makes when it signs at the start of the half hour.
    start = datetime.fromtimestamp(signed_at(now), UTC).replace(tzinfo=None)
    monkeypatch.setattr(botocore.auth, "get_current_datetime", lambda *_, **__: start)
    plain = AWSRequest(method="GET", url=f"https://s3.nl-ams.scw.cloud/tm-bilder/{key}")
    S3SigV4QueryAuth(Credentials("SCWAKEY", "hemlig"), "s3", "nl-ams", expires=3600).add_auth(plain)
    assert url == plain.url


def test_object_storage_reads_back_a_file_and_tells_its_size() -> None:
    """A new background is made from the kept photo (CAT-128): fetched with a signed GET, and
    the original's size read with a signed HEAD, without fetching it."""
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "saknas" in request.url.path:
            return httpx.Response(404)
        if request.method == "HEAD":
            return httpx.Response(200, headers={"Content-Length": "1234"})
        return httpx.Response(200, content=b"fotot")

    http = httpx.Client(transport=httpx.MockTransport(answer))
    store = S3Store("https://s3.nl-ams.scw.cloud", "tm-bilder", "nl-ams", "SCWAKEY", "hemlig", http)
    key = new_key(UUID(A), "image/png")
    assert key.endswith(".png")
    assert store.get(key) == b"fotot"
    assert store.size(key) == 1234
    assert [(r.method, r.url.path) for r in seen] == [
        ("GET", f"/tm-bilder/{key}"),
        ("HEAD", f"/tm-bilder/{key}"),
    ]
    for request in seen:
        assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=SCWAKEY/")
    missing = f"{A}/saknas"
    with pytest.raises(StoreFailed):
        store.get(missing)
    with pytest.raises(StoreFailed):
        store.size(missing)


def test_object_storage_that_says_no_or_does_not_answer_fails(world: World) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="AccessDenied")

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nere", request=request)

    for handler in (refuse, down):
        http = httpx.Client(transport=httpx.MockTransport(handler))
        store = S3Store("https://s3.fr-par.scw.cloud", "b-1", "fr-par", "AK", "SK", http)
        with pytest.raises(StoreFailed):
            store.put(new_key(UUID(A)), b"x")
        with pytest.raises(StoreFailed):
            store.delete(new_key(UUID(A)))
        pictures = Pictures(world.pictures.db, store)
        with pytest.raises(Refused) as refused:
            pictures.add(
                UUID(A),
                UUID(world.vehicle()),
                photo(),
                keep_original=False,
                uploaded_by=UUID(A),
                club=False,
            )
        assert refused.value.status == 503


# --- The settings, and the browser's rules for where pictures come from ----------------------


def test_object_storage_is_set_from_the_environment_and_its_keys_are_never_shown(
    tmp_path: Path,
) -> None:
    keys = tmp_path / "s3-nycklar"
    keys.write_text("SCWAKEY\nzq-SECRET-9\n")
    base = {"CATALOG_DATABASE_URL": "postgresql://db/catalog"}
    disk = from_env({**base, "CATALOG_PICTURES_DIR": str(tmp_path / "bilder")})
    assert (disk.pictures_s3, disk.pictures_dir) == (None, tmp_path / "bilder")
    s3_env = {
        **base,
        "CATALOG_PICTURES_S3_ENDPOINT": "https://s3.nl-ams.scw.cloud",
        "CATALOG_PICTURES_S3_BUCKET": "tm-bilder",
        "CATALOG_PICTURES_S3_REGION": "nl-ams",
        "CATALOG_PICTURES_S3_KEY_FILE": str(keys),
    }
    settings = from_env(s3_env)
    s3 = settings.pictures_s3
    assert s3 is not None
    assert (s3.endpoint, s3.bucket, s3.region, s3.origin) == (
        "https://s3.nl-ams.scw.cloud",
        "tm-bilder",
        "nl-ams",
        "https://s3.nl-ams.scw.cloud",
    )
    assert (s3.access_key, s3.secret_key) == ("SCWAKEY", "zq-SECRET-9")
    for shown in (repr(settings), repr(s3), str(s3)):
        assert "zq-SECRET-9" not in shown and "SCWAKEY" not in shown
    without_region = {k: v for k, v in s3_env.items() if k != "CATALOG_PICTURES_S3_REGION"}
    default = from_env(without_region).pictures_s3
    assert default is not None and default.region == "fr-par"

    one_line = tmp_path / "en-rad"
    one_line.write_text("zq-SECRET-9\n")
    for wrong, name in (
        ({"CATALOG_PICTURES_S3_KEY_FILE": ""}, "CATALOG_PICTURES_S3_KEY_FILE"),
        ({"CATALOG_PICTURES_S3_KEY_FILE": str(tmp_path / "saknas")}, "KEY_FILE"),
        ({"CATALOG_PICTURES_S3_KEY_FILE": str(one_line)}, "KEY_FILE"),
        ({"CATALOG_PICTURES_S3_BUCKET": ""}, "CATALOG_PICTURES_S3_BUCKET"),
        ({"CATALOG_PICTURES_S3_REGION": "Amsterdam"}, "CATALOG_PICTURES_S3_REGION"),
        ({"CATALOG_PICTURES_S3_ENDPOINT": "http://s3.nl-ams.scw.cloud"}, "ENDPOINT"),
        ({"CATALOG_PICTURES_S3_ENDPOINT": "https://s3.nl-ams.scw.cloud/x"}, "ENDPOINT"),
    ):
        with pytest.raises(SettingsError, match=name) as error:
            from_env({**s3_env, **wrong})
        assert "zq-SECRET-9" not in str(error.value)


def test_the_browser_may_fetch_pictures_only_from_object_storages_own_origin(
    database_url: str, tmp_path: Path
) -> None:
    """Without Object Storage the pictures come from Catalog itself; with it, from exactly the
    endpoint's origin, and nowhere else."""
    plain = Settings(database_url=database_url, migrate="auto", web_dir=tmp_path)
    with TestClient(create_app(plain)) as client:
        assert client.get("/fordon").headers["content-security-policy"] == CONTENT_SECURITY_POLICY
        assert "img-src 'self' data: blob:;" in CONTENT_SECURITY_POLICY

    for endpoint, origin in (
        ("https://s3.nl-ams.scw.cloud", "https://s3.nl-ams.scw.cloud"),
        ("http://localhost:9000", "http://localhost:9000"),
    ):
        s3 = S3Settings(endpoint=endpoint, bucket="tm-bilder", region="nl-ams")
        with_s3 = Settings(
            database_url=database_url, migrate="auto", web_dir=tmp_path, pictures_s3=s3
        )
        with TestClient(create_app(with_s3)) as client:
            policy = client.get("/fordon").headers["content-security-policy"]
            assert policy == content_security_policy(origin)
            assert f"img-src 'self' data: blob: {origin};" in policy
            assert "*" not in policy and policy.count(origin) == 1
            # The disk's files are not served when the pictures are in Object Storage.
            assert client.get(f"{API}/pictures/file/x/y.jpg").status_code == 404


def test_the_pictures_take_no_more_than_their_share_of_a_shared_fleets_answer(
    world: World,
) -> None:
    """The tag and the messages stay hidden from the others; the picture does not (CAT-47)."""
    car = world.vehicle()
    tag = world.a.post(f"{API}/tags/simulated").json()["uid"]
    world.a.post(f"{API}/tags/{tag}/link", json={"vehicle": car, "confirm": True})
    added(upload(world, car, photo()))
    world.id.roles[(B, A)] = "viewer"
    seen: dict[str, Any] = world.b.get(_in(f"{API}/vehicles/{car}", A)).json()
    assert (seen["tags"], seen["tagged"]) == ([], True)
    assert seen["picture"]["thumb_url"].startswith(f"{API}/pictures/file/{A}/")
