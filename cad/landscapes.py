"""Landskapet's service (#89 del d1, CAD-04, CAD-08, CAD-17, CAD-33): a module version's landscape
in the database, made, painted, saved and approved. The cells and the clustering are in
cad/landskap.py.

The landscape belongs to the module version (CAD-08). Gör landskapet, Spara and Godkänn
landskapet with changes each make a new version of the module, with the same name, measures,
gables, track plan and drawing as the newest, and the landscape in module_landscape; a later
version keeps the landscape until a new one is saved. As in Ritningen, the painting is a change
set replayed on the newest version for every call, and refused with 409 when someone saved in
between. The landscape is a proposal (orange) until the version that shows it is approved:
Godkänn landskapet approves it as the module's Godkänn does, and is refused the same way while
the track plan has open Att kolla items.

Whoever sees the module sees its landscape; only those who may change it make and paint it
(CAD-21). Everything is code on CAD's server: free (CAD-18).
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import cv2
import numpy as np
from psycopg import Connection
from psycopg.rows import DictRow

from cad import checks, geometry, landskap
from cad.db import Database
from cad.errors import forbidden, invalid, not_found
from cad.library import Modules, Who, changed
from cad.store import Store, StoreFailed
from contracts.cad import (
    DrawingState,
    Landscape,
    LandscapeArea,
    LandscapeEdit,
    LandscapeMake,
    LandscapeMethod,
    LandscapeStatus,
    Module,
    ModuleApproval,
    ModuleStatus,
    PhotoLayer,
    SurfaceTotal,
)
from contracts.station_model import Point

LOGGER = logging.getLogger("cad.landskap")


@dataclass
class Work:
    """A version's landscape on the grid of its board: the cells, the board, the track bed."""

    module: Module
    grid: landskap.Grid
    board: landskap.Mask
    bed: landskap.Mask
    distance: landskap.Floats
    labels: landskap.Labels | None
    stored: dict[str, Any] | None

    @classmethod
    def of(cls, module: Module, stored: dict[str, Any] | None) -> Work:
        track1 = geometry.track1_of(module.gables[0].tracks)
        outline = geometry.outline(module.shape, track1)
        grid = landskap.Grid.over(outline)
        board = landskap.board(grid, outline)
        distance = landskap.track_distance(grid, module.graph)
        bed = landskap.track_bed(distance, module.scale, grid.cell)
        labels = None
        if stored is not None:
            old = landskap.Grid(
                float(stored["x0"]),
                float(stored["y0"]),
                float(stored["cell"]),
                int(stored["width"]),
                int(stored["height"]),
            )
            labels = landskap.regrid(landskap.decode(bytes(stored["cells"]), old), old, grid)
        return cls(module, grid, board, bed, distance, labels, stored)


@dataclass(frozen=True)
class Shown:
    """A landscape as the exports draw it."""

    areas: list[LandscapeArea]
    track_bed: list[list[Point]]
    totals: list[SurfaceTotal]


def _what_was_painted(edit: LandscapeEdit) -> str:
    counts: Counter[str] = Counter(op.op for op in edit.operations)
    parts = []
    for op, one, many in (
        ("paint", "ett drag målat", "drag målade"),
        ("erase", "ett drag suddat", "drag suddade"),
        ("fill", "en yta fylld", "ytor fyllda"),
    ):
        if counts[op] == 1:
            parts.append(one)
        elif counts[op]:
            parts.append(f"{counts[op]} {many}")
    return "landskapet ändrat" + (f" ({', '.join(parts)})" if parts else "")


