"""Studio, Inställningar, Stream Deck (#86 del c): the owner's deviations from the default per size
(SD32, SD40), laid on again when the drawing changes and Att kolla when they cannot be; what may
and may not be changed (SD43, SD29); the pedal (SD55); Studio's checks (SD44) on the four
reference stations; Föreslå (SD45); Prova alla knappar against an empty interlocking (SD47); and
the deviations kept with the model and versioned with it like Manöver's settings (SD49).

A made-up station (provby) and the reference stations looped over from their files: nothing here
names a real station (RS13).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts.station_model import StationModel, to_json
from contracts.tkl import (
    DeckAction,
    DeckChange,
    DeckKeyType,
    DeckMode,
    DeckModelId,
    DeckPageKind,
    DeckPageRef,
    DeckProblemKind,
    DeckSuggestion,
    DeckTried,
    RouteKind,
    TklDeckDeviation,
    TklDeckKey,
    TklDeckProfile,
    TklDeckProva,
    TklDeckRoute,
    TklDeckStudio,
    TklDeckView,
    TklStudio,
)
from tkl import track_plan
from tkl.deck import checks, deviations, service, suggest, tryall
from tkl.deck.models import model_of
from tkl.deck.profile import build, geography_of
from tkl.deck.trains import Daily
from tkl.stallverk import plant_of
from tkl.store import LOCAL
from tkl.tests.test_app import API, set_up, tkl
from tkl.tests.test_app_stallverk import S, model, with_model

C = DeckChange
K = DeckKeyType
A = DeckAction
SD = API + "/studio/stream-deck"
FILES = Path(__file__).resolve().parents[2] / "tkl" / "referens"
STATIONS = sorted(p.name.removesuffix(".tkl.json") for p in FILES.glob("*.tkl.json"))
PLACES = DeckPageRef(kind=DeckPageKind.PLACES, name="Platser")
SIGNALS = DeckPageRef(kind=DeckPageKind.SIGNALS, name="Signaler")


def place(name: str) -> TklDeckKey:
    return TklDeckKey(type=K.PLACE, place=name)


def quick(start: str, end: str, kind: RouteKind = RouteKind.TRAIN) -> TklDeckKey:
    return TklDeckKey(type=K.ROUTE, route=TklDeckRoute(start=start, end=end, kind=kind))


def default(given: StationModel | None = None, size: DeckModelId = DeckModelId.FIFTEEN) -> Any:
    found = given or model()
    plant = plant_of(found)
    panel = track_plan.panel_of(found)
    geo = geography_of(plant, panel)
    made = build(plant, panel, model_of(size).grid, size)
    return made, deviations.known_of(plant, geo), plant, geo


def page(profile: TklDeckProfile, name: str) -> list[TklDeckKey | None]:
    return next(p.keys for p in profile.pages if p.name == name)


def without_signal(name: str) -> StationModel:
    """The made-up station drawn again without one of its signals: its routes go too."""
    found = model()
    return found.model_copy(update={"signals": [s for s in found.signals if s.name != name]})


# --- apply and diff -------------------------------------------------------------------------


def test_apply_lays_on_every_kind_of_deviation_and_diff_gives_them_back() -> None:
    """SD40, SD43: a key moved, added, removed and changed; a page added, removed and the
    pages put in another order. The default itself is not changed, and diff gives the
    fewest deviations that make the same profile."""
    made, known, _, _ = default()
    before = made.model_dump_json()
    mine = DeckPageRef(kind=DeckPageKind.OWN, name="Mina")
    given = [
        TklDeckDeviation(change=C.MOVE, page=PLACES, key=place("V"), cell=6),
        TklDeckDeviation(change=C.MOVE, page=PLACES, key=place("1"), cell=2),
        TklDeckDeviation(change=C.ADD, page=PLACES, key=quick("In", "12"), cell=7),
        TklDeckDeviation(change=C.REMOVE, page=PLACES, key=place("O")),
        TklDeckDeviation(
            change=C.KEY,
            page=PLACES,
            key=quick("In", "12"),
            text="In 12",
            under="tåg",
            hold=A.NOTHING,
            number=False,
            dim=False,
            confirm=True,
        ),
        TklDeckDeviation(change=C.ADD_PAGE, page=mine, mode=DeckMode.PLACES),
        TklDeckDeviation(change=C.ADD, page=mine, key=quick("21", "Ut"), cell=0),
        TklDeckDeviation(change=C.ORDER, order=[mine, PLACES]),
        TklDeckDeviation(
            change=C.REMOVE_PAGE, page=DeckPageRef(kind=DeckPageKind.ALL, name="Alla")
        ),
    ]
    applied = deviations.apply(made, given, known)
    assert applied.to_check == [], applied.to_check
    assert made.model_dump_json() == before, "apply is pure"
    profile = applied.profile
    places = page(profile, "Platser")
    assert places[6] == place("V") and places[0] is None
    assert places[2] == place("1") and places[1] == place("2"), "what stood there took its cell"
    assert place("O") not in places
    added = places[7]
    assert added is not None and added.route == quick("In", "12").route
    assert (added.text, added.under, added.hold, added.number, added.dim, added.confirm) == (
        "In 12",
        "tåg",
        A.NOTHING,
        False,
        False,
        True,
    )
    names = [p.name for p in profile.pages if p.mode == DeckMode.PLACES and p.listed]
    assert names[:2] == ["Mina", "Platser"] and "Alla" not in names
    own = next(p for p in profile.pages if p.name == "Mina")
    assert own.kind == DeckPageKind.OWN and own.keys[0] == quick("21", "Ut")
    assert own.keys[14] is not None and own.keys[14].type == K.MODE, "the fixed row comes along"
    fewest = deviations.diff(made, profile)
    assert len(fewest) <= len(given)
    again = deviations.apply(made, fewest, known)
    assert again.to_check == [] and again.profile == profile


def test_the_pedal_has_no_default_and_does_what_the_owner_chose() -> None:
    """SD55: three pedals and nothing on them until the owner chooses."""
    made, known, _, _ = default(size=DeckModelId.PEDAL)
    assert made.pedals == [None, None, None] and made.pages == []
    given = [
        TklDeckDeviation(change=C.PEDAL, pedal=0, key=TklDeckKey(type=K.ACTION, action=A.ARRIVED)),
        TklDeckDeviation(change=C.PEDAL, pedal=2, key=quick("In", "12")),
    ]
    applied = deviations.apply(made, given, known)
    assert applied.to_check == []
    assert applied.profile.pedals == [given[0].key, None, given[1].key]
    assert deviations.diff(made, applied.profile) == given


def test_att_kolla_after_the_drawing_changes() -> None:
    """SD40: the drawing loses a signal and its route; the default is made again and the
    owner's deviations laid on; what cannot be is Att kolla, the rest holds."""
    given = [
        TklDeckDeviation(
            change=C.ADD, page=PLACES, key=quick("D", "22", RouteKind.SHUNTING), cell=5
        ),
        TklDeckDeviation(
            change=C.MOVE, page=SIGNALS, key=TklDeckKey(type=K.SIGNAL, point="D"), cell=4
        ),
        TklDeckDeviation(change=C.MOVE, page=PLACES, key=place("V"), cell=9),
    ]
    made, known, _, _ = default()
    assert deviations.apply(made, given, known).to_check == []
    redrawn, known_now, _, _ = default(without_signal("D"))
    applied = deviations.apply(redrawn, given, known_now)
    assert [c.deviation for c in applied.to_check] == [0, 1]
    assert "D → 22 finns inte" in applied.to_check[0].text
    assert applied.to_check[1].text == "Signalen D finns inte längre på sidan Signaler."
    assert page(applied.profile, "Platser")[9] == place("V"), "the rest is laid on again"
    kept, again = deviations.tidy(redrawn, given, known_now)
    assert len(again.to_check) == 2 and kept[-2:] == given[:2], "kept for the owner to decide"


