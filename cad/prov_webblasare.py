"""Startar CAD för webbläsarprovet, med en låtsad TrainMeet ID (#89 del a).

    python -m cad.prov_webblasare --databas <PostgreSQL> [--ny] [--port 8095]
        [--webb apps/cad/dist]

CAD körs på riktigt: sin riktiga databas, som migreras när den startar, och den byggda webbappen,
som CAD:s bild serverar den (CAD_WEB_DIR, cad/app.py). Inloggningen är provinloggningen med de
fasta provkontona.

TrainMeet ID är låtsat, inne i processen, som i cad/tests (httpx.MockTransport): CAD:s token,
klubbarna, appväxlaren och saldot. Provkonto A är administratör i Provklubben och Provkonto B
medlem, så att klubbens synlighet och rättigheter går att prova. Inget anropar ID på riktigt.

Med --ny skapas en egen databas på servern i --databas, och den tas bort när programmet stannar,
så att provet alltid börjar från ett tomt bibliotek.

Körs av kontrollen "CAD:s bild", med apps/cad/e2e/bibliotek.mjs, och lokalt.
"""

from __future__ import annotations

import argparse
import logging
import secrets
import signal
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import httpx
import psycopg
import uvicorn
from psycopg import conninfo

from cad.app import create_app
from cad.login import TRIAL_ACCOUNTS
from cad.settings import DEFAULT_WEB_DIR, IdSettings, Settings, package_version
from contracts.cad import CadVersion

LOGGER = logging.getLogger("cad.prov")

PERSON_A, PERSON_B = (account.id for account in TRIAL_ACCOUNTS[:2])
CLUB = UUID("5a1f0c3e-89a0-4d2b-9e1f-7a6b5c4d3e2f")
"""Provklubben: only in the browser test."""


class PretendId:
    """Just enough of TrainMeet ID's API for CAD's pages."""

    def __init__(self, tokens: int) -> None:
        self.tokens = tokens
        self.clubs: dict[UUID, list[dict[str, str]]] = {
            PERSON_A: [{"id": str(CLUB), "name": "Provklubben", "role": "admin"}],
            PERSON_B: [{"id": str(CLUB), "name": "Provklubben", "role": "member"}],
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "prov", "expires_in": 3600})
        what = path.removeprefix("/api/id/1/apps/")
        person = request.url.params.get("person", "")
        try:
            who = UUID(person)
        except ValueError:
            return httpx.Response(422)
        if what == "clubs":
            return httpx.Response(200, json=self.clubs.get(who, []))
        if what == "access":
            resource = request.url.params.get("resource", "")
            kind, _, ident = resource.partition(":")
            return httpx.Response(
                200, json={"person": person, "resource": {"kind": kind, "id": ident}, "roles": []}
            )
        if what == "switcher":
            return httpx.Response(200, json={"apps": ["hub", "tkl", "cad", "catalog", "id"]})
        if what == "tokens":
            return httpx.Response(200, json={"available": self.tokens})
        return httpx.Response(404)


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
    """The database CAD runs against: as given, or a fresh one on the same server, removed
    afterwards."""
    _wait_for(url)
    if not fresh:
        yield url
        return
    name = f"cad_prov_{secrets.token_hex(6)}"
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield conninfo.make_conninfo(url, dbname=name)
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def settings_for(database_url: str, port: int, web: Path) -> Settings:
    """CAD with the trial login and TrainMeet ID's API, which is the pretend one: its addresses
    are never reached, the transport answers them."""
    return Settings(
        database_url=database_url,
        migrate="auto",
        trial_login=True,
        web_dir=web,
        id=IdSettings(
            issuer="https://id.prov.invalid/realms/trainmeet",
            client="cad",
            secret=secrets.token_urlsafe(24),
            public_url=f"http://127.0.0.1:{port}",
            internal="http://id.prov.invalid/realms/trainmeet",
            api="http://id-api.prov.invalid",
        ),
        build=CadVersion(version=package_version()),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--databas", required=True, help="PostgreSQL, t.ex. postgresql://...")
    parser.add_argument("--ny", action="store_true", help="en egen databas, borttagen efteråt")
    parser.add_argument("--port", type=int, default=8095)
    parser.add_argument("--webb", type=Path, default=DEFAULT_WEB_DIR, help="den byggda webbappen")
    parser.add_argument("--tokens", type=int, default=86, help="provkontonas saldo")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # every call to the pretend ID
    if not (args.webb / "index.html").is_file():
        parser.error(f"Webbappen är inte byggd i {args.webb}: kör npm run build -w apps/cad.")
    pretend = PretendId(args.tokens)
    # uvicorn stops on SIGTERM and then raises it again: as an exit, so that the fresh database
    # is removed below.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with database(args.databas, args.ny) as url:
        app = create_app(
            settings_for(url, args.port, args.webb),
            id_http=httpx.Client(transport=httpx.MockTransport(pretend.handle)),
        )
        LOGGER.info("CAD med låtsad ID på http://127.0.0.1:%d", args.port)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
