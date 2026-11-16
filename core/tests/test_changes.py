"""The ten driftändringar on a package (DRIFT-41, H12, H43), on Provbanan: 101 Norrby 06:00 →
Åsen 06:08/06:10 → Lövhult (halt) → Mellanå 06:19/06:21 → Sjövik 06:29, and 102 back."""

from __future__ import annotations

from importlib.resources import files

import pytest

from contracts import drift as changes
from contracts.common import Weekday
from contracts.meet import ClearanceMode, MeetPackage, PlaceKind, TrackKind
from contracts.reasons import Reason
from core.changes import ChangeError, apply, touches, train


@pytest.fixture
def package() -> MeetPackage:
    raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    return MeetPackage.model_validate_json(raw)


def calls(package: MeetPackage, train_id: str) -> list[tuple[str, str | None, str | None]]:
    return [(c.place, c.arrival, c.departure) for c in train(package, train_id).calls]


def refused(package: MeetPackage, change: changes.DriftChange) -> Reason:
    with pytest.raises(ChangeError) as error:
        apply(package, change, "c1")
    return error.value.reason


def test_a_change_gives_a_new_package_and_leaves_the_version_as_it_is(
    package: MeetPackage,
) -> None:
    changed = apply(package, changes.CancelTrain(train="t101"), "c1")
    assert "t101" not in {t.id for t in changed.trains}
    assert "t101" in {t.id for t in package.trains}, "the version is never changed"
    assert refused(package, changes.CancelTrain(train="t999")) == Reason.UNKNOWN_TRAIN


def test_an_extra_train_as_a_copy_with_a_new_number_and_time(package: MeetPackage) -> None:
    changed = apply(
        package, changes.ExtraTrain(number="9101", copy_of="t101", departure="10:00"), "c1"
    )
    extra = train(changed, "x-c1")
    assert (extra.number, extra.days, extra.train_type) == ("9101", [Weekday.MON], "Pt")
    assert calls(changed, "x-c1")[:2] == [("nby", None, "10:00"), ("asn", "10:08", "10:10")]
    assert [c.id for c in extra.calls][:2] == ["x-c1-0", "x-c1-1"]
    taken = changes.ExtraTrain(number="102", copy_of="t101", departure="10:00")
    assert refused(package, taken) == Reason.TRAIN_NUMBER_TAKEN


def test_an_extra_train_from_to_gets_the_places_between_and_the_timetables_times(
    package: MeetPackage,
) -> None:
    extra = changes.ExtraTrain(
        number="9801", from_place="nby", to_place="sjv", departure="10:00", days=[Weekday.MON]
    )
    changed = apply(package, extra, "c1")
    # 8 minutes Norrby–Åsen, 9 Åsen–Mellanå and 8 Mellanå–Sjövik, and a minute at each stop.
    assert calls(changed, "x-c1") == [
        ("nby", None, "10:00"),
        ("asn", "10:08", "10:09"),
        ("mla", "10:18", "10:19"),
        ("sjv", "10:27", None),
    ]
    closed = apply(package, changes.ChangePlace(section="s-mla-sjv", closed=True), "c0")
    assert refused(closed, extra) == Reason.NO_ROUTE
    lost = changes.ExtraTrain(number="9802", from_place="nby", to_place="lvh", departure="10:00")
    assert refused(package, lost) == Reason.UNKNOWN_PLACE, "a halt is no place to clear to"


def test_times_for_the_whole_train_from_a_call_or_per_call(package: MeetPackage) -> None:
    later = apply(package, changes.ChangeTimes(train="t101", minutes=10), "c1")
    assert calls(later, "t101")[:2] == [("nby", None, "06:10"), ("asn", "06:18", "06:20")]
    held = apply(package, changes.ChangeTimes(train="t101", minutes=10, from_call="t101-asn"), "c1")
    assert calls(held, "t101")[1] == ("asn", "06:08", "06:20"), "it waits in Åsen"
    assert calls(held, "t101")[-1] == ("sjv", "06:39", None)
    one = changes.ChangeTimes(
        train="t101", calls=[changes.CallTime(call="t101-mla", departure="06:25")]
    )
    assert calls(apply(package, one, "c1"), "t101")[3] == ("mla", "06:19", "06:25")
    backwards = changes.ChangeTimes(
        train="t101", calls=[changes.CallTime(call="t101-mla", arrival="06:30")]
    )
    assert refused(package, backwards) == Reason.INVALID_TIME
    assert refused(package, changes.ChangeTimes(train="t101", minutes=-720)) == Reason.INVALID_TIME


