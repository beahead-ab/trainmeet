"""Fjärrområden i planen (PLAN-04, PLAN-33, FR49, TKL87): the plan holds remote areas, a name and
a row of driftplatser that hangs together along the line. A place in an area is planned as
remote-controlled from it, not from another place; it is only the default, and the operating
form during the meet decides. The area goes with the version in the meet package."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.meet import MeetPackage, PlaceKind
from contracts.planning import Changes, NewMeet, PlaceChange, RemoteAreaChange
from planering.store import Planning, PlanningError
from planering.tests.test_planning import MON, SUN, result, source


@pytest.fixture
def planning(tmp_path: Path) -> Planning:
    return Planning(tmp_path / "planering.sqlite3")


def kinds(package: MeetPackage) -> dict[str, tuple[PlaceKind, str | None]]:
    return {p.id: (p.kind, p.remote_area) for p in package.places}


def test_the_plan_holds_remote_areas_and_the_package_carries_them(planning: Planning) -> None:
    meet = planning.create(NewMeet(name="Fjärrträffen", first_date=MON, last_date=SUN)).meet
    src = source()
    planning.add_source(meet.id, src, b"1", result(src))
    draft = planning.change(
        meet.id, RemoteAreaChange(remote_area="vast", name="Västra", places=["asn", "mla", "sjv"])
    )
    assert draft.package is not None
    [area] = draft.package.remote_areas
    assert (area.id, area.name, area.places) == ("vast", "Västra", ["asn", "mla", "sjv"])
    assert kinds(draft.package)["mla"] == (PlaceKind.REMOTE, "vast")
    assert kinds(draft.package)["nby"] == (PlaceKind.MANNED, None)
    fact = next(f for f in draft.facts if f.ref == "remote_area:vast")
    assert fact.origins[0].source == "planner"
    # The version carries it, and the package reads back whole.
    frozen = MeetPackage.model_validate_json(planning.freeze(meet.id).model_dump_json())
    assert [a.id for a in frozen.remote_areas] == ["vast"]
    assert next(p for p in frozen.places if p.id == "sjv").remote_area == "vast"
    # A place taken out is manned again; the area survives a new source and other changes.
    planning.change(meet.id, RemoteAreaChange(remote_area="vast", name="Västra", places=["mla"]))
    planning.change(meet.id, PlaceChange(place="asn", phone="211"))
    again = planning.add_source(meet.id, source(digest="b"), b"2", result(source(digest="b")))
    assert again.package is not None
    assert kinds(again.package)["asn"] == (PlaceKind.MANNED, None)
    assert kinds(again.package)["mla"] == (PlaceKind.REMOTE, "vast")
    # No name takes the area away.
    gone = planning.change(meet.id, RemoteAreaChange(remote_area="vast"))
    assert gone.package is not None and gone.package.remote_areas == []
    assert kinds(gone.package)["mla"] == (PlaceKind.MANNED, None)
    assert not [f for f in gone.facts if f.ref.startswith("remote_area:")]


def test_a_remote_area_hangs_together_and_has_no_halts(planning: Planning) -> None:
    meet = planning.create(NewMeet(name="Fjärrträffen")).meet
    src = source()
    planning.add_source(meet.id, src, b"1", result(src))
    with pytest.raises(PlanningError, match="hänger inte ihop"):
        planning.change(meet.id, RemoteAreaChange(remote_area="a", name="A", places=["nby", "mla"]))
    with pytest.raises(PlanningError, match="hållplats"):
        planning.change(meet.id, RemoteAreaChange(remote_area="a", name="A", places=["lvh"]))
    with pytest.raises(PlanningError, match="finns inte"):
        planning.change(meet.id, RemoteAreaChange(remote_area="a", name="A", places=["x"]))
    planning.change(meet.id, RemoteAreaChange(remote_area="a", name="A", places=["asn", "mla"]))
    with pytest.raises(PlanningError, match="hör redan till fjärrområdet A"):
        planning.change(meet.id, RemoteAreaChange(remote_area="b", name="B", places=["mla", "sjv"]))


def test_the_change_reads_as_part_of_spara() -> None:
    changes = Changes.model_validate(
        {
            "revision": 3,
            "changes": [
                {"remote_area": "vast", "name": "Västra", "places": ["asn", "mla"]},
                {"place": "asn", "phone": "211"},
            ],
        }
    )
    assert isinstance(changes.changes[0], RemoteAreaChange)
    assert isinstance(changes.changes[1], PlaceChange)
