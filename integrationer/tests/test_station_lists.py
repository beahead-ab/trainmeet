"""Stationslistorna (4c1, IMPORT-33, IMPORT-27): read with code, and each list judged against the
planning file row by row.

The lists here are made from Värnamo's planning file (the public fixture, H54) in the planning
program's own format: Tåg, Dagar, Spår, Ank, Från, Avg, Till, the day boxes and Anmärkningar.
The organiser's own 14 lists are not in the repository, as they name the vehicles in the
trains; run against them locally, all 14 agree with the plan."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from contracts.meet import Meet, MeetPackage
from contracts.planning import Source, SourceKind
from integrationer import planning_json, station_lists
from integrationer.station_lists import ListError, check, member_name, parse_days, read, verdicts

FIXTURE = Path(__file__).parent / "fixtures" / "varnamo.json.gz"
SHORT = {"mon": "M", "tue": "Ti", "wed": "O", "thu": "To", "fri": "F", "sat": "L", "sun": "S"}
HEADER = [
    "Tåg",
    "Dagar",
    "Spår",
    "Ank",
    "Från",
    "Avg",
    "Till",
    "M",
    "Ti",
    "O",
    "To",
    "F",
    "L",
    "Anmärkningar",
]


def source(kind: SourceKind = SourceKind.STATION_LISTS) -> Source:
    return Source(
        id="u-lists",
        kind=kind,
        filename="lists.zip",
        size=1,
        sha256="a" * 64,
        level=1,
        added=datetime(2026, 11, 16, tzinfo=UTC),
    )


@pytest.fixture(scope="module")
def plan() -> MeetPackage:
    meet = Meet(id="varnamo", name="Värnamo", country="se", timezone="Europe/Stockholm")
    data = FIXTURE.read_bytes()
    return planning_json.read(data, meet=meet, source=source(SourceKind.PLANNING_JSON)).package


def rows_for(plan: MeetPackage, code: str) -> list[list[str]]:
    """A station's list as the planning program prints it."""
    place = next(p for p in plan.places if p.code == code)
    names = {p.id: p.name for p in plan.places}
    out = [HEADER]
    for train in plan.trains:
        for call in train.calls:
            if call.place != place.id or not (call.arrival or call.departure):
                continue
            days = "Dagl" if len(train.days) == 7 else ",".join(SHORT[d] for d in train.days)
            label = " ".join(x for x in (train.operator, train.train_type, train.number) if x)
            out.append(
                [
                    label,
                    days,
                    call.track or "",
                    call.arrival or "",
                    names[train.calls[0].place],
                    call.departure or "",
                    names[train.calls[-1].place],
                    *[""] * 6,
                    ("Ej uppehåll" if not call.stops else "") + "I tåget: ett fordon.",
                ]
            )
    return out


