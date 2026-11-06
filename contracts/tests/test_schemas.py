"""The published JSON Schemas match the models, and the examples follow the schemas.

TKL, CAD, TrainMeet Catalog and the apps read the schemas, not the Python models, so the
examples are also checked with a plain JSON Schema reader.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from contracts.generate import CONTRACTS, SCHEMA_DIR, filename, main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
EXAMPLE_FOR = {
    "trainmeet.meet/1": "provbanan.meet.json",
    "trainmeet.station-outside/1": "asen.station-outside.json",
}


def test_the_schemas_are_up_to_date() -> None:
    assert main(["generate", "--check"]) == 0


def test_every_contract_has_an_example() -> None:
    assert set(EXAMPLE_FOR) == set(CONTRACTS)


@pytest.mark.parametrize("fmt", sorted(EXAMPLE_FOR))
def test_the_example_follows_the_published_schema(fmt: str) -> None:
    schema = json.loads((SCHEMA_DIR / filename(fmt)).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    example = json.loads((EXAMPLES / EXAMPLE_FOR[fmt]).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(example), key=str)
    assert errors == []
    assert example["format"] == fmt
