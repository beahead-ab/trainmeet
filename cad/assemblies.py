"""Anläggningar (CAD-06, CAD-21) and the way to TKL Studio (CAD-10, CAD-15): the assemblies with
their revisions and rights, the modules' versions they pin, what Studio's Från CAD lists, and the
stations that use them (Används i).

Who may do what (CAD-21): a person's own assembly is the person's alone; a club's is seen by the
club's members and changed by its administrators, as a club's module. Only modules the person
sees can be put in, and only at an approved version (Flödet: godkänd modul → anläggning). A
module the person no longer sees stays as an outline, and keeps the assembly from Studio.

The rights on the modules are the library's own (cad/library.py), so that the rules stay in one
place. The placement, the joint checks and the graph are cad/assembly.py's.

The AnyRail import (#91) makes an assembly of the drafts it made, placed as in the drawing: it
pins their first versions, and each draft is a problem that keeps the assembly from Studio until
the module is approved (AR3). Where its gables lie against each other without a joint (an a/b
pair against one wide gable, an end module at an angle), the tracks that meet within
JOINT_TOLERANCE are joined in the graph as at a joint (_contacts).
"""

from __future__ import annotations

import itertools
import json
import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow

from cad import assembly
from cad.db import Database
from cad.errors import Refused, invalid
from cad.library import MODULE_COLUMNS, SHAPE, Modules, Right, Who
from contracts.cad import (
    JOINT_TOLERANCE,
    Assembly,
    AssemblyBrief,
    AssemblyChange,
    AssemblyModule,
    AssemblyRemoved,
    Gable,
    GableEnd,
    Joint,
    NewAssembly,
    Owner,
    OwnerKind,
    PlacedModule,
    ProblemCode,
    Scale,
    StationUse,
    StationUseAsk,
    StudioGraph,
    StudioModule,
    StudioSource,
    StudioSourceKind,
    StudioSources,
    TrackGraph,
    UsedIn,
)
from contracts.station_model import NodeType

COLUMNS = "id, owner_kind, owner_id, owner_name, name, scale, revision, modules, joints, changed_at"


def not_found() -> Refused:
    return Refused(404, ProblemCode.NOT_FOUND, "Anläggningen finns inte, eller så ser du den inte.")


def forbidden() -> Refused:
    return Refused(
        403,
        ProblemCode.FORBIDDEN,
        "Bara ägaren ändrar anläggningen; en klubbs anläggning ändras av klubbens administratör.",
    )


def changed() -> Refused:
    return Refused(
        409,
        ProblemCode.CHANGED,
        "Anläggningen har ändrats sedan du öppnade den. Öppna den igen och ändra där.",
    )


def module_missing() -> Refused:
    return Refused(404, ProblemCode.NOT_FOUND, "Modulen finns inte, eller så ser du den inte.")


@dataclass
class Built:
    """An assembly placed and checked for one person."""

    answer: Assembly
    members: list[assembly.Member]


