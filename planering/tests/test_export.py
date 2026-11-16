"""Exporten (PLAN-07, F25): stationstidtabeller to print, the whole timetable and the duties as
CSV for a spreadsheet, and the sources as a ZIP."""

from __future__ import annotations

import csv
import io
import zipfile

from planering import export
from planering.tests.test_planning import package


def rows(data: bytes) -> list[list[str]]:
    assert data.startswith("﻿".encode()), "Excel reads å, ä and ö"
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig")), delimiter=";"))


def test_the_whole_timetable_one_row_per_call() -> None:
    plan = package()
    table = rows(export.timetable_csv(plan))
    assert table[0][:8] == [
        "Tåg",
        "Tågslag",
        "Bolag",
        "Dagar",
        "Nr",
        "Driftplats",
        "Ankomst",
        "Avgång",
    ]
    assert len(table) == 1 + sum(len(t.calls) for t in plan.trains)
    first = table[1]
    assert (first[0], first[3], first[5], first[7], first[9]) == (
        "101",
        "Mån",
        "Norrby",
        "06:00",
        "1",
    )


def test_the_duties_leg_by_leg() -> None:
    plan = package()
    table = rows(export.duties_csv(plan))
    assert table[0] == ["Köruppdrag", "Del", "Tåg", "Dagar", "Från", "Avgång", "Till", "Ankomst"]
    assert len(table) == 1 + sum(len(d.legs) for d in plan.duties)
    assert table[1][2:] and table[1][4] and table[1][5]


def test_station_timetables_one_page_per_place_in_time_order_and_escaped() -> None:
    plan = package()
    trains = [
        t.model_copy(update={"note": "<script>alert(1)</script>"}) if t.id == "t101" else t
        for t in plan.trains
    ]
    page = export.station_timetables(
        plan.model_copy(update={"trains": trains}), "Provbanan · Stationstidtabeller", "Version 1"
    ).decode()
    assert page.count("<section>") == len(plan.places)
    assert "<h2>Åsen</h2>" in page
    assert "<script>" not in page and "&lt;script&gt;" in page, "every text is escaped"
    norrby = page.split("<h2>Norrby</h2>")[1].split("</section>")[0]
    times = [cell.split("</td>")[0] for cell in norrby.split('<td class="tid">')[1:]]
    departures = [t for t in times[1::2] if t]
    assert departures == sorted(departures), "in time order"


def test_a_file_name_is_plain() -> None:
    assert export.filename("Värnamo Moduldagar", "tidtabell", "csv", 2) == (
        "varnamo-moduldagar-v2-tidtabell.csv"
    )
    assert export.filename("Å", "paket", "json", None) == "a-utkast-paket.json"


def test_the_sources_zip_is_the_files_as_they_came() -> None:
    data = export.sources_zip([("plan.json", b"1"), ("plan.json", b"2"), ("../x", b"3")])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.namelist() == ["plan.json", "2-plan.json", ".._x"]
        assert archive.read("2-plan.json") == b"2"
    assert export.sources_zip([("a", b"1")]) == export.sources_zip([("a", b"1")]), "the same ZIP"


def test_days_read_as_in_planering() -> None:
    assert [
        export.days(d) for d in (["mon"], ["mon", "tue", "wed"], ["mon", "fri"], export.WEEK)
    ] == [
        "Mån",
        "Mån–Ons",
        "Mån, Fre",
        "Dagl",
    ]
