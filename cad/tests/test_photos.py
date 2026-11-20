"""Foto och kontroll's service (#89 del c1): the upload and the intake, the job and its key,
the price through ID's meter (reserve, draw, give back, own AI), the transcripts, the questions
without AI, the storage and its 100 MB, the original's 30 days, the training opt-in, and the
rights. The chain runs on a synthetic photo (cad/bildkedjan/syntetisk.py)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any
from uuid import UUID

import numpy as np
import pytest

from cad.bildkedjan import intake, syntetisk
from cad.bildkedjan.corners import clockwise
from cad.tests.conftest import API, CLUB, A, B, World

PHOTOS = f"{API}/photos"


@cache
def station() -> syntetisk.Photo:
    return syntetisk.take(syntetisk.station_scene(), syntetisk.Shot(size=(3200, 2400), fill=0.8))


@cache
def straight() -> syntetisk.Photo:
    return syntetisk.take(syntetisk.straight_scene(), syntetisk.Shot(size=(3000, 2250)))


def _form(data: dict[str, Any], *photos: bytes) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
    files: list[tuple[str, Any]] = [("data", (None, json.dumps(data), "application/json"))]
    files += [("images", (f"foto-{i}.jpg", photo, "image/jpeg")) for i, photo in enumerate(photos)]
    return {}, files


def upload(world: World, person: UUID, photo: bytes, **data: Any) -> dict[str, Any]:
    start = {"name": "Fotomodul", "scale": "H0", "kind": "straight", "width": 600, **data}
    _, files = _form(start, photo)
    answer = world.as_(person).post(PHOTOS, files=files)
    assert answer.status_code == 201, answer.text
    found: dict[str, Any] = answer.json()
    return found


def on_preview(job: dict[str, Any], photo: syntetisk.Photo) -> float:
    """The corners come in the preview's pixels."""
    return float(job["preview"]["width"]) / float(photo.pixels.shape[1])


def kant1_of(job: dict[str, Any], photo: syntetisk.Photo) -> tuple[list[list[float]], int]:
    """The corners as found, and the side from A at Kant 1 to B at Kant 1, as the truth has it."""
    corners = np.array(job["corners"]["corners"], np.float64)
    ordered = clockwise(corners)
    truth = np.array(photo.corners[0]) * on_preview(job, photo)
    first = int(np.argmin(np.linalg.norm(ordered - truth, axis=1)))
    return ordered.tolist(), first


def read(
    world: World, person: UUID, job: dict[str, Any], photo: syntetisk.Photo, **ask: Any
) -> dict[str, Any]:
    corners, kant1 = kant1_of(job, photo)
    body = {"corners": corners, "kant1": kant1, "ai": False, "consent": False, **ask}
    answer = world.as_(person).post(f"{PHOTOS}/{job['id']}/read", json=body)
    assert answer.status_code == 200, answer.text
    world.app.state.photos.work()
    done = world.as_(person).get(f"{PHOTOS}/{answer.json()['id']}")
    assert done.status_code == 200
    found: dict[str, Any] = done.json()
    return found


def truth_answer(scene: syntetisk.Scene, pairs: set[tuple[str, str]]) -> Any:
    def answer(prompt: str) -> str:
        return json.dumps(
            {"forbindelser": sorted([list(p) for p in pairs]), "noder": {}, "osakert": ""}
        )

    del scene
    return answer


def test_the_upload_takes_out_the_metadata_and_finds_the_corners(world: World) -> None:
    photo = straight()
    assert "GPS" in intake.has_metadata(photo.jpeg)
    job = upload(world, A.id, photo.jpeg, width=480)
    assert job["state"] == "corners"
    assert job["corners"]["found"]
    found = np.array(job["corners"]["corners"], np.float64) / on_preview(job, photo)
    truth = clockwise(np.array(photo.corners))
    assert np.abs(found - truth).max() < 4  # the lens is taken out when it is read
    stored = world.as_(A.id).get(job["photos"][0]["url"])
    assert stored.status_code == 200
    assert intake.has_metadata(stored.content) == []
    module = world.as_(A.id).get(f"{API}/modules/{job['module']}").json()
    assert module["name"] == "Fotomodul"
    assert module["shape"]["width"] == 480


