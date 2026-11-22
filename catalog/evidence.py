"""Belägget: does a source hold a value (#53 del b, CAT-167–CAT-170)? Ported from TrainCatalog's
catalog/research_provider.py (validate_result) and catalog/research_sources.py
(excerpt_supports), for the web search through TrainMeet ID's meter.

The meter gives what the AI proposes with the citations the AI put on it, and every result of
the real searches (contracts/tokens.py). Nothing of that is trusted here:

- A source must be in the real search result (CAT-167): a citation whose address is not one of
  the results is invented, and is refused.
- The publisher is classed against the small reviewed list (CAT-168, catalog/publishers.py),
  never by what the AI says.
- An excerpt of the source must hold the value (CAT-169). A number with a unit is compared as a
  number: 1 435 mm, 1435 mm and 1,435 m are the same length. The unit may stand after the
  number or in the label before it, as in a company's table: Maximum speed (km/h) 120, also
  with the middle dot a table leaves: Maximum speed (km/h) · 120. A count of axles may be
  written 4 axlar, tvåaxlig, Number of axles 2, two wheelsets or as the wheel arrangement after
  its label, Achsfolge Bo'Bo'. Text is compared after normalising: case, spaces and the kind
  of dash do not matter. An excerpt that tells when something was ordered or presented does not
  hold a year of building.
- A value without such evidence is dropped, never proposed. What is kept is the evidence and
  the address per field.

supports() is also what says, later, whether the evidence still agrees with the value that
stands in the field (CAT-170): after a change of the value, the same excerpt may not hold it.

The search's own excerpt is at most about 150 characters, and in a table the value often stands
further in. When it does not hold the value, the page itself may (catalog/source_pages.py): the
cited words are found in the page's text, and the excerpt is read on from there, at most
READ_ON characters and never past the middle of a word, until it holds the value or not. The
excerpt that is kept is then that part of the page, from the cited words to the value, and the
same rules hold for it: the unit, the label, ordered is not built. A page where the cited words
cannot be found is no evidence.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from catalog.prototype_fields import BY_KEY, INTEGER, TEXT, BadTypeData, clean
from catalog.publishers import publisher_kind, safe_url
from contracts.catalog import (
    DroppedField,
    DroppedReason,
    Evidence,
    FieldEvidence,
    FieldProfile,
    PublisherKind,
)
from contracts.tokens import MeterCitation, MeterSearchResult, MeterSearchValue

MOST_PER_FIELD: Final = 3
"""Sources kept per field: a known publisher's first."""
SHORTEST_EXCERPT: Final = 5
"""An excerpt shorter than this says nothing."""
READ_ON: Final = 1000
"""How far into the page, from the cited words, a value may stand: a table's rows or an
infobox's, never the rest of the page."""
ANCHOR: Final = 80
"""The cited words that are looked for in the page: the first letters and digits of them."""
SHORTEST_ANCHOR: Final = 12

