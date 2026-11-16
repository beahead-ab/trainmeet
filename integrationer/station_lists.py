"""Stationslistorna (4c1, IMPORT-33): the planning program's dispatch list per station, read with
code, never with AI. One list per station, in ODT (one file, or many in a ZIP), Excel or CSV,
with the columns Tåg, Dagar, Spår, Ank, Från, Avg, Till, the week's day boxes and Anmärkningar.

With the planning file in the draft the lists are its check, not a second source: each list gets
a verdict, row by row, against the plan (IMPORT-27; Värnamo gave no questions in the old Cloud).
The draft does not change. Building a draft from the lists alone, without the planning file,
comes in the next part of 4c1.

Ported from the old Cloud (cloud/dispatch_import.py). Nothing in a file is ever run, archives
are checked before they are unpacked, and XML with its own definitions is refused. What the
lists say about the vehicles in a train ("I tåget: …") is never read in.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final
from xml.etree import ElementTree as ET

from contracts.common import Weekday
from contracts.meet import MeetPackage, Train
from contracts.planning import ImportReport, ImportResult, ListVerdict, Source

MAX_BYTES: Final = 20 * 1024 * 1024
MAX_EXPANDED: Final = 100 * 1024 * 1024
MAX_ENTRIES: Final = 200
MAX_ROWS: Final = 20_000
SUFFIXES: Final = (".odt", ".zip", ".xlsx", ".csv")
LEVEL: Final = 1  # Stationstidtabeller: underlagsnivå 1 (I1)
SHOWN: Final = 5

ODT: Final = {
    "t": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "a": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
}
XLSX: Final = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
HEADER: Final = (
    {"tåg", "tog"},
    {"dagar", "dage", "dager"},
    {"spår", "spor"},
    {"ank"},
    {"från", "fra"},
    {"avg", "afg"},
    {"till", "til"},
)
NO_STOP: Final = ("ej uppehåll", "uden ophold", "uten opphold")
DAYS: Final = {
    "m": 0, "må": 0, "mån": 0, "måndag": 0,
    "ti": 1, "tis": 1, "tisdag": 1,
    "o": 2, "on": 2, "ons": 2, "onsdag": 2,
    "to": 3, "tor": 3, "torsdag": 3,
    "f": 4, "fr": 4, "fre": 4, "fredag": 4,
    "l": 5, "lö": 5, "lör": 5, "lördag": 5,
    "s": 6, "sö": 6, "sön": 6, "söndag": 6,
}  # fmt: skip
WEEK: Final = list(Weekday)
TIME: Final = re.compile(r"^\(?([0-2]?\d)[:.]([0-5]\d)\)?$")


class ListError(ValueError):
    """The file is not station lists that can be read. The message is for the planner."""


@dataclass
class Row:
    """One row of a station's list: a train at the place, or passing it."""

    station: str
    code: str
    document: str
    row: int
    label: str
    number: str
    days: set[int]
    track: str
    arrival: str | None
    departure: str | None
    origin: str
    destination: str
    stops: bool
    remote: str | None = None  # the code before the track: a place the station clears for


@dataclass
class Lists:
    """What the lists say: the rows per station document, and what could not be read."""

    rows: dict[str, list[Row]] = field(default_factory=dict)
    left_out: list[str] = field(default_factory=list)


def header_key(text: str) -> str:
    return re.sub(r"[^\wåäöæøé]", "", text.casefold())


def is_lists(name: str) -> bool:
    return Path(name).suffix.casefold() in SUFFIXES


def member_name(item: zipfile.ZipInfo) -> str:
    """The name as it was written: an archive without the UTF-8 flag is read as CP437 by
    Python, so "Mkd Munkerød.odt" would get the wrong station name."""
    if item.flag_bits & 0x800:
        return item.filename
    try:
        return item.filename.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return item.filename


def _members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > MAX_ENTRIES or sum(i.file_size for i in entries) > MAX_EXPANDED:
        raise ListError("Arkivet är för stort: högst 200 filer och 100 MB uppackat.")
    names: set[str] = set()
    for item in entries:
        path = PurePosixPath(item.filename)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in item.filename
            or item.filename in names
            or item.flag_bits & 1
        ):
            raise ListError("Arkivet har ogiltiga, dubbla eller krypterade filnamn.")
        names.add(item.filename)
    return [item for item in entries if not item.is_dir()]