def test_a_full_page_is_att_kolla() -> None:
    made, known, _, _ = default()
    starts = ["21", "22", "11", "12", "In", "In2", "In"]
    ends = ["Ut", "Ut2", "Ut", "Ut2", "12", "11", "22"]
    given = [
        TklDeckDeviation(change=C.ADD, page=PLACES, key=quick(s, e), cell=4)
        for s, e in zip(starts, ends, strict=True)
    ]
    applied = deviations.apply(made, given, known)
    assert [c.text for c in applied.to_check] == ["Sidan Platser är full."]


# --- SD43: refused with the reason ------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "said"),
    [
        (
            {
                "change": "andra",
                "page": PLACES.model_dump(),
                "key": {"type": "place", "place": "V"},
                "bg": "#ff0000",
            },
            "Färgerna är låsta",
        ),
        (
            {
                "change": "andra",
                "page": PLACES.model_dump(),
                "key": {"type": "place", "place": "V", "symbol": "stjärna"},
            },
            "Symbolerna är låsta",
        ),
        (
            {
                "change": "andra",
                "page": PLACES.model_dump(),
                "key": {"type": "place", "place": "V"},
                "text": "\N{STEAM LOCOMOTIVE}",
            },
            "Symbolerna är låsta",
        ),
        (
            {
                "change": "andra",
                "page": PLACES.model_dump(),
                "key": {"type": "action", "action": "los"},
                "press": "noll",
            },
            "håll in, aldrig med ett tryck",
        ),
        (
            {
                "change": "andra",
                "page": SIGNALS.model_dump(),
                "key": {"type": "signal", "point": "21"},
                "press": "kor",
            },
            "är låst och lika på alla stationer",
        ),
        (
            {
                "change": "andra",
                "page": PLACES.model_dump(),
                "key": {"type": "action", "action": "los"},
                "press": "los-vagen",
            },
            "behöver en snabbväg",
        ),
        (
            {
                "change": "flytta",
                "page": PLACES.model_dump(),
                "key": {"type": "place", "place": "V"},
                "cell": 14,
            },
            "fasta raden",
        ),
        (
            {
                "change": "lagg-till",
                "page": PLACES.model_dump(),
                "key": {"type": "cell", "dx": 0, "dy": 0},
                "cell": 5,
            },
            "följer ritningen",
        ),
    ],
)
def test_a_change_of_colour_symbol_or_gesture_is_refused(
    tmp_path: Path, given: dict[str, Any], said: str
) -> None:
    """SD43, SD3, SD29: refused on the server with the reason, and nothing is kept."""
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    with_model(client)
    for method in (client.post, client.put):
        path = SD + "/utkast" if method == client.post else SD
        answer = method(path, json={"size": "15", "deviations": [given]})
        assert answer.status_code == 422, answer.text
        assert said in " ".join(answer.json()["detail"]["problems"]), answer.json()
    assert TklDeckStudio.model_validate(client.get(SD + "?size=15").json()).deviations == []


