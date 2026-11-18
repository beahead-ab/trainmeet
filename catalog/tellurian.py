"""Tellurian's format (#56, CAT-185, CAT-186): a vehicle as a file for Tellurian's card app, and
such files read back as drafts.

The card app saves one wagon as JSON with its C# property names: PascalCase and case-sensitive,
enums as numbers, and pictures as {Base64data, ContentType, FileName}. The interoperability
number keeps the app's own spelling, InteroperatbilityNumber. The export writes every property
the app sets, so that the file opens there; the import reads such a file into the values of a
draft (VehicleFields), which the owner reviews in a batch (catalog/batches.py) before it is a
vehicle.

The EVN is split as the app wants it (CAT-185): the interoperability code and the country number
as numbers, and the seven-digit serial number with the grouping it is painted with, since the
app adds the check digit itself. The import joins the parts again to the number as painted, with
the check digit. A painted check digit that is wrong is never corrected (CAT-59): such a number
goes to the app whole, as the vehicle number.

Catalog has only the core fields (C14). The export takes the type data the app shows, such as
the description, the top speed and the length, from the vehicle's prototype (CAT-160). The
import leaves the file's type data out, with a note, and so the owner's details and the
markings, which are not Catalog's. A value in a file that cannot be read fails that file only.

Ported from TrainCatalog's module for the format, with its tests.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from PIL import Image

from catalog import evn
from contracts.catalog import Vehicle, VehicleFields, VehicleKind, VehicleStatus

MAX_FILE_BYTES: Final = 20 * 1024 * 1024
"""One file: a model picture of at most 15 MB (CAT-123) as base64, and the rest."""
SCALES: Final = {0: "H0", 1: "N"}
"""The app's Scale: the two scales it prints cards for."""

NOT_TELLURIAN: Final = "Filen är inte ett vagnkort i Tellurians format."
NOT_JSON: Final = "Filen är inte giltig JSON."
TOO_LARGE: Final = "Filen är större än 20 MB."
ODD_VALUE: Final = "Filen har ett värde som inte kan läsas."
BAD_PICTURE: Final = "En bild i filen kunde inte läsas."
NO_PROTOTYPE_PICTURE: Final = "Förebildsbilden i filen kom inte med: Catalog tar bara modellbilden."
NO_LINKS: Final = "Bildlänkar hämtas inte. Lägg till bilderna själv."
NO_TYPE_DATA: Final = (
    "Typuppgifterna i filen, som beskrivning, hastighet och längd, kom inte med. Koppla fordonet "
    "till en förebild för dem."
)
NO_OWNER_DATA: Final = "Ägaruppgifterna och märkningen i filen kom inte med."
NO_PARTS: Final = (
    "Interoperabilitetskoden och landnumret kom inte med: löpnumret har inte sju siffror."
)

_TYPE_TEXTS: Final = (
    "Description",
    "LoadingInstructions",
    "Manufacturer",
    "UicMainClass",
    "WheelType",
    "WagonColor",
)
_TYPE_NUMBERS: Final = (
    "MaxSpeed",
    "Length",
    "LoadLimit",
    "LoadVolume",
    "LoadArea",
    "ModelWeight",
    "OperatingFromYear",
    "OperatingUptoYear",
    "YearOfManufacturing",
)
_TYPE_FLAGS: Final = (
    "IsEuropConformant",
    "IsInterfrigoConformant",
    "IsMcConformant",
    "IsOpwConformant",
    "IsRivConformant",
    "IsTenConformant",
    "IsFlatWagon",
)


class Unreadable(ValueError):
    """The file cannot be read as Tellurian's. The message is for the person, in Swedish."""


@dataclass(frozen=True)
class Read:
    """A file, read: the draft's values, the model picture as the file had it, and what was left
    out, in Swedish."""

    values: VehicleFields
    picture: bytes | None
    notes: list[str]


# --- The export (CAT-185) ---------------------------------------------------------------------


def painted_serial(number: str) -> str | None:
    """The seven digits of a painted EVN with their own grouping: '50 74 20-35 123-5' gives
    '20-35 123'. None when the number has no eleven or twelve digits."""
    positions = [i for i, ch in enumerate(number) if ch.isdigit()]
    if len(positions) not in (11, 12):
        return None
    return number[positions[4] : positions[10] + 1].strip(" -")


def split_number(number: str) -> tuple[int, int, str]:
    """The number as the app has it (CAT-185): the interoperability code, the country number, and
    the seven-digit serial number as painted. A number that is no EVN, or whose painted check
    digit is wrong (CAT-59), is the vehicle number as it is, with 0 and 0."""
    found = evn.describe(number)
    if found is None or not found.valid:
        return 0, 0, number
    return int(found.interop), int(found.country), painted_serial(number) or found.serial


def _number(value: object) -> Decimal | None:
    """A type value as a number: written with a point (catalog/prototype_fields.py)."""
    if not isinstance(value, str):
        return None
    try:
        found = Decimal(value)
    except InvalidOperation:
        return None
    return found if found.is_finite() and found > 0 else None


