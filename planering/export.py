"""Exporten (PLAN-07, F25): the timetable out of Planering, for people.

- Stationstidtabeller: one page per place where trains stop or pass, to print or save as PDF
  from the browser. Every text is escaped; the page has no script.
- Hela tidtabellen and köruppdragen: CSV for a spreadsheet, with semicolons and a byte order
  mark so that Excel in Swedish reads å, ä and ö.
- Paketets JSON: the package as Drift reads it.
- Underlaget: the sources as they came, in a ZIP.

The graph is saved as SVG from Graf in the browser.
"""

from __future__ import annotations

import csv
import html
import io
import re
import unicodedata
import zipfile
from collections.abc import Iterable
from typing import Final

from contracts.meet import Call, MeetPackage, PlaceKind, Train

DAY_NAMES: Final = {
    "mon": "Mån",
    "tue": "Tis",
    "wed": "Ons",
    "thu": "Tor",
    "fri": "Fre",
    "sat": "Lör",
    "sun": "Sön",
}
WEEK: Final = list(DAY_NAMES)


def days(listed: Iterable[str]) -> str:
    """Dagl, a run such as Mån–Fre, or the days one by one."""
    given = [str(d) for d in listed]
    if len(given) == 7:
        return "Dagl"
    indexes = sorted(WEEK.index(d) for d in given)
    if len(indexes) > 2 and indexes == list(range(indexes[0], indexes[-1] + 1)):
        return f"{DAY_NAMES[WEEK[indexes[0]]]}–{DAY_NAMES[WEEK[indexes[-1]]]}"
    return ", ".join(DAY_NAMES[WEEK[i]] for i in indexes)


def filename(meet: str, what: str, suffix: str, version: int | None) -> str:
    """varnamo-moduldagar-v2-stationstidtabeller.html: plain letters, safe in any system."""
    plain = unicodedata.normalize("NFKD", meet).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-") or "traff"
    part = f"v{version}" if version is not None else "utkast"
    return f"{slug}-{part}-{what}.{suffix}"


