"""A local TKL owns its Stream Decks over USB (#86 del b, SD50): a deck works without an open
tab and in every browser. TKL in the cloud never opens USB, as with LocoNet; there the browser
drives a deck with WebHID (apps/tkl/src/deckhid.ts).

The driver runs in the background for as long as TKL runs. It finds the decks on USB through
python-elgato-streamdeck and the system's libhidapi, and looks again every few seconds, so that
a deck can be plugged in and out at any time. Each deck is known by its serial number (SD35)
and opened through the same deck service as the API's (tkl.deck.service), with its model from
its USB product id: the Modules and the 15 with Scissor Keys get the profile of their size
(SD54). Then:

- a key down and up is a press or a hold by the deck's hold time (SD29, logic.Holds);
- the dials of + and + XL turn and press (SD83), a tap on the touch strip presses the dial over
  it, and a swipe along it, like Neo's touch points, turns the page (SD82);
- only the keys whose face changed are drawn again, and the blinking ones every half second;
  the deck is read again when the interlocking, the hub or the start changes, the same
  signature as the API's wait, and when a reason's three seconds run out (SD18);
- when TKL cannot read the deck's state, every key says Ingen kontakt, never an old state
  (SD21); when TKL is locked, the deck shows only the clock (SD30);
- a deck that is unplugged is closed, and nothing a deck does can stop TKL.

The pictures are TKL's own (tkl.deck.render), the same as WebHID's.
"""

from __future__ import annotations

import io
import logging
import queue
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol

from PIL import Image

from contracts.tkl import DeckModelId, TklDeckFace
from tkl.deck import look, render
from tkl.deck.logic import Holds
from tkl.deck.models import model_of
from tkl.deck.service import Shown

LOGGER = logging.getLogger("tkl.deck.usb")
M = DeckModelId
VENDOR: Final = 0x0FD9
"""Elgato's USB vendor id."""
PRODUCTS: Final[dict[int, DeckModelId]] = {
    0x0060: M.FIFTEEN,  # Stream Deck, the first one
    0x006D: M.FIFTEEN,  # Stream Deck, second edition
    0x0080: M.FIFTEEN,  # Stream Deck MK.2
    0x00A5: M.FIFTEEN,  # Stream Deck MK.2, Scissor Keys
    0x0063: M.MINI,  # Stream Deck Mini
    0x0090: M.MINI,  # Stream Deck Mini MK.2
    0x00B3: M.MINI,  # Stream Deck Mini, Discord's edition
    0x006C: M.XL,  # Stream Deck XL
    0x008F: M.XL,  # Stream Deck XL, second edition
    0x009A: M.NEO,  # Stream Deck Neo
    0x0084: M.PLUS,  # Stream Deck +
    0x00C6: M.PLUS_XL,  # Stream Deck + XL
    0x0086: M.PEDAL,  # Stream Deck Pedal
    0x00AA: M.STUDIO,  # Stream Deck Studio
    0x00B8: M.MODULE_6,  # Stream Deck Module, 6 keys
    0x00B9: M.MODULE_15,  # Stream Deck Module, 15 keys
    0x00E4: M.MODULE_15,  # Stream Deck Module, 15 keys, Scissor Keys
    0x00BA: M.MODULE_32,  # Stream Deck Module, 32 keys
}
"""Every deck Elgato sells, by its USB product id (SD52), as both libraries know them."""
RESCAN: Final = 3.0
"""Seconds between looks for decks plugged in or out."""
RESCAN_WITHOUT_USB: Final = 30.0
"""Without libhidapi TKL looks again this seldom, and says why once."""
TICK: Final = 0.05
POLL: Final = 0.25
"""Seconds between asking whether the deck's state changed."""
RETRY: Final = 1.0
"""Seconds between tries to read a deck that said Ingen kontakt."""
SERIAL: Final = re.compile(r"[^A-Za-z0-9._-]")
TOUCH_COLOUR: Final = (51, 65, 85)
"""Neo's touch points, lit dimly so that they can be found."""
SWIPE: Final = 40
"""Pixels along the strip that make a swipe."""


