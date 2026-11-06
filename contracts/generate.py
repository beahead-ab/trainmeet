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

from contracts import drift, meet, station, station_outside, terminal

SCHEMA_DIR = Path(__file__).parent / "schemas"
BASE_URL = "https://github.com/beahead-ab/trainmeet/blob/main/contracts/schemas/"

# File stem -> model. The stem says the contract, its version and the message.
CONTRACTS: dict[str, type[BaseModel]] = {
    "trainmeet.meet-1": meet.MeetPackage,
    "trainmeet.station-outside-1": station_outside.StationOutside,
    "trainmeet.station-1.connect-request": station.ConnectRequest,
    "trainmeet.station-1.connect-reply": station.ConnectReply,
    "trainmeet.station-1.command": station.Command,
    "trainmeet.station-1.reply": station.Reply,
    "trainmeet.station-1.snapshot": station.Snapshot,
    "trainmeet.station-1.event": station.Event,
    "trainmeet.terminal16.hello": terminal.Hello,
    "trainmeet.terminal16.presence": terminal.Presence,
    "trainmeet.terminal16.alive": terminal.Alive,
    "trainmeet.terminal16.key-press": terminal.KeyPress,
    "trainmeet.terminal16.frame": terminal.Frame,
    "trainmeet.terminal16.frame-message": terminal.FrameMessage,
    "trainmeet.terminal16.ack": terminal.Ack,
    "trainmeet.drift-1.start": drift.StartMeet,
    "trainmeet.drift-1.clock": drift.ClockControl,
    "trainmeet.drift-1.approve": drift.Approve,
    "trainmeet.drift-1.revoke": drift.Revoke,
    "trainmeet.drift-1.assign": drift.Assign,
    "trainmeet.drift-1.event": drift.DriftEvent,
}


def filename(stem: str) -> str:
    return stem + ".schema.json"


def render(stem: str, model: type[BaseModel]) -> str:
    schema = model.model_json_schema(mode="validation")
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE_URL + filename(stem),
        "title": stem,
        **{key: value for key, value in schema.items() if key != "title"},
    }
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv[1:]
    expected = {filename(stem): render(stem, model) for stem, model in CONTRACTS.items()}
    if check:
        present = {p.name for p in SCHEMA_DIR.glob("*.schema.json")}
        stale = sorted(
            name
            for name, text in expected.items()
            if name not in present or (SCHEMA_DIR / name).read_text(encoding="utf-8") != text
        )
        extra = sorted(present - set(expected))
        if stale or extra:
            print("Inaktuella scheman: " + ", ".join(stale + extra), file=sys.stderr)
            print("Kör: uv run python -m contracts.generate", file=sys.stderr)
            return 1
        return 0
    SCHEMA_DIR.mkdir(exist_ok=True)
    for old in SCHEMA_DIR.glob("*.schema.json"):
        if old.name not in expected:
            old.unlink()
    for name, text in expected.items():
        (SCHEMA_DIR / name).write_text(text, encoding="utf-8")
    print(f"Skrev {len(expected)} scheman i contracts/schemas/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
