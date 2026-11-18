"""Flytten från gamla TrainCatalog (#57, CAT-204–CAT-206): the script, the waiting fleets that
are taken over at the first login, the old fields, and the old addresses.

The old TrainCatalog is a database of its own here, with its tables and columns as its Django
migrations made them (traincatalog's catalog/migrations, 0001–0021), and made-up data: no real
names, addresses at example.org. The pictures are small JPEG files in a folder of their own,
laid out as the old MEDIA_ROOT.
"""

from __future__ import annotations

import io
import json
import logging
import os
import secrets
import uuid
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from psycopg import conninfo
from psycopg.types.json import Jsonb

from catalog import migrate, waiting
from catalog.app import create_app
from catalog.db import Database
from catalog.fleet import Fleet
from catalog.flytten import (
    NO_VERIFIED,
    PICTURE_FULL,
    PICTURE_MISSING,
    PICTURE_VEHICLE,
    TAG_TAKEN,
    VEHICLE_OWNER,
    Move,
    OldVehicle,
    carry,
    main,
    read_old,
)
from catalog.id_login import verified_email
from catalog.old_paths import new_address
from catalog.pictures import DiskStore, PictureLimits, Pictures
from catalog.settings import Settings
from catalog.tags import Tags
from catalog.tests.conftest import ENV
from catalog.tests.test_id_login import PretendId, back_from_id, id_settings, to_id
from contracts.catalog import (
    CatalogVersion,
    FieldSource,
    TagLink,
    VehicleFields,
    VehicleKind,
    VehicleStatus,
)

API = "/api/catalog/1"
PEPPER = "en-peppar-som-bara-finns-i-provet-0123456789"
BASE = "https://test.catalog.trainmeet.app/t/"

# The old accounts: one with a verified address, one whose address was never verified, and one
# with nothing to move.
ONE, TWO, THREE = (uuid.UUID(f"00000000-0000-4000-8000-00000000000{n}") for n in (1, 2, 3))
ONE_EMAIL = "agare.ett@example.org"
TWO_EMAIL = "agare.tva@example.org"
THREE_EMAIL = "agare.tre@example.org"
# ONE's vehicles: a wagon with many old fields, a locomotive linked to an old prototype, a
# saved vehicle without litt and number, a coach with a DCC address and a long epoch, and a
# wagon whose painted check digit is wrong. TWO's wagon.
HBIS, RC6, UNNAMED, COACH, WRONG, TWOS = (
    uuid.UUID(f"10000000-0000-4000-8000-00000000000{n}") for n in range(1, 7)
)
PROTOTYPE = uuid.UUID("20000000-0000-4000-8000-000000000001")
NFC_UID = "04a1b2c3d4e5f6"
SIM_UID = "6b1f6e1c-2f43-4e5b-9a1d-3c0e8f7a6b5d"
TAKEN_UID = "0411223344556677"
NFC_TAG, SIM_TAG, TAKEN_TAG = (
    uuid.UUID(f"30000000-0000-4000-8000-00000000000{n}") for n in (1, 2, 3)
)
PICTURES = [uuid.UUID(f"40000000-0000-4000-8000-00000000000{n}") for n in range(1, 5)]

