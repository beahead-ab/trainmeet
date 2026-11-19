"""A local TKL owns its Stream Decks over USB (#86 del b, SD50), tried without real USB: fake decks
with the methods the driver uses, and once the library's own deck over its Dummy transport.

The driver finds the decks and opens each by its serial number with its model from the product
id (SD35, SD52, SD54); a press, a hold, a dial and Neo's touch points reach the interlocking
through the deck service (SD1, SD29, SD82, SD83); only the keys that changed are drawn again;
without the interlocking every key says Ingen kontakt (SD21); Lås locks TKL for the whole
station and the deck shows only the clock (SD30); a deck unplugged and plugged in again is
closed and opened cleanly; and TKL in the cloud never opens USB. A made-up station (provby);
nothing here names a real one (RS13).
"""

from __future__ import annotations

import io
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from StreamDeck.Devices.StreamDeck import DialEventType, TouchscreenEventType
from StreamDeck.ProductIDs import USBProductIDs
from StreamDeck.Transport.Dummy import Dummy

from contracts.tkl import DeckConnection, DeckModelId, TklDecks, TklMode
from tkl.app import create_app
from tkl.deck import logic, look, render, usb
from tkl.deck.models import model_of
from tkl.tests.test_app import API, PIN, set_up
from tkl.tests.test_app_stallverk import with_model

S = API + "/stallverk"


@dataclass
class FakeDeck:
    """A Stream Deck as python-elgato-streamdeck shows it, without USB."""

    pid: int
    serial: str
    path: str
    keys: int
    size: tuple[int, int] = (72, 72)
    dials: int = 0
    strip: tuple[int, int] | None = None
    screen: tuple[int, int] | None = None
    touch_keys: int = 0
    visual: bool = True
    gone: bool = False
    opened: int = 0
    closed: int = 0
    was_reset: int = 0
    images: dict[int, bytes] = field(default_factory=dict)
    writes: list[int] = field(default_factory=list)
    strip_images: list[bytes] = field(default_factory=list)
    screen_images: list[bytes] = field(default_factory=list)
    colours: dict[int, tuple[int, int, int]] = field(default_factory=dict)
    brightness: list[int] = field(default_factory=list)
    on_key: Callable[..., None] | None = None
    on_dial: Callable[..., None] | None = None
    on_touch: Callable[..., None] | None = None

    def __enter__(self) -> FakeDeck:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def open(self) -> None:
        self.opened += 1

    def close(self) -> None:
        self.closed += 1

    def id(self) -> str:
        return self.path

    def product_id(self) -> int:
        return self.pid

    def get_serial_number(self) -> str:
        return self.serial

    def key_count(self) -> int:
        return self.keys

    def touch_key_count(self) -> int:
        return self.touch_keys

    def dial_count(self) -> int:
        return self.dials

    def is_visual(self) -> bool:
        return self.visual

    def is_touch(self) -> bool:
        return self.strip is not None

    def _form(self, size: tuple[int, int] | None) -> dict[str, Any]:
        return {"size": size or (0, 0), "format": "BMP", "flip": (False, False), "rotation": 0}

    def key_image_format(self) -> dict[str, Any]:
        return self._form(self.size if self.visual else None)

    def touchscreen_image_format(self) -> dict[str, Any]:
        return self._form(self.strip)

    def screen_image_format(self) -> dict[str, Any]:
        return self._form(self.screen)

    def set_key_image(self, key: int, image: bytes) -> None:
        if self.gone:
            raise OSError("unplugged")
        self.images[key] = image
        self.writes.append(key)

    def set_touchscreen_image(
        self, image: bytes, x_pos: int = 0, y_pos: int = 0, width: int = 0, height: int = 0
    ) -> None:
        self.strip_images.append(image)

    def set_screen_image(self, image: bytes) -> None:
        self.screen_images.append(image)

    def set_key_color(self, key: int, r: int, g: int, b: int) -> None:
        self.colours[key] = (r, g, b)

    def set_brightness(self, percent: int) -> None:
        self.brightness.append(percent)

    def set_key_callback(self, callback: Callable[..., None] | None) -> None:
        self.on_key = callback

    def set_dial_callback(self, callback: Callable[..., None] | None) -> None:
        self.on_dial = callback

    def set_touchscreen_callback(self, callback: Callable[..., None] | None) -> None:
        self.on_touch = callback

    def reset(self) -> None:
        self.was_reset += 1

    # --- the hand on the deck ---

    def down(self, key: int) -> None:
        assert self.on_key is not None
        self.on_key(self, key, True)

    def up(self, key: int) -> None:
        assert self.on_key is not None
        self.on_key(self, key, False)

    def turn(self, dial: int, steps: int) -> None:
        assert self.on_dial is not None
        self.on_dial(self, dial, DialEventType.TURN, steps)

    def push(self, dial: int) -> None:
        assert self.on_dial is not None
        self.on_dial(self, dial, DialEventType.PUSH, True)
        self.on_dial(self, dial, DialEventType.PUSH, False)

    def tap(self, x: int) -> None:
        assert self.on_touch is not None
        self.on_touch(self, TouchscreenEventType.SHORT, {"x": x, "y": 50})