_D = Decimal
UNITS: Final[dict[str, dict[str, Decimal]]] = {
    # The field's unit, and what one of each written unit is in it. Only within one system:
    # metric is never made into US units or the other way round.
    "mm": {
        "mm": _D(1),
        "millimeter": _D(1),
        "millimetre": _D(1),
        "millimetres": _D(1),
        "millimeters": _D(1),
        "cm": _D(10),
        "centimeter": _D(10),
        "m": _D(1000),
        "meter": _D(1000),
        "meters": _D(1000),
        "metre": _D(1000),
        "metres": _D(1000),
    },
    "t": {
        "t": _D(1),
        "ton": _D(1),
        "tonne": _D(1),
        "tonnes": _D(1),
        "tonnen": _D(1),
        "kg": _D("0.001"),
        "kilogram": _D("0.001"),
    },
    "km/h": {"km/h": _D(1), "kmh": _D(1), "km/tim": _D(1), "km/t": _D(1), "kph": _D(1)},
    "ft": {"ft": _D(1), "feet": _D(1), "foot": _D(1)},
    "lbs": {"lbs": _D(1), "lb": _D(1), "pounds": _D(1), "pound": _D(1)},
    "mph": {"mph": _D(1), "miles per hour": _D(1)},
}
COUNTED: Final[dict[str, tuple[str, ...]]] = {
    # A whole number without a unit is still a number of something: the words that say what.
    # A wheelset is an axle with its two wheels, so a count of wheelsets is a count of axles.
    "axles": (
        "axlar",
        "axliga",
        "axlig",
        "axel",
        "axl",
        "axles",
        "axle",
        "achsen",
        "achsig",
        "achse",
        "hjulpar",
        "hjulparen",
        "wheelsets",
        "wheelset",
        "wheel sets",
        "radsätze",
        "radsätzen",
        "radsatz",
    ),
}
COUNT_LABELS: Final[dict[str, tuple[str, ...]]] = {
    # A label that is the count itself, so that the number stands after it: Achszahl 4.
    "axles": ("achszahl", "achsanzahl", "axelantal", "axle count"),
}
ARRANGEMENT_LABELS: Final[dict[str, tuple[str, ...]]] = {
    # A label after which the wheel arrangement stands, which counts the axles: Bo'Bo' is four.
    "axles": (
        "achsfolge",
        "axelföljd",
        "hjulföljd",
        "axle arrangement",
        "wheel arrangement",
        "uic axles",
    ),
}
_ARRANGEMENT: Final = re.compile(r"(?:(?:[A-D]o?|[1-4])['\u2019\u2032]?[-+]?)+")
"""Bo'Bo', Co'Co', B-B, 1'D1': groups of a letter, or a digit, each with a prime or not."""
_AXLES_IN: Final = {"A": 1, "B": 2, "C": 3, "D": 4, "1": 1, "2": 2, "3": 3, "4": 4}
_WORDS: Final = {
    "två": 2,
    "tva": 2,
    "tre": 3,
    "fyr": 4,
    "fyra": 4,
    "sex": 6,
    "åtta": 8,
    "two": 2,
    "three": 3,
    "four": 4,
    "six": 6,
    "eight": 8,
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "sechs": 6,
    "acht": 8,
}
_NUMBER: Final = (
    r"(?<![\w.,])"
    r"(\d{1,3}(?:[ \u00a0\u202f'\u2019.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
)
_GLUED: Final = (
    r"(?<=[^\W\d_])"
    r"(\d{1,3}(?:[ \u00a0\u202f'\u2019.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
)
"""A number right after a word, as when a table loses its space: Length over buffers14 040 mm.
Read beside _NUMBER, never instead of it: BR185 120 km/h is still 120 km/h."""
_AFTER: Final = r"(?![0-9A-Za-zÀ-ÖØ-öø-ÿ/])"
_NOT_A_DIGIT_AFTER: Final = r"(?![.,]?\d)"
_SEPARATOR: Final = r"(?:\s*[:=\u00b7])*\s*"
"""Between a label and its number: nothing, a colon, or the middle dot a table leaves when it
loses its columns, Average tare weight (kg) · 15,500 and Achsen: · 4."""
_COUNT_OF: Final = r"(?:number\s+of|no\.?\s+of|antal|anzahl(?:\s+der)?)"
"""Words before the counted thing that make the label a count: Number of axles 2."""
_EACH: Final = r"(?!\s+(?:per|pro|je)\b)"
"""2 axlar per boggi is not the number of the vehicle's axles. The counted word is read whole
first (an atomic group), so that axl in axlar per cannot slip past."""
_FEET_INCHES: Final = re.compile(
    r"(?<![\w.,])(\d+)\s*(?:ft|feet|foot|['\u2019\u2032])\s*-?\s*"
    r"(\d+(?:\.\d+)?)\s*(?:in\b|inch(?:es)?\b|[\"\u201d\u2033])",
    re.IGNORECASE,
)
_NOT_BUILT: Final = re.compile(
    r"\b(ordered|beställ\w*|bestellt\w*|introduced|presented|presentera\w*)\b", re.IGNORECASE
)
"""When something was ordered or presented is not when it was built."""
_DASHES: Final = re.compile(r"\s*[\u2010-\u2015\u2212-]\s*")


def _unit_pattern(names: Iterable[str]) -> str:
    return "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))


