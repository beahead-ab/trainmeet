"""Rimlighetskontrollen (PLAN-36), after the old Cloud's tests (tests/test_sanity.py there):
each train against the other trains between the same places and at the same place, with Låt
stå that comes back when the calls change, and Ta tillbaka.

On Provbanan every train takes 8 minutes between Norrby and Åsen and stands 2 minutes at
Åsen."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from contracts.meet import MeetPackage
from contracts.planning import CallChange, LetStand, NewMeet, PlaceChange
from planering.sanity import deviations, duration
from planering.store import Planning, PlanningError
from planering.tests.test_planning import MON, SUN, package, result, source

Times = tuple[str | None, str | None]


def retimed(
    plan: MeetPackage, calls: Mapping[str, Times], keep: list[str] | None = None
) -> MeetPackage:
    """The plan with new times on some calls, and only the trains kept if told."""
    trains = [
        t.model_copy(
            update={
                "calls": [
                    c.model_copy(update={"arrival": calls[c.id][0], "departure": calls[c.id][1]})
                    if c.id in calls
                    else c
                    for c in t.calls
                ]
            }
        )
        for t in plan.trains
        if keep is None or t.id in keep
    ]
    return plan.model_copy(update={"trains": trains})


def found(plan: MeetPackage) -> list[tuple[str, str]]:
    return [(d.kind, d.message) for d in deviations(plan)]


AFTER_ASN: dict[str, Times] = {  # 105 an hour later from Åsen on
    "t105-asn": ("08:08", "09:10"),
    "t105-lvh": ("09:14", "09:15"),
    "t105-mla": ("09:19", "09:21"),
    "t105-sjv": ("09:29", None),
}


def test_provbanan_is_reasonable() -> None:
    assert deviations(package()) == []


def test_two_hours_where_the_others_take_eight_minutes() -> None:
    plan = retimed(package(), {"t105-asn": ("10:08", "08:10")})
    assert found(plan) == [
        (
            "slow_leg",
            "Tåg 105 tar 2 h 8 min mellan Norrby och Åsen. Andra tåg tar 8 min (median av 9 tåg).",
        ),
        ("backwards_dwell", "Tåg 105 avgår från Åsen 08:10, 1 h 58 min före ankomsten 10:08."),
    ]
    [slow, _] = deviations(plan)
    assert (slow.id, slow.calls, slow.usual, slow.samples) == (
        "slow_leg:t105:nby.asn",
        ["t105-asn", "t105-nby"],
        8,
        9,
    )


def test_fast_leg() -> None:
    plan = retimed(package(), {"t105-asn": ("08:02", "08:10")})
    assert found(plan) == [
        (
            "fast_leg",
            "Tåg 105 tar 2 min mellan Norrby och Åsen. Andra tåg tar 8 min (median av 9 tåg).",
        )
    ]


def test_backwards_leg_is_marked_even_without_other_trains() -> None:
    plan = retimed(package(), {"t101-asn": ("05:50", "06:10")}, keep=["t101"])
    assert found(plan) == [
        (
            "backwards_leg",
            "Tåg 101 är framme i Åsen 05:50 men lämnar Norrby först 06:00.",
        )
    ]


def test_long_stop_compared_with_the_other_trains() -> None:
    plan = retimed(package(), AFTER_ASN)
    assert found(plan) == [
        (
            "long_dwell",
            "Tåg 105 står 1 h 2 min i Åsen (ankomst 08:08, avgång 09:10). Andra tåg står 2 min "
            "(median av 9 tåg).",
        )
    ]


def test_long_stop_without_a_comparison_uses_the_absolute_limit() -> None:
    three_hours: dict[str, Times] = {
        "t101-asn": ("06:08", "09:10"),
        "t101-lvh": ("09:14", "09:15"),
        "t101-mla": ("09:19", "09:21"),
        "t101-sjv": ("09:29", None),
    }
    plan = retimed(package(), three_hours, keep=["t101"])
    assert found(plan) == [
        (
            "long_dwell",
            "Tåg 101 står 3 h 2 min i Åsen (ankomst 06:08, avgång 09:10). För få andra tåg "
            "stannar här för en jämförelse; uppehåll på 3 h eller mer markeras ändå.",
        )
    ]


def test_too_few_other_trains_means_nothing_to_compare() -> None:
    an_hour_late: dict[str, Times] = {**AFTER_ASN, "t105-asn": ("09:08", "09:10")}
    plan = retimed(package(), an_hour_late, keep=["t101", "t103", "t105"])
    assert found(plan) == [], "two others are too few"


def test_a_train_that_runs_past_midnight_is_not_marked() -> None:
    late: dict[str, Times] = {
        "t107-nby": (None, "23:58"),
        "t107-asn": ("00:06", "00:08"),
        "t107-lvh": ("00:12", "00:13"),
        "t107-mla": ("00:17", "00:19"),
        "t107-sjv": ("00:27", None),
    }
    assert deviations(retimed(package(), late)) == []


def test_a_passage_is_no_stop() -> None:
    plan = package()
    trains = [
        t.model_copy(
            update={
                "calls": [
                    c.model_copy(update={"stops": False, "arrival": "06:14", "departure": "07:30"})
                    if c.id == "t101-lvh"
                    else c
                    for c in t.calls
                ]
            }
        )
        for t in plan.trains
    ]
    kinds = [d.kind for d in deviations(plan.model_copy(update={"trains": trains}))]
    assert "long_dwell" not in kinds


def test_the_id_says_what_and_where_and_the_fingerprint_only_the_calls_it_is_about() -> None:
    [first] = deviations(retimed(package(), AFTER_ASN))
    elsewhere = retimed(package(), {**AFTER_ASN, "t105-sjv": ("09:30", None)})
    [same] = deviations(elsewhere)
    assert (same.id, same.fingerprint) == (first.id, first.fingerprint)
    moved = retimed(package(), {**AFTER_ASN, "t105-asn": ("08:08", "09:11")})
    [changed] = deviations(moved)
    assert changed.id == first.id and changed.fingerprint != first.fingerprint


def test_duration_reads_as_the_old_one() -> None:
    assert [duration(m) for m in (8, 14.5, 60, 125, -15)] == [
        "8 min",
        "15 min",
        "1 h",
        "2 h 5 min",
        "15 min",
    ]


@pytest.fixture
def planning(tmp_path: Path) -> Planning:
    return Planning(tmp_path / "planering.sqlite3")


def test_låt_stå_holds_until_the_calls_change_and_can_be_taken_back(planning: Planning) -> None:
    meet = planning.create(NewMeet(name="Grimslöv", first_date=MON, last_date=SUN)).meet
    src = source()
    odd = result(src)
    odd = odd.model_copy(update={"package": retimed(odd.package, AFTER_ASN)})
    planning.add_source(meet.id, src, b"1", odd)
    [deviation] = planning.check(meet.id).deviations
    with pytest.raises(PlanningError, match="ändrats"):
        planning.let_stand(meet.id, deviation.id, LetStand(fingerprint="0" * 64))
    with pytest.raises(PlanningError, match="finns inte"):
        planning.let_stand(meet.id, "slow_leg:t1:a.b", LetStand(fingerprint=deviation.fingerprint))
    planning.let_stand(meet.id, deviation.id, LetStand(fingerprint=deviation.fingerprint))
    planning.change(meet.id, PlaceChange(place="asn", phone="211"))  # something else
    [kept] = planning.check(meet.id).deviations
    assert kept.let_stand, "kept through other saves"
    planning.change(meet.id, CallChange(call="t105-asn", field="departure", value="09:11"))
    [back] = planning.check(meet.id).deviations
    assert not back.let_stand, "back when the calls change"
    planning.let_stand(meet.id, back.id, LetStand(fingerprint=back.fingerprint))
    planning.take_back(meet.id, back.id)
    assert not planning.check(meet.id).deviations[0].let_stand
    with pytest.raises(PlanningError, match="står inte"):
        planning.take_back(meet.id, back.id)
    assert "long_dwell" not in {f.code for f in planning.freeze(meet.id).findings}
