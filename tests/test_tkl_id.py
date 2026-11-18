"""TKL loggar in med TrainMeet ID och sparar stationspaketet i molnhubben (TKL18, SYNK-06,
SYNK-18, SYNK-30, H71, #78).

TKL, the cloud hub and a pretend ID run in one process. TKL logs in as the public client "tkl"
with PKCE and no secret; the hub takes the owner from TKL's access token, signed by ID.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from contracts.station_model import StationModel
from contracts.sync import StationPackage
from contracts.tkl import TklIdState, TklMode, TklSaved
from hub import id_login as hub_id
from hub.app import create_app as create_hub
from hub.build_info import BuildInfo
from tkl.app import create_app as create_tkl
from tkl.id_login import TklIdSettings, code_challenge

API = "/api/tkl/1"
ISSUER = "https://id.example.test/realms/trainmeet"
INTERNAL = "http://id:8080/realms/trainmeet"
CLOUD = "https://moln.example.test"
TKL = "http://localhost:8090"


@dataclass
class PretendId:
    """Keycloak for the public client tkl: the code for tokens with PKCE, and the keys."""

    key: rsa.RSAPrivateKey = field(
        default_factory=lambda: rsa.generate_private_key(public_exponent=65537, key_size=2048)
    )
    subject: str = field(default_factory=lambda: str(uuid.uuid4()))
    challenge: str = ""
    nonce: str = ""
    exchanges: list[dict[str, str]] = field(default_factory=list)

    def sign(self, claims: dict[str, Any]) -> str:
        now = int(time.time())
        body = {"iss": ISSUER, "sub": self.subject, "iat": now, "exp": now + 300, **claims}
        return jwt.encode(body, self.key, algorithm="RS256", headers={"kid": "k1"})

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/certs"):
            public = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
            return httpx.Response(200, json={"keys": [{**public, "kid": "k1", "alg": "RS256"}]})
        if request.url.path.endswith("/token"):
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.exchanges.append(form)
            assert "authorization" not in request.headers, "a public client sends no secret"
            if form["grant_type"] == "authorization_code":
                assert code_challenge(form["code_verifier"]) == self.challenge, "PKCE"
            ident = {"aud": "tkl", "azp": "tkl", "nonce": self.nonce, "name": "Tomas Ek"}
            return httpx.Response(
                200,
                json={
                    "id_token": self.sign({**ident, "email_verified": True}),
                    "access_token": self.sign({"azp": "tkl", "aud": "account"}),
                    "refresh_token": "förnya",
                    "expires_in": 300,
                },
            )
        return httpx.Response(404)


@pytest.fixture
def pretend() -> PretendId:
    return PretendId()


@pytest.fixture
def cloud(tmp_path: Path, pretend: PretendId) -> TestClient:
    settings = hub_id.IdSettings(
        issuer=ISSUER, secret="hemlighet", public_url=CLOUD, internal=INTERNAL, client="hub"
    )
    made = create_hub(
        BuildInfo(version="0.1.0"),
        preview_db=tmp_path / "moln" / "p.db",
        id_settings=settings,
        id_http=httpx.Client(transport=httpx.MockTransport(pretend.handle)),
    )
    return TestClient(made)


def internet(cloud: TestClient, pretend: PretendId) -> httpx.Client:
    """What TKL reaches: ID, and the cloud hub."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host in ("id.example.test", "id"):
            return pretend.handle(request)
        answer = cloud.request(
            request.method,
            request.url.raw_path.decode(),
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            content=request.content,
        )
        return httpx.Response(answer.status_code, headers=answer.headers, content=answer.content)

    return httpx.Client(transport=httpx.MockTransport(handle))


@pytest.fixture
def tkl(tmp_path: Path, cloud: TestClient, pretend: PretendId) -> TestClient:
    settings = TklIdSettings(issuer=ISSUER, internal=INTERNAL, public_url=TKL, cloud=CLOUD)
    made = create_tkl(
        tmp_path / "tkl",
        mode=TklMode.LOCAL,
        http=lambda: internet(cloud, pretend),
        discover=lambda: [],
        id_settings=settings,
    )
    client = TestClient(made, base_url=TKL, follow_redirects=False)
    answer = client.post(API + "/setup", json={"name": "Åsen", "station_id": "asen", "pin": "4711"})
    assert answer.status_code == 201, answer.text
    assert client.post(API + "/studio/version").status_code == 200
    return client


