"""Short transactions that lock the owner's row first (CAT-40)."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator

import pytest

from catalog import migrate
from catalog.db import Database, UnknownOwner


@pytest.fixture
def db(database_url: str) -> Iterator[Database]:
    migrate.migrate(database_url)
    database = Database(database_url, min_size=2, max_size=4)
    database.open()
    try:
        yield database
    finally:
        database.close()


def add_owner(db: Database, name: str = "Provkonto A") -> uuid.UUID:
    owner = uuid.uuid4()
    with db.transaction() as conn:
        conn.execute("INSERT INTO owner (id, name) VALUES (%s, %s)", (owner, name))
    return owner


def test_a_transaction_commits_or_leaves_nothing(db: Database) -> None:
    owner = uuid.uuid4()
    with pytest.raises(RuntimeError), db.transaction() as conn:
        conn.execute("INSERT INTO owner (id, name) VALUES (%s, %s)", (owner, "Borta"))
        raise RuntimeError("halvvägs")
    with db.transaction() as conn:
        assert conn.execute("SELECT 1 FROM owner WHERE id = %s", (owner,)).fetchone() is None


def test_an_unknown_owner_is_refused(db: Database) -> None:
    with pytest.raises(UnknownOwner), db.owner_transaction(uuid.uuid4()):
        pass


def test_two_writes_for_the_same_owner_take_turns(db: Database) -> None:
    owner = add_owner(db)
    order: list[str] = []
    first_has_lock = threading.Event()

    def first() -> None:
        with db.owner_transaction(owner):
            order.append("first in")
            first_has_lock.set()
            time.sleep(0.3)
            order.append("first out")

    def second() -> None:
        first_has_lock.wait(timeout=5)
        with db.owner_transaction(owner):
            order.append("second in")

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert order == ["first in", "first out", "second in"]


def test_different_owners_do_not_wait_for_each_other(db: Database) -> None:
    one, two = add_owner(db), add_owner(db, "Provkonto B")
    with db.owner_transaction(one), db.owner_transaction(two) as conn:
        assert conn.execute("SELECT 1").fetchone() is not None


def test_ping_says_whether_the_database_answers(db: Database) -> None:
    assert db.ping() is True
