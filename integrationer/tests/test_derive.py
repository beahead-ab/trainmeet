"""Härledningen (4c1, IMPORT-17, IMPORT-33): the draft the station lists give on their own,
with Värnamo's planning file as the answer (H79).

The 14 lists here are made from the planning file in the planning program's format, as in
test_station_lists: Steinsnes runs Triangeln from afar ("Tri 1"), and a stop is printed on two
rows. Run against the organiser's own 14 lists, the derivation gives the same: 228 trains, each
with the plan's number, days, Från, Till and times."""

from __future__ import annotations

import csv
import io
from collections import deque
from itertools import pairwise

import pytest

from contracts.meet import Meet, MeetPackage, PlaceKind, TrackKind, Train
from contracts.planning import Certainty, ImportResult
from integrationer import derive, track_picture
from integrationer.derive import abbreviates
from integrationer.station_lists import ListError, Lists, read
from integrationer.tests.test_station_lists import HEADER, lists_zip, odt, plan, rows_for, source
from integrationer.tests.test_track_picture import AT, picture_pdf

__all__ = ["plan"]

LISTED = ("Ebh", "Ful", "Gbg", "Gdö", "Lek", "Mkd", "Mot", "Nlu", "R", "Rse", "Sbg", "Sku", "Spn")


def varnamo(plan: MeetPackage) -> Lists:
    names = {p.code: p.name for p in plan.places}
    files = {f"{code} {names[code]}.odt": odt(rows_for(plan, code, twice=True)) for code in LISTED}
    files["Ste Steinsnes.odt"] = odt(rows_for(plan, "Ste", remote=("Tri",), twice=True))
    return read(lists_zip(files), "Station dispatch lists.zip")


@pytest.fixture(scope="module")
def derived(plan: MeetPackage) -> ImportResult:
    return derive.draft(varnamo(plan), meet=plan.meet, source=source())


@pytest.fixture(scope="module")
def drawn(plan: MeetPackage) -> ImportResult:
    """The lists and the track picture: underlagsnivå 2."""
    picture = track_picture.read(picture_pdf(plan))
    given = source().model_copy(update={"id": "u-picture", "filename": "Banan.pdf", "level": 2})
    return derive.draft(
        varnamo(plan), meet=plan.meet, source=source(), picture=picture, drawn=given
    )


def key(train: Train, package: MeetPackage) -> tuple[str, tuple[str, ...], str, str]:
    names = {p.id: p.name for p in package.places}
    days = tuple(day.value for day in train.days)
    return (train.number, days, names[train.calls[0].place], names[train.calls[-1].place])


def test_the_trains_are_the_plans(plan: MeetPackage, derived: ImportResult) -> None:
    """The same number on the same days between the same Från and Till is one train; trains
    that share a number (116 Skovborg–Munkerød and Munkerød–Nättelund) are two."""
    package = derived.package
    planned = {key(t, plan): t for t in plan.trains}
    assert len(planned) == len(plan.trains) == len(package.trains) == 228
    assert {key(t, package) for t in package.trains} == set(planned)
    assert len([t for t in package.trains if t.number == "116"]) == 2
    codes = {p.id: p.code for p in plan.places}
    mine = {p.id: p.code for p in package.places}
    for train in package.trains:
        twin = planned[key(train, package)]
        calls = {
            (codes[c.place], c.arrival, c.departure, c.track, c.stops, c.day_offset)
            for c in twin.calls
        }
        timed = [c for c in train.calls if c.arrival or c.departure]
        assert timed, train.number
        begins = train.calls[0] is timed[0]
        for call in timed:
            seen = (mine[call.place], call.arrival, call.departure, call.track, call.stops)
            if begins:
                assert (*seen, call.day_offset) in calls, (train.number, seen)
            else:
                # The first time is in no list (8239 leaves Kjøllstad 23:58), so the lists
                # cannot say that a passage at 00:05 is on the next day.
                assert seen in {c[:5] for c in calls}, (train.number, seen)
        assert (train.operator, train.train_type) == (twin.operator, twin.train_type)
    assert [t.calls[-1].day_offset for t in package.trains if t.number == "91"] == [1]


