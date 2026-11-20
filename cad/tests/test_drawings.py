"""Ladda upp ritning in CAD (#89 del c4, CAD6, CAD-31): the jobs keyed by the file's checksum,
the price before start, the meter flow for a raster page (reserve, read with hold, check, draw,
or give back), the transcript kept so a page is never transcribed twice, the owner's answers,
the underlay, and TKL's call with the person's access token from TrainMeet ID (TKL18)."""

from __future__ import annotations

import json
import time
from functools import cache
from typing import Any
from uuid import UUID

import jwt

from cad.bildkedjan import ritning_syntetisk as syn
from cad.drawings import Drawings
from cad.tests.conftest import API, ISSUER, A, B, World

DRAWINGS = f"{API}/drawings"


@cache
def drawing_pdf() -> bytes:
    return syn.pdf()


@cache
def drawing_photo() -> bytes:
    return syn.photo()


def _files(data: bytes, name: str, kind: str) -> list[tuple[str, Any]]:
    return [
        ("data", (None, json.dumps({"name": name}), "application/json")),
        ("file", (name, data, kind)),
    ]


def upload(world: World, person: UUID, data: bytes, name: str = "plan.pdf") -> dict[str, Any]:
    kind = "application/pdf" if name.endswith(".pdf") else "image/jpeg"
    answer = world.as_(person).post(DRAWINGS, files=_files(data, name, kind))
    assert answer.status_code == 201, answer.text
    found: dict[str, Any] = answer.json()
    return found


def queue(world: World) -> Drawings:
    found: Drawings = world.app.state.drawings
    return found


def ai_reads(prompt: str) -> str:
    assert "Skriv av all text" in prompt
    return syn.ai_answer()


def test_a_vector_drawing_is_read_free_and_the_same_file_is_the_same_job(world: World) -> None:
    job = upload(world, A.id, drawing_pdf())
    assert job["state"] == "waiting" and job["format"] == "pdf" and job["name"] == "plan.pdf"
    assert [(p["kind"], p["text"], p["tokens"]) for p in job["pages"]] == [("vector", True, 0)]
    assert job["price"] == {
        "tokens": 0,
        "why": "vector",
        "text": "Gratis: sidan har ritade linjer och text, som koden läser utan AI.",
    }
    client = world.as_(A.id)
    read = client.post(f"{DRAWINGS}/{job['id']}/read", json={"page": 1})
    assert read.status_code == 200, read.text
    assert read.json()["state"] == "queued"
    assert queue(world).work() == 1
    done = client.get(f"{DRAWINGS}/{job['id']}").json()
    assert done["state"] == "done" and done["cost"] == 0
    summary = done["read"]["summary"]
    assert (summary["switches"], summary["signals"], summary["boundaries"]) == (5, 7, 9)
    assert done["read"]["graph"]["geometry"] == "schema"
    assert [q["key"] for q in done["read"]["questions"]] == [
        "linje.orange-tunna",
        "symbol.triangle-grona",
    ]
    underlay = client.get(done["read"]["underlay"]["url"])
    assert underlay.status_code == 200 and underlay.headers["content-type"] == "image/png"
    assert underlay.content[:4] == b"\x89PNG"
    # The same file again is the same job, and the same read again costs and reads nothing.
    assert upload(world, A.id, drawing_pdf())["id"] == job["id"]
    again = client.post(f"{DRAWINGS}/{job['id']}/read", json={"page": 1}).json()
    assert again["state"] == "done" and queue(world).work() == 0
    # Nobody else sees it.
    assert world.as_(B.id).get(f"{DRAWINGS}/{job['id']}").status_code == 404


def test_the_answers_change_the_read_at_no_cost(world: World) -> None:
    job = upload(world, A.id, drawing_pdf())
    client = world.as_(A.id)
    client.post(f"{DRAWINGS}/{job['id']}/read", json={"page": 1})
    queue(world).work()
    answered = client.post(
        f"{DRAWINGS}/{job['id']}/answers",
        json={"answers": [{"key": "symbol.triangle-grona", "answer": "knapp"}]},
    )
    assert answered.status_code == 200, answered.text
    read = answered.json()["read"]
    assert read["summary"]["unknown_symbols"] == 0
    asked = {q["key"]: q["answer"] for q in read["questions"]}
    assert asked["symbol.triangle-grona"] == "knapp"
    wrong = client.post(
        f"{DRAWINGS}/{job['id']}/answers",
        json={"answers": [{"key": "symbol.triangle-grona", "answer": "kanske"}]},
    )
    assert wrong.status_code == 422


