"""The automation on the box and in Trafikledningen (F14, issue 18), ported from the old
Server's test_station_automatic: * on the start screen leaves the place to the automation
(AUTOMATIK?), the start screen then says AUTOMATIK with the place's code and #Aktiv, # takes
it back (TA TILLBAKA?), and a traffic key there asks first. Trafikledningen sees who works
each place, leaves and gives back, and chooses the settings; the hub ticks the automation.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts import drift
from drift import lcd
from drift.engine import Drift
from drift.terminal_text import LANGUAGES
from hub.app import tick_once
from hub.tests.test_drift_api import API, code_of, running  # noqa: F401
from hub.tests.test_drift_api import hub as hub
from hub.tests.test_tmbox_terminal import Lab
from hub.tests.test_tmbox_web import Tab


def first(lab: Lab, place: str) -> str:
    return lab.lines(place)[0]


def hint(lab: Lab, place: str) -> str:
    return lab.lines(place)[1][:11].strip()


def leave(lab: Lab, place: str = "asn") -> None:
    lab.accept(place, "*")
    lab.accept(place, "#")


def test_star_asks_and_hash_leaves_the_place_to_the_automation() -> None:
    lab = Lab()
    assert lab.frame("asn")["keys"]["*"]["label"] == "Lämna till automatiken…"
    lab.accept("asn", "*")
    assert (first(lab, "asn").strip(), hint(lab, "asn")) == ("AUTOMATIK?", "#Ja *Nej")
    lab.accept("asn", "#")
    left = lab.drift.left["asn"]
    assert (left.by, left.client_id) == (drift.LeftBy.OPERATOR, "box-asn")
    assert first(lab, "asn") == "AUTOMATIK     Ån"
    assert hint(lab, "asn") == "#Aktiv"
    assert "Automatiken sköter stationen" in lab.frame("asn")["status"]


def test_star_then_star_changes_nothing() -> None:
    lab = Lab()
    lab.accept("asn", "*")
    lab.accept("asn", "*")
    assert not lab.drift.left
    assert "AUTOMATIK" not in first(lab, "asn")


def test_hash_on_the_start_screen_takes_it_back() -> None:
    lab = Lab()
    leave(lab)
    assert lab.frame("asn")["keys"]["#"]["label"] == "Ta tillbaka stationen…"
    lab.accept("asn", "#")
    assert (first(lab, "asn").strip(), hint(lab, "asn")) == ("TA TILLBAKA?", "#Ja *Nej")
    lab.accept("asn", "#")
    assert "asn" not in lab.drift.left
    assert lab.drift.manned["asn"] == "box-asn"
    assert "AUTOMATIK" not in first(lab, "asn")


def test_star_on_the_question_keeps_the_automation() -> None:
    lab = Lab()
    leave(lab)
    lab.accept("asn", "#")
    lab.accept("asn", "*")
    assert "asn" in lab.drift.left
    assert first(lab, "asn") == "AUTOMATIK     Ån"


def test_a_traffic_key_asks_first_and_acts_after_the_place_is_back() -> None:
    lab = Lab()
    leave(lab)
    lab.lookup("101")  # Norrby asks for 101 at once.
    lab.lookup("101", "asn")
    lab.accept("asn", "#")  # Ge klart: the box asks to take the place back first.
    assert first(lab, "asn").strip() == "TA TILLBAKA?"
    case = next(iter(lab.drift.cases.values()))
    assert case.status == "waiting"
    lab.accept("asn", "#")
    assert "asn" not in lab.drift.left
    lab.accept("asn", "#")  # Now the answer goes.
    assert next(iter(lab.drift.cases.values())).status == "approved"


def test_a_request_to_a_place_left_to_the_automation_leaves_the_box_on_automatik() -> None:
    lab = Lab()
    leave(lab)
    lab.lookup("101")  # Norrby asks Åsen, which the automation works.
    assert first(lab, "asn") == "AUTOMATIK     Ån"
    assert lab.frame("asn")["attention"]["kind"] is None


def test_not_offered_while_the_automation_is_switched_off() -> None:
    lab = Lab()
    lab.drift.set_automation(drift.AutomationSettings(enabled=False), lab.now)
    assert "*" not in lab.frame("asn")["keys"]


def test_switching_the_automation_off_gives_the_place_back_to_its_box() -> None:
    lab = Lab()
    leave(lab)
    lab.drift.set_automation(drift.AutomationSettings(enabled=False), lab.now)
    assert "AUTOMATIK" not in first(lab, "asn")
    lab.lookup("101")
    lab.lookup("101", "asn")
    lab.accept("asn", "#")
    assert next(iter(lab.drift.cases.values())).status == "approved"


def test_a_place_left_to_the_automation_stays_so_after_a_restart() -> None:
    lab = Lab()
    leave(lab)
    lab.drift = Drift(lab.package, lab.drift.history, now=lab.now)
    assert first(lab, "asn") == "AUTOMATIK     Ån"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("display", [(2, 16), (4, 20)])
def test_the_automation_pictures_fit_in_every_language(
    language: str, display: tuple[int, int]
) -> None:
    lab = Lab()
    box = lab.boxes["asn"]
    box.language, (box.rows, box.cols) = language, display
    pictures = []
    for key in ("*", "#", "#"):  # AUTOMATIK?, AUTOMATIK, TA TILLBAKA?
        lab.send("asn", key)
        pictures.append(lab.lines("asn"))
    for lines in pictures:
        assert len(lines) == display[0] and all(len(row) == display[1] for row in lines)
        assert lcd.fits(lines)
    assert pictures[1][0].startswith(
        {
            "sv": "AUTOMATIK",
            "en": "AUTOMATIC",
            "da": "AUTOMATIK",
            "nb": "AUTOMATIKK",
            "de": "AUTOMATIK",
        }[language]
    )


# --- In the hub: contact, Trafikledningen and the ticks -----------------------------------


def automation(client: TestClient) -> drift.AutomationStatus:
    response = client.get(API + "/automation")
    assert response.status_code == 200, response.text
    return drift.AutomationStatus.model_validate(response.json())


def place(status: drift.AutomationStatus, place_id: str) -> drift.AutomationPlaceStatus:
    return next(p for p in status.places if p.place == place_id)


def box_at(hub: TestClient, place_id: str) -> Tab:
    box = Tab(hub, f"Box {place_id}", code_of(hub))
    assigned = hub.post(
        API + "/clients/assign", json={"client_id": box.client_id, "places": [place_id]}
    )
    assert assigned.status_code == 200
    box.frame()
    return box


def test_only_the_dispatcher_sees_and_changes_the_automation(running: TestClient) -> None:  # noqa: F811
    anonymous = TestClient(running.app)
    assert anonymous.get(API + "/automation").status_code == 401
    assert anonymous.post(API + "/automation", json={"enabled": False}).status_code == 401
    status = automation(running)
    assert status.settings == drift.AutomationSettings()
    assert {p.mode for p in status.places} == {drift.PlaceMode.AUTOMATIC}
    assert [p.code for p in status.places] == ["Nby", "Ån", "Mlå", "Sjv"]


def test_the_first_box_at_a_place_mans_it_and_the_dispatcher_leaves_and_gives_back(
    running: TestClient,  # noqa: F811
) -> None:
    box = box_at(running, "asn")
    status = place(automation(running), "asn")
    assert (status.mode, status.operator, status.present) == (
        drift.PlaceMode.MANNED,
        box.client_id,
        [box.client_id],
    )
    left = running.post(API + "/automation/place", json={"place": "asn", "action": "leave"})
    assert left.status_code == 200
    status = place(drift.AutomationStatus.model_validate(left.json()), "asn")
    assert (status.mode, status.left_by) == (drift.PlaceMode.AUTOMATIC, drift.LeftBy.DISPATCHER)
    assert box.frame()["lines"][0] == "AUTOMATIK     Ån"
    back = running.post(API + "/automation/place", json={"place": "asn", "action": "take_back"})
    assert back.status_code == 200
    assert place(drift.AutomationStatus.model_validate(back.json()), "asn").mode == "manned"
    nobody = running.post(API + "/automation/place", json={"place": "nby", "action": "take_back"})
    assert nobody.status_code == 409
    assert nobody.json()["detail"] == "Klienten måste vara ansluten till driftplatsen."


def test_the_dispatcher_chooses_the_settings(running: TestClient) -> None:  # noqa: F811
    chosen: dict[str, Any] = {
        "lost_contact_minutes": 5,
        "disturbance": "normal",
        "answer_seconds": 0,
    }
    response = running.post(API + "/automation", json=chosen)
    assert response.status_code == 200
    settings = drift.AutomationStatus.model_validate(response.json()).settings
    assert (settings.lost_contact_minutes, settings.disturbance, settings.answer_seconds) == (
        5,
        drift.Disturbance.NORMAL,
        0,
    )
    assert running.post(API + "/automation", json={"lost_contact_minutes": 3}).status_code == 422
    log = running.get(API + "/log").json()
    assert log[0]["kind"] == "automation.set" and log[0]["actor"]["kind"] == "dispatcher"


def test_the_hub_ticks_the_automation_while_the_clock_runs(running: TestClient) -> None:  # noqa: F811
    hub_running = running.app.state.running  # type: ignore[attr-defined]
    running.post(API + "/automation", json={"answer_seconds": 0})
    tick_once(hub_running)
    assert not [e for e in running.get(API + "/log").json() if e["kind"] == "clearance.requested"]
    assert running.post(API + "/clock", json={"action": "start"}).status_code == 200
    # Nobody works Norrby or Åsen: the automation asks for 101 and gives it clear.
    tick_once(hub_running)
    tick_once(hub_running)
    log = running.get(API + "/log").json()
    asked = next(e for e in log if e["kind"] == "clearance.requested")
    answered = next(e for e in log if e["kind"] == "clearance.answered")
    assert (asked["place"], asked["actor"]["kind"]) == ("nby", "automation")
    assert (answered["place"], answered["actor"]["kind"]) == ("asn", "automation")
