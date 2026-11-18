"""Friläggning: the background removal on Catalog's own server (CAT-18, CAT-127–CAT-129).

The U2NetP model (Apache-2.0, about 4.6 MB) finds the vehicle in the photo and gives a mask: how
much each pixel belongs to the vehicle. It runs here with onnxruntime on the CPU, so the photo
is never sent to an AI provider and it costs no tokens (CAT-18, CAT-127). The model lies in the
image (catalog/Dockerfile) and is checked against its SHA-256 when it is loaded. Without it only
the original background can be chosen, and the uploads work as before.

The mask decides two things. The crop: the display picture and the thumbnail are cut around the
vehicle with a small margin, so it stands in the middle and fills them (CAT-129), as the old
TrainCatalog cut its printed cards. And the background (CAT-128): white, grey, transparent or
rails, drawn here, with the vehicle's own pixels laid on it. The vehicle's colours come only
from the photo; nothing of it is generated (CAT-127).

Ported from TrainCatalog's catalog/backgrounds.py (the model and its input) and
catalog/cropping.py (the crop).
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

from catalog.fleet import Refused
from contracts.catalog import PictureBackground, ProblemCode

LOGGER = logging.getLogger("catalog.backgrounds")

MODEL_SHA256: Final = "309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8"
"""U2NetP from rembg's release v0.0.0, the same file the old TrainCatalog checked."""
_MODEL_MAX_BYTES: Final = 16 * 1024 * 1024
_INPUT: Final = (320, 320)
_MEAN: Final = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD: Final = np.array([0.229, 0.224, 0.225], dtype=np.float32)

RATIO: Final = 3 / 2
"""The display picture and the thumbnail are 3:2, as the thumbnail's 360×240 (CAT-126)."""
FILL_WIDTH: Final = 0.95
"""A long vehicle fills 95 % of the width: buffers and couplers keep a margin."""
FILL_HEIGHT: Final = 0.86
"""A tall vehicle fills 86 % of the height."""
CENTER_Y: Final = 0.53
"""The vehicle stands a little below the middle, as on the old printed cards."""
_SEEN: Final = 32
"""From this mask value a pixel counts towards the vehicle's box."""

Colour = tuple[int, int, int]

WHITE: Final = (255, 255, 255)
GREY: Final = (238, 238, 235)
_SKY: Final[tuple[Colour, Colour]] = ((206, 219, 228), (240, 241, 238))
_BALLAST: Final[tuple[Colour, Colour]] = ((152, 143, 131), (104, 97, 88))
_SLEEPER: Final = (86, 68, 54)
_FAR_RAIL: Final = (146, 148, 152)
_RAIL: Final = (104, 106, 110)
_RAIL_SHINE: Final = (204, 206, 210)

Box = tuple[int, int, int, int]
"""(left, top, right, bottom) in pixels, as Pillow's crop takes it."""


def backgrounds_off() -> Refused:
    return Refused(
        503,
        ProblemCode.BACKGROUNDS_OFF,
        "Friläggningen finns inte här just nu, så bara bakgrunden Original går att välja.",
    )


def no_vehicle() -> Refused:
    return Refused(
        422,
        ProblemCode.NO_VEHICLE,
        "Fordonet syns inte tydligt i bilden. Prova ett foto med lugnare bakgrund, "
        "eller välj bakgrunden Original.",
    )


def _failed() -> Refused:
    return Refused(
        503,
        ProblemCode.BACKGROUNDS_OFF,
        "Bilden kunde inte friläggas just nu. Försök igen om en stund, "
        "eller välj bakgrunden Original.",
    )


# --- The mask (CAT-127) ------------------------------------------------------------------------


