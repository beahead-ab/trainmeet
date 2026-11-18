"""Startar Catalog för webbläsarprovet, med en låtsad TrainMeet ID och en låtsad AI (#52 del d).

    python -m catalog.prov_webblasare --databas <PostgreSQL> [--ny] [--port 8090]
        [--webb apps/catalog/dist] [--tokens 36]

Catalog körs på riktigt: sin riktiga kö för flera foton i en worker-tråd, sin riktiga databas, som
migreras när den startar, och den byggda webbappen, som Catalogs bild serverar den
(CATALOG_WEB_DIR, catalog/app.py). Bilderna sparas på disken i en egen mapp som tas bort efteråt.
Inloggningen är provinloggningen med de fasta provkontona (CAT-214).

TrainMeet ID är låtsat, inne i processen, som i catalog/tests (httpx.MockTransport): Catalogs token,
inga delade vagnparker, och saldot, reservationerna och mätaren med hold (contracts/tokens.py).
Mätarens AI är låtsad: den svarar med ett färdigt förslag per foto, valt efter fotots färg, så att
webbläsarprovet vet vad varje foto ska bli. Inget anropar en AI-leverantör på riktigt (CAT-154).
Provkonto A har --tokens tokens, 36 från början: tre foton, så att tokens tar slut på det fjärde i
en omgång om fyra (CAT-152). Provkonto B har 120, för ett foto i Lägg till med foto.

Med --ny skapas en egen databas på servern i --databas, och den tas bort när programmet stannar,
så att provet alltid börjar från en tom vagnpark.

Körs av kontrollen "Catalogs bild", med apps/catalog/e2e/omgang.mjs, och lokalt.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import secrets
import shutil
import signal
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import psycopg
import uvicorn
from PIL import Image
from psycopg import conninfo

from catalog.app import create_app
from catalog.login import TRIAL_ACCOUNTS
from catalog.reading import FIELDS
from catalog.settings import DEFAULT_WEB_DIR, IdSettings, Settings, package_version
from contracts.catalog import CatalogVersion
from contracts.tokens import (
    MeterAnswer,
    TokenBalance,
    TokenOwner,
    TokenOwnerKind,
    TokenReservation,
    TokenReservationState,
)

LOGGER = logging.getLogger("catalog.prov")

PERSON_A, PERSON_B = (account.id for account in TRIAL_ACCOUNTS[:2])
MODEL = "låtsad AI för webbläsarprovet"
"""The model the pretend meter says it is: never a real provider's."""


def _said(value: str, basis: str = "visible_text", confidence: str = "high") -> dict[str, str]:
    return {"value": value, "confidence": confidence, "basis": basis, "evidence": "Står på sidan."}


def _answer(kind: str, litt: str, number: str, operator: str, *warnings: str) -> str:
    """The AI's answer as the prompt asks for it (catalog/reading.py)."""
    fields: dict[str, Any] = {
        name: {"value": None, "confidence": "low", "basis": "unknown", "evidence": ""}
        for name in FIELDS
    }
    fields.update(
        kind=_said(kind, "visual_inference"),
        litt=_said(litt),
        number=_said(number),
        operator=_said(operator),
    )
    return json.dumps(
        {
            "summary": "Ett fordon från sidan.",
            "fields": fields,
            "warnings": list(warnings),
            "suggested_next_photo": "",
        },
        ensure_ascii=False,
    )


ANSWERS: dict[tuple[int, int, int], str] = {
    # Lägg till flera: the four photos of the batch, in order (apps/catalog/e2e/omgang.mjs).
    (200, 40, 40): _answer("freight_wagon", "Gbs", "3087", "Green Cargo"),
    (40, 150, 60): _answer("freight_wagon", "Hbis", "2253", "Green Cargo", "Kontrollera numret."),
    (40, 80, 200): _answer("freight_wagon", "Sgns", "1209", "privat"),
    (220, 190, 40): _answer("locomotive", "Rc6", "1340", "SJ"),
    # Lägg till med foto: the one photo.
    (130, 60, 160): _answer("locomotive", "Rc4", "1145", "SJ"),
}
"""The pretend AI's answer for each photo, by the photo's colour."""


