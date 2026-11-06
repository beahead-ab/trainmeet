"""Regelboken: the train types every source is read with (import principle 3).

A source that says what a train type carries (the planning file's Content) is the fact. Where
it does not, the abbreviation is looked up here. Where no rule is found the import asks; it
never guesses from the train number.

The abbreviations come from the old Cloud (table_import.TRAIN_PREFIXES): the planning program's
train categories and what they are in TrainMeet. Museum trains (M) and InterCity are passenger
trains; wagon moves and loco transfers are service trains.
"""

from __future__ import annotations

import unicodedata
from typing import Final

from contracts.planning import Certainty, Origin, TrainContent, TrainTypeRule

SOURCE: Final = "regelboken"

KNOWN: Final[dict[TrainContent, tuple[str, ...]]] = {
    "passengers": ("pt", "snt", "lt", "rt", "xt", "nt", "ic", "ir", "m"),
    "goods": ("g", "gt", "gxt", "lgt", "ngt", "mt", "pxt"),
    "service": ("a", "t", "vut", "trp"),
}
_BY_KEY: Final[dict[str, TrainContent]] = {
    code: content for content, codes in KNOWN.items() for code in codes
}


def key(code: str) -> str:
    """The abbreviation as a key: case and punctuation do not count (Pt, PT and P.t.)."""
    text = unicodedata.normalize("NFC", code).casefold()
    return "".join(char for char in text if char.isalnum())


def known(code: str) -> TrainTypeRule | None:
    """The rule for an abbreviation, or None when the rulebook has none."""
    content = _BY_KEY.get(key(code))
    if content is None:
        return None
    return TrainTypeRule(
        code=code,
        content=content,
        certainty=Certainty.LIKELY,
        origins=[Origin(source=SOURCE, at=f"Förkortningen {code}")],
    )
