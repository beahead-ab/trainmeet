"""The module library (CAD-01, CAD-05, CAD-07, CAD-08, CAD-21, CAD-22): the modules with their
versions and history, the rights, and the gable profiles.

Who may do what (CAD-21, decided in one place, _right):
- change (redigera): a person's own module; a club's module for the club's administrators, as
  for a club's fleet in Catalog (C36); and anyone TrainMeet ID gives the role editor on the
  module, which its owner or the club's administrator hands out (KONTO-36).
- see and use: as above, and by the visibility: jag (no one more), klubben (the members of the
  module's club) or alla (everyone logged in); and anyone ID gives the role viewer on the module.
404 when the module is not seen at all, 403 when it is seen but the change needs more.

The clubs and the roles come from ID at every call (cad/id_roles.py); nothing is kept. A person's
own modules need no answer from ID.

Every save is a new version on top of the newest one the person read (409 otherwise). The newest
version is a draft until someone who may change the module approves it. Removing a module hides
it; its rows and history stay.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow

from cad import geometry, graph, profiles
from cad.db import Database
from cad.errors import Refused, forbidden, invalid, not_found
from cad.id_roles import IdRoles
from contracts.cad import (
    NORM_NAMES,
    ClubChoice,
    Curve,
    EdgeSide,
    Gable,
    GableCount,
    GableLabel,
    GableProfile,
    Library,
    Module,
    ModuleApproval,
    ModuleBrief,
    ModuleChange,
    ModuleEvent,
    ModuleEventKind,
    ModuleList,
    ModuleRemoved,
    ModuleStatus,
    NewModule,
    NewProfile,
    Norm,
    Owner,
    OwnerKind,
    ProblemCode,
    ProfileKind,
    ProfileList,
    Scale,
    Shape,
    TrackGraph,
    Visibility,
    VisibilityChange,
)

VISIBILITY_TEXT = {
    Visibility.ME: "Bara jag",
    Visibility.CLUB: "Min klubb",
    Visibility.ALL: "Alla i TrainMeet",
}


class Right(IntEnum):
    SEE = 1
    EDIT = 2


class Access:
    """What ID says, or nothing without ID's API: then no one has a club or a role."""

    def __init__(self, roles: IdRoles | None) -> None:
        self.roles = roles

    def clubs(self, person: UUID) -> list[ClubChoice]:
        return self.roles.clubs(person) if self.roles is not None else []

    def module_roles(self, person: UUID, module: UUID) -> set[str]:
        return self.roles.module_roles(person, module) if self.roles is not None else set()


@dataclass
class Who:
    """The person asking, with their clubs from ID, asked once per call and only when needed."""

    person: UUID
    name: str
    access: Access
    _clubs: list[ClubChoice] | None = field(default=None, repr=False)

    def clubs(self) -> list[ClubChoice]:
        if self._clubs is None:
            self._clubs = self.access.clubs(self.person)
        return self._clubs

    def club(self, club: UUID) -> ClubChoice | None:
        return next((c for c in self.clubs() if c.id == club), None)


def changed() -> Refused:
    return Refused(
        409, ProblemCode.CHANGED, "Modulen har en nyare version. Öppna den igen och ändra där."
    )


MODULE_COLUMNS = (
    "m.id, m.owner_kind, m.owner_id, m.owner_name, m.number, m.visibility, m.club_id, "
    "m.club_name, m.latest, m.approved_version, m.created_at, "
    "v.version, v.name, v.scale, v.shape, v.gables, v.graph, v.track_length, v.saved_at, "
    "v.approved_at, v.approved_by_name"
)


