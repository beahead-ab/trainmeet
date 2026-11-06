"""Stefan's planning file read with code (level 4). Ported from the old Cloud's
test_planning_json: the plan is built here in the form the program saves it, .NET's
reference-preserving JSON with "$id", {"$ref": id} and {"$values": [...]}.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from contracts.common import Language, Weekday
from contracts.meet import Meet, PlaceKind, TrackKind, Train
from contracts.planning import Certainty, ImportResult, Source, SourceKind
from integrationer.planning_json import PlanError, clock, read, weekdays

DAILY = 0b11111111111111
WEEKDAYS = 0b0011111 | (0b0011111 << 7)
WEEKEND = 0b1100000 | (0b1100000 << 7)
MON_FRI = [Weekday.MON, Weekday.TUE, Weekday.WED, Weekday.THU, Weekday.FRI]


def call(
    track: int,
    arrival: str,
    departure: str,
    *,
    arrives: bool = True,
    departs: bool = True,
    sequence: int,
    notes: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "TrackId": track,
        "Sequence": sequence,
        "Arrival": arrival,
        "Departure": departure,
        "IsArrival": arrives,
        "IsDeparture": departs,
        "Notes": {"$values": [{"Text": text} for text in notes]},
    }


def train(
    number: Any, category: int, sessions: int, calls: list[dict[str, Any]], **extra: Any
) -> dict[str, Any]:
    return {
        "Number": number,
        "CategoryId": category,
        "Sessions": sessions,
        "Calls": {"$values": calls},
        **extra,
    }


def plan() -> dict[str, Any]:
    """Charlottendal – Vagnsta (double track) – Salsborg (single track), as the old test's plan."""
    locations = [
        {
            "$id": "10",
            "Id": 10,
            "Name": "Charlottendal",
            "Signature": "Cda",
            "IsManned": True,
            "PhoneNumber": "201",
            "Instructions": "[se]\nRing före avgång.\n[da]\nRing før afgang.",
            "Tracks": {
                "$id": "11",
                "$values": [
                    {
                        "$id": "12",
                        "Id": 100,
                        "Number": "1",
                        "DisplayOrder": 1,
                        "Station": {"$ref": "10"},
                    },
                    {
                        "$id": "13",
                        "Id": 101,
                        "Number": "2",
                        "DisplayOrder": 2,
                        "Station": {"$ref": "10"},
                    },
                    {"Id": 102, "Number": "41", "IsScheduled": False},
                ],
            },
        },
        {
            "$id": "20",
            "Id": 11,
            "Name": "Vagnsta",
            "Signature": "Vst",
            "Owner": "Någon Person",
            "Tracks": {"$values": [{"Id": 110, "Number": "1a"}, {"Id": 111, "Number": "2"}]},
        },
        {
            "$id": "30",
            "Id": 12,
            "Name": " Salsborg ",
            "Signature": "Sal",
            "IsManned": True,
            "Tracks": {"$values": [{"Id": 120, "Number": "3"}]},
        },
    ]
    categories = [
        {"Id": 1, "Prefix": "Pt", "Name": "Persontåg", "Content": 1, "IsShunting": False},
        {
            "Id": 2,
            "Prefix": "Gt",
            "Name": "Godståg",
            "Content": 2,
            "IsShunting": False,
            "CompanyId": 7,
        },
        {"Id": 3, "Prefix": "RE", "Name": "Regionaltåg", "Content": 1, "IsShunting": False},
        {"Id": 4, "Prefix": "", "Name": "Växling", "Content": 0, "IsShunting": True},
        {"Id": 5, "Prefix": "Mt", "Name": "Materialtåg", "Content": 0, "IsShunting": False},
    ]
    trains = [
        train(
            91,
            1,
            DAILY,
            [
                call(100, "05:50:00", "06:20:00", arrives=False, sequence=1),
                call(110, "06:31:00", "06:32:00", arrives=False, departs=False, sequence=2),
                call(120, "06:45:00", "07:00:00", departs=False, sequence=3),
            ],
            Id=1,
        ),
        # The calls in reverse order in the file: Sequence decides.
        train(
            5102,
            2,
            WEEKDAYS,
            [
                call(101, "08:41:00", "09:00:00", departs=False, sequence=3),
                call(
                    111,
                    "08:22:00",
                    "08:30:00",
                    sequence=2,
                    notes=("Lok runt.", "Tåganmälan till Vagnsta."),
                ),
                call(120, "08:00:00", "08:10:00", arrives=False, sequence=1),
            ],
            Id=2,
        ),
        train(
            9901,
            5,
            WEEKEND,
            [
                call(110, "10:00:00", "10:05:00", arrives=False, sequence=1),
                call(100, "10:15:00", "10:20:00", departs=False, sequence=2),
            ],
            Id=3,
        ),
        # The same number on other days does not clash.
        train(
            5102,
            2,
            WEEKEND,
            [
                call(120, "12:00:00", "12:10:00", arrives=False, sequence=1),
                call(101, "12:41:00", "13:00:00", departs=False, sequence=2),
            ],
            Id=4,
        ),
        # The night train: "1.00:05:00" is the next day.
        train(
            93,
            3,
            DAILY,
            [
                call(100, "23:30:00", "23:40:00", arrives=False, sequence=1),
                call(120, "1.00:05:00", "1.00:20:00", departs=False, sequence=2),
            ],
            Id=5,
        ),
        # A shunting task and a train with one call are not trains in the timetable.
        train(1, 4, WEEKDAYS, [call(100, "11:00:00", "11:05:00", sequence=1) | {"Id": 900}], Id=6),
        train(77, 1, DAILY, [call(100, "12:00:00", "12:05:00", sequence=1)], Id=7),
        # A train without a number cannot be shown.
        train(
            None,
            1,
            DAILY,
            [
                call(100, "15:00:00", "15:05:00", arrives=False, sequence=1),
                call(120, "15:30:00", "15:40:00", departs=False, sequence=2),
            ],
            Id=8,
        ),
        # A call on a missing track is left out; the rest of the train is read.
        train(
            95,
            1,
            DAILY,
            [
                call(100, "14:00:00", "14:05:00", arrives=False, sequence=1),
                call(999, "14:10:00", "14:10:00", sequence=2),
                call(120, "14:30:00", "14:40:00", departs=False, sequence=3),
            ],
            Id=9,
        ),
        # A train without traffic days is not guessed to be daily.
        train(
            96,
            1,
            0,
            [
                call(100, "16:00:00", "16:05:00", arrives=False, sequence=1),
                call(120, "16:30:00", "16:40:00", departs=False, sequence=2),
            ],
            Id=10,
        ),
        {"$ref": "t1"},
    ]
    stretches = [
        {"$id": "s1", "Id": 1, "StartId": 10, "EndId": 11, "TracksCount": 2},
        {"$id": "s2", "Id": 2, "StartId": 11, "EndId": 12, "TracksCount": 1},
        {"Id": 3, "StartId": 12, "EndId": 99, "TracksCount": 2},
    ]
    dispatch = [
        {
            "Id": 7,
            "From": {"$ref": "10"},
            "To": {"$ref": "30"},
            "Stretches": {"$values": [{"$ref": "s2"}, {"$ref": "s1"}]},
        }
    ]
    return {
        "$id": "1",
        "Id": 0,
        "Name": "Grimslöv",
        "GeneralInstructions": "Allmänt om träffen.",
        "Participants": {"$values": [{"Name": "Någon Person", "Email": "nagon@example.org"}]},
        "VehicleContributions": {"$values": [{"Owner": "Någon Person"}]},
        "Timetable": {
            "$id": "2",
            "Name": "Grimslöv",
            "Layout": {
                "$id": "3",
                "Name": "Grimslöv",
                "Settings": {
                    "General": {
                        "ValidFrom": "2026-05-01T00:00:00",
                        "ValidTo": "2026-05-02",
                        "FirstSessionStartTime": "06:00:00",
                        "StartDay": 1,
                        "MaxSessions": 2,
                        "RunsOverMidnight": True,
                    },
                    "TimeAndSpeed": {"FastClockSpeed": 5},
                },
                "Companies": {"$values": [{"Id": 7, "Signature": "GC", "Name": "Green Cargo"}]},
                "OperationLocations": {"$id": "4", "$values": locations},
                "TrackStretches": {"$values": stretches},
                "DispatchStretches": {"$values": dispatch},
            },
            "TrainCategories": {"$values": categories},
            "Trains": {"$id": "5", "$values": trains},
        },
        # A train only named with $ref: defined under a schedule.
        "Schedules": {
            "$values": [
                {
                    "$id": "s9",
                    "Id": 3,
                    "Number": 533,
                    "Train": {
                        "$id": "t1",
                        **train(
                            92,
                            1,
                            DAILY,
                            [
                                call(120, "16:00:00", "16:10:00", arrives=False, sequence=1)
                                | {"Id": 501},
                                call(100, "16:40:00", "17:00:00", departs=False, sequence=2)
                                | {"Id": 502},
                            ],
                            Id=11,
                        ),
                    },
                    "Parts": {"$values": [{"FromId": 501, "ToId": 502}]},
                }
            ]
        },
        "DriverDuties": {
            "$values": [
                {"Id": 4, "Identity": "39", "Parts": {"$values": [{"FromId": 501, "ToId": 502}]}}
            ]
        },
    }


