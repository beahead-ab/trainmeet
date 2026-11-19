"""Studio, Dela stationen (#87 del b, TKL99, TKL101, TKL103): what Studio works out for a part
from the track plan, and its checks, on a small made-up station and on the reference station
that has a part. No code here names a station (RS13): the reference station is found by being
the one with a part."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.station_model import (
    BorderSwitch,
    PartOwner,
    PartSide,
    Position,
    RouteOut,
    StationModel,
    StationPart,
    StationTrack,
    SwitchStreet,
)
from contracts.tkl import TklDela, TklDelaRefKind, TklDelaState
from tkl.stallverk.parts import resolve, street_end
from tkl.stallverk.plant import Plant, plant_of
from tkl.studio import dela
from tkl.tests.provstation import bangard, build, switch
from tkl.track_plan import panel_of

PLUS, MINUS = Position.PLUS, Position.MINUS
YARD = ["u", "v", "w", "x", "p", "q", "r", "s"]
MODELS = Path(__file__).resolve().parents[1] / "referens"


def bare() -> StationModel:
    """The made-up station before its owner divided it: no parts."""
    return bangard().model_copy(update={"parts": []})


def new_part(**more: object) -> StationPart:
    """The yard as the owner draws it in Studio, step by step."""
    given: dict[str, object] = {"id": "bangarden", "name": "Bangården", "pieces": YARD}
    given.update(more)
    return StationPart.model_validate(given)


def drawn() -> StationPart:
    """The yard with its area, own switch, border switch, signals and border signal."""
    return new_part(
        switches=["4"],
        signals=["U1", "51", "52", "B"],
        border=[BorderSwitch(switch="3", towards_part=MINUS)],
        border_signals=["B"],
        own_place=True,
        code="Bg",
    )


def shown(model: StationModel, *parts: StationPart) -> TklDela:
    plain = model.model_copy(update={"parts": []})
    return dela.view(plain, plant_of(plain), list(parts), TklDelaState.DRAFT, panel_of(plain))


def texts(found: TklDela, problem: bool = True) -> list[str]:
    return [c.text for c in found.checks if c.problem == problem]


def test_a_part_is_made_on_a_station_without_parts() -> None:
    """A name and an area: the border switch at the edge is the only problem, and it says so."""
    found = shown(bare(), new_part())
    [check] = [c for c in found.checks if c.problem]
    assert check.text.startswith("Bangården: växel 3 står vid gränsen")
    assert (check.part, check.kind, check.id) == ("bangarden", TklDelaRefKind.SWITCH, "3")
    [yard] = found.found
    assert yard.border_switches == [BorderSwitch(switch="3", towards_part=MINUS)], (
        "a switch with a piece inside and a way out, towards the leg that stays inside"
    )
    assert yard.edge == ["B"], "where the area meets the rest of the station"
    assert found.sections["q"] == ["q"], "the area is clicked section by section"


def test_area_border_and_rules() -> None:
    """With the border switch and its owner, the station by default, nothing stops it. The
    rules are on by default (TKL99), and the part's own switch is its own."""
    part = drawn()
    assert part.border[0].owner == PartOwner.STATION
    assert part.rules.lays_towards_part and part.rules.one_way
    found = shown(bare(), part)
    assert texts(found) == []
    [resolved] = resolve(plant_of(bare()), [part]).values()
    assert resolved.may_lay("4", PLUS) and resolved.may_lay("3", MINUS)
    assert not resolved.may_lay("3", PLUS), "never out (RANG-12)"


def test_a_street_comes_from_the_track_graph() -> None:
    """An end and a track: the street is walked from the track to the end of the area, and
    walked again with street_end. The made-up station's two streets are the ones del a wrote."""
    found = shown(bare(), drawn())
    streets = {s.track: s for s in found.found[0].streets}
    assert set(streets) == {"51", "52"}
    assert dict(streets["51"].positions) == {"3": MINUS, "4": PLUS}
    assert dict(streets["52"].positions) == {"3": MINUS, "4": MINUS}
    assert list(streets["51"].positions) == ["3", "4"], "from the end of the area to the track"
    side = streets["51"].side
    assert side is not None
    assert streets["51"].name == f"{'V' if side == PartSide.LEFT else 'H'} 51"
    written = {s.track: dict(s.positions) for s in bangard().parts[0].streets}
    assert {t: dict(s.positions) for t, s in streets.items()} == written


