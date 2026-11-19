"""Delställverk (#87, TKL97–TKL103) in the interlocking: a part's area, the rules at the border,
the five messages, the one-way rule, switch streets, Klart and Grindar, Klart att skicka, and the
same rules at level 3 with the pretend LocoNet.

The made-up station with a yard (provstation.bangard) carries the general rules; the reference
station that has a part is found by its data, never by name (RS13). The tests marked "Ported"
carry an old cda-tkl test's behaviour, with the old test named.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from contracts import station
from contracts.station_model import (
    PartOwner,
    PartRules,
    Position,
    StationModel,
    SwitchStreet,
    TrackPiece,
)
from contracts.tkl import (
    TklInterlocking,
    TklPartMessageKind,
    TklPartRequestState,
    TklSetRoute,
)
from tkl.stallverk import Interlocking, Plant, load, plant_of
from tkl.stallverk.interlocking import STATION_BY
from tkl.stallverk.parts import plan_trains, street_end
from tkl.standard import RouteKind
from tkl.tests.niva3 import Rig, level_3
from tkl.tests.provstation import bangard

PLUS, MINUS = Position.PLUS, Position.MINUS
MODELS = Path(__file__).resolve().parents[2] / "tkl" / "referens"
YARD = "bangarden"
NOON = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def it(**more: object) -> Interlocking:
    return Interlocking(plant_of(bangard(**more)), now=lambda: NOON)


def routes(made: Interlocking) -> list[TklSetRoute]:
    return made.view().routes


def asked(made: Interlocking, part: str = YARD) -> int:
    shown = next(p for p in made.view().parts if p.id == part)
    return shown.requests[-1].id


# --- the part in the reference model (RS13: found by its data) ---------------------------------


def with_parts() -> list[StationModel]:
    found = []
    for path in sorted(MODELS.glob("*.tkl.json")):
        model = StationModel.model_validate_json(path.read_text("utf-8"))
        if model.parts:
            found.append(model)
    return found


@pytest.fixture(scope="module")
def reference() -> Plant:
    [model] = with_parts()
    return plant_of(model)


def test_one_reference_station_has_a_part_with_its_area_and_border(reference: Plant) -> None:
    [part] = reference.parts.values()
    spec = part.spec
    assert spec.own_place, "the yard is its own driftplats (TKL52, TKL101)"
    assert set(spec.switches) == {
        *["111", "114", "115", "118", "119", "127", "128", "130", "133", "150", "155"],
        *["42", "43", "51"],
    }, "the own switches of the document, and the depot's in the drawing"
    assert {b.switch: b.towards_part for b in spec.border} == {
        "103": MINUS,
        "132": PLUS,
        "144": PLUS,
        "164": PLUS,
    }, "grindväxlarna and their position towards the yard (TKL55, TKL56)"
    assert all(b.owner == PartOwner.STATION for b in spec.border), "TKL steers them (RANG-12)"
    assert spec.border_signals == ["3/3", "6/8", "6/9", "3/13"], "RANG-11"
    for number in ("170", "172", "173", "175", "112", "131", "154", "153", "161"):
        assert number not in part.own and number not in part.border, f"{number} is TKL's"
    nodes = {p.start for name in part.sections for p in _pieces(reference, name)}
    nodes |= {p.end for name in part.sections for p in _pieces(reference, name)}
    for number in part.own:
        assert reference.part_node[number] in nodes, f"{number} is inside the area"
    for name in ("51", "52", "53", "54", "6"):
        track = next(t for t in reference.model.station_tracks if t.id == name)
        assert set(track.pieces) <= set(part.pieces), f"track {name} is the yard's (RANG-08)"
    for name in ("11", "12", "13", "1a", "2a", "3", "4"):
        track = next(t for t in reference.model.station_tracks if t.id == name)
        assert not set(track.pieces) & set(part.pieces), f"track {name} is TKL's"


def _pieces(plant: Plant, section: str) -> list[TrackPiece]:
    return [plant.graph.pieces[p] for p in plant.sections[section].pieces]


def test_the_streets_come_out_of_the_track_plan_as_the_document_says(reference: Plant) -> None:
    """Ported: ranger-paths.test.mjs, 'the point chains come out of the track graph exactly as
    the layout owner described them'. The new H51 and Kolgård with 155 (RANG-18); Skiva is left
    out while the way to the turntable is open."""
    [part] = reference.parts.values()
    c, t = PLUS, MINUS
    assert {s.id: dict(s.positions) for s in part.streets.values()} == {
        "V51": {"103": t, "114": c, "115": t},
        "V52": {"103": t, "114": c, "115": c},
        "V53": {"103": t, "114": t, "111": c, "118": c},
        "V54": {"103": t, "114": t, "111": t, "118": t},
        "H51": {"132": c, "130": c, "127": t},
        "H52": {"132": c, "130": c, "127": c},
        "H53": {"132": c, "130": t, "128": t},
        "H54": {"132": c, "130": t, "128": c},
        "Last1": {"119": t},
        "Last2": {"119": c},
        "Last3": {"133": t},
        "Kolgard": {"133": c, "144": c, "150": t, "155": c},
        "Lokstall": {"133": c, "144": c, "150": c},
    }
    for street in part.streets.values():
        assert street_end(reference, street.positions) == street.track, street.id
        for number, position in street.positions.items():
            assert part.may_lay(number, position), f"{street.id} lays only the yard's: {number}"


def test_every_route_out_crosses_the_border_and_the_yard_cannot_set_it(reference: Plant) -> None:
    [part] = reference.parts.values()
    assert {r.id: (r.start, r.end) for r in part.routes_out.values()} == {
        "V3": ("3/1", "3/5"),
        "V4": ("3/1", "4/5"),
        "V5": ("3/1", "5/5"),
        "H3": ("6/6", "3/10"),
        "H4": ("6/6", "4/10"),
        "H5": ("6/6", "5/10"),
        "Spar6": ("6/7", "6/9"),
        "3d": ("3/2", "3/6"),
    }, "the document's table of requests (RANG-03); 3d to the right is missing, as in old TKL"
    made = Interlocking(reference)
    for out in part.routes_out.values():
        [chain] = reference.candidates(RouteKind.SHUNTING, out.start, out.end)[:1]
        positions = {k: v for way in chain for k, v in way.route.positions.items()}
        out_over = [
            n for n in part.border if positions.get(n) not in (None, part.border[n].towards_part)
        ]
        assert out_over, f"{out.id} goes out over a border switch"
        assert chain[0].start in part.signals
        said = made.part_route(part.id, out.start, out.end)
        assert not said.accepted, out.id
        assert made.part_request(part.id, out.id).accepted, out.id
        reply = made.part_reply(asked(made, part.id), True)
        assert reply.accepted, (out.id, reply.message)
        assert made.part_return(part.id, asked(made, part.id)).accepted
    assert routes(made) == []


def test_the_yard_requests_52_to_3_and_the_station_approves(reference: Plant) -> None:
    """The issue's test (#87): the street to 52, the request out to 3 from the right end, the
    station's approval, and Klart att skicka."""
    [part] = reference.parts.values()
    made = Interlocking(reference)
    assert made.part_street(part.id, "H52").accepted
    request = made.part_request(part.id, "H3")
    assert request.accepted, request.message
    assert request.message.startswith(f"{part.name} begär 52 → 3")
    view = made.view().parts[0]
    assert (
        view.requests[0].said == "52 → 3" and view.requests[0].state == TklPartRequestState.WAITING
    )
    approved = made.part_reply(view.requests[0].id, True)
    assert approved.accepted, approved.message
    assert [(r.start, r.end) for r in routes(made)] == [("6/6", "6/8"), ("6/8", "3/10")]
    assert all(r.part == part.id and r.request == view.requests[0].id for r in routes(made))
    assert made.part_ready(part.id, "3795").accepted
    assert [r.number for r in made.view().ready] == ["3795"]
    for number in ("170", "172"):
        refused = made.part_lever(part.id, number)
        assert not refused.accepted and "tillhör stationen" in refused.message, "RANG-19"


