"""Flytten från gamla TrainCatalog (#57, CAT-204–CAT-207): the vehicles, the pictures, the tags
and their link history, from the old TrainCatalog into Catalog.

    python -m catalog.flytten --gammal <old PostgreSQL URL> --bilder <old media folder> \\
        --ny <Catalog's PostgreSQL URL> [--provkorning]

The old database is read in one read-only transaction, so it is never changed and is read as
it stood at one moment. The vehicles, the pictures and the tags are written through Catalog's
own code, so its rules hold: Fleet.insert with the core fields, their source import (CAT-64)
and the EVN as painted (CAT-55); Pictures.add with prepare(), which checks the size and the
megapixels and strips the metadata (CAT-123, CAT-124), and the limits of 10 pictures per
vehicle and the free storage (CAT-17, CAT-131); and the tags' normalize() and slots (CAT-79,
CAT-82), with the database's own constraints. The tags' links and events keep their dates, so
they are written here rather than by Tags.link(), which stamps the time of the link.

Each old owner with a verified e-mail address gets a waiting fleet (catalog/waiting.py): an
owner of its own, with a keyed hash of the address and never the address. The person takes it
over at the first login with TrainMeet ID after the move. An old account without a verified
address cannot be matched to ID, so nothing of it is moved; the report counts it.

A vehicle keeps its id (CAT-52), so the old /fordon/<id> is the same page (catalog/old_paths.py).
The old values that are not core fields go into the vehicle's legacy, under the old field's
Swedish label as the old card showed it (CAT-205). A tag keeps its uid, so a tag that carries
/t/<uid> goes on working (CAT-206).

flytt_map holds what has been moved, written in the same transaction as the thing itself, so a
second run moves nothing twice and a later run adds only what is new: new owners, vehicles,
pictures, tags, links and events. A link that has ended in the old TrainCatalog since it was
moved ends here too. Changes to what was moved before are not carried over.

--provkorning writes nothing: it reads both databases and the picture files, prepares each
picture as the run would, and prints the same report. The log and the report hold counts,
never an e-mail address, a name or a picture. The pepper (CATALOG_FLYTT_PEPPER) and the
pictures' store (CATALOG_PICTURES_*) come from the environment, as for Catalog itself.

Not moved, as Catalog's definition says (C1–C3, CAT-25; trainmeet-spec,
docs/trainmeet-catalog.md §11): the prototype catalog, the values and the ads search, the
reference library, the invitations and shares, the print settings and logos, the subscriptions
(Gratis and Plus), the AI readings and the batches.
A vehicle's link to an old prototype keeps the inherited values and the prototype's name among
the old fields. The pictures come as the photos were taken, with the original background.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from pydantic import ValidationError

from catalog import migrate, waiting
from catalog.db import Database, UnknownOwner
from catalog.fleet import CORE_FIELDS, Fleet, Refused
from catalog.pictures import Pictures, StoreFailed, prepare, store_for
from catalog.settings import (
    DEFAULT_PICTURES_DIR,
    PEPPER_ENV,
    Settings,
    SettingsError,
    pepper_from_env,
    s3_from_env,
)
from catalog.tags import normalize, slot_of
from contracts.catalog import (
    FieldSource,
    ProblemCode,
    VehicleFields,
    VehicleKind,
    VehicleStatus,
)

LOGGER = logging.getLogger("catalog.flytten")
NOBODY: Final = UUID(int=0)
"""Who did an old tag event when that person's account is not moved: no one, as for a removed
account (CAT-193)."""

# --- The old field register (TrainCatalog's catalog/fields.py), for the labels ---------------

_OLD_FIELDS: Final[tuple[tuple[str, str, str, str], ...]] = (
    # key, the Swedish label the old card showed, kind, unit
    ("uic_type", "UIC-typ", "text", ""),
    ("epoch", "Epok", "text", ""),
    ("description", "Beskrivning", "text", ""),
    ("brake", "Broms", "text", ""),
    ("brake_marking", "Bromsmarkering", "boolean", ""),
    ("prototype_length", "L ö b", "number", "m"),
    ("wheelbase", "Axelavstånd", "number", "m"),
    ("prototype_weight", "Vn Vr", "number", "ton"),
    ("max_speed", "Sth", "number", "km/h"),
    ("load", "Lastar", "number", "ton"),
    ("load_length", "Lastlängd", "number", "m"),
    ("load_area", "Lastyta", "number", "m²"),
    ("volume", "Volym", "number", "m³"),
    ("riv", "RIV", "boolean", ""),
    ("country", "Land", "text", ""),
    ("built_years", "Byggnadsår / byggnadsperiod", "text", ""),
    ("prototype_axles", "Antal axlar (förebild)", "integer", ""),
    ("characteristics", "Modellens kännetecken", "text", ""),
    ("color_marks", "Märkning under vagnen", "text", ""),
    ("coupler", "Koppel-typ", "text", ""),
    ("nem_socket", "NEM-ficka", "boolean", ""),
    ("close_coupler", "KK-kuliss", "boolean", ""),
    ("spring_buffers", "Fjädrande buffertar", "boolean", ""),
    ("wheelset", "Hjulsats", "text", ""),
    ("back_to_back", "Innermått", "number", "mm"),
    ("flange_height", "Flänshöjd", "number", "mm"),
    ("wheel_profile", "Hjulprofil", "text", ""),
    ("roller_bearings", "Rullblock", "boolean", ""),
    ("rp25", "RP 25", "boolean", ""),
    ("model_length", "L ö b (modell)", "number", "mm"),
    ("model_weight", "Vikt (modell)", "number", "g"),
    ("axles", "Antal axlar", "integer", ""),
    ("paint", "Färg/lackering", "text", ""),
    ("dcc_address", "DCC-adress", "text", ""),
    ("notes", "Anteckningar", "text", ""),
    ("labels", "Egna etiketter", "text", ""),
    ("vkm", "VKM (fordonsinnehavare)", "text", ""),
    ("ten", "TEN", "boolean", ""),
    ("reporting_mark", "Reporting mark", "text", ""),
    ("aar_type", "AAR-typ", "text", ""),
    ("builder", "Builder (förebild)", "text", ""),
    ("builder_model", "Builder-modell", "text", ""),
    ("wheel_arrangement", "Hjulställning", "text", ""),
    ("length_ft", "Längd", "number", "ft"),
    ("capacity_lbs", "CAPY (lastförmåga)", "number", "lbs"),
    ("load_limit_lbs", "LD LMT (lastgräns)", "number", "lbs"),
    ("light_weight_lbs", "LT WT (tara)", "number", "lbs"),
    ("cubic_feet", "Volym", "number", "cu ft"),
    ("uic_interop_code", "Interoperabilitetskod (UIC)", "text", ""),
    ("uic_country_code", "Landnummer (UIC)", "text", ""),
    ("operating_period", "Driftperiod i detta utförande", "text", ""),
    ("loading_instructions", "Lastinstruktioner", "text", ""),
    ("mc", "MC", "boolean", ""),
    ("europ", "EUROP", "boolean", ""),
    ("opw", "OPW", "boolean", ""),
    ("interfrigo", "Interfrigo", "boolean", ""),
    ("wagon_color", "Vagnens färg", "color", ""),
    ("inventory_number", "Inventarienummer", "text", ""),
    ("home_station", "Hemstation", "text", ""),
    ("home_region", "Hemstationens regionfärg", "choice", ""),
    ("home_country", "Hemstationens land", "text", ""),
)
_OLD_BY_KEY: Final = {f[0]: f for f in _OLD_FIELDS}
_TYPE_KEYS: Final = frozenset(
    {f[0] for f in _OLD_FIELDS[:17]}
    | {"vkm", "ten", "reporting_mark", "aar_type", "builder", "builder_model"}
    | {"wheel_arrangement", "length_ft", "capacity_lbs", "load_limit_lbs", "light_weight_lbs"}
    | {"cubic_feet", "uic_interop_code", "uic_country_code", "operating_period"}
    | {"loading_instructions", "mc", "europ", "opw", "interfrigo", "wagon_color"}
    | {"operator", "litt"}
)
"""The old prototype's keys: its front-side fields, operator and litt (old prototypes.py)."""
_REGION_LABELS: Final[dict[str, dict[str, str]]] = {
    "SE": {"builder": "Tillverkare (förebild)"},
    "EU": {"builder": "Tillverkare (förebild)", "country": "Land (registrering)"},
    "US": {"built_years": "Byggnadsår (BLT)"},
}
"""The old profiles' own labels for fields that are not core fields (old fields.PROFILES)."""
_CHOICES: Final = {
    "home_region": {
        "yellow": "Gul",
        "red": "Röd",
        "green": "Grön",
        "blue": "Blå",
        "brown": "Brun",
        "black": "Svart",
        "orange": "Orange",
    }
}
_NAME_LABEL: Final = "Benämning"
_REGION_LABEL: Final = "Region"
_PROTOTYPE_LABEL: Final = "Förebild"
_SOURCE_LABEL: Final = "Källa"
_ENGINES: Final = {VehicleKind.LOCOMOTIVE, VehicleKind.MULTIPLE_UNIT}
_LIMITS: Final = {
    "litt": 80,
    "number": 80,
    "operator": 80,
    "epoch": 12,
    "scale": 12,
    "maker": 80,
    "article_number": 80,
    "note": 2000,
    "dcc_address": 8,
}
"""How long a core field may be (contracts/catalog.py, VehicleFields)."""
_CORE_LABELS: Final = {
    "litt": "Litt",
    "number": "Vagnsnummer",
    "operator": "Operatör",
    "epoch": "Epok",
    "scale": "Skala",
    "maker": "Tillverkare",
    "article_number": "Artikelnummer",
    "note": "Anteckningar",
    "dcc_address": "DCC-adress",
}
"""The old labels of the values that become core fields, for a value too long to be one."""

