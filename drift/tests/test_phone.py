"""The telephone number during the meet (TRAFIK-06, H30, H24): a field per place, the meet's
game number. Trafikledningen changes it as a Drift event, and every TKL and app reads it in its
phone list. It is a setting of the meet, so a time jump or Ångra leaves it as it is."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib.resources import files

import pytest

from contracts import drift as events
from contracts.meet import MeetPackage
from contracts.reasons import Reason
from drift.engine import Drift, Refused
from drift.now import now as nu
from drift.snapshot import snapshot

START = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


@pytest.fixture
def drift() -> Drift:
    raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
    engine = Drift(MeetPackage.model_validate_json(raw), [], now=START)
    engine.start(START)
    return engine


def numbers(drift: Drift, place: str) -> dict[str, str | None]:
    return {p.place: p.phone for p in snapshot(drift, place, at(1)).all_places}


def test_the_package_gives_the_numbers_first(drift: Drift) -> None:
    assert numbers(drift, "nby") == {"nby": "101", "asn": "102", "mla": "103", "sjv": "104"}


def test_a_changed_number_reaches_every_place(drift: Drift) -> None:
    before = {place: snapshot(drift, place, at(1)).place_revision for place in drift.stops()}
    drift.set_phone(events.PlacePhone(place="asn", phone=" 202 "), at(2))
    event = drift.history[-1]
    assert (event.kind, event.place, event.actor.kind) == (
        events.EventKind.PLACE_PHONE,
        "asn",
        events.ActorKind.DISPATCHER,
    )
    for place in drift.stops():
        seen = snapshot(drift, place, at(3))
        assert seen.place_revision > before[place], "every TKL reads its phone list again"
        assert numbers(drift, place)["asn"] == "202"
    (neighbour,) = [n for n in snapshot(drift, "nby", at(3)).neighbours if n.place == "asn"]
    assert neighbour.phone == "202"


def test_an_empty_number_takes_it_away_and_the_same_number_is_no_event(drift: Drift) -> None:
    drift.set_phone(events.PlacePhone(place="sjv", phone=None), at(1))
    assert numbers(drift, "nby")["sjv"] is None
    size = len(drift.history)
    drift.set_phone(events.PlacePhone(place="sjv"), at(2))
    drift.set_phone(events.PlacePhone(place="nby", phone="101"), at(3))
    assert len(drift.history) == size


def test_only_a_place_of_the_meet_has_a_number(drift: Drift) -> None:
    for place in ("lvh", "nowhere"):  # A halt has no telephone, nor does a place not here.
        with pytest.raises(Refused) as refused:
            drift.set_phone(events.PlacePhone(place=place, phone="9"), at(1))
        assert refused.value.reason == Reason.UNKNOWN_PLACE


def test_a_number_is_kept_through_a_replay_a_jump_and_ångra(drift: Drift) -> None:
    drift.control_clock(events.ClockControl(action=events.ClockAction.JUMP, time="08:00"), at(1))
    drift.set_phone(events.PlacePhone(place="mla", phone="303"), at(2))
    drift.control_clock(events.ClockControl(action=events.ClockAction.UNDO_JUMP), at(3))
    assert drift.phone("mla") == "303"
    again = Drift(drift.package, drift.history, now=at(4))
    assert again.phone("mla") == "303"


def test_nu_shows_no_numbers(drift: Drift) -> None:
    """Nu is open to everyone who looks, so it holds no numbers (B13)."""
    drift.set_phone(events.PlacePhone(place="asn", phone="202"), at(1))
    assert "202" not in nu(drift, at(2)).model_dump_json()
