"""Ställverket at level 3 with LocoNet (#85, STV-11, STV-15, STV-16, STV-17, STV-10), against the
pretend LocoNet through the same bus and link as on the layout.

The made-up Provby: the line from V, the entry signal In, switch 1 with track 1 straight on and
track 2 diverging, the exit signals towards O, and a track circuit for each part. Nothing here
names a station (RS13). The tests marked "Ported" carry an old cda-tkl test's behaviour, with
the old test named.
"""

from __future__ import annotations

from contracts.station_model import Address, FeedbackType, Position, StationModel, SwitchControl
from contracts.tkl import (
    AddressState,
    ObjectKind,
    TklAspect,
    TklFieldMode,
    TklInterlocking,
    TklReportKind,
)
from tkl.loconet.objects import changed
from tkl.loconet.simulator import PretendLoconet
from tkl.stallverk import Interlocking, load, plant_of
from tkl.stallverk import automats as automat
from tkl.stallverk.interlocking import BY_CIRCUITS, KOPPLA_IN
from tkl.studio import fjarr
from tkl.tests.niva3 import Rig, level_3
from tkl.tests.provstation import provby

PLUS, MINUS = Position.PLUS, Position.MINUS


def rig(**more: object) -> Rig:
    made = Rig(level_3(provby()), **more)  # type: ignore[arg-type]
    made.connect()
    return made


def route(r: Rig, start: str, end: str) -> int:
    return next(x.id for x in r.it.view().routes if (x.start, x.end) == (start, end))


def shown(r: Rig, start: str, end: str) -> object:
    return next(x for x in r.it.view().routes if (x.start, x.end) == (start, end))


def test_connecting_orders_every_signal_to_stop_and_knows_nothing_yet() -> None:
    """Ported: engine.mjs's connection(true): every signal is ordered to stop, and nothing the
    layout said before counts."""
    r = rig()
    view = r.it.view()
    assert view.field is not None and view.field.mode == TklFieldMode.LOCONET
    stops = {o.name for o in r.sent if o.kind == ObjectKind.SIGNAL and o.aspect == TklAspect.STOP}
    assert stops == set(r.it.plant.signals)
    assert view.switches["1"].reported is None, "an MGP card says nothing until it is ordered"
    assert view.field.sections["Spår 1"] is False, "the interrogation answered"
    assert not any(o.kind == ObjectKind.SWITCH for o in r.sent), "no switch moves on connecting"


def test_a_route_waits_for_its_switches_feedback_before_the_signal_clears() -> None:
    """Level 3: setting a route sends the switch request and waits for the report; the signal
    shows stop until it comes, and kör is ordered after (STV-11)."""
    r = rig()
    outcome = r.do(r.it.set_route("In", "22"))
    assert outcome.accepted, outcome.message  # type: ignore[attr-defined]
    assert "Väntar på återrapport från växel 1" in outcome.message  # type: ignore[attr-defined]
    set_ = shown(r, "In", "22")
    assert set_.waiting == ["1"] and set_.aspect == TklAspect.STOP  # type: ignore[attr-defined]
    r.run(0.3)
    assert r.layout.position("1") is None, "on its way"
    assert shown(r, "In", "22").aspect == TklAspect.STOP  # type: ignore[attr-defined]
    assert not r.layout.proceed("In")
    r.run(0.5)
    assert r.layout.position("1") == MINUS
    after = shown(r, "In", "22")
    assert after.waiting == [] and after.aspect == TklAspect.PROCEED  # type: ignore[attr-defined]
    assert r.layout.proceed("In"), "kör is ordered once the switch lies right"
    assert r.it.view().switches["1"].reported == MINUS
    assert "växlarna ligger rätt" in r.it.events[0].text


def test_without_feedback_in_time_the_route_is_held_with_the_reason() -> None:
    """Ported: engine.mjs, "Växelåterrapport uteblev eller visar fel läge" after commandTimeoutMs:
    six seconds without the report, and the route stops, keeps its locks, and is set again."""
    model = level_3(provby())
    silent = PretendLoconet.from_model(level_3(provby(), feedback=FeedbackType.NONE))
    r = Rig(model, layout=silent)
    r.connect()
    r.do(r.it.set_route("In", "22"))
    r.run(5.0)
    assert shown(r, "In", "22").held is None  # type: ignore[attr-defined]
    r.run(1.5)
    held = shown(r, "In", "22")
    assert held.held == "ingen återrapport från växel 1 inom 6 sekunder"  # type: ignore[attr-defined]
    assert held.aspect == TklAspect.STOP  # type: ignore[attr-defined]
    assert "Lägg den på nytt eller lös ut den" in r.it.events[0].text
    again = r.do(r.it.set_route("In", "22"))
    assert again.accepted and "Väntar på återrapport" in again.message  # type: ignore[attr-defined]
    assert sum(1 for o in r.sent if o.kind == ObjectKind.SWITCH) == 2, "ordered again"


