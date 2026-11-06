"""Writes the JSON Schemas in contracts/schemas from the models. The models are the source.

    uv run python -m contracts.generate          # write the schemas
    uv run python -m contracts.generate --check  # exit 1 if a schema is out of date

The tests run the check, so a model and its schema can never disagree on main.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from contracts.meet import FORMAT as MEET_FORMAT
from contracts.meet import MeetPackage
from contracts.station_outside import FORMAT as OUTSIDE_FORMAT
from contracts.station_outside import StationOutside

SCHEMA_DIR = Path(__file__).parent / "schemas"
BASE_URL = "https://github.com/beahead-ab/trainmeet/blob/main/contracts/schemas/"

CONTRACTS: dict[str, type[BaseModel]] = {
    MEET_FORMAT: MeetPackage,
    OUTSIDE_FORMAT: StationOutside,
}


def filename(fmt: str) -> str:
    """trainmeet.meet/1 -> trainmeet.meet-1.schema.json"""
    return fmt.replace("/", "-") + ".schema.json"


def render(fmt: str, model: type[BaseModel]) -> str:
    schema = model.model_json_schema(mode="validation")
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE_URL + filename(fmt),
        "title": fmt,
        **{key: value for key, value in schema.items() if key != "title"},
    }
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv[1:]
    stale: list[str] = []
    for fmt, model in CONTRACTS.items():
        path = SCHEMA_DIR / filename(fmt)
        text = render(fmt, model)
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
        else:
            SCHEMA_DIR.mkdir(exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"Skrev {path.relative_to(SCHEMA_DIR.parent.parent)}")
    if stale:
        print("Inaktuella scheman: " + ", ".join(stale), file=sys.stderr)
        print("Kör: uv run python -m contracts.generate", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