class Modules:
    def __init__(self, db: Database, access: Access) -> None:
        self.db = db
        self.access = access

    # --- Rights -------------------------------------------------------------------------------

    def _right(self, who: Who, row: dict[str, Any], *, ask_id: bool = True) -> Right | None:
        """The person's right to the module (CAD-21), or None when it is not seen."""
        owner = row["owner_id"]
        if row["owner_kind"] == OwnerKind.PERSON and owner == who.person:
            return Right.EDIT
        club_owned = row["owner_kind"] == OwnerKind.CLUB
        if club_owned:
            mine = who.club(owner)
            if mine is not None and mine.admin:
                return Right.EDIT
        roles = self.access.module_roles(who.person, row["id"]) if ask_id else set()
        if "editor" in roles:
            return Right.EDIT
        visibility = Visibility(row["visibility"])
        if visibility == Visibility.ALL:
            return Right.SEE
        club = row["club_id"]
        if visibility == Visibility.CLUB and club is not None and who.club(club) is not None:
            return Right.SEE
        if "viewer" in roles:
            return Right.SEE
        return None

    def _row(
        self, conn: Connection[DictRow], module: UUID, version: int | None = None
    ) -> dict[str, Any]:
        row = conn.execute(
            f"SELECT {MODULE_COLUMNS} FROM module m JOIN module_version v ON v.module_id = m.id "
            "AND v.version = coalesce(%s, m.latest) WHERE m.id = %s AND m.removed_at IS NULL",
            (version, module),
        ).fetchone()
        if row is None:
            raise not_found()
        return dict(row)

    def _work(
        self, who: Who, module: UUID, need: Right, version: int | None = None
    ) -> tuple[dict[str, Any], Right]:
        with self.db.transaction() as conn:
            row = self._row(conn, module, version)
        right = self._right(who, row)
        if right is None:
            raise not_found()
        if right < need:
            raise forbidden()
        return row, right

    # --- Profiles -----------------------------------------------------------------------------

    def _own_profiles(
        self, conn: Connection[DictRow], ids: Sequence[str]
    ) -> dict[str, GableProfile]:
        if not ids:
            return {}
        rows = conn.execute("SELECT * FROM gable_profile WHERE id = ANY(%s)", (list(ids),))
        return {str(r["id"]): profiles.own_profile(dict(r)) for r in rows.fetchall()}

    def _profiles_for(
        self, conn: Connection[DictRow], gables: Sequence[Sequence[dict[str, Any]]]
    ) -> dict[str, GableProfile]:
        wanted = {
            str(g["profile"])
            for row in gables
            for g in row
            if g.get("profile") and g["profile"] not in profiles.SEEDED_BY_ID
        }
        return {**profiles.SEEDED_BY_ID, **self._own_profiles(conn, sorted(wanted))}

    def _sees_profile(self, who: Who, profile: GableProfile) -> bool:
        if profile.owner is None:
            return True
        if profile.owner.kind == OwnerKind.PERSON:
            return profile.owner.id == who.person
        return who.club(profile.owner.id) is not None

    # --- Building the answers -----------------------------------------------------------------

    @staticmethod
    def _labels(gables: Sequence[Gable], known: dict[str, GableProfile]) -> list[GableLabel]:
        return [
            GableLabel(
                end=g.end,
                label=profiles.label(g, known.get(g.profile) if g.profile else None),
                norm=g.norm,
                profile=g.profile,
                tracks=list(g.tracks),
            )
            for g in gables
        ]

    def _brief(self, row: dict[str, Any], known: dict[str, GableProfile]) -> ModuleBrief:
        gables = [Gable.model_validate(g) for g in row["gables"]]
        version = int(row["version"])
        approved = row["approved_at"] is not None  # this version's own approval
        return ModuleBrief(
            id=row["id"],
            number=f"M-{int(row['number']):03d}",
            name=row["name"],
            owner=Owner(kind=row["owner_kind"], id=row["owner_id"], name=row["owner_name"]),
            visibility=row["visibility"],
            scale=row["scale"],
            shape=row["shape"],
            gables=self._labels(gables, known),
            graph=TrackGraph.model_validate(row["graph"]),
            status=ModuleStatus.APPROVED if approved else ModuleStatus.DRAFT,
            version=version,
            track_length=round(float(row["track_length"]), 1),
            changed_at=row["saved_at"],
        )

    def _module(self, row: dict[str, Any], right: Right, known: dict[str, GableProfile]) -> Module:
        brief = self._brief(row, known)
        return Module(
            **brief.model_dump(),
            club=row["club_id"],
            club_name=row["club_name"],
            approved_version=row["approved_version"],
            approved_at=row["approved_at"],
            approved_by=row["approved_by_name"],
            created_at=row["created_at"],
            may_edit=right >= Right.EDIT,
            latest=int(row["latest"]),
        )

    def _answer(self, who: Who, module: UUID, right: Right, version: int | None = None) -> Module:
        with self.db.transaction() as conn:
            row = self._row(conn, module, version)
            known = self._profiles_for(conn, [row["gables"]])
        return self._module(row, right, known)

    # --- Checking the measures ----------------------------------------------------------------

    def _checked(
        self,
        conn: Connection[DictRow],
        who: Who,
        scale: Scale,
        shape: Shape,
        gables: list[Gable],
        owner: UUID,
    ) -> list[Gable]:
        """The gables as they are saved, with the norm from a norm's profile, or 422 with why."""
        for gable in gables:
            width = geometry.width_at(shape, gable.end.value)
            if gable.tracks and gable.tracks[-1] >= width:
                raise invalid(
                    f"Gavel {gable.end}: spår {len(gable.tracks)} ligger utanför modulen, "
                    f"som är {width:g} mm bred."
                )
        if isinstance(shape, Curve):
            if not gables[0].tracks:
                raise invalid(
                    "En kurvmodul behöver spår 1 vid gavel A: snöret mäts mellan spår 1:s mitt."
                )
            track1 = gables[0].tracks[0]
            edge = geometry.edge_radius(shape, track1)
            inner = edge - shape.width if shape.edge == EdgeSide.OUTER else edge
            if inner <= 0:
                raise invalid("Radien är för liten för modulens bredd.")
            if not geometry.agrees(shape):
                raise invalid("Radien och vinkeln stämmer inte med snöret och pilhöjden.")
        wanted = [g.profile for g in gables if g.profile and g.profile not in profiles.SEEDED_BY_ID]
        own = self._own_profiles(conn, [p for p in wanted if p is not None])
        checked: list[Gable] = []
        for gable in gables:
            if gable.profile is None:
                checked.append(gable)
                continue
            profile = profiles.SEEDED_BY_ID.get(gable.profile) or own.get(gable.profile)
            # The person's own and their clubs' profiles, and the module owner's: an editor
            # keeps the owner's own gables when they change the module.
            mine = profile is not None and profile.owner is not None and profile.owner.id == owner
            if profile is None or not (mine or self._sees_profile(who, profile)):
                raise invalid(f"Gavel {gable.end}: gavelprofilen finns inte.")
            if profile.scale != scale:
                raise invalid(f"Gavel {gable.end}: {profile.name} hör till skala {profile.scale}.")
            why = profiles.check(gable, profile)
            if why is not None:
                raise invalid(why)
            norm = profile.norm if profile.kind == ProfileKind.NORM else gable.norm
            checked.append(gable.model_copy(update={"norm": norm}))
        return checked

    def _club_for(
        self, who: Who, owner: Owner, visibility: Visibility, club: UUID | None
    ) -> tuple[UUID | None, str | None]:
        """The club that sees the module with the visibility klubben."""
        if owner.kind == OwnerKind.CLUB:
            return owner.id, owner.name
        if visibility != Visibility.CLUB:
            return None, None
        if club is None:
            mine = who.clubs()
            if not mine:
                raise invalid("Du är inte med i någon klubb i TrainMeet ID än.")
            if len(mine) != 1:
                raise invalid("Välj vilken klubb som ser modulen.")
            return mine[0].id, mine[0].name
        found = who.club(club)
        if found is None:
            raise invalid("Du är inte med i den klubben.")
        return found.id, found.name

    # --- Libraries and the list ---------------------------------------------------------------

    def libraries(self, who: Who) -> list[Library]:
        found = [Library(id="mine", name="Mitt modulbibliotek", kind="mine", may_add=True)]
        for club in who.clubs():
            found.append(
                Library(
                    id=f"club:{club.id}",
                    name=club.name,
                    kind="club",
                    club=club.id,
                    may_add=club.admin,
                )
            )
        found.append(Library(id="all", name="Alla moduler jag ser", kind="all", may_add=False))
        return found

    def _library(self, who: Who, library: str) -> Library:
        if library == "mine":
            return Library(id="mine", name="Mitt modulbibliotek", kind="mine", may_add=True)
        for choice in self.libraries(who):
            if choice.id == library:
                return choice
        raise Refused(
            404, ProblemCode.NOT_FOUND, "Biblioteket finns inte, eller så ser du det inte."
        )

    def _visible_rows(
        self, who: Who, library: Library, scale: Scale | None
    ) -> list[dict[str, Any]]:
        if library.kind == "mine":
            where = "m.owner_kind = 'person' AND m.owner_id = %s"
            params: list[object] = [who.person]
        elif library.kind == "club":
            where = "(m.owner_id = %s OR (m.visibility = 'club' AND m.club_id = %s))"
            params = [library.club, library.club]
        else:
            clubs = [c.id for c in who.clubs()]
            where = (
                "((m.owner_kind = 'person' AND m.owner_id = %s) OR m.visibility = 'all' "
                "OR m.club_id = ANY(%s) OR m.owner_id = ANY(%s))"
            )
            params = [who.person, clubs, clubs]
        if scale is not None:
            where += " AND v.scale = %s"
            params.append(scale.value)
        with self.db.transaction() as conn:
            rows = conn.execute(
                f"SELECT {MODULE_COLUMNS} FROM module m JOIN module_version v "
                "ON v.module_id = m.id AND v.version = m.latest "
                f"WHERE m.removed_at IS NULL AND {where}",
                params,
            ).fetchall()
        seen = [dict(r) for r in rows if self._right(who, dict(r), ask_id=False) is not None]
        mine_first = lambda r: (  # noqa: E731
            not (r["owner_kind"] == OwnerKind.PERSON and r["owner_id"] == who.person),
            str(r["owner_name"]).lower(),
            int(r["number"]),
        )
        return sorted(seen, key=mine_first)

    def listing(
        self, who: Who, library: str = "mine", scale: Scale | None = None, q: str | None = None
    ) -> ModuleList:
        chosen = self._library(who, library)
        rows = self._visible_rows(who, chosen, scale)
        with self.db.transaction() as conn:
            known = self._profiles_for(conn, [r["gables"] for r in rows])
        briefs = [self._brief(r, known) for r in rows]
        if q and q.strip():
            words = q.strip().lower().split()
            briefs = [
                b
                for b in briefs
                if all(
                    word in " ".join([b.name, b.number, *(g.label for g in b.gables)]).lower()
                    for word in words
                )
            ]
        counts: Counter[tuple[str, str | None]] = Counter(
            (g.label, g.profile) for b in briefs for g in b.gables
        )
        gables = [
            GableCount(label=label, profile=profile, count=count)
            for (label, profile), count in sorted(counts.items(), key=lambda i: (-i[1], i[0][0]))
        ]
        return ModuleList(library=chosen, modules=briefs, gables=gables)

    # --- One module ---------------------------------------------------------------------------

    def create(self, who: Who, new: NewModule) -> Module:
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
                    "Bara klubbens administratör lägger till klubbens moduler.",
                )
            owner = Owner(kind=OwnerKind.CLUB, id=club.id, name=club.name)
        club_id, club_name = self._club_for(who, owner, new.visibility, new.club)
        module = uuid.uuid4()
        with self.db.transaction() as conn:
            gables = self._checked(conn, who, new.scale, new.shape, list(new.gables), owner.id)
            built = graph.from_measures(new.shape, gables)
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (str(owner.id),))
            number = conn.execute(
                "SELECT coalesce(max(number), 0) + 1 AS next FROM module WHERE owner_id = %s",
                (owner.id,),
            ).fetchone()
            assert number is not None
            conn.execute(
                "INSERT INTO module (id, owner_kind, owner_id, owner_name, number, visibility, "
                "club_id, club_name, latest, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, "
                "1, %s)",
                (
                    module,
                    owner.kind.value,
                    owner.id,
                    owner.name,
                    int(number["next"]),
                    new.visibility.value,
                    club_id,
                    club_name,
                    who.person,
                ),
            )
            self._insert_version(
                conn, who, module, 1, new.name, new.scale, new.shape, gables, built
            )
            self._event(conn, who, module, ModuleEventKind.CREATED, 1, "Modulen skapad ur mått")
        return self._answer(who, module, Right.EDIT)

    def _insert_version(
        self,
        conn: Connection[DictRow],
        who: Who,
        module: UUID,
        version: int,
        name: str,
        scale: Scale,
        shape: Shape,
        gables: Sequence[Gable],
        built: TrackGraph,
    ) -> None:
        conn.execute(
            "INSERT INTO module_version (module_id, version, name, scale, shape, gables, graph, "
            "track_length, saved_by, saved_by_name) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s)",
            (
                module,
                version,
                name,
                scale.value,
                json.dumps(shape.model_dump(mode="json")),
                json.dumps([g.model_dump(mode="json") for g in gables]),
                json.dumps(built.model_dump(mode="json")),
                graph.track_length(built),
                who.person,
                who.name,
            ),
        )

    @staticmethod
    def _event(
        conn: Connection[DictRow],
        who: Who,
        module: UUID,
        kind: ModuleEventKind,
        version: int,
        text: str,
    ) -> None:
        conn.execute(
            "INSERT INTO module_event (module_id, kind, version, by_name, text) "
            "VALUES (%s, %s, %s, %s, %s)",
            (module, kind.value, version, who.name, text),
        )

    def read(self, who: Who, module: UUID, version: int | None = None) -> Module:
        _, right = self._work(who, module, Right.SEE)
        if version is not None:
            return self._answer(who, module, right, version)
        return self._answer(who, module, right)

    def save(self, who: Who, module: UUID, change: ModuleChange) -> Module:
        self._work(who, module, Right.EDIT)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT latest FROM module WHERE id = %s AND removed_at IS NULL FOR UPDATE",
                (module,),
            ).fetchone()
            if row is None:
                raise not_found()
            latest = int(row["latest"])
            if change.base != latest:
                raise changed()
            before = self._row(conn, module, latest)
            old_gables = [Gable.model_validate(g) for g in before["gables"]]
            old_graph = TrackGraph.model_validate(before["graph"])
            owner = conn.execute("SELECT owner_id FROM module WHERE id = %s", (module,)).fetchone()
            assert owner is not None
            gables = self._checked(
                conn, who, change.scale, change.shape, list(change.gables), owner["owner_id"]
            )
            built = graph.from_measures(change.shape, gables, (old_graph, old_gables))
            version = latest + 1
            self._insert_version(
                conn, who, module, version, change.name, change.scale, change.shape, gables, built
            )
            conn.execute("UPDATE module SET latest = %s WHERE id = %s", (version, module))
            what = self._what_changed(before, change, gables)
            self._event(
                conn, who, module, ModuleEventKind.SAVED, version, f"Version {version}: {what}"
            )
        return self._answer(who, module, Right.EDIT)

    @staticmethod
    def _what_changed(before: dict[str, Any], change: ModuleChange, gables: Sequence[Gable]) -> str:
        parts: list[str] = []
        if before["name"] != change.name:
            parts.append("namnet")
        if before["scale"] != change.scale.value:
            parts.append("skalan")
        if before["shape"] != change.shape.model_dump(mode="json"):
            parts.append("formen och måtten")
        for old, new in zip(before["gables"], gables, strict=True):
            if Gable.model_validate(old) != new:
                parts.append(f"gavel {new.end.value}")
        if not parts:
            return "sparad utan ändringar"
        listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " och " + parts[-1]
        return f"{listed} ändrade" if len(parts) > 1 or parts[0] != "namnet" else "namnet ändrat"

    def history(self, who: Who, module: UUID) -> list[ModuleEvent]:
        self._work(who, module, Right.SEE)
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT at, kind, version, by_name, text FROM module_event WHERE module_id = %s "
                "ORDER BY at DESC, id DESC",
                (module,),
            ).fetchall()
        return [
            ModuleEvent(
                at=r["at"], kind=r["kind"], version=r["version"], by=r["by_name"], text=r["text"]
            )
            for r in rows
        ]

    def approve(self, who: Who, module: UUID, approval: ModuleApproval) -> Module:
        self._work(who, module, Right.EDIT)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT latest FROM module WHERE id = %s AND removed_at IS NULL FOR UPDATE",
                (module,),
            ).fetchone()
            if row is None:
                raise not_found()
            if approval.version != int(row["latest"]):
                raise changed()
            conn.execute(
                "UPDATE module_version SET approved_at = now(), approved_by_name = %s "
                "WHERE module_id = %s AND version = %s AND approved_at IS NULL",
                (who.name, module, approval.version),
            )
            conn.execute(
                "UPDATE module SET approved_version = %s WHERE id = %s", (approval.version, module)
            )
            self._event(
                conn,
                who,
                module,
                ModuleEventKind.APPROVED,
                approval.version,
                f"Version {approval.version} godkänd",
            )
        return self._answer(who, module, Right.EDIT)

    def set_visibility(self, who: Who, module: UUID, change: VisibilityChange) -> Module:
        row, _ = self._work(who, module, Right.EDIT)
        owner = Owner(kind=row["owner_kind"], id=row["owner_id"], name=row["owner_name"])
        club_id, club_name = self._club_for(who, owner, change.visibility, change.club)
        text = VISIBILITY_TEXT[change.visibility]
        if change.visibility == Visibility.CLUB and club_name:
            text += f" · {club_name}"
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE module SET visibility = %s, club_id = %s, club_name = %s WHERE id = %s",
                (change.visibility.value, club_id, club_name, module),
            )
            self._event(
                conn,
                who,
                module,
                ModuleEventKind.VISIBILITY,
                int(row["latest"]),
                f"Vem ser modulen: {text}",
            )
        return self._answer(who, module, Right.EDIT)

    def remove(self, who: Who, module: UUID) -> ModuleRemoved:
        row, _ = self._work(who, module, Right.EDIT)
        with self.db.transaction() as conn:
            conn.execute("UPDATE module SET removed_at = now() WHERE id = %s", (module,))
            self._event(
                conn, who, module, ModuleEventKind.REMOVED, int(row["latest"]), "Modulen borttagen"
            )
        return ModuleRemoved(id=module)

    # --- Gable profiles -----------------------------------------------------------------------

    def profile_list(self, who: Who, scale: Scale) -> ProfileList:
        clubs = [c.id for c in who.clubs()]
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM gable_profile WHERE scale = %s AND (owner_id = %s "
                "OR owner_id = ANY(%s)) ORDER BY lower(name)",
                (scale.value, who.person, clubs),
            ).fetchall()
        own = [profiles.own_profile(dict(r)) for r in rows]
        visible = self._visible_rows(
            who, Library(id="all", name="Alla", kind="all", may_add=False), scale
        )
        uses: Counter[str] = Counter(
            str(g["profile"]) for r in visible for g in r["gables"] if g.get("profile")
        )
        found = [p for p in profiles.SEEDED if p.scale == scale] + own
        return ProfileList(
            scale=scale,
            norms=profiles.norms_in(scale),
            profiles=[p.model_copy(update={"uses": uses[p.id]}) for p in found],
        )

    def new_profile(self, who: Who, new: NewProfile) -> GableProfile:
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
                    "Bara klubbens administratör gör klubbens gavelprofiler.",
                )
            owner = Owner(kind=OwnerKind.CLUB, id=club.id, name=club.name)
        if new.norm == Norm.CLUB and owner.kind != OwnerKind.CLUB:
            raise invalid(f"{NORM_NAMES[new.norm]} norm hör till en klubb.")
        profile = f"egen-{uuid.uuid4().hex[:12]}"
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO gable_profile (id, owner_kind, owner_id, owner_name, name, scale, "
                "norm, positions, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    profile,
                    owner.kind.value,
                    owner.id,
                    owner.name,
                    new.name,
                    new.scale.value,
                    new.norm.value if new.norm else None,
                    json.dumps(list(new.tracks)),
                    who.person,
                ),
            )
            row = conn.execute("SELECT * FROM gable_profile WHERE id = %s", (profile,)).fetchone()
        assert row is not None
        return profiles.own_profile(dict(row))
