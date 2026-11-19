"""CAD's migrations run once, in order, and a database that differs from the code stops the
start, as Catalog's."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from cad import migrate


def write(folder: Path, name: str, sql: str) -> None:
    (folder / name).write_text(sql, encoding="utf-8")


def test_the_real_migrations_are_numbered_without_gaps() -> None:
    found = migrate.migrations()
    assert [m.version for m in found] == list(range(1, len(found) + 1))
    assert [m.name for m in found[:2]] == ["grunden", "modulbiblioteket"]


def test_migrate_runs_each_once_and_check_sees_nothing_missing(database_url: str) -> None:
    everything = migrate.migrations()
    assert migrate.check(database_url) == everything
    assert migrate.migrate(database_url) == everything
    assert migrate.migrate(database_url) == []
    assert migrate.check(database_url) == []
    assert migrate.current_version(database_url) == len(everything)
    with psycopg.connect(database_url) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }
    assert {
        "person",
        "login_session",
        "id_login",
        "cad_migration",
        "module",
        "module_version",
        "module_event",
        "gable_profile",
    } <= tables


def test_a_changed_migration_stops_the_start(database_url: str, tmp_path: Path) -> None:
    write(tmp_path, "0001_first.sql", "CREATE TABLE thing (id integer);")
    migrate.migrate(database_url, tmp_path)
    write(tmp_path, "0001_first.sql", "CREATE TABLE thing (id bigint);")
    with pytest.raises(migrate.MigrationError, match="har ändrats"):
        migrate.check(database_url, tmp_path)


def test_a_database_newer_than_the_code_stops_the_start(database_url: str, tmp_path: Path) -> None:
    write(tmp_path, "0001_first.sql", "CREATE TABLE thing (id integer);")
    write(tmp_path, "0002_second.sql", "ALTER TABLE thing ADD COLUMN name text;")
    migrate.migrate(database_url, tmp_path)
    (tmp_path / "0002_second.sql").unlink()
    with pytest.raises(migrate.MigrationError, match="nyare än koden"):
        migrate.check(database_url, tmp_path)


def test_a_version_is_never_changed_in_place_by_the_schema(database_url: str) -> None:
    """A module's versions are rows of their own: two with the same number cannot exist."""
    migrate.migrate(database_url)
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            "SELECT count(*) FROM pg_constraint WHERE conrelid = 'module_version'::regclass "
            "AND contype = 'p'"
        ).fetchone()
    assert row == (1,)


def test_main_needs_the_database_address(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CAD_DATABASE_URL", raising=False)
    assert migrate.main(["cad.migrate"]) == 2
    assert "CAD_DATABASE_URL saknas" in capsys.readouterr().err
