"""Tellurian Dispatch i skugga (H79, IMPORT-06, IMPORT-34, issue 93), in the hub.

Tellurian's simulator answers over HTTP on 127.0.0.1 (integrationer/tellurian_sim.py). The hub
reads every five seconds in a thread of its own; here each round is taken by hand. Nothing
is ever sent to Tellurian, and Drift is never touched.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts import drift
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.provbanan import package as provbanan
from hub.tellurian_shadow import Shadow, SimulatorFeed
from hub.tests.test_drift_api import API, PIN, nu
from integrationer.tellurian_sim import SimSection, TellurianSimulator

SETTINGS = "/api/hub/tellurian"


class Hub:
    def __init__(self, tmp_path: Path) -> None:
        self.client = TestClient(
            create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "prov.db")
        )
        assert self.client.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN}).status_code
        assert self.client.post(API + "/start", json={"version": 1}).status_code == 201

    @property
    def shadow(self) -> Shadow:
        found: Shadow = self.client.app.state.tellurian  # type: ignore[attr-defined]
        return found

    def round(self) -> drift.Now:
        self.shadow.round()
        return nu(self.client)

    def save(self, **given: Any) -> Any:
        return self.client.post(SETTINGS, json=given)


@pytest.fixture
def h(tmp_path: Path) -> Hub:
    return Hub(tmp_path)


@pytest.fixture
def sim() -> Iterator[TellurianSimulator]:
    with TellurianSimulator.from_package(provbanan()) as simulator:
        yield simulator


def test_off_by_default_and_only_for_the_one_who_runs_the_meet(h: Hub) -> None:
    settings = h.client.get(SETTINGS).json()
    assert (settings["mode"], settings["meet"], settings["simulator"]) == ("off", "provbanan", None)
    assert nu(h.client).tellurian is None
    anonymous = TestClient(h.client.app)
    assert anonymous.get(SETTINGS).status_code == 401
    assert anonymous.post(SETTINGS, json={"mode": "off"}).status_code == 401


def test_the_shadow_shows_tellurian_beside_drift_and_never_writes(
    h: Hub, sim: TellurianSimulator
) -> None:
    sim.set_sections([SimSection(train="Pt 101", from_code="Nby", to_code="Ån", state="Accepted")])
    # Loopback is a test instance only.
    refused = h.save(mode="shadow", address=sim.base_url)
    assert refused.status_code == 422
    assert refused.json()["detail"].startswith("Adressen är inte på träffens nät.")
    saved = h.save(mode="shadow", address=sim.base_url + "/", test_instance=True)
    assert saved.status_code == 200, saved.text
    assert saved.json()["address"] == sim.base_url
    seen = h.round()
    assert seen.tellurian is not None
    assert (seen.tellurian.contact, seen.tellurian.simulated) == ("ok", True)
    section = next(s for s in seen.tellurian.sections if s.train == "Pt 101")
    assert (section.from_code, section.to_code, section.state) == ("Nby", "Ån", "Accepted")
    assert section.differs and seen.tellurian.differences >= 1, "Drift has cleared nothing"
    # Logg: what Tellurian changed, beside Drift's own log.
    log = h.client.get(SETTINGS + "/log").json()
    assert log and log[0]["text"].startswith("101 Nby–Ån: klar")
    # Nothing was ever sent to Tellurian.
    assert {method for method, _ in sim.requests} == {"GET"}
    # Off again: nothing more is read, and Nu says nothing.
    reads = len(sim.requests)
    assert h.save(mode="off").status_code == 200
    assert h.round().tellurian is None
    assert len(sim.requests) == reads


def test_without_an_answer_the_contact_is_lost_after_15_seconds(
    h: Hub, sim: TellurianSimulator
) -> None:
    h.save(mode="shadow", address=sim.base_url, test_instance=True)
    clock = [datetime.now().astimezone()]
    h.shadow.clock = lambda: clock[0]
    h.round()
    sim.fail_next_read("server_error")
    clock[0] += timedelta(seconds=5)
    seen = h.round()
    assert seen.tellurian is not None and seen.tellurian.contact == "ok", "one miss is not lost"
    assert seen.tellurian.problem is not None
    sim.stop()
    clock[0] += timedelta(seconds=16)
    seen = h.round()
    assert seen.tellurian is not None and seen.tellurian.contact == "lost"
    assert seen.tellurian.problem == "Tellurian Dispatch svarar inte på adressen."


def test_a_tellurian_that_does_not_answer_is_not_saved(h: Hub) -> None:
    refused = h.save(mode="shadow", address="http://127.0.0.1:9", test_instance=True)
    assert (refused.status_code, refused.json()["detail"]) == (
        422,
        "Tellurian Dispatch svarar inte på adressen.",
    )
    assert h.client.get(SETTINGS).json()["mode"] == "off"


def test_in_the_test_environment_the_simulator_shows_drifts_clearances_with_one_difference(
    h: Hub,
) -> None:
    feed = SimulatorFeed(h.shadow)
    try:
        feed.round()
        address = h.client.get(SETTINGS).json()["simulator"]
        assert address and address.startswith("http://127.0.0.1:")
        assert h.save(mode="shadow", address=address, test_instance=True).status_code == 200
        seen = h.round()
        assert seen.tellurian is not None and seen.tellurian.simulated
    finally:
        feed.stop()
