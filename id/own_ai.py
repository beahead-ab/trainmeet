"""Egen AI på kontot (#79, TOKEN-03, TOKEN-10, TK4): en persons eller klubbs egen AI-tjänst.

The person, or the club's admin, connects any service with the ordinary chat API, or Claude's own
API (H59), with its address, model and key. ID checks that the model reads a picture before it is
saved: a number just drawn, which the model must read back (H70). The meter then reads with the
owner's own AI instead of TrainMeets AI, and draws no tokens (TK4, TOKEN-13).

The key is kept sealed in ID's database with a key derived from ID's own client secret, so a copy
of the database alone does not give it away. It is sent to the service and nowhere else, and never
shown again. Ported from the hub's own AI (integrationer/ai.py), since ID may only share the
contracts with the hub.
"""

from __future__ import annotations

import base64
import json
import secrets
import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from contracts.id import ProblemCode
from contracts.tokens import OwnAiChange, OwnAiState, TokenOwner
from id.db import Database
from id.meter import MeterFailed
from id.roles import Refused
from id.tokens import Tokens

CLAUDE_VERSION: Final = "2023-06-01"
PROBE: Final = "Vilket tal står i bilden? Svara bara med siffrorna."
DIGITS: Final = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
}


class OwnAiFailed(Exception):
    """The service could not be used. The message is for the person and never holds the key."""


@dataclass(frozen=True)
class OwnAi:
    format: str
    address: str
    model: str
    key: str = field(repr=False)


def sealer(secret: str) -> Fernet:
    """The key that seals the services' keys, derived from ID's own client secret."""
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"trainmeet-id egen ai"
    ).derive(secret.encode())
    return Fernet(base64.urlsafe_b64encode(derived))


def seal(fernet: Fernet, key: str) -> bytes:
    return fernet.encrypt(key.encode())


def unseal(fernet: Fernet, sealed: bytes) -> str | None:
    """The key, or None if ID's secret has changed since it was sealed."""
    try:
        return fernet.decrypt(sealed).decode()
    except InvalidToken:
        return None


