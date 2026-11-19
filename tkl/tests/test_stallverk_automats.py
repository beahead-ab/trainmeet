"""The station automats, the magazine and the remote routes in the station's own interlocking
(#36 del b, FR12, FR13, FR15, FR22, FR24–FR29, FR40, FR42, FR45), on a made-up station: two
station tracks between two single lines (tkl.tests.provstation.provby), with its remote catalogue
derived as Studio does. Nothing here names a station (RS13)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from contracts.common import Side
from contracts.reasons import Reason
from contracts.station import RouteBy
from contracts.station_model import PanelFunction, PanelFunctionType, StationModel
from contracts.station_outside import AutomatKind, RemoteRoute
from contracts.tkl import TklAutomatSpec, TklFunctionAction
from tkl.stallverk import Interlocking, plant_of
from tkl.stallverk import automats as automat
from tkl.stallverk.automats import MAGAZINE_DELAY, Want
from tkl.studio import fjarr
from tkl.tests.provstation import provby

START = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)
SPECS = [
    TklAutomatSpec(code="A3", kind=AutomatKind.A3, default=True),
    TklAutomatSpec(code="A2", kind=AutomatKind.A2),
    TklAutomatSpec(code="A1", kind=AutomatKind.A1),
    TklAutomatSpec(code="ANIn", kind=AutomatKind.AN, signals=["In"]),
    TklAutomatSpec(code="AUIn2", kind=AutomatKind.AU, signals=["In2"]),
    TklAutomatSpec(code="L1", kind=AutomatKind.LOCAL_RELEASE, function="Lokal frigivning"),
]
WEST, EAST = Side.LEFT, Side.RIGHT
ON, OFF = TklFunctionAction.ON, TklFunctionAction.OFF


def area() -> StationModel:
    """Provby with a local release of track 2 (FR41): its dwarf and combined signals show
    shunting, and nothing goes in while it is on."""
    release = PanelFunction(
        type=PanelFunctionType.LOCAL_RELEASE,
        name="Lokal frigivning",
        track_circuits=["Spår 2"],
        signals=["21", "22", "D"],
    )
    return provby(functions=[release])


class Station:
    """The interlocking with a clock in the test's hand, and the catalogue by start and end."""

    def __init__(self, model: StationModel | None = None) -> None:
        self.at = START
        plant = plant_of(model or area())
        self.it = Interlocking(plant, now=lambda: self.at)
        self.catalogue = [c.remote for c in fjarr.candidates(plant)]

    def route(self, start: str, end: str) -> RemoteRoute:
        return next(r for r in self.catalogue if (r.start, r.end) == (start, end))

    def want(self, start: str, end: str, call: str, side: Side) -> Want:
        return Want(self.route(start, end), call, side)

    def later(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)

    def laid(self) -> list[tuple[str, str, RouteBy | None, str | None]]:
        return [(r.start, r.end, r.by, r.automat) for r in self.it.view().routes]

    def free(self, start: str, end: str) -> None:
        first = self.it.set_by(start, end)
        assert first is not None
        assert self.it.free_route(first).accepted

    def on(self, code: str, by: RouteBy = RouteBy.STATION) -> None:
        assert automat.set_automat(self.it, SPECS, code, True, by).accepted


def test_the_catalogue_of_the_made_up_station() -> None:
    station = Station()
    ids = {(r.start, r.end): (r.direction.value, r.exit, r.track) for r in station.catalogue}
    assert ids == {
        ("In", "12"): ("in", "V", "1"),
        ("In", "22"): ("in", "V", "2"),
        ("11", "Ut"): ("out", "V", "1"),
        ("21", "Ut"): ("out", "V", "2"),
        ("In2", "11"): ("in", "O", "1"),
        ("In2", "21"): ("in", "O", "2"),
        ("12", "Ut2"): ("out", "O", "1"),
        ("22", "Ut2"): ("out", "O", "2"),
    }


# --- Remote routes (FR12, FR13, FR15) -----------------------------------------------------------


