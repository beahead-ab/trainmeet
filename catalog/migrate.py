"""Brings Catalog's database up to date with the numbered files in catalog/migrations.

    python -m catalog.migrate           # apply what is missing
    python -m catalog.migrate --check   # exit 1 if something is missing

A migration is a file NNNN_name.sql. It runs once, in a transaction of its own, and its
checksum is kept: a file that has already run must never change, so a changed file stops
the start instead of leaving two databases that differ. A database that is newer than the
code also stops the start.

In the test environment the backup is taken and verified before this runs (CAT-39,
deploy/testmiljo/catalog-backup.sh).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).parent / "migrations"
# One migration at a time, also with two containers starting together.
LOCK_KEY = 48_000_001
_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
LOGGER = logging.getLogger("catalog.migrate")


class MigrationError(RuntimeError):
    """The database and the code do not agree. The message says how."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def migrations(folder: Path = MIGRATIONS) -> list[Migration]:
    """The migrations in order. Numbers start at 1 and have no gaps."""
    found: list[Migration] = []
    for path in sorted(folder.glob("*.sql")):
        match = _NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"{path.name}: namnet ska vara NNNN_namn.sql.")
        found.append(Migration(int(match[1]), match[2], path.read_text(encoding="utf-8")))
    for expected, migration in enumerate(found, start=1):
        if migration.version != expected:
            raise MigrationError(f"Migration {expected:04d} saknas.")
    return found


def _ensure_table(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_migration (
            version integer PRIMARY KEY,
            name text NOT NULL,
            checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def pending(
    conn: psycopg.Connection[tuple[object, ...]], folder: Path = MIGRATIONS
) -> list[Migration]:
    """What is missing in the database. Raises if the database and the code disagree."""
    known = {m.version: m for m in migrations(folder)}
    exists = conn.execute("SELECT to_regclass('catalog_migration') IS NOT NULL").fetchone()
    applied: dict[int, str] = {}
    if exists is not None and exists[0]:
        rows = conn.execute("SELECT version, checksum FROM catalog_migration").fetchall()
        applied = {int(str(version)): str(checksum) for version, checksum in rows}
    for version, checksum in sorted(applied.items()):
        migration = known.get(version)
        if migration is None:
            raise MigrationError(
                f"Databasen har migration {version:04d}, som koden inte känner till. "
                "Databasen är nyare än koden."
            )
        if migration.checksum != checksum:
            raise MigrationError(
                f"Migration {version:04d}_{migration.name} har ändrats efter att den körts. "
                "Lägg ändringen i en ny migration."
            )
    return [m for v, m in sorted(known.items()) if v not in applied]


def migrate(url: str, folder: Path = MIGRATIONS) -> list[Migration]:
    """Apply what is missing, one transaction per migration. Returns what was applied."""
    applied: list[Migration] = []
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            _ensure_table(conn)
            for migration in pending(conn, folder):
                with conn.transaction():
                    conn.execute(migration.sql.encode("utf-8"))
                    conn.execute(
                        "INSERT INTO catalog_migration (version, name, checksum) "
                        "VALUES (%s, %s, %s)",
                        (migration.version, migration.name, migration.checksum),
                    )
                LOGGER.info("Migration %04d_%s är körd.", migration.version, migration.name)
                applied.append(migration)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    return applied


def check(url: str, folder: Path = MIGRATIONS) -> list[Migration]:
    """What is missing, without changing anything."""
    with psycopg.connect(url, autocommit=True) as conn:
        return pending(conn, folder)


def current_version(url: str) -> int:
    with psycopg.connect(url, autocommit=True) as conn:
        exists = conn.execute("SELECT to_regclass('catalog_migration') IS NOT NULL").fetchone()
        if exists is None or not exists[0]:
            return 0
        row = conn.execute("SELECT coalesce(max(version), 0) FROM catalog_migration").fetchone()
        return int(str(row[0])) if row else 0


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    url = os.environ.get("CATALOG_DATABASE_URL", "").strip()
    if not url:
        print("CATALOG_DATABASE_URL saknas.", file=sys.stderr)
        return 2
    try:
        if "--check" in argv[1:]:
            missing = check(url)
            for migration in missing:
                print(f"Saknas: {migration.version:04d}_{migration.name}")
            return 1 if missing else 0
        done = migrate(url)
    except MigrationError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Databasen är uppdaterad ({len(done)} nya migrationer).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
