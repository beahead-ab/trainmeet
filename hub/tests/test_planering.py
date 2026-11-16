"""Steg 4a through the hub: a meet in Planering, Tellurian's file as its source, the check, a
version, and Drift running that version with web boxes (Caspers prov, as a test).

Värnamo Moduldagar is the key (H54).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts import drift, planning
from contracts.common import checksum
from contracts.meet import MeetPackage
from drift.store import PreviewStore
from hub import provbanan
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.running import Running
from hub.tests.test_tmbox_web import Tab
from planering.store import Planning

PIN = "482915"
API = "/api/planering/1"
DRIFT = "/api/drift/1"
FIXTURE = Path(__file__).resolve().parents[2] / "integrationer" / "tests" / "fixtures"
VARNAMO = (FIXTURE / "varnamo.json.gz").read_bytes()
MEET = "varnamo-moduldagar"


def new_hub(tmp_path: Path) -> TestClient:
    return TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "prov.db"))


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    client = new_hub(tmp_path)
    assert client.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN}).status_code == 201
    return client


def upload(hub: TestClient, data: bytes = VARNAMO, name: str = "Värnamo.json.gz") -> Any:
    return hub.post(
        f"{API}/meets/{MEET}/sources",
        params={"name": name},
        content=data,
        headers={"Content-Type": "application/octet-stream"},
    )


@pytest.fixture
def planned(hub: TestClient) -> TestClient:
    created = hub.post(
        API + "/meets",
        json={"name": "Värnamo Moduldagar", "first_date": "2026-10-30", "last_date": "2026-11-01"},
    )
    assert created.status_code == 201, created.text
    response = upload(hub)
    assert response.status_code == 201, response.text
    source = response.json()["source"]["id"]
    applied = hub.post(f"{API}/meets/{MEET}/sources/{source}/apply")
    assert applied.status_code == 200, applied.text
    return hub


def test_only_the_administrator_changes_and_everyone_may_look(planned: TestClient) -> None:
    anonymous = TestClient(planned.app)
    assert anonymous.post(API + "/meets", json={"name": "X"}).status_code == 401
    assert anonymous.post(f"{API}/meets/{MEET}/versions").status_code == 401
    change = {"changes": [{"place": "p2", "phone": "1"}]}
    assert anonymous.post(f"{API}/meets/{MEET}/changes", json=change).status_code == 401
    assert anonymous.post(f"{API}/meets/{MEET}/sources/u-x/apply").status_code == 401
    [summary] = anonymous.get(API + "/meets").json()
    assert (summary["meet"]["id"], summary["level"], summary["trains"]) == (MEET, 4, 228)
    draft = planning.Draft.model_validate(anonymous.get(f"{API}/meets/{MEET}").json())
    source = draft.sources[0]
    path = f"{API}/meets/{MEET}/sources/{source.id}"
    assert anonymous.get(path).status_code == 401, "the file itself only for the administrator"
    assert planned.get(path).content == VARNAMO


def test_the_file_gives_the_draft_and_the_report(planned: TestClient) -> None:
    draft = planning.Draft.model_validate(planned.get(f"{API}/meets/{MEET}").json())
    assert draft.package is not None and draft.report is not None
    assert (draft.meet.name, str(draft.meet.first_date)) == ("Värnamo Moduldagar", "2026-10-30")
    assert draft.meet.traffic_week.days == 6
    assert (draft.report.trains, draft.report.calls, draft.report.sections) == (228, 1366, 17)
    assert draft.sources[0].filename == "Värnamo.json.gz" and draft.questions == []


def test_files_that_are_not_a_plan_are_refused(planned: TestClient) -> None:
    assert upload(planned, b"{not json", "plan.json").status_code == 422
    refused = upload(planned, b"%PDF-1.7", "Banan.pdf")
    assert refused.status_code == 415 and "planeringsfil" in refused.json()["detail"]
    assert upload(planned, b"", "plan.json").status_code == 422
    missing = planned.post(f"{API}/meets/nowhere/sources", params={"name": "a.json"}, content=b"{}")
    assert missing.status_code == 404


def test_the_planner_saves_several_changes_at_once(planned: TestClient) -> None:
    saved = planned.post(
        f"{API}/meets/{MEET}/changes",
        json={
            "changes": [
                {"place": "p2", "phone": "241"},
                {"section": "d2", "clearance_mode": "direct"},
                {"section": "d2", "tracks": "double"},
                {"place": "p2", "phone": "242"},
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    draft = planning.Draft.model_validate(saved.json())
    assert draft.package is not None
    assert next(p.phone for p in draft.package.places if p.id == "p2") == "242"
    section = next(s for s in draft.package.sections if s.id == "d2")
    assert (section.clearance_mode, section.tracks) == ("direct", "double")
    assert len(draft.changes) == 3, "the last change per field counts"
    unknown = planned.post(
        f"{API}/meets/{MEET}/changes", json={"changes": [{"place": "p999", "phone": "1"}]}
    )
    assert unknown.status_code == 409


def test_a_source_waits_until_it_is_laid_in(hub: TestClient) -> None:
    hub.post(API + "/meets", json={"name": "Värnamo Moduldagar"})
    preview = planning.ImportPreview.model_validate(upload(hub).json())
    assert preview.first and preview.report.level == 4
    assert (preview.trains.added, preview.places.added, preview.sections.added) == (228, 31, 17)
    assert preview.lines.added == 9, "the graph's lines from the plan"
    draft = planning.Draft.model_validate(hub.get(f"{API}/meets/{MEET}").json())
    assert draft.package is None, "nothing changes before Lägg in i utkastet"
    wrong = hub.post(f"{API}/meets/{MEET}/sources/u-other/apply")
    assert wrong.status_code == 409
    hub.post(f"{API}/meets/{MEET}/sources/{preview.source.id}/apply")
    hub.post(f"{API}/meets/{MEET}/changes", json={"changes": [{"place": "p2", "phone": "241"}]})
    # The same file again changes nothing, and the planner's change stays.
    again = planning.ImportPreview.model_validate(upload(hub).json())
    assert not again.first and again.kept == 1
    assert (again.trains, again.places, again.times, again.tracks) == (
        planning.Difference(),
        planning.Difference(),
        0,
        0,
    )
    gone = hub.post(f"{API}/meets/{MEET}/sources/{preview.source.id}/apply")
    assert gone.status_code == 200
    assert hub.post(f"{API}/meets/{MEET}/sources/{preview.source.id}/apply").status_code == 409


def test_the_check_and_publishing(planned: TestClient) -> None:
    check = planning.Check.model_validate(planned.get(f"{API}/meets/{MEET}/check").json())
    codes = {f.code for f in check.findings}
    assert codes == {"no_section"}, "Värnamo has no track conflicts"
    published = planned.post(f"{API}/meets/{MEET}/versions")
    assert published.status_code == 201, published.text
    version = planning.Version.model_validate(published.json())
    assert (version.number, version.conflicts, version.observations) == (1, 0, 2)
    again = planned.post(f"{API}/meets/{MEET}/versions")
    assert again.status_code == 409 and "samma som version 1" in again.json()["detail"]
    package = MeetPackage.model_validate(planned.get(f"{API}/meets/{MEET}/versions/1").json())
    assert package.meet.id == MEET and len(package.findings) == 2
    assert planned.get(f"{API}/meets/{MEET}/versions/2").status_code == 404


def run_varnamo(hub: TestClient) -> drift.Now:
    assert hub.post(f"{API}/meets/{MEET}/versions").status_code == 201
    started = hub.post(DRIFT + "/start", json={"meet": MEET, "version": 1})
    assert started.status_code == 201, started.text
    response = hub.get(DRIFT + "/now")
    return drift.Now.model_validate(response.json())


def test_drift_runs_the_published_version(planned: TestClient) -> None:
    provbanan = planned.post(DRIFT + "/start", json={"version": 1})
    assert provbanan.status_code == 201
    code = drift.Joining.model_validate(planned.get(DRIFT + "/connect").json()).code
    old_box = Tab(planned, "Box Norrby", code)
    assert planned.post(DRIFT + "/start", json={"meet": MEET, "version": 2}).status_code == 409
    seen = run_varnamo(planned)
    assert (seen.meet_id, seen.name, seen.version) == (MEET, "Värnamo Moduldagar", 1)
    assert (seen.clock.time, seen.traffic_day) == ("05:00", "mon")
    assert len(seen.places) == 20, "every place that is not a halt"
    # Byt träff lets the boxes of the meet before go: they join the new one with its code.
    assert planned.get("/api/terminal/frame", headers=old_box.headers).status_code == 401


def test_two_boxes_run_a_varnamo_train(planned: TestClient) -> None:
    seen = run_varnamo(planned)
    # The meet starts at 05:00: the night's trains stand where the timetable has them, counted
    # as arrived (DRIFT-43), and the first train still to run is taken.
    assert next(item for item in seen.legs if item.train_number == "537").state == "arrived"
    leg = next(item for item in seen.legs if item.state == "planned")
    code = drift.Joining.model_validate(planned.get(DRIFT + "/connect").json()).code
    sender, receiver = Tab(planned, "Box 1", code), Tab(planned, "Box 2", code)
    for box, place in ((sender, leg.from_place), (receiver, leg.to_place)):
        assigned = planned.post(
            DRIFT + "/clients/assign", json={"client_id": box.client_id, "places": [place]}
        )
        assert assigned.status_code == 200, assigned.text
    sender.number(leg.train_number)
    request = receiver.frame()["lines"][0]
    assert f"{leg.train_number}?" in request or f"?{leg.train_number}" in request
    receiver.press("#")  # Klart.
    sender.press("#")  # Avgång.
    receiver.press("#")  # Ankomst.
    assert receiver.frame()["lines"][0].startswith(f"{leg.train_number} ANK")
    after = drift.Now.model_validate(planned.get(DRIFT + "/now").json())
    done = next(item for item in after.legs if item.leg == leg.leg)
    assert done.state == "arrived"


def test_the_running_meet_survives_a_restart(planned: TestClient, tmp_path: Path) -> None:
    run_varnamo(planned)
    again = new_hub(tmp_path)
    seen = drift.Now.model_validate(again.get(DRIFT + "/now").json())
    assert (seen.meet_id, seen.version) == (MEET, 1)


def test_the_pages_follow_s6_and_the_buttons_need_the_administrator(planned: TestClient) -> None:
    """Planering is Data · Bana · Graf · Versioner (S6), all in apps/planering; what the pages
    show is tested there. The hub gives every address under /planering the app."""
    anonymous = TestClient(planned.app)
    pages = ("/planering", f"/planering/{MEET}", f"/planering/{MEET}/data")
    for path in (
        *pages,
        f"/planering/{MEET}/bana",
        f"/planering/{MEET}/graf",
        f"/planering/{MEET}/versioner",
    ):
        page = anonymous.get(path)
        assert page.status_code == 200 and "Planering" in page.text, path
        assert "script-src 'self'" in page.headers["content-security-policy"], path
    for old in ("/static/planering.js", "/static/bana.js", "/static/graf.js"):
        assert anonymous.get(old).status_code == 404, old  # the old pages are gone
    # A path out of the folder never gives a file: at most the app's own page.
    outside = planned.get("/planering/..%2Fx")
    assert outside.status_code in {200, 404, 422}
    assert outside.status_code != 200 or "Planering" in outside.text


def test_a_run_keeps_its_package_when_the_contracts_gain_a_field(
    planned: TestClient, tmp_path: Path
) -> None:
    """A run belongs to the version as published, so a new contract field with a default (as
    call.exchange in 4a) does not end the meet that runs."""
    run_varnamo(planned)
    plans = Planning(tmp_path / "planering.sqlite3")
    [version] = plans.versions(MEET)
    running = Running(tmp_path, provbanan.package(), provbanan.package_key(), plans)
    store = running.store
    assert store.package_key == version.checksum
    run_id = store.current()
    widened = MeetPackage.model_validate({**store.package.model_dump(mode="json"), "later": 1})
    assert checksum(widened.model_dump(mode="json")) != version.checksum
    later = PreviewStore(store.path, widened, version=1, package_key=version.checksum, max_runs=64)
    assert later.current() == run_id
    assert provbanan.package_key() == checksum(
        json.loads(
            (Path(__file__).parents[2] / "contracts/examples/provbanan.meet.json").read_text()
        )
    )


def test_a_driftändring_becomes_a_proposal_and_drift_sees_the_answer(planned: TestClient) -> None:
    """Förslag från Drift (4.4, PLAN-03, TRAFIK-16) through the hub: made in Nu, answered in
    Versioner, seen again in Nu. Släppt before an answer, it is withdrawn."""
    seen = run_varnamo(planned)
    first, second, third = [leg.train for leg in seen.legs if leg.state == "planned"][:3]
    for train in (first, second, third):
        made = planned.post(
            DRIFT + "/changes", json={"change": {"kind": "note", "train": train, "text": "Ånglok"}}
        )
        assert made.status_code == 200, made.text
    proposals = planned.get(f"{API}/meets/{MEET}/proposals").json()
    assert [p["status"] for p in proposals] == ["waiting"] * 3
    by_train = {p["change"]["train"]: p["id"] for p in proposals}
    assert (
        TestClient(planned.app)
        .post(f"{API}/meets/{MEET}/proposals/{by_train[first]}/take")
        .status_code
        == 401
    )
    taken = planned.post(f"{API}/meets/{MEET}/proposals/{by_train[first]}/take")
    assert taken.status_code == 200, taken.text
    draft = planning.Draft.model_validate(taken.json())
    assert draft.package is not None
    assert next(t.note for t in draft.package.trains if t.id == first) == "Ånglok"
    assert (
        planned.post(f"{API}/meets/{MEET}/proposals/{by_train[second]}/reject").status_code == 200
    )
    assert planned.post(DRIFT + f"/changes/{by_train[third]}/drop").status_code == 200
    answers = {
        c.change_id: c.proposal
        for c in drift.Now.model_validate(planned.get(DRIFT + "/now").json()).changes
    }
    assert answers == {
        by_train[first]: "taken",
        by_train[second]: "rejected",
        by_train[third]: "withdrawn",
    }


def test_the_dispatcher_switches_to_a_new_version_during_the_meet(planned: TestClient) -> None:
    """Versionsbyte (TRAFIK-03, DRIFT-29, H4, H66) through the hub: the change the planner took
    into version 2 falls away at the switch, the one kept stays on top of version 2."""
    seen = run_varnamo(planned)
    noted, cancelled = [leg.train for leg in seen.legs if leg.state == "planned"][:2]
    note = {"change": {"kind": "note", "train": noted, "text": "Ånglok"}}
    note_id = drift.ChangeMade.model_validate(
        planned.post(DRIFT + "/changes", json=note).json()["data"]
    ).change_id
    cancel = {"change": {"kind": "cancel", "train": cancelled}}
    cancel_id = drift.ChangeMade.model_validate(
        planned.post(DRIFT + "/changes", json=cancel).json()["data"]
    ).change_id
    assert planned.post(f"{API}/meets/{MEET}/proposals/{note_id}/take").status_code == 200
    assert planned.post(f"{API}/meets/{MEET}/versions").status_code == 201
    anonymous = TestClient(planned.app)
    assert anonymous.get(DRIFT + "/switch/2").status_code == 401
    preview = drift.SwitchPreview.model_validate(planned.get(DRIFT + "/switch/2").json())
    assert {c.change_id: c.included for c in preview.changes} == {note_id: True, cancel_id: False}
    assert preview.waits_for == []
    assert anonymous.post(DRIFT + "/switch", json={"version": 2}).status_code == 401
    switched = planned.post(DRIFT + "/switch", json={"version": 2})
    assert switched.status_code == 200, switched.text
    assert drift.DriftEvent.model_validate(switched.json()).kind == drift.EventKind.VERSION_SWITCHED
    after = drift.Now.model_validate(planned.get(DRIFT + "/now").json())
    assert after.version == 2
    assert {c.change_id: c.status for c in after.changes} == {
        note_id: "dropped",
        cancel_id: "applied",
    }
    package = planned.get(DRIFT + "/package").json()
    trains = {t["id"]: t for t in package["trains"]}
    assert trains[noted]["note"] == "Ånglok", "from version 2 itself"
    assert cancelled not in trains, "kept on top of version 2"
    assert planned.post(DRIFT + "/switch", json={"version": 2}).status_code == 409
