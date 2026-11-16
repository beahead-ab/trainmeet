"""Writes the JSON Schemas in contracts/schemas from the models. The models are the source.

    uv run python -m contracts.generate          # write the schemas
    uv run python -m contracts.generate --check  # exit 1 if a schema is out of date

The tests run the check, so a model and its schema can never disagree on main.
The Hub's HTTP API is described in openapi.json and TrainMeet Catalog's in
catalog.openapi.json, since Catalog is a service of its own (C16).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaValue

from contracts import (
    catalog,
    drift,
    hub,
    meet,
    planning,
    screen,
    station,
    station_outside,
    terminal,
)
from contracts import id as id_api

SCHEMA_DIR = Path(__file__).parent / "schemas"
OPENAPI = SCHEMA_DIR.parent / "openapi.json"
CATALOG_OPENAPI = SCHEMA_DIR.parent / "catalog.openapi.json"
CATALOG_PREFIX = "trainmeet.catalog-"
ID_OPENAPI = SCHEMA_DIR.parent / "id.openapi.json"
ID_PREFIX = "trainmeet.id-"
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
    "trainmeet.drift-1.new-day": drift.NewDay,
    "trainmeet.drift-1.day-settings": drift.DaySettings,
    "trainmeet.drift-1.day": drift.DayStatus,
    "trainmeet.drift-1.phone": drift.PlacePhone,
    "trainmeet.drift-1.make-change": drift.MakeChange,
    "trainmeet.drift-1.switch": drift.SwitchVersion,
    "trainmeet.drift-1.switch-preview": drift.SwitchPreview,
    "trainmeet.drift-1.approve": drift.Approve,
    "trainmeet.drift-1.revoke": drift.Revoke,
    "trainmeet.drift-1.assign": drift.Assign,
    "trainmeet.drift-1.client": drift.Client,
    "trainmeet.drift-1.event": drift.DriftEvent,
    "trainmeet.drift-1.now": drift.Now,
    "trainmeet.drift-1.joining": drift.Joining,
    "trainmeet.drift-1.refusal": drift.Refusal,
    "trainmeet.drift-1.automation-settings": drift.AutomationSettings,
    "trainmeet.drift-1.automation-place": drift.AutomationPlace,
    "trainmeet.drift-1.automation": drift.AutomationStatus,
    "trainmeet.drift-1.preview": drift.Preview,
    "trainmeet.drift-1.preview-clients": drift.PreviewClients,
    "trainmeet.screen-1.login": screen.ScreenLogin,
    "trainmeet.screen-1.session": screen.ScreenSession,
    "trainmeet.screen-1.show": screen.ShowView,
    "trainmeet.screen-1.picture": screen.ScreenPicture,
    "trainmeet.hub-1.info": hub.HubInfo,
    "trainmeet.hub-1.setup": hub.SetUp,
    "trainmeet.hub-1.login": hub.LogIn,
    "trainmeet.hub-1.session": hub.Session,
    "trainmeet.hub-1.version": hub.Version,
    "trainmeet.planning-1.import": planning.ImportResult,
    "trainmeet.planning-1.draft": planning.Draft,
    "trainmeet.planning-1.new-meet": planning.NewMeet,
    "trainmeet.planning-1.meet-summary": planning.MeetSummary,
    "trainmeet.planning-1.changes": planning.Changes,
    "trainmeet.planning-1.import-preview": planning.ImportPreview,
    "trainmeet.planning-1.answer": planning.Answer,
    "trainmeet.planning-1.double-track-answer": planning.DoubleTrackAnswer,
    "trainmeet.planning-1.let-stand": planning.LetStand,
    "trainmeet.planning-1.check": planning.Check,
    "trainmeet.planning-1.version": planning.Version,
    "trainmeet.planning-1.proposal": planning.Proposal,
    "trainmeet.catalog-1.version": catalog.CatalogVersion,
    "trainmeet.catalog-1.account": catalog.Account,
    "trainmeet.catalog-1.session": catalog.Session,
    "trainmeet.catalog-1.trial-login": catalog.TrialLogin,
    "trainmeet.catalog-1.fleet-choice": catalog.FleetChoice,
    "trainmeet.catalog-1.vehicle-fields": catalog.VehicleFields,
    "trainmeet.catalog-1.vehicle-change": catalog.VehicleChange,
    "trainmeet.catalog-1.vehicle": catalog.Vehicle,
    "trainmeet.catalog-1.vehicle-list": catalog.VehicleList,
    "trainmeet.catalog-1.move": catalog.Move,
    "trainmeet.catalog-1.lend": catalog.Lend,
    "trainmeet.catalog-1.return": catalog.Return,
    "trainmeet.catalog-1.vehicle-event": catalog.VehicleEvent,
    "trainmeet.catalog-1.place": catalog.Place,
    "trainmeet.catalog-1.place-name": catalog.PlaceName,
    "trainmeet.catalog-1.removed": catalog.Removed,
    "trainmeet.catalog-1.problem": catalog.Problem,
    "trainmeet.catalog-1.tag": catalog.Tag,
    "trainmeet.catalog-1.lookup": catalog.Lookup,
    "trainmeet.catalog-1.tag-link": catalog.TagLink,
    "trainmeet.catalog-1.tag-unlink": catalog.TagUnlink,
    "trainmeet.catalog-1.new-label": catalog.NewLabel,
    "trainmeet.catalog-1.tag-event": catalog.TagEvent,
    "trainmeet.catalog-1.new-pending": catalog.NewPending,
    "trainmeet.catalog-1.pending": catalog.PendingState,
    "trainmeet.catalog-1.tell": catalog.Tell,
    "trainmeet.catalog-1.told": catalog.Told,
    "trainmeet.catalog-1.settings": catalog.OwnerSettings,
    "trainmeet.catalog-1.vehicle-history": catalog.VehicleHistory,
    "trainmeet.catalog-1.catalog-export": catalog.CatalogExport,
    "trainmeet.catalog-1.owners-removed": catalog.OwnersRemoved,
    "trainmeet.catalog-1.removed-count": catalog.RemovedCount,
    "trainmeet.id-1.version": id_api.Version,
    "trainmeet.id-1.session": id_api.Session,
    "trainmeet.id-1.account": id_api.Account,
    "trainmeet.id-1.person": id_api.Person,
    "trainmeet.id-1.club-name": id_api.ClubName,
    "trainmeet.id-1.club": id_api.Club,
    "trainmeet.id-1.club-page": id_api.ClubPage,
    "trainmeet.id-1.member": id_api.Member,
    "trainmeet.id-1.invite": id_api.Invite,
    "trainmeet.id-1.invitation": id_api.Invitation,
    "trainmeet.id-1.answer": id_api.Answer,
    "trainmeet.id-1.fleet-invite": id_api.FleetInvite,
    "trainmeet.id-1.fleet-page": id_api.FleetPage,
    "trainmeet.id-1.grant": id_api.Grant,
    "trainmeet.id-1.resource": id_api.Resource,
    "trainmeet.id-1.removed": id_api.Removed,
    "trainmeet.id-1.access": id_api.Access,
    "trainmeet.id-1.fleet-access": id_api.FleetAccess,
    "trainmeet.id-1.club-role-change": id_api.ClubRoleChange,
    "trainmeet.id-1.club-brief": id_api.ClubBrief,
    "trainmeet.id-1.removal-plan": id_api.RemovalPlan,
    "trainmeet.id-1.remove-account": id_api.RemoveAccount,
    "trainmeet.id-1.account-export": id_api.AccountExport,
    "trainmeet.id-1.help-request": id_api.HelpRequest,
    "trainmeet.id-1.help-sent": id_api.HelpSent,
    "trainmeet.id-1.switcher": id_api.Switcher,
    "trainmeet.id-1.new-meet": id_api.NewMeet,
    "trainmeet.id-1.meet": id_api.Meet,
    "trainmeet.id-1.meet-page": id_api.MeetPage,
    "trainmeet.id-1.meet-grant": id_api.MeetGrant,
    "trainmeet.id-1.problem": id_api.Problem,
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


def components(stems: list[str]) -> dict[str, JsonSchemaValue]:
    """The contracts as OpenAPI components, with Pydantic's local names made distinct."""
    found: dict[str, JsonSchemaValue] = {}
    for stem in stems:
        schema = model_schema(CONTRACTS[stem])
        definitions = schema.pop("$defs", {})
        # Pydantic's definition names are local. Keep them distinct across contracts.
        for name, item in [
            (stem, schema),
            *((f"{stem}.{key}", value) for key, value in definitions.items()),
        ]:
            found[name] = json.loads(
                json.dumps(item).replace("#/$defs/", f"#/components/schemas/{stem}.")
            )
    return found