class Segmenter(Protocol):
    """What finds the vehicle. The real one is U2NetP; the tests give a pretend one."""

    def available(self) -> bool:
        """Can it find vehicles here? The first call may load the model."""
        ...

    def segment(self, image: Image.Image) -> Image.Image:
        """The mask: an L picture the size of the image, 255 where it is the vehicle and 0
        where it is not. Refused with backgrounds_off when it cannot, and with no_vehicle when
        nothing in the picture stands out."""
        ...


class NoSegmenter:
    """No background removal at all: only the original background."""

    def available(self) -> bool:
        return False

    def segment(self, image: Image.Image) -> Image.Image:
        raise backgrounds_off()


class U2NetP:
    """The U2NetP model with onnxruntime, loaded the first time it is needed: once, behind a
    lock, and checked against MODEL_SHA256 before it is used. One picture at a time goes
    through it, on one CPU thread, so the rest of Catalog keeps going while it works."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._loading = threading.Lock()
        self._running = threading.Lock()
        self._tried = False
        self._session: Any = None

    def __repr__(self) -> str:
        return f"U2NetP({str(self.path)!r})"

    def available(self) -> bool:
        return self._load() is not None

    def _load(self) -> Any:
        with self._loading:
            if not self._tried:
                self._session = self._open()
                self._tried = True
            return self._session

    def _open(self) -> Any:
        """The session, or None when the model is missing, is not the right file, or
        onnxruntime cannot run it. Said once in the log, without the file's content."""
        try:
            if self.path.stat().st_size > _MODEL_MAX_BYTES:
                LOGGER.warning("Friläggningsmodellen är för stor och används inte.")
                return None
            data = self.path.read_bytes()
        except OSError:
            LOGGER.warning(
                "Friläggningsmodellen finns inte: bara bakgrunden Original går att välja."
            )
            return None
        if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
            LOGGER.warning("Friläggningsmodellen har fel SHA-256 och används inte.")
            return None
        try:
            # onnxruntime's own telemetry to Microsoft is off before it is loaded, also its
            # store under ~/.cache: nothing about Catalog or the photos leaves the server.
            os.environ["ORT_DISABLE_TELEMETRY"] = "1"
            import onnxruntime

            onnxruntime.disable_telemetry_events()
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            session = onnxruntime.InferenceSession(
                data, options, providers=["CPUExecutionProvider"]
            )
        except Exception as error:  # onnxruntime missing, or a library it needs
            LOGGER.warning("Friläggningsmodellen kunde inte läsas: %s", type(error).__name__)
            return None
        LOGGER.info("Friläggningen är på.")
        return session

    def segment(self, image: Image.Image) -> Image.Image:
        session = self._load()
        if session is None:
            raise backgrounds_off()
        # As U2NetP was trained: 320×320, scaled to 0–1 by the brightest value, then
        # ImageNet's mean and spread per colour, in the order channel, row, column.
        small = image.convert("RGB").resize(_INPUT, Image.Resampling.LANCZOS)
        data = np.array(small, dtype=np.float32)
        data /= max(float(data.max()), 1.0)
        data = (data - _MEAN) / _STD
        batch = data.transpose(2, 0, 1)[np.newaxis]
        try:
            with self._running:
                first = session.get_outputs()[0].name
                output = session.run([first], {session.get_inputs()[0].name: batch})[0][0, 0]
        except Exception as error:
            LOGGER.warning("Friläggningen gick inte: %s", type(error).__name__)
            raise _failed() from error
        return mask_from(np.asarray(output, dtype=np.float32), image.size)


def mask_from(output: NDArray[np.float32], size: tuple[int, int]) -> Image.Image:
    """The model's answer as a mask the size of the picture: stretched to 0–255. An answer
    that is the same everywhere has found nothing."""
    low, high = float(output.min()), float(output.max())
    if not math.isfinite(low + high) or high - low < 1e-6:
        raise no_vehicle()
    scaled = ((output - low) / (high - low) * 255).astype(np.uint8)
    return Image.fromarray(scaled).resize(size, Image.Resampling.LANCZOS)


