"""EVN and the UIC check digit, derived from the number as it is painted (CAT-57–CAT-60).

The number is text exactly as on the vehicle (CAT-55). Twelve digits, or eleven without the
check digit, are read as an EVN: interoperability code (2), country number (2), serial
number (7) and check digit (1). The parts and the check digit are derived here every time and
never written back into the number (CAT-58). A painted check digit that does not match is
reported, never corrected (CAT-59).

Seven or eight digits are only a UIC number together with the interoperability code and the
country number from elsewhere. Eight digits (seven and a check digit) are read as UIC when the
check digit matches or when they are painted in the UIC grouping ("393 3 013-7"); a national
number ("6018 035-3") has its own check digit, so a mismatch there means "not a UIC number",
not "wrong" (CAT-60).

Ported from TrainCatalog's catalog/evn.py with its tests (C14).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Country number -> the letters painted beside the keeper marking (TSI/COTIF).
COUNTRY_LETTERS = {
    "10": "FIN",
    "51": "PL",
    "52": "BG",
    "53": "RO",
    "54": "CZ",
    "55": "H",
    "56": "SK",
    "70": "GB",
    "71": "E",
    "72": "SRB",
    "73": "GR",
    "74": "S",
    "75": "TR",
    "76": "N",
    "78": "HR",
    "79": "SLO",
    "80": "D",
    "81": "A",
    "82": "L",
    "83": "I",
    "84": "NL",
    "85": "CH",
    "86": "DK",
    "87": "F",
    "88": "B",
    "94": "P",
}
_UIC_GROUPING = re.compile(r"\d{3}\s+\d\s+\d{3}\s*-\s*\d")


@dataclass(frozen=True)
class Evn:
    interop: str
    country: str
    country_letters: str
    serial: str
    check: int
    given: int | None

    @property
    def valid(self) -> bool:
        """False only when a painted check digit is wrong."""
        return self.given is None or self.given == self.check

    @property
    def text(self) -> str:
        """For example 31 76 393 3 013-1, always with the computed check digit."""
        return f"{self.interop} {self.country} {self.serial}-{self.check}"


def check_digit(eleven: str) -> int:
    """Weights 2, 1, 2, 1 ... from the left, the digit sum of each product, up to the next ten."""
    if not re.fullmatch(r"\d{11}", eleven):
        raise ValueError("eleven digits expected")
    total = sum(
        sum(divmod(int(digit) * (2 if index % 2 == 0 else 1), 10))
        for index, digit in enumerate(eleven)
    )
    return (10 - total % 10) % 10


def serial_text(serial: str) -> str:
    """'3933013' -> '393 3 013': the type digits, then the serial number, as painted."""
    return f"{serial[:3]} {serial[3]} {serial[4:]}"


def describe(number: str, interop: str = "", country: str = "") -> Evn | None:
    """The EVN in a painted number, or None when it cannot be read as one."""
    digits = re.sub(r"\D", "", number or "")
    interop, country = (interop or "").strip(), (country or "").strip()
    given: int | None = None
    if len(digits) in (11, 12):
        interop, country, serial = digits[:2], digits[2:4], digits[4:11]
        given = int(digits[11]) if len(digits) == 12 else None
    elif (
        len(digits) in (7, 8)
        and re.fullmatch(r"\d{2}", interop)
        and re.fullmatch(r"\d{2}", country)
    ):
        serial = digits[:7]
        given = int(digits[7]) if len(digits) == 8 else None
    else:
        return None
    check = check_digit(interop + country + serial)
    if len(digits) == 8 and given != check and not _UIC_GROUPING.fullmatch(number.strip()):
        return None
    return Evn(
        interop=interop,
        country=country,
        country_letters=COUNTRY_LETTERS.get(country, ""),
        serial=serial_text(serial),
        check=check,
        given=given,
    )