# --- Why something is not moved: the report's lines --------------------------------------------

NO_VERIFIED: Final = "konto utan verifierad e-postadress, som inte kan kopplas till TrainMeet ID"
OWNER_GONE: Final = "konto vars vagnpark har tagits bort i nya Catalog"
HASH_TAKEN: Final = "konto vars e-postadress redan har en väntande vagnpark"
VEHICLE_OWNER: Final = "fordon vars ägare inte flyttas"
VEHICLE_ID: Final = "fordon vars id redan finns i nya Catalog"
VEHICLE_BAD: Final = "fordon vars värden Catalog inte godtar"
PICTURE_VEHICLE: Final = "bild till ett fordon som inte flyttas"
PICTURE_MISSING: Final = "bild vars fil saknas i bildmappen"
PICTURE_OUTSIDE: Final = "bild vars fil ligger utanför bildmappen"
PICTURE_FULL: Final = "bild till ett fordon som redan har så många bilder som det får ha"
PICTURE_STORAGE: Final = "bild som inte får plats i ägarens fria lagring"
PICTURE_STORE: Final = "bild som bildlagringen inte tog emot"
PICTURE_LARGE: Final = "bild som är för stor: högst 15 MB och 40 megapixel"
PICTURE_BAD: Final = "bild som inte är en JPEG-, PNG- eller WebP-bild som går att läsa"
TAG_OWNER: Final = "tagg vars ägare inte flyttas"
TAG_NO_UID: Final = "tagg utan identifierare"
TAG_BAD_UID: Final = "tagg vars identifierare inte är en taggs adress"
TAG_TAKEN: Final = "tagg som redan är kopplad till någon annans fordon i nya Catalog"
TAG_EXISTS: Final = "tagg som redan finns i nya Catalog"
LINK_VEHICLE: Final = "koppling till ett fordon som inte flyttas"
LINK_CLASH: Final = "koppling som krockar med en aktiv koppling i nya Catalog"