def test_a_remote_request_is_laid_and_locked_as_the_controllers() -> None:
    station = Station()
    station.it.set_remote("Fjärr Västra")
    answer = automat.request(station.it, station.route("In", "22"), "r1")
    assert (answer.locked, answer.reason) == (True, None)
    [route] = station.it.view().routes
    assert (route.catalogue, route.by, route.request_id) == ("In-22", RouteBy.REMOTE, "r1")
    again = automat.request(station.it, station.route("In", "22"), "r1")
    assert again.locked, "a resend of the same request is locked again"
    state = automat.route_state(station.it, station.catalogue, SPECS)
    [locked] = state.locked
    assert (locked.route, locked.by, locked.request_id) == ("In-22", RouteBy.REMOTE, "r1")
    assert state.occupied == [], "only level 3 reports occupied tracks"


def test_a_remote_request_is_refused_with_the_interlockings_reason() -> None:
    station = Station()
    assert automat.request(station.it, station.route("In", "22"), "r1").locked
    answer = automat.request(station.it, station.route("In2", "21"), "r2")
    assert (answer.locked, answer.reason) == (False, Reason.CONFLICTING_ROUTE)
    assert "låst i vägen In → 22" in answer.message
    station.free("In", "22")
    assert station.it.function("Lokal frigivning", ON).accepted
    answer = automat.request(station.it, station.route("In2", "21"), "r3")
    assert (answer.locked, answer.reason) == (False, Reason.AREA_RELEASED)
    assert station.it.function("Lokal frigivning", OFF).accepted
    put = station.it.put_train("41", section="Spår 1")
    assert put.accepted
    answer = automat.request(station.it, station.route("In", "12"), "r4")
    assert (answer.locked, answer.reason) == (False, Reason.TRACK_OCCUPIED)


def test_a_cancelled_route_is_released_when_the_interlocking_allows() -> None:
    station = Station()
    assert automat.request(station.it, station.route("In", "12"), "r1").locked
    [route] = station.it.view().routes
    assert station.it.put_train("41", exit="V").accepted
    assert station.it.step(route.id).accepted  # the train is in the route
    held = automat.cancel(station.it, "r1")
    assert held is not None and not held.accepted, "not under the train"
    for _ in range(10):
        if not station.it.step(route.id).accepted:
            break
    assert station.it.arrive(route.id).accepted
    assert automat.cancel(station.it, "r1") is None, "gone with its train"


def test_the_stations_own_panel_lays_nothing_while_remote_controlled_and_routes_stay() -> None:
    """FR6, FR17: the station's own panel lays nothing; FR15: a route the controller laid stays
    when the station is taken back, and route.state still says who laid it."""
    station = Station()
    station.it.set_remote("Fjärr Västra")
    refused = station.it.set_route("In", "12")
    assert not refused.accepted and "fjärrstyrs från Fjärr Västra" in refused.message
    assert not station.it.lay_lever("1").accepted
    assert automat.request(station.it, station.route("In", "12"), "r1").locked
    first = station.it.set_by("In", "12")
    assert first is not None and not station.it.release(first).accepted
    assert station.it.set_remote(None)
    state = automat.route_state(station.it, station.catalogue, SPECS)
    assert [(r.route, r.by) for r in state.locked] == [("In-12", RouteBy.REMOTE)]
    assert station.it.set_route("In2", "21").accepted
    state = automat.route_state(station.it, station.catalogue, SPECS)
    assert [(r.route, r.by) for r in state.locked] == [
        ("In-12", RouteBy.REMOTE),
        ("In2-21", RouteBy.STATION),
    ]


# --- The automats (FR24–FR27, FR40, FR45) -------------------------------------------------------


def test_a3_lays_the_routes_in_and_out() -> None:
    station = Station()
    wants = [station.want("In", "12", "c41", WEST)]
    assert automat.tick(station.it, SPECS, wants) == [], "no automat on, nothing laid"
    station.on("A3")
    said = automat.tick(station.it, SPECS, wants)
    assert said and station.laid() == [("In", "12", RouteBy.AUTOMAT, "A3")]
    assert automat.tick(station.it, SPECS, wants) == [], "laid once"
    station.free("In", "12")
    automat.tick(station.it, SPECS, [station.want("12", "Ut2", "c41", WEST)])
    assert station.laid() == [("12", "Ut2", RouteBy.AUTOMAT, "A3")]
    state = automat.route_state(station.it, station.catalogue, SPECS)
    assert [(a.code, a.by) for a in state.automats] == [("A3", RouteBy.STATION)]
    assert [(r.route, r.automat) for r in state.locked] == [("12-Ut2", "A3")]


