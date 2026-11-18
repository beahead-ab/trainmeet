"""Vem får göra vad i Hubben (#78).

- Hubbens PIN (H18): the hub's own administrator, who may do everything.
- Insläppt med engångskod (H56): Trafikledare in the meet that runs, and only there.
- Inloggad med TrainMeet ID: the roles at the meet come from ID, asked at every call (C35,
  hub/id_roles.py). On a meet's Pi they come from ID's signed ticket (KONTO-11, KONTO-37,
  hub/pi_login.py). The hub's meet is linked to ID's meet (Meet.id_meet, ID10). Administratör
  and Arrangör plan the meet; Administratör and the Arrangör with Får publicera publish it;
  only Administratör withdraws a version (PLAN-19, PLAN-24). Läsare looks at the plan and
  changes nothing (H16), which is what everyone may in Planering (S1, PLAN-37). Administratör
  and Trafikledare run it in Drift (ID3). A meet that is not linked to ID has no roles from ID:
  only the PIN plans it.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import HTTPException

from hub.id_roles import PLANS, RUNS, IdRoles, publishes, withdraws
from hub.local import ADMIN, DISPATCHER, PERSON, LocalLogin

NOT_LOGGED_IN = "Logga in med hubbens PIN-kod eller med TrainMeet ID."
NO_ROLE = "Du har ingen roll på den här träffen i TrainMeet ID."
NO_PUBLISHING = (
    "Du får inte publicera den här träffen. Klubbens administratör ger rätten i TrainMeet ID."
)
NO_WITHDRAWING = "Bara klubbens administratör drar tillbaka en version."
NOT_FOR_YOUR_ROLE = "Din roll på träffen i TrainMeet ID ger inte rätt att ändra planen."


class Rights:
    def __init__(self, login: LocalLogin, roles: IdRoles | None = None) -> None:
        self.login = login
        self.roles = roles

    def id_roles(self, token: str | None, id_meet: UUID | None) -> set[str]:
        """The roles ID gives the one logged in with ID at the meet, as ID says now. On a
        meet's Pi, with no ID to ask, the roles in the ticket the session began with: a role
        taken back in ID holds until the ticket runs out (KONTO-37)."""
        if id_meet is None:
            return set()
        person = self.login.person(token)
        if person is None:
            return set()
        if self.roles is None:
            from_ticket = self.login.ticket_roles(token) or {}
            return set(from_ticket.get(str(id_meet), set()))
        return self.roles.at_meet(person.id, id_meet)

    def may_plan(self, token: str | None, id_meet: UUID | None) -> bool:
        if self.login.valid(token):
            return True
        if self.login.role(token) != PERSON:
            return False
        return bool(self.id_roles(token, id_meet) & PLANS)

    def may_publish(self, token: str | None, id_meet: UUID | None) -> bool:
        if self.login.valid(token):
            return True
        if self.login.role(token) != PERSON:
            return False
        return publishes(self.id_roles(token, id_meet))

    def may_withdraw(self, token: str | None, id_meet: UUID | None) -> bool:
        if self.login.valid(token):
            return True
        if self.login.role(token) != PERSON:
            return False
        return withdraws(self.id_roles(token, id_meet))

    def may_run(self, token: str | None, run: str | None, id_meet: UUID | None) -> bool:
        role = self.login.role(token, run)
        if role in (ADMIN, DISPATCHER):
            return True
        return role == PERSON and bool(self.id_roles(token, id_meet) & RUNS)

    def require_planner(self, token: str | None, id_meet: UUID | None) -> None:
        """Planering: the PIN, or Administratör or Arrangör at the meet in ID (PLAN-19)."""
        self._require(token, id_meet, lambda roles: bool(roles & PLANS), NOT_FOR_YOUR_ROLE)

    def require_publisher(self, token: str | None, id_meet: UUID | None) -> None:
        """Publicera: the PIN, Administratör, or the Arrangör with Får publicera (PLAN-24)."""
        self._require(token, id_meet, publishes, NO_PUBLISHING)

    def require_withdrawer(self, token: str | None, id_meet: UUID | None) -> None:
        """Dra tillbaka: the PIN or Administratör (PLAN-24)."""
        self._require(token, id_meet, withdraws, NO_WITHDRAWING)

    def _require(
        self,
        token: str | None,
        id_meet: UUID | None,
        allows: Callable[[set[str]], bool],
        planner_told: str,
    ) -> None:
        """The roles asked of ID once: allowed, or why not. Someone with a role at the meet is
        told what the role does not give; a planner, what is missing (PLAN-24)."""
        if self.login.valid(token):
            return
        if self.login.role(token) != PERSON:
            self._refuse(token)
        roles = self.id_roles(token, id_meet)
        if allows(roles):
            return
        if roles & PLANS:
            raise HTTPException(403, planner_told)
        if roles:
            raise HTTPException(403, NOT_FOR_YOUR_ROLE)
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
