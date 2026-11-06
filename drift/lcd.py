"""A 16×2 (or 20×4) picture as HD44780 cells, as the old Server sent it (terminal16_glyphs).

Only the characters a picture needs get one of the eight own-character places. Nothing is
transliterated: a character the box cannot draw is an error, so Drift picks another picture.
The browser box draws the Unicode lines; a physical box draws the cells and glyphs.
"""

from __future__ import annotations

from typing import Any, Final
from unicodedata import normalize

ENCODING: Final = "hd44780-5x8-cgram-v1"
GEOMETRIES: Final = ((2, 16), (4, 20))

# 5×8 bitmaps, one row per number, from the old Server. ASCII \ and ~ differ between ROMs.
GLYPHS: Final[dict[str, tuple[int, ...]]] = {
    "\\": (16, 8, 4, 2, 1, 0, 0, 0),
    "~": (0, 0, 8, 21, 2, 0, 0, 0),
    "Å": (4, 10, 4, 14, 17, 31, 17, 17),
    "å": (4, 10, 4, 14, 1, 15, 17, 15),
    "Ä": (10, 0, 14, 17, 31, 17, 17, 0),
    "ä": (10, 0, 14, 1, 15, 17, 15, 0),
    "Ö": (10, 0, 14, 17, 17, 17, 14, 0),
    "ö": (10, 0, 0, 14, 17, 17, 14, 0),
    "Æ": (7, 12, 20, 23, 28, 20, 23, 0),
    "æ": (0, 0, 26, 5, 15, 20, 15, 0),
    "Ø": (15, 19, 21, 21, 21, 25, 30, 0),
    "ø": (0, 0, 15, 19, 21, 25, 30, 0),
    "Ü": (10, 0, 17, 17, 17, 17, 14, 0),
    "ü": (10, 0, 0, 17, 17, 19, 13, 0),
    "é": (2, 4, 14, 17, 31, 16, 14, 0),
    "ß": (6, 9, 9, 14, 9, 9, 22, 0),
    "ẞ": (14, 17, 18, 20, 18, 17, 22, 0),
    "◀": (1, 3, 7, 15, 7, 3, 1, 0),
    "▶": (16, 24, 28, 30, 28, 24, 16, 0),
}


def cells(value: str) -> str:
    """Composed and decomposed Å/Ä/Ö take exactly one cell."""
    return normalize("NFC", value)


def custom_characters(lines: list[str]) -> list[str]:
    found = {char for line in lines for char in cells(line)}
    return sorted(char for char in found if char in GLYPHS or not 32 <= ord(char) <= 126)


def fits(lines: list[str]) -> bool:
    """Every character known, and at most eight needing an own-character place."""
    custom = custom_characters(lines)
    return len(custom) <= 8 and all(char in GLYPHS for char in custom)


def encode(lines: list[str]) -> dict[str, Any]:
    normalized = [cells(line) for line in lines]
    geometry = (len(normalized), len(normalized[0]) if normalized else 0)
    if geometry not in GEOMETRIES or any(len(line) != geometry[1] for line in normalized):
        raise ValueError("Bilden ska vara två hela rader om 16 tecken eller fyra om 20.")
    custom = custom_characters(normalized)
    unknown = [char for char in custom if char not in GLYPHS]
    if unknown:
        raise ValueError("Tecken som boxen inte kan rita: " + " ".join(unknown))
    if len(custom) > 8:
        raise ValueError("Fler än åtta egna tecken i en bild.")
    slots = {char: slot for slot, char in enumerate(custom)}
    return {
        "encoding": ENCODING,
        "cells": [[slots.get(char, ord(char)) for char in line] for line in normalized],
        "glyphs": [
            {"slot": slots[char], "character": char, "rows": list(GLYPHS[char])} for char in custom
        ],
    }


def row(left: str = "", right: str = "", width: int = 16) -> str:
    """`left` and `right` on one row. An identity is never cut: the left part gives way."""
    left, right = cells(left), cells(right)
    room = width - len(right)
    if len(left) > room:
        left = left[: max(0, room)]
    return left + " " * (width - len(left) - len(right)) + right


def centered(text: str, width: int = 16) -> str:
    """In the middle of a row; the odd cell, if any, goes to the right."""
    text = cells(text)[:width]
    return (" " * ((width - len(text)) // 2) + text).ljust(width)
