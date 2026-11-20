"""CAD's test fixtures: a fresh PostgreSQL per test, and CAD with a pretend TrainMeet ID.

CAD_TEST_DATABASE_URL points at a server where the user may create databases, for example
postgresql://postgres@127.0.0.1:5432/postgres; without it CATALOG_TEST_DATABASE_URL is used, the
same server the check "Tester" starts. Without either the database tests are skipped locally,
but never in CI.

The pretend ID answers CAD's client credentials, the token exchange and the signing keys, and
ID's API for the apps: the person's clubs (#67), the roles on a module, the switcher and the
tokens. Its clubs and roles are set by each test.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from uuid import UUID

import httpx
import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from psycopg import conninfo

from cad.app import create_app
from cad.geometry import from_chord
from cad.login import TRIAL_ACCOUNTS
from cad.prov_webblasare import PretendMeter
from cad.settings import IdSettings, Settings
from contracts.cad import CadVersion

API = "/api/cad/1"
ISSUER = "https://id.example.test/realms/trainmeet"
INTERNAL = "http://id:8080/realms/trainmeet"
ID_API = "http://id-api:8080"
PUBLIC = "https://cad.example.test"
SECRET = "klienthemlighet-for-provet"

A, B, C, D = TRIAL_ACCOUNTS
CLUB = UUID("0b6f2a1c-5d3e-4f70-8a91-2c3d4e5f6a7b")
OTHER_CLUB = UUID("1c7a3b2d-6e4f-4081-9ba2-3d4e5f6a7b8c")


@pytest.fixture
def database_url() -> Iterator[str]:
    admin = (
        os.environ.get("CAD_TEST_DATABASE_URL", "").strip()
        or os.environ.get("CATALOG_TEST_DATABASE_URL", "").strip()
    )
    if not admin:
        if os.environ.get("CI"):
            pytest.fail("CAD_TEST_DATABASE_URL saknas i CI: databastesterna för CAD måste köras.")
        pytest.skip("CAD_TEST_DATABASE_URL saknas: inga databastester för CAD.")
    name = f"cad_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield conninfo.make_conninfo(admin, dbname=name)
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@dataclass
class PretendId(PretendMeter):
    """Just enough of TrainMeet ID for CAD; its meter is the browser test's (balance, own_ai,
    reservations, reads, and answer: what the AI says, a callable of the prompt)."""

    key: rsa.RSAPrivateKey = field(default_factory=new_key)
    kid: str = "nyckel-1"
    nonce: str = ""
    clubs: dict[UUID, list[dict[str, str]]] = field(default_factory=dict)
    """person -> [{"id", "name", "role"}], as GET /api/id/1/apps/clubs answers."""
    module_roles: dict[tuple[UUID, str], list[str]] = field(default_factory=dict)
    """(person, module id) -> roles, as GET /api/id/1/apps/access answers."""
    down: bool = False
    asked: list[str] = field(default_factory=list)
    app_tokens: int = 0

    def join(self, person: UUID, club: UUID, name: str, role: str = "member") -> None:
        self.clubs.setdefault(person, []).append({"id": str(club), "name": name, "role": role})

    def token(self, subject: str) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": "cad",
            "azp": "cad",
            "sub": subject,
            "iat": now,
            "exp": now + 300,
            "nonce": self.nonce,
            "email": "prov@example.com",
            "email_verified": True,
            "name": "Provare Ett",
        }
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": self.kid})

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("ID svarar inte", request=request)
        path = request.url.path
        if path.endswith("/protocol/openid-connect/certs"):
            public = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
            return httpx.Response(
                200, json={"keys": [{**public, "kid": self.kid, "use": "sig", "alg": "RS256"}]}
            )
        if path.endswith("/protocol/openid-connect/token"):
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if form.get("grant_type") == "client_credentials":
                self.app_tokens += 1
                return httpx.Response(200, json={"access_token": "app-token", "expires_in": 300})
            return httpx.Response(200, json={"id_token": self.token(form["code"])})
        if path.startswith("/api/id/1/apps/"):
            assert request.headers.get("authorization") == "Bearer app-token"
            what = path.removeprefix("/api/id/1/apps/")
            self.asked.append(what)
            if what.startswith(("tokens/reservations", "meter")) or (
                what == "tokens" and request.url.params.get("owner")
            ):
                return self.tokens_answer(request, what)
            person = UUID(request.url.params["person"])
            if what == "clubs":
                return httpx.Response(200, json=self.clubs.get(person, []))
            if what == "access":
                resource = request.url.params["resource"]
                module = resource.removeprefix("module:")
                roles = self.module_roles.get((person, module), [])
                return httpx.Response(
                    200,
                    json={
                        "person": str(person),
                        "resource": {"kind": "module", "id": module},
                        "roles": roles,
                    },
                )
            if what == "switcher":
                return httpx.Response(200, json={"apps": ["cad", "catalog", "id"]})
            if what == "tokens":
                return httpx.Response(200, json={"available": 86})
        return httpx.Response(404)

    def tokens_answer(self, request: httpx.Request, what: str) -> httpx.Response:
        """The balance, the reservations and the meter with hold (contracts/tokens.py)."""
        return self.meter_answer(request, what)


def settings_for(url: str, web_dir: Path, *, trial: bool = True) -> Settings:
    return Settings(
        database_url=url,
        migrate="auto",
        trial_login=trial,
        web_dir=web_dir,
        id=IdSettings(
            issuer=ISSUER,
            client="cad",
            secret=SECRET,
            public_url=PUBLIC,
            internal=INTERNAL,
            api=ID_API,
        ),
        build=CadVersion(version="0.1.0", commit="abcdef1234"),
        photos_dir=web_dir / "foton",
        photo_queue=False,
    )


@dataclass
class World:
    """CAD with a pretend ID, and a browser per trial account."""

    app: Any
    id: PretendId
    browsers: dict[UUID, TestClient] = field(default_factory=dict)

    def browser(self) -> TestClient:
        return TestClient(self.app, base_url=PUBLIC, follow_redirects=False)

    def as_(self, person: UUID) -> TestClient:
        if person not in self.browsers:
            client = self.browser()
            client.__enter__()
            answer = client.post(f"{API}/trial/login", json={"account": str(person)})
            assert answer.status_code == 200, answer.text
            self.browsers[person] = client
        return self.browsers[person]


@pytest.fixture
def pretend_id() -> PretendId:
    return PretendId()


@pytest.fixture
def world(database_url: str, tmp_path: Path, pretend_id: PretendId) -> Iterator[World]:
    (tmp_path / "index.html").write_text("<!doctype html><title>TrainMeet CAD</title>")
    http = httpx.Client(transport=httpx.MockTransport(pretend_id.handle))
    app = create_app(settings_for(database_url, tmp_path), id_http=http)
    with TestClient(app, base_url=PUBLIC):
        made = World(app=app, id=pretend_id)
        try:
            yield made
        finally:
            for client in made.browsers.values():
                client.__exit__(None, None, None)


def straight(
    name: str = "Linje 1500",
    *,
    length: float = 1500,
    width: float = 500,
    a: list[float] | None = None,
    b: list[float] | None = None,
    profile_a: str | None = None,
    profile_b: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """A straight module from measures, as the web app sends it."""
    a = [250] if a is None else a
    b = a if b is None else b
    return {
        "name": name,
        "scale": "H0",
        "shape": {"kind": "straight", "length": length, "width": width},
        "gables": [
            {"end": "A", "profile": profile_a, "tracks": a},
            {"end": "B", "profile": profile_b, "tracks": b},
        ],
        **extra,
    }


def curve(name: str = "Kurva 30° · K2", **extra: Any) -> dict[str, Any]:
    """The view Kurvmodul's example: string 1035 and sagitta 68 give R 2 003 mm · 29,9°, kept as
    computed (CAD16); double track 200 + 50 from Kant 1, the outer edge."""
    bend = from_chord(1035, 68)
    return {
        "name": name,
        "scale": "H0",
        "shape": {
            "kind": "curve",
            "radius": bend.radius,
            "angle": bend.angle,
            "width": 500,
            "edge": "outer",
            "sides": "bent",
            "measured": {"chord": 1035, "sagitta": 68},
        },
        "gables": [
            {"end": "A", "profile": "h0-dubbelspar", "tracks": [200, 250]},
            {"end": "B", "profile": "h0-dubbelspar", "tracks": [200, 250]},
        ],
        **extra,
    }