def test_the_pedal_refuses_los_ut_alla_noll_and_nodutlosning(tmp_path: Path) -> None:
    """SD55: none of them goes on a pedal, as a press or a hold."""
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    with_model(client)
    for key in (
        {"type": "action", "action": "los-alla"},
        {"type": "action", "action": "noll"},
        {"type": "action", "action": "los", "hold": "nodutlosning"},
        {"type": "signal", "point": "21"},
    ):
        answer = client.put(
            SD, json={"size": "pedal", "deviations": [{"change": "pedal", "pedal": 0, "key": key}]}
        )
        assert answer.status_code == 422, (key, answer.text)
    on_page = {"change": "ta-bort-sida", "page": PLACES.model_dump()}
    answer = client.put(SD, json={"size": "pedal", "deviations": [on_page]})
    assert answer.status_code == 422 and "inga sidor" in answer.text


# --- kept with the model and versioned with it (SD40, SD49) ----------------------------------


def deck(client: TestClient, serial: str, model_id: str) -> TklDeckView:
    answer = client.post(f"{API}/deck/{serial}", json={"model": model_id})
    assert answer.status_code == 200, answer.text
    return TklDeckView.model_validate(answer.json())


def test_kept_per_size_versioned_with_the_model_and_used_by_every_deck(tmp_path: Path) -> None:
    """SD32, SD40, SD49, SD54: saved for the 15 only, with the model, in the next version;
    the deck of that size and the Module 15 get it at once, the XL does not."""
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    with_model(client)
    assert client.post(API + "/studio/version").status_code == 200
    move = {
        "change": "flytta",
        "page": PLACES.model_dump(),
        "key": place("V").model_dump(exclude_none=True),
        "cell": 8,
    }
    draft = client.post(SD + "/utkast", json={"size": "15", "deviations": [move]})
    assert draft.status_code == 200, draft.text
    shown = TklDeckStudio.model_validate(draft.json())
    assert shown.saved is False and len(shown.deviations) == 1
    assert page(shown.profile, "Platser")[8] == place("V")
    assert next(p for p in shown.pages if p.ref == PLACES).changed
    saved = client.put(SD, json={"size": "15", "deviations": [move]})
    assert saved.status_code == 200, saved.text
    kept = TklDeckStudio.model_validate(saved.json())
    assert kept.saved and kept.deviations == shown.deviations
    sizes = {s.size: s for s in kept.sizes}
    assert sizes[DeckModelId.FIFTEEN].deviations == 1 and sizes[DeckModelId.XL].deviations == 0
    xl = TklDeckStudio.model_validate(client.get(SD + "?size=xl").json())
    assert xl.deviations == []
    studio = TklStudio.model_validate(client.get(API + "/studio").json())
    assert studio.changed, "the deviations count as a change since the latest version"
    assert client.post(API + "/studio/version").status_code == 200
    store = client.app.state.store  # type: ignore[attr-defined]
    number = TklStudio.model_validate(client.get(API + "/studio").json()).versions[0].number
    versioned = store.deck_deviations_of_version(LOCAL, number)
    assert versioned is not None and len(versioned.sizes[DeckModelId.FIFTEEN]) == 1
    assert store.deck_deviations_of_version(LOCAL, number - 1) is None
    # Every deck of the size uses the owner's profile (SD40); the Module 15 too (SD54).
    for serial, model_id in (("skarm-1", "15"), ("modul", "module-15")):
        view = deck(client, serial, model_id)
        assert view.mode == DeckMode.PLACES
        assert view.keys[8].label == "Plats V" and view.keys[0].type == "empty"
    assert deck(client, "stor", "xl").keys[0].label == "Plats V"
    # Återställ the whole size: nothing kept, the default again.
    assert client.put(SD, json={"size": "15", "deviations": []}).status_code == 200
    assert deck(client, "skarm-1", "15").keys[0].label == "Plats V"
    assert client.app.state.store.deck_deviations(LOCAL).sizes == {}  # type: ignore[attr-defined]