def numbers(written: str) -> set[Decimal]:
    """What a written number may be: 1 435 and 1435 are one number, 14,5 is 14.5, and 1.435 is
    1.435 or 1 435, since some write the thousands with a point."""
    plain = re.sub(r"[ \u00a0\u202f'\u2019]", "", written)
    signs = [c for c in plain if c in ".,"]
    found: set[str] = set()
    if not signs:
        found.add(plain)
    elif "." in signs and "," in signs:
        decimal = signs[-1]
        thousands = "," if decimal == "." else "."
        found.add(plain.replace(thousands, "").replace(decimal, "."))
    elif len(signs) > 1:
        found.add(plain.replace(signs[0], ""))  # 1.435.000: only thousands are written so
    else:
        whole, _, rest = plain.partition(signs[0])
        found.add(f"{whole}.{rest}")
        if len(rest) == 3 and whole != "0":
            found.add(whole + rest)
    result: set[Decimal] = set()
    for each in found:
        try:
            result.add(Decimal(each))
        except InvalidOperation:
            continue
    return result


def _in_unit(excerpt: str, unit: str) -> set[Decimal]:
    """Every number with a unit in the excerpt, as numbers in the field's unit: the unit after
    the number, or in brackets in the label before it, Average tare weight (kg) 15,500."""
    names = UNITS[unit]
    units = _unit_pattern(names)
    found: set[Decimal] = set()
    for start in (_NUMBER, _GLUED):
        after = re.compile(rf"{start}\s*-?\s*({units}){_AFTER}", re.IGNORECASE)
        for match in after.finditer(excerpt):
            factor = names[match[2].lower()]
            found |= {number * factor for number in numbers(match[1])}
    before = re.compile(
        rf"[(\[]\s*({units})\s*[)\]]{_SEPARATOR}{_NUMBER}{_NOT_A_DIGIT_AFTER}", re.IGNORECASE
    )
    for match in before.finditer(excerpt):
        factor = names[match[1].lower()]
        found |= {number * factor for number in numbers(match[2])}
    if unit == "ft":
        for match in _FEET_INCHES.finditer(excerpt):
            found.add(Decimal(match[1]) + Decimal(match[2]) / 12)
    return found


def _counted(excerpt: str, words: Sequence[str], labels: Sequence[str] = ()) -> set[Decimal]:
    """Every count of the thing in the excerpt: 4 axlar, 2-axlig, tvåaxlig, two wheelsets, and
    with the number after a label that says it is the count: Number of axles 2, Achsen: 4,
    Achszahl 4."""
    what = _unit_pattern(words)
    found = {
        Decimal(match[1])
        for match in re.finditer(
            rf"(?<![\w.,])(\d+)\s*-?\s*(?>(?:{what})\w*){_EACH}", excerpt, re.IGNORECASE
        )
    }
    spelled = _unit_pattern(_WORDS)
    for match in re.finditer(
        rf"\b({spelled})[\s-]*(?>(?:{what})\w*){_EACH}", excerpt, re.IGNORECASE
    ):
        found.add(Decimal(_WORDS[match[1].lower()]))
    counts = [
        rf"\b{_COUNT_OF}\s+(?:{what})",  # Number of axles 2, Antal axlar 2
        rf"\b(?:{what})\s*[:=\u00b7]",  # Achsen: 4
    ]
    if labels:
        counts.append(rf"\b(?:{_unit_pattern(labels)})")  # Achszahl 4
    for label in counts:
        for match in re.finditer(
            rf"{label}{_SEPARATOR}(\d+){_NOT_A_DIGIT_AFTER}", excerpt, re.IGNORECASE
        ):
            found.add(Decimal(match[1]))
    return found


def _arranged(excerpt: str, labels: Sequence[str]) -> set[Decimal]:
    """The axles in a wheel arrangement after its label, UIC axles: · Bo'Bo' or Achsfolge
    Co'Co': a letter is driven axles, A one to D four, and a digit is that many axles that are
    not. Only after the label, since a letter and a prime alone can be anything."""
    label = rf"(?i:\b(?:{_unit_pattern(labels)}))"
    found: set[Decimal] = set()
    for match in re.finditer(rf"{label}{_SEPARATOR}([\w'\u2019\u2032+-]{{2,20}})", excerpt):
        written = match[1].strip("-+")
        if _ARRANGEMENT.fullmatch(written) and re.search("[A-D]", written):
            found.add(Decimal(sum(_AXLES_IN[c] for c in written if c in _AXLES_IN)))
    return found