# --- the rules at the border (TKL99, RANG-12) ---------------------------------------------------


def test_the_part_lays_its_streets_but_never_into_the_station() -> None:
    """Ported: ranger-paths.test.mjs, 'one press lays the chain; a chain over a group lying out
    or a locked turnout is refused before any order'."""
    made = it()
    assert made.positions["3"] == PLUS, "the border switch starts out, every lever in +"
    laid = made.part_street(YARD, "V52")
    assert laid.accepted, laid.message
    assert (made.positions["3"], made.positions["4"]) == (MINUS, MINUS)
    assert made.part_street(YARD, "V52").message == "Växelgatan V 52 ligger redan."
    assert made.view().parts[0].streets[1].laid
    assert made.set_route("In", "Stopp").accepted, "the station's route into the yard"
    refused = made.part_street(YARD, "V51")
    assert not refused.accepted
    assert "är låst i vägen In → Stopp" in refused.message, "a locked switch refuses the street"
    assert made.positions["4"] == MINUS, "nothing of it was laid"
    assert made.view().parts[0].refused[0].text == refused.message, "the part sees why"
    assert not made.part_street(YARD, "V53").accepted
    station_switch = made.part_lever(YARD, "1")
    assert not station_switch.accepted and "tillhör stationen" in station_switch.message


