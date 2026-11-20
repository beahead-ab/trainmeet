"""Anläggning från CAD i Hubbens import (#89 del d3, CAD-11, CAD-12, CAD-14, K4).

The cloud hub lists the planner's assemblies in a pretend CAD and fetches one with the planner's
own access token from a pretend ID; the assembly is kept as it came, read into the plan's places
and the sections' lengths, laid in, and goes with the version as its attachment. A meet's Pi
following the cloud gets it with the version and has it without CAD. Without CAD or without a
login with ID, the way is grey with the reason.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
from fastapi.testclient import TestClient

from contracts import planning, sync
from contracts.cad import MeetAssembly
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.cad_access import NO_CAD, NO_LOGIN
from hub.tests.test_id_login import PIN, PUBLIC, back, to_id
from hub.tests.test_id_roles import AUTUMN, SETTINGS, PretendIdApi
from hub.tests.test_synk import wire
from integrationer import cad_example
from integrationer.tests.test_cad_assembly import TOKEN, pretend_cad
from integrationer.tests.test_planning_json import plan

API = "/api/planering/1"
CAD = "http://cad.invalid"
ATTACHMENT = "cad-anlaggning"


class PretendIdWithAccess(PretendIdApi):
    """ID that also gives the person an access token for the client hub, and renews it."""

    renewed: int = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/realms/trainmeet/protocol/openid-connect/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if form.get("grant_type") == "authorization_code":
                return httpx.Response(
                    200,
                    json={
                        "id_token": self.token(),
                        "access_token": TOKEN,
                        "refresh_token": "fornyelse",
                        "expires_in": 1,
                    },
                )
            if form.get("grant_type") == "refresh_token":
                assert form["refresh_token"] == "fornyelse"
                self.renewed += 1
                return httpx.Response(200, json={"access_token": TOKEN, "expires_in": 300})
        return super().handle(request)


def small_plan() -> bytes:
    """Tellurian's small plan with the places renamed to the synthetic assembly's stations: one
    section from Aby to Cby, with Bby between."""
    text = json.dumps(plan(), ensure_ascii=False)
    for old, new in (
        ("Charlottendal", "Aby"),
        ('"Cda"', '"Aby"'),
        ("Vagnsta", "Bby"),
        ('"Vst"', '"Bby"'),
        (" Salsborg ", "Cby"),
        ('"Sal"', '"Cby"'),
    ):
        text = text.replace(old, new)
    return text.encode()


def cloud_with(
    tmp_path: Path, pretend: PretendIdApi, seen: list[httpx.Request], cad: str | None = CAD
) -> tuple[TestClient, TestClient]:
    made = create_app(
        BuildInfo(version="0.1.0"),
        preview_db=tmp_path / "moln" / "p.db",
        id_settings=SETTINGS,
        id_http=httpx.Client(transport=httpx.MockTransport(pretend.handle)),
        cad_address=cad,
        cad_http=pretend_cad(seen),
    )
    owner = TestClient(made, base_url=PUBLIC, follow_redirects=False)
    assert owner.post("/api/hub/setup", json={"name": "Molnet", "pin": PIN}).status_code == 201
    person = TestClient(made, base_url=PUBLIC, follow_redirects=False)
    assert back(person, to_id(person, pretend)).status_code == 303
    return owner, person


def planned_meet(person: TestClient) -> str:
    made = person.post(
        f"{API}/meets",
        json={
            "name": "Höst",
            "id_meet": str(AUTUMN),
            "first_date": "2026-05-01",
            "last_date": "2026-05-02",
        },
    )
    assert made.status_code == 201, made.text
    meet = str(made.json()["meet"]["id"])
    read = person.post(
        f"{API}/meets/{meet}/sources",
        params={"name": "plan.json"},
        content=small_plan(),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert read.status_code == 201, read.text
    applied = person.post(f"{API}/meets/{meet}/sources/{read.json()['source']['id']}/apply")
    assert applied.status_code == 200, applied.text
    return meet


def test_the_planner_adds_the_assembly_from_cad_and_bana_gets_its_lengths(
    tmp_path: Path,
) -> None:
    pretend = PretendIdWithAccess()
    pretend.roles = {str(AUTUMN): ["organizer"]}
    seen: list[httpx.Request] = []
    owner, person = cloud_with(tmp_path, pretend, seen)
    meet = planned_meet(person)

    listed = planning.CadAssemblies.model_validate(person.get(f"{API}/meets/{meet}/cad").json())
    assert listed.available and listed.reason is None
    assert [(a.name, a.modules, a.revision) for a in listed.assemblies] == [
        ("Provträffens anläggning", 6, 3)
    ]
    # The access token had run out: ID renewed it before CAD was asked, never shown.
    assert pretend.renewed == 1
    assert {r.headers["authorization"] for r in seen} == {f"Bearer {TOKEN}"}
    # The hub's PIN is no person in ID: grey, with the reason.
    grey = planning.CadAssemblies.model_validate(owner.get(f"{API}/meets/{meet}/cad").json())
    assert (grey.available, grey.reason) == (False, NO_LOGIN)

    asked = person.post(f"{API}/meets/{meet}/cad/{cad_example.ASSEMBLY}")
    assert asked.status_code == 201, asked.text
    preview = planning.ImportPreview.model_validate(asked.json())
    assert preview.source.kind == planning.SourceKind.CAD_ASSEMBLY
    kept_as_it_came = hashlib.sha256(cad_example.assembly_bytes()).hexdigest()
    assert preview.source.sha256 == kept_as_it_came
    assert preview.lengths == 1 and preview.places.changed == 0
    draft = planning.Draft.model_validate(
        person.post(f"{API}/meets/{meet}/sources/{preview.source.id}/apply").json()
    )
    # Aby – Cby: 2 500 mm of line to Bby, 2 000 mm through it, 1 200 mm on to Cby.
    [length] = draft.lengths
    assert (length.length, length.prototype, length.tracks) == (5700, 495.9, 1)
    facts = {f.ref: f for f in draft.facts}
    assert facts[f"section:{length.section}.length"].origins[0].source == preview.source.id
    assert {r for r in facts if r.endswith(".modules")} == {
        f"place:{p.id}.modules" for p in (draft.package.places if draft.package else [])
    }
    # The same assembly again changes nothing.
    again = planning.ImportPreview.model_validate(
        person.post(f"{API}/meets/{meet}/cad/{cad_example.ASSEMBLY}").json()
    )
    assert again.lengths == 0

    # Published, the version carries the assembly with its modules (CAD-12).
    published = owner.post(f"{API}/meets/{meet}/versions")
    assert published.status_code == 201, published.text
    package = person.get(f"{API}/meets/{meet}/versions/1").json()
    assert ATTACHMENT in {a["id"] for a in package["attachments"]}
    file = person.get(f"{API}/meets/{meet}/versions/1/attachments/{ATTACHMENT}")
    assert file.status_code == 200 and file.content == cad_example.assembly_bytes()

    # A meet's Pi follows the cloud: the version and the assembly come down; CAD is not asked.
    asked_before = len(seen)
    pi = TestClient(
        create_app(
            BuildInfo(version="0.1.0"),
            preview_db=tmp_path / "pi" / "p.db",
            sync_call=wire(owner),
        )
    )
    assert pi.post("/api/hub/setup", json={"name": "Pi:n", "pin": PIN}).status_code == 201
    code = owner.post(f"/api/sync/1/meets/{meet}/code")
    assert code.status_code == 201, code.text
    linked = pi.post(
        "/api/hub/cloud",
        json={"address": "http://moln", "code": sync.LinkCode.model_validate(code.json()).code},
    )
    assert linked.status_code == 200, linked.text
    [link] = [sync.CloudLink.model_validate(c) for c in linked.json()]
    assert (link.versions, link.problem) == (1, None)
    down = pi.get(f"{API}/meets/{meet}/versions/1/attachments/{ATTACHMENT}")
    assert down.status_code == 200 and down.content == cad_example.assembly_bytes()
    kept = MeetAssembly.model_validate_json(down.content)
    assert [m.number for m in kept.modules] == [f"M-00{n}" for n in range(1, 7)]
    assert len(seen) == asked_before, "the Pi never asks CAD"
    # Only a Pi that follows the meet gets the file, and only a file a version names.
    stranger = owner.get(f"/api/sync/1/meets/{meet}/files/{'0' * 64}")
    assert stranger.status_code == 401


def test_without_cad_the_way_is_grey_and_cad_saying_no_is_said(tmp_path: Path) -> None:
    pretend = PretendIdWithAccess()
    pretend.roles = {str(AUTUMN): ["organizer"]}
    seen: list[httpx.Request] = []
    _, person = cloud_with(tmp_path, pretend, seen, cad=None)
    meet = planned_meet(person)
    grey = planning.CadAssemblies.model_validate(person.get(f"{API}/meets/{meet}/cad").json())
    assert (grey.available, grey.reason, grey.assemblies) == (False, NO_CAD, [])
    refused = person.post(f"{API}/meets/{meet}/cad/{cad_example.ASSEMBLY}")
    assert refused.status_code == 409 and refused.json()["detail"] == NO_CAD
    assert seen == []


def test_an_assembly_cad_does_not_give_is_refused_with_cads_reason(tmp_path: Path) -> None:
    pretend = PretendIdWithAccess()
    pretend.roles = {str(AUTUMN): ["organizer"]}
    seen: list[httpx.Request] = []
    _, person = cloud_with(tmp_path, pretend, seen)
    meet = planned_meet(person)
    unseen = person.post(f"{API}/meets/{meet}/cad/00000000-0000-4000-8000-000000000bad")
    assert unseen.status_code == 422 and "syns inte" in unseen.json()["detail"]
    gone = person.post(f"{API}/meets/{meet}/cad/00000000-0000-4000-8000-000000000123")
    assert gone.status_code == 404
    # Someone who may not plan the meet gets nothing from CAD.
    pretend.roles = {}
    assert person.get(f"{API}/meets/{meet}/cad").status_code in (401, 403)
    assert person.post(f"{API}/meets/{meet}/cad/{cad_example.ASSEMBLY}").status_code in (401, 403)


def test_the_test_hub_reaches_cad_beside_it_and_the_pretend_pi_never_does() -> None:
    """HUB_CAD in the test environment: CAD's container on compose's network, for the test hub
    only. The Låtsas-Pi gets the modules with the versions (CAD-12, CAD-14)."""
    compose = (Path(__file__).resolve().parents[2] / "deploy/testmiljo/compose.yaml").read_text()
    hub = compose.split("\n  hub:\n")[1].split("\n\n")[0]
    pi = compose.split("\n  pi:\n")[1].split("\n\n")[0]
    assert "HUB_CAD: http://cad:8080" in hub
    assert "HUB_CAD" not in pi