def openapi() -> str:
    """The Hub's HTTP API."""
    hub_components = components(
        [s for s in CONTRACTS if not s.startswith((CATALOG_PREFIX, ID_PREFIX))]
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
    route("post", "/api/drift/1/day", "newDay", d + "event", d + "new-day", bearer=True)
    route(
        "post",
        "/api/drift/1/day/settings",
        "daySettings",
        d + "day",
        d + "day-settings",
        bearer=True,
    )
    route("get", "/api/drift/1/phones", "driftPhones", d + "phone", bearer=True, many=True)
    route("post", "/api/drift/1/changes", "makeChange", d + "event", d + "make-change", bearer=True)
    route("post", "/api/drift/1/changes/{change_id}/drop", "dropChange", d + "event", bearer=True)
    route("post", "/api/drift/1/changes/{change_id}/force", "forceChange", d + "event", bearer=True)
    route("get", "/api/drift/1/package", "driftPackage", "trainmeet.meet-1")
    route(
        "get", "/api/drift/1/switch/{version}", "switchPreview", d + "switch-preview", bearer=True
    )
    route("post", "/api/drift/1/switch", "switchVersion", d + "event", d + "switch", bearer=True)
    route("post", "/api/drift/1/switch/force", "forceSwitch", d + "event", bearer=True)
    route("post", "/api/drift/1/switch/call-off", "callOffSwitch", d + "event", bearer=True)
    route("post", "/api/drift/1/unlock", "unlockDrift", d + "event", bearer=True)
    route(
        "post",
        "/api/drift/1/phones",
        "changePhone",
        d + "phone",
        d + "phone",
        bearer=True,
        many=True,
    )
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
    route("get", "/api/drift/1/automation", "driftAutomation", d + "automation", bearer=True)
    route(
        "post",
        "/api/drift/1/automation",
        "driftAutomationSettings",
        d + "automation",
        d + "automation-settings",
        bearer=True,
    )
    route(
        "post",
        "/api/drift/1/automation/place",
        "driftAutomationPlace",
        d + "automation",
        d + "automation-place",
        bearer=True,
    )
    route("get", "/api/drift/1/events", "driftEvents", d + "event", bearer=True, stream=True)
    # Provbanan: one run per browser, in a cookie of its own (H51).
    pv = "/api/provbanan"
    route("get", pv, "preview", d + "preview")
    route("post", pv + "/start", "previewStart", d + "preview", d + "start")
    route("post", pv + "/clock", "previewClock", d + "preview", d + "clock")
    route("post", pv + "/command", "previewCommand", d + "preview", s + "command")
    route("get", pv + "/clients", "previewClients", d + "preview-clients")
    for action in ("approve", "revoke", "assign"):
        route(
            "post",
            f"{pv}/clients/{action}",
            f"{action}PreviewClient",
            d + "preview-clients",
            d + action,
        )
    v = "trainmeet.screen-1."
    route("post", "/api/screen/session", "screenLogin", v + "session", v + "login")
    route("get", "/api/screen/picture", "screenPicture", v + "picture", bearer=True)
    route("post", "/api/drift/1/clients/view", "showView", d + "client", v + "show", bearer=True)
    h = "trainmeet.hub-1."
    route("get", "/api/hub", "hubInfo", h + "info")
    route("get", "/api/version", "hubVersion", h + "version")
    route("post", "/api/hub/setup", "hubSetUp", h + "session", h + "setup")
    route("post", "/api/hub/login", "hubLogIn", h + "session", h + "login")
    p = "trainmeet.planning-1."
    m = "/api/planering/1/meets"
    route("get", m, "planningMeets", p + "meet-summary", many=True)
    route("post", m, "newMeet", p + "draft", p + "new-meet", bearer=True)
    route("get", m + "/{meet}", "planningDraft", p + "draft")
    route("post", m + "/{meet}/changes", "changeDraft", p + "draft", p + "changes", bearer=True)
    route("post", m + "/{meet}/answers", "answerQuestion", p + "draft", p + "answer", bearer=True)
    route("get", m + "/{meet}/proposals", "planningProposals", p + "proposal", many=True)
    route("post", m + "/{meet}/proposals/{proposal}/take", "takeProposal", p + "draft", bearer=True)
    route(
        "post",
        m + "/{meet}/proposals/{proposal}/reject",
        "rejectProposal",
        p + "proposal",
        bearer=True,
    )
    route("get", m + "/{meet}/check", "planningCheck", p + "check")
    route(
        "post",
        m + "/{meet}/double-track/{section}",
        "answerDoubleTrack",
        p + "draft",
        p + "double-track-answer",
        bearer=True,
    )
    route(
        "post",
        m + "/{meet}/deviations/{deviation}/let-stand",
        "letStand",
        p + "draft",
        p + "let-stand",
        bearer=True,
    )
    route(
        "post", m + "/{meet}/deviations/{deviation}/take-back", "takeBack", p + "draft", bearer=True
    )
    route("get", m + "/{meet}/versions", "planningVersions", p + "version", many=True)
    route("post", m + "/{meet}/versions", "publish", p + "version", bearer=True)
    route(
        "post",
        m + "/{meet}/versions/{number}/withdraw",
        "withdrawVersion",
        p + "version",
        bearer=True,
    )
    route("get", m + "/{meet}/versions/{number}", "planningVersion", "trainmeet.meet-1")
    # Lägg till underlag: the file's own bytes, its name in the address.
    route("post", m + "/{meet}/sources", "addSource", p + "import-preview", bearer=True)
    route("post", m + "/{meet}/sources/{source}/apply", "applySource", p + "draft", bearer=True)
    upload = paths[m + "/{meet}/sources"]["post"]
    upload["requestBody"] = {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
    upload["parameters"].append(
        {"name": "name", "in": "query", "required": True, "schema": {"type": "string"}}
    )
    return (
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "TrainMeet Hub · kontrakten", "version": "1"},
                "paths": paths,
                "components": {
                    "schemas": hub_components,
                    "securitySchemes": {"clientKey": {"type": "http", "scheme": "bearer"}},
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def catalog_openapi() -> str:
    """TrainMeet Catalog's HTTP API (CAT-36). The session is a cookie set by the login."""
    paths: dict[str, dict[str, JsonSchemaValue]] = {}
    c = "trainmeet.catalog-1."

    def route(
        method: str,
        path: str,
        operation: str,
        response: str,
        request: str | None = None,
        *,
        many: bool = False,
        created: bool = False,
        query: tuple[tuple[str, JsonSchemaValue], ...] = (),
        problems: tuple[int, ...] = (),
    ) -> None:
        body = openapi_ref(c + response)
        if many:
            body = {"type": "array", "items": body}
        answer = {"description": "OK", "content": {"application/json": {"schema": body}}}
        entry: JsonSchemaValue = {
            "operationId": operation,
            "responses": {"201" if created else "200": answer},
        }
        for code in problems:
            entry["responses"][str(code)] = {
                "description": "Catalog säger nej",
                "content": {"application/json": {"schema": openapi_ref(c + "problem")}},
            }
        if request:
            entry["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": openapi_ref(c + request)}},
            }
        params = [
            {"name": part[1:-1], "in": "path", "required": True, "schema": {"type": "string"}}
            for part in path.split("/")
            if part.startswith("{")
        ]
        params += [{"name": name, "in": "query", "schema": schema} for name, schema in query]
        if params:
            entry["parameters"] = params
        paths.setdefault(path, {})[method] = entry

    route("get", "/api/version", "catalogVersion", "version")
    route("get", "/api/catalog/1/session", "catalogSession", "session")
    route("delete", "/api/catalog/1/session", "catalogLogOut", "session")
    route("get", "/api/catalog/1/trial/accounts", "trialAccounts", "account", many=True)
    route("post", "/api/catalog/1/trial/login", "trialLogIn", "session", "trial-login")
    route("get", "/api/catalog/1/fleets", "fleets", "fleet-choice", many=True, problems=(401, 503))
    # Only TrainMeet ID's own API calls these, with a token for its client (KONTO-31, CAT-193).
    route(
        "get",
        "/api/catalog/1/id/export",
        "exportForId",
        "catalog-export",
        query=(("person", {"type": "string", "format": "uuid"}),),
        problems=(401, 403, 404),
    )
    route(
        "post",
        "/api/catalog/1/id/removed",
        "removedById",
        "removed-count",
        "owners-removed",
        problems=(401, 403, 404, 422),
    )

    def redirect(path: str, operation: str, summary: str, query: tuple[str, ...]) -> None:
        """An address the browser opens itself; the answer sends it on (#66)."""
        paths.setdefault(path, {})["get"] = {
            "operationId": operation,
            "summary": summary,
            "parameters": [
                {"name": name, "in": "query", "schema": {"type": "string"}} for name in query
            ],
            "responses": {"303": {"description": "Vidare, med Location."}},
        }

    redirect(
        "/api/catalog/1/id/login",
        "idLogIn",
        "Till TrainMeet ID för att logga in. next är sidan att komma tillbaka till, lang sv/en.",
        ("next", "lang"),
    )
    redirect(
        "/api/catalog/1/id/callback",
        "idCallback",
        "Tillbaka från TrainMeet ID: sessionen startar och webbläsaren går till next, "
        "eller till /logga-in?inloggning=fel.",
        ("code", "state", "error"),
    )
    v = "/api/catalog/1/vehicles"
    text: JsonSchemaValue = {"type": "string"}
    kinds: JsonSchemaValue = {"type": "array", "items": {"type": "string"}}
    write = (401, 404, 409, 422)
    route(
        "get",
        v,
        "vehicles",
        "vehicle-list",
        query=(("q", text), ("kind", kinds), ("scale", text), ("state", text), ("place", text)),
        problems=(401, 422),
    )
    route("post", v, "addVehicle", "vehicle", "vehicle-fields", created=True, problems=write)
    route("post", v + "/move", "moveVehicles", "vehicle-list", "move", problems=write)
    route("get", v + "/{vehicle}", "vehicle", "vehicle", problems=(401, 404))
    route("put", v + "/{vehicle}", "changeVehicle", "vehicle", "vehicle-change", problems=write)
    route(
        "delete",
        v + "/{vehicle}",
        "removeVehicle",
        "removed",
        query=(("version", {"type": "integer"}),),
        problems=write,
    )
    route("post", v + "/{vehicle}/lend", "lendVehicle", "vehicle", "lend", problems=write)
    route("post", v + "/{vehicle}/return", "returnVehicle", "vehicle", "return", problems=write)
    route("get", v + "/{vehicle}/events", "vehicleEvents", "vehicle-event", many=True)
    p = "/api/catalog/1/places"
    route("get", p, "places", "place", many=True, problems=(401,))
    route("post", p, "addPlace", "place", "place-name", created=True, problems=write)
    route("put", p + "/{place}", "renamePlace", "place", "place-name", problems=write)
    route("delete", p + "/{place}", "removePlace", "removed", problems=write)
    t = "/api/catalog/1/tags"
    route("post", t + "/simulated", "newSimulatedTag", "tag", created=True, problems=(401, 403))
    route("get", t + "/pending", "pendingLink", "pending", problems=(401,))
    route("post", t + "/pending", "waitForTag", "pending", "new-pending", problems=write)
    route("delete", t + "/pending", "stopWaiting", "pending", problems=(401,))
    route("get", t + "/{uid}", "lookupTag", "lookup", problems=(422, 429))
    route("post", t + "/{uid}/link", "linkTag", "vehicle", "tag-link", problems=write)
    route("get", t + "/{uid}/events", "tagEvents", "tag-event", many=True, problems=(401, 422))
    route("post", v + "/{vehicle}/tags/qr", "newLabel", "vehicle", "new-label", problems=write)
    route(
        "post", t + "/{uid}/notice", "tellTheOwner", "told", "tell", problems=(401, 404, 422, 429)
    )
    route("delete", v + "/{vehicle}/notices/{notice}", "clearNotice", "removed", problems=write)
    s_ = "/api/catalog/1/settings"
    route("get", s_, "ownerSettings", "settings", problems=(401,))
    route("put", s_, "changeOwnerSettings", "settings", "settings", problems=(401, 422))
    route(
        "post", v + "/{vehicle}/tags/unlink", "unlinkTag", "vehicle", "tag-unlink", problems=write
    )
    paths[t + "/{uid}/qr.svg"] = {
        "get": {
            "operationId": "tagQrCode",
            "parameters": [
                {"name": "uid", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": {
                    "description": "The QR code with the tag's address, for its owner",
                    "content": {"image/svg+xml": {"schema": {"type": "string"}}},
                },
                "404": {
                    "description": "Catalog säger nej",
                    "content": {"application/json": {"schema": openapi_ref(c + "problem")}},
                },
            },
        }
    }
    # A fleet shared with the person (#49): ?fleet=<owner> works in it, with the right ID says
    # now. 403 when only the owner may, 503 when ID does not answer (CAT-49, KONTO-34).
    fleet_param: JsonSchemaValue = {
        "name": "fleet",
        "in": "query",
        "description": "The owner's id, to work in a fleet shared with the person.",
        "schema": {"type": "string", "format": "uuid"},
    }
    for path, methods in paths.items():
        if not path.startswith(("/api/catalog/1/vehicles", "/api/catalog/1/places")):
            continue
        for entry in methods.values():
            entry.setdefault("parameters", []).append(fleet_param)
            for code in (403, 503):
                entry["responses"][str(code)] = {
                    "description": "Catalog säger nej",
                    "content": {"application/json": {"schema": openapi_ref(c + "problem")}},
                }
    return (
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "TrainMeet Catalog · kontrakten", "version": "1"},
                "paths": paths,
                "components": {
                    "schemas": components([s for s in CONTRACTS if s.startswith(CATALOG_PREFIX)]),
                    "securitySchemes": {
                        "session": {"type": "apiKey", "in": "cookie", "name": "catalog_session"}
                    },
                },
                "security": [{"session": []}],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def id_openapi() -> str:
    """TrainMeet ID's own API (#67, KONTO-34). The person's session is a cookie; an app asks
    with an access token from Keycloak's client credentials."""
    paths: dict[str, dict[str, JsonSchemaValue]] = {}
    c = "trainmeet.id-1."

    def route(
        method: str,
        path: str,
        operation: str,
        response: str | None,
        request: str | None = None,
        *,
        many: bool = False,
        created: bool = False,
        query: tuple[str, ...] = (),
        problems: tuple[int, ...] = (),
        app: bool = False,
    ) -> None:
        responses: dict[str, JsonSchemaValue] = {}
        if response is not None:
            body = openapi_ref(c + response)
            if many:
                body = {"type": "array", "items": body}
            responses["201" if created else "200"] = {
                "description": "OK",
                "content": {"application/json": {"schema": body}},
            }
        for code in problems:
            responses[str(code)] = {
                "description": "ID säger nej",
                "content": {"application/json": {"schema": openapi_ref(c + "problem")}},
            }
        entry: JsonSchemaValue = {"operationId": operation, "responses": responses}
        if request:
            entry["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": openapi_ref(c + request)}},
            }
        params = [
            {"name": part[1:-1], "in": "path", "required": True, "schema": {"type": "string"}}
            for part in path.split("/")
            if part.startswith("{")
        ]
        params += [
            {"name": name, "in": "query", "required": app, "schema": {"type": "string"}}
            for name in query
        ]
        if params:
            entry["parameters"] = params
        if app:
            entry["security"] = [{"app": []}]
        paths.setdefault(path, {})[method] = entry

    a = "/api/id/1"
    write = (401, 403, 404, 409, 422)
    route("get", "/api/version", "idVersion", "version")
    route("get", a + "/session", "idSession", "session")
    route("delete", a + "/session", "idLogOut", "session")
    for path, operation, query in (
        (a + "/login", "idLogIn", ("next", "lang")),
        (a + "/login/callback", "idLoginCallback", ("code", "state", "error")),
    ):
        paths[path] = {
            "get": {
                "operationId": operation,
                "parameters": [
                    {"name": name, "in": "query", "schema": {"type": "string"}} for name in query
                ],
                "responses": {"303": {"description": "Vidare, med Location."}},
            }
        }
    route("get", a + "/clubs", "clubs", "club", many=True, problems=(401,))
    route("post", a + "/clubs", "createClub", "club", "club-name", created=True, problems=write)
    route("get", a + "/clubs/{club}", "clubPage", "club-page", problems=(401, 404))
    route(
        "post",
        a + "/clubs/{club}/invitations",
        "inviteToClub",
        "invitation",
        "invite",
        created=True,
        problems=(*write, 503),
    )
    route(
        "put",
        a + "/clubs/{club}/members/{member}",
        "changeClubRole",
        "club-page",
        "club-role-change",
        problems=write,
    )
    route(
        "delete",
        a + "/clubs/{club}/members/{member}",
        "removeMember",
        "club-page",
        problems=write,
    )
    route("get", a + "/account/removal", "removalPlan", "removal-plan", problems=(401,))
    route("get", a + "/account/export", "exportAccount", "account-export", problems=(401, 503))
    route(
        "post",
        a + "/account/remove",
        "removeAccount",
        "session",
        "remove-account",
        problems=(401, 409, 422, 503),
    )
    route("get", a + "/fleets/{owner}", "fleetPage", "fleet-page", problems=(401, 403, 404))
    route(
        "post",
        a + "/fleets/{owner}/invitations",
        "inviteToFleet",
        "invitation",
        "fleet-invite",
        created=True,
        problems=(*write, 503),
    )
    route("delete", a + "/grants/{grant}", "removeGrant", "removed", problems=write)
    route(
        "post",
        a + "/clubs/{club}/meets",
        "createMeet",
        "meet",
        "new-meet",
        created=True,
        problems=write,
    )
    route("get", a + "/meets", "meets", "meet", many=True, problems=(401,))
    route("get", a + "/meets/{meet}", "meetPage", "meet-page", problems=(401, 404))
    route("put", a + "/meets/{meet}", "changeMeet", "meet-page", "new-meet", problems=write)
    route("delete", a + "/meets/{meet}", "removeMeet", "removed", problems=write)
    route(
        "post", a + "/meets/{meet}/grants", "giveAtMeet", "meet-page", "meet-grant", problems=write
    )
    route(
        "post", a + "/help", "sendHelp", "help-sent", "help-request", problems=(401, 422, 429, 503)
    )
    route("get", a + "/invitations", "invitations", "invitation", many=True, problems=(401,))
    route(
        "post",
        a + "/invitations/{invitation}/answer",
        "answerInvitation",
        "invitation",
        "answer",
        problems=write,
    )
    route(
        "delete", a + "/invitations/{invitation}", "withdrawInvitation", "removed", problems=write
    )
    route(
        "get",
        a + "/apps/access",
        "appAccess",
        "access",
        query=("person", "resource"),
        problems=(401, 422),
        app=True,
    )
    route(
        "get",
        a + "/apps/switcher",
        "appSwitcher",
        "switcher",
        query=("person",),
        problems=(401, 422),
        app=True,
    )
    route(
        "get",
        a + "/apps/fleets",
        "appFleets",
        "fleet-access",
        many=True,
        query=("person",),
        problems=(401, 422),
        app=True,
    )
    return (
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "TrainMeet ID · kontrakten", "version": "1"},
                "paths": paths,
                "components": {
                    "schemas": components([s for s in CONTRACTS if s.startswith(ID_PREFIX)]),
                    "securitySchemes": {
                        "session": {"type": "apiKey", "in": "cookie", "name": "id_session"},
                        "app": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
                    },
                },
                "security": [{"session": []}],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


OPENAPI_FILES = {OPENAPI: openapi, CATALOG_OPENAPI: catalog_openapi, ID_OPENAPI: id_openapi}


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
        for path, write in OPENAPI_FILES.items():
            if not path.exists() or path.read_text(encoding="utf-8") != write():
                stale.append(path.name)
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
    for path, write in OPENAPI_FILES.items():
        path.write_text(write(), encoding="utf-8")
    print(f"Skrev {len(expected)} scheman i contracts/schemas/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