def _speed(data: Mapping[str, str]) -> tuple[int | None, int]:
    """The top speed and the app's SpeedUnit: 0 km/h, 1 mph."""
    for key, unit in (("max_speed", 0), ("max_speed_mph", 1)):
        found = _number(data.get(key))
        if found is not None:
            return round(found), unit
    return None, 0


def _length(data: Mapping[str, str]) -> float | None:
    """The length over buffers in metres, as the app has it."""
    millimetres = _number(data.get("length_over_buffers"))
    if millimetres is not None:
        return float(millimetres / 1000)
    feet = _number(data.get("length_ft"))
    return round(float(feet) * 0.3048, 2) if feet is not None else None


def _year(text: str) -> int | None:
    found = re.search(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)", text)
    return int(found[1]) if found else None


def _image(picture: bytes | None) -> dict[str, str] | None:
    if not picture:
        return None
    encoded = base64.b64encode(picture).decode("ascii")
    return {"Base64data": encoded, "ContentType": "image/jpeg", "FileName": "modell.jpg"}


def as_jpeg(picture: bytes) -> bytes:
    """A display picture as a JPEG, as the app shows pictures: a transparent one on white."""
    with Image.open(io.BytesIO(picture), formats=("JPEG", "PNG", "WEBP")) as image:
        image.load()
        if image.format == "JPEG":
            return picture
        rgba = image.convert("RGBA")
    flat = Image.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    out = io.BytesIO()
    flat.save(out, format="JPEG", quality=90)
    return out.getvalue()


def to_tellurian(vehicle: Vehicle, owner_name: str, picture: bytes | None) -> dict[str, Any]:
    """The vehicle as the app's Wagon, with every property the app sets. picture is the main
    picture as a JPEG. The owner's name is the only owner data: Catalog has no club, phone or
    e-mail, and the note is never in a file for others (CAT-191)."""
    interop, country, serial = split_number(vehicle.number)
    data: Mapping[str, str] = vehicle.prototype.fields if vehicle.prototype else {}
    speed, unit = _speed(data)
    load = _number(data.get("load"))
    return {
        "Scale": 1 if vehicle.scale.strip().upper() == "N" else 0,
        "OperatorSignature": vehicle.operator,
        "OperatorLogo": None,
        "VehicleClass": vehicle.litt,
        "InteroperatbilityNumber": interop,
        "CountryRegistrationNumber": country,
        "VehicleNumber": serial,
        "Epoch": vehicle.epoch,
        "UicMainClass": None,
        "OperatingFromYear": None,
        "OperatingUptoYear": None,
        "MaxSpeed": speed,
        "SpeedUnit": unit,
        "YearOfManufacturing": _year(data.get("built", "")),
        "Manufacturer": "",
        "Length": _length(data),
        "OriginalImage": None,
        "OriginalImageUrl": None,
        "ModelImage": _image(picture),
        "ModelImageUrl": None,
        "ModelManufacturer": vehicle.maker,
        "ModelNumber": vehicle.article_number,
        "WheelType": None,
        "Marking": {
            "UseMarking": True,
            "UseColorMarking": False,
            "Color1": "#FFFFFF",
            "Color2": "#FFFFFF",
            "Color3": "#FFFFFF",
            "Color4": "#FFFFFF",
            "InventoryNumber": "",
            "IconHref": None,
            "TextLabel": None,
            "Icon": None,
        },
        "PrintOptions": {
            "PrintCard": True,
            "PrintInventoryCard": True,
            "PrintFredSticker": True,
            "PrintExtraFredSticker": False,
            "DisplayQRCode": True,
        },
        "Owner": {"OwnerName": owner_name, "ClubName": "", "PhoneNumber": "", "EmailAddress": ""},
        "IsPassengerWagon": vehicle.kind is VehicleKind.PASSENGER_COACH,
        "Description": data.get("description", ""),
        "LoadLimit": float(load) if load is not None else 0.0,
        "LoadVolume": 0.0,
        "LoadArea": 0.0,
        "LoadingInstructions": None,
        **dict.fromkeys(_TYPE_FLAGS, False),
        "WagonColor": None,
        "ModelWeight": None,
        "HomeStation": {"Name": "", "Region": 0, "CountryCode": None},
    }


def file_name(vehicle: Vehicle) -> str:
    """The file's name: the litt and the number, made safe, with only letters, digits, dots,
    dashes and underscores. ČD's and ŽSR's letters stay (RFC 6266 lets the browser have them)."""
    safe = re.sub(r"[^\w.-]+", "_", f"{vehicle.litt} {vehicle.number}").strip("._-")
    return f"{safe[:100] or 'fordon'}.json"


# --- The import (CAT-186) ---------------------------------------------------------------------


def _text(wagon: Mapping[str, Any], key: str, limit: int) -> str:
    value = wagon.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise Unreadable(f"{ODD_VALUE[:-1]}: {key} ska vara text.")
    return value.strip()[:limit]