def xl(serial: str = "XL0001", path: str = "usb-1") -> FakeDeck:
    return FakeDeck(0x006C, serial, path, 32, (96, 96))


def plus(serial: str = "PL0001") -> FakeDeck:
    return FakeDeck(0x0084, serial, "usb-plus", 8, (120, 120), dials=4, strip=(800, 100))


def neo(serial: str = "NEO001") -> FakeDeck:
    return FakeDeck(0x009A, serial, "usb-neo", 8, (96, 96), screen=(248, 58), touch_keys=2)


@dataclass
class Rig:
    """A local TKL with its station and model, a USB driver with fake decks and a fake clock."""

    client: TestClient
    driver: usb.Driver
    plugged: list[Any]
    now: list[float]

    def step(self, seconds: float = 0.0) -> None:
        self.now[0] += seconds
        self.driver.step()

    def view(self, serial: str) -> Any:
        return self.driver.desk.view(serial).view

    def key(self, serial: str, label: str) -> int:
        """The key with this label, or with this label and the interlocking's reason."""
        faces = self.view(serial).keys
        found = [
            i for i, f in enumerate(faces) if f.label == label or f.label.startswith(label + ":")
        ]
        assert found, (label, [f.label for f in faces])
        return found[0]

    def press(self, deck: FakeDeck, key: int, held: float = 0.05) -> None:
        deck.down(key)
        self.step()
        self.now[0] += held
        deck.up(key)
        self.step()

    def routes(self) -> list[Any]:
        return list(self.client.get(S).json()["routes"])


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    plugged: list[Any] = []
    now = [1000.0]
    app = create_app(tmp_path, discover=lambda: [], usb_finder=lambda: list(plugged))
    client = TestClient(app)
    assert set_up(client).status_code == 201
    with_model(client)
    driver = app.state.deck_usb
    assert isinstance(driver, usb.Driver)
    driver.clock = lambda: now[0]
    return Rig(client, driver, plugged, now)


def picture(face: Any, size: tuple[int, int]) -> bytes:
    form = {"size": size, "format": "BMP", "flip": (False, False), "rotation": 0}
    return usb.native(render.key(face, size[0], size[1]), form)


# --- Studio, Deck (#86 del c, SD46): what the owner sets reaches the deck -------------------