MEET = Meet(id="grimslov", name="Grimslöv")


def source(data: bytes) -> Source:
    return Source(
        id="u1",
        kind=SourceKind.PLANNING_JSON,
        filename="plan.json",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        level=4,
        added=datetime(2026, 11, 6, tzinfo=UTC),
    )


def imported(data: dict[str, Any], meet: Meet = MEET) -> ImportResult:
    raw = json.dumps(data, ensure_ascii=False).encode()
    return read(raw, meet=meet, source=source(raw))


@pytest.fixture(scope="module")
def result() -> ImportResult:
    return imported(plan())


def by_number(result: ImportResult, number: str, days: list[Weekday] | None = None) -> Train:
    return next(
        t for t in result.package.trains if t.number == number and (days is None or t.days == days)
    )


def test_places_keep_the_files_names_codes_and_kinds(result: ImportResult) -> None:
    places = {p.name: p for p in result.package.places}
    assert [(p.id, p.code, p.kind) for p in places.values()] == [
        ("p10", "Cda", PlaceKind.MANNED),
        ("p11", "Vst", PlaceKind.HALT),
        ("p12", "Sal", PlaceKind.MANNED),
    ]
    cda = places["Charlottendal"]
    assert cda.phone == "201"
    assert [t.name for t in cda.tracks] == ["1", "2"], "a storage track is not the place's track"
    assert cda.instructions == {"sv": "Ring före avgång.", "da": "Ring før afgang."}
    assert cda.source_ids == {"planning_json": "10"}