OLD_SCHEMA = """
CREATE TABLE catalog_user (
    password varchar(128) NOT NULL DEFAULT '',
    last_login timestamptz,
    is_superuser boolean NOT NULL DEFAULT false,
    first_name varchar(150) NOT NULL DEFAULT '',
    last_name varchar(150) NOT NULL DEFAULT '',
    is_staff boolean NOT NULL DEFAULT false,
    is_active boolean NOT NULL DEFAULT true,
    date_joined timestamptz NOT NULL DEFAULT now(),
    id uuid PRIMARY KEY,
    email varchar(254) NOT NULL UNIQUE,
    display_name varchar(80) NOT NULL,
    scale varchar(20) NOT NULL DEFAULT 'H0',
    ai_opt_in boolean NOT NULL DEFAULT false,
    next_tag_number integer NOT NULL DEFAULT 1,
    ai_consent_at timestamptz,
    default_region varchar(2) NOT NULL DEFAULT 'SE',
    share_name boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX user_email_case_unique ON catalog_user (lower(email));
CREATE TABLE account_emailaddress (
    id serial PRIMARY KEY,
    email varchar(254) NOT NULL,
    verified boolean NOT NULL,
    "primary" boolean NOT NULL,
    user_id uuid NOT NULL REFERENCES catalog_user (id)
);
CREATE TABLE catalog_prototypetype (
    id uuid PRIMARY KEY,
    name varchar(160) NOT NULL,
    operator varchar(80) NOT NULL DEFAULT '',
    litt varchar(40) NOT NULL DEFAULT '',
    fields jsonb NOT NULL DEFAULT '{}',
    source varchar(1000) NOT NULL DEFAULT '',
    status varchar(10) NOT NULL DEFAULT 'approved',
    version integer NOT NULL DEFAULT 1
);
CREATE TABLE catalog_vehicle (
    id uuid PRIMARY KEY,
    name varchar(160) NOT NULL DEFAULT '',
    category varchar(24) NOT NULL DEFAULT 'other',
    status varchar(10) NOT NULL DEFAULT 'draft',
    card_type varchar(12) NOT NULL DEFAULT 'wagon',
    wagon_number varchar(80) NOT NULL DEFAULT '',
    operator varchar(80) NOT NULL DEFAULT '',
    litt varchar(40) NOT NULL DEFAULT '',
    manufacturer varchar(80) NOT NULL DEFAULT '',
    article_number varchar(80) NOT NULL DEFAULT '',
    scale varchar(20) NOT NULL DEFAULT 'H0',
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    owner_id uuid NOT NULL REFERENCES catalog_user (id),
    prototype_overrides jsonb NOT NULL DEFAULT '[]',
    prototype_snapshot jsonb NOT NULL DEFAULT '{}',
    prototype_version integer,
    prototype_id uuid REFERENCES catalog_prototypetype (id),
    region varchar(2) NOT NULL DEFAULT 'SE',
    field_sources jsonb NOT NULL DEFAULT '{}',
    labels varchar(2000)[] NOT NULL DEFAULT '{}',
    model_fields jsonb NOT NULL DEFAULT '{}',
    prototype_fields jsonb NOT NULL DEFAULT '{}',
    prototype_source_url varchar(2000) NOT NULL DEFAULT '',
    research_evidence jsonb NOT NULL DEFAULT '{}',
    reference_snapshot jsonb NOT NULL DEFAULT '{}',
    print_diagonal boolean NOT NULL DEFAULT false,
    UNIQUE (id, owner_id)
);
CREATE TABLE catalog_vehicleimage (
    id uuid PRIMARY KEY,
    display varchar(100) NOT NULL,
    thumbnail varchar(100) NOT NULL,
    original varchar(100) NOT NULL DEFAULT '',
    angle varchar(20) NOT NULL DEFAULT 'side',
    is_main boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    vehicle_id uuid NOT NULL REFERENCES catalog_vehicle (id),
    position integer NOT NULL DEFAULT 0,
    background_mask varchar(100) NOT NULL DEFAULT '',
    background_settings jsonb NOT NULL DEFAULT '{}',
    background_style varchar(16) NOT NULL DEFAULT 'original',
    presentation varchar(100) NOT NULL DEFAULT '',
    presentation_thumbnail varchar(100) NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX image_one_main ON catalog_vehicleimage (vehicle_id) WHERE is_main;
CREATE TABLE catalog_tag (
    id uuid PRIMARY KEY,
    name varchar(32) NOT NULL,
    kind varchar(20) NOT NULL DEFAULT 'sim',
    created_at timestamptz NOT NULL DEFAULT now(),
    owner_id uuid NOT NULL REFERENCES catalog_user (id),
    UNIQUE (id, owner_id),
    UNIQUE (owner_id, name)
);
CREATE TABLE catalog_tagidentifier (
    id bigserial PRIMARY KEY,
    namespace varchar(32) NOT NULL,
    value varchar(160) NOT NULL,
    tag_id uuid NOT NULL REFERENCES catalog_tag (id),
    UNIQUE (namespace, value)
);
CREATE TABLE catalog_tagassignment (
    id uuid PRIMARY KEY,
    started_at timestamptz NOT NULL,
    ended_at timestamptz,
    owner_id uuid NOT NULL REFERENCES catalog_user (id),
    tag_id uuid NOT NULL REFERENCES catalog_tag (id),
    vehicle_id uuid NOT NULL,
    FOREIGN KEY (vehicle_id, owner_id) REFERENCES catalog_vehicle (id, owner_id)
);
CREATE UNIQUE INDEX one_active_vehicle_per_tag ON catalog_tagassignment (tag_id)
    WHERE ended_at IS NULL;
CREATE UNIQUE INDEX one_active_tag_per_vehicle ON catalog_tagassignment (vehicle_id)
    WHERE ended_at IS NULL;
CREATE TABLE catalog_tagevent (
    id bigserial PRIMARY KEY,
    event varchar(10) NOT NULL,
    at timestamptz NOT NULL,
    by_user_id uuid NOT NULL REFERENCES catalog_user (id),
    tag_id uuid NOT NULL REFERENCES catalog_tag (id),
    vehicle_id uuid REFERENCES catalog_vehicle (id)
);
"""


def at(month: int, day: int) -> datetime:
    return datetime(2026, month, day, 12, tzinfo=UTC)


@contextmanager
def fresh_database() -> Iterator[str]:
    """A database of its own, as conftest.py makes them: here for the old TrainCatalog."""
    admin = os.environ.get(ENV, "").strip()
    if not admin:
        if os.environ.get("CI"):
            pytest.fail(f"{ENV} saknas i CI: databastesterna för Catalog måste köras.")
        pytest.skip(f"{ENV} saknas: inga databastester för Catalog.")
    name = f"traincatalog_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield conninfo.make_conninfo(admin, dbname=name)
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def add_vehicle(conn: psycopg.Connection[Any], **values: Any) -> None:
    row = {
        "created_at": at(1, 2),
        "updated_at": at(1, 3),
        "prototype_fields": {},
        "model_fields": {},
        "prototype_snapshot": {},
        "prototype_overrides": [],
        **values,
    }
    for key in ("prototype_fields", "model_fields", "prototype_snapshot", "prototype_overrides"):
        row[key] = Jsonb(row[key])
    names = ", ".join(row)
    conn.execute(
        f"INSERT INTO catalog_vehicle ({names}) VALUES ({', '.join(['%s'] * len(row))})",
        list(row.values()),
    )