# --- The old TrainCatalog, as read ------------------------------------------------------------


@dataclass(frozen=True)
class OldVehicle:
    id: UUID
    owner: UUID
    name: str
    category: str
    status: str
    wagon_number: str
    operator: str
    litt: str
    manufacturer: str
    article_number: str
    scale: str
    region: str
    prototype_fields: dict[str, Any]
    model_fields: dict[str, Any]
    labels: list[str]
    prototype_id: UUID | None
    prototype_snapshot: dict[str, Any]
    prototype_overrides: list[str]
    prototype_source_url: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class OldPicture:
    id: UUID
    vehicle: UUID
    display: str
    original: str
    is_main: bool


@dataclass(frozen=True)
class OldTag:
    id: UUID
    owner: UUID
    name: str
    kind: str
    identifiers: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class OldLink:
    id: UUID
    owner: UUID
    tag: UUID
    vehicle: UUID
    started_at: datetime
    ended_at: datetime | None


@dataclass(frozen=True)
class OldEvent:
    id: int
    tag: UUID
    vehicle: UUID | None
    by_user: UUID
    event: str
    at: datetime


@dataclass(frozen=True)
class Old:
    """What the old TrainCatalog has: every account with its verified e-mail address, if any,
    and the vehicles, pictures, tags, links and events, in the order they were made."""

    users: dict[UUID, str | None]
    vehicles: list[OldVehicle]
    pictures: list[OldPicture]
    tags: list[OldTag]
    links: list[OldLink]
    events: list[OldEvent]


def read_old(url: str) -> Old:
    """Read the old TrainCatalog's tables (its migrations 0001–0021) in one read-only
    transaction. The e-mail address is read only where allauth has it verified."""
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.read_only = True
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with conn.transaction():
            users = {
                row["id"]: row["verified"]
                for row in conn.execute(
                    "SELECT u.id, (SELECT e.email FROM account_emailaddress e "
                    "WHERE e.user_id = u.id AND lower(e.email) = lower(u.email) AND e.verified "
                    "LIMIT 1) AS verified FROM catalog_user u"
                ).fetchall()
            }
            vehicles = [
                OldVehicle(**row)
                for row in conn.execute(
                    "SELECT id, owner_id AS owner, name, category, status, wagon_number, "
                    "operator, litt, manufacturer, article_number, scale, region, "
                    "prototype_fields, model_fields, labels, prototype_id, prototype_snapshot, "
                    "prototype_overrides, prototype_source_url, created_at, updated_at "
                    "FROM catalog_vehicle ORDER BY created_at, id"
                ).fetchall()
            ]
            pictures = [
                OldPicture(**row)
                for row in conn.execute(
                    "SELECT id, vehicle_id AS vehicle, display, original, is_main "
                    "FROM catalog_vehicleimage ORDER BY vehicle_id, position, created_at, id"
                ).fetchall()
            ]
            identifiers: dict[UUID, list[tuple[str, str]]] = {}
            for row in conn.execute(
                "SELECT tag_id, namespace, value FROM catalog_tagidentifier ORDER BY id"
            ).fetchall():
                identifiers.setdefault(row["tag_id"], []).append((row["namespace"], row["value"]))
            tags = [
                OldTag(**row, identifiers=tuple(identifiers.get(row["id"], [])))
                for row in conn.execute(
                    "SELECT id, owner_id AS owner, name, kind FROM catalog_tag "
                    "ORDER BY created_at, id"
                ).fetchall()
            ]
            links = [
                OldLink(**row)
                for row in conn.execute(
                    "SELECT id, owner_id AS owner, tag_id AS tag, vehicle_id AS vehicle, "
                    "started_at, ended_at FROM catalog_tagassignment ORDER BY started_at, id"
                ).fetchall()
            ]
            events = [
                OldEvent(**row)
                for row in conn.execute(
                    "SELECT id, tag_id AS tag, vehicle_id AS vehicle, by_user_id AS by_user, "
                    "event, at FROM catalog_tagevent ORDER BY at, id"
                ).fetchall()
            ]
    return Old(users, vehicles, pictures, tags, links, events)


# --- An old vehicle as Catalog's -----------------------------------------------------------------


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _shown(key: str, value: Any) -> str:
    """An old value as the old card showed it: Ja or Nej, a number with a decimal comma and its
    unit, a choice by its name."""
    _, _, kind, unit = _OLD_BY_KEY.get(key, (key, key, "text", ""))
    if isinstance(value, bool):
        return "Ja" if value else "Nej"
    if isinstance(value, list):
        return ", ".join(_text(v) for v in value if _text(v))
    text = _text(value)
    if kind in ("number", "integer"):
        text = text.replace(".", ",")
        return f"{text} {unit}" if unit else text
    if kind == "choice":
        return _CHOICES.get(key, {}).get(text, text)
    return text


