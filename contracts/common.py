"""Building blocks shared by the contracts: ids, times, sides and the canonical checksum.

Rules for every contract (spec 5.1 and "Kontrakten" in TrainMeet Platform):
- Unknown fields are kept and ignored, so an older reader never breaks on a newer writer.
- New fields are added without a new format number. Removing a field or changing what it
  means gives a new number (trainmeet.meet/2 ...).
- Ids are stable between versions: a place, section, train or call keeps its id.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")]
"""A stable id: letters, digits and . _ : - (at most 80 characters)."""

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
"""A non-empty line of text for people."""

TimeOfDay = Annotated[str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]
"""Model time as HH:MM. A time after midnight on the next game day uses day_offset."""


class Contract(BaseModel):
    """Base for every contract object: unknown fields are kept, nothing is coerced silently."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True, frozen=True)


class Side(StrEnum):
    """Which side of a place a section or exit leaves from, as the box shows it."""

    LEFT = "left"
    RIGHT = "right"


class Weekday(StrEnum):
    """The timetable's weekday (trafikdag). Not the same as the game day (Dag 1…N)."""

    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"


class Language(StrEnum):
    SV = "sv"
    EN = "en"
    DA = "da"
    NB = "nb"
    DE = "de"


def canonical_json(data: Mapping[str, Any]) -> bytes:
    """Sorted keys, no spaces, UTF-8: the same bytes for the same content, always."""
    return json.dumps(
        data, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode("utf-8")


def checksum(data: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON, as hex. Synk uses it to know that a package is whole."""
    return hashlib.sha256(canonical_json(data)).hexdigest()