def test_the_model_drawn_again_keeps_the_deviations_and_says_att_kolla(tmp_path: Path) -> None:
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    with_model(client)
    add = {
        "change": "lagg-till",
        "page": PLACES.model_dump(),
        "key": quick("D", "22", RouteKind.SHUNTING).model_dump(mode="json", exclude_none=True),
        "cell": 5,
    }
    assert client.put(SD, json={"size": "15", "deviations": [add]}).status_code == 200
    answer = client.put(API + "/studio/model", content=to_json(without_signal("D")))
    assert answer.status_code == 200, answer.text
    shown = TklDeckStudio.model_validate(client.get(SD + "?size=15").json())
    assert len(shown.deviations) == 1, "kept until the owner decides"
    [check] = shown.to_check
    assert check.deviation == 0 and "finns inte" in check.text
    assert {s.size: s.to_check for s in shown.sizes}[DeckModelId.FIFTEEN] == 1
    assert client.put(SD, json={"size": "mini", "deviations": []}).status_code == 200
    mini_pages = TklDeckStudio.model_validate(client.get(SD + "?size=mini").json()).profile.pages
    gone = [
        {"change": "ta-bort-sida", "page": {"kind": p.kind.value, "name": p.name}}
        for p in mini_pages
        if p.kind in (DeckPageKind.SIGNALS, DeckPageKind.ALL)
    ]
    assert client.put(SD, json={"size": "mini", "deviations": gone}).status_code == 200
    sizes = {s.size: s for s in TklDeckStudio.model_validate(client.get(SD).json()).sizes}
    assert sizes[DeckModelId.MINI].problems > 0, "the checks for every size the station uses"
    assert sizes[DeckModelId.XL].problems == 0


# --- SD44: Studio's checks ------------------------------------------------------------------