def test_a_street_that_goes_out_or_into_the_station_is_refused() -> None:
    """A street lays only the part's own switches and border switches towards its area."""
    model = bangard()
    [part] = model.parts
    wrong = [
        SwitchStreet(id="Ut", name="Ut", track="1", positions={"3": PLUS}),
        SwitchStreet(id="In", name="In", track="1", positions={"3": MINUS, "1": MINUS}),
    ]
    changed = part.model_copy(update={"streets": [*part.streets, *wrong]})
    made = Interlocking(plant_of(model.model_copy(update={"parts": [changed]})))
    out = made.part_street(YARD, "Ut")
    assert not out.accepted and "RANG-12" in out.message
    into = made.part_street(YARD, "In")
    assert not into.accepted and "Växel 1 tillhör stationen" in into.message
    assert made.positions["1"] == PLUS and made.positions["3"] == PLUS, "nothing was laid"


def test_a_border_switch_towards_the_yard_never_out() -> None:
    """Ported: yard-boundaries.test.mjs, 'ranger may only lay the boundary back'; and
    yard-control.test.mjs, 'the ranger lays own turnouts freely, boundaries only back, and never
    TKL's'."""
    made = it()
    assert made.part_lever(YARD, "4").accepted, "its own switch, freely"
    assert made.part_lever(YARD, "4").accepted
    back = made.part_lever(YARD, "3")
    assert back.accepted and made.positions["3"] == MINUS, "towards the yard"
    out = made.part_lever(YARD, "3")
    assert not out.accepted and "RANG-12" in out.message, "never out"
    assert made.positions["3"] == MINUS
    assert made.lay_lever("3").accepted, "the station lays it out"
    assert made.positions["3"] == PLUS
    assert not made.part_route(YARD, "U1", "B").accepted, "a route out over the border"
    assert made.part_route(YARD, "U1", "Stopp51").accepted, "inside, laying 3 towards the yard"
    assert made.positions["3"] == MINUS