def _label(region: str, key: str) -> str:
    own = _REGION_LABELS.get(region, _REGION_LABELS["SE"]).get(key)
    return own or _OLD_BY_KEY.get(key, (key, key))[1]


def _resolved(old: OldVehicle) -> tuple[str, str, dict[str, Any]]:
    """The litt, the operator and the fields as the old card showed them: the prototype's
    snapshot where the owner kept the inherited value (TrainCatalog's prototypes.values)."""
    litt, operator = old.litt, old.operator
    fields: dict[str, Any] = {**old.prototype_fields, **old.model_fields}
    if old.labels:
        fields["labels"] = list(old.labels)
    if old.prototype_id is not None:
        for key in _TYPE_KEYS - set(old.prototype_overrides):
            value = old.prototype_snapshot.get(key)
            if key == "litt":
                litt = _text(value)
            elif key == "operator":
                operator = _text(value)
            elif value is not None:
                fields[key] = value
            else:
                fields.pop(key, None)
    return litt, operator, fields


@dataclass(frozen=True)
class Carried:
    """An old vehicle as Catalog's: the core fields and the old fields."""

    fields: VehicleFields
    legacy: dict[str, str]
    became_draft: bool
    """Ready in the old TrainCatalog, a draft here: ready needs a kind and a litt or number."""
    too_long: int
    """Values too long for their core field, kept among the old fields instead."""


def carry(old: OldVehicle) -> Carried:
    """The core fields from the old vehicle, and every other value with its old label
    (CAT-205)."""
    litt, operator, fields = _resolved(old)
    try:
        kind = VehicleKind(old.category)
    except ValueError:
        kind = VehicleKind.OTHER
    core: dict[str, str] = {}
    legacy: dict[str, str] = {}
    too_long = 0

    def keep(label: str, value: str) -> None:
        if not value:
            return
        name, n = label, 2
        while name in legacy and legacy[name] != value:
            name, n = f"{label} ({n})", n + 1
        legacy[name] = value

    wanted = {
        "litt": litt,
        "number": old.wagon_number,
        "operator": operator,
        "epoch": _text(fields.pop("epoch", "")),
        "scale": old.scale,
        "maker": old.manufacturer,
        "article_number": old.article_number,
        "note": _text(fields.pop("notes", "")),
        "dcc_address": _text(fields.pop("dcc_address", "")) if kind in _ENGINES else "",
    }
    for name, value in wanted.items():
        value = value if name == "note" else _text(value)
        if len(value) <= _LIMITS[name]:
            core[name] = value
        else:
            too_long += 1
            keep(_CORE_LABELS[name], value)
    keep(_NAME_LABEL, _text(old.name))
    for key in [f[0] for f in _OLD_FIELDS] + sorted(set(fields) - set(_OLD_BY_KEY)):
        if key in fields:
            keep(_label(old.region, key), _shown(key, fields[key]))
    if old.prototype_id is not None:
        keep(_PROTOTYPE_LABEL, _text(old.prototype_snapshot.get("name")))
    keep(_SOURCE_LABEL, _text(old.prototype_source_url))
    keep(_REGION_LABEL, _text(old.region))
    ready = old.status == "ready" and bool(core["litt"] or core["number"])
    status = VehicleStatus.READY if ready else VehicleStatus.DRAFT
    values = VehicleFields.model_validate({"status": status, "kind": kind, **core})
    return Carried(values, legacy, old.status == "ready" and not ready, too_long)


# --- The report ----------------------------------------------------------------------------------


@dataclass
class Tally:
    new: int = 0
    before: int = 0


@dataclass
class Report:
    """What the run moved, or would move, and what it did not, and why. Counts only."""

    dry: bool
    accounts: int = 0
    owners: int = 0
    waiting: int = 0
    """Old owners whose fleet waits: not logged in to Catalog with TrainMeet ID yet."""
    claimed: int = 0
    owners_new: int = 0
    vehicles: Tally = field(default_factory=Tally)
    pictures: Tally = field(default_factory=Tally)
    tags: Tally = field(default_factory=Tally)
    links: Tally = field(default_factory=Tally)
    events: Tally = field(default_factory=Tally)
    links_ended: int = 0
    originals_left: int = 0
    drafts: int = 0
    too_long: int = 0
    skipped: Counter[str] = field(default_factory=Counter)

    def text(self) -> str:
        def tally(name: str, found: Tally) -> str:
            return f"{name}: {found.new} nya, {found.before} flyttade förut."

        lines = [
            "Flytten från gamla TrainCatalog: provkörning, inget har skrivits."
            if self.dry
            else "Flytten från gamla TrainCatalog är körd.",
            f"Konton i gamla TrainCatalog: {self.accounts}, varav {self.owners} "
            "med fordon eller taggar.",
            f"Ägare: {self.owners_new} nya väntande vagnparker. {self.claimed} ägare har redan "
            "tagit över sin vagnpark.",
            f"Inte i TrainMeet ID än: {self.waiting} ägare har inte loggat in i Catalog med ID. "
            "Deras vagnparker väntar och blir deras när de loggar in med samma verifierade "
            "e-postadress.",
            tally("Fordon", self.vehicles),
            tally("Bilder", self.pictures),
            tally("Taggar", self.tags),
            tally("Kopplingar", self.links),
            tally("Tagghändelser", self.events),
        ]
        if self.links_ended:
            lines.append(f"Kopplingar som har avslutats i gamla TrainCatalog: {self.links_ended}.")
        if self.originals_left:
            lines.append(
                f"Original: {self.originals_left} bilder kommer utan sitt sparade original, som "
                "saknades, var för stort eller inte fick plats; visningsbilden kommer med."
            )
        if self.drafts:
            lines.append(
                f"Utkast: {self.drafts} fordon som var sparade blir utkast, eftersom ett klart "
                "fordon behöver littera eller nummer."
            )
        if self.too_long:
            lines.append(
                f"För långa värden: {self.too_long} värden får inte plats i kärnfälten och "
                "sparas bland de gamla fälten."
            )
        if self.skipped:
            lines.append("Flyttas inte:")
            lines += [f"- {n} {why}" for why, n in sorted(self.skipped.items())]
        else:
            lines.append("Inget hoppas över.")
        return "\n".join(lines)