def normalized(text: str) -> str:
    """Text as it is compared: the same letters whatever the case, the spaces and the dashes."""
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(_DASHES.sub("-", text).split())


def _text_in(value: str, excerpt: str) -> bool:
    """The value stands in the excerpt as words of its own, not as a part of another word."""
    wanted, within = normalized(value), normalized(excerpt)
    if not wanted:
        return False
    start = within.find(wanted)
    while start >= 0:
        end = start + len(wanted)
        before = within[start - 1] if start else " "
        after = within[end] if end < len(within) else " "
        if not before.isalnum() and not after.isalnum():
            return True
        start = within.find(wanted, start + 1)
    return False


def supports(key: str, value: str, excerpt: str) -> bool:
    """Does the excerpt hold the value for the field (CAT-169, CAT-170)? The value is as the
    field register writes it: a number with a point, in the field's unit."""
    known = BY_KEY.get(key)
    value = value.strip()
    if known is None or not value or len(excerpt.strip()) < SHORTEST_EXCERPT:
        return False
    if key == "built" and _NOT_BUILT.search(excerpt):
        return False
    if known.kind is TEXT:
        return _text_in(value, excerpt)
    try:
        wanted = Decimal(value)
    except InvalidOperation:
        return False
    if known.unit in UNITS:
        found = _in_unit(excerpt, known.unit)
        if known.unit == "ft":  # inches make thirds of a foot: near enough is the same
            return any(abs(each - wanted) <= Decimal("0.01") for each in found)
        return wanted in found
    if key in COUNTED and known.kind is INTEGER:
        counted = _counted(excerpt, COUNTED[key], COUNT_LABELS.get(key, ()))
        if key in ARRANGEMENT_LABELS:
            counted |= _arranged(excerpt, ARRANGEMENT_LABELS[key])
        return wanted in counted
    return False


# --- Further on in the page (CAT-169, förslag 22 november) -------------------------------------


def _skeleton(text: str) -> tuple[str, list[int]]:
    """The text's ASCII letters and digits in lower case, with where each stands: the search
    and Catalog make a page into text differently, with other marks, spaces, and sometimes
    without å, ä and ö, but the same letters and digits in the same order."""
    kept: list[str] = []
    where: list[int] = []
    for index, char in enumerate(text):
        if char.isascii() and char.isalnum():
            kept.append(char.lower())
            where.append(index)
    return "".join(kept), where


def anchored(cited: str, page: str) -> tuple[int, int] | None:
    """Where the cited words stand in the page's text, from the first of them to the last that
    was looked for, or None when they are not there."""
    wanted, _ = _skeleton(cited.removesuffix("...").removesuffix("…"))
    wanted = wanted[:ANCHOR]
    if len(wanted) < SHORTEST_ANCHOR:
        return None
    letters, where = _skeleton(page)
    found = letters.find(wanted)
    if found < 0:
        return None
    return where[found], where[found + len(wanted) - 1] + 1


def read_on(key: str, value: str, cited: str, page: str) -> str | None:
    """The part of the page from the cited words on that holds the value, as short as it can be
    without ending inside a word, or None."""
    found = anchored(cited, page)
    if found is None:
        return None
    start, end = found
    last = min(len(page), start + READ_ON)
    ends = [match.start() for match in re.finditer(r"\s", page[end:last])]
    for stop in [end + each for each in ends] + [last]:
        if last < len(page) and stop == last and not page[last].isspace():
            continue  # never a number cut off at the end of the reach
        excerpt = page[start:stop].strip()
        if supports(key, value, excerpt):
            return excerpt
    return None


# --- The meter's answer, checked (CAT-167–CAT-169) ---------------------------------------------


@dataclass(frozen=True)
class Checked:
    """What is left of the AI's proposal after the source rules: the values with valid
    evidence, the evidence as it is stored, and what was dropped and why."""

    fields: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    dropped: list[DroppedField] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)
    """The cited pages whose excerpt did not hold the value, and that were not given: the
    pages to read (catalog/source_pages.py) before checking again."""
    from_page: set[str] = field(default_factory=set)
    """The fields whose evidence was read further on in the page."""


def _plain(text: str, most: int) -> str:
    """Text from a web page, for keeping: on one line, without control characters."""
    return " ".join("".join(c if c.isprintable() else " " for c in text).split())[:most]


