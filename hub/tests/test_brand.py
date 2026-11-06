from __future__ import annotations

import re

import pytest

from hub.brand import GLYPHS, product_name_svg

PRODUCTS = ("HUB", "TKL", "CAD", "CATALOG", "TMBOX", "ID", "PLATFORM")


def test_every_glyph_is_five_by_seven() -> None:
    for char, rows in GLYPHS.items():
        assert len(rows) == 7, char
        assert all(len(row) == 5 and set(row) <= {"#", "."} for row in rows), char


@pytest.mark.parametrize("name", PRODUCTS)
def test_every_product_name_can_be_drawn(name: str) -> None:
    lit = sum(row.count("#") for char in name for row in GLYPHS[char])
    svg = product_name_svg(name)
    assert svg.count("<circle") == lit


def test_hub_is_three_letters_wide_and_seven_dots_high() -> None:
    svg = product_name_svg("HUB")
    match = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    assert match is not None
    assert (float(match[1]), float(match[2])) == (51.0, 21.0)


def test_the_dots_have_the_text_colour_never_blue() -> None:
    svg = product_name_svg("HUB")
    assert 'fill="#c0c5cf"' in svg
    assert "#2347ce" not in svg


def test_an_unknown_character_is_an_error() -> None:
    with pytest.raises(ValueError, match="Q"):
        product_name_svg("QUB")
