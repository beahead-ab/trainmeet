"""Trafikkontrollens regler (PLAN-35), as in the old Cloud's conflict check: A on single
track, B on a place's track with a passage a minute, C close behind, D what cannot be checked,
Struktur that stops publishing, and the double-track question.

Provbanan runs clean; each test moves its trains until they meet."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts import drift as changes
from contracts.common import Weekday
from contracts.meet import Meet, MeetPackage, TrackKind, Train
from contracts.planning import DoubleTrackAnswer, Draft, NewMeet
from core.changes import apply
from planering.check import check, review
from planering.store import Planning, PlanningError
from planering.tests.test_planning import MON, SUN, package, result, source


def moved(plan: MeetPackage, *shifts: tuple[str, int]) -> MeetPackage:
    for train, minutes in shifts:
        plan = apply(plan, changes.ChangeTimes(train=train, minutes=minutes), f"m-{train}")
    return plan


def draft(plan: MeetPackage, meet: Meet | None = None) -> Draft:
    """A draft of a package made by hand here: not validated, as a broken one is the point."""
    return Draft.model_construct(meet=meet or plan.meet, package=plan)


def codes(plan: MeetPackage, code: str) -> list[str]:
    return [f.message for f in check(draft(plan)) if f.code == code]


def test_provbanan_runs_clean() -> None:
    found = review(draft(package()))
    assert (found.findings, found.double_track) == ([], [])


def test_a_two_trains_meet_on_single_track_and_the_question_is_asked() -> None:
    # 101 and 103 leave Norrby as 102 and 104 run from Åsen to Norrby.
    plan = moved(package(), ("t101", 26), ("t103", 26))
    conflicts = codes(plan, "single_track_conflict")
    assert conflicts == [
        "Norrby–Åsen (enkelspår): tåg 101 (Norrby → Åsen) och tåg 102 (Åsen → Norrby) är på "
        "linjen samtidigt, 06:26–06:34 (Mån).",
        "Norrby–Åsen (enkelspår): tåg 103 (Norrby → Åsen) och tåg 104 (Åsen → Norrby) är på "
        "linjen samtidigt, 07:26–07:34 (Mån).",
    ]
    [question] = review(draft(plan)).double_track
    assert (question.section, question.conflicts) == ("s-nby-asn", 2)
    assert (
        question.message == "Är det dubbelspår på Norrby–Åsen? I så fall försvinner 2 konflikter."
    )
    one = moved(package(), ("t101", 26))
    assert review(draft(one)).double_track == [], "one conflict asks nothing"
    double = plan.model_copy(
        update={
            "sections": [
                s.model_copy(update={"tracks": TrackKind.DOUBLE}) if s.id == "s-nby-asn" else s
                for s in plan.sections
            ]
        }
    )
    assert codes(double, "single_track_conflict") == []


def test_times_are_half_open() -> None:
    # 102 is in at Norrby 06:34 as 101 leaves it at 06:34: they do not meet.
    plan = moved(package(), ("t101", 34))
    assert codes(plan, "single_track_conflict") == []


def test_c_one_train_close_behind_another() -> None:
    plan = moved(package(), ("t4501", -32))  # Norrby 06:03, three minutes after 101
    assert "Norrby–Åsen: tåg 4501 följer tåg 101 med 3 min lucka, 06:03 (Mån)." in codes(
        plan, "close_following"
    )


def test_b_a_passage_holds_its_track_a_minute() -> None:
    plan = package()
    lvh = next(p for p in plan.places if p.id == "lvh")
    lvh = lvh.model_copy(update={"tracks": [*plan.places[0].tracks[:1]]})

    def through(train: Train, at: str) -> Train:
        return train.model_copy(
            update={
                "calls": [
                    c.model_copy(
                        update={"stops": False, "track": "1", "arrival": at, "departure": at}
                    )
                    if c.place == "lvh"
                    else c
                    for c in train.calls
                ]
            }
        )

    trains = {t.id: t for t in plan.trains}
    trains["t101"] = through(trains["t101"], "06:14")
    trains["t4501"] = through(trains["t4501"], "06:14")
    plan = plan.model_copy(
        update={
            "places": [lvh if p.id == "lvh" else p for p in plan.places],
            "trains": list(trains.values()),
        }
    )
    assert "Tåg 101 och 4501 står på spår 1 i Lövhult samtidigt (06:14)." in codes(
        plan, "track_conflict"
    )


def test_the_check_follows_the_days_and_sunday_runs_into_monday() -> None:
    plan = package()
    trains = {t.id: t for t in plan.trains}

    def run(
        train: Train, days: list[Weekday], times: list[tuple[str | None, str | None, int]]
    ) -> Train:
        calls = [
            c.model_copy(update={"arrival": a, "departure": d, "day_offset": o})
            for c, (a, d, o) in zip(train.calls[:2], times, strict=True)
        ]
        return train.model_copy(update={"days": days, "calls": calls})

    trains["t101"] = run(trains["t101"], [Weekday.SUN], [(None, "23:58", 0), ("00:06", None, 1)])
    trains["t102"] = run(trains["t102"], [Weekday.MON], [(None, "00:00", 0), ("00:08", None, 0)])
    trains["t102"] = trains["t102"].model_copy(
        update={
            "calls": [
                c.model_copy(update={"place": p})
                for c, p in zip(trains["t102"].calls, ("asn", "nby"), strict=True)
            ]
        }
    )
    only = plan.model_copy(update={"trains": [trains["t101"], trains["t102"]]})
    assert codes(only, "single_track_conflict") == [
        "Norrby–Åsen (enkelspår): tåg 101 (Norrby → Åsen) och tåg 102 (Åsen → Norrby) är på "
        "linjen samtidigt, 00:00–00:06 (Mån)."
    ]
    saturday = trains["t102"].model_copy(update={"days": [Weekday.SAT]})
    apart = plan.model_copy(update={"trains": [trains["t101"], saturday]})
    assert codes(apart, "single_track_conflict") == [], "Saturday never meets Sunday night"


def test_d_a_call_without_time() -> None:
    plan = package()
    trains = [
        t.model_copy(
            update={
                "calls": [
                    c.model_copy(update={"arrival": None, "departure": None})
                    if c.id == "t101-lvh"
                    else c
                    for c in t.calls
                ]
            }
        )
        for t in plan.trains
    ]
    assert codes(plan.model_copy(update={"trains": trains}), "missing_time") == [
        "Tåg 101: tid saknas vid Lövhult."
    ]


def test_struktur_stops_publishing() -> None:
    plan = package()
    assert review(draft(plan)).blocking == [
        "Träffen saknar första eller sista dag. Ange dem under Träffar."
    ]
    dated = plan.meet.model_copy(update={"first_date": MON, "last_date": SUN})
    assert review(draft(plan, dated)).blocking == []
    island = plan.model_copy(
        update={
            "sections": [s for s in plan.sections if s.id != "s-asn-mla"],
            "trains": [],
        }
    )
    assert review(draft(island, dated)).blocking == [
        "Tidtabellen saknar tåg.",
        "Banan hänger inte ihop: några driftplatser nås varken via sträckorna eller av tågen "
        "från de andra.",
    ]


@pytest.fixture
def planning(tmp_path: Path) -> Planning:
    return Planning(tmp_path / "planering.sqlite3")


def test_ja_and_nej_to_the_double_track_question(planning: Planning) -> None:
    meet = planning.create(NewMeet(name="Grimslöv", first_date=MON, last_date=SUN)).meet
    src = source()
    meeting = result(src)
    meeting = meeting.model_copy(
        update={"package": moved(meeting.package, ("t101", 26), ("t103", 26))}
    )
    planning.add_source(meet.id, src, b"1", meeting)
    [asked] = planning.check(meet.id).double_track
    with pytest.raises(PlanningError, match="ändrats"):
        planning.double_track(
            meet.id, "s-nby-asn", DoubleTrackAnswer(double=False, fingerprint="0" * 64)
        )
    planning.double_track(
        meet.id, "s-nby-asn", DoubleTrackAnswer(double=False, fingerprint=asked.fingerprint)
    )
    check = planning.check(meet.id)
    assert check.double_track == [], "Nej is kept"
    assert len([f for f in check.findings if f.code == "single_track_conflict"]) == 2
    again = planning.add_source(meet.id, source(digest="b"), b"2", meeting)
    assert again.double_track_declined == {"s-nby-asn": asked.fingerprint}, "kept on a new file"
    # The trains change: the question comes back.
    planning.add_source(
        meet.id,
        source(digest="c"),
        b"3",
        meeting.model_copy(update={"package": moved(meeting.package, ("t105", -2))}),
    )
    planning.add_source(
        meet.id,
        source(digest="d"),
        b"4",
        meeting.model_copy(update={"package": moved(meeting.package, ("t103", 1))}),
    )
    [back] = planning.check(meet.id).double_track
    assert back.fingerprint != asked.fingerprint
    draft = planning.double_track(
        meet.id, "s-nby-asn", DoubleTrackAnswer(double=True, fingerprint=back.fingerprint)
    )
    assert draft.package is not None
    section = next(s for s in draft.package.sections if s.id == "s-nby-asn")
    assert section.tracks == TrackKind.DOUBLE
    left = {f.code for f in planning.check(meet.id).findings}
    assert left == {"unanswered_questions"}, "the conflicts are gone"
    with pytest.raises(PlanningError, match="inte längre"):
        planning.double_track(
            meet.id, "s-nby-asn", DoubleTrackAnswer(double=True, fingerprint=back.fingerprint)
        )
