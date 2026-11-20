"""Exportera (#89 del d1, CAD-07, CAD-24): a module version as files, free, for whoever sees it.

- FREMO-ritning: the module sheet, SVG (cad/sheets.py), printed by the browser.
- Moduldatabasen: the module as a record (ModuleRecord, format trainmeet.cad.moduldatabas/1),
  JSON, or CSV with a header row and the record's row in RECORD_COLUMNS' order (comma-separated,
  UTF-8, decimal point, a gable's tracks joined with /, empty for nothing).
- MMM: each gable's tracks from Kant 1, the distance to the track before, MMM's position for the
  track (140, + 57 for a double track, 140/197/283/340 for four tracks, CAD15) and the deviation,
  as CSV. The MMM forms themselves are planned (Öppet in the CAD views).
- DXF: R12 in mm with the track centres as real LINE and ARC (cad/dxf.py); the rails and the
  landscape on their own layers if asked.
- Utskrift: the module with its landscape, SVG, printed by the browser as the hub prints.

A module with an approved version exports that one unless another is asked for; a draft exports
with Utkast in every file: UTKAST over the drawings and the sheets, and the status draft in the
records. A CSV value that a spreadsheet would read as a formula gets a ' first.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote
from uuid import UUID

from cad import dxf, geometry, profiles, sheets
from cad.errors import Refused
from cad.landscapes import Landscapes, Shown
from cad.library import Modules, Who
from contracts.cad import (
    EXPORT_FILES,
    RECORD_COLUMNS,
    Curve,
    ExportFile,
    ExportKind,
    ExportVersion,
    Gable,
    MmmGable,
    MmmTrack,
    Module,
    ModuleExport,
    ModuleRecord,
    ModuleStatus,
    Norm,
    ProblemCode,
    RecordGable,
    Scale,
    Trapezoid,
)
from contracts.station_model import NodeType

API = "/api/cad/1"
MMM_DEVIATION = 2.0
"""A gable track farther than this from MMM's position is shown (bildkedjan step 13)."""
NAMES = {
    "fremo.svg": "FREMO-ritning (SVG)",
    "utskrift.svg": "Utskrift (SVG)",
    "moduldatabas.json": "Moduldatabasen (JSON)",
    "moduldatabas.csv": "Moduldatabasen (CSV)",
    "mmm.csv": "MMM-måtten (CSV)",
    "modul.dxf": "DXF",
}


def _mmm_positions() -> dict[int, list[float]]:
    """MMM's positions by the number of tracks, from the MMM profiles (cad/profiles.py)."""
    found: dict[int, list[float]] = {}
    for profile in profiles.SEEDED:
        if profile.norm == Norm.MMM and profile.scale == Scale.H0:
            known = profiles.positions(profile)
            if all(p is not None for p in known):
                found[profile.tracks] = [float(p) for p in known if p is not None]
    return found


MMM_POSITIONS = _mmm_positions()


def file_stem(module: Module) -> str:
    """M-001-exempelstation-v3: ASCII, for every file system."""
    plain = unicodedata.normalize("NFKD", module.name).encode("ascii", "ignore").decode()
    words = re.sub(r"[^A-Za-z0-9]+", "-", plain).strip("-").lower()[:40]
    return (
        f"{module.number}-{words}-v{module.version}"
        if words
        else f"{module.number}-v{module.version}"
    )


def disposition(name: str, attachment: bool = True) -> str:
    kind = "attachment" if attachment else "inline"
    ascii_name = name.encode("ascii", "replace").decode().replace('"', "")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


# --- Moduldatabasen ----------------------------------------------------------------------


