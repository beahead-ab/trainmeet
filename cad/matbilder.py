"""Mätbilden i TKL:s Foto (#89 del d4, CAD-13, CAD-33, CAD8): the measuring images of the modules
in what Studio has, an assembly or a single module, at the versions it pins, with where each lies
in the source's mm, so that TKL's Foto skin can draw them under the tracks.

Who sees what is Till TKL Studio's (cad/assemblies.py), and so the library's (CAD-21): the
assembly or the single module as Studio's graph has it, and of an assembly only the modules the
person sees. A module without a photo, or whose measuring image is gone, is listed as missing
with the reason; Foto draws it as vectors.

The image is the measuring image's display copy, JPEG at 1 px per mm, as the photo chain keeps it
(cad/photos.py); a copy in another format is sent as JPEG. Its frame is worked out from the
measuring image's grid: pixel (0, 0)'s centre at (x0, y0) mm at MEASURE_PPM, the display copy
covering the same ground with fewer pixels, then the photo's own frame (PhotoGrid.matrix) when
it was read with another Kant 1 or gable A, then the module's place in the assembly (cad/
assembly.py's Pose). Everything is code on CAD's server: free (CAD-18).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import cv2
import numpy as np

from cad import geometry, switches
from cad.assemblies import Assemblies
from cad.db import Database
from cad.errors import Refused
from cad.library import SHAPE, Who
from cad.store import Store, StoreFailed
from contracts.cad import (
    Gable,
    ProblemCode,
    Scale,
    StudioImage,
    StudioImageFrame,
    StudioImageMissing,
    StudioImages,
    StudioSourceKind,
)
from contracts.station_model import Point

LOGGER = logging.getLogger("cad.matbilder")
JPEG_QUALITY = 85
"""The display copy's own quality, for a copy CAD has to make."""

Affine = tuple[float, float, float, float, float, float]
IDENTITY: Affine = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

NO_PHOTO = "Modulen är inte fotad i TrainMeet CAD; Foto ritar den som vektorer."
GONE = "Mätbilden finns inte kvar i TrainMeet CAD."
UNSEEN = "Du ser inte modulen längre."


# --- The frame, as pure functions ----------------------------------------------------------


def compose(a: Sequence[float], b: Sequence[float]) -> Affine:
    """a after b, both SVG's (a, b, c, d, e, f)."""
    return (
        a[0] * b[0] + a[2] * b[1],
        a[1] * b[0] + a[3] * b[1],
        a[0] * b[2] + a[2] * b[3],
        a[1] * b[2] + a[3] * b[3],
        a[0] * b[4] + a[2] * b[5] + a[4],
        a[1] * b[4] + a[3] * b[5] + a[5],
    )


def apply(m: Sequence[float], p: Point) -> Point:
    return (m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5])


def invert(m: Sequence[float]) -> Affine:
    det = m[0] * m[3] - m[1] * m[2]
    if abs(det) < 1e-12:
        raise ValueError("The matrix cannot be inverted.")
    a, b, c, d = m[3] / det, -m[1] / det, -m[2] / det, m[0] / det
    return (a, b, c, d, -(a * m[4] + c * m[5]), -(b * m[4] + d * m[5]))


def pose(at: Point, angle: float) -> Affine:
    """cad.assembly.Pose as a matrix: turned angle degrees counterclockwise on the screen (y
    down), then moved to at."""
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return (c, -s, s, c, at[0], at[1])


def _rounded(m: Sequence[float]) -> list[float]:
    return [round(v, 6) + 0.0 for v in m]


def frame_of(
    grid: Sequence[float], width: int, height: int, matrix: Sequence[float] | None
) -> StudioImageFrame:
    """The display copy's frame in the module. grid is the measuring image's, as the chain
    stores it: x0, y0 (pixel (0, 0)'s centre in mm), its pixels per mm, its width and height;
    the copy of width × height pixels covers the same ground. matrix takes the mm it was read in
    to the module's."""
    x0, y0, ppm, measured_w, measured_h = (float(v) for v in grid[:5])
    across = measured_w / ppm / width
    down = measured_h / ppm / height
    pixels: Affine = (across, 0.0, 0.0, down, x0 - 0.5 / ppm, y0 - 0.5 / ppm)
    whole = compose(matrix, pixels) if matrix else pixels
    origin = apply(invert(whole), (0.0, 0.0))
    return StudioImageFrame(
        width=width,
        height=height,
        mm_per_px=(round(across, 6), round(down, 6)),
        origin=(round(origin[0], 3), round(origin[1], 3)),
        matrix=_rounded(whole),
    )


# --- The service ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Placed:
    """A module of the source as Studio has it: its version, its place and its board."""

    module: UUID
    version: int
    title: str
    number: str | None
    name: str | None
    at: Point
    angle: float
    outline: list[Point]
    seen: bool


@dataclass(frozen=True)
class Found:
    """A version's display copy: its file and the frame worked out from its grid."""

    job: UUID
    key: str
    frame: StudioImageFrame