def log_in(tkl: TestClient, pretend: PretendId) -> None:
    sent = tkl.get(API + "/id/login")
    assert sent.status_code == 303, sent.text
    address = urlparse(sent.headers["location"])
    query = {k: v[0] for k, v in parse_qs(address.query).items()}
    assert (query["client_id"], query["code_challenge_method"]) == ("tkl", "S256")
    assert query["redirect_uri"] == TKL + "/api/tkl/1/id/callback"
    pretend.challenge, pretend.nonce = query["code_challenge"], query["nonce"]
    back = tkl.get(API + "/id/callback", params={"code": "kod", "state": query["state"]})
    assert (back.status_code, back.headers["location"]) == (303, "/")


def id_state(tkl: TestClient) -> TklIdState:
    return TklIdState.model_validate(tkl.get(API + "/id").json())


def test_tkl_logs_in_with_id_and_saves_the_station_in_the_cloud(
    tkl: TestClient, cloud: TestClient, pretend: PretendId
) -> None:
    before = id_state(tkl)
    assert (before.available, before.person, before.cloud, before.local) == (
        True,
        None,
        CLOUD,
        1,
    )
    refused = tkl.post(API + "/id/save", json={})
    assert refused.status_code == 401
    log_in(tkl, pretend)
    assert id_state(tkl).person == "Tomas Ek"

    saved = TklSaved.model_validate(tkl.post(API + "/id/save", json={}).json())
    assert saved.version == 1, saved
    assert id_state(tkl).saved == 1
    # The cloud keeps it as the owner's, the person ID named.
    owner = cloud.app.state.owners.owner(  # type: ignore[attr-defined]
        "Bearer " + pretend.sign({"azp": "tkl"})
    )
    assert owner == pretend.subject
    listed = cloud.get(
        "/api/sync/1/stations/asen/versions",
        headers={"Authorization": "Bearer " + pretend.sign({"azp": "tkl"})},
    ).json()
    assert [v["version"] for v in listed["versions"]] == [1]


def test_a_save_on_top_of_an_older_version_is_refused_and_the_owner_chooses(
    tkl: TestClient, cloud: TestClient, pretend: PretendId, tmp_path: Path
) -> None:
    """H71: another computer saved meanwhile. TKL is told, and saves on top only when asked."""
    log_in(tkl, pretend)
    assert TklSaved.model_validate(tkl.post(API + "/id/save", json={}).json()).version == 1
    other = {"Authorization": "Bearer " + pretend.sign({"azp": "tkl"})}
    body = tkl.get(API + "/studio").json()["draft"]
    package = StationPackage(station_id="asen", outside=body).model_dump_json()
    assert (
        cloud.post(
            "/api/sync/1/stations/asen/versions?base=1", content=package, headers=other
        ).status_code
        == 201
    )
    told = TklSaved.model_validate(tkl.post(API + "/id/save", json={}).json())
    assert (told.version, told.behind) == (None, 2)
    assert "sparad från en annan dator" in (told.message or "")
    on_top = TklSaved.model_validate(tkl.post(API + "/id/save", json={"on_top": 2}).json())
    assert on_top.version == 3


def test_logging_out_of_id_in_tkl_forgets_the_person(tkl: TestClient, pretend: PretendId) -> None:
    log_in(tkl, pretend)
    assert tkl.post(API + "/id/logout").json()["person"] is None
    assert tkl.post(API + "/id/save", json={}).status_code == 401


def test_a_login_that_did_not_start_here_logs_no_one_in(
    tkl: TestClient, pretend: PretendId
) -> None:
    back = tkl.get(API + "/id/callback", params={"code": "kod", "state": "fel"})
    assert back.headers["location"] == "/?id=fel"
    assert id_state(tkl).person is None


def test_the_station_s_model_goes_to_the_cloud_in_the_station_package(
    tkl: TestClient, cloud: TestClient, pretend: PretendId
) -> None:
    """From level 1 the model is kept with the station and versioned with the outside; both go
    to the cloud as one station package (SYNK-30, #83). The cloud keeps the inside as it came."""
    listed = tkl.get(API + "/referens").json()
    used = tkl.post(API + f"/referens/{listed[0]['id']}/use")
    assert used.status_code == 200, used.text
    assert tkl.post(API + "/studio/version").json()["versions"][0]["number"] == 2
    log_in(tkl, pretend)
    saved = TklSaved.model_validate(tkl.post(API + "/id/save", json={}).json())
    assert saved.version == 1, saved
    package = cloud.get(
        "/api/sync/1/stations/asen/versions/1",
        headers={"Authorization": "Bearer " + pretend.sign({"azp": "tkl"})},
    )
    assert package.status_code == 200, package.text
    inside = StationPackage.model_validate(package.json()).inside
    kept = StationModel.model_validate(inside["station_model"])
    assert (kept.station_id, kept.name) == ("asen", "Åsen")