def record(module: Module, landscape: bool) -> ModuleRecord:
    shape = module.shape
    nodes = module.graph.nodes
    return ModuleRecord(
        id=module.id,
        number=module.number,
        name=module.name,
        owner=module.owner.name,
        scale=module.scale,
        shape=shape.kind,
        length=round(geometry.length_of(shape), 3),
        radius=shape.radius if isinstance(shape, Curve) else None,
        angle=shape.angle if isinstance(shape, Curve) else None,
        offset=shape.offset if isinstance(shape, Trapezoid) else None,
        gables=[
            RecordGable(
                end=g.end,
                norm=g.norm,
                profile=g.profile,
                label=g.label,
                width=geometry.width_at(shape, g.end.value),
                tracks=list(g.tracks),
            )
            for g in module.gables
        ],
        track_length=module.track_length,
        switches=len(module.graph.switches),
        crossings=sum(1 for n in nodes if n.type == NodeType.CROSSING),
        landscape=landscape,
        version=module.version,
        status=module.status,
        approved_at=module.approved_at if module.status == ModuleStatus.APPROVED else None,
    )


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}" if abs(value) < 1e15 else str(value)
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _csv(header: tuple[str, ...] | list[str], rows: list[list[object]]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return out.getvalue().encode("utf-8")


def record_csv(found: ModuleRecord) -> bytes:
    a, b = found.gables
    values: dict[str, object] = {
        **found.model_dump(mode="json", exclude={"gables"}),
        "length": found.length,
        "radius": found.radius,
        "angle": found.angle,
        "offset": found.offset,
        "track_length": found.track_length,
    }
    for prefix, gable in (("gable_a", a), ("gable_b", b)):
        values[f"{prefix}_norm"] = gable.norm.value if gable.norm else None
        values[f"{prefix}_profile"] = gable.profile
        values[f"{prefix}_width"] = gable.width
        values[f"{prefix}_tracks"] = "/".join(f"{t:g}" for t in gable.tracks)
    return _csv(list(RECORD_COLUMNS), [[values[c] for c in RECORD_COLUMNS]])


# --- MMM ---------------------------------------------------------------------------------


def mmm(module: Module) -> list[MmmGable]:
    """Each gable's tracks as MMM measures them, with MMM's positions where the gable is MMM."""
    found: list[MmmGable] = []
    for gable in module.gables:
        norm_positions = MMM_POSITIONS.get(len(gable.tracks)) if gable.norm == Norm.MMM else None
        tracks: list[MmmTrack] = []
        for i, at in enumerate(gable.tracks):
            target = norm_positions[i] if norm_positions else None
            tracks.append(
                MmmTrack(
                    track=i + 1,
                    from_kant1=at,
                    spacing=round(at - gable.tracks[i - 1], 2) if i else None,
                    mmm=target,
                    deviation=round(at - target, 2) if target is not None else None,
                )
            )
        found.append(
            MmmGable(
                end=gable.end,
                norm=gable.norm,
                label=gable.label,
                width=geometry.width_at(module.shape, gable.end.value),
                tracks=tracks,
            )
        )
    return found


MMM_COLUMNS = (
    "gavel",
    "norm",
    "profil",
    "gavelbredd_mm",
    "spar",
    "fran_kant1_mm",
    "avstand_till_forra_mm",
    "mmm_mm",
    "avvikelse_mm",
    "status",
)


def mmm_csv(module: Module) -> bytes:
    rows: list[list[object]] = []
    status = "godkänd" if module.status == ModuleStatus.APPROVED else "utkast"
    for gable in mmm(module):
        for track in gable.tracks:
            rows.append(
                [
                    gable.end.value,
                    gable.norm.value if gable.norm else None,
                    gable.label,
                    gable.width,
                    track.track,
                    track.from_kant1,
                    track.spacing,
                    track.mmm,
                    track.deviation,
                    status,
                ]
            )
    return _csv(MMM_COLUMNS, rows)


# --- DXF ---------------------------------------------------------------------------------


def module_dxf(module: Module, shown: Shown | None, *, rails: bool = False) -> bytes:
    """The module on its own, in mm: dxf.draw_module with its title and, on a draft, UTKAST."""
    doc = dxf.Dxf()
    draft = module.status != ModuleStatus.APPROVED
    dxf.draw_module(
        doc,
        module.shape,
        _gables(module),
        module.graph,
        module.scale,
        sheet=dxf.ModuleSheet(
            title=f"{module.number} {module.name} · version {module.version}"
            + (" · utkast" if draft else ""),
            draft=draft,
            rails=rails,
            landscape=shown.areas if shown else (),
            track_bed=shown.track_bed if shown else (),
        ),
    )
    return doc.write()


def _gables(module: Module) -> list[Gable]:
    return [
        Gable(end=g.end, norm=g.norm, profile=g.profile, tracks=list(g.tracks))
        for g in module.gables
    ]


# --- The service -------------------------------------------------------------------------


@dataclass(frozen=True)
class File:
    data: bytes
    media_type: str
    name: str
    attachment: bool


class Exports:
    def __init__(self, modules: Modules, landscapes: Landscapes) -> None:
        self.modules = modules
        self.landscapes = landscapes

    def _chosen(self, who: Who, module: UUID, version: int | None) -> tuple[Module, Module]:
        """The version to export, and the newest: the approved one unless asked otherwise."""
        newest = self.modules.read(who, module)
        wanted = version or newest.approved_version or newest.latest
        if wanted == newest.version:
            return newest, newest
        if wanted < 1 or wanted > newest.latest:
            raise Refused(404, ProblemCode.NOT_FOUND, "Versionen finns inte.")
        return self.modules.read(who, module, wanted), newest

    def summary(self, who: Who, module: UUID, version: int | None = None) -> ModuleExport:
        chosen, newest = self._chosen(who, module, version)
        shown = self.landscapes.shown(chosen)
        versions: list[ExportVersion] = []
        if newest.approved_version is not None:
            versions.append(
                ExportVersion(
                    version=newest.approved_version,
                    status=ModuleStatus.APPROVED,
                    label=f"Godkänd version {newest.approved_version}",
                )
            )
        if newest.approved_version != newest.latest:
            versions.append(
                ExportVersion(
                    version=newest.latest,
                    status=ModuleStatus.DRAFT,
                    label=f"Utkastet, version {newest.latest}",
                )
            )
        if all(v.version != chosen.version for v in versions):
            versions.append(
                ExportVersion(
                    version=chosen.version,
                    status=chosen.status,
                    label=f"Version {chosen.version}",
                )
            )
        stem = file_stem(chosen)
        files = [
            ExportFile(
                kind=kind,
                name=NAMES[name],
                file=f"{stem}-{name}" if name != "modul.dxf" else f"{stem}.dxf",
                url=f"{API}/modules/{chosen.id}/export/{chosen.version}/{name}",
                media_type=media,
            )
            for name, (kind, media) in EXPORT_FILES.items()
        ]
        return ModuleExport(
            module=chosen.id,
            number=chosen.number,
            name=chosen.name,
            version=chosen.version,
            status=chosen.status,
            versions=versions,
            files=files,
            record=record(chosen, shown is not None),
            mmm=mmm(chosen),
            landscape=shown is not None,
        )

    def file(
        self,
        who: Who,
        module: UUID,
        version: int,
        name: str,
        *,
        rails: bool = False,
        landscape: bool = True,
    ) -> File:
        if name not in EXPORT_FILES:
            raise Refused(404, ProblemCode.NOT_FOUND, "Den filen finns inte i exporten.")
        if version < 1:
            raise Refused(404, ProblemCode.NOT_FOUND, "Versionen finns inte.")
        chosen = self.modules.read(who, module, version)
        kind, media = EXPORT_FILES[name]
        stem = file_stem(chosen)
        wanted = kind in (ExportKind.DXF, ExportKind.PRINT, ExportKind.DATABASE)
        shown = self.landscapes.shown(chosen) if wanted else None
        if name == "modul.dxf":
            data = module_dxf(chosen, shown if landscape else None, rails=rails)
            return File(data, media, f"{stem}.dxf", True)
        if name == "fremo.svg":
            return File(sheets.fremo_sheet(chosen).encode(), media, f"{stem}-fremo.svg", False)
        if name == "utskrift.svg":
            drawn = (
                sheets.SheetLandscape(shown.areas, shown.track_bed, shown.totals) if shown else None
            )
            return File(
                sheets.print_sheet(chosen, drawn).encode(), media, f"{stem}-utskrift.svg", False
            )
        found = record(chosen, shown is not None)
        if name == "moduldatabas.json":
            text = json.dumps(found.model_dump(mode="json"), ensure_ascii=False, indent=2)
            return File((text + "\n").encode(), media, f"{stem}-moduldatabas.json", True)
        if name == "moduldatabas.csv":
            return File(record_csv(found), media, f"{stem}-moduldatabas.csv", True)
        return File(mmm_csv(chosen), media, f"{stem}-mmm.csv", True)
