"""Vem får göra vad i Hubben (#78).

- Hubbens PIN (H18): the hub's own administrator, who may do everything.
- Insläppt med engångskod (H56): Trafikledare in the meet that runs, and only there.
- Inloggad med TrainMeet ID: the roles at the meet come from ID, asked at every call (C35,
  hub/id_roles.py). The hub's meet is linked to ID's meet (Meet.id_meet, ID10). Administratör
  and Arrangör plan the meet and publish it (PLAN-19); Administratör and Trafikledare run it in
  Drift (ID3). A meet that is not linked to ID has no roles from ID: only the PIN plans it.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException

from hub.id_roles import PLANS, RUNS, IdRoles
from hub.local import ADMIN, DISPATCHER, PERSON, LocalLogin

NOT_LOGGED_IN = "Logga in med hubbens PIN-kod eller med TrainMeet ID."
NO_ROLE = "Du har ingen roll på den här träffen i TrainMeet ID."


class Rights:
    def __init__(self, login: LocalLogin, roles: IdRoles | None = None) -> None:
        self.login = login
        self.roles = roles

    def id_roles(self, token: str | None, id_meet: UUID | None) -> set[str]:
        """The roles ID gives the one logged in with ID at the meet, as ID says now."""
        if self.roles is None or id_meet is None:
            return set()
        person = self.login.person(token)
        if person is None:
            return set()
        return self.roles.at_meet(person.id, id_meet)

    def may_plan(self, token: str | None, id_meet: UUID | None) -> bool:
        if self.login.valid(token):
            return True
        if self.login.role(token) != PERSON:
            return False
        return bool(self.id_roles(token, id_meet) & PLANS)

    def may_run(self, token: str | None, run: str | None, id_meet: UUID | None) -> bool:
        role = self.login.role(token, run)
        if role in (ADMIN, DISPATCHER):
            return True
        return role == PERSON and bool(self.id_roles(token, id_meet) & RUNS)

    def require_planner(self, token: str | None, id_meet: UUID | None) -> None:
        """Planering: the PIN, or Administratör or Arrangör at the meet in ID (PLAN-19)."""
        if self.may_plan(token, id_meet):
            return
        self._refuse(token)

    def require_runner(self, token: str | None, run: str | None, id_meet: UUID | None) -> None:
        """Drift: the PIN, let in as Trafikledare (H56), or Administratör or Trafikledare at the
        meet in ID (ID3)."""
        if self.may_run(token, run, id_meet):
            return
        self._refuse(token)

    def _refuse(self, token: str | None) -> None:
        if self.login.role(token) == PERSON:
            raise HTTPException(403, NO_ROLE)
        raise HTTPException(401, NOT_LOGGED_IN)