def check(
    profile: FieldProfile,
    wanted: Sequence[str],
    values: Sequence[MeterSearchValue],
    results: Sequence[MeterSearchResult],
    searched_at: datetime,
    pages: Mapping[str, str] | None = None,
) -> Checked:
    """The AI's values for the wanted keys, each kept only with a source from the real search
    whose excerpt holds it, or whose page holds it further on from the cited words (pages, by
    the safe address). Everything else is dropped, with the reason."""
    real = {safe: result for result in results if (safe := safe_url(result.url)) is not None}
    found = Checked()
    seen: set[str] = set()
    for proposed in values:
        key = proposed.key
        if key not in wanted or key in seen:
            continue
        seen.add(key)
        try:
            value = clean(profile, {key: proposed.value}).get(key, "")
        except BadTypeData:
            value = ""
        if not value:
            found.dropped.append(DroppedField(key=key, reason=DroppedReason.BAD_VALUE))
            continue
        if not proposed.citations:
            found.dropped.append(DroppedField(key=key, reason=DroppedReason.NO_SOURCE))
            continue
        cited = [
            (safe, citation)
            for citation in proposed.citations
            if (safe := safe_url(citation.url)) is not None and safe in real
        ]
        if not cited:
            found.dropped.append(DroppedField(key=key, reason=DroppedReason.INVENTED_SOURCE))
            continue
        kept, read, unread = _holding(key, value, cited, real, searched_at, pages or {})
        if not kept:
            found.dropped.append(DroppedField(key=key, reason=DroppedReason.UNSUPPORTED))
            found.unread.extend(url for url in unread if url not in found.unread)
            continue
        found.fields[key] = value
        found.evidence[key] = kept
        if read:
            found.from_page.add(key)
    return found


def _holding(
    key: str,
    value: str,
    cited: Sequence[tuple[str, MeterCitation]],
    real: Mapping[str, MeterSearchResult],
    searched_at: datetime,
    pages: Mapping[str, str],
) -> tuple[list[dict[str, str]], bool, list[str]]:
    """The sources whose excerpt holds the value, one per address, a known publisher's first;
    whether any was read on in its page; and the cited pages that were not there to read."""
    holding: dict[str, dict[str, str]] = {}
    read = False
    unread: list[str] = []
    for url, citation in cited:
        if url in holding:
            continue
        excerpt: str | None = citation.cited_text
        if not supports(key, value, citation.cited_text):
            excerpt = None
            if url in pages:
                excerpt = read_on(key, value, citation.cited_text, pages[url])
            elif url not in unread:
                unread.append(url)
        if excerpt is None:
            continue
        read = read or excerpt != citation.cited_text
        holding[url] = {
            "value": value,
            "url": url,
            "title": _plain(citation.title or real[url].title, 500),
            "excerpt": _plain(excerpt, 2000),
            "searched_at": searched_at.isoformat(),
        }
    ordered = sorted(
        holding.values(), key=lambda each: publisher_kind(each["url"]) is PublisherKind.UNKNOWN
    )
    return ordered[:MOST_PER_FIELD], read, unread


# --- The evidence as it is shown, with whether it still agrees (CAT-170) -----------------------


def shown(stored: Mapping[str, Any] | None, fields: Mapping[str, str]) -> Evidence:
    """The stored evidence for the fields that have a value now, each with its publisher's class
    by the list as it is now, and whether its excerpt still holds the value that stands there."""
    found: Evidence = {}
    for key, items in (stored or {}).items():
        now = fields.get(key, "")
        if not now or not isinstance(items, list):
            continue
        evidence = []
        for item in items[:MOST_PER_FIELD]:
            try:
                evidence.append(
                    FieldEvidence(
                        value=item["value"],
                        url=item["url"],
                        title=item.get("title", ""),
                        publisher=publisher_kind(item["url"]),
                        excerpt=item["excerpt"],
                        searched_at=datetime.fromisoformat(item["searched_at"]),
                        agrees=supports(key, now, item["excerpt"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        if evidence:
            found[key] = evidence
    return found


def carried(stored: Mapping[str, Any] | None, fields: Mapping[str, str]) -> dict[str, Any]:
    """The evidence a new revision takes with it: that of the fields it still has a value for."""
    return {key: items for key, items in (stored or {}).items() if fields.get(key)}
