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
from pydantic.json_schema import JsonSchemaValue

from contracts import drift, hub, meet, station, station_outside, terminal

SCHEMA_DIR = Path(__file__).parent / "schemas"
OPENAPI = SCHEMA_DIR.parent / "openapi.json"
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
    "trainmeet.terminal-web-1.login": terminal.WebLogin,
    "trainmeet.terminal-web-1.session": terminal.WebSession,
    "trainmeet.drift-1.start": drift.StartMeet,
    "trainmeet.drift-1.clock": drift.ClockControl,
    "trainmeet.drift-1.approve": drift.Approve,
    "trainmeet.drift-1.revoke": drift.Revoke,
    "trainmeet.drift-1.assign": drift.Assign,
    "trainmeet.drift-1.client": drift.Client,
    "trainmeet.drift-1.event": drift.DriftEvent,
    "trainmeet.drift-1.now": drift.Now,
    "trainmeet.drift-1.joining": drift.Joining,
    "trainmeet.drift-1.refusal": drift.Refusal,
    "trainmeet.hub-1.info": hub.HubInfo,
    "trainmeet.hub-1.setup": hub.SetUp,
    "trainmeet.hub-1.login": hub.LogIn,
    "trainmeet.hub-1.session": hub.Session,
}


def filename(stem: str) -> str:
    return stem + ".schema.json"


def payload_variants(
    schema: JsonSchemaValue,
    discriminator: str,
    field: str,
    models: dict[str, type[BaseModel]],
    *,
    other_values: bool = False,
) -> None:
    variants: list[JsonSchemaValue] = []
    definitions = schema.setdefault("$defs", {})
    for value, model in models.items():
        payload = model.model_json_schema()
        definitions.update(payload.pop("$defs", {}))
        definitions[model.__name__] = payload
        variants.append(
            {
                "properties": {
                    discriminator: {"const": value, "type": "string"},
                    field: {"$ref": f"#/$defs/{model.__name__}"},
                },
                "required": [discriminator, field],
            }
        )
    if other_values:
        variants.append({"properties": {discriminator: {"not": {"enum": list(models)}}}})
    schema["oneOf"] = variants


def model_schema(model: type[BaseModel]) -> JsonSchemaValue:
    schema = model.model_json_schema(mode="validation")
    if model is station.Command:
        payload_variants(
            schema, "action", "payload", {k.value: v for k, v in station.PAYLOADS.items()}
        )
    elif model is station.Reply:
        schema["oneOf"] = [
            {
                "properties": {
                    "status": {"const": "rejected"},
                    "reason": {"$ref": "#/$defs/Reason"},
                },
                "required": ["reason"],
            },
            {
                "properties": {
                    "status": {"enum": ["accepted", "duplicate"]},
                    "reason": {"type": "null"},
                }
            },
        ]
    elif model is drift.ClockControl:
        schema["oneOf"] = [
            {
                "properties": {"action": {"const": "speed"}, "speed": {"type": "number"}},
                "required": ["speed"],
            },
            {
                "properties": {"action": {"const": "jump"}, "time": {"type": "string"}},
                "required": ["time"],
            },
            {"properties": {"action": {"enum": ["start", "stop", "undo_jump"]}}},
        ]
    elif model is drift.DriftEvent:
        payload_variants(
            schema,
            "kind",
            "data",
            {k.value: v for k, v in drift.EVENT_PAYLOADS.items()},
            other_values=True,
        )
        schema["allOf"] = [
            {
                "if": {"properties": {"kind": {"const": "clearance.requested"}}},
                "then": {"properties": {"call": {"type": "string"}}, "required": ["call"]},
            }
        ]
    return schema


def render(stem: str, model: type[BaseModel]) -> str:
    schema = model_schema(model)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE_URL + filename(stem),
        "title": stem,
        **{key: value for key, value in schema.items() if key != "title"},
    }
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


def openapi_ref(stem: str) -> JsonSchemaValue:
    return {"$ref": f"#/components/schemas/{stem}"}