def test_a_switch_without_feedback_is_taken_at_its_order() -> None:
    r = Rig(level_3(provby(), feedback=FeedbackType.NONE))
    r.connect()
    r.do(r.it.set_route("In", "22"))
    assert shown(r, "In", "22").aspect == TklAspect.PROCEED  # type: ignore[attr-defined]
    r.run(0.1)
    assert r.layout.proceed("In")


def test_a_switch_that_reports_another_position_holds_the_route() -> None:
    """Ported: engine.mjs's turnoutConfirmed: a set route whose switch is laid by hand on the
    layout shows stop, with the reason."""
    r = rig()
    r.do(r.it.set_route("In", "22"))
    r.run(1.0)
    r.layout.lay_by_hand("1", PLUS)
    r.run(0.1)
    held = shown(r, "In", "22")
    assert held.held == "växel 1 rapporterar +, men vägen kräver \N{MINUS SIGN}"  # type: ignore[attr-defined]
    assert not r.layout.proceed("In")


def test_the_train_number_follows_the_track_circuits_and_releases_behind_it() -> None:
    """STV-15: with LocoNet the circuits move the train number; the section behind the train is
    released when its circuit is free (sectional release, after the train)."""
    r = rig()
    assert r.it.put_train("102", exit="V").accepted
    r.do(r.it.set_route("In", "12"))
    r.run(0.5)
    r.layout.put_train("102", ["Infart V"])
    r.run(0.1)
    r.layout.move_train("102", "Vx1")
    r.run(0.1)
    in_route = shown(r, "In", "12")
    assert in_route.at == 0 and in_route.train is not None  # type: ignore[attr-defined]
    assert in_route.aspect == TklAspect.STOP, "the train has passed In"  # type: ignore[attr-defined]
    assert not r.layout.proceed("In")
    number = next(n for n in r.it.view().numbers if n.number == "102")
    assert number.section == "Vx1" and not number.estimated
    assert r.it.step(route(r, "In", "12")).message == BY_CIRCUITS
    r.layout.move_train("102", "Spår 1")
    r.run(0.1)
    ahead = shown(r, "In", "12")
    assert ahead.at == 1, "the front in track 1"  # type: ignore[attr-defined]
    assert [s.released for s in ahead.sections] == [False, False], "the tail over the switch"  # type: ignore[attr-defined]
    r.layout.move_train("102", "Spår 1", length=1)
    r.run(0.1)
    said = [e.text for e in r.it.events]
    assert "Spårledningen Vx1 utlöst efter tåg 102." in said


def test_arrival_is_the_entry_route_released_after_passage() -> None:
    """STV-16: at level 3 the arrival is the entry route released after passage: the train is
    wholly in the last section, and the arrival goes up with its track.

    Ported: simulated-trains.test.mjs, "ett tåg på linjen kör in när signalen visar kör, stannar
    på spåret, tågvägen löses upp vid ankomst": the route released, the track still occupied,
    and no new train route in on it."""
    r = rig()
    r.it.put_train("102", exit="V")
    r.do(r.it.set_route("In", "12"))
    r.run(0.5)
    r.layout.put_train("102", ["Infart V"])
    r.layout.move_train("102", "Vx1")
    r.run(0.1)
    r.layout.move_train("102", "Spår 1")
    r.run(0.1)
    assert len(r.it.view().routes) == 1, "the tail is still over the switch"
    early = r.it.arrive(route(r, "In", "12"))
    assert early.message == "Spårledningen Vx1 är belagd: tåg 102 är inte helt inne."
    r.layout.move_train("102", "Spår 1", length=1)
    r.run(0.1)
    assert r.it.view().routes == []
    arrived = [u for u in r.up if u.kind == TklReportKind.ARRIVED]
    assert [(u.train_number, u.track) for u in arrived] == [("102", "1")]
    assert "är utlöst efter passage" in r.it.events[0].text
    train = r.it.view().trains[0]
    assert (train.number, train.section) == ("102", "Spår 1")
    refused = r.it.set_route("In", "12")
    assert not refused.accepted and "belagd" in refused.message
    assert r.it.arrive(1).message == BY_CIRCUITS


