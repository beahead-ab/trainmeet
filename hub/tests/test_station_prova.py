"""The station protocol and Prova in TKL (#85 del c, STUDIO-12, DRIFT-10): the hub knows each
TKL's level from its connection and takes section.occupancy only at level 3, and a TKL in Prova
connects only to a preview run in Provbanan, never to a real meet."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from contracts import drift, station
from contracts.reasons import Reason
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.station_api import NOT_PREVIEW
from hub.tests.test_planering import DRIFT, hub, planned, run_varnamo  # noqa: F401
from hub.tests.test_station_api import API
from hub.tests.test_tmbox_web import started

SECTION = "s-nby-asn"


def connect(client: TestClient, code: str, **more: Any) -> Any:
    return client.post(
        API + "/connect",
        json={
            "kind": "tkl",
            "name": "TKL Åsen",
            "software": "TKL 0.1.0",
            "wants": ["asn"],
            "code": code,
            **more,
        },
    )


def keyed(client: TestClient, code: str, level: int) -> tuple[str, dict[str, str]]:
    made = connect(client, code, level=level)
    assert made.status_code == 201, made.text
    reply = station.ConnectReply.model_validate(made.json())
    approved = client.post(
        "/api/provbanan/clients/approve", json={"client_id": reply.client_id, "places": ["asn"]}
    )
    assert approved.status_code == 200, approved.text
    key = client.get(f"{API}/connect/{reply.client_id}").json()["key"]
    return reply.client_id, {"Authorization": f"Bearer {key}"}


def occupancy(client: TestClient, client_id: str, headers: dict[str, str]) -> station.Reply:
    seen = client.get(f"{API}/places/asn", headers=headers).json()
    answer = client.post(
        API + "/commands",
        headers=headers,
        json={
            "message_id": uuid4().hex,
            "client_id": client_id,
            "place": "asn",
            "context": seen["context"],
            "action": "section.occupancy",
            "payload": {"section": SECTION, "occupied": True},
        },
    )
    assert answer.status_code == 200, answer.text
    return station.Reply.model_validate(answer.json())


def test_the_hub_takes_occupancy_from_a_tkl_that_connected_at_level_3(tmp_path: Path) -> None:
    """DRIFT-10, KLAR-16: the level comes with the connection and is kept per client; a TKL at
    level 2 is refused with not_level_3, and connecting again at level 3 is enough."""
    client = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))
    code = started(client)
    level_2, headers_2 = keyed(client, code, 2)
    refused = occupancy(client, level_2, headers_2)
    assert (refused.status, refused.reason) == (station.ReplyStatus.REJECTED, Reason.NOT_LEVEL_3)
    level_3, headers_3 = keyed(client, code, 3)
    taken = occupancy(client, level_3, headers_3)
    assert taken.status == station.ReplyStatus.ACCEPTED, taken.message
    here = next(s for s in taken.snapshot.sections if s.section == SECTION)
    assert here.detected


def test_prova_connects_to_a_provbanan_run(tmp_path: Path) -> None:
    """STUDIO-12: a preview run says so, and takes Prova."""
    client = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))
    code = started(client)
    made = connect(client, code, preview_only=True, level=3)
    assert made.status_code == 201, made.text
    reply = station.ConnectReply.model_validate(made.json())
    assert reply.preview and reply.status == station.ApprovalStatus.WAITING
    approve_ = client.post(
        "/api/provbanan/clients/approve", json={"client_id": reply.client_id, "places": ["asn"]}
    )
    assert approve_.status_code == 200
    assert station.ConnectReply.model_validate(
        client.get(f"{API}/connect/{reply.client_id}").json()
    ).preview


def test_prova_is_refused_by_a_real_meet(planned: TestClient) -> None:  # noqa: F811
    """STUDIO-12: the hub's meet running a published version is a real meet. Prova is refused
    with the reason and leaves no client waiting; TKL as usual may still connect."""
    run_varnamo(planned)
    code = drift.Joining.model_validate(planned.get(DRIFT + "/connect").json()).code
    refused = connect(planned, code, preview_only=True)
    assert refused.status_code == 409
    assert refused.json()["detail"] == NOT_PREVIEW
    listed = planned.get(DRIFT + "/clients").json()
    assert not [c for c in listed if c.get("kind") == "tkl"], "no client was made"
    usual = connect(planned, code)
    assert usual.status_code == 201, usual.text
    assert not station.ConnectReply.model_validate(usual.json()).preview
    listed = planned.get(DRIFT + "/clients").json()
    assert [c["kind"] for c in listed if c.get("kind") == "tkl"] == ["tkl"]


def test_the_hubs_own_provbanan_is_a_preview_run(planned: TestClient) -> None:  # noqa: F811
    """The hub running Provbanan as its meet is no real meet either."""
    assert planned.post(DRIFT + "/start", json={"version": 1}).status_code == 201
    code = drift.Joining.model_validate(planned.get(DRIFT + "/connect").json()).code
    made = connect(planned, code, preview_only=True)
    assert made.status_code == 201, made.text
    assert station.ConnectReply.model_validate(made.json()).preview