def openapi() -> str:
    components: dict[str, JsonSchemaValue] = {}
    for stem, model in CONTRACTS.items():
        schema = model_schema(model)
        definitions = schema.pop("$defs", {})
        # Pydantic's definition names are local. Keep them distinct across contracts.
        for name, item in [
            (stem, schema),
            *((f"{stem}.{key}", value) for key, value in definitions.items()),
        ]:
            components[name] = json.loads(
                json.dumps(item).replace("#/$defs/", f"#/components/schemas/{stem}.")
            )

    paths: dict[str, dict[str, JsonSchemaValue]] = {}

    def route(
        method: str,
        path: str,
        operation: str,
        response: str,
        request: str | None = None,
        *,
        bearer: bool = False,
        many: bool = False,
        stream: bool = False,
    ) -> None:
        body = openapi_ref(response)
        if many:
            body = {"type": "array", "items": body}
        if stream:
            body = {"type": "string", "x-event-schema": body}
        media = "text/event-stream" if stream else "application/json"
        entry: JsonSchemaValue = {
            "operationId": operation,
            "responses": {"200": {"description": "OK", "content": {media: {"schema": body}}}},
        }
        if request:
            entry["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": openapi_ref(request)}},
            }
        if bearer:
            entry["security"] = [{"clientKey": []}]
        params = [
            {"name": part[1:-1], "in": "path", "required": True, "schema": {"type": "string"}}
            for part in path.split("/")
            if part.startswith("{")
        ]
        if path.endswith("/log"):
            params.extend(
                {"name": name, "in": "query", "schema": {"type": "string"}}
                for name in ("place", "train")
            )
        if params:
            entry["parameters"] = params
        paths.setdefault(path, {})[method] = entry

    s = "trainmeet.station-1."
    d = "trainmeet.drift-1."
    t = "trainmeet.terminal16."
    w = "trainmeet.terminal-web-1."
    route(
        "post",
        "/api/station/1/connect",
        "connectStation",
        s + "connect-reply",
        s + "connect-request",
    )
    route("get", "/api/station/1/connect/{client}", "stationApproval", s + "connect-reply")
    route("get", "/api/station/1/places/{place}", "stationSnapshot", s + "snapshot", bearer=True)
    route(
        "post", "/api/station/1/commands", "stationCommand", s + "reply", s + "command", bearer=True
    )
    route(
        "get",
        "/api/station/1/places/{place}/events",
        "stationEvents",
        s + "event",
        bearer=True,
        stream=True,
    )
    route("post", "/api/terminal/session", "terminalLogin", w + "session", w + "login")
    route("get", "/api/terminal/frame", "terminalFrame", t + "frame", bearer=True)
    route("post", "/api/terminal/keys", "terminalKey", t + "ack", t + "key-press", bearer=True)
    route("get", "/api/terminal/events", "terminalEvents", t + "frame", bearer=True, stream=True)
    route("post", "/api/drift/1/start", "startMeet", d + "event", d + "start", bearer=True)
    route("post", "/api/drift/1/clock", "driftClock", d + "event", d + "clock", bearer=True)
    route("get", "/api/drift/1/clients", "driftClients", d + "client", bearer=True, many=True)
    for action in ("approve", "revoke", "assign"):
        route(
            "post",
            f"/api/drift/1/clients/{action}",
            f"{action}Client",
            d + "client",
            d + action,
            bearer=True,
        )
    route("get", "/api/drift/1/now", "driftNow", d + "now")
    route("get", "/api/drift/1/connect", "driftJoining", d + "joining", bearer=True)
    route("get", "/api/drift/1/log", "driftLog", d + "event", bearer=True, many=True)
    route("get", "/api/drift/1/refusals", "driftRefusals", d + "refusal", bearer=True, many=True)
    route("get", "/api/drift/1/events", "driftEvents", d + "event", bearer=True, stream=True)
    h = "trainmeet.hub-1."
    route("get", "/api/hub", "hubInfo", h + "info")
    route("post", "/api/hub/setup", "hubSetUp", h + "session", h + "setup")
    route("post", "/api/hub/login", "hubLogIn", h + "session", h + "login")
    return (
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "TrainMeet Hub · kontrakten", "version": "1"},
                "paths": paths,
                "components": {
                    "schemas": components,
                    "securitySchemes": {"clientKey": {"type": "http", "scheme": "bearer"}},
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


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
        if not OPENAPI.exists() or OPENAPI.read_text(encoding="utf-8") != openapi():
            stale.append(OPENAPI.name)
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
    OPENAPI.write_text(openapi(), encoding="utf-8")
    print(f"Skrev {len(expected)} scheman i contracts/schemas/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