def test_occupancy_never_frees_anything_by_itself() -> None:
    """STV-16: a circuit that flickers under a set route releases nothing, and a train whose
    circuit goes free stays where it is with its route."""
    r = rig()
    r.do(r.it.set_route("In", "12"))
    r.run(0.5)
    r.layout.occupy("Spår 1")
    r.run(0.1)
    r.layout.occupy("Spår 1", False)
    r.run(0.1)
    still = shown(r, "In", "12")
    assert still.at == -1 and [s.released for s in still.sections] == [False, False]  # type: ignore[attr-defined]
    r.it.put_train("102", exit="V")
    r.layout.put_train("102", ["Infart V"])
    r.layout.move_train("102", "Vx1")
    r.run(0.1)
    r.layout.occupy("Vx1", False)
    r.run(0.1)
    inside = shown(r, "In", "12")
    assert inside.at == 0 and [s.released for s in inside.sections] == [False, False]  # type: ignore[attr-defined]
    assert r.it.view().trains[0].section == "Vx1"


def test_a_track_without_a_sensor_gets_its_arrival_with_ankommit() -> None:
    """STV-16, beslut 22 november (#251): where the sections ahead of the train have no sensor
    (Utan givare), the interlocking cannot see the passage. Occupancy still frees nothing by
    itself: the route stays, the events say why, and Ankommit gives the arrival once every
    section behind the train with a sensor is free, as at level 1–2."""
    model = changed(level_3(provby()), ObjectKind.TRACK_CIRCUIT, "Spår 1", address="without")
    r = Rig(model)
    r.connect()
    r.it.put_train("102", exit="V")
    r.do(r.it.set_route("In", "12"))
    r.run(0.5)
    r.layout.occupy("Infart V")
    r.layout.occupy("Vx1")
    r.run(0.1)
    in_12 = route(r, "In", "12")
    early = r.it.arrive(in_12)
    assert not early.accepted
    assert early.message == "Spårledningen Vx1 är belagd: tåg 102 är inte helt inne."
    r.layout.occupy("Infart V", False)
    r.layout.occupy("Vx1", False)
    r.run(0.1)
    assert len(r.it.view().routes) == 1, "occupancy frees nothing by itself"
    assert r.it.view().trains[0].section == "Vx1"
    assert r.it.events[0].text == (
        "Tåg 102 har lämnat spårledningen Vx1, men spårledningen Spår 1 saknar givare: "
        "ställverket kan inte se passagen. Tryck Ankommit när tåget är helt inne."
    )
    assert r.it.release(in_12).message == (
        "Tåg 102 är i vägen In → 12, och ställverket kan inte se passagen. Tryck Ankommit när "
        "tåget är helt inne, eller nödutlös vägen."
    )
    assert r.it.step(in_12).message == BY_CIRCUITS
    arrived = r.do(r.it.arrive(in_12))
    assert arrived.accepted  # type: ignore[attr-defined]
    assert arrived.message == (  # type: ignore[attr-defined]
        "Tåg 102 har kommit fram till spår 1, bekräftat med Ankommit: ställverket kan inte se "
        "passagen. Vägen In → 12 är utlöst."
    )
    up = [u for u in arrived.reports if u.kind == TklReportKind.ARRIVED]  # type: ignore[attr-defined]
    assert [(u.train_number, u.track) for u in up] == [("102", "1")]
    assert r.it.view().routes == []
    assert r.it.view().trains[0].section == "Spår 1"


def brought_in(model: StationModel) -> Rig:
    """The route In → 12 laid from afar for train 102, which is in the switch area."""
    r = Rig(model)
    r.connect()
    r.it.set_remote("Fjärr Västra")
    r.it.put_train("102", exit="V")
    [route] = [
        c.remote
        for c in fjarr.candidates(r.it.plant)
        if (c.remote.start, c.remote.end) == ("In", "12")
    ]
    assert automat.request(r.it, route, "r1", "t102-p").locked
    r.send(r.it.take_orders())
    r.run(0.5)
    r.layout.occupy("Infart V")
    r.layout.occupy("Vx1")
    r.run(0.1)
    return r