def test_the_dispatch_stretch_is_the_section_and_its_track_stretches_the_parts(
    result: ImportResult,
) -> None:
    [section] = result.package.sections
    assert (section.id, section.place_a, section.place_b, section.tracks) == (
        "d7",
        "p10",
        "p12",
        TrackKind.SINGLE,
    )
    assert [(p.id, p.from_place, p.to_place) for p in section.parts] == [
        ("s1", "p10", "p11"),
        ("s2", "p11", "p12"),
    ]
    note = next(n for n in result.report.notes if n.startswith("Vagnsta"))
    assert "inne i klareringssträckan Charlottendal–Salsborg" in note


def test_a_place_without_a_signature_is_known_by_its_name() -> None:
    data = plan()
    del data["Timetable"]["Layout"]["OperationLocations"]["$values"][1]["Signature"]
    result = imported(data)
    assert result.package.places[1].code == "Vagnsta"
    assert "Vagnsta har ingen signatur i filen; namnet används." in result.report.notes


def test_the_origin_has_no_arrival_and_the_destination_no_departure(
    result: ImportResult,
) -> None:
    first, through, last = by_number(result, "91").calls
    assert (first.arrival, first.departure, first.track) == (None, "06:20", "1")
    # The train stands a minute in Vagnsta without exchange: a stop, not a passage.
    assert (through.arrival, through.departure, through.stops, through.exchange) == (
        "06:31",
        "06:32",
        True,
        False,
    )
    assert (last.arrival, last.departure, last.track) == ("06:45", None, "3")
    assert (first.exchange, last.exchange) == (True, True)


