"""Efter pappret (LOK-29): the photos cleaned before anything is sent, and the AI's reading read
with code, where a time that could not be read stays empty and is never guessed."""

from __future__ import annotations

import json
import struct
import zlib

import pytest

from integrationer import paper
from integrationer.ai import drawn

PLACE = b"GPS 57.1834 N 14.0432 E"


def segment(marker: int, body: bytes) -> bytes:
    return bytes([0xFF, marker]) + (len(body) + 2).to_bytes(2, "big") + body


def png_chunk(kind: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(kind + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def webp_chunk(kind: bytes, body: bytes) -> bytes:
    return kind + len(body).to_bytes(4, "little") + body + (b"\x00" if len(body) % 2 else b"")


def test_a_jpeg_keeps_the_picture_and_loses_the_cameras_data() -> None:
    """EXIF with the place, XMP, the comment and what follows the end are left out; the
    tables, the frame and the scan's data stay, and Adobe's colour segment too."""
    tables = segment(0xDB, b"\x00" + bytes(64))
    frame = segment(0xC0, b"\x08\x00\x10\x00\x10\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01")
    adobe = segment(0xEE, b"Adobe\x00\x64\x00\x00\x00\x00\x01")
    scan = (
        segment(0xDA, b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00") + b"\x12\xff\x00\x34\xff\xd0\x56"
    )
    photo = (
        b"\xff\xd8"
        + segment(0xE1, b"Exif\x00\x00" + PLACE)
        + segment(0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x>" + PLACE + b"</x>")
        + segment(0xFE, b"Pixel 9")
        + adobe
        + tables
        + frame
        + scan
        + b"\xff\xd9"
        + b"MotionPhoto"
        + PLACE
    )
    cleaned = paper.clean(photo)
    assert cleaned.media_type == "image/jpeg"
    assert cleaned.data == b"\xff\xd8" + adobe + tables + frame + scan + b"\xff\xd9"
    assert PLACE not in cleaned.data and b"Pixel" not in cleaned.data


def test_a_png_and_a_webp_lose_their_text_and_exif() -> None:
    picture = drawn("4521")
    text = png_chunk(b"tEXt", b"Comment\x00" + PLACE)
    exif = png_chunk(b"eXIf", b"MM\x00*" + PLACE)
    assert paper.clean(picture[:33] + text + exif + picture[33:]).data == picture
    vp8x = webp_chunk(b"VP8X", bytes([0x2C, 0, 0, 0, 15, 0, 0, 15, 0, 0]))
    image = webp_chunk(b"VP8L", b"\x2f\x0f\xc0\x03\x00")
    body = vp8x + webp_chunk(b"ICCP", PLACE) + image + webp_chunk(b"EXIF", PLACE)
    webp = b"RIFF" + (len(body) + 4).to_bytes(4, "little") + b"WEBP" + body
    cleaned = paper.clean(webp).data
    assert PLACE not in cleaned and cleaned[8:12] == b"WEBP"
    assert cleaned[20] == 0x00, "the flags no longer say ICC or EXIF"
    assert int.from_bytes(cleaned[4:8], "little") == len(cleaned) - 8


def test_only_pictures_of_a_reasonable_size_are_read() -> None:
    with pytest.raises(paper.PaperError, match="JPEG, PNG eller WebP"):
        paper.clean(b"GIF89a" + bytes(32))
    with pytest.raises(paper.PaperError, match="5 MB"):
        paper.clean(b"\xff\xd8\xff" + bytes(6 * 1024 * 1024))
    with pytest.raises(paper.PaperError, match="gick inte att läsa"):
        paper.clean(b"\xff\xd8\xff\xe1\x00")
    with pytest.raises(paper.PaperError, match="1–4"):
        paper.pages_of([drawn("1234")] * 5)


def test_the_reading_is_read_with_code_and_nothing_is_guessed() -> None:
    """LOK-29: a time that stands but cannot be read is empty and its row marked; an empty one
    is just empty; 3.21 is 03:21. The front as written."""
    said = {
        "number": "24",
        "train": "G 4521",
        "operator": "?",
        "start": {"time": "3.01", "place": "Charlottendal"},
        "end": {"time": "05:3?", "place": "Särö"},
        "rows": [
            {"place": "Charlottendal", "arrival": "", "departure": "03:21", "track": "52"},
            {"place": "Väster", "departure": "3:27", "stops": False, "note": "Ej uppehåll"},
            {"place": "Gårdsjö", "arrival": "03:3?", "departure": "03:34", "track": "3"},
            {"place": "", "arrival": "03:40"},
            "inte en rad",
        ],
    }
    read = paper.reading("Avskriften:\n" + json.dumps(said) + "\nKlart.")
    assert (read.number, read.train_number, read.operator) == ("24", "G 4521", None)
    assert (read.start.time, read.start.place_name, read.start.unreadable) == (
        "03:01",
        "Charlottendal",
        False,
    )
    assert (read.end.time, read.end.unreadable) == (None, True)
    assert [(r.place_name, r.arrival, r.departure, r.stops, r.unreadable) for r in read.rows] == [
        ("Charlottendal", None, "03:21", True, False),
        ("Väster", None, "03:27", False, False),
        ("Gårdsjö", None, "03:34", True, True),
    ]
    assert all(row.place is None for row in read.rows), "Drift matches the places"
    with pytest.raises(paper.PaperError, match="tidtabell"):
        paper.reading("Jag ser ingen tidtabell.")
    with pytest.raises(paper.PaperError, match="ingen tidtabell"):
        paper.reading(json.dumps({"rows": []}))