def answer_for(image: bytes) -> str:
    """The answer for the photo whose mean colour is nearest: the photo Catalog sends is made
    anew as a JPEG (CAT-124), so its colour is near the one the test drew, never the same."""
    with Image.open(io.BytesIO(image)) as opened:
        mean = opened.convert("RGB").resize((1, 1)).getpixel((0, 0))
    assert isinstance(mean, tuple)
    nearest = min(
        ANSWERS, key=lambda colour: sum((a - b) ** 2 for a, b in zip(colour, mean[:3], strict=True))
    )
    return ANSWERS[nearest]


@dataclass
class PretendId:
    """TrainMeet ID's API as Catalog uses it, for the trial accounts: the token, the roles (none
    shared), the app switcher, the balances, the reservations and the meter with hold."""

    balances: dict[UUID, int] = field(default_factory=dict)
    reservations: dict[str, dict[str, Any]] = field(default_factory=dict)
    reads: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def handle(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            return self._handle(request)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "prov", "expires_in": 3600})
        if request.headers.get("authorization") != "Bearer prov":
            return httpx.Response(401, json={"code": "login", "message": "Ingen token."})
        params = request.url.params
        if path.endswith("/apps/access"):
            return httpx.Response(200, json={"roles": []})
        if path.endswith("/apps/switcher"):
            return httpx.Response(200, json={"apps": ["catalog", "id"]})
        if path.endswith("/apps/fleets"):
            return httpx.Response(200, json=[])
        if path.endswith("/apps/tokens"):
            return self._balance(params.get("person", ""), params.get("owner", ""))
        body = json.loads(request.content) if request.content else {}
        if path.endswith("/apps/tokens/reservations"):
            return self._reserve(body)
        if path.endswith("/apps/meter"):
            return self._read(body)
        if "/apps/tokens/reservations/" in path:
            found = self.reservations.get(path.split("/")[-2])
            if found is None:
                return httpx.Response(404, json={"code": "not_found", "message": "Finns inte."})
            if path.endswith("/draw"):
                return self._draw(found, int(body.get("amount", found["amount"])))
            if path.endswith("/return"):
                return self._give_back(found)
        return httpx.Response(404, json={"code": "not_found", "message": "Finns inte."})

    def _owner(self, owner: str) -> UUID | None:
        kind, _, ident = owner.partition(":")
        try:
            person = UUID(ident)
        except ValueError:
            return None
        return person if kind == "person" and person in self.balances else None

    def _token_balance(self, person: UUID) -> TokenBalance:
        left = self.balances[person]
        return TokenBalance(
            owner=TokenOwner(kind=TokenOwnerKind.PERSON, id=person),
            title="Provkonto",
            free_left=0,
            free_monthly=0,
            bought=left,
            reserved=0,
            available=left,
            month=datetime.now(UTC).strftime("%Y-%m"),
        )

    def _balance(self, person: str, owner: str) -> httpx.Response:
        found = self._owner(owner)
        if found is None or str(found) != person:
            return httpx.Response(404, json={"code": "not_found", "message": "Finns inte."})
        return httpx.Response(200, json=self._token_balance(found).model_dump(mode="json"))

    def _reserve(self, body: dict[str, Any]) -> httpx.Response:
        person = self._owner(f"{body['owner']['kind']}:{body['owner']['id']}")
        if person is None:
            return httpx.Response(404, json={"code": "not_found", "message": "Finns inte."})
        amount = int(body["amount"])
        if self.balances[person] < amount:
            return httpx.Response(402, json={"code": "no_tokens", "message": "Saldot räcker inte."})
        self.balances[person] -= amount
        made: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "person": person,
            "amount": amount,
            "drawn": 0,
            "state": TokenReservationState.HELD,
            "what": str(body["what"]),
        }
        self.reservations[made["id"]] = made
        return self._reservation(made, 201)

    def _read(self, body: dict[str, Any]) -> httpx.Response:
        found = self.reservations.get(str(body.get("reservation")))
        if found is None or found["state"] is not TokenReservationState.HELD:
            return httpx.Response(409, json={"code": "conflict", "message": "Ingen reservation."})
        self.reads += 1
        images = body["images"]
        text = answer_for(base64.b64decode(images[0]["data"]))
        meter = MeterAnswer(
            text=text,
            cost=12 * len(images),
            model=MODEL,
            reservation=self._made(found),
        )
        return httpx.Response(200, json=meter.model_dump(mode="json"))

    def _draw(self, found: dict[str, Any], amount: int) -> httpx.Response:
        if found["state"] is TokenReservationState.HELD:
            amount = min(amount, found["amount"])
            self.balances[found["person"]] += found["amount"] - amount
            found.update(state=TokenReservationState.DRAWN, drawn=amount)
        return self._reservation(found)

    def _give_back(self, found: dict[str, Any]) -> httpx.Response:
        if found["state"] is TokenReservationState.DRAWN:
            return httpx.Response(409, json={"code": "conflict", "message": "Dragen."})
        if found["state"] is TokenReservationState.HELD:
            self.balances[found["person"]] += found["amount"]
            found["state"] = TokenReservationState.RETURNED
        return self._reservation(found)

    def _made(self, found: dict[str, Any]) -> TokenReservation:
        now = datetime.now(UTC)
        return TokenReservation(
            id=found["id"],
            owner=TokenOwner(kind=TokenOwnerKind.PERSON, id=found["person"]),
            amount=found["amount"],
            drawn=found["drawn"],
            state=found["state"],
            what=found["what"],
            at=now,
            expires=now + timedelta(minutes=30),
            balance=self._token_balance(found["person"]),
        )

    def _reservation(self, found: dict[str, Any], status: int = 200) -> httpx.Response:
        return httpx.Response(status, json=self._made(found).model_dump(mode="json"))