@pytest.mark.parametrize("name", STATIONS)
def test_the_checks_on_the_reference_stations(name: str) -> None:
    """SD44: the default reaches every route for every size; without its signal pages a small
    deck does not, and a key that points at nothing is a problem with its page and cell."""
    found = StationModel.model_validate_json((FILES / f"{name}.tkl.json").read_text("utf-8"))
    for size in (DeckModelId.MINI, DeckModelId.FIFTEEN, DeckModelId.XL, DeckModelId.PLUS_XL):
        made, known, plant, geo = default(found, size)
        result = checks.check(made, plant, geo, known)
        assert result.problems == [], (size, result.problems[:3])
        assert result.reached == result.routes == len(checks.routes_of(plant)) > 0
    made, known, plant, geo = default(found, DeckModelId.MINI)
    gone = [
        TklDeckDeviation(change=C.REMOVE_PAGE, page=deviations.ref_of(p))
        for p in made.pages
        if p.kind in (DeckPageKind.SIGNALS, DeckPageKind.ALL)
    ]
    profile = deviations.apply(made, gone, known).profile
    result = checks.check(profile, plant, geo, known)
    unreached = [p for p in result.problems if p.kind == DeckProblemKind.UNREACHED]
    assert unreached and all(p.route is not None for p in unreached)
    assert result.reached == result.routes - len(unreached)
    shunting = [r for r in checks.routes_of(plant) if r.kind == RouteKind.SHUNTING]
    assert len(unreached) >= len(shunting), "shunting routes start at signals, not places"
    # A key that points at something that does not exist, as one made by hand would.
    first = profile.pages[0]
    keys = list(first.keys)
    keys[0] = TklDeckKey(type=K.SIGNAL, point="finns-inte")
    broken = profile.model_copy(
        update={"pages": [first.model_copy(update={"keys": keys}), *profile.pages[1:]]}
    )
    missing = [
        p
        for p in checks.check(broken, plant, geo, known).problems
        if p.kind == DeckProblemKind.MISSING
    ]
    assert [(p.page, p.cell) for p in missing] == [(0, 0)]


def test_the_studio_page_lists_knappar_and_where_they_are(tmp_path: Path) -> None:
    """SD41: Knappar from the station model by group, each with where it is on the deck."""
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    with_model(client)
    shown = TklDeckStudio.model_validate(client.get(SD + "?size=15").json())
    groups = {b.group.value for b in shown.buttons}
    assert groups >= {"trafiken", "tagvagar", "vaxlingsvagar", "platser", "signaler", "funktioner"}
    route = next(b for b in shown.buttons if b.text == "In → 12")
    assert route.key.type == K.ROUTE and route.pieces and not route.missing
    assert route.where.startswith("start och mål") or route.where.startswith("platser")
    assert next(b for b in shown.buttons if b.text == "V").where == "Platser"
    assert next(b for b in shown.buttons if b.text == "Läge").where == "fast rad"
    assert shown.checks.routes == shown.checks.reached > 0
    assert len(shown.pages) == len(shown.profile.pages)
    assert all(len(p.faces) == 15 for p in shown.pages)
    nu = next(p for p in shown.pages if p.ref.name == "Nu")
    assert nu.faces[0].text == "Tågknapp" and nu.faces[0].under == "1", "a placeholder in Studio"


# --- SD45: Föreslå --------------------------------------------------------------------------


def test_foresla_geographically_by_dagens_vagar_and_by_mest_anvanda(tmp_path: Path) -> None:
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    with_model(client)
    moved = {
        "change": "flytta",
        "page": PLACES.model_dump(),
        "key": place("V").model_dump(exclude_none=True),
        "cell": 8,
    }
    other = {
        "change": "flytta",
        "page": SIGNALS.model_dump(),
        "key": {"type": "signal", "point": "21"},
        "cell": 9,
    }

    def suggested(rule: DeckSuggestion, given: list[dict[str, Any]]) -> Any:
        return client.post(
            SD + "/foresla",
            json={"size": "15", "deviations": given, "page": PLACES.model_dump(), "rule": rule},
        )

    geo = TklDeckStudio.model_validate(suggested(DeckSuggestion.GEOGRAPHIC, [moved, other]).json())
    assert page(geo.profile, "Platser")[0] == place("V"), "the default's layout again"
    assert page(geo.profile, "Signaler")[9] == TklDeckKey(type=K.SIGNAL, point="21")
    nothing = suggested(DeckSuggestion.MOST_USED, [])
    assert nothing.status_code == 409 and "räknade" in nothing.json()["detail"]
    assert suggested(DeckSuggestion.DAILY, []).status_code == 409
    for start, end, times in (("In", "12", 3), ("21", "Ut", 1)):
        for _ in range(times):
            laid = client.post(S + "/route", json={"start": start, "end": end})
            assert laid.json()["accepted"], laid.text
            route = laid.json()["state"]["routes"][0]["id"]
            client.post(S + "/release", json={"route": route})
    most = TklDeckStudio.model_validate(suggested(DeckSuggestion.MOST_USED, []).json())
    keys = page(most.profile, "Platser")
    assert [k.route.start if k and k.route else None for k in keys[:3]] == ["In", "21", None]
    assert keys[14] is not None and keys[14].type == K.MODE, "Läge stays"
    store = client.app.state.store  # type: ignore[attr-defined]

    def daily(data: dict[str, object]) -> dict[str, object]:
        return {**data, service.DAILY: {"for": "x", "routes": [["V", "1", "102", "10:00", True]]}}

    store.change_deck_drift(LOCAL, daily)
    today = TklDeckStudio.model_validate(suggested(DeckSuggestion.DAILY, []).json())
    first = page(today.profile, "Platser")[0]
    assert first is not None and first.type == K.ROUTE and first.under == "102"
    assert first.text == "V→1"


