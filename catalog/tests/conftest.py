"""A fresh PostgreSQL database for each test that needs one.

CATALOG_TEST_DATABASE_URL points at a server where the user may create databases, for
example postgresql://postgres@127.0.0.1:5432/postgres. GitHub Actions starts one for the
check "Tester". Without it the database tests are skipped locally, but never in CI.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import conninfo

ENV = "CATALOG_TEST_DATABASE_URL"


@pytest.fixture
def database_url() -> Iterator[str]:
    admin = os.environ.get(ENV, "").strip()
    if not admin:
        if os.environ.get("CI"):
            pytest.fail(f"{ENV} saknas i CI: databastesterna för Catalog måste köras.")
        pytest.skip(f"{ENV} saknas: inga databastester för Catalog.")
    name = f"catalog_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield conninfo.make_conninfo(admin, dbname=name)
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
