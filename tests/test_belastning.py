"""Belastningsprovet (DRIFT-20) and what it found: the hub's meet takes as many boxes and
station clients as a big meet has, and a PDF is read in a process of its own, so that an
import never holds Drift up."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep
from typing import Any

from fastapi.testclient import TestClient

from deploy import belastning
from deploy.belastning import Tally, acceptable, report
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.running import MAX_CLIENTS
from integrationer import pdf_page
from integrationer.tests.pdf_writer import Sheet, pdf


def test_the_report_and_what_is_acceptable() -> None:
    tally = Tally()
    for spent in [0.005] * 98 + [0.02, 0.03]:
        tally.took("ögonblicksbild", spent, 200)
    tally.took("import", 3.0, 422)
    shown = report(tally, 20)
    assert "ögonblicksbild" in shown and "100" in shown and "import 422 × 1" in shown
    assert acceptable(tally), "a file the meet cannot take yet is no failure of Drift"
    tally.took("boxens bild", 0.01, 500)
    assert not acceptable(tally)
    slow = Tally()
    for _ in range(100):
        slow.took("kommando", 1.5, 200)
    assert not acceptable(slow)


def test_phones_and_reports_run_against_a_hub(tmp_path: Path) -> None:
    """Hemmaprovet (#77, SYNK-29): telefoner med TMBox-appen bredvid stationerna och boxarna,
    och ett läge under provet. Here against the hub in this process, for a moment."""
    hub = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))
    assert hub.post("/api/hub/setup", json={"name": "Hubben", "pin": "482915"}).status_code == 201
    assert hub.post("/api/drift/1/start", json={"version": 1}).status_code == 201

    class InProcess(belastning.Hub):
        def call(
            self,
            method: str,
            path: str,
            body: Any = None,
            key: str | None = None,
            kind: str | None = None,
            raw: bytes | None = None,
        ) -> tuple[int, Any]:
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            began = monotonic()
            answer = hub.request(method, path, json=body, headers=headers)
            if kind is not None:
                self.tally.took(kind, monotonic() - began, answer.status_code)
            return answer.status_code, answer.json() if answer.content else None

    tally = Tally()
    near = InProcess("http://testserver", tally)
    admin = hub.post("/api/hub/login", json={"pin": "482915"}).json()["session_key"]
    code = hub.get("/api/drift/1/connect").json()["code"]
    [phone] = belastning.station_clients(near, admin, code, ["asn"], 1, "tmbox_app", "Telefon")
    listed = {c["client_id"]: c for c in hub.get("/api/drift/1/clients").json()}
    assert (listed[phone.client_id]["kind"], listed[phone.client_id]["name"]) == (
        "tmbox_app",
        "Telefon 1",
    )
    stop = Event()

    def enough() -> None:
        # Two pictures, then stop: on a busy CI runner the first can take more than half a
        # second, so a fixed half second sometimes gave only one. At most 10 s.
        deadline = monotonic() + 10.0
        while monotonic() < deadline and len(tally.seconds.get("telefonens bild", [])) < 2:
            sleep(0.02)
        stop.set()

    Thread(target=enough, daemon=True).start()
    belastning.run_client(near, phone, stop, 0.05, "telefonens bild", False)
    assert len(tally.seconds["telefonens bild"]) >= 2 and not tally.errors
    assert "telefonens bild" in report(tally, 1)


def test_the_hubs_meet_takes_more_boxes_than_provbanan(tmp_path: Path) -> None:
    """Found by the load test: Provbanan's limit of 16 also held the hub's own meet."""
    hub = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))
    assert hub.post("/api/hub/setup", json={"name": "Hubben", "pin": "482915"}).status_code == 201
    assert hub.post("/api/drift/1/start", json={"version": 1}).status_code == 201
    assert hub.app.state.running.store.max_clients == MAX_CLIENTS >= 100  # type: ignore[attr-defined]
    code = hub.get("/api/drift/1/connect").json()["code"]
    for n in range(20):
        box = hub.post("/api/terminal/session", json={"name": f"Box {n}", "code": code})
        assert box.status_code == 201, box.text
        client = hub.post(
            "/api/station/1/connect",
            json={"kind": "tkl", "name": f"TKL {n}", "software": "TKL 0.1.0", "code": code},
        )
        assert client.status_code == 201, client.text


def test_a_pdf_is_read_in_a_process_of_its_own_and_once() -> None:
    data = pdf(Sheet().text(40, 60, "Lekby"))
    first = pdf_page.pages(data)
    assert [w.text for w in first[0].words] == ["Lekby"]
    pool = pdf_page._pool
    assert pool is not None and pool.submit(os.getpid).result() != os.getpid()
    # The same file again is not read again, and what comes back is a copy of its own.
    first[0].words.clear()
    again = pdf_page.pages(data)
    assert [w.text for w in again[0].words] == ["Lekby"]
