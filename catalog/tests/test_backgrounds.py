"""Friläggningen (CAT-18, CAT-127–CAT-129): the five backgrounds, the crop around the vehicle,
the vehicle's colours from the photo alone, and a new background without a new upload.

A pretend segmenter stands in for the model: it finds what differs from the photo's corner,
which in these synthetic photos is a coloured block, the vehicle, on a plain field. One test
runs the real U2NetP when CATALOG_BACKGROUND_MODEL points at it, and is skipped otherwise.
"""

from __future__ import annotations

import io
import logging
import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import numpy as np
import psycopg
import pytest
from PIL import Image, ImageDraw

from catalog.backgrounds import (
    FILL_HEIGHT,
    FILL_WIDTH,
    GREY,
    RATIO,
    U2NetP,
    backgrounds_off,
    crop_box,
    render,
    subject_box,
)
from catalog.fleet import Refused
from catalog.pictures import DiskStore, PictureLimits, Pictures, prepare
from catalog.settings import DEFAULT_BACKGROUND_MODEL, from_env
from catalog.tests.test_pictures import API, World, _in, added, fetched, problem, world_with
from catalog.tests.test_sharing import A, B
from contracts.catalog import Picture, PictureBackground, ProblemCode, StorageUse

BLOCK = (180, 40, 40)
FIELD = (70, 140, 90)
SIZE = (480, 360)
LONG = (100, 160, 340, 220)
"""A long vehicle, 240×60, as (left, top, right, bottom)."""
TALL = (200, 60, 260, 300)
"""A tall one, 60×240."""
ORIGINAL, WHITE, GREY_, TRANSPARENT, RAILS = (
    PictureBackground.ORIGINAL,
    PictureBackground.WHITE,
    PictureBackground.GREY,
    PictureBackground.TRANSPARENT,
    PictureBackground.RAILS,
)


@dataclass
class PretendSegmenter:
    """The model's stand-in: the mask is what differs clearly from the photo's corner."""

    on: bool = True
    calls: int = 0

    def available(self) -> bool:
        return self.on

    def segment(self, image: Image.Image) -> Image.Image:
        if not self.on:
            raise backgrounds_off()
        self.calls += 1
        rgb = np.asarray(image.convert("RGB"), dtype=np.int32)
        differs = np.abs(rgb - rgb[0, 0]).sum(axis=2) > 60
        return Image.fromarray((differs * 255).astype(np.uint8))


def scene(
    size: tuple[int, int] = SIZE, block: tuple[int, int, int, int] = LONG, pattern: bool = False
) -> Image.Image:
    """A plain field with the block on it. With pattern, every pixel of the block differs."""
    photo = Image.new("RGB", size, FIELD)
    left, top, right, bottom = block
    ImageDraw.Draw(photo).rectangle((left, top, right - 1, bottom - 1), fill=BLOCK)
    if pattern:
        for y in range(top, bottom):
            for x in range(left, right):
                photo.putpixel((x, y), (120 + (x * 7) % 120, 20 + (y * 13) % 60, (x + y) % 50))
    return photo


def mask_of(size: tuple[int, int] = SIZE, block: tuple[int, int, int, int] = LONG) -> Image.Image:
    mask = Image.new("L", size, 0)
    left, top, right, bottom = block
    ImageDraw.Draw(mask).rectangle((left, top, right - 1, bottom - 1), fill=255)
    return mask


def png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def close(colour: object, expected: tuple[int, ...], tolerance: int = 6) -> bool:
    assert isinstance(colour, tuple)
    return all(abs(a - b) <= tolerance for a, b in zip(colour, expected, strict=False))


def on_disk(world: World) -> dict[str, int]:
    """Every stored file, by key, with its size."""
    return {
        str(path.relative_to(world.files)): path.stat().st_size
        for path in world.files.rglob("*")
        if path.is_file()
    }


def key_of(url: str) -> str:
    return urlsplit(url).path.rsplit("/file/", 1)[1]


def send(
    world: World,
    vehicle: str,
    data: bytes,
    background: str | None = None,
    client: httpx.Client | None = None,
    fleet: str | None = None,
) -> httpx.Response:
    path = f"{API}/vehicles/{vehicle}/pictures"
    if background is not None:
        path += f"?background={background}"
    answer: httpx.Response = (client or world.a).post(
        _in(path, fleet), content=data, headers={"Content-Type": "image/png"}
    )
    return answer