def check_address(address: str) -> str:
    parts = urlsplit(address.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise OwnAiFailed("Adressen ska börja med https:// (eller http:// för en egen server).")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise OwnAiFailed("Adressen ska vara bara tjänstens adress, utan frågor eller inloggning.")
    return address.strip().rstrip("/")


def ask(
    service: OwnAi,
    prompt: str,
    images: Sequence[tuple[str, str]],
    max_tokens: int,
    http: httpx.Client,
) -> str:
    """The model's answer, as text, for pictures given as (media type, base64)."""
    address = check_address(service.address)
    if service.format == "claude":
        url = f"{address}/v1/messages"
        headers = {"x-api-key": service.key, "anthropic-version": CLAUDE_VERSION}
        content: list[dict[str, Any]] = [
            {"type": "image", "source": {"type": "base64", "media_type": kind, "data": data}}
            for kind, data in images
        ]
        content.append({"type": "text", "text": prompt})
    else:
        url = f"{address}/chat/completions"
        headers = {"Authorization": f"Bearer {service.key}"}
        content = [{"type": "text", "text": prompt}]
        content += [
            {"type": "image_url", "image_url": {"url": f"data:{kind};base64,{data}"}}
            for kind, data in images
        ]
    body = {
        "model": service.model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    try:
        answer = http.post(
            url,
            content=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **headers},
            timeout=120.0,
        )
    except httpx.HTTPError as error:
        raise OwnAiFailed("AI-tjänsten svarar inte på adressen.") from error
    if answer.status_code != 200:
        # The refusal's own words are not passed on: they can quote the key.
        raise OwnAiFailed(_refused(answer.status_code))
    try:
        found = answer.json()
        if service.format == "claude":
            text = "".join(
                part.get("text", "") for part in found["content"] if part.get("type") == "text"
            )
        else:
            text = found["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise OwnAiFailed("AI-tjänsten svarade, men inte i det format som valts.") from error
    if not isinstance(text, str):
        raise OwnAiFailed("AI-tjänsten svarade, men inte i det format som valts.")
    return text


def _refused(status: int) -> str:
    if status in (401, 403):
        return "AI-tjänsten godtog inte nyckeln."
    if status == 404:
        return "AI-tjänsten känner inte adressen eller modellen."
    if status == 429:
        return "AI-tjänsten säger att det är för många frågor eller att taket är nått."
    if status == 400:
        return "AI-tjänsten förstod inte frågan. Kan modellen läsa bilder?"
    return f"AI-tjänsten svarade med fel {status}."


def probe(service: OwnAi, http: httpx.Client, number: str | None = None) -> None:
    """The model must read back a number drawn just now (H70). Raises OwnAiFailed."""
    wanted = number or "".join(secrets.choice("0123456789") for _ in range(3))
    picture = base64.b64encode(drawn(wanted)).decode()
    answer = ask(service, PROBE, [("image/png", picture)], 20, http)
    if "".join(ch for ch in answer if ch.isdigit()) != wanted:
        raise OwnAiFailed(
            "Modellen svarar, men läste inte talet i provbilden. Välj en modell som kan läsa "
            "bilder."
        )


def drawn(number: str, scale: int = 12) -> bytes:
    """A PNG with the number in large black digits on white: the probe's picture."""
    gap = 1
    width = (len(number) * (3 + gap) + gap) * scale
    height = 7 * scale
    rows = []
    for y in range(height):
        cell_y = y // scale - 1
        line = bytearray(b"\x00")
        for x in range(width):
            cell_x = x // scale - gap
            index, column = divmod(cell_x, 3 + gap)
            black = (
                0 <= cell_y < 5
                and 0 <= index < len(number)
                and column < 3
                and cell_x >= 0
                and DIGITS[number[index]][cell_y][column] == "1"
            )
            line.append(0 if black else 255)
        rows.append(bytes(line))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


class OwnAis:
    """The accounts' own AI in ID's database, with the key sealed."""

    def __init__(self, db: Database, tokens: Tokens, fernet: Fernet, http: httpx.Client) -> None:
        self.db = db
        self.tokens = tokens
        self.fernet = fernet
        self.http = http

    def state(self, person: UUID, owner: TokenOwner) -> OwnAiState | None:
        with self.db.transaction() as conn:
            self.tokens.may_manage(conn, person, owner)
            account = self.tokens.account_id(conn, owner)
            row = conn.execute("SELECT * FROM own_ai WHERE account_id = %s", (account,)).fetchone()
        return self._out(owner, row) if row else None

    def connect(self, person: UUID, owner: TokenOwner, change: OwnAiChange) -> OwnAiState:
        """Koppla in egen AI: the model must read the probe's picture before it is saved."""
        with self.db.transaction() as conn:
            self.tokens.may_manage(conn, person, owner)
            account = self.tokens.account_id(conn, owner)
            row = conn.execute(
                "SELECT key_sealed FROM own_ai WHERE account_id = %s", (account,)
            ).fetchone()
        key = change.key or (unseal(self.fernet, bytes(row["key_sealed"])) if row else None)
        if not key:
            raise Refused(422, ProblemCode.INVALID, "Skriv in tjänstens nyckel.")
        try:
            address = check_address(change.address)
            service = OwnAi(change.format, address, change.model.strip(), key)
            probe(service, self.http)
        except OwnAiFailed as error:
            raise Refused(422, ProblemCode.INVALID, str(error)) from None
        with self.db.transaction() as conn:
            stored = conn.execute(
                "INSERT INTO own_ai (account_id, format, address, model, key_sealed, checked_at) "
                "VALUES (%s, %s, %s, %s, %s, now()) ON CONFLICT (account_id) DO UPDATE SET "
                "format = excluded.format, address = excluded.address, model = excluded.model, "
                "key_sealed = excluded.key_sealed, checked_at = excluded.checked_at RETURNING *",
                (account, service.format, address, service.model, seal(self.fernet, key)),
            ).fetchone()
        assert stored is not None
        return self._out(owner, stored)

    def remove(self, person: UUID, owner: TokenOwner) -> None:
        with self.db.transaction() as conn:
            self.tokens.may_manage(conn, person, owner)
            account = self.tokens.account_id(conn, owner)
            conn.execute("DELETE FROM own_ai WHERE account_id = %s", (account,))

    def for_owner(self, owner: TokenOwner) -> OwnAi | None:
        """The owner's own AI for the meter, or None; also None when the key needs to be put
        in again."""
        with self.db.transaction() as conn:
            account = self.tokens.account_id(conn, owner)
            row = conn.execute("SELECT * FROM own_ai WHERE account_id = %s", (account,)).fetchone()
        if row is None:
            return None
        key = unseal(self.fernet, bytes(row["key_sealed"]))
        if key is None:
            return None
        return OwnAi(str(row["format"]), str(row["address"]), str(row["model"]), key)

    def _out(self, owner: TokenOwner, row: Any) -> OwnAiState:
        return OwnAiState(
            owner=owner,
            format=row["format"],
            address=row["address"],
            model=row["model"],
            key_set=unseal(self.fernet, bytes(row["key_sealed"])) is not None,
            checked=row["checked_at"],
        )


@dataclass(frozen=True)
class OwnReader:
    """The owner's own AI as the meter reads with it."""

    service: OwnAi
    http: httpx.Client = field(repr=False)

    @property
    def model(self) -> str:
        return f"{self.service.model} (egen AI)"

    def read(self, prompt: str, images: Sequence[tuple[str, str]], max_tokens: int) -> str:
        try:
            return ask(self.service, prompt, images, max_tokens, self.http)
        except OwnAiFailed as error:
            raise MeterFailed(f"Den egna AI:n: {error}") from None