def _part(value: object) -> int | None:
    """The interoperability code or the country number: 1–99."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 < value < 100:
        return value
    return None


def join_number(interop: int | None, country: int | None, serial: str) -> tuple[str, bool]:
    """The number as painted, from the app's parts: '31 76 393 3 013-1' from 31, 76 and
    '393 3 013', with the check digit the app would add. A serial with its own check digit keeps
    it, right or wrong (CAT-59). The second value is false when the parts were left out because
    the serial is not seven digits."""
    serial = serial.strip(" -")
    digits = re.sub(r"\D", "", serial)
    if interop is None or country is None or len(digits) in (11, 12):
        return serial, True
    head = f"{interop:02d} {country:02d}"
    if len(digits) == 7:
        check = evn.check_digit(f"{interop:02d}{country:02d}{digits}")
        return f"{head} {serial}-{check}", True
    if len(digits) == 8:
        return f"{head} {serial}", True
    return serial, False


def _finite(value: object) -> bool:
    """A real, positive number: never a bool, and never infinity (1e999 is read as one)."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _filled(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _type_data(wagon: Mapping[str, Any]) -> bool:
    """Does the file have type data, which are the prototype's in Catalog (CAT-155)?"""
    station = wagon.get("HomeStation")
    return (
        any(_filled(wagon.get(key)) for key in _TYPE_TEXTS)
        or any(_finite(wagon.get(key)) for key in _TYPE_NUMBERS)
        or any(wagon.get(key) is True for key in _TYPE_FLAGS)
        or (isinstance(station, Mapping) and _filled(station.get("Name")))
    )


def _owner_data(wagon: Mapping[str, Any]) -> bool:
    """Does the file have the owner's details or a marking? The owner's name is the account's."""
    owner = wagon.get("Owner")
    marking = wagon.get("Marking")
    return (
        isinstance(owner, Mapping)
        and any(_filled(owner.get(key)) for key in ("ClubName", "PhoneNumber", "EmailAddress"))
    ) or (
        isinstance(marking, Mapping)
        and (
            marking.get("UseColorMarking") is True
            or any(_filled(marking.get(key)) for key in ("TextLabel", "InventoryNumber"))
            or bool(marking.get("Icon"))
        )
    )


def _picture(wagon: Mapping[str, Any]) -> bytes | None:
    image = wagon.get("ModelImage")
    if not isinstance(image, Mapping) or not image.get("Base64data"):
        return None
    encoded = image["Base64data"]
    if not isinstance(encoded, str):
        raise Unreadable(BAD_PICTURE)
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise Unreadable(BAD_PICTURE) from None


def from_tellurian(wagon: object) -> Read:
    """The draft's values from one of the app's files, and what was left out."""
    if not isinstance(wagon, Mapping) or not any(
        key in wagon for key in ("VehicleClass", "VehicleNumber", "OperatorSignature")
    ):
        raise Unreadable(NOT_TELLURIAN)
    notes: list[str] = []
    litt = _text(wagon, "VehicleClass", 80)
    number, joined = join_number(
        _part(wagon.get("InteroperatbilityNumber")),
        _part(wagon.get("CountryRegistrationNumber")),
        _text(wagon, "VehicleNumber", 80),
    )
    if not joined:
        notes.append(NO_PARTS)
    kind = (
        VehicleKind.PASSENGER_COACH
        if wagon.get("IsPassengerWagon") is True
        else VehicleKind.FREIGHT_WAGON
    )
    scale = wagon.get("Scale")
    values = VehicleFields(
        status=VehicleStatus.READY if litt or number else VehicleStatus.DRAFT,
        kind=kind,
        litt=litt,
        number=number[:80],
        operator=_text(wagon, "OperatorSignature", 80),
        epoch=_text(wagon, "Epoch", 12),
        scale=SCALES.get(scale, "")
        if isinstance(scale, int) and not isinstance(scale, bool)
        else "",
        maker=_text(wagon, "ModelManufacturer", 80),
        article_number=_text(wagon, "ModelNumber", 80),
    )
    picture = _picture(wagon)
    original = wagon.get("OriginalImage")
    if isinstance(original, Mapping) and original.get("Base64data"):
        notes.append(NO_PROTOTYPE_PICTURE)
    if _filled(wagon.get("ModelImageUrl")) or _filled(wagon.get("OriginalImageUrl")):
        notes.append(NO_LINKS)
    if _type_data(wagon):
        notes.append(NO_TYPE_DATA)
    if _owner_data(wagon):
        notes.append(NO_OWNER_DATA)
    return Read(values=values, picture=picture, notes=notes)


def _no_constant(name: str) -> object:
    raise ValueError(f"{name} is not a number")


def read(data: bytes) -> Read:
    """One file, as it was sent. Raises Unreadable, with the reason in Swedish, for a file that
    is not the app's or cannot be read; an odd value fails this file only."""
    if len(data) > MAX_FILE_BYTES:
        raise Unreadable(TOO_LARGE)
    try:
        wagon = json.loads(data.decode("utf-8-sig"), parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise Unreadable(NOT_JSON) from None
    try:
        return from_tellurian(wagon)
    except Unreadable:
        raise
    except Exception:  # an odd value fails this file only, never the files around it
        raise Unreadable(ODD_VALUE) from None
