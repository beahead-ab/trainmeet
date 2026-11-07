"""Planering: meets, a source into the draft, the planner's changes, the check and versions.

An import comes in as a contracts.planning.ImportResult; here it is built from Provbanan's
example package, so the part is tested without Integrationer (the boundaries).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from contracts.meet import ClearanceMode, MeetPackage, PlaceKind
from contracts.planning import (
    Alternative,
    Answer,
    Certainty,
    Draft,
    Fact,
    ImportReport,
    ImportResult,
    NewMeet,
    Origin,
    PlaceChange,
    Question,
    Rulebook,
    SectionChange,
    Source,
    SourceKind,
    TrainTypeRule,
)
from planering.check import check
from planering.store import Planning, PlanningError, UnknownMeet, UnknownVersion, slug

EXAMPLE = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "provbanan.meet.json"


def package() -> MeetPackage:
    return MeetPackage.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))


def source(name: str = "plan.json", digest: str = "a") -> Source:
    return Source(
        id=f"u-{digest}",
        kind=SourceKind.PLANNING_JSON,
        filename=name,
        size=3,
        sha256=digest * 64,
        level=4,
        added=datetime(2026, 11, 6, tzinfo=UTC),
    )


def result(src: Source) -> ImportResult:
    plan = package()
    origin = [Origin(source=src.id, at="OperationLocations Id 1")]
    return ImportResult(
        package=plan,
        facts=[
            Fact(ref=f"place:{p.id}", certainty=Certainty.SURE, origins=origin) for p in plan.places
        ],
        rulebook=Rulebook(
            train_types=[
                TrainTypeRule(
                    code="Pt", content="passengers", certainty=Certainty.SURE, origins=origin
                ),
                TrainTypeRule(code="Zq", certainty=Certainty.UNSURE, origins=origin),
            ]
        ),
        questions=[
            Question(
                id="train-type-zq",
                cause="train_type",
                message="Vad kör tågslaget Zq?",
                refs=["train_type:Zq"],
                alternatives=[Alternative(value="goods", label="Gods")],
            )
        ],
        report=ImportReport(source=src.id, level=4, trains=len(plan.trains)),
    )


@pytest.fixture
def planning(tmp_path: Path) -> Planning:
    return Planning(tmp_path / "planering.sqlite3")


def test_a_new_meet_gets_an_id_from_its_name(planning: Planning) -> None:
    first = planning.create(NewMeet(name="Värnamo Moduldagar", first_date=date(2026, 10, 30)))
    again = planning.create(NewMeet(name="Värnamo moduldagar"))
    assert (first.meet.id, again.meet.id) == ("varnamo-moduldagar", "varnamo-moduldagar-2")
    assert planning.create(NewMeet(name="Provbanan")).meet.id == "provbanan-2"
    assert slug("Ørmen & Æbelø") == "ormen-aebelo"
    [_provbanan, newest, oldest] = planning.meets()
    assert (newest.meet.id, newest.level, newest.versions) == ("varnamo-moduldagar-2", None, [])
    assert oldest.meet.first_date == date(2026, 10, 30)


def test_the_last_day_cannot_come_before_the_first(planning: Planning) -> None:
    with pytest.raises(PlanningError, match="före"):
        planning.create(NewMeet(name="X", first_date=date(2026, 5, 2), last_date=date(2026, 5, 1)))


def test_a_source_becomes_the_draft_and_the_meet_keeps_its_name(planning: Planning) -> None:
    meet = planning.create(NewMeet(name="Grimslöv", country="dk")).meet
    src = source()
    draft = planning.add_source(meet.id, src, b"abc", result(src))
    assert draft.package is not None
    assert (draft.package.meet.id, draft.package.meet.name, draft.package.meet.country) == (
        meet.id,
        "Grimslöv",
        "dk",
    )
    assert len(draft.package.trains) == 10 and draft.report is not None
    assert planning.source_file(meet.id, src.id) == (src, b"abc")
    [summary] = planning.meets()
    assert (summary.level, summary.places, summary.trains, summary.questions) == (4, 5, 10, 1)


def test_a_new_planning_file_takes_the_place_of_the_old(planning: Planning) -> None:
    meet = planning.create(NewMeet(name="Grimslöv")).meet
    first, second = source(digest="a"), source("ny.json", digest="b")
    planning.add_source(meet.id, first, b"1", result(first))
    draft = planning.add_source(meet.id, second, b"2", result(second))
    assert [s.filename for s in draft.sources] == ["ny.json"]
    with pytest.raises(UnknownMeet):
        planning.source_file(meet.id, first.id)


def test_the_planners_changes_carry_their_origin_and_survive_a_new_file(planning: Planning) -> None:
    meet = planning.create(NewMeet(name="Grimslöv")).meet
    src = source()
    planning.add_source(meet.id, src, b"1", result(src))
    planning.change(meet.id, PlaceChange(place="asn", phone="211"))
    planning.change(meet.id, PlaceChange(place="asn", phone="212"))
    draft = planning.change(
        meet.id, SectionChange(section="s-asn-mla", clearance_mode=ClearanceMode.DIRECT)
    )
    assert len(draft.changes) == 2, "the last change per place counts"
    again = planning.add_source(meet.id, source(digest="b"), b"2", result(source(digest="b")))
    assert again.package is not None
    assert next(p.phone for p in again.package.places if p.id == "asn") == "212"
    section = next(s for s in again.package.sections if s.id == "s-asn-mla")
    assert section.clearance_mode == ClearanceMode.DIRECT
    fact = next(f for f in again.facts if f.ref == "place:asn.phone")
    assert (fact.certainty, fact.origins[0].source) == (Certainty.CONFIRMED, "planner")


def test_a_change_needs_a_draft_and_a_known_place(planning: Planning) -> None:
    meet = planning.create(NewMeet(name="Grimslöv")).meet
    with pytest.raises(PlanningError, match="underlag"):
        planning.change(meet.id, PlaceChange(place="asn", phone="1"))
    src = source()
    planning.add_source(meet.id, src, b"1", result(src))
    with pytest.raises(PlanningError, match="finns inte"):
        planning.change(meet.id, PlaceChange(place="nowhere", phone="1"))
    with pytest.raises(UnknownMeet):
        planning.draft("nowhere")


def test_an_answer_becomes_the_rule(planning: Planning) -> None:
    meet = planning.create(NewMeet(name="Grimslöv")).meet
    src = source()
    planning.add_source(meet.id, src, b"1", result(src))
    with pytest.raises(PlanningError, match="alternativen"):
        planning.answer(meet.id, Answer(question="train-type-zq", value="passengers"))
    draft = planning.answer(meet.id, Answer(question="train-type-zq", value="goods"))
    rule = next(r for r in draft.rulebook.train_types if r.code == "Zq")
    assert (rule.content, rule.certainty, rule.origins[-1].source) == (
        "goods",
        Certainty.CONFIRMED,
        "planner",
    )
    again = planning.add_source(meet.id, source(digest="b"), b"2", result(source(digest="b")))
    assert again.questions[0].answer == "goods", "the answer stays when the file is read again"
    assert planning.meets()[0].questions == 0


def test_publishing_freezes_the_draft_as_numbered_versions(planning: Planning) -> None:
    meet = planning.create(NewMeet(name="Grimslöv")).meet
    with pytest.raises(PlanningError, match="underlag"):
        planning.publish(meet.id)
    src = source()
    planning.add_source(meet.id, src, b"1", result(src))
    first = planning.publish(meet.id)
    with pytest.raises(PlanningError, match="samma som version 1"):
        planning.publish(meet.id)
    planning.change(meet.id, PlaceChange(place="nby", phone="999"))
    second = planning.publish(meet.id)
    assert (first.number, second.number) == (1, 2)
    old, new = planning.package(meet.id, 1), planning.package(meet.id, 2)
    assert (old.meet.id, old.meet.name) == (meet.id, "Grimslöv")
    assert next(p.phone for p in old.places if p.id == "nby") == "101"
    assert next(p.phone for p in new.places if p.id == "nby") == "999"
    assert [v.number for v in planning.versions(meet.id)] == [1, 2]
    assert [f.code for f in old.findings] == ["unanswered_questions"]
    with pytest.raises(UnknownVersion):
        planning.package(meet.id, 3)


def test_the_check_finds_trains_without_a_section_and_shared_tracks() -> None:
    plan = package()
    # Without the last section, every train there is noted once for the pair of places.
    without = plan.model_copy(
        update={"sections": [s for s in plan.sections if s.id != "s-mla-sjv"]}
    )
    draft = Draft(meet=plan.meet, package=without)
    [finding] = check(draft)
    assert finding.code == "no_section" and finding.severity == "observation"
    names = {p.id: p.name for p in plan.places}
    assert finding.message.startswith(f"10 tåg går {names['mla']}–{names['sjv']} utan klarering")
    # Two trains on one track at once is a conflict.
    trains = list(plan.trains)
    first = trains[0]
    twin = first.model_copy(
        update={
            "id": "t901",
            "number": "901",
            "calls": [c.model_copy(update={"id": f"901-{i}"}) for i, c in enumerate(first.calls)],
        }
    )
    clash = Draft(meet=plan.meet, package=plan.model_copy(update={"trains": [*trains, twin]}))
    conflicts = [f for f in check(clash) if f.code == "track_conflict"]
    assert conflicts and all(f.severity == "conflict" for f in conflicts)
    assert "Tåg 101 och 901 står på spår 1 i Åsen samtidigt (06:08)." in [
        f.message for f in conflicts
    ]


def test_halts_are_not_where_sections_end(tmp_path: Path) -> None:
    plan = package()
    assert {p.kind for p in plan.places} >= {PlaceKind.HALT}
    assert check(Draft(meet=plan.meet, package=plan)) == []
    assert json.loads(EXAMPLE.read_text(encoding="utf-8"))["meet"]["id"] == "provbanan"


def test_a_preview_counts_what_would_change_and_changes_nothing(planning: Planning) -> None:
    meet = planning.create(NewMeet(name="Grimslöv")).meet
    first = source(digest="a")
    planning.add_source(meet.id, first, b"1", result(first))
    planning.change(meet.id, PlaceChange(place="asn", phone="211"))
    second = source("ny.json", digest="b")
    later = result(second)
    trains = list(later.package.trains)
    moved = trains[0].calls[1].model_copy(update={"departure": "06:30", "track": "2"})
    calls = [trains[0].calls[0], moved, *trains[0].calls[2:]]
    trains[0] = trains[0].model_copy(update={"calls": calls})
    later = later.model_copy(
        update={"package": later.package.model_copy(update={"trains": trains[:-1]})}
    )
    preview = planning.preview(meet.id, second, b"2", later)
    assert not preview.first
    assert (preview.trains.removed, preview.trains.changed, preview.times, preview.tracks) == (
        1,
        1,
        1,
        1,
    )
    assert preview.places.changed == 0, "the planner's phone stays, so the place is the same"
    assert (preview.kept, preview.questions) == (1, 1)
    assert len(planning.draft(meet.id).package.trains) == 10  # type: ignore[union-attr]
    with pytest.raises(PlanningError, match="väntar inte"):
        planning.apply(meet.id, first.id)
    draft = planning.apply(meet.id, second.id)
    assert draft.package is not None and len(draft.package.trains) == 9
    with pytest.raises(PlanningError, match="väntar inte"):
        planning.apply(meet.id, second.id)