def test_an_and_au_lay_only_from_their_entry_signal() -> None:
    station = Station()
    station.on("ANIn")
    wants = [station.want("In2", "21", "c42", EAST), station.want("In", "12", "c41", WEST)]
    automat.tick(station.it, SPECS, wants)
    assert station.laid() == [("In", "12", RouteBy.AUTOMAT, "ANIn")]
    station.on("AUIn2")
    automat.tick(station.it, SPECS, wants)
    assert ("In2", "21", RouteBy.AUTOMAT, "AUIn2") in station.laid()
    # Out: only for the trains it took in.
    station.free("In", "12")
    station.free("In2", "21")
    automat.tick(station.it, SPECS, [station.want("12", "Ut2", "c99", WEST)])
    assert all(r[0] != "12" for r in station.laid()), "AN does not lay out a train it never took"
    automat.tick(station.it, SPECS, [station.want("12", "Ut2", "c41", WEST)])
    assert ("12", "Ut2", RouteBy.AUTOMAT, "ANIn") in station.laid()


def test_a1_takes_a_meeting_and_switches_off_afterwards() -> None:
    """FR26: A1, enstaka möte: two trains from opposite ends, in and out, then it switches
    itself off; a third train waits."""
    station = Station()
    station.on("A1")
    automat.tick(
        station.it,
        SPECS,
        [
            station.want("In", "12", "c41", WEST),
            station.want("In2", "21", "c42", EAST),
            station.want("In2", "11", "c43", EAST),  # a third: not this meeting
        ],
    )
    assert sorted(station.laid()) == [
        ("In", "12", RouteBy.AUTOMAT, "A1"),
        ("In2", "21", RouteBy.AUTOMAT, "A1"),
    ]
    station.free("In", "12")
    station.free("In2", "21")
    automat.tick(
        station.it,
        SPECS,
        [station.want("12", "Ut2", "c41", WEST), station.want("21", "Ut", "c42", EAST)],
    )
    assert sorted(station.laid()) == [
        ("12", "Ut2", RouteBy.AUTOMAT, "A1"),
        ("21", "Ut", RouteBy.AUTOMAT, "A1"),
    ]
    assert [a.code for a in station.it.fjarr.automats] == ["A1"], "on until the trains are out"
    station.free("12", "Ut2")
    station.free("21", "Ut")
    said = automat.tick(station.it, SPECS, [])
    assert said == ["A1 kopplades ur av sig själv efter mötet."]
    assert station.it.fjarr.automats == []


def test_a2_takes_a_passing_from_one_end() -> None:
    """A2, enstaka förbigång: two trains from the same end; one from the other end waits."""
    station = Station()
    station.on("A2")
    automat.tick(
        station.it,
        SPECS,
        [station.want("In", "22", "c41", WEST), station.want("In2", "11", "c42", EAST)],
    )
    assert station.laid() == [("In", "22", RouteBy.AUTOMAT, "A2")]
    automat.tick(station.it, SPECS, [station.want("In", "12", "c43", WEST)])
    assert ("In", "12", RouteBy.AUTOMAT, "A2") not in station.laid(), "In is still locked"
    assert [m.route for m in station.it.fjarr.magazine] == ["In-12"]


def test_a_conflicting_route_waits_in_the_magazine_and_is_laid_after_the_train() -> None:
    """FR45: the route that conflicts with a set one goes into the magazine and is laid by
    itself once the incoming train has reached its end, after a delay."""
    station = Station()
    station.on("A3")
    first = [station.want("In", "12", "c41", WEST)]
    automat.tick(station.it, SPECS, first)
    both = [*first, station.want("In2", "11", "c42", EAST)]
    said = automat.tick(station.it, SPECS, both)
    assert said == ["A3: In2 → 11 magasinerad."]
    [kept] = station.it.fjarr.magazine
    assert (kept.route, kept.automat, kept.call) == ("In2-11", "A3", "c42")
    assert kept.blocked_by == [station.it.set_by("In", "12")]
    station.free("In", "12")
    automat.tick(station.it, SPECS, both[1:])
    assert station.laid() == [], "after a delay, not at once"
    station.later(MAGAZINE_DELAY + 1)
    said = automat.tick(station.it, SPECS, both[1:])
    assert station.laid() == [("In2", "11", RouteBy.AUTOMAT, "A3")]
    assert said[0].startswith("A3: ur magasinet:") and station.it.fjarr.magazine == []