def test_brightness_sleep_hold_and_blinka_from_studio_reach_the_deck_on_usb(rig: Rig) -> None:
    """SD46, SD29: the owner's brightness and hold time reach the deck; after the owner's
    minutes without a press it goes dark, and the first press only wakes it; Blinka lights
    every key of the real deck."""
    deck = xl()
    rig.plugged.append(deck)
    rig.step()
    assert deck.brightness == [70], "the default brightness"
    changed = rig.client.put(
        API + "/deck/XL0001", json={"brightness": 30, "sleep": 1, "hold": "lang"}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["settings"]["brightness"] == 30
    assert changed.json()["connection"] == "usb"
    rig.step(usb.POLL + 0.01)
    assert deck.brightness[-1] == 30
    assert rig.driver.decks["usb-1"].holds.seconds == 1.0, "Lång is a second"
    rig.step(59)
    assert deck.brightness[-1] == 30
    rig.step(2)
    assert deck.brightness[-1] == 0, "dark after a minute without a press"
    rig.press(deck, rig.key("XL0001", "Plats O"))
    assert deck.brightness[-1] == 30, "the first press wakes it"
    assert not any(f.label == "Start O" for f in rig.view("XL0001").keys), "and does nothing"
    rig.press(deck, rig.key("XL0001", "Plats O"), held=0.1)
    assert any(f.label == "Start O" for f in rig.view("XL0001").keys)
    rig.step(61)
    assert deck.brightness[-1] == 0
    blinked = rig.client.post(API + "/deck/XL0001/blinka")
    assert blinked.status_code == 200 and blinked.json()["blinking"] is True
    deck.writes.clear()
    rig.step(usb.POLL + 0.01)
    assert deck.brightness[-1] == 30, "Blinka lights a dark deck"
    assert sorted(deck.writes) == list(range(32)), "every key of the real deck"
    assert {f.type for f in rig.view("XL0001").keys} == {"here"}


# --- the models ---------------------------------------------------------------------------


def test_every_product_id_has_its_model_and_the_librarys_grid() -> None:
    """SD51, SD52, SD54: every product id the library knows, and the Module 15 with Scissor
    Keys, maps to TKL's model; the library's class for it has the model's keys and dials."""
    library = {int(v) for k, v in vars(USBProductIDs).items() if k.startswith("USB_PID_STREAMDECK")}
    assert library <= set(usb.PRODUCTS), sorted(hex(p) for p in library - set(usb.PRODUCTS))
    assert usb.PRODUCTS[0x00E4] == DeckModelId.MODULE_15
    assert usb.PRODUCTS[0x00A5] == DeckModelId.FIFTEEN, "Scissor Keys: the 15's profile"
    assert usb.PRODUCTS[0x00B9] == DeckModelId.MODULE_15
    assert usb.PRODUCTS[0x00B8] == DeckModelId.MODULE_6
    assert usb.PRODUCTS[0x00BA] == DeckModelId.MODULE_32
    kinds = usb.kinds()
    assert set(kinds) == set(usb.PRODUCTS)
    for pid, model in usb.PRODUCTS.items():
        grid = model_of(model).grid
        kind = kinds[pid]
        if model == DeckModelId.PEDAL:
            assert (kind.KEY_COUNT, grid.pedals) == (3, 3)
            continue
        assert (grid.columns, grid.rows) == (kind.KEY_COLS, kind.KEY_ROWS), hex(pid)
        assert grid.dials == kind.DIAL_COUNT, hex(pid)
        assert bool(kind.DECK_TOUCH) == grid.strip, hex(pid)
        assert grid.touch == kind.TOUCH_KEY_COUNT, hex(pid)


def test_the_librarys_own_deck_over_its_dummy_transport(rig: Rig) -> None:
    """The driver speaks to python-elgato-streamdeck's own class, here over its Dummy
    transport: opened, every key drawn, and let go when it is gone."""
    device = usb.kinds()[0x006C](Dummy.Device(usb.VENDOR, 0x006C))
    rig.plugged.append(device)
    rig.step()
    [(serial, model)] = rig.driver.connected()
    assert model == DeckModelId.XL and serial.startswith("usb-006c-"), serial
    assert rig.view(serial).settings.model == DeckModelId.XL
    rig.plugged.clear()
    rig.step(usb.RESCAN + 0.1)
    assert rig.driver.connected() == []
    assert not device.is_open()


# --- opening, pressing and drawing ----------------------------------------------------------


def test_a_deck_on_usb_is_opened_by_its_serial_number_and_every_key_drawn(rig: Rig) -> None:
    """SD35, SD50: found, opened with its model, and drawn; the API says it is on USB."""
    deck = xl()
    rig.plugged.append(deck)
    rig.step()
    assert deck.opened == 1 and sorted(deck.writes) == list(range(32))
    view = rig.view("XL0001")
    assert view.settings.model == DeckModelId.XL
    for index, face in enumerate(view.keys):
        assert deck.images[index] == picture(face, (96, 96)), index
    decks = TklDecks.model_validate(rig.client.get(API + "/decks").json())
    assert decks.usb is True
    [status] = decks.decks
    assert (status.serial, status.model, status.connection) == (
        "XL0001",
        DeckModelId.XL,
        DeckConnection.USB,
    )
    assert status.tried is False, "Inte provad until a real deck has been tried (SD58)"
    webhid = rig.client.post(API + "/deck/XL0001", json={"model": "xl", "connection": "webhid"})
    assert webhid.status_code == 409 and "USB" in webhid.json()["detail"], "never opened twice"


def test_a_press_and_a_hold_reach_the_interlocking_and_only_changed_keys_are_drawn(
    rig: Rig,
) -> None:
    """SD1, SD29, SD67: a start and a goal in Platser set the route; holding Lös ut releases
    every route. Only the keys whose face changed are written to the deck."""
    deck = xl()
    rig.plugged.append(deck)
    rig.step()
    deck.writes.clear()
    rig.step(0.3)
    assert deck.writes == [], "nothing changed, nothing drawn"
    rig.press(deck, rig.key("XL0001", "Plats O"))
    changed = list(deck.writes)
    assert changed and len(changed) < 32, "only the keys that changed"
    assert rig.key("XL0001", "Start O") in changed
    rig.press(deck, rig.key("XL0001", "Mål 2"))
    assert [r["enters"] for r in rig.routes()] == ["O"]
    assert rig.view("XL0001").accepted is True
    release = rig.key("XL0001", "Lös ut")
    deck.down(release)
    rig.step()
    rig.step(0.7)
    assert rig.routes() == [], "held for the hold time: Lös ut alla (SD29)"
    deck.up(release)
    rig.step()


def test_a_change_elsewhere_is_drawn_and_a_reason_stands_three_seconds(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deck follows the interlocking without a press (the wait's signature), and the
    interlocking's no stands on the key for three seconds, then goes (SD17, SD18). Here the
    three seconds are made short."""
    monkeypatch.setattr(logic, "FLASH_SECONDS", 0.3)
    deck = xl()
    rig.plugged.append(deck)
    rig.step()
    tracks = rig.client.get(S).json()["tracks"]
    on_two = next(section for section, track in tracks.items() if track == "2")
    deck.writes.clear()
    put = rig.client.post(S + "/train", json={"number": "9", "section": on_two})
    assert put.status_code == 200, put.text
    rig.step(usb.POLL + 0.01)
    assert rig.key("XL0001", "Plats 2") in deck.writes, "the train number on its place (SD19)"
    rig.press(deck, rig.key("XL0001", "Plats O"))
    goal = rig.key("XL0001", "Mål 2")
    assert rig.view("XL0001").keys[goal].dim, "hindered: dimmed with the reason (SD17)"
    rig.press(deck, goal)
    view = rig.view("XL0001")
    assert view.accepted is False and rig.routes() == []
    assert view.keys[goal].type == "answer" and view.keys[goal].bg == look.RED
    assert deck.images[goal] == picture(view.keys[goal], (96, 96))
    deck.writes.clear()
    time.sleep(0.35)
    rig.step(0.35)
    assert goal in deck.writes and rig.view("XL0001").keys[goal].type != "answer"


def test_ingen_kontakt_when_the_interlocking_does_not_answer(rig: Rig) -> None:
    """SD21: without the interlocking every key says Ingen kontakt, never an old state; the
    deck comes back when it answers again."""
    deck = xl()
    rig.plugged.append(deck)
    rig.step()
    assert rig.client.delete(API + "/studio/model").status_code == 200
    rig.step(usb.POLL + 0.01)
    nothing = picture(look.no_contact(), (96, 96))
    assert all(deck.images[i] == nothing for i in range(32))
    rig.press(deck, 0)
    assert all(deck.images[i] == nothing for i in range(32)), "a press does nothing"
    with_model(rig.client)
    rig.step(usb.RETRY + 0.01)
    assert any(deck.images[i] != nothing for i in range(32))


def test_las_on_the_deck_locks_tkl_for_the_whole_station(rig: Rig) -> None:
    """SD30: Lås on the page Läge locks TKL; the deck shows only the clock, the browser's
    session ends, and the PIN opens TKL again. Lås in TKL does the same to the deck."""
    deck = xl()
    rig.plugged.append(deck)
    rig.step()
    rig.press(deck, rig.key("XL0001", "Läge Platser"))
    rig.press(deck, rig.key("XL0001", "Lås TKL"))
    view = rig.view("XL0001")
    assert view.locked and [f.type for f in view.keys if f.type != "empty"] == ["clock"]
    clock = next(i for i, f in enumerate(view.keys) if f.type == "clock")
    empty = picture(look.EMPTY, (96, 96))
    assert all(deck.images[i] == empty for i in range(32) if i != clock)
    state = rig.client.get(API + "/state").json()
    assert (state["unlocked"], state["locked"]) == (False, True)
    assert rig.client.get(API + "/studio").status_code == 401
    deck.writes.clear()
    rig.press(deck, 0)
    assert deck.writes == [] and rig.view("XL0001").message == "TKL är låst. PIN-koden låser upp."
    assert rig.client.post(API + "/unlock", json={"pin": PIN}).status_code == 200
    rig.step(usb.POLL + 0.01)
    assert not rig.view("XL0001").locked
    assert rig.client.post(API + "/lock").status_code == 200
    rig.step(usb.POLL + 0.01)
    assert rig.view("XL0001").locked, "Lås in TKL locks the deck too"


def test_dials_strip_and_touch_points(rig: Rig) -> None:
    """SD33, SD34, SD82, SD83: the dials of + turn and press, a tap on the strip presses the
    dial over it, the strip and Neo's info line are drawn, and Neo's touch points turn the
    page."""
    deck = plus()
    rig.plugged.append(deck)
    rig.step()
    assert deck.strip_images, "the strip is drawn"
    laid = rig.client.post(S + "/route", json={"start": "In", "end": "12"})
    assert laid.status_code == 200 and rig.routes()
    rig.step(usb.POLL + 0.01)
    route_dial = next(i for i, p in enumerate(rig.view("PL0001").strip) if p.label == "Lagd väg")
    deck.push(route_dial)
    rig.step()
    assert rig.routes() == [], "press on Lagd väg releases it (SD83)"
    before = rig.view("PL0001").strip[0]
    deck.turn(0, 1)
    rig.step()
    assert rig.view("PL0001").strip[0] != before, "a turn chooses (SD83)"
    width = 800
    laid = rig.client.post(S + "/route", json={"start": "In", "end": "12"})
    assert laid.status_code == 200
    rig.step(usb.POLL + 0.01)
    deck.tap(int((route_dial + 0.5) * width / 4))
    rig.step()
    assert rig.routes() == [], "a tap on the strip presses the dial over it"

    small = neo()
    rig.plugged.append(small)
    rig.step(usb.RESCAN + 0.1)
    assert small.screen_images, "Neo's info line is drawn"
    assert small.colours == {8: usb.TOUCH_COLOUR, 9: usb.TOUCH_COLOUR}
    before = rig.view("NEO001").revision
    small.down(9)
    rig.step()
    small.up(9)
    rig.step()
    assert rig.view("NEO001").revision > before, "the touch point reached the deck (SD82)"


def test_a_deck_unplugged_and_plugged_in_again(rig: Rig) -> None:
    """Unplugged, the deck is closed cleanly and the API no longer says it is on USB; plugged
    in again it is opened and drawn afresh. A deck that stops answering is let go too."""
    deck = xl()
    rig.plugged.append(deck)
    rig.step()
    rig.plugged.clear()
    rig.step(usb.RESCAN + 0.1)
    assert deck.closed == 1 and deck.on_key is None
    status = rig.client.get(API + "/decks").json()["decks"]
    assert [d["connection"] for d in status] == [None]
    again = xl(path="usb-2")
    rig.plugged.append(again)
    rig.step(usb.RESCAN + 0.1)
    assert again.opened == 1 and sorted(again.writes) == list(range(32))
    assert rig.driver.connected() == [("XL0001", DeckModelId.XL)]
    again.gone = True
    rig.press(again, 0)
    rig.step()
    assert rig.driver.connected() == [] and again.closed == 1
    assert rig.client.get(API + "/state").status_code == 200, "TKL goes on"


def test_without_libhidapi_tkl_says_so_and_goes_on(tmp_path: Path) -> None:
    def missing() -> list[usb.Device]:
        raise OSError("libhidapi-libusb.so.0")

    app = create_app(tmp_path, discover=lambda: [], usb_finder=missing)
    client = TestClient(app)
    set_up(client)
    driver = app.state.deck_usb
    driver.step()
    decks = TklDecks.model_validate(client.get(API + "/decks").json())
    assert decks.usb and decks.usb_problem and "libhidapi" in decks.usb_problem


def test_the_driver_runs_with_tkl_and_lets_go_when_tkl_stops(tmp_path: Path) -> None:
    deck = xl()
    app = create_app(tmp_path, discover=lambda: [], usb_finder=lambda: [deck])
    with TestClient(app) as client:
        set_up(client)
        with_model(client)
        for _ in range(100):
            if len(deck.writes) >= 32:
                break
            time.sleep(0.05)
        assert sorted(set(deck.writes)) == list(range(32))
    assert deck.was_reset == 1 and deck.closed == 1, "Elgato's own picture back"


def test_tkl_in_the_cloud_never_opens_usb(tmp_path: Path) -> None:
    """SD50, TKLMOLN-08: as with LocoNet, the cloud never looks for a deck on USB."""
    looked: list[int] = []

    def finder() -> list[usb.Device]:
        looked.append(1)
        return [xl()]

    app = create_app(
        tmp_path,
        mode=TklMode.CLOUD,
        over_internet=["https://hub.invalid"],
        discover=lambda: [],
        usb_finder=finder,
    )
    assert app.state.deck_usb is None
    with TestClient(app) as client:
        set_up(client)
        time.sleep(0.2)
        decks = TklDecks.model_validate(client.get(API + "/decks").json())
    assert looked == [] and decks.usb is False


def test_native_turns_and_mirrors_as_the_deck_wants() -> None:
    image = Image.new("RGB", (4, 2), "#000000")
    image.putpixel((0, 0), (255, 0, 0))
    form = {"size": (4, 2), "format": "BMP", "flip": (True, True), "rotation": 0}
    back = Image.open(io.BytesIO(usb.native(image, form))).convert("RGB")
    assert back.getpixel((3, 1)) == (255, 0, 0)
    turned = {"size": (4, 2), "format": "BMP", "flip": (False, False), "rotation": 90}
    assert Image.open(io.BytesIO(usb.native(image, turned))).size == (2, 4)