def _xml(data: bytes) -> ET.Element:
    if len(data) > 16 * 1024 * 1024 or re.search(rb"<!\s*(DOCTYPE|ENTITY)", data, re.I):
        raise ListError("Dokumentets XML är för stort eller har egna definitioner.")
    return ET.fromstring(data)


def _odt_text(cell: ET.Element) -> str:
    for element in cell.iter():
        if element.tag == f"{{{ODT['t']}}}s":
            element.text = " " * min(100, int(element.get(f"{{{ODT['t']}}}c", "1")))
        elif element.tag in {f"{{{ODT['t']}}}tab", f"{{{ODT['t']}}}line-break"}:
            element.text = " "
    return "\n".join("".join(p.itertext()) for p in cell.findall(".//t:p", ODT)).strip()


def _odt_tables(data: bytes) -> list[list[list[str]]]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        _members(archive)
        root = _xml(archive.read("content.xml"))
    tables = []
    for table in root.findall(".//a:table", ODT):
        rows = []
        for row in table.findall(".//a:table-row", ODT):
            cells = []
            for cell in row.findall("a:table-cell", ODT):
                repeat = min(50, int(cell.get(f"{{{ODT['a']}}}number-columns-repeated", "1")))
                cells.extend([_odt_text(cell)] * repeat)
            rows.append(cells)
        tables.append(rows)
    return tables


