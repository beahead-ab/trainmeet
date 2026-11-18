"""Förarna in Planering (PLAN-40, LOK-34, LF21): the general instructions the duties refer to, as
text or as a PDF. They are kept in the meet package, the text in about and the PDF as an
attachment with its checksum beside the package, and go with the next version to Drift, where
Lokföraren shows what there is.

Värnamo's planning file brings its general instructions as text; the planner may change them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contracts import driver as contract
from contracts import planning
from contracts.common import Language
from contracts.meet import AttachmentKind
from hub.tests.test_planering import API, DRIFT, MEET, PIN, new_hub, save, upload

PDF = b"%PDF-1.7\n" + b"0" * 2048 + b"\n%%EOF\n"
OTHER_PDF = b"%PDF-1.7\n" + b"1" * 2048 + b"\n%%EOF\n"


@pytest.fixture
def planned(tmp_path: Path) -> TestClient:
    hub = new_hub(tmp_path)
    assert hub.post("/api/hub/setup", json={"name": "Hubben", "pin": PIN}).status_code == 201
    assert hub.post(API + "/meets", json={"name": "Värnamo Moduldagar"}).status_code == 201
    source = upload(hub).json()["source"]["id"]
    assert hub.post(f"{API}/meets/{MEET}/sources/{source}/apply").status_code == 200
    return hub


def draft(hub: TestClient) -> planning.Draft:
    return planning.Draft.model_validate(hub.get(f"{API}/meets/{MEET}").json())


def test_the_instructions_are_text_or_a_pdf_in_the_package(planned: TestClient) -> None:
    imported = draft(planned).package
    assert imported is not None and imported.about[Language.SV].instructions, (
        "from the planning file"
    )
    saved = save(planned, {"instructions": "text", "language": "sv", "text": "Kör lugnt."})
    assert saved.status_code == 200, saved.text
    package = draft(planned).package
    assert package is not None and package.about[Language.SV].instructions == "Kör lugnt."
    # The PDF: kept by its checksum, and in the package as an attachment.
    sent = planned.post(f"{API}/meets/{MEET}/instructions.pdf?name=Allmänt.pdf", content=PDF)
    assert sent.status_code == 200, sent.text
    package = draft(planned).package
    assert package is not None
    (pdf,) = [a for a in package.attachments if a.kind == AttachmentKind.INSTRUCTIONS]
    assert (pdf.filename, pdf.size, pdf.media_type) == ("Allmänt.pdf", len(PDF), "application/pdf")
    read = TestClient(planned.app).get(f"{API}/meets/{MEET}/attachments/{pdf.id}")
    assert (read.status_code, read.content) == (200, PDF), "everyone may look at the plan"
    # A new PDF replaces the one before; the text stays.
    planned.post(f"{API}/meets/{MEET}/instructions.pdf", content=OTHER_PDF)
    package = draft(planned).package
    assert package is not None
    assert [a.size for a in package.attachments if a.kind == AttachmentKind.INSTRUCTIONS] == [
        len(OTHER_PDF)
    ]
    assert package.about[Language.SV].instructions == "Kör lugnt."
    # Taken away, and only a PDF is a PDF.
    assert save(planned, {"instructions": "pdf", "pdf": None}).status_code == 200
    package = draft(planned).package
    assert package is not None and package.attachments == []
    assert (
        planned.post(f"{API}/meets/{MEET}/instructions.pdf", content=b"<html>").status_code == 415
    )


def test_only_the_planner_adds_them(planned: TestClient) -> None:
    looker = TestClient(planned.app)
    assert looker.post(f"{API}/meets/{MEET}/instructions.pdf", content=PDF).status_code == 401
    refused = looker.post(
        f"{API}/meets/{MEET}/changes",
        json={"revision": 0, "changes": [{"instructions": "text", "text": "x"}]},
    )
    assert refused.status_code == 401


def test_lokforaren_shows_what_the_version_has(planned: TestClient) -> None:
    """LOK-34: with the version, the text and the PDF reach Drift, and the drivers read them."""
    save(planned, {"instructions": "text", "language": "en", "text": "Drive gently."})
    planned.post(f"{API}/meets/{MEET}/instructions.pdf", content=PDF)
    assert planned.post(f"{API}/meets/{MEET}/versions").status_code == 201
    assert planned.post(DRIFT + "/start", json={"meet": MEET, "version": 1}).status_code == 201
    looker = TestClient(planned.app)
    shown = contract.Instructions.model_validate(looker.get(DRIFT + "/drivers/instructions").json())
    assert shown.text["en"] == "Drive gently." and shown.text["sv"]
    assert shown.pdf == DRIFT + "/drivers/instructions.pdf"
    read = looker.get(DRIFT + "/drivers/instructions.pdf")
    assert (read.status_code, read.content, read.headers["content-type"]) == (
        200,
        PDF,
        "application/pdf",
    )
    # Värnamo has duties with their difficulty: the list shows them as on the papers' fronts.
    code = planned.get(DRIFT + "/drivers/connect").json()["code"]
    driver = TestClient(planned.app)
    joined = driver.post(
        DRIFT + "/drivers/join", json={"code": code, "name": "Anna", "level": "experienced"}
    )
    assert joined.status_code == 201
    listed = contract.ServiceList.model_validate(driver.get(DRIFT + "/drivers/services").json())
    assert listed.kind == "duty" and listed.services
    assert listed.services[0].level == "experienced"