@pytest.mark.parametrize("arrives", [False, True])
def test_a_passage_has_the_same_time_in_and_out(arrives: bool) -> None:
    """The program writes "Ej uppehåll" when the time in and out is the same, even when the
    plan marks the arrival (N 91 in Lekby)."""
    data = plan()
    data["Timetable"]["Trains"]["$values"][0]["Calls"]["$values"][1].update(
        Arrival="06:31:00", Departure="06:31:00", IsArrival=arrives
    )
    through = by_number(imported(data), "91").calls[1]
    assert (through.arrival, through.departure, through.stops) == ("06:31", "06:31", False)


def test_calls_follow_their_sequence_not_the_files_order(
    result: ImportResult,
) -> None:
    first, middle, last = by_number(result, "5102", MON_FRI).calls
    assert (first.place, first.arrival, first.departure) == ("p12", None, "08:10")
    assert (middle.place, middle.arrival, middle.departure, middle.stops) == (
        "p11",
        "08:22",
        "08:30",
        True,
    )
    assert (last.place, last.arrival, last.departure) == ("p10", "08:41", None)
    assert middle.note == "Lok runt. Tåganmälan till Vagnsta."


def test_operating_days_come_from_the_two_week_mask(result: ImportResult) -> None:
    days = {(t.number, tuple(t.days)) for t in result.package.trains}
    weekend = (Weekday.SAT, Weekday.SUN)
    assert days == {
        ("91", tuple(Weekday)),
        ("5102", tuple(MON_FRI)),
        ("5102", weekend),
        ("9901", weekend),
        ("93", tuple(Weekday)),
        ("95", tuple(Weekday)),
        ("92", tuple(Weekday)),
    }
    assert weekdays(1 << 8) == [Weekday.TUE], "the second week's Tuesday is a Tuesday"
    assert weekdays(0b1111111) == list(Weekday), "one week is enough"
    assert weekdays(0) == [] and weekdays(None) == []
    assert "Tåg 96 har inga trafikdagar i filen." in result.report.left_out


def test_a_time_after_midnight_is_the_next_game_day(result: ImportResult) -> None:
    first, last = by_number(result, "93").calls
    assert (first.departure, first.day_offset) == ("23:40", 0)
    assert (last.arrival, last.day_offset) == ("00:05", 1)
    assert clock("25:00:00") is None and clock("") is None


def test_shunting_single_calls_and_missing_tracks_are_reported(
    result: ImportResult,
) -> None:
    [task] = result.package.shunting
    assert (task.id, task.place, task.name, task.time) == ("v900", "p10", "1", "11:00")
    assert task.description == "11:00–11:05, Växling, spår 1, Mån–Fre"
    left_out = result.report.left_out
    assert "Tåg 77 har färre än två uppehåll." in left_out
    assert "Ett tåg utan nummer lästes inte." in left_out
    assert "Tåg 95: ett uppehåll pekar på ett spår som saknas och lästes inte." in left_out
    assert [c.place for c in by_number(result, "95").calls] == ["p10", "p12"]
    assert "1" not in {t.number for t in result.package.trains}


def test_a_number_used_twice_on_the_same_days_gets_service_keys(
    result: ImportResult,
) -> None:
    assert {t.service_key for t in result.package.trains} == {None}, (
        "5102 weekdays and weekend do not clash"
    )
    clashing = plan()
    clashing["Timetable"]["Trains"]["$values"].append(
        train(
            91,
            3,
            WEEKEND,
            [
                call(120, "18:00:00", "18:10:00", arrives=False, sequence=1),
                call(100, "18:40:00", "19:00:00", departs=False, sequence=2),
            ],
            Id=12,
        )
    )
    keys = {
        t.train_type: t.service_key for t in imported(clashing).package.trains if t.number == "91"
    }
    assert keys == {"Pt": "Pt", "RE": "RE"}


