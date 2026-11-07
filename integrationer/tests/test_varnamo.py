"""Värnamo Moduldagar 2026 as the key (H54). The fixture is the organiser's planning file,
anonymised: without participants, vehicle contributions, owners, phone numbers and logos.

The numbers are the old Cloud's (test_varnamo_acceptance), where the station lists confirmed
the plan row for row. What is new is the model: sections are the plan's clearance sections.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from contracts.common import Weekday
from contracts.meet import Meet, PlaceKind
from contracts.planning import Certainty, ImportResult, Source, SourceKind
from integrationer.planning_json import read

FIXTURE = Path(__file__).parent / "fixtures" / "varnamo.json.gz"


def load() -> ImportResult:
    data = FIXTURE.read_bytes()
    source = Source(
        id="varnamo-plan",
        kind=SourceKind.PLANNING_JSON,
        filename="Värnamo Moduldagar.json",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        level=4,
        added=datetime(2026, 11, 6, tzinfo=UTC),
    )
    return read(data, meet=Meet(id="varnamo", name="Värnamo Moduldagar"), source=source)


@pytest.fixture(scope="module")
def result() -> ImportResult:
    return load()


def codes(result: ImportResult, kind: PlaceKind) -> set[str]:
    return {place.code for place in result.package.places if place.kind == kind}


def test_the_plan_is_read_in_full(result: ImportResult) -> None:
    report = result.report
    assert (report.trains, report.calls, report.sections, report.parts, report.shunting) == (
        228,
        1366,
        17,
        22,
        3,
    )
    assert sum(report.places.values()) == 31
    assert (report.duties, report.turns, report.train_types) == (141, 46, 12)
    assert result.questions == []


def test_the_places_kinds(result: ImportResult) -> None:
    assert codes(result, PlaceKind.SHADOW_YARD) == {"Sbg", "Gbg", "Spn"}
    assert len(codes(result, PlaceKind.MANNED)) == 11
    assert codes(result, PlaceKind.REMOTE) == {"Tby", "Stv", "Tri", "Idp"}
    assert codes(result, PlaceKind.UNMANNED) == {"Skh", "Tve"}
    # Tremetsrud and Ørmen lie inside Rise–Spiten and end no section: halts along it.
    assert {"Tre", "Ørm", "Hld", "Ryt", "Hgt"} <= codes(result, PlaceKind.HALT)
    names = {place.id: place.code for place in result.package.places}
    remote = {p.code: names[p.remote_from] for p in result.package.places if p.remote_from}
    assert remote == {"Tby": "Gdö", "Stv": "Ste", "Tri": "Ste", "Idp": "Ful"}


def test_sections_are_the_clearance_sections(result: ImportResult) -> None:
    names = {place.id: place.name for place in result.package.places}
    sections = {(names[s.place_a], names[s.place_b]): s for s in result.package.sections}
    rise_spiten = sections[("Rise", "Spiten")]
    assert [names[p.to_place] for p in rise_spiten.parts] == ["Tremetsrud", "Ørmen", "Spiten"]
    assert [names[p.to_place] for p in sections[("Tjärby", "Elisabeth")].parts] == [
        "Hammarlind",
        "Ryr timmer",
        "Elisabeth",
    ]
    outside = next(n for n in result.report.notes if "utanför planens klareringssträckor" in n)
    assert outside.startswith("8 spårsträckor") and "Tveiten–Triangeln" in outside


def test_sj_x_116_and_dsb_ic_116_are_two_trains(result: ImportResult) -> None:
    names = {place.id: place.name for place in result.package.places}
    trains = {
        t.service_key: (names[t.calls[0].place], names[t.calls[-1].place])
        for t in result.package.trains
        if t.number == "116"
    }
    assert trains == {"SJ X": ("Munkerød", "Nättelund"), "DSB IC": ("Skovborg", "Munkerød")}
    shared = {t.number for t in result.package.trains if t.service_key}
    assert shared == {str(n) for n in range(115, 133)}


def test_three_kinds_of_call(result: ImportResult) -> None:
    calls = [c for t in result.package.trains for c in t.calls]
    assert sum(not c.stops for c in calls) == 598
    no_exchange = [c for c in calls if not c.exchange]
    assert len(no_exchange) == 28
    assert all(c.stops and c.arrival != c.departure for c in no_exchange)
    lekby = next(p.id for p in result.package.places if p.name == "Lekby")
    n91 = next(
        c for t in result.package.trains if t.number == "91" for c in t.calls if c.place == lekby
    )
    assert (n91.arrival, n91.departure, n91.stops) == ("23:53", "23:53", False)


def test_day_variants_and_the_night(result: ImportResult) -> None:
    assert sum(t.days != list(Weekday) for t in result.package.trains) == 8
    assert max(c.day_offset for t in result.package.trains for c in t.calls) == 1


def test_the_plans_clock_and_game_week(result: ImportResult) -> None:
    package = result.package
    assert (package.clock.start_time, package.clock.speed) == ("05:00", 7)
    week = package.meet.traffic_week
    assert (week.start_weekday, week.days, week.runs_over_midnight) == (Weekday.MON, 6, True)
    assert (str(package.meet.first_date), str(package.meet.last_date)) == (
        "2026-10-30",
        "2026-11-01",
    )
    assert set(package.about) == {"sv", "da", "nb", "de"}


def test_train_types_come_from_the_file(result: ImportResult) -> None:
    rules = {rule.code: rule for rule in result.rulebook.train_types}
    assert rules["RE"].names == ["VY Regionaltog", "SJ Regional", "NSB Regional", "DSB Regional"]
    assert Counter(rule.content for rule in rules.values()) == {"goods": 6, "passengers": 6}
    assert {rule.certainty for rule in rules.values()} == {Certainty.SURE}


def test_everything_is_sure_and_nothing_personal_comes_in(result: ImportResult) -> None:
    assert {fact.certainty for fact in result.facts} == {Certainty.SURE}
    text = result.model_dump_json()
    assert "Owner" not in text and "Participants" not in text


def test_the_same_file_again_gives_the_same_draft(result: ImportResult) -> None:
    assert load() == result


def test_the_graphs_lines_come_from_the_plan(result: ImportResult) -> None:
    pages = result.package.display.graph_pages
    assert [page.number for page in pages] == ["1", "5", "3", "7", "8", "9", "2", "6", "4"]
    codes = {place.id: place.code for place in result.package.places}
    main = next(page for page in pages if page.name == "Huvudlinje i Sverige")
    assert [codes[ref] for ref in main.places] == ["Mkd", "Lek", "Gdö", "Tby", "R", "Nlu", "Mot"]
    assert main.distances == [0, 12, 24, 28, 37, 55, 67]
    assert main.color == "#1a3a5c"
