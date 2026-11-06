"""Steg 4a through the hub: a meet in Planering, Stefan's file as its source, the check, a
version, and Drift running that version with web boxes (Caspers prov, as a test).

Värnamo Moduldagar is the key (H54).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts import drift, planning
from contracts.meet import MeetPackage
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.tests.test_tmbox_web import Tab

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
    return hub


def test_only_the_administrator_changes_and_everyone_may_look(planned: TestClient) -> None:
    anonymous = TestClient(planned.app)
    assert anonymous.post(API + "/meets", json={"name": "X"}).status_code == 401
    assert anonymous.post(f"{API}/meets/{MEET}/versions").status_code == 401
    assert (
        anonymous.post(f"{API}/meets/{MEET}/places", json={"place": "p2", "phone": "1"}).status_code
        == 401
    )
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


def test_the_planner_changes_a_phone_and_a_clearance_mode(planned: TestClient) -> None:
    place = planned.post(f"{API}/meets/{MEET}/places", json={"place": "p2", "phone": "241"})
    assert (place.status_code, place.json()["phone"]) == (200, "241")
    section = planned.post(
        f"{API}/meets/{MEET}/sections", json={"section": "d2", "clearance_mode": "direct"}
    )
    assert (section.status_code, section.json()["clearance_mode"]) == (200, "direct")
    unknown = planned.post(f"{API}/meets/{MEET}/places", json={"place": "p999", "phone": "1"})
    assert unknown.status_code == 409


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
    leg = seen.legs[0]
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


def test_the_pages_are_light_and_the_buttons_need_the_administrator(planned: TestClient) -> None:
    anonymous = TestClient(planned.app)
    for path in ("/planering", f"/planering/{MEET}", f"/planering/{MEET}/data"):
        page = anonymous.get(path)
        assert page.status_code == 200 and "/static/planering.css" in page.text
    assert 'id="upload"' in planned.get(f"/planering/{MEET}").text
    assert 'id="upload"' not in anonymous.get(f"/planering/{MEET}").text
    assert 'id="publish"' in planned.get(f"/planering/{MEET}/versioner").text
    assert 'id="new-meet"' not in anonymous.get("/planering").text
    assert 'aria-current=page>Data<' in planned.get(f"/planering/{MEET}/data").text
    assert planned.get("/planering/..%2Fx").status_code in {404, 422}
    assert 'href="/planering"' in planned.get("/").text
    assert 'id="new-choice"' in planned.get("/drift").text
