"""The hub's check of a session on every request only reads (core/sqlite.py): it answers at once
while another connection holds the hub's file for a write, as a big import on a Pi can for
seconds, rather than wait up to BUSY_SECONDS for it."""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from threading import Event, Thread

from hub.local import LocalLogin

PIN = "482915"


def _hold(path: Path, held: Event, seconds: float) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.execute("BEGIN IMMEDIATE")
        held.set()
        time.sleep(seconds)
        db.commit()


def test_the_hub_checks_a_session_while_another_connection_writes(tmp_path: Path) -> None:
    login = LocalLogin(tmp_path / "hubben.sqlite3", "Hubben")
    login.set_up("Pi:n", PIN)
    session = login.log_in(PIN)
    held = Event()
    thread = Thread(target=_hold, args=(login.path, held, 2.0))
    thread.start()
    assert held.wait(5)
    try:
        start = time.monotonic()
        assert login.valid(session)
        assert login.state().set_up
        assert login.person(session) is None
        assert time.monotonic() - start < 1
    finally:
        thread.join()
