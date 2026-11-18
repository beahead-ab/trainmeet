"""Stationspaketen med ägaren från TrainMeet ID (SYNK-06, SYNK-18, SYNK-30, TKL18, #78).

TKL logs in with ID and saves the station package in the cloud hub with its access token from
ID. The hub takes the owner from the token: signed by ID, not run out, and given to TKL. A pretend
ID signs the tokens (hub/tests/test_id_login.py).
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from hub.app import create_app
from hub.build_info import BuildInfo
from hub.tests.test_id_login import ISSUER, SETTINGS, PretendId
from synk.tests.test_stations import outside, package

ROUTE = "/api/sync/1/stations"


@pytest.fixture
def pretend() -> PretendId:
    return PretendId()


@pytest.fixture
def cloud(tmp_path: Path, pretend: PretendId) -> TestClient:
    made = create_app(
        BuildInfo(version="0.1.0"),
        preview_db=tmp_path / "p.db",
        id_settings=SETTINGS,
        id_http=httpx.Client(transport=httpx.MockTransport(pretend.handle)),
    )
    return TestClient(made)


def token(pretend: PretendId, owner: str, app: str = "tkl", **change: object) -> dict[str, str]:
    now = int(time.time())
    claims = {"iss": ISSUER, "azp": app, "sub": owner, "iat": now, "exp": now + 300, **change}
    signed = jwt.encode(claims, pretend.key, algorithm="RS256", headers={"kid": pretend.kid})
    return {"Authorization": f"Bearer {signed}"}


def test_tkls_token_from_id_names_the_owner(cloud: TestClient, pretend: PretendId) -> None:
    station = outside()["station_id"]
    kim, sara = str(uuid.uuid4()), str(uuid.uuid4())
    saved = cloud.post(
        f"{ROUTE}/{station}/versions?base=0", content=package(), headers=token(pretend, kim)
    )
    assert saved.status_code == 201, saved.text
    behind = cloud.post(
        f"{ROUTE}/{station}/versions?base=0",
        content=package(signals=6),
        headers=token(pretend, kim),
    )
    assert behind.status_code == 409 and behind.headers["TrainMeet-Latest"] == "1"
    mine = cloud.get(f"{ROUTE}/{station}/versions", headers=token(pretend, kim)).json()
    assert [v["version"] for v in mine["versions"]] == [1]
    assert cloud.get(f"{ROUTE}/{station}/versions", headers=token(pretend, sara)).status_code == 403


@pytest.mark.parametrize(
    "change",
    [
        {"app": "catalog"},
        {"exp": int(time.time()) - 3600},
        {"iss": "https://annan.example.test/realms/x"},
        {"sub": "inte-ett-id"},
    ],
)
def test_a_token_the_hub_cannot_trust_owns_nothing(
    cloud: TestClient, pretend: PretendId, change: dict[str, object]
) -> None:
    station = outside()["station_id"]
    app = str(change.pop("app", "tkl"))
    headers = token(pretend, str(uuid.uuid4()), app, **change)
    refused = cloud.post(f"{ROUTE}/{station}/versions?base=0", content=package(), headers=headers)
    assert refused.status_code == 401
    assert refused.json()["detail"] == "Logga in med TrainMeet ID i TKL för att spara i molnet."
    assert (
        cloud.get(f"{ROUTE}/{station}/versions", headers={"Authorization": "Bearer x"}).status_code
        == 401
    )
