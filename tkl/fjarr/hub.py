"""The remote role towards Hubben (#36 del c): the plan's remote areas, the connect request, and
the fjärrbild's data. Only the contracts: the station protocol and Drift's open package.

The fjärrbild reads Hubben's Overview (`GET /api/station/1/overview`, also through the relay)
with no places named, so that Hubben gives every place TKL runs, controls, is offered or is
approved for, and their neighbours. The offers and what TKL controls are the client's own, in
any snapshot it may read: the station's own place for a station's TKL, the first approved place
for the remote interlocking. The overview has no revision counter yet, so the web app asks for
the picture again every few seconds, more often while a route waits for its answer.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Any, Final

import httpx
from pydantic import ValidationError

from contracts import station
from contracts.meet import PlaceKind, RemoteArea
from contracts.tkl import (
    TklFjarr,
    TklRemote,
    TklRemoteArea,
    TklRemoteAreas,
    TklRemoteConnect,
    TklRemotePlace,
)
from tkl.hub_client import HubClient
from tkl.store import Connection

PACKAGE: Final = "/api/drift/1/package"
"""The package Drift goes by, open to anyone who looks, like Nu: the plan's remote areas."""
NO_MEET: Final = "Hubben har ingen träff igång. Skriv driftplatserna i stället."
NO_HUB: Final = "Ingen kontakt med hubben. Skriv driftplatserna i stället."


def remote_id(name: str) -> str:
    """The remote interlocking's id in TKL's store, from its name: never a station's."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:60]
    return slug if slug.startswith("fjarr") else f"fjarr-{slug}".rstrip("-")


def _place(raw: Any) -> TklRemotePlace | None:
    if not isinstance(raw, dict) or raw.get("kind") == PlaceKind.HALT.value:
        return None
    try:
        return TklRemotePlace.model_validate(
            {"place": raw.get("id"), "code": raw.get("code"), "name": raw.get("name")}
        )
    except ValidationError:
        return None


def _area(raw: Any) -> TklRemoteArea | None:
    try:
        found = RemoteArea.model_validate(raw)
    except ValidationError:
        return None
    return TklRemoteArea(id=found.id, name=found.name, places=found.places)


def areas(http: httpx.Client, address: str) -> TklRemoteAreas:
    """The plan's remote areas and driftplatser at the hub, to choose from at Anslut (FR49).
    Read from the hub's own address; a hub with no meet running has none, and then the
    driftplatser are written by hand."""
    try:
        response = http.get(address.rstrip("/") + PACKAGE)
    except httpx.HTTPError:
        return TklRemoteAreas(message=NO_HUB)
    if response.status_code >= 400:
        return TklRemoteAreas(message=NO_MEET)
    try:
        found = response.json()
    except ValueError:
        return TklRemoteAreas(message=NO_MEET)
    if not isinstance(found, dict):
        return TklRemoteAreas(message=NO_MEET)
    places = [p for p in map(_place, found.get("places") or []) if p is not None]
    listed = [a for a in map(_area, found.get("remote_areas") or []) if a is not None]
    return TklRemoteAreas(areas=listed, places=places)


def connect_request(
    remote: TklRemote, given: TklRemoteConnect, software: str
) -> station.ConnectRequest:
    """Anslut som fjärrställverk (FR4): the client kind remote, with no station, and the remote
    area: the driftplatser written by hand, else the plan's area, as given now or at first
    start. Hubben suggests the area's driftplatser when only the area is named (FR49)."""
    places = list(dict.fromkeys(given.places)) if given.places else []
    area = given.area
    if not places and area is None:
        places, area = list(remote.places), remote.area
    return station.ConnectRequest(
        kind=station.ClientKind.REMOTE,
        name=remote.name,
        software=software,
        wants=places,
        remote_area=area,
        code=(given.code or "").strip() or None,
    )


def picture(hub: HubClient, made: Connection, home: str | None) -> TklFjarr:
    """Fjärrbildens data: Hubben's overview, and the client's offers and controls from one of
    its snapshots. Raises the hub client's errors; the caller keeps the last good picture."""
    overview = hub.overview()
    mine = [
        p.place.place
        for p in overview.places
        if p.controller is not None and p.controller.client_id == made.client_id
    ]
    look = home or next(iter(made.places), None) or next(iter(mine), None)
    seen = hub.snapshot(look) if look else None
    return TklFjarr(
        overview=overview,
        client_id=made.client_id,
        controls=list(seen.controls) if seen else mine,
        offers=list(seen.offers) if seen else [],
        heard=datetime.now(UTC),
    )