def test_rules_where_the_part_owns_the_border_switch() -> None:
    """TKL99: the owner lays it both ways; the station only towards the part."""
    made = it(border={"owner": PartOwner.PART})
    assert made.part_lever(YARD, "3").accepted and made.positions["3"] == MINUS
    assert made.part_lever(YARD, "3").accepted and made.positions["3"] == PLUS
    assert made.lay_lever("3", MINUS).accepted, "towards the part"
    refused = made.lay_lever("3", PLUS)
    assert not refused.accepted and "styrs av Bangården" in refused.message
    assert not made.set_route("In", "Stopp").accepted, "the station's route lays it out"


def test_without_rights_at_the_border_the_part_lays_no_border_switch() -> None:
    made = it(rules=PartRules(lays_towards_part=False))
    refused = made.part_lever(YARD, "3")
    assert not refused.accepted and "läggs av stationen" in refused.message
    assert not made.part_street(YARD, "V51").accepted


def test_the_area_does_not_stop_the_station() -> None:
    """Only the border rules stop the station: its routes go into the part's area."""
    made = it()
    assert made.set_route("In", "Stopp").accepted
    assert made.lay_lever("4").accepted


# --- the five messages (TKL98) -----------------------------------------------------------------


def test_a_request_approved_lays_the_route_and_logs_who() -> None:
    """Ported: yard-control.test.mjs, 'TKL approves: the group is laid and locked, routes over
    it wait, and the ranger lays it back'."""
    made = it()
    made.part_street(YARD, "V51")
    request = made.part_request(YARD, "Ut")
    assert request.accepted, request.message
    [message] = request.messages
    assert message.kind == TklPartMessageKind.REQUEST and message.route_out == "Ut"
    assert request.message == "Bangården begär 51 → V (U1 → Ut)."
    assert made.events[0].by == "Bangården", "RANG-05: with who did it"
    again = made.part_request(YARD, "Ut")
    assert not again.accepted and "redan begärd" in again.message
    reply = made.part_reply(asked(made), True)
    assert reply.accepted, reply.message
    assert reply.messages[0].kind == TklPartMessageKind.REPLY and reply.messages[0].approved
    assert made.events[0].by == STATION_BY
    assert made.events[0].text.startswith("Tågklareraren godkände Bangårdens begäran 51 → V.")
    assert [(r.start, r.end) for r in routes(made)] == [("U1", "B"), ("B", "Ut")]
    assert made.positions["3"] == PLUS and made.positions["1"] == MINUS
    assert not made.set_route("In", "Stopp").accepted, "the station's routes over it wait"
    assert not made.lay_lever("3").accepted
    shown = made.view().parts[0]
    assert shown.requests[0].state == TklPartRequestState.APPROVED
    assert shown.routes_out[0].state == TklPartRequestState.APPROVED
    returned = made.part_return(YARD, shown.requests[0].id)
    assert returned.accepted, returned.message
    assert returned.messages[0].kind == TklPartMessageKind.RETURN
    assert routes(made) == [] and made.view().parts[0].requests == []
    assert made.positions["3"] == MINUS, "the border switch back towards the yard"
    assert made.set_route("In", "Stopp").accepted, "the station has its tracks free"


def test_a_request_refused_and_one_taken_back() -> None:
    """Ported: yard-control.test.mjs, 'TKL denies or withdraws; a route laid while a request
    waits answers it for TKL'."""
    made = it()
    assert made.part_request(YARD, "Ut").accepted
    first = asked(made)
    refused = made.part_reply(first, False)
    assert refused.accepted and refused.messages[0].approved is False
    assert made.view().parts[0].requests == []
    assert made.view().parts[0].refused[0].text == "Tågklareraren nekade Bangårdens begäran V Ut."
    assert not made.part_reply(first, True).accepted, "it is gone"
    assert made.part_request(YARD, "Ut").accepted
    assert made.set_route("In", "Stopp").accepted
    assert made.view().parts[0].requests == [], "the route set since answers it no"
    assert "kan inte läggas" in made.view().parts[0].refused[0].text
    made.release(routes(made)[0].id)
    assert made.part_request(YARD, "Ut").accepted
    taken = made.part_return(YARD, asked(made))
    assert taken.accepted and "tog tillbaka" in taken.message