def test_a_route_out_is_one_of_the_stations_routes_that_leaves_the_area() -> None:
    """U1 → Ut, chained through the border signal as the interlocking sets a request; and the
    links that end at the border signal. Nothing that stays inside."""
    found = shown(bare(), drawn())
    outs = {(r.start, r.end): r for r in found.found[0].routes_out}
    assert ("U1", "Ut") in outs and ("B", "Ut") in outs
    assert ("U1", "Stopp51") not in outs, "a route inside the area the part sets itself"
    assert outs[("U1", "Ut")].track == "Ut", "no station track at its end: the signal"
    written = bangard().parts[0].routes_out[0]
    assert (written.start, written.end) in outs


@pytest.mark.parametrize(
    ("change", "said", "kind", "ref"),
    [
        (
            {"streets": [SwitchStreet(id="X", name="X", track="52", positions={"3": MINUS})]},
            "Växelgatan X leder",
            TklDelaRefKind.STREET,
            "X",
        ),
        (
            {
                "streets": [
                    SwitchStreet(
                        id="V51", name="V 51", track="51", positions={"3": MINUS, "4": MINUS}
                    )
                ]
            },
            "Växelgatan V 51 leder till 52, inte till 51.",
            TklDelaRefKind.STREET,
            "V51",
        ),
        (
            {
                "streets": [
                    SwitchStreet(id="S", name="S", track="1", positions={"1": PLUS, "3": PLUS})
                ]
            },
            "Växelgatan S lägger 1, som är stationens.",
            TklDelaRefKind.STREET,
            "S",
        ),
        (
            {
                "streets": [
                    SwitchStreet(id="U", name="U", track="51", positions={"3": PLUS, "4": PLUS})
                ]
            },
            "Växelgatan U lägger gränsväxeln 3 ut från delen.",
            TklDelaRefKind.STREET,
            "U",
        ),
        (
            {"routes_out": [RouteOut(id="I", name="In", track="1", start="In", end="11")]},
            "Vägen ut In börjar vid In, utanför området.",
            TklDelaRefKind.ROUTE_OUT,
            "I",
        ),
        (
            {"routes_out": [RouteOut(id="S", name="51", track="51", start="U1", end="Stopp51")]},
            "Vägen ut 51 lämnar inte området.",
            TklDelaRefKind.ROUTE_OUT,
            "S",
        ),
        ({"border": []}, "Bangården: växel 3 står vid gränsen.", TklDelaRefKind.SWITCH, "3"),
        (
            {"border": [BorderSwitch(switch="3", towards_part=PLUS)]},
            "Bangården: gränsväxeln 3 i läge + leder inte in i området.",
            TklDelaRefKind.SWITCH,
            "3",
        ),
        (
            {"pieces": ["u", "v", "w", "q"]},
            "Bangårdens område hänger inte ihop: det är 2 delar.",
            TklDelaRefKind.PIECE,
            "q",
        ),
        ({"pieces": []}, "Bangården har inget område.", TklDelaRefKind.PART, "bangarden"),
        ({"switches": ["9"]}, "Bangården: växel 9 finns inte.", TklDelaRefKind.SWITCH, "9"),
        (
            {"switches": ["1"]},
            "Bangården: växel 1 står utanför området.",
            TklDelaRefKind.SWITCH,
            "1",
        ),
        (
            {"signals": ["In"]},
            "Bangården: signal In står utanför området.",
            TklDelaRefKind.SIGNAL,
            "In",
        ),
        ({"name": " "}, "Delen bangarden behöver ett namn.", TklDelaRefKind.PART, "bangarden"),
    ],
)
def test_each_check_says_what_and_where(
    change: dict[str, object], said: str, kind: TklDelaRefKind, ref: str
) -> None:
    """Studio's checks, each with what it is about to click (del a did not build them): a
    street leads to its track and lays only the part's own, a route out starts inside the area
    and leaves it, a border switch has an owner, and the area hangs together."""
    found = shown(bare(), drawn().model_copy(update=change))
    [check] = [c for c in found.checks if c.problem and c.text.startswith(said.rstrip("."))]
    assert (check.part, check.kind, check.id) == ("bangarden", kind, ref)


