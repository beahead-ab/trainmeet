"""Egna urtavlor (F13, H75, ärende 64): a clock pack is checked, the right to use it is
logged, it is an attachment of the meet package, and the clock screen draws custom:<id>
in light and in dark. No finished face from the old code is included.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts import planning, screen
from contracts.meet import AttachmentKind
from core.clock_pack import ClockPackError, read_pack, read_packs
from core.tests.test_clock_pack import SQUARE, bundle, pack
from hub.tests.test_planering import API, DRIFT, MEET, PIN, new_hub, upload
from hub.tests.test_screens import join


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


def send(
    hub: TestClient,
    data: bytes,
    *,
    rights: bool = True,
    approved: list[str] | None = None,
    name: str = "mitt-ur.tmclock",
) -> Any:
    if approved is None:
        try:
            approved = [found.id for found in read_packs(data)]
        except ClockPackError:
            approved = ["mitt-ur"]
    query = "&".join(f"approved={face}" for face in approved)
    rights_flag = "true" if rights else "false"
    return hub.post(
        f"{API}/meets/{MEET}/clock-faces?name={name}&rights={rights_flag}&{query}",
        content=data,
    )


def test_a_pack_is_checked_before_it_is_saved(planned: TestClient) -> None:
    before = draft(planned).revision
    files = bundle(
        {"a.tmclock": pack(id="ur-a", name="Ur A"), "b.tmclock": pack(id="ur-b", name="Ur B")}
    )
    seen = planning.ClockCheck.model_validate(
        planned.post(f"{API}/meets/{MEET}/clock-faces/check", content=files).json()
    )
    assert [(item.id, item.name, item.replaces) for item in seen.packs] == [
        ("ur-a", "Ur A", False),
        ("ur-b", "Ur B", False),
    ]
    assert seen.packs[0].layers["dial"].startswith("data:image/svg+xml;base64,")
    checked = draft(planned)
    assert checked.revision == before
    assert checked.package is not None and checked.package.clock.faces == []


def test_the_right_is_required_and_logged_and_only_the_approved_faces_are_kept(
    planned: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="planering.klocka")
    files = bundle({"a.tmclock": pack(id="ur-a"), "b.tmclock": pack(id="ur-b", name="Ur B")})
    refused = send(planned, files, rights=False, approved=["ur-b"])
    assert refused.status_code == 400 and "Intyga rätten" in refused.json()["detail"]
    untouched = draft(planned).package
    assert untouched is not None and untouched.clock.faces == []
    empty = send(planned, files, approved=[])
    assert empty.status_code == 400
    missing = send(planned, files, approved=["ur-c"])
    assert missing.status_code == 400 and "ur-c" in missing.json()["detail"]
    kept = send(planned, files, approved=["ur-b"], name="klockor.zip")
    assert kept.status_code == 200, kept.text
    package = draft(planned).package
    assert package is not None
    assert [a.id for a in package.attachments if a.kind == AttachmentKind.CLOCK_FACE] == ["ur-b"]
    logged = [record for record in caplog.records if "clock_face.uploaded" in record.message]
    assert len(logged) == 1
    assert "rights_confirmed=true" in logged[0].message
    assert "ur-b" in logged[0].message
    listed = planned.get(f"{API}/meets/{MEET}/clock-faces").json()
    stamps = planning.ClockStamps.model_validate(listed)
    assert stamps.faces[0].by == "pin"
    assert stamps.faces[0].id == "ur-b" and stamps.faces[0].at
    looker = TestClient(planned.app)
    assert looker.post(f"{API}/meets/{MEET}/clock-faces", content=files).status_code == 401


def test_a_bad_pack_is_refused_and_the_same_id_replaces_it(planned: TestClient) -> None:
    broken = send(planned, pack({"hour.svg": SQUARE.format("<script/>")}))
    assert broken.status_code == 400 and "<script>" in broken.json()["detail"]
    empty = draft(planned).package
    assert empty is not None and empty.clock.faces == []
    first = send(planned, pack())
    assert first.status_code == 200, first.text
    second = send(planned, pack(version="1.1"))
    assert second.status_code == 200, second.text
    package = draft(planned).package
    assert package is not None
    faces = [a for a in package.attachments if a.kind == AttachmentKind.CLOCK_FACE]
    assert len(faces) == 1 and faces[0].id == "mitt-ur"
    body = planned.get(f"{API}/meets/{MEET}/attachments/{faces[0].id}").content
    assert read_pack(body).version == "1.1"
    warned = send(planned, pack({"dial.svg": SQUARE.format("<text>12</text>")}))
    assert warned.status_code == 200, warned.text
    listed = planning.ClockStamps.model_validate(
        planned.get(f"{API}/meets/{MEET}/clock-faces").json()
    )
    assert any("text ritas" in warning for warning in listed.faces[0].warnings)


def test_a_meet_holds_at_most_twenty_faces_and_a_zip_that_does_not_fit_saves_none(
    planned: TestClient,
) -> None:
    many = {f"ur-{number}.tmclock": pack(id=f"ur-{number}") for number in range(20)}
    assert send(planned, bundle(many), name="alla.zip").status_code == 200
    package = draft(planned).package
    assert package is not None and len(package.clock.faces) == 20
    extra = send(planned, bundle({"a.tmclock": pack(id="ny-a"), "b.tmclock": pack(id="ny-b")}))
    assert extra.status_code == 409 and "Ta bort några först" in extra.json()["detail"]
    assert len(draft(planned).package.clock.faces) == 20  # type: ignore[union-attr]
    assert send(planned, pack(id="ur-3", version="2")).status_code == 200


def test_the_style_is_custom_and_removing_it_returns_to_analog(planned: TestClient) -> None:
    assert send(planned, pack()).status_code == 200
    unknown = planned.post(f"{API}/meets/{MEET}/clock-style", json={"style": "custom:finns-inte"})
    assert unknown.status_code == 404
    chosen = planned.post(f"{API}/meets/{MEET}/clock-style", json={"style": "custom:mitt-ur"})
    assert chosen.status_code == 200, chosen.text
    assert draft(planned).package.clock.styles[0] == "custom:mitt-ur"  # type: ignore[union-attr]
    removed = planned.post(f"{API}/meets/{MEET}/clock-faces/remove", json={"face": "mitt-ur"})
    assert removed.status_code == 200, removed.text
    package = draft(planned).package
    assert package is not None
    assert package.clock.faces == [] and package.clock.styles[0] == "analog"
    assert planned.get(f"{API}/meets/{MEET}/clock-faces").json()["faces"] == []


def test_the_clock_screen_draws_the_face_in_light_and_in_dark(planned: TestClient) -> None:
    dark = SQUARE.format('<circle cx="100" cy="100" r="96" fill="#15181e"/>')
    data = pack({"dial-dark.svg": dark}, dark={"dial": "dial-dark.svg"})
    assert send(planned, data).status_code == 200
    chosen = planned.post(f"{API}/meets/{MEET}/clock-style", json={"style": "custom:mitt-ur"})
    assert chosen.status_code == 200
    assert planned.post(f"{API}/meets/{MEET}/versions").status_code == 201
    assert planned.post(DRIFT + "/start", json={"meet": MEET, "version": 1}).status_code == 201
    _client, headers = join(planned)
    planned.post(DRIFT + "/clients/view", json={"client_id": _client, "view": "clock"})
    shown = screen.ClockFaceShow.model_validate(
        TestClient(planned.app).get("/api/screen/clock", headers=headers).json()
    )
    assert shown.style == "custom:mitt-ur"
    assert shown.layers == ["dial", "hour", "minute", "second"]
    assert shown.dark == ["dial"]
    assert shown.motion is not None and shown.motion.second == "sweep"
    layer = TestClient(planned.app).get("/api/screen/clock/mitt-ur/hour", headers=headers)
    assert layer.status_code == 200
    assert layer.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in layer.headers["content-security-policy"]
    assert "default-src 'none'" in layer.headers["content-security-policy"]
    assert layer.content.startswith(b"<svg")
    dark_layer = TestClient(planned.app).get("/api/screen/clock/mitt-ur/dark-dial", headers=headers)
    assert dark_layer.content == dark.encode()
    missing = TestClient(planned.app).get("/api/screen/clock/mitt-ur/dark-hour", headers=headers)
    assert missing.status_code == 404
    assert TestClient(planned.app).get("/api/screen/clock/mitt-ur/hour").status_code == 401
