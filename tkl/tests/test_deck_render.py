"""What a real Stream Deck shows (#86 del b): every key type and state drawn at every size the
decks have, a sample compared with stored pictures, the ETag that changes when the face does
and not otherwise, Spårplan's keys with the panel, and the pictures in the API (SD3, SD6).

The stored pictures are in tkl/tests/deck_png/. After a deliberate change of the look, write
them again with TKL_DECK_PNG=skriv and look at them before they are checked in. A made-up
station (provby); nothing here names a real one (RS13).
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops

from contracts.tkl import (
    DeckPlanDrawn,
    TklDeckFace,
    TklDeckStrip,
    TklDeckTile,
    TklDeckView,
)
from tkl import track_plan
from tkl.deck import look, render
from tkl.stallverk import Interlocking, plant_of
from tkl.tests.provstation import provby
from tkl.tests.test_app import API, set_up, tkl
from tkl.tests.test_app_stallverk import with_model

STORED = Path(__file__).with_name("deck_png")
D = API + "/deck"
SIZES = [(s, s) for s in render.SIZES] + [(80, 120), (32, 32), (256, 256)]
"""Every key size of Elgato's decks, Studio's tall keys, and the API's smallest and largest."""
FACE_TYPES = TklDeckFace.model_fields["type"].annotation.__args__  # type: ignore[union-attr]


def faces() -> dict[str, TklDeckFace]:
    """Every key type, and every mark a face can carry: band, frame, dashed frame, line, dot,
    star, chip, bar, dashed bar, blink, small text, the reason in red, Ingen kontakt, the
    clock alone, Spårplan's piece, and the empty key."""
    long = "Spårledningen 12 är belagd av tåg 4501 som väntar"
    made = {
        "empty": look.EMPTY,
        "clock": look.clock("06:10", "Provby"),
        "contact": look.no_contact(),
        "answer": look.refused("V1→2", look.short("Spårledningen 2 är belagd av tåg 9.")),
        "lock": look.LOCK,
        "page": look.tab("Nu", "Tågen", True),
        "train": TklDeckFace(
            type="train",
            top="Ö1 → 2",
            text="102",
            under="väntar · lägg infart",
            bg="#1d1a0b",
            fg="#fde68a",
            frame="#f5c518",
            blink="#3d3208",
            label="Tåg 102",
        ),
        "line": TklDeckFace(
            type="line",
            top="linje",
            text="Nby",
            under="frågar: 102",
            bg="#0f1a2b",
            fg="#bfdbfe",
            frame="#60a5fa",
            dashed=True,
            blink="#1e3a5f",
        ),
        "place": TklDeckFace(
            type="place",
            text="Spår 2",
            chip="102",
            chip_colour="red",
            bg="#000000",
            fg="#f3f4f6",
            bar="#ef4444",
        ),
        "goal": TklDeckFace(
            type="goal",
            text="Spår 3",
            under="planerat",
            small="64 · 33",
            bg="#172a46",
            fg="#f3f4f6",
            frame="#60a5fa",
            bar="#facc15",
            bar_dashed=True,
            star=True,
            chip="4501",
            chip_colour="green",
        ),
        "daily": TklDeckFace(
            type="daily",
            text="V1→2",
            under="belagt",
            bg="#191d21",
            fg="#98a2ad",
            band="#3a424a",
            dot="#ff5a4d",
            dim=True,
        ),
        "favourite": TklDeckFace(
            type="favourite", text="In→12", under="lagd", bg="#15803d", fg="#ffffff", band="#bbf7d0"
        ),
        "next": TklDeckFace(
            type="next", text="▶", under="Dagens vägar", bg="#1e293b", fg="#cbd5e1"
        ),
        "pan": TklDeckFace(
            type="pan",
            text="\N{SINGLE LEFT-POINTING ANGLE QUOTATION MARK} Hela",
            bg="#1e293b",
            fg="#cbd5e1",
        ),
        "mode": TklDeckFace(type="mode", top="Läge", text="Spårplan", bg="#1d2125", fg="#ffffff"),
        "long": TklDeckFace(
            type="case", top=long, text=long, under=long, bg="#1f2937", fg="#ffffff"
        ),
        "shapes": TklDeckFace(type="pan", text="◀ ▲ ▼ ★ ✕", bg="#1e293b", fg="#cbd5e1"),
        "tile": TklDeckFace(
            type="tile",
            bg="#000000",
            fg="#f3f4f6",
            tile=TklDeckTile(x=0, y=0, w=10, h=5, names=["1", "2"], start="In"),
        ),
        "relay": TklDeckFace(
            type="cell",
            bg="#000000",
            fg="#f3f4f6",
            frame="#60a5fa",
            tile=TklDeckTile(x=4, y=0, w=4, h=4, drawn=DeckPlanDrawn.RELAY, chosen=True),
        ),
    }
    for kind in FACE_TYPES:
        made.setdefault(
            f"type-{kind}", TklDeckFace(type=kind, text=kind[:6], under="under", bg="#262b31")
        )
    return made


