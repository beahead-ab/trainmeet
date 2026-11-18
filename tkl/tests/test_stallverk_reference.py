"""The interlocking on the four reference stations (#84, TKL40): every route the engine derives
can be set from a clean state, run with Kör and released; every chain can be set; every lever
lays its switches; and two switches that drag each other never lie crossed (TKL104).

Nothing here names a station (RS13): the stations are found from the model files, and a station
is picked by what its data has.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from contracts.station_model import Position, StationModel
from contracts.tkl import TklReportKind
from tkl.stallverk import Interlocking, Plant, Way, plant_of
from tkl.standard import RouteKind

MODELS = Path(__file__).resolve().parents[2] / "tkl" / "referens"
STATIONS = sorted(p.name.removesuffix(".tkl.json") for p in MODELS.glob("*.tkl.json"))
PLUS, MINUS = Position.PLUS, Position.MINUS


def plant(station: str) -> Plant:
    text = (MODELS / f"{station}.tkl.json").read_text("utf-8")
    return plant_of(StationModel.model_validate_json(text))


def test_there_are_four() -> None:
    assert len(STATIONS) == 4


@pytest.mark.parametrize("station", STATIONS)
def test_every_route_can_be_set_from_a_clean_state_and_released(station: str) -> None:
    found = plant(station)
    ways = found.preferred()
    assert ways, "the engine derives routes"
    for way in ways:
        it = Interlocking(found)
        laid = it.set_route(way.start, way.end, way.kind)
        assert laid.accepted, (way.name, laid.message)
        [route] = it.view().routes
        assert route.kind.value == way.kind.value
        assert [p for s in route.sections for p in s.pieces] == list(way.pieces)
        released = it.release(laid.route or 0)
        assert released.accepted, (way.name, released.message)
        assert it.view().routes == [] and it.view().pieces == {}


def _put_at_start(it: Interlocking, way: Way) -> bool:
    for kind, name in sorted(way.starts):
        put = it.put_train("1", section=name) if kind == "section" else it.put_train("1", exit=name)
        if put.accepted:
            return True
    return False


@pytest.mark.parametrize("station", STATIONS)
def test_every_route_runs_with_kor_and_frees_everything(station: str) -> None:
    """STV-06, STV-29: the route set, a train at its start, Kör section by section to the end,
    then out on the line or Ankommit. Nothing stays locked. (A train already standing next to
    a switch the route must move keeps it where it lies, so the route comes first.)"""
    found = plant(station)
    ran = 0
    for way in found.preferred():
        it = Interlocking(found)
        laid = it.set_route(way.start, way.end, way.kind)
        assert laid.accepted, (way.name, laid.message)
        route = laid.route or 0
        if not _put_at_start(it, way):
            # From a stop point or a buffer stop the train stands in the route's own first
            # section, having come in over the same switches: they stay as the route laid them.
            assert it.release(route).accepted
            assert _put_at_start(it, way), way.name
            laid = it.set_route(way.start, way.end, way.kind)
            assert laid.accepted, (way.name, laid.message)
            route = laid.route or 0
        ran += 1
        for _ in range(len(way.sections) + 1):
            [running] = [r for r in it.view().routes if r.id == route]
            if running.at == len(running.sections) - 1:
                break
            stepped = it.step(route)
            assert stepped.accepted, (way.name, stepped.message)
        if way.leaves is not None:
            left = it.step(route)
            assert left.accepted, (way.name, left.message)
            assert TklReportKind.DEPARTED in [r.kind for r in left.reports]
            assert it.view().trains == []
        else:
            arrived = it.arrive(route)
            assert arrived.accepted, (way.name, arrived.message)
            assert [t.section for t in it.view().trains] == [way.sections[-1][0]]
        after = it.view()
        assert after.routes == []
        assert all(not s.routes for s in after.switches.values())
    assert ran == len(found.preferred()), "every route has a place for a train at its start"


@pytest.mark.parametrize("station", STATIONS)
def test_every_chain_can_be_set_from_a_clean_state(station: str) -> None:
    """TKL53: a goal several signals away is set as the whole chain, or not at all."""
    found = plant(station)
    for kind in (RouteKind.TRAIN, RouteKind.SHUNTING):
        for start in sorted({w.start for w in found.preferred() if w.kind == kind}):
            for end in found.ends(kind, start):
                if (kind, start, end) in found.paths:
                    continue
                it = Interlocking(found)
                laid = it.set_route(start, end, kind)
                assert laid.accepted, (start, end, laid.message)
                parts = it.view().routes
                assert len(parts) > 1 and parts[0].start == start and parts[-1].end == end
                assert {p.chain for p in parts} == {parts[0].id}


@pytest.mark.parametrize("station", STATIONS)
def test_every_lever_lays_all_its_switches(station: str) -> None:
    """STV-52: coupled switches move together, also more than two on a lever, the reversed
    ones the other way, and with them the ones the lever drags along."""
    found = plant(station)
    for lever in found.model.levers:
        for side, wanted in ((MINUS, lever.minus), (PLUS, lever.plus)):
            it = Interlocking(found)
            laid = it.lay_lever(lever.id, side)
            assert laid.accepted, (lever.id, laid.message)
            shown = it.view().switches
            assert {p: shown[p].position for p in wanted} == dict(wanted), lever.id


def _dragging() -> list[str]:
    """The stations with two switches that drag each other: each to one side drags the other."""
    found = []
    for station in STATIONS:
        levers = {lever.id: lever for lever in plant(station).model.levers}
        for lever in levers.values():
            dragged = set(lever.minus) - set(lever.plus)
            if any(
                set(levers.get(d, lever).plus) - set(levers.get(d, lever).minus) for d in dragged
            ):
                found.append(station)
                break
    return found


@pytest.mark.parametrize("station", _dragging())
def test_switches_that_drag_each_other_never_lie_crossed(station: str) -> None:
    """TKL104: one switch to diverging drags the other, and the other to straight drags the
    first, so the two are never crossed: the first diverging with the other straight. Tried
    with levers and routes in a long random order."""
    found = plant(station)
    levers = {lever.id: lever for lever in found.model.levers}
    pairs = []
    for lever in levers.values():
        for other in set(lever.minus) - set(lever.plus):
            back = levers.get(other)
            if back is not None and lever.id in set(back.plus) - set(back.minus):
                pairs.append((lever.id, other))
    assert pairs
    touching = [
        w
        for w in found.preferred()
        if any(part in w.route.positions for pair in pairs for part in pair)
    ]
    pick = random.Random(84)
    it = Interlocking(found)
    for _ in range(400):
        roll = pick.random()
        if roll < 0.5:
            it.lay_lever(pick.choice([p for pair in pairs for p in pair]))
        elif roll < 0.8 and touching:
            way = pick.choice(touching)
            it.set_route(way.start, way.end, way.kind)
        elif it.view().routes:
            it.release(pick.choice(it.view().routes).id)
        shown = it.view().switches
        for first, other in pairs:
            crossed = (shown[first].position, shown[other].position) == (MINUS, PLUS)
            assert not crossed, (first, other)