class Device(Protocol):
    """What the driver uses of a deck: python-elgato-streamdeck's StreamDeck, or a fake one."""

    def __enter__(self) -> Any: ...
    def __exit__(self, *args: object) -> Any: ...
    def open(self) -> None: ...
    def close(self) -> None: ...
    def id(self) -> str: ...
    def product_id(self) -> int: ...
    def get_serial_number(self) -> str: ...
    def key_count(self) -> int: ...
    def touch_key_count(self) -> int: ...
    def dial_count(self) -> int: ...
    def is_visual(self) -> bool: ...
    def is_touch(self) -> bool: ...
    def key_image_format(self) -> dict[str, Any]: ...
    def touchscreen_image_format(self) -> dict[str, Any]: ...
    def screen_image_format(self) -> dict[str, Any]: ...
    def set_key_image(self, key: int, image: bytes) -> None: ...
    def set_touchscreen_image(
        self, image: bytes, x_pos: int = 0, y_pos: int = 0, width: int = 0, height: int = 0
    ) -> None: ...
    def set_screen_image(self, image: bytes) -> None: ...
    def set_key_color(self, key: int, r: int, g: int, b: int) -> None: ...
    def set_key_callback(self, callback: Callable[..., None] | None) -> None: ...
    def set_dial_callback(self, callback: Callable[..., None] | None) -> None: ...
    def set_touchscreen_callback(self, callback: Callable[..., None] | None) -> None: ...
    def reset(self) -> None: ...


Finder = Callable[[], list[Device]]


class Desk(Protocol):
    """The deck service for the station on this computer, without an HTTP request: the same
    opening, logic and view as the API's (tkl/app.py)."""

    def open(self, serial: str, model: DeckModelId) -> Shown: ...
    def view(self, serial: str) -> Shown: ...
    def press(self, serial: str, key: int, hold: bool) -> Shown: ...
    def dial(self, serial: str, dial: int, turn: int, press: bool) -> Shown: ...
    def touch(self, serial: str, point: Literal[-1, 1]) -> Shown: ...
    def revision(self, serial: str) -> int: ...
    def gone(self, serial: str) -> None: ...


# --- finding the decks ------------------------------------------------------------------------


_manager: Any = None


def kinds() -> dict[int, Any]:
    """python-elgato-streamdeck's class for each product id: how TKL talks to the deck. The
    library lists the Module 15 twice and does not know its Scissor Keys edition; both speak
    as the second-generation 15."""
    from StreamDeck.Devices.StreamDeckMini import StreamDeckMini
    from StreamDeck.Devices.StreamDeckNeo import StreamDeckNeo
    from StreamDeck.Devices.StreamDeckOriginal import StreamDeckOriginal
    from StreamDeck.Devices.StreamDeckOriginalV2 import StreamDeckOriginalV2
    from StreamDeck.Devices.StreamDeckPedal import StreamDeckPedal
    from StreamDeck.Devices.StreamDeckPlus import StreamDeckPlus
    from StreamDeck.Devices.StreamDeckPlusXL import StreamDeckPlusXL
    from StreamDeck.Devices.StreamDeckStudio import StreamDeckStudio
    from StreamDeck.Devices.StreamDeckXL import StreamDeckXL

    return {
        0x0060: StreamDeckOriginal,
        0x006D: StreamDeckOriginalV2,
        0x0080: StreamDeckOriginalV2,
        0x00A5: StreamDeckOriginalV2,
        0x00B9: StreamDeckOriginalV2,
        0x00E4: StreamDeckOriginalV2,
        0x0063: StreamDeckMini,
        0x0090: StreamDeckMini,
        0x00B3: StreamDeckMini,
        0x00B8: StreamDeckMini,
        0x006C: StreamDeckXL,
        0x008F: StreamDeckXL,
        0x00BA: StreamDeckXL,
        0x009A: StreamDeckNeo,
        0x0084: StreamDeckPlus,
        0x00C6: StreamDeckPlusXL,
        0x0086: StreamDeckPedal,
        0x00AA: StreamDeckStudio,
    }