def test_a_photo_read_without_ai_gives_a_track_plan_with_questions(world: World) -> None:
    photo = straight()
    job = upload(world, A.id, photo.jpeg, width=480, length=1200)
    done = read(world, A.id, job, photo)
    assert done["state"] == "done", done["message"]
    assert done["cost"] == 0
    assert done["price"]["why"] == "no_ai"
    keys = [q["key"] for q in done["questions"]]
    assert "forbindelser" in keys
    module = world.as_(A.id).get(f"{API}/modules/{job['module']}").json()
    assert module["version"] == 2
    assert module["drawing"]["source"] == "photo"
    assert module["photographed"]
    pieces = module["graph"]["pieces"]
    assert len(pieces) == 2
    assert all(
        p["origin"]["source"] == "photo" and p["origin"]["certainty"] != "confirmed" for p in pieces
    )
    open_ = [c for c in module["checks"] if not c["answer"]]
    assert any(c["kind"] == "question" for c in open_)
    assert module["photo"]["measure_url"]
    # The answer makes a new version; the question is gone from Att kolla.
    answered = world.as_(A.id).post(
        f"{PHOTOS}/{job['id']}/answers", json={"answers": [{"key": "forbindelser", "answer": "ja"}]}
    )
    assert answered.status_code == 200, answered.text
    module = world.as_(A.id).get(f"{API}/modules/{job['module']}").json()
    assert module["version"] == 3
    assert not [c for c in module["checks"] if c["kind"] == "question" and not c["answer"]]
    # The ids are kept from the version before (CAD-20).
    before = world.as_(A.id).get(f"{API}/modules/{job['module']}/versions/2").json()
    assert {p["id"] for p in before["graph"]["pieces"]} == {
        p["id"] for p in module["graph"]["pieces"]
    }