def fill_old(url: str) -> None:
    with psycopg.connect(url) as conn:
        conn.execute(OLD_SCHEMA)
        for user, email, verified in (
            (ONE, ONE_EMAIL, True),
            (TWO, TWO_EMAIL, False),
            (THREE, THREE_EMAIL, True),
        ):
            conn.execute(
                "INSERT INTO catalog_user (id, email, display_name, first_name) "
                "VALUES (%s, %s, 'Provägare', 'Prov')",
                (user, email),
            )
            conn.execute(
                'INSERT INTO account_emailaddress (email, verified, "primary", user_id) '
                "VALUES (%s, %s, true, %s)",
                (email, verified, user),
            )
        conn.execute(
            "INSERT INTO catalog_prototypetype (id, name, operator, litt) "
            "VALUES (%s, 'Rc6', 'SJ', 'Rc6')",
            (PROTOTYPE,),
        )
        add_vehicle(
            conn,
            id=HBIS,
            owner_id=ONE,
            name="Hbis med skjutväggar",
            category="freight_wagon",
            status="ready",
            wagon_number="21 74 245 2 253-0",
            operator="Green Cargo",
            litt="Hbis",
            manufacturer="Roco",
            article_number="76543",
            prototype_fields={
                "epoch": "V",
                "prototype_length": "14.5",
                "brake": "KE-GP",
                "riv": True,
            },
            model_fields={
                "notes": "Ny hjulsats 2025",
                "inventory_number": "17",
                "home_region": "red",
                "coupler": "Kadee",
            },
            labels=["Malmbanan", "Väderskydd"],
        )
        add_vehicle(
            conn,
            id=RC6,
            owner_id=ONE,
            name="Rc6 1340",
            category="locomotive",
            status="ready",
            wagon_number="1340",
            litt="Rc6",
            model_fields={"dcc_address": "1340"},
            prototype_id=PROTOTYPE,
            prototype_version=1,
            prototype_snapshot={
                "name": "Rc6",
                "operator": "SJ",
                "litt": "Rc6",
                "epoch": "IV",
                "max_speed": "160",
            },
            prototype_overrides=["litt"],
            created_at=at(1, 4),
        )
        add_vehicle(
            conn, id=UNNAMED, owner_id=ONE, name="Okänd vagn", status="ready", created_at=at(1, 5)
        )
        add_vehicle(
            conn,
            id=COACH,
            owner_id=ONE,
            name="B7 med belysning",
            category="passenger_coach",
            status="ready",
            litt="B7",
            wagon_number="5114",
            prototype_fields={"epoch": "III–IV (1950–1975)"},
            model_fields={"dcc_address": "3"},
            created_at=at(1, 6),
        )
        add_vehicle(
            conn,
            id=WRONG,
            owner_id=ONE,
            name="Hbis med fel siffra",
            category="freight_wagon",
            status="ready",
            litt="Hbis",
            wagon_number="21 74 245 2 253-1",
            created_at=at(1, 7),
        )
        add_vehicle(
            conn,
            id=TWOS,
            owner_id=TWO,
            name="Gbs",
            category="freight_wagon",
            status="ready",
            litt="Gbs",
            created_at=at(1, 8),
        )
        for picture, vehicle, position, main, original in (
            (PICTURES[0], HBIS, 0, False, False),
            (PICTURES[1], HBIS, 1, True, True),
            (PICTURES[2], RC6, 0, True, False),  # its file is gone
            (PICTURES[3], TWOS, 0, True, False),
        ):
            conn.execute(
                "INSERT INTO catalog_vehicleimage (id, vehicle_id, display, thumbnail, original, "
                "is_main, position) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    picture,
                    vehicle,
                    f"display/{ONE}/{picture}.jpg",
                    f"thumbs/{ONE}/{picture}.jpg",
                    f"originals/{ONE}/{picture}.jpg" if original else "",
                    main,
                    position,
                ),
            )
        for tag, name, kind, namespace, value in (
            (NFC_TAG, NFC_UID, "nfc", "iso14443a_uid", NFC_UID),
            (SIM_TAG, "SIM-001", "sim", "sim", SIM_UID),
            (TAKEN_TAG, TAKEN_UID, "nfc", "iso14443a_uid", TAKEN_UID),
        ):
            conn.execute(
                "INSERT INTO catalog_tag (id, name, kind, owner_id) VALUES (%s, %s, %s, %s)",
                (tag, name, kind, ONE),
            )
            conn.execute(
                "INSERT INTO catalog_tagidentifier (namespace, value, tag_id) VALUES (%s, %s, %s)",
                (namespace, value, tag),
            )
        # The NFC tag sat on the locomotive in January, and is on the wagon since March.
        for tag, vehicle, started, ended in (
            (NFC_TAG, RC6, at(1, 10), at(2, 1)),
            (SIM_TAG, RC6, at(2, 5), None),
            (NFC_TAG, HBIS, at(3, 1), None),
            (TAKEN_TAG, COACH, at(4, 1), None),
        ):
            conn.execute(
                "INSERT INTO catalog_tagassignment (id, started_at, ended_at, owner_id, tag_id, "
                "vehicle_id) VALUES (%s, %s, %s, %s, %s, %s)",
                (uuid.uuid4(), started, ended, ONE, tag, vehicle),
            )
        for tag, vehicle, event, when in (
            (NFC_TAG, RC6, "linked", at(1, 10)),
            (NFC_TAG, RC6, "unlinked", at(2, 1)),
            (SIM_TAG, RC6, "linked", at(2, 5)),
            (NFC_TAG, HBIS, "linked", at(3, 1)),
            (TAKEN_TAG, COACH, "linked", at(4, 1)),
        ):
            conn.execute(
                "INSERT INTO catalog_tagevent (event, at, by_user_id, tag_id, vehicle_id) "
                "VALUES (%s, %s, %s, %s, %s)",
                (event, when, ONE, tag, vehicle),
            )