def picture_of_provby() -> render.Picture:
    model = provby()
    it = Interlocking(plant_of(model))
    targets = it.targets("In")
    it.set_route("In", next(t.end for t in targets.targets if t.possible), None)
    panel = track_plan.panel_of(model)
    assert panel is not None
    return render.picture(panel, it.view())


@pytest.mark.parametrize("size", SIZES, ids=[f"{w}x{h}" for w, h in SIZES])
def test_every_key_type_renders_at_every_size(size: tuple[int, int]) -> None:
    """Drawn at the size asked for, never a bitmap scaled; both colours of a blinking key."""
    found = picture_of_provby()
    w, h = size
    for name, face in faces().items():
        for phase in (0, 1):
            image = render.key(face, w, h, found, phase)
            assert image.size == (w, h) and image.mode == "RGB", name
    inside = (round(w * 0.12), h // 2)
    on = render.key(faces()["train"], w, h, None, 0).getpixel(inside)
    off = render.key(faces()["train"], w, h, None, 1).getpixel(inside)
    assert on != off, "a blinking key has its other colour every other half second"


SAMPLE = {
    "clock-72": ("clock", 72),
    "contact-80": ("contact", 80),
    "answer-72": ("answer", 72),
    "train-96": ("train", 96),
    "goal-120": ("goal", 120),
    "daily-72": ("daily", 72),
    "next-80": ("next", 80),
    "tile-96": ("tile", 96),
}


def different(a: Image.Image, b: Image.Image) -> float:
    """The share of pixels that differ clearly: fonts may be smoothed a little differently
    from one computer to the next, the drawing may not."""
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
    clear = sum(diff.histogram()[49:])
    return clear / (a.width * a.height)


@pytest.mark.parametrize("name", sorted(SAMPLE))
def test_a_sample_looks_as_stored(name: str) -> None:
    kind, size = SAMPLE[name]
    image = render.key(faces()[kind], size, size, picture_of_provby(), 0)
    path = STORED / f"{name}.png"
    if os.environ.get("TKL_DECK_PNG") == "skriv":
        STORED.mkdir(exist_ok=True)
        image.save(path, optimize=True)
    stored = Image.open(path)
    assert stored.size == image.size
    assert different(stored, image) < 0.02, f"{name} looks different from {path.name}"


def test_the_etag_changes_with_the_face_and_not_otherwise() -> None:
    face = faces()["goal"]
    tag = render.key_etag(face, 72, 72, 0)
    assert tag == render.key_etag(face.model_copy(), 72, 72, 0)
    assert tag == render.key_etag(face, 72, 72, 1), "the phase matters only when it blinks"
    assert tag != render.key_etag(face.model_copy(update={"under": "ledigt"}), 72, 72, 0)
    assert tag != render.key_etag(face, 96, 96, 0)
    blinking = faces()["train"]
    assert render.key_etag(blinking, 72, 72, 0) != render.key_etag(blinking, 72, 72, 1)
    assert render.key_etag(blinking, 72, 72, 0) == render.key_etag(blinking, 72, 72, 2)


def test_spårplans_keys_follow_the_panel_in_their_piece() -> None:
    """SD70, SD71: the piece's state is stamped on the face, so a key whose tracks change is
    drawn again, and one whose tracks do not is not."""
    model = provby()
    it = Interlocking(plant_of(model))
    panel = track_plan.panel_of(model)
    assert panel is not None
    tiles = [
        TklDeckFace(type="tile", tile=TklDeckTile(x=x, y=0, w=4, h=panel.height))
        for x in range(0, int(panel.width) + 4, 4)
    ]
    view = TklDeckView.model_validate(
        {
            "settings": {"serial": "x", "grid": {"columns": len(tiles), "rows": 1}},
            "revision": 0,
            "style": "row",
            "keys": [t.model_dump() for t in tiles],
        }
    )
    before = render.stamp(view, render.picture(panel, it.view()))
    targets = it.targets("In")
    it.set_route("In", next(t.end for t in targets.targets if t.possible), None)
    after = render.stamp(view, render.picture(panel, it.view()))
    states = [
        (a.tile.state, b.tile.state)
        for a, b in zip(before.keys, after.keys, strict=True)
        if a.tile and b.tile
    ]
    assert any(a != b for a, b in states), "the route's pieces changed"
    assert any(a == b for a, b in states), "the pieces without it did not"
    assert render.stamp(view, None) is view


def test_the_strip_and_the_info_line() -> None:
    """SD33, SD34, SD18, SD21: a segment per dial, the no across the strip, Ingen kontakt."""
    parts = [TklDeckStrip(label="Tåg", value="102", under="06:14"), TklDeckStrip(label="Spår")]
    for w, h in ((800, 100), (1200, 100)):
        assert render.strip(parts, 4, w, h).size == (w, h)
        said = render.strip(parts, 4, w, h, said="Spår 2 är belagt.")
        plain = render.strip(parts, 4, w, h)
        assert ImageChops.difference(said, plain).getbbox() is not None
        assert render.strip([], 4, w, h, contact=False).size == (w, h)
    for text in ("06:10  Nu", "06:10  Nej: Spårledningen 2 är belagd av tåg 9.", "06:10", ""):
        assert render.info(text, 248, 58).size == (248, 58)
    assert render.info("", 248, 58, contact=False).getbbox() is not None


def test_the_fonts_are_the_design_systems_with_their_licences() -> None:
    """Inter and TrainMeet Mono under the SIL Open Font License, as TTF beside the renderer,
    the same fonts as the web app's WOFF2 files."""
    for ttf, licence, author in (
        (render.SANS, "LICENSE-inter.txt", "The Inter Project Authors"),
        (render.MONO, "LICENSE-trainmeet-mono.txt", "JetBrains Mono Project Authors"),
    ):
        text = (render.FONTS / licence).read_text(encoding="utf-8")
        assert "SIL Open Font License" in text and author in text
        assert ttf.stat().st_size > 50_000
    assert render.font(True, 700, 20).getname()[0] == "TrainMeet Mono"
    assert render.font(False, 600, 20).getname()[0] == "Inter"
    web = Path(__file__).resolve().parents[2] / "apps/design/src/fonts/trainmeet-mono.woff2"
    try:
        from PIL import ImageFont

        woff = ImageFont.truetype(str(web), 40, layout_engine=ImageFont.Layout.BASIC)
    except OSError:
        pytest.skip("this Pillow cannot read WOFF2")
    ttf_font = ImageFont.truetype(str(render.MONO), 40, layout_engine=ImageFont.Layout.BASIC)
    for font in (woff, ttf_font):
        font.set_variation_by_axes([700])
    a, b = Image.new("L", (400, 60)), Image.new("L", (400, 60))
    from PIL import ImageDraw

    ImageDraw.Draw(a).text((4, 4), "0123 Åäö", font=woff, fill=255)
    ImageDraw.Draw(b).text((4, 4), "0123 Åäö", font=ttf_font, fill=255)
    assert ImageChops.difference(a, b).getbbox() is None, "the TTF is the web app's font"


# --- the pictures in the API ----------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    made = tkl(tmp_path)
    assert set_up(made).status_code == 201
    with_model(made)
    return made


def test_a_key_as_a_picture_with_its_etag(client: TestClient) -> None:
    """The same picture for WebHID as over USB, at the deck's size; the same again is a 304,
    and a press that changes the key gives it a new ETag."""
    opened = TklDeckView.model_validate(client.post(D + "/W1", json={"model": "xl"}).json())
    start = next(i for i, f in enumerate(opened.keys) if f.label == "Plats O")
    got = client.get(D + f"/W1/key/{start}.png", params={"size": 96})
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    image = Image.open(io.BytesIO(got.content))
    assert image.size == (96, 96)
    tag = got.headers["etag"]
    again = client.get(D + f"/W1/key/{start}.png?size=96", headers={"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b""
    assert client.get(D + f"/W1/key/{start}.png?size=72").headers["etag"] != tag
    tall = client.get(D + f"/W1/key/{start}.png?size=80&height=120")
    assert Image.open(io.BytesIO(tall.content)).size == (80, 120), "Studio's keys"
    client.post(D + "/W1/press", json={"key": start})
    pressed = client.get(D + f"/W1/key/{start}.png?size=96", headers={"If-None-Match": tag})
    assert pressed.status_code == 200 and pressed.headers["etag"] != tag
    assert client.get(D + "/W1/key/99.png").status_code == 200, "beyond the keys: black"
    assert client.get(D + "/W1/key/0.png?size=4").status_code == 422
    assert client.get(D + "/okand/key/0.png").status_code == 404


def test_the_strip_and_the_info_line_as_pictures(client: TestClient) -> None:
    client.post(D + "/P1", json={"model": "plus"})
    strip = client.get(D + "/P1/strip.png", params={"width": 800, "height": 100})
    assert Image.open(io.BytesIO(strip.content)).size == (800, 100)
    assert (
        client.get(
            D + "/P1/strip.png", headers={"If-None-Match": strip.headers["etag"]}
        ).status_code
        == 304
    )
    client.post(D + "/N1", json={"model": "neo"})
    info = client.get(D + "/N1/info.png", params={"width": 248, "height": 58})
    assert Image.open(io.BytesIO(info.content)).size == (248, 58)


def test_the_locked_tkl_draws_only_the_clock(client: TestClient) -> None:
    """SD30: while TKL is locked the pictures are the clock and black keys; no session is
    needed to read them."""
    opened = TklDeckView.model_validate(client.post(D + "/W1", json={"model": "15"}).json())
    client.post(API + "/lock")
    locked = TklDeckView.model_validate(client.get(D + "/W1").json())
    clock = next(i for i, f in enumerate(locked.keys) if f.type == "clock")
    black = client.get(D + f"/W1/key/{(clock + 1) % 15}.png")
    image = Image.open(io.BytesIO(black.content)).convert("RGB")
    assert image.getcolors() == [(72 * 72, (13, 15, 17))]
    del opened


def test_ingen_kontakt_as_a_picture_for_the_browser(client: TestClient) -> None:
    """SD21: a deck in the browser fetches Ingen kontakt once, for when TKL does not answer."""
    got = client.get(D + "/ingen-kontakt.png", params={"size": 96})
    assert got.status_code == 200 and got.headers["etag"]
    image = Image.open(io.BytesIO(got.content)).convert("RGB")
    assert ImageChops.difference(image, render.key(look.no_contact(), 96)).getbbox() is None
    tall = client.get(D + "/ingen-kontakt.png", params={"size": 80, "height": 120})
    assert Image.open(io.BytesIO(tall.content)).size == (80, 120)