def _xlsx_tables(data: bytes) -> list[list[list[str]]]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = {item.filename for item in _members(archive)}
        shared: list[str] = []
        if "xl/sharedStrings.xml" in members:
            for item in _xml(archive.read("xl/sharedStrings.xml")).findall(f"{XLSX}si"):
                shared.append("".join(t.text or "" for t in item.iter(f"{XLSX}t")))
        sheets = sorted(n for n in members if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        tables = []
        for sheet in sheets:
            rows = []
            for row in _xml(archive.read(sheet)).iter(f"{XLSX}row"):
                cells: dict[int, str] = {}
                for cell in row.findall(f"{XLSX}c"):
                    ref = cell.get("r", "")
                    letters = re.match(r"[A-Z]+", ref)
                    column = 0
                    for char in letters.group(0) if letters else "A":
                        column = column * 26 + ord(char) - 64
                    kind = cell.get("t")
                    if kind == "inlineStr":
                        value = "".join(t.text or "" for t in cell.iter(f"{XLSX}t"))
                    else:
                        raw = cell.findtext(f"{XLSX}v") or ""
                        value = shared[int(raw)] if kind == "s" and raw.isdigit() else raw
                        if kind != "s" and re.fullmatch(r"0?\.\d+", raw):
                            minutes = round(float(raw) * 1440)  # Excel keeps times as day parts
                            value = f"{minutes // 60:02d}:{minutes % 60:02d}"
                    cells[column] = value.strip()
                rows.append([cells.get(i, "") for i in range(1, max(cells, default=0) + 1)])
            tables.append(rows)
    return tables


def _csv_tables(data: bytes) -> list[list[list[str]]]:
    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    return [
        [
            [cell.strip() for cell in row]
            for row in csv.reader(io.StringIO(text), delimiter=delimiter)
        ]
    ]


def _station(name: str) -> tuple[str, str]:
    """ "Lek Lekby.odt" is the list for Lekby, with the signature Lek."""
    heading = Path(name).stem
    match = re.fullmatch(r"([\wØøÆæÅåÄäÖö]{1,12}) (.+)", heading)
    return (match[2], match[1]) if match else (heading, "")


def parse_days(text: str) -> set[int] | None:
    """Dagl, M-O, To-L or Ti,O as weekdays 0–6; None when the text is not days."""
    value = text.strip().casefold().replace("–", "-").replace("—", "-")
    if value in {"", "dagl", "dagligen", "daily", "alla"}:
        return set(range(7))
    result: set[int] = set()
    for part in re.split(r"[,;/ ]+", value):
        ends = [p.strip() for p in part.split("-") if p.strip()]
        if not 1 <= len(ends) <= 2 or any(end not in DAYS for end in ends):
            return None
        start, end = DAYS[ends[0]], DAYS[ends[-1]]
        result.update((start + i) % 7 for i in range((end - start) % 7 + 1))
    return result or None


def _time(text: str) -> str | None:
    match = TIME.match(text.strip())
    if not match:
        return None
    hour, minute = int(match[1]), int(match[2])
    return f"{hour % 24:02d}:{minute:02d}"


def _rows(name: str, tables: list[list[list[str]]], found: Lists) -> None:
    station, code = _station(name)
    read = False
    for table in tables:
        if not table or len(table[0]) < 7:
            continue
        if not all(header_key(v) in allowed for v, allowed in zip(table[0], HEADER, strict=False)):
            continue
        read = True
        for index, cells in enumerate(table[1:], 2):
            if not any(cells):
                continue
            cells = [*cells, *[""] * (14 - len(cells))]
            if [header_key(c) for c in cells[:2]] == ["tåg", "dagar"]:
                continue  # the header again on a new page
            label = " ".join(cells[0].split())
            number = re.fullmatch(r"(.*?)\s*(\d+)", label)
            days = parse_days(cells[1])
            arrival, departure = _time(cells[3]), _time(cells[5])
            where = f"{name}, rad {index}"
            if not number or days is None:
                found.left_out.append(f"{where}: tåget eller dagarna går inte att läsa.")
                continue
            if arrival is None and departure is None:
                found.left_out.append(f"{where}: {label} har ingen tid (växling?).")
                continue
            track = cells[2].strip()
            remote = re.fullmatch(r"([^\W\d][\w]*)\s+(\S+)", track)
            note = cells[13].casefold() if len(cells) > 13 else ""
            found.rows.setdefault(name, []).append(
                Row(
                    station=station,
                    code=code,
                    document=name,
                    row=index,
                    label=label,
                    number=number[2],
                    days=days,
                    track=remote[2] if remote else track,
                    arrival=arrival,
                    departure=departure,
                    origin=cells[4].strip(),
                    destination=cells[6].strip(),
                    stops=not any(s in note for s in NO_STOP),
                    remote=remote[1] if remote else None,
                )
            )
            if sum(len(rows) for rows in found.rows.values()) > MAX_ROWS:
                raise ListError("Stationslistorna har fler än 20 000 rader.")
    if not read:
        found.left_out.append(f"{name}: ingen stationslista med Tåg, Dagar, Spår, Ank och Avg.")


def read(data: bytes, name: str) -> Lists:
    """The station lists in the file: one ODT, a ZIP of ODT lists, Excel or CSV."""
    if len(data) > MAX_BYTES:
        raise ListError("Filen är större än 20 MB.")
    suffix = Path(name).suffix.casefold()
    found = Lists()
    try:
        if suffix == ".odt":
            _rows(name, _odt_tables(data), found)
        elif suffix == ".zip":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members = _members(archive)
                lists = [m for m in members if member_name(m).casefold().endswith(".odt")]
                if not lists:
                    raise ListError("ZIP-filen har inga stationslistor i ODT.")
                for item in lists:
                    _rows(Path(member_name(item)).name, _odt_tables(archive.read(item)), found)
                for item in members:
                    if item not in lists:
                        found.left_out.append(f"{member_name(item)}: inte en stationslista i ODT.")
        elif suffix == ".xlsx":
            _rows(name, _xlsx_tables(data), found)
        elif suffix == ".csv":
            _rows(name, _csv_tables(data), found)
        else:
            raise ListError("Filen är inte stationslistor i ODT, ZIP, Excel eller CSV.")
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as error:
        raise ListError(f"Stationslistan gick inte att läsa: {error}.") from error
    if not found.rows:
        raise ListError("Ingen stationslista gick att läsa. " + " ".join(found.left_out[:3]))
    return found


# --- The verdict per list against the plan (IMPORT-27) -------------------------------------------


def _merged(rows: list[Row]) -> list[Row]:
    """A stop printed on two rows, the arrival and the departure, is one stop."""
    seen: dict[tuple[object, ...], Row] = {}
    for row in rows:
        key = (row.remote, row.label, frozenset(row.days), row.track, row.arrival, row.departure)
        if key not in seen:
            seen[key] = row
    return list(seen.values())


def verdicts(found: Lists, plan: MeetPackage) -> list[ListVerdict]:
    """Each list against the plan, row by row: the train with the same number on the same
    days at the place, with the same times and the same track. Calls in the plan that the
    list does not have are differences too."""
    by_code = {p.code.casefold(): p for p in plan.places}
    by_name = {p.name.casefold(): p for p in plan.places}
    by_id = {p.id: p for p in plan.places}
    trains: dict[str, list[Train]] = defaultdict(list)
    for train in plan.trains:
        trains[train.number].append(train)
    out: list[ListVerdict] = []
    for document, rows in sorted(found.rows.items()):
        first = rows[0]
        place = by_code.get(first.code.casefold()) or by_name.get(first.station.casefold())
        if place is None:
            out.append(
                ListVerdict(
                    document=document,
                    place=None,
                    rows=len(rows),
                    agreeing=0,
                    differences=[f"{first.station} finns inte i planen."],
                )
            )
            continue
        differences: list[str] = []
        agreeing = 0
        matched: set[str] = set()
        merged = _merged(rows)
        for row in merged:
            at = place
            if row.remote:
                at = by_code.get(row.remote.casefold(), place)
            candidates = [
                (train, call)
                for train in trains.get(row.number, [])
                if row.days <= {WEEK.index(day) for day in train.days}
                for call in train.calls
                if call.place == at.id
            ]
            exact = [
                (train, call)
                for train, call in candidates
                if (call.arrival or call.departure) == (row.arrival or row.departure)
                and (call.departure or call.arrival) == (row.departure or row.arrival)
            ]
            if not candidates:
                differences.append(f"Tåg {row.number} vid {at.name} finns inte i planen.")
                continue
            if not exact:
                train, call = candidates[0]
                differences.append(
                    f"Tåg {row.number} vid {at.name}: {_times(row.arrival, row.departure)} i "
                    f"listan, {_times(call.arrival, call.departure)} i planen."
                )
                continue
            train, call = exact[0]
            matched.add(call.id)
            if row.track and call.track and row.track != call.track:
                differences.append(
                    f"Tåg {row.number} vid {at.name}: spår {row.track} i listan, "
                    f"{call.track} i planen."
                )
                continue
            agreeing += 1
        covered = {place.id} | {
            by_code[r.remote.casefold()].id
            for r in merged
            if r.remote and r.remote.casefold() in by_code
        }
        listed_days = set().union(*(r.days for r in merged)) if merged else set()
        for train in plan.trains:
            if not {WEEK.index(day) for day in train.days} & listed_days:
                continue
            for call in train.calls:
                if (
                    call.place in covered
                    and call.id not in matched
                    and (call.arrival or call.departure)
                ):
                    if any(r.number == train.number for r in merged):
                        continue  # said above, with its times
                    differences.append(
                        f"Tåg {train.number} vid {by_id[call.place].name} finns i planen men "
                        "inte i listan."
                    )
        out.append(
            ListVerdict(
                document=document,
                place=place.id,
                rows=len(merged),
                agreeing=agreeing,
                differences=list(dict.fromkeys(differences)),
            )
        )
    return out


def _times(arrival: str | None, departure: str | None) -> str:
    if arrival and departure and arrival != departure:
        return f"{arrival}–{departure}"
    return arrival or departure or "ingen tid"


def check(data: bytes, name: str, *, plan: MeetPackage, source: Source) -> ImportResult:
    """The lists as the check of the plan: a verdict per list; the draft does not change."""
    found = read(data, name)
    judged = verdicts(found, plan)
    agreeing = sum(1 for v in judged if not v.differences)
    notes = [f"{agreeing} av {len(judged)} stationslistor stämmer med planeringsfilen rad för rad."]
    return ImportResult(
        package=plan,
        report=ImportReport(
            source=source.id,
            level=LEVEL,
            notes=notes,
            left_out=list(dict.fromkeys(found.left_out)),
            verdicts=judged,
        ),
        checks_only=True,
    )