def change(
    world: World,
    vehicle: str,
    picture: UUID,
    background: str,
    client: httpx.Client | None = None,
    fleet: str | None = None,
) -> httpx.Response:
    path = f"{API}/vehicles/{vehicle}/pictures/{picture}/background"
    answer: httpx.Response = (client or world.a).post(
        _in(path, fleet), json={"background": background}
    )
    return answer


def used(world: World) -> StorageUse:
    return StorageUse.model_validate(world.a.get(f"{API}/storage").json())


def trash(database_url: str) -> int:
    with psycopg.connect(database_url) as conn:
        row = conn.execute("SELECT count(*) FROM picture_trash").fetchone()
    assert row is not None
    return int(row[0])


@pytest.fixture
def pretend() -> PretendSegmenter:
    return PretendSegmenter()


@pytest.fixture
def world(database_url: str, tmp_path: Path, pretend: PretendSegmenter) -> Iterator[World]:
    with world_with(database_url, tmp_path, segmenter=pretend) as made:
        yield made


# --- The backgrounds and the crop, without a server (CAT-128, CAT-129) -----------------------


def test_the_five_backgrounds() -> None:
    photo, mask = scene(), mask_of()
    shown = {background: render(photo, mask, background) for background in PictureBackground}
    assert {b: image.mode for b, image in shown.items()} == {
        ORIGINAL: "RGB",
        WHITE: "RGB",
        GREY_: "RGB",
        TRANSPARENT: "RGBA",
        RAILS: "RGB",
    }
    for background, image in shown.items():
        window = crop_box(mask, inside=background is ORIGINAL)
        assert window is not None
        middle = image.getpixel((220 - window[0], 190 - window[1]))  # the block's middle
        assert isinstance(middle, tuple) and middle[:3] == BLOCK, background
    assert shown[ORIGINAL].getpixel((0, 0)) == FIELD  # the photo's own background
    assert shown[WHITE].getpixel((0, 0)) == (255, 255, 255)
    assert shown[GREY_].getpixel((0, 0)) == GREY
    assert shown[TRANSPARENT].getpixel((0, 0)) == (0, 0, 0, 0)
    for background in (WHITE, GREY_, TRANSPARENT, RAILS):
        rgb = np.asarray(shown[background])[..., :3]
        assert not (rgb == FIELD).all(axis=-1).any(), background  # none of the photo's

    # Räls: a sky above, and the near rail under the vehicle, the whole width across.
    rails = shown[RAILS]
    vehicle = subject_box(shown[TRANSPARENT].getchannel("A"))
    assert vehicle is not None
    ground = vehicle[3]
    steel = {rails.getpixel((x, ground)) for x in (0, 3, rails.width - 1)}
    assert len(steel) == 1
    (rail,) = steel
    assert isinstance(rail, tuple) and max(rail) - min(rail) <= 8 and 90 < rail[0] < 230
    sky = rails.getpixel((0, 0))
    assert isinstance(sky, tuple) and sky[2] > sky[0]  # bluish
    assert len(rails.getcolors(1 << 20) or []) > 10  # drawn, not one colour


