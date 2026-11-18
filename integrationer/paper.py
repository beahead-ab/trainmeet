"""Efter pappret (LOK-29, LF16): the driver's photos of a duty missing from the plan, read by AI.

The photos are cleaned before anything is sent: a JPEG, PNG or WebP keeps only what draws the
picture, and loses the camera's data, the place it was taken, the time and any text or profile
that came with it. The phone draws the photos anew before it sends them; this is the hub's own
guarantee. Nothing else is read out of a photo here.

AI only writes down what the pages say, in the order they say it. Code reads its answer: a time
it could not read stays empty and its row is marked, never guessed (LOK-29). The places are
matched to the meet's in Drift.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, Final

from contracts import drift as events
from integrationer.ai import Image
from integrationer.scanned import MAX_PICTURE

MAX_PAGES: Final = 4
MAX_ROWS: Final = 200
MAX_TOKENS: Final = 8192
PROMPT: Final = """Bilderna är sidorna i ett köruppdrag för en förare på en modelljärnvägsträff,
i ordning. Framsidan har ordet Tjänst och ett nummer, Startar med tid och station, Slutar med tid
och station, bolaget och svårigheten. Inuti står tåget och tidtabellen: station, spår, ankomst,
avgång och anmärkning. Språket kan vara svenska, norska eller danska.

Skriv av det som står, exakt, utan att tolka, rätta eller gissa. En tid som står men inte går att
läsa skriver du som "?". Saknas något skriver du "".

Svara bara med JSON, så här:
{"number": "tjänstens nummer", "train": "tågnumret", "operator": "bolaget",
 "start": {"time": "TT:MM", "place": "stationen"},
 "end": {"time": "TT:MM", "place": "stationen"},
 "rows": [{"place": "stationen", "arrival": "TT:MM", "departure": "TT:MM", "track": "spåret",
           "note": "anmärkningen", "stops": true}]}

En rad per station i tidtabellen, i ordning, från alla sidor. stops är false bara när det står
Ej uppehåll på raden (eller Uden ophold, Uten opphold)."""

_TIME: Final = re.compile(r"([01]?[0-9]|2[0-3])[:.]([0-5][0-9])")
_UNKNOWN: Final = frozenset({"", "?", "-", "–"})
JPEG: Final = b"\xff\xd8\xff"
PNG: Final = b"\x89PNG\r\n\x1a\n"
# The PNG chunks that draw the picture, and its colours; everything else is left out.
PNG_KEPT: Final = frozenset(
    {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB"}
)
# The WebP chunks that draw the picture; EXIF, XMP and the colour profile are left out.
WEBP_KEPT: Final = frozenset({b"VP8 ", b"VP8L", b"VP8X", b"ALPH", b"ANIM", b"ANMF"})
WEBP_LEFT_OUT: Final = 0x20 | 0x08 | 0x04  # VP8X flags: ICC profile, EXIF, XMP


class PaperError(ValueError):
    """The photo or the reading could not be used. The message is for the driver."""


# --- The photos ---------------------------------------------------------------------------


def clean(data: bytes) -> Image:
    """The photo with nothing but the picture: JPEG, PNG or WebP. Raises PaperError."""
    if len(data) > MAX_PICTURE:
        raise PaperError("Ett foto är större än 5 MB. Fota igen med lägre upplösning.")
    if data.startswith(JPEG):
        return Image("image/jpeg", _jpeg(data))
    if data.startswith(PNG):
        return Image("image/png", _png(data))
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return Image("image/webp", _webp(data))
    raise PaperError("Fotona ska vara bilder i JPEG, PNG eller WebP.")


def _broken() -> PaperError:
    return PaperError("Ett foto gick inte att läsa. Fota sidan igen.")


def _jpeg(data: bytes) -> bytes:
    """The JPEG without its application segments (EXIF, XMP, ICC, Photoshop, the thumbnails)
    and comments. Adobe's segment stays, since it says how the colours are stored."""
    out = bytearray(data[:2])
    at, size = 2, len(data)
    while at + 1 < size:
        if data[at] != 0xFF:
            raise _broken()
        marker = data[at + 1]
        if marker == 0xFF:  # a fill byte before the marker
            at += 1
            continue
        if marker == 0xD9:  # the end of the picture; whatever follows is left out
            return bytes(out + b"\xff\xd9")
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            out += data[at : at + 2]
            at += 2
            continue
        if at + 4 > size:
            raise _broken()
        length = int.from_bytes(data[at + 2 : at + 4], "big")
        end = at + 2 + length
        if length < 2 or end > size:
            raise _broken()
        if marker == 0xDA:
            # The start of a scan, then its coded data up to the next marker. In the data a
            # 0xFF is followed by 0x00, a restart marker or another 0xFF.
            while end + 1 < size and not (
                data[end] == 0xFF
                and data[end + 1] not in (0x00, 0xFF)
                and not 0xD0 <= data[end + 1] <= 0xD7
            ):
                end += 1
            out += data[at:end]
            at = end
            continue
        application = 0xE0 <= marker <= 0xEF or marker == 0xFE
        adobe = marker == 0xEE and data[at + 4 : at + 9] == b"Adobe"
        if not application or adobe:
            out += data[at:end]
        at = end
    raise _broken()


