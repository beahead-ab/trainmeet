"""Från CAD in Studio through TKL's server (#89 del d2, STUDIO-01, STUDIO-03, CAD-15): TKL asks a
pretend TrainMeet CAD with the person's access token from ID for the person's assemblies, makes
the proposal yellow in Rita, refuses Använd ritningen until the owner has confirmed it, tells
CAD which station took it into use, and a re-import shows the difference. Without CAD's address
or a login with ID the way in is grey, with the reason. Nothing here names a station (RS13)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts.cad import StudioGraph
from contracts.tkl import TklCadImport, TklFromCad, TklRita
from tkl.tests.test_app import API
from tkl.tests.test_app_ritning import ACCESS, PretendCad, studio
from tkl.tests.test_studio_fran_cad import after, before

F = API + "/studio/fran-cad"


@dataclass
class PretendStudio(PretendCad):
    """CAD's Till TKL Studio, pretended: one assembly, its graph, and Används i."""

    graph: StudioGraph = field(default_factory=before)
    used: list[dict[str, Any]] = field(default_factory=list)
    down: bool = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if not path.startswith("/api/cad/1/studio"):
            return super().handle(request)
        self.tokens.append(request.headers.get("authorization", ""))
        if request.headers.get("authorization") != f"Bearer {ACCESS}":
            return httpx.Response(401, json={"code": "login", "message": "Logga in först."})
        if self.down:
            return httpx.Response(503, json={"code": "unavailable", "message": "Inte nu."})
        self.asked.append(f"{request.method} {path}")
        source = self.graph.source.model_dump(mode="json")
        if path == "/api/cad/1/studio":
            return httpx.Response(200, json={"sources": [source]})
        where = f"/api/cad/1/studio/assembly/{self.graph.source.id}"
        if path == where:
            return httpx.Response(200, json=self.graph.model_dump(mode="json"))
        if path == where + "/station" and request.method == "PUT":
            self.used.append(json.loads(request.content))
            return httpx.Response(200, json=source)
        return httpx.Response(404, json={"code": "not_found", "message": "Finns inte."})


@pytest.fixture
def cad() -> PretendStudio:
    return PretendStudio()


def from_cad(client: TestClient) -> TklFromCad:
    answer = client.get(F)
    assert answer.status_code == 200, answer.text
    return TklFromCad.model_validate(answer.json())


def propose(client: TestClient, cad: PretendStudio) -> TklCadImport:
    answer = client.post(f"{F}/assembly/{cad.graph.source.id}/forslag")
    assert answer.status_code == 200, answer.text
    return TklCadImport.model_validate(answer.json())


def confirm_and_use(client: TestClient, rita: TklRita) -> TklRita:
    model = rita.drawing.model
    confirmed = model.model_copy(
        update={
            key: [
                i.model_copy(update={"origin": i.origin.model_copy(update={"confirmed": True})})
                if i.origin is not None
                else i
                for i in getattr(model, key)
            ]
            for key in ("pieces", "switches", "line_exits")
        }
    )
    saved = client.put(
        API + "/studio/rita",
        content=rita.drawing.model_copy(update={"model": confirmed}).model_dump_json(),
    )
    assert saved.status_code == 200, saved.text
    used = client.post(API + "/studio/rita/use")
    assert used.status_code == 200, used.text
    return TklRita.model_validate(used.json())


def test_the_way_in_is_grey_without_cad_or_a_login(tmp_path: Path, cad: PretendStudio) -> None:
    found = from_cad(studio(tmp_path / "a", cad, address=None))
    assert not found.available and found.reason and found.reason.startswith("Från CAD kräver")
    assert "TrainMeet CAD" in found.reason
    client = studio(tmp_path / "b", cad, login=False)
    found = from_cad(client)
    assert found.reason == (
        "Från CAD kräver inloggning med TrainMeet ID: logga in under Inställningar. Rita går "
        "alltid."
    )
    assert client.post(f"{F}/assembly/{cad.graph.source.id}/forslag").status_code == 409
    assert cad.asked == []


def test_the_proposal_is_yellow_and_the_station_is_told_to_cad_when_used(
    tmp_path: Path, cad: PretendStudio
) -> None:
    client = studio(tmp_path, cad)
    found = from_cad(client)
    assert found.available and [s.name for s in found.sources] == ["Exempelanläggning"]
    made = propose(client, cad)
    assert made.diff.first and len(made.diff.added) == 4
    assert made.rita.state == "draft" and made.rita.drawing.proposal
    assert [f.text for f in made.rita.findings if f.problem] == [
        "7 saker ur TrainMeet CAD är inte bekräftade. Bekräfta dem en och en, eller alla med "
        "Bekräfta förslaget."
    ]
    assert from_cad(client).pending == made.link and made.link.revision == 2
    # CAD never makes a station: Använd ritningen waits for the owner's yes.
    refused = client.post(API + "/studio/rita/use")
    assert (
        refused.status_code == 422 and "inte bekräftade" in refused.json()["detail"]["problems"][0]
    )
    assert cad.used == []
    used = confirm_and_use(client, made.rita)
    assert used.state == "in_use"
    assert cad.used == [{"station_id": "exb", "name": "Exempelby", "revision": 2}]
    now = from_cad(client)
    assert now.pending is None and now.link is not None and now.link.registered
    assert set(cad.tokens) == {f"Bearer {ACCESS}"}


def test_a_reimport_shows_the_difference(tmp_path: Path, cad: PretendStudio) -> None:
    client = studio(tmp_path, cad)
    confirm_and_use(client, propose(client, cad).rita)
    cad.graph = after(cad.graph)
    again = propose(client, cad)
    assert not again.diff.first and again.link.revision == 3
    assert [p.text for p in again.diff.added] == ["M-003 Linje bortom · spår 1"]
    assert [p.text for p in again.diff.moved] == ["M-002 Linje · spår 1"]
    assert "3 bekräftade spårbitar" in again.diff.kept
    problems = [f.text for f in again.rita.findings if f.problem]
    assert problems == [
        "3 saker ur TrainMeet CAD är inte bekräftade. Bekräfta dem en och en, eller alla med "
        "Bekräfta förslaget."
    ]
    # Släng utkastet: the station keeps what it had, and its link.
    assert client.delete(API + "/studio/rita").status_code == 200
    found = from_cad(client)
    assert found.pending is None and found.link is not None and found.link.revision == 2


def test_a_source_with_problems_and_cad_that_does_not_answer(
    tmp_path: Path, cad: PretendStudio
) -> None:
    client = studio(tmp_path, cad)
    cad.graph = cad.graph.model_copy(
        update={
            "source": cad.graph.source.model_copy(
                update={"ready": False, "problems": ["Skarven går inte ihop."]}
            )
        }
    )
    refused = client.post(f"{F}/assembly/{cad.graph.source.id}/forslag")
    assert refused.status_code == 409
    assert refused.json()["detail"]["problems"] == ["Skarven går inte ihop."]
    cad.graph = before()
    made = propose(client, cad)
    # CAD is down when the station is taken into use: the link waits, and is told later.
    cad.down = True
    confirm_and_use(client, made.rita)
    assert cad.used == []
    down = from_cad(client)
    assert not down.available and down.reason == "Inte nu."
    assert down.link is not None and not down.link.registered
    cad.down = False
    assert from_cad(client).link.registered  # type: ignore[union-attr]
    assert cad.used == [{"station_id": "exb", "name": "Exempelby", "revision": 2}]