def test_daily_routes_are_snabbvagar_between_the_places() -> None:
    """SD23, SD45: Dagens vägar as snabbvägar, between the places, named after them."""
    _, known, plant, geo = default()
    keys = suggest.daily_routes([Daily("V", "1", "7", "10:00", True)], plant, geo)
    assert len(keys) == 1 and keys[0].text == "V→1" and keys[0].under == "7"
    assert all(k.route is not None and known.route(k.route) for k in keys)


# --- SD47: Prova alla knappar ---------------------------------------------------------------


def test_prova_alla_knappar_against_an_empty_interlocking(tmp_path: Path) -> None:
    """Every key of every page pressed on a copy: the live interlocking keeps its route."""
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    with_model(client)
    laid = client.post(S + "/route", json={"start": "In", "end": "12"})
    assert laid.json()["accepted"], laid.text
    add = {
        "change": "lagg-till",
        "page": PLACES.model_dump(),
        "key": quick("21", "Ut").model_dump(mode="json", exclude_none=True),
        "cell": 5,
    }
    assert client.put(SD, json={"size": "15", "deviations": [add]}).status_code == 200
    started = client.post(SD + "/prova/start", json={"size": "15"})
    assert started.status_code == 200, started.text
    for _ in range(100):
        shown = TklDeckProva.model_validate(client.get(SD + "/prova?size=15").json())
        if not shown.running:
            break
        time.sleep(0.05)
    assert not shown.running and shown.done == shown.total > 0
    assert shown.did + shown.refused + shown.nothing == shown.total
    snabb = next(k for k in shown.keys if k.label.startswith("21→Ut"))
    assert snabb.result == DeckTried.DID, snabb
    release = next(k for k in shown.keys if k.label == "Lös ut")
    assert release.result == DeckTried.NOTHING and "Inga vägar" in release.said
    start = next(k for k in shown.keys if k.label == "Signal In")
    assert start.result == DeckTried.DID and "Valde start In" in start.said
    routes = client.get(S).json()["routes"]
    assert [(r["start"], r["end"]) for r in routes] == [("In", "12")], "the live one untouched"
    assert TklDeckProva.model_validate(client.get(SD + "/prova?size=xl").json()).total == 0


def test_a_key_that_asks_once_more_and_holds_that_are_holds() -> None:
    """SD43, SD29: Fråga en gång till before the press; Lös ut alla and Noll are held."""
    made, known, plant, geo = default()
    given = [
        TklDeckDeviation(change=C.ADD, page=PLACES, key=quick("In", "12"), cell=5),
        TklDeckDeviation(change=C.KEY, page=PLACES, key=quick("In", "12"), confirm=True),
        TklDeckDeviation(
            change=C.ADD, page=PLACES, key=TklDeckKey(type=K.ACTION, action=A.RELEASE_ALL), cell=6
        ),
        TklDeckDeviation(
            change=C.ADD, page=PLACES, key=TklDeckKey(type=K.ACTION, action=A.RESET), cell=7
        ),
    ]
    applied = deviations.apply(made, given, known)
    assert applied.to_check == []
    profile = applied.profile
    at = next(i for i, p in enumerate(profile.pages) if p.name == "Platser")
    tried = {
        cell: tryall.try_key(profile, pressed, plant, geo)
        for pressed in tryall.keys_of(profile)
        if pressed.page == at
        for cell in [pressed.cell]
    }
    assert tried[5].result == DeckTried.DID, "pressed twice: the second press does it"
    assert tried[6].result == DeckTried.NOTHING and "Inga vägar" in tried[6].said
    assert tried[7].result == DeckTried.DID, tried[7]


