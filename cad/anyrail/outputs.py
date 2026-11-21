"""Vad importen ger (trainmeet-cad-anyrail-import.md, 5; ANYRAIL-05, ANYRAIL-07): the exports of an
interpreted AnyRail file, before and after the modules are made.

- DXF of the whole station: every proposed module where the drawing has it, with its tracks as
  real LINE and ARC and its gable measures as text (cad/dxf.py, as an assembly's DXF), and
  AnyRail's own thin lines on the layer ANYRAIL-RITNING, not read (rule 1).
- DXF per module, in the module's own mm: gable A at Kant 1 at the origin, the front edge along
  x, never mirrored (cad/dxf.py, as Exportera's).
- Gavelprofiler (CSV): each joint with track, and each gable at the line, as the prototype's
  file: skarv;skarvlangd_mm;spar_mm_fran_bakkant_kant1;snett_grader.
- Växellista (CSV): nr;anyrail_id;typ;radie_mm;modul;antagen;x_mm;y_mm, numbered from the west,
  with AnyRail's id kept as the origin.

The CSV files are UTF-8 with a byte order mark (as the prototype's, so that a spreadsheet reads
å, ä and ö), separated by semicolons, with a decimal point; a value a spreadsheet would read as a
formula gets a ' first (cad/export.py).
"""

from __future__ import annotations

import io
import re
import unicodedata
from typing import Final

from cad import dxf
from cad.anyrail.interpret import Result
from cad.export import _cell
from contracts.station_model import Point

DRAWING: Final = dxf.Layer("ANYRAIL-RITNING", 8)
"""AnyRail's own thin lines: module edges, buildings, arrows. Not read."""
SIDES: Final = {"left": "vänster", "right": "höger", "y": "Y"}
GABLE_COLUMNS: Final = ("skarv", "skarvlangd_mm", "spar_mm_fran_bakkant_kant1", "snett_grader")
SWITCH_COLUMNS: Final = (
    "nr",
    "anyrail_id",
    "typ",
    "radie_mm",
    "modul",
    "antagen",
    "x_mm",
    "y_mm",
)


def stem(name: str) -> str:
    """A file name's stem as a safe file name: letters, digits and dashes."""
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    base = base.rsplit(".", 1)[0] if "." in base else base
    plain = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    found = re.sub(r"[^A-Za-z0-9]+", "-", plain).strip("-").lower()
    return found[:60] or "anyrail"


def _csv(header: tuple[str, ...], rows: list[list[object]]) -> bytes:
    out = io.StringIO()
    out.write("\ufeff")
    table: list[list[object]] = [list(header), *rows]
    for row in table:
        out.write(";".join(_cell(v).replace(";", ",") for v in row) + "\r\n")
    return out.getvalue().encode("utf-8")


def gable_csv(result: Result) -> bytes:
    rows: list[list[object]] = [
        [
            row.joint,
            f"{row.length:.0f}",
            " ".join(f"{t:.0f}" for t in row.tracks),
            " ".join(f"{a:.1f}" for a in row.angles),
        ]
        for row in result.profiles
    ]
    return _csv(GABLE_COLUMNS, rows)


def switch_csv(result: Result) -> bytes:
    numbers = {m.key: m.number for m in result.modules}
    rows: list[list[object]] = []
    for sw in result.switches:
        rows.append(
            [
                sw.number,
                sw.anyrail or "",
                SIDES[sw.side],
                f"{sw.radius:.0f}" if sw.radius else "",
                numbers.get(sw.module or "", ""),
                "ja" if sw.assumed else "nej",
                f"{sw.at[0]:.0f}",
                f"{sw.at[1]:.0f}",
            ]
        )
    return _csv(SWITCH_COLUMNS, rows)


def station_dxf(result: Result) -> bytes:
    """The whole station in the drawing's mm, each module where AnyRail has it."""
    doc = dxf.Dxf()
    for line in result.drawing:
        _polyline(doc, line)
    for proposal, module in zip(result.proposals, result.modules, strict=True):
        dxf.draw_module(
            doc,
            module.shape,
            module.gables,
            module.graph,
            result.scale,
            place=dxf.Placement(at=module.at, angle=module.angle),
            sheet=dxf.ModuleSheet(title=f"{proposal.number} · ur AnyRail", draft=True),
        )
    return doc.write()


def module_dxf(result: Result, key: str) -> bytes | None:
    """One module in its own mm, or None when the file has no such module."""
    for proposal, module in zip(result.proposals, result.modules, strict=True):
        if module.key != key:
            continue
        doc = dxf.Dxf()
        dxf.draw_module(
            doc,
            module.shape,
            module.gables,
            module.graph,
            result.scale,
            sheet=dxf.ModuleSheet(title=f"{proposal.number} · ur AnyRail", draft=True),
        )
        return doc.write()
    return None


def _polyline(doc: dxf.Dxf, points: list[Point]) -> None:
    if len(points) == 2:
        doc.line(DRAWING, points[0], points[1])
    elif len(points) > 2:
        doc.polyline(DRAWING, points)