# --- The crop (CAT-129) ------------------------------------------------------------------------


def _longest_run(indices: NDArray[np.intp], gap: float) -> tuple[int, int]:
    """The longest stretch of rows or columns, over gaps of at most `gap`: thin parts such as a
    coupler hold the vehicle together, while a speck apart from it is left out."""
    start = previous = int(indices[0])
    best = (start, start)
    for value in indices[1:]:
        index = int(value)
        if index - previous > gap:
            start = index
        previous = index
        if previous - start > best[1] - best[0]:
            best = (start, previous)
    return best


def subject_box(mask: Image.Image) -> Box | None:
    """The vehicle's box in the mask, or None when nothing clear stands out."""
    seen = np.asarray(mask.convert("L")) > _SEEN
    rows_n, cols_n = seen.shape
    cols = np.flatnonzero(seen.sum(axis=0) >= max(1.0, rows_n * 0.002))
    rows = np.flatnonzero(seen.sum(axis=1) >= max(1.0, cols_n * 0.002))
    if cols.size == 0 or rows.size == 0:
        return None
    left, right = _longest_run(cols, max(2.0, cols_n * 0.03))
    top, bottom = _longest_run(rows, max(2.0, rows_n * 0.04))
    if (right - left + 1) * (bottom - top + 1) < seen.size * 0.001:
        return None  # a speck, not a vehicle
    return left, top, right + 1, bottom + 1


def _slide(start: float, length: float, low: int, high: int, limit: int, margin: float) -> float:
    """Move the window into the photo, as long as the vehicle keeps its margin on both sides."""
    lowest = max(high + margin * length - length, 0.0)
    highest = min(low - margin * length, limit - length)
    return min(max(start, lowest), highest) if lowest <= highest else start


def _window(size: tuple[int, int], box: Box, ratio: float, inside: bool) -> Box:
    width, height = size
    left, top, right, bottom = box
    cw = max((right - left) / FILL_WIDTH, ratio * (bottom - top) / FILL_HEIGHT, 1.0)
    ch = cw / ratio
    x = (left + right) / 2 - cw / 2
    y = (top + bottom) / 2 - CENTER_Y * ch
    if not inside:
        w = max(1, round(cw))
        h = max(1, round(w / ratio))
        x0, y0 = round(x), round(y)
        return x0, y0, x0 + w, y0 + h
    x = _slide(x, cw, left, right, width, 0.01)
    y = _slide(y, ch, top, bottom, height, 0.03)
    return max(0, round(x)), max(0, round(y)), min(width, round(x + cw)), min(height, round(y + ch))


def crop_box(mask: Image.Image, ratio: float = RATIO, *, inside: bool = False) -> Box | None:
    """Where to cut the picture around the vehicle (CAT-129): the vehicle in the middle,
    filling 95 % of the width (a long vehicle) or 86 % of the height (a tall one), in a box
    `ratio` wide. The box may reach past the photo, where a new background is drawn. With
    inside, for the photo's own background, it is moved into the photo while the vehicle keeps
    a small margin, and what still lies outside is left out: nothing is ever made up. None
    when the mask shows no vehicle."""
    box = subject_box(mask)
    return None if box is None else _window(mask.size, box, ratio, inside)


# --- The backgrounds (CAT-128) -----------------------------------------------------------------


def fit(image: Image.Image, box: tuple[int, int]) -> Image.Image:
    """The picture within the box, never larger than it was."""
    width, height = image.size
    scale = min(box[0] / width, box[1] / height)
    if scale >= 1:
        return image
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS, reducing_gap=2.0)


def _alpha(mask: Image.Image) -> Image.Image:
    """The mask as the vehicle's alpha: the faint haze around it goes, its edges stay soft."""
    table = [0 if p <= 16 else 255 if p >= 240 else round((p - 16) * 255 / 224) for p in range(256)]
    return mask.convert("L").point(table)


