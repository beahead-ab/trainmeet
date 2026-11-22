"""The hub's SQLite files (core/sqlite.py): made ready when the store is made, a file another
connection writes to is waited for, never refused at once, and a transaction that only reads
does not wait for a write at all."""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from threading import Event, Thread

import pytest

from core.sqlite import BUSY_SECONDS, add_columns, connect, prepare, reading

SCHEMA = "CREATE TABLE IF NOT EXISTS thing (id TEXT PRIMARY KEY);"


def _hold(path: Path, held: Event, seconds: float) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.execute("BEGIN IMMEDIATE")
        held.set()
        time.sleep(seconds)
        db.commit()


def holding(path: Path, seconds: float = 0.3) -> Thread:
    """Another store's transaction on the same file, in a thread of its own: it holds the write
    for a while."""
    held = Event()
    thread = Thread(target=_hold, args=(path, held, seconds))
    thread.start()
    assert held.wait(5)
    return thread


def made_before(path: Path) -> None:
    """A file as a store made it before: without write-ahead logging."""
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)


def journal_mode(path: Path) -> str:
    with closing(sqlite3.connect(path)) as db:
        return str(db.execute("PRAGMA journal_mode").fetchone()[0])


def test_the_file_gets_its_folder_write_ahead_logging_and_the_tables(tmp_path: Path) -> None:
    path = tmp_path / "hubben" / "planering.sqlite3"
    prepare(path, SCHEMA)
    # A second store on the same file adds its own tables.
    prepare(path, "CREATE TABLE IF NOT EXISTS other (id TEXT);")
    assert journal_mode(path) == "wal"
    with closing(connect(path)) as db:
        tables = {name for (name,) in db.execute("SELECT name FROM sqlite_master")}
    assert {"thing", "other"} <= tables


def test_sqlite_refuses_write_ahead_logging_at_once_while_another_writes(tmp_path: Path) -> None:
    """Why the change is made when the store is made, and tried again: SQLite does not wait the
    busy timeout for it, but says at once that the database is locked."""
    path = tmp_path / "planering.sqlite3"
    made_before(path)
    thread = holding(path)
    try:
        with closing(sqlite3.connect(path, timeout=5)) as db:
            start = time.monotonic()
            with pytest.raises(sqlite3.OperationalError, match="database is locked"):
                db.execute("PRAGMA journal_mode=WAL")
            assert time.monotonic() - start < 1
    finally:
        thread.join()


def test_a_file_another_connection_writes_to_is_waited_for(tmp_path: Path) -> None:
    path = tmp_path / "planering.sqlite3"
    made_before(path)
    thread = holding(path)
    try:
        prepare(path, SCHEMA)
    finally:
        thread.join()
    assert journal_mode(path) == "wal"


def test_a_transaction_waits_longer_than_sqlite3s_five_seconds(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "planering.sqlite3")) as db:
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_SECONDS * 1000


def test_processes_starting_on_a_new_file_add_each_column_once(tmp_path: Path) -> None:
    """Four processes that make the same store on a new file at once (the hub imported in each
    of "Tester"'s processes): the later columns are added once, and no one is refused."""
    path = tmp_path / "ny.sqlite3"
    prepare(path, SCHEMA)
    columns = [(f"c{i}", "TEXT") for i in range(20)]
    start = Event()
    failed: list[BaseException] = []

    def make() -> None:
        start.wait()
        try:
            add_columns(path, "thing", columns)
        except BaseException as error:
            failed.append(error)

    threads = [Thread(target=make) for _ in range(4)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join()
    assert failed == []
    with closing(sqlite3.connect(path)) as db:
        present = [str(row[1]) for row in db.execute("PRAGMA table_info(thing)")]
    assert present == ["id", *(c for c, _ in columns)]


def test_a_transaction_that_only_reads_does_not_wait_for_a_write(tmp_path: Path) -> None:
    """With write-ahead logging a deferred read goes on while another connection holds the write,
    and sees the file as it was before that write."""
    path = tmp_path / "planering.sqlite3"
    prepare(path, SCHEMA)
    with closing(connect(path)) as db, db:
        db.execute("INSERT INTO thing VALUES ('a')")
    thread = holding(path, seconds=2.0)
    try:
        start = time.monotonic()
        with reading(path) as db:
            found = [row[0] for row in db.execute("SELECT id FROM thing")]
        assert time.monotonic() - start < 1
    finally:
        thread.join()
    assert found == ["a"]


def test_a_transaction_that_only_reads_may_not_write(tmp_path: Path) -> None:
    path = tmp_path / "planering.sqlite3"
    prepare(path, SCHEMA)
    with reading(path) as db, pytest.raises(sqlite3.OperationalError, match="readonly"):
        db.execute("INSERT INTO thing VALUES ('a')")
    with closing(connect(path)) as db:
        assert db.execute("SELECT count(*) FROM thing").fetchone()[0] == 0