def test_the_crop_centres_the_vehicle_and_fills_the_picture() -> None:
    """CAT-129: a long vehicle fills 95 % of the width, a tall one 86 % of the height, in a 3:2
    picture; the vehicle stands in the middle, a little below for the ground."""
    for block, fills in ((LONG, (FILL_WIDTH, None)), (TALL, (None, FILL_HEIGHT))):
        shown = render(scene(block=block), mask_of(block=block), TRANSPARENT)
        width, height = shown.size
        assert abs(width / height - RATIO) < 0.01
        found = subject_box(shown.getchannel("A"))
        assert found is not None
        left, top, right, bottom = found
        assert (right - left, bottom - top) == (block[2] - block[0], block[3] - block[1])
        assert abs((left + right) / 2 - width / 2) <= 1
        assert abs((top + bottom) / 2 - 0.53 * height) <= 1.5
        if fills[0] is not None:
            assert abs((right - left) / width - fills[0]) < 0.01
        if fills[1] is not None:
            assert abs((bottom - top) / height - fills[1]) < 0.01

    # A large photo is made smaller, and keeps the crop.
    big, wide = (4000, 3000), (1000, 1500, 3000, 2000)
    large = render(scene(big, wide), mask_of(big, wide), WHITE)
    assert large.width == 1800 and abs(large.width / large.height - RATIO) < 0.01

    # The original background is cut within the photo. A vehicle near its edge: the box is
    # moved into the photo rather than past it, while the vehicle keeps its margin.
    near = (4, 150, 244, 210)
    window = crop_box(mask_of(block=near), inside=True)
    assert window is not None and window[0] == 0 and window[2] <= SIZE[0]
    original = render(scene(block=near), mask_of(block=near), ORIGINAL)
    assert abs(original.width / original.height - RATIO) < 0.01
    # At the very edge there is nothing more to show: cut short, nothing made up.
    at = (0, 150, 240, 210)
    short = render(scene(block=at), mask_of(block=at), ORIGINAL)
    assert short.width < round(short.height * RATIO)
    for shown in (original, short):
        assert {c for _, c in shown.getcolors(1 << 20) or []} == {FIELD, BLOCK}
    # Without a mask, the photo as it is.
    assert render(scene(), None, ORIGINAL).size == SIZE


def test_the_vehicles_colours_come_only_from_the_photo() -> None:
    """CAT-127: nothing of the vehicle is generated; every pixel of it is the photo's own."""
    photo, mask = scene(pattern=True), mask_of()
    window = crop_box(mask)
    assert window is not None
    x0, y0 = window[:2]
    left, top, right, bottom = LONG
    source = np.asarray(photo)[top:bottom, left:right]
    for background in (WHITE, GREY_, TRANSPARENT, RAILS):
        shown = np.asarray(render(photo, mask, background).convert("RGB"))
        here = shown[top - y0 : bottom - y0, left - x0 : right - x0]
        assert (here == source).all(), background
    # Transparent: what can be seen at all is the photo at the same place.
    seen = np.asarray(render(photo, mask, TRANSPARENT))
    visible = seen[..., 3] > 0
    ys, xs = np.nonzero(visible)
    assert (seen[ys, xs, :3] == np.asarray(photo)[ys + y0, xs + x0]).all()


def test_no_clear_vehicle_is_refused_for_a_new_background() -> None:
    plain = Image.new("RGB", SIZE, FIELD)
    empty = Image.new("L", SIZE, 0)
    for background in (WHITE, TRANSPARENT, RAILS):
        with pytest.raises(Refused) as refused:
            render(plain, empty, background)
        assert (refused.value.status, refused.value.code) == (422, ProblemCode.NO_VEHICLE)
    assert render(plain, empty, ORIGINAL).size == SIZE
    # A speck is not a vehicle.
    speck = Image.new("L", SIZE, 0)
    speck.putpixel((10, 10), 255)
    assert subject_box(speck) is None


# --- The model (CAT-18, CAT-127) ----------------------------------------------------------------


