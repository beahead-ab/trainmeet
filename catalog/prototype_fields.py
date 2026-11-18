"""The field register for the prototypes' type data, and the field profiles (CAT-156–CAT-158).

The register is the code here, published as FieldRegister (contracts/catalog.py). A key always
means the same thing with the same unit, so a value means the same in every profile and every
revision: a key is never reused with another meaning, and a field that is no longer wanted is
retired, never given to something else (RETIRED). US units therefore have keys of their own.
Ported from TrainCatalog's catalog/fields.py, with only the type data (CAT-155, CAT-157): the
model's data and the vehicle's own data are not here.

The profiles say which keys a prototype shows, in which order and under which label: Sweden,
Europe and the USA from the start (CAT-158, C31).

The values are text, as written: a number keeps no more and no less than was given. clean()
checks a revision's or a vehicle's values against the register and the profile.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Final

from contracts.catalog import (
    FieldKind,
    FieldProfile,
    FieldRegister,
    ProfileField,
    ProfileFields,
    TypeField,
)

LARGEST: Final = Decimal(1_000_000)
"""No type value is larger: a guard against a slip of the keyboard, not a physical limit."""


@dataclass(frozen=True)
class Field:
    """One key: what it holds and in which unit, never changed once published (CAT-156)."""

    key: str
    kind: FieldKind
    unit: str
    label: str
    label_en: str
    max_length: int = 20


TEXT, NUMBER, INTEGER = FieldKind.TEXT, FieldKind.NUMBER, FieldKind.INTEGER

REGISTER: Final[tuple[Field, ...]] = (
    # The twelve type data (CAT-157). Metric, as on European and Swedish rolling stock.
    Field("litt", TEXT, "", "Littera", "Class", 40),
    Field("operator", TEXT, "", "Bolag", "Operator", 80),
    Field("epoch", TEXT, "", "Epok", "Epoch", 12),
    Field("description", TEXT, "", "Beskrivning", "Description", 1000),
    Field("length_over_buffers", NUMBER, "mm", "Längd över buffertar", "Length over buffers"),
    Field("wheelbase", NUMBER, "mm", "Axelavstånd", "Wheelbase"),
    Field("weight", NUMBER, "t", "Vikt", "Weight"),
    Field("max_speed", NUMBER, "km/h", "Största hastighet", "Top speed"),
    Field("load", NUMBER, "t", "Lastvikt", "Load"),
    Field("axles", INTEGER, "", "Axlar", "Axles"),
    Field("built", TEXT, "", "Byggår", "Built", 40),
    Field("brake", TEXT, "", "Broms", "Brake", 80),
    # North America: US stencils give feet, pounds and miles an hour, so these keys never hold
    # a metric value, and the metric keys never a US one.
    Field("length_ft", NUMBER, "ft", "Längd", "Length"),
    Field("truck_centers_ft", NUMBER, "ft", "Boggiavstånd", "Truck centers"),
    Field("weight_lbs", NUMBER, "lbs", "Tara (LT WT)", "Light weight (LT WT)"),
    Field("max_speed_mph", NUMBER, "mph", "Största hastighet", "Top speed"),
    Field("load_lbs", NUMBER, "lbs", "Lastförmåga (CAPY)", "Capacity (CAPY)"),
)

RETIRED: Final[frozenset[str]] = frozenset()
"""Keys that were once in the register and are no longer used. They are never used again."""

BY_KEY: Final[dict[str, Field]] = {f.key: f for f in REGISTER}


@dataclass(frozen=True)
class Profile:
    name: str
    name_en: str
    keys: tuple[str, ...]
    labels: dict[str, tuple[str, str]] = field(default_factory=dict)
    """The profile's own labels, Swedish and English, where they differ from the register's."""


_METRIC: Final = (
    "litt",
    "operator",
    "epoch",
    "description",
    "length_over_buffers",
    "wheelbase",
    "weight",
    "max_speed",
    "load",
    "axles",
    "built",
    "brake",
)

PROFILES: Final[dict[FieldProfile, Profile]] = {
    FieldProfile.SE: Profile("Sverige", "Sweden", _METRIC),
    # Modern European markings: the UIC's letter code for the type, beside the litt.
    FieldProfile.EU: Profile(
        "Europa",
        "Europe",
        _METRIC,
        {"litt": ("UIC-typ eller littera", "UIC type or class")},
    ),
    # The North American car card: class, road name and era, in US units.
    FieldProfile.US: Profile(
        "USA",
        "USA",
        (
            "litt",
            "operator",
            "epoch",
            "description",
            "length_ft",
            "truck_centers_ft",
            "weight_lbs",
            "max_speed_mph",
            "load_lbs",
            "axles",
            "built",
            "brake",
        ),
        {
            "litt": ("Klass", "Class"),
            "operator": ("Bolag (road name)", "Road name"),
            "epoch": ("Era", "Era"),
        },
    ),
}


class BadTypeData(ValueError):
    """The values do not follow the register or the profile. The message is for the person."""


def label(profile: FieldProfile, key: str) -> str:
    """The Swedish label the profile gives the key."""
    own = PROFILES[profile].labels.get(key)
    return own[0] if own else BY_KEY[key].label


def register() -> FieldRegister:
    """The register and the profiles as they are published (GET /prototypes/fields)."""
    return FieldRegister(
        fields=[
            TypeField(
                key=f.key,
                kind=f.kind,
                unit=f.unit,
                label=f.label,
                label_en=f.label_en,
                max_length=f.max_length if f.kind is TEXT else 20,
            )
            for f in REGISTER
        ],
        profiles=[
            ProfileFields(
                profile=code,
                name=profile.name,
                name_en=profile.name_en,
                fields=[
                    ProfileField(
                        key=key,
                        label=profile.labels.get(key, (BY_KEY[key].label, ""))[0],
                        label_en=profile.labels.get(key, ("", BY_KEY[key].label_en))[1],
                    )
                    for key in profile.keys
                ],
            )
            for code, profile in PROFILES.items()
        ],
    )


def _number(text: str, whole: bool) -> str:
    """A number as written, with a point and without spaces or trailing zeros: 14,50 is 14.5."""
    plain = "".join(text.split()).replace(",", ".")
    try:
        number = Decimal(plain)
    except InvalidOperation:
        raise ValueError from None
    if not number.is_finite() or number < 0 or number > LARGEST:
        raise ValueError
    if whole and number != number.to_integral_value():
        raise ValueError
    written = format(number, "f")
    if "." in written:
        written = written.rstrip("0").rstrip(".")
    return written or "0"


def clean(
    profile: FieldProfile, values: Mapping[str, str], *, empty: bool = False
) -> dict[str, str]:
    """The values checked against the register and the profile, in the profile's order. An empty
    value is left out, or kept as empty when empty is true: the owner's own empty value on a
    vehicle is a deviation too (CAT-162). Raises BadTypeData."""
    shown = PROFILES[profile].keys
    for key in values:
        if key not in BY_KEY:
            raise BadTypeData(f"Fältet {key} finns inte i fältregistret.")
        if key not in shown:
            raise BadTypeData(
                f"{BY_KEY[key].label} hör till en annan fältprofil. "
                "Välj rätt profil för förebilden."
            )
    found: dict[str, str] = {}
    for key in shown:
        if key not in values:
            continue
        text = values[key].strip()
        if not text:
            if empty:
                found[key] = ""
            continue
        f = BY_KEY[key]
        if f.kind is TEXT:
            if len(text) > f.max_length:
                raise BadTypeData(f"{label(profile, key)}: högst {f.max_length} tecken.")
            found[key] = text
            continue
        try:
            found[key] = _number(text, f.kind is INTEGER)
        except ValueError:
            what = "ett heltal" if f.kind is INTEGER else "ett tal"
            unit = f" i {f.unit}" if f.unit else ""
            example = ", till exempel 14.5" if f.kind is NUMBER else ""
            raise BadTypeData(f"{label(profile, key)}: ange {what}{unit}{example}.") from None
    return found
