"""Biljetten för inloggning på Pi:n utan internet (KONTO-11, KONTO-37, #78).

The Hub asks for a ticket when someone logs in on a meet's Pi with internet, through the Pi's
cloud hub. ID signs it with a key of its own, ES256, kept in ID's database and made the first
time it is needed; the public keys are open at /api/id/1/keys, and the Pi fetches them while it
has internet. The ticket says who the person is, for which Pi, and the person's roles at the
meet's meets in ID as they were then. It lasts 30 days: a role taken back in ID holds on the Pi
until the ticket runs out or the person logs in again with internet (KONTO-37).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from contracts.id import ProblemCode, Resource, ResourceKind, Ticket
from id.db import Database
from id.roles import Refused, Roles, not_found

LIFETIME: Final = timedelta(days=30)
AUDIENCE_PREFIX: Final = "trainmeet-hub:"
"""The ticket's audience: the Pi it was asked for, by its hub id."""


class Tickets:
    def __init__(self, db: Database, roles: Roles, issuer: str) -> None:
        self.db = db
        self.roles = roles
        self.issuer = issuer

    def _keys(self) -> list[tuple[str, ec.EllipticCurvePrivateKey]]:
        """Every key, newest first; one is made when there is none."""
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT kid, private_pem FROM ticket_key ORDER BY created_at DESC"
            ).fetchall()
            if not rows:
                key = ec.generate_private_key(ec.SECP256R1())
                pem = key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                ).decode("ascii")
                kid = f"biljett-{secrets.token_hex(6)}"
                conn.execute(
                    "INSERT INTO ticket_key (kid, private_pem) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (kid, pem),
                )
                rows = [{"kid": kid, "private_pem": pem}]
        found: list[tuple[str, ec.EllipticCurvePrivateKey]] = []
        for row in rows:
            loaded = serialization.load_pem_private_key(row["private_pem"].encode(), None)
            if isinstance(loaded, ec.EllipticCurvePrivateKey):
                found.append((str(row["kid"]), loaded))
        return found

    def jwks(self) -> dict[str, Any]:
        """The public keys, for the Pi to check tickets with when it has no internet."""
        keys = []
        for kid, key in self._keys():
            public = jwt.algorithms.ECAlgorithm.to_jwk(key.public_key(), as_dict=True)
            keys.append({**public, "kid": kid, "use": "sig", "alg": "ES256"})
        return {"keys": keys}

    def issue(self, app: str, person: UUID, hub: str, meets: list[UUID]) -> Ticket:
        """A ticket for the person on the Pi, with the roles at the meets as ID says now."""
        if app != "hub":
            raise Refused(403, ProblemCode.FORBIDDEN, "Bara Hubben får be om en biljett.")
        with self.db.transaction() as conn:
            row = conn.execute("SELECT name FROM person WHERE id = %s", (person,)).fetchone()
        if row is None:
            raise not_found()
        roles = {
            str(meet): [
                role.value
                for role in self.roles.access(
                    person, Resource(kind=ResourceKind.MEET, id=str(meet))
                ).roles
            ]
            for meet in meets
        }
        now = datetime.now(UTC)
        expires = now + LIFETIME
        kid, key = self._keys()[0]
        claims = {
            "iss": self.issuer,
            "aud": AUDIENCE_PREFIX + hub,
            "sub": str(person),
            "name": str(row["name"]),
            "roles": roles,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "typ": "trainmeet-pi-ticket",
        }
        token = jwt.encode(claims, key, algorithm="ES256", headers={"kid": kid})
        return Ticket(ticket=token, expires=expires)
