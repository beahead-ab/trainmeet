"""Import från AnyRail as CAD keeps it (#91): the uploaded file in CAD's own database only, never
anywhere else (ANYRAIL-08), with its scale and measures; the reading again with other measures
(AR5, AR6); Skapa modulerna, which makes the approved proposals modules in the person's library,
as drafts, and an assembly that places them as in the drawing (ANYRAIL-06, #89 d2); and the
exports (ANYRAIL-05).

Only the person who uploaded a file sees it: anyone else gets 404, as for a module they do not
see. The modules and the assembly are the person's own, with the library's and the assemblies'
own rules (cad/library.py, cad/assemblies.py). An assumed switch the owner confirmed in the import
is answered in the module's Att kolla with their name (AR3); one not confirmed stays open, and the
module cannot be approved until it is.

The interpretation is pure and deterministic, so the reading is kept per file and measures in a
small cache in memory: the same file with the same measures gives the same answer, and the page,
the exports and Skapa modulerna read it once.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from cad import assembly as assembly_
from cad import editor
from cad.anyrail import interpret, outputs, reader
from cad.assemblies import Assemblies
from cad.db import Database
from cad.errors import Refused, invalid
from cad.library import Modules, Who
from contracts.cad import (
    JOINT_TOLERANCE,
    AnyRailCreate,
    AnyRailCreated,
    AnyRailFile,
    AnyRailImport,
    AnyRailMeasures,
    AnyRailSettings,
    AnyRailStart,
    AssemblyChange,
    AssemblyPart,
    CheckAnswer,
    DrawingSource,
    GableEnd,
    Joint,
    JointEnd,
    ModuleBrief,
    NewAssembly,
    NewModule,
    ProblemCode,
    Scale,
    Visibility,
)

API: Final = "/api/cad/1"
CACHE: Final = 4
MEDIA: Final = {
    "dxf": "application/dxf",
    "csv": "text/csv; charset=utf-8",
}


def not_found() -> Refused:
    return Refused(404, ProblemCode.NOT_FOUND, "Importen finns inte, eller så är den inte din.")


def changed() -> Refused:
    return Refused(
        409,
        ProblemCode.CHANGED,
        "Filen har lästs om med andra mått sedan du öppnade den. Öppna importen igen.",
    )


@dataclass(frozen=True)
class File:
    data: bytes
    media_type: str
    name: str


class AnyRailImports:
    def __init__(self, db: Database, modules: Modules, assemblies: Assemblies) -> None:
        self.db = db
        self.modules = modules
        self.assemblies = assemblies
        self._cache: OrderedDict[tuple[str, str, str], interpret.Result] = OrderedDict()
        self._lock = threading.Lock()

    # --- Reading ----------------------------------------------------------------------------

    def _read(self, data: bytes, name: str) -> reader.Layout:
        try:
            return reader.read(data, name)
        except reader.Unreadable as error:
            raise Refused(422, ProblemCode.BAD_DRAWING, str(error)) from error

    def _result(
        self, digest: str, data: bytes, name: str, scale: Scale, measures: AnyRailMeasures
    ) -> interpret.Result:
        key = (digest, scale.value, measures.model_dump_json())
        with self._lock:
            found = self._cache.get(key)
            if found is not None:
                self._cache.move_to_end(key)
                return found
        layout = self._read(data, name)
        try:
            made = interpret.interpret(layout, scale, measures)
        except (editor.EditError, ValueError, ArithmeticError, IndexError) as error:
            raise Refused(
                422,
                ProblemCode.BAD_DRAWING,
                "Filen gick inte att tolka som en station med de här måtten. Prova andra mått.",
            ) from error
        with self._lock:
            self._cache[key] = made
            while len(self._cache) > CACHE:
                self._cache.popitem(last=False)
        return made

    def _answer(
        self, row: dict[str, Any], result: interpret.Result, layout_area: tuple[float, float]
    ) -> AnyRailImport:
        ident = row["id"]
        stem = outputs.stem(str(row["name"]))
        files = [
            AnyRailFile(
                name="DXF, hela stationen",
                file=f"{stem}-anlaggning.dxf",
                url=f"{API}/anyrail/{ident}/files/anlaggning.dxf",
                media_type=MEDIA["dxf"],
            ),
            AnyRailFile(
                name="Gavelprofiler (CSV)",
                file=f"{stem}-gavelprofiler.csv",
                url=f"{API}/anyrail/{ident}/files/gavelprofiler.csv",
                media_type=MEDIA["csv"],
            ),
            AnyRailFile(
                name="Växellista (CSV)",
                file=f"{stem}-vaxlar.csv",
                url=f"{API}/anyrail/{ident}/files/vaxlar.csv",
                media_type=MEDIA["csv"],
            ),
        ] + [
            AnyRailFile(
                name=f"DXF, modul {m.number}",
                file=f"{stem}-modul-{outputs.stem(m.number)}.dxf",
                url=f"{API}/anyrail/{ident}/files/modul-{m.key}.dxf",
                media_type=MEDIA["dxf"],
            )
            for m in result.modules
        ]
        created = AnyRailCreated.model_validate(row["created"]) if row.get("created") else None
        return AnyRailImport(
            id=ident,
            name=row["name"],
            format=row["format"],
            library=row.get("library"),
            revision=int(row["revision"]),
            scale=Scale(row["scale"]),
            measures=result.measures,
            area=layout_area,
            modules=result.modules,
            switches=result.switches,
            checks=result.checks,
            stats=result.stats,
            graph=result.graph,
            drawing=result.drawing,
            left_out=result.left_out,
            files=files,
            created=created,
            created_at=row["created_at"],
        )

    def _row(self, who: Who, ident: UUID, *, lock: bool = False) -> dict[str, Any]:
        with self.db.transaction() as conn:
            found = conn.execute(
                "SELECT * FROM anyrail_import WHERE id = %s AND person_id = %s"
                + (" FOR UPDATE" if lock else ""),
                (ident, who.person),
            ).fetchone()
        if found is None:
            raise not_found()
        return dict(found)

    def _result_of(self, row: dict[str, Any]) -> interpret.Result:
        return self._result(
            str(row["sha256"]),
            bytes(row["data"]),
            str(row["name"]),
            Scale(row["scale"]),
            AnyRailMeasures.model_validate(row["measures"]),
        )

    # --- The import's addresses -------------------------------------------------------------

    def upload(self, who: Who, name: str, data: bytes, start: AnyRailStart) -> AnyRailImport:
        """Ladda upp: the file read with the file's own scale and the default measures, unless
        others are given."""
        if not data:
            raise Refused(422, ProblemCode.BAD_DRAWING, "Filen är tom.")
        clean = (name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip() or "AnyRail")[:200]
        layout = self._read(data, clean)
        scale = start.scale or interpret.scale_of(layout)
        measures = start.measures or AnyRailMeasures()
        digest = hashlib.sha256(data).hexdigest()
        result = self._result(digest, data, clean, scale, measures)
        ident = uuid.uuid4()
        row: dict[str, Any] = {
            "id": ident,
            "name": clean,
            "format": layout.format,
            "library": layout.library,
            "revision": 1,
            "scale": scale.value,
            "created": None,
            "created_at": datetime.now(UTC),
        }
        answer = self._answer(row, result, (layout.length, layout.width))
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO person (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                (who.person, who.name[:80] or "Okänd"),
            )
            stored = conn.execute(
                "INSERT INTO anyrail_import (id, person_id, name, format, data, sha256, library, "
                "scale, measures, result) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING created_at",
                (
                    ident,
                    who.person,
                    clean,
                    layout.format,
                    data,
                    digest,
                    layout.library,
                    scale.value,
                    measures.model_dump_json(),
                    answer.model_dump_json(),
                ),
            ).fetchone()
        assert stored is not None
        return answer.model_copy(update={"created_at": stored["created_at"]})

    def read(self, who: Who, ident: UUID) -> AnyRailImport:
        row = self._row(who, ident)
        found = AnyRailImport.model_validate(row["result"])
        created = AnyRailCreated.model_validate(row["created"]) if row.get("created") else None
        return found.model_copy(update={"created": created})

    def settings(self, who: Who, ident: UUID, change: AnyRailSettings) -> AnyRailImport:
        """Läs om: the same file with another scale or other measures, the next revision."""
        row = self._row(who, ident)
        if change.base != int(row["revision"]):
            raise changed()
        result = self._result(
            str(row["sha256"]), bytes(row["data"]), str(row["name"]), change.scale, change.measures
        )
        layout_area = tuple(AnyRailImport.model_validate(row["result"]).area)
        with self.db.transaction() as conn:
            locked = conn.execute(
                "SELECT revision FROM anyrail_import WHERE id = %s AND person_id = %s FOR UPDATE",
                (ident, who.person),
            ).fetchone()
            if locked is None:
                raise not_found()
            if int(locked["revision"]) != change.base:
                raise changed()
            revision = change.base + 1
            fresh = {**row, "revision": revision, "scale": change.scale.value}
            answer = self._answer(fresh, result, (layout_area[0], layout_area[1]))
            conn.execute(
                "UPDATE anyrail_import SET scale = %s, measures = %s, revision = %s, result = %s, "
                "updated_at = now() WHERE id = %s",
                (
                    change.scale.value,
                    change.measures.model_dump_json(),
                    revision,
                    answer.model_dump_json(),
                    ident,
                ),
            )
        return answer

    def file(self, who: Who, ident: UUID, name: str) -> File:
        row = self._row(who, ident)
        result = self._result_of(row)
        stem = outputs.stem(str(row["name"]))
        if name == "anlaggning.dxf":
            return File(outputs.station_dxf(result), MEDIA["dxf"], f"{stem}-anlaggning.dxf")
        if name == "gavelprofiler.csv":
            return File(outputs.gable_csv(result), MEDIA["csv"], f"{stem}-gavelprofiler.csv")
        if name == "vaxlar.csv":
            return File(outputs.switch_csv(result), MEDIA["csv"], f"{stem}-vaxlar.csv")
        if name.startswith("modul-") and name.endswith(".dxf"):
            key = name.removeprefix("modul-").removesuffix(".dxf")
            data = outputs.module_dxf(result, key)
            number = next((m.number for m in result.modules if m.key == key), key)
            if data is not None:
                return File(data, MEDIA["dxf"], f"{stem}-modul-{outputs.stem(number)}.dxf")
        raise Refused(404, ProblemCode.NOT_FOUND, "Den filen finns inte i importen.")

    # --- Skapa modulerna --------------------------------------------------------------------

    def create(self, who: Who, ident: UUID, ask: AnyRailCreate) -> AnyRailCreated:
        """The approved proposals as modules, drafts in the person's library, with the assumed
        switches confirmed as answered; and an assembly placing them as in the drawing."""
        row = self._row(who, ident)
        if ask.base != int(row["revision"]):
            raise changed()
        if row.get("created"):
            raise Refused(409, ProblemCode.CHANGED, "Modulerna ur den här filen är redan skapade.")
        result = self._result_of(row)
        by_key = {m.key: (m, p) for m, p in zip(result.modules, result.proposals, strict=True)}
        unknown = [c.key for c in ask.modules if c.key not in by_key]
        if unknown:
            raise invalid(f"Importen har ingen modul {unknown[0]}.")
        confirmed = set(ask.confirmed)
        scale = Scale(row["scale"])
        made: dict[str, ModuleBrief] = {}
        for choice in ask.modules:
            module, proposal = by_key[choice.key]
            keys = {c.key for c in module.checks}
            state = proposal.drawing.state().model_copy(
                update={
                    "source": DrawingSource.ANYRAIL,
                    "answers": [
                        CheckAnswer(key=k, answer="vaxel", by=who.name[:80] or None)
                        for k in sorted(confirmed & keys)
                    ],
                }
            )
            new = NewModule(
                name=choice.name,
                scale=scale,
                shape=module.shape,
                gables=module.gables,
                visibility=Visibility.ME,
            )
            created = self.modules.create(
                who, new, made_from="Modulen skapad ur AnyRail", drawn=(module.graph, state)
            )
            made[choice.key] = ModuleBrief.model_validate(
                created.model_dump(include=set(ModuleBrief.model_fields))
            )
        name = ask.assembly or str(row["name"]).rsplit(".", 1)[0][:80] or "AnyRail"
        assembly = self.assemblies.create(who, NewAssembly(name=name, scale=scale))
        parts = [
            AssemblyPart(
                module=made[c.key].id,
                version=1,
                at=by_key[c.key][0].at,
                angle=round(by_key[c.key][0].angle, 6),
            )
            for c in ask.modules
        ]
        joints = _joints(result, made)
        saved = self.assemblies.save(
            who,
            assembly.id,
            AssemblyChange(base=assembly.revision, name=name, modules=parts, joints=joints),
            drafts=True,
        )
        answer = AnyRailCreated(
            modules=[made[c.key] for c in ask.modules],
            assembly=saved.id,
            assembly_name=saved.name,
            at=datetime.now(UTC),
        )
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE anyrail_import SET created = %s, updated_at = now() WHERE id = %s",
                (answer.model_dump_json(), ident),
            )
        return answer


def _joints(result: interpret.Result, made: dict[str, ModuleBrief]) -> list[Joint]:
    """The joints where two made modules meet gable to gable, whole and in line: then the joint
    places the second where the drawing has it. Others lie where the drawing has them, and their
    tracks meet where the gables lie against each other (cad/assemblies.py)."""
    used: set[tuple[str, GableEnd]] = set()
    found: list[Joint] = []
    modules = {m.key: m for m in result.modules if m.key in made}
    for a, b in sorted((x, y) for x in modules for y in modules if x != y):
        ma, mb = modules[a], modules[b]
        if abs(ma.angle - mb.angle) > 0.01:
            continue
        pa = assembly_.Pose(ma.at, ma.angle)
        pb = assembly_.Pose(mb.at, mb.angle)
        corner_a = (pa.point((ma.shape.length, 0.0)), pa.point((ma.shape.length, ma.shape.width)))
        corner_b = (pb.point((0.0, 0.0)), pb.point((0.0, mb.shape.width)))
        if any(
            max(abs(p[0] - q[0]), abs(p[1] - q[1])) > JOINT_TOLERANCE
            for p, q in zip(corner_a, corner_b, strict=True)
        ):
            continue
        ga, gb = ma.gables[1].tracks, mb.gables[0].tracks
        if len(ga) != len(gb) or any(
            abs(x - y) > JOINT_TOLERANCE for x, y in zip(ga, gb, strict=True)
        ):
            continue
        if (a, GableEnd.B) in used or (b, GableEnd.A) in used:
            continue
        used.update(((a, GableEnd.B), (b, GableEnd.A)))
        found.append(
            Joint(
                a=JointEnd(module=made[a].id, gable=GableEnd.B),
                b=JointEnd(module=made[b].id, gable=GableEnd.A),
            )
        )
    return found
