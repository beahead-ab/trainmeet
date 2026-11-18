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
    driver,
    hub,
    meet,
    planning,
    screen,
    station,
    station_outside,
    sync,
    terminal,
    tkl,
    tokens,
)
from contracts import id as id_api

SCHEMA_DIR = Path(__file__).parent / "schemas"
OPENAPI = SCHEMA_DIR.parent / "openapi.json"
CATALOG_OPENAPI = SCHEMA_DIR.parent / "catalog.openapi.json"
CATALOG_PREFIX = "trainmeet.catalog-"
ID_OPENAPI = SCHEMA_DIR.parent / "id.openapi.json"
ID_PREFIX = "trainmeet.id-"
TKL_OPENAPI = SCHEMA_DIR.parent / "tkl.openapi.json"
TKL_PREFIX = "trainmeet.tkl-"
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
    "trainmeet.station-1.push-token": station.PushToken,
    "trainmeet.station-1.notice": station.Notice,
    "trainmeet.station-1.exit-answer": station.ExitAnswer,
    "trainmeet.station-1.track-display-change": station.TrackDisplayChange,
    "trainmeet.tkl-1.state": tkl.TklState,
    "trainmeet.tkl-1.setup": tkl.TklSetUp,
    "trainmeet.tkl-1.unlock": tkl.TklUnlock,
    "trainmeet.tkl-1.pin-change": tkl.TklPinChange,
    "trainmeet.tkl-1.studio": tkl.TklStudio,
    "trainmeet.tkl-1.found-hub": tkl.FoundHub,
    "trainmeet.tkl-1.connect": tkl.TklConnect,
    "trainmeet.tkl-1.connection": tkl.TklConnection,
    "trainmeet.tkl-1.view": tkl.TklView,
    "trainmeet.tkl-1.command": tkl.TklCommand,
    "trainmeet.tkl-1.id-state": tkl.TklIdState,
    "trainmeet.tkl-1.save": tkl.TklSave,
    "trainmeet.tkl-1.saved": tkl.TklSaved,
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
    "trainmeet.drift-1.take-over": drift.TakeOver,
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
    "trainmeet.drift-1.couple-exit": drift.CoupleExit,
    "trainmeet.drift-1.client": drift.Client,
    "trainmeet.drift-1.event": drift.DriftEvent,
    "trainmeet.drift-1.now": drift.Now,
    "trainmeet.drift-1.tellurian-log": drift.TellurianLogEntry,
    "trainmeet.drift-1.joining": drift.Joining,
    "trainmeet.drift-1.refusal": drift.Refusal,
    "trainmeet.drift-1.automation-settings": drift.AutomationSettings,
    "trainmeet.drift-1.automation-place": drift.AutomationPlace,
    "trainmeet.drift-1.automation": drift.AutomationStatus,
    "trainmeet.drift-1.preview": drift.Preview,
    "trainmeet.drift-1.preview-clients": drift.PreviewClients,
    "trainmeet.drift-1.driver-settings": drift.DriverSettings,
    "trainmeet.drift-1.service": drift.ServiceRef,
    "trainmeet.driver-1.join": driver.DriverJoin,
    "trainmeet.driver-1.session": driver.DriverSession,
    "trainmeet.driver-1.me": driver.DriverMe,
    "trainmeet.driver-1.profile": driver.DriverProfile,
    "trainmeet.driver-1.services": driver.ServiceList,
    "trainmeet.driver-1.korplan": driver.Korplan,
    "trainmeet.driver-1.check-in": driver.CheckIn,
    "trainmeet.driver-1.framme": driver.Framme,
    "trainmeet.driver-1.message-send": driver.DriverMessageSend,
    "trainmeet.driver-1.message": driver.DriverMessage,
    "trainmeet.driver-1.clock": driver.DriverClock,
    "trainmeet.driver-1.train-position": driver.TrainPosition,
    "trainmeet.driver-1.presence": driver.DriverPresence,
    "trainmeet.driver-1.wait": driver.DriverWait,
    "trainmeet.driver-1.instructions": driver.Instructions,
    "trainmeet.driver-1.overview": driver.DriverOverview,
    "trainmeet.driver-1.hand-out": driver.HandOut,
    "trainmeet.driver-1.take-back": driver.TakeBack,
    "trainmeet.screen-1.login": screen.ScreenLogin,
    "trainmeet.screen-1.session": screen.ScreenSession,
    "trainmeet.screen-1.show": screen.ShowView,
    "trainmeet.screen-1.picture": screen.ScreenPicture,
    "trainmeet.hub-1.info": hub.HubInfo,
    "trainmeet.hub-1.setup": hub.SetUp,
    "trainmeet.hub-1.login": hub.LogIn,
    "trainmeet.hub-1.session": hub.Session,
    "trainmeet.hub-1.rename": hub.Rename,
    "trainmeet.hub-1.pin-change": hub.PinChange,
    "trainmeet.hub-1.wifi-status": hub.WifiStatus,
    "trainmeet.hub-1.wifi-profile-change": hub.WifiProfileChange,
    "trainmeet.hub-1.wifi-action": hub.WifiAction,
    "trainmeet.hub-1.update-status": hub.UpdateStatus,
    "trainmeet.hub-1.meet-wifi": hub.MeetWifi,
    "trainmeet.hub-1.meet-wifi-change": hub.MeetWifiChange,
    "trainmeet.hub-1.clock-source": hub.ClockSourceSettings,
    "trainmeet.hub-1.clock-source-change": hub.ClockSourceChange,
    "trainmeet.hub-1.tellurian": hub.TellurianSettings,
    "trainmeet.hub-1.tellurian-change": hub.TellurianChange,
    "trainmeet.hub-1.shared-wifi": hub.SharedWifi,
    "trainmeet.hub-1.participant": hub.Participant,
    "trainmeet.hub-1.version": hub.Version,
    "trainmeet.hub-1.ai-service": hub.AiService,
    "trainmeet.hub-1.ai-service-change": hub.AiServiceChange,
    "trainmeet.hub-1.code-login": hub.CodeLogIn,
    "trainmeet.hub-1.logged-out": hub.LoggedOut,
    "trainmeet.hub-1.one-time-code-request": hub.OneTimeCodeRequest,
    "trainmeet.hub-1.one-time-code": hub.OneTimeCode,
    "trainmeet.hub-1.let-in": hub.LetIn,
    "trainmeet.planning-1.import": planning.ImportResult,
    "trainmeet.planning-1.draft": planning.Draft,
    "trainmeet.planning-1.new-meet": planning.NewMeet,
    "trainmeet.planning-1.id-meet-choice": planning.IdMeetChoice,
    "trainmeet.planning-1.meet-summary": planning.MeetSummary,
    "trainmeet.planning-1.changes": planning.Changes,
    "trainmeet.planning-1.import-preview": planning.ImportPreview,
    "trainmeet.planning-1.answer": planning.Answer,
    "trainmeet.planning-1.double-track-answer": planning.DoubleTrackAnswer,
    "trainmeet.planning-1.let-stand": planning.LetStand,
    "trainmeet.planning-1.check": planning.Check,
    "trainmeet.planning-1.track-picture": planning.TrackPicture,
    "trainmeet.planning-1.ai-pages": planning.AiPages,
    "trainmeet.planning-1.version": planning.Version,
    "trainmeet.planning-1.proposal": planning.Proposal,
    "trainmeet.sync-1.hello": sync.Hello,
    "trainmeet.sync-1.link-code": sync.LinkCode,
    "trainmeet.sync-1.link-request": sync.LinkRequest,
    "trainmeet.sync-1.link": sync.Link,
    "trainmeet.sync-1.version-list": sync.VersionList,
    "trainmeet.sync-1.follower": sync.Follower,
    "trainmeet.sync-1.cloud-link": sync.CloudLink,
    "trainmeet.sync-1.cloud-link-change": sync.CloudLinkChange,
    "trainmeet.sync-1.run-events": sync.RunEvents,
    "trainmeet.sync-1.run-ack": sync.RunAck,
    "trainmeet.sync-1.run-feed": sync.RunFeed,
    "trainmeet.sync-1.home": sync.Home,
    "trainmeet.sync-1.home-bundle": sync.HomeBundle,
    "trainmeet.sync-1.sent-version": sync.SentVersion,
    "trainmeet.sync-1.relay-call": sync.RelayCall,
    "trainmeet.sync-1.relay-calls": sync.RelayCalls,
    "trainmeet.sync-1.relay-answer": sync.RelayAnswer,
    "trainmeet.sync-1.push": sync.Push,
    "trainmeet.sync-1.push-batch": sync.PushBatch,
    "trainmeet.sync-1.station-package": sync.StationPackage,
    "trainmeet.sync-1.station-version-info": sync.StationVersionInfo,
    "trainmeet.sync-1.station-versions": sync.StationVersions,
    "trainmeet.sync-1.pi-login-start": sync.PiLoginStart,
    "trainmeet.sync-1.pi-login-started": sync.PiLoginStarted,
    "trainmeet.sync-1.pi-ticket": sync.PiTicket,
    "trainmeet.catalog-1.version": catalog.CatalogVersion,
    "trainmeet.catalog-1.account": catalog.Account,
    "trainmeet.catalog-1.session": catalog.Session,
    "trainmeet.catalog-1.trial-login": catalog.TrialLogin,
    "trainmeet.catalog-1.fleet-choice": catalog.FleetChoice,
    "trainmeet.catalog-1.vehicle-fields": catalog.VehicleFields,
    "trainmeet.catalog-1.vehicle-change": catalog.VehicleChange,
    "trainmeet.catalog-1.new-vehicle": catalog.NewVehicle,
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
    "trainmeet.catalog-1.picture": catalog.Picture,
    "trainmeet.catalog-1.picture-links": catalog.PictureLinks,
    "trainmeet.catalog-1.storage-use": catalog.StorageUse,
    "trainmeet.catalog-1.background-change": catalog.BackgroundChange,
    "trainmeet.catalog-1.trip-summary": catalog.TripSummary,
    "trainmeet.catalog-1.trip": catalog.Trip,
    "trainmeet.catalog-1.new-trip": catalog.NewTrip,
    "trainmeet.catalog-1.pack-list": catalog.PackList,
    "trainmeet.catalog-1.tick-change": catalog.TickChange,
    "trainmeet.catalog-1.trip-tap": catalog.TripTap,
    "trainmeet.catalog-1.trip-tapped": catalog.TripTapped,
    "trainmeet.catalog-1.reading": catalog.Reading,
    "trainmeet.catalog-1.reading-ask": catalog.ReadingAsk,
    "trainmeet.catalog-1.reading-consent": catalog.ReadingConsent,
    "trainmeet.catalog-1.batch": catalog.Batch,
    "trainmeet.catalog-1.batch-card": catalog.BatchCard,
    "trainmeet.catalog-1.batch-summary": catalog.BatchSummary,
    "trainmeet.catalog-1.batch-ask": catalog.BatchAsk,
    "trainmeet.catalog-1.batch-card-change": catalog.BatchCardChange,
    "trainmeet.catalog-1.batch-approval": catalog.BatchApproval,
    "trainmeet.catalog-1.tellurian-ask": catalog.TellurianAsk,
    "trainmeet.catalog-1.tellurian-import": catalog.TellurianImport,
    "trainmeet.catalog-1.field-register": catalog.FieldRegister,
    "trainmeet.catalog-1.prototype": catalog.Prototype,
    "trainmeet.catalog-1.prototype-list": catalog.PrototypeList,
    "trainmeet.catalog-1.prototype-revision": catalog.PrototypeRevision,
    "trainmeet.catalog-1.prototype-proposal": catalog.PrototypeProposal,
    "trainmeet.catalog-1.prototype-review": catalog.PrototypeReview,
    "trainmeet.catalog-1.prototype-summary": catalog.PrototypeSummary,
    "trainmeet.catalog-1.prototype-link": catalog.PrototypeLink,
    "trainmeet.catalog-1.prototype-overrides": catalog.PrototypeOverrides,
    "trainmeet.catalog-1.vehicle-prototype": catalog.VehiclePrototype,
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
    "trainmeet.id-1.ticket-request": id_api.TicketRequest,
    "trainmeet.id-1.ticket": id_api.Ticket,
    "trainmeet.id-1.ticket-keys": id_api.TicketKeys,
    "trainmeet.id-1.token-owner": tokens.TokenOwner,
    "trainmeet.id-1.token-balance": tokens.TokenBalance,
    "trainmeet.id-1.token-reserve": tokens.TokenReserve,
    "trainmeet.id-1.token-draw": tokens.TokenDraw,
    "trainmeet.id-1.token-reservation": tokens.TokenReservation,
    "trainmeet.id-1.meter-image": tokens.MeterImage,
    "trainmeet.id-1.meter-read": tokens.MeterRead,
    "trainmeet.id-1.meter-answer": tokens.MeterAnswer,
    "trainmeet.id-1.token-package": tokens.TokenPackage,
    "trainmeet.id-1.token-shop": tokens.TokenShop,
    "trainmeet.id-1.token-purchase": tokens.TokenPurchase,
    "trainmeet.id-1.token-checkout": tokens.TokenCheckout,
    "trainmeet.id-1.own-ai-state": tokens.OwnAiState,
    "trainmeet.id-1.own-ai-change": tokens.OwnAiChange,
    "trainmeet.id-1.token-settings": tokens.TokenSettings,
    "trainmeet.id-1.token-month": tokens.TokenMonth,
    "trainmeet.id-1.owner-page": tokens.OwnerPage,
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
    "trainmeet.id-1.reviewer-grant": id_api.ReviewerGrant,
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
        [s for s in CONTRACTS if not s.startswith((CATALOG_PREFIX, ID_PREFIX, TKL_PREFIX))]
    )
    paths: dict[str, dict[str, JsonSchemaValue]] = {}

    def route(
        method: str,
        path: str,
        operation: str,
        response: str | None,
        request: str | None = None,
        *,
        bearer: bool = False,
        many: bool = False,
        stream: bool = False,
        driver_key: bool = False,
    ) -> None:
        """response None: the answer is 204, with no body. driver_key: Lokföraren's device key,
        in its cookie or in X-Driver-Key (trainmeet.driver/1)."""
        entry: JsonSchemaValue = {
            "operationId": operation,
            "responses": {"204": {"description": "No Content"}},
        }
        if response is not None:
            body = openapi_ref(response)
            if many:
                body = {"type": "array", "items": body}
            if stream:
                body = {"type": "string", "x-event-schema": body}
            media = "text/event-stream" if stream else "application/json"
            entry["responses"] = {
                "200": {"description": "OK", "content": {media: {"schema": body}}}
            }
        if request:
            entry["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": openapi_ref(request)}},
            }
        if bearer:
            entry["security"] = [{"clientKey": []}]
        if driver_key:
            entry["security"] = [{"driverKey": []}, {"driverCookie": []}]
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
    route(
        "post",
        "/api/station/1/places/{place}/exits",
        "stationExit",
        s + "snapshot",
        s + "exit-answer",
        bearer=True,
    )
    route(
        "put",
        "/api/station/1/places/{place}/track-display",
        "stationTrackDisplay",
        s + "snapshot",
        s + "track-display-change",
        bearer=True,
    )
    route("put", "/api/station/1/push", "stationPush", None, s + "push-token", bearer=True)
    route("delete", "/api/station/1/push", "stationPushOff", None, bearer=True)
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
    route(
        "post",
        "/api/drift/1/clients/exit",
        "coupleExit",
        d + "client",
        d + "couple-exit",
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
    # Förarnas API (trainmeet.driver/1): Lokföraren, and Förare in Drift (TRAFIK-33).
    f = "trainmeet.driver-1."
    dr = "/api/drift/1/drivers"
    route("post", dr + "/join", "driverJoin", f + "session", f + "join")
    route("get", dr + "/me", "driverMe", f + "me", driver_key=True)
    route("post", dr + "/me", "driverProfile", f + "me", f + "profile", driver_key=True)
    route("post", dr + "/me/photo", "driverPhoto", f + "me", driver_key=True)
    paths[dr + "/me/photo"]["post"]["requestBody"] = {
        "required": True,
        "content": {
            kind: {"schema": {"type": "string", "format": "binary"}}
            for kind in ("image/png", "image/jpeg", "image/webp")
        },
    }
    route("post", dr + "/me/photo/remove", "driverPhotoRemove", f + "me", driver_key=True)
    route("get", dr + "/services", "driverServices", f + "services", driver_key=True)
    paths[dr + "/services"]["get"]["parameters"] = [
        {"name": "q", "in": "query", "schema": {"type": "string"}}
    ]
    route("post", dr + "/claim", "driverClaim", f + "me", d + "service", driver_key=True)
    route("post", dr + "/release", "driverRelease", f + "me", driver_key=True)
    route("get", dr + "/korplan", "driverKorplan", f + "korplan", driver_key=True)
    route("post", dr + "/checkin", "driverCheckIn", f + "me", f + "check-in", driver_key=True)
    route("post", dr + "/framme", "driverFramme", f + "me", f + "framme", driver_key=True)
    route(
        "post",
        dr + "/messages",
        "driverMessage",
        f + "message",
        f + "message-send",
        driver_key=True,
    )
    route("get", dr + "/clock", "driverClock", f + "clock")
    route("get", dr + "/trains", "driverTrains", f + "train-position", many=True)
    route("get", dr + "/list", "driverList", f + "presence", many=True)
    route("get", dr + "/wait", "driverWait", f + "wait")
    paths[dr + "/wait"]["get"]["parameters"] = [
        {"name": "after", "in": "query", "required": True, "schema": {"type": "integer"}},
        {"name": "seconds", "in": "query", "schema": {"type": "number"}},
    ]
    route("get", dr + "/instructions", "driverInstructions", f + "instructions")
    route("post", dr + "/leave", "driverLeave", None, driver_key=True)
    route("get", dr + "/overview", "driverOverview", f + "overview", bearer=True)
    route("post", dr + "/hand-out", "handOutService", f + "overview", f + "hand-out", bearer=True)
    route(
        "post", dr + "/take-back", "takeBackService", f + "overview", f + "take-back", bearer=True
    )
    route(
        "post",
        dr + "/settings",
        "driverSettings",
        f + "overview",
        d + "driver-settings",
        bearer=True,
    )
    route("post", dr + "/alarms/clear", "clearAlarm", f + "overview", d + "service", bearer=True)
    route("get", dr + "/connect", "driverJoining", d + "joining", bearer=True)
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
    route(
        "post",
        pv + "/clients/exit",
        "coupleExitPreview",
        d + "preview-clients",
        d + "couple-exit",
    )
    v = "trainmeet.screen-1."
    route("post", "/api/screen/session", "screenLogin", v + "session", v + "login")
    route("get", "/api/screen/picture", "screenPicture", v + "picture", bearer=True)
    route("get", "/api/screen/package", "screenPackage", "trainmeet.meet-1", bearer=True)
    route("post", "/api/drift/1/clients/view", "showView", d + "client", v + "show", bearer=True)
    h = "trainmeet.hub-1."
    route("get", "/api/hub", "hubInfo", h + "info")
    route("get", "/api/version", "hubVersion", h + "version")
    route("post", "/api/hub/setup", "hubSetUp", h + "session", h + "setup")
    route("post", "/api/hub/login", "hubLogIn", h + "session", h + "login")
    route("post", "/api/hub/login/code", "hubCodeLogIn", h + "session", h + "code-login")
    route("post", "/api/hub/logout", "hubLogOut", h + "logged-out")
    route(
        "post",
        "/api/drift/1/codes",
        "giveOneTimeCode",
        h + "one-time-code",
        h + "one-time-code-request",
        bearer=True,
    )
    route("get", "/api/drift/1/let-in", "letIn", h + "let-in", bearer=True, many=True)
    route("post", "/api/drift/1/let-in/{person}/remove", "takeAwayLetIn", None, bearer=True)
    route("post", "/api/hub/name", "renameHub", h + "info", h + "rename", bearer=True)
    route("post", "/api/hub/pin", "changePin", None, h + "pin-change", bearer=True)
    route("get", "/api/hub/wifi", "piWifi", h + "wifi-status", bearer=True)
    route("get", "/api/hub/update", "hubUpdate", h + "update-status", bearer=True)
    route("post", "/api/hub/update", "startHubUpdate", h + "update-status", bearer=True)
    route("get", "/api/hub/tellurian", "tellurian", h + "tellurian", bearer=True)
    route(
        "post",
        "/api/hub/tellurian",
        "setTellurian",
        h + "tellurian",
        h + "tellurian-change",
        bearer=True,
    )
    route("get", "/api/hub/tellurian/log", "tellurianLog", d + "tellurian-log", many=True)
    route("get", "/api/hub/clock-source", "clockSource", h + "clock-source", bearer=True)
    route(
        "post",
        "/api/hub/clock-source",
        "setClockSource",
        h + "clock-source",
        h + "clock-source-change",
        bearer=True,
    )
    route("get", "/api/hub/meet-wifi", "meetWifi", h + "meet-wifi", bearer=True)
    route(
        "put",
        "/api/hub/meet-wifi",
        "setMeetWifi",
        h + "meet-wifi",
        h + "meet-wifi-change",
        bearer=True,
    )
    route("get", "/api/deltagare", "participant", h + "participant")
    wifi = "/api/hub/wifi/"
    route(
        "post",
        wifi + "save",
        "savePiWifi",
        h + "wifi-status",
        h + "wifi-profile-change",
        bearer=True,
    )
    route(
        "post", wifi + "{action}", "piWifiAction", h + "wifi-status", h + "wifi-action", bearer=True
    )
    route("get", "/api/hub/ai", "hubAiService", h + "ai-service", bearer=True)
    route(
        "post", "/api/hub/ai", "connectAi", h + "ai-service", h + "ai-service-change", bearer=True
    )
    y = "trainmeet.sync-1."
    st = "/api/sync/1/stations/{station}/versions"
    pl = "/api/sync/1/meets/{meet}/id-login"
    route("post", pl, "piLoginStart", y + "pi-login-started", y + "pi-login-start", bearer=True)
    route("get", pl + "/{attempt}", "piTicket", y + "pi-ticket", bearer=True)
    route("post", "/api/hub/id/again", "hubLogInAgain", h + "session")
    route("post", st, "saveStation", y + "station-version-info", y + "station-package", bearer=True)
    route("get", st, "stationVersions", y + "station-versions", bearer=True)
    route("get", st + "/{number}", "stationPackage", y + "station-package", bearer=True)
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
    route("get", m + "/{meet}/picture", "planningTrackPicture", p + "track-picture")
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
    # Förarna (PLAN-40): the general instructions as PDF, kept beside the package.
    route("post", m + "/{meet}/instructions.pdf", "instructionsPdf", p + "draft", bearer=True)
    paths[m + "/{meet}/instructions.pdf"]["post"]["requestBody"] = {
        "required": True,
        "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
    }
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
                    "securitySchemes": {
                        "clientKey": {"type": "http", "scheme": "bearer"},
                        "driverKey": {"type": "apiKey", "in": "header", "name": "X-Driver-Key"},
                        "driverCookie": {
                            "type": "apiKey",
                            "in": "cookie",
                            "name": "trainmeet_forare",
                        },
                    },
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
    route("post", v, "addVehicle", "vehicle", "new-vehicle", created=True, problems=write)
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
    # The pictures (CAT-05, CAT-17, CAT-123–CAT-133). The upload's body is the picture itself.
    pictures = v + "/{vehicle}/pictures"
    backgrounds: JsonSchemaValue = {
        "type": "string",
        "enum": [b.value for b in catalog.PictureBackground],
        "default": catalog.PictureBackground.ORIGINAL.value,
    }
    route("get", pictures, "vehiclePictures", "picture", many=True, problems=(401, 404))
    route(
        "post",
        pictures,
        "addPicture",
        "picture",
        created=True,
        query=(
            ("keep_original", {"type": "boolean", "default": False}),
            ("background", backgrounds),
        ),
        # 402 and 429: the storage over the free level could not be paid (CAT-132).
        problems=(401, 402, 404, 413, 415, 422, 429, 503),
    )
    paths[pictures]["post"]["requestBody"] = {
        "required": True,
        "description": "The picture: at most 15 MB and 40 megapixel (CAT-123).",
        "content": {
            kind: {"schema": {"type": "string", "format": "binary"}}
            for kind in ("image/jpeg", "image/png", "image/webp")
        },
    }
    route("post", pictures + "/{picture}/main", "mainPicture", "picture", many=True, problems=write)
    # Friläggningen (CAT-127–CAT-129): made again from the photo and the mask kept at the upload.
    route(
        "post",
        pictures + "/{picture}/background",
        "pictureBackground",
        "picture",
        "background-change",
        problems=(*write, 402, 429, 503),
    )
    route("delete", pictures + "/{picture}", "removePicture", "removed", problems=write)
    route("get", "/api/catalog/1/storage", "storageUse", "storage-use", problems=(401,))
    # The trip to the meet (#55, CAT-174–CAT-183): the owner's own, so 403 for a shared fleet.
    m = "/api/catalog/1/meets"
    trip_write = (401, 404, 409, 422)
    route("get", m, "trips", "trip-summary", many=True, problems=(401,))
    route("post", m, "newTrip", "trip", "new-trip", created=True, problems=(401, 404, 422))
    route("get", m + "/{meet}", "trip", "trip", problems=(401, 404))
    route("post", m + "/{meet}/vehicles", "packList", "trip", "pack-list", problems=trip_write)
    route("post", m + "/{meet}/ticks", "tick", "trip", "tick-change", problems=trip_write)
    route("post", m + "/{meet}/tap", "tapInTrip", "trip-tapped", "trip-tap", problems=trip_write)
    route("post", m + "/{meet}/archive", "archiveTrip", "trip", problems=trip_write)
    # Only when Catalog keeps the pictures on its own disk: the signed address is the right.
    paths["/api/catalog/1/pictures/file/{key}"] = {
        "get": {
            "operationId": "pictureFile",
            "security": [],
            "parameters": [
                {"name": "key", "in": "path", "required": True, "schema": {"type": "string"}},
                {"name": "expires", "in": "query", "schema": {"type": "string"}},
                {"name": "sig", "in": "query", "schema": {"type": "string"}},
            ],
            "responses": {
                "200": {
                    "description": "The picture, kept by the browser until the address expires",
                    "content": {
                        kind: {"schema": {"type": "string", "format": "binary"}}
                        for kind in ("image/jpeg", "image/webp")
                    },
                },
                "403": {"description": "The address is not signed by Catalog, or has expired"},
                "404": {"description": "No such picture, or the pictures are in Object Storage"},
            },
        }
    }
    # The reading of a photo with AI (CAT-135–CAT-146): a form with the ask and the photos.
    readings = "/api/catalog/1/readings"
    route(
        "get",
        readings + "/consent",
        "readingConsent",
        "reading-consent",
        problems=(401, 404),
    )
    route(
        "post",
        readings,
        "readPhotos",
        "reading",
        # 402: the balance is short. 409: changed, or reading_busy. 422: consent_required or a
        # photo that cannot be read. 429: ten an hour, with Retry-After. 502: reading_failed.
        problems=(401, 402, 404, 409, 413, 415, 422, 429, 502),
    )
    paths[readings]["post"]["requestBody"] = {
        "required": True,
        "description": "The ask as JSON in the part data, and 1–4 photos in the parts images, "
        "each at most 15 MB and 40 megapixel (CAT-123).",
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "data": openapi_ref(c + "reading-ask"),
                        "images": {
                            "type": "array",
                            "items": {"type": "string", "format": "binary"},
                            "minItems": 1,
                            "maxItems": 4,
                        },
                    },
                    "required": ["data", "images"],
                },
                "encoding": {
                    "data": {"contentType": "application/json"},
                    "images": {"contentType": "image/jpeg, image/png, image/webp"},
                },
            }
        },
    }
    # Several photos in a batch (#52 del b, CAT-146–CAT-153): a form like the reading's, and
    # the queue, the drafts and Godkänn alla.
    b = "/api/catalog/1/batches"
    batch_write = (401, 404, 409, 422)
    route("get", b, "batches", "batch-summary", many=True, problems=(401, 404))
    route(
        "post",
        b,
        "addBatchPhotos",
        "batch",
        # 403: AI asked by someone who edits. 409: the id is another's. 413: over 60 MB in one
        # request. 422: consent_required, too_many_pictures, or a photo that cannot be read.
        problems=(401, 404, 409, 413, 415, 422),
    )
    paths[b]["post"]["requestBody"] = {
        "required": True,
        "description": "The ask as JSON in the part data, and 1–30 photos in the parts images, "
        "each at most 15 MB and 40 megapixel (CAT-123), at most 60 MB in one request: send the "
        "rest with the same id.",
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "data": openapi_ref(c + "batch-ask"),
                        "images": {
                            "type": "array",
                            "items": {"type": "string", "format": "binary"},
                            "minItems": 1,
                            "maxItems": catalog.MAX_BATCH_PHOTOS,
                        },
                    },
                    "required": ["data", "images"],
                },
                "encoding": {
                    "data": {"contentType": "application/json"},
                    "images": {"contentType": "image/jpeg, image/png, image/webp"},
                },
            }
        },
    }
    route("get", b + "/{batch}", "batch", "batch", problems=(401, 404))
    route("delete", b + "/{batch}", "removeBatch", "removed", problems=batch_write)
    card = b + "/{batch}/cards/{card}"
    route("post", card, "changeBatchCard", "batch-card", "batch-card-change", problems=batch_write)
    route("delete", card, "removeBatchCard", "removed", problems=batch_write)
    route("post", card + "/retry", "retryBatchCard", "batch-card", problems=batch_write)
    route(
        "post",
        b + "/{batch}/approve",
        "approveBatch",
        "batch",
        "batch-approval",
        # 402 and 429: the storage over the free level could not be paid (CAT-132).
        problems=(*batch_write, 402, 429),
    )

    # Printing and files (#56, CAT-184–CAT-188). The QR labels are printed from the label's own
    # QR code; Tellurian's format is a file each way, and the account export one ZIP.
    def problem_answers(*codes: int) -> dict[str, JsonSchemaValue]:
        return {
            str(code): {
                "description": "Catalog säger nej",
                "content": {"application/json": {"schema": openapi_ref(c + "problem")}},
            }
            for code in codes
        }

    paths[v + "/{vehicle}/tellurian"] = {
        "get": {
            "operationId": "tellurianFile",
            "summary": "Fordonet som en fil i Tellurians format, med EVN delat (CAT-185).",
            "parameters": [
                {"name": "vehicle", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": {
                    "description": "The file, named after the litt and the number, to download",
                    "content": {"application/json": {"schema": {"type": "object"}}},
                },
                **problem_answers(401, 404),
            },
        }
    }
    route(
        "post",
        b + "/tellurian",
        "importTellurian",
        "tellurian-import",
        # 409: the id is another batch's. 413: over 60 MB together. 422: not 1–50 files, or more
        # drafts waiting than the owner may have. A file that cannot be read is in the answer.
        problems=(401, 404, 409, 413, 422),
    )
    paths[b + "/tellurian"]["post"]["requestBody"] = {
        "required": True,
        "description": "The ask as JSON in the part data, and 1–50 files in Tellurian's format in "
        "the parts files, each with its name, at most 20 MB each and 60 MB together (CAT-186).",
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "data": openapi_ref(c + "tellurian-ask"),
                        "files": {
                            "type": "array",
                            "items": {"type": "string", "format": "binary"},
                            "minItems": 1,
                            "maxItems": catalog.MAX_TELLURIAN_FILES,
                        },
                    },
                    "required": ["data", "files"],
                },
                "encoding": {
                    "data": {"contentType": "application/json"},
                    "files": {"contentType": "application/json"},
                },
            }
        },
    }
    paths["/api/catalog/1/export"] = {
        "get": {
            "operationId": "accountExport",
            "summary": "Kontoexport: allt ägaren har, som en ZIP med catalog.json och bilderna "
            "(CAT-188).",
            "responses": {
                "200": {
                    "description": "The ZIP: catalog.json (catalog-export) and the pictures' files",
                    "content": {
                        "application/zip": {"schema": {"type": "string", "format": "binary"}}
                    },
                },
                **problem_answers(401, 404),
            },
        }
    }
    # The prototype catalog (#53 del a, CAT-155–CAT-165, CAT-173). The register is open to all.
    f = "/api/catalog/1/prototypes"
    route("get", f + "/fields", "fieldRegister", "field-register")
    paths[f + "/fields"]["get"]["security"] = []
    route(
        "get",
        f,
        "prototypes",
        "prototype-list",
        query=(("q", text), ("kind", kinds)),
        problems=(401, 422),
    )
    route(
        "post",
        f + "/proposals",
        "proposePrototype",
        "prototype-revision",
        "prototype-proposal",
        created=True,
        problems=(401, 404, 409, 422),
    )
    route(
        "get",
        f + "/proposals/mine",
        "myProposals",
        "prototype-revision",
        many=True,
        problems=(401,),
    )
    route(
        "get",
        f + "/proposals/queue",
        "reviewQueue",
        "prototype-revision",
        many=True,
        problems=(401, 403, 503),
    )
    route(
        "post",
        f + "/proposals/{revision}/review",
        "reviewProposal",
        "prototype-revision",
        "prototype-review",
        problems=(401, 403, 404, 409, 422, 503),
    )
    route("get", f + "/{prototype}", "prototype", "prototype", problems=(401, 404))
    route(
        "post",
        v + "/{vehicle}/prototype",
        "linkPrototype",
        "vehicle",
        "prototype-link",
        problems=write,
    )
    route(
        "put",
        v + "/{vehicle}/prototype",
        "changeTypeData",
        "vehicle",
        "prototype-overrides",
        problems=write,
    )
    route(
        "delete",
        v + "/{vehicle}/prototype",
        "unlinkPrototype",
        "vehicle",
        query=(("version", {"type": "integer"}),),
        problems=write,
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
        if not path.startswith(
            (
                "/api/catalog/1/vehicles",
                "/api/catalog/1/places",
                "/api/catalog/1/storage",
                "/api/catalog/1/meets",
                "/api/catalog/1/readings",
                "/api/catalog/1/batches",
                "/api/catalog/1/export",
            )
        ):
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
    route("get", a + "/keys", "ticketKeys", "ticket-keys")
    route(
        "post",
        a + "/apps/tickets",
        "appTicket",
        "ticket",
        "ticket-request",
        problems=(401, 403, 404, 422),
        app=True,
    )
    route(
        "get",
        a + "/apps/meets",
        "appMeets",
        "meet",
        many=True,
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
    # TrainMeet tokens (#79, TOKEN-08): the person's balances, and the apps' reservations.
    route("get", a + "/tokens", "tokens", "token-balance", many=True, problems=(401,))
    # Köpen (TOKEN-02, TOKEN-11): Stripe Checkout, in test mode until MOMS is decided.
    route("get", a + "/tokens/shop", "tokenShop", "token-shop", problems=(401,))
    # Ägarsidan (TOKEN-05, TOKEN-18): for TrainMeet's owners.
    route("get", a + "/owner", "ownerPage", "owner-page", problems=(401, 403))
    route(
        "put",
        a + "/owner/settings",
        "changeOwnerSettings",
        "owner-page",
        "token-settings",
        problems=(401, 403, 422),
    )
    # Granskare i Catalog (KONTO-30, ID6, CAT-165): given and taken on the owner page.
    route("get", a + "/owner/reviewers", "reviewers", "grant", many=True, problems=(401, 403))
    route(
        "post",
        a + "/owner/reviewers",
        "giveReviewer",
        "grant",
        "reviewer-grant",
        many=True,
        problems=(401, 403, 404, 422),
    )
    route(
        "delete",
        a + "/owner/reviewers/{reviewer}",
        "takeReviewer",
        "grant",
        many=True,
        problems=(401, 403, 404, 422),
    )
    # Egen AI på kontot (TOKEN-03): the answer to GET is null when none is connected.
    route(
        "get",
        a + "/tokens/own-ai",
        "ownAi",
        "own-ai-state",
        query=("owner",),
        problems=(401, 403, 404, 422),
    )
    route(
        "put",
        a + "/tokens/own-ai",
        "connectOwnAi",
        "own-ai-state",
        "own-ai-change",
        query=("owner",),
        problems=(401, 403, 404, 422),
    )
    route(
        "delete",
        a + "/tokens/own-ai",
        "removeOwnAi",
        None,
        query=("owner",),
        problems=(401, 403, 404, 422),
    )
    route(
        "post",
        a + "/tokens/purchases",
        "buyTokens",
        "token-checkout",
        "token-purchase",
        problems=(401, 403, 404, 422, 502, 503),
    )
    paths[a + "/stripe/webhook"] = {
        "post": {
            "operationId": "stripeWebhook",
            "summary": "Stripe säger att en betalning är klar. Signerad av Stripe.",
            "security": [],
            "parameters": [
                {
                    "name": "Stripe-Signature",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {"type": "object"}}},
            },
            "responses": {
                "200": {"description": "Mottagen."},
                "400": {"description": "Signaturen stämmer inte."},
            },
        }
    }
    route(
        "get",
        a + "/apps/tokens",
        "appTokens",
        "token-balance",
        query=("person", "owner"),
        problems=(401, 403, 404, 422),
        app=True,
    )
    route(
        "post",
        a + "/apps/tokens/reservations",
        "appReserveTokens",
        "token-reservation",
        "token-reserve",
        created=True,
        problems=(401, 402, 403, 404, 409, 422),
        app=True,
    )
    route(
        "post",
        a + "/apps/tokens/reservations/{reservation}/draw",
        "appDrawTokens",
        "token-reservation",
        "token-draw",
        problems=(401, 404, 409, 422),
        app=True,
    )
    route(
        "post",
        a + "/apps/tokens/reservations/{reservation}/return",
        "appReturnTokens",
        "token-reservation",
        problems=(401, 404, 409),
        app=True,
    )
    # Mätaren (TOKEN-28): TrainMeets AI with the reservation.
    route(
        "post",
        a + "/apps/meter",
        "appReadWithMeter",
        "meter-answer",
        "meter-read",
        problems=(401, 404, 409, 422, 502, 503),
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


def tkl_openapi() -> str:
    """TrainMeet TKL's own API, between its server and its web app (KLAR-22). The session is a
    cookie set when the PIN unlocks TKL. The hub's station protocol is in openapi.json."""
    paths: dict[str, dict[str, JsonSchemaValue]] = {}
    t = "trainmeet.tkl-1."
    st = "trainmeet.station-1."

    def route(
        method: str,
        path: str,
        operation: str,
        response: str | None,
        request: str | None = None,
        *,
        many: bool = False,
        stream: bool = False,
    ) -> None:
        responses: dict[str, JsonSchemaValue] = {"204": {"description": "No Content"}}
        if response is not None:
            body = openapi_ref(response)
            if many:
                body = {"type": "array", "items": body}
            media = "application/json"
            if stream:
                body, media = {"type": "string", "x-event-schema": body}, "text/event-stream"
            responses = {"200": {"description": "OK", "content": {media: {"schema": body}}}}
        entry: JsonSchemaValue = {"operationId": operation, "responses": responses}
        if request:
            entry["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": openapi_ref(request)}},
            }
        params = [
            {"name": part[1:-1], "in": "path", "required": True, "schema": {"type": "string"}}
            for part in path.split("/")
            if part.startswith("{")
        ]
        if params:
            entry["parameters"] = params
        paths.setdefault(path, {})[method] = entry

    a = "/api/tkl/1"
    route("get", a + "/state", "tklState", t + "state")
    route("post", a + "/setup", "tklSetUp", t + "state", t + "setup")
    route("post", a + "/unlock", "tklUnlock", t + "state", t + "unlock")
    route("post", a + "/lock", "tklLock", t + "state")
    route("post", a + "/pin", "tklPin", None, t + "pin-change")
    route("get", a + "/studio", "tklStudio", t + "studio")
    route("put", a + "/studio", "tklSaveList", t + "studio", "trainmeet.station-outside-1")
    route("post", a + "/studio/version", "tklNewVersion", t + "studio")
    route("get", a + "/hubs", "tklHubs", t + "found-hub", many=True)
    route("get", a + "/connection", "tklConnection", t + "connection")
    route("post", a + "/connection", "tklConnect", t + "connection", t + "connect")
    route("delete", a + "/connection", "tklDisconnect", t + "connection")
    route("get", a + "/places/{place}", "tklPlace", t + "view")
    route("post", a + "/commands", "tklCommand", st + "reply", t + "command")
    route("post", a + "/places/{place}/exits", "tklExit", t + "view", st + "exit-answer")
    route("get", a + "/places/{place}/events", "tklEvents", st + "event", stream=True)
    route("get", a + "/id", "tklId", t + "id-state")
    route("post", a + "/id/logout", "tklIdLogOut", t + "id-state")
    route("post", a + "/id/save", "tklSaveInCloud", t + "saved", t + "save")
    stems = [
        s
        for s in CONTRACTS
        if s.startswith(TKL_PREFIX)
        or s in {st + "reply", st + "event", st + "exit-answer", "trainmeet.station-outside-1"}
    ]
    return (
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "TrainMeet TKL · kontrakten", "version": "1"},
                "paths": paths,
                "components": {
                    "schemas": components(stems),
                    "securitySchemes": {
                        "session": {"type": "apiKey", "in": "cookie", "name": "tkl_session"}
                    },
                },
                "security": [{"session": []}],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


OPENAPI_FILES = {
    OPENAPI: openapi,
    CATALOG_OPENAPI: catalog_openapi,
    ID_OPENAPI: id_openapi,
    TKL_OPENAPI: tkl_openapi,
}


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