# --- The move ------------------------------------------------------------------------------------


class _OwnerMoved(Exception):
    """An owner's row went while the move worked: the person took the fleet over. The mapping
    is read again and the work tried again."""


class Move:
    """One run of the move. dry writes nothing."""

    def __init__(
        self,
        old: Old,
        media: Path,
        db: Database,
        pictures: Pictures,
        pepper: bytes,
        *,
        dry: bool,
    ) -> None:
        self.old = old
        self.media = media.resolve()
        self.db = db
        self.pictures = pictures
        self.pepper = pepper
        self.dry = dry
        self.report = Report(dry=dry)
        self.owner_of = {vehicle.id: vehicle.owner for vehicle in old.vehicles}
        self.owners: dict[UUID, UUID] = {}
        """Old account -> Catalog's owner: a waiting owner, a person, or one made up in a dry
        run."""
        self.vehicles: dict[UUID, UUID] = {}
        self.moved_now: set[UUID] = set()
        """The old vehicles this run moves, whose main picture it sets."""
        self._planned: Counter[UUID] = Counter()
        """A dry run's pictures per vehicle and storage per owner, as they would grow."""

    # --- Reading what is moved already --------------------------------------------------------

    def _map(self, conn: Connection[DictRow], kind: str) -> dict[str, str]:
        rows = conn.execute(
            "SELECT old_id, new_id FROM flytt_map WHERE kind = %s", (kind,)
        ).fetchall()
        return {str(row["old_id"]): str(row["new_id"]) for row in rows}

    def _note(self, conn: Connection[DictRow], kind: str, old: object, new: object) -> None:
        conn.execute(
            "INSERT INTO flytt_map (kind, old_id, new_id) VALUES (%s, %s, %s)",
            (kind, str(old), str(new)),
        )

    def run(self) -> Report:
        self.report.accounts = len(self.old.users)
        self._move_owners()
        self._move_vehicles()
        self._move_pictures()
        self._move_tags()
        LOGGER.info(
            "Flytten%s: %d fordon, %d bilder, %d taggar nya.",
            " (provkörning)" if self.dry else "",
            self.report.vehicles.new,
            self.report.pictures.new,
            self.report.tags.new,
        )
        return self.report

    # --- The owners -----------------------------------------------------------------------------

    def _move_owners(self) -> None:
        having = {v.owner for v in self.old.vehicles} | {t.owner for t in self.old.tags}
        self.report.owners = len(having)
        with self.db.transaction() as conn:
            mapped = self._map(conn, "owner")
            known = {
                str(row["id"]): row["waits"]
                for row in conn.execute(
                    "SELECT o.id, w.owner_id IS NOT NULL AS waits FROM owner o "
                    "LEFT JOIN waiting_fleet w ON w.owner_id = o.id WHERE o.id::text = ANY(%s)",
                    (list(mapped.values()),),
                ).fetchall()
            }
        for user in sorted(having):
            email = self.old.users.get(user)
            if str(user) in mapped:
                new = mapped[str(user)]
                if new not in known:
                    self.report.skipped[OWNER_GONE] += 1
                    continue
                self.owners[user] = UUID(new)
                if known[new]:
                    self.report.waiting += 1
                else:
                    self.report.claimed += 1
                continue
            if email is None:
                self.report.skipped[NO_VERIFIED] += 1
                continue
            made = self._new_owner(user, waiting.email_hash(self.pepper, email))
            if made is None:
                self.report.skipped[HASH_TAKEN] += 1
                continue
            self.owners[user] = made
            self.report.owners_new += 1
            self.report.waiting += 1

    def _new_owner(self, user: UUID, hashed: bytes) -> UUID | None:
        """A waiting owner with the hash, in one transaction with its flytt_map row."""
        owner = uuid.uuid4()
        with self.db.transaction() as conn:
            taken = conn.execute(
                "SELECT 1 FROM waiting_fleet WHERE email_hash = %s", (hashed,)
            ).fetchone()
            if taken is not None:
                return None
            if self.dry:
                return owner
            conn.execute(
                "INSERT INTO owner (id, name) VALUES (%s, %s)", (owner, waiting.WAITING_NAME)
            )
            conn.execute(
                "INSERT INTO waiting_fleet (owner_id, email_hash) VALUES (%s, %s)",
                (owner, hashed),
            )
            self._note(conn, "owner", user, owner)
        return owner

    def _refresh_owner(self, user: UUID) -> None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT new_id FROM flytt_map WHERE kind = 'owner' AND old_id = %s", (str(user),)
            ).fetchone()
        if row is not None:
            self.owners[user] = UUID(str(row["new_id"]))

    def _for_owners[T](self, users: Iterable[UUID], work: Callable[[Connection[DictRow]], T]) -> T:
        """work in one transaction after the owners' rows are locked, in the order of their ids
        (CAT-40). A fleet taken over meanwhile has a new owner: the mapping is read again and
        the work tried again."""
        wanted = sorted(set(users))
        for attempt in (1, 2, 3):
            owners = sorted({self.owners[user] for user in wanted})
            try:
                with self.db.transaction() as conn:
                    locked = conn.execute(
                        "SELECT id FROM owner WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
                        (owners,),
                    ).fetchall()
                    if len(locked) != len(owners):
                        raise _OwnerMoved()
                    return work(conn)
            except (_OwnerMoved, UnknownOwner):
                if attempt == 3:
                    raise
                for user in wanted:
                    self._refresh_owner(user)
        raise AssertionError("not reached")

    # --- The vehicles ---------------------------------------------------------------------------

    def _move_vehicles(self) -> None:
        with self.db.transaction() as conn:
            mapped = self._map(conn, "vehicle")
        for old in self.old.vehicles:
            if str(old.id) in mapped:
                self.vehicles[old.id] = UUID(mapped[str(old.id)])
                self.report.vehicles.before += 1
                continue
            if old.owner not in self.owners:
                self.report.skipped[VEHICLE_OWNER] += 1
                continue
            try:
                carried = carry(old)
            except ValidationError:
                self.report.skipped[VEHICLE_BAD] += 1
                continue
            if self.dry:
                with self.db.transaction() as conn:
                    there = conn.execute(
                        "SELECT 1 FROM vehicle WHERE id = %s", (old.id,)
                    ).fetchone()
                moved = there is None
            else:
                try:
                    moved = self._for_owners(
                        [old.owner], partial(self._insert, old=old, carried=carried)
                    )
                except Refused:
                    self.report.skipped[VEHICLE_BAD] += 1
                    continue
            if not moved:
                self.report.skipped[VEHICLE_ID] += 1
                continue
            self.vehicles[old.id] = old.id
            self.moved_now.add(old.id)
            self.report.vehicles.new += 1
            self.report.drafts += carried.became_draft
            self.report.too_long += carried.too_long

    def _insert(self, conn: Connection[DictRow], *, old: OldVehicle, carried: Carried) -> bool:
        """The vehicle with its own id, its core fields from the import (CAT-64) and its old
        fields, dated as it was made in the old TrainCatalog."""
        if conn.execute("SELECT 1 FROM vehicle WHERE id = %s", (old.id,)).fetchone() is not None:
            return False
        owner = self.owners[old.owner]
        sources = dict.fromkeys(CORE_FIELDS, FieldSource.IMPORT)
        Fleet.insert(conn, owner, carried.fields, sources, vehicle=old.id, legacy=carried.legacy)
        conn.execute(
            "UPDATE vehicle SET created_at = %s, updated_at = %s WHERE id = %s",
            (old.created_at, old.updated_at, old.id),
        )
        conn.execute(
            "UPDATE vehicle_owner SET since = %s WHERE vehicle_id = %s", (old.created_at, old.id)
        )
        conn.execute(
            "UPDATE vehicle_event SET at = %s WHERE vehicle_id = %s", (old.created_at, old.id)
        )
        self._note(conn, "vehicle", old.id, old.id)
        return True

    # --- The pictures ---------------------------------------------------------------------------

    def _files(self, old: OldPicture) -> list[tuple[Path, bool]] | str:
        """The old picture's files to try, best first: the original kept with Spara original,
        then the display picture. Or why there is none: a file outside the media folder, or
        none there."""
        found: list[tuple[Path, bool]] = []
        outside = False
        for name, original in ((old.original, True), (old.display, False)):
            if not name:
                continue
            path = (self.media / name).resolve()
            if not path.is_relative_to(self.media):
                outside = True
            elif path.is_file():
                found.append((path, original))
        if found:
            return found
        return PICTURE_OUTSIDE if outside else PICTURE_MISSING

    def _move_pictures(self) -> None:
        with self.db.transaction() as conn:
            mapped = self._map(conn, "picture")
        mains: dict[UUID, UUID] = {}
        for old in self.old.pictures:
            if str(old.id) in mapped:
                self.report.pictures.before += 1
                continue
            if old.vehicle not in self.vehicles:
                self.report.skipped[PICTURE_VEHICLE] += 1
                continue
            files = self._files(old)
            if isinstance(files, str):
                self.report.skipped[files] += 1
                continue
            vehicle = self.vehicles[old.vehicle]
            user = self.owner_of[old.vehicle]
            made: UUID | None = None
            why = PICTURE_MISSING
            for path, original in files:
                try:
                    made = self._picture(user, vehicle, path.read_bytes(), original, old.id)
                except Refused as refused:
                    why = self._why(refused)
                    if refused.code is ProblemCode.TOO_MANY_PICTURES:
                        break
                    continue  # without the original, the display picture may do
                except StoreFailed:
                    why = PICTURE_STORE
                    break
                self.report.originals_left += old.original != "" and not original
                break
            if made is None:
                self.report.skipped[why] += 1
                continue
            self.report.pictures.new += 1
            if old.is_main:
                mains[old.vehicle] = made
        if self.dry:
            return
        for old_vehicle, picture in mains.items():
            if old_vehicle not in self.moved_now:
                continue  # the owner may have chosen another main picture since
            try:
                self.pictures.set_main(
                    self.owners[self.owner_of[old_vehicle]], self.vehicles[old_vehicle], picture
                )
            except UnknownOwner:
                continue  # taken over meanwhile: the first picture stays the main one

    @staticmethod
    def _why(refused: Refused) -> str:
        if refused.code is ProblemCode.TOO_MANY_PICTURES:
            return PICTURE_FULL
        if refused.code in (ProblemCode.STORAGE_FULL, ProblemCode.NO_TOKENS):
            return PICTURE_STORAGE
        if refused.code is ProblemCode.PICTURE_TOO_LARGE:
            return PICTURE_LARGE
        if refused.code is ProblemCode.UNAVAILABLE:
            return PICTURE_STORE
        return PICTURE_BAD

    def _picture(
        self, user: UUID, vehicle: UUID, data: bytes, keep_original: bool, old: UUID
    ) -> UUID:
        """The picture through Catalog's upload, the old picture noted in its transaction. A
        fleet taken over meanwhile has a new owner, and the upload is tried again with it. A
        dry run prepares the picture, and counts the vehicle's pictures and the owner's storage
        as the upload would."""
        if not self.dry:
            try:
                return self._upload(user, vehicle, data, keep_original, old)
            except UnknownOwner:
                self._refresh_owner(user)
                return self._upload(user, vehicle, data, keep_original, old)
        owner = self.owners[user]
        prepared = prepare(data, keep_original)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT (SELECT count(*) FROM picture WHERE vehicle_id = %s) AS here, "
                "(SELECT coalesce(sum(bytes), 0) FROM picture WHERE owner_id = %s) AS used",
                (vehicle, owner),
            ).fetchone()
        assert row is not None
        limits = self.pictures.limits
        if int(row["here"]) + self._planned[vehicle] >= limits.per_vehicle:
            raise Refused(422, ProblemCode.TOO_MANY_PICTURES, PICTURE_FULL)
        if int(row["used"]) + self._planned[owner] + prepared.size > limits.person:
            raise Refused(422, ProblemCode.STORAGE_FULL, PICTURE_STORAGE)
        self._planned[vehicle] += 1
        self._planned[owner] += prepared.size
        return uuid.uuid4()

    def _upload(
        self, user: UUID, vehicle: UUID, data: bytes, keep_original: bool, old: UUID
    ) -> UUID:
        owner = self.owners[user]
        made = self.pictures.add(
            owner,
            vehicle,
            data,
            keep_original=keep_original,
            uploaded_by=owner,
            club=False,
            within=lambda conn, picture: self._note(conn, "picture", old, picture),
        )
        return made.id

    # --- The tags, their links and their events -------------------------------------------------

    def _move_tags(self) -> None:
        with self.db.transaction() as conn:
            mapped = {kind: self._map(conn, kind) for kind in ("tag", "assignment", "event")}
        links: dict[UUID, list[OldLink]] = {}
        for link in self.old.links:
            links.setdefault(link.tag, []).append(link)
        events: dict[UUID, list[OldEvent]] = {}
        for event in self.old.events:
            events.setdefault(event.tag, []).append(event)
        for tag in self.old.tags:
            if str(tag.id) in mapped["tag"]:
                self.report.tags.before += 1
                existing: UUID | None = UUID(mapped["tag"][str(tag.id)])
            elif tag.owner not in self.owners:
                self.report.skipped[TAG_OWNER] += 1
                continue
            else:
                existing = None
            uids = self._uids(tag)
            if uids is None:
                continue
            users = {tag.owner} | {link.owner for link in links.get(tag.id, [])}
            users = {user for user in users if user in self.owners}
            work = partial(
                self._tag,
                tag=tag,
                existing=existing,
                uids=uids,
                links=links.get(tag.id, []),
                events=events.get(tag.id, []),
                mapped=mapped,
            )
            if self.dry:
                with self.db.transaction() as conn:
                    work(conn)
            else:
                self._for_owners(users, work)

    def _uids(self, tag: OldTag) -> list[tuple[str, str]] | None:
        """The tag's identifiers as Catalog keeps them (CAT-79): the same uid, so /t/<uid> on
        the tag goes on working (CAT-206)."""
        if not tag.identifiers:
            self.report.skipped[TAG_NO_UID] += 1
            return None
        found: list[tuple[str, str]] = []
        for namespace, value in tag.identifiers:
            try:
                uid = normalize(value)
            except Refused:
                uid = None
            if uid is None or uid.namespace != namespace:
                self.report.skipped[TAG_BAD_UID] += 1
                return None
            found.append((uid.namespace, uid.value))
        return found

    def _tag(
        self,
        conn: Connection[DictRow],
        *,
        tag: OldTag,
        existing: UUID | None,
        uids: list[tuple[str, str]],
        links: list[OldLink],
        events: list[OldEvent],
        mapped: Mapping[str, Mapping[str, str]],
    ) -> None:
        """One tag in one transaction: the tag and its identifiers, unless it is moved already,
        then its links and events that are new."""
        kind = "sim" if uids[0][0] == "sim" else "nfc"
        if existing is None:
            clash = conn.execute(
                "SELECT i.tag_id, a.owner_id FROM tag_identifier i LEFT JOIN tag_assignment a "
                "ON a.tag_id = i.tag_id AND a.ended_at IS NULL "
                "WHERE (i.namespace, i.value) IN (SELECT * FROM unnest(%s::text[], %s::text[]))",
                ([n for n, _ in uids], [v for _, v in uids]),
            ).fetchone()
            if clash is not None:
                taken = (
                    clash["owner_id"] is not None and clash["owner_id"] != self.owners[tag.owner]
                )
                self.report.skipped[TAG_TAKEN if taken else TAG_EXISTS] += 1
                return
            existing = uuid.uuid4()
            self.report.tags.new += 1
            if not self.dry:
                name = tag.name.strip()[:80] or f"NFC {uids[0][1][-6:].upper()}"
                conn.execute(
                    "INSERT INTO tag (id, owner_id, name, kind) VALUES (%s, %s, %s, %s)",
                    (existing, self.owners[tag.owner], name, kind),
                )
                for namespace, value in uids:
                    conn.execute(
                        "INSERT INTO tag_identifier (namespace, value, tag_id) VALUES (%s, %s, %s)",
                        (namespace, value, existing),
                    )
                self._note(conn, "tag", tag.id, existing)
        for link in links:
            self._link(conn, existing, kind, link, mapped["assignment"])
        for event in events:
            if str(event.id) in mapped["event"]:
                self.report.events.before += 1
                continue
            self.report.events.new += 1
            if self.dry:
                continue
            vehicle = self.vehicles.get(event.vehicle) if event.vehicle is not None else None
            row = conn.execute(
                "INSERT INTO tag_event (tag_id, vehicle_id, by_owner, event, at) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (existing, vehicle, self.owners.get(event.by_user, NOBODY), event.event, event.at),
            ).fetchone()
            assert row is not None
            self._note(conn, "event", event.id, row["id"])

    def _link(
        self,
        conn: Connection[DictRow],
        tag: UUID,
        kind: str,
        link: OldLink,
        mapped: Mapping[str, str],
    ) -> None:
        """A link with its dates. One moved before that has ended since ends here too."""
        if str(link.id) in mapped:
            self.report.links.before += 1
            if link.ended_at is not None and not self.dry:
                ended = conn.execute(
                    "UPDATE tag_assignment SET ended_at = %s WHERE id = %s AND ended_at IS NULL",
                    (link.ended_at, UUID(mapped[str(link.id)])),
                )
                self.report.links_ended += ended.rowcount
            return
        if link.vehicle not in self.vehicles or link.owner not in self.owners:
            self.report.skipped[LINK_VEHICLE] += 1
            return
        vehicle, slot = self.vehicles[link.vehicle], slot_of(kind)
        if link.ended_at is None:
            busy = conn.execute(
                "SELECT 1 FROM tag_assignment WHERE ended_at IS NULL "
                "AND (tag_id = %s OR (vehicle_id = %s AND slot = %s))",
                (tag, vehicle, slot),
            ).fetchone()
            if busy is not None:
                self.report.skipped[LINK_CLASH] += 1
                return
        self.report.links.new += 1
        if self.dry:
            return
        made = uuid.uuid4()
        conn.execute(
            "INSERT INTO tag_assignment (id, owner_id, tag_id, vehicle_id, slot, started_at, "
            "ended_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (made, self.owners[link.owner], tag, vehicle, slot, link.started_at, link.ended_at),
        )
        self._note(conn, "assignment", link.id, made)