def test_a_train_that_no_longer_wants_its_route_leaves_the_magazine() -> None:
    station = Station()
    station.on("A3")
    automat.tick(station.it, SPECS, [station.want("In", "12", "c41", WEST)])
    automat.tick(station.it, SPECS, [station.want("In2", "11", "c42", EAST)])
    assert station.it.fjarr.magazine
    automat.tick(station.it, SPECS, [])
    assert station.it.fjarr.magazine == []


def test_switching_automats_and_their_codes() -> None:
    station = Station()
    station.on("A3", RouteBy.AUTOMAT)
    assert automat.set_automat(station.it, SPECS, "A3", True, RouteBy.REMOTE).message == (
        "A3 är redan inkopplad."
    )
    refused = automat.set_automat(station.it, SPECS, "L1", True, RouteBy.STATION)
    assert not refused.accepted, "the local area is switched as its function"
    assert not automat.set_automat(station.it, SPECS, "A9", True, RouteBy.STATION).accepted
    assert automat.default_automat(SPECS) == SPECS[0]
    assert fjarr.code_for(AutomatKind.AN, ["21"], 0) == "AN"
    assert fjarr.code_for(AutomatKind.AN, ["121"], 1) == "AN121", "FR40: AN 21 and AN 121"
    off = automat.set_automat(station.it, SPECS, "A3", False, RouteBy.REMOTE)
    assert off.message == "Stationsautomaten A3 kopplades ur från fjärr."


# --- The local area (FR20–FR23, FR41, FR42) -----------------------------------------------------


def test_the_local_area_border_and_taking_it_back_when_empty() -> None:
    """FR42: in only when no route goes to, from or through it, and then none goes in. FR22: a
    train out of it goes from its border, laid by the controller. FR23: back when empty."""
    station = Station()
    station.it.set_remote("Fjärr Västra")
    assert automat.request(station.it, station.route("In", "22"), "r1").locked
    refused = station.it.switch_local("Lokal frigivning", True)
    assert not refused.accepted and "Lös ut vägarna i området först" in refused.message
    station.free("In", "22")
    assert station.it.put_train("41", section="Spår 2").accepted
    assert station.it.switch_local("Lokal frigivning", True).accepted
    state = automat.route_state(station.it, station.catalogue, SPECS)
    assert [(a.code, a.tracks) for a in state.local_areas] == [("L1", ["2"])]
    # Into the area: no; out of it from the border: yes (FR22).
    assert not automat.request(station.it, station.route("In", "22"), "r2").locked
    out = automat.request(station.it, station.route("22", "Ut2"), "r3")
    assert out.locked, out.message
    # The station's own panel gives it back on the spot (FR44) but switches nothing else.
    assert not station.it.function("Lokal frigivning", ON).accepted
    # The controller takes it back when it is empty (FR23).
    busy = station.it.switch_local("Lokal frigivning", False, empty=True)
    assert not busy.accepted and "inte tomt" in busy.message
    assert station.it.remove_train(station.it.view().trains[0].id).accepted
    assert station.it.switch_local("Lokal frigivning", False, empty=True).accepted
    assert automat.route_state(station.it, station.catalogue, SPECS).local_areas == []


def test_only_a_train_route_out_from_the_border_while_it_is_released() -> None:
    """FR22, FR42: a shunting route inside the area is the people's own, by the modules'
    buttons; a train route from its border signal out of it may be laid; nothing goes in."""
    station = Station()
    assert station.it.switch_local("Lokal frigivning", True).accepted
    inside = station.it.lay_route("D", "22")
    assert not inside.accepted and "lokalt frigivet" in inside.message
    assert not station.it.lay_route("In2", "21").accepted
    assert station.it.lay_route("21", "Ut").accepted
