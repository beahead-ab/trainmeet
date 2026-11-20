"""Låtsas-ID och låtsas-CAD för provet av Anläggning från CAD i Hubbens bild (#89 del d3, CAD-11).

A pretend TrainMeet ID and a pretend TrainMeet CAD in one small server, for the check in the
workflow "Hubbens bild": the cloud hub from the image logs a planner in with ID's code flow,
asks CAD for the planner's assemblies with the planner's access token, and gets the synthetic
assembly (integrationer/cad_example.py). Nothing here is real: the signing key is made at start
and the person, the club and the meet are made up.

    python -m hub.prov_cad --port 8098 --issuer http://127.0.0.1:8098/realms/trainmeet

ID: the realm's auth, token (code, refresh and the app's client credentials) and certs, and the
apps' API with the person's roles at the meet. CAD: /api/cad/1/meet/assemblies and one assembly.
"""

from __future__ import annotations

import argparse
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Final
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from integrationer import cad_example

PERSON: Final = "00000000-0000-4000-8000-00000000d301"
CLUB: Final = "00000000-0000-4000-8000-00000000d302"
MEET: Final = "00000000-0000-4000-8000-00000000d303"
"""The meet in ID the planner plans, as Arrangör and the club's administrator."""
REALM: Final = "/realms/trainmeet/protocol/openid-connect"
KID: Final = "prov-1"


class Pretend:
    def __init__(self, issuer: str) -> None:
        self.issuer = issuer
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.nonces: dict[str, str] = {}
        self.access: set[str] = set()
        self.lock = threading.Lock()
        self.assembly = cad_example.assembly_bytes()

    def id_token(self, nonce: str) -> str:
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "aud": "hub",
            "azp": "hub",
            "sub": PERSON,
            "iat": now,
            "exp": now + 300,
            "nonce": nonce,
            "email_verified": True,
            "name": "Provplanerare",
        }
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": KID})

    def new_access(self) -> str:
        token = secrets.token_urlsafe(24)
        with self.lock:
            self.access.add(token)
        return token

    def bearer_known(self, token: str) -> bool:
        with self.lock:
            return token in self.access

    def jwks(self) -> dict[str, Any]:
        public = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        return {"keys": [{**public, "kid": KID, "use": "sig", "alg": "RS256"}]}

    def meet(self) -> dict[str, Any]:
        return {
            "id": MEET,
            "club": CLUB,
            "club_name": "Provklubben",
            "name": "Provträffen",
            "starts_on": "2026-11-20",
            "ends_on": "2026-11-22",
            "roles": ["organizer"],
            "club_admin": True,
        }

    def brief(self) -> dict[str, Any]:
        return {
            "id": str(cad_example.ASSEMBLY),
            "name": "Provträffens anläggning",
            "owner": {"kind": "person", "id": PERSON, "name": "Provplaneraren"},
            "scale": "H0",
            "modules": 6,
            "problems": 0,
            "revision": 3,
            "changed_at": "2026-11-20T10:00:00Z",
            "may_edit": True,
        }


def handler(pretend: Pretend) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return None  # nothing about tokens in any log

        def send(self, status: int, body: bytes, media: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", media)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def answer(self, status: int, value: object) -> None:
            self.send(status, json.dumps(value).encode())

        def bearer(self) -> str:
            return self.headers.get("Authorization", "").removeprefix("Bearer ").strip()

        def do_GET(self) -> None:
            address = urlsplit(self.path)
            query = {k: v[0] for k, v in parse_qs(address.query).items()}
            path = address.path
            if path == "/healthz":
                return self.send(200, b"ok", "text/plain")
            if path == f"{REALM}/auth":
                code = secrets.token_urlsafe(16)
                with pretend.lock:
                    pretend.nonces[code] = query.get("nonce", "")
                back = {"code": code, "state": query.get("state", "")}
                self.send_response(302)
                self.send_header("Location", f"{query['redirect_uri']}?{urlencode(back)}")
                self.send_header("Content-Length", "0")
                return self.end_headers()
            if path == f"{REALM}/certs":
                return self.answer(200, pretend.jwks())
            if path == "/api/id/1/apps/access":
                roles = ["organizer"] if query.get("resource") == f"meet:{MEET}" else []
                return self.answer(200, {"person": PERSON, "resource": {}, "roles": roles})
            if path == "/api/id/1/apps/meets":
                return self.answer(200, [pretend.meet()])
            if path.startswith("/api/cad/1/meet/"):
                if pretend.bearer_known(self.bearer()):
                    if path == "/api/cad/1/meet/assemblies":
                        return self.answer(200, [pretend.brief()])
                    if path == f"/api/cad/1/meet/assemblies/{cad_example.ASSEMBLY}":
                        return self.send(200, pretend.assembly)
                    return self.answer(404, {"code": "not_found", "message": "Finns inte."})
                return self.answer(401, {"code": "login", "message": "Logga in med ID."})
            return self.answer(404, {"detail": "Finns inte i låtsas-ID eller låtsas-CAD."})

        def do_POST(self) -> None:
            size = int(self.headers.get("Content-Length", "0") or 0)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(size).decode()).items()}
            if urlsplit(self.path).path != f"{REALM}/token":
                return self.answer(404, {"detail": "Finns inte."})
            grant = form.get("grant_type")
            if grant == "client_credentials":
                return self.answer(200, {"access_token": "app", "expires_in": 300})
            if grant == "authorization_code":
                with pretend.lock:
                    nonce = pretend.nonces.pop(form.get("code", ""), None)
                if nonce is None:
                    return self.answer(400, {"error": "invalid_grant"})
                return self.answer(
                    200,
                    {
                        "id_token": pretend.id_token(nonce),
                        "access_token": pretend.new_access(),
                        "refresh_token": "prov-fornyelse",
                        "expires_in": 300,
                    },
                )
            if grant == "refresh_token":
                return self.answer(200, {"access_token": pretend.new_access(), "expires_in": 300})
            return self.answer(400, {"error": "unsupported_grant_type"})

    return Handler


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8098)
    parser.add_argument("--issuer", required=True, help="ID:s adress som webbläsaren ser den.")
    given = parser.parse_args(argv)
    server = ThreadingHTTPServer(("0.0.0.0", given.port), handler(Pretend(given.issuer)))
    print(f"Låtsas-ID och låtsas-CAD på port {given.port}, träffen i ID {MEET}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