# --- The command ---------------------------------------------------------------------------------


def _store_settings(env: Mapping[str, str], database_url: str) -> Settings:
    """The pictures' store as Catalog has it: Object Storage, or the disk (catalog/settings.py)."""
    folder = env.get("CATALOG_PICTURES_DIR", "").strip()
    return Settings(
        database_url=database_url,
        pictures_dir=Path(folder) if folder else DEFAULT_PICTURES_DIR,
        pictures_s3=s3_from_env(env),
    )


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    source = os.environ if env is None else env
    parser = argparse.ArgumentParser(
        prog="python -m catalog.flytten",
        description="Flyttar fordon, bilder, taggar och kopplingshistorik från gamla "
        "TrainCatalog till Catalog (CAT-204).",
    )
    parser.add_argument(
        "--gammal", required=True, help="Gamla TrainCatalogs PostgreSQL. Läses, ändras aldrig."
    )
    parser.add_argument(
        "--bilder", required=True, type=Path, help="Gamla TrainCatalogs bildmapp (MEDIA_ROOT)."
    )
    parser.add_argument(
        "--ny", default=None, help="Catalogs PostgreSQL. Förval: CATALOG_DATABASE_URL."
    )
    parser.add_argument(
        "--provkorning", action="store_true", help="Skriv ingenting, visa bara vad som flyttas."
    )
    args = parser.parse_args(argv)
    new_url = (args.ny or source.get("CATALOG_DATABASE_URL", "")).strip()
    if not new_url:
        print("Ange --ny eller CATALOG_DATABASE_URL.", file=sys.stderr)
        return 2
    if not args.bilder.is_dir():
        print("--bilder är ingen mapp.", file=sys.stderr)
        return 2
    try:
        pepper = pepper_from_env(source)
        settings = _store_settings(source, new_url)
    except SettingsError as error:
        print(str(error), file=sys.stderr)
        return 2
    if pepper is None:
        print(f"{PEPPER_ENV} saknas: samma hemlighet som Catalog har.", file=sys.stderr)
        return 2
    try:
        missing = migrate.check(new_url)
        if missing:
            names = ", ".join(f"{m.version:04d}_{m.name}" for m in missing)
            print(f"Catalogs databas saknar migrationer: {names}.", file=sys.stderr)
            return 1
        old = read_old(args.gammal)
        db = Database(new_url, max_size=2)
        db.open()
        try:
            report = Move(
                old,
                args.bilder,
                db,
                Pictures(db, store_for(settings)),
                pepper,
                dry=args.provkorning,
            ).run()
        finally:
            db.close()
    except migrate.MigrationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except psycopg.Error as error:
        # The type only: a database's message can hold its address or the data.
        print(f"Flytten stannade: {type(error).__name__}. Kör den igen.", file=sys.stderr)
        return 1
    print(report.text())
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