def test_the_places_and_their_kinds(plan: MeetPackage, derived: ImportResult) -> None:
    package = derived.package
    kinds = {p.code: p.kind for p in package.places}
    assert {code for code, kind in kinds.items() if kind == PlaceKind.SHADOW_YARD} == {
        "Sbg",
        "Spn",
        "Gbg",
    }, "every train in their lists starts or ends there"
    assert kinds["Mkd"] == kinds["Ste"] == PlaceKind.MANNED
    tri = next(p for p in package.places if p.code == "Tri")
    assert tri.kind == PlaceKind.REMOTE and tri.remote_from == "l-ste"
    assert [t.name for t in tri.tracks] == ["1", "2"]
    halts = {p.name for p in package.places if p.kind == PlaceKind.HALT}
    assert {"Tveiten", "Kjøllstad", "Skuggvik havn", "Industriparken"} <= halts
    assert all(p.code == p.name for p in package.places if p.kind == PlaceKind.HALT), (
        "no signature is made up (IMPORT-29)"
    )
    planned = {p.name for p in plan.places}
    assert {p.name for p in package.places if p.code != "Tri"} <= planned
    facts = {f.ref: f for f in derived.facts}
    for place in package.places:
        assert facts[f"place:{place.id}"].certainty == Certainty.LIKELY
        assert facts[f"place:{place.id}.kind"].certainty == Certainty.UNSURE
        assert facts[f"place:{place.id}.kind"].note
    tveiten = next(t for t in package.trains if t.number == "401")
    assert tveiten.calls[-1].arrival is None and tveiten.calls[-1].departure is None
    assert facts[f"call:{tveiten.calls[-1].id}"].certainty == Certainty.UNSURE


def test_the_sections_follow_the_trains_route(plan: MeetPackage, derived: ImportResult) -> None:
    """Each derived section joins two places that the plan joins through places without a
    list of their own (Gårdsjö–Rotebro through Tjärby), single track and osäker."""
    package = derived.package
    codes = {p.id: p.code for p in package.places}
    by_code = {p.code: p.id for p in plan.places}
    listed = {by_code[c] for c in (*LISTED, "Ste", "Tri")}
    links: dict[str, set[str]] = {p.id: set() for p in plan.places}
    for section in plan.sections:
        links[section.place_a].add(section.place_b)
        links[section.place_b].add(section.place_a)

    def joined(a: str, b: str) -> bool:
        seen, queue = {a}, deque([a])
        while queue:
            here = queue.popleft()
            for there in links[here] - seen:
                if there == b:
                    return True
                if there not in listed:
                    seen.add(there)
                    queue.append(there)
        return False

    facts = {f.ref: f for f in derived.facts}
    assert len(package.sections) == 14
    for section in package.sections:
        a, b = codes[section.place_a], codes[section.place_b]
        assert joined(by_code[a], by_code[b]), (a, b)
        assert section.tracks == TrackKind.SINGLE
        assert facts[f"section:{section.id}"].certainty == Certainty.UNSURE
        assert "Härledd" in (facts[f"section:{section.id}"].note or "")


def test_the_report_and_the_rulebook(plan: MeetPackage, derived: ImportResult) -> None:
    report = derived.report
    assert report.level == 1 and report.trains == 228 and not derived.checks_only
    assert report.notes[0].startswith("Utkastet är härlett ur 14 stationslistor.")
    assert any("Tri står bara med signaturen" in n for n in report.notes)
    assert any(n.startswith("Tåg 91, 4003 och 47522 går över midnatt") for n in report.notes)
    assert derived.questions == [], "the rulebook knows every train type in Värnamo"
    contents = {r.code: r.content for r in derived.rulebook.train_types}
    types = {t.train_type for t in plan.trains}
    assert set(contents) == {t for t in types if t}
    assert contents["X"] == "passengers" and contents["Kp"] == "goods"


def csv_list(*rows: list[str]) -> bytes:
    out = io.StringIO()
    csv.writer(out, delimiter=";").writerows([HEADER, *rows])
    return out.getvalue().encode()


def row(label: str, track: str, arrival: str, came: str, departure: str, to: str) -> list[str]:
    return [label, "Dagl", track, arrival, came, departure, to, *[""] * 7]


def test_runs_that_share_everything_are_told_apart_on_exact_times() -> None:
    """Train 7 runs Ansby–Bodarna twice a day: two trains, each run by its own times."""
    found = read(
        csv_list(
            row("X 7", "1", "", "", "06:00", "Bodarna"),
            row("X 7", "1", "", "", "18:00", "Bodarna"),
        ),
        "A Ansby.csv",
    )
    found.rows.update(
        read(
            csv_list(
                row("X 7", "2", "06:20", "Ansby", "", ""),
                row("X 7", "2", "18:25", "Ansby", "", ""),
            ),
            "B Bodarna.csv",
        ).rows
    )
    package = derive.draft(found, meet=meet(), source=source()).package
    assert [(t.id, [(c.departure, c.arrival) for c in t.calls]) for t in package.trains] == [
        ("lt-7", [("06:00", None), (None, "06:20")]),
        ("lt-7-2", [("18:00", None), (None, "18:25")]),
    ]
    assert [(s.place_a, s.place_b) for s in package.sections] == [("l-a", "l-b")]


