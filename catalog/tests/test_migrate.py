"""The migrations run once, in order, and a database that differs from the code stops the start."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from catalog import migrate


def write(folder: Path, name: str, sql: str) -> None:
    (folder / name).write_text(sql, encoding="utf-8")


def test_the_real_migrations_are_numbered_without_gaps() -> None:
    found = migrate.migrations()
    assert [m.version for m in found] == list(range(1, len(found) + 1))
    assert found[0].name == "grunden"


def test_a_badly_named_or_missing_migration_stops(tmp_path: Path) -> None:
    write(tmp_path, "0001_a.sql", "SELECT 1;")
    write(tmp_path, "0003_c.sql", "SELECT 1;")
    with pytest.raises(migrate.MigrationError, match="0002 saknas"):
        migrate.migrations(tmp_path)
    write(tmp_path, "2_b.sql", "SELECT 1;")
    with pytest.raises(migrate.MigrationError, match="NNNN_namn"):
        migrate.migrations(tmp_path)


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
    assert {"owner", "login_session", "catalog_migration", "vehicle", "place"} <= tables


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


def test_a_failing_migration_leaves_nothing_half_done(database_url: str, tmp_path: Path) -> None:
    write(tmp_path, "0001_first.sql", "CREATE TABLE thing (id integer);")
    write(tmp_path, "0002_broken.sql", "CREATE TABLE other (id integer); SELECT nothing_here;")
    with pytest.raises(psycopg.errors.UndefinedColumn):
        migrate.migrate(database_url, tmp_path)
    assert migrate.current_version(database_url) == 1
    with psycopg.connect(database_url) as conn:
        row = conn.execute("SELECT to_regclass('other') IS NULL").fetchone()
    assert row == (True,)


def test_main_needs_the_database_address(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CATALOG_DATABASE_URL", raising=False)
    assert migrate.main(["migrate"]) == 2
    assert "CATALOG_DATABASE_URL saknas" in capsys.readouterr().err


def test_main_checks_and_migrates(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CATALOG_DATABASE_URL", database_url)
    assert migrate.main(["migrate", "--check"]) == 1
    assert "Saknas: 0001_grunden" in capsys.readouterr().out
    assert migrate.main(["migrate"]) == 0
    assert migrate.main(["migrate", "--check"]) == 0