def test_an_impossible_request_is_refused_at_once_and_nothing_reaches_the_station() -> None:
    """RANG-10. Ported: yard-control.test.mjs, 'a route over the group answers the ranger at
    once; no request reaches TKL'."""
    made = it()
    assert made.set_route("In", "11").accepted, "the station's route over switch 1 +"
    refused = made.part_request(YARD, "Ut")
    assert not refused.accepted
    assert refused.message.startswith("Går inte att begära V Ut:")
    assert refused.messages == (), "nothing goes to the station"
    assert made.view().parts[0].requests == []
    assert made.view().parts[0].routes_out[0].possible is False
    assert made.view().parts[0].routes_out[0].reason


def test_the_one_way_rule() -> None:
    """RANG-09: the part can only return an approved route, never set it itself, and the
    station cannot take it back while it is the part's; nödutlösning still can."""
    made = it()
    assert not made.part_route(YARD, "U1", "B").accepted, "never set by the part"
    made.part_request(YARD, "Ut")
    made.part_reply(asked(made), True)
    first = routes(made)[0]
    refused = made.release(first.id)
    assert not refused.accepted and "envägsregeln" in refused.message
    assert made.part_release(YARD, first.id).accepted, "its own release is a return"
    assert routes(made) == []
    made.part_request(YARD, "Ut")
    made.part_reply(asked(made), True)
    assert made.emergency_release(routes(made)[0].id, True).accepted
    assert [r.request for r in routes(made)] == [routes(made)[0].request]
    assert made.emergency_release(routes(made)[0].id, True).accepted
    assert made.view().parts[0].requests == [], "the request goes with its routes"
    loose = it(rules=PartRules(one_way=False))
    loose.part_request(YARD, "Ut")
    loose.part_reply(asked(loose), True)
    assert loose.release(routes(loose)[0].id).accepted, "without the rule the station may"


def test_the_part_takes_back_only_its_own_routes() -> None:
    """Ported: yard-control.test.mjs, 'the ranger lays shunt routes inside the area and over a
    laid group, takes back only its own, never a main route'."""
    made = it()
    assert made.set_route("In", "11").accepted
    station_route = routes(made)[0]
    refused = made.part_release(YARD, station_route.id)
    assert not refused.accepted and "stationens" in refused.message
    own = made.part_route(YARD, "U1", "Stopp52")
    assert own.accepted
    mine = next(r for r in routes(made) if r.start == "U1")
    assert mine.part == YARD and mine.request is None
    assert made.part_release(YARD, mine.id).accepted


def test_klart_returns_everything_and_grindar_lays_the_border_back() -> None:
    """RANG-04, RANG-12. Ported: yard-boundaries.test.mjs, 'ranger restoration never overrides
    route locks'."""
    made = it()
    assert made.part_gates(YARD).accepted
    assert made.positions["3"] == MINUS
    assert made.part_gates(YARD).message == "Gränsväxlarna ligger redan mot Bangården."
    made.lay_lever("3")
    assert made.set_route("In", "Stopp").accepted
    kept = made.part_gates(YARD)
    assert "står kvar" in kept.message and made.positions["3"] == PLUS, "a locked one stays"
    made.release(routes(made)[0].id)
    made.part_request(YARD, "Ut")
    made.part_reply(asked(made), True)
    done = made.part_done(YARD)
    assert done.accepted, done.message
    assert [m.kind for m in done.messages] == [TklPartMessageKind.RETURN]
    assert routes(made) == [] and made.positions["3"] == MINUS
    assert done.message.startswith("Bangården: klart. V Ut tillbaka.")