def test_a_place_known_by_its_code_takes_the_name_the_other_lists_give() -> None:
    found = read(csv_list(row("GC G 9", "Tri 1", "", "", "05:00", "Spiten")), "S Steinsnes.csv")
    found.rows.update(
        read(csv_list(row("GC G 9", "3", "05:30", "Triangeln", "", "")), "Spn Spiten.csv").rows
    )
    result = derive.draft(found, meet=meet(), source=source())
    tri = next(p for p in result.package.places if p.code == "Tri")
    assert tri.name == "Triangeln" and tri.kind == PlaceKind.REMOTE
    assert "Tri heter Triangeln, som tåg 9 kallar den." in result.report.notes
    [train] = result.package.trains
    assert [c.place for c in train.calls] == ["l-tri", "l-spn"]


def test_nothing_to_build_from() -> None:
    with pytest.raises(ListError, match="inga tåg"):
        derive.draft(Lists(), meet=meet(), source=source())


def meet() -> Meet:
    return Meet(id="m", name="Provträffen", country="se", timezone="Europe/Stockholm")


def test_the_picture_confirms_the_sections_and_gives_the_places_in_between(
    plan: MeetPackage, drawn: ImportResult
) -> None:
    """Level 2: every section the trains give is on the picture, with the places in between
    as its parts, and double track where the plan has it (I4)."""
    package, report = drawn.package, drawn.report
    assert report.level == 2 and report.trains == 228
    codes = {p.id: p.code for p in package.places}
    assert set(codes.values()) == set(AT), "every place on the picture is in the draft"
    planned = {p.id: p.code for p in plan.places}
    double = {
        frozenset((planned[part.from_place], planned[part.to_place]))
        for s in plan.sections
        if s.tracks == TrackKind.DOUBLE
        for part in s.parts
    }
    facts = {f.ref: f for f in drawn.facts}
    ways: dict[frozenset[str], list[str]] = {}
    for section in package.sections:
        way = [codes[section.place_a], *(codes[p.to_place] for p in section.parts)]
        ways[frozenset((way[0], way[-1]))] = way
        assert facts[f"section:{section.id}"].certainty == Certainty.SURE
        assert [o.source for o in facts[f"section:{section.id}"].origins][-1] == "u-picture"
        on_double = all(frozenset(pair) in double for pair in pairwise(way))
        assert (section.tracks == TrackKind.DOUBLE) == on_double, way
    assert ways[frozenset(("Gdö", "R"))] in (["Gdö", "Tby", "R"], ["R", "Tby", "Gdö"])
    assert len(ways[frozenset(("Ebh", "Gdö"))]) == 5, "through Tjärby, Hammarlind and Ryr"
    assert sum(s.tracks == TrackKind.DOUBLE for s in package.sections) == 6
    assert set(package.display.reference_layout) == set(codes)
    assert report.notes[0].startswith(
        "Utkastet är härlett ur 14 stationslistor och banbilden. Banbilden visar 14 av 14 "
        "sträckor, 9 platser emellan och dubbelspår på 6 sträckor."
    )
    assert any(n.startswith("Banan grenar sig vid Stv och Tby") for n in report.notes)


def test_a_place_named_only_in_the_lists_takes_its_signature_from_the_picture(
    drawn: ImportResult,
) -> None:
    places = {p.name: p for p in drawn.package.places}
    assert {name: places[name].code for name in (
        "Tveiten", "Kjøllstad", "Skuggvik havn", "Industriparken", "Godsterminalen",
        "Hammarlind", "Tremetsrud",
    )} == {
        "Tveiten": "Tve", "Kjøllstad": "Kje", "Skuggvik havn": "Skh", "Industriparken": "Idp",
        "Godsterminalen": "Gtn", "Hammarlind": "Hld", "Tremetsrud": "Tre",
    }  # fmt: skip
    facts = {f.ref: f for f in drawn.facts}
    kje = facts[f"place:{places['Kjøllstad'].id}.code"]
    assert kje.certainty == Certainty.UNSURE
    assert kje.note == (
        "Signaturen ur banbilden: Kje är den enda signaturen på banbilden som börjar som "
        "Kjøllstad och inte har en lista."
    )
    assert facts[f"place:{places['Tveiten'].id}.code"].note == (
        "Signaturen ur banbilden: Tve är en förkortning av Tveiten."
    )
    assert facts[f"place:{places['Lekby'].id}"].certainty == Certainty.SURE, "list and picture"
    tby = next(p for p in drawn.package.places if p.code == "Tby")
    assert tby.kind == PlaceKind.HALT and tby.name == "Tby"
    assert "grenar sig" in (facts[f"place:{tby.id}.kind"].note or "")


def test_abbreviations() -> None:
    assert abbreviates("Tve", "Tveiten") and abbreviates("Skh", "Skuggvik havn")
    assert abbreviates("Gdö", "Gårdsjö") and not abbreviates("Gbg", "Gårdsjö")
    assert not abbreviates("Kje", "Kjøllstad") and not abbreviates("Tby", "Tveiten")