def odt(rows: list[list[str]]) -> bytes:
    cells = "".join(
        "<table:table-row>"
        + "".join(f"<table:table-cell><text:p>{escape(c)}</text:p></table:table-cell>" for c in row)
        + "</table:table-row>"
        for row in rows
    )
    content = (
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        f"<office:body><office:text><table:table>{cells}</table:table></office:text></office:body>"
        "</office:document-content>"
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr("content.xml", content)
    return stream.getvalue()


def xlsx(rows: list[list[str]]) -> bytes:
    def column(i: int) -> str:
        return chr(65 + i) if i < 26 else "A" + chr(65 + i - 26)

    body = "".join(
        f'<row r="{r + 1}">'
        + "".join(
            f'<c r="{column(i)}{r + 1}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
            for i, v in enumerate(row)
            if v
        )
        + "</row>"
        for r, row in enumerate(rows)
    )
    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{body}</sheetData></worksheet>"
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return stream.getvalue()


class _Cp437Name(zipfile.ZipInfo):
    """A name written as the planning program writes it: UTF-8 bytes without the UTF-8 flag."""

    def _encodeFilenameFlags(self) -> tuple[bytes, int]:
        return self.filename.encode("cp437"), self.flag_bits


def lists_zip(files: dict[str, bytes], *, utf8: bool = False) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo(name) if utf8 else _Cp437Name(name.encode().decode("cp437"))
            archive.writestr(info, data)
    return stream.getvalue()


def test_every_list_agrees_with_the_plan_row_by_row(plan: MeetPackage) -> None:
    files = {
        f"{code} {name}.odt": odt(rows_for(plan, code))
        for code, name in (("Lek", "Lekby"), ("Mkd", "Munkerød"), ("R", "Rotebro"))
    }
    found = read(lists_zip(files), "Station dispatch lists.zip")
    assert sorted(found.rows) == ["Lek Lekby.odt", "Mkd Munkerød.odt", "R Rotebro.odt"], (
        "CP437 names read as written"
    )
    judged = verdicts(found, plan)
    assert [(v.document, v.differences) for v in judged] == [(name, []) for name in sorted(files)]
    assert all(v.agreeing == v.rows > 20 for v in judged)
    result = check(lists_zip(files), "lists.zip", plan=plan, source=source())
    assert result.checks_only and result.package == plan, "the draft does not change"
    assert result.report.notes == ["3 av 3 stationslistor stämmer med planeringsfilen rad för rad."]
    assert result.report.level == 1


def test_a_list_that_differs_says_where(plan: MeetPackage) -> None:
    rows = rows_for(plan, "Lek")
    rows[1][3] = rows[1][5] = "23:59"  # a time
    rows[2][2] = "9"  # a track
    rows.append(["SJ X 99999", "Dagl", "1", "12:00", "Lekby", "12:00", "Spiten", *[""] * 6, ""])
    [verdict] = verdicts(read(odt(rows), "Lek Lekby.odt"), plan)
    assert verdict.place is not None and verdict.agreeing == verdict.rows - 3
    text = " ".join(verdict.differences)
    assert "23:59 i listan" in text and "spår 9 i listan" in text
    assert "Tåg 99999 vid Lekby finns inte i planen." in verdict.differences


def test_excel_and_csv_are_read_the_same_way(plan: MeetPackage) -> None:
    rows = rows_for(plan, "Gdö")
    [from_excel] = verdicts(read(xlsx(rows), "Gdö Gårdsjö.xlsx"), plan)
    out = io.StringIO()
    csv.writer(out, delimiter=";").writerows(rows)
    [from_csv] = verdicts(read(out.getvalue().encode(), "Gdö Gårdsjö.csv"), plan)
    assert from_excel.differences == from_csv.differences == []
    assert from_excel.rows == from_csv.rows > 20


def test_the_days_and_passages(plan: MeetPackage) -> None:
    assert parse_days("Dagl") == set(range(7))
    assert parse_days("M-O") == {0, 1, 2}
    assert parse_days("To-L") == {3, 4, 5}
    assert parse_days("Ti,O") == {1, 2}
    assert parse_days("L-M") == {5, 6, 0}
    assert parse_days("tisdagar") is None
    rows = rows_for(plan, "Lek")
    found = read(odt(rows), "Lek Lekby.odt")
    passing = [r for r in found.rows["Lek Lekby.odt"] if not r.stops]
    assert passing, "Ej uppehåll is a passage"
    assert not hasattr(passing[0], "note"), "what the list says about the vehicles is never read in"


def test_what_is_not_a_list_is_refused_or_left_out() -> None:
    with pytest.raises(ListError, match="ingen stationslista"):
        read(odt([["Namn", "Telefon"], ["Lekby", "201"]]), "Telefonlista.odt")
    with pytest.raises(ListError, match="ogiltiga"):
        read(lists_zip({"../evil.odt": b"x"}, utf8=True), "lists.zip")
    with pytest.raises(ListError, match="egna definitioner"):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("content.xml", '<!DOCTYPE x [<!ENTITY a "b">]><x/>')
        read(stream.getvalue(), "Lek Lekby.odt")
    with pytest.raises(ListError, match="inte stationslistor"):
        read(b"x", "Banan.pdf")
    rows = [
        HEADER,
        ["CN 11", "Dagl", "1", "", "", "", "", *[""] * 7],
        ["SJ X 1", "Dagl", "1", "06:00", "A", "06:00", "B", *[""] * 7],
    ]
    found = read(odt(rows), "Sku Skuggevik.odt")
    assert found.left_out == ["Sku Skuggevik.odt, rad 2: CN 11 har ingen tid (växling?)."]


def test_a_name_without_the_utf8_flag_is_read_as_written() -> None:
    info = zipfile.ZipInfo("Mkd Munkerød.odt".encode().decode("cp437"))
    assert member_name(info) == "Mkd Munkerød.odt"
    assert station_lists.is_lists("Lek Lekby.ODT") and not station_lists.is_lists("plan.json")