class Landscapes:
    def __init__(
        self,
        db: Database,
        store: Store,
        modules: Modules,
        models: Sequence[landskap.SurfaceModel] = landskap.MODELS,
    ) -> None:
        self.db = db
        self.store = store
        self.modules = modules
        self.models = models

    # --- Reading ------------------------------------------------------------------------------

    @staticmethod
    def _stored(conn: Connection[DictRow], module: UUID, version: int) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM module_landscape WHERE module_id = %s AND version <= %s "
            "ORDER BY version DESC LIMIT 1",
            (module, version),
        ).fetchone()
        return dict(row) if row is not None else None

    def _work(self, module: Module) -> Work:
        with self.db.transaction() as conn:
            stored = self._stored(conn, module.id, module.version)
        return Work.of(module, stored)

    def _image(self, state: DrawingState, module: UUID) -> landskap.MeasuringImage | None:
        """The measuring image the version's track plan came from, if it is still kept."""
        if state.photo is None:
            return None
        with self.db.transaction() as conn:
            job = conn.execute(
                "SELECT result FROM photo_job WHERE id = %s AND module_id = %s",
                (state.photo, module),
            ).fetchone()
            kept = conn.execute(
                "SELECT key FROM photo_file WHERE job_id = %s AND kind = 'measure' "
                "AND removed_at IS NULL ORDER BY position LIMIT 1",
                (state.photo,),
            ).fetchone()
        found = (job["result"] or {}) if job is not None else {}
        grid = found.get("grid")
        if kept is None or not grid:
            return None
        try:
            data = self.store.get(str(kept["key"]))
        except StoreFailed:
            LOGGER.warning("Mätbilden kunde inte hämtas för landskapet.")
            return None
        pixels = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if pixels is None:
            return None
        frame = found.get("frame")
        return landskap.MeasuringImage(
            pixels=np.asarray(pixels, np.uint8),
            x0=float(grid[0]),
            y0=float(grid[1]),
            ppm=float(grid[2]),
            matrix=tuple(float(v) for v in frame) if frame else None,
        )

    def _answer(
        self, work: Work, labels: landskap.Labels | None, changed: bool = False
    ) -> Landscape:
        module = work.module
        stored = work.stored
        photo = (
            PhotoLayer(job=module.photo.job, url=module.photo.display_url, grid=module.photo.grid)
            if module.photo is not None
            else None
        )
        if stored is None or labels is None:
            return Landscape(
                module=module.id,
                version=module.version,
                latest=module.latest,
                status=LandscapeStatus.NONE,
                grid=work.grid.contract(),
                surfaces=landskap.surface_infos(),
                photo=photo,
                may_edit=module.may_edit,
                track_bed=landskap.bed_rings(work.grid, work.board, work.bed),
            )
        approved = module.status == ModuleStatus.APPROVED and not changed
        return Landscape(
            module=module.id,
            version=module.version,
            latest=module.latest,
            saved_in=int(stored["version"]),
            status=LandscapeStatus.APPROVED if approved else LandscapeStatus.PROPOSAL,
            method=LandscapeMethod(stored["method"]),
            made_by=str(stored["made_by"]),
            grid=work.grid.contract(),
            areas=landskap.areas(labels, work.grid, work.board, work.bed),
            track_bed=landskap.bed_rings(work.grid, work.board, work.bed),
            totals=landskap.totals(labels, work.board, work.bed, work.grid.cell),
            surfaces=landskap.surface_infos(),
            photo=photo,
            may_edit=module.may_edit,
            changed=changed,
        )

    def get(self, who: Who, module: UUID, version: int | None = None) -> Landscape:
        """Landskapet of a version, the newest without one."""
        found = self.modules.read(who, module, version)
        work = self._work(found)
        return self._answer(work, work.labels)

    def shown(self, module: Module) -> Shown | None:
        """The version's landscape for the exports, None without one. The module is already
        read with the person's rights."""
        work = self._work(module)
        if work.labels is None:
            return None
        return Shown(
            areas=landskap.areas(work.labels, work.grid, work.board, work.bed),
            track_bed=landskap.bed_rings(work.grid, work.board, work.bed),
            totals=landskap.totals(work.labels, work.board, work.bed, work.grid.cell),
        )

    # --- Changing -----------------------------------------------------------------------------

    def _newest(self, who: Who, module: UUID, base: int) -> Module:
        found = self.modules.read(who, module)
        if not found.may_edit:
            raise forbidden()
        if base != found.latest:
            raise changed()
        return found

    def _replayed(self, work: Work, edit: LandscapeEdit) -> tuple[landskap.Labels, bool]:
        if work.labels is None:
            raise invalid("Modulen har inget landskap än. Gör landskapet först.")
        labels = work.labels.copy()
        moved = False
        for op in edit.operations:
            try:
                moved = landskap.apply(labels, work.grid, work.board, work.bed, op) or moved
            except landskap.LandscapeError as error:
                raise invalid(str(error)) from error
        return labels, moved

    def preview(self, who: Who, module: UUID, edit: LandscapeEdit) -> Landscape:
        """The change set on the newest version; nothing is saved."""
        work = self._work(self._newest(who, module, edit.base))
        labels, moved = self._replayed(work, edit)
        return self._answer(work, labels, changed=moved)

    def make(self, who: Who, module: UUID, ask: LandscapeMake) -> Landscape:
        """Gör landskapet: from the measuring image with the first model that answers, or empty
        without a photo; a new version."""
        newest = self._newest(who, module, ask.base)
        work = Work.of(newest, None)
        image = self._image(newest.drawing, newest.id)
        try:
            made = landskap.make(
                work.grid, work.board, work.bed, work.distance, newest.scale, image, self.models
            )
        except ValueError as error:
            raise invalid(f"Landskapet gick inte att göra: {error}") from error
        text = (
            f"landskapet gjort ur mätbilden ({made.made_by})"
            if made.method != LandscapeMethod.HAND
            else "ett tomt landskap att måla"
        )
        self._save(
            who,
            newest,
            work.grid,
            made.labels,
            made.method,
            made.made_by,
            newest.drawing.photo if image is not None else None,
            text,
        )
        return self.get(who, module)

    def save(
        self, who: Who, module: UUID, edit: LandscapeEdit, *, approve: bool = False
    ) -> Landscape:
        """Spara: the change set as a new version. With approve, Godkänn landskapet: saved if it
        changes something, and the version approved; refused while the track plan has open Att
        kolla items."""
        newest = self._newest(who, module, edit.base)
        work = self._work(newest)
        labels, moved = self._replayed(work, edit)
        if approve:
            unanswered = checks.open_items(list(newest.checks))
            if unanswered:
                what = (
                    "en sak att kolla"
                    if len(unanswered) == 1
                    else (f"{len(unanswered)} saker att kolla")
                )
                raise invalid(f"Spårplanen har {what}. Svara på dem i Ritningen först.")
        elif not moved:
            raise invalid("Det finns inget att spara.")
        version = newest.latest
        if moved:
            stored = work.stored
            assert stored is not None
            version = self._save(
                who,
                newest,
                work.grid,
                labels,
                LandscapeMethod(stored["method"]),
                str(stored["made_by"]),
                stored["photo_job"],
                _what_was_painted(edit),
            )
        if approve and (moved or newest.status != ModuleStatus.APPROVED):
            self.modules.approve(who, module, ModuleApproval(version=version))
        return self.get(who, module)

    def _save(
        self,
        who: Who,
        newest: Module,
        grid: landskap.Grid,
        labels: landskap.Labels,
        method: LandscapeMethod,
        made_by: str,
        photo_job: UUID | None,
        text: str,
    ) -> int:
        """A new version of the module, a copy of the newest with the landscape. Its number."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT latest FROM module WHERE id = %s AND removed_at IS NULL FOR UPDATE",
                (newest.id,),
            ).fetchone()
            if row is None:
                raise not_found()
            latest = int(row["latest"])
            if latest != newest.latest:
                raise changed()
            version = latest + 1
            # The same name, measures, gables, track plan and drawing; this version split no ids.
            conn.execute(
                "INSERT INTO module_version (module_id, version, name, scale, shape, gables, "
                "graph, track_length, saved_by, saved_by_name, drawing) SELECT module_id, %s, "
                "name, scale, shape, gables, graph, track_length, %s, %s, "
                "jsonb_set(drawing, '{ids}', '[]'::jsonb) FROM module_version "
                "WHERE module_id = %s AND version = %s",
                (version, who.person, who.name, newest.id, latest),
            )
            conn.execute(
                "INSERT INTO module_landscape (module_id, version, method, made_by, photo_job, "
                "x0, y0, cell, width, height, cells) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s)",
                (
                    newest.id,
                    version,
                    method.value,
                    made_by,
                    photo_job,
                    grid.x0,
                    grid.y0,
                    grid.cell,
                    grid.width,
                    grid.height,
                    landskap.encode(labels),
                ),
            )
            conn.execute("UPDATE module SET latest = %s WHERE id = %s", (version, newest.id))
            conn.execute(
                "INSERT INTO module_event (module_id, kind, version, by_name, text) "
                "VALUES (%s, 'saved', %s, %s, %s)",
                (newest.id, version, who.name, f"Version {version}: {text}"),
            )
        LOGGER.info("Landskapet sparat i version %d (%s).", version, method.value)
        return version