def test_ring_and_fika() -> None:
    made = it()
    rang = made.part_ring(YARD)
    assert rang.accepted and rang.messages[0].kind == TklPartMessageKind.RING
    assert made.view().parts[0].rings == NOON
    assert made.part_ring_answer(YARD).accepted
    assert made.view().parts[0].rings is None
    assert made.part_fika(YARD, True).accepted
    assert made.view().parts[0].fika
    refused = made.part_street(YARD, "V51")
    assert not refused.accepted and "har fika" in refused.message
    assert made.part_fika(YARD, False).accepted
    assert made.part_street(YARD, "V51").accepted


def test_the_state_survives_a_restart() -> None:
    """Ported: yard-control.test.mjs, 'a laid group survives restart and connection loss'."""
    made = it()
    made.part_request(YARD, "Ut")
    made.part_reply(asked(made), True)
    made.part_ready(YARD, "3795", track="51", departure="10:42")
    made.part_ring(YARD)
    body = made.view().model_dump_json()
    again = load(made.plant, made.revision, body, now=lambda: NOON)
    assert again.problem is None
    assert again.view().parts == made.view().parts
    assert again.view().ready == made.view().ready
    refused = again.release(again.view().routes[0].id)
    assert not refused.accepted and "envägsregeln" in refused.message
    assert again.part_return(YARD, asked(again)).accepted
    other = bangard(parts=[])
    assert load(plant_of(other), 1, body).problem is not None, "another model: fails closed"


# --- Klart att skicka (TKL108, TKL110, TKL111) ---------------------------------------------------


def snapshot(*calls: station.CallHere, place: str = "pby") -> station.Snapshot:
    return station.Snapshot(
        place=station.Neighbour(place=place, code="Pby", name="Provby"),
        context=station.MeetContext(meet_id="m1", version=1, game_day=1, epoch=0),
        clock=station.Clock(time="10:00", seconds=36000, running=False, speed=1, game_day=1),
        place_revision=1,
        calls=list(calls),
    )


def call(number: str, **more: object) -> station.CallHere:
    return station.CallHere.model_validate(
        {"call": f"c{number}", "train": f"t{number}", "train_number": number, "revision": 1, **more}
    )


def test_the_plans_trains_for_a_part_that_is_its_own_driftplats() -> None:
    """TKL108: one choice per train that departs from the part's driftplats; from its own
    place's snapshot when TKL is approved for it, else the calls coming from it."""
    plant = plant_of(bangard(place="pby-bg"))
    part = plant.parts[YARD]
    here = snapshot(
        call("3811", from_place="pby-bg", arrival="11:15"),
        call("3795", from_place="pby-bg", arrival="10:42"),
        call("41", from_place="vby", arrival="10:00"),
    )
    found = plan_trains(part, plant, here)
    assert [(t.number, t.departure) for t in found.trains] == [("3795", "10:42"), ("3811", "11:15")]
    own = snapshot(
        call("3827", to_place="pby", departure="11:48", planned_track="52"),
        call("3901", to_place="pby", departure="09:00", departure_state="departed"),
        place="pby-bg",
    )
    found = plan_trains(part, plant, here, own)
    assert [(t.number, t.track) for t in found.trains] == [("3827", "52")]
    assert (
        plan_trains(part, plant, None).message == "TKL har ingen plan från Hubben. Skriv tågnumret."
    )


def test_a_part_that_is_not_its_own_driftplats_has_the_trains_on_its_tracks() -> None:
    """TKL110: the station's trains that by the plan stand on a track in the part's area."""
    plant = plant_of(bangard(own_place=False))
    here = snapshot(
        call("3795", planned_track="52", departure="10:42"),
        call("41", planned_track="1", departure="10:00"),
        call("42", track="51", planned_track="Spår 52", departure="09:30"),
    )
    found = plan_trains(plant.parts[YARD], plant, here)
    assert [(t.number, t.track) for t in found.trains] == [("42", "51"), ("3795", "52")]