def test_a_train_late_in_the_evening_runs_past_midnight(package: MeetPackage) -> None:
    late = apply(
        package, changes.ExtraTrain(number="9199", copy_of="t101", departure="23:55"), "c1"
    )
    asn, sjv = train(late, "x-c1").calls[1], train(late, "x-c1").calls[-1]
    assert (asn.arrival, asn.departure, asn.day_offset) == ("00:03", "00:05", 1)
    assert (sjv.arrival, sjv.day_offset) == ("00:24", 1)


def test_places_and_sections(package: MeetPackage) -> None:
    closed = apply(package, changes.ChangePlace(section="s-nby-asn", closed=True), "c1")
    assert next(s for s in closed.sections if s.id == "s-nby-asn").closed
    direct = changes.ChangePlace(section="s-nby-asn", clearance_mode=ClearanceMode.DIRECT)
    mode = next(s for s in apply(package, direct, "c1").sections if s.id == "s-nby-asn")
    assert mode.clearance_mode == ClearanceMode.DIRECT
    unmanned = apply(package, changes.ChangePlace(place="asn", place_kind="unmanned"), "c1")
    assert next(p for p in unmanned.places if p.id == "asn").kind == PlaceKind.UNMANNED
    halt = changes.ChangePlace(place="lvh", place_kind="manned")
    assert refused(package, halt) == Reason.UNKNOWN_PLACE
    double = apply(
        package, changes.ChangeSectionTracks(section="s-nby-asn", tracks=TrackKind.DOUBLE), "c1"
    )
    assert next(s for s in double.sections if s.id == "s-nby-asn").tracks == TrackKind.DOUBLE


def test_a_track_days_number_stop_and_note(package: MeetPackage) -> None:
    track = apply(package, changes.ChangeTrack(call="t101-asn", track="2"), "c1")
    assert train(track, "t101").calls[1].track == "2"
    assert refused(package, changes.ChangeTrack(call="t101-asn", track="9")) == (
        Reason.UNKNOWN_TRACK
    )
    days = apply(package, changes.ChangeDays(train="t101", days=[Weekday.TUE]), "c1")
    assert train(days, "t101").days == [Weekday.TUE]
    number = apply(package, changes.ChangeNumber(train="t101", number="111"), "c1")
    assert train(number, "t101").number == "111"
    assert refused(package, changes.ChangeNumber(train="t101", number="102")) == (
        Reason.TRAIN_NUMBER_TAKEN
    )
    passing = apply(package, changes.NoStop(call="t101-asn"), "c1")
    assert not train(passing, "t101").calls[1].stops
    noted = apply(package, changes.TrainNote(train="t101", text="Ånglok"), "c1")
    assert train(noted, "t101").note == "Ånglok"
    elsewhere = changes.TrainNote(train="t101", call="t102-asn", text="x")
    assert refused(package, elsewhere) == Reason.UNKNOWN_CALL


def test_what_a_change_touches(package: MeetPackage) -> None:
    assert touches(package, changes.CancelTrain(train="t101")) == ({"t101"}, set())
    assert touches(package, changes.ChangeTrack(call="t102-asn", track="1")) == ({"t102"}, set())
    closed = changes.ChangePlace(section="s-nby-asn", closed=True)
    assert touches(package, closed) == (set(), {"s-nby-asn"})
    assert touches(package, changes.TrainNote(train="t101", text="x")) == (set(), set())
    extra = changes.ExtraTrain(number="9", copy_of="t101", departure="10:00")
    assert touches(package, extra) == (set(), set())