class Matbilder:
    def __init__(self, db: Database, store: Store, assemblies: Assemblies) -> None:
        self.db = db
        self.store = store
        self.assemblies = assemblies

    def _placed(
        self, who: Who, kind: StudioSourceKind, source: UUID
    ) -> tuple[int, Scale, list[Placed]]:
        """The source's revision, its scale and its modules, with Till TKL Studio's rights."""
        if kind == StudioSourceKind.ASSEMBLY:
            found = self.assemblies.read(who, source)
            placed = []
            for where, part in zip(found.modules, found.parts, strict=True):
                title = f"{part.number} {part.name}" if part.seen else "En modul du inte ser"
                placed.append(
                    Placed(
                        module=part.module,
                        version=part.version,
                        title=title,
                        number=part.number,
                        name=part.name,
                        at=where.at,
                        angle=where.angle,
                        outline=list(part.outline),
                        seen=part.seen,
                    )
                )
            return found.revision, found.scale, placed
        studio = self.assemblies.studio_graph(who, kind, source).source
        one = studio.modules[0]
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT shape, gables FROM module_version WHERE module_id = %s AND version = %s",
                (one.id, one.version),
            ).fetchone()
        assert row is not None, "Till TKL Studio found the version"
        gables = [Gable.model_validate(g) for g in row["gables"]]
        board = geometry.outline(
            SHAPE.validate_python(row["shape"]), geometry.track1_of(gables[0].tracks), steps=24
        )
        return (
            studio.revision,
            studio.scale,
            [
                Placed(
                    module=one.id,
                    version=one.version,
                    title=f"{one.number} {one.name}",
                    number=one.number,
                    name=one.name,
                    at=(0.0, 0.0),
                    angle=0.0,
                    outline=[(round(x, 1) + 0.0, round(y, 1) + 0.0) for x, y in board],
                    seen=True,
                )
            ],
        )

    def _found(self, pairs: Sequence[tuple[UUID, int]]) -> dict[tuple[UUID, int], Found | None]:
        """Each version's display copy: None when the version has no photo, absent when its
        image is gone."""
        if not pairs:
            return {}
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT v.module_id, v.version, v.drawing->>'photo' AS photo, j.id AS job, "
                "j.result, f.key, f.width, f.height "
                "FROM module_version v "
                "LEFT JOIN photo_job j ON j.id = (v.drawing->>'photo')::uuid "
                "AND j.module_id = v.module_id "
                "LEFT JOIN LATERAL (SELECT key, width, height FROM photo_file WHERE job_id = j.id "
                "AND kind = 'display' AND removed_at IS NULL ORDER BY position LIMIT 1) f ON true "
                "WHERE (v.module_id, v.version) IN "
                "(SELECT * FROM unnest(%s::uuid[], %s::integer[]))",
                ([m for m, _ in pairs], [v for _, v in pairs]),
            ).fetchall()
        found: dict[tuple[UUID, int], Found | None] = {}
        for row in rows:
            key = (row["module_id"], int(row["version"]))
            if row["photo"] is None:
                found[key] = None
                continue
            result: dict[str, Any] = row["result"] or {}
            grid = result.get("grid")
            if row["job"] is None or row["key"] is None or not grid:
                continue
            if not row["width"] or not row["height"]:
                continue
            frame = frame_of(grid, int(row["width"]), int(row["height"]), result.get("frame"))
            found[key] = Found(job=row["job"], key=str(row["key"]), frame=frame)
        return found

    def listing(self, who: Who, kind: StudioSourceKind, source: UUID) -> StudioImages:
        """Mätbilderna: each seen module's measuring image where the source puts it."""
        revision, scale, placed = self._placed(who, kind, source)
        found = self._found([(p.module, p.version) for p in placed if p.seen])
        images: list[StudioImage] = []
        missing: list[StudioImageMissing] = []
        for p in placed:
            if not p.seen:
                missing.append(
                    StudioImageMissing(
                        module=p.module, version=p.version, title=p.title, reason=UNSEEN
                    )
                )
                continue
            key = (p.module, p.version)
            image = found.get(key)
            if image is None:
                reason = NO_PHOTO if key in found else GONE
                missing.append(
                    StudioImageMissing(
                        module=p.module, version=p.version, title=p.title, reason=reason
                    )
                )
                continue
            assert p.number is not None and p.name is not None
            images.append(
                StudioImage(
                    module=p.module,
                    version=p.version,
                    number=p.number,
                    name=p.name,
                    job=image.job,
                    at=p.at,
                    angle=p.angle,
                    frame=image.frame,
                    to_source=_rounded(compose(pose(p.at, p.angle), image.frame.matrix)),
                    outline=p.outline,
                )
            )
        return StudioImages(
            kind=kind,
            source=source,
            revision=revision,
            gauge=switches.limits(scale).gauge,
            images=images,
            missing=missing,
        )

    def image(
        self, who: Who, kind: StudioSourceKind, source: UUID, module: UUID, version: int
    ) -> bytes:
        """One module's display copy as JPEG, for whoever the listing shows it to."""
        listed = self.listing(who, kind, source)
        if not any(i.module == module and i.version == version for i in listed.images):
            raise Refused(
                404,
                ProblemCode.NOT_FOUND,
                "Modulen har ingen mätbild här, eller så ser du den inte.",
            )
        found = self._found([(module, version)]).get((module, version))
        if found is None:
            raise Refused(404, ProblemCode.NOT_FOUND, GONE)
        try:
            data = self.store.get(found.key)
        except StoreFailed as error:
            LOGGER.warning("Mätbilden kunde inte hämtas för Studio.")
            raise Refused(503, ProblemCode.UNAVAILABLE, GONE) from error
        return as_jpeg(data)


def as_jpeg(data: bytes) -> bytes:
    """The image as JPEG: the display copy is one already; another is turned into one."""
    if data[:3] == b"\xff\xd8\xff":
        return data
    pixels = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if pixels is None:
        raise Refused(404, ProblemCode.NOT_FOUND, GONE)
    ok, encoded = cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise Refused(503, ProblemCode.UNAVAILABLE, GONE)
    return bytes(encoded.tobytes())