def test_hubbens_arrival_releases_the_route_only_where_the_passage_cannot_be_seen() -> None:
    """Beslut 22 november: on a remote-controlled station at level 3, route.state names the
    tracks whose circuits have no sensor. There the arrival in Hubben, by the driver's Framme or
    the controller's Ankommit, releases the route as Ankommit does on the spot, once the train
    is wholly in. With a sensor, the interlocking sees the passage and releases it itself."""
    seen = brought_in(level_3(provby()))
    assert seen.it.unseen_tracks() == []
    assert seen.it.hub_arrival("t102-p", "102") is None, "it waits for the passage"
    seen.layout.occupy("Spår 1")
    seen.layout.occupy("Infart V", False)
    seen.layout.occupy("Vx1", False)
    seen.run(0.2)
    assert seen.it.view().routes == [], "released after the passage, as always"
    assert seen.it.hub_arrival("t102-p", "102") is None

    model = changed(level_3(provby()), ObjectKind.TRACK_CIRCUIT, "Spår 1", address="without")
    blind = brought_in(model)
    assert blind.it.unseen_tracks() == ["1"]
    assert blind.it.hub_arrival("t102-p", "102") is None, "Vx1 is still occupied"
    assert len(blind.it.view().routes) == 1
    blind.layout.occupy("Infart V", False)
    blind.layout.occupy("Vx1", False)
    blind.run(0.1)
    arrived = blind.it.hub_arrival("t102-p", "102")
    assert arrived is not None and arrived.accepted
    assert arrived.message == (
        "Tåg 102 har kommit fram till spår 1 enligt Hubben. Vägen In → 12 är utlöst."
    )
    assert not [u for u in arrived.reports if u.kind == TklReportKind.ARRIVED], "Hubben has it"
    assert blind.it.view().routes == []
    assert blind.it.view().trains[0].section == "Spår 1"
    assert blind.it.hub_departure("t102-p", "102") is None, "the circuits release a route out"


def test_a_sensor_far_along_the_track_gets_its_arrival_with_ankommit() -> None:
    """STV-16, beslut 22 november (#251): a short train leaves the switch area before the
    track's sensor, far along the track, sees it. The interlocking has not seen the passage, and
    never takes it as one by itself: the events say why, and Ankommit gives the arrival. Before
    that, Ankommit is refused while the interlocking can still see the train come in."""
    r = rig()
    r.it.put_train("102", exit="V")
    r.do(r.it.set_route("In", "12"))
    r.run(0.5)
    r.layout.put_train("102", ["Infart V"])
    r.layout.move_train("102", "Vx1")
    r.run(0.1)
    in_12 = route(r, "In", "12")
    assert r.it.arrive(in_12).message == (
        "Tåg 102 är i spårledningen Vx1. Ställverket ser när det kommer fram till "
        "spårledningen Spår 1, och löser ut vägen efter passagen (STV-16)."
    )
    r.layout.remove_train("102")
    r.run(0.1)
    r.layout.put_train("102", ["Spår 1"])
    r.run(0.1)
    still = shown(r, "In", "12")
    assert still.at == 1 and [s.released for s in still.sections] == [False, False]  # type: ignore[attr-defined]
    assert r.it.events[0].text == (
        "Spårledningen Vx1 blev fri innan tåg 102 syntes i spårledningen Spår 1: ställverket kan "
        "inte se passagen. Tryck Ankommit när tåget är helt inne."
    )
    arrived = r.do(r.it.arrive(in_12))
    assert arrived.accepted  # type: ignore[attr-defined]
    up = [u for u in arrived.reports if u.kind == TklReportKind.ARRIVED]  # type: ignore[attr-defined]
    assert [(u.train_number, u.track) for u in up] == [("102", "1")]
    assert r.it.view().routes == []


def test_a_train_leaves_on_the_line_and_the_line_occupancy_goes_up() -> None:
    """STV-10: the occupancy of the line outside an exit goes up as section.occupancy, at level 3
    only; a train that leaves its route's last section for the line has departed."""
    r = rig()
    r.it.put_train("201", section="Spår 1")
    r.layout.put_train("201", ["Spår 1"])
    r.run(0.1)
    r.do(r.it.set_route("12", "Ut2"))
    r.run(1.0)
    assert r.layout.proceed("12")
    r.layout.move_train("201", "Vx2")
    r.run(0.1)
    r.layout.occupy("Vx2", False)
    r.run(0.1)
    assert r.it.view().routes and r.it.view().trains, "a flicker is no departure"
    r.layout.occupy("Vx2")
    r.run(0.1)
    r.layout.move_train("201", "Infart O")
    r.run(0.1)
    occupancy = [u for u in r.up if u.kind == TklReportKind.SECTION_OCCUPANCY]
    assert [(u.exit, u.occupied) for u in occupancy] == [("V", False), ("O", False), ("O", True)]
    assert occupancy[0].occupied is False, "what the interrogation said on connecting goes up"
    r.layout.move_train("201", "Infart O", length=1)
    r.run(0.1)
    departed = [u for u in r.up if u.kind == TklReportKind.DEPARTED]
    assert [(u.train_number, u.exit) for u in departed] == [("201", "O")]
    assert r.it.view().routes == [] and r.it.view().trains == []
    r.layout.remove_train("201")
    r.run(0.1)
    occupancy = [u for u in r.up if u.kind == TklReportKind.SECTION_OCCUPANCY]
    assert [(u.exit, u.occupied) for u in occupancy][-2:] == [("O", True), ("O", False)]


