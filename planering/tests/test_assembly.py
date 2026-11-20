"""CAD:s anläggning på utkastet (CAD-11, CAD-30, K4): the assembly's places matched to the plan,
the sections' lengths through the places between, the questions where the assembly and the plan
differ, the map, and the assembly as the package's attachment for the Pi (CAD-12)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from contracts.meet import (
    Clock,
    MapPoint,
    Meet,
    MeetPackage,
    Place,
    PlaceKind,
    Section,
    SectionPart,
    TrackKind,
)
from contracts.planning import (
    Answer,
    AssemblyLayout,
    AssemblyLink,
    AssemblyPlace,
    AssemblyThrough,
    Certainty,
    ConfirmChange,
    Fact,
    ImportReport,
    ImportResult,
    NewMeet,
    Origin,
    SectionTracksChange,
    Source,
    SourceKind,
)
from planering import assembly
from planering.store import Planning, PlanningError

CAD = "u-cad"


def plan() -> MeetPackage:
    """Aby – Bby with a halt between, Bby – Cby, and Dby that the assembly does not have."""
    meet = Meet(id="provtraffen", name="Provträffen")
    places = [
        Place(id="aby", code="Aby", name="Aby", kind=PlaceKind.MANNED),
        Place(id="hpl", code="Hpl", name="Hållplatsen", kind=PlaceKind.HALT),
        Place(id="bby", code="Bby", name="Bby", kind=PlaceKind.MANNED),
        Place(id="cby", code="Cby", name="Cby", kind=PlaceKind.MANNED),
        Place(id="dby", code="Dby", name="Dby", kind=PlaceKind.SHADOW_YARD),
    ]
    sections = [
        Section(
            id="s1",
            place_a="aby",
            place_b="bby",
            parts=[
                SectionPart(id="p1", from_place="aby", to_place="hpl"),
                SectionPart(id="p2", from_place="hpl", to_place="bby"),
            ],
        ),
        Section(
            id="s2",
            place_a="bby",
            place_b="cby",
            parts=[SectionPart(id="p3", from_place="bby", to_place="cby")],
        ),
        Section(
            id="s3",
            place_a="cby",
            place_b="dby",
            parts=[SectionPart(id="p4", from_place="cby", to_place="dby")],
        ),
    ]
    return MeetPackage(meet=meet, clock=Clock(start_time="06:00"), places=places, sections=sections)


def layout(**changed: object) -> AssemblyLayout:
    """The assembly: Aby and Bby by their stations, a siding with a switch between them that is
    the halt, Cby by its station, and Eby, which the plan does not have."""
    places = [
        AssemblyPlace(
            id="m-1", name="Aby", stations=["Aby"], station_ids=["aby"],
            modules=["M-001 Aby station"], at=MapPoint(x=1000, y=0), switches=1,
        ),
        AssemblyPlace(
            id="m-2", name="M-003 Sidospår", modules=["M-003 Sidospår"],
            at=MapPoint(x=3000, y=0), switches=1,
        ),
        AssemblyPlace(
            id="m-4", name="Bby", stations=["Bby"], station_ids=["bby"],
            modules=["M-004 Bby station"], at=MapPoint(x=5500, y=0), switches=2,
        ),
        AssemblyPlace(
            id="m-6", name="Cby", stations=["CBY"], station_ids=["cby"],
            modules=["M-006 Cby station"], at=MapPoint(x=8400, y=0), switches=1,
        ),
        AssemblyPlace(
            id="m-8", name="Eby", stations=["Eby"], station_ids=["eby"],
            modules=["M-008 Eby station"], at=MapPoint(x=8400, y=2000), switches=1,
        ),
    ]  # fmt: skip
    links = [
        AssemblyLink(id="l1", a="m-1", b="m-2", length=1500, tracks=1, modules=["M-002 Linje"]),
        AssemblyLink(id="l2", a="m-2", b="m-4", length=1000, tracks=1, modules=["M-005 Linje"]),
        AssemblyLink(id="l3", a="m-4", b="m-6", length=1200, tracks=2, modules=["M-007 Linje"]),
        AssemblyLink(id="l4", a="m-6", b="m-8", length=900, tracks=1, modules=["M-009 Linje"]),
    ]
    found = AssemblyLayout(
        source=CAD,
        assembly=UUID("00000000-0000-4000-8000-0000000000aa"),
        name="Provträffens anläggning",
        revision=3,
        scale="H0",
        ratio=87,
        places=places,
        links=links,
        through=[
            AssemblyThrough(place="m-2", a="l1", b="l2", length=600),
            AssemblyThrough(place="m-4", a="l2", b="l3", length=2000),
            AssemblyThrough(place="m-6", a="l3", b="l4", length=800),
        ],
        modules=9,
    )
    return found.model_copy(update=changed)


def cad_source(digest: str = "c") -> Source:
    return Source(
        id=f"u-cad{digest}",
        kind=SourceKind.CAD_ASSEMBLY,
        filename="Provträffens anläggning.json",
        size=10,
        sha256=digest * 64,
        level=2,
        added=datetime(2026, 11, 20, tzinfo=UTC),
    )


def json_source(digest: str = "a") -> Source:
    return Source(
        id=f"u-{digest}",
        kind=SourceKind.PLANNING_JSON,
        filename="plan.json",
        size=3,
        sha256=digest * 64,
        level=4,
        added=datetime(2026, 11, 6, tzinfo=UTC),
    )


def json_result(src: Source) -> ImportResult:
    package = plan()
    origin = [Origin(source=src.id, at="OperationLocations")]
    facts = [
        Fact(ref=f"place:{p.id}", certainty=Certainty.SURE, origins=origin) for p in package.places
    ]
    facts += [
        Fact(ref=f"section:{s.id}", certainty=Certainty.SURE, origins=origin)
        for s in package.sections
    ]
    return ImportResult(package=package, facts=facts, report=ImportReport(source=src.id, level=4))


@pytest.fixture
def planning(tmp_path: Path) -> Planning:
    return Planning(tmp_path / "planering.sqlite3")


def planned(planning: Planning) -> str:
    meet = planning.create(NewMeet(name="Provträffen")).meet.id
    src = json_source()
    planning.add_source(meet, src, b"{}", json_result(src))
    return meet


def test_the_assembly_gives_the_sections_their_lengths_through_the_places_between(
    planning: Planning,
) -> None:
    meet = planned(planning)
    src = cad_source()
    preview = planning.stage_assembly(meet, src, b"assembly as it came", layout())
    assert preview.lengths == 2 and preview.sections.changed == 0
    assert "2 sträckor får sin längd" in preview.report.notes[0]
    draft = planning.apply(meet, src.id)
    lengths = {length.section: length for length in draft.lengths}
    # Aby – Bby: 1 500 to the siding, 600 through it, 1 000 on to Bby. Bby – Cby: 1 200.
    assert lengths["s1"].length == 3100 and lengths["s1"].links == ["l1", "l2"]
    assert lengths["s1"].prototype == pytest.approx(269.7)
    assert (lengths["s2"].length, lengths["s2"].tracks) == (1200, 2)
    assert "s3" not in lengths  # Dby is not in the assembly
    facts = {fact.ref: fact for fact in draft.facts}
    fact = facts["section:s1.length"]
    assert fact.certainty == Certainty.LIKELY and fact.origins[0].source == src.id
    assert "M-002 Linje" in fact.origins[0].at and fact.note is not None
    assert "3\N{NO-BREAK SPACE}100 mm" in fact.note and "270 m i H0" in fact.note
    assert facts["place:bby.modules"].origins[0].at.endswith("M-004 Bby station")
    # Cby by its station's signature in another case, and the halt was asked about.
    assert "place:cby.modules" in facts
    asked = {q.cause: q for q in draft.questions if q.cause in assembly.CAUSES}
    halt = next(q for q in draft.questions if q.id == "cad-plats-m-2")
    assert [a.value for a in halt.alternatives] == ["hpl", "dby", assembly.NONE]
    # Single track in the plan, double in the assembly: a question, and the plan is unchanged.
    tracks = next(q for q in draft.questions if q.id == "cad-spar-s2")
    assert tracks.cause == assembly.CAD_TRACKS and tracks.answer is None
    assert draft.package is not None
    assert {s.id: s.tracks for s in draft.package.sections}["s2"] == TrackKind.SINGLE
    # Eby lies next to Cby in the assembly, but the plan has no section there and no Eby.
    assert asked[assembly.CAD_PLACE].id in {"cad-plats-m-2", "cad-plats-m-8"}
    # The assembly goes with the package, by its checksum (CAD-12).
    [attached] = [a for a in draft.package.attachments if a.id == assembly.ATTACHMENT]
    assert attached.sha256 == src.sha256
    assert planning.file(src.sha256) == ("application/json", b"assembly as it came")


def test_answers_and_confirmations_are_kept_when_the_plan_is_read_again(
    planning: Planning,
) -> None:
    meet = planned(planning)
    src = cad_source()
    planning.stage_assembly(meet, src, b"assembly", layout())
    planning.apply(meet, src.id)
    planning.answer(meet, Answer(question="cad-plats-m-2", value="hpl"))
    planning.answer(meet, Answer(question="cad-spar-s2", value="double"))
    draft = planning.change(meet, ConfirmChange(confirm="section:s1.length"))
    # Now the halt is the siding: Aby – Hpl and Hpl – Bby are the assembly's links.
    assert {f.ref for f in draft.facts if f.ref.endswith(".modules")} >= {"place:hpl.modules"}
    assert draft.package is not None
    assert {s.id: s.tracks for s in draft.package.sections}["s2"] == TrackKind.DOUBLE
    # A new planning file: the assembly, the answers and the confirmation stay.
    again = planning.add_source(meet, json_source("b"), b"{}", json_result(json_source("b")))
    assert again.assembly is not None and again.package is not None
    assert {s.id: s.tracks for s in again.package.sections}["s2"] == TrackKind.DOUBLE
    facts = {f.ref: f for f in again.facts}
    assert facts["section:s1.length"].certainty == Certainty.CONFIRMED
    assert {length.section: length.length for length in again.lengths} == {
        "s1": 3100,
        "s2": 1200,
    }
    # The planner's own choice counts over the answer.
    mine = planning.change(meet, SectionTracksChange(section="s2", tracks=TrackKind.SINGLE))
    assert mine.package is not None
    assert {s.id: s.tracks for s in mine.package.sections}["s2"] == TrackKind.SINGLE
    # Every place on the map is in the assembly once Dby is out: Bana stands where it has them.
    assert "dby" not in mine.package.display.reference_layout


def test_a_section_the_assembly_has_no_tracks_for_is_a_question(planning: Planning) -> None:
    meet = planned(planning)
    src = cad_source()
    cut = layout(links=[link for link in layout().links if link.id != "l3"])
    planning.stage_assembly(meet, src, b"assembly", cut)
    draft = planning.apply(meet, src.id)
    question = next(q for q in draft.questions if q.id == "cad-stracka-s2")
    assert question.cause == assembly.CAD_SECTION and question.refs == ["section:s2"]
    assert [a.value for a in question.alternatives] == [assembly.PLAN]
    assert "s2" not in {length.section for length in draft.lengths}
    assert draft.package is not None and len(draft.package.sections) == 3  # the plan's stays


def test_the_same_assembly_again_changes_nothing_and_a_new_one_takes_its_place(
    planning: Planning,
) -> None:
    meet = planned(planning)
    src = cad_source()
    planning.stage_assembly(meet, src, b"assembly", layout())
    first = planning.apply(meet, src.id)
    preview = planning.stage_assembly(meet, src, b"assembly", layout())
    assert preview.lengths == 0 and "inget ändras" in preview.report.notes[-1]
    assert planning.apply(meet, src.id).revision == first.revision
    newer = cad_source("d")
    planning.stage_assembly(meet, newer, b"newer", layout(revision=4))
    draft = planning.apply(meet, newer.id)
    assert [s.id for s in draft.sources if s.kind == SourceKind.CAD_ASSEMBLY] == [newer.id]
    assert draft.assembly is not None and draft.assembly.revision == 4


def test_every_place_on_the_map_in_the_assembly_draws_bana_where_it_has_them(
    planning: Planning,
) -> None:
    meet = planned(planning)
    src = cad_source()
    planning.stage_assembly(meet, src, b"assembly", layout())
    planning.apply(meet, src.id)
    planning.answer(meet, Answer(question="cad-plats-m-2", value="hpl"))
    draft = planning.answer(meet, Answer(question="cad-plats-m-8", value="dby"))
    assert draft.package is not None
    points = draft.package.display.reference_layout
    assert set(points) == {"aby", "hpl", "bby", "cby", "dby"}
    assert (points["aby"].x, points["cby"].x) == (0, assembly.MAP_SIZE)  # the longer side
    assert points["bby"].x == pytest.approx(assembly.MAP_SIZE * 4500 / 7400, abs=0.01)


def test_the_assembly_needs_a_plan_first(planning: Planning) -> None:
    meet = planning.create(NewMeet(name="Tom")).meet.id
    with pytest.raises(PlanningError, match="först"):
        planning.stage_assembly(meet, cad_source(), b"assembly", layout())
