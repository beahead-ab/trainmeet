"""Förslag från Drift (4.4, PLAN-03, TRAFIK-16): every driftändring is a proposal for the next
version. The planner takes it into the draft (Ta med) or rejects it (Avslå); one taken stays
when the sources are read again, and one let go in Drift before an answer is withdrawn."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts import drift as changes
from contracts.drift import ProposalStatus
from contracts.planning import NewMeet
from planering.store import Planning, PlanningError, UnknownProposal
from planering.tests.test_planning import MON, SUN, result, source


@pytest.fixture
def meet(planning: Planning) -> str:
    meet = planning.create(NewMeet(name="Grimslöv", first_date=MON, last_date=SUN)).meet
    src = source()
    planning.add_source(meet.id, src, b"1", result(src))
    return meet.id


@pytest.fixture
def planning(tmp_path: Path) -> Planning:
    return Planning(tmp_path / "planering.sqlite3")


def propose(planning: Planning, meet: str, change_id: str, change: changes.DriftChange) -> None:
    planning.propose(meet, 1, change_id, change, None)


def test_a_driftändring_waits_in_planering(planning: Planning, meet: str) -> None:
    propose(planning, meet, "c1", changes.CancelTrain(train="t101"))
    propose(planning, meet, "c1", changes.CancelTrain(train="t101"))
    (waiting,) = planning.proposals(meet)
    assert (waiting.id, waiting.version, waiting.status) == ("c1", 1, ProposalStatus.WAITING)
    assert planning.answers(meet) == {"c1": ProposalStatus.WAITING}
    planning.propose("provbanan", 1, "c2", changes.CancelTrain(train="t101"), None)
    assert planning.answers("provbanan") == {}, "Provbanan is no meet of Planering's"


def test_ta_med_lays_it_on_the_draft_and_it_stays_when_the_source_is_read_again(
    planning: Planning, meet: str
) -> None:
    propose(planning, meet, "c1", changes.CancelTrain(train="t102"))
    extra = changes.ExtraTrain(number="9101", copy_of="t101", departure="10:00")
    propose(planning, meet, "c2", extra)
    draft = planning.take(meet, "c1")
    draft = planning.take(meet, "c2")
    assert draft.package is not None
    trains = {t.id: t.number for t in draft.package.trains}
    assert "t102" not in trains and trains["x-c2"] == "9101", "the same id as in Drift"
    again = planning.add_source(meet, source(digest="b"), b"2", result(source(digest="b")))
    assert again.package is not None
    assert {t.id for t in again.package.trains} == set(trains)
    assert [t.id for t in again.taken] == ["c1", "c2"]
    assert planning.answers(meet) == {"c1": ProposalStatus.TAKEN, "c2": ProposalStatus.TAKEN}
    package = planning.freeze(meet)
    assert "x-c2" in {t.id for t in package.trains}, "the next version has it"


def test_avslå_and_an_answer_is_given_once(planning: Planning, meet: str) -> None:
    propose(planning, meet, "c1", changes.ChangeNumber(train="t101", number="111"))
    rejected = planning.reject(meet, "c1")
    assert (rejected.status, rejected.answered is not None) == (ProposalStatus.REJECTED, True)
    draft = planning.draft(meet)
    assert draft.package is not None
    assert next(t.number for t in draft.package.trains if t.id == "t101") == "101"
    with pytest.raises(PlanningError):
        planning.take(meet, "c1")
    with pytest.raises(UnknownProposal):
        planning.reject(meet, "nothing")


def test_one_that_no_longer_fits_the_draft_is_not_taken(planning: Planning, meet: str) -> None:
    planning.change(meet)  # nothing
    propose(planning, meet, "c1", changes.CancelTrain(train="t101"))
    propose(planning, meet, "c2", changes.ChangeNumber(train="t101", number="111"))
    planning.take(meet, "c1")
    with pytest.raises(PlanningError) as error:
        planning.take(meet, "c2")
    assert "Tåget finns inte i träffen." in str(error.value)
    assert planning.answers(meet)["c2"] == ProposalStatus.WAITING, "it can still be rejected"


def test_let_go_in_drift_before_an_answer_it_is_withdrawn(planning: Planning, meet: str) -> None:
    propose(planning, meet, "c1", changes.CancelTrain(train="t101"))
    propose(planning, meet, "c2", changes.CancelTrain(train="t102"))
    planning.take(meet, "c2")
    planning.withdraw(meet, "c1")
    planning.withdraw(meet, "c2")
    planning.withdraw(meet, "unknown")
    assert planning.answers(meet) == {"c1": ProposalStatus.WITHDRAWN, "c2": ProposalStatus.TAKEN}
