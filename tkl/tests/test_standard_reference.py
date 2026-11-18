"""The reference stations as model files, laid out by the same engine (#83, TKL40, RS12, RS13).

Each station in tkl/referens/ has a fixture in tkl/tests/referens/: the route list of its
reference page in the spec (start, end, kind and switch positions), and the documented cases
where the engine and the page differ, with the reason. Every such case is checked here too: a
chain must be a chain of the engine's routes, and the engine's positions are pinned. Nothing in
the code names a station; the stations are found from the files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from contracts.generate import SCHEMA_DIR, STATION_MODEL, filename
from contracts.station_model import StationModel, to_json
from tkl.standard import RouteKind, chains, derive, problems
from tkl.standard.chains import positions

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "tkl" / "referens"
FIXTURES = Path(__file__).resolve().parent / "referens"
STATIONS = sorted(p.name.removesuffix(".tkl.json") for p in MODELS.glob("*.tkl.json"))


def model(station: str) -> StationModel:
    return StationModel.model_validate_json((MODELS / f"{station}.tkl.json").read_text("utf-8"))


def fixture(station: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{station}.vagar.json").read_text("utf-8"))
    return data


Key = tuple[str, str, str]


def key(item: dict[str, Any]) -> Key:
    return (item["kind"], item["start"], item["end"])


def test_there_are_four_reference_stations_each_with_a_fixture() -> None:
    assert len(STATIONS) == 4
    assert sorted(p.name.removesuffix(".vagar.json") for p in FIXTURES.glob("*.json")) == STATIONS


@pytest.mark.parametrize("station", STATIONS)
def test_the_model_file_round_trips(station: str) -> None:
    text = (MODELS / f"{station}.tkl.json").read_text("utf-8")
    assert to_json(StationModel.model_validate_json(text)) == text


@pytest.mark.parametrize("station", STATIONS)
def test_the_model_file_follows_the_published_schema(station: str) -> None:
    schema = json.loads((SCHEMA_DIR / filename(STATION_MODEL)).read_text("utf-8"))
    data = json.loads((MODELS / f"{station}.tkl.json").read_text("utf-8"))
    assert sorted(Draft202012Validator(schema).iter_errors(data), key=str) == []


@pytest.mark.parametrize("station", STATIONS)
def test_the_fixture_is_the_reference_page_s_route_list(station: str) -> None:
    data = fixture(station)
    routes = data["routes"]
    counted = {kind: sum(1 for r in routes if r["kind"] == kind) for kind in ("train", "shunting")}
    assert counted == data["counts"]
    assert len({key(r) for r in routes}) == len(routes), "one route per kind, start and end"


@pytest.mark.parametrize("station", STATIONS)
def test_the_engine_gives_the_reference_routes(station: str) -> None:
    """The same set as the page, except the cases the fixture documents, each checked."""
    data = fixture(station)
    reference = {key(r): r for r in data["routes"]}
    routes = derive(model(station))
    engine = {(r.kind.value, r.start.name, r.end.name): r for r in routes}
    laid = {k: {p: v.value for p, v in r.positions.items()} for k, r in engine.items()}
    excepted: dict[Key, dict[str, Any]] = {}
    for case in data["exceptions"]:
        assert case["reason"], case
        excepted[key(case)] = case
        k = key(case)
        if case["side"] == "reference":
            assert k in reference and k not in engine, case
            if "chain" in case:
                found = [
                    c
                    for c in chains(routes, RouteKind(case["kind"]), case["start"], case["end"])
                    if [r.end.name for r in c[:-1]] == case["chain"]
                ]
                assert found, f"no chain {case}"
                want = reference[k]["switches"]
                got = {p: v.value for p, v in positions(found[0]).items()}
                stale = set(case.get("stale", []))
                assert {p: v for p, v in want.items() if p not in stale} == {
                    p: v for p, v in got.items() if p not in stale
                }, case
        elif case["side"] == "engine":
            assert k in engine and k not in reference, case
            assert laid[k] == case["switches"], case
        else:
            assert case["side"] == "both", case
            assert k in engine and k in reference, case
            assert reference[k]["switches"] != laid[k], case
            assert laid[k] == case["switches"], case
    for k in reference.keys() & engine.keys():
        if k in excepted:
            continue
        assert laid[k] == reference[k]["switches"], k
        assert engine[k].turntable == reference[k].get("turntable"), k
    unexplained = (reference.keys() ^ engine.keys()) - excepted.keys()
    assert unexplained == set()


@pytest.mark.parametrize("station", STATIONS)
def test_the_reference_station_passes_the_checks_but_for_its_neighbours(station: str) -> None:
    """The pages do not say which station lies beyond most line exits (§6)."""
    station_model = model(station)
    missing = [e.id for e in station_model.line_exits if not e.neighbour]
    assert problems(station_model) == [f"Linjeutfarten {x} saknar grannstation." for x in missing]


def test_no_code_names_a_station() -> None:
    """RS13: the stations are data. The names come from the model files themselves."""
    names: set[str] = set()
    for station in STATIONS:
        names |= {station, model(station).name}
    pattern = re.compile("|".join(re.escape(n) for n in sorted(names)), re.IGNORECASE)
    found = [
        f"{path.relative_to(ROOT)}: {match.group(0)}"
        for folder in ("tkl", "contracts")
        for path in sorted((ROOT / folder).rglob("*"))
        if path.suffix in {".py", ".ts", ".tsx"}
        for match in pattern.finditer(path.read_text("utf-8"))
    ]
    assert found == []
