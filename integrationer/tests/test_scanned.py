"""Skannat (4c2): scanned station lists written down by the hub's own AI, here a stand-in that
answers each picture from a table. Code reads the rows; everything it gave is osäker (I2)."""

from __future__ import annotations

import hashlib
import json

import pytest

from contracts.meet import MeetPackage
from contracts.planning import Certainty
from integrationer import derive, scanned
from integrationer.ai import Image, Service, ask, drawn
from integrationer.scanned import Page, lists, needs_ai, pages, transcribed
from integrationer.station_lists import ListError, verdicts
from integrationer.tests.fake_ai import KEY, FakeAi, serving
from integrationer.tests.pdf_writer import Sheet, pdf
from integrationer.tests.test_station_lists import plan, rows_for, source

__all__ = ["plan"]


def grey(number: str, scale: int = 4) -> tuple[int, int, bytes]:
    """A scanned page: the number in black on white, as raw 8-bit grey pixels."""
    picture = drawn(number, scale)
    width = int.from_bytes(picture[16:20], "big")
    height = int.from_bytes(picture[20:24], "big")
    pixels = bytes(255 for _ in range(width * height))
    return width, height, pixels


def transcript(plan: MeetPackage, code: str, heading: str, part: slice = slice(None)) -> str:
    """What the AI writes for a page of a station's list: the heading and the rows."""
    rows = [
        [*row[:7], "Ej uppehåll" if "Ej uppehåll" in row[13] else ""]
        for row in rows_for(plan, code)[1:]
    ]
    return (
        "```json\n"
        + json.dumps({"station": heading, "rows": rows[part]}, ensure_ascii=False)
        + "\n```"
    )


def test_what_needs_ai() -> None:
    assert needs_ai(b"\xff\xd8\xff", "Lekby.JPG") and needs_ai(b"", "lista.png")
    assert not needs_ai(pdf(Sheet().text(40, 40, "Lekby")), "lista.pdf"), "text is read with code"
    assert needs_ai(pdf(Sheet().scanned(*grey("1"))), "skannad.pdf")
    assert not needs_ai(b"plan", "plan.json")


def test_the_pages_of_a_scanned_pdf_are_pictures() -> None:
    data = pdf(Sheet().scanned(*grey("1")), Sheet().scanned(*grey("2")))
    found = pages(data, "skannad.pdf")
    assert [p.number for p in found] == [1, 2]
    assert all(
        p.image.media_type == "image/png" and p.image.data.startswith(b"\x89PNG") for p in found
    )
    assert found[0].digest != hashlib.sha256(found[0].image.data).hexdigest(), (
        "the prompt's version counts"
    )
    with pytest.raises(ListError, match="ingen skannad bild"):
        pages(pdf(Sheet()), "tom.pdf")
    with pytest.raises(ListError, match="inte en bild"):
        pages(b"GIF89a", "bild.png")


def test_the_price_before_the_ai_starts() -> None:
    """IMPORT-05: the tokens it costs to send the pages, before anything is sent."""
    small = Page(1, Image("image/png", drawn("12", 10)), "d")  # 90 × 70 pixels
    assert scanned.tokens([small]) == 6300 // 750 + len(scanned.PROMPT) // 4
    large = Page(2, Image("image/png", drawn("12", 200)), "e")
    assert scanned.tokens([large], "") == scanned.PICTURE_TOKENS, "the services make it smaller"
    assert scanned.tokens([]) == 0


def test_the_transcription_is_read_with_code(plan: MeetPackage) -> None:
    heading, rows = transcribed(transcript(plan, "Lek", "Lek Lekby"))
    assert heading == "Lek Lekby" and len(rows) > 20 and all(len(r) == 8 for r in rows)
    with pytest.raises(ListError, match="gick inte att läsa"):
        transcribed("Jag ser ingen tabell.")


def test_two_pages_of_one_list_are_one_list_osäker(plan: MeetPackage) -> None:
    """The second page has no heading: it goes on with the list before it."""
    two = [Page(1, Image("image/png", b"a"), "d1"), Page(2, Image("image/png", b"b"), "d2")]
    said = {
        "d1": transcript(plan, "Lek", "Lek Lekby", slice(0, 20)),
        "d2": transcript(plan, "Lek", "", slice(20, None)),
    }
    found = lists("lekby.pdf", two, lambda page: said[page.digest])
    assert found.transcribed and list(found.rows) == ["lekby.pdf · Lekby"]
    rows = found.rows["lekby.pdf · Lekby"]
    assert {r.page for r in rows} == {1, 2} and {r.code for r in rows} == {"Lek"}
    [verdict] = verdicts(found, plan)
    assert not verdict.differences and verdict.agreeing == verdict.rows > 20
    result = derive.draft(found, meet=plan.meet, source=source())
    facts = {f.ref: f for f in result.facts}
    train = result.package.trains[0]
    assert facts[f"train:{train.id}"].certainty == Certainty.UNSURE, "written down by AI"
    assert facts[f"call:{train.calls[0].id}"].origins[0].at.startswith("lekby.pdf · Lekby, sida")
    assert "som AI har skrivit av" in result.report.notes[0]


def test_the_stand_in_answers_a_page_from_its_table(plan: MeetPackage) -> None:
    [page] = pages(pdf(Sheet().scanned(*grey("7"))), "lekby.pdf")
    text = transcript(plan, "Lek", "Lek Lekby")
    with serving(FakeAi(answers={hashlib.sha256(page.image.data).hexdigest(): text})) as fake:
        answer = ask(Service("claude", fake.address, "m", KEY), scanned.PROMPT, [page.image])
    assert answer == text
