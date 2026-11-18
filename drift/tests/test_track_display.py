"""Spår-vyn (BOXIOS-16, H65), ported from the old Server's tests/test_track_display.py."""

from __future__ import annotations

import pytest

from contracts import station
from contracts.meet import Place, PlaceKind, PlanTrack
from drift.track_display import (
    TrackDisplayConflict,
    TracksChanged,
    base_order,
    checked,
    shown,
)


def place(*names: str) -> Place:
    return Place(
        id="asn",
        code="Ån",
        name="Åsen",
        kind=PlaceKind.MANNED,
        tracks=[PlanTrack(name=name, sort_order=index) for index, name in enumerate(names)],
    )


def listed(display: station.TrackDisplay) -> list[tuple[str, bool]]:
    return [(t.track, t.visible) for t in display.tracks]


def test_the_plans_order_then_the_timetables_other_tracks() -> None:
    assert base_order(place("1", "2", "10"), ["2", "3a", "", "3a"]) == ["1", "2", "10", "3a"]


def test_without_a_saved_choice_every_track_is_shown_in_the_plans_order() -> None:
    display = shown(["1", "2", "10"], 0, None)
    assert listed(display) == [("1", True), ("2", True), ("10", True)]
    assert (display.revision, display.customized) == (0, False)


def test_saved_order_and_hidden_tracks_survive_and_new_tracks_come_last_visible() -> None:
    saved = {"order": ["10", "gone", "1", "2"], "hidden": ["2", "gone"]}
    display = shown(["1", "2", "10", "new"], 3, saved)
    assert listed(display) == [("10", True), ("1", True), ("2", False), ("new", True)]
    assert (display.revision, display.customized) == (3, True)


def test_a_save_names_every_current_track_exactly_once() -> None:
    change = station.TrackDisplayChange(
        revision=0,
        tracks=[station.TrackShown(track="2"), station.TrackShown(track="1", visible=False)],
    )
    assert checked(["1", "2"], 0, change) == {"order": ["2", "1"], "hidden": ["1"]}
    for wrong in (["1"], ["1", "2", "3"], ["1", "1"], ["1", "2", "2"]):
        bad = station.TrackDisplayChange(
            revision=0, tracks=[station.TrackShown(track=t) for t in wrong]
        )
        with pytest.raises(TracksChanged):
            checked(["1", "2"], 0, bad)


def test_a_stale_revision_never_overwrites_and_a_reset_has_no_tracks() -> None:
    with pytest.raises(TrackDisplayConflict):
        checked(["1"], 2, station.TrackDisplayChange(revision=1))
    assert checked(["1"], 2, station.TrackDisplayChange(revision=2)) is None
