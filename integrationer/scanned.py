"""Skannat (4c2, IMPORT-15, IMPORT-33): station lists that are not text, transcribed by the
hub's own AI. A photo of a list (JPEG or PNG), or a PDF whose pages are scanned pictures.

AI only writes down what the page says; code reads the rows, as for the lists in text
(station_lists.py), and everything it gave is osäker until confirmed (I2). Each page's
transcription is kept by the picture's sha256, so the same file gives the same result and never
costs twice (principle 7). What a list says about the vehicles in a train is not asked for.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTFigure, LTImage, LTPage

from integrationer import pdf_page
from integrationer.ai import Image
from integrationer.station_lists import HEADER_WORDS, ListError, Lists, rows_from, title

PICTURES: Final = (".jpg", ".jpeg", ".png")
MAX_PICTURE: Final = 5 * 1024 * 1024  # what the AI services take per picture
MAX_PAGES: Final = 40
VERSION: Final = "listor-1"  # a new prompt is a new transcription
PROMPT: Final = """Bilden är en sida ur en stationslista för en modelljärnvägsträff: en tabell med
kolumnerna Tåg, Dagar, Spår, Ank, Från, Avg, Till och Anmärkningar (på danska eller norska Tog,
Dage, Spor, Ank, Fra, Afg, Til och Bemærkninger). Skriv av den exakt som den står, utan att
tolka, rätta eller lägga till något.

Svara bara med JSON, så här:
{"station": "rubriken över tabellen, eller tom om sidan saknar rubrik",
 "rows": [["Tåg", "Dagar", "Spår", "Ank", "Från", "Avg", "Till", "Anmärkning"], ...]}

En rad per tågrad i tabellen, i ordning, utan tabellhuvudet. En tom cell blir "". Tider och
tecken skrivs som de står, också parenteser. I Anmärkning skriver du bara "Ej uppehåll" när
det står i anmärkningen (eller "Uden ophold", "Uten opphold"); annars "". Ta inte med något om
fordonen i tåget."""


@dataclass(frozen=True)
class Page:
    number: int
    image: Image
    digest: str


def is_picture(name: str) -> bool:
    return Path(name).suffix.casefold() in PICTURES


def needs_ai(data: bytes, name: str) -> bool:
    """A picture, or a PDF with no text to read on its pages."""
    if is_picture(name):
        return True
    if not pdf_page.is_pdf(data):
        return False
    try:
        read = pdf_page.pages(data, limit=MAX_PAGES)
    except pdf_page.PdfError:
        return False
    return bool(read) and all(not page.words for page in read)


def pages(data: bytes, name: str) -> list[Page]:
    """The pages to transcribe, as pictures. Raises ListError."""
    if is_picture(name):
        return [_page(1, _picture(data, name))]
    try:
        layouts = list(extract_pages(io.BytesIO(data), maxpages=MAX_PAGES, laparams=LAParams()))
    except Exception as error:  # pdfminer raises many kinds for a broken file
        raise ListError("PDF:en gick inte att läsa.") from error
    found = []
    for number, layout in enumerate(layouts, 1):
        image = _largest(layout)
        if image is None:
            raise ListError(f"{name}, sida {number}: ingen skannad bild att skriva av.")
        found.append(_page(number, _from_pdf(image, name, number)))
    if not found:
        raise ListError(f"{name}: inga sidor att skriva av.")
    return found


def _page(number: int, image: Image) -> Page:
    digest = hashlib.sha256(VERSION.encode() + b"\0" + image.data).hexdigest()
    return Page(number, image, digest)


def _picture(data: bytes, name: str) -> Image:
    if len(data) > MAX_PICTURE:
        raise ListError(f"{name} är större än 5 MB. Fota eller skanna med lägre upplösning.")
    if data[:3] == b"\xff\xd8\xff":
        return Image("image/jpeg", data)
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return Image("image/png", data)
    raise ListError(f"{name} är inte en bild i JPEG eller PNG.")


def _largest(layout: LTPage) -> LTImage | None:
    images: list[LTImage] = []

    def walk(items: Any) -> None:
        for item in items:
            if isinstance(item, LTImage):
                images.append(item)
            elif isinstance(item, LTFigure):
                walk(item)

    walk(layout)
    return max(images, key=lambda i: i.width * i.height, default=None)


def _from_pdf(image: LTImage, name: str, number: int) -> Image:
    """The scanned page as JPEG, as it is in the PDF, or as PNG from 8-bit grey or RGB."""
    stream = image.stream
    filters = [f for f, _ in stream.get_filters()]
    where = f"{name}, sida {number}"
    if filters and str(filters[-1]).endswith("DCTDecode"):
        return _picture(stream.get_rawdata() or b"", where)
    width, height = int(stream.get_any(("W", "Width"))), int(stream.get_any(("H", "Height")))
    bits = int(stream.get_any(("BPC", "BitsPerComponent"), 8))
    space = str(stream.get_any(("CS", "ColorSpace"), ""))
    channels = 3 if "RGB" in space else 1 if "Gray" in space else 0
    if bits != 8 or not channels:
        raise ListError(
            f"{where}: bilden är sparad på ett sätt hubben inte läser än. Skanna som JPEG eller "
            "fota sidan."
        )
    pixels = stream.get_data()
    if len(pixels) < width * height * channels:
        raise ListError(f"{where}: bilden gick inte att läsa.")
    return _picture(_png(pixels, width, height, channels), where)


def _png(pixels: bytes, width: int, height: int, channels: int) -> bytes:
    row = width * channels
    raw = b"".join(b"\x00" + pixels[y * row : (y + 1) * row] for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    kind = 2 if channels == 3 else 0
    header = struct.pack(">IIBBBBB", width, height, 8, kind, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def transcribed(text: str) -> tuple[str, list[list[str]]]:
    """The station and the rows from what the AI wrote. Raises ListError."""
    match = re.search(r"\{.*\}", text, re.S)
    try:
        answer = json.loads(match[0] if match else text)
        station = str(answer.get("station") or "").strip()
        rows = [[str(cell or "").strip() for cell in row][:8] for row in answer["rows"]]
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ListError("AI:ns avskrift gick inte att läsa som en tabell.") from error
    return station, [[*row, *[""] * (8 - len(row))] for row in rows]


def lists(name: str, found_pages: list[Page], transcript: Callable[[Page], str]) -> Lists:
    """The lists the pages say, read with code from each page's transcription. A page without
    a heading goes on with the list before it."""
    found = Lists(transcribed=True)
    station = ""
    for page in found_pages:
        heading, rows = transcribed(transcript(page))
        heading = re.split(r"\s+\+\s+", heading)[0].strip()
        station = heading or station
        if not station:
            raise ListError(f"{name}, sida {page.number}: stationens namn saknas över tabellen.")
        table = [HEADER_WORDS, *([*row[:7], *[""] * 6, row[7]] for row in rows)]
        named, _ = title(station)
        rows_from(f"{name} · {named}", table, found, station, page.number)
    if not found.rows:
        raise ListError(
            f"{name}: AI:n hittade ingen stationslista. " + " ".join(found.left_out[:2])
        )
    return found