def test_only_green_and_without_objects_run_with_loconet() -> None:
    """STV-17: with LocoNet only green and Utan adress run; a route over a grey or a yellow
    object is refused with the reason, and the panel's state shows each one's state."""
    model = level_3(provby())
    yellow = changed(model, ObjectKind.SWITCH, "1", address=Address(number=1))
    r = Rig(yellow)
    r.connect()
    refused = r.it.set_route("In", "12")
    assert refused.message == (
        f"Växel 1 är gul: adressen är inte bekräftad på banan. Bekräfta den i {KOPPLA_IN} (STV-17)."
    )
    assert not r.it.lay_lever("1").accepted
    grey = changed(model, ObjectKind.SIGNAL, "In", address=None)
    r = Rig(grey)
    r.connect()
    assert "Signalen In är grå: den har ingen adress" in r.it.set_route("In", "12").message
    no_sensor = changed(model, ObjectKind.TRACK_CIRCUIT, "Spår 1", address="without")
    r = Rig(no_sensor)
    r.connect()
    assert r.do(r.it.set_route("In", "12")).accepted, "Utan adress runs"  # type: ignore[attr-defined]
    view = r.it.view()
    assert view.signals["In"].state == AddressState.GREEN
    manual = changed(model, ObjectKind.SWITCH, "2", control=SwitchControl.MANUAL, address=None)
    view = Rig(manual).it.view()
    assert view.switches["2"].state == AddressState.WITHOUT, "Utan adress shows on the panel"
    pretend = Rig(yellow, mode=TklFieldMode.PRETEND)
    pretend.connect()
    assert pretend.it.set_route("In", "12").accepted, "the pretend LocoNet runs yellow too"


def test_without_loconet_level_3_works_with_the_buttons() -> None:
    """Without LocoNet, or in the cloud, the station at level 3 works as at level 1–2."""
    model = level_3(provby())
    it = Interlocking(plant_of(model))
    assert it.view().field is None
    assert it.put_train("102", exit="V").accepted
    assert it.set_route("In", "12").accepted
    assert it.view().routes[0].aspect == TklAspect.PROCEED
    assert it.step(it.view().routes[0].id).accepted
    assert it.view().numbers[0].estimated
    level_2 = Interlocking(plant_of(provby()))
    refused = level_2.field_connect(TklFieldMode.LOCONET)
    assert not refused.accepted and "inte på nivå 3" in refused.message


def test_disconnecting_and_connecting_hold_the_routes_until_they_are_set_again() -> None:
    r = rig()
    r.do(r.it.set_route("In", "12"))
    r.run(0.5)
    assert shown(r, "In", "12").aspect == TklAspect.PROCEED  # type: ignore[attr-defined]
    assert r.it.field_connect(None).accepted
    assert r.it.view().field is None
    held = shown(r, "In", "12")
    assert held.held == "LocoNet kopplades från: lägg vägen på nytt"  # type: ignore[attr-defined]
    r.connect()
    assert shown(r, "In", "12").aspect == TklAspect.STOP  # type: ignore[attr-defined]
    again = r.do(r.it.set_route("In", "12"))
    assert again.accepted  # type: ignore[attr-defined]
    r.run(0.5)
    assert shown(r, "In", "12").aspect == TklAspect.PROCEED  # type: ignore[attr-defined]


def test_the_field_and_the_waiting_route_are_kept_with_the_state() -> None:
    r = rig()
    r.do(r.it.set_route("In", "22"))
    body = r.it.view().model_dump_json()
    back = load(plant_of(r.model), r.it.revision, body)
    assert back.view().field == r.it.view().field
    assert back.view().routes[0].waiting == ["1"]
    assert TklInterlocking.model_validate_json(body).field is not None