def _mix(first: Colour, last: Colour, share: float) -> Colour:
    share = min(1.0, max(0.0, share))
    red, green, blue = (round(a + (b - a) * share) for a, b in zip(first, last, strict=True))
    return red, green, blue


def rails(size: tuple[int, int], ground: float, vehicle_height: float) -> Image.Image:
    """Räls, drawn here, without an image file: a pale sky, ballast, sleepers and two rails,
    the near one right under the vehicle's wheels at `ground`. The track's size follows the
    vehicle's height, so it looks the same however close the photo was taken."""
    width, height = size
    unit = max(1.0, vehicle_height / 30)
    horizon = ground - 1.6 * unit
    rows = [
        _mix(*_SKY, y / max(1.0, horizon))
        if y < horizon
        else _mix(*_BALLAST, (y - horizon) / max(1.0, height - horizon))
        for y in range(height)
    ]
    column = Image.new("RGB", (1, height))
    column.putdata(rows)
    canvas = column.resize(size, Image.Resampling.NEAREST).convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    step, sleeper = 5.0 * unit, 2.2 * unit
    x = (width / 2 - sleeper / 2) % step - step
    while x < width:
        draw.rectangle((x, ground - 0.9 * unit, x + sleeper, ground + 2.2 * unit), fill=_SLEEPER)
        x += step
    draw.rectangle((0, ground - 1.0 * unit, width, ground - 0.4 * unit), fill=_FAR_RAIL)
    draw.rectangle((0, ground, width, ground + 1.3 * unit), fill=_RAIL)
    draw.rectangle((0, ground, width, ground + max(1.0, 0.3 * unit) - 1), fill=_RAIL_SHINE)
    return canvas


def render(
    source: Image.Image,
    mask: Image.Image | None,
    background: PictureBackground,
    *,
    ratio: float = RATIO,
    limit: tuple[int, int] = (1800, 1800),
) -> Image.Image:
    """The picture with the background, cut around the vehicle (CAT-128, CAT-129), within
    `limit`: RGBA for transparent, else RGB. The original background is the photo cut within
    itself, or the photo as it is without a mask. The others are refused with no_vehicle when
    the mask shows no vehicle. Only the photo's pixels make the vehicle (CAT-127)."""
    if background is PictureBackground.ORIGINAL:
        photo = source.convert("RGB")
        window = crop_box(mask, ratio, inside=True) if mask is not None else None
        return fit(photo.crop(window) if window is not None else photo, limit)
    if mask is None:
        raise no_vehicle()
    if mask.size != source.size:
        mask = mask.resize(source.size, Image.Resampling.LANCZOS)
    box = subject_box(mask)
    if box is None:
        raise no_vehicle()
    window = _window(source.size, box, ratio, inside=False)
    w, h = window[2] - window[0], window[3] - window[1]
    scale = min(1.0, limit[0] / w, limit[1] / h)
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    vehicle = source.convert("RGBA")
    vehicle.putalpha(_alpha(mask))
    vehicle = vehicle.crop(window)  # outside the photo: nothing, fully transparent
    if vehicle.size != size:
        vehicle = vehicle.resize(size, Image.Resampling.LANCZOS)  # Pillow keeps the edges clean
    if background is PictureBackground.TRANSPARENT:
        # What is not the vehicle is nothing: not the photo's background hidden under alpha 0.
        seen = vehicle.getchannel("A").point(lambda p: 255 if p else 0)
        return Image.composite(vehicle, Image.new("RGBA", size), seen)
    if background is PictureBackground.RAILS:
        canvas = rails(size, (box[3] - window[1]) * scale, (box[3] - box[1]) * scale)
    else:
        colour = WHITE if background is PictureBackground.WHITE else GREY
        canvas = Image.new("RGBA", size, (*colour, 255))
    canvas.alpha_composite(vehicle)
    return canvas.convert("RGB")