def test_operator_and_abbreviation(result: ImportResult) -> None:
    goods = by_number(result, "5102", MON_FRI)
    assert (goods.train_type, goods.operator, goods.source_ids) == (
        "Gt",
        "GC",
        {"planning_json": "2", "category": "2"},
    )


def test_a_train_only_referenced_is_still_a_train(result: ImportResult) -> None:
    referenced = by_number(result, "92")
    assert [(c.id, c.place) for c in referenced.calls] == [("c501", "p12"), ("c502", "p10")]


def test_duties_and_turns_point_at_the_trains(result: ImportResult) -> None:
    [duty] = result.package.duties
    assert (duty.id, duty.name, duty.legs[0].train, duty.legs[0].from_call) == (
        "k4",
        "39",
        "t11",
        "c501",
    )
    [turn] = result.package.turns
    assert (turn.id, turn.name, turn.trains) == ("o3", "533", ["t11"])


def test_settings_give_the_clock_and_the_game_week(result: ImportResult) -> None:
    package = result.package
    assert (package.clock.start_time, package.clock.speed) == ("06:00", 5)
    week = package.meet.traffic_week
    assert (week.start_weekday, week.days, week.runs_over_midnight) == (Weekday.MON, 2, True)
    assert (str(package.meet.first_date), str(package.meet.last_date)) == (
        "2026-05-01",
        "2026-05-02",
    )
    assert (
        package.meet.name == "Grimslöv"
        and package.about[Language.SV].instructions == "Allmänt om träffen."
    )


def test_the_meets_own_dates_stay() -> None:
    own = Meet(
        id="grimslov", name="Grimslöv 2027", first_date=date(2027, 5, 1), last_date=date(2027, 5, 2)
    )
    package = imported(plan(), own).package
    assert (package.meet.name, str(package.meet.first_date)) == ("Grimslöv 2027", "2027-05-01")


def test_train_types_go_through_the_rulebook(result: ImportResult) -> None:
    rules = {rule.code: rule for rule in result.rulebook.train_types}
    assert (rules["Pt"].content, rules["Pt"].certainty) == ("passengers", Certainty.SURE)
    assert (rules["Gt"].content, rules["Gt"].certainty) == ("goods", Certainty.SURE)
    # Mt has no content in the file; the rulebook knows it.
    assert (rules["Mt"].content, rules["Mt"].certainty) == ("goods", Certainty.LIKELY)
    assert [o.source for o in rules["Mt"].origins] == ["u1", "regelboken"]
    assert result.questions == []


def test_a_type_nobody_knows_is_a_question_never_a_guess_from_the_number() -> None:
    data = plan()
    data["Timetable"]["TrainCategories"]["$values"][4]["Prefix"] = "Zq"
    result = imported(data)
    [question] = result.questions
    assert question.cause == "train_type" and question.refs == ["train_type:Zq"]
    assert [a.value for a in question.alternatives] == ["passengers", "goods", "service"]
    rule = next(r for r in result.rulebook.train_types if r.code == "Zq")
    assert (rule.content, rule.certainty) == (None, Certainty.UNSURE)
    # 9901 is still a train; nothing was guessed from its 9.
    assert by_number(result, "9901").train_type == "Zq"


def test_two_categories_that_disagree_are_a_question() -> None:
    data = plan()
    data["Timetable"]["TrainCategories"]["$values"][2].update(Prefix="Pt", Content=2)
    result = imported(data)
    assert [q.id for q in result.questions] == ["train-type-pt"]
    question = result.questions[0]
    assert [len(a.origins) for a in question.alternatives] == [1, 1, 0]


