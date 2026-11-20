"""Ladda upp ritning in Studio (#89 del c4, STUDIO-01, STUDIO-03, CAD6): TKL's server sends the
drawing to a pretend TrainMeet CAD with the person's access token from ID, passes the price, the
questions and the answers on, turns the read into Rita's draft with everything yellow, and
refuses Använd ritningen until the owner has confirmed it. Without CAD's address or a login with
ID the way in is grey, with the reason. Nothing here names a station (RS13)."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts.tkl import TklRita, TklUpload
from tkl.app import create_app
from tkl.id_login import TklIdSettings
from tkl.store import LOCAL
from tkl.tests.test_app import API, set_up
from tkl.tests.test_studio_ritning import EXAMPLE

CAD = "https://cad.example.test"
U = API + "/studio/ritning"
ACCESS = "atkomst-for-provet"


@dataclass
class PretendCad:
    """TrainMeet CAD's drawings, pretended: one job, read at once with the contract's example."""

    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)

    def job(
        self, ident: str, state: str = "waiting", answers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        read = json.loads(EXAMPLE.read_text(encoding="utf-8")) if state == "done" else None
        if read is not None:
            read["job"] = ident
            for question in read["questions"]:
                question["answer"] = (answers or {}).get(question["key"])
        return {
            "id": ident,
            "name": "plan.pdf",
            "state": state,
            "progress": 100 if state == "done" else 0,
            "step": "Klart" if state == "done" else "Väntar på Läs",
            "created_at": datetime(2026, 11, 20, tzinfo=UTC).isoformat(),
            "format": "pdf",
            "pages": [
                {
                    "number": 1,
                    "kind": "vector",
                    "width": 842,
                    "height": 595,
                    "text": True,
                    "tokens": 0,
                }
            ],
            "page": 1,
            "price": {"tokens": 0, "why": "vector", "text": "Gratis."},
            "ai": {
                "available": True,
                "given": False,
                "version": "1",
                "sent_to": "TrainMeets AI",
                "text": "Sidan skickas till AI:n.",
            },
            "read": read,
            "cost": 0,
            "chain": "1.0.0",
            "key": "0" * 64,
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.tokens.append(request.headers.get("authorization", ""))
        if request.headers.get("authorization") != f"Bearer {ACCESS}":
            return httpx.Response(401, json={"code": "login", "message": "Logga in först."})
        path = request.url.path.removeprefix("/api/cad/1/drawings")
        self.asked.append(f"{request.method} {path or '/'}")
        if request.method == "POST" and path == "":
            assert b'name="file"' in request.content and b"%PDF-" in request.content
            ident = str(uuid.uuid4())
            self.jobs[ident] = self.job(ident)
            return httpx.Response(201, json=self.jobs[ident])
        ident, _, action = path.strip("/").partition("/")
        if ident not in self.jobs:
            return httpx.Response(404, json={"code": "not_found", "message": "Finns inte."})
        if action == "read":
            self.jobs[ident] = self.job(ident, "done")
        elif action == "answers":
            given = {a["key"]: a["answer"] for a in json.loads(request.content)["answers"]}
            self.jobs[ident] = self.job(ident, "done", given)
        elif action == "underlay":
            return httpx.Response(
                200, content=b"\x89PNG\r\n\x1a\nprov", headers={"content-type": "image/png"}
            )
        return httpx.Response(200, json=self.jobs[ident])


def studio(
    tmp_path: Path, cad: PretendCad, *, address: str | None = CAD, login: bool = True
) -> TestClient:
    settings = TklIdSettings(
        issuer="https://id.example.test/realms/trainmeet",
        internal="http://id:8080/realms/trainmeet",
        public_url="http://localhost:8090",
    )
    app = create_app(
        tmp_path,
        http=lambda: httpx.Client(transport=httpx.MockTransport(cad.handle)),
        discover=lambda: [],
        id_settings=settings,
        cad=address,
    )
    client = TestClient(app)
    assert set_up(client).status_code == 201
    if login:
        app.state.store.keep_account(
            LOCAL, str(uuid.uuid4()), "Provare", ACCESS, None, time.time() + 3600
        )
    return client


def upload(client: TestClient, response: Any) -> TklUpload:
    assert response.status_code == 200, response.text
    return TklUpload.model_validate(response.json())


@pytest.fixture
def cad() -> PretendCad:
    return PretendCad()


def test_the_way_in_is_grey_without_cad_or_a_login(tmp_path: Path, cad: PretendCad) -> None:
    client = studio(tmp_path / "a", cad, address=None)
    found = upload(client, client.get(U))
    assert not found.available and found.reason and "TrainMeet CAD" in found.reason
    refused = client.post(U + "?namn=plan.pdf", content=b"%PDF-1.4")
    assert refused.status_code == 409
    client = studio(tmp_path / "b", cad, login=False)
    found = upload(client, client.get(U))
    assert not found.available and found.reason and "TrainMeet ID" in found.reason
    no_id = TestClient(create_app(tmp_path / "c", discover=lambda: [], cad=CAD))
    assert set_up(no_id).status_code == 201
    found = upload(no_id, no_id.get(U))
    assert (
        found.reason
        == "Ladda upp ritning kräver internet och inloggning med TrainMeet ID. Rita går alltid."
    )
    assert cad.asked == []


def test_upload_read_answer_and_the_proposal_in_rita(tmp_path: Path, cad: PretendCad) -> None:
    client = studio(tmp_path, cad)
    found = upload(client, client.get(U))
    assert found.available and found.job is None
    made = upload(
        client,
        client.post(
            U + "?namn=plan.pdf",
            content=b"%PDF-1.4 ritningen",
            headers={"content-type": "application/pdf"},
        ),
    )
    assert made.job is not None and made.job.state == "waiting" and made.job.price.tokens == 0
    job = made.job.id
    read = upload(client, client.post(f"{U}/{job}/read", json={"page": 1, "ai": False}))
    assert read.job is not None and read.job.read is not None
    assert read.underlay == f"{U}/{job}/underlag"
    assert [q.key for q in read.job.read.questions] == [
        "linje.orange-tunna",
        "symbol.triangle-grona",
    ]
    # The green triangle has no answer of the code's: the proposal waits for the owner's.
    waiting = client.post(f"{U}/{job}/forslag")
    assert waiting.status_code == 409
    assert waiting.json()["detail"]["problems"] == ["Vad betyder ▲ i den här ritningen?"]
    answered = upload(
        client,
        client.post(
            f"{U}/{job}/answers",
            json={"answers": [{"key": "symbol.triangle-grona", "answer": "knapp"}]},
        ),
    )
    assert answered.job is not None and answered.job.read is not None
    underlay = client.get(f"{U}/{job}/underlag")
    assert underlay.status_code == 200 and underlay.headers["content-type"] == "image/png"
    # Förslaget: Rita's draft, everything yellow, the panel the engine's.
    proposal = client.post(f"{U}/{job}/forslag")
    assert proposal.status_code == 200, proposal.text
    rita = TklRita.model_validate(proposal.json())
    assert rita.state == "draft" and rita.drawing.proposal
    assert {s.name for s in rita.model.signals} == {"11", "12", "13", "14", "15", "21", "22"}
    assert all(not s.origin.confirmed for s in rita.model.switches if s.origin)
    problems = [f.text for f in rita.findings if f.problem]
    assert len(problems) == 1 and "inte bekräftade" in problems[0]
    # Never the station's model without the owner's yes.
    refused = client.post(API + "/studio/rita/use")
    assert refused.status_code == 422
    assert "inte bekräftade" in refused.json()["detail"]["problems"][0]
    confirmed = rita.drawing.model.model_copy(
        update={
            key: [
                i.model_copy(update={"origin": i.origin.model_copy(update={"confirmed": True})})
                if i.origin is not None
                else i
                for i in getattr(rita.drawing.model, key)
            ]
            for key in ("pieces", "switches", "signals", "line_exits")
        }
    )
    saved = client.put(
        API + "/studio/rita",
        content=rita.drawing.model_copy(update={"model": confirmed}).model_dump_json(),
    )
    assert saved.status_code == 200, saved.text
    used = client.post(API + "/studio/rita/use")
    assert used.status_code == 200, used.text
    assert TklRita.model_validate(used.json()).state == "in_use"
    # Every call to CAD carried the person's token, and nothing else.
    assert set(cad.tokens) == {f"Bearer {ACCESS}"}
    assert [a.split(" ")[0] for a in cad.asked].count("POST") == 3


def test_cads_no_is_said_as_cad_said_it(tmp_path: Path, cad: PretendCad) -> None:
    client = studio(tmp_path, cad)
    missing = client.get(f"{U}/{uuid.uuid4()}")
    assert missing.status_code == 404 and missing.json()["detail"] == "Finns inte."
    client.app.state.store.keep_account(LOCAL, "x", "Provare", "fel", None, time.time() + 3600)  # type: ignore[attr-defined]
    again = client.get(f"{U}/{uuid.uuid4()}")
    assert again.status_code == 401 and "Logga in med TrainMeet ID igen" in again.json()["detail"]