def find() -> list[Device]:
    """Every Elgato deck on USB, through python-elgato-streamdeck and the system's libhidapi,
    once each. Raises when libhidapi is missing; the driver says so and looks again later."""
    global _manager
    from StreamDeck.DeviceManager import DeviceManager

    known = kinds()
    if _manager is None:
        _manager = DeviceManager(transport="libusb")
    found: dict[str, Device] = {}
    for raw in _manager.transport.enumerate(vid=VENDOR, pid=None):
        kind = known.get(int(raw.product_id()))
        if kind is not None:
            found.setdefault(str(raw.path()), kind(raw))
    return list(found.values())


def serial_of(device: Device) -> str:
    """The deck's serial number as TKL keeps it: letters, digits, dot, dash and underscore."""
    try:
        given = SERIAL.sub("", device.get_serial_number() or "")[:64]
    except Exception:
        given = ""
    if not given or not given[0].isalnum():
        given = f"usb-{device.product_id():04x}-" + SERIAL.sub("", device.id())[-24:]
    return given[:64]


def native(image: Image.Image, form: dict[str, Any]) -> bytes:
    """A picture in the deck's own format: turned and mirrored as the deck wants, as BMP or
    JPEG (python-elgato-streamdeck's PILHelper does the same)."""
    given = form.get("size") or image.size
    size = (int(given[0]), int(given[1]))
    if image.size != size:
        image = image.resize(size)
    if form.get("rotation"):
        image = image.rotate(form["rotation"], expand=True)
    flip = form.get("flip") or (False, False)
    if flip[0]:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if flip[1]:
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    with io.BytesIO() as out:
        image.save(out, form.get("format") or "JPEG", quality=100)
        return out.getvalue()


# --- the driver ------------------------------------------------------------------------------


Kind = Literal["down", "up", "turn", "push", "tap", "swipe"]


@dataclass(frozen=True)
class Input:
    """Something done on the deck, from the library's own thread."""

    kind: Kind
    index: int
    value: int = 0
    at: float = 0.0


class Gone(Exception):
    """The deck does not answer: it is unplugged."""


@dataclass
class Plugged:
    """A deck TKL has open: what it is, and what it shows now."""

    device: Device
    path: str
    serial: str
    model: DeckModelId
    keys: int
    touch_keys: int
    dials: int
    key_size: tuple[int, int] | None
    key_form: dict[str, Any] | None
    strip_form: dict[str, Any] | None
    screen_form: dict[str, Any] | None
    inputs: queue.Queue[Input] = field(default_factory=queue.Queue)
    holds: Holds = field(default_factory=Holds)
    opened: bool = False
    shown: Shown | None = None
    contact: bool = True
    revision: int | None = None
    read_at: float = 0.0
    polled_at: float = 0.0
    drawn: dict[int, str] = field(default_factory=dict)
    strip_drawn: str | None = None
    info_drawn: str | None = None
    painted: tuple[int, int] | None = None