# --- Studio, Deck (SD46, SD35, SD36): one deck's settings on this computer -------------------


def test_a_decks_settings_blinka_and_glom_deck(tmp_path: Path) -> None:
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    with_model(client)
    deck(client, "skarm-1", "15")
    changed = client.put(
        f"{API}/deck/skarm-1",
        json={"name": "Stationen", "opens_on": "Alla", "workplace": "2", "lock_key": False},
    )
    assert changed.status_code == 200, changed.text
    settings = changed.json()["settings"]
    assert (settings["name"], settings["opens_on"], settings["workplace"]) == (
        "Stationen",
        "Alla",
        "2",
    )
    view = TklDeckView.model_validate(client.get(f"{API}/deck/skarm-1").json())
    assert view.page == "Alla", "the deck opens on its start page (SD35)"
    assert client.put(f"{API}/deck/skarm-1", json={"brightness": 101}).status_code == 422
    nulls = {"name": None, "brightness": 40, "hold": None, "sleep": None, "lock_key": None}
    kept = client.put(f"{API}/deck/skarm-1", json=nulls).json()["settings"]
    assert (kept["name"], kept["brightness"], kept["lock_key"]) == ("Stationen", 40, False)
    cleared = client.put(f"{API}/deck/skarm-1", json={"name": "", "opens_on": ""}).json()
    assert cleared["settings"]["name"] is None and cleared["settings"]["opens_on"] is None
    client.put(f"{API}/deck/skarm-1", json={"name": "Stationen", "opens_on": "Alla"})
    assert client.put(f"{API}/deck/nej", json={"brightness": 50}).status_code == 404
    listed = client.get(API + "/decks").json()["decks"]
    assert listed[0]["settings"]["name"] == "Stationen" and listed[0]["tried"] is False
    blinked = client.post(f"{API}/deck/skarm-1/blinka")
    assert blinked.status_code == 200 and blinked.json()["blinking"]
    view = TklDeckView.model_validate(client.get(f"{API}/deck/skarm-1").json())
    assert {f.type for f in view.keys} == {"here"} and view.keys[0].under == "Stationen"
    assert view.refresh_ms < 4000, "read again when the blink is over"
    assert client.delete(f"{API}/deck/skarm-1").status_code == 204
    assert client.get(API + "/decks").json()["decks"] == []
    assert client.delete(f"{API}/deck/skarm-1").status_code == 404


def test_a_pedal_does_nothing_until_chosen_then_what_was_chosen(tmp_path: Path) -> None:
    """SD55 through the deck's API: nothing on a pedal, then a snabbväg on the middle one."""
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    with_model(client)
    opened = deck(client, "pedal-1", "pedal")
    assert opened.keys == []
    pressed = client.post(f"{API}/deck/pedal-1/press", json={"key": 1})
    assert "gör ingenting förrän" in (pressed.json()["message"] or "")
    assert client.get(S).json()["routes"] == []
    chosen = {
        "change": "pedal",
        "pedal": 1,
        "key": quick("In", "12").model_dump(mode="json", exclude_none=True),
    }
    assert client.put(SD, json={"size": "pedal", "deviations": [chosen]}).status_code == 200
    client.post(f"{API}/deck/pedal-1/press", json={"key": 1})
    assert [(r["start"], r["end"]) for r in client.get(S).json()["routes"]] == [("In", "12")]
    held = client.post(f"{API}/deck/pedal-1/press", json={"key": 1, "hold": True})
    assert held.status_code == 200
    assert len(client.get(S).json()["routes"]) == 1, "a hold does only what was chosen for it"


def test_the_fixed_row_stays_the_same_on_every_page() -> None:
    """SD27: a key of the fixed row is not changed on one page."""
    made, known, _, _ = default()
    mode = TklDeckKey(type=K.MODE)
    applied = deviations.apply(
        made, [TklDeckDeviation(change=C.KEY, page=PLACES, key=mode, text="Byt")], known
    )
    assert [c.text for c in applied.to_check] == [
        "Den fasta raden är densamma på alla sidor och ändras inte här (SD27)."
    ]
    assert page(applied.profile, "Platser")[14] == mode