def _png(data: bytes) -> bytes:
    """The PNG with only the chunks that draw it: no text, time, EXIF or colour profile."""
    out = bytearray(PNG)
    at = len(PNG)
    while at + 12 <= len(data):
        length = int.from_bytes(data[at : at + 4], "big")
        kind = data[at + 4 : at + 8]
        end = at + 12 + length
        if end > len(data):
            raise _broken()
        if kind in PNG_KEPT:
            out += data[at:end]
        if kind == b"IEND":
            return bytes(out)
        at = end
    raise _broken()


def _webp(data: bytes) -> bytes:
    """The WebP without EXIF, XMP and the colour profile, and its header saying so."""
    chunks = bytearray()
    at = 12
    end_of_file = min(len(data), 8 + int.from_bytes(data[4:8], "little"))
    while at + 8 <= end_of_file:
        kind = data[at : at + 4]
        length = int.from_bytes(data[at + 4 : at + 8], "little")
        end = at + 8 + length + (length & 1)
        if at + 8 + length > end_of_file:
            raise _broken()
        if kind in WEBP_KEPT:
            chunk = bytearray(data[at:end])
            if kind == b"VP8X" and length >= 1:
                chunk[8] &= 0xFF ^ WEBP_LEFT_OUT
            chunks += chunk
        at = end
    if not chunks:
        raise _broken()
    return b"RIFF" + (len(chunks) + 4).to_bytes(4, "little") + b"WEBP" + bytes(chunks)


# --- What AI read ---------------------------------------------------------------------------


def _text(value: Any, limit: int = 200) -> str | None:
    """A field as written, or None when it is empty or could not be read."""
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = " ".join(str(value).split())[:limit].strip()
    return None if text in _UNKNOWN else text


def _time(value: Any) -> tuple[str | None, bool]:
    """A time as TT:MM, and whether something stood there that could not be read. Only the
    digits are put in order (3.21 is 03:21); nothing is guessed."""
    if value is None or isinstance(value, (dict, list, bool)):
        return None, False
    text = str(value).strip()
    if not text or text in ("-", "–"):
        return None, False
    found = _TIME.fullmatch(text)
    if found is None:
        return None, True
    return f"{int(found[1]):02d}:{found[2]}", False


def _end(value: Any) -> events.PaperEnd:
    if not isinstance(value, dict):
        return events.PaperEnd()
    time, unreadable = _time(value.get("time"))
    return events.PaperEnd(
        time=time, place_name=_text(value.get("place"), 80), unreadable=unreadable
    )


def reading(text: str) -> events.PaperReading:
    """What the AI wrote, read with code: the front and the timetable. Raises PaperError."""
    match = re.search(r"\{.*\}", text, re.S)
    try:
        answer = json.loads(match[0] if match else text)
    except ValueError as error:
        raise PaperError("AI:ns avläsning gick inte att läsa som en tidtabell.") from error
    if not isinstance(answer, dict) or not isinstance(answer.get("rows"), list):
        raise PaperError("AI:ns avläsning gick inte att läsa som en tidtabell.")
    rows: list[events.PaperRow] = []
    for raw in answer["rows"][:MAX_ROWS]:
        if not isinstance(raw, dict):
            continue
        name = _text(raw.get("place"), 80)
        if name is None:
            continue
        arrival, late_unread = _time(raw.get("arrival"))
        departure, leave_unread = _time(raw.get("departure"))
        rows.append(
            events.PaperRow(
                place_name=name,
                arrival=arrival,
                departure=departure,
                track=_text(raw.get("track"), 12),
                stops=raw.get("stops") is not False,
                note=_text(raw.get("note"), 200),
                unreadable=late_unread or leave_unread,
            )
        )
    if not rows:
        raise PaperError(
            "AI:n hittade ingen tidtabell på fotona. Fota sidorna med tidtabellen, en i taget."
        )
    return events.PaperReading(
        number=_text(answer.get("number"), 20),
        train_number=_text(answer.get("train"), 20),
        operator=_text(answer.get("operator"), 80),
        start=_end(answer.get("start")),
        end=_end(answer.get("end")),
        rows=rows,
    )


def pages_of(photos: Sequence[bytes]) -> list[Image]:
    """The photos of 1–4 pages, cleaned. Raises PaperError."""
    if not 1 <= len(photos) <= MAX_PAGES:
        raise PaperError(f"Fota 1–{MAX_PAGES} sidor.")
    return [clean(photo) for photo in photos]
