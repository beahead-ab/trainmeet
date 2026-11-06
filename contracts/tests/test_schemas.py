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
    "trainmeet.meet-1": "provbanan.meet.json",
    "trainmeet.station-outside-1": "asen.station-outside.json",
    "trainmeet.station-1.command": "station-1.command.json",
    "trainmeet.station-1.reply": "station-1.reply.json",
    "trainmeet.terminal16.hello": "terminal16.hello.json",
    "trainmeet.terminal16.frame-message": "terminal16.frame-message.json",
    "trainmeet.drift-1.event": "drift-1.event.json",
}


def test_the_schemas_are_up_to_date() -> None:
    assert main(["generate", "--check"]) == 0


def test_every_example_belongs_to_a_contract() -> None:
    assert set(EXAMPLE_FOR) <= set(CONTRACTS)
    assert {p.name for p in EXAMPLES.glob("*.json")} == set(EXAMPLE_FOR.values())


@pytest.mark.parametrize("stem", sorted(CONTRACTS))
def test_every_schema_is_valid(stem: str) -> None:
    schema = json.loads((SCHEMA_DIR / filename(stem)).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("stem", sorted(EXAMPLE_FOR))
def test_the_example_follows_the_published_schema(stem: str) -> None:
    schema = json.loads((SCHEMA_DIR / filename(stem)).read_text(encoding="utf-8"))
    example = json.loads((EXAMPLES / EXAMPLE_FOR[stem]).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(example), key=str)
    assert errors == []


@pytest.mark.parametrize("stem", sorted(EXAMPLE_FOR))
def test_the_example_follows_the_model(stem: str) -> None:
    example = json.loads((EXAMPLES / EXAMPLE_FOR[stem]).read_text(encoding="utf-8"))
    CONTRACTS[stem].model_validate(example)