def test_klart_att_skicka_the_order_a_typed_number_and_skickat() -> None:
    made = it()
    assert made.part_ready(YARD, "3811", track="53", departure="11:15").accepted
    assert made.part_ready(YARD, "9999").accepted, "a typed number, without a time: last"
    assert made.part_ready(YARD, "3795", track="52", departure="10:42").accepted
    said = made.events[0]
    assert said.text == "Bangården: tåg 3795 är klart att skicka från spår 52, avgår 10:42."
    assert said.by == "Bangården"
    assert [r.number for r in made.view().ready] == ["3795", "3811", "9999"]
    assert not made.part_ready(YARD, "3795").accepted, "once"
    assert made.ready_move("9999", 0).accepted
    assert made.part_ready(YARD, "3827", departure="11:48").accepted
    assert [r.number for r in made.view().ready] == ["9999", "3795", "3811", "3827"]
    assert made.view().ready[0].moved, "what the station moved stays"
    assert made.ready_sent("3795").accepted
    assert made.events[0].text == "Tåg 3795 från Bangården är skickat."
    assert [r.number for r in made.view().ready] == ["9999", "3811", "3827"]
    assert not made.ready_sent("3795").accepted


def test_the_deck_marks_a_ready_train_on_the_page_nu() -> None:
    """SD62, TKL111: a train ready to send is marked on its train key on the page Nu, and gets
    no page of its own."""
    from tkl.tests.test_deck_logic import Hands, Station

    model = bangard()
    made = Interlocking(plant_of(model), now=lambda: NOON)
    s = Station(model, made, Hands(made))
    s.snapshot = snapshot(call("3795", planned_track="1", departure="10:42", to_place="vby"))
    deck = s.deck()
    key = next(f for f in s.faces(deck) if f.type == "train" and f.text == "3795")
    assert not key.ready
    made.part_ready(YARD, "3795")
    key = next(f for f in s.faces(deck) if f.type == "train" and f.text == "3795")
    assert key.ready and key.label.endswith(", klart att skicka")
    made.ready_sent("3795")
    key = next(f for f in s.faces(deck) if f.type == "train" and f.text == "3795")
    assert not key.ready


# --- level 3 with the pretend LocoNet (STV-11, STV-17) -------------------------------------------


def test_level_3_the_same_rules_on_the_real_switches() -> None:
    r = Rig(level_3(bangard()))
    r.connect()
    assert r.do(r.it.part_street(YARD, "V52")).accepted  # type: ignore[attr-defined]
    r.run(1.0)
    assert (r.layout.position("3"), r.layout.position("4")) == (MINUS, MINUS)
    out = r.do(r.it.part_lever(YARD, "3"))
    assert not out.accepted  # type: ignore[attr-defined]
    r.run(0.5)
    assert r.layout.position("3") == MINUS, "never out, on the layout either"
    assert r.do(r.it.part_request(YARD, "Ut")).accepted  # type: ignore[attr-defined]
    reply = r.do(r.it.part_reply(asked(r.it), True))
    assert reply.accepted, reply.message  # type: ignore[attr-defined]
    r.run(1.5)
    assert r.layout.position("3") == PLUS and r.layout.position("1") == MINUS
    assert all(not x.waiting for x in r.it.view().routes), "the switches reported"
    assert r.do(r.it.part_return(YARD, asked(r.it))).accepted  # type: ignore[attr-defined]
    r.run(1.0)
    assert r.layout.position("3") == MINUS, "back towards the yard on the layout"


def test_the_view_is_saved_and_read_as_the_contract() -> None:
    made = it()
    made.part_request(YARD, "Ut")
    shown = TklInterlocking.model_validate_json(made.view().model_dump_json())
    assert shown.parts[0].requests[0].said == "V Ut"
    assert set(shown.parts[0].pieces) == {"u", "v", "w", "x", "p", "q", "r", "s"}
    assert shown.parts[0].routes_out[0].state == TklPartRequestState.WAITING