def test_ai_through_the_meter_costs_12_once_and_the_same_job_is_free(world: World) -> None:
    photo = straight()
    world.id.answer = truth_answer(syntetisk.straight_scene(), {("A1", "B1"), ("A2", "B2")})
    job = upload(world, A.id, photo.jpeg, width=480, length=1200)
    refused = world.as_(A.id).post(
        f"{PHOTOS}/{job['id']}/read",
        json={"corners": job["corners"]["corners"], "kant1": 0, "ai": True},
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "consent_required"
    consent = world.as_(A.id).get(f"{PHOTOS}/consent", params={"module": job["module"]}).json()
    assert consent["available"] and consent["price"] == 12
    assert "Claude" in consent["sent_to"]
    start = world.id.balance
    done = read(world, A.id, job, photo, ai=True, consent=True)
    assert done["state"] == "done", done["message"]
    assert done["cost"] == 12
    assert world.id.balance == start - 12
    assert world.id.reads == 1
    assert not [q for q in done["questions"] if q["topology"]]
    assert any(f["key"] == "forbindelser" and f["certainty"] == "certain" for f in done["facts"])
    # The same photo, input and versions: the stored job, no new reading and nothing drawn.
    again = upload(world, A.id, photo.jpeg, module=job["module"])
    same = read(world, A.id, again, photo, ai=True)
    assert same["id"] == done["id"]
    assert world.id.reads == 1
    assert world.id.balance == start - 12


def test_an_unreadable_answer_gives_everything_back_and_the_owner_is_asked(world: World) -> None:
    photo = straight()
    world.id.answer = lambda prompt: "Jag tror att alla spår hänger ihop."
    job = upload(world, A.id, photo.jpeg, width=480, length=1200)
    start = world.id.balance
    done = read(world, A.id, job, photo, ai=True, consent=True)
    assert done["state"] == "done"
    assert done["cost"] == 0
    assert world.id.balance == start
    assert "AI:n kunde inte läsa fotot" in (done["message"] or "")
    assert any(q["key"] == "forbindelser" for q in done["questions"])


def test_own_ai_costs_nothing(world: World) -> None:
    photo = straight()
    world.id.own_ai = "egen-modell"
    world.id.answer = truth_answer(syntetisk.straight_scene(), {("A1", "B1"), ("A2", "B2")})
    job = upload(world, A.id, photo.jpeg, width=480, length=1200)
    consent = world.as_(A.id).get(f"{PHOTOS}/consent", params={"module": job["module"]}).json()
    assert consent["price"] == 0 and "egen AI" in consent["sent_to"]
    start = world.id.balance
    done = read(world, A.id, job, photo, ai=True, consent=True)
    assert done["cost"] == 0
    assert world.id.balance == start


def test_no_tokens_reads_without_ai(world: World) -> None:
    photo = straight()
    world.id.balance = 5
    job = upload(world, A.id, photo.jpeg, width=480, length=1200)
    done = read(world, A.id, job, photo, ai=True, consent=True)
    assert done["state"] == "done"
    assert "Saldot räcker inte" in (done["message"] or "")
    assert world.id.balance == 5


def test_rights_only_the_owner_reads_and_others_see_nothing(world: World) -> None:
    photo = straight()
    job = upload(world, A.id, photo.jpeg, width=480, length=1200)
    assert world.as_(B.id).get(f"{PHOTOS}/{job['id']}").status_code == 404
    corners, kant1 = kant1_of(job, photo)
    refused = world.as_(B.id).post(
        f"{PHOTOS}/{job['id']}/read", json={"corners": corners, "kant1": kant1, "ai": False}
    )
    assert refused.status_code == 404
    # A module someone sees but may not change: no upload.
    world.as_(A.id).put(f"{API}/modules/{job['module']}/visibility", json={"visibility": "all"})
    _, files = _form({"module": job["module"]}, photo.jpeg)
    assert world.as_(B.id).post(PHOTOS, files=files).status_code == 403
    assert world.as_(B.id).get(f"{PHOTOS}/{job['id']}").status_code == 200


def test_a_club_editor_reads_without_ai_only(world: World) -> None:
    world.id.join(A.id, CLUB, "Provklubben", "admin")
    world.id.join(B.id, CLUB, "Provklubben", "member")
    photo = straight()
    job = upload(world, A.id, photo.jpeg, width=480, length=1200, owner=str(CLUB))
    world.id.module_roles[(B.id, job["module"])] = ["editor"]
    corners, kant1 = kant1_of(job, photo)
    refused = world.as_(B.id).post(
        f"{PHOTOS}/{job['id']}/read",
        json={"corners": corners, "kant1": kant1, "ai": True, "consent": True},
    )
    assert refused.status_code == 403


def test_the_storage_counts_measuring_images_and_kept_originals(world: World) -> None:
    photo = straight()
    job = upload(world, A.id, photo.jpeg, width=480, length=1200)
    before = world.as_(A.id).get(f"{API}/storage").json()
    assert before["used"] == 0
    assert before["waiting"] > 0
    assert before["limit"] == 100 * 1024 * 1024
    read(world, A.id, job, photo)
    after = world.as_(A.id).get(f"{API}/storage").json()
    assert after["used"] > 0
    kept = world.as_(A.id).put(f"{API}/modules/{job['module']}/photo", json={"keep_original": True})
    assert kept.status_code == 200
    assert kept.json()["keep_original"]
    assert world.as_(A.id).get(f"{API}/storage").json()["used"] > after["used"]


def test_the_storage_is_full_at_100_mb(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from cad import photos

    monkeypatch.setattr(photos, "STORAGE_LIMIT", 1000)
    photo = straight()
    job = upload(world, A.id, photo.jpeg, width=480, length=1200)
    done = read(world, A.id, job, photo)
    assert done["state"] == "failed"
    assert "Lagringen för modulfoton är full" in done["message"]


def test_the_original_goes_at_approval_or_after_30_days(world: World) -> None:
    photo = straight()
    job = upload(world, A.id, photo.jpeg, width=480, length=1200)
    done = read(world, A.id, job, photo)
    module = world.as_(A.id).get(f"{API}/modules/{job['module']}").json()
    until = datetime.fromisoformat(module["photo"]["original_until"])
    assert timedelta(days=29) < until - datetime.now(UTC) <= timedelta(days=30)
    world.as_(A.id).post(
        f"{PHOTOS}/{job['id']}/answers", json={"answers": [{"key": "forbindelser", "answer": "ja"}]}
    )
    module = world.as_(A.id).get(f"{API}/modules/{job['module']}").json()
    for check in module["checks"]:
        if not check["answer"]:
            choice = next(c for c in check["choices"] if c.get("closes", True))
            world.as_(A.id).post(
                f"{API}/modules/{job['module']}/drawing/save",
                json={
                    "base": module["version"],
                    "operations": [{"op": "answer", "key": check["key"], "answer": choice["id"]}],
                },
            )
            module = world.as_(A.id).get(f"{API}/modules/{job['module']}").json()
    approved = world.as_(A.id).post(
        f"{API}/modules/{job['module']}/drawing/approve",
        json={"base": module["version"], "operations": []},
    )
    assert approved.status_code == 200, approved.text
    assert world.app.state.photos.sweep() >= 1
    module = world.as_(A.id).get(f"{API}/modules/{job['module']}").json()
    assert module["photo"]["original_until"] is None
    assert module["photo"]["measure_url"]
    assert world.as_(A.id).get(done["photos"][0]["url"]).status_code == 404
    # Räkna om needs the original: gone now.
    again = world.as_(A.id).post(f"{PHOTOS}/{job['id']}/recompute")
    assert again.status_code in (200, 422)


def test_training_is_the_owners_yes_with_its_date(world: World) -> None:
    photo = straight()
    job = upload(world, A.id, photo.jpeg, width=480, length=1200)
    module = (
        world.as_(A.id).put(f"{API}/modules/{job['module']}/photo", json={"training": True}).json()
    )
    assert module["training_at"]
    history = world.as_(A.id).get(f"{API}/modules/{job['module']}/history").json()
    assert any("träna" in e["text"] for e in history)
    module = (
        world.as_(A.id).put(f"{API}/modules/{job['module']}/photo", json={"training": False}).json()
    )
    assert module["training_at"] is None


def test_a_bad_photo_is_refused_with_a_reason(world: World) -> None:
    _, files = _form({"width": 500}, b"ftypheic" + b"\x00" * 100)
    answer = world.as_(A.id).post(PHOTOS, files=files)
    assert answer.status_code in (415, 422)
    _, files = _form({"width": 500}, b"%PDF-1.7 ...")
    answer = world.as_(A.id).post(PHOTOS, files=files)
    assert answer.status_code == 415
    assert "PDF" in answer.json()["message"]