def test_a_raster_page_is_transcribed_through_the_meter_once(world: World) -> None:
    """R2: 12 tokens for the page with TrainMeets AI, reserved, read with hold and drawn; the
    same page again, for anyone, is the transcript, at no cost."""
    world.id.answer = ai_reads
    job = upload(world, A.id, drawing_photo(), "foto.jpg")
    assert job["format"] == "image" and job["pages"][0]["kind"] == "raster"
    assert job["price"]["tokens"] == 12 and job["price"]["why"] == "first"
    assert job["ai"]["available"] and not job["ai"]["given"]
    client = world.as_(A.id)
    refused = client.post(f"{DRAWINGS}/{job['id']}/read", json={"page": 1, "ai": True})
    assert refused.status_code == 422 and refused.json()["code"] == "consent_required"
    started = client.post(
        f"{DRAWINGS}/{job['id']}/read", json={"page": 1, "ai": True, "consent": True}
    )
    assert started.status_code == 200, started.text
    assert queue(world).work() == 1
    done = client.get(f"{DRAWINGS}/{job['id']}").json()
    assert done["state"] == "done", done["message"]
    assert done["cost"] == 12 and world.id.reads == 1 and world.id.balance == 86 - 12
    assert done["price"]["why"] == "same" and done["ai"]["given"]
    read = done["read"]
    assert read["kind"] == "raster" and read["summary"]["signals"] == 7
    assert (read["price"]["tokens"], read["price"]["why"]) == (12, "first")
    assert all(label["read_by"] == "ai" for label in read["graph"]["labels"])
    held = list(world.id.reservations.values())
    assert [(r["amount"], r["state"], r["drawn"]) for r in held] == [(12, "drawn", 12)]
    assert client.get(read["underlay"]["url"]).headers["content-type"] == "image/jpeg"
    # Another person with the same page: the transcript, never a new reading or a new cost.
    other = upload(world, B.id, drawing_photo(), "samma.jpg")
    assert other["id"] != job["id"]
    world.as_(B.id).post(
        f"{DRAWINGS}/{other['id']}/read", json={"page": 1, "ai": True, "consent": True}
    )
    queue(world).work()
    theirs = world.as_(B.id).get(f"{DRAWINGS}/{other['id']}").json()
    assert theirs["state"] == "done" and theirs["cost"] == 0
    assert theirs["read"]["price"]["why"] == "same"
    assert world.id.reads == 1 and world.id.balance == 86 - 12


def test_an_unreadable_transcription_gives_everything_back(world: World) -> None:
    world.id.answer = lambda prompt: "Jag ser en ritning."
    job = upload(world, A.id, drawing_photo(), "foto.jpg")
    client = world.as_(A.id)
    client.post(f"{DRAWINGS}/{job['id']}/read", json={"page": 1, "ai": True, "consent": True})
    queue(world).work()
    done = client.get(f"{DRAWINGS}/{job['id']}").json()
    assert done["state"] == "done" and done["cost"] == 0
    assert world.id.balance == 86
    assert [r["state"] for r in world.id.reservations.values()] == ["returned"]
    assert "Inget drogs" in done["read"]["notes"][0]
    assert done["read"]["price"]["why"] == "no_ai"
    assert done["read"]["summary"]["labels"] == 0


def test_without_ai_a_raster_page_is_free(world: World) -> None:
    job = upload(world, A.id, drawing_photo(), "foto.jpg")
    client = world.as_(A.id)
    client.post(f"{DRAWINGS}/{job['id']}/read", json={"page": 1, "ai": False})
    queue(world).work()
    done = client.get(f"{DRAWINGS}/{job['id']}").json()
    assert done["cost"] == 0 and done["price"]["why"] == "no_ai" and world.id.reads == 0
    assert done["read"]["summary"]["switches"] == 5


def _tkl_token(world: World, person: UUID, azp: str = "tkl") -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": str(person),
        "azp": azp,
        "iat": now,
        "exp": now + 300,
        "name": "Provare Tkl",
    }
    return jwt.encode(claims, world.id.key, algorithm="RS256", headers={"kid": world.id.kid})


def test_tkl_calls_with_the_persons_access_token_from_id(world: World) -> None:
    """TKL18: Studio's server calls CAD on the person's behalf with ID's access token for the
    app tkl, as Synk takes it; no cookie. Another app's token, or none, is refused."""
    browser = world.browser()
    with browser:
        headers = {"Authorization": f"Bearer {_tkl_token(world, A.id)}"}
        made = browser.post(
            DRAWINGS, files=_files(drawing_pdf(), "plan.pdf", "application/pdf"), headers=headers
        )
        assert made.status_code == 201, made.text
        job = made.json()
        assert browser.get(f"{DRAWINGS}/{job['id']}", headers=headers).status_code == 200
        # It is the person's own job: the same as the browser logged in to CAD as the person.
        assert world.as_(A.id).get(f"{DRAWINGS}/{job['id']}").status_code == 200
        for bad in (_tkl_token(world, A.id, azp="cad"), "inte-en-token"):
            refused = browser.get(
                f"{DRAWINGS}/{job['id']}", headers={"Authorization": f"Bearer {bad}"}
            )
            assert refused.status_code == 401 and refused.json()["code"] == "login"
        assert browser.get(f"{DRAWINGS}/{job['id']}").status_code == 401


def test_the_upload_refuses_what_is_no_drawing(world: World) -> None:
    client = world.as_(A.id)
    answer = client.post(DRAWINGS, files=_files(b"%PDF-1.4 trasig", "x.pdf", "application/pdf"))
    assert answer.status_code == 422 and answer.json()["code"] == "bad_drawing"
    two = client.post(
        DRAWINGS,
        files=[
            ("file", ("a.pdf", drawing_pdf(), "application/pdf")),
            ("file", ("b.pdf", drawing_pdf(), "application/pdf")),
        ],
    )
    assert two.status_code == 422