def test_two_parts_never_share_a_piece_or_an_id() -> None:
    other = new_part(id="lokstall", name="Lokstallet", pieces=["q"], code=None)
    found = shown(bare(), drawn(), other)
    assert "Spårbit q hör till både Bangården och Lokstallet. Ett område hör till en del." in (
        texts(found)
    )
    again = shown(bare(), drawn(), drawn())
    assert "Två delar har id bangarden. Varje del behöver ett eget id." in texts(again)


def test_an_own_place_without_a_signature_is_a_note() -> None:
    found = shown(bare(), drawn().model_copy(update={"code": None}))
    assert texts(found) == []
    assert texts(found, problem=False) == [
        "Bangården är egen driftplats men har ingen signatur. Hubben använder namnet."
    ]


# --- the reference station with a part ----------------------------------------------------------


@pytest.fixture(scope="module")
def reference() -> Plant:
    models = [StationModel.model_validate_json(p.read_text("utf-8")) for p in MODELS.iterdir()]
    [found] = [m for m in models if m.parts]
    return plant_of(found)


def test_the_reference_part_passes_studios_checks(reference: Plant) -> None:
    """The part del a wrote opens in Studio with no problem: its border switches are the ones
    at the edge, its streets lead to their tracks and its routes out leave the area."""
    found = dela.view(
        reference.model,
        reference,
        list(reference.model.parts),
        TklDelaState.IN_USE,
        panel_of(reference.model),
    )
    assert texts(found) == [], texts(found)
    [part] = reference.model.parts
    [yard] = found.found
    assert sorted(yard.border_switches, key=lambda b: b.switch) == sorted(
        part.border, key=lambda b: b.switch
    ), "the same switches, owned by the station, towards the part as written"


def test_the_reference_streets_come_out_of_the_track_graph_where_the_end_says_it(
    reference: Plant,
) -> None:
    """From the end and the track, Studio computes seven of the part's thirteen streets as they
    are written: the goods tracks from the left and the right. The others were written from a
    start of their own in old TKL (a loading track's or the depot's), or with a flank switch,
    and stay as written; the checks say they lead to their tracks."""
    [part] = reference.model.parts
    found = dela.view(
        reference.model, reference, [part], TklDelaState.IN_USE, panel_of(reference.model)
    )
    computed = {(s.side, s.track): dict(s.positions) for s in found.found[0].streets}
    same = [s.id for s in part.streets if computed.get((s.side, s.track)) == dict(s.positions)]
    assert len(same) == 7, same
    outs = {(r.start, r.end) for r in found.found[0].routes_out}
    assert {(r.start, r.end) for r in part.routes_out} <= outs


def test_a_street_of_one_switch_leads_where_the_switch_points() -> None:
    """A siding on one switch, as the station Rita's browser test draws: the street lays the
    switch to the siding, and street_end says it leads there, not back along the trunk to the
    line, which passes as many of the street's switches."""
    model = build(
        "a:V-1 b:1-O c:1-E",
        switches=[switch("1", "a", "b", "c")],
        exits={"V": "Västby", "O": "Östby"},
        station_tracks=[StationTrack(id="2", label="Spår 2", pieces=["c"])],
        level=1,
    )
    plant = plant_of(model)
    assert street_end(plant, {"1": MINUS}) == "2"
    siding = new_part(pieces=["c"], border=[BorderSwitch(switch="1", towards_part=MINUS)])
    found = dela.view(model, plant, [siding], TklDelaState.DRAFT, panel_of(model))
    assert [(s.track, dict(s.positions)) for s in found.found[0].streets] == [("2", {"1": MINUS})]
    assert texts(found) == []