class Driver:
    """Owns the decks on USB for as long as TKL runs (SD50). `step` does one round, so that a
    test can drive it without a thread; `start` runs it in the background."""

    def __init__(
        self,
        desk: Desk,
        finder: Finder = find,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.desk = desk
        self.finder = finder
        self.clock = clock
        self.decks: dict[str, Plugged] = {}
        self.problem: str | None = None
        self.scan_at = 0.0
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._said: set[str] = set()
        self._failed: set[str] = set()

    # --- running ---------------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="tkl-stream-deck", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """TKL stops: the decks get Elgato's own picture back and are let go."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        with self.lock:
            for plugged in list(self.decks.values()):
                self._close(plugged, reset=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.step()
            except Exception:  # never stop TKL, never stop the driver
                LOGGER.exception("Stream Deck över USB: ett fel i drivrutinen")
            self._stop.wait(TICK)

    def connected(self) -> list[tuple[str, DeckModelId]]:
        with self.lock:
            return [(p.serial, p.model) for p in self.decks.values()]

    # --- one round -------------------------------------------------------------------------

    def step(self) -> None:
        with self.lock:
            now = self.clock()
            if now >= self.scan_at:
                self._scan(now)
            for plugged in list(self.decks.values()):
                try:
                    self._serve(plugged, now)
                except Gone:
                    self._close(plugged)

    def _scan(self, now: float) -> None:
        try:
            found = self.finder()
        except Exception as error:
            self.problem = (
                f"TKL når inte USB: libhidapi saknas eller kan inte läsas ({type(error).__name__})."
            )
            if self.problem not in self._said:
                self._said.add(self.problem)
                LOGGER.warning("Stream Deck över USB: %s", self.problem)
            self.scan_at = now + RESCAN_WITHOUT_USB
            return
        self.problem = None
        self.scan_at = now + RESCAN
        paths: dict[str, Device] = {}
        for device in found:
            try:
                paths.setdefault(device.id(), device)
            except Exception:
                continue
        for path, plugged in list(self.decks.items()):
            if path not in paths:
                self._close(plugged)
        for path, device in paths.items():
            if path in self.decks:
                continue
            try:
                known = device.product_id() in PRODUCTS
            except Exception:
                continue
            if known:
                self._open(path, device, now)

    def _open(self, path: str, device: Device, now: float) -> None:
        model = PRODUCTS[device.product_id()]
        try:
            device.open()
            serial = serial_of(device)
            visual = device.is_visual()
            key_form = device.key_image_format() if visual and device.key_count() else None
            strip_form = device.touchscreen_image_format() if device.is_touch() else None
            screen_form = _screen_form(device)
        except Exception:
            if path not in self._failed:
                # Said once per deck: on Linux most often the rule for Elgato (tkl/README.md).
                self._failed.add(path)
                LOGGER.warning(
                    "Stream Deck över USB: %s gick inte att öppna; saknas rätten till USB?",
                    model_of(model).name,
                )
            _quietly(device.close)
            return
        self._failed.discard(path)
        size = tuple(key_form["size"]) if key_form else None
        plugged = Plugged(
            device=device,
            path=path,
            serial=serial,
            model=model,
            keys=device.key_count(),
            touch_keys=device.touch_key_count(),
            dials=device.dial_count(),
            key_size=(int(size[0]), int(size[1])) if size else None,
            key_form=key_form,
            strip_form=strip_form if strip_form and strip_form.get("size") != (0, 0) else None,
            screen_form=screen_form,
        )
        inputs = plugged.inputs

        def on_key(_: object, key: int, down: bool) -> None:
            inputs.put(Input("down" if down else "up", int(key), at=self.clock()))

        def on_dial(_: object, dial: int, event: object, value: object) -> None:
            name = getattr(event, "name", str(event))
            if name == "TURN":
                inputs.put(Input("turn", int(dial), int(value)))  # type: ignore[call-overload]
            elif name == "PUSH" and value:
                inputs.put(Input("push", int(dial)))

        def on_touch(_: object, event: object, value: object) -> None:
            name = getattr(event, "name", str(event))
            spot = value if isinstance(value, dict) else {}
            x = int(spot.get("x", 0))
            if name == "DRAG":
                moved = int(spot.get("x_out", x)) - x
                if abs(moved) >= SWIPE:
                    inputs.put(Input("swipe", 0, 1 if moved < 0 else -1))
            else:
                inputs.put(Input("tap", x))

        try:
            device.set_key_callback(on_key)
            if plugged.dials:
                device.set_dial_callback(on_dial)
            if plugged.strip_form is not None:
                device.set_touchscreen_callback(on_touch)
            for touch in range(plugged.touch_keys):
                device.set_key_color(plugged.keys + touch, *TOUCH_COLOUR)
        except Exception:
            _quietly(device.close)
            return
        self.decks[path] = plugged
        LOGGER.info("Stream Deck över USB: %s inkopplat", model_of(model).name)
        self._read(plugged, now, first=True)

    def _close(self, plugged: Plugged, *, reset: bool = False) -> None:
        """An unplugged deck is let go cleanly; TKL stopping gives it Elgato's picture back."""
        self.decks.pop(plugged.path, None)
        device = plugged.device
        _quietly(lambda: device.set_key_callback(None))
        if plugged.dials:
            _quietly(lambda: device.set_dial_callback(None))
        if plugged.strip_form is not None:
            _quietly(lambda: device.set_touchscreen_callback(None))
        if reset:
            _quietly(device.reset)
        _quietly(device.close)
        _quietly(lambda: self.desk.gone(plugged.serial))
        LOGGER.info("Stream Deck över USB: %s urkopplat", model_of(plugged.model).name)

    # --- what the deck does and shows ------------------------------------------------------

    def _serve(self, plugged: Plugged, now: float) -> None:
        acted = False
        while True:
            try:
                done = plugged.inputs.get_nowait()
            except queue.Empty:
                break
            acted = self._input(plugged, done, now) or acted
        for key in plugged.holds.tick(now):
            acted = self._held(plugged, key) or acted
        if not acted:
            due = now >= plugged.read_at
            if not due and plugged.contact and now - plugged.polled_at >= POLL:
                plugged.polled_at = now
                try:
                    due = self.desk.revision(plugged.serial) != plugged.revision
                except Exception:
                    due = True
            if due:
                self._read(plugged, now)
        self._paint(plugged, now)

    def _held(self, plugged: Plugged, key: int) -> bool:
        """A key held for the hold time, while it is still down: a hold (SD29)."""
        return self._act(plugged, lambda: self.desk.press(plugged.serial, key, True))

    def _input(self, plugged: Plugged, done: Input, now: float) -> bool:
        serial = plugged.serial
        if done.kind in ("down", "up") and done.index >= plugged.keys:
            # Neo's touch points come after the keys: the pages back and forth (SD82).
            if done.kind == "down":
                side: Literal[-1, 1] = -1 if done.index == plugged.keys else 1
                return self._act(plugged, lambda: self.desk.touch(serial, side))
            return False
        if done.kind == "down":
            plugged.holds.pressed(done.index, done.at or now)
            return False
        if done.kind == "up":
            what = plugged.holds.released(done.index, done.at or now)
            if what is None:
                return False
            return self._act(plugged, lambda: self.desk.press(serial, done.index, what == "hold"))
        if done.kind == "turn":
            turn = max(-20, min(20, done.value))
            return self._act(plugged, lambda: self.desk.dial(serial, done.index, turn, False))
        if done.kind == "push":
            return self._act(plugged, lambda: self.desk.dial(serial, done.index, 0, True))
        if done.kind == "tap" and plugged.strip_form is not None and plugged.dials:
            width = int(plugged.strip_form["size"][0]) or 1
            dial = max(0, min(plugged.dials - 1, done.index * plugged.dials // width))
            return self._act(plugged, lambda: self.desk.dial(serial, dial, 0, True))
        if done.kind == "swipe":
            way: Literal[-1, 1] = 1 if done.value > 0 else -1
            return self._act(plugged, lambda: self.desk.touch(serial, way))
        return False

    def _act(self, plugged: Plugged, act: Callable[[], Shown]) -> bool:
        """Something done on the deck, through the deck service; its answer is shown."""
        if not plugged.opened:
            self._read(plugged, self.clock())
            if not plugged.opened:
                return True
        try:
            self._shown(plugged, act(), self.clock())
        except Exception:
            self._lost(plugged, self.clock())
        return True

    def _read(self, plugged: Plugged, now: float, *, first: bool = False) -> None:
        try:
            if not plugged.opened:
                shown = self.desk.open(plugged.serial, plugged.model)
                plugged.opened = True
            else:
                shown = self.desk.view(plugged.serial)
        except Exception:
            if first or plugged.contact:
                LOGGER.info(
                    "Stream Deck över USB: %s visar Ingen kontakt", model_of(plugged.model).name
                )
            self._lost(plugged, now)
            return
        self._shown(plugged, shown, now)

    def _shown(self, plugged: Plugged, shown: Shown, now: float) -> None:
        plugged.shown = shown
        plugged.contact = True
        plugged.revision = shown.view.revision
        plugged.read_at = now + shown.view.refresh_ms / 1000
        plugged.polled_at = now
        plugged.holds.seconds = shown.view.hold_ms / 1000

    def _lost(self, plugged: Plugged, now: float) -> None:
        """Ingen kontakt (SD21): never an old state, and a hold half done is forgotten."""
        plugged.shown = None
        plugged.contact = False
        plugged.opened = False  # opened again when TKL answers: its settings may be new
        plugged.read_at = now + RETRY
        plugged.holds = Holds(seconds=plugged.holds.seconds)

    def _paint(self, plugged: Plugged, now: float) -> None:
        """Only what changed: the keys whose face changed, the blinking ones every half
        second, and the strip or the info line when theirs did."""
        shown = plugged.shown
        faces: list[TklDeckFace]
        if shown is None:
            faces = [look.no_contact() for _ in range(plugged.keys)]
        else:
            faces = list(shown.view.keys)
        blinking = render.blinks(faces)
        phase = render.phase_at(now) if blinking else 0
        painted = (id(shown) if shown is not None else -1, phase)
        if plugged.painted == painted:
            return
        picture = shown.picture if shown is not None else None
        if plugged.key_form is not None and plugged.key_size is not None:
            w, h = plugged.key_size
            for index in range(plugged.keys):
                face = faces[index] if index < len(faces) else look.EMPTY
                tag = render.key_etag(face, w, h, phase)
                if plugged.drawn.get(index) == tag:
                    continue
                image = native(render.key(face, w, h, picture, phase), plugged.key_form)
                self._key(plugged, index, image)
                plugged.drawn[index] = tag
        if plugged.strip_form is not None:
            self._paint_strip(plugged, shown)
        if plugged.screen_form is not None:
            self._paint_info(plugged, shown)
        plugged.painted = painted

    def _paint_strip(self, plugged: Plugged, shown: Shown | None) -> None:
        assert plugged.strip_form is not None
        w, h = (int(v) for v in plugged.strip_form["size"])
        parts = shown.view.strip if shown is not None else []
        said = shown.view.said if shown is not None else ""
        tag = render.etag(
            "strip", [p.model_dump() for p in parts], said, shown is not None, plugged.dials, w, h
        )
        if plugged.strip_drawn == tag:
            return
        image = render.strip(parts, plugged.dials, w, h, said=said, contact=shown is not None)
        data = native(image, plugged.strip_form)
        self._write(plugged, lambda: plugged.device.set_touchscreen_image(data, 0, 0, w, h))
        plugged.strip_drawn = tag

    def _paint_info(self, plugged: Plugged, shown: Shown | None) -> None:
        assert plugged.screen_form is not None
        w, h = (int(v) for v in plugged.screen_form["size"])
        text = shown.view.info if shown is not None else ""
        tag = render.etag("info", text, shown is not None, w, h)
        if plugged.info_drawn == tag:
            return
        data = native(render.info(text, w, h, contact=shown is not None), plugged.screen_form)
        self._write(plugged, lambda: plugged.device.set_screen_image(data))
        plugged.info_drawn = tag

    def _key(self, plugged: Plugged, index: int, image: bytes) -> None:
        self._write(plugged, lambda: plugged.device.set_key_image(index, image))

    def _write(self, plugged: Plugged, write: Callable[[], None]) -> None:
        try:
            with plugged.device:
                write()
        except Exception as error:
            raise Gone from error


def _screen_form(device: Device) -> dict[str, Any] | None:
    """Neo's info line, the only deck with a screen besides its keys."""
    try:
        form = device.screen_image_format()
    except Exception:
        return None
    size = form.get("size") if form else None
    return form if size and size[0] and size[1] else None


def _quietly(act: Callable[[], object]) -> None:
    try:
        act()
    except Exception:
        LOGGER.debug("Stream Deck över USB: ett fel när decket släpptes", exc_info=True)


__all__ = [
    "PRODUCTS",
    "Desk",
    "Device",
    "Driver",
    "Finder",
    "find",
    "kinds",
    "native",
    "serial_of",
]