def _csv(rows: list[list[str]]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerows(rows)
    return ("﻿" + out.getvalue()).encode("utf-8")


def _sort_time(call: Call) -> str:
    return call.departure or call.arrival or "99:99"


def timetable_csv(package: MeetPackage) -> bytes:
    """Hela tidtabellen: one row per call, train by train in the order they run."""
    names = {p.id: p.name for p in package.places}
    rows = [
        [
            "Tåg",
            "Tågslag",
            "Bolag",
            "Dagar",
            "Nr",
            "Driftplats",
            "Ankomst",
            "Avgång",
            "Dygn",
            "Spår",
            "Uppehåll",
            "Anmärkning",
        ]
    ]
    for train in sorted(package.trains, key=lambda t: (_sort_time(t.calls[0]), t.number)):
        for index, call in enumerate(train.calls, start=1):
            rows.append(
                [
                    train.number,
                    train.train_type or "",
                    train.operator or "",
                    days(train.days),
                    str(index),
                    names.get(call.place, call.place),
                    call.arrival or "",
                    call.departure or "",
                    f"+{call.day_offset}" if call.day_offset else "",
                    call.track or "",
                    "ja" if call.stops else "passerar",
                    "; ".join(n for n in (train.note, call.note) if n),
                ]
            )
    return _csv(rows)


def duties_csv(package: MeetPackage) -> bytes:
    """Köruppdragen: each leg of each duty, from where and when to where and when."""
    names = {p.id: p.name for p in package.places}
    trains = {t.id: t for t in package.trains}
    calls = {c.id: c for t in package.trains for c in t.calls}
    rows = [["Köruppdrag", "Del", "Tåg", "Dagar", "Från", "Avgång", "Till", "Ankomst"]]
    for duty in package.duties:
        for index, leg in enumerate(duty.legs, start=1):
            train = trains.get(leg.train)
            start, end = calls.get(leg.from_call), calls.get(leg.to_call)
            rows.append(
                [
                    duty.name,
                    str(index),
                    train.number if train else leg.train,
                    days(train.days) if train else "",
                    names.get(start.place, start.place) if start else "",
                    (start.departure or start.arrival or "") if start else "",
                    names.get(end.place, end.place) if end else "",
                    (end.arrival or end.departure or "") if end else "",
                ]
            )
    return _csv(rows)


_PAGE: Final = """<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font: 14px/1.4 system-ui, sans-serif; color: #111; margin: 24px; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  h2 {{ font-size: 17px; margin: 0 0 8px; }}
  p {{ margin: 0 0 16px; color: #444; }}
  section {{ break-after: page; margin-bottom: 32px; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: 4px 8px; border-bottom: 1px solid #ccc; }}
  th {{ font-size: 12px; text-transform: uppercase; color: #444; }}
  td.tid {{ font-variant-numeric: tabular-nums; font-weight: 600; }}
  .liten {{ color: #555; font-size: 12px; }}
  @media print {{ body {{ margin: 0; }} }}
</style>
</head>
<body>
<main>
<h1>{title}</h1>
<p>{subtitle}</p>
{sections}
</main>
</body>
</html>
"""


def _row(train: Train, call: Call, names: dict[str, str]) -> tuple[str, str]:
    first, last = train.calls[0], train.calls[-1]
    passing = not call.stops
    origin = names.get(first.place, first.place) if call is not first else "–"
    cells = [
        f"<td><b>{html.escape(train.number)}</b></td>",
        f"<td>{html.escape(origin)}</td>",
        f'<td class="tid">{html.escape(call.arrival or "")}</td>',
        f'<td class="tid">{html.escape(call.departure or "")}</td>',
        f"<td>{html.escape(names.get(last.place, last.place)) if call is not last else '–'}</td>",
        f"<td>{html.escape(call.track or '–')}</td>",
        f"<td>{html.escape(days(train.days))}</td>",
        "<td>"
        + html.escape(
            "; ".join(n for n in ("passerar" if passing else None, train.note, call.note) if n)
        )
        + "</td>",
    ]
    return _sort_time(call), "<tr>" + "".join(cells) + "</tr>"


def station_timetables(package: MeetPackage, title: str, subtitle: str) -> bytes:
    """One page per place with trains, the trains in time order."""
    names = {p.id: p.name for p in package.places}
    by_place: dict[str, list[tuple[str, str]]] = {p.id: [] for p in package.places}
    for train in package.trains:
        for call in train.calls:
            if call.place in by_place:
                by_place[call.place].append(_row(train, call, names))
    head = (
        "<thead><tr><th>Tåg</th><th>Från</th><th>Ank</th><th>Avg</th><th>Till</th>"
        "<th>Spår</th><th>Dagar</th><th>Anmärkning</th></tr></thead>"
    )
    sections = []
    for place in package.places:
        rows = by_place[place.id]
        if not rows:
            continue
        rows.sort(key=lambda row: row[0])
        kind = " · industri eller hållplats" if place.kind == PlaceKind.HALT else ""
        phone = f" · telefon {html.escape(place.phone)}" if place.phone else ""
        sections.append(
            f"<section><h2>{html.escape(place.name)}</h2>"
            f'<p class="liten">{html.escape(place.code)}{kind}{phone} · {len(rows)} tåg</p>'
            f"<table>{head}<tbody>{''.join(r for _, r in rows)}</tbody></table></section>"
        )
    page = _PAGE.format(
        title=html.escape(title), subtitle=html.escape(subtitle), sections="\n".join(sections)
    )
    return page.encode("utf-8")


def sources_zip(files: Iterable[tuple[str, bytes]]) -> bytes:
    """The sources as they came, with fixed dates so that the same files give the same ZIP."""
    stream = io.BytesIO()
    seen: set[str] = set()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in files:
            base = name.replace("/", "_").replace("\\", "_") or "underlag"
            unique, n = base, 1
            while unique in seen:
                n += 1
                unique = f"{n}-{base}"
            seen.add(unique)
            archive.writestr(zipfile.ZipInfo(unique, date_time=(1980, 1, 1, 0, 0, 0)), body)
    return stream.getvalue()