def jpeg(colour: tuple[int, int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (96, 64), colour).save(out, format="JPEG")
    return out.getvalue()


@pytest.fixture
def old_url() -> Iterator[str]:
    with fresh_database() as url:
        fill_old(url)
        yield url


@pytest.fixture
def media(tmp_path: Path) -> Path:
    """The old MEDIA_ROOT: the display pictures, and the original kept with Spara original.
    The locomotive's picture is missing."""
    folder = tmp_path / "media"
    for picture, colour in ((PICTURES[0], (120, 40, 30)), (PICTURES[1], (30, 90, 140))):
        display = folder / "display" / str(ONE) / f"{picture}.jpg"
        display.parent.mkdir(parents=True, exist_ok=True)
        display.write_bytes(jpeg(colour))
    original = folder / "originals" / str(ONE) / f"{PICTURES[1]}.jpg"
    original.parent.mkdir(parents=True)
    original.write_bytes(jpeg((30, 90, 141)))
    two = folder / "display" / str(ONE) / f"{PICTURES[3]}.jpg"
    two.write_bytes(jpeg((10, 10, 10)))
    return folder


@pytest.fixture
def new_url(database_url: str) -> str:
    migrate.migrate(database_url)
    return database_url


def env_for(tmp_path: Path, **more: str) -> dict[str, str]:
    return {
        "CATALOG_FLYTT_PEPPER": PEPPER,
        "CATALOG_PICTURES_DIR": str(tmp_path / "bilder"),
        **more,
    }


def run(
    capsys: pytest.CaptureFixture[str],
    old_url: str,
    media: Path,
    new_url: str,
    tmp_path: Path,
    *extra: str,
) -> str:
    code = main(
        ["--gammal", old_url, "--bilder", str(media), "--ny", new_url, *extra], env_for(tmp_path)
    )
    out, err = capsys.readouterr()
    assert code == 0, err
    return out


def rows(url: str, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as conn:
        return conn.execute(sql, args).fetchall()


def counts(url: str) -> dict[str, int]:
    """Every table's rows in Catalog's database."""
    with psycopg.connect(url) as conn:
        tables = [
            str(row[0])
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        ]
        found: dict[str, int] = {}
        for table in tables:
            row = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()
            assert row is not None
            found[table] = int(row[0])
        return found


def catalog_app(new_url: str, tmp_path: Path, pretend: PretendId) -> TestClient:
    (tmp_path / "web").mkdir(exist_ok=True)
    (tmp_path / "web" / "index.html").write_text("<!doctype html><title>TrainMeet Catalog</title>")
    settings = Settings(
        database_url=new_url,
        migrate="auto",
        web_dir=tmp_path / "web",
        id=id_settings(),
        build=CatalogVersion(version="0.1.0"),
        tag_base=BASE,
        pictures_dir=tmp_path / "bilder",
        flytt_pepper=PEPPER.encode(),
    )
    http = httpx.Client(transport=httpx.MockTransport(pretend.handle))
    return TestClient(create_app(settings, id_http=http), follow_redirects=False)


def log_in(client: TestClient, pretend: PretendId, person: str, **claims: Any) -> httpx.Response:
    pretend.claims = claims
    return back_from_id(client, pretend, to_id(client), person)


# --- The script -------------------------------------------------------------------------------


def test_a_dry_run_writes_nothing_and_says_what_the_run_will_do(
    old_url: str,
    media: Path,
    new_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = counts(new_url)
    dry = run(capsys, old_url, media, new_url, tmp_path, "--provkorning")
    assert counts(new_url) == before
    assert not (tmp_path / "bilder").exists() or not any((tmp_path / "bilder").rglob("*.*"))
    assert (
        dry.splitlines()[0] == "Flytten från gamla TrainCatalog: provkörning, inget har skrivits."
    )
    assert "Konton i gamla TrainCatalog: 3, varav 2 med fordon eller taggar." in dry
    assert "Fordon: 5 nya, 0 flyttade förut." in dry
    assert "Bilder: 2 nya, 0 flyttade förut." in dry
    assert "Taggar: 3 nya, 0 flyttade förut." in dry
    assert "Inte i TrainMeet ID än: 1 ägare har inte loggat in i Catalog med ID." in dry
    for why in (NO_VERIFIED, VEHICLE_OWNER, PICTURE_MISSING, PICTURE_VEHICLE):
        assert f"- 1 {why}" in dry
    # The run does what the dry run said.
    real = run(capsys, old_url, media, new_url, tmp_path)
    assert real.splitlines()[0] == "Flytten från gamla TrainCatalog är körd."
    assert real.splitlines()[1:] == dry.splitlines()[1:]


def test_the_run_moves_vehicles_pictures_tags_and_their_history(
    old_url: str,
    media: Path,
    new_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = run(capsys, old_url, media, new_url, tmp_path)
    assert "Kopplingar: 4 nya, 0 flyttade förut." in report
    assert "Tagghändelser: 5 nya, 0 flyttade förut." in report
    assert "Utkast: 1 fordon som var sparade blir utkast" in report
    assert "För långa värden: 1 värden" in report

    # One waiting fleet, for the account with a verified address, holding ONE's vehicles with
    # the ids they had, dated as they were made.
    [(waiting_owner, name)] = rows(
        new_url, "SELECT o.id, o.name FROM owner o JOIN waiting_fleet w ON w.owner_id = o.id"
    )
    assert name == waiting.WAITING_NAME
    vehicles = dict(rows(new_url, "SELECT id, owner_id FROM vehicle"))
    assert vehicles == dict.fromkeys([HBIS, RC6, UNNAMED, COACH, WRONG], waiting_owner)
    [(created, since)] = rows(
        new_url,
        "SELECT v.created_at, o.since FROM vehicle v JOIN vehicle_owner o ON o.vehicle_id = v.id "
        "WHERE v.id = %s",
        HBIS,
    )
    assert created == since == at(1, 2)

    # The pictures through Catalog's own upload: two files each, the main picture as it was,
    # and the original only where Spara original kept one.
    pictures = rows(
        new_url,
        "SELECT position, is_main, original_key IS NOT NULL, owner_id FROM picture "
        "WHERE vehicle_id = %s ORDER BY position",
        HBIS,
    )
    assert pictures == [(0, False, False, waiting_owner), (1, True, True, waiting_owner)]
    assert len(list((tmp_path / "bilder").rglob("*.jpg"))) == 5

    # The tags keep their uid; the links and the events keep their dates.
    tags = dict(
        rows(new_url, "SELECT i.value, t.kind FROM tag t JOIN tag_identifier i ON i.tag_id = t.id")
    )
    assert tags == {NFC_UID: "nfc", SIM_UID: "sim", TAKEN_UID: "nfc"}
    links = rows(
        new_url,
        "SELECT i.value, a.vehicle_id, a.slot, a.started_at, a.ended_at FROM tag_assignment a "
        "JOIN tag_identifier i ON i.tag_id = a.tag_id ORDER BY a.started_at",
    )
    assert links == [
        (NFC_UID, RC6, "nfc", at(1, 10), at(2, 1)),
        (SIM_UID, RC6, "nfc", at(2, 5), None),
        (NFC_UID, HBIS, "nfc", at(3, 1), None),
        (TAKEN_UID, COACH, "nfc", at(4, 1), None),
    ]
    events = rows(new_url, "SELECT event, at, by_owner FROM tag_event ORDER BY at")
    assert [(e, when) for e, when, _ in events] == [
        ("linked", at(1, 10)),
        ("unlinked", at(2, 1)),
        ("linked", at(2, 5)),
        ("linked", at(3, 1)),
        ("linked", at(4, 1)),
    ]
    assert {by for _, _, by in events} == {waiting_owner}

    # The old TrainCatalog is only read.
    assert rows(old_url, "SELECT count(*) FROM catalog_vehicle") == [(6,)]


def test_a_second_run_moves_nothing_twice_and_a_later_one_only_what_is_new(
    old_url: str,
    media: Path,
    new_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run(capsys, old_url, media, new_url, tmp_path)
    after_first = counts(new_url)
    again = run(capsys, old_url, media, new_url, tmp_path)
    assert counts(new_url) == after_first
    assert "Fordon: 0 nya, 5 flyttade förut." in again
    assert "Bilder: 0 nya, 2 flyttade förut." in again
    assert "Taggar: 0 nya, 3 flyttade förut." in again
    assert "Ägare: 0 nya väntande vagnparker." in again

    # The old TrainCatalog is still in use until the new one is tried (CAT-206): a new vehicle
    # there, and the tag moved to it.
    newer = uuid.uuid4()
    with psycopg.connect(old_url) as conn:
        add_vehicle(
            conn,
            id=newer,
            owner_id=ONE,
            category="freight_wagon",
            status="ready",
            litt="Gbs",
            wagon_number="21 74 151 5 005-1",
            created_at=at(5, 1),
        )
        conn.execute(
            "UPDATE catalog_tagassignment SET ended_at = %s WHERE tag_id = %s AND ended_at IS NULL",
            (at(5, 2), NFC_TAG),
        )
        conn.execute(
            "INSERT INTO catalog_tagassignment (id, started_at, owner_id, tag_id, vehicle_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            (uuid.uuid4(), at(5, 2), ONE, NFC_TAG, newer),
        )
    later = run(capsys, old_url, media, new_url, tmp_path)
    assert "Fordon: 1 nya, 5 flyttade förut." in later
    assert "Kopplingar: 1 nya, 4 flyttade förut." in later
    assert "Kopplingar som har avslutats i gamla TrainCatalog: 1." in later
    active = rows(
        new_url,
        "SELECT a.vehicle_id FROM tag_assignment a JOIN tag_identifier i ON i.tag_id = a.tag_id "
        "WHERE i.value = %s AND a.ended_at IS NULL",
        NFC_UID,
    )
    assert active == [(newer,)]


def test_the_old_fields_are_kept_with_their_labels_and_the_core_fields_come_from_the_import(
    old_url: str,
    media: Path,
    new_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run(capsys, old_url, media, new_url, tmp_path)
    db = Database(new_url)
    db.open()
    try:
        fleet = Fleet(db)
        [(owner,)] = rows(new_url, "SELECT owner_id FROM waiting_fleet")
        hbis = fleet.get(owner, HBIS)
        rc6 = fleet.get(owner, RC6)
        unnamed = fleet.get(owner, UNNAMED)
        coach = fleet.get(owner, COACH)
    finally:
        db.close()
    assert (hbis.kind, hbis.litt, hbis.operator, hbis.epoch, hbis.scale) == (
        "freight_wagon",
        "Hbis",
        "Green Cargo",
        "V",
        "H0",
    )
    assert (hbis.maker, hbis.article_number, hbis.note) == ("Roco", "76543", "Ny hjulsats 2025")
    assert hbis.field_sources == dict.fromkeys(
        ["kind", "litt", "number", "operator", "epoch", "scale", "maker", "article_number", "note"],
        FieldSource.IMPORT,
    )
    assert hbis.legacy == {
        "Benämning": "Hbis med skjutväggar",
        "Broms": "KE-GP",
        "L ö b": "14,5 m",
        "RIV": "Ja",
        "Koppel-typ": "Kadee",
        "Egna etiketter": "Malmbanan, Väderskydd",
        "Inventarienummer": "17",
        "Hemstationens regionfärg": "Röd",
        "Region": "SE",
    }
    # A locomotive keeps its DCC address; what it inherited from its old prototype is kept.
    assert (rc6.dcc_address, rc6.operator, rc6.epoch) == ("1340", "SJ", "IV")
    assert rc6.legacy["Sth"] == "160 km/h"
    assert rc6.legacy["Förebild"] == "Rc6"
    # Ready needs a litt or a number here (CAT-62): the vehicle without them is a draft.
    assert unnamed.status is VehicleStatus.DRAFT
    assert unnamed.legacy["Benämning"] == "Okänd vagn"
    # A coach has no DCC address among the core fields, and the epoch is too long for one.
    assert (coach.dcc_address, coach.epoch) == ("", "")
    assert coach.legacy["DCC-adress"] == "3"
    assert coach.legacy["Epok"] == "III–IV (1950–1975)"


def test_an_evn_keeps_its_painted_check_digit(
    old_url: str,
    media: Path,
    new_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run(capsys, old_url, media, new_url, tmp_path)
    db = Database(new_url)
    db.open()
    try:
        [(owner,)] = rows(new_url, "SELECT owner_id FROM waiting_fleet")
        right = Fleet(db).get(owner, HBIS)
        wrong = Fleet(db).get(owner, WRONG)
    finally:
        db.close()
    assert right.number == "21 74 245 2 253-0"
    assert right.evn is not None
    assert (right.evn.check, right.evn.given, right.evn.valid) == (0, 0, True)
    # A painted check digit that is wrong is reported, never corrected (CAT-59).
    assert wrong.number == "21 74 245 2 253-1"
    assert wrong.evn is not None
    assert (wrong.evn.check, wrong.evn.given, wrong.evn.valid) == (0, 1, False)


def test_another_persons_tag_in_the_new_catalog_is_reported_and_skipped(
    old_url: str,
    media: Path,
    new_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    someone = uuid.uuid4()
    db = Database(new_url)
    db.open()
    try:
        with db.transaction() as conn:
            conn.execute("INSERT INTO owner (id, name) VALUES (%s, 'Provkonto B')", (someone,))
        fields = VehicleFields(
            status=VehicleStatus.READY, kind=VehicleKind.FREIGHT_WAGON, litt="Gbs"
        )
        theirs = Fleet(db).create(someone, fields).id
        Tags(db, base=BASE, simulated=False).link(
            someone, TAKEN_UID.upper(), TagLink(vehicle=theirs, confirm=True)
        )
    finally:
        db.close()
    report = run(capsys, old_url, media, new_url, tmp_path)
    assert f"- 1 {TAG_TAKEN}" in report
    assert "Taggar: 2 nya" in report
    links = rows(
        new_url,
        "SELECT a.owner_id, a.vehicle_id FROM tag_assignment a "
        "JOIN tag_identifier i ON i.tag_id = a.tag_id WHERE i.value = %s",
        TAKEN_UID,
    )
    assert links == [(someone, theirs)]


def test_the_move_needs_the_pepper_and_an_up_to_date_catalog(
    old_url: str, media: Path, database_url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--gammal", old_url, "--bilder", str(media), "--ny", database_url]
    assert main(args, {}) == 2
    assert "CATALOG_FLYTT_PEPPER saknas" in capsys.readouterr().err
    assert main(args, {"CATALOG_FLYTT_PEPPER": "för-kort"}) == 2
    assert "minst 32 tecken" in capsys.readouterr().err
    assert main(args, env_for(tmp_path)) == 1  # no migrations yet
    assert "0014_flytten" in capsys.readouterr().err


def test_carry_reads_an_old_vehicle_as_the_old_card_showed_it() -> None:
    old = OldVehicle(
        id=uuid.uuid4(),
        owner=ONE,
        name="",
        category="locomotive",
        status="draft",
        wagon_number="",
        operator="",
        litt="",
        manufacturer="",
        article_number="",
        scale="H0",
        region="US",
        prototype_fields={"built_years": "1948", "length_ft": "50.5", "uic_type": "x" * 3},
        model_fields={"dcc_address": "123456789", "rp25": False},
        labels=[],
        prototype_id=None,
        prototype_snapshot={},
        prototype_overrides=[],
        prototype_source_url="https://example.org/forebild",
        created_at=at(1, 1),
        updated_at=at(1, 1),
    )
    carried = carry(old)
    assert carried.fields.status is VehicleStatus.DRAFT
    assert carried.fields.dcc_address == ""
    assert carried.too_long == 1
    assert carried.legacy == {
        "DCC-adress": "123456789",
        "UIC-typ": "xxx",
        "Byggnadsår (BLT)": "1948",
        "RP 25": "Nej",
        "Längd": "50,5 ft",
        "Källa": "https://example.org/forebild",
        "Region": "US",
    }


# --- The waiting fleet, taken over at the first login ----------------------------------------


def test_a_waiting_fleet_becomes_the_persons_at_the_first_login_with_a_verified_address(
    old_url: str,
    media: Path,
    new_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run(capsys, old_url, media, new_url, tmp_path)
    [(waiting_owner,)] = rows(new_url, "SELECT owner_id FROM waiting_fleet")
    pretend = PretendId()
    person = str(uuid.uuid4())
    with catalog_app(new_url, tmp_path, pretend) as client:
        # ID gives the address as the person typed it.
        answer = log_in(client, pretend, person, email=" Agare.Ett@Example.ORG ")
        assert answer.status_code == 303
        listed = client.get(f"{API}/vehicles").json()
        assert listed["total"] == 5
        card = client.get(f"{API}/vehicles/{HBIS}").json()
        assert card["legacy"]["L ö b"] == "14,5 m"
        assert card["picture"] is not None
        assert [tag["uid"] for tag in card["tags"]] == [NFC_UID]
        assert client.get(f"{API}/tags/{NFC_UID}").json()["outcome"] == "mine"
        assert len(client.get(f"{API}/tags/{NFC_UID}/events").json()) == 3
        # The account export has the old fields (CAT-188).
        export = client.get(f"{API}/export")
        assert export.status_code == 200
        with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
            data = json.loads(archive.read("catalog.json"))
            assert len([n for n in archive.namelist() if n.startswith("bilder/")]) == 3
        exported = {v["id"]: v for v in data["vehicles"]}
        assert exported[str(HBIS)]["legacy"]["Benämning"] == "Hbis med skjutväggar"
        # The person's fleet, everything in it, and the hash is gone.
        assert rows(new_url, "SELECT count(*) FROM waiting_fleet") == [(0,)]
        assert rows(new_url, "SELECT count(*) FROM owner WHERE id = %s", waiting_owner) == [(0,)]
        for table, column in (
            ("vehicle", "owner_id"),
            ("vehicle_owner", "owner_id"),
            ("picture", "owner_id"),
            ("picture", "uploaded_by"),
            ("tag", "owner_id"),
            ("tag_assignment", "owner_id"),
            ("tag_event", "by_owner"),
        ):
            assert rows(new_url, f"SELECT DISTINCT {column}::text FROM {table}") == [(person,)]
        assert rows(new_url, "SELECT new_id FROM flytt_map WHERE kind = 'owner'") == [(person,)]
        # Coming back takes nothing more, and a later run adds to the person's own fleet.
        client.delete(f"{API}/session")
        log_in(client, pretend, person, email=ONE_EMAIL)
        assert client.get(f"{API}/vehicles").json()["total"] == 5
    again = run(capsys, old_url, media, new_url, tmp_path)
    assert "1 ägare har redan tagit över sin vagnpark." in again
    assert "Inte i TrainMeet ID än: 0 ägare" in again


def test_another_or_an_unverified_address_takes_nothing_over(
    old_url: str,
    media: Path,
    new_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run(capsys, old_url, media, new_url, tmp_path)
    pretend = PretendId()
    with catalog_app(new_url, tmp_path, pretend) as client:
        log_in(client, pretend, str(uuid.uuid4()), email="nagon.annan@example.org")
        assert client.get(f"{API}/vehicles").json()["total"] == 0
        client.delete(f"{API}/session")
        # ID must say that the address is verified: without it there is no login (KONTO-10),
        # and the fleet still waits.
        refused = log_in(client, pretend, str(uuid.uuid4()), email=ONE_EMAIL, email_verified=False)
        assert refused.headers["location"].startswith("/logga-in?")
        assert client.get(f"{API}/session").json()["account"] is None
    assert rows(new_url, "SELECT count(*) FROM waiting_fleet") == [(1,)]
    assert verified_email({"email": ONE_EMAIL, "email_verified": False}) is None
    assert verified_email({"email": ONE_EMAIL}) is None
    assert verified_email({"email": ONE_EMAIL, "email_verified": True}) == ONE_EMAIL
    # Hashed with another pepper, the same address finds nothing either.
    person = uuid.uuid4()
    db = Database(new_url)
    db.open()
    try:
        with db.transaction() as conn:
            conn.execute("INSERT INTO owner (id, name) VALUES (%s, 'Prov')", (person,))
        other = waiting.email_hash(secrets.token_bytes(32), ONE_EMAIL)
        assert waiting.claim(db, person, other) is None
    finally:
        db.close()


def test_the_places_of_a_waiting_fleet_go_with_it_and_a_name_the_person_has_is_theirs(
    old_url: str,
    media: Path,
    new_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run(capsys, old_url, media, new_url, tmp_path)
    [(fleet,)] = rows(new_url, "SELECT owner_id FROM waiting_fleet")
    person, box, theirs, shelf = (uuid.uuid4() for _ in range(4))
    with psycopg.connect(new_url) as conn:
        conn.execute("INSERT INTO owner (id, name) VALUES (%s, 'Prov')", (person,))
        conn.execute(
            "INSERT INTO place (id, owner_id, name) VALUES (%s, %s, 'Låda 1')", (box, person)
        )
        for place, name in ((theirs, "Låda 1"), (shelf, "Hyllan")):
            conn.execute(
                "INSERT INTO place (id, owner_id, name) VALUES (%s, %s, %s)", (place, fleet, name)
            )
        conn.execute("UPDATE vehicle SET place_id = %s WHERE id = %s", (theirs, HBIS))
        conn.execute("UPDATE vehicle SET place_id = %s WHERE id = %s", (shelf, RC6))
    db = Database(new_url)
    db.open()
    try:
        hashed = waiting.email_hash(PEPPER.encode(), ONE_EMAIL.upper())
        claimed = waiting.claim(db, person, hashed)
        assert claimed == waiting.Claimed(waiting=fleet, vehicles=5)
        assert waiting.claim(db, person, hashed) is None
    finally:
        db.close()
    places = dict(rows(new_url, "SELECT name, owner_id FROM place"))
    assert places == {"Låda 1": person, "Hyllan": person}
    homes = dict(rows(new_url, "SELECT id, place_id FROM vehicle WHERE place_id IS NOT NULL"))
    assert homes == {HBIS: box, RC6: shelf}


# --- The old addresses -------------------------------------------------------------------------


def test_the_old_addresses_go_on_for_good(
    old_url: str,
    media: Path,
    new_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run(capsys, old_url, media, new_url, tmp_path)
    pretend = PretendId()
    with catalog_app(new_url, tmp_path, pretend) as client:
        moved = {
            "/t/04:A1:B2:C3:D4:E5:F6/": f"/t/{NFC_UID}",
            f"/t/{NFC_UID}/": f"/t/{NFC_UID}",
            f"/t/sim:{SIM_UID.upper()}": f"/t/{SIM_UID}",
            f"/fordon/{HBIS}/redigera": f"/fordon/{HBIS}/andra",
            "/nytt": "/fordon/nytt",
            "/nytt/flera": "/fordon/nytt/flera",
            "/konto": "/fordon",
            "/accounts/login/?next=/t/04a1b2c3d4e5f6": "/logga-in?next=/t/04a1b2c3d4e5f6",
        }
        for old, new in moved.items():
            answer = client.get(old)
            assert (answer.status_code, answer.headers.get("location")) == (301, new), old
        # The tag's and the vehicle's own addresses are Catalog's too: the page itself.
        for same in (f"/t/{NFC_UID}", f"/t/{SIM_UID}", f"/fordon/{HBIS}", "/fordon", "/blippa"):
            assert client.get(same).status_code == 200, same
        # The lookup finds the moved tag from the old forms of its uid, and a visitor gets the
        # mini card: never the old fields (CAT-205).
        for uid in (NFC_UID, "04:A1:B2:C3:D4:E5:F6", NFC_UID.upper()):
            looked = client.get(f"{API}/tags/{uid}")
            assert looked.json()["outcome"] == "private", uid
            assert looked.json()["card"]["litt"] == "Hbis"
            assert "legacy" not in looked.text and "Benämning" not in looked.text
    assert new_address("/t/inte-en-tagg") is None
    assert new_address("/fordon") is None


# --- Nothing personal in the log ---------------------------------------------------------------


def test_the_log_and_the_database_hold_no_email_address(
    old_url: str,
    media: Path,
    new_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    shown = run(capsys, old_url, media, new_url, tmp_path, "--provkorning")
    shown += run(capsys, old_url, media, new_url, tmp_path)
    pretend = PretendId()
    with catalog_app(new_url, tmp_path, pretend) as client:
        log_in(client, pretend, str(uuid.uuid4()), email=ONE_EMAIL)
    out, err = capsys.readouterr()
    for text in (shown, out, err, caplog.text):
        assert "@" not in text
        assert "example.org" not in text.lower()
        assert "Provägare" not in text
    for table in counts(new_url):
        found = rows(
            new_url, f'SELECT count(*) FROM "{table}" t WHERE t::text ILIKE %s', "%example.org%"
        )
        assert found == [(0,)], table


def test_a_dry_run_counts_the_pictures_limits_as_the_upload_does(
    old_url: str, media: Path, new_url: str, tmp_path: Path
) -> None:
    old = read_old(old_url)
    db = Database(new_url)
    db.open()
    try:
        pictures = Pictures(
            db,
            DiskStore(tmp_path / "bilder", secrets.token_bytes(32)),
            PictureLimits(per_vehicle=1),
        )
        dry = Move(old, media, db, pictures, PEPPER.encode(), dry=True).run()
        real = Move(old, media, db, pictures, PEPPER.encode(), dry=False).run()
    finally:
        db.close()
    for report in (dry, real):
        assert report.pictures.new == 1
        assert report.skipped[PICTURE_FULL] == 1
    assert dry.text().splitlines()[1:] == real.text().splitlines()[1:]
