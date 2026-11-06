"""The TMBox texts in five languages (old Server's test_tmbox_language.py and the language parts
of test_terminal16_20x4.py): complete, used, and short enough for the box."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from drift import lcd
from drift.terminal_text import COUNTRY_LANGUAGE, LANGUAGES, MESSAGES, notice, text

SOURCE = Path(__file__).resolve().parents[1] / "terminal.py"


def test_five_complete_catalogues() -> None:
    assert LANGUAGES == ("sv", "en", "da", "nb", "de")
    for code in LANGUAGES:
        assert set(MESSAGES[code]) == set(MESSAGES["sv"]), code
        assert all(MESSAGES[code].values()), code
    assert set(COUNTRY_LANGUAGE.values()) <= set(LANGUAGES)


def test_a_text_without_a_row_stays_as_it_is() -> None:
    """Codes, numbers and names are never in the table, so they pass through unchanged."""
    assert text("de", "Nby") == "Nby"
    assert text("en", "101") == "101"
    assert text("xx", "Nr# A:Kö") == "Nr# A:Kö", "an unknown language is Swedish"


def keys_in_terminal() -> set[str]:
    """Every text the view looks up: t(...) and text(...) calls, hints, and the labels of
    the ("action", "Label") pairs, as the old test found them."""
    tree = ast.parse(SOURCE.read_text())

    def constants(node: ast.AST) -> list[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.IfExp):
            return constants(node.body) + constants(node.orelse)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Dict):
            return [value for item in node.value.values for value in constants(item)]
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Dict)
        ):
            found = [v for item in node.func.value.values for v in constants(item)]
            return found + [v for arg in node.args[1:] for v in constants(arg)]
        return []

    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else None
            attribute = node.func.attr if isinstance(node.func, ast.Attribute) else None
            if name == "t" and node.args:
                keys |= set(constants(node.args[0]))
            if attribute == "text" and len(node.args) > 1:
                keys |= set(constants(node.args[1]))
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in {"hint", "question", "word"}
            for target in node.targets
        ):
            keys |= set(constants(node.value))
        if (
            isinstance(node, ast.Tuple)
            and len(node.elts) == 2
            and all(isinstance(item, ast.Constant) for item in node.elts)
        ):
            first, second = (item.value for item in node.elts)  # type: ignore[attr-defined]
            if (
                isinstance(first, str)
                and isinstance(second, str)
                and re.fullmatch(r"[a-z_]+", first)
                and not re.fullmatch(r"[a-z_]+", second)
            ):
                keys.add(second)
    return keys - {"", "C/D"}


def test_every_text_the_box_shows_is_in_every_language() -> None:
    keys = keys_in_terminal()
    assert len(keys) > 60
    assert not keys - set(MESSAGES["sv"]), sorted(keys - set(MESSAGES["sv"]))


def test_every_short_label_is_in_every_language() -> None:
    from drift.terminal import SHORT_LABELS

    assert not set(SHORT_LABELS.values()) - set(MESSAGES["sv"])
    assert not set(SHORT_LABELS) - set(MESSAGES["sv"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_notice_fits_and_can_be_drawn(language: str) -> None:
    """FLERA TÅG - ADMIN was 17 characters: the frame raised and the box got no answer."""
    for value in (
        "ANNAN SIDA",
        "INGET TÅG",
        "FLERA TÅG ADMIN",
        "INGA FRÅGOR",
        "UNDANSTÄLLT",
        "12345 MOTTAGET",
        "12345 ÅTERTAGET",
        "12345 NEKAT",
        "12345 ANK SP12A",
        "12345 UPPT SPÅR",
    ):
        shown = notice(language, value)
        assert len(lcd.cells(shown)) <= 16, (language, shown)
        assert lcd.fits([shown]), (language, shown)


def test_the_arrival_track_is_said_in_every_language() -> None:
    """Benny #197: after #In the box names the track the train came in on."""
    assert notice("sv", "93 ANK SP2a") == "93 ANK SP2a"
    assert notice("en", "93 ANK SP2a") == "93 ARR TRK2a"
    assert notice("de", "93 ANK SP2a") == "93 AN GL2a"
    assert notice("en", "93 UPPT SPÅR") == "93 TRK BUSY"


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_hint_fits_beside_the_clock(language: str) -> None:
    """A hint has eleven cells; the clock and a space take the other five of a 16×2."""
    tree = ast.parse(SOURCE.read_text())
    hints: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "hint" for target in node.targets
        ):
            for found in ast.walk(node.value):
                if isinstance(found, ast.Constant) and isinstance(found.value, str):
                    hints.add(found.value)
    hints = {hint for hint in hints if hint and "{" not in hint and hint in MESSAGES["sv"]}
    assert len(hints) > 15
    for hint in hints:
        shown = text(language, hint)
        assert len(lcd.cells(shown)) <= 11, (language, shown)
        assert lcd.fits([shown]), (language, shown)


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_state_word_fits_beside_a_two_digit_track(language: str) -> None:
    track = text(language, "Sp {track}", track="99")
    for word in (
        "Vill skicka",
        "Väntar svar",
        "Klar att avgå",
        "Klarerad",
        "Avgått",
        "På väg hit",
        "Ej begärd",
        "Ej skickad",
    ):
        shown = text(language, word)
        assert len(shown) + 1 + len(track) <= 20, (language, shown)
        assert lcd.fits([shown]), (language, shown)
    for word in ("Till", "Från"):
        assert text(language, word)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_entry_keeps_its_digits_at_column_five(language: str) -> None:
    assert len(text(language, "TÅG: _____")) == 10
    assert text(language, "TÅG: _____").endswith(" _____")