def _wait_for(url: str, seconds: float = 60.0) -> None:
    """The database, as it starts beside the test: a fresh container takes a moment."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            with psycopg.connect(url, connect_timeout=3):
                return
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


@contextmanager
def database(url: str, fresh: bool) -> Iterator[str]:
    """The database Catalog runs against: as given, or a fresh one on the same server, removed
    afterwards."""
    _wait_for(url)
    if not fresh:
        yield url
        return
    name = f"catalog_prov_{secrets.token_hex(6)}"
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield conninfo.make_conninfo(url, dbname=name)
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def settings_for(database_url: str, port: int, web: Path, pictures: Path) -> Settings:
    """Catalog as in the test environment, with the trial login and TrainMeet ID's API, which is
    the pretend one: its addresses are never reached, the transport answers them."""
    here = f"http://127.0.0.1:{port}"
    return Settings(
        database_url=database_url,
        migrate="auto",
        trial_login=True,
        web_dir=web,
        tag_base="https://localhost/t/",
        id=IdSettings(
            issuer="https://id.prov.invalid/realms/trainmeet",
            client="catalog",
            secret=secrets.token_urlsafe(24),
            public_url=here,
            internal="http://id.prov.invalid/realms/trainmeet",
            api="http://id-api.prov.invalid",
        ),
        build=CatalogVersion(version=package_version()),
        pictures_dir=pictures,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--databas", required=True, help="PostgreSQL, t.ex. postgresql://...")
    parser.add_argument("--ny", action="store_true", help="en egen databas, borttagen efteråt")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--webb", type=Path, default=DEFAULT_WEB_DIR, help="den byggda webbappen")
    parser.add_argument("--tokens", type=int, default=36, help="Provkonto A:s saldo")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # every call to the pretend ID
    if not (args.webb / "index.html").is_file():
        parser.error(f"Webbappen är inte byggd i {args.webb}: kör npm run build -w apps/catalog.")
    pretend = PretendId(balances={PERSON_A: args.tokens, PERSON_B: 120})
    # uvicorn stops on SIGTERM and then raises it again: as an exit, so that the fresh database
    # and the pictures are removed below.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    pictures = Path(tempfile.mkdtemp(prefix="catalog-prov-"))
    try:
        with database(args.databas, args.ny) as url:
            app = create_app(
                settings_for(url, args.port, args.webb, pictures),
                id_http=httpx.Client(transport=httpx.MockTransport(pretend.handle)),
            )
            LOGGER.info("Catalog med låtsad ID och AI på http://127.0.0.1:%d", args.port)
            try:
                uvicorn.run(
                    app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False
                )
            finally:
                LOGGER.info("Den låtsade AI:n läste %d foton.", pretend.reads)
    finally:
        shutil.rmtree(pictures, ignore_errors=True)


if __name__ == "__main__":
    main()