def test_a_model_that_is_missing_or_not_u2netp_is_not_used(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    other = tmp_path / "u2netp.onnx"
    other.write_bytes(b"inte modellen")
    with caplog.at_level(logging.WARNING, logger="catalog.backgrounds"):
        for segmenter in (U2NetP(other), U2NetP(tmp_path / "saknas.onnx")):
            assert not segmenter.available()
            with pytest.raises(Refused) as refused:
                segmenter.segment(scene())
            assert (refused.value.status, refused.value.code) == (503, ProblemCode.BACKGROUNDS_OFF)
            assert "Original" in refused.value.message
    assert "fel SHA-256" in caplog.text and "finns inte" in caplog.text
    assert "inte modellen" not in caplog.text


def test_the_model_is_set_in_the_environment() -> None:
    base = {"CATALOG_DATABASE_URL": "postgresql://db/catalog"}
    assert (
        from_env(base).background_model
        == DEFAULT_BACKGROUND_MODEL
        == Path("/app/models/u2netp.onnx")
    )
    chosen = from_env({**base, "CATALOG_BACKGROUND_MODEL": "/srv/modeller/u2netp.onnx"})
    assert chosen.background_model == Path("/srv/modeller/u2netp.onnx")


MODEL = os.environ.get("CATALOG_BACKGROUND_MODEL", "").strip()


@pytest.mark.skipif(
    not MODEL or not Path(MODEL).is_file(),
    reason="CATALOG_BACKGROUND_MODEL pekar inte på U2NetP: den riktiga modellen provas inte.",
)
def test_the_real_model_finds_a_wagon() -> None:
    photo = Image.new("RGB", (640, 400), (232, 232, 226))
    draw = ImageDraw.Draw(photo)
    draw.rectangle((0, 300, 640, 306), fill=(120, 120, 124))
    draw.rectangle((110, 170, 530, 280), fill=(150, 34, 30))
    for x in range(140, 500, 60):
        draw.rectangle((x, 190, x + 36, 222), fill=(40, 50, 60))
    for x in (170, 230, 410, 470):
        draw.ellipse((x - 22, 262, x + 22, 306), fill=(25, 25, 25))
    segmenter = U2NetP(Path(MODEL))
    assert segmenter.available()
    assert segmenter._load() is segmenter._load()  # loaded once
    mask = segmenter.segment(photo)
    assert (mask.mode, mask.size) == ("L", photo.size)
    seen = np.asarray(mask, dtype=np.float32)
    assert seen[180:270, 120:520].mean() > 200 and seen[:40, :40].mean() < 30
    box = subject_box(mask)
    assert box is not None and box[0] < 130 and box[2] > 510
    shown = render(photo, mask, WHITE)
    assert shown.getpixel((0, 0)) == (255, 255, 255)


# --- At the upload (CAT-128) ------------------------------------------------------------------


def test_an_upload_with_a_background(world: World) -> None:
    car = world.vehicle()
    grey = added(send(world, car, png(scene()), "grey"))
    assert grey.background is GREY_
    shown = fetched(world, grey.display_url)
    assert shown.format == "JPEG" and abs(shown.width / shown.height - RATIO) < 0.01
    assert close(shown.getpixel((0, 0)), GREY, 3)
    assert close(shown.getpixel((shown.width // 2, shown.height // 2)), BLOCK, 12)
    # The display picture, the thumbnail, the kept photo and the mask, all in the storage.
    files = on_disk(world)
    assert sorted(key.rsplit(".", 1)[1] for key in files) == ["jpg", "jpg", "jpg", "png"]
    assert grey.bytes == sum(files.values()) == used(world).used

    # The original background: the photo cut around the vehicle within itself, and its mask.
    before = set(files)
    original = added(send(world, car, png(scene())))
    assert original.background is ORIGINAL
    shown = fetched(world, original.display_url)
    window = crop_box(mask_of(), inside=True)
    assert window is not None and shown.size == (window[2] - window[0], window[3] - window[1])
    assert close(shown.getpixel((0, 0)), FIELD)
    added_files = {k: v for k, v in on_disk(world).items() if k not in before}
    assert sorted(key.rsplit(".", 1)[1] for key in added_files) == ["jpg", "jpg", "png"]
    assert original.bytes == sum(added_files.values())
    assert used(world).backgrounds is True


@dataclass
class Recording:
    """The disk, and what each file was stored as."""

    inner: DiskStore
    puts: list[tuple[str, str]] = field(default_factory=list)

    def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        self.puts.append((key, content_type))
        self.inner.put(key, data, content_type)

    def get(self, key: str) -> bytes:
        return self.inner.get(key)

    def size(self, key: str) -> int:
        return self.inner.size(key)

    def delete(self, key: str) -> None:
        self.inner.delete(key)

    def url(self, key: str, now: float | None = None) -> str:
        return self.inner.url(key, now)


def test_transparency_is_kept_as_webp_with_its_content_type(world: World) -> None:
    car = UUID(world.vehicle())
    inner = world.pictures.store
    assert isinstance(inner, DiskStore)
    recording = Recording(inner)
    pictures = Pictures(world.pictures.db, recording, segmenter=PretendSegmenter())
    picture = pictures.add(
        UUID(A),
        car,
        png(scene()),
        keep_original=True,
        uploaded_by=UUID(A),
        club=False,
        background=TRANSPARENT,
    )
    assert sorted((key.rsplit(".", 1)[1], kind) for key, kind in recording.puts) == [
        ("jpg", "image/jpeg"),  # the original
        ("jpg", "image/jpeg"),  # the kept photo
        ("png", "image/png"),  # the mask
        ("webp", "image/webp"),  # the display picture
        ("webp", "image/webp"),  # the thumbnail
    ]
    for url in (picture.display_url, picture.thumb_url):
        answer = world.nobody.get(url)
        assert answer.status_code == 200 and answer.headers["content-type"] == "image/webp"
        shown = Image.open(io.BytesIO(answer.content))
        assert (shown.format, shown.mode) == ("WEBP", "RGBA")
        assert shown.getpixel((0, 0)) == (0, 0, 0, 0)
        middle = shown.getpixel((shown.width // 2, shown.height // 2))
        assert isinstance(middle, tuple) and middle[3] == 255 and close(middle[:3], BLOCK, 12)
    assert world.nobody.get(picture.original_url or "").headers["content-type"] == "image/jpeg"


def test_without_the_model_only_the_original_can_be_chosen_and_uploads_work(
    world: World, pretend: PretendSegmenter
) -> None:
    pretend.on = False
    assert used(world).backgrounds is False
    car = world.vehicle()
    for background in ("white", "transparent", "rails"):
        refused = send(world, car, png(scene()), background)
        assert problem(refused) == (503, "backgrounds_off")
        assert "Friläggningen" in refused.json()["message"]
    assert on_disk(world) == {}
    picture = added(send(world, car, png(scene())))
    assert picture.background is ORIGINAL
    assert fetched(world, picture.display_url).size == SIZE  # as it is, not cut
    assert len(on_disk(world)) == 2  # no mask without the model
    assert problem(change(world, car, picture.id, "grey")) == (503, "backgrounds_off")
    same = change(world, car, picture.id, "original")
    assert same.status_code == 200 and same.json()["display_url"] == picture.display_url

    # With the model back, a picture without a mask gets one at its first change, and the
    # display picture it had becomes the kept photo.
    pretend.on = True
    white = Picture.model_validate(change(world, car, picture.id, "white").json())
    assert pretend.calls == 1
    files = on_disk(world)
    assert key_of(picture.display_url) in files and key_of(picture.thumb_url) not in files
    assert len(files) == 4 and white.bytes == sum(files.values())


def test_a_photo_without_a_clear_vehicle(world: World) -> None:
    car = world.vehicle()
    plain = png(Image.new("RGB", SIZE, FIELD))
    assert problem(send(world, car, plain, "white")) == (422, "no_vehicle")
    assert on_disk(world) == {}
    kept = added(send(world, car, plain))
    assert fetched(world, kept.display_url).size == SIZE and len(on_disk(world)) == 2


# --- A new background without a new upload (CAT-128) -------------------------------------------


def test_a_background_change_through_the_api(
    world: World, pretend: PretendSegmenter, database_url: str
) -> None:
    car = world.vehicle()
    first = added(send(world, car, png(scene())))
    kept = key_of(first.display_url)  # the original background's picture is the kept photo
    assert len(on_disk(world)) == 3

    answer = change(world, car, first.id, "white")
    assert answer.status_code == 200, answer.text
    white = Picture.model_validate(answer.json())
    assert (white.id, white.main, white.background) == (first.id, True, WHITE)
    assert close(fetched(world, white.display_url).getpixel((0, 0)), (255, 255, 255), 3)
    files = on_disk(world)
    assert kept in files and key_of(first.thumb_url) not in files  # the old thumbnail went
    assert len(files) == 4 and white.bytes == sum(files.values()) == used(world).used
    assert trash(database_url) == 0

    rails = Picture.model_validate(change(world, car, first.id, "rails").json())
    files = on_disk(world)
    assert key_of(white.display_url) not in files and key_of(white.thumb_url) not in files
    assert len(files) == 4 and rails.bytes == sum(files.values()) == used(world).used

    back = Picture.model_validate(change(world, car, first.id, "original").json())
    assert back.background is ORIGINAL and key_of(back.display_url) == kept
    assert (back.width, back.height) == (first.width, first.height)
    files = on_disk(world)
    assert len(files) == 3 and back.bytes == sum(files.values()) == used(world).used
    assert pretend.calls == 1  # the mask from the upload, kept, never made again
    listed = world.a.get(f"{API}/vehicles/{car}/pictures").json()
    assert [p["background"] for p in listed] == ["original"]

    # The right: an editor of the shared fleet may, a viewer may not, and nobody else.
    world.id.roles[(B, A)] = "editor"
    by_editor = change(world, car, first.id, "grey", client=world.b, fleet=A)
    assert by_editor.status_code == 200 and by_editor.json()["background"] == "grey"
    world.id.roles[(B, A)] = "viewer"
    assert problem(change(world, car, first.id, "white", client=world.b, fleet=A)) == (
        403,
        "forbidden",
    )
    del world.id.roles[(B, A)]
    assert problem(change(world, car, first.id, "white", client=world.b)) == (404, "not_found")
    assert (
        world.nobody.post(
            f"{API}/vehicles/{car}/pictures/{first.id}/background", json={"background": "white"}
        ).status_code
        == 401
    )
    missing = change(world, car, UUID(int=7), "white")
    assert problem(missing) == (404, "not_found")
    assert change(world, car, first.id, "sepia").status_code == 422

    # Removed: the kept photo and the mask go with the rest.
    assert world.a.delete(f"{API}/vehicles/{car}/pictures/{first.id}").status_code == 200
    assert on_disk(world) == {} and trash(database_url) == 0


def test_a_change_needs_room_but_one_that_does_not_grow_is_always_possible(
    database_url: str, tmp_path: Path
) -> None:
    pretend = PretendSegmenter()
    data = png(scene())
    original = prepare(data, segmenter=pretend).size
    white = prepare(data, background=WHITE, segmenter=pretend).size
    assert white > original
    limits = PictureLimits(person=original * 2 + (white - original) // 2)
    with world_with(database_url, tmp_path, limits, segmenter=pretend) as world:
        car = world.vehicle()
        first, second = (added(send(world, car, data)) for _ in range(2))
        before = on_disk(world)
        full = change(world, car, first.id, "white")
        assert problem(full) == (422, "storage_full")
        assert on_disk(world) == before and trash(database_url) == 0
        assert world.a.delete(f"{API}/vehicles/{car}/pictures/{second.id}").status_code == 200
        assert change(world, car, first.id, "white").status_code == 200

        # Over the limit, going back to the original makes the picture smaller: always fine.
        world.pictures.limits = PictureLimits(person=1)
        back = change(world, car, first.id, "original")
        assert back.status_code == 200 and back.json()["background"] == "original"
        assert problem(change(world, car, first.id, "grey")) == (422, "storage_full")


def test_two_changes_at_once_leave_one_picture_and_no_stray_files(
    world: World, database_url: str
) -> None:
    """Both store their files, then meet the owner's lock: the second finds the picture
    changed, says so, and its files go."""
    car = world.vehicle()
    picture = added(send(world, car, png(scene())))
    inner = world.pictures.store
    assert isinstance(inner, DiskStore)
    meet = threading.Barrier(2, timeout=10)

    class Together(Recording):
        def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
            super().put(key, data, content_type)
            meet.wait()

    pictures = Pictures(world.pictures.db, Together(inner), segmenter=PretendSegmenter())
    results: list[Picture | Refused] = []

    def to(background: PictureBackground) -> None:
        try:
            results.append(
                pictures.change_background(UUID(A), UUID(car), picture.id, background, club=False)
            )
        except Refused as refused:
            results.append(refused)

    threads = [threading.Thread(target=to, args=(b,)) for b in (WHITE, GREY_)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    winners = [r for r in results if isinstance(r, Picture)]
    losers = [r for r in results if isinstance(r, Refused)]
    assert len(winners) == 1 and len(losers) == 1
    assert (losers[0].status, losers[0].code) == (409, ProblemCode.CHANGED)
    world.pictures.sweep()
    files = on_disk(world)
    assert len(files) == 4 and winners[0].bytes == sum(files.values())
    assert trash(database_url) == 0