class Assemblies:
    def __init__(self, db: Database, modules: Modules) -> None:
        self.db = db
        self.modules = modules

    # --- Rights -------------------------------------------------------------------------------

    @staticmethod
    def _right(who: Who, row: dict[str, Any]) -> Right | None:
        if row["owner_kind"] == OwnerKind.PERSON:
            return Right.EDIT if row["owner_id"] == who.person else None
        club = who.club(row["owner_id"])
        if club is None:
            return None
        return Right.EDIT if club.admin else Right.SEE

    def _row(self, conn: Connection[DictRow], ident: UUID, *, lock: bool = False) -> dict[str, Any]:
        found = conn.execute(
            f"SELECT {COLUMNS} FROM assembly WHERE id = %s AND removed_at IS NULL"
            + (" FOR UPDATE" if lock else ""),
            (ident,),
        ).fetchone()
        if found is None:
            raise not_found()
        return dict(found)

    def _seen(self, who: Who, row: dict[str, Any], need: Right = Right.SEE) -> Right:
        right = self._right(who, row)
        if right is None:
            raise not_found()
        if right < need:
            raise forbidden()
        return right

    def _module_right(self, who: Who, row: dict[str, Any]) -> Right | None:
        """The library's right to the module (CAD-21), asking ID only when it is needed."""
        if row.get("removed_at") is not None:
            return None
        right = self.modules._right(who, row, ask_id=False)
        return right if right is not None else self.modules._right(who, row)

    # --- The modules an assembly pins ---------------------------------------------------------

    def _versions(
        self, conn: Connection[DictRow], wanted: Sequence[tuple[UUID, int]]
    ) -> dict[tuple[UUID, int], dict[str, Any]]:
        if not wanted:
            return {}
        rows = conn.execute(
            f"SELECT {MODULE_COLUMNS}, m.removed_at FROM module m JOIN module_version v "
            "ON v.module_id = m.id WHERE (m.id, v.version) IN "
            "(SELECT * FROM unnest(%s::uuid[], %s::integer[]))",
            ([m for m, _ in wanted], [v for _, v in wanted]),
        ).fetchall()
        return {(r["id"], int(r["version"])): dict(r) for r in rows}

    def _members(
        self, conn: Connection[DictRow], who: Who, placed: Sequence[PlacedModule]
    ) -> list[tuple[assembly.Member, int | None, str, bool]]:
        """Each pinned module as the assembly uses it, the newer approved version it may take,
        its owner's name, and whether the pinned version is approved."""
        rows = self._versions(conn, [(p.module, p.version) for p in placed])
        known = self.modules._profiles_for(conn, [r["gables"] for r in rows.values()])
        found: list[tuple[assembly.Member, int | None, str, bool]] = []
        for part in placed:
            row = rows.get((part.module, part.version))
            if row is None:
                raise module_missing()
            seen = self._module_right(who, row) is not None
            gables = tuple(Gable.model_validate(g) for g in row["gables"])
            labels = tuple(g.label for g in self.modules._labels(gables, known))
            member = assembly.Member(
                module=row["id"],
                version=int(row["version"]),
                number=f"M-{int(row['number']):03d}",
                name=str(row["name"]),
                scale=Scale(row["scale"]),
                shape=SHAPE.validate_python(row["shape"]),
                gables=gables,
                graph=TrackGraph.model_validate(row["graph"]),
                labels=(labels[0], labels[1]),
                seen=seen,
            )
            approved = row["approved_version"]
            newer = int(approved) if seen and approved and int(approved) > part.version else None
            found.append((member, newer, str(row["owner_name"]), row["approved_at"] is not None))
        return found

    def _stations(
        self, conn: Connection[DictRow], kind: StudioSourceKind, ident: UUID
    ) -> list[StationUse]:
        rows = conn.execute(
            "SELECT station_id, station_name, revision, at FROM station_use "
            "WHERE source_kind = %s AND source_id = %s ORDER BY at DESC, station_name",
            (kind.value, ident),
        ).fetchall()
        return [
            StationUse(
                station_id=r["station_id"],
                name=r["station_name"],
                revision=r["revision"],
                at=r["at"],
            )
            for r in rows
        ]

    # --- Building the answer ------------------------------------------------------------------

    def _build(self, conn: Connection[DictRow], who: Who, row: dict[str, Any]) -> Built:
        right = self._seen(who, row)
        placed = [PlacedModule.model_validate(m) for m in row["modules"]]
        joints = [Joint.model_validate(j) for j in row["joints"]]
        found = self._members(conn, who, placed)
        members = [m for m, _, _, _ in found]
        placement = assembly.place(members, [assembly.Pose(p.at, p.angle) for p in placed], joints)
        by_id = {m.module: m for m in members}
        checks = [assembly.check(k, j, by_id, placement) for k, j in enumerate(joints)]
        problems = self._problems(Scale(row["scale"]), members, joints, checks, by_id)
        # An assembly the AnyRail import made pins its modules' drafts (#91): each is approved
        # before the assembly goes to Studio (AR3: an assumed switch is confirmed first).
        problems += [
            f"{m.title} är ett utkast i version {m.version}. Godkänn modulen, eller ta den "
            "godkända versionen."
            for m, _, _, approved in found
            if m.seen and not approved
        ]
        joined: dict[UUID, list[GableEnd]] = {}
        for joint in joints:
            joined.setdefault(joint.a.module, []).append(joint.a.gable)
            joined.setdefault(joint.b.module, []).append(joint.b.gable)
        parts: list[AssemblyModule] = []
        for member, newer, owner, _ in found:
            pose = placement.poses[member.module]
            gables = assembly.gables_at(member, pose, joined.get(member.module, []))
            if not member.seen:
                gables = [
                    g.model_copy(update={"label": f"Gavel {g.end}", "norm": None, "tracks": []})
                    for g in gables
                ]
            parts.append(
                AssemblyModule(
                    module=member.module,
                    version=member.version,
                    seen=member.seen,
                    number=member.number if member.seen else None,
                    name=member.name if member.seen else None,
                    owner=owner if member.seen else None,
                    placed=placement.placed[member.module],
                    outline=assembly.outline(member, pose),
                    gables=gables,
                    newer=newer,
                )
            )
        answer = Assembly(
            id=row["id"],
            name=row["name"],
            owner=Owner(kind=row["owner_kind"], id=row["owner_id"], name=row["owner_name"]),
            scale=Scale(row["scale"]),
            modules=[
                p.model_copy(
                    update={
                        "at": (round(pose.at[0], 3), round(pose.at[1], 3)),
                        "angle": round(pose.angle, 6),
                    }
                )
                for p in placed
                for pose in (placement.poses[p.module],)
            ],
            joints=joints,
            revision=int(row["revision"]),
            changed_at=row["changed_at"],
            may_edit=right >= Right.EDIT,
            parts=parts,
            checks=checks,
            problems=problems,
            graph=_contacts(assembly.graph(members, placement, joints, checks)),
            stations=self._stations(conn, StudioSourceKind.ASSEMBLY, row["id"]),
        )
        return Built(answer=answer, members=members)

    @staticmethod
    def _problems(
        scale: Scale,
        members: Sequence[assembly.Member],
        joints: Sequence[Joint],
        checks: Sequence[Any],
        by_id: dict[UUID, assembly.Member],
    ) -> list[str]:
        """What keeps the assembly from Studio, in Swedish."""
        found: list[str] = []
        if not members:
            found.append("Anläggningen har inga moduler än.")
        for member in members:
            if not member.seen:
                found.append(
                    "En modul i anläggningen syns inte för dig längre. Ta bort den ur "
                    "anläggningen, eller be ägaren visa den."
                )
            elif member.scale != scale:
                found.append(f"{member.title} är i skala {member.scale}, anläggningen i {scale}.")
            elif not member.graph.complete:
                found.append(
                    f"{member.title}: spåren mellan gavlarna är inte kända än. Rita dem i "
                    "Ritningen eller ta ett foto."
                )
        for joint, result in zip(joints, checks, strict=True):
            a, b = by_id[joint.a.module], by_id[joint.b.module]
            where = f"Skarven {a.title} gavel {joint.a.gable} – {b.title} gavel {joint.b.gable}"
            found += [f"{where}: {problem}" for problem in result.problems]
        return found

    # --- The list and one assembly ------------------------------------------------------------

    def _visible(self, conn: Connection[DictRow], who: Who) -> list[dict[str, Any]]:
        clubs = [c.id for c in who.clubs()]
        rows = conn.execute(
            f"SELECT {COLUMNS} FROM assembly WHERE removed_at IS NULL AND "
            "((owner_kind = 'person' AND owner_id = %s) OR (owner_kind = 'club' AND "
            "owner_id = ANY(%s))) ORDER BY changed_at DESC, lower(name)",
            (who.person, clubs),
        ).fetchall()
        return [dict(r) for r in rows]

    def listing(self, who: Who) -> list[AssemblyBrief]:
        with self.db.transaction() as conn:
            built = [self._build(conn, who, row).answer for row in self._visible(conn, who)]
        return [
            AssemblyBrief(
                id=a.id,
                name=a.name,
                owner=a.owner,
                scale=a.scale,
                modules=len(a.modules),
                problems=len(a.problems),
                revision=a.revision,
                changed_at=a.changed_at or datetime.min,
                may_edit=a.may_edit,
                stations=a.stations,
            )
            for a in built
        ]

    def create(self, who: Who, new: NewAssembly) -> Assembly:
        if new.owner is None or new.owner == who.person:
            owner = Owner(kind=OwnerKind.PERSON, id=who.person, name=who.name)
        else:
            club = who.club(new.owner)
            if club is None:
                raise Refused(
                    404, ProblemCode.NOT_FOUND, "Klubben finns inte, eller så är du inte med."
                )
            if not club.admin:
                raise Refused(
                    403,
                    ProblemCode.FORBIDDEN,
                    "Bara klubbens administratör gör klubbens anläggningar.",
                )
            owner = Owner(kind=OwnerKind.CLUB, id=club.id, name=club.name)
        ident = uuid.uuid4()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO assembly (id, owner_kind, owner_id, owner_name, name, scale, "
                "created_by, changed_by_name) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    ident,
                    owner.kind.value,
                    owner.id,
                    owner.name,
                    new.name,
                    new.scale.value,
                    who.person,
                    who.name,
                ),
            )
        return self.read(who, ident)

    def read(self, who: Who, ident: UUID) -> Assembly:
        with self.db.transaction() as conn:
            return self._build(conn, who, self._row(conn, ident)).answer

    def save(
        self, who: Who, ident: UUID, change: AssemblyChange, *, drafts: bool = False
    ) -> Assembly:
        """Spara: the whole assembly on top of the newest revision, the versions pinned and the
        placement worked out from the joints. drafts: the AnyRail import (#91) pins the drafts
        it made, at the versions it names."""
        with self.db.transaction() as conn:
            row = self._row(conn, ident, lock=True)
            self._seen(who, row, Right.EDIT)
            if change.base != int(row["revision"]):
                raise changed()
            scale = Scale(row["scale"])
            pinned = [PlacedModule.model_validate(m) for m in row["modules"]]
            before = {p.module: p.version for p in pinned}
            placed = [
                self._pin(conn, who, scale, part, before, drafts=drafts) for part in change.modules
            ]
            draft = {**row, "modules": [p.model_dump(mode="json") for p in placed]}
            draft["joints"] = [j.model_dump(mode="json") for j in change.joints]
            built = self._build(conn, who, draft).answer
            conn.execute(
                "UPDATE assembly SET name = %s, revision = revision + 1, modules = %s, "
                "joints = %s, changed_at = now(), changed_by_name = %s WHERE id = %s",
                (
                    change.name,
                    json.dumps([m.model_dump(mode="json") for m in built.modules]),
                    json.dumps(draft["joints"]),
                    who.name,
                    ident,
                ),
            )
            conn.execute("DELETE FROM assembly_module WHERE assembly_id = %s", (ident,))
            for p in placed:
                conn.execute(
                    "INSERT INTO assembly_module (assembly_id, module_id, version) "
                    "VALUES (%s, %s, %s)",
                    (ident, p.module, p.version),
                )
        return self.read(who, ident)

    def _pin(
        self,
        conn: Connection[DictRow],
        who: Who,
        scale: Scale,
        part: Any,
        before: dict[UUID, int],
        *,
        drafts: bool = False,
    ) -> PlacedModule:
        """The version a module in the change pins: as before, or an approved one it may take;
        null for its newest approved version."""
        found = conn.execute("SELECT * FROM module WHERE id = %s", (part.module,)).fetchone()
        if found is None:
            raise module_missing()
        row = dict(found)
        version = part.version
        kept = version is not None and before.get(part.module) == version
        seen = self._module_right(who, row) is not None
        if not kept and not seen:
            raise module_missing()
        number = f"M-{int(row['number']):03d}"
        if version is None:
            if row["approved_version"] is None:
                raise invalid(f"{number} har ingen godkänd version än. Godkänn den först.")
            version = int(row["approved_version"])
        pinned = conn.execute(
            "SELECT name, scale, approved_at FROM module_version WHERE module_id = %s "
            "AND version = %s",
            (part.module, version),
        ).fetchone()
        if pinned is None:
            raise invalid(f"{number} har ingen version {version}.")
        if not kept and not drafts and pinned["approved_at"] is None:
            raise invalid(f"Version {version} av {number} är inte godkänd.")
        if pinned["scale"] != scale.value:
            raise invalid(
                f"{number} {pinned['name']} är i skala {pinned['scale']}, och anläggningen är i "
                f"{scale.value}. En anläggning har en skala (CAD9)."
            )
        return PlacedModule(module=part.module, version=version, at=part.at, angle=part.angle)

    def remove(self, who: Who, ident: UUID) -> AssemblyRemoved:
        with self.db.transaction() as conn:
            row = self._row(conn, ident, lock=True)
            self._seen(who, row, Right.EDIT)
            conn.execute("UPDATE assembly SET removed_at = now() WHERE id = %s", (ident,))
            conn.execute("DELETE FROM assembly_module WHERE assembly_id = %s", (ident,))
        return AssemblyRemoved(id=ident)

    # --- Till TKL Studio (CAD-10, CAD-15) -----------------------------------------------------

    def _assembly_source(
        self, conn: Connection[DictRow], who: Who, row: dict[str, Any]
    ) -> tuple[StudioSource, TrackGraph]:
        built = self._build(conn, who, row)
        a = built.answer
        source = StudioSource(
            kind=StudioSourceKind.ASSEMBLY,
            id=a.id,
            name=a.name,
            scale=a.scale,
            owner=a.owner.name,
            revision=a.revision,
            modules=[
                StudioModule(id=m.module, number=m.number, name=m.name, version=m.version)
                for m in built.members
                if m.seen
            ],
            ready=not a.problems,
            problems=a.problems,
            stations=a.stations,
            changed_at=a.changed_at or datetime.min,
        )
        return source, a.graph

    def _module_rows(self, conn: Connection[DictRow], who: Who) -> list[dict[str, Any]]:
        """The person's own modules with an approved version, at that version."""
        rows = conn.execute(
            f"SELECT {MODULE_COLUMNS}, m.removed_at FROM module m JOIN module_version v "
            "ON v.module_id = m.id AND v.version = m.approved_version WHERE m.removed_at IS NULL "
            "AND m.owner_kind = 'person' AND m.owner_id = %s ORDER BY v.saved_at DESC",
            (who.person,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _module_source(
        self, conn: Connection[DictRow], who: Who, row: dict[str, Any]
    ) -> tuple[StudioSource, TrackGraph]:
        """A single module, as an assembly of one at the origin."""
        placed = PlacedModule(module=row["id"], version=int(row["version"]), at=(0, 0), angle=0)
        member, _, owner, _ = self._members(conn, who, [placed])[0]
        placement = assembly.place([member], [assembly.Pose()], [])
        made = assembly.graph([member], placement, [], [])
        problems = (
            []
            if member.graph.complete
            else [f"{member.title}: spåren mellan gavlarna är inte kända än."]
        )
        source = StudioSource(
            kind=StudioSourceKind.MODULE,
            id=member.module,
            name=member.name,
            scale=member.scale,
            owner=owner,
            revision=member.version,
            modules=[
                StudioModule(
                    id=member.module, number=member.number, name=member.name, version=member.version
                )
            ],
            ready=not problems,
            problems=problems,
            stations=self._stations(conn, StudioSourceKind.MODULE, member.module),
            changed_at=row["saved_at"],
        )
        return source, made

    def sources(self, who: Who) -> StudioSources:
        """Från CAD's list: the person's assemblies, then their own approved modules."""
        with self.db.transaction() as conn:
            found = [self._assembly_source(conn, who, r)[0] for r in self._visible(conn, who)]
            found += [self._module_source(conn, who, r)[0] for r in self._module_rows(conn, who)]
        return StudioSources(sources=found)

    def _source(
        self, conn: Connection[DictRow], who: Who, kind: StudioSourceKind, ident: UUID
    ) -> tuple[StudioSource, TrackGraph]:
        if kind == StudioSourceKind.ASSEMBLY:
            return self._assembly_source(conn, who, self._row(conn, ident))
        found = next((r for r in self._module_rows(conn, who) if r["id"] == ident), None)
        if found is None:
            raise Refused(
                404,
                ProblemCode.NOT_FOUND,
                "Modulen finns inte, är inte din, eller har ingen godkänd version.",
            )
        return self._module_source(conn, who, found)

    def studio_graph(self, who: Who, kind: StudioSourceKind, ident: UUID) -> StudioGraph:
        """Till TKL Studio: the track graph only, with ids CAD never changes (CAD-10, CAD-20)."""
        with self.db.transaction() as conn:
            source, made = self._source(conn, who, kind, ident)
        return StudioGraph(source=source, graph=made)

    def station_use(
        self, who: Who, kind: StudioSourceKind, ident: UUID, ask: StationUseAsk
    ) -> StudioSource:
        """Studio says that a station took the source into use (CAD-15): Används i."""
        with self.db.transaction() as conn:
            self._source(conn, who, kind, ident)
            conn.execute(
                "INSERT INTO station_use (source_kind, source_id, person, station_id, "
                "station_name, revision) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (source_kind, source_id, person, station_id) DO UPDATE SET "
                "station_name = excluded.station_name, revision = excluded.revision, at = now()",
                (kind.value, ident, who.person, ask.station_id, ask.name, ask.revision),
            )
            source, _ = self._source(conn, who, kind, ident)
        return source

    # --- Används i on the module's page -------------------------------------------------------

    def used_in(self, who: Who, module: UUID) -> list[UsedIn]:
        """The assemblies the person sees that pin the module, and the stations that use it."""
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT a.id, a.name, a.owner_kind, a.owner_id, am.version FROM assembly_module "
                "am JOIN assembly a ON a.id = am.assembly_id WHERE am.module_id = %s AND "
                "a.removed_at IS NULL ORDER BY lower(a.name)",
                (module,),
            ).fetchall()
            seen = [dict(r) for r in rows if self._right(who, dict(r)) is not None]
            found = [
                UsedIn(kind="assembly", id=r["id"], name=r["name"], version=r["version"])
                for r in seen
            ]
            sources = [(StudioSourceKind.MODULE, module)] + [
                (StudioSourceKind.ASSEMBLY, r["id"]) for r in seen
            ]
            for kind, ident in sources:
                found += [
                    UsedIn(
                        kind="station",
                        id=ident,
                        name=s.name,
                        version=s.revision,
                        station=s.station_id,
                    )
                    for s in self._stations(conn, kind, ident)
                ]
        return found


def _contacts(graph: TrackGraph) -> TrackGraph:
    """Gables that lie against each other without a joint (one wide gable against two narrow
    ones, or an end module at an angle, as AnyRail draws them, #91): their tracks that meet within
    JOINT_TOLERANCE become one node, as at a joint (cad/assembly.py). Only module joints that no
    joint has joined, of two different modules, each used once."""
    free = [
        n
        for n in graph.nodes
        if n.type == NodeType.MODULE_JOINT
        and sum(1 for p in graph.pieces if n.id in (p.start, p.end)) == 1
    ]
    nodes = {n.id: n for n in graph.nodes}
    pieces = {p.id: p for p in graph.pieces}
    used: set[str] = set()
    pairs: list[tuple[float, str, str]] = []
    for a, b in itertools.combinations(sorted(free, key=lambda n: n.id), 2):
        if a.id.split(":", 1)[0] == b.id.split(":", 1)[0]:
            continue
        apart = math.dist(a.at, b.at)
        if apart <= JOINT_TOLERANCE:
            pairs.append((apart, a.id, b.id))
    for _, a_id, b_id in sorted(pairs):
        if a_id in used or b_id in used:
            continue
        used.update((a_id, b_id))
        assembly._merge(nodes, pieces, a_id, b_id)
    if not used:
        return graph
    return graph.model_copy(update={"nodes": list(nodes.values()), "pieces": list(pieces.values())})
