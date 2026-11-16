"""Banbilden (4c1, IMPORT-33, I4): the page Topologi in the planning program's PDF.

The picture here is drawn from Värnamo's planning file (the public fixture) as the program
draws it: a round mark per place with its signature above, one line between places on single
track and two side by side on double track, and the short tracks to industries and halts that
the plan has no section for. The organiser's own picture is not in the repository; read
locally, it gives the same 31 places and 30 links, with double track where the plan has it."""

from __future__ import annotations

import json
import math

import pytest

from contracts.meet import MeetPackage, TrackKind
from integrationer import track_picture
from integrationer.tests.pdf_writer import Sheet, pdf
from integrationer.tests.test_station_lists import plan
from integrationer.track_picture import PictureError, read

__all__ = ["plan"]

# Where each place stands on the test's own map, in points from the top left.
AT = {
    "Mkd": (75, 140), "Lek": (115, 140), "Gdö": (155, 140), "Tby": (195, 140),
    "R": (235, 140), "Nlu": (295, 140), "Mot": (335, 140), "Rse": (395, 140),
    "Tre": (435, 140), "Ørm": (475, 140), "Spn": (515, 140), "Sub": (335, 105),
    "Idp": (40, 170), "Ful": (75, 170), "Sbg": (75, 200), "Hld": (215, 170),
    "Ryt": (245, 170), "Ebh": (275, 170), "Hgt": (315, 170), "Gbg": (375, 170),
    "Ela": (265, 230), "Bgn": (305, 230), "Ste": (395, 230), "Gtn": (235, 260),
    "Skh": (275, 260), "Sku": (315, 260), "Stv": (355, 260), "Tve": (315, 300),
    "Tri": (355, 300), "Ons": (395, 300), "Kje": (435, 300),
}  # fmt: skip
# Tracks on the picture that the plan has no section for.
SPURS = [("Mot", "Sub"), ("Nlu", "Bgn"), ("Bgn", "Ela"), ("Gtn", "Skh"), ("Skh", "Sku"),
         ("Tri", "Ons"), ("Ons", "Kje"), ("Tri", "Tve")]  # fmt: skip


def links(plan: MeetPackage) -> dict[frozenset[str], bool]:
    """Every link the picture draws: the plan's parts, double where the section is, and the
    spurs."""
    codes = {p.id: p.code for p in plan.places}
    out = {frozenset(pair): False for pair in SPURS}
    for section in plan.sections:
        for part in section.parts:
            pair = frozenset((codes[part.from_place], codes[part.to_place]))
            out[pair] = section.tracks == TrackKind.DOUBLE
    return out


def picture_pdf(plan: MeetPackage) -> bytes:
    sheet = Sheet().text(42, 40, "Banan", 20).text(42, 70, "Topologi", 13)
    sheet.text(520, 40, "Värnamo Moduldagar", 9)
    for pair, double in links(plan).items():
        a, b = (AT[code] for code in sorted(pair))
        if not double:
            sheet.line(a, b)
            continue
        length = math.dist(a, b)
        nx, ny = -(b[1] - a[1]) / length * 1.1, (b[0] - a[0]) / length * 1.1
        for side in (1, -1):
            sheet.line((a[0] + side * nx, a[1] + side * ny), (b[0] + side * nx, b[1] + side * ny))
    for code, (x, y) in AT.items():
        sheet.mark(x, y)
        sheet.text(x - 1.6 * len(code), y - 3, code, 5.7)
    sheet.text(42, 400, "Godsflöden", 13).text(42, 420, "En lastgräns skrivs som ett tal.", 9)
    return pdf(sheet, Sheet().text(42, 40, "Instruktioner", 13))


def test_the_picture_gives_the_places_the_links_and_double_track(plan: MeetPackage) -> None:
    picture = read(picture_pdf(plan))
    assert picture.page == 1
    assert set(picture.places) == set(AT) == {p.code for p in plan.places}
    assert picture.links == links(plan)
    assert picture.places["Gdö"] == pytest.approx((155, 140), abs=0.5)
    assert sum(picture.links.values()) == 7, "Sbg–Ful–Mkd–Lek–Gdö–Tby–R–Nlu"
    assert picture.path("Gdö", "R", {"Tby"}) == ["Gdö", "Tby", "R"]
    assert picture.path("Gdö", "Ebh", {"Tby", "Hld", "Ryt"}) == ["Gdö", "Tby", "Hld", "Ryt", "Ebh"]
    assert picture.path("Gdö", "Ebh", {"Hld", "Ryt"}) is None, "only through places in between"
    assert picture.branches("Tby") == 3


def test_what_is_not_a_track_picture_is_refused(plan: MeetPackage) -> None:
    with pytest.raises(PictureError, match="inte en PDF"):
        read(b"Banan")
    with pytest.raises(PictureError, match="ingen sida Topologi"):
        read(pdf(Sheet().text(42, 40, "Stationslista Lekby").text(42, 60, "Tåg Dagar Spår")))
    with pytest.raises(PictureError, match="gick inte att läsa"):
        read(b"%PDF-1.4\nnot really\n")
    assert track_picture.is_picture(picture_pdf(plan))
    assert not track_picture.is_picture(b"%PDF-1.4\n")


def photo_transcript(plan: MeetPackage, width: float = 560.0, height: float = 330.0) -> str:
    """What the AI writes for a photo of the test's own map: each signature where it stands, in
    per cent, and the lines between places."""
    places = [{"code": c, "x": x / width * 100, "y": y / height * 100} for c, (x, y) in AT.items()]
    lines = [
        {"a": a, "b": b, "double": d} for pair, d in links(plan).items() for a, b in [sorted(pair)]
    ]
    return "Här är banan:\n" + json.dumps({"places": places, "links": lines}, ensure_ascii=False)


def test_a_photo_of_the_track_written_down_is_the_same_picture(plan: MeetPackage) -> None:
    """4c2 (IMPORT-17): the AI's transcription of a photo, read with code, in map units as wide
    as a printed page."""
    from integrationer.track_picture import PHOTO_WIDTH, from_photo

    picture = from_photo(photo_transcript(plan), 1600, 943)
    assert set(picture.places) == set(AT) and picture.links == links(plan)
    x, y = picture.places["Gdö"]
    assert x == pytest.approx(155 / 560 * PHOTO_WIDTH, abs=0.2)
    assert y == pytest.approx(140 / 330 * PHOTO_WIDTH * 943 / 1600, abs=0.2)
    with pytest.raises(PictureError, match="gick inte att läsa"):
        from_photo("Jag ser en bana.", 100, 100)
    with pytest.raises(PictureError, match="inga driftplatser"):
        from_photo('{"places": [], "links": []}', 100, 100)


def test_the_size_of_a_picture() -> None:
    from integrationer.ai import Image, drawn
    from integrationer.scanned import dimensions

    assert dimensions(Image("image/png", drawn("12", 10))) == (90, 70)
    jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + (
        b"\xff\xc0\x00\x11\x08\x01\xe0\x02\x80\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    assert dimensions(Image("image/jpeg", jpeg)) == (640, 480)