def test_every_thing_carries_its_origin(result: ImportResult) -> None:
    refs = {fact.ref for fact in result.facts}
    package = result.package
    expected = (
        {f"place:{p.id}" for p in package.places}
        | {f"section:{s.id}" for s in package.sections}
        | {f"part:{p.id}" for s in package.sections for p in s.parts}
        | {f"train:{t.id}" for t in package.trains}
        | {f"call:{c.id}" for t in package.trains for c in t.calls}
        | {f"shunting:{s.id}" for s in package.shunting}
        | {f"duty:{d.id}" for d in package.duties}
        | {f"turn:{t.id}" for t in package.turns}
    )
    assert expected <= refs
    assert all(
        fact.origins[0].source == "u1"
        for fact in result.facts
        if not fact.ref.startswith("train_type:")
    )
    call_fact = next(f for f in result.facts if f.ref == "call:c501")
    assert (call_fact.certainty, call_fact.origins[0].at) == (Certainty.SURE, "Calls Id 501")


def test_personal_data_never_comes_in(result: ImportResult) -> None:
    text = result.model_dump_json()
    assert "Någon Person" not in text and "example.org" not in text


def test_the_same_file_gives_the_same_result() -> None:
    assert imported(plan()) == imported(plan())


def test_a_plan_without_dispatch_stretches_has_no_sections() -> None:
    data = plan()
    del data["Timetable"]["Layout"]["DispatchStretches"]
    result = imported(data)
    assert result.package.sections == []
    assert result.package.places[1].kind == PlaceKind.UNMANNED
    assert (
        "Filen har inga klareringssträckor; Drift kan inte klarera några tåg."
        in result.report.notes
    )
    assert any("2 spårsträckor ligger utanför" in note for note in result.report.notes)


def test_the_report_counts_what_the_file_gave(result: ImportResult) -> None:
    report = result.report
    assert (report.level, report.places, report.sections, report.parts) == (
        4,
        {PlaceKind.MANNED: 2, PlaceKind.HALT: 1},
        1,
        2,
    )
    assert (
        report.trains,
        report.calls,
        report.shunting,
        report.duties,
        report.turns,
        report.train_types,
    ) == (7, 16, 1, 1, 1, 4)


# --- The file ---------------------------------------------------------------------------------


def test_a_file_with_a_byte_order_mark_or_packed_is_read() -> None:
    raw = json.dumps(plan(), ensure_ascii=False).encode()
    for data in (b"\xef\xbb\xbf" + raw, gzip.compress(raw)):
        assert len(read(data, meet=MEET, source=source(data)).package.places) == 3


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"{not json", "går inte att läsa som JSON"),
        (b"[1, 2]", "inte ett objekt"),
        (b'{"a": 1}', "inte planeringsprogrammets plan: Timetable.Layout saknas"),
        (b"\x1f\x8bnot gzip", "går inte att packa upp"),
    ],
)
def test_a_file_that_is_not_a_plan_is_refused(data: bytes, message: str) -> None:
    with pytest.raises(PlanError, match=message):
        read(data, meet=MEET, source=source(data))


def test_a_plan_without_trains_or_places_is_refused() -> None:
    empty = plan()
    empty["Timetable"]["Trains"]["$values"] = []
    empty.pop("Schedules")
    with pytest.raises(PlanError, match="inga tåg"):
        imported(empty)
    nowhere = plan()
    nowhere["Timetable"]["Layout"]["OperationLocations"]["$values"] = []
    nowhere["Timetable"]["Layout"].pop("DispatchStretches")
    with pytest.raises(PlanError, match="inga driftplatser"):
        imported(nowhere)
    unlinked = plan()
    unlinked["Timetable"]["Trains"]["$values"] = [
        item for item in unlinked["Timetable"]["Trains"]["$values"] if "$ref" not in item
    ]
    for item in unlinked["Timetable"]["Trains"]["$values"]:
        for entry in item["Calls"]["$values"]:
            entry["TrackId"] = 999
    with pytest.raises(PlanError, match="kunde kopplas"):
        imported(unlinked)


def test_too_many_calls_are_refused() -> None:
    huge = plan()
    huge["Timetable"]["Trains"]["$values"] = [
        train(n, 1, DAILY, [call(100, "06:00:00", "06:01:00", sequence=1)] * 101)
        for n in range(200)
    ]
    with pytest.raises(PlanError, match="fler än 20000 uppehåll"):
        imported(huge)
